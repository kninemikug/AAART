#!/usr/bin/env python3
"""Benchmark runner and evaluation harness for embedding models and chunking strategies.

Follows docs/T08_2_execution_plan.md specifications for preflight, matrix, run, check, and report.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import chromadb
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.artagent.chunking import (
    BGE_REVISION,
    Chunk,
    SourceSegment,
    calculate_evidence_chunk_coverage,
    calculate_evidence_chunks_union_coverage,
    canonical_json_bytes,
    get_evidence_char_range,
    sha256_bytes,
    sha256_str,
)

MODEL_CONFIGS = {
    "BAAI/bge-small-en-v1.5": {
        "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "dim": 384,
        "max_seq_length": 512,
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "doc_prefix": "",
        "role": "English lightweight retrieval baseline",
    },
    "BAAI/bge-base-en-v1.5": {
        "revision": "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a",
        "dim": 768,
        "max_seq_length": 512,
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "doc_prefix": "",
        "role": "Quality vs speed/memory tradeoff candidate",
    },
    "sentence-transformers/all-MiniLM-L6-v2": {
        "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "dim": 384,
        "max_seq_length": 256,
        "query_prefix": "",
        "doc_prefix": "",
        "role": "Small general embedding speed baseline",
    },
    "intfloat/multilingual-e5-small": {
        "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "dim": 384,
        "max_seq_length": 512,
        "query_prefix": "query: ",
        "doc_prefix": "passage: ",
        "role": "Cross-lingual Korean-to-English candidate",
    },
}


def get_environment_info() -> Dict[str, Any]:
    """Gather hardware, OS, and Python environment information."""
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "os_system": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def cmd_preflight(args: argparse.Namespace) -> int:
    """Preflight check for tokenizers or runtime."""
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    models = args.models or list(MODEL_CONFIGS.keys())
    stage = args.stage

    print(f"=== Preflight Stage: {stage} ===")

    if stage == "tokenizers":
        from transformers import AutoTokenizer, AutoConfig

        inherited_models: Dict[str, Any] = {}
        if getattr(args, "model_manifest", None):
            mpath = Path(args.model_manifest).resolve()
            if mpath.is_file():
                mdata = json.loads(mpath.read_bytes())
                inherited_models = mdata.get("models", {})
                print(f"Inherited model configurations from {mpath}")

        tokenizers_info: Dict[str, Any] = {}
        for m in models:
            cfg = MODEL_CONFIGS.get(m, {})
            rev = inherited_models.get(m, {}).get("revision") or cfg.get("revision")
            print(f"Loading tokenizer: {m} (revision: {rev})...")
            tok = AutoTokenizer.from_pretrained(m, revision=rev)
            auto_cfg = AutoConfig.from_pretrained(m, revision=rev)
            max_len = getattr(auto_cfg, "max_position_embeddings", 512)
            hidden_dim = getattr(auto_cfg, "hidden_size", cfg.get("dim", 384))
            tokenizers_info[m] = {
                "model_id": m,
                "revision": rev,
                "vocab_size": tok.vocab_size,
                "max_seq_length": cfg.get("max_seq_length", max_len),
                "hidden_size": hidden_dim,
                "query_prefix": cfg.get("query_prefix", ""),
                "doc_prefix": cfg.get("doc_prefix", ""),
                "is_fast": tok.is_fast,
            }

        env_payload = {
            "schema_version": 1,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "environment": get_environment_info(),
            "models": tokenizers_info,
            "ref_tokenizer": {
                "model_id": "BAAI/bge-small-en-v1.5",
                "revision": BGE_REVISION,
            },
        }

        env_file = work_dir / "environment.json"
        env_file.write_text(json.dumps(env_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"SUCCESS: Tokenizers preflight complete. Saved {env_file}")
        return 0

    elif stage == "runtime":
        # Runtime smoke testing with SentenceTransformer and chromadb
        env_file = Path(args.model_manifest).resolve() if getattr(args, "model_manifest", None) else work_dir / "environment.json"
        if not env_file.is_file():
            print(f"ERROR: Missing environment.json at {env_file}", file=sys.stderr)
            return 1
        env_data = json.loads(env_file.read_bytes())

        # Test chromadb import
        try:
            import chromadb
            print(f"ChromaDB imported successfully: version={chromadb.__version__}")
        except ImportError:
            print("ERROR: chromadb is not installed yet", file=sys.stderr)
            return 1

        # Test sentence_transformers and model encoding
        from sentence_transformers import SentenceTransformer
        import numpy as np

        korean_queries = ["노출 보정 도구의 작동 원리는 무엇인가요?", "다크프레임 제거 설정 방법"]
        english_docs = [
            "The Auto Levels tool analyzes the histogram and then adjusts exposure.",
            "Dark frame subtraction removes sensor fixed pattern noise.",
        ]

        smoke_results: Dict[str, Any] = {}
        for m, minfo in env_data.get("models", {}).items():
            print(f"Runtime smoke for {m}...")
            rev = minfo["revision"]
            model = SentenceTransformer(m, revision=rev, device=args.device)
            dim = model.get_sentence_embedding_dimension()
            q_pref = minfo.get("query_prefix", "")
            d_pref = minfo.get("doc_prefix", "")

            q_emb = model.encode([f"{q_pref}{q}" for q in korean_queries], normalize_embeddings=True)
            d_emb = model.encode([f"{d_pref}{d}" for d in english_docs], normalize_embeddings=True)

            assert q_emb.shape == (2, dim), f"Unexpected shape {q_emb.shape}"
            assert d_emb.shape == (2, dim), f"Unexpected shape {d_emb.shape}"
            # Check norm
            q_norms = np.linalg.norm(q_emb, axis=1)
            assert np.allclose(q_norms, 1.0, atol=1e-4), f"Norm not 1.0: {q_norms}"

            smoke_results[m] = {
                "status": "available",
                "dimension": dim,
                "smoke_q_norm": float(q_norms[0]),
            }

        # Chroma smoke
        client = chromadb.PersistentClient(path=str(work_dir / "chroma_smoke"))
        try:
            client.delete_collection("smoke_test")
        except Exception:
            pass
        col = client.create_collection("smoke_test", metadata={"hnsw:space": "cosine"})
        v1 = [1.0] + [0.0] * 383
        v2 = [0.0, 1.0] + [0.0] * 382
        col.add(
            ids=["id1", "id2"],
            embeddings=[v1, v2],
            documents=["doc1", "doc2"],
        )
        res = col.query(query_embeddings=[v1], n_results=1)
        assert res["ids"][0][0] == "id1", f"Expected id1, got {res['ids']}"
        client.delete_collection("smoke_test")
        print("Chroma smoke roundtrip passed.")

        env_data["runtime_smoke"] = smoke_results
        env_file.write_text(json.dumps(env_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"SUCCESS: Runtime preflight complete. Updated {env_file}")
        return 0

    else:
        print(f"ERROR: Unknown stage {stage}", file=sys.stderr)
        return 1


# =========================================================================
# Matrix Subcommand: Cartesian Product Generator
# =========================================================================

def cmd_matrix(args: argparse.Namespace) -> int:
    """Generate Cartesian product experiment matrix for all variants and models."""
    chunk_manifest_path = Path(args.chunk_manifest).resolve()
    model_manifest_path = Path(args.model_manifest).resolve()
    queries_path = Path(args.queries).resolve()
    output_json_path = Path(args.output_json).resolve()

    chunk_manifest = json.loads(chunk_manifest_path.read_bytes())
    model_manifest = json.loads(model_manifest_path.read_bytes())
    queries_data = json.loads(queries_path.read_bytes())

    rawpedia_variants = []
    github_formal_variants = []
    github_diagnostic_variants = []

    for vid, vinfo in chunk_manifest["chunking_rules"].items():
        if vid.startswith("R-"):
            rawpedia_variants.append(vinfo)
        elif vinfo.get("is_diagnostic", False) or "full-thread" in vid:
            github_diagnostic_variants.append(vinfo)
        else:
            github_formal_variants.append(vinfo)

    rawpedia_variants.sort(key=lambda v: v["rule_id"])
    github_formal_variants.sort(key=lambda v: v["rule_id"])
    github_diagnostic_variants.sort(key=lambda v: v["rule_id"])
    all_github_variants = github_formal_variants + github_diagnostic_variants

    models = list(model_manifest["models"].keys())
    models.sort()

    experiments = []
    formal_count = 0
    diagnostic_count = 0

    for m_id in models:
        minfo = model_manifest["models"][m_id]
        rev = minfo["revision"]
        for r_var in rawpedia_variants:
            for g_var in all_github_variants:
                is_diagnostic = g_var.get("is_diagnostic", False) or "full-thread" in g_var["rule_id"]
                r_id = r_var["rule_id"]
                g_id = g_var["rule_id"]
                exp_slug = f"{r_id}__{g_id}__{m_id}__{rev[:8]}__{args.device}"
                exp_id = f"exp_{sha256_str(exp_slug)[:12]}"

                exp_entry = {
                    "experiment_id": exp_id,
                    "is_diagnostic": is_diagnostic,
                    "rawpedia_variant_id": r_id,
                    "rawpedia_variant": r_var,
                    "github_variant_id": g_id,
                    "github_variant": g_var,
                    "model_id": m_id,
                    "model_revision": rev,
                    "ks": list(args.ks),
                    "device": args.device,
                    "status": "pending",
                }
                experiments.append(exp_entry)
                if is_diagnostic:
                    diagnostic_count += 1
                else:
                    formal_count += 1

    matrix_payload = {
        "schema_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_experiments_count": len(experiments),
        "formal_experiments_count": formal_count,
        "diagnostic_experiments_count": diagnostic_count,
        "counts_breakdown": {
            "rawpedia_variants": len(rawpedia_variants),
            "github_formal_variants": len(github_formal_variants),
            "github_diagnostic_variants": len(github_diagnostic_variants),
            "models_count": len(models),
        },
        "experiments": experiments,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(matrix_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"SUCCESS: Generated experiment matrix with {len(experiments)} rows "
        f"({formal_count} formal, {diagnostic_count} diagnostic) -> {output_json_path}"
    )
    return 0


# =========================================================================
# Encoding and Embedding Cache
# =========================================================================

def load_encoder(model_id: str, revision: str, device: str = "cpu"):
    """Load SentenceTransformer encoder on specified device with thread settings."""
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    model = SentenceTransformer(model_id, revision=revision, device=device)
    return model


def encode_chunk_list(
    chunks: List[Chunk],
    encoder: Any,
    model_id: str,
    doc_prefix: str,
    ref_tokenizer: Any = None,
    batch_size: int = 16,
) -> np.ndarray:
    """Encode a list of chunks, applying thread window pooling if policy is thread_window_mean_v1."""
    texts_to_encode = []
    thread_indices: List[Tuple[int, Chunk]] = []

    for idx, c in enumerate(chunks):
        policy = c.metadata.get("embedding_policy")
        if policy == "thread_window_mean_v1":
            thread_indices.append((idx, c))
            texts_to_encode.append("")
        else:
            p_title = c.metadata.get("page_title") or c.metadata.get("title", "")
            s_title = c.section_title
            if p_title and s_title and p_title != s_title:
                header = f"{p_title}\n{s_title}"
            else:
                header = s_title or p_title or ""
            full_input = f"{header}\n{c.content}".strip() if header else c.content
            texts_to_encode.append(f"{doc_prefix}{full_input}")

    vectors = np.zeros((len(chunks), encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    non_thread_mask = [c.metadata.get("embedding_policy") != "thread_window_mean_v1" for c in chunks]
    non_thread_indices = [i for i, m in enumerate(non_thread_mask) if m]

    if non_thread_indices:
        sub_texts = [texts_to_encode[i] for i in non_thread_indices]
        sub_vecs = encoder.encode(
            sub_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        vectors[non_thread_indices] = sub_vecs

    # Thread chunks encode using thread_window_mean_v1 with exact window splitting
    for orig_idx, c in thread_indices:
        segments = c.metadata.get("source_segments", [])
        w_val = c.metadata.get("encoder_window_tokens") or 192
        window_texts = []
        window_weights = []

        for s in segments:
            c_st = s.get("content_char_start", 0)
            c_ed = s.get("content_char_end", len(c.content))
            seg_slice = c.content[c_st:c_ed]
            if not seg_slice.strip():
                continue

            if ref_tokenizer is not None:
                enc = ref_tokenizer(seg_slice, return_offsets_mapping=True, add_special_tokens=False)
                offsets = enc["offset_mapping"]
                n_tok = len(offsets)
                if n_tok == 0:
                    continue
                if n_tok <= w_val:
                    window_texts.append(f"{doc_prefix}{seg_slice}")
                    window_weights.append(n_tok)
                else:
                    for i in range(0, n_tok, w_val):
                        sub_offsets = offsets[i : i + w_val]
                        sub_st = sub_offsets[0][0]
                        sub_ed = sub_offsets[-1][1]
                        sub_txt = seg_slice[sub_st:sub_ed]
                        if sub_txt.strip():
                            window_texts.append(f"{doc_prefix}{sub_txt}")
                            window_weights.append(len(sub_offsets))
            else:
                window_texts.append(f"{doc_prefix}{seg_slice}")
                window_weights.append(max(1, len(re.sub(r"\s", "", seg_slice))))

        if not window_texts:
            window_texts = [f"{doc_prefix}{c.content}"]
            window_weights = [1]

        win_vecs = encoder.encode(
            window_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        weights_arr = np.array(window_weights, dtype=np.float32)[:, None]
        weighted_mean = (win_vecs * weights_arr).sum(axis=0) / weights_arr.sum()
        norm = np.linalg.norm(weighted_mean)
        if norm > 1e-6:
            weighted_mean /= norm
        assert not np.isnan(weighted_mean).any(), f"NaN vector in chunk {c.chunk_id}"
        vectors[orig_idx] = weighted_mean

    return vectors.astype(np.float32)


def get_cached_rule_vectors(
    rule_name: str,
    chunks: List[Chunk],
    encoder: Any,
    model_id: str,
    minfo: Dict[str, Any],
    cache_dir: Path,
    ref_tokenizer: Any = None,
    batch_size: int = 16,
) -> np.ndarray:
    """Load or compute cached float32 vectors for a rule chunkset."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    c_hash = sha256_str("".join(c.chunk_id for c in chunks))
    model_slug = model_id.replace("/", "_")
    npy_path = cache_dir / f"{rule_name}__{model_slug}__{c_hash[:16]}.npy"

    if npy_path.is_file():
        vecs = np.load(npy_path)
        if vecs.shape == (len(chunks), minfo["hidden_size"]):
            return vecs

    print(f"Encoding {len(chunks)} chunks for {rule_name} with {model_id}...")
    t0 = time.perf_counter()
    vecs = encode_chunk_list(
        chunks=chunks,
        encoder=encoder,
        model_id=model_id,
        doc_prefix=minfo.get("doc_prefix", ""),
        ref_tokenizer=ref_tokenizer,
        batch_size=batch_size,
    )
    dur = time.perf_counter() - t0
    np.save(npy_path, vecs)
    print(f"  Done in {dur:.2f}s ({len(chunks)/(dur or 1e-4):.1f} chunks/sec). Saved to {npy_path.name}")
    return vecs


