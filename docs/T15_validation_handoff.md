# Task 15 평가 보완 인계

2026-10-20 최신 상태는 [v5 결과](T15_results_v5.md)를 우선한다. 아래 v3/v4 이력과 당시 FAIL/보류 판정은 보존한다. v5는720개 조건의 검색 비저하 후보와600건 새 반복 회귀를 확보했다. 성공 답변의 전체 재생성을 바로잡아 누락만 이어 실행했고, 현재 성공129건을 보존했다. Q096 T15와 Q097~Q100 양쪽9건은 시간 초과/미실행으로 미완료다. 최종 답변 감사 FAIL·B0 유지이며 T15 전체 완료와 CP3를 선언하지 않는다. 재개 도구는 성공을 재호출하지 않고 첫 오류에 중단한다.

작성일: 2026-10-16. 기존 100개 질문은 튜닝·회귀 입력이다. Slice 1의 15개는 그 부분집합이며 독립 평가셋이 아니다.

## 변경 사항

리랭커는 토크나이저 offset으로 원문을 자르고 실제 pair 길이를 검사한다. 길이를 줄였을 때 실제로 소비한 끝에서 다음 윈도우를 시작하여 마지막 단어까지 보존한다. 사용자 한도를 추론 객체에도 적용하고, 문자·UTF-8 바이트 범위·pair 길이·윈도우 로짓을 보존한다. R1의 `ENDMARKER` 후반 누락 반례와 실제 토크나이저 96/128/512 한도 검사를 추가했다.

T14 코드 지문 불일치를 환경변수로 통과시키던 처리를 제거했다. 현재 파일과 다르면 T15 이전 고정 Git 이력에 해당 바이트의 SHA가 실제로 존재해야 한다. 알려지지 않은 지문은 실패한다. 과거 dirty 실행의 `code_commit`만 신뢰하지 않는다.

평가 실행과 오프라인 감사를 `scripts/eval_t15_rerank.py`와 `scripts/t15_evaluation.py`로 나눴다. `check`는 모델을 로드하거나 검색·생성을 실행하지 않는다. 입력·실행 코드·모델 파일·산출물 해시, 실제 원문 세그먼트, 거리·필터·전체 후보, 윈도우 범위, 점수 변환, top-k/임계값 선택, 전달 bundle과 지표를 저장 증거에서 다시 검증한다. 보고서의 PASS 문자열을 판정 입력으로 쓰지 않는다. 과거 증거를 새 스키마로 소급 작성하지 않는다.

R1/R2/BM25를 전체 A/B에서 같은 격자로 비교하며 필요하면 후보40으로 확대한다. BM25는 고정154개 청크의 동일 통계에 적합한다. 합격 조건이 있을 때만 사전 등록한 동률 해소 기준으로 선정한다. 진단 최선 후보는 채택 설정과 구별한다.

실제 `RetrievalStore`와 `create_router_graph`를 사용한다. 경로40건은 기대 검색 노드를 직접 호출하지 않으며 trace·출처·지정 글·상태·Evidence를 검사한다. 준비 상태와 답변은 명시적인 검색 계약 시험 대역이며 G5 증거가 아니다. T14의 검증된 생성 원본만 같은 프롬프트로 재생한다.

## 기준선 복원과 실행 이력

`plan_v3`은 실행기 정리 중 만든 초기 준비 기록이다. `plan_v3_final`과 `grid_v3`은 첫 실제 실행의 증거다. 첫 실행은 A Q006에서 거리 표시 불일치를 발견하여 실패했다. ID/순서는 일치했지만, 이미 정규화된 Chroma 저장 벡터를 다시 넣어 약 `1.19e-7` 차이가 생겼다. 실패 기록과 protocol을 보존했다.

최종 실행은 `plan_v3_rebuilt`와 `grid_v3_rebuilt`다. T9의 기존 `embed_chunks`로 입력 벡터를 다시 생성하고 실제 Chroma에 적재한다. 복원된154개 청크·본문·메타데이터·벡터의 전체 스냅샷 SHA가 원본과 정확히 같아야 진행한다. A/B200건의 top5 ID·순서·거리 표시·원문 위치도 정확히 비교한다. 거리 오차 허용으로 이 검사를 완화하지 않았다.

