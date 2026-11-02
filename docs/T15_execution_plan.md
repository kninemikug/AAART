# Task 15 실행 플랜 — 리랭킹과 top-k 튜닝

작성일: 2026-10-16. 담당: 김구. 기준 HEAD: `aaa70c0ce`, 작업 브랜치: `kninemikug/T15-rerank`.

이번 산출물은 이 플랜 문서 한 개다. 아래 코드·테스트·평가 스크립트·실험 기록은 **후속 실행에서 작성할 설계**이며, 구현이나 튜닝 완료를 뜻하지 않는다. 실행 단계의 작업 목록도 이 문서에서 관리한다.

## 1. 목표·범위·비목표

목표는 T9 검색에 리랭커를 붙이고 T8-1의 질문·허용 원문 문서 ID를 기준으로 최종 top-k와 임계값을 선택하는 것이다. 적용 전후 문서 ID 기준 context precision·recall을 기록하고, T14 B 기준선의 집계 품질과 개별 순위를 보존한다. 검색 개선이 실제 T17 답변·인용에서도 유효한지 확인한 뒤 검색 설정 v1의 채택 여부를 판정한다.

착수 의존은 T8-1·T9·T14다. 검색 단독 검증 뒤 T13-2에 연결하고, 실제 답변 영향 확인은 T17과 조율한다. T16 완료를 검색 튜닝 착수의 선행조건으로 두지 않는다.

