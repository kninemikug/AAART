#!/usr/bin/env python3
"""실시간 수치 조정 지연 측정 하네스 및 성능 프로브 (WBS §1.2~1.5 구현).

macOS Unix socket 상에서 실제 GUI 프로세스를 구동하고,
시나리오 매트릭스(노출, 채도, 색온도, 샤프닝 × 배율 × 캐시 × HDR × 노이즈제거)에 대해
클라이언트 RTT(C0, CA, CR) 및 서버 구간(S0, SQ, SG, SA, SP, SS, SN, SC, SR)을 수집하고
p50/p95 및 구간별 기여도를 분석하여 manifest.json, client.jsonl, trace.jsonl,
samples.csv, summary.csv를 생성한다.
"""

import argparse
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


def stage_bundle(root_dir):
    root = Path(root_dir).resolve()
    bundle = root / "build/ARTLiveParamTest.app"
    macos = bundle / "Contents/MacOS"
    res = bundle / "Contents/Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)

    app_bin = macos / "test_liveparam_app"
    src_bin = root / "build/rtgui/test_liveparam_app"
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
                 poll_interval_s=0.003, is_builtin=False, enable_tool=True):
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
        })

    target["baseRevision"] = base_rev
    return samples


REQUIRED_MUTATION_EVENTS = ("S0", "SQ", "SG", "SA", "SP", "SS", "SN", "SC", "SR")
MONOTONIC_PAIRS = (
    ("S0", "SQ"), ("SQ", "SG"), ("SG", "SA"), ("SA", "SP"), ("SP", "SS"),
    ("SA", "SN"), ("SA", "SC"), ("SN", "SR"), ("SC", "SR"),
)


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

    with open(trace_file, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
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

            if ev_name == "ENGINE_DONE":
                gen = ev.get("generation")
                if gen:
                    engine_stages[gen] = ev.get("detail", "")
                continue
            if ev_name == "CROP_DONE":
                gen = ev.get("generation")
                detail = ev.get("detail", "")
                if gen and ("crop:main=1" in detail or gen not in crop_stages):
                    crop_stages[gen] = detail
                continue
            if ev_name == "ENGINE_CHANGE":
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

        indexed_by_req[req_id] = merged

    return errors, indexed_by_req, engine_stages, crop_stages


def validate_directory(dir_path):
    """Validate an existing perf output directory and raise SystemExit(1) on any error."""
    target = Path(dir_path).resolve()
    client_file = target / "client.jsonl"
    trace_file = target / "trace.jsonl"
    manifest_file = target / "manifest.json"
    errors = []
    client_samples = []
    if not client_file.exists():
        errors.append(f"Missing client.jsonl: {client_file}")
    else:
        with open(client_file, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                s = raw.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    if not isinstance(obj, dict):
                        errors.append(f"client line {lineno}: expected JSON object")
                    else:
                        client_samples.append(obj)
                except Exception as exc:
                    errors.append(f"client line {lineno}: invalid JSON ({exc})")
    trace_errors, indexed, engine_stages, crop_stages = validate_and_index_trace(
        trace_file, client_samples
    )
    errors.extend(trace_errors)
    if errors:
        manifest = {}
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                manifest = {"raw_manifest_corrupt": True}
        manifest["status"] = "FAILED"
        manifest["validation_error_count"] = len(errors)
        manifest["validation_errors"] = errors[:50]
        manifest_file.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"VALIDATION FAILED ({len(errors)} error(s)):", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        return False
    print(
        f"VALIDATION PASSED: {len(indexed)} READY samples, "
        f"{len(engine_stages)} ENGINE_DONE, {len(crop_stages)} CROP_DONE"
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="LiveParam real-time numeric performance probe")
    parser.add_argument("--app", default=None, help="Path to test_liveparam_app or bundle")
    parser.add_argument("--raw", default="data/fivek_sample/sample1.nef", help="RAW file")
    parser.add_argument("--output-dir", default=None, help="Directory to save artifacts")
    parser.add_argument("--validate-dir", default=None, help="Validate existing artifacts directory and exit")
    parser.add_argument("--mode", choices=["persistent", "client"], default="persistent")
    parser.add_argument("--repeats", type=int, default=10, help="Repeats per cell per batch")
    parser.add_argument("--batches", type=int, default=3, help="Number of independent batches")
    parser.add_argument("--params", default="exposure,saturation,temperature,sharpening",
                        help="Comma-separated params")
    parser.add_argument("--quick", action="store_true", help="Quick run with 1 batch and 5 repeats")
    args = parser.parse_args()

    if args.validate_dir:
        sys.exit(0 if validate_directory(args.validate_dir) else 1)

    root_dir = Path.cwd()
    if args.quick:
        args.repeats = 5
        args.batches = 1

    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (root_dir / f"build/liveparam-perf-checks/{run_id}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    app_bin = Path(args.app) if args.app else stage_bundle(root_dir)
    raw_path = (root_dir / args.raw).resolve()
    assert raw_path.exists(), f"RAW file not found: {raw_path}"

    target_params = [p.strip() for p in args.params.split(",") if p.strip()]

    # Values sequences for the 4 params (oscillating to ensure real changes)
    param_configs = {
        "exposure": {
            "key": "Exposure.Compensation",
            "values": [round(-0.5 + (i % 5) * 0.25, 2) for i in range(args.repeats)],
            "is_builtin": True
        },
        "saturation": {
            "key": None, # Discovered from catalogue
            "values": [round(10.0 + (i % 5) * 2.5, 1) for i in range(args.repeats)],
            "is_builtin": False
        },
        "temperature": {
            "key": None, # Discovered from catalogue
            "values": [round(5000 + (i % 5) * 300, 0) for i in range(args.repeats)],
            "is_builtin": False
        },
        "sharpening": {
            "key": None, # Discovered from catalogue
            "values": [round(0.6 + (i % 5) * 0.05, 2) for i in range(args.repeats)],
            "is_builtin": False
        }
    }

    all_client_samples = []
    matrix_cells = []

    # Matrix axes:
    # 4 params × 2 zoom (fit, 100) × 2 cache (initial, cached) × 2 HDR (0, 1) × 2 denoise (0, 1)
    # For initial vs cached:
    # An independent batch starts a fresh GUI process, measures the 1st mutation (initial),
    # then subsequent mutations (cached).
    zoom_levels = ["fit", "100"]
    hdr_states = [0, 1]
    denoise_states = [0, 1]

    trace_file = out_dir / "trace.jsonl"
    if trace_file.exists():
        trace_file.unlink()

    print(f"=== ART LiveParam Performance Benchmark: {run_id} ===")
    print(f"  App: {app_bin}")
    print(f"  RAW: {raw_path}")
    print(f"  Mode: {args.mode}")
    print(f"  Batches: {args.batches}, Repeats: {args.repeats}")
    print(f"  Params: {target_params}")
    print(f"  Output: {out_dir}")

    total_cells = len(target_params) * len(zoom_levels) * 2 * len(hdr_states) * len(denoise_states)
    print(f"  Matrix size: {total_cells} cells ({args.batches} batches = {total_cells * args.batches} evaluations)")

    batch_idx = 0
    for batch in range(args.batches):
        batch_idx += 1
        print(f"\n--- Batch {batch_idx}/{args.batches} ---")
        for hdr in hdr_states:
            for denoise in denoise_states:
                for zoom in zoom_levels:
                    # Setup custom options/profile for this combination
                    work = out_dir / f"work_b{batch_idx}_hdr{hdr}_dn{denoise}_{zoom}"
                    if work.exists():
                        shutil.rmtree(work)
                    work.mkdir(parents=True)
                    settings = work / "settings"
                    settings.mkdir()
                    cache = work / "cache"
                    cache.mkdir()

                    # Copy base options
                    shutil.copy2(root_dir / "rtdata/options/options.osx", settings / "options")

                    # Copy sample RAW
                    raw_copy = work / "sample.nef"
                    shutil.copy2(raw_path, raw_copy)

                    # Prepare initial ARP profile with specified HDR & denoise settings
                    profile_arp = work / "sample.nef.arp"
                    arp_lines = [
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
                        arp_lines.extend(["[FattalToneMapping]", "Enabled=true", "Amount=30", "Threshold=40"])
                    else:
                        arp_lines.extend(["[FattalToneMapping]", "Enabled=false"])
                    if denoise:
                        arp_lines.extend(["[Impulse Denoising]", "Enabled=true", "[Denoise]", "Enabled=true"])
                    else:
                        arp_lines.extend(["[Impulse Denoising]", "Enabled=false", "[Denoise]", "Enabled=false"])
                    profile_arp.write_text("\n".join(arp_lines) + "\n")

                    env = {
                        **os.environ,
                        "ART_LIVE_PARAM": "1",
                        "ART_LIVE_PARAM_TRACE": str(trace_file),
                        "ART_SETTINGS": str(settings),
                        "ART_CACHE": str(cache),
                        "ART_LIVE_PARAM_INITIAL_ZOOM": "100" if zoom == "100" else "fit",
                    }

                    # Launch GUI
                    proc = subprocess.Popen([str(app_bin), "-s", str(raw_copy)], env=env)
                    proc_alive = True
                    try:
                        # Wait for socket
                        deadline = time.monotonic() + 15.0
                        sock_path = None
                        while time.monotonic() < deadline:
                            socks = glob.glob(f"/tmp/art-liveparam-{os.geteuid()}/art-{proc.pid}-*.sock")
                            if socks:
                                sock_path = socks[0]
                                break
                            time.sleep(0.05)
                        assert sock_path, f"Process {proc.pid} did not open socket"

                        client = LiveParamClient(sock_path, persistent=(args.mode == "persistent"), timeout=15.0)

                        # Wait for initial get_state and initial render (including 100% zoom M_HIGHQUAL settle)
                        init_state = None
                        deadline = time.monotonic() + 30.0
                        while time.monotonic() < deadline:
                            try:
                                s = client.rpc({"protocolVersion": 1, "requestId": f"init-{uuid.uuid4().hex[:4]}", "op": "get_state"})
                                editors = s.get("result", {}).get("editors", [])
                                if editors:
                                    editor_id = editors[0]["editorId"]
                                    sess_id = s["sessionId"]
                                    st = client.rpc({"protocolVersion": 1, "requestId": f"init-st-{uuid.uuid4().hex[:4]}", "op": "get_state", "editorId": editor_id})
                                    res = st.get("result", {})
                                    rev = res.get("revision")
                                    r_rev = res.get("renderedRevision")
                                    v_rev = res.get("viewRevision")
                                    rv_rev = res.get("renderedViewRevision")
                                    if (r_rev is not None and r_rev == rev and
                                            rv_rev is not None and rv_rev == v_rev and
                                            (zoom != "100" or v_rev >= 1)):
                                        init_state = st
                                        break
                            except Exception:
                                pass
                            time.sleep(0.1)
                        assert init_state, "GUI did not complete initial render"

                        target = {
                            "sessionId": sess_id,
                            "editorId": editor_id,
                            "baseRevision": init_state["result"]["renderedRevision"]
                        }

                        # Catalog discovery for numeric controls
                        offset = 0
                        context_id = None
                        all_items = []
                        while True:
                            cat_req = {
                                "protocolVersion": 1,
                                "requestId": f"cat-{offset}-{uuid.uuid4().hex[:4]}",
                                "op": "list_params",
                                "sessionId": sess_id,
                                "editorId": editor_id,
                                "baseRevision": target["baseRevision"],
                                "offset": offset,
                                "limit": 32
                            }
                            if context_id:
                                cat_req["contextId"] = context_id
                            cat = client.rpc(cat_req)
                            context_id = cat.get("result", {}).get("contextId", context_id)
                            items = cat.get("result", {}).get("items", [])
                            all_items.extend(items)
                            next_off = cat.get("result", {}).get("nextOffset")
                            if not next_off:
                                break
                            offset = next_off

                        # Find IDs for saturation, temperature, sharpening
                        for item in all_items:
                            tool = item.get("tool", "").lower()
                            label = item.get("label", "").lower()
                            key = item.get("key", "")
                            if tool == "saturation" and label == "saturation":
                                param_configs["saturation"]["key"] = key
                            elif tool == "whitebalance" and label == "temperature":
                                param_configs["temperature"]["key"] = key
                            elif tool == "sharpening" and label == "radius":
                                param_configs["sharpening"]["key"] = key

                        # Fallback keys if not found by name
                        if not param_configs["saturation"]["key"]:
                            param_configs["saturation"]["key"] = "saturation.amount"
                        if not param_configs["temperature"]["key"]:
                            param_configs["temperature"]["key"] = "whitebalance.temperature"
                        if not param_configs["sharpening"]["key"]:
                            param_configs["sharpening"]["key"] = "sharpening.radius"

                        # Run each parameter
                        for param_name in target_params:
                            cfg = param_configs[param_name]
                            pkey = cfg["key"]
                            values = cfg["values"]

                            # First mutation is "initial"
                            initial_val = [values[0]]
                            cached_vals = values[1:] if len(values) > 1 else [values[0]]

                            # Cell 1: initial
                            cell_id_init = f"{param_name}_{zoom}_init_hdr{hdr}_dn{denoise}"
                            init_samples = run_scenario(
                                client, target, param_name, pkey, initial_val,
                                is_initial=True,
                                poll_interval_s=(0.003 if args.mode == "persistent" else 0.05),
                                is_builtin=cfg["is_builtin"]
                            )
                            for s in init_samples:
                                s.update({
                                    "batch": batch_idx, "cell_id": cell_id_init,
                                    "param": param_name, "zoom": zoom, "cache": "initial",
                                    "hdr": hdr, "denoise": denoise
                                })
                            all_client_samples.extend(init_samples)

                            # Cell 2: cached
                            cell_id_cache = f"{param_name}_{zoom}_cache_hdr{hdr}_dn{denoise}"
                            cached_samples = run_scenario(
                                client, target, param_name, pkey, cached_vals,
                                is_initial=False,
                                poll_interval_s=(0.003 if args.mode == "persistent" else 0.05),
                                is_builtin=cfg["is_builtin"]
                            )
                            for s in cached_samples:
                                s.update({
                                    "batch": batch_idx, "cell_id": cell_id_cache,
                                    "param": param_name, "zoom": zoom, "cache": "cached",
                                    "hdr": hdr, "denoise": denoise
                                })
                            all_client_samples.extend(cached_samples)

                            sys.stdout.write(f".")
                            sys.stdout.flush()

                        client.close()
                        time.sleep(0.2)
                    finally:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()

    print("\nBenchmark runs completed. Processing trace and generating reports...")

    # Write client.jsonl (preserve raw data before validation)
    client_jsonl = out_dir / "client.jsonl"
    with open(client_jsonl, "w", encoding="utf-8") as f:
        for s in all_client_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # Validate trace.jsonl strictly against client_samples
    trace_errors, server_events, engine_stages, crop_stages = validate_and_index_trace(
        trace_file, all_client_samples
    )

    # Merge into samples.csv
    samples_csv = out_dir / "samples.csv"
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

        def delta_ms(t_end, t_start):
            return (t_end - t_start) / 1e6 if (t_end and t_start and t_end >= t_start) else None

        row = {
            "requestId": req_id,
            "sessionId": s.get("sessionId"),
            "editorId": s.get("editorId"),
            "batch": s["batch"],
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
            "polls": s["polls"],
            "engine_stages": engine_stages.get(sr_gen, ""),
            "crop_stages": crop_stages.get(sr_gen, ""),
        }
        csv_rows.append(row)

    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        with open(samples_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

    # Aggregate into summary.csv
    cells = {}
    for r in csv_rows:
        cid = r["cell_id"]
        if cid not in cells:
            cells[cid] = []
        cells[cid].append(r)

    summary_rows = []
    for cid, items in sorted(cells.items()):
        total = len(items)
        successes = [it for it in items if it["status"] == "READY"]
        success_rate = len(successes) / total if total else 0.0

        applied_times = [it["applied_rtt_ms"] for it in items if it["applied_rtt_ms"] is not None]
        ready_times = [it["ready_rtt_ms"] for it in successes if it["ready_rtt_ms"] is not None]

        sq_s0 = [it["sq_minus_s0_ms"] for it in items if it["sq_minus_s0_ms"] is not None]
        sg_sq = [it["sg_minus_sq_ms"] for it in items if it["sg_minus_sq_ms"] is not None]
        sa_sg = [it["sa_minus_sg_ms"] for it in items if it["sa_minus_sg_ms"] is not None]
        sp_sa = [it["sp_minus_sa_ms"] for it in items if it["sp_minus_sa_ms"] is not None]
        ss_sp = [it["ss_minus_sp_ms"] for it in items if it["ss_minus_sp_ms"] is not None]
        sn_sa = [it["sn_minus_sa_ms"] for it in items if it["sn_minus_sa_ms"] is not None]
        sc_sa = [it["sc_minus_sa_ms"] for it in items if it["sc_minus_sa_ms"] is not None]
        sr_sa = [it["sr_minus_sa_ms"] for it in items if it["sr_minus_sa_ms"] is not None]

        first = items[0]
        s_row = {
            "cell_id": cid,
            "param": first["param"],
            "zoom": first["zoom"],
            "cache": first["cache"],
            "hdr": first["hdr"],
            "denoise": first["denoise"],
            "samples_total": total,
            "success_rate": round(success_rate * 100, 1),
            "applied_p50_ms": round(percentile(applied_times, 0.5), 2),
            "applied_p95_ms": round(percentile(applied_times, 0.95), 2),
            "ready_p50_ms": round(percentile(ready_times, 0.5), 2),
            "ready_p95_ms": round(percentile(ready_times, 0.95), 2),
            "sq_s0_p50_ms": round(percentile(sq_s0, 0.5), 2) if sq_s0 else None,
            "sg_sq_p50_ms": round(percentile(sg_sq, 0.5), 2) if sg_sq else None,
            "sa_sg_p50_ms": round(percentile(sa_sg, 0.5), 2) if sa_sg else None,
            "sp_sa_p50_ms": round(percentile(sp_sa, 0.5), 2) if sp_sa else None,
            "ss_sp_p50_ms": round(percentile(ss_sp, 0.5), 2) if ss_sp else None,
            "sn_sa_p50_ms": round(percentile(sn_sa, 0.5), 2) if sn_sa else None,
            "sc_sa_p50_ms": round(percentile(sc_sa, 0.5), 2) if sc_sa else None,
            "sr_sa_p50_ms": round(percentile(sr_sa, 0.5), 2) if sr_sa else None,
        }
        summary_rows.append(s_row)

    summary_csv = out_dir / "summary.csv"
    if summary_rows:
        with open(summary_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    # Manifest metadata
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    git_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())

    manifest = {
        "run_id": run_id,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpu_count": os.cpu_count(),
        "app_binary": str(app_bin),
        "app_binary_sha256": file_sha256(app_bin),
        "raw_file": str(raw_path),
        "raw_file_sha256": file_sha256(raw_path),
        "parameters": target_params,
        "batches": args.batches,
        "repeats_per_batch": args.repeats,
        "mode": args.mode,
        "total_samples": len(all_client_samples),
        "total_cells": len(cells),
        "pp_version": 1045,
        "status": "FAILED" if trace_errors else "PASSED",
        "validation_error_count": len(trace_errors),
        "validation_errors": trace_errors[:50],
    }
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    print(f"\nReport generated at: {out_dir}")
    print(f"  - Manifest: {manifest_file.name}")
    print(f"  - Client events: {client_jsonl.name}")
    print(f"  - Samples CSV: {samples_csv.name}")
    print(f"  - Summary CSV: {summary_csv.name}")
    if trace_errors:
        print(f"FAILED: trace validation detected {len(trace_errors)} error(s):", file=sys.stderr)
        for e in trace_errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
