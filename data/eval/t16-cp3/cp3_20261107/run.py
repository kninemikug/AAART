#!/usr/bin/env python3
"""고정 질문·실제 검색·실제 생성을 연결하고 관측 결과를 별도 보존한다."""

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from unittest.mock import patch

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
REF = ROOT / "docs/T08_2_t9_handoff_reference.json"
REPRO = Path("/private/var/folders/w9/wyg8ltjx56b_s3kk7zk8r1k80000gn/T/pytest-of-user/pytest-452/t09-reproduction0/reproduction")
IDS = ["Q001", "Q004", "Q014", "Q021", "Q033", "Q044", "Q054", "Q063", "Q072", "Q080", "Q084", "Q086", "Q092", "Q093", "Q096"]
EXTRA = ["Q010", "Q077"]
MISSING = "GitHub Issue #999999999에서 보고한 ART 오류의 원인과 해결 방법은 무엇인가요?"


def plain(value):
    if callable(value):
        return "<관측 콜백>"
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items() if k != "_trace"}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def write(name, value):
    (OUT / name).write_text(json.dumps(plain(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_store():
    helper = runpy.run_path(str(ROOT / "tests/t09_test_data.py"))
    helper["prepare_store"]("verify", REPRO, REF, ROOT, OUT / "store")
    write("store-verification.json", {
        "status": "passed", "reference_sha256": digest(REF),
        "reproduction": json.loads((REPRO / "reproduction.json").read_bytes()),
        "store": str(OUT / "store"),
    })
    print("STORE_VERIFIED", flush=True)


def run():
    from artagent.graph import create_router_graph, create_search_nodes, create_answer_node
    from artagent.graph.research import create_research_node, generate_search_query
    from artagent.graph.state import RequestInput, RuntimeCapabilities
    from artagent.retrieval.embedding import load_encoder
    from artagent.retrieval.store import open_store
    from artagent.retrieval.types import load_spec
    from t15_evaluation import capture_code_identity, fit_bm25_from_snapshot

    path = OUT / "records.jsonl"
    if (OUT / "records.jsonl.gz").exists() or (path.exists() and path.stat().st_size):
        raise ValueError("기존 실행 기록을 덮어쓰지 않습니다.")
    os.environ.update(LLM_PROVIDER="codex", LLM_MODEL="gpt-5.6-sol", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    runtime = importlib.import_module("artagent.answer")
    answering = importlib.import_module("artagent.graph.answer")
    actual_generate = runtime.generate_llm_response
    code_commit, code_hashes = capture_code_identity()
    spec = load_spec(REF)
    store, encoder = open_store(OUT / "store", spec), load_encoder(spec)
    collection = store.client.get_collection(spec.collection_name, embedding_function=None)
    stored = collection.get(include=["documents", "metadatas", "embeddings"])
    rows = sorted(zip(stored["ids"], stored["documents"], stored["metadatas"], stored["embeddings"]))
    reranker = fit_bm25_from_snapshot(rows)
    queries = {q["query_id"]: q for q in json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())["queries"]}
    write("manifest.json", {
        "code_commit": code_commit, "code_hashes": code_hashes,
        "harness_sha256": digest(Path(__file__)), "python": sys.version,
        "model": "gpt-5.6-sol", "provider": "codex-cli",
        "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "inputs": {str(p.relative_to(ROOT)): digest(p) for p in [REF, ROOT / "docs/search_eval_queries.json", ROOT / "docs/T11_execution_records.jsonl"]},
        "settings": {"rewrite_enabled": True, "hyde_enabled": False, "candidate_k": 20, "top_k": 5, "min_score": 0.5, "rerank_weight": 0.25, "reranker": reranker.model_id},
        "query_ids": IDS, "scope_regressions": EXTRA,
        "missing_case": {"text": MISSING, "kind": "고정 자료에 없는 지정 Issue의 정상 빈 검색"},
    })
    for qid in [*IDS, *EXTRA, "MISSING_ISSUE"]:
        record = {"query_id": qid, "query": queries[qid]["query"] if qid in queries else MISSING, "calls": [], "nodes": [], "searches": [], "answers": []}

        def transport(*args, **kwargs):
            started = time.monotonic()
            call = {"prompt_version": kwargs.get("prompt_version"), "arguments": plain(kwargs), "started_at": time.time()}
            record["calls"].append(call)
            try:
                result = actual_generate(*args, **kwargs)
                raw, usage, meta = result
                trace = meta.get("_trace") or {}
                call.update(raw_response=raw, usage=usage, runtime={k: plain(v) for k, v in meta.items() if not k.startswith("_")}, execution={k: trace.get(k) for k in ("cli_version", "execution_policy", "process_returncode", "process_error", "tool_activity", "validation")})
                return result
            except Exception as exc:
                call["error"] = str(exc)
                raise
            finally:
                call["elapsed_seconds"] = time.monotonic() - started

        services = create_search_nodes(store, encoder, generate=generate_search_query, snapshot_ref=spec.reference_sha256, rewrite_enabled=True, hyde_enabled=False, reranker=reranker, candidate_k=20, top_k=5, min_score=0.5, rerank_weight=0.25, observe=lambda e: record["searches"].append(plain(e)))
        services.update(ANSWER=create_answer_node(source_root=ROOT, observe=lambda e: record["answers"].append(plain(e))), RESEARCH=create_research_node(generate=generate_search_query))

        def wrap(name, node):
            def observed(state):
                update = node(state)
                record["nodes"].append({"node": name, "update": plain(update)})
                return update
            return observed

        graph = create_router_graph({name: wrap(name, node) for name, node in services.items()})
        started = time.monotonic()
        with patch.object(runtime, "generate_llm_response", transport), patch.object(answering, "generate_llm_response", transport):
            result = graph.invoke({"request": RequestInput(request_id="cp3-" + qid, text=record["query"]), "capabilities": RuntimeCapabilities(search_ready=True)})
        record.update(result=plain(result), elapsed_seconds=time.monotonic() - started)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(qid, record["result"]["response"]["status"], "research", result.get("research_count"), "calls", len(record["calls"]), round(record["elapsed_seconds"], 2), flush=True)


def records():
    return [json.loads(line) for line in (OUT / "records.jsonl").read_text(encoding="utf-8").splitlines()]


def verify_records():
    from artagent.graph.state import Evidence, RetrievalBundle
    from artagent.graph.answer import validate_and_project_bundle
    entries = records()
    assert [r["query_id"] for r in entries] == [*IDS, *EXTRA, "MISSING_ISSUE"]
    manifest = json.loads((OUT / "manifest.json").read_bytes())
    for rel, sha in manifest["inputs"].items():
        assert digest(ROOT / rel) == sha, rel
    for r in entries:
        trace = r["result"]["trace"]
        assert trace.count("RESEARCH") <= 1, r["query_id"]
        assert r["result"]["response"]["status"] not in ("FAILED", "WAITING_CLARIFICATION"), r["query_id"]
        assert all("error" not in call for call in r["calls"]), r["query_id"]
        for node in r["nodes"]:
            if node["node"].startswith("SEARCH_") and (bundle := node["update"].get("retrieval")):
                bundle = RetrievalBundle(**{**bundle, "hits": [Evidence(**h) for h in bundle["hits"]]})
                validate_and_project_bundle(bundle, ROOT)
        for index, answer in enumerate(r["answers"]):
            assert not answer.get("error"), (r["query_id"], answer.get("error"))
            if json.loads(answer["raw_response"])["status"] == "UNSUPPORTED":
                assert index == len(r["answers"]) - 1
        assert trace.count("ANSWER") <= 2
        assert len(r["searches"]) == trace.count("SEARCH_RAWPEDIA") + trace.count("SEARCH_GITHUB")
    q96 = next(r for r in entries if r["query_id"] == "Q096")
    assert q96["result"]["response"]["status"] == "UNSUPPORTED"
    assert "RESEARCH" not in q96["result"]["trace"]
    assert any("4711197631" in c["url"] for c in q96["result"]["response"]["citations"])
    print("RECORDS_VERIFIED")


def verify_fallback():
    r = next(r for r in records() if r["query_id"] == "MISSING_ISSUE")
    trace = r["result"]["trace"]
    assert trace.count("RESEARCH") == 1 and trace.count("SEARCH_GITHUB") == 2 and trace.count("ANSWER") == 2
    assert r["result"]["research_count"] == 1
    assert r["result"]["response"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert all(not n["update"]["retrieval"]["hits"] for n in r["nodes"] if n["node"] == "SEARCH_GITHUB")
    assert len(r["calls"]) == 4  # 최초 재작성, 최초 답변, 추가 재작성, 추가 답변
    assert all(not c.get("error") for c in r["calls"])
    print("FALLBACK_VERIFIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify-store", "run", "verify-records", "verify-fallback"))
    args = parser.parse_args()
    {"verify-store": verify_store, "run": run, "verify-records": verify_records, "verify-fallback": verify_fallback}[args.action]()
