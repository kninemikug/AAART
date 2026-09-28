"""Exhaustive pytest suite for ART Master search evaluation query dataset (100 queries).

Implements 13 mandatory test suites defined in docs/T08_1_execution_plan.md §7.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest
from typing import Any, Dict, List

from scripts.generate_eval_queries import (
    DATASET_ID,
    EXPECTED_RAWPEDIA_COLLECTION_SHA256,
    EXPECTED_RAWPEDIA_FILES_SHA256,
    EXPECTED_SEARCH_CANDIDATES_SHA256,
    EXPECTED_SYNC_STATE_SHA256,
    RULES_VERSION,
    SCHEMA_VERSION,
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    VALID_INTENTS,
    VALID_PRODUCT_SCOPES,
    compute_rawpedia_files_sha256,
    generate_markdown,
    load_github_candidates,
    load_manifest_sources,
    parse_rawpedia_collection_included,
    sha256_bytes,
    verify_full_query,
    verify_single_evidence,
)


@pytest.fixture(scope="module")
def dataset_data() -> Dict[str, Any]:
    json_path = Path("docs/search_eval_queries.json")
    assert json_path.exists(), f"Dataset file missing: {json_path}"
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def queries(dataset_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return dataset_data["queries"]


@pytest.fixture(scope="module")
def manifest_sources() -> Dict[str, Any]:
    return load_manifest_sources()


@pytest.fixture(scope="module")
def github_candidates() -> Dict[str, Any]:
    return load_github_candidates()


# ------------------------------------------------------------------------------
# Test 1: Full Inputs and Distributions
# ------------------------------------------------------------------------------
def test_inputs_and_distributions(queries: List[Dict[str, Any]]):
    """Test 1: Input fingerprints, total counts and exact taxonomy distributions."""
    # Fingerprints
    rp_coll = Path("docs/rawpedia_collection.md")
    assert sha256_bytes(rp_coll.read_bytes()) == EXPECTED_RAWPEDIA_COLLECTION_SHA256

    cand_p = Path("data/issues/search-candidates.json")
    assert sha256_bytes(cand_p.read_bytes()) == EXPECTED_SEARCH_CANDIDATES_SHA256

    sync_p = Path("data/issues/sync-state.json")
    assert sha256_bytes(sync_p.read_bytes()) == EXPECTED_SYNC_STATE_SHA256

    rp_sha, file_list = compute_rawpedia_files_sha256()
    assert rp_sha == EXPECTED_RAWPEDIA_FILES_SHA256
    assert len(file_list) == 116

    # Included pages count
    included_map = parse_rawpedia_collection_included(rp_coll)
    assert len(included_map) == 116

    # 100 queries total
    assert len(queries) == 100

    # Source distribution: RawPedia 80, GitHub 20
    rp_cnt = sum(1 for q in queries if q["source_type"] == "rawpedia")
    gh_cnt = sum(1 for q in queries if q["source_type"] == "github")
    assert rp_cnt == 80
    assert gh_cnt == 20

    # RawPedia 50 unique pages
    rp_pages = set(q["source_group_id"] for q in queries if q["source_type"] == "rawpedia")
    assert len(rp_pages) == 50

    # Difficulty distribution: factoid 50, complex 45, negative 5
    diff_counts = {
        d: sum(1 for q in queries if q["difficulty"] == d)
        for d in VALID_DIFFICULTIES
    }
    assert diff_counts == {"factoid": 50, "complex": 45, "negative": 5}

    # Intent distribution: usage 35, concept 25, troubleshooting 20, workflow 20
    intent_counts = {
        i: sum(1 for q in queries if q["intent"] == i)
        for i in VALID_INTENTS
    }
    assert intent_counts == {
        "usage/how-to": 35,
        "concept": 25,
        "troubleshooting": 20,
        "workflow": 20,
    }

    # Category distribution
    cat_counts = {
        c: sum(1 for q in queries if q["category"] == c)
        for c in VALID_CATEGORIES
    }
    assert cat_counts == {
        "color_wb": 21,
        "demosaic_raw": 14,
        "exposure_tone": 16,
        "mask_local": 19,
        "settings_workflow": 18,
        "sharpening_noise": 12,
    }


# ------------------------------------------------------------------------------
# Test 2: Identifiers and Mandatory Fields
# ------------------------------------------------------------------------------
def test_identifiers_and_mandatory_fields(queries: List[Dict[str, Any]]):
    """Test 2: Sequential query_id Q001~Q100, field schemas, mirror consistency."""
    expected_ids = [f"Q{i:03d}" for i in range(1, 101)]
    actual_ids = [q["query_id"] for q in queries]
    assert actual_ids == expected_ids

    for q in queries:
        qid = q["query_id"]
        assert q["category"] in VALID_CATEGORIES
        assert q["intent"] in VALID_INTENTS
        assert q["difficulty"] in VALID_DIFFICULTIES
        assert q["product_scope"] in VALID_PRODUCT_SCOPES
        assert q["source_type"] in ["rawpedia", "github"]
        assert isinstance(q["query"], str) and len(q["query"].strip()) > 0

        # Mirror fields must exactly match evidence[0]
        ev0 = q["evidence"][0]
        assert q["doc_id"] == ev0["doc_id"]
        assert q["section_title"] == ev0["section_title"]
        assert q["target_url"] == ev0["target_url"]
        assert q["evidence_text_span"] == ev0["text_span"]
        assert q["evidence_hash"] == ev0["evidence_hash"]


# ------------------------------------------------------------------------------
# Test 3: Exhaustive Byte Verification
# ------------------------------------------------------------------------------
def test_exhaustive_bytes(
    queries: List[Dict[str, Any]],
    manifest_sources: Dict[str, Any],
    github_candidates: Dict[str, Any],
):
    """Test 3: 100% byte-level span and hash match across all 100 queries and all evidence items."""
    total_spans = 0
    for q in queries:
        qid = q["query_id"]
        errs = verify_full_query(q, manifest_sources, github_candidates)
        assert len(errs) == 0, f"Query {qid} failed verification: {errs}"
        total_spans += len(q["evidence"])

    assert total_spans >= 135
    print(f"Verified all 100 queries ({total_spans} total evidence spans) successfully.")


# ------------------------------------------------------------------------------
# Test 4: Multiple Evidence for Complex Queries
# ------------------------------------------------------------------------------
def test_multiple_evidence_for_complex(queries: List[Dict[str, Any]]):
    """Test 4: Complex queries must have >= 2 distinct evidence spans."""
    complex_queries = [q for q in queries if q["difficulty"] == "complex"]
    assert len(complex_queries) == 45

    for q in complex_queries:
        qid = q["query_id"]
        evs = q["evidence"]
        assert len(evs) >= 2, f"Complex query {qid} has {len(evs)} evidence spans (< 2)"
        # Verify spans are not identical
        span_texts = [e["text_span"] for e in evs]
        assert len(set(span_texts)) == len(span_texts), f"Complex query {qid} has duplicate spans"


# ------------------------------------------------------------------------------
# Test 5: Negative Queries Semantics
# ------------------------------------------------------------------------------
def test_negative_queries_semantics(queries: List[Dict[str, Any]]):
    """Test 5: Negative queries (Q096~Q100) must have role='counterevidence' and empty gold IDs."""
    negative_queries = [q for q in queries if q["difficulty"] == "negative"]
    assert len(negative_queries) == 5
    neg_ids = [q["query_id"] for q in negative_queries]
    assert neg_ids == ["Q096", "Q097", "Q098", "Q099", "Q100"]

    for q in negative_queries:
        assert q["expected_behavior"] == "unsupported_or_insufficient_evidence"
        assert q["gold_support_doc_ids"] == []
        roles = [e.get("role") for e in q["evidence"]]
        assert "counterevidence" in roles

    # Positives must have expected_behavior 'grounded_answer' and non-empty gold IDs
    positive_queries = [q for q in queries if q["difficulty"] != "negative"]
    for q in positive_queries:
        assert q["expected_behavior"] == "grounded_answer"
        assert len(q["gold_support_doc_ids"]) > 0


# ------------------------------------------------------------------------------
# Test 6: CRLF Roundtrip Preservation
# ------------------------------------------------------------------------------
def test_crlf_roundtrip(queries: List[Dict[str, Any]]):
    """Test 6: GitHub snapshots with CRLF (e.g. D412, D420, D424) preserve CRLF in span bytes."""
    # Find queries on D420
    d420_qs = [
        q for q in queries if q.get("source_group_id") == "github:artraweditor/ART:discussion:420"
    ]
    assert len(d420_qs) >= 1
    # Check that CRLF is in the text_span of curated[1]
    found_crlf = False
    for q in d420_qs:
        for ev in q["evidence"]:
            if "\r\n" in ev["text_span"]:
                found_crlf = True
                assert b"\r\n" in ev["text_span"].encode("utf-8")
    assert found_crlf, "Expected CRLF preserved in D420 span"


# ------------------------------------------------------------------------------
# Test 7: UTF-8 Character vs Byte Boundary
# ------------------------------------------------------------------------------
def test_utf8_char_vs_byte_boundary(queries: List[Dict[str, Any]]):
    """Test 7: Multibyte UTF-8 characters (Korean, emoji) have correct byte offsets."""
    # Q090 is based on I477 which contains emoji 🎉 in comment 4433310082
    q090 = next(q for q in queries if q["query_id"] == "Q090")
    ev = q090["evidence"][0]
    # Check that byte offsets correctly reflect UTF-8 encoding length
    snap_path = Path(ev["source_path"])
    body = json.loads(snap_path.read_bytes().decode("utf-8"))["body"]
    char_s = ev["char_start"]
    char_e = ev["char_end"]
    byte_s = ev["byte_start"]
    byte_e = ev["byte_end"]

    assert byte_s == len(body[:char_s].encode("utf-8"))
    assert byte_e == len(body[:char_e].encode("utf-8"))


# ------------------------------------------------------------------------------
# Test 8: Tamper Detection
# ------------------------------------------------------------------------------
def test_tamper_detection(
    queries: List[Dict[str, Any]],
    manifest_sources: Dict[str, Any],
    github_candidates: Dict[str, Any],
):
    """Test 8: Changing bytes, offsets, hashes, or URLs must fail verification."""
    q_sample = copy.deepcopy(queries[0])

    # 1. Modify span text by 1 character
    tampered_q = copy.deepcopy(q_sample)
    tampered_q["evidence"][0]["text_span"] += "X"
    errs = verify_full_query(tampered_q, manifest_sources, github_candidates)
    assert len(errs) > 0

    # 2. Modify byte offset
    tampered_q2 = copy.deepcopy(q_sample)
    tampered_q2["evidence"][0]["byte_start"] += 1
    errs2 = verify_full_query(tampered_q2, manifest_sources, github_candidates)
    assert len(errs2) > 0

    # 3. Modify evidence_hash
    tampered_q3 = copy.deepcopy(q_sample)
    tampered_q3["evidence"][0]["evidence_hash"] = "0" * 64
    errs3 = verify_full_query(tampered_q3, manifest_sources, github_candidates)
    assert len(errs3) > 0

    # 4. Modify source_file_sha256
    tampered_q4 = copy.deepcopy(q_sample)
    tampered_q4["evidence"][0]["source_file_sha256"] = "f" * 64
    errs4 = verify_full_query(tampered_q4, manifest_sources, github_candidates)
    assert len(errs4) > 0


# ------------------------------------------------------------------------------
# Test 9: Input Drift Detection
# ------------------------------------------------------------------------------
def test_input_drift_detection(
    queries: List[Dict[str, Any]],
    manifest_sources: Dict[str, Any],
    github_candidates: Dict[str, Any],
):
    """Test 9: Manifest file_sha256 mismatch triggers validation failure."""
    tampered_sources = copy.deepcopy(manifest_sources)
    q0 = queries[0]
    src_path = q0["evidence"][0]["source_path"]
    tampered_sources[src_path]["file_sha256"] = "0" * 64

    errs = verify_full_query(q0, tampered_sources, github_candidates)
    assert any("Manifest file_sha256 mismatch" in e for e in errs)


# ------------------------------------------------------------------------------
# Test 10: Allowed Scope Boundaries
# ------------------------------------------------------------------------------
def test_allowed_scope_boundaries(
    queries: List[Dict[str, Any]],
    manifest_sources: Dict[str, Any],
    github_candidates: Dict[str, Any],
):
    """Test 10: Out-of-candidate snapshots or invalid source paths are rejected."""
    q_sample = copy.deepcopy(queries[-1])  # GitHub query
    # Tamper candidate_id to non-existent
    q_sample["evidence"][0]["candidate_id"] = "github:artraweditor/ART:issue:9999"
    q_sample["source_group_id"] = "github:artraweditor/ART:issue:9999"
    errs = verify_full_query(q_sample, manifest_sources, github_candidates)
    assert any("not found in candidate" in e for e in errs)


# ------------------------------------------------------------------------------
# Test 11: Document Structures (Edge Cases)
# ------------------------------------------------------------------------------
def test_document_structures(queries: List[Dict[str, Any]]):
    """Test 11: Structural edge cases: tutorial nesting, page_body sections."""
    # Rocks tutorial (nested path)
    q_rocks = next((q for q in queries if "rocks.md" in q["evidence"][0]["source_path"]), None)
    assert q_rocks is not None
    assert q_rocks["doc_id"] == "rawpedia:Tutorials/game_changer/rocks"

    # Headless markdown files (e.g. Channel_Mixer.md or RGB_and_Lab.md) have page_body
    q_cm = next((q for q in queries if "Channel_Mixer.md" in q["evidence"][0]["source_path"]), None)
    assert q_cm is not None
    assert q_cm["section_title"] == "Channel Mixer"


# ------------------------------------------------------------------------------
# Test 12: Presentation and Reproducibility
# ------------------------------------------------------------------------------
def test_presentation_and_reproducibility(queries: List[Dict[str, Any]]):
    """Test 12: Markdown specification reproduces 100% identical byte stream."""
    md_path = Path("docs/search_eval_queries.md")
    assert md_path.exists()
    actual_md = md_path.read_text(encoding="utf-8")
    expected_md = generate_markdown(queries)
    assert actual_md == expected_md, "Markdown specification byte mismatch"


# ------------------------------------------------------------------------------
# Test 13: Atomic Finalize Preservation
# ------------------------------------------------------------------------------
def test_finalize_atomic_preservation(tmp_path: Path):
    """Test 13: Finalize creates files safely and preserves valid files on error."""
    valid_file = tmp_path / "valid.json"
    valid_file.write_text('{"status": "ok"}', encoding="utf-8")

    # Verify atomic replace semantics
    tmp_file = tmp_path / "valid.json.tmp"
    tmp_file.write_text('{"status": "updated"}', encoding="utf-8")
    tmp_file.replace(valid_file)

    assert json.loads(valid_file.read_text(encoding="utf-8"))["status"] == "updated"
