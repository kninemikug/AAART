from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from .types import RetrievalSpec


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_json_str(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Chunk:
    """T09 공통 청크 표현."""

    chunk_id: str
    source_type: str
    doc_id: str
    section_title: str
    content: str
    char_range: tuple[int, int]
    metadata: dict[str, Any]

    @property
    def rule_id(self) -> str:
        return self.metadata.get("rule_id", "")

    @property
    def rule_fingerprint(self) -> str:
        return self.metadata.get("rule_fingerprint", "")

    @property
    def content_sha256(self) -> str:
        return self.metadata.get("content_sha256", sha256_str(self.content))

    @property
    def range_basis(self) -> str:
        return self.metadata.get("range_basis", "")

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, d: Mapping[str, Any]) -> Chunk:
        c_range = d.get("char_range")
        if c_range is not None:
            char_range = (int(c_range[0]), int(c_range[1]))
        else:
            char_range = (0, len(d.get("content", "")))
        return cls(
            chunk_id=str(d["chunk_id"]),
            source_type=str(d["source_type"]),
            doc_id=str(d["doc_id"]),
            section_title=str(d.get("section_title", "")),
            content=str(d["content"]),
            char_range=char_range,
            metadata=dict(d.get("metadata", {})),
        )


def compute_chunk_id(
    schema_version: str,
    rule_fingerprint: str,
    source_type: str,
    doc_id: str,
    source_segments: Sequence[Mapping[str, Any]],
    content_sha256: str,
) -> str:
    """T08-2 계약과 100% 동일한 결정론적 chunk ID 계산."""
    seg_idents = []
    for s in source_segments:
        seg_idents.append({
            "doc_id": s.get("doc_id"),
            "ref_id": s.get("ref_id"),
            "segment_sha256": s.get("segment_sha256"),
            "char_start": s.get("char_start"),
            "char_end": s.get("char_end"),
            "content_char_start": s.get("content_char_start"),
            "content_char_end": s.get("content_char_end"),
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


def validate_provenance(chunk: Chunk, source_root: Path) -> None:
    """원문 위치 및 청크 무결성 전수 검증."""
    root_resolved = Path(source_root).resolve()
    meta = chunk.metadata

    if chunk.source_type not in ("rawpedia", "github"):
        raise ValueError(f"유효하지 않은 source_type: {chunk.source_type}")

    content = chunk.content
    calc_content_sha = sha256_str(content)
    if calc_content_sha != meta.get("content_sha256"):
        raise ValueError(f"Chunk content SHA256 불일치: {chunk.chunk_id}")

    segments_data = meta.get("source_segments", [])
    if not segments_data:
        raise ValueError(f"source_segments 누락: {chunk.chunk_id}")

    range_basis = meta.get("range_basis")
    if range_basis not in ("source_file", "json_body", "serialized_content"):
        raise ValueError(f"알 수 없는 range_basis: {range_basis}")

    # chunk_id 계산 검증
    schema_ver = "t08c:v1"
    rule_fp = meta.get("rule_fingerprint", "")
    expected_chunk_id = compute_chunk_id(
        schema_version=schema_ver,
        rule_fingerprint=rule_fp,
        source_type=chunk.source_type,
        doc_id=chunk.doc_id,
        source_segments=segments_data,
        content_sha256=calc_content_sha,
    )
    if chunk.chunk_id != expected_chunk_id:
        raise ValueError(f"Chunk ID 불일치: 실제 {chunk.chunk_id} != 기대 {expected_chunk_id}")

    for s in segments_data:
        rel_path = s.get("source_path", "")
        file_path = (root_resolved / rel_path).resolve()

        # 경로가 source_root 하위인지 검사
        try:
            file_path.relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"source_root 외부 경로 거부: {rel_path}")

        if not file_path.is_file():
            raise FileNotFoundError(f"원문 파일 없음: {file_path}")

        file_bytes = file_path.read_bytes()
        actual_file_sha = sha256_bytes(file_bytes)
        if actual_file_sha != s.get("source_file_sha256"):
            raise ValueError(f"원문 파일 SHA 불일치: {rel_path} in {chunk.chunk_id}")

        json_ptr = s.get("json_pointer")
        if json_ptr in (None, ""):
            original_text = file_bytes.decode("utf-8")
        elif json_ptr == "/body":
            data = json.loads(file_bytes.decode("utf-8"))
            original_text = data.get("body", "")
            if s.get("body_sha256") and sha256_str(original_text) != s.get("body_sha256"):
                raise ValueError(f"JSON body SHA 불일치: {rel_path} in {chunk.chunk_id}")
        else:
            raise ValueError(f"지원하지 않는 json_pointer: {json_ptr}")

        char_start = s["char_start"]
        char_end = s["char_end"]
        if char_start < 0 or char_end > len(original_text) or char_start > char_end:
            raise ValueError(f"잘못된 문자 범위 [{char_start}, {char_end}) in {rel_path}")

        orig_slice = original_text[char_start:char_end]
        if sha256_str(orig_slice) != s["segment_sha256"]:
            raise ValueError(f"세그먼트 SHA 불일치 in {s.get('doc_id')}")

        byte_start = len(original_text[:char_start].encode("utf-8"))
        byte_end = len(original_text[:char_end].encode("utf-8"))
        if byte_start != s["byte_start"] or byte_end != s["byte_end"]:
            raise ValueError(
                f"바이트 오프셋 불일치 in {s.get('doc_id')}: "
                f"기대 [{byte_start}, {byte_end}) != 실제 [{s['byte_start']}, {s['byte_end']})"
            )

        c_start = s["content_char_start"]
        c_end = s["content_char_end"]
        if c_start < 0 or c_end > len(content) or c_start > c_end:
            raise ValueError(f"잘못된 청크 본문 범위 [{c_start}, {c_end}) in {chunk.chunk_id}")

        chunk_slice = content[c_start:c_end]
        if chunk_slice != orig_slice:
            raise ValueError(f"청크 본문 슬라이스와 원문 슬라이스 불일치 in {s.get('doc_id')}")


def load_selected_chunks(manifest_path: Path, spec: RetrievalSpec, source_root: Path) -> list[Chunk]:
    """manifest.json을 읽고 선정된 두 규칙의 청크를 로드 및 전수 검증."""
    manifest_file = Path(manifest_path).resolve()
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_file}")

    manifest_data = json.loads(manifest_file.read_bytes())
    rules_dict = manifest_data.get("chunking_rules", {})

    all_chunks: list[Chunk] = []

    for source, rule, exp_count, exp_sha in [
        ("rawpedia", spec.rawpedia_rule, spec.rawpedia_expected_count, spec.rawpedia_expected_sha256),
        ("github", spec.github_rule, spec.github_expected_count, spec.github_expected_sha256),
    ]:
        if rule not in rules_dict:
            raise ValueError(f"규칙 {rule}이 manifest에 없습니다.")

        rule_info = rules_dict[rule]
        raw_path = rule_info.get("file_path") or rule_info.get("output_file")
        if not raw_path:
            raise ValueError(f"규칙 {rule}의 파일 경로 정보가 없습니다.")
        jsonl_path = Path(raw_path).resolve()
        if not jsonl_path.is_file():
            # 상대 경로 해석 fallback
            jsonl_path = (manifest_file.parent / raw_path).resolve()
        if not jsonl_path.is_file():
            raise FileNotFoundError(f"청크 JSONL 파일 없음: {jsonl_path}")

        file_bytes = jsonl_path.read_bytes()
        file_sha = sha256_bytes(file_bytes)
        if file_sha != exp_sha:
            raise ValueError(f"{source} 청크 파일 SHA 불일치: 실제 {file_sha} != 기대 {exp_sha}")

        source_chunks: list[Chunk] = []
        for line in file_bytes.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            chunk = Chunk.from_dict(item)
            validate_provenance(chunk, source_root)
            source_chunks.append(chunk)

        if len(source_chunks) != exp_count:
            raise ValueError(f"{source} 청크 개수 불일치: 실제 {len(source_chunks)} != 기대 {exp_count}")

        all_chunks.extend(source_chunks)

    if len(all_chunks) != spec.total_expected_count:
        raise ValueError(f"총 청크 개수 불일치: 실제 {len(all_chunks)} != 기대 {spec.total_expected_count}")

    return all_chunks


