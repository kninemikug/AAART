"""Reproduce Gate B integrity gaps using the frozen 47-record v2 run.

These checks never generate an answer or change the frozen evidence.  An old
record may become PENDING when a newer schema needs evidence it did not capture;
an independently provable contradiction must still be FAIL.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.check_t17_answer import evaluate_gate_b


ROOT = Path(__file__).resolve().parents[1]
FROZEN_RUN = ROOT / "data/eval/t17-answer/run_20261015_v2"


@pytest.fixture
def frozen_run():
    def read_records(name):
        return [json.loads(line) for line in (FROZEN_RUN / name).read_text(encoding="utf-8").splitlines() if line]

    records = read_records("execution_records.jsonl")
    regressions = read_records("regression_records.jsonl")
    reviews = json.loads((FROZEN_RUN / "manual_reviews.json").read_text(encoding="utf-8"))
    assert len(records) == 45 and len(regressions) == 2 and len(reviews) == 19
    return records, regressions, reviews


def check(records, regressions, reviews=None, **kwargs):
    return evaluate_gate_b(
        records, regressions, manual_reviews=reviews or {}, source_root=ROOT, **kwargs
    )


def assert_corruption_fails(records, regressions, reviews=None):
    verdict, failures, pending = check(records, regressions, reviews)
    assert verdict == "FAIL", (verdict, failures, pending)
    assert failures


def test_frozen_v2_has_no_provable_integrity_violation(frozen_run):
    records, regressions, reviews = frozen_run
    verdict, failures, _ = check(records, regressions, reviews)
    assert verdict in {"PASS", "PENDING"}, failures


@pytest.mark.parametrize("field", ["text", "applicability", "actionable_goal"])
def test_output_must_be_reconstructed_from_raw_response(frozen_run, field):
    records, regressions, _ = frozen_run
    records[0]["output"][field] = "변조된 최종 답변입니다."
    assert_corruption_fails(records, regressions)


@pytest.mark.parametrize("field", ["url", "doc_id", "source_location"])
def test_citation_must_match_retrieved_source(frozen_run, field):
    records, regressions, _ = frozen_run
    records[0]["citations"][0][field] = "https://example.invalid/tampered" if field == "url" else "변조된 근거"
    assert_corruption_fails(records, regressions)


def test_used_citation_provenance_must_match_projected_evidence(frozen_run):
    records, regressions, _ = frozen_run
    records[0]["used_citations_provenance"][0]["text"] = "검색 근거에 없는 주장"
    assert_corruption_fails(records, regressions)


@pytest.mark.parametrize("copy_name", ["trace", "runtime", "both"])
@pytest.mark.parametrize("corruption", ["failed_process", "malformed_events", "different_answer"])
def test_trace_is_revalidated_instead_of_trusting_saved_validation(frozen_run, copy_name, corruption):
    records, regressions, _ = frozen_run
    generation = records[0]["generation"]
    traces = []
    if copy_name in {"trace", "both"}:
        traces.append(generation["trace"])
    if copy_name in {"runtime", "both"}:
        traces.append(generation["runtime_meta"]["_trace"])
    for trace in traces:
        if corruption == "failed_process":
            trace["process_returncode"] = 17
            trace["process_error"] = "recorded process failure"
        elif corruption == "malformed_events":
            trace["stdout_jsonl"] = "this is not JSONL\n"
        else:
            events = [json.loads(line) for line in trace["stdout_jsonl"].splitlines()]
            message = next(event["item"] for event in events if event.get("item", {}).get("type") == "agent_message")
            answer = json.loads(message["text"])
            answer["answer"] = "실제 출력과 다른 프로세스 응답입니다. [C1S1]"
            message["text"] = json.dumps(answer, ensure_ascii=False)
            trace["stdout_jsonl"] = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    assert_corruption_fails(records, regressions)


@pytest.mark.parametrize("field", ["run_id", "record_hash"])
def test_manual_review_cannot_verify_a_different_execution(frozen_run, field):
    records, regressions, reviews = frozen_run
    next(iter(reviews.values()))[field] = "stale-value-from-another-run"
    assert_corruption_fails(records, regressions, reviews)


@pytest.mark.parametrize("query_id", ["Q010", "Q077"])
@pytest.mark.parametrize("corruption", ["error", "no_citations", "output_text", "failed_trace", "zero_calls"])
def test_regression_records_receive_the_same_integrity_checks(frozen_run, query_id, corruption):
    records, regressions, _ = frozen_run
    record = next(record for record in regressions if record["query_id"] == query_id)
    if corruption == "error":
        record["output"]["error"] = {"code": "ANSWER_GENERATION_FAILED", "message": "failed"}
    elif corruption == "no_citations":
        assert record["output"]["status"] in {"SUPPORTED", "UNSUPPORTED"}
        record["citations"] = []
    elif corruption == "output_text":
        record["output"]["text"] = "원응답에 없는 최종 답변"
    elif corruption == "failed_trace":
        record["generation"]["trace"]["process_returncode"] = 17
        record["generation"]["runtime_meta"]["_trace"]["process_returncode"] = 17
    else:
        record["generation"]["call_count"] = 0
    assert_corruption_fails(records, regressions)


@pytest.mark.parametrize("query_id", ["Q010", "Q077"])
def test_regression_mock_generation_cannot_satisfy_gate_b(frozen_run, query_id):
    records, regressions, reviews = frozen_run
    record = next(record for record in regressions if record["query_id"] == query_id)
    record["generation"]["is_mock"] = True
    verdict, failures, pending = check(records, regressions, reviews)
    assert verdict != "PASS", (failures, pending)
    assert any("mock" in reason.lower() or "모의" in reason for reason in failures + pending)


def test_allow_mock_does_not_turn_mock_generation_into_gate_b_evidence(frozen_run):
    records, regressions, reviews = frozen_run
    for record in records + regressions:
        record["generation"]["is_mock"] = True
    verdict, failures, pending = check(records, regressions, reviews, allow_mock=True)
    assert verdict != "PASS", (failures, pending)
    assert any("mock" in reason.lower() or "모의" in reason for reason in failures + pending)


@pytest.mark.parametrize("location", ["slice", "regression"])
@pytest.mark.parametrize("corruption", ["query_original", "query_normalized", "parent_id", "zero_calls"])
def test_canonical_input_parent_and_call_count_are_verified(frozen_run, location, corruption):
    records, regressions, _ = frozen_run
    record = (records if location == "slice" else regressions)[0]
    if corruption in {"query_original", "query_normalized"}:
        record["input"][corruption] = "고정 질문과 다른 입력"
    elif corruption == "parent_id":
        record["original_run_id"] = "unrelated-parent-run"
    else:
        record["generation"]["call_count"] = 0
    assert_corruption_fails(records, regressions)


def test_duplicate_regression_records_fail(frozen_run):
    records, regressions, _ = frozen_run
    regressions.append(copy.deepcopy(regressions[0]))
    assert_corruption_fails(records, regressions)


@pytest.mark.parametrize("corruption", ["failed_process", "bad_status", "no_citations"])
def test_missing_raw_response_does_not_hide_provable_failure(frozen_run, corruption):
    records, regressions, _ = frozen_run
    record = records[0]
    record["generation"]["raw_response"] = None
    if corruption == "failed_process":
        for trace in (record["generation"]["trace"], record["generation"]["runtime_meta"]["_trace"]):
            trace["process_returncode"] = 17
    elif corruption == "bad_status":
        record["output"]["status"] = "NOT_A_STATUS"
    else:
        record["citations"] = []
    assert_corruption_fails(records, regressions)


def test_run_ids_are_unique_across_slice_and_regression_records(frozen_run):
    records, regressions, _ = frozen_run
    regressions[0]["run_id"] = records[0]["run_id"]
    assert_corruption_fails(records, regressions)


def test_validate_does_not_write_to_any_input_directory_file(tmp_path):
    run_directory = tmp_path / "frozen-run"
    shutil.copytree(FROZEN_RUN, run_directory)

    def snapshot():
        return {
            str(path.relative_to(run_directory)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in run_directory.rglob("*") if path.is_file()
        }

    before = snapshot()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_t17_answer.py"), "--validate", str(run_directory)],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT / "src"),
             "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        text=True, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode in {0, 2}, result.stdout + result.stderr
    after = snapshot()
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    assert changed == [], f"--validate modified input files: {changed}"
