# 실시간 노출 클라이언트와 채팅 연결 구현 플랜

- 기준: `main`의 `be77ac6e5` 및 병합된 PR #19.
- 작업 브랜치: `kninemikug/T-live-param-client`.
- 계약 근거: `docs/ART_live_param_feasibility.md` §7과 `docs/ART_live_param_impl_plan.md` §1~2.
- 기존 `tasks/plan.md`·`tasks/todo.md`의 미완료 Phase A 작업은 보존한다. 이 문서가 이번 후속 작업의 플랜·체크리스트다.

## 1. 완료할 사용자 동작

macOS에서 GUI 허용 설정을 켠 ART의 현재 편집 사진에, 외부 Python 프로그램 또는 채팅에서 명시한 노출 절대값을 적용하고 실제 화면 자료 준비 결과를 확인한다. 예시는 `/exposure 0.75`와 `노출을 0.75 EV로 설정해줘`다. 결과에는 실제 반영값을 표시한다. 기존 환경변수의 호환 규칙은 §7에 기록한다.

범위는 `Exposure.Compensation` 한 키와 기존 Unix socket v1 계약으로 한정한다. C1~C4는 기존 환경변수로 활성화하는 연결을 완성했다. 이후 요청한 GUI 허용 설정은 §7에 따라 추가한다. 전송·서버 연산·프로필 버전·엔진 처리식은 유지한다.

저장소의 현재 채팅은 문서 Q&A를 제공하고 일반 EXECUTE를 차단한다. 추천 프로필 생성기는 아직 연결돼 있지 않다. 이번에는 숫자가 명시된 단일 노출 명령을 별도 처리하고, 추천 결과를 만드는 기능과 자유 서술에서 값을 추측하는 동작은 포함하지 않는다. 후속 추천기는 같은 Python 단일 키 API를 호출할 수 있다. `.arp` 생성·일괄 적용·렌더링·세션 기억·상대값 증감은 별도 범위다.

## 2. 경계와 계약

### Python 클라이언트

- 표준 라이브러리만 사용한다. 공개 모듈은 `src/artagent/live_param.py`, CLI는 `python -m artagent.live_param_cli`로 분리한다.
- 연결 대상 socket 경로를 명시한다. 자동으로 다른 인스턴스를 선택하거나 GUI를 시작하지 않는다. 대상은 `(sessionId, editorId, baseRevision)`의 변경 불가능한 복사본으로 전달한다.
- `get_state`·`set_param`만 사용한다. JSON 객체 + LF, UTF-8, 본문 64 KiB, 유일한 요청 ID와 서버의 응답 형식을 유지한다. 응답도 중복 키·타입·버전·요청 ID·세션·편집기·상태를 확인한다.
- `set_param`은 한 번만 전송한다. 전송 후 연결 종료·시간 초과·잘못된 응답은 결과 불명으로 취급하며 자동 재전송·새 revision 재시도·값 되돌리기를 하지 않는다. 조회에 필요한 원래 요청 ID와 대상을 보존한다.
- `APPLIED`의 실제 반영값을 보존하고 `mutationRequestId` 조회로 `READY/PENDING/SUPERSEDED/FAILED/UNKNOWN`을 구분한다. 완료 판정은 해당 변경 ID·적용 revision과 현재 뷰의 표시 자료를 확인한다. 기한은 연결·읽기·폴링을 포함한 단조 시계의 상한으로 제한한다.
- 반영을 확인한 뒤의 미리보기 지연·실패는 반영 실패로 바꾸지 않는다. CLI와 GUI는 반영 확인·화면 준비·결과 불명을 구분해 안내한다. 내부 경로·예외를 채팅 응답에 노출하지 않는다.

### CLI

`state`, `set`, `status` 세 하위 명령을 제공한다. 모든 명령에 `--socket`이 필요하다. `set`은 `--session`, `--editor`, `--revision`, `--value`를 명시한다. `status`는 원래 변경의 `--mutation`을 조회한다. `--wait`는 실제 미리보기 준비를 기다리며 자동 적용 재시도를 뜻하지 않는다. stdout은 JSON 한 객체로 유지한다. 유효하지 않은 입력은 연결 전에 거부한다.

