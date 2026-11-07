#!/usr/bin/env python3
"""실제 REPL의 검색·답변·재검색·종료 표준입출력을 검증한다."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
path = OUT / "cli-record.json"
assert not path.exists(), "기존 실행은 보존합니다."
queries = {q["query_id"]: q["query"] for q in json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())["queries"]}
inputs = "\n".join([queries["Q001"], queries["Q096"], "GitHub Issue #999999999에서 보고한 ART 오류의 원인과 해결 방법은 무엇인가요?", "/quit", ""])
command = [sys.executable, "-m", "artagent.cli", "--reference", str(ROOT / "docs/T08_2_t9_handoff_reference.json"), "--persist-dir", str(OUT / "store"), "--source-root", str(ROOT)]
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"), LLM_PROVIDER="codex", LLM_MODEL="gpt-5.6-sol", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
started = time.monotonic()
proc = subprocess.run(command, input=inputs, capture_output=True, text=True, timeout=300, cwd=ROOT, env=environment)
record = {"command": command, "input": inputs, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "elapsed_seconds": time.monotonic() - started}
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
assert proc.returncode == 0, record
assert "https://rawpedia.rawtherapee.com/exposure/" in proc.stdout
assert "#issuecomment-4711197631" in proc.stdout
assert "[UNSUPPORTED]" in proc.stdout and "[INSUFFICIENT_EVIDENCE]" in proc.stdout
assert "근거" in proc.stdout and "999999999" in proc.stdout
print("CLI_VERIFIED", round(record["elapsed_seconds"], 2), flush=True)
