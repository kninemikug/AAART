"""Apply only complete, explicit absolute-exposure commands from chat."""

import math
import re
import uuid

from .live_param import Client, LiveParamError, Target

NUMBER = r"([+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
COMMANDS = (
    rf"/exposure\s+{NUMBER}(?:\s*EV)?",
    rf"노출(?:\s*보정)?(?:을|를)?\s*{NUMBER}\s*(?:EV\s*)?(?:로|으로)\s*"
    r"(?:설정|적용)(?:해\s*줘|해\s*주세요|해주세요|해|하세요)?[.!]?",
    rf"set\s+exposure\s+to\s+{NUMBER}(?:\s*EV)?[.!]?",
)


def _value(text):
    for pattern in COMMANDS:
        match = re.fullmatch(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if not math.isfinite(value) or not -12 <= value <= 12:
                raise ValueError("Exposure outside range")
            return value
    if text.strip().lower().startswith("/exposure"):
        raise ValueError("Invalid explicit exposure command")
    return None


def _response(request_id, status, message, code=None):
    return {
        "version": 1, "request_id": request_id, "status": status,
        "message": message, "steps": [], "citations": [],
        "error": {"code": code, "message": message} if code else None,
    }


def try_apply(text, context, request_id):
    """Return None for ordinary questions; never infer edits from answer text."""
    try:
        value = _value(text)
    except ValueError:
        return _response(request_id, "FAILED",
            "노출 절대값을 -12~12 EV의 숫자로 지정해주세요. 예: /exposure 0.75",
            "INVALID_VALUE")
    if value is None:
        return None
    try:
        required = {"socket_path", "session_id", "editor_id", "base_revision"}
        if not isinstance(context, dict) or set(context) != required:
            raise ValueError("Missing GUI target")
        target = Target(context["session_id"], context["editor_id"], context["base_revision"])
        if not isinstance(context["socket_path"], str):
            raise ValueError("Invalid socket path")
        client = Client(context["socket_path"])
    except (ValueError, TypeError):
        return _response(request_id, "FAILED",
            "실시간 노출 조정을 켠 상태에서 편집기에 사진을 열고 다시 요청해주세요.",
            "LIVE_TARGET_UNAVAILABLE")
    # Stable across reconnects for the original GUI request, within the 128-char limit.
    mutation_id = "chat-" + uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex
    try:
        acknowledgement = client.set_exposure(target, value, request_id=mutation_id)
        client.wait_ready(target, acknowledgement)
        effective = acknowledgement["result"]["effectiveParams"]["Exposure.Compensation"]
        return _response(request_id, "COMPLETED",
            f"노출을 {effective:+.2f} EV로 설정했습니다. 미리보기가 준비됐습니다.")
    except LiveParamError as error:
        partial = error.applied is not None or error.uncertain
        if error.uncertain:
            message = ("요청을 보낸 뒤 반영 여부를 확인하지 못했습니다. "
                       "이미 반영됐을 수 있으니 현재 노출을 확인해주세요.")
        elif error.applied is not None:
            effective = error.applied["result"]["effectiveParams"]["Exposure.Compensation"]
            notices = {
                "PREVIEW_PENDING": "미리보기는 아직 준비 중입니다.",
                "PREVIEW_FAILED": "미리보기를 준비하지 못했습니다.",
                "SUPERSEDED": "이후 다른 편집이 반영되었습니다.",
                "STATE_CHANGED": "이후 다른 편집이 반영되었습니다.",
            }
            message = (f"노출 {effective:+.2f} EV를 반영했습니다. "
                       + notices.get(error.code, "미리보기 상태를 확인하지 못했습니다.")
                       + " 현재 화면과 노출을 확인해주세요.")
        else:
            messages = {
                "REVISION_CONFLICT": "사진의 편집 상태가 변경되었습니다. 현재 노출을 확인하고 새로 요청해주세요.",
                "EDITOR_NOT_FOUND": "대상 사진이 닫혔거나 다시 열렸습니다. 현재 사진에서 새로 요청해주세요.",
                "SESSION_MISMATCH": "ART 실행이 변경되었습니다. 현재 사진에서 새로 요청해주세요.",
                "TOOL_DISABLED": "노출 도구가 꺼져 있습니다. 도구를 켠 뒤 다시 요청해주세요.",
                "BUSY": "사진이나 이전 요청을 처리 중입니다. 현재 상태를 확인한 뒤 요청해주세요.",
                "TRANSPORT_ERROR": "실시간 노출 연결을 사용할 수 없습니다. ART와 현재 사진을 확인해주세요.",
            }
            message = messages.get(error.code, "노출 요청을 처리하지 못했습니다. 현재 노출을 확인해주세요.")
        return _response(request_id, "PARTIAL" if partial else "FAILED", message, error.code)
