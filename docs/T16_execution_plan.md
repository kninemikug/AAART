# Task 16 실행 계획 — 근거 부족 1회 재검색 폴백

작성일: 2026-11-04. 이 문서는 후속 구현·검증 계획이다. 이번 산출물은 이 문서 한 개이며 코드 구현, 테스트 추가, 기존 작업 카드 수정, push·PR은 수행하지 않는다.

## 1. 기준과 최소 범위

요구사항은 다음 기준으로 한정한다.

- [Task 16 카드](../tasks/todo.md#task-16-근거-부족-1회-재검색-폴백-a-16): 근거 부족에서만 재작성→재검색→재답변을 정확히 1회 수행하고, 재차 부족하면 종료한다.
- [WBS A-16](ART_agentic_wbs.md#5-phase-a--④-art-master-agent-91--101-70h): 산출물은 근거 부족 1회 재검색 폴백 노드다.
- [T14-CONN 인계 §2](T14_conn_handoff.md#2-t17--실제-답변인용-연결): 기존 검색 bundle과 출처를 보존하고 T17의 세 가지 의미 상태를 소비한다. §2의 검색 미도달·순위 저하 사례는 T15 입력이며 T16에서 튜닝하지 않는다.
- 같은 인계 [§3](T14_conn_handoff.md#3-t16--근거-부족-1회-폴백): 요청 전체 예산, 중복 변환 방지, 혼합 항목·재개 계약을 따른다.
- [CP3 체크리스트](../tasks/todo.md#checkpoint-cp3--slice-2-w3-말): 세 처리 경로 분기, 1회 폴백 재현, 그래프 경유 Slice 1 동등 이상을 함께 확인한다.

지시된 `tasks/todo.md` 180~187행은 현재 Task 16 위치와 다르다. 점검 시 Task 16은 230~238행이며 제목으로 식별했다. WBS에는 `CP3`라는 표기가 없으므로 WBS W3의 A-13~A-17과 위 CP3 체크리스트를 연결해 읽는다. 문서의 행 이동을 기능 범위 변경으로 해석하지 않는다.

최소 구현은 **기존 T14 재작성, T15 검색 설정, T17 답변을 그대로 사용해 추가 시도 한 번을 연결하는 것**이다. 직선 호출 순서로 먼저 검증한 뒤 기존 T13-2 그래프에 접합한다. T14 최초 검색의 재작성 on/off와 무관하게 폴백은 재작성 on·HyDE off로 한 번 수행한다. 최초 검색 팩터리의 기본 off는 유지한다.

점수·거리·순위·Hit·골드 도달 여부로 답변 신뢰도를 판정하지 않는다. 검색 설정·리랭킹·top-k·임계값 변경, 추가 재시도, HyDE 도입, 새 의존성·모델 선정, 프로필 생성·렌더링 변경은 범위 밖이다. `rtengine/`, `rtgui/`, 프로필 형식·처리 의미를 변경하지 않으므로 PPVERSION 변경도 필요하지 않다.

## 2. 현재 소스와 연결 지점

| 확인한 소스 | 현재 동작과 후속 연결 |
| --- | --- |
| `src/artagent/graph/answer.py` | `create_answer_node()`는 `RetrievalBundle`을 받아 `answer`, `error`, `trace`만 갱신한다. `SUPPORTED`·`UNSUPPORTED`·`INSUFFICIENT_EVIDENCE`를 구분하며 검색을 수행하지 않는다. 이 계약을 유지한다. |
| `src/artagent/graph/rewrite.py` | T14 실제 구현이다. `prepare_search_input()`과 `SearchInput`을 재사용하고 제품명·파일명·버전·숫자·확정 문맥 보존 검사를 유지한다. |
| `src/artagent/graph/research.py` | 현재 파일이 없다. T14 구현 파일로 간주하지 않고 T16의 추가 입력 준비 노드로 신설한다. |
| `src/artagent/graph/graph.py` | `route_after_answer()`에 count=0인 근거 부족→`RESEARCH`, count 소진→`FALLBACK` 분기가 이미 있다. `RESEARCH` 후에는 현재 항목의 RawPedia/GitHub 검색으로 돌아간다. |
| `src/artagent/graph/nodes.py` | 기본 `research_node()`는 `CAPABILITY_UNAVAILABLE`을 반환하는 미구현 노드다. `INTAKE`는 count를 보존한다. `DISPATCH`는 항목 임시값을 지우며, `ROUTE`의 재개 건너뛰기는 현재 `SUCCEEDED`에 한정된다. |
| `src/artagent/graph/search.py` | 매 호출마다 `prepare_search_input()`을 실행한다. 재검색 입력을 별도로 준비한 뒤 그대로 호출하면 재작성이 중복되므로 준비된 입력을 소비하는 최소 분기가 필요하다. |
| `src/artagent/graph/state.py` | `research_count`와 `step_results`는 있지만 항목·시도별 준비 입력 필드는 없다. |

연결은 기존 `create_router_graph(node_overrides=...)`를 사용한다. `create_search_nodes(...)`, `create_answer_node(...)`, 새 `create_research_node(...)`를 같은 그래프에 주입한다. 기본 미구현 노드를 실제 연결 완료로 보고하지 않으며, 답변에서 전체 `run_pipeline()`을 호출해 검색을 중복하지 않는다.

## 3. 상태 전이와 요청 예산

### 3.1 답변 상태별 edge

| 현재 결과 | `research_count` | 다음 노드 | 추가 재검색 |
| --- | --- | --- | --- |
| `error` 존재 | 무관 | `FALLBACK` | 없음. 기존 기술 오류를 보존한다. |
| `SUPPORTED` | 0 또는 1 | `ADVANCE` | 없음 |
| `UNSUPPORTED` | 0 또는 1 | `FALLBACK` | 없음. 미지원은 재검색 대상이 아니다. |
| `INSUFFICIENT_EVIDENCE` | 0 | `RESEARCH` | 준비 성공 시 재작성·검색·답변 각 1회 |
| `INSUFFICIENT_EVIDENCE` | 1 | `FALLBACK` | 없음. 해당 상태와 부족 안내를 반환한다. |
| 답변 누락·잘못된 상태 또는 유효하지 않은 예산 | 무효 | 오류 종료 경로 | 없음. 근거 부족으로 바꾸지 않는다. |

정상 흐름은 다음과 같다. 검색 노드 선택은 현재 `decision.plan[cursor].path`를 사용하며 출처를 바꾸지 않는다.

```text
DISPATCH → SEARCH_RAWPEDIA 또는 SEARCH_GITHUB → ANSWER
  SUPPORTED → ADVANCE
  UNSUPPORTED 또는 기술 오류 → FALLBACK
  INSUFFICIENT_EVIDENCE, count=0
    → RESEARCH: T14로 입력 준비, count=1
    → 같은 출처의 SEARCH: 준비된 입력으로 1회 검색
    → ANSWER: 새 bundle로 1회 답변
      SUPPORTED → ADVANCE
      UNSUPPORTED / INSUFFICIENT_EVIDENCE / 기술 오류 → FALLBACK
FALLBACK → ADVANCE → 남은 항목 또는 RESPOND → END
```

단일 항목의 반복 부족 결과는 `response.status=INSUFFICIENT_EVIDENCE`와 해당 `StepResult.answer`를 보존한다. `FALLBACK`은 재검색 노드가 아니며 `ADVANCE`와 `RESPOND`는 결과 기록·집계만 수행한다. 혼합 요청에서는 현재 항목의 추가 시도를 즉시 끝내고, 다른 독립 항목의 최초 처리는 계속한다. 선행 항목이 필요한 실행은 기존 의존성 검사로 차단한다.

### 3.2 count 갱신 책임

- 새 요청의 `research_count` 기본값은 0이며 요청 전체에서 추가 시도는 최대 1회다. 저장된 값은 boolean을 제외한 정수 0·1만 허용한다. 항목별 카운터로 바꾸지 않는다.
- `RESEARCH`는 오류 없음, 명시적 근거 부족, 유효한 검색 항목, 예산 0을 검사한 뒤 한 번만 진입한다. 재작성 성공·실패 모두 반환 state에 count=1을 기록하며 실패해도 예산을 돌려주지 않는다.
- `INTAKE`, `ROUTE`, `DISPATCH`, 검색, 답변, `ADVANCE`는 요청 도중 이 값을 0으로 초기화하지 않는다. 준비된 시도의 재사용도 count를 증가시키지 않는다.
- count가 1이어도 다른 항목의 최초 검색·답변은 수행한다. 그 항목도 부족하면 추가 시도 없이 해당 결과를 기록한다.
- 유효한 노드 완료 state에서 0→1 전이가 최대 한 번인지 단언한다. 재작성 오류는 재검색·재답변 0회, 재검색 오류는 재답변 0회로 끝난다. 성공 경로의 정확히 1회와 기술 실패의 조기 종료를 구분한다.

## 4. 준비 입력·중복 방지·재개 계약

### 4.1 준비 입력 소유권

공유 state에 선택 필드 `research_input`을 추가한다. 새 준비 레코드는 요청 ID, 항목 ID, 시도 번호 1, 원질문·확정 문맥·출처/대상 글·스냅샷·검색 설정의 식별값, T14 `SearchInput`, 진행 단계(`PREPARED` 또는 `SEARCHED`)를 가진다. 메모리 클로저의 플래그나 요청 전체의 boolean으로 대체하지 않는다.

`RESEARCH`는 현재 항목의 원질문과 확정 OS·버전·목표·제약을 사용해 `prepare_search_input(rewrite_enabled=True, hyde_enabled=False)`를 한 번 호출한다. 최초 검색용으로 재작성된 문장을 원질문 대신 사용하지 않는다. 보존 검사를 통과한 입력·count=1을 함께 반환하며 이전 `retrieval`·`answer`는 지운다. 재작성 오류도 준비 기록·오류·소진 예산을 남기고 검색으로 진행하지 않는다.

검색 어댑터는 현재 요청·항목·시도·문맥과 일치하는 `PREPARED` 입력이 있으면 그 `search_query`를 직접 검색한다. 이 분기에서는 `prepare_search_input()`과 생성 콜백을 다시 호출하지 않는다. 일치하는 추가 입력이 없으면 기존 최초 검색 경로를 수행한다. 다른 항목의 준비 입력을 재사용하거나 count=1만 보고 최초 검색을 생략하지 않는다. 추가 시도인데 준비 기록이 손상·불일치하면 `CONTRACT_VIOLATION`으로 종료한다.

재검색도 원질문의 RawPedia/GitHub 출처와 명시한 Issue/Discussion 필터를 유지한다. 필터를 생성된 문장에서 확대하지 않는다. T15 검색 설정·스냅샷을 그대로 적용하고 새 bundle로 교체한다. `Evidence`의 원문·문서/세그먼트 ID·URL·위치 JSON·제품 범위를 보존하고, 가상 문서를 근거에 섞거나 이전 근거와 무조건 합치지 않는다.

### 4.2 완료 state에서의 재개

재개 지원은 **노드가 반환한 갱신값을 반영한 state를 보존·복원하는 경우**로 정한다. 현재 그래프에는 영속 checkpointer가 없으므로 외부 호출 도중 강제 종료까지 정확히 1회를 보장한다고 주장하지 않는다. 새 저장소나 분산 트랜잭션은 도입하지 않는다.

| 보존된 상태 | 재개 동작과 금지할 중복 |
| --- | --- |
| `PREPARED`, count=1 | 동일 항목 입력을 재사용해 검색부터 진행한다. `RESEARCH`와 재작성은 반복하지 않는다. |
| `SEARCHED`와 새 bundle, 답변 없음 | 검색을 생략하고 `ANSWER`부터 진행한다. |
| 추가 시도의 답변 또는 기술 오류까지 있음 | 해당 답변의 전이 또는 오류 경로로 진행한다. 재작성·검색·답변을 반복하지 않는다. |
| `step_results`에 최종 결과가 기록됨 | 같은 항목·경로의 완료 결과를 보존하고 다음 미완료 항목으로 진행한다. 부족·미지원·실패·차단 결과도 완료로 취급한다. |

이를 위해 `DISPATCH`의 임시값 초기화는 새 항목 진입에만 적용한다. 동일 추가 시도의 재개에서는 준비 입력·bundle·답변·오류를 보존한다. `route_after_dispatch()`는 보존 단계에 따라 검색·답변·결과 기록 경로를 고르고 필요한 edge 매핑만 확장한다. `ROUTE`는 최종 결과가 있는 항목을 재실행하지 않는다. `ADVANCE`가 현재 결과를 기록한 뒤 해당 준비 입력을 제거하되 count와 이전 결과는 유지한다.

재개 시 요청 ID나 현재 항목·입력 식별값이 불일치하면 외부 호출 전에 계약 오류로 거부한다. 서로 다른 새 요청에 이전 state를 붙여 쓰지 않는다. 명확화 응답으로 요청이 보완된 기존 재개 경로에서도 완료 결과·소진 예산을 보존하고, 완료 항목의 준비 입력을 다음 항목에 넘기지 않는다.

## 5. 후속 파일별 변경 목표

아래는 구현 시 예상 변경이다. 이번 작업에서는 이 문서만 추가한다.

| 파일 | 최소 변경 목표 |
| --- | --- |
| `src/artagent/graph/research.py` 신설 | `create_research_node()`와 추가 입력 준비 계약. 예산 검사, T14 호출 1회, 오류 처리, 준비 기록 갱신. 검색·답변을 노드 안에서 중복 실행하지 않는다. |
| `src/artagent/graph/state.py` | 선택 준비 필드와 레코드 타입 추가. 기존 상태·응답 스키마와 count 의미 유지. |
| `src/artagent/graph/search.py` | 일치하는 준비 입력 소비, 중복 재작성 생략, 검색 후 단계 갱신. 최초 검색과 T15 설정·출처·대상 글·근거 변환 보존. |
| `src/artagent/graph/graph.py` | 기존 답변/재검색 edge를 재사용하고 준비 단계별 재개 분기·매핑만 확장. `EXECUTE`를 재검색에 연결하지 않는다. |
| `src/artagent/graph/nodes.py` | 완료 결과 건너뛰기, 새 항목/재개 구별, 결과 기록 후 준비 입력 정리. count를 초기화하지 않는다. |
| `tests/test_graph_research.py` 신설 | 직선 호출·실제 그래프에서 상태, 외부 호출 수, 요청 예산, 오류·혼합·재개 검증. |
| 기존 `tests/test_graph_search_connection.py`, `tests/test_router_contracts.py` | 최초 검색·필터 보존과 완료 결과 재개 회귀를 필요한 지점에 추가. |

T14 `rewrite.py`와 T17 `answer.py`는 기존 기능을 호출하는 경계로 사용한다. 새 팩터리는 모듈에서 직접 import하여 불필요한 패키지 공개 API 확장을 피한다.

## 6. pytest 검증 계획

생성·검색·답변 대역에 호출 계수와 허용 순서 검사를 두고, 세 번째 검색·답변이나 두 번째 추가 재작성 요청은 즉시 실패시킨다. 실제 T14/T17 노드를 쓰는 통합 테스트에서는 생성 콜백과 저장소만 대역으로 주입하고 임시 원문으로 인용 검증까지 수행한다. 외부 생성·네트워크·모델 다운로드 없이 재현한다.

다음 표의 검색·답변 횟수는 **단일 항목의 최초 처리 포함 합계**이고, 추가 재작성은 최초 검색 재작성과 분리해 센다. 최초 검색 on이면 최초 재작성 1회+추가 재작성 1회가 가능하며 이것을 추가 재시도 2회로 세지 않는다. 두 검색 출처와 최초 재작성 on/off를 매개변수화한다.

| 입력/결과 시퀀스 | 추가 재작성 / 검색 / 답변 | 필수 단언 |
| --- | --- | --- |
| 최초 `SUPPORTED` | 0 / 1 / 1 | count=0, `RESEARCH` 없음, 정상 결과 |
| 최초 `UNSUPPORTED` | 0 / 1 / 1 | 미지원 보존, 추가 검색 없음 |
| 부족→`SUPPORTED` | 1 / 2 / 2 | count=1, `RESEARCH` 1회, 새 bundle로 성공 |
| 부족→부족 | 1 / 2 / 2 | count=1, 부족 결과 반환, 세 번째 호출 없음, 종료 노드 도달 |
| 부족→`UNSUPPORTED` | 1 / 2 / 2 | 미지원 보존, 세 번째 호출 없음 |
| 부족→재작성/보존 검사 실패 | 1 / 1 / 1 | `REWRITE_FAILED`, 원질문 재검색으로 대체 없음 |
| 부족→재검색 실패 | 1 / 2 / 1 | `SEARCH_UNAVAILABLE`, 재답변·추가 재시도 없음 |
| 부족→재답변 기술 실패 | 1 / 2 / 2 | T17 오류 보존, 의미 상태로 바꾸지 않음 |
| 최초 검색/답변 기술 실패 | 0 / 최대 1 / 최대 1 | `RESEARCH` 없음, 기술 오류 유지 |
| count=1에서 최초 부족 답변 | 0 / 1 / 1 | 현재 항목의 최초 검색은 수행, 추가 시도 없음 |

추가 회귀는 다음을 포함한다.

- 정상 빈 hits와 기술 오류를 구별한다. 빈 bundle의 T17 부족 상태는 폴백 대상이고, 잘못된 bundle·손상된 출처·답변 형식 오류는 대상이 아니다.
- 재작성 문장이 원질문과 같아도 추가 시도는 한 번으로 끝낸다. 점수 높고 낮음이나 골드 도달 정보를 바꾸어도 같은 T17 상태의 전이는 같아야 한다.
- 두 검색 항목이 모두 부족한 혼합 요청은 최초 검색 2회+추가 검색 1회, 답변 최대 3회, `RESEARCH` 합계 1회다. 첫 항목의 예산 소진 때문에 둘째 최초 검색을 건너뛰지 않는다. 반대로 첫 항목이 지원됨이면 둘째 부족 항목이 예산을 쓸 수 있다.
- §4의 각 노드 완료 state를 복원해 재작성·검색·답변 누적 횟수가 중복되지 않는지 확인한다. 명확화 후 재개에서 완료 항목의 성공·부족·미지원·실패·차단 결과와 count를 보존한다.
- 잘못된 준비 레코드, 요청/항목/문맥 불일치, 음수·2 이상·boolean·잘못된 타입의 count, `EXECUTE`의 직접 `RESEARCH` 호출은 외부 호출 전에 거부한다.
- 재검색 전후 요청·계획·cursor는 보존하고 `ADVANCE`만 cursor를 전진시킨다. 지정 글 필터, RawTherapee/ART 제품 범위, 실제 세그먼트·인용 위치·해시를 검사한다.
- 기존 라우터 20개와 혼합·모호 요청, T14 검색 연결, T17 세 상태·인용·오류 테스트를 통과시킨다. 기본 `RESEARCH` 미구현 경로와 실제 노드 주입 경로를 구분한다.

## 7. 빌드·테스트 명령과 증거

명령은 저장소 루트에서 실행한다. 현재 작업 위치에는 `venv/`가 없고 원본 저장소의 Python 3.14 venv가 있다. 점검 시 Python 3.14.3, pytest·LangGraph 설치를 확인했다. 아래 집중 테스트 파일은 후속 구현에서 추가하며, 이번 문서 작성에서 테스트 통과를 주장하지 않는다.

```bash
# 원본 저장소 루트의 venv 사용. 해당 위치에 venv가 있는 환경에서는 venv/bin/python3 사용.
T16_PYTHON=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3

# Python 모듈 구문 컴파일. 바이트코드 출력은 임시 경로로 제한.
PYTHONPYCACHEPREFIX=/tmp/t16-pycache "$T16_PYTHON" -m compileall -q src/artagent/graph

# 직선 호출·그래프 폴백 집중 검증
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$T16_PYTHON" -m pytest -p no:cacheprovider tests/test_graph_research.py -q

# 라우팅·검색·답변 경계 회귀
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$T16_PYTHON" -m pytest -p no:cacheprovider tests/test_router.py tests/test_router_contracts.py tests/test_graph_search_connection.py tests/test_graph_answer.py tests/test_answer.py tests/test_rewrite.py tests/test_rewrite_preservation.py -q

# 집중 검증 통과 후 전체 Python 회귀
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$T16_PYTHON" -m pytest -p no:cacheprovider tests -q

# 변경·공백 확인
git diff --check
git diff --stat
```

외부 검색 입력·모델 캐시가 필요한 전체 테스트의 전제는 기존 재현 경로를 사용한다. 입력 누락이나 실행 실패를 skip·테스트 삭제로 통과 처리하지 않고 원인·미검증 범위를 기록한다. C++ 소스·빌드 등록을 건드리지 않으므로 T16만을 위한 ART GUI/CLI 재빌드는 요구하지 않는다.

T16 완료 증거는 시나리오별 최종 상태, `research_count`, 항목별 재작성·검색·답변 횟수, 노드 trace, 재개 전후 결과와 테스트 명령·종료 코드다. 호출 대역 pytest 통과는 제어 흐름의 증거이며 실제 답변 품질의 증거와 구분한다.

CP3는 별도 게이트다. 실제 검색/T17/RESEARCH를 연결한 같은 Slice 1 15개에서 T11 기록 대비 주요 사실·제품 범위·인용을 대조하고, Q001·Q086·Q096과 CP2 양성 표본을 검토한다. 폴백 실제 재현과 세 처리 경로 회귀를 함께 확보한 뒤 판정한다. 기존 검색 연결 결과나 이번 문서만으로 CP3를 닫지 않는다. 실제 실행 조건·설정·기록을 확보하지 못하면 미완료로 남긴다.

## 8. 작업 순서와 커밋 분할

1. **계획 고정:** 이 문서만 검토·커밋한다. 기준 링크, 세 상태, 요청 예산·재개 계약, 검증 명령을 확인한다. 이번 작업은 이 단계에서 끝낸다.
2. **직선 호출 검증:** 후속 구현 시 부족→지원/부족, 미지원·오류, 예산 소진 테스트를 먼저 작성해 실패를 확인한다. `research.py`의 준비·예산과 state 계약을 구현하고 동일 검색·답변 콜백을 순서대로 호출해 집중 검증한다.
3. **검색·그래프 연결:** 준비 입력 소비 분기와 `node_overrides` 주입을 연결한다. 최초 검색 on/off·두 출처에서 중복 재작성 0건을 확인한다. 이 시점에 기본 집중 시나리오와 기존 경계 회귀를 통과시킨다.
4. **혼합·재개 완성:** 단계별 state 복원, 완료 항목 건너뛰기, 독립 항목 최초 검색·예산 공유를 검증한다. 전체 회귀와 구문 컴파일을 통과시키고 실패·미검증을 기록한다.
5. **통합 인수:** 실제 실행 조건을 고정해 T17 답변·인용과 폴백 기록을 확보한다. CP3 판정은 §7의 별도 게이트에 따른다.

| 순서 | 커밋 메시지 | 포함 범위·완료 조건 |
| --- | --- | --- |
| 1, 이번 작업 | `docs: 근거 부족 재검색 폴백 구현 플랜 추가` | `docs/T16_execution_plan.md` 하나만. 문서·범위 검증 통과. |
| 2, 후속 구현 | `feat: 근거 부족 단일 재검색과 입력 재사용 연결` | 준비·예산·검색 소비·그래프 접합과 해당 테스트를 함께 포함. 기본 상태·오류·호출 횟수 및 경계 회귀 통과. |
| 3, 후속 구현 | `fix: 혼합 요청과 재개 시 재검색 예산 보존` | 항목 초기화·완료 결과 재개·단계별 재사용과 해당 테스트. 혼합·재개·전체 회귀 통과. |

실패하는 테스트만 남긴 중간 커밋은 만들지 않는다. 이번 문서에 구현 완료 표시를 붙이거나 작업 카드 체크박스를 갱신하지 않는다. 모든 커밋은 국문으로 작성하며 push·PR은 이 작업 범위에 포함하지 않는다.
