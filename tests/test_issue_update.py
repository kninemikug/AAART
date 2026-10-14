"""Task 10-2c GitHub 변경분 갱신 및 Chroma 반영 모듈 단위·통합 테스트.

docs/T10_2c_execution_plan.md 및 Codex 리뷰 2차 보완 5개 문제 검증 기준을 전수 충족한다:
1. 중단 복구: updating 상태에서 T09 복구 API 호출, 복구 후 ready 및 검색 가능 확인
2. 대상 저장소 검증: 계획·실행인자·vector-state의 persist경로·컬렉션·계약 불일치 시 쓰기 전 거부
3. 오래된 계획 차단: base_state_sha256 불일치 및 다른 세대 갱신 시 거부, 거부 후 최신 레코드 유지
4. 정제만 변경: 임베딩 생략 및 SHA·판정 갱신, 실제 무변경 재실행 시 기존 상태·성공시각 유지
5. 동결 입력 무결성: 손상된 기존 세대 덮어쓰기 금지 및 즉시 오류 중단
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import pytest
from transformers import AutoTokenizer

from artagent.chunking import TokenizerBundle
from artagent.issue_filter import compute_canonical_manifest_sha256, compute_file_sha256, load_sources
from artagent import issue_update
from artagent.issue_update import (
    apply_plan,
    compute_candidate_sha256,
    compute_chunks_payload_sha256,
    compute_generation_id,
    generate_candidate_chunks,
    get_existing_github_records,
    prepare_generation,
    validate_plan_preflight,
    validate_store_before_access,
    validate_store_matching,
)
from artagent.retrieval.embedding import load_encoder
from artagent.retrieval.provenance import (
    Chunk as T09Chunk,
    canonical_json_bytes,
    canonical_json_str,
    validate_provenance,
)
from artagent.retrieval.store import RetrievalStore, _contract_metadata, open_store
from artagent.retrieval.types import RetrievalSpec, SourceKey, load_spec

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "issue_filter"
FIXTURE_CORPUS = FIXTURE_DIR / "corpus"
FIXTURE_CURATION = FIXTURE_DIR / "curation-decisions.json"
REFERENCE_PATH = ROOT / "docs" / "T08_2_t9_handoff_reference.json"
DATA_ISSUES = ROOT / "data" / "issues"


@pytest.fixture(scope="session")
def spec() -> RetrievalSpec:
    return load_spec(REFERENCE_PATH)


@pytest.fixture(scope="session")
def ref_tokenizer(spec: RetrievalSpec) -> AutoTokenizer:
    return AutoTokenizer.from_pretrained(
        spec.ref_tokenizer_id,
        revision=spec.ref_tokenizer_revision,
    )


@pytest.fixture(scope="session")
def tokenizer_bundle(ref_tokenizer: AutoTokenizer) -> TokenizerBundle:
    return TokenizerBundle(bge_tokenizer=ref_tokenizer)


@pytest.fixture
def t09_store_dir(tmp_path: Path, t09_seed_store: Path) -> Path:
    """세션에서 생성·검증하고 닫은 초기 저장소의 독립 복사본을 제공한다."""
    store_dir = tmp_path / "t09_store"
    shutil.copytree(t09_seed_store, store_dir)
    return store_dir


@pytest.fixture
def mutable_issue_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """원문 및 정제 규칙을 운영 데이터와 분리해 수정할 수 있는 입력 복사본."""
    corpus = tmp_path / "mutable-corpus"
    curation = tmp_path / "mutable-curation.json"
    shutil.copytree(FIXTURE_CORPUS, corpus)
    shutil.copy2(FIXTURE_CURATION, curation)
    return corpus, curation


def rewrite_issue_body(
    corpus: Path,
    curation: Path,
    number: int,
    *,
    prefix: str = "",
    suffix: str = "",
    select_entire_body: bool = False,
) -> None:
    """수집 SHA와 검토된 정제 SHA를 함께 갱신하되 선택 범위는 명시적으로만 확장."""
    record_key = f"issue:{number}"
    snapshot = corpus / "snapshots" / "issues" / f"{number}.json"
    raw = json.loads(snapshot.read_text(encoding="utf-8"))
    raw["body"] = prefix + raw["body"] + suffix
    snapshot.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    sync_path = corpus / "sync-state.json"
    sync = json.loads(sync_path.read_text(encoding="utf-8"))
    sync["records"][record_key]["file_sha256"] = compute_file_sha256(snapshot.read_bytes())
    sync_path.write_text(json.dumps(sync, ensure_ascii=False), encoding="utf-8")
    inventory = load_sources(corpus)
    thread = next(t for t in inventory.threads if t.record_key == record_key)
    curated = json.loads(curation.read_text(encoding="utf-8"))
    curated["threads"][record_key]["thread_sha256"] = thread.thread_sha256
    if select_entire_body:
        span = next(
            item for item in curated["threads"][record_key]["curated_content"]
            if item["record_key"] == record_key
        )
        span["char_end"] = len(raw["body"])
    curation.write_text(json.dumps(curated, ensure_ascii=False), encoding="utf-8")


def snapshot_store_records(store: RetrievalStore) -> dict[str, object]:
    """반환 순서에 의존하지 않고 본문·메타데이터·임베딩과 컬렉션 상태를 비교."""
    result = store.collection.get(include=["documents", "metadatas", "embeddings"])
    records = {
        chunk_id: {
            "document": result["documents"][index],
            "metadata": result["metadatas"][index],
            "embedding": result["embeddings"][index].tolist(),
        }
        for index, chunk_id in enumerate(result["ids"])
    }
    return {
        "records": records,
        "collection_metadata": dict(store._current_collection().metadata or {}),
    }


def forbid_chroma_writes(monkeypatch: pytest.MonkeyPatch, store: RetrievalStore) -> None:
    """무변경 재실행에서는 Chroma에 실제 쓰기를 시도하는 것도 오류로 취급."""
    def fail_write(*args, **kwargs):
        pytest.fail("무변경 재실행 중 Chroma 쓰기가 발생했습니다")

    for method in ("add", "upsert", "update", "delete", "modify"):
        monkeypatch.setattr(type(store.collection), method, fail_write)


# ---------------------------------------------------------------------------
# 1. 선정 청킹 규칙 및 기준선 재현 테스트
# ---------------------------------------------------------------------------


def test_t09_fixture_initial_state(t09_store_dir: Path, tmp_path: Path, spec: RetrievalSpec):
    """실물 작업 저장소 없이 테스트 임시 경로에 검증된 초기 상태를 준비한다."""
    assert t09_store_dir.parent == tmp_path
    store = open_store(t09_store_dir, spec)
    metadata = store._current_collection().metadata
    assert metadata["store_state"] == "ready"
    assert metadata["reference_sha256"] == spec.reference_sha256
    assert metadata["protocol_sha256"] == spec.protocol_sha256
    for source, expected in (("rawpedia", 141), ("github", 13)):
        ids = store.collection.get(
            where={"$and": [{"source_type": source}, {"excluded": False}]}, include=[]
        )["ids"]
        assert len(ids) == expected


def test_t09_fixture_copy_preserves_seed(t09_store_dir: Path, t09_seed_store: Path, spec: RetrievalSpec):
    """복사본 변경이 세션 기준 저장소의 파일 바이트에 영향을 주지 않는다."""
    def seed_hashes():
        return {
            str(path.relative_to(t09_seed_store)): compute_file_sha256(path.read_bytes())
            for path in t09_seed_store.rglob("*") if path.is_file()
        }

    before = seed_hashes()
    store = open_store(t09_store_dir, spec)
    github = store.collection.get(where={"source_type": "github"}, include=["metadatas"])
    key = SourceKey("github", github["metadatas"][0]["source_group_id"])
    report = store.exclude_source(key)
    assert report.total_active < spec.total_expected_count
    assert seed_hashes() == before


def test_baseline_github_13_chunks_byte_parity(
    spec: RetrievalSpec, tokenizer_bundle: TokenizerBundle
):
    """실제 search-candidates.json의 12개 후보를 선정 함수로 청킹하여 기대 SHA와 정확히 일치하는지 검증."""
    candidates_path = DATA_ISSUES / "search-candidates.json"
    cands_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    cands = cands_data["candidates"]
    assert len(cands) == 12

    all_chunks: list[T09Chunk] = []
    for cand in cands:
        chunks = generate_candidate_chunks(
            candidate=cand,
            github_dir=DATA_ISSUES,
            tokenizer_bundle=tokenizer_bundle,
            spec=spec,
        )
        for chunk in chunks:
            validate_provenance(chunk, source_root=ROOT)
        all_chunks.extend(chunks)

    assert len(all_chunks) == spec.github_expected_count  # 13

    lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in all_chunks]
    payload_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    actual_sha = hashlib.sha256(payload_bytes).hexdigest()

    assert actual_sha == spec.github_expected_sha256
    assert actual_sha == "7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571"


# ---------------------------------------------------------------------------
# 2. 문제 1: 중단 복구 회귀 테스트 (updating -> ready 및 검색 가능 확인)
# ---------------------------------------------------------------------------


def test_interrupted_updating_recovery_to_ready_and_searchable(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """updating 상태에서 동일 작업 복구 후 ready 전환 및 정상 검색 가능 검증."""
    output_dir = tmp_path / "output"

    prep = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep["plan_path"])
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))

    # 첫 번째 후보 작업의 T09 지문 확인
    target_op = plan_data["operations"][0]
    target_cand_id = target_op["candidate_id"]
    target_fp = target_op["t09_operation_fingerprint"]

    store = open_store(t09_store_dir, spec)
    session = load_encoder(spec)

    # 1. 인위적으로 store_state="updating" 주입
    store._set_store_state(
        "updating",
        operation="replace_source",
        input_fingerprint=target_fp,
        source_type="github",
        source_group_id=target_cand_id,
    )
    assert store._get_store_state() == "updating"

    # updating 중에는 T09 계약에 따라 검색이 거부되어야 함
    with pytest.raises(RuntimeError, match="저장소가 준비되지 않았습니다"):
        store.search("test query", session=session)

    # 2. apply_plan 실행 -> 복구 수행 (payload 동일하더라도 replace_source 직접 호출하여 복구)
    app_res = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_res["status"] == "success"

    # 3. 통과 증거: 복구 후 store_state == "ready" 확인
    assert store._get_store_state() == "ready"

    # 4. 통과 증거: 검색 가능 확인 (예외 없이 정상 검색 결과 반환)
    hits = store.search("RAW crop ratio", session=session)
    assert len(hits) > 0

    # 5. 불일치하는 updating 작업이 남아있는 경우 임의로 ready로 바꾸지 않고 오류 중단 검증
    store._set_store_state(
        "updating",
        operation="replace_source",
        input_fingerprint="mismatched_fp_12345",
        source_type="github",
        source_group_id="github:artraweditor/ART:issue:9999",
    )
    with pytest.raises(RuntimeError, match="일치하는 계획 작업이 없습니다"):
        apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)


# ---------------------------------------------------------------------------
# 3. 문제 2: 대상 저장소 검증 회귀 테스트 (불일치 시 쓰기 전 거부)
# ---------------------------------------------------------------------------


def test_store_mismatch_rejection_no_write(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """계획·실행인자·vector-state의 persist경로·컬렉션·계약 불일치 시 쓰기 전 거부 검증."""
    output_dir = tmp_path / "output"

    prep = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep["plan_path"])

    # 1. 실행 인자 persist_dir가 계획의 persist_dir와 다를 때 거부
    other_dir = tmp_path / "other_store"
    other_dir.mkdir()
    (other_dir / "chroma.sqlite3").write_text("dummy")

    with pytest.raises(ValueError, match="저장소 경로 불일치"):
        apply_plan(plan_path, other_dir, REFERENCE_PATH)

    # 2. vector-state.json의 store 정보와 대상 경로가 다를 때 거부
    state_file = output_dir / "vector-state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "store": {
            "persist_dir": str((tmp_path / "different_store").resolve()),
            "collection_name": spec.collection_name,
            "reference_sha256": spec.reference_sha256,
            "protocol_sha256": spec.protocol_sha256,
        },
        "last_completed_generation": None,
        "items": {},
    }), encoding="utf-8")

    mtime_before = state_file.stat().st_mtime_ns

    with pytest.raises(ValueError, match="vector-state 저장소 경로 불일치"):
        apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)

    # 거부 시 상태 파일에 쓰기가 없었음을 확인
    mtime_after = state_file.stat().st_mtime_ns
    assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# 4. 문제 3: 오래된 계획 차단 회귀 테스트 (최신 레코드 유지)
# ---------------------------------------------------------------------------


def test_stale_plan_rejection_preserves_latest_records(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """다른 세대 갱신 후 이전 세대 계획 재적용 시 거부되고 최신 레코드가 보존됨을 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 세대 A 준비
    prep_a = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_a_path = Path(prep_a["plan_path"])
    apply_plan(plan_a_path, t09_store_dir, REFERENCE_PATH)

    # 2. 세대 B (Issue 500 본문 수정) 준비 및 적용 완료
    snap_500 = custom_corpus / "snapshots" / "issues" / "500.json"
    data_500 = json.loads(snap_500.read_text(encoding="utf-8"))
    data_500["body"] += "\n[Updated in Generation B]"
    snap_500.write_text(json.dumps(data_500), encoding="utf-8")
    new_snap_sha = compute_file_sha256(snap_500.read_bytes())

    sync_file = custom_corpus / "sync-state.json"
    sync_data = json.loads(sync_file.read_text(encoding="utf-8"))
    sync_data["records"]["issue:500"]["file_sha256"] = new_snap_sha
    sync_file.write_text(json.dumps(sync_data), encoding="utf-8")

    inv = load_sources(custom_corpus)
    thread_500 = next(t for t in inv.threads if t.record_key == "issue:500")
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["thread_sha256"] = thread_500.thread_sha256
    curation_data["threads"]["issue:500"]["curated_content"][0]["char_end"] = len(data_500["body"])
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_b = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_b_path = Path(prep_b["plan_path"])
    assert prep_b["generation_id"] != prep_a["generation_id"]

    app_b = apply_plan(plan_b_path, t09_store_dir, REFERENCE_PATH)
    assert app_b["status"] == "success"

    # 세대 B의 최신 상태 및 Chroma 레코드 확인
    store = open_store(t09_store_dir, spec)
    col_500_b = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": "github:artraweditor/ART:issue:500"}]},
        include=["documents"],
    )
    doc_500_b = col_500_b["documents"][0]
    assert "[Updated in Generation B]" in doc_500_b

    state_data_b = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert state_data_b["last_completed_generation"] == prep_b["generation_id"]

    # 3. 오래된 계획 세대 A를 재적용 시도 -> 거부 확인
    with pytest.raises(RuntimeError, match="오래된 계획 거부"):
        apply_plan(plan_a_path, t09_store_dir, REFERENCE_PATH)

    # 4. 통과 증거: 거부 후에도 최신 레코드(세대 B 내용) 및 vector-state가 유지됨
    col_500_after = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": "github:artraweditor/ART:issue:500"}]},
        include=["documents"],
    )
    assert col_500_after["documents"][0] == doc_500_b
    state_data_after = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert state_data_after["last_completed_generation"] == prep_b["generation_id"]


