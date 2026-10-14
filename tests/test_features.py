"""Tests for Task 18 photo feature extraction (artagent.features)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

# Ensure src/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from artagent.features import dumps_features, extract_features
from artagent.features.exif import _parse_shutter_seconds, normalize_exif, read_exif
from artagent.features.histogram import (
    _parse_ppm_p6,
    decode_raw_rgb,
    derive_signals,
    summarize_rgb,
)

SAMPLE_PATH = Path("data/fivek_sample/sample1.nef")
SAMPLE_SHA256 = "18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805"
SAMPLE_FILE_SIZE = 5533313
# Independently checked on the fixed 16-bit PPM using integer bin indices.
SAMPLE_PPM_SHA256 = "d6c0d4098988e60104c90d3b737b5ad0172c941c816ccbde858605f0c1bba176"
SAMPLE_CHANNEL_SUMS = {"r": 57958062951, "g": 46785065609, "b": 53862449764}
SAMPLE_CHANNEL_COUNTS = {
    "r": [2463241, 1289356, 750743, 405109, 342818, 286850, 196790, 122833,
          85361, 57166, 39223, 22284, 12541, 9952, 10619, 25660],
    "g": [2889965, 1503300, 692549, 336784, 203968, 122749, 89872, 73899,
          48685, 33365, 23468, 17790, 11640, 9672, 7414, 55426],
    "b": [2962316, 1250364, 627418, 381230, 241200, 151582, 112061, 67341,
          47091, 39915, 36137, 32897, 27551, 23243, 18785, 101415],
}


def test_sample_identity() -> None:
    """Verify sample1.nef existence, exact byte size, and fixed SHA-256 hash."""
    assert SAMPLE_PATH.is_file(), f"Fixed sample RAW must exist at {SAMPLE_PATH}"
    assert not SAMPLE_PATH.name.endswith(".dng"), "DUMMY dng must not be used as input"

    with open(SAMPLE_PATH, "rb") as f:
        data = f.read()

    assert len(data) == SAMPLE_FILE_SIZE, f"Expected size {SAMPLE_FILE_SIZE}, got {len(data)}"
    file_hash = hashlib.sha256(data).hexdigest()
    assert file_hash == SAMPLE_SHA256, f"Hash mismatch: expected {SAMPLE_SHA256}, got {file_hash}"


def test_sample_exif_reference() -> None:
    """Verify exact reference EXIF normalization on sample1.nef."""
    raw_tags = read_exif(SAMPLE_PATH)
    exif = normalize_exif(raw_tags)

    # 1. ISO
    assert exif["iso"] == 200
    assert exif["source_tags"]["iso"] == "Exif.Nikon3.ISOSpeed"

    # 2. Shutter seconds
    assert exif["shutter_seconds"] == 0.005  # 1/200 s
    assert exif["source_tags"]["shutter_seconds"] == "Exif.Photo.ExposureTime"

    # 3. Camera Make / Model
    assert exif["camera"]["make"] == "NIKON CORPORATION"
    assert exif["camera"]["model"] == "NIKON D70"
    assert exif["source_tags"]["camera.make"] == "Exif.Image.Make"
    assert exif["source_tags"]["camera.model"] == "Exif.Image.Model"

    # 4. White Balance
    wb = exif["white_balance"]
    assert wb["mode"] == "auto"
    assert wb["preset"] == "AUTO"
    assert wb["temperature_kelvin"] is None
    assert exif["source_tags"]["white_balance.mode"] == "Exif.Photo.WhiteBalance"
    assert exif["source_tags"]["white_balance.preset"] == "Exif.Nikon3.WhiteBalance"
    assert exif["source_tags"]["white_balance.temperature_kelvin"] is None

    # Multipliers normalized to g1 = 1.0 (507 / 256, 1.0, 428 / 256, 1.0)
    mults = wb["camera_multipliers"]
    assert mults is not None
    assert pytest.approx(mults["r"], abs=1e-7) == 507.0 / 256.0
    assert mults["g1"] == 1.0
    assert pytest.approx(mults["b"], abs=1e-7) == 428.0 / 256.0
    assert mults["g2"] == 1.0
    assert exif["source_tags"]["white_balance.camera_multipliers"] == "Exif.NikonCb3.WB_RGBGLevels"


def test_sample_histogram_reference() -> None:
    """Verify measured RGB statistics, histogram distribution, and signals on sample1.nef."""
    res = extract_features(SAMPLE_PATH)

    # Analysis verification
    analysis = res["analysis"]
    assert analysis["pipeline_version"] == "t18-linear-rgb-v1"
    assert analysis["color_space"] == "linear_srgb"
    assert analysis["bit_depth"] == 16
    assert analysis["wb_applied"] == "camera"
    assert analysis["width"] == 3039
    assert analysis["height"] == 2014
    assert analysis["pixel_count"] == 3039 * 2014
    assert analysis["threads"] == 1
    assert analysis["metadata_tool"] == {"name": "exiv2", "version": "0.28.8"}
    assert analysis["decoder"]["version"] == "0.22.2"
    assert analysis["numpy_version"] == "2.5.3"
    assert analysis["ppm_sha256"] == SAMPLE_PPM_SHA256

    # Histogram verification
    hist = res["histogram"]
    assert hist["bin_count"] == 16
    assert len(hist["bin_edges"]) == 17

    # Measured statistics (compared to reference within tight tolerances)
    assert hist["luminance"]["mean"] == pytest.approx(0.12383494352000035, abs=1e-12, rel=0)
    assert hist["luminance"]["shadow_fraction"] == pytest.approx(0.37190587244994155, abs=1e-12, rel=0)
    assert hist["saturation"]["mean"] == pytest.approx(0.45569380057466047, abs=1e-12, rel=0)

    r_ch = hist["channels"]["r"]
    g_ch = hist["channels"]["g"]
    b_ch = hist["channels"]["b"]

    for channel in ("r", "g", "b"):
        # Sum uint16 pixels exactly, then normalize once; avoid accumulating
        # millions of already-normalized floats in the independent reference.
        expected_mean = SAMPLE_CHANNEL_SUMS[channel] / (3039 * 2014 * 65535)
        assert hist["channels"][channel]["mean"] == pytest.approx(
            expected_mean, abs=1e-12, rel=0
        )

    # Counts sum must equal total pixels exactly
    total_pixels = 3039 * 2014
    assert sum(r_ch["counts"]) == total_pixels
    assert sum(g_ch["counts"]) == total_pixels
    assert sum(b_ch["counts"]) == total_pixels

    for channel in ("r", "g", "b"):
        stats = hist["channels"][channel]
        expected_counts = SAMPLE_CHANNEL_COUNTS[channel]
        assert stats["counts"] == expected_counts
        assert stats["probabilities"] == pytest.approx(
            [count / total_pixels for count in expected_counts], abs=1e-12, rel=0
        )
        assert sum(stats["probabilities"]) == pytest.approx(1, abs=1e-12, rel=0)

    # Signals verification
    signals = res["signals"]
    assert signals["rules_version"] == "t18-thresholds-v1"
    assert signals["is_dark"] is True
    assert signals["yellow_tendency"] is False
    assert signals["yellow_excess"] == pytest.approx(-0.009399956166449671, abs=1e-12, rel=0)
    assert signals["red_green_imbalance"] == pytest.approx(0.07044517261035904, abs=1e-12, rel=0)
    assert signals["deferred_reasons"] == []


def test_rgb_known_values() -> None:
    """Verify luminance, saturation, and yellow excess on controlled small arrays."""
    # 1. Pure black (0, 0, 0)
    black = np.zeros((2, 2, 3), dtype=np.float64)
    black_summary = summarize_rgb(black)
    assert black_summary["luminance"]["mean"] == 0.0
    assert black_summary["luminance"]["shadow_fraction"] == 1.0
    assert black_summary["saturation"]["mean"] == 0.0
    black_signals = derive_signals(black_summary, {"wb_applied": "camera"})
    assert black_signals["yellow_excess"] is None
    assert black_signals["is_dark"] is True
    assert black_signals["yellow_tendency"] is None  # deferred due to low luminance
    assert "low_luminance_deferred" in black_signals["deferred_reasons"]

    # 2. Pure white (1, 1, 1)
    white = np.ones((2, 2, 3), dtype=np.float64)
    white_summary = summarize_rgb(white)
    assert white_summary["luminance"]["mean"] == 1.0
    assert white_summary["luminance"]["shadow_fraction"] == 0.0
    assert white_summary["saturation"]["mean"] == 0.0
    white_signals = derive_signals(white_summary, {"wb_applied": "camera"})
    assert white_signals["yellow_excess"] == 0.0
    assert white_signals["red_green_imbalance"] == 0.0
    assert white_signals["is_dark"] is False
    assert white_signals["yellow_tendency"] is False  # saturation = 0 <= 0.10

    # 3. Pure gray (0.5, 0.5, 0.5)
    gray = np.full((2, 2, 3), 0.5, dtype=np.float64)
    gray_summary = summarize_rgb(gray)
    assert pytest.approx(gray_summary["luminance"]["mean"], abs=1e-6) == 0.5
    assert gray_summary["saturation"]["mean"] == 0.0

    # 4. Pure yellow (1.0, 1.0, 0.0)
    yellow = np.zeros((2, 2, 3), dtype=np.float64)
    yellow[:, :, 0] = 1.0
    yellow[:, :, 1] = 1.0
    yellow[:, :, 2] = 0.0
    yellow_summary = summarize_rgb(yellow)
    assert yellow_summary["saturation"]["mean"] == 1.0
    yellow_signals = derive_signals(yellow_summary, {"wb_applied": "camera"})
    # D = 2.0, yellow_excess = ((1 + 1)/2 - 0)/2 = 0.5
    assert pytest.approx(yellow_signals["yellow_excess"], abs=1e-6) == 0.5
    assert yellow_signals["red_green_imbalance"] == 0.0
    assert yellow_signals["yellow_tendency"] is True


@pytest.mark.parametrize(
    ("value", "bin_index"),
    [(0.0, 0), (1.0, 15)] + [
        (value, expected)
        for edge in range(1, 16)
        for value, expected in (
            (np.nextafter(edge / 16, 0.0), edge - 1),
            (edge / 16, edge),
            (np.nextafter(edge / 16, 1.0), edge),
        )
    ],
)
def test_histogram_bins_and_counts(value, bin_index) -> None:
    """Check both sides of every boundary, including the inclusive endpoint 1."""
    summary = summarize_rgb(np.full((1, 1, 3), value))
    expected = [0] * 16
    expected[bin_index] = 1
    assert summary["bin_edges"] == [i / 16 for i in range(17)]
    for channel in ("r", "g", "b"):
        assert summary["channels"][channel]["counts"] == expected
        assert summary["channels"][channel]["probabilities"] == expected


@pytest.mark.parametrize(("blue", "expected"), [(2085, 1.0), (2086, 0.0), (2087, 0.0)])
def test_shadow_cutoff_excludes_exact_boundary(blue, expected) -> None:
    # 2126*4232 + 7152*3113 + 722*2086 == 500*65535: exactly Y=0.05.
    rgb = np.array([[[4232, 3113, blue]]], dtype=np.float64) / 65535
    summary = summarize_rgb(rgb)
    assert summary["luminance"]["shadow_fraction"] == expected


def test_signal_thresholds() -> None:
    """Verify boundary conditions and threshold margins (margin = 0.0001)."""
    # 1. is_dark threshold test (threshold: 0.18)
    def make_dummy_hist(mean_lum: float, mean_sat: float, r: float, g: float, b: float) -> Dict[str, Any]:
        return {
            "luminance": {"mean": mean_lum, "shadow_fraction": 0.0},
            "saturation": {"mean": mean_sat},
            "channels": {
                "r": {"mean": r, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
                "g": {"mean": g, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
                "b": {"mean": b, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
            },
        }

    # Near dark boundary (0.18 ± 0.0001)
    boundary_dark = make_dummy_hist(0.18005, 0.2, 0.18, 0.18, 0.18)
    sig = derive_signals(boundary_dark, {"wb_applied": "camera"})
    assert sig["is_dark"] is None
    assert "is_dark_boundary" in sig["deferred_reasons"]

    # Clear dark (< 0.1798)
    clear_dark = make_dummy_hist(0.15, 0.2, 0.15, 0.15, 0.15)
    sig_dark = derive_signals(clear_dark, {"wb_applied": "camera"})
    assert sig_dark["is_dark"] is True

    # Clear bright (> 0.1802)
    clear_bright = make_dummy_hist(0.25, 0.2, 0.25, 0.25, 0.25)
    sig_bright = derive_signals(clear_bright, {"wb_applied": "camera"})
    assert sig_bright["is_dark"] is False

    # 2. yellow_tendency boundary test
    # target: yellow_excess > 0.08, red_green_imbalance < 0.10, sat > 0.10, lum > 0.02
    # Create near yellow_excess boundary (0.08 ± 0.00005)
    # D = R + G + B. Let R=0.15, G=0.15, B = 0.15 - delta
    # yellow_excess = (0.15 - B) / (0.30 + B)
    # If yellow_excess = 0.08005 (near 0.08):
    target_excess = 0.08005
    # (0.15 - B) = 0.08005 * (0.30 + B) => 0.15 - 0.024015 = 1.08005 * B => B = 0.125985 / 1.08005 = 0.116647
    near_yellow_hist = make_dummy_hist(0.14, 0.3, 0.15, 0.15, 0.116647)
    sig_near_y = derive_signals(near_yellow_hist, {"wb_applied": "camera"})
    assert sig_near_y["yellow_tendency"] is None
    assert "yellow_tendency_boundary" in sig_near_y["deferred_reasons"]


@pytest.mark.parametrize(
    ("luminance", "expected"),
    [(0.17989951, True), (0.17990049, None),
     (0.18009951, None), (0.18010049, False)],
)
def test_dark_signal_uses_unrounded_pixels(luminance, expected) -> None:
    rgb = np.full((1, 1, 3), luminance, dtype=np.float64)
    histogram = summarize_rgb(rgb)
    assert histogram["luminance"]["mean"] == pytest.approx(
        luminance, abs=1e-12, rel=0
    )
    signals = derive_signals(histogram, {"wb_applied": "camera"})
    assert signals["is_dark"] is expected


@pytest.mark.parametrize(
    ("yellow_excess", "expected"),
    [(0.07989951, False), (0.07990049, None),
     (0.08009951, None), (0.08010049, True)],
)
def test_yellow_signal_uses_unrounded_channel_means(yellow_excess, expected) -> None:
    blue = (0.15 - 0.30 * yellow_excess) / (1 + yellow_excess)
    rgb = np.array([[[0.15, 0.15, blue]]], dtype=np.float64)
    signals = derive_signals(summarize_rgb(rgb), {"wb_applied": "camera"})
    assert signals["yellow_excess"] == pytest.approx(
        yellow_excess, abs=1e-12, rel=0
    )
    assert signals["yellow_tendency"] is expected


def test_shutter_normalization_keeps_full_precision() -> None:
    exif = normalize_exif({"vanilla": {"Exif.Photo.ExposureTime": "1/3"}})
    assert exif["shutter_seconds"] == pytest.approx(1 / 3, abs=1e-12, rel=0)


def test_json_rounding_preserves_internal_values_and_decisions() -> None:
    features = {
        "histogram": summarize_rgb(np.full((1, 1, 3), 0.17989951)),
        "exif": {"shutter_seconds": 1 / 3, "multipliers": [507 / 256]},
        "signals": {"is_dark": True, "yellow_tendency": None},
    }
    original = copy.deepcopy(features)
    serialized = dumps_features(features)
    loaded = json.loads(serialized)
    assert loaded["histogram"]["luminance"]["mean"] == 0.1799
    assert loaded["exif"]["shutter_seconds"] == 0.333333
    assert loaded["exif"]["multipliers"] == [1.980469]
    assert loaded["signals"] == features["signals"]
    assert features == original
    assert serialized.endswith("\n")
    assert serialized == dumps_features(dict(reversed(list(features.items()))))


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_json_rejects_non_finite_values(invalid) -> None:
    with pytest.raises(ValueError, match="Non-finite"):
        dumps_features({"nested": [{"value": invalid}]})


def test_missing_or_invalid_exif() -> None:
    """Verify handling of missing/invalid EXIF fields without inventing values."""
    # Shutter with division by zero
    sec, err = _parse_shutter_seconds("10/0")
    assert sec is None
    assert err == "shutter_division_by_zero"

    # Shutter with negative / invalid format
    sec, err = _parse_shutter_seconds("-1/200")
    assert sec is None
    assert err == "shutter_non_positive"

    sec, err = _parse_shutter_seconds("not_a_number")
    assert sec is None
    assert err == "shutter_format_invalid"

    # Normalize with empty tags
    empty_exif = normalize_exif({})
    assert empty_exif["iso"] is None
    assert empty_exif["shutter_seconds"] is None
    assert empty_exif["camera"]["make"] is None
    assert empty_exif["camera"]["model"] is None
    assert empty_exif["white_balance"]["mode"] is None
    assert empty_exif["white_balance"]["preset"] is None
    assert empty_exif["white_balance"]["temperature_kelvin"] is None
    assert empty_exif["white_balance"]["camera_multipliers"] is None
    assert "iso_missing" in empty_exif["_warnings"]
    assert "shutter_missing" in empty_exif["_warnings"]
    assert "wb_coefficients_missing" in empty_exif["_warnings"]


def test_wb_fallback_defers_yellow() -> None:
    """Verify unity WB fallback applies and defers yellow tendency with warning."""
    # When WB multipliers are missing
    exif_no_wb: Dict[str, Any] = {
        "white_balance": {"camera_multipliers": None},
    }
    # Pass mock or synthetic histogram
    hist = {
        "luminance": {"mean": 0.10, "shadow_fraction": 0.1},
        "saturation": {"mean": 0.50},
        "channels": {
            "r": {"mean": 0.20, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
            "g": {"mean": 0.20, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
            "b": {"mean": 0.05, "counts": [1] * 16, "probabilities": [1 / 16] * 16},
        },
    }
    signals = derive_signals(hist, {"wb_applied": "unity"})
    assert signals["yellow_tendency"] is None
    assert "unity_wb_deferred" in signals["deferred_reasons"]


def test_invalid_pixels_and_raw() -> None:
    """Verify explicit exceptions for corrupt/invalid pixel buffers and PPM headers."""
    # Empty array
    with pytest.raises(ValueError, match="empty"):
        summarize_rgb(np.array([], dtype=np.float64))

    # Invalid dimension
    with pytest.raises(ValueError, match="Expected array of shape"):
        summarize_rgb(np.zeros((10, 10), dtype=np.float64))

    # Array containing NaN
    nan_arr = np.zeros((2, 2, 3), dtype=np.float64)
    nan_arr[0, 0, 0] = float("nan")
    with pytest.raises(ValueError, match="NaN or Inf"):
        summarize_rgb(nan_arr)

    # Array containing values > 1.0
    out_of_bounds = np.ones((2, 2, 3), dtype=np.float64) * 1.5
    with pytest.raises(ValueError, match="outside"):
        summarize_rgb(out_of_bounds)

    # Corrupt PPM header
    with pytest.raises(ValueError, match="magic number"):
        _parse_ppm_p6(b"P5\n10 10\n65535\n" + b"\x00" * 200)

    # Truncated PPM payload
    with pytest.raises(ValueError, match="Truncated PPM payload"):
        _parse_ppm_p6(b"P6\n10 10\n65535\n" + b"\x00" * 10)


def test_tool_failures() -> None:
    """Verify tool failure states do not produce successful output."""
    # Non-existent file
    with pytest.raises(FileNotFoundError):
        extract_features(Path("non_existent_file.nef"))

    # Missing dcraw_emu tool
    with patch("subprocess.run", side_effect=FileNotFoundError("dcraw_emu not found")):
        with pytest.raises(RuntimeError):
            decode_raw_rgb(SAMPLE_PATH, {})


def test_exif_records_actual_tool_version(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "exiv2"
    executable.write_bytes(b"selected metadata executable")
    monkeypatch.setattr(shutil, "which", lambda name: str(executable))
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["LC_ALL"] == "C"
        assert kwargs["env"]["LANG"] == "C"
        stdout = "exiv2 9.8.7\n" if command[-1] == "--version" else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    tags = read_exif(SAMPLE_PATH)
    assert tags["metadata_tool"] == {"name": "exiv2", "version": "9.8.7"}
    assert all(command[0] == str(executable) for command in calls)
    assert [str(executable), "--version"] in calls


@pytest.mark.parametrize("package_version", ["9.8.7", None])
def test_decoder_records_binary_and_enforces_threads(
    monkeypatch, tmp_path, package_version
) -> None:
    prefix = tmp_path / "selected-installation"
    executable = prefix / "bin" / "dcraw_emu"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"selected decoder executable")
    if package_version:
        metadata = prefix / "lib" / "pkgconfig" / "libraw.pc"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(f"Name: libraw\nVersion: {package_version}\n")
    monkeypatch.setattr(shutil, "which", lambda name: str(executable))
    inherited = {
        "OMP_NUM_THREADS": "16", "OMP_THREAD_LIMIT": "32",
        "OMP_DYNAMIC": "TRUE", "LC_ALL": "ko_KR.UTF-8",
    }
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    child_environment = {}

    def run(command, **kwargs):
        assert command[0] == str(executable)
        child_environment.update(kwargs["env"])
        ppm = b"P6\n1 1\n65535\n" + b"\x00\x00" * 3
        return subprocess.CompletedProcess(command, 0, stdout=ppm, stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    _, analysis = decode_raw_rgb(SAMPLE_PATH, {})
    assert analysis["threads"] == 1
    assert child_environment["OMP_NUM_THREADS"] == "1"
    assert child_environment["OMP_THREAD_LIMIT"] == "1"
    assert child_environment["OMP_DYNAMIC"] == "FALSE"
    assert child_environment["LC_ALL"] == child_environment["LANG"] == "C"
    for key, value in inherited.items():
        assert os.environ[key] == value
    decoder = analysis["decoder"]
    assert decoder["version"] == package_version
    assert decoder["version_source"] == ("libraw.pc" if package_version else None)
    assert decoder["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()


def test_repeatable_json() -> None:
    """Verify 3 consecutive runs produce byte-identical JSON and validate schema."""
    runs = [dumps_features(extract_features(SAMPLE_PATH)) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2], "JSON output must be byte-identical across runs"

    data = json.loads(runs[0])
    assert data["schema_version"] == 1
    assert data["source"]["path"] == "data/fivek_sample/sample1.nef"
    assert data["source"]["sha256"] == SAMPLE_SHA256
    assert isinstance(data["warnings"], list)


def test_source_unchanged(tmp_path: Path) -> None:
    """Verify RAW file hash is unchanged and no sidecar/scratch files created in source directory."""
    with open(SAMPLE_PATH, "rb") as f:
        before_hash = hashlib.sha256(f.read()).hexdigest()

    before_dir_files = sorted(p.name for p in SAMPLE_PATH.parent.iterdir())

    # Run feature extraction
    res = extract_features(SAMPLE_PATH)
    assert res is not None

    with open(SAMPLE_PATH, "rb") as f:
        after_hash = hashlib.sha256(f.read()).hexdigest()

    after_dir_files = sorted(p.name for p in SAMPLE_PATH.parent.iterdir())

    assert before_hash == after_hash, "Source RAW file must remain unmodified"
    assert before_dir_files == after_dir_files, "No files should be added to source directory"


def test_t19_input_contract() -> None:
    """Verify JSON round-trip maintains types and completeness for Task 19 consumer."""
    features = extract_features(SAMPLE_PATH)
    json_str = dumps_features(features)
    loaded = json.loads(json_str)

    # Check top-level keys
    for key in ("schema_version", "source", "exif", "analysis", "histogram", "signals", "warnings"):
        assert key in loaded, f"Missing top-level key: {key}"

    # Verify key data contracts for T19
    assert isinstance(loaded["schema_version"], int)
    assert isinstance(loaded["signals"]["is_dark"], bool)
    assert isinstance(loaded["signals"]["yellow_tendency"], bool)
    assert isinstance(loaded["signals"]["deferred_reasons"], list)
    assert len(loaded["histogram"]["channels"]["r"]["counts"]) == 16
    assert len(loaded["histogram"]["channels"]["r"]["probabilities"]) == 16
