"""Tests for reranking, candidate search, and top-k tuning (Task 15 / A-15)."""

from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest

from artagent.graph import (
    AgentState,
    PlanStep,
    RequestInput,
    RouteDecision,
    create_search_github_node,
    create_search_nodes,
    create_search_rawpedia_node,
)
from artagent.graph.state import Path
from artagent.retrieval import (
    BM25Reranker,
    CrossEncoderReranker,
    RerankRecord,
    RerankResult,
    SearchHit,
    rerank_candidates,
)
from artagent.retrieval.provenance import sha256_str


def _create_hit(
    rank: int,
    chunk_id: str,
    doc_id: str = "rawpedia:Doc1",
    section_title: str = "Section 1",
    content: str = "This is test content for retrieval.",
    distance: float = 0.2,
    source_type: str = "rawpedia",
    source_group_id: str = "rawpedia:Doc1",
) -> SearchHit:
    content_sha = sha256_str(content)
    segment = {
        "doc_id": doc_id,
        "ref_id": doc_id,
        "source_path": "data/rawpedia/Doc1.md",
        "target_url": "https://rawpedia.rawtherapee.com/doc1/",
        "content_char_start": 0,
        "content_char_end": len(content),
        "char_start": 0,
        "char_end": len(content),
        "json_pointer": None,
        "source_file_sha256": "f" * 64,
        "segment_sha256": content_sha,
    }
    return SearchHit(
        rank=rank,
        chunk_id=chunk_id,
        source_type=source_type,
        doc_id=doc_id,
        source_group_id=source_group_id,
        section_title=section_title,
        content=content,
        content_sha256=content_sha,
        source_segments=[segment],
        original_metadata={"source_segments": [segment]},
        distance=distance,
        distance_text=f"{distance:.6f}",
    )


class DummyReranker:
    """테스트용 점수 주입 리랭커."""

    def __init__(self, scores: dict[str, float], model_id: str = "dummy-reranker"):
        self.scores = scores
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def score_hit(self, query: str, hit: SearchHit) -> tuple[float, float, int]:
        raw = self.scores.get(hit.chunk_id, 0.0)
        sel = 1.0 / (1.0 + math.exp(-raw))
        return raw, sel, 1


def test_rerank_candidates_sorting_and_top_k():
    h1 = _create_hit(1, "c1", distance=0.1)
    h2 = _create_hit(2, "c2", distance=0.2)
    h3 = _create_hit(3, "c3", distance=0.3)
    h4 = _create_hit(4, "c4", distance=0.4)

    # c3 gets highest score, c1 second, c4 third, c2 lowest
    scores = {"c1": 1.0, "c2": -2.0, "c3": 3.0, "c4": 0.5}
    reranker = DummyReranker(scores)

    res = rerank_candidates("query", [h1, h2, h3, h4], reranker, top_k=2)

    assert len(res.selected_hits) == 2
    assert res.selected_hits[0].chunk_id == "c3"
    assert res.selected_hits[1].chunk_id == "c1"

    # Check records
    records_by_id = {r.hit.chunk_id: r for r in res.records}
    assert records_by_id["c3"].rerank_rank == 1
    assert records_by_id["c3"].final_rank == 1
    assert records_by_id["c3"].excluded_reason is None

    assert records_by_id["c1"].rerank_rank == 2
    assert records_by_id["c1"].final_rank == 2
    assert records_by_id["c1"].excluded_reason is None

    assert records_by_id["c4"].rerank_rank == 3
    assert records_by_id["c4"].final_rank is None
    assert records_by_id["c4"].excluded_reason == "top_k_cut"

    assert records_by_id["c2"].rerank_rank == 4
    assert records_by_id["c2"].final_rank is None
    assert records_by_id["c2"].excluded_reason == "top_k_cut"


def test_rerank_candidates_tie_sorting():
    # When selection scores are equal, sort by dense_rank ascending, then chunk_id ascending
    h1 = _create_hit(1, "b_chunk", distance=0.1)
    h2 = _create_hit(2, "a_chunk", distance=0.2)
    h3 = _create_hit(3, "c_chunk", distance=0.3)

    scores = {"b_chunk": 1.0, "a_chunk": 1.0, "c_chunk": 1.0}
    reranker = DummyReranker(scores)

    res = rerank_candidates("query", [h1, h2, h3], reranker, top_k=3)
    assert [h.chunk_id for h in res.selected_hits] == ["b_chunk", "a_chunk", "c_chunk"]


def test_rerank_candidates_min_score_threshold_no_backfill():
    h1 = _create_hit(1, "c1")
    h2 = _create_hit(2, "c2")
    h3 = _create_hit(3, "c3")

    # c1 has sel_score ~0.88, c2 has sel_score ~0.50 (raw=0.0), c3 has sel_score ~0.95
    # sorting: c3 (0.95), c1 (0.88), c2 (0.50)
    scores = {"c1": 2.0, "c2": 0.0, "c3": 3.0}
    reranker = DummyReranker(scores)

    # top_k=2: candidates inside top_k are c3, c1.
    # threshold 0.90 drops c1 (sel_score ~0.88).
    # Crucially, c2 (which is outside top_k or below) MUST NOT backfill!
    res = rerank_candidates("query", [h1, h2, h3], reranker, top_k=2, min_score=0.90)

    assert len(res.selected_hits) == 1
    assert res.selected_hits[0].chunk_id == "c3"

    rec_c1 = [r for r in res.records if r.hit.chunk_id == "c1"][0]
    assert rec_c1.rerank_rank == 2
    assert rec_c1.final_rank is None
    assert rec_c1.excluded_reason == "min_score_threshold"

    rec_c2 = [r for r in res.records if r.hit.chunk_id == "c2"][0]
    assert rec_c2.rerank_rank == 3
    assert rec_c2.final_rank is None
    assert rec_c2.excluded_reason == "top_k_cut"


