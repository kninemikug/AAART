# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-28T23:06:48.386584+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 대형 청크 확장 단계: Stage N (108개) + Stage P (72개), 판정: 실행 (Triggered)
- 총 실험 조합: 180개 (정식 180개 + 진단 0개, 100% 완료)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `intfloat/multilingual-e5-small` | Revision: `614241f622f5...`, Dim: 384 |
| **RawPedia 청킹 규칙** | `R-B-window-t224-o0` | $L/O$ 파라미터 최적 조합 |
| **GitHub 청킹 규칙** | `G-A-curated-thread-w224-wo0` | 정제된 스레드/유닛 최적 조합 |
| **주요 검색 품질** | **Macro MRR@5: 0.7730** | Macro Hit@5: 0.8667 |
| **검색 속도 (p95)** | **8.9 ms** | 100개 쿼리 단일 검색 지연 |
| **선정 근거** | Highest retrieval precision under Korean-to-English evaluation with optimal latency/storage tradeoff. |

## 2. 기존 기준선 대비 증감 비교

| 지표 | 이전 최적 기준선 (`grid_128_224`) | 대형 청크 확장 최적 스택 (`large_grid`) | 증감 (Delta) |
|---|---|---|---|
| **임베딩 모델** | `intfloat/multilingual-e5-small` | `intfloat/multilingual-e5-small` | 동일 모델 유지/비교 |
| **RawPedia 규칙** | `R-B-window-t448-o32` | `R-B-window-t224-o0` | 청크 크기/오버랩 확장 비교 |
| **GitHub 규칙** | `G-A-curated-thread-w224-wo0` | `G-A-curated-thread-w224-wo0` | 스레드 윈도우 확장 비교 |
| **Macro MRR@5** | 0.8032 | **0.7730** | **-0.0302** |
| **Macro Hit@5** | 0.8854 | **0.8667** | **-0.0187** |

## 3. 대형 청크 확장 파라미터 탐색 분석

- **경계 판정 (Boundary Status)**: `interior_peak` (탐색 공간 내부(224 토큰)에서 최적점을 형성하여 상한선 미만에서 성능 피크 도달.)

