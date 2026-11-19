#!/usr/bin/env python3
"""MiniMax가 만든 검색어를 고정해 임베딩·리랭킹을 비교하고 답변을 검증한다."""

import argparse
from dataclasses import asdict, dataclass
from itertools import product
import json
import os
from pathlib import Path
import sys
from time import perf_counter, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from artagent.retrieval.rerank import rank_scored_hits
from scripts import eval_rag_graph as graph
from scripts.eval_ragas import context_scores


MINIMAX = graph.MODELS[0]
EMBEDDINGS = ("minilm", "e5", "bge-small")
POOLS = (10, 20, 40)
WEIGHTS = (0.1, 0.25, 0.5, 0.75)
THRESHOLDS = (None, 0.5)
FINAL_REWRITES = graph.BASE / "graph_live_rewrite_v2"


@dataclass(frozen=True)
class Configuration:
    embedding: str
    ranker: str
    candidate_k: int
    rerank_weight: float
    min_score: float | None
    top_k: int = 5

    @property
    def name(self):
        threshold = "off" if self.min_score is None else str(self.min_score)
        return f"{self.embedding}-{self.ranker}-k{self.candidate_k}-w{self.rerank_weight}-s{threshold}"

    def search_settings(self):
        return {key: getattr(self, key) for key in ("candidate_k", "top_k", "min_score", "rerank_weight")}


BASELINE = Configuration("minilm", "bm25", 20, 0.25, 0.5)
IMPROVEMENT_BASELINE = Configuration("minilm", "bm25", 20, 0.75, 0.5)
IMPROVED_SEARCH = {"rawpedia_ui_terms": True, "recover_rewrite": True}


def load_rewrites(directory, retry_dir=None):
    def checked_rows(path):
        indexed = {}
        for file in sorted(path.glob("*.jsonl.gz")):
            row, = graph.read_rows(file)
            qid = row["query_id"]
            if (qid in indexed or row["model"] != MINIMAX or not row["rewrite_only"] or row["answers"]
                    or row["live_rewrite_format"] != graph.LIVE_REWRITE_FORMAT):
                raise ValueError(f"MiniMax 재작성 기록 불일치: {file}")
            indexed[qid] = row
        return indexed

    cases = graph.evaluation_cases(False)
    rows = checked_rows(directory)
    if rows.keys() != cases.keys() or any(row["case"] != cases[qid] for qid, row in rows.items()):
        raise ValueError("고정 100문항의 실시간 재작성 기록 누락 또는 불일치")
    if retry_dir is not None:
        for qid, retry in checked_rows(retry_dir).items():
            original = rows[qid]
            if (retry["case"] != original["case"] or retry["snapshot_sha256"] != original["snapshot_sha256"]
                    or not graph.rate_limited(original)):
                raise ValueError(f"429 재시도 입력 불일치: {qid}")
            rows[qid] = retry
    return rows


def chosen_hits(hits, scores, config):
    if config.ranker == "dense":
        return hits[:config.top_k]
    ranked = rank_scored_hits(hits, scores, config.rerank_weight)
    return [hit for hit in ranked[:config.top_k]
            if config.min_score is None or scores[hit.chunk_id] >= config.min_score]


def measure(row, hits):
    expected = set(row["case"]["allowed"])
    ranks = {}
    for rank, hit in enumerate(hits, start=1):
        for segment in hit.source_segments:
            ranks.setdefault(segment["doc_id"], rank)
    return {"query_id": row["query_id"], "case": row["case"], "route_matched": row["route_matched"],
            "search_ok": row["search_ok"],
            "selected_chunk_ids": [hit.chunk_id for hit in hits],
            "retrieval": context_scores(expected, ranks), "all_gold_retrieved": expected <= ranks.keys(),
            "first_gold_rank": min((ranks[doc] for doc in expected & ranks.keys()), default=None)}


def score_configurations(store, encoder, snapshot, rewrites, configs, reranker):
    by_name = {config.name: [] for config in configs}
    pool_sizes = sorted({config.candidate_k for config in configs})
    for qid, row in rewrites.items():
        pools = {k: [] for k in pool_sizes}
        scores = {}
        if row["search_ok"]:
            search = row["searches"][0]
            query = search["search_input"]["search_query"]
            for size in pool_sizes:
                candidates = store.search_candidates(query, encoder, candidate_k=size,
                                                     source_type=search["source_type"],
                                                     source_group_ids=search["source_group_ids"])
                pools[size] = candidates
                for hit in candidates:
                    if hit.chunk_id not in scores:
                        scores[hit.chunk_id] = reranker.score_hit(query, hit)[1]
        for config in configs:
            selected = chosen_hits(pools[config.candidate_k], scores, config)
            by_name[config.name].append(measure(row, selected))
            if config == BASELINE and row["search_ok"]:
                observed = row["searches"][0]["selected_chunk_ids"]
                if [hit.chunk_id for hit in selected] != observed:
                    raise ValueError(f"실제 MiniLM + BM25 기준 검색의 순서 불일치: {qid}")
        if configs[0].ranker == "cross" and qid.endswith("0"):
            print(f"다국어 교차 인코더 {qid}", flush=True)

    experiments = []
    for config in configs:
        rows = by_name[config.name]
        # 격자에서 후보와 점수를 공유하므로 실제 그래프 검증에서만 지연을 측정한다.
        summary = graph.search_summary(rows)
        del summary["p50_search_ms"]
        experiments.append({"name": config.name, "settings": asdict(config), "snapshot_sha256": snapshot,
                            "metrics": summary, "rows": rows})
    return experiments


