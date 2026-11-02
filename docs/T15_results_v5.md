# Task 15 추가 튜닝과 실제 답변 대조

2026-10-19 검색 실험, 2026-10-20 답변 이어 실행. 검색 구현 `7c78e7893`, 답변 재개 도구 `b56e63e5c`, 재개 경계 보완 `08e484294`. 기존100개 질문은 튜닝·회귀 입력이며 독립 평가셋이 아니다. Slice1 15개는 이100개의 부분집합이다.

## 현재 판정

검색 품질·원시 증거 감사·실제600건 반복 회귀와 **실제 답변138건의 주장·인용·제품 범위 검토를 모두 통과**했다. [최종 감사](../data/eval/t15-rerank/audit_v6/answers.json)는 PASS/exit0이며 미검토·오류·누락은0이다. T15 범위의 채택 게이트를 충족했고 아래 명시 연결 설정을 인수한다. 기존100개 입력의 튜닝·회귀 결과이며 서비스 배포나 T16/CP3 전체 완료를 뜻하지 않는다.

## 설정과 기준선

| 항목 | 조건 |
| --- | --- |
| A0 | T14 rewrite off·HyDE off, 기존 dense 후보10→top5 |
| B0 | T14 채택 조건: rewrite on·HyDE off, 기존 dense 후보10→top5 |
| 선정 후보 | BM25, 후보20·top5·min_score0.5·rerank_weight0.25 |
| 고정 입력 | 기존 T8-1 문서ID표·T9 154청크/임베딩·T14 A/B 원시 기록과 원문 위치 |
| 채택 전제 | 양경로의 전체/RawPedia/GitHub/Slice1 precision·recall·Hit@5·MRR@5 비저하, 개별 골드 순위 퇴행0, 부정 질문 반증 보존 |

순수 리랭크 점수로 dense 순위를 완전히 대체하던 방식에 결합 정렬을 추가했다.

`ranking_score = 0.75 × (1 - round(distance, 6)) + 0.25 × selection_score`

결합 점수는 정렬에만 사용한다. top-k 컷 뒤 원래 리랭커 `selection_score`에 임계값을 적용하며 빈자리를 다른 후보로 채우지 않는다. 원본 rank·거리·청크·원문 위치·제품 범위는 보존한다. 기본 가중치1은 기존 순수 리랭크 동작이다. 질문 ID나 정답 문서ID는 런타임 정렬 입력에 없다.

## 격자와 증거 재사용 범위

[protocol](../data/eval/t15-rerank/plan_v5/protocol.json)에3종 리랭커 × 후보20/40 × k3/5/10/20 × 임계값 미적용/0/0.2/0.5/0.7 × 가중치0.05/0.1/0.2/0.25/0.5/1을 등록했다. **720개 조건·144,000건 조건별 관측**을 전수 계산했다. 같은100개 질문의 반복이며 표본 수가 늘어난 것으로 해석하지 않는다.

후보 검색은 새 실제 Chroma에서 수행했다. 격자의 채점 값은 동결된 v3 실제 추론 증거를 재사용했다. 과거 protocol·manifest·전체 산출물·Git 코드 SHA와 채점 클래스 구문 트리, 모델/코퍼스·스냅샷·질의 벡터·전체 검색 후보가 일치하는 경우만 허용한다. `archived_inference`와 원본 파일 해시를 기록하며 새 추론 시간은 null이다. 초기168개 결합 진단도 새 추론이나 독립 평가로 세지 않는다.

[전체 조건](../data/eval/t15-rerank/grid_v5/grid_records.jsonl) · [선정 설정](../data/eval/t15-rerank/grid_v5/selected_condition.json) · [격자 감사](../data/eval/t15-rerank/grid_v5/validation.json).

## 적용 전후 검색 지표

양성95개의 원문 문서ID 집합 기준 macro 값이다. 선택 청크의 모든 `source_segments[].doc_id`를 중복 제거하며 precision은 골드 교집합/선택 문서 수, recall은 골드 교집합/골드 문서 수다. 부정5개는 이 평균에서 제외하고 반증 문서 보존을 별도로 검사한다.

| 경로·설정 | Precision | Recall | Hit@5 | MRR@5 | 개별순위 저하 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A0 | 0.259474 | 0.905263 | 0.905263 | 0.861754 | 기준선 |
| T15 A | 0.268596 | 0.915789 | 0.915789 | 0.867544 | 0 |
| B0 | 0.267368 | 0.968421 | 0.968421 | 0.880702 | 기준선 |
| T15 B | 0.268421 | 0.968421 | 0.968421 | 0.894737 | 0 |

양경로의 출처별/Slice1 집계도 비저하이고 부정 질문의 반증 문서는 각각5/5 보존했다. [전수·출처·Slice1·질문별 대조](../data/eval/t15-rerank/audit_v5/retrieval_summary.json)에 분모와 원시 지표를 보존했다.