def test_rerank_candidates_validation():
    h = _create_hit(1, "c1")
    reranker = DummyReranker({"c1": 1.0})

    with pytest.raises(ValueError, match="top_k는 양의 정수"):
        rerank_candidates("query", [h], reranker, top_k=0)

    with pytest.raises(ValueError, match="min_score는 0.0과 1.0 사이"):
        rerank_candidates("query", [h], reranker, top_k=5, min_score=-0.1)

    with pytest.raises(ValueError, match="min_score는 0.0과 1.0 사이"):
        rerank_candidates("query", [h], reranker, top_k=5, min_score=1.5)


def test_bm25_reranker_scoring():
    corpus = [
        "Exposure compensation and highlight reconstruction in RawTherapee",
        "Color management ICC profiles and monitor calibration",
        "Noise reduction and sharpening filters",
    ]
    bm25 = BM25Reranker(corpus, model_id="test-bm25")
    assert bm25.n_docs == 3
    assert bm25.model_id == "test-bm25"

    h1 = _create_hit(1, "c1", content="Exposure compensation adjusts the image brightness.")
    h2 = _create_hit(2, "c2", content="Noise reduction smooths grainy artifacts.")

    raw1, sel1, w1 = bm25.score_hit("exposure compensation", h1)
    raw2, sel2, w2 = bm25.score_hit("exposure compensation", h2)

    assert raw1 > raw2
    assert sel1 > sel2
    assert 0.0 <= sel1 < 1.0
    assert 0.0 <= sel2 < 1.0
    assert w1 == 1


def test_cross_encoder_window_scoring():
    # Use ms-marco-MiniLM-L6-v2 (cached locally)
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L6-v2")
    assert reranker.model_id == "cross-encoder/ms-marco-MiniLM-L6-v2"

    short_hit = _create_hit(
        1,
        "short",
        section_title="Auto Levels",
        content="Auto levels adjusts exposure compensation based on the histogram.",
    )
    raw, sel, w_cnt = reranker.score_hit("auto levels exposure", short_hit)
    assert isinstance(raw, float)
    assert 0.0 <= sel <= 1.0
    assert w_cnt == 1

    # Long content to trigger windowing
    long_content = "The quick brown fox jumps over the lazy dog. " * 80
    long_hit = _create_hit(2, "long", section_title="Fox Story", content=long_content)
    raw_long, sel_long, w_long = reranker.score_hit("brown fox", long_hit)
    assert w_long >= 2
    assert 0.0 <= sel_long <= 1.0


def test_cross_encoder_query_overflow_error():
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L6-v2", max_length=100)
    huge_query = "word " * 120
    hit = _create_hit(1, "c1", content="normal content")

    with pytest.raises(ValueError, match=r"질의 토큰 수.*초과"):
        reranker.score_hit(huge_query, hit)


def test_graph_search_node_with_reranker():
    mock_store = MagicMock()
    mock_session = MagicMock()

    h1 = _create_hit(1, "c1", distance=0.1)
    h2 = _create_hit(2, "c2", distance=0.2)
    h3 = _create_hit(3, "c3", distance=0.3)

    mock_store.search_candidates.return_value = [h1, h2, h3]
    reranker = DummyReranker({"c1": 0.0, "c2": 2.0, "c3": 1.0})

    observed = []
    node = create_search_rawpedia_node(
        mock_store,
        mock_session,
        candidate_k=10,
        top_k=2,
        reranker=reranker,
        observe=observed.append,
    )

    state: AgentState = {
        "request": RequestInput(request_id="req1", text="test query"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=Path.DOC_QA, query="test query")]
        ),
        "cursor": 0,
        "trace": [],
    }

    result = node(state)
    assert result["error"] is None
    bundle = result["retrieval"]
    assert bundle.source_filter == "RAWPEDIA"

    # c2 was scored highest, c3 second
    obs = observed[0]
    assert obs["candidate_k"] == 10
    assert obs["top_k"] == 2
    assert "candidates" in obs
    assert len(obs["candidates"]) == 3
    assert "rerank" in obs
    assert obs["rerank"]["selected_chunk_ids"] == ["c2", "c3"]


def test_graph_search_node_configuration_validation():
    mock_store = MagicMock()
    mock_session = MagicMock()

    with pytest.raises(ValueError, match=r"top_k.*candidate_k.*보다 클 수 없습니다"):
        create_search_nodes(mock_store, mock_session, candidate_k=5, top_k=10)

    with pytest.raises(ValueError, match="리랭커가 없는 조건에서는 min_score를 설정할 수 없습니다"):
        create_search_nodes(mock_store, mock_session, reranker=None, min_score=0.5)

    with pytest.raises(ValueError, match="양의 정수여야 합니다"):
        create_search_nodes(mock_store, mock_session, candidate_k=0)


def test_graph_search_node_reranker_failure_gives_search_unavailable():
    mock_store = MagicMock()
    mock_session = MagicMock()
    h1 = _create_hit(1, "c1")
    mock_store.search_candidates.return_value = [h1]

    failing_reranker = MagicMock()
    failing_reranker.score_hit.side_effect = RuntimeError("Reranker inference exploded")

    node = create_search_rawpedia_node(
        mock_store,
        mock_session,
        candidate_k=10,
        top_k=5,
        reranker=failing_reranker,
    )

    state: AgentState = {
        "request": RequestInput(request_id="req1", text="test query"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=Path.DOC_QA, query="test query")]
        ),
        "cursor": 0,
        "trace": [],
    }

    result = node(state)
    assert result["error"] is not None
    assert result["error"].code == "SEARCH_UNAVAILABLE"
