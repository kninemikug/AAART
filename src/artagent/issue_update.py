"""GitHub 이슈/디스커션 변경분 갱신 및 Chroma 벡터 저장소 반영 모듈.

WBS A-10 (Task 10-2c) 및 docs/T10_2c_execution_plan.md 명세를 준수한다.
완료 원문 입력을 동결·정제하고 차이를 계산하여 세대별 실행 계획·청크를 생성하며,
T09 Chroma 저장소에 멱등적으로 반영·제외하고 vector-state.json을 갱신한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import chromadb
from transformers import AutoTokenizer

from artagent.chunking import TokenizerBundle, chunk_github_curated_group_rule
from artagent.issue_filter import (
    FilterError,
    RULES_VERSION,
    SCHEMA_VERSION as FILTER_SCHEMA_VERSION,
    compute_canonical_manifest_sha256,
    compute_file_sha256,
    filter_corpus,
    load_sources,
)
from artagent.retrieval.embedding import EncoderSession, load_encoder
from artagent.retrieval.provenance import (
    Chunk as T09Chunk,
    canonical_json_bytes,
    canonical_json_str,
    serialize_metadata,
    sha256_bytes,
    sha256_str,
    validate_provenance,
)
from artagent.retrieval.store import RetrievalStore, open_store
from artagent.retrieval.types import IndexReport, RetrievalSpec, SourceKey, load_spec

PLAN_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1


def now_iso_utc() -> str:
    """현재 UTC 시각을 ISO-8601 형식 문자열로 반환."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_json_atomic(path: Path, data: Any) -> None:
    """내용이 바뀐 JSON만 원자적으로 저장하고 무변경 파일의 시각을 보존."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_bytes() == content.encode("utf-8"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def compute_generation_id(
    store_identifier: str,
    sync_state_sha256: str,
    snapshot_manifest_sha256: str,
    curation_sha256: str,
    filter_rules_version: str,
    rule_fingerprint: str,
    reference_sha256: str,
    protocol_sha256: str,
) -> str:
    """동결 입력 및 계약 지문들로부터 결정론적 입력 내용 식별값 계산."""
    payload = {
        "curation_sha256": curation_sha256,
        "filter_rules_version": filter_rules_version,
        "protocol_sha256": protocol_sha256,
        "reference_sha256": reference_sha256,
        "rule_fingerprint": rule_fingerprint,
        "snapshot_manifest_sha256": snapshot_manifest_sha256,
        "store_identifier": store_identifier,
        "sync_state_sha256": sync_state_sha256,
    }
    canonical_bytes = canonical_json_bytes(payload)
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return f"gen_{digest[:16]}"


def compute_candidate_sha256(candidate: dict[str, Any]) -> str:
    """후보 객체 전체의 canonical JSON SHA256 계산."""
    return sha256_bytes(canonical_json_bytes(candidate))


def compute_chunks_payload_sha256(chunks: Sequence[T09Chunk], spec: RetrievalSpec) -> str:
    """청크셋의 직렬화 payload canonical digest 계산 (T09 입력 지문 계약과 동일)."""
    records = [
        {
            "chunk_id": chunk.chunk_id,
            "document": chunk.content,
            "metadata": serialize_metadata(chunk, spec, excluded=False),
        }
        for chunk in sorted(chunks, key=lambda c: c.chunk_id)
    ]
    return sha256_str(canonical_json_str(records))


def compute_stored_records_canonical_fingerprint(
    stored_entry: Optional[dict[str, Any]],
) -> Optional[str]:
    """저장소 레코드를 chunk_id 순으로 정렬한 ID·본문·전체 metadata·excluded 상태의 canonical JSON 해시."""
    if not stored_entry or not stored_entry.get("chunk_ids"):
        return None
    zipped = list(zip(
        stored_entry["chunk_ids"],
        stored_entry["documents"],
        stored_entry["metadatas"],
    ))
    zipped.sort(key=lambda x: x[0])
    records_rep = [
        {
            "chunk_id": cid,
            "document": doc,
            "metadata": meta,
            "excluded": bool(meta.get("excluded", False)),
        }
        for cid, doc, meta in zipped
    ]
    return sha256_str(canonical_json_str(records_rep))


def compute_chunks_canonical_fingerprint(
    chunks: Sequence[T09Chunk],
    spec: RetrievalSpec,
    excluded: bool = False,
) -> str:
    """목표 청크셋에 대해 chunk_id 순으로 정렬한 ID·본문·전체 metadata·excluded 상태의 canonical JSON 해시."""
    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)
    records_rep = [
        {
            "chunk_id": c.chunk_id,
            "document": c.content,
            "metadata": serialize_metadata(c, spec, excluded=excluded),
            "excluded": excluded,
        }
        for c in sorted_chunks
    ]
    return sha256_str(canonical_json_str(records_rep))


def compute_excluded_target_fingerprint(
    stored_entry: Optional[dict[str, Any]],
) -> Optional[str]:
    """exclude 작업의 목표 지문: 기존 청크들의 metadata에 excluded=True를 적용한 canonical JSON 해시."""
    if not stored_entry or not stored_entry.get("chunk_ids"):
        return None
    zipped = list(zip(
        stored_entry["chunk_ids"],
        stored_entry["documents"],
        stored_entry["metadatas"],
    ))
    zipped.sort(key=lambda x: x[0])
    records_rep = [
        {
            "chunk_id": cid,
            "document": doc,
            "metadata": {**meta, "excluded": True},
            "excluded": True,
        }
        for cid, doc, meta in zipped
    ]
    return sha256_str(canonical_json_str(records_rep))


def validate_store_before_access(
    persist_dir: Path,
    spec: RetrievalSpec,
    require_rawpedia_count: bool = True,
) -> RetrievalStore:
    """Chroma 저장소 접근 전 경로 유효성, 계약 일치 및 T09 초기 저장소(RawPedia 141청크) 존재를 검증."""
    pdir = Path(persist_dir).resolve()
    if not pdir.is_dir():
        raise FileNotFoundError(f"Chroma 영속 디렉터리를 찾을 수 없습니다: {pdir}")

    db_file = pdir / "chroma.sqlite3"
    if not db_file.is_file():
        raise ValueError(
            f"Chroma DB 파일(chroma.sqlite3)이 존재하지 않는 빈 디렉터리입니다: {pdir}"
        )

    # PersistentClient로 컬렉션 존재 여부 확인
    client = chromadb.PersistentClient(path=str(pdir))
    existing_cols = [c.name for c in client.list_collections()]
    if spec.collection_name not in existing_cols:
        raise ValueError(
            f"T09 컬렉션 '{spec.collection_name}'이 존재하지 않습니다: {pdir}"
        )

    store = open_store(pdir, spec)
    store._validate_collection_contract()

    if require_rawpedia_count:
        rawpedia_res = store.collection.get(where={"source_type": "rawpedia"}, include=[])
        rawpedia_count = len(rawpedia_res.get("ids", []))
        if rawpedia_count != spec.rawpedia_expected_count:
            raise ValueError(
                f"T09 초기 저장소 검증 실패: RawPedia 청크 수 불일치 (실제 {rawpedia_count} != 기대 {spec.rawpedia_expected_count})"
            )

    return store


def validate_store_matching(
    target_persist_dir: Path,
    plan_store: dict[str, Any],
    vector_state_store: Optional[dict[str, Any]],
    spec: RetrievalSpec,
) -> None:
    """계획·실행인자·vector-state의 persist 경로·컬렉션·계약 지문 전수 대조. 불일치 시 쓰기 전 거부."""
    target_resolved = Path(target_persist_dir).resolve()

    # 1. 계획과 실행 인자 대조
    plan_persist = Path(plan_store.get("persist_dir", "")).resolve()
    if plan_persist != target_resolved:
        raise ValueError(
            f"저장소 경로 불일치: 계획 ({plan_persist}) != 실행 인자 ({target_resolved})"
        )
    if plan_store.get("collection_name") != spec.collection_name:
        raise ValueError(
            f"컬렉션 이름 불일치: 계획 ({plan_store.get('collection_name')}) != 기대 ({spec.collection_name})"
        )
    if plan_store.get("reference_sha256") != spec.reference_sha256:
        raise ValueError("계획의 reference_sha256가 spec 계약과 불일치합니다.")
    if plan_store.get("protocol_sha256") != spec.protocol_sha256:
        raise ValueError("계획의 protocol_sha256가 spec 계약과 불일치합니다.")

    # 2. vector-state가 이미 존재하는 경우 저장소 정보 대조
    if vector_state_store:
        state_persist = Path(vector_state_store.get("persist_dir", "")).resolve()
        if state_persist != target_resolved:
            raise ValueError(
                f"vector-state 저장소 경로 불일치: 상태 ({state_persist}) != 대상 ({target_resolved})"
            )
        if vector_state_store.get("collection_name") != spec.collection_name:
            raise ValueError("vector-state의 collection_name이 대상 저장소와 불일치합니다.")
        if vector_state_store.get("reference_sha256") != spec.reference_sha256:
            raise ValueError("vector-state의 reference_sha256가 spec 계약과 불일치합니다.")
        if vector_state_store.get("protocol_sha256") != spec.protocol_sha256:
            raise ValueError("vector-state의 protocol_sha256가 spec 계약과 불일치합니다.")


def generate_candidate_chunks(
    candidate: dict[str, Any],
    github_dir: Path,
    tokenizer_bundle: TokenizerBundle,
    spec: RetrievalSpec,
) -> list[T09Chunk]:
    """T08-2 선정 규칙 G-C-curated-group-t1024-o64로 청크를 생성하고 T09 Chunk로 변환."""
    expected_rule_fp = (
        f"{spec.github_rule}:{spec.guard_group}:{spec.physical_embedding_policy}:{spec.ref_tokenizer_revision}"
    )
    raw_chunks = chunk_github_curated_group_rule(
        candidate,
        github_dir=github_dir,
        tokenizer_bundle=tokenizer_bundle,
        target_tokens=1024,
        overlap_tokens=64,
        guard_group=spec.guard_group,
        physical_embedding_policy=spec.physical_embedding_policy,
        encoder_window_tokens=spec.encoder_window_tokens,
        encoder_overlap_tokens=spec.encoder_overlap_tokens,
    )
    t09_chunks: list[T09Chunk] = []
    for rc in raw_chunks:
        c_dict = rc.to_dict()
        meta = c_dict.get("metadata", {})
        if meta.get("rule_fingerprint") != expected_rule_fp:
            raise ValueError(
                f"청크 규칙 지문 불일치: 실제 {meta.get('rule_fingerprint')} != 기대 {expected_rule_fp}"
            )
        t09_c = T09Chunk.from_dict(c_dict)
        t09_chunks.append(t09_c)
    return t09_chunks


def freeze_inputs(
    input_dir: Path,
    curation_path: Path,
    target_issues_dir: Path,
) -> None:
    """원문 sync-state, snapshots 및 curation-decisions 파일을 세대별 디렉터리에 바이트 그대로 보존."""
    target_issues_dir.mkdir(parents=True, exist_ok=True)
    target_snapshots_dir = target_issues_dir / "snapshots"
    target_snapshots_dir.mkdir(parents=True, exist_ok=True)

    src_sync = input_dir / "sync-state.json"
    dst_sync = target_issues_dir / "sync-state.json"
    shutil.copy2(src_sync, dst_sync)

    dst_curation = target_issues_dir / "curation-decisions.json"
    shutil.copy2(curation_path, dst_curation)

    src_snapshots = input_dir / "snapshots"
    if src_snapshots.is_dir():
        for root, dirs, files in os.walk(src_snapshots):
            rel_root = Path(root).relative_to(src_snapshots)
            curr_dst_dir = target_snapshots_dir / rel_root
            curr_dst_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.endswith(".json"):
                    shutil.copy2(Path(root) / f, curr_dst_dir / f)


def get_existing_github_records(store: RetrievalStore) -> dict[str, dict[str, Any]]:
    """Chroma에서 github source_type의 레코드들을 읽어 candidate_id별로 묶어 반환."""
    col = store.collection
    results = col.get(
        where={"source_type": "github"},
        include=["documents", "metadatas"],
    )
    by_candidate: dict[str, dict[str, Any]] = {}
    ids = results.get("ids", []) or []
    docs = results.get("documents", []) or []
    metas = results.get("metadatas", []) or []
    for cid, doc, meta in zip(ids, docs, metas):
        cand_id = meta.get("doc_id") or meta.get("source_group_id")
        if not cand_id:
            continue
        if cand_id not in by_candidate:
            by_candidate[cand_id] = {
                "chunk_ids": [],
                "documents": [],
                "metadatas": [],
                "all_excluded": True,
                "any_excluded": False,
            }
        entry = by_candidate[cand_id]
        entry["chunk_ids"].append(cid)
        entry["documents"].append(doc)
        entry["metadatas"].append(meta)
        is_ex = bool(meta.get("excluded", False))
        if not is_ex:
            entry["all_excluded"] = False
        else:
            entry["any_excluded"] = True
    return by_candidate


def records_match_chunks(
    stored_entry: Optional[dict[str, Any]],
    chunks: Sequence[T09Chunk],
    spec: RetrievalSpec,
) -> bool:
    """저장된 Chroma 레코드가 주어진 청크셋과 본문·메타데이터·활성 상태까지 정확히 일치하는지 검사."""
    if not stored_entry:
        return False
    if set(stored_entry["chunk_ids"]) != {c.chunk_id for c in chunks}:
        return False
    if stored_entry.get("any_excluded", False):
        return False
    stored_map = {
        cid: (doc, meta)
        for cid, doc, meta in zip(
            stored_entry["chunk_ids"],
            stored_entry["documents"],
            stored_entry["metadatas"],
        )
    }
    for c in chunks:
        expected_meta = serialize_metadata(c, spec, excluded=False)
        if c.chunk_id not in stored_map:
            return False
        st_doc, st_meta = stored_map[c.chunk_id]
        if st_doc != c.content:
            return False
        if canonical_json_str(st_meta) != canonical_json_str(expected_meta):
            return False
    return True


def _validate_generation_manifest(
    gen_dir: Path, plan_doc: dict[str, Any],
) -> dict[str, Any]:
    """불변 세대의 모든 필수 파일과 식별값을 쓰기 전에 검증."""
    manifest_path = gen_dir / "generation-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"generation-manifest.json 누락: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("generation-manifest 스키마 버전 불일치")
    if manifest.get("generation_id") != plan_doc.get("generation_id"):
        raise ValueError("generation-manifest 세대 식별값 불일치")
    if "input_generation_id" in plan_doc and (
        manifest.get("input_generation_id") != plan_doc["input_generation_id"]
    ):
        raise ValueError("generation-manifest 입력 내용 식별값 불일치")
    if manifest.get("inventory_manifest_sha256") != plan_doc.get("input_manifest"):
        raise ValueError("generation-manifest 원문 매니페스트 불일치")
    files_sha = manifest.get("files")
    if not isinstance(files_sha, dict):
        raise ValueError("generation-manifest의 files가 객체 형식이 아닙니다.")
    required_files = (
        "update-plan.json", "chunks.jsonl", "search-candidates.json",
        "filter-report.json", "source/data/issues/sync-state.json",
        "source/data/issues/curation-decisions.json",
    )
    for name in required_files:
        expected_sha = files_sha.get(name)
        if (
            not isinstance(expected_sha, str) or len(expected_sha) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha)
        ):
            raise ValueError(f"generation-manifest 필수 SHA 누락/손상: {name}")
        path = gen_dir / name
        if not path.is_file() or sha256_bytes(path.read_bytes()) != expected_sha:
            raise ValueError(f"{name} 파일이 manifest와 불일치합니다.")
    for name in ("include_candidate_ids", "include_operation_ids", "chunk_doc_ids"):
        ids = manifest.get(name)
        if (
            not isinstance(ids, list) or any(not isinstance(cid, str) or not cid for cid in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValueError(f"generation-manifest ID 집합 누락/손상: {name}")
    return manifest


def validate_plan_preflight(
    plan_doc: dict[str, Any],
    plan_path: Path,
    spec: RetrievalSpec,
) -> tuple[Path, dict[str, list[T09Chunk]]]:
    """Apply 실행 전 계획 문서, 동결 원문 매니페스트, 저장소 계약 및 chunks.jsonl 무결성 전수 검증."""
    if plan_doc.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError(f"계획 스키마 버전 불일치: {plan_doc.get('schema_version')}")

    gen_id = plan_doc.get("generation_id")
    if not gen_id:
        raise ValueError("계획에 generation_id가 누락되었습니다.")
    gen_dir = plan_path.parent
    gen_manifest = _validate_generation_manifest(gen_dir, plan_doc)

    source_root = Path(plan_doc.get("source_root", "")).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"동결 source_root 디렉터리를 찾을 수 없습니다: {source_root}")

    frozen_issues = source_root / "data" / "issues"
    if not frozen_issues.is_dir():
        raise FileNotFoundError(f"동결 data/issues 디렉터리를 찾을 수 없습니다: {frozen_issues}")

    # 동결본 SHA 검증
    sync_file = frozen_issues / "sync-state.json"
    if not sync_file.is_file():
        raise FileNotFoundError(f"동결 sync-state.json 누락: {sync_file}")
    if compute_file_sha256(sync_file.read_bytes()) != plan_doc.get("sync_state_sha256"):
        raise ValueError("동결 sync-state.json SHA256 불일치")

    curation_file = frozen_issues / "curation-decisions.json"
    if not curation_file.is_file():
        raise FileNotFoundError(f"동결 curation-decisions.json 누락: {curation_file}")
    if compute_file_sha256(curation_file.read_bytes()) != plan_doc.get("curation_sha256"):
        raise ValueError("동결 curation-decisions.json SHA256 불일치")

    frozen_inv = load_sources(frozen_issues)
    if frozen_inv.snapshot_manifest_sha256 != plan_doc.get("input_manifest"):
        raise ValueError(
            f"동결 입력 매니페스트 불일치: 실제 {frozen_inv.snapshot_manifest_sha256} != 기대 {plan_doc.get('input_manifest')}"
        )

    # chunks.jsonl 파일 무결성 및 SHA 대조
    chunks_jsonl_path = gen_dir / "chunks.jsonl"
    if not chunks_jsonl_path.is_file():
        raise FileNotFoundError(f"chunks.jsonl 파일을 찾을 수 없습니다: {chunks_jsonl_path}")

    chunks_bytes = chunks_jsonl_path.read_bytes()
    expected_chunks_sha = plan_doc.get("chunks_sha256")
    if expected_chunks_sha and sha256_bytes(chunks_bytes) != expected_chunks_sha:
        raise ValueError("chunks.jsonl 파일 SHA256 불일치")

    chunks_by_cand: dict[str, list[T09Chunk]] = {}
    for line in chunks_bytes.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = T09Chunk.from_dict(json.loads(line))
        except Exception as e:
            raise ValueError(f"chunks.jsonl 파싱 오류: {e}") from e
        chunks_by_cand.setdefault(c.doc_id, []).append(c)

    operations = plan_doc.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("계획의 operations가 리스트 형식이 아닙니다.")

    # 작업 ID 중복 검사
    op_ids = [op.get("candidate_id") for op in operations if isinstance(op, dict)]
    if len(op_ids) != len(set(op_ids)):
        raise ValueError("계획의 operations에 중복된 candidate_id가 존재합니다.")

    # 미지원 action 및 필수 필드 검사
    valid_actions = {"create", "update", "exclude", "noop"}
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError("작업 항목이 객체 형식이 아닙니다.")
        act = op.get("action")
        if act not in valid_actions:
            raise ValueError(f"지원하지 않는 작업 action 감지: {act}")
        if not op.get("candidate_id"):
            raise ValueError("작업에 candidate_id가 누락되었습니다.")
        disposition = op.get("disposition")
        if disposition not in {"include", "exclude", "review"}:
            raise ValueError(f"지원하지 않는 정제 판정: {disposition}")
        if (act in {"create", "update"} and disposition != "include") or (
            act == "exclude" and disposition == "include"
        ):
            raise ValueError("작업 action과 정제 판정이 불일치합니다.")
        required = (
            "record_key", "thread_sha256", "candidate_sha256", "reason_codes",
            "base_payload_fingerprint", "target_payload_fingerprint",
            "t09_operation_fingerprint",
        )
        if any(name not in op for name in required):
            raise ValueError("계획 작업의 필수 필드가 누락되었습니다.")

    # include 후보 ID, include 작업 ID, 청크 doc_id 집합 일치 검사
    include_op_ids = {op["candidate_id"] for op in operations if op.get("disposition") == "include"}
    chunk_doc_ids = set(chunks_by_cand.keys())
    if include_op_ids != chunk_doc_ids:
        raise ValueError(
            f"include 작업 ID 집합과 청크 doc_id 집합이 불일치합니다: 작업({len(include_op_ids)}) != 청크({len(chunk_doc_ids)})"
        )

    candidates_doc = json.loads((gen_dir / "search-candidates.json").read_text(encoding="utf-8"))
    candidate_ids = {candidate["candidate_id"] for candidate in candidates_doc["candidates"]}
    if any(include_op_ids != set(gen_manifest[name]) for name in (
        "include_candidate_ids", "include_operation_ids", "chunk_doc_ids",
    )) or include_op_ids != candidate_ids:
        raise ValueError("계획의 include 작업 ID 집합이 generation-manifest/정제 후보와 불일치합니다.")

    for op in operations:
        if op.get("disposition") == "include":
            cid = op["candidate_id"]
            cand_chunks = chunks_by_cand.get(cid, [])
            if not cand_chunks:
                raise ValueError(f"계획의 include 후보 {cid} 청크가 chunks.jsonl에 없습니다.")
            actual_ids = [c.chunk_id for c in cand_chunks]
            if actual_ids != op.get("chunk_ids"):
                raise ValueError(f"청크 ID 집합 불일치: {cid}")
            actual_payload = compute_chunks_payload_sha256(cand_chunks, spec)
            if actual_payload != op.get("chunks_payload_sha256"):
                raise ValueError(f"청크 payload SHA256 불일치: {cid}")
            if compute_chunks_canonical_fingerprint(cand_chunks, spec) != op["target_payload_fingerprint"]:
                raise ValueError(f"목표 payload 지문 불일치: {cid}")
            for chunk in cand_chunks:
                validate_provenance(chunk, source_root=source_root)
            expected_operation_fp = actual_payload
        else:
            expected_operation_fp = sha256_str(canonical_json_str({
                "source_type": "github", "source_group_id": op["candidate_id"],
            }))
        if op["t09_operation_fingerprint"] != expected_operation_fp:
            raise ValueError(f"T09 작업 지문 불일치: {op['candidate_id']}")

    return source_root, chunks_by_cand


# ---------------------------------------------------------------------------
# Prepare 동작
# ---------------------------------------------------------------------------


def _select_generation_id(
    input_generation_id: str, base_generation: Optional[str], output_dir: Path,
) -> str:
    """현재 완료 계획과 같은 기준의 미완료 계획만 재사용하고 새 적용은 구분."""
    generations = output_dir / "index-updates"
    if base_generation is not None:
        completed_plan = generations / base_generation / "update-plan.json"
        if completed_plan.is_file():
            completed = json.loads(completed_plan.read_text(encoding="utf-8"))
            completed_input = completed.get("input_generation_id", completed.get("generation_id"))
            if completed_input == input_generation_id:
                return base_generation

    # 내용 지문을 세대 ID로 사용한 기존 계획도 기준 세대가 맞으면 복구·재사용.
    legacy_dir = generations / input_generation_id
    legacy_plan = legacy_dir / "update-plan.json"
    if legacy_dir.exists():
        if not legacy_plan.is_file():
            return input_generation_id  # 기존 세대 검증에서 누락을 거부한다.
        legacy = json.loads(legacy_plan.read_text(encoding="utf-8"))
        if legacy.get("base_generation") == base_generation:
            return input_generation_id

    if base_generation is None:
        return input_generation_id
    digest = sha256_bytes(canonical_json_bytes({
        "input_generation_id": input_generation_id,
        "base_generation": base_generation,
    }))
    return f"gen_{digest[:16]}"


def prepare_generation(
    source_root: Path,
    input_dir: Path,
    curation_path: Path,
    reference_path: Path,
    persist_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """완료 원문 입력을 검증·동결하고 정제·청킹하여 세대별 실행 계획 update-plan.json 생성.
    
    같은 기준의 재시도 및 현재 완료 입력 재실행은 기존 계획을 재사용하며,
    다른 세대 이후 같은 입력으로 복원하면 현재 기준으로 새 계획을 만든다.
    손상된 기존 세대 발견 시 덮어쓰지 않고 즉시 오류로 중단한다.
    """
    input_dir = Path(input_dir).resolve()
    curation_path = Path(curation_path).resolve()
    reference_path = Path(reference_path).resolve()
    persist_dir = Path(persist_dir).resolve()
    output_dir = Path(output_dir).resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"입력 디렉터리를 찾을 수 없습니다: {input_dir}")
    if not curation_path.is_file():
        raise FileNotFoundError(f"검토 결정 파일을 찾을 수 없습니다: {curation_path}")
    if not reference_path.is_file():
        raise FileNotFoundError(f"인계 참조 파일을 찾을 수 없습니다: {reference_path}")

    spec = load_spec(reference_path)

    # T09 저장소 계약 및 사전 유효성 검증 (RawPedia 141청크 존재 확인)
    store = validate_store_before_access(persist_dir, spec, require_rawpedia_count=True)

    # 1. 원문 입력 전수 검증
    inventory = load_sources(input_dir)
    sync_bytes = (input_dir / "sync-state.json").read_bytes()
    sync_state_sha256 = compute_file_sha256(sync_bytes)
    curation_bytes = curation_path.read_bytes()
    curation_sha256 = compute_file_sha256(curation_bytes)
    snapshot_manifest_sha256 = inventory.snapshot_manifest_sha256

    rule_fingerprint = (
        f"{spec.github_rule}:{spec.guard_group}:{spec.physical_embedding_policy}:{spec.ref_tokenizer_revision}"
    )
    store_identifier = f"{spec.collection_name}:{spec.model_id}:{spec.dimension}"

    input_generation_id = compute_generation_id(
        store_identifier=store_identifier,
        sync_state_sha256=sync_state_sha256,
        snapshot_manifest_sha256=snapshot_manifest_sha256,
        curation_sha256=curation_sha256,
        filter_rules_version=RULES_VERSION,
        rule_fingerprint=rule_fingerprint,
        reference_sha256=spec.reference_sha256,
        protocol_sha256=spec.protocol_sha256,
    )

    plan_store = {
        "persist_dir": str(persist_dir),
        "collection_name": spec.collection_name,
        "reference_sha256": spec.reference_sha256,
        "protocol_sha256": spec.protocol_sha256,
        "contract_fingerprint": rule_fingerprint,
    }
    vector_state_path = output_dir / "vector-state.json"
    vector_state_data: Optional[dict[str, Any]] = None
    base_state_sha256 = None
    if vector_state_path.is_file():
        state_bytes = vector_state_path.read_bytes()
        vector_state_data = json.loads(state_bytes.decode("utf-8"))
        validate_store_matching(persist_dir, plan_store, vector_state_data.get("store"), spec)
        base_state_sha256 = sha256_bytes(state_bytes)
    base_generation = vector_state_data.get("last_completed_generation") if vector_state_data else None
    gen_id = _select_generation_id(input_generation_id, base_generation, output_dir)

    gen_dir = output_dir / "index-updates" / gen_id
    plan_path = gen_dir / "update-plan.json"
    chunks_jsonl_path = gen_dir / "chunks.jsonl"
    frozen_source_root = gen_dir / "source"
    frozen_issues_dir = frozen_source_root / "data" / "issues"

    # [동결 입력 무결성 및 기존 세대 검증]: 이미 존재하는 경우 손상 여부 확인
    if gen_dir.exists():
        # 동결 원문 및 파일 검증
        if not (plan_path.is_file() and chunks_jsonl_path.is_file() and frozen_issues_dir.is_dir()):
            raise ValueError(
                f"손상된 기존 세대 디렉터리 감지 (필수 파일 누락): {gen_dir}. 덮어쓰지 않고 중단합니다."
            )
        try:
            existing_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if existing_plan.get("generation_id") != gen_id:
                raise ValueError("기존 세대의 generation_id 불일치")
            if existing_plan.get("input_generation_id", input_generation_id) != input_generation_id:
                raise ValueError("기존 세대의 입력 내용 식별값 불일치")
            # 계획의 핵심 SHA 및 매니페스트 대조
            if existing_plan.get("input_manifest") != snapshot_manifest_sha256:
                raise ValueError("기존 세대의 input_manifest 불일치")
            if existing_plan.get("sync_state_sha256") != sync_state_sha256:
                raise ValueError("기존 세대의 sync_state_sha256 불일치")
            if existing_plan.get("curation_sha256") != curation_sha256:
                raise ValueError("기존 세대의 curation_sha256 불일치")

            # chunks.jsonl 바이트 SHA 대조
            chunks_bytes = chunks_jsonl_path.read_bytes()
            exp_chunks_sha = existing_plan.get("chunks_sha256")
            if exp_chunks_sha and sha256_bytes(chunks_bytes) != exp_chunks_sha:
                raise ValueError("기존 세대의 chunks.jsonl 파일 SHA256 손상")

            # 동결본 원문 매니페스트 대조
            frozen_inv = load_sources(frozen_issues_dir)
            if frozen_inv.snapshot_manifest_sha256 != snapshot_manifest_sha256:
                raise ValueError("기존 동결본의 snapshot_manifest_sha256 불일치")
            validate_store_matching(persist_dir, existing_plan["store"], None, spec)
            validate_plan_preflight(existing_plan, plan_path, spec)

            # 정상 세대 재사용: 파일 덮어쓰기 없이 기존 요약 반환
            ops = existing_plan.get("operations", [])
            s_created = sum(1 for op in ops if op["action"] == "create")
            s_updated = sum(1 for op in ops if op["action"] == "update")
            s_excluded = sum(1 for op in ops if op["action"] == "exclude")
            s_unchanged = sum(1 for op in ops if op["action"] == "noop")
            return {
                "generation_id": gen_id,
                "plan_path": str(plan_path),
                "created": s_created,
                "updated": s_updated,
                "excluded": s_excluded,
                "unchanged": s_unchanged,
                "unapplied": s_created + s_updated + s_excluded,
            }
        except Exception as e:
            # 손상된 세대는 덮어쓰지 않고 명시적으로 오류 중단!
            raise ValueError(
                f"손상된 기존 세대 디렉터리 감지: {gen_dir} ({e}). 덮어쓰지 않고 중단합니다."
            ) from e

    gen_dir.mkdir(parents=True, exist_ok=True)

    # 2. 동결 디렉터리 구축 및 매니페스트 대조
    freeze_inputs(input_dir, curation_path, frozen_issues_dir)
    frozen_inv = load_sources(frozen_issues_dir)
    if frozen_inv.snapshot_manifest_sha256 != snapshot_manifest_sha256:
        raise ValueError("동결 디렉터리의 snapshot_manifest_sha256가 원본과 일치하지 않습니다.")

    # 3. 동결 입력으로 filter_corpus 실행
    frozen_curation_path = frozen_issues_dir / "curation-decisions.json"
    cands_doc, report_doc = filter_corpus(frozen_issues_dir, frozen_curation_path)

    save_json_atomic(gen_dir / "search-candidates.json", cands_doc)
    save_json_atomic(gen_dir / "filter-report.json", report_doc)

    # 4. 기준 토크나이저 로드 및 선정 청크 생성
    ref_tok = AutoTokenizer.from_pretrained(
        spec.ref_tokenizer_id,
        revision=spec.ref_tokenizer_revision,
    )
    tokenizer_bundle = TokenizerBundle(bge_tokenizer=ref_tok)

    candidates = cands_doc.get("candidates", [])
    candidates_sorted = sorted(
        candidates,
        key=lambda c: (c.get("source_type", ""), int(c.get("source_number", 0))),
    )

    candidate_chunks_map: dict[str, list[T09Chunk]] = {}
    all_chunks: list[T09Chunk] = []

    for cand in candidates_sorted:
        cand_id = cand["candidate_id"]
        chunks = generate_candidate_chunks(
            cand,
            github_dir=frozen_issues_dir,
            tokenizer_bundle=tokenizer_bundle,
            spec=spec,
        )
        if not chunks:
            raise ValueError(f"유효 include 후보의 청크셋이 비어 있습니다: {cand_id}")
        for chunk in chunks:
            validate_provenance(chunk, source_root=frozen_source_root)
        candidate_chunks_map[cand_id] = chunks
        all_chunks.extend(chunks)

    # chunks.jsonl 저장 및 SHA 계산
    lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in all_chunks]
    chunks_content = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    chunks_jsonl_path.write_bytes(chunks_content)
    chunks_sha256 = sha256_bytes(chunks_content)

    # 5. 현재 기준 세대의 Chroma 저장소 상태 읽기
    existing_stored_github = get_existing_github_records(store)
    existing_items: dict[str, dict[str, Any]] = (
        vector_state_data.get("items", {}) if vector_state_data else {}
    )

    # 6. 작업 산출 (operations)
    operations: list[dict[str, Any]] = []
    include_cand_ids = {cand["candidate_id"] for cand in candidates}

    summary_created = 0
    summary_updated = 0
    summary_excluded = 0
    summary_unchanged = 0

    for cand in candidates_sorted:
        cand_id = cand["candidate_id"]
        record_key = cand.get("source_record_key") or cand.get("record_key", "")
        thread_sha256 = cand.get("metadata", {}).get("thread_sha256") or cand.get("thread_sha256", "")
        cand_sha256 = compute_candidate_sha256(cand)
        chunks = candidate_chunks_map[cand_id]
        chunk_ids = [c.chunk_id for c in chunks]
        payload_sha256 = compute_chunks_payload_sha256(chunks, spec)
        t09_fingerprint = payload_sha256

        stored_rec = existing_stored_github.get(cand_id)
        state_item = existing_items.get(cand_id)

        base_fp = compute_stored_records_canonical_fingerprint(stored_rec)
        target_fp = compute_chunks_canonical_fingerprint(chunks, spec, excluded=False)

        # 멱등/무변경 판정 (플랜 §3.2 139줄, §3.3 150줄)
        is_identical = False
        if records_match_chunks(stored_rec, chunks, spec):
            if state_item and state_item.get("status") == "active":
                if (
                    state_item.get("chunks_payload_sha256") == payload_sha256
                    and state_item.get("candidate_sha256") == cand_sha256
                    and state_item.get("thread_sha256") == thread_sha256
                ):
                    is_identical = True
            elif state_item is None:
                is_identical = True

        if is_identical:
            action = "noop"
            summary_unchanged += 1
        elif stored_rec and stored_rec["chunk_ids"]:
            action = "update"
            summary_updated += 1
        elif state_item and state_item.get("status") in ("active", "excluded"):
            action = "update"
            summary_updated += 1
        else:
            action = "create"
            summary_created += 1

        operations.append({
            "candidate_id": cand_id,
            "record_key": record_key,
            "thread_sha256": thread_sha256,
            "disposition": "include",
            "reason_codes": [],
            "action": action,
            "candidate_sha256": cand_sha256,
            "base_payload_fingerprint": base_fp,
            "target_payload_fingerprint": target_fp,
            "existing_payload_fingerprint": base_fp,
            "chunk_ids": chunk_ids,
            "chunks_payload_sha256": payload_sha256,
            "t09_operation_fingerprint": t09_fingerprint,
        })

    # 이전에 활성이었으나 현재 exclude 또는 review인 후보 확인
    all_known_candidate_ids = set(existing_items.keys()) | set(existing_stored_github.keys())
    excluded_or_stale_ids = sorted(all_known_candidate_ids - include_cand_ids)

    report_threads = report_doc.get("threads", [])
    report_map_by_key = {t.get("record_key", ""): t for t in report_threads}
    report_map_by_cand = {t.get("candidate_id", ""): t for t in report_threads if t.get("candidate_id")}

    for cand_id in excluded_or_stale_ids:
        state_item = existing_items.get(cand_id)
        record_key = state_item.get("record_key") if state_item else None
        t_info = report_map_by_cand.get(cand_id)
        if not t_info and record_key:
            t_info = report_map_by_key.get(record_key)
        if not t_info:
            parts = cand_id.split(":")
            guess_key = f"{parts[-2]}:{parts[-1]}" if len(parts) >= 4 else cand_id
            t_info = report_map_by_key.get(guess_key)
            if not record_key:
                record_key = guess_key

        disp = (t_info.get("decision") or t_info.get("disposition")) if t_info else "review"
        reason_codes = t_info.get("reason_codes", []) if t_info else ["EXCLUDED"]
        thread_sha256 = t_info.get("thread_sha256", "") if t_info else ""

        stored_rec = existing_stored_github.get(cand_id)
        state_item = existing_items.get(cand_id)

        was_active = False
        if stored_rec and not stored_rec["all_excluded"] and len(stored_rec["chunk_ids"]) > 0:
            was_active = True
        elif state_item and state_item.get("status") == "active":
            was_active = True

        t09_fingerprint = sha256_str(
            canonical_json_str({"source_type": "github", "source_group_id": cand_id})
        )

        base_fp = compute_stored_records_canonical_fingerprint(stored_rec)
        target_fp = compute_excluded_target_fingerprint(stored_rec) if was_active else base_fp

        if was_active:
            action = "exclude"
            summary_excluded += 1
        else:
            action = "noop"
            summary_unchanged += 1

        operations.append({
            "candidate_id": cand_id,
            "record_key": record_key,
            "thread_sha256": thread_sha256,
            "disposition": disp,
            "reason_codes": reason_codes,
            "action": action,
            "candidate_sha256": state_item.get("candidate_sha256", "") if state_item else "",
            "base_payload_fingerprint": base_fp,
            "target_payload_fingerprint": target_fp,
            "existing_payload_fingerprint": base_fp,
            "chunk_ids": [],
            "chunks_payload_sha256": None,
            "t09_operation_fingerprint": t09_fingerprint,
        })

    # 7. 실행 계획 update-plan.json 조립 및 저장
    plan_doc = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generation_id": gen_id,
        "input_generation_id": input_generation_id,
        "repository": str(inventory.state.get("repository", "artraweditor/ART")),
        "sync_state_sha256": sync_state_sha256,
        "input_manifest": snapshot_manifest_sha256,
        "curation_sha256": curation_sha256,
        "chunks_sha256": chunks_sha256,
        "source_root": str(frozen_source_root.resolve()),
        "base_generation": base_generation,
        "base_state_sha256": base_state_sha256,
        "store": plan_store,
        "operations": operations,
    }

    save_json_atomic(plan_path, plan_doc)

    # 8. 불변 generation-manifest.json 생성 및 저장
    include_candidate_ids = sorted([c["candidate_id"] for c in candidates])
    include_operation_ids = sorted([op["candidate_id"] for op in operations if op.get("disposition") == "include"])
    chunk_doc_ids = sorted(list({c.doc_id for c in all_chunks}))

    if set(include_candidate_ids) != set(include_operation_ids) or set(include_candidate_ids) != set(chunk_doc_ids):
        raise ValueError(
            f"ID 집합 불일치: 후보({len(include_candidate_ids)}) != 작업({len(include_operation_ids)}) != 청크({len(chunk_doc_ids)})"
        )

    manifest_doc = {
        "schema_version": 1,
        "generation_id": gen_id,
        "input_generation_id": input_generation_id,
        "created_at": now_iso_utc(),
        "files": {
            "update-plan.json": sha256_bytes(plan_path.read_bytes()),
            "chunks.jsonl": chunks_sha256,
            "search-candidates.json": sha256_bytes((gen_dir / "search-candidates.json").read_bytes()),
            "filter-report.json": sha256_bytes((gen_dir / "filter-report.json").read_bytes()),
            "source/data/issues/sync-state.json": sync_state_sha256,
            "source/data/issues/curation-decisions.json": curation_sha256,
        },
        "inventory_manifest_sha256": snapshot_manifest_sha256,
        "include_candidate_ids": include_candidate_ids,
        "include_operation_ids": include_operation_ids,
        "chunk_doc_ids": chunk_doc_ids,
    }
    save_json_atomic(gen_dir / "generation-manifest.json", manifest_doc)

    return {
        "generation_id": gen_id,
        "plan_path": str(plan_path),
        "created": summary_created,
        "updated": summary_updated,
        "excluded": summary_excluded,
        "unchanged": summary_unchanged,
        "unapplied": summary_created + summary_updated + summary_excluded,
    }


# ---------------------------------------------------------------------------
# Apply 동작
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PreparedOperation:
    operation: dict[str, Any]
    chunks: list[T09Chunk]
    stored_entry: dict[str, Any]
    target_matched: bool
    needs_recovery: bool


def _read_stored_group(store: RetrievalStore, candidate_id: str) -> dict[str, Any]:
    records = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": candidate_id}]},
        include=["documents", "metadatas"],
    )
    metadatas = records.get("metadatas") or []
    return {
        "chunk_ids": records.get("ids", []),
        "documents": records.get("documents") or [],
        "metadatas": metadatas,
        "all_excluded": all(meta.get("excluded") is True for meta in metadatas),
        "any_excluded": any(meta.get("excluded") is True for meta in metadatas),
    }


def _matches_target(
    op: dict[str, Any], entry: dict[str, Any],
    chunks: list[T09Chunk], spec: RetrievalSpec,
) -> bool:
    if compute_stored_records_canonical_fingerprint(entry) != op["target_payload_fingerprint"]:
        return False
    if op["disposition"] == "include":
        return bool(chunks) and records_match_chunks(entry, chunks, spec)
    return entry["all_excluded"]


def _prepare_store_operations(
    store: RetrievalStore, operations: list[dict[str, Any]],
    chunks_by_cand: dict[str, list[T09Chunk]], spec: RetrievalSpec,
) -> list[_PreparedOperation]:
    """모든 그룹의 기준/목표를 쓰기 전에 검증하고 중단 작업을 맨 앞에 배치."""
    state = store._get_store_state()
    if state not in {"ready", "updating"}:
        raise RuntimeError(f"저장소가 준비되지 않았습니다. 현재 상태: {state}")

    pending_id = None
    if state == "updating":
        metadata = store._current_collection().metadata or {}
        pending = next((
            op for op in operations
            if op["candidate_id"] == metadata.get("source_group_id")
            and metadata.get("source_type") == "github"
            and op["t09_operation_fingerprint"] == metadata.get("input_fingerprint")
            and metadata.get("operation") == (
                "replace_source" if op["disposition"] == "include" else "exclude_source"
            )
        ), None)
        if pending is None:
            raise RuntimeError(
                "미완료 updating 상태와 일치하는 계획 작업이 없습니다. 중단합니다."
            )
        pending_id = pending["candidate_id"]

    prepared = []
    for op in operations:
        cid = op["candidate_id"]
        entry = _read_stored_group(store, cid)
        chunks = chunks_by_cand.get(cid, [])
        needs_recovery = cid == pending_id
        target_matched = _matches_target(op, entry, chunks, spec)
        base_matched = (
            compute_stored_records_canonical_fingerprint(entry)
            == op["base_payload_fingerprint"]
        )
        # 동일 T09 작업만 중간 upsert/delete 상태를 복구할 수 있다.
        if not needs_recovery and not (target_matched or base_matched):
            raise RuntimeError(
                f"오래된 계획 거부: 저장소 레코드 지문이 준비 시점의 기준/목표 상태와 "
                f"불일치합니다 ({cid}). 최신 레코드를 보존하고 쓰기 전 거부합니다."
            )
        if op["action"] == "noop" and not target_matched and not needs_recovery:
            raise RuntimeError(f"noop/목표 상태 읽기 검증 실패 ({cid})")
        prepared.append(_PreparedOperation(op, chunks, entry, target_matched, needs_recovery))

    return sorted(prepared, key=lambda item: not item.needs_recovery)


def _apply_prepared_operation(
    prepared: _PreparedOperation, store: RetrievalStore,
    session: EncoderSession, source_root: Path, spec: RetrievalSpec,
) -> tuple[Optional[IndexReport], dict[str, Any]]:
    """필요한 그룹만 T09 API로 반영하고 저장된 목표 상태를 읽어 검증."""
    op = prepared.operation
    if prepared.target_matched and not prepared.needs_recovery:
        return None, prepared.stored_entry

    cid = op["candidate_id"]
    key = SourceKey("github", cid)
    if op["disposition"] == "include":
        report = store.replace_source(
            key=key, chunks=prepared.chunks, session=session, source_root=source_root,
        )
    else:
        report = store.exclude_source(key)
    if report.status != "success":
        raise RuntimeError(f"Chroma 작업 실패: {cid}")
    if store._get_store_state() != "ready":
        raise RuntimeError(f"Chroma 작업 후 저장소 상태가 ready가 아닙니다: {cid}")

    entry = _read_stored_group(store, cid)
    if not _matches_target(op, entry, prepared.chunks, spec):
        raise RuntimeError(f"Chroma 저장 후 목표 레코드 검증 실패: {cid}")
    return report, entry


def _checkpoint_applied_item(
    state_path: Path, state_doc: dict[str, Any], op: dict[str, Any],
    stored_entry: dict[str, Any], plan_doc: dict[str, Any],
    source_root: Path, applied_at: str,
) -> bool:
    """검증된 항목만 확정하며 기존 성공 기록과 제외 tombstone을 보존."""
    cid = op["candidate_id"]
    if op["disposition"] == "include":
        status = "active"
    else:
        status = "excluded" if stored_entry["chunk_ids"] else "never_indexed"
    core = {
        "candidate_id": cid,
        "record_key": op["record_key"],
        "thread_sha256": op["thread_sha256"],
        "candidate_sha256": op["candidate_sha256"],
        "disposition": op["disposition"],
        "reason_codes": op["reason_codes"],
        "status": status,
        "chunk_ids": op.get("chunk_ids", []),
        "chunks_payload_sha256": op.get("chunks_payload_sha256"),
    }
    items = state_doc.get("items", {})
    previous = items.get(cid)
    if previous is not None and all(previous.get(name) == value for name, value in core.items()):
        return False

    item = {
        **core,
        "applied_generation": plan_doc["generation_id"],
        "applied_input_manifest": plan_doc["input_manifest"],
        "source_root": str(source_root),
        "applied_at": applied_at,
    }
    next_state = {**state_doc, "items": {**items, cid: item}}
    save_json_atomic(state_path, next_state)
    # 디스크 체크포인트가 성공한 경우에만 메모리 상태도 전진한다.
    state_doc.update(next_state)
    return True


def _load_vector_state(
    state_path: Path, plan_doc: dict[str, Any], persist_dir: Path, spec: RetrievalSpec,
) -> dict[str, Any]:
    if not state_path.is_file():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "store": {
                "persist_dir": str(persist_dir),
                "collection_name": spec.collection_name,
                "reference_sha256": spec.reference_sha256,
                "protocol_sha256": spec.protocol_sha256,
            },
            "last_completed_generation": None,
            "last_completed_at": None,
            "items": {},
        }

    state_bytes = state_path.read_bytes()
    state = json.loads(state_bytes.decode("utf-8"))
    validate_store_matching(persist_dir, plan_doc["store"], state.get("store"), spec)
    generation = plan_doc["generation_id"]
    current = state.get("last_completed_generation")
    base = plan_doc.get("base_generation")
    base_sha = plan_doc.get("base_state_sha256")
    partial_retry = current == base and any(
        item.get("applied_generation") == generation for item in state.get("items", {}).values()
    )
    fresh_apply = current == base and (
        base_sha is None or base_sha == sha256_bytes(state_bytes)
    )
    if current != generation and not partial_retry and not fresh_apply:
        raise RuntimeError(
            f"오래된 계획 거부: 현재 저장소 완료 세대({current})가 계획의 기준 세대({base})와 "
            "다르거나 외부 실행에 의해 이미 갱신되었습니다. 현재 레코드를 보존하고 거부합니다."
        )
    return state


def apply_plan(
    plan_path: Path,
    persist_dir: Path,
    reference_path: Path,
) -> dict[str, Any]:
    """전수 검증 → 중단 작업 우선 복구 → 순차 반영/체크포인트 → 완료 확정."""
    plan_path = Path(plan_path).resolve()
    persist_dir = Path(persist_dir).resolve()
    reference_path = Path(reference_path).resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"실행 계획 파일을 찾을 수 없습니다: {plan_path}")
    if not reference_path.is_file():
        raise FileNotFoundError(f"인계 참조 파일을 찾을 수 없습니다: {reference_path}")

    spec = load_spec(reference_path)
    plan_doc = json.loads(plan_path.read_text(encoding="utf-8"))
    source_root, chunks_by_cand = validate_plan_preflight(plan_doc, plan_path, spec)
    validate_store_matching(persist_dir, plan_doc["store"], None, spec)
    gen_dir = plan_path.parent
    state_path = gen_dir.parent.parent / "vector-state.json"
    operations = plan_doc["operations"]
    now_ts = now_iso_utc()
    counts = {"created": 0, "updated": 0, "excluded": 0, "unchanged": 0}
    results: dict[str, dict[str, Any]] = {}
    completion_error = None

    store = validate_store_before_access(persist_dir, spec, require_rawpedia_count=True)
    # T09와 동일한 저장소 잠금 아래 사전 검증과 반영을 연속 수행한다.
    with store._lock:
        state_doc = _load_vector_state(state_path, plan_doc, persist_dir, spec)
        prepared_ops = _prepare_store_operations(store, operations, chunks_by_cand, spec)
        session = load_encoder(spec)
        failed_id = None
        for prepared in prepared_ops:
            op = prepared.operation
            cid = op["candidate_id"]
            try:
                report, entry = _apply_prepared_operation(
                    prepared, store, session, source_root, spec,
                )
                had_checkpoint = cid in state_doc.get("items", {})
                checkpoint_changed = _checkpoint_applied_item(
                    state_path, state_doc, op, entry, plan_doc, source_root, now_ts,
                )
                if report is not None:
                    status = "success"
                    report_data = asdict(report)
                    if op["disposition"] != "include":
                        counts["excluded"] += 1
                    elif op["action"] == "create":
                        counts["created"] += 1
                    else:
                        counts["updated"] += 1
                elif checkpoint_changed and had_checkpoint:
                    status = "metadata_only"
                    report_data = {"skipped_embedding": True}
                    counts["updated"] += 1
                else:
                    status = "noop"
                    report_data = {}
                    counts["unchanged"] += 1
                results[cid] = {
                    "candidate_id": cid, "action": op["action"],
                    "status": status, "report": report_data,
                    "verification": True, "error": None,
                }
            except Exception as error:
                failed_id = cid
                results[cid] = {
                    "candidate_id": cid, "action": op["action"],
                    "status": "failed", "report": {},
                    "verification": False, "error": str(error),
                }
                break

        # 보고서는 계획 순서로 유지하고, 복구 우선 처리 후 미실행 항목도 집계한다.
        for op in operations:
            cid = op["candidate_id"]
            if cid not in results:
                results[cid] = {
                    "candidate_id": cid, "action": op["action"],
                    "status": "unapplied", "report": {}, "verification": False,
                    "error": f"선행 작업({failed_id}) 실패로 인해 실행되지 않음",
                }
        unapplied = sum(not result["verification"] for result in results.values())
        if unapplied == 0:
            try:
                final_state = store._get_store_state()
                if final_state != "ready":
                    raise RuntimeError(f"배치 완료 후 저장소 상태가 ready가 아닙니다: {final_state}")
                store.search("test search query", session=session)
                if state_doc.get("last_completed_generation") != plan_doc["generation_id"]:
                    completed_state = {
                        **state_doc,
                        "last_completed_generation": plan_doc["generation_id"],
                        "last_completed_at": now_ts,
                    }
                    save_json_atomic(state_path, completed_state)
                    state_doc.update(completed_state)
            except Exception as error:
                completion_error = str(error)
        total_active = store._active_count()

    status = "success" if unapplied == 0 and completion_error is None else "partial"
    summary = {**counts, "unapplied": unapplied, "total_active": total_active}
    apply_report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generation_id": plan_doc["generation_id"],
        "plan_path": str(plan_path),
        "applied_at": now_ts,
        "status": status,
        "summary": summary,
        "operations": [results[op["candidate_id"]] for op in operations],
    }
    if completion_error is not None:
        apply_report["completion_error"] = completion_error
    save_json_atomic(gen_dir / "apply-report.json", apply_report)
    return {
        "generation_id": plan_doc["generation_id"],
        "plan_path": str(plan_path),
        "status": status,
        **summary,
    }