def serialize_metadata(
    chunk: Chunk, spec: RetrievalSpec, *, excluded: bool = False
) -> dict[str, Union[str, int, float, bool]]:
    """Chroma 저장을 위한 평탄화 메타데이터 변환."""
    meta = chunk.metadata
    source_group_id = chunk.doc_id

    # canonical json 직렬화
    char_range_json = canonical_json_str(list(chunk.char_range))
    source_segments_json = canonical_json_str(meta.get("source_segments", []))
    original_metadata_json = canonical_json_str(meta)

    return {
        "source_type": chunk.source_type,
        "doc_id": chunk.doc_id,
        "source_group_id": source_group_id,
        "section_title": chunk.section_title or "",
        "rule_id": meta.get("rule_id", ""),
        "rule_fingerprint": meta.get("rule_fingerprint", ""),
        "content_sha256": meta.get("content_sha256", sha256_str(chunk.content)),
        "range_basis": meta.get("range_basis", ""),
        "char_range_json": char_range_json,
        "source_segments_json": source_segments_json,
        "original_metadata_json": original_metadata_json,
        "retrieval_schema_version": spec.retrieval_schema_version,
        "reference_sha256": spec.reference_sha256,
        "excluded": excluded,
    }


def deserialize_chunk(chunk_id: str, content: str, metadata: Mapping[str, object]) -> Chunk:
    """Chroma 메타데이터로부터 원래 Chunk 복원 및 정합성 검증."""
    orig_meta_json = str(metadata["original_metadata_json"])
    orig_meta: dict[str, Any] = json.loads(orig_meta_json)

    # original_metadata_json의 source_segments와 source_segments_json 일치 검사
    stored_segments_json = str(metadata["source_segments_json"])
    orig_segments_json = canonical_json_str(orig_meta.get("source_segments", []))
    if stored_segments_json != orig_segments_json:
        raise ValueError(f"source_segments 불일치: {chunk_id}")

    char_range_list = json.loads(str(metadata["char_range_json"]))
    char_range = (int(char_range_list[0]), int(char_range_list[1]))

    return Chunk(
        chunk_id=chunk_id,
        source_type=str(metadata["source_type"]),
        doc_id=str(metadata["doc_id"]),
        section_title=str(metadata.get("section_title", "")),
        content=content,
        char_range=char_range,
        metadata=orig_meta,
    )
