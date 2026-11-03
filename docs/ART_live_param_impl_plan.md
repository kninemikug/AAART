# 실행 중 ART의 단일 노출 파라미터 조정 구현 플랜

## 1. 최소 범위 확정

유일한 설계 근거는 [ART_live_param_feasibility.md](ART_live_param_feasibility.md)다. 이 플랜은 해당 문서의 후보 B를 구체화하며, §5의 **1~4번을 네 구현 단계**로 사용한다. §5의 5번에 있는 일치·수명 검증은 완료 조건에 반영하고, 키 확장은 후속 범위에만 남긴다.

| 항목 | 이번 범위 |
|---|---|
| 조정 키 | `Exposure.Compensation` 단 1개. 절대값 설정만 허용한다. |
| OS·전송 | macOS의 Unix socket만 지원한다. Windows/Linux 지원과 다른 전송 수단은 제외한다. |
| 실행 대상 | 실행 중인 GUI 프로세스에서 사진이 열린 편집기. 별도 상주 프로세스와 헤드리스 상주 데몬은 금지한다. |
| 시작 방식 | 일반 GUI와 단독 편집 시작의 `Gtk::Application`·`Gtk::Main` 분기 모두에 같은 수명 규칙을 적용한다. |
| 기본 상태 | **OFF**. GUI 시작 시 환경변수 `ART_LIVE_PARAM`이 정확히 `1`인 경우에만 수신부를 시작한다. 미설정·빈 값·그 밖의 값은 OFF다. 별도 옵션이나 영구 설정은 추가하지 않는다. |
| 지원 편집 상태 | 초기 로드가 끝난 일반 편집 상태. spot 편집 등 `TweakOperator` 활성 상태, 초기화 중, 종료 중은 `BUSY`로 거부한다. 팬·줌과 GUI 조작은 허용하되 동시 실행 검증을 통과해야 한다. |
| 흐름 제어 | 편집기당 외부 변경 하나가 미리보기 처리 중이면 다음 변경은 `BUSY`. 기존 GUI 조작은 허용하며, 미완료 외부 변경이 대체되면 `SUPERSEDED`로 보고한다. |
| 저장·내보내기 | 외부 변경도 일반 GUI 편집의 기존 저장 정책을 따른다. 실행 중 내보내기는 생성 당시 값을 유지한다. |

기능이 OFF이면 소켓·수신 스레드·명령 큐를 생성하지 않고 경로도 공개하지 않는다. 시작 조건 검사는 GUI 공통 수명에 수신부를 붙이기 전에 둔다. 수신부의 시작 진입점에서도 macOS와 활성화 조건을 확인한다. 시작이나 인증 준비가 실패하면 수신을 열지 않으며 다른 전송으로 전환하지 않는다. `.arp`에는 환경변수, 접속 정보, 요청 ID, revision, 큐·캐시 상태를 저장하지 않는다.

이번 산출물은 이 문서 하나다. 아래의 규칙 갱신, 코드 변경, 빌드와 실행 검증은 후속 작업이며 이 문서 작성 중에는 수행하지 않는다.

## 2. 고정할 외부 계약 — 기준 문서 §7

### 전송·인증·조회

- UTF-8 JSON 한 객체와 LF를 한 프레임으로 사용한다. 문자열 내부 줄바꿈은 이스케이프하고 중복 JSON 키는 거부한다.
- 초기 한도는 프레임 **64 KiB**, 연결별 미처리 요청 **1개**, GUI 명령 큐 **32개**로 고정한다. 입력·크기 위반은 `INVALID_REQUEST`, 큐·처리 용량 포화는 `BUSY`로 거부하고 적용하지 않는다.
- 사용자 전용 디렉터리와 제한된 소켓 권한을 사용한다. 구현 시 디렉터리 `0700`, 소켓 `0600`을 적용하고, 인스턴스별 경로를 분리한다. 다른 인스턴스의 소켓을 재사용하거나 제거하지 않는다.
- 연결마다 macOS의 커널 제공 상대 사용자 자격을 확인하여 GUI 실행 사용자와 일치할 때만 인증한다. 이 연결 인증을 마치기 전에는 조회·변경 명령을 GUI에 전달하지 않는다. 사용자 확인이 실패하거나 불가능하면 `UNAUTHORIZED`로 거부한다. 별도 인증 연산이나 JSON 필드는 추가하지 않는다.
- 지원 연산은 `get_state`, `set_param`뿐이다. 파일 열기, 명령 실행, 범용 구조체 쓰기, 네트워크 바인딩은 제공하지 않는다.
- 최초 `get_state`의 필수 필드는 `protocolVersion`, `requestId`, `op`다. `editorId` 생략 시 편집기 목록, 지정 시 해당 편집기 상태를 반환한다. 재연결 시 선택적으로 `sessionId`를 보내 같은 실행인지 확인한다.
- 조회는 GUI 메인루프에서 일관된 소유 복사본을 만든다. `sessionId`, `editorId`, `revision`, `viewRevision`, 허용 키·범위·활성 상태와 최근 요청 상태를 제공하며 I/O 스레드에서 엔진 상태를 읽지 않는다.

