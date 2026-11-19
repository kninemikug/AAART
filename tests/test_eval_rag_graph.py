"""검색 평가가 실제 그래프를 타고 답변 직전에서 멈추는지 확인한다."""

from types import SimpleNamespace

from scripts import eval_rag_graph
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


def test_live_rewrite_requests_the_required_json_shape(monkeypatch):
    rewritten = "RawTherapee 5:4 custom crop settings"

    def generate(_instruction, prompt, _context, _version):
        assert '{"answer":"the single English search query","citation_ids":[]}' in prompt
        assert "Output ONLY the single search query" not in prompt
        assert "Preserve all critical technical identifiers" in prompt
        assert "5:4" in prompt
        return '{"answer":"RawTherapee 5:4 custom crop settings","citation_ids":[]}', {}, {
            "model_id": "test", "endpoint": "test",
        }

    def search_candidates(query, _encoder, **_settings):
        assert query == rewritten
        return []

    monkeypatch.setattr(eval_rag_graph, "generate_llm_response", generate)
    case = {"question": "RawTherapee에서 5:4 사용자 정의 크롭을 어떻게 설정하나요?",
            "source_type": "rawpedia", "allowed": ["rawpedia:Crop"]}
    result = evaluate(SimpleNamespace(search_candidates=search_candidates), None, "snapshot", None,
                      "test", case, live=False, live_rewrite=True)

    assert result["search_ok"]
    assert result["rewrite_calls"][0]["output"] == rewritten
