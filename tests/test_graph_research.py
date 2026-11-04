"""근거 부족 폴백의 요청 예산과 외부 호출 횟수 회귀."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import pickle
import json
from unittest.mock import MagicMock

import pytest

from artagent.graph import (
    AnswerResult, ErrorInfo, RequestInput, RuntimeCapabilities,
    create_router_graph, create_search_nodes,
)


def services(outcomes, *, rewrite_enabled=False, generate_error=False,
             search_error_at=None):
    from artagent.graph.research import create_research_node

    counts = Counter(search=0, answer=0, rewrite=0)
    observations = []
    store = MagicMock()

    def retrieve(query, session, **filters):
        counts["search"] += 1
        assert counts["search"] <= 3, "추가 검색 예산 초과"
        if counts["search"] == search_error_at:
            raise RuntimeError("검색 연결 실패")
        return []

    store.search.side_effect = retrieve

    def generate(prompt):
        counts["rewrite"] += 1
        if generate_error:
            raise RuntimeError("재작성 연결 실패")
        # T14의 실제 보존 검사를 통과하는 원질문 재사용도 1회 시도다.
        return prompt.split("User Query:\n", 1)[1].split("\n", 1)[0]

    def answer(state):
        counts["answer"] += 1
        assert counts["answer"] <= len(outcomes), "추가 답변 예산 초과"
        outcome = outcomes[counts["answer"] - 1]
        error = outcome if isinstance(outcome, ErrorInfo) else None
        return {
            "answer": None if error else AnswerResult(outcome, "테스트 답변"),
            "error": error,
            "trace": [*state.get("trace", []), "ANSWER"],
        }

    nodes = create_search_nodes(
        store, MagicMock(), generate=generate, rewrite_enabled=rewrite_enabled,
        snapshot_ref="t16-test", observe=observations.append,
    )
    nodes.update(ANSWER=answer, RESEARCH=create_research_node(generate=generate))
    return nodes, counts, observations, store


def request(text="노출 보정 방법을 알려줘", **fields):
    return {"request": RequestInput("t16", text),
            "capabilities": RuntimeCapabilities(search_ready=True), **fields}


@pytest.mark.parametrize("text", ["노출 보정 방법을 알려줘", "GitHub Issue #524 크래시 원인?"])
@pytest.mark.parametrize("rewrite_enabled", [False, True])
@pytest.mark.parametrize("outcomes,searches,final_status", [
    (["SUPPORTED"], 1, "COMPLETED"),
    (["UNSUPPORTED"], 1, "UNSUPPORTED"),
    (["INSUFFICIENT_EVIDENCE", "SUPPORTED"], 2, "COMPLETED"),
    (["INSUFFICIENT_EVIDENCE", "UNSUPPORTED"], 2, "UNSUPPORTED"),
    (["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"], 2, "INSUFFICIENT_EVIDENCE"),
])
def test_retry_only_for_insufficient_evidence(text, rewrite_enabled, outcomes,
                                            searches, final_status):
    nodes, counts, observations, store = services(outcomes, rewrite_enabled=rewrite_enabled)
    state = create_router_graph(nodes).invoke(request(text))
    assert state["response"].status == final_status
    assert counts == {"search": searches, "answer": searches,
                      "rewrite": int(rewrite_enabled) + searches - 1}
    assert state["research_count"] == searches - 1
    assert state["trace"].count("RESEARCH") == searches - 1
    assert state["trace"][-1] == "RESPOND"
    assert len(observations) == searches
    if "#524" in text:
        for call in store.search.call_args_list:
            assert call.kwargs["source_group_ids"] == ["github:artraweditor/ART:issue:524"]


@pytest.mark.parametrize("failure,expected,searches,answers", [
    ("rewrite", "REWRITE_FAILED", 1, 1),
    ("search", "SEARCH_UNAVAILABLE", 2, 1),
    ("answer", "ANSWER_GENERATION_FAILED", 2, 2),
])
def test_retry_technical_failure_stops(failure, expected, searches, answers):
    outcomes = ["INSUFFICIENT_EVIDENCE", ErrorInfo("ANSWER_GENERATION_FAILED", "실패", "ANSWER")]
    nodes, counts, _, _ = services(outcomes, generate_error=failure == "rewrite",
                                  search_error_at=2 if failure == "search" else None)
    state = create_router_graph(nodes).invoke(request())
    result = state["step_results"]["t16_step_1"]
    assert result.status == "FAILED"
    assert result.error.code == expected
    assert counts == {"rewrite": 1, "search": searches, "answer": answers}
    assert state["research_count"] == 1
    assert state["trace"].count("RESEARCH") == 1


def test_standalone_nodes_replace_bundle_without_mutating_request():
    from artagent.graph.nodes import intake_node, route_node

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = request()
    state.update(intake_node(state))
    state.update(route_node(state))
    original_request = deepcopy(state["request"])
    original_decision = deepcopy(state["decision"])
    for name in ("SEARCH_RAWPEDIA", "ANSWER", "RESEARCH", "SEARCH_RAWPEDIA", "ANSWER"):
        state.update(nodes[name](state))
    assert state["answer"].status == "SUPPORTED"
    assert counts == {"rewrite": 1, "search": 2, "answer": 2}
    assert state["request"] == original_request
    assert state["decision"] == original_decision
    assert state["cursor"] == 0


@pytest.mark.parametrize("outcomes", [
    ["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"],
    ["SUPPORTED", "INSUFFICIENT_EVIDENCE", "SUPPORTED"],
])
def test_mixed_request_has_one_shared_retry_without_skipping_initial_search(outcomes):
    nodes, counts, _, _ = services(outcomes)
    state = create_router_graph(nodes).invoke(request(
        "GitHub Issue #524 크래시 원인과 해결책을 알려주고, 노출 보정 도구 사용법도 알려줘."
    ))
    assert len(state["step_results"]) == 2
    assert counts == {"search": 3, "answer": 3, "rewrite": 1}
    assert state["research_count"] == 1
    assert state["trace"].count("RESEARCH") == 1
    assert state.get("research_input") is None


def retry_snapshot(nodes, phase="PREPARED"):
    from artagent.graph.nodes import intake_node, route_node, dispatch_node

    state = request()
    for node in (intake_node, route_node, dispatch_node):
        state.update(node(state))
    names = ["SEARCH_RAWPEDIA", "ANSWER", "RESEARCH"]
    if phase in ("SEARCHED", "ANSWERED"):
        names.append("SEARCH_RAWPEDIA")
    if phase == "ANSWERED":
        names.append("ANSWER")
    for name in names:
        state.update(nodes[name](state))
    # 재개는 콜백의 메모리 대신 저장한 state에 의존한다.
    return pickle.loads(pickle.dumps(state))


@pytest.mark.parametrize("phase", ["PREPARED", "SEARCHED", "ANSWERED"])
@pytest.mark.parametrize("last_status", ["SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE"])
def test_resume_at_completed_node_does_not_repeat_external_calls(phase, last_status):
    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", last_status])
    state = retry_snapshot(nodes, phase)
    state = create_router_graph(nodes).invoke(state)
    assert counts == {"search": 2, "answer": 2, "rewrite": 1}
    assert state["research_count"] == 1
    assert state["step_results"]["t16_step_1"].answer.status == last_status
    assert state.get("research_input") is None
    # 최종 결과까지 저장한 요청을 다시 불러와도 외부 호출은 늘지 않는다.
    create_router_graph(nodes).invoke(pickle.loads(pickle.dumps(state)))
    assert counts == {"search": 2, "answer": 2, "rewrite": 1}


@pytest.mark.parametrize("count", [-1, 2, True, False, 1.0, "0", None])
def test_invalid_budget_is_rejected_before_search(count):
    nodes, counts, _, _ = services(["SUPPORTED"])
    state = create_router_graph(nodes).invoke(request(research_count=count))
    assert state["response"].status == "FAILED"
    assert state["response"].error.code == "CONTRACT_VIOLATION"
    assert not any(counts.values())


@pytest.mark.parametrize("change", ["request", "query", "context", "prepared", "input", "phase"])
def test_stale_or_corrupt_preparation_is_rejected_without_external_calls(change):
    from artagent.graph import RequestContext

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    if change == "request":
        state["request"] = replace(state["request"], request_id="other")
    elif change == "query":
        state["request"] = replace(state["request"], text="화이트밸런스 원리를 알려줘")
    elif change == "context":
        state["request"] = replace(state["request"], context=RequestContext(os="Windows"))
    elif change == "prepared":
        state["research_input"] = {"phase": "PREPARED"}
    elif change == "input":
        item = state["research_input"]
        state["research_input"] = replace(item, search_input=replace(item.search_input, search_query="changed"))
    else:
        state["research_input"] = replace(state["research_input"], phase="OTHER")
    state = create_router_graph(nodes).invoke(state)
    assert state["response"].status == "FAILED"
    assert state["response"].error.code == "CONTRACT_VIOLATION"
    assert counts == {"search": 1, "answer": 1, "rewrite": 1}


def test_missing_preparation_cannot_repeat_an_allocated_attempt():
    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    state["research_input"] = None
    state = create_router_graph(nodes).invoke(state)
    assert state["response"].status == "FAILED"
    assert state["response"].error.code == "CONTRACT_VIOLATION"
    assert counts == {"search": 1, "answer": 1, "rewrite": 1}


def test_completed_search_node_is_safe_to_reenter():
    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes, "SEARCHED")
    state.update(nodes["SEARCH_RAWPEDIA"](state))
    state.update(nodes["RESEARCH"](state))
    assert state.get("error") is None
    assert counts == {"search": 2, "answer": 1, "rewrite": 1}


@pytest.mark.parametrize("failure", ["rewrite", "search", "answer"])
def test_resume_after_technical_failure_preserves_error_without_repeating(failure):
    outcomes = ["INSUFFICIENT_EVIDENCE", ErrorInfo("ANSWER_GENERATION_FAILED", "실패", "ANSWER")]
    nodes, counts, _, _ = services(outcomes, generate_error=failure == "rewrite",
                                  search_error_at=2 if failure == "search" else None)
    phase = {"rewrite": "PREPARED", "search": "SEARCHED", "answer": "ANSWERED"}[failure]
    state = retry_snapshot(nodes, phase)
    error = state["error"]
    before = dict(counts)
    state = create_router_graph(nodes).invoke(state)
    assert state["step_results"]["t16_step_1"].error == error
    assert dict(counts) == before
    assert state["research_count"] == 1


@pytest.mark.parametrize("source_type", ["rawpedia", "github"])
@pytest.mark.parametrize("status", ["SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE"])
def test_real_answer_node_uses_retry_evidence_and_exact_citation(tmp_path, source_type, status):
    from artagent.graph import create_answer_node
    from artagent.retrieval.provenance import sha256_bytes, sha256_str
    from artagent.retrieval.types import SearchHit

    text = "노출 보정 안내 원문."
    rawpedia = source_type == "rawpedia"
    rel = "source.md" if rawpedia else "source.json"
    file_bytes = text.encode() if rawpedia else json.dumps({"body": text}).encode()
    (tmp_path / rel).write_bytes(file_bytes)
    url = "https://rawpedia.rawtherapee.com/Exposure" if rawpedia else "https://github.com/artraweditor/ART/issues/524"
    doc_id = "rawpedia:Exposure" if rawpedia else "issue:524"
    group = doc_id if rawpedia else "github:artraweditor/ART:issue:524"
    segment = {
        "doc_id": doc_id, "ref_id": doc_id, "source_path": rel, "target_url": url,
        "source_file_sha256": sha256_bytes(file_bytes), "segment_sha256": sha256_str(text),
        "char_start": 0, "char_end": len(text), "byte_start": 0, "byte_end": len(text.encode()),
        "content_char_start": 0, "content_char_end": len(text),
        "json_pointer": None if rawpedia else "/body",
    }
    hit = SearchHit(1, "t16-chunk", source_type, doc_id, group, "노출 안내",
                    text, sha256_str(text), [segment], {}, 0.2, "0.200000")
    store = MagicMock()
    store.search.side_effect = [[], [hit]]
    observed = []
    generate = MagicMock(side_effect=[
        json.dumps({"status": "INSUFFICIENT_EVIDENCE", "answer": "근거가 부족합니다.", "citation_ids": []}),
        json.dumps({
            "status": status,
            "answer": "RawTherapee 참고 원문의 설명입니다 [C1S1]." if rawpedia else "원문의 설명입니다 [C1S1].",
            "citation_ids": ["C1S1"],
        }),
    ])
    from artagent.graph.research import create_research_node

    question = "노출 보정 방법을 알려줘" if rawpedia else "GitHub Issue #524 크래시 원인?"
    rewrite = MagicMock(return_value=question)
    nodes = create_search_nodes(store, MagicMock(), snapshot_ref="integration")
    nodes.update(ANSWER=create_answer_node(generate=generate, source_root=tmp_path, observe=observed.append),
                 RESEARCH=create_research_node(generate=rewrite))
    state = create_router_graph(nodes).invoke(request(question))
    result = state["step_results"]["t16_step_1"]
    assert result.error is None, result.error
    assert result.answer.status == status
    assert result.error is None
    assert state["research_count"] == 1
    assert store.search.call_count == 2
    assert rewrite.call_count == 1
    assert generate.call_count == 2
    citation = result.answer.citations[0]
    assert citation.doc_id == doc_id
    assert citation.url == url
    assert json.loads(citation.source_location)["source_segment"] == segment
    assert ("RawTherapee" if rawpedia else "ART") in result.answer.applicability
    assert state["retrieval"].snapshot_ref == "integration"


def test_preservation_failure_does_not_search_or_change_product_scope():
    from artagent.graph.nodes import intake_node, route_node, dispatch_node
    from artagent.graph.research import create_research_node

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE"])
    state = request()
    for node in (intake_node, route_node, dispatch_node, nodes["SEARCH_RAWPEDIA"], nodes["ANSWER"]):
        state.update(node(state))
    rewrite = MagicMock(return_value="ART exposure instructions")
    state.update(create_research_node(generate=rewrite)(state))
    assert state["error"].code == "REWRITE_FAILED"
    assert state["research_input"].search_input.error_category == "PRODUCT_SCOPE_VIOLATION"
    assert state["research_count"] == 1
    assert counts == {"search": 1, "answer": 1, "rewrite": 0}
    assert rewrite.call_count == 1


def test_changed_search_configuration_is_rejected_on_resume():
    nodes, counts, _, store = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    nodes.update(create_search_nodes(store, MagicMock(), snapshot_ref="other"))
    state = create_router_graph(nodes).invoke(state)
    assert state["response"].error.code == "CONTRACT_VIOLATION"
    assert counts == {"search": 1, "answer": 1, "rewrite": 1}


@pytest.mark.parametrize("change", ["path", "cursor", "answer", "count"])
def test_research_guards_run_before_rewrite(change):
    from artagent.graph import Path

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    # 최초 답변 직후의 상태로 돌린 다음 잘못된 입력을 주입한다.
    state.update(research_input=None, research_count=0, research_request_id=None,
                 research_step_id=None, answer=AnswerResult("INSUFFICIENT_EVIDENCE", "부족"))
    if change == "path":
        state["decision"].plan[0].path = Path.EXECUTE
    elif change == "cursor":
        state["cursor"] = -1
    elif change == "answer":
        state["answer"] = AnswerResult("UNSUPPORTED", "미지원")
    elif change == "count":
        state["research_count"] = True
    before = dict(counts)
    updates = nodes["RESEARCH"](state)
    assert updates["error"].code == "CONTRACT_VIOLATION"
    assert dict(counts) == before


@pytest.mark.parametrize("output", [123, {"query": "문자열 아님"}])
def test_invalid_rewrite_response_is_a_consumed_technical_failure(output):
    from artagent.graph.research import create_research_node

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE"])
    generate = MagicMock(return_value=output)
    nodes["RESEARCH"] = create_research_node(generate=generate)
    state = create_router_graph(nodes).invoke(request())
    assert state["step_results"]["t16_step_1"].error.code == "REWRITE_FAILED"
    assert state["research_count"] == 1
    assert counts["search"] == counts["answer"] == generate.call_count == 1


def test_direct_search_rejects_lost_retry_input():
    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    state["research_input"] = None
    updates = nodes["SEARCH_RAWPEDIA"](state)
    assert updates["error"].code == "CONTRACT_VIOLATION"
    assert counts == {"search": 1, "answer": 1, "rewrite": 1}


def test_prepared_resume_still_checks_runtime_capability():
    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "SUPPORTED"])
    state = retry_snapshot(nodes)
    state["capabilities"] = RuntimeCapabilities(search_ready=False)
    state = create_router_graph(nodes).invoke(state)
    assert state["step_results"]["t16_step_1"].error.code == "CAPABILITY_UNAVAILABLE"
    assert counts == {"search": 1, "answer": 1, "rewrite": 1}


def test_clarification_resume_preserves_completed_insufficient_answer_and_budget():
    from artagent.graph import AssetRef, ResumeInput

    nodes, counts, _, _ = services(["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"])
    graph = create_router_graph(nodes)
    initial = request("화이트밸런스 어떻게 조절하고 바로 이 사진에 적용해줘.")
    initial["capabilities"] = RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True)
    state = graph.invoke(initial)
    assert state["response"].status == "WAITING_CLARIFICATION"
    completed = deepcopy(state["step_results"]["t16_step_1"])
    before = dict(counts)
    state["resume"] = ResumeInput("t16", state["clarification"].id, "노출 +0.5 EV로 보정해줘",
                                  assets=[AssetRef("raw", "RAW", "/tmp/t16-example.dng")])
    state = graph.invoke(state)
    assert state["step_results"]["t16_step_1"] == completed
    assert dict(counts) == before
    assert state["research_count"] == 1
