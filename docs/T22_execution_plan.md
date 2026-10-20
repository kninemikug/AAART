# Task 22 조기 착수 실행 계획 — 최소 터미널 REPL

- 작성 기준: 2026-10-20, `kninemikug/T22-chat-ui`
- 기준 커밋: `aaa70c0ce5ecc6b603459a6876e4cb021795544b` (`main`)
- 이번 산출물: 이 문서 1개. 구현 코드는 작성하지 않는다.
- 후속 구현 예상 파일: `src/artagent/cli.py`

## 1. 목적과 범위

[tasks/todo.md](../tasks/todo.md)의 Task 22(A-22)는 질문·실행요청·재조정을
타이핑하는 최소 CLI이며, 의존 태스크는 T13-2와 T21이다.
원래 완료 기준은 시나리오 1~3단계의 수동 수행이다.
[WBS §4·§5](ART_agentic_wbs.md)의 질문→실행→재조정 흐름을 따른다.

이번 조기 착수의 목표는 **세션 저장 없이 질문·답변만 우선** 수행하는 REPL이다.
터미널 질문 입력→그래프 호출→답변·인용 출력→다음 입력을 최소 흐름으로 정한다.
문서 Q&A와 문제 해결 질문은 각각 기존 검색 경로에 연결한다.

T21의 세션 저장·복원과 증분 수정은 **미완료이며 이번 범위 밖**이다.
Task 21의 완료 항목은 모두 미체크이고 `src/artagent/session.py`도 없다.
세션 파일, 대화 이력 저장, 이전 프로필 참조, 재조정·재렌더링은 구현하지 않는다.
프로필 루프가 미완성이므로 EXECUTE는 반드시 “아직 미지원”으로 안내한다.
이 최소본을 구현해도 Task 22의 원래 완료 기준을 충족했다고 표시하지 않는다.

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
질문마다 새 `request_id`와 초기 state를 만들고 다음 형태로 동기 호출한다.

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
실행 부정·인용된 명령의 기존 처리 규칙을 유지하고 CLI에서 재분류하지 않는다.

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
  필요한 최소 래퍼는 후속 `cli.py` 안에 정의하고 그래프 파일은 수정하지 않는다.

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

## 3. REPL 구조와 출력 규칙

후속 구현은 `cli.py` 안에서 환경 준비, 그래프 구성, 입력 반복,
응답 표시로 나눈다. 그래프와 검색 자원은 시작 시 한 번 준비한다.
각 입력은 독립 요청이며 이전 반환 state를 다음 호출에 넘기지 않는다.
`session_id=None`, `assets=[]`, `context=None`을 유지하고 재개 입력도 보관하지 않는다.

```text
시작 → 환경·검색 준비 확인 → override 연결 → 그래프 생성
art> 입력 → 빈 줄·종료 명령 확인 → 새 RequestInput
         → graph.invoke → 단계별 답변·인용·오류 표시 → art>
```

- 프롬프트는 `art> `로 정한다. 빈 줄은 호출 없이 다음 입력을 받는다.
  `/quit`, `/exit`, EOF, Ctrl-C는 정상 종료한다.
- 출력은 전체 상태와 안내, 계획 순서의 단계별 답변 본문·인용으로 구성한다.
  본문의 `[출처: 문서명·URL]` 표식을 그대로 보존한다.
  별도 인용 목록을 표시하면 `Citation.title`·`url`을 사용하고
  서로 다른 원문 세그먼트의 인용을 임의로 합치지 않는다.
- EXECUTE 단계의 고정 안내는 다음 문구로 정한다.

  > 실행 요청은 아직 미지원입니다. 프로필 생성·렌더링 루프와
  > 세션 저장·증분 수정이 완료되면 제공됩니다.
  > 현재는 질문·답변만 이용할 수 있습니다.

- 혼합 요청은 기존 라우터 계획을 유지한다. Q&A 단계의 답변은 출력하고
  EXECUTE 단계에서는 같은 미지원 문구를 출력한다. 성공한 Q&A와
  미지원 단계가 함께 있으면 전체 `PARTIAL` 상태를 유지한다.
- `WAITING_CLARIFICATION`이면 `clarification.question`을 출력하고
  “질문 전체를 구체적으로 다시 입력해주세요.”라고 안내한다.
  `CLARIFY`는 `RESPOND`를 거치지 않고 END로 끝나도 `response`를 만든다.
  최소본에서는 `ResumeInput`으로 이전 요청을 재개하지 않는다.
