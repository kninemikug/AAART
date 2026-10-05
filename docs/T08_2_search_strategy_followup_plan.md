# T8-2 후속 검색 방식 비교 실행 플랜

작성일: 2026-09-29 · 플랜 담당: 김대성 레인

**상태: `awaiting_t08_2_completion` — 계획 작성 완료, 구현·벤치마크 미착수.** 현재 실행 중인 [T8-2 실행 플랜 §15](T08_2_execution_plan.md#15-현행-정책-전체-조합-재측정과-선정-재검증)가 검증까지 끝난 뒤 이 문서를 실행한다. 선행 작업의 코드·행렬·청크·캐시·보고서는 그대로 사용하고, 후속 산출물은 별도 경로에 기록한다.

목표는 **검증된 청킹·임베딩 조합 5~8개 × 검색 방식 3개**를 비교하여, 검색 방식이 바뀌면 청킹·모델 선정도 달라지는지 확인하는 것이다. 5502개 조합에 검색 방식을 모두 곱하지 않는다. 선행 T8-2 결과는 해당 벡터 검색 조건에서의 선정이며, 이번 결과도 고정 질문셋과 등록 후보 범위의 선정으로 표현한다.

## 1. 선행 작업과 착수 조건

### 1.1 작업 관계

```text
T8-2 §15 전체 재측정·독립 재현·선정 완료
  ├─ T9: 검증된 벡터 검색 기준선 인계·공통 모듈 구현
  └─ 이 후속 실험: 대표 스택 선정 → 검색 3종 비교 → 필요 시 크기/O/W 국소 비교
       └─ T15 입력: 검색 방식 후보·재현 명세·query별 득실
T9 + T14 → T15: 서비스 경로에서 리랭킹·top-k·임계값 튜닝 및 검증
```

후속 실험의 독립 벤치마크는 T8-2 완료 후 시작할 수 있다. 서비스 연결은 기존 [T9·T14·T15 의존 관계](../tasks/todo.md)를 따른다. 이 실험을 기다리느라 완료된 T8-2의 기준선 인계를 막지 않는다. T15의 리랭킹·k 튜닝 완료 기준, 담당 김구, WBS 일정·시간 배분은 기존대로이며 추가 실험 시간은 별도로 기록한다.

현재는 문서 준비와 입력 구조 확인까지만 수행한다. 실행 중인 `scripts/benchmark_embeddings.py`, `scripts/chunk_corpus.py`, `src/artagent/chunking.py`, 해당 테스트 및 원본 보고서에 후속 구현을 섞지 않는다. 선행 실행이 끝난 뒤 확정 코드·실제 검색 설정을 받아 사용하며, 미완료 checkpoint를 완성된 입력으로 취급하지 않는다.

### 1.2 `prepare`가 확인할 시작 게이트

다음 조건을 모두 충족해야 `ready`로 전환한다. 파일 존재나 완료 체크박스만으로 통과하지 않는다.

| 조건 | 확인할 증거 |
|---|---|
| 선행 §15 전체 완료 | 필수 5478 + 추가 24 = **5502행**, 정식 4716/진단 786, `pending=failed=0`; C0/C1/C2는 별도 대조군 |
| 실제 실행 로그 완비 | 100문항 × 3회 × 5502행 = **1,650,600개** 지연 관측과 원시 검색 로그; 전수 재집계 일치 |
| 입력·청킹·임베딩 무결성 | 원문 누락·source/hash 오류·truncation·guard 그룹 불일치 0; 모든 실제 encoder 입력/window trace |
| 재현 문제 해결 | 선두·선정·차순위·현행 448/32 기준점·Q091의 독립 재현 및 ANN 검사 통과; 원인과 보정 기록 |
| 선정 계약 확정 | 압축 정본 `docs/chunking_embedding_benchmark.json.gz`을 펼친 JSON의 검증된 `selected`, 실제 R/G JSONL·모델 revision·guard/window/prefix·Chroma/검색 설정 |

선행 완료 기준이 정식으로 개정되면 개정 문서·commit과 변경된 분모를 함께 고정한다. 후속 실행자가 일부 완료 행만 읽어 시작 조건을 낮추지 않는다. 입력 부족 시 `status=awaiting_t08_2_completion`, 누락 목록을 출력하고 종료한다. 자동 원문 재수집·골드 변경·모델 대체로 진행하지 않는다.

## 2. 선행 결과 인수와 실험 고정

`prepare`에서 다음을 `upstream_snapshot.json`과 `protocol.json`에 고정한다.

- 선행 실행 ID, 완료 코드 commit, 보고서 JSON/MD SHA, 행렬·환경·원시 로그 manifest SHA, 선정/선두/차순위의 원본 행 ID.
- RawPedia **116개 전량**, GitHub **정제 후보 12개·35조각**, 관련 snapshots·후보 규칙·source manifest SHA. 전체 스레드 진단 행은 선정 대상에 편입하지 않는다.
- `docs/search_eval_queries.json`의 dataset/schema/SHA, 질문 100개, 양성 **RawPedia 80 + GitHub 15**, negative 5, 근거 **147개 = support 142 + counterevidence 5**. 실제 파일을 전수 검증한다.
- 각 스택의 R/G 방식·요청/실측 L/O/W, JSONL 건수·SHA·chunk ID 순서, 원문 위치 schema, 모델 ID/revision/차원/정규화/prefix 및 native/pooled 정책 지문.
- 검증된 Chroma package·cosine/HNSW·삽입 순서·검색 후보 수 `D`·정렬 및 동점 규칙. 현재 작업 중 코드의 후보 10개/최종 5개 설정은 잠정 관찰이며 **완료된 선행 protocol의 실제 값**을 인수한다. `D≥5`여야 한다.
- CPU/device/thread/seed·reference tokenizer와 title 조립 규칙·예산 packing 규칙. 본 후속 코드 commit·BM25 tokenizer/점수식·RRF 상수·등록 행렬 SHA도 기록한다.

검색은 두 출처의 혼합 코퍼스 전체에서 수행한다. 질문의 `source_type`, 정답 문서 ID, 골드 스팬으로 후보를 미리 제한하지 않는다. 질문 원문은 세 방식 모두 동일하며 모델용 query prefix는 벡터 인코딩에만 적용한다.

선행 문서 벡터는 전체 입력·모델·정책·ID 순서 SHA가 일치할 때 재사용할 수 있다. 후속 Chroma 작업 위치와 lexical 색인은 분리한다. 주 지연 측정에서는 query embedding과 검색 결과를 캐시하지 않는다. `protocol_hash`가 달라지면 새 run ID로 모든 등록 행을 다시 측정한다.

## 3. 대표 스택 5~8개 선정 규칙

검색 방식별 결과를 보기 **전에**, 선행 정식·검증 완료 행만 사용해 아래 순서로 슬롯을 채운다. 점수 순서는 선행 §8.1의 반올림 전 Macro MRR@5 → Macro Hit@5 → complex Macro FullEvidence_all@5 → p95 → vector bytes → 행 ID다.

| 슬롯 | 선정 조건 |
|---|---|
| S1 | 선행 T8-2 최종 선정 스택. 후속의 서비스 기준선 `baseline_dense`로 반드시 포함 |
| S2 | 선행 정식 Macro MRR@5 선두. S1과 같으면 이유를 합침 |
| S3 | S1과 다른 임베딩 모델 중 가장 높은 행 |
| S4 | S1과 다른 물리 청크 인코딩 정책(native ↔ pooled) 중 가장 높은 행 |
| S5 | S1과 다른 RawPedia 방식(R-A-heading ↔ R-B-window) 중 가장 높은 행 |
| S6 | S1과 다른 GitHub 단위(G-B-curated-unit ↔ G-A-curated-thread) 중 가장 높은 행 |
| S7 | RawPedia 요청 L≤256 중 가장 높은 행: 작은 청크 비교 |
| S8 | RawPedia 요청 L≥1536 중 가장 높은 행: 큰 청크 비교 |

동일 모델/revision·encoder 정책·R/G JSONL SHA 조합은 한 스택으로 합치고 해당 슬롯 사유를 모두 보존한다. 중복 제거 후 5개 미만이면 기존 순서로 미포함 정식 행을 추가해 5개를 채운다. 최종 `N`은 5~8이며, 각 슬롯의 대상 행이 없으면 누락 사유와 선행 탐색 범위를 기록한다. 있는 행을 낮은 점수라는 이유로 빼지 않는다.

`shortlist.json`에 원본 행 ID, 모든 실제 파라미터·지문, 선정 사유, 선행 지표를 저장한다. 구현자는 모델·정책·출처별 방식·작은/큰 L의 대표성이 확보됐는지 검사한다. 명목 L만으로 실제 청크가 길다고 단정하지 않고 본문 token 중앙값/p95와 window 수를 같이 표시한다. 이번 shortlist 밖 스택의 우월 가능성은 결과의 제약으로 남긴다.

## 4. 비교 검색 방식과 반환 계약

### 4.1 등록 행렬

각 스택에 같은 물리 R/G 청크셋으로 다음 세 방식을 실행한다. 기본 행 수는 **`3×N=15~24`**, 실제 지연 관측은 **`3×N×100×3=4500~7200`**이다. warmup·기준선 사전 검사·독립 재현은 이 관측 수와 구분해 기록한다.

| ID | 방식 | 후보 생성·최종 반환 |
|---|---|---|
| `dense` | 선행과 동일한 임베딩 + Chroma HNSW cosine | `D`개 검색 → 선행의 검증된 정렬 → top5 |
| `bm25` | 같은 물리 청크를 lexical 색인으로 검색 | 양의 BM25 점수 후보 최대 `D`개 → 점수 내림차순, 정확한 동점은 chunk ID 오름차순 → top5 |
| `hybrid_rrf` | dense와 BM25의 순위를 RRF로 결합 | 각각 최대 `D`개, chunk ID 합집합 최대 `2D`개 → RRF 순서 → top5 |

`D`는 선행의 최종 검증값으로 고정하고 최종 k는 5다. 하이브리드는 두 검색을 수행하므로 후보 합집합과 비용이 늘어난다. 채널별 후보 수·합집합 수·실제 지연을 보고하여 동일 계산량 실험으로 표현하지 않는다. `D`, BM25 상수, tokenizer, RRF 상수를 결과에 맞춰 조절하지 않는다. 후보 깊이·최종 k·threshold 튜닝은 후속 T15에서 별도 행렬로 등록한다.

### 4.2 BM25 입력·tokenizer·점수식

Python 표준 라이브러리 기반 inverted index로 구현한다. Chroma를 유지하며 별도 검색 서버나 새 모델을 도입하지 않는다. 색인 문서는 **1 physical chunk = 1 lexical document**다. pooled 내부 window를 문서로 늘리거나 반복 header의 term frequency를 누적하지 않는다.

색인 text는 선행과 같은 규칙으로 길이를 제한한 `section_title`과 **저장된 전체 `content`**를 줄바꿈으로 연결한다. 모델 prefix·embedding window별 중복 title·metadata 필드를 추가하지 않는다. 원래 content에 들어 있는 직렬화 구분자는 그대로 보존한다. 원문 payload·source_segments·char_range는 변경하지 않으며 lexical 정규화는 색인용 사본에만 적용한다.

문서와 질문 모두 다음 고정 tokenizer를 사용한다.

```python
normalized = unicodedata.normalize("NFKC", text).casefold()
tokens = re.findall(r"(?:--?)?[a-z0-9]+(?:[._+/-][a-z0-9]+)*|[가-힣]+", normalized)
```

영문 코드·확장자·버전·옵션과 한글 문자열을 token으로 만든다. stemming·stopwords·번역·약어 사전·한글 형태소 분석은 적용하지 않는다. 질문 term은 중복 제거하고 문서 term frequency는 유지한다. `--size`, `foo.arp`, `1.2.3`, `JXL/jxl`, 한글/결합문자 사례를 테스트한다. 모든 질문이 한국어를 포함하고 코퍼스는 주로 영어이므로, 정확한 영문 용어가 적은 질문에서 lexical 검색이 실패할 가능성은 이 고정 조건의 실험 대상이다.

```text
N = 색인 청크 수; dl(d) = 문서 token 수; avgdl = sum(dl) / N
idf(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
BM25(q,d) = sum_t∈unique(q) idf(t) × tf(t,d) × (k1+1)
             / (tf(t,d) + k1 × (1-b + b × dl(d)/avgdl))
k1 = 1.2; b = 0.75
```

상수와 IDF는 [Lucene BM25Similarity 공식 문서](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)를 따른다. 위 점수식 구현을 작은 수작업 예제로 검증한다. `avgdl=0`인 코퍼스는 입력 오류다. 공통 term이 없는 query는 BM25 결과 `[]`이며 0점 문서를 ID 순서로 채우지 않는다. query별 term 수·문서와 공유하는 term 수·lexical 후보 수를 진단 로그에 남긴다. 골드를 보며 번역이나 fallback을 추가하지 않는다.

### 4.3 하이브리드 RRF

```text
rrf(d) = sum_channel 1 / (60 + rank_channel(d))
rank는 각 채널의 확정 후보 목록에서 1부터 시작
채널에 없는 d의 기여는 0; dense/BM25 가중치는 각각 1
정렬: rrf 내림차순 → 정확한 동점이면 chunk_id 오름차순
```

상수 60과 순위 합산 구조는 [Elastic RRF 공식 문서](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)에 근거한 초기 비교 조건이다. 서로 단위가 다른 코사인·BM25 원점수를 합산하지 않는다. 후보 중복은 **같은 chunk ID**만 합치고, 같은 문서의 다른 overlap 청크는 유지한다. BM25가 빈 목록이면 하이브리드의 순서는 dense 순서와 같아야 한다.

### 4.4 공통 인터페이스

내부 호출 계약은 `search(query_text, fetch_k) -> list[SearchHit]`로 두고, 공통 wrapper가 최종 top5와 원문 trace를 구성한다. `SearchHit`에는 `chunk_id`, `rank`, `source_type`, `doc_id`, `section_title`, `content`, `char_range`, `source_segments`, `score`, `score_kind`를 반환한다. hybrid에는 각 채널의 rank/score·cosine distance·RRF score를 추가한다. 범위 필드·원문 URL·body hash는 선행 schema를 그대로 따른다.

`score_kind`는 `cosine_similarity`, `bm25`, `rrf`로 구분하며 다른 score를 동일 threshold로 비교하지 않는다. 최종 정렬/상위 k와 평가 함수는 `run`·`check`에서 공유한다. T9 공통 반환 타입이 이미 존재하면 그 타입에 필요한 trace를 확장하고 중복 인터페이스를 만들지 않는다.

## 5. 지표·문맥 예산·지연 측정

골드 관련성·지표 계산은 [선행 §7](T08_2_execution_plan.md#7-골드-매핑과-평가-지표)의 확정 구현을 재사용한다. 원문/body ID가 일치하고, 청크와 support span의 교집합이 근거 길이의 50% 이상이면 관련 청크다. 청크 순위 기준 첫 관련 rank를 `r`이라 하면 `Hit@k=1[r≤k]`, `RR@5=1/r`(r≤5)이며 관련 청크가 없거나 r>5이면 0이다. 출처별 평균으로 MRR을 계산한다.

| 필수 출력 | 기준 |
|---|---|
| Hit@1/3/5, MRR@5 | RawPedia 80 / GitHub 15 별도, Macro=출처 평균 50:50, Micro=95문항 평균; 반올림 전 값으로 비교 |
| 근거 완전성 | Hit_all@5·FullEvidence_all@5; complex 45개와 출처별 세부. strict coverage는 선행 확정 계약을 그대로 적용 |
| 문맥 예산 2048/4096 | 동일 reference tokenizer로 `section_title + '\n' + content` 계산; 순위대로 **전체 청크**를 넣고 안 들어가면 skip; top6 보충·정답 주변 자르기 없음 |
| 예산 안의 근거 | packing 후 Hit/All/FullEvidence·소비 tokens·skip 건수. 긴 청크의 검색 성공과 답변에 쓸 근거 확보를 구분 |
| 부정 질문 5개 | 양성 Hit/MRR `null`, 분모에서 제외. counterevidence 회수 별도; 답변 거절·환각 평가로 해석하지 않음 |
| 실행 부담 | 평균/중앙값/p95 초/쿼리, vector 차원/bytes, Chroma/lexical 색인 bytes, peak RSS·구축/모델 적재 시간 |

직접 재계산에 필요한 support별 교집합·합집합 위치를 저장한다. 큰 청크라고 관련성 조건을 바꾸거나 문서 ID 일치만으로 성공 처리하지 않는다. 반복 순위가 같을 때 품질의 분모는 고유 양성 95개이며 반복 285개를 독립 표본으로 취급하지 않는다.

CPU·thread·seed=42 및 측정 순서는 선행 검증 조건을 인수한다. 모델/색인 준비 후 동일 첫 10문항 warmup, 100문항 × 3회, batch 1로 측정한다. 다른 벤치마크와 동시에 실행하지 않는다. `perf_counter_ns`로 다음 실제 경로를 계측하며 평가 계산·로그 쓰기는 타이머 밖에 둔다.

- dense: query prefix/tokenize → 실제 encode → Chroma → 최종 결과 구성.
- BM25: query tokenize → inverted-index 점수/정렬 → 최종 결과 구성. 불필요한 embedding 시간을 더하지 않는다.
- hybrid: query 준비 → 실제 encode·dense 검색·BM25 검색 → RRF → 최종 결과 구성. 최초 비교는 한 프로세스에서 순차 호출하고 전체 벽시계를 기록한다.

모든 행은 실제 300개 지연값을 저장한다. 세부 시간·p95 산식은 선행과 같으며 실패 문항을 빼고 집계하지 않는다. 동일 corpus/tokenizer의 BM25 색인은 스택 간 재사용 가능하지만 각 행의 실제 query 검색은 재실행한다. BM25 행의 모델 정보는 청크 생성 조건 추적용이며 `query_encoder_used=false`, `query_encoder=null`을 명시한다. 동일 물리 청크셋의 BM25 점수 차이를 임베딩 모델의 효과로 해석하지 않는다.

## 6. 선정·국소 청킹 재확인·재현

### 6.1 비교·선정 순서

1. S1-dense를 새 작업 위치에서 재검색해 선행 기록과 query별 top5/RR·지표를 대조한다. 주 지표 차이 `1e-9` 이내, vector `allclose(atol=1e-6, rtol=1e-5)`, distance `1e-5` 이내를 적용한다. ANN/동점 문제를 해결하기 전 다른 방식의 개선을 판정하지 않는다.
2. **동일 스택 내** dense/BM25/hybrid 차이로 검색 방식 효과를 보고하고, **같은 검색 방식 내** 스택 차이로 청킹·모델 효과를 보고한다. 여러 축이 다른 행의 차이를 청크 크기 효과로 설명하지 않는다.
3. 전체 등록 행 완료·무결성·재현 통과 후 선행 §8.1과 같은 Macro MRR → Hit → complex FullEvidence → p95 → bytes → ID 순서로 정렬한다. 근접 후보 폭 MRR/Hit 각각 0.01, 출처별 MRR 0.02 및 complex FullEvidence 조건도 그대로 적용한다. 비용 동률 판정의 bytes는 **필요한 float32 vector bytes + 저장된 lexical 색인 bytes**로 고정한다(dense의 lexical=0, BM25의 vector=0). 실제 Chroma/모델/전체 작업 공간 bytes는 별도 보고한다.
4. S1-dense 대비 출처별/complex/예산 지표·지연의 증감, 개선/악화/동률 query ID와 rank 변화를 기록한다. `quality_leader`와 비용을 고려한 `recommended`를 구분하며 근접 폭을 합격선·통계적 유의차로 해석하지 않는다.
5. 선행 선정 계약은 보존하고 별도 `search_selection.json`에 추천을 기록한다. 서비스 반영 시 T15의 문서 ID 기준 context precision·recall 무저하 기준을 검증한다. 이 비교만으로 T15 완료나 서비스 설정 적용을 선언하지 않는다.

### 6.2 검색 방식에 따른 크기·오버랩 상호작용 확인

기본 비교의 추천 방식이 dense와 다르거나 추천 스택이 S1과 다르면 **국소 재측정을 실행**한다. 추천 스택과 해당 방식의 품질 선두를 anchor로 사용하며, 같으면 하나로 합친다. 신규 모델/청킹 정책은 도입하지 않고 선행에서 검증된 정식 행 중 아래 조건을 만족하는 이웃을 찾는다.

- 모델/revision·guard/인코딩 정책·R/G 방식 및 나머지 축을 고정한다.
- R-L, R-O 각각 요청값 기준 가장 가까운 낮은/높은 값 1개씩 비교한다.
- G-B이면 G-L/G-O 각각 가장 가까운 낮은/높은 값, G-A-curated이면 내부 W의 낮은/높은 값만 비교한다. W/O 등 고정 조건을 바꾸지 않는다.
- native 한도를 넘어 pooled로 바꾸는 행은 L의 단독 이웃이 아니다. `O≥L` 등 불가능한 조합, 다른 고정 축을 바꿔야 하는 조합은 제외 사유를 남긴다.

anchor당 중심 포함 G-B 최대 9개, G-A 최대 7개, 두 anchor 합계 **최대 18스택**이다. 중복 제거한 스택마다 **dense와 추천 방식**을 측정하고 추천이 dense이면 한 방식만 실행한다. 최대 36행/10,800개 실제 지연 관측이며 중심·이미 측정한 동일 protocol 행은 참조할 수 있다. 국소 행렬을 파일로 등록한 후 실행한다.

선행에 해당 이웃이 없으면 `unavailable_neighbor`와 검증된 탐색 경계를 기록한다. 미검증 청크를 조용히 생성하거나 검색 방식 개선을 전역 최적점으로 확정하지 않는다. 국소 결과가 새로운 anchor를 추천해도 연쇄 확장을 자동 진행하지 않으며, 추가 확대는 범위·실행 부담을 등록하는 다음 실험이다. trigger가 없으면 `not_triggered`와 추천 근거를 기록한다.

### 6.3 독립 검증과 표현 범위

모든 query/repeat 로그에서 지표·예산 packing·지연 집계를 재계산한다. 추천·품질 선두·차순위·S1-dense를 새 Chroma/lexical 색인에서 다시 검색하고, dense 계열은 선행 ANN 대조를 적용한다. BM25/RRF는 candidate rank와 점수식을 저장 로그 및 작은 수작업 fixture로 검증한다. 입력/정렬이 지표를 바꾸면 원인을 해결하고 공통 protocol 아래 영향을 받는 전체 등록 행을 재실행한다.

결론은 **이번 고정 100문항·대표/국소 후보·고정 D 및 RRF 조건에서의 추천**이다. 동일 질문셋을 선정에 재사용하므로 독립 hold-out 성능·일반화·전역 최적점을 주장하지 않는다. source_group별 득실을 기록하고 통계적 재표집/RAGAS는 기존 T23 범위로 남긴다.

## 7. 후속 구현 산출물과 실행 CLI

아래 파일과 명령은 **후속 실행 시 구현할 계약**이다. 이 플랜 작성 시점에는 생성·실행하지 않는다. root Python 3.14 venv를 사용하고 argparse/docstring/`main()` guard를 유지한다. 실제로 필요한 의존성만 소비 시 설치·기록하며 `requirements.txt`는 추가하지 않는다.

```text
scripts/benchmark_search_strategies.py       # prepare/matrix/run/check/report, 기존 T8 실행기와 분리
src/artagent/retrieval/search_strategies.py  # BM25·RRF·공통 반환 trace; T9 구현과 인터페이스 정합
tests/test_search_strategies.py             # 점수식·순위·누락·무결성·Chroma 통합 회귀
docs/search_strategy_benchmark.json         # 전체 행·선정·재현 정본
docs/search_strategy_benchmark.md           # JSON에서 생성한 비교 보고서
data/retrieval-benchmark/t08-2-search-followup/run-001/
  upstream_snapshot.json                   # 선행 결과·입력·코드 고정
  protocol.json / shortlist.json           # 고정 검색·평가 계약과 대표 스택
  experiment_matrix.json / local_matrix.json
  results.json / search_selection.json
  runs/<experiment-id>.jsonl               # query/repeat별 300행
  chroma/ / lexical/                       # 선행 저장소와 분리한 색인
```

큰 작업 폴더의 gitignore는 후속 구현 때 추가한다. 원문·모델 cache·벡터·Chroma 내부 파일은 보고서 commit에 포함하지 않는다. 보고서는 경로·건수·SHA·재생성 명령을 남긴다. 기존 `docs/chunking_embedding_benchmark.*`를 후속 검색 보고서로 덮어쓰지 않는다.

실행 CLI는 다음 순서다. `$T08_SEARCH_PY`에는 기존 root venv의 Python 실행 파일, `$T08_SEARCH_RUN`에는 위 새 run 경로를 지정한다. `prepare`가 선행 보고서에서 실제 manifest/log 경로를 읽고 확인하며 없는 경로를 추측하지 않는다.

```bash
gzip -dc docs/chunking_embedding_benchmark.json.gz > docs/chunking_embedding_benchmark.json
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py prepare --upstream-report docs/chunking_embedding_benchmark.json --queries docs/search_eval_queries.json --work-dir "$T08_SEARCH_RUN"
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py matrix --work-dir "$T08_SEARCH_RUN" --strategies dense bm25 hybrid_rrf
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py run --work-dir "$T08_SEARCH_RUN" --matrix experiment_matrix.json --device cpu --warmup 10 --query-repeat 3 --resume
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py matrix --work-dir "$T08_SEARCH_RUN" --local-from results.json
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py run --work-dir "$T08_SEARCH_RUN" --matrix local_matrix.json --device cpu --warmup 10 --query-repeat 3 --resume
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py check --work-dir "$T08_SEARCH_RUN" --independent-rebuild
"$T08_SEARCH_PY" scripts/benchmark_search_strategies.py report --work-dir "$T08_SEARCH_RUN" --output docs/search_strategy_benchmark
```

trigger가 없으면 local `run`은 실행하지 않으며 matrix 명령은 `not_triggered`를 기록한다. 상대 matrix 경로는 work dir 기준이다. `--resume`는 protocol/입력/행 ID가 일치하는 완료 행만 인정한다. 실패 행은 오류 로그를 보존하고 재시도하며 건너뛴 뒤 완주로 집계하지 않는다.

JSON 필수 항목은 `schema_version/run_id/status/upstream_snapshot/protocol_hash/input_fingerprints/shortlist/matrix_coverage/experiments/baseline_dense/paired_deltas/local_refinement/quality_leader/recommended/reproduction/limitations`다. 추천은 완료된 행 ID를 참조해야 하며 로그 누락·등록 행 실패 시 `status=incomplete`, `recommended=null`이다.

원시 query log에는 query/repeat/행 ID, query input hash, 두 채널 후보의 전체 순서와 rank/score, RRF 합집합, 최종 top5 및 source_segments, support/counterevidence coverage, 예산 packing·token 소비, 실제 단계별/총 지연을 기록한다. 사용하지 않은 채널은 null/빈 목록으로 표시한다. Markdown은 JSON에서 생성하며 같은 스택의 방식 비교·같은 방식의 스택 비교·국소 L/O/W 곡선·출처별/complex/negative 결과·실패 문항·속도/크기·추천 이유와 탐색 범위를 포함한다.

## 8. 실행 Step 1~6 체크리스트

아래 단계는 모두 미실행이다. 산출물의 검증 통과를 완료 조건으로 삼고 파일 생성만으로 완료 체크하지 않는다.

- [ ] **Step 1 — 선행 결과 대기·인수.** §1.2 착수 게이트를 검사하고 선행 보고서/코드/데이터 hash를 고정하여 snapshot/protocol을 만든다. 의존: T8-2 §15. 완료: 5502행·1,650,600관측·guard/coverage/truncation/재현 검사 통과. 검증: `prepare`의 미완료/변조 입력 거부. 범위: 새 CLI prepare와 거부 회귀.
- [ ] **Step 2 — 대표 등록·dense 기준선 검증.** §3에 따라 대표5~8개/15~24행을 등록하고 S1의 원문→검색→trace→평가 경로로 선행 기준선을 재현한다. 의존: Step1. 완료: shortlist 사유/hash와 RR/지표 일치. 검증: S1-dense의 새 색인100문항 대조. 범위: matrix/dense adapter와 기준선 회귀.
- [ ] **Step 3 — BM25/RRF 구현·경로 검증.** 작은 fixture와 실제 두 출처에서 term→후보→융합→원문 trace를 연결하고 고정 tokenizer/상수를 적용한다. 의존: Step2. 완료: BM25 손계산·빈 결과·RRF 단일 채널/중복/동점·원문 위치·prefix 테스트 통과. 검증: root venv `python -m pytest tests/test_search_strategies.py tests/test_benchmark_embeddings.py tests/test_chunking.py`. 범위: retrieval 모듈·새 테스트·CLI adapter.
- [ ] **Step 4 — 대표 전체 비교·실제 계측.** 3N행의100문항×3회에서 두 채널 후보·문맥 예산·지연을 기록하며 다른 벤치마크와 동시 실행하지 않는다. 의존: Step3. 완료: 15~24행·4500~7200관측·실패0. 검증: `check` 전수 재집계와 같은 스택/방식 비교. 범위: run·로그/check.
- [ ] **Step 5 — 조건부 국소 비교.** §6.2 trigger에 따라 L/O/W를 최대18스택/36행으로 사전 등록하고 실행한다. trigger가 없으면 그 근거를 기록한다. 의존: Step4. 완료: 다른 축 고정·없는 이웃·신규/재사용 행 수 명시. 검증: 국소 paired 표와 신규 행마다300관측. 범위: local matrix·run·국소 보고 표.
- [ ] **Step 6 — 독립 재현·보고·인계.** 추천/선두/차순위/S1을 새 색인에서 재현하고 입력·원시 로그를 검증하여 JSON/MD와T15 입력을 만든다. 의존: Step4/5. 완료: 대표/국소 행렬 완료 또는 명시적not_triggered·추천 재현·같은 질문 그룹의 득실과 예산/비용 기록. 검증: `check --independent-rebuild`와`report`. 범위: check/report·별도 보고서; 선행T8-2 결과 보존.

이번 실험은 원래 질문을 고정한다. T14의 재작성/HyDE가 준비된 뒤 T15에서 변환 출력·hash를 따로 고정하고 같은 후보 설정으로 on/off를 비교한다. BM25에만 번역 질문을 제공하지 않는다. CrossEncoder를 후보 검색 뒤 적용하는 단계는 [SentenceTransformers 공식 retrieve/rerank 절차](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)를 참고하며 모델/후보 깊이/k/threshold를 T15 구현 전에 등록한다. 검색3종 비교 완료는 이러한 후속 검증의 완료를 대신하지 않는다.
