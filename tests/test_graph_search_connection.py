"""Tests for LangGraph router search connection (Task 14-CONN / A-14).

Verifies SEARCH_RAWPEDIA and SEARCH_GITHUB node factories, target resolution,
Evidence segment mapping, rewrite on/off behavior, error handling, and graph integration.
"""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Any, Optional, Sequence
from unittest.mock import MagicMock
import pytest

from artagent.graph import (
    AgentState,
    AnswerResult,
    Citation,
    Path,
    PlanStep,
    RequestContext,
    RequestInput,
    ResponseStatus,
    RouteDecision,
    RuntimeCapabilities,
    create_router_graph,
    create_search_github_node,
    create_search_nodes,
    create_search_rawpedia_node,
    resolve_github_targets,
    search_hits_to_evidences,
)
from artagent.retrieval.types import SearchHit
from artagent.retrieval.provenance import sha256_str


def _test_hit(**fields: Any) -> SearchHit:
    """테스트 원문에도 실제 본문/세그먼트 해시를 사용한다."""
    content = fields["content"]
    fields["content_sha256"] = sha256_str(content)
    segments = fields["source_segments"]
    for seg in segments:
        seg.update(source_file_sha256="a" * 64,
                   segment_sha256=sha256_str(content[seg["content_char_start"]:seg["content_char_end"]]))
    fields["original_metadata"] = {**fields["original_metadata"], "source_segments": segments}
    return SearchHit(**fields)


def _segment_hit() -> SearchHit:
    text = "first comment\nsecond comment"
    segment = {
        "doc_id": "issue-comment:1", "ref_id": "issue-comment:1",
        "source_path": "data/issues/snapshots/issue-comments/1.json",
        "target_url": "https://github.com/artraweditor/ART/issues/524#issuecomment-1",
        "content_char_start": 0, "content_char_end": 13,
        "char_start": 7, "char_end": 20, "json_pointer": "/body",
        "source_file_sha256": "a" * 64, "segment_sha256": sha256_str(text[:13]),
    }
    return SearchHit(1, "chunk_segments", "github", "issue:524",
                     "github:artraweditor/ART:issue:524", "thread title", text,
                     sha256_str(text), [segment], {"source_segments": [segment]},
                     0.1, "0.100000")


@pytest.mark.parametrize("start,end", [(0, 999), (-1, 13), (13, 0), (None, 13), (0, "13"), (False, 13)])
def test_mapping_rejects_invalid_segment_range(start: Any, end: Any) -> None:
    hit = _segment_hit()
    malformed = {**hit.source_segments[0], "content_char_start": start, "content_char_end": end}
    with pytest.raises(ValueError, match="segment|세그먼트|범위"):
        search_hits_to_evidences([replace(hit, source_segments=[malformed])])


def test_mapping_preserves_exact_source_location() -> None:
    hit = _segment_hit()
    evidence = search_hits_to_evidences([hit])[0]
    location = json.loads(evidence.source_location)
    assert location["source_segment"] == hit.source_segments[0]
    assert location["section_title"] == "thread title"
    assert evidence.text == "first comment"
    assert "second comment" not in evidence.text


def test_mapping_rejects_missing_segments_and_changed_segment_body() -> None:
    hit = _segment_hit()
    with pytest.raises(ValueError):
        search_hits_to_evidences([replace(hit, source_segments=[])])
    changed = {**hit.source_segments[0], "segment_sha256": "b" * 64}
    with pytest.raises(ValueError):
        search_hits_to_evidences([replace(hit, source_segments=[changed])])


@pytest.mark.parametrize("factory", [create_search_rawpedia_node, create_search_github_node])
def test_mapping_failure_is_a_node_error(factory: Any) -> None:
    hit = _segment_hit()
    broken = {**hit.source_segments[0], "content_char_end": 999}
    store = MagicMock()
    store.search.return_value = [replace(hit, source_segments=[broken])]
    result = factory(store, MagicMock(), rewrite_enabled=False)(
        {"request": RequestInput(request_id="bad_segment", text="query")}
    )
    assert result["error"].code == "SEARCH_UNAVAILABLE"
    assert "retrieval" not in result


