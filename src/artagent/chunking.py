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
) -> List[ChunkingVariant]:
    """Enumerate all 33 chunking variants (18 RawPedia + 12 formal GitHub + 3 diagnostic GitHub)."""
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

    # 3. GitHub G-B-curated-unit: 9 variants
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

    # 4. GitHub G-A-curated-thread: 3 variants
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

    # 5. GitHub G-A-full-thread: 3 diagnostic variants
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
) -> List[Chunk]:
    """Generate chunks under rule R-A-heading with (target_tokens, overlap_tokens) grid support."""
    text = raw_bytes.decode("utf-8")
    file_sha = sha256_bytes(raw_bytes)
    page_title, _, fm_end, sections = parse_rawpedia_markdown_sections(text)
    rule_family = "R-A-heading"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    rule_fingerprint = f"{rule_id}:{BGE_REVISION}"

    chunks: List[Chunk] = []

    for sec in sections:
        sec_text = sec.text
        if not sec_text.strip():
            continue
        sec_tokens = tokenizer_bundle.count_ref_tokens(sec_text)
        last_sec_range: Optional[Tuple[int, int]] = None

        if sec_tokens <= target_tokens:
            # Entire section fits in one chunk
            c_start = sec.char_start
            c_end = sec.char_end
            b_start = len(text[:c_start].encode("utf-8"))
            b_end = len(text[:c_end].encode("utf-8"))
            actual_toks = sec_tokens
            actual_overlap_toks = 0  # Section start: no overlap across section boundary

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
                content_char_end=len(sec_text),
                target_url=target_url,
                segment_sha256=sha256_str(sec_text),
            )
            cid = compute_chunk_id(
                CHUNK_SCHEMA_VERSION,
                rule_fingerprint,
                "rawpedia",
                doc_id,
                [seg],
                sha256_str(sec_text),
            )
            meta = {
                "schema_version": 1,
                "rule_family": rule_family,
                "rule_id": rule_id,
                "rule_fingerprint": rule_fingerprint,
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
                "encoder_window_tokens": None,
                "encoder_overlap_tokens": None,
                "actual_tokens": actual_toks,
                "actual_overlap_tokens": actual_overlap_toks,
                "content_sha256": sha256_str(sec_text),
                "source_group_id": doc_id,
                "product_scope": "rawtherapee_reference",
                "range_basis": "source_file",
                "section_kind": "heading",
                "section_path": sec.section_path,
                "page_title": page_title,
                "target_url": target_url,
                "source_path": file_path,
                "source_file_sha256": file_sha,
                "source_segments": [seg.to_dict()],
            }
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    source_type="rawpedia",
                    doc_id=doc_id,
                    section_title=sec.heading_title,
                    content=sec_text,
                    char_range=(c_start, c_end),
                    metadata=meta,
                )
            )
        else:
            # Section exceeds target_tokens: split into pieces using sentences/tokens
            sec_sentences = split_text_by_sentences(sec_text)
            if not sec_sentences:
                sec_sentences = [(0, len(sec_text), sec_text)]

            sent_idx = 0
            num_sents = len(sec_sentences)
            while sent_idx < num_sents:
                cur_pieces = []
                cur_tokens = 0
                win_start_rel = sec_sentences[sent_idx][0]
                idx = sent_idx

                while idx < num_sents:
                    s_st, s_ed, s_tx = sec_sentences[idx]
                    s_tok = tokenizer_bundle.count_ref_tokens(s_tx)
                    if cur_pieces and (cur_tokens + s_tok > target_tokens):
                        break
                    cur_pieces.append(sec_sentences[idx])
                    cur_tokens += s_tok
                    idx += 1
                    if cur_tokens >= target_tokens:
                        break

                win_end_rel = cur_pieces[-1][1]
                combined = sec_text[win_start_rel:win_end_rel]

                # Check if a single sentence exceeds target_tokens
                if len(cur_pieces) == 1 and cur_tokens > target_tokens:
                    # Token-level fallback for giant single sentence
                    offsets = tokenizer_bundle.get_token_offsets(combined)
                    t_idx = 0
                    while t_idx < len(offsets):
                        t_end = min(t_idx + target_tokens, len(offsets))
                        sub_st = offsets[t_idx][0]
                        sub_ed = offsets[t_end - 1][1]
                        sub_slice = combined[sub_st:sub_ed]

                        c_start = sec.char_start + win_start_rel + sub_st
                        c_end = sec.char_start + win_start_rel + sub_ed
                        b_start = len(text[:c_start].encode("utf-8"))
                        b_end = len(text[:c_end].encode("utf-8"))
                        actual_toks = tokenizer_bundle.count_ref_tokens(sub_slice)
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
                            content_char_end=len(sub_slice),
                            target_url=target_url,
                            segment_sha256=sha256_str(sub_slice),
                        )
                        cid = compute_chunk_id(
                            CHUNK_SCHEMA_VERSION,
                            rule_fingerprint,
                            "rawpedia",
                            doc_id,
                            [seg],
                            sha256_str(sub_slice),
                        )
                        meta = {
                            "schema_version": 1,
                            "rule_family": rule_family,
                            "rule_id": rule_id,
                            "rule_fingerprint": rule_fingerprint,
                            "target_tokens": target_tokens,
                            "overlap_tokens": overlap_tokens,
                            "encoder_window_tokens": None,
                            "encoder_overlap_tokens": None,
                            "actual_tokens": actual_toks,
                            "actual_overlap_tokens": actual_overlap_toks,
                            "content_sha256": sha256_str(sub_slice),
                            "source_group_id": doc_id,
                            "product_scope": "rawtherapee_reference",
                            "range_basis": "source_file",
                            "section_kind": "heading",
                            "section_path": sec.section_path,
                            "page_title": page_title,
                            "target_url": target_url,
                            "source_path": file_path,
                            "source_file_sha256": file_sha,
                            "source_segments": [seg.to_dict()],
                        }
                        chunks.append(
                            Chunk(
                                chunk_id=cid,
                                source_type="rawpedia",
                                doc_id=doc_id,
                                section_title=sec.heading_title,
                                content=sub_slice,
                                char_range=(c_start, c_end),
                                metadata=meta,
                            )
                        )
                        if t_end >= len(offsets):
                            break
                        if overlap_tokens == 0:
                            t_idx = t_end
                        else:
                            t_idx = max(t_idx + 1, t_end - overlap_tokens)
                    sent_idx += 1
                    continue

                c_start = sec.char_start + win_start_rel
                c_end = sec.char_start + win_end_rel
                b_start = len(text[:c_start].encode("utf-8"))
                b_end = len(text[:c_end].encode("utf-8"))
                actual_toks = tokenizer_bundle.count_ref_tokens(combined)
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
                    content_char_end=len(combined),
                    target_url=target_url,
                    segment_sha256=sha256_str(combined),
                )
                cid = compute_chunk_id(
                    CHUNK_SCHEMA_VERSION,
                    rule_fingerprint,
                    "rawpedia",
                    doc_id,
                    [seg],
                    sha256_str(combined),
                )
                meta = {
                    "schema_version": 1,
                    "rule_family": rule_family,
                    "rule_id": rule_id,
                    "rule_fingerprint": rule_fingerprint,
                    "target_tokens": target_tokens,
                    "overlap_tokens": overlap_tokens,
                    "encoder_window_tokens": None,
                    "encoder_overlap_tokens": None,
                    "actual_tokens": actual_toks,
                    "actual_overlap_tokens": actual_overlap_toks,
                    "content_sha256": sha256_str(combined),
                    "source_group_id": doc_id,
                    "product_scope": "rawtherapee_reference",
                    "range_basis": "source_file",
                    "section_kind": "heading",
                    "section_path": sec.section_path,
                    "page_title": page_title,
                    "target_url": target_url,
                    "source_path": file_path,
                    "source_file_sha256": file_sha,
                    "source_segments": [seg.to_dict()],
                }
                chunks.append(
                    Chunk(
                        chunk_id=cid,
                        source_type="rawpedia",
                        doc_id=doc_id,
                        section_title=sec.heading_title,
                        content=combined,
                        char_range=(c_start, c_end),
                        metadata=meta,
                    )
                )

                if idx >= num_sents:
                    break
                # Overlap within section
                if overlap_tokens == 0:
                    sent_idx = idx
                else:
                    overlap_accum = 0
                    back_idx = idx - 1
                    while back_idx > sent_idx:
                        s_tok = tokenizer_bundle.count_ref_tokens(sec_sentences[back_idx][2])
                        if overlap_accum + s_tok > overlap_tokens:
                            break
                        overlap_accum += s_tok
                        back_idx -= 1
                    if back_idx == idx - 1 and overlap_accum == 0 and (idx - 1 > sent_idx):
                        sent_idx = idx - 1
                    else:
                        sent_idx = max(sent_idx + 1, back_idx + 1)

    return chunks


