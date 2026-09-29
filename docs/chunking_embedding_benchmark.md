# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-29T08:16:24.388012+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 대형 청크 확장 단계: Stage N (3402개) + Stage P (2100개), 판정: 실행 (Triggered)
- 총 실험 조합: 5502개 (정식 4716개 + 진단 786개, 100% 완료)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `sentence-transformers/all-MiniLM-L6-v2` | Revision: `1110a243fdf4...`, Dim: 384 |
| **RawPedia 청킹 규칙** | `R-B-window-t8192-o0` | $L/O$ 파라미터 최적 조합 |
| **GitHub 청킹 규칙** | `G-A-curated-thread-w224-wo0` | 정제된 스레드/유닛 최적 조합 |
| **주요 검색 품질** | **Macro MRR@5: 0.8035** | Macro Hit@5: 0.9104 |
| **검색 속도 (p95)** | **7.9 ms** | 100개 쿼리 단일 검색 지연 |
| **선정 근거** | Highest retrieval precision under Korean-to-English evaluation with optimal latency/storage tradeoff. |

## 2. 기존 기준선 대비 증감 비교

| 지표 | 이전 최적 기준선 (`grid_128_224`) | 대형 청크 확장 최적 스택 (`large_grid`) | 증감 (Delta) |
|---|---|---|---|
| **임베딩 모델** | `intfloat/multilingual-e5-small` | `sentence-transformers/all-MiniLM-L6-v2` | 동일 모델 유지/비교 |
| **RawPedia 규칙** | `R-B-window-t224-o0` | `R-B-window-t8192-o0` | 청크 크기/오버랩 확장 비교 |
| **GitHub 규칙** | `G-A-curated-thread-w224-wo0` | `G-A-curated-thread-w224-wo0` | 스레드 윈도우 확장 비교 |
| **Macro MRR@5** | 0.7730 | **0.8035** | **+0.0305** |
| **Macro Hit@5** | 0.8667 | **0.9104** | **+0.0437** |

## 3. 대형 청크 확장 파라미터 탐색 분석

- **경계 판정 (Boundary Status)**: `upper_boundary` (청크 크기가 탐색 그리드의 실제 탐색 상한선(8192 토큰)에 위치하며 상한선에서 최적 성능 달성.)