### 채팅 연결

- 기존 질문 요청에 선택적 `live_param` 객체를 추가한다. 이 객체는 ART GUI 메인루프가 전송 시점의 현재 편집기에서 복사한 `socket_path`, `session_id`, `editor_id`, `base_revision`만 포함한다. 지원 검증은 일반 GUI의 주 창 편집 탭과 단독 GUI로 한정한다. 별도 편집 창·다중 모니터 배치는 이번 완료 범위에 포함하지 않는다. 파일 브라우저·사진 없음·기능 OFF에서는 대상을 만들지 않는다.
- Python 채팅 연결은 전체 문자열이 허용한 명령 문형과 일치하고 유한한 절대값이 있을 때만 노출 경로를 실행한다. 인용된 예시·질문·부정문·복합 요청·값 없는 요청을 적용 명령으로 추측하지 않는다. 일반 질문과 나머지 EXECUTE는 기존 경로를 유지한다.
- 명시적 노출 명령은 검색 저장소·외부 답변 호출 없이 수행한다. 대상·revision이 바뀌면 그대로 거부하고 다른 사진이나 최신 revision으로 바꾸어 적용하지 않는다.
- 기존 채팅 응답 envelope를 유지한다. 성공은 화면 준비를 확인한 경우에만 `COMPLETED`, 이미 반영됐지만 화면 지연·대체·실패가 있거나 반영 여부가 불명확하면 이를 설명하는 `PARTIAL`로 구분한다. 적용 전 확정 오류는 `FAILED`다.
- 취소·시간 초과는 응답 대기를 중지하는 동작이다. 이미 반영된 편집을 취소했다고 표시하지 않는다. 현재 노출을 확인하도록 안내하며 자동 되돌리기는 없다.

## 3. 순서·완료 조건·예상 파일

### C1 — Python 소켓 클라이언트

예상 파일: `src/artagent/live_param.py`, `tests/test_live_param.py`.

- [x] 실제 Unix socket의 정상·조각난 응답과 요청/응답 ID·세션·대상을 검사한다.
- [x] 입력·응답 크기·UTF-8·JSON·비유한값·타입 위반과 전송 후 결과 불명을 검사한다.
- [x] 단일 변경 이후 상태 조회·완료 대기·충돌·실패·대체·알 수 없는 요청을 구분하고 재전송하지 않는다.

검증: 해당 pytest 모듈. 오류 사례는 서버의 수신 요청 수와 요청 본문도 대조한다.

### C2 — 외부 CLI

의존: C1. 예상 파일: `src/artagent/live_param_cli.py`, `tests/test_live_param_cli.py`.

- [x] 상태 조회·명시적 대상의 단일 키 변경·이전 변경 조회를 제공한다.
- [x] 실제 반영값·대기 상태·오류를 JSON과 종료 코드로 구분한다.
- [x] 잘못된 값·필수 인자 누락은 서버 접속 없이 거부한다.

검증: 실제 CLI 하위 프로세스와 임시 Unix socket을 사용한 pytest. C1~C2 통과 후 첫 구현 커밋.

### C3 — Python 채팅의 제한된 노출 명령

의존: C1. 예상 파일: `src/artagent/live_param_chat.py`, `src/artagent/gui_bridge.py`, `tests/test_live_param_chat.py`, `tests/test_gui_bridge.py`.

- [x] 명시적 단일 절대값 명령만 실행하고 원래 대상 복사본을 사용한다.
- [x] 반영·화면 준비·부분 완료·결과 불명을 구분하며 Q&A와 일반 EXECUTE 차단 회귀가 없다.
- [x] 노출 경로는 검색·답변 기능을 초기화하지 않는다.

검증: parser와 실제 Unix socket을 거치는 채팅 연결 pytest. C3 통과 후 두 번째 구현 커밋.

### C4 — 현재 편집기 연결과 실제 GUI 검증

