"""GitHub 이슈/디스커션 변경분 갱신 및 Chroma 벡터 저장소 반영 모듈.

WBS A-10 (Task 10-2c) 및 docs/T10_2c_execution_plan.md 명세를 준수한다.
완료 원문 입력을 동결·정제하고 차이를 계산하여 세대별 실행 계획·청크를 생성하며,
T09 Chroma 저장소에 멱등적으로 반영·제외하고 vector-state.json을 갱신한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    """JSON 데이터를 파일에 원자적으로 저장 (임시 파일 작성 후 교체)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
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
    """동결 입력 및 계약 지문들로부터 결정론적 generation_id 계산."""
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
    """청크셋의 직렬화 payload canonical digest 계산 (T09 입력 지문과 동일)."""
    records = [
        {
            "chunk_id": chunk.chunk_id,
            "document": chunk.content,
            "metadata": serialize_metadata(chunk, spec, excluded=False),
        }
        for chunk in sorted(chunks, key=lambda c: c.chunk_id)
    ]
    return sha256_str(canonical_json_str(records))


def validate_store_before_access(
    persist_dir: Path,
    spec: RetrievalSpec,
    require_rawpedia_count: bool = True,
) -> RetrievalStore:
    """Chroma 저장소 접근 전 경로 유효성, 계약 일치 및 T09 초기 저장소(RawPedia 141청크) 존재를 검증.
    
    경로 오타나 빈 디렉터리에 빈 저장소를 자동 생성하고 성공하는 문제를 차단한다.
    """
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

    source_root = Path(plan_doc.get("source_root", "")).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"동결 source_root 디렉터리를 찾을 수 없습니다: {source_root}")

    frozen_issues = source_root / "data" / "issues"
    if not frozen_issues.is_dir():
        raise FileNotFoundError(f"동결 data/issues 디렉터리를 찾을 수 없습니다: {frozen_issues}")

    frozen_inv = load_sources(frozen_issues)
    if frozen_inv.snapshot_manifest_sha256 != plan_doc.get("input_manifest"):
        raise ValueError(
            f"동결 입력 매니페스트 불일치: 실제 {frozen_inv.snapshot_manifest_sha256} != 기대 {plan_doc.get('input_manifest')}"
        )

    store_info = plan_doc.get("store", {})
    if store_info.get("reference_sha256") != spec.reference_sha256:
        raise ValueError("계획의 reference_sha256가 spec과 불일치합니다.")
    if store_info.get("protocol_sha256") != spec.protocol_sha256:
        raise ValueError("계획의 protocol_sha256가 spec과 불일치합니다.")

    gen_dir = plan_path.parent
    chunks_jsonl_path = gen_dir / "chunks.jsonl"
    if not chunks_jsonl_path.is_file():
        raise FileNotFoundError(f"chunks.jsonl 파일을 찾을 수 없습니다: {chunks_jsonl_path}")

    chunks_by_cand: dict[str, list[T09Chunk]] = {}
    for line in chunks_jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        c = T09Chunk.from_dict(json.loads(line))
        chunks_by_cand.setdefault(c.doc_id, []).append(c)

    for op in plan_doc.get("operations", []):
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

    return source_root, chunks_by_cand


# ---------------------------------------------------------------------------
# Prepare 동작
# ---------------------------------------------------------------------------


