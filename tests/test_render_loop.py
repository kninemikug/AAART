"""Exercise T20 through T19 validation and a controlled ART-cli boundary."""

import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from artagent.arp.generator import parse_profile
from artagent.arp.runtime import RuntimeFailure
from artagent.features import derive_signals, summarize_rgb
from artagent.render import loop


REQUEST = "노출 +0.5 EV"
RETRY_MARKER = "\n렌더 재시도 진단(JSON): "


@pytest.fixture
def inputs(tmp_path):
    raw = tmp_path / "input photo.nef"
    raw.write_bytes(b"raw fixture")
    histogram = summarize_rgb(np.full((2, 2, 3), 0.1))
    analysis = {
        "pipeline_version": "t18-linear-rgb-v1", "color_space": "linear_srgb",
        "wb_applied": "camera", "pixel_count": 4,
    }
    features = {
        "schema_version": 1,
        "source": {"path": str(raw), "sha256": "a" * 64},
        "exif": {"iso": 200, "shutter_seconds": 0.005,
                 "camera": {"make": "Nikon", "model": "D70"},
                 "white_balance": {"temperature_kelvin": None, "camera_multipliers": None}},
        "analysis": analysis, "histogram": histogram,
        "signals": derive_signals(histogram, analysis), "warnings": [],
    }
    return raw, tmp_path / "output photo.jpg", features


def reply(exposure=None):
    if exposure is None:
        exposure = {"Compensation": 0.5}
    response = {"groups": {"Exposure": exposure}, "reason": "요청 노출 반영"}
    return {"raw_response": json.dumps(response), "metadata": {"provider": "fixture"}}


def stderr_feedback(prompt):
    original, payload = prompt.rsplit(RETRY_MARKER, 1)
    assert json.dumps(REQUEST, ensure_ascii=False) in original
    return json.loads(payload)


@pytest.fixture
def cli(monkeypatch, inputs):
    raw, destination, _ = inputs
    calls = []
    outcomes = []
    executable = raw.with_name("ART-cli fixture")

    def run(command, **options):
        assert command == [str(executable), "-a", "-Y", "-j92", "-o", command[5],
                           "-p", command[7], "-c", str(raw)]
        assert options["timeout"] > 0
        output, profile = Path(command[5]), Path(command[7])
        assert output != destination and not output.exists()
        assert parse_profile(profile.read_text(encoding="utf-8"))["groups"]["Exposure"] == {
            "Enabled": True, "Compensation": 0.5,
        }
        assert all(output != prior for prior, _ in calls)
        calls.append((output, profile))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        code, data, stderr = outcome
        if data is not None:
            output.write_bytes(data)
        return subprocess.CompletedProcess(command, code, "", stderr)

    monkeypatch.setattr(loop.subprocess, "run", run)
    return executable, calls, outcomes


def execute(inputs, cli, runtime):
    raw, output, features = inputs
    return loop.render_or_retry(raw, output, REQUEST, features, cli_path=cli[0], runtime=runtime)


@pytest.mark.parametrize(("defect", "reason"), [
    (lambda arp: arp + "Unknown=1\n", "Unknown key: Exposure.Unknown"),
    (lambda arp: arp.replace("Compensation=0.5", "Compensation=30"), "greater than the maximum"),
    (lambda arp: arp.replace("[Version]", "[Version"), "Invalid profile INI"),
])
def test_detects_defective_arp_and_regenerates(inputs, cli, monkeypatch, defect, reason):
    _, calls, outcomes = cli
    outcomes.append((0, b"new image", ""))
    prompts = []

    def runtime(prompt):
        prompts.append(prompt)
        return reply()

    generate_profile = loop.generate_profile

    def generate_with_defect(*args, **kwargs):
        result = generate_profile(*args, **kwargs)
        if len(prompts) == 1:
            result["arp"] = defect(result["arp"])
        return result

    monkeypatch.setattr(loop, "generate_profile", generate_with_defect)
    result = execute(inputs, cli, runtime)

    assert len(calls) == 1
    assert len(prompts) == 2 and RETRY_MARKER not in prompts[0]
    diagnostic = stderr_feedback(prompts[1])
    assert diagnostic["status"] == "invalid_profile"
    assert reason in diagnostic["detail"]
    assert diagnostic["exit_code"] is None
    assert [item.status for item in result.attempts] == ["invalid_profile", "success"]
    assert result.output_path == inputs[1]
    assert result.output_path.read_bytes() == b"new image"
    assert parse_profile(result.generation["arp"]) == result.generation["profile"]


