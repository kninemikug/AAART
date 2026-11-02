"""T15 답변 채택 감사의 증거 누락·변조 반례와 완전한 양성 대조군."""

from __future__ import annotations

import copy
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import tempfile

import pytest

from artagent.answer import normalize_query
from artagent.answer_validation import capture_code_state, record_digest
from artagent.graph.answer import answer_standalone, T17_PROMPT_VERSION
from artagent.graph.search import search_hits_to_evidences
from artagent.graph.state import Evidence, RetrievalBundle
from artagent.retrieval.provenance import canonical_json_str, sha256_str
from scripts import t15_evaluation as evaluation


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data/eval/t15-rerank/grid_v3_rebuilt/baseline_records.jsonl.gz"


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_rows(path, values):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _record(case, runtime, status):
    """No network: generate deterministically, retaining the real validation path."""
    observation = {}
    raw = json.dumps({"status": status,
                      "answer": "제공된 검색 근거로는 확인할 수 없습니다." if status == "INSUFFICIENT_EVIDENCE" else "근거의 제품 범위를 확인했습니다. [C1S1]",
                      "citation_ids": [] if status == "INSUFFICIENT_EVIDENCE" else ["C1S1"]}, ensure_ascii=False)
    body = {"choices": [{"message": {"content": raw}}]}

    def generate(system, prompt, citations, query):
        return raw, {}, {"llm_provider": "openai-compatible", "model_id": "review-unit-model",
                         "_response_body": body, "_response_text": json.dumps(body)}

    bundle = RetrievalBundle(**{**case["retrieval"], "hits": [Evidence(**h) for h in case["retrieval"]["hits"]]})
    answer, error = answer_standalone(case["query"], bundle, generate=generate,
                                      source_root=ROOT, observe=observation.update)
    assert error is None
    payload = {"model": "review-unit-model", "messages": [
        {"role": "system", "content": observation["system_instruction"]},
        {"role": "user", "content": observation["user_prompt"]}]}
    return {"fixture_kind": "unit-only-offline-capture", "record_schema": "t17-run-v3",
            "runtime": runtime, "run_id": f"unit:{case['track']}:{case['query_id']}",
            "track": case["track"], "query_id": case["query_id"], "original_run_id": case["parent"],
            "input": {"query_original": case["query"], "query_normalized": normalize_query(case["query"]),
                      "confirmed_context": None, "constraints": []},
            "retrieval": case["retrieval"],
            "prompt": {"version": T17_PROMPT_VERSION, **{k: observation[k] for k in ("system_instruction", "user_prompt", "prompt_hash")}},
            "generation": {"call_count": 1, "provider": "openai-compatible", "model": "review-unit-model",
                           "is_mock": False, "runtime_meta": observation["runtime_meta"], "raw_response": raw,
                           "request": {"kind": "chat-completions", "payload": payload,
                                       "sha256": sha256_str(canonical_json_str(payload)), "model": "review-unit-model",
                                       "prompt_version": T17_PROMPT_VERSION, "response_schema": "t17-answer-v1"}},
            "citations": [asdict(c) for c in answer.citations],
            "used_citations_provenance": observation["used_citations_provenance"],
            "output": {**asdict(answer), "error": None}}


def _review(row):
    used = row["used_citations_provenance"]
    return {"record_digest": record_digest(row), "reviewer": "unit-reviewer", "verdict": "PASS",
            "claims": [{"claim": row["output"]["text"], "verdict": "PASS",
                        "reason": "답변 주장을 사용 인용의 원문과 대조했습니다.",
                        "citation_ids": [s["cid"] for s in used],
                        "evidence_links": [{k: s[k] for k in ("cid", "target_url", "source_location")} for s in used],
                        "checks": {key: {"verdict": "PASS", "reason": reason} for key, reason in (
                            ("status", "지원·반증·근거 부족 상태가 원문과 일치합니다."),
                            ("product_scope", "원문의 제품 범위를 보존합니다."),
                            ("baseline", "짝지은 B0 답변과 비교하여 오판 증가가 없습니다."))}}]}


