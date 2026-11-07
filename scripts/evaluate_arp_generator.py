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
from artagent.arp.generator import generate_profile, parse_profile, strict_json
from artagent.features import dumps_features, extract_features

CASE_PATH = ROOT / "tests/t19_cases.py"
CASE_DEFINITIONS = runpy.run_path(str(CASE_PATH))
CASES = CASE_DEFINITIONS["CASES"]
MATCHES = CASE_DEFINITIONS["matches_request"]
SAMPLE = ROOT / "data/fivek_sample/sample1.nef"
SAMPLE_HASH = "18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805"


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
                "sources": {str(path.relative_to(ROOT)): sha(path) for path in [
                    ROOT / "rtgui/ppversion.h", ROOT / "src/artagent/arp/schema.json",
                    ROOT / "src/artagent/arp/generator.py", ROOT / "src/artagent/arp/runtime.py",
                    Path(__file__).resolve()]}}
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
    for path, digest in manifest["sources"].items():
        if sha(ROOT / path) != digest:
            raise ValueError(f"Evaluation source changed: {path}")
    features = strict_json((run_dir / "features.json").read_text())
    passed = intent = attempted = 0
    for case_id, query, expected in CASES:
        record = run_dir / f"{case_id}.json"
        if not record.is_file():
            continue
        attempted += 1
        saved = strict_json(record.read_text())
        if saved["status"] != "ok":
            continue
        metadata = saved["runtime"]
        from artagent.arp.runtime import validate_evidence
        validate_evidence(metadata, saved["raw_response"])
        replay = generate_profile(query, features, runtime=lambda prompt: {
            "raw_response": saved["raw_response"], "metadata": metadata})
        for key in ("status", "profile", "arp", "request_sha256", "features_sha256", "contract", "prompt_version"):
            if replay.get(key) != saved.get(key):
                raise ValueError(f"Replay mismatch: {case_id}.{key}")
        if replay["status"] != "ok" or parse_profile((run_dir / f"{case_id}.arp").read_text()) != replay["profile"]:
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
