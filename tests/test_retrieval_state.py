from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
from typing import Sequence

import numpy as np
import pytest

from artagent.retrieval.embedding import EncoderSession
from artagent.retrieval.provenance import (
    Chunk,
    canonical_json_bytes,
    compute_chunk_id,
    serialize_metadata,
    sha256_bytes,
    sha256_str,
    validate_provenance,
)
from artagent.retrieval.store import RetrievalStore, open_store
from artagent.retrieval.types import RetrievalSpec, SourceKey
import artagent.retrieval.store as store_module


def snapshot_chunks(
    root: Path,
    source_type: str,
    group: str,
    contents: Sequence[str],
    *,
    title: str = "Exposure adjustment",
    suffix: str = "",
    url: str = "https://example.test/source",
) -> list[Chunk]:
    """실제 파일과 일치하는 문자·바이트 범위 및 출처 ID를 만든다."""
    root.mkdir(parents=True, exist_ok=True)
    body = "\n".join(contents) + suffix
    relative_path = f"{group}.md" if source_type == "rawpedia" else f"{group}.json"
    source_bytes = (
        body.encode("utf-8")
        if source_type == "rawpedia"
        else canonical_json_bytes({"body": body, "title": title})
    )
    (root / relative_path).write_bytes(source_bytes)
    spec = RetrievalSpec()
    rule = spec.rawpedia_rule if source_type == "rawpedia" else spec.github_rule
    chunks = []
    start = 0
    for content in contents:
        end = start + len(content)
        segment = {
            "doc_id": group,
            "ref_id": None if source_type == "rawpedia" else f"{group}:body",
            "source_path": relative_path,
            "source_file_sha256": sha256_bytes(source_bytes),
            "json_pointer": None if source_type == "rawpedia" else "/body",
            "char_start": start,
            "char_end": end,
            "byte_start": len(body[:start].encode("utf-8")),
            "byte_end": len(body[:end].encode("utf-8")),
            "content_char_start": 0,
            "content_char_end": len(content),
            "segment_sha256": sha256_str(content),
            "target_url": url,
        }
        if source_type == "github":
            segment["body_sha256"] = sha256_str(body)
        metadata = {
            "schema_version": "t08c:v1",
            "rule_id": rule,
            "rule_fingerprint": f"{rule}:state-regression",
            "content_sha256": sha256_str(content),
            "page_title": title,
            "range_basis": "source_file" if source_type == "rawpedia" else "json_body",
            "source_segments": [segment],
        }
        chunk = Chunk(
            chunk_id=compute_chunk_id(
                "t08c:v1", metadata["rule_fingerprint"], source_type,
                group, [segment], metadata["content_sha256"],
            ),
            source_type=source_type,
            doc_id=group,
            section_title=title,
            content=content,
            char_range=(start, end),
            metadata=metadata,
        )
        validate_provenance(chunk, root)
        chunks.append(chunk)
        start = end + 1
    return chunks


def fixed_vectors(chunks: Sequence[Chunk], session: EncoderSession) -> np.ndarray:
    """제목과 본문 변경을 구분하는 고정 float32 정규화 벡터."""
    vectors = []
    for chunk in chunks:
        header = str(chunk.metadata.get("page_title", "")) + chunk.section_title
        digest = hashlib.sha256((header + chunk.content).encode("utf-8")).digest()
        vector = np.tile(np.frombuffer(digest, dtype=np.uint8), 12).astype(np.float32) + 1
        vector /= np.linalg.norm(vector)
        vectors.append(vector)
    return np.asarray(vectors, dtype=np.float32).reshape(len(chunks), 384)


@pytest.fixture
def state_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = RetrievalSpec()
    session = EncoderSession(model=None, ref_tokenizer=None, spec=spec)
    monkeypatch.setattr(store_module, "embed_chunks", fixed_vectors)
    query_vector = np.ones(384, dtype=np.float32) / np.sqrt(np.float32(384))
    monkeypatch.setattr(store_module, "embed_query", lambda query, encoder: query_vector)
    source_root = tmp_path / "sources"
    groups = {
        SourceKey("rawpedia", "raw-one"): snapshot_chunks(
            source_root, "rawpedia", "raw-one",
            ["First exposure correction.", "Second white balance correction."],
        ),
        SourceKey("github", "issue-one"): snapshot_chunks(
            source_root, "github", "issue-one",
            ["Issue body has an exposure problem.", "A reply explains white balance."],
        ),
    }
    store = open_store(tmp_path / "db", spec)
    for key, chunks in groups.items():
        store.replace_source(key, chunks, session, source_root=source_root)
    return store, spec, session, source_root, groups