- 근거 부족·범위 밖·오류 상태를 성공 답변으로 표시하지 않는다.
  `ADVANCE`가 최상위 `error`를 지우므로 `completed_steps[*].error`도
  확인해 단계별 오류 코드·안내를 출력한다. 답변이 없으면 인용을 만들지 않는다.
- 준비 실패는 원인과 필요한 경로를 stderr에 알리고 종료 코드 1로 끝낸다.
  요청 처리 중 오류는 해당 요청을 실패로 표시한 뒤 새 입력을 받는다.
  응답 누락도 오류로 처리한다. 정상 종료는 코드 0으로 정한다.

## 4. 실행법과 환경

아래는 **후속 구현 후** 사용할 실행법이다. 현재 기준에는 `cli.py`가 없어
`python -m artagent.cli` 실행은 아직 불가능하다. 이 문서 작성 중에는 실행하지 않는다.

작업 디렉터리는 이 worktree 루트, import 대상은 이곳의 `src/artagent`다.
worktree에는 `venv/`가 없으므로 확인된 원본 저장소의 Python 3.14 환경을 사용한다.
패키지는 해당 환경의 기존 설치를 사용하며 새 `requirements.txt`를 만들지 않는다.

```bash
cd /Users/user/orca/workspaces/AAART/T22-chat-ui
source /Users/user/Workspace/Programming/Projects/AAART/venv/bin/activate
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
export T09_REFERENCE_PATH="$PWD/docs/T08_2_t9_handoff_reference.json"
export T09_SOURCE_ROOT="$PWD"
# T09_PERSIST_DIR은 준비된 기존 T9 Chroma 저장소의 절대 경로로 설정한다.
: "${T09_PERSIST_DIR:?기존 T9 저장소 경로를 먼저 설정하세요}"
python -m artagent.cli
```

현재 이 worktree의 기본 경로 `data/vector-store/t09`는 존재하지 않는다.
명령 실행 전에 준비된 저장소 경로를 `T09_PERSIST_DIR`로 지정해야 한다.
원문이 다른 위치에 있으면 `T09_SOURCE_ROOT`도 그 스냅샷의 루트로 변경한다.

준비 순서는 기존 [answer.py](../src/artagent/answer.py)의
경로 해석·검증 함수를 재사용해 다음과 같이 정한다.

1. argparse의 `--reference`, `--persist-dir` 옵션과 기존
   `T09_REFERENCE_PATH`, `T09_PERSIST_DIR` 설정을 해석한다.
   명시한 경로가 없거나 잘못되면 다른 저장소로 조용히 대체하지 않는다.
2. `load_spec(reference_path)`→`verify_store_ready(persist_dir, spec)`→
   `load_encoder(spec)`→`open_store(persist_dir, spec)` 순서로 준비한다.
   `open_store`에는 생성 기능이 있으므로 기존 저장소 검증을 먼저 수행한다.
   CLI에서 재색인·적재 작업은 수행하지 않는다.
3. `create_answer_node(source_root=...)`에 `T09_SOURCE_ROOT`를 명시해
   reference·검색 결과·원문의 해시 및 세그먼트가 같은 스냅샷인지 검증한다.
4. 답변 생성은 기존 `generate_llm_response`의 환경 설정을 사용한다.
   `LLM_PROVIDER`·`LLM_MODEL`과 선택 경로에 필요한 인증·접속 설정은
   기존 실행 환경 값을 유지한다. 접속 경로에 따라 `LLM_API_KEY`,
   `LLM_BASE_URL` 또는 기존 대체 환경변수가 필요하다.
   이 최소본에서 새로운 제공 경로나 모델을 선정하지 않는다.
5. 선택 검색 규격의 가중치·토크나이저 캐시가 필요하다.
   `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`은 캐시가 준비된 경우만 사용한다.
   누락 패키지·캐시·인증은 준비 실패로 보고하며 실행 중 자동 설치하지 않는다.

`argparse`, 모듈·함수 docstring, `main() -> int`,
`if __name__ == "__main__":` 가드를 기존 Python 관례대로 적용한다.
`--help`는 검색 자원 초기화 전에 처리하고 Python 코드의 줄 길이 80 이하를 권장한다.

## 5. 후속 구현 순서와 수동 검증 체크리스트

