from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Mapping, Optional, Sequence
from weakref import WeakValueDictionary

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.errors import NotFoundError
import numpy as np

from .embedding import EncoderSession, embed_chunks, embed_query
from .provenance import (
    Chunk,
    canonical_json_str,
    deserialize_chunk,
    serialize_metadata,
    sha256_str,
    validate_provenance,
)
from .types import IndexReport, RetrievalSpec, SearchHit, SourceKey


# 동일 프로세스의 여러 핸들이 같은 컬렉션을 동시에 갱신하지 않게 한다.
_locks: WeakValueDictionary = WeakValueDictionary()
_locks_guard = threading.Lock()


def _store_lock(persist_dir: Path, collection_name: str):
    key = (str(persist_dir.resolve()), collection_name)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


_CONTRACT_FIELDS = (
    "retrieval_schema_version", "model_id", "model_revision", "dimension",
    "dtype", "normalize_embeddings", "rawpedia_rule", "github_rule",
    "guard_group", "physical_embedding_policy", "ref_tokenizer_revision",
    "doc_prefix", "query_prefix", "reference_sha256", "protocol_sha256",
)
# 이전 저장소에 없던 필드만 당시 고정 기본값으로 해석한다.
_ADDED_CONTRACT_FIELDS = (
    "ref_tokenizer_id", "thread_embedding_policy", "encoder_window_tokens",
    "encoder_overlap_tokens", "max_header_tokens", "max_seq_length",
)
_SESSION_FIELDS = (
    "model_id", "model_revision", "ref_tokenizer_id", "ref_tokenizer_revision",
    "dimension", "dtype", "normalize_embeddings", "guard_group",
    "physical_embedding_policy", "thread_embedding_policy",
    "encoder_window_tokens", "encoder_overlap_tokens", "max_header_tokens",
    "max_seq_length", "doc_prefix", "query_prefix",
)
_OPERATION_FIELDS = (
    "operation", "input_fingerprint", "source_type", "source_group_id", "total_chunks",
)


def _contract_metadata(spec: RetrievalSpec) -> dict[str, Any]:
    return {name: getattr(spec, name) for name in _CONTRACT_FIELDS + _ADDED_CONTRACT_FIELDS}


def _source_where(key: SourceKey) -> dict[str, Any]:
    return {"$and": [
        {"source_type": key.source_type},
        {"source_group_id": key.source_group_id},
    ]}