def choose(experiments):
    baseline = next(e for e in experiments if e["name"] == BASELINE.name)
    expected = baseline["metrics"]

    def qualified(entry):
        metrics = entry["metrics"]
        return (metrics["negative_evidence"] >= expected["negative_evidence"]
                and all(metrics["recall_by_source"][source] >= value
                        for source, value in expected["recall_by_source"].items()))

    def order(entry):
        metrics, settings = entry["metrics"], entry["settings"]
        return (-metrics["context_recall"], -metrics["context_precision"], -metrics["mrr"],
                settings["candidate_k"], settings["ranker"] == "cross", entry["name"] != BASELINE.name, entry["name"])

    return min((e for e in experiments if qualified(e)), key=order)


def configured_ranker(protocol, bm25, ranker):
    if ranker == "dense":
        return None
    return bm25 if ranker == "bm25" else graph.load_reranker(protocol, "R1")


def evaluate_grid(protocol, store_args, bm25, rewrites):
    results = []
    for embedding in EMBEDDINGS:
        configs = [Configuration(embedding, "dense", 20, 1.0, None)]
        configs.extend(Configuration(embedding, "bm25", k, w, t) for k, w, t in product(POOLS, WEIGHTS, THRESHOLDS))
        with graph.candidate_index(embedding, *store_args) as (store, encoder, snapshot):
            results.extend(score_configurations(store, encoder, snapshot, rewrites, configs, bm25))
        print(f"{embedding} {len(configs)}개 순위 조합 완료", flush=True)
    leading = choose(results)
    embedding = leading["settings"]["embedding"]
    print(graph.canonical({"dense_bm25_leader": leading["name"], "metrics": leading["metrics"]}), flush=True)
    configs = [Configuration(embedding, "cross", 10, w, t) for w, t in product(WEIGHTS, THRESHOLDS)]
    with graph.candidate_index(embedding, *store_args) as (store, encoder, snapshot):
        results.extend(score_configurations(store, encoder, snapshot, rewrites, configs,
                                           configured_ranker(protocol, bm25, "cross")))
    return results


def verify(entry, store, encoder, snapshot, reranker, rewrites, *, improved=False):
    config = Configuration(**entry["settings"])
    if snapshot != entry["snapshot_sha256"]:
        raise ValueError("격자와 실제 그래프의 색인 불일치")
    expected = {row["query_id"]: row for row in entry["rows"]}
    search_settings = config.search_settings()
    if improved:
        search_settings.update(IMPROVED_SEARCH)
    results = []
    for qid, row in rewrites.items():
        if not improved and not row["search_ok"]:
            results.append({**measure(row, []), "rewrite_error": row["searches"][0]["error"]})
            continue
        if improved:
            call, = row["rewrite_calls"]
            query = call["output"]
        else:
            query = row["searches"][0]["search_input"]["search_query"]
        case = {**row["case"], "rewrite": query}
        result = graph.evaluate(store, encoder, snapshot, reranker, qid, case, live=False,
                                search_config=search_settings)
        if not result["route_matched"]:
            raise ValueError(f"실제 그래프의 출처 불일치: {config.name}/{qid}")
        if not improved and (not result["search_ok"]
                             or result["searches"][0]["selected_chunk_ids"] != expected[qid]["selected_chunk_ids"]
                             or result["retrieval"] != expected[qid]["retrieval"]):
            raise ValueError(f"격자와 실제 그래프의 선택·근거 불일치: {config.name}/{qid}")
        results.append(result)
    print(graph.canonical({label(config, improved): graph.search_summary(results)}), flush=True)
    return results


def final_cases():
    cases = graph.evaluation_cases(True)
    for qid, case in cases.items():
        path = FINAL_REWRITES / f"minilm-bm25-{qid}-{MINIMAX.replace('/', '--')}.jsonl.gz"
        row, = graph.read_rows(path)
        if (row["case"] != case or row["model"] != MINIMAX
                or row["live_rewrite_format"] != graph.LIVE_REWRITE_FORMAT or not row["search_ok"]):
            raise ValueError(f"고정 MiniMax 검증용 재작성 불일치: {qid}")
        sequence = [call["output"] for call in row["rewrite_calls"]]
        cases[qid] = {**case, "rewrite": sequence[0], "rewrite_sequence": sequence}
    return cases


def label(config, improved):
    return f"{config.name}-improved" if improved else config.name


