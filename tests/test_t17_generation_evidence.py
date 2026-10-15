"""The captured request must be the request actually sent, including failures."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from artagent.answer import GenerationError, generate_llm_response
from artagent.graph.answer import answer_standalone
from artagent.graph.state import RetrievalBundle


def test_codex_captures_exact_request_and_output_file(monkeypatch):
    from pathlib import Path

    response = {"status": "INSUFFICIENT_EVIDENCE", "answer": "모르겠습니다.", "citation_ids": []}
    raw_file = json.dumps(response, ensure_ascii=False) + "\n"
    events = [
        {"type": "thread.started", "thread_id": "capture-test"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": raw_file}},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]
    captured = []
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("artagent.answer._get_codex_version", lambda _: "test-version")

    def run(command, **kwargs):
        assert captured[0]["call_count"] == 1
        assert captured[0]["request"]["full_prompt"] == command[-1]
        assert "키: status, answer, citation_ids" in command[-1]
        Path(command[command.index("-o") + 1]).write_text(raw_file)
        return SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, events)), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    _, _, meta = generate_llm_response(
        "system", "user", {}, "query", prompt_version="t17-answer-v2",
        response_schema="t17-answer-v1", observe_request=captured.append,
    )
    assert meta["_output_file_content"] == raw_file
    assert captured[0]["request"]["response_schema"] == "t17-answer-v1"


@pytest.mark.parametrize("entered", [False, True])
def test_generation_attempt_count_is_observed_before_call(monkeypatch, entered):
    def fail(*args, **kwargs):
        if entered:
            kwargs["observe_request"]({"call_count": 1, "request": {"kind": "codex", "full_prompt": "sent"}})
        raise GenerationError("failed", trace={"stderr": "diagnostic"}, raw_response="partial")

    monkeypatch.setattr("artagent.graph.answer.generate_llm_response", fail)
    observations = []
    answer, error = answer_standalone("q", RetrievalBundle("q", "RAWPEDIA", []), observe=observations.append)
    assert answer is None and error.code == "ANSWER_GENERATION_FAILED"
    assert len(observations) == 1
    assert observations[0]["call_count"] == int(entered)
    assert observations[0]["trace"] == {"stderr": "diagnostic"}
    assert observations[0]["raw_response"] == "partial"


def test_invalid_input_never_records_a_generation_attempt():
    observations = []
    _, error = answer_standalone("", None, observe=observations.append)
    assert error.code == "ANSWER_INPUT_INVALID"
    assert observations[0]["call_count"] == 0
    assert observations[0]["request"] is None


def test_custom_generator_records_attempt_without_impersonating_live():
    observations = []
    answer, error = answer_standalone(
        "q", RetrievalBundle("q", "RAWPEDIA", []),
        generate=lambda prompt: json.dumps({"status": "INSUFFICIENT_EVIDENCE", "answer": "모르겠습니다.", "citation_ids": []}),
        observe=observations.append,
    )
    assert error is None and answer is not None
    assert observations[0]["call_count"] == 1
    assert observations[0]["custom_generation"] is True


def test_api_captures_sent_payload_without_authorization_header(monkeypatch):
    from artagent.retrieval.provenance import canonical_json_str, sha256_str

    captured = []
    answer = {"status": "INSUFFICIENT_EVIDENCE", "answer": "모르겠습니다.", "citation_ids": []}
    response = {"choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(response).encode()

    def open_request(request, **kwargs):
        assert captured[0]["request"]["payload"] == json.loads(request.data)
        assert "Authorization" not in json.dumps(captured)
        return Response()

    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost/test")
    monkeypatch.setenv("LLM_API_KEY", "test-secret-never-record")
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    _, _, meta = generate_llm_response(
        "sys", "user", {}, "q", prompt_version="t17-answer-v2",
        response_schema="t17-answer-v1", observe_request=captured.append,
    )
    request = captured[0]["request"]
    assert request["sha256"] == sha256_str(canonical_json_str(request["payload"]))
    assert meta["_response_body"] == response
    assert "test-secret-never-record" not in json.dumps(captured)


def test_api_invalid_answer_preserves_received_body(monkeypatch):
    from io import BytesIO

    body = {"choices": [{"message": {"content": '{"status":'}, "finish_reason": "stop"}]}
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost/test")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: BytesIO(json.dumps(body).encode()))
    observations = []
    _, error = answer_standalone("q", RetrievalBundle("q", "RAWPEDIA", []), observe=observations.append)
    evidence = observations[0]
    assert error.code == "ANSWER_GENERATION_FAILED"
    assert evidence["call_count"] == 1
    assert evidence["raw_response"] == '{"status":'
    assert evidence["runtime_meta"]["_response_body"] == body
    assert evidence["runtime_meta"]["llm_provider"] == "openai-compatible"