선정 규칙은 기존의 양경로 비저하 후보 중 낮은 쪽 recall 우선, 합산 precision, 작은 k, 조건ID 순서를 유지했다. Q030을 복구하는 R1 결합 후보도 있으나, A recall을 개선한 BM25가 이 규칙으로 선정됐다. 결과를 본 뒤 특정 질문에 맞춰 선정 기준을 바꾸지 않았다.

## 집중 질문의 복구와 잔여

| 질문 | A0 | T15 A | B0 | T15 B |
| --- | ---: | ---: | ---: | ---: |
| Q017 | 1 | 1 | 2 | 2 |
| Q024 | 미도달 | 미도달 | 미도달 | 미도달 |
| Q025 | 2 | 2 | 3 | 2 |
| Q026 | 1 | 1 | 2 | 1 |
| Q030 | 1 | 1 | 미도달 | 미도달 |
| Q033 | 1 | 1 | 2 | 2 |
| Q041 | 1 | 1 | 2 | 2 |
| Q053 | 1 | 1 | 3 | 3 |
| Q055 | 1 | 1 | 2 | 2 |
| Q057 | 1 | 1 | 2 | 2 |
| Q070 | 미도달 | 4 | 미도달 | 미도달 |
| Q072 | 1 | 1 | 2 | 1 |

B의 기존 순위 저하10개 중 Q025·Q026·Q072가 원래 A 순위로 복구됐다. 다른 질문에 새 퇴행은 없다. Q024의 RawPedia 골드는 현재 B의 GitHub 출처 필터 밖에 있어 리랭킹만으로 복구할 수 없다. Q030·Q070의 B 골드는 후보40에서 dense10/19위에 있으나 선정 설정의 top5에는 들지 못한다. 이 세 질문의 B 복구를 완료했다고 보고하지 않는다.

## 실제 반복 회귀와 운영 계측

[회귀 기록](../data/eval/t15-rerank/regression_v5/validation.json)은 A/B200건을3회 새 검색·새 채점한600건이다. `fresh_inference`만 허용했고 결과 해시가3회 동일했다. 실제 그래프 경로40건과 G0~G4도 통과했다. [BM25 점수 독립 재계산](../data/eval/t15-rerank/audit_v5/bm25_independent_recompute.json)은 실제9,690개 점수를154청크 코퍼스에서 다시 계산해 모두 일치함을 확인했다.

[계측](../data/eval/t15-rerank/audit_v5/reranker_runtime.json)에서 새 BM25 채점 p50/p95는 A 약7.47/10.70ms, B 약8.47/11.43ms다. 별도 새 프로세스3회의 코퍼스 적합은 약44.6~45.2ms, 시작/import/적합 전체는 약3.39~3.47초였다. 최대 RSS 약543~546MB는 Python과 import 라이브러리를 포함한 프로세스 전체이며 리랭커 전용 증가량이 아니다. OS 캐시는 비우지 않았다.

BM25 리랭킹에는 외부 추론 요청이나 외부 추론 요금이 없다. 실제 T17 생성의 요청·사용량·요금은 별도다. 위 수치를 전체 서비스 cold start나 최종 응답 지연으로 해석하지 않는다.

## 연결과 롤백 설정

최종 게이트를 통과한 명시 인수 설정은 `create_search_nodes(..., rewrite_enabled=True, hyde_enabled=False, reranker=bm25, candidate_k=20, top_k=5, min_score=0.5, rerank_weight=0.25)`다. `bm25`는 고정 스냅샷154청크를 `section_title + "\n\n" + 본문`(제목이 없으면 본문만)으로 구성한 코퍼스에 적합한다. 순서·전처리는 `fit_bm25_from_snapshot`과 같으며 코퍼스 지문은 `f0a4afa910d3843c1b779aa44cf49fd4396b408c09721533bc1df9b82108e8fa`, `k1=1.5`, `b=0.75`다.

T13-2 그래프에는 이 노드 매핑을 `create_router_graph(node_overrides=...)`로 전달한다. 실제40건의 경로 시험은 검색 노드 연결과 상태·필터 계약을 확인한 것이며, 답변은 별도의 실제 `answer_standalone` 대조다. 실제 그래프의 ANSWER/T16 폴백 통합 완료 증거로 확대하지 않는다. 팩터리의 rewrite off·무리랭크 기본값은 그대로다.

롤백은 B0의 `rewrite_enabled=True, hyde_enabled=False, reranker=None, candidate_k=10, top_k=5, min_score=None, rerank_weight=1.0` 명시 설정이다. 문맥 예산·제품 범위·출처 필터·스냅샷을 바꾸거나 질문ID별 예외를 넣지 않는다. 이후 코드·코퍼스·생성 조건이 바뀌면 기존 합격을 자동 승계하지 않는다.

