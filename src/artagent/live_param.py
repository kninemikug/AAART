"""Bounded client for ART's local, single-exposure protocol v1."""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import socket
import stat
import time
import uuid

MAX_FRAME = 65536
MAX_INTEGER = 9007199254740991
PREVIEW_STATUSES = {"PENDING", "READY", "SUPERSEDED", "FAILED"}
ERROR_CODES = {"INVALID_REQUEST", "UNSUPPORTED_VERSION", "UNAUTHORIZED",
    "SESSION_MISMATCH", "EDITOR_NOT_FOUND", "REVISION_CONFLICT", "UNSUPPORTED_PARAM",
    "INVALID_VALUE", "TOOL_DISABLED", "BUSY", "REQUEST_ID_CONFLICT", "INTERNAL_ERROR"}


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_INTEGER


def _number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 128 and "\x00" not in value


def _duration(value):
    try:
        valid = _number(value) and value > 0 and math.isfinite(float(value))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Timeout and interval must be finite and positive")
    return float(value)


@dataclass(frozen=True)
class Target:
    session_id: str
    editor_id: str
    base_revision: int

    def __post_init__(self):
        if (not _identifier(self.session_id) or not _identifier(self.editor_id)
                or not _integer(self.base_revision)):
            raise ValueError("An explicit session, editor and exact revision are required")


class LiveParamError(Exception):
    """Local/remote failure; an acknowledged edit is never silently undone."""

    def __init__(self, code, message, *, request_id="", applied=None, uncertain=False):
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.applied = applied
        self.uncertain = uncertain or code == "OUTCOME_UNKNOWN"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Nonfinite JSON number")


def _revision_pair(result):
    values = [result.get("renderedRevision"), result.get("renderedViewRevision")]
    return ("renderedRevision" in result and "renderedViewRevision" in result
            and (all(v is None for v in values) or all(_integer(v) for v in values)))


def _validate_reply(reply, request):
    """Reject mismatched/malformed replies before interpreting success."""
    if (not isinstance(reply, dict) or type(reply.get("protocolVersion")) is not int
            or reply["protocolVersion"] != 1
            or reply.get("requestId") != request["requestId"]
            or not _identifier(reply.get("sessionId"))
            or reply.get("editorId") != request.get("editorId")):
        raise ValueError("Mismatched response envelope")
    status = reply.get("status")
    if status == "ERROR":
        error = reply.get("error")
        if ("result" in reply or not isinstance(error, dict)
                or not isinstance(error.get("code"), str)
                or error["code"] not in ERROR_CODES
                or not isinstance(error.get("message"), str)
                or not isinstance(error.get("details"), dict)
                or type(error.get("retryable")) is not bool):
            raise ValueError("Malformed error response")
        if (request.get("sessionId") is not None
                and reply["sessionId"] != request["sessionId"]
                and error["code"] != "SESSION_MISMATCH"):
            raise ValueError("Mismatched response session")
        return
    if (request.get("sessionId") is not None
            and reply["sessionId"] != request["sessionId"]):
        raise ValueError("Mismatched response session")
    result = reply.get("result")
    expected = "APPLIED" if request["op"] == "set_param" else "OK"
    if status != expected or "error" in reply or not isinstance(result, dict):
        raise ValueError("Malformed success response")
    if request.get("editorId") is None:
        editors = result.get("editors")
        if not isinstance(editors, list) or any(
            not isinstance(e, dict) or not _identifier(e.get("editorId"))
            or not isinstance(e.get("name"), str) for e in editors
        ):
            raise ValueError("Malformed editor list")
        return
    if (not _integer(result.get("viewRevision")) or not _revision_pair(result)
            or not _integer(result.get("ppVersion"))):
        raise ValueError("Malformed revision fields")
    if status == "APPLIED":
        params = result.get("effectiveParams")
        if (not _integer(result.get("appliedRevision"))
                or result["appliedRevision"] != request["baseRevision"] + 1
                or not isinstance(result.get("previewStatus"), str)
                or result["previewStatus"] not in PREVIEW_STATUSES
                or not isinstance(params, dict)
                or set(params) != {"Exposure.Compensation"}
                or not _number(params["Exposure.Compensation"])
                or not -12 <= params["Exposure.Compensation"] <= 12):
            raise ValueError("Malformed application acknowledgement")
        return
    supported = result.get("supportedParams")
    exposure = supported.get("Exposure.Compensation") if isinstance(supported, dict) else None
    if (not _integer(result.get("revision")) or not isinstance(exposure, dict)
            or type(exposure.get("enabled")) is not bool
            or exposure.get("min") != -12 or exposure.get("max") != 12
            or not _number(exposure.get("value"))):
        raise ValueError("Malformed editor state")
    record = result.get("lastMutation")
    if record is not None and (
        not isinstance(record, dict) or not _identifier(record.get("requestId"))
        or not _integer(record.get("appliedRevision"))
        or not isinstance(record.get("previewStatus"), str)
        or record["previewStatus"] not in PREVIEW_STATUSES
    ):
        raise ValueError("Malformed mutation state")
    if "mutationRequestId" in request:
        if record is None:
            if result.get("mutationStatus") != "UNKNOWN":
                raise ValueError("Missing mutation status")
        elif (record["requestId"] != request["mutationRequestId"]
              or result.get("mutationStatus") != record["previewStatus"]):
            raise ValueError("Mismatched mutation status")


