from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class RetrievalSpec:
    """T09 공통 검색/적재 규격 계약."""

    model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    model_revision: str = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    ref_tokenizer_id: str = "BAAI/bge-small-en-v1.5"
    ref_tokenizer_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    dimension: int = 384
    dtype: str = "float32"
    normalize_embeddings: bool = True
    rawpedia_rule: str = "R-C-heading-window-t8192-o64"
    rawpedia_expected_count: int = 141
    rawpedia_expected_sha256: str = "8e8f163d2ce8da99fec3dc7e38652ea3d7aecb35997dc20a3d2202c09753c4cd"
    github_rule: str = "G-C-curated-group-t1024-o64"
    github_expected_count: int = 13
    github_expected_sha256: str = "7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571"
    total_expected_count: int = 154
    guard_group: str = "pooled-common-256"
    physical_embedding_policy: str = "chunk_window_mean_v2"
    thread_embedding_policy: str = "thread_window_mean_v2"
    encoder_window_tokens: int = 224
    encoder_overlap_tokens: int = 0
    max_header_tokens: int = 32
    max_seq_length: int = 256
    doc_prefix: str = ""
    query_prefix: str = ""
    collection_name: str = "art_retrieval_t09_v1"
    space: str = "cosine"
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 200
    hnsw_max_neighbors: int = 16
    hnsw_num_threads: int = 1
    retrieval_schema_version: int = 1
    reference_sha256: str = "f21a1e65299e5595f9a2cc384abef22648ffb96553a0997a04cbbd451ab2fd23"
    protocol_sha256: str = "3694eb3cb0a8b8e989e6bc828adf1f067b4f988f9be0a04a4d43507850412dc5"


@dataclass(frozen=True)
class SourceKey:
    """원문 문서 또는 후보 항목 갱신·제외 식별 키."""

    source_type: str
    source_group_id: str

    def __post_init__(self) -> None:
        if self.source_type not in ("rawpedia", "github"):
            raise ValueError(f"지원하지 않는 source_type: {self.source_type}")
        if not self.source_group_id:
            raise ValueError("source_group_id는 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class SearchHit:
    """검색 결과 단위."""

    rank: int
    chunk_id: str
    source_type: str
    doc_id: str
    source_group_id: str
    section_title: str
    content: str
    content_sha256: str
    source_segments: list[dict[str, Any]]
    original_metadata: dict[str, Any]
    distance: float
    distance_text: str


@dataclass
class IndexReport:
    """적재, 갱신, 제외 작업 보고서."""

    source_key: Optional[SourceKey] = None
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    excluded: int = 0
    total_active: int = 0
    status: str = "success"


def load_spec(reference_path: Path) -> RetrievalSpec:
    """인계 reference JSON을 읽고 스펙 계약을 생성 및 검증."""
    ref_file = Path(reference_path).resolve()
    if not ref_file.is_file():
        raise FileNotFoundError(f"Reference file not found: {ref_file}")

    content_bytes = ref_file.read_bytes()
    file_sha = hashlib.sha256(content_bytes).hexdigest()
    data = json.loads(content_bytes.decode("utf-8"))

    selected = data.get("selected", {})
    chunks = data.get("chunks", {})
    protocol_sha = data.get("protocol_sha256", "")

    return RetrievalSpec(
        model_id=selected.get("model_id", "sentence-transformers/all-MiniLM-L6-v2"),
        model_revision=selected.get("model_revision", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"),
        rawpedia_rule=selected.get("rawpedia_rule", "R-C-heading-window-t8192-o64"),
        rawpedia_expected_count=chunks.get("rawpedia", {}).get("count", 141),
        rawpedia_expected_sha256=chunks.get("rawpedia", {}).get("sha256", "8e8f163d2ce8da99fec3dc7e38652ea3d7aecb35997dc20a3d2202c09753c4cd"),
        github_rule=selected.get("github_rule", "G-C-curated-group-t1024-o64"),
        github_expected_count=chunks.get("github", {}).get("count", 13),
        github_expected_sha256=chunks.get("github", {}).get("sha256", "7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571"),
        guard_group=selected.get("guard_group", "pooled-common-256"),
        physical_embedding_policy=selected.get("physical_embedding_policy", "chunk_window_mean_v2"),
        thread_embedding_policy=selected.get("thread_embedding_policy", "thread_window_mean_v2"),
        encoder_window_tokens=selected.get("encoder_window_tokens", 224),
        encoder_overlap_tokens=selected.get("encoder_overlap_tokens", 0),
        reference_sha256=file_sha,
        protocol_sha256=protocol_sha,
    )
