"""Document chunking and source span tracking for ART Master RAG pipeline.

Supports RawPedia Markdown and GitHub Issue/Discussion threads/comments
with exact code-point and byte-level provenance tracking according to docs/T08_2_execution_plan.md.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = 1
CHUNK_SCHEMA_VERSION = "t08c:v1"
BGE_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"

GUARD_GROUP_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "native-common-256": {
        "allowed_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
            "intfloat/multilingual-e5-small",
        },
        "exact_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
            "intfloat/multilingual-e5-small",
        },
        "expected_limits": {
            "BAAI/bge-small-en-v1.5": 512,
            "BAAI/bge-base-en-v1.5": 512,
            "sentence-transformers/all-MiniLM-L6-v2": 256,
            "intfloat/multilingual-e5-small": 512,
        },
        "allowed_physical_policies": {"direct_native_v1", "direct_native_v2", "direct_native_v3"},
    },
    "bge-512": {
        "allowed_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
        },
        "exact_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
        },
        "expected_limits": {
            "BAAI/bge-small-en-v1.5": 512,
            "BAAI/bge-base-en-v1.5": 512,
        },
        "allowed_physical_policies": {"direct_native_v1", "direct_native_v2", "direct_native_v3"},
    },
    "e5-512": {
        "allowed_models": {
            "intfloat/multilingual-e5-small",
        },
        "exact_models": {
            "intfloat/multilingual-e5-small",
        },
        "expected_limits": {
            "intfloat/multilingual-e5-small": 512,
        },
        "allowed_physical_policies": {"direct_native_v1", "direct_native_v2", "direct_native_v3"},
    },
    "pooled-common-256": {
        "allowed_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
            "intfloat/multilingual-e5-small",
        },
        "exact_models": {
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
            "intfloat/multilingual-e5-small",
        },
        "expected_limits": {
            "BAAI/bge-small-en-v1.5": 512,
            "BAAI/bge-base-en-v1.5": 512,
            "sentence-transformers/all-MiniLM-L6-v2": 256,
            "intfloat/multilingual-e5-small": 512,
        },
        "allowed_physical_policies": {"chunk_window_mean_v1", "chunk_window_mean_v2"},
    },
}


def resolve_guard_models(
    guard_group: Optional[str],
    all_models: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve and validate strict guard model manifest according to guard group contract."""
    if not guard_group:
        return all_models
    if guard_group not in GUARD_GROUP_CONTRACTS:
        raise ValueError(
            f"Unknown guard_group: '{guard_group}'. Must be one of {list(GUARD_GROUP_CONTRACTS.keys())}"
        )
    contract = GUARD_GROUP_CONTRACTS[guard_group]

    filtered = {m: dict(cfg) for m, cfg in all_models.items() if m in contract["allowed_models"]}
    missing = contract["exact_models"] - set(filtered.keys())
    if missing:
        raise ValueError(f"Guard group '{guard_group}' missing required models: {missing}")

    for m_id, expected_len in contract["expected_limits"].items():
        actual_len = filtered[m_id].get("max_seq_length", 512)
        if actual_len != expected_len:
            raise ValueError(
                f"Model {m_id} in guard group '{guard_group}' has max_seq_length={actual_len}, expected {expected_len}"
            )

    # Negative validation: bge-512 and e5-512 must NEVER contain MiniLM
    if guard_group in ("bge-512", "e5-512"):
        if "sentence-transformers/all-MiniLM-L6-v2" in filtered:
            raise ValueError(f"MiniLM (256 limit) must not be in guard group '{guard_group}'")

    return filtered



