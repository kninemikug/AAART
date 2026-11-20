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


YELLOW_CAST_QUESTION = "사진이 노랗게 나와요. White Balance에서 무엇부터 조정해야 하나요?"
_REPLAY_ROOT = Path(__file__).resolve().parents[1]
_MINIMAX_TEMPERATURE_REPLAY = json.loads(
    (_REPLAY_ROOT / "data/eval/rag-service/minimax_temperature_replay_v1.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def minimax_temperature_bundles():
    retrieval = _MINIMAX_TEMPERATURE_REPLAY["retrieval"]
    evidence = []
    for metadata in retrieval["hits"]:
        location = metadata["source_location"]
        segment = location["source_segment"]
        document = (_REPLAY_ROOT / metadata["source_path"]).read_bytes().decode("utf-8")
        text = document[segment["char_start"]:segment["char_end"]]
        evidence.append(Evidence(**{
            **metadata, "source_location": canonical_json_str(location), "text": text,
        }))
    return {
        key: RetrievalBundle(query=question["search_query"], source_filter=retrieval["source_filter"],
                             hits=evidence, snapshot_ref=retrieval["snapshot_ref"])
        for key, question in _MINIMAX_TEMPERATURE_REPLAY["questions"].items()
    }


@pytest.mark.parametrize("sample", _MINIMAX_TEMPERATURE_REPLAY["responses"], ids=lambda sample: sample["id"])
def test_temperature_prescription_replays_minimax_responses(minimax_temperature_bundles, sample):
    question = _MINIMAX_TEMPERATURE_REPLAY["questions"][sample["question"]]["text"]
    raw = json.dumps(sample["response"], ensure_ascii=False)
    assert sha256_str(raw) == sample["raw_response_sha256"]
    generate = MagicMock(return_value=raw)
    answer, error = answer_standalone(
        query=question, bundle=minimax_temperature_bundles[sample["question"]],
        source_root=_REPLAY_ROOT, generate=generate, assemble_citations=True,
    )
    generate.assert_called_once()
    if sample["expected"] == "correct":
        assert error is None and answer.status == "SUPPORTED"
        assert any(ref.doc_id == "rawpedia:White_Balance" for ref in answer.citations)
    else:
        assert answer is None and error is not None and error.code == "INSUFFICIENT_EVIDENCE"


@pytest.fixture
def temperature_bundle():
    root = Path(__file__).resolve().parents[1]
    source = "data/rawpedia/White_Balance.md"
    data = (root / source).read_bytes()
    document = data.decode("utf-8")
    start = document.index("The temperature slider adjusts colors")
    end = document.index("\n\n", start)
    evidence = _make_evidence(
        doc_id="rawpedia:White_Balance", source_group_id="rawpedia:White_Balance",
        source_path=source, section_title="Temperature and Tint",
        target_url="https://rawpedia.rawtherapee.com/white_balance/#temperature-and-tint",
        text=document[start:end], char_start=start, byte_start=len(document[:start].encode()),
        source_file_sha=sha256_bytes(data),
    )
    return root, RetrievalBundle(query="White Balance temperature", source_filter="RAWPEDIA", hits=[evidence])


@pytest.mark.parametrize("text", [
    "먼저 White Balance의 Temperature 슬라이더를 오른쪽(따뜻한/노란 방향)으로 이동해 색온도를 높여 보세요.",
    "먼저 White Balance의 Temperature 슬라이더를 오른쪽으로 옮겨 이미지를 따뜻하게 만드십시오.",
    "Temperature 슬라이더를 오른쪽으로 이동해 색을 더 차갑게 만드세요. 따라서 이미 노란 캐스트가 있다면 오른쪽이 아니라 왼쪽으로 이동해야 합니다.",
    "Temperature 슬라이더를 왼쪽으로 옮기세요. 같은 설정에서 이어서 오른쪽으로 이동하세요.",
    "색온도를 높이세요.",
    "Temperature 슬라이더를 조정하세요.",
    "Tint는 자홍–녹색 축입니다. Temperature를 왼쪽으로 옮기고 Tint와 색온도를 모두 오른쪽으로 조정하세요.",
    "Temperature를 왼쪽으로 옮기세요. 이어서 Temperature(색온도)와 Tint(틴트)를 모두 오른쪽으로 조정하세요.",
    "Temperature를 왼쪽으로 옮기세요. 그리고 Temperature를 6500K로 설정하세요.",
    "노란 색감을 의도적으로 강화하려는 경우에는 오른쪽이 맞습니다.",
])
def test_temperature_prescription_withholds_reversed_or_unverified_action(temperature_bundle, text):
    root, bundle = temperature_bundle
    observations = []
    generate = MagicMock(return_value=json.dumps({
        "status": "SUPPORTED", "answer": text + " [C1S1]", "citation_ids": ["C1S1"],
    }))
    answer, error = answer_standalone(
        query=YELLOW_CAST_QUESTION, bundle=bundle, source_root=root,
        generate=generate, observe=observations.append,
    )
    generate.assert_called_once()
    assert answer is None
    assert error is not None and error.code == "INSUFFICIENT_EVIDENCE"
    assert "오른쪽" not in error.message
    assert observations[-1]["direction_check"]["reason"] in {"conflict", "unverified_action"}


@pytest.mark.parametrize(("query", "text"), [
    (YELLOW_CAST_QUESTION, "Temperature 슬라이더를 왼쪽으로 옮겨 차갑게 만들어 보세요."),
    (YELLOW_CAST_QUESTION, "Temperature 슬라이더를 왼쪽으로 옮겨 따뜻한 색감을 줄이세요."),
    (YELLOW_CAST_QUESTION, "색온도를 낮춰 보세요."),
    (YELLOW_CAST_QUESTION, "오른쪽으로 옮기면 따뜻해집니다. 노란 기를 줄이려면 오른쪽이 아니라 왼쪽으로 옮기세요."),
    (YELLOW_CAST_QUESTION, "오른쪽으로 이동하면 사진이 더 노래집니다. 왼쪽으로 옮기세요."),
    (YELLOW_CAST_QUESTION, "노란 기가 있다면 왼쪽, 푸른 기가 있다면 오른쪽으로 옮기세요."),
    (YELLOW_CAST_QUESTION, "Tint는 자홍과 녹색을 다루며, 오른쪽은 녹색입니다. 색온도는 왼쪽으로 낮추세요."),
    (YELLOW_CAST_QUESTION, "Tint를 오른쪽으로 조금 옮긴 뒤에는 Temperature를 왼쪽으로 내리세요."),
    ("사진이 푸르게 나와요. 화이트 밸런스는 어떻게 조정하나요?", "색온도 슬라이더를 오른쪽으로 옮겨 따뜻하게 보정하세요."),
    ("사진이 너무 따뜻해요. 화이트 밸런스를 어떻게 조정하나요?", "색온도 슬라이더를 왼쪽으로 옮겨 차갑게 보정하세요."),
    ("사진이 노랗지만 더 따뜻하게 연출하고 싶어요. White Balance는 어떻게 조정하나요?", "Temperature 슬라이더를 오른쪽으로 옮기세요."),
    ("사진을 노랗게 연출하고 싶어요. White Balance는 어떻게 조정하나요?", "Temperature 슬라이더를 오른쪽으로 옮기세요."),
    ("사진이 노랗게 나와요. 화이트 밸런스의 틴트는 어떻게 조정하나요?", "Tint 슬라이더를 오른쪽으로 옮기세요."),
    ("White Balance에서 Temperature를 양쪽으로 옮기면 각각 어떤 효과가 있나요?", "왼쪽은 차갑게, 오른쪽은 따뜻하게 만듭니다."),
])
def test_temperature_prescription_keeps_correct_actions_and_comparisons(temperature_bundle, query, text):
    root, bundle = temperature_bundle
    answer, error = answer_standalone(
        query=query, bundle=bundle, source_root=root,
        generate=lambda _: json.dumps({
            "status": "SUPPORTED", "answer": text + " [C1S1]", "citation_ids": ["C1S1"],
        }),
    )
    assert error is None
    assert answer.status == "SUPPORTED"
    assert answer.text.startswith(text)
    assert [ref.doc_id for ref in answer.citations] == ["rawpedia:White_Balance"]


def test_temperature_prescription_uses_confirmed_goal_and_versioned_prompt(temperature_bundle):
    root, bundle = temperature_bundle
    observations = []
    answer, error = answer_standalone(
        query="White Balance를 어떻게 조정하나요?", bundle=bundle, source_root=root,
        context=RequestContext(confirmed_goal="이미지를 더 따뜻하게 만들기"),
        generate=lambda _: json.dumps({
            "status": "SUPPORTED", "answer": "색온도를 높여 보세요. [C1S1]", "citation_ids": ["C1S1"],
        }),
        observe=observations.append,
    )
    assert error is None and answer.status == "SUPPORTED"
    record = observations[-1]
    assert record["prompt_version"] == "t17-answer-temperature-v1"
    assert "증상을 완화하는 조작을 첫 권장으로" in record["user_prompt"]
    assert record["direction_check"]["reason"] is None


def test_temperature_prescription_requires_direction_evidence_in_used_citation(tmp_path):
    source = "data/rawpedia/White_Balance.md"
    text = "White balance ensures that neutral-colored objects appear neutral."
    _, source_sha = _setup_mock_source_file(tmp_path, source, text)
    evidence = _make_evidence(
        doc_id="rawpedia:White_Balance", source_group_id="rawpedia:White_Balance",
        source_path=source, text=text, source_file_sha=source_sha,
    )
    bundle = RetrievalBundle(query="White Balance", source_filter="RAWPEDIA", hits=[evidence])
    answer, error = answer_standalone(
        query=YELLOW_CAST_QUESTION, bundle=bundle, source_root=tmp_path,
        generate=lambda _: json.dumps({
            "status": "SUPPORTED", "answer": "Temperature를 왼쪽으로 옮기세요. [C1S1]",
            "citation_ids": ["C1S1"],
        }),
    )
    assert answer is None and error.code == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("status", ["INSUFFICIENT_EVIDENCE", "UNSUPPORTED"])
def test_temperature_prescription_does_not_expose_conflicting_low_confidence_text(temperature_bundle, status):
    root, bundle = temperature_bundle
    answer, error = answer_standalone(
        query=YELLOW_CAST_QUESTION, bundle=bundle, source_root=root,
        generate=lambda _: json.dumps({
            "status": status, "answer": "모르겠습니다. Temperature를 오른쪽으로 옮기세요. [C1S1]",
            "citation_ids": ["C1S1"],
        }),
    )
    assert answer is None and error.code == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("entry", ["gui", "cli"])
@pytest.mark.parametrize(("question", "text", "accepted"), [
    pytest.param(YELLOW_CAST_QUESTION, "Temperature를 오른쪽으로 옮기세요.", False, id="original"),
    pytest.param(
        "사진이 노랗게 나와요. White Balance의 Temperature를 높여야 하나요, 낮춰야 하나요?",
        "Temperature를 높이세요. 오른쪽으로 옮기면 따뜻해집니다.", False, id="direction-question",
    ),
    pytest.param(
        "사진이 노랗게 보여요. 화이트 밸런스 어디부터 만지면 돼요?",
        "Temperature 슬라이더를 오른쪽으로 옮기세요.", False, id="colloquial-question",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "먼저 화이트 밸런스에서 따뜻한 색감이 더 강해지도록 맞추세요.",
        False, id="implicit-warming",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "사진의 색감을 더 따뜻하게 만들어 보세요.",
        False, id="implicit-warming-without-control-label",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "Temperature 슬라이더를 왼쪽으로 옮기세요. 그다음 색온도는 약간 올리세요.",
        False, id="contradictory-followup",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "Temperature 슬라이더를 왼쪽으로 옮기세요. 이어서 조금 올리세요.",
        False, id="followup-without-control-label",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION,
        "Temperature는 오른쪽으로 옮길수록 따뜻해집니다. 노란 기를 줄이려면 왼쪽으로 옮기세요.",
        True, id="effect-comparison",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "색온도를 높이면 이미지가 더 따뜻해집니다. 색온도를 낮춰 보세요.",
        True, id="value-comparison",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION, "노란 기가 있으면 왼쪽이고 푸른 기가 있으면 오른쪽입니다.",
        True, id="conditions-in-one-sentence",
    ),
    pytest.param(YELLOW_CAST_QUESTION, "색온도를 살짝 낮춰 보세요.", True, id="qualified-adjustment"),
    pytest.param(
        "ART에서 " + YELLOW_CAST_QUESTION,
        "RawTherapee 문서를 참고했습니다. ART의 Temperature 슬라이더를 왼쪽으로 옮기세요.",
        False, id="unverified-art-claim",
    ),
    pytest.param(
        "ART에서 " + YELLOW_CAST_QUESTION,
        "RawTherapee 기준으로는 Temperature 슬라이더를 왼쪽으로 옮기세요. ART 동작은 확인할 수 없습니다.",
        True, id="explicit-reference-scope",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION,
        "Temperature를 오른쪽으로 옮기면 따뜻해집니다. 왼쪽으로 옮긴 다음 다시 오른쪽으로 조정하세요.",
        False, id="explanation-with-wrong-action",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION,
        "노란 기가 있으면 왼쪽으로 옮겨 차갑게 하고 푸른 기가 있으면 오른쪽으로 옮겨 따뜻하게 하세요.",
        True, id="conditions-with-effects",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION,
        "노란 기를 없애려면 왼쪽으로, 푸른 기를 없애려면 오른쪽으로 옮기세요.",
        True, id="remove-casts",
    ),
    pytest.param(
        YELLOW_CAST_QUESTION,
        "왼쪽으로 옮기세요. 푸른 기가 있으면 오른쪽이고 푸른 기가 없으면 오른쪽입니다.",
        False, id="negative-condition",
    ),
    pytest.param(
        "사진이 노랗지만 더 따뜻하게 연출하고 싶어요. White Balance는 어떻게 조정하나요?",
        "노란 기가 있으면 왼쪽이고 푸른 기가 있으면 오른쪽입니다.", False, id="condition-conflicts-with-creative-goal",
    ),
    pytest.param(
        "사진이 노랗지만 더 따뜻하게 연출하고 싶어요. White Balance는 어떻게 조정하나요?",
        "노란 기가 있는 사진을 더 따뜻하게 표현하려면 Temperature를 오른쪽으로 옮기세요.",
        True, id="condition-matches-creative-goal",
    ),
    pytest.param(
        "ART에서 " + YELLOW_CAST_QUESTION,
        "ART의 Temperature를 왼쪽으로 옮기는 걸 RawTherapee 기준으로 안내합니다.",
        False, id="reference-cannot-override-art-claim",
    ),
])
def test_temperature_prescription_service_output(
    temperature_bundle, entry, question, text, accepted, monkeypatch,
):
    from artagent import cli, gui_bridge

    root, bundle = temperature_bundle
    search = MagicMock(return_value={"retrieval": bundle})
    research = MagicMock(side_effect=AssertionError("검사 실패는 재검색을 시작하지 않습니다."))
    generation = MagicMock(return_value=(json.dumps({
        "status": "SUPPORTED", "answer": text + " [C1S1]", "citation_ids": [],
    }), None, {}))
    expected_status = "COMPLETED" if accepted else "INSUFFICIENT_EVIDENCE"
    monkeypatch.setenv("ART_RAG_PROFILE", "local")
    if entry == "gui":
        monkeypatch.setattr("artagent.rag_service.service_answer_generator", lambda: generation)
        graph = gui_bridge.create_gui_graph(
            root, root, root, search_nodes={"SEARCH_RAWPEDIA": search}, research_generate=research,
        )
        result = gui_bridge.process_request(
            {"version": 1, "request_id": "direction-test", "text": question},
            lambda: graph,
        )
        assert result["status"] == expected_status
        assert bool(result["citations"]) == accepted
        if accepted:
            assert result["steps"][0]["text"].startswith(text)
        else:
            assert result["steps"][0]["text"] == ""
            assert result["steps"][0]["error"]["code"] == expected_status
    else:
        monkeypatch.setattr("artagent.cli.service_answer_generator", lambda: generation)
        monkeypatch.setattr("artagent.cli.create_service_search_nodes", lambda *_args, **_kw: {"SEARCH_RAWPEDIA": search})
        graph = cli.build_repl_graph(None, None, source_root=root, research_generate=research)
        result = graph.invoke({
            "request": RequestInput("direction-test", question),
            "capabilities": RuntimeCapabilities(search_ready=True),
        })
        output = []
        cli.render_response(result["response"], write_fn=output.append)
        assert result["response"].status == expected_status
        assert (text in "\n".join(output)) == accepted
        assert bool(result["response"].citations) == accepted
        assert "RESEARCH" not in result["trace"]
    search.assert_called_once()
    generation.assert_called_once()
    research.assert_not_called()


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


@pytest.mark.parametrize("body, reported, valid", [
    ("확인된 내용 [C1S1].", ["C1S1", "C1S2"], True),
    ("확인된 내용 [C1S1] [C1S1].", [], True),
    ("확인된 내용 [C1S1]과 미지의 내용 [C9S9].", ["C1S1"], False),
    ("확인된 내용 [C1S1]과 미지의 내용 [c9s9].", ["C1S1"], False),
    ("확인된 내용 [C1S1]과 조합 표식 [C1S1, C9S9].", ["C1S1"], False),
    ("표식이 없는 답변.", ["C1S1"], False),
])
def test_citation_ids_can_be_assembled_from_verified_body_markers(tmp_path, body, reported, valid):
    path = "data/rawpedia/sample.md"
    text = "Sample text."
    _, file_sha = _setup_mock_source_file(tmp_path, path, text)
    hit = _make_evidence(source_path=path, text=text, source_file_sha=file_sha)
    bundle = RetrievalBundle(query="q", source_filter="RAWPEDIA", hits=[hit])

    answer, error = answer_standalone(
        query="test", bundle=bundle, source_root=tmp_path, assemble_citations=True,
        generate=lambda *_: json.dumps({"status": "UNSUPPORTED", "answer": body, "citation_ids": reported}),
    )

    if valid:
        assert error is None
        assert len(answer.citations) == 1
        assert "[C1S1]" not in answer.text
    else:
        assert answer is None
        assert error.code == "ANSWER_CITATION_INVALID"


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
