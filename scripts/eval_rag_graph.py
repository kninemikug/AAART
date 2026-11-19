#!/usr/bin/env python3
"""실제 RAG 그래프에서 고정 검색 조합과 NVIDIA 답변을 검증한다."""

import argparse
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, replace
import gzip
import json
import os
from pathlib import Path
from statistics import mean, median
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from artagent.answer import generate_llm_response, generation_time_budget
from artagent.graph.answer import create_answer_node
from artagent.graph.graph import create_router_graph
from artagent.graph.research import create_research_node
from artagent.graph.search import create_search_nodes
from artagent.graph.state import RequestInput, RuntimeCapabilities
from artagent.retrieval.embedding import embed_chunks, load_encoder
from artagent.retrieval.provenance import deserialize_chunk
from artagent.retrieval.store import open_store
from scripts.compare_rag_models import (NVIDIA_BASE_URL, canonical, digest, final_cases,
                                        load_cases, nvidia_tokens)
from scripts.eval_ragas import context_scores
from scripts.eval_t15_rerank import load_reranker
from scripts.prepare_rag_selection import BASE, PROTOCOL, expanded_snapshot, expanded_store, new_candidates
from scripts.t15_evaluation import read_rows

EMBEDDINGS = ("minilm", "e5")
RANKERS = ("dense", "bm25", "cross")
MODELS = ("minimaxai/minimax-m3.1-flash", "nvidia/nemotron-3.5-lightning-30b-a3b")
BASELINE = "minilm-bm25"
FINAL_INPUT = BASE / "final_search_v1/search_inputs.jsonl.gz"


@contextmanager
def candidate_index(embedding, store, encoder, snapshot_sha):
    if embedding == "minilm":
        yield store, encoder, snapshot_sha
        return

    spec = replace(store.spec, model_id="intfloat/multilingual-e5-small",
                   model_revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
                   query_prefix="query: ", doc_prefix="passage: ")
    corpus = [row[:3] for row in expanded_snapshot(store)]
    encoder = load_encoder(spec)
    vectors = embed_chunks([deserialize_chunk(*row) for row in corpus], encoder)
    with TemporaryDirectory(prefix="rag-graph-e5-") as temp:
        alternative = open_store(Path(temp), spec)
        ids, texts, metadata = zip(*corpus, strict=True)
        alternative.collection.add(ids=list(ids), documents=list(texts), metadatas=list(metadata),
                                   embeddings=vectors.tolist())
        snapshot = expanded_snapshot(alternative)
        if [row[:3] for row in snapshot] != corpus:
            raise ValueError("임베딩 후보 간 코퍼스 불일치")
        yield alternative, encoder, digest(snapshot)


def evaluation_cases(live):
    if not live:
        return {qid: {"question": row["question"], "source_type": row["source_type"],
                      "allowed": row["allowed_source_doc_ids"], "negative": row["is_negative"],
                      "rewrite": row["search_run"]["query"]}
                for qid, row in load_cases(full=True).items()}

    final_cases(FINAL_INPUT)
    return {row["id"]: {"question": row["question"], "source_type": row["source_type"],
                        "allowed": sorted({e["doc_id"] for e in row["evidence"]}),
                        "expected_status": row["expected_status"], "rewrite": row["rewrite"]["output"]}
            for row in read_rows(FINAL_INPUT)}