@pytest.mark.parametrize("factory", [create_search_rawpedia_node, create_search_github_node])
def test_search_defaults_to_off_while_adoption_is_pending(factory: Any) -> None:
    store = MagicMock()
    store.search.return_value = []
    generate = MagicMock(return_value="rewritten query")
    result = factory(store, MagicMock(), generate=generate)(
        {"request": RequestInput(request_id="pending_adoption", text="original query")}
    )
    assert result["error"] is None
    assert result["retrieval"].query == "original query"
    generate.assert_not_called()


# =========================================================================
# 1. GitHub 대상 번호 추출 (resolve_github_targets)
# =========================================================================

def test_resolve_github_targets() -> None:
    # 1. Discussion 번호 추출
    res1 = resolve_github_targets("GitHub Discussion #412에 정리된 Windows 환경 ART 빌드 절차")
    assert res1 == ["github:artraweditor/ART:discussion:412"]

    # 2. Issue 번호 추출
    res2 = resolve_github_targets("GitHub Issue #524에서 크래시 증상")
    assert res2 == ["github:artraweditor/ART:issue:524"]

    # 3. URL 형태 추출
    res3 = resolve_github_targets("https://github.com/artraweditor/ART/issues/477 및 https://github.com/artraweditor/ART/discussions/442")
    assert res3 == [
        "github:artraweditor/ART:issue:477",
        "github:artraweditor/ART:discussion:442",
    ]

    # 4. 복수 혼합 대상
    res4 = resolve_github_targets("Issue #500 관련 내용과 Discussion #420 참고")
    assert res4 == [
        "github:artraweditor/ART:issue:500",
        "github:artraweditor/ART:discussion:420",
    ]

    # 5. 한글 표기 (이슈 / 디스커션)
    res5 = resolve_github_targets("이슈 #516 내용 확인")
    assert res5 == ["github:artraweditor/ART:issue:516"]

    res6 = resolve_github_targets("디스커션 #489 타원형 마스크")
    assert res6 == ["github:artraweditor/ART:discussion:489"]

    # 6. 대상 미명시 (일반 질문)
    res7 = resolve_github_targets("노출 보정 도구의 작동 원리는 무엇인가요?")
    assert res7 is None


# =========================================================================
# 2. SearchHit -> Evidence 변환 (search_hits_to_evidences)
# =========================================================================

def test_search_hits_to_evidences() -> None:
    # 1. RawPedia 단일 세그먼트
    hit_raw = _test_hit(
        rank=1,
        chunk_id="chunk_r1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure",
        section_title="Exposure Compensation",
        content="This is the full text of exposure compensation in RawTherapee.",
        content_sha256="sha_r1",
        source_segments=[{
            "doc_id": "rawpedia:Exposure",
            "source_path": "data/rawpedia/Exposure.md",
            "target_url": "https://rawpedia.rawtherapee.com/exposure/",
            "content_char_start": 0,
            "content_char_end": len("This is the full text of exposure compensation in RawTherapee."),
        }],
        original_metadata={"source_path": "data/rawpedia/Exposure.md"},
        distance=0.12,
        distance_text="0.120000",
    )
    ev_raw = search_hits_to_evidences([hit_raw])
    assert len(ev_raw) == 1
    assert ev_raw[0].chunk_id == "chunk_r1"
    assert ev_raw[0].doc_id == "rawpedia:Exposure"
    assert ev_raw[0].product_scope == "RawTherapee"
    assert ev_raw[0].source_type == "rawpedia"
    assert ev_raw[0].text == "This is the full text of exposure compensation in RawTherapee."
    assert ev_raw[0].target_url == "https://rawpedia.rawtherapee.com/exposure/"

    # 2. GitHub 복수 세그먼트 (각 세그먼트별 개별 Evidence 분리)
    hit_gh = _test_hit(
        rank=1,
        chunk_id="chunk_g1",
        source_type="github",
        doc_id="issue:524",
        source_group_id="github:artraweditor/ART:issue:524",
        section_title="Crash on Spot Removal",
        content="Issue body text here... [comment separator] Comment 1 text here...",
        content_sha256="sha_g1",
        source_segments=[
            {
                "doc_id": "issue:524",
                "source_path": "data/issues/snapshots/issues/524.json",
                "target_url": "https://github.com/artraweditor/ART/issues/524",
                "content_char_start": 0,
                "content_char_end": 23,
            },
            {
                "doc_id": "issue-comment:5648127070",
                "source_path": "data/issues/snapshots/issue-comments/5648127070.json",
                "target_url": "https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070",
                "content_char_start": 44,
                "content_char_end": len("Issue body text here... [comment separator] Comment 1 text here..."),
            },
        ],
        original_metadata={"source_path": "data/issues/snapshots/issues/524.json"},
        distance=0.08,
        distance_text="0.080000",
    )
    ev_gh = search_hits_to_evidences([hit_gh])
    assert len(ev_gh) == 2
    assert ev_gh[0].doc_id == "issue:524"
    assert ev_gh[0].text == "Issue body text here..."
    assert ev_gh[0].product_scope == "ART"
    assert ev_gh[0].target_url == "https://github.com/artraweditor/ART/issues/524"

    assert ev_gh[1].doc_id == "issue-comment:5648127070"
    assert ev_gh[1].text == "Comment 1 text here..."
    assert ev_gh[1].product_scope == "ART"
    assert ev_gh[1].target_url == "https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070"