### 단일 키 요청과 응답

요청 형식은 §7.2의 예시를 그대로 사용한다.

```json
{
  "protocolVersion": 1,
  "requestId": "req-00042",
  "op": "set_param",
  "sessionId": "run-7f21",
  "editorId": "editor-c903",
  "baseRevision": 17,
  "params": {
    "Exposure.Compensation": 0.75
  }
}
```

| 필드·매핑 | 고정 규칙 |
|---|---|
| `protocolVersion` | 모든 요청에 정수 `1`이 필수다. PPVERSION과 독립적이다. |
| `requestId` | 모든 요청에 1~128자 문자열이 필수다. 연결을 넘어 실행 세션 안에서 유일하게 발급한다. |
| `sessionId`, `editorId` | `set_param`에 필수다. 실행마다 새 `sessionId`, 같은 사진을 다시 열어도 새 `editorId`를 사용한다. 활성 탭을 암묵적으로 대상으로 삼지 않는다. |
| `baseRevision` | `set_param`에 필수인 음이 아닌 정수다. 적용 직전 현재 revision과 같아야 한다. |
| `params` | `set_param`에 필수인 객체이며 `Exposure.Compensation` 하나만 받는다. 다른 모든 필드와 생략된 기존 값은 보존한다. |
| 키 매핑 | `Exposure.Compensation` → `[Exposure] Compensation` → `ProcParams::exposure.expcomp` → `EvExpComp`. |
| 값 | EV 단위의 유한 실수 `-12..12`. `NaN/Infinity`, 문자열 숫자, 잘못된 타입·범위는 거부하고 조용히 보정하지 않는다. GUI 조작 간격 `0.05`를 허용 범위와 혼동하지 않는다. |
| 도구 상태 | 꺼져 있으면 `TOOL_DISABLED`. 임의 활성화하지 않는다. |

GUI 콜백 안에서 입력·대상·revision 검증을 끝낸 다음 컨트롤·편집 상태·`nextParams`를 함께 갱신한다. 성공 응답의 공통 필드는 `protocolVersion`, `requestId`, `sessionId`, `editorId`, `status`, `result`이며, 실패에는 `result` 대신 `error`만 둔다.

| 응답·조회 필드 | 의미와 판정 |
|---|---|
| `status: APPLIED` | GUI 반영 완료. 파일 저장이나 미리보기 완료를 뜻하지 않는다. `result`에 `appliedRevision`, `viewRevision`, `effectiveParams`, `previewStatus`, `renderedRevision`, `renderedViewRevision`, `ppVersion`을 반환한다. 최초 미리보기 상태는 `PENDING`이다. |
| `status: OK` | `get_state` 성공. 현재 `revision`, `viewRevision`, 결과의 `renderedRevision`, `renderedViewRevision`과 `lastMutation`을 조회한다. |
| `lastMutation` | `requestId`, `appliedRevision`, `previewStatus`를 포함한다. 선택 문자열 `mutationRequestId`로 캐시에 남은 이전 변경을 조회한다. 조회 자체의 `requestId`와 구분한다. |
| `previewStatus: READY` | 같은 편집·뷰 세대의 Navigator와 주 표시 Crop 결과가 GUI에 전달되어 표시 자료가 준비됨. 실제 모니터 그리기, 별도 상세 창, 전체 해상도 출력 완료는 포함하지 않는다. |
| `SUPERSEDED`, `FAILED` | 후속 편집에 대체된 미완료 요청, 반영 후 렌더 실패를 각각 보고한다. 렌더 실패로 반영한 값을 취소하지 않는다. |
| `renderedRevision`, `renderedViewRevision` | 정수 또는 `null`. 두 세대를 쌍으로 판정한다. 세대가 불명확하면 완료를 추정하지 않고 `null`을 사용한다. |
| 캐시에 없는 변경 조회 | `lastMutation: null`, `mutationStatus: UNKNOWN`. 성공·실패를 추측하지 않는다. |
| `ppVersion` | 실제 프로필 버전 진단값이다. 기준 문서의 값은 `1045`이며 유지 여부는 아래 회귀 판정에 따른다. |

