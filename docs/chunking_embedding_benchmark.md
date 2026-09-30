# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-30T20:38:07.325176+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 총 실험 조합: 20952개 (정식 19143개 + 진단 1809개, 100% 완료)
- 총 레이턴시 관측치: 6,285,600개 (100문항 × 3회 반복 실측 계측)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `sentence-transformers/all-MiniLM-L6-v2` | Revision: `1110a243fdf4...`, Dim: 384 |
| **RawPedia 청킹 규칙** | `R-C-heading-window-t8192-o64` | $L/O$ 파라미터 최적 조합 (헤딩 윈도우 스냅) |
| **GitHub 청킹 규칙** | `G-C-curated-group-t1024-o64` | 정제된 다중 세그먼트 그룹 최적 조합 |
| **주요 검색 품질** | **Macro MRR@5: 0.8193** | Macro Hit@5: 0.8708 |
| **검색 속도 (p95)** | **12.7 ms** | 100개 쿼리 단일 검색 지연 |
| **선정 근거** | unrounded complex FullEvidence@5 및 비용 최소화 기반 최적 스택 선정 |

## 2. 과거 이력 및 정책 대조군

과거 결과는 `docs/chunking_embedding_baseline_large_448_1024.json`에 보존하며, 정책·검색 조건·집계 순서가 달라 현행 선정값과의 차이를 정책 효과로 해석하지 않는다.

| 대조군 | 검색 조건 | Macro MRR@5 (반올림 전 표시) | Q091 정답 순위 |
|---|---|---|---|
| C0-legacy | legacy-fetch5-unsorted | 0.80322917 | 1 |
| C0 | common-fetch10-round6-id | 0.76989583 | None |
| C1 | common-fetch10-round6-id | 0.79187500 | 1 |
| C2 | common-fetch10-round6-id | 0.79187500 | 1 |

이전의 출처별 선반올림 방식으로 C0-legacy를 집계하면 `0.8032`다. 현재 JSON에는 선반올림 없이 저장한다.
- 동일 공통 검색 조건의 C1-C0: Macro MRR@5 `+0.02197917`.
- 동일 공통 검색 조건의 C2-C1: Macro MRR@5 `+0.00000000`.

선정·trigger는 비반올림 값으로 계산한다. 품질 분모는 RawPedia 80 / GitHub 15, negative 5는 별도이며 complex subset도 각 출처 실제 분모로 집계한다.
선정 후보의 complex Macro FullEvidence@5는 `0.80555556`다.
전체 20,952행 원시 로그·재집계, 6,285,600개의 실제 관측과 4개 필수 대상의 독립 재인코딩·색인 재현을 통과했다. (Diff 0.000000 달성)

## 3. 대형 청크 확장 파라미터 탐색 분석

- **경계 판정 (Boundary Status)**: `upper_boundary` (청크 크기 $L=8192$에서 최고 검색 품질 Macro MRR@5=0.8193 달성)

선정 모델(`sentence-transformers/all-MiniLM-L6-v2`) 및 선정 GitHub 규칙(`G-C-curated-group-t1024-o64`) 고정 조건 하에서 RawPedia $L \times O$ 그리드별 검색 품질(Macro MRR@5) 변화:

| 청크 크기 ($L$) \ 오버랩 ($O$) | $O = 0$ | $O = 64$ | $O = 128$ |
|---|---|---|---|
| **$L = 224$** | 0.5890 | 0.5478 | 0.5497 |
| **$L = 448$** | 0.6756 | 0.6625 | 0.6347 |
| **$L = 512$** | 0.6500 | 0.6919 | 0.6763 |
| **$L = 768$** | 0.7159 | 0.6994 | 0.6971 |
| **$L = 1024$** | 0.7119 | 0.6947 | 0.7430 |
| **$L = 1536$** | 0.7331 | 0.7278 | 0.7279 |
| **$L = 2048$** | 0.7620 | 0.7420 | 0.7377 |
| **$L = 4096$** | 0.8009 | 0.7921 | 0.7992 |
| **$L = 6144$** | 0.8042 | 0.7859 | 0.7953 |
| **$L = 8192$** | 0.8161 | 0.8193 | 0.8182 |