@pytest.mark.parametrize("field,value", [
    ("model_id", "other/model"),
    ("model_revision", "other-revision"),
    ("dimension", 768),
    ("dtype", "float64"),
    ("normalize_embeddings", False),
    ("doc_prefix", "document: "),
    ("query_prefix", "query: "),
    ("reference_sha256", "different-reference"),
    ("protocol_sha256", "different-protocol"),
    ("ref_tokenizer_id", "different/tokenizer"),
    ("ref_tokenizer_revision", "different-tokenizer-revision"),
    ("physical_embedding_policy", "different-pooling"),
    ("thread_embedding_policy", "different-thread-pooling"),
    ("encoder_window_tokens", 112),
    ("encoder_overlap_tokens", 16),
    ("max_header_tokens", 16),
    ("max_seq_length", 512),
    ("rawpedia_rule", "different-rule"),
    ("retrieval_schema_version", 2),
])
def test_existing_store_rejects_changed_spec(state_db, field: str, value) -> None:
    store, spec, _, _, _ = state_db
    with pytest.raises(ValueError):
        open_store(store.persist_dir, replace(spec, **{field: value}))


def test_existing_handle_rejects_changed_persisted_contract(state_db) -> None:
    store, spec, session, _, _ = state_db
    other = store.client.get_collection(spec.collection_name)
    changed = dict(other.metadata)
    changed["model_revision"] = "changed-after-open"
    other.modify(metadata=changed)
    with pytest.raises(ValueError):
        store.search("exposure", session)


@pytest.mark.parametrize("field", ["model_revision", "dimension", "doc_prefix", "reference_sha256"])
def test_existing_store_rejects_missing_required_contract_field(state_db, field: str) -> None:
    store, spec, _, _, _ = state_db
    existing = store.client.get_collection(spec.collection_name)
    metadata = dict(existing.metadata)
    metadata.pop(field)
    existing.modify(metadata=metadata)
    with pytest.raises(ValueError):
        open_store(store.persist_dir, spec)


@pytest.mark.parametrize("override", [
    {},
    {"ref_tokenizer_id": "different/tokenizer"},
    {"thread_embedding_policy": "different-thread-pooling"},
    {"encoder_window_tokens": 112},
    {"encoder_overlap_tokens": 16},
    {"max_header_tokens": 16},
    {"max_seq_length": 512},
])
def test_legacy_metadata_uses_only_fixed_historical_defaults(state_db, override: dict) -> None:
    store, spec, session, _, _ = state_db
    existing = store.client.get_collection(spec.collection_name)
    metadata = dict(existing.metadata)
    for field in (
        "ref_tokenizer_id", "thread_embedding_policy", "encoder_window_tokens",
        "encoder_overlap_tokens", "max_header_tokens", "max_seq_length",
    ):
        metadata.pop(field)
    existing.modify(metadata=metadata)
    if override:
        with pytest.raises(ValueError):
            open_store(store.persist_dir, replace(spec, **override))
    else:
        reopened = open_store(store.persist_dir, spec)
        assert reopened._get_store_state() == "ready"
        assert len(reopened.search("exposure", session)) == 4
        persisted = reopened.client.get_collection(spec.collection_name)
        assert dict(persisted.metadata) == metadata


@pytest.mark.parametrize("operation", ["search", "replace_source", "index_all"])
def test_store_rejects_session_contract_mismatch(state_db, operation: str) -> None:
    store, spec, session, source_root, groups = state_db
    incompatible = replace(session, spec=replace(spec, model_revision="other-revision"))
    key, chunks = next(iter(groups.items()))
    with pytest.raises(ValueError):
        if operation == "search":
            store.search("exposure", incompatible)
        elif operation == "replace_source":
            store.replace_source(key, chunks, incompatible, source_root=source_root)
        else:
            store.index_all(list(chunk for group in groups.values() for chunk in group), incompatible, source_root=source_root)