# =========================================================================
# 3. SEARCH_RAWPEDIA 노드 계약 (on / off / 오류)
# =========================================================================

def test_search_rawpedia_node_off_and_on() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    mock_hit = _test_hit(
        rank=1,
        chunk_id="chunk_1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure",
        section_title="Exposure",
        content="Exposure content",
        content_sha256="sha1",
        source_segments=[{
            "doc_id": "rawpedia:Exposure", "source_path": "data/rawpedia/Exposure.md",
            "target_url": "https://rawpedia.rawtherapee.com/exposure/",
            "content_char_start": 0, "content_char_end": len("Exposure content"),
        }],
        original_metadata={},
        distance=0.1,
        distance_text="0.100000",
    )
    mock_store.search.return_value = [mock_hit]

    generate_calls = []

    def mock_generate(prompt: str) -> str:
        generate_calls.append(prompt)
        return "노출 보정 도구의 슬라이더 범위와 작동 방식"

    # A: rewrite_enabled = False (off)
    node_off = create_search_rawpedia_node(
        mock_store,
        mock_session,
        generate=mock_generate,
        snapshot_ref="snap_test",
        rewrite_enabled=False,
    )

    state_off: AgentState = {
        "request": RequestInput(request_id="req1", text="노출 보정 어떻게 하나요?"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=Path.DOC_QA, query="노출 보정 어떻게 하나요?")]
        ),
        "cursor": 0,
        "trace": ["INTAKE", "ROUTE", "DISPATCH"],
    }

    result_off = node_off(state_off)
    assert len(generate_calls) == 0  # off에서는 생성 호출 0회
    assert result_off["error"] is None
    assert result_off["retrieval"].source_filter == "RAWPEDIA"
    assert result_off["retrieval"].query == "노출 보정 어떻게 하나요?"
    assert result_off["retrieval"].snapshot_ref == "snap_test"
    assert result_off["trace"] == ["INTAKE", "ROUTE", "DISPATCH", "SEARCH_RAWPEDIA"]
    mock_store.search.assert_called_with("노출 보정 어떻게 하나요?", mock_session, source_type="rawpedia")

    # B: rewrite_enabled = True (on)
    mock_store.search.reset_mock()
    generate_calls.clear()

    node_on = create_search_rawpedia_node(
        mock_store,
        mock_session,
        generate=mock_generate,
        snapshot_ref="snap_test",
        rewrite_enabled=True,
    )

    result_on = node_on(state_off)
    assert len(generate_calls) == 1  # on에서는 생성 호출 1회
    assert result_on["error"] is None
    assert result_on["retrieval"].query == "노출 보정 도구의 슬라이더 범위와 작동 방식"
    mock_store.search.assert_called_with(
        "노출 보정 도구의 슬라이더 범위와 작동 방식",
        mock_session,
        source_type="rawpedia",
    )


