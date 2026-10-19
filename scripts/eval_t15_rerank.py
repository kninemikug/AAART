#!/usr/bin/env python3
"""Task 15: 고정 스냅샷의 실제 검색·채점·그래프 평가와 독립 감사.

prepare/run은 새 폴더에만 기록한다. check는 저장된 증거만 읽으며 모델을
로드하거나 검색·생성을 실행하지 않는다. 품질 미달이면 B0를 유지한다.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.t15_evaluation import (
    CODE_PATHS, MODEL_IDS, SLICE1_QIDS, FOCUS_12_QIDS, T17_CRITICAL_31_QIDS,
    EXPECTED_FILES, MissingEvidence, RecordVerifier, audit_run, calculate_first_gold_rank,
    compare_quality, compute_metrics_for_records, digest, doc_ids_from_hit,
    evaluate_gates, extract_counter_evidence_ids, fit_bm25_from_snapshot, read_rows,
    regressions, result_digest, score_result_digest, select_condition, sha256_file, should_expand_candidates,
    summarize, verify_manifest, verify_protocol, verify_routes,
)
from artagent.retrieval.rerank import CrossEncoderReranker, rank_scored_hits
from artagent.retrieval.embedding import embed_chunks, embed_query, load_encoder
from artagent.retrieval.provenance import deserialize_chunk
from artagent.retrieval.store import open_store
from artagent.retrieval.types import load_spec
from artagent.graph.search import create_search_nodes, resolve_github_targets, search_hits_to_evidences, _extract_query_and_constraints
from artagent.graph import create_router_graph, RequestInput, RuntimeCapabilities, AnswerResult
from artagent.graph.state import RetrievalBundle, Evidence

T14 = "data/eval/t14-conn/conn_20261015_pr"
CACHE = "data/eval/t14-live-20261014-final/generation_cache.json"
GENERATION_SOURCE = "data/eval/t14-conn/conn_20261015_product_scope_v3_live"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


@contextmanager
def row_writer(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        def emit(row):
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
        yield emit


def seal(out: Path, protocol_path: Path, phase: str, **extra) -> None:
    artifacts = {p.name: sha256_file(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != "manifest.json"}
    write_json(out / "manifest.json", {"schema_version": 3, "phase": phase,
               "protocol_path": str(protocol_path.relative_to(ROOT)), "protocol_sha256": sha256_file(protocol_path),
               "artifacts": artifacts, **extra})


def model_identity(model_id: str) -> dict:
    from huggingface_hub.constants import HF_HUB_CACHE
    cache = Path(HF_HUB_CACHE) / ("models--" + model_id.replace("/", "--"))
    revision = (cache / "refs/main").read_text().strip()
    snapshot = cache / "snapshots" / revision
    files = {str(p.relative_to(snapshot)): sha256_file(p) for p in sorted(snapshot.rglob("*"))
             if p.is_file() and p.suffix in (".json", ".txt", ".model", ".safetensors", ".bin")}
    if not files or len(revision) != 40:
        raise ValueError(f"고정할 로컬 모델이 없습니다: {model_id}")
    return {"model_id": model_id, "revision": revision, "cache_path": str(snapshot), "files": files,
            "max_length": 512, "overlap_tokens": 64, "max_header_tokens": 32, "aggregation": "max_window_v2_offsets"}


def cmd_prepare(args) -> int:
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = {"queries": Path(args.queries).resolve(), "reference": Path(args.reference).resolve(),
             "ab_records": Path(args.t14_run).resolve() / "ab_records.jsonl",
             "snapshot": Path(args.t14_run).resolve() / "store_snapshot.json",
             "generation_events": Path(args.t14_run).resolve() / "generation_events.json",
             "generation_source_events": ROOT / GENERATION_SOURCE / "generation_events.json",
             "generation_source_protocol": ROOT / GENERATION_SOURCE / "protocol.json",
             "generation_cache": ROOT / CACHE, "slice1": ROOT / "docs/T11_execution_records.jsonl"}
    archive_run = getattr(args, 'score_source_run', None)
    if archive_run:
        paths['score_archive_manifest'] = Path(archive_run).resolve() / 'manifest.json'
        paths['score_archive_audit'] = ROOT / 'data/eval/t15-rerank/audit_v4/frozen_v3_integrity.json'
    inputs = {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for name, path in paths.items()}
    snapshot = json.loads(paths["snapshot"].read_bytes())
    if digest(snapshot) != "09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6":
        raise ValueError("T14 스냅샷 변경")
    models = {name: model_identity(model_id) for name, model_id in MODEL_IDS.items()}
    bm25 = fit_bm25_from_snapshot(snapshot)
    models["R3"] = {"model_id": "lexical_bm25", "corpus_fingerprint": bm25.corpus_fingerprint,
                    "n_docs": bm25.n_docs, "k1": bm25.k1, "b": bm25.b, "tokenizer": "unicode_word_v1"}
    protocol = {"schema_version": 3, "created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
                "snapshot_fingerprint": digest(snapshot), "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "code_sha256": {name: sha256_file(ROOT / name) for name in CODE_PATHS}, "models": models,
                "grid": {"candidate_k": [20, 40], "top_k": [3, 5, 10, 20], "min_score": [None, 0., .2, .5, .7],
                         "rerank_weight": [.05, .1, .2, .25, .5, 1.]},
                "runtime": {"python": sys.version, "executable": sys.executable, "device": "cpu", "threads": 4, "seed": 0},
                "selection": "both_paths_no_regression_v1", "repeat_count": 3,
                "store_restore": "rebuild_original_embeddings_v1",
                "answer": {"provider": "codex-cli", "model": "gpt-5.6-sol", "prompt_version": "t17-answer-v1"}}
    if archive_run:
        protocol['score_archive'] = {'run_dir': str(Path(archive_run).resolve().relative_to(ROOT)),
                                     'scope': '격자 채점만 기존 실제 추론 증거 재사용. 회귀는 새 검색·채점.'}
        from scripts.t15_score_archive import ScoreArchive
        ScoreArchive(protocol, Path(archive_run).resolve(), paths['score_archive_audit'])
    write_json(out / "protocol.json", protocol)
    verify_protocol(out / "protocol.json")
    RecordVerifier(protocol)
    print(f"입력·원문·모델 revision 고정: {out / 'protocol.json'}", flush=True)
    return 0


@contextmanager
def runtime_store(protocol: dict):
    import torch
    torch.set_num_threads(protocol["runtime"]["threads"])
    torch.manual_seed(protocol["runtime"]["seed"])
    spec = load_spec(ROOT / protocol["inputs"]["reference"]["path"])
    session = load_encoder(spec)
    rows = json.loads((ROOT / protocol["inputs"]["snapshot"]["path"]).read_bytes())
    # Chroma의 저장 벡터는 이미 정규화되어 있다. 다시 넣으면 재정규화되어
    # 마지막 비트가 변하므로 T9의 원래 임베딩 경로로 입력 벡터를 재생성한다.
    vectors = embed_chunks([deserialize_chunk(cid, text, meta) for cid, text, meta, _ in rows], session)
    with tempfile.TemporaryDirectory(prefix="t15-store-") as temp:
        store = open_store(Path(temp), spec)
        store.collection.add(ids=[r[0] for r in rows], documents=[r[1] for r in rows],
                             metadatas=[r[2] for r in rows], embeddings=vectors.tolist())
        store._validate_collection_contract()
        actual = store.collection.get(include=["documents", "metadatas", "embeddings"])
        restored = sorted([(cid, actual["documents"][i], actual["metadatas"][i], actual["embeddings"][i].tolist())
                           for i, cid in enumerate(actual["ids"])], key=lambda row: row[0])
        if digest(restored) != protocol["snapshot_fingerprint"]:
            raise ValueError("T9 원래 임베딩으로 복원한 스냅샷 불일치")
        yield store, session


def load_reranker(protocol: dict, name: str):
    if name == "R3":
        return fit_bm25_from_snapshot(json.loads((ROOT / protocol["inputs"]["snapshot"]["path"]).read_bytes()))
    identity = protocol["models"][name]
    return CrossEncoderReranker(identity["model_id"], revision=identity["revision"], device="cpu",
                               max_length=identity["max_length"], overlap_tokens=identity["overlap_tokens"],
                               max_header_tokens=identity["max_header_tokens"], local_files_only=True)


def search_record(store, session, verifier: RecordVerifier, condition: str, qid: str, pool: int, repetition: int = 1):
    parent = verifier.t14[condition, qid]
    observation = parent["search_observations"][0]
    query = observation["search_input"]["search_query"]
    source = "github" if observation["node"] == "SEARCH_GITHUB" else "rawpedia"
    groups = resolve_github_targets(query, verifier.questions[qid]["query"]) if source == "github" else None
    started = time.perf_counter()
    hits = store.search_candidates(query, session, candidate_k=pool, source_type=source, source_group_ids=groups)
    vector = embed_query(query, session).tolist()
    row = {"condition": condition, "query_id": qid, "candidate_k": pool, "repeat_index": repetition,
           "search_query": query, "source_type": source, "source_group_ids": groups, "query_vector": vector,
           "candidates": [{k: getattr(h, k) for k in ("chunk_id", "rank", "distance", "distance_text")} for h in hits],
           "elapsed_ms": (time.perf_counter() - started) * 1000}
    return row, hits


def score_record(model, name, search, hits, cache=None):
    started = time.perf_counter()
    scores = []
    for hit in hits:
        key = (name, search["condition"], search["query_id"], hit.chunk_id)
        if cache is not None and key in cache:
            value = cache[key]
        else:
            raw, selection, count = model.score_hit(search["search_query"], hit)
            value = {"chunk_id": hit.chunk_id, "raw_score": raw, "selection_score": selection,
                     "window_count": count, "windows": copy.deepcopy(getattr(model, "last_windows", []))}
            if cache is not None:
                cache[key] = value
        scores.append(value)
    return {**{k: search[k] for k in ("condition", "query_id", "candidate_k", "repeat_index")},
            "model": name, "scores": scores, "elapsed_ms": (time.perf_counter() - started) * 1000,
            "measurement": "incremental_cache" if cache is not None else "fresh_inference"}


def trial(search, score, hits, config, protocol, question):
    values = {value["chunk_id"]: value for value in score["scores"]}
    ordered = rank_scored_hits(hits, {cid: value['selection_score'] for cid, value in values.items()},
                               config.get('rerank_weight', 1.))
    chosen = [h for h in ordered[:config["top_k"]] if config["min_score"] is None
              or values[h.chunk_id]["selection_score"] >= config["min_score"]]
    bundle = RetrievalBundle(search["search_query"], search["source_type"].upper(), search_hits_to_evidences(chosen), protocol["snapshot_fingerprint"])
    return {"condition_id": config["condition_id"], "condition": search["condition"], "query_id": search["query_id"],
            "repeat_index": search["repeat_index"], "selected_chunk_ids": [h.chunk_id for h in chosen],
            "metrics": summarize(chosen, question), "scores_digest": digest(score),
            "score_result_digest": score_result_digest(score), "bundle_digest": digest(asdict(bundle))}, bundle


def baseline_records(store, session, verifier, out):
    per_condition = {"A": {}, "B": {}}
    with row_writer(out / "baseline_records.jsonl.gz") as emit:
        for condition in ("A", "B"):
            for qid in verifier.questions:
                row, hits = search_record(store, session, verifier, condition, qid, 10)
                expected = verifier.t14[condition, qid]["hits"]
                if [(h.chunk_id, h.distance_text) for h in hits[:5]] != [(h["chunk_id"], h["distance_text"]) for h in expected]:
                    raise ValueError(f"A0/B0 원시 검색 재현 실패: {condition} {qid}")
                per_condition[condition][qid] = summarize(hits[:5], verifier.questions[qid])
                emit(row)
    return per_condition


def run_routes(store, session, protocol, out, reranker=None, config=None):
    from scripts.check_t14_graph_connection import GenerationRecorder, load_connection_generation, _route_observation
    from tests.test_router import BENCHMARK_CASES
    cache_path = ROOT / protocol["inputs"]["generation_cache"]["path"]
    events = load_connection_generation(ROOT / GENERATION_SOURCE, ROOT / protocol["inputs"]["queries"]["path"], cache_path)
    recorder = GenerationRecorder(json.loads(cache_path.read_bytes()), connection_events=events)
    rows = []
    with row_writer(out / "routes.jsonl") as emit:
        for condition in ("A", "B"):
            observations = []
            nodes = create_search_nodes(store, session, generate=recorder.generate, rewrite_enabled=condition == "B", hyde_enabled=False,
                                        observe=observations.append, reranker=reranker,
                                        candidate_k=config["candidate_k"] if config else 10,
                                        top_k=config["top_k"] if config else 5,
                                        min_score=config["min_score"] if config else None,
                                        rerank_weight=config.get('rerank_weight', 1.) if config else 1.)
            def wrap(node):
                def invoke(state):
                    recorder.context = _extract_query_and_constraints(state, preserve_literals=True)
                    before = copy.deepcopy({key: state.get(key) for key in ("request", "decision", "cursor", "research_count")})
                    result = node(state)
                    observations[-1]["state_preserved"] = before == {key: state.get(key) for key in before}
                    return result
                return invoke
            graph = create_router_graph(node_overrides={**{key: wrap(node) for key, node in nodes.items()},
                "INTAKE": lambda state: {"capabilities": RuntimeCapabilities(True, True, True)},
                "ANSWER": lambda state: {"answer": AnswerResult("SUPPORTED", "검색 계약 검증 대역"), "trace": [*state.get("trace", []), "ANSWER"]}})
            for case in BENCHMARK_CASES:
                observations.clear()
                request = RequestInput(request_id=f"t15_{condition}_{case['id']}", text=case["text"], assets=case["assets"], context=case["context"])
                state = graph.invoke({"request": request})
                row = {"condition": condition, "case_id": case["id"], "request": asdict(request), **_route_observation(state),
                       "trace": state.get("trace", []), "search_observations": copy.deepcopy(observations), "answer_test_double": True}
                emit(row)
                rows.append(row)
    return verify_routes(rows, RecordVerifier(protocol))


def grid_summary(config, per_condition, baseline, questions):
    a, b = per_condition["A"], per_condition["B"]
    am, bm = (compute_metrics_for_records(rows, questions) for rows in (a, b))
    a0, b0 = (compute_metrics_for_records(baseline[c], questions) for c in ("A", "B"))
    ar, br = regressions(a, baseline["A"]), regressions(b, baseline["B"])
    return {**config, "on_metrics": bm, "off_metrics": am, "on_regressions": br, "off_regressions": ar,
            "focus_ranks": {qid: b[qid]["first_gold_rank"] for qid in FOCUS_12_QIDS},
            "G2": not compare_quality(am, a0) and not compare_quality(bm, b0),
            "G3": not ar and not br and am["negative_counter_retrieved_count"] == bm["negative_counter_retrieved_count"] == 5}


def run_grid(protocol, protocol_path, out):
    verifier = RecordVerifier(protocol)
    summaries, configs, score_cache = [], [], {}
    with runtime_store(protocol) as (store, session):
        baseline = baseline_records(store, session, verifier, out)
        routes = run_routes(store, session, protocol, out)
        if routes["passed"] != 40:
            raise ValueError("기준선 실제 그래프 경로 실패")
        archive = None
        if protocol.get('score_archive'):
            from scripts.t15_score_archive import ScoreArchive
            archive = ScoreArchive(protocol, ROOT / protocol['score_archive']['run_dir'],
                                   ROOT / protocol['inputs']['score_archive_audit']['path'])
        models = {name: None if archive else load_reranker(protocol, name) for name in protocol["models"]}
        with row_writer(out / "search_records.jsonl.gz") as search_emit, row_writer(out / "score_records.jsonl.gz") as score_emit, row_writer(out / "records.jsonl.gz") as trial_emit:
            for pool in (20, 40):
                searches, all_hits, scores = {}, {}, {}
                for condition in ("A", "B"):
                    for index, qid in enumerate(verifier.questions, 1):
                        search, hits = search_record(store, session, verifier, condition, qid, pool)
                        searches[condition, qid], all_hits[condition, qid] = search, hits
                        search_emit(search)
                        for name, model in models.items():
                            scored = archive.score(name, search) if archive else score_record(model, name, search, hits, score_cache)
                            score_emit(scored)
                            scores[name, condition, qid] = scored
                        if index % 10 == 0:
                            print(f"후보{pool} {condition}: {index}/100 실제 검색·{'기존 채점 연결' if archive else '실제 채점'}", flush=True)
                for name in models:
                    for k in protocol["grid"]["top_k"]:
                        for threshold, weight in product(protocol["grid"]["min_score"], protocol['grid'].get('rerank_weight', [1.])):
                            config = {"condition_id": f"{name}_c{pool}_k{k}_min{threshold}_w{weight}", "model": name,
                                      "candidate_k": pool, "top_k": k, "min_score": threshold, "rerank_weight": weight}
                            configs.append(config)
                            per_condition = {"A": {}, "B": {}}
                            for condition in ("A", "B"):
                                for qid, question in verifier.questions.items():
                                    row, _ = trial(searches[condition, qid], scores[name, condition, qid], all_hits[condition, qid], config, protocol, question)
                                    trial_emit(row)
                                    per_condition[condition][qid] = row["metrics"]
                            summaries.append(grid_summary(config, per_condition, baseline, verifier.questions))
                focus = next(row["focus_ranks"] for row in summaries if row["model"] == "R1" and row["top_k"] == 5 and row["min_score"] is None
                             and row['rerank_weight'] == 1.)
                if pool == 20 and not should_expand_candidates(summaries, focus):
                    break
    write_json(out / "conditions.json", configs)
    with row_writer(out / "grid_records.jsonl") as emit:
        for row in summaries:
            emit(row)
    chosen = select_condition(summaries)
    diagnostic = min(summaries, key=lambda row: (len(row["on_regressions"]) + len(row["off_regressions"]), not row["G2"], abs(row["top_k"] - 5)))
    write_json(out / "selected_condition.json", {"selected_condition": chosen["condition_id"] if chosen else None,
               "adoption_status": "PENDING_T17" if chosen else "B0_MAINTAINED", "configuration": chosen,
               "diagnostic_best_candidate": diagnostic, "rationale": "양경로 G2/G3 통과 후보 선정" if chosen else "측정한 전체 조건에 양경로 비저하 후보 없음"})
    seal(out, protocol_path, "grid")
    result = audit_run(out)
    write_json(out / "validation.json", result)
    (out / "report.md").write_text(f"# Task 15 v3 검색 튜닝\n\n판정: {result['overall_verdict']}. 채택: B0 유지.\n\n실제 비교 조건 {len(configs)}개, 질문별 조건 관측 {result['record_count']}개.\n\n선정: {chosen['condition_id'] if chosen else '없음'}. 실제 T17과 CP3는 별도 게이트다.\n", encoding="utf-8")
    seal(out, protocol_path, "grid")
    return result["exit_code"]


def run_regression(protocol, protocol_path, selected_path, out):
    if selected_path is None:
        raise ValueError("--selected-condition이 필요합니다.")
    verify_manifest(selected_path.parent)
    selection = json.loads(selected_path.read_bytes())
    config = selection["configuration"]
    if config is None:
        write_json(out / "skipped.json", {"reason": "검색 품질 합격 후보가 없어 후보 회귀·실제 T17 채택 평가를 진행하지 않습니다."})
        seal(out, protocol_path, "regression", selected_sha256=sha256_file(selected_path),
             selected_path=str(selected_path.relative_to(ROOT)))
        return 2
    verifier = RecordVerifier(protocol)
    model = load_reranker(protocol, config["model"])
    write_json(out / "conditions.json", [config])
    repeats, summaries = [], []
    with runtime_store(protocol) as (store, session):
        baseline = baseline_records(store, session, verifier, out)
        run_routes(store, session, protocol, out, model, config)
        with row_writer(out / "search_records.jsonl.gz") as search_emit, row_writer(out / "score_records.jsonl.gz") as score_emit, row_writer(out / "records.jsonl.gz") as emit:
            for repetition in (1, 2, 3):
                raw = []
                per_condition = {"A": {}, "B": {}}
                for condition in ("A", "B"):
                    for index, (qid, question) in enumerate(verifier.questions.items(), 1):
                        search, hits = search_record(store, session, verifier, condition, qid, config["candidate_k"], repetition)
                        score = score_record(model, config["model"], search, hits)
                        row, _ = trial(search, score, hits, config, protocol, question)
                        search_emit(search); score_emit(score); emit(row)
                        raw.append(row)
                        per_condition[condition][qid] = row["metrics"]
                        if index % 10 == 0:
                            print(f"실제 반복{repetition} {condition} {index}/100", flush=True)
                repeats.append({"repeat_index": repetition, "record_count": len(raw), "result_digest": result_digest(raw)})
                summaries.append(grid_summary(config, per_condition, baseline, verifier.questions))
    with row_writer(out / "repeat_records.jsonl") as emit:
        for row in repeats:
            emit(row)
    seal(out, protocol_path, "regression", selected_sha256=sha256_file(selected_path), selected_path=str(selected_path.relative_to(ROOT)))
    result = audit_run(out, selected_path=selected_path)
    write_json(out / "validation.json", result)
    seal(out, protocol_path, "regression", selected_sha256=sha256_file(selected_path), selected_path=str(selected_path.relative_to(ROOT)))
    return result["exit_code"]


def run_t17(protocol, protocol_path, selected_path, retrieval_run, out):
    if selected_path is None:
        raise ValueError("--selected-condition이 필요합니다.")
    verify_manifest(selected_path.parent)
    selection = json.loads(selected_path.read_bytes())
    if selection["selected_condition"] is None:
        write_json(out / "skipped.json", {"reason": "검색 품질 합격 후보 없음. 실제 T17 비교는 보류하며 대역을 생성하지 않습니다."})
        seal(out, protocol_path, "t17", selected_sha256=sha256_file(selected_path), selected_path=str(selected_path.relative_to(ROOT)))
        return 2
    if retrieval_run is None:
        raise ValueError("실제 T17에는 --retrieval-run이 필요합니다.")
    result = audit_run(retrieval_run, selected_path=selected_path)
    if any(result["gates"][g]["status"] != "PASS" for g in ("G0", "G1", "G2", "G3", "G4")) or result["repeated"] != "PASS":
        raise ValueError("실제 답변 평가의 검색 선행 게이트 미달")
    from artagent.graph.answer import answer_standalone, T17_PROMPT_VERSION
    from artagent.answer import normalize_query
    from artagent.answer_validation import capture_code_state
    provider = os.getenv("LLM_PROVIDER", "codex").lower().strip()
    model_id = os.getenv("LLM_MODEL") or os.getenv("CODEX_MODEL") or "gpt-5.6-sol"
    if provider != "codex" or protocol["answer"] != {"provider": "codex-cli", "model": model_id,
                                                     "prompt_version": T17_PROMPT_VERSION}:
        raise ValueError("사전 등록한 답변 생성 설정과 다릅니다.")
    verifier = RecordVerifier(protocol)
    searches = {(r["condition"], r["query_id"]): r for r in read_rows(retrieval_run / "search_records.jsonl.gz") if r["repeat_index"] == 1}
    from scripts.t15_answer_validation import comparison_inputs
    needed, baseline_bundles, trials = comparison_inputs(verifier, retrieval_run)
    cases = []
    for qid in sorted(needed):
        for track in ("B0", "T15"):
            if track == "B0":
                bundle_dict = baseline_bundles[qid]
            else:
                search = searches["B", qid]
                by_id = {h.chunk_id: h for h in verifier.search(search)}
                bundle = RetrievalBundle(search["search_query"], search["source_type"].upper(),
                                         search_hits_to_evidences([by_id[cid] for cid in trials[qid]["selected_chunk_ids"]]),
                                         protocol["snapshot_fingerprint"])
                bundle_dict = asdict(bundle)
            cases.append({"query_id": qid, "track": track, "query": verifier.questions[qid]["query"],
                          "retrieval": bundle_dict, "parent": f"{retrieval_run.name}:{track}:{qid}"})
    write_json(out / "cases.json", cases)
    with row_writer(out / "answer_records.jsonl") as emit:
        for case in cases:
            observation = {}
            bundle = RetrievalBundle(**{**case["retrieval"], "hits": [Evidence(**h) for h in case["retrieval"]["hits"]]})
            answer, error = answer_standalone(case["query"], bundle, source_root=ROOT, observe=observation.update)
            meta = observation.get("runtime_meta") or {}
            emit({"record_schema": "t17-run-v3", "runtime": capture_code_state(ROOT),
                  "input_reference": {"path": str((out / "cases.json").relative_to(ROOT)), "sha256": sha256_file(out / "cases.json")},
                  "run_id": f"{out.name}:{case['track']}:{case['query_id']}", "track": case["track"], "query_id": case["query_id"],
                  "original_run_id": case["parent"], "input": {"query_original": case["query"], "query_normalized": normalize_query(case["query"]), "confirmed_context": None, "constraints": []},
                  "retrieval": case["retrieval"], "prompt": {"version": T17_PROMPT_VERSION, **{k: observation.get(k) for k in ("system_instruction", "user_prompt", "prompt_hash")}},
                  "generation": {"call_count": observation.get("call_count", 0), "request": observation.get("request"),
                     "provider": meta.get("llm_provider"), "model": meta.get("model_id"), "is_mock": False,
                     "runtime_meta": meta, "trace": observation.get("trace") or meta.get("_trace"), "usage": observation.get("usage"), "raw_response": observation.get("raw_response")},
                  "citations": [asdict(c) for c in answer.citations] if answer else [], "used_citations_provenance": observation.get("used_citations_provenance", []),
                  "output": {**asdict(answer), "error": asdict(error) if error else None} if answer else {"status": None, "error": asdict(error)},
                  "verification": {"manual_review": "pending"}})
    seal(out, protocol_path, "t17", retrieval_run=str(retrieval_run.relative_to(ROOT)),
         retrieval_manifest_sha256=sha256_file(retrieval_run / "manifest.json"), selected_sha256=sha256_file(selected_path),
         selected_path=str(selected_path.relative_to(ROOT)))
    return audit_run(out)["exit_code"]


def cmd_check(args) -> int:
    out = Path(args.run_dir).resolve()
    try:
        result = audit_run(out, Path(args.protocol).resolve() if getattr(args, "protocol", None) else None,
                           Path(args.selected_condition).resolve() if getattr(args, "selected_condition", None) else None,
                           Path(args.manual_reviews).resolve() if getattr(args, "manual_reviews", None) else None)
    except MissingEvidence as error:
        result = {"overall_verdict": "PENDING", "exit_code": 2, "reason": str(error)}
    except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
        result = {"overall_verdict": "FAIL", "exit_code": 1, "reason": str(error)}
    target = getattr(args, "audit_output", None) or getattr(args, "validation_output", None)
    if target:
        path = Path(target).resolve()
        if path.is_relative_to(out) or path.exists():
            raise ValueError("감사 결과는 실행 폴더 밖의 새 파일에 기록해야 합니다.")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["exit_code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--queries", default=str(ROOT / "docs/search_eval_queries.json"))
    prepare.add_argument("--reference", default=str(ROOT / "docs/T08_2_t9_handoff_reference.json"))
    prepare.add_argument("--t14-run", default=str(ROOT / T14))
    prepare.add_argument("--output-dir", required=True)
    prepare.add_argument("--score-source-run", help="격자의 기존 실제 채점 증거 폴더. 반복 회귀에는 재사용하지 않음")
    run = commands.add_parser("run")
    run.add_argument("--protocol", required=True)
    run.add_argument("--phase", required=True, choices=["grid", "regression", "t17"])
    run.add_argument("--selected-condition")
    run.add_argument("--retrieval-run")
    run.add_argument("--output-dir", required=True)
    check = commands.add_parser("check")
    check.add_argument("--run-dir", required=True)
    for name in ("protocol", "selected-condition", "manual-reviews", "audit-output", "validation-output"):
        check.add_argument("--" + name)
    args = parser.parse_args()
    if args.command == "check":
        return cmd_check(args)
    if args.command == "prepare":
        return cmd_prepare(args)
    protocol_path = Path(args.protocol).resolve()
    protocol = verify_protocol(protocol_path)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    selected = Path(args.selected_condition).resolve() if args.selected_condition else None
    try:
        if args.phase == "grid":
            return run_grid(protocol, protocol_path, out)
        if args.phase == "regression":
            return run_regression(protocol, protocol_path, selected, out)
        return run_t17(protocol, protocol_path, selected, Path(args.retrieval_run).resolve() if args.retrieval_run else None, out)
    except Exception as error:
        write_json(out / "failure.json", {"error": f"{type(error).__name__}: {error}"})
        seal(out, protocol_path, args.phase, execution_error=True)
        raise


if __name__ == "__main__":
    sys.exit(main())
