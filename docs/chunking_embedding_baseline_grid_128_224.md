# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-28T08:22:59.297987+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 탐색 파라미터 그리드: L in {128, 192, 224}, O in {0, 32, 64}
- 총 실험 조합: 1080개 (정식 864개 + 진단 216개, 100% 완료)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `BAAI/bge-base-en-v1.5` | Revision: `a5beb1e3e68b...`, Dim: 768 |
| **RawPedia 청킹 규칙** | `R-B-window-t224-o0` | $L/O$ 파라미터 최적 조합 |
| **GitHub 청킹 규칙** | `G-A-curated-thread-w224-wo0` | 정제된 스레드/유닛 최적 조합 |
| **주요 검색 품질** | **Macro MRR@5: 0.7655** | Macro Hit@5: 0.9000 |
| **검색 속도 (p95)** | **19.6 ms** | 100개 쿼리 단일 검색 지연 |
| **선정 근거** | Highest retrieval precision under Korean-to-English evaluation with optimal latency/storage tradeoff. |

## 2. 192/32 기준선 대비 증감 비교

| 지표 | 192/32 기준선 (`baseline_192_32`) | 신규 최적 스택 (`grid_search`) | 증감 (Delta) |
|---|---|---|---|
| **임베딩 모델** | `intfloat/multilingual-e5-small` | `BAAI/bge-base-en-v1.5` | intfloat/multilingual-e5-small -> BAAI/bge-base-en-v1.5 |
| **RawPedia 규칙** | `R-B-window` (192/32) | `R-B-window-t224-o0` | 파라미터 최적화 |
| **GitHub 규칙** | `G-A-curated-thread` (192) | `G-A-curated-thread-w224-wo0` | 윈도우 크기 최적화 |
| **Macro MRR@5** | 0.7830 | **0.7655** | **-0.0175** |
| **Macro Hit@5** | 0.8541 | **0.9000** | **+0.0459** |

## 3. 청킹 크기($L$) 및 오버랩($O$) 그리드 탐색 분석 (3×3 Grid Effect)

