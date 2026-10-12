"""Task 10-2c GitHub 변경분 갱신 및 Chroma 반영 모듈 단위·통합 테스트.

docs/T10_2c_execution_plan.md §5 검증 기준을 전수 충족한다:
- 선행 기준선 및 선정 청킹 규칙 재현 (13청크 바이트 및 지문 일치)
- 입력 동결 및 매니페스트 전수 대조
- 최초 반영, 중복 없는 멱등 재실행 (0 쓰기)
- 후보 수정 (구 청크 삭제, 새 청크 교체, 비대상 불변)
- 제외 및 보류 (검색 배제 및 excluded=True)
- 재포함 (excluded=False 복원 및 검색 정상화)
- 상태 전진 및 이전 계획 재적용 거부
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import pytest
from transformers import AutoTokenizer

from artagent.chunking import TokenizerBundle
from artagent.issue_filter import compute_canonical_manifest_sha256, compute_file_sha256
from artagent.issue_update import (
    apply_plan,
    compute_candidate_sha256,
    compute_generation_id,
    generate_candidate_chunks,
    get_existing_github_records,
    prepare_generation,
)
from artagent.retrieval.embedding import load_encoder
from artagent.retrieval.provenance import (
    Chunk as T09Chunk,
    canonical_json_bytes,
    canonical_json_str,
    validate_provenance,
)
from artagent.retrieval.store import open_store
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
# 2. 동결 및 실행 계획 (Prepare) 계약 테스트
# ---------------------------------------------------------------------------


def test_prepare_generation_contracts(tmp_path: Path):
    """동결 복사, 매니페스트 일치, 세대 디렉터리 산출물 스키마를 검증."""
    persist_dir = tmp_path / "chroma"
    output_dir = tmp_path / "output"

    res = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )

    gen_id = res["generation_id"]
    assert gen_id.startswith("gen_")
    assert res["created"] == 12
    assert res["updated"] == 0
    assert res["excluded"] == 0
    assert res["unchanged"] == 0
    assert res["unapplied"] == 12

    gen_dir = output_dir / "index-updates" / gen_id
    assert (gen_dir / "source" / "data" / "issues" / "sync-state.json").is_file()
    assert (gen_dir / "source" / "data" / "issues" / "curation-decisions.json").is_file()
    assert (gen_dir / "search-candidates.json").is_file()
    assert (gen_dir / "filter-report.json").is_file()
    assert (gen_dir / "chunks.jsonl").is_file()
    assert (gen_dir / "update-plan.json").is_file()

    plan_doc = json.loads((gen_dir / "update-plan.json").read_text(encoding="utf-8"))
    assert plan_doc["generation_id"] == gen_id
    assert len(plan_doc["operations"]) == 12
    for op in plan_doc["operations"]:
        assert op["action"] == "create"
        assert len(op["chunk_ids"]) >= 1


# ---------------------------------------------------------------------------
# 3. 최초 적용, 멱등 재실행, vector-state.json 확정 테스트
# ---------------------------------------------------------------------------


def test_apply_and_idempotent_reexecution(tmp_path: Path, spec: RetrievalSpec):
    """최초 apply 후 vector-state.json 확정, 검색 가능 확인, 동일 입력 재실행 시 0 쓰기(멱등성) 검증."""
    persist_dir = tmp_path / "chroma"
    output_dir = tmp_path / "output"

    # Stage 1: Prepare
    prep_res = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep_res["plan_path"])

    # Stage 1: Apply
    app_res = apply_plan(
        plan_path=plan_path,
        persist_dir=persist_dir,
        reference_path=REFERENCE_PATH,
    )

    assert app_res["status"] == "success"
    assert app_res["created"] == 12
    assert app_res["updated"] == 0
    assert app_res["excluded"] == 0
    assert app_res["unchanged"] == 0
    assert app_res["unapplied"] == 0
    assert app_res["total_active"] == 13

    # vector-state.json 검증
    state_file = output_dir / "vector-state.json"
    assert state_file.is_file()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["last_completed_generation"] == prep_res["generation_id"]
    assert len(state_data["items"]) == 12
    for cand_id, item in state_data["items"].items():
        assert item["status"] == "active"
        assert item["applied_generation"] == prep_res["generation_id"]

    # Chroma 검색 검증
    store = open_store(persist_dir, spec)
    session = load_encoder(spec)
    hits = store.search("RAW crop ratio", session=session)
    assert len(hits) > 0
    assert hits[0].source_type == "github"

    # Stage 2: 재실행 (동일 입력 멱등성 검증)
    prep_res_2 = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    # 동일 입력이므로 generation_id 동일
    assert prep_res_2["generation_id"] == prep_res["generation_id"]
    assert prep_res_2["created"] == 0
    assert prep_res_2["updated"] == 0
    assert prep_res_2["excluded"] == 0
    assert prep_res_2["unchanged"] == 12
    assert prep_res_2["unapplied"] == 0

    app_res_2 = apply_plan(
        plan_path=Path(prep_res_2["plan_path"]),
        persist_dir=persist_dir,
        reference_path=REFERENCE_PATH,
    )
    assert app_res_2["status"] == "success"
    assert app_res_2["created"] == 0
    assert app_res_2["updated"] == 0
    assert app_res_2["excluded"] == 0
    assert app_res_2["unchanged"] == 12
    assert app_res_2["unapplied"] == 0
    assert app_res_2["total_active"] == 13


# ---------------------------------------------------------------------------
# 4. 후보 수정, 구 청크 삭제, 비대상 불변 테스트
# ---------------------------------------------------------------------------


def test_candidate_update_and_cleanup(tmp_path: Path, spec: RetrievalSpec):
    """후보 원문 수정 시 replace_source가 청크를 갱신하고 구 청크를 삭제하며 비대상 그룹이 불변임을 검증."""
    persist_dir = tmp_path / "chroma"
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
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_1["plan_path"]), persist_dir, REFERENCE_PATH)

    # 2. Issue 500 원문 본문 및 제목 수정
    snap_500 = custom_corpus / "snapshots" / "issues" / "500.json"
    data_500 = json.loads(snap_500.read_text(encoding="utf-8"))
    data_500["body"] = data_500["body"] + "\nModified explanation for update test."
    snap_500.write_text(json.dumps(data_500), encoding="utf-8")
    new_snap_sha = compute_file_sha256(snap_500.read_bytes())

    # sync-state.json 갱신
    sync_file = custom_corpus / "sync-state.json"
    sync_data = json.loads(sync_file.read_text(encoding="utf-8"))
    sync_data["records"]["issue:500"]["file_sha256"] = new_snap_sha
    sync_file.write_text(json.dumps(sync_data), encoding="utf-8")

    # curation-decisions.json에서 thread_sha256 갱신
    from artagent.issue_filter import load_sources
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
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    assert prep_2["generation_id"] != prep_1["generation_id"]
    assert prep_2["updated"] == 1
    assert prep_2["unchanged"] == 11

    app_2 = apply_plan(Path(prep_2["plan_path"]), persist_dir, REFERENCE_PATH)
    assert app_2["status"] == "success"
    assert app_2["updated"] == 1
    assert app_2["unchanged"] == 11
    assert app_2["total_active"] == 13

    # vector-state.json에 새 세대 및 변경된 thread_sha256 반영 확인
    state_file = output_dir / "vector-state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["last_completed_generation"] == prep_2["generation_id"]
    item_500 = state_data["items"]["github:artraweditor/ART:issue:500"]
    assert item_500["thread_sha256"] == new_thread_sha
    assert item_500["applied_generation"] == prep_2["generation_id"]


# ---------------------------------------------------------------------------
# 5. 제외, STALE_CURATION 보류 및 재포함 테스트
# ---------------------------------------------------------------------------


def test_exclude_and_reinclude_lifecycle(tmp_path: Path, spec: RetrievalSpec):
    """include -> exclude(검색 배제) -> re-include(복구) 전체 생명주기 검증."""
    persist_dir = tmp_path / "chroma"
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
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_1["plan_path"]), persist_dir, REFERENCE_PATH)

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
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    assert prep_ex["excluded"] == 1
    assert prep_ex["unchanged"] == 11

    app_ex = apply_plan(Path(prep_ex["plan_path"]), persist_dir, REFERENCE_PATH)
    assert app_ex["status"] == "success"
    assert app_ex["excluded"] == 1
    assert app_ex["unchanged"] == 11
    assert app_ex["total_active"] == 12  # 13 - 1 = 12

    # Issue 500 검색 결과 배제 확인
    store = open_store(persist_dir, spec)
    session = load_encoder(spec)
    hits_500 = store.search(
        "aspect ratio",
        session=session,
        source_key=SourceKey("github", "github:artraweditor/ART:issue:500"),
    )
    assert len(hits_500) == 0

    # vector-state에서 excluded 플래그 확인
    state_file = output_dir / "vector-state.json"
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["items"]["github:artraweditor/ART:issue:500"]["status"] == "excluded"

    # 3. Issue 500을 다시 include로 재포함
    original_curation = json.loads(FIXTURE_CURATION.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"] = original_curation["threads"]["issue:500"]
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_re = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    assert prep_re["updated"] == 1
    assert prep_re["unchanged"] == 11

    app_re = apply_plan(Path(prep_re["plan_path"]), persist_dir, REFERENCE_PATH)
    assert app_re["status"] == "success"
    assert app_re["updated"] == 1
    assert app_re["total_active"] == 13

    # Issue 500 검색 정상 복원 확인
    hits_restored = store.search(
        "aspect ratio",
        session=session,
        source_key=SourceKey("github", "github:artraweditor/ART:issue:500"),
    )
    assert len(hits_restored) > 0


# ---------------------------------------------------------------------------
# 6. 이전 계획 재적용 방지 및 오류/복구 검증
# ---------------------------------------------------------------------------


def test_stale_plan_rejection(tmp_path: Path):
    """최신 세대가 적용된 후 이전 세대 계획을 재적용하려는 시도가 거부됨을 검증."""
    persist_dir = tmp_path / "chroma"
    output_dir = tmp_path / "output"
    custom_corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, custom_corpus)
    custom_curation = tmp_path / "curation-decisions.json"
    shutil.copy2(FIXTURE_CURATION, custom_curation)

    # 세대 1 prepare
    prep_1 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_1["plan_path"]), persist_dir, REFERENCE_PATH)

    # 세대 2 prepare & apply
    curation_data = json.loads(custom_curation.read_text(encoding="utf-8"))
    curation_data["threads"]["issue:500"]["disposition"] = "exclude"
    curation_data["threads"]["issue:500"]["reason_codes"] = ["EXCLUDED"]
    custom_curation.write_text(json.dumps(curation_data), encoding="utf-8")

    prep_2 = prepare_generation(
        source_root=ROOT,
        input_dir=custom_corpus,
        curation_path=custom_curation,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    apply_plan(Path(prep_2["plan_path"]), persist_dir, REFERENCE_PATH)

    # 이제 세대 1 계획을 재적용 시도 -> RuntimeError 발생 확인
    with pytest.raises(RuntimeError, match="이전 계획"):
        apply_plan(Path(prep_1["plan_path"]), persist_dir, REFERENCE_PATH)


def test_interrupted_operation_recovery(tmp_path: Path, spec: RetrievalSpec):
    """store_state=updating 상태에서 동일 작업 및 지문으로 재시도 시 정상 복구됨을 검증."""
    persist_dir = tmp_path / "chroma"
    output_dir = tmp_path / "output"

    prep = prepare_generation(
        source_root=ROOT,
        input_dir=FIXTURE_CORPUS,
        curation_path=FIXTURE_CURATION,
        reference_path=REFERENCE_PATH,
        persist_dir=persist_dir,
        output_dir=output_dir,
    )
    plan_path = Path(prep["plan_path"])
    plan_doc = json.loads(plan_path.read_text(encoding="utf-8"))
    first_op = plan_doc["operations"][0]

    # 저장소를 강제로 updating 상태로 설정
    store = open_store(persist_dir, spec)
    store._begin_operation(
        operation="replace_source",
        fingerprint=first_op["t09_operation_fingerprint"],
        key=SourceKey("github", first_op["candidate_id"]),
    )
    assert store._get_store_state() == "updating"

    # 동일 계획 적용 시 복구되어 정상 완료 확인
    res = apply_plan(plan_path, persist_dir, REFERENCE_PATH)
    assert res["status"] == "success"
    assert store._get_store_state() == "ready"