class Client:
    def __init__(self, socket_path, *, timeout=3.0):
        self.socket_path = os.fspath(socket_path)
        if not os.path.isabs(self.socket_path) or "\x00" in self.socket_path:
            raise ValueError("An absolute Unix socket path is required")
        self.timeout = _duration(timeout)

    def _exchange(self, request, *, deadline=None):
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_FRAME:
            raise ValueError("Request exceeds 64 KiB")
        end = min(time.monotonic() + self.timeout, deadline or math.inf)
        sent = False
        try:
            path = Path(self.socket_path)
            parent, endpoint = path.parent.lstat(), path.lstat()
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                    or stat.S_IMODE(parent.st_mode) != 0o700
                    or not stat.S_ISSOCK(endpoint.st_mode)
                    or endpoint.st_uid != os.geteuid()
                    or stat.S_IMODE(endpoint.st_mode) != 0o600):
                raise OSError("Untrusted local endpoint")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                def remaining():
                    delay = end - time.monotonic()
                    if delay <= 0:
                        raise TimeoutError()
                    connection.settimeout(delay)
                remaining()
                connection.connect(self.socket_path)
                remaining()
                sent = True
                connection.sendall(raw + b"\n")
                buffer = bytearray()
                while b"\n" not in buffer:
                    remaining()
                    chunk = connection.recv(min(4096, MAX_FRAME + 1 - len(buffer)))
                    if not chunk:
                        raise OSError("Response connection closed")
                    buffer.extend(chunk)
                    if len(buffer) > MAX_FRAME and not buffer.endswith(b"\n"):
                        raise ValueError("Response exceeds 64 KiB")
                body, tail = bytes(buffer).split(b"\n", 1)
                if len(body) > MAX_FRAME or tail:
                    raise ValueError("Invalid frame boundary")
                reply = json.loads(body.decode("utf-8"), object_pairs_hook=_object,
                                   parse_constant=_invalid_constant)
                _validate_reply(reply, request)
        except (OSError, ValueError, UnicodeError, RecursionError) as error:
            unknown = sent and request["op"] == "set_param"
            code = "OUTCOME_UNKNOWN" if unknown else (
                "TRANSPORT_ERROR" if isinstance(error, OSError) else "PROTOCOL_ERROR")
            raise LiveParamError(code, "ART 요청 결과를 확인하지 못했습니다.",
                                 request_id=request["requestId"]) from None
        if reply["status"] == "ERROR":
            raise LiveParamError(reply["error"]["code"], "ART가 요청을 처리하지 못했습니다.",
                request_id=request["requestId"], uncertain=(request["op"] == "set_param"
                    and reply["error"]["code"] == "INTERNAL_ERROR"))
        return reply

    def get_state(self, target=None, *, mutation_request_id=None, _deadline=None):
        request = {"protocolVersion": 1, "requestId": uuid.uuid4().hex, "op": "get_state"}
        if target is not None:
            if not isinstance(target, Target):
                raise ValueError("An explicit target is required")
            request.update(sessionId=target.session_id, editorId=target.editor_id)
        if mutation_request_id is not None:
            if target is None or not _identifier(mutation_request_id):
                raise ValueError("Mutation lookup requires a target and request ID")
            request["mutationRequestId"] = mutation_request_id
        return self._exchange(request, deadline=_deadline)

    def set_exposure(self, target, value, *, request_id=None):
        if not isinstance(target, Target):
            raise ValueError("An explicit target is required")
        if not _number(value) or not -12 <= value <= 12:
            raise ValueError("Exposure must be a finite number in [-12,12]")
        request_id = request_id if request_id is not None else uuid.uuid4().hex
        if not _identifier(request_id):
            raise ValueError("Request ID must be a 1..128 character string")
        return self._exchange({"protocolVersion": 1, "requestId": request_id,
            "op": "set_param", "sessionId": target.session_id,
            "editorId": target.editor_id, "baseRevision": target.base_revision,
            "params": {"Exposure.Compensation": value}})

    def wait_ready(self, target, applied, *, timeout=30.0, interval=0.05):
        deadline = time.monotonic() + _duration(timeout)
        interval = _duration(interval)
        request_id = applied["requestId"]
        revision = applied["result"]["appliedRevision"]
        try:
            while time.monotonic() < deadline:
                state = self.get_state(target, mutation_request_id=request_id, _deadline=deadline)
                result = state["result"]
                record = result.get("lastMutation")
                if record is None:
                    raise LiveParamError("UNKNOWN_MUTATION", "변경 기록을 확인하지 못했습니다.")
                if record["appliedRevision"] != revision:
                    raise LiveParamError("PROTOCOL_ERROR", "변경의 revision이 일치하지 않습니다.")
                status = record["previewStatus"]
                if status in {"FAILED", "SUPERSEDED"}:
                    raise LiveParamError("PREVIEW_FAILED" if status == "FAILED" else status,
                                         "반영한 노출의 미리보기를 완료하지 못했습니다.")
                if result["revision"] != revision:
                    raise LiveParamError("STATE_CHANGED", "다른 편집이 반영되었습니다.")
                if (status == "READY" and result["renderedRevision"] == revision
                        and result["renderedViewRevision"] == result["viewRevision"]):
                    return state
                time.sleep(min(interval, max(0, deadline - time.monotonic())))
            raise LiveParamError("PREVIEW_PENDING", "노출은 반영됐으며 화면 준비를 기다리고 있습니다.")
        except LiveParamError as error:
            error.applied = applied
            error.request_id = request_id
            if error.code == "TRANSPORT_ERROR" and time.monotonic() >= deadline:
                error.code = "PREVIEW_PENDING"
            raise
