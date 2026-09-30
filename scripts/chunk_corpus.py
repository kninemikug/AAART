#!/usr/bin/env python3
"""Corpus chunking CLI and pipeline utility for ART Master RAG.

Provides prepare, build, and check subcommands for deterministic chunk generation
and provenance validation according to docs/T08_2_execution_plan.md.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.artagent.chunking import (
    BGE_REVISION,
    CHUNK_SCHEMA_VERSION,
    GUARD_GROUP_CONTRACTS,
    Chunk,
    SourceSegment,
    calculate_evidence_chunk_coverage,
    calculate_evidence_chunks_union_coverage,
    canonical_json_bytes,
    compute_chunk_id,
    resolve_guard_models,
    sha256_bytes,
    sha256_str,
    validate_chunk_provenance,
)
from src.artagent.issue_filter import load_sources
from scripts.generate_eval_queries import (
    compute_rawpedia_files_sha256,
    parse_rawpedia_collection_included,
)


EXPECTED_FILE_HASHES = {
    "docs/search_eval_queries.json": "91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8",
    "docs/search_eval_source_manifest.json": "9df74aad9b082f4ce908f38f9a53e4850de24fd9f889c60c9da04791fa59d309",
    "data/issues/search-candidates.json": "c2074548354406b6bd2e886259ca8eea4a02813dead57fba77e0bf1a5bf86344",
    "data/issues/sync-state.json": "0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187",
    "docs/rawpedia_collection.md": "234766dbe5ace8f8ccef4965a32ced0b79ad55939a2363bfb0ebae126863a7a0",
    "rawpedia_files_sha256": "241c48434bab72cceacfdcc083869c4e27265e4b474d48988fab0f0cb813f56f",
}


def get_current_git_head() -> str:
    """Return current git HEAD commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def cmd_prepare(args: argparse.Namespace) -> int:
    """Validate all source inputs and freeze data/chunks/t08-2/manifest.json."""
    rawpedia_dir = Path(args.rawpedia_dir).resolve()
    collection_md = Path(args.rawpedia_collection).resolve()
    candidates_json = Path(args.github_candidates).resolve()
    github_dir = Path(args.github_dir).resolve()
    source_manifest_json = Path(args.source_manifest).resolve()
    queries_json = Path(args.queries).resolve()
    output_dir = Path(args.output_dir).resolve()

    print("=== Step 1: Input Verification and Manifest Freezing ===")

    # 1. Verify fixed file fingerprints
    files_to_check = {
        "docs/search_eval_queries.json": queries_json,
        "docs/search_eval_source_manifest.json": source_manifest_json,
        "data/issues/search-candidates.json": candidates_json,
        "data/issues/sync-state.json": github_dir / "sync-state.json",
        "docs/rawpedia_collection.md": collection_md,
    }

    actual_fingerprints: Dict[str, str] = {}
    for rel_name, p in files_to_check.items():
        if not p.is_file():
            print(f"ERROR: Missing expected input file: {p}", file=sys.stderr)
            return 1
        actual_sha = sha256_bytes(p.read_bytes())
        expected_sha = EXPECTED_FILE_HASHES[rel_name]
        if actual_sha != expected_sha:
            print(
                f"ERROR: SHA-256 drift for {rel_name}:\n  expected: {expected_sha}\n  actual:   {actual_sha}",
                file=sys.stderr,
            )
            return 1
        actual_fingerprints[rel_name] = actual_sha

    # Verify rawpedia aggregate files SHA-256
    rawpedia_agg_sha, rawpedia_files = compute_rawpedia_files_sha256()
    if rawpedia_agg_sha != EXPECTED_FILE_HASHES["rawpedia_files_sha256"]:
        print(
            f"ERROR: RawPedia files aggregate SHA-256 drift:\n"
            f"  expected: {EXPECTED_FILE_HASHES['rawpedia_files_sha256']}\n"
            f"  actual:   {rawpedia_agg_sha}",
            file=sys.stderr,
        )
        return 1
    actual_fingerprints["rawpedia_files_sha256"] = rawpedia_agg_sha

    if len(rawpedia_files) != 116:
        print(f"ERROR: Expected 116 RawPedia files, found {len(rawpedia_files)}", file=sys.stderr)
        return 1

    # Verify individual RawPedia files against source_manifest
    source_manifest_data = json.loads(source_manifest_json.read_bytes())
    source_manifest_sources = source_manifest_data.get("rawpedia_sources", {})
    rawpedia_source_info = parse_rawpedia_collection_included(collection_md)
    if len(rawpedia_source_info) != 116:
        print(f"ERROR: Expected 116 included RawPedia docs, found {len(rawpedia_source_info)}", file=sys.stderr)
        return 1

    for rf in rawpedia_files:
        path_str = rf["path"]
        f_sha = rf["sha256"]
        if path_str not in rawpedia_source_info:
            print(f"ERROR: {path_str} not in rawpedia_collection.md included list", file=sys.stderr)
            return 1
        # Check source manifest
        if path_str not in source_manifest_sources:
            print(f"ERROR: path {path_str} missing from source manifest", file=sys.stderr)
            return 1
        sm_entry = source_manifest_sources[path_str]
        if sm_entry.get("file_sha256") != f_sha:
            print(f"ERROR: File sha mismatch for {path_str} in source manifest", file=sys.stderr)
            return 1

    # 2. Verify GitHub candidates and threads
    cand_data = json.loads(candidates_json.read_bytes())
    candidates = cand_data.get("candidates", [])
    if len(candidates) != 12:
        print(f"ERROR: Expected 12 GitHub candidates, found {len(candidates)}", file=sys.stderr)
        return 1

    total_curated_content = sum(len(c.get("curated_content", [])) for c in candidates)
    if total_curated_content != 35:
        print(f"ERROR: Expected 35 curated_content slices, found {total_curated_content}", file=sys.stderr)
        return 1

    inv = load_sources(github_dir)
    threads_by_key = {t.record_key: t for t in inv.threads}
    total_candidate_comments = 0
    for c in candidates:
        th = threads_by_key.get(c["source_record_key"])
        if not th:
            print(f"ERROR: Thread {c['source_record_key']} not found in source inventory", file=sys.stderr)
            return 1
        total_candidate_comments += len(th.comments)

        # Check source_locations
        for loc in c.get("source_locations", []):
            rel_snap = loc["snapshot_path"]
            fpath = github_dir / rel_snap
            if not fpath.is_file():
                print(f"ERROR: Candidate source file missing: {fpath}", file=sys.stderr)
                return 1
            f_bytes = fpath.read_bytes()
            if sha256_bytes(f_bytes) != loc["file_sha256"]:
                print(f"ERROR: File SHA mismatch for candidate location {rel_snap}", file=sys.stderr)
                return 1
            body_text = json.loads(f_bytes).get("body", "")
            if sha256_str(body_text) != loc["body_sha256"]:
                print(f"ERROR: Body SHA mismatch for candidate location {rel_snap}", file=sys.stderr)
                return 1

    if total_candidate_comments != 39:
        print(f"ERROR: Expected 39 total thread comments for candidates, found {total_candidate_comments}", file=sys.stderr)
        return 1

    # 3. Verify 100 queries and 147 evidence spans
    queries_data = json.loads(queries_json.read_bytes())
    queries = queries_data.get("queries", [])
    if len(queries) != 100:
        print(f"ERROR: Expected 100 queries, found {len(queries)}", file=sys.stderr)
        return 1

    query_ids = [q["query_id"] for q in queries]
    if len(set(query_ids)) != 100:
        print("ERROR: Duplicate query IDs found", file=sys.stderr)
        return 1

    pos_queries = [q for q in queries if q["difficulty"] != "negative"]
    neg_queries = [q for q in queries if q["difficulty"] == "negative"]
    if len(pos_queries) != 95 or len(neg_queries) != 5:
        print(f"ERROR: Expected 95 positive and 5 negative queries, got {len(pos_queries)}/{len(neg_queries)}", file=sys.stderr)
        return 1

    rawpedia_queries = [q for q in queries if q["source_type"] == "rawpedia"]
    github_queries = [q for q in queries if q["source_type"] == "github"]
    if len(rawpedia_queries) != 80 or len(github_queries) != 20:
        print(f"ERROR: Expected 80 RawPedia and 20 GitHub queries, got {len(rawpedia_queries)}/{len(github_queries)}", file=sys.stderr)
        return 1

    # Negative queries must be Q096~Q100
    for q in neg_queries:
        if q["expected_behavior"] != "unsupported_or_insufficient_evidence":
            print(f"ERROR: Negative query {q['query_id']} has unexpected behavior", file=sys.stderr)
            return 1
        if q["gold_support_doc_ids"] != []:
            print(f"ERROR: Negative query {q['query_id']} has non-empty gold_support_doc_ids", file=sys.stderr)
            return 1

    total_evidence = 0
    support_count = 0
    counter_count = 0
    for q in queries:
        for ev in q.get("evidence", []):
            total_evidence += 1
            if ev["role"] == "support":
                support_count += 1
            elif ev["role"] == "counterevidence":
                counter_count += 1
            else:
                print(f"ERROR: Unknown evidence role: {ev['role']}", file=sys.stderr)
                return 1

            # Verify actual source slice
            src_path = REPO_ROOT / ev["source_path"]
            if not src_path.is_file():
                print(f"ERROR: Evidence source path missing: {ev['source_path']}", file=sys.stderr)
                return 1
            src_bytes = src_path.read_bytes()
            if sha256_bytes(src_bytes) != ev["source_file_sha256"]:
                print(f"ERROR: Evidence source file SHA mismatch for {ev['source_path']}", file=sys.stderr)
                return 1

            b_start = ev["byte_start"]
            b_end = ev["byte_end"]
            ev_text = ev["text_span"]

            if ev.get("json_pointer") == "/body":
                body = json.loads(src_bytes).get("body", "")
                c_start = ev["char_start"]
                c_end = ev["char_end"]
                actual_slice = body[c_start:c_end]
                body_enc = body.encode("utf-8")
                actual_bstart = len(body[:c_start].encode("utf-8"))
                actual_bend = len(body[:c_end].encode("utf-8"))
                # Also verify evidence_hash
                ev_slice_bytes = body_enc[b_start:b_end]
                if sha256_bytes(ev_slice_bytes) != ev["evidence_hash"]:
                    print(f"ERROR: Evidence hash mismatch in {q['query_id']}", file=sys.stderr)
                    return 1
            else:
                text = src_bytes.decode("utf-8")
                ev_slice_bytes = src_bytes[b_start:b_end]
                actual_slice = ev_slice_bytes.decode("utf-8")
                c_start = len(src_bytes[:b_start].decode("utf-8"))
                c_end = len(src_bytes[:b_end].decode("utf-8"))
                actual_bstart = b_start
                actual_bend = b_end
                if sha256_bytes(ev_slice_bytes) != ev["evidence_hash"]:
                    print(f"ERROR: Evidence hash mismatch in {q['query_id']}", file=sys.stderr)
                    return 1

            if actual_slice != ev_text:
                print(f"ERROR: Evidence text span mismatch in {q['query_id']}", file=sys.stderr)
                return 1
            if b_start != actual_bstart or b_end != actual_bend:
                print(f"ERROR: Evidence byte offset mismatch in {q['query_id']}", file=sys.stderr)
                return 1

    if total_evidence != 147 or support_count != 142 or counter_count != 5:
        print(f"ERROR: Evidence count mismatch: total={total_evidence} (support={support_count}, counter={counter_count})", file=sys.stderr)
        return 1

    # 4. Preserve baseline benchmark files if provided
    baseline_record = {}
    baseline_prefix = getattr(args, "baseline_prefix", None)
    if getattr(args, "baseline_md", None):
        base_md_in = Path(args.baseline_md).resolve()
        if baseline_prefix:
            preserved_md = REPO_ROOT / f"{baseline_prefix}.md"
        else:
            preserved_md = REPO_ROOT / "docs/chunking_embedding_baseline_192_32.md"
        if base_md_in.is_file():
            if not preserved_md.is_file():
                preserved_md.parent.mkdir(parents=True, exist_ok=True)
                preserved_md.write_bytes(base_md_in.read_bytes())
            md_sha = sha256_bytes(preserved_md.read_bytes())
            try:
                rel_md = preserved_md.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel_md = str(preserved_md)
            baseline_record["markdown"] = {
                "source_path": rel_md,
                "file_sha256": md_sha,
            }
    if getattr(args, "baseline_json", None):
        base_json_in = Path(args.baseline_json).resolve()
        if baseline_prefix:
            preserved_json = REPO_ROOT / f"{baseline_prefix}.json"
        else:
            preserved_json = REPO_ROOT / "docs/chunking_embedding_baseline_192_32.json"
        if base_json_in.is_file():
            if not preserved_json.is_file():
                preserved_json.parent.mkdir(parents=True, exist_ok=True)
                preserved_json.write_bytes(base_json_in.read_bytes())
            json_sha = sha256_bytes(preserved_json.read_bytes())
            try:
                rel_json = preserved_json.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel_json = str(preserved_json)
            baseline_record["json"] = {
                "source_path": rel_json,
                "file_sha256": json_sha,
            }

    # 5. Save manifest.json in output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"

    manifest_payload = {
        "schema_version": 1,
        "dataset_id": "t08-1-100-v1",
        "rules_version": "t10-2a-v1",
        "sync_time": "2026-09-28T02:06:12Z",
        "baseline_head": "b7c105cc1c0ded7647be9bfe891cf4c23f7652eb",
        "execution_head": get_current_git_head(),
        "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "input_fingerprints": actual_fingerprints,
        "baseline_files": baseline_record,
        "counts": {
            "rawpedia_files": 116,
            "github_candidates": 12,
            "curated_content_segments": 35,
            "candidate_thread_comments": 39,
            "total_queries": 100,
            "positive_queries": 95,
            "negative_queries": 5,
            "rawpedia_queries": 80,
            "github_queries": 20,
            "total_evidence_spans": 147,
            "support_spans": 142,
            "counterevidence_spans": 5,
        },
        "rawpedia_sources_summary": {
            "count": 116,
            "aggregate_sha256": rawpedia_agg_sha,
        },
        "github_candidates_summary": {
            "count": 12,
            "curated_segments_count": 35,
            "threads_comments_count": 39,
        },
    }

    manifest_bytes = json.dumps(manifest_payload, indent=2, ensure_ascii=False).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    print(f"SUCCESS: Frozen input manifest written to: {manifest_path}")
    print(f"  RawPedia files: 116 | GitHub candidates: 12 (curated: 35, comments: 39)")
    print(f"  Queries: 100 (95 positive, 5 negative) | Evidence spans: 147 (142 support, 5 counter)")
    if baseline_record:
        print(f"  Preserved baseline records: {list(baseline_record.keys())}")
    return 0


