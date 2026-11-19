"""검색 평가가 실제 그래프를 타고 답변 직전에서 멈추는지 확인한다."""

from types import SimpleNamespace

from scripts.eval_rag_graph import evaluate, search_summary


def test_search_evaluation_uses_normal_route_without_remote_answer():
    queries = []

    def search_candidates(query, _encoder, *, candidate_k, source_type, source_group_ids):
        queries.append((query, candidate_k, source_type, source_group_ids))
        return []

    case = {"question": "ART GitHub에서 RAW 파일을 연 사례가 있나요?",
            "rewrite": "ART GitHub example of opening a RAW file", "source_type": "github",
            "allowed": ["issue:123"], "negative": False}
    result = evaluate(SimpleNamespace(search_candidates=search_candidates), None, "snapshot", None,
                      "test", case, live=False)

    assert queries == [(case["rewrite"], 20, "github", None)]
    assert result["trace"] == ["INTAKE", "ROUTE", "DISPATCH", "SEARCH_GITHUB"]
    assert result["route_matched"] and result["search_ok"]
    assert result["answers"] == []
    assert search_summary([result])["context_recall"] == 0
