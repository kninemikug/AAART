from __future__ import annotations

import copy
import dataclasses
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import numpy as np
import pytest

from artagent.retrieval.embedding import (
    EncoderSession,
    embed_chunks,
    embed_query,
    load_encoder,
)
from artagent.retrieval.provenance import (
    Chunk,
    canonical_json_bytes,
    canonical_json_str,
    compute_chunk_id,
    deserialize_chunk,
    load_selected_chunks,
    serialize_metadata,
    sha256_bytes,
    sha256_str,
    validate_provenance,
)
from artagent.retrieval.store import RetrievalStore, open_store
from artagent.retrieval.types import (
    IndexReport,
    RetrievalSpec,
    SearchHit,
    SourceKey,
    load_spec,
)


def find_reference_path() -> Path:
    env_ref = os.getenv("T09_REFERENCE_PATH")
    if env_ref and Path(env_ref).is_file():
        return Path(env_ref).resolve()
    candidates = [
        Path("docs/T08_2_t9_handoff_reference.json"),
        Path("/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json"),
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    raise FileNotFoundError("docs/T08_2_t9_handoff_reference.json을 찾을 수 없습니다.")


def find_source_root() -> Path:
    env_root = os.getenv("T09_SOURCE_ROOT")
    if env_root and Path(env_root).is_dir():
        return Path(env_root).resolve()
    candidates = [
        Path("/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding"),
        Path(".").resolve(),
    ]
    for p in candidates:
        if (p / "data/rawpedia").is_dir() and (p / "data/issues").is_dir():
            return p.resolve()
    return Path(".").resolve()


def find_repro_dir() -> Path:
    env_dir = os.getenv("T09_REPRO_DIR")
    if env_dir and Path(env_dir).is_dir() and (Path(env_dir) / "reproduction.json").is_file():
        return Path(env_dir).resolve()
    for p in sorted(Path("/private/tmp").glob("t09-repro.*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if (p / "reproduction.json").is_file():
            return p.resolve()
    raise FileNotFoundError("reproduction.json이 포함된 T09_REPRO_DIR를 찾을 수 없습니다.")


@pytest.fixture(scope="session")
def reference_path() -> Path:
    return find_reference_path()


@pytest.fixture(scope="session")
def source_root() -> Path:
    return find_source_root()


@pytest.fixture(scope="session")
def repro_dir() -> Path:
    return find_repro_dir()


@pytest.fixture(scope="session")
def spec(reference_path: Path) -> RetrievalSpec:
    return load_spec(reference_path)


@pytest.fixture(scope="session")
def session(spec: RetrievalSpec) -> EncoderSession:
    return load_encoder(spec)


# =========================================================================
# 1. 인계 입력 계약 검증
# =========================================================================

def test_spec_contract_and_reference_fingerprint(reference_path: Path, spec: RetrievalSpec) -> None:
    """모델 revision, 규칙, 풀링, prefix, 차원, 윈도우 설정과 reference SHA 검증."""
    assert spec.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert spec.model_revision == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert spec.ref_tokenizer_id == "BAAI/bge-small-en-v1.5"
    assert spec.ref_tokenizer_revision == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    assert spec.dimension == 384
    assert spec.dtype == "float32"
    assert spec.normalize_embeddings is True
    assert spec.rawpedia_rule == "R-C-heading-window-t8192-o64"
    assert spec.rawpedia_expected_count == 141
    assert spec.rawpedia_expected_sha256 == "8e8f163d2ce8da99fec3dc7e38652ea3d7aecb35997dc20a3d2202c09753c4cd"
    assert spec.github_rule == "G-C-curated-group-t1024-o64"
    assert spec.github_expected_count == 13
    assert spec.github_expected_sha256 == "7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571"
    assert spec.total_expected_count == 154
    assert spec.guard_group == "pooled-common-256"
    assert spec.physical_embedding_policy == "chunk_window_mean_v2"
    assert spec.thread_embedding_policy == "thread_window_mean_v2"
    assert spec.encoder_window_tokens == 224
    assert spec.encoder_overlap_tokens == 0
    assert spec.max_header_tokens == 32
    assert spec.max_seq_length == 256
    assert spec.doc_prefix == ""
    assert spec.query_prefix == ""
    assert spec.space == "cosine"
    assert spec.hnsw_ef_construction == 200
    assert spec.hnsw_ef_search == 200
    assert spec.hnsw_max_neighbors == 16
    assert spec.hnsw_num_threads == 1
    assert spec.reference_sha256 == "2c7081ba6a7c37b00735b0be2ef362f5b0c2a86cd41fe97bbb2a3b5ebdc195bc"
    assert RetrievalSpec().reference_sha256 == spec.reference_sha256
    assert spec.protocol_sha256 == "3694eb3cb0a8b8e989e6bc828adf1f067b4f988f9be0a04a4d43507850412dc5"


# =========================================================================
# 2. 출처 정보 직렬화 / 역직렬화 roundtrip
# =========================================================================

def test_metadata_serialization_roundtrip(spec: RetrievalSpec) -> None:
    """다중 segment, null/선택 필드, UTF-8 및 원본 metadata 전체 roundtrip 검증."""
    seg1 = {
        "doc_id": "doc_kr_1",
        "source_path": "data/rawpedia/sample.md",
        "source_file_sha256": "dummy_sha_1",
        "json_pointer": None,
        "char_start": 0,
        "char_end": 15,
        "byte_start": 0,
        "byte_end": 35,
        "content_char_start": 0,
        "content_char_end": 15,
        "target_url": "https://rawpedia.es/test",
        "segment_sha256": "seg_sha_1",
        "ref_id": None,
    }
    seg2 = {
        "doc_id": "issue_100",
        "source_path": "data/issues/100.json",
        "source_file_sha256": "dummy_sha_2",
        "json_pointer": "/body",
        "char_start": 10,
        "char_end": 30,
        "byte_start": 10,
        "byte_end": 30,
        "content_char_start": 16,
        "content_char_end": 36,
        "target_url": "https://github.com/agriggio/ART/issues/100",
        "segment_sha256": "seg_sha_2",
        "ref_id": "comment_1",
        "curated": True,
    }
    content = "안녕하세요 테스트 본문입니다. GitHub 이슈 내용 포함."
    orig_meta = {
        "schema_version": "t08c:v1",
        "rule_id": "R-C-heading-window-t8192-o64",
        "rule_fingerprint": "R-C-heading-window-t8192-o64:fp123",
        "content_sha256": sha256_str(content),
        "range_basis": "source_file",
        "source_segments": [seg1, seg2],
        "custom_extra_key": {"nested": [1, 2, "한글"]},
    }
    cid = compute_chunk_id(
        schema_version="t08c:v1",
        rule_fingerprint="R-C-heading-window-t8192-o64:fp123",
        source_type="rawpedia",
        doc_id="doc_kr_1",
        source_segments=[seg1, seg2],
        content_sha256=orig_meta["content_sha256"],
    )
    chunk = Chunk(
        chunk_id=cid,
        source_type="rawpedia",
        doc_id="doc_kr_1",
        section_title="노출 보정 (Exposure)",
        content=content,
        char_range=(0, len(content)),
        metadata=orig_meta,
    )

    serialized = serialize_metadata(chunk, spec, excluded=False)
    assert serialized["source_type"] == "rawpedia"
    assert serialized["excluded"] is False
    assert serialized["retrieval_schema_version"] == 1
    assert serialized["reference_sha256"] == spec.reference_sha256

    # 역직렬화
    deserialized = deserialize_chunk(cid, content, serialized)
    assert deserialized.chunk_id == chunk.chunk_id
    assert deserialized.source_type == chunk.source_type
    assert deserialized.doc_id == chunk.doc_id
    assert deserialized.section_title == chunk.section_title
    assert deserialized.content == chunk.content
    assert deserialized.char_range == chunk.char_range
    assert deserialized.metadata == chunk.metadata

    # 변조: original_metadata_json의 source_segments와 source_segments_json 불일치 시 오류
    tampered_meta = dict(serialized)
    tampered_meta["source_segments_json"] = "[]"
    with pytest.raises(ValueError, match="source_segments 불일치"):
        deserialize_chunk(cid, content, tampered_meta)


# =========================================================================
# 3. 출처 불일치 거부 및 경로 안전성
# =========================================================================

def test_provenance_validation_and_tampering(source_root: Path, spec: RetrievalSpec, repro_dir: Path) -> None:
    """원문 파일 SHA, 본문/구간 SHA, 경로 traversal, ID 불일치 거부 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)
    assert len(chunks) == 154

    valid_chunk = chunks[0]
    validate_provenance(valid_chunk, source_root)

    # 1. content 변조 거부
    bad_content_chunk = dataclasses.replace(valid_chunk, content=valid_chunk.content + " modified")
    with pytest.raises(ValueError, match="content SHA256 불일치"):
        validate_provenance(bad_content_chunk, source_root)

    # 2. chunk_id 변조 거부
    bad_id_chunk = dataclasses.replace(valid_chunk, chunk_id=valid_chunk.chunk_id[:-4] + "ffff")
    with pytest.raises(ValueError, match="Chunk ID 불일치"):
        validate_provenance(bad_id_chunk, source_root)

    # 3. 경로 traversal 거부
    traversal_meta = copy.deepcopy(valid_chunk.metadata)
    traversal_meta["source_segments"][0]["source_path"] = "../../../etc/passwd"
    traversal_chunk = dataclasses.replace(valid_chunk, metadata=traversal_meta)
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_provenance(traversal_chunk, source_root)

    # 4. 세그먼트 SHA 변조 거부
    bad_seg_meta = copy.deepcopy(valid_chunk.metadata)
    bad_seg_meta["source_segments"][0]["segment_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
    bad_seg_chunk = dataclasses.replace(valid_chunk, metadata=bad_seg_meta)
    with pytest.raises(ValueError):
        validate_provenance(bad_seg_chunk, source_root)


# =========================================================================
# 4. 윈도우 평균 정책 (chunk_window_mean_v2) 검증
# =========================================================================

def test_window_mean_v2_logic(session: EncoderSession) -> None:
    """224토큰 분할, 본문 토큰 가중치 w_i, 헤더 32토큰 제한 검증."""
    ref_tok = session.ref_tokenizer

    long_header = "Very Long Section Header " * 20  # > 32 tokens
    long_body = "This is an important body sentence explaining exposure and raw processing. " * 30  # > 224 tokens

    content_sha = sha256_str(long_body)
    meta = {
        "schema_version": "t08c:v1",
        "rule_id": "R-C-heading-window-t8192-o64",
        "rule_fingerprint": "R-C-heading-window-t8192-o64:fp",
        "content_sha256": content_sha,
        "range_basis": "source_file",
        "source_segments": [{
            "doc_id": "doc1",
            "ref_id": None,
            "segment_sha256": content_sha,
            "char_start": 0,
            "char_end": len(long_body),
            "content_char_start": 0,
            "content_char_end": len(long_body),
        }],
    }
    cid = compute_chunk_id(
        schema_version="t08c:v1",
        rule_fingerprint="R-C-heading-window-t8192-o64:fp",
        source_type="rawpedia",
        doc_id="doc1",
        source_segments=meta["source_segments"],
        content_sha256=content_sha,
    )
    chunk = Chunk(
        chunk_id=cid,
        source_type="rawpedia",
        doc_id="doc1",
        section_title=long_header,
        content=long_body,
        char_range=(0, len(long_body)),
        metadata=meta,
    )

    trace_records = []
    vecs = embed_chunks([chunk], session, trace_callback=trace_records.append)

    assert vecs.shape == (1, 384)
    assert vecs.dtype == np.float32
    assert abs(np.linalg.norm(vecs[0]) - 1.0) <= 1e-5

    assert len(trace_records) == 1
    record = trace_records[0]
    windows = record["windows"]
    assert len(windows) >= 2  # 분할되었는지 확인

    # 각 윈도우의 input_tokens가 256 이하인지 확인
    for w in windows:
        assert w["input_tokens"] <= 256
        assert w["body_token_weight"] > 0
        assert w["header_token_weight"] == 0


# =========================================================================
# 5. 실제 임베딩 재현 대조 (T08-2 벡터 파일 SHA 대조)
# =========================================================================

def test_actual_embedding_reproduction(repro_dir: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path) -> None:
    """141/13개 실제 청크 및 100개 쿼리 임베딩이 기대 벡터 파일 SHA와 일치하는지 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    all_chunks = load_selected_chunks(manifest_path, spec, source_root)

    rawpedia_chunks = [c for c in all_chunks if c.source_type == "rawpedia"]
    github_chunks = [c for c in all_chunks if c.source_type == "github"]

    assert len(rawpedia_chunks) == 141
    assert len(github_chunks) == 13

    # 1. RawPedia 벡터 계산 및 대조
    raw_vecs = embed_chunks(rawpedia_chunks, session)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as tmp:
        np.save(tmp.name, raw_vecs)
        tmp_path = Path(tmp.name)
    actual_raw_sha = sha256_bytes(tmp_path.read_bytes())
    tmp_path.unlink()
    assert actual_raw_sha == "88f5bf0e1ed5dfee85a4ee77768fd88e8d5088cd73c5a72b2725d9bd754ea018"

    # 2. GitHub 벡터 계산 및 대조
    gh_vecs = embed_chunks(github_chunks, session)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as tmp:
        np.save(tmp.name, gh_vecs)
        tmp_path = Path(tmp.name)
    actual_gh_sha = sha256_bytes(tmp_path.read_bytes())
    tmp_path.unlink()
    assert actual_gh_sha == "6a851588ab8b2a466e033bb13e4de296d9c5ced58b0ca4cd7eb8d24d27b2a2ef"

    # 3. 100개 쿼리 벡터 계산 및 대조
    queries_file = repro_dir / "chunks/manifest.json"
    queries_path = Path("docs/search_eval_queries.json").resolve()
    if not queries_path.is_file():
        queries_path = (source_root / "docs/search_eval_queries.json").resolve()
    queries_data = json.loads(queries_path.read_bytes())["queries"]
    assert len(queries_data) == 100

    q_vecs = np.zeros((100, 384), dtype=np.float32)
    for i, q in enumerate(queries_data):
        q_vecs[i] = embed_query(q["query"], session)

    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as tmp:
        np.save(tmp.name, q_vecs)
        tmp_path = Path(tmp.name)
    actual_q_sha = sha256_bytes(tmp_path.read_bytes())
    tmp_path.unlink()
    assert actual_q_sha == "abe189f84bb4d7276b920c72569e78d151e4b1ca41babae5e406857f6a699822"


# =========================================================================
# 6. 실제 154개 전량 적재 및 HNSW 인덱스 계약 검증
# =========================================================================

def test_index_all_and_hnsw_contract(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path) -> None:
    """154개 전량 Chroma 적재 및 HNSW 설정 5개(cosine/200/200/16/1) 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "chroma_db"
    store = open_store(persist_dir, spec)

    report = store.index_all(chunks, session, source_root=source_root)
    assert report.status == "success"
    assert report.created == 154
    assert report.total_active == 154
    assert store.collection.count() == 154

    # HNSW 설정 검증
    cfg = store.collection.schema.keys["#embedding"].float_list.vector_index.config
    assert cfg.space == "cosine"
    assert cfg.hnsw.ef_construction == 200
    assert cfg.hnsw.ef_search == 200
    assert cfg.hnsw.max_neighbors == 16
    assert cfg.hnsw.num_threads == 1

    # 단일 쿼리 검색 테스트
    hits = store.search("exposure compensation", session)
    assert len(hits) == 5
    for h in hits:
        assert h.rank in (1, 2, 3, 4, 5)
        assert len(h.distance_text) == 8  # e.g. "0.123456"
        assert len(h.source_segments) > 0


# =========================================================================
# 7. 영속 저장소 재개방 검증
# =========================================================================

def test_reopen_persistent_store(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path) -> None:
    """영속 경로 재개방 후 건수 154개, 계약, 검색 결과 일관성 유지 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "persist_test"
    store1 = open_store(persist_dir, spec)
    store1.index_all(chunks, session, source_root=source_root)
    hits1 = store1.search("tone curve contrast", session)

    # 재개방
    store2 = open_store(persist_dir, spec)
    assert store2.collection.count() == 154
    hits2 = store2.search("tone curve contrast", session)

    assert [h.chunk_id for h in hits1] == [h.chunk_id for h in hits2]
    assert [h.distance for h in hits1] == [h.distance for h in hits2]


# =========================================================================
# 8. T08-2 선정 검색 회귀 전수 대조 (300회 top5 순위 지문 + 거리 오차 <= 1e-5)
# =========================================================================

def test_search_regression_and_metric_parity(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path) -> None:
    """100문항 x 3회 검색 수행 후 T08-2 순위 지문 및 거리 차이 전수 대조."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "regression_db"
    store = open_store(persist_dir, spec)
    store.index_all(chunks, session, source_root=source_root)

    queries_path = Path("docs/search_eval_queries.json").resolve()
    if not queries_path.is_file():
        queries_path = (source_root / "docs/search_eval_queries.json").resolve()
    queries = json.loads(queries_path.read_bytes())["queries"]

    # 재현 로그 읽기
    res_json = repro_dir / "selected-results.json"
    if res_json.is_file():
        fresh = json.loads(res_json.read_bytes())
        row = fresh["experiments"][0]
        run_log = Path(row["query_log"]["path"])
    else:
        run_log = next((repro_dir / "run/runs").glob("*.jsonl.gz"))

    with gzip.open(run_log, "rt", encoding="utf-8") as f:
        repro_records = [json.loads(line) for line in f]

    repro_by_key = {(r["query_id"], r["repeat"]): r for r in repro_records}

    rankings = []
    largest_dist_delta = 0.0

    for repeat in range(3):
        for q in queries:
            qid = q["query_id"]
            hits = store.search(q["query"], session)
            assert len(hits) == 5

            hit_ids = [h.chunk_id for h in hits]
            rankings.append([qid, repeat, hit_ids])

            # 거리 오차 검증
            ref_rec = repro_by_key[(qid, repeat)]
            ref_top5 = ref_rec["top5"]
            for h, ref_c in zip(hits, ref_top5):
                assert h.chunk_id == ref_c["chunk_id"], f"Rank mismatch in {qid} repeat {repeat}"
                delta = abs(h.distance - ref_c["distance"])
                largest_dist_delta = max(largest_dist_delta, delta)

    # 300회 top5 순위 지문 검증
    rankings.sort(key=lambda x: (x[0], x[1]))
    actual_ranked_sha = hashlib.sha256(
        json.dumps(rankings, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    expected_ranked_sha = "a8ac9685ce31717b4d2b7cfe10bb635f5016dec41f4b8be0ca273b4bb0dbf25c"
    assert actual_ranked_sha == expected_ranked_sha, f"순위 지문 불일치: 실제 {actual_ranked_sha} != 기대 {expected_ranked_sha}"
    assert largest_dist_delta <= 1e-5, f"최대 거리 차이 초과: {largest_dist_delta} > 1e-5"


# =========================================================================
# 9. 동점 처리 및 6자리 포맷팅
# =========================================================================

def test_tie_breaking_and_distance_text_formatting(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession) -> None:
    """반올림 6자리 동점 시 chunk_id 오름차순 정렬 및 distance_text 6자리 확인."""
    persist_dir = tmp_path / "tie_test"
    store = open_store(persist_dir, spec)

    # 동일한 벡터를 가지는 서로 다른 청크 3개 생성
    content1 = "동일한 본문 내용입니다. A"
    content2 = "동일한 본문 내용입니다. B"
    content3 = "동일한 본문 내용입니다. C"

    # 수동 upsert
    v = [0.1] * 384
    norm = np.linalg.norm(v)
    v = (v / norm).tolist()

    ids = ["chunk_zeta", "chunk_alpha", "chunk_beta"]
    docs = [content1, content2, content3]
    metas = []
    for cid, doc in zip(ids, docs):
        metas.append({
            "source_type": "rawpedia",
            "doc_id": "doc1",
            "source_group_id": "doc1",
            "section_title": "Title",
            "rule_id": spec.rawpedia_rule,
            "rule_fingerprint": "fp",
            "content_sha256": sha256_str(doc),
            "range_basis": "source_file",
            "char_range_json": "[0, 10]",
            "source_segments_json": "[]",
            "original_metadata_json": "{}",
            "retrieval_schema_version": 1,
            "reference_sha256": spec.reference_sha256,
            "excluded": False,
        })

    store.collection.upsert(
        ids=ids,
        embeddings=[v, v, v],
        documents=docs,
        metadatas=metas,
    )
    store._set_store_state("ready")

    hits = store.search("동일한 본문 내용", session)
    assert len(hits) == 3
    # 동점 거리이므로 chunk_id 기준 오름차순: chunk_alpha -> chunk_beta -> chunk_zeta
    assert [h.chunk_id for h in hits] == ["chunk_alpha", "chunk_beta", "chunk_zeta"]
    for h in hits:
        # 소수점 6자리 확인
        parts = h.distance_text.split(".")
        assert len(parts) == 2 and len(parts[1]) == 6


# =========================================================================
# 10. 후보 수 및 빈 저장소 처리
# =========================================================================

def test_candidate_counts_and_empty_store(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession) -> None:
    """빈 저장소 및 1~4개 청크에 대한 검색 결과 크기 처리 검증."""
    persist_dir = tmp_path / "candidate_test"
    store = open_store(persist_dir, spec)

    # 1. 빈 저장소 -> []
    assert store.search("query on empty store", session) == []

    # 2. 2개 청크 적재 -> top5 요청 시 2개 반환
    v = [0.1] * 384
    v = (v / np.linalg.norm(v)).tolist()
    store.collection.upsert(
        ids=["id1", "id2"],
        embeddings=[v, v],
        documents=["doc1", "doc2"],
        metadatas=[
            {
                "source_type": "rawpedia",
                "doc_id": "d1",
                "source_group_id": "d1",
                "section_title": "T1",
                "rule_id": spec.rawpedia_rule,
                "rule_fingerprint": "fp",
                "content_sha256": sha256_str("doc1"),
                "range_basis": "source_file",
                "char_range_json": "[0, 4]",
                "source_segments_json": "[]",
                "original_metadata_json": "{}",
                "retrieval_schema_version": 1,
                "reference_sha256": spec.reference_sha256,
                "excluded": False,
            },
            {
                "source_type": "rawpedia",
                "doc_id": "d2",
                "source_group_id": "d2",
                "section_title": "T2",
                "rule_id": spec.rawpedia_rule,
                "rule_fingerprint": "fp",
                "content_sha256": sha256_str("doc2"),
                "range_basis": "source_file",
                "char_range_json": "[0, 4]",
                "source_segments_json": "[]",
                "original_metadata_json": "{}",
                "retrieval_schema_version": 1,
                "reference_sha256": spec.reference_sha256,
                "excluded": False,
            },
        ],
    )
    store._set_store_state("ready")

    hits = store.search("doc", session)
    assert len(hits) == 2


# =========================================================================
# 11. 멱등 재적재 (Idempotent Indexing)
# =========================================================================

def test_idempotent_index(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path) -> None:
    """동일 154개 재적재 시 중복 없이 건수 154개 유지 및 순위 유지."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "idempotent_db"
    store = open_store(persist_dir, spec)

    rep1 = store.index_all(chunks, session, source_root=source_root)
    assert rep1.total_active == 154

    rep2 = store.index_all(chunks, session, source_root=source_root)
    assert rep2.total_active == 154
    assert store.collection.count() == 154


# =========================================================================
# 12. 그룹 갱신 및 구 청크 삭제 (replace_source)
# =========================================================================

@pytest.mark.parametrize("source_type", ["rawpedia", "github"])
def test_group_update_and_cleanup(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path, source_type: str) -> None:
    """두 출처의 실제 본문 갱신, 구 ID 삭제, 다른 그룹 보존과 재실행 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "replace_db"
    store = open_store(persist_dir, spec)
    store.index_all(chunks, session, source_root=source_root)

    target = next(chunk for chunk in chunks if chunk.source_type == source_type)
    target_group_chunks = [
        chunk for chunk in chunks
        if chunk.source_type == source_type and chunk.doc_id == target.doc_id
    ]
    key = SourceKey(source_type=source_type, source_group_id=target.doc_id)
    old_ids = {chunk.chunk_id for chunk in target_group_chunks}
    other_ids = {chunk.chunk_id for chunk in chunks} - old_ids
    other_before = store.collection.get(ids=sorted(other_ids), include=["documents", "metadatas", "embeddings"])

    # 1. 동일 청크로 갱신 시 쓰기 생략 확인
    rep_same = store.replace_source(key, target_group_chunks, session, source_root=source_root)
    assert rep_same.unchanged == len(target_group_chunks)

    # 원본 파일은 유지하고, 실제 원문에서 파생한 새 snapshot을 임시 경로에 둔다.
    updated_root = tmp_path / "updated_source"
    updated_root.mkdir()
    updated_content = target.content + "\nUpdated exposure and white balance instructions."
    relative_path = "updated.md" if source_type == "rawpedia" else "updated.json"
    snapshot_bytes = (
        updated_content.encode("utf-8") if source_type == "rawpedia"
        else canonical_json_bytes({"body": updated_content})
    )
    (updated_root / relative_path).write_bytes(snapshot_bytes)
    segment = copy.deepcopy(target.metadata["source_segments"][0])
    segment.update({
        "source_path": relative_path,
        "source_file_sha256": sha256_bytes(snapshot_bytes),
        "json_pointer": None if source_type == "rawpedia" else "/body",
        "char_start": 0,
        "char_end": len(updated_content),
        "byte_start": 0,
        "byte_end": len(updated_content.encode("utf-8")),
        "content_char_start": 0,
        "content_char_end": len(updated_content),
        "segment_sha256": sha256_str(updated_content),
    })
    if source_type == "github":
        segment["body_sha256"] = sha256_str(updated_content)
    updated_metadata = copy.deepcopy(target.metadata)
    updated_metadata.update({
        "content_sha256": sha256_str(updated_content),
        "range_basis": "source_file" if source_type == "rawpedia" else "json_body",
        "source_segments": [segment],
    })
    updated = Chunk(
        chunk_id=compute_chunk_id(
            "t08c:v1", target.rule_fingerprint, source_type, target.doc_id,
            [segment], sha256_str(updated_content),
        ),
        source_type=source_type,
        doc_id=target.doc_id,
        section_title=target.section_title,
        content=updated_content,
        char_range=(0, len(updated_content)),
        metadata=updated_metadata,
    )
    assert updated.chunk_id not in old_ids
    validate_provenance(updated, updated_root)
    report = store.replace_source(key, [updated], session, source_root=updated_root)
    assert report.created == 1
    assert report.deleted == len(old_ids)
    assert set(store.collection.get()["ids"]) == other_ids | {updated.chunk_id}
    assert store.collection.count() == 154 - len(old_ids) + 1
    stored_update = store.collection.get(ids=[updated.chunk_id], include=["documents", "metadatas"])
    assert stored_update["documents"] == [updated_content]
    assert stored_update["metadatas"] == [serialize_metadata(updated, spec, excluded=False)]

    other_after = store.collection.get(ids=sorted(other_ids), include=["documents", "metadatas", "embeddings"])
    assert other_after["ids"] == other_before["ids"]
    assert other_after["documents"] == other_before["documents"]
    assert other_after["metadatas"] == other_before["metadatas"]
    np.testing.assert_array_equal(other_after["embeddings"], other_before["embeddings"])
    retry = store.replace_source(key, [updated], session, source_root=updated_root)
    assert retry.unchanged == 1
    assert retry.created == retry.updated == retry.deleted == 0
    assert set(store.collection.get()["ids"]) == other_ids | {updated.chunk_id}


# =========================================================================
# 13. 검색 제외 및 재포함 (exclude_source)
# =========================================================================

def test_exclude_and_reinclude_source(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession, source_root: Path, repro_dir: Path) -> None:
    """exclude_source로 제외 시 검색 결과에서 즉시 배제 및 replace_source로 재포함 검증."""
    manifest_path = repro_dir / "chunks/manifest.json"
    chunks = load_selected_chunks(manifest_path, spec, source_root)

    persist_dir = tmp_path / "exclude_db"
    store = open_store(persist_dir, spec)
    store.index_all(chunks, session, source_root=source_root)

    # 특정 질문으로 top1 청크 찾기
    q = "exposure compensation"
    hits_before = store.search(q, session)
    assert len(hits_before) > 0
    top1 = hits_before[0]
    target_key = SourceKey(source_type=top1.source_type, source_group_id=top1.source_group_id)

    # 그룹 제외 실행
    rep_ex = store.exclude_source(target_key)
    assert rep_ex.excluded > 0
    # 물리 건수는 154 유지
    assert store.collection.count() == 154

    # 제외 후 검색 결과에서 해당 그룹 청크가 없음을 확인
    hits_after = store.search(q, session)
    for h in hits_after:
        assert not (h.source_type == target_key.source_type and h.source_group_id == target_key.source_group_id)

    # 반복 제외 멱등성 확인
    rep_ex2 = store.exclude_source(target_key)
    assert rep_ex2.excluded == rep_ex.excluded

    # 재포함: 원래 청크셋으로 replace_source
    group_chunks = [c for c in chunks if c.source_type == target_key.source_type and c.doc_id == target_key.source_group_id]
    store.replace_source(target_key, group_chunks, session, source_root=source_root)

    # 재포함 후 다시 top에 나타남을 확인
    hits_restored = store.search(q, session)
    assert hits_restored[0].chunk_id == top1.chunk_id


# =========================================================================
# 14. 입력 경계 및 계약 위반 거부
# =========================================================================

def test_input_validation_and_errors(tmp_path: Path, spec: RetrievalSpec, session: EncoderSession) -> None:
    """빈 쿼리, 256토큰 초과 쿼리, updating 상태에서의 검색 거부 검증."""
    persist_dir = tmp_path / "error_test"
    store = open_store(persist_dir, spec)

    # 1. 빈 쿼리 거부
    with pytest.raises(ValueError, match="빈 검색어"):
        store.search("", session)

    with pytest.raises(ValueError, match="빈 검색어"):
        store.search("   \n\t ", session)

    # 2. 256토큰 초과 쿼리 거부
    long_query = "word " * 300
    with pytest.raises(ValueError, match="최대 허용치"):
        store.search(long_query, session)

    # 3. updating 상태에서 검색 시 RuntimeError 거부
    store._set_store_state("updating")
    with pytest.raises(RuntimeError, match="저장소가 준비되지 않았습니다"):
        store.search("valid query", session)
    store._set_store_state("ready")
