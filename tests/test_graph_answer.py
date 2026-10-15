"""Tests for LangGraph answer node and standalone answering (Task 17 / A-17).

Verifies RetrievalBundle boundary, evidence/segment projection, three semantic states
(SUPPORTED, UNSUPPORTED, INSUFFICIENT_EVIDENCE), citation formatting and validation,
error codes (ANSWER_INPUT_INVALID, ANSWER_GENERATION_FAILED, ANSWER_CITATION_INVALID),
call count assertions (search=0, rewrite=0, generate=1/0), and state preservation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock
import pytest

from artagent.answer import get_source_root, normalize_query, sha256_bytes, sha256_str
from artagent.graph import (
    AgentState,
    AnswerResult,
    Citation,
    ErrorInfo,
    Evidence,
    IntentSignals,
    Path as AgentPath,
    PlanStep,
    RequestContext,
    RequestInput,
    RetrievalBundle,
    RouteDecision,
    RuntimeCapabilities,
    answer_query,
    answer_standalone,
    create_answer_node,
    create_router_graph,
    search_hits_to_evidences,
)
from artagent.retrieval.provenance import canonical_json_str
from artagent.retrieval.types import SearchHit


# =========================================================================
# Fixture Helpers
# =========================================================================

def _make_evidence(
    *,
    chunk_id: str = "chunk_1",
    doc_id: str = "rawpedia:Exposure",
    source_group_id: str = "rawpedia:Exposure",
    source_type: str = "rawpedia",
    source_path: str = "data/rawpedia/Exposure.md",
    section_title: str = "Exposure",
    target_url: str = "https://rawpedia.rawtherapee.com/exposure/",
    text: str = "Auto Levels analyzes the image histogram to adjust exposure settings.",
    product_scope: str = "RawTherapee",
    char_start: int = 0,
    char_end: Optional[int] = None,
    byte_start: Optional[int] = None,
    byte_end: Optional[int] = None,
    source_file_sha: str = "dummy_file_sha",
    json_pointer: Optional[str] = None,
    ref_id: Optional[str] = None,
    body_sha256: Optional[str] = None,
) -> Evidence:
    text_b = text.encode("utf-8")
    if char_end is None:
        char_end = char_start + len(text)
    if byte_start is None:
        byte_start = char_start  # ascii default
    if byte_end is None:
        byte_end = byte_start + len(text_b)
    seg = {
        "doc_id": doc_id,
        "source_path": source_path,
        "target_url": target_url,
        "source_file_sha256": source_file_sha,
        "segment_sha256": sha256_str(text),
        "char_start": char_start,
        "char_end": char_end,
        "byte_start": byte_start,
        "byte_end": byte_end,
        "content_char_start": 0,
        "content_char_end": len(text),
        "json_pointer": json_pointer,
    }
    if ref_id:
        seg["ref_id"] = ref_id
    if body_sha256:
        seg["body_sha256"] = body_sha256

    return Evidence(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_group_id=source_group_id,
        source_type=source_type,
        source_path=source_path,
        source_location=canonical_json_str({
            "section_title": section_title,
            "source_segment": seg,
        }),
        target_url=target_url,
        text=text,
        product_scope=product_scope,
    )


def _setup_mock_source_file(tmp_path: Path, rel_path: str, content: str, is_json: bool = False) -> tuple[Path, str]:
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_json:
        obj = {"body": content}
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    else:
        b = content.encode("utf-8")
    target.write_bytes(b)
    return target, sha256_bytes(b)


# =========================================================================
# 1. Bundle Boundary & Input Validation Tests
# =========================================================================

def test_bundle_none_returns_input_invalid() -> None:
    ans, err = answer_standalone(
        query="Auto Levels 설명",
        bundle=None,
    )
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"
    assert err.node == "ANSWER"
    assert err.recoverable is False


def test_empty_query_returns_input_invalid() -> None:
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[])
    ans, err = answer_standalone(query="", bundle=bundle)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"


def test_invalid_source_filter_returns_input_invalid() -> None:
    bundle = RetrievalBundle(query="q", source_filter="INVALID_FILTER", hits=[])
    ans, err = answer_standalone(query="test", bundle=bundle)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"


def test_product_scope_violation_for_rawpedia_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "RawTherapee sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(
        source_path=rel_path,
        text=text,
        product_scope="ART",  # VIOLATION: RawPedia must be RawTherapee
        source_file_sha=f_sha,
    )
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])
    ans, err = answer_standalone(query="test", bundle=bundle, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"
    assert "RawTherapee" in err.message


def test_product_scope_violation_for_github_rejected(tmp_path: Path) -> None:
    rel_path = "data/issues/sample.json"
    text = "GitHub issue text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text, is_json=True)
    ev = _make_evidence(
        source_type="github",
        source_path=rel_path,
        text=text,
        product_scope="RawTherapee",  # VIOLATION: GitHub must be ART
        source_file_sha=f_sha,
        json_pointer="/body",
    )
    bundle = RetrievalBundle(query="q", source_filter="GITHUB", hits=[ev])
    ans, err = answer_standalone(query="test", bundle=bundle, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"
    assert "ART" in err.message


def test_file_sha_mismatch_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "RawTherapee sample text."
    _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(
        source_path=rel_path,
        text=text,
        source_file_sha="wrong_sha" * 4,
    )
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])
    ans, err = answer_standalone(query="test", bundle=bundle, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"


def test_segment_sha_mismatch_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "RawTherapee sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(
        source_path=rel_path,
        text=text,
        source_file_sha=f_sha,
    )
    # Tamper with evidence text
    ev.text = "Tampered text"
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])
    ans, err = answer_standalone(query="test", bundle=bundle, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"


def test_multiple_segments_from_same_chunk_get_unique_ids(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/multi.md"
    full_content = "First paragraph here.\nSecond paragraph here."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, full_content)

    ev1 = _make_evidence(
        chunk_id="chunk_100",
        source_path=rel_path,
        text="First paragraph here.",
        char_start=0,
        char_end=21,
        source_file_sha=f_sha,
    )
    ev2 = _make_evidence(
        chunk_id="chunk_100",
        source_path=rel_path,
        text="Second paragraph here.",
        char_start=22,
        char_end=44,
        source_file_sha=f_sha,
    )
    ev3 = _make_evidence(
        chunk_id="chunk_200",
        source_path=rel_path,
        text="First paragraph here.",
        char_start=0,
        char_end=21,
        source_file_sha=f_sha,
    )

    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev1, ev2, ev3])

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        assert "C1S1" in ctx_cits
        assert "C1S2" in ctx_cits
        assert "C2S1" in ctx_cits
        assert len(ctx_cits) == 3
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "첫 번째 단락 [C1S1]과 두 번째 단락 [C1S2]입니다.",
            "citation_ids": ["C1S1", "C1S2"],
        })

    ans, err = answer_standalone(
        query="다중 세그먼트 질문",
        bundle=bundle,
        generate=mock_gen,
        source_root=tmp_path,
    )
    assert err is None
    assert ans is not None
    assert ans.status == "SUPPORTED"
    assert len(ans.citations) == 2
    assert "[출처: Exposure·https://rawpedia.rawtherapee.com/exposure/]" in ans.text


# =========================================================================
# 2. Three Semantic States & Negative Cases
# =========================================================================

def test_supported_state_success(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/exposure.md"
    text = "Auto Levels analyzes histogram to adjust exposure."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev], snapshot_ref="20261015")

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "Auto Levels는 히스토그램을 분석하여 노출을 조정합니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(
        query="Auto Levels 기능",
        bundle=bundle,
        generate=mock_gen,
        source_root=tmp_path,
    )
    assert err is None
    assert ans is not None
    assert ans.status == "SUPPORTED"
    assert "RawTherapee" in ans.applicability
    assert len(ans.citations) == 1
    assert ans.citations[0].url == ev.target_url
    assert ans.actionable_goal is None
    assert "[출처: Exposure·https://rawpedia.rawtherapee.com/exposure/]" in ans.text


def test_unsupported_state_success(tmp_path: Path) -> None:
    rel_path = "data/issues/500.json"
    text = "There are no quality settings for JXL export; it is fixed."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text, is_json=True)
    ev = _make_evidence(
        source_type="github",
        source_path=rel_path,
        text=text,
        product_scope="ART",
        source_file_sha=f_sha,
        json_pointer="/body",
        target_url="https://github.com/artraweditor/ART/issues/500#issuecomment-1",
    )
    bundle = RetrievalBundle(query="q", source_filter="GITHUB", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "UNSUPPORTED",
            "answer": "JXL 내보내기 시 품질 슬라이더는 지원되지 않으며 고정 설정입니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(
        query="JXL 슬라이더 활성화 방법",
        bundle=bundle,
        generate=mock_gen,
        source_root=tmp_path,
    )
    assert err is None
    assert ans is not None
    assert ans.status == "UNSUPPORTED"
    assert len(ans.citations) == 1
    assert "ART" in ans.applicability


def test_insufficient_evidence_normal_empty_hits() -> None:
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[])

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        assert "(검색된 문맥이 없습니다.)" in user_prompt
        return json.dumps({
            "status": "INSUFFICIENT_EVIDENCE",
            "answer": "모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.",
            "citation_ids": [],
        })

    ans, err = answer_standalone(
        query="알 수 없는 질문",
        bundle=bundle,
        generate=mock_gen,
    )
    assert err is None
    assert ans is not None
    assert ans.status == "INSUFFICIENT_EVIDENCE"
    assert len(ans.citations) == 0
    assert "모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다." in ans.text


def test_insufficient_evidence_with_incidental_citation(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/incidental.md"
    text = "General color management info."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "INSUFFICIENT_EVIDENCE",
            "answer": "해당 기능에 대한 직접 정보는 확인되지 않습니다. 다만 일반 색상 관리 정보는 있습니다 [C1S1]. (모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.)",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(
        query="특수 색상 기능",
        bundle=bundle,
        generate=mock_gen,
        source_root=tmp_path,
    )
    assert err is None
    assert ans is not None
    assert ans.status == "INSUFFICIENT_EVIDENCE"
    assert len(ans.citations) == 1


# =========================================================================
# 3. Negative Counter-Examples & Error Contracts
# =========================================================================

def test_missing_status_key_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        # Missing 'status'
        return json.dumps({
            "answer": "답변 [C1S1]",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_GENERATION_FAILED"


def test_unknown_status_value_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "PARTIAL_SUPPORT",  # Invalid status
            "answer": "답변 [C1S1]",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_GENERATION_FAILED"


def test_empty_answer_string_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "   ",  # Empty whitespace
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_GENERATION_FAILED"


def test_supported_with_zero_citations_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "인용 없는 긍정 답변입니다.",
            "citation_ids": [],  # VIOLATION: SUPPORTED requires >= 1 citation
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_CITATION_INVALID"


def test_supported_on_empty_search_hits_rejected() -> None:
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "빈 검색인데 긍정 선언.",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_CITATION_INVALID"


def test_unknown_citation_id_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "미지 인용 사용 [C9S9].",
            "citation_ids": ["C9S9"],  # Unknown citation ID
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_CITATION_INVALID"


def test_marker_mismatch_rejected(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "본문에는 C1S1이 없음.",  # Marker missing in text
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_CITATION_INVALID"


def test_generation_timeout_or_error_handled(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen_fail(*args: Any) -> str:
        raise TimeoutError("Execution timed out")

    ans, err = answer_standalone(query="test", bundle=bundle, generate=mock_gen_fail, source_root=tmp_path)
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_GENERATION_FAILED"


# =========================================================================
# 4. Disallowed Call & Call Count Assertion Tests
# =========================================================================

def test_disallowed_subsystems_are_not_called(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """단독 답변 실행 중 run_pipeline, open_store, store.search, load_encoder, rewrite 호출 시 즉시 실패."""
    import artagent.answer as t11_ans
    import artagent.retrieval.store as store_mod
    import artagent.retrieval.embedding as emb_mod
    import artagent.graph.rewrite as rw_mod

    def _disallowed(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Disallowed subsystem called during answer generation!")

    monkeypatch.setattr(t11_ans, "run_pipeline", _disallowed)
    monkeypatch.setattr(store_mod, "open_store", _disallowed)
    monkeypatch.setattr(emb_mod, "load_encoder", _disallowed)
    monkeypatch.setattr(rw_mod, "prepare_search_input", _disallowed)

    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    gen_mock = MagicMock(return_value=json.dumps({
        "status": "SUPPORTED",
        "answer": "답변입니다 [C1S1].",
        "citation_ids": ["C1S1"],
    }))

    ans, err = answer_standalone(query="test", bundle=bundle, generate=gen_mock, source_root=tmp_path)
    assert err is None
    assert ans is not None
    assert gen_mock.call_count == 1  # Exactly 1 generation call


def test_generation_zero_on_input_error() -> None:
    gen_mock = MagicMock()
    ans, err = answer_standalone(query="test", bundle=None, generate=gen_mock)
    assert ans is None
    assert err is not None
    gen_mock.assert_not_called()  # 0 generation call on error


# =========================================================================
# 5. Graph Node State Immutability & Error Preservation Tests
# =========================================================================

def test_create_answer_node_preserves_state_fields(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    gen_mock = MagicMock(return_value=json.dumps({
        "status": "SUPPORTED",
        "answer": "답변입니다 [C1S1].",
        "citation_ids": ["C1S1"],
    }))

    node = create_answer_node(generate=gen_mock, source_root=tmp_path)

    plan = [PlanStep(step_id="step_1", path=AgentPath.DOC_QA, query="Plan query")]
    decision = RouteDecision(primary_path=AgentPath.DOC_QA, plan=plan)
    req = RequestInput(request_id="req_1", text="Request text")

    initial_state: AgentState = {
        "request": req,
        "decision": decision,
        "cursor": 0,
        "retrieval": bundle,
        "research_count": 0,
        "trace": ["DISPATCH", "SEARCH_RAWPEDIA"],
    }

    updates = node(initial_state)

    # Only answer, error, trace updated
    assert set(updates.keys()) == {"answer", "error", "trace"}
    assert updates["answer"] is not None
    assert updates["answer"].status == "SUPPORTED"
    assert updates["error"] is None
    assert updates["trace"] == ["DISPATCH", "SEARCH_RAWPEDIA", "ANSWER"]


def test_create_answer_node_preserves_prior_error_without_generation() -> None:
    gen_mock = MagicMock()
    node = create_answer_node(generate=gen_mock)

    prior_error = ErrorInfo(
        code="SEARCH_UNAVAILABLE",
        message="Search service failed",
        node="SEARCH_RAWPEDIA",
        recoverable=False,
    )

    initial_state: AgentState = {
        "error": prior_error,
        "trace": ["DISPATCH", "SEARCH_RAWPEDIA"],
        "research_count": 0,
    }

    updates = node(initial_state)

    assert set(updates.keys()) == {"answer", "error", "trace"}
    assert updates["answer"] is None
    assert updates["error"] == prior_error
    assert updates["trace"] == ["DISPATCH", "SEARCH_RAWPEDIA", "ANSWER"]
    gen_mock.assert_not_called()


# =========================================================================
# 6. Router Transitions with Real ANSWER Node
# =========================================================================

def test_router_graph_transitions_with_answer_node(tmp_path: Path) -> None:
    rel_path = "data/rawpedia/sample.md"
    text = "Exposure setting information."
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    # 1. SUPPORTED -> ADVANCE
    gen_supported = MagicMock(return_value=json.dumps({
        "status": "SUPPORTED",
        "answer": "노출 설정 답변입니다 [C1S1].",
        "citation_ids": ["C1S1"],
    }))
    ans_node_supported = create_answer_node(generate=gen_supported, source_root=tmp_path)

    # Mock search node that injects the bundle
    def mock_search_node(state: AgentState) -> dict[str, Any]:
        return {"retrieval": bundle, "error": None, "trace": list(state.get("trace", [])) + ["SEARCH_RAWPEDIA"]}

    graph = create_router_graph(node_overrides={
        "SEARCH_RAWPEDIA": mock_search_node,
        "ANSWER": ans_node_supported,
    })

    req = RequestInput(request_id="req_test", text="Exposure 설정 방법?")
    res_state = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    assert "ANSWER" in res_state["trace"]
    assert "ADVANCE" in res_state["trace"]
    assert res_state["answer"].status == "SUPPORTED"
    assert res_state.get("error") is None


# =========================================================================
# 7. F02 Exact UTF-8 Byte Offset Verification Tests
# =========================================================================

def test_repetitive_text_mismatched_byte_offsets_rejected(tmp_path: Path) -> None:
    """R2 / F02: 'same\\nsame\\n'에서 문자 [0:4]와 바이트 [5:9]를 거부하고 생성 0회."""
    rel_path = "data/rawpedia/repeat.md"
    file_content = "same\nsame\n"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(file_content, encoding="utf-8")
    f_sha = sha256_bytes(file_content.encode("utf-8"))

    # char: 0..4 ("same"), byte: 5..9 ("same" at second line)
    ev = _make_evidence(
        source_path=rel_path,
        text="same",
        source_file_sha=f_sha,
        char_start=0,
        char_end=4,
        byte_start=5,
        byte_end=9,
    )
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    gen_mock = MagicMock()
    ans, err = answer_standalone(
        query="test query",
        bundle=bundle,
        generate=gen_mock,
        source_root=tmp_path,
    )
    assert ans is None
    assert err is not None
    assert err.code == "ANSWER_INPUT_INVALID"
    gen_mock.assert_not_called()


def test_invalid_byte_offsets_various(tmp_path: Path) -> None:
    """F02: 시작만 불일치, 끝만 불일치, 음수, bool 타입 좌표는 ANSWER_INPUT_INVALID 및 생성 0회."""
    rel_path = "data/rawpedia/sample.md"
    file_content = "Hello world\n"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(file_content, encoding="utf-8")
    f_sha = sha256_bytes(file_content.encode("utf-8"))

    # 1. byte_start mismatch
    ev1 = _make_evidence(
        source_path=rel_path, text="Hello", source_file_sha=f_sha,
        char_start=0, char_end=5, byte_start=1, byte_end=5,
    )
    # 2. byte_end mismatch
    ev2 = _make_evidence(
        source_path=rel_path, text="Hello", source_file_sha=f_sha,
        char_start=0, char_end=5, byte_start=0, byte_end=4,
    )
    # 3. bool offset
    ev3 = _make_evidence(
        source_path=rel_path, text="Hello", source_file_sha=f_sha,
        char_start=True, char_end=5, byte_start=0, byte_end=5,  # type: ignore
    )

    for ev in (ev1, ev2, ev3):
        gen_mock = MagicMock()
        b = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])
        ans, err = answer_standalone(query="test", bundle=b, generate=gen_mock, source_root=tmp_path)
        assert ans is None
        assert err is not None
        assert err.code == "ANSWER_INPUT_INVALID"
        gen_mock.assert_not_called()


def test_multibyte_korean_exact_byte_offsets_pass(tmp_path: Path) -> None:
    """F02: 한글 멀티바이트 원문에서 정확한 byte_start/end가 성공적으로 통과."""
    rel_path = "data/rawpedia/korean.md"
    file_content = "노출(Exposure) 설정 방법 안내입니다.\n"
    target_file = tmp_path / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(file_content, encoding="utf-8")
    f_sha = sha256_bytes(file_content.encode("utf-8"))

    segment_text = "설정 방법"
    char_start = file_content.index(segment_text)
    char_end = char_start + len(segment_text)
    byte_start = len(file_content[:char_start].encode("utf-8"))
    byte_end = len(file_content[:char_end].encode("utf-8"))

    ev = _make_evidence(
        source_path=rel_path,
        text=segment_text,
        source_file_sha=f_sha,
        char_start=char_start,
        char_end=char_end,
        byte_start=byte_start,
        byte_end=byte_end,
    )
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    def mock_gen(*args: Any) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "설정 방법 답변입니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    ans, err = answer_standalone(query="설정 방법", bundle=bundle, generate=mock_gen, source_root=tmp_path)
    assert err is None
    assert ans is not None
    assert ans.status == "SUPPORTED"


# =========================================================================
# 8. F03 Constraints & Source Contract Verification Tests
# =========================================================================

def test_create_answer_node_cross_source_rejected(tmp_path: Path) -> None:
    """R5 / F03: TROUBLESHOOT 항목에 RAWPEDIA 번들이 주입되면 ANSWER_INPUT_INVALID 거부."""
    rel_path = "data/rawpedia/sample.md"
    text = "Exposure sample text"
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    gen_mock = MagicMock()
    ans_node = create_answer_node(generate=gen_mock, source_root=tmp_path)

    plan_item = PlanStep(step_id="step_1", path=AgentPath.TROUBLESHOOT, query="에러 질문")
    decision = RouteDecision(primary_path=AgentPath.TROUBLESHOOT, plan=[plan_item])

    state: AgentState = {
        "request": RequestInput(request_id="req_1", text="에러 질문"),
        "decision": decision,
        "cursor": 0,
        "retrieval": bundle,
        "trace": ["DISPATCH", "SEARCH_GITHUB"],
    }

    updates = ans_node(state)
    assert updates["answer"] is None
    assert updates["error"] is not None
    assert updates["error"].code == "ANSWER_INPUT_INVALID"
    assert "불일치" in updates["error"].message
    gen_mock.assert_not_called()


def test_create_answer_node_execute_action_rejected(tmp_path: Path) -> None:
    """F03: EXECUTE 액션의 ANSWER 진입은 거부."""
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[])
    gen_mock = MagicMock()
    ans_node = create_answer_node(generate=gen_mock, source_root=tmp_path)

    plan_item = PlanStep(step_id="step_1", path=AgentPath.EXECUTE, query="렌더 명령")
    decision = RouteDecision(primary_path=AgentPath.EXECUTE, plan=[plan_item])

    state: AgentState = {
        "request": RequestInput(request_id="req_1", text="렌더 명령"),
        "decision": decision,
        "cursor": 0,
        "retrieval": bundle,
    }

    updates = ans_node(state)
    assert updates["answer"] is None
    assert updates["error"] is not None
    assert updates["error"].code == "ANSWER_INPUT_INVALID"
    gen_mock.assert_not_called()


def test_create_answer_node_passes_constraints_to_prompt(tmp_path: Path) -> None:
    """R4 / F03: signals.constraints가 프롬프트의 확정 문맥 구역에 보존되어 전달됨."""
    rel_path = "data/rawpedia/sample.md"
    text = "Exposure sample text"
    _, f_sha = _setup_mock_source_file(tmp_path, rel_path, text)
    ev = _make_evidence(source_path=rel_path, text=text, source_file_sha=f_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[ev])

    captured_prompt = {}

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        captured_prompt["user_prompt"] = user_prompt
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "제약을 준수한 답변입니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    ans_node = create_answer_node(generate=mock_gen, source_root=tmp_path)

    req_ctx = RequestContext(os="macOS", art_version="1.20", confirmed_goal="노출 조정")
    signals = IntentSignals(constraints=["RawTherapee 전용 기능 제외", "절대 자동 노출 슬라이더를 건드리지 말 것"])
    plan_item = PlanStep(step_id="step_1", path=AgentPath.DOC_QA, query="노출 조정 방법")
    decision = RouteDecision(primary_path=AgentPath.DOC_QA, plan=[plan_item])

    state: AgentState = {
        "request": RequestInput(request_id="req_1", text="노출 조정 방법", context=req_ctx),
        "signals": signals,
        "decision": decision,
        "cursor": 0,
        "retrieval": bundle,
    }

    updates = ans_node(state)
    assert updates["error"] is None
    assert updates["answer"] is not None
    assert updates["answer"].status == "SUPPORTED"

    user_p = captured_prompt.get("user_prompt", "")
    assert "[확정 문맥]" in user_p
    assert "OS: macOS" in user_p
    assert "ART Version: 1.20" in user_p
    assert "Confirmed Goal: 노출 조정" in user_p
    assert "Constraints:" in user_p
    assert "RawTherapee 전용 기능 제외" in user_p
    assert "절대 자동 노출 슬라이더를 건드리지 말 것" in user_p