## 실제 T17 실행 이력

필수31개와 나머지 문맥 변경 질문을 합친69개 질문의 B0/T15 쌍138건을 도출했다. 실제 `answer_standalone`에 검증된 bundle을 전달하며 제공처·모델·프롬프트 버전을 등록 조건과 대조한다.

첫 [실행](../data/eval/t15-rerank/t17_v5/manifest.json)은86건 성공 후 제공처 사용량 한도로52건이 실패했다. [첫 감사](../data/eval/t15-rerank/audit_v5/t17_first_attempt.json)는 FAIL이며 [부분 검토](../data/eval/t15-rerank/review_v5/review_meta.json)도86건 검토/52건 미검토로 구분한다. 이 실행을 합격으로 채우거나 수정하지 않았다.

사용 가능 상태 확인 후 같은 `codex-cli/gpt-5.6-sol/t17-answer-v1`로 [전체 재실행](../data/eval/t15-rerank/t17_v5_retry_20261019/manifest.json)을 수행한 것은 불필요한 중복이었다. 첫 실행의 성공86건을 재사용했어야 했다. 재실행은123건 성공 뒤 사용량 한도로15건이 실패했다. 두 실행 모두 수정하지 않고 보존한다.

[이어 실행 계획](../data/eval/t15-rerank/resume_plan_20261020/resume_plan.json)은 첫 실행 성공86건과 두 번째 실행에서 추가로 성공한37건을 재사용하고, 남은15건만 호출한다. 재사용 대상은 질문·bundle·부모 manifest·등록 조건·코드 지문·실제 제공처 trace·원문/인용 검증을 먼저 통과해야 한다. 먼저 성공한 응답을 우선하므로 중복 성공86건은 선정 증거에 다시 포함하지 않는다.

재개 도구는 새 폴더에 원본 행의 입력 파일 연결만 바꾼 사본을 두고 원본 행 해시/실행 manifest/변환 후 해시를 `origins.json`에 연결한다. 원응답·요청·trace·인용·생성 코드·run ID는 바꾸지 않는다. 원본과 연결 필드 외의 차이가 있으면 감사에서 실패한다. 재사용123건을 새 생성으로 세지 않으며, 실제 생성이 한 번이라도 실패하면 즉시 중단하고 나머지는 미완료로 남긴다.

[첫 재개](../data/eval/t15-rerank/t17_v5_resumed_20261020/manifest.json)는123건 재사용 후3건이 새로 성공하고 Q093 B0의120초 시간 초과에서 즉시 중단했다. 전체 테스트를 마친 뒤 [한 차례 후속 재개](../data/eval/t15-rerank/t17_v5_resumed_20261020_final/manifest.json)는126건을 재사용하고3건이 새로 성공했으며 Q096 T15의120초 시간 초과에서 즉시 멈췄다. 두 재개 모두 새 요청4회이며, 오류 뒤 나머지 질문을 호출하지 않았다. 추가 전체 재생성은 없다.

재개 전 기록(`4d010a367` 시점)은130행(성공129·오류1)이고 필수138개 중8개는 호출하지 않았다. 당시 미성공9개는 **Q096 T15와 Q097~Q100의 B0/T15**였다. [원문 검토](../data/eval/t15-rerank/review_v5_resumed_20261020_final/review_meta.json)는 성공129건을 검토했고 오류1건은 PENDING이다. 미실행8건의 검토나 응답을 채워 넣지 않았다. Q010·Q077의 제품 범위는 검토한 실제 양쪽 응답에서 보존됐지만, 부정5개 전체의 답변 게이트는 아직 완료되지 않았다.

[재사용123건 독립 대조](../data/eval/t15-rerank/audit_v5/resume_reuse_integrity.json)와 각 재개의 원본 연결 감사는 통과했다. [당시 명령 판정](../data/eval/t15-rerank/audit_v5/t17_final_command.json)은 필수 쌍 누락으로 exit1/FAIL이며, 검색 비저하를 실제 답변 전체 합격으로 확대하지 않는다. 봉인한 과거 실행의 PENDING/FAIL도 소급 변경하지 않는다.


### 남은9건 완료와 최종 감사

성공129건의 원응답·요청·인용·코드 지문을 그대로 재사용하고, 남은9건만 이어 실행했다. [첫 후속 실행](../data/eval/t15-rerank/t17_v5_completed_20261020/manifest.json)은3건 성공 후 Q098 B0의120초 시간 초과, [두 번째](../data/eval/t15-rerank/t17_v5_complete_20261020_r2/manifest.json)는3건 성공 후 Q099 T15의120초 시간 초과에서 각각 즉시 멈췄다. [세 번째](../data/eval/t15-rerank/t17_v5_complete_20261020_r3/manifest.json)는남은3건만 성공했다. 실제 요청11회 중9회 성공·시간 초과2회이며, 성공한 답변의 중복 호출은0회다.

