"""RAW image decoding to linear RGB and histogram/signal analysis."""

import math
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _parse_ppm_p6(data: bytes) -> Tuple[int, int, int, np.ndarray]:
    """Parse Netpbm P6 format PPM image bytes.

    Returns (width, height, maxval, uint16_rgb_array).
    """
    idx = 0
    tokens: List[bytes] = []
    data_len = len(data)

    while len(tokens) < 4 and idx < data_len:
        nl = data.find(b"\n", idx)
        if nl == -1:
            line = data[idx:].strip()
            idx = data_len
        else:
            line = data[idx:nl].strip()
            idx = nl + 1
        if not line or line.startswith(b"#"):
            continue
        tokens.extend(line.split())

    if len(tokens) < 4:
        raise ValueError("Invalid PPM: header incomplete or truncated")

    magic = tokens[0].decode("ascii", errors="replace")
    if magic != "P6":
        raise ValueError(f"Invalid PPM magic number: expected P6, got {magic}")

    try:
        width = int(tokens[1])
        height = int(tokens[2])
        maxval = int(tokens[3])
    except ValueError as e:
        raise ValueError(f"Invalid PPM header dimensions: {e}") from e

    if width <= 0 or height <= 0 or maxval <= 0:
        raise ValueError(f"Invalid PPM dimensions/maxval: {width}x{height}, maxval={maxval}")

    expected_bytes = width * height * 3 * 2
    raw_pixels = data[idx:]
    if len(raw_pixels) < expected_bytes:
        raise ValueError(
            f"Truncated PPM payload: expected {expected_bytes} bytes, got {len(raw_pixels)}"
        )

    # Netpbm 16-bit P6 pixel data is big-endian
    arr = np.frombuffer(raw_pixels[:expected_bytes], dtype=">u2")
    arr = arr.reshape((height, width, 3))
    return width, height, maxval, arr


