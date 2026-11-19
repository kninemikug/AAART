# T23 RAGAS 평가 리포트 구현 계획

## 평가 범위와 고정 입력

- [Task 23 카드](../tasks/todo.md#task-23-ragas-평가-a-23)와 [WBS A-23 상세 항목](ART_agentic_wbs.md)에 따라 T8-1 정본 `docs/search_eval_queries.json`의 `t08-1-100-v1` 전수(`Q001`~`Q100`)를 사용한다. RawPedia 80개와 GitHub 20개이며, 근거형 95개와 반증형 5개다. 이 질문은 검색 후보 탐색과 튜닝에 쓰인 회귀 입력이다.
- WBS §4의 15개 표기는 대표 실행의 규모와 같다. [T11 계획 §4.2](T11_execution_plan.md)와 `docs/T11_execution_records.jsonl`의 Slice 1 목록, [T14 계획](T14_execution_plan.md)과 `docs/T14_ab_eval_records.jsonl`의 대표 목록은 서로 다른 고정 부분집합이다. 두 목록은 보조 집계에 사용한다. T11·T14 및 `t17-answer/run_20261015_v3_resumed`의 기존 답변은 다른 실행 조건이므로 현재 설정의 누락을 보완하는 데 쓰지 않는다.
- [T15 v5 최종 결과](T15_results_v5.md)의 B 경로를 고정한다. 재작성 on, HyDE off, BM25 후보 20·top 5·최소 점수 0.5·가중치 0.25다. `t15-rerank/regression_v5`의 B 첫 반복에서 선택 청크와 검색 질의를 가져오고, protocol이 고정한 T14-CONN 스냅샷의 원문 세그먼트에 연결한다. `t15-rerank/t17_v5_complete_20261020_r3`에서 같은 조건의 `T15` 트랙만 결합한다. 저장된 생성 조건은 `codex-cli / gpt-5.6-sol / t17-answer-v1`이며 답변은 69개다. `B0`는 T15 원래 비교의 기준선이다.
- 이 리포트의 상태는 T15·T17 보존 기록 재평가다. 독립 질문과 경량 생성 모델을 사용하는 별도 최종 스택 선정 게이트는 저장소 카드에서 미완료다. 해당 게이트의 인수 기록이 생기면 그 조건에서 다시 평가해야 한다.

## 입력 조립

1. 실행 manifest, protocol과 사용한 원본의 SHA-256을 확인한다. 질문 ID·질문 본문·선택 조건의 중복, 누락 또는 불일치는 오류로 처리한다. T11·T14 대표 목록의 질문을 정본과 대조한다.
2. 정본의 `gold_support_doc_ids`와 `evidence`의 원문 ID·역할·위치를 보존한다. 근거형은 지원 ID를, 반증형은 명시적으로 허용된 `counterevidence` ID를 참조 집합으로 사용한다. 기대 답변 필드는 만들지 않는다.
3. 검색된 청크 순서대로 스냅샷의 `source_segments`를 펼친다. 청크·세그먼트 본문 해시와 T15 bundle 지문을 검증한다. 검색 문서 ID는 GitHub 항목의 청크 대표 ID나 스레드 ID 대신 각 세그먼트의 실제 원문 ID를 사용한다. 원문 텍스트·청크 ID·문서 ID·URL과 좌표를 입력에 기록한다.
4. T17 실제 기록의 질문·부모 검색·bundle·모델·프롬프트 버전을 대조한다. 구조화한 전체 세그먼트가 해당 프롬프트에 나타난 순서와 텍스트를 확인하고, 원응답의 답변 및 실제 상태·제공처·모델·실행 ID를 보존한다. 답변이 없는 31개는 `answer: null`과 사유를 기록하고 문맥은 재구성한 검색 증거로 표시한다.

## 지표

| 지표 | 계산과 범위 |
| --- | --- |
| ID-based context precision | 참조와 검색의 중복 제거 원문 ID 교집합 크기 ÷ 검색 원문 ID 수. 빈 검색은 `null`. 문서 수준이므로 순위·절 일치 여부는 점수에 반영하지 않는다. |
| ID-based context recall | 같은 교집합 크기 ÷ 참조 원문 ID 수. 빈 참조는 `null`. 반증형에는 참조로 미리 지정된 반증 문서를 사용한다. |
| Faithfulness | 실제 제출 문맥으로 뒷받침된 원자적 사실 주장 수 ÷ 응답에서 분해한 전체 사실 주장 수. 입력 지문에 연결된 판정 JSONL이 있는 경우 이 비율을 계산한다. 평가기 판정·사실 주장 또는 답변이 없으면 `null`과 원인을 기록한다. |

공식 정의는 [ID-based context precision](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_precision/), [ID-based context recall](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_recall/), [Faithfulness](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/faithfulness/)를 따른다. 입력별 점수를 매크로 평균하며 `null`은 평균에서 제외하고 실제 분모를 기록한다. 전체·근거형·반증형·T11/T14 대표 집합을 집계한다.

2026-11-20 KST에 Python 3.14 작업 venv에서 RAGAS 0.4.0의 PyPI 설치 dry-run을 확인했다. 패키지와 모델은 설치하지 않는다. 이 보존 기록에서 확인 가능한 ID 기반 두 지표는 공식 정의를 표준 라이브러리로 계산한다. 저장소에 고정된 faithfulness 평가기와 원자 주장별 판정은 없다. T15 수동 검토는 복합 문장 또는 응답 전체를 한 검토 단위로 묶을 수 있으므로 그대로 원자 주장 점수로 환산할 수 없다. 평가기 증거가 없는 기본 실행에는 `null`을 기록한다. 기존 생성·검색 도구에 네트워크 호출을 추가하지 않는다.

## 구현과 산출물

1. 입력 조립 및 출처 검증을 구현하고 실제 100행에서 대표 목록과 답변 연결을 확인한다.
2. 지표별 분모·산식·누락 사유를 검증하고 Markdown·JSON 산출물을 결정적으로 생성한다.
3. 임시 출력 디렉터리 두 곳에 평가를 실행해 파일을 바이트 단위로 비교한 다음 기본 경로에도 생성한다. 기존 Python 평가 회귀를 실행한다.

| 파일 | 레코드 |
| --- | --- |
| `data/eval/ragas_v1/inputs.jsonl.gz` | 고정 질문별 원문 ID·근거 위치, 순서가 있는 검색 세그먼트 원문과 출처, 답변·상태·실행 식별자, 원본 연결 및 `input_sha256`. gzip으로 본문이 반복되는 JSONL을 압축한다. |
| `data/eval/ragas_v1/scores.jsonl` | 질문 ID·입력 지문, 세 지표의 값·분자·분모·미산출 사유. |
| `data/eval/ragas_v1/summary.json` | 입력·판정 증거 파일 지문, 채택 설정, 질문 및 답변 커버리지, 집합별 점수·분모·누락 사유. |
| `data/eval/report_v1.md` | 실행 명령, 원본과 산출물 링크, 지표·표본 규모·누락 및 해석 범위. |

옵션 `--faithfulness-verdicts FILE`의 JSONL에는 `query_id`, `input_sha256`, 고정 평가기 식별자인 `evaluator`, `claims`를 둔다. `claims`는 `statement`와 불리언 `supported`의 목록이다. 정확한 입력 지문을 가진 실제 답변에만 결합하고, 평가기 식별자·기록 지문을 남긴다. 주장 목록이 비어 있으면 분모 0으로 처리한다. 평가기 판정의 의미적 정확성은 이 집계 스크립트의 검증 범위 밖이다.

## 실행과 완료 조건

```bash
venv/bin/python scripts/eval_ragas.py
t23_run_a=$(mktemp -d)
t23_run_b=$(mktemp -d)
venv/bin/python scripts/eval_ragas.py --output-dir "$t23_run_a"
venv/bin/python scripts/eval_ragas.py --output-dir "$t23_run_b"
diff -r "$t23_run_a" "$t23_run_b"
```

재실행의 기대값은 차이 0건이다. 답변이 없는 질문, 평가기 판정이 없는 답변, 빈 분모는 행별 `null`과 사유로 추적한다. 원본 손상 또는 다른 설정의 답변이 검출되면 실행 실패로 처리한다. 리포트에는 실제 산출한 수치만 기록하며, 100문항의 전수 faithfulness와 최종 스택 성능은 관련 증거가 확보될 때까지 미검증으로 표시한다.
