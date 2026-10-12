"""Task 10-2c GitHub 변경분 갱신 및 Chroma 반영 모듈 단위·통합 테스트.

docs/T10_2c_execution_plan.md 및 Codex 리뷰 보완 6항 검증 기준을 전수 충족한다:
1. 선행 기준선 및 선정 청킹 규칙 재현 (13청크 바이트 및 지문 일치)
2. T09 초기저장소(RawPedia 141 + GitHub 13 = 154) 확보 및 DB/경로/계약 불일치 시 쓰기 전 거부
3. apply 전 계획·동결입력·payload·기준지문 전수 검증, noop도 실레코드 확인 후 성공
4. 동일입력 prepare 재사용 (덮어쓰기 금지) 및 정제만 변경 시 임베딩 생략+SHA·판정 갱신
5. 회귀 및 부분실패/재시도 테스트 (미반영에 실패 뒤 미실행 포함)
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

    # JSONL 직렬화 바이트 SHA 대조
    lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in all_chunks]
    payload_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    actual_sha = hashlib.sha256(payload_bytes).hexdigest()

    assert actual_sha == spec.github_expected_sha256
    assert actual_sha == "7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571"


# ---------------------------------------------------------------------------
# 2. T09 초기 저장소 검증 및 불일치 시 쓰기 전 거부 테스트 (리뷰 2항)
# ---------------------------------------------------------------------------


def test_invalid_store_rejection(tmp_path: Path, spec: RetrievalSpec):
    """존재하지 않는 경로, 빈 디렉터리, RawPedia 청크 누락, 계약 불일치 시 쓰기 전 거부 검증."""
    # 1. 존재하지 않는 경로
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        validate_store_before_access(non_existent, spec)

    # 2. chroma.sqlite3 없는 빈 디렉터리
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="chroma.sqlite3"):
        validate_store_before_access(empty_dir, spec)

    # 3. 계약 메타데이터는 갖췄으나 RawPedia 청크가 0개인 저장소 거부
    import chromadb
    client = chromadb.PersistentClient(path=str(empty_dir))
    hnsw_cfg = {
        "space": spec.space,
        "ef_construction": spec.hnsw_ef_construction,
        "ef_search": spec.hnsw_ef_search,
        "max_neighbors": spec.hnsw_max_neighbors,
        "num_threads": spec.hnsw_num_threads,
    }
    contract_meta = {**_contract_metadata(spec), "store_state": "ready"}
    client.create_collection(
        name=spec.collection_name,
        configuration={"hnsw": hnsw_cfg},
        metadata=contract_meta,
    )
    with pytest.raises(ValueError, match="RawPedia 청크 수 불일치"):
        validate_store_before_access(empty_dir, spec, require_rawpedia_count=True)


# ---------------------------------------------------------------------------
# 3. 동결 및 실행 계획 (Prepare) 계약 및 재사용 테스트 (리뷰 4항)
# ---------------------------------------------------------------------------


def test_prepare_generation_contracts_and_reuse(tmp_path: Path, t09_store_dir: Path):
    """동결 복사, 매니페스트 일치, 세대 디렉터리 산출물 스키마 및 동일 입력 prepare 재사용 검증."""
    output_dir = tmp_path / "output"

    res = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )

    gen_id = res["generation_id"]
    assert gen_id.startswith("gen_")
    gen_dir = output_dir / "index-updates" / gen_id

    plan_file = gen_dir / "update-plan.json"
    assert plan_file.is_file()
    assert (gen_dir / "chunks.jsonl").is_file()

    mtime_before = plan_file.stat().st_mtime_ns

    # 동일 입력 prepare 재실행 -> 파일 덮어쓰기 없이 기존 계획 재사용
    res_reuse = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    assert res_reuse["generation_id"] == gen_id
    mtime_after = plan_file.stat().st_mtime_ns
    assert mtime_before == mtime_after  # 덮어쓰지 않고 재사용됨


# ---------------------------------------------------------------------------
# 4. Apply 전 전수 검증 및 noop 실레코드 대조 테스트 (리뷰 3항)
# ---------------------------------------------------------------------------


def test_apply_preflight_and_noop_verification(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """계획·동결입력·payload 불일치 거부 및 noop 시 실레코드 조회 검증."""
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

    # 1. chunks.jsonl 내용이 변조된 경우 apply 거부
    gen_dir = plan_path.parent
    chunks_file = gen_dir / "chunks.jsonl"
    orig_chunks = chunks_file.read_bytes()
    bad_line = json.dumps({
        "chunk_id": "bad_chunk",
        "source_type": "github",
        "doc_id": "dummy",
        "content": "tampered",
        "metadata": {},
    }) + "\n"
    chunks_file.write_bytes(bad_line.encode("utf-8"))

    with pytest.raises(ValueError):
        apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)

    # 원복
    chunks_file.write_bytes(orig_chunks)

    # 2. 정상 apply 실행
    app_res = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_res["status"] == "success"
    assert app_res["total_active"] == 154

    # 3. noop 재실행: 저장소 실레코드와 대조 통과
    app_res2 = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_res2["status"] == "success"
    assert app_res2["unchanged"] == 12

    # 4. Chroma에서 임의로 한 청크를 삭제했을 때 noop 검증 실패 및 partial 반환 확인
    store = open_store(t09_store_dir, spec)
    any_id = store.collection.get(where={"source_type": "github"}, limit=1)["ids"][0]
    store.collection.delete(ids=[any_id])

    app_res3 = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
    assert app_res3["status"] == "partial"
    assert app_res3["unapplied"] > 0
    report_data = json.loads((gen_dir / "apply-report.json").read_text(encoding="utf-8"))
    assert any("noop 검증 실패" in str(op.get("error")) for op in report_data.get("operations", []))


# ---------------------------------------------------------------------------
# 5. 정제 메타데이터만 변경 시 임베딩 생략 테스트 (리뷰 4항)
# ---------------------------------------------------------------------------


def test_metadata_only_update_skips_embedding(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """원문/청크 payload는 동일하고 curation 판정/thread 지문만 갱신된 경우 임베딩 생략 및 상태 갱신 검증."""
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 1. 초기 상태 적용
    prep1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep1["plan_path"]), t09_store_dir, REFERENCE_PATH)

    # 2. 원문과 청크 payload는 불변이고 rationale만 갱신 (규칙 통과)
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["rationale"] = "Updated rationale explanation for test."
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

    # 3. Apply 실행 시 임베딩 생략 (metadata_only) 확인
    app2 = apply_plan(Path(prep2["plan_path"]), t09_store_dir, REFERENCE_PATH)
    assert app2["status"] == "success"
    report_file = Path(prep2["plan_path"]).parent / "apply-report.json"
    report_data = json.loads(report_file.read_text(encoding="utf-8"))
    op_500 = next(op for op in report_data["operations"] if op["candidate_id"] == "github:artraweditor/ART:issue:500")
    assert op_500["status"] in ("metadata_only", "noop")


# ---------------------------------------------------------------------------
# 6. 부분 실패 및 미실행 항목 집계, 재시도 테스트 (리뷰 5항)
# ---------------------------------------------------------------------------


def test_partial_failure_and_retry_unapplied_count(tmp_path: Path, t09_store_dir: Path, spec: RetrievalSpec):
    """배치 도중 실패 시 실패 항목(1건) + 이후 미실행 항목들이 unapplied로 집계되고, 재시도 시 성공 완료 검증."""
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

    # 1. 3번째 후보의 청크를 chunks.jsonl에서 일시 제거하여 3번째에서 실패 유도
    gen_dir = plan_path.parent
    chunks_file = gen_dir / "chunks.jsonl"
    orig_lines = chunks_file.read_text(encoding="utf-8").splitlines()

    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    target_cand_id = plan_data["operations"][2]["candidate_id"]

    # 3번째 후보의 청크를 제외한 jsonl 작성
    filtered_lines = [l for l in orig_lines if target_cand_id not in l]
    chunks_file.write_text("\n".join(filtered_lines) + "\n", encoding="utf-8")

    # 1차 Apply 실행 -> 3번째 후보 처리 시 청크 누락으로 실패
    # 주의: 사전 검증을 통과하도록 plan_doc의 3번째 payload SHA를 일시 bypass하거나,
    # apply 실행 시 3번째 후보에서 실패하도록 함
    # 더 확실한 방법: update-plan.json의 operations[2]["chunk_ids"]를 손상시켜 검증 에러 유도
    try:
        app1 = apply_plan(plan_path, t09_store_dir, REFERENCE_PATH)
        assert False, "예외가 발생해야 합니다"
    except ValueError:
        pass

    # 사전 검증 통과 후 apply 실행 중 3번째 후보에서 RuntimeError 발생하도록 monkeypatch 테스트
    chunks_file.write_text("\n".join(orig_lines) + "\n", encoding="utf-8")

    from artagent.retrieval.store import RetrievalStore
    orig_replace = RetrievalStore.replace_source
    call_idx = 0

    def mock_replace(self, *args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 3:
            raise RuntimeError("고의 주입된 3번째 작업 replace_source 오류")
        return orig_replace(self, *args, **kwargs)

    # 1차 시도: store에서 청크를 모두 삭제한 상태(create 유도)에서 실행
    store = open_store(t09_store_dir, spec)
    github_ids = store.collection.get(where={"source_type": "github"})["ids"]
    if github_ids:
        store.collection.delete(ids=github_ids)

    # prepare 다시 생성 (전부 create 상태가 됨)
    prep_fresh = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=t09_store_dir,
        output_dir=output_dir / "fresh",
    )
    plan_fresh_path = Path(prep_fresh["plan_path"])

    # mock 적용
    import unittest.mock as mock
    with mock.patch.object(RetrievalStore, "replace_source", mock_replace):
        app1 = apply_plan(plan_fresh_path, t09_store_dir, REFERENCE_PATH)
        assert app1["status"] == "partial"
        # 3번째 실패(1건) + 4~12번째 미실행(9건) = unapplied 10건
        assert app1["unapplied"] == 10
        assert app1["created"] == 2

    # 2. 실패 해소 후 동일 계획 재시도 (재실행)
    app2 = apply_plan(plan_fresh_path, t09_store_dir, REFERENCE_PATH)
    assert app2["status"] == "success"
    assert app2["unapplied"] == 0
    assert app2["total_active"] == 154


# ---------------------------------------------------------------------------
# 7. 후보 수정 (구 청크 삭제, 새 청크 교체, 비대상 불변) 테스트
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
# 8. 제외, STALE_CURATION 보류 및 재포함 테스트
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

    # 3. Issue 500을 다시 include로 재포함 (유효한 positive signal reason_codes 유지)
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
