#!/usr/bin/env python3
"""저장된 실제 호출·원문·브리지·REPL 증거를 호출 없이 다시 대조한다."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
spec = importlib.util.spec_from_file_location("cp3_frozen_run", OUT / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(name):
    path = OUT / name
    if Path(str(path) + ".gz").exists():
        with gzip.open(str(path) + ".gz", "rt", encoding="utf-8") as stream:
            text = stream.read()
    else:
        text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def verify_records():
    from artagent.graph.answer import validate_and_project_bundle
    from artagent.graph.state import Evidence, RetrievalBundle
    from t15_evaluation import _verify_code_identity

    manifest = json.loads((OUT / "manifest.json").read_bytes())
    _verify_code_identity(manifest["code_commit"], manifest["code_hashes"], historical=False)
    with gzip.open(OUT / "run-at-execution.py.gz", "rb") as stream:
        assert hashlib.sha256(stream.read()).hexdigest() == manifest["harness_sha256"]
    runtime_files = json.loads((OUT / "runtime-files.json").read_bytes())
    for rel, expected in runtime_files["sha256"].items():
        assert sha(ROOT / rel) == expected
        pinned = subprocess.check_output(["git", "show", runtime_files["commit"] + ":" + rel], cwd=ROOT)
        assert hashlib.sha256(pinned).hexdigest() == expected
    for rel, expected in manifest["inputs"].items():
        assert sha(ROOT / rel) == expected, rel
    canonical = {q["query_id"]: q["query"] for q in json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())["queries"]}
    entries = rows("records.jsonl")
    assert [r["query_id"] for r in entries] == [*run.IDS, *run.EXTRA, "MISSING_ISSUE"]
    for r in entries:
        qid, trace = r["query_id"], r["result"]["trace"]
        assert r["query"] == canonical.get(qid, run.MISSING)
        assert trace.count("RESEARCH") == r["result"]["research_count"] <= 1
        assert r["result"]["response"]["status"] in ("COMPLETED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE")
        searches = r["searches"]
        assert len(searches) == 1 + trace.count("RESEARCH")
        assert trace.count("ANSWER") == len(r["answers"]) == len(searches)
        assert sum(s["search_call_count"] for s in searches) == len(searches)
        for search in searches:
            assert not search["error"]
            assert (search["candidate_k"], search["top_k"], search["min_score"], search["rerank_weight"]) == (20, 5, 0.5, 0.25)
            if "GitHub" in r["query"]:
                assert search["source_group_ids"] and len(search["source_group_ids"]) == 1
        for node in r["nodes"]:
            if node["node"].startswith("SEARCH_"):
                b = node["update"]["retrieval"]
                validate_and_project_bundle(RetrievalBundle(**{**b, "hits": [Evidence(**e) for e in b["hits"]]}), ROOT)
        for answer in r["answers"]:
            assert not answer["error"] and answer["call_count"] == 1
        if len(r["answers"]) == 2:
            assert json.loads(r["answers"][0]["raw_response"])["status"] == "INSUFFICIENT_EVIDENCE"
            assert searches[0]["source_type"] == searches[1]["source_type"]
            assert searches[0]["source_group_ids"] == searches[1]["source_group_ids"]
        assert len(r["calls"]) == 2 + 2 * trace.count("RESEARCH")
        for call in r["calls"]:
            assert not call.get("error")
            assert call["runtime"]["model_id"] == "gpt-5.6-sol"
            execution = call["execution"]
            assert execution["process_returncode"] == 0 and not execution["process_error"]
            assert execution["execution_policy"]["application_status"] == "confirmed"
            assert execution["execution_policy"]["tools_enabled"] is False
            assert execution["validation"]["additional_tool_count"] == 0
            assert execution["validation"]["status"] == "verified"
    q96 = next(r for r in entries if r["query_id"] == "Q096")
    assert q96["result"]["response"]["status"] == "UNSUPPORTED" and q96["result"]["research_count"] == 0
    assert any("4711197631" in c["url"] for c in q96["result"]["response"]["citations"])
    print("RECORDS_VERIFIED")


def verify_fallback():
    run.records = lambda: rows("records.jsonl")
    run.verify_fallback()


def verify_interfaces():
    expected = [("Q001", "COMPLETED", "DOC_QA"), ("Q086", "COMPLETED", "TROUBLESHOOT"), ("Q096", "UNSUPPORTED", "TROUBLESHOOT"), ("MISSING_ISSUE", "INSUFFICIENT_EVIDENCE", "TROUBLESHOOT"), ("EXECUTE", "UNSUPPORTED", "EXECUTE")]
    bridge = rows("bridge-records.jsonl")
    assert len(bridge) == len(expected)
    observations = {r["request"]["request_id"]: r for r in rows("gui-records.jsonl") if r["event"] == "completed"}
    for record, (qid, status, route) in zip(bridge, expected):
        response = record["response"]
        assert record["query_id"] == qid and record["returncode"] == 0
        assert json.loads(record["stdout"]) == response
        assert response["status"] == status and response["steps"][0]["path"] == route
        observation = observations[record["request"]["request_id"]]
        trace = observation["trace"]
        assert observation["research_count"] == int(qid == "MISSING_ISSUE")
        assert trace.count("RESEARCH") == int(qid == "MISSING_ISSUE")
        if qid == "MISSING_ISSUE":
            assert trace.count("ANSWER") == trace.count("SEARCH_GITHUB") == 2
        if qid == "EXECUTE":
            assert not any(node.startswith("SEARCH_") for node in trace) and "ANSWER" not in trace
        assert 0 < record["elapsed_seconds"] < 300
    cli = json.loads((OUT / "cli-record.json").read_bytes())
    assert cli["returncode"] == 0
    for marker in ["[COMPLETED]", "[UNSUPPORTED]", "[INSUFFICIENT_EVIDENCE]", "#issuecomment-4711197631", "https://rawpedia.rawtherapee.com/exposure/"]:
        assert marker in cli["stdout"], marker
    print("INTERFACES_VERIFIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("records", "fallback", "interfaces"))
    action = parser.parse_args().action
    {"records": verify_records, "fallback": verify_fallback, "interfaces": verify_interfaces}[action]()
