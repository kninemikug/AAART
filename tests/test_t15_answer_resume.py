"""성공 답변의 중복 호출과 오류 이후의 연속 호출을 방지한다."""
import copy

import pytest

from scripts.resume_t15_answers import execute_missing, rebind, select_existing


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
