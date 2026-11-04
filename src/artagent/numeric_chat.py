"""Resolve explicit numeric edits against the current photo's native controls."""

from functools import lru_cache
import html
import math
from pathlib import Path
import re
import uuid

from .live_param import Client, LiveParamError, Target

NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
COMMANDS = (
    rf"(?P<name>.+?)(?:을|를)?\s*(?P<value>{NUMBER})\s*(?:EV|K|%|px|도)?\s*"
    r"(?:으로|로)\s*(?:설정|적용)(?:해\s*줘|해\s*주세요|해주세요|해|하세요)?[.!]?",
    rf"set\s+(?P<name>.+?)\s+to\s+(?P<value>{NUMBER})(?:\s*(?:EV|K|%|px))?[.!]?",
    rf"/set\s+(?P<name>.+?)\s+(?P<value>{NUMBER})",
    rf"/exposure\s+(?P<value>{NUMBER})(?:\s*EV)?",
)


def _norm(text):
    # Preserve signs and digits: -4EV and +4EV are different controls.
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).casefold()
    return re.sub(r"[\s_/:()\[\],]+", "", text)


@lru_cache(maxsize=1)
def _translations():
    tables = []
    directory = Path(__file__).resolve().parents[2] / "rtdata/languages"
    for language in ("default", "Korean"):
        try:
            tables.append(dict(line.split(";", 1) for line in
                (directory / language).read_text(encoding="utf-8").splitlines()
                if ";" in line and not line.startswith("#")))
        except OSError:
            tables.append({})
    translations = {}
    for key in tables[0].keys() | tables[1].keys():
        # Long help text is not a control name.
        values = {t[key] for t in tables if key in t and len(t[key]) <= 120}
        for value in values:
            translations.setdefault(_norm(value), set()).update(values)
    return translations


def _names(text):
    values = {text, *_translations().get(_norm(text), ())}
    # Native Korean labels commonly carry the English translation in brackets.
    for value in tuple(values):
        values.update(re.findall(r"\(([^()]+)\)", value))
        values.add(re.sub(r"\([^()]+\)", "", value))
    return {_norm(v) for v in values if _norm(v)}


# Convenience vocabulary augments, rather than limits, the runtime catalogue.
ALIASES = {
    "saturation": {"채도"}, "vibrance": {"생동감", "바이브런스"},
    "whitebalance": {"화이트밸런스", "화이트 밸런스"},
    "temperature": {"색온도", "온도"}, "sharpening": {"샤프닝", "선명화"},
    "localcontrast": {"명료도", "부분 대비"}, "detail": {"세부 수준", "디테일"},
    "radius": {"반경"}, "exposurecompensation": {"노출", "노출 보정", "exposure"},
    "resize": {"리사이즈", "크기 조정"}, "width": {"너비", "폭"},
    "height": {"높이"}, "hue": {"색조"}, "contrast": {"대비"},
}


def _aliases(text):
    names = _names(text)
    parts = text.split(" / ")
    if len(parts) > 1:
        combinations = {""}
        for part in parts:
            combinations = {prefix + name for prefix in combinations for name in _aliases(part)}
        names.update(combinations)
        names.update(_aliases(parts[-1]))
    for english, aliases in ALIASES.items():
        if english in names:
            names.update(_norm(a) for a in aliases)
    return names


def _matches(name, entry):
    query = _norm(name)
    labels = _aliases(entry["label"])
    tools = _aliases(entry["tool"]) | _aliases(entry["toolLabel"])
    return query in labels | {tool + label for tool in tools for label in labels}


def _response(request_id, status, message, code=None):
    return {"version": 1, "request_id": request_id, "status": status,
            "message": message, "steps": [], "citations": [],
            "error": {"code": code, "message": message} if code else None}


def _parse(text):
    text = text.strip()
    if any(c in text for c in ('"', "'", "“", "”", "?", "？", "\n")):
        return None
    listing = re.fullmatch(r"(?P<filter>.*?)\s*조정 가능한 항목\s*"
        r"(?:(?P<page>[0-9]+)\s*페이지\s*)?보여\s*줘[.!]?", text)
    if not listing:
        listing = re.fullmatch(r"list controls(?:\s+(?P<filter>.*?))?"
            r"(?:\s+page\s+(?P<page>[0-9]+))?", text, re.I)
    if listing:
        return ("list", listing["filter"] or "", int(listing["page"] or 1))
    for pattern in COMMANDS:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            name = match.groupdict().get("name") or "exposure"
            if re.search(r"\s(?:and|then|그리고)\s|하지\s*마", name, re.I):
                return None
            return ("set", name.strip(), float(match["value"]))
    return None


def _row(index, entry):
    status = " (현재 모드에서 사용 불가)" if not entry["available"] else (
        " (처리 중)" if entry["pending"] else " (적용 시 도구 켜기)" if not entry["enabled"] else "")
    return (f"항목 {index + 1}: {entry['toolLabel']} / {entry['label']} — "
            f"현재 {entry['value']:g}, 범위 {entry['min']:g}~{entry['max']:g}{status}")