@pytest.fixture(scope="module")
def answer_template():
    protocol = json.loads((ROOT / "data/eval/t15-rerank/plan_v3_rebuilt/protocol.json").read_bytes())
    protocol["answer"] = {"provider": "openai-compatible", "model": "review-unit-model", "prompt_version": T17_PROMPT_VERSION}
    verifier = evaluation.RecordVerifier(protocol)
    baselines = evaluation.read_rows(BASELINE)
    bundles, trials = {}, []
    for search in baselines:
        hits = verifier.search(search)[:5]
        bundle = asdict(RetrievalBundle(search["search_query"], search["source_type"].upper(),
                                       search_hits_to_evidences(hits), protocol["snapshot_fingerprint"]))
        bundles[search["query_id"], search["condition"]] = bundle
        trials.append({"query_id": search["query_id"], "condition": search["condition"], "repeat_index": 1,
                       "selected_chunk_ids": [h.chunk_id for h in hits], "bundle_digest": evaluation.digest(bundle)})
    cases, rows = [], []
    runtime = capture_code_state(ROOT)
    for qid in sorted(set(evaluation.T17_CRITICAL_31_QIDS) | {"Q002"}):
        for track in ("B0", "T15"):
            case = {"query_id": qid, "track": track, "query": verifier.questions[qid]["query"],
                    "retrieval": bundles[qid, "B"], "parent": f"unit-parent:{track}:{qid}"}
            status = "INSUFFICIENT_EVIDENCE" if qid == "Q010" else "SUPPORTED" if verifier.questions[qid]["gold_support_doc_ids"] else "UNSUPPORTED"
            cases.append(case)
            rows.append(_record(case, runtime, status))
    return protocol, verifier, baselines, trials, cases, rows


@pytest.fixture
def answer_audit(answer_template, monkeypatch):
    protocol, verifier, baselines, trials, cases, rows = answer_template
    template = copy.deepcopy((protocol, trials, cases, rows))
    parent_result = {"repeated": "PASS", "gates": {key: {"status": "PASS"} for key in ("G0", "G1", "G2", "G3", "G4")}}
    monkeypatch.setattr(evaluation, "audit_run", lambda *args, **kwargs: parent_result)

    def audit(*, mutate=None, changed=False, include_extra=False, manual=True, omit_baseline_link=False):
        protocol, trials, cases, rows = copy.deepcopy(template)
        if changed:
            search = next(s for s in baselines if s["condition"] == "B" and s["query_id"] == "Q002")
            hits = verifier.search(search)[:4]
            bundle = asdict(RetrievalBundle(search["search_query"], search["source_type"].upper(),
                                           search_hits_to_evidences(hits), protocol["snapshot_fingerprint"]))
            for trial in trials:
                if trial["condition"] == "B" and trial["query_id"] == "Q002":
                    trial.update(selected_chunk_ids=[h.chunk_id for h in hits], bundle_digest=evaluation.digest(bundle))
            for case in cases:
                if case["query_id"] == "Q002" and case["track"] == "T15":
                    case["retrieval"] = bundle
                    replacement = _record(case, rows[0]["runtime"], "SUPPORTED")
                    rows = [replacement if r["query_id"] == "Q002" and r["track"] == "T15" else r for r in rows]
        if not include_extra:
            cases = [c for c in cases if c["query_id"] != "Q002"]
            rows = [r for r in rows if r["query_id"] != "Q002"]
        reviews = {r["run_id"]: _review(r) for r in rows}
        if mutate:
            mutate(protocol, cases, rows, reviews)
        with tempfile.TemporaryDirectory(prefix=".t15-answer-test-", dir=ROOT) as temp:
            parent, run = Path(temp) / "parent", Path(temp) / "answers"
            parent.mkdir()
            run.mkdir()
            _write(parent / "manifest.json", {"unit_fixture": True})
            _write_rows(parent / "baseline_records.jsonl.gz", baselines)
            _write_rows(parent / "records.jsonl.gz", trials)
            _write(run / "cases.json", cases)
            reference = {"path": str((run / "cases.json").relative_to(ROOT)), "sha256": evaluation.sha256_file(run / "cases.json")}
            for row in rows:
                row["input_reference"] = reference
                if row["run_id"] in reviews:
                    reviews[row["run_id"]]["record_digest"] = record_digest(row)
            baseline_rows = {row["query_id"]: row for row in rows if row["track"] == "B0"}
            for row in rows:
                if row["run_id"] in reviews:
                    reviews[row["run_id"]].setdefault("baseline_record_digest", record_digest(baseline_rows[row["query_id"]]))
            if omit_baseline_link:
                reviews[rows[0]["run_id"]].pop("baseline_record_digest")
            _write_rows(run / "answer_records.jsonl", rows)
            if manual:
                _write(run / "manual_reviews.json", reviews)
            manifest = {"retrieval_run": str(parent.relative_to(ROOT)), "retrieval_manifest_sha256": evaluation.sha256_file(parent / "manifest.json")}
            try:
                return evaluation.audit_answers(run, protocol, manifest, verifier, None)
            except ValueError as error:
                return {"overall_verdict": "FAIL", "failures": [str(error)]}
    return audit