def evaluate(store, encoder, snapshot_sha, reranker, qid, case, *, live, live_rewrite=False):
    searches, answers, rewrite_prompts, rewrite_calls = [], [], [], []

    def rewrite(prompt):
        rewrite_prompts.append(digest(prompt))
        if not live_rewrite:
            return case["rewrite"]

        started = perf_counter()
        instruction = "검색 입력 변환만 수행하십시오. 출력은 answer에 넣고 citation_ids는 빈 목록으로 두십시오."
        raw, usage, metadata = generate_llm_response(instruction, prompt, {}, prompt)
        result = json.loads(raw)
        rewrite_calls.append({"output": result["answer"], "usage": usage,
                              "model": metadata["model_id"], "endpoint": metadata["endpoint"],
                              "elapsed_ms": (perf_counter() - started) * 1000})
        if result["citation_ids"]:
            raise ValueError("검색 재작성에 인용을 반환했습니다.")
        return result["answer"]

    search_nodes = create_search_nodes(
        store, encoder, generate=rewrite, snapshot_ref=snapshot_sha, rewrite_enabled=True,
        reranker=reranker, candidate_k=20, top_k=5,
        min_score=0.5 if reranker is not None else None,
        rerank_weight=0.25 if reranker is not None else 1.0, observe=searches.append,
    )
    graph = create_router_graph({**search_nodes,
                                 "ANSWER": create_answer_node(source_root=ROOT, observe=answers.append),
                                 "RESEARCH": create_research_node(generate=rewrite)})
    request = RequestInput(request_id=qid, text=case["question"])
    started = perf_counter()
    with generation_time_budget(120):
        state = graph.invoke({"request": request, "capabilities": RuntimeCapabilities(search_ready=True)},
                             interrupt_before=[] if live else ["ANSWER"])
    elapsed_ms = (perf_counter() - started) * 1000
    reports = []
    for obs in searches:
        doc_ranks = {}
        for rank, hit in enumerate(obs["hits"], start=1):
            for segment in hit["source_segments"]:
                doc_ranks.setdefault(segment["doc_id"], rank)
        reports.append({"node": obs["node"], "source_type": obs["source_type"],
                        "source_group_ids": obs["source_group_ids"], "search_input": obs["search_input"],
                        "selected_chunk_ids": [hit["chunk_id"] for hit in obs["hits"]],
                        "candidate_chunk_ids": [hit["chunk_id"] for hit in obs.get("candidates", [])],
                        "doc_ranks": doc_ranks, "elapsed_ms": obs["elapsed_ms"], "error": obs["error"]})
    first = reports[0] if reports else {}
    expected = set(case["allowed"])
    ranks = first.get("doc_ranks", {})
    best_rank = min((rank for doc, rank in ranks.items() if doc in expected), default=None)
    terminal = state.get("response")
    steps = list(state.get("step_results", {}).values())
    return {"query_id": qid, "case": case, "snapshot_sha256": snapshot_sha,
            "trace": state.get("trace", []), "route_matched": first.get("source_type") == case["source_type"],
            "rewrites": rewrite_prompts, "rewrite_calls": rewrite_calls,
            "searches": reports, "retrieval": context_scores(expected, ranks),
            "first_gold_rank": best_rank, "all_gold_retrieved": expected <= ranks.keys(),
            "search_ok": bool(first) and first["error"] is None,
            "response": asdict(terminal) if terminal is not None else None,
            "steps": [asdict(step) for step in steps], "answers": answers,
            "state_error": asdict(state["error"]) if state.get("error") else None,
            "elapsed_ms": elapsed_ms}


def write_rows(path, rows):
    data = "".join(canonical(row) + "\n" for row in rows).encode()
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(gzip.compress(data, mtime=0))
            stream.close()
            os.link(temporary, path)
        finally:
            temporary.unlink()


def search_summary(rows):
    def avg(key, subset):
        values = [r["retrieval"][key]["value"] for r in subset]
        return mean(v if v is not None else 0 for v in values) if values else None

    times = [r["searches"][0]["elapsed_ms"] for r in rows if r["search_ok"]]
    return {"questions": len(rows), "correct_route": sum(r["route_matched"] for r in rows),
            "search_ok": sum(r["search_ok"] for r in rows),
            "context_precision": avg("context_precision", rows), "context_recall": avg("context_recall", rows),
            "recall_by_source": {source: avg("context_recall", [r for r in rows if r["case"]["source_type"] == source])
                                 for source in ("rawpedia", "github")},
            "negative_evidence": sum(r["all_gold_retrieved"] for r in rows if r["case"].get("negative")),
            "mrr": mean(1 / r["first_gold_rank"] if r["first_gold_rank"] else 0 for r in rows),
            "p50_search_ms": median(times) if times else None}


