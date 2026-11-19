#!/usr/bin/env python3
"""실제 GUI·CLI 그래프의 원질문 검색을 같은 서비스 색인에서 비교한다."""

import argparse
from itertools import groupby
import json
import os
from pathlib import Path
from statistics import quantiles
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from artagent.cli import build_repl_graph, load_resources
from artagent.graph import RequestInput, RuntimeCapabilities
from artagent.gui_bridge import create_gui_graph
from scripts import eval_rag_graph as graph
from scripts.eval_ragas import context_scores


def inputs():
    for group, cases in (("regression", graph.evaluation_cases(False)), ("previous_final", graph.evaluation_cases(True))):
        for qid, case in cases.items():
            yield group, qid, {key: value for key, value in case.items() if key != "rewrite"}
    fresh = ROOT / "data/eval/rag-service/questions_v1.json"
    for case in json.loads(fresh.read_bytes()):
        yield "new_questions", case["id"], case


def run(instance, group, qid, case, available):
    started = perf_counter()
    state = instance.invoke({"request": RequestInput(qid, case["question"]),
                             "capabilities": RuntimeCapabilities(search_ready=True)},
                            interrupt_before=["ANSWER"])
    elapsed = (perf_counter() - started) * 1000
    bundle = state.get("retrieval")
    allowed = set(case["allowed"])
    ranks, chunks = {}, {}
    if bundle is not None:
        for hit in bundle.hits:
            ranks.setdefault(hit.doc_id, chunks.setdefault(hit.chunk_id, len(chunks) + 1))
    assert "ANSWER" not in state["trace"]
    return {"group": group, "query_id": qid, "case": case, "search_ok": bundle is not None,
            "route_matched": bool(bundle and bundle.source_filter.lower() == case["source_type"]),
            "retrieval": context_scores(allowed, ranks), "all_gold_retrieved": allowed <= ranks.keys(),
            "first_gold_rank": min((ranks[doc] for doc in ranks.keys() & allowed), default=None),
            "gold_in_index": allowed <= available,
            "search_query": bundle.query if bundle else None, "doc_ranks": ranks,
            "elapsed_ms": elapsed, "trace": state["trace"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=ROOT / "docs/T08_2_t9_handoff_reference.json")
    parser.add_argument("--persist-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(exist_ok=True, parents=True)
    store, encoder, source = load_resources(args.reference, args.persist_dir, ROOT)
    with store.active_search_corpus() as (snapshot, corpus):
        columns = store.collection.get(where={"excluded": False}, include=["metadatas"])
        available = {segment["doc_id"] for meta in columns["metadatas"]
                     for segment in json.loads(meta["source_segments_json"])}
    summary = {"snapshot": snapshot, "active_chunks": len(corpus), "encoder": encoder.spec.model_id,
               "revision": encoder.spec.model_revision, "runs": {}}
    cases = list(inputs())
    for profile in ("legacy", "local"):
        os.environ["ART_RAG_PROFILE"] = profile
        for entry in ("cli", "gui"):
            instance = (build_repl_graph(store, encoder, source_root=source) if entry == "cli"
                        else create_gui_graph(args.reference, args.persist_dir, source))
            rows = [run(instance, group, qid, case, available) for group, qid, case in cases]
            name = f"{entry}-{profile}"
            graph.write_rows(args.output_dir / f"{name}.jsonl.gz", rows)
            summary["runs"][name] = {}
            for group, group_rows in groupby(rows, key=lambda row: row["group"]):
                items = list(group_rows)
                metrics = graph.search_summary(items)
                del metrics["p50_search_ms"]
                times = [row["elapsed_ms"] for row in items]
                if group == "regression":
                    metrics["first_graph_search_ms"], *times = times
                    cuts = quantiles(times, n=20, method="inclusive")
                    metrics.update(warm_graph_p50_ms=cuts[9], warm_graph_p95_ms=cuts[18])
                metrics["gold_in_index"] = sum(row["gold_in_index"] for row in items)
                summary["runs"][name][group] = metrics
            print(name, flush=True)
    for profile in ("legacy", "local"):
        cli_rows, gui_rows = [graph.read_rows(args.output_dir / f"{entry}-{profile}.jsonl.gz") for entry in ("cli", "gui")]
        for cli, gui in zip(cli_rows, gui_rows, strict=True):
            assert all(cli[key] == gui[key] for key in ("query_id", "search_query", "doc_ranks", "search_ok", "trace")), cli["query_id"]
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(graph.canonical(summary), flush=True)


if __name__ == "__main__":
    main()
