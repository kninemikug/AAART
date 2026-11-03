"""Client contracts with actual bounded Unix-stream peers; no ART-value stubs."""

import json
import os
from pathlib import Path
import socket
import threading
import tempfile
import time

import pytest

from artagent.live_param import Client, LiveParamError, Target


def state(request, **updates):
    result = {
        "revision": 4, "viewRevision": 2, "renderedRevision": 4,
        "renderedViewRevision": 2, "ppVersion": 1045,
        "supportedParams": {"Exposure.Compensation": {
            "min": -12, "max": 12, "enabled": True, "value": 0.75}},
        "lastMutation": None,
    }
    result.update(updates)
    return {"protocolVersion": 1, "requestId": request["requestId"],
            "sessionId": "run-one", "editorId": "editor-one",
            "status": "OK", "result": result}


def applied(request):
    return {"protocolVersion": 1, "requestId": request["requestId"],
            "sessionId": "run-one", "editorId": "editor-one", "status": "APPLIED",
            "result": {"appliedRevision": 4, "viewRevision": 2,
                       "effectiveParams": {"Exposure.Compensation": 0.13},
                       "previewStatus": "PENDING", "renderedRevision": 3,
                       "renderedViewRevision": 2, "ppVersion": 1045}}


class Peer:
    def __init__(self, tmp_path, handler):
        self.path = tmp_path / "peer.sock"
        self.requests = []
        self.errors = []
        self.handler = handler
        self.stop = threading.Event()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        self.path.chmod(0o600)
        self.socket.listen()
        self.socket.settimeout(0.1)
        self.worker = threading.Thread(target=self.serve, daemon=True)
        self.worker.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1)
                try:
                    raw = conn.makefile("rb").readline(65538)
                    request = json.loads(raw)
                    self.requests.append(request)
                    response = self.handler(request)
                    if response is not None:
                        raw = response if isinstance(response, bytes) else (
                            json.dumps(response, ensure_ascii=False).encode() + b"\n")
                        # Exercise fragmented reads across UTF-8 and JSON boundaries.
                        for offset in range(0, len(raw), 71):
                            conn.sendall(raw[offset:offset + 71])
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    self.errors.append(error)

    def close(self):
        self.stop.set()
        self.socket.close()
        self.worker.join(timeout=2)
        assert not self.worker.is_alive()
        assert not self.errors


@pytest.fixture
def peer(tmp_path):
    peers = []
    directories = []

    def make(handler=state):
        temporary = tempfile.TemporaryDirectory(prefix="art-client-", dir="/private/tmp")
        directories.append(temporary)
        item = Peer(Path(temporary.name), handler)
        peers.append(item)
        return item

    yield make
    for item in peers:
        item.close()
    for directory in directories:
        directory.cleanup()


def target():
    return Target("run-one", "editor-one", 3)


def test_explicit_target_and_effective_gui_value(peer):
    server = peer(applied)
    reply = Client(server.path).set_exposure(target(), 0.125, request_id="same-id")
    assert reply["result"]["effectiveParams"] == {"Exposure.Compensation": 0.13}
    assert server.requests == [{"protocolVersion": 1, "requestId": "same-id",
        "op": "set_param", "sessionId": "run-one", "editorId": "editor-one",
        "baseRevision": 3, "params": {"Exposure.Compensation": 0.125}}]


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), -12.01, 12.01])
def test_invalid_value_never_connects(peer, value):
    server = peer()
    with pytest.raises(ValueError):
        Client(server.path).set_exposure(target(), value)
    assert server.requests == []


@pytest.mark.parametrize("revision", [True, -1, 1.5, 9007199254740992])
def test_target_requires_exact_nonnegative_revision(revision):
    with pytest.raises(ValueError):
        Target("run-one", "editor-one", revision)


def test_list_uses_no_implicit_active_editor(peer):
    def listing(request):
        reply = state(request)
        reply["editorId"] = None
        reply["result"] = {"editors": [{"editorId": "editor-one", "name": '사진 "가".nef'}]}
        return reply
    server = peer(listing)
    reply = Client(server.path).get_state()
    assert reply["result"]["editors"][0]["name"] == '사진 "가".nef'
    assert "editorId" not in server.requests[0]


@pytest.mark.parametrize("change", [
    {"requestId": "foreign"}, {"sessionId": "run-other"},
    {"editorId": "editor-other"}, {"protocolVersion": True},
    {"status": "READY"}, {"result": []},
])
def test_untrusted_reply_cannot_confirm_a_mutation(peer, change):
    def bad(request):
        return {**applied(request), **change}
    server = peer(bad)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5, request_id="mutation")
    assert error.value.code == "OUTCOME_UNKNOWN"
    assert error.value.request_id == "mutation"
    assert len(server.requests) == 1


@pytest.mark.parametrize("raw", [
    b'{"protocolVersion":1,"protocolVersion":1}\n',
    b'{} {}\n', b'\xff\n', b'x' * 65537,
], ids=["duplicate", "trailing", "utf8", "oversized"])
def test_invalid_or_oversized_response_is_bounded_and_never_retried(peer, raw):
    server = peer(lambda request: raw)
    with pytest.raises(LiveParamError):
        Client(server.path, timeout=0.3).set_exposure(target(), 0.5)
    assert len(server.requests) == 1


