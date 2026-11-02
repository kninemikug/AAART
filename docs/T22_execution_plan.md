# Task 22 실행 계획 — ART 프로그램 내부 채팅 GUI

- 작성 기준: 2026-10-20, `kninemikug/T22-chat-ui`
- 기준 커밋: `aaa70c0ce5ecc6b603459a6876e4cb021795544b` (`main`)
- 상태: ART 내부 GTK 채팅 패널과 Python 연결 모듈 구현
- 사용자 진입점: ART 실행 후 메인 창 안의 채팅 패널
- 후속 구현: GTK3/gtkmm 패널과 기존 Python 그래프의 프로세스 연결

## 1. 목적과 범위

[tasks/todo.md](../tasks/todo.md)의 Task 22(A-22)는 현재 최소 CLI로 적혀 있고,
예상 파일은 `src/artagent/cli.py`, 의존 태스크는 T13-2와 T21이다.
그러나 최신 사용자 요구는 **ART를 실행한 뒤 프로그램 안에서 쓰는 GUI**다.
이 문서는 그 요구에 맞춰 ART 내부 채팅 패널을 계획한다.
기존 Task 22 카드와 구현 형태가 달라지므로 후속 태스크 정합화가 필요하다.

목표는 **ART 내부에서 세션 저장 없이 질문·답변만 우선** 수행하는 것이다.
ART 창의 채팅 입력→그래프 호출→같은 창의 답변·인용 표시를 최소 흐름으로 정한다.
문서 Q&A와 문제 해결 질문을 각각 기존 검색 경로에 연결한다.
사용자가 별도의 터미널 명령을 실행하는 것은 제품 사용 흐름에 포함하지 않는다.

T21의 세션 저장·복원과 증분 수정은 **미완료이며 이번 범위 밖**이다.
Task 21의 완료 항목은 모두 미체크이고 `src/artagent/session.py`도 없다.
세션 파일, 대화 이력 저장, 이전 프로필 참조, 재조정·재렌더링은 구현하지 않는다.
프로필 루프가 미완성이므로 EXECUTE는 반드시 “아직 미지원”으로 안내한다.
원래 Task 22의 완료 기준인 시나리오 1~3 전체 수행은 후속 통합에서 검증한다.
[WBS §4·§5](ART_agentic_wbs.md)의 실행·재조정 완료를 앞당겨 표시하지 않는다.

루트 [AGENTS.md](../AGENTS.md)의 기존 `rtgui/` 수정 금지에 대해서는
후속 사용자 지시 “실제 gui 구현해”를 적용한다. 신규 채팅 위젯·프로세스 연결·
메인 창 배치와 해당 빌드 설정만 변경하며 `rtengine/`은 수정하지 않는다.

## 2. T13-2 그래프 진입점 검증 결과

### 2.1 진입점·입력·반환 계약

[graph.py](../src/artagent/graph/graph.py)의 실제 진입점은 다음과 같다.

```python
def create_router_graph(
    node_overrides: Mapping[str, Callable[[AgentState], dict]] | None = None,
) -> CompiledStateGraph:
```

반환 타입은 `langgraph.graph.state.CompiledStateGraph`이며 마지막에
`graph.compile()`을 호출한다. 현재 checkpointer 연결은 없다.
노드 이름은 대문자 문자열이고, 모르는 override 이름은 `ValueError`가 된다.
[graph/__init__.py](../src/artagent/graph/__init__.py)에서
`create_router_graph`, `RequestInput`, `Path`, `RuntimeCapabilities`,
`create_search_nodes`, `create_answer_node`를 import하고 `__all__`로 공개한다.
`CompiledStateGraph` 자체는 이 패키지의 공개 export에 포함되지 않는다.

