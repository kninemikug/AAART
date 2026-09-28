"""Unit tests for chunking schema, deterministic IDs, provenance validation, and gold coverage."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import pytest

from src.artagent.chunking import (
    CHUNK_SCHEMA_VERSION,
    Chunk,
    SourceSegment,
    calculate_evidence_chunk_coverage,
    calculate_evidence_chunks_union_coverage,
    compute_chunk_id,
    get_evidence_char_range,
    sha256_bytes,
    sha256_str,
    validate_chunk_provenance,
)


def test_chunk_id_determinism():
    """Ensure chunk ID computation is deterministic and canonical."""
    seg = SourceSegment(
        doc_id="rawpedia:Exposure",
        source_path="data/rawpedia/Exposure.md",
        source_file_sha256="abc123def",
        json_pointer=None,
        char_start=10,
        char_end=50,
        byte_start=10,
        byte_end=50,
        content_char_start=0,
        content_char_end=40,
        target_url="https://example.com/exposure",
        segment_sha256=sha256_str("Hello World! This is a test segment text."),
    )
    content = "Hello World! This is a test segment text."
    cid1 = compute_chunk_id(
        schema_version=CHUNK_SCHEMA_VERSION,
        rule_fingerprint="R-A-heading:v1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_segments=[seg],
        content_sha256=sha256_str(content),
    )
    cid2 = compute_chunk_id(
        schema_version=CHUNK_SCHEMA_VERSION,
        rule_fingerprint="R-A-heading:v1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_segments=[seg],
        content_sha256=sha256_str(content),
    )
    assert cid1 == cid2
    assert cid1.startswith("t08c:v1:rawpedia:R-A-heading:")


def test_validate_chunk_provenance_and_tampering():
    """Verify that provenance validation accepts valid chunks and rejects tampering."""
    doc_text = "Line 1: Introduction\nLine 2: Important detail about Exposure.\nLine 3: End."
    file_sha = sha256_str(doc_text)

    # Slice "Important detail about Exposure."
    target_str = "Important detail about Exposure."
    char_start = doc_text.index(target_str)
    char_end = char_start + len(target_str)
    byte_start = len(doc_text[:char_start].encode("utf-8"))
    byte_end = len(doc_text[:char_end].encode("utf-8"))

    seg = SourceSegment(
        doc_id="rawpedia:Exposure",
        source_path="data/rawpedia/Exposure.md",
        source_file_sha256=file_sha,
        json_pointer=None,
        char_start=char_start,
        char_end=char_end,
        byte_start=byte_start,
        byte_end=byte_end,
        content_char_start=0,
        content_char_end=len(target_str),
        target_url="https://example.com/exposure",
        segment_sha256=sha256_str(target_str),
    )

    metadata = {
        "content_sha256": sha256_str(target_str),
        "range_basis": "source_file",
        "source_segments": [seg.to_dict()],
    }

    chunk = Chunk(
        chunk_id="test-chunk-1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        section_title="Exposure",
        content=target_str,
        char_range=(char_start, char_end),
        metadata=metadata,
    )

    def dummy_source_getter(s: SourceSegment):
        return doc_text, file_sha

    # 1. Valid passes
    validate_chunk_provenance(chunk, dummy_source_getter)

    # 2. Tampered content fails
    tampered_chunk = Chunk(
        chunk_id="test-chunk-1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        section_title="Exposure",
        content=target_str + "!",
        char_range=(char_start, char_end),
        metadata=metadata,
    )
    with pytest.raises(ValueError, match="content SHA256 mismatch"):
        validate_chunk_provenance(tampered_chunk, dummy_source_getter)

    # 3. Tampered segment offset fails
    bad_seg = dataclasses.replace(seg, byte_start=byte_start + 1)
    bad_meta = {
        "content_sha256": sha256_str(target_str),
        "range_basis": "source_file",
        "source_segments": [bad_seg.to_dict()],
    }
    bad_chunk = Chunk(
        chunk_id="test-chunk-1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        section_title="Exposure",
        content=target_str,
        char_range=(char_start, char_end),
        metadata=bad_meta,
    )
    with pytest.raises(ValueError, match="byte offset mismatch"):
        validate_chunk_provenance(bad_chunk, dummy_source_getter)


def test_evidence_coverage_single_chunk():
    """Verify single chunk evidence coverage calculation with 50% relevance threshold."""
    doc_text = "ABCDEFGHIJ 1234567890"
    file_sha = sha256_str(doc_text)

    # Evidence span: "ABCDEFGHIJ" (10 non-ws chars)
    ev = {
        "source_path": "data/test.md",
        "json_pointer": None,
        "doc_id": "test:doc1",
        "char_start": 0,
        "char_end": 10,
        "text_span": "ABCDEFGHIJ",
    }

    # Chunk covers first 4 chars: "ABCD" (40% coverage < 50%)
    seg_40 = SourceSegment(
        doc_id="test:doc1",
        source_path="data/test.md",
        source_file_sha256=file_sha,
        json_pointer=None,
        char_start=0,
        char_end=4,
        byte_start=0,
        byte_end=4,
        content_char_start=0,
        content_char_end=4,
        target_url="https://test",
        segment_sha256=sha256_str("ABCD"),
    )
    chunk_40 = Chunk(
        chunk_id="c40",
        source_type="rawpedia",
        doc_id="test:doc1",
        section_title="test",
        content="ABCD",
        char_range=(0, 4),
        metadata={"source_segments": [seg_40.to_dict()]},
    )
    cov_40 = calculate_evidence_chunk_coverage(ev, chunk_40)
    assert cov_40 == pytest.approx(0.4)
    assert cov_40 < 0.5  # Not relevant

    # Chunk covers first 6 chars: "ABCDEF" (60% coverage >= 50%)
    seg_60 = dataclasses.replace(
        seg_40,
        char_end=6,
        byte_end=6,
        content_char_end=6,
        segment_sha256=sha256_str("ABCDEF"),
    )
    chunk_60 = Chunk(
        chunk_id="c60",
        source_type="rawpedia",
        doc_id="test:doc1",
        section_title="test",
        content="ABCDEF",
        char_range=(0, 6),
        metadata={"source_segments": [seg_60.to_dict()]},
    )
    cov_60 = calculate_evidence_chunk_coverage(ev, chunk_60)
    assert cov_60 == pytest.approx(0.6)
    assert cov_60 >= 0.5  # Relevant


def test_evidence_coverage_union_chunks():
    """Verify union coverage across multiple chunks without double-counting overlaps."""
    # Evidence: "0123456789" (10 chars)
    ev = {
        "source_path": "data/test.md",
        "json_pointer": None,
        "doc_id": "test:doc1",
        "char_start": 0,
        "char_end": 10,
        "text_span": "0123456789",
    }

    # Chunk 1: [0, 6) -> "012345"
    # Chunk 2: [4, 10) -> "456789" (overlap at [4, 6))
    seg1 = SourceSegment(
        doc_id="test:doc1",
        source_path="data/test.md",
        source_file_sha256="dummy",
        json_pointer=None,
        char_start=0,
        char_end=6,
        byte_start=0,
        byte_end=6,
        content_char_start=0,
        content_char_end=6,
        target_url="https://test",
        segment_sha256="dummy",
    )
    c1 = Chunk("c1", "rawpedia", "test:doc1", "t", "012345", (0, 6), {"source_segments": [seg1.to_dict()]})

    seg2 = SourceSegment(
        doc_id="test:doc1",
        source_path="data/test.md",
        source_file_sha256="dummy",
        json_pointer=None,
        char_start=4,
        char_end=10,
        byte_start=4,
        byte_end=10,
        content_char_start=0,
        content_char_end=6,
        target_url="https://test",
        segment_sha256="dummy",
    )
    c2 = Chunk("c2", "rawpedia", "test:doc1", "t", "456789", (4, 10), {"source_segments": [seg2.to_dict()]})

    # Individual coverages are 0.6 each
    assert calculate_evidence_chunk_coverage(ev, c1) == pytest.approx(0.6)
    assert calculate_evidence_chunk_coverage(ev, c2) == pytest.approx(0.6)

    # Union coverage should be 1.0 (no double count)
    union_cov = calculate_evidence_chunks_union_coverage(ev, [c1, c2])
    assert union_cov == pytest.approx(1.0)


def test_crlf_and_korean_unicode():
    """Verify handling of CRLF and multibyte Korean text."""
    body_text = "첫 번째 줄\r\n두 번째 줄: 가나다라\r\n세 번째 줄: 끝"
    # "가나다라"
    target = "가나다라"
    c_start = body_text.index(target)
    c_end = c_start + len(target)

    body_bytes = body_text.encode("utf-8")
    b_start = len(body_text[:c_start].encode("utf-8"))
    b_end = len(body_text[:c_end].encode("utf-8"))

    ev = {
        "source_path": "data/issues/snapshots/test.json",
        "json_pointer": "/body",
        "doc_id": "issue:123",
        "ref_id": "issue:123",
        "char_start": c_start,
        "char_end": c_end,
        "byte_start": b_start,
        "byte_end": b_end,
        "text_span": target,
    }

    seg = SourceSegment(
        doc_id="issue:123",
        source_path="data/issues/snapshots/test.json",
        source_file_sha256="dummy",
        json_pointer="/body",
        char_start=c_start,
        char_end=c_end,
        byte_start=b_start,
        byte_end=b_end,
        content_char_start=0,
        content_char_end=len(target),
        target_url="https://github.com/test",
        segment_sha256=sha256_str(target),
        ref_id="issue:123",
    )
    chunk = Chunk("c-kr", "github", "issue:123", "/body", target, (c_start, c_end), {"source_segments": [seg.to_dict()]})

    cov = calculate_evidence_chunk_coverage(ev, chunk)
    assert cov == pytest.approx(1.0)