## 검증 증거와 판정

- v3 코드 전체 테스트: `950 passed, 3 warnings, 399.52s`. 마지막 벡터 복원 수정 후 평가 집중 테스트23개와 추가 판정 대조를 포함한 무결성 테스트21개도 통과했다. 경고는 Chroma와 추론 라이브러리의 폐기 예정 속성이다.
- 원래 고정 입력6개는 [보존 해시 대조](../data/eval/t15-rerank/audit_v3/original_inputs.json)에서 모두 일치했다.
- v1 [검색 감사](../data/eval/t15-rerank/audit_v3/regression_v1.json)와 [답변 감사](../data/eval/t15-rerank/audit_v3/t17_v1.json)는 실행 증거의 완전성을 확인할 수 없어 PENDING이다. 별도의 [확인 가능한 위반 재집계](../data/eval/t15-rerank/audit_v3/v1_known_violations.json)는 A/B 순위 저하11/5건과 답변 오류·부정 질문의 거짓 지원10건으로 FAIL이다. 증거 부족이 이미 확인한 위반을 상쇄하지 않는다.
- 최종 격자 결과와 후속 검증 상태는 아래에 기록했다.
- [읽기 전용 감사](../data/eval/t15-rerank/audit_v3/grid_readonly.json)는 검색·임베딩·추론 객체 생성을 금지한 상태에서 같은120개 조건·24,000건 판정을 재현했다. 실행 폴더의 모든 파일 SHA·크기·mtime이 감사 전후 동일했다.

## 재실행