필독 입력은 [Task 15](../tasks/todo.md#task-15-리랭킹top-k-튜닝-a-15), 지정된 [T14 인계 §5](/Users/user/orca/workspaces/AAART/T14-rewrite-hyde/docs/T14_conn_handoff.md#5-t15--검색-튜닝-입력)다. 구현 근거는 현재 저장소의 [동일 인계](T14_conn_handoff.md), [WBS](ART_agentic_wbs.md), [T9 인수 계약](T08_2_t9_handoff.md), [T14 최종 보고서](../data/eval/t14-conn/conn_20261015_pr/report.md)다.

### 1.1 평가 입력의 구분

| 입력 | 구성·역할 | 사용 제한 |
| --- | --- | --- |
| T8-1에서 선택한 Slice 1 고정 15개 표 | WBS의 15개 대조 범위. `Q001·Q004·Q014·Q021·Q033·Q044·Q054·Q063·Q072·Q080·Q084·Q086·Q092·Q093·Q096`. 원질문·허용 원문 ID는 `docs/search_eval_queries.json`, T11 대조는 `docs/T11_execution_records.jsonl` | 검색·답변·인용의 고정 대조용. 양성 14개와 부정 Q096 1개를 구분한다. |
| T14 전체 100개 회귀 입력 | 같은 T8-1 JSON의 전체 질문. RawPedia 양성 80개, GitHub 양성 15개·부정 5개. `ab_records.jsonl`은 A/B 각 100행 | 후보 선택·튜닝·회귀에 사용한다. Slice 1 15개는 이 100개의 부분집합이다. |
| 별도 독립 평가 입력 | `tasks/todo.md`의 독립 질문·원문셋 준비 및 최종 스택 선정 게이트가 소유 | 이번에 새로 만들지 않는다. 질문·문서/스레드 단위 분리와 기대 행동을 별도로 고정해야 한다. |

T8-1 원본은 현재 100문항이며, 15문항은 그 안에서 고정한 Slice 1 대조표다. 두 입력의 표본 수를 합산하지 않는다. 기존 100개와 그 부분집합을 **독립평가셋·독립 홀드아웃으로 표기하지 않는다.** 반복 실행도 독립 표본 수를 늘리지 않는다. 골드 ID·근거 절·질문별 기대 행동은 평가에만 사용하고 검색·리랭크·실제 답변 입력으로 넣지 않는다.

범위는 `src/artagent/retrieval/`의 후보 검색·재정렬·선택 경계와 `src/artagent/graph/search.py`의 최소 연결 설계다. T9의 Chroma·임베딩·청킹·원문 스냅샷은 고정한다. 임베딩/청킹 교체, 별도 dense/BM25/RRF 검색 방식 실험, 답변 생성 모델 선정, T16 구현, 코퍼스 확대, 프로필 생성·렌더링, `rtengine/`·`rtgui/` 변경은 비목표다. 아래 lexical 후보는 **T9가 가져온 후보만 재정렬**하며 새 검색 스택을 만들지 않는다.

### 1.2 확인한 원기록

`data/eval/t14-conn/conn_20261015_pr/ab_records.jsonl`은 현재 위치에 존재하며 200행이다. 파일 SHA-256은 `96f11d6d63f41896c1b8cf028f52b0932d121d3d5ad4093c69a33802ea0dfd0e`다. 따라서 원기록 부재를 가정하지 않는다. 후속 실행 위치에서 누락되면 같은 해시의 인수 파일을 확보할 때까지 기준선 재현을 보류하며 결과를 추정하지 않는다.

| 필드·경로 | 인수·활용 방식 |
| --- | --- |
| `query_id`, `condition`, `query_original`, `rewrite_enabled`, `hyde_enabled` | `(query_id, condition)`으로 A/B를 조인한다. |
| `gold_support_doc_ids`, `is_negative`, `counter_evidence_doc_ids` | 질문 원본 JSON과 전수 대조한다. 부정 질문은 지원 골드와 반증 근거를 혼합하지 않는다. |
| `first_gold_rank`, `hit_at_5`, `mrr_at_5` | 원문 ID에서 다시 계산해 저장값과 대조한다. `null`은 상위 5개 미도달이며 전체 색인 부재를 뜻하지 않는다. |
| `hits`, `search_observations[].hits` | 반환된 SearchHit 전체 목록이다. `rank`, `chunk_id`, `distance`, `distance_text`, `content`, `content_sha256`, `source_group_id`, `source_segments`, `original_metadata`를 보존한다. |
| `search_observations[].search_input` | 실제 검색 문장·변환·보존 검사 조건을 인수한다. |
| `retrieval.hits`, `search_observations[].evidences` | 실제 세그먼트 Evidence와 `source_location`·`product_scope`를 인수한다. |
| `service_error`, `answer_test_double`, `capabilities_test_double` | 기술 오류와 대역 사용 여부를 판정한다. T14 답변은 대역이므로 실제 답변 품질 증거로 쓰지 않는다. |

이 파일의 “전체 검색 결과”는 **당시 반환된 top5 SearchHit 전체**다. Chroma 내부 후보 10개 전부나 20·40개 후보가 저장된 것은 아니다. 확대 후보는 같은 스냅샷에서 새로 조회하고 별도 실행으로 기록해야 한다. 원문 위치는 `source_segments`와 Evidence의 `source_location`에 있으며, GitHub 그룹 ID와 본문·댓글의 실제 원문 ID를 구별한다.

## 2. 리랭커 선정

### 2.1 후보와 비교 기준

| 후보 | 지연·비용 측정 계획 | 오프라인성 | 라이선스·언어·한계 |
| --- | --- | --- | --- |
| R1: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | 동일 CPU에서 후보 수·윈도우 수별 cold load, warm p50/p95, 최대 메모리를 측정한다. 로컬 실행은 외부 호출료가 없으며 계산 비용은 별도다. | 가중치·토크나이저를 확보한 뒤 로컬 실행. revision·파일 해시를 고정한다. | Apache-2.0, multilingual MiniLMv2 기반. 한국어 원질문과 영어 재작성 양경로의 실제 적합성은 검증 대상이다. [공식 모델 카드](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1) |
| R2: `cross-encoder/ms-marco-MiniLM-L6-v2` | 6층 경량 대조 후보. R1보다 빠를 가능성은 실측으로 확인하며 공개 GPU 처리량을 로컬 CPU 지연으로 대입하지 않는다. 외부 호출료 없음. | 같은 로컬 고정·오프라인 재실행 조건 | Apache-2.0, 영어 검색용. rewrite off의 한국어 입력에 대한 품질 위험이 있다. [공식 모델 카드](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) |
| R3: lexical BM25 재정렬 | 후보 텍스트의 어휘 점수 계산 시간·메모리를 같은 장비에서 측정한다. 외부 호출료·가중치 다운로드 없음. | 완전 로컬 | 기존 저장소 GPL-3 범위의 자체 구현을 설계한다. 어휘 불일치·한영 교차 검색에 취약하다. 토큰화·IDF 통계·상수를 고정한다. |

R1을 우선 검증 후보로 둔다. on/off 양경로를 다루는 multilingual 후보라는 이유이며, 선정 완료를 뜻하지 않는다. R2는 경량 대조, R3는 의존성과 연산량이 작은 대안이다. BM25의 통계는 고정 코퍼스 전체에서 구하고 후보 풀마다 다시 적합하지 않는다. 이번 문서 작성에서는 패키지 설치·가중치 다운로드를 수행하지 않는다. 소비 단계에서 Python 3.14 루트 venv와 현재 설치 버전의 로딩 호환성을 확인하고 필요한 설치만 기록한다.

선정 순서는 ① 원문·필터·제품 범위 보존 및 오류 0건, ② §5~6의 precision·recall·집계·개별 순위 게이트, ③ §4의 복구 실적, ④ T17 영향, ⑤ 지연·비용 순이다. 품질이 같은 후보는 warm p95, 메모리, 설정 복잡도, 작은 k 순으로 비교한다. 운영 지연 상한은 아직 확정된 입력이 없으므로 지연을 측정하지 않고 “빠름”으로 판정하지 않는다. 상한을 추가한다면 본 격자 실행 전에 수치와 장비를 protocol에 등록하고, 결과 확인 후 유리하게 바꾸지 않는다. 합격 후보가 없으면 B를 유지하고 선정 보류한다.

### 2.2 입력 길이와 점수 계약

T9의 RawPedia 물리 청크는 `R-C-heading-window-t8192-o64`라서 리랭커의 한 쌍 입력 길이를 넘을 수 있다. 첫 부분만 잘라 채점하면 뒤쪽 근거를 잃는다. T9 청크·벡터는 유지하고, **채점용 윈도우만** 만든다. 후보의 모든 실제 세그먼트를 리랭커 토크나이저의 유효 pair 한도 안에서 순회하며 겹침 64토큰, 제목 최대 32토큰을 초기 정책으로 둔다. 질의·특수 토큰을 뺀 본문 예산, 실제 token 범위·원문 좌표·윈도우 수를 기록하고 원문 누락 0을 확인한다. 질의가 한도를 넘으면 조용히 자르지 않고 설정/입력 오류로 처리한다.

윈도우 점수의 최댓값을 청크 점수로 삼는 `max_window_v1`을 우선 고정한다. 긴 청크의 기회 증가 편향을 위험으로 기록한다. 최상위 윈도우만 Evidence로 보내거나 원문을 요약하지 않는다. 선택된 SearchHit의 모든 기존 세그먼트를 유지한다. 문맥 추출·패킹 변경이 필요하면 별도 조건·T17 검증으로 분리한다.

Cross-encoder는 원시 logit을 명시적으로 얻은 뒤 sigmoid를 **한 번만** 적용해 `selection_score∈[0,1]`로 만든다. 현재 라이브러리의 기본 activation을 추정하지 않고 확인한다. 이 값은 보정된 정답 확률이 아니다. lexical은 고정된 비음수 BM25 점수 `s`에 `s/(1+s)`를 적용한다. 후보별 변환·원시 점수·revision을 기록하며 모델 간 점수의 같은 숫자를 같은 신뢰도로 해석하지 않는다. 질의별 min-max 정규화·골드 기반 점수 보정은 하지 않는다. [CrossEncoder 공식 API](https://sbert.net/docs/package_reference/cross_encoder/model.html)의 activation·길이·로컬 로딩 계약을 구현 시 설치 버전과 대조한다.

## 3. 부착 위치와 인터페이스 설계

### 3.1 현재 구조와 변경 경계

| 현재 파일 | 확인한 역할 | 후속 변경 원칙 |
| --- | --- | --- |
| `retrieval/__init__.py` | 인코더·저장소·규격·원문 도구 공개 | 필요한 새 리랭크 진입점만 추가 노출한다. |
| `retrieval/embedding.py` | 고정 CPU 인코더, 청크 윈도우 평균, 단일 질의 임베딩 | 기존 모델·정규화·벡터 차원·질의 길이 검사를 보존한다. |
| `retrieval/store.py` | Chroma 적재·갱신·제외·검색, ready 상태·계약 검사, 출처/지정 글 필터 | 후보 반환 경계만 추가하며 적재·색인 계약은 보존한다. |
| `retrieval/types.py` | `RetrievalSpec`, 불변 `SearchHit`, `SourceKey`, `IndexReport` | 원문·거리 필드를 재활용해 리랭크 점수를 덮어쓰지 않는다. |
| `retrieval/provenance.py` | 문서/청크 ID, 원문 세그먼트·문자/바이트·해시 검증, Chroma 메타데이터 변환 | 기존 검증과 역추적을 유지한다. |
| `graph/search.py` | T14 입력 준비 → `store.search` → `search_hits_to_evidences` → `RetrievalBundle` | 두 검색 노드가 같은 선택 경로를 호출하도록 최소 연결한다. |

현재 `RetrievalStore.search(...)`는 `source_key`·`source_type`·`source_group_ids`의 교집합과 `excluded=False`를 적용한다. `collection.get(limit=10)`으로 조회 수를 제한하고 Chroma에서 최대 10개를 받은 뒤 `(round(distance,6), chunk_id)` 오름차순으로 정렬하여 top5만 반환한다. 확대 시 **조회용 limit과 최종 슬라이스 양쪽**을 다루어야 하며, top5 반환값만 재정렬해서 k=20을 구현했다고 해서는 안 된다.

후속 설계는 `store.search_candidates(query, session, *, candidate_k, source_key=None, source_type=None, source_group_ids=None) → list[SearchHit]`를 추가하고 기존 `search`는 후보 10·최종 5의 호환 경로로 유지하는 방식이다. 필터 적용 뒤 후보 수가 부족하면 있는 만큼 반환한다. 빈 `source_group_ids=[]`는 계속 정상 빈 결과이며 범위를 전체로 넓히지 않는다. 확대 경로도 동일한 계약·상태·해시 검사를 거친다.

최소 새 설계 파일은 `src/artagent/retrieval/rerank.py`다. 이곳에 `rerank_candidates(search_query, hits, reranker) → 순서·점수 레코드`와 top-k·임계값 선택 경계를 둔다. 출력 레코드는 원래 SearchHit, 원래 dense rank, rerank rank, 최종 rank, raw/selection score, 윈도우 관측값을 가진다. 최종 선택 순서는 `(-selection_score, dense_rank, chunk_id)`로 고정한다. 기존 SearchHit의 원문·거리·원래 rank를 변조하지 않고 최종 rank는 별도 레코드에서 관리한다. 이 경로들은 구현 예정이며 현재 존재하는 API로 취급하지 않는다.

### 3.2 실행 순서와 팩터리 인자

```text
원질문·확정 문맥 / 현재 항목
  → T14 prepare_search_input (rewrite on 또는 off, HyDE off)
  → T9 출처·지정 글 필터 검색 (candidate_k)
  → 리랭크 (검증된 search_query + 실제 원문 후보)
  → 최종 top-k 컷 (청크 단위)
  → selection_score >= min_score 필터
  → search_hits_to_evidences (선택 청크의 모든 원문 세그먼트)
  → RetrievalBundle → T17 답변·인용
```

top-k 컷 이후 임계값을 적용하고 빈자리를 다른 후보로 채우지 않는다. `min_score=None`은 필터 미적용, `0.0`은 명시적 하한이다. 빈 결과는 정상 빈 bundle이며 답변 상태는 T17이 판단한다. 리랭크 로딩·점수·비유한 값·계약 오류는 기존 그래프 경계의 `SEARCH_UNAVAILABLE`로 반환하고 관측 상세에 rerank 단계를 남긴다. 실패를 빈 결과나 성공으로 바꾸지 않는다. T14 보존 실패는 계속 `REWRITE_FAILED`이며 검색 0회다. 실패 시 자동 dense 복귀는 두지 않고 §6의 명시적 설정 롤백으로 처리한다.

`create_search_nodes`와 두 하위 검색 팩터리에 다음 **선택적 keyword-only 인자**를 함께 전달하는 설계다. 기존 `store`, `session`, `generate`, `snapshot_ref`, `observe` 계약은 유지한다.

| 인자 | 기본값·검증 | 용도 |
| --- | --- | --- |
| `rewrite_enabled` | 기존 `False` 유지 | 채택 기준선과 후보는 `True`를 명시. off 대조도 유지한다. |
| `hyde_enabled` | 기존 `False` 유지 | 이번 모든 조건에서 off. 가상 문서를 근거로 넣지 않는다. |
| `reranker` | `None` | `None`은 재정렬 없음. 주입 객체가 ID·revision·채점 계약을 제공한다. |
| `candidate_k` | `10`, 양의 정수 | dense 후보 수. `top_k <= candidate_k`를 검사한다. |
| `top_k` | `5`, 양의 정수 | 임계값 적용 전 최종 청크 수 상한. |
| `min_score` | `None`, 설정 시 0~1 | 리랭커 없는 조건에 숫자 임계값을 주면 설정 오류다. cosine distance와 혼용하지 않는다. |

기존 호출은 결과·기본 재작성 off·오류 의미가 같아야 한다. B 호환 호출은 `create_search_nodes(..., rewrite_enabled=True, hyde_enabled=False, reranker=None, candidate_k=10, top_k=5, min_score=None)`다. 후보는 이 호출의 리랭커·후보 수·k·임계값만 명시적으로 바꾼다. on/off 모두 동일 리랭크 경로를 쓰고 각 경로의 `search_query`로 채점한다. off에서 추가 번역이나 숨은 재작성을 하지 않는다. `observe`에는 후보 전체·단계별 순위/제외 이유·선택 설정·오류·지연을 추가하되 bundle의 필드 구조는 유지한다.

### 3.3 T13-2 연결 전후

연결 전에는 고정 질문과 같은 요청·제약으로 T14 입력 준비 → T9 → 리랭크 → bundle을 직선 실행하고 T17 `answer_standalone`에 전달한다. 전체 T11 `run_pipeline`을 호출하여 검색을 중복 수행하지 않는다. 연결 후에는 같은 팩터리 결과를 `create_router_graph(node_overrides=...)`의 `SEARCH_RAWPEDIA`·`SEARCH_GITHUB`에 주입하고 실제 `ANSWER`와 비교한다. T13-2의 경로·전이·T16 예산을 T15에서 재설계하지 않는다.

검색 노드는 `request`, `decision.plan`, `cursor`, `research_count`를 변경하지 않는다. 라우터 20개 고정 경로를 on/off 각 20개씩 확인하고, 출처·지정 Issue/Discussion 필터·제품 범위·오류·혼합 항목 상태가 유지되는지 검사한다. k는 SearchHit 수이며 `RetrievalBundle.hits`의 Evidence 수가 아니다. Evidence 목록을 다시 k개로 자르지 않는다.

## 4. top-k·임계값 튜닝 격자

### 4.1 조건과 단계적 축소

| 축 | 1차 범위 | 고정·비교 규칙 |
| --- | --- | --- |
| 리랭커 | R1·R2·R3 | 품질 합격 전 후보 제외 이유를 기록한다. |
| dense 후보 수 `candidate_k` | 20, 필요 시 40 | 기준선 10과 구별한다. 부족한 출처/지정 글에서는 실제 반환 수를 기록한다. |
| 최종 `top_k` | 3·5·10·20 | 후보 수를 초과하는 설정은 금지한다. |
| `min_score` | 미적용, 0.0·0.2·0.5·0.7 | 후보별 점수 변환을 고정한다. 미적용과 0.0은 별도 조건이며 결과 중복은 명시한다. |
| 재작성 | on / off | HyDE는 항상 off. 원기록의 검증된 변환을 정확한 입력·설정으로 재생해 검색 튜닝 변수를 분리한다. |

전수 교차 대신 다음 순서로 줄인다. 질문별 예외 k·임계값이나 골드 문서 강제 삽입은 금지한다.

1. **기준선 재현:** B와 A의 기존 10→5를 재현한다. 확대 후보의 무리랭크 20→5도 진단 조건으로 남겨 후보 풀 효과와 리랭커 효과를 분리한다.
2. **부착 검증:** 15개 고정표와 집중 집합으로 R1/R2/R3의 20→5·임계값 미적용을 확인한다. 실행 불가·필터/원문 위반 후보만 여기서 제외한다. 집중 표본 점수가 낮다는 이유만으로 전체 평가를 생략하지 않는다.
3. **후보 비교:** 실행 가능한 모든 리랭커의 20→5·미적용을 전체 100개 on/off로 측정한다. §6의 검색 품질 G2·G3을 우선 충족한 후보 중 최대 2개를 남긴다. 미달 후보의 점수·제외 이유도 저장한다. 통과 후보가 없으면 미달 사유에 따라 k/임계값 탐색까지 수행하고 성급히 최종 탈락시키지 않는다. 이 단계에서 실제 T17 검증 G5 통과를 요구하지 않는다.
4. **격자 튜닝:** 남긴 후보에 k 4종 × 임계값 5종, 후보당 20조건을 전체 100개 on/off로 적용한다. 단계 3에서 모두 미달이면 실행 가능한 후보 전부에 이 격자를 적용한다. 같은 후보 풀의 원시 점수는 한 번 계산해 컷/필터만 재생할 수 있으나 이를 새 실측 지연 표본으로 세지 않는다.
5. **후보 풀 확대:** 집중 3건의 골드가 20개 후보에 없거나 20개에서 합격 조건이 없을 때만 40개를 조회하고 같은 격자를 수행한다. 발동/미발동 근거를 기록한다. 40개에도 없으면 색인·필터·질의·청크 범위를 진단하여 미해결로 남긴다. 이 작업에서 임베딩·청킹을 몰래 바꾸지 않는다.
6. **최종 재현:** 합격 후보를 고정한 뒤 캐시된 최종 순위 재생과 구별하여 실제 검색·채점 전체 경로를 3회 실행한다. warm 반복과 cold load를 분리하고 질문별 성공/오류·순위·p50/p95를 기록한다. 이후 전체 회귀와 실제 T17 대조를 수행한다.

### 4.2 집중 복구와 개별 순위 목표

| 질문 | A 최초 골드 순위 | B 최초 골드 순위 | 복구 목표 |
| --- | ---: | ---: | --- |
| Q024 | 상위5 미도달 | 상위5 미도달 | 최종 선택 결과의 상위5에서 허용 원문 도달 |
| Q030 | 1 | 상위5 미도달 | 상위5 도달 필수 복구 목표, 1위 회복 우선 |
| Q070 | 상위5 미도달 | 상위5 미도달 | 최종 선택 결과의 상위5에서 허용 원문 도달 |
| Q017·Q026·Q033·Q041·Q055·Q057·Q072 | 각 1 | 각 2 | B 대비 악화 0, 각 A 순위 회복 목표 |
| Q025 | 2 | 3 | B 대비 악화 0, 2위 이내 회복 목표 |
| Q053 | 1 | 3 | B 대비 악화 0, 1위 회복 목표 |

A 대비 저하 10개는 `Q017·Q025·Q026·Q030·Q033·Q041·Q053·Q055·Q057·Q072`다. Q030은 미도달 3개와 중복하므로 집중 집합의 합집합은 12개다. 이 12개의 후보 풀 내 도달, 리랭크 전후 순위, 컷 탈락, 임계값 탈락, 최종 원문 위치를 모두 남긴다. 큰 k에서 6위 이하에 넣은 결과를 “상위5 복구”로 세지 않는다.

3개 미도달의 복구와 10개 A 순위 회복은 개선 목표이며, B 대비 비저하 합격과 별도 열로 판정한다. 목표 미달을 완전 복구로 표시하지 않는다. §6의 안전 게이트를 통과해도 집중 복구 잔여가 있으면 개선 범위·잔여 원인·후속 소유를 명시하고 최종 채택 판정을 보류하거나 제한된 검색 개선으로 인계한다. 수치 게이트를 낮추어 완료 처리하지 않는다.

## 5. 평가 지표·스크립트 설계

### 5.1 문서 ID 기준 context precision·recall

질문 q의 허용 지원 원문 ID 집합을 `Gq = gold_support_doc_ids`라 한다. 선택된 청크의 **실제 `source_segments[].doc_id`**를 합쳐 중복 제거한 집합을 `Dq`라 한다. RawPedia 문서 ID, GitHub 본문·댓글 ID를 사용하며 `source_group_id`를 지원 원문으로 간주하지 않는다. 같은 문서의 여러 청크/세그먼트를 여러 정답으로 세지 않는다.

- `context_precision(q) = |Dq ∩ Gq| / |Dq|`. 양성 질문에서 `Dq`가 비면 0이다.
- `context_recall(q) = |Dq ∩ Gq| / |Gq|`. 양성 95개에 적용한다.
- 전체 및 RawPedia·GitHub별 macro 평균을 기본 지표로 사용하고, 분자·분모 합산의 micro 평균도 병기한다. Slice 1은 양성 14개를 따로 집계한다.
- 부정 Q096~Q100은 지원 골드가 비므로 지원 precision·recall은 N/A로 둔다. 해당 질문의 `counter_evidence_doc_ids`에 대해 별도 반증 precision·recall·도달 여부를 기록한다. 부정 질문을 0 또는 1로 넣어 양성 평균을 바꾸지 않는다.

측정 지점은 후보 풀, 리랭크 후 컷 전, 최종 선택 후 bundle, 실제 T17 프롬프트의 전달 문맥으로 나눈다. 공식 적용 전후 비교는 **최종 bundle** 기준이며, 후보 풀 지표로 대체하지 않는다. 현재 설계에서는 선택 청크의 모든 세그먼트를 보내므로 bundle과 전달 문맥의 ID 집합이 같아야 한다. T17 문맥 한도로 차이가 나면 누락 ID·텍스트 범위·이유를 기록하고 전달 문맥 지표를 다시 계산한다. 원문 ID 도달은 근거 절·필요한 사실 도달을 보장하지 않으므로 고정표의 근거 절·문자/바이트 위치도 대조한다.

보조 지표는 Hit@5, MRR@5, 최종 Hit@k/MRR@k, 모든 허용 ID 도달률, 최초 골드 청크 순위, 반증 도달, 빈 결과율, 실제 후보/선택 청크 수·Evidence 수·토큰/문자 수, 기술 오류율, 단계별 지연·메모리·외부 호출 비용이다. 최초 골드 순위는 T14와 같은 청크 순위 단위로 계산하고 그룹/세그먼트 ID 매핑을 대조한다. 원기록의 순위와 새 최종 rank를 별도 보관한다.

### 5.2 기준선과 적용 전후 표 양식

아래 precision·recall은 문서 작성 중 **기존 A/B 기록의 원문 세그먼트 ID만 재집계한 참고값**이며 새 검색·튜닝 결과가 아니다. 후속 스크립트가 동일 정의·분모·원기록 해시로 재집계해야 확정한다. Hit/MRR은 T14 기록값이다. 후보 행의 `—`는 미측정이며 0점이 아니다.

| 조건 | 범위·양성 n | 문서 precision | 문서 recall | Hit@5 | MRR@5 | k / 임계값 | 판정 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| B0: rewrite on, 무리랭크 | 전체 95 | 0.267368421 | 0.968421053 | 0.968421 | 0.880702 | 5 / 미적용 | 고정 기준선 |
| B0 | RawPedia 80 | 0.215833333 | 0.962500000 | 0.962500 | 0.858333 | 동일 | 고정 기준선 |
| B0 | GitHub 15 | 0.542222222 | 1.000000000 | 1.000000 | 1.000000 | 동일 | 고정 기준선 |
| B0 | Slice 1 양성 14 | 0.320238095 | 1.000000000 | 재집계 | 재집계 | 동일 | 고정 대조 |
| A0: rewrite off, 무리랭크 | 전체 95 | 0.259473684 | 0.905263158 | 0.905263 | 0.861754 | 5 / 미적용 | off 대조 기준 |
| Cxx: 후보 ID·revision | 전체/출처/Slice 1 각각 | — | — | — | — | 후보 설정 | 미측정 |

후속 보고서는 위 표를 한국어 조건명으로 채우고, 원시 분수와 충분한 정밀도를 유지한다. 각 조건에 지연 p50/p95·메모리·비용/제공 여부·오류 건수·세 집합의 크기를 추가한다. 반올림 표시값으로 비저하를 판정하지 않는다.

질문별 표는 `query_id | source_type | gold IDs | counter IDs | A rank | B rank | 후보 내 rank | rerank rank | 최종 rank | 최종 IDs | precision 전/후 | recall 전/후 | 탈락 단계 | 원문 위치 | T17 상태·인용 변화 | 판정`으로 고정한다. 미도달은 null로 저장하고 순위 비교에서는 무한대로 취급한다.

### 5.3 평가 실행기와 재실행 명령

후속 평가 스크립트 경로는 `scripts/eval_t15_rerank.py`다. `argparse`, docstring, main guard를 사용한다. 아래는 **신규 CLI 설계**이며 현재 스크립트나 플래그가 구현됐다는 뜻이 아니다. 현재 문서 작성에서는 실행하지 않는다. 저장소 루트에서 기존 Python 3.14 venv를 사용하고 새 `requirements.txt`는 만들지 않는다.

```bash
# 입력 해시·스냅샷·격자·지표·분모·선정 규칙 사전 고정
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py prepare --queries docs/search_eval_queries.json --t14-run data/eval/t14-conn/conn_20261015_pr --reference docs/T08_2_t9_handoff_reference.json --output-dir data/eval/t15-rerank/plan_v1

# §4의 단계적 격자 실행; 제외/확대 사유와 조건별 로그 보존
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_v1/protocol.json --phase grid --output-dir data/eval/t15-rerank/grid_v1

# 고정한 후보의 전체 100개·Slice 1·경로·반복 재현
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_v1/protocol.json --phase regression --selected-condition data/eval/t15-rerank/grid_v1/selected_condition.json --output-dir data/eval/t15-rerank/regression_v1

# 실제 T17 비교. 입력/프롬프트·응답·검토는 별도 실행 폴더로 저장
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_v1/protocol.json --phase t17 --selected-condition data/eval/t15-rerank/grid_v1/selected_condition.json --output-dir data/eval/t15-rerank/t17_v1

# 생성·검색 없이 원문/해시·전수 기록·분모·수동 검토·게이트 재계산
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py check --run-dir data/eval/t15-rerank/regression_v1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/eval_t15_rerank.py check --run-dir data/eval/t15-rerank/t17_v1
```

계획하는 기록은 `protocol.json`(입력·기준선·조건·코드/환경 지문), `records.jsonl`(질문×조건×반복의 전체 후보·단계별 선택·위치·지표), `selected_condition.json`(설정·선정/보류 이유), `report.md`(비교·게이트)다. 기존 T14 기록은 덮어쓰지 않는다. 중복/누락 질문, 후보 밖 ID, 순위/점수 불일치, 근거 해시 위반은 검증 실패로 처리한다. 캐시 재생, 실측, 실패/재시도, 미측정 비용을 구별하며 비용 미제공을 0원으로 채우지 않는다.

T23 RAGAS는 별도 단계로, 고정100개의 검색 문맥·실제 답변·인용을 받아 context precision/recall/faithfulness를 보고한다. T15의 문서 ID 집합 기반 지표와 RAGAS 채점을 같은 이름으로 혼합하지 않고 `doc_id_context_precision/recall`로 정의·분모를 전달한다. T15에서 기대 답변을 새로 작성하거나 faithfulness 완료를 선언하지 않는다. 최종 스택 선정 게이트의 설정이 고정된 뒤 T23에 전달하며, 100문항의 독립성 한계도 남긴다.

## 6. 기준선·회귀 게이트

### 6.1 고정 기준선과 조건 분리

기준선 B0는 T14 B의 `rewrite_enabled=True`, `hyde_enabled=False`, `literal_preservation_v3`, 후보 10→최종5, 리랭커 없음·임계값 미적용이다. A0는 같은 조건에서 rewrite off인 대조다. §4의 후보 확대만 한 조건·리랭커 조건·k/임계값 조건을 각각 별도 ID로 남긴다. B0를 새 k의 무리랭크 조건으로 교체하지 않는다.

임베딩은 `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Chroma collection `art_retrieval_t09_v1`, RawPedia 141개·GitHub 13개 물리 청크를 고정한다. T9 reference SHA는 `2c7081ba6a7c37b00735b0be2ef362f5b0c2a86cd41fe97bbb2a3b5ebdc195bc`, T14 실행 전후 스냅샷 지문은 `09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6`다. 스냅샷 파일의 바이트 해시와 저장소 내용 지문을 혼동하지 않는다.

protocol에는 질문/골드·T11 고정표·T14 A/B·생성 이벤트·스냅샷·source manifest의 해시, 코드 commit/파일 해시, Python·라이브러리·장비·스레드·seed, 필터, 준비된 질의/보존 정책, 후보 수, 리랭커 revision·토크나이저·윈도우/activation, k·임계값을 기록한다. 정답을 보기 위한 수집/재색인은 허용하지 않는다. 기준선 재현이 다르면 원인을 먼저 해결하고 새 조건과 이전 기준선을 섞지 않는다.

### 6.2 필수 게이트와 롤백

| 게이트 | 검증·합격 기준 | 실패/미확인 시 |
| --- | --- | --- |
| G0 입력·기준선 | 같은 입력·스냅샷의 A0/B0 top5 ID·거리 정렬·원문 위치·지표 재현. 원기록 해시 및 양성95/부정5 분모 일치 | 격자 판정 중단, 조건 불일치 해결 |
| G1 부착 계약 | 기본 호출 호환, on/off 각20개 라우터 경로 유지, 출처·지정 글·제외·원문 해시/좌표·product_scope 위반0. 빈 결과·오류 구별, state 보존 | 후보 부적격, B0 유지 |
| G2 집계 비저하 | 전체95·RawPedia80·GitHub15 및 Slice 1 양성14 각각 문서 precision/recall이 B0 이상. 고정 Hit@5/MRR@5도 B0 이상. off 후보도 A0에 대해 같은 비교 | 하나라도 하락하면 탈락. 큰 k의 Hit@k로 @5 저하를 상쇄하지 않음 |
| G3 개별 회귀 | 양성95개에서 B0의 각 최초 골드 순위보다 악화0건. off는 A0에서 도달했던 질문의 순위 악화0건. 부정5개 반증 도달을 B0/A0보다 잃지 않음 | 전체 평균 상승만으로 통과시키지 않음 |
| G4 고정표·복구 보고 | 전체100개 on/off를 빠짐없이 재실행하고 Slice 1 15개를 별도 대조. 집중3개·순위저하10개의 전후/원인·목표 달성 여부, 원문 근거 절 도달을 기록 | 누락은 PENDING. 미해결 복구 목표는 잔여로 명시하고 최종 채택 범위를 보류 |
| G5 재현·T17 영향 | 고정 후보3회 실제 재현, §7의 실제 답변·인용·제품 범위 검증 및 필수 수동 검토 완료 | T17 확인 전 검색 실험 통과까지만 기록. 운영 채택/전체 완료는 보류 |

순위는 최종 컷/임계값 통과 후 청크 기준이다. B0의 null은 무한대이므로 새 후보의 null을 “개선”으로 세지 않는다. G3는 B 대비 새 퇴행을 막고, A 순위 회복은 §4의 10개 개선 목표로 따로 보고한다. 지표 비교는 원시 분수로 하며 수치 변동 허용으로 품질 저하를 덮지 않는다. 입력·원문·필터 위반이나 기술 실패를 평가 분모에서 빼지 않는다.

실패 후보는 새 기능 주입을 해제하고 B0 명시 설정으로 되돌린다. Chroma·원문은 바꾸지 않았으므로 재색인 없이 돌아갈 수 있어야 한다. 후보 결과·실패 원인은 보존하고 삭제/덮어쓰지 않는다. 기술 오류에서 자동 재작성·재검색이나 임계값 완화로 결과를 보충하지 않는다. 게이트 판정은 `PASS`·`FAIL`·`PENDING`으로 구분하고 누락된 증거를 통과로 처리하지 않는다.

## 7. T17 답변·인용 영향 확인

### 7.1 추적 경로와 비교 범위

`query_id + condition_id + repeat + run_id`로 후보/최종 rank → SearchHit → 실제 Evidence → `RetrievalBundle` → 실제 전달 프롬프트의 인용 ID → `AnswerResult` → 공개 Citation → 원문 파일·위치를 연결한다. bundle에 없는 rank/거리를 복원했다고 적지 않는다. bundle·최종 프롬프트 해시, 생성 제공처·모델 식별값/설정·프롬프트 버전·요청/원응답·호출/시간/비용·오류, 수동 검토자를 기록한다. 인용 ID는 문맥 순서에 따라 달라질 수 있으므로 `[C1S1]` 문자열 일치 대신 실제 doc_id·URL·원문 위치·주요 사실을 대조한다.

T17 단독 입력은 현재 항목의 **원질문**·동일한 확정 문맥/제약과 각각의 bundle이다. T15 조건 외에 답변 생성 설정·프롬프트·문맥 정책을 함께 바꾸지 않는다. T17 내부 검색/재작성은 0회이며 기존 `run_pipeline`으로 다시 검색하지 않는다. 실제 T13-2 접합 뒤에는 같은 검색 팩터리와 `create_answer_node`를 사용한 결과도 확인한다.

필수 실제 비교 질문은 Slice 1 15개, 집중 집합12개, Q010·Q077, 부정 Q096~Q100의 합집합이다. 중복 제거 시 **31개**이며 각 질문을 B0와 최종 후보로 짝지어 비교한다. 그 밖의 질문도 최종 문서 집합·순서·선택 범위가 B0에서 바뀌었으면 실제 답변 비교에 추가한다. 전체100개 검색 회귀는 모든 경우 필수다. 비용/시간 부족으로 실제 답변 비교가 빠지면 G5를 PENDING으로 남긴다.

T11 고정15 기록과 T17의 검증된 기존 실행도 대조 자료로 보존한다. 현재 HEAD의 [T17 보완 플랜 §10](T17_fix_plan.md#10-재리뷰-보완-및-실제-평가-완료-2026-10-16) 및 `data/eval/t17-answer/run_20261015_v3_resumed/`는 단독 모듈 검증 기록이다. 이전 T17 답변을 정답으로 삼지 않고 원문·제품 범위·기대 행동으로 판정한다. 미완료인 실제 그래프 접합의 증거로 대신하지 않는다.

### 7.2 상태별 영향과 제품 범위

| 상태·상황 | 검증할 변화 | 합격 기준 |
| --- | --- | --- |
| `SUPPORTED` | 기존 지원 답변의 핵심 사실·적용 범위, 새로 확보/탈락한 근거와 인용 | 사용 인용≥1, `[출처: 문서명·URL]` 일관성, 모든 인용의 실제 원문 역추적. 근거 삭제로 사실/지원 판정이 나빠지지 않음 |
| `UNSUPPORTED` | 명시적 미지원 근거·반증이 컷/임계값에 의해 사라지는지 | 미지원 근거와 인용≥1, 지원으로 오판0. T16 추가 검색 없음 |
| `INSUFFICIENT_EVIDENCE` | 정상 빈 결과·부분 근거·다중 조건 누락, 실제 근거 확보 후 상태 변화 | 부족하면 모른다는 안내·기계 상태 유지. 원문이 충분한 경우에만 지원 전환. 검색 Hit만으로 상태 승격 금지 |
| 기술 오류 | 검색/리랭크·입력/생성·인용 오류 | 의미 상태로 위장하지 않고 ErrorInfo로 기록. 미지원·오류에서 폴백 없음 |

`Evidence.doc_id`, `source_group_id`, `source_path`, `target_url`, `text`, 원래 `source_location`과 `product_scope`를 보존한다. RawPedia는 `RawTherapee`, ART GitHub는 `ART`다. 파일·본문·세그먼트 해시, JSON pointer, 문자·UTF-8 바이트 좌표, ref ID/댓글 앵커를 검증하고 요약문으로 원문을 대체하지 않는다.

Q010·Q077의 현재 B 최초 골드 순위는 각각 1·3이며 근거 범위는 RawTherapee다. T14에서 제품명 무단 추가를 보완한 사실과 별개로, 리랭킹 뒤 T17이 ART 지원으로 확정하는 오판을 막는다. 원요청이 RawPedia/RawTherapee 설명을 묻는지 ART 적용을 묻는지에 따라 실제 답변 범위를 판정한다. 이 질문들의 Hit·점수 상승을 근거 답변 완료로 해석하지 않는다.

수동 검토는 Q001·Q086·Q096, 집중12개, Q010·Q077 및 나머지 부정 질문을 필수로 포함하고, 상태 전환·핵심 사실·제품 범위·인용 변경 질문을 추가한다. 검토 상태 `pending`이 남으면 G5는 통과하지 않는다. 답변 상태가 같아도 주요 사실·적용 범위·인용 대응이 나빠지면 탈락시킨다. 정당한 반증/불충분 상태를 “지원 답변 수 감소”만으로 퇴행으로 판정하지 않는다.

## 8. 작업 단계·검증·일정

착수 시점 T0 기준의 순차 일정이다. WBS A-15의 기존 **3h**는 유지하며 아래는 목표 공수 배분이다. 실제 계산/생성 대기 시간과 실작업 시간을 함께 기록한다. 초과가 예상되면 단계별 잔여·추가 공수를 명시하며 T17·T16·독립 평가 작업을 T15 3h 안에 조용히 합산하지 않는다.

| 단계·목표 공수 | 입력 | 후속 출력·예상 변경 범위 | 검증·다음 단계 조건 |
| --- | --- | --- | --- |
| P0 플랜·기준선 준비, 0.5h | 본 문서, T8-1·T9·T14 인수 | 조건/지표/해시 protocol, A0/B0 재현 기록. 평가기 설계→구현은 후속 작업 | 입력 정합·분모·기준선 G0 통과. 계획 작성 자체로 실험 완료 처리하지 않음 |
| P1 리랭커 부착, 0.75h | G0, 고정 Chroma·후보 카드 | `retrieval/rerank.py`, `store.py` 후보 경계, `graph/search.py` 최소 인자 전달. 각각 작은 변경으로 나눔 | 기본10→5 일치, 후보확대·컷/임계값·출처/지정 글·순위·원문/오류 계약 검증, G1 |
| P2 격자 튜닝, 0.75h | 부착 경로, 집중12·고정15·전체100 | `scripts/eval_t15_rerank.py`, 조건별 전수 기록·후보 축소/확대 근거·선정/보류 설정 | §4 절차·격자 누락/중복 확인, 문서ID 지표 전수 재집계, G2/G3 |
| P3 전체 회귀, 0.5h | 고정 최종 후보 | 전체100 on/off·Slice 1·경로40·실제3회 재현 및 비교 보고 | G0~G4, 원문/스냅샷 불변, 원시 기록만으로 재계산 가능 |
| P4 T17 대조·인계 정리, 0.5h | G0~G4, 실제 T17 경로/담당 검증 | 비교 bundle·실제 답변/인용·필수 검토·게이트 보고, 검색 설정 v1 또는 보류 사유 | §7 G5 확인. 생성 실행·수동 검토의 추가 공수와 T17 접합 일정은 별도 기록 |

P1의 계약 검증은 후속 `tests/test_rerank.py`와 기존 `tests/test_retrieval.py`, `tests/test_graph_search_connection.py`, `tests/test_rewrite_preservation.py`로 계획한다. 후보 풀에 없는 정답을 만들지 못함, 긴 청크 후반의 근거, 동점 정렬, threshold 경계·전부 탈락, 명시적 빈 글 필터, 기본 호출 호환, 점수 오류를 검증한다. 평가기 검증은 후속 `tests/test_t15_rerank_eval.py`에서 문서 ID 중복·그룹/댓글 구별·빈 양성/부정 분모·조건 누락·집계 상승 속 개별 퇴행을 반례로 둔다. T17은 기존 답변/인용·게이트 테스트와 실제 비교를 함께 사용한다. 현재 문서 작업에서는 테스트 파일을 작성하거나 실행기를 구현하지 않는다.

체크포인트는 P1 뒤의 **호환·원문 계약 통과**, P3 뒤의 **검색 품질 통과**, P4 뒤의 **실제 답변 영향 확인**으로 나눈다. P4 입력이 준비되지 않아도 P0~P3는 진행할 수 있으나, 최종 채택 판정은 PENDING으로 둔다. 완료 보고에는 통과한 범위와 남은 게이트를 함께 적는다.

## 9. 리스크·T17/T16·CP3 연계

| 리스크 | 영향 | 대응·소유 경계 |
| --- | --- | --- |
| 후보 밖 골드 | 리랭커만으로 Q024·Q030·Q070을 복구할 수 없음 | 20→40 발동 근거·원문/필터/질의 진단. 임베딩/청킹/검색 방식 교체는 별도 조건·후속 과제 |
| 긴 청크·최대 윈도우 편향 | 뒷부분 근거 누락 또는 긴 청크 과대 평가·높은 지연 | 전 범위 채점·원문 좌표 기록·윈도우 수/지연 보고. T17 문맥 추출 변경은 별도 검증 |
| 점수 스케일·언어 차이 | 같은 임계값이 후보·on/off에서 다른 결과를 냄 | raw/변환 점수 고정, 언어별 실제 회귀, 후보별 threshold 선택. 영어 후보를 off에 무검증 적용 금지 |
| 평균으로 가려지는 퇴행 | T14의 집계 통과 속 개별10개 저하 반복 | 전체95개 개별 순위·집중12개·부정5개 검증을 집계와 별도 게이트로 유지 |
| k/threshold로 문맥 증가·근거 손실 | T17의 사실·인용·지원 상태 변화 | bundle/전달 문맥 지표 분리, 원문 기반 수동 검토, 변경 질문의 실제 답변 대조 |
| 회귀셋 반복 사용 | 튜닝 성능을 일반화 성능으로 오해 | 기존100/부분15의 탐색·회귀 표시 유지, 독립 평가 준비·최종 스택 선정·T23에 한계 인계 |
| T17·T16 연결 미완료 | 검색 개선만으로 실제 폴백·CP3를 증명할 수 없음 | T17 단독 검증과 실제 그래프 접합을 구분. 답변/인용·폴백이 준비되기 전 CP3 판정 보류 |
| 지연·실행/검토 예산 초과 | 3h 안에 일부 증거 누락 가능 | 원시 기록 보존, 단계별 공수·실제 호출/실패 기록, 필요한 후속 공수 명시. 미실행은 PENDING |

착수 전제는 **T17의 전체 연결과 T16 폴백·CP3가 미완료**라는 것이다. 현재 HEAD에는 T17 단독 모듈의 실제 v3 검증이 들어 있으므로 이를 미구현으로 되돌려 설명하지 않는다. 다만 T13-2 실제 `ANSWER` 접합·T15 변경 후 영향·T16 실제 폴백 완료를 증명하지 않는다. T15는 검색 결과를 제공하고, T17은 근거 기반 의미 상태·답변·인용을 소유하며, T16은 요청 전체의 추가 검색 1회 예산·중복 변환 방지·종료/재개를 소유한다.

CP3 판정에는 세 처리 경로의 실제 분기, T15 설정을 쓴 검색→실제 T17 답변·인용의 Slice 1 동등 이상, 명시적 `INSUFFICIENT_EVIDENCE`에서만 T16 추가 재작성→검색→답변이 정확히 한 번 실행되고 재부족이면 종료하는 증거가 필요하다. `UNSUPPORTED`·기술 오류에서 추가 검색 없음, 혼합 요청의 항목별 최초 검색 보존, 재개 시 count/완료 항목 보존도 확인한다. 라우터40건 통과·검색 지표 상승·대역 ANSWER만으로 CP3를 닫지 않는다.

최종 인계는 고정 설정·기준선/조건 지문·전체/개별 지표·복구/잔여 목록·재실행 명령·실제 T17 비교/검토·롤백 설정을 포함한다. 독립 평가와 최종 답변 스택 선정은 별도 게이트에서 수행하고 그 결과를 T23에 연결한다. 이번 플랜 커밋은 해당 구현·평가·채택·CP3의 완료 판정이 아니다.