def test_search_rawpedia_node_rewrite_failure() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    # 빈 문자열을 반환하여 재작성 실패 유도
    def failing_generate(prompt: str) -> str:
        return ""

    node = create_search_rawpedia_node(
        mock_store,
        mock_session,
        generate=failing_generate,
        rewrite_enabled=True,
    )

    state: AgentState = {
        "request": RequestInput(request_id="req1", text="노출 보정 질문"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=Path.DOC_QA, query="노출 보정 질문")]
        ),
        "cursor": 0,
        "trace": [],
    }

    result = node(state)
    assert result["error"] is not None
    assert result["error"].code == "REWRITE_FAILED"
    assert result["error"].node == "SEARCH_RAWPEDIA"
    assert result["error"].recoverable is False
    assert mock_store.search.call_count == 0  # 검색 호출 0회 보장


# =========================================================================
# 4. SEARCH_GITHUB 노드 계약 (대상 글 추출, 필터링, 검색 실패)
# =========================================================================

def test_search_github_node_with_target_resolution() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()
    mock_store.search.return_value = []

    node = create_search_github_node(
        mock_store,
        mock_session,
        rewrite_enabled=False,
        snapshot_ref="snap_gh",
    )

    state: AgentState = {
        "request": RequestInput(
            request_id="req_gh",
            text="GitHub Issue #524에서 스팟 제거 크래시 버그 원인과 해결책은?",
        ),
        "decision": RouteDecision(
            plan=[PlanStep(
                step_id="s1",
                path=Path.TROUBLESHOOT,
                query="GitHub Issue #524에서 스팟 제거 크래시 버그 원인과 해결책은?",
            )]
        ),
        "cursor": 0,
        "trace": [],
    }

    result = node(state)
    assert result["error"] is None
    assert result["retrieval"].source_filter == "GITHUB"
    # 대상 글 #524가 source_group_ids로 전달되었는지 검증
    mock_store.search.assert_called_with(
        "GitHub Issue #524에서 스팟 제거 크래시 버그 원인과 해결책은?",
        mock_session,
        source_type="github",
        source_group_ids=["github:artraweditor/ART:issue:524"],
    )


def test_search_service_failure() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()
    mock_store.search.side_effect = RuntimeError("DB connection error")

    node = create_search_rawpedia_node(
        mock_store,
        mock_session,
        rewrite_enabled=False,
    )

    state: AgentState = {
        "request": RequestInput(request_id="req1", text="query"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=Path.DOC_QA, query="query")]
        ),
        "cursor": 0,
        "trace": [],
    }

    result = node(state)
    assert result["error"] is not None
    assert result["error"].code == "SEARCH_UNAVAILABLE"
    assert result["error"].node == "SEARCH_RAWPEDIA"
    assert result["error"].recoverable is False


# =========================================================================
# 5. create_router_graph와 검색 노드 결합 E2E 검증
# =========================================================================

def test_router_graph_with_search_nodes_rawpedia() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    mock_hit = _test_hit(
        rank=1,
        chunk_id="chunk_exp",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure",
        section_title="Exposure",
        content="Exposure tools guide.",
        content_sha256="sha1",
        source_segments=[{
            "doc_id": "rawpedia:Exposure",
            "source_path": "data/rawpedia/Exposure.md",
            "target_url": "https://rawpedia.rawtherapee.com/exposure/",
            "content_char_start": 0,
            "content_char_end": 21,
        }],
        original_metadata={},
        distance=0.05,
        distance_text="0.050000",
    )
    mock_store.search.return_value = [mock_hit]

    search_nodes = create_search_nodes(
        mock_store,
        mock_session,
        rewrite_enabled=False,
        snapshot_ref="test_snapshot",
    )

    # ANSWER 노드 대역 (검색 연결 검증 목적)
    def answer_standin(state: AgentState) -> dict[str, Any]:
        bundle = state["retrieval"]
        ev = bundle.hits[0]
        cit = Citation(doc_id=ev.doc_id, title=ev.source_location, url=ev.target_url, source_location=ev.source_location)
        ans = AnswerResult(
            status="SUPPORTED",
            text=f"답변: {ev.text}",
            citations=[cit],
        )
        return {"answer": ans, "trace": [*state.get("trace", []), "ANSWER"]}

    ready = RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True)

    def intake_standin(state: AgentState) -> dict[str, Any]:
        return {"capabilities": ready}

    overrides = {
        **search_nodes,
        "INTAKE": intake_standin,
        "ANSWER": answer_standin,
    }

    graph = create_router_graph(node_overrides=overrides)

    initial_state: AgentState = {
        "request": RequestInput(
            request_id="req_test_p1",
            text="노출 보정 도구의 작동 원리는 무엇인가요?",
        ),
    }

    final_state = graph.invoke(initial_state)

    # 1. 경로 전이 순서 검증
    assert "SEARCH_RAWPEDIA" in final_state["trace"]
    assert "ANSWER" in final_state["trace"]
    assert "RESPOND" in final_state["trace"]

    # 2. RetrievalBundle 검증
    bundle = final_state.get("retrieval")
    assert bundle is not None
    assert bundle.source_filter == "RAWPEDIA"
    assert len(bundle.hits) == 1
    assert bundle.hits[0].product_scope == "RawTherapee"
    assert bundle.hits[0].text == "Exposure tools guide."

    # 3. 최종 응답 상태 검증
    resp = final_state.get("response")
    assert resp is not None
    assert resp.status == ResponseStatus.COMPLETED
    assert resp.primary_path == Path.DOC_QA