[state.py](../src/artagent/graph/state.py)의 입력은 dataclass
`RequestInput(request_id, text, session_id=None, assets=[], context=None)`이다.
`assets`의 기본값은 요청별 새 목록을 만드는 `default_factory=list`이다.
경로 enum은 `Path.DOC_QA`, `Path.TROUBLESHOOT`, `Path.EXECUTE`이다.
질문마다 새 `request_id`와 초기 state를 만들고 Python 작업 프로세스에서 호출한다.
동기 `invoke`는 GTK의 메인 스레드에서 실행하지 않는다.

```python
result = graph.invoke({
    "request": request,
    "capabilities": RuntimeCapabilities(
        search_ready=True,
        profile_ready=False,
        render_ready=False,
    ),
})
response = result["response"]
```

`request`는 `RequestInput` 객체다. `graph.run()`을 가정하지 않는다.
반환 state의 `response`는 `ResponseOutput` 객체이고, 실제 답변 본문은
`response.completed_steps`의 각 `StepResult.answer.text`에 있다.
`response.message`는 전체 완료·실패 안내이므로 본문 대신 출력하면 안 된다.
인용은 `AnswerResult.citations`와 집계된 `ResponseOutput.citations`에 있다.

[router.py](../src/artagent/graph/router.py)의
`route_request(request, completed_steps=None, resolved_goal=None)`는
`(RouteDecision, Optional[Clarification])`을 반환한다.
`analyze_signals(text, context=None)`의 규칙으로 원질문을 분기하며,
혼합 요청은 단계별 계획, 모호한 요청은 명확화 질문이 된다.
실행 부정·인용된 명령의 기존 처리 규칙을 유지하고 GUI에서 재분류하지 않는다.

### 2.2 노드 시그니처와 연결 상태

[nodes.py](../src/artagent/graph/nodes.py)의 기본 노드는 모두
`(state: AgentState) -> dict[str, Any]` 형식으로 부분 state를 반환한다.

| 함수 | 확인 결과와 최소본에서의 사용 |
|---|---|
| `intake_node` | 입력 검증·카운터 초기화. 기본 노드 유지 |
| `route_node` | 의도·계획·명확화 결정. 기본 노드 유지 |
| `clarify_node` | 대기 응답 생성·재개 입력 처리. 대기 응답만 표시 |
| `dispatch_node` | 의존 단계와 기능 준비 여부 확인. EXECUTE 차단 래퍼 필요 |
| `search_rawpedia_node`, `search_github_node` | 연결 대기 상태. 팩토리로 교체 |
| `answer_node` | 연결 대기 상태. 기존 답변 팩토리로 교체 |
| `research_node` | 연결 대기 상태. 최소본에서는 재검색 없이 종료하도록 교체 |
| `advance_node`, `respond_node` | 단계 결과 저장·최종 응답 집계. 기본 노드 유지 |

기본 검색·답변·재검색 노드는 `_unavailable()`로
`CAPABILITY_UNAVAILABLE`을 반환한다. 따라서 인자 없는
`create_router_graph()`만으로 실제 답변·인용을 제공할 수 없다.
또한 `RuntimeCapabilities`는 기본적으로 모든 준비 플래그가 `False`다.
검색 준비를 확인한 뒤 `search_ready=True`를 입력 state에 명시해야 한다.

기존 override 팩토리는 이미 존재한다.

- [search.py](../src/artagent/graph/search.py)의
  `create_search_nodes(store, session, *, generate=None, snapshot_ref="",
  rewrite_enabled=False, hyde_enabled=False, observe=None)`는
  `SEARCH_RAWPEDIA`·`SEARCH_GITHUB` 콜백 매핑을 반환한다.
  개별 `create_search_rawpedia_node`·`create_search_github_node`도 존재한다.
  `session`은 검색용 `EncoderSession`이며 T21의 대화 세션과 관계없다.
- [graph/answer.py](../src/artagent/graph/answer.py)의
  `create_answer_node(generate=None, *, source_root=None, observe=None)`는
  `ANSWER` 콜백을 반환한다. 원문 검증·답변·인용 계약을 그대로 사용한다.