def test_invalid_runtime_proposal_is_retried(inputs, cli):
    cli[2].append((0, b"image", ""))

    def runtime(prompt):
        if RETRY_MARKER not in prompt:
            return reply({"Compensation": 0.5, "Unknown": 1})
        assert stderr_feedback(prompt)["status"] == "validation_error"
        return reply()

    result = execute(inputs, cli, runtime)
    assert [item.status for item in result.attempts] == ["validation_error", "success"]


def test_exit_and_missing_output_feed_the_next_generation(inputs, cli):
    raw, output, _ = inputs
    output.write_bytes(b"existing image")
    _, calls, outcomes = cli
    outcomes.extend([
        (253, b"failed partial image", "noise\n" * 8 + "\n Error:   profile rejected \n"),
        (0, None, "warning: renderer skipped the image"),
        (0, b"fresh image", "Warning: optional metadata missing\n"),
    ])
    diagnostics = []

    def runtime(prompt):
        assert output.read_bytes() == b"existing image"
        if RETRY_MARKER in prompt:
            diagnostics.append(stderr_feedback(prompt))
        return reply()

    result = execute(inputs, cli, runtime)

    assert [entry.status for entry in result.attempts] == ["cli_exit", "missing_output", "success"]
    assert diagnostics[0] == {
        "attempt": 1, "status": "cli_exit", "detail": "ART-cli exited with code 253",
        "exit_code": 253, "stderr": ["Error: profile rejected", "noise", "noise", "noise", "noise"],
    }
    assert diagnostics[1]["exit_code"] == 0
    assert diagnostics[1]["stderr"] == ["warning: renderer skipped the image"]
    assert result.attempts[-1].stderr == ("Warning: optional metadata missing",)
    assert output.read_bytes() == b"fresh image"
    assert raw.read_bytes() == b"raw fixture"
    assert len(calls) == 3 and not calls[0][0].parent.exists()


def test_three_failures_report_all_reasons_and_preserve_existing_output(inputs, cli):
    output = inputs[1]
    output.write_bytes(b"existing image")
    _, calls, outcomes = cli
    outcomes.extend([
        (254, None, "Error: cannot create job"),
        (0, b"", ""),
        subprocess.TimeoutExpired("ART-cli", 120, stderr=b"Fatal: processing took too long"),
    ])
    prompts = []

    def runtime(prompt):
        prompts.append(prompt)
        return reply()

    with pytest.raises(loop.RenderLoopError) as error:
        execute(inputs, cli, runtime)

    assert len(prompts) == len(calls) == 3
    attempts = error.value.attempts
    assert [(item.attempt, item.status, item.exit_code) for item in attempts] == [
        (1, "cli_exit", 254), (2, "missing_output", 0), (3, "cli_timeout", None),
    ]
    for reason in ("cannot create job", "empty", "processing took too long"):
        assert reason in str(error.value)
    assert output.read_bytes() == b"existing image"
    assert not calls[0][0].parent.exists()


def test_cli_start_failure_stops_without_regeneration(inputs, cli):
    cli[2].append(FileNotFoundError("CLI executable unavailable"))
    with pytest.raises(loop.RenderLoopError, match="CLI executable unavailable") as error:
        execute(inputs, cli, lambda prompt: reply())
    assert [item.status for item in error.value.attempts] == ["cli_start_error"]
    assert not inputs[1].exists()


def test_runtime_infrastructure_failure_stops_without_regeneration(inputs, cli):
    def runtime(prompt):
        raise RuntimeFailure("provider unavailable", {"fatal_infrastructure": True})

    with pytest.raises(loop.RenderLoopError, match="provider unavailable") as error:
        execute(inputs, cli, runtime)
    assert [item.status for item in error.value.attempts] == ["runtime_error"]
    assert not cli[1]
