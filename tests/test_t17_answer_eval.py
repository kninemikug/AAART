"""Unit tests for Task 17 answer evaluation and Gate B verdict logic (F01).

docs/T17_fix_plan.md §3 (F01) requirements:
- Separate evaluation/verdict from report writing
- Verdict returns FAIL=1, PENDING=2, PASS=0
- Integrity violation -> FAIL
- Missing evidence / pending manual reviews / missing prompts -> PENDING
- Existing run_20261015_final must be evaluated as PENDING, not PASS
- Valid complete fixture -> PASS
"""

from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
import pytest

from artagent.answer import sha256_str
from artagent.answer_validation import record_digest, reference_cases
from scripts.check_t17_answer import (
    FIXED_SLICE1_IDS,
    evaluate_gate_b,
    generate_comparison_report,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_RUN = ROOT / "data/eval/t17-answer/run_20261015_v2"


def _refresh_review_hashes(records, regressions, reviews):
    """Keep review identity consistent so it cannot mask the tested condition."""
    by_run = {r["run_id"]: r for r in records + regressions}
    for review in reviews.values():
        review["record_hash"] = record_digest(by_run[review["run_id"]])


@lru_cache(maxsize=1)
def _synthetic_dataset_template():
    """Construct in-memory v3 controls; never promote or rewrite frozen runs.

    Real queries, bundles, raw responses, process events, citations and outputs
    come from v2. Only the new capture fields are simulated for these tests.
    """
    def load_records(filename):
        return [json.loads(line) for line in (FROZEN_RUN / filename).read_text(encoding="utf-8").splitlines() if line]

    records = load_records("execution_records.jsonl")
    regressions = load_records("regression_records.jsonl")
    reviews = json.loads((FROZEN_RUN / "manual_reviews.json").read_text(encoding="utf-8"))
    cases = reference_cases(ROOT)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    paths = ("src/artagent/answer.py", "src/artagent/graph/answer.py", "scripts/check_t17_answer.py")
    code_files = {
        path: hashlib.sha256(subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)).hexdigest()
        for path in paths
    }
    for record in records + regressions:
        record["record_schema"] = "t17-run-v3"
        record["fixture_kind"] = "synthetic-v3-capture-on-frozen-v2"
        record["input_reference"] = copy.deepcopy(cases[record["query_id"], record["track"]]["input_reference"])
        record["runtime"] = {"code_commit": commit, "code_files": dict(code_files)}
        prompt = record["prompt"]
        full_prompt = (
            f"{prompt['system_instruction']}\n\n{prompt['user_prompt']}\n\n"
            "반드시 마크다운 코드블록(```json 등) 없이 순수 JSON 객체(키: status, answer, citation_ids) 하나만 출력하십시오."
        )
        record["generation"]["request"] = {
            "kind": "codex", "full_prompt": full_prompt,
            "sha256": sha256_str(full_prompt), "response_schema": "t17-answer-v1",
            "prompt_version": prompt["version"],
            "model": record["generation"]["model"],
        }
        record["generation"]["runtime_meta"]["_output_file_content"] = record["generation"]["raw_response"]
    _refresh_review_hashes(records, regressions, reviews)
    return records, regressions, reviews


def _make_full_synthetic_dataset() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return copy.deepcopy(_synthetic_dataset_template())


def test_evaluate_gate_b_all_errors_returns_fail():
    records, _, _ = _make_full_synthetic_dataset()
    for record in records:
        record["output"]["error"] = {"code": "ANSWER_GENERATION_FAILED", "message": "Failed"}
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, [])
    assert verdict == "FAIL"
    assert len(fail_reasons) > 0


def test_evaluate_gate_b_missing_records_returns_pending():
    records, _, _ = _make_full_synthetic_dataset()
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records[:1], [])
    assert verdict == "PENDING"
    assert any("누락" in r for r in pending_reasons)


def test_evaluate_gate_b_mock_returns_pending():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["generation"]["is_mock"] = True
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews, allow_mock=False)
    assert verdict == "PENDING"
    assert any("mock" in r.lower() or "모의" in r for r in pending_reasons)


def test_evaluate_gate_b_missing_manual_review_returns_pending():
    records, reg, reviews = _make_full_synthetic_dataset()
    # Remove one review
    reviews.pop(list(reviews.keys())[0])
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "PENDING"
    assert any("수동 검토" in r for r in pending_reasons)


def test_evaluate_gate_b_citation_zero_on_supported_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["citations"] = []  # SUPPORTED with 0 citations
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("인용" in r for r in fail_reasons)


def test_evaluate_gate_b_duplicate_track_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    # Add duplicate
    records.append(records[0])
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("중복" in r for r in fail_reasons)


def test_evaluate_gate_b_existing_final_run_returns_pending():
    existing_file = Path("data/eval/t17-answer/run_20261015_final/execution_records.jsonl")
    if not existing_file.is_file():
        pytest.skip("Existing run file not found")
    with open(existing_file, "r", encoding="utf-8") as f:
        recs = [json.loads(line) for line in f]
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(recs, [])
    assert verdict == "PENDING"
    assert len(pending_reasons) > 0


def test_evaluate_gate_b_valid_synthetic_dataset_returns_pass():
    records, reg, reviews = _make_full_synthetic_dataset()
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "PASS"
    assert len(fail_reasons) == 0
    assert len(pending_reasons) == 0


@pytest.mark.parametrize("missing", ["runtime_mock", "return_code"])
def test_complete_fixture_requires_live_normal_process_evidence(missing):
    records, regressions, reviews = _make_full_synthetic_dataset()
    generation = records[0]["generation"]
    if missing == "runtime_mock":
        generation["runtime_meta"]["is_mock"] = True
    else:
        generation["trace"]["process_returncode"] = None
        generation["runtime_meta"]["_trace"]["process_returncode"] = None
    _refresh_review_hashes(records, regressions, reviews)
    verdict, failures, pending = evaluate_gate_b(records, regressions, reviews)
    assert verdict != "PASS", (failures, pending)


