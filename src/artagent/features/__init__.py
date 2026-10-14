"""Feature extraction entry point for RAW images."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict

from artagent.features.exif import normalize_exif, read_exif
from artagent.features.histogram import decode_raw_rgb, derive_signals, summarize_rgb


def _ensure_finite(obj: Any) -> None:
    """Ensure all floats in obj are finite."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite float encountered: {obj}")
    elif isinstance(obj, dict):
        for v in obj.values():
            _ensure_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _ensure_finite(v)


def extract_features(raw_path: Path | str) -> Dict[str, Any]:
    """Extract standard EXIF, RGB histogram statistics, and signals from a RAW file.

    Entry point for Task 18. Does not modify the input RAW file.
    """
    path = Path(raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"RAW file not found: {path}")

    # Compute SHA-256 of input RAW bytes
    with open(path, "rb") as f:
        file_bytes = f.read()
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # Determine project-relative path if possible
    try:
        rel_path = str(path.relative_to(Path.cwd()))
    except ValueError:
        rel_path = str(path)

    # 1. EXIF extraction & normalization
    raw_tags = read_exif(path)
    exif = normalize_exif(raw_tags)
    warnings = exif.pop("_warnings", [])

    # 2. RGB decoding
    rgb, analysis = decode_raw_rgb(path, exif)
    analysis["metadata_tool"] = raw_tags["metadata_tool"]
    if analysis.get("wb_applied") == "unity" and "wb_coefficients_missing" not in warnings:
        warnings.append("wb_coefficients_missing")

    # 3. Histogram and signal derivation
    histogram = summarize_rgb(rgb)
    signals = derive_signals(histogram, analysis)

    features: Dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "path": rel_path,
            "sha256": sha256_hash,
        },
        "exif": exif,
        "analysis": analysis,
        "histogram": histogram,
        "signals": signals,
        "warnings": warnings,
    }

    _ensure_finite(features)
    return features


def dumps_features(features: Dict[str, Any]) -> str:
    """Serialize features dict into repeatable JSON string."""
    _ensure_finite(features)

    def rounded(obj: Any) -> Any:
        if isinstance(obj, float):
            return round(obj, 6)
        if isinstance(obj, dict):
            return {key: rounded(value) for key, value in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [rounded(value) for value in obj]
        return obj

    return json.dumps(
        rounded(features), indent=2, ensure_ascii=False, sort_keys=True,
        allow_nan=False,
    ) + "\n"


__all__ = ["extract_features", "dumps_features", "read_exif", "normalize_exif", "decode_raw_rgb", "summarize_rgb", "derive_signals"]
