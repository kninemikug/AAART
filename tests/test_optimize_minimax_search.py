"""검색 최적화가 실제 순위·임계값 계약과 근거 보존 기준을 지킨다."""

from dataclasses import asdict
from types import SimpleNamespace

from artagent.retrieval.rerank import rerank_candidates
from scripts.optimize_minimax_search import BASELINE, Configuration, choose, chosen_hits


def test_grid_uses_runtime_cut_before_score_threshold():
    hits = [SimpleNamespace(chunk_id=str(i), rank=i, distance=distance)
            for i, distance in enumerate((0.0, 0.1, 0.5), start=1)]
    scores = {"1": 0.49, "2": 0.8, "3": 0.9}
    reranker = SimpleNamespace(score_hit=lambda _query, hit: (scores[hit.chunk_id], scores[hit.chunk_id], 1))
    config = Configuration("minilm", "bm25", 3, 0.25, 0.5, top_k=2)

    direct = rerank_candidates("query", hits, reranker, **{
        k: getattr(config, k) for k in ("top_k", "min_score", "rerank_weight")
    })

    assert chosen_hits(hits, scores, config) == direct.selected_hits == [hits[1]]


def test_choice_preserves_each_source_recall_and_counterevidence():
    baseline = {"name": BASELINE.name, "settings": asdict(BASELINE),
                "metrics": {"negative_evidence": 5, "recall_by_source": {"rawpedia": 0.9, "github": 0.9},
                            "context_recall": 0.9, "context_precision": 0.25, "mrr": 0.8}}
    better = {**baseline, "name": "better", "settings": {**baseline["settings"], "candidate_k": 10},
              "metrics": {**baseline["metrics"], "context_precision": 0.3}}
    lost_evidence = {**better, "name": "lost", "metrics": {**better["metrics"], "negative_evidence": 4,
                                                           "context_recall": 1.0}}
    lost_github = {**better, "name": "lost-source", "metrics": {**better["metrics"], "context_recall": 0.95,
                                                                 "recall_by_source": {"rawpedia": 1.0, "github": 0.8}}}

    assert choose([baseline, better, lost_evidence, lost_github]) == better