def prepare_generation(
    source_root: Path,
    input_dir: Path,
    curation_path: Path,
    reference_path: Path,
    persist_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """완료 원문 입력을 검증·동결하고 정제·청킹하여 세대별 실행 계획 update-plan.json 생성.
    
    동일 입력에 대한 재실행 시 기존 계획 및 청크 파일을 덮어쓰지 않고 재사용한다.
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

    gen_id = compute_generation_id(
        store_identifier=store_identifier,
        sync_state_sha256=sync_state_sha256,
        snapshot_manifest_sha256=snapshot_manifest_sha256,
        curation_sha256=curation_sha256,
        filter_rules_version=RULES_VERSION,
        rule_fingerprint=rule_fingerprint,
        reference_sha256=spec.reference_sha256,
        protocol_sha256=spec.protocol_sha256,
    )

    gen_dir = output_dir / "index-updates" / gen_id
    plan_path = gen_dir / "update-plan.json"
    chunks_jsonl_path = gen_dir / "chunks.jsonl"

    # [동일 입력 재사용]: 이미 해당 세대의 계획과 청크가 존재하고 매니페스트가 일치하면 덮어쓰지 않고 반환
    if plan_path.is_file() and chunks_jsonl_path.is_file():
        try:
            existing_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if existing_plan.get("input_manifest") == snapshot_manifest_sha256:
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
        except Exception:
            pass  # 기존 파일 손상 시 새로 생성

    gen_dir.mkdir(parents=True, exist_ok=True)
    frozen_source_root = gen_dir / "source"
    frozen_issues_dir = frozen_source_root / "data" / "issues"

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

    # chunks.jsonl 저장
    lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in all_chunks]
    chunks_content = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    chunks_jsonl_path.write_bytes(chunks_content)

    # 5. 기존 vector-state.json 및 Chroma 저장소 상태 읽기
    vector_state_path = output_dir / "vector-state.json"
    vector_state_data: Optional[dict[str, Any]] = None
    if vector_state_path.is_file():
        try:
            vector_state_data = json.loads(vector_state_path.read_text(encoding="utf-8"))
        except Exception:
            vector_state_data = None

    base_generation = vector_state_data.get("last_completed_generation") if vector_state_data else None
    base_state_sha256 = (
        sha256_bytes(vector_state_path.read_bytes()) if vector_state_path.is_file() else None
    )

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

        existing_fp = None
        if stored_rec and stored_rec["chunk_ids"]:
            existing_fp = sha256_str(
                canonical_json_str(sorted(stored_rec["chunk_ids"]))
            )

        # 멱등/무변경 판정
        is_identical = False
        if records_match_chunks(stored_rec, chunks, spec):
            if state_item and state_item.get("status") == "active":
                if state_item.get("chunks_payload_sha256") == payload_sha256:
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
            "existing_payload_fingerprint": existing_fp,
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
            "existing_payload_fingerprint": None,
            "chunk_ids": [],
            "chunks_payload_sha256": None,
            "t09_operation_fingerprint": t09_fingerprint,
        })

    # 7. 실행 계획 update-plan.json 조립 및 저장
    plan_doc = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generation_id": gen_id,
        "repository": str(inventory.state.get("repository", "artraweditor/ART")),
        "input_manifest": snapshot_manifest_sha256,
        "source_root": str(frozen_source_root.resolve()),
        "base_generation": base_generation,
        "base_state_sha256": base_state_sha256,
        "store": {
            "persist_dir": str(persist_dir.resolve()),
            "collection_name": spec.collection_name,
            "reference_sha256": spec.reference_sha256,
            "protocol_sha256": spec.protocol_sha256,
            "contract_fingerprint": rule_fingerprint,
        },
        "operations": operations,
    }

    save_json_atomic(plan_path, plan_doc)

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


def apply_plan(
    plan_path: Path,
    persist_dir: Path,
    reference_path: Path,
) -> dict[str, Any]:
    """저장된 update-plan.json을 읽고 Chroma 저장소에 갱신/제외를 반영 후 vector-state.json 확정.
    
    사전 검증, noop 실레코드 대조, 정제만 변경 시 임베딩 생략 및 미실행 건수 집계를 보장한다.
    """
    plan_path = Path(plan_path).resolve()
    persist_dir = Path(persist_dir).resolve()
    reference_path = Path(reference_path).resolve()

    if not plan_path.is_file():
        raise FileNotFoundError(f"실행 계획 파일을 찾을 수 없습니다: {plan_path}")
    if not reference_path.is_file():
        raise FileNotFoundError(f"인계 참조 파일을 찾을 수 없습니다: {reference_path}")

    spec = load_spec(reference_path)
    plan_doc = json.loads(plan_path.read_text(encoding="utf-8"))

    # [사전 전수 검증]: 계획 문서, 동결 원문 매니페스트, 계약 및 chunks.jsonl 검증
    frozen_source_root, chunks_by_cand = validate_plan_preflight(plan_doc, plan_path, spec)

    # T09 저장소 계약 및 사전 유효성 검증
    store = validate_store_before_access(persist_dir, spec, require_rawpedia_count=True)
    session = load_encoder(spec)

    gen_id = plan_doc["generation_id"]
    gen_dir = plan_path.parent
    output_dir = gen_dir.parent.parent
    vector_state_path = output_dir / "vector-state.json"

    # vector-state 유효성 및 최신 상태 대조 (오래된 계획 적용 방지)
    vector_state_doc: dict[str, Any] = {}
    if vector_state_path.is_file():
        vector_state_doc = json.loads(vector_state_path.read_text(encoding="utf-8"))
        last_gen = vector_state_doc.get("last_completed_generation")
        base_gen = plan_doc.get("base_generation")
        if last_gen and last_gen != base_gen and last_gen != gen_id:
            raise RuntimeError(
                f"최신 세대({last_gen})가 이미 반영되었으므로 이전 계획({gen_id})을 재적용할 수 없습니다."
            )

    if not vector_state_doc:
        vector_state_doc = {
            "schema_version": STATE_SCHEMA_VERSION,
            "store": {
                "persist_dir": str(persist_dir.resolve()),
                "collection_name": spec.collection_name,
                "reference_sha256": spec.reference_sha256,
                "protocol_sha256": spec.protocol_sha256,
            },
            "last_completed_generation": None,
            "last_completed_at": None,
            "items": {},
        }

    items_state = vector_state_doc.setdefault("items", {})

    operations = plan_doc.get("operations", [])
    op_results: list[dict[str, Any]] = []

    count_created = 0
    count_updated = 0
    count_excluded = 0
    count_unchanged = 0
    count_failed = 0

    now_ts = now_iso_utc()
    failed_index: Optional[int] = None

    for idx, op in enumerate(operations):
        cand_id = op["candidate_id"]
        action = op["action"]
        record_key = op["record_key"]
        thread_sha256 = op["thread_sha256"]
        cand_sha256 = op["candidate_sha256"]
        disp = op["disposition"]
        reason_codes = op["reason_codes"]
        chunk_ids = op.get("chunk_ids", [])
        payload_sha256 = op.get("chunks_payload_sha256")

        try:
            if action == "noop":
                # [noop 실레코드 확인]: Chroma에 실제로 존재하며 메타데이터/상태가 일치하는지 조회
                if disp == "include":
                    stored_col = store.collection.get(
                        where={"$and": [{"source_type": "github"}, {"source_group_id": cand_id}]},
                        include=["documents", "metadatas"],
                    )
                    cand_chunks = chunks_by_cand.get(cand_id, [])
                    stored_entry = {
                        "chunk_ids": stored_col.get("ids", []),
                        "documents": stored_col.get("documents", []),
                        "metadatas": stored_col.get("metadatas", []),
                        "any_excluded": any(m.get("excluded", False) for m in stored_col.get("metadatas", [])),
                    }
                    if not records_match_chunks(stored_entry, cand_chunks, spec):
                        raise RuntimeError(
                            f"noop 검증 실패: 저장소 레코드가 기대 청크셋과 불일치합니다 ({cand_id})"
                        )
                elif disp in ("exclude", "review"):
                    active_stored = store.collection.get(
                        where={"$and": [{"source_type": "github"}, {"source_group_id": cand_id}, {"excluded": False}]},
                        include=[],
                    )
                    if len(active_stored.get("ids", [])) > 0:
                        raise RuntimeError(
                            f"noop 제외 검증 실패: 활성 청크가 여전히 검색 가능합니다 ({cand_id})"
                        )

                count_unchanged += 1
                op_results.append({
                    "candidate_id": cand_id,
                    "action": "noop",
                    "status": "noop",
                    "report": {},
                    "verification": True,
                    "error": None,
                })

                # vector-state 확정 (기존 적용 시각 유지)
                if cand_id not in items_state:
                    status_str = "active" if disp == "include" else "never_indexed"
                    items_state[cand_id] = {
                        "candidate_id": cand_id,
                        "record_key": record_key,
                        "thread_sha256": thread_sha256,
                        "candidate_sha256": cand_sha256,
                        "disposition": disp,
                        "reason_codes": reason_codes,
                        "status": status_str,
                        "chunk_ids": chunk_ids,
                        "chunks_payload_sha256": payload_sha256,
                        "applied_generation": gen_id,
                        "applied_input_manifest": plan_doc["input_manifest"],
                        "source_root": str(frozen_source_root),
                        "applied_at": now_ts,
                    }
                    save_json_atomic(vector_state_path, vector_state_doc)

            elif action in ("create", "update"):
                cand_chunks = chunks_by_cand.get(cand_id, [])
                if not cand_chunks:
                    raise ValueError(f"후보 {cand_id}의 청크를 chunks.jsonl에서 찾을 수 없습니다.")

                # [정제만 변경 시 임베딩 생략]: 기존 저장 레코드와 청크 payload가 완전히 일치하는지 확인
                stored_col = store.collection.get(
                    where={"$and": [{"source_type": "github"}, {"source_group_id": cand_id}]},
                    include=["documents", "metadatas"],
                )
                stored_entry = {
                    "chunk_ids": stored_col.get("ids", []),
                    "documents": stored_col.get("documents", []),
                    "metadatas": stored_col.get("metadatas", []),
                    "any_excluded": any(m.get("excluded", False) for m in stored_col.get("metadatas", [])),
                }

                if records_match_chunks(stored_entry, cand_chunks, spec):
                    # 청크 payload가 일치하므로 임베딩 재계산 생략, 정제 SHA 및 판정만 갱신
                    count_unchanged += 1
                    prev_applied_at = items_state.get(cand_id, {}).get("applied_at", now_ts)
                    items_state[cand_id] = {
                        "candidate_id": cand_id,
                        "record_key": record_key,
                        "thread_sha256": thread_sha256,
                        "candidate_sha256": cand_sha256,
                        "disposition": disp,
                        "reason_codes": reason_codes,
                        "status": "active",
                        "chunk_ids": chunk_ids,
                        "chunks_payload_sha256": payload_sha256,
                        "applied_generation": gen_id,
                        "applied_input_manifest": plan_doc["input_manifest"],
                        "source_root": str(frozen_source_root),
                        "applied_at": prev_applied_at,
                    }
                    save_json_atomic(vector_state_path, vector_state_doc)

                    op_results.append({
                        "candidate_id": cand_id,
                        "action": action,
                        "status": "metadata_only",
                        "report": {"skipped_embedding": True},
                        "verification": True,
                        "error": None,
                    })
                    continue

                # provenance 전수 검증
                for c in cand_chunks:
                    validate_provenance(c, source_root=frozen_source_root)

                source_key = SourceKey("github", cand_id)
                report = store.replace_source(
                    key=source_key,
                    chunks=cand_chunks,
                    session=session,
                    source_root=frozen_source_root,
                )
                if report.status != "success":
                    raise RuntimeError(f"Chroma replace_source 실패: {cand_id}")

                # 저장 후 레코드 검증
                stored_col = store.collection.get(
                    where={"$and": [{"source_type": "github"}, {"source_group_id": cand_id}]},
                    include=["documents", "metadatas"],
                )
                if set(stored_col["ids"]) != set(chunk_ids):
                    raise RuntimeError(f"Chroma 저장 ID 검증 실패: {cand_id}")
                if any(m.get("excluded") is True for m in stored_col["metadatas"]):
                    raise RuntimeError(f"Chroma 저장 청크 중 excluded=True가 있습니다: {cand_id}")

                if action == "create":
                    count_created += 1
                else:
                    count_updated += 1

                items_state[cand_id] = {
                    "candidate_id": cand_id,
                    "record_key": record_key,
                    "thread_sha256": thread_sha256,
                    "candidate_sha256": cand_sha256,
                    "disposition": disp,
                    "reason_codes": reason_codes,
                    "status": "active",
                    "chunk_ids": chunk_ids,
                    "chunks_payload_sha256": payload_sha256,
                    "applied_generation": gen_id,
                    "applied_input_manifest": plan_doc["input_manifest"],
                    "source_root": str(frozen_source_root),
                    "applied_at": now_ts,
                }
                save_json_atomic(vector_state_path, vector_state_doc)

                op_results.append({
                    "candidate_id": cand_id,
                    "action": action,
                    "status": "success",
                    "report": asdict(report) if hasattr(report, "__dataclass_fields__") else vars(report),
                    "verification": True,
                    "error": None,
                })

            elif action == "exclude":
                source_key = SourceKey("github", cand_id)
                report = store.exclude_source(source_key)
                if report.status != "success":
                    raise RuntimeError(f"Chroma exclude_source 실패: {cand_id}")

                stored_col = store.collection.get(
                    where={"$and": [{"source_type": "github"}, {"source_group_id": cand_id}]},
                    include=["metadatas"],
                )
                if stored_col["ids"] and not all(m.get("excluded") is True for m in stored_col["metadatas"]):
                    raise RuntimeError(f"Chroma exclude 검증 실패: 미제외 청크 잔류 in {cand_id}")

                count_excluded += 1
                items_state[cand_id] = {
                    "candidate_id": cand_id,
                    "record_key": record_key,
                    "thread_sha256": thread_sha256,
                    "candidate_sha256": cand_sha256,
                    "disposition": disp,
                    "reason_codes": reason_codes,
                    "status": "excluded",
                    "chunk_ids": [],
                    "chunks_payload_sha256": None,
                    "applied_generation": gen_id,
                    "applied_input_manifest": plan_doc["input_manifest"],
                    "source_root": str(frozen_source_root),
                    "applied_at": now_ts,
                }
                save_json_atomic(vector_state_path, vector_state_doc)

                op_results.append({
                    "candidate_id": cand_id,
                    "action": action,
                    "status": "success",
                    "report": asdict(report) if hasattr(report, "__dataclass_fields__") else vars(report),
                    "verification": True,
                    "error": None,
                })

        except Exception as e:
            count_failed += 1
            failed_index = idx
            op_results.append({
                "candidate_id": cand_id,
                "action": action,
                "status": "failed",
                "report": {},
                "verification": False,
                "error": str(e),
            })
            # 순차 처리 중단: 실패 시 상태 전진을 멈춤
            break

    # [미반영에 실패 뒤 미실행 포함]: 실패 이후 남은 작업들을 unapplied로 기록
    count_unapplied_skipped = 0
    if failed_index is not None:
        for rem_op in operations[failed_index + 1:]:
            count_unapplied_skipped += 1
            op_results.append({
                "candidate_id": rem_op["candidate_id"],
                "action": rem_op["action"],
                "status": "unapplied",
                "report": {},
                "verification": False,
                "error": f"선행 작업({operations[failed_index]['candidate_id']}) 실패로 인해 실행되지 않음",
            })

    total_unapplied = count_failed + count_unapplied_skipped
    total_active = store._active_count()

    overall_status = "success" if total_unapplied == 0 else "partial"
    if total_unapplied == 0:
        # [성공 시각 덮어쓰기 금지]: 이미 동일 세대로 완료된 상태라면 기존 completed_at 유지
        if vector_state_doc.get("last_completed_generation") != gen_id:
            vector_state_doc["last_completed_generation"] = gen_id
            vector_state_doc["last_completed_at"] = now_ts
            save_json_atomic(vector_state_path, vector_state_doc)

    apply_report_doc = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generation_id": gen_id,
        "plan_path": str(plan_path),
        "applied_at": now_ts,
        "status": overall_status,
        "summary": {
            "created": count_created,
            "updated": count_updated,
            "excluded": count_excluded,
            "unchanged": count_unchanged,
            "unapplied": total_unapplied,
            "total_active": total_active,
        },
        "operations": op_results,
    }

    apply_report_path = gen_dir / "apply-report.json"
    save_json_atomic(apply_report_path, apply_report_doc)

    return {
        "generation_id": gen_id,
        "plan_path": str(plan_path),
        "status": overall_status,
        "created": count_created,
        "updated": count_updated,
        "excluded": count_excluded,
        "unchanged": count_unchanged,
        "unapplied": total_unapplied,
        "total_active": total_active,
    }
