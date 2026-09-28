# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-28T14:27:08.141475+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 대형 청크 확장 단계: Stage N (2250개) + Stage P (2040개), 판정: 실행 (Triggered)
- 총 실험 조합: 4290개 (정식 3720개 + 진단 570개, 100% 완료)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `intfloat/multilingual-e5-small` | Revision: `614241f622f5...`, Dim: 384 |
| **RawPedia 청킹 규칙** | `R-B-window-t448-o32` | $L/O$ 파라미터 최적 조합 |
| **GitHub 청킹 규칙** | `G-A-curated-thread-w224-wo0` | 정제된 스레드/유닛 최적 조합 |
| **주요 검색 품질** | **Macro MRR@5: 0.8032** | Macro Hit@5: 0.8854 |
| **검색 속도 (p95)** | **8.7 ms** | 100개 쿼리 단일 검색 지연 |
| **선정 근거** | Highest retrieval precision under Korean-to-English evaluation with optimal latency/storage tradeoff. |

## 2. 기존 기준선 대비 증감 비교

| 지표 | 이전 최적 기준선 (`grid_128_224`) | 대형 청크 확장 최적 스택 (`large_grid`) | 증감 (Delta) |
|---|---|---|---|
| **임베딩 모델** | `BAAI/bge-base-en-v1.5` | `intfloat/multilingual-e5-small` | 동일 모델 유지/비교 |
| **RawPedia 규칙** | `R-B-window-t224-o0` | `R-B-window-t448-o32` | 청크 크기/오버랩 확장 비교 |
| **GitHub 규칙** | `G-A-curated-thread-w224-wo0` | `G-A-curated-thread-w224-wo0` | 스레드 윈도우 확장 비교 |
| **Macro MRR@5** | 0.7655 | **0.8032** | **+0.0377** |
| **Macro Hit@5** | 0.9000 | **0.8854** | **-0.0146** |

## 3. 대형 청크 확장 파라미터 탐색 분석

- **경계 판정 (Boundary Status)**: `upper_boundary` (물리 청크 크기가 Stage N의 상한선(448 토큰)에 도달하였음.)

선정 모델(`intfloat/multilingual-e5-small`) 및 선정 GitHub 규칙 고정 조건 하에서 RawPedia $L \times O$ 그리드별 검색 품질(Macro MRR@5) 변화:

| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ (중복 없음) | $O = 32$ (경량 오버랩) | $O = 64$ (확장 오버랩) |
|---|---|---|---|
| **$L = 224$** | 0.7673 | 0.7295 | 0.7637 |
| **$L = 256$** | 0.7653 | 0.7473 | 0.7548 |
| **$L = 320$** | 0.7782 | 0.7399 | 0.7308 |
| **$L = 384$** | 0.7540 | 0.7863 | 0.7507 |
| **$L = 448$** | 0.7928 | 0.8032 | 0.7747 |

## 4. 상위 정식 실험 조합 비교표 (Top 25 Combinations)

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w224-wo0` | 0.7541 | 0.8854 | **0.8032** | 0.7142 | 8.7ms | 1.0000 |
| 2 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w384-wo0` | 0.7541 | 0.8854 | **0.8032** | 0.7142 | 8.7ms | 1.0000 |
| 3 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w448-wo0` | 0.7541 | 0.8854 | **0.8032** | 0.7142 | 8.7ms | 1.0000 |
| 4 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w256-wo0` | 0.7479 | 0.8854 | **0.8001** | 0.7090 | 8.7ms | 1.0000 |
| 5 | `multilingual-e5-small` | `R-B-window-t448-o32` | `G-A-curated-thread-w320-wo0` | 0.7479 | 0.8854 | **0.8001** | 0.7090 | 8.7ms | 1.0000 |
| 6 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w384-wo0` | 0.7291 | 0.8979 | **0.7980** | 0.7054 | 8.7ms | 1.0000 |
| 7 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w448-wo0` | 0.7291 | 0.8979 | **0.7980** | 0.7054 | 8.7ms | 1.0000 |
| 8 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w320-wo0` | 0.7291 | 0.8979 | **0.7975** | 0.7046 | 8.7ms | 1.0000 |
| 9 | `multilingual-e5-small` | `R-A-heading-t448-o32` | `G-A-curated-thread-w256-wo0` | 0.7291 | 0.8979 | **0.7964** | 0.7028 | 8.7ms | 1.0000 |
| 10 | `multilingual-e5-small` | `R-A-heading-t320-o32` | `G-A-curated-thread-w448-wo0` | 0.7417 | 0.8854 | **0.7958** | 0.7017 | 8.8ms | 1.0000 |
| 11 | `multilingual-e5-small` | `R-A-heading-t320-o32` | `G-A-curated-thread-w320-wo0` | 0.7417 | 0.8854 | **0.7955** | 0.7012 | 8.8ms | 1.0000 |
| 12 | `multilingual-e5-small` | `R-A-heading-t320-o32` | `G-A-curated-thread-w384-wo0` | 0.7417 | 0.8854 | **0.7955** | 0.7012 | 8.9ms | 1.0000 |
| 13 | `multilingual-e5-small` | `R-A-heading-t320-o32` | `G-A-curated-thread-w256-wo0` | 0.7417 | 0.8854 | **0.7950** | 0.7004 | 8.9ms | 1.0000 |
| 14 | `multilingual-e5-small` | `R-B-window-t320-o0` | `G-A-curated-thread-w320-wo0` | 0.7271 | 0.8917 | **0.7949** | 0.7230 | 8.7ms | 0.9960 |
| 15 | `multilingual-e5-small` | `R-A-heading-t448-o0` | `G-A-curated-thread-w384-wo0` | 0.7229 | 0.8979 | **0.7931** | 0.6972 | 8.8ms | 1.0000 |
| 16 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w224-wo0` | 0.7396 | 0.8729 | **0.7928** | 0.7195 | 8.7ms | 1.0000 |
| 17 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w384-wo0` | 0.7396 | 0.8729 | **0.7928** | 0.7195 | 8.6ms | 1.0000 |
| 18 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w448-wo0` | 0.7396 | 0.8729 | **0.7928** | 0.7195 | 8.7ms | 1.0000 |
| 19 | `multilingual-e5-small` | `R-A-heading-t448-o0` | `G-A-curated-thread-w320-wo0` | 0.7229 | 0.8979 | **0.7926** | 0.6963 | 8.7ms | 1.0000 |
| 20 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w256-wo0` | 0.7396 | 0.8729 | **0.7917** | 0.7177 | 8.6ms | 1.0000 |
| 21 | `multilingual-e5-small` | `R-B-window-t448-o0` | `G-A-curated-thread-w320-wo0` | 0.7396 | 0.8729 | **0.7917** | 0.7177 | 8.8ms | 1.0000 |
| 22 | `multilingual-e5-small` | `R-A-heading-t448-o0` | `G-A-curated-thread-w256-wo0` | 0.7229 | 0.8979 | **0.7915** | 0.6946 | 8.7ms | 1.0000 |
| 23 | `multilingual-e5-small` | `R-A-heading-t320-o0` | `G-A-curated-thread-w320-wo0` | 0.7229 | 0.8917 | **0.7884** | 0.6893 | 8.8ms | 1.0000 |
| 24 | `multilingual-e5-small` | `R-B-window-t384-o32` | `G-A-curated-thread-w448-wo0` | 0.7271 | 0.8791 | **0.7876** | 0.7107 | 8.7ms | 1.0000 |
| 25 | `multilingual-e5-small` | `R-A-heading-t320-o64` | `G-A-curated-thread-w448-wo0` | 0.7146 | 0.8979 | **0.7872** | 0.7100 | 8.8ms | 1.0000 |

## 5. 진단 후보군(`G-A-full-thread`) 대비 정제 효과 분석

미정제 전체 댓글 39개를 포함한 진단 기준선(`G-A-full-thread`)과 정제된 35개 조각 스레드(`G-A-curated-thread`)의 성능 대조:

| 모델 ID | 윈도우 크기 ($W$) | 정제 스레드 (`G-A-curated`) MRR@5 | 진단 전체 스레드 (`G-A-full`) MRR@5 | 정제 효과 (Noise Reduction) |
|---|---|---|---|---|
| `multilingual-e5-small` | $W = 224$ | 0.7490 | 0.7316 | **+0.0174** |
| `multilingual-e5-small` | $W = 256$ | 0.7545 | 0.7545 | **+0.0000** |
| `multilingual-e5-small` | $W = 320$ | 0.7555 | 0.7039 | **+0.0516** |
| `multilingual-e5-small` | $W = 384$ | 0.7555 | 0.7070 | **+0.0485** |
| `multilingual-e5-small` | $W = 448$ | 0.7555 | 0.7008 | **+0.0547** |

## 6. 결론 및 T9 인계 명세

1. **최종 선정 스택**:
   - **임베딩 모델**: `intfloat/multilingual-e5-small` (commit revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`)
   - **차원 및 Prefix**: 384 차원 / Query: `query: ` / Document: `passage: `
   - **RawPedia 청크 파일**: `data/chunks/t08-2-large-native/e5-512/rawpedia/R-B-window-t448-o32.jsonl`
   - **GitHub 청크 파일**: `data/chunks/t08-2-large-native/e5-512/github/G-A-curated-thread-w224-wo0.jsonl`
   - **Chroma 설정**: cosine 거리, HNSW ef_construction=200, ef_search=200

2. **인계 주의 사항**:
   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`query: `)를 부가하여 384차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.
   - GitHub 스레드 청크는 `thread_window_mean_v2` 임베딩 정책이 적용되어 있으므로, 갱신 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.

