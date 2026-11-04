"""User-facing numeric chat commands with real Unix peers, no answer service."""
import pytest

from artagent import gui_bridge
from artagent.live_param_chat import try_apply
from test_live_param import peer, applied, state
from test_live_param_numeric import item


def context(server):
    return {"socket_path": str(server.path), "session_id": "run-one",
            "editor_id": "editor-one", "base_revision": 3,
            "numeric_context_id": "context-one"}


def responder(entries):
    def handle(request):
        if request["op"] == "list_params":
            start = request["offset"]
            end = min(start + request["limit"], len(entries))
            return {"protocolVersion": 1, "requestId": request["requestId"],
                    "sessionId": "run-one", "editorId": "editor-one", "status": "OK",
                    "result": {"revision": 3, "contextId": "context-one",
                               "items": entries[start:end], "total": len(entries),
                               "nextOffset": end if end < len(entries) else None}}
        if request["op"] == "set_param":
            reply = applied(request)
            reply["result"].update(effectiveParams=request["params"],
                                   enabledTools=["saturation"])
            return reply
        return state(request, lastMutation={"requestId": request["mutationRequestId"],
            "appliedRevision": 4, "previewStatus": "READY"}, mutationStatus="READY")
    return handle


@pytest.mark.parametrize("text,entry,value", [
    ("채도를 20으로 설정해줘", item(), 20),
    ("set saturation to 20", item(), 20),
    ("색온도를 6500으로 설정해줘", dict(item(), tool="whitebalance",
        toolLabel="White Balance", label="Temperature", min=1500, max=60000), 6500),
    ("샤프닝 반경을 0.8로 설정해줘", dict(item(), tool="sharpening",
        toolLabel="Sharpening", label="Radius", min=.1, max=2), .8),
    ("명료도 세부 수준을 4로 설정해줘", dict(item(), tool="localcontrast",
        toolLabel="Local Contrast", label="Detail", min=0, max=10), 4),
    ("항목 1을 20으로 설정해줘", item(), 20),
])
def test_numeric_names_resolve_from_catalogue_and_enable_requested_tool(peer, text, entry, value):
    server = peer(responder([entry]))
    response = gui_bridge.process_request({"version": 1, "request_id": "numeric-chat",
        "text": text, "live_param": context(server)},
        lambda: pytest.fail("Numeric commands must not initialize answers"))
    assert response["status"] == "COMPLETED", response
    mutation = next(r for r in server.requests if r["op"] == "set_param")
    assert mutation["params"] == {entry["key"]: value}
    assert mutation["contextId"] == "context-one" and mutation["enableTool"] is True
    assert mutation["baseRevision"] == 3
    assert "켰습니다" in response["message"]


def test_all_pages_are_searchable_without_a_field_whitelist(peer):
    entries = [dict(item(f"numeric-{n}"), label=f"Custom control {n}") for n in range(40)]
    server = peer(responder(entries))
    response = try_apply("set custom control 39 to 12", context(server), "dynamic")
    assert response["status"] == "COMPLETED"
    assert [r["offset"] for r in server.requests if r["op"] == "list_params"] == [0, 32]
    assert next(r for r in server.requests if r["op"] == "set_param")["params"] == {"numeric-39": 12}


def test_ambiguous_names_show_numbered_candidates_without_editing(peer):
    entries = [dict(item(), tool="sharpening", toolLabel="Sharpening", label="Radius"),
               dict(item("numeric-2"), tool="localcontrast", toolLabel="Local Contrast", label="Radius")]
    server = peer(responder(entries))
    response = try_apply("반경을 1로 설정해줘", context(server), "ambiguous")
    assert response["status"] == "FAILED" and response["error"]["code"] == "AMBIGUOUS_CONTROL"
    assert "항목 1" in response["message"] and "항목 2" in response["message"]
    assert all(r["op"] == "list_params" for r in server.requests)


@pytest.mark.parametrize("text", ["조정 가능한 항목 보여줘", "조정 가능한 항목 2페이지 보여줘",
                                   "채도 조정 가능한 항목 보여줘"])
def test_listing_is_bounded_read_only_and_never_shows_wire_keys(peer, text):
    entries = [dict(item(f"numeric-{n}"), label=f"Custom control {n}") for n in range(40)]
    server = peer(responder(entries))
    response = try_apply(text, context(server), "listing")
    assert response["status"] == "COMPLETED"
    assert "numeric-" not in response["message"] and len(response["message"]) < 6000
    assert all(r["op"] == "list_params" for r in server.requests)