def test_complete_paired_answer_proof_passes(answer_audit):
    result = answer_audit()
    assert result["overall_verdict"] == "PASS", result


def test_missing_manual_reviews_remain_pending(answer_audit):
    assert answer_audit(manual=False)["overall_verdict"] == "PENDING"


@pytest.mark.parametrize("part", ["empty_claim", "claim", "reason", "citation_ids", "evidence_links", "checks", "status", "product_scope", "baseline"])
def test_incomplete_claim_proof_cannot_pass(answer_audit, part):
    def mutate(protocol, cases, rows, reviews):
        review = reviews[rows[0]["run_id"]]
        claim = review["claims"][0]
        if part == "empty_claim":
            review["claims"] = [{}]
        elif part in ("status", "product_scope", "baseline"):
            claim["checks"].pop(part)
        else:
            claim.pop(part)
    result = answer_audit(mutate=mutate)
    assert result["overall_verdict"] == "PENDING", result


@pytest.mark.parametrize("part", ["cid", "location", "url", "scope_fail", "baseline_fail", "claim_fail", "review_fail"])
def test_invalid_or_failed_claim_proof_fails(answer_audit, part):
    def mutate(protocol, cases, rows, reviews):
        review = reviews[rows[0]["run_id"]]
        claim = review["claims"][0]
        if part == "cid":
            claim["citation_ids"] = ["C999S999"]
        elif part in ("location", "url"):
            claim["evidence_links"][0]["source_location" if part == "location" else "target_url"] = "forged"
        elif part.endswith("_fail"):
            target = review if part == "review_fail" else claim if part == "claim_fail" else claim["checks"]["product_scope" if part == "scope_fail" else "baseline"]
            target["verdict"] = "FAIL"
    result = answer_audit(mutate=mutate)
    assert result["overall_verdict"] == "FAIL", result


def test_changed_parent_question_cannot_be_omitted(answer_audit):
    result = answer_audit(changed=True)
    assert result["overall_verdict"] == "FAIL", result


def test_changed_question_with_both_tracks_passes(answer_audit):
    result = answer_audit(changed=True, include_extra=True)
    assert result["overall_verdict"] == "PASS", result


