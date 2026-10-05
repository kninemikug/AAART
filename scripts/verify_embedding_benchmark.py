#!/usr/bin/env python3
"""Trace, reaggregate and independently verify the complete T08-2 matrix.

Old summaries are historical inputs, never completion evidence. All timing samples
come from a real batch-one query encode, Chroma query and result construction.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import importlib.metadata
import inspect
import json
from pathlib import Path
import random
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import chromadb
import numpy as np
import torch
from transformers import AutoTokenizer

from scripts import benchmark_embeddings as bench
from src.artagent.benchmark_validation import (
    aggregate_query_results, compare_retrieval_runs, select_stack, validate_query_log,
)
from src.artagent.chunking import (
    BGE_REVISION, Chunk, GUARD_GROUP_CONTRACTS, canonical_json_bytes,
    get_evidence_char_range, sha256_bytes, sha256_str, validate_chunk_provenance,
    verify_raw_text_coverage,
)

HNSW = {"space": "cosine", "ef_construction": 200, "ef_search": 200,
        "max_neighbors": 16, "num_threads": 1}
CODE_FILES = ("scripts/benchmark_embeddings.py", "scripts/verify_embedding_benchmark.py",
              "scripts/verify_embedding_policy_controls.py",
              "scripts/complete_embedding_validation.py", "scripts/chunk_corpus.py",
              "src/artagent/benchmark_validation.py", "src/artagent/chunking.py")


def digest_file(path):
    import hashlib
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(path):
    path = Path(path).resolve()
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def artifact(path):
    return {"path": relative(path), "sha256": digest_file(path)}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def write_log(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=1) as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return artifact(path)


def read_log(reference):
    path = REPO_ROOT / reference["path"]
    if digest_file(path) != reference["sha256"]:
        raise ValueError(f"Artifact hash mismatch: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def protocol(args):
    """Freeze actual code, sources, packages and common evaluation settings."""
    raw_paths = sorted((REPO_ROOT / "data/rawpedia").rglob("*.md"))
    snapshot_paths = sorted((REPO_ROOT / "data/issues/snapshots").rglob("*.json"))
    return {
        "version": "t08-2-traced-v1", "queries": artifact(args.queries),
        "rawpedia": {relative(p): digest_file(p) for p in raw_paths},
        "github_candidates": artifact(REPO_ROOT / "data/issues/search-candidates.json"),
        "github_snapshots": {relative(p): digest_file(p) for p in snapshot_paths},
        "source_manifest": artifact(REPO_ROOT / "docs/search_eval_source_manifest.json"),
        "github_sync_state": artifact(REPO_ROOT / "data/issues/sync-state.json"),
        "rawpedia_collection": artifact(REPO_ROOT / "docs/rawpedia_collection.md"),
        "code": {f: digest_file(REPO_ROOT / f) for f in CODE_FILES},
        "packages": {p: importlib.metadata.version(p) for p in
                     ("torch", "numpy", "chromadb", "sentence-transformers", "transformers", "tokenizers")},
        "environment": bench.get_environment_info(), "models": bench.MODEL_CONFIGS,
        "device": args.device, "dtype": "float32", "normalize": True,
        "torch_threads": 4, "seed": args.seed, "document_batch_size": args.batch_size,
        "query_batch_size": 1, "query_repeat": args.query_repeat, "warmup_queries": args.warmup_queries,
        "ks": list(args.ks), "context_budgets": list(args.context_budgets),
        "hnsw": HNSW, "index_insert_batch": 500, "index_insert_order": "chunk_id",
        "fetch_k": 10, "return_k": 5, "tie_sort": ["round(distance,6)", "chunk_id"],
        "relevance_threshold": 0.5, "full_evidence_threshold": 0.999,
        "metric_rounding": "none; four decimal display only",
        "negative_policy": "counterevidence diagnostics; excluded from quality denominators",
        "latency_scope": "encode(batch=1)->Chroma query(documents/metadatas/distances)->top5 construction with source segments",
        "metric_tolerance": 1e-9, "distance_tolerance": 1e-5,
        "vector_atol": 1e-6, "vector_rtol": 1e-5,
    }


def prepare_queries(path):
    queries = json.loads(Path(path).read_bytes())["queries"]
    cache = {}
    for query in queries:
        for ev in query["evidence"]:
            key = (ev["source_path"], ev.get("json_pointer"))
            if key not in cache:
                source = (REPO_ROOT / key[0]).read_bytes()
                if sha256_bytes(source) != ev["source_file_sha256"]:
                    raise ValueError(f"Evidence source hash mismatch: {key}")
                text = source.decode("utf-8")
                cache[key] = json.loads(text)["body"] if key[1] == "/body" else text
            ev["_char_start"], ev["_char_end"] = get_evidence_char_range(ev, cache[key])
    return queries


def load_chunks(path):
    return [Chunk.from_dict(json.loads(line)) for line in Path(path).read_text().splitlines() if line.strip()]


def verify_chunks(chunks, source_type):
    cache = {}
    def source(segment):
        key = (segment.source_path, segment.json_pointer)
        if key not in cache:
            raw = (REPO_ROOT / segment.source_path).read_bytes()
            text = raw.decode("utf-8")
            cache[key] = (json.loads(text)["body"] if segment.json_pointer == "/body" else text, sha256_bytes(raw))
        return cache[key]
    for chunk in chunks:
        validate_chunk_provenance(chunk, source)
    result = verify_raw_text_coverage(chunks, REPO_ROOT / "data/rawpedia",
        REPO_ROOT / "data/issues/search-candidates.json", REPO_ROOT / "data/issues", source_type=source_type)
    if result.get("zero_omission") is not True:
        raise ValueError(f"Source coverage failed: {result}")
    return result


def traced_vectors(variant, chunks, encoder, model_id, minfo, cache_dir, ref, batch_size=16, fresh=False):
    """Cache only complete input+implementation fingerprints, with window trace."""
    binding = {"chunks": [c.to_dict() for c in chunks], "model_id": model_id, "model": minfo,
               "encoder_code": sha256_str(inspect.getsource(bench.encode_chunk_list)),
               "dtype": "float32", "normalize": True, "batch_size": batch_size,
               "ref_tokenizer": ["BAAI/bge-small-en-v1.5", BGE_REVISION],
               "packages": {p: importlib.metadata.version(p) for p in
                            ("torch", "numpy", "sentence-transformers", "transformers", "tokenizers")}}
    key = sha256_bytes(canonical_json_bytes(binding))
    stem = Path(cache_dir) / key
    npy, metadata, trace_path = stem.with_suffix(".npy"), stem.with_suffix(".json"), stem.with_suffix(".jsonl.gz")
    if not fresh and metadata.is_file():
        saved = json.loads(metadata.read_bytes())
        if saved["input_fingerprint"] != key or digest_file(npy) != saved["vectors"]["sha256"]:
            raise ValueError("Vector cache fingerprint/hash mismatch")
        if digest_file(trace_path) != saved["window_trace"]["sha256"]:
            raise ValueError("Window trace hash mismatch")
        vectors = np.load(npy, allow_pickle=False)
        validate_vectors(vectors, len(chunks), minfo["hidden_size"])
        return vectors, saved
    trace = []
    start = time.perf_counter()
    vectors = bench.encode_chunk_list(chunks, encoder, model_id, minfo.get("doc_prefix", ""),
                                     ref, batch_size, trace_callback=trace.append)
    validate_vectors(vectors, len(chunks), minfo["hidden_size"])
    if len(trace) != len(chunks) or any(w["input_tokens"] > encoder.max_seq_length
                                     for t in trace for w in t["windows"]):
        raise ValueError("Incomplete trace or truncation")
    npy.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy, vectors)
    saved = {"input_fingerprint": key, "variant_id": variant, "model_id": model_id,
             "model_revision": minfo["revision"], "encoder_code": binding["encoder_code"],
             "vectors": artifact(npy), "window_trace": write_log(trace_path, trace),
             "chunk_count": len(chunks), "window_count": sum(len(t["windows"]) for t in trace),
             "truncation_count": 0, "encoding_seconds": time.perf_counter() - start}
    write_json(metadata, saved)
    print(f"ENCODE {model_id} {variant}: {len(chunks)} chunks, {saved['window_count']} windows, {saved['encoding_seconds']:.1f}s", flush=True)
    return vectors, saved


def validate_vectors(vectors, count, dimension):
    if vectors.dtype != np.float32 or vectors.shape != (count, dimension) or not np.isfinite(vectors).all():
        raise ValueError("Invalid vectors")
    if not np.all(np.abs(np.linalg.norm(vectors, axis=1) - 1) <= 1e-5):
        raise ValueError("Unnormalized/zero vectors")


def build_collection(client, name, chunks, vectors, legacy=False):
    try:
        client.delete_collection(name)
    except chromadb.errors.NotFoundError:
        pass
    if legacy:
        col = client.create_collection(name, embedding_function=None,
            metadata={"hnsw:space": "cosine", "hnsw:construction_ef": 200, "hnsw:search_ef": 200})
    else:
        col = client.create_collection(name, embedding_function=None, configuration={"hnsw": HNSW})
        vector_config = col.schema.keys["#embedding"].float_list.vector_index.config
        actual = {"space": vector_config.space, **{key: getattr(vector_config.hnsw, key)
                  for key in HNSW if key != "space"}}
        if any(actual[k] != v for k, v in HNSW.items()):
            raise ValueError(f"Applied Chroma configuration differs: {actual}")
    for offset in range(0, len(chunks), 500):
        batch = chunks[offset:offset+500]
        col.add(ids=[c.chunk_id for c in batch], embeddings=vectors[offset:offset+500].tolist(),
                documents=[c.content for c in batch], metadatas=[{
                    "source_type": c.source_type, "doc_id": c.doc_id,
                    "section_title": c.section_title[:100], "rule_id": c.metadata.get("rule_id", "")}
                    for c in batch])
    if col.count() != len(chunks):
        raise ValueError("Chroma count mismatch")
    return col


def latency_summary(values):
    array = np.asarray(values, dtype=np.float64)
    return {"observations_count": len(values), "mean_seconds": float(np.mean(array)),
            "median_seconds": float(np.median(array)), "p50_seconds": float(np.percentile(array, 50)),
            "p95_seconds": float(np.percentile(array, 95))}


def execute_row(row, chunks, vectors, encoder, minfo, queries, ref, client, work_dir, args, legacy=False):
    order = sorted(range(len(chunks)), key=lambda i: chunks[i].chunk_id)
    chunks, vectors = [chunks[i] for i in order], vectors[order]
    by_id = {c.chunk_id: c for c in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("Duplicate chunk IDs")
    start = time.perf_counter()
    name = "t08_2_" + row["experiment_id"]
    col = build_collection(client, name, chunks, vectors, legacy=legacy)
    index_seconds = time.perf_counter() - start
    vector_config = col.schema.keys["#embedding"].float_list.vector_index.config
    applied_index = {"space": vector_config.space, **{key: getattr(vector_config.hnsw, key)
                     for key in HNSW if key != "space"}}
    texts = [minfo.get("query_prefix", "") + q["query"] for q in queries]
    query_tokens = [len(encoder.tokenizer.encode(text, add_special_tokens=True)) for text in texts]
    if any(count > encoder.max_seq_length for count in query_tokens):
        raise ValueError("Query input truncation")
    legacy_query_vectors = encoder.encode(texts, batch_size=32, normalize_embeddings=True,
        show_progress_bar=False, convert_to_numpy=True).astype(np.float32) if legacy else None
    for text in texts[:args.warmup_queries]:
        vector = encoder.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        col.query(query_embeddings=[vector.tolist()], n_results=10)
    records, query_vectors, first_metrics, ann_diagnostics = [], None, None, []
    try:
        for repeat in range(args.query_repeat):
            ids, distances, elapsed, diagnostics = bench.query_collection_deterministic(
                col, encoder, texts, n_results=5 if legacy else 10,
                measure_latency=True, chunks_by_id=by_id, sort_candidates=not legacy,
                legacy_query_vectors=legacy_query_vectors)
            metrics = bench.evaluate_retrieval(queries, ids, by_id, {}, row["rawpedia_variant_id"],
                row["github_variant_id"], ks=tuple(args.ks), context_budgets=args.context_budgets, ref_tokenizer=ref)
            results = {q["query_id"]: q for q in metrics["query_results"]}
            qvecs = np.asarray([d.pop("_query_vector") for d in diagnostics], dtype=np.float32)
            validate_vectors(qvecs, len(queries), minfo["hidden_size"])
            if query_vectors is None:
                query_vectors, first_metrics = qvecs, metrics
            elif not np.allclose(query_vectors, qvecs, atol=1e-6, rtol=1e-5):
                raise ValueError("Repeated query vector drift")
            exact = np.argsort(-(qvecs @ vectors.T), axis=1)[:, :5]
            exact_ids = [[chunks[i].chunk_id for i in indices] for indices in exact]
            overlaps = [len(set(a) & set(b)) / 5 for a, b in zip(ids, exact_ids)]
            overlap = float(np.mean(overlaps))
            if overlap < .98:
                raise ValueError(f"ANN overlap below .98: {overlap}")
            for i, (query, text, diag, seconds) in enumerate(zip(queries, texts, diagnostics, elapsed)):
                evaluated = results[query["query_id"]]
                evaluated["top5_distances"] = distances[i]
                records.append({"experiment_id": row["experiment_id"], "query_id": query["query_id"],
                    "repeat": repeat, "query_input_hash": sha256_str(text), "total_seconds": seconds,
                    "query_input_tokens": query_tokens[i], "query_max_seq_length": encoder.max_seq_length,
                    "top5": diag.pop("top5"), "query_result": evaluated, "search_diagnostics": diag,
                    "exact_top5_ids": exact_ids[i], "ann_overlap_at_5": overlaps[i]})
            ann_diagnostics.append(overlap)
    finally:
        client.delete_collection(name)
    validate_query_log(records, [q["query_id"] for q in queries], args.query_repeat)
    log = write_log(Path(work_dir) / "runs" / (row["experiment_id"] + ".jsonl.gz"), records)
    query_path = Path(work_dir) / "query_vectors" / (row["experiment_id"] + ".npy")
    query_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(query_path, query_vectors)
    first_metrics.pop("query_results")
    return {**{k: v for k, v in row.items() if k not in ("rawpedia_variant", "github_variant")},
            "status": "completed", "dimension": minfo["hidden_size"], "total_chunks": len(chunks),
            "vector_bytes": int(vectors.nbytes), "index_build_seconds": index_seconds,
            "applied_index_configuration": applied_index,
            "latency_observations_sec": [r["total_seconds"] for r in records],
            "latency": latency_summary([r["total_seconds"] for r in records]),
            "ann_overlap_at_5": min(ann_diagnostics), "ann_overlap_by_repeat": ann_diagnostics,
            "metrics": first_metrics, "query_log": log, "query_vectors": artifact(query_path),
            "q091": next(r["query_result"] for r in records if r["query_id"] == "Q091")}


def validate_row(row, queries, repeat_count):
    if row["status"] != "completed":
        raise ValueError("Incomplete row")
    records = read_log(row["query_log"])
    validate_query_log(records, [q["query_id"] for q in queries], repeat_count)
    prefix = bench.MODEL_CONFIGS[row["model_id"]]["query_prefix"]
    expected_hashes = {q["query_id"]: sha256_str(prefix + q["query"]) for q in queries}
    if any(r["query_input_hash"] != expected_hashes[r["query_id"]] for r in records):
        raise ValueError("Actual query input differs from the fixed questions/prefix")
    entry = row["query_vectors"]
    if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
        raise ValueError("Query vector artifact drift")
    vectors = np.load(REPO_ROOT / entry["path"], allow_pickle=False)
    validate_vectors(vectors, len(queries), row["dimension"])
    first = {r["query_id"]: r for r in records if r["repeat"] == 0}
    if any(first[q["query_id"]]["search_diagnostics"]["query_vector_sha256"] != sha256_bytes(v.tobytes())
           for q, v in zip(queries, vectors)):
        raise ValueError("Actual query vector differs from logged vector hash")
    results = [r["query_result"] for r in records if r["repeat"] == 0]
    metrics = aggregate_query_results(results)
    compare_retrieval_runs({"metrics": row["metrics"], "query_results": results},
                           {"metrics": metrics, "query_results": results})
    times = [r["total_seconds"] for r in records]
    if times != row["latency_observations_sec"] or latency_summary(times) != row["latency"]:
        raise ValueError("Log/timer summary mismatch")
    min_ann = min(sum(r["ann_overlap_at_5"] for r in records if r["repeat"] == rep) / len(queries)
                  for rep in range(repeat_count))
    if abs(min_ann - row["ann_overlap_at_5"]) > 1e-9 or min_ann < .98:
        raise ValueError("ANN diagnostic mismatch")
    return results


def validate_guard(manifest, models, matrix):
    group = manifest["guard_group"]
    allowed = set(GUARD_GROUP_CONTRACTS[group]["allowed_models"])
    if set(manifest["guard_models"]) != allowed:
        raise ValueError("Guard model set mismatch")
    for model, actual in manifest["guard_models"].items():
        cfg = bench.MODEL_CONFIGS[model]
        if any(actual[key] != cfg[key] for key in ("revision", "max_seq_length", "query_prefix", "doc_prefix")):
            raise ValueError("Guard deployment configuration mismatch")
        if any(models[model][key] != actual[key] for key in
               ("revision", "max_seq_length", "query_prefix", "doc_prefix", "hidden_size")):
            raise ValueError("Evaluation model differs from the declared guard deployment")
    if sha256_str(json.dumps(manifest["guard_models"], sort_keys=True)) != manifest["guard_models_hash"]:
        raise ValueError("Guard model hash mismatch")
    for row in matrix:
        if row["guard_group"] != group or row["model_id"] not in allowed:
            raise ValueError("Row/guard mismatch")
        if row["model_revision"] != models[row["model_id"]]["revision"]:
            raise ValueError("Row/model revision mismatch")


def run_matrix(args):
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    args.context_budgets = list(args.context_budgets)
    if (args.device, args.batch_size, args.seed, args.query_repeat, list(args.ks), args.context_budgets) != (
            "cpu", 16, 42, 3, [1, 3, 5], [2048, 4096]):
        raise ValueError("The registered T08-2 protocol requires CPU/batch16/seed42/repeat3/k1,3,5/budgets2048,4096")
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    manifest = json.loads(Path(args.chunk_manifest).read_bytes())
    for source, expected in manifest["input_fingerprints"].items():
        if source == "rawpedia_files_sha256":
            continue
        if digest_file(REPO_ROOT / source) != expected:
            raise ValueError(f"Chunk manifest input drift: {source}")
    if getattr(args, "guard_group", None) and args.guard_group != manifest["guard_group"]:
        raise ValueError("Requested guard group differs from manifest")
    models = json.loads(Path(args.model_manifest).read_bytes())["models"]
    declared = json.loads(Path(args.matrix).read_bytes())["experiments"]
    validate_guard(manifest, models, declared)
    queries = prepare_queries(args.queries)
    ref = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION, local_files_only=True)
    contract = protocol(args)
    protocol_sha = sha256_bytes(canonical_json_bytes(contract))
    chunks, coverage, inputs = {}, {}, {}
    for vid in sorted({e[key] for e in declared for key in ("rawpedia_variant_id", "github_variant_id")}):
        entry = manifest["chunking_rules"][vid]
        path = REPO_ROOT / entry["file_path"]
        if digest_file(path) != entry["file_sha256"]:
            raise ValueError("Chunk JSONL hash mismatch")
        chunks[vid] = load_chunks(path)
        coverage[vid] = verify_chunks(chunks[vid], "rawpedia" if vid.startswith("R-") else "github")
        inputs[vid] = artifact(path)
    matrix = []
    for source in declared:
        row = dict(source)
        binding = {"protocol_sha256": protocol_sha, "model_id": row["model_id"], "revision": row["model_revision"],
                   "guard_models": manifest["guard_models"], "rawpedia": inputs[row["rawpedia_variant_id"]],
                   "github": inputs[row["github_variant_id"]], "requested_rawpedia": row["rawpedia_variant"],
                   "requested_github": row["github_variant"]}
        fingerprint = sha256_bytes(canonical_json_bytes(binding))
        row.update(origin_experiment_id=row["experiment_id"], experiment_id="exp_" + fingerprint[:24],
                   input_fingerprint=fingerprint, protocol_sha256=protocol_sha,
                   rawpedia_rule=row["rawpedia_variant_id"], github_rule=row["github_variant_id"],
                   source_binding=binding)
        matrix.append(row)
    matrix_sha = sha256_bytes(canonical_json_bytes(matrix))
    previous = {}
    output = Path(args.output_json)
    if output.is_file():
        old = json.loads(output.read_bytes())
        if old.get("protocol_sha256") != protocol_sha or old.get("matrix_sha256") != matrix_sha:
            raise ValueError("Resume rejected: code/input/protocol/matrix fingerprint drift")
        previous = {e["experiment_id"]: e for e in old["experiments"]}
        if len(previous) != len(old["experiments"]):
            raise ValueError("Duplicate resume rows")
    for path in (work_dir / "rows").glob("*.json"):
        saved = json.loads(path.read_bytes())
        if saved["protocol_sha256"] != protocol_sha:
            raise ValueError("Per-row checkpoint protocol mismatch")
        previous[saved["experiment_id"]] = saved
    write_json(work_dir / "protocol.json", {"protocol_sha256": protocol_sha, "protocol": contract})
    write_json(work_dir / "declared_matrix.json", {"matrix_sha256": matrix_sha, "experiments": matrix})
    write_json(work_dir / "coverage.json", {"variants": coverage, "inputs": inputs})
    completed = []
    current_model, encoder, cache = None, None, {}
    client = chromadb.PersistentClient(path=str(work_dir / "chroma"))
    def checkpoint():
        write_json(output, {"schema_version": 2, "dataset_id": "t08-1-100-v1", "status": "completed" if len(completed) == len(matrix) else "running",
            "protocol_sha256": protocol_sha, "protocol": contract, "matrix_sha256": matrix_sha,
            "matrix": artifact(work_dir / "declared_matrix.json"), "coverage": artifact(work_dir / "coverage.json"),
            "guard_manifest": artifact(args.chunk_manifest), "environment": bench.get_environment_info(),
            "target_matrix_count": len(matrix), "total_experiments_count": len(completed),
            "grid_complete": len(completed) == len(matrix), "models_evaluated": sorted({e['model_id'] for e in matrix}),
            "experiments": completed, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    for row in matrix:
        eid = row["experiment_id"]
        if eid in previous:
            prior = previous[eid]
            if prior["input_fingerprint"] != row["input_fingerprint"]:
                raise ValueError("Resume row input mismatch")
            validate_row(prior, queries, args.query_repeat)
            completed.append(prior)
            continue
        model_id = row["model_id"]
        minfo = models[model_id]
        if current_model != model_id:
            encoder = bench.load_encoder(model_id, minfo["revision"], args.device)
            if encoder.max_seq_length != minfo["max_seq_length"]:
                raise ValueError("Encoder deployment length mismatch")
            current_model, cache = model_id, {}
        for key in ("rawpedia_variant_id", "github_variant_id"):
            vid = row[key]
            if vid not in cache:
                cache[vid] = traced_vectors(vid, chunks[vid], encoder, model_id, minfo,
                    work_dir / "vectors", ref, args.batch_size)
        r, g = row["rawpedia_variant_id"], row["github_variant_id"]
        row["document_inputs"] = {"rawpedia": cache[r][1], "github": cache[g][1]}
        try:
            record = execute_row(row, chunks[r]+chunks[g], np.vstack([cache[r][0], cache[g][0]]),
                                 encoder, minfo, queries, ref, client, work_dir, args)
        except Exception as exc:
            write_json(work_dir / "failure.json", {"experiment_id": eid, "error": repr(exc),
                       "protocol_sha256": protocol_sha, "completed_count": len(completed)})
            checkpoint()
            raise
        completed.append(record)
        write_json(work_dir / "rows" / (eid + ".json"), record)
        if len(completed) % 25 == 0:
            checkpoint()
        print(f"ROW {len(completed)}/{len(matrix)} {model_id} {r} {g} MRR={record['metrics']['macro']['mrr@5']:.8f} p95={record['latency']['p95_seconds']:.6f}", flush=True)
    checkpoint()
    return 0


def check_report(args):
    """Full log audit; independent fresh vectors/index for mandatory targets."""
    data = validate_batch(Path(args.input_json))
    if not data.get("grid_complete") or data.get("status") != "completed":
        raise ValueError("Full declared matrix has not completed")
    queries = prepare_queries(REPO_ROOT / data["protocol"]["queries"]["path"])
    rows = data["experiments"]
    for row in rows:
        validate_row(row, queries, data["protocol"]["query_repeat"])
    output = {"status": "passed", "input": artifact(args.input_json), "rows_reaggregated": len(rows),
              "experiment_results_sha256": sha256_bytes(canonical_json_bytes(rows)),
              "protocol_sha256": data["protocol_sha256"],
              "observations_count": sum(len(e["latency_observations_sec"]) for e in rows), "reproduction": []}
    if args.verify_top_candidates:
        selection = select_stack(rows)
        ranked = sorted([r for r in rows if not r["is_diagnostic"]], key=lambda r: (-r["metrics"]["macro"]["mrr@5"], -r["metrics"]["macro"]["hit@5"], r["experiment_id"]))
        baseline = next(r for r in rows if r["model_id"] == "intfloat/multilingual-e5-small" and r["guard_group"] == "e5-512" and r["rawpedia_rule"] == "R-B-window-t448-o32" and r["github_rule"] == "G-A-curated-thread-w224-wo0")
        targets = [("quality_leader", selection["quality_leader"]), ("selected", selection["selected"]),
                   ("runner_up", ranked[1]), ("current_native_448_32_Q091", baseline)]
        ref = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION, local_files_only=True)
        work = Path(args.work_dir)
        work.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(work / "fresh-chroma"))
        settings = argparse.Namespace(**{k: data["protocol"][k] for k in
            ("seed", "device", "query_repeat", "warmup_queries", "ks", "context_budgets")})
        for label, row in targets:
            minfo = {**bench.MODEL_CONFIGS[row["model_id"]], "hidden_size": row["dimension"]}
            encoder = bench.load_encoder(row["model_id"], row["model_revision"], "cpu")
            chunks, vecs, vector_checks = [], [], {}
            for source in ("rawpedia", "github"):
                current = load_chunks(REPO_ROOT / row[f"{source}_file_path"])
                vectors, info = traced_vectors(row[f"{source}_variant_id"], current, encoder, row["model_id"], minfo,
                                               work / label / "vectors", ref, fresh=True)
                old_ref = row["document_inputs"][source]["vectors"]
                if digest_file(REPO_ROOT / old_ref["path"]) != old_ref["sha256"]:
                    raise ValueError("Original document vector hash mismatch")
                original = np.load(REPO_ROOT / old_ref["path"], allow_pickle=False)
                if not np.allclose(original, vectors, atol=1e-6, rtol=1e-5):
                    raise ValueError("Independent document vector mismatch")
                vector_checks[source] = {"max_abs_diff": float(np.max(np.abs(original-vectors))), "fresh": info}
                chunks.extend(current); vecs.append(vectors)
            fresh = execute_row(row, chunks, np.vstack(vecs), encoder, minfo, queries, ref, client, work / label, settings)
            expected_results, actual_results = validate_row(row, queries, 3), validate_row(fresh, queries, 3)
            check = compare_retrieval_runs({"metrics": row["metrics"], "query_results": expected_results},
                                         {"metrics": fresh["metrics"], "query_results": actual_results})
            before = np.load(REPO_ROOT / row["query_vectors"]["path"], allow_pickle=False)
            after = np.load(REPO_ROOT / fresh["query_vectors"]["path"], allow_pickle=False)
            if not np.allclose(before, after, atol=1e-6, rtol=1e-5):
                raise ValueError("Independent query vector mismatch")
            output["reproduction"].append({"label": label, "experiment_id": row["experiment_id"], **check,
                "vectors": vector_checks, "query_vector_max_abs_diff": float(np.max(np.abs(before-after))),
                "query_log": fresh["query_log"], "ann_overlap_at_5": fresh["ann_overlap_at_5"], "q091": fresh["q091"]})
            write_json(work / "reproduction.json", output)
    write_json(Path(args.work_dir) / "reproduction.json", output)
    return 0


def validate_batch(path):
    """Verify declaration coverage, protocol hashes, input artifacts and all logs."""
    data = json.loads(Path(path).read_bytes())
    if data.get("status") != "completed" or not data.get("grid_complete"):
        raise ValueError("Incomplete benchmark batch")
    if sha256_bytes(canonical_json_bytes(data["protocol"])) != data["protocol_sha256"]:
        raise ValueError("Protocol hash mismatch")
    for name, expected in data["protocol"]["code"].items():
        if digest_file(REPO_ROOT / name) != expected:
            raise ValueError(f"Benchmark code changed since measurement: {name}")
    for entry in [data["protocol"][k] for k in
                  ("queries", "github_candidates", "source_manifest", "github_sync_state", "rawpedia_collection")]:
        if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError("Dataset input fingerprint drift")
    for field in ("rawpedia", "github_snapshots"):
        for name, expected in data["protocol"][field].items():
            if digest_file(REPO_ROOT / name) != expected:
                raise ValueError(f"Source fingerprint drift: {name}")
    batches = data.get("batches", [data])
    expected_ids, declarations = set(), {}
    for batch in batches:
        entry = batch["matrix"]
        if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError("Declared matrix artifact drift")
        matrix = json.loads((REPO_ROOT / entry["path"]).read_bytes())["experiments"]
        if sha256_bytes(canonical_json_bytes(matrix)) != batch["matrix_sha256"]:
            raise ValueError("Declared matrix fingerprint drift")
        ids = [e["experiment_id"] for e in matrix]
        if len(ids) != len(set(ids)) or expected_ids.intersection(ids):
            raise ValueError("Duplicate declared experiments")
        expected_ids.update(ids)
        declarations.update({e["experiment_id"]: e for e in matrix})
        for field in ("coverage", "guard_manifest"):
            entry = batch[field]
            if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
                raise ValueError(f"{field} artifact drift")
    actual_ids = [e["experiment_id"] for e in data["experiments"]]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ValueError("Registered rows missing, duplicated or unexpected")
    queries = prepare_queries(REPO_ROOT / data["protocol"]["queries"]["path"])
    for row in data["experiments"]:
        if row["status"] != "completed" or row["protocol_sha256"] != data["protocol_sha256"]:
            raise ValueError("Incomplete/mixed protocol row")
        expected = declarations[row["experiment_id"]]
        if row["input_fingerprint"] != expected["input_fingerprint"] or row["source_binding"] != expected["source_binding"]:
            raise ValueError("Measured row input differs from declaration")
        if sha256_bytes(canonical_json_bytes(row["source_binding"])) != row["input_fingerprint"]:
            raise ValueError("Experiment fingerprint does not match complete inputs")
        validate_row(row, queries, data["protocol"]["query_repeat"])
    seen = set()
    for row in data["experiments"]:
        for source, document in row["document_inputs"].items():
            key = document["input_fingerprint"]
            if key in seen:
                continue
            seen.add(key)
            for field in ("vectors", "window_trace"):
                entry = document[field]
                if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
                    raise ValueError(f"Document {field} artifact drift")
            trace = read_log(document["window_trace"])
            if len(trace) != document["chunk_count"] or document["truncation_count"] != 0:
                raise ValueError("Incomplete window trace")
            limit = data["protocol"]["models"][row["model_id"]]["max_seq_length"]
            for chunk in trace:
                for window in chunk["windows"]:
                    if sha256_str(window["input"]) != window["input_sha256"] or window["input_tokens"] > limit:
                        raise ValueError("Window input hash/truncation mismatch")
                    if window["body_token_weight"] <= 0 or window["header_token_weight"] != 0:
                        raise ValueError("Window pooling weight mismatch")
    return data


def validate_release(path):
    """Require actual full-matrix and verification evidence before publication."""
    from scripts.complete_embedding_validation import expected_keys, row_key
    data = validate_batch(path)
    rows = data["experiments"]
    if data.get("validation_status") != "passed" or len(rows) != 5502:
        raise ValueError("Final publication requires all 5502 registered rows and passed verification")
    if {row_key(r) for r in rows} != expected_keys():
        raise ValueError("Final union differs from the plan")
    if sum(not r["is_diagnostic"] for r in rows) != 4716:
        raise ValueError("Wrong formal/diagnostic denominators")
    if sum(len(r["latency_observations_sec"]) for r in rows) != 1650600:
        raise ValueError("Wrong observation count")
    regeneration = data["validation"]["regeneration"]
    if len(regeneration) != 4:
        raise ValueError("All four guard groups require independent chunk regeneration")
    for entry in regeneration:
        if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError("Regeneration proof artifact drift")
        proof = json.loads((REPO_ROOT / entry["path"]).read_bytes())
        if proof["status"] != "passed" or proof["protocol_sha256"] != data["protocol_sha256"]:
            raise ValueError("Independent regeneration status/protocol mismatch")
        if digest_file(REPO_ROOT / proof["log"]["path"]) != proof["log"]["sha256"]:
            raise ValueError("Independent regeneration log drift")
    for field in ("policy_controls", "independent_reproduction"):
        entry = data["validation"][field]
        if digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Final {field} artifact hash mismatch")
    controls = json.loads((REPO_ROOT / data["validation"]["policy_controls"]["path"]).read_bytes())
    reproduction = json.loads((REPO_ROOT / data["validation"]["independent_reproduction"]["path"]).read_bytes())
    for record in (controls, reproduction):
        if record["status"] != "passed" or record["protocol_sha256"] != data["protocol_sha256"]:
            raise ValueError("Verification status/protocol mismatch")
    if reproduction["experiment_results_sha256"] != sha256_bytes(canonical_json_bytes(rows)):
        raise ValueError("Independent reproduction belongs to different measured results")
    labels = {r["label"] for r in reproduction["reproduction"] if r["status"] == "passed"}
    if labels != {"quality_leader", "selected", "runner_up", "current_native_448_32_Q091"}:
        raise ValueError("Required independent reproduction targets missing")
    if {r["experiment_id"] for r in controls["controls"]} != {"C0-legacy", "C0", "C1", "C2"}:
        raise ValueError("Required policy controls missing")
    if controls["historical_rounded_macro_mrr_at_5"] != .8032:
        raise ValueError("Historical baseline reproduction missing")
    chosen = select_stack(rows)
    if data["selected_stack"]["experiment_id"] != chosen["selected"]["experiment_id"]:
        raise ValueError("Published selection differs from unrounded complex-evidence selection")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--verify-top-candidates", action="store_true")
    return check_report(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