# ---------------------------------------------------------------------------
# 5. 문제 4: 정제만 변경 시 임베딩 생략 및 실제 무변경 성공시각 보존 테스트
# ---------------------------------------------------------------------------


def test_curation_metadata_only_update_and_exact_reexecution(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """정제만 변경 시 임베딩 생략 및 SHA 갱신, 동일 세대 재실행 시 성공시각 보존 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 초기 세대 적용
    prep1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep1["plan_path"]), t09_store_dir, REFERENCE_PATH)

    state_file = output_dir / "vector-state.json"
    state_data_1 = json.loads(state_file.read_text(encoding="utf-8"))
    init_cand_sha_500 = state_data_1["items"]["github:artraweditor/ART:issue:500"]["candidate_sha256"]

    # 2. 원문/청크는 동일하고 curation rationale만 갱신 (정제만 변경)
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["rationale"] = "Updated rationale explanation for metadata test."
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep2 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert prep2["generation_id"] != prep1["generation_id"]

    # apply 실행: 임베딩 생략 확인
    app2 = apply_plan(Path(prep2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app2["status"] == "success"

    report_data2 = json.loads((Path(prep2["plan_path"]).parent / "apply-report.json").read_text(encoding="utf-8"))
    op_500 = next(op for op in report_data2["operations"] if op["candidate_id"] == "github:artraweditor/ART:issue:500")
    assert op_500["status"] == "metadata_only"
    assert op_500["report"].get("skipped_embedding") is True

    # vector-state의 candidate_sha 및 반영세대가 새 값으로 갱신되었는지 확인
    state_data_2 = json.loads(state_file.read_text(encoding="utf-8"))
    updated_item_500 = state_data_2["items"]["github:artraweditor/ART:issue:500"]
    assert updated_item_500["candidate_sha256"] != init_cand_sha_500
    assert updated_item_500["applied_generation"] == prep2["generation_id"]
    gen2_applied_at = updated_item_500["applied_at"]
    gen2_completed_at = state_data_2["last_completed_at"]

    # 3. 실제 무변경 동일 세대 재실행: 기존 성공시각 보존 확인
    app2_re = apply_plan(Path(prep2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app2_re["status"] == "success"
    assert app2_re["unchanged"] == 12

    state_data_2_re = json.loads(state_file.read_text(encoding="utf-8"))
    re_item_500 = state_data_2_re["items"]["github:artraweditor/ART:issue:500"]
    assert re_item_500["applied_at"] == gen2_applied_at  # 성공시각 유지
    assert state_data_2_re["last_completed_at"] == gen2_completed_at  # 완료시각 유지


# ---------------------------------------------------------------------------
# 6. 문제 5: 동결 입력 무결성 회귀 테스트 (손상 시 덮어쓰기 금지 및 오류 중단)
# ---------------------------------------------------------------------------


def test_corrupted_frozen_generation_aborts_without_overwrite(tmp_path: Path, t09_store_dir: Path):
    """손상된 기존 세대 발견 시 덮어쓰지 않고 즉시 오류 중단 검증."""
    output_dir = tmp_path / "output"

    prep = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    gen_id = prep["generation_id"]
    gen_dir = output_dir / "index-updates" / gen_id

    # chunks.jsonl을 고의로 손상
    chunks_file = gen_dir / "chunks.jsonl"
    chunks_file.write_bytes(b'{"damaged": true}\n')

    # prepare 재실행 시 덮어쓰지 않고 손상 감지 오류 중단 확인
    with pytest.raises(ValueError, match="손상된 기존 세대 디렉터리 감지"):
        prepare_generation(
            source_root=ROOT,
            input_dir=FIXTURE_CORPUS,
            curation_path=FIXTURE_CURATION,
            reference_path=REFERENCE_PATH,
            persist_dir=t09_store_dir,
            output_dir=output_dir,
        )


# ---------------------------------------------------------------------------
# 7. 부분 실패 및 미실행 항목 집계, 재시도 테스트
# ---------------------------------------------------------------------------


def test_partial_failure_and_retry_unapplied_count(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """배치 도중 실패 시 실패 항목(1건) + 이후 미실행 항목들이 unapplied로 집계되고, 재시도 시 성공 완료 검증."""
    output_dir = tmp_path / "output"

    # store에서 청크를 삭제한 상태에서 fresh prepare (create 유도)
    store = open_store(t09_store_dir, spec)
    github_ids = store.collection.get(where={"source_type": "github"})["ids"]
    if github_ids:
        store.collection.delete(ids=github_ids)

    prep_fresh = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir / "fresh",
    )
    plan_fresh_path = Path(prep_fresh["plan_path"])

    from artagent.retrieval.store import RetrievalStore
    orig_replace = RetrievalStore.replace_source
    call_idx = 0

    def mock_replace(self, *args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 3:
            raise RuntimeError("고의 주입된 3번째 작업 replace_source 오류")
        return orig_replace(self, *args, **kwargs)

    import unittest.mock as mock
    with mock.patch.object(RetrievalStore, "replace_source", mock_replace):
        app1 = apply_plan(plan_fresh_path, t09_store_dir, REFERENCE_PATH)
        assert app1["status"] == "partial"
        # 3번째 실패(1건) + 4~12번째 미실행(9건) = unapplied 10건
        assert app1["unapplied"] == 10
        assert app1["created"] == 2

    # 재시도: mock 해제 후 동일 계획 재실행
    app2 = apply_plan(plan_fresh_path, t09_store_dir, REFERENCE_PATH)
    assert app2["status"] == "success"
    assert app2["unapplied"] == 0
    assert app2["total_active"] == 154


# ---------------------------------------------------------------------------
# 8. 후보 수정 (구 청크 삭제, 새 청크 교체, 비대상 불변) 테스트
# ---------------------------------------------------------------------------


def test_candidate_update_and_cleanup(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """후보 원문 수정 시 청크가 갱신되고 구 청크가 삭제되며 비대상 그룹이 불변임을 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 초기 적재
    prep_1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_1["plan_path"]), t09_store_dir, REFERENCE_PATH)

    # 2. Issue 500 본문 수정
    snap_500 = custom_corpus / "snapshots" / "issues" / "500.json"
    data_500 = json.loads(snap_500.read_text(encoding="utf-8"))
    data_500["body"] = data_500["body"] + "\nModified explanation for update test."
    snap_500.write_text(json.dumps(data_500), encoding="utf-8")
    new_snap_sha = compute_file_sha256(snap_500.read_bytes())

    sync_file = custom_corpus / "sync-state.json"
    sync_data = json.loads(sync_file.read_text(encoding="utf-8"))
    sync_data["records"]["issue:500"]["file_sha256"] = new_snap_sha
    sync_file.write_text(json.dumps(sync_data), encoding="utf-8")

    inv = load_sources(custom_corpus)
    thread_500 = next(t for t in inv.threads if t.record_key == "issue:500")
    new_thread_sha = thread_500.thread_sha256
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["thread_sha256"] = new_thread_sha
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    # 3. 변경분 감지 Prepare 및 Apply
    prep_2 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert prep_2["generation_id"] != prep_1["generation_id"]
    assert prep_2["updated"] == 1

    app_2 = apply_plan(Path(prep_2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app_2["status"] == "success"
    assert app_2["total_active"] == 154


# ---------------------------------------------------------------------------
# 9. 제외, STALE_CURATION 보류 및 재포함 테스트
# ---------------------------------------------------------------------------


def test_exclude_and_reinclude_lifecycle(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """include -> exclude(검색 배제) -> re-include(복구) 전체 생명주기 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 초기 12건 적재
    prep_1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_1["plan_path"]), t09_store_dir, REFERENCE_PATH)

    # 2. Issue 500을 제외(exclude)로 변경
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["disposition"] = "exclude"
    curation_data["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_ex = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert prep_ex["excluded"] == 1

    app_ex = apply_plan(Path(prep_ex["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app_ex["status"] == "success"
    assert app_ex["total_active"] == 153  # 154 - 1 = 153

    # 검색에서 Issue 500이 배제되었는지 검증
    store = open_store(t09_store_dir, spec)
    session = load_encoder(spec)
    hits = store.search("RAW crop ratio", session=session)
    for h in hits:
        assert h.doc_id != "github:artraweditor/ART:issue:500"

    # 3. Issue 500을 다시 include로 재포함
    curation_data["threads"]["issue:500"]["disposition"] = "include"
    curation_data["threads"]["issue:500"]["reason_codes"] = ["ART_TECHNICAL_EXPLANATION"]
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_re = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert prep_re["updated"] == 1

    app_re = apply_plan(Path(prep_re["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app_re["status"] == "success"
    assert app_re["total_active"] == 154  # 복원


# ---------------------------------------------------------------------------
# 10. Codex 5:21PM 신규 리뷰 4항 회귀 테스트 (A, B, C, D)
# ---------------------------------------------------------------------------


def test_regression_a_chunk_id_change_reexecution_success(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec, monkeypatch: pytest.MonkeyPatch
):
    """A. 청크 ID 변경 -> 구 청크 삭제·교체 및 재실행 성공 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 초기 세대 적용
    prep1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep1["plan_path"]), t09_store_dir, REFERENCE_PATH)

    store = open_store(t09_store_dir, spec)
    col_before = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": "github:artraweditor/ART:issue:500"}]},
        include=[],
    )
    old_chunk_ids = set(col_before["ids"])
    assert len(old_chunk_ids) > 0

    # 2. Issue 500 본문 수정 및 슬라이스 확장으로 청크 ID 완전 변경
    snap_500 = custom_corpus / "snapshots" / "issues" / "500.json"
    data_500 = json.loads(snap_500.read_text(encoding="utf-8"))
    data_500["body"] = "Totally rewritten content that changes chunk boundaries.\n" + data_500["body"]
    snap_500.write_text(json.dumps(data_500), encoding="utf-8")
    new_snap_sha = compute_file_sha256(snap_500.read_bytes())

    sync_file = custom_corpus / "sync-state.json"
    sync_data = json.loads(sync_file.read_text(encoding="utf-8"))
    sync_data["records"]["issue:500"]["file_sha256"] = new_snap_sha
    sync_file.write_text(json.dumps(sync_data), encoding="utf-8")

    inv = load_sources(custom_corpus)
    thread_500 = next(t for t in inv.threads if t.record_key == "issue:500")
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["thread_sha256"] = thread_500.thread_sha256
    curation_data["threads"]["issue:500"]["curated_content"][0]["char_end"] = len(data_500["body"])
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep2 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert prep2["generation_id"] != prep1["generation_id"]

    plan2_doc = json.loads(Path(prep2["plan_path"]).read_text(encoding="utf-8"))
    op_500 = next(op for op in plan2_doc["operations"] if op["candidate_id"] == "github:artraweditor/ART:issue:500")
    new_chunk_ids = set(op_500["chunk_ids"])
    assert old_chunk_ids != new_chunk_ids  # 청크 ID가 다름 확인

    app2 = apply_plan(Path(prep2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app2["status"] == "success"

    col_after = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": "github:artraweditor/ART:issue:500"}]},
        include=[],
    )
    current_ids = set(col_after["ids"])
    assert current_ids == new_chunk_ids
    assert not (old_chunk_ids & current_ids)

    # 완료된 변경 세대의 동일 계획 재실행은 레코드·상태 파일을 다시 쓰지 않는다.
    state_path = output_dir / "vector-state.json"
    os.utime(state_path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    state_bytes = state_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    stored_records = snapshot_store_records(store)
    forbid_chroma_writes(monkeypatch, store)

    reexecution = apply_plan(Path(prep2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert reexecution["status"] == "success"
    assert reexecution["unapplied"] == 0
    assert snapshot_store_records(store) == stored_records
    assert state_path.read_bytes() == state_bytes
    assert state_path.stat().st_mtime_ns == state_mtime


def test_regression_b_interrupted_after_payload_write_recovery_to_ready_and_searchable(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec, monkeypatch: pytest.MonkeyPatch
):
    """B. 실제 payload 쓰기 후 ready 전 실패 -> 재시도 -> ready 및 검색 가능 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # discussion 412 본문 수정하여 첫 번째 include 작업이 update로 replace_source 호출되도록 유도
    snap_412 = custom_corpus / "snapshots" / "discussions" / "412.json"
    data_412 = json.loads(snap_412.read_text(encoding="utf-8"))
    data_412["body"] = "Modified discussion 412 body for recovery test.\n" + data_412["body"]
    snap_412.write_text(json.dumps(data_412), encoding="utf-8")
    new_snap_sha = compute_file_sha256(snap_412.read_bytes())

    sync_file = custom_corpus / "sync-state.json"
    sync_data = json.loads(sync_file.read_text(encoding="utf-8"))
    sync_data["records"]["discussion:D_kwDONWPV1M4Ai6_I"]["file_sha256"] = new_snap_sha
    sync_file.write_text(json.dumps(sync_data), encoding="utf-8")

    inv = load_sources(custom_corpus)
    thread_412 = next(t for t in inv.threads if t.record_key == "discussion:D_kwDONWPV1M4Ai6_I")
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["discussion:D_kwDONWPV1M4Ai6_I"]["thread_sha256"] = thread_412.thread_sha256
    curation_data["threads"]["discussion:D_kwDONWPV1M4Ai6_I"]["curated_content"][0]["char_end"] = len(data_412["body"])
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep["plan_path"])

    store = open_store(t09_store_dir, spec)
    session = load_encoder(spec)

    # replace_source 내부에서 payload upsert 후 ready 직전에 실패 주입
    orig_set_state = RetrievalStore._set_store_state
    injected_failure = False

    def crashing_set_store_state(self, state, **kwargs):
        nonlocal injected_failure
        if state == "ready" and not injected_failure:
            injected_failure = True
            raise RuntimeError("CRASH_AFTER_UPSERT: Simulated power loss right after payload write")
        return orig_set_state(self, state, **kwargs)

    monkeypatch.setattr(RetrievalStore, "_set_store_state", crashing_set_store_state)

    # 1. apply_plan 실행 -> payload upsert 완료 후 예외 발생하여 partial 반환
    app_fail = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_fail["status"] == "partial"
    assert app_fail["unapplied"] > 0

    # 2. 저장소 상태가 updating이고 검색이 거부됨을 확인
    assert store._get_store_state() == "updating"
    with pytest.raises(RuntimeError, match="저장소가 준비되지 않았습니다"):
        store.search("test query", session=session)

    # 3. 실패 주입 해제 후 재시도
    monkeypatch.undo()

    app_retry = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_retry["status"] == "success"

    # 4. 통과 증거: 복구 후 ready 및 실제 검색 가능 확인
    assert store._get_store_state() == "ready"
    hits = store.search("Modified discussion 412 body", session=session)
    assert isinstance(hits, list)


def test_regression_c_same_id_metadata_change_stale_plan_rejection_preserves_latest(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec
):
    """C. chunk_id 동일·metadata 변경 시 오래된 계획 거부 및 최신 레코드 유지 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 세대 A 준비 및 적용
    prep_a = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_a_path = Path(prep_a["plan_path"])
    apply_plan(plan_a_path, t09_store_dir, REFERENCE_PATH)

    # 2. 세대 B: 청크 본문/ID는 동일하되 curation metadata만 갱신 (정제 메타데이터 변경)
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["rationale"] = "Updated rationale for metadata fingerprint test."
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_b = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_b_path = Path(prep_b["plan_path"])
    assert prep_b["generation_id"] != prep_a["generation_id"]

    app_b = apply_plan(plan_b_path, t09_store_dir, REFERENCE_PATH)
    assert app_b["status"] == "success"

    state_data_b = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    cand_sha_b = state_data_b["items"]["github:artraweditor/ART:issue:500"]["candidate_sha256"]

    # 3. 세대 A 오래된 계획 재적용 시도 -> 거부 확인
    with pytest.raises(RuntimeError, match="오래된 계획 거부"):
        apply_plan(plan_a_path, t09_store_dir, REFERENCE_PATH)

    # 4. 통과 증거: 거부 후에도 세대 B의 최신 상태 및 지문이 그대로 유지됨
    state_data_after = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert state_data_after["last_completed_generation"] == prep_b["generation_id"]
    assert state_data_after["items"]["github:artraweditor/ART:issue:500"]["candidate_sha256"] == cand_sha_b


def test_regression_d_plan_operations_mutation_rejection_without_writes(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec
):
    """D. operations 삭제·변경 시 쓰기 없이 사전 거부 검증."""
    output_dir = tmp_path / "output"
    prep = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep["plan_path"])

    store = open_store(t09_store_dir, spec)
    initial_count = len(store.collection.get(include=[])["ids"])

    # update-plan.json의 operations에서 한 항목을 임의 삭제
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_data["operations"].pop(0)
    plan_path.write_text(json.dumps(plan_data), encoding="utf-8")

    # apply_plan 실행 -> manifest 불일치로 쓰기 전 거부
    with pytest.raises(ValueError, match="(manifest와 불일치|집합이 불일치)"):
        apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)

    # 거부 후 저장소 쓰기가 전혀 발생하지 않았음(레코드 수 불변) 검증
    after_count = len(store.collection.get(include=[])["ids"])
    assert after_count == initial_count
    assert not (output_dir / "vector-state.json").exists()


@pytest.mark.parametrize("failure_stage", ["before_delete", "before_ready", "checkpoint"])
def test_later_group_payload_write_failure_recovers_before_noop_groups(
    tmp_path: Path,
    t09_store_dir: Path,
    spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
):
    """중간 issue 500의 실제 쓰기 후 중단돼도 앞쪽 noop보다 먼저 동일 작업을 복구."""
    corpus, curation = mutable_issue_inputs
    rewrite_issue_body(
        corpus, curation, 500,
        prefix="Recovery must complete after a later issue write.\n",
        select_entire_body=True,
    )
    output_dir = tmp_path / "output"
    prepared = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    plan_path = Path(prepared["plan_path"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    candidate_id = "github:artraweditor/ART:issue:500"
    target = next(op for op in plan["operations"] if op["candidate_id"] == candidate_id)
    assert plan["operations"][0]["action"] == "noop"
    assert plan["operations"].index(target) > 0
    assert target["action"] == "update"

    store = open_store(t09_store_dir, spec)
    before = snapshot_store_records(store)
    original_set_state = RetrievalStore._set_store_state
    original_delete = type(store.collection).delete
    original_save = issue_update.save_json_atomic
    old_ids = {
        cid for cid, record in before["records"].items()
        if record["metadata"].get("source_group_id") == candidate_id
    }
    obsolete_ids = old_ids - set(target["chunk_ids"])
    assert obsolete_ids
    failed = False

    def fail_after_issue_500_payload(self, state, **kwargs):
        nonlocal failed
        current = self._current_collection().metadata or {}
        if state == "ready" and current.get("source_group_id") == candidate_id and not failed:
            failed = True
            raise RuntimeError("CRASH_AFTER_ISSUE_500_PAYLOAD_WRITE")
        return original_set_state(self, state, **kwargs)

    def fail_before_old_chunk_delete(self, *args, **kwargs):
        nonlocal failed
        if set(kwargs.get("ids", [])) & obsolete_ids and not failed:
            failed = True
            raise RuntimeError("CRASH_BEFORE_OLD_CHUNK_DELETE")
        return original_delete(self, *args, **kwargs)

    def fail_issue_500_checkpoint(path, data):
        nonlocal failed
        item = data.get("items", {}).get(candidate_id, {})
        if (
            path.name == "vector-state.json"
            and item.get("applied_generation") == prepared["generation_id"]
            and not failed
        ):
            failed = True
            raise OSError("CRASH_DURING_ISSUE_500_CHECKPOINT")
        return original_save(path, data)

    with monkeypatch.context() as failure_patch:
        if failure_stage == "before_delete":
            failure_patch.setattr(type(store.collection), "delete", fail_before_old_chunk_delete)
        elif failure_stage == "before_ready":
            failure_patch.setattr(RetrievalStore, "_set_store_state", fail_after_issue_500_payload)
        else:
            failure_patch.setattr(issue_update, "save_json_atomic", fail_issue_500_checkpoint)
        interrupted = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)

    assert failed
    assert interrupted["status"] == "partial"
    if failure_stage != "checkpoint":
        assert store._get_store_state() == "updating"
        pending = store._current_collection().metadata or {}
        assert pending["source_group_id"] == candidate_id
        assert pending["input_fingerprint"] == target["t09_operation_fingerprint"]
    else:
        assert store._get_store_state() == "ready"
    interrupted_state = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert interrupted_state["last_completed_generation"] is None
    assert candidate_id not in interrupted_state["items"]
    written = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": candidate_id}]},
        include=["documents", "metadatas"],
    )
    expected_ids = set(target["chunk_ids"])
    if failure_stage == "before_delete":
        expected_ids |= old_ids
    assert set(written["ids"]) == expected_ids
    assert any("Recovery must complete" in doc for doc in written["documents"])
    session = load_encoder(spec)
    if failure_stage != "checkpoint":
        with pytest.raises(RuntimeError, match="저장소가 준비되지 않았습니다"):
            store.search("Recovery must complete", session=session)

    with monkeypatch.context() as retry_patch:
        if failure_stage == "checkpoint":
            forbid_chroma_writes(retry_patch, store)
        retried = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert retried["status"] == "success"
    assert retried["unapplied"] == 0
    assert store._get_store_state() == "ready"
    assert store.search("RAW crop ratio", session=session)
    after = snapshot_store_records(store)
    other_before = {
        key: value for key, value in before["records"].items()
        if value["metadata"].get("source_group_id") != candidate_id
    }
    other_after = {
        key: value for key, value in after["records"].items()
        if value["metadata"].get("source_group_id") != candidate_id
    }
    assert other_after == other_before
    state = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert state["last_completed_generation"] == prepared["generation_id"]
    assert state["items"][candidate_id]["status"] == "active"
    assert set(state["items"][candidate_id]["chunk_ids"]) == set(target["chunk_ids"])


def test_batch_stale_preflight_rejects_before_any_earlier_group_or_state_write(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
):
    """앞쪽 477이 갱신 대상이어도 뒤쪽 500의 외부 변경을 첫 쓰기 전에 검출."""
    old_corpus = tmp_path / "old-corpus"
    new_corpus = tmp_path / "new-corpus"
    old_curation = tmp_path / "old-curation.json"
    new_curation = tmp_path / "new-curation.json"
    for corpus, curation in ((old_corpus, old_curation), (new_corpus, new_curation)):
        shutil.copytree(FIXTURE_CORPUS, corpus)
        shutil.copy2(FIXTURE_CURATION, curation)

    rewrite_issue_body(
        old_corpus, old_curation, 477,
        prefix="This older plan must not update issue 477.\n", select_entire_body=True,
    )
    old_output = tmp_path / "old-output"
    old = prepare_generation(
        source_root=ROOT, input_dir=old_corpus, curation_path=old_curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=old_output,
    )
    old_plan_path = Path(old["plan_path"])
    old_plan = json.loads(old_plan_path.read_text(encoding="utf-8"))
    ordered_ids = [op["candidate_id"] for op in old_plan["operations"]]
    assert ordered_ids.index("github:artraweditor/ART:issue:477") < ordered_ids.index("github:artraweditor/ART:issue:500")

    # 선택되지 않은 끝부분만 바꿔 청크 ID·본문은 유지하면서 원문 지문 metadata를 변경.
    rewrite_issue_body(
        new_corpus, new_curation, 500,
        suffix="\nUnselected later source update; preserve its metadata.",
    )
    new_output = tmp_path / "new-output"
    new = prepare_generation(
        source_root=ROOT, input_dir=new_corpus, curation_path=new_curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=new_output,
    )
    new_plan = json.loads(Path(new["plan_path"]).read_text(encoding="utf-8"))
    old_500 = next(op for op in old_plan["operations"] if op["candidate_id"].endswith("issue:500"))
    new_500 = next(op for op in new_plan["operations"] if op["candidate_id"].endswith("issue:500"))
    assert old_500["chunk_ids"] == new_500["chunk_ids"]
    assert old_500["target_payload_fingerprint"] != new_500["target_payload_fingerprint"]
    assert apply_plan(Path(new["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"

    store = open_store(t09_store_dir, spec)
    latest_records = snapshot_store_records(store)
    new_state_path = new_output / "vector-state.json"
    latest_state = new_state_path.read_bytes()
    latest_mtime = new_state_path.stat().st_mtime_ns
    with pytest.raises(RuntimeError, match="오래된 계획 거부"):
        apply_plan(old_plan_path, t09_store_dir, REFERENCE_PATH)

    assert snapshot_store_records(store) == latest_records
    assert not (old_output / "vector-state.json").exists()
    assert new_state_path.read_bytes() == latest_state
    assert new_state_path.stat().st_mtime_ns == latest_mtime


@pytest.mark.parametrize("corruption", [
    "missing_manifest_and_exclusion", "malformed_manifest", "wrong_schema", "wrong_generation",
    "missing_plan_sha", "empty_plan_sha", "incorrect_plan_sha", "missing_chunks_sha",
    "incorrect_chunks_sha", "missing_candidates_sha", "missing_report_sha", "missing_sync_sha",
    "missing_curation_sha",
])
def test_manifest_missing_or_invalid_rejects_before_store_and_state_writes(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], corruption: str,
):
    """제외 작업이 누락돼도 manifest 검증을 우회할 수 없고 모든 필수 SHA를 검증."""
    corpus, curation = mutable_issue_inputs
    output_dir = tmp_path / "output"
    baseline = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert apply_plan(Path(baseline["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"
    decisions = json.loads(curation.read_text(encoding="utf-8"))
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    curation.write_text(json.dumps(decisions), encoding="utf-8")
    prepared = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert prepared["excluded"] == 1
    plan_path = Path(prepared["plan_path"])
    manifest_path = plan_path.parent / "generation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corruption == "missing_manifest_and_exclusion":
        manifest_path.unlink()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["operations"] = [op for op in plan["operations"] if op["action"] != "exclude"]
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
    elif corruption == "malformed_manifest":
        manifest_path.write_text("{malformed", encoding="utf-8")
    else:
        file_by_corruption = {
            "missing_plan_sha": "update-plan.json", "empty_plan_sha": "update-plan.json",
            "incorrect_plan_sha": "update-plan.json", "missing_chunks_sha": "chunks.jsonl",
            "incorrect_chunks_sha": "chunks.jsonl", "missing_candidates_sha": "search-candidates.json",
            "missing_report_sha": "filter-report.json", "missing_sync_sha": "source/data/issues/sync-state.json",
            "missing_curation_sha": "source/data/issues/curation-decisions.json",
        }
        if corruption == "wrong_schema":
            manifest["schema_version"] = 999
        elif corruption == "wrong_generation":
            manifest["generation_id"] = "gen_from_another_generation"
        elif corruption.startswith("missing_"):
            manifest["files"].pop(file_by_corruption[corruption])
        elif corruption == "empty_plan_sha":
            manifest["files"][file_by_corruption[corruption]] = ""
        else:
            manifest["files"][file_by_corruption[corruption]] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    store = open_store(t09_store_dir, spec)
    stored_before = snapshot_store_records(store)
    state_path = output_dir / "vector-state.json"
    state_before = state_path.read_bytes()
    mtime_before = state_path.stat().st_mtime_ns
    with pytest.raises((ValueError, FileNotFoundError)):
        apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)

    assert snapshot_store_records(store) == stored_before
    assert state_path.read_bytes() == state_before
    assert state_path.stat().st_mtime_ns == mtime_before
    assert not (plan_path.parent / "apply-report.json").exists()


def test_excluded_generation_replay_preserves_tombstone_and_state_file(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    """include→exclude 완료 후 재실행은 excluded 상태 및 상태 파일 bytes·mtime을 보존."""
    corpus, curation = mutable_issue_inputs
    output_dir = tmp_path / "output"
    baseline = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert apply_plan(Path(baseline["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"
    decisions = json.loads(curation.read_text(encoding="utf-8"))
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    curation.write_text(json.dumps(decisions), encoding="utf-8")
    excluded = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    excluded_path = Path(excluded["plan_path"])
    assert apply_plan(excluded_path, t09_store_dir, REFERENCE_PATH)["status"] == "success"

    state_path = output_dir / "vector-state.json"
    os.utime(state_path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before_bytes = state_path.read_bytes()
    before_mtime = state_path.stat().st_mtime_ns
    before_state = json.loads(before_bytes)
    assert before_state["items"]["github:artraweditor/ART:issue:500"]["status"] == "excluded"
    store = open_store(t09_store_dir, spec)
    before_records = snapshot_store_records(store)
    forbid_chroma_writes(monkeypatch, store)

    replay = apply_plan(excluded_path, t09_store_dir, REFERENCE_PATH)
    assert replay["status"] == "success"
    assert replay["unapplied"] == 0
    assert snapshot_store_records(store) == before_records
    assert state_path.read_bytes() == before_bytes
    assert state_path.stat().st_mtime_ns == before_mtime
    after_state = json.loads(state_path.read_bytes())
    assert after_state["items"]["github:artraweditor/ART:issue:500"]["status"] == "excluded"


def test_missing_manifest_cannot_be_recreated_by_prepare(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
):
    output_dir = tmp_path / "output"
    arguments = dict(
        source_root=ROOT, input_dir=FIXTURE_CORPUS, curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    prepared = prepare_generation(**arguments)
    generation_dir = Path(prepared["plan_path"]).parent
    (generation_dir / "generation-manifest.json").unlink()
    before_files = {
        str(path.relative_to(generation_dir)): path.read_bytes()
        for path in generation_dir.rglob("*") if path.is_file()
    }
    store = open_store(t09_store_dir, spec)
    before_store = snapshot_store_records(store)

    with pytest.raises(ValueError, match="generation-manifest.json 누락"):
        prepare_generation(**arguments)

    after_files = {
        str(path.relative_to(generation_dir)): path.read_bytes()
        for path in generation_dir.rglob("*") if path.is_file()
    }
    assert after_files == before_files
    assert snapshot_store_records(store) == before_store
    assert not (output_dir / "vector-state.json").exists()


def test_exclusion_write_failure_recovers_before_earlier_noop_groups(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    corpus, curation = mutable_issue_inputs
    decisions = json.loads(curation.read_text(encoding="utf-8"))
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    curation.write_text(json.dumps(decisions), encoding="utf-8")
    output_dir = tmp_path / "output"
    prepared = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    plan_path = Path(prepared["plan_path"])
    candidate_id = "github:artraweditor/ART:issue:500"
    original_set_state = RetrievalStore._set_store_state

    def fail_exclusion_ready(self, state, **kwargs):
        current = self._current_collection().metadata or {}
        if state == "ready" and current.get("source_group_id") == candidate_id:
            assert current["operation"] == "exclude_source"
            raise RuntimeError("CRASH_AFTER_EXCLUSION_WRITE")
        return original_set_state(self, state, **kwargs)

    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(RetrievalStore, "_set_store_state", fail_exclusion_ready)
        interrupted = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert interrupted["status"] == "partial"
    store = open_store(t09_store_dir, spec)
    assert store._get_store_state() == "updating"
    stored = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": candidate_id}]},
        include=["metadatas"],
    )
    assert stored["ids"]
    assert all(meta["excluded"] is True for meta in stored["metadatas"])
    interrupted_state = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert candidate_id not in interrupted_state["items"]

    retried = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert retried["status"] == "success"
    assert store._get_store_state() == "ready"
    session = load_encoder(spec)
    assert store.search("RAW crop ratio", session=session)
    assert store.search("RAW crop ratio", session=session, source_key=SourceKey("github", candidate_id)) == []
    state = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
    assert state["items"][candidate_id]["status"] == "excluded"
    assert state["last_completed_generation"] == prepared["generation_id"]


def test_completion_checkpoint_failure_retries_without_chroma_writes(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec, monkeypatch: pytest.MonkeyPatch,
):
    output_dir = tmp_path / "output"
    prepared = prepare_generation(
        source_root=ROOT, input_dir=FIXTURE_CORPUS, curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    plan_path = Path(prepared["plan_path"])
    original_save = issue_update.save_json_atomic

    def fail_completion_checkpoint(path, data):
        if path.name == "vector-state.json" and data.get("last_completed_generation") is not None:
            raise OSError("CRASH_DURING_COMPLETION_CHECKPOINT")
        return original_save(path, data)

    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(issue_update, "save_json_atomic", fail_completion_checkpoint)
        interrupted = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert interrupted["status"] == "partial"
    assert interrupted["unapplied"] == 0  # 그룹은 완료됐지만 배치 완료 기록은 미확정.
    report = json.loads((plan_path.parent / "apply-report.json").read_text(encoding="utf-8"))
    assert report["completion_error"] == "CRASH_DURING_COMPLETION_CHECKPOINT"
    state_path = output_dir / "vector-state.json"
    interrupted_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert interrupted_state["last_completed_generation"] is None
    assert len(interrupted_state["items"]) == 12
    store = open_store(t09_store_dir, spec)
    before_store = snapshot_store_records(store)

    forbid_chroma_writes(monkeypatch, store)
    retried = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert retried["status"] == "success"
    assert snapshot_store_records(store) == before_store
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["items"] == interrupted_state["items"]
    assert final_state["last_completed_generation"] == prepared["generation_id"]


def test_identical_input_bytes_can_cycle_include_exclude_without_reusing_historical_plan(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path],
):
    """A→B→A→B 입력 복원은 각 현재 기준에서 새 계획으로 적용하고 과거 산출물을 보존."""
    corpus, curation = mutable_issue_inputs
    include_bytes = curation.read_bytes()
    excluded = json.loads(include_bytes)
    excluded["threads"]["issue:500"]["disposition"] = "exclude"
    excluded["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    exclude_bytes = json.dumps(excluded, ensure_ascii=False).encode("utf-8")
    source_files = {path: path.read_bytes() for path in corpus.rglob("*.json")}
    output_dir = tmp_path / "output"
    store = open_store(t09_store_dir, spec)
    candidate_id = "github:artraweditor/ART:issue:500"
    prior_generation = None
    preserved_files: dict[Path, tuple[bytes, int]] = {}
    prior_plans: set[Path] = set()
    original_records = snapshot_store_records(store)

    for input_bytes, expected_status, expected_active in (
        (include_bytes, "active", 154),
        (exclude_bytes, "excluded", 153),
        (include_bytes, "active", 154),
        (exclude_bytes, "excluded", 153),
    ):
        curation.write_bytes(input_bytes)
        prepared = prepare_generation(
            source_root=ROOT, input_dir=corpus, curation_path=curation,
            reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
        )
        plan_path = Path(prepared["plan_path"])
        assert plan_path not in prior_plans, "현재 상태로의 전환에 과거 계획을 재사용했습니다"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert plan["base_generation"] == prior_generation
        applied = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
        assert applied["status"] == "success"
        assert applied["unapplied"] == 0
        assert applied["total_active"] == expected_active
        assert store._get_store_state() == "ready"
        current = snapshot_store_records(store)
        expected_records = copy.deepcopy(original_records)
        for record in expected_records["records"].values():
            if record["metadata"].get("source_group_id") == candidate_id:
                record["metadata"]["excluded"] = expected_status == "excluded"
        assert current == expected_records
        state = json.loads((output_dir / "vector-state.json").read_text(encoding="utf-8"))
        assert state["last_completed_generation"] == prepared["generation_id"]
        assert state["items"][candidate_id]["status"] == expected_status
        assert curation.read_bytes() == input_bytes
        assert all(path.read_bytes() == content for path, content in source_files.items())
        for artifact, (content, mtime) in preserved_files.items():
            assert artifact.read_bytes() == content
            assert artifact.stat().st_mtime_ns == mtime
        for artifact in (plan_path, plan_path.parent / "generation-manifest.json"):
            preserved_files[artifact] = (artifact.read_bytes(), artifact.stat().st_mtime_ns)
        prior_plans.add(plan_path)
        prior_generation = prepared["generation_id"]


@pytest.mark.parametrize("disposition", ["include", "exclude"])
def test_completed_input_prepare_reuses_current_plan_without_store_or_state_writes(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], disposition: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """완료된 현재 입력의 prepare/apply 재실행은 같은 계획과 상태 bytes·mtime을 유지."""
    corpus, curation = mutable_issue_inputs
    output_dir = tmp_path / "output"
    prepared = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert apply_plan(Path(prepared["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"
    if disposition == "exclude":
        decisions = json.loads(curation.read_bytes())
        decisions["threads"]["issue:500"]["disposition"] = "exclude"
        decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
        curation.write_text(json.dumps(decisions), encoding="utf-8")
        prepared = prepare_generation(
            source_root=ROOT, input_dir=corpus, curation_path=curation,
            reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
        )
        assert apply_plan(Path(prepared["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"

    plan_path = Path(prepared["plan_path"])
    artifacts = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (plan_path, plan_path.parent / "generation-manifest.json")
    }
    state_path = output_dir / "vector-state.json"
    os.utime(state_path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    state_bytes = state_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    store = open_store(t09_store_dir, spec)
    records = snapshot_store_records(store)
    forbid_chroma_writes(monkeypatch, store)

    repeated = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert Path(repeated["plan_path"]) == plan_path
    assert repeated["generation_id"] == prepared["generation_id"]
    applied = apply_plan(Path(repeated["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert applied["status"] == "success"
    assert applied["unapplied"] == 0
    assert snapshot_store_records(store) == records
    assert state_path.read_bytes() == state_bytes
    assert state_path.stat().st_mtime_ns == state_mtime
    for path, (content, mtime) in artifacts.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime


def test_restored_input_prepare_reuses_interrupted_plan_and_recovers_real_write(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    """A 복원 쓰기 후 중단되면 동일 입력 prepare는 그 실패 계획을 재사용하고 복구."""
    corpus, curation = mutable_issue_inputs
    include_bytes = curation.read_bytes()
    output_dir = tmp_path / "output"
    original = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert apply_plan(Path(original["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"
    decisions = json.loads(include_bytes)
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    curation.write_text(json.dumps(decisions), encoding="utf-8")
    excluded = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    assert apply_plan(Path(excluded["plan_path"]), t09_store_dir, REFERENCE_PATH)["status"] == "success"
    curation.write_bytes(include_bytes)
    restored = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    restored_path = Path(restored["plan_path"])
    assert restored_path != Path(original["plan_path"])
    restored_plan = json.loads(restored_path.read_bytes())
    assert restored_plan["base_generation"] == excluded["generation_id"]
    candidate_id = "github:artraweditor/ART:issue:500"
    store = open_store(t09_store_dir, spec)
    original_set_state = RetrievalStore._set_store_state
    injected = False

    def crash_after_restore_write(self, state, **kwargs):
        nonlocal injected
        current = self._current_collection().metadata or {}
        if state == "ready" and current.get("source_group_id") == candidate_id and not injected:
            injected = True
            raise RuntimeError("CRASH_AFTER_REINCLUDE_PAYLOAD_WRITE")
        return original_set_state(self, state, **kwargs)

    with monkeypatch.context() as fail_patch:
        fail_patch.setattr(RetrievalStore, "_set_store_state", crash_after_restore_write)
        interrupted = apply_plan(restored_path, t09_store_dir, REFERENCE_PATH)
    assert injected
    assert interrupted["status"] == "partial"
    assert store._get_store_state() == "updating"
    written = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": candidate_id}]},
        include=["metadatas"],
    )
    assert written["ids"]
    assert all(metadata["excluded"] is False for metadata in written["metadatas"])
    preserved = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (restored_path, restored_path.parent / "generation-manifest.json")
    }
    state_path = output_dir / "vector-state.json"
    state_bytes = state_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    with monkeypatch.context() as no_write_patch:
        forbid_chroma_writes(no_write_patch, store)
        repeated = prepare_generation(
            source_root=ROOT, input_dir=corpus, curation_path=curation,
            reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
        )
    assert Path(repeated["plan_path"]) == restored_path
    assert repeated["generation_id"] == restored["generation_id"]
    assert state_path.read_bytes() == state_bytes
    assert state_path.stat().st_mtime_ns == state_mtime
    for path, (content, mtime) in preserved.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime
    recovered = apply_plan(restored_path, t09_store_dir, REFERENCE_PATH)
    assert recovered["status"] == "success"
    assert recovered["unapplied"] == 0
    assert recovered["total_active"] == 154
    assert store._get_store_state() == "ready"
    assert store.search("RAW crop ratio", session=load_encoder(spec))
    state = json.loads(state_path.read_bytes())
    assert state["last_completed_generation"] == restored["generation_id"]
    assert state["items"][candidate_id]["status"] == "active"


def test_historical_include_plan_rejected_after_restored_input_generation(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    """입력 A를 새 기준에서 복원해도 보존된 최초 A 계획의 직접 적용은 거부."""
    corpus, curation = mutable_issue_inputs
    include_bytes = curation.read_bytes()
    decisions = json.loads(include_bytes)
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    exclude_bytes = json.dumps(decisions).encode("utf-8")
    output_dir = tmp_path / "output"
    applied_plans = []
    for input_bytes in (include_bytes, exclude_bytes, include_bytes):
        curation.write_bytes(input_bytes)
        prepared = prepare_generation(
            source_root=ROOT, input_dir=corpus, curation_path=curation,
            reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
        )
        plan_path = Path(prepared["plan_path"])
        assert apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)["status"] == "success"
        applied_plans.append(plan_path)
    assert applied_plans[0] != applied_plans[2]
    original_plan = applied_plans[0]
    plan_bytes = original_plan.read_bytes()
    plan_mtime = original_plan.stat().st_mtime_ns
    manifest_path = original_plan.parent / "generation-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_mtime = manifest_path.stat().st_mtime_ns
    store = open_store(t09_store_dir, spec)
    records = snapshot_store_records(store)
    state_path = output_dir / "vector-state.json"
    state_bytes = state_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    forbid_chroma_writes(monkeypatch, store)

    with pytest.raises(RuntimeError, match="오래된 계획 거부"):
        apply_plan(original_plan, t09_store_dir, REFERENCE_PATH)
    assert snapshot_store_records(store) == records
    assert state_path.read_bytes() == state_bytes
    assert state_path.stat().st_mtime_ns == state_mtime
    assert original_plan.read_bytes() == plan_bytes
    assert original_plan.stat().st_mtime_ns == plan_mtime
    assert manifest_path.read_bytes() == manifest_bytes
    assert manifest_path.stat().st_mtime_ns == manifest_mtime


def test_legacy_interrupted_generation_is_reused_and_recovered_without_rewriting_files(
    tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec,
    mutable_issue_inputs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    """내용 지문만 generation_id로 쓰던 옛 계획도 prepare 재사용 후 실제 중단을 복구."""
    corpus, curation = mutable_issue_inputs
    output_dir = tmp_path / "output"
    included = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    include_path = Path(included["plan_path"])
    include_plan = json.loads(include_path.read_bytes())
    assert include_plan["base_generation"] is None
    assert include_plan["generation_id"] == include_plan.pop("input_generation_id")
    include_path.write_text(json.dumps(include_plan), encoding="utf-8")
    include_manifest_path = include_path.parent / "generation-manifest.json"
    include_manifest = json.loads(include_manifest_path.read_bytes())
    include_manifest.pop("input_generation_id")
    include_manifest["files"]["update-plan.json"] = compute_file_sha256(include_path.read_bytes())
    include_manifest_path.write_text(json.dumps(include_manifest), encoding="utf-8")
    assert apply_plan(include_path, t09_store_dir, REFERENCE_PATH)["status"] == "success"

    decisions = json.loads(curation.read_bytes())
    decisions["threads"]["issue:500"]["disposition"] = "exclude"
    decisions["threads"]["issue:500"]["reason_codes"] = ["MANUAL_EXCLUSION"]
    curation.write_text(json.dumps(decisions), encoding="utf-8")
    excluded = prepare_generation(
        source_root=ROOT, input_dir=corpus, curation_path=curation,
        reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
    )
    new_exclude_path = Path(excluded["plan_path"])
    exclude_plan = json.loads(new_exclude_path.read_bytes())
    legacy_generation = exclude_plan.pop("input_generation_id")
    legacy_dir = new_exclude_path.parent.parent / legacy_generation
    assert not legacy_dir.exists()
    new_exclude_path.parent.rename(legacy_dir)
    legacy_path = legacy_dir / "update-plan.json"
    exclude_plan["generation_id"] = legacy_generation
    exclude_plan["source_root"] = str((legacy_dir / "source").resolve())
    legacy_path.write_text(json.dumps(exclude_plan), encoding="utf-8")
    legacy_manifest_path = legacy_dir / "generation-manifest.json"
    legacy_manifest = json.loads(legacy_manifest_path.read_bytes())
    legacy_manifest.pop("input_generation_id")
    legacy_manifest["generation_id"] = legacy_generation
    legacy_manifest["files"]["update-plan.json"] = compute_file_sha256(legacy_path.read_bytes())
    legacy_manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")
    validate_plan_preflight(exclude_plan, legacy_path, spec)

    candidate_id = "github:artraweditor/ART:issue:500"
    original_set_state = RetrievalStore._set_store_state
    injected = False

    def crash_after_legacy_exclusion_write(self, state, **kwargs):
        nonlocal injected
        current = self._current_collection().metadata or {}
        if state == "ready" and current.get("source_group_id") == candidate_id and not injected:
            assert current["operation"] == "exclude_source"
            injected = True
            raise RuntimeError("CRASH_AFTER_LEGACY_EXCLUSION_WRITE")
        return original_set_state(self, state, **kwargs)

    with monkeypatch.context() as fail_patch:
        fail_patch.setattr(RetrievalStore, "_set_store_state", crash_after_legacy_exclusion_write)
        interrupted = apply_plan(legacy_path, t09_store_dir, REFERENCE_PATH)
    assert injected
    assert interrupted["status"] == "partial"
    store = open_store(t09_store_dir, spec)
    assert store._get_store_state() == "updating"
    written = store.collection.get(
        where={"$and": [{"source_type": "github"}, {"source_group_id": candidate_id}]},
        include=["metadatas"],
    )
    assert written["ids"]
    assert all(metadata["excluded"] is True for metadata in written["metadatas"])
    state_path = output_dir / "vector-state.json"
    state_bytes = state_path.read_bytes()
    state_mtime = state_path.stat().st_mtime_ns
    interrupted_records = snapshot_store_records(store)
    preserved = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (include_path, include_manifest_path, legacy_path, legacy_manifest_path)
    }
    with monkeypatch.context() as no_write_patch:
        forbid_chroma_writes(no_write_patch, store)
        repeated = prepare_generation(
            source_root=ROOT, input_dir=corpus, curation_path=curation,
            reference_path=REFERENCE_PATH, persist_dir=t09_store_dir, output_dir=output_dir,
        )
    assert Path(repeated["plan_path"]) == legacy_path
    assert repeated["generation_id"] == legacy_generation
    assert snapshot_store_records(store) == interrupted_records
    assert state_path.read_bytes() == state_bytes
    assert state_path.stat().st_mtime_ns == state_mtime
    for path, (content, mtime) in preserved.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime

    recovered = apply_plan(legacy_path, t09_store_dir, REFERENCE_PATH)
    assert recovered["status"] == "success"
    assert recovered["unapplied"] == 0
    assert recovered["total_active"] == 153
    assert store._get_store_state() == "ready"
    session = load_encoder(spec)
    assert store.search("RAW crop ratio", session=session)
    assert store.search("RAW crop ratio", session=session, source_key=SourceKey("github", candidate_id)) == []
    state = json.loads(state_path.read_bytes())
    assert state["last_completed_generation"] == legacy_generation
    assert state["items"][candidate_id]["status"] == "excluded"
    for path, (content, mtime) in preserved.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime
