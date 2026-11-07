"""GUI bridge contracts against the real router, without external services."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from artagent import gui_bridge
from artagent.graph import AnswerResult, Citation, ErrorInfo, create_search_nodes


def make_graph(status="SUPPORTED", calls=None):
    """Keep routing real while substituting retrieval and answer generation."""
    calls = calls if calls is not None else []

    def search(query, session, **filters):
        calls.append("search")
        return []

    def answer(state):
        calls.append("answer")
        return {"answer": AnswerResult(
            status, "검증된 답변" if status == "SUPPORTED" else "근거가 부족합니다.",
            [Citation("doc", "문서", "https://example.org/docs", "section")]
            if status == "SUPPORTED" else [],
        )}

    return gui_bridge.create_gui_graph(
        Path("missing-reference"), Path("missing-store"), Path.cwd(),
        search_nodes=create_search_nodes(SimpleNamespace(search=search), None),
        answer_node=answer,
        research_generate=lambda prompt: prompt.split("User Query:\n", 1)[1].split("\n", 1)[0],
    )


def request(text="노출 보정 방법을 알려줘"):
    return {"version": 1, "request_id": "gui-1", "text": text}


def test_answer_and_citations_cross_process_boundary():
    result = gui_bridge.process_request(request(), make_graph)
    assert result["status"] == "COMPLETED"
    assert result["request_id"] == "gui-1"
    assert result["steps"][0]["text"] == "검증된 답변"
    assert result["citations"][0]["url"] == "https://example.org/docs"
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


def test_execute_does_not_require_retrieval_or_rendering():
    calls = []
    result = gui_bridge.process_request(
        request("노출 보정을 적용해줘"), lambda: make_graph(calls=calls),
    )
    assert result["status"] == "UNSUPPORTED"
    assert "아직 미지원" in result["steps"][0]["error"]["message"]
    assert calls == []
    assert result["steps"][0]["text"] == ""


def test_mixed_request_keeps_answer_out_of_execute_step():
    result = gui_bridge.process_request(
        request("노출 조절 방법도 알려주고 노출 보정을 적용해줘"), make_graph,
    )
    assert result["status"] == "PARTIAL"
    assert [step["path"] for step in result["steps"]] == ["DOC_QA", "EXECUTE"]
    assert result["steps"][0]["text"] == "검증된 답변"
    assert result["steps"][1]["text"] == ""
    assert result["steps"][1]["citations"] == []


def test_insufficient_evidence_retries_once_and_preserves_semantic_state():
    calls = []
    result = gui_bridge.process_request(
        request(), lambda: make_graph("INSUFFICIENT_EVIDENCE", calls),
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert calls == ["search", "answer", "search", "answer"]
    assert result["steps"][0]["error"] is None


def test_clarification_is_a_response_without_completed_steps():
    result = gui_bridge.process_request(request("사진이 노래요. 봐주세요"), make_graph)
    assert result["status"] == "WAITING_CLARIFICATION"
    assert "다시 입력" in result["message"]


@pytest.mark.parametrize("payload", [
    None, [], {}, {"version": True, "request_id": "1", "text": "question"},
    request(" "), request("x" * 8193), request("hello\x00world"),
    {"version": 1, "request_id": "", "text": "question"},
])
def test_invalid_input_never_initializes_graph(payload):
    def forbidden():
        pytest.fail("Invalid input initialized graph")

    result = gui_bridge.process_request(payload, forbidden)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "INVALID_INPUT"


def test_questions_have_independent_graph_state():
    graph = make_graph()
    first = gui_bridge.process_request(request(), lambda: graph)
    second = gui_bridge.process_request(request("노출 보정을 적용해줘"), lambda: graph)
    assert first["citations"]
    assert second["citations"] == []
    assert len(second["steps"]) == 1


def test_protocol_errors_are_structured_json(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO("{invalid"))
    monkeypatch.setattr("sys.stdout", output)
    assert gui_bridge.main([]) == 1
    assert json.loads(output.getvalue())["error"]["code"] == "INVALID_INPUT"


def test_generation_diagnostics_are_not_exposed_in_gui():
    graph = gui_bridge.create_gui_graph(
        Path("missing"), Path("missing"), Path.cwd(),
        search_nodes={"SEARCH_RAWPEDIA": lambda state: {}},
        answer_node=lambda state: {"error": ErrorInfo(
            "ANSWER_GENERATION_FAILED", "Authorization: Bearer private-value",
            "ANSWER",
        )},
    )
    result = gui_bridge.process_request(request(), lambda: graph)
    assert result["status"] == "FAILED"
    assert "private-value" not in json.dumps(result)
    assert result["steps"][0]["error"]["code"] == "ANSWER_GENERATION_FAILED"


def test_missing_store_is_not_silently_created(tmp_path):
    store = tmp_path / "absent-store"
    root = Path(__file__).resolve().parents[1]
    graph = gui_bridge.create_gui_graph(
        root / "docs/T08_2_t9_handoff_reference.json", store, root,
    )
    result = gui_bridge.process_request(request(), lambda: graph)
    assert result["steps"][0]["error"]["code"] == "SEARCH_UNAVAILABLE"
    assert not store.exists()


def test_main_keeps_diagnostics_off_protocol_stdout(monkeypatch, capsys):
    output = io.StringIO()
    graph = make_graph()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request())))
    monkeypatch.setattr("sys.stdout", output)

    def factory(*args):
        print("initialization diagnostic")
        return graph

    monkeypatch.setattr(gui_bridge, "create_gui_graph", factory)
    assert gui_bridge.main([]) == 0
    assert json.loads(output.getvalue())["status"] == "COMPLETED"
    assert "initialization diagnostic" in capsys.readouterr().err