def test_changed_question_missing_one_track_fails(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        cases[:] = [c for c in cases if not (c["query_id"] == "Q002" and c["track"] == "T15")]
        rows[:] = [r for r in rows if not (r["query_id"] == "Q002" and r["track"] == "T15")]
    assert answer_audit(changed=True, include_extra=True, mutate=mutate)["overall_verdict"] == "FAIL"


def test_duplicate_case_cannot_pass(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        cases.append(copy.deepcopy(cases[0]))
    assert answer_audit(mutate=mutate)["overall_verdict"] == "FAIL"


def test_stale_baseline_review_link_fails(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        reviews[rows[0]["run_id"]]["baseline_record_digest"] = "0" * 64
    assert answer_audit(mutate=mutate)["overall_verdict"] == "FAIL"


@pytest.mark.parametrize("field,value", [("provider", "different-provider"), ("model", "different-model"), ("prompt_version", "different-version")])
def test_registered_generation_contract_must_match(answer_audit, field, value):
    def mutate(protocol, cases, rows, reviews):
        protocol["answer"][field] = value
    result = answer_audit(mutate=mutate)
    assert result["overall_verdict"] == "FAIL", result


def test_malformed_claims_and_reviewer_fail(answer_audit):
    for key, value in (("claims", True), ("claims", "complete"), ("reviewer", False)):
        def mutate(protocol, cases, rows, reviews):
            reviews[rows[0]["run_id"]][key] = value
        assert answer_audit(mutate=mutate)["overall_verdict"] == "FAIL", (key, value)


def test_empty_claim_list_and_reviewer_stay_pending(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        reviews[rows[0]["run_id"]].update(claims=[], reviewer="  ")
    assert answer_audit(mutate=mutate)["overall_verdict"] == "PENDING"


def test_missing_baseline_review_link_stays_pending(answer_audit):
    assert answer_audit(omit_baseline_link=True)["overall_verdict"] == "PENDING"


def test_explicit_status_failure_wins_over_missing_proof(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        claim = reviews[rows[0]["run_id"]]["claims"][0]
        claim["checks"]["status"]["verdict"] = "FAIL"
        claim.pop("reason")
    result = answer_audit(mutate=mutate)
    assert result["overall_verdict"] == "FAIL", result
    assert result["failures"] and result["pending"]


def test_status_check_pending_cannot_pass(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        reviews[rows[0]["run_id"]]["claims"][0]["checks"]["status"]["verdict"] = "PENDING"
    assert answer_audit(mutate=mutate)["overall_verdict"] == "PENDING"


def test_unreviewed_used_citation_stays_pending(answer_audit):
    def mutate(protocol, cases, rows, reviews):
        claim = reviews[rows[0]["run_id"]]["claims"][0]
        claim.update(citation_ids=[], evidence_links=[])
    assert answer_audit(mutate=mutate)["overall_verdict"] == "PENDING"


def test_duplicate_or_malformed_evidence_link_fails(answer_audit):
    for malformed in (False, True):
        def mutate(protocol, cases, rows, reviews):
            links = reviews[rows[0]["run_id"]]["claims"][0]["evidence_links"]
            links.append(False if malformed else copy.deepcopy(links[0]))
        assert answer_audit(mutate=mutate)["overall_verdict"] == "FAIL"


def test_unknown_track_and_unpaired_case_or_record_fail(answer_audit):
    for variant in ("track", "case_missing", "record_missing", "record_extra"):
        def mutate(protocol, cases, rows, reviews):
            if variant == "track":
                cases[1]["track"] = rows[1]["track"] = "UNKNOWN"
            elif variant == "case_missing":
                cases.pop(1)
            elif variant == "record_missing":
                rows.pop(1)
            else:
                extra = copy.deepcopy(rows[1])
                extra.update(track="EXTRA", run_id="extra-run")
                rows.append(extra)
        assert answer_audit(mutate=mutate)["overall_verdict"] == "FAIL", variant


def test_runtime_contract_mismatch_is_rejected_before_generation(monkeypatch, tmp_path):
    """Only selection/retrieval prerequisites are doubles; generation must never run."""
    from scripts import eval_t15_rerank as runtime
    import artagent.graph.answer as answer_module

    selected = tmp_path / "selected_condition.json"
    _write(selected, {"selected_condition": "unit-qualified"})
    monkeypatch.setattr(runtime, "verify_manifest", lambda *args: ({}, {}))
    monkeypatch.setattr(runtime, "audit_run", lambda *args, **kwargs: {
        "repeated": "PASS", "gates": {key: {"status": "PASS"} for key in ("G0", "G1", "G2", "G3", "G4")}})
    monkeypatch.setattr(answer_module, "answer_standalone", lambda *args, **kwargs: pytest.fail("조건 불일치에도 실제 생성을 호출함"))
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("LLM_MODEL", "unit-runtime-model")
    expected = {"provider": "codex-cli", "model": "unit-runtime-model", "prompt_version": T17_PROMPT_VERSION}
    for field in ("provider", "model", "prompt_version"):
        protocol = {"answer": {**expected, field: "mismatching-condition"}}
        with pytest.raises(ValueError, match="사전 등록"):
            runtime.run_t17(protocol, tmp_path / "protocol.json", selected, tmp_path / "retrieval", tmp_path / "answers")
