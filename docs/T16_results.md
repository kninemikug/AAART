# T16 근거 부족 1회 재검색 구현·검증

작성일: 2026-11-04. 기준은 [실행 계획](T16_execution_plan.md), Task 16, WBS A-16과 T14-CONN 인계 §2~3이다.

## 구현 결과

- T17이 `INSUFFICIENT_EVIDENCE`를 반환할 때만 T14 재작성→같은 출처 재검색→T17 재답변을 요청 전체에서 한 번 허용한다. 재차 부족하면 해당 상태를 반환하며 `UNSUPPORTED`와 기술 오류에서는 재검색하지 않는다.
- `research_count`와 요청·항목 소유 정보를 유지한다. 혼합 요청의 다른 항목은 예산 소진 후에도 최초 검색·답변을 수행한다. 완료한 성공·미지원·부족·실패·차단 결과는 재개 시 다시 실행하지 않는다.
- `ResearchInput`은 원질문·확정 문맥의 식별값, 준비된 `SearchInput`과 해시, 최초 검색 설정, 진행 단계(`PREPARED`/`SEARCHED`)를 보존한다. 검색 노드가 준비 입력을 직접 소비하여 이중 재작성을 방지하고, 요청·항목·문맥·설정 불일치는 외부 호출 전에 거부한다.
- 기존 검색의 출처·지정 글·스냅샷·리랭킹 설정과 실제 원문 세그먼트·제품 범위·인용 위치를 유지한다. 점수 기반 신뢰도 판정이나 추가 재시도는 도입하지 않았다.
- CLI `build_repl_graph()`와 GUI `create_gui_graph()`의 임시 종결 래퍼를 실제 노드로 교체했다. 기존 생성 전송의 JSON 응답에서 검색 문장만 추출하며, 빈 `citation_ids`를 요구한 뒤 T14 보존 검사를 수행한다. 최초 검색의 재작성 기본 off, HyDE off와 실행 요청 차단은 유지한다.

현재 기본 `create_router_graph()`는 외부 서비스가 연결되지 않은 그래프다. 직접 사용할 때는 기존 검색·답변 팩터리와 새 노드를 함께 주입한다. `store`, `session`, 두 생성 콜백과 `source_root`는 호출자가 제공한다.

```python
from artagent.graph import create_answer_node, create_router_graph, create_search_nodes
from artagent.graph.research import create_research_node

graph = create_router_graph({
    **create_search_nodes(store, session, rewrite_enabled=False, hyde_enabled=False),
    "ANSWER": create_answer_node(generate=answer_generate, source_root=source_root),
    "RESEARCH": create_research_node(generate=rewrite_generate),
})
```

## 검증 범위

`tests/test_graph_research.py`는 두 검색 출처와 최초 재작성 on/off, 세 답변 상태, 단계별 기술 실패, 혼합 요청의 예산 공유, 저장된 추가 시도의 재개, 준비 기록 손상·유실, 설정 변경, 서비스 비활성화와 명확화 재개를 검증한다. 실제 T14/T17 노드와 임시 원문을 사용한 테스트에서는 세그먼트 해시·URL·원문 위치·제품 범위·인용을 대조한다. 생성·검색의 외부 경계만 대역으로 주입한다.

| 단일 항목 결과 | 추가 재작성 | 검색 합계 | 답변 노드 합계 |
| --- | --- | --- | --- |
| 최초 지원됨·미지원 | 0 | 1 | 1 |
| 부족→지원됨·미지원·부족 | 1 | 2 | 2 |
| 부족→재작성 실패 | 1 | 1 | 1 |
| 부족→검색 실패 | 1 | 2 | 1 |
| 부족→답변 실패 | 1 | 2 | 2 |

추가 시도는 완료 노드가 반환한 state를 보존·복원하는 경계에서 재개한다. 임의의 초기 검색·초기 답변 지점에서 그래프를 처음부터 호출하거나 외부 호출 도중 강제 종료한 경우의 중복 방지는 보장하지 않는다. 영속 checkpointer나 세션 저장 기능을 추가하지 않았다.

## 기존 봉인 기록 검증 보완

새 모듈 추가와 기존 파일 변경으로 T15의 과거 코드 지문이 현재 작업 파일과 달라졌다. `check_origins()`의 읽기 전용 계보 검증에는 `historical=True`를 명시하여 기록된 전체 Git 커밋의 파일 목록·원본 바이트·해시를 대조한다. 입력·모델·manifest·산출물 해시 검사는 유지한다. 새 실행과 기본 `verify_protocol()`은 현재 파일 목록·바이트와 기록된 Git 원본이 모두 일치해야 하므로 과거 프로토콜로 변경된 코드를 실행할 수 없다.

기존 봉인 기록의 재사용 126건·새 시도 4건·누락 9건 기대값은 유지한다. 지문 누락·추가·변조, 잘못된 커밋과 현재 실행 게이트를 별도 회귀로 검증하며 `data/eval/`의 기존 기록은 수정하지 않는다.

## 실행 환경과 완료 경계

