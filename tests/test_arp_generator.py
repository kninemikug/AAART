"""T19 profile constraints and generation, independent of live model access."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from artagent.arp.generator import (
    generate_profile,
    parse_profile,
    serialize_profile,
    validate_profile,
    main,
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


@pytest.mark.parametrize("value", [-12.001, 12.001, True, "1.0", float("nan"), float("inf"), 10**400])
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


@pytest.mark.parametrize("groups", [
    {"White Balance": {"Enabled": True, "Setting": "Camera"}},
    {"White Balance": {"Enabled": True, "Setting": "CustomTemp", "Temperature": 1500, "Green": 0.02}},
    {"White Balance": {"Enabled": True, "Setting": "CustomTemp", "Temperature": 60000, "Green": 10}},
    {"Saturation": {"Enabled": True, "Saturation": -100, "Vibrance": 100}},
])
def test_wb_and_saturation_round_trip(groups):
    profile = {"ppversion": 1045, "groups": groups}
    assert parse_profile(serialize_profile(profile)) == profile


@pytest.mark.parametrize("values", [
    {"Setting": "Custom"}, {"Setting": "Auto"},
    {"Setting": "CustomTemp", "Temperature": 5500},
    {"Setting": "CustomTemp", "Temperature": 5500.0, "Green": 1},
    {"Setting": "CustomTemp", "Temperature": 1499, "Green": 1},
    {"Setting": "CustomTemp", "Temperature": 60001, "Green": 1},
    {"Setting": "CustomTemp", "Temperature": 5500, "Green": 0.019},
    {"Setting": "CustomTemp", "Temperature": 5500, "Green": 10.001},
    {"Setting": "Camera", "Temperature": 5500, "Green": 1},
    {"Setting": "Camera", "Multipliers": [1, 1, 1]},
])
def test_wb_coupling_and_ranges(values):
    with pytest.raises(ValueError):
        validate_profile({"ppversion": 1045,
                          "groups": {"White Balance": {"Enabled": True, **values}}})


@pytest.mark.parametrize("values", [{}, {"Saturation": 101}, {"Vibrance": -101},
                                   {"Saturation": True}, {"Vibrance": 5.0}])
def test_invalid_saturation(values):
    with pytest.raises(ValueError):
        validate_profile({"ppversion": 1045,
                          "groups": {"Saturation": {"Enabled": True, **values}}})


@pytest.mark.parametrize("query,groups", [
    ("화이트밸런스 5500K, Green=1.1", {"White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1.1}}),
    ("촬영 WB 유지", {"White Balance": {"Setting": "Camera"}}),
    ("채도를 줄여줘", {"Saturation": {"Saturation": -15}}),
    ("생동감을 올려줘", {"Saturation": {"Vibrance": 10}}),
    ("밝게 하고 채도를 줄여줘", {"Exposure": {"Compensation": 0.3}, "Saturation": {"Saturation": -10}}),
    ("노출을 높여줘. WB 5500K", {"Exposure": {"Compensation": 0.3}, "White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1}}),
    ("채도를 올려줘. WB 5500K", {"Saturation": {"Saturation": 5}, "White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1}}),
    ("채도를 줄여줘. 촬영 WB 유지", {"Saturation": {"Saturation": -5}, "White Balance": {"Setting": "Camera"}}),
])
def test_selected_tools_generate(features, query, groups):
    result = generate_profile(query, features, runtime=runtime_reply(groups))
    assert result["status"] == "ok", result
    assert set(result["profile"]["groups"]) == set(groups)


@pytest.mark.parametrize("query,status", [
    ("노란 기를 줄여줘", "needs_input"),
    ("색온도 5500K 또는 6500K", "needs_input"),
    ("색온도를 2000K 낮춰줘", "needs_input"),
    ("WB 5500K 기준에서 조금 더 따뜻하게 해줘", "needs_input"),
    ("색온도 1000K 줄여줘", "needs_input"),
    ("밝게 하고 채도는 올리지 마", "needs_input"),
    ("크롭해줘", "unsupported_request"),
    ("밝게 하고 노이즈 제거", "unsupported_request"),
    ("", "validation_error"),
])
def test_unsupported_or_missing_reference_prevents_inference(features, query, status):
    def forbidden(prompt):
        pytest.fail("invalid requests must fail before inference")
    result = generate_profile(query, features, runtime=forbidden)
    assert result["status"] == status
    assert "arp" not in result


@pytest.mark.parametrize("groups", [
    {"Exposure": {"Compensation": 0.3}, "White Balance": {"Setting": "Camera"}},
    {"Saturation": {"Saturation": 5}}, {},
    {"Exposure": {"Enabled": True, "Compensation": 0.3}},
])
def test_unrequested_or_missing_tools_fail(features, groups):
    result = generate_profile("밝게 해줘", features, runtime=runtime_reply(groups))
    assert result["status"] == "validation_error"
    assert "arp" not in result


@pytest.mark.parametrize("values", [
    {"Setting": "CustomTemp", "Temperature": 6500, "Green": 1.1},
    {"Setting": "Camera"},
    {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1.2},
])
def test_wb_cannot_ignore_explicit_reference(features, values):
    result = generate_profile("WB 5500K Green=1.1", features,
                              runtime=runtime_reply({"White Balance": values}))
    assert result["status"] == "validation_error"


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(schema_version=True),
    lambda f: f["source"].update(sha256="invalid"),
    lambda f: f["analysis"].update(color_space="srgb"),
    lambda f: f["histogram"]["channels"]["r"].update(counts=[4]),
    lambda f: f["signals"].update(is_dark="false"),
    lambda f: f["histogram"]["luminance"].update(mean=float("nan")),
    lambda f: f["exif"].update(iso=True),
    lambda f: f["exif"].update(iso="not-an-iso"),
    lambda f: f["exif"].update(shutter_seconds=-10),
    lambda f: f["exif"].update(camera=[]),
    lambda f: f["exif"].update(white_balance="bad"),
    lambda f: f["histogram"].update(bin_edges=[False] + [i / 16 for i in range(1, 16)] + [True]),
])
def test_invalid_features_prevent_runtime(features, mutate):
    mutate(features)
    def forbidden(prompt):
        pytest.fail("invalid features must fail before inference")
    assert generate_profile("밝게", features, runtime=forbidden)["status"] == "validation_error"


def test_nullable_signals_are_preserved(features):
    features["signals"].update(is_dark=None, yellow_tendency=None,
                               deferred_reasons=["unity_wb_deferred"])
    features["analysis"]["wb_applied"] = "unity"
    features["warnings"] = ["wb_coefficients_missing"]
    original = copy.deepcopy(features)
    result = generate_profile("밝게", features,
                              runtime=runtime_reply({"Exposure": {"Compensation": 0.2}}))
    assert result["status"] == "ok"
    assert result["warnings"] == ["wb_coefficients_missing"]
    assert features == original


@pytest.mark.parametrize("raw", ["not JSON", "```json\n{}\n```", '{"groups":{},"groups":{}}',
                                 '{"groups":{"Exposure":{"Compensation":NaN}},"reason":"x"}'])
def test_invalid_runtime_json_does_not_generate(features, raw):
    result = generate_profile("밝게", features,
                              runtime=lambda prompt: {"raw_response": raw, "metadata": {}})
    assert result["status"] == "runtime_error"
    assert result["raw_response"] == raw
    assert "arp" not in result


def test_cli_writes_valid_profile_without_overwriting_source(features, tmp_path, monkeypatch, capsys):
    from artagent.arp import runtime
    monkeypatch.setattr(runtime, "generate", runtime_reply({"Exposure": {"Compensation": 0.4}}))
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps(features))
    output = tmp_path / "generated.arp"
    arguments = ["--request", "밝게", "--features", str(feature_path), "--output", str(output)]
    assert main(arguments) == 0
    assert parse_profile(output.read_text()) == exposure(0.4)
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    before = output.read_bytes()
    assert main(arguments) != 0
    assert output.read_bytes() == before


@pytest.mark.parametrize("suffix", [".nef", ".nef.arp", ".arp"])
def test_cli_preserves_raw_and_sidecars(features, tmp_path, monkeypatch, suffix):
    from artagent.arp import runtime
    source = tmp_path / "source.nef"
    source.write_bytes(b"raw")
    features["source"]["path"] = str(source)
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps(features))
    monkeypatch.setattr(runtime, "generate", runtime_reply({"Exposure": {"Compensation": 0.4}}))
    output = tmp_path / ("source" + suffix)
    assert main(["--request", "밝게", "--features", str(feature_path), "--output", str(output)]) != 0
    assert source.read_bytes() == b"raw"
    if output != source:
        assert not output.exists()


def test_schema_keys_match_documentation():
    schema = json.loads((Path(__file__).resolve().parents[1] / "src/artagent/arp/schema.json").read_text())
    documentation = (Path(__file__).resolve().parents[1] / "docs/arp_schema.md").read_text()
    for group, definition in schema["properties"]["groups"]["properties"].items():
        section = documentation.split(f"## [{group}]\n", 1)[1].split("\n## ", 1)[0]
        for key in definition["properties"]:
            assert f"- `{key}`" in section


def test_negated_adjustment_is_not_requested(features):
    query = "밝게 해줘. 채도는 바꾸지 마"
    result = generate_profile(query, features,
                              runtime=runtime_reply({"Exposure": {"Compensation": 0.3}}))
    assert result["status"] == "ok", result
    changed = generate_profile(query, features, runtime=runtime_reply({
        "Exposure": {"Compensation": 0.3}, "Saturation": {"Saturation": 70}}))
    assert changed["status"] == "validation_error"


@pytest.mark.parametrize("query", [
    "채도 변경 없이 밝게 해줘", "채도 변화 없이 밝게 해줘",
    "brighten without changing saturation", "brighten; keep saturation unchanged",
    "brighten; don't change saturation",
    "채도는 바꾸지 말고 밝게 해줘",
])
def test_preservation_clauses_never_authorize_saturation(features, query):
    good = generate_profile(query, features,
                            runtime=runtime_reply({"Exposure": {"Compensation": 0.5}}))
    assert good["status"] == "ok", good
    bad = generate_profile(query, features, runtime=runtime_reply({
        "Exposure": {"Compensation": 0.5}, "Saturation": {"Saturation": 50}}))
    assert bad["status"] == "validation_error"


@pytest.mark.parametrize("query", [
    "WB를 2000K, 낮춰줘", "WB를 2000K; 낮춰줘", "WB를 2000K. 낮춰줘",
    "WB 5500K, 조금 더 따뜻하게 해줘", "현재 WB 5500K. 밝게 하고 더 따뜻하게 해줘",
])
def test_relative_wb_cannot_hide_behind_punctuation(features, query):
    def forbidden(prompt):
        pytest.fail("a relative WB request needs a target before inference")
    result = generate_profile(query, features, runtime=forbidden)
    assert result["status"] == "needs_input"


@pytest.mark.parametrize("query", [
    "밝게 해주고 회전해줘", "밝게 해주고 비네팅을 제거해줘",
    "brighten and rotate", "밝게 해주고 크기를 변경해줘",
])
def test_mixed_unsupported_edits_do_not_partially_succeed(features, query):
    def forbidden(prompt):
        pytest.fail("all requested tools must be supported before inference")
    result = generate_profile(query, features, runtime=forbidden)
    assert result["status"] == "unsupported_request"


@pytest.mark.parametrize("text,value", [(".8", 0.8), ("1e-1", 0.1), ("+8e-1", 0.8)])
def test_green_number_is_parsed_as_a_complete_token(features, text, value):
    result = generate_profile(f"WB 5500K Green={text}", features, runtime=runtime_reply({
        "White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": value}}))
    assert result["status"] == "ok", result
    assert result["contract"]["wb_reference"]["Green"] == value


@pytest.mark.parametrize("text", ["1e", "1e-", "1.2.3", "oops", "1,1"])
def test_malformed_explicit_green_is_not_defaulted(features, text):
    def forbidden(prompt):
        pytest.fail("malformed Green must fail before inference")
    result = generate_profile(f"WB 5500K Green={text}", features, runtime=forbidden)
    assert result["status"] == "validation_error"


@pytest.mark.parametrize("query", ["WB 5500K, 채도를 줄여줘", "WB 5500K. 노출을 높여줘"])
def test_other_tool_directions_do_not_turn_absolute_wb_into_a_delta(features, query):
    groups = {"White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1.0}}
    if "채도" in query:
        groups["Saturation"] = {"Saturation": -5}
    else:
        groups["Exposure"] = {"Compensation": 0.3}
    assert generate_profile(query, features, runtime=runtime_reply(groups))["status"] == "ok"


@pytest.mark.parametrize("query,good,bad", [
    ("brighten without changing saturation or vibrance", {"Exposure": {"Compensation": 0.5}},
     {"Exposure": {"Compensation": 0.5}, "Saturation": {"Vibrance": 50}}),
    ("brighten without changing saturation, or the vibrance", {"Exposure": {"Compensation": 0.5}},
     {"Exposure": {"Compensation": 0.5}, "Saturation": {"Vibrance": 50}}),
    ("밝게, 채도와 생동감은 유지해줘", {"Exposure": {"Compensation": 0.5}},
     {"Exposure": {"Compensation": 0.5}, "Saturation": {"Saturation": 50}}),
    ("don't change exposure or saturation; WB 5500K",
     {"White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1}},
     {"White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1},
      "Saturation": {"Saturation": 50}}),
])
def test_coordinated_preservation_applies_to_every_named_tool(features, query, good, bad):
    assert generate_profile(query, features, runtime=runtime_reply(good))["status"] == "ok"
    assert generate_profile(query, features, runtime=runtime_reply(bad))["status"] == "validation_error"


@pytest.mark.parametrize("query,groups", [
    ("노출을 0 EV로 되돌려줘", {"Exposure": {"Compensation": 0}}),
    ("채도를 0으로 되돌려줘", {"Saturation": {"Saturation": 0}}),
    ("WB 5500K Green=1.1.", {"White Balance": {"Setting": "CustomTemp", "Temperature": 5500, "Green": 1.1}}),
])
def test_valid_reset_and_sentence_punctuation_remain_supported(features, query, groups):
    assert generate_profile(query, features, runtime=runtime_reply(groups))["status"] == "ok"
