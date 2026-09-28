"""Common utilities for query seed definitions and span extraction."""

from pathlib import Path
import json
from typing import Any, Dict, List, Optional


def slice_rawpedia_span(
    relative_path: str,
    start_marker: str,
    end_marker: str,
) -> str:
    """Extract unique substring from RawPedia markdown file."""
    path = Path("data/rawpedia") / relative_path
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text(encoding="utf-8")
    c1 = text.count(start_marker)
    c2 = text.count(end_marker)
    if c1 != 1:
        raise ValueError(
            f"[{relative_path}] start_marker count={c1} for {repr(start_marker[:40])}"
        )
    if c2 != 1:
        raise ValueError(
            f"[{relative_path}] end_marker count={c2} for {repr(end_marker[:40])}"
        )

    idx1 = text.find(start_marker)
    idx2 = text.find(end_marker, idx1)
    if idx2 == -1:
        raise ValueError(
            f"[{relative_path}] end_marker appears before start_marker"
        )

    span = text[idx1 : idx2 + len(end_marker)]
    raw_bytes = path.read_bytes()
    span_bytes = span.encode("utf-8")
    b_count = raw_bytes.count(span_bytes)
    if b_count != 1:
        raise ValueError(
            f"[{relative_path}] extracted span appears {b_count} times in raw bytes"
        )

    return span


def slice_github_body_span(
    candidate_id: str,
    curated_content_index: int,
    start_marker: str,
    end_marker: str,
) -> str:
    """Extract unique substring from GitHub snapshot /body string within curated range."""
    with open("data/issues/search-candidates.json", "r", encoding="utf-8") as f:
        cands = {c["candidate_id"]: c for c in json.load(f)["candidates"]}

    if candidate_id not in cands:
        raise KeyError(f"Candidate not found: {candidate_id}")

    cand = cands[candidate_id]
    curated_list = cand.get("curated_content", [])
    if not (0 <= curated_content_index < len(curated_list)):
        raise IndexError(f"Invalid curated_content_index: {curated_content_index}")

    cur = curated_list[curated_content_index]
    ref_id = cur["ref_id"]

    # Find source_location for ref_id
    loc = None
    for sl in cand.get("source_locations", []):
        if sl["ref_id"] == ref_id:
            loc = sl
            break
    if not loc:
        raise ValueError(f"No source_location for ref_id {ref_id}")

    snap_rel = loc["snapshot_path"]
    snap_path = Path("data/issues") / snap_rel
    snap_bytes = snap_path.read_bytes()
    doc = json.loads(snap_bytes.decode("utf-8"))
    body = doc.get("body", "")

    # Curated boundaries
    c_start = cur["char_start"]
    c_end = cur["char_end"]
    curated_text = body[c_start:c_end]
    if curated_text != cur["text"]:
        raise ValueError(
            f"curated_text does not match body[{c_start}:{c_end}] for {ref_id}"
        )

    # Find markers within curated_text
    i1 = curated_text.find(start_marker)
    if i1 == -1:
        raise ValueError(
            f"[{ref_id}] start_marker not found in curated_text: {repr(start_marker[:40])}"
        )
    i2 = curated_text.find(end_marker, i1)
    if i2 == -1:
        raise ValueError(
            f"[{ref_id}] end_marker not found in curated_text: {repr(end_marker[:40])}"
        )

    span = curated_text[i1 : i2 + len(end_marker)]

    # Check span uniqueness in body
    if body.count(span) != 1:
        raise ValueError(f"[{ref_id}] span count in body is {body.count(span)} != 1")

    return span