의존: C2~C3. 예상 파일: `rtgui/chatconnection.h/.cc`, `rtgui/chatpanel.h/.cc`, `rtgui/rtwindow.cc`, `rtgui/test_liveparam_gui.cc`, `rtdata/languages/default`·`Korean`. 안내 문구와 검사를 같은 연결 변경에 포함한다.

- [x] GUI 메인루프에서 현재 대상·revision을 소유 복사하고 비동기 작업에 위젯·엔진 포인터를 넘기지 않는다.
- [x] 실제 ChatConnection → Python → Unix socket → EditorPanel 경로로 노출·히스토리·화면 준비를 확인한다. OFF·사진 없음·오래된 대상/리비전·사진 재열기·취소도 검증한다.
- [x] GUI/CLI 빌드, 새 GUI 검사와 기존 OFF·프레임 경계 회귀, 새 경로의 ASan·TSan 및 전체 Python 검사를 통과한다.

검증과 문서의 실제 결과 기록 후 세 번째 구현 커밋. 현재 작업의 후속 PR·병합은 별도 지시 시 진행한다.

## 4. 검증 명령과 기록

Python은 기존 루트 Python 3.14 환경을 사용하고 새 의존성을 설치하지 않는다. 이 worktree에는 `venv/`가 없으므로 기존 저장소의 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3`를 사용한다. 실행 자료는 gitignored `build/liveparam-client-checks/`에 보관한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest tests/test_live_param.py tests/test_live_param_cli.py tests/test_live_param_chat.py tests/test_gui_bridge.py -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest tests -q
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 4 --target art art-cli test_liveparam_gui
build/rtgui/test_liveparam_gui --case T01 --case T10 --case T16
build/rtgui/test_liveparam_gui --case T17
cmake --build build/asan --parallel 4 --target art art-cli test_liveparam_gui
build/asan/rtgui/test_liveparam_gui --case T16
build/asan/rtgui/test_liveparam_gui --case T17
cmake --build build/tsan --parallel 4 --target art art-cli test_liveparam_gui
build/tsan/rtgui/test_liveparam_gui --case T16
build/tsan/rtgui/test_liveparam_gui --case T17
build/rtgui/test_liveparam_gui --case T18
build/asan/rtgui/test_liveparam_gui --case T18
build/tsan/rtgui/test_liveparam_gui --case T18
```

`T16`은 실제 채팅의 적용·충돌·재열기·취소·대상 없음·OFF를 검사하고, `T17`은 별도 프로세스의 일반 GUI에서 탭 전환과 파일 브라우저의 대상 부재를 검사한다. 인자 없는 전체 GUI 검사도 `T17`을 별도 프로세스로 실행하고 그 실패를 전체 결과에 반영한다.

새 C++ GUI 경로는 기존 `build/asan`·`build/tsan`의 검출 옵션을 유지하여 빌드·실행한다. ASan은 Debug와 `-fsanitize=address -fno-omit-frame-pointer`, TSan은 Debug와 `-fsanitize=thread -fno-omit-frame-pointer`, `CMAKE_CXX_FLAGS_DEBUG=-g -O1` 설정이다. `-ffast-math`·in-source 빌드·임의 완화·미실행 검사의 성공 표시는 금지한다. 엔진 처리·직렬화 변경이 없으므로 PPVERSION은 기존 `1045`를 유지한다. 기존 GUI의 프로필 재열기·수동/외부 조정·출력 일치 검사를 다시 실행하여 그 전제를 확인한다.

## 5. 상태와 발견한 제약

