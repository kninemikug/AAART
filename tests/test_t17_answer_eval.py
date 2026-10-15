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

import json
from pathlib import Path
import tempfile
from typing import Any
import pytest

from artagent.answer import sha256_str
from scripts.check_t17_answer import (
    FIXED_SLICE1_IDS,
    evaluate_gate_b,
    generate_comparison_report,
)


def _make_dummy_evidence(chunk_id: str = "C1", doc_id: str = "doc1", source_type: str = "rawpedia") -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "source_group_id": "group1",
        "source_type": source_type,
        "source_path": f"{doc_id}.md",
        "target_url": f"https://example.com/{doc_id}",
        "product_scope": "RawTherapee" if source_type == "rawpedia" else "ART",
        "text": "test text",
        "source_location": json.dumps({
            "section_title": "Section",
            "source_segment": {
                "doc_id": doc_id,
                "source_path": f"{doc_id}.md",
                "target_url": f"https://example.com/{doc_id}",
                "json_pointer": None,
                "char_start": 0,
                "char_end": 9,
                "byte_start": 0,
                "byte_end": 9,
                "source_file_sha256": "dummy",
                "segment_sha256": "dummy",
            }
        }),
    }


def _make_dummy_record(
    query_id: str,
    track: str,
    status: str = "SUPPORTED",
    is_mock: bool = False,
    has_prompt: bool = True,
    has_raw: bool = True,
    error: Any = None,
    citations_count: int = 1,
) -> dict[str, Any]:
    cits = []
    for i in range(citations_count):
        cits.append({
            "doc_id": "doc1",
            "title": "Title",
            "url": "https://example.com/doc1",
            "source_location": "{}",
            "citation_id": f"C1S{i+1}",
        })
    ev = _make_dummy_evidence(source_type="github" if query_id in ("Q084", "Q086", "Q092", "Q093", "Q096") else "rawpedia")
    s_inst = "sys inst" if has_prompt else ""
    u_prompt = "user prompt" if has_prompt else ""
    p_hash = sha256_str(f"{s_inst}\n{u_prompt}") if has_prompt else ""

    return {
        "run_id": f"run_{query_id}_{track}",
        "record_version": "t17-run-v2",
        "track": track,
        "query_id": query_id,
        "query": f"Query {query_id}",
        "decision_step_id": f"step_{query_id}",
        "original_run_id": f"orig_{query_id}",
        "input_file_sha": "some_sha",
        "retrieval": {
            "query": f"Query {query_id}",
            "source_filter": "GITHUB" if query_id in ("Q084", "Q086", "Q092", "Q093", "Q096") else "RAWPEDIA",
            "snapshot_ref": "snap",
            "hits": [ev],
        },
        "prompt": {
            "version": "t17-answer-v1",
            "system_instruction": s_inst,
            "user_prompt": u_prompt,
            "prompt_hash": p_hash,
        },
        "generation": {
            "provider": "codex-cli",
            "model": "gpt-5.6-sol",
            "is_mock": is_mock,
            "raw_response": json.dumps({"status": status, "answer": "답변", "citation_ids": ["C1S1"]}) if has_raw else None,
            "call_count": 1 if error is None else 0,
        },
        "output": {
            "status": status,
            "text": "답변 [출처: Title·https://example.com/doc1]",
            "applicability": "제품 범위: RawTherapee",
        },
        "citations": cits,
        "error": error,
        "manual_review": {
            "status": "pending",
        },
    }