def shortlist(results):
    baseline = results[BASELINE]
    qualified = []
    for name, row in results.items():
        if (row["questions"] != 100 or row["correct_route"] != 100
                or row["search_ok"] < baseline["search_ok"]
                or row["negative_evidence"] < baseline["negative_evidence"]
                or any(row["recall_by_source"][source] < recall
                       for source, recall in baseline["recall_by_source"].items())):
            continue
        if name != BASELINE:
            qualified.append(name)

    def order(name):
        row = results[name]
        return -row["context_recall"], -row["context_precision"], -row["mrr"], row["p50_search_ms"]

    return [BASELINE, *sorted(qualified, key=order)[:2]]


def answer_summary(rows):
    details = {}
    token_counts = []
    times = []
    for row in rows:
        model = row["model"]
        for position, observation in enumerate(row["answers"], start=1):
            request = observation.get("request") or {}
            endpoint = (observation.get("runtime_meta") or {}).get("endpoint")
            if request and (request["model"] != model or endpoint != f"{NVIDIA_BASE_URL}/chat/completions"
                            or digest(request["payload"]) != request["sha256"]):
                raise ValueError(f"실제 생성 요청 불일치: {row['query_id']}/{position}")
            tokens = nvidia_tokens(observation)
            if tokens is not None:
                token_counts.append(tokens)

        answer = (row["steps"][0].get("answer") or {}) if len(row["steps"]) == 1 else {}
        status = answer.get("status")
        expected = row["case"]["expected_status"]
        if status:
            times.append(row["elapsed_ms"])
        details[row["query_id"]] = {"status": status, "expected_status": expected,
                                    "matched_status": status == expected,
                                    "response_status": (row["response"] or {}).get("status"),
                                    "errors": [s["error"]["code"] for s in row["steps"] if s["error"]],
                                    "answer_requests": sum(a.get("call_count", 0) for a in row["answers"]),
                                    "rewrote_live": len(row.get("rewrite_calls", []))}
    return {**search_summary(rows), "valid_answers": len(times),
            "matched_status": sum(d["matched_status"] for d in details.values()),
            "all_gold_retrieved": sum(r["all_gold_retrieved"] for r in rows),
            "answer_requests": sum(d["answer_requests"] for d in details.values()),
            "requests_with_usage": len(token_counts),
            "prompt_tokens": sum(t[0] for t in token_counts),
            "completion_tokens": sum(t[1] for t in token_counts),
            "p50_graph_ms": median(times) if times else None, "cases": details}


def rate_limited(row):
    return any("HTTP Error 429" in step["error"]["message"]
               for step in row["steps"] if step["error"] is not None)