def run_final(entry, store, encoder, snapshot, reranker, directory, selected, *, improved=False):
    config = Configuration(**entry["settings"])
    if snapshot != entry["snapshot_sha256"]:
        raise ValueError("격자와 답변 그래프의 색인 불일치")
    cases = final_cases()
    name = label(config, improved)
    search_settings = config.search_settings()
    if improved:
        search_settings.update(IMPROVED_SEARCH)
    if selected and not set(selected) <= cases.keys():
        raise ValueError("검증 문항 범위 초과")
    next_request = 0.0
    for qid, case in cases.items():
        if selected and qid not in selected:
            continue
        path = directory / f"{name}-{qid}.jsonl.gz"
        if path.exists():
            saved, = graph.read_rows(path)
            if saved["case"] != case or saved["snapshot_sha256"] != snapshot or saved["candidate"] != name:
                raise ValueError(f"재개 기록 불일치: {path}")
            continue
        if improved:
            sleep(max(0.0, next_request - perf_counter()))
            next_request = perf_counter() + 5
        row = graph.evaluate(store, encoder, snapshot, reranker, qid, case, live=True,
                             search_config=search_settings, assemble_citations=improved)
        row.update(candidate=name, model=MINIMAX, search_config={**asdict(config), **search_settings})
        if improved:
            row["assemble_citations"] = True
        graph.write_rows(path, [row])
        print(name, qid, row["trace"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("grid", "verify", "final", "summary"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--rewrites", type=Path)
    parser.add_argument("--rewrite-retries", type=Path)
    parser.add_argument("--grid", type=Path)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--improved", action="store_true", help="상위 설정에서 검색어·인용 개선을 켠다")
    parser.add_argument("--query", action="append")
    args = parser.parse_args()
    if args.improved and (args.baseline or args.phase not in ("verify", "final")):
        parser.error("--improved는 상위 검색 설정의 verify 또는 final에 사용합니다.")
    if args.phase in ("grid", "verify") and not args.rewrites:
        parser.error("--rewrites 필요")
    needs_grid = args.phase in ("summary", "verify") or (args.phase == "final" and not args.baseline)
    if needs_grid and not args.grid:
        parser.error("--grid 필요")
    if args.phase != "summary" and not args.output_dir:
        parser.error("--output-dir 필요")

    experiments = graph.read_rows(args.grid) if args.grid else None
    if args.phase == "summary":
        for entry in sorted(experiments, key=lambda x: x["name"]):
            print(graph.canonical({key: entry[key] for key in ("name", "settings", "metrics")}))
        print(graph.canonical({"winner": choose(experiments)["name"]}))
        return

    if args.phase == "final":
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            parser.error("NVIDIA_API_KEY 필요")
        os.environ.update(LLM_PROVIDER="openai-compatible", LLM_BASE_URL=graph.NVIDIA_BASE_URL,
                          LLM_API_KEY=key, LLM_MODEL=MINIMAX)

    directory = args.output_dir
    directory.mkdir(parents=True, exist_ok=True)
    rewrites = load_rewrites(args.rewrites, args.rewrite_retries) if args.rewrites else None
    protocol = json.loads(graph.PROTOCOL.read_bytes())
    candidates = graph.new_candidates(graph.FINAL_INPUT.parent / "curation.json")
    with graph.expanded_store(protocol, candidates) as (base_store, base_encoder, bm25, base_snapshot):
        store_args = (base_store, base_encoder, base_snapshot)
        if args.phase == "grid":
            path = directory / "grid.jsonl.gz"
            if path.exists():
                raise FileExistsError(path)
            input_sha = graph.digest(rewrites)
            results = evaluate_grid(protocol, store_args, bm25, rewrites)
            graph.write_rows(path, [{**entry, "rewrites_sha256": input_sha} for entry in results])
            print(graph.canonical({"winner": choose(results)["name"]}), flush=True)
            return

        if args.baseline and experiments is None:
            entry = {"settings": asdict(BASELINE), "snapshot_sha256": base_snapshot}
        elif args.improved:
            entry = next(e for e in experiments if e["name"] == IMPROVEMENT_BASELINE.name)
        else:
            entry = next(e for e in experiments if e["name"] == BASELINE.name) if args.baseline else choose(experiments)
        config = Configuration(**entry["settings"])
        with graph.candidate_index(config.embedding, *store_args) as (store, encoder, snapshot):
            ranker = configured_ranker(protocol, bm25, config.ranker)
            if args.phase == "verify":
                if graph.digest(rewrites) != entry["rewrites_sha256"]:
                    raise ValueError("검증용 재작성 지문 불일치")
                rows = verify(entry, store, encoder, snapshot, ranker, rewrites, improved=args.improved)
                graph.write_rows(directory / f"{label(config, args.improved)}.jsonl.gz", rows)
            else:
                run_final(entry, store, encoder, snapshot, ranker, directory, args.query, improved=args.improved)


if __name__ == "__main__":
    main()
