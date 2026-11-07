"""Replay acceptance evidence and reject corrupt records without model calls."""

import importlib.util
import json
import os
from pathlib import Path
import shutil

import pytest

from test_arp_generator import features
from test_arp_runtime import events


ROOT = Path(__file__).resolve().parents[1]


def evaluator():
    spec = importlib.util.spec_from_file_location("t19_evaluation", ROOT / "scripts/evaluate_arp_generator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_offline_run(module, features, run_dir, monkeypatch, malformed_first=False):
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