def decode_raw_rgb(
    raw_path: Path | str, exif: Dict[str, Any]
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Decode RAW file to 16-bit linear sRGB using dcraw_emu and return (rgb, analysis)."""
    path = Path(raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"RAW file not found: {path}")

    wb_applied = "camera"
    multipliers = exif.get("white_balance", {}).get("camera_multipliers")

    decoder_opts = [
        "-4",
        "-o", "1",
        "-q", "3",
        "-H", "0",
        "-b", "1",
        "-c", "0",
        "-m", "0",
        "-n", "0",
        "-t", "0",
    ]

    if multipliers and all(
        k in multipliers and multipliers[k] is not None for k in ("r", "g1", "b", "g2")
    ):
        r_val = str(multipliers["r"])
        g1_val = str(multipliers["g1"])
        b_val = str(multipliers["b"])
        g2_val = str(multipliers["g2"])
        decoder_opts.extend(["-r", r_val, g1_val, b_val, g2_val])
    else:
        decoder_opts.extend(["-r", "1", "1", "1", "1"])
        wb_applied = "unity"

    cmd = ["dcraw_emu"] + decoder_opts + ["-Z", "-", str(path)]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30.0,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
        raise RuntimeError(f"dcraw_emu execution failed (code {e.returncode}): {stderr_msg}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("dcraw_emu execution timed out") from e
    except FileNotFoundError as e:
        raise RuntimeError("dcraw_emu executable not found in PATH") from e

    width, height, maxval, uint16_arr = _parse_ppm_p6(proc.stdout)

    rgb = uint16_arr.astype(np.float64) / float(maxval)

    if rgb.size == 0:
        raise ValueError("Decoded image array is empty")
    if not np.all(np.isfinite(rgb)):
        raise ValueError("Decoded image array contains NaN or Inf")
    if (rgb < 0.0).any() or (rgb > 1.0000001).any():
        raise ValueError("Decoded image array contains out-of-range values")

    rgb = np.clip(rgb, 0.0, 1.0)

    analysis: Dict[str, Any] = {
        "pipeline_version": "t18-linear-rgb-v1",
        "metadata_tool": {"name": "exiv2", "version": "0.28.8"},
        "decoder": {"name": "dcraw_emu", "version": "0.22.2"},
        "numpy_version": np.__version__,
        "color_space": "linear_srgb",
        "bit_depth": 16,
        "wb_applied": wb_applied,
        "width": width,
        "height": height,
        "pixel_count": width * height,
        "decoder_options": decoder_opts + ["-Z", "-"],
        "threads": 1,
    }

    return rgb, analysis


def summarize_rgb(rgb: np.ndarray) -> Dict[str, Any]:
    """Calculate mean luminance, saturation, and 16-bin channel distributions."""
    if not isinstance(rgb, np.ndarray):
        raise TypeError("Input must be a numpy ndarray")
    if rgb.size == 0:
        raise ValueError("Input image array is empty")
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"Expected array of shape (H, W, 3), got shape {rgb.shape}")
    if not np.all(np.isfinite(rgb)):
        raise ValueError("Input array contains NaN or Inf")
    if (rgb < 0.0).any() or (rgb > 1.0).any():
        raise ValueError("Input array contains values outside [0.0, 1.0]")

    height, width, _ = rgb.shape
    total_pixels = width * height

    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    # Linear sRGB relative luminance
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mean_luminance = float(np.mean(y))
    shadow_fraction = float(np.sum(y < 0.05) / total_pixels)

    # HSV saturation (M-m)/M
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    sat = np.divide(max_c - min_c, max_c, out=np.zeros_like(max_c), where=(max_c > 0))
    mean_saturation = float(np.mean(sat))

    bin_edges = [
        0, 0.0625, 0.125, 0.1875, 0.25, 0.3125, 0.375, 0.4375,
        0.5, 0.5625, 0.625, 0.6875, 0.75, 0.8125, 0.875, 0.9375, 1
    ]

    def _channel_stats(channel: np.ndarray) -> Dict[str, Any]:
        counts_arr, _ = np.histogram(channel, bins=16, range=(0.0, 1.0))
        counts = [int(c) for c in counts_arr]
        probs = [float(c) / total_pixels for c in counts]
        return {
            "mean": float(np.mean(channel)),
            "counts": counts,
            "probabilities": probs,
        }

    return {
        "bin_count": 16,
        "bin_edges": bin_edges,
        "luminance": {
            "mean": mean_luminance,
            "shadow_fraction": shadow_fraction,
        },
        "saturation": {
            "mean": mean_saturation,
        },
        "channels": {
            "r": _channel_stats(r),
            "g": _channel_stats(g),
            "b": _channel_stats(b),
        },
    }


def derive_signals(
    histogram: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Derive heuristic signals (is_dark, yellow_tendency) and boundary/deferral reasons."""
    r_mean = histogram["channels"]["r"]["mean"]
    g_mean = histogram["channels"]["g"]["mean"]
    b_mean = histogram["channels"]["b"]["mean"]
    d = r_mean + g_mean + b_mean

    yellow_excess: Optional[float] = None
    red_green_imbalance: Optional[float] = None
    if d > 0:
        yellow_excess = ((r_mean + g_mean) / 2.0 - b_mean) / d
        red_green_imbalance = abs(r_mean - g_mean) / d

    thresholds: Dict[str, float] = {
        "dark_mean": 0.18,
        "yellow_excess": 0.08,
        "red_green_imbalance_max": 0.10,
        "saturation_min": 0.10,
        "yellow_luminance_min": 0.02,
        "boundary_margin": 0.0001,
    }

    deferred_reasons: List[str] = []
    mean_lum = histogram["luminance"]["mean"]
    mean_sat = histogram["saturation"]["mean"]
    margin = thresholds["boundary_margin"]

    # 1. is_dark evaluation
    is_dark: Optional[bool] = None
    dark_diff = abs(mean_lum - thresholds["dark_mean"])
    if dark_diff <= margin:
        is_dark = None
        deferred_reasons.append("is_dark_boundary")
    else:
        is_dark = bool(mean_lum < thresholds["dark_mean"])

    # 2. yellow_tendency evaluation
    yellow_tendency: Optional[bool] = None
    if mean_lum <= thresholds["yellow_luminance_min"]:
        yellow_tendency = None
        deferred_reasons.append("low_luminance_deferred")
    elif analysis.get("wb_applied") == "unity":
        yellow_tendency = None
        deferred_reasons.append("unity_wb_deferred")
    elif yellow_excess is None or red_green_imbalance is None:
        yellow_tendency = None
        deferred_reasons.append("yellow_excess_undefined")
    else:
        # Check if near any decision boundary within boundary_margin
        near_boundary = (
            abs(yellow_excess - thresholds["yellow_excess"]) <= margin
            or abs(red_green_imbalance - thresholds["red_green_imbalance_max"]) <= margin
            or abs(mean_sat - thresholds["saturation_min"]) <= margin
            or abs(mean_lum - thresholds["yellow_luminance_min"]) <= margin
        )
        if near_boundary:
            yellow_tendency = None
            deferred_reasons.append("yellow_tendency_boundary")
        else:
            is_yellow = (
                (yellow_excess > thresholds["yellow_excess"])
                and (red_green_imbalance < thresholds["red_green_imbalance_max"])
                and (mean_sat > thresholds["saturation_min"])
            )
            yellow_tendency = bool(is_yellow)

    return {
        "rules_version": "t18-thresholds-v1",
        "yellow_excess": yellow_excess,
        "red_green_imbalance": red_green_imbalance,
        "is_dark": is_dark,
        "yellow_tendency": yellow_tendency,
        "thresholds": thresholds,
        "deferred_reasons": deferred_reasons,
    }
