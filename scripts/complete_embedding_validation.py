#!/usr/bin/env python3
"""Complete the registered 5502-row verification and publish only after all gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import benchmark_embeddings as bench
from scripts import verify_embedding_benchmark as verify
from scripts.verify_embedding_policy_controls import run_controls
from src.artagent.benchmark_validation import compare_retrieval_runs

OLD_RUN = ROOT / "data/embedding-benchmark/t08-2/remeasurement-001"
CHUNKS = ROOT / "data/chunks/t08-2-remeasurement"
BATCHES = (("batch-native-common", "native-common-256", 1080), ("batch-bge", "bge-512", 1548),
           ("batch-e5", "e5-512", 774), ("batch-pooled", "pooled-common-256", 2100))


def expected_keys():
    """Construct the approved union independently of files produced by the worker."""
    models = list(bench.MODEL_CONFIGS)
    keys = set()
    def add(group, chosen, lengths, overlaps, unit_l, unit_o, windows, fixed=None):
        github = [f"G-B-curated-unit-t{l}-o{o}" for l in unit_l for o in unit_o]
        github += [f"G-A-{kind}-thread-w{w}-wo0" for kind in ("curated", "full") for w in windows]
        if fixed:
            github = [f"G-A-curated-thread-w{fixed}-wo0"]
        for m in chosen:
            for family in ("R-A-heading", "R-B-window"):
                for length in lengths:
                    for overlap in overlaps:
                        for g in github:
                            keys.add((group, m, f"{family}-t{length}-o{overlap}", g))
    add("native-common-256", models, [128,192,224], [0,32,64], [128,192,224], [0,32,64], [128,192,224])
    for group, selected in (("bge-512", models[:2]), ("e5-512", [models[3]])):
        add(group, selected, [224,256,320,384,448], [0,32,64], [224,256,320,384,448], [0,32,64], [224,256,320,384,448])
        for model in selected:
            fixed = 384 if model == models[0] else 320 if model == models[1] else 224
            add(group, [model], [464,480,496,512], [0,32,64], [], [], [], fixed=fixed)
    add("pooled-common-256", models, [224,448,512,768,1024], [0,64,128], [224,448,512,768,1024], [0,64,128], [224])
    add("pooled-common-256", models[2:], [1536,2048,4096,6144,8192], [0,64,128], [], [], [], fixed=224)
    assert len(keys) == 5502
    return keys


def row_key(row):
    return (row["guard_group"], row["model_id"], row["rawpedia_variant_id"], row["github_variant_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default="data/embedding-benchmark/t08-2/validation-001")
    args = parser.parse_args()
    work = Path(args.work_dir).resolve()
    if work == OLD_RUN:
        raise ValueError("Historical results must be preserved")
    declarations = []
    for name, group, count in BATCHES:
        rows = json.loads((OLD_RUN / name / "experiment_matrix.json").read_bytes())["experiments"]
        if len(rows) != count:
            raise ValueError(f"Wrong declared batch size: {name}")
        declarations.extend(rows)
    actual = {row_key(r) for r in declarations}
    if len(actual) != len(declarations) or actual != expected_keys():
        raise ValueError("The full union has missing, duplicate or unexpected combinations")
    settings = argparse.Namespace(queries=str(ROOT / "docs/search_eval_queries.json"), device="cpu", seed=42,
        batch_size=16, query_repeat=3, warmup_queries=10, ks=[1,3,5], context_budgets=[2048,4096])
    if not (work / "historical_baseline.json").is_file():
        verify.write_json(work / "historical_baseline.json", {"git_commit": "382cc2722",
        "report": verify.artifact(ROOT / "docs/chunking_embedding_benchmark.json"),
        "declared_counts": {name: count for name, _, count in BATCHES}})
    current_protocol = verify.sha256_bytes(verify.canonical_json_bytes(verify.protocol(settings)))
    regeneration = []
    for _, group, _ in BATCHES:
        proof = work / "regeneration" / (group + ".json")
        if proof.is_file():
            saved = json.loads(proof.read_bytes())
            if saved["protocol_sha256"] != current_protocol or saved["log"]["sha256"] != verify.digest_file(ROOT / saved["log"]["path"]):
                raise ValueError("Regeneration resume fingerprint mismatch")
        else:
            log_path = proof.with_suffix(".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"REGENERATE {group}", flush=True)
            with log_path.open("w") as log:
                subprocess.run([sys.executable, str(ROOT / "scripts/chunk_corpus.py"), "check", "--manifest",
                    str(CHUNKS / group / "manifest.json"), "--queries", settings.queries, "--verify-regeneration"],
                    stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
            saved = {"status": "passed", "protocol_sha256": current_protocol,
                "manifest": verify.artifact(CHUNKS / group / "manifest.json"), "log": verify.artifact(log_path)}
            verify.write_json(proof, saved)
        regeneration.append(verify.artifact(proof))
    control_path = work / "controls" / "policy_controls.json"
    if control_path.is_file():
        controls = json.loads(control_path.read_bytes())
        if controls["protocol_sha256"] != current_protocol:
            raise ValueError("Policy control resume protocol mismatch")
        queries = verify.prepare_queries(settings.queries)
        for row in controls["controls"]:
            verify.validate_row(row, queries, 3)
    else:
        controls = run_controls(work / "controls", settings)
    inputs = []
    for name, group, count in BATCHES:
        output = work / name / "results.json"
        run_args = argparse.Namespace(**vars(settings), matrix=str(OLD_RUN / name / "experiment_matrix.json"),
            chunk_manifest=str(CHUNKS / group / "manifest.json"),
            model_manifest=str(OLD_RUN / name / "environment.json"), guard_group=group,
            work_dir=str(work / name), output_json=str(output))
        verify.run_matrix(run_args)
        inputs.append(str(output))
    combined = work / "results.json"
    bench.cmd_combine(argparse.Namespace(inputs=inputs, extension_decision=str(OLD_RUN / "extension_decision.json"), output_json=str(combined)))
    data = json.loads(combined.read_bytes())
    if len(data["experiments"]) != 5502 or {row_key(r) for r in data["experiments"]} != expected_keys():
        raise ValueError("Combined result differs from declared full union")
    if sum(len(r["latency_observations_sec"]) for r in data["experiments"]) != 1650600:
        raise ValueError("Missing real query/repeat observations")
    verify.check_report(argparse.Namespace(input_json=str(combined), work_dir=str(work / "recheck"), verify_top_candidates=True))
    c2 = next(r for r in controls["controls"] if r["experiment_id"] == "C2")
    current = next(r for r in data["experiments"] if row_key(r) == row_key(c2))
    queries = verify.prepare_queries(settings.queries)
    compare_retrieval_runs({"metrics": c2["metrics"], "query_results": verify.validate_row(c2, queries, 3)},
                           {"metrics": current["metrics"], "query_results": verify.validate_row(current, queries, 3)})
    data["validation_status"] = "passed"
    data["validation"] = {"policy_controls": verify.artifact(control_path),
        "regeneration": regeneration,
        "independent_reproduction": verify.artifact(work / "recheck/reproduction.json"),
        "registered_rows": 5502, "formal_rows": 4716, "diagnostic_rows": 786,
        "observations_count": 1650600, "matrix_keys_sha256": verify.sha256_bytes(verify.canonical_json_bytes(sorted(expected_keys())))}
    verify.write_json(combined, data)
    bench.cmd_report_markdown(argparse.Namespace(input_json=str(combined),
        output_json=str(ROOT / "docs/chunking_embedding_benchmark.json"),
        output_md=str(ROOT / "docs/chunking_embedding_benchmark.md")))
    print("COMPLETE: full 5502-row validation, controls, reproduction and report publication passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
