"""Runtime boundary tests: process evidence, tools, timeout and provider selection."""

import json
import io
from pathlib import Path
import subprocess

import pytest

from artagent.arp.runtime import RuntimeFailure, generate, validate_evidence


RAW = '{"groups":{"Exposure":{"Compensation":0.3}},"reason":"test"}'


def events(extra=None, final=RAW):
    rows = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}]
    if extra:
        rows.append(extra)
    rows.extend([{"type": "item.completed", "item": {"type": "agent_message", "text": final}},
                 {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 10}}])
    return "\n".join(json.dumps(row) for row in rows)


@pytest.fixture
def process(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-sol")
    monkeypatch.setattr("artagent.arp.runtime.shutil.which", lambda name: "/test/codex")
    def install(stdout=None, code=0, output=RAW, timeout=False):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "codex-cli test", "")
            if timeout:
                raise subprocess.TimeoutExpired(command, 120, output=b"partial", stderr=b"timeout")
            if output is not None:
                Path(command[command.index("-o") + 1]).write_text(output)
            return subprocess.CompletedProcess(command, code, stdout or events(), "diagnostic")
        monkeypatch.setattr("artagent.arp.runtime.subprocess.run", run)
    return calls, install


def test_runtime_policy_and_evidence(process):
    calls, install = process
    install()
    reply = generate("test input")
    assert reply["raw_response"] == RAW
    assert reply["metadata"]["model"] == "gpt-5.6-sol"
    assert reply["metadata"]["cli_version"] == "codex-cli test"
    assert reply["metadata"]["usage"]["input_tokens"] == 10
    command, kwargs = calls[-1]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command and "--ephemeral" in command
    assert "features.shell_tool=false" in command
    assert "features.unified_exec=false" in command
    assert 'web_search="disabled"' in command
    assert kwargs["input"] == "test input"
    assert "shell" not in kwargs


@pytest.mark.parametrize("options", [
    {"code": 1}, {"output": None}, {"output": "{}"}, {"timeout": True},
    {"stdout": "broken json"},
    {"stdout": events({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}})},
    {"stdout": events({"type": "error", "message": "failure"})},
    {"stdout": events().replace('"turn.completed"', '"turn.failed"')},
    {"stdout": events({"type": "turn.started"})},
])
def test_failed_evidence_rejects_without_retry(process, options):
    calls, install = process
    install(**options)
    with pytest.raises(RuntimeFailure) as exc:
        generate("test input")
    assert exc.value.metadata["model"] == "gpt-5.6-sol"
    assert len([cmd for cmd, _ in calls if "exec" in cmd]) == 1


def test_no_provider_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(RuntimeFailure, match="provider"):
        generate("test")


@pytest.mark.parametrize("mutation", [
    {"returncode": 99}, {"call_count": 9}, {"timeout": True},
    {"stdout_jsonl": events({"type": "item.completed", "item": {"type": "command_execution"}})},
    {"stdout_jsonl": "broken"},
])
def test_saved_evidence_is_independently_validated(mutation):
    metadata = {"provider": "codex-cli", "model": "test", "returncode": 0, "call_count": 1,
                "stdout_jsonl": events(), "evidence_verified": True, **mutation}
    with pytest.raises(ValueError):
        validate_evidence(metadata, RAW)


@pytest.mark.parametrize("message", [None, [], "bad", {"content": "partial", "tool_calls": [{}]}])
def test_invalid_api_response_is_a_runtime_failure(monkeypatch, message):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    payload = {"choices": [{"message": message, "finish_reason": "stop"}]}
    monkeypatch.setattr("artagent.arp.runtime.urllib.request.urlopen",
                        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeFailure):
        generate("test")
