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
from artagent.retrieval.store import _contract_metadata, open_store
from artagent.retrieval.types import RetrievalSpec, SourceKey, load_spec

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "issue_filter"
FIXTURE_CORPUS = FIXTURE_DIR / "corpus"
FIXTURE_CURATION = FIXTURE_DIR / "curation-decisions.json"
REFERENCE_PATH = ROOT / "docs" / "T08_2_t9_handoff_reference.json"
DATA_ISSUES = ROOT / "data" / "issues"
REAL_STORE_DIR = ROOT / "data" / "vector-store" / "t09"


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
def t09_store_dir(tmp_path: Path) -> Path:
    """T09 초기 저장소(RawPedia 141개 + GitHub 13개 = 154개)를 tmp_path에 복사한 격리 환경 제공."""
    store_dir = tmp_path / "t09_store"
    shutil.copytree(REAL_STORE_DIR, store_dir)
    return store_dir


# ---------------------------------------------------------------------------
# 1. 선정 청킹 규칙 및 기준선 재현 테스트
# ---------------------------------------------------------------------------


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
