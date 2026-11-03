"""Exercise the public CLI as a real child process against Unix sockets."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_live_param import applied, peer, state


def cli(server, *arguments):
    root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-m", "artagent.live_param_cli", "--socket", str(server.path),
         *arguments], cwd=root, capture_output=True, text=True, timeout=5,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / "src")},
    )


def set_args(*more):
    return ["set", "--session", "run-one", "--editor", "editor-one",
            "--revision", "3", "--value", "0.125", *more]


def test_state_is_a_single_json_object(peer):
    server = peer(state)
    result = cli(server, "state", "--session", "run-one", "--editor", "editor-one")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["revision"] == 4
    assert len(server.requests) == 1


def test_set_preserves_actual_effective_value(peer):
    server = peer(applied)
    result = cli(server, *set_args("--request-id", "cli-apply"))
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["requestId"] == "cli-apply"
    assert response["result"]["effectiveParams"]["Exposure.Compensation"] == 0.13
    assert response["result"]["previewStatus"] == "PENDING"


def test_wait_and_status_use_original_mutation_id(peer):
    def handler(request):
        if request["op"] == "set_param":
            return applied(request)
        return state(request, lastMutation={"requestId": "cli-apply", "appliedRevision": 4,
                     "previewStatus": "READY"}, mutationStatus="READY")
    server = peer(handler)
    result = cli(server, *set_args("--request-id", "cli-apply", "--wait"))
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["status"] == "READY"
    assert response["state"]["result"]["renderedRevision"] == 4
    result = cli(server, "status", "--session", "run-one", "--editor", "editor-one",
                 "--mutation", "cli-apply")
    assert result.returncode == 0
    assert json.loads(result.stdout)["result"]["mutationStatus"] == "READY"
    assert sum(r["op"] == "set_param" for r in server.requests) == 1


@pytest.mark.parametrize("arguments", [
    ["set", "--value", "0.5"],
    ["set", "--session", "run-one", "--editor", "editor-one", "--revision", "-1", "--value", "0"],
    set_args("--wait-timeout", "nan"),
])
def test_invalid_cli_input_never_connects(peer, arguments):
    server = peer()
    result = cli(server, *arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert server.requests == []


def test_lost_ack_is_a_partial_unknown_result(peer):
    server = peer(lambda request: None)
    result = cli(server, *set_args("--request-id", "lost-ack"))
    assert result.returncode == 3
    response = json.loads(result.stdout)
    assert response["status"] == "PARTIAL"
    assert response["error"]["code"] == "OUTCOME_UNKNOWN"
    assert response["error"]["requestId"] == "lost-ack"
    assert len(server.requests) == 1