### 충돌·재전송·오류

`revision`은 GUI 메인루프에서 단조 증가시킨다. 외부 변경뿐 아니라 마우스 조작, 히스토리 이동, 프로필 변경, 처리 결과의 자동값이 편집 상태에 반영되는 경우도 포함한다. 비교 → GUI 갱신 → revision 발급을 같은 콜백에서 수행한다. 같은 값을 성공적으로 설정해도 한 번 증가한다. 팬·줌은 별도 `viewRevision`으로 구분한다.

응답 캐시는 GUI 프로세스가 소유하고 `(sessionId, editorId, requestId)`로 식별한다. 같은 ID·같은 내용은 재실행 없이 처리 중 상태나 원래 응답을 반환한다. 다른 내용은 `REQUEST_ID_CONFLICT`다. 기존 ID 조회 → 입력·대상·revision 검사 → 캐시 자리 예약 → 값 적용 순서를 GUI 직렬 처리에서 확정한다. 처리 중 항목은 만료시키지 않고, 완료부터 **5분**, 최대 **1024건**을 유지한다. 기한 전 조기 폐기 없이 포화 시 `BUSY`로 거부한다. 수락 전 오류는 변경 요청 캐시에 등록하지 않는다.

연결 종료·타임아웃은 적용 실패가 아니다. 보관 기간 내 같은 요청의 재전송은 캐시로 처리한다. 기한 경과나 재시작 후에는 `get_state`로 확인하고 새 revision에 근거한 별도 요청을 만든다. 타임아웃을 이유로 값을 되돌리지 않는다.

| 오류 코드 | 적용 조건 |
|---|---|
| `INVALID_REQUEST` | JSON·중복 키·타입·알 수 없는 필드·연산·크기 위반. 해석 불가능한 `requestId`는 `null` 허용. |
| `UNSUPPORTED_VERSION` | 지원하지 않는 프로토콜 버전. |
| `UNAUTHORIZED` | 사용자·연결 인증 실패. |
| `SESSION_MISMATCH` | GUI 실행 ID 불일치. |
| `EDITOR_NOT_FOUND` | 대상 부재·닫힘·재열기로 이전 대상이 무효화됨. |
| `REVISION_CONFLICT` | 기준 revision 불일치. |
| `UNSUPPORTED_PARAM` | 허용 목록 밖의 키. |
| `INVALID_VALUE` | 값의 타입·유한성·범위 위반. |
| `TOOL_DISABLED` | 도구 비활성 상태. |
| `BUSY` | 초기화·미지원 편집 모드·해당 편집기의 외부 미리보기 처리 중·큐/캐시 포화·종료 중. |
| `REQUEST_ID_CONFLICT` | 같은 ID를 다른 내용에 재사용함. |
| `INTERNAL_ERROR` | 적용 전 또는 결과 불명의 내부 실패. 상태를 확인한다. |

오류 응답은 §7.4와 같이 `status: ERROR`, `error.code`, `message`, `details`, `retryable`을 사용한다. 내부 예외나 로컬 파일의 전체 경로를 노출하지 않는다. `retryable`은 같은 기준 상태로 나중에 재시도할 수 있다는 뜻이며 결과 불명과 동일하지 않다. 반영 후 렌더 오류는 해당 변경의 `previewStatus: FAILED`와 오류 상세로 보고한다.

## 3. 파일별 변경 목표

아래는 기준 문서 §2·§5·§9에 근거한 변경 예정 지점이다. 신규 파일명은 이 플랜의 배치안이며 기존 API가 있다는 뜻이 아니다. 관련 선언부 변경도 같은 역할로 한정한다.

### rtgui 중심 변경

