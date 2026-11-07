"""Replay acceptance evidence and reject corrupt records without model calls."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import io
import urllib.error

import pytest

from test_arp_generator import features
from test_arp_runtime import events


ROOT = Path(__file__).resolve().parents[1]


def evaluator():
    spec = importlib.util.spec_from_file_location("t19_evaluation", ROOT / "scripts/evaluate_arp_generator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_offline_run(module, features, run_dir, monkeypatch, malformed_first=False, failure_kind=None, captured_failure=None):
    """Synthetic runtime evidence tests the verifier, never counts as a live run."""
    features["source"] = {"path": str(module.SAMPLE), "sha256": module.SAMPLE_HASH}
    monkeypatch.setattr(module, "extract_features", lambda path: features)
    original = module.generate_profile
    attempted = []
    def generate(query, feature_input, **kwargs):
        if "runtime" in kwargs:
            return original(query, feature_input, **kwargs)
        attempted.append(query)
        case_id, _, expected = next(case for case in module.CASES if case[1] == query)
        if case_id == "E01" and captured_failure is not None:
            def captured(prompt):
                raise captured_failure
            return original(query, feature_input, runtime=captured)
        groups = {}
        for name, value in expected.items():
            group, key = name.split(".")
            if isinstance(value, tuple):
                value = (value[0] + value[1]) / 2
                if group == "Saturation":
                    value = int(value)
            groups.setdefault(group, {})[key] = value
        if "White Balance" in groups and "Setting" not in groups["White Balance"]:
            groups["White Balance"].update(Setting="CustomTemp")
            groups["White Balance"].setdefault("Green", 1)
        raw = "not JSON" if malformed_first and case_id == "E01" else json.dumps({"groups": groups, "reason": "fixture"})
        metadata = {"provider": "codex-cli", "model": "fixture", "call_count": 1,
                    "returncode": 0, "stdout_jsonl": events(final=raw), "evidence_verified": True}
        if case_id == "E01" and failure_kind is not None:
            from artagent.arp.runtime import RuntimeFailure
            metadata.update(stdout_jsonl="", stderr="captured failure")
            error = "codex process failed: exit 7"
            if failure_kind == "timeout":
                metadata.update(timeout=True, timeout_seconds=120)
                error = "Runtime timeout"
            else:
                metadata["returncode"] = 7
            def fail(prompt):
                raise RuntimeFailure(error, metadata, "")
            return original(query, feature_input, runtime=fail)
        return original(query, feature_input, runtime=lambda prompt: {"raw_response": raw, "metadata": metadata})
    monkeypatch.setattr(module, "generate_profile", generate)
    summary = module.evaluate(run_dir)
    return summary, attempted


@pytest.fixture
def recorded_run(features, tmp_path, monkeypatch):
    module = evaluator()
    destination = tmp_path / "run"
    live_path = os.getenv("T19_RUN_DIR")
    if live_path:
        shutil.copytree(live_path, destination)
    else:
        create_offline_run(module, features, destination, monkeypatch)
    return module, destination


def test_acceptance_records_replay(recorded_run):
    module, run_dir = recorded_run
    summary = module.check(run_dir)
    assert summary["total"] == 20
    assert summary["attempted"] == 20
    assert summary["valid"] >= 18
    assert summary["accepted"] is True


@pytest.mark.parametrize("mutation", [{"returncode": 99}, {"call_count": 9},
                                      {"stdout_jsonl": events({"type": "item.completed", "item": {"type": "command_execution"}})}])
def test_corrupt_evidence_cannot_keep_pass_flag(recorded_run, mutation):
    module, run_dir = recorded_run
    path = run_dir / "E01.json"
    record = json.loads(path.read_text())
    record["runtime"].update(mutation)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        module.check(run_dir)


def test_one_malformed_response_still_attempts_all_twenty(features, tmp_path, monkeypatch):
    module = evaluator()
    summary, attempted = create_offline_run(module, features, tmp_path / "run", monkeypatch, malformed_first=True)
    assert len(attempted) == 20
    assert summary["valid"] == 19
    assert summary["accepted"] is True


@pytest.mark.parametrize("mutation", ["empty", "missing", "extra"])
def test_source_fingerprints_are_required_as_an_exact_set(recorded_run, mutation):
    module, run_dir = recorded_run
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text())
    if mutation == "empty":
        manifest["sources"] = {}
    elif mutation == "missing":
        del manifest["sources"]["src/artagent/arp/generator.py"]
    else:
        manifest["sources"]["../outside-file"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.check(run_dir)


@pytest.mark.parametrize("status", ["runtime_error", "validation_error", "needs_input", "unknown"])
def test_unproven_failure_records_cannot_count_as_attempts(recorded_run, status):
    module, run_dir = recorded_run
    for case in ("E01", "E02"):
        (run_dir / f"{case}.json").write_text(json.dumps({"status": status}))
        (run_dir / f"{case}.arp").unlink()
    with pytest.raises(ValueError):
        module.check(run_dir)


def test_failures_must_keep_request_identity(features, tmp_path, monkeypatch):
    module = evaluator()
    run_dir = tmp_path / "run"
    create_offline_run(module, features, run_dir, monkeypatch, malformed_first=True)
    path = run_dir / "E01.json"
    record = json.loads(path.read_text())
    record["request_sha256"] = "0" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        module.check(run_dir)


def test_runtime_failure_requires_process_evidence(features, tmp_path, monkeypatch):
    module = evaluator()
    run_dir = tmp_path / "run"
    create_offline_run(module, features, run_dir, monkeypatch, malformed_first=True)
    path = run_dir / "E01.json"
    record = json.loads(path.read_text())
    record["runtime"] = {"provider": "codex-cli", "call_count": 1}
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        module.check(run_dir)


@pytest.mark.parametrize("failure_kind", ["exit", "timeout"])
def test_proven_runtime_failure_can_still_produce_nineteen_of_twenty(features, tmp_path, monkeypatch, failure_kind):
    module = evaluator()
    summary, attempted = create_offline_run(module, features, tmp_path / "run", monkeypatch,
                                           failure_kind=failure_kind)
    assert len(attempted) == 20
    assert summary["attempted"] == 20
    assert summary["valid"] == 19
    assert summary["accepted"] is True


@pytest.mark.parametrize("failure_kind", ["http429", "http500", "network", "json"])
def test_real_api_failure_capture_replays_as_one_failed_attempt(features, tmp_path, monkeypatch, failure_kind):
    from artagent.arp import runtime
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    def urlopen(*args, **kwargs):
        if failure_kind.startswith("http"):
            raise urllib.error.HTTPError("https://example.invalid/v1", int(failure_kind[4:]), "failure", {}, None)
        if failure_kind == "network":
            raise urllib.error.URLError("offline")
        return io.BytesIO(b"not JSON")
    monkeypatch.setattr(runtime.urllib.request, "urlopen", urlopen)
    with pytest.raises(runtime.RuntimeFailure) as exc:
        runtime.generate("fixture prompt")
    module = evaluator()
    summary, attempted = create_offline_run(module, features, tmp_path / "run", monkeypatch,
                                           captured_failure=exc.value)
    assert len(attempted) == 20
    assert summary["valid"] == 19
    assert summary["accepted"] is True