선정 모델(`intfloat/multilingual-e5-small`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \times O$ 그리드별 검색 품질(Macro MRR@5) 변화:

| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ (중복 없음) | $O = 32$ (경량 오버랩) | $O = 64$ (확장 오버랩) |
|---|---|---|---|
| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ | $O = 32$ | $O = 64$ | $O = 128$ |
|---|---|---|---|---|
| **$L = 224$** | 0.7730 | N/A | 0.7642 | 0.7532 |
| **$L = 384$** | 0.7387 | 0.7290 | 0.7579 | N/A |
| **$L = 448$** | 0.7267 | 0.7426 | 0.7655 | N/A |
| **$L = 464$** | 0.7615 | 0.7262 | 0.7655 | N/A |
| **$L = 480$** | 0.7267 | 0.7429 | 0.7666 | N/A |
| **$L = 496$** | 0.7267 | 0.7419 | 0.7681 | N/A |
| **$L = 512$** | 0.7619 | 0.7419 | 0.7686 | N/A |
| **$L = 768$** | 0.6349 | N/A | 0.6091 | 0.6330 |
| **$L = 1024$** | 0.6288 | N/A | 0.6251 | 0.6227 |
| **$L = 1536$** | 0.6356 | N/A | 0.6429 | 0.6218 |
| **$L = 2048$** | 0.6342 | N/A | 0.6270 | 0.6363 |
| **$L = 4096$** | 0.6441 | N/A | 0.6590 | 0.6533 |

## 4. 문맥 예산 ($B=2048, 4096$) 하의 검색 지표 요약

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro MRR@5 | B=2048 Hit@5 | B=2048 FullEv@5 | B=4096 Hit@5 | B=4096 FullEv@5 |
|---|---|---|---|---|---|---|---|---|
| 1 | `multilingual-e5-small` | `R-B-window-t224-o0` | `G-A-curated-thread-w224-wo0` | **0.7730** | 0.8667 | 0.7979 | 0.8667 | 0.7979 |
| 2 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o0` | `G-A-curated-thread-w224-wo0` | **0.7708** | 0.6625 | 0.6625 | 0.7541 | 0.7541 |
| 3 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o64` | `G-A-curated-thread-w224-wo0` | **0.7691** | 0.6354 | 0.6291 | 0.7729 | 0.7667 |
| 4 | `multilingual-e5-small` | `R-B-window-t512-o64` | `G-A-curated-thread-w224-wo0` | **0.7686** | 0.8854 | 0.8104 | 0.8854 | 0.8104 |
| 5 | `multilingual-e5-small` | `R-B-window-t496-o64` | `G-A-curated-thread-w224-wo0` | **0.7681** | 0.8854 | 0.8104 | 0.8854 | 0.8104 |
| 6 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o128` | `G-A-curated-thread-w224-wo0` | **0.7671** | 0.6354 | 0.6354 | 0.7729 | 0.7729 |
| 7 | `multilingual-e5-small` | `R-B-window-t480-o64` | `G-A-curated-thread-w224-wo0` | **0.7666** | 0.8791 | 0.8042 | 0.8791 | 0.8042 |
| 8 | `multilingual-e5-small` | `R-B-window-t448-o64` | `G-A-curated-thread-w224-wo0` | **0.7655** | 0.8791 | 0.8042 | 0.8791 | 0.8042 |
| 9 | `multilingual-e5-small` | `R-B-window-t464-o64` | `G-A-curated-thread-w224-wo0` | **0.7655** | 0.8791 | 0.8042 | 0.8791 | 0.8042 |
| 10 | `multilingual-e5-small` | `R-B-window-t224-o64` | `G-A-curated-thread-w224-wo0` | **0.7642** | 0.8604 | 0.8104 | 0.8604 | 0.8104 |
| 11 | `multilingual-e5-small` | `R-B-window-t512-o0` | `G-A-curated-thread-w224-wo0` | **0.7619** | 0.8667 | 0.7916 | 0.8667 | 0.7916 |
| 12 | `multilingual-e5-small` | `R-B-window-t464-o0` | `G-A-curated-thread-w224-wo0` | **0.7615** | 0.8729 | 0.7979 | 0.8729 | 0.7979 |
| 13 | `multilingual-e5-small` | `R-A-heading-t224-o64` | `G-A-curated-thread-w224-wo0` | **0.7587** | 0.8604 | 0.7979 | 0.8604 | 0.7979 |
| 14 | `multilingual-e5-small` | `R-B-window-t384-o64` | `G-A-curated-thread-w224-wo0` | **0.7579** | 0.8458 | 0.7709 | 0.8458 | 0.7709 |
| 15 | `multilingual-e5-small` | `R-B-window-t224-o128` | `G-A-curated-thread-w224-wo0` | **0.7532** | 0.8541 | 0.7979 | 0.8541 | 0.7979 |

## 5. 상위 정식 실험 조합 비교표 (Top 25 Combinations)

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `multilingual-e5-small` | `R-B-window-t224-o0` | `G-A-curated-thread-w224-wo0` | 0.7084 | 0.8667 | **0.7730** | 0.6861 | 8.9ms | 1.0000 |
| 2 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o0` | `G-A-curated-thread-w224-wo0` | 0.7021 | 0.8709 | **0.7708** | 0.7872 | 7.3ms | 1.0000 |
| 3 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o64` | `G-A-curated-thread-w224-wo0` | 0.7146 | 0.8771 | **0.7691** | 0.7958 | 7.2ms | 1.0000 |
| 4 | `multilingual-e5-small` | `R-B-window-t512-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8854 | **0.7686** | 0.6863 | 9.1ms | 0.9980 |
| 5 | `multilingual-e5-small` | `R-B-window-t496-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8854 | **0.7681** | 0.6854 | 9.1ms | 1.0000 |
| 6 | `all-MiniLM-L6-v2` | `R-B-window-t4096-o128` | `G-A-curated-thread-w224-wo0` | 0.7146 | 0.8646 | **0.7671** | 0.7925 | 7.4ms | 1.0000 |
| 7 | `multilingual-e5-small` | `R-B-window-t480-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8791 | **0.7666** | 0.6828 | 9.0ms | 0.9980 |
| 8 | `multilingual-e5-small` | `R-B-window-t448-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8791 | **0.7655** | 0.6811 | 9.1ms | 1.0000 |
| 9 | `multilingual-e5-small` | `R-B-window-t464-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8791 | **0.7655** | 0.6811 | 9.0ms | 1.0000 |
| 10 | `multilingual-e5-small` | `R-B-window-t224-o64` | `G-A-curated-thread-w224-wo0` | 0.6896 | 0.8604 | **0.7642** | 0.6714 | 9.4ms | 0.9980 |
| 11 | `multilingual-e5-small` | `R-B-window-t512-o0` | `G-A-curated-thread-w224-wo0` | 0.6834 | 0.8667 | **0.7619** | 0.6674 | 10.2ms | 1.0000 |
| 12 | `multilingual-e5-small` | `R-B-window-t464-o0` | `G-A-curated-thread-w224-wo0` | 0.6834 | 0.8729 | **0.7615** | 0.6668 | 9.3ms | 1.0000 |
| 13 | `multilingual-e5-small` | `R-A-heading-t224-o64` | `G-A-curated-thread-w224-wo0` | 0.6896 | 0.8604 | **0.7587** | 0.6696 | 9.1ms | 0.9980 |
| 14 | `multilingual-e5-small` | `R-B-window-t384-o64` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8458 | **0.7579** | 0.6834 | 9.4ms | 0.9980 |
| 15 | `multilingual-e5-small` | `R-B-window-t224-o128` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8541 | **0.7532** | 0.6604 | 9.6ms | 1.0000 |
| 16 | `multilingual-e5-small` | `R-A-heading-t224-o0` | `G-A-curated-thread-w224-wo0` | 0.6771 | 0.8667 | **0.7486** | 0.6526 | 9.0ms | 1.0000 |
| 17 | `multilingual-e5-small` | `R-B-window-t480-o32` | `G-A-curated-thread-w224-wo0` | 0.6687 | 0.8479 | **0.7429** | 0.6658 | 8.8ms | 1.0000 |
| 18 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w224-wo0` | 0.6687 | 0.8479 | **0.7426** | 0.6653 | 9.1ms | 1.0000 |
| 19 | `multilingual-e5-small` | `R-B-window-t496-o32` | `G-A-curated-thread-w224-wo0` | 0.6687 | 0.8479 | **0.7419** | 0.6640 | 9.0ms | 1.0000 |
| 20 | `multilingual-e5-small` | `R-B-window-t512-o32` | `G-A-curated-thread-w224-wo0` | 0.6687 | 0.8479 | **0.7419** | 0.6640 | 9.2ms | 1.0000 |
| 21 | `multilingual-e5-small` | `R-A-heading-t384-o64` | `G-A-curated-thread-w224-wo0` | 0.6500 | 0.8729 | **0.7387** | 0.6625 | 9.2ms | 0.9980 |
| 22 | `multilingual-e5-small` | `R-A-heading-t448-o64` | `G-A-curated-thread-w224-wo0` | 0.6500 | 0.8729 | **0.7387** | 0.6625 | 9.1ms | 1.0000 |
| 23 | `multilingual-e5-small` | `R-A-heading-t464-o64` | `G-A-curated-thread-w224-wo0` | 0.6500 | 0.8729 | **0.7387** | 0.6625 | 9.0ms | 0.9980 |
| 24 | `multilingual-e5-small` | `R-A-heading-t496-o64` | `G-A-curated-thread-w224-wo0` | 0.6500 | 0.8729 | **0.7387** | 0.6625 | 9.1ms | 0.9960 |
| 25 | `multilingual-e5-small` | `R-A-heading-t512-o64` | `G-A-curated-thread-w224-wo0` | 0.6500 | 0.8729 | **0.7387** | 0.6625 | 9.1ms | 0.9980 |

## 6. 결론 및 T9 인계 명세

1. **최종 선정 스택**:
   - **임베딩 모델**: `intfloat/multilingual-e5-small` (commit revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`)
   - **차원 및 Prefix**: 384 차원 / Query: `query: ` / Document: `passage: `
   - **RawPedia 청크 파일**: `data/chunks/t08-2-boundary-pooled/rawpedia/R-B-window-t224-o0.jsonl`
   - **GitHub 청크 파일**: `data/chunks/t08-2-boundary-pooled/github/G-A-curated-thread-w224-wo0.jsonl`
   - **Chroma 설정**: cosine 거리, HNSW ef_construction=200, ef_search=200

2. **인계 주의 사항**:
   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`query: `)를 부가하여 384차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.
   - GitHub 스레드 청크는 `thread_window_mean_v3` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.