def chunk_rawpedia_window_rule(
    file_path: str,
    raw_bytes: bytes,
    doc_id: str,
    target_url: str,
    tokenizer_bundle: TokenizerBundle,
    target_tokens: int = 192,
    overlap_tokens: int = 32,
) -> List[Chunk]:
    """Generate chunks under rule R-B-window (sliding sentence window across headings)."""
    text = raw_bytes.decode("utf-8")
    file_sha = sha256_bytes(raw_bytes)
    page_title, body_text, fm_end, sections = parse_rawpedia_markdown_sections(text)
    rule_family = "R-B-window"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    rule_fingerprint = f"{rule_id}:{BGE_REVISION}"

    sentences = split_text_by_sentences(body_text)
    if not sentences:
        return []

    chunks: List[Chunk] = []
    sent_idx = 0
    num_sents = len(sentences)
    last_window_range: Optional[Tuple[int, int]] = None

    def find_section_title(char_pos: int) -> Tuple[str, List[str]]:
        for sec in sections:
            if sec.char_start <= char_pos < sec.char_end:
                return sec.heading_title, sec.section_path
        return page_title or "Overview", [page_title or "Overview"]

    while sent_idx < num_sents:
        cur_sents = []
        token_count = 0
        window_start_rel = sentences[sent_idx][0]
        curr_idx = sent_idx

        while curr_idx < num_sents:
            s_start, s_end, s_text = sentences[curr_idx]
            s_tok = tokenizer_bundle.count_ref_tokens(s_text)
            if cur_sents and (token_count + s_tok > target_tokens):
                break
            cur_sents.append(sentences[curr_idx])
            token_count += s_tok
            curr_idx += 1
            if token_count >= target_tokens:
                break

        window_end_rel = cur_sents[-1][1]
        chunk_content = body_text[window_start_rel:window_end_rel]

        # Check if single sentence exceeds target_tokens
        if len(cur_sents) == 1 and token_count > target_tokens:
            offsets = tokenizer_bundle.get_token_offsets(chunk_content)
            t_idx = 0
            while t_idx < len(offsets):
                t_end = min(t_idx + target_tokens, len(offsets))
                sub_st = offsets[t_idx][0]
                sub_ed = offsets[t_end - 1][1]
                sub_slice = chunk_content[sub_st:sub_ed]

                c_start = fm_end + window_start_rel + sub_st
                c_end = fm_end + window_start_rel + sub_ed
                b_start = len(text[:c_start].encode("utf-8"))
                b_end = len(text[:c_end].encode("utf-8"))
                actual_toks = tokenizer_bundle.count_ref_tokens(sub_slice)
                actual_overlap_toks = compute_actual_overlap_tokens(
                    text, last_window_range, (c_start, c_end), tokenizer_bundle
                )
                last_window_range = (c_start, c_end)

                sec_title, sec_path = find_section_title(c_start)
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
                    content_char_end=len(sub_slice),
                    target_url=target_url,
                    segment_sha256=sha256_str(sub_slice),
                )
                cid = compute_chunk_id(
                    CHUNK_SCHEMA_VERSION,
                    rule_fingerprint,
                    "rawpedia",
                    doc_id,
                    [seg],
                    sha256_str(sub_slice),
                )
                meta = {
                    "schema_version": 1,
                    "rule_family": rule_family,
                    "rule_id": rule_id,
                    "rule_fingerprint": rule_fingerprint,
                    "target_tokens": target_tokens,
                    "overlap_tokens": overlap_tokens,
                    "encoder_window_tokens": None,
                    "encoder_overlap_tokens": None,
                    "actual_tokens": actual_toks,
                    "actual_overlap_tokens": actual_overlap_toks,
                    "content_sha256": sha256_str(sub_slice),
                    "source_group_id": doc_id,
                    "product_scope": "rawtherapee_reference",
                    "range_basis": "source_file",
                    "section_kind": "window",
                    "section_path": sec_path,
                    "page_title": page_title,
                    "target_url": target_url,
                    "source_path": file_path,
                    "source_file_sha256": file_sha,
                    "source_segments": [seg.to_dict()],
                }
                chunks.append(
                    Chunk(
                        chunk_id=cid,
                        source_type="rawpedia",
                        doc_id=doc_id,
                        section_title=sec_title,
                        content=sub_slice,
                        char_range=(c_start, c_end),
                        metadata=meta,
                    )
                )
                if t_end >= len(offsets):
                    break
                if overlap_tokens == 0:
                    t_idx = t_end
                else:
                    t_idx = max(t_idx + 1, t_end - overlap_tokens)
            sent_idx += 1
            continue

        c_start = fm_end + window_start_rel
        c_end = fm_end + window_end_rel
        b_start = len(text[:c_start].encode("utf-8"))
        b_end = len(text[:c_end].encode("utf-8"))
        actual_toks = tokenizer_bundle.count_ref_tokens(chunk_content)
        actual_overlap_toks = compute_actual_overlap_tokens(
            text, last_window_range, (c_start, c_end), tokenizer_bundle
        )
        last_window_range = (c_start, c_end)

        sec_title, sec_path = find_section_title(c_start)

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
            content_char_end=len(chunk_content),
            target_url=target_url,
            segment_sha256=sha256_str(chunk_content),
        )

        cid = compute_chunk_id(
            CHUNK_SCHEMA_VERSION,
            rule_fingerprint,
            "rawpedia",
            doc_id,
            [seg],
            sha256_str(chunk_content),
        )
        meta = {
            "schema_version": 1,
            "rule_family": rule_family,
            "rule_id": rule_id,
            "rule_fingerprint": rule_fingerprint,
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
            "encoder_window_tokens": None,
            "encoder_overlap_tokens": None,
            "actual_tokens": actual_toks,
            "actual_overlap_tokens": actual_overlap_toks,
            "content_sha256": sha256_str(chunk_content),
            "source_group_id": doc_id,
            "product_scope": "rawtherapee_reference",
            "range_basis": "source_file",
            "section_kind": "window",
            "section_path": sec_path,
            "page_title": page_title,
            "target_url": target_url,
            "source_path": file_path,
            "source_file_sha256": file_sha,
            "source_segments": [seg.to_dict()],
        }

        chunks.append(
            Chunk(
                chunk_id=cid,
                source_type="rawpedia",
                doc_id=doc_id,
                section_title=sec_title,
                content=chunk_content,
                char_range=(c_start, c_end),
                metadata=meta,
            )
        )

        # Advance sent_idx with overlap
        if curr_idx >= num_sents:
            break
        if overlap_tokens == 0:
            sent_idx = curr_idx
        else:
            overlap_accum = 0
            back_idx = curr_idx - 1
            while back_idx > sent_idx:
                s_tok = tokenizer_bundle.count_ref_tokens(sentences[back_idx][2])
                if overlap_accum + s_tok > overlap_tokens:
                    break
                overlap_accum += s_tok
                back_idx -= 1

            if back_idx == curr_idx - 1 and overlap_accum == 0 and (curr_idx - 1 > sent_idx):
                sent_idx = curr_idx - 1
            else:
                sent_idx = max(sent_idx + 1, back_idx + 1)

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
) -> List[Chunk]:
    """Generate chunks under rule G-B-curated-unit with (target_tokens, overlap_tokens) grid support."""
    rule_family = "G-B-curated-unit"
    rule_id = f"{rule_family}-t{target_tokens}-o{overlap_tokens}"
    rule_fingerprint = f"{rule_id}:{BGE_REVISION}"
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

        b_start = len(body[:c_start].encode("utf-8"))
        b_end = len(body[:c_end].encode("utf-8"))
        slice_tokens = tokenizer_bundle.count_ref_tokens(slice_text)

        if slice_tokens <= target_tokens:
            actual_toks = slice_tokens
            actual_overlap_toks = 0

            seg = SourceSegment(
                doc_id=ref_id,
                source_path=f"data/issues/{rel_snap}",
                source_file_sha256=file_sha,
                json_pointer="/body",
                char_start=c_start,
                char_end=c_end,
                byte_start=b_start,
                byte_end=b_end,
                content_char_start=0,
                content_char_end=len(slice_text),
                target_url=loc.get("url", candidate["url"]),
                segment_sha256=sha256_str(slice_text),
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
                sha256_str(slice_text),
            )
            meta = {
                "schema_version": 1,
                "rule_family": rule_family,
                "rule_id": rule_id,
                "rule_fingerprint": rule_fingerprint,
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
                "encoder_window_tokens": None,
                "encoder_overlap_tokens": None,
                "actual_tokens": actual_toks,
                "actual_overlap_tokens": actual_overlap_toks,
                "content_sha256": sha256_str(slice_text),
                "source_group_id": candidate_id,
                "candidate_id": candidate_id,
                "source_kind": loc.get("source_kind"),
                "product_scope": "art_snapshot",
                "range_basis": "json_body",
                "section_kind": "json_pointer",
                "section_path": ["body"],
                "title": candidate.get("title", ""),
                "target_url": loc.get("url", candidate["url"]),
                "source_segments": [seg.to_dict()],
            }

            chunks.append(
                Chunk(
                    chunk_id=cid,
                    source_type="github",
                    doc_id=ref_id,
                    section_title="/body",
                    content=slice_text,
                    char_range=(c_start, c_end),
                    metadata=meta,
                )
            )
        else:
            s_sents = split_text_by_sentences(slice_text)
            if not s_sents:
                s_sents = [(0, len(slice_text), slice_text)]
            s_idx = 0
            n_s = len(s_sents)
            last_slice_range: Optional[Tuple[int, int]] = None

            while s_idx < n_s:
                cur_pieces = []
                cur_toks = 0
                w_start_rel = s_sents[s_idx][0]
                j = s_idx

                while j < n_s:
                    st_p, ed_p, tx_p = s_sents[j]
                    p_tok = tokenizer_bundle.count_ref_tokens(tx_p)
                    if cur_pieces and (cur_toks + p_tok > target_tokens):
                        break
                    cur_pieces.append(s_sents[j])
                    cur_toks += p_tok
                    j += 1
                    if cur_toks >= target_tokens:
                        break

                w_end_rel = cur_pieces[-1][1]
                sub_text = slice_text[w_start_rel:w_end_rel]

                # Check single long sentence
                if len(cur_pieces) == 1 and cur_toks > target_tokens:
                    offsets = tokenizer_bundle.get_token_offsets(sub_text)
                    t_i = 0
                    while t_i < len(offsets):
                        t_e = min(t_i + target_tokens, len(offsets))
                        sub_st = offsets[t_i][0]
                        sub_ed = offsets[t_e - 1][1]
                        piece = sub_text[sub_st:sub_ed]

                        sub_c_start = c_start + w_start_rel + sub_st
                        sub_c_end = c_start + w_start_rel + sub_ed
                        sub_b_start = len(body[:sub_c_start].encode("utf-8"))
                        sub_b_end = len(body[:sub_c_end].encode("utf-8"))
                        actual_toks = tokenizer_bundle.count_ref_tokens(piece)
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
                            content_char_end=len(piece),
                            target_url=loc.get("url", candidate["url"]),
                            segment_sha256=sha256_str(piece),
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
                            sha256_str(piece),
                        )
                        meta = {
                            "schema_version": 1,
                            "rule_family": rule_family,
                            "rule_id": rule_id,
                            "rule_fingerprint": rule_fingerprint,
                            "target_tokens": target_tokens,
                            "overlap_tokens": overlap_tokens,
                            "encoder_window_tokens": None,
                            "encoder_overlap_tokens": None,
                            "actual_tokens": actual_toks,
                            "actual_overlap_tokens": actual_overlap_toks,
                            "content_sha256": sha256_str(piece),
                            "source_group_id": candidate_id,
                            "candidate_id": candidate_id,
                            "source_kind": loc.get("source_kind"),
                            "product_scope": "art_snapshot",
                            "range_basis": "json_body",
                            "section_kind": "json_pointer",
                            "section_path": ["body"],
                            "title": candidate.get("title", ""),
                            "target_url": loc.get("url", candidate["url"]),
                            "source_segments": [seg.to_dict()],
                        }
                        chunks.append(
                            Chunk(
                                chunk_id=cid,
                                source_type="github",
                                doc_id=ref_id,
                                section_title="/body",
                                content=piece,
                                char_range=(sub_c_start, sub_c_end),
                                metadata=meta,
                            )
                        )
                        if t_e >= len(offsets):
                            break
                        if overlap_tokens == 0:
                            t_i = t_e
                        else:
                            t_i = max(t_i + 1, t_e - overlap_tokens)
                    s_idx += 1
                    continue

                sub_c_start = c_start + w_start_rel
                sub_c_end = c_start + w_end_rel
                sub_b_start = len(body[:sub_c_start].encode("utf-8"))
                sub_b_end = len(body[:sub_c_end].encode("utf-8"))
                actual_toks = tokenizer_bundle.count_ref_tokens(sub_text)
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
                    content_char_end=len(sub_text),
                    target_url=loc.get("url", candidate["url"]),
                    segment_sha256=sha256_str(sub_text),
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
                    sha256_str(sub_text),
                )
                meta = {
                    "schema_version": 1,
                    "rule_family": rule_family,
                    "rule_id": rule_id,
                    "rule_fingerprint": rule_fingerprint,
                    "target_tokens": target_tokens,
                    "overlap_tokens": overlap_tokens,
                    "encoder_window_tokens": None,
                    "encoder_overlap_tokens": None,
                    "actual_tokens": actual_toks,
                    "actual_overlap_tokens": actual_overlap_toks,
                    "content_sha256": sha256_str(sub_text),
                    "source_group_id": candidate_id,
                    "candidate_id": candidate_id,
                    "source_kind": loc.get("source_kind"),
                    "product_scope": "art_snapshot",
                    "range_basis": "json_body",
                    "section_kind": "json_pointer",
                    "section_path": ["body"],
                    "title": candidate.get("title", ""),
                    "target_url": loc.get("url", candidate["url"]),
                    "source_segments": [seg.to_dict()],
                }
                chunks.append(
                    Chunk(
                        chunk_id=cid,
                        source_type="github",
                        doc_id=ref_id,
                        section_title="/body",
                        content=sub_text,
                        char_range=(sub_c_start, sub_c_end),
                        metadata=meta,
                    )
                )

                if j >= n_s:
                    break
                if overlap_tokens == 0:
                    s_idx = j
                else:
                    overlap_accum = 0
                    back_idx = j - 1
                    while back_idx > s_idx:
                        s_tok = tokenizer_bundle.count_ref_tokens(s_sents[back_idx][2])
                        if overlap_accum + s_tok > overlap_tokens:
                            break
                        overlap_accum += s_tok
                        back_idx -= 1
                    if back_idx == j - 1 and overlap_accum == 0 and (j - 1 > s_idx):
                        s_idx = j - 1
                    else:
                        s_idx = max(s_idx + 1, back_idx + 1)

    return chunks


def chunk_github_thread_rule(
    candidate: Dict[str, Any],
    github_dir: Path,
    tokenizer_bundle: TokenizerBundle,
    curated_only: bool = True,
    thread_obj: Optional[Any] = None,
    target_tokens: int = 192,
) -> Chunk:
    """Generate thread chunk under rule G-A-curated-thread or G-A-full-thread."""
    rule_family = "G-A-curated-thread" if curated_only else "G-A-full-thread"
    rule_id = f"{rule_family}-w{target_tokens}-wo0"
    rule_fingerprint = f"{rule_id}:{BGE_REVISION}"
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
        "encoder_window_tokens": target_tokens,
        "encoder_overlap_tokens": 0,
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
        "embedding_policy": "thread_window_mean_v1",
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