@pytest.mark.parametrize("field", ["version", "generation_status", "hit_summary"])
def test_capture_metadata_is_required_and_consistent(field):
    records, regressions, reviews = _make_full_synthetic_dataset()
    record = records[0]
    if field == "version":
        record["prompt"].pop("version")
        record["generation"]["request"].pop("prompt_version")
        record["generation"]["runtime_meta"]["generation_config"].pop("prompt_version")
    elif field == "generation_status":
        record["generation"]["status"] = "UNSUPPORTED"
    else:
        record["retrieval"]["hits_count"] = 0
        record["retrieval"]["product_scopes"] = ["ART"]
    _refresh_review_hashes(records, regressions, reviews)
    verdict, failures, pending = evaluate_gate_b(records, regressions, reviews)
    assert verdict == ("PENDING" if field == "version" else "FAIL"), (failures, pending)


@pytest.mark.parametrize("missing_field", [None, "raw_response", "_response_text"])
def test_api_capture_can_pass_or_report_missing_evidence_without_false_failure(missing_field):
    records, regressions, reviews = _make_full_synthetic_dataset()
    record = records[0]
    gen, prompt = record["generation"], record["prompt"]
    body = {"choices": [{"message": {"content": gen["raw_response"]}}]}
    payload = {"model": gen["model"], "messages": [
        {"role": "system", "content": prompt["system_instruction"]},
        {"role": "user", "content": prompt["user_prompt"]},
    ]}
    from artagent.retrieval.provenance import canonical_json_str
    gen["provider"] = gen["runtime_meta"]["llm_provider"] = "openai-compatible"
    gen["trace"] = gen["runtime_meta"]["_trace"] = None
    gen["runtime_meta"]["_response_body"] = body
    gen["runtime_meta"]["_response_text"] = json.dumps(body)
    gen["request"] = {"kind": "chat-completions", "payload": payload,
                      "sha256": sha256_str(canonical_json_str(payload)),
                      "response_schema": "t17-answer-v1", "model": gen["model"],
                      "prompt_version": prompt["version"]}
    if missing_field == "raw_response":
        gen["raw_response"] = None
    elif missing_field == "_response_text":
        gen["runtime_meta"].pop("_response_text")
    _refresh_review_hashes(records, regressions, reviews)
    verdict, failures, pending = evaluate_gate_b(records, regressions, reviews)
    assert verdict == ("PENDING" if missing_field else "PASS"), (failures, pending)


@pytest.mark.parametrize("response_text", ["not JSON", '{"choices": []}'])
def test_api_original_response_must_match_parsed_copy(response_text):
    from artagent.retrieval.provenance import canonical_json_str

    records, regressions, reviews = _make_full_synthetic_dataset()
    gen, prompt = records[0]["generation"], records[0]["prompt"]
    gen["provider"] = gen["runtime_meta"]["llm_provider"] = "openai-compatible"
    gen["trace"] = gen["runtime_meta"]["_trace"] = None
    gen["runtime_meta"]["_response_body"] = {"choices": [{"message": {"content": gen["raw_response"]}}]}
    gen["runtime_meta"]["_response_text"] = response_text
    payload = {"model": gen["model"], "messages": [
        {"role": "system", "content": prompt["system_instruction"]},
        {"role": "user", "content": prompt["user_prompt"]},
    ]}
    gen["request"] = {"kind": "chat-completions", "payload": payload,
                      "sha256": sha256_str(canonical_json_str(payload)),
                      "response_schema": "t17-answer-v1", "model": gen["model"],
                      "prompt_version": prompt["version"]}
    _refresh_review_hashes(records, regressions, reviews)
    verdict, failures, _ = evaluate_gate_b(records, regressions, reviews)
    assert verdict == "FAIL", failures


def test_evaluate_gate_b_tampered_prompt_hash_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["prompt"]["prompt_hash"] = "tampered_hash_12345"
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("프롬프트 해시 불일치" in r for r in fail_reasons)


def test_evaluate_gate_b_raw_response_status_mismatch_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    # output.status is SUPPORTED, but raw_response says UNSUPPORTED
    records[0]["generation"]["raw_response"] = json.dumps({
        "status": "UNSUPPORTED",
        "answer": "반대 근거입니다.",
        "citation_ids": ["C1S1"],
    })
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("원생성 응답의 status" in r for r in fail_reasons)


def test_evaluate_gate_b_call_count_exceeded_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["generation"]["call_count"] = 2
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("호출 수 초과" in r for r in fail_reasons)


def test_evaluate_gate_b_tampered_coordinates_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    evidence = records[0]["retrieval"]["hits"][0]
    location = json.loads(evidence["source_location"])
    location["source_segment"]["byte_start"] += 1
    evidence["source_location"] = json.dumps(location)
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(
        records, reg, reviews, source_root=ROOT
    )
    assert verdict == "FAIL"
    assert any("원문/좌표 독립 검증 실패" in r for r in fail_reasons)


@pytest.mark.parametrize("missing", ["prompt", "raw_response"])
def test_evaluate_gate_b_missing_capture_returns_pending(missing):
    records, reg, reviews = _make_full_synthetic_dataset()
    if missing == "prompt":
        records[0]["prompt"] = {"version": "t17-answer-v1"}
        records[0]["generation"].pop("request")
    else:
        records[0]["generation"]["raw_response"] = None
    _refresh_review_hashes(records, reg, reviews)
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "PENDING", fail_reasons
    assert any("누락" in reason for reason in pending_reasons)