def summarize(directory, retry_dir=None):
    groups = defaultdict(list)
    for path in sorted(directory.glob("*.jsonl.gz")):
        for row in read_rows(path):
            groups[row["candidate"], row["model"]].append(row)
    if not groups:
        raise ValueError(f"평가 기록 없음: {directory}")

    retries = {}
    if retry_dir is not None:
        for path in sorted(retry_dir.glob("*.jsonl.gz")):
            row, = read_rows(path)
            key = (row["candidate"], row["model"], row["query_id"])
            if key in retries:
                raise ValueError(f"재시도 중복: {key}")
            retries[key] = row

    results = {}
    for (candidate, model), rows in groups.items():
        qids = {row["query_id"] for row in rows}
        snapshots = {row["snapshot_sha256"] for row in rows}
        if len(qids) != len(rows) or len(snapshots) != 1:
            raise ValueError(f"후보별 중복 문항 또는 색인 불일치: {candidate}/{model}")
        label = candidate if model is None else f"{candidate}/{model}"
        if model is None:
            results[label] = search_summary(rows)
            continue
        final_rows = []
        for original in rows:
            retry = retries.pop((candidate, model, original["query_id"]), None)
            if retry is not None and (not rate_limited(original)
                    or retry["case"] != original["case"]
                    or retry["snapshot_sha256"] != original["snapshot_sha256"]
                    or retry.get("live_rewrite", False) != original.get("live_rewrite", False)):
                raise ValueError(f"429 재시도 입력 불일치: {candidate}/{original['query_id']}")
            final_rows.append(retry or original)
        results[label] = {**answer_summary(final_rows), "initial_429": sum(rate_limited(r) for r in rows),
                          "final_429": sum(rate_limited(r) for r in final_rows)}
    if retries:
        raise ValueError(f"원래 시도가 없는 재시도: {sorted(retries)}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--embedding", choices=EMBEDDINGS, default="minilm")
    parser.add_argument("--ranker", choices=RANKERS, action="append")
    parser.add_argument("--answer-model", choices=MODELS)
    parser.add_argument("--live-rewrite", action="store_true", help="NVIDIA 답변과 함께 재작성도 실호출")
    parser.add_argument("--summary", action="store_true", help="보존 기록만 오프라인 집계")
    parser.add_argument("--retry-dir", type=Path, help="오프라인 집계에 연결할 429 재시도 기록")
    parser.add_argument("--query", action="append")
    args = parser.parse_args()
    if args.summary:
        result = summarize(args.output_dir, args.retry_dir)
        if set(result) == {f"{encoder}-{ranker}" for encoder in EMBEDDINGS for ranker in RANKERS}:
            result["shortlist"] = shortlist(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return
    live = bool(args.answer_model)
    if args.live_rewrite and not live:
        parser.error("--live-rewrite에는 --answer-model이 필요합니다.")
    cases = evaluation_cases(live)
    if args.query and not set(args.query) <= cases.keys():
        parser.error("고정 범위 밖 문항")
    if args.query:
        cases = {qid: case for qid, case in cases.items() if qid in args.query}
    if live:
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            parser.error("NVIDIA_API_KEY 필요")
        os.environ.update(LLM_PROVIDER="openai-compatible", LLM_BASE_URL=NVIDIA_BASE_URL,
                          LLM_API_KEY=key, LLM_MODEL=args.answer_model)

    directory = args.output_dir
    directory.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(PROTOCOL.read_bytes())
    # 정제 원본은 기존 독립 인덱스와 같은 불변 파일을 검증한다.
    candidates = new_candidates(FINAL_INPUT.parent / "curation.json")
    with expanded_store(protocol, candidates) as (base_store, base_encoder, bm25, base_sha):
        with candidate_index(args.embedding, base_store, base_encoder, base_sha) as (store, encoder, snapshot):
            for name in args.ranker or RANKERS:
                label = f"{args.embedding}-{name}"
                path = directory / f"{label}.jsonl.gz"
                if not live and path.exists():
                    raise FileExistsError(path)
                reranker = load_reranker(protocol, "R2") if name == "cross" else bm25 if name == "bm25" else None
                rows = []
                for qid, case in cases.items():
                    if live:
                        model = args.answer_model.replace("/", "--")
                        path = directory / f"{label}-{qid}-{model}.jsonl.gz"
                        if path.exists():
                            saved, = read_rows(path)
                            if (saved["case"] != case or saved["snapshot_sha256"] != snapshot
                                    or saved.get("live_rewrite", False) != args.live_rewrite):
                                raise ValueError(f"재개 입력 불일치: {path}")
                            continue
                    row = evaluate(store, encoder, snapshot, reranker, qid, case, live=live,
                                   live_rewrite=args.live_rewrite)
                    row.update(candidate=label, model=args.answer_model, live_rewrite=args.live_rewrite,
                               encoder_spec=asdict(encoder.spec))
                    if live:
                        write_rows(path, [row])
                    else:
                        rows.append(row)
                    if live or qid.endswith("0") or len(cases) < 10:
                        print(label, qid, row["trace"], flush=True)
                if not live:
                    write_rows(path, rows)
                    print(canonical({label: search_summary(rows)}), flush=True)


if __name__ == "__main__":
    main()
