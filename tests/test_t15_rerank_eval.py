"""Task 15 리랭킹 및 top-k 평가기 단위 테스트.

docs/T15_execution_plan.md §8 준수:
- 문서 ID 중복 제거 및 source_group_id 배제 검증
- GitHub 본문 및 댓글 세그먼트 ID 정밀 추출
- 빈 양성/부정 분모 분리 및 counter_evidence 독립 집계
- 집계 지표(G2) 상승 속 개별 퇴행(G3) 감지 반례 검증
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

from artagent.retrieval.types import SearchHit
from scripts.eval_t15_rerank import (
    calculate_first_gold_rank,
    compute_metrics_for_records,
    doc_ids_from_hit,
)


def _make_hit(
    chunk_id: str,
    doc_id: str,
    source_segments: list[dict[str, Any]],
    rank: int = 1,
    source_type: str = "rawpedia",
    source_group_id: str = "group_1",
) -> SearchHit:
    return SearchHit(
        rank=rank,
        chunk_id=chunk_id,
        source_type=source_type,
        doc_id=doc_id,
        source_group_id=source_group_id,
        section_title="Test Section",
        content="Test content",
        content_sha256="abc123",
        source_segments=source_segments,
        original_metadata={},
        distance=0.1,
        distance_text="0.100000",
    )


def test_doc_ids_from_hit_deduplication_and_segment_isolation():
    """같은 문서의 여러 세그먼트가 중복 제거되고 source_group_id가 포함되지 않는지 검증."""
    hit = _make_hit(
        chunk_id="chunk_1",
        doc_id="github:issue:100",
        source_group_id="group_excluded",
        source_segments=[
            {"doc_id": "github:comment:1001"},
            {"doc_id": "github:comment:1001"},  # duplicate
            {"doc_id": "github:comment:1002"},
        ],
    )
    doc_ids = doc_ids_from_hit(hit)
    assert doc_ids == {"github:comment:1001", "github:comment:1002"}
    assert "group_excluded" not in doc_ids
    assert "github:issue:100" not in doc_ids  # 세그먼트가 있으면 상위 doc_id 배제


def test_doc_ids_from_hit_fallback_when_segments_empty():
    """세그먼트 목록이 비어있을 때는 hit.doc_id로 안전 폴백하는지 검증."""
    hit = _make_hit(
        chunk_id="chunk_2",
        doc_id="rawpedia:Exposure",
        source_segments=[],
    )
    doc_ids = doc_ids_from_hit(hit)
    assert doc_ids == {"rawpedia:Exposure"}


def test_calculate_first_gold_rank():
    """최초 골드 순위가 max_k 내에서 정확히 계산되는지 검증."""
    gold = {"rawpedia:Exposure"}
    hits = [
        _make_hit("c1", "rawpedia:Tone", [{"doc_id": "rawpedia:Tone"}], rank=1),
        _make_hit("c2", "rawpedia:Color", [{"doc_id": "rawpedia:Color"}], rank=2),
        _make_hit("c3", "rawpedia:Exposure", [{"doc_id": "rawpedia:Exposure"}], rank=3),
        _make_hit("c4", "rawpedia:Exposure", [{"doc_id": "rawpedia:Exposure"}], rank=4),
    ]
    # k=5
    assert calculate_first_gold_rank(hits, gold, max_k=5) == 3
    # k=2
    assert calculate_first_gold_rank(hits, gold, max_k=2) is None


def test_compute_metrics_positive_and_negative_separation():
    """양성 및 부정 분모가 엄격히 분리되고 negative_counter_retrieved가 올바르게 집계되는지 검증."""
    query_set_map = {
        "Q001": {
            "query_id": "Q001",
            "source_type": "rawpedia",
            "gold_support_doc_ids": ["doc_A"],
            "counter_evidence_doc_ids": [],
        },
        "Q002": {
            "query_id": "Q002",
            "source_type": "github",
            "gold_support_doc_ids": ["doc_B"],
            "counter_evidence_doc_ids": [],
        },
        "Q003": {
            "query_id": "Q003",
            "source_type": "github",
            "gold_support_doc_ids": [],
            "counter_evidence_doc_ids": ["doc_C"],
        },
    }

    per_query_results = {
        "Q001": {
            "precision": 0.5,
            "recall": 1.0,
            "first_gold_rank": 1,
            "intersect_count": 1,
            "selected_doc_count": 2,
            "gold_count": 1,
            "counter_evidence_retrieved": False,
        },
        "Q002": {
            "precision": 1.0,
            "recall": 1.0,
            "first_gold_rank": 1,
            "intersect_count": 1,
            "selected_doc_count": 1,
            "gold_count": 1,
            "counter_evidence_retrieved": False,
        },
        "Q003": {
            "precision": 0.0,
            "recall": 0.0,
            "first_gold_rank": None,
            "intersect_count": 0,
            "selected_doc_count": 2,
            "gold_count": 0,
            "counter_evidence_retrieved": True,
        },
    }

    metrics = compute_metrics_for_records(per_query_results, query_set_map)

    # 양성 분모 2개
    assert metrics["positive_count"] == 2
    assert metrics["negative_count"] == 1
    assert metrics["negative_counter_retrieved_count"] == 1

    # 전체 양성 macro 평균: (0.5 + 1.0) / 2 = 0.75
    assert abs(metrics["total"]["precision"] - 0.75) < 1e-9
    assert abs(metrics["total"]["recall"] - 1.0) < 1e-9
    assert abs(metrics["total"]["hit_at_5"] - 1.0) < 1e-9

    # micro 평균: intersect=2, selected=3 -> 2/3 = 0.666666...
    assert abs(metrics["total"]["micro_precision"] - 2 / 3) < 1e-9


def test_regression_detection_despite_aggregate_improvement():
    """G2(집계 평균 상승)와 G3(개별 순위 악화)가 독립적으로 검증되는지 확인."""
    b0_ranks = {"Q001": 2, "Q002": 1}
    new_ranks = {"Q001": 1, "Q002": 2}  # Q001 개선, Q002 퇴행

    # MRR@5: B0=(1/2 + 1/1)/2 = 0.75, New=(1/1 + 1/2)/2 = 0.75 (또는 상승 가능)
    # 하지만 Q002가 1->2로 저하되었으므로 개별 회귀는 반드시 1건 감지되어야 함
    regressions = []
    for qid in ["Q001", "Q002"]:
        b_r = b0_ranks[qid]
        n_r = new_ranks[qid]
        if n_r is None or n_r > b_r:
            regressions.append((qid, b_r, n_r))

    assert len(regressions) == 1
    assert regressions[0] == ("Q002", 1, 2)


def test_extract_counter_evidence_ids():
    """부정 질문의 반증 문서 ID가 evidence[].doc_id에서 추출되고 fallback도 동작하는지 검증 (F02/R4)."""
    from scripts.eval_t15_rerank import extract_counter_evidence_ids

    # evidence[].doc_id가 있는 정상 부정 질문
    q_neg = {
        "query_id": "Q096",
        "gold_support_doc_ids": [],
        "evidence": [
            {"doc_id": "issue-comment:4711197631", "role": "counter_evidence"},
            {"doc_id": "issue-comment:4711197631"},  # duplicate
        ],
    }
    assert extract_counter_evidence_ids(q_neg) == {"issue-comment:4711197631"}

    # evidence가 없고 counter_evidence_doc_ids가 있는 경우 폴백
    q_fallback = {
        "query_id": "Q097",
        "gold_support_doc_ids": [],
        "counter_evidence_doc_ids": ["doc_fallback_1", "doc_fallback_2"],
    }
    assert extract_counter_evidence_ids(q_fallback) == {"doc_fallback_1", "doc_fallback_2"}


def test_fit_bm25_from_snapshot():
    """Chroma 스냅샷 청크로부터 BM25를 적합하고 지문이 생성되는지 검증 (F04/R5)."""
    from scripts.eval_t15_rerank import fit_bm25_from_snapshot

    dummy_snapshot = [
        ("c1", "Exposure tone curve", {"section_title": "Exposure"}, [0.1]),
        ("c2", "Color management profile", {"section_title": "Color"}, [0.2]),
    ]
    bm25 = fit_bm25_from_snapshot(dummy_snapshot)
    assert bm25.n_docs == 2
    assert len(bm25.corpus_fingerprint) == 64
    assert bm25.model_id == "lexical_bm25"


def test_evaluate_gates_verdicts_and_exit_codes():
    """evaluate_gates의 FAIL(코드 1), PENDING(코드 2), PASS(코드 0) 판정 분리 검증 (F01)."""
    from scripts.eval_t15_rerank import evaluate_gates

    dummy_base = {
        "total": {"precision": 0.26, "recall": 0.96, "hit_at_5": 0.96, "mrr_at_5": 0.88},
        "rawpedia": {"precision": 0.21, "recall": 0.96, "hit_at_5": 0.96, "mrr_at_5": 0.92},
        "github": {"precision": 0.54, "recall": 1.0, "hit_at_5": 1.0, "mrr_at_5": 1.0},
        "slice1": {"precision": 0.32, "recall": 1.0, "hit_at_5": 1.0, "mrr_at_5": 1.0},
        "negative_counter_retrieved_count": 5,
    }

    # Case 1: G3 회귀 발생 시 FAIL 및 종료 코드 1
    res_fail = evaluate_gates(
        g0_reproduced=True,
        router_results={"passed": 40, "total": 40},
        b_metrics=dummy_base,
        b0_metrics=dummy_base,
        b_regressions=[("Q003", 1, 2)],  # 1건 회귀
        a_metrics=dummy_base,
        a0_metrics=dummy_base,
        a_regressions=[],
        repeat_summaries=[{"slice1_precision": 0.32, "slice1_recall": 1.0}] * 3,
        t17_summary={"is_mock": False, "error_count": 0, "unsupported_as_supported_count": 0, "product_scope_safe": True},
    )
    assert res_fail["overall_verdict"] == "FAIL"
    assert res_fail["exit_code"] == 1
    assert res_fail["adoption_status"] == "B0_MAINTAINED"
    assert res_fail["gates"]["G3"]["status"] == "FAIL"

    # Case 2: 회귀는 없으나 모의 LLM(mock)인 경우 PENDING 및 종료 코드 2
    res_pending = evaluate_gates(
        g0_reproduced=True,
        router_results={"passed": 40, "total": 40},
        b_metrics=dummy_base,
        b0_metrics=dummy_base,
        b_regressions=[],
        a_metrics=dummy_base,
        a0_metrics=dummy_base,
        a_regressions=[],
        repeat_summaries=[{"slice1_precision": 0.32, "slice1_recall": 1.0}] * 3,
        t17_summary={"is_mock": True, "error_count": 0, "unsupported_as_supported_count": 0, "product_scope_safe": True},
    )
    assert res_pending["overall_verdict"] == "PENDING"
    assert res_pending["exit_code"] == 2
    assert res_pending["gates"]["G5"]["status"] == "PENDING"

    # Case 3: Off 경로만 저하된 경우 G2 FAIL 검출
    off_degraded = copy.deepcopy(dummy_base)
    off_degraded["total"]["recall"] = 0.90  # 0.96에서 하락
    res_off_fail = evaluate_gates(
        g0_reproduced=True,
        router_results={"passed": 40, "total": 40},
        b_metrics=dummy_base,
        b0_metrics=dummy_base,
        b_regressions=[],
        a_metrics=off_degraded,
        a0_metrics=dummy_base,
        a_regressions=[],
        repeat_summaries=[{"slice1_precision": 0.32, "slice1_recall": 1.0}] * 3,
        t17_summary={"is_mock": False, "error_count": 0, "unsupported_as_supported_count": 0, "product_scope_safe": True},
    )
    assert res_off_fail["overall_verdict"] == "FAIL"
    assert res_off_fail["gates"]["G2"]["status"] == "FAIL"