Python 3.14 venv는 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3`를 사용한다. 명령은 저장소 루트에서 실행한다.

```bash
T16_PYTHON=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$T16_PYTHON" -m pytest -p no:cacheprovider tests/test_graph_research.py tests/test_cli.py tests/test_gui_bridge.py tests/test_t15_protocol_history.py tests/test_t15_answer_resume.py -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$T16_PYTHON" -m pytest -p no:cacheprovider tests -q --maxfail=3 --tb=short
PYTHONPYCACHEPREFIX=/tmp/t16-pycache "$T16_PYTHON" -m compileall -q src/artagent/graph src/artagent/cli.py src/artagent/gui_bridge.py scripts/t15_evaluation.py scripts/resume_t15_answers.py
git diff --check
```

샌드박스 안의 첫 전체 회귀에서는 기존 로컬 소켓 테스트가 `PermissionError`로 실패했다. 로컬 소켓을 허용한 실행에서는 해당 제약을 해소했다. 새 파일 때문에 발생한 T15 지문 오류는 위의 과거 코드 검증으로 보완했다. 최종 전체 회귀 결과는 아래에 기록한다.

**초기 구현 검증:** 전체 pytest **1,258개 통과**, 종료 코드 0, 364.04초. 당시 신규 T16 집중 사례는 70개다. 로그는 `/tmp/t16-full-before-review-improvements.log`에 보존했다.

## 리뷰 보완

2026-11-04 재검토에서 확인한 네 문제를 다음과 같이 보완했다.

| 문제 | 변경과 재현 검증 |
| --- | --- |
| 재개 단계와 결과의 모순 | `PREPARED`에는 검색 결과·답변이 없어야 한다. 완료된 검색의 단계만 되돌리거나 이전 답변을 남긴 state는 외부 호출 전에 `CONTRACT_VIOLATION`으로 거부한다. 저장 답변은 `SEARCHED`에서만 소비한다. |
| GUI 전체 제한과 생성 단계별 제한 불일치 | 요청 준비에 쓴 시간을 포함해 270초의 공통 생성 예산을 적용한다. 버전 조회·최초 답변·재작성·재답변이 남은 시간을 사용한다. 가상 시간에서 110+110+100초 흐름은 마지막 호출에 50초만 부여하고, 준비 40초가 있으면 마지막 호출은 10초로 제한한다. 300초의 네이티브 종료 전에 구조화된 오류를 반환한다. |
| 선택 정보인 리랭커 식별값을 필수로 접근 | `model_id`가 없으면 기존 검색과 동일하게 `unknown`을 사용한다. 해당 리랭커로 최초 검색과 재검색을 모두 확인했다. |
| 준비와 과거 검증의 코드 지문 조건 차이 | 평가 준비 전에 실행 대상 파일의 목록·바이트가 HEAD와 일치하는지 확인한다. 미커밋 수정·추가·삭제는 결과 폴더 생성이나 모델 처리 전에 거부한다. 준비한 코드 지문은 현재·과거 검증에 모두 통과해야 한다. 실행 대상이 아닌 문서 변경은 허용한다. |

외부 API 방식도 연결·헤더·본문 수신 전체를 남은 시간으로 제한한다. 기한이 있는 요청은 표준 라이브러리만 사용하는 별도 프로세스에서 수신하며, 기한 초과 시 종료·회수한다. 요청 본문과 인증 헤더는 표준 입력으로 전달하고 명령행에 넣지 않는다. 응답은 바이트로 전달해 자식 프로세스의 출력 로케일이 ASCII여도 한국어를 보존한다. GUI의 준비·생성 예산은 요청마다 초기화하며 중첩 예산은 상위 기한을 늘리지 않는다. GUI 밖의 기본 생성 제한은 유지한다.

`tests/test_generation_budget.py`에서 실제 GUI 그래프와 가상 시간, 느린 응답 프로세스, 출력 인코딩, 시간 예산 초기화·중첩, 호출 증거와 버전 조회를 검증한다. `tests/test_t15_protocol_history.py`에서는 임시 Git 저장소로 준비 단계의 거부와 현재·과거 검증의 일치를 확인한다. 실제 저장소의 커밋된 실행 파일 24개도 같은 조건으로 검증했다. 기존 봉인 기록은 수정하지 않았다.

**리뷰 보완 후 전체 검증:** pytest **1,272개 통과**, 종료 코드 0, 362.78초. T16 집중 사례 73개, GUI 시간 예산 사례 7개를 포함한다. Python 구문 컴파일과 `git diff --check`도 종료 코드 0이다. 기존 Chroma·Torch 경고 3건은 숨기지 않았다. 최종 로그는 `/tmp/t16-full-pytest-final.log`에 보존했다.

이번 검증은 외부 생성 호출 없이 수행한다. 실제 생성 제공처·실제 검색 저장소를 사용하는 Slice 1 15개 답변 비교와 화면 조작은 수행하지 않았으며 CP3를 완료로 판정하지 않는다. C++·프로필 형식·영상 처리 의미를 변경하지 않아 GUI/CLI 재빌드와 PPVERSION 증가는 필요하지 않다. push·PR은 수행하지 않는다.
