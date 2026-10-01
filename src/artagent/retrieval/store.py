from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Mapping, Optional, Sequence

import chromadb
from chromadb.api.models.Collection import Collection
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
        self._lock = threading.RLock()

    def _get_store_state(self) -> str:
        meta = self.collection.metadata or {}
        return str(meta.get("store_state", "unknown"))

    def _set_store_state(self, state: str, **extra: Any) -> None:
        current_meta = dict(self.collection.metadata or {})
        current_meta["store_state"] = state
        for k, v in extra.items():
            current_meta[k] = v
        self.collection.modify(metadata=current_meta)

    def _validate_collection_contract(self) -> None:
        """Chroma HNSW 설정 및 컬렉션 계약 전수 검증."""
        vector_config = self.collection.schema.keys["#embedding"].float_list.vector_index.config
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

            # 1. 청크 무결성 및 원문 검증
            for c in chunks:
                validate_provenance(c, source_root)

            # 2. 임베딩 계산
            vectors = embed_chunks(chunks, session)

            self._set_store_state(
                "updating",
                operation="index_all",
                total_chunks=len(chunks),
            )

            # 3. chunk_id 기준 정렬 후 배치 upsert
            triples = sorted(
                zip([c.chunk_id for c in chunks], chunks, vectors),
                key=lambda item: item[0],
            )
            sorted_ids = [t[0] for t in triples]
            sorted_chunks = [t[1] for t in triples]
            sorted_vectors = [t[2] for t in triples]

            batch_size = 500
            for offset in range(0, len(triples), batch_size):
                b_ids = sorted_ids[offset : offset + batch_size]
                b_chunks = sorted_chunks[offset : offset + batch_size]
                b_vecs = sorted_vectors[offset : offset + batch_size]

                b_docs = [c.content for c in b_chunks]
                b_metas = [serialize_metadata(c, self.spec, excluded=False) for c in b_chunks]

                self.collection.upsert(
                    ids=b_ids,
                    embeddings=[v.tolist() for v in b_vecs],
                    documents=b_docs,
                    metadatas=b_metas,
                )

            # 4. 적재 검증
            total_count = self.collection.count()
            if total_count != len(chunks):
                raise ValueError(
                    f"적재 건수 불일치: 컬렉션 건수 {total_count} != 입력 청크수 {len(chunks)}"
                )

            # 저장 내용 무결성 확인
            stored = self.collection.get(
                ids=sorted_ids,
                include=["documents", "metadatas"],
            )
            stored_id_set = set(stored["ids"])
            if stored_id_set != set(sorted_ids):
                raise ValueError("적재된 ID 집합이 입력과 일치하지 않습니다.")

            for cid, doc, meta in zip(stored["ids"], stored["documents"], stored["metadatas"]):
                deser_chunk = deserialize_chunk(cid, doc, meta)
                if sha256_str(deser_chunk.content) != deser_chunk.content_sha256:
                    raise ValueError(f"역직렬화된 청크 본문 SHA 검증 실패: {cid}")

            self._set_store_state("ready")

            return IndexReport(
                created=len(chunks),
                total_active=len(chunks),
                status="success",
            )

    def replace_source(
        self,
        key: SourceKey,
        chunks: Sequence[Chunk],
        session: EncoderSession,
        *,
        source_root: Path,
    ) -> IndexReport:
        """특정 원문 문서/후보 항목의 청크 전체를 원자적/멱등적으로 갱신."""
        with self._lock:
            self._validate_collection_contract()

            if not chunks:
                raise ValueError("빈 청크셋으로 갱신할 수 없습니다. 제외는 exclude_source를 사용하십시오.")

            for c in chunks:
                if c.source_type != key.source_type or c.doc_id != key.source_group_id:
                    raise ValueError(
                        f"청크의 그룹 식별자 불일치: ({c.source_type}, {c.doc_id}) != ({key.source_type}, {key.source_group_id})"
                    )
                validate_provenance(c, source_root)

            # 기존 저장 항목 조회
            existing = self.collection.get(
                where={
                    "$and": [
                        {"source_type": key.source_type},
                        {"source_group_id": key.source_group_id},
                    ]
                },
                include=["documents", "metadatas"],
            )
            old_ids = set(existing["ids"])
            new_ids = {c.chunk_id for c in chunks}

            # 멱등성 검사: ID 집합, content_sha256, excluded=False 여부 확인
            if old_ids == new_ids:
                all_match = True
                old_meta_by_id = {cid: m for cid, m in zip(existing["ids"], existing["metadatas"])}
                for c in chunks:
                    old_m = old_meta_by_id.get(c.chunk_id)
                    if not old_m or old_m.get("excluded") is True or old_m.get("content_sha256") != c.content_sha256:
                        all_match = False
                        break
                if all_match:
                    return IndexReport(
                        source_key=key,
                        unchanged=len(chunks),
                        total_active=self.collection.count(),
                        status="success",
                    )

            # 임베딩 계산
            vectors = embed_chunks(chunks, session)

            self._set_store_state(
                "updating",
                operation="replace_source",
                source_type=key.source_type,
                source_group_id=key.source_group_id,
            )

            # 새 청크 upsert
            triples = sorted(
                zip([c.chunk_id for c in chunks], chunks, vectors),
                key=lambda item: item[0],
            )
            u_ids = [t[0] for t in triples]
            u_docs = [t[1].content for t in triples]
            u_metas = [serialize_metadata(t[1], self.spec, excluded=False) for t in triples]
            u_vecs = [t[2].tolist() for t in triples]

            self.collection.upsert(
                ids=u_ids,
                embeddings=u_vecs,
                documents=u_docs,
                metadatas=u_metas,
            )

            # 기존 ID 중 새 청크셋에 없는 오래된 ID 삭제
            to_delete = list(old_ids - new_ids)
            if to_delete:
                self.collection.delete(ids=to_delete)

            self._set_store_state("ready")

            return IndexReport(
                source_key=key,
                created=len(new_ids - old_ids),
                updated=len(new_ids & old_ids),
                deleted=len(to_delete),
                total_active=self.collection.count(),
                status="success",
            )

    def exclude_source(self, key: SourceKey) -> IndexReport:
        """특정 원문 문서/후보 항목의 청크 전체를 검색 제외 처리 (excluded=True)."""
        with self._lock:
            self._validate_collection_contract()

            existing = self.collection.get(
                where={
                    "$and": [
                        {"source_type": key.source_type},
                        {"source_group_id": key.source_group_id},
                    ]
                },
                include=["documents", "metadatas"],
            )
            target_ids = existing["ids"]
            if not target_ids:
                return IndexReport(
                    source_key=key,
                    excluded=0,
                    total_active=self.collection.count(),
                    status="success",
                )

            # 이미 모두 제외되었는지 확인
            all_excluded = all(m.get("excluded") is True for m in existing["metadatas"])
            if all_excluded:
                return IndexReport(
                    source_key=key,
                    excluded=len(target_ids),
                    unchanged=len(target_ids),
                    total_active=self.collection.count(),
                    status="success",
                )

            self._set_store_state(
                "updating",
                operation="exclude_source",
                source_type=key.source_type,
                source_group_id=key.source_group_id,
            )

            updated_metas = []
            for m in existing["metadatas"]:
                new_m = dict(m)
                new_m["excluded"] = True
                updated_metas.append(new_m)

            self.collection.update(
                ids=target_ids,
                metadatas=updated_metas,
            )

            self._set_store_state("ready")

            return IndexReport(
                source_key=key,
                excluded=len(target_ids),
                total_active=self.collection.count(),
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
            if self._get_store_state() != "ready":
                raise RuntimeError(
                    f"저장소가 준비되지 않았습니다. 현재 상태: {self._get_store_state()}"
                )
            self._validate_collection_contract()

            q_vec = embed_query(query, session)

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
                limit=1000,
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
                segments = json.loads(str(meta["source_segments_json"]))
                orig_meta = json.loads(str(meta["original_metadata_json"]))

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
                        source_segments=segments,
                        original_metadata=orig_meta,
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

    initial_metadata = {
        "retrieval_schema_version": spec.retrieval_schema_version,
        "model_id": spec.model_id,
        "model_revision": spec.model_revision,
        "dimension": spec.dimension,
        "dtype": spec.dtype,
        "normalize_embeddings": spec.normalize_embeddings,
        "rawpedia_rule": spec.rawpedia_rule,
        "github_rule": spec.github_rule,
        "guard_group": spec.guard_group,
        "physical_embedding_policy": spec.physical_embedding_policy,
        "ref_tokenizer_revision": spec.ref_tokenizer_revision,
        "doc_prefix": spec.doc_prefix,
        "query_prefix": spec.query_prefix,
        "reference_sha256": spec.reference_sha256,
        "protocol_sha256": spec.protocol_sha256,
        "store_state": "ready",
    }

    try:
        col = client.get_collection(spec.collection_name)
    except Exception:
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
