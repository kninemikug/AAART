"""T19 profile constraints and generation, independent of live model access."""

import copy
import json

import numpy as np
import pytest

from artagent.arp.generator import (
    generate_profile,
    parse_profile,
    serialize_profile,
    validate_profile,
)
from artagent.features import derive_signals, summarize_rgb


@pytest.fixture
def features():
    histogram = summarize_rgb(np.full((2, 2, 3), 0.1))
    analysis = {
        "pipeline_version": "t18-linear-rgb-v1", "color_space": "linear_srgb",
        "wb_applied": "camera", "pixel_count": 4,
    }
    return {
        "schema_version": 1,
        "source": {"path": "photo.nef", "sha256": "a" * 64},
        "exif": {"iso": 200, "shutter_seconds": 0.005,
                 "camera": {"make": "Nikon", "model": "D70"},
                 "white_balance": {"temperature_kelvin": None,
                                   "camera_multipliers": None}},
        "analysis": analysis, "histogram": histogram,
        "signals": derive_signals(histogram, analysis), "warnings": [],
    }


def runtime_reply(groups):
    def run(prompt):
        assert "사진 특성" in prompt
        return {"raw_response": json.dumps({"groups": groups, "reason": "요청 반영"}),
                "metadata": {"provider": "test", "model": "fixture"}}
    return run


def exposure(value):
    return {"ppversion": 1045,
            "groups": {"Exposure": {"Enabled": True, "Compensation": value}}}


def test_exposure_generation_round_trip(features):
    original = copy.deepcopy(features)
    result = generate_profile("조금 밝게 해줘", features,
                              runtime=runtime_reply({"Exposure": {"Compensation": 0.5}}))
    assert result["status"] == "ok"
    assert result["profile"] == exposure(0.5)
    assert parse_profile(result["arp"]) == exposure(0.5)
    assert "[Version]\nVersion=1045\n" in result["arp"]
    assert "Enabled=true" in result["arp"]
    assert features == original


@pytest.mark.parametrize("value", [-12, 12, 0.015, 0])
def test_exposure_inclusive_bounds_and_precision(value):
    profile = exposure(value)
    validate_profile(profile)
    assert parse_profile(serialize_profile(profile)) == profile


@pytest.mark.parametrize("value", [-12.001, 12.001, True, "1.0", float("nan"), float("inf")])
def test_invalid_exposure_is_rejected(value):
    with pytest.raises(ValueError):
        validate_profile(exposure(value))


def test_unknown_keys_are_not_silently_ignored():
    profile = exposure(0.5)
    profile["groups"]["Exposure"]["Auto"] = True
    with pytest.raises(ValueError):
        serialize_profile(profile)


@pytest.mark.parametrize("version", [1044, 1046, True, "1045"])
def test_profile_version_must_match_header(version):
    profile = exposure(0)
    profile["ppversion"] = version
    with pytest.raises(ValueError):
        validate_profile(profile)


@pytest.mark.parametrize("header", [None, "#define PPVERSION 1046\n", "not a header\n",
                                    "#define PPVERSION 1045\n#define PPVERSION 1045\n"])
def test_version_conflict_prevents_runtime(features, tmp_path, header):
    path = tmp_path / "ppversion.h"
    if header is not None:
        path.write_text(header)
    def forbidden(prompt):
        pytest.fail("version mismatch must fail before inference")
    result = generate_profile("明るく +0.5 EV", features, runtime=forbidden,
                              header_path=path)
    assert result["status"] == "validation_error"
    assert "arp" not in result


@pytest.mark.parametrize("text", [
    "[Version]\nVersion=1045\n[Exposure]\nEnabled=true\nCompensation=0\nCompensation=1\n",
    "[Version]\nVersion=1045\n[Exposure]\nEnabled=true\nCompensation=0\n[Exposure]\n",
    "[Version]\nVersion=1045\n[Exposure]\nEnabled=true\ncompensation=0\n",
    "[Version]\nVersion=1045\n[Exposure]\nEnabled=true\nCompensation=nan\n",
])
def test_malformed_ini_is_rejected(text):
    with pytest.raises(ValueError):
        parse_profile(text)