| 파일 | 역할·변경 목표 | 단계 |
|---|---|---|
| `rtgui/liveparamserver.h`, `rtgui/liveparamserver.cc` 신규 | Unix socket 생성·인스턴스 분리·연결 인증·프레임 파싱·크기 제한·유한 큐·응답 송신. 소유한 명령 복사본만 전달한다. GTK·조정기·`ProcessingJob`에 접근하거나 raw `EditorPanel*`을 보관하지 않는다. | 3 |
| `rtgui/liveparamcontroller.h`, `rtgui/liveparamcontroller.cc` 신규 | GUI 메인루프의 명령 처리, GUI 소유 편집기 레지스트리, ID·revision 검사, 응답 캐시, 상태 복사본과 완료 상태 관리. `IdleRegister` 패턴으로 전달하고 무효화 가능한 수명을 사용한다. | 2~4 |
| `rtgui/main.cc` | 공통 GUI 수명에 활성화 조건과 서버 소유권을 연결한다. 두 기동 분기에서 OFF 검사를 서버 생성 전에 수행한다. GUI 종료 시 수신 중단을 먼저 시작한다. | 3 |
| `rtgui/editorpanel.cc` | `open()`마다 새 `editorId`를 등록한다. `close()` 시작 시 대상과 대기 명령을 무효화하고 처리·리스너 해제를 정렬한다. 기존 저장 정책을 유지한다. | 2~4 |
| `rtgui/toolpanelcoord.cc` | `applyExternalPatch` 성격의 GUI 진입점. 패널 현재 값의 복사본에서 `expcomp`만 변경하고, 컨트롤 동기화 후 `panelChanged(EvExpComp, ...)`와 동등한 경로를 정확히 한 번 수행한다. GUI 편집·히스토리·프로필·자동값 반영의 revision 경계도 연결한다. | 2·4 |
| `rtgui/exposure.cc` | 필요할 때만 패널 접근부를 최소 보완한다. `Exposure::read()`처럼 리스너를 차단한 컨트롤 갱신을 재사용한다. 다른 노출 필드와 도구 활성 상태를 보존한다. | 2 |
| `rtgui/previewhandler.cc`, `rtgui/crophandler.cc` | Navigator·주 Crop 결과의 편집·뷰 세대를 GUI 전달까지 보존하고 두 결과가 같은 세대로 준비됐는지 집계한다. 오래된 결과나 진행률 종료로 `READY`를 추정하지 않는다. | 4 |
| `rtgui/CMakeLists.txt` | 단계 2의 명령 처리와 단계 3의 수신부 도입 시 각각 필요한 GUI 소스만 등록한다. 수신부의 macOS 한정과 다른 OS에서의 비활성 상태를 보장한다. 새 의존성은 필요성이 확인된 경우에만 도입한다. | 2·3 |

`rtgui/guiutils.cc`의 `IdleRegister`는 기존 수명 관리 패턴을 재사용할 참조 지점이며, 공통 동작을 바꾸는 대상으로 잡지 않는다. `rtgui/main-cli.cc`에는 서버나 상시 루프를 추가하지 않는다. 그룹 단위 `ParamsEdited`만으로 다른 노출 필드 보존을 가정하지 않고, 기본값을 채운 전체 프로필로 덮어쓰지도 않는다.

### rtengine 최소 변경

| 파일·함수/경로 | 최소 변경과 이유 |
|---|---|
| `rtengine/improccoordinator.h`, `rtengine/improccoordinator.cc` — `beginUpdateParams()`, `endUpdateParams()`, `process()` | `nextParams`에서 작업용 `params`로 복사하는 경계와 Crop의 동시 읽기·임시 변경을 함께 보호한다. 작업 스냅샷과 revision을 같은 시점에 묶고 결과까지 운반한다. 외부 I/O 작성자는 추가하지 않는다. |
| 같은 파일 — `getParams()`, 실행·정지, `updaterRunning`, `tweakOperator` 설정·해제 경계 | §2.2가 지적한 공유 상태의 보호 범위를 확인하고 확인된 경쟁만 수정한다. GUI 패치는 잠금 없는 `getParams()`를 스냅샷 취득 수단으로 사용하지 않는다. 종료 중 갱신 예약을 차단한다. |
| `rtengine/dcrop.cc` — `Crop::fullUpdate()`와 결과 통지 | 조정기와 공유하는 `params` 읽기·임시 변경의 보호를 맞추고 해당 계산의 편집·뷰 세대를 결과에 붙인다. 조정기와 Crop 사이의 경쟁 및 잘못된 완료 보고를 막기 위한 변경만 허용한다. |
| `rtengine/rtengine.h` 등 기존 리스너 선언부 | Navigator·Crop 프레임 통지에 세대를 전달하는 최소 확장. 기존 구현체가 계속 동작할 기본 동작 또는 내부 확장을 택한다. 세대 미제공 결과는 최신 완료로 간주하지 않는다. |

기존 `mProcessing → mTweak` 잠금 순서를 유지한다. `paramsUpdateMutex`를 포함한 획득·해제 순서와 콜백 경계를 단계 1에서 확정하며, 잠금 중 예외나 종료로 해제가 누락되지 않게 한다. `endUpdateParams()` 후 반환 포인터를 비동기 작업에 보관하지 않고 값과 세대를 소유 복사한다.