- C1~C2 완료: 실제 Unix socket과 CLI 하위 프로세스 검사 45건 통과(`c1-c2-green.log`, 종료 코드 `0`). 전송 후 연결 종료·잘못된 응답·내부 오류는 결과 불명으로 구분하고 자동 재전송하지 않는다. C3도 명시적 노출·질문/부정/복합 요청 구분과 기존 GUI 연결의 40건 검사(경고 1건)를 통과했다(`c3-green.log`).
- C4 완료: Release GUI·CLI 빌드 성공(`c4-final-build.log`). GUI 전체 `T01`~`T14`, `T16`, 별도 일반 GUI의 `T17` 통과(`c4-release-all.log`), 대상 없음 검사를 보강한 최종 `T01/T10/T16`도 통과(`c4-final-release.log`). `0.125` 입력의 실제 `0.13` 반영·revision/히스토리 각 1회 증가·현재 뷰 `READY`, 충돌·재열기·취소·OFF·대상 없음·탭 전환을 실제 Python과 수신부를 거쳐 확인했다. 일반 GUI 검사 준비에서 직접 `EditorPanel`을 구성하다 발생한 충돌은 실제 `FileCatalog` 파일 열기 경로로 준비를 바꾸어 해결했다. 제품 엔진·서버에는 해당 수정이 없다.
- ASan·TSan GUI/CLI 빌드와 각 `T16/T17` 통과, 검출 보고 없음(`c4-asan-build.log`, `c4-tsan-build.log`, `c4-asan-t16-final.log`, `c4-asan-t17.log`, `c4-tsan-t16-final.log`, `c4-tsan-t17.log`). 전체 Python 검사도 1,129건 통과, 경고 3건(`python-all.log`, 349.41초). 모든 실행 종료 코드 `0`. 기존 Python 의존성의 폐기 예정 API 경고와 로컬 GTK의 `quartz` 입력 모듈 경고는 별도로 남아 있다.
- 추천 생성·`.arp` 실행·다른 키는 기존 미완료 Phase A와 분리한다. 이번 결과를 추천 전체 기능의 완료로 표시하지 않는다.

## 6. 사용 절차

1. `build/liveparam-client-checks/ARTLiveParamClient.app`을 일반 앱처럼 연다. 로컬 번들은 실행 파일과 런타임 자료를 포함하고 다른 ART 인스턴스와 별도 사용자 설정으로 실행한다. 터미널 환경변수를 입력할 필요가 없다. 현재 macOS 빌드의 `DATA_SEARCH_PATH`는 `../../Contents/Resources`이므로 `build/rtgui/ART`만 단독 실행하지 않는다.
2. 채팅의 **연결 설정**에서 **채팅으로 노출 조정 허용**을 켠다. 영문 표시는 **Connection settings → Allow exposure adjustment from chat**이다. 처음에는 꺼져 있으며 변경은 즉시 적용되고 다음 실행에도 유지된다. Python 실행 파일·현재 저장소·검색 저장소의 기본 경로는 필요한 경우 같은 설정에서 변경한다. 명시적 노출 명령은 검색 저장소를 읽지 않는다. 사진을 열고 주 창에서 대상 편집 탭을 선택한 뒤 `/exposure 0.75` 또는 `노출을 0.75 EV로 설정해줘`를 보낸다.
3. 표시된 값과 화면 준비 안내를 확인한다. 취소·부분 완료·결과 불명에서는 현재 노출을 확인하고 판단한다. 같은 명령을 자동으로 다시 보내지 않는다.

외부 CLI는 대상 GUI 프로세스의 `/tmp/art-liveparam-<uid>/art-<pid>-<sessionId>.sock` 경로를 명시한다. `state`로 세션과 편집기 목록을 얻고, 명시적 편집기의 `state`로 현재 revision을 확인한 뒤 `set`에 전달한다. 아래 변수에는 확인한 경로·식별자·revision을 넣는다. 다른 실행의 소켓을 임의로 선택하지 않는다.

```bash
PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m artagent.live_param_cli --socket "$ART_SOCKET" state
PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m artagent.live_param_cli --socket "$ART_SOCKET" state --session "$ART_SESSION" --editor "$ART_EDITOR"
PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m artagent.live_param_cli --socket "$ART_SOCKET" set --session "$ART_SESSION" --editor "$ART_EDITOR" --revision "$ART_REVISION" --value 0.75 --wait
```

이전 변경은 `status --session "$ART_SESSION" --editor "$ART_EDITOR" --mutation "$ART_MUTATION"`으로 조회한다. CLI 종료 코드는 성공 `0`, 적용 전 확정 오류 `1`, 잘못된 인자 `2`, 반영 후 미리보기 문제 또는 반영 여부 불명 `3`이다. `set`의 `APPLIED`는 저장 완료를 뜻하지 않으며 기존 GUI 저장 정책을 따른다.

