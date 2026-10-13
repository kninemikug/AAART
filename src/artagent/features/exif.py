"""EXIF metadata extraction and normalization for RAW files."""

import math
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple


def _run_cmd(cmd: List[str], timeout: float = 10.0) -> str:
    """Run external command and return stdout."""
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=True,
    )
    return res.stdout


def read_exif(raw_path: Path | str) -> Dict[str, Any]:
    """Read EXIF tags from RAW file using exiv2 and fallback metadata tools.

    Returns a dict containing 'translated' and 'vanilla' tag dictionaries.
    """
    path = Path(raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"RAW file not found: {path}")

    # Read translated tags (-PEkt)
    try:
        stdout_t = _run_cmd(["exiv2", "-PEkt", str(path)])
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Failed to read translated EXIF with exiv2: {e}") from e

    # Read vanilla tags (-PEkv)
    try:
        stdout_v = _run_cmd(["exiv2", "-PEkv", str(path)])
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Failed to read vanilla EXIF with exiv2: {e}") from e

    tags_t: Dict[str, str] = {}
    for line in stdout_t.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            tags_t[parts[0]] = parts[1].strip()
        elif len(parts) == 1:
            tags_t[parts[0]] = ""

    tags_v: Dict[str, str] = {}
    for line in stdout_v.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            tags_v[parts[0]] = parts[1].strip()
        elif len(parts) == 1:
            tags_v[parts[0]] = ""

    return {"translated": tags_t, "vanilla": tags_v}


def _parse_shutter_seconds(val: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """Parse exposure time string into float seconds.

    Returns (seconds, error_code).
    """
    if not val:
        return None, "shutter_missing"
    cleaned = val.replace("s", "").strip()
    if not cleaned:
        return None, "shutter_missing"

    try:
        if "/" in cleaned:
            parts = cleaned.split("/")
            if len(parts) != 2:
                return None, "shutter_format_invalid"
            num = float(parts[0].strip())
            denom = float(parts[1].strip())
            if denom == 0:
                return None, "shutter_division_by_zero"
            sec = num / denom
        else:
            sec = float(cleaned)

        if not math.isfinite(sec) or sec <= 0:
            return None, "shutter_non_positive"
        return sec, None
    except ValueError:
        return None, "shutter_format_invalid"


def _parse_camera_multipliers(
    tags_t: Dict[str, str], tags_v: Dict[str, str]
) -> Tuple[Optional[Dict[str, float]], Optional[str], Optional[str]]:
    """Parse white balance camera multipliers r, g1, b, g2.

    Returns (multipliers_dict, source_tag, warning_code).
    """
    # 1. Try Exif.NikonCb3.WB_RGBGLevels
    tag_name = "Exif.NikonCb3.WB_RGBGLevels"
    raw_val = tags_t.get(tag_name) or tags_v.get(tag_name)
    if raw_val:
        parts = raw_val.split()
        if len(parts) >= 4:
            try:
                r = float(parts[0])
                g1 = float(parts[1])
                b = float(parts[2])
                g2 = float(parts[3])
                if g1 > 0 and r > 0 and b > 0 and g2 > 0:
                    return (
                        {
                            "r": r / g1,
                            "g1": 1.0,
                            "b": b / g1,
                            "g2": g2 / g1,
                        },
                        tag_name,
                        None,
                    )
            except ValueError:
                pass

    return None, None, "wb_coefficients_missing"


def normalize_exif(raw_tags: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw EXIF tags into standard schema fields and track sources.

    Returns normalized exif dictionary with an internal '_warnings' key.
    """
    tags_t: Dict[str, str] = raw_tags.get("translated", {})
    tags_v: Dict[str, str] = raw_tags.get("vanilla", {})

    warnings: List[str] = []
    source_tags: Dict[str, Optional[str]] = {}

    # 1. ISO
    iso: Optional[int] = None
    iso_src: Optional[str] = None
    if "Exif.Photo.ISOSpeedRatings" in tags_t:
        val = tags_t["Exif.Photo.ISOSpeedRatings"]
        try:
            parsed = int(val)
            if parsed > 0:
                iso = parsed
                iso_src = "Exif.Photo.ISOSpeedRatings"
        except ValueError:
            pass

    if iso is None and "Exif.Nikon3.ISOSpeed" in tags_t:
        val = tags_t["Exif.Nikon3.ISOSpeed"]
        try:
            parsed = int(val)
            if parsed > 0:
                iso = parsed
                iso_src = "Exif.Nikon3.ISOSpeed"
        except ValueError:
            pass

    if iso is None:
        warnings.append("iso_missing")
    source_tags["iso"] = iso_src

    # 2. Shutter seconds
    shutter_sec: Optional[float] = None
    shutter_src: Optional[str] = None
    shutter_raw = tags_v.get("Exif.Photo.ExposureTime") or tags_t.get("Exif.Photo.ExposureTime")
    if shutter_raw:
        shutter_sec, err = _parse_shutter_seconds(shutter_raw)
        if err:
            warnings.append(err)
        else:
            shutter_src = "Exif.Photo.ExposureTime"
    else:
        warnings.append("shutter_missing")
    source_tags["shutter_seconds"] = shutter_src

    # 3. Camera Make & Model
    make: Optional[str] = tags_t.get("Exif.Image.Make", "").strip() or None
    model: Optional[str] = tags_t.get("Exif.Image.Model", "").strip() or None
    source_tags["camera.make"] = "Exif.Image.Make" if make else None
    source_tags["camera.model"] = "Exif.Image.Model" if model else None

    # 4. White balance
    wb_mode: Optional[str] = None
    wb_mode_src: Optional[str] = None
    raw_mode = tags_t.get("Exif.Photo.WhiteBalance", "").lower()
    if raw_mode in ("auto", "0"):
        wb_mode = "auto"
        wb_mode_src = "Exif.Photo.WhiteBalance"
    elif raw_mode in ("manual", "1"):
        wb_mode = "manual"
        wb_mode_src = "Exif.Photo.WhiteBalance"
    source_tags["white_balance.mode"] = wb_mode_src

    wb_preset: Optional[str] = tags_t.get("Exif.Nikon3.WhiteBalance", "").strip() or None
    source_tags["white_balance.preset"] = "Exif.Nikon3.WhiteBalance" if wb_preset else None

    temperature_kelvin: Optional[float] = None
    source_tags["white_balance.temperature_kelvin"] = None

    multipliers, wb_mult_src, wb_mult_warn = _parse_camera_multipliers(tags_t, tags_v)
    source_tags["white_balance.camera_multipliers"] = wb_mult_src
    if wb_mult_warn:
        warnings.append(wb_mult_warn)

    return {
        "iso": iso,
        "shutter_seconds": round(shutter_sec, 6) if shutter_sec is not None else None,
        "camera": {
            "make": make,
            "model": model,
        },
        "white_balance": {
            "mode": wb_mode,
            "preset": wb_preset,
            "temperature_kelvin": temperature_kelvin,
            "camera_multipliers": multipliers,
        },
        "source_tags": source_tags,
        "_warnings": warnings,
    }