`ProcParams` 밖에 revision·뷰 세대·큐·캐시를 둔다. `rtengine/improcfun.cc`의 처리식·순서, RAW 처리, 캐시 구조는 변경 목표가 아니다. `EvExpComp → HDR`의 기존 무효화 범위를 유지하며 `MINUPDATE`를 다른 이벤트와 결합하지 않는다. 요청마다 `stopProcessing()`을 호출하거나 실행 중 계산을 강제 중단하지 않는다. 실행 중 `ProcessingJob`의 변형·재사용·destroy, 소비된 job의 재사용, 무보호 파라미터·이미지 버퍼 교환은 금지한다.

## 4. PPVERSION 판정 — 기준 문서 §6

**이번 범위는 PPVERSION 미증가로 가능한 설계다. 단, 회귀 증거가 있어야 최종 확정한다.** 기존 키의 기존 값을 기존 GUI 이벤트로 전달하고, IPC·수명·동기화·세대 통지는 런타임 상태로만 추가한다. 기준 문서의 `1045`를 유지할 수 있는 전제는 다음과 같다.

- 기존 `.arp`의 그룹·키·타입·단위·기본값·열거값 해석과 저장·재로드 결과가 유지된다. 새 런타임 상태가 직렬화되지 않는다.
- 같은 초기 상태에서 수동 GUI 설정과 외부 설정의 도구 활성 상태, 다른 노출 필드, 히스토리·저장 프로필과 처리 효과가 일치한다.
- 같은 RAW·프로필의 변경 전후 GUI/CLI 최종 출력 의미가 유지되고, BatchQueue와 실행 중 내보내기의 값 고정도 유지된다.
- 잠금·스케줄링·통지 변경으로 재계산 누락이나 처리 순서 변경이 생기지 않는다. 비교할 이미지 허용 오차는 실행 전에 기록하며 의미 변경을 오차로 면책하지 않는다.

증거에는 비교 기준 커밋, macOS·빌드 구성, RAW·프로필, 비교 방법·사전 허용 오차와 결과를 남긴다. 증거가 없으면 미증가 판정을 완료하지 않는다. `.arp` 해석·기본값이나 처리식·순서·기존 도구 결과를 바꿔야 한다면 이번 예외로 진행하지 않고 별도 설계로 돌린다. 그 경우 `rtgui/ppversion.h` 증가, 저장·로드·기존 프로필 호환 정책과 `docs/arp_schema.md` 갱신이 필요하다. `protocolVersion`은 이 판정과 독립적이다.

## 5. 구현 전 규칙 갱신 — 기준 문서 §9

현재 worktree의 `AGENTS.md`에는 코어 수정 금지 문안이 남아 있다. **두 번째 커밋에서 기존 금지 항목을 아래 §9 문안으로 교체한 뒤에만 코어 구현을 시작한다.** 기존 명시 파일의 `main-cli.cc` 처리 예외도 유지한다. 이 문서 작성에서는 `AGENTS.md`를 수정하지 않는다.

> **파이프라인 기능을 위한 `rtengine/`·`rtgui/` 수정은 원칙적으로 금지한다. 다만 실행 중 GUI의 로컬 IPC 파라미터 조정에 한해, 승인된 설계와 검증 계획에 따라 조건부로 허용한다.**
>
> 허용 조건: 대상 기능, 허용 파라미터, 지원 OS·편집 모드, 변경 예정 지점, PPVERSION 판정, GUI/CLI 회귀 항목을 착수 전에 기록한다. 외부 입력 검증, GUI 메인루프 전달, 편집 대상과 revision 검사, 종료 시 수명 관리를 갖춘다. 초기 상태는 기능 비활성화로 한다.
>
> 허용 범위: `rtgui/`의 로컬 수신, GUI 명령 처리, 패널·히스토리·저장 상태 동기화, 편집기 열기·닫기 관리와 필요한 GUI 빌드 등록. `rtengine/`은 기존 단계의 안전한 파라미터 전달, 확인된 공유 상태의 동기화, 세대 번호를 포함한 프레임 통지에 필요한 최소 변경으로 한정한다. 기존 명시 파일에 대한 `main-cli.cc` 처리 예외는 유지한다.
>
> 유지하는 금지 사항: 실행 중 `ProcessingJob` 수정·재사용·destroy, 무보호 파라미터/이미지 버퍼 교환, `MINUPDATE`와 다른 이벤트 결합, 미검증 무효화 범위 축소, 헤드리스 상주화, 미인증 외부 네트워크 공개, vendored 코드 정리를 이 예외에 포함하지 않는다. 처리식·처리 순서·프로필 형식을 바꾸려면 이 예외를 확대 해석하지 않고 별도 설계와 PPVERSION 판정을 수행한다.
>
> 검증 절차: GUI·CLI 아웃오브소스 빌드, 기존 프로필 로드/저장/렌더 회귀, 수동 GUI 조작과 일치, 연속 요청·GUI 충돌·팬/줌·닫기/종료를 포함한 스레드/메모리 검사, 세대·오류 계약, 대상 OS의 화면 반영을 확인하고 결과를 기록한다. 하나라도 미검증이면 지원 범위를 한정하고 통과를 추측하여 보고하지 않는다. 공통 엔진 변경은 GUI와 CLI 양쪽의 회귀 결과를 필요로 한다.