@pytest.mark.parametrize("invalid_vector", [
    "float64", "wrong_dimension", "nan", "zero", "norm_outside_absolute_tolerance",
])
def test_search_rejects_invalid_embedding_output(state_db, monkeypatch: pytest.MonkeyPatch, invalid_vector: str) -> None:
    store, _, session, _, _ = state_db
    vector = np.zeros(384, dtype=np.float32)
    vector[0] = 1
    if invalid_vector == "float64":
        vector = vector.astype(np.float64)
    elif invalid_vector == "wrong_dimension":
        vector = vector[:383]
    elif invalid_vector == "nan":
        vector[0] = np.nan
    elif invalid_vector == "zero":
        vector[0] = 0
    else:
        vector[0] = np.float32(1 + 1.5e-5)
        assert float(np.linalg.norm(vector)) - 1 > 1e-5
    monkeypatch.setattr(store_module, "embed_query", lambda query, encoder: vector)
    with pytest.raises(ValueError, match="임베딩"):
        store.search("exposure", session)


@pytest.mark.parametrize("source_type", ["rawpedia", "github"])
def test_same_id_metadata_and_title_changes_are_persisted(state_db, source_type: str) -> None:
    store, spec, session, source_root, groups = state_db
    key = next(key for key in groups if key.source_type == source_type)
    original = groups[key]
    before = store.collection.get(ids=[chunk.chunk_id for chunk in original], include=["embeddings"])
    before_vectors = dict(zip(before["ids"], before["embeddings"]))
    changed = snapshot_chunks(
        source_root, source_type, key.source_group_id,
        [chunk.content for chunk in original], title="Changed page and section title",
        suffix="\nSnapshot changed outside the selected segments.",
        url="https://example.test/updated-source",
    )
    assert [chunk.chunk_id for chunk in changed] == [chunk.chunk_id for chunk in original]

    report = store.replace_source(key, changed, session, source_root=source_root)
    assert report.unchanged == 0
    after = store.collection.get(ids=[chunk.chunk_id for chunk in changed], include=["metadatas", "documents", "embeddings"])
    after_by_id = {
        chunk_id: (document, metadata, vector)
        for chunk_id, document, metadata, vector in zip(after["ids"], after["documents"], after["metadatas"], after["embeddings"])
    }
    expected_vectors = fixed_vectors(changed, session)
    for chunk, expected_vector in zip(changed, expected_vectors):
        document, metadata, vector = after_by_id[chunk.chunk_id]
        assert document == chunk.content
        assert metadata == serialize_metadata(chunk, spec, excluded=False)
        np.testing.assert_allclose(vector, expected_vector, rtol=0, atol=1e-7)
        assert not np.array_equal(vector, before_vectors[chunk.chunk_id])
    hits = store.search("exposure", session, source_key=key)
    assert {hit.section_title for hit in hits} == {"Changed page and section title"}
    assert all(hit.source_segments[0]["target_url"] == "https://example.test/updated-source" for hit in hits)


@pytest.mark.parametrize("source_type", ["rawpedia", "github"])
def test_provenance_only_changes_are_persisted(state_db, source_type: str) -> None:
    store, spec, session, source_root, groups = state_db
    key = next(key for key in groups if key.source_type == source_type)
    original = groups[key]
    changed = snapshot_chunks(
        source_root, source_type, key.source_group_id,
        [chunk.content for chunk in original],
        suffix="\nChanged snapshot outside the selected segment.",
        url="https://example.test/new-canonical-url",
    )
    assert [chunk.chunk_id for chunk in changed] == [chunk.chunk_id for chunk in original]
    report = store.replace_source(key, changed, session, source_root=source_root)
    assert report.unchanged == 0
    after = store.collection.get(ids=[chunk.chunk_id for chunk in changed], include=["metadatas"])
    actual = dict(zip(after["ids"], after["metadatas"]))
    for chunk in changed:
        assert actual[chunk.chunk_id] == serialize_metadata(chunk, spec, excluded=False)


