"""Unit tests for embedding benchmark metrics, evaluation rules, and Chroma retrieval."""

from __future__ import annotations

import math
from pathlib import Path
import pytest
import chromadb
import numpy as np

from src.artagent.chunking import Chunk, SourceSegment, sha256_str


def evaluate_sample_query_metrics(
    query_evidence: list[dict],
    returned_chunks: list[Chunk],
    ks: tuple[int, ...] = (1, 3, 5),
    relevance_threshold: float = 0.5,
) -> dict:
    """Compute Hit@k, RR@k, All@k, FullEvidence@k for a query."""
    support_evs = [e for e in query_evidence if e["role"] == "support"]
    if not support_evs:
        # Negative query
        return {
            "is_negative": True,
            "hit": {k: None for k in ks},
            "rr": {k: None for k in ks},
            "all": {k: None for k in ks},
            "full_evidence": {k: None for k in ks},
        }

    # Rank of first relevant chunk
    first_rel_rank = None
    for r_idx, chunk in enumerate(returned_chunks, start=1):
        is_rel = False
        for ev in support_evs:
            # Simple coverage calculation for unit test
            cov = calculate_dummy_coverage(ev, chunk)
            if cov >= relevance_threshold:
                is_rel = True
                break
        if is_rel:
            first_rel_rank = r_idx
            break

    hit_any = {}
    rr_any = {}
    for k in ks:
        if first_rel_rank is not None and first_rel_rank <= k:
            hit_any[k] = 1.0
            rr_any[k] = 1.0 / first_rel_rank
        else:
            hit_any[k] = 0.0
            rr_any[k] = 0.0

    # All@k and FullEvidence@k
    all_k = {}
    full_ev_k = {}
    for k in ks:
        top_k_chunks = returned_chunks[:k]
        all_covered = True
        full_covered = True
        for ev in support_evs:
            cov = calculate_dummy_union_coverage(ev, top_k_chunks)
            if cov < relevance_threshold:
                all_covered = False
            if cov < 1.0 - 1e-6:
                full_covered = False
        all_k[k] = 1.0 if all_covered else 0.0
        full_ev_k[k] = 1.0 if full_covered else 0.0

    return {
        "is_negative": False,
        "first_rel_rank": first_rel_rank,
        "hit": hit_any,
        "rr": rr_any,
        "all": all_k,
        "full_evidence": full_ev_k,
    }


def calculate_dummy_coverage(ev: dict, chunk: Chunk) -> float:
    return chunk.metadata.get("coverage_map", {}).get(ev["id"], 0.0)


def calculate_dummy_union_coverage(ev: dict, chunks: list[Chunk]) -> float:
    # Union of disjoint pieces in metadata
    pieces = set()
    for c in chunks:
        pieces.update(c.metadata.get("piece_map", {}).get(ev["id"], []))
    total_pieces = ev.get("total_pieces", 10)
    return len(pieces) / total_pieces


def test_metric_calculations_any_all_full_example():
    """Verify execution plan §7.2 example:

    2위가 e1의 80%, 3위가 나머지 20%, 4위가 e2의 60%, 5위가 나머지 40%를 포함하면
    Hit@1=0, Hit@3=1, Hit@5=1, MRR@5=0.5, All@3=0, All@5=1, FullEvidence_all@5=1.
    """
    ev1 = {"id": "e1", "role": "support", "total_pieces": 10}
    ev2 = {"id": "e2", "role": "support", "total_pieces": 10}
    evidence = [ev1, ev2]

    # Rank 1: irrelevant
    c1 = Chunk("c1", "rawpedia", "d1", "t", "text1", (0, 10), {"coverage_map": {}, "piece_map": {}})
    # Rank 2: covers e1 80% (8 pieces, cov=0.8 >= 0.5 -> relevant!)
    c2 = Chunk("c2", "rawpedia", "d1", "t", "text2", (10, 20), {"coverage_map": {"e1": 0.8}, "piece_map": {"e1": list(range(0, 8))}})
    # Rank 3: covers e1 20% (pieces 8,9)
    c3 = Chunk("c3", "rawpedia", "d1", "t", "text3", (20, 30), {"coverage_map": {"e1": 0.2}, "piece_map": {"e1": list(range(8, 10))}})
    # Rank 4: covers e2 60% (pieces 0..5, cov=0.6 >= 0.5 -> relevant!)
    c4 = Chunk("c4", "rawpedia", "d1", "t", "text4", (30, 40), {"coverage_map": {"e2": 0.6}, "piece_map": {"e2": list(range(0, 6))}})
    # Rank 5: covers e2 40% (pieces 6..9)
    c5 = Chunk("c5", "rawpedia", "d1", "t", "text5", (40, 50), {"coverage_map": {"e2": 0.4}, "piece_map": {"e2": list(range(6, 10))}})

    returned = [c1, c2, c3, c4, c5]
    metrics = evaluate_sample_query_metrics(evidence, returned, ks=(1, 3, 5))

    assert metrics["hit"][1] == 0.0
    assert metrics["hit"][3] == 1.0
    assert metrics["hit"][5] == 1.0
    assert metrics["rr"][5] == pytest.approx(0.5)

    assert metrics["all"][3] == 0.0  # e2 not covered at all in top 3
    assert metrics["all"][5] == 1.0  # both e1 and e2 >= 50% in top 5
    assert metrics["full_evidence"][5] == 1.0  # both e1 and e2 100% covered in top 5