같은 커밋에서 PPVERSION 규칙에 §6의 해석을 함께 기재한다.

> PPVERSION의 도구 동작은 저장된 프로필의 해석·기본값·영상 처리 의미를 말한다. 이를 보존하는 IPC 전송·수명·동기화 변경은 회귀 검증 근거를 남겨 증가를 생략할 수 있다.

이는 형식·도구 의미 변경 시 증가 의무를 완화하지 않는다. 네트워크 노출도 이번 범위에서는 인증 여부와 관계없이 제외한다.

## 6. 이번 범위의 필수 검증 — 기준 문서 §8 선별

아래는 단일 키·macOS·기본 OFF에 필요한 검증만 재구성한 것이다. 각 결과에 대상 OS, 빌드 구성, 사용 이미지·프로필·설정과 관찰 결과를 기록한다. 기존 수동 하네스만으로 충분하다고 가정하지 않고 입력, GUI 적용, 결과 통지 경계의 재현 검사를 마련한다.

| ID·원문 항목 | 이번 범위의 절차와 통과 조건 | 선별 이유 |
|---|---|---|
| V1 — 계약·입력 | 정상값·`-12`/`12`·범위 밖·비유한값·문자열 숫자·잘못된 타입·중복 JSON 키·알 수 없는 필드/키·버전/연산·과대 프레임·미인증을 확인한다. 단일 키와 오류 형식이 계약과 맞고, 거부 시 GUI 값·revision·히스토리가 불변이어야 한다. 도구 비활성 상태를 임의로 켜지 않는다. | 한 키만 허용해도 외부 입력이 편집 상태를 잘못 바꾸는 경로를 차단해야 한다. |
| V2 — 수동 조작과 일치 | 같은 초기 상태에서 수동/외부 노출 설정 후 컨트롤, 도구 활성 상태, 파라미터, 히스토리, 저장 프로필·재읽기, 미리보기를 비교한다. `0.05`의 배수가 아닌 범위 내 값도 확인한다. 다른 노출 필드는 보존되고, 성공한 변경당 이벤트·revision은 한 번이어야 한다. | `Exposure.Compensation`만 바뀌고 기존 GUI 편집 의미가 유지됨을 입증해야 한다. |
| V3 — 동시 조작·수명 | 연속 요청 중 `BUSY`, GUI 조작·히스토리 이동과의 충돌, 팬·줌·100% 상세 창, spot 모드의 거부, 이미지 전환·닫기·재열기·재연결·종료 중 요청을 반복한다. 다른 대상 적용, 오래된 ID 수락, 잘못된 완료 보고, 충돌·교착이 없어야 한다. | 키 수와 무관하게 비동기 명령이 대상 수명을 넘거나 GUI 편집을 덮어쓰는 위험이 남는다. |
| V4 — 스레드·메모리 | macOS GUI에 적용 가능한 ThreadSanitizer와 AddressSanitizer의 별도 구성으로 V3 및 프레임 통지를 반복한다. `params` 복사/Crop, 실행 플래그, `tweakOperator`의 미검증 경쟁을 남기지 않는다. 수신 중단 → GUI 대기 요청 무효화 → 처리 대기 → 리스너/편집 대상 해제를 확인한다. | 코어 최소 변경의 필요성과 외부 요청 빈도에서의 안전성을 직접 확인해야 한다. |
| V5 — 세대·흐름 제어 | `APPLIED/PENDING` 이후 같은 편집·뷰 세대의 Navigator와 주 Crop이 모두 준비돼야 `READY`다. GUI 편집의 `SUPERSEDED`, 렌더 실패의 `FAILED`, 세대 불명의 `null`도 확인한다. 큐/캐시 포화, 동일 ID 재전송·내용 충돌, 값이 같은 성공 요청, 타임아웃 후 조회, 완료 후 5분 보관·1024건 상한·미완료 무만료·`UNKNOWN`을 확인한다. | 단일 요청 제한에서도 중복 반영과 이전 프레임의 완료 오인이 발생할 수 있다. |
| V6 — 저장·CLI 회귀 | 기존 `.arp` 로드/저장, GUI 저장·재읽기, 같은 프로필의 변경 전후 ART-cli 출력, BatchQueue·실행 중 내보내기의 값 고정을 비교한다. 사전 허용 오차와 비교 결과로 PPVERSION 판정을 뒷받침한다. | 공유 엔진의 동기화·리스너 변경과 PPVERSION 미증가에는 GUI/CLI 양쪽의 의미 보존 증거가 필요하다. |
| V7 — OS·시작 방식 중 macOS·기본 OFF | 일반/단독 편집 시작, 인스턴스별 소켓·실행 ID 분리와 연결 권한을 확인한다. 환경변수 미설정·빈 값·`1` 이외에는 소켓·수신 스레드·큐가 없어야 하며, `1`일 때만 실행 중 GUI의 열린 편집기에 연결된다. 종료 뒤 별도 상주 프로세스가 남지 않아야 한다. | 이번 지원 선언과 기본 비활성화를 실제 시작·종료 동작으로 입증해야 한다. |

