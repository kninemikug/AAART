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
    Chunk,
    SourceSegment,
    calculate_evidence_chunk_coverage,
    calculate_evidence_chunks_union_coverage,
    canonical_json_bytes,
    compute_chunk_id,
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

    # 4. Save data/chunks/t08-2/manifest.json
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
    return 0


def execute_chunking_build(
    manifest_path: Path,
    model_manifest_path: Path,
    rawpedia_rules: List[str],
    github_rules: List[str],
    target_tokens: int,
    overlap_tokens: int,
    target_dir: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Core logic to build chunks and compute gold mapping."""
    from transformers import AutoTokenizer
    from src.artagent.chunking import (
        TokenizerBundle,
        chunk_rawpedia_heading_rule,
        chunk_rawpedia_window_rule,
        chunk_github_curated_unit_rule,
        chunk_github_thread_rule,
        get_evidence_char_range,
    )

    manifest_data = json.loads(manifest_path.read_bytes())
    model_data = json.loads(model_manifest_path.read_bytes())

    # 1. Initialize TokenizerBundle
    print("Loading tokenizers for chunking build...")
    bge_tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION)
    candidate_toks = {}
    for m_id, m_info in model_data.get("models", {}).items():
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

    chunks_by_rule: Dict[str, List[Chunk]] = {}
    rule_manifest: Dict[str, Any] = {}

    # Build RawPedia rules
    for r_rule in rawpedia_rules:
        print(f"Building chunks for {r_rule}...")
        rule_chunks: List[Chunk] = []
        for rf in rawpedia_files:
            rel_p = rf.relative_to(REPO_ROOT).as_posix()
            info = rawpedia_info[rel_p]
            doc_id = info["doc_id"]
            page_url = info["page_url"]
            b = rf.read_bytes()
            if r_rule == "R-A-heading":
                c_list = chunk_rawpedia_heading_rule(
                    rel_p, b, doc_id, page_url, tokenizer_bundle, target_tokens, overlap_tokens
                )
            elif r_rule == "R-B-window":
                c_list = chunk_rawpedia_window_rule(
                    rel_p, b, doc_id, page_url, tokenizer_bundle, target_tokens, overlap_tokens
                )
            else:
                raise ValueError(f"Unknown RawPedia rule {r_rule}")

            for c in c_list:
                validate_chunk_provenance(c, get_source_text)
            rule_chunks.extend(c_list)

        chunks_by_rule[r_rule] = rule_chunks

    # Build GitHub rules
    for g_rule in github_rules:
        print(f"Building chunks for {g_rule}...")
        rule_chunks = []
        for cand in candidates:
            if g_rule == "G-B-curated-unit":
                c_list = chunk_github_curated_unit_rule(
                    cand, github_dir, tokenizer_bundle, target_tokens, overlap_tokens
                )
                for c in c_list:
                    validate_chunk_provenance(c, get_source_text)
                rule_chunks.extend(c_list)
            elif g_rule == "G-A-curated-thread":
                c_th = chunk_github_thread_rule(
                    cand, github_dir, tokenizer_bundle, curated_only=True, target_tokens=target_tokens
                )
                validate_chunk_provenance(c_th, get_source_text)
                rule_chunks.append(c_th)
            elif g_rule == "G-A-full-thread":
                th_obj = threads_by_key[cand["source_record_key"]]
                c_th = chunk_github_thread_rule(
                    cand, github_dir, tokenizer_bundle, curated_only=False, thread_obj=th_obj, target_tokens=target_tokens
                )
                validate_chunk_provenance(c_th, get_source_text)
                rule_chunks.append(c_th)
            else:
                raise ValueError(f"Unknown GitHub rule {g_rule}")

        chunks_by_rule[g_rule] = rule_chunks

    # 5. Save JSONL files and write metadata
    for rule_name, c_list in chunks_by_rule.items():
        if rule_name.startswith("R-"):
            out_subdir = target_dir / "rawpedia"
        else:
            out_subdir = target_dir / "github"
        out_subdir.mkdir(parents=True, exist_ok=True)
        jsonl_path = out_subdir / f"{rule_name}.jsonl"

        lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in c_list]
        file_bytes = ("\n".join(lines) + "\n").encode("utf-8")
        jsonl_path.write_bytes(file_bytes)
        file_sha = sha256_bytes(file_bytes)
        try:
            rel_file_path = jsonl_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_file_path = str(jsonl_path)
        rule_manifest[rule_name] = {
            "rule_id": rule_name,
            "chunk_count": len(c_list),
            "file_path": rel_file_path,
            "file_sha256": file_sha,
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
        }
        print(f"  {rule_name}: {len(c_list)} chunks -> {jsonl_path} ({file_sha[:12]}...)")

    # 6. Generate gold_mapping.json
    print("Generating gold mapping against all rules...")
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

            # Map across each rule
            for rule_name, c_list in chunks_by_rule.items():
                # Check if rule matches source type
                if (rule_name.startswith("R-") and q_src_type != "rawpedia") or (
                    rule_name.startswith("G-") and q_src_type != "github"
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
                ev_item["rules"][rule_name] = {
                    "union_coverage": round(union_cov, 4),
                    "relevant_chunks": relevant_chunks,
                }
                # Sanity: union coverage must be 1.0 (all evidence covered)
                if round(union_cov, 2) < 0.99:
                    print(
                        f"WARNING: Incomplete union coverage {union_cov} for query {qid} under {rule_name}",
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
    """Build chunk datasets and gold mapping."""
    manifest_path = Path(args.manifest).resolve()
    model_manifest_path = Path(args.model_manifest).resolve()
    target_dir = manifest_path.parent

    rule_manifest, _ = execute_chunking_build(
        manifest_path=manifest_path,
        model_manifest_path=model_manifest_path,
        rawpedia_rules=args.rawpedia_rules,
        github_rules=args.github_rules,
        target_tokens=args.target_tokens,
        overlap_tokens=args.overlap_tokens,
        target_dir=target_dir,
    )

    # Update manifest.json
    manifest_data = json.loads(manifest_path.read_bytes())
    manifest_data["chunking_rules"] = rule_manifest
    manifest_data["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.write_bytes(json.dumps(manifest_data, indent=2, ensure_ascii=False).encode("utf-8"))
    print(f"SUCCESS: Updated chunk manifest at {manifest_path}")
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
        print("Verifying deterministic regeneration in temporary directory...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_target = Path(tmpdir)
            model_manifest_path = REPO_ROOT / "data/embedding-benchmark/t08-2/run-001/environment.json"
            regen_manifest, _ = execute_chunking_build(
                manifest_path=manifest_path,
                model_manifest_path=model_manifest_path,
                rawpedia_rules=["R-A-heading", "R-B-window"],
                github_rules=["G-A-full-thread", "G-A-curated-thread", "G-B-curated-unit"],
                target_tokens=192,
                overlap_tokens=32,
                target_dir=tmp_target,
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
    prep.add_argument("--output-dir", default="data/chunks/t08-2", help="Output directory for chunks and manifest.")
    prep.set_defaults(func=cmd_prepare)

    # build subcommand
    bld = subparsers.add_parser("build", help="Build chunk candidates.")
    bld.add_argument("--manifest", required=True, help="Path to chunk manifest.")
    bld.add_argument("--model-manifest", required=True, help="Path to environment.json.")
    bld.add_argument("--rawpedia-rules", nargs="+", default=["R-A-heading", "R-B-window"], help="RawPedia chunking rules.")
    bld.add_argument("--github-rules", nargs="+", default=["G-A-full-thread", "G-A-curated-thread", "G-B-curated-unit"], help="GitHub chunking rules.")
    bld.add_argument("--target-tokens", type=int, default=192, help="Target reference tokens.")
    bld.add_argument("--overlap-tokens", type=int, default=32, help="Overlap reference tokens.")
    bld.set_defaults(func=cmd_build)

    # check subcommand
    chk = subparsers.add_parser("check", help="Verify generated chunks and regeneration.")
    chk.add_argument("--manifest", required=True, help="Path to chunk manifest.")
    chk.add_argument("--queries", required=True, help="Path to evaluation queries.")
    chk.add_argument("--verify-regeneration", action="store_true", help="Verify byte-for-byte regeneration.")
    chk.set_defaults(func=cmd_check)

    parsed = parser.parse_args()
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main() or 0)