- 반환 콜백은 모두 `AgentState`를 받아 부분 갱신 dict를 반환하므로
  `create_router_graph(node_overrides=...)`에 바로 연결할 수 있다.
- 기존 `INTAKE`·`CLARIFY`·`DISPATCH`·`RESEARCH`의 별도 팩토리는 없다.
  필요한 최소 래퍼는 후속 Python 연결 모듈 안에 정의한다.
  기존 그래프 계약과 파일은 유지한다.

### 2.3 최소본의 override 결정

1. 기존 검색 팩토리의 두 콜백과 답변 팩토리의 `ANSWER`를 연결한다.
   재작성·HyDE는 명시적으로 끄고 기존 검색 규격을 사용한다.
2. `DISPATCH` 래퍼는 현재 `decision.plan[cursor].path`를 확인한다.
   EXECUTE이면 기본 노드를 호출하기 전에
   `ErrorInfo(code="UNSUPPORTED", node="DISPATCH", message=미지원 문구)`를
   반환한다. `trace`에 `DISPATCH`를 추가하고 이전 단계의 `retrieval`,
   `answer`, `execution`, `features`, `profile`, `validation`, `render`는
   `None`으로 비운다. 이전 답변이 EXECUTE 단계에 복제되지 않게 한다.
   나머지 경로는 기존 `dispatch_node`에 위임한다.
3. `RESEARCH`는 재검색하지 않고 `INSUFFICIENT_EVIDENCE` 오류와
   해당 trace 갱신을 반환하도록 연결한다. 기존 그래프는 근거 부족 시
   기본 `RESEARCH`로 이동하므로, 미연결 오류로 바뀌지 않게 하는 조치다.
   T16의 재검색 구현은 이번 최소본에 포함하지 않는다.

`profile_ready=False`·`render_ready=False`만으로는 기본 DISPATCH에서
일반 기능 오류가 된다. 위 래퍼로 미지원 상태와 문구를 명확히 정한다.
전이는 `DISPATCH→FALLBACK→ADVANCE→RESPOND`이며 실행 노드에 진입하지 않는다.

## 3. ART 내부 화면과 연결 지점

기존 GTK3/gtkmm 화면을 사용한다. ART 메인 창 안에 접을 수 있는 채팅 패널을
두고 사진 편집 화면을 옆에서 계속 볼 수 있게 한다.

```text
+-------------------------------+--------------------------+
| ART 파일 탐색·사진 편집 화면   | 채팅                 접기 |
|                               | 사용법을 질문해보세요.    |
|                               | 질문 / 답변 / 출처        |
|                               |                          |
|                               | [질문 입력             ] |
|                               | [보내기]   처리 상태      |
+-------------------------------+--------------------------+
```

[rtwindow.cc](../rtgui/rtwindow.cc)의 `RTWindow::RTWindow()`는 일반 모드에서
`mainNB`, 단순 편집 모드에서는 `epanel`을 `main_widget`으로 정한 뒤
`init(main_widget)`으로 메인 창에 넣는다. 이 경계에 외부 컨테이너를 두어
기존 화면과 채팅 패널을 함께 배치하는 방식을 우선한다.

기존 `mainNB`에 새 탭을 바로 추가하지 않는다. `isEditorPanel()` 및 키·스크롤
처리는 파일 탐색기·대기열 이외 페이지를 `EditorPanel`로 간주한다.
옆 패널로 통합하면 그 탭 전환 계약을 유지할 수 있다.

화면 요구사항은 다음과 같다.

- ART 실행 시 채팅의 위치를 찾을 수 있고 이미지 미선택 상태에서도 질문할 수 있다.
- 질문 입력, 보내기, 스크롤 가능한 답변 내역, 출처 링크, 처리 상태를 제공한다.
  빈 입력의 전송은 막고 처리 중에는 중복 전송을 막는다.
