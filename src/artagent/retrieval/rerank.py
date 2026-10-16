"""Reranking and top-k selection for retrieval candidates (Task 15 / A-15).

Provides cross-encoder and lexical BM25 rerankers, window-level scoring
with max_window_v1 aggregation, and top-k/min_score candidate selection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Optional, Sequence

import numpy as np

from .types import SearchHit


@dataclass(frozen=True)
class RerankRecord:
    """단일 청크 후보에 대한 리랭킹 및 최종 순위 기록."""

    hit: SearchHit
    dense_rank: int
    rerank_rank: int
    final_rank: Optional[int]
    raw_score: float
    selection_score: float
    window_count: int
    excluded_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.hit.chunk_id,
            "doc_id": self.hit.doc_id,
            "dense_rank": self.dense_rank,
            "rerank_rank": self.rerank_rank,
            "final_rank": self.final_rank,
            "raw_score": self.raw_score,
            "selection_score": self.selection_score,
            "window_count": self.window_count,
            "excluded_reason": self.excluded_reason,
            "distance": self.hit.distance,
        }


@dataclass(frozen=True)
class RerankResult:
    """리랭킹 및 최종 선택 결과."""

    selected_hits: list[SearchHit]
    records: list[RerankRecord]
    reranker_id: str
    top_k: int
    min_score: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reranker_id": self.reranker_id,
            "top_k": self.top_k,
            "min_score": self.min_score,
            "selected_chunk_ids": [h.chunk_id for h in self.selected_hits],
            "records": [r.to_dict() for r in self.records],
        }


class CrossEncoderReranker:
    """Cross-Encoder 기반 질의-문서 쌍 리랭커.

    R1 (cross-encoder/mmarco-mMiniLMv2-L12-H384-v1) 및
    R2 (cross-encoder/ms-marco-MiniLM-L6-v2)를 지원하며,
    T9 청크의 전 세그먼트를 순회하는 채점용 윈도우 분할과
    max_window_v1 점수 집계를 수행한다.
    """

    def __init__(
        self,
        model_name_or_path: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        *,
        device: str = "cpu",
        max_length: Optional[int] = None,
        overlap_tokens: int = 64,
        max_header_tokens: int = 32,
    ) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name_or_path
        self.device = device
        self.model = CrossEncoder(model_name_or_path, device=device)
        self.tokenizer = self.model.tokenizer

        tok_max = getattr(self.tokenizer, "model_max_length", 512)
        if tok_max is None or tok_max > 512:
            tok_max = 512
        self.max_length = max_length if max_length is not None else tok_max
        self.overlap_tokens = overlap_tokens
        self.max_header_tokens = max_header_tokens

    @property
    def model_id(self) -> str:
        return self.model_name

    def score_hit(self, query: str, hit: SearchHit) -> tuple[float, float, int]:
        """(query, hit) 쌍을 평가하여 (raw_score, selection_score, window_count) 반환.

        raw_score: 최고 점수 윈도우의 원시 로짓 (logit)
        selection_score: sigmoid(raw_score) ∈ [0, 1]
        window_count: 평가된 윈도우 수
        """
        q_ids = self.tokenizer(query, add_special_tokens=False, verbose=False)["input_ids"]
        # Special tokens: [CLS] query [SEP] passage [SEP] (3 tokens)
        if len(q_ids) + 3 >= self.max_length:
            raise ValueError(
                f"질의 토큰 수({len(q_ids)})가 리랭커 토크나이저 최대 길이({self.max_length - 3})를 초과합니다."
            )

        t_ids: list[int] = []
        header_text = ""
        if hit.section_title:
            t_ids = self.tokenizer(hit.section_title, add_special_tokens=False, verbose=False)["input_ids"][
                : self.max_header_tokens
            ]
            header_text = self.tokenizer.decode(t_ids, skip_special_tokens=True).strip()

        budget = self.max_length - 3 - len(q_ids) - len(t_ids)
        if budget <= self.overlap_tokens:
            raise ValueError(
                f"질의 및 제목 길이가 너무 길어 본문 윈도우 예산이 부족합니다: budget={budget}, overlap={self.overlap_tokens}"
            )

        c_ids = self.tokenizer(hit.content, add_special_tokens=False, verbose=False)["input_ids"]

        if len(c_ids) <= budget:
            if header_text:
                windows = [f"{header_text}\n\n{hit.content}"]
            else:
                windows = [hit.content]
        else:
            step = max(1, budget - self.overlap_tokens)
            windows = []
            start = 0
            while start < len(c_ids):
                end = min(start + budget, len(c_ids))
                sub_text = self.tokenizer.decode(c_ids[start:end], skip_special_tokens=True)
                if header_text:
                    window_text = f"{header_text}\n\n{sub_text}"
                else:
                    window_text = sub_text
                windows.append(window_text)
                if end == len(c_ids):
                    break
                start += step

        pairs = [[query, w] for w in windows]
        raw_logits = np.atleast_1d(self.model.predict(pairs, apply_activation=False))

        # max_window_v1
        best_idx = int(np.argmax(raw_logits))
        best_raw = float(raw_logits[best_idx])

        if math.isnan(best_raw) or math.isinf(best_raw):
            raise ValueError(f"비유한 점수 검출: {best_raw}")

        selection_score = float(1.0 / (1.0 + math.exp(-best_raw)))
        return best_raw, selection_score, len(windows)

    def score_candidates(
        self, query: str, hits: Sequence[SearchHit]
    ) -> list[tuple[SearchHit, float]]:
        """후보 hits 목록 전체에 대해 (hit, selection_score) 목록을 반환."""
        return [(hit, self.score_hit(query, hit)[1]) for hit in hits]


class BM25Reranker:
    """고정 코퍼스 기반 어휘 BM25 재정렬기 (R3).

    GPL-3 호환의 순수 파이썬 BM25 Okapi 구현으로,
    후보 텍스트의 어휘 매칭 점수를 계산하고 s / (1 + s) 변환을 적용한다.
    """

    def __init__(
        self,
        corpus_texts: Optional[Sequence[str]] = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
        model_id: str = "lexical-bm25",
    ) -> None:
        self.k1 = k1
        self.b = b
        self._model_id = model_id
        self.doc_len: list[int] = []
        self.avgdl: float = 1.0
        self.doc_freqs: dict[str, int] = {}
        self.n_docs: int = 0

        if corpus_texts:
            self.fit(corpus_texts)

    @property
    def model_id(self) -> str:
        return self._model_id

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return [tok for tok in re.findall(r"[\w]+", text.lower()) if tok]

    def fit(self, corpus_texts: Sequence[str]) -> None:
        self.n_docs = len(corpus_texts)
        self.doc_len = []
        self.doc_freqs = Counter()

        for doc in corpus_texts:
            tokens = self.tokenize(doc)
            self.doc_len.append(len(tokens))
            unique_tokens = set(tokens)
            for t in unique_tokens:
                self.doc_freqs[t] += 1

        total_tokens = sum(self.doc_len)
        self.avgdl = (total_tokens / self.n_docs) if self.n_docs > 0 else 1.0

    def score_hit(self, query: str, hit: SearchHit) -> tuple[float, float, int]:
        """(query, hit) BM25 점수 및 s / (1 + s) selection_score 반환."""
        combined_text = (
            f"{hit.section_title}\n\n{hit.content}" if hit.section_title else hit.content
        )
        d_tokens = self.tokenize(combined_text)
        q_tokens = self.tokenize(query)

        tf_map = Counter(d_tokens)
        d_len = len(d_tokens)
        score = 0.0

        for t in q_tokens:
            if t in self.doc_freqs:
                df = self.doc_freqs[t]
                # Okapi IDF with floor at 0
                idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
                tf = tf_map.get(t, 0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self.avgdl))
                if denom > 0:
                    score += idf * (tf * (self.k1 + 1.0) / denom)

        raw_score = max(0.0, float(score))
        if math.isnan(raw_score) or math.isinf(raw_score):
            raise ValueError(f"비유한 점수 검출: {raw_score}")

        selection_score = float(raw_score / (1.0 + raw_score))
        return raw_score, selection_score, 1

    def score_candidates(
        self, query: str, hits: Sequence[SearchHit]
    ) -> list[tuple[SearchHit, float]]:
        """후보 hits 목록 전체에 대해 (hit, selection_score) 목록을 반환."""
        return [(hit, self.score_hit(query, hit)[1]) for hit in hits]


def rerank_candidates(
    search_query: str,
    hits: Sequence[SearchHit],
    reranker: Any,
    *,
    top_k: int = 5,
    min_score: Optional[float] = None,
) -> RerankResult:
    """후보 SearchHit 목록을 reranker로 재정렬하고 top_k 및 min_score 선택을 수행.

    정렬 계약: (-selection_score, dense_rank, chunk_id)
    top_k 컷 이후 min_score 필터를 적용하고 빈자리를 다른 후보로 채우지 않는다.
    SearchHit의 원래 rank, distance, content 등은 변경하지 않는다.
    """
    if top_k <= 0:
        raise ValueError(f"top_k는 양의 정수여야 합니다: {top_k}")
    if min_score is not None and not (0.0 <= min_score <= 1.0):
        raise ValueError(f"min_score는 0.0과 1.0 사이여야 합니다: {min_score}")

    if not hits:
        return RerankResult(
            selected_hits=[],
            records=[],
            reranker_id=getattr(reranker, "model_id", "unknown"),
            top_k=top_k,
            min_score=min_score,
        )

    # 1. 채점
    scored_items: list[tuple[SearchHit, int, float, float, int]] = []
    for dense_idx, hit in enumerate(hits, start=1):
        raw_score, sel_score, w_count = reranker.score_hit(search_query, hit)
        scored_items.append((hit, dense_idx, raw_score, sel_score, w_count))

    # 2. 정렬: (-selection_score, dense_rank, chunk_id)
    scored_items.sort(
        key=lambda item: (-item[3], item[1], str(item[0].chunk_id))
    )

    # 3. 컷 및 임계값 적용
    records: list[RerankRecord] = []
    selected_hits: list[SearchHit] = []
    final_counter = 1

    for rerank_idx, (hit, dense_rank, raw_score, sel_score, w_count) in enumerate(
        scored_items, start=1
    ):
        if rerank_idx <= top_k:
            if min_score is not None and sel_score < min_score:
                records.append(
                    RerankRecord(
                        hit=hit,
                        dense_rank=dense_rank,
                        rerank_rank=rerank_idx,
                        final_rank=None,
                        raw_score=raw_score,
                        selection_score=sel_score,
                        window_count=w_count,
                        excluded_reason="min_score_threshold",
                    )
                )
            else:
                records.append(
                    RerankRecord(
                        hit=hit,
                        dense_rank=dense_rank,
                        rerank_rank=rerank_idx,
                        final_rank=final_counter,
                        raw_score=raw_score,
                        selection_score=sel_score,
                        window_count=w_count,
                        excluded_reason=None,
                    )
                )
                selected_hits.append(hit)
                final_counter += 1
        else:
            records.append(
                RerankRecord(
                    hit=hit,
                    dense_rank=dense_rank,
                    rerank_rank=rerank_idx,
                    final_rank=None,
                    raw_score=raw_score,
                    selection_score=sel_score,
                    window_count=w_count,
                    excluded_reason="top_k_cut",
                )
            )

    return RerankResult(
        selected_hits=selected_hits,
        records=records,
        reranker_id=getattr(reranker, "model_id", "unknown"),
        top_k=top_k,
        min_score=min_score,
    )
