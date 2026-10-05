"""Strict, dependency-free validation for the T08-2 retrieval benchmark."""

from __future__ import annotations

import math
from typing import Any


def _value(record: dict, field: str, key: int) -> float:
    values = record[field]
    value = values[key] if key in values else values[str(key)]
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite {field}[{key}]")
    return value


def aggregate_query_results(query_results, ks=(1, 3, 5), context_budgets=(2048, 4096)) -> dict:
    """Aggregate actual positive denominators without intermediate rounding."""
    records = list(query_results)
    ids = [r["query_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate query IDs")
    positives = [r for r in records if r["difficulty"] != "negative"]
    names = [(f"{label}@{k}", field, k) for k in ks for label, field in
             (("hit", "hit"), ("mrr", "rr"), ("all", "all"), ("full_evidence", "full_evidence"))]
    names += [(f"budget_{b}_{label}@5", field, b) for b in context_budgets for label, field in
              (("hit", "budget_hit"), ("full_evidence", "budget_full_evidence"))]

    def summary(subset):
        groups = {}
        for source in ("rawpedia", "github"):
            rows = [r for r in subset if r["source_type"] == source]
            groups[source] = {"count": len(rows), **{
                name: math.fsum(_value(r, field, key) for r in rows) / len(rows) if rows else 0.0
                for name, field, key in names}}
        populated = [g for g in groups.values() if g["count"]]
        groups["macro"] = {name: math.fsum(g[name] for g in populated) / len(populated)
                           if populated else 0.0 for name, _, _ in names}
        groups["micro"] = {name: math.fsum(_value(r, field, key) for r in subset) / len(subset)
                           if subset else 0.0 for name, field, key in names}
        return groups

    return {**summary(positives), "complex": summary([r for r in positives if r["difficulty"] == "complex"]),
            "positive_count": len(positives), "negative_count": len(records) - len(positives),
            "query_results": records}


def select_stack(experiments) -> dict:
    """Apply the declared quality order, then cost order within the near band."""
    rows = list(experiments)
    if any(r.get("status", "completed") != "completed" for r in rows):
        raise ValueError("Selection requires every registered experiment to be completed")
    formal = [r for r in rows if not r["is_diagnostic"]]
    if not formal:
        raise ValueError("No formal experiments")
    def evidence(r):
        return r["metrics"]["complex"]["macro"]["full_evidence@5"]
    def cost(r):
        return (r["latency"]["p95_seconds"], r["vector_bytes"], r["experiment_id"])
    ranked = sorted(formal, key=lambda r: (-r["metrics"]["macro"]["mrr@5"],
                    -r["metrics"]["macro"]["hit@5"], -evidence(r), *cost(r)))
    leader = ranked[0]
    near = [r for r in ranked
            if abs(r["metrics"]["macro"]["mrr@5"] - leader["metrics"]["macro"]["mrr@5"]) <= 0.01
            and abs(r["metrics"]["macro"]["hit@5"] - leader["metrics"]["macro"]["hit@5"]) <= 0.01
            and all(abs(r["metrics"][s]["mrr@5"] - leader["metrics"][s]["mrr@5"]) <= 0.02
                    for s in ("rawpedia", "github"))
            and evidence(r) >= evidence(leader)]
    return {"quality_leader": leader, "selected": min(near, key=cost),
            "close_candidate_ids": [r["experiment_id"] for r in near]}


def _compare(expected: Any, actual: Any, tolerance: float, path: str = ""):
    if isinstance(expected, dict):
        # JSON round trips stringify integer metric keys.
        e, a = {str(k): v for k, v in expected.items()}, {str(k): v for k, v in actual.items()}
        if e.keys() != a.keys():
            raise ValueError(f"Different fields at {path}")
        for key in e:
            _compare(e[key], a[key], tolerance, f"{path}/{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"Different lengths at {path}")
        for i, (e, a) in enumerate(zip(expected, actual)):
            _compare(e, a, tolerance, f"{path}/{i}")
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if actual is None or not math.isfinite(float(actual)) or abs(expected - actual) > tolerance:
            raise ValueError(f"Numeric mismatch at {path}: {expected} != {actual}")
    elif expected != actual:
        raise ValueError(f"Mismatch at {path}: {expected!r} != {actual!r}")


def compare_retrieval_runs(expected: dict, recomputed: dict, metric_tolerance=1e-9) -> dict:
    """Reject aggregate agreement that hides per-query rank/evidence drift."""
    fields = ("source_type", "difficulty", "first_rel_rank", "hit", "rr", "all", "full_evidence",
              "budget_hit", "budget_full_evidence", "top5_ids", "top5_distances")
    def by_id(run):
        rows = run["query_results"]
        result = {r["query_id"]: r for r in rows}
        if len(result) != len(rows):
            raise ValueError("Duplicate query IDs in reproduction")
        return result
    e, a = by_id(expected), by_id(recomputed)
    if e.keys() != a.keys():
        raise ValueError("Reproduction query set mismatch")
    for qid in e:
        for field in fields:
            if field not in e[qid] or field not in a[qid]:
                raise ValueError(f"Missing {qid}/{field}")
            _compare(e[qid][field], a[qid][field], 1e-5 if field == "top5_distances" else metric_tolerance,
                     f"{qid}/{field}")
        for field in ("evidence_coverage", "packing"):
            if field in e[qid] or field in a[qid]:
                _compare(e[qid].get(field), a[qid].get(field), metric_tolerance, f"{qid}/{field}")
    for group in ("rawpedia", "github", "macro", "micro", "complex"):
        _compare(expected["metrics"][group], recomputed["metrics"][group], metric_tolerance, group)
    return {"status": "passed", "query_count": len(e), "metric_tolerance": metric_tolerance,
            "distance_tolerance": 1e-5}


def validate_query_log(records, expected_query_ids, repeat_count) -> dict:
    """Require exactly one genuine observation for every query/repeat pair."""
    expected_ids = set(expected_query_ids)
    if len(expected_ids) != len(expected_query_ids) or repeat_count < 1:
        raise ValueError("Invalid query/repeat contract")
    seen, inputs, experiment_ids = set(), {}, set()
    runs = {r: [] for r in range(repeat_count)}
    for record in records:
        qid, rep = record["query_id"], record["repeat"]
        if qid not in expected_ids or rep not in runs or (qid, rep) in seen:
            raise ValueError("Unexpected or duplicate query/repeat")
        seen.add((qid, rep))
        experiment_ids.add(record["experiment_id"])
        digest = record["query_input_hash"]
        if not digest or inputs.setdefault(qid, digest) != digest:
            raise ValueError("Query input hash drift")
        if record["query_result"]["query_id"] != qid:
            raise ValueError("Wrong query result")
        elapsed = float(record["total_seconds"])
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError("Invalid timer observation")
        top5 = record["top5"]
        result = record["query_result"]
        if [r["chunk_id"] for r in top5] != result["top5_ids"]:
            raise ValueError("Logged top5 IDs differ from evaluated result")
        _compare([r["distance"] for r in top5], result["top5_distances"], 0.0)
        runs[rep].append(result)
    if len(seen) != len(expected_ids) * repeat_count or len(experiment_ids) != 1:
        raise ValueError("Incomplete query/repeat log")
    # Repeats must preserve retrieval quality, not just the timing sample count.
    baseline = {"query_results": sorted(runs[0], key=lambda r: r["query_id"])}
    baseline["metrics"] = aggregate_query_results(baseline["query_results"])
    for rep in range(1, repeat_count):
        current = {"query_results": sorted(runs[rep], key=lambda r: r["query_id"])}
        current["metrics"] = aggregate_query_results(current["query_results"])
        compare_retrieval_runs(baseline, current)
    return {"status": "passed", "query_count": len(expected_ids), "observations_count": len(seen)}