- 패널을 접어도 다시 열 수 있으며 편집 영역 크기 조절이 가능해야 한다.
- 입력 중 Enter·Tab·복사/붙여넣기가 편집기 단축키에 가로채이지 않아야 한다.
  `RTWindow`의 키·스크롤 전달 전에 채팅 내부 포커스 여부를 확인한다.
- macOS 입력칸은 Quartz 입력기를 사용해 한글 자모를 조합한다.
  채팅에 포커스가 있으면 `RTWindow::keyPressedBefore`에서 ⌘A/C/X/V와
  ⌘←/→를 처리하고 나머지 키는 GTK 입력기로 전달한다. 한글 자판의 키값에는
  macOS 하드웨어 키 코드 보완을 적용한다. 선택한 답변의 ⌘C도 지원한다.
  전송하거나 입력 내용을 변경하기 전에 조합 중인 마지막 글자를 확정한다.
- 기존 ART 테마·글꼴을 따르고 긴 한국어 답변과 URL을 줄바꿈한다.
  입력 라벨과 버튼 이름을 명시하고 키보드만으로 이용할 수 있게 한다.
- 준비 중·답변 중·오류 상태는 텍스트로 알린다. 연결 실패도 패널 안에서 표시한다.
  채팅 연결 실패 때문에 ART 자체의 실행·사진 편집이 실패하면 안 된다.

## 4. GTK와 Python 그래프 연결

GTK는 화면과 프로세스 수명만 담당하고 기존 Python 그래프는 별도 작업 프로세스에서
실행한다. ART가 설정된 Python 실행 파일을 직접 실행하므로 사용자에게 터미널을
열도록 요구하지 않는다. 쉘 명령 문자열에 질문을 삽입하지 않는다.

[subprocess.h](../rtengine/subprocess.h)에 기존 `popen`과
`SubprocessInfo`의 읽기·쓰기·종료 인터페이스가 있다.
기존 기능 재사용 가능성과 취소·출력 배수의 제약을 구현 전에 확인한다.
GUI 스레드에서 검색·답변 처리나 프로세스 완료를 기다리지 않는다.
위젯 갱신은 GTK 메인 스레드에 전달하고 종료 뒤의 위젯을 콜백에서 참조하지 않는다.

