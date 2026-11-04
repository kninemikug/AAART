"""GUI 생성 단계들이 요청의 남은 시간을 함께 사용한다."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from artagent import answer, gui_bridge
from artagent.graph import create_answer_node, create_search_nodes


def test_gui_retry_returns_structured_failure_before_outer_timeout(monkeypatch):
    elapsed = [0.0]
    timeouts = []
    durations = iter([110, 110, 100])
    question = "노출 보정 방법을 알려줘"
    responses = iter([
        {"status": "INSUFFICIENT_EVIDENCE", "answer": "부족합니다.", "citation_ids": []},
        {"answer": question, "citation_ids": []},
        {"status": "INSUFFICIENT_EVIDENCE", "answer": "아직 부족합니다.", "citation_ids": []},
    ])
    monkeypatch.setattr(answer, "monotonic", lambda: elapsed[0], raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex")
    monkeypatch.setattr(answer, "_get_codex_version", lambda binary: "test-version")

    def run(command, *, timeout, **kwargs):
        timeouts.append(timeout)
        duration = next(durations)
        if duration > timeout:
            elapsed[0] += timeout
            raise subprocess.TimeoutExpired(command, timeout)
        elapsed[0] += duration
        raw = json.dumps(next(responses))
        Path(command[command.index("-o") + 1]).write_text(raw)
        events = [
            {"type": "thread.started", "thread_id": "budget-test"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": raw}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
        return SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, events)), stderr="")

    monkeypatch.setattr(answer.subprocess, "run", run)
    store = SimpleNamespace(search=MagicMock(return_value=[]))
    nodes = create_search_nodes(store, None)
    observations = []
    response = gui_bridge.process_request(
        {"version": 1, "request_id": "budget", "text": question},
        lambda: gui_bridge.create_gui_graph(
            Path("unused"), Path("unused"), Path.cwd(), search_nodes=nodes,
            answer_node=create_answer_node(observe=observations.append),
        ),
    )
    assert elapsed[0] == 270
    assert timeouts == [120, 120, 50]
    assert response["status"] == "FAILED"
    assert response["steps"][0]["error"]["code"] == "ANSWER_GENERATION_FAILED"
    assert store.search.call_count == 2
    assert observations[-1]["trace"]["process_error"]["timeout_seconds"] == 50


def test_version_probe_uses_remaining_time_and_exhaustion_never_sends_request(monkeypatch):
    from artagent.answer import generation_time_budget

    elapsed = [0.0]
    monkeypatch.setattr(answer, "monotonic", lambda: elapsed[0])
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex")
    calls = []

    def run(command, *, timeout, **kwargs):
        assert command[-1] == "--version"
        calls.append(timeout)
        elapsed[0] += timeout
        return SimpleNamespace(returncode=0, stdout="test-version", stderr="")

    monkeypatch.setattr(answer.subprocess, "run", run)
    observations = []
    with generation_time_budget(4):
        with pytest.raises(TimeoutError):
            answer.generate_llm_response("sys", "user", {}, "q", observe_request=observations.append)
    assert calls == [4]
    assert observations == []


def test_api_timeout_budget_is_scoped_and_nested_budget_does_not_extend_it(monkeypatch):
    from artagent.answer import generation_time_budget

    elapsed = [0.0]
    monkeypatch.setattr(answer, "monotonic", lambda: elapsed[0])
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost/test")
    monkeypatch.setenv("LLM_API_KEY", "test-only")
    monkeypatch.setattr(answer.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("테스트에서 네트워크 전송 금지"))
    timeouts = []

    def read_response(request, timeout):
        timeouts.append(timeout)
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "answer": "응답", "citation_ids": [],
        })}}]})

    monkeypatch.setattr(answer, "_read_api_response", read_response, raising=False)
    with generation_time_budget(30):
        elapsed[0] = 20
        with generation_time_budget(100):
            answer.generate_llm_response("sys", "user", {}, "q")
        elapsed[0] = 30
        with pytest.raises(TimeoutError):
            answer.generate_llm_response("sys", "user", {}, "q")
    answer.generate_llm_response("sys", "user", {}, "q")
    assert timeouts == [10, 60]


def test_budget_covers_entire_api_response_worker(monkeypatch):
    from artagent.answer import generation_time_budget

    # 응답 본문이 끝나지 않는 전송을 별도 프로세스에서 재현한다.
    monkeypatch.setattr(answer, "_API_RESPONSE_WORKER", "import sys,time; sys.stdin.read(); time.sleep(2)", raising=False)
    request = answer.urllib.request.Request("http://unused.test", data=b"{}")
    with generation_time_budget(0.05):
        with pytest.raises(subprocess.TimeoutExpired):
            answer._read_api_response(request, 60)


@pytest.mark.parametrize("stdout_encoding", ["utf-8", "ascii"])
def test_api_worker_preserves_body_and_keeps_headers_off_command_line(tmp_path, monkeypatch, stdout_encoding):
    from artagent.answer import generation_time_budget

    body = tmp_path / "response.json"
    body.write_text('{"response":"전송 확인"}', encoding="utf-8")
    monkeypatch.setattr(answer, "_API_RESPONSE_WORKER", (
        f"import sys; sys.stdout.reconfigure(encoding={stdout_encoding!r})\n" + answer._API_RESPONSE_WORKER
    ))
    request = answer.urllib.request.Request(body.as_uri(), headers={"Authorization": "private-header"})
    run = answer.subprocess.run
    commands = []

    def observe(command, **kwargs):
        commands.append(command)
        assert "private-header" not in " ".join(command)
        return run(command, **kwargs)

    monkeypatch.setattr(answer.subprocess, "run", observe)
    with generation_time_budget(5):
        assert answer._read_api_response(request, 60) == body.read_text(encoding="utf-8")
    assert len(commands) == 1