선정 모델(`sentence-transformers/all-MiniLM-L6-v2`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \times O$ 그리드별 검색 품질(Macro MRR@5) 변화:

| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ | $O = 32$ | $O = 64$ | $O = 128$ |
|---|---|---|---|---|
| **$L = 128$** | 0.5381 | 0.5352 | 0.5496 | N/A |
| **$L = 192$** | 0.5693 | 0.5702 | 0.5538 | N/A |
| **$L = 224$** | 0.5791 | 0.5879 | 0.5629 | 0.5642 |
| **$L = 256$** | N/A | N/A | N/A | N/A |
| **$L = 320$** | N/A | N/A | N/A | N/A |
| **$L = 384$** | N/A | N/A | N/A | N/A |
| **$L = 448$** | 0.6509 | N/A | 0.6471 | 0.6412 |
| **$L = 464$** | N/A | N/A | N/A | N/A |
| **$L = 480$** | N/A | N/A | N/A | N/A |
| **$L = 496$** | N/A | N/A | N/A | N/A |
| **$L = 512$** | 0.5788 | N/A | 0.6645 | 0.6393 |
| **$L = 768$** | 0.6946 | N/A | 0.6799 | 0.6684 |
| **$L = 1024$** | 0.6868 | N/A | 0.6858 | 0.6946 |
| **$L = 1536$** | 0.7352 | N/A | 0.7248 | 0.7097 |
| **$L = 2048$** | 0.7387 | N/A | 0.7172 | 0.7187 |
| **$L = 4096$** | 0.7708 | N/A | 0.7691 | 0.7671 |
| **$L = 6144$** | 0.7953 | N/A | 0.7958 | 0.7964 |
| **$L = 8192$** | 0.8035 | N/A | 0.8079 | 0.8095 |

## 4. 문맥 예산 ($B=2048, 4096$) 하의 검색 지표 요약

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro MRR@5 | B=2048 Hit@5 | B=2048 FullEv@5 | B=4096 Hit@5 | B=4096 FullEv@5 |
|---|---|---|---|---|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-A-curated-thread-w224-wo0` | **0.8095** | 0.6959 | 0.6959 | 0.7896 | 0.7896 |
| 2 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w384-wo0` | **0.8085** | 0.8791 | 0.8229 | 0.8791 | 0.8229 |
| 3 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w448-wo0` | **0.8085** | 0.8791 | 0.8229 | 0.8791 | 0.8229 |
| 4 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-A-curated-thread-w224-wo0` | **0.8079** | 0.6959 | 0.6959 | 0.7958 | 0.7958 |
| 5 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w256-wo0` | **0.8054** | 0.8791 | 0.8229 | 0.8791 | 0.8229 |
| 6 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w320-wo0` | **0.8054** | 0.8791 | 0.8229 | 0.8791 | 0.8229 |
| 7 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o0` | `G-A-curated-thread-w224-wo0` | **0.8035** | 0.6959 | 0.6959 | 0.7896 | 0.7896 |
| 8 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w224-wo0` | **0.8003** | 0.8791 | 0.8292 | 0.8854 | 0.8354 |
| 9 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w384-wo0` | **0.8003** | 0.8791 | 0.8292 | 0.8854 | 0.8354 |
| 10 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w448-wo0` | **0.8003** | 0.8791 | 0.8292 | 0.8854 | 0.8354 |
| 11 | `multilingual-e5-small` | `R-B-window-t480-o0` | `G-A-curated-thread-w224-wo0` | **0.8001** | 0.8604 | 0.8229 | 0.8667 | 0.8354 |
| 12 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w256-wo0` | **0.7993** | 0.8791 | 0.8292 | 0.8854 | 0.8354 |
| 13 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w320-wo0` | **0.7993** | 0.8791 | 0.8292 | 0.8854 | 0.8354 |
| 14 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w384-wo0` | **0.7978** | 0.8979 | 0.8166 | 0.8979 | 0.8166 |
| 15 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w448-wo0` | **0.7978** | 0.8979 | 0.8166 | 0.8979 | 0.8166 |

## 5. 상위 정식 실험 조합 비교표 (Top 25 Combinations)

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-A-curated-thread-w224-wo0` | 0.7729 | 0.9042 | **0.8095** | 0.8283 | 8.1ms | 1.0000 |
| 2 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w384-wo0` | 0.7604 | 0.8791 | **0.8085** | 0.7232 | 15.0ms | 0.9980 |
| 3 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w448-wo0` | 0.7604 | 0.8791 | **0.8085** | 0.7232 | 16.1ms | 1.0000 |
| 4 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-A-curated-thread-w224-wo0` | 0.7667 | 0.9104 | **0.8079** | 0.8256 | 8.0ms | 1.0000 |
| 5 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w256-wo0` | 0.7541 | 0.8791 | **0.8054** | 0.7179 | 15.8ms | 1.0000 |
| 6 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w320-wo0` | 0.7541 | 0.8791 | **0.8054** | 0.7179 | 27.0ms | 1.0000 |
| 7 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o0` | `G-A-curated-thread-w224-wo0` | 0.7604 | 0.9104 | **0.8035** | 0.8181 | 7.9ms | 1.0000 |
| 8 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w224-wo0` | 0.7459 | 0.8854 | **0.8003** | 0.7321 | 16.5ms | 1.0000 |
| 9 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w384-wo0` | 0.7459 | 0.8854 | **0.8003** | 0.7321 | 15.1ms | 1.0000 |
| 10 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w448-wo0` | 0.7459 | 0.8854 | **0.8003** | 0.7321 | 17.8ms | 1.0000 |
| 11 | `multilingual-e5-small` | `R-B-window-t480-o0` | `G-A-curated-thread-w224-wo0` | 0.7521 | 0.8667 | **0.8001** | 0.7317 | 16.3ms | 1.0000 |
| 12 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w256-wo0` | 0.7459 | 0.8854 | **0.7993** | 0.7303 | 18.1ms | 1.0000 |
| 13 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w320-wo0` | 0.7459 | 0.8854 | **0.7993** | 0.7303 | 15.8ms | 1.0000 |
| 14 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w384-wo0` | 0.7291 | 0.8979 | **0.7978** | 0.7051 | 20.4ms | 0.9960 |
| 15 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w448-wo0` | 0.7291 | 0.8979 | **0.7978** | 0.7051 | 21.6ms | 1.0000 |
| 16 | `multilingual-e5-small` | `R-B-window-t320-o0` | `G-A-curated-thread-w320-wo0` | 0.7271 | 0.8979 | **0.7978** | 0.7279 | 14.8ms | 0.9980 |
| 17 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w320-wo0` | 0.7291 | 0.8979 | **0.7973** | 0.7042 | 25.1ms | 1.0000 |
| 18 | `all-MiniLM-L6-v2` | `R-B-window-t6144-o128` | `G-A-curated-thread-w224-wo0` | 0.7396 | 0.9104 | **0.7964** | 0.8288 | 7.6ms | 1.0000 |
| 19 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w256-wo0` | 0.7291 | 0.8979 | **0.7963** | 0.7025 | 26.0ms | 1.0000 |
| 20 | `all-MiniLM-L6-v2` | `R-B-window-t6144-o64` | `G-A-curated-thread-w224-wo0` | 0.7396 | 0.9104 | **0.7958** | 0.8279 | 7.7ms | 1.0000 |
| 21 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w192-wo0` | 0.7479 | 0.8667 | **0.7957** | 0.7016 | 12.9ms | 1.0000 |
| 22 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w256-wo0` | 0.7479 | 0.8667 | **0.7957** | 0.7016 | 15.3ms | 1.0000 |
| 23 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w320-wo0` | 0.7479 | 0.8667 | **0.7957** | 0.7016 | 16.3ms | 1.0000 |
| 24 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w384-wo0` | 0.7479 | 0.8667 | **0.7957** | 0.7016 | 15.4ms | 1.0000 |
| 25 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w448-wo0` | 0.7479 | 0.8667 | **0.7957** | 0.7016 | 23.9ms | 1.0000 |

## 6. 결론 및 T9 인계 명세

1. **최종 선정 스택**:
   - **임베딩 모델**: `sentence-transformers/all-MiniLM-L6-v2` (commit revision: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`)
   - **차원 및 Prefix**: 384 차원 / Query: `` / Document: ``
   - **RawPedia 청크 파일**: `data/chunks/t08-2-remeasurement/pooled-common-256/rawpedia/R-B-window-t8192-o0.jsonl`
   - **GitHub 청크 파일**: `data/chunks/t08-2-remeasurement/pooled-common-256/github/G-A-curated-thread-w224-wo0.jsonl`
   - **Chroma 설정**: cosine 거리, HNSW ef_construction=200, ef_search=200

2. **인계 주의 사항**:
   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(``)를 부가하여 384차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.
   - GitHub 스레드 청크는 `thread_window_mean_v3` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.