루트 Python 3.14 venv를 사용한다. 아래 명령의 출력 폴더는 새 이름으로 바꾼다. protocol은 코드 SHA를 고정하므로 코드가 달라졌으면 새 prepare부터 실행한다. 기존 결과를 덮어쓰지 않는다.

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
$PY scripts/eval_t15_rerank.py prepare --output-dir data/eval/t15-rerank/plan_next
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase grid --output-dir data/eval/t15-rerank/grid_next
$PY scripts/eval_t15_rerank.py check --run-dir data/eval/t15-rerank/grid_next --audit-output data/eval/t15-rerank/audit_next/grid.json
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase regression --selected-condition data/eval/t15-rerank/grid_next/selected_condition.json --output-dir data/eval/t15-rerank/regression_next
$PY scripts/eval_t15_rerank.py run --protocol data/eval/t15-rerank/plan_next/protocol.json --phase t17 --selected-condition data/eval/t15-rerank/grid_next/selected_condition.json --retrieval-run data/eval/t15-rerank/regression_next --output-dir data/eval/t15-rerank/t17_next
```

품질 FAIL의 종료 코드는1, 실제 답변·검토·반복 등 선행 증거가 부족하면2, 모든 채택 게이트 통과만0이다. `selected_condition=null`이면 후속 두 단계는 생략 이유를 기록하고2를 반환한다. 합격 후보의 회귀는 전체200건을3회 새 검색·채점하여600건을 남긴다. 실행 시간은 반복 동일성 해시에서 제외하고 점수·문맥·질문별 지표를 비교한다.

실제 T17은 `answer_standalone`에 검증된 B0/후보 bundle을 각각 주며 필수31개와 나머지 문맥 변화 질문을 짝지어 실행한다. 최소62개 실제 요청·원응답·제공처 trace·인용·코드 지문을 보존하고 기존 T17 검증기를 재사용한다. 실제 생성이나 필수 수동 검토가 없으면 G5는 PENDING이다. Q010/Q077의 제품 범위 승격과 부정5개의 거짓 SUPPORTED는 실패다.

수동 검토는 봉인된 실행 폴더 밖의 새 파일에 기록하고 `check --manual-reviews <검토 파일> --audit-output <새 감사 파일>`로 연결한다. 실행 폴더에 파일을 추가하면 manifest의 파일 목록 대조가 실패한다. 검토 파일은 run ID를 키로 쓰며 각 항목에 아래 구조를 둔다. `record_digest(record)`는 기존 T17 함수를 사용한다.

| 필드 | 필수 내용 |
| --- | --- |
| `record_digest` | 검토한 해당 답변 레코드의 해시 |
| `baseline_record_digest` | 같은 질문의 짝지은 B0 답변 레코드 해시. B0 검토도 자기 B0 해시를 기록 |
| `reviewer`, `verdict` | 비어 있지 않은 검토자 문자열과 `PASS`/`FAIL`/`PENDING` |
| `claims[]` | 하나 이상의 객체. 각 객체에 비어 있지 않은 `claim`, `reason`과 `verdict` |
| `claims[].citation_ids` | 해당 주장의 실제 사용 인용 ID 배열. 지원·반증 답변은 인용이 필수 |
| `claims[].evidence_links` | 각 인용의 `cid`, `target_url`, `source_location`. 답변의 `used_citations_provenance` 값과 일치해야 함 |
| `claims[].checks` | `status`, `product_scope`, `baseline` 각각에 `verdict`와 비어 있지 않은 `reason` |

사용한 모든 인용을 주장 검토에 포함한다. 무인용 `INSUFFICIENT_EVIDENCE`는 빈 인용/원문 연결 배열을 허용하되 주장·사유·상태·제품 범위·B0 대조 검토는 필수다. 빈 주장이나 누락된 검토 증거는 PENDING이고, 명시적 불합격·잘못된 CID/URL/원문 위치·오래된 답변 해시는 FAIL이다. 확인된 FAIL이 증거 부족보다 우선한다. 검증기는 이 연결과 완전성을 검사하며 사실의 의미 판정은 실제 수동 검토가 담당한다.

## 잔여와 CP3

리랭커 기본값과 B0 채택 설정은 유지한다. 새 리랭커를 서비스 기본값으로 연결하지 않는다. Q024의 B 경로는 GITHUB이며 RawPedia 골드가 출처 필터 밖에 있으므로 후보 수만 늘려 해결할 수 없다. 질문 ID에 따라 다른 출처로 강제 우회하지 않는다.

검색 품질 합격 후보의 전체3회 회귀, 실제 T17 대조 및 의미·인용 수동 검토가 끝나기 전에는 T15 품질 목표나 G5를 완료로 표시하지 않는다. T16의 요청 전체1회 폴백·종료/재개, 실제 그래프 ANSWER 연결도 별도다. 이번 검색 계약 시험으로 CP3를 닫지 않는다. 지연 기록의 `incremental_cache`는 풀 확대 시 새 후보만 채점한 시간이며 전체 warm 응답 지연으로 해석하지 않는다. cold load·메모리·비용의 완전한 운영 계측과 독립 평가/T23은 후속 검증 범위다.

## 최종 격자 결과

실제 비교는 3종 × 후보20/40 × k 3/5/10/20 × 임계값 미적용/0.0/0.2/0.5/0.7의 **120개 조건·24,000건 조건별 관측**이다. 같은 100개 질문을 반복한 튜닝·회귀이며 독립 표본으로 세지 않는다. 합격 조건은0개다. 원시 증거 감사는 통과했지만 품질은 FAIL, `selected_condition=null`, **B0 유지**다.

[최종 판정](../data/eval/t15-rerank/grid_v3_rebuilt/validation.json) · [전체 조건 지표](../data/eval/t15-rerank/grid_v3_rebuilt/grid_records.jsonl) · [선정 불가 및 진단 후보](../data/eval/t15-rerank/grid_v3_rebuilt/selected_condition.json).

아래 후보는 모두 k5·임계값 미적용이다. 수치는 양성95개의 macro precision/recall이며 순위 저하 건수는 각 경로의 원래 기준선과 비교한다.

| 조건 | A precision | A recall | A 순위저하 | B precision | B recall | B 순위저하 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A0/B0 | 0.259474 | 0.905263 | 0 | 0.267368 | 0.968421 | 0 |
| R1 후보20 | 0.257368 | 0.884211 | 12 | 0.283684 | 0.968421 | 5 |
| R2 후보20 | 0.257895 | 0.863158 | 12 | 0.280877 | 0.978947 | 7 |
| R3 후보20 | 0.265965 | 0.905263 | 16 | 0.283158 | 0.947368 | 16 |
| R1 후보40 | 0.264211 | 0.884211 | 12 | 0.278070 | 0.957895 | 7 |
| R2 후보40 | 0.256491 | 0.842105 | 12 | 0.279474 | 0.968421 | 7 |
| R3 후보40 | 0.258421 | 0.884211 | 16 | 0.264561 | 0.905263 | 18 |

R1 후보20·k5는 B precision/MRR을 개선하지만 A recall을 낮추고 개별 순위를 퇴행시킨다. 후보40은 B recall도 낮춘다. 집계 개선으로 개별 퇴행을 상쇄하지 않는다. RawPedia80·GitHub15·Slice 1 양성14와 Hit@5/MRR@5도 전체 조건 JSON에서 각각 비교했다.

### 집중12개 최초 골드 순위

| 질문 | A0 | B0 | R1 후보20 B | R1 후보40 B |
| --- | ---: | ---: | ---: | ---: |
| Q017 | 1 | 2 | 1 | 1 |
| Q024 | 미도달 | 미도달 | 미도달 | 미도달 |
| Q025 | 2 | 3 | 1 | 1 |
| Q026 | 1 | 2 | 1 | 1 |
| Q030 | 1 | 미도달 | 1 | 1 |
| Q033 | 1 | 2 | 1 | 1 |
| Q041 | 1 | 2 | 1 | 1 |
| Q053 | 1 | 3 | 1 | 1 |
| Q055 | 1 | 2 | 1 | 1 |
| Q057 | 1 | 2 | 미도달 | 미도달 |
| Q070 | 미도달 | 미도달 | 미도달 | 미도달 |
| Q072 | 1 | 2 | 1 | 1 |

Q030은1위 복구, Q024·Q070은 미도달이며 Q057은 B0의2위에서 미도달로 퇴행한다. Q024는 원래 B의 GITHUB 경로/필터를 유지한 결과다. Q024를 복구하려면 라우팅 소유 범위에서 별도 조건과 기준선을 검토해야 한다.

### Slice 1 대조

진단 후보 R1 후보20·k5·임계값 미적용의 B 경로다. 양성14개와 부정 Q096을 구별한다.

| 질문 | B0 precision/recall | R1 precision/recall | 최초 골드 순위 B0→R1 | 반증 B0→R1 |
| --- | --- | --- | --- | --- |
| Q001 | 0.2000/1.0000 | 0.2000/1.0000 | 1→1 | N/A |
| Q004 | 0.2500/1.0000 | 0.2500/1.0000 | 1→1 | N/A |
| Q014 | 0.2500/1.0000 | 0.3333/1.0000 | 1→1 | N/A |
| Q021 | 0.2000/1.0000 | 0.2000/1.0000 | 1→1 | N/A |
| Q033 | 0.2000/1.0000 | 0.2000/1.0000 | 2→1 | N/A |
| Q044 | 0.2000/1.0000 | 0.2000/1.0000 | 1→1 | N/A |
| Q054 | 0.3333/1.0000 | 0.3333/1.0000 | 1→1 | N/A |
| Q063 | 0.2000/1.0000 | 0.2000/1.0000 | 1→1 | N/A |
| Q072 | 0.2000/1.0000 | 0.2000/1.0000 | 2→1 | N/A |
| Q080 | 0.2000/1.0000 | 0.2000/1.0000 | 1→1 | N/A |
| Q084 | 0.5000/1.0000 | 0.5000/1.0000 | 1→1 | N/A |
| Q086 | 0.6667/1.0000 | 0.6667/1.0000 | 1→1 | N/A |
| Q092 | 0.7500/1.0000 | 0.7500/1.0000 | 1→1 | N/A |
| Q093 | 0.3333/1.0000 | 0.3333/1.0000 | 1→1 | N/A |
| Q096 | N/A | N/A | N/A | True→True |

### 후속 게이트

검색 합격 후보가 없어 [전체3회 후보 회귀](../data/eval/t15-rerank/regression_v3/skipped.json)와 [실제 T17 대조](../data/eval/t15-rerank/t17_v3/skipped.json)는 선행 조건 미달로 보류했다. 각 실행의 종료 코드는2이며,600건 반복이나 실제 답변62개를 실행한 것으로 기록하지 않았다. G5와 CP3는 미완료다.

후보20의 단일 전체 채점 시간은 [계측 요약](../data/eval/t15-rerank/audit_v3/scoring20.json)에 있다. R1 p50/p95 약5.24/7.35초, R2 약2.66/3.81초, BM25 약8.09/11.22ms다. 후보40의 일부 구간은 전체 테스트와 겹쳤고 캐시에서 새 후보만 추가 채점했으므로 전체 warm 지연 비교에 쓰지 않는다.

## 답변 감사 후속 보완

2026-10-18, 구현 커밋 `ad8e17bac`. [검증 요약](../data/eval/t15-rerank/audit_v4/verification.json): 새 집중 테스트35개 통과, 전체 **985 passed, 3 warnings, 330.84s**. 새 [준비 protocol](../data/eval/t15-rerank/plan_v4/protocol.json)은 이 구현 커밋과 추가 답변 검증기의 지문을 포함하며 기존 검색 입력·모델·격자가 같음을 확인했다. 준비 기록은 새 검색/실제 답변 실험의 결과가 아니다.

v3 후속 리뷰에서 빈 주장 객체, 문맥 변경 질문의 비교 누락, 등록한 제공처·모델·프롬프트 버전 불일치가 답변 감사에서 PASS되는 문제를 재현했다. 답변 전용 검증을 `scripts/t15_answer_validation.py`로 분리하고 기존 감사 진입점과 연결했다. 새 파일도 protocol의 코드 지문 대상이다.

실행기와 감사기는 동일한 `comparison_inputs`로 부모의 전체100개 B0/후보 bundle 해시를 비교해 필수31개와 모든 문맥 변경 질문을 도출한다. `cases.json`과 실제 답변 기록은 이 질문들의 B0/T15 쌍과 정확히 일치해야 하며 중복·불명 track·한쪽 누락은 실패한다. 각 답변의 제공처·모델·프롬프트 버전은 등록 조건과 대조하고, 실제 생성 전에 런타임 조건도 같은 세 항목을 확인한다.

새 테스트는 완전한62건과 문맥 변경 Q002를 포함한64건의 양성 대조를 포함한다. 부모 검색 선행 판정만 대역이며 원문·답변·인용·코드 검증은 실제 함수를 실행한다. 테스트용 응답은 실측 T17 기록으로 저장하지 않는다. 실제 T17 비교와 CP3는 여전히 보류다.

이번 변경은 검색 알고리즘·가중치·k·임계값을 바꾸지 않는다. 기존120개 조건·24,000건의 검색 실험은 다시 실행하지 않았고 v3 원본도 수정하지 않았다. [동결 기록 검사](../data/eval/t15-rerank/audit_v4/frozen_v3_integrity.json)는 당시 코드 `8984ecd44`의 바이트와 protocol 지문, 입력·산출물10개·manifest의 해시 일치를 확인한 것이며 새 품질 재평가가 아니다. v3의 B0 유지 결론을 보존한다.

현재 코드는 감사 규칙과 코드 지문 목록이 바뀌었으므로 v3 protocol을 새 코드의 실행 증거로 재사용하면 코드 지문 검사에서 거부된다. 새 검색/실제 답변 평가가 필요하면 위의 `prepare`부터 새 폴더에서 시작한다. 과거 protocol의 해시를 새 코드 값으로 고쳐 통과시키지 않는다.
