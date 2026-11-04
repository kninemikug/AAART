"""근거 부족 폴백의 요청 예산과 외부 호출 횟수 회귀."""

from collections import Counter
from copy import deepcopy
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
