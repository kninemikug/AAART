"""Reranking and top-k selection for retrieval candidates (Task 15 / A-15).

Provides cross-encoder and lexical BM25 rerankers, window-level scoring
with max_window_v1 aggregation, and top-k/min_score candidate selection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
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
    windows: list[dict[str, Any]] = field(default_factory=list)
    ranking_score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.hit.chunk_id,
            "doc_id": self.hit.doc_id,
            "dense_rank": self.dense_rank,
            "rerank_rank": self.rerank_rank,
            "final_rank": self.final_rank,
            "raw_score": self.raw_score,
            "selection_score": self.selection_score,
            "ranking_score": self.ranking_score,
            "window_count": self.window_count,
            "excluded_reason": self.excluded_reason,
            "distance": self.hit.distance,
            "windows": self.windows,
        }


@dataclass(frozen=True)
class RerankResult:
    """리랭킹 및 최종 선택 결과."""

    selected_hits: list[SearchHit]
    records: list[RerankRecord]
    reranker_id: str
    top_k: int
    min_score: Optional[float]
    rerank_weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reranker_id": self.reranker_id,
            "top_k": self.top_k,
            "min_score": self.min_score,
            "rerank_weight": self.rerank_weight,
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
        revision: Optional[str] = None,
        local_files_only: bool = False,
    ) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name_or_path
        self.device = device
        self.model = CrossEncoder(
            model_name_or_path, device=device, revision=revision,
            local_files_only=local_files_only,
        )
        self.tokenizer = self.model.tokenizer

        tok_max = getattr(self.tokenizer, "model_max_length", 512)
        if tok_max is None or tok_max > 512:
            tok_max = 512
        self.max_length = max_length if max_length is not None else tok_max
        if type(self.max_length) is not int or not 0 < self.max_length <= tok_max:
            raise ValueError("max_length는 모델 한도 이하의 양의 정수여야 합니다.")
        if type(overlap_tokens) is not int or overlap_tokens < 0:
            raise ValueError("overlap_tokens는 음이 아닌 정수여야 합니다.")
        self.model.max_length = self.max_length
        self.overlap_tokens = overlap_tokens
        self.max_header_tokens = max_header_tokens
        self.last_windows: list[dict[str, Any]] = []

    @property
    def model_id(self) -> str:
        return self.model_name

    def score_hit(self, query: str, hit: SearchHit) -> tuple[float, float, int]:
        """(query, hit) 쌍을 평가하여 (raw_score, selection_score, window_count) 반환.

        raw_score: 최고 점수 윈도우의 원시 로짓 (logit)
        selection_score: sigmoid(raw_score) ∈ [0, 1]
        window_count: 평가된 윈도우 수
        """
        self.last_windows = []
        q_ids = self.tokenizer(query, add_special_tokens=False, verbose=False)["input_ids"]
        num_special = self.tokenizer.num_special_tokens_to_add(pair=True)
        if len(q_ids) + num_special >= self.max_length:
            raise ValueError(f"질의 토큰 수({len(q_ids)})가 최대 길이를 초과합니다.")

        title = hit.section_title
        if title:
            encoded_title = self.tokenizer(title, add_special_tokens=False,
                                           return_offsets_mapping=True, verbose=False)
            offsets = encoded_title["offset_mapping"]
            if len(offsets) > self.max_header_tokens:
                title = title[:offsets[self.max_header_tokens - 1][1]] if self.max_header_tokens else ""
        title_tokens = len(self.tokenizer(title, add_special_tokens=False, verbose=False)["input_ids"])
        budget = self.max_length - num_special - len(q_ids) - title_tokens
        if budget <= self.overlap_tokens:
            raise ValueError("질의 및 제목 길이가 너무 길어 본문 윈도우 예산이 부족합니다.")

        # 토큰을 decode하여 원문을 바꾸지 않고 실제 문자열의 좌표로 자른다.
        encoded = self.tokenizer(hit.content, add_special_tokens=False,
                                 return_offsets_mapping=True, verbose=False)
        offsets = encoded["offset_mapping"]
        pairs: list[list[str]] = []
        start = 0
        while True:
            end = min(start + budget, len(offsets))
            char_start = offsets[start][0] if start else 0
            while True:
                char_end = len(hit.content) if end == len(offsets) else offsets[end - 1][1]
                body = hit.content[char_start:char_end]
                passage = f"{title}\n\n{body}" if title else body
                pair_length = len(self.tokenizer(query, passage, add_special_tokens=True,
                                                 truncation=False, verbose=False)["input_ids"])
                if pair_length <= self.max_length:
                    break
                end -= 1
                if end <= start:
                    raise ValueError("원문을 보존하는 채점 윈도우를 만들 수 없습니다.")
            pairs.append([query, passage])
            self.last_windows.append({
                "token_start": start, "token_end": end,
                "content_char_start": char_start, "content_char_end": char_end,
                "content_byte_start": len(hit.content[:char_start].encode("utf-8")),
                "content_byte_end": len(hit.content[:char_end].encode("utf-8")),
                "pair_tokens": pair_length,
            })
            if end == len(offsets):
                break
            # 실제로 소비한 끝에서 이동해야 줄어든 마지막 부분도 다음에 채점된다.
            start = max(start + 1, end - self.overlap_tokens)

        raw_logits = np.asarray(self.model.predict(pairs, apply_activation=False)).reshape(-1)
        if len(raw_logits) != len(pairs) or not np.isfinite(raw_logits).all():
            raise ValueError("리랭커 점수 개수 또는 유한성 계약 위반")
        for window, value in zip(self.last_windows, raw_logits):
            window["raw_score"] = float(value)
        best_raw = float(np.max(raw_logits))
        if best_raw >= 0:
            selection_score = 1.0 / (1.0 + math.exp(-best_raw))
        else:
            exp_score = math.exp(best_raw)
            selection_score = exp_score / (1.0 + exp_score)
        return best_raw, selection_score, len(pairs)

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
        self.corpus_fingerprint: str = ""

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
        self.corpus_fingerprint = hashlib.sha256(
            "\n".join(corpus_texts).encode("utf-8")
        ).hexdigest()

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
        if self.n_docs == 0:
            raise ValueError("BM25Reranker가 코퍼스에 적합(fit)되지 않은 상태입니다.")
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


def fusion_score(distance: float, selection_score: float, rerank_weight: float = 1.0) -> float:
    """기존 거리 표시 정밀도의 cosine similarity와 리랭커 점수를 선형 결합한다.

    결합 점수는 정렬 전용이며 min_score는 원래 리랭커 점수에 적용한다.
    weight=1은 기존 정렬이며 원본 거리와 근거는 변경하지 않는다.
    """
    if (type(rerank_weight) not in (int, float) or not math.isfinite(rerank_weight)
            or not 0 <= rerank_weight <= 1):
        raise ValueError("rerank_weight는 0부터 1 사이의 유한한 수여야 합니다.")
    if not math.isfinite(selection_score) or not 0 <= selection_score <= 1:
        raise ValueError("리랭커 점수 계약 위반")
    if rerank_weight == 1:
        return selection_score
    if not math.isfinite(distance):
        raise ValueError("결합할 dense 거리가 유한하지 않습니다.")
    return (1 - rerank_weight) * (1 - round(distance, 6)) + rerank_weight * selection_score


def rank_scored_hits(hits: Sequence[SearchHit], scores: dict[str, float],
                     rerank_weight: float = 1.0) -> list[SearchHit]:
    """런타임과 증거 감사가 공유하는 결정적 정렬. 질문 ID나 정답을 받지 않는다."""
    fusion_score(0., 0., rerank_weight)
    return sorted(hits, key=lambda h: (-fusion_score(h.distance, scores[h.chunk_id], rerank_weight),
                                       h.rank, h.chunk_id))


def rerank_candidates(
    search_query: str,
    hits: Sequence[SearchHit],
    reranker: Any,
    *,
    top_k: int = 5,
    min_score: Optional[float] = None,
    rerank_weight: float = 1.0,
) -> RerankResult:
    """후보 SearchHit 목록을 reranker로 재정렬하고 top_k 및 min_score 선택을 수행.

    정렬 계약: (-결합 점수, dense_rank, chunk_id). 기본 가중치 1은 기존 점수 정렬.
    top_k 컷 이후 min_score 필터를 적용하고 빈자리를 다른 후보로 채우지 않는다.
    SearchHit의 원래 rank, distance, content 등은 변경하지 않는다.
    """
    fusion_score(0., 0., rerank_weight)
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
            rerank_weight=rerank_weight,
        )

    # 1. 채점
    scored_items: list[tuple[SearchHit, int, float, float, int]] = []
    windows_by_id: dict[str, list[dict[str, Any]]] = {}
    for dense_idx, hit in enumerate(hits, start=1):
        raw_score, sel_score, w_count = reranker.score_hit(search_query, hit)
        if not math.isfinite(raw_score) or not math.isfinite(sel_score) or not 0 <= sel_score <= 1:
            raise ValueError("리랭커 점수 계약 위반")
        windows_by_id[hit.chunk_id] = [dict(w) for w in getattr(reranker, "last_windows", [])]
        scored_items.append((hit, dense_idx, raw_score, sel_score, w_count))

    # 2. 정렬: (-selection_score, dense_rank, chunk_id)
    scored_items.sort(
        key=lambda item: (-fusion_score(item[0].distance, item[3], rerank_weight), item[1], str(item[0].chunk_id))
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
                        ranking_score=fusion_score(hit.distance, sel_score, rerank_weight),
                        window_count=w_count,
                        windows=windows_by_id[hit.chunk_id],
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
                        ranking_score=fusion_score(hit.distance, sel_score, rerank_weight),
                        window_count=w_count,
                        windows=windows_by_id[hit.chunk_id],
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
                    ranking_score=fusion_score(hit.distance, sel_score, rerank_weight),
                    window_count=w_count,
                    windows=windows_by_id[hit.chunk_id],
                    excluded_reason="top_k_cut",
                )
            )

    return RerankResult(
        selected_hits=selected_hits,
        records=records,
        reranker_id=getattr(reranker, "model_id", "unknown"),
        top_k=top_k,
        min_score=min_score,
        rerank_weight=rerank_weight,
    )