def test_identical_replace_skips_embedding_and_database_writes(state_db, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, session, source_root, groups = state_db
    key, chunks = next(iter(groups.items()))

    def unexpected(*args, **kwargs):
        pytest.fail("동일 입력을 재계산하거나 저장하지 않아야 합니다.")

    monkeypatch.setattr(store_module, "embed_chunks", unexpected)
    monkeypatch.setattr(type(store.collection), "upsert", unexpected)
    monkeypatch.setattr(type(store.collection), "modify", unexpected)
    report = store.replace_source(key, copy.deepcopy(chunks), session, source_root=source_root)
    assert report.unchanged == len(chunks)
    assert store._get_store_state() == "ready"


def test_identical_index_skips_embedding_and_database_writes(state_db, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, session, source_root, groups = state_db
    chunks = [chunk for group in groups.values() for chunk in group]

    def unexpected(*args, **kwargs):
        pytest.fail("동일 입력을 재계산하거나 저장하지 않아야 합니다.")

    monkeypatch.setattr(store_module, "embed_chunks", unexpected)
    monkeypatch.setattr(type(store.collection), "upsert", unexpected)
    monkeypatch.setattr(type(store.collection), "modify", unexpected)
    report = store.index_all(copy.deepcopy(chunks), session, source_root=source_root)
    assert report.unchanged == len(chunks)
    assert report.total_active == len(chunks)


def test_index_reports_exclude_inactive_rows(state_db) -> None:
    store, _, session, source_root, groups = state_db
    key, chunks = next(iter(groups.items()))
    physical_count = store.collection.count()
    excluded = store.exclude_source(key)
    assert excluded.total_active == physical_count - len(chunks)
    repeated = store.exclude_source(key)
    assert repeated.total_active == physical_count - len(chunks)
    other_key = next(candidate for candidate in groups if candidate != key)
    untouched = store.replace_source(other_key, groups[other_key], session, source_root=source_root)
    assert untouched.total_active == physical_count - len(chunks)
    missing = store.exclude_source(SourceKey("rawpedia", "missing-group"))
    assert missing.total_active == physical_count - len(chunks)
    restored = store.replace_source(key, chunks, session, source_root=source_root)
    assert restored.total_active == physical_count
    assert store.collection.count() == physical_count


def test_search_rejects_inconsistent_source_segment_copies(state_db) -> None:
    store, _, session, _, groups = state_db
    key, chunks = next(iter(groups.items()))
    chunk = chunks[0]
    stored = store.collection.get(ids=[chunk.chunk_id], include=["metadatas"])
    metadata = dict(stored["metadatas"][0])
    segments = json.loads(metadata["source_segments_json"])
    segments[0]["target_url"] = "https://example.test/inconsistent-copy"
    metadata["source_segments_json"] = json.dumps(segments)
    store.collection.update(ids=[chunk.chunk_id], metadatas=[metadata])
    with pytest.raises(ValueError, match="source_segments"):
        store.search("exposure", session, source_key=key)


def fail_ready_once(store: RetrievalStore, monkeypatch: pytest.MonkeyPatch) -> None:
    original = store._set_store_state

    def set_state(state: str, **extra):
        if state == "ready":
            raise RuntimeError("injected ready failure")
        return original(state, **extra)

    monkeypatch.setattr(store, "_set_store_state", set_state)


@pytest.mark.parametrize("operation", ["exclude_source", "replace_source"])
def test_retry_after_applied_mutation_restores_ready(state_db, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    store, spec, session, source_root, groups = state_db
    key, old_chunks = next(iter(groups.items()))
    changed = snapshot_chunks(source_root, key.source_type, key.source_group_id, ["New correction instructions."])
    fail_ready_once(store, monkeypatch)
    with pytest.raises(RuntimeError, match="injected ready failure"):
        if operation == "exclude_source":
            store.exclude_source(key)
        else:
            store.replace_source(key, changed, session, source_root=source_root)
    assert store._get_store_state() == "updating"

    reopened = open_store(store.persist_dir, spec)
    if operation == "exclude_source":
        reopened.exclude_source(key)
        assert reopened.search("exposure", session, source_key=key) == []
    else:
        reopened.replace_source(key, changed, session, source_root=source_root)
        assert {hit.chunk_id for hit in reopened.search("exposure", session, source_key=key)} == {chunk.chunk_id for chunk in changed}
        assert not set(chunk.chunk_id for chunk in old_chunks).intersection(reopened.collection.get()["ids"])
    assert reopened._get_store_state() == "ready"


def test_retry_after_applied_index_restores_ready(state_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, spec, session, source_root, groups = state_db
    fresh = open_store(tmp_path / "new-index-db", spec)
    chunks = [chunk for group in groups.values() for chunk in group]
    fail_ready_once(fresh, monkeypatch)
    with pytest.raises(RuntimeError, match="injected ready failure"):
        fresh.index_all(chunks, session, source_root=source_root)
    assert fresh._get_store_state() == "updating"
    reopened = open_store(fresh.persist_dir, spec)
    report = reopened.index_all(chunks, session, source_root=source_root)
    assert reopened._get_store_state() == "ready"
    assert report.total_active == len(chunks)
    assert set(reopened.collection.get()["ids"]) == {chunk.chunk_id for chunk in chunks}
    assert len(reopened.search("exposure", session)) == len(chunks)


def test_new_process_reads_persistent_state_and_recovers_same_operation(state_db, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, _, _, groups = state_db
    key, chunks = next(iter(groups.items()))
    other_key = next(candidate for candidate in groups if candidate != key)
    child_code = textwrap.dedent("""
        import json
        from pathlib import Path
        import sys
        import numpy as np
        from artagent.retrieval.embedding import EncoderSession
        from artagent.retrieval.store import open_store
        from artagent.retrieval.types import RetrievalSpec, SourceKey
        import artagent.retrieval.store as store_module

        request = json.loads(sys.stdin.read())
        spec = RetrievalSpec()
        session = EncoderSession(model=None, ref_tokenizer=None, spec=spec)
        vector = np.ones(384, dtype=np.float32) / np.sqrt(np.float32(384))
        store_module.embed_query = lambda query, encoder: vector
        store = open_store(Path(request["persist_dir"]), spec)
        key = SourceKey(**request["key"])
        other_key = SourceKey(**request["other_key"])
        initial_state = store._get_store_state()
        assert initial_state == request["expected_state"], initial_state
        if initial_state == "ready":
            assert len(store.search("exposure", session)) == request["total_count"]
        else:
            try:
                store.search("exposure", session)
            except RuntimeError:
                pass
            else:
                raise AssertionError("updating 상태 검색을 거부하지 않았습니다.")
            report = store.exclude_source(key)
            assert report.excluded == request["target_count"], report
            assert report.total_active == request["total_count"] - request["target_count"], report
            assert store._get_store_state() == "ready"
            assert store.search("exposure", session, source_key=key) == []
            other_hits = store.search("exposure", session, source_key=other_key)
            assert {hit.chunk_id for hit in other_hits} == set(request["other_ids"])
        assert store.collection.count() == request["total_count"]
        print(json.dumps({"initial_state": initial_state, "final_state": store._get_store_state()}))
    """)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    request = {
        "persist_dir": str(store.persist_dir),
        "key": {"source_type": key.source_type, "source_group_id": key.source_group_id},
        "other_key": {"source_type": other_key.source_type, "source_group_id": other_key.source_group_id},
        "other_ids": [chunk.chunk_id for chunk in groups[other_key]],
        "total_count": store.collection.count(),
        "target_count": len(chunks),
    }

    def run_child(expected_state: str) -> dict:
        payload = {**request, "expected_state": expected_state}
        result = subprocess.run(
            [sys.executable, "-c", child_code],
            input=json.dumps(payload), text=True, capture_output=True,
            env=environment, timeout=60,
        )
        assert result.returncode == 0, (
            f"subprocess returncode={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return json.loads(result.stdout)

    assert run_child("ready") == {"initial_state": "ready", "final_state": "ready"}
    fail_ready_once(store, monkeypatch)
    with pytest.raises(RuntimeError, match="injected ready failure"):
        store.exclude_source(key)
    assert store._get_store_state() == "updating"
    assert run_child("updating") == {"initial_state": "updating", "final_state": "ready"}


@pytest.mark.parametrize("pending", ["replace_source", "exclude_source"])
@pytest.mark.parametrize("next_operation", ["other_group_replace", "other_group_exclude", "different_input", "different_operation", "index_all"])
def test_pending_mutation_rejects_unrelated_work(state_db, monkeypatch: pytest.MonkeyPatch, pending: str, next_operation: str) -> None:
    store, spec, session, source_root, groups = state_db
    key, chunks = next(iter(groups.items()))
    other_key = next(candidate for candidate in groups if candidate != key)
    if pending == "replace_source":
        chunks = snapshot_chunks(
            source_root, key.source_type, key.source_group_id,
            ["Pending correction instructions.", "Pending white balance instructions."],
        )
        groups[key] = chunks
    fail_ready_once(store, monkeypatch)
    with pytest.raises(RuntimeError, match="injected ready failure"):
        if pending == "replace_source":
            store.replace_source(key, chunks, session, source_root=source_root)
        else:
            store.exclude_source(key)
    reopened = open_store(store.persist_dir, spec)
    before_ids = set(reopened.collection.get()["ids"])
    with pytest.raises(RuntimeError):
        if next_operation == "other_group_replace":
            reopened.replace_source(other_key, groups[other_key], session, source_root=source_root)
        elif next_operation == "other_group_exclude":
            reopened.exclude_source(other_key)
        elif next_operation == "different_input":
            altered = copy.deepcopy(chunks)
            altered[0].section_title = "Different retry input"
            reopened.replace_source(key, altered, session, source_root=source_root)
        elif next_operation == "different_operation":
            if pending == "replace_source":
                reopened.exclude_source(key)
            else:
                reopened.replace_source(key, chunks, session, source_root=source_root)
        else:
            reopened.index_all([chunk for group in groups.values() for chunk in group], session, source_root=source_root)
    assert set(reopened.collection.get()["ids"]) == before_ids
    assert reopened._get_store_state() == "updating"


@pytest.mark.parametrize("failure", ["partial_upsert", "partial_delete"])
def test_partial_replace_retry_finishes_cleanup(state_db, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    store, spec, session, source_root, groups = state_db
    key, old_chunks = next(iter(groups.items()))
    other_ids = {chunk.chunk_id for candidate, chunks in groups.items() if candidate != key for chunk in chunks}
    new_chunks = snapshot_chunks(source_root, key.source_type, key.source_group_id, ["New exposure adjustment.", "New white balance adjustment."])
    method_name = "upsert" if failure == "partial_upsert" else "delete"
    original = getattr(type(store.collection), method_name)

    def partial_then_fail(collection, **kwargs):
        partial = {name: value[:1] for name, value in kwargs.items()}
        original(collection, **partial)
        raise RuntimeError(f"injected {failure}")

    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(type(store.collection), method_name, partial_then_fail)
        with pytest.raises(RuntimeError, match=f"injected {failure}"):
            store.replace_source(key, new_chunks, session, source_root=source_root)
    assert store._get_store_state() == "updating"
    reopened = open_store(store.persist_dir, spec)
    reopened.replace_source(key, new_chunks, session, source_root=source_root)
    assert reopened._get_store_state() == "ready"
    assert set(reopened.collection.get()["ids"]) == other_ids | {chunk.chunk_id for chunk in new_chunks}
    assert not set(chunk.chunk_id for chunk in old_chunks).intersection(reopened.collection.get()["ids"])
    hits = reopened.search("exposure", session, source_key=key)
    assert {hit.chunk_id for hit in hits} == {chunk.chunk_id for chunk in new_chunks}


def test_partial_exclude_retry_finishes_all_rows(state_db, monkeypatch: pytest.MonkeyPatch) -> None:
    store, spec, session, _, groups = state_db
    key, chunks = next(iter(groups.items()))
    original = type(store.collection).update

    def partial_then_fail(collection, **kwargs):
        partial = {name: value[:1] for name, value in kwargs.items()}
        original(collection, **partial)
        raise RuntimeError("injected partial exclude")

    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(type(store.collection), "update", partial_then_fail)
        with pytest.raises(RuntimeError, match="injected partial exclude"):
            store.exclude_source(key)
    applied = store.collection.get(ids=[chunk.chunk_id for chunk in chunks], include=["metadatas"])
    assert sum(metadata["excluded"] for metadata in applied["metadatas"]) == 1
    assert store._get_store_state() == "updating"
    reopened = open_store(store.persist_dir, spec)
    report = reopened.exclude_source(key)
    assert reopened._get_store_state() == "ready"
    assert report.excluded == len(chunks)
    assert report.total_active == store.collection.count() - len(chunks)
    assert reopened.search("exposure", session, source_key=key) == []
    other_key = next(candidate for candidate in groups if candidate != key)
    assert {hit.chunk_id for hit in reopened.search("exposure", session, source_key=other_key)} == {chunk.chunk_id for chunk in groups[other_key]}


def test_preopened_handle_observes_updating_state(state_db) -> None:
    store, spec, session, _, _ = state_db
    preopened = open_store(store.persist_dir, spec)
    store._set_store_state("updating")
    with pytest.raises(RuntimeError, match="저장소가 준비되지 않았습니다"):
        preopened.search("exposure", session)


def test_handles_share_lock_for_resolved_database_path(state_db) -> None:
    store, spec, _, _, _ = state_db
    other = open_store(store.persist_dir / ".", spec)
    acquired = []

    def try_other_lock():
        success = other._lock.acquire(blocking=False)
        acquired.append(success)
        if success:
            other._lock.release()

    with store._lock:
        thread = threading.Thread(target=try_other_lock)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert acquired == [False]
