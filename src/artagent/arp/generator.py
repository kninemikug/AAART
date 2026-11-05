"""Generate partial .arp profiles with strict key, constraint and version checks."""

from __future__ import annotations

import configparser
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any, Callable

from jsonschema import Draft202012Validator, validators


ROOT = Path(__file__).resolve().parents[3]
HEADER_PATH = ROOT / "rtgui/ppversion.h"
SCHEMA_PATH = Path(__file__).with_name("schema.json")
PROMPT_VERSION = "t19-profile-v1"

# JSON Schema considers 1.0 an integer; ART's integer fields require Python ints.
_TYPES = Draft202012Validator.TYPE_CHECKER.redefine_many({
    "integer": lambda checker, value: type(value) is int,
    "number": lambda checker, value: type(value) in (int, float) and math.isfinite(value),
})
_Validator = validators.extend(Draft202012Validator, type_checker=_TYPES)


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite number")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _finite(child)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text: str) -> Any:
    """Parse one plain JSON document; reject duplicates and non-finite numbers."""
    result = json.loads(text, object_pairs_hook=_unique_pairs)
    _finite(result)
    return result


def load_schema(header_path: Path = HEADER_PATH) -> dict:
    """Fail closed when the source header and supported profile version differ."""
    try:
        header = Path(header_path).read_text(encoding="utf-8")
        schema = strict_json(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read version/schema: {exc}") from exc
    versions = re.findall(r"^\s*#define\s+PPVERSION\s+(\d+)\s*$", header, re.MULTILINE)
    supported = schema["properties"]["ppversion"]["const"]
    if len(versions) != 1 or int(versions[0]) != supported:
        raise ValueError(f"PPVERSION conflict: header={versions}, schema={supported}")
    Draft202012Validator.check_schema(schema)
    return schema


def validate_profile(profile: dict, *, header_path: Path = HEADER_PATH) -> None:
    """Validate the complete structured profile before emitting any INI text."""
    _finite(profile)
    validator = _Validator(load_schema(header_path))
    error = next(validator.iter_errors(profile), None)
    if error is not None:
        location = ".".join(map(str, error.absolute_path)) or "profile"
        raise ValueError(f"{location}: {error.message}")


def serialize_profile(profile: dict, *, header_path: Path = HEADER_PATH) -> str:
    """Serialize only known, validated keys in a fixed order and locale."""
    validate_profile(profile, header_path=header_path)
    lines = ["[Version]", f"Version={profile['ppversion']}", ""]
    schema = load_schema(header_path)
    for group, definition in schema["properties"]["groups"]["properties"].items():
        if group not in profile["groups"]:
            continue
        lines.append(f"[{group}]")
        values = profile["groups"][group]
        for key in definition["properties"]:
            if key in values:
                value = values[key]
                rendered = str(value).lower() if type(value) is bool else str(value)
                lines.append(f"{key}={rendered}")
        lines.append("")
    return "\n".join(lines)


def parse_profile(text: str, *, header_path: Path = HEADER_PATH) -> dict:
    """Read the generated subset, preserving case and rejecting duplicate keys."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_file(io.StringIO(text))
        if parser.defaults() or set(parser["Version"]) != {"Version"}:
            raise ValueError("Invalid Version/defaults section")
        profile = {"ppversion": int(parser["Version"]["Version"]), "groups": {}}
        schema = load_schema(header_path)
        definitions = schema["properties"]["groups"]["properties"]
        for group in parser.sections():
            if group == "Version":
                continue
            if group not in definitions:
                raise ValueError(f"Unknown group: {group}")
            values = {}
            for key, value in parser[group].items():
                definition = definitions[group]["properties"].get(key)
                if definition is None:
                    raise ValueError(f"Unknown key: {group}.{key}")
                kind = definition["type"]
                if kind == "boolean":
                    if value not in ("true", "false"):
                        raise ValueError(f"Invalid boolean: {group}.{key}")
                    values[key] = value == "true"
                elif kind == "integer":
                    values[key] = int(value)
                elif kind == "number":
                    values[key] = float(value)
                else:
                    values[key] = value
            profile["groups"][group] = values
        validate_profile(profile, header_path=header_path)
        return profile
    except (configparser.Error, KeyError) as exc:
        raise ValueError(f"Invalid profile INI: {exc}") from exc


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def generate_profile(
    request: str,
    features: dict,
    *,
    runtime: Callable[[str], dict],
    header_path: Path = HEADER_PATH,
) -> dict:
    """Return a validated profile or an explicit failure without writing files."""
    result: dict[str, Any] = {"prompt_version": PROMPT_VERSION}
    try:
        schema = load_schema(header_path)
        if not isinstance(request, str) or not request.strip() or len(request) > 10000:
            raise ValueError("Expected a nonempty request of at most 10000 characters")
        _finite(features)
        if not isinstance(features, dict) or type(features.get("schema_version")) is not int or features["schema_version"] != 1:
            raise ValueError("Unsupported T18 feature schema")
        result.update(request_sha256=hashlib.sha256(request.encode()).hexdigest(),
                      features_sha256=hashlib.sha256(_canonical(features).encode()).hexdigest())
    except (ValueError, TypeError) as exc:
        return dict(result, status="validation_error", error=str(exc))

    prompt = ("요청과 사진 특성을 사용해 노출 보정을 제안한다. 도구를 사용하지 않는다. "
              '순수 JSON {"groups":{"Exposure":{"Compensation":number}},"reason":string}만 출력한다.\n'
              f"제약: {_canonical(schema)}\n요청: {_canonical(request)}\n사진 특성: {_canonical(features)}")
    try:
        reply = runtime(prompt)
        result.update(runtime=reply["metadata"], raw_response=reply["raw_response"])
        proposal = strict_json(reply["raw_response"])
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        return dict(result, status="runtime_error", error=str(exc))
    try:
        if not isinstance(proposal, dict) or set(proposal) != {"groups", "reason"}:
            raise ValueError("Expected only groups and reason")
        if not isinstance(proposal["reason"], str) or not proposal["reason"].strip():
            raise ValueError("Missing generation reason")
        groups = proposal["groups"]
        if not isinstance(groups, dict) or any(not isinstance(v, dict) or "Enabled" in v for v in groups.values()):
            raise ValueError("Enabled is assembled by the host")
        profile = {"ppversion": schema["properties"]["ppversion"]["const"],
                   "groups": {g: {"Enabled": True, **v} for g, v in groups.items()}}
        arp = serialize_profile(profile, header_path=header_path)
        if parse_profile(arp, header_path=header_path) != profile:
            raise ValueError("Profile round-trip mismatch")
        return dict(result, status="ok", profile=profile, arp=arp,
                    reason=proposal["reason"], warnings=list(features.get("warnings", [])))
    except (ValueError, TypeError) as exc:
        return dict(result, status="validation_error", error=str(exc))