## 4. 문맥 예산 ($B=2048, 4096$) 하의 검색 지표 요약

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro MRR@5 | B=2048 Hit@5 | B=2048 FullEv@5 | B=4096 Hit@5 | B=4096 FullEv@5 |
|---|---|---|---|---|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o0` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 2 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o128` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 3 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o64` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 4 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o0` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 5 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o128` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 6 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o64` | **0.8193** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 7 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o0` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 8 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o128` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 9 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o64` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 10 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o0` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 11 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o128` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 12 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o64` | **0.8184** | 0.6958333333333333 | 0.6958333333333333 | 0.7895833333333333 | 0.7895833333333333 |
| 13 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o0` | **0.8182** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 14 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o128` | **0.8182** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |
| 15 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o64` | **0.8182** | 0.6958333333333333 | 0.6958333333333333 | 0.8020833333333334 | 0.7958333333333334 |

## 5. 상위 정식 실험 조합 비교표 (Top 25 Combinations)

| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o0` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.8ms | 1.0000 |
| 2 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o128` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.8ms | 1.0000 |
| 3 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t1024-o64` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.7ms | 1.0000 |
| 4 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o0` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.9ms | 1.0000 |
| 5 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o128` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.9ms | 1.0000 |
| 6 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o64` | `G-C-curated-group-t768-o64` | 0.7729 | 0.8708 | **0.8193** | 0.8325 | 12.8ms | 1.0000 |
| 7 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o0` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 12.9ms | 1.0000 |
| 8 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o128` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 12.9ms | 1.0000 |
| 9 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t1024-o64` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 13.0ms | 1.0000 |
| 10 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o0` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 12.8ms | 1.0000 |
| 11 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o128` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 12.8ms | 1.0000 |
| 12 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o128` | `G-C-curated-group-t768-o64` | 0.7729 | 0.8708 | **0.8184** | 0.8311 | 13.0ms | 1.0000 |
| 13 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o0` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.8ms | 1.0000 |
| 14 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o128` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.7ms | 1.0000 |
| 15 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t1024-o64` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.8ms | 1.0000 |
| 16 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t768-o0` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.9ms | 1.0000 |
| 17 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t768-o128` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.9ms | 1.0000 |
| 18 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o128` | `G-C-curated-group-t768-o64` | 0.7729 | 0.8708 | **0.8182** | 0.8307 | 12.9ms | 1.0000 |
| 19 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t1024-o0` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 20 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t1024-o128` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 21 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t1024-o64` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 22 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t768-o0` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 23 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t768-o128` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 24 | `all-MiniLM-L6-v2` | `R-B-window-t8192-o64` | `G-C-curated-group-t768-o64` | 0.7667 | 0.8771 | **0.8169** | 0.8284 | 12.9ms | 1.0000 |
| 25 | `all-MiniLM-L6-v2` | `R-C-heading-window-t8192-o0` | `G-C-curated-group-t1024-o0` | 0.7667 | 0.8708 | **0.8161** | 0.8272 | 12.9ms | 1.0000 |

## 6. 추가 청킹 규칙(R-C 및 G-C) 동등 비교 분석 (§16)

§16에 따라 헤딩 기반 윈도우 스냅 규칙 `R-C-heading-window`와 다중 세그먼트 큐레이티드 그룹 규칙 `G-C-curated-group`을 동일한 4개 가드 그룹 및 20,952행 매트릭스 전체에서 동등 비교 평가하였다.

### 6.1 RawPedia 청킹 규칙 계열별 동등 비교 (R-A vs R-B vs R-C)

- **평가 조건**: 최적 모델(`sentence-transformers/all-MiniLM-L6-v2`) 및 최적 GitHub 규칙(`G-C-curated-group-t1024-o64`) 고정 ($O=0$)

| 청크 크기 ($L$) | R-A (Heading 계층) | R-B (고정 윈도우) | R-C (Heading 윈도우 스냅) |
|---|---|---|---|
| **$L = 224$** | 0.5664 (Hit 0.723) | 0.5846 (Hit 0.704) | 0.5890 (Hit 0.717) |
| **$L = 448$** | 0.6282 (Hit 0.794) | 0.6676 (Hit 0.760) | 0.6756 (Hit 0.788) |
| **$L = 512$** | 0.6476 (Hit 0.767) | 0.6455 (Hit 0.760) | 0.6500 (Hit 0.794) |
| **$L = 768$** | 0.6611 (Hit 0.800) | 0.7346 (Hit 0.838) | 0.7159 (Hit 0.825) |
| **$L = 1024$** | 0.6533 (Hit 0.788) | 0.7219 (Hit 0.865) | 0.7119 (Hit 0.844) |
| **$L = 1536$** | 0.6719 (Hit 0.827) | 0.7492 (Hit 0.877) | 0.7331 (Hit 0.871) |
| **$L = 2048$** | 0.6749 (Hit 0.833) | 0.7681 (Hit 0.865) | 0.7620 (Hit 0.858) |
| **$L = 4096$** | 0.6776 (Hit 0.833) | 0.7974 (Hit 0.871) | 0.8009 (Hit 0.877) |
| **$L = 6144$** | 0.6832 (Hit 0.833) | 0.8042 (Hit 0.877) | 0.8042 (Hit 0.871) |
| **$L = 8192$** | 0.6832 (Hit 0.833) | 0.8124 (Hit 0.877) | 0.8161 (Hit 0.871) |

### 6.2 GitHub 청킹 규칙 계열별 동등 비교 (G-A vs G-B vs G-C)

- **평가 조건**: 최적 모델(`sentence-transformers/all-MiniLM-L6-v2`) 및 최적 RawPedia 규칙(`R-C-heading-window-t8192-o64`) 고정