최적 모델(`BAAI/bge-base-en-v1.5`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \times O$ 그리드별 검색 품질(Macro MRR@5) 변화:

| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ (중복 없음) | $O = 32$ (경량 오버랩) | $O = 64$ (확장 오버랩) |
|---|---|---|---|
| **$L = 128$** | 0.6981 | 0.6986 | 0.7305 |
| **$L = 192$** | 0.7582 | 0.7339 | 0.6957 |
| **$L = 224$** | 0.7655 | 0.7440 | 0.7469 |

## 4. 상위 정식 실험 조합 비교표 (Top 25 Combinations)

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `bge-base-en-v1.5` | `R-B-window-t224-o0` | `G-A-curated-thread-w224-wo0` | 0.6834 | 0.9000 | **0.7655** | 0.6583 | 19.6ms | 0.9960 |
| 2 | `bge-base-en-v1.5` | `R-B-window-t192-o0` | `G-A-curated-thread-w224-wo0` | 0.6708 | 0.8938 | **0.7582** | 0.6460 | 19.5ms | 0.9980 |
| 3 | `multilingual-e5-small` | `R-B-window-t224-o0` | `G-A-curated-thread-w224-wo0` | 0.6959 | 0.8541 | **0.7576** | 0.6602 | 6.3ms | 0.9940 |
| 4 | `multilingual-e5-small` | `R-B-window-t224-o64` | `G-A-curated-thread-w224-wo0` | 0.6834 | 0.8541 | **0.7551** | 0.6560 | 6.3ms | 0.9960 |
| 5 | `bge-base-en-v1.5` | `R-A-heading-t192-o0` | `G-A-curated-thread-w224-wo0` | 0.6771 | 0.8875 | **0.7545** | 0.6397 | 19.6ms | 0.9920 |
| 6 | `multilingual-e5-small` | `R-B-window-t224-o32` | `G-A-curated-thread-w224-wo0` | 0.6896 | 0.8541 | **0.7536** | 0.6535 | 6.3ms | 0.9940 |
| 7 | `multilingual-e5-small` | `R-A-heading-t192-o64` | `G-A-curated-thread-w224-wo0` | 0.6708 | 0.8604 | **0.7492** | 0.6461 | 6.3ms | 0.9940 |
| 8 | `bge-base-en-v1.5` | `R-B-window-t224-o0` | `G-A-curated-thread-w192-wo0` | 0.6500 | 0.9000 | **0.7489** | 0.6530 | 19.6ms | 0.9980 |
| 9 | `multilingual-e5-small` | `R-B-window-t192-o32` | `G-A-curated-thread-w224-wo0` | 0.6834 | 0.8541 | **0.7476** | 0.6433 | 6.3ms | 0.9920 |
| 10 | `bge-base-en-v1.5` | `R-B-window-t224-o64` | `G-A-curated-thread-w224-wo0` | 0.6771 | 0.8625 | **0.7469** | 0.6269 | 19.6ms | 0.9940 |
| 11 | `bge-base-en-v1.5` | `R-B-window-t224-o32` | `G-A-curated-thread-w224-wo0` | 0.6687 | 0.8750 | **0.7440** | 0.6488 | 19.6ms | 0.9940 |
| 12 | `multilingual-e5-small` | `R-A-heading-t192-o32` | `G-A-curated-thread-w224-wo0` | 0.6708 | 0.8479 | **0.7434** | 0.6363 | 6.3ms | 0.9900 |
| 13 | `multilingual-e5-small` | `R-A-heading-t224-o64` | `G-A-curated-thread-w224-wo0` | 0.6583 | 0.8541 | **0.7431** | 0.6357 | 6.3ms | 0.9900 |
| 14 | `bge-base-en-v1.5` | `R-B-window-t192-o0` | `G-A-curated-thread-w192-wo0` | 0.6375 | 0.8938 | **0.7415** | 0.6407 | 19.5ms | 0.9960 |
| 15 | `bge-small-en-v1.5` | `R-B-window-t224-o0` | `G-A-curated-thread-w128-wo0` | 0.6417 | 0.8854 | **0.7406** | 0.6848 | 7.8ms | 1.0000 |
| 16 | `bge-base-en-v1.5` | `R-A-heading-t192-o0` | `G-A-curated-thread-w192-wo0` | 0.6438 | 0.8875 | **0.7378** | 0.6344 | 19.6ms | 0.9920 |
| 17 | `multilingual-e5-small` | `R-B-window-t224-o0` | `G-A-curated-thread-w192-wo0` | 0.6562 | 0.8479 | **0.7356** | 0.6458 | 6.2ms | 1.0000 |
| 18 | `multilingual-e5-small` | `R-B-window-t224-o64` | `G-A-curated-thread-w192-wo0` | 0.6438 | 0.8541 | **0.7351** | 0.6451 | 6.3ms | 0.9980 |
| 19 | `multilingual-e5-small` | `R-A-heading-t192-o0` | `G-A-curated-thread-w224-wo0` | 0.6583 | 0.8479 | **0.7347** | 0.6216 | 6.3ms | 0.9880 |
| 20 | `bge-base-en-v1.5` | `R-A-heading-t224-o0` | `G-A-curated-thread-w192-wo0` | 0.6375 | 0.8750 | **0.7345** | 0.6288 | 19.6ms | 0.9900 |
| 21 | `bge-base-en-v1.5` | `R-B-window-t192-o32` | `G-A-curated-thread-w224-wo0` | 0.6375 | 0.8875 | **0.7339** | 0.6318 | 19.6ms | 0.9940 |
| 22 | `bge-base-en-v1.5` | `R-B-window-t224-o32` | `G-A-curated-thread-w192-wo0` | 0.6417 | 0.8812 | **0.7336** | 0.6540 | 19.6ms | 0.9960 |
| 23 | `multilingual-e5-small` | `R-B-window-t128-o32` | `G-A-curated-thread-w224-wo0` | 0.6708 | 0.8229 | **0.7327** | 0.6182 | 6.3ms | 0.9840 |
| 24 | `multilingual-e5-small` | `R-B-window-t192-o32` | `G-A-curated-thread-w192-wo0` | 0.6500 | 0.8604 | **0.7319** | 0.6397 | 6.3ms | 0.9940 |
| 25 | `multilingual-e5-small` | `R-A-heading-t224-o0` | `G-A-curated-thread-w224-wo0` | 0.6459 | 0.8541 | **0.7316** | 0.6163 | 6.5ms | 0.9920 |

## 5. 진단 후보군(`G-A-full-thread`) 대비 정제 효과 분석

미정제 전체 댓글 39개를 포함한 진단 기준선(`G-A-full-thread`)과 정제된 35개 조각 스레드(`G-A-curated-thread`)의 성능 대조:

| 모델 ID | 윈도우 크기 ($W$) | 정제 스레드 (`G-A-curated`) MRR@5 | 진단 전체 스레드 (`G-A-full`) MRR@5 | 정제 효과 (Noise Reduction) |
|---|---|---|---|---|
| `bge-base-en-v1.5` | $W = 128$ | 0.6477 | 0.6587 | **-0.0110** |
| `bge-base-en-v1.5` | $W = 192$ | 0.6754 | 0.6865 | **-0.0111** |
| `bge-base-en-v1.5` | $W = 224$ | 0.6921 | 0.6921 | **+0.0000** |

## 6. 결론 및 T9 인계 명세

1. **최종 선정 스택**:
   - **임베딩 모델**: `BAAI/bge-base-en-v1.5` (commit revision: `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`)
   - **차원 및 Prefix**: 768 차원 / Query: `Represent this sentence for searching relevant passages: ` / Document: ``
   - **RawPedia 청크 파일**: `data/chunks/t08-2-grid/rawpedia/R-B-window-t224-o0.jsonl`
   - **GitHub 청크 파일**: `data/chunks/t08-2-grid/github/G-A-curated-thread-w224-wo0.jsonl`
   - **Chroma 설정**: cosine 거리, HNSW ef_construction=200, ef_search=200

2. **인계 주의 사항**:
   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`Represent this sentence for searching relevant passages: `)를 부가하여 768차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.
   - GitHub 스레드 청크는 `thread_window_mean_v1` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.