@pytest.mark.parametrize("changes", [{"available": False}, {"pending": True}, {"min": 30}])
def test_unavailable_pending_and_out_of_range_never_mutate(peer, changes):
    server = peer(responder([dict(item(), **changes)]))
    response = try_apply("채도를 20으로 설정해줘", context(server), "invalid")
    assert response["status"] == "FAILED"
    assert all(r["op"] == "list_params" for r in server.requests)


@pytest.mark.parametrize("text", ["채도를 올려줘", "채도를 20으로 설정하지 마",
    "채도를 20으로 설정해줘라는 문장을 설명해줘", '"set saturation to 20"',
    "set saturation to 20 and contrast to 30", "채도 20이 적당해?"])
def test_non_commands_do_not_connect(peer, text):
    server = peer(responder([item()]))
    assert try_apply(text, context(server), "question") is None
    assert not server.requests


def test_missing_context_refuses_numeric_command_without_graph():
    response = gui_bridge.process_request({"version": 1, "request_id": "off",
        "text": "채도를 20으로 설정해줘"}, lambda: pytest.fail("No graph"))
    assert response["error"]["code"] == "LIVE_TARGET_UNAVAILABLE"


def test_lost_numeric_ack_is_partial_and_not_retried(peer):
    catalogue = responder([item()])
    server = peer(lambda r: catalogue(r) if r["op"] == "list_params" else None)
    response = try_apply("채도를 20으로 설정해줘", context(server), "unknown")
    assert response["status"] == "PARTIAL" and response["error"]["code"] == "OUTCOME_UNKNOWN"
    assert sum(r["op"] == "set_param" for r in server.requests) == 1


def test_band_signs_are_distinct(peer):
    entries = [dict(item(), label="-4EV"), dict(item("numeric-2"), label="+4EV")]
    server = peer(responder(entries))
    response = try_apply("set -4EV to 10", context(server), "band")
    assert response["status"] == "COMPLETED"
    assert next(r for r in server.requests if r["op"] == "set_param")["params"] == {"numeric-1": 10}


@pytest.mark.parametrize("text,expected", [("채도를 20으로 설정해줘", "numeric-1"),
    ("set color correction saturation to 20", "numeric-wheel")])
def test_namesake_tool_and_explicit_other_tool_remain_distinct(peer, text, expected):
    entries = [item(), dict(item("numeric-wheel"), tool="colorcorrection",
                           toolLabel="Color Correction", max=250)]
    server = peer(responder(entries))
    response = try_apply(text, context(server), "same-label")
    assert response["status"] == "COMPLETED"
    assert next(r for r in server.requests if r["op"] == "set_param")["params"] == {expected: 20}


@pytest.mark.parametrize("text,entry", [
    ("채도를 20EV로 설정해줘", item()),
    ("set saturation to 20K", item()),
    ("set saturation to 20%", item()),
    # Width can be in cm/inches in the native GUI. The catalogue does not
    # publish that unit, so a px suffix cannot be interpreted safely.
    ("set resize width to 20px", dict(item(), tool="resize", toolLabel="Resize", label="Width")),
    ("색온도를 6500EV로 설정해줘", dict(item(), tool="whitebalance",
        toolLabel="White Balance", label="Temperature", min=1500, max=60000)),
])
def test_unverified_units_never_reach_a_numeric_mutation(peer, text, entry):
    server = peer(responder([entry]))
    response = try_apply(text, context(server), "wrong-unit")
    assert response["status"] == "FAILED", response
    assert response["error"]["code"] == "INVALID_VALUE"
    assert "단위" in response["message"]
    assert all(r["op"] == "list_params" for r in server.requests)


@pytest.mark.parametrize("text,entry,expected", [
    ("노출을 0.75EV로 설정해줘", dict(item("Exposure.Compensation"),
        tool="exposure", toolLabel="Exposure", label="Exposure compensation", min=-12, max=12), .75),
    ("set temperature to 6500K", dict(item(), tool="whitebalance",
        toolLabel="White Balance", label="Temperature", min=1500, max=60000), 6500),
])
def test_intrinsic_exposure_and_temperature_units_remain_supported(peer, text, entry, expected):
    server = peer(responder([entry]))
    response = try_apply(text, context(server), "known-unit")
    assert response["status"] == "COMPLETED", response
    assert next(r for r in server.requests if r["op"] == "set_param")["params"] == {entry["key"]: expected}
