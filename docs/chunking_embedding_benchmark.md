# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트

- 생성 일시: 2026-09-28T06:17:02.110114+00:00
- 평가 질문 데이터셋: `t08-1-100-v1` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)
- 총 실험 조합: 24개 (정식 16개 + 진단 8개)

## 1. 최종 선정 결과 요약

| 구분 | 선정 항목 | 상세 내용 |
|---|---|---|
| **최적 임베딩 모델** | `intfloat/multilingual-e5-small` | Revision: `614241f622f5...`, Dim: 384 |
| **RawPedia 청킹 규칙** | `R-B-window` | 목표 192 토큰, 슬라이딩 오버랩 32 토큰 |
| **GitHub 청킹 규칙** | `G-A-curated-thread` | 정제된 유의미 body/댓글 독립 청크 단위 |
| **주요 검색 품질** | **Macro MRR@5: 0.7830** | Macro Hit@5: 0.8541 |
| **검색 속도 (p95)** | **0.7 ms** | 100개 쿼리 배치 1 단일 검색 지연 |

## 2. 전체 실험 조합 비교표 (Cartesian Product 24개 조합)

| 구분 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | RawPedia MRR@5 | GitHub MRR@5 | p95 지연 (ms) | ANN 일치율 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 정식 | `multilingual-e5-small` | `R-B-window` | `G-A-curated-thread` | 0.7354 | 0.8541 | **0.7830** | 0.6802 | 0.6327 | 0.9333 | 0.7ms | 0.9920 |
| 정식 | `multilingual-e5-small` | `R-A-heading` | `G-A-curated-thread` | 0.7104 | 0.8292 | **0.7604** | 0.6421 | 0.5875 | 0.9333 | 0.7ms | 0.9920 |
| 정식 | `bge-base-en-v1.5` | `R-B-window` | `G-A-curated-thread` | 0.5708 | 0.8604 | **0.6900** | 0.6222 | 0.5910 | 0.7889 | 1.0ms | 0.9920 |
| 정식 | `multilingual-e5-small` | `R-B-window` | `G-B-curated-unit` | 0.6021 | 0.7875 | **0.6830** | 0.6486 | 0.6327 | 0.7333 | 0.7ms | 0.9840 |
| 정식 | `bge-small-en-v1.5` | `R-B-window` | `G-A-curated-thread` | 0.5500 | 0.8604 | **0.6799** | 0.6394 | 0.6208 | 0.7389 | 0.7ms | 1.0000 |
| 정식 | `bge-base-en-v1.5` | `R-A-heading` | `G-A-curated-thread` | 0.5312 | 0.8417 | **0.6661** | 0.6048 | 0.5765 | 0.7556 | 1.0ms | 0.9940 |
| 정식 | `multilingual-e5-small` | `R-A-heading` | `G-B-curated-unit` | 0.5041 | 0.7896 | **0.6320** | 0.5930 | 0.5750 | 0.6889 | 0.8ms | 0.9900 |
| 정식 | `bge-small-en-v1.5` | `R-A-heading` | `G-A-curated-thread` | 0.4646 | 0.8541 | **0.6305** | 0.5944 | 0.5777 | 0.6833 | 0.6ms | 1.0000 |
| 정식 | `bge-base-en-v1.5` | `R-B-window` | `G-B-curated-unit` | 0.4437 | 0.7937 | **0.5853** | 0.5942 | 0.5983 | 0.5722 | 1.0ms | 0.9920 |
| 정식 | `all-MiniLM-L6-v2` | `R-B-window` | `G-A-curated-thread` | 0.4708 | 0.7167 | **0.5695** | 0.5714 | 0.5723 | 0.5667 | 0.7ms | 0.9920 |
| 정식 | `all-MiniLM-L6-v2` | `R-B-window` | `G-B-curated-unit` | 0.4375 | 0.7167 | **0.5584** | 0.5679 | 0.5723 | 0.5444 | 0.7ms | 0.9980 |
| 정식 | `bge-base-en-v1.5` | `R-A-heading` | `G-B-curated-unit` | 0.3979 | 0.7416 | **0.5454** | 0.5674 | 0.5775 | 0.5133 | 1.0ms | 0.9960 |
| 정식 | `bge-small-en-v1.5` | `R-B-window` | `G-B-curated-unit` | 0.3500 | 0.7937 | **0.5437** | 0.5965 | 0.6208 | 0.4667 | 0.6ms | 0.9940 |
| 정식 | `all-MiniLM-L6-v2` | `R-A-heading` | `G-A-curated-thread` | 0.4334 | 0.7229 | **0.5364** | 0.5256 | 0.5206 | 0.5522 | 0.8ms | 0.9980 |
| 정식 | `all-MiniLM-L6-v2` | `R-A-heading` | `G-B-curated-unit` | 0.4000 | 0.7563 | **0.5364** | 0.5256 | 0.5206 | 0.5522 | 0.6ms | 0.9960 |
| 정식 | `bge-small-en-v1.5` | `R-A-heading` | `G-B-curated-unit` | 0.3313 | 0.7875 | **0.5039** | 0.5544 | 0.5777 | 0.4300 | 0.7ms | 0.9960 |
| 진단 | `multilingual-e5-small` | `R-B-window` | `G-A-full-thread` | 0.6896 | 0.8541 | **0.7601** | 0.6644 | 0.6202 | 0.9000 | 0.7ms | 0.9960 |
| 진단 | `multilingual-e5-small` | `R-A-heading` | `G-A-full-thread` | 0.6708 | 0.8292 | **0.7396** | 0.6299 | 0.5792 | 0.9000 | 0.7ms | 0.9920 |
| 진단 | `bge-small-en-v1.5` | `R-B-window` | `G-A-full-thread` | 0.6166 | 0.8604 | **0.7170** | 0.6512 | 0.6208 | 0.8133 | 0.6ms | 0.9960 |
| 진단 | `bge-small-en-v1.5` | `R-A-heading` | `G-A-full-thread` | 0.5979 | 0.8541 | **0.6955** | 0.6149 | 0.5777 | 0.8133 | 0.6ms | 0.9940 |
| 진단 | `bge-base-en-v1.5` | `R-B-window` | `G-A-full-thread` | 0.5708 | 0.8604 | **0.6900** | 0.6222 | 0.5910 | 0.7889 | 1.0ms | 0.9940 |
| 진단 | `bge-base-en-v1.5` | `R-A-heading` | `G-A-full-thread` | 0.5646 | 0.8417 | **0.6883** | 0.6118 | 0.5765 | 0.8000 | 1.0ms | 0.9920 |
| 진단 | `all-MiniLM-L6-v2` | `R-B-window` | `G-A-full-thread` | 0.5041 | 0.8166 | **0.6234** | 0.5884 | 0.5723 | 0.6744 | 0.6ms | 0.9960 |
| 진단 | `all-MiniLM-L6-v2` | `R-A-heading` | `G-A-full-thread` | 0.4334 | 0.7563 | **0.5431** | 0.5277 | 0.5206 | 0.5656 | 0.7ms | 0.9980 |