def try_numeric(text, context, request_id):
    command = _parse(text)
    if command is None:
        return None
    action, name, value = command
    if action == "set" and not math.isfinite(value):
        return _response(request_id, "FAILED", "유한한 숫자의 절대값을 지정해주세요.", "INVALID_VALUE")
    try:
        fields = {"socket_path", "session_id", "editor_id", "base_revision", "numeric_context_id"}
        if not isinstance(context, dict) or set(context) != fields:
            raise ValueError("Missing numeric GUI target")
        target = Target(context["session_id"], context["editor_id"], context["base_revision"])
        if not isinstance(context["socket_path"], str) or not isinstance(context["numeric_context_id"], str):
            raise ValueError("Invalid context")
        client = Client(context["socket_path"])
        catalogue = client.catalog(target, context_id=context["numeric_context_id"])
        entries = catalogue["items"]
        if action == "list":
            rows = [(i, e) for i, e in enumerate(entries) if not name or
                    _norm(name) in _aliases(e["tool"]) | _aliases(e["toolLabel"]) |
                    _aliases(e["label"])]
            pages = max(1, (len(rows) + 19) // 20)
            if not 1 <= value <= pages:
                return _response(request_id, "FAILED", f"1~{pages}페이지를 지정해주세요.", "INVALID_VALUE")
            lines = [_row(i, e) for i, e in rows[(value - 1) * 20:value * 20]]
            return _response(request_id, "COMPLETED", f"조정 가능한 항목 {len(rows)}개 · {value}/{pages}페이지\n"
                + "\n".join(lines) + "\n예: 채도를 20으로 설정해줘. 이름이 겹치면 ‘항목 1을 20으로 설정해줘’처럼 지정하세요. "
                "다음 목록은 ‘조정 가능한 항목 2페이지 보여줘’, 도구별 목록은 ‘채도 조정 가능한 항목 보여줘’로 확인하세요.")
        ordinal = re.fullmatch(r"(?:항목\s*([0-9]+)|([0-9]+)번\s*항목|control\s+([0-9]+))", name, re.I)
        if ordinal:
            index = int(next(n for n in ordinal.groups() if n)) - 1
            matches = [(index, entries[index])] if 0 <= index < len(entries) else []
        else:
            matches = [(i, e) for i, e in enumerate(entries) if _matches(name, e)]
            # A bare tool name refers to that tool's namesake control. Explicit
            # tool-qualified names still reach wheels/regions with the same label.
            namesake = [(i, e) for i, e in matches if _norm(name) in
                        (_aliases(e["tool"]) & _aliases(e["label"]))]
            if namesake:
                matches = namesake
        if not matches:
            return _response(request_id, "FAILED", "일치하는 수치 항목을 찾지 못했습니다. "
                "‘조정 가능한 항목 보여줘’에서 현재 도구의 이름과 범위를 확인해주세요.", "UNSUPPORTED_PARAM")
        # Prefer currently usable matches only when there is exactly one; dormant
        # fields from another mode must not make a clear current control ambiguous.
        usable = [(i, e) for i, e in matches if e["available"]]
        if usable:
            matches = usable
        if len(matches) != 1:
            return _response(request_id, "FAILED", "같은 이름의 항목이 여러 개입니다. 도구명이나 항목 번호를 함께 지정해주세요.\n"
                + "\n".join(_row(i, e) for i, e in matches[:12]), "AMBIGUOUS_CONTROL")
        _, entry = matches[0]
        if not entry["available"] or entry["pending"] or not entry["min"] <= value <= entry["max"]:
            code = "BUSY" if entry["pending"] else "TOOL_DISABLED" if not entry["available"] else "INVALID_VALUE"
            return _response(request_id, "FAILED", "현재 모드·처리 상태와 입력 범위를 확인해주세요.\n"
                + _row(matches[0][0], entry), code)
        acknowledgement = client.set_numeric(target, entry["key"], value,
            context_id=catalogue["contextId"], enable_tool=True,
            request_id="chat-" + uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex)
        client.wait_ready(target, acknowledgement)
        result = acknowledgement["result"]
        effective = result["effectiveParams"][entry["key"]]
        activation = " 도구를 함께 켰습니다." if result["enabledTools"] else ""
        return _response(request_id, "COMPLETED",
            f"{entry['toolLabel']} / {entry['label']}을 {effective:g}로 설정했습니다.{activation} 미리보기가 준비됐습니다.")
    except (ValueError, TypeError):
        return _response(request_id, "FAILED", "채팅의 ‘사진 수치 조정 허용’을 켜고 편집기에 사진을 열어 다시 요청해주세요.",
                         "LIVE_TARGET_UNAVAILABLE")
    except LiveParamError as error:
        partial = error.applied is not None or error.uncertain
        if error.uncertain:
            message = "요청을 보낸 뒤 반영 여부를 확인하지 못했습니다. 이미 반영됐을 수 있으니 현재 값을 확인해주세요."
        elif error.applied:
            effective = next(iter(error.applied["result"]["effectiveParams"].values()))
            message = f"값 {effective:g}를 반영했지만 미리보기 완료를 확인하지 못했습니다. 현재 화면과 값을 확인해주세요."
        else:
            message = {
                "REVISION_CONFLICT": "편집 상태·영역·선택한 곡선 점이 변경되었습니다. 현재 상태에서 새로 요청해주세요.",
                "EDITOR_NOT_FOUND": "대상 사진이 닫혔거나 다시 열렸습니다. 현재 사진에서 새로 요청해주세요.",
                "SESSION_MISMATCH": "ART 실행 또는 허용 설정이 변경되었습니다. 현재 사진에서 새로 요청해주세요.",
                "BUSY": "사진이나 이전 수치 변경을 처리 중입니다. 처리가 끝난 뒤 요청해주세요.",
                "TRANSPORT_ERROR": "채팅 수치 연결을 사용할 수 없습니다. 허용 설정과 현재 사진을 확인해주세요.",
            }.get(error.code, "수치 요청을 처리하지 못했습니다. 현재 모드와 값을 확인해주세요.")
        return _response(request_id, "PARTIAL" if partial else "FAILED", message, error.code)
