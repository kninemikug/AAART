"""Tests for Task 18 photo feature extraction (artagent.features)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
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

    # Histogram verification
    hist = res["histogram"]
    assert hist["bin_count"] == 16
    assert len(hist["bin_edges"]) == 17

    # Measured statistics (compared to reference within tight tolerances)
    assert pytest.approx(hist["luminance"]["mean"], abs=1e-5) == 0.123835
    assert pytest.approx(hist["luminance"]["shadow_fraction"], abs=1e-5) == 0.371906
    assert pytest.approx(hist["saturation"]["mean"], abs=1e-5) == 0.455694

    r_ch = hist["channels"]["r"]
    g_ch = hist["channels"]["g"]
    b_ch = hist["channels"]["b"]

    assert pytest.approx(r_ch["mean"], abs=1e-5) == 0.144494
    assert pytest.approx(g_ch["mean"], abs=1e-5) == 0.116639
    assert pytest.approx(b_ch["mean"], abs=1e-5) == 0.134283

    # Counts sum must equal total pixels exactly
    total_pixels = 3039 * 2014
    assert sum(r_ch["counts"]) == total_pixels
    assert sum(g_ch["counts"]) == total_pixels
    assert sum(b_ch["counts"]) == total_pixels

    # Probabilities sum must equal 1.0 (within rounded precision)
    assert pytest.approx(sum(r_ch["probabilities"]), abs=1e-4) == 1.0
    assert pytest.approx(sum(g_ch["probabilities"]), abs=1e-4) == 1.0
    assert pytest.approx(sum(b_ch["probabilities"]), abs=1e-4) == 1.0

    # Signals verification
    signals = res["signals"]
    assert signals["rules_version"] == "t18-thresholds-v1"
    assert signals["is_dark"] is True
    assert signals["yellow_tendency"] is False
    assert pytest.approx(signals["yellow_excess"], abs=1e-5) == -0.009399
    assert pytest.approx(signals["red_green_imbalance"], abs=1e-5) == 0.070445
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


def test_histogram_bins_and_counts() -> None:
    """Verify boundary assignment in 16 bins: [0, 1/16, ..., 1]."""
    bin_edges = [i / 16.0 for i in range(17)]
    # Create test pixels placed exactly on bin edges and interiors
    vals = [0.0, 0.0625, 0.125, 0.5, 0.9375, 1.0]
    arr = np.zeros((len(vals), 1, 3), dtype=np.float64)
    for i, v in enumerate(vals):
        arr[i, 0, :] = v

    summary = summarize_rgb(arr)
    r_counts = summary["channels"]["r"]["counts"]
    assert len(r_counts) == 16
    assert sum(r_counts) == len(vals)
    # 0.0 should be in bin 0
    assert r_counts[0] >= 1
    # 1.0 should be included in the last bin 15
    assert r_counts[15] >= 1


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