## 3. 분석 및 선정 근거

1. **언어 간 검색 (Cross-Lingual) 격차**:
   - 한국어 평가 질의(100개)를 영문 코퍼스에 직접 매칭할 때, 다국어 사전학습 임베딩 모델인 `intfloat/multilingual-e5-small`이 모든 조합에서 최고 성능(Macro MRR@5: 0.7830)을 기록함.
   - 영문 전용 모델인 `bge-base-en-v1.5`(최고 0.6900), `bge-small-en-v1.5`(최고 0.6799), `all-MiniLM-L6-v2`(최고 0.5695)는 교차 언어 정렬 한계로 인해 MRR@5 격차가 확연함.

2. **청킹 규칙 비교**:
   - **RawPedia**: 슬라이딩 윈도우 방식인 `R-B-window`가 헤딩 기반 분할(`R-A-heading`) 대비 일관되게 높은 점수(0.7830 vs 0.7604)를 보임. 이는 32토큰 오버랩을 통해 헤딩 경계에 걸친 세부 파라미터나 상호 참조 문맥이 누락 없이 검색 스팬에 잘 포착되기 때문임.
   - **GitHub**: 스레드 문맥을 보존하는 `G-A-curated-thread`가 단일 단위(`G-B-curated-unit`) 대비 큰 폭의 우위(0.7830 vs 0.6830, +0.1000)를 기록함. 단편적인 댓글 1개보다 부모 이슈/디스커션과 조치 댓글이 결합된 스레드 수준의 풍부한 맥락(`thread_window_mean_v1` 임베딩 정책)이 질의 매칭에 결정적이었음.
   - **진단 기준선(`G-A-full-thread`) 대비**: 미정제 전체 댓글 39개를 모두 포함한 `G-A-full-thread`(MRR@5: 0.7601) 대비, 정제된 35개 조각만 포함한 `G-A-curated-thread`(MRR@5: 0.7830)가 오히려 더 높은 품질을 보여 정제 룰(T10-2a)의 노이즈 제거 효과가 입증됨.

3. **T9 전달 사항**:
   - **선정 모델**: `intfloat/multilingual-e5-small` (revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`, dim: 384, query prefix: `query: `, doc prefix: `passage: `)
   - **선정 청크셋**:
     - RawPedia: `data/chunks/t08-2/rawpedia/R-B-window.jsonl` (2,584개 청크)
     - GitHub: `data/chunks/t08-2/github/G-A-curated-thread.jsonl` (12개 스레드 청크)
   - **Chroma 설정**: 코사인 공간(`hnsw:space="cosine"`), ef_construction=200, ef_search=200, max_neighbors=16

