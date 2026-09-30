#!/usr/bin/env python3
"""Benchmark runner and evaluation harness for embedding models and chunking strategies.

Follows docs/T08_2_execution_plan.md specifications for preflight, matrix, run, check, and report.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import inspect
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
    GUARD_GROUP_CONTRACTS,
    Chunk,
    SourceSegment,
    calculate_evidence_chunk_coverage,
    calculate_evidence_chunks_union_coverage,
    canonical_json_bytes,
    get_evidence_char_range,
    sha256_bytes,
    sha256_str,
)
from src.artagent.benchmark_validation import aggregate_query_results, select_stack

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

    if getattr(args, "rawpedia_variant_ids", None):
        if len(args.rawpedia_variant_ids) != len(set(args.rawpedia_variant_ids)):
            raise ValueError(f"Duplicate rawpedia variant IDs in filter: {args.rawpedia_variant_ids}")
        selected_rp = set(args.rawpedia_variant_ids)
        rawpedia_variants = [v for v in rawpedia_variants if v["rule_id"] in selected_rp]
        if not rawpedia_variants:
            raise ValueError(f"No rawpedia variants match --rawpedia-variant-ids: {args.rawpedia_variant_ids}")

    if getattr(args, "model_ids", None):
        if len(args.model_ids) != len(set(args.model_ids)):
            raise ValueError(f"Duplicate model IDs in filter: {args.model_ids}")
        selected_m = set(args.model_ids)
        models = [m for m in models if m in selected_m]
        if not models:
            raise ValueError(f"No models match --model-ids: {args.model_ids}")

    # Guard group compatibility check
    guard_group = getattr(args, "guard_group", None) or chunk_manifest.get("guard_group")
    if guard_group and guard_group in GUARD_GROUP_CONTRACTS:
        allowed_models = GUARD_GROUP_CONTRACTS[guard_group]["allowed_models"]
        for m_id in models:
            if m_id not in allowed_models:
                raise ValueError(
                    f"Model '{m_id}' is not allowed for guard group '{guard_group}' (allowed: {allowed_models})"
                )

    if getattr(args, "github_variant_ids", None):
        if len(args.github_variant_ids) != len(set(args.github_variant_ids)):
            raise ValueError(f"Duplicate github variant IDs in filter: {args.github_variant_ids}")
        selected_gh = set(args.github_variant_ids)
        all_github_variants = [v for v in all_github_variants if v["rule_id"] in selected_gh]
        github_formal_variants = [v for v in github_formal_variants if v["rule_id"] in selected_gh]
        github_diagnostic_variants = [v for v in github_diagnostic_variants if v["rule_id"] in selected_gh]
        if not all_github_variants:
            raise ValueError(f"No github variants match --github-variant-ids: {args.github_variant_ids}")

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
                r_policy = r_var.get("embedding_policy", "direct")
                g_policy = g_var.get("embedding_policy", "direct")
                stage_id = "boundary-native" if r_policy == "direct_native_v3" else ("boundary-pooled" if r_policy == "chunk_window_mean_v2" else "stage-n")
                guard_group = getattr(args, "guard_group", None) or chunk_manifest.get("guard_group", "bge-512" if "bge" in m_id else ("e5-512" if "e5" in m_id else "pooled-common-256"))
                exp_slug = f"{r_id}__{g_id}__{m_id}__{rev[:8]}__{r_policy}__{g_policy}__{guard_group}__{args.device}"
                exp_id = f"exp_{sha256_str(exp_slug)[:12]}"

                exp_entry = {
                    "experiment_id": exp_id,
                    "stage_id": stage_id,
                    "guard_group": guard_group,
                    "is_diagnostic": is_diagnostic,
                    "rawpedia_variant_id": r_id,
                    "rawpedia_variant": r_var,
                    "rawpedia_file_path": r_var.get("file_path"),
                    "rawpedia_policy": r_policy,
                    "github_variant_id": g_id,
                    "github_variant": g_var,
                    "github_file_path": g_var.get("file_path"),
                    "github_policy": g_policy,
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
    trace_callback: Optional[Callable] = None,
) -> np.ndarray:
    """Encode a list of chunks, applying window pooling or direct native encoding as specified by policy."""
    vectors = np.zeros((len(chunks), encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    max_len = getattr(encoder, "max_seq_length", 512)
    direct_items: List[Tuple[int, str]] = []

    def trace(chunk, texts, weights):
        if trace_callback is not None:
            trace_callback({"chunk_id": chunk.chunk_id,
                "policy": chunk.metadata.get("embedding_policy", "direct"),
                "source_segments": chunk.metadata.get("source_segments", []),
                "windows": [{"input": text, "input_sha256": sha256_str(text),
                    "input_tokens": len(encoder.tokenizer.encode(text, add_special_tokens=True)),
                    "body_token_weight": int(weight), "header_token_weight": 0}
                    for text, weight in zip(texts, weights)]})

    for idx, c in enumerate(chunks):
        policy = c.metadata.get("embedding_policy", "direct")

        # Build header (truncated to 32 reference tokens if present)
        p_title = c.metadata.get("page_title") or c.metadata.get("title", "")
        s_title = c.section_title
        if p_title and s_title and p_title != s_title:
            header = f"{p_title}\n{s_title}"
        else:
            header = s_title or p_title or ""
        if header and ref_tokenizer is not None:
            enc_h = ref_tokenizer(header, return_offsets_mapping=True, add_special_tokens=False)
            offsets_h = enc_h["offset_mapping"]
            if len(offsets_h) > 32:
                header = header[:offsets_h[31][1]].strip()

        if policy in ("thread_window_mean_v1", "thread_window_mean_v2"):
            # Isolated legacy implementation from 7b4dbe8f7
            segments = c.metadata.get("source_segments", [])
            w_val = c.metadata.get("encoder_window_tokens") or 224
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
                        txt = f"{header}\n{seg_slice}".strip() if header else seg_slice
                        window_texts.append(f"{doc_prefix}{txt}")
                        window_weights.append(n_tok)
                    else:
                        for i in range(0, n_tok, w_val):
                            sub_offsets = offsets[i : i + w_val]
                            sub_st = sub_offsets[0][0]
                            sub_ed = sub_offsets[-1][1]
                            sub_txt = seg_slice[sub_st:sub_ed]
                            if sub_txt.strip():
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                window_texts.append(f"{doc_prefix}{txt}")
                                window_weights.append(len(sub_offsets))
                else:
                    txt = f"{header}\n{seg_slice}".strip() if header else seg_slice
                    window_texts.append(f"{doc_prefix}{txt}")
                    window_weights.append(max(1, len(re.sub(r"\s", "", seg_slice))))

            if not window_texts:
                txt = f"{header}\n{c.content}".strip() if header else c.content
                window_texts = [f"{doc_prefix}{txt}"]
                window_weights = [1]

            # Enforce length guard for each window, sub-splitting if necessary
            final_window_texts = []
            final_window_weights = []
            for w_t, w_w in zip(window_texts, window_weights):
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len <= max_len:
                    final_window_texts.append(w_t)
                    final_window_weights.append(w_w)
                else:
                    core_t = w_t[len(doc_prefix):] if doc_prefix and w_t.startswith(doc_prefix) else w_t
                    if ref_tokenizer is not None:
                        core_enc = ref_tokenizer(core_t, return_offsets_mapping=True, add_special_tokens=False)
                        core_offsets = core_enc["offset_mapping"]
                        sub_step = 160
                        for si in range(0, len(core_offsets), sub_step):
                            so = core_offsets[si : si + sub_step]
                            sub_txt = core_t[so[0][0] : so[-1][1]]
                            if sub_txt.strip():
                                final_window_texts.append(f"{doc_prefix}{sub_txt}")
                                final_window_weights.append(len(so))
                    else:
                        mid = len(core_t) // 2
                        p1, p2 = core_t[:mid], core_t[mid:]
                        final_window_texts.append(f"{doc_prefix}{p1}")
                        final_window_weights.append(max(1, w_w // 2))
                        final_window_texts.append(f"{doc_prefix}{p2}")
                        final_window_weights.append(max(1, w_w - (w_w // 2)))

            window_texts = final_window_texts
            window_weights = final_window_weights

            for w_t in window_texts:
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len > max_len:
                    raise ValueError(f"Thread window exceeds max_seq_length ({tok_len} > {max_len}) for model {model_id}")

            trace(c, window_texts, window_weights)
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
            vectors[idx] = weighted_mean

        elif policy == "thread_window_mean_v3":
            # Thread chunks encode using internal window splitting across segments with zero header weight
            segments = c.metadata.get("source_segments", [])
            w_val = c.metadata.get("encoder_window_tokens") or 224
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
                        txt = f"{header}\n{seg_slice}".strip() if header else seg_slice
                        window_texts.append((f"{doc_prefix}{txt}", seg_slice, n_tok))
                    else:
                        for i in range(0, n_tok, w_val):
                            sub_offsets = offsets[i : i + w_val]
                            sub_st = sub_offsets[0][0]
                            sub_ed = sub_offsets[-1][1]
                            sub_txt = seg_slice[sub_st:sub_ed]
                            if sub_txt.strip():
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                window_texts.append((f"{doc_prefix}{txt}", sub_txt, len(sub_offsets)))
                else:
                    txt = f"{header}\n{seg_slice}".strip() if header else seg_slice
                    window_texts.append((f"{doc_prefix}{txt}", seg_slice, max(1, len(re.sub(r"\s", "", seg_slice)))))

            if not window_texts:
                txt = f"{header}\n{c.content}".strip() if header else c.content
                window_texts = [(f"{doc_prefix}{txt}", c.content, 1)]

            # Enforce length guard for each window, sub-splitting on body only to preserve zero header weight
            final_window_texts = []
            final_window_weights = []
            for w_t, body_slice, w_w in window_texts:
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len <= max_len:
                    final_window_texts.append(w_t)
                    final_window_weights.append(w_w)
                else:
                    if ref_tokenizer is not None:
                        core_enc = ref_tokenizer(body_slice, return_offsets_mapping=True, add_special_tokens=False)
                        core_offsets = core_enc["offset_mapping"]
                        header_txt = f"{doc_prefix}{header}\n" if header else f"{doc_prefix}"
                        header_tok_len = len(encoder.tokenizer.encode(header_txt, add_special_tokens=True))
                        avail_tokens = max(16, max_len - header_tok_len - 5)
                        sub_step = min(160, avail_tokens)
                        st = 0
                        while st < len(core_offsets):
                            step = sub_step
                            while step > 1:
                                so = core_offsets[st : st + step]
                                sub_txt = body_slice[so[0][0] : so[-1][1]]
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                cand_w_t = f"{doc_prefix}{txt}"
                                if len(encoder.tokenizer.encode(cand_w_t, add_special_tokens=True)) <= max_len:
                                    break
                                step = max(1, step // 2)
                            so = core_offsets[st : st + step]
                            sub_txt = body_slice[so[0][0] : so[-1][1]]
                            if sub_txt.strip():
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                final_window_texts.append(f"{doc_prefix}{txt}")
                                final_window_weights.append(len(so))
                            st += step
                    else:
                        mid = len(body_slice) // 2
                        p1, p2 = body_slice[:mid], body_slice[mid:]
                        txt1 = f"{header}\n{p1}".strip() if header else p1
                        txt2 = f"{header}\n{p2}".strip() if header else p2
                        final_window_texts.append(f"{doc_prefix}{txt1}")
                        final_window_weights.append(max(1, w_w // 2))
                        final_window_texts.append(f"{doc_prefix}{txt2}")
                        final_window_weights.append(max(1, w_w - (w_w // 2)))

            window_texts = final_window_texts
            window_weights = final_window_weights

            for w_t in window_texts:
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len > max_len:
                    raise ValueError(f"Thread window exceeds max_seq_length ({tok_len} > {max_len}) for model {model_id}")

            trace(c, window_texts, window_weights)
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
            vectors[idx] = weighted_mean

        elif policy in ("chunk_window_mean_v1", "chunk_window_mean_v2"):
            # Pooled physical chunks: split content into windows of encoder_window_tokens (default 224)
            w_val = c.metadata.get("encoder_window_tokens") or 224
            window_texts = []

            if ref_tokenizer is not None:
                enc = ref_tokenizer(c.content, return_offsets_mapping=True, add_special_tokens=False)
                offsets = enc["offset_mapping"]
                n_tok = len(offsets)
                if n_tok == 0:
                    txt = f"{header}\n{c.content}".strip() if header else c.content
                    window_texts.append((f"{doc_prefix}{txt}", c.content, 1))
                elif n_tok <= w_val:
                    txt = f"{header}\n{c.content}".strip() if header else c.content
                    window_texts.append((f"{doc_prefix}{txt}", c.content, n_tok))
                else:
                    for i in range(0, n_tok, w_val):
                        sub_offsets = offsets[i : i + w_val]
                        sub_st = sub_offsets[0][0]
                        sub_ed = sub_offsets[-1][1]
                        sub_txt = c.content[sub_st:sub_ed]
                        if sub_txt.strip():
                            txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                            window_texts.append((f"{doc_prefix}{txt}", sub_txt, len(sub_offsets)))
            else:
                txt = f"{header}\n{c.content}".strip() if header else c.content
                window_texts.append((f"{doc_prefix}{txt}", c.content, 1))

            if not window_texts:
                txt = f"{header}\n{c.content}".strip() if header else c.content
                window_texts.append((f"{doc_prefix}{txt}", c.content, 1))

            # Enforce length guard for each window, sub-splitting on body only
            final_window_texts = []
            final_window_weights = []
            for w_t, body_slice, w_w in window_texts:
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len <= max_len:
                    final_window_texts.append(w_t)
                    final_window_weights.append(w_w)
                else:
                    if ref_tokenizer is not None:
                        core_enc = ref_tokenizer(body_slice, return_offsets_mapping=True, add_special_tokens=False)
                        core_offsets = core_enc["offset_mapping"]
                        header_txt = f"{doc_prefix}{header}\n" if header else f"{doc_prefix}"
                        header_tok_len = len(encoder.tokenizer.encode(header_txt, add_special_tokens=True))
                        avail_tokens = max(16, max_len - header_tok_len - 5)
                        sub_step = min(max(50, w_val // 2), avail_tokens)
                        st = 0
                        while st < len(core_offsets):
                            step = sub_step
                            while step > 1:
                                so = core_offsets[st : st + step]
                                sub_txt = body_slice[so[0][0] : so[-1][1]]
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                cand_w_t = f"{doc_prefix}{txt}"
                                if len(encoder.tokenizer.encode(cand_w_t, add_special_tokens=True)) <= max_len:
                                    break
                                step = max(1, step // 2)
                            so = core_offsets[st : st + step]
                            sub_txt = body_slice[so[0][0] : so[-1][1]]
                            if sub_txt.strip():
                                txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                                final_window_texts.append(f"{doc_prefix}{txt}")
                                final_window_weights.append(len(so))
                            st += step
                    else:
                        mid = len(body_slice) // 2
                        p1, p2 = body_slice[:mid], body_slice[mid:]
                        txt1 = f"{header}\n{p1}".strip() if header else p1
                        txt2 = f"{header}\n{p2}".strip() if header else p2
                        final_window_texts.append(f"{doc_prefix}{txt1}")
                        final_window_weights.append(max(1, w_w // 2))
                        final_window_texts.append(f"{doc_prefix}{txt2}")
                        final_window_weights.append(max(1, w_w - (w_w // 2)))

            window_texts = final_window_texts
            window_weights = final_window_weights

            for w_t in window_texts:
                tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
                if tok_len > max_len:
                    raise ValueError(f"Pooled chunk window exceeds max_seq_length ({tok_len} > {max_len}) for model {model_id}")

            trace(c, window_texts, window_weights)
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
            vectors[idx] = weighted_mean

        else:
            # direct / direct_native_v2 / direct_native_v3
            full_input = f"{header}\n{c.content}".strip() if header else c.content
            cand_text = f"{doc_prefix}{full_input}"
            # Check length guard
            tok_len = len(encoder.tokenizer.encode(cand_text, add_special_tokens=True))
            if tok_len > max_len:
                raise ValueError(
                    f"Direct chunk exceeds max_seq_length ({tok_len} > {max_len}) for model {model_id} in {c.chunk_id}"
                )
            trace(c, [cand_text], [len(ref_tokenizer.encode(c.content, add_special_tokens=False)) if ref_tokenizer is not None else 1])
            direct_items.append((idx, cand_text))

    if direct_items:
        d_idxs = [item[0] for item in direct_items]
        d_texts = [item[1] for item in direct_items]
        d_vecs = encoder.encode(
            d_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        vectors[d_idxs] = d_vecs

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
    policy = chunks[0].metadata.get("embedding_policy", "direct") if chunks else "direct"
    rev = minfo.get("revision", "rev")
    content_hash = sha256_bytes(canonical_json_bytes({
        "chunks": [c.to_dict() for c in chunks], "model_id": model_id, "model": minfo,
        "encoder_code": sha256_str(inspect.getsource(encode_chunk_list)),
        "dtype": "float32", "normalize": True,
    }))
    model_slug = model_id.replace("/", "_")
    cache_key = f"{rule_name}__{model_slug}__{rev[:8]}__{policy}__{content_hash[:16]}"
    npy_path = cache_dir / f"{cache_key}.npy"

    if npy_path.is_file():
        vecs = np.load(npy_path)
        if vecs.shape == (len(chunks), minfo["hidden_size"]):
            return vecs

    print(f"Encoding {len(chunks)} chunks for {rule_name} with {model_id} (policy: {policy})...")
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


def query_collection_deterministic(
    col: Any,
    encoder: Any,
    query_texts: List[str],
    n_results: int = 10,
    k: int = 5,
    measure_latency: bool = False,
    chunks_by_id: Optional[Dict[str, Chunk]] = None,
    sort_candidates: bool = True,
    legacy_query_vectors: Optional[np.ndarray] = None,
) -> Tuple[List[List[str]], List[List[float]], List[float], List[Dict[str, Any]]]:
    """Execute queries against Chroma collection with deterministic tie-breaking.

    Tie-breaking rule: candidates are sorted by (round(distance, 6), chunk_id).
    Returns:
        top_k_ids: List of top-k chunk IDs for each query
        top_k_distances: List of top-k cosine distances for each query
        latencies: List of measured latency in seconds (if measure_latency=True)
        diagnostics: List of diagnostic dicts for each query (candidates near rank k, tie flags)
    """
    top_k_ids: List[List[str]] = []
    top_k_distances: List[List[float]] = []
    latencies: List[float] = []
    diagnostics: List[Dict[str, Any]] = []

    for q_idx, q_text in enumerate(query_texts):
        t0 = time.perf_counter()
        q_emb = encoder.encode([q_text], normalize_embeddings=True, show_progress_bar=False)[0]
        if legacy_query_vectors is not None:
            q_emb = legacy_query_vectors[q_idx]
        res = col.query(
            query_embeddings=[q_emb.tolist()],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        raw_ids = res["ids"][0]
        raw_dists = res["distances"][0]
        raw_docs = res["documents"][0]
        raw_metas = res["metadatas"][0]

        # Deterministic sorting by (round(distance, 6), chunk_id)
        candidates = list(zip(raw_ids, raw_dists, raw_docs, raw_metas))
        if sort_candidates:
            candidates.sort(key=lambda c: (round(float(c[1]), 6), str(c[0])))
        top_cand = candidates[:k]
        c_ids = [c[0] for c in top_cand]
        c_dists = [float(c[1]) for c in top_cand]
        top_k_ids.append(c_ids)
        top_k_distances.append(c_dists)

        # Record diagnostics around rank k boundary
        k_dist = c_dists[-1] if c_dists else 0.0
        near_boundary = [
            {"chunk_id": c[0], "distance": float(c[1])}
            for c in candidates
            if abs(float(c[1]) - k_dist) < 1e-4
        ]
        materialized = []
        if chunks_by_id is not None:
            for cid, dist, document, metadata in top_cand:
                chunk = chunks_by_id[cid]
                if document != chunk.content:
                    raise ValueError(f"Chroma document roundtrip mismatch: {cid}")
                materialized.append({"chunk_id": cid, "distance": float(dist),
                    "cosine_similarity": 1.0 - float(dist), "source_type": chunk.source_type,
                    "doc_id": chunk.doc_id, "content_sha256": sha256_str(document),
                    "source_segments": chunk.metadata.get("source_segments", [])})
        diagnostics.append({
            "top5_ids": c_ids,
            "top5_distances": c_dists,
            "near_boundary_candidates": near_boundary,
            "tie_at_boundary": len(near_boundary) > 1,
            "top5": materialized,
            "query_vector_sha256": sha256_bytes(q_emb.astype(np.float32).tobytes()),
            "_query_vector": q_emb,
        })
        if measure_latency:
            latencies.append(time.perf_counter() - t0)

    return top_k_ids, top_k_distances, latencies, diagnostics


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
    context_budgets: Optional[List[int]] = None,
    ref_tokenizer: Any = None,
) -> Dict[str, Any]:
    """Calculate retrieval metrics (Hit@k, MRR@k, All@k, FullEvidence@k, etc.) and context budgets."""
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
        support_evs = [e for e in q.get("evidence", []) if e["role"] == ("counter" if is_neg else "support")]
        evidence_coverage = [{"evidence_id": ev.get("evidence_id", str(i)), "role": ev["role"],
            "source_path": ev["source_path"],
            "per_rank": [calculate_evidence_chunk_coverage(ev, c, (ev.get("_char_start"), ev.get("_char_end"))) for c in top5_chunks],
            "union_at_k": {k: calculate_evidence_chunks_union_coverage(ev, top5_chunks[:k], (ev.get("_char_start"), ev.get("_char_end"))) for k in ks}}
            for i, ev in enumerate(support_evs)]
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

        # Context budget packing and evaluation
        budget_hit = {}
        budget_full_ev = {}
        packing = {}
        if context_budgets and ref_tokenizer is not None:
            for B in context_budgets:
                packed_chunks = []
                cur_tokens = 0
                for c in top5_chunks:
                    ser_text = f"{c.section_title}\n{c.content}" if c.section_title else c.content
                    c_tokens = c.metadata.get("_benchmark_context_tokens")
                    if c_tokens is None:
                        c_tokens = len(ref_tokenizer(ser_text, add_special_tokens=False)["input_ids"])
                        c.metadata["_benchmark_context_tokens"] = c_tokens
                    if cur_tokens + c_tokens <= B:
                        packed_chunks.append(c)
                        cur_tokens += c_tokens

                b_hit = 0.0
                for c in packed_chunks:
                    for ev in q.get("evidence", []):
                        cov = calculate_evidence_chunk_coverage(
                            ev, c, (ev.get("_char_start"), ev.get("_char_end"))
                        )
                        if cov >= relevance_threshold:
                            b_hit = 1.0
                            break
                    if b_hit > 0.0:
                        break
                budget_hit[B] = b_hit

                b_fe = 1.0
                for ev in support_evs:
                    cov = calculate_evidence_chunks_union_coverage(
                        ev, packed_chunks, (ev.get("_char_start"), ev.get("_char_end"))
                    )
                    if cov < 0.999:
                        b_fe = 0.0
                        break
                budget_full_ev[B] = b_fe
                packing[B] = {"packed_ids": [c.chunk_id for c in packed_chunks], "consumed_tokens": cur_tokens,
                    "skipped_ids": [c.chunk_id for c in top5_chunks if c not in packed_chunks],
                    "evidence_coverage": [calculate_evidence_chunks_union_coverage(ev, packed_chunks,
                        (ev.get("_char_start"), ev.get("_char_end"))) for ev in support_evs]}

        q_res = {
            "query_id": qid,
            "source_type": q_src,
            "difficulty": q["difficulty"],
            "first_rel_rank": first_rel_rank,
            "hit": hit,
            "rr": rr,
            "all": all_k,
            "full_evidence": full_ev_k,
            "budget_hit": budget_hit,
            "budget_full_evidence": budget_full_ev,
            "top5_ids": top5_ids,
            "evidence_coverage": evidence_coverage,
            "packing": packing,
        }

        if is_neg:
            negative_results.append(q_res)
        elif q_src == "rawpedia":
            rawpedia_results.append(q_res)
        else:
            github_results.append(q_res)

    return aggregate_query_results(rawpedia_results + github_results + negative_results,
        ks=ks, context_budgets=context_budgets or ())


# =========================================================================
# Main Run Command: Cartesian Product Matrix Execution
# =========================================================================

def cmd_run(args: argparse.Namespace) -> int:
    """Execute a fingerprinted matrix, persisting every query/repeat observation."""
    from scripts.verify_embedding_benchmark import run_matrix
    return run_matrix(args)



def cmd_check_benchmark(args: argparse.Namespace) -> int:
    """Reaggregate all logs and independently reproduce mandatory candidates."""
    from scripts.verify_embedding_benchmark import check_report
    return check_report(args)



def cmd_decide_extension(args: argparse.Namespace) -> int:
    """Evaluate trigger conditions for large chunk extension (§13.4 or §14.4)."""
    stage = getattr(args, "stage", "stage-n")
    inputs = [Path(p).resolve() for p in args.inputs]
    output_json_path = Path(args.output_json).resolve()

    all_experiments = []
    for in_path in inputs:
        if not in_path.is_file():
            print(f"ERROR: Input results file missing: {in_path}", file=sys.stderr)
            return 1
        data = json.loads(in_path.read_bytes())
        all_experiments.extend(data.get("experiments", []))

    formal_exps = [e for e in all_experiments if not e.get("is_diagnostic", False)]
    if not formal_exps:
        print("ERROR: No formal experiments found in inputs", file=sys.stderr)
        return 1

    # Group formal experiments by model_id
    exps_by_model: Dict[str, List[Dict[str, Any]]] = {}
    for e in formal_exps:
        exps_by_model.setdefault(e["model_id"], []).append(e)

    per_model_eval: Dict[str, Any] = {}
    overall_trigger = False

    if stage == "boundary-pooled":
        for m_id, m_exps in exps_by_model.items():
            sorted_m = sorted(
                m_exps,
                key=lambda e: (
                    e["metrics"]["macro"]["mrr@5"],
                    e["metrics"]["macro"]["hit@5"],
                    e["metrics"]["macro"]["full_evidence@5"],
                    -e["latency"]["p95_seconds"],
                    -e["vector_bytes"],
                ),
                reverse=True,
            )
            top_cand = sorted_m[0]
            r_rule = top_cand["rawpedia_rule"]
            r_l_match = re.search(r"-t(\d+)-", r_rule)
            r_l = int(r_l_match.group(1)) if r_l_match else None

            top_is_2048 = (r_l == 2048)
            comp_1536_exp = None
            comp_1024_exp = None
            triggered_by_mrr = False
            triggered_by_budget = False
            mrr_gain_1536 = None
            mrr_gain_1024 = None

            if top_is_2048:
                rule_1536 = re.sub(r"-t2048-", "-t1536-", r_rule)
                rule_1024 = re.sub(r"-t2048-", "-t1024-", r_rule)
                comp_1536_list = [e for e in m_exps if e["rawpedia_rule"] == rule_1536 and e["github_rule"] == top_cand["github_rule"]]
                comp_1024_list = [e for e in m_exps if e["rawpedia_rule"] == rule_1024 and e["github_rule"] == top_cand["github_rule"]]
                if comp_1536_list and comp_1024_list:
                    comp_1536_exp = comp_1536_list[0]
                    comp_1024_exp = comp_1024_list[0]
                    mrr_2048 = top_cand["metrics"]["macro"]["mrr@5"]
                    mrr_1536 = comp_1536_exp["metrics"]["macro"]["mrr@5"]
                    mrr_1024 = comp_1024_exp["metrics"]["macro"]["mrr@5"]
                    mrr_gain_1536 = round(mrr_2048 - mrr_1536, 6)
                    mrr_gain_1024 = round(mrr_2048 - mrr_1024, 6)
                    if mrr_gain_1536 > 1e-9 and mrr_gain_1024 > 1e-9:
                        triggered_by_mrr = True

                    fe_2048 = top_cand["metrics"]["macro"].get("budget_4096_full_evidence@5", top_cand["metrics"]["macro"]["full_evidence@5"])
                    fe_1024 = comp_1024_exp["metrics"]["macro"].get("budget_4096_full_evidence@5", comp_1024_exp["metrics"]["macro"]["full_evidence@5"])
                    if fe_2048 >= fe_1024 - 1e-9:
                        triggered_by_budget = True

            model_trigger = top_is_2048 and triggered_by_mrr and triggered_by_budget
            if model_trigger:
                overall_trigger = True

            per_model_eval[m_id] = {
                "top_candidate_id": top_cand["experiment_id"],
                "top_rawpedia_rule": r_rule,
                "top_github_rule": top_cand["github_rule"],
                "top_l": r_l,
                "is_2048": top_is_2048,
                "top_macro_mrr@5": top_cand["metrics"]["macro"]["mrr@5"],
                "comp_1536_macro_mrr@5": comp_1536_exp["metrics"]["macro"]["mrr@5"] if comp_1536_exp else None,
                "comp_1024_macro_mrr@5": comp_1024_exp["metrics"]["macro"]["mrr@5"] if comp_1024_exp else None,
                "mrr_gain_over_1536": mrr_gain_1536,
                "mrr_gain_over_1024": mrr_gain_1024,
                "triggered_by_mrr": triggered_by_mrr,
                "triggered_by_budget": triggered_by_budget,
                "model_trigger": model_trigger,
                "notes": (
                    "L=2048 strictly outperformed 1536 and 1024 in Macro MRR@5 with B=4096 FullEvidence >= 1024."
                    if model_trigger
                    else "Peak was at <= 1536 tokens or 2048 did not improve over both 1536 and 1024."
                ),
            }

        decision_payload = {
            "schema_version": 1,
            "stage": "boundary-pooled",
            "decision_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "inputs": [str(p) for p in inputs],
            "models_evaluated": list(exps_by_model.keys()),
            "per_model_evaluation": per_model_eval,
            "trigger": overall_trigger,
            "status": "triggered" if overall_trigger else "not_triggered",
            "rationale": (
                "At least one model's best candidate is L=2048 strictly superior to 1536 and 1024 under B=4096 budget."
                if overall_trigger
                else "No model has L=2048 strictly outperforming 1536 and 1024 with maintained budget full evidence; conditional 4096 not triggered."
            ),
        }
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.write_text(json.dumps(decision_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved boundary extension decision to {output_json_path}")
        print(f"Trigger: {overall_trigger}")
        return 0

    for m_id, m_exps in exps_by_model.items():
        # Sort to find top formal candidate for this model
        sorted_m = sorted(
            m_exps,
            key=lambda e: (
                e["metrics"]["macro"]["mrr@5"],
                e["metrics"]["macro"]["hit@5"],
                e["metrics"]["macro"]["full_evidence@5"],
                -e["latency"]["p95_seconds"],
                -e["vector_bytes"],
            ),
            reverse=True,
        )
        top_cand = sorted_m[0]
        r_rule = top_cand["rawpedia_rule"]
        g_rule = top_cand["github_rule"]

        # Parse target tokens
        r_l_match = re.search(r"-t(\d+)-", r_rule)
        r_l = int(r_l_match.group(1)) if r_l_match else None

        g_is_physical_l = False
        g_l = None
        if "curated-unit" in g_rule:
            g_l_match = re.search(r"-t(\d+)-", g_rule)
            if g_l_match:
                g_l = int(g_l_match.group(1))
                g_is_physical_l = True
        elif "thread" in g_rule:
            g_w_match = re.search(r"-w(\d+)-", g_rule)
            if g_w_match:
                g_l = int(g_w_match.group(1))
                g_is_physical_l = False

        has_physical_448 = (r_l == 448) or (g_is_physical_l and g_l == 448)

        mrr_gain = None
        triggered_by_mrr = False
        comp_384_exp = None

        if has_physical_448:
            target_r_rule = re.sub(r"-t448-", "-t384-", r_rule) if r_l == 448 else r_rule
            target_g_rule = re.sub(r"-t448-", "-t384-", g_rule) if (g_is_physical_l and g_l == 448) else g_rule

            matching_384 = [
                e for e in m_exps
                if e["rawpedia_rule"] == target_r_rule and e["github_rule"] == target_g_rule
            ]
            if matching_384:
                comp_384_exp = matching_384[0]
                mrr_448 = top_cand["metrics"]["macro"]["mrr@5"]
                mrr_384 = comp_384_exp["metrics"]["macro"]["mrr@5"]
                mrr_gain = round(mrr_448 - mrr_384, 6)
                if mrr_gain > 1e-9:
                    triggered_by_mrr = True

        guard_saturation = False
        model_trigger = triggered_by_mrr or guard_saturation
        if model_trigger:
            overall_trigger = True

        per_model_eval[m_id] = {
            "top_formal_experiment_id": top_cand["experiment_id"],
            "top_rawpedia_rule": r_rule,
            "top_github_rule": g_rule,
            "rawpedia_target_tokens": r_l,
            "github_target_tokens": g_l,
            "github_is_physical_l": g_is_physical_l,
            "has_physical_448": has_physical_448,
            "top_macro_mrr@5": top_cand["metrics"]["macro"]["mrr@5"],
            "comp_384_macro_mrr@5": comp_384_exp["metrics"]["macro"]["mrr@5"] if comp_384_exp else None,
            "mrr_gain": mrr_gain,
            "triggered_by_mrr": triggered_by_mrr,
            "guard_saturation": guard_saturation,
            "model_trigger": model_trigger,
            "notes": (
                "Physical L=448 showed positive gain over 384."
                if triggered_by_mrr
                else (
                    "Internal window W=448 reached encoder context limit (not physical L trigger)."
                    if (not g_is_physical_l and g_l == 448 and r_l != 448)
                    else "Peak was at <= 384 tokens or no improvement over 384."
                )
            ),
        }

    decision_payload = {
        "schema_version": 1,
        "decision_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "inputs": [str(p) for p in inputs],
        "models_evaluated": list(exps_by_model.keys()),
        "per_model_evaluation": per_model_eval,
        "trigger": overall_trigger,
        "rationale": (
            "At least one model's best formal candidate has physical L=448 outperforming 384."
            if overall_trigger
            else "No model has physical L=448 outperforming 384 at the frontier; Stage P not triggered."
        ),
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(decision_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved extension decision to {output_json_path}")
    print(f"Trigger: {overall_trigger}")
    return 0


def cmd_combine(args: argparse.Namespace) -> int:
    """Combine Stage N (and Stage P if triggered) benchmark results and select optimal stack."""
    inputs = [Path(p).resolve() for p in args.inputs]
    decision_path = Path(args.extension_decision).resolve()
    output_json_path = Path(args.output_json).resolve()

    if not decision_path.is_file():
        print(f"ERROR: Extension decision missing at {decision_path}", file=sys.stderr)
        return 1

    decision_data = json.loads(decision_path.read_bytes())
    trigger = decision_data.get("trigger", False)

    # Verify trigger and inputs
    has_pooled = any("pooled" in str(p) for p in inputs)
    if trigger and not has_pooled:
        print("ERROR: Decision trigger is true, but no pooled results file was provided in --inputs", file=sys.stderr)
        return 1
    if not trigger and has_pooled:
        print("WARNING: Decision trigger is false, but pooled results file was provided in --inputs", file=sys.stderr)

    all_experiments = []
    seen_ids = set()
    models_evaluated = set()
    env_info = {}

    for in_path in inputs:
        if not in_path.is_file():
            print(f"ERROR: Input results file missing: {in_path}", file=sys.stderr)
            return 1
        data = json.loads(in_path.read_bytes())
        if not env_info:
            env_info = data.get("environment", {})
        for m in data.get("models_evaluated", []):
            models_evaluated.add(m)
        for exp in data.get("experiments", []):
            exp_copy = dict(exp)
            eid = exp_copy["experiment_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                all_experiments.append(exp_copy)

    from scripts.verify_embedding_benchmark import validate_batch
    validated = [validate_batch(Path(p)) for p in args.inputs]
    if len({d["protocol_sha256"] for d in validated}) != 1:
        raise ValueError("Cannot combine different evaluation protocols")
    if sum(len(d["experiments"]) for d in validated) != len(all_experiments):
        raise ValueError("Duplicate experiments across batches")
    formal_exps = [e for e in all_experiments if not e.get("is_diagnostic", False)]
    diag_exps = [e for e in all_experiments if e.get("is_diagnostic", False)]

    selection = select_stack(all_experiments)
    top_formal = selection["quality_leader"]
    best_candidate = selection["selected"]
    sel_cfg = MODEL_CONFIGS.get(best_candidate["model_id"], {})
    sel_stack = {
        "experiment_id": best_candidate["experiment_id"],
        "stage_id": best_candidate.get("stage_id", "stage-n"),
        "guard_group": best_candidate.get("guard_group", "default"),
        "model_id": best_candidate["model_id"],
        "model_revision": best_candidate["model_revision"],
        "dimension": best_candidate.get("dimension", sel_cfg.get("dim", 384)),
        "query_prefix": sel_cfg.get("query_prefix", ""),
        "doc_prefix": sel_cfg.get("doc_prefix", ""),
        "rawpedia_rule": best_candidate["rawpedia_rule"],
        "rawpedia_variant_id": best_candidate.get("rawpedia_variant_id", best_candidate["rawpedia_rule"]),
        "rawpedia_file_path": best_candidate.get("rawpedia_file_path", ""),
        "rawpedia_policy": best_candidate.get("rawpedia_policy", ""),
        "github_rule": best_candidate["github_rule"],
        "github_variant_id": best_candidate.get("github_variant_id", best_candidate["github_rule"]),
        "github_file_path": best_candidate.get("github_file_path", ""),
        "github_policy": best_candidate.get("github_policy", ""),
        "macro_mrr@5": best_candidate["metrics"]["macro"]["mrr@5"],
        "macro_hit@5": best_candidate["metrics"]["macro"]["hit@5"],
        "macro_all@5": best_candidate["metrics"]["macro"]["all@5"],
        "macro_full_evidence@5": best_candidate["metrics"]["macro"]["full_evidence@5"],
        "p95_latency_seconds": best_candidate["latency"]["p95_seconds"],
        "vector_bytes": best_candidate["vector_bytes"],
        "selection_rationale": "반올림 전 Macro MRR·Hit·complex 근거 기준으로 선두를 정하고, 근접 품질 조건을 만족한 후보에서 실측 p95·벡터 크기·ID 순으로 선정. 고정 질문셋·등록 범위의 조건부 결과.",
        "t9_reproduction_command": (
            f"python3 scripts/benchmark_embeddings.py check --input-json {output_json_path} --verify-top-candidates --work-dir recheck"
        ),
    }

    # Baseline lookup if available
    baseline_record = None
    baseline_path = REPO_ROOT / "docs/chunking_embedding_baseline_boundary_4096.json"
    if not baseline_path.is_file():
        baseline_path = REPO_ROOT / "docs/chunking_embedding_baseline_large_448_1024.json"
    if not baseline_path.is_file():
        baseline_path = REPO_ROOT / "docs/chunking_embedding_baseline_grid_128_224.json"
    if not baseline_path.is_file():
        baseline_path = REPO_ROOT / "docs/chunking_embedding_baseline_192_32.json"
    if baseline_path.is_file():
        try:
            b_data = json.loads(baseline_path.read_bytes())
            baseline_record = {
                "file_path": str(baseline_path.relative_to(REPO_ROOT)),
                "file_sha256": sha256_bytes(baseline_path.read_bytes()),
                "selected_stack": b_data.get("selected_stack", {}),
            }
        except Exception:
            pass

    stage_p_count = len([e for e in all_experiments if e.get("stage_id") == "boundary-pooled" or "pooled" in str(e.get("rawpedia_file_path", ""))])
    stage_n_count = len(all_experiments) - stage_p_count

    combined_summary = {
        "schema_version": 1,
        "dataset_id": "t08-1-100-v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "environment": env_info,
        "models_evaluated": sorted(list(models_evaluated)),
        "extension_decision": decision_data,
        "stage_n_experiments_count": stage_n_count,
        "stage_p_experiments_count": stage_p_count,
        "total_experiments_count": len(all_experiments),
        "formal_experiments_count": len(formal_exps),
        "diagnostic_experiments_count": len(diag_exps),
        "baseline": baseline_record,
        "selected_stack": sel_stack,
        "selected": sel_stack,
        "experiments": all_experiments,
        "status": "completed",
        "grid_complete": True,
        "protocol": validated[0]["protocol"],
        "protocol_sha256": validated[0]["protocol_sha256"],
        "batches": [{"path": str(Path(p).resolve().relative_to(REPO_ROOT)),
                     "matrix_sha256": d["matrix_sha256"], "matrix": d["matrix"],
                     "coverage": d["coverage"], "guard_manifest": d["guard_manifest"]}
                    for p, d in zip(args.inputs, validated)],
        "quality_leader_id": selection["quality_leader"]["experiment_id"],
        "close_candidate_ids": selection["close_candidate_ids"],
        "validation_status": "awaiting_independent_reproduction_and_policy_controls",
    }
    sel_stack.update(protocol_sha256=validated[0]["protocol_sha256"],
        input_fingerprint=best_candidate["input_fingerprint"],
        source_binding=best_candidate["source_binding"], document_inputs=best_candidate["document_inputs"],
        complex_macro_full_evidence_at_5=best_candidate["metrics"]["complex"]["macro"]["full_evidence@5"])

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(combined_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"SUCCESS: Combined {len(all_experiments)} experiments into {output_json_path}")
    print(f"Selected Stack: {best_candidate['rawpedia_rule']} + {best_candidate['github_rule']} with {best_candidate['model_id']}")
    print(f"  Macro MRR@5: {best_candidate['metrics']['macro']['mrr@5']:.4f}, Hit@5: {best_candidate['metrics']['macro']['hit@5']:.4f}")
    return 0


def cmd_report_markdown(args: argparse.Namespace) -> int:
    """Generate comprehensive Markdown and JSON reports from benchmark results."""
    input_json = Path(args.input_json).resolve()
    output_md = Path(args.output_md).resolve()
    output_json = Path(args.output_json).resolve() if getattr(args, "output_json", None) else None

    from scripts.verify_embedding_benchmark import validate_release
    data = validate_release(input_json)
    selected = data.get("selected_stack", {})
    experiments = data.get("experiments", [])
    formal_exps = [e for e in experiments if not e.get("is_diagnostic", False)]
    diag_exps = [e for e in experiments if e.get("is_diagnostic", False)]

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

    # Check if this is large chunk extension dataset
    is_large_chunk = "extension_decision" in data or any(re.search(r"-[tw](?:256|320|384|448|512|768|1024)-", e.get("rawpedia_rule", "")) for e in experiments)

    lines = [
        "# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트",
        "",
        f"- 생성 일시: {data.get('generated_at')}",
        f"- 평가 질문 데이터셋: `{data.get('dataset_id')}` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)",
    ]

    if is_large_chunk:
        ext_dec = data.get("extension_decision", {})
        trig_str = "실행 (Triggered)" if ext_dec.get("trigger") else "미실행 (Not Triggered)"
        n_cnt = data.get("stage_n_experiments_count", len(experiments))
        p_cnt = data.get("stage_p_experiments_count", 0)
        lines.extend([
            f"- 대형 청크 확장 단계: Stage N ({n_cnt}개) + Stage P ({p_cnt}개), 판정: {trig_str}",
            f"- 총 실험 조합: {len(experiments)}개 (정식 {len(formal_exps)}개 + 진단 {len(diag_exps)}개, 100% 완료)",
        ])
    else:
        lines.extend([
            "- 탐색 파라미터 그리드: L in {128, 192, 224}, O in {0, 32, 64}",
            f"- 총 실험 조합: {len(experiments)}개 (정식 {len(formal_exps)}개 + 진단 {len(diag_exps)}개, 100% 완료)",
        ])

    lines.extend([
        "",
        "## 1. 최종 선정 결과 요약",
        "",
        "| 구분 | 선정 항목 | 상세 내용 |",
        "|---|---|---|",
        f"| **최적 임베딩 모델** | `{selected.get('model_id')}` | Revision: `{selected.get('model_revision', '')[:12]}...`, Dim: {sel_dim} |",
        f"| **RawPedia 청킹 규칙** | `{selected.get('rawpedia_rule')}` | $L/O$ 파라미터 최적 조합 |",
        f"| **GitHub 청킹 규칙** | `{selected.get('github_rule')}` | 정제된 스레드/유닛 최적 조합 |",
        f"| **주요 검색 품질** | **Macro MRR@5: {selected.get('macro_mrr@5', 0.0):.4f}** | Macro Hit@5: {selected.get('macro_hit@5', 0.0):.4f} |",
        f"| **검색 속도 (p95)** | **{selected.get('p95_latency_seconds', 0.0)*1000:.1f} ms** | 100개 쿼리 단일 검색 지연 |",
        f"| **선정 근거** | {selected.get('selection_rationale')} |",
        "",
        "## 2. 과거 이력 및 정책 대조군",
        "",
        f"과거 결과는 `{baseline.get('file_path', '')}`에 보존하며, 정책·검색 조건·집계 순서가 달라 현행 선정값과의 차이를 정책 효과로 해석하지 않는다.",
        "",
        "| 대조군 | 검색 조건 | Macro MRR@5 (반올림 전 값의 표시) | Q091 정답 순위 |",
        "|---|---|---|---|",
    ])
    control_path = REPO_ROOT / data["validation"]["policy_controls"]["path"]
    controls = json.loads(control_path.read_bytes())
    for control in controls["controls"]:
        lines.append(f"| {control['experiment_id']} | {control['control_search_policy']} | {control['metrics']['macro']['mrr@5']:.8f} | {control['q091']['first_rel_rank']} |")
    lines.extend(["", f"이전의 출처별 선반올림 방식으로 C0-legacy를 집계하면 `{controls['historical_rounded_macro_mrr_at_5']:.4f}`다. 현재 JSON에는 선반올림 없이 저장한다."])
    for label, delta in controls["deltas"].items():
        lines.append(f"- 동일 공통 검색 조건의 {label}: Macro MRR@5 `{delta['macro_mrr_at_5']:+.8f}`.")
    lines.extend(["", f"선정·trigger는 비반올림 값으로 계산한다. 품질 분모는 RawPedia80/GitHub15, negative5는 별도이며 complex subset도 각 출처 실제 분모로 집계한다. 선정 후보의 complex Macro FullEvidence@5는 `{selected['complex_macro_full_evidence_at_5']:.8f}`다.",
        f"전체 {len(experiments)}행 원시 로그·재집계, 1,650,600개의 실제 관측과 4개 필수 대상의 독립 재인코딩·색인 재현을 통과했다. 이 선정은 이번 질문셋·선언 조합 범위의 결과다.", ""])

    # Determine boundary status
    r_sel_rule = selected.get("rawpedia_rule", "")
    g_sel_rule = selected.get("github_rule", "")
    r_l_match = re.search(r"-t(\d+)-", r_sel_rule)
    r_l = int(r_l_match.group(1)) if r_l_match else 224
    g_l_match = re.search(r"-[tw](\d+)-", g_sel_rule)
    g_l = int(g_l_match.group(1)) if g_l_match else 224

    # Collect all available L and O values dynamically from formal experiments
    parsed_l = set()
    parsed_o = set()
    curve_exps = [e for e in formal_exps if e["model_id"] == sel_m_id
        and e["guard_group"] == selected["guard_group"]
        and e["rawpedia_policy"] == selected["rawpedia_policy"]
        and e["github_policy"] == selected["github_policy"]]
    for e in curve_exps:
        m_l = re.search(r"-t(\d+)-", e.get("rawpedia_rule", ""))
        m_o = re.search(r"-o(\d+)", e.get("rawpedia_rule", ""))
        if m_l:
            parsed_l.add(int(m_l.group(1)))
        if m_o:
            parsed_o.add(int(m_o.group(1)))

    max_l = max(parsed_l) if parsed_l else 448
    if r_l == max_l or ("curated-unit" in g_sel_rule and g_l == max_l):
        boundary_status = "upper_boundary"
        boundary_desc = f"청크 크기가 탐색 그리드의 실제 탐색 상한선({max_l} 토큰)에 위치하며 상한선에서 최적 성능 달성."
    elif "thread" in g_sel_rule and g_l == 448 and r_l < 448:
        boundary_status = "encoder_limited"
        boundary_desc = "GitHub 스레드의 내부 인코더 윈도우(W=448)가 인코더 문맥 한도에 도달하였으나 RawPedia 물리 청크는 내부 피크에 머무름."
    elif r_l < max_l and g_l < max_l:
        boundary_status = "interior_peak"
        boundary_desc = f"탐색 공간 내부({r_l} 토큰)에서 최적점을 형성하여 상한선 미만에서 성능 피크 도달."
    else:
        boundary_status = "no_effect"
        boundary_desc = "청크 크기 확장에 따른 유의미한 검색 품질 향상이 관측되지 않음."

    lines.extend([
        "## 3. 대형 청크 확장 파라미터 탐색 분석",
        "",
        f"- **경계 판정 (Boundary Status)**: `{boundary_status}` ({boundary_desc})",
        "",
        f"선정 모델(`{sel_m_id}`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \\times O$ 그리드별 검색 품질(Macro MRR@5) 변화:",
        "",
    ])

    l_candidates = sorted(list(parsed_l)) if parsed_l else ([224, 256, 320, 384, 448] if is_large_chunk else [128, 192, 224])
    o_candidates = sorted(list(parsed_o)) if parsed_o else [0, 32, 64]
    r_family = "R-B-window" if "R-B" in r_sel_rule else "R-A-heading"

    o_header = " | ".join(f"$O = {o}$" for o in o_candidates)
    lines.append(f"| 청크 크기 ($L$) \\ 오버랩 ($O$) | {o_header} |")
    lines.append("|---" * (len(o_candidates) + 1) + "|")

    for l_val in l_candidates:
        row_vals = []
        for o_val in o_candidates:
            target_r_vid = f"{r_family}-t{l_val}-o{o_val}"
            matching = [
                e for e in curve_exps
                if e["model_id"] == sel_m_id and e["rawpedia_rule"] == target_r_vid and e["github_rule"] == sel_g_rule
            ]
            if matching:
                row_vals.append(f"{matching[0]['metrics']['macro']['mrr@5']:.4f}")
            else:
                row_vals.append("N/A")
        lines.append(f"| **$L = {l_val}$** | " + " | ".join(row_vals) + " |")

    # Section 4: Context Budgets & Top Combinations
    has_budget = any("budget_2048_hit@5" in e.get("metrics", {}).get("macro", {}) for e in formal_exps)
    if has_budget:
        lines.extend([
            "",
            "## 4. 문맥 예산 ($B=2048, 4096$) 하의 검색 지표 요약",
            "",
            "| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro MRR@5 | B=2048 Hit@5 | B=2048 FullEv@5 | B=4096 Hit@5 | B=4096 FullEv@5 |",
            "|---|---|---|---|---|---|---|---|---|",
        ])
        sorted_by_mrr = sorted(formal_exps, key=lambda e: e["metrics"]["macro"]["mrr@5"], reverse=True)
        budget_rows = sorted_by_mrr[:15]
        selected_row = next(e for e in formal_exps if e["experiment_id"] == selected["experiment_id"])
        if selected_row not in budget_rows:
            budget_rows.append(selected_row)
        for rank, e in enumerate(budget_rows, start=1):
            m = e["metrics"]["macro"]
            m_id = e["model_id"].split("/")[-1]
            b2048_h = m.get("budget_2048_hit@5", "N/A")
            b2048_fe = m.get("budget_2048_full_evidence@5", "N/A")
            b4096_h = m.get("budget_4096_hit@5", "N/A")
            b4096_fe = m.get("budget_4096_full_evidence@5", "N/A")
            lines.append(
                f"| {rank} | `{m_id}` | `{e['rawpedia_rule']}` | `{e['github_rule']}` | "
                f"**{m['mrr@5']:.4f}** | {b2048_h} | {b2048_fe} | {b4096_h} | {b4096_fe} |"
            )

    lines.extend([
        "",
        "## 5. 상위 정식 실험 조합 비교표 (Top 25 Combinations)",
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
        "## 6. 결론 및 T9 인계 명세",
        "",
        "1. **최종 선정 스택**:",
        f"   - **임베딩 모델**: `{selected.get('model_id')}` (commit revision: `{selected.get('model_revision')}`)",
        f"   - **차원 및 Prefix**: {sel_dim} 차원 / Query: `{sel_q_pref}` / Document: `{sel_d_pref}`",
        f"   - **RawPedia 청크 파일**: `{selected.get('rawpedia_file_path', 'data/chunks/...')}`",
        f"   - **GitHub 청크 파일**: `{selected.get('github_file_path', 'data/chunks/...')}`",
        "   - **Chroma 설정**: cosine, HNSW ef_construction/ef_search=200, max_neighbors=16, num_threads=1. fetch10 후 distance(6자리)·chunk ID 순 top5.",
        f"   - **공통 protocol SHA**: `{data['protocol_sha256']}`",
        f"   - **선정 입력 fingerprint**: `{selected['input_fingerprint']}`",
        f"   - **독립 재현 기록**: `{data['validation']['independent_reproduction']['path']}`",
        f"   - **정책 대조군 기록**: `{data['validation']['policy_controls']['path']}`",
        "   - R/G JSONL·guard·전체 encoder/window·가중치·vector·코드·패키지 지문과 원시 로그 SHA는 JSON의 source_binding/document_inputs/protocol/validation을 함께 전달한다.",
        "",
        "2. **인계 주의 사항**:",
        f"   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`{sel_q_pref}`)를 부가하여 {sel_dim}차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.",
        f"   - GitHub 스레드 청크는 `{selected.get('github_policy', 'thread_window_mean_v3')}` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.",
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
    mx.add_argument("--model-ids", nargs="*", help="Filter model IDs to evaluate")
    mx.add_argument("--rawpedia-variant-ids", nargs="*", help="Filter RawPedia variant IDs to evaluate")
    mx.add_argument("--github-variant-ids", nargs="*", help="Filter GitHub variant IDs to evaluate")
    mx.add_argument(
        "--guard-group",
        choices=["native-common-256", "bge-512", "e5-512", "pooled-common-256"],
        default=None,
        help="Guard group for matrix generation.",
    )
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
    rn.add_argument(
        "--guard-group",
        choices=["native-common-256", "bge-512", "e5-512", "pooled-common-256"],
        default=None,
        help="Guard group for benchmark run.",
    )
    rn.add_argument("--context-budgets", nargs="*", type=int, default=[2048, 4096])
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

    # decide-extension
    de = subparsers.add_parser("decide-extension", help="Evaluate trigger conditions for large chunk extension.")
    de.add_argument("--stage", choices=["stage-n", "boundary-pooled"], default="stage-n")
    de.add_argument("--inputs", nargs="+", required=True)
    de.add_argument("--output-json", required=True)
    de.set_defaults(func=cmd_decide_extension)

    # combine
    cb = subparsers.add_parser("combine", help="Combine benchmark results across stages.")
    cb.add_argument("--inputs", nargs="+", required=True)
    cb.add_argument("--extension-decision", required=True)
    cb.add_argument("--output-json", required=True)
    cb.set_defaults(func=cmd_combine)

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
