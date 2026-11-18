#!/usr/bin/env python3
"""실시간 수치 조정 지연 측정 하네스 및 성능 프로브 (WBS §1.2~1.5 구현).

macOS Unix socket 상에서 실제 GUI 프로세스를 구동하고,
시나리오 매트릭스(노출, 채도, 색온도, 샤프닝 × 배율 × 캐시 × HDR × 노이즈제거)에 대해
클라이언트 RTT(C0, CA, CR) 및 서버 구간(S0, SQ, SG, SA, SP, SS, SN, SC, SR)을 수집하고
p50/p95 및 구간별 기여도를 분석하여 manifest.json, client.jsonl, trace.jsonl,
samples.csv, summary.csv를 생성한다.
"""

import argparse
from collections import Counter
import csv
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid

MAX_FRAME = 65536


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, math.ceil(p * len(s)) - 1))
    return s[idx]


def stage_bundle(repo_dir, src_bin_override=None, bundle_dir=None):
    root = Path(repo_dir).resolve()
    bundle = Path(bundle_dir).resolve() if bundle_dir else (root / "build/ARTLiveParamTest.app")
    macos = bundle / "Contents/MacOS"
    res = bundle / "Contents/Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)

    app_bin = macos / "test_liveparam_app"
    src_bin = Path(src_bin_override).resolve() if src_bin_override else (root / "build/rtgui/test_liveparam_app")
    if not src_bin.exists():
        src_bin = root / "build/rtgui/ART"
    if app_bin.exists() or app_bin.is_symlink():
        app_bin.unlink()
    app_bin.symlink_to(src_bin.resolve())

    info_plist = bundle / "Contents/Info.plist"
    info_plist.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key>
	<string>test_liveparam_app</string>
	<key>CFBundleIdentifier</key>
	<string>us.pixls.art.ART.liveparamtest</string>
	<key>CFBundleName</key>
	<string>ARTLiveParamTest</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>NSHighResolutionCapable</key>
	<true/>
