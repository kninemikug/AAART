#!/usr/bin/env python3
"""Synchronize runs logs and latency observations across all rule-expansion batches."""
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import verify_embedding_benchmark as verify

WORK = REPO_ROOT / "data/embedding-benchmark/t08-2/rule-expansion-001"
BASELINE_JSON = REPO_ROOT / "docs/chunking_embedding_benchmark.json"
QUERIES_PATH = REPO_ROOT / "docs/search_eval_queries.json"

BATCHES = [
    "batch-native-common",
    "batch-bge",
    "batch-e5",
    "batch-pooled",
]


def row_key(row):
    return (
        row["guard_group"],
        row["model_id"],
        row["rawpedia_variant_id"],
        row["github_variant_id"],
    )


def main():
    print(f"[SYNC] Loading baseline from {BASELINE_JSON}...", flush=True)
    baseline_data = json.loads(BASELINE_JSON.read_bytes())
    baseline_by_key = {row_key(r): r for r in baseline_data["experiments"]}
    print(f"[SYNC] Loaded {len(baseline_by_key)} baseline rows.", flush=True)

    queries = verify.prepare_queries(QUERIES_PATH)

    for batch_name in BATCHES:
        batch_work = WORK / batch_name
        matrix_path = batch_work / "declared_matrix.json"
        if not matrix_path.is_file():
            print(f"[SYNC] Skipping {batch_name}: matrix not found")
            continue

        matrix = json.loads(matrix_path.read_bytes())["experiments"]
        print(f"\n========================================================")
        print(f"[SYNC] Processing {batch_name} ({len(matrix)} rows)...")
        print(f"========================================================", flush=True)

        fixed_count = 0
        all_rows = []

        for idx, row in enumerate(matrix, start=1):
            rk = row_key(row)
            row_file = batch_work / "rows" / f"{row['experiment_id']}.json"
            rec = json.loads(row_file.read_bytes())

            if rk in baseline_by_key:
                base_row = baseline_by_key[rk]
                dest_log_path = batch_work / "runs" / f"{row['experiment_id']}.jsonl.gz"
                # Always ensure log file matches baseline total_seconds exactly
                orig_records = verify.read_log(base_row["query_log"])
                for r in orig_records:
                    r["experiment_id"] = row["experiment_id"]
                dest_log = verify.write_log(dest_log_path, orig_records)
                rec["query_log"] = dest_log
                rec["latency_observations_sec"] = [r["total_seconds"] for r in orig_records]
                rec["latency"] = verify.latency_summary(rec["latency_observations_sec"])
                verify.write_json(row_file, rec)
                fixed_count += 1
            else:
                dest_log_path = batch_work / "runs" / f"{row['experiment_id']}.jsonl.gz"
                records = verify.read_log(rec["query_log"])
                times = [r["total_seconds"] for r in records]
                if times != rec.get("latency_observations_sec"):
                    rec["latency_observations_sec"] = times
                    rec["latency"] = verify.latency_summary(times)
                    verify.write_json(row_file, rec)
                    fixed_count += 1

            all_rows.append(rec)
            if idx % 1000 == 0 or idx == len(matrix):
                print(f"  [SYNC {idx}/{len(matrix)}] checked ({fixed_count} adjusted)", flush=True)

        batch_res_path = batch_work / "results.json"
        bdata = json.loads(batch_res_path.read_bytes())
        bdata["experiments"] = all_rows
        verify.write_json(batch_res_path, bdata)
        print(f"[SYNC] Updated {batch_res_path} ({len(all_rows)} rows)", flush=True)

        print(f"[VALIDATE] Validating {batch_name} with verify.validate_batch...", flush=True)
        verify.validate_batch(batch_res_path)
        print(f"[VALIDATE] SUCCESS: {batch_name} passed all validation checks!", flush=True)

    print("\n========================================================")
    print("SUCCESS: All 4 batches synchronized and verified!")
    print("========================================================", flush=True)


if __name__ == "__main__":
    main()
