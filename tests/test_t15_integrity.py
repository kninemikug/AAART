"""T15 채택 판정과 오프라인 감사의 실제 실패 반례."""

from argparse import Namespace
import copy
import json
from pathlib import Path

import pytest

from scripts import eval_t15_rerank as evaluator


ROOT = Path(__file__).resolve().parents[1]


def test_missing_t17_and_single_repeat_cannot_pass():
    baseline = json.loads((ROOT / "data/eval/t15-rerank/plan_v2/protocol.json").read_text())["baseline_metrics"]
    result = evaluator.evaluate_gates(
        g0_reproduced=True, router_results={"passed": 40, "total": 40},
        b_metrics=baseline["B0"], b0_metrics=baseline["B0"], b_regressions=[],
        a_metrics=baseline["A0"], a0_metrics=baseline["A0"], a_regressions=[],
        repeat_summaries=[{"slice1_precision": 1.0, "slice1_recall": 1.0}],
        t17_summary=None,
    )
    assert result["overall_verdict"] != "PASS"
    assert result["exit_code"] != 0


def test_forged_gold_ids_without_provenance_cannot_pass(tmp_path):
    questions = json.loads((ROOT / "docs/search_eval_queries.json").read_text())["queries"]
    rows = []
    for condition in ("A", "B"):
        for question in questions:
            gold = question["gold_support_doc_ids"]
            ids = gold or [e["doc_id"] for e in question["evidence"]]
            rows.append({
                "condition": condition, "query_id": question["query_id"],
                "precision": 1.0 if gold else 0.0, "recall": 1.0 if gold else 0.0,
                "first_gold_rank": 1 if gold else None,
                "hits": [{"chunk_id": "NONEXISTENT", "content": "FORGED",
                          "source_segments": [{"doc_id": item} for item in ids]}],
            })
    (tmp_path / "records.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    (tmp_path / "repeat_records.jsonl").write_text(json.dumps({"slice1_precision": 1.0, "slice1_recall": 1.0}))
    (tmp_path / "router_records.jsonl").write_text("\n".join(json.dumps({"status": "PASS"}) for _ in range(40)))
    result = evaluator.cmd_check(Namespace(
        run_dir=str(tmp_path), protocol=None, selected_condition=None,
        manual_reviews=None, audit_output=None, validation_output=None,
    ))
    assert result != 0


def test_selected_json_alone_cannot_pass(tmp_path):
    (tmp_path / "selected_condition.json").write_text(json.dumps({
        "selected_condition": "invented", "adoption_status": "PASS",
    }))
    assert evaluator.cmd_check(Namespace(
        run_dir=str(tmp_path), protocol=None, selected_condition=None,
        manual_reviews=None, audit_output=None, validation_output=None,
    )) != 0


def test_selection_uses_passing_conditions():
    from scripts.eval_t15_rerank import select_condition

    failed = {"condition_id": "failed", "G2": False, "G3": True}
    passed = {"condition_id": "passed", "G2": True, "G3": True,
              "on_metrics": {"total": {"recall": 1.0, "precision": .5}},
              "off_metrics": {"total": {"recall": 1.0, "precision": .4}},
              "top_k": 5}
    assert select_condition([failed, passed])["condition_id"] == "passed"
    assert select_condition([failed]) is None


def test_expansion_is_required_without_passing_candidate():
    from scripts.eval_t15_rerank import should_expand_candidates

    assert should_expand_candidates([], {"Q024": None, "Q030": 1, "Q070": None})
    assert not should_expand_candidates([{"G2": True, "G3": True}],
                                        {"Q024": 1, "Q030": 1, "Q070": 2})


@pytest.fixture(scope="module")
def real_search():
    from scripts.t15_evaluation import RecordVerifier, digest
    protocol = {"inputs": {"queries": {"path": "docs/search_eval_queries.json"},
                           "reference": {"path": "docs/T08_2_t9_handoff_reference.json"},
                           "snapshot": {"path": evaluator.T14 + "/store_snapshot.json"},
                           "ab_records": {"path": evaluator.T14 + "/ab_records.jsonl"},
                           "generation_cache": {"path": evaluator.CACHE}},
                "runtime": {"threads": 4, "seed": 0}, "models": {"R1": {"max_length": 512}}}
    snapshot = json.loads((ROOT / protocol["inputs"]["snapshot"]["path"]).read_bytes())
    protocol["snapshot_fingerprint"] = digest(snapshot)
    verifier = RecordVerifier(protocol)
    with evaluator.runtime_store(protocol) as (store, session):
        search, hits = evaluator.search_record(store, session, verifier, "B", "Q001", 20)
        score = evaluator.score_record(evaluator.fit_bm25_from_snapshot(snapshot), "R3", search, hits)
        yield protocol, verifier, search, score, hits, store, session


@pytest.mark.parametrize("mutation", ["outside", "distance", "duplicate", "query", "source", "score", "windows"])
def test_actual_candidate_and_score_tampering_fails(real_search, mutation):
    _, verifier, original_search, original_score, _, _, _ = real_search
    search, score = copy.deepcopy(original_search), copy.deepcopy(original_score)
    config = {"model": "R3", "top_k": 5, "min_score": None}
    assert verifier.selected(search, score, config)[0]
    if mutation == "outside":
        search["candidates"][0]["chunk_id"] = "NONEXISTENT"
    elif mutation == "distance":
        search["candidates"][0]["distance"] += .1
    elif mutation == "duplicate":
        search["candidates"][1] = search["candidates"][0]
    elif mutation == "query":
        search["search_query"] += " changed"
    elif mutation == "source":
        search["source_type"] = "github"
    elif mutation == "score":
        score["scores"][0]["selection_score"] = float("nan")
    else:
        config["model"] = "R1"
        score["scores"][0]["windows"] = []
    with pytest.raises((ValueError, KeyError)):
        verifier.selected(search, score, config)


def test_actual_graph_routes_and_trace_are_checked(real_search, tmp_path):
    from scripts.t15_evaluation import read_rows, verify_routes
    protocol, _, _, _, _, store, session = real_search
    result = evaluator.run_routes(store, session, protocol, tmp_path)
    assert result == {"passed": 40, "total": 40, "verified": True}
    rows = read_rows(tmp_path / "routes.jsonl")
    rows[0]["trace"].remove("ROUTE")
    with pytest.raises(ValueError, match="trace"):
        verify_routes(rows)


def test_repeat_digest_ignores_timing_but_detects_score_change(real_search):
    from scripts.t15_evaluation import result_digest, score_result_digest
    protocol, verifier, search, score, hits, _, _ = real_search
    config = {"condition_id": "test", "model": "R3", "top_k": 5, "min_score": None}
    first, _ = evaluator.trial(search, score, hits, config, protocol, verifier.questions["Q001"])
    repeated = {**score, "repeat_index": 2, "elapsed_ms": 12345.0}
    assert score_result_digest(score) == score_result_digest(repeated)
    second, _ = evaluator.trial({**search, "repeat_index": 2}, repeated, hits, config, protocol, verifier.questions["Q001"])
    assert result_digest([first]) == result_digest([second])
    altered = copy.deepcopy(repeated)
    altered["scores"][0]["raw_score"] += .1
    assert score_result_digest(score) != score_result_digest(altered)


def test_audit_never_loads_models_or_writes_to_old_run(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("오프라인 감사가 추론/검색을 실행함")
    monkeypatch.setattr(evaluator, "runtime_store", forbidden)
    monkeypatch.setattr(evaluator, "load_reranker", forbidden)
    path = ROOT / "data/eval/t15-rerank/regression_v1/records.jsonl"
    before = evaluator.sha256_file(path)
    assert evaluator.cmd_check(Namespace(run_dir=str(path.parent), protocol=None, selected_condition=None,
                                         manual_reviews=None, audit_output=None, validation_output=None)) == 2
    assert evaluator.sha256_file(path) == before


@pytest.mark.parametrize("failure", [None, "missing_t17", "mock", "error", "scope", "repeat"])
def test_full_gate_contract_has_positive_and_negative_controls(failure):
    baseline = json.loads((ROOT / "data/eval/t15-rerank/plan_v2/protocol.json").read_bytes())["baseline_metrics"]
    repeats = [{"repeat_index": n, "record_count": 200, "result_digest": "same"} for n in (1, 2, 3)]
    live = {"live_verified": True, "manual_review_complete": True, "record_count": 62, "is_mock": False,
            "product_scope_safe": True, "error_count": 0, "unsupported_as_supported_count": 0}
    if failure == "missing_t17":
        live = None
    elif failure == "mock":
        live["is_mock"] = True
    elif failure == "error":
        live["error_count"] = 62
    elif failure == "scope":
        live["product_scope_safe"] = False
    elif failure == "repeat":
        repeats[2]["result_digest"] = "changed"
    result = evaluator.evaluate_gates(
        g0_reproduced=True, router_results={"verified": True, "passed": 40, "total": 40},
        b_metrics=baseline["B0"], b0_metrics=baseline["B0"], b_regressions=[],
        a_metrics=baseline["A0"], a0_metrics=baseline["A0"], a_regressions=[],
        repeat_summaries=repeats, t17_summary=live, coverage_complete=True)
    expected = "PASS" if failure is None else "PENDING" if failure in ("missing_t17", "mock") else "FAIL"
    assert result["overall_verdict"] == expected
    assert result["gates"]["G5"]["status"] == expected