def sha256_bytes(data: bytes) -> str:
    """Compute lowercase hex SHA-256 digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_str(text: str) -> str:
    """Compute lowercase hex SHA-256 digest of UTF-8 string."""
    return sha256_bytes(text.encode("utf-8"))


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize object to deterministic canonical JSON bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass
class SourceSegment:
    """A slice of an original source file with absolute character and byte bounds."""

    doc_id: str
    source_path: str
    source_file_sha256: str
    json_pointer: Optional[str]
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int
    content_char_start: int
    content_char_end: int
    target_url: str
    segment_sha256: str
    ref_id: Optional[str] = None
    body_sha256: Optional[str] = None
    curated_content_index: Optional[int] = None
    source_role: Optional[str] = None
    curated: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "source_file_sha256": self.source_file_sha256,
            "json_pointer": self.json_pointer,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "content_char_start": self.content_char_start,
            "content_char_end": self.content_char_end,
            "target_url": self.target_url,
            "segment_sha256": self.segment_sha256,
        }
        if self.ref_id is not None:
            d["ref_id"] = self.ref_id
        if self.body_sha256 is not None:
            d["body_sha256"] = self.body_sha256
        if self.curated_content_index is not None:
            d["curated_content_index"] = self.curated_content_index
        else:
            if self.ref_id is not None:
                d["curated_content_index"] = None
        if self.source_role is not None:
            d["source_role"] = self.source_role
        if self.curated is not None:
            d["curated"] = self.curated
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SourceSegment:
        return cls(
            doc_id=d["doc_id"],
            source_path=d["source_path"],
            source_file_sha256=d["source_file_sha256"],
            json_pointer=d.get("json_pointer"),
            char_start=d["char_start"],
            char_end=d["char_end"],
            byte_start=d["byte_start"],
            byte_end=d["byte_end"],
            content_char_start=d["content_char_start"],
            content_char_end=d["content_char_end"],
            target_url=d["target_url"],
            segment_sha256=d["segment_sha256"],
            ref_id=d.get("ref_id"),
            body_sha256=d.get("body_sha256"),
            curated_content_index=d.get("curated_content_index"),
            source_role=d.get("source_role"),
            curated=d.get("curated"),
        )


@dataclass
class ChunkingVariant:
    """Descriptor for a specific parameter instantiation of a chunking rule."""

    rule_family: str
    variant_id: str
    target_tokens: Optional[int]
    overlap_tokens: Optional[int]
    encoder_window_tokens: Optional[int]
    encoder_overlap_tokens: Optional[int]
    fingerprint: str
    source_type: str
    is_diagnostic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_family": self.rule_family,
            "variant_id": self.variant_id,
            "target_tokens": self.target_tokens,
            "overlap_tokens": self.overlap_tokens,
            "encoder_window_tokens": self.encoder_window_tokens,
            "encoder_overlap_tokens": self.encoder_overlap_tokens,
            "fingerprint": self.fingerprint,
            "source_type": self.source_type,
            "is_diagnostic": self.is_diagnostic,
        }


def enumerate_chunking_variants(
    target_tokens_grid: Tuple[int, ...] = (128, 192, 224),
    overlap_tokens_grid: Tuple[int, ...] = (0, 32, 64),
    thread_window_tokens_grid: Tuple[int, ...] = (128, 192, 224),
    include_expanded_rules: bool = False,
) -> List[ChunkingVariant]:
    """Enumerate chunking variants across the parameter grid.

    By default returns the baseline 33 variants (18 RawPedia + 12 formal GitHub + 3 diagnostic GitHub).
    When include_expanded_rules is True, includes R-C-heading-window and G-C-curated-group (51 variants).
    """
    variants: List[ChunkingVariant] = []

    # 1. RawPedia R-A-heading: 9 variants
    for t in target_tokens_grid:
        for o in overlap_tokens_grid:
            vid = f"R-A-heading-t{t}-o{o}"
            fp = f"{vid}:{BGE_REVISION}"
            variants.append(
                ChunkingVariant(
                    rule_family="R-A-heading",
                    variant_id=vid,
                    target_tokens=t,
                    overlap_tokens=o,
                    encoder_window_tokens=None,
                    encoder_overlap_tokens=None,
                    fingerprint=fp,
                    source_type="rawpedia",
                    is_diagnostic=False,
                )
            )

    # 2. RawPedia R-B-window: 9 variants
    for t in target_tokens_grid:
        for o in overlap_tokens_grid:
            vid = f"R-B-window-t{t}-o{o}"
            fp = f"{vid}:{BGE_REVISION}"
            variants.append(
                ChunkingVariant(
                    rule_family="R-B-window",
                    variant_id=vid,
                    target_tokens=t,
                    overlap_tokens=o,
                    encoder_window_tokens=None,
                    encoder_overlap_tokens=None,
                    fingerprint=fp,
                    source_type="rawpedia",
                    is_diagnostic=False,
                )
            )

    # 3. RawPedia R-C-heading-window (expanded): 9 variants
    if include_expanded_rules:
        for t in target_tokens_grid:
            for o in overlap_tokens_grid:
                vid = f"R-C-heading-window-t{t}-o{o}"
                fp = f"{vid}:{BGE_REVISION}"
                variants.append(
                    ChunkingVariant(
                        rule_family="R-C-heading-window",
                        variant_id=vid,
                        target_tokens=t,
                        overlap_tokens=o,
                        encoder_window_tokens=None,
                        encoder_overlap_tokens=None,
                        fingerprint=fp,
                        source_type="rawpedia",
                        is_diagnostic=False,
                    )
                )

    # 4. GitHub G-B-curated-unit: 9 variants
    for t in target_tokens_grid:
        for o in overlap_tokens_grid:
            vid = f"G-B-curated-unit-t{t}-o{o}"
            fp = f"{vid}:{BGE_REVISION}"
            variants.append(
                ChunkingVariant(
                    rule_family="G-B-curated-unit",
                    variant_id=vid,
                    target_tokens=t,
                    overlap_tokens=o,
                    encoder_window_tokens=None,
                    encoder_overlap_tokens=None,
                    fingerprint=fp,
                    source_type="github",
                    is_diagnostic=False,
                )
            )

    # 5. GitHub G-C-curated-group (expanded): 9 variants
    if include_expanded_rules:
        for t in target_tokens_grid:
            for o in overlap_tokens_grid:
                vid = f"G-C-curated-group-t{t}-o{o}"
                fp = f"{vid}:{BGE_REVISION}"
                variants.append(
                    ChunkingVariant(
                        rule_family="G-C-curated-group",
                        variant_id=vid,
                        target_tokens=t,
                        overlap_tokens=o,
                        encoder_window_tokens=None,
                        encoder_overlap_tokens=None,
                        fingerprint=fp,
                        source_type="github",
                        is_diagnostic=False,
                    )
                )

    # 6. GitHub G-A-curated-thread: 3 variants
    for w in thread_window_tokens_grid:
        vid = f"G-A-curated-thread-w{w}-wo0"
        fp = f"{vid}:{BGE_REVISION}"
        variants.append(
            ChunkingVariant(
                rule_family="G-A-curated-thread",
                variant_id=vid,
                target_tokens=None,
                overlap_tokens=None,
                encoder_window_tokens=w,
                encoder_overlap_tokens=0,
                fingerprint=fp,
                source_type="github",
                is_diagnostic=False,
            )
        )

    # 7. GitHub G-A-full-thread: 3 diagnostic variants
    for w in thread_window_tokens_grid:
        vid = f"G-A-full-thread-w{w}-wo0"
        fp = f"{vid}:{BGE_REVISION}"
        variants.append(
            ChunkingVariant(
                rule_family="G-A-full-thread",
                variant_id=vid,
                target_tokens=None,
                overlap_tokens=None,
                encoder_window_tokens=w,
                encoder_overlap_tokens=0,
                fingerprint=fp,
                source_type="github",
                is_diagnostic=True,
            )
        )

    return variants


@dataclass
class Chunk:
    """Single retrieval chunk representation."""

    chunk_id: str
    source_type: str  # 'rawpedia' or 'github'
    doc_id: str
    section_title: str
    content: str
    char_range: Tuple[int, int]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_type": self.source_type,
            "doc_id": self.doc_id,
            "section_title": self.section_title,
            "content": self.content,
            "char_range": list(self.char_range),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Chunk:
        return cls(
            chunk_id=d["chunk_id"],
            source_type=d["source_type"],
            doc_id=d["doc_id"],
            section_title=d["section_title"],
            content=d["content"],
            char_range=tuple(d["char_range"]),  # type: ignore
            metadata=d["metadata"],
        )


def compute_chunk_id(
    schema_version: str,
    rule_fingerprint: str,
    source_type: str,
    doc_id: str,
    source_segments: List[SourceSegment],
    content_sha256: str,
) -> str:
    """Generate deterministic chunk ID according to T08-2 execution plan §3.3."""
    seg_idents = []
    for s in source_segments:
        seg_idents.append({
            "doc_id": s.doc_id,
            "ref_id": s.ref_id,
            "segment_sha256": s.segment_sha256,
            "char_start": s.char_start,
            "char_end": s.char_end,
            "content_char_start": s.content_char_start,
            "content_char_end": s.content_char_end,
        })
    canonical_payload = {
        "content_sha256": content_sha256,
        "doc_id": doc_id,
        "rule_fingerprint": rule_fingerprint,
        "schema_version": schema_version,
        "source_segments": seg_idents,
        "source_type": source_type,
    }
    digest = sha256_bytes(canonical_json_bytes(canonical_payload))
    rule_id = rule_fingerprint.split(":")[0] if ":" in rule_fingerprint else rule_fingerprint
    return f"{schema_version}:{source_type}:{rule_id}:{digest}"


def validate_chunk_provenance(chunk: Chunk, source_text_getter: Callable[[SourceSegment], Tuple[str, str]]) -> None:
    """Verify chunk provenance and segment correspondence strictly against original sources.

    Raises ValueError on any mismatch.
    """
    meta = chunk.metadata
    if chunk.source_type not in ("rawpedia", "github"):
        raise ValueError(f"Invalid source_type: {chunk.source_type}")

    content = chunk.content
    if sha256_str(content) != meta.get("content_sha256"):
        raise ValueError(f"Chunk content SHA256 mismatch for {chunk.chunk_id}")

    segments_data = meta.get("source_segments", [])
    if not segments_data:
        raise ValueError(f"No source_segments in chunk {chunk.chunk_id}")

    range_basis = meta.get("range_basis")
    if range_basis not in ("source_file", "json_body", "serialized_content"):
        raise ValueError(f"Unknown range_basis: {range_basis}")

    for s_dict in segments_data:
        seg = SourceSegment.from_dict(s_dict) if isinstance(s_dict, dict) else s_dict
        original_text, file_sha = source_text_getter(seg)
        if file_sha != seg.source_file_sha256:
            raise ValueError(f"File SHA mismatch for segment {seg.doc_id} in chunk {chunk.chunk_id}")

        if seg.char_start < 0 or seg.char_end > len(original_text) or seg.char_start > seg.char_end:
            raise ValueError(f"Invalid char range [{seg.char_start}, {seg.char_end}) in {seg.source_path}")

        orig_slice = original_text[seg.char_start:seg.char_end]
        if sha256_str(orig_slice) != seg.segment_sha256:
            raise ValueError(f"Segment slice SHA mismatch in {seg.doc_id}")

        byte_start = len(original_text[:seg.char_start].encode("utf-8"))
        byte_end = len(original_text[:seg.char_end].encode("utf-8"))
        if byte_start != seg.byte_start or byte_end != seg.byte_end:
            raise ValueError(f"Segment byte offset mismatch in {seg.doc_id}: expected [{byte_start},{byte_end}) got [{seg.byte_start},{seg.byte_end})")

        # Verify content_char_start/end
        if seg.content_char_start < 0 or seg.content_char_end > len(content) or seg.content_char_start > seg.content_char_end:
            raise ValueError(f"Invalid content char range [{seg.content_char_start}, {seg.content_char_end}) in {chunk.chunk_id}")

        chunk_slice = content[seg.content_char_start:seg.content_char_end]
        if chunk_slice != orig_slice:
            raise ValueError(f"Content slice does not match original slice in {seg.doc_id}")


def get_evidence_char_range(evidence: Dict[str, Any], original_text: str) -> Tuple[int, int]:
    """Get [char_start, char_end) for an evidence dictionary."""
    if "char_start" in evidence and "char_end" in evidence:
        return evidence["char_start"], evidence["char_end"]
    # Compute from byte_start, byte_end
    b_start = evidence["byte_start"]
    b_end = evidence["byte_end"]
    enc = original_text.encode("utf-8")
    c_start = len(enc[:b_start].decode("utf-8"))
    c_end = len(enc[:b_end].decode("utf-8"))
    return c_start, c_end


def calculate_evidence_chunk_coverage(
    evidence: Dict[str, Any],
    chunk: Chunk,
    evidence_char_range: Optional[Tuple[int, int]] = None,
) -> float:
    """Calculate the non-whitespace character coverage of an evidence span within a chunk.

    Returns float in [0.0, 1.0].
    """
    ev_source_path = evidence.get("source_path")
    ev_pointer = evidence.get("json_pointer")
    ev_ref_id = evidence.get("ref_id")
    ev_doc_id = evidence.get("doc_id")
    ev_text = evidence.get("text_span", "")

    if evidence_char_range is not None:
        ev_cstart, ev_cend = evidence_char_range
    elif "char_start" in evidence and "char_end" in evidence:
        ev_cstart, ev_cend = evidence["char_start"], evidence["char_end"]
    else:
        ev_cstart = evidence.get("char_start", 0)
        ev_cend = evidence.get("char_end", len(ev_text))

    ev_non_ws = len(re.sub(r"\s", "", ev_text))
    if ev_non_ws == 0:
        return 1.0

    matched_chars = 0
    segments_data = chunk.metadata.get("source_segments", [])
    for s_dict in segments_data:
        seg = SourceSegment.from_dict(s_dict) if isinstance(s_dict, dict) else s_dict
        if seg.source_path != ev_source_path:
            continue
        if seg.json_pointer != ev_pointer:
            continue
        if ev_ref_id is not None and seg.ref_id is not None and seg.ref_id != ev_ref_id:
            continue
        if ev_ref_id is None and seg.doc_id != ev_doc_id:
            continue

        overlap_start = max(seg.char_start, ev_cstart)
        overlap_end = min(seg.char_end, ev_cend)
        if overlap_end > overlap_start:
            rel_start = overlap_start - ev_cstart
            rel_end = overlap_end - ev_cstart
            overlap_slice = ev_text[rel_start:rel_end]
            matched_chars += len(re.sub(r"\s", "", overlap_slice))

    return min(1.0, matched_chars / ev_non_ws)


def calculate_evidence_chunks_union_coverage(
    evidence: Dict[str, Any],
    chunks: List[Chunk],
    evidence_char_range: Optional[Tuple[int, int]] = None,
) -> float:
    """Calculate union non-whitespace character coverage across multiple chunks."""
    ev_source_path = evidence.get("source_path")
    ev_pointer = evidence.get("json_pointer")
    ev_ref_id = evidence.get("ref_id")
    ev_doc_id = evidence.get("doc_id")
    ev_text = evidence.get("text_span", "")

    if evidence_char_range is not None:
        ev_cstart, ev_cend = evidence_char_range
    elif "char_start" in evidence and "char_end" in evidence:
        ev_cstart, ev_cend = evidence["char_start"], evidence["char_end"]
    else:
        ev_cstart = evidence.get("char_start", 0)
        ev_cend = evidence.get("char_end", len(ev_text))

    ev_len = ev_cend - ev_cstart
    if ev_len <= 0:
        return 1.0

    covered = [False] * ev_len
    for chunk in chunks:
        segments_data = chunk.metadata.get("source_segments", [])
        for s_dict in segments_data:
            seg = SourceSegment.from_dict(s_dict) if isinstance(s_dict, dict) else s_dict
            if seg.source_path != ev_source_path:
                continue
            if seg.json_pointer != ev_pointer:
                continue
            if ev_ref_id is not None and seg.ref_id is not None and seg.ref_id != ev_ref_id:
                continue
            if ev_ref_id is None and seg.doc_id != ev_doc_id:
                continue

            overlap_start = max(seg.char_start, ev_cstart)
            overlap_end = min(seg.char_end, ev_cend)
            if overlap_end > overlap_start:
                for idx in range(overlap_start - ev_cstart, overlap_end - ev_cstart):
                    covered[idx] = True

    total_non_ws = 0
    covered_non_ws = 0
    for idx, ch in enumerate(ev_text):
        if not ch.isspace():
            total_non_ws += 1
            if covered[idx]:
                covered_non_ws += 1

    if total_non_ws == 0:
        return 1.0
    return min(1.0, covered_non_ws / total_non_ws)


# =========================================================================
# Tokenizer Bundle and Length Guards
# =========================================================================

class TokenizerBundle:
    """Manages reference tokenizer and multi-model length guards."""

    def __init__(self, bge_tokenizer: Any, candidate_tokenizers: Optional[Dict[str, Any]] = None):
        self.ref_tokenizer = bge_tokenizer
        self.candidate_tokenizers = candidate_tokenizers or {}
        self.ref_revision = BGE_REVISION

    def count_ref_tokens(self, text: str) -> int:
        """Count reference tokens using BGE fast tokenizer without special tokens."""
        if not text:
            return 0
        return len(self.ref_tokenizer.encode(text, add_special_tokens=False))

    def get_token_offsets(self, text: str) -> List[Tuple[int, int]]:
        """Return list of (char_start, char_end) for each token."""
        if not text:
            return []
        encoding = self.ref_tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
        return encoding["offset_mapping"]

    def truncate_header_text(self, header: str, max_tokens: int = 32) -> str:
        """Truncate header to at most max_tokens at character boundary using token offsets."""
        offsets = self.get_token_offsets(header)
        if len(offsets) <= max_tokens:
            return header
        cut_char_end = offsets[max_tokens - 1][1]
        return header[:cut_char_end].strip()

    def check_length_guard(self, text: str, header: str, model_id: str, max_seq_length: int, prefix: str = "") -> None:
        """Ensure full input text does not exceed max_seq_length for model."""
        tok = self.candidate_tokenizers.get(model_id, self.ref_tokenizer)
        full_text = f"{header}\n{text}".strip() if header else text
        if prefix:
            full_text = f"{prefix}{full_text}"
        tokens = tok.encode(full_text, add_special_tokens=True)
        if len(tokens) > max_seq_length:
            raise ValueError(
                f"Length guard violated for model {model_id}: tokens={len(tokens)} > max_seq_length={max_seq_length}"
            )

    def truncate_text_to_guard(
        self,
        text: str,
        header: str,
        guard_models: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, bool]:
        """Truncate text so that f"{prefix}{header}\n{text}" fits in max_seq_length for all guard models."""
        adjusted = False
        cur_text = text
        for m_id, m_cfg in guard_models.items():
            tok = self.candidate_tokenizers.get(m_id, self.ref_tokenizer)
            max_len = m_cfg.get("max_seq_length", 512)
            prefix = m_cfg.get("doc_prefix", "")
            full_text = f"{header}\n{cur_text}".strip() if header else cur_text
            if prefix:
                full_text = f"{prefix}{full_text}"
            tokens = tok.encode(full_text, add_special_tokens=True)
            if len(tokens) > max_len:
                adjusted = True
                excess = len(tokens) - max_len
                offsets = self.get_token_offsets(cur_text)
                if offsets:
                    target_tokens_count = max(1, len(offsets) - excess - 4)
                    cut_char = offsets[min(target_tokens_count - 1, len(offsets) - 1)][1]
                    cur_text = cur_text[:cut_char]
                while len(tok.encode(f"{prefix}{header}\n{cur_text}".strip() if header else f"{prefix}{cur_text}", add_special_tokens=True)) > max_len:
                    if len(cur_text) <= 10:
                        break
                    cur_text = cur_text[:int(len(cur_text) * 0.9)]
        return cur_text, adjusted


def build_chunk_header(
    page_title: Optional[str],
    section_title: Optional[str],
    tokenizer_bundle: Optional[Any] = None,
) -> str:
    """Build header string according to §4.1: page_title \n section_title (deduplicating identical titles), truncated to 32 ref tokens."""
    p = (page_title or "").strip()
    s = (section_title or "").strip()
    if p and s and p != s:
        header = f"{p}\n{s}"
    else:
        header = s or p
    if header and tokenizer_bundle is not None:
        if hasattr(tokenizer_bundle, "truncate_header_text"):
            return tokenizer_bundle.truncate_header_text(header, max_tokens=32)
        elif hasattr(tokenizer_bundle, "encode"):
            enc_h = tokenizer_bundle(header, return_offsets_mapping=True, add_special_tokens=False)
            offsets_h = enc_h.get("offset_mapping", [])
            if len(offsets_h) > 32:
                return header[:offsets_h[31][1]].strip()
    return header


# =========================================================================
# RawPedia Chunking
# =========================================================================

@dataclass
class RawPediaSection:
    heading_title: str
    section_path: List[str]
    level: int
    char_start: int
    char_end: int
    text: str


def parse_rawpedia_markdown_sections(text: str) -> Tuple[str, str, int, List[RawPediaSection]]:
    """Parse Markdown frontmatter and H2/H3 headings, ignoring hashes in code blocks.

    Returns:
        (page_title, body_text_after_fm, fm_end_char, list of sections)
    """
    page_title = ""
    fm_end_char = 0
    if text.startswith("---"):
        end_idx = text.find("\n---", 3)
        if end_idx != -1:
            fm_text = text[3:end_idx]
            fm_end_char = end_idx + 4
            for line in fm_text.splitlines():
                if line.startswith("title:"):
                    page_title = line.split("title:", 1)[1].strip().strip('"\'')
                    break

    # Identify code blocks to ignore markdown headings inside fences
    lines = text.splitlines(keepends=True)
    in_code = False
    cur_pos = 0
    heading_positions: List[Tuple[int, int, int, str]] = []  # (pos, end_line_pos, level, title)

    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith("```") or line_stripped.startswith("~~~"):
            in_code = not in_code
        elif not in_code and cur_pos >= fm_end_char:
            # Check for H2 or H3
            m = re.match(r"^(#{2,3})\s+(.+)$", line)
            if m:
                level = len(m.group(1))
                h_title = m.group(2).strip()
                heading_positions.append((cur_pos, cur_pos + len(line), level, h_title))
        cur_pos += len(line)

    if not heading_positions:
        # No H2/H3 headings in page
        body_text = text[fm_end_char:]
        sec = RawPediaSection(
            heading_title=page_title or "Overview",
            section_path=[page_title] if page_title else ["Overview"],
            level=1,
            char_start=fm_end_char,
            char_end=len(text),
            text=body_text,
        )
        return page_title, text[fm_end_char:], fm_end_char, [sec]

    sections: List[RawPediaSection] = []
    stack: List[Tuple[int, str]] = []

    # Content before first heading if any
    first_h_pos = heading_positions[0][0]
    if first_h_pos > fm_end_char:
        pre_text = text[fm_end_char:first_h_pos]
        if pre_text.strip():
            sections.append(
                RawPediaSection(
                    heading_title=page_title or "Introduction",
                    section_path=[page_title, "Introduction"] if page_title else ["Introduction"],
                    level=1,
                    char_start=fm_end_char,
                    char_end=first_h_pos,
                    text=pre_text,
                )
            )

    for i, (h_pos, h_end_line, lvl, title) in enumerate(heading_positions):
        next_pos = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(text)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        stack.append((lvl, title))
        sec_path = [t for _, t in stack]

        # Section body includes the heading itself and everything up to next heading
        sec_text = text[h_pos:next_pos]
        sections.append(
            RawPediaSection(
                heading_title=title,
                section_path=sec_path,
                level=lvl,
                char_start=h_pos,
                char_end=next_pos,
                text=sec_text,
            )
        )

    return page_title, text[fm_end_char:], fm_end_char, sections


def split_text_by_sentences(text: str) -> List[Tuple[int, int, str]]:
    """Split text into sentences with [char_start, char_end) offsets relative to text.

    Protects URLs and backtick/code spans from being split.
    """
    if not text:
        return []

    # Regex finding sentence endings (. ? !) followed by whitespace, not inside common patterns
    # Simple, robust sentence boundary finder:
    sentence_end_regex = re.compile(r"([.!?]+(?:\s+|$))")
    parts = []
    cur_start = 0

    # Mask code spans
    in_code = False
    in_backtick = False

    i = 0
    n = len(text)
    while i < n:
        if text[i : i + 3] == "```":
            in_code = not in_code
            i += 3
            continue
        elif text[i] == "`" and not in_code:
            in_backtick = not in_backtick
            i += 1
            continue

        if not in_code and not in_backtick:
            if text[i] in ".!?" and (i + 1 == n or text[i + 1].isspace()):
                # Potential sentence boundary
                # Lookahead to see if it's e.g. a number or abbreviation (e.g. "1.5" or "e.g.")
                is_num = i > 0 and text[i - 1].isdigit() and (i + 1 < n and text[i + 1].isdigit())
                if not is_num:
                    # Advance past consecutive punctuation
                    end_punct = i + 1
                    while end_punct < n and text[end_punct] in ".!?":
                        end_punct += 1
                    # Advance past trailing whitespace
                    while end_punct < n and text[end_punct] in " \t\r\n":
                        end_punct += 1
                    sent = text[cur_start:end_punct]
                    if sent.strip():
                        parts.append((cur_start, end_punct, sent))
                    cur_start = end_punct
                    i = end_punct
                    continue
        i += 1

    if cur_start < n:
        tail = text[cur_start:n]
        if tail.strip():
            parts.append((cur_start, n, tail))

    return parts


def compute_actual_overlap_tokens(
    text: str,
    prev_range: Optional[Tuple[int, int]],
    curr_range: Tuple[int, int],
    tokenizer_bundle: TokenizerBundle,
) -> int:
    """Compute number of reference tokens in overlap between previous and current chunk."""
    if prev_range is None:
        return 0
    st = max(prev_range[0], curr_range[0])
    ed = min(prev_range[1], curr_range[1])
    if ed <= st:
        return 0
    return tokenizer_bundle.count_ref_tokens(text[st:ed])


def chunk_rawpedia_heading_rule(
    file_path: str,
    raw_bytes: bytes,
    doc_id: str,
    target_url: str,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
) -> List[Chunk]:
    """Generate chunks under rule R-A-heading with (target_tokens, overlap_tokens) grid support."""
    text = raw_bytes.decode("utf-8")
    file_sha = sha256_bytes(raw_bytes)
    page_title, _, fm_end, sections = parse_rawpedia_markdown_sections(text)
    rule_family = "R-A-heading"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    pol = physical_embedding_policy or ("direct_native_v3" if guard_group else "direct_native_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{pol}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"

    chunks: List[Chunk] = []

    for sec in sections:
        sec_text = sec.text
        if not sec_text.strip():
            continue
        header = build_chunk_header(page_title, sec.heading_title, tokenizer_bundle)
        last_sec_range: Optional[Tuple[int, int]] = None

        cur_pos = 0
        while cur_pos < len(sec_text):
            if not sec_text[cur_pos:].strip():
                break
            remaining = sec_text[cur_pos:]
            sents = split_text_by_sentences(remaining)
            if not sents:
                sents = [(0, len(remaining), remaining)]

            cur_toks = 0
            cand_end_rel = 0
            for s_st, s_ed, s_tx in sents:
                s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
                if cand_end_rel > 0 and (cur_toks + s_tok > target_tokens):
                    break
                cand_end_rel = s_ed
                cur_toks += s_tok
                if cur_toks >= target_tokens:
                    break

            if cur_toks > target_tokens and cand_end_rel == sents[0][1]:
                offsets = tokenizer_bundle.get_token_offsets(sents[0][2])
                t_cut = min(target_tokens, len(offsets))
                cand_end_rel = sents[0][0] + offsets[t_cut - 1][1]

            cand_text = sec_text[cur_pos : cur_pos + cand_end_rel]
            c_start = sec.char_start + cur_pos

            if guard_models and pol in ("direct_native_v2", "direct_native_v3"):
                actual_text, _ = tokenizer_bundle.truncate_text_to_guard(cand_text, header, guard_models)
            else:
                actual_text = cand_text
            if not actual_text.strip():
                actual_text = cand_text[:max(1, len(cand_text))]

            c_end = c_start + len(actual_text)
            b_start = len(text[:c_start].encode("utf-8"))
            b_end = len(text[:c_end].encode("utf-8"))
            actual_toks = tokenizer_bundle.count_ref_tokens(actual_text)
            actual_overlap_toks = compute_actual_overlap_tokens(
                text, last_sec_range, (c_start, c_end), tokenizer_bundle
            )
            last_sec_range = (c_start, c_end)

            seg = SourceSegment(
                doc_id=doc_id,
                source_path=file_path,
                source_file_sha256=file_sha,
                json_pointer=None,
                char_start=c_start,
                char_end=c_end,
                byte_start=b_start,
                byte_end=b_end,
                content_char_start=0,
                content_char_end=len(actual_text),
                target_url=target_url,
                segment_sha256=sha256_str(actual_text),
            )
            cid = compute_chunk_id(
                CHUNK_SCHEMA_VERSION,
                rule_fingerprint,
                "rawpedia",
                doc_id,
                [seg],
                sha256_str(actual_text),
            )
            meta = {
                "schema_version": 1,
                "rule_family": rule_family,
                "rule_id": rule_id,
                "rule_fingerprint": rule_fingerprint,
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
                "encoder_window_tokens": encoder_window_tokens,
                "encoder_overlap_tokens": encoder_overlap_tokens,
                "actual_tokens": actual_toks,
                "actual_overlap_tokens": actual_overlap_toks,
                "content_sha256": sha256_str(actual_text),
                "source_group_id": doc_id,
                "product_scope": "rawtherapee_reference",
                "range_basis": "source_file",
                "section_kind": "heading",
                "section_path": sec.section_path,
                "page_title": page_title,
                "target_url": target_url,
                "source_path": file_path,
                "source_file_sha256": file_sha,
                "embedding_policy": pol,
                "guard_group": guard_group,
                "source_segments": [seg.to_dict()],
            }
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    source_type="rawpedia",
                    doc_id=doc_id,
                    section_title=sec.heading_title,
                    content=actual_text,
                    char_range=(c_start, c_end),
                    metadata=meta,
                )
            )

            actual_end_pos = cur_pos + len(actual_text)
            if actual_end_pos >= len(sec_text):
                break

            eff_overlap = min(overlap_tokens, max(0, actual_toks - 16))
            if eff_overlap == 0:
                next_pos = actual_end_pos
            else:
                best_p = None
                for s_st, s_ed, _ in sents:
                    abs_p = cur_pos + s_st
                    if cur_pos < abs_p < actual_end_pos:
                        if tokenizer_bundle.count_ref_tokens(sec_text[abs_p : actual_end_pos]) <= eff_overlap:
                            best_p = abs_p
                            break
                if best_p is not None:
                    next_pos = best_p
                else:
                    tok_offsets = tokenizer_bundle.get_token_offsets(actual_text)
                    if len(tok_offsets) > eff_overlap:
                        next_pos = cur_pos + tok_offsets[-eff_overlap][0]
                    else:
                        next_pos = actual_end_pos

            if next_pos <= cur_pos:
                next_pos = actual_end_pos
            cur_pos = next_pos

    return chunks


def chunk_rawpedia_window_rule(
    file_path: str,
    raw_bytes: bytes,
    doc_id: str,
    target_url: str,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
) -> List[Chunk]:
    """Generate chunks under rule R-B-window (sliding sentence window across headings)."""
    text = raw_bytes.decode("utf-8")
    file_sha = sha256_bytes(raw_bytes)
    page_title, body_text, fm_end, sections = parse_rawpedia_markdown_sections(text)
    rule_family = "R-B-window"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    pol = physical_embedding_policy or ("direct_native_v3" if guard_group else "direct_native_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{pol}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"

    chunks: List[Chunk] = []
    last_window_range: Optional[Tuple[int, int]] = None

    def find_section_title(char_pos: int) -> Tuple[str, List[str]]:
        for sec in sections:
            if sec.char_start <= char_pos < sec.char_end:
                return sec.heading_title, sec.section_path
        return page_title or "Overview", [page_title or "Overview"]

    cur_pos = 0
    while cur_pos < len(body_text):
        if not body_text[cur_pos:].strip():
            break
        remaining = body_text[cur_pos:]
        sents = split_text_by_sentences(remaining)
        if not sents:
            sents = [(0, len(remaining), remaining)]

        cur_toks = 0
        cand_end_rel = 0
        for s_st, s_ed, s_tx in sents:
            s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
            if cand_end_rel > 0 and (cur_toks + s_tok > target_tokens):
                break
            cand_end_rel = s_ed
            cur_toks += s_tok
            if cur_toks >= target_tokens:
                break

        if cur_toks > target_tokens and cand_end_rel == sents[0][1]:
            offsets = tokenizer_bundle.get_token_offsets(sents[0][2])
            t_cut = min(target_tokens, len(offsets))
            cand_end_rel = sents[0][0] + offsets[t_cut - 1][1]

        cand_text = body_text[cur_pos : cur_pos + cand_end_rel]
        c_start = fm_end + cur_pos
        sec_title, sec_path = find_section_title(c_start)
        header = build_chunk_header(page_title, sec_title, tokenizer_bundle)

        if guard_models and pol in ("direct_native_v2", "direct_native_v3"):
            actual_text, _ = tokenizer_bundle.truncate_text_to_guard(cand_text, header, guard_models)
        else:
            actual_text = cand_text
        if not actual_text.strip():
            actual_text = cand_text[:max(1, len(cand_text))]

        c_end = c_start + len(actual_text)
        b_start = len(text[:c_start].encode("utf-8"))
        b_end = len(text[:c_end].encode("utf-8"))
        actual_toks = tokenizer_bundle.count_ref_tokens(actual_text)
        actual_overlap_toks = compute_actual_overlap_tokens(
            text, last_window_range, (c_start, c_end), tokenizer_bundle
        )
        last_window_range = (c_start, c_end)

        seg = SourceSegment(
            doc_id=doc_id,
            source_path=file_path,
            source_file_sha256=file_sha,
            json_pointer=None,
            char_start=c_start,
            char_end=c_end,
            byte_start=b_start,
            byte_end=b_end,
            content_char_start=0,
            content_char_end=len(actual_text),
            target_url=target_url,
            segment_sha256=sha256_str(actual_text),
        )
        cid = compute_chunk_id(
            CHUNK_SCHEMA_VERSION,
            rule_fingerprint,
            "rawpedia",
            doc_id,
            [seg],
            sha256_str(actual_text),
        )
        meta = {
            "schema_version": 1,
            "rule_family": rule_family,
            "rule_id": rule_id,
            "rule_fingerprint": rule_fingerprint,
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
            "encoder_window_tokens": encoder_window_tokens,
            "encoder_overlap_tokens": encoder_overlap_tokens,
            "actual_tokens": actual_toks,
            "actual_overlap_tokens": actual_overlap_toks,
            "content_sha256": sha256_str(actual_text),
            "source_group_id": doc_id,
            "product_scope": "rawtherapee_reference",
            "range_basis": "source_file",
            "section_kind": "window",
            "section_path": sec_path,
            "page_title": page_title,
            "target_url": target_url,
            "source_path": file_path,
            "source_file_sha256": file_sha,
            "embedding_policy": pol,
            "guard_group": guard_group,
            "source_segments": [seg.to_dict()],
        }
        chunks.append(
            Chunk(
                chunk_id=cid,
                source_type="rawpedia",
                doc_id=doc_id,
                section_title=sec_title,
                content=actual_text,
                char_range=(c_start, c_end),
                metadata=meta,
            )
        )

        actual_end_pos = cur_pos + len(actual_text)
        if actual_end_pos >= len(body_text):
            break

        eff_overlap = min(overlap_tokens, max(0, actual_toks - 16))
        if eff_overlap == 0:
            next_pos = actual_end_pos
        else:
            best_p = None
            for s_st, s_ed, _ in sents:
                abs_p = cur_pos + s_st
                if cur_pos < abs_p < actual_end_pos:
                    if tokenizer_bundle.count_ref_tokens(body_text[abs_p : actual_end_pos]) <= eff_overlap:
                        best_p = abs_p
                        break
            if best_p is not None:
                next_pos = best_p
            else:
                tok_offsets = tokenizer_bundle.get_token_offsets(actual_text)
                if len(tok_offsets) > eff_overlap:
                    next_pos = cur_pos + tok_offsets[-eff_overlap][0]
                else:
                    next_pos = actual_end_pos

        if next_pos <= cur_pos:
            next_pos = actual_end_pos
        cur_pos = next_pos

    return chunks


def chunk_rawpedia_heading_window_rule(
    file_path: str,
    raw_bytes: bytes,
    doc_id: str,
    target_url: str,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
) -> List[Chunk]:
    """Generate chunks under rule R-C-heading-window (sentence-first sliding window with heading snap)."""
    text = raw_bytes.decode("utf-8")
    file_sha = sha256_bytes(raw_bytes)
    page_title, body_text, fm_end, sections = parse_rawpedia_markdown_sections(text)
    rule_family = "R-C-heading-window"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    pol = physical_embedding_policy or ("direct_native_v3" if guard_group else "direct_native_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{pol}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"

    chunks: List[Chunk] = []
    last_window_range: Optional[Tuple[int, int]] = None

    def find_section_title(char_pos: int) -> Tuple[str, List[str]]:
        for sec in sections:
            if sec.char_start <= char_pos < sec.char_end:
                return sec.heading_title, sec.section_path
        return page_title or "Overview", [page_title or "Overview"]

    cur_pos = 0
    while cur_pos < len(body_text):
        if not body_text[cur_pos:].strip():
            break
        remaining = body_text[cur_pos:]
        sents = split_text_by_sentences(remaining)
        if not sents:
            sents = [(0, len(remaining), remaining)]

        cur_toks = 0
        nominal_end_rel = 0
        for s_st, s_ed, s_tx in sents:
            s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
            if nominal_end_rel > 0 and (cur_toks + s_tok > target_tokens):
                break
            nominal_end_rel = s_ed
            cur_toks += s_tok
            if cur_toks >= target_tokens:
                break

        if cur_toks > target_tokens and nominal_end_rel == sents[0][1]:
            offsets = tokenizer_bundle.get_token_offsets(sents[0][2])
            t_cut = min(target_tokens, len(offsets))
            nominal_end_rel = sents[0][0] + offsets[t_cut - 1][1]

        # Heading snap: check H2/H3 headings strictly after cur_pos and strictly before cur_pos + nominal_end_rel
        heading_candidates: List[int] = []
        for sec in sections:
            if sec.level in (2, 3) and sec.char_start >= fm_end:
                h_rel = sec.char_start - fm_end
                if cur_pos < h_rel < cur_pos + nominal_end_rel:
                    toks_to_h = tokenizer_bundle.count_ref_tokens(body_text[cur_pos:h_rel])
                    if 0.8 * target_tokens <= toks_to_h <= target_tokens:
                        heading_candidates.append(h_rel)

        if heading_candidates:
            h_best = max(heading_candidates)
            cand_end_rel = h_best - cur_pos
            heading_snapped = True
            geometry_equivalent = None
        else:
            cand_end_rel = nominal_end_rel
            heading_snapped = False
            geometry_equivalent = f"R-B-window-t{target_tokens}-o{overlap_tokens}"

        cand_text = body_text[cur_pos : cur_pos + cand_end_rel]
        c_start = fm_end + cur_pos
        sec_title, sec_path = find_section_title(c_start)
        header = build_chunk_header(page_title, sec_title, tokenizer_bundle)

        if guard_models and pol in ("direct_native_v2", "direct_native_v3"):
            actual_text, _ = tokenizer_bundle.truncate_text_to_guard(cand_text, header, guard_models)
        else:
            actual_text = cand_text
        if not actual_text.strip():
            actual_text = cand_text[:max(1, len(cand_text))]

        c_end = c_start + len(actual_text)
        b_start = len(text[:c_start].encode("utf-8"))
        b_end = len(text[:c_end].encode("utf-8"))
        actual_toks = tokenizer_bundle.count_ref_tokens(actual_text)
        actual_overlap_toks = compute_actual_overlap_tokens(
            text, last_window_range, (c_start, c_end), tokenizer_bundle
        )
        last_window_range = (c_start, c_end)

        seg = SourceSegment(
            doc_id=doc_id,
            source_path=file_path,
            source_file_sha256=file_sha,
            json_pointer=None,
            char_start=c_start,
            char_end=c_end,
            byte_start=b_start,
            byte_end=b_end,
            content_char_start=0,
            content_char_end=len(actual_text),
            target_url=target_url,
            segment_sha256=sha256_str(actual_text),
        )
        cid = compute_chunk_id(
            CHUNK_SCHEMA_VERSION,
            rule_fingerprint,
            "rawpedia",
            doc_id,
            [seg],
            sha256_str(actual_text),
        )
        meta = {
            "schema_version": 1,
            "rule_family": rule_family,
            "rule_id": rule_id,
            "rule_fingerprint": rule_fingerprint,
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
            "encoder_window_tokens": encoder_window_tokens,
            "encoder_overlap_tokens": encoder_overlap_tokens,
            "actual_tokens": actual_toks,
            "actual_overlap_tokens": actual_overlap_toks,
            "content_sha256": sha256_str(actual_text),
            "source_group_id": doc_id,
            "product_scope": "rawtherapee_reference",
            "range_basis": "source_file",
            "section_kind": "heading_window",
            "section_path": sec_path,
            "page_title": page_title,
            "target_url": target_url,
            "source_path": file_path,
            "source_file_sha256": file_sha,
            "embedding_policy": pol,
            "guard_group": guard_group,
            "source_segments": [seg.to_dict()],
            "heading_snapped": heading_snapped,
            "geometry_equivalent": geometry_equivalent,
        }
        chunks.append(
            Chunk(
                chunk_id=cid,
                source_type="rawpedia",
                doc_id=doc_id,
                section_title=sec_title,
                content=actual_text,
                char_range=(c_start, c_end),
                metadata=meta,
            )
        )

        actual_end_pos = cur_pos + len(actual_text)
        if actual_end_pos >= len(body_text):
            break

        eff_overlap = min(overlap_tokens, max(0, actual_toks - 16))
        if eff_overlap == 0:
            next_pos = actual_end_pos
        else:
            best_p = None
            for s_st, s_ed, _ in sents:
                abs_p = cur_pos + s_st
                if cur_pos < abs_p < actual_end_pos:
                    if tokenizer_bundle.count_ref_tokens(body_text[abs_p : actual_end_pos]) <= eff_overlap:
                        best_p = abs_p
                        break
            if best_p is not None:
                next_pos = best_p
            else:
                tok_offsets = tokenizer_bundle.get_token_offsets(actual_text)
                if len(tok_offsets) > eff_overlap:
                    next_pos = cur_pos + tok_offsets[-eff_overlap][0]
                else:
                    next_pos = actual_end_pos

        if next_pos <= cur_pos:
            next_pos = actual_end_pos
        cur_pos = next_pos

    return chunks


# =========================================================================
# GitHub Chunking
# =========================================================================

def chunk_github_curated_unit_rule(
    candidate: Dict[str, Any],
    github_dir: Path,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
) -> List[Chunk]:
    """Generate chunks under rule G-B-curated-unit with (target_tokens, overlap_tokens) grid support."""
    rule_family = "G-B-curated-unit"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    pol = physical_embedding_policy or ("direct_native_v3" if guard_group else "direct_native_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{pol}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"
    candidate_id = candidate["candidate_id"]
    chunks: List[Chunk] = []

    curated_content = candidate.get("curated_content", [])
    source_locations = candidate.get("source_locations", [])
    loc_by_ref = {loc["ref_id"]: loc for loc in source_locations}

    for idx, c_slice in enumerate(curated_content):
        ref_id = c_slice["ref_id"]
        loc = loc_by_ref.get(ref_id)
        if not loc:
            continue

        rel_snap = loc["snapshot_path"]
        snap_path = github_dir / rel_snap
        snap_bytes = snap_path.read_bytes()
        file_sha = sha256_bytes(snap_bytes)
        body = json.loads(snap_bytes).get("body", "")
        body_sha = sha256_str(body)

        c_start = c_slice["char_start"]
        c_end = c_slice["char_end"]
        slice_text = body[c_start:c_end]
        if not slice_text.strip():
            continue

        header = f"{candidate.get('title', '')}\n[{loc.get('source_kind', 'issue')} {ref_id}]"
        header = build_chunk_header("", header, tokenizer_bundle)
        last_slice_range: Optional[Tuple[int, int]] = None

        cur_pos = 0
        while cur_pos < len(slice_text):
            if not slice_text[cur_pos:].strip():
                break
            remaining = slice_text[cur_pos:]
            sents = split_text_by_sentences(remaining)
            if not sents:
                sents = [(0, len(remaining), remaining)]

            cur_toks = 0
            cand_end_rel = 0
            for s_st, s_ed, s_tx in sents:
                s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
                if cand_end_rel > 0 and (cur_toks + s_tok > target_tokens):
                    break
                cand_end_rel = s_ed
                cur_toks += s_tok
                if cur_toks >= target_tokens:
                    break

            if cur_toks > target_tokens and cand_end_rel == sents[0][1]:
                offsets = tokenizer_bundle.get_token_offsets(sents[0][2])
                t_cut = min(target_tokens, len(offsets))
                cand_end_rel = sents[0][0] + offsets[t_cut - 1][1]

            cand_text = slice_text[cur_pos : cur_pos + cand_end_rel]
            sub_c_start = c_start + cur_pos

            if guard_models and pol in ("direct_native_v2", "direct_native_v3"):
                actual_text, _ = tokenizer_bundle.truncate_text_to_guard(cand_text, header, guard_models)
            else:
                actual_text = cand_text
            if not actual_text.strip():
                actual_text = cand_text[:max(1, len(cand_text))]

            sub_c_end = sub_c_start + len(actual_text)
            sub_b_start = len(body[:sub_c_start].encode("utf-8"))
            sub_b_end = len(body[:sub_c_end].encode("utf-8"))
            actual_toks = tokenizer_bundle.count_ref_tokens(actual_text)
            actual_overlap_toks = compute_actual_overlap_tokens(
                body, last_slice_range, (sub_c_start, sub_c_end), tokenizer_bundle
            )
            last_slice_range = (sub_c_start, sub_c_end)

            seg = SourceSegment(
                doc_id=ref_id,
                source_path=f"data/issues/{rel_snap}",
                source_file_sha256=file_sha,
                json_pointer="/body",
                char_start=sub_c_start,
                char_end=sub_c_end,
                byte_start=sub_b_start,
                byte_end=sub_b_end,
                content_char_start=0,
                content_char_end=len(actual_text),
                target_url=loc.get("url", candidate["url"]),
                segment_sha256=sha256_str(actual_text),
                ref_id=ref_id,
                body_sha256=body_sha,
                curated_content_index=idx,
                source_role=c_slice.get("source_role", loc.get("source_kind")),
                curated=True,
            )
            cid = compute_chunk_id(
                CHUNK_SCHEMA_VERSION,
                rule_fingerprint,
                "github",
                ref_id,
                [seg],
                sha256_str(actual_text),
            )
            meta = {
                "schema_version": 1,
                "rule_family": rule_family,
                "rule_id": rule_id,
                "rule_fingerprint": rule_fingerprint,
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
                "encoder_window_tokens": encoder_window_tokens,
                "encoder_overlap_tokens": encoder_overlap_tokens,
                "actual_tokens": actual_toks,
                "actual_overlap_tokens": actual_overlap_toks,
                "content_sha256": sha256_str(actual_text),
                "source_group_id": candidate_id,
                "candidate_id": candidate_id,
                "source_kind": loc.get("source_kind"),
                "product_scope": "art_snapshot",
                "range_basis": "json_body",
                "section_kind": "json_pointer",
                "section_path": ["body"],
                "title": candidate.get("title", ""),
                "target_url": loc.get("url", candidate["url"]),
                "embedding_policy": pol,
                "guard_group": guard_group,
                "source_segments": [seg.to_dict()],
            }
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    source_type="github",
                    doc_id=ref_id,
                    section_title="/body",
                    content=actual_text,
                    char_range=(sub_c_start, sub_c_end),
                    metadata=meta,
                )
            )

            actual_end_pos = cur_pos + len(actual_text)
            if actual_end_pos >= len(slice_text):
                break

            eff_overlap = min(overlap_tokens, max(0, actual_toks - 16))
            if eff_overlap == 0:
                next_pos = actual_end_pos
            else:
                best_p = None
                for s_st, s_ed, _ in sents:
                    abs_p = cur_pos + s_st
                    if cur_pos < abs_p < actual_end_pos:
                        if tokenizer_bundle.count_ref_tokens(slice_text[abs_p : actual_end_pos]) <= eff_overlap:
                            best_p = abs_p
                            break
                if best_p is not None:
                    next_pos = best_p
                else:
                    tok_offsets = tokenizer_bundle.get_token_offsets(actual_text)
                    if len(tok_offsets) > eff_overlap:
                        next_pos = cur_pos + tok_offsets[-eff_overlap][0]
                    else:
                        next_pos = actual_end_pos

            if next_pos <= cur_pos:
                next_pos = actual_end_pos
            cur_pos = next_pos

    return chunks


def chunk_github_curated_group_rule(
    candidate: Dict[str, Any],
    github_dir: Path,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
    guard_group: Optional[str] = None,
    physical_embedding_policy: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
) -> List[Chunk]:
    """Generate chunks under rule G-C-curated-group (intermediate grouped curated slices)."""
    rule_family = "G-C-curated-group"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    pol = physical_embedding_policy or ("direct_native_v3" if guard_group else "direct_native_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{pol}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"
    candidate_id = candidate["candidate_id"]
    chunks: List[Chunk] = []

    curated_content = candidate.get("curated_content", [])
    source_locations = candidate.get("source_locations", [])
    loc_by_ref = {loc["ref_id"]: loc for loc in source_locations}

    slices_data: List[Dict[str, Any]] = []
    for idx, c_slice in enumerate(curated_content):
        ref_id = c_slice["ref_id"]
        loc = loc_by_ref.get(ref_id)
        if not loc:
            continue
        rel_snap = loc["snapshot_path"]
        snap_path = github_dir / rel_snap
        snap_bytes = snap_path.read_bytes()
        file_sha = sha256_bytes(snap_bytes)
        body = json.loads(snap_bytes).get("body", "")
        body_sha = sha256_str(body)

        c_start = c_slice["char_start"]
        c_end = c_slice["char_end"]
        slice_text = body[c_start:c_end]
        if not slice_text.strip():
            continue
        slices_data.append({
            "curated_idx": idx,
            "ref_id": ref_id,
            "loc": loc,
            "rel_snap": rel_snap,
            "file_sha": file_sha,
            "body": body,
            "body_sha": body_sha,
            "c_start": c_start,
            "c_end": c_end,
            "slice_text": slice_text,
            "source_role": c_slice.get("source_role", loc.get("source_kind")),
            "target_url": loc.get("url", candidate["url"]),
        })

    if not slices_data:
        return []

    # Stream of sentences across slices:
    # Each item: (slice_idx, sent_st, sent_ed, sent_text, sent_toks)
    items: List[Tuple[int, int, int, str, int]] = []
    for s_idx, s_info in enumerate(slices_data):
        slice_text = s_info["slice_text"]
        sents = split_text_by_sentences(slice_text)
        if not sents:
            sents = [(0, len(slice_text), slice_text)]
        for s_st, s_ed, s_tx in sents:
            s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
            if s_tok > target_tokens:
                offsets = tokenizer_bundle.get_token_offsets(s_tx)
                cur_off = 0
                while cur_off < len(offsets):
                    sub_cut = min(len(offsets), cur_off + target_tokens)
                    c_sub_st = s_st + offsets[cur_off][0]
                    c_sub_ed = s_st + offsets[sub_cut - 1][1]
                    sub_tx = slice_text[c_sub_st:c_sub_ed]
                    sub_tok = tokenizer_bundle.count_ref_tokens(sub_tx)
                    items.append((s_idx, c_sub_st, c_sub_ed, sub_tx, sub_tok))
                    cur_off = sub_cut
            else:
                items.append((s_idx, s_st, s_ed, s_tx, s_tok))

    cur_item = 0
    last_window_range: Optional[Tuple[int, int]] = None

    while cur_item < len(items):
        chunk_items = [items[cur_item]]
        cur_toks = items[cur_item][4]
        next_cand = cur_item + 1

        while next_cand < len(items):
            cand_item = items[next_cand]
            prev_item = chunk_items[-1]
            sep = f"\n\n[{slices_data[cand_item[0]]['loc']['source_kind']} {slices_data[cand_item[0]]['ref_id']}]\n" if cand_item[0] != prev_item[0] else ""
            sep_toks = tokenizer_bundle.count_ref_tokens(sep) if sep else 0
            if cur_toks + sep_toks + cand_item[4] > target_tokens:
                break
            chunk_items.append(cand_item)
            cur_toks += sep_toks + cand_item[4]
            next_cand += 1

        # Group adjacent chunk_items of same slice together
        slice_groups: List[Dict[str, Any]] = []
        for it in chunk_items:
            if not slice_groups or slice_groups[-1]["slice_idx"] != it[0]:
                slice_groups.append({
                    "slice_idx": it[0],
                    "items": [it],
                    "char_start": it[1],
                    "char_end": it[2],
                })
            else:
                slice_groups[-1]["items"].append(it)
                slice_groups[-1]["char_end"] = it[2]

        content_pieces: List[str] = []
        cur_content_pos = 0
        segs: List[SourceSegment] = []

        for g_i, grp in enumerate(slice_groups):
            s_info = slices_data[grp["slice_idx"]]
            sep = f"\n\n[{s_info['loc']['source_kind']} {s_info['ref_id']}]\n" if g_i > 0 else ""
            if sep:
                content_pieces.append(sep)
                cur_content_pos += len(sep)

            part_text = s_info["slice_text"][grp["char_start"]:grp["char_end"]]
            c_st = cur_content_pos
            content_pieces.append(part_text)
            cur_content_pos += len(part_text)
            c_ed = cur_content_pos

            sub_b_st = s_info["c_start"] + grp["char_start"]
            sub_b_ed = s_info["c_start"] + grp["char_end"]
            b_st = len(s_info["body"][:sub_b_st].encode("utf-8"))
            b_ed = len(s_info["body"][:sub_b_ed].encode("utf-8"))

            seg = SourceSegment(
                doc_id=s_info["ref_id"],
                source_path=f"data/issues/{s_info['rel_snap']}",
                source_file_sha256=s_info["file_sha"],
                json_pointer="/body",
                char_start=sub_b_st,
                char_end=sub_b_ed,
                byte_start=b_st,
                byte_end=b_ed,
                content_char_start=c_st,
                content_char_end=c_ed,
                target_url=s_info["target_url"],
                segment_sha256=sha256_str(part_text),
                ref_id=s_info["ref_id"],
                body_sha256=s_info["body_sha"],
                curated_content_index=s_info["curated_idx"],
                source_role=s_info["source_role"],
                curated=True,
            )
            segs.append(seg)

        cand_content = "".join(content_pieces)
        header = candidate.get("title", "")
        header = build_chunk_header("", header, tokenizer_bundle)

        if guard_models and pol in ("direct_native_v2", "direct_native_v3"):
            actual_text, _ = tokenizer_bundle.truncate_text_to_guard(cand_content, header, guard_models)
        else:
            actual_text = cand_content
        if not actual_text.strip():
            actual_text = cand_content[:max(1, len(cand_content))]

        # If guard truncated, adjust segments to not exceed actual_text
        if len(actual_text) < len(cand_content):
            trimmed_segs = []
            for s in segs:
                if s.content_char_start >= len(actual_text):
                    continue
                if s.content_char_end > len(actual_text):
                    cut = len(actual_text) - s.content_char_start
                    s.content_char_end = len(actual_text)
                    s.char_end = s.char_start + cut
                    orig_body = slices_data[s.curated_content_index]["body"]
                    s.byte_end = len(orig_body[:s.char_end].encode("utf-8"))
                    s.segment_sha256 = sha256_str(actual_text[s.content_char_start:s.content_char_end])
                trimmed_segs.append(s)
            segs = trimmed_segs

        distinct_slices = len(set(s.curated_content_index for s in segs))
        is_single = (distinct_slices == 1 and len(chunk_items) == 1 and chunk_items[0][1] == 0 and chunk_items[0][2] == len(slices_data[chunk_items[0][0]]["slice_text"]))
        geom_eq = f"G-B-curated-unit-t{target_tokens}-o{overlap_tokens}" if is_single else None

        actual_toks = tokenizer_bundle.count_ref_tokens(actual_text)
        actual_overlap_toks = compute_actual_overlap_tokens(cand_content, last_window_range, (0, len(actual_text)), tokenizer_bundle)
        last_window_range = (0, len(actual_text))

        cid = compute_chunk_id(
            CHUNK_SCHEMA_VERSION,
            rule_fingerprint,
            "github",
            candidate_id,
            segs,
            sha256_str(actual_text),
        )
        meta = {
            "schema_version": 1,
            "rule_family": rule_family,
            "rule_id": rule_id,
            "rule_fingerprint": rule_fingerprint,
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
            "encoder_window_tokens": encoder_window_tokens,
            "encoder_overlap_tokens": encoder_overlap_tokens,
            "actual_tokens": actual_toks,
            "actual_overlap_tokens": actual_overlap_toks,
            "content_sha256": sha256_str(actual_text),
            "source_group_id": candidate_id,
            "candidate_id": candidate_id,
            "source_kind": candidate.get("source_type"),
            "product_scope": "art_snapshot",
            "range_basis": "serialized_content",
            "section_kind": "curated_group",
            "section_path": [candidate.get("title", "")],
            "title": candidate.get("title", ""),
            "target_url": candidate.get("url", ""),
            "embedding_policy": pol,
            "guard_group": guard_group,
            "source_segments": [s.to_dict() for s in segs],
            "geometry_equivalent": geom_eq,
            "distinct_curated_count": distinct_slices,
        }
        chunks.append(
            Chunk(
                chunk_id=cid,
                source_type="github",
                doc_id=candidate_id,
                section_title=candidate.get("title", ""),
                content=actual_text,
                char_range=(0, len(actual_text)),
                metadata=meta,
            )
        )

        if next_cand >= len(items):
            break

        eff_overlap = min(overlap_tokens, max(0, actual_toks - 16))
        if eff_overlap == 0:
            next_pos_item = next_cand
        else:
            best_i = None
            for i_idx in range(len(chunk_items)):
                tail_toks = sum(it[4] for it in chunk_items[i_idx:])
                if tail_toks <= eff_overlap:
                    best_i = cur_item + i_idx
                    break
            if best_i is not None and best_i > cur_item:
                next_pos_item = best_i
            else:
                next_pos_item = next_cand

        if next_pos_item <= cur_item:
            next_pos_item = cur_item + 1
        cur_item = next_pos_item

    return chunks


def chunk_github_thread_rule(
    candidate: Dict[str, Any],
    github_dir: Path,
    tokenizer_bundle: TokenizerBundle,
    curated_only: bool = True,
    thread_obj: Optional[Any] = None,
    target_tokens: int = 192,
    guard_group: Optional[str] = None,
    guard_models: Optional[Dict[str, Any]] = None,
    encoder_window_tokens: Optional[int] = None,
    encoder_overlap_tokens: Optional[int] = None,
    thread_embedding_policy: Optional[str] = None,
) -> Chunk:
    """Generate thread chunk under rule G-A-curated-thread or G-A-full-thread."""
    w_val = encoder_window_tokens or target_tokens
    rule_family = "G-A-curated-thread" if curated_only else "G-A-full-thread"
    rule_id = f"{rule_family}-w{w_val}-wo0"
    w_policy = thread_embedding_policy or ("thread_window_mean_v3" if guard_group else "thread_window_mean_v1")
    rule_fingerprint = f"{rule_id}:{guard_group}:{w_policy}:{BGE_REVISION}" if guard_group else f"{rule_id}:{BGE_REVISION}"
    candidate_id = candidate["candidate_id"]

    segments: List[SourceSegment] = []
    content_pieces: List[str] = []
    cur_content_pos = 0

    if curated_only:
        # Curated slices in order
        curated_content = candidate.get("curated_content", [])
        source_locations = candidate.get("source_locations", [])
        loc_by_ref = {loc["ref_id"]: loc for loc in source_locations}

        for idx, c_slice in enumerate(curated_content):
            ref_id = c_slice["ref_id"]
            loc = loc_by_ref.get(ref_id)
            if not loc:
                continue

            rel_snap = loc["snapshot_path"]
            snap_path = github_dir / rel_snap
            snap_bytes = snap_path.read_bytes()
            file_sha = sha256_bytes(snap_bytes)
            body = json.loads(snap_bytes).get("body", "")
            body_sha = sha256_str(body)

            c_start = c_slice["char_start"]
            c_end = c_slice["char_end"]
            slice_text = body[c_start:c_end]
            if not slice_text.strip():
                continue

            b_start = len(body[:c_start].encode("utf-8"))
            b_end = len(body[:c_end].encode("utf-8"))

            sep = f"\n\n[{loc['source_kind']} {ref_id}]\n" if content_pieces else ""
            if sep:
                content_pieces.append(sep)
                cur_content_pos += len(sep)

            content_start = cur_content_pos
            content_pieces.append(slice_text)
            cur_content_pos += len(slice_text)
            content_end = cur_content_pos

            seg = SourceSegment(
                doc_id=ref_id,
                source_path=f"data/issues/{rel_snap}",
                source_file_sha256=file_sha,
                json_pointer="/body",
                char_start=c_start,
                char_end=c_end,
                byte_start=b_start,
                byte_end=b_end,
                content_char_start=content_start,
                content_char_end=content_end,
                target_url=loc.get("url", candidate["url"]),
                segment_sha256=sha256_str(slice_text),
                ref_id=ref_id,
                body_sha256=body_sha,
                curated_content_index=idx,
                source_role=c_slice.get("source_role", loc.get("source_kind")),
                curated=True,
            )
            segments.append(seg)
    else:
        # Full thread: parent + all comments
        assert thread_obj is not None, "thread_obj required for full thread"
        curated_refs = {loc["ref_id"]: loc for loc in candidate.get("source_locations", [])}

        # Parent
        parent_item = thread_obj.parent
        p_body = parent_item.body
        p_file_sha = parent_item.file_sha256
        p_body_sha = parent_item.body_sha256
        p_ref = parent_item.record_key

        p_slice = p_body
        p_bstart = 0
        p_bend = len(p_body.encode("utf-8"))

        content_start = 0
        content_pieces.append(p_slice)
        cur_content_pos += len(p_slice)
        content_end = cur_content_pos

        p_seg = SourceSegment(
            doc_id=p_ref,
            source_path=f"data/issues/{parent_item.storage_path}",
            source_file_sha256=p_file_sha,
            json_pointer="/body",
            char_start=0,
            char_end=len(p_body),
            byte_start=p_bstart,
            byte_end=p_bend,
            content_char_start=content_start,
            content_char_end=content_end,
            target_url=parent_item.url,
            segment_sha256=sha256_str(p_slice),
            ref_id=p_ref,
            body_sha256=p_body_sha,
            curated_content_index=0 if p_ref in curated_refs else None,
            source_role=parent_item.kind,
            curated=(p_ref in curated_refs),
        )
        segments.append(p_seg)

        # Comments sorted by created_at, ref_id
        comments_sorted = sorted(thread_obj.comments, key=lambda c: (c.created_at, c.record_key))
        for c in comments_sorted:
            c_body = c.body
            c_file_sha = c.file_sha256
            c_body_sha = c.body_sha256
            c_ref = c.record_key

            sep = f"\n\n[{c.kind} {c_ref}]\n"
            content_pieces.append(sep)
            cur_content_pos += len(sep)

            c_cstart = 0
            c_cend = len(c_body)
            c_bstart = 0
            c_bend = len(c_body.encode("utf-8"))

            c_content_start = cur_content_pos
            content_pieces.append(c_body)
            cur_content_pos += len(c_body)
            c_content_end = cur_content_pos

            c_seg = SourceSegment(
                doc_id=c_ref,
                source_path=f"data/issues/{c.storage_path}",
                source_file_sha256=c_file_sha,
                json_pointer="/body",
                char_start=c_cstart,
                char_end=c_cend,
                byte_start=c_bstart,
                byte_end=c_bend,
                content_char_start=c_content_start,
                content_char_end=c_content_end,
                target_url=c.url,
                segment_sha256=sha256_str(c_body),
                ref_id=c_ref,
                body_sha256=c_body_sha,
                curated_content_index=None,
                source_role=c.kind,
                curated=(c_ref in curated_refs),
            )
            segments.append(c_seg)

    full_content = "".join(content_pieces)
    cid = compute_chunk_id(
        CHUNK_SCHEMA_VERSION,
        rule_fingerprint,
        "github",
        candidate_id,
        segments,
        sha256_str(full_content),
    )

    meta = {
        "schema_version": 1,
        "rule_family": rule_family,
        "rule_id": rule_id,
        "rule_fingerprint": rule_fingerprint,
        "target_tokens": None,
        "overlap_tokens": None,
        "encoder_window_tokens": w_val,
        "encoder_overlap_tokens": encoder_overlap_tokens or 0,
        "actual_tokens": tokenizer_bundle.count_ref_tokens(full_content),
        "actual_overlap_tokens": 0,
        "content_sha256": sha256_str(full_content),
        "source_group_id": candidate_id,
        "candidate_id": candidate_id,
        "source_kind": candidate.get("source_type"),
        "product_scope": "art_snapshot",
        "range_basis": "serialized_content",
        "section_kind": "thread",
        "section_path": [candidate.get("title", "")],
        "title": candidate.get("title", ""),
        "target_url": candidate.get("url", ""),
        "embedding_policy": w_policy,
        "guard_group": guard_group,
        "source_segments": [s.to_dict() for s in segments],
    }

    return Chunk(
        chunk_id=cid,
        source_type="github",
        doc_id=candidate_id,
        section_title=candidate.get("title", ""),
        content=full_content,
        char_range=(0, len(full_content)),
        metadata=meta,
    )


def verify_raw_text_coverage(
    chunks: List[Chunk],
    rawpedia_dir: Path,
    candidates_path: Path,
    issues_dir: Path,
    source_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify that chunks cover 100% of non-whitespace characters across RawPedia docs and/or curated GitHub pieces."""
    omissions = []

    has_rawpedia = any(c.source_type == "rawpedia" for c in chunks)
    has_github = any(c.source_type == "github" for c in chunks)

    check_rawpedia = (source_type == "rawpedia") or (source_type is None and has_rawpedia and not has_github) or (source_type is None and has_rawpedia)
    check_github = (source_type == "github") or (source_type is None and has_github and not has_rawpedia) or (source_type is None and has_github)

    if source_type == "rawpedia":
        check_github = False
    elif source_type == "github":
        check_rawpedia = False

    rp_files = []
    total_pieces = 0

    # 1. RawPedia verification
    if check_rawpedia:
        rawpedia_chunks = [c for c in chunks if c.source_type == "rawpedia"]
        rp_covered_spans: Dict[str, List[Tuple[int, int]]] = {}
        for c in rawpedia_chunks:
            for s in c.metadata.get("source_segments", []):
                sp = s.get("source_path", "")
                rp_covered_spans.setdefault(sp, []).append((s["char_start"], s["char_end"]))

        rp_files = sorted(list(rawpedia_dir.glob("**/*.md")))
        for p in rp_files:
            rel_sp = str(p.relative_to(rawpedia_dir.parent.parent)) if rawpedia_dir.parent.parent in p.parents else str(p)
            text = p.read_bytes().decode("utf-8")
            _, body_text, fm_end, _ = parse_rawpedia_markdown_sections(text)

            spans = rp_covered_spans.get(rel_sp, [])
            if not spans:
                # Check by stem
                for k, v in rp_covered_spans.items():
                    if Path(k).stem == p.stem:
                        spans = v
                        break

            covered = [False] * len(text)
            for st, ed in spans:
                for i in range(max(0, st), min(len(text), ed)):
                    covered[i] = True

            in_miss = False
            mst = 0
            for i in range(fm_end, len(text)):
                if not text[i].isspace() and not covered[i]:
                    if not in_miss:
                        in_miss = True
                        mst = i
                else:
                    if in_miss:
                        in_miss = False
                        omissions.append({
                            "source": "rawpedia",
                            "path": str(p),
                            "char_start": mst,
                            "char_end": i,
                            "text": text[mst:i],
                        })
            if in_miss:
                omissions.append({
                    "source": "rawpedia",
                    "path": str(p),
                    "char_start": mst,
                    "char_end": len(text),
                    "text": text[mst:len(text)],
                })

    # 2. GitHub verification
    if check_github:
        cands_data = json.loads(candidates_path.read_bytes())
        candidates = cands_data.get("candidates", [])
        gh_chunks = [c for c in chunks if c.source_type == "github"]
        gh_covered_spans: Dict[str, List[Tuple[int, int]]] = {}
        for c in gh_chunks:
            for s in c.metadata.get("source_segments", []):
                ref = s.get("ref_id", s.get("doc_id", ""))
                gh_covered_spans.setdefault(ref, []).append((s["char_start"], s["char_end"]))

        total_pieces = 0
        for cand in candidates:
            curated_content = cand.get("curated_content", [])
            source_locations = cand.get("source_locations", [])
            loc_by_ref = {loc["ref_id"]: loc for loc in source_locations}
            for c_slice in curated_content:
                total_pieces += 1
                ref_id = c_slice["ref_id"]
                loc = loc_by_ref.get(ref_id)
                if not loc:
                    continue
                snap_path = issues_dir / loc["snapshot_path"]
                if not snap_path.is_file():
                    continue
                body = json.loads(snap_path.read_bytes()).get("body", "")
                c_start = c_slice["char_start"]
                c_end = c_slice["char_end"]

                spans = gh_covered_spans.get(ref_id, [])
                covered = [False] * len(body)
                for st, ed in spans:
                    for i in range(max(0, st), min(len(body), ed)):
                        covered[i] = True

                in_miss = False
                mst = 0
                for i in range(c_start, c_end):
                    if not body[i].isspace() and not covered[i]:
                        if not in_miss:
                            in_miss = True
                            mst = i
                    else:
                        if in_miss:
                            in_miss = False
                            omissions.append({
                                "source": "github",
                                "ref_id": ref_id,
                                "char_start": mst,
                                "char_end": i,
                                "text": body[mst:i],
                            })
                if in_miss:
                    omissions.append({
                        "source": "github",
                        "ref_id": ref_id,
                        "char_start": mst,
                        "char_end": c_end,
                        "text": body[mst:c_end],
                    })

    missing_chars = sum(len(o["text"]) for o in omissions)
    return {
        "rawpedia_files_checked": len(rp_files),
        "github_pieces_checked": total_pieces,
        "missing_intervals_count": len(omissions),
        "missing_chars_count": missing_chars,
        "omissions": omissions,
        "zero_omission": len(omissions) == 0,
    }

