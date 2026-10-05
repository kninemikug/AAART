#!/usr/bin/env python3
"""Rebuild and verify the T8-2 selected stack from tracked inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE = ROOT / "docs/T08_2_t9_handoff_reference.json"
DEFAULT_WORK_DIR = ROOT / "data/embedding-benchmark/t08-2/t9-handoff-repro"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def run_step(label: str, arguments: list[str]) -> None:
    print(f"[{label}] {' '.join(arguments)}", flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True)


def query_log_digests(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    records.sort(key=lambda record: (record["query_id"], record["repeat"]))
    keys = [(record["query_id"], record["repeat"]) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate query/repeat in reproduced log")
    rankings = []
    evaluations = []
    for record in records:
        qid, repeat = record["query_id"], record["repeat"]
        ids = [chunk["chunk_id"] for chunk in record["top5"]]
        if len(ids) != 5 or len(set(ids)) != 5:
            raise ValueError(f"Invalid top5 for {qid}, repeat {repeat}")
        rankings.append([qid, repeat, ids])
        evaluation = dict(record["query_result"])
        evaluation.pop("top5_distances", None)
        evaluations.append([qid, repeat, evaluation])
    return {
        "records": len(records),
        "ranked_top5_sha256": stable_digest(rankings),
        "query_evaluation_sha256": stable_digest(evaluations),
    }


def max_distance_delta(path: Path, expected: dict[str, list[float]]) -> float:
    largest = 0.0
    seen = set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            qid = record["query_id"]
            if qid not in expected or len(record["top5"]) != len(expected[qid]):
                raise ValueError(f"Unexpected distance reference for {qid}")
            seen.add(qid)
            for chunk, before in zip(record["top5"], expected[qid]):
                largest = max(largest, abs(chunk["distance"] - before))
    require_equal("queries with distance references", seen, set(expected))
    if largest > 1e-5:
        raise ValueError(f"Top5 distance delta {largest} exceeds 1e-5")
    return largest


def reproduce(reference: dict[str, object], work_dir: Path) -> dict[str, object]:
    if work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError(f"Use an empty work directory for a fresh run: {work_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    chunks = work_dir / "chunks"
    environment = work_dir / "environment" / "environment.json"
    matrix = work_dir / "selected-matrix.json"
    result = work_dir / "selected-results.json"
    selected = reference["selected"]
    build = reference["build"]

    run_step("tokenizers", [python, "scripts/benchmark_embeddings.py", "preflight",
        "--stage", "tokenizers", "--work-dir", str(environment.parent)])
    model_manifest = json.loads(environment.read_bytes())
    require_equal("model revision", model_manifest["models"][selected["model_id"]]["revision"],
        selected["model_revision"])

    run_step("sources", [python, "scripts/chunk_corpus.py", "prepare",
        "--output-dir", str(chunks), "--baseline-md", str(work_dir / "unused.md"),
        "--baseline-json", str(work_dir / "unused.json")])
    run_step("chunks", [python, "scripts/chunk_corpus.py", "build",
        "--manifest", str(chunks / "manifest.json"), "--model-manifest", str(environment),
        "--rawpedia-rules", build["rawpedia_family"],
        "--github-rules", build["github_family"],
        "--target-tokens-grid", *map(str, build["target_tokens_grid"]),
        "--overlap-tokens-grid", *map(str, build["overlap_tokens_grid"]),
        "--thread-window-tokens-grid", *map(str, build["thread_window_tokens_grid"]),
        "--guard-group", selected["guard_group"],
        "--physical-embedding-policy", selected["physical_embedding_policy"],
        "--thread-embedding-policy", selected["thread_embedding_policy"],
        "--encoder-window-tokens", str(selected["encoder_window_tokens"]),
        "--encoder-overlap-tokens", str(selected["encoder_overlap_tokens"])])
    run_step("chunk-check", [python, "scripts/chunk_corpus.py", "check",
        "--manifest", str(chunks / "manifest.json"), "--verify-regeneration"])
    manifest = json.loads((chunks / "manifest.json").read_bytes())
    for source in ("rawpedia", "github"):
        rule = selected[f"{source}_rule"]
        actual = manifest["chunking_rules"][rule]
        expected = reference["chunks"][source]
        require_equal(f"{source} chunk count", actual["chunk_count"], expected["count"])
        require_equal(f"{source} chunk SHA", actual["file_sha256"], expected["sha256"])

    run_step("matrix", [python, "scripts/benchmark_embeddings.py", "matrix",
        "--chunk-manifest", str(chunks / "manifest.json"),
        "--model-manifest", str(environment), "--queries", "docs/search_eval_queries.json",
        "--model-ids", selected["model_id"],
        "--rawpedia-variant-ids", selected["rawpedia_rule"],
        "--github-variant-ids", selected["github_rule"],
        "--guard-group", selected["guard_group"], "--output-json", str(matrix)])
    declared = json.loads(matrix.read_bytes())["experiments"]
    require_equal("selected matrix row count", len(declared), 1)
    run_step("search", [python, "scripts/benchmark_embeddings.py", "run",
        "--matrix", str(matrix), "--chunk-manifest", str(chunks / "manifest.json"),
        "--model-manifest", str(environment), "--queries", "docs/search_eval_queries.json",
        "--guard-group", selected["guard_group"], "--context-budgets", "2048", "4096",
        "--ks", "1", "3", "5", "--device", "cpu", "--batch-size", "16",
        "--seed", "42", "--warmup-queries", "10", "--query-repeat", "3",
        "--work-dir", str(work_dir / "run"), "--output-json", str(result)])
    run_step("log-check", [python, "scripts/benchmark_embeddings.py", "check",
        "--input-json", str(result), "--work-dir", str(work_dir / "check")])

    fresh = json.loads(result.read_bytes())
    require_equal("protocol SHA", fresh["protocol_sha256"], reference["protocol_sha256"])
    row = fresh["experiments"][0]
    require_equal("selected model", row["model_id"], selected["model_id"])
    require_equal("selected revision", row["model_revision"], selected["model_revision"])
    require_equal("retrieval metrics", row["metrics"], reference["metrics"])
    for source in ("rawpedia", "github"):
        require_equal(f"{source} vector SHA", row["document_inputs"][source]["vectors"]["sha256"],
            reference["vectors"][source])
    require_equal("query vector SHA", row["query_vectors"]["sha256"], reference["vectors"]["queries"])
    log_path = Path(row["query_log"]["path"])
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    observed_log = query_log_digests(log_path)
    require_equal("query log evidence", observed_log, reference["query_log"])
    distance_delta = max_distance_delta(log_path, reference["distances_by_query"])
    return {
        "status": "passed", "selected_experiment_id": selected["experiment_id"],
        "reproduced_experiment_id": row["experiment_id"],
        "protocol_sha256": fresh["protocol_sha256"], "chunks": reference["chunks"],
        "vectors": reference["vectors"], "query_log": observed_log,
        "max_top5_distance_delta": distance_delta,
        "metrics": row["metrics"], "result_path": str(result),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    args = parser.parse_args()
    reference_path = args.reference.resolve()
    work_dir = args.work_dir.resolve()
    reference = json.loads(reference_path.read_bytes())
    require_equal("reference schema", reference["schema_version"], 1)
    proof = reproduce(reference, work_dir)
    proof["reference_sha256"] = sha256_file(reference_path)
    proof_path = work_dir / "reproduction.json"
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SUCCESS: T9 selected stack reproduced: {proof_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