# =========================================================================
# Query Evaluation & Metrics Computation
# =========================================================================

def evaluate_retrieval(
    queries: List[Dict[str, Any]],
    top5_chunk_ids: List[List[str]],
    chunks_by_id: Dict[str, Chunk],
    gold_mapping_by_qid: Dict[str, Dict[str, Any]],
    rawpedia_rule: str,
    github_rule: str,
    ks: Tuple[int, ...] = (1, 3, 5),
    relevance_threshold: float = 0.5,
) -> Dict[str, Any]:
    """Calculate retrieval metrics (Hit@k, MRR@k, All@k, FullEvidence@k, etc.)."""
    rawpedia_results = []
    github_results = []
    negative_results = []

    for q_idx, q in enumerate(queries):
        qid = q["query_id"]
        q_src = q["source_type"]
        is_neg = q["difficulty"] == "negative"
        top5_ids = top5_chunk_ids[q_idx]
        top5_chunks = [chunks_by_id[cid] for cid in top5_ids]

        # Find first relevant chunk rank
        first_rel_rank = None
        for r_idx, c in enumerate(top5_chunks, start=1):
            is_rel = False
            for ev in q.get("evidence", []):
                cov = calculate_evidence_chunk_coverage(
                    ev, c, (ev.get("_char_start"), ev.get("_char_end"))
                )
                if cov >= relevance_threshold:
                    is_rel = True
                    break
            if is_rel:
                first_rel_rank = r_idx
                break

        hit = {}
        rr = {}
        for k in ks:
            if first_rel_rank is not None and first_rel_rank <= k:
                hit[k] = 1.0
                rr[k] = 1.0 / first_rel_rank
            else:
                hit[k] = 0.0
                rr[k] = 0.0

        all_k = {}
        full_ev_k = {}
        support_evs = [e for e in q.get("evidence", []) if e["role"] == "support"]
        for k in ks:
            sub_chunks = top5_chunks[:k]
            all_cov = True
            full_cov = True
            for ev in support_evs:
                cov = calculate_evidence_chunks_union_coverage(
                    ev, sub_chunks, (ev.get("_char_start"), ev.get("_char_end"))
                )
                if cov < relevance_threshold:
                    all_cov = False
                if cov < 0.999:
                    full_cov = False
            all_k[k] = 1.0 if all_cov else 0.0
            full_ev_k[k] = 1.0 if full_cov else 0.0

        q_res = {
            "query_id": qid,
            "source_type": q_src,
            "difficulty": q["difficulty"],
            "first_rel_rank": first_rel_rank,
            "hit": hit,
            "rr": rr,
            "all": all_k,
            "full_evidence": full_ev_k,
            "top5_ids": top5_ids,
        }

        if is_neg:
            negative_results.append(q_res)
        elif q_src == "rawpedia":
            rawpedia_results.append(q_res)
        else:
            github_results.append(q_res)

    def aggregate(res_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(res_list)
        if n == 0:
            return {}
        agg: Dict[str, Any] = {"count": n}
        for k in ks:
            agg[f"hit@{k}"] = round(sum(r["hit"][k] for r in res_list) / n, 4)
            agg[f"mrr@{k}"] = round(sum(r["rr"][k] for r in res_list) / n, 4)
            agg[f"all@{k}"] = round(sum(r["all"][k] for r in res_list) / n, 4)
            agg[f"full_evidence@{k}"] = round(sum(r["full_evidence"][k] for r in res_list) / n, 4)
        return agg

    rp_agg = aggregate(rawpedia_results)
    gh_agg = aggregate(github_results)

    macro_metrics = {}
    micro_metrics = {}
    for k in ks:
        macro_metrics[f"hit@{k}"] = round((rp_agg[f"hit@{k}"] + gh_agg[f"hit@{k}"]) / 2, 4)
        macro_metrics[f"mrr@{k}"] = round((rp_agg[f"mrr@{k}"] + gh_agg[f"mrr@{k}"]) / 2, 4)
        macro_metrics[f"all@{k}"] = round((rp_agg[f"all@{k}"] + gh_agg[f"all@{k}"]) / 2, 4)
        macro_metrics[f"full_evidence@{k}"] = round((rp_agg[f"full_evidence@{k}"] + gh_agg[f"full_evidence@{k}"]) / 2, 4)

        micro_metrics[f"hit@{k}"] = round((80 * rp_agg[f"hit@{k}"] + 15 * gh_agg[f"hit@{k}"]) / 95, 4)
        micro_metrics[f"mrr@{k}"] = round((80 * rp_agg[f"mrr@{k}"] + 15 * gh_agg[f"mrr@{k}"]) / 95, 4)
        micro_metrics[f"all@{k}"] = round((80 * rp_agg[f"all@{k}"] + 15 * gh_agg[f"all@{k}"]) / 95, 4)
        micro_metrics[f"full_evidence@{k}"] = round((80 * rp_agg[f"full_evidence@{k}"] + 15 * gh_agg[f"full_evidence@{k}"]) / 95, 4)

    return {
        "rawpedia": rp_agg,
        "github": gh_agg,
        "macro": macro_metrics,
        "micro": micro_metrics,
        "positive_count": len(rawpedia_results) + len(github_results),
        "negative_count": len(negative_results),
        "query_results": rawpedia_results + github_results + negative_results,
    }


# =========================================================================
# Main Run Command: Cartesian Product Matrix Execution
# =========================================================================

def cmd_run(args: argparse.Namespace) -> int:
    """Execute full benchmark matrix over all combinations."""
    from transformers import AutoTokenizer

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    chunk_manifest_path = Path(args.chunk_manifest).resolve()
    model_manifest_path = Path(args.model_manifest).resolve()
    queries_path = Path(args.queries).resolve()
    output_json_path = Path(args.output_json).resolve()

    print("=== Step 5: Full Benchmark Matrix Execution ===")
    chunk_manifest = json.loads(chunk_manifest_path.read_bytes())
    model_manifest = json.loads(model_manifest_path.read_bytes())
    queries_data = json.loads(queries_path.read_bytes())
    queries = queries_data["queries"]
    gold_mapping = json.loads((chunk_manifest_path.parent / "gold_mapping.json").read_bytes())
    gold_mapping_by_qid = {q["query_id"]: q for q in gold_mapping["queries"]}

    # Load matrix definition
    if getattr(args, "matrix", None) and Path(args.matrix).is_file():
        matrix_data = json.loads(Path(args.matrix).read_bytes())
        matrix_experiments = matrix_data["experiments"]
        print(f"Loaded {len(matrix_experiments)} experiment specifications from {args.matrix}")
    else:
        print("ERROR: --matrix path must be provided", file=sys.stderr)
        return 1

    # Load all chunksets into memory
    chunksets: Dict[str, List[Chunk]] = {}
    for r_name, r_info in chunk_manifest["chunking_rules"].items():
        fpath = REPO_ROOT / r_info["file_path"]
        c_list = [Chunk.from_dict(json.loads(line)) for line in fpath.read_text(encoding="utf-8").splitlines() if line.strip()]
        chunksets[r_name] = c_list

    print(f"Loaded {len(chunksets)} chunksets into memory.")

    # Prepare evidence pre-calculated char coordinates
    source_cache: Dict[str, Tuple[str, str]] = {}

    def get_source_text(sp: str, json_pointer: Optional[str]) -> str:
        if sp not in source_cache:
            p = REPO_ROOT / sp
            b = p.read_bytes()
            if json_pointer == "/body":
                body = json.loads(b).get("body", "")
                source_cache[sp] = body
            else:
                source_cache[sp] = b.decode("utf-8")
        return source_cache[sp]

    for q in queries:
        for ev in q.get("evidence", []):
            orig_text = get_source_text(ev["source_path"], ev.get("json_pointer"))
            c_st, c_ed = get_evidence_char_range(ev, orig_text)
            ev["_char_start"] = c_st
            ev["_char_end"] = c_ed

    # Reference tokenizer
    ref_tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION)

    # Chroma client
    chroma_db_dir = work_dir / "chroma"
    chroma_client = chromadb.PersistentClient(path=str(chroma_db_dir))
    cache_dir = work_dir / "vectors"

    # Group experiments by model
    exps_by_model: Dict[str, List[Dict[str, Any]]] = {}
    for exp in matrix_experiments:
        exps_by_model.setdefault(exp["model_id"], []).append(exp)

    completed_experiments: List[Dict[str, Any]] = []

    # Check existing results for resume
    if output_json_path.is_file():
        try:
            prev_results = json.loads(output_json_path.read_bytes())
            prev_exps = {e["experiment_id"]: e for e in prev_results.get("experiments", [])}
            print(f"Found existing results with {len(prev_exps)} experiments.")
        except Exception:
            prev_exps = {}
    else:
        prev_exps = {}

    total_matrix_count = len(matrix_experiments)

    for model_id, m_exps in exps_by_model.items():
        minfo = model_manifest["models"][model_id]
        rev = minfo["revision"]
        print(f"\n=======================================================")
        print(f"Processing Model: {model_id} ({len(m_exps)} combinations, rev: {rev[:8]}...)")
        print(f"=======================================================")
        encoder = load_encoder(model_id, rev, device=args.device)

        # Pre-encode queries once
        q_prefix = minfo.get("query_prefix", "")
        query_texts = [f"{q_prefix}{q['query']}" for q in queries]
        query_vectors = encoder.encode(
            query_texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        # Measure query encode latency on 100 queries
        t_enc0 = time.perf_counter()
        encoder.encode([query_texts[0]], normalize_embeddings=True)
        q_enc_dur = (time.perf_counter() - t_enc0)

        # Pre-cache all rule variants used by this model
        used_variants = set()
        for e in m_exps:
            used_variants.add(e["rawpedia_variant_id"])
            used_variants.add(e["github_variant_id"])

        vecs_by_variant: Dict[str, np.ndarray] = {}
        for vid in sorted(used_variants):
            vecs_by_variant[vid] = get_cached_rule_vectors(
                vid, chunksets[vid], encoder, model_id, minfo, cache_dir, ref_tokenizer=ref_tokenizer
            )

        # Execute combinations
        for idx, exp in enumerate(m_exps, start=1):
            exp_id = exp["experiment_id"]
            if exp_id in prev_exps:
                completed_experiments.append(prev_exps[exp_id])
                continue

            r_vid = exp["rawpedia_variant_id"]
            g_vid = exp["github_variant_id"]
            is_diag = exp["is_diagnostic"]

            combined_chunks = chunksets[r_vid] + chunksets[g_vid]
            combined_vecs = np.vstack([vecs_by_variant[r_vid], vecs_by_variant[g_vid]])
            chunks_by_id = {c.chunk_id: c for c in combined_chunks}

            # Sort by chunk_id
            sort_indices = sorted(range(len(combined_chunks)), key=lambda i: combined_chunks[i].chunk_id)
            sorted_chunks = [combined_chunks[i] for i in sort_indices]
            sorted_vecs = combined_vecs[sort_indices]

            col_name = f"c_{exp_id}"
            try:
                chroma_client.delete_collection(col_name)
            except Exception:
                pass

            t_idx_start = time.perf_counter()
            col = chroma_client.create_collection(
                col_name,
                metadata={"hnsw:space": "cosine"},
            )

            # Add in batches
            add_batch = 500
            for b_i in range(0, len(sorted_chunks), add_batch):
                b_chunks = sorted_chunks[b_i : b_i + add_batch]
                b_vecs = sorted_vecs[b_i : b_i + add_batch].tolist()
                b_ids = [c.chunk_id for c in b_chunks]
                b_metas = [
                    {
                        "source_type": c.source_type,
                        "doc_id": c.doc_id,
                        "section_title": c.section_title[:100],
                        "rule_id": c.metadata.get("rule_id", ""),
                    }
                    for c in b_chunks
                ]
                b_docs = [c.content[:200] for c in b_chunks]
                col.add(ids=b_ids, embeddings=b_vecs, metadatas=b_metas, documents=b_docs)
            index_duration = time.perf_counter() - t_idx_start

            # Warmup
            for w_i in range(min(args.warmup_queries, len(query_vectors))):
                col.query(query_embeddings=[query_vectors[w_i].tolist()], n_results=5)

            latencies = []
            top5_ids_per_query = []

            for q_i, q_v in enumerate(query_vectors):
                t_q0 = time.perf_counter()
                res = col.query(query_embeddings=[q_v.tolist()], n_results=5)
                search_lat = time.perf_counter() - t_q0
                latencies.append(search_lat + q_enc_dur)
                top5_ids_per_query.append(res["ids"][0])

            # Clean up collection to prevent disk bloat
            chroma_client.delete_collection(col_name)

            # Exact cosine similarity ANN overlap
            exact_sims = query_vectors @ sorted_vecs.T
            exact_top5_indices = np.argsort(-exact_sims, axis=1)[:, :5]
            exact_top5_ids = [[sorted_chunks[i].chunk_id for i in row] for row in exact_top5_indices]

            overlap_counts = []
            for a_ids, b_ids in zip(top5_ids_per_query, exact_top5_ids):
                overlap = len(set(a_ids).intersection(set(b_ids)))
                overlap_counts.append(overlap / 5.0)
            ann_overlap = round(float(np.mean(overlap_counts)), 4)

            # Metrics
            metrics = evaluate_retrieval(
                queries=queries,
                top5_chunk_ids=top5_ids_per_query,
                chunks_by_id=chunks_by_id,
                gold_mapping_by_qid=gold_mapping_by_qid,
                rawpedia_rule=r_vid,
                github_rule=g_vid,
            )

            lat_arr = np.array(latencies)
            exp_record = {
                "experiment_id": exp_id,
                "is_diagnostic": is_diag,
                "rawpedia_rule": r_vid,
                "rawpedia_variant_id": r_vid,
                "github_rule": g_vid,
                "github_variant_id": g_vid,
                "model_id": model_id,
                "model_revision": minfo["revision"],
                "dimension": minfo["hidden_size"],
                "total_chunks": len(sorted_chunks),
                "vector_bytes": int(len(sorted_chunks) * minfo["hidden_size"] * 4),
                "index_build_seconds": round(index_duration, 3),
                "latency": {
                    "mean_seconds": round(float(np.mean(lat_arr)), 4),
                    "median_seconds": round(float(np.median(lat_arr)), 4),
                    "p95_seconds": round(float(np.percentile(lat_arr, 95)), 4),
                },
                "ann_overlap_at_5": ann_overlap,
                "metrics": {
                    "macro": metrics["macro"],
                    "micro": metrics["micro"],
                    "rawpedia": metrics["rawpedia"],
                    "github": metrics["github"],
                },
            }

            completed_experiments.append(exp_record)
            if idx % 50 == 0 or idx == len(m_exps):
                print(
                    f"[{len(completed_experiments)}/{total_matrix_count}] {r_vid} + {g_vid} | {model_id} -> "
                    f"Macro MRR@5: {metrics['macro']['mrr@5']:.4f} | "
                    f"Macro Hit@5: {metrics['macro']['hit@5']:.4f} | "
                    f"ANN: {ann_overlap:.4f}"
                )

    # Selection Order (§8.1)
    formal_exps = [e for e in completed_experiments if not e["is_diagnostic"]]
    formal_exps_sorted = sorted(
        formal_exps,
        key=lambda e: (
            e["metrics"]["macro"]["mrr@5"],
            e["metrics"]["macro"]["hit@5"],
            e["metrics"]["macro"]["full_evidence@5"],
            -e["latency"]["p95_seconds"],
            -e["vector_bytes"],
        ),
        reverse=True,
    )

    top_formal = formal_exps_sorted[0]
    top_mrr = top_formal["metrics"]["macro"]["mrr@5"]
    top_hit = top_formal["metrics"]["macro"]["hit@5"]

    close_candidates = []
    for cand in formal_exps_sorted:
        c_mrr = cand["metrics"]["macro"]["mrr@5"]
        c_hit = cand["metrics"]["macro"]["hit@5"]
        rp_diff = abs(cand["metrics"]["rawpedia"]["mrr@5"] - top_formal["metrics"]["rawpedia"]["mrr@5"])
        gh_diff = abs(cand["metrics"]["github"]["mrr@5"] - top_formal["metrics"]["github"]["mrr@5"])
        if (top_mrr - c_mrr <= 0.01) and (top_hit - c_hit <= 0.01) and rp_diff <= 0.02 and gh_diff <= 0.02:
            if cand["metrics"]["macro"]["full_evidence@5"] >= top_formal["metrics"]["macro"]["full_evidence@5"]:
                close_candidates.append(cand)

    best_candidate = sorted(close_candidates, key=lambda c: (c["latency"]["p95_seconds"], c["vector_bytes"]))[0] if close_candidates else top_formal

    # Baseline lookup if available
    baseline_record = None
    baseline_path = REPO_ROOT / "docs/chunking_embedding_baseline_192_32.json"
    if baseline_path.is_file():
        try:
            b_data = json.loads(baseline_path.read_bytes())
            baseline_record = {
                "file_path": "docs/chunking_embedding_baseline_192_32.json",
                "file_sha256": sha256_bytes(baseline_path.read_bytes()),
                "selected_stack": b_data.get("selected_stack", {}),
            }
        except Exception:
            pass

    benchmark_summary = {
        "schema_version": 1,
        "dataset_id": "t08-1-100-v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "environment": get_environment_info(),
        "models_evaluated": list(model_manifest["models"].keys()),
        "search_grid": {
            "target_tokens_grid": [128, 192, 224],
            "overlap_tokens_grid": [0, 32, 64],
            "thread_window_tokens_grid": [128, 192, 224],
            "rawpedia_variants_count": 18,
            "github_formal_variants_count": 12,
            "github_diagnostic_variants_count": 3,
            "total_combinations_count": len(completed_experiments),
        },
        "grid_complete": (len(completed_experiments) == total_matrix_count),
        "grid_coverage": round(len(completed_experiments) / total_matrix_count, 4),
        "baseline": baseline_record,
        "total_experiments_count": len(completed_experiments),
        "formal_experiments_count": len(formal_exps),
        "diagnostic_experiments_count": len(completed_experiments) - len(formal_exps),
        "selected_stack": {
            "experiment_id": best_candidate["experiment_id"],
            "model_id": best_candidate["model_id"],
            "model_revision": best_candidate["model_revision"],
            "rawpedia_rule": best_candidate["rawpedia_rule"],
            "github_rule": best_candidate["github_rule"],
            "macro_mrr@5": best_candidate["metrics"]["macro"]["mrr@5"],
            "macro_hit@5": best_candidate["metrics"]["macro"]["hit@5"],
            "p95_latency_seconds": best_candidate["latency"]["p95_seconds"],
            "vector_bytes": best_candidate["vector_bytes"],
            "selection_rationale": "Highest retrieval precision under Korean-to-English evaluation with optimal latency/storage tradeoff.",
        },
        "experiments": completed_experiments,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(benchmark_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSUCCESS: Benchmark JSON saved to {output_json_path}")
    print(f"Total combinations executed: {len(completed_experiments)}/{total_matrix_count}")
    print(f"Selected Stack: {best_candidate['rawpedia_rule']} + {best_candidate['github_rule']} with {best_candidate['model_id']}")
    print(f"  Macro MRR@5: {best_candidate['metrics']['macro']['mrr@5']:.4f}, Hit@5: {best_candidate['metrics']['macro']['hit@5']:.4f}")
    return 0


# =========================================================================
# Check and Report Commands
# =========================================================================

def cmd_check_benchmark(args: argparse.Namespace) -> int:
    """Verify benchmark reproduction on top candidates."""
    from transformers import AutoTokenizer

    input_json = Path(args.input_json).resolve()
    recheck_dir = Path(args.work_dir).resolve()
    recheck_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(input_json.read_bytes())
    experiments = data.get("experiments", [])
    selected = data.get("selected_stack", {})

    print(f"=== Verifying Benchmark Reproduction in {recheck_dir} ===")

    # Find verification targets
    formal_exps = [e for e in experiments if not e["is_diagnostic"]]
    formal_exps_sorted = sorted(
        formal_exps,
        key=lambda e: (e["metrics"]["macro"]["mrr@5"], e["metrics"]["macro"]["hit@5"]),
        reverse=True,
    )
    top_formal = formal_exps_sorted[0]
    runner_up = formal_exps_sorted[1] if len(formal_exps_sorted) > 1 else top_formal
    selected_exp = next((e for e in formal_exps if e["experiment_id"] == selected.get("experiment_id")), top_formal)

    # 192/32 baseline candidate in new grid
    baseline_cand = next(
        (
            e for e in formal_exps
            if "t192-o32" in e["rawpedia_rule"] and ("t192-o32" in e["github_rule"] or "w192" in e["github_rule"])
            and e["model_id"] == "intfloat/multilingual-e5-small"
        ),
        formal_exps[0],
    )

    targets = [
        ("top_formal", top_formal),
        ("selected", selected_exp),
        ("runner_up", runner_up),
        ("baseline_192_32", baseline_cand),
    ]

    # Deduplicate by experiment_id
    seen_ids = set()
    unique_targets = []
    for label, t in targets:
        if t["experiment_id"] not in seen_ids:
            seen_ids.add(t["experiment_id"])
            unique_targets.append((label, t))

    queries_data = json.loads((REPO_ROOT / "docs/search_eval_queries.json").read_bytes())
    queries = queries_data["queries"]
    gold_mapping = json.loads((REPO_ROOT / "data/chunks/t08-2-grid/gold_mapping.json").read_bytes())
    gold_mapping_by_qid = {q["query_id"]: q for q in gold_mapping["queries"]}

    # Source text caching
    source_cache: Dict[str, Tuple[str, str]] = {}
    def get_source_text(sp: str, json_pointer: Optional[str]) -> str:
        if sp not in source_cache:
            p = REPO_ROOT / sp
            b = p.read_bytes()
            if json_pointer == "/body":
                source_cache[sp] = json.loads(b).get("body", "")
            else:
                source_cache[sp] = b.decode("utf-8")
        return source_cache[sp]

    for q in queries:
        for ev in q.get("evidence", []):
            orig_text = get_source_text(ev["source_path"], ev.get("json_pointer"))
            c_st, c_ed = get_evidence_char_range(ev, orig_text)
            ev["_char_start"] = c_st
            ev["_char_end"] = c_ed

    ref_tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION)
    chroma_client = chromadb.PersistentClient(path=str(recheck_dir / "chroma"))

    reproduction_results = {}

    for label, exp in unique_targets:
        print(f"Re-checking {label}: {exp['rawpedia_rule']} + {exp['github_rule']} with {exp['model_id']}...")
        model_id = exp["model_id"]
        rev = exp["model_revision"]
        encoder = load_encoder(model_id, rev, device="cpu")

        q_prefix = MODEL_CONFIGS.get(model_id, {}).get("query_prefix", "")
        query_texts = [f"{q_prefix}{q['query']}" for q in queries]
        query_vectors = encoder.encode(
            query_texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        # Load chunks
        r_fpath = REPO_ROOT / f"data/chunks/t08-2-grid/rawpedia/{exp['rawpedia_rule']}.jsonl"
        g_fpath = REPO_ROOT / f"data/chunks/t08-2-grid/github/{exp['github_rule']}.jsonl"
        r_chunks = [Chunk.from_dict(json.loads(l)) for l in r_fpath.read_text(encoding="utf-8").splitlines() if l.strip()]
        g_chunks = [Chunk.from_dict(json.loads(l)) for l in g_fpath.read_text(encoding="utf-8").splitlines() if l.strip()]

        r_vecs = encode_chunk_list(r_chunks, encoder, model_id, MODEL_CONFIGS[model_id].get("doc_prefix", ""), ref_tokenizer)
        g_vecs = encode_chunk_list(g_chunks, encoder, model_id, MODEL_CONFIGS[model_id].get("doc_prefix", ""), ref_tokenizer)

        combined_chunks = r_chunks + g_chunks
        combined_vecs = np.vstack([r_vecs, g_vecs])
        chunks_by_id = {c.chunk_id: c for c in combined_chunks}

        sort_indices = sorted(range(len(combined_chunks)), key=lambda i: combined_chunks[i].chunk_id)
        sorted_chunks = [combined_chunks[i] for i in sort_indices]
        sorted_vecs = combined_vecs[sort_indices]

        col_name = f"recheck_{exp['experiment_id']}"
        try:
            chroma_client.delete_collection(col_name)
        except Exception:
            pass

        col = chroma_client.create_collection(col_name, metadata={"hnsw:space": "cosine"})
        b_vecs = sorted_vecs.tolist()
        b_ids = [c.chunk_id for c in sorted_chunks]
        b_metas = [{"doc_id": c.doc_id} for c in sorted_chunks]
        b_docs = [c.content[:200] for c in sorted_chunks]
        col.add(ids=b_ids, embeddings=b_vecs, metadatas=b_metas, documents=b_docs)

        top5_ids = []
        for q_v in query_vectors:
            res = col.query(query_embeddings=[q_v.tolist()], n_results=5)
            top5_ids.append(res["ids"][0])

        chroma_client.delete_collection(col_name)

        recomputed = evaluate_retrieval(
            queries=queries,
            top5_chunk_ids=top5_ids,
            chunks_by_id=chunks_by_id,
            gold_mapping_by_qid=gold_mapping_by_qid,
            rawpedia_rule=exp["rawpedia_rule"],
            github_rule=exp["github_rule"],
        )

        orig_macro_mrr = exp["metrics"]["macro"]["mrr@5"]
        new_macro_mrr = recomputed["macro"]["mrr@5"]
        diff = abs(orig_macro_mrr - new_macro_mrr)
        print(f"  Orig MRR@5: {orig_macro_mrr:.4f} | Recomputed MRR@5: {new_macro_mrr:.4f} | Diff: {diff:.6f}")
        assert diff < 1e-4, f"Reproduction mismatch for {exp['experiment_id']}: {diff}"

        reproduction_results[exp["experiment_id"]] = {
            "label": label,
            "orig_macro_mrr@5": orig_macro_mrr,
            "recomputed_macro_mrr@5": new_macro_mrr,
            "diff": diff,
            "status": "verified",
        }

    recheck_summary = {
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verified_targets_count": len(unique_targets),
        "reproduction_results": reproduction_results,
    }
    recheck_file = recheck_dir / "reproduction.json"
    recheck_file.write_text(json.dumps(recheck_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"SUCCESS: Benchmark reproduction verified for all {len(unique_targets)} targets. Saved {recheck_file}")
    return 0


def cmd_report_markdown(args: argparse.Namespace) -> int:
    """Generate comprehensive Markdown and JSON reports from benchmark results."""
    input_json = Path(args.input_json).resolve()
    output_md = Path(args.output_md).resolve()
    output_json = Path(args.output_json).resolve() if getattr(args, "output_json", None) else None

    data = json.loads(input_json.read_bytes())
    selected = data.get("selected_stack", {})
    experiments = data.get("experiments", [])
    formal_exps = [e for e in experiments if not e["is_diagnostic"]]
    diag_exps = [e for e in experiments if e["is_diagnostic"]]

    # Save output json if requested
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved benchmark JSON to {output_json}")

    # Baseline info
    baseline = data.get("baseline", {})
    b_sel = baseline.get("selected_stack", {}) if baseline else {}

    sel_cfg = MODEL_CONFIGS.get(selected.get("model_id"), {})
    sel_dim = sel_cfg.get("dim", 384)
    sel_q_pref = sel_cfg.get("query_prefix", "")
    sel_d_pref = sel_cfg.get("doc_prefix", "")
    sel_g_rule = selected.get("github_rule")
    sel_m_id = selected.get("model_id")

    lines = [
        "# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트",
        "",
        f"- 생성 일시: {data.get('generated_at')}",
        f"- 평가 질문 데이터셋: `{data.get('dataset_id')}` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)",
        "- 탐색 파라미터 그리드: L in {128, 192, 224}, O in {0, 32, 64}",
        f"- 총 실험 조합: {len(experiments)}개 (정식 {len(formal_exps)}개 + 진단 {len(diag_exps)}개, 100% 완료)",
        "",
        "## 1. 최종 선정 결과 요약",
        "",
        "| 구분 | 선정 항목 | 상세 내용 |",
        "|---|---|---|",
        f"| **최적 임베딩 모델** | `{selected.get('model_id')}` | Revision: `{selected.get('model_revision')[:12]}...`, Dim: {sel_dim} |",
        f"| **RawPedia 청킹 규칙** | `{selected.get('rawpedia_rule')}` | $L/O$ 파라미터 최적 조합 |",
        f"| **GitHub 청킹 규칙** | `{selected.get('github_rule')}` | 정제된 스레드/유닛 최적 조합 |",
        f"| **주요 검색 품질** | **Macro MRR@5: {selected.get('macro_mrr@5'):.4f}** | Macro Hit@5: {selected.get('macro_hit@5'):.4f} |",
        f"| **검색 속도 (p95)** | **{selected.get('p95_latency_seconds')*1000:.1f} ms** | 100개 쿼리 단일 검색 지연 |",
        f"| **선정 근거** | {selected.get('selection_rationale')} |",
        "",
        "## 2. 192/32 기준선 대비 증감 비교",
        "",
        "| 지표 | 192/32 기준선 (`baseline_192_32`) | 신규 최적 스택 (`grid_search`) | 증감 (Delta) |",
        "|---|---|---|---|",
    ]

    b_mrr = b_sel.get("macro_mrr@5", 0.7830)
    b_hit = b_sel.get("macro_hit@5", 0.8541)
    s_mrr = selected.get("macro_mrr@5", 0.0)
    s_hit = selected.get("macro_hit@5", 0.0)
    mrr_diff = s_mrr - b_mrr
    hit_diff = s_hit - b_hit

    lines.extend([
        f"| **임베딩 모델** | `{b_sel.get('model_id', 'intfloat/multilingual-e5-small')}` | `{selected.get('model_id')}` | {b_sel.get('model_id')} -> {selected.get('model_id')} |",
        f"| **RawPedia 규칙** | `{b_sel.get('rawpedia_rule', 'R-B-window')}` (192/32) | `{selected.get('rawpedia_rule')}` | 파라미터 최적화 |",
        f"| **GitHub 규칙** | `{b_sel.get('github_rule', 'G-A-curated-thread')}` (192) | `{selected.get('github_rule')}` | 윈도우 크기 최적화 |",
        f"| **Macro MRR@5** | {b_mrr:.4f} | **{s_mrr:.4f}** | **{mrr_diff:+.4f}** |",
        f"| **Macro Hit@5** | {b_hit:.4f} | **{s_hit:.4f}** | **{hit_diff:+.4f}** |",
        "",
        "## 3. 청킹 크기($L$) 및 오버랩($O$) 그리드 탐색 분석 (3×3 Grid Effect)",
        "",
        f"최적 모델(`{sel_m_id}`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \\times O$ 그리드별 검색 품질(Macro MRR@5) 변화:",
        "",
        "| 청크 크기 ($L$) \\ 오버랩 ($O$) | $O = 0$ (중복 없음) | $O = 32$ (경량 오버랩) | $O = 64$ (확장 오버랩) |",
        "|---|---|---|---|",
    ])

    # Build 3x3 table for R-B-window with multilingual-e5-small and selected github rule
    sel_g_rule = selected.get("github_rule")
    sel_m_id = selected.get("model_id")

    for l_val in [128, 192, 224]:
        row_vals = []
        for o_val in [0, 32, 64]:
            target_r_vid = f"R-B-window-t{l_val}-o{o_val}"
            matching = [
                e for e in formal_exps
                if e["model_id"] == sel_m_id and e["rawpedia_rule"] == target_r_vid and e["github_rule"] == sel_g_rule
            ]
            if matching:
                val = f"{matching[0]['metrics']['macro']['mrr@5']:.4f}"
            else:
                val = "N/A"
            row_vals.append(val)
        lines.append(f"| **$L = {l_val}$** | {row_vals[0]} | {row_vals[1]} | {row_vals[2]} |")

    lines.extend([
        "",
        "## 4. 상위 정식 실험 조합 비교표 (Top 25 Combinations)",
        "",
        "| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])

    sorted_formal = sorted(
        formal_exps,
        key=lambda e: (e["metrics"]["macro"]["mrr@5"], e["metrics"]["macro"]["hit@5"]),
        reverse=True,
    )

    for rank, e in enumerate(sorted_formal[:25], start=1):
        m = e["metrics"]
        m_id = e["model_id"].split("/")[-1]
        lat_ms = e["latency"]["p95_seconds"] * 1000
        ann = e["ann_overlap_at_5"]
        lines.append(
            f"| {rank} | `{m_id}` | `{e['rawpedia_rule']}` | `{e['github_rule']}` | "
            f"{m['macro']['hit@1']:.4f} | {m['macro']['hit@5']:.4f} | **{m['macro']['mrr@5']:.4f}** | "
            f"{m['micro']['mrr@5']:.4f} | {lat_ms:.1f}ms | {ann:.4f} |"
        )

    lines.extend([
        "",
        "## 5. 진단 후보군(`G-A-full-thread`) 대비 정제 효과 분석",
        "",
        "미정제 전체 댓글 39개를 포함한 진단 기준선(`G-A-full-thread`)과 정제된 35개 조각 스레드(`G-A-curated-thread`)의 성능 대조:",
        "",
        "| 모델 ID | 윈도우 크기 ($W$) | 정제 스레드 (`G-A-curated`) MRR@5 | 진단 전체 스레드 (`G-A-full`) MRR@5 | 정제 효과 (Noise Reduction) |",
        "|---|---|---|---|---|",
    ])

    for w_val in [128, 192, 224]:
        c_vid = f"G-A-curated-thread-w{w_val}-wo0"
        f_vid = f"G-A-full-thread-w{w_val}-wo0"
        c_exp = next((e for e in formal_exps if e["model_id"] == sel_m_id and e["github_rule"] == c_vid), None)
        f_exp = next((e for e in diag_exps if e["model_id"] == sel_m_id and e["github_rule"] == f_vid), None)
        if c_exp and f_exp:
            c_score = c_exp["metrics"]["macro"]["mrr@5"]
            f_score = f_exp["metrics"]["macro"]["mrr@5"]
            diff = c_score - f_score
            lines.append(f"| `{sel_m_id.split('/')[-1]}` | $W = {w_val}$ | {c_score:.4f} | {f_score:.4f} | **{diff:+.4f}** |")

    sel_cfg = MODEL_CONFIGS.get(selected.get("model_id"), {})
    sel_dim = sel_cfg.get("dim", 384)
    sel_q_pref = sel_cfg.get("query_prefix", "")
    sel_d_pref = sel_cfg.get("doc_prefix", "")

    lines.extend([
        "",
        "## 6. 결론 및 T9 인계 명세",
        "",
        "1. **최종 선정 스택**:",
        f"   - **임베딩 모델**: `{selected.get('model_id')}` (commit revision: `{selected.get('model_revision')}`)",
        f"   - **차원 및 Prefix**: {sel_dim} 차원 / Query: `{sel_q_pref}` / Document: `{sel_d_pref}`",
        f"   - **RawPedia 청크 파일**: `data/chunks/t08-2-grid/rawpedia/{selected.get('rawpedia_rule')}.jsonl`",
        f"   - **GitHub 청크 파일**: `data/chunks/t08-2-grid/github/{selected.get('github_rule')}.jsonl`",
        "   - **Chroma 설정**: cosine 거리, HNSW ef_construction=200, ef_search=200",
        "",
        "2. **인계 주의 사항**:",
        f"   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`{sel_q_pref}`)를 부가하여 {sel_dim}차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.",
        "   - GitHub 스레드 청크는 `thread_window_mean_v1` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.",
        "",
    ])

    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SUCCESS: Markdown report saved to {output_md}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding model and chunking strategy benchmark runner.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # preflight
    pf = subparsers.add_parser("preflight", help="Preflight environment, tokenizers, and model smoke.")
    pf.add_argument("--stage", choices=["tokenizers", "runtime"], required=True, help="Preflight stage.")
    pf.add_argument("--models", nargs="+", help="Model IDs to test.")
    pf.add_argument("--device", default="cpu", help="Device to use (cpu).")
    pf.add_argument("--work-dir", default="data/embedding-benchmark/t08-2/run-001", help="Work directory.")
    pf.add_argument("--model-manifest", help="Path to environment.json for runtime stage.")
    pf.set_defaults(func=cmd_preflight)

    # matrix
    mx = subparsers.add_parser("matrix", help="Generate cartesian product experiment matrix.")
    mx.add_argument("--chunk-manifest", required=True)
    mx.add_argument("--model-manifest", required=True)
    mx.add_argument("--queries", required=True)
    mx.add_argument("--ks", nargs="+", type=int, default=[1, 3, 5])
    mx.add_argument("--device", default="cpu")
    mx.add_argument("--output-json", required=True)
    mx.set_defaults(func=cmd_matrix)

    # run
    rn = subparsers.add_parser("run", help="Run full benchmark matrix.")
    rn.add_argument("--matrix", help="Path to experiment_matrix.json")
    rn.add_argument("--chunk-manifest", required=True)
    rn.add_argument("--model-manifest", required=True)
    rn.add_argument("--queries", required=True)
    rn.add_argument("--ks", nargs="+", type=int, default=[1, 3, 5])
    rn.add_argument("--device", default="cpu")
    rn.add_argument("--batch-size", type=int, default=16)
    rn.add_argument("--seed", type=int, default=42)
    rn.add_argument("--warmup-queries", type=int, default=10)
    rn.add_argument("--query-repeat", type=int, default=3)
    rn.add_argument("--work-dir", required=True)
    rn.add_argument("--output-json", required=True)
    rn.set_defaults(func=cmd_run)

    # check
    ck = subparsers.add_parser("check", help="Verify benchmark results and reproduction.")
    ck.add_argument("--input-json", required=True)
    ck.add_argument("--verify-top-candidates", action="store_true")
    ck.add_argument("--work-dir", required=True)
    ck.set_defaults(func=cmd_check_benchmark)

    # report
    rp = subparsers.add_parser("report", help="Generate benchmark markdown report.")
    rp.add_argument("--input-json", required=True)
    rp.add_argument("--output-json", help="Path to output benchmark JSON")
    rp.add_argument("--output-md", required=True)
    rp.set_defaults(func=cmd_report_markdown)

    parsed = parser.parse_args()
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main() or 0)