구현 순서는 환경·그래프 연결→독립 입력 반복→출력·미지원 처리→수동 검증이다.
변경 예상 파일은 `src/artagent/cli.py`이며 그래프·ART 본체는 변경하지 않는다.
아래 항목은 **구현 후 검증용**이며 현재 실행 완료를 뜻하지 않는다.

- [ ] 위 환경에서 `python -m artagent.cli --help`가 옵션을 표시한다.
- [ ] CLI 시작 후 `art> `가 나오고 빈 줄은 그래프 호출 없이 무시된다.
- [ ] “노출 보정 방법을 알려줘” 입력 후 실제 답변 본문과
  `[출처: 문서명·URL]`을 확인한다. URL·문서명을 원문 근거와 대조한다.
- [ ] “ART가 비정상 종료돼요. 원인과 해결 방법을 알려줘” 입력 시
  TROUBLESHOOT의 답변·인용 또는 근거 부족 상태를 표시한다.
- [ ] “노출 보정을 적용해줘” 입력 시 정확한 “아직 미지원” 안내가 나온다.
  trace에서 `CHECK_EXEC`·`FEATURES`·`GENERATE_PROFILE`·`RENDER` 미진입을
  확인하고 프로필·렌더 출력 파일이 생성되지 않았는지 확인한다.
- [ ] “노출 조절 방법도 알려주고 노출 보정을 적용해줘” 입력 시
  Q&A 결과와 EXECUTE 미지원 안내를 함께 표시한다.
- [ ] “사진이 노래요. 봐주세요” 입력 시 명확화 질문과 전체 재입력 안내가 나온다.
  다음 질문은 새 요청으로 실행되고 이전 대기 state를 재사용하지 않는다.
- [ ] 근거 부족이 일반 연결 오류로 바뀌지 않고, 재검색 없이 종료된다.
  준비 오류는 실패 종료하고 검색·답변 오류 뒤에는 새 입력이 가능하다.
  오류를 성공으로 표시하지 않는다.
- [ ] 연속 질문·재시작 후 이전 답변·프로필을 참조하지 않고 세션 파일이 없다.
- [ ] `/quit`, `/exit`, EOF, Ctrl-C가 정상 종료한다.

최소 시나리오 스크립트는 다음과 같다. 답변 내용은 고정 문자열로 가정하지 않는다.

```text
art> 노출 보정 방법을 알려줘
[답변 본문과 검증된 출처 표시]
art> 노출 보정을 적용해줘
실행 요청은 아직 미지원입니다. ...
art> 조금 더 밝게 보정해줘
실행 요청은 아직 미지원입니다. ...
art> /quit
```

이는 WBS 시나리오 1의 질문 흐름과 2·3의 미지원 경계를 확인하는 스크립트다.
실행·재조정 성공이나 시나리오 1~3 전체 완료의 증거로 사용하지 않는다.

## 6. 리스크와 열린 질문

- **T21 통합:** 세션 저장·복원과 증분 수정 계약이 확정된 뒤,
  요청 생성 직전의 `session_id`·`assets`·`context` 주입과 결과 수신 후의
  프로필·렌더 결과 저장을 연결한다. 저장 형식·수명은 T21에서 결정한다.
- **실행 통합:** T18~T20의 생성·검증·렌더 루프와 T21이 준비된 후
  DISPATCH 미지원 래퍼를 제거하고 실행 기능 준비 여부를 실제 상태에 연결한다.
  그때 Task 22의 원래 시나리오 1~3 및 증분 재조정을 다시 검증한다.
- **검색 의존성:** T13-2 골격만으로 답변이 동작하지 않는다.
  T9 저장소·T14-CONN 검색·T17 답변 모듈의 준비 여부가 최소본의 전제다.
  현재 저장소 부재는 실행 전 해결해야 할 환경 항목이다.
- **근거 부족·명확화:** T16 재검색과 요청 단위 메모리 재개 지원 여부는
  후속 통합에서 결정한다. 현재는 재검색 없이 종료하고 질문 전체를 다시 받는다.
- **원문 일치:** 다른 worktree의 기본 경로를 그대로 쓰면 원문 검증이 실패할 수 있다.
  reference·저장소·원문 루트를 함께 확인하고 경로 오류를 답변 품질 문제로 숨기지 않는다.
- **적용 범위:** RawPedia 인용은 RawTherapee 참고 설명이라는 기존 답변 계약을 유지한다.
  근거 없이 ART 기능·UI와 동일하다고 단정하지 않는다.
