"""T15 답변 비교 대상·생성 조건·주장별 검토의 오프라인 감사."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Optional

from artagent.answer_validation import _check_record, _check_code_state, record_digest
from artagent.graph.search import search_hits_to_evidences
from artagent.graph.state import RetrievalBundle
from scripts import t15_evaluation as evaluation


def comparison_inputs(verifier, parent_dir: Path) -> tuple[set[str], dict, dict]:
    """원래 B0 bundle과 후보 bundle에서 필수 비교 질문·기준선·후보를 도출한다."""
    baseline_index = evaluation.unique_rows(
        [r for r in evaluation.read_rows(parent_dir / "baseline_records.jsonl.gz") if r["condition"] == "B"],
        ("query_id",))
    trial_index = evaluation.unique_rows(
        [r for r in evaluation.read_rows(parent_dir / "records.jsonl.gz")
         if r["condition"] == "B" and r["repeat_index"] == 1], ("query_id",))
    baselines = {key[0]: row for key, row in baseline_index.items()}
    trials = {key[0]: row for key, row in trial_index.items()}
    if set(baselines) != set(verifier.questions) or set(trials) != set(verifier.questions):
        raise ValueError("T17 대상 도출에 필요한 부모 검색 질문 누락/추가")
    needed = set(evaluation.T17_CRITICAL_31_QIDS)
    bundles = {}
    for qid, search in baselines.items():
        bundle = RetrievalBundle(search["search_query"], search["source_type"].upper(),
                                 search_hits_to_evidences(verifier.search(search)[:5]),
                                 verifier.protocol["snapshot_fingerprint"])
        bundles[qid] = asdict(bundle)
        if evaluation.digest(bundles[qid]) != trials[qid]["bundle_digest"]:
            needed.add(qid)
    return needed, bundles, trials


def _text_proof(value, label: str, failures: list, pending: list) -> None:
    if value is None or isinstance(value, str) and not value.strip():
        pending.append(f"{label} 누락")
    elif not isinstance(value, str):
        failures.append(f"{label} 타입 오류")


def _verdict(value, label: str, failures: list, pending: list) -> None:
    if value is None or value == "PENDING":
        pending.append(f"{label} 미완료")
    elif value != "PASS":
        failures.append(f"{label} 불합격/상태 오류: {value}")


def _manual_review(review, row: dict, baseline: dict, failures: list, pending: list) -> None:
    label = f"수동 검토 {row['run_id']}"
    if review is None:
        pending.append(f"{label} 누락")
        return
    if not isinstance(review, dict):
        failures.append(f"{label} 구조 오류")
        return
    for name, expected in (("record_digest", record_digest(row)),
                           ("baseline_record_digest", record_digest(baseline))):
        if review.get(name) is None:
            pending.append(f"{label} {name} 누락")
        elif review[name] != expected:
            failures.append(f"{label} {name} 불일치")
    _text_proof(review.get("reviewer"), f"{label} 검토자", failures, pending)
    _verdict(review.get("verdict"), label, failures, pending)
    claims = review.get("claims")
    if claims is None or claims == []:
        pending.append(f"{label} 주장 누락")
        return
    if not isinstance(claims, list):
        failures.append(f"{label} 주장 목록 타입 오류")
        return
    used = {s["cid"]: s for s in row.get("used_citations_provenance", []) if isinstance(s, dict) and s.get("cid")}
    covered = set()
    for index, claim in enumerate(claims, 1):
        part = f"{label} 주장{index}"
        if not isinstance(claim, dict):
            failures.append(f"{part} 구조 오류")
            continue
        _text_proof(claim.get("claim"), f"{part} 내용", failures, pending)
        _text_proof(claim.get("reason"), f"{part} 사유", failures, pending)
        _verdict(claim.get("verdict"), part, failures, pending)
        checks = claim.get("checks")
        if checks is None:
            pending.append(f"{part} 상태/제품 범위/B0 대조 누락")
        elif not isinstance(checks, dict):
            failures.append(f"{part} 검사 구조 오류")
        else:
            for name in ("status", "product_scope", "baseline"):
                check = checks.get(name)
                if check is None:
                    pending.append(f"{part} {name} 누락")
                elif not isinstance(check, dict):
                    failures.append(f"{part} {name} 구조 오류")
                else:
                    _verdict(check.get("verdict"), f"{part} {name}", failures, pending)
                    _text_proof(check.get("reason"), f"{part} {name} 사유", failures, pending)
        cids, links = claim.get("citation_ids"), claim.get("evidence_links")
        cids_missing = cids is None
        if cids_missing:
            pending.append(f"{part} 인용 ID 목록 누락")
            cids = []
        if not isinstance(cids, list) or any(not isinstance(cid, str) or not cid for cid in cids):
            failures.append(f"{part} 인용 ID 목록 타입 오류")
            continue
        if len(cids) != len(set(cids)) or not set(cids) <= set(used):
            failures.append(f"{part} 중복/사용하지 않은 인용 ID")
        if not cids and row["output"]["status"] in ("SUPPORTED", "UNSUPPORTED"):
            pending.append(f"{part} 근거 답변 인용 누락")
        covered.update(set(cids) & set(used))
        if links is None:
            pending.append(f"{part} 원문 연결 목록 누락")
            links = []
        if not isinstance(links, list):
            failures.append(f"{part} 원문 연결 목록 타입 오류")
            continue
        linked = set()
        for link in links:
            if not isinstance(link, dict):
                failures.append(f"{part} 원문 연결 구조 오류")
                continue
            cid = link.get("cid")
            if (not isinstance(cid, str) or cid not in used or cid in linked
                    or not cids_missing and cid not in cids):
                failures.append(f"{part} 원문 연결 인용 ID 불일치/중복")
                continue
            linked.add(cid)
            for name in ("target_url", "source_location"):
                if link.get(name) is None:
                    pending.append(f"{part} {cid} {name} 누락")
                elif link[name] != used[cid][name]:
                    failures.append(f"{part} {cid} {name} 원문 불일치")
        if not set(cids) <= linked:
            pending.append(f"{part} 인용별 원문 연결 누락")
    if set(used) - covered:
        pending.append(f"{label} 사용 인용의 주장 검토 누락")


def audit_answers(run_dir: Path, protocol: dict, manifest: dict,
                  verifier, manual_path: Optional[Path]) -> dict:
    expected_conditions = protocol["answer"]
    for name in ("provider", "model", "prompt_version"):
        if not isinstance(expected_conditions.get(name), str) or not expected_conditions[name].strip():
            raise ValueError(f"등록한 답변 생성 조건 누락: {name}")
    parent_dir = evaluation.ROOT / manifest["retrieval_run"]
    if evaluation.sha256_file(parent_dir / "manifest.json") != manifest["retrieval_manifest_sha256"]:
        raise ValueError("T17 입력 검색 실행 연결 불일치")
    parent_result = evaluation.audit_run(parent_dir)
    if parent_result["repeated"] != "PASS" or any(
            parent_result["gates"][name]["status"] != "PASS" for name in ("G0", "G1", "G2", "G3", "G4")):
        raise ValueError("검색 품질 미달 후보의 실제 답변 채택 평가")
    needed, baselines, trials = comparison_inputs(verifier, parent_dir)
    expected = {(qid, track) for qid in needed for track in ("B0", "T15")}
    cases = evaluation.unique_rows(json.loads((run_dir / "cases.json").read_bytes()), ("query_id", "track"))
    rows = evaluation.read_rows(run_dir / "answer_records.jsonl")
    indexed = evaluation.unique_rows(rows, ("query_id", "track"))
    evaluation.unique_rows(rows, ("run_id",))
    if set(cases) != expected or set(indexed) != expected:
        raise ValueError("필수31개·문맥 변경 질문의 B0/T15 비교 누락/추가")
    path = manual_path or run_dir / "manual_reviews.json"
    reviews = json.loads(path.read_bytes()) if path.exists() else {}
    if not isinstance(reviews, dict):
        raise ValueError("수동 검토 파일 구조 오류")
    failures, pending, checked = [], [], set()
    reference_file = {"path": str((run_dir / "cases.json").relative_to(evaluation.ROOT)),
                      "sha256": evaluation.sha256_file(run_dir / "cases.json")}
    for (qid, track), case in cases.items():
        row = indexed[qid, track]
        if case["query"] != verifier.questions[qid]["query"]:
            raise ValueError("T17 원질문 변경")
        expected_digest = trials[qid]["bundle_digest"] if track == "T15" else evaluation.digest(baselines[qid])
        if evaluation.digest(case["retrieval"]) != expected_digest:
            raise ValueError("부모 검색 bundle과 실제 생성 입력 불일치")
        reference = {"query": case["query"], "retrieval": case["retrieval"],
                     "parent": case["parent"], "input_reference": reference_file}
        _check_record(row, reference, evaluation.ROOT, failures, pending)
        _check_code_state(row, evaluation.ROOT, checked, failures, pending)
        actual_conditions = {"provider": row.get("generation", {}).get("provider"),
                             "model": row.get("generation", {}).get("model"),
                             "prompt_version": row.get("prompt", {}).get("version")}
        for name, value in actual_conditions.items():
            if value is None:
                pending.append(f"답변 생성 조건 누락: {qid} {track} {name}")
            elif value != expected_conditions[name]:
                failures.append(f"등록한 답변 생성 조건 불일치: {qid} {track} {name}")
        if not verifier.questions[qid]["gold_support_doc_ids"] and row["output"]["status"] == "SUPPORTED":
            failures.append(f"부정 질문 허위 지원: {qid}")
        _manual_review(reviews.get(row["run_id"]), row, indexed[qid, "B0"], failures, pending)
    verdict = "FAIL" if failures else "PENDING" if pending else "PASS"
    return {"overall_verdict": verdict, "exit_code": {"PASS": 0, "FAIL": 1, "PENDING": 2}[verdict],
            "adoption_status": "PASS" if verdict == "PASS" else "B0_MAINTAINED",
            "record_count": len(rows), "failures": failures, "pending": pending}
