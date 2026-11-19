# RAG 답변 생성 모델 비교 결과

보존 문맥과 독립 질문에서 비교한 결과 **`gpt-5.6-terra`를 답변 생성 모델로 선정했다.** 독립 8문항에서 Sol과 Terra가 각각 8/8의 상태·응답·인용·제품 범위 기준을 충족했다. Terra의 답변 지연 중앙값은 7.698초, Sol은 7.751초였다. 공개 API 단가로 환산한 Terra의 토큰 비용은 Sol보다 26.8% 낮았다. 기본 라우팅의 불일치가 한 건 확인되어 전체 경로 선정 게이트와 정식 T23 인수는 보류한다. [사전 실험 계획](RAG_stack_selection_plan.md)

## 모델 비교

| 집합 | 모델 | 기술 성공 | 상태 일치 | 중요한 주장·인용·범위 기준 통과 | 답변 중앙값 | API 단가 환산 합계 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 기존 회귀 표본 | Sol | 6/6 | 6/6 | 6/6 | 6.138초 | $0.5139 |
| 기존 회귀 표본 | Terra | 6/6 | 6/6 | 6/6 | 6.253초 | $0.3405 |
| 기존 회귀 표본 | Luna | 6/6 | 6/6 | 5/6 | 6.822초 | $0.0274 |
| 독립 평가 | Sol | 8/8 | 8/8 | 8/8 | 7.751초 | $0.4294 |
| 독립 평가 | Terra | 8/8 | 8/8 | 8/8 | 7.698초 | $0.3144 |

Codex CLI 0.167.1에서 문항당 한 번씩 초기 답변 18건, 독립 답변 16건과 독립 검색 재작성 8건을 요청했다. 초기 비교 6문항의 입력은 보존된 T17 요청과 프롬프트 지문이 일치한다. 독립 비교 8문항에서 두 모델의 질문·검색 bundle·프롬프트 지문이 각각 일치했다. 기술 실패와 자동 재시도는 비교 본실행에서 각각 0건이었다. 초기 샌드박스 접근 시험은 CLI 초기화 권한 오류로 중단됐으며 원격 모델 응답이 없었다. [초기 실행](../data/eval/stack-selection/pilot_v1) · [독립 실행](../data/eval/stack-selection/final_v1)

지연은 T17 답변 단계의 경과 시간이다. 독립 표본에서 Terra는 8개 중 6개에서 더 오래 걸렸으며, 문항별 Terra−Sol 지연의 중앙값은 +0.802초였다. 독립 표본의 모델별 중앙값 차이 0.052초로 일반적인 속도 향상을 주장할 수 없다. 비용 추정은 CLI 사용량의 입력·캐시 적중 입력·출력 토큰을 2026-11-20 공개 표준 API 단가에 곱한 값이다. 캐시 쓰기 여부 및 실제 구독 과금은 `null`이다. [Sol 단가](https://developers.openai.com/api/docs/models/gpt-5.6-sol) · [Terra 단가](https://developers.openai.com/api/docs/models/gpt-5.6-terra) · [Luna 단가](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

초기 Q070에서 Luna는 요청한 `rocks.md`가 문맥에 없다고 올바르게 판단했으나, 다른 예시의 스팟 수와 도구를 설명하면서 그 내용이 없는 `[C3S1]`을 인용했다. 해당 예시와 관련된 설명은 다른 세그먼트 `[C1S1]`에 있다. Q086의 두 경량 후보가 사용한 `Liked mask`는 GitHub 댓글의 표기를 그대로 인용한 것이다. 후속 도구 순서와 재사용 조건은 원문과 일치했다. Terra는 기존 프롬프트로 초기 검토를 통과해 독립 비교에서도 그 버전을 유지했다. Luna의 별도 조정은 수행하지 않았다. [Q070 Luna 응답](../data/eval/stack-selection/pilot_v1/Q070-gpt-5.6-luna.json.gz)

독립 문항은 RawPedia 4문서, GitHub 4스레드에서 작성했다. 기존 T8-1 골드 및 초기 비교 문맥과 원문 ID가 겹치지 않는다. 지원 5개, 근거 부족 2개, 미지원 1개를 포함한다. 각 답변을 인용한 원문과 대조해 크롭 비율·메타데이터 모드·필름 중성점 순서, RawTherapee와 ART 범위, 충돌·파일 열기 보고의 확인 범위, 수정 커밋 미기재, PPI와 EXIF의 구분을 확인했다. [고정 질문·근거·기대 행동](../data/eval/stack-selection/final_questions_v1.json)

## 실제 검색과 인수 범위

- 실험 색인은 기존 154청크를 T9 임베딩으로 복원하고, T10 정제 결정을 통해 GitHub 4스레드를 기존 청킹 규칙으로 추가해 158청크로 고정했다. 색인과 회귀를 새 임시 위치에서 다시 구성했을 때 스냅샷 SHA-256 `99e62ddbeb46b451abdbdced5425972d7f352ffd3bee6fdf6b8aea90bd1e6dcc`가 일치했다. 검색 설정은 고정 Sol 재작성, HyDE off, BM25 후보 20·top 5·최소 점수 0.5·가중치 0.25다. [정제 결정](../data/eval/stack-selection/final_search_v1/curation.json)
- 등록한 출처에서 실제 T15 검색을 적용했을 때 독립 8문항 모두에서 지정 원문 구간을 확보했다. 기존 100문항의 T15 보존 재작성으로 회귀한 결과, 선택 청크와 순서는 97문항에서 일치했다. `Q015`, `Q021`, `Q065`에서 선택 청크나 순서가 바뀌었으며, 100문항 모두의 T15 원문 ID 지표와 첫 골드 순위는 일치했다. [독립 검색 기록](../data/eval/stack-selection/final_search_v1/search_inputs.jsonl.gz) · [100문항 검색 회귀](../data/eval/stack-selection/final_search_v1/regression.json)
- 기본 라우터는 F01~F05·F07·F08을 지정 검색 출처로 보내며, 글 번호가 없는 F06은 `DOC_QA`로 분류해 RawPedia 검색으로 보낸다. 이번 F06의 GitHub 검색과 두 모델의 답변은 평가용으로 등록한 GitHub 출처에서 실행했다. F06의 기본 라우팅, 전체 경로에서의 답변 회귀, 정식 T23 평가에는 후속 검증이 필요하다. 생성 모델 인수 후보는 `codex-cli / gpt-5.6-terra / t17-answer-v1`이다. [라우터 경로 정의](../src/artagent/graph/graph.py#L78)

## 재현

준비와 비교는 파이프라인 의존성이 들어 있는 프로젝트 Python 3.14 venv에서 실행한다. `--summary`는 보존 결과에서 수치를 다시 계산한다.

```bash
venv/bin/python -B scripts/compare_rag_models.py \
  --output-dir data/eval/stack-selection/pilot_v1 --summary
venv/bin/python -B scripts/compare_rag_models.py \
  --output-dir data/eval/stack-selection/final_v1 \
  --final-search data/eval/stack-selection/final_search_v1/search_inputs.jsonl.gz --summary
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 venv/bin/python -B scripts/prepare_rag_selection.py \
  --output-dir build/rag-stack-regression --regression
```
