"""Regression checks for complete, unrounded and independently reproducible runs."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.artagent.benchmark_validation import (
    aggregate_query_results,
    compare_retrieval_runs,
    select_stack,
    validate_query_log,
)


def query_result(
    query_id: str,
    source_type: str,
    rank: int | None,
    *,
    difficulty: str = "complex",
    full: float = 1.0,
) -> dict:
    """Create an evaluated query with explicit evidence and budget outcomes."""
    hit = {k: float(rank is not None and rank <= k) for k in (1, 3, 5)}
    rr = {k: 1.0 / rank if hit[k] else 0.0 for k in (1, 3, 5)}
    return {
        "query_id": query_id,
        "source_type": source_type,
        "difficulty": difficulty,
        "first_rel_rank": rank,
        "hit": hit,
        "rr": rr,
        "all": dict(hit),
        "full_evidence": {k: full if hit[k] else 0.0 for k in (1, 3, 5)},
        "budget_hit": {2048: hit[3], 4096: hit[5]},
        "budget_full_evidence": {2048: full if hit[3] else 0.0, 4096: full if hit[5] else 0.0},
        "top5_ids": [f"{query_id}-chunk-{i}" for i in range(5)],
        "top5_distances": [0.05 + i / 10.0 for i in range(5)],
    }


def test_aggregation_keeps_full_precision_and_actual_source_denominators():
    """Source means must not be rounded before macro or micro averaging."""
    records = [
        query_result("R1", "rawpedia", 3),
        query_result("R2", "rawpedia", None, difficulty="factoid", full=0.0),
        query_result("R3", "rawpedia", 5, full=0.0),
        query_result("G1", "github", 2, full=0.0),
        query_result("G2", "github", 1, difficulty="factoid"),
        query_result("N1", "github", 1, difficulty="negative"),
    ]

    metrics = aggregate_query_results(records)
    raw_mrr = (1 / 3 + 1 / 5) / 3
    github_mrr = (1 / 2 + 1) / 2
    assert metrics["positive_count"] == 5
    assert metrics["negative_count"] == 1
    assert metrics["rawpedia"]["count"] == 3
    assert metrics["github"]["count"] == 2
    assert metrics["rawpedia"]["mrr@5"] == pytest.approx(raw_mrr, abs=1e-14)
    assert metrics["github"]["mrr@5"] == github_mrr
    assert metrics["macro"]["mrr@5"] == pytest.approx((raw_mrr + github_mrr) / 2, abs=1e-14)
    assert metrics["micro"]["mrr@5"] == pytest.approx((1 / 3 + 1 / 5 + 1 / 2 + 1) / 5, abs=1e-14)
    assert metrics["rawpedia"]["mrr@5"] != round(raw_mrr, 4)
    assert metrics["micro"]["hit@1"] == pytest.approx(1 / 5, abs=1e-14)
    assert metrics["complex"]["rawpedia"]["count"] == 2
    assert metrics["complex"]["github"]["count"] == 1
    assert metrics["complex"]["macro"]["full_evidence@5"] == 0.25
    assert metrics["complex"]["micro"]["full_evidence@5"] == pytest.approx(1 / 3, abs=1e-14)
    assert metrics["complex"]["macro"]["budget_4096_full_evidence@5"] == 0.25
    assert len(metrics["query_results"]) == len(records)


def test_aggregation_accepts_json_string_metric_keys_without_changing_scores():
    records = [query_result("R1", "rawpedia", 3), query_result("G1", "github", 5)]
    in_memory = aggregate_query_results(records)
    from_json = aggregate_query_results(json.loads(json.dumps(records)))

    for group in ("rawpedia", "github", "macro", "micro"):
        assert from_json[group] == in_memory[group]
        assert from_json["complex"][group] == in_memory["complex"][group]


def experiment(
    experiment_id: str,
    *,
    mrr: float = 0.8096,
    hit: float = 0.94,
    overall_full: float = 0.95,
    complex_full: float = 0.70,
    p95: float = 0.08,
    vector_bytes: int = 1000,
    diagnostic: bool = False,
) -> dict:
    return {
        "experiment_id": experiment_id,
        "is_diagnostic": diagnostic,
        "metrics": {
            "macro": {"mrr@5": mrr, "hit@5": hit, "full_evidence@5": overall_full},
            "rawpedia": {"mrr@5": mrr - 0.01},
            "github": {"mrr@5": mrr + 0.01},
            "complex": {"macro": {"full_evidence@5": complex_full}},
        },
        "latency": {"p95_seconds": p95},
        "vector_bytes": vector_bytes,
    }


def test_selection_uses_complex_full_evidence_instead_of_overall_full_evidence():
    leader = experiment("leader")
    eligible = experiment(
        "eligible", mrr=0.8035, hit=0.938, overall_full=0.30, complex_full=0.75, p95=0.03
    )
    loses_complex_evidence = experiment(
        "loses-complex", mrr=0.804, overall_full=0.99, complex_full=0.60, p95=0.001
    )

    result = select_stack([loses_complex_evidence, eligible, leader])

    assert result["quality_leader"]["experiment_id"] == "leader"
    assert result["selected"]["experiment_id"] == "eligible"
    assert set(result["close_candidate_ids"]) == {"leader", "eligible"}


def test_selection_quality_tie_uses_complex_evidence_before_latency():
    overall_winner = experiment("overall-winner", overall_full=0.99, complex_full=0.50, p95=0.01)
    complex_winner = experiment("complex-winner", overall_full=0.30, complex_full=0.90, p95=0.08)

    result = select_stack([overall_winner, complex_winner])

    assert result["quality_leader"]["experiment_id"] == "complex-winner"
    assert result["selected"]["experiment_id"] == "complex-winner"


def test_selection_does_not_round_scores_before_identifying_quality_leader():
    lower = experiment("lower", mrr=0.80001, p95=0.001)
    higher = experiment("higher", mrr=0.80004, p95=0.05)

    result = select_stack([lower, higher])

    assert result["quality_leader"]["experiment_id"] == "higher"
    assert result["selected"]["experiment_id"] == "lower"


@pytest.mark.parametrize("violation", ["macro_mrr", "macro_hit", "rawpedia_mrr", "github_mrr"])
def test_selection_rejects_candidates_outside_declared_near_quality_bounds(violation):
    leader = experiment("leader")
    candidate = experiment("too-far", mrr=0.8046, p95=0.001)
    if violation == "macro_mrr":
        candidate["metrics"]["macro"]["mrr@5"] = 0.79949
    elif violation == "macro_hit":
        candidate["metrics"]["macro"]["hit@5"] = 0.9299
    elif violation == "rawpedia_mrr":
        candidate["metrics"]["rawpedia"]["mrr@5"] = 0.7746
        candidate["metrics"]["github"]["mrr@5"] = 0.8346
    else:
        candidate["metrics"]["rawpedia"]["mrr@5"] = 0.8346
        candidate["metrics"]["github"]["mrr@5"] = 0.7746

    result = select_stack([candidate, leader])

    assert result["selected"]["experiment_id"] == "leader"
    assert result["close_candidate_ids"] == ["leader"]


def test_selection_excludes_diagnostic_rows_and_breaks_cost_ties_by_id():
    rows = [
        experiment("z", p95=0.02, vector_bytes=500),
        experiment("a", p95=0.02, vector_bytes=500),
        experiment("bigger", p95=0.02, vector_bytes=600),
        experiment("diagnostic", mrr=1.0, hit=1.0, p95=0.0, diagnostic=True),
    ]

    result = select_stack(rows)

    assert result["quality_leader"]["experiment_id"] == "a"
    assert result["selected"]["experiment_id"] == "a"
    assert "diagnostic" not in result["close_candidate_ids"]


@pytest.mark.parametrize("status", ["failed", "pending"])
def test_selection_rejects_incomplete_registered_experiments(status):
    incomplete = experiment("not-complete", mrr=0.1)
    incomplete["status"] = status

    with pytest.raises(ValueError):
        select_stack([experiment("complete"), incomplete])


def retrieval_run() -> dict:
    records = [
        query_result("R1", "rawpedia", 1),
        query_result("R2", "rawpedia", 2),
        query_result("G1", "github", 1),
    ]
    return {"metrics": aggregate_query_results(records), "query_results": records}


def test_reproduction_accepts_identical_results_and_small_distance_noise():
    expected = retrieval_run()
    recomputed = deepcopy(expected)
    recomputed["query_results"][0]["top5_distances"][0] += 5e-6

    assert isinstance(compare_retrieval_runs(expected, recomputed), dict)


def test_reproduction_rejects_rank_swaps_hidden_by_equal_aggregate_mrr():
    expected = retrieval_run()
    recomputed = deepcopy(expected)
    recomputed["query_results"][0] = query_result("R1", "rawpedia", 2)
    recomputed["query_results"][1] = query_result("R2", "rawpedia", 1)
    recomputed["metrics"] = aggregate_query_results(recomputed["query_results"])
    assert recomputed["metrics"]["macro"] == expected["metrics"]["macro"]
    assert recomputed["metrics"]["complex"]["macro"] == expected["metrics"]["complex"]["macro"]

    with pytest.raises(ValueError):
        compare_retrieval_runs(expected, recomputed)


def test_reproduction_rejects_point_zero_zero_five_aggregate_drift():
    """The old 0.01 MRR allowance falsely accepted this mismatch."""
    expected = retrieval_run()
    recomputed = deepcopy(expected)
    recomputed["metrics"]["macro"]["mrr@5"] -= 0.005

    with pytest.raises(ValueError):
        compare_retrieval_runs(expected, recomputed)


@pytest.mark.parametrize(
    "mutation", ["query_id", "missing_evidence", "full_evidence", "budget", "top5_ids", "distance"]
)
def test_reproduction_rejects_changed_query_evidence_or_search_outputs(mutation):
    expected = retrieval_run()
    recomputed = deepcopy(expected)
    record = recomputed["query_results"][0]
    if mutation == "query_id":
        record["query_id"] = "unexpected-query"
    elif mutation == "missing_evidence":
        del record["full_evidence"]
    elif mutation == "full_evidence":
        record["full_evidence"][5] = 0.0
    elif mutation == "budget":
        record["budget_full_evidence"][2048] = 0.0
    elif mutation == "top5_ids":
        record["top5_ids"][0] = "other-chunk"
    else:
        record["top5_distances"][0] += 2e-5

    with pytest.raises(ValueError):
        compare_retrieval_runs(expected, recomputed)


def query_logs(query_ids: list[str], repeat_count: int = 3) -> list[dict]:
    records = []
    for query_id in query_ids:
        result = query_result(query_id, "rawpedia", 1)
        for repeat in range(repeat_count):
            records.append({
                "experiment_id": "experiment-1",
                "query_id": query_id,
                "repeat": repeat,
                "query_input_hash": f"input-hash-{query_id}",
                "total_seconds": 0.01 + repeat / 1000,
                "top5": [
                    {"chunk_id": chunk_id, "distance": distance}
                    for chunk_id, distance in zip(result["top5_ids"], result["top5_distances"])
                ],
                "query_result": deepcopy(result),
            })
    return records


def test_query_log_accounts_for_every_real_query_and_repeat():
    records = query_logs(["Q001", "Q002"])

    validation = validate_query_log(records, ["Q001", "Q002"], repeat_count=3)

    assert validation["query_count"] == 2
    assert validation["observations_count"] == 6


def test_query_log_rejects_300_observations_faked_with_a_duplicate():
    query_ids = [f"Q{i:03d}" for i in range(1, 101)]
    records = query_logs(query_ids)
    records[-1] = deepcopy(records[0])
    assert len(records) == 300

    with pytest.raises(ValueError):
        validate_query_log(records, query_ids, repeat_count=3)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_hash", "wrong_repeat", "wrong_query_result"])
def test_query_log_rejects_incomplete_or_inconsistent_observations(mutation):
    records = query_logs(["Q001", "Q002"])
    if mutation == "missing":
        records.pop()
    elif mutation == "extra":
        records.append(deepcopy(records[0]))
    elif mutation == "wrong_hash":
        records[1]["query_input_hash"] = "different-input"
    elif mutation == "wrong_repeat":
        records[1]["repeat"] = 3
    else:
        records[1]["query_result"]["query_id"] = "Q999"

    with pytest.raises(ValueError):
        validate_query_log(records, ["Q001", "Q002"], repeat_count=3)


def test_registered_union_has_all_5502_combinations_and_group_denominators():
    from collections import Counter
    from scripts.complete_embedding_validation import expected_keys

    keys = expected_keys()
    assert len(keys) == 5502
    assert Counter(k[0] for k in keys) == {
        "native-common-256": 1080, "bge-512": 1548, "e5-512": 774, "pooled-common-256": 2100,
    }
    assert sum("full-thread" in k[3] for k in keys) == 786


def test_raw_log_rejects_corrupted_artifact_hash(tmp_path):
    from scripts.verify_embedding_benchmark import write_log, read_log

    records = query_logs(["Q001"])
    reference = write_log(tmp_path / "trace.jsonl.gz", records)
    assert read_log(reference) == json.loads(json.dumps(records))
    (tmp_path / "trace.jsonl.gz").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_log(reference)


def test_chroma_applied_schema_preserves_index_thread_setting(tmp_path):
    import chromadb
    import numpy as np
    from scripts.verify_embedding_benchmark import build_collection, HNSW
    from src.artagent.chunking import Chunk

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    chunks = [Chunk("chunk", "rawpedia", "doc", "section", "body", (0, 4), {})]
    col = build_collection(client, "schema_regression", chunks, np.array([[1., 0.]], dtype=np.float32))
    schema = col.schema.keys["#embedding"].float_list.vector_index.config
    assert schema.space == "cosine"
    assert schema.hnsw.num_threads == HNSW["num_threads"] == 1
    assert schema.hnsw.ef_search == schema.hnsw.ef_construction == 200
    client.delete_collection(col.name)
