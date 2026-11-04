"""Numeric catalogue and mutation contracts over real Unix stream peers."""
import pytest

from artagent.live_param import Client, LiveParamError
from test_live_param import peer, target, applied


def item(key="numeric-1"):
    return {"key": key, "tool": "saturation", "toolLabel": "Saturation",
            "label": "Saturation", "min": -100, "max": 100, "step": 1,
            "value": 0, "enabled": False, "available": True, "pending": False}


def page(request):
    offset = request.get("offset", 0)
    entries = [item("numeric-" + str(n)) for n in range(offset, min(offset + 32, 35))]
    return {"protocolVersion": 1, "requestId": request["requestId"],
        "sessionId": "run-one", "editorId": "editor-one", "status": "OK",
        "result": {"revision": 3, "contextId": "context-one", "items": entries,
                   "total": 35, "nextOffset": 32 if offset == 0 else None}}


def test_catalogue_pages_preserve_one_context(peer):
    server = peer(page)
    result = Client(server.path).catalog(target(), context_id="context-one")
    assert result["contextId"] == "context-one" and len(result["items"]) == 35
    assert [r["offset"] for r in server.requests] == [0, 32]
    assert all(r["contextId"] == "context-one" and r["baseRevision"] == 3 for r in server.requests)
    assert len({entry["key"] for entry in result["items"]}) == 35


@pytest.mark.parametrize("corruption", [
    lambda r: r["result"].update(contextId="wrong-context"),
    lambda r: r["result"].update(revision=4),
    lambda r: r["result"].update(nextOffset=0),
    lambda r: r["result"]["items"][0].update(min=True),
    lambda r: r["result"]["items"][0].update(available=[]),
    lambda r: r["result"]["items"][0].update(value=float("inf")),
])
def test_invalid_catalogue_never_mutates(peer, corruption):
    def handler(request):
        result = page(request)
        corruption(result)
        return result
    server = peer(handler)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).catalog(target(), context_id="context-one")
    assert error.value.code == "PROTOCOL_ERROR"
    assert all(r["op"] == "list_params" for r in server.requests)


def numeric_applied(request):
    result = applied(request)
    result["result"]["effectiveParams"] = {"numeric-1": 20}
    result["result"]["enabledTools"] = ["saturation"]
    return result


def test_numeric_mutation_uses_explicit_context_and_activation(peer):
    server = peer(numeric_applied)
    result = Client(server.path).set_numeric(target(), "numeric-1", 20,
        context_id="context-one", enable_tool=True, request_id="numeric-once")
    assert result["result"]["effectiveParams"] == {"numeric-1": 20}
    assert server.requests == [{"protocolVersion": 1, "requestId": "numeric-once",
        "op": "set_param", "sessionId": "run-one", "editorId": "editor-one",
        "baseRevision": 3, "params": {"numeric-1": 20},
        "contextId": "context-one", "enableTool": True}]


@pytest.mark.parametrize("value", [True, "20", float("nan"), float("inf")])
def test_invalid_numeric_value_does_not_connect(peer, value):
    server = peer()
    with pytest.raises(ValueError):
        Client(server.path).set_numeric(target(), "numeric-1", value,
            context_id="context-one", enable_tool=True)
    assert server.requests == []


def test_numeric_mutation_is_not_retried_on_missing_ack(peer):
    server = peer(lambda request: None)
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_numeric(target(), "numeric-1", 20,
            context_id="context-one", enable_tool=True, request_id="numeric-once")
    assert error.value.code == "OUTCOME_UNKNOWN"
    assert error.value.request_id == "numeric-once" and len(server.requests) == 1


def test_acknowledgement_cannot_change_the_requested_key(peer):
    server = peer(lambda request: applied(request))
    with pytest.raises(LiveParamError) as error:
        Client(server.path).set_numeric(target(), "numeric-1", 20,
            context_id="context-one", enable_tool=True)
    assert error.value.code == "OUTCOME_UNKNOWN" and len(server.requests) == 1