최종 집계는69문항의 B0/T15 **138건: SUPPORTED122·UNSUPPORTED10·INSUFFICIENT_EVIDENCE6, 오류0**이다. [전체 주장 검토](../data/eval/t15-rerank/review_v5_complete_20261020/review_meta.json)는138건 검토·미검토0이다. Q010·Q077의 RawTherapee 제품 범위, 부정5문항의 양쪽 UNSUPPORTED, Q024·Q030·Q070 양쪽의 근거 부족 유지를 확인했다.

[최종 감사](../data/eval/t15-rerank/audit_v6/answers.json)는 실제 제공처·모델·프롬프트, 원문 좌표·인용·현재/B0 답변 해시·재사용 계보를 검증해 **PASS/exit0**을 반환했다. [원본 보존 대조](../data/eval/t15-rerank/audit_v6/preservation.json)는129건의 입력 파일 경로 외 모든 필드가 같고, 신규 성공은 정확히누락9건임을 별도 확인한다. 과거 오류 행은 원본 실행에 남겨두고 최종 집계의 성공을 대체 생성으로 연결했다.

[구현 점검](T15_review_20261020.md)에서 미응답 case의 부모 입력 연결·재사용 계보·실패 판정 출력의 결함을 재현하고 수정했다. 등록한23개 검색/생성 코드 파일과 기존 protocol은 변경하지 않았다. 과거 도구 바이트는 Git으로 검증하고 새 재개 도구 원본은 실행과 함께 봉인한다.

## 검증과 재실행

최신 보완 구현의 전체 테스트 **1,015개·경고3개·334.60초**를 통과했다. 보완 전1,002개·332.86초의 기록도 보존한다. 재개 전 검색 구현은997개·336.08초였으며, 결합/증거 연결 집중27개·기존 평가/감사64개·재개 집중18개도 통과했다. 경고는 Chroma와 추론 라이브러리의 폐기 예정 속성이다. [완료 조건](../GATES.md)은 검색 검증과 실제 답변 검증을 구분한다.

새 출력 폴더를 사용한다. 코드 지문이 바뀌면 새 prepare부터 시작하며 과거 protocol을 수정하지 않는다.

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LLM_PROVIDER=codex LLM_MODEL=gpt-5.6-sol
PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
$PY scripts/eval_t15_rerank.py prepare --score-source-run data/eval/t15-rerank/grid_v3_rebuilt --output-dir data/eval/t15-rerank/plan_next
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase grid --output-dir data/eval/t15-rerank/grid_next
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase regression --selected-condition data/eval/t15-rerank/grid_next/selected_condition.json --output-dir data/eval/t15-rerank/regression_next
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase t17 --selected-condition data/eval/t15-rerank/grid_next/selected_condition.json --retrieval-run data/eval/t15-rerank/regression_next --output-dir data/eval/t15-rerank/t17_next
```

실제 검토 파일은 봉인한 실행 폴더 밖에 두고 `check --manual-reviews <새 검토 파일> --audit-output <새 감사 파일>`로 연결한다. T23은 고정100문항에서 RAGAS 지표를 측정하는 후속 작업이며 독립 홀드아웃 평가로 부르지 않는다. 별도 최종 스택 선정의 독립 평가와 T16/CP3 통합 증거도 이 반복 튜닝으로 대체하지 않는다.

이미 실제 답변 기록이 있다면 위 `--phase t17` 전체 실행을 반복하지 않는다. 반드시 성공이 가장 많이 모인 최신 집계 실행을 입력으로 사용한다. 아래 명령은 현재 성공138건의 재사용과 누락0건을 확인하는 오프라인 계획이며 생성하지 않는다. 이후 별도 실행에 누락이 있을 때만 그 최신 집계를 입력으로 `--execute-missing`을 붙인다.

```bash
$PY scripts/resume_t15_answers.py --source-run data/eval/t15-rerank/t17_v5_complete_20261020_r3 --output-dir data/eval/t15-rerank/resume_plan_next
```

최종 집계의 성공138건은 모두 보존돼 있다. 같은 입력의 완료 여부는 아래 저장 증거 감사로 확인하며 답변을 다시 생성하지 않는다. 이후 별도 실행에 누락이 생긴 경우만 그 최신 집계 실행을 `--source-run`으로 주어 재개한다.

```bash
$PY scripts/resume_t15_answers.py --check-run data/eval/t15-rerank/t17_v5_complete_20261020_r3 --manual-reviews data/eval/t15-rerank/review_v5_complete_20261020/manual_reviews.json
```
