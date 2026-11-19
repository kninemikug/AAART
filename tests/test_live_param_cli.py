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


def _probe_cmd(tmp_path, *args):
    root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(root / "scripts/live_param_perf_probe.py"), *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _make_perf_dir(base_dir: Path, *, batch: int = 1, trace_enabled: bool = False,
                   params=("saturation",), repeats: int = 1, warm: int = 1,
                   drop_cell=None, override_status=None, duplicate_req: bool = False,
                   app_sha: str = "binsha-aaa"):
    base_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": f"test-b{batch}",
        "run_type": "perf_benchmark",
        "variant": "candidate",
        "git_commit": "deadbeef",
        "git_dirty": False,
        "common_trace_patch_sha256": None,
        "app_binary_sha256": app_sha,
        "raw_file_sha256": "rawsha-1",
        "profile_sha256": {"hdr0_dn0": "p0", "hdr0_dn1": "p1", "hdr1_dn0": "p2", "hdr1_dn1": "p3"},
        "parameters": list(params),
        "batches": [batch],
        "repeats_per_batch": repeats,
        "warm_repeats_per_batch": warm,
        "core_boost_per_batch": 0,
        "mode": "persistent",
        "poll_interval_s": 0.003,
        "startup_quiet_window_s": 0.05,
        "trace_enabled": trace_enabled,
    }
    (base_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    samples = []
    trace_lines = []
    cmd_id = 0
    gen = 10
    rev = 0
    t_ns = 1_000_000_000
    for hdr in (0, 1):
        for dn in (0, 1):
            for zoom in ("fit", "100"):
                for p in params:
                    for cache_mode, cnt in (("initial", repeats), ("cached", warm)):
                        prefix = "init" if cache_mode == "initial" else "cache"
                        cell_id = f"{p}_{zoom}_{prefix}_hdr{hdr}_dn{dn}"
                        if drop_cell and cell_id == drop_cell:
                            continue
                        for r in range(cnt):
                            cmd_id += 1
                            gen += 1
                            rev += 1
                            t_ns += 50_000_000
                            req_id = f"req-b{batch}-{cell_id}-{r}"
                            if duplicate_req and len(samples) == 1:
                                req_id = samples[0]["requestId"]
                            st = "READY"
                            err = None
                            if override_status and override_status(cell_id, r, len(samples)):
                                st = "TIMEOUT"
                                err = "TIMEOUT"
                            row = {
                                "requestId": req_id,
                                "sessionId": f"run-s{batch}",
                                "editorId": f"ed-s{batch}",
                                "param": p,
                                "paramKey": "Saturation.Saturation",
                                "val": 10.0 + r,
                                "effectiveValue": 10.0 + r,
                                "baseRevision": rev - 1,
                                "appliedRevision": rev,
                                "viewRevision": 4,
                                "finalViewRevision": 4,
                                "renderedRevision": rev,
                                "renderedViewRevision": 4,
                                "status": st,
                                "error": err,
                                "applied_rtt_ms": 20.0,
                                "ready_rtt_ms": 150.0 if st == "READY" else None,
                                "polls": 5,
                                "c0": t_ns,
                                "ca": t_ns + 20_000_000,
                                "cr": (t_ns + 150_000_000) if st == "READY" else None,
                                "phase": "core_matrix",
                                "batch": batch,
                                "cell_id": cell_id,
                                "zoom": zoom,
                                "cache": cache_mode,
                                "hdr": hdr,
                                "denoise": dn,
                            }
                            samples.append(row)
                            if trace_enabled and st == "READY":
                                for idx, ev_name in enumerate(("S0", "SQ", "SG", "SA", "SP", "SS", "SN", "SC", "SR")):
                                    ev_obj = {
                                        "event": ev_name,
                                        "timestamp_ns": t_ns + idx * 1_000_000,
                                        "cmdId": cmd_id,
                                        "requestId": req_id,
                                        "sessionId": f"run-s{batch}",
                                    }
                                    if ev_name in ("SA", "SN", "SC", "SR"):
                                        ev_obj.update({
                                            "editorId": f"ed-s{batch}",
                                            "editRev": rev,
                                            "viewRev": 4,
                                            "generation": gen,
                                        })
                                    trace_lines.append(json.dumps(ev_obj))

    (base_dir / "client.jsonl").write_text(
        "\n".join(json.dumps(s) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    if samples:
        import csv
        with open(base_dir / "samples.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(samples[0].keys()))
            writer.writeheader()
            writer.writerows(samples)
    if trace_enabled:
        (base_dir / "trace.jsonl").write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
    return manifest


def test_probe_rejects_empty_timeout_incomplete_missing_and_duplicate_batch(tmp_path):
    # 1. Valid trace_enabled=False and trace_enabled=True complete runs must pass
    valid_off = tmp_path / "valid_off"
    _make_perf_dir(valid_off, batch=1, trace_enabled=False)
    res = _probe_cmd(tmp_path, "--validate-dir", str(valid_off))
    assert res.returncode == 0, res.stderr + res.stdout
    assert "log_integrity=PASSED, perf_run=PASSED" in res.stdout

    valid_on = tmp_path / "valid_on_b1"
    _make_perf_dir(valid_on, batch=1, trace_enabled=True)
    res = _probe_cmd(tmp_path, "--validate-dir", str(valid_on))
    assert res.returncode == 0, res.stderr + res.stdout

    # 2. 0 samples (empty client.jsonl) -> FAIL
    empty_dir = tmp_path / "empty"
    _make_perf_dir(empty_dir, batch=1, trace_enabled=False)
    (empty_dir / "client.jsonl").write_text("", encoding="utf-8")
    res = _probe_cmd(tmp_path, "--validate-dir", str(empty_dir))
    assert res.returncode != 0
    assert "perf_run=FAILED" in res.stderr

    # 3. Single TIMEOUT sample (0 READY) -> FAIL
    timeout_only = tmp_path / "timeout_only"
    _make_perf_dir(timeout_only, batch=1, trace_enabled=False,
                   override_status=lambda cid, r, idx: True)
    # Keep only the first TIMEOUT sample to specifically simulate 1 TIMEOUT-only sample
    first_line = (timeout_only / "client.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (timeout_only / "client.jsonl").write_text(first_line + "\n", encoding="utf-8")
    res = _probe_cmd(tmp_path, "--validate-dir", str(timeout_only))
    assert res.returncode != 0
    assert "0 READY" in res.stderr

    # 4. Partial incomplete (15 READY + 1 TIMEOUT) -> FAIL even with trace OFF
    partial_dir = tmp_path / "partial"
    _make_perf_dir(partial_dir, batch=1, trace_enabled=False,
                   override_status=lambda cid, r, idx: idx == 5)
    res = _probe_cmd(tmp_path, "--validate-dir", str(partial_dir))
    assert res.returncode != 0
    assert "non-READY sample" in res.stderr

    # 5. Missing condition (dropped cell) -> FAIL
    missing_cell = tmp_path / "missing_cell"
    _make_perf_dir(missing_cell, batch=1, trace_enabled=False,
                   drop_cell="saturation_fit_init_hdr0_dn0")
    res = _probe_cmd(tmp_path, "--validate-dir", str(missing_cell))
    assert res.returncode != 0
    assert "missing 1 planned condition" in res.stderr

    # 6. Duplicate requestId -> FAIL
    dup_req = tmp_path / "dup_req"
    _make_perf_dir(dup_req, batch=1, trace_enabled=False, duplicate_req=True)
    res = _probe_cmd(tmp_path, "--validate-dir", str(dup_req))
    assert res.returncode != 0
    assert "duplicate requestId" in res.stderr

    # 7. Duplicate batch in --merge-dirs -> FAIL
    b1_dup = tmp_path / "b1_dup"
    _make_perf_dir(b1_dup, batch=1, trace_enabled=True)
    merged_dup = tmp_path / "merged_dup"
    res = _probe_cmd(
        tmp_path, "--merge-dirs", f"{valid_on},{b1_dup}", "--output-dir", str(merged_dup)
    )
    assert res.returncode != 0
    assert "Duplicate batch id 1" in res.stderr

    # 8. Cross-batch binary hash mismatch in --merge-dirs -> FAIL
    b2_mismatch = tmp_path / "b2_mismatch"
    _make_perf_dir(b2_mismatch, batch=2, trace_enabled=True, app_sha="binsha-DIFFERENT")
    merged_mm = tmp_path / "merged_mm"
    res = _probe_cmd(
        tmp_path, "--merge-dirs", f"{valid_on},{b2_mismatch}", "--output-dir", str(merged_mm)
    )
    assert res.returncode != 0
    assert "Cross-batch mismatch for 'app_binary_sha256'" in res.stderr

    # 9. Valid multi-batch merge (batch 1 + batch 2) -> PASS with merged batches=[1, 2]
    b2_ok = tmp_path / "b2_ok"
    _make_perf_dir(b2_ok, batch=2, trace_enabled=True)
    merged_ok = tmp_path / "merged_ok"
    res = _probe_cmd(
        tmp_path, "--merge-dirs", f"{valid_on},{b2_ok}", "--output-dir", str(merged_ok)
    )
    assert res.returncode == 0, res.stderr + res.stdout
    mf_ok = json.loads((merged_ok / "manifest.json").read_text(encoding="utf-8"))
    assert mf_ok["batches"] == [1, 2]
    assert mf_ok["log_integrity_status"] == "PASSED"
    assert mf_ok["perf_run_status"] == "PASSED"

    # 10. Contract test run_type distinguishes explicit non-READY expectations and cannot merge
    ct_dir = tmp_path / "contract_load"
    ct_dir.mkdir()
    (ct_dir / "manifest.json").write_text(json.dumps({
        "run_type": "contract_test",
        "trace_enabled": False,
        "expected_ready_count": 1,
        "expected_statuses": {"ok-1": "READY", "busy-1": "ERROR"},
    }), encoding="utf-8")
    (ct_dir / "client.jsonl").write_text(
        json.dumps({"requestId": "ok-1", "status": "READY", "effectiveValue": 0.5,
                    "applied_rtt_ms": 10.0, "ready_rtt_ms": 90.0}) + "\n" +
        json.dumps({"requestId": "busy-1", "status": "ERROR"}) + "\n",
        encoding="utf-8",
    )
    res = _probe_cmd(tmp_path, "--validate-dir", str(ct_dir))
    assert res.returncode == 0, res.stderr + res.stdout
    assert "[contract_test]" in res.stdout