프로세스 간 계약은 질문 1건당 UTF-8 JSON 요청·응답 한 쌍이다.
요청마다 새 작업 프로세스를 실행하고 비동기 `GSubprocess` 통신으로 입출력한다.
기존 `SubprocessInfo` 대신 취소·양쪽 출력 배수·완료 콜백을 제공하는
[GIO Subprocess](https://docs.gtk.org/gio/class.Subprocess.html)를 사용한다.

- 요청: `version`, `request_id`, `text`.
- 응답: `version`, `request_id`, `status`, `message`, `steps`, `citations`,
  `error`. `steps`는 순서를 유지하며 단계별 `path`, `status`, `text`,
  `citations`, `error`를 포함한다.
- `error`는 없으면 `null`, 있으면 `code`·`message` 객체다.
  준비 오류도 구조화하여 반환하고 잘못된 응답·프로세스 종료는 연결 오류로 표시한다.
- 표준 출력은 프로토콜 전용, 진단 출력은 표준 오류로 분리한다.
  줄 경계, 요청 ID, 타입과 버전을 검증하고 응답을 다른 질문에 붙이지 않는다.

작업 프로세스는 해당 질문에 필요한 그래프·검색 자원을 준비한다.
EXECUTE 차단과 명확화 응답에는 검색 저장소가 필요하지 않다.
최소 구현에서는 질문마다 자원을 다시 읽는 준비 비용이 있으며,
장기 실행 프로세스로 바꾸는 최적화는 후속 범위다.
`session_id=None`, `assets=[]`, `context=None`을 유지한다.
화면에 이전 문답이 보여도 이를 다음 질문의 문맥으로 자동 주입하지 않는다.
창을 닫으면 작업 프로세스와 대기 작업도 종료한다.

기존 반환 계약에 맞춰 아래 표시 규칙을 적용한다.

- `completed_steps[*].answer.text`를 본문으로 보여준다.
  `[출처: 문서명·URL]`을 보존하고 `Citation.title`·`url`을 출처에 사용한다.
  URL은 허용한 웹 스킴만 열고 답변 문자열을 GTK markup으로 직접 실행하지 않는다.
- `ADVANCE`가 최상위 오류를 지우므로 단계별 오류도 응답에 보존한다.
- EXECUTE 단계에는 다음 고정 안내를 표시한다.

  > 실행 요청은 아직 미지원입니다. 프로필 생성·렌더링 루프와
  > 세션 저장·증분 수정이 완료되면 제공됩니다.
  > 현재는 질문·답변만 이용할 수 있습니다.

- 혼합 요청은 Q&A 결과와 실행 미지원 안내를 함께 표시한다.
  성공 Q&A와 미지원 단계가 함께 있으면 전체 `PARTIAL` 상태를 유지한다.
- `WAITING_CLARIFICATION`은 질문과 “질문 전체를 구체적으로 다시 입력해주세요.”를
  표시한다. `CLARIFY`가 바로 END로 끝내도 생성된 `response`를 사용한다.
  최소본에서는 `ResumeInput`으로 이전 요청을 재개하지 않는다.
- 근거 부족은 재검색 없이 종료하며 성공 답변으로 표시하지 않는다.
  오류 후에는 입력을 다시 사용할 수 있게 하고 응답 누락도 오류로 표시한다.

## 5. 실행 환경과 후속 구현 단위

제품의 사용 절차는 **ART 실행→채팅 열기→질문 입력→답변·출처 확인**이다.
`python -m artagent.cli`를 최종 사용자 실행법으로 두지 않는다.
GUI는 `rtgui/chatpanel.*`, 비동기 연결은 `rtgui/chatconnection.*`,
그래프와 JSON 연결은 `src/artagent/gui_bridge.py`에 구현했다.

개발 환경은 원본 저장소의 Python 3.14 `venv/`와 이 worktree의 `src/artagent`다.
worktree 자체에는 `venv/`와 `data/vector-store/t09`가 없다.
Python 실행 파일·연결 모듈·reference·저장소·원문 루트는 ART에서 시작하는
작업 프로세스에 명시적으로 전달한다. Finder 등으로 실행해도 터미널의
환경변수나 현재 디렉터리에 의존하지 않아야 한다.
필요한 경로는 패널의 “연결 설정”에서 수정하고 폴더 선택기로 고를 수 있다.
Python·프로젝트·검색 저장소 경로는 ART 설정 폴더의 `artagent.ini`에 저장한다.
이 실행 환경 설정은 T21의 대화·프로필 세션 저장과 구분하며 인증값은 저장하지 않는다.
빌드 시 `ART_AGENT_PYTHON`, `ART_AGENT_SOURCE_DIR`, `ART_AGENT_STORE_DIR`로
초깃값을 지정할 수 있다. 기존 답변 실행 파일 경로도 빌드 때 탐색하여
자식 프로세스의 PATH에 추가하므로 앱 실행 시 터미널 PATH에 의존하지 않는다.

기존 [answer.py](../src/artagent/answer.py)의 검색 준비 순서를 유지한다.

1. reference·기존 Chroma 저장소·원문 경로를 명시적으로 검증한다.
2. `load_spec`→`verify_store_ready`→`load_encoder`→`open_store` 순서로 준비한다.
   `open_store`에 생성 기능이 있으므로 저장소 검증을 먼저 수행한다.
   GUI에서 자동 재색인·적재·패키지 설치를 하지 않는다.
3. `create_answer_node(source_root=...)`에 검증한 원문 루트를 넘긴다.
   검색 결과의 해시·세그먼트와 실제 원문이 일치해야 한다.
4. 기존 답변 생성 설정과 인증·접속 환경을 유지한다.
   `T09_REFERENCE_PATH`, `T09_PERSIST_DIR`, `T09_SOURCE_ROOT`에 해당하는
   경로를 명시적으로 구성한다. 기존 `LLM_PROVIDER`·`LLM_MODEL` 등도
   GUI에서 실행한 작업 프로세스에 전달되어야 한다.
   인증값을 대화 내역·진단 화면·일반 설정 파일에 출력하지 않는다.

후속 구현은 아래 순서로 나누고 각 단계에서 동작을 검증한다.

| 순서 | 예상 변경 | 인수 조건 |
|---|---|---|
| 1 | Python 연결 모듈·집중 테스트 | 그래프 응답·인용·미지원 상태를 계약대로 반환 |
| 2 | `rtgui/chatpanel.h`, `chatpanel.cc` | 입력·답변·상태·오류 화면과 비동기 연결 동작 |
| 3 | `rtgui/rtwindow.h`, `rtwindow.cc` | 메인 창 안에서 패널 접근·포커스·종료 정상 |
| 4 | `rtgui/CMakeLists.txt` 및 필요한 표시 문구 | GUI 대상에 연결되고 기존 테마 사용 |
| 5 | 실행 환경 설정·패키징 연결 | ART 직접 실행 후 터미널 없이 질문 가능 |

예상 신규 Python 모듈은 `src/artagent/gui_bridge.py`다.
기존 그래프·처리 엔진의 변경 없이 연결 계층에서 override를 구성한다.
Python은 argparse·docstring·`main()` 가드를 따르고 줄 길이 80 이하를 권장한다.
C++는 프로젝트의 C++11·GTK3/gtkmm·기존 포맷을 따른다.

개발 중 GUI 빌드 명령은 다음과 같다. 빌드 디렉터리는 소스 루트와 분리한다.

```bash
cmake -DCMAKE_BUILD_TYPE=Release -B build
cmake --build build --target art -j 4
```

macOS ARM 환경의 기존 비 SIMD 경로에는 `LUT3D.cc` 중복 선언 오류가 있다.
이 검증에서는 설치된 SIMD 지원을 `-DENABLE_SIMDE=ON`으로 사용했다.
GUI 빌드·실행 리소스 설치를 마쳤으며 로컬 실행 앱은 `build/ART.app`이다.
이 앱은 현재 개발 환경의 Python·검색 자료·Homebrew 라이브러리를 사용한다.
다른 컴퓨터용 독립 배포 패키지로 검증한 것은 아니다.

현재 macOS 로컬 앱을 다시 빌드·설치할 때는 다음 명령을 사용한다.
기존 `build/CMakeCache.txt`의 Python·검색 저장소 경로를 유지한다.

```bash
cmake --build build --target art art-cli -j 6
cmake --install build
```

앱 번들의 실제 아이콘·테마는 설치 시 배치된다. 원본 `rtdata` 디렉터리를
설치된 리소스처럼 직접 사용하면 아이콘 경로가 달라 실행이 실패할 수 있다.

## 6. 수동 검증 체크리스트와 열린 질문

아래는 인수 체크리스트다. 수행한 항목만 체크하고 나머지는 후속 수동 검증으로 남긴다.

- [x] ART 메인 창 안의 채팅 패널에서 질문을 전송할 수 있다.
- [x] 이미지 미선택 상태에서 예시 질문의 한국어 답변과 출처 링크가 표시된다.
- [ ] 사진 편집 모드에서도 패널을 사용할 수 있다.
- [ ] “노출 보정 방법을 알려줘”에 실제 답변과 검증된 문서명·URL이 표시된다.
- [ ] 문제 해결 질문은 GitHub 근거 답변 또는 근거 부족 상태로 표시된다.
- [ ] “노출 보정을 적용해줘”는 정확한 “아직 미지원” 안내를 표시한다.
  실행 노드 미진입과 프로필·렌더 파일 미생성을 확인한다.
- [ ] 혼합 요청에서 Q&A 결과와 실행 미지원 안내를 함께 확인한다.
- [ ] 처리 중 사진 편집·창 이동·패널 접기가 가능하며 중복 전송을 막는다.
- [ ] 한국어 입력·Enter·Tab·복사/붙여넣기가 편집기 단축키와 충돌하지 않는다.
- [ ] 긴 답변·URL은 줄바꿈되고 출처를 키보드로 열거나 복사할 수 있다.
- [ ] 잘못된 경로·연결 실패·프로세스 종료가 GUI 안에서 설명된다.
  채팅 실패 상태에서도 ART 편집 화면을 계속 사용할 수 있다.
- [ ] 응답 대기 중 ART를 종료해도 정지·종료된 위젯 접근·고아 작업이 없다.
- [ ] 재시작 시 이전 문답·프로필을 복원하지 않고 세션 파일을 생성하지 않는다.
- [ ] 터미널 환경을 상속하지 않는 앱 직접 실행에서도 질문·답변이 동작한다.

열린 항목과 후속 통합 지점은 다음과 같다.

- **배포 환경:** Python·검색 저장소·원문·인증의 초기 설정과 앱 번들 제공 범위는
  독립 배포 시 확정해야 한다. 이번 검증은 T14 저장소를 무시되는 로컬 경로로 복사해
  원본을 변경하지 않고 사용했다.
- **다중 창:** 최초 최소본의 대상은 `RTWindow`다. 별도 `EditWindow`에서도
  같은 패널을 제공할지와 창 사이의 표시 내역 공유 여부는 후속 결정한다.
- **T21 통합:** 완료 후 요청 생성 직전의 `session_id`·`assets`·`context`와
  응답 수신 뒤의 프로필·렌더 결과 저장을 연결한다. 지금 세션 형식을 미리 정하지 않는다.
- **실행 통합:** T18~T20·T21 완료 후 미지원 래퍼를 대체하고 질문→실행→재조정의
  원래 시나리오를 ART 내부에서 검증한다. 현재의 안내만으로 완료 처리하지 않는다.
- **검색·답변:** T9·T14-CONN·T17 준비가 필요하며 T16 재검색은 후속 통합한다.
  RawPedia의 설명을 근거 없이 ART 기능·UI와 동일하다고 단정하지 않는다.

## 7. 구현 검증 기록 (2026-10-20)

- `art`·`art-cli` 빌드 및 `cmake --install build` 완료.
- 기존 전체 Python 테스트와 신규 연결 테스트를 함께 실행해 **953개 통과**.
  기존 Chroma 의존성의 폐기 예정 경고 1건이 있으며 실패는 없다.
- 실제 검색 저장소로 Q001 질문을 실행해 `COMPLETED`, 답변·인용 1건을 확인했다.
- 실제 ART 창에서 “예시: Auto Levels”→“보내기”를 클릭하고 한국어 답변,
  문서명 `Exposure`, 해당 출처 링크 표시를 확인했다.
  이때 이미지를 열지 않은 파일 탐색 화면에서 채팅을 사용했다.
- 화면 기록은 로컬 `build/T22_chat_verified.png`에 보관했다.
- 프로세스 경계 테스트는 실행 미지원, 혼합 요청의 답변 분리, 근거 부족,
  명확화 응답, 잘못된 입력, 검색 저장소 자동 생성 방지, 표준 출력 분리,
  비공개 오류 상세의 화면 노출 방지를 포함한다.
- 이 기록은 프로필 실행·증분 수정, Windows·Linux 실기 검증,
  다른 컴퓨터용 독립 배포 또는 모든 수동 체크리스트의 통과를 뜻하지 않는다.

### 7.1 macOS 한글 입력·단축키 수정 (2026-11-02)

- 자모가 조합되지 않고 ⌘C/V가 작동하지 않는 현상을 보고받았다.
  로컬 `.app` 실행에서 Quartz 입력기 모듈을 찾지 못하는 로그를 확인했다.
- CMake가 설치된 GTK 입력기 캐시를 찾아 `main.cc`에서 `gtk_init` 전에
  연결한다. 배포용 런처가 지정한 `GTK_IM_MODULE_FILE`은 우선한다.
  채팅 입력칸에는 Quartz를 명시하되 기존 `GTK_IM_MODULE` 설정은 유지한다.
  로컬 빌드는 설치된 GTK 모듈에 의존하며 독립 배포 패키지의 검증을 대체하지 않는다.
- 기존 입력칸 신호에서 단축키를 중복 처리하는 코드를 제거했다.
  `chatinput.h/.cc`가 입력칸·선택 가능한 답변의 편집 키 처리를 담당한다.
  일반 한글 입력과 한영 전환 키는 이 처리에서 소비하지 않는다.
- `tests/test_chat_input.cc`는 기존 처리에서 한글 자판 ⌘A, 답변 ⌘C,
  ⌘⇧←가 실패하는 것을 확인한 뒤 수정했다. 한글 복사·잘라내기·붙여넣기,
  Quartz 선택, 다른 보조 키·조합 키 보존을 포함해 7개 검사를 통과했다.
- `art` 재빌드와 `cmake --install build`를 완료하고 수정본 실행 시
  입력기 로드 오류가 사라지는 것을 확인했다. 실제 키보드의 한글 조합과
  한영 전환은 별도 수동 확인 항목으로 유지한다.

macOS 네이티브 입력 회귀 검사는 저장소 루트에서 다음과 같이 실행한다.

```bash
c++ -std=c++11 -Irtgui tests/test_chat_input.cc rtgui/chatinput.cc \
  -o /private/tmp/t22-chat-input-tests \
  $(pkg-config --cflags --libs gtkmm-3.0)
GTK_IM_MODULE_FILE="$(pkg-config --variable=libdir gtk+-3.0)/gtk-3.0/$(pkg-config --variable=gtk_binary_version gtk+-3.0)/immodules.cache" \
  /private/tmp/t22-chat-input-tests
```

### 7.2 브랜치 종료 시 남은 확인 사항 (2026-11-02)

- 한국어 기본 사용 질문의 검색 누락을 확인했다.
  “작업할 사진은 어떻게 불러오나요?”와 “사진 불러오기 방법 알려줘”를
  현재 검색 저장소에서 조회하면 상위 5건에 사진 열기 안내 문서가 나오지 않는다.
  같은 의미의 영어 검색에는 `file_browser`와 `getting_started`가 포함된다.
  원문 `data/rawpedia/getting_started.md`의 `Start RawTherapee` 절에
  폴더를 열고 사진을 더블클릭하는 절차가 있으므로 원문 누락은 아니다.
- 현재 GUI 연결은 `rewrite_enabled=False`, `hyde_enabled=False`다.
  후속 작업에서 한국어 검색어 처리와 기본 사용 질문의 검색 회귀 검증을 보완한다.
  검색에 잡히지 않았다는 이유로 매뉴얼 전체에 내용이 없다고 단정하지 않는다.
- 실제 키보드의 한글 자모 조합·한영 전환·⌘C/V 수동 인수 확인은 남아 있다.
  입력 처리 회귀 검사와 입력기 로드 오류 해소만으로 이 항목을 완료 처리하지 않는다.
- 이 브랜치는 ART 내부 채팅 GUI 구현 상태를 보존한다.
  위 검색·입력 확인 사항과 T21 세션 저장, 프로필 실행·재조정 통합은 후속 작업이다.
