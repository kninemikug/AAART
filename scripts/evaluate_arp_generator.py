#!/usr/bin/env python3
"""Run or independently replay the fixed twenty-profile T19 acceptance evaluation."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artagent.arp.generator import PROMPT_VERSION, generate_profile, parse_profile, strict_json
from artagent.arp.runtime import RuntimeFailure, validate_evidence, validate_failure_evidence
from artagent.features import dumps_features, extract_features

CASE_PATH = ROOT / "tests/t19_cases.py"
CASE_DEFINITIONS = runpy.run_path(str(CASE_PATH))
CASES = CASE_DEFINITIONS["CASES"]
MATCHES = CASE_DEFINITIONS["matches_request"]
SAMPLE = ROOT / "data/fivek_sample/sample1.nef"
SAMPLE_HASH = "18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805"
SOURCE_PATHS = ("rtgui/ppversion.h", "src/artagent/arp/schema.json",
                "src/artagent/arp/generator.py", "src/artagent/arp/runtime.py",
                "scripts/evaluate_arp_generator.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def evaluate(run_dir: Path) -> dict:
    """Persist inputs before invocation, and each first response before continuing."""
    if len(CASES) != 20 or sha(SAMPLE) != SAMPLE_HASH:
        raise ValueError("Fixed evaluation inputs differ")
    run_dir.mkdir(parents=True, exist_ok=False)
    features = strict_json(dumps_features(extract_features(SAMPLE)))
    write_json(run_dir / "features.json", features)
    manifest = {"cases": CASES, "cases_sha256": sha(CASE_PATH), "raw_sha256": SAMPLE_HASH,
                "features_sha256": sha(run_dir / "features.json"),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "sources": {path: sha(ROOT / path) for path in SOURCE_PATHS}}
    write_json(run_dir / "manifest.json", manifest)
    for case_id, query, expected in CASES:
        result = generate_profile(query, features)
        write_json(run_dir / f"{case_id}.json", result)
        if result["status"] == "ok":
            with (run_dir / f"{case_id}.arp").open("x", encoding="utf-8") as handle:
                handle.write(result["arp"])
        print(f"{case_id}: {result['status']}", flush=True)
        if result["status"] == "runtime_error" and result.get("runtime", {}).get("fatal_infrastructure"):
            # Stop an unavailable environment without making nineteen more calls.
            break
    if sha(SAMPLE) != SAMPLE_HASH:
        raise ValueError("RAW changed during evaluation")
    return check(run_dir)


def check(run_dir: Path) -> dict:
    """Revalidate saved first responses; no network or model calls are permitted."""
    manifest = strict_json((run_dir / "manifest.json").read_text())
    if manifest["cases"] != json.loads(json.dumps(CASES)) or manifest["cases_sha256"] != sha(CASE_PATH):
        raise ValueError("Case manifest mismatch")
    if manifest["raw_sha256"] != SAMPLE_HASH or sha(SAMPLE) != SAMPLE_HASH:
        raise ValueError("RAW identity mismatch")
    if manifest["features_sha256"] != sha(run_dir / "features.json"):
        raise ValueError("Feature input changed")
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_PATHS):
        raise ValueError("Missing or unexpected source fingerprints")
    for path, digest in sources.items():
        if sha(ROOT / path) != digest:
            raise ValueError(f"Evaluation source changed: {path}")
    features = strict_json((run_dir / "features.json").read_text())
    passed = intent = attempted = 0
    for case_id, query, expected in CASES:
        record = run_dir / f"{case_id}.json"
        if not record.is_file():
            continue
        saved = strict_json(record.read_text())
        if not isinstance(saved, dict) or saved.get("status") not in (
                "ok", "runtime_error", "validation_error", "needs_input", "unsupported_request"):
            raise ValueError(f"Invalid saved status: {case_id}")
        identities = {"request_sha256": hashlib.sha256(query.encode()).hexdigest(),
                      "features_sha256": hashlib.sha256(json.dumps(features, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                      "prompt_version": PROMPT_VERSION}
        if any(saved.get(key) != value for key, value in identities.items()):
            raise ValueError(f"Missing or changed request identity: {case_id}")
        metadata, raw = saved.get("runtime"), saved.get("raw_response")
        failure = None
        if "runtime" in saved:
            if not isinstance(metadata, dict) or "raw_response" not in saved:
                raise ValueError(f"Missing invocation evidence: {case_id}")
            try:
                validate_evidence(metadata, raw)
            except ValueError:
                if saved["status"] != "runtime_error":
                    raise
                failure = validate_failure_evidence(metadata, raw)
        runtime_called = False
        def recorded_runtime(prompt):
            nonlocal runtime_called
            runtime_called = True
            if metadata is None:
                raise ValueError("Missing invocation evidence")
            if failure is not None:
                raise RuntimeFailure(failure, metadata, raw)
            return {"raw_response": raw, "metadata": metadata}
        replay = generate_profile(query, features, runtime=recorded_runtime)
        if runtime_called != ("runtime" in saved):
            raise ValueError(f"Invocation evidence does not match execution: {case_id}")
        for key in ("status", "profile", "arp", "request_sha256", "features_sha256", "contract", "prompt_version", "error", "reason", "warnings"):
            if replay.get(key) != saved.get(key):
                raise ValueError(f"Replay mismatch: {case_id}.{key}")
        attempted += 1
        profile_path = run_dir / f"{case_id}.arp"
        if replay["status"] != "ok":
            if profile_path.exists():
                raise ValueError(f"Failed record has an output profile: {case_id}")
            continue
        if parse_profile(profile_path.read_text()) != replay["profile"]:
            raise ValueError(f"Invalid stored profile: {case_id}")
        passed += 1
        intent += int(MATCHES(replay["profile"], expected))
    return {"attempted": attempted, "total": 20, "valid": passed, "valid_rate": passed / 20,
            "request_matches": intent, "accepted": attempted == 20 and passed >= 18}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "check"))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = evaluate(args.run_dir) if args.action == "run" else check(args.run_dir)
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["accepted"] else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