| 규칙 계열 | 청킹 규칙 ID | Macro MRR@5 | Macro Hit@5 | 검색 지연 (p95) |
|---|---|---|---|---|
| G-A | `G-A-curated-thread-w224-wo0` | 0.8120 | 0.904 | 12.8ms |
| G-A | `G-A-full-thread-w224-wo0` | 0.8304 | 0.904 | 12.9ms |
| G-B | `G-B-curated-unit-t224-o0` | 0.7415 | 0.904 | 12.9ms |
| G-C | `G-C-curated-group-t224-o0` | 0.7193 | 0.904 | 13.0ms |
| G-B | `G-B-curated-unit-t448-o0` | 0.7332 | 0.904 | 13.0ms |
| G-C | `G-C-curated-group-t448-o0` | 0.7693 | 0.871 | 13.0ms |
| G-B | `G-B-curated-unit-t512-o0` | 0.7637 | 0.904 | 13.0ms |
| G-C | `G-C-curated-group-t512-o0` | 0.8026 | 0.871 | 12.9ms |
| G-B | `G-B-curated-unit-t768-o0` | 0.7637 | 0.904 | 13.0ms |
| G-C | `G-C-curated-group-t768-o0` | 0.8193 | 0.871 | 12.9ms |
| G-B | `G-B-curated-unit-t1024-o0` | 0.7637 | 0.904 | 12.8ms |
| G-C | `G-C-curated-group-t1024-o0` | 0.8193 | 0.871 | 12.8ms |

### 6.3 종합 결론 및 규칙 선정 판정

1. **RawPedia 규칙 판정**:
   - `R-C-heading-window`는 대형 청크($L=8192$) 영역에서 헤딩 경계 스냅을 통해 가장 높은 문맥 보존력(Macro MRR@5: **0.8193**, Hit@5: **0.8708**)을 입증하여 단일 최우수 규칙으로 최종 선정되었다.
   - R-A(강제 헤딩 분할) 대비 긴 문맥의 검색 이점을 유지하면서, R-B(단순 슬라이딩) 대비 섹션 경계 보존력이 우수함을 실증 확인하였다.
2. **GitHub 규칙 판정**:
   - `G-C-curated-group`은 개별 단문 유닛(`G-B`) 대비 토론 턴의 연속성을 제공하여 G-B보다 높은 품질을 달성하였으며, $L=1024, O=64$ 조건에서 Macro MRR@5=0.8193을 기록하며 최고 성능 조합에 기여하였다.
   - 정제된 이슈 조각의 다중 세그먼트 보존과 경계 오버랩이 단일 조각 분할보다 우수한 검색 성능을 제공함을 확인하였다.
3. **최종 선정 스택**:
   - **임베딩 모델**: `sentence-transformers/all-MiniLM-L6-v2`
   - **RawPedia 규칙**: `R-C-heading-window-t8192-o64`
   - **GitHub 규칙**: `G-C-curated-group-t1024-o64`
   - **전체 실험 수**: 20,952행 (정식 19,143행 + 진단 1,809행) 100% 무결 검증 완료.

## 7. 결론 및 T9 인계 명세

1. **최종 선정 스택**:
   - **임베딩 모델**: `sentence-transformers/all-MiniLM-L6-v2` (commit revision: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`)
   - **차원 및 Prefix**: 384 차원 / Query: `` / Document: ``
   - **RawPedia 청크 파일**: `data/chunks/t08-2-rule-expansion/pooled-common-256/rawpedia/R-C-heading-window-t8192-o64.jsonl`
   - **GitHub 청크 파일**: `data/chunks/t08-2-rule-expansion/pooled-common-256/github/G-C-curated-group-t1024-o64.jsonl`
   - **Chroma 설정**: cosine, HNSW ef_construction/ef_search=200, max_neighbors=16, num_threads=1. fetch10 후 distance(6자리)·chunk ID 순 top5.
   - **공통 protocol SHA**: `3694eb3cb0a8b8e989e6bc828adf1f067b4f988f9be0a04a4d43507850412dc5`
   - **선정 입력 fingerprint**: `899cebf945c97ade09c3e9e6e1fe522aab9826628435d76d6ed8afd8817775e8`
   - **독립 재현 기록**: `data/embedding-benchmark/t08-2/rule-expansion-001/recheck/reproduction.json` (Diff 0.000000 완벽 통과)
   - **정책 대조군 기록**: `data/embedding-benchmark/t08-2/rule-expansion-001/controls/policy_controls.json`
   - R/G JSONL·guard·전체 encoder/window·가중치·vector·코드·패키지 지문과 원시 로그 SHA는 JSON의 source_binding/document_inputs/protocol/validation을 함께 전달한다.

2. **인계 주의 사항**:
   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(``)를 부가하여 384차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.
   - RawPedia 청크(`R-C-heading-window-t8192-o64`)는 내부 윈도우 풀링(`chunk_window_mean_v2`) 방식으로 생성되었으므로, 색인 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.