def test_router_graph_with_search_nodes_github() -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    mock_hit = _test_hit(
        rank=1,
        chunk_id="chunk_gh",
        source_type="github",
        doc_id="issue:524",
        source_group_id="github:artraweditor/ART:issue:524",
        section_title="Crash fix",
        content="Fixed crash in spot removal",
        content_sha256="sha2",
        source_segments=[{
            "doc_id": "issue:524",
            "source_path": "data/issues/snapshots/issues/524.json",
            "target_url": "https://github.com/artraweditor/ART/issues/524",
            "content_char_start": 0,
            "content_char_end": len("Fixed crash in spot removal"),
        }],
        original_metadata={},
        distance=0.03,
        distance_text="0.030000",
    )
    mock_store.search.return_value = [mock_hit]

    search_nodes = create_search_nodes(
        mock_store,
        mock_session,
        rewrite_enabled=False,
        snapshot_ref="test_snapshot",
    )

    def answer_standin(state: AgentState) -> dict[str, Any]:
        bundle = state["retrieval"]
        ev = bundle.hits[0]
        cit = Citation(doc_id=ev.doc_id, title=ev.source_location, url=ev.target_url, source_location=ev.source_location)
        ans = AnswerResult(
            status="SUPPORTED",
            text=f"GitHub 문제 답변: {ev.text}",
            citations=[cit],
        )
        return {"answer": ans, "trace": [*state.get("trace", []), "ANSWER"]}

    ready = RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True)

    def intake_standin(state: AgentState) -> dict[str, Any]:
        return {"capabilities": ready}

    overrides = {
        **search_nodes,
        "INTAKE": intake_standin,
        "ANSWER": answer_standin,
    }

    graph = create_router_graph(node_overrides=overrides)

    initial_state: AgentState = {
        "request": RequestInput(
            request_id="req_test_p2",
            text="GitHub Issue #524에서 스팟 제거 활성화 시 동결/크래시 버그의 재현 절차는 무엇인가요?",
        ),
    }

    final_state = graph.invoke(initial_state)

    # 1. 경로 전이 순서 검증
    assert "SEARCH_GITHUB" in final_state["trace"]
    assert "ANSWER" in final_state["trace"]
    assert "RESPOND" in final_state["trace"]

    # 2. RetrievalBundle 검증
    bundle = final_state.get("retrieval")
    assert bundle is not None
    assert bundle.source_filter == "GITHUB"
    assert len(bundle.hits) == 1
    assert bundle.hits[0].product_scope == "ART"
    assert bundle.hits[0].doc_id == "issue:524"

    # 3. Store 호출 시 지정 글 group_id 필터가 제대로 전달되었는지 검증
    mock_store.search.assert_called_with(
        "GitHub Issue #524에서 스팟 제거 활성화 시 동결/크래시 버그의 재현 절차는 무엇인가요?",
        mock_session,
        source_type="github",
        source_group_ids=["github:artraweditor/ART:issue:524"],
    )