def test_disconnect_after_send_retains_original_mutation_id(peer):
    server = peer(lambda request: None)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5, request_id="lost-ack")
    assert error.value.code == "OUTCOME_UNKNOWN"
    assert error.value.request_id == "lost-ack"
    assert len(server.requests) == 1


def test_failed_connection_has_no_possible_applied_mutation(tmp_path):
    with pytest.raises(LiveParamError) as error:
        Client(tmp_path / "absent.sock").set_exposure(target(), 0.5)
    assert error.value.code == "TRANSPORT_ERROR"


def test_wait_requires_current_view_and_matching_mutation(peer):
    queried = []
    def handler(request):
        if request["op"] == "set_param":
            return applied(request)
        queried.append(request)
        ready = len(queried) > 1
        record = {"requestId": "apply", "appliedRevision": 4, "previewStatus": "READY"}
        return state(request, viewRevision=3, renderedViewRevision=3 if ready else 2,
                     lastMutation=record, mutationStatus="READY")
    server = peer(handler)
    client = Client(server.path)
    ack = client.set_exposure(target(), 0.125, request_id="apply")
    result = client.wait_ready(target(), ack, timeout=1, interval=0.001)
    assert result["result"]["renderedViewRevision"] == 3
    assert len(queried) == 2
    assert all(r["mutationRequestId"] == "apply" for r in queried)
    assert len([r for r in server.requests if r["op"] == "set_param"]) == 1


@pytest.mark.parametrize("status,code", [("FAILED", "PREVIEW_FAILED"),
    ("SUPERSEDED", "SUPERSEDED"), ("UNKNOWN", "UNKNOWN_MUTATION")])
def test_terminal_preview_outcomes_preserve_applied_value(peer, status, code):
    def handler(request):
        if request["op"] == "set_param":
            return applied(request)
        record = None if status == "UNKNOWN" else {
            "requestId": "apply", "appliedRevision": 4, "previewStatus": status}
        return state(request, lastMutation=record, mutationStatus=status)
    server = peer(handler)
    client = Client(server.path)
    ack = client.set_exposure(target(), 0.125, request_id="apply")
    with pytest.raises(LiveParamError) as error:
        client.wait_ready(target(), ack, timeout=1)
    assert error.value.code == code
    assert error.value.applied == ack
    assert len(server.requests) == 2


def test_preview_timeout_does_not_turn_applied_into_rollback(peer):
    def handler(request):
        if request["op"] == "set_param":
            return applied(request)
        return state(request, lastMutation={"requestId": "apply", "appliedRevision": 4,
                     "previewStatus": "PENDING"}, mutationStatus="PENDING")
    server = peer(handler)
    client = Client(server.path)
    ack = client.set_exposure(target(), 0.125, request_id="apply")
    started = time.monotonic()
    with pytest.raises(LiveParamError) as error:
        client.wait_ready(target(), ack, timeout=0.1, interval=0.01)
    assert time.monotonic() - started < 0.8
    assert error.value.code == "PREVIEW_PENDING"
    assert error.value.applied == ack
    assert sum(r["op"] == "set_param" for r in server.requests) == 1


def test_restart_rejection_is_not_reported_as_a_new_application(peer):
    def restarted(request):
        return {"protocolVersion": 1, "requestId": request["requestId"],
                "sessionId": "run-new", "editorId": "editor-one", "status": "ERROR",
                "error": {"code": "SESSION_MISMATCH", "message": "Restarted",
                          "details": {}, "retryable": False}}
    server = peer(restarted)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5)
    assert error.value.code == "SESSION_MISMATCH"
    assert error.value.applied is None
    assert len(server.requests) == 1


def test_insecure_endpoint_is_rejected_before_sending(peer):
    server = peer()
    server.path.chmod(0o666)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5)
    assert error.value.code == "TRANSPORT_ERROR"
    assert server.requests == []


def test_huge_integer_value_is_rejected_before_io(peer):
    server = peer()
    with pytest.raises(ValueError):
        Client(server.path).set_exposure(target(), 10 ** 1000)
    assert server.requests == []


def test_internal_application_error_preserves_uncertain_outcome(peer):
    def failure(request):
        return {"protocolVersion": 1, "requestId": request["requestId"],
                "sessionId": "run-one", "editorId": "editor-one", "status": "ERROR",
                "error": {"code": "INTERNAL_ERROR", "message": "Result unknown",
                          "details": {}, "retryable": False}}
    server = peer(failure)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5)
    assert error.value.code == "INTERNAL_ERROR"
    assert error.value.uncertain
    assert len(server.requests) == 1


@pytest.mark.parametrize("field,value", [("previewStatus", []), ("previewStatus", {}),
                                         ("appliedRevision", True), ("ppVersion", False)])
def test_malformed_acknowledgement_fields_cannot_escape_outcome_tracking(peer, field, value):
    def malformed(request):
        reply = applied(request)
        reply["result"][field] = value
        return reply
    server = peer(malformed)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_exposure(target(), 0.5)
    assert error.value.uncertain
    assert len(server.requests) == 1
