"""Explicit chat controls use the real local client, never generated prose."""

import pytest
from artagent import gui_bridge
from artagent.live_param_chat import try_apply
from test_live_param import applied, peer, state


def context(server):
    return {"socket_path": str(server.path), "session_id": "run-one",
            "editor_id": "editor-one", "base_revision": 3}


def ready(request):
    if request["op"] == "set_param":
        return applied(request)
    return state(request, lastMutation={"requestId": request["mutationRequestId"],
        "appliedRevision": 4, "previewStatus": "READY"}, mutationStatus="READY")


def forbidden_graph():
    pytest.fail("A live exposure command initialized retrieval/answer generation")


@pytest.mark.parametrize("text", ["/exposure 0.125", "노출을 0.125 EV로 설정해줘",
    "노출 보정을 0.125로 적용해주세요", "set exposure to 0.125 EV"])
def test_explicit_value_uses_frozen_target_and_effective_result(peer, text):
    server = peer(ready)
    response = gui_bridge.process_request({"version": 1, "request_id": "chat-1",
        "text": text, "live_param": context(server)}, forbidden_graph)
    assert response["status"] == "COMPLETED"
    assert "0.13" in response["message"]
    assert response["citations"] == []
    request = server.requests[0]
    assert request["baseRevision"] == 3
    assert request["sessionId"] == "run-one" and request["editorId"] == "editor-one"
    assert request["params"] == {"Exposure.Compensation": 0.125}
    assert server.requests[1]["mutationRequestId"] == request["requestId"]


@pytest.mark.parametrize("text", ["노출을 0.75 EV로 설정하지 마", "노출을 올려줘",
    '"/exposure 0.75"를 설명해줘', "노출을 0.75 EV로 설정해줘라는 문장을 설명해줘",
    "노출을 0.75 EV로 설정해줘 그리고 채도도 바꿔줘", "노출 보정 방법을 알려줘"])
def test_examples_questions_negation_and_compound_requests_never_apply(peer, text):
    server = peer(ready)
    assert try_apply(text, context(server), "question") is None
    assert server.requests == []


@pytest.mark.parametrize("text", ["/exposure nan", "/exposure inf", "/exposure 13",
    "/exposure 0.5 extra", "노출을 -13 EV로 설정해줘"])
def test_invalid_explicit_value_does_not_connect(peer, text):
    server = peer(ready)
    response = try_apply(text, context(server), "invalid")
    assert response["status"] == "FAILED"
    assert response["error"]["code"] == "INVALID_VALUE"
    assert server.requests == []


@pytest.mark.parametrize("target", [None, {}, {"base_revision": True},
    {"socket_path": "/private/tmp/x", "session_id": "run-one", "editor_id": "editor-one",
     "base_revision": 3, "extra": "field"}])
def test_missing_or_invalid_gui_target_never_initializes_graph(target):
    response = gui_bridge.process_request({"version": 1, "request_id": "missing",
        "text": "/exposure 0.5", "live_param": target}, forbidden_graph)
    assert response["status"] == "FAILED"
    assert response["error"]["code"] == "LIVE_TARGET_UNAVAILABLE"


def test_revision_conflict_is_not_retried_with_a_new_revision(peer):
    def conflict(request):
        return {"protocolVersion": 1, "requestId": request["requestId"],
            "sessionId": "run-one", "editorId": "editor-one", "status": "ERROR",
            "error": {"code": "REVISION_CONFLICT", "message": "changed",
                      "details": {"currentRevision": 9}, "retryable": False}}
    server = peer(conflict)
    response = try_apply("/exposure 0.5", context(server), "conflict")
    assert response["status"] == "FAILED"
    assert "변경" in response["message"]
    assert len(server.requests) == 1


def test_lost_ack_is_partial_and_keeps_request_identity(peer):
    server = peer(lambda request: None)
    response = try_apply("/exposure 0.5", context(server), "lost")
    assert response["status"] == "PARTIAL"
    assert response["error"]["code"] == "OUTCOME_UNKNOWN"
    assert "확인" in response["message"]
    assert len(server.requests) == 1


def test_preview_failure_reports_acknowledged_value_without_rollback(peer):
    def failed(request):
        if request["op"] == "set_param":
            return applied(request)
        return state(request, lastMutation={"requestId": request["mutationRequestId"],
            "appliedRevision": 4, "previewStatus": "FAILED"}, mutationStatus="FAILED")
    server = peer(failed)
    response = try_apply("/exposure 0.125", context(server), "failed-preview")
    assert response["status"] == "PARTIAL"
    assert "0.13" in response["message"]
    assert response["error"]["code"] == "PREVIEW_FAILED"
    assert len(server.requests) == 2
