"""Resume the fixed T17 evaluation into a new directory, preserving prior runs."""
import importlib.util
import json
import os
from pathlib import Path
import sys

def main():
    root = Path.cwd()
    sys.path.insert(0, str(root / "src"))
    from artagent.answer_validation import evaluate_records, reference_cases, record_digest
    from artagent.graph.state import Evidence, RetrievalBundle
    from artagent.retrieval.provenance import sha256_bytes

    spec = importlib.util.spec_from_file_location("t17_runner", root / "scripts/check_t17_answer.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    source, destination = map(Path, sys.argv[1:3])
    cases = reference_cases(root)
    keys = [(qid, track) for track in ("t11_replay", "t14_a", "t14_b") for qid in runner.FIXED_SLICE1_IDS]
    keys += [(qid, f"t14_b_reg_{qid}") for qid in ("Q010", "Q077")]
    records, regressions, reusable = [], [], {}
    source_hashes = {}
    for name, target in (("execution_records.jsonl", records), ("regression_records.jsonl", regressions)):
        path = source / name
        if path.is_file():
            source_hashes[name] = sha256_bytes(path.read_bytes())
            for line in path.read_text().splitlines():
                row = json.loads(line)
                if row["output"]["error"] is None and row["output"]["status"] is not None:
                    target.append(row)
                    reusable[row["query_id"], row["track"]] = row
    verdict, failures, pending = evaluate_records(records, regressions, {}, root, root, [])
    unverified = [reason for reason in pending if not reason.startswith("필수 실행 기록 누락:")]
    if failures or unverified:
        raise RuntimeError({"failures": failures, "unverified": unverified})
    if os.environ.get("LLM_PROVIDER") != "codex" or os.environ.get("LLM_MODEL") != "gpt-5.6-sol":
        raise RuntimeError("기존 제공처와 모델을 유지해야 합니다.")
    destination.mkdir(exist_ok=False)
    manifest = {
        "source": str(source), "source_hashes": source_hashes,
        "reused": [{"query_id": q, "track": t, "run_id": r["run_id"], "record_hash": record_digest(r)} for (q, t), r in reusable.items()],
        "rule": "독립 검증에 통과한 정상 기록만 그대로 재사용. 실패는 원본에 보존하고 새 run_id로 시도.",
    }
    (destination / "resume_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for name, group in (("execution_records.jsonl", records), ("regression_records.jsonl", regressions)):
        (destination / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in group))
    print(f"검증된 정상 기록 {len(reusable)}건 유지, 남은 {len(keys)-len(reusable)}건 재시도", flush=True)
    for key in keys:
        if key in reusable:
            continue
        qid, track = key
        case = cases[key]
        ret = case["retrieval"]
        bundle = RetrievalBundle(ret["query"], ret["source_filter"], [Evidence(**hit) for hit in ret["hits"]], ret["snapshot_ref"])
        row = runner.run_single_evaluation(track, qid, {"query": case["query"]}, bundle, case["parent"], root)
        is_regression = "_reg_" in track
        target = regressions if is_regression else records
        target.append(row)
        filename = "regression_records.jsonl" if is_regression else "execution_records.jsonl"
        with (destination / filename).open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
        print(qid, track, row["output"]["status"], row["output"]["error"], flush=True)
        if row["output"]["error"]:
            for event_line in (row["generation"].get("trace") or {}).get("stdout_jsonl", "").splitlines():
                event = json.loads(event_line)
                if event.get("type") == "error":
                    print(event.get("message"), flush=True)
            break
    verdict, failures, pending = runner.evaluate_gate_b(records, regressions, {}, source_root=root)
    by_id = {r["query_id"]: r for r in regressions}
    runner.generate_comparison_report(records, destination, by_id.get("Q010"), by_id.get("Q077"), {}, verdict, failures, pending)
    print("게이트 B", verdict, "실행 기록", len(records)+len(regressions), flush=True)
    sys.exit({"PASS": 0, "PENDING": 2, "FAIL": 1}[verdict])


if __name__ == "__main__":
    main()
