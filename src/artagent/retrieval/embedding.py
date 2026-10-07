from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable, Optional, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer
import torch
from transformers import AutoTokenizer

from .provenance import Chunk, sha256_str
from .types import RetrievalSpec


@dataclass
class EncoderSession:
    """임베딩 인코더 및 토크나이저 세션."""

    model: SentenceTransformer
    ref_tokenizer: Any
    spec: RetrievalSpec


def load_encoder(spec: RetrievalSpec) -> EncoderSession:
    """고정 모델 및 기준 토크나이저를 로드하고 세션을 구성."""
    torch.set_num_threads(4)

    encoder = SentenceTransformer(
        spec.model_id,
        revision=spec.model_revision,
        device="cpu",
    )
    encoder.max_seq_length = spec.max_seq_length

    ref_tokenizer = AutoTokenizer.from_pretrained(
        spec.ref_tokenizer_id,
        revision=spec.ref_tokenizer_revision,
    )

    return EncoderSession(
        model=encoder,
        ref_tokenizer=ref_tokenizer,
        spec=spec,
    )


def embed_chunks(
    chunks: Sequence[Chunk],
    session: EncoderSession,
    *,
    batch_size: int = 16,
    trace_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> np.ndarray:
    """chunk_window_mean_v2 정책에 따라 물리 청크 목록을 임베딩.

    출력: (len(chunks), 384) float32 L2 정규화 배열
    """
    if not chunks:
        return np.zeros((0, session.spec.dimension), dtype=np.float32)

    encoder = session.model
    ref_tokenizer = session.ref_tokenizer
    spec = session.spec
    max_len = spec.max_seq_length
    w_val = spec.encoder_window_tokens
    doc_prefix = spec.doc_prefix

    vectors = np.zeros((len(chunks), spec.dimension), dtype=np.float32)

    for idx, c in enumerate(chunks):
        if not c.content or not c.content.strip():
            raise ValueError(f"빈 본문 청크 거부: {c.chunk_id}")

        # 1. 헤더 생성 (기준 토크나이저로 최대 32토큰 제한)
        p_title = c.metadata.get("page_title") or c.metadata.get("title", "")
        s_title = c.section_title
        if p_title and s_title and p_title != s_title:
            header = f"{p_title}\n{s_title}"
        else:
            header = s_title or p_title or ""

        if header and ref_tokenizer is not None:
            enc_h = ref_tokenizer(header, return_offsets_mapping=True, add_special_tokens=False)
            offsets_h = enc_h["offset_mapping"]
            if len(offsets_h) > spec.max_header_tokens:
                header = header[: offsets_h[spec.max_header_tokens - 1][1]].strip()

        # 2. 본문 224토큰 윈도우 분할 (overlap 0)
        enc = ref_tokenizer(c.content, return_offsets_mapping=True, add_special_tokens=False)
        offsets = enc["offset_mapping"]
        n_tok = len(offsets)

        window_texts: list[tuple[str, str, int]] = []
        if n_tok == 0:
            txt = f"{header}\n{c.content}".strip() if header else c.content
            window_texts.append((f"{doc_prefix}{txt}", c.content, 1))
        elif n_tok <= w_val:
            txt = f"{header}\n{c.content}".strip() if header else c.content
            window_texts.append((f"{doc_prefix}{txt}", c.content, n_tok))
        else:
            for i in range(0, n_tok, w_val):
                sub_offsets = offsets[i : i + w_val]
                sub_st = sub_offsets[0][0]
                sub_ed = sub_offsets[-1][1]
                sub_txt = c.content[sub_st:sub_ed]
                if sub_txt.strip():
                    txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                    window_texts.append((f"{doc_prefix}{txt}", sub_txt, len(sub_offsets)))

        if not window_texts:
            txt = f"{header}\n{c.content}".strip() if header else c.content
            window_texts.append((f"{doc_prefix}{txt}", c.content, 1))

        # 3. 길이 guard (pooled-common-256): 모델 토크나이저 입력 256 이하 검사 및 sub-splitting
        final_window_texts: list[str] = []
        final_window_weights: list[int] = []

        for w_t, body_slice, w_w in window_texts:
            tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
            if tok_len <= max_len:
                final_window_texts.append(w_t)
                final_window_weights.append(w_w)
            else:
                core_enc = ref_tokenizer(body_slice, return_offsets_mapping=True, add_special_tokens=False)
                core_offsets = core_enc["offset_mapping"]
                header_txt = f"{doc_prefix}{header}\n" if header else f"{doc_prefix}"
                header_tok_len = len(encoder.tokenizer.encode(header_txt, add_special_tokens=True))
                avail_tokens = max(16, max_len - header_tok_len - 5)
                sub_step = min(max(50, w_val // 2), avail_tokens)
                st = 0
                while st < len(core_offsets):
                    step = sub_step
                    while step > 1:
                        so = core_offsets[st : st + step]
                        sub_txt = body_slice[so[0][0] : so[-1][1]]
                        txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                        cand_w_t = f"{doc_prefix}{txt}"
                        if len(encoder.tokenizer.encode(cand_w_t, add_special_tokens=True)) <= max_len:
                            break
                        step = max(1, step // 2)
                    so = core_offsets[st : st + step]
                    sub_txt = body_slice[so[0][0] : so[-1][1]]
                    if sub_txt.strip():
                        txt = f"{header}\n{sub_txt}".strip() if header else sub_txt
                        final_window_texts.append(f"{doc_prefix}{txt}")
                        final_window_weights.append(len(so))
                    st += step

        for w_t in final_window_texts:
            tok_len = len(encoder.tokenizer.encode(w_t, add_special_tokens=True))
            if tok_len > max_len:
                raise ValueError(
                    f"윈도우 길이가 모델 허용치({max_len})를 초과함: {tok_len} in {c.chunk_id}"
                )

        if trace_callback is not None:
            trace_callback({
                "chunk_id": c.chunk_id,
                "policy": spec.physical_embedding_policy,
                "source_segments": c.metadata.get("source_segments", []),
                "windows": [
                    {
                        "input": text,
                        "input_sha256": sha256_str(text),
                        "input_tokens": len(encoder.tokenizer.encode(text, add_special_tokens=True)),
                        "body_token_weight": int(weight),
                        "header_token_weight": 0,
                    }
                    for text, weight in zip(final_window_texts, final_window_weights)
                ],
            })

        # 4. 윈도우 인코딩 및 가중 평균
        win_vecs = encoder.encode(
            final_window_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        weights_arr = np.array(final_window_weights, dtype=np.float32)[:, None]
        weighted_mean = (win_vecs * weights_arr).sum(axis=0) / weights_arr.sum()
        norm = np.linalg.norm(weighted_mean)
        if norm > 1e-6:
            weighted_mean /= norm

        if np.isnan(weighted_mean).any() or np.isinf(weighted_mean).any():
            raise ValueError(f"NaN/Inf 벡터 발생: {c.chunk_id}")

        vectors[idx] = weighted_mean.astype(np.float32)

    # 5. 전수 무결성 및 정규화 검증
    if vectors.dtype != np.float32:
        vectors = vectors.astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1)
    if not np.all(np.abs(norms - 1.0) <= 1e-5):
        raise ValueError("L2 정규화 검증 실패")

    return vectors


def embed_query(query: str, session: EncoderSession) -> np.ndarray:
    """단일 질문 문자열 임베딩.

    출력: (384,) float32 L2 정규화 배열
    """
    if not query or not query.strip():
        raise ValueError("빈 검색어는 거부됩니다.")

    encoder = session.model
    spec = session.spec

    tok_len = len(encoder.tokenizer.encode(query, add_special_tokens=True))
    if tok_len > spec.max_seq_length:
        raise ValueError(
            f"검색어 길이({tok_len} 토큰)가 최대 허용치({spec.max_seq_length} 토큰)를 초과합니다."
        )

    # query_prefix=""
    cand_query = f"{spec.query_prefix}{query}" if spec.query_prefix else query
    vec = encoder.encode(
        [cand_query],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )[0]

    if vec.dtype != np.float32:
        vec = vec.astype(np.float32)

    if np.isnan(vec).any() or np.isinf(vec).any():
        raise ValueError("검색어 벡터에 NaN 또는 Inf가 포함되어 있습니다.")

    norm = np.linalg.norm(vec)
    if abs(norm - 1.0) > 1e-5:
        raise ValueError(f"검색어 벡터 정규화 실패: norm={norm}")

    return vec