</dict>
</plist>""")

    rtdata = root / "rtdata"
    subdirs = ["languages", "sounds", "iccprofiles", "dcpprofiles", "profiles",
               "themes", "ctlscripts", "luts"]
    for sd in subdirs:
        target = res / sd
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        target.symlink_to((rtdata / sd).resolve())

    files = ["cammatrices.json", "dcraw.json", "rt.json", "wbpresets.json", "dynamicprofile.cfg"]
    for fn in files:
        target = res / fn
        if target.is_symlink() or target.is_file():
            target.unlink()
        target.symlink_to((rtdata / fn).resolve())

    opt_target = res / "options"
    if opt_target.exists() or opt_target.is_symlink():
        opt_target.unlink()
    shutil.copy2(rtdata / "options/options.osx", opt_target)

    images_dst = res / "images"
    if images_dst.is_symlink() or images_dst.is_file():
        images_dst.unlink()
    elif images_dst.is_dir():
        shutil.rmtree(images_dst)
    images_dst.mkdir()
    for src_dir in [rtdata / "images", rtdata / "images/svg", rtdata / "images/png"]:
        if src_dir.exists():
            for f in src_dir.iterdir():
                if f.is_file() and not (images_dst / f.name).exists():
                    (images_dst / f.name).symlink_to(f.resolve())

    return app_bin


class LiveParamClient:
    def __init__(self, socket_path, persistent=True, timeout=15.0):
        self.socket_path = str(socket_path)
        self.persistent = persistent
        self.timeout = timeout
        self.sock = None
        self.stream = None
        if self.persistent:
            self._connect()

    def _connect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)
        self.stream = self.sock.makefile("rb")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.stream = None

    def rpc(self, request):
        if not self.persistent:
            self._connect()
        req_id = request.get("requestId")
        data = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        self.sock.sendall(data)
        line = self.stream.readline()
        if not line:
            raise RuntimeError("Connection closed prematurely")
        reply = json.loads(line.decode("utf-8"))
        if req_id is not None and reply.get("requestId") is not None:
            if reply.get("requestId") != req_id:
                raise RuntimeError(
                    f"requestId mismatch: expected {req_id!r}, got {reply.get('requestId')!r}"
                )
        if not self.persistent:
            self.close()
        return reply


def run_scenario(client, target, param_name, param_key, val_seq, is_initial,
                 poll_interval_s=0.003, is_builtin=False, enable_tool=False,
                 phase="core_matrix"):
    samples = []
    session_id = target["sessionId"]
    editor_id = target["editorId"]
    base_rev = target["baseRevision"]

    for i, val in enumerate(val_seq):
        req_id = f"perf-{param_name}-{'init' if is_initial else 'cache'}-{i}-{uuid.uuid4().hex[:6]}"
        req = {
            "protocolVersion": 1,
            "requestId": req_id,
            "op": "set_param",
            "sessionId": session_id,
            "editorId": editor_id,
            "baseRevision": base_rev,
            "params": {param_key: val}
        }
        if not is_builtin:
            cat = client.rpc({
                "protocolVersion": 1,
                "requestId": f"cat-{uuid.uuid4().hex[:4]}",
                "op": "list_params",
                "sessionId": session_id,
                "editorId": editor_id,
                "baseRevision": base_rev,
                "offset": 0,
                "limit": 1
            })
            ctx_id = cat.get("result", {}).get("contextId")
            if ctx_id:
                req["contextId"] = ctx_id
                req["enableTool"] = enable_tool

        c0 = time.perf_counter_ns()
        reply = client.rpc(req)
        ca = time.perf_counter_ns()

        if reply.get("status") != "APPLIED":
            err_code = reply.get("error", {}).get("code")
            samples.append({
                "requestId": req_id,
                "sessionId": session_id,
                "editorId": editor_id,
                "param": param_name,
                "paramKey": param_key,
                "val": val,
                "effectiveValue": None,
                "baseRevision": base_rev,
                "appliedRevision": None,
                "viewRevision": None,
                "renderedRevision": None,
                "renderedViewRevision": None,
                "status": reply.get("status"),
                "error": err_code,
                "applied_rtt_ms": (ca - c0) / 1e6,
                "ready_rtt_ms": None,
                "polls": 0,
                "c0": c0,
                "ca": ca,
                "cr": None,
            })
            if err_code == "REVISION_CONFLICT":
                st = client.rpc({
                    "protocolVersion": 1,
                    "requestId": f"resync-{uuid.uuid4().hex[:4]}",
                    "op": "get_state",
                    "editorId": editor_id
                })
                base_rev = st.get("result", {}).get("renderedRevision", base_rev)
            continue

        res = reply.get("result", {})
        if reply.get("sessionId") != session_id or reply.get("editorId") != editor_id:
            raise RuntimeError(
                f"APPLIED target mismatch for {req_id}: {reply.get('sessionId')}/{reply.get('editorId')}"
            )
        applied_rev = res.get("appliedRevision")
        applied_view_rev = res.get("viewRevision")
        eff_params = res.get("effectiveParams", {})
        if applied_rev != base_rev + 1:
            raise RuntimeError(
                f"Unexpected appliedRevision for {req_id}: expected {base_rev + 1}, got {applied_rev}"
            )
        if param_key not in eff_params or not math.isfinite(float(eff_params[param_key])):
            raise RuntimeError(f"Missing or non-finite effectiveParams[{param_key!r}] in {req_id}")
        eff_val = float(eff_params[param_key])

        base_rev = applied_rev
        polls = 0
        deadline = time.monotonic() + 30.0
        ready_found = False
        final_view_rev = None
        rendered_rev = None
        rendered_view_rev = None

        while time.monotonic() < deadline:
            polls += 1
            st = client.rpc({
                "protocolVersion": 1,
                "requestId": f"poll-{polls}-{uuid.uuid4().hex[:4]}",
                "op": "get_state",
                "editorId": editor_id
            })
            if st.get("sessionId") != session_id:
                raise RuntimeError(f"Session mismatch during poll for {req_id}: {st.get('sessionId')}")
            st_res = st.get("result", {})
            last = st_res.get("lastMutation")
            cur_v = st_res.get("viewRevision")
            r_rev = st_res.get("renderedRevision")
            rv_rev = st_res.get("renderedViewRevision")
            if (last and last.get("requestId") == req_id and
                    last.get("previewStatus") == "READY" and
                    last.get("appliedRevision") == applied_rev and
                    r_rev == applied_rev and
                    rv_rev is not None and rv_rev == cur_v and
                    applied_view_rev is not None and rv_rev >= applied_view_rev):
                ready_found = True
                final_view_rev = cur_v
                rendered_rev = r_rev
                rendered_view_rev = rv_rev
                break
            time.sleep(poll_interval_s)

        cr = time.perf_counter_ns()
        samples.append({
            "requestId": req_id,
            "sessionId": session_id,
            "editorId": editor_id,
            "param": param_name,
            "paramKey": param_key,
            "val": val,
            "effectiveValue": eff_val,
            "baseRevision": applied_rev - 1,
            "appliedRevision": applied_rev,
            "viewRevision": applied_view_rev,
            "finalViewRevision": final_view_rev,
            "renderedRevision": rendered_rev,
            "renderedViewRevision": rendered_view_rev,
            "status": "READY" if ready_found else "TIMEOUT",
            "error": None if ready_found else "TIMEOUT",
            "applied_rtt_ms": (ca - c0) / 1e6,
            "ready_rtt_ms": (cr - c0) / 1e6 if ready_found else None,
            "polls": polls,
            "c0": c0,
            "ca": ca,
            "cr": cr if ready_found else None,
            "phase": phase,
        })

    target["baseRevision"] = base_rev
    return samples


CORE_BOOST_SET = {
    ("saturation", "100", 0, 0),
    ("saturation", "100", 1, 1),
    ("sharpening", "100", 0, 0),
    ("sharpening", "100", 1, 1),
}

REQUIRED_MUTATION_EVENTS = ("S0", "SQ", "SG", "SA", "SP", "SS", "SN", "SC", "SR")
MONOTONIC_PAIRS = (
    ("S0", "SQ"), ("SQ", "SG"), ("SG", "SA"), ("SA", "SP"), ("SP", "SS"),
    ("SA", "SN"), ("SA", "SC"), ("SN", "SR"), ("SC", "SR"),
)


def load_client_jsonl(client_file):
    """Parse client.jsonl and validate per-sample schema and numeric finiteness."""
    errors = []
    client_samples = []
    if not client_file.exists():
        errors.append(f"Missing client.jsonl: {client_file}")
        return client_samples, errors
    with open(client_file, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as exc:
                errors.append(f"client line {lineno}: invalid JSON ({exc})")
                continue
            if not isinstance(obj, dict):
                errors.append(f"client line {lineno}: expected JSON object")
                continue
            req_id = obj.get("requestId")
            status = obj.get("status")
            if not isinstance(req_id, str) or not req_id:
                errors.append(f"client line {lineno}: missing or invalid 'requestId'")
                continue
            if not isinstance(status, str) or not status:
                errors.append(f"client line {lineno}: missing or invalid 'status' for {req_id!r}")
                continue
            if status == "READY":
                for num_field in ("effectiveValue", "applied_rtt_ms", "ready_rtt_ms"):
                    val = obj.get(num_field)
                    if num_field in obj and val is not None:
                        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(float(val)):
                            errors.append(
                                f"client line {lineno} ({req_id}): non-finite {num_field}={val!r}"
                            )
            client_samples.append(obj)
    return client_samples, errors


def resolve_planned_batches(manifest):
    """Resolve planned batch IDs from manifest, rejecting duplicate batch entries."""
    errors = []
    batches = manifest.get("batches")
    merged_from = manifest.get("merged_from")
    if isinstance(merged_from, list) and len(merged_from) > 1:
        merged_batches = manifest.get("merged_batches")
        if isinstance(merged_batches, list) and merged_batches:
            batches = merged_batches
        elif not (isinstance(batches, list) and len(batches) == len(merged_from)):
            resolved = []
            for d_str in merged_from:
                src_mf_path = Path(d_str) / "manifest.json"
                if not src_mf_path.exists():
                    errors.append(f"Missing source batch manifest in merged_from: {src_mf_path}")
                    continue
                try:
                    src_mf = json.loads(src_mf_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"Invalid source batch manifest {src_mf_path}: {exc}")
                    continue
                src_batches = src_mf.get("batches")
                if not isinstance(src_batches, list) or not src_batches:
                    errors.append(f"Source batch manifest missing batches list: {src_mf_path}")
                    continue
                resolved.extend(src_batches)
            if not errors:
                batches = resolved

    if not isinstance(batches, list) or not batches:
        errors.append("manifest missing non-empty 'batches' list")
        return [], errors

    clean_batches = []
    seen = set()
    for b in batches:
        if not isinstance(b, int) or isinstance(b, bool):
            errors.append(f"manifest contains non-integer batch id: {b!r}")
            continue
        if b in seen:
            errors.append(f"duplicate planned batch id in manifest: {b}")
            continue
        seen.add(b)
        clean_batches.append(b)
    return clean_batches, errors


def compute_expected_plan(manifest):
    """Compute exact planned condition keys (batch, phase, cell_id) -> count from manifest."""
    errors = []
    expected = Counter()
    if not isinstance(manifest, dict) or not manifest:
        return expected, 0, ["Missing or empty manifest.json for perf_benchmark validation"]

    params = manifest.get("parameters")
    if not isinstance(params, list) or not params:
        errors.append("manifest missing non-empty 'parameters' list")
    elif len(params) != len(set(params)):
        errors.append(f"manifest contains duplicate parameters: {params}")

    batches, batch_errs = resolve_planned_batches(manifest)
    errors.extend(batch_errs)

    repeats = manifest.get("repeats_per_batch")
    warm = manifest.get("warm_repeats_per_batch")
    core_boost = manifest.get("core_boost_per_batch", 0)
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats <= 0:
        errors.append(f"manifest invalid 'repeats_per_batch': {repeats!r}")
    if not isinstance(warm, int) or isinstance(warm, bool) or warm < 0:
        errors.append(f"manifest invalid 'warm_repeats_per_batch': {warm!r}")
    if not isinstance(core_boost, int) or isinstance(core_boost, bool) or core_boost < 0:
        errors.append(f"manifest invalid 'core_boost_per_batch': {core_boost!r}")

    if errors:
        return expected, 0, errors

    for b in batches:
        for hdr in (0, 1):
            for denoise in (0, 1):
                for zoom in ("fit", "100"):
                    for p in params:
                        cid_init = f"{p}_{zoom}_init_hdr{hdr}_dn{denoise}"
                        expected[(b, "core_matrix", cid_init)] += repeats
                        if warm > 0:
                            cid_cache = f"{p}_{zoom}_cache_hdr{hdr}_dn{denoise}"
                            expected[(b, "core_matrix", cid_cache)] += warm
                        if core_boost > 0 and (p, zoom, hdr, denoise) in CORE_BOOST_SET:
                            cid_cache = f"{p}_{zoom}_cache_hdr{hdr}_dn{denoise}"
                            expected[(b, "core_boost", cid_cache)] += core_boost

    return expected, sum(expected.values()), errors


def validate_contract_test(manifest, client_samples):
    """Validate explicit expectations for contract_test / stress runs separately from perf benchmarks."""
    errors = []
    has_ready_exp = "expected_ready_count" in manifest
    has_req_exp = "expected_request_ids" in manifest
    has_status_exp = "expected_statuses" in manifest
    if not (has_ready_exp or has_req_exp or has_status_exp):
        errors.append(
            "contract_test manifest must declare at least one of "
            "'expected_ready_count', 'expected_request_ids', or 'expected_statuses'"
        )
        return errors

    seen_reqs = set()
    actual_statuses = {}
    ready_count = 0
    for s in client_samples:
        req_id = s.get("requestId")
        if req_id in seen_reqs:
            errors.append(f"duplicate requestId in client.jsonl: {req_id!r}")
        else:
            seen_reqs.add(req_id)
            actual_statuses[req_id] = s.get("status")
        if s.get("status") == "READY":
            ready_count += 1

    if has_ready_exp:
        exp_ready = manifest["expected_ready_count"]
        if ready_count != exp_ready:
            errors.append(
                f"contract_test expected_ready_count={exp_ready}, got {ready_count}"
            )
    if has_req_exp:
        exp_reqs = manifest["expected_request_ids"]
        if not isinstance(exp_reqs, list) or len(exp_reqs) != len(set(exp_reqs)):
            errors.append("contract_test manifest has invalid or duplicate expected_request_ids")
        elif set(exp_reqs) != seen_reqs:
            missing = sorted(set(exp_reqs) - seen_reqs)
            extra = sorted(seen_reqs - set(exp_reqs))
            errors.append(
                f"contract_test requestId mismatch (missing={missing}, extra={extra})"
            )
    if has_status_exp:
        exp_statuses = manifest["expected_statuses"]
        if not isinstance(exp_statuses, dict):
            errors.append("contract_test expected_statuses must be a JSON object")
        else:
            for req_id, exp_st in exp_statuses.items():
                got_st = actual_statuses.get(req_id)
                if got_st != exp_st:
                    errors.append(
                        f"contract_test status mismatch for {req_id!r}: expected {exp_st!r}, got {got_st!r}"
                    )
    return errors


def validate_perf_run(manifest, client_samples, samples_csv=None):
    """Validate sample completeness, READY rate, no duplicates, and planned condition coverage."""
    errors = []
    if not isinstance(manifest, dict) or not manifest:
        return ["Missing or invalid manifest.json"]

    run_type = manifest.get("run_type") or "perf_benchmark"
    if run_type not in ("perf_benchmark", "contract_test"):
        return [f"Unknown manifest run_type={run_type!r}"]

    for le in manifest.get("launch_errors") or []:
        errors.append(f"launch error: {le}")

    if run_type == "contract_test":
        errors.extend(validate_contract_test(manifest, client_samples))
        return errors

    if not client_samples:
        errors.append("empty client.jsonl (0 attempted samples)")
        return errors

    expected_counts, expected_total, plan_errors = compute_expected_plan(manifest)
    errors.extend(plan_errors)

    seen_reqs = set()
    attempted_counts = Counter()
    ready_counts = Counter()
    ready_total = 0
    non_ready_samples = []

    for s in client_samples:
        req_id = s.get("requestId")
        if req_id in seen_reqs:
            errors.append(f"duplicate requestId in client.jsonl: {req_id!r}")
        else:
            seen_reqs.add(req_id)

        batch_val = s.get("batch")
        phase_val = s.get("phase") or "core_matrix"
        cell_val = s.get("cell_id")
        if not isinstance(batch_val, int) or isinstance(batch_val, bool) or not cell_val:
            errors.append(
                f"sample {req_id!r} missing valid batch/cell_id metadata "
                f"(batch={batch_val!r}, cell_id={cell_val!r})"
            )
            continue

        key = (batch_val, phase_val, cell_val)
        attempted_counts[key] += 1
        if s.get("status") == "READY":
            ready_total += 1
            ready_counts[key] += 1
        else:
            non_ready_samples.append((req_id, key, s.get("status"), s.get("error")))

    if ready_total == 0:
        errors.append(f"0 READY samples out of {len(client_samples)} attempted samples")

    for req_id, key, status, err in non_ready_samples[:20]:
        errors.append(
            f"non-READY sample {req_id!r} in {key}: status={status!r}, error={err!r}"
        )
    if len(non_ready_samples) > 20:
        errors.append(f"... and {len(non_ready_samples) - 20} more non-READY sample(s)")

    if not plan_errors:
        if len(client_samples) != expected_total or ready_total != expected_total:
            errors.append(
                f"total sample count mismatch: planned={expected_total}, "
                f"attempted={len(client_samples)}, ready={ready_total}"
            )
        missing_keys = sorted(set(expected_counts.keys()) - set(attempted_counts.keys()))
        extra_keys = sorted(set(attempted_counts.keys()) - set(expected_counts.keys()))
        if missing_keys:
            errors.append(
                f"missing {len(missing_keys)} planned condition(s), e.g. {missing_keys[:5]}"
            )
        if extra_keys:
            errors.append(
                f"found {len(extra_keys)} unexpected condition(s) beyond plan, e.g. {extra_keys[:5]}"
            )
        mismatched = []
        for k in sorted(set(expected_counts.keys()) & set(attempted_counts.keys())):
            exp_n = expected_counts[k]
            att_n = attempted_counts[k]
            rdy_n = ready_counts[k]
            if att_n != exp_n or rdy_n != exp_n:
                mismatched.append((k, exp_n, att_n, rdy_n))
        for k, exp_n, att_n, rdy_n in mismatched[:15]:
            errors.append(
                f"condition count mismatch for {k}: planned={exp_n}, attempted={att_n}, ready={rdy_n}"
            )
        if len(mismatched) > 15:
            errors.append(f"... and {len(mismatched) - 15} more condition count mismatch(es)")

    if samples_csv is not None and samples_csv.exists():
        try:
            with open(samples_csv, "r", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            if len(csv_rows) != len(client_samples):
                errors.append(
                    f"samples.csv row count ({len(csv_rows)}) != client.jsonl count ({len(client_samples)})"
                )
            csv_reqs = [r.get("requestId") for r in csv_rows]
            if len(csv_reqs) != len(set(csv_reqs)):
                errors.append("duplicate requestId found in samples.csv")
        except Exception as exc:
            errors.append(f"failed reading samples.csv: {exc}")

    return errors


def validate_and_index_trace(trace_file, client_samples):
    """Validate JSONL integrity, drops/writeErrors, identity/generation correlation and timing."""
    errors = []
    if not trace_file.exists():
        if client_samples:
            errors.append(f"Missing trace file: {trace_file}")
        return errors, {}, {}, {}

    events_by_cmd = {}
    sa_by_req = {}
    sr_by_req = {}
    replay_cmds = set()
    engine_stages = {}
    crop_stages = {}
    engine_change_ts = {}
    current_session_id = ""
    non_empty_lines = 0

    with open(trace_file, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            non_empty_lines += 1
            try:
                ev = json.loads(line)
            except Exception as exc:
                errors.append(f"trace line {lineno}: invalid JSON ({exc})")
                continue
            if not isinstance(ev, dict):
                errors.append(f"trace line {lineno}: expected JSON object")
                continue
            ev_name = ev.get("event")
            ts_ns = ev.get("timestamp_ns")
            if not isinstance(ev_name, str) or not ev_name:
                errors.append(f"trace line {lineno}: missing or invalid 'event'")
                continue
            if not isinstance(ts_ns, (int, float)) or isinstance(ts_ns, bool) or ts_ns <= 0:
                errors.append(f"trace line {lineno}: invalid 'timestamp_ns' for {ev_name}")
                continue
            drops = ev.get("drops", 0)
            write_errs = ev.get("writeErrors", 0)
            if isinstance(drops, (int, float)) and drops > 0:
                errors.append(f"trace line {lineno}: recorded dropped events drops={drops}")
            if isinstance(write_errs, (int, float)) and write_errs > 0:
                errors.append(f"trace line {lineno}: recorded write errors writeErrors={write_errs}")

            if ev.get("sessionId"):
                current_session_id = ev.get("sessionId") or current_session_id

            if ev_name == "ENGINE_DONE":
                gen = ev.get("generation")
                if gen:
                    key_sg = (current_session_id, gen)
                    engine_stages[key_sg] = ev.get("detail", "")
                continue
            if ev_name == "CROP_DONE":
                gen = ev.get("generation")
                detail = ev.get("detail", "")
                if gen:
                    key_sg = (current_session_id, gen)
                    if "crop:main=1" in detail or key_sg not in crop_stages:
                        crop_stages[key_sg] = detail
                continue
            if ev_name == "ENGINE_CHANGE":
                gen = ev.get("generation")
                if gen:
                    key_sg = (current_session_id, gen)
                    engine_change_ts.setdefault(key_sg, ts_ns)
                continue

            cmd_id = ev.get("cmdId")
            sess_id = ev.get("sessionId") or ""
            req_id = ev.get("requestId")

            if cmd_id:
                cmd_key = (sess_id, int(cmd_id))
                bucket = events_by_cmd.setdefault(cmd_key, {})
                if ev_name == "REPLAY":
                    replay_cmds.add(cmd_key)
                if ev_name in bucket:
                    errors.append(
                        f"trace line {lineno}: duplicate event {ev_name} for cmd={cmd_key}"
                    )
                else:
                    bucket[ev_name] = ev

            if req_id:
                if ev_name == "SA":
                    lst = sa_by_req.setdefault(req_id, [])
                    lst.append(ev)
                    if len(lst) > 1:
                        errors.append(f"trace line {lineno}: duplicate SA for requestId={req_id!r}")
                elif ev_name == "SR":
                    lst = sr_by_req.setdefault(req_id, [])
                    lst.append(ev)
                    if len(lst) > 1:
                        errors.append(f"trace line {lineno}: duplicate SR for requestId={req_id!r}")

    if client_samples and non_empty_lines == 0:
        errors.append(f"Empty trace file: {trace_file}")
        return errors, {}, engine_stages, crop_stages

    indexed_by_req = {}
    for sample in client_samples:
        req_id = sample.get("requestId")
        if not req_id:
            errors.append("client sample missing requestId")
            continue
        if sample.get("status") != "READY":
            continue

        sa_list = sa_by_req.get(req_id, [])
        if len(sa_list) != 1:
            errors.append(
                f"requestId={req_id!r}: expected exactly 1 SA event, found {len(sa_list)}"
            )
            continue
        sa_ev = sa_list[0]
        cmd_id = sa_ev.get("cmdId")
        sess_id = sa_ev.get("sessionId") or ""
        if not cmd_id:
            errors.append(f"requestId={req_id!r}: SA missing cmdId")
            continue
        cmd_key = (sess_id, int(cmd_id))
        if cmd_key in replay_cmds:
            errors.append(f"requestId={req_id!r}: REPLAY collided with primary cmd={cmd_key}")
            continue
        cmd_events = events_by_cmd.get(cmd_key, {})

        # Collect SN/SC/SR: prefer same cmdId, fallback to matching requestId if needed
        merged = dict(cmd_events)
        for ev_name in ("SN", "SC", "SR"):
            if ev_name not in merged and ev_name == "SR":
                sr_list = sr_by_req.get(req_id, [])
                if len(sr_list) == 1:
                    merged["SR"] = sr_list[0]

        missing = [e for e in REQUIRED_MUTATION_EVENTS if e not in merged]
        if missing:
            errors.append(
                f"requestId={req_id!r} (cmd={cmd_key}): missing trace events {missing}"
            )
            continue

        exp_sess = sample.get("sessionId")
        exp_ed = sample.get("editorId")
        exp_rev = sample.get("appliedRevision")
        exp_sa_vrev = sample.get("viewRevision")
        exp_fin_vrev = sample.get("renderedViewRevision")

        for ev_name in REQUIRED_MUTATION_EVENTS:
            ev = merged[ev_name]
            ev_req = ev.get("requestId")
            if ev_req != req_id:
                errors.append(
                    f"requestId={req_id!r}: {ev_name}.requestId mismatch ({ev_req!r})"
                )
            if exp_sess and ev.get("sessionId") != exp_sess:
                errors.append(
                    f"requestId={req_id!r}: {ev_name}.sessionId mismatch "
                    f"({ev.get('sessionId')!r} != {exp_sess!r})"
                )
        for ev_name in ("SA", "SN", "SC", "SR"):
            ev = merged[ev_name]
            if exp_ed and ev.get("editorId") != exp_ed:
                errors.append(
                    f"requestId={req_id!r}: {ev_name}.editorId mismatch "
                    f"({ev.get('editorId')!r} != {exp_ed!r})"
                )
            if exp_rev is not None and ev.get("editRev") != exp_rev:
                errors.append(
                    f"requestId={req_id!r}: {ev_name}.editRev mismatch "
                    f"({ev.get('editRev')} != {exp_rev})"
                )

        if exp_sa_vrev is not None and merged["SA"].get("viewRev") != exp_sa_vrev:
            errors.append(
                f"requestId={req_id!r}: SA.viewRev mismatch "
                f"({merged['SA'].get('viewRev')} != {exp_sa_vrev})"
            )
        if exp_fin_vrev is not None:
            for ev_name in ("SC", "SR"):
                if merged[ev_name].get("viewRev") != exp_fin_vrev:
                    errors.append(
                        f"requestId={req_id!r}: {ev_name}.viewRev mismatch "
                        f"({merged[ev_name].get('viewRev')} != {exp_fin_vrev})"
                    )

        sa_gen = merged["SA"].get("generation") or 0
        sn_gen = merged["SN"].get("generation") or 0
        sc_gen = merged["SC"].get("generation") or 0
        sr_gen = merged["SR"].get("generation") or 0
        if not (sr_gen > 0 and sn_gen == sr_gen and sc_gen == sr_gen and sr_gen >= sa_gen):
            errors.append(
                f"requestId={req_id!r}: generation mismatch "
                f"SA={sa_gen}, SN={sn_gen}, SC={sc_gen}, SR={sr_gen}"
            )

        if sample.get("effectiveValue") is None or not math.isfinite(float(sample["effectiveValue"])):
            errors.append(f"requestId={req_id!r}: missing finite effectiveValue")

        for earlier, later in MONOTONIC_PAIRS:
            t1 = merged[earlier]["timestamp_ns"]
            t2 = merged[later]["timestamp_ns"]
            if t1 > t2:
                errors.append(
                    f"requestId={req_id!r}: non-monotonic timestamp {earlier}({t1}) > {later}({t2})"
                )

        key_sg = (sample.get("sessionId") or "", sr_gen)
        merged["_stage_timings"] = {
            "engine_change_ns": engine_change_ts.get(key_sg),
        }
        indexed_by_req[req_id] = merged

    return errors, indexed_by_req, engine_stages, crop_stages


def evaluate_perf_artifacts(manifest, client_samples, client_parse_errors=None,
                            trace_file=None, samples_csv=None, extra_perf_errors=None):
    """Evaluate BOTH log integrity and performance run completeness under one shared rule set."""
    log_errors = list(client_parse_errors or [])
    trace_enabled = bool(manifest.get("trace_enabled", True)) if isinstance(manifest, dict) else True
    indexed = {}
    engine_stages = {}
    crop_stages = {}

    if trace_enabled and trace_file is not None:
        t_errors, indexed, engine_stages, crop_stages = validate_and_index_trace(
            trace_file, client_samples
        )
        log_errors.extend(t_errors)

    perf_errors = list(extra_perf_errors or [])
    perf_errors.extend(validate_perf_run(manifest, client_samples, samples_csv=samples_csv))

    run_type = (manifest.get("run_type") or "perf_benchmark") if isinstance(manifest, dict) else "perf_benchmark"
    log_ok = not log_errors
    perf_ok = not perf_errors
    all_errors = log_errors + perf_errors
    ready_count = sum(1 for s in client_samples if s.get("status") == "READY")

    result = {
        "run_type": run_type,
        "log_integrity_status": "PASSED" if log_ok else "FAILED",
        "log_integrity_error_count": len(log_errors),
        "log_integrity_errors": log_errors[:50],
        "perf_run_status": "PASSED" if perf_ok else "FAILED",
        "perf_run_error_count": len(perf_errors),
        "perf_run_errors": perf_errors[:50],
        "status": "PASSED" if (log_ok and perf_ok) else "FAILED",
        "exit_code": 0 if (log_ok and perf_ok) else 1,
        "validation_error_count": len(all_errors),
        "validation_errors": all_errors[:50],
        "attempted_samples": len(client_samples),
        "ready_samples": ready_count,
    }
    return result, indexed, engine_stages, crop_stages


def validate_directory(dir_path, update_manifest=False):
    """Validate an existing perf output directory using identical integrity & completeness rules."""
    target = Path(dir_path).resolve()
    client_file = target / "client.jsonl"
    trace_file = target / "trace.jsonl"
    samples_csv = target / "samples.csv"
    manifest_file = target / "manifest.json"

    manifest = {}
    manifest_errors = []
    if not manifest_file.exists():
        manifest_errors.append(f"Missing manifest.json: {manifest_file}")
    else:
        try:
            loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                manifest_errors.append(f"manifest.json must be a JSON object: {manifest_file}")
            else:
                manifest = loaded
        except Exception as exc:
            manifest_errors.append(f"Invalid JSON in manifest.json ({exc})")

    client_samples, client_errors = load_client_jsonl(client_file)
    trace_enabled = bool(manifest.get("trace_enabled", True))
    eval_res, indexed, engine_stages, crop_stages = evaluate_perf_artifacts(
        manifest=manifest,
        client_samples=client_samples,
        client_parse_errors=client_errors,
        trace_file=trace_file if trace_enabled else None,
        samples_csv=samples_csv if samples_csv.exists() else None,
        extra_perf_errors=manifest_errors,
    )

    if update_manifest:
        out_manifest = dict(manifest)
        out_manifest.update({k: v for k, v in eval_res.items() if k != "attempted_samples"})
        manifest_file.write_text(
            json.dumps(out_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if eval_res["status"] != "PASSED":
        print(
            f"VALIDATION FAILED [{eval_res['run_type']}] "
            f"(log_integrity={eval_res['log_integrity_status']}[{eval_res['log_integrity_error_count']}], "
            f"perf_run={eval_res['perf_run_status']}[{eval_res['perf_run_error_count']}], "
            f"attempted={eval_res['attempted_samples']}, ready={eval_res['ready_samples']}):",
            file=sys.stderr,
        )
        for e in eval_res["validation_errors"][:25]:
            print(f"  - {e}", file=sys.stderr)
        return False

    print(
        f"VALIDATION PASSED [{eval_res['run_type']}]: "
        f"log_integrity={eval_res['log_integrity_status']}, perf_run={eval_res['perf_run_status']}, "
        f"{eval_res['ready_samples']}/{eval_res['attempted_samples']} READY samples, "
        f"{len(engine_stages)} ENGINE_DONE, {len(crop_stages)} CROP_DONE"
    )
    return True


def build_arp_text(hdr, denoise):
    lines = [
        "[Version]",
        "AppVersion=1045",
        "Version=1045",
        "[Exposure]",
        "Enabled=true",
        "Compensation=0.0",
        "[Saturation]",
        "Enabled=true",
        "Saturation=0",
        "[White Balance]",
        "Enabled=true",
        "Setting=Custom",
        "Temperature=5500",
        "Green=1.0",
        "Equal=1.0",
        "[Sharpening]",
        "Enabled=true",
        "Method=usm",
        "Radius=0.5",
        "Amount=200",
        "[Dehaze]",
        "Enabled=false",
    ]
    if hdr:
        lines.extend(["[FattalToneMapping]", "Enabled=true", "Amount=30", "Threshold=40"])
    else:
        lines.extend(["[FattalToneMapping]", "Enabled=false"])
    if denoise:
        lines.extend(["[Impulse Denoising]", "Enabled=true", "[Denoise]", "Enabled=true"])
    else:
        lines.extend(["[Impulse Denoising]", "Enabled=false", "[Denoise]", "Enabled=false"])
    return "\n".join(lines) + "\n"


def discover_param_keys(client, session_id, editor_id, base_revision, needed_param=None):
    offset = 0
    context_id = None
    discovered = {}
    while True:
        cat_req = {
            "protocolVersion": 1,
            "requestId": f"cat-{offset}-{uuid.uuid4().hex[:4]}",
            "op": "list_params",
            "sessionId": session_id,
            "editorId": editor_id,
            "baseRevision": base_revision,
            "offset": offset,
            "limit": 32,
        }
        if context_id:
            cat_req["contextId"] = context_id
        cat = client.rpc(cat_req)
        context_id = cat.get("result", {}).get("contextId", context_id)
        items = cat.get("result", {}).get("items", [])
        for item in items:
            tool = item.get("tool", "").lower()
            label = item.get("label", "").lower()
            key = item.get("key", "")
            if tool == "exposure" and label == "exposure compensation":
                discovered["exposure"] = key
            elif tool == "saturation" and label == "saturation":
                discovered["saturation"] = key
            elif tool == "whitebalance" and label == "temperature":
                discovered["temperature"] = key
            elif tool == "sharpening" and label == "radius":
                discovered["sharpening"] = key
        if needed_param and needed_param in discovered:
            break
        next_off = cat.get("result", {}).get("nextOffset")
        if not next_off:
            break
        offset = next_off

    return discovered


def wait_for_initial_ready(client, zoom, quiet_window_s=0.05):
    deadline = time.monotonic() + 30.0
    stable_sig = None
    stable_since = None
    while time.monotonic() < deadline:
        try:
            s = client.rpc({
                "protocolVersion": 1,
                "requestId": f"init-{uuid.uuid4().hex[:4]}",
                "op": "get_state",
            })
            editors = s.get("result", {}).get("editors", [])
            if editors:
                editor_id = editors[0]["editorId"]
                sess_id = s["sessionId"]
                st = client.rpc({
                    "protocolVersion": 1,
                    "requestId": f"init-st-{uuid.uuid4().hex[:4]}",
                    "op": "get_state",
                    "editorId": editor_id,
                })
                res = st.get("result", {})
                rev = res.get("revision")
                r_rev = res.get("renderedRevision")
                v_rev = res.get("viewRevision")
                rv_rev = res.get("renderedViewRevision")
                ready_now = (
                    rev is not None and r_rev is not None and r_rev == rev and
                    v_rev is not None and rv_rev is not None and rv_rev == v_rev and
                    (zoom != "100" or v_rev >= 1)
                )
                sig = (rev, v_rev, r_rev, rv_rev)
                if ready_now:
                    now = time.monotonic()
                    if sig != stable_sig:
                        stable_sig = sig
                        stable_since = now
                    elif now - stable_since >= quiet_window_s:
                        return sess_id, editor_id, st
                    time.sleep(0.05)
                    continue
                stable_sig = None
                stable_since = None
        except Exception:
            stable_sig = None
            stable_since = None
        time.sleep(0.01)
    raise RuntimeError(f"GUI did not complete initial render/settle for zoom={zoom}")


def generate_distinct_values(pool, count, avoid_value=None):
    out = []
    prev = avoid_value
    idx = 0
    while len(out) < count:
        candidate = pool[idx % len(pool)]
        idx += 1
        if candidate == prev and len(pool) > 1:
            candidate = pool[idx % len(pool)]
            idx += 1
        out.append(candidate)
        prev = candidate
    return out


def run_single_launch(app_bin, raw_path, options_file, arp_text, trace_file, work_dir,
                          mode, zoom, hdr, denoise, batch_idx, param_name, init_val,
                          warm_vals, core_boost_vals, poll_interval_s, is_builtin,
                          trace_enabled=True):
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    settings = work_dir / "settings"
    cache = work_dir / "cache"
    settings.mkdir()
    cache.mkdir()
    shutil.copy2(options_file, settings / "options")

    raw_copy = work_dir / "sample.nef"
    cp_res = subprocess.run(["cp", "-c", str(raw_path), str(raw_copy)], capture_output=True)
    if cp_res.returncode != 0:
        shutil.copy2(raw_path, raw_copy)
    (work_dir / "sample.nef.arp").write_text(arp_text, encoding="utf-8")

    env = {
        **os.environ,
        "ART_LIVE_PARAM": "1",
        "ART_SETTINGS": str(settings),
        "ART_CACHE": str(cache),
        "ART_LIVE_PARAM_INITIAL_ZOOM": "100" if zoom == "100" else "fit",
    }
    if trace_enabled and trace_file is not None:
        env["ART_LIVE_PARAM_TRACE"] = str(trace_file)
    else:
        env.pop("ART_LIVE_PARAM_TRACE", None)

    sock_dir = f"/tmp/art-liveparam-{os.geteuid()}"
    pre_socks = set(glob.glob(f"{sock_dir}/art-*.sock"))
    proc = subprocess.Popen([str(app_bin), "-s", str(raw_copy)], env=env)
    collected = []
    sock_path = None
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            socks = [s for s in glob.glob(f"{sock_dir}/art-{proc.pid}-*.sock") if s not in pre_socks]
            if socks:
                sock_path = socks[0]
                break
            time.sleep(0.005)
        if not sock_path:
            raise RuntimeError(f"Process {proc.pid} did not open socket")

        client = None
        connect_deadline = time.monotonic() + 2.0
        while True:
            try:
                client = LiveParamClient(sock_path, persistent=(mode == "persistent"), timeout=15.0)
                break
            except (ConnectionRefusedError, FileNotFoundError):
                if proc.poll() is not None or time.monotonic() >= connect_deadline:
                    raise
                time.sleep(0.01)
        try:
            sess_id, editor_id, init_state = wait_for_initial_ready(client, zoom)
            target = {
                "sessionId": sess_id,
                "editorId": editor_id,
                "baseRevision": init_state["result"]["renderedRevision"],
            }
            if is_builtin:
                pkey = "Exposure.Compensation"
            else:
                discovered = discover_param_keys(
                    client, sess_id, editor_id, target["baseRevision"], needed_param=param_name
                )
                if param_name not in discovered:
                    raise RuntimeError(f"Param {param_name!r} not found in catalogue: {sorted(discovered)}")
                pkey = discovered[param_name]

            init_samples = run_scenario(
                client, target, param_name, pkey, [init_val],
                is_initial=True, poll_interval_s=poll_interval_s,
                is_builtin=is_builtin, enable_tool=False, phase="core_matrix"
            )
            cell_id_init = f"{param_name}_{zoom}_init_hdr{hdr}_dn{denoise}"
            for s in init_samples:
                s.update({
                    "batch": batch_idx, "cell_id": cell_id_init,
                    "param": param_name, "zoom": zoom, "cache": "initial",
                    "hdr": hdr, "denoise": denoise,
                })
            collected.extend(init_samples)

            cell_id_cache = f"{param_name}_{zoom}_cache_hdr{hdr}_dn{denoise}"
            if warm_vals:
                warm_samples = run_scenario(
                    client, target, param_name, pkey, warm_vals,
                    is_initial=False, poll_interval_s=poll_interval_s,
                    is_builtin=is_builtin, enable_tool=False, phase="core_matrix"
                )
                for s in warm_samples:
                    s.update({
                        "batch": batch_idx, "cell_id": cell_id_cache,
                        "param": param_name, "zoom": zoom, "cache": "cached",
                        "hdr": hdr, "denoise": denoise,
                    })
                collected.extend(warm_samples)

            if core_boost_vals:
                boost_samples = run_scenario(
                    client, target, param_name, pkey, core_boost_vals,
                    is_initial=False, poll_interval_s=poll_interval_s,
                    is_builtin=is_builtin, enable_tool=False, phase="core_boost"
                )
                for s in boost_samples:
                    s.update({
                        "batch": batch_idx, "cell_id": cell_id_cache,
                        "param": param_name, "zoom": zoom, "cache": "cached",
                        "hdr": hdr, "denoise": denoise,
                    })
                collected.extend(boost_samples)
        finally:
            client.close()
            if trace_enabled:
                time.sleep(0.08)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        if sock_path and os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except OSError:
                pass
    return collected


def parse_stage_kv(detail):
    """Parse 'nav:k=v,...' or 'crop:k=v,...' detail strings into an int-valued dict."""
    if not detail:
        return {}
    body = detail.split(":", 1)[1] if ":" in detail else detail
    out = {}
    for part in body.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out


def build_csv_rows(all_client_samples, server_events, engine_stages, crop_stages):
    csv_rows = []
    for s in all_client_samples:
        req_id = s["requestId"]
        sev = server_events.get(req_id, {})
        s0 = sev.get("S0", {}).get("timestamp_ns")
        sq = sev.get("SQ", {}).get("timestamp_ns")
        sg = sev.get("SG", {}).get("timestamp_ns")
        sa = sev.get("SA", {}).get("timestamp_ns")
        sp = sev.get("SP", {}).get("timestamp_ns")
        ss = sev.get("SS", {}).get("timestamp_ns")
        sn = sev.get("SN", {}).get("timestamp_ns")
        sc = sev.get("SC", {}).get("timestamp_ns")
        sr = sev.get("SR", {}).get("timestamp_ns")
        sr_gen = sev.get("SR", {}).get("generation")
        eng_str = engine_stages.get((s.get("sessionId") or "", sr_gen), "")
        crop_str = crop_stages.get((s.get("sessionId") or "", sr_gen), "")
        nav_kv = parse_stage_kv(eng_str)
        crop_kv = parse_stage_kv(crop_str)
        st_tim = sev.get("_stage_timings", {})
        ec_ns = st_tim.get("engine_change_ns")
        publish_ns = crop_kv.get("publish_ns")
        worker_start_ns = nav_kv.get("worker_start_ns")

        wait_ms = None
        nav_pre_ms = (nav_kv["nav_pre_us"] / 1000.0) if "nav_pre_us" in nav_kv else None
        nav_post_ms = (nav_kv["nav_post_us"] / 1000.0) if "nav_post_us" in nav_kv else None
        crop_stage_ms = (crop_kv["stage_us"] / 1000.0) if "stage_us" in crop_kv else None
        crop_conv_ms = (crop_kv["conv_us"] / 1000.0) if "conv_us" in crop_kv else None
        crop_calc_ms = (
            (crop_kv["stage_us"] + crop_kv["conv_us"]) / 1000.0
            if ("stage_us" in crop_kv and "conv_us" in crop_kv) else None
        )
        crop_copy_ms = (crop_kv["copy_us"] / 1000.0) if "copy_us" in crop_kv else None
        gui_pixbuf_ms = (
            (sc - publish_ns) / 1e6 if sc and publish_ns and sc >= publish_ns
            else None
        )
        gui_deliver_ms = (
            (crop_copy_ms + gui_pixbuf_ms)
            if (crop_copy_ms is not None and gui_pixbuf_ms is not None) else None
        )
        # The worker can start before the GUI finishes assembling APPLIED.
        if worker_start_ns and sa:
            wait_ms = max(0.0, (worker_start_ns - sa) / 1e6)
        change_to_worker_ms = (
            (worker_start_ns - ec_ns) / 1e6
            if worker_start_ns and ec_ns and worker_start_ns >= ec_ns else None
        )

        def delta_ms(t_end, t_start):
            return (t_end - t_start) / 1e6 if (t_end and t_start and t_end >= t_start) else None

        csv_rows.append({
            "requestId": req_id,
            "sessionId": s.get("sessionId"),
            "editorId": s.get("editorId"),
            "batch": s["batch"],
            "phase": s.get("phase", "core_matrix"),
            "cell_id": s["cell_id"],
            "param": s["param"],
            "paramKey": s.get("paramKey"),
            "val": s["val"],
            "effectiveValue": s.get("effectiveValue"),
            "appliedRevision": s.get("appliedRevision"),
            "viewRevision": s.get("renderedViewRevision"),
            "generation": sr_gen,
            "zoom": s["zoom"],
            "cache": s["cache"],
            "hdr": s["hdr"],
            "denoise": s["denoise"],
            "status": s["status"],
            "applied_rtt_ms": s["applied_rtt_ms"],
            "ready_rtt_ms": s["ready_rtt_ms"],
            "sq_minus_s0_ms": delta_ms(sq, s0),
            "sg_minus_sq_ms": delta_ms(sg, sq),
            "sa_minus_sg_ms": delta_ms(sa, sg),
            "sp_minus_sa_ms": delta_ms(sp, sa),
            "ss_minus_sp_ms": delta_ms(ss, sp),
            "sn_minus_sa_ms": delta_ms(sn, sa),
            "sc_minus_sa_ms": delta_ms(sc, sa),
            "sr_minus_sa_ms": delta_ms(sr, sa),
            "wait_ms": wait_ms,
            "nav_pre_ms": nav_pre_ms,
            "nav_post_ms": nav_post_ms,
            "crop_stage_ms": crop_stage_ms,
            "crop_conv_ms": crop_conv_ms,
            "crop_calc_ms": crop_calc_ms,
            "crop_copy_ms": crop_copy_ms,
            "gui_pixbuf_ms": gui_pixbuf_ms,
            "gui_deliver_ms": gui_deliver_ms,
            "change_to_worker_ms": change_to_worker_ms,
            "req_todo": nav_kv.get("req_todo"),
            "exec_todo": nav_kv.get("todo"),
            "wb_mode": nav_kv.get("wb_mode"),
            "hr_mode": nav_kv.get("hr_mode"),
            "crop_skip": crop_kv.get("skip"),
            "crop_w": crop_kv.get("w"),
            "crop_h": crop_kv.get("h"),
            "polls": s["polls"],
            "engine_stages": eng_str,
            "crop_stages": crop_str,
        })
    return csv_rows


def summarize_rows(csv_rows):
    cells = {}
    for r in csv_rows:
        cells.setdefault(r["cell_id"], []).append(r)

    summary_rows = []
    for cid, items in sorted(cells.items()):
        total = len(items)
        successes = [it for it in items if it["status"] == "READY"]
        rejected = [it for it in items if it["status"] == "ERROR"]
        incomplete = total - len(successes) - len(rejected)
        success_rate = len(successes) / total if total else 0.0

        applied_times = [float(it["applied_rtt_ms"]) for it in items if it["applied_rtt_ms"] not in (None, "")]
        ready_times = [float(it["ready_rtt_ms"]) for it in successes if it["ready_rtt_ms"] not in (None, "")]

        def metric_list(col):
            return [float(it[col]) for it in items if it.get(col) not in (None, "")]

        sq_s0 = metric_list("sq_minus_s0_ms")
        sg_sq = metric_list("sg_minus_sq_ms")
        sa_sg = metric_list("sa_minus_sg_ms")
        sp_sa = metric_list("sp_minus_sa_ms")
        ss_sp = metric_list("ss_minus_sp_ms")
        sn_sa = metric_list("sn_minus_sa_ms")
        sc_sa = metric_list("sc_minus_sa_ms")
        sr_sa = metric_list("sr_minus_sa_ms")
        wait_l = metric_list("wait_ms")
        nav_pre_l = metric_list("nav_pre_ms")
        crop_stage_l = metric_list("crop_stage_ms")
        crop_conv_l = metric_list("crop_conv_ms")
        crop_calc_l = metric_list("crop_calc_ms")
        gui_deliv_l = metric_list("gui_deliver_ms")

        first = items[0]
        summary_rows.append({
            "cell_id": cid,
            "param": first["param"],
            "zoom": first["zoom"],
            "cache": first["cache"],
            "hdr": first["hdr"],
            "denoise": first["denoise"],
            "samples_total": total,
            "samples_ready": len(successes),
            "samples_rejected": len(rejected),
            "samples_incomplete": incomplete,
            "success_rate": round(success_rate * 100, 1),
            "applied_p50_ms": round(percentile(applied_times, 0.5), 2),
            "applied_p95_ms": round(percentile(applied_times, 0.95), 2),
            "ready_p50_ms": round(percentile(ready_times, 0.5), 2),
            "ready_p95_ms": round(percentile(ready_times, 0.95), 2),
            "sq_s0_p50_ms": round(percentile(sq_s0, 0.5), 2) if sq_s0 else None,
            "sg_sq_p50_ms": round(percentile(sg_sq, 0.5), 2) if sg_sq else None,
            "sa_sg_p50_ms": round(percentile(sa_sg, 0.5), 2) if sa_sg else None,
            "sa_sg_p95_ms": round(percentile(sa_sg, 0.95), 2) if sa_sg else None,
            "sp_sa_p50_ms": round(percentile(sp_sa, 0.5), 2) if sp_sa else None,
            "ss_sp_p50_ms": round(percentile(ss_sp, 0.5), 2) if ss_sp else None,
            "sn_sa_p50_ms": round(percentile(sn_sa, 0.5), 2) if sn_sa else None,
            "sc_sa_p50_ms": round(percentile(sc_sa, 0.5), 2) if sc_sa else None,
            "sc_sa_p95_ms": round(percentile(sc_sa, 0.95), 2) if sc_sa else None,
            "sr_sa_p50_ms": round(percentile(sr_sa, 0.5), 2) if sr_sa else None,
            "wait_p50_ms": round(percentile(wait_l, 0.5), 2) if wait_l else None,
            "nav_pre_p50_ms": round(percentile(nav_pre_l, 0.5), 2) if nav_pre_l else None,
            "crop_stage_p50_ms": round(percentile(crop_stage_l, 0.5), 2) if crop_stage_l else None,
            "crop_conv_p50_ms": round(percentile(crop_conv_l, 0.5), 2) if crop_conv_l else None,
            "crop_calc_p50_ms": round(percentile(crop_calc_l, 0.5), 2) if crop_calc_l else None,
            "gui_deliver_p50_ms": round(percentile(gui_deliv_l, 0.5), 2) if gui_deliv_l else None,
        })
    return summary_rows, len(cells)


def write_perf_reports(out_dir, csv_rows, client_samples, manifest):
    out_dir.mkdir(parents=True, exist_ok=True)
    client_jsonl = out_dir / "client.jsonl"
    with open(client_jsonl, "w", encoding="utf-8") as f:
        for s in client_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    samples_csv = out_dir / "samples.csv"
    if csv_rows:
        with open(samples_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    summary_rows, total_cells = summarize_rows(csv_rows)
    summary_csv = out_dir / "summary.csv"
    if summary_rows:
        with open(summary_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    manifest["total_samples"] = len(csv_rows)
    manifest["total_cells"] = total_cells
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_batch_dirs(merge_dirs_csv, out_dir):
    dirs = [Path(d.strip()).resolve() for d in merge_dirs_csv.split(",") if d.strip()]
    assert dirs, "No directories passed to --merge-dirs"
    merged_rows = []
    merged_client = []
    client_parse_errors = []
    source_manifests = []
    merge_errors = []
    log_errors_from_batches = []
    seen_batches = set()
    merged_batches = []
    ref_mf = None

    compare_keys = (
        "parameters",
        "repeats_per_batch",
        "warm_repeats_per_batch",
        "core_boost_per_batch",
        "app_binary_sha256",
        "git_commit",
        "git_dirty",
        "common_trace_patch_sha256",
        "raw_file_sha256",
        "profile_sha256",
        "mode",
        "poll_interval_s",
        "startup_quiet_window_s",
        "trace_enabled",
    )

    for d in dirs:
        mf_path = d / "manifest.json"
        if not mf_path.exists():
            merge_errors.append(f"Batch missing manifest.json: {d}")
            continue
        try:
            mf = json.loads(mf_path.read_text(encoding="utf-8"))
        except Exception as exc:
            merge_errors.append(f"Batch invalid manifest.json in {d}: {exc}")
            continue
        source_manifests.append(mf)

        run_type = mf.get("run_type") or "perf_benchmark"
        if run_type != "perf_benchmark":
            merge_errors.append(f"Batch {d} has run_type={run_type!r}; cannot merge into perf_benchmark")

        if not validate_directory(d, update_manifest=False):
            merge_errors.append(f"Batch validation failed: {d}")

        b_list, b_errs = resolve_planned_batches(mf)
        for be in b_errs:
            merge_errors.append(f"Batch {d}: {be}")
        for b in b_list:
            if b in seen_batches:
                merge_errors.append(f"Duplicate batch id {b} across merge directories (at {d})")
            else:
                seen_batches.add(b)
                merged_batches.append(b)

        if ref_mf is None:
            ref_mf = mf
        else:
            for k in compare_keys:
                if mf.get(k) != ref_mf.get(k):
                    merge_errors.append(
                        f"Cross-batch mismatch for '{k}' in {d}: {mf.get(k)!r} != {ref_mf.get(k)!r}"
                    )

        samples_path = d / "samples.csv"
        if samples_path.exists():
            with open(samples_path, "r", encoding="utf-8") as f:
                merged_rows.extend(list(csv.DictReader(f)))
        else:
            merge_errors.append(f"Batch missing samples.csv: {samples_path}")

        csamples, cerrors = load_client_jsonl(d / "client.jsonl")
        merged_client.extend(csamples)
        client_parse_errors.extend([f"{d.name}: {e}" for e in cerrors])

    base0 = dict(source_manifests[0]) if source_manifests else {}
    base0["run_id"] = out_dir.name
    base0["run_type"] = "perf_benchmark"
    base0["date"] = time.strftime("%Y-%m-%d %H:%M:%S")
    base0["merged_from"] = [str(d) for d in dirs]
    base0["batches"] = merged_batches
    base0["merged_batches"] = merged_batches
    base0["batch_commits"] = [m.get("git_commit") for m in source_manifests]
    base0["batch_binary_sha256s"] = [m.get("app_binary_sha256") for m in source_manifests]

    eval_res, _, _, _ = evaluate_perf_artifacts(
        manifest=base0,
        client_samples=merged_client,
        client_parse_errors=client_parse_errors + log_errors_from_batches,
        trace_file=None,
        extra_perf_errors=merge_errors,
    )
    base0.update({k: v for k, v in eval_res.items() if k != "attempted_samples"})
    write_perf_reports(out_dir, merged_rows, merged_client, base0)
    print(
        f"Merged {len(dirs)} batch dirs -> {out_dir} ({len(merged_rows)} samples, "
        f"log_integrity={base0['log_integrity_status']}, perf_run={base0['perf_run_status']})"
    )
    if base0["status"] != "PASSED":
        print(f"MERGE VALIDATION FAILED ({base0['validation_error_count']} error(s)):", file=sys.stderr)
        for e in base0["validation_errors"][:25]:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="LiveParam real-time numeric performance probe")
    parser.add_argument("--repo-dir", default=".", help="Git repo root for git metadata, rtdata, default binary")
    parser.add_argument("--app", default=None, help="Path to test_liveparam_app or bundle")
    parser.add_argument("--raw", default="data/fivek_sample/sample1.nef", help="RAW file")
    parser.add_argument("--output-dir", default=None, help="Directory to save artifacts")
    parser.add_argument("--validate-dir", default=None, help="Validate existing artifacts directory and exit")
    parser.add_argument("--merge-dirs", default=None, help="Comma-separated batch dirs to validate and merge")
    parser.add_argument("--mode", choices=["persistent", "client"], default="persistent")
    parser.add_argument("--repeats", type=int, default=10, help="Initial launches & warm repeats per cell per batch")
    parser.add_argument("--warm-repeats", type=int, default=None, help="Warm repeats per batch (defaults to --repeats)")
    parser.add_argument("--core-boost", type=int, default=0, help="Extra warm samples per batch on Stage 2/3 100%% core cells")
    parser.add_argument("--batches", type=int, default=3, help="Number of independent batches")
    parser.add_argument("--batch-ids", default=None, help="Explicit comma-separated batch numbers, e.g. '1' or '2,3'")
    parser.add_argument("--params", default="exposure,saturation,temperature,sharpening",
                        help="Comma-separated params (exposure,saturation,temperature,sharpening,exposure_builtin)")
    parser.add_argument("--no-trace", action="store_true", help="Disable ART_LIVE_PARAM_TRACE for trace OFF comparison")
    parser.add_argument("--trace-patch-sha256", default=None, help="SHA-256 of common instrumentation patch")
    parser.add_argument("--variant", default="candidate", help="Variant tag recorded in manifest.json")
    parser.add_argument("--quick", action="store_true", help="Quick run with 1 batch and 5 repeats")
    args = parser.parse_args()

    if args.validate_dir:
        sys.exit(0 if validate_directory(args.validate_dir, update_manifest=False) else 1)

    if args.merge_dirs:
        out_dir = Path(args.output_dir or "build/liveparam-perf-checks/merged").resolve()
        merge_batch_dirs(args.merge_dirs, out_dir)
        return

    repo_dir = Path(args.repo_dir).resolve()
    cwd_dir = Path.cwd().resolve()
    if args.quick:
        args.repeats = 5
        args.batches = 1

    batch_id_list = (
        [int(x.strip()) for x in args.batch_ids.split(",") if x.strip()]
        if args.batch_ids else list(range(1, args.batches + 1))
    )
    assert batch_id_list, "batches cannot be empty"
    assert len(batch_id_list) == len(set(batch_id_list)), f"Duplicate batch ids: {batch_id_list}"
    warm_repeats = args.warm_repeats if args.warm_repeats is not None else args.repeats
    trace_enabled = not args.no_trace

    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (cwd_dir / f"build/liveparam-perf-checks/{run_id}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    app_bin = stage_bundle(repo_dir, src_bin_override=args.app)
    raw_path = Path(args.raw)
    if not raw_path.is_absolute():
        raw_path = (repo_dir / raw_path).resolve()
    assert raw_path.exists(), f"RAW file not found: {raw_path}"

    target_params = [p.strip() for p in args.params.split(",") if p.strip()]
    param_pools = {
        "exposure": {"values": [-0.5, -0.25, 0.25, 0.5, -0.35, 0.35, -0.15, 0.15, 0.45, -0.45], "is_builtin": False},
        "exposure_builtin": {"values": [-0.5, -0.25, 0.25, 0.5, -0.35, 0.35, -0.15, 0.15, 0.45, -0.45], "is_builtin": True},
        "saturation": {"values": [10.0, 15.0, 20.0, 25.0, 12.0, 18.0, 22.0, 28.0, 14.0, 24.0], "is_builtin": False},
        "temperature": {"values": [5000.0, 5600.0, 6200.0, 6800.0, 5300.0, 5900.0, 6500.0, 7100.0, 5200.0, 6100.0], "is_builtin": False},
        "sharpening": {"values": [0.6, 0.75, 0.9, 1.05, 1.2, 0.65, 0.8, 0.95, 1.1, 1.25], "is_builtin": False},
    }
    for p in target_params:
        assert p in param_pools, f"Unknown param {p!r}"

    zoom_levels = ["fit", "100"]
    hdr_states = [0, 1]
    denoise_states = [0, 1]

    trace_file = out_dir / "trace.jsonl"
    if trace_file.exists():
        trace_file.unlink()

    poll_interval_s = 0.003 if args.mode == "persistent" else 0.05
    options_file = repo_dir / "rtdata/options/options.osx"

    print(f"=== ART LiveParam Performance Benchmark: {run_id} ({args.variant}) ===")
    print(f"  Repo: {repo_dir}")
    print(f"  App: {app_bin}")
    print(f"  RAW: {raw_path}")
    print(f"  Mode: {args.mode} (poll={poll_interval_s}s, trace={'ON' if trace_enabled else 'OFF'})")
    print(f"  Batches: {batch_id_list}, Initials/cell/batch: {args.repeats}, Warm/cell/batch: {warm_repeats}, Core boost: {args.core_boost}")
    print(f"  Params: {target_params}")
    print(f"  Output: {out_dir}")

    all_client_samples = []
    profile_hashes = {}
    launch_errors = []

    try:
        for batch_idx in batch_id_list:
            print(f"\n--- Batch {batch_idx} ---")
            for hdr in hdr_states:
                for denoise in denoise_states:
                    arp_text = build_arp_text(hdr, denoise)
                    profile_hashes[f"hdr{hdr}_dn{denoise}"] = hashlib.sha256(arp_text.encode("utf-8")).hexdigest()
                    for zoom in zoom_levels:
                        for param_name in target_params:
                            pool = param_pools[param_name]["values"]
                            is_builtin = param_pools[param_name]["is_builtin"]
                            for rep in range(args.repeats):
                                init_val = pool[rep % len(pool)]
                                collect_warm = (rep == args.repeats - 1)
                                warm_vals = generate_distinct_values(pool, warm_repeats, avoid_value=init_val) if collect_warm else []
                                extra_n = args.core_boost if (collect_warm and args.core_boost > 0 and (param_name, zoom, hdr, denoise) in CORE_BOOST_SET) else 0
                                last_warm = warm_vals[-1] if warm_vals else init_val
                                boost_vals = generate_distinct_values(pool, extra_n, avoid_value=last_warm) if extra_n else []

                                work = out_dir / f"work_b{batch_idx}_hdr{hdr}_dn{denoise}_{zoom}_{param_name}_r{rep}"
                                samples = run_single_launch(
                                    app_bin=app_bin, raw_path=raw_path, options_file=options_file,
                                    arp_text=arp_text, trace_file=trace_file, work_dir=work,
                                    mode=args.mode, zoom=zoom, hdr=hdr, denoise=denoise,
                                    batch_idx=batch_idx, param_name=param_name, init_val=init_val,
                                    warm_vals=warm_vals, core_boost_vals=boost_vals,
                                    poll_interval_s=poll_interval_s, is_builtin=is_builtin,
                                    trace_enabled=trace_enabled,
                                )
                                all_client_samples.extend(samples)
                            sys.stdout.write(".")
                            sys.stdout.flush()
    except Exception as exc:
        launch_errors.append(f"Benchmark launch interrupted: {exc}")

    print("\nBenchmark runs completed. Processing trace and generating reports...")

    git_commit = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()
    dirty_lines = [
        ln for ln in subprocess.check_output(["git", "-C", str(repo_dir), "status", "--porcelain"], text=True).splitlines()
        if ln.strip()
    ]
    git_dirty = bool(dirty_lines)

    real_bin = app_bin.resolve() if app_bin.is_symlink() else app_bin
    manifest = {
        "run_id": run_id,
        "run_type": "perf_benchmark",
        "variant": args.variant,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo_dir": str(repo_dir),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "dirty_files": dirty_lines,
        "common_trace_patch_sha256": args.trace_patch_sha256,
        "probe_script_sha256": file_sha256(Path(__file__).resolve()),
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpu_count": os.cpu_count(),
        "command": sys.argv,
        "app_binary": str(real_bin),
        "app_binary_sha256": file_sha256(real_bin),
        "raw_file": str(raw_path),
        "raw_file_sha256": file_sha256(raw_path),
        "profile_sha256": profile_hashes,
        "parameters": target_params,
        "batches": batch_id_list,
        "repeats_per_batch": args.repeats,
        "warm_repeats_per_batch": warm_repeats,
        "core_boost_per_batch": args.core_boost,
        "mode": args.mode,
        "poll_interval_s": poll_interval_s,
        "startup_quiet_window_s": 0.05,
        "trace_enabled": trace_enabled,
        "env_policy": {
            "ART_LIVE_PARAM": "1",
            "ART_LIVE_PARAM_INITIAL_ZOOM": "100|fit",
            "ART_LIVE_PARAM_TRACE": str(trace_file) if trace_enabled else None,
        },
        "pp_version": 1045,
        "launch_errors": launch_errors,
    }

    eval_res, server_events, engine_stages, crop_stages = evaluate_perf_artifacts(
        manifest=manifest,
        client_samples=all_client_samples,
        client_parse_errors=[],
        trace_file=trace_file if trace_enabled else None,
        extra_perf_errors=launch_errors,
    )
    csv_rows = build_csv_rows(all_client_samples, server_events, engine_stages, crop_stages)
    manifest.update({k: v for k, v in eval_res.items() if k != "attempted_samples"})
    write_perf_reports(out_dir, csv_rows, all_client_samples, manifest)

    print(f"\nReport generated at: {out_dir}")
    print(f"  - Manifest: manifest.json (git_dirty={git_dirty})")
    print(f"  - Client events: client.jsonl ({len(all_client_samples)} attempted)")
    print(f"  - Samples CSV: samples.csv ({len(csv_rows)} samples)")
    print(f"  - Summary CSV: summary.csv")
    print(
        f"  - Verdict: status={manifest['status']} "
        f"(log_integrity={manifest['log_integrity_status']}, perf_run={manifest['perf_run_status']})"
    )
    if manifest["status"] != "PASSED":
        print(f"FAILED: validation detected {manifest['validation_error_count']} error(s):", file=sys.stderr)
        for e in manifest["validation_errors"][:25]:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