def _make_full_synthetic_dataset() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    records = []
    for qid in FIXED_SLICE1_IDS:
        for tr in ("t11_replay", "t14_a", "t14_b"):
            st = "INSUFFICIENT_EVIDENCE" if (qid == "Q086" and tr == "t11_replay") else ("UNSUPPORTED" if qid == "Q096" else "SUPPORTED")
            cc = 0 if st == "INSUFFICIENT_EVIDENCE" else 1
            records.append(_make_dummy_record(qid, tr, status=st, citations_count=cc))

    reg_records = [
        _make_dummy_record("Q010", "t14_b_reg_Q010", status="SUPPORTED", citations_count=1),
        _make_dummy_record("Q077", "t14_b_reg_Q077", status="SUPPORTED", citations_count=1),
    ]

    # 19 required manual reviews: Q001 (3 tracks), Q086 (3 tracks), Q096 (3 tracks), CP2 5 queries (2 tracks A/B = 10, note Q001 already in Q001 tracks so 8 more), Q010 (1), Q077 (1) = 19
    manual_reviews = {}
    review_targets = [
        ("Q001", "t11_replay"), ("Q001", "t14_a"), ("Q001", "t14_b"),
        ("Q086", "t11_replay"), ("Q086", "t14_a"), ("Q086", "t14_b"),
        ("Q096", "t11_replay"), ("Q096", "t14_a"), ("Q096", "t14_b"),
        ("Q004", "t14_a"), ("Q004", "t14_b"),
        ("Q014", "t14_a"), ("Q014", "t14_b"),
        ("Q054", "t14_a"), ("Q054", "t14_b"),
        ("Q063", "t14_a"), ("Q063", "t14_b"),
        ("Q010", "t14_b_reg_Q010"),
        ("Q077", "t14_b_reg_Q077"),
    ]
    for qid, tr in review_targets:
        run_id = f"run_{qid}_{tr}"
        manual_reviews[run_id] = {
            "run_id": run_id,
            "query_id": qid,
            "track": tr,
            "status": "verified",
            "reviewed_claims": ["claim verified"],
            "reason": "Verified against source document",
        }

    return records, reg_records, manual_reviews


def test_evaluate_gate_b_all_errors_returns_fail():
    records = []
    for qid in FIXED_SLICE1_IDS:
        for tr in ("t11_replay", "t14_a", "t14_b"):
            records.append(_make_dummy_record(qid, tr, error={"code": "ANSWER_GENERATION_FAILED", "message": "Failed"}))
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, [])
    assert verdict == "FAIL"
    assert len(fail_reasons) > 0


def test_evaluate_gate_b_missing_records_returns_pending():
    # Only 10 records out of 45
    records = [_make_dummy_record(FIXED_SLICE1_IDS[0], "t11_replay")]
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, [])
    assert verdict == "PENDING"
    assert any("누락" in r for r in pending_reasons)


def test_evaluate_gate_b_mock_returns_pending():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["generation"]["is_mock"] = True
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


def test_evaluate_gate_b_tampered_prompt_hash_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["prompt"]["prompt_hash"] = "tampered_hash_12345"
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
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("원생성 응답의 status" in r for r in fail_reasons)


def test_evaluate_gate_b_call_count_exceeded_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    records[0]["generation"]["call_count"] = 2
    verdict, fail_reasons, pending_reasons = evaluate_gate_b(records, reg, reviews)
    assert verdict == "FAIL"
    assert any("호출 수 초과" in r for r in fail_reasons)


def test_evaluate_gate_b_tampered_coordinates_returns_fail():
    records, reg, reviews = _make_full_synthetic_dataset()
    # Point to a real hit or simulate coordinate validation failure with source_root
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        doc_path = tmp_dir / "test.md"
        doc_path.write_text("abcdefghij", encoding="utf-8")
        file_sha = sha256_str("abcdefghij")

        ev = _make_dummy_evidence()
        ev["source_path"] = "test.md"
        loc = json.loads(ev["source_location"])
        loc["source_segment"]["source_file_sha256"] = file_sha
        loc["source_segment"]["byte_start"] = 99  # Tampered byte_start!
        ev["source_location"] = json.dumps(loc)
        records[0]["retrieval"]["hits"] = [ev]

        verdict, fail_reasons, pending_reasons = evaluate_gate_b(
            records, reg, reviews, source_root=tmp_dir
        )
        assert verdict == "FAIL"
        assert any("원문/좌표 독립 검증 실패" in r for r in fail_reasons)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