§8의 Windows/Linux 실행 검증과 지원 선언은 제외한다. 지연 항목의 최초/캐시 후·축소/100%·HDR/노이즈 제거 조합별 p50/p95 및 응답 목표 검증은 이번 최소 범위의 완료 조건에서 제외한다. 기능 확인에는 RAW 1~2장을 사용하고 고정 fps나 지연 보장을 제시하지 않는다. 안전성·화면 반영이 미검증이면 해당 지원을 선언하지 않고 기능은 비활성 상태로 둔다.

## 7. 커밋·구현·검증을 합친 작업 순서

커밋은 정확히 세 개로 분리한다. 아래 단계 1~4의 변경은 세 번째 구현 커밋 안에서 순서대로 진행하고, 각 단계의 검증을 다음 단계의 진입 조건으로 삼는다. 아직 없는 수신부나 완료 통지를 앞 단계의 완료 증거로 요구하지 않는다.

1. **커밋 1 — 본 플랜 문서 추가.**

   대상은 `docs/ART_live_param_impl_plan.md` 하나다. 최소 범위·계약·파일 역할·규칙 인용·검증·빌드 절차가 기준 문서와 맞는지 확인하고 문서 차이만 커밋한다. 제목 후보: `docs: 실시간 노출 조정 최소 구현 플랜 추가`.

2. **커밋 2 — `AGENTS.md` 조건부 허용 규칙 갱신.**

   본 플랜 §5에 인용한 기준 문서 §9의 문안과 §6의 PPVERSION 해석을 반영한다. 대상 기능·한 키·macOS·편집 모드·변경 예정 지점·PPVERSION 조건·GUI/CLI 회귀 계획이 착수 전에 기록됐는지 확인한다. 규칙 갱신 커밋이 완료되기 전에는 `rtgui/`·`rtengine/`을 수정하지 않는다. 제목 후보: `docs: GUI 로컬 파라미터 조정의 코어 수정 조건 명시`.

3. **§5 단계 1 — 스레드 경계와 지원 상태 확정.**

   선행 조건은 커밋 2다. 변경 전 비교 기준과 프로필·출력을 확보하고 아래 빌드 명령으로 GUI·CLI 기준 빌드를 남긴다. `params` 복사 위치, Crop 읽기·임시 변경, `getParams()`, 실행·정지 플래그의 보호 범위를 정리한다. `mProcessing → mTweak`를 유지하면서 필요한 공유 상태 보호만 수정한다. 일반 편집 허용과 `TweakOperator`·초기화·종료 중 `BUSY` 조건을 확정한다.

   완료 조건: 잠금·수명 경계가 기록되고 GUI 조작·팬/줌·종료의 V3/V4 재현에서 확인된 경쟁·교착을 해소한다. 기능은 OFF로 유지하며 외부 요청 빈도에서의 최종 검증은 단계 3~4 뒤 반복한다. 이 단계의 동기화 변경을 별도 수정 단위로 분리하되, 커밋 수는 늘리지 않는다.

4. **§5 단계 2 — GUI 내 명령 하나 완성.**

   선행 조건은 단계 1이다. GUI 메인루프에서 현재 패널 값의 소유 복사본을 만들고 `expcomp`만 바꾼다. 검증을 변경 전에 끝내고, 리스너를 차단한 컨트롤 갱신 후 기존 노출 이벤트 경로를 한 번 실행한다. 엔진 값만 바꾸거나 기본값 전체 프로필로 덮어쓰지 않는다.

   완료 조건: 전송 없이 GUI 명령 경계에서 V1의 키·값·도구 검증과 V2를 통과한다. 다른 노출 필드·활성 상태·히스토리·저장 의미가 보존돼야 한다. 실제 응답과 revision 추적의 통합 검증은 단계 4에서 마친다.

