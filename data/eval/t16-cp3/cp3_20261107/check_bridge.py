#!/usr/bin/env python3
"""네이티브 패널과 같은 표준입출력 명령으로 실제 브리지 응답을 검증한다."""
import json
from pathlib import Path
import subprocess
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
queries = {q["query_id"]: q["query"] for q in json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())["queries"]}
cases = [("Q001", queries["Q001"], "DOC_QA", "COMPLETED"),
         ("Q086", queries["Q086"], "TROUBLESHOOT", "COMPLETED"),
         ("Q096", queries["Q096"], "TROUBLESHOOT", "UNSUPPORTED"),
         ("MISSING_ISSUE", "GitHub Issue #999999999에서 보고한 ART 오류의 원인과 해결 방법은 무엇인가요?", "TROUBLESHOOT", "INSUFFICIENT_EVIDENCE"),
         ("EXECUTE", "이 사진을 자동 보정해서 JPEG로 저장해줘.", "EXECUTE", "UNSUPPORTED")]
target = OUT / "bridge-records.jsonl"
assert not target.exists(), "기존 기록은 덮어쓰지 않습니다."
for qid, text, route, expected in cases:
    payload = {"version": 1, "request_id": "cp3-bridge-" + qid, "text": text}
    command = [str(OUT / "gui-python"), "-u", "-m", "artagent.gui_bridge", "--source-root", str(ROOT), "--persist-dir", str(OUT / "store")]
    started = time.monotonic()
    proc = subprocess.run(command, input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=300, cwd=ROOT)
    try:
        response = json.loads(proc.stdout)
    except Exception:
        response = None
    row = {"query_id": qid, "command": command, "request": payload, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "response": response, "elapsed_seconds": time.monotonic() - started}
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
    assert proc.returncode == 0 and response, row
    assert response["status"] == expected, (qid, response)
    assert response["steps"][0]["path"] == route, (qid, response)
    assert row["elapsed_seconds"] < 300
    print(qid, response["status"], round(row["elapsed_seconds"], 2), flush=True)
print("BRIDGE_VERIFIED", flush=True)
