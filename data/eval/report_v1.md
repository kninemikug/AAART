# T23 RAGAS 평가 리포트 v2

T8-1 `t08-1-100-v1` 100문항(RawPedia 80·GitHub 20)의 T15 검색 기록과 100개 T17 실답변을 재평가했다. T8-2와 T15에서 사용한 회귀 표본이다. WBS §4에 적힌 15개 규모의 대표 실행은 T11·T14에서 서로 다른 부분집합으로 확인했다. Task 23 카드와 WBS의 A-23 상세 항목에 따라 전체 100개를 사용했다. [평가 계획](../../docs/T23_execution_plan.md)

| 입력 | 질문 | 보존 답변 | ID-based context precision | ID-based context recall | Faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: |
| T8-1 전체 | 100 | 100 | 0.276667 (100/100) | 0.970000 (100/100) | 0.985931 (99/100) |
| 세 지표 공통 표본 | 99 | 99 | 0.279461 (99/99) | 0.979798 (99/99) | 0.985931 (99/99) |
| 추가 평가 문항 | 31 | 31 | 0.336559 (31/31) | 1.000000 (31/31) | 0.985484 (31/31) |
| 근거형 | 95 | 95 | 0.268421 (95/95) | 0.968421 (95/95) | 0.985182 (94/95) |
| 반증형 | 5 | 5 | 0.433333 (5/5) | 1.000000 (5/5) | 1.000000 (5/5) |
| T11 Slice 1 대표 | 15 | 15 | 0.332222 (15/15) | 1.000000 (15/15) | 0.981587 (15/15) |
| T14 대표 | 15 | 15 | 0.340000 (15/15) | 1.000000 (15/15) | 0.986667 (15/15) |

점수 옆 괄호는 실제 점수를 집계한 행 수와 대상 질문 수다. 질문별 점수를 매크로 평균했다. 세 지표 공통 표본은 세 점수가 모두 있는 동일 문항에서 각 평균을 계산한다. 근거형은 정본의 지원 원문 ID, 반증형은 사전 지정한 반증 원문 ID를 사용했다. 정밀도는 검색한 고유 원문 ID 중 허용된 ID의 비율이고, 재현율은 허용 원문 ID 중 검색된 ID의 비율이다. 평가 단위는 원문 문서이며 GitHub에서는 각 이슈·Discussion·댓글 세그먼트를 해당 원문 ID로 센다. [Precision 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_precision/) · [Recall 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_recall/)

## 실행 증거와 범위

- 검색은 T15 v5의 B 첫 반복을 사용했다. 재작성 on, HyDE off, BM25 후보 20·top 5·최소 점수 0.5·가중치 0.25에서 선택한 청크를 보존 스냅샷으로 복원했다. [T15 결과와 실행 인계](../../docs/T15_results_v5.md)
- 같은 검색 bundle이 확인된 T17 `T15` 트랙(`codex-cli / gpt-5.6-sol / t17-answer-v1`)의 응답 상태는 `INSUFFICIENT_EVIDENCE` 3건, `SUPPORTED` 92건, `UNSUPPORTED` 5건이다. 기존 69건과 동일 검색 문맥·모델·프롬프트의 추가 실호출 31건을 합쳤다. 기존 실행은 codex-cli 0.162.1, 추가 실행은 codex-cli 0.167.1로 수행했다. 기존 주장별 판정은 입력 지문을 대조해 재사용했다. [추가 생성 원본](ragas_v2/sol_answers_v1.jsonl.gz) · [주장별 판정](ragas_v2/faithfulness_verdicts_v1.jsonl) · [T17 최종 감사](t15-rerank/audit_v6/answers.json)
- T17 감사는 당시 코드 `08e484294`에서 138건 전부 재통과했다. 현재 브랜치에서는 계보 검증이 통과했고 뒤이은 감사가 T15 당시 코드 지문 목록과의 차이로 중단됐다. T23은 보존 manifest, 원문 세그먼트, 검색 bundle 지문과 실제 생성 요청 문맥을 대조했다.
- Faithfulness는 제출 문맥에서 뒷받침된 원자 주장 수를 전체 사실 주장 수로 나눈다. 평가기 `nvidia/minimaxai/minimax-m3.1-flash/t23-claims-v1`의 원자 주장 판정을 사용했다. 전체 사실 주장 545개 중 538개가 지지됐다. 미산출 사유는 판정 파일에 사실 주장 없음 1건이다. [Faithfulness 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/faithfulness/) · [보존 판정과 방법](../../docs/T23_execution_plan.md#구현과-산출물)
- 별도 최종 스택 선정 게이트와 독립 평가가 미완료다. 이 결과는 보존된 T15·T17 조건에 적용된다. [Task 23 및 선행 게이트](../../tasks/todo.md#task-23-ragas-평가-a-23)

## 재실행

```bash
venv/bin/python scripts/eval_ragas.py
```

2026-11-20 KST에 RAGAS 0.4.0의 PyPI 설치 dry-run을 확인했다. 공개된 공식 ID 산식은 Python 3.14.3 표준 라이브러리로 실행했다. 기본 실행에서 임시 출력 경로 두 곳의 산출물 네 파일이 바이트 단위로 일치했다. `--output-dir`로 출력 경로를 지정할 수 있다. [비교 명령과 원자 주장 판정 파일 형식](../../docs/T23_execution_plan.md)

질문별 검색 문맥·답변·출처는 [입력 JSONL(gzip)](ragas_v2/inputs.jsonl.gz), 점수·분모·누락 사유는 [점수 JSONL](ragas_v2/scores.jsonl), 원본 SHA-256 및 집계는 [요약 JSON](ragas_v2/summary.json)에 있다.
