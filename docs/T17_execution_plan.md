# Task 17 실행 플랜 — 답변 생성과 출처 인용

작성일: 2026-10-15. 담당: 김구. 이 문서는 실행 계획이며, 구현·실제 답변 실행·그래프 연결의 완료 기록이 아니다.

## 1. 근거와 범위

필수 근거는 [Task 17 전문](../tasks/todo.md#task-17-답변-생성출처-인용-a-17)과 지정된 [T14 인계 §2](/Users/user/orca/workspaces/AAART/T14-rewrite-hyde/docs/T14_conn_handoff.md#2-t17--실제-답변인용-연결)다. 현재 작업 위치의 [동일 인계](T14_conn_handoff.md#2-t17--실제-답변인용-연결)와 내용이 같은 것을 확인했다. 구현 경계는 [T11 헬퍼](../src/artagent/answer.py), [현재 상태 스키마](../src/artagent/graph/state.py), [검색 어댑터](../src/artagent/graph/search.py), [T13-2 전이](../src/artagent/graph/graph.py), [라우터 설계](langgraph_router_design.md)를 따른다.

목표는 검증된 `RetrievalBundle`에서 답변 프롬프트·생성·인용 검증만 수행하는 단독 모듈을 만들고, 근거 충분·명시적 미지원·근거 부족을 구별하여 반환하는 것이다. 근거 부족에는 사용자에게 모른다는 안내와 코드가 읽을 수 있는 상태를 함께 반환한다. 단독 검증을 통과한 뒤 T13-2의 `ANSWER` 교체를 준비한다.

이번 작업의 변경 산출물은 **이 플랜 문서 한 개**다. 아래 구현·테스트·실행 산출물은 후속 구현 시 작성한다. T15 검색 튜닝, T16 재검색, 프로필·렌더, 코어 변경은 포함하지 않는다. 검색 점수·골드 도달만으로 답변 상태를 정하거나 CP3 완료를 선언하지 않는다.

## 2. 입력·출력 계약

### 2.1 단독 입력과 그래프 입력

후속 핵심 산출물은 `src/artagent/graph/answer.py`다. 단독 호출은 현재 항목의 원질문·확정 문맥, `RetrievalBundle`, 생성 콜백, 원문 검증용 `source_root`를 받는다. 그래프용 팩터리 `create_answer_node(...)`는 같은 단독 경로를 감싸 `AgentState → 부분 state 갱신`을 제공한다. 이 이름은 구현 예정이며 현재 존재하는 함수로 취급하지 않는다.

| 입력 | 형식·사용 규칙 |
| --- | --- |
| 답변할 질문 | `decision.plan[cursor].query`를 우선 사용하고, 단독 호출에서는 같은 원질문을 명시한다. 전체 혼합 요청과 현재 항목을 혼동하지 않는다. |
| 확정 문맥 | 요청의 OS·ART 버전·확정 목표와 제약. 원문 근거와 구분하여 프롬프트에 표시한다. |
| `RetrievalBundle.query` | 실제 검색에 사용한 문자열. 재작성 결과일 수 있으므로 원질문을 대체하지 않고 검색 실행 정보로 보존한다. |
| `source_filter` | `RAWPEDIA` 또는 `GITHUB`. 현재 항목의 처리 경로 및 각 근거의 `source_type`과 일치해야 한다. |
| `hits` | 검색 순서대로 평탄화된 `list[Evidence]`. 청크 수가 아니라 세그먼트 수이므로 다섯 개로 잘라서는 안 된다. 정상적인 빈 배열도 허용한다. |
| `snapshot_ref` | 검색 스냅샷 식별값 그대로 기록한다. 독립 파일 경로나 원문 파일 해시로 해석하지 않는다. |
| `Evidence` 식별값 | `chunk_id`, `doc_id`, `source_group_id`, `source_type`, `source_path`, `target_url`, `product_scope`를 변경 없이 전달·기록한다. |
| `Evidence.text` | 해당 원문 세그먼트 전체 본문. 청크 전체 본문이라고 간주하거나 요약·절단하지 않는다. |
| `source_location` | `section_title`과 전체 `source_segment`를 담은 정규 JSON 문자열. 파싱한 위치 정보와 원래 문자열을 모두 보존한다. |

bundle의 `query`, `source_filter`, `snapshot_ref`와 Evidence의 식별·출처·본문 필드는 문자열이다. `source_segment`에는 `doc_id`, `source_path`, `target_url`, `json_pointer`, `char_start/end`, `byte_start/end`, `content_char_start/end`, `source_file_sha256`, `segment_sha256` 및 존재하는 `ref_id`, `body_sha256` 등이 있다. 범위 값은 정수이며 `json_pointer`는 Markdown에서 `null`, JSON 본문에서 `/body`다. 표시 제목에는 `section_title`을 사용하되, 이를 실제 인용 위치 대신 저장하지 않는다. RawPedia의 `product_scope=RawTherapee`와 GitHub의 `ART` 범위를 유지한다. 누락된 제품 범위를 임의로 ART로 채우지 않는다.

입력 검증은 필수 필드·타입·출처·위치 JSON, Evidence와 세그먼트 사이의 ID/경로/URL 일치, 본문 해시를 확인한다. 지정된 원문 루트에서 파일 해시·JSON pointer·문자/바이트 범위와 본문도 대조한다. 불일치나 읽기 실패는 오류다. `retrieval=None`은 정상 빈 검색과 구분한다.

### 2.2 출력과 상태 갱신

정상적인 의미 판정은 기존 `AnswerResult(status, text, citations, applicability, actionable_goal)`로 반환한다. `status`는 기존 세 값만 사용한다. `text`는 인용을 치환한 한국어 답변이며 `applicability`에 실제 근거의 제품·버전·스냅샷 범위를 적는다. 질문이 RawPedia 설명 자체를 묻는다면 RawTherapee 참고 범위의 답변이 가능하다. ART 적용을 묻는데 RawTherapee 자료만 있으면 ART 지원을 확정하지 않는다. 실행 목표를 새로 추론하지 않으며 `actionable_goal`은 기본 `None`이다.

기술 실패는 `AnswerResult.status`에 새 값을 추가하지 않고 `answer=None`, `ErrorInfo(node="ANSWER", code, message, recoverable=False)`로 반환한다. 후속 `StepResult.status=FAILED`와 응답의 실패 상태로 연결한다. 오류 코드 계획은 입력·원문 불일치 `ANSWER_INPUT_INVALID`, 생성·응답 스키마 실패 `ANSWER_GENERATION_FAILED`, 인용 계약 위반 `ANSWER_CITATION_INVALID`다.

그래프 어댑터는 성공 시 `answer`·`error=None`·`trace`를, 오류 시 `answer=None`·`error`·`trace`를 갱신한다. 이전 항목의 답변이나 오류를 재사용하지 않는다. `request`, `decision.plan`, `cursor`, `retrieval`, `research_count`는 변경하지 않는다. 선행 `REWRITE_FAILED`·`SEARCH_UNAVAILABLE`가 있으면 이를 보존하고 생성하지 않는다.

## 3. RetrievalBundle → T11 헬퍼 연결

### 3.1 현재 헬퍼와 필요한 최소 확장

현재 `build_prompt_and_citations(query_normalized, hits)`의 `hits`는 T9 `SearchHit` 목록이며, 생성 헬퍼 `generate_llm_response(...)`는 `answer`·`citation_ids`를 요구한다. 따라서 현재 `RetrievalBundle.hits`를 그대로 넘기거나 기존 생성 출력만으로 상태 계약이 완성됐다고 보아서는 안 된다.

후속 구현에서는 T11 문맥 구성 헬퍼에 **세그먼트 입력 경로**를 추가하고, 기존 `SearchHit` 입력·기본 프롬프트는 유지한다. 그래프 모듈은 Evidence를 제목·본문·식별값·원문 위치·제품 범위를 갖춘 세그먼트 레코드로 투영해 이 경로에 전달한다. 원래 청크의 직렬화 헤더·전체 본문·거리·순위는 bundle에 없으므로 가짜 `SearchHit`을 만들거나 잃은 값을 복원했다고 기록하지 않는다.

T17용 프롬프트·응답 계약은 `t17-answer-v1`로 구분한다. 생성 헬퍼에는 명시적인 T17 응답 스키마 선택을 추가하여 `status`, `answer`, `citation_ids`를 요구한다. 내부의 최종 출력 지시·파서·실행 로그 검증도 같은 스키마를 사용한다. 현재의 두 키 전용 지시 뒤에 상태 요구만 덧붙이는 방식은 사용하지 않는다. T11 기본 호출과 기존 기록의 재검증은 기존 계약을 유지한다. 이 최소 확장 외에 T11 검색·CLI 동작을 바꾸지 않는다.

### 3.2 호출 순서와 호출 수

1. 현재 항목의 원질문·확정 문맥을 선택하고 T11 `normalize_query`로 기본 정규화한다. T14 재작성·HyDE를 다시 실행하지 않는다.
2. 입력 bundle과 원문 대응을 검증하고, 각 Evidence를 고유 인용 ID에 연결하는 불변 매핑을 만든다. 빈 검색과 입력 손상을 분리한다.
3. T11의 확장된 `build_prompt_and_citations`로 전체 세그먼트 문맥·인용 목록을 구성한다. `product_scope`와 위치 정보를 프롬프트에 포함한다.
4. T11 `SYSTEM_INSTRUCTION`의 근거 제한·제품 범위·문맥 내 명령 무시 규칙에 T17 상태 조건을 더해 `generate_llm_response`를 **한 번** 호출한다. 별도 상태 분류 생성이나 형식 복구 재호출을 하지 않는다.
5. `status` 열거값, 비어 있지 않은 문자열 `answer`, 문자열 배열 `citation_ids`를 검사하고 T11 `validate_and_format_citations`로 표식·목록·URL을 검증·치환한다. 상태별 인용 개수 조건도 검사한다.
6. 사용한 인용을 기존 `Citation(doc_id, title, url, source_location)`으로 변환하여 `AnswerResult` 또는 오류를 반환하고 관측 기록을 남긴다.

**`run_pipeline` 호출은 금지한다.** 단독 모듈과 `ANSWER` 안에서 `open_store`, 임베딩 로드, `store.search`도 호출하지 않는다. 검색은 상위 T14/T9 경로에서 이미 끝났다. 호출 계수 테스트로 단독 답변의 검색 0회·재작성 0회·생성 1회를 증명한다. 입력·선행 오류는 생성 0회다. 정상 빈 검색도 T11과 같은 1회 생성 경로를 사용하며, 허용되는 의미 상태는 `INSUFFICIENT_EVIDENCE`다. 문맥 한도를 넘으면 절단하지 않고 오류를 반환한다.

## 4. 세 처리 결과와 상태 전이

요구된 세 처리 결과는 아래와 같다. 첫 결과 안에서 긍정 답변과 반증 답변을 구별하므로, 기존 세 가지 답변 의미 상태와 기술 오류가 섞이지 않는다.

| 처리 결과 | 반환 계약 | 진입 조건·사용자 안내 |
| --- | --- | --- |
| 정상 답변 | `AnswerResult.status=SUPPORTED` 또는 `UNSUPPORTED`, `error=None` | 긍정 근거 또는 직접 반대 근거로 답할 수 있으며 인용 ≥1. 적용 범위와 근거에 따른 결론을 설명한다. |
| 근거 부족 상태반환 | `AnswerResult.status=INSUFFICIENT_EVIDENCE`, `error=None` | 빈 검색, 무관한 문맥, 복합 질문의 핵심 조건 누락, 제품·버전 적용 불확실 등으로 답을 확정할 수 없음. “모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.”라는 취지의 안내를 포함한다. 인용 0개를 허용하되 부수 사실을 설명하면 그 사실도 인용한다. |
| 실패·에러 | `answer=None`, `ErrorInfo`; 항목은 `FAILED` | 입력·원문 무결성 실패, 생성 시간 초과·프로세스/제공처 오류, JSON/타입/상태 오류, 미지 인용·표식 불일치 등. 실패 이유를 반환한다. 근거 부족으로 바꾸지 않는다. |

`SUPPORTED`는 질문의 주요 사실·절차를 해당 제품 범위의 근거가 뒷받침할 때 반환한다. `UNSUPPORTED`는 질문 전제가 지원되지 않는다는 직접 반대 근거가 있을 때 반환하고 해당 스냅샷에서 불가한 이유를 설명한다. 문서에 없다는 사실만으로 미지원이라 단정하지 않는다.

프롬프트에서 위 조건에 따라 `status`를 명시적으로 반환하게 하고 코드가 구조·인용 조건을 검사한다. 인용 없는 `SUPPORTED`/`UNSUPPORTED`나 빈 검색에서의 긍정·미지원 선언은 계약 오류로 거부한다. 상태를 답변의 특정 단어, 검색 거리, Hit, 골드 도달로 추정하거나 강제로 승격하지 않는다. 실제 주장과 상태의 의미적 정합성은 원문 대조로 검토한다.

| 현재 조건 | 단독 검증의 종료 | T13-2 연결 후 기존 전이 |
| --- | --- | --- |
| `SUPPORTED` | 결과 반환 | `ANSWER → ADVANCE`, 항목 `SUCCEEDED` |
| `UNSUPPORTED` | 반증 답변 반환 | `ANSWER → FALLBACK → ADVANCE`, 항목 `UNSUPPORTED`; 재검색 없음 |
| `INSUFFICIENT_EVIDENCE`, `research_count=0` | 부족 상태 그대로 반환 | T16 연결 후에만 `ANSWER → RESEARCH`로 요청 전체 추가 검색 1회 |
| `INSUFFICIENT_EVIDENCE`, `research_count=1` | 부족 상태 그대로 반환 | `ANSWER → FALLBACK → ADVANCE`, 부족 상태로 종료 |
| 기술 오류 또는 선행 검색 오류 | 오류 반환 | `FALLBACK → ADVANCE`, 항목 실패; 재검색 없음 |

T17은 `research_count`를 증가시키거나 재검색을 실행하지 않는다. 현재 T13-2의 `RESEARCH`는 대역이므로, T16 연결 전에는 근거 부족 전이를 대역으로 검증한 결과와 실제 폴백 실행을 구분한다. T16은 명시적인 부족 상태만 소비하고 추가 재작성·검색·답변을 한 번 수행한다. 미지원·기술 오류에서 이를 실행하지 않는다.

## 5. 인용 포맷과 근거 매핑 검증

내부 표식은 T11과 같은 `[C1S1]` 형태다. `C` 번호는 bundle에서 서로 다른 `chunk_id`가 처음 나타나는 순서, `S` 번호는 그 청크 안 세그먼트 순서로 부여한다. 이를 bundle에 없는 원래 검색 rank라고 기록하지 않는다. 세그먼트마다 ID가 유일해야 하며, 문맥 순서를 유지한다.

최종 본문 표시는 **`[출처: 문서명·URL]`**로 고정한다. 예: `[출처: Exposure·https://rawpedia.rawtherapee.com/exposure/]`. 표시명은 `section_title`을 바탕으로 GitHub에서는 `doc_id`/`ref_id`를 덧붙여 본문과 댓글을 구별한다. URL은 `Evidence.target_url`과 그 안의 실제 댓글 앵커를 그대로 사용한다. 생성 응답이 URL·표시명·위치를 새로 결정하지 않는다.

| 검증 층 | 방법·합격 기준 |
| --- | --- |
| 표식·목록 | 본문의 인용 ID 집합 = `citation_ids` 집합, 모든 ID가 이번 문맥 매핑에 존재. 모르는 ID·누락 표식·임의 URL·필수 표시명 누락은 거부한다. |
| 상태·개수 | `SUPPORTED`와 `UNSUPPORTED`의 사용 인용 ≥1. `INSUFFICIENT_EVIDENCE`는 빈 배열 가능. 잘못된 인용을 삭제하거나 출처를 임의 보충해 통과시키지 않는다. |
| 인용 → Evidence | 사용 ID마다 `chunk_id`, `doc_id`, `source_group_id`, `source_path`, `target_url`, `product_scope`, 원래 `source_location`과 본문 해시를 역추적한다. 공개 `Citation`에 없는 필드는 관측 기록의 매핑에 보존한다. |
| Evidence → 원문 | 파일 SHA 확인 → Markdown 전문 또는 JSON pointer의 본문 선택 → 문자 범위 추출 → UTF-8 바이트 범위 대조 → 추출 본문과 `Evidence.text`, `segment_sha256` 일치 확인. JSON 본문의 `body_sha256`도 있으면 검사한다. |
| 좌표 구별 | `content_char_start/end`는 원래 청크의 좌표로 보존한다. 이를 독립 `Evidence.text`의 로컬 오프셋으로 사용하거나 0부터 다시 쓰지 않는다. 원문 대조는 `char_start/end`, `byte_start/end`로 수행한다. |
| 주장 → 원문 | 주요 사실·각 절차·반증을 해당 인용 본문과 제품·버전 범위까지 대조한다. URL의 형식이 맞거나 같은 문서 ID라는 이유만으로 통과시키지 않는다. |

같은 ID의 반복 사용만 목록에서 한 번으로 줄인다. 같은 문서·URL이라도 다른 댓글·범위·세그먼트는 별개로 유지한다. 모든 검색 결과를 사용한 출처처럼 나열하지 않는다. 원문 무결성 검사와 주장에 대한 의미 검토 결과를 각각 기록한다.

## 6. Slice 1 동일 15개 대조 계획

### 6.1 고정 기준선과 실행 조건

기준선은 [T11 계획 §4.2·§6](T11_execution_plan.md), [기존 15개 기록](T11_execution_records.jsonl), [T11 검증 결과 §9](T11_fix_plan.md), [T14 검색 30개 기록](../data/eval/t14-conn/conn_20261015_pr/slice1_search.jsonl)이다. 기존 T11 기록 SHA-256은 `5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7`이며 원본을 덮어쓰지 않는다.

질문 원문은 `/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/search_eval_queries.json`에서 읽는다. 로컬 [동일 질문셋](search_eval_queries.json)의 SHA-256도 `91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8`임을 확인했다. 실행 전후 SHA와 원문 일치를 확인한다. 골드 문서 ID·근거 구간·`expected_behavior`·질문 ID는 사후 대조에만 사용하고 생성 입력에 넣지 않는다.

고정 ID와 순서: **Q001, Q004, Q014, Q021, Q033, Q044, Q054, Q063, Q072, Q080, Q084, Q086, Q092, Q093, Q096**. RawPedia 10개·GitHub 5개이며 성공 사례로 교체하지 않는다.

먼저 기존 T11 `SearchHit`을 T14의 `search_hits_to_evidences`로 변환한 bundle 15개에서 단독 답변을 실행하여, 검색 문맥을 고정한 T11→T17 차이를 확인한다. 이어 T14의 A(off)·B(on) bundle 각각 15개에서 같은 단독 답변 경로를 실행한다. 저장된 bundle을 답변 입력으로 재생하는 것이며 저장된 대역 답변을 실제 생성 결과로 사용하지 않는다. 각 실행은 검색 0회·생성 1회다.

T14 인수 설정은 `rewrite_enabled=True`, `hyde_enabled=False`이며 off 대조도 유지한다. 생성 기준은 T11 기록의 `codex-cli`·`gpt-5.6-sol`이며 A/B에는 동일 제공처·모델·설정·T17 프롬프트 버전을 사용한다. 실행 전에 실제 사용 가능 여부와 설정을 확인하고, 변경이 필요하면 이유와 T11 대비 차이를 별도 조건으로 고정한다. T14 팩터리의 기본 off는 변경하지 않는다. 서비스 검색과 묶는 최종 확인에서도 최초 검색은 항목별 1회, `ANSWER` 내부 검색은 0회여야 한다.

T11의 한계 답변과 T14에서 새로 도달한 근거의 차이를 분리하여 기록한다. 문장 완전 일치나 과거 한계 답변의 반복을 동등성 기준으로 삼지 않는다. 기존 15개·A/B는 독립 표본으로 합산하지 않으며 확대 평가나 최종 스택 선정으로 보고하지 않는다.

### 6.2 지정 질문의 예상 결과와 판정

| 질문·기준선 | 예상 결과 | 통과·실패 기준 |
| --- | --- | --- |
| **Q001** — 기존 `run_1791816326_4bfaeb47`: Auto Levels가 히스토그램을 분석해 Exposure 설정을 조정, 인용 1개 | T11 문맥 재생·T14 A/B 모두 `SUPPORTED`. `Exposure`의 Auto Levels 사실과 RawTherapee 참고 범위를 유지 | 히스토그램 분석과 Exposure 조정이 원문에서 나오고 인용 ≥1이며 URL·위치가 일치하면 통과. ART UI·기능 지원 확정으로 확대하거나 핵심 사실을 잃으면 실패 |
| **Q086** — 기존 `run_1791816457_7032ccae`: #442 미검색, RawPedia 참고 1건만 인용하며 한계 안내 | T11 문맥 재생은 `INSUFFICIENT_EVIDENCE` 유지. T14 A/B에는 #442 본문과 `discussion-comment:DC_kwDONWPV1M4A7gGl`가 있으므로 `SUPPORTED` 기대 | T14 답변은 마스크에 이름을 주면 Linked mask로 나타남과, 원래 마스크 도구/영역보다 뒤에 있는 후속 도구에서만 사용하며 화면 위→아래 순서가 처리 순서라는 조건을 설명해야 함. 댓글 앵커 `#discussioncomment-15597989`까지 연결. 근거에 없는 이름 입력 UI 조작을 만들면 실패. 충분한 댓글이 있는데 부족 상태로만 끝나면 개선 기대 미달로 기록 |
| **Q096** — 기존 `run_1791816494_ebbb5582`: Issue #500 본문·댓글 2건으로 슬라이더 전제 반증 | 반증이 있는 T11 문맥·T14 A/B 모두 `UNSUPPORTED`. 해당 스냅샷에서 별도 옵션 없이 품질이 visually lossless로 고정됨을 설명 | 인용 ≥1과 반증 댓글 `#issuecomment-4711197631` 매핑 확인. JXL 품질 슬라이더 활성화·50 설정 절차를 만들면 실패. 반증을 제거한 별도 단위 입력만 `INSUFFICIENT_EVIDENCE`를 기대하며, 반증 부재를 미지원 근거로 쓰지 않음 |

Q096은 `gold_support_doc_ids=[]`인 반증 사례이므로 양성 검색 Hit로 세지 않는다. Q086도 과거 미도달 사실만으로 현재 답변을 부족 상태로 고정하지 않는다. 상태는 매 실행에 실제 제공된 근거에 따라 판단한다.

### 6.3 전수 대조와 수동 검토

15개 전부에서 원질문·검색 문맥·답변 주요 사실·의미 상태·적용 범위·사용 인용의 원문 연결을 T11과 비교한다. T17 단독 경로 안의 검색·재작성 호출은 모두 0, 구조·출처 매핑·제품 범위 위반은 0이어야 한다. 근거가 충분한 양성 답변의 퇴행, 거짓 절차, 반증의 긍정 전환은 불합격이다. Q044 등 기존 부족 사례도 실제 새 문맥에 따라 판정하고 부족 상태 자체를 기술 실패로 세지 않는다.

수동 지정 3개는 Q001·Q086·Q096이다. CP2 양성 5개 **Q001·Q004·Q014·Q054·Q063**에서는 T14 A/B 각각 주요 사실·제품 범위·인용이 있는 근거 답변을 확인한다. Q086·Q096은 기존 CP2 양성 수를 대신하지 않는다. 이들은 동일 15개의 부분집합이다. 실제 run ID·검토 주장·인용 ID·원문 위치·판정 이유를 남긴 뒤에만 검토 완료로 표시한다.

제품 범위 추가 회귀로 T14의 Q010·Q077 bundle을 점검한다. 실제 RawTherapee 근거를 ART 지원 확정으로 바꾸지 않는지 확인하며, 순위 1·3이라는 이유로 답변 성공을 선언하지 않는다. 이 둘은 고정 Slice 1 15개나 독립 평가 수에 추가하지 않는다.

## 7. T13-2 연결 전 단독 검증 → 연결 준비

순서는 **계약·매핑 단위 검증 → 생성·상태 단독 검증 → 실제 Slice 1 대조 → 연결 준비**다. 단계별 실패 원인을 고친 뒤 해당 게이트를 통과하며, 부족 상태를 감추려고 검색 설정을 바꾸지 않는다.

| 단계·의존 | 후속 작업·예상 파일 | 합격 기준·검증 |
| --- | --- | --- |
| 1. 입력·인용 매핑 (S, T11·T14 인수) | `graph/answer.py`와 `tests/test_graph_answer.py`에 단독 bundle 경계·세그먼트 투영 검증 준비 | 두 출처 정상·빈 hits·같은 청크의 복수 댓글 통과. 위치 JSON 손상·ID/URL/해시 불일치는 생성 전 거부. 서로 다른 범위가 병합되지 않음 |
| 2. 생성·세 상태 (M, 단계 1) | T11 순수 헬퍼 최소 확장과 그래프 답변·상태 검사, 관련 테스트 | 주입한 생성 응답으로 긍정·반증·부족·오류 각각 확인. 검색/임베딩/재작성/`run_pipeline`을 호출하면 즉시 실패하는 대역을 두고 호출 수 단언. 기존 `tests/test_answer.py`도 통과 |
| 게이트 A: 단독 계약 | 단계 1~2 집중 테스트 | T11 기본 CLI·프롬프트·기존 15개 원본 불변, 원문/제품 범위 보존. 실제 저장소·모델·외부 생성 호출 없이 실행 가능 |
| 3. 실제 생성 대조 (M, 게이트 A) | 계획된 `scripts/check_t17_answer.py`, `data/eval/t17-answer/<run>/` | §6의 T11 문맥 15개 및 A/B 30개 실제 생성, 수동 3개·CP2 5개 검토와 원문 매핑 통과. 실패 시 원인·원응답을 보존 |
| 게이트 B: 연결 준비 | 단독 계약과 실제 검토 보고서, 상태·오류·호출 계약 인계 | 모든 필수 검토가 통과하고 미검증을 완료로 표시하지 않음. T16 소비 상태와 T13-2 override 인자가 명확함 |
| 4. T13-2 접합 확인 (S, 게이트 B 뒤 별도 연결) | `create_router_graph(node_overrides={..., "ANSWER": ...})`에 실노드 주입, 라우터·검색 연결 회귀 | 기존 경로 20개·혼합/모호 요청 보존, 항목 답변/오류 혼선 없음. 부족 count=0/1 및 미지원·기술 오류의 전이를 대역으로 확인. 실제 재검색 완료는 T16 연결 후 검증 |

단계 2의 필수 반례는 미지 상태·누락 status·잘못된 타입·빈 답변, 미지 인용·표식/목록 불일치, 인용 없는 긍정/반증, 원문 없는 ART 단정, 복합 질문의 일부 근거만 있는 경우, 시간 초과·프로세스 오류다. 각 반례와 함께 정상 대조 입력도 통과시켜 모든 응답을 거부하는 구현을 방지한다. 오류 때 이전 답변이 남지 않고 `research_count`가 0/1 그대로인지 검증한다.

구현 후 집중 검증 명령은 다음과 같다. 이번 문서 작업에서 실행했다고 기록하지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python -m pytest -p no:cacheprovider tests/test_graph_answer.py tests/test_answer.py -q
```

연결 준비 뒤에는 같은 환경으로 `tests/test_router.py`, `tests/test_router_contracts.py`, `tests/test_graph_search_connection.py`를 실행한다. 단독 pytest에는 실제 생성·모델 로드·Chroma 생성이 없고, 실제 생성 평가는 단계 3의 별도 실행기로 기록한다. 원문·질문셋·기존 기록은 읽기 전용으로 사용한다.

## 8. 후속 산출물과 완료 판단

| 산출물 | 내용 |
| --- | --- |
| **`src/artagent/graph/answer.py`** | bundle 기반 단독 답변 경로, T11 헬퍼 연결, 세 의미 상태와 기술 오류, 노드 팩터리 |
| `src/artagent/answer.py` 최소 보완 | 세그먼트 입력·T17 응답 스키마의 명시적 선택. 기존 기본 계약은 회귀 검증 |
| `tests/test_graph_answer.py` 및 필요한 T11 회귀 | 매핑·상태·오류·제품 범위·호출 수·state 보존 검증 |
| `scripts/check_t17_answer.py` | 고정 입력 읽기, bundle 재생과 실제 답변 실행, 저장 기록 독립 검증. 세부 CLI는 구현 시 확정 |
| `data/eval/t17-answer/<run>/` | 기준선 파일 SHA·코드/모델/설정·프롬프트 버전, 실행별 원질문/문맥/bundle, 실제 전달 프롬프트·생성 원응답·상태·호출 수·시간, 사용 인용 전체 매핑, 수동 판정, 비교 보고서 |

관측 기록에는 입력 구분(T11 문맥/A/B), query/run ID, 원본 기록 run ID, 스냅샷, `product_scope`, 전체 원문 세그먼트, 생성의 실제 제공처·설정·확인 가능한 사용량을 담는다. 미제공 값은 `null`, 미검토는 `pending`으로 남긴다. 공개 `Citation`에 없는 provenance를 별도 매핑에 보존하여 최종 출력에서도 원문으로 역추적한다. 자격증명은 기록하지 않는다.

후속 T17의 연결 준비 완료는 게이트 A·B, 고정 15개 대조와 지정 수동 검토, CP2 양성 5개 근거 답변, 오류/부족 구분의 증거가 있을 때 판정한다. T14 검색 대역의 `ANSWER`나 집계 검색 지표는 답변 검증을 대신하지 않는다. T13-2 실노드 접합과 T16 실제 폴백 회귀까지 확보한 뒤 CP3를 별도로 판단한다.

이번 플랜 작성의 검증은 요구 항목·참조·기준선 ID/해시 대조와 문서 diff 점검으로 한정한다. 커밋 대상은 `docs/T17_execution_plan.md` 하나이며 메시지는 `docs: Task 17 실행 플랜 추가`로 고정한다.
