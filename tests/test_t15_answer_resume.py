"""성공 답변의 중복 호출과 오류 이후의 연속 호출을 방지한다."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts.resume_t15_answers import execute_missing, rebind, select_existing
from scripts import resume_t15_answers as resume

ROOT = Path(__file__).resolve().parents[1]


def row(qid, track="B0", success=True):
    return {"query_id": qid, "track": track, "run_id": f"old:{qid}:{track}",
            "output": {"status": "SUPPORTED" if success else None,
                       "error": None if success else {"message": "usage limit"}},
            "generation": {"raw_response": "original"}, "input_reference": {"path": "old"}}


def test_preserve_first_success_and_only_generate_missing():
    original = row("Q001")
    repeated = {**row("Q001"), "generation": {"raw_response": "unnecessary repeat"}}
    old_failure, new_success = row("Q002", success=False), row("Q002")
    expected = {(f"Q00{i}", "B0") for i in (1, 2, 3)}
    existing = select_existing([[original, old_failure], [repeated, new_success]], expected)
    calls, saved = [], []
    def generate(case):
        calls.append(case["query_id"])
        return row(case["query_id"])
    cases = [{"query_id": q, "track": t} for q, t in sorted(expected)]
    execute_missing(cases, existing, generate, saved.append)
    assert calls == ["Q003"]
    assert existing["Q001", "B0"][1] is original
    assert existing["Q002", "B0"][1] is new_success


def test_first_failure_stops_without_calling_remaining_cases():
    cases = [{"query_id": f"Q00{i}", "track": "B0"} for i in (1, 2, 3)]
    calls, saved = [], []
    def generate(case):
        calls.append(case["query_id"])
        return row(case["query_id"], success=False)
    execute_missing(cases, {}, generate, saved.append)
    assert calls == ["Q001"]
    assert len(saved) == 1 and saved[0]["output"]["error"] is not None


def test_complete_sources_never_call_generator():
    existing = {("Q001", "B0"): (0, row("Q001"))}
    def forbidden(case):
        pytest.fail("성공한 답변을 재생성함")
    assert execute_missing([{"query_id": "Q001", "track": "B0"}], existing, forbidden, forbidden) == []


def test_rebinding_only_changes_input_reference_without_mutating_original():
    original = row("Q001")
    before = copy.deepcopy(original)
    rebound = rebind(original, {"path": "new"})
    assert original == before
    assert {k: v for k, v in rebound.items() if k != "input_reference"} == {k: v for k, v in original.items() if k != "input_reference"}


def test_duplicate_and_unknown_pairs_are_rejected():
    with pytest.raises(ValueError):
        select_existing([[row("Q001"), row("Q001")]], {("Q001", "B0")})
    with pytest.raises(ValueError):
        select_existing([[row("Q002")]], {("Q001", "B0")})


@pytest.fixture(scope="module")
def stored_resume_inputs():
    base = ROOT / "data/eval/t15-rerank"
    source = base / "t17_v5_resumed_20261020_final"
    protocol = json.loads((base / "plan_v5/protocol.json").read_bytes())
    manifest = json.loads((source / "manifest.json").read_bytes())
    cases = json.loads((source / "cases.json").read_bytes())
    records = resume.read_rows(source / "answer_records.jsonl")
    parent_verdict = json.loads((base / "regression_v5/validation.json").read_bytes())
    return source, protocol, manifest, cases, records, parent_verdict


@pytest.mark.parametrize("mutation", ["query", "retrieval", "parent", "parent_manifest", "selection"])
def test_unanswered_case_is_bound_to_original_parent_before_any_call(
        stored_resume_inputs, monkeypatch, tmp_path, mutation):
    source, protocol, manifest, cases, records, parent_verdict = copy.deepcopy(stored_resume_inputs)
    case = next(c for c in cases if (c["query_id"], c["track"]) == ("Q096", "T15"))
    if mutation == "query":
        case["query"] += " 다른 요청"
    elif mutation == "retrieval":
        case["retrieval"]["query"] += " wrong context"
    elif mutation == "parent":
        case["parent"] = "other-run:T15:Q096"
    elif mutation == "parent_manifest":
        manifest["retrieval_manifest_sha256"] = "0" * 64
    else:
        manifest["selected_sha256"] = "0" * 64
    monkeypatch.setattr(resume, "load_sources", lambda paths: (protocol, [manifest], cases, [records]))
    # 검색 자체의 합격은 기존 실제 회귀 판정을 쓰고, 재개 경계 검사를 검증한다.
    monkeypatch.setattr(resume, "audit_run", lambda path: parent_verdict)
    def forbidden(*args, **kwargs):
        pytest.fail("불일치 입력으로 실제 생성에 진입함")
    monkeypatch.setattr(resume, "answer_standalone", forbidden)
    destination = tmp_path / "should-not-exist"
    with pytest.raises(ValueError):
        resume.run([source], destination, execute=False)
    assert not destination.exists()


def test_failed_check_returns_structured_verdict_instead_of_traceback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["resume", "--check-run", "unused"])
    monkeypatch.setattr(resume, "check_origins", lambda out: {"missing_count": 9})
    def incomplete(*args, **kwargs):
        raise ValueError("필수 B0/T15 비교 누락")
    monkeypatch.setattr(resume, "audit_run", incomplete)
    assert resume.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["overall_verdict"] == "FAIL"
    assert result["adoption_status"] == "B0_MAINTAINED"
    assert result["resumption"]["missing_count"] == 9


def test_missing_run_evidence_is_pending_not_a_known_failure(monkeypatch, capsys):
    from scripts.t15_evaluation import MissingEvidence
    monkeypatch.setattr(sys, "argv", ["resume", "--check-run", "unused"])
    def absent(out):
        raise MissingEvidence("실행 manifest 없음")
    monkeypatch.setattr(resume, "check_origins", absent)
    assert resume.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["overall_verdict"] == "PENDING"
    assert result["adoption_status"] == "B0_MAINTAINED"


def test_sealed_legacy_resumption_remains_independently_verifiable():
    result = resume.check_origins(ROOT / "data/eval/t15-rerank/t17_v5_resumed_20261020_final")
    assert result == {"reused_record_count": 126, "fresh_attempt_count": 4, "missing_count": 9}


def test_resumed_source_lineage_is_checked_before_reuse(monkeypatch, tmp_path):
    (tmp_path / "cases.json").write_text("[]")
    (tmp_path / "answer_records.jsonl").write_text("")
    monkeypatch.setattr(resume, "verify_manifest", lambda path: ({}, {"phase": "t17", "resumption": {}}))
    def broken_lineage(*args, **kwargs):
        raise ValueError("원본 계보 변조")
    monkeypatch.setattr(resume, "check_origins", broken_lineage)
    with pytest.raises(ValueError, match="계보"):
        resume.load_sources([tmp_path])


@pytest.mark.parametrize("mutation", [None, "content", "escape"])
def test_archived_helper_bytes_are_bound_and_stay_inside_run(tmp_path, mutation):
    content = b"archived helper source\n"
    snapshot = tmp_path / "resume_helper.py"
    snapshot.write_bytes(content)
    metadata = {"helper_source": snapshot.name, "helper_sha256": hashlib.sha256(content).hexdigest()}
    if mutation == "content":
        snapshot.write_bytes(b"modified")
    elif mutation == "escape":
        metadata["helper_source"] = "../outside.py"
    if mutation is None:
        resume.check_helper_source(tmp_path, metadata)
    else:
        with pytest.raises(ValueError, match="지문"):
            resume.check_helper_source(tmp_path, metadata)


def test_lineage_cycle_is_rejected_before_reading_again(tmp_path):
    with pytest.raises(ValueError, match="순환"):
        resume.check_origins(tmp_path, ancestors=frozenset({tmp_path.resolve()}))
