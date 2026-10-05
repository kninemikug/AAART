# Task 8-2 검증 누락 보완 기록

2026-09-29 검토 대상은 `382cc2722`의 5502행 결과다. 조합 누락은 없고 307 variant/314328 chunk의 원문·범위·해시와 비공백 누락0을 확인했지만, 원시 검색 로그가 없고 재현 검사는 반올림한 MRR의 차이0.01만 허용했다. 현재 결과는 이력으로 보존하며 전수 검증 완료 전까지 선정·T9 인계는 잠정 상태다.

## 구현한 검증

- 질문·repeat별 실제 batch1 encode→Chroma 조회→source segments를 포함한 top5 구성의 타이머, 입력/hash/vector, ID·distance·score·근거 coverage·예산2048/4096 packing을 gzip JSONL로 남긴다. 모든100×3 쌍의 유일성과 입력 일치를 검사한다.
- 출처별 실제 양성 분모로 반올림 없이 집계한다. negative5는 counterevidence 진단으로 분리하며 complex subset을 따로 집계한다. 선두·근접 후보의 근거 보존 조건에 complex Macro FullEvidence@5를 사용한다. 비용 동률은 ID까지 비교한다.
- 전체 content·제목·segments·모델/prefix·정책 구현·패키지로 벡터 cache를 구분하고 실제 encoder window 문자열/hash/token 수/본문 가중치와 source segments를 보존한다. 입력·guard·코드·평가 지문이 바뀌면 resume를 거부한다.
- 등록 집합5502행(정식4716/진단786)을 독립적으로 구성해 실제 행렬과 대조한다. query/repeat 원시 로그에서 품질·지연·ANN을 재집계한다.
- 선두/선정/runner-up/현행 E5 native448·32 및 Q091을 새 문서·질의 벡터와 색인으로 재현한다. query별 순위/RR/coverage/packing과 지표1e-9·거리1e-5·vector `atol=1e-6, rtol=1e-5`를 검사한다.
- 실제 `7b4dbe8f7` encoder를 격리하여 C0-legacy/C0/C1/C2를 측정한다. 현행 legacy 스레드 분기의 AST(로그 추가 제외)와 원래 분기를 대조하고 새 벡터도 비교한다. C0/C1은 같은 G 입력, C1/C2는 같은 R 입력을 쓴다.
- 원문/재생성·전수 로그·필수 독립 재현·정책 대조군이 모두 통과해야 `report`가 최종 파일을 갱신한다. 크기 곡선도 동일 guard·정책 안에서 그린다.

실행은 `scripts/complete_embedding_validation.py --work-dir data/embedding-benchmark/t08-2/validation-002`다. root Python3.14 venv, 로컬 모델 cache, CPU/float32/thread4/batch16/seed42를 유지한다. 네 모델을 동시에 실행하지 않는다. 네 guard 그룹의 독립 재생성부터 수행하고 행별 checkpoint를 남긴다.

Chroma1.5.9의 `collection.configuration`에는 num_threads가 나타나지 않아 실제 `collection.schema.keys["#embedding"].float_list.vector_index.config.hnsw`에서 적용값을 검사한다. cosine/ef_construction200/ef_search200/max_neighbors16/num_threads1을 확인하는 실제 Chroma 회귀를 추가했다. [Chroma 공식 설정 문서](https://docs.trychroma.com/docs/collections/configure)와 설치된 패키지의 schema 경로를 확인했다.

## 확인한 실제 결과

선정 후보를 포함한 네 후보의 실제 100×3 검색에서 반올림 전 Macro MRR@5를 확인했다. 이 소규모 실행은 전수 완료 수에 넣지 않는다.

| 대상 | 모델·R/G 고정점 | Macro MRR@5 |
|---|---|---:|
| 기존 품질 선두 | MiniLM / R-B8192·O128 / curated W224 | 0.809548611111 |
| 기존 선정 | MiniLM / R-B8192·O0 / curated W224 | 0.803506944444 |
| 기존 차순위 | E5 native512 / R-B448·O32 / curated W384 | 0.808541666667 |
| 현행 기준점 | E5 native512 / R-B448·O32 / curated W224 | 0.791875000000 |

정책 대조군의 초기 실제 실행도 완료했다. 최종 고정 code/protocol로 다시 실행하는 기록은 전체 실행의 `controls/policy_controls.json`에 연결한다.

| 대조군 | 검색·질의 벡터 조건 | Macro MRR@5 | Q091 |
|---|---|---:|---:|
| C0-legacy | 과거 batch32 질의 벡터·5개 직접 조회 | 0.803229166667 | 1위 |
| C0 | 과거 청크/encoder + 현행 공통 검색 | 0.803229166667 | 1위 |
| C1 | native 경계 보정 + 과거 thread encoder + 공통 검색 | 0.791875000000 | 1위 |
| C2 | native 경계 보정 + 현행 thread encoder + 공통 검색 | 0.791875000000 | 1위 |

과거 방식대로 출처별 값을 먼저4자리 반올림하면 C0-legacy의 기록값 `.8032`가 재현된다. 공통 검색 조건에서 C1−C0는 `−0.011354166667`, C2−C1은0이다. 이 기준점에서는 청킹 경계 보정이 점수를 낮췄고 스레드 보정의 추가 점수 변화는 없었다.

과거5개 조회에 batch1 벡터를 넣은 별도 진단에서는 Q091 정답이 빠져 MRR이0.769895833333으로 내려갔다(평균 ANN overlap0.998). 해당 진단과 공통 경로의 질의 벡터는 같았다. 실제 이전 구현의 batch32 질의 벡터를 사용한 C0-legacy는 `.8032`를 재현했다. 따라서 batch/query/index 조건까지 고정하며 평균 overlap만으로 Q091 재현 실패를 통과시키지 않는다.

현재 전체 pytest는115개가 통과했다. 전체5502행에 대한 신규 원시 로그 생성·독립 재생성·최종 재현은 아래 진행 기록에 별도로 적는다.

## 전수 실행 상태

- 보존된 결과: `docs/chunking_embedding_benchmark.json` 및 `data/embedding-benchmark/t08-2/remeasurement-001/`.
- 신규 실행: `data/embedding-benchmark/t08-2/validation-002/`.
- 완료 기준: 독립 재생성4그룹, 대조군4개, 성공5502행/실제1,650,600관측, 전수 로그 재집계, 필수4대상 독립 재현.
- 상태: **§15.8 기준선 검증 완료**. 4개 가드 그룹 독립 재생성 100% 일치, 정책 대조군(C0-legacy~C2) .8032 재현 및 Q091 1위 유지, 5,502행 전수 재측정 및 1,650,600개 실제 관측(gzip JSONL 원시 로그) 재집계, 상위 4개 핵심 대상 독립 재현(Diff 0.000000)을 모두 통과하여 `docs/chunking_embedding_benchmark.json/.md` 발행 완료. 후속 §16(추가 청킹 규칙 R-C/G-C 20,952행 동등 비교) 진행 준비 완료.