def execute_chunking_build(
    manifest_path: Path,
    model_manifest_path: Path,
    rawpedia_rules: List[str],
    github_rules: List[str],
    target_tokens_grid: List[int],
    overlap_tokens_grid: List[int],
    thread_window_tokens_grid: List[int],
    target_dir: Path,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
    thread_embedding_policy: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Core logic to build chunks and compute gold mapping across the full parameter grid."""
    from transformers import AutoTokenizer
    from src.artagent.chunking import (
        GUARD_GROUP_CONTRACTS,
        TokenizerBundle,
        chunk_rawpedia_heading_rule,
        chunk_rawpedia_window_rule,
        chunk_rawpedia_heading_window_rule,
        chunk_github_curated_unit_rule,
        chunk_github_curated_group_rule,
        chunk_github_thread_rule,
        get_evidence_char_range,
        resolve_guard_models,
        verify_raw_text_coverage,
    )

    manifest_data = json.loads(manifest_path.read_bytes())
    model_data = json.loads(model_manifest_path.read_bytes())

    # Resolve strict guard models according to guard group contract
    all_models = model_data.get("models", {})
    guard_models = resolve_guard_models(guard_group, all_models)
    if guard_group:
        contract = GUARD_GROUP_CONTRACTS[guard_group]
        if physical_embedding_policy and physical_embedding_policy not in contract["allowed_physical_policies"]:
            raise ValueError(
                f"Physical embedding policy '{physical_embedding_policy}' is not allowed for guard group '{guard_group}' (allowed: {contract['allowed_physical_policies']})"
            )

    # 1. Initialize TokenizerBundle with ONLY the guard tokenizers
    print(f"Loading tokenizers for chunking build (guard_group={guard_group}, models={list(guard_models.keys())})...")
    bge_tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION)
    candidate_toks = {}
    for m_id, m_info in guard_models.items():
        candidate_toks[m_id] = AutoTokenizer.from_pretrained(m_id, revision=m_info["revision"])
    tokenizer_bundle = TokenizerBundle(bge_tok, candidate_toks)

    # 2. Source getter for validation
    source_cache: Dict[str, Tuple[str, str]] = {}

    def get_source_text(seg: SourceSegment) -> Tuple[str, str]:
        sp = seg.source_path
        if sp not in source_cache:
            p = REPO_ROOT / sp
            b = p.read_bytes()
            f_sha = sha256_bytes(b)
            if seg.json_pointer == "/body":
                body = json.loads(b).get("body", "")
                source_cache[sp] = (body, f_sha)
            else:
                text = b.decode("utf-8")
                source_cache[sp] = (text, f_sha)
        return source_cache[sp]

    # 3. Load RawPedia docs
    rawpedia_dir = REPO_ROOT / "data/rawpedia"
    collection_md = REPO_ROOT / "docs/rawpedia_collection.md"
    rawpedia_info = parse_rawpedia_collection_included(collection_md)
    rawpedia_files = sorted(rawpedia_dir.rglob("*.md"))

    # 4. Load GitHub candidates and threads
    cand_file = REPO_ROOT / "data/issues/search-candidates.json"
    candidates = json.loads(cand_file.read_bytes()).get("candidates", [])
    github_dir = REPO_ROOT / "data/issues"
    inv = load_sources(github_dir)
    threads_by_key = {t.record_key: t for t in inv.threads}

    chunks_by_variant: Dict[str, List[Chunk]] = {}
    rule_manifest: Dict[str, Any] = {}

    # Build RawPedia rules across (L, O) grid
    for r_rule in rawpedia_rules:
        for l_val in target_tokens_grid:
            for o_val in overlap_tokens_grid:
                variant_id = f"{r_rule}-t{l_val}-o{o_val}"
                print(f"Building chunks for {variant_id}...")
                rule_chunks: List[Chunk] = []
                for rf in rawpedia_files:
                    rel_p = rf.relative_to(REPO_ROOT).as_posix()
                    info = rawpedia_info[rel_p]
                    doc_id = info["doc_id"]
                    page_url = info["page_url"]
                    b = rf.read_bytes()
                    if r_rule == "R-A-heading":
                        c_list = chunk_rawpedia_heading_rule(
                            rel_p,
                            b,
                            doc_id,
                            page_url,
                            tokenizer_bundle,
                            l_val,
                            o_val,
                            guard_group=guard_group,
                            physical_embedding_policy=physical_embedding_policy,
                            guard_models=guard_models,
                            encoder_window_tokens=encoder_window_tokens,
                            encoder_overlap_tokens=encoder_overlap_tokens,
                        )
                    elif r_rule == "R-B-window":
                        c_list = chunk_rawpedia_window_rule(
                            rel_p,
                            b,
                            doc_id,
                            page_url,
                            tokenizer_bundle,
                            l_val,
                            o_val,
                            guard_group=guard_group,
                            physical_embedding_policy=physical_embedding_policy,
                            guard_models=guard_models,
                            encoder_window_tokens=encoder_window_tokens,
                            encoder_overlap_tokens=encoder_overlap_tokens,
                        )
                    elif r_rule == "R-C-heading-window":
                        c_list = chunk_rawpedia_heading_window_rule(
                            rel_p,
                            b,
                            doc_id,
                            page_url,
                            tokenizer_bundle,
                            l_val,
                            o_val,
                            guard_group=guard_group,
                            physical_embedding_policy=physical_embedding_policy,
                            guard_models=guard_models,
                            encoder_window_tokens=encoder_window_tokens,
                            encoder_overlap_tokens=encoder_overlap_tokens,
                        )
                    else:
                        raise ValueError(f"Unknown RawPedia rule {r_rule}")

                    for c in c_list:
                        validate_chunk_provenance(c, get_source_text)
                    rule_chunks.extend(c_list)

                chunks_by_variant[variant_id] = rule_chunks

    # Build GitHub rules
    # G-B-curated-unit across (L, O) grid
    if "G-B-curated-unit" in github_rules:
        for l_val in target_tokens_grid:
            for o_val in overlap_tokens_grid:
                variant_id = f"G-B-curated-unit-t{l_val}-o{o_val}"
                print(f"Building chunks for {variant_id}...")
                rule_chunks = []
                for cand in candidates:
                    c_list = chunk_github_curated_unit_rule(
                        cand,
                        github_dir,
                        tokenizer_bundle,
                        l_val,
                        o_val,
                        guard_group=guard_group,
                        physical_embedding_policy=physical_embedding_policy,
                        guard_models=guard_models,
                        encoder_window_tokens=encoder_window_tokens,
                        encoder_overlap_tokens=encoder_overlap_tokens,
                    )
                    for c in c_list:
                        validate_chunk_provenance(c, get_source_text)
                    rule_chunks.extend(c_list)
                chunks_by_variant[variant_id] = rule_chunks

    # G-C-curated-group across (L, O) grid
    if "G-C-curated-group" in github_rules:
        for l_val in target_tokens_grid:
            for o_val in overlap_tokens_grid:
                variant_id = f"G-C-curated-group-t{l_val}-o{o_val}"
                print(f"Building chunks for {variant_id}...")
                rule_chunks = []
                for cand in candidates:
                    c_list = chunk_github_curated_group_rule(
                        cand,
                        github_dir,
                        tokenizer_bundle,
                        l_val,
                        o_val,
                        guard_group=guard_group,
                        physical_embedding_policy=physical_embedding_policy,
                        guard_models=guard_models,
                        encoder_window_tokens=encoder_window_tokens,
                        encoder_overlap_tokens=encoder_overlap_tokens,
                    )
                    for c in c_list:
                        validate_chunk_provenance(c, get_source_text)
                    rule_chunks.extend(c_list)
                chunks_by_variant[variant_id] = rule_chunks

    # G-A-curated-thread across thread_window_tokens_grid
    if "G-A-curated-thread" in github_rules:
        for w_val in thread_window_tokens_grid:
            variant_id = f"G-A-curated-thread-w{w_val}-wo0"
            print(f"Building chunks for {variant_id}...")
            rule_chunks = []
            for cand in candidates:
                c_th = chunk_github_thread_rule(
                    cand,
                    github_dir,
                    tokenizer_bundle,
                    curated_only=True,
                    target_tokens=w_val,
                    guard_group=guard_group,
                    guard_models=guard_models,
                    encoder_window_tokens=encoder_window_tokens or w_val,
                    encoder_overlap_tokens=encoder_overlap_tokens or 0,
                    thread_embedding_policy=thread_embedding_policy,
                )
                validate_chunk_provenance(c_th, get_source_text)
                rule_chunks.append(c_th)
            chunks_by_variant[variant_id] = rule_chunks

    # G-A-full-thread across thread_window_tokens_grid
    if "G-A-full-thread" in github_rules:
        for w_val in thread_window_tokens_grid:
            variant_id = f"G-A-full-thread-w{w_val}-wo0"
            print(f"Building chunks for {variant_id}...")
            rule_chunks = []
            for cand in candidates:
                th_obj = threads_by_key[cand["source_record_key"]]
                c_th = chunk_github_thread_rule(
                    cand,
                    github_dir,
                    tokenizer_bundle,
                    curated_only=False,
                    thread_obj=th_obj,
                    target_tokens=w_val,
                    guard_group=guard_group,
                    guard_models=guard_models,
                    encoder_window_tokens=encoder_window_tokens or w_val,
                    encoder_overlap_tokens=encoder_overlap_tokens or 0,
                    thread_embedding_policy=thread_embedding_policy,
                )
                validate_chunk_provenance(c_th, get_source_text)
                rule_chunks.append(c_th)
            chunks_by_variant[variant_id] = rule_chunks

    # 5. Save JSONL files and write metadata
    for variant_id, c_list in chunks_by_variant.items():
        if variant_id.startswith("R-"):
            out_subdir = target_dir / "rawpedia"
        else:
            out_subdir = target_dir / "github"
        out_subdir.mkdir(parents=True, exist_ok=True)
        jsonl_path = out_subdir / f"{variant_id}.jsonl"

        lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in c_list]
        file_bytes = ("\n".join(lines) + "\n").encode("utf-8")
        jsonl_path.write_bytes(file_bytes)
        file_sha = sha256_bytes(file_bytes)
        try:
            rel_file_path = jsonl_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_file_path = str(jsonl_path)

        first_c = c_list[0] if c_list else None
        actual_toks_list = [c.metadata.get("actual_tokens", 0) for c in c_list]

        # Verify 100% non-whitespace coverage
        if variant_id.startswith("R-"):
            cov_res = verify_raw_text_coverage(c_list, rawpedia_dir, cand_file, github_dir, source_type="rawpedia")
            if cov_res["missing_chars_count"] > 0:
                raise ValueError(
                    f"Coverage verification failed for {variant_id}: {cov_res['missing_chars_count']} chars missing across {cov_res['missing_intervals_count']} intervals! First: {cov_res['omissions'][0]}"
                )
        elif variant_id.startswith("G-"):
            cov_res = verify_raw_text_coverage(c_list, rawpedia_dir, cand_file, github_dir, source_type="github")
            if cov_res["missing_chars_count"] > 0:
                raise ValueError(
                    f"Coverage verification failed for {variant_id}: {cov_res['missing_chars_count']} chars missing across {cov_res['missing_intervals_count']} intervals! First: {cov_res['omissions'][0]}"
                )

        rule_manifest[variant_id] = {
            "rule_id": variant_id,
            "rule_family": first_c.metadata.get("rule_family") if first_c else "",
            "chunk_count": len(c_list),
            "file_path": rel_file_path,
            "file_sha256": file_sha,
            "target_tokens": first_c.metadata.get("target_tokens") if first_c else None,
            "overlap_tokens": first_c.metadata.get("overlap_tokens") if first_c else None,
            "encoder_window_tokens": first_c.metadata.get("encoder_window_tokens") if first_c else None,
            "encoder_overlap_tokens": first_c.metadata.get("encoder_overlap_tokens") if first_c else None,
            "embedding_policy": first_c.metadata.get("embedding_policy") if first_c else None,
            "guard_group": first_c.metadata.get("guard_group") if first_c else None,
            "actual_tokens_min": min(actual_toks_list) if actual_toks_list else 0,
            "actual_tokens_max": max(actual_toks_list) if actual_toks_list else 0,
            "zero_omission": True,
            "is_diagnostic": "full-thread" in variant_id,
        }
        print(f"  {variant_id}: {len(c_list)} chunks (zero omission verified) -> {jsonl_path} ({file_sha[:12]}...)")

    # 6. Generate gold_mapping.json
    print(f"Generating gold mapping against {len(chunks_by_variant)} variants...")
    queries_data = json.loads((REPO_ROOT / "docs/search_eval_queries.json").read_bytes())
    queries = queries_data["queries"]

    # Pre-cache evidence char ranges
    for q in queries:
        for ev in q.get("evidence", []):
            sp = ev["source_path"]
            orig_text, _ = get_source_text(
                SourceSegment(
                    doc_id=ev["doc_id"],
                    source_path=sp,
                    source_file_sha256=ev["source_file_sha256"],
                    json_pointer=ev.get("json_pointer"),
                    char_start=0,
                    char_end=0,
                    byte_start=0,
                    byte_end=0,
                    content_char_start=0,
                    content_char_end=0,
                    target_url=ev["target_url"],
                    segment_sha256="",
                )
            )
            c_st, c_ed = get_evidence_char_range(ev, orig_text)
            ev["_char_start"] = c_st
            ev["_char_end"] = c_ed

    gold_mapping_entries: List[Dict[str, Any]] = []

    for q in queries:
        qid = q["query_id"]
        q_src_type = q["source_type"]
        q_entry: Dict[str, Any] = {
            "query_id": qid,
            "source_type": q_src_type,
            "difficulty": q["difficulty"],
            "evidence_mappings": [],
        }

        for ev in q.get("evidence", []):
            ev_role = ev["role"]
            ev_char_range = (ev["_char_start"], ev["_char_end"])
            ev_item: Dict[str, Any] = {
                "doc_id": ev["doc_id"],
                "source_path": ev["source_path"],
                "role": ev_role,
                "text_span": ev["text_span"],
                "rules": {},
            }

            # Map across each variant
            for variant_id, c_list in chunks_by_variant.items():
                if (variant_id.startswith("R-") and q_src_type != "rawpedia") or (
                    variant_id.startswith("G-") and q_src_type != "github"
                ):
                    continue

                relevant_chunks = []
                for c in c_list:
                    cov = calculate_evidence_chunk_coverage(ev, c, ev_char_range)
                    if cov >= 0.5:
                        relevant_chunks.append({
                            "chunk_id": c.chunk_id,
                            "coverage": round(cov, 4),
                        })

                union_cov = calculate_evidence_chunks_union_coverage(ev, c_list, ev_char_range)
                ev_item["rules"][variant_id] = {
                    "union_coverage": round(union_cov, 4),
                    "relevant_chunks": relevant_chunks,
                }
                if round(union_cov, 2) < 0.99:
                    print(
                        f"WARNING: Incomplete union coverage {union_cov} for query {qid} under {variant_id}",
                        file=sys.stderr,
                    )

            q_entry["evidence_mappings"].append(ev_item)

        gold_mapping_entries.append(q_entry)

    gold_mapping_path = target_dir / "gold_mapping.json"
    gold_mapping_payload = {
        "schema_version": 1,
        "dataset_id": "t08-1-100-v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "relevance_threshold": 0.5,
        "queries": gold_mapping_entries,
    }
    gold_mapping_path.write_bytes(
        json.dumps(gold_mapping_payload, indent=2, ensure_ascii=False).encode("utf-8")
    )
    print(f"SUCCESS: Gold mapping saved to {gold_mapping_path}")

    return rule_manifest, gold_mapping_payload


def cmd_build(args: argparse.Namespace) -> int:
    """Build chunk datasets across the parameter grid and gold mapping."""
    manifest_path = Path(args.manifest).resolve()
    model_manifest_path = Path(args.model_manifest).resolve()
    target_dir = manifest_path.parent

    target_tokens_grid = list(getattr(args, "target_tokens_grid", [128, 192, 224]))
    overlap_tokens_grid = list(getattr(args, "overlap_tokens_grid", [0, 32, 64]))
    thread_window_tokens_grid = list(getattr(args, "thread_window_tokens_grid", [128, 192, 224]))

    rule_manifest, _ = execute_chunking_build(
        manifest_path=manifest_path,
        model_manifest_path=model_manifest_path,
        rawpedia_rules=args.rawpedia_rules,
        github_rules=args.github_rules,
        target_tokens_grid=target_tokens_grid,
        overlap_tokens_grid=overlap_tokens_grid,
        thread_window_tokens_grid=thread_window_tokens_grid,
        target_dir=target_dir,
        guard_group=getattr(args, "guard_group", None),
        physical_embedding_policy=getattr(args, "physical_embedding_policy", None),
        encoder_window_tokens=getattr(args, "encoder_window_tokens", None),
        encoder_overlap_tokens=getattr(args, "encoder_overlap_tokens", None),
        thread_embedding_policy=getattr(args, "thread_embedding_policy", None),
    )

    # Update manifest.json
    manifest_data = json.loads(manifest_path.read_bytes())
    manifest_data["chunking_rules"] = rule_manifest
    manifest_data["guard_group"] = getattr(args, "guard_group", None)
    model_data = json.loads(model_manifest_path.read_bytes())
    resolved_guards = resolve_guard_models(getattr(args, "guard_group", None), model_data.get("models", {}))
    manifest_data["guard_models"] = resolved_guards
    manifest_data["guard_models_hash"] = sha256_str(json.dumps(resolved_guards, sort_keys=True))
    manifest_data["physical_embedding_policy"] = getattr(args, "physical_embedding_policy", None)
    manifest_data["thread_embedding_policy"] = getattr(args, "thread_embedding_policy", None)
    manifest_data["encoder_window_tokens"] = getattr(args, "encoder_window_tokens", None)
    manifest_data["encoder_overlap_tokens"] = getattr(args, "encoder_overlap_tokens", None)
    manifest_data["model_manifest_path"] = str(model_manifest_path)
    manifest_data["search_grid"] = {
        "target_tokens_grid": target_tokens_grid,
        "overlap_tokens_grid": overlap_tokens_grid,
        "thread_window_tokens_grid": thread_window_tokens_grid,
        "rawpedia_variants_count": len([k for k in rule_manifest if k.startswith("R-")]),
        "github_formal_variants_count": len([k for k in rule_manifest if k.startswith("G-") and not rule_manifest[k]["is_diagnostic"]]),
        "github_diagnostic_variants_count": len([k for k in rule_manifest if rule_manifest[k]["is_diagnostic"]]),
        "total_variants_count": len(rule_manifest),
    }
    manifest_data["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.write_bytes(json.dumps(manifest_data, indent=2, ensure_ascii=False).encode("utf-8"))
    print(f"SUCCESS: Updated chunk manifest with {len(rule_manifest)} variants at {manifest_path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Validate all generated chunks, gold mapping, and optional regeneration."""
    manifest_path = Path(args.manifest).resolve()
    queries_path = Path(args.queries).resolve()
    chunks_dir = manifest_path.parent

    print("=== Step 3: Checking Generated Chunks & Regeneration ===")
    manifest_data = json.loads(manifest_path.read_bytes())
    rules_info = manifest_data.get("chunking_rules", {})
    if not rules_info:
        print("ERROR: No chunking_rules found in manifest", file=sys.stderr)
        return 1

    # 1. Verify JSONL files and hashes
    for r_name, r_info in rules_info.items():
        fpath = REPO_ROOT / r_info["file_path"]
        if not fpath.is_file():
            print(f"ERROR: Chunk file missing: {fpath}", file=sys.stderr)
            return 1
        f_bytes = fpath.read_bytes()
        actual_sha = sha256_bytes(f_bytes)
        if actual_sha != r_info["file_sha256"]:
            print(f"ERROR: Chunk file SHA mismatch for {r_name}", file=sys.stderr)
            return 1

        # Check line count
        lines = [line for line in f_bytes.decode("utf-8").splitlines() if line.strip()]
        if len(lines) != r_info["chunk_count"]:
            print(f"ERROR: Chunk count mismatch in {r_name}: expected {r_info['chunk_count']}, got {len(lines)}", file=sys.stderr)
            return 1

        expected_guard = manifest_data.get("guard_group")
        if expected_guard:
            for line in lines:
                c_dict = json.loads(line)
                c_meta = c_dict.get("metadata", {})
                c_guard = c_meta.get("guard_group")
                if c_guard != expected_guard:
                    print(f"ERROR: Chunk {c_dict.get('chunk_id')} in {r_name} has guard_group '{c_guard}', expected '{expected_guard}'", file=sys.stderr)
                    return 1

    # 2. Check gold mapping
    gold_map_file = chunks_dir / "gold_mapping.json"
    if not gold_map_file.is_file():
        print(f"ERROR: Missing {gold_map_file}", file=sys.stderr)
        return 1
    gold_map = json.loads(gold_map_file.read_bytes())
    if len(gold_map.get("queries", [])) != 100:
        print(f"ERROR: Expected 100 queries in gold mapping, got {len(gold_map.get('queries', []))}", file=sys.stderr)
        return 1

    # 3. Optional regeneration verification
    if args.verify_regeneration:
        import tempfile
        print(f"Verifying deterministic regeneration across all {len(rules_info)} variants in temporary directory...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_target = Path(tmpdir)
            grid_info = manifest_data.get("search_grid", {})
            t_grid = grid_info.get("target_tokens_grid", [128, 192, 224])
            o_grid = grid_info.get("overlap_tokens_grid", [0, 32, 64])
            w_grid = grid_info.get("thread_window_tokens_grid", [128, 192, 224])
            g_group = manifest_data.get("guard_group")
            p_policy = manifest_data.get("physical_embedding_policy")
            t_policy = manifest_data.get("thread_embedding_policy")
            enc_w = manifest_data.get("encoder_window_tokens")
            enc_o = manifest_data.get("encoder_overlap_tokens")

            model_manifest_path = None
            if manifest_data.get("model_manifest_path") and Path(manifest_data["model_manifest_path"]).is_file():
                model_manifest_path = Path(manifest_data["model_manifest_path"])
            elif (manifest_path.parent / "environment.json").is_file():
                model_manifest_path = manifest_path.parent / "environment.json"
            elif (REPO_ROOT / "data/embedding-benchmark/t08-2/grid-001/environment.json").is_file():
                model_manifest_path = REPO_ROOT / "data/embedding-benchmark/t08-2/grid-001/environment.json"
            else:
                model_manifest_path = REPO_ROOT / "data/embedding-benchmark/t08-2/run-001/environment.json"
            r_rules = list(dict.fromkeys(r.get("rule_family") for r in rules_info.values() if r["rule_id"].startswith("R-")))
            g_rules = list(dict.fromkeys(r.get("rule_family") for r in rules_info.values() if r["rule_id"].startswith("G-")))
            if not r_rules:
                r_rules = ["R-A-heading", "R-B-window"]
            if not g_rules:
                g_rules = ["G-A-full-thread", "G-A-curated-thread", "G-B-curated-unit"]

            regen_manifest, _ = execute_chunking_build(
                manifest_path=manifest_path,
                model_manifest_path=model_manifest_path,
                rawpedia_rules=r_rules,
                github_rules=g_rules,
                target_tokens_grid=t_grid,
                overlap_tokens_grid=o_grid,
                thread_window_tokens_grid=w_grid,
                target_dir=tmp_target,
                guard_group=g_group,
                physical_embedding_policy=p_policy,
                encoder_window_tokens=enc_w,
                encoder_overlap_tokens=enc_o,
                thread_embedding_policy=t_policy,
            )
            for r_name, r_info in rules_info.items():
                orig_file = REPO_ROOT / r_info["file_path"]
                regen_file = tmp_target / ("rawpedia" if r_name.startswith("R-") else "github") / f"{r_name}.jsonl"
                orig_bytes = orig_file.read_bytes()
                regen_bytes = regen_file.read_bytes()
                if orig_bytes != regen_bytes:
                    print(f"ERROR: Byte mismatch in regenerated chunk file {r_name}!", file=sys.stderr)
                    return 1
                print(f"  Regeneration MATCH for {r_name} ({len(orig_bytes)} bytes)")

    print("SUCCESS: All chunk checks passed!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Corpus chunking and provenance verification CLI.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # prepare subcommand
    prep = subparsers.add_parser("prepare", help="Verify input files and freeze t08-2 chunking manifest.")
    prep.add_argument("--rawpedia-dir", default="data/rawpedia", help="Path to rawpedia markdown directory.")
    prep.add_argument("--rawpedia-collection", default="docs/rawpedia_collection.md", help="Path to rawpedia collection markdown.")
    prep.add_argument("--github-candidates", default="data/issues/search-candidates.json", help="Path to github search-candidates.json.")
    prep.add_argument("--github-dir", default="data/issues", help="Path to data/issues directory.")
    prep.add_argument("--source-manifest", default="docs/search_eval_source_manifest.json", help="Path to source manifest.")
    prep.add_argument("--queries", default="docs/search_eval_queries.json", help="Path to evaluation queries.")
    prep.add_argument("--baseline-md", default="docs/chunking_embedding_benchmark.md", help="Path to baseline markdown.")
    prep.add_argument("--baseline-json", default="docs/chunking_embedding_benchmark.json", help="Path to baseline json.")
    prep.add_argument("--baseline-prefix", default=None, help="Prefix for preserved baseline files.")
    prep.add_argument("--output-dir", default="data/chunks/t08-2-grid", help="Output directory for chunks and manifest.")
    prep.set_defaults(func=cmd_prepare)

    # build subcommand
    bld = subparsers.add_parser("build", help="Build chunk candidates across grid.")
    bld.add_argument("--manifest", required=True, help="Path to chunk manifest.")
    bld.add_argument("--model-manifest", required=True, help="Path to environment.json.")
    bld.add_argument("--rawpedia-rules", nargs="+", default=["R-A-heading", "R-B-window"], help="RawPedia chunking rules.")
    bld.add_argument("--github-rules", nargs="+", default=["G-A-full-thread", "G-A-curated-thread", "G-B-curated-unit"], help="GitHub chunking rules.")
    bld.add_argument("--target-tokens-grid", nargs="+", type=int, default=[128, 192, 224], help="Target reference tokens grid.")
    bld.add_argument("--overlap-tokens-grid", nargs="+", type=int, default=[0, 32, 64], help="Overlap reference tokens grid.")
    bld.add_argument("--thread-window-tokens-grid", nargs="+", type=int, default=[128, 192, 224], help="Thread window reference tokens grid.")
    bld.add_argument(
        "--guard-group",
        choices=["native-common-256", "bge-512", "e5-512", "pooled-common-256"],
        default=None,
        help="Guard group for chunking build.",
    )
    bld.add_argument("--physical-embedding-policy", choices=["direct_native_v1", "direct_native_v2", "direct_native_v3", "chunk_window_mean_v1", "chunk_window_mean_v2"], default=None, help="Physical embedding policy.")
    bld.add_argument("--thread-embedding-policy", choices=["thread_window_mean_v1", "thread_window_mean_v2", "thread_window_mean_v3"], default=None, help="Thread embedding policy.")
    bld.add_argument("--encoder-window-tokens", type=int, default=None, help="Encoder window tokens.")
    bld.add_argument("--encoder-overlap-tokens", type=int, default=None, help="Encoder overlap tokens.")
    bld.set_defaults(func=cmd_build)

    # check subcommand
    chk = subparsers.add_parser("check", help="Verify generated chunks and regeneration.")
    chk.add_argument("--manifest", required=True, help="Path to chunk manifest.")
    chk.add_argument("--queries", default="docs/search_eval_queries.json", help="Path to evaluation queries.")
    chk.add_argument("--verify-regeneration", action="store_true", help="Verify byte-for-byte regeneration.")
    chk.set_defaults(func=cmd_check)

    parsed = parser.parse_args()
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main() or 0)
