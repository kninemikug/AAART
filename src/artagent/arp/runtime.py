"""Use the existing runtime stack, with no tools, fallback or generation retry."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import urllib.request
import urllib.error


class RuntimeFailure(RuntimeError):
    """A failed invocation, retaining raw output and process evidence for evaluation."""

    def __init__(self, message: str, metadata: dict | None = None, raw_response: str = ""):
        super().__init__(message)
        self.metadata = metadata or {}
        self.raw_response = raw_response


def _text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def validate_evidence(metadata: dict, raw_response: str) -> Any:
    """Independently verify a saved invocation, never trusting a stored pass flag."""
    from .generator import strict_json

    if type(metadata.get("call_count")) is not int or metadata["call_count"] != 1 or metadata.get("timeout"):
        raise ValueError("Expected one completed invocation")
    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ValueError("Missing final response")
    if metadata.get("provider") == "openai-compatible":
        data = metadata.get("response_body")
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or len(data["choices"]) != 1:
            raise ValueError("Expected exactly one API response choice")
        choice = data["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("Invalid API message shape")
        message = choice["message"]
        if choice.get("finish_reason") != "stop" or message.get("tool_calls") or message.get("function_call") or message.get("content") != raw_response:
            raise ValueError("Incomplete API response or unexpected tool call")
        return data.get("usage")
    if metadata.get("provider") != "codex-cli" or type(metadata.get("returncode")) is not int or metadata["returncode"] != 0:
        raise ValueError("Missing successful Codex process evidence")
    stdout = metadata.get("stdout_jsonl")
    if not isinstance(stdout, str):
        raise ValueError("Missing event stream")
    lifecycle, messages, usage = [], [], None
    known = {"thread.started", "turn.started", "turn.completed", "item.started", "item.updated", "item.completed"}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = strict_json(line)
        if not isinstance(event, dict) or event.get("type") not in known:
            raise ValueError("Unexpected/failed runtime event")
        kind = event["type"]
        if kind in ("thread.started", "turn.started", "turn.completed"):
            lifecycle.append(kind)
        if kind.startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") not in ("agent_message", "reasoning"):
                raise ValueError("Tool/unrecognized runtime item")
            if kind == "item.completed" and item["type"] == "agent_message":
                messages.append(item.get("text"))
        if kind == "turn.completed":
            usage = event.get("usage")
    if lifecycle != ["thread.started", "turn.started", "turn.completed"]:
        raise ValueError("Incomplete or repeated runtime lifecycle")
    if not messages or not isinstance(messages[-1], str) or messages[-1].strip() != raw_response.strip():
        raise ValueError("Final message/output file missing or inconsistent")
    return usage


def validate_failure_evidence(metadata: dict, raw_response: Any) -> str:
    """Reconstruct a runtime failure from captured evidence, not a stored status."""
    if type(metadata.get("call_count")) is not int or metadata["call_count"] != 1:
        raise ValueError("Missing failed invocation count")
    if metadata.get("provider") == "openai-compatible":
        if "response_body" not in metadata:
            transport = metadata.get("transport_error")
            if isinstance(transport, dict) and transport.get("kind") == "http":
                status = transport.get("status")
                if type(status) is int and 400 <= status <= 599:
                    return "Compatible API invocation failed (HTTPError)"
            if isinstance(transport, dict) and transport.get("kind") == "network":
                if transport.get("exception") in ("URLError", "TimeoutError", "ConnectionError", "ConnectionResetError", "OSError", "SSLError", "RemoteDisconnected"):
                    return f"Compatible API invocation failed ({transport['exception']})"
            if isinstance(metadata.get("response_text"), str):
                from .generator import strict_json
                try:
                    strict_json(metadata["response_text"])
                except ValueError as exc:
                    return f"Compatible API invocation failed ({type(exc).__name__})"
            raise ValueError("Missing failed API response evidence")
        try:
            validate_evidence(metadata, raw_response)
        except ValueError:
            return "Compatible API invocation failed (ValueError)"
        raise ValueError("API evidence describes a successful invocation")
    if metadata.get("provider") != "codex-cli" or not isinstance(raw_response, str):
        raise ValueError("Unknown failed invocation")
    if not all(isinstance(metadata.get(key), str) for key in ("stdout_jsonl", "stderr")):
        raise ValueError("Missing failed process capture")
    if metadata.get("timeout") is True:
        if type(metadata.get("timeout_seconds")) is not int or metadata["timeout_seconds"] <= 0:
            raise ValueError("Missing timeout bound")
        return "Runtime timeout"
    code = metadata.get("returncode")
    if type(code) is not int:
        raise ValueError("Missing failed process exit status")
    if code != 0:
        return f"codex process failed: exit {code}"
    try:
        validate_evidence(metadata, raw_response)
    except ValueError as exc:
        return str(exc)
    raise ValueError("Process evidence describes a successful invocation")


def _codex(prompt: str) -> dict:
    model = os.getenv("LLM_MODEL") or os.getenv("CODEX_MODEL") or "gpt-5.6-sol"
    metadata: dict[str, Any] = {"provider": "codex-cli", "model": model, "call_count": 0,
                               "timeout_seconds": 120, "tools_enabled": False}
    raw = ""
    try:
        executable = shutil.which("codex")
        if not executable:
            metadata["fatal_infrastructure"] = True
            raise ValueError("codex executable not found")
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
        if version.returncode != 0:
            metadata["fatal_infrastructure"] = True
            raise ValueError("Cannot identify codex version")
        metadata["cli_version"] = version.stdout.strip()
        with tempfile.TemporaryDirectory(prefix="t19-runtime-") as workdir:
            output = Path(workdir) / "response.json"
            command = [executable, "exec", "-m", model, "-C", workdir,
                       "--sandbox", "read-only", "--ignore-user-config", "--skip-git-repo-check",
                       "--ephemeral", "--json", "-c", "features.shell_tool=false",
                       "-c", "features.unified_exec=false", "-c", 'web_search="disabled"',
                       "-o", str(output), "-"]
            metadata["call_count"] = 1
            process = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=120)
            metadata.update(returncode=process.returncode, stdout_jsonl=process.stdout, stderr=process.stderr)
            if output.is_file():
                raw = output.read_text(encoding="utf-8")
            if process.returncode != 0:
                metadata["fatal_infrastructure"] = True
                raise ValueError(f"codex process failed: exit {process.returncode}")
        metadata["usage"] = validate_evidence(metadata, raw)
        metadata["evidence_verified"] = True
        return {"raw_response": raw, "metadata": metadata}
    except subprocess.TimeoutExpired as exc:
        metadata.update(stdout_jsonl=_text(exc.stdout), stderr=_text(exc.stderr), timeout=True)
        raise RuntimeFailure("Runtime timeout", metadata, raw) from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeFailure(str(exc), metadata, raw) from exc


def _compatible_api(prompt: str) -> dict:
    """Honor the already-supported explicit compatible API configuration."""
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.6-sol"
    base = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    metadata = {"provider": "openai-compatible", "model": model, "call_count": 0,
                "tools_enabled": False, "timeout_seconds": 60, "temperature": 0}
    raw = ""
    try:
        if not key and not base:
            metadata["fatal_infrastructure"] = True
            raise ValueError("Compatible API configuration is missing")
        url = base.rstrip("/") + "/chat/completions" if base else "https://api.openai.com/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                "temperature": 0, "response_format": {"type": "json_object"}}
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        metadata["call_count"] = 1
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata["response_text"] = _text(response.read())
        from .generator import strict_json
        data = strict_json(metadata["response_text"])
        metadata["response_body"] = data
        if isinstance(data, dict) and isinstance(data.get("choices"), list) and len(data["choices"]) == 1:
            choice = data["choices"][0]
            if isinstance(choice, dict) and isinstance(choice.get("message"), dict):
                raw = choice["message"].get("content")
        metadata["usage"] = validate_evidence(metadata, raw)
        return {"raw_response": raw, "metadata": metadata}
    except urllib.error.HTTPError as exc:
        metadata["transport_error"] = {"kind": "http", "status": exc.code}
        raise RuntimeFailure("Compatible API invocation failed (HTTPError)", metadata, raw) from exc
    except OSError as exc:
        metadata["transport_error"] = {"kind": "network", "exception": type(exc).__name__}
        raise RuntimeFailure(f"Compatible API invocation failed ({type(exc).__name__})", metadata, raw) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeFailure(f"Compatible API invocation failed ({type(exc).__name__})", metadata, raw) from exc


def generate(prompt: str) -> dict:
    """Invoke the explicitly selected existing provider once."""
    provider = os.getenv("LLM_PROVIDER", "codex").strip().lower()
    if provider == "codex":
        return _codex(prompt)
    if provider in ("openai", "openai-compatible"):
        return _compatible_api(prompt)
    raise RuntimeFailure(f"Unsupported runtime provider: {provider}")