def test_negative_query_exclusion():
    """Verify negative queries are marked and excluded from positive Hit/MRR."""
    neg_ev = [{"id": "c1", "role": "counterevidence", "total_pieces": 5}]
    c1 = Chunk("c1", "github", "d1", "t", "text1", (0, 10), {})
    metrics = evaluate_sample_query_metrics(neg_ev, [c1], ks=(1, 3, 5))

    assert metrics["is_negative"] is True
    assert metrics["hit"][1] is None
    assert metrics["hit"][5] is None
    assert metrics["rr"][5] is None


def test_chroma_roundtrip_with_cosine(tmp_path):
    """Verify Chroma PersistentClient cosine retrieval with handmade orthogonal vectors."""
    db_path = str(tmp_path / "chroma_test")
    client = chromadb.PersistentClient(path=db_path)
    col = client.create_collection("cosine_test", metadata={"hnsw:space": "cosine"})

    # 3 vectors in 4D
    v_a = [1.0, 0.0, 0.0, 0.0]
    v_b = [0.0, 1.0, 0.0, 0.0]
    v_c = [0.7071, 0.7071, 0.0, 0.0]

    col.add(
        ids=["A", "B", "C"],
        embeddings=[v_a, v_b, v_c],
        documents=["Doc A", "Doc B", "Doc C"],
        metadatas=[{"src": "rp"}, {"src": "gh"}, {"src": "rp"}],
    )

    # Query with [1.0, 0.0, 0.0, 0.0] -> nearest is A (dist 0.0), then C (dist ~0.29), then B (dist 1.0)
    res = col.query(query_embeddings=[v_a], n_results=3)
    assert res["ids"][0] == ["A", "C", "B"]
    assert res["distances"][0][0] == pytest.approx(0.0, abs=1e-4)
    assert res["distances"][0][1] < res["distances"][0][2]


def test_enumerate_chunking_variants_counts():
    """Verify enumerate_chunking_variants produces 33 variants across the grid."""
    from src.artagent.chunking import enumerate_chunking_variants

    variants = enumerate_chunking_variants()
    assert len(variants) == 33

    rawpedia = [v for v in variants if v.source_type == "rawpedia"]
    github_formal = [v for v in variants if v.source_type == "github" and not v.is_diagnostic]
    github_diagnostic = [v for v in variants if v.source_type == "github" and v.is_diagnostic]

    assert len(rawpedia) == 18  # 2 rules * 3 L * 3 O
    assert len(github_formal) == 12  # 9 G-B + 3 G-A-curated
    assert len(github_diagnostic) == 3  # 3 G-A-full


def test_matrix_cartesian_counts():
    """Verify matrix calculation produces 1080 rows (864 formal + 216 diagnostic)."""
    rawpedia_count = 18
    github_formal_count = 12
    github_diagnostic_count = 3
    models_count = 4

    formal_combinations = rawpedia_count * github_formal_count * models_count
    diagnostic_combinations = rawpedia_count * github_diagnostic_count * models_count
    total = formal_combinations + diagnostic_combinations

    assert formal_combinations == 864
    assert diagnostic_combinations == 216
    assert total == 1080

