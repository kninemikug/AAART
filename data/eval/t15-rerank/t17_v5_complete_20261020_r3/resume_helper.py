#!/usr/bin/env python3
"""검증된 T15 답변을 보존하고 누락된 쌍만 이어 실행한다.

원본 실행은 수정하지 않는다. 새 실행의 입력 파일 연결만 바꾼 재사용 행은
원본 행·manifest 해시와 연결하며, 실제 생성 오류가 한 번 발생하면 중단한다.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from artagent.answer import normalize_query
from artagent.answer_validation import _check_code_state, _check_record, capture_code_state, record_digest
from artagent.graph.answer import T17_PROMPT_VERSION, answer_standalone
from artagent.graph.state import Evidence, RetrievalBundle
from scripts.eval_t15_rerank import row_writer, seal, write_json
from scripts.t15_answer_validation import comparison_inputs
from scripts.t15_evaluation import MissingEvidence, RecordVerifier, audit_run, digest, read_rows, sha256_file, unique_rows, verify_manifest

# source snapshot이 없는 최초 재개 기록의 도구 바이트를 Git에서 검증한다.
LEGACY_HELPER_COMMIT = "b56e63e5c609753f6abb716bd37b7ea296b382ef"


def successful(row: dict) -> bool:
    return (row.get("output", {}).get("status") in
            ("SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE")
            and row["output"].get("error") is None and row.get("error") is None)


def select_existing(sources: list[list[dict]], expected: set[tuple[str, str]]) -> dict:
    """입력 순서상 최초 성공을 택한다. 실패 행 때문에 성공을 재생성하지 않는다."""
    selected = {}
    for index, rows in enumerate(sources):
        indexed = unique_rows(rows, ("query_id", "track"))
        if not set(indexed) <= expected:
            raise ValueError("이어 실행 원본의 비교 대상 불일치")
        for key, row in indexed.items():
            if successful(row) and key not in selected:
                selected[key] = (index, row)
    return selected


def rebind(row: dict, reference: dict) -> dict:
    result = copy.deepcopy(row)
    result["input_reference"] = reference
    return result


def execute_missing(cases: list[dict], existing: dict, generate, emit) -> list[tuple[str, str]]:
    """누락된 행만 호출하고 첫 오류에서 멈춘다. 재시도 루프는 없다."""
    attempted = []
    for case in cases:
        key = case["query_id"], case["track"]
        if key in existing:
            continue
        row = generate(case)
        emit(row)
        attempted.append(key)
        if not successful(row):
            break
    return attempted


def load_sources(paths: list[Path], *, ancestors: frozenset[Path] = frozenset()):
    manifests, protocols, cases, rows = [], [], None, []
    for path in paths:
        protocol, manifest = verify_manifest(path)
        if manifest.get("phase") != "t17":
            raise ValueError("실제 답변 실행만 이어받을 수 있습니다.")
        if "resumption" in manifest:
            check_origins(path, ancestors=ancestors)
        current = json.loads((path / "cases.json").read_bytes())
        if cases is not None and digest(current) != digest(cases):
            raise ValueError("이어 실행 간 질문·문맥·부모 불일치")
        if manifests and any(manifest.get(k) != manifests[0].get(k) for k in
                             ("protocol_sha256", "retrieval_run", "retrieval_manifest_sha256", "selected_sha256", "selected_path")):
            raise ValueError("이어 실행 간 등록 조건/검색 부모/선정 조건 불일치")
        cases = current
        manifests.append(manifest)
        protocols.append(protocol)
        rows.append(read_rows(path / "answer_records.jsonl"))
    return protocols[0], manifests, cases, rows


def check_helper_source(out: Path, resume: dict) -> None:
    expected = resume["helper_sha256"]
    if sha256_file(Path(__file__).resolve()) == expected:
        return
    snapshot = resume.get("helper_source")
    if snapshot is not None:
        path = (out / snapshot).resolve()
        if not path.is_relative_to(out.resolve()) or sha256_file(path) != expected:
            raise ValueError("이어 실행 도구 원본 지문 불일치")
        return
    original = subprocess.check_output(
        ["git", "show", f"{LEGACY_HELPER_COMMIT}:scripts/resume_t15_answers.py"], cwd=ROOT)
    if hashlib.sha256(original).hexdigest() != expected:
        raise ValueError("이어 실행 도구 지문 불일치")


def check_origins(out: Path, *, ancestors: frozenset[Path] = frozenset()) -> dict:
    """재사용은 원본과 입력 파일 연결 외의 모든 필드가 같아야 한다."""
    out = out.resolve()
    if out in ancestors:
        raise ValueError("이어 실행 원본 계보 순환")
    _, manifest = verify_manifest(out)
    resume = manifest["resumption"]
    check_helper_source(out, resume)
    paths = [ROOT / source["path"] for source in resume["sources"]]
    for path, source in zip(paths, resume["sources"]):
        if sha256_file(path / "manifest.json") != source["manifest_sha256"]:
            raise ValueError("이어 실행 원본 manifest 변경")
    _, _, cases, sources = load_sources(paths, ancestors=ancestors | {out})
    if digest(cases) != digest(json.loads((out / "cases.json").read_bytes())):
        raise ValueError("이어 실행 입력 변경")
    origins = json.loads((out / "origins.json").read_bytes())
    rows = unique_rows(read_rows(out / "answer_records.jsonl"), ("run_id",))
    if set(origins) != {key[0] for key in rows}:
        raise ValueError("이어 실행 원본 연결 누락/추가")
    expected = {(c["query_id"], c["track"]) for c in cases}
    selected = select_existing(sources, expected)
    reference = {"path": str((out / "cases.json").relative_to(ROOT)), "sha256": sha256_file(out / "cases.json")}
    reused = fresh = 0
    for (run_id,), row in rows.items():
        origin = origins[run_id]
        if origin["record_digest"] != record_digest(row):
            raise ValueError("이어 실행 행 해시 불일치")
        key = row["query_id"], row["track"]
        if origin["kind"] == "reused":
            index, original = selected[key]
            if (index != origin["source_index"] or origin["source_record_digest"] != record_digest(original)
                    or row != rebind(original, reference)):
                raise ValueError("재사용 행의 원응답/추적/인용/코드 변경")
            reused += 1
        elif origin["kind"] == "fresh" and key not in selected:
            fresh += 1
        else:
            raise ValueError("성공 행 중복 생성 또는 원본 연결 종류 오류")
    return {"reused_record_count": reused, "fresh_attempt_count": fresh,
            "missing_count": len(expected - {(r["query_id"], r["track"]) for r in rows.values() if successful(r)})}


def run(paths: list[Path], out: Path, execute: bool) -> int:
    protocol, manifests, cases, sources = load_sources(paths)
    parent = ROOT / manifests[0]["retrieval_run"]
    if sha256_file(parent / "manifest.json") != manifests[0]["retrieval_manifest_sha256"]:
        raise ValueError("이어 실행의 부모 검색 manifest 불일치")
    _, parent_manifest = verify_manifest(parent)
    if any(manifests[0][key] != parent_manifest[key] for key in ("selected_sha256", "selected_path")):
        raise ValueError("이어 실행의 부모 선정 조건 불일치")
    result = audit_run(parent)
    if result["repeated"] != "PASS" or any(result["gates"][g]["status"] != "PASS" for g in ("G0", "G1", "G2", "G3", "G4")):
        raise ValueError("검색 선행 게이트 미달")
    verifier = RecordVerifier(protocol)
    needed, baselines, trials = comparison_inputs(verifier, parent)
    expected = {(qid, track) for qid in needed for track in ("B0", "T15")}
    if set(unique_rows(cases, ("query_id", "track"))) != expected:
        raise ValueError("필수 질문 또는 문맥 변경 질문 누락")
    for case in cases:
        qid, track = case["query_id"], case["track"]
        if case["query"] != verifier.questions[qid]["query"]:
            raise ValueError("이어 실행 원질문 변경")
        bundle_digest = trials[qid]["bundle_digest"] if track == "T15" else digest(baselines[qid])
        if digest(case["retrieval"]) != bundle_digest:
            raise ValueError("이어 실행의 부모 검색 문맥 불일치")
        if case["parent"] != f"{parent.name}:{track}:{qid}":
            raise ValueError("이어 실행의 부모 비교 쌍 불일치")
    existing = select_existing(sources, expected)
    checked = set()
    for key, (index, row) in existing.items():
        case = next(c for c in cases if (c["query_id"], c["track"]) == key)
        ref = {"path": str((paths[index] / "cases.json").relative_to(ROOT)),
               "sha256": sha256_file(paths[index] / "cases.json")}
        failures, pending = [], []
        _check_record(row, {**case, "input_reference": ref}, ROOT, failures, pending)
        _check_code_state(row, ROOT, checked, failures, pending)
        actual = {"provider": row["generation"]["provider"], "model": row["generation"]["model"],
                  "prompt_version": row["prompt"]["version"]}
        if failures or pending or actual != protocol["answer"]:
            raise ValueError(f"재사용 답변 검증 실패 {key}: {failures + pending}")
    missing = sorted(expected - set(existing))
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "resume_plan.json", {"required": len(expected), "reused": len(existing),
               "missing": missing, "execute_missing": execute, "stop_after_first_error": True})
    print(json.dumps({"required": len(expected), "reused": len(existing), "missing": missing}, ensure_ascii=False), flush=True)
    if not execute:
        return 2
    if (os.getenv("LLM_PROVIDER", "codex").lower().strip() != "codex" or
            protocol["answer"] != {"provider": "codex-cli", "model": os.getenv("LLM_MODEL") or os.getenv("CODEX_MODEL") or "gpt-5.6-sol",
                                    "prompt_version": T17_PROMPT_VERSION}):
        raise ValueError("등록한 실제 생성 조건 불일치")
    write_json(out / "cases.json", cases)
    helper_source = Path(__file__).resolve().read_bytes()
    (out / "resume_helper.py").write_bytes(helper_source)
    reference = {"path": str((out / "cases.json").relative_to(ROOT)), "sha256": sha256_file(out / "cases.json")}
    origins = {}

    def generate(case):
        observation = {}
        bundle = RetrievalBundle(**{**case["retrieval"], "hits": [Evidence(**h) for h in case["retrieval"]["hits"]]})
        answer, error = answer_standalone(case["query"], bundle, source_root=ROOT, observe=observation.update)
        meta = observation.get("runtime_meta") or {}
        return {"record_schema": "t17-run-v3", "runtime": capture_code_state(ROOT), "input_reference": reference,
                "run_id": f"{out.name}:{case['track']}:{case['query_id']}", "track": case["track"], "query_id": case["query_id"],
                "original_run_id": case["parent"], "input": {"query_original": case["query"], "query_normalized": normalize_query(case["query"]), "confirmed_context": None, "constraints": []},
                "retrieval": case["retrieval"], "prompt": {"version": T17_PROMPT_VERSION, **{k: observation.get(k) for k in ("system_instruction", "user_prompt", "prompt_hash")}},
                "generation": {"call_count": observation.get("call_count", 0), "request": observation.get("request"), "provider": meta.get("llm_provider"), "model": meta.get("model_id"), "is_mock": False,
                               "runtime_meta": meta, "trace": observation.get("trace") or meta.get("_trace"), "usage": observation.get("usage"), "raw_response": observation.get("raw_response")},
                "citations": [asdict(c) for c in answer.citations] if answer else [], "used_citations_provenance": observation.get("used_citations_provenance", []),
                "output": {**asdict(answer), "error": asdict(error) if error else None} if answer else {"status": None, "error": asdict(error)}, "verification": {"manual_review": "pending"}}

    try:
        with row_writer(out / "answer_records.jsonl") as emit:
            for index, row in existing.values():
                rebound = rebind(row, reference)
                emit(rebound)
                origins[row["run_id"]] = {"kind": "reused", "source_index": index,
                    "source_record_digest": record_digest(row), "record_digest": record_digest(rebound)}

            def emit_new(row):
                emit(row)
                origins[row["run_id"]] = {"kind": "fresh", "record_digest": record_digest(row)}
                print(f"{row['query_id']} {row['track']}: {'success' if successful(row) else 'ERROR; stopped'}", flush=True)

            execute_missing(cases, existing, generate, emit_new)
    finally:
        write_json(out / "origins.json", origins)
        seal(out, ROOT / manifests[0]["protocol_path"], "t17", **{k: manifests[0][k] for k in
             ("retrieval_run", "retrieval_manifest_sha256", "selected_path", "selected_sha256")},
             resumption={"helper_sha256": hashlib.sha256(helper_source).hexdigest(),
                 "helper_source": "resume_helper.py", "sources": [
                 {"path": str(p.relative_to(ROOT)), "manifest_sha256": sha256_file(p / "manifest.json")} for p in paths]})
    progress = check_origins(out)
    print(json.dumps(progress, ensure_ascii=False), flush=True)
    return 2 if progress["missing_count"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", action="append", default=[])
    parser.add_argument("--output-dir")
    parser.add_argument("--execute-missing", action="store_true")
    parser.add_argument("--check-run")
    parser.add_argument("--manual-reviews")
    args = parser.parse_args()
    if args.check_run:
        out = Path(args.check_run).resolve()
        result = {}
        try:
            result["resumption"] = check_origins(out)
            result.update(audit_run(out, manual_path=Path(args.manual_reviews).resolve() if args.manual_reviews else None))
        except MissingEvidence as error:
            result.update(overall_verdict="PENDING", exit_code=2, adoption_status="B0_MAINTAINED",
                          reason=f"{type(error).__name__}: {error}")
        except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
            result.update(overall_verdict="FAIL", exit_code=1, adoption_status="B0_MAINTAINED",
                          reason=f"{type(error).__name__}: {error}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result["exit_code"]
    if not args.source_run or not args.output_dir:
        parser.error("--source-run과 --output-dir이 필요합니다.")
    return run([Path(p).resolve() for p in args.source_run], Path(args.output_dir).resolve(), args.execute_missing)


if __name__ == "__main__":
    sys.exit(main())