## 7. GUI 허용 설정 후속 변경

앱을 평소처럼 실행한 뒤 채팅 연결 설정의 **채팅으로 노출 조정 허용**을 켜고 끈다. 처음에는 꺼져 있으며 명시적으로 저장한 선택을 다음 실행에도 유지한다. 저장 위치는 기존 사용자 설정 `artagent.ini`의 `[Chat] live_exposure`다. 저장한 선택이 있으면 환경변수보다 우선한다. 선택을 아직 저장하지 않았을 때만 기존 `ART_LIVE_PARAM=1` 호환 경로를 사용한다. 잘못된 설정은 비활성화로 처리한다. 체크 변경은 요청 전송 없이 즉시 저장하며, 기존 Python·자료·검색 저장소 설정과 서로 덮어쓰지 않는다.

지원은 macOS의 주 창 편집 탭·단독 GUI, `Exposure.Compensation` 한 키다. 허용을 켜면 기존 Unix socket 서버를 시작하고 GUI 메인루프에서 열린 편집기에 새 식별자를 등록한다. 기존 파라미터 값·히스토리는 보존하고 기존 조정기의 전체 갱신 이벤트로 현재 자료의 세대를 다시 추적한다. Crop의 뷰 식별자도 새 세션에 다시 발급하며 기존 줌의 지연 갱신 상태를 이어받는다. 끄면 수신부·대기 요청을 정지하고 편집기 리스너·등록을 해제한다. 이미 반영된 값은 유지한다. 다시 켜면 새로운 세션을 사용하여 이전 대상·요청이 뒤따라 적용되지 않게 한다. 실행 중 `ProcessingJob` 수정·재사용은 하지 않는다. 켜기 선택을 저장하지 못하면 수신부를 켜지 않는다. 끄기 선택의 저장 실패는 현재 실행의 비활성화를 막지 않으며 다음 실행의 설정 확인을 안내한다.

- [x] G1 — 기본 OFF·설정 저장·기존 설정 보존·저장 실패·설정 우선순위를 실제 설정 파일로 검증했다. 변경: `chatpanel.h/.cc`, `main.cc`, 안내 언어 파일. `T18` 및 실제 GUI 시작 검사에서 저장한 ON의 환경변수 없는 시작, 저장한 OFF의 환경변수 ON보다 높은 우선순위를 확인했다(`startup-final.log`, 종료 코드 `0`).
- [x] G2 — 실제 체크박스로 열린 사진의 허용/해제·다시 허용과 실제 채팅 적용을 검증했다. 변경: `liveparamserver.h/.cc`의 명시적 허용 진입, `editorpanel.h/.cc`의 등록·리스너 수명, `crophandler.h/.cc`의 새 세션 뷰 재등록, `rtwindow.cc`의 GUI 연결, `test_liveparam_gui.cc`의 `T17/T18`. 다중 탭의 이전 뷰 번호가 남아 `BUSY`가 지속된 재현을 뷰 재등록으로 수정했다. 열린 탭 전체 등록, 기존 값·히스토리 보존, 오래된 세션 거부와 줌 지연 중의 허용 변경을 확인했다.
- [x] G3 — GUI/CLI 아웃오브소스 빌드, 기존 기본 OFF·채팅·저장/출력 회귀와 새 경로의 ASan·TSan 검사를 통과하고 번들을 갱신했다. 엔진·직렬화·PPVERSION은 변경하지 않았다. `release-final-all.log`의 전체 GUI 17개 사례, `protocol.log`, Python 연결 회귀 85건(`python-regression.log`, 경고 1건), `asan-final-t17.log`·`asan-final-t18.log`·`tsan-final-t17.log`·`tsan-final-t18.log` 모두 종료 코드 `0`. 메모리·스레드 검출 보고는 없으며 기존 GTK 입력 모듈 경고는 남아 있다. 결과는 `build/liveparam-gui-settings-checks/`에 기록했다.