class RetrievalStore:
    """T09 Chroma 벡터 저장소 관리 및 검색 클래스."""

    def __init__(
        self,
        client: chromadb.PersistentClient,
        collection: Collection,
        spec: RetrievalSpec,
        persist_dir: Path,
    ) -> None:
        self.client = client
        self.collection = collection
        self.spec = spec
        self.persist_dir = persist_dir
        self._lock = _store_lock(persist_dir, collection.name)

    def _current_collection(self) -> Collection:
        # Collection.metadata는 래퍼의 캐시이므로 영속 상태를 다시 읽는다.
        return self.client.get_collection(self.collection.name, embedding_function=None)

    def _get_store_state(self) -> str:
        meta = self._current_collection().metadata or {}
        return str(meta.get("store_state", "unknown"))

    def _set_store_state(self, state: str, **extra: Any) -> None:
        current_meta = dict(self._current_collection().metadata or {})
        for name in _OPERATION_FIELDS:
            current_meta.pop(name, None)
        current_meta["store_state"] = state
        for k, v in extra.items():
            current_meta[k] = v
        self.collection.modify(metadata=current_meta)

    def _validate_collection_contract(self) -> None:
        """Chroma HNSW 설정 및 컬렉션 계약 전수 검증."""
        current = self._current_collection()
        metadata = current.metadata or {}
        defaults = RetrievalSpec()
        for name, expected_value in _contract_metadata(self.spec).items():
            actual_value = metadata.get(name)
            if name in _ADDED_CONTRACT_FIELDS and name not in metadata:
                actual_value = getattr(defaults, name)
            if actual_value != expected_value:
                raise ValueError(
                    f"저장소 계약 불일치: {name} 실제 {actual_value!r} != 기대 {expected_value!r}"
                )
        vector_config = current.schema.keys["#embedding"].float_list.vector_index.config
        actual = {
            "space": vector_config.space,
            "ef_construction": vector_config.hnsw.ef_construction,
            "ef_search": vector_config.hnsw.ef_search,
            "max_neighbors": vector_config.hnsw.max_neighbors,
            "num_threads": vector_config.hnsw.num_threads,
        }
        expected = {
            "space": self.spec.space,
            "ef_construction": self.spec.hnsw_ef_construction,
            "ef_search": self.spec.hnsw_ef_search,
            "max_neighbors": self.spec.hnsw_max_neighbors,
            "num_threads": self.spec.hnsw_num_threads,
        }
        for k, v in expected.items():
            if actual[k] != v:
                raise ValueError(f"Chroma HNSW 설정 불일치: {k} 실제 {actual[k]} != 기대 {v}")

    def _validate_session(self, session: EncoderSession) -> None:
        for name in _SESSION_FIELDS:
            if getattr(session.spec, name) != getattr(self.spec, name):
                raise ValueError(f"임베딩 세션 계약 불일치: {name}")

    def _check_operation(
        self, operation: str, fingerprint: str, key: Optional[SourceKey] = None,
    ) -> bool:
        metadata = self._current_collection().metadata or {}
        state = metadata.get("store_state", "unknown")
        if state == "ready":
            return False
        same_key = (
            metadata.get("source_type", "") == (key.source_type if key else "")
            and metadata.get("source_group_id", "") == (key.source_group_id if key else "")
        )
        if (state == "updating" and metadata.get("operation") == operation
                and metadata.get("input_fingerprint") == fingerprint and same_key):
            return True
        raise RuntimeError("완료되지 않은 갱신이 있습니다. 동일 작업과 입력으로 재시도하십시오.")

    def _begin_operation(
        self, operation: str, fingerprint: str, key: Optional[SourceKey] = None,
    ) -> None:
        self._set_store_state(
            "updating", operation=operation, input_fingerprint=fingerprint,
            source_type=key.source_type if key else "",
            source_group_id=key.source_group_id if key else "",
        )

    def _input_fingerprint(self, chunks: Sequence[Chunk]) -> str:
        records = [
            {"chunk_id": chunk.chunk_id, "document": chunk.content,
             "metadata": serialize_metadata(chunk, self.spec, excluded=False)}
            for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id)
        ]
        return sha256_str(canonical_json_str(records))

    def _records_match(self, stored: Mapping[str, Any], chunks: Sequence[Chunk]) -> bool:
        if set(stored["ids"]) != {chunk.chunk_id for chunk in chunks}:
            return False
        records = {
            chunk_id: (document, metadata)
            for chunk_id, document, metadata in zip(
                stored["ids"], stored["documents"], stored["metadatas"],
            )
        }
        return all(
            records[chunk.chunk_id] == (
                chunk.content, serialize_metadata(chunk, self.spec, excluded=False),
            )
            for chunk in chunks
        )

    def _active_count(self) -> int:
        return len(self.collection.get(where={"excluded": False}, include=[])["ids"])

    def _validate_vectors(self, vectors: np.ndarray, count: int) -> None:
        if vectors.shape != (count, self.spec.dimension) or vectors.dtype != np.float32:
            raise ValueError("임베딩 형태 또는 dtype이 계약과 일치하지 않습니다.")
        if not np.isfinite(vectors).all() or not np.allclose(
            np.linalg.norm(vectors, axis=1), 1.0, rtol=0, atol=1e-5,
        ):
            raise ValueError("임베딩은 유한한 정규화 벡터여야 합니다.")

    def _upsert_chunks(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        pairs = sorted(zip(chunks, vectors), key=lambda pair: pair[0].chunk_id)
        batch_size = min(500, self.client.get_max_batch_size())
        for offset in range(0, len(pairs), batch_size):
            batch = pairs[offset:offset + batch_size]
            self.collection.upsert(
                ids=[chunk.chunk_id for chunk, _ in batch],
                embeddings=[vector.tolist() for _, vector in batch],
                documents=[chunk.content for chunk, _ in batch],
                metadatas=[serialize_metadata(chunk, self.spec, excluded=False) for chunk, _ in batch],
            )

    def _validate_chunks(self, chunks: Sequence[Chunk], source_root: Path) -> None:
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("중복 chunk_id가 포함되어 있습니다.")
        for chunk in chunks:
            validate_provenance(chunk, source_root)

    def index_all(
        self,
        chunks: Sequence[Chunk],
        session: EncoderSession,
        *,
        source_root: Path,
    ) -> IndexReport:
        """선정된 청크셋 전량(154개)을 검증 및 upsert 적재."""
        with self._lock:
            self._validate_collection_contract()
            self._validate_session(session)
            if not chunks:
                raise ValueError("빈 청크셋을 적재할 수 없습니다.")
            fingerprint = self._input_fingerprint(chunks)
            retry = self._check_operation("index_all", fingerprint)
            self._validate_chunks(chunks, source_root)
            existing = self.collection.get(include=["documents", "metadatas"])
            old_ids = set(existing["ids"])
            new_ids = {chunk.chunk_id for chunk in chunks}
            if old_ids - new_ids:
                raise ValueError("전체 적재 입력에 없는 ID가 저장소에 있습니다. 원문별 갱신을 사용하십시오.")
            if self._records_match(existing, chunks):
                if retry:
                    self._set_store_state("ready")
                return IndexReport(unchanged=len(chunks), total_active=self._active_count())

            vectors = embed_chunks(chunks, session)
            self._validate_vectors(vectors, len(chunks))
            self._begin_operation("index_all", fingerprint)
            self._upsert_chunks(chunks, vectors)
            stored = self.collection.get(include=["documents", "metadatas"])
            if not self._records_match(stored, chunks):
                raise ValueError("전체 적재 검증 실패: 저장된 ID·본문·메타데이터가 입력과 다릅니다.")
            self._set_store_state("ready")
            return IndexReport(
                created=len(new_ids - old_ids), updated=len(new_ids & old_ids),
                total_active=self._active_count(),
            )

    def replace_source(
        self,
        key: SourceKey,
        chunks: Sequence[Chunk],
        session: EncoderSession,
        *,
        source_root: Path,
    ) -> IndexReport:
        """특정 원문의 청크를 멱등적으로 갱신하고 실패 시 같은 입력으로 복구."""
        with self._lock:
            self._validate_collection_contract()
            self._validate_session(session)
            if not chunks:
                raise ValueError("빈 청크셋으로 갱신할 수 없습니다. 제외는 exclude_source를 사용하십시오.")
            fingerprint = self._input_fingerprint(chunks)
            retry = self._check_operation("replace_source", fingerprint, key)
            for c in chunks:
                if c.source_type != key.source_type or c.doc_id != key.source_group_id:
                    raise ValueError(
                        f"청크의 그룹 식별자 불일치: ({c.source_type}, {c.doc_id}) != ({key.source_type}, {key.source_group_id})"
                    )
            self._validate_chunks(chunks, source_root)
            existing = self.collection.get(
                where=_source_where(key),
                include=["documents", "metadatas"],
            )
            old_ids = set(existing["ids"])
            new_ids = {c.chunk_id for c in chunks}

            if self._records_match(existing, chunks):
                if retry:
                    self._set_store_state("ready")
                return IndexReport(
                    source_key=key, unchanged=len(chunks), total_active=self._active_count(),
                )
            vectors = embed_chunks(chunks, session)
            self._validate_vectors(vectors, len(chunks))
            self._begin_operation("replace_source", fingerprint, key)
            self._upsert_chunks(chunks, vectors)
            to_delete = sorted(old_ids - new_ids)
            if to_delete:
                self.collection.delete(ids=to_delete)
            stored = self.collection.get(
                where=_source_where(key), include=["documents", "metadatas"],
            )
            if not self._records_match(stored, chunks):
                raise ValueError("원문 갱신 검증 실패: 저장된 ID·본문·메타데이터가 입력과 다릅니다.")
            self._set_store_state("ready")

            return IndexReport(
                source_key=key,
                created=len(new_ids - old_ids),
                updated=len(new_ids & old_ids),
                deleted=len(to_delete),
                total_active=self._active_count(),
                status="success",
            )

    def exclude_source(self, key: SourceKey) -> IndexReport:
        """특정 원문 문서/후보 항목의 청크 전체를 검색 제외 처리 (excluded=True)."""
        with self._lock:
            self._validate_collection_contract()
            fingerprint = sha256_str(canonical_json_str({
                "source_type": key.source_type, "source_group_id": key.source_group_id,
            }))
            retry = self._check_operation("exclude_source", fingerprint, key)
            existing = self.collection.get(
                where=_source_where(key),
                include=["documents", "metadatas"],
            )
            target_ids = existing["ids"]
            if not target_ids:
                if retry:
                    self._set_store_state("ready")
                return IndexReport(
                    source_key=key,
                    excluded=0,
                    total_active=self._active_count(),
                    status="success",
                )

            # 이미 모두 제외되었는지 확인
            all_excluded = all(m.get("excluded") is True for m in existing["metadatas"])
            if all_excluded:
                if retry:
                    self._set_store_state("ready")
                return IndexReport(
                    source_key=key,
                    excluded=len(target_ids),
                    unchanged=len(target_ids),
                    total_active=self._active_count(),
                    status="success",
                )

            self._begin_operation("exclude_source", fingerprint, key)

            updated_metas = []
            for m in existing["metadatas"]:
                new_m = dict(m)
                new_m["excluded"] = True
                updated_metas.append(new_m)

            self.collection.update(
                ids=target_ids,
                metadatas=updated_metas,
            )
            stored = self.collection.get(where=_source_where(key), include=["metadatas"])
            if set(stored["ids"]) != set(target_ids) or not all(
                metadata.get("excluded") is True for metadata in stored["metadatas"]
            ):
                raise ValueError("원문 제외 검증 실패: 모든 대상 청크가 제외되지 않았습니다.")
            self._set_store_state("ready")

            return IndexReport(
                source_key=key,
                excluded=len(target_ids),
                total_active=self._active_count(),
                status="success",
            )

    def search(
        self,
        query: str,
        session: EncoderSession,
        *,
        source_key: Optional[SourceKey] = None,
    ) -> list[SearchHit]:
        """T09 검색 계약에 따라 query 임베딩 후 top5 SearchHit 반환."""
        with self._lock:
            state = self._get_store_state()
            if state != "ready":
                raise RuntimeError(
                    f"저장소가 준비되지 않았습니다. 현재 상태: {state}"
                )
            self._validate_collection_contract()
            self._validate_session(session)
            q_vec = embed_query(query, session)
            self._validate_vectors(q_vec.reshape(1, -1), 1)

            # where 절 구성
            if source_key is None:
                where_clause: dict[str, Any] = {"excluded": False}
            else:
                where_clause = {
                    "$and": [
                        {"excluded": False},
                        {"source_type": source_key.source_type},
                        {"source_group_id": source_key.source_group_id},
                    ]
                }

            # 검색 가능한 ID 수 확인
            searchable = self.collection.get(
                where=where_clause,
                limit=10,
                include=[],
            )
            searchable_count = len(searchable["ids"])
            if searchable_count == 0:
                return []

            n_results = min(10, searchable_count)

            res = self.collection.query(
                query_embeddings=[q_vec.tolist()],
                n_results=n_results,
                where=where_clause,
                include=["documents", "metadatas", "distances"],
            )

            if not res["ids"] or not res["ids"][0]:
                return []

            ids = res["ids"][0]
            docs = res["documents"][0]
            metas = res["metadatas"][0]
            dists = res["distances"][0]

            candidates = list(zip(ids, docs, metas, dists))

            # 정렬 계약: (round(float(distance), 6), str(chunk_id)) 오름차순
            candidates.sort(key=lambda item: (round(float(item[3]), 6), str(item[0])))

            top5 = candidates[:5]

            hits: list[SearchHit] = []
            for rank_idx, (cid, doc, meta, dist) in enumerate(top5, start=1):
                chunk = deserialize_chunk(cid, doc, meta)

                calc_sha = sha256_str(doc)
                if calc_sha != meta.get("content_sha256"):
                    raise ValueError(f"검색 결과 본문 SHA 불일치: {cid}")

                dist_float = float(dist)
                dist_str = format(dist_float, ".6f")

                hits.append(
                    SearchHit(
                        rank=rank_idx,
                        chunk_id=cid,
                        source_type=str(meta["source_type"]),
                        doc_id=str(meta["doc_id"]),
                        source_group_id=str(meta["source_group_id"]),
                        section_title=str(meta.get("section_title", "")),
                        content=doc,
                        content_sha256=str(meta["content_sha256"]),
                        source_segments=chunk.metadata.get("source_segments", []),
                        original_metadata=chunk.metadata,
                        distance=dist_float,
                        distance_text=dist_str,
                    )
                )

            return hits


def open_store(persist_dir: Path, spec: RetrievalSpec) -> RetrievalStore:
    """영속 경로에서 Chroma 클라이언트를 열고 RetrievalStore 인스턴스 반환."""
    resolved_path = Path(persist_dir).resolve()
    resolved_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(resolved_path))

    hnsw_config = {
        "space": spec.space,
        "ef_construction": spec.hnsw_ef_construction,
        "ef_search": spec.hnsw_ef_search,
        "max_neighbors": spec.hnsw_max_neighbors,
        "num_threads": spec.hnsw_num_threads,
    }

    initial_metadata = {**_contract_metadata(spec), "store_state": "ready"}
    with _store_lock(resolved_path, spec.collection_name):
        try:
            col = client.get_collection(spec.collection_name, embedding_function=None)
        except NotFoundError:
            col = client.create_collection(
                name=spec.collection_name,
                embedding_function=None,
                configuration={"hnsw": hnsw_config},
                metadata=initial_metadata,
            )
        store = RetrievalStore(
            client=client,
            collection=col,
            spec=spec,
            persist_dir=resolved_path,
        )
        store._validate_collection_contract()
    return store