5. **§5 단계 3 — 로컬 서버와 편집기 식별 연결.**

   선행 조건은 단계 2다. 환경변수 OFF 검사 → 사용자 전용 Unix socket·연결 인증 → 소유된 유한 큐 → `IdleRegister` 등 GUI 전달 → GUI 레지스트리에서 대상 재확인의 경로를 연결한다. 두 GUI 기동 분기, 인스턴스 분리, `open()`의 새 ID와 `close()`의 무효화를 구현한다. `baseRevision` 검사 위치와 캐시 예약은 GUI 콜백에 둔다. 종료는 수신 중단부터 시작하며 이미 닫힌 대상의 대기 명령을 적용하지 않는다.

   완료 조건: V1의 전송·인증 부분과 V7, V3/V4의 연결·닫기·종료 경계를 통과한다. 세대 통지 전에는 미리보기 완료를 추정하지 않는다. 외부 요청을 포함한 경쟁 검증이 끝나기 전 실사용 활성화를 선언하지 않는다.

6. **§5 단계 4 — 세대와 완료 응답 연결.**

   선행 조건은 단계 3이다. 모든 편집의 revision과 팬·줌의 viewRevision을 조정기 스냅샷부터 Navigator·주 Crop·GUI 전달까지 운반한다. 비교·반영·revision 발급·캐시 등록을 GUI 직렬 경로로 완성한다. `setProgressState(false)`만으로 완료를 판정하지 않는다. `APPLIED`, `READY`, `SUPERSEDED`, `FAILED`, 재전송·만료·포화 규칙을 연결한다.

   완료 조건: V5와 V3/V4의 전체 외부 요청 경로를 통과한다. 처리 중 외부 변경은 편집기당 하나만 허용하고, 오래된 편집·뷰 세대의 결과를 최신 완료로 보고하지 않는다.

7. **검증 빌드·회귀 후 커밋 3 — 구현 확정.**

   선행 조건은 단계 1~4다. 저장소 루트에서 아래 명령으로 `build/`에 아웃오브소스 빌드를 수행한다. in-source 빌드는 금지한다. `CFLAGS`, `CXXFLAGS`, CMake 캐시와 실제 컴파일 명령 어디에도 `-ffast-math`가 없어야 한다. GUI 타깃은 `art`, CLI 타깃은 `art-cli`이며 GUI 검증을 CLI 빌드로 대신하지 않는다.

   ```bash
   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build --parallel 4 --target art
   cmake --build build --parallel 4 --target art-cli
   ```

   V4는 ThreadSanitizer와 AddressSanitizer를 섞지 않고 별도 디렉터리에서 구성한다. 적용 가능한 macOS 도구 체인과 종속 라이브러리 조합을 기록한 뒤 각 GUI 실행으로 검사한다.

   ```bash
   cmake -S . -B build/tsan -DCMAKE_BUILD_TYPE=Debug \
     -DCMAKE_C_FLAGS="-fsanitize=thread -fno-omit-frame-pointer" \
     -DCMAKE_CXX_FLAGS="-fsanitize=thread -fno-omit-frame-pointer" \
     -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=thread" \
     -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=thread"
   cmake --build build/tsan --parallel 4 --target art

   cmake -S . -B build/asan -DCMAKE_BUILD_TYPE=Debug \
     -DCMAKE_C_FLAGS="-fsanitize=address -fno-omit-frame-pointer" \
     -DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer" \
     -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address" \
     -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address"
   cmake --build build/asan --parallel 4 --target art
   ```

   구성·실행할 수 없는 검사는 미검증으로 기록하고 통과로 취급하지 않는다.

   V1~V7을 수행해 결과를 기록하고 §4의 증거에 따라 PPVERSION을 최종 판정한다. 대상은 본 플랜의 `rtgui/`·`rtengine/` 필요 변경과 GUI 빌드 등록, 필요한 검사다. 처리 의미 변경이 필요하면 별도 설계로 돌리고 버전 증가만으로 이번 범위에 포함하지 않는다. 제목 후보: `feat: macOS GUI에 단일 노출 파라미터 조정 연결`.

## 8. 후속 범위

- `Exposure.Compensation` 밖의 키 확장. 채도·WB 등은 각 키의 결합 규칙·무효화 비용·회귀를 따로 검증한 뒤 판단한다.
- Windows/Linux 지원과 다른 전송 수단.
- 네트워크 노출. 이번 로컬 전용 계약의 확대 해석으로 추가하지 않는다.

헤드리스 상주 데몬, 실행 중 job의 변형·재사용, 미검증 무효화 축소는 후속 확장 목록에도 포함하지 않고 금지를 유지한다.
