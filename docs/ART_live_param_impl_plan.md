# 실행 중 ART의 단일 노출 파라미터 조정 구현·보수 플랜

- 보수 기준 구현: `98dad107e771118306cf03253bbba649216aeafc`.
- 현재 판정: 보수 2·3의 구현과 단계 검증을 진행했다. 프레임 세대 연결과 전체 출력 회귀는 남아 있다. 제한된 검증 통과를 전체 기능 완료와 구분하며 실제 결과는 §13~14에 기록한다.
- 문서 구성: §1~6은 유지할 범위·계약·규칙, §7은 최초 구현 순서의 기록, §9~12는 보수 작업 순서와 완료 조건, §13~14는 후속 구현의 실행 기록이다.

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

보수 플랜 수립 당시 산출물은 이 문서의 갱신이었다. 규칙 갱신과 최초 구현의 커밋 이력은 §7에 구분하고, 이후 진행한 보수 코드 변경·신규 검사·빌드·실행 검증은 §13에 별도 기록한다.

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

GUI 콜백 안에서 입력·대상·revision 검증을 끝낸 다음 컨트롤·편집 상태·`nextParams`를 함께 갱신한다. 성공 응답의 공통 필드는 `protocolVersion`, `requestId`, `sessionId`, `editorId`, `status`, `result`이며, 실패에는 `result` 대신 `error`만 둔다. 편집기 목록 조회(`editorId`를 생략한 `get_state`)나 대상 확정 전 오류에서는 최상위 `editorId`를 `null`로 두고, 대상 편집기가 지정된 요청·응답에서는 해당 문자열을 반환한다.

| 응답·조회 필드 | 의미와 판정 |
|---|---|
| `status: APPLIED` | GUI 반영 완료. 파일 저장이나 미리보기 완료를 뜻하지 않는다. `result`에 `appliedRevision`, `viewRevision`, `effectiveParams`, `previewStatus`, `renderedRevision`, `renderedViewRevision`, `ppVersion`을 반환한다. 최초 미리보기 상태는 `PENDING`이다. |
| `status: OK` | `get_state` 성공. `editorId` 생략 시 `result.editors`(`{"editorId", "name"}` 배열)를 반환한다. `editorId` 지정 시 현재 `revision`, `viewRevision`, `renderedRevision`, `renderedViewRevision`, `supportedParams`, `lastMutation`, `ppVersion`을 조회한다. |
| `supportedParams` | 단일 편집기 `get_state`의 허용 키·범위·활성·현재 값 객체다. 이번 범위에서는 `{"Exposure.Compensation": {"min": -12.0, "max": 12.0, "enabled": <bool>, "value": <number>}}`로 고정한다. |
| `lastMutation` | `requestId`, `appliedRevision`, `previewStatus`를 포함한다(변경 이력이 없으면 `null`). 선택 문자열 `mutationRequestId`를 지정하면 캐시에 남은 해당 변경의 `lastMutation`과 `mutationStatus`(해당 변경의 `previewStatus` 값)를 함께 반환한다. 조회 자체의 `requestId`와 구분한다. |
| `previewStatus: READY` | 해당 적용 `revision`과 현재 `viewRevision`에 대해 유효성이 확인된 Navigator·주 표시 Crop의 표시 자료가 모두 GUI에 준비됨. Navigator를 새로 계산해야 하는 경우에는 해당 계산 결과의 GUI 전달까지 기다리고, 재사용은 아래 조건을 모두 충족한 경우에만 허용한다. 실제 모니터 그리기, 별도 상세 창, Before/After 보조 뷰, 전체 해상도 출력 완료는 포함하지 않는다. |
| `SUPERSEDED`, `FAILED` | 후속 편집에 대체된 미완료 요청, 반영 후 실제 프레임 생성이 중단된 렌더 실패를 각각 보고한다. 비치명적 경고 후 정상 프레임이 도착하는 경우는 `FAILED`로 처리하지 않으며, 렌더 실패로 반영한 값을 취소하지 않는다. |
| `renderedRevision`, `renderedViewRevision` | 정수 또는 `null`. Navigator·주 Crop 모두에 대해 표시 준비가 확인된 편집·뷰 세대 쌍을 기록한다. Navigator 재사용 시에도 원래 계산 세대와 현재 뷰에 대한 유효성 확인 기록을 보존한다. 세대가 불명확하면 완료를 추정하지 않고 `null`을 사용한다. |
| 캐시에 없는 변경 조회 | `lastMutation: null`, `mutationStatus: UNKNOWN`. 성공·실패를 추측하지 않는다. |
| `ppVersion` | 실제 프로필 버전 진단값이다. 기준 문서의 값은 `1045`이며 유지 여부는 아래 회귀 판정에 따른다. |

### Navigator 재사용과 갱신 조건

- 같은 편집기·편집 `revision`의 Navigator 표시 자료가 이미 GUI에 있고, 뷰 변경으로 Navigator의 입력·처리 품질·색 변환이 바뀌지 않으며 필요한 Navigator 재계산도 남아 있지 않은 경우에만 재사용한다. 일반 팬·줌이라는 동작 이름만으로 이 조건을 충족했다고 간주하지 않는다.
- 재사용 시 원래 프레임의 계산 세대를 바꾸지 않고 현재 `viewRevision`에도 유효하다는 확인을 별도로 기록한다. 이 확인과 같은 편집·뷰 세대의 주 Crop 준비를 묶어 기준 문서 §7.2의 완료 조건을 충족한다. 유효성을 입증하지 못하면 `PENDING`을 유지하고 기존 Navigator 갱신 경로로 결과를 확보한다.
- 주 뷰 `setZoom`의 100% 경계나 100% 상세 창 최초 추가(`ImageArea::addCropWindow`)가 부르는 `M_HIGHQUAL`, 색 관리 툴바(`EvMonitorTransform`), 샤프닝 마스크(`EvShrEnabled`), `refreshPreview()` 등 Navigator를 재계산하는 경로는 `setZoom` 지연 타이머가 대기 중이거나 `ImProcCoordinator`에 Navigator 갱신 패스(`endUpdateParams`·`startProcessing`)가 예약된 시점에 기존 준비 상태의 재사용을 차단한다. 편집·뷰 세대와 별도로 필요한 Navigator 계산 세대를 내부에서 추적하고 실제 결과가 GUI에 전달될 때까지 기다린다. 같은 편집 `revision`의 예전 Navigator와 새 Crop만으로 `READY`를 선언하지 않는다.
- 계산 세대와 재사용 유효성 기록은 `ProcParams` 밖의 일시 상태이며 새 IPC 필드로 노출하지 않는다. 이전 준비 결과를 보관하더라도 현재 요구를 충족한 결과로 보고하지 않는다.

### 충돌·재전송·오류

`revision`은 GUI 메인루프에서 편집 상태와 새 엔진 파라미터 스냅샷을 확정할 때 단조 증가시킨다. 외부 변경뿐 아니라 마우스 조작, 히스토리 이동, 프로필 변경, Spot WB·자동 크롭 등 독립적인 편집 상태 변경과 처리 결과의 자동값 반영도 같은 관리에 포함한다. 비교 → GUI 갱신 → revision 발급을 같은 콜백에서 수행한다. 같은 값을 성공적으로 설정해도 한 번 증가한다. 팬·줌은 별도 `viewRevision`으로 구분한다.

엔진이 `ToolPanelCoordinator::initImage`에 등록된 리스너로 통지하여 패널·프로필 저장값을 바꿀 수 있는 파생 자동 계산 콜백(`autoMatchedToneCurveChanged`, `logEncodingChanged`, `autoDeconvRadiusChanged`, `WBChanged`, `Crop::update`를 포함한 `chromaChanged`, `filmRefValuesChanged`, `flatFieldAutoClipValueChanged`, Bayer/X-Trans `autoContrastChanged`; 열기 수명 보호 대상인 `FrameCountChanged`·`imageTypeChanged` 포함)은 표시 전용으로 단정하지 않는다. 이미 확정한 편집의 계산 결과를 동기화하는 경우에만 해당 편집 `revision`에 귀속시켜 별도 revision 증가·변경 이벤트·재계산 예약 없이 위젯과 해당 세대의 `nextParams` 대응 필드에 함께 반영한다. 콜백 이름이나 새 스냅샷 예약이 없다는 사실만으로 이 예외를 적용하지 않는다. 독립적인 새 편집 상태 변경은 공통 변경 확정 경로에서 revision을 발급한다.

파생 콜백의 값에는 실제 계산 스냅샷의 `revision`과 해당 열기의 `sessionId`·`editorId`를 묶는다. 같은 revision 안에서 계산이 대체될 수 있으면(`M_HIGHQUAL` 재처리나 팬·줌 `Crop::update`의 `chromaChanged` 등) 처리 세대도 함께 추적한다. GUI는 패널·위젯·공유 중간값·`nextParams`를 변경하기 전에 현재 대상·revision 및 필요한 처리 세대를 검사하고, 구세대이거나 출처가 불명확한 결과는 폐기한다. 새 편집 뒤 도착한 이전 계산 결과가 값·히스토리·저장 상태나 현재 요청의 완료 상태를 바꾸게 해서는 안 된다.

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

아래는 기준 문서 §2·§5·§9에 근거한 최초 구현의 목표 역할이다. 관련 선언부 변경도 같은 역할로 한정한다. 수신부와 명령 처리 파일은 기준 구현에 이미 추가됐으며, 현재 코드의 결함과 보수 대상은 §9~10에서 구체화한다.

### rtgui 중심 변경

| 파일 | 역할·변경 목표 | 단계 |
|---|---|---|
| `rtgui/liveparamserver.h`, `rtgui/liveparamserver.cc` 최초 추가 | Unix socket 생성·인스턴스 분리·연결 인증·프레임 파싱·크기 제한·유한 큐·응답 송신. 소유한 명령 복사본만 전달한다. GTK·조정기·`ProcessingJob`에 접근하거나 raw `EditorPanel*`을 보관하지 않는다. | 3 |
| `rtgui/liveparamcontroller.h`, `rtgui/liveparamcontroller.cc` 최초 추가 | GUI 메인루프의 명령 처리, GUI 소유 편집기 레지스트리, ID·revision 검사, 응답 캐시, 상태 복사본과 완료 상태 관리. `IdleRegister` 패턴으로 전달하고 무효화 가능한 수명을 사용한다. | 2~4 |
| `rtgui/main.cc` | 공통 GUI 수명에 활성화 조건과 서버 소유권을 연결한다. 두 기동 분기에서 OFF 검사를 서버 생성 전에 수행한다. GUI 종료 시 수신 중단을 먼저 시작한다. | 3 |
| `rtgui/editorpanel.cc` | `open()`마다 새 `editorId`를 등록한다. `close()` 시작 시 대상과 대기 명령을 무효화하고 처리·리스너 해제를 정렬하며, 이전 렌더 진행 중 닫기·저장·큐 등록에서도 확정된 최신 파라미터 스냅샷을 보존해 기존 저장 정책을 유지한다. | 2~4 |
| `rtgui/toolpanelcoord.cc` | `applyExternalPatch` 성격의 GUI 진입점. 패널 현재 값의 복사본에서 `expcomp`만 변경하고, 컨트롤 동기화 후 `panelChanged(EvExpComp, ...)`와 동등한 경로를 정확히 한 번 수행한다. GUI 편집·히스토리·프로필·스냅샷 갱신형 자동 동작의 revision 경계와 §2 파생 자동 계산 리스너들의 단일 소유 복사본·세대 검증 게이트를 연결한다. | 2·4 |
| `rtgui/exposure.cc` | 필요할 때만 패널 접근부를 최소 보완한다. `Exposure::read()`처럼 리스너를 차단한 컨트롤 갱신을 재사용한다. 다른 노출 필드와 도구 활성 상태를 보존한다. | 2 |
| `rtgui/tonecurve.cc`, `rtgui/logencoding.cc` 및 파생 자동 계산 수신 패널(`sharpening.cc`, `whitebalance.cc`, `denoise.cc`, `filmnegative.cc`, `flatfield.cc`, `bayerprocess.cc`, `xtransprocess.cc`) | 워커 스레드의 공유 중간값 쓰기(`nextToneCurve`)와 직접 GTK 위젯 변경(`logEncodingChanged`)을 제거하고, `ToolPanelCoordinator`의 세대 검사를 통과한 소유 복사본만 GUI 메인루프에서 동기 반영하도록 최소 보완한다. 처리식이나 외부 조정 허용 키는 바꾸지 않는다. | 2 |
| `rtgui/previewhandler.cc`, `rtgui/crophandler.cc`, `rtgui/imagearea.cc` | Navigator 결과의 편집 세대와 주 `iareapanel` Crop 결과의 편집·뷰 세대를 GUI 전달까지 보존해 집계한다. 지연 생성되는 `mainCropWindow`도 같은 주 표시 경로에 연결하며, 오래된 결과나 진행률 종료로 `READY`를 추정하지 않는다. | 4 |
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

## 5. 코어 수정 규칙과 선행 커밋 — 기준 문서 §9

최초 플랜 작성 당시에는 `AGENTS.md`에 코어 수정 금지 문안이 남아 있었다. 이후 `cc9f8dbe3`에서 아래 §9의 조건부 허용 문안과 §6의 PPVERSION 해석이 반영됐고, 구현 커밋 `98dad107e`에 선행한다. 보수 착수 전에도 이 조건이 유지되는지 확인하며, 이번 보수를 위해 예외를 확대하거나 규칙 갱신 커밋을 반복하지 않는다. 기존 명시 파일의 `main-cli.cc` 처리 예외도 유지한다. 이 문서 갱신에서는 `AGENTS.md`를 수정하지 않는다.

> **파이프라인 기능을 위한 `rtengine/`·`rtgui/` 수정은 원칙적으로 금지한다. 다만 실행 중 GUI의 로컬 IPC 파라미터 조정에 한해, 승인된 설계와 검증 계획에 따라 조건부로 허용한다.**
>
> 허용 조건: 대상 기능, 허용 파라미터, 지원 OS·편집 모드, 변경 예정 지점, PPVERSION 판정, GUI/CLI 회귀 항목을 착수 전에 기록한다. 외부 입력 검증, GUI 메인루프 전달, 편집 대상과 revision 검사, 종료 시 수명 관리를 갖춘다. 초기 상태는 기능 비활성화로 한다.
>
> 허용 범위: `rtgui/`의 로컬 수신, GUI 명령 처리, 패널·히스토리·저장 상태 동기화, 편집기 열기·닫기 관리와 필요한 GUI 빌드 등록. `rtengine/`은 기존 단계의 안전한 파라미터 전달, 확인된 공유 상태의 동기화, 세대 번호를 포함한 프레임 통지에 필요한 최소 변경으로 한정한다. 기존 명시 파일에 대한 `main-cli.cc` 처리 예외는 유지한다.
>
> 유지하는 금지 사항: 실행 중 `ProcessingJob` 수정·재사용·destroy, 무보호 파라미터/이미지 버퍼 교환, `MINUPDATE`와 다른 이벤트 결합, 미검증 무효화 범위 축소, 헤드리스 상주화, 미인증 외부 네트워크 공개, vendored 코드 정리를 이 예외에 포함하지 않는다. 처리식·처리 순서·프로필 형식을 바꾸려면 이 예외를 확대 해석하지 않고 별도 설계와 PPVERSION 판정을 수행한다.
>
> 검증 절차: GUI·CLI 아웃오브소스 빌드, 기존 프로필 로드/저장/렌더 회귀, 수동 GUI 조작과 일치, 연속 요청·GUI 충돌·팬/줌·닫기/종료를 포함한 스레드/메모리 검사, 세대·오류 계약, 대상 OS의 화면 반영을 확인하고 결과를 기록한다. 하나라도 미검증이면 지원 범위를 한정하고 통과를 추측하여 보고하지 않는다. 공통 엔진 변경은 GUI와 CLI 양쪽의 회귀 결과를 필요로 한다.

같은 규칙 갱신 커밋에 포함된 §6의 PPVERSION 해석도 유지한다.

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
| V5 — 세대·흐름 제어 | `APPLIED/PENDING` 이후 적용 revision·최신 뷰에 유효한 Navigator와 주 Crop이 모두 준비돼야 `READY`다. Navigator 재사용의 유효성을 확인하고, `M_HIGHQUAL` 등 재계산이 필요하면 새 결과를 기다린다. 구세대 자동 계산 콜백 거부, GUI 편집의 `SUPERSEDED`, 실제 프레임 생성 중단 실패의 `FAILED`, 세대 불명의 `null`도 확인한다. 큐/캐시 포화, 동일 ID 재전송·내용 충돌, 값이 같은 성공 요청, 타임아웃 후 조회, 완료 후 5분 보관·1024건 상한·미완료 무만료·`UNKNOWN`을 확인한다. | 단일 요청 제한에서도 중복 반영과 이전 프레임의 완료 오인이 발생할 수 있다. |
| V6 — 저장·CLI 회귀 | 기존 `.arp` 로드/저장, GUI 저장·재읽기, 같은 프로필의 변경 전후 ART-cli 출력, BatchQueue·실행 중 내보내기의 값 고정을 비교한다. 사전 허용 오차와 비교 결과로 PPVERSION 판정을 뒷받침한다. | 공유 엔진의 동기화·리스너 변경과 PPVERSION 미증가에는 GUI/CLI 양쪽의 의미 보존 증거가 필요하다. |
| V7 — OS·시작 방식 중 macOS·기본 OFF | 일반/단독 편집 시작, 인스턴스별 소켓·실행 ID 분리와 연결 권한을 확인한다. 환경변수 미설정·빈 값·`1` 이외에는 소켓·수신 스레드·큐가 없어야 하며, `1`일 때만 실행 중 GUI의 열린 편집기에 연결된다. 종료 뒤 별도 상주 프로세스가 남지 않아야 한다. | 이번 지원 선언과 기본 비활성화를 실제 시작·종료 동작으로 입증해야 한다. |

§8의 Windows/Linux 실행 검증과 지원 선언은 제외한다. 지연 항목의 최초/캐시 후·축소/100%·HDR/노이즈 제거 조합별 p50/p95 및 응답 목표 검증은 이번 최소 범위의 완료 조건에서 제외한다. 기능 확인에는 RAW 1~2장을 사용하고 고정 fps나 지연 보장을 제시하지 않는다. 안전성·화면 반영이 미검증이면 해당 지원을 선언하지 않고 기능은 비활성 상태로 둔다.

## 7. 최초 커밋·구현·검증 순서의 기록

최초 플랜은 아래와 같이 세 커밋과 네 구현 단계로 나눴다. 현재 문서 추가 `df6700e39`, 규칙 갱신 `cc9f8dbe3`, 최초 구현 `98dad107e`가 존재한다. 다음 목록은 당시의 작업 순서이며, 커밋의 존재를 검증 통과로 간주하지 않는다. 이후 보수는 §10의 순서와 §12의 추가 커밋 계획을 따른다.

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

## 9. 보수 기준과 확인된 결함

설계 기준은 계속 기준 문서 §5~§9이며, 아래 코드와 이전 검토의 실행 결과는 결함을 식별하는 증거로만 사용한다. 키·OS·전송·연산·오류 코드와 응답 필드는 확장하지 않는다. 검증용 GUI 프로세스에서만 `ART_LIVE_PARAM=1`을 사용하고, 보수 완료 전에는 일반 사용과 지원 완료 선언을 보류한다.

| ID·우선순위 | 기준 구현의 문제와 확인 수준 | 보수 단계 |
|---|---|---|
| F01·P1 | `liveparamserver.cc`의 `stop()`이 클라이언트 `recv()`와 GUI 응답 대기를 해제하지 않은 채 작업자를 기다린다. 이전 서버 단독 검사에서 클라이언트를 1500 ms 뒤 닫자 `stop()`도 1500 ms 뒤 반환했다. GUI 전체 종료 검증은 별도로 필요하다. | 3 |
| F02·P1 | `liveparamcontroller.cc`의 직접 revision 증가 뒤 `applyExternalExposure()` → `panelChanged()` → `EditorPanel::procParamsChanged()`가 다시 증가시키는 경로, `getIsProcessing()`(`!can_open_now()`)을 초기화 판정에 써서 팬·줌·상세 창·일반 재계산 중 요청까지 `BUSY`로 막는 경로, 히스토리 값 열에 포맷된 수치 대신 라벨(`M("TP_EXPOSURE_EXPCOMP")`)을 넣고 `effectiveParams`에 실제 패널 반영값 대신 요청 원문을 그대로 반환하는 불일치를 코드에서 확인했다. 실제 GUI에서 응답·현재 revision·히스토리 일치와 일반 편집·팬/줌 중 수락 경계를 검증해야 한다. | 2 |
| F03·P1 | Crop 세대 갱신은 `fullUpdate()`에 있지만 일반 변경은 조정기에서 `Crop::update()`를 직접 호출한다. 또한 `EditorPanel::open()`의 첫 열기 시점에는 `mainCropWindow`가 아직 `nullptr`이고 이후 `ImageArea::on_resized()`에서 지연 생성되어 `cropHandler` 연결이 누락된다. 이 경로들의 `READY` 누락·오래된 세대 보고와 GUI 결과 병합 시 이미지·세대 불일치를 코드에서 확인했으며 실행 검사로 재현해야 한다. | 4 |
| F04·P1 | `EditorPanel::sizeChanged()`·오류 통지에서 컨트롤러를 직접 변경하고, 수신 스레드도 컨트롤러의 `sessionId`를 직접 읽는다. 파생 콜백에서도 워커 스레드의 `nextToneCurve` 무잠금 쓰기와 `logEncodingChanged`의 직접 GTK 접근이 남아 있고, 엔진 `ImProcCoordinator::process()`에는 `paramsUpdateMutex`와 `mProcessing`의 잠금 순서 역전, `hasTweakOperator()`·`is_running()`(`c->updating`) 무잠금 읽기, `getHighQualComputed()`의 빈 `crops` 언더플로 위험이 있다. 코드 경계의 위반을 확인했으며 실제 경쟁·교착 부재는 ASan/TSan 검증 대상이다. | 1·2 |
| F05·P2 | 정상적으로 이스케이프된 `requestId`로 응답 JSON 파손을 재현했다. `protocolVersion: 1.5`, JSON 뒤의 쓰레기 데이터, 잘못된 선택 필드 타입도 `get_state`에서 수락됐으며, §2의 허용 키·범위·활성 상태(`supportedParams`)·`ppVersion` 보고와 목록 조회의 최상위 `editorId` 형식도 빠져 있다. | 3 |
| F06·P2 | LF를 찾은 뒤에만 길이를 검사하므로 LF 없는 입력의 수신 버퍼가 상한 없이 증가하는 경로를 코드에서 확인했다. 실제 스트림 경계 검사는 추가해야 한다. | 3 |

이전 검토에서 `art`, `art-cli`, `test_liveparam`의 빌드는 통과했다. 이는 실제 GUI 일치·세대·경쟁 검증의 통과를 뜻하지 않는다. `test_liveparam.cc`의 노출 적용·도구 활성·편집 가능 여부는 성공 반환으로 대체되어 있고, 현재 V5 검사는 세션 불일치·대상 부재·빈 목록만 확인한다. 최초 구현 커밋 본문의 통과 표시는 재검증 대상이며 보수 완료 증거로 그대로 사용하지 않는다.

## 10. 보수 작업 순서 — 기준 문서 §5의 네 단계

다음 네 단계를 순서대로 수행한다. 단계별 대상에는 관련 선언부와 해당 검사가 포함된다. 각 결함의 검사는 수정 전에 기준 구현에서 실패 또는 불충족을 확인하고, 수정 후 같은 조건으로 다시 수행한다. 검사가 아직 없는 다음 단계의 기능을 앞 단계의 완료 증거로 삼지 않는다.

### 단계 1. 스레드 경계와 지원 상태 확정

**선행 조건:** §5의 조건부 허용 규칙이 유지되고, 기준 커밋·검증 구성·사용 RAW와 프로필이 기록돼 있어야 한다. F04를 먼저 해결하며, 다른 결함은 이후 단계 전까지 미해결 상태로 남긴다.

**작업 1-A — GUI 상태 소유권 정리.** 대상은 `rtgui/editorpanel.cc`, `rtgui/liveparamcontroller.h`, `rtgui/liveparamcontroller.cc`다.

- 편집기 등록·해제, revision·viewRevision, 요청 캐시, 완료 상태의 읽기·쓰기를 GUI 메인루프로 모은다. 처리 스레드의 크기·오류 통지는 소유한 값 복사본을 편집기 수명에 묶인 GUI 콜백으로 전달한다.
- 콜백에는 해당 이미지 열기의 식별 정보도 묶고, 실행 시 현재 `sessionId`·`editorId`와 대상을 재확인한다. 닫기·재열기 이후 이전 콜백이 새 편집기를 변경하지 못하게 한다. 계산 결과를 반영하는 콜백의 발생 revision 검사는 작업 2-B·2-C에서 연결하며, 값은 그 검사 전 공유 상태에 쓰지 않는다. 무효화된 콜백은 제거하거나 무시한다.
- OFF 상태에서는 새 외부 제어 상태를 등록·변경하지 않게 진입점을 제한한다. 기존 GUI의 크기·오류 처리 자체는 유지한다. I/O 작업자에 필요한 실행 정보는 GUI가 만든 불변 복사본으로 전달하며 작업자가 컨트롤러를 직접 조회하지 않는다.

**작업 1-B — 공유 엔진 상태 보호 확인.** 1-A 뒤에 `rtengine/improccoordinator.h`, `rtengine/improccoordinator.cc`, 필요한 `rtengine/dcrop.cc` 경계를 확인한다.

- `paramsUpdateMutex`, `mProcessing`, `mTweak`의 획득 순서와 콜백 진입점을 표로 기록한다. `ImProcCoordinator::process()`의 `paramsUpdateMutex`↔`mProcessing` 잠금 역전을 해소하여 `mProcessing → paramsUpdateMutex` 및 `mProcessing → mTweak` 단일 순서를 유지하고, GUI의 `beginUpdateParams()` 구간 안에서는 `mProcessing`을 잡지 않아 `Crop::fullUpdate()` 중에도 GUI 갱신이 막히지 않게 한다.
- `params` 복사·Crop 읽기·임시 변경(`Crop::update()`의 `parent->params.denoise` 갱신 포함), `getParams()`, `hasTweakOperator()`, `is_running()`의 `c->updating`, `getHighQualComputed()`의 빈 `crops` 경계를 포함한 실행·정지 플래그를 같은 보호 규칙으로 점검하고 확인된 경쟁·언더플로만 수정한다. 잠금을 추가한 결과 GUI를 기다리는 처리와 처리를 기다리는 GUI가 서로 막히지 않는지 확인한다. `nextParams` 포인터는 잠금 구간 밖에서 사용하지 않고, 비동기 작업에는 소유한 값 복사본만 전달한다.
- `ProcessingJob`·처리식·처리 순서·무효화 범위는 변경하지 않는다. 수신부의 실행 플래그와 연결 자원 보호는 단계 3에서 완성한다.

**완료 조건:** T01의 GUI 상태 접근 경계를 확인하고, OFF 상태의 GUI 열기·편집·팬/줌·닫기 검사와 이 단계에 해당하는 ASan/TSan 검사를 통과한다. 수신부·세대 통지의 전체 경로 검사 완료는 단계 3~4 이후로 남긴다.

### 단계 2. GUI 내 명령 하나와 변경 확정 경로 통합

**선행 조건:** 단계 1 완료. F02를 해결한다. 단순히 revision 증가문 하나를 삭제하는 수정으로 끝내지 않는다.

**작업 2-A — GUI 변경 확정 경로 통합.** 대상은 `rtgui/liveparamcontroller.h`, `rtgui/liveparamcontroller.cc`, `rtgui/toolpanelcoord.h`, `rtgui/toolpanelcoord.cc`, `rtgui/editorpanel.h`, `rtgui/editorpanel.cc`다.

- 외부 요청과 일반 GUI 조작이 같은 변경 확정 경로를 사용하게 한다. 외부 요청의 일반 변경 알림을 같은 요청에 대한 두 번째 변경이나 `SUPERSEDED`로 오인하지 않도록 콜백 범위의 변경 출처를 구분한다.
- 초기화·닫기 중 `BUSY` 검사는 팬·줌·상세 창·일반 재계산 중에도 참이 되는 `getIsProcessing()`(`!can_open_now()`)에서 분리한다. `open()`마다 리셋되고 초기 첫 프리뷰 완료 시 열리는 열기 수명 상태와 닫기·종료 중 상태를 명시적으로 관리하여(`firstProcessingDone`은 싱글탭 재열기 시 리셋되지 않으므로 그대로 쓰지 않는다), 초기 로드 완료 후에는 팬·줌이나 직전 GUI 편집 재계산 중이라도 미완료 외부 변경이 없으면 요청을 수락한다.
- 같은 GUI 콜백에서 기존 요청 ID 조회 → 입력·대상·도구·revision 검사 → 캐시 자리 예약 → 값 적용과 변경 확정을 수행한다. 미인증·미지원·충돌·`BUSY` 등 적용 전 거부는 값·revision·히스토리를 변경하지 않는다.
- 패널 현재 값의 복사본에서 `expcomp`만 바꾸고, 리스너를 차단한 컨트롤 갱신 뒤 기존 `EvExpComp` 경로를 한 번 수행한다. 성공한 요청은 같은 값이라도 revision을 한 번 증가시킨다. 히스토리 값 문자열 포맷(`Exposure::adjusterChanged`와 같은 소수 둘째 자리 포맷)과 다른 노출 필드·도구 활성 상태는 기존 수동 조작과 일치시킨다.
- `APPLIED`의 `effectiveParams`는 `Adjuster` 컨트롤(`digits = 2`, `0.01` 단위 반영)을 거쳐 실제 패널·`nextParams`에 반영된 값을 읽어 보고하며 요청 원문을 그대로 에코하지 않는다. 별도의 새 값 보정이나 `0.05` 배수 제한은 도입하지 않는다. 또한 `APPLIED` 직후 워커가 아직 이전 세대를 처리 중일 때 닫기(`saveProfile`)·즉시 내보내기·BatchQueue 등록이 실행돼도 `ipc->getParams()`가 구세대 `params`만 읽고 `stopProcessing()`이 `changeSinceLast`를 비워 반영값을 유실하지 않도록 확정된 최신 파라미터 스냅샷을 기준으로 삼는다. 적용 전 실패와 반영 후 결과 불명을 구분하며, 반영된 값을 연결 오류 때문에 되돌리지 않는다.

**작업 2-B — 파라미터와 세대의 동시 전달.** 2-A 뒤에 `rtgui/toolpanelcoord.cc`, `rtgui/editorpanel.cc`, `rtengine/rtengine.h`, `rtengine/improccoordinator.h`, `rtengine/improccoordinator.cc`, `rtengine/dcrop.cc`를 연결한다.

- 파라미터와 revision을 같은 `beginUpdateParams()`·`endUpdateParams()` 보호 구간에서 확정하고, 그 뒤 계산을 예약한다. `setNextRevisions()`와 값 갱신을 따로 잠가 서로 다른 스냅샷에 묶일 가능성을 남기지 않는다.
- 마우스 조작·히스토리 이동·프로필 변경·스냅샷 재계산을 예약하는 자동 동작도 같은 경계에서 세대를 전달하고, `refreshPreview()`·`sharpMaskSelected()`·`updateTransformPreviewRequested()`·색 관리 툴바(`EvMonitorTransform`) 등 직접 `beginUpdateParams()`를 호출하는 경로도 이전 세대나 예전 `nextParams`로 이미 수락된 파생 계산값을 덮어쓰지 않게 맞춘다. `procParamsChanged()`에서 계산 예약 후 뒤늦게 세대만 증가시키는 경로를 없애고, 세대 상태는 `ProcParams` 밖에 둔다.
- `ImProcCoordinator`와 `Crop::update()`가 발생시키는 §2의 파생 콜백에는 결과를 만든 스냅샷의 revision과 열기 식별 정보를 소유 복사본으로 전달한다. 같은 revision의 계산 대체(`M_HIGHQUAL` 재처리나 팬·줌 `Crop::update` 반복 포함)도 구분해야 하면 처리 세대를 함께 전달한다. 콜백 실행 시점의 최신 revision을 뒤늦게 붙이지 않으며, 이 정보는 프로필이나 IPC 필드에 추가하지 않는다.
- 응답 캐시는 GUI 프로세스가 소유하고 연결 종료에도 유지한다. 같은 ID·같은 내용은 재실행하지 않고 다른 내용은 수치 허용 오차로 같다고 처리하지 않는다. 미완료 항목 무만료, 완료 후 5분 보관, 전체 1024건 상한, 포화 전 거부와 `UNKNOWN` 조회를 유지한다.

**작업 2-C — 파생 계산 결과의 수락 경계.** 2-B 뒤에 `rtgui/toolpanelcoord.cc`의 리스너 전달 계층과 `rtgui/tonecurve.cc`, `rtgui/logencoding.cc`(및 필요한 동기 반영 진입점 `sharpening.cc`, `whitebalance.cc`, `denoise.cc`, `filmnegative.cc`, `flatfield.cc`, `bayerprocess.cc`, `xtransprocess.cc`) 관련 선언부를 보완한다.

- `ToolPanelCoordinator`에서 §2에 열거한 모든 파생 자동 계산 콜백을 소유 복사본과 실제 스냅샷 세대로 받아 GUI 메인루프(`IdleRegister`)에서 수락 여부를 단일 기준으로 판단하고, `ToneCurve::autoMatchedToneCurveChanged`의 워커 공유 멤버 쓰기와 `LogEncoding::logEncodingChanged`의 워커 직접 GTK 접근을 제거한다. 검증 전 공유 중간값을 덮어쓰거나, 이후 도착한 새 결과와 이전 콜백의 세대를 섞지 않는다.
- 대상·발생 revision·필요한 처리 세대가 현재 상태와 맞는 계산 결과만 해당 revision에 귀속시켜 위젯과 `nextParams`의 대응 필드에 함께 반영한다. 이 반영은 같은 외부 요청을 자체 `SUPERSEDED`로 만들거나 두 번째 노출 이벤트·revision을 발생시키지 않으며, 직후 비패널 `beginUpdateParams()` 경로(`EvMonitorTransform`, `sharpMaskSelected` 등)가 실행돼도 수락된 파생값을 유지한다.
- 수동 조작·새 외부 변경·프로필 변경 또는 닫기·재열기 뒤 도착한 구세대 결과는 폐기한다. 현재 패널·`nextParams`·히스토리·저장 대상 값·최신 요청 상태가 폐기한 콜백 때문에 바뀌지 않아야 한다. 기능 OFF 상태의 기존 GUI 자동 계산 동작도 보존한다.

**완료 조건:** 실제 GUI 진입점을 거친 T02·T03과 T13의 변경·재전송 부분을 통과한다. 기본 RAW 프로필(`histmatching` 등 자동 계산 활성 상태 포함)에서도 외부 변경 한 번에 자체 `SUPERSEDED` 없이 `APPLIED` 응답의 `result.appliedRevision`과 직후 `get_state`의 `result.revision`이 같고, 이벤트는 한 번 처리돼야 한다. 구세대 파생 콜백을 지연시켰다가 새 편집 후 도착시키는 검사도 통과해야 한다. `READY`와 후속 요청의 통합 검사는 단계 4에서 마친다.

### 단계 3. 로컬 수신부·계약·종료 수명 보수

**선행 조건:** 단계 2 완료. F01·F05·F06을 해결한다.

**작업 3-A — 입력과 응답 계약 보수.** 대상은 `rtgui/liveparamserver.h`, `rtgui/liveparamserver.cc`, `rtgui/liveparamcontroller.cc`다.

- LF 도착 전에도 미완성 프레임 길이를 제한한다. 조각난 입력과 한 번에 여러 프레임이 들어온 경우를 구분해 처리하고, 과대 프레임은 GUI 큐에 넣지 않는다. 읽기 완료 후에만 크기를 확인하는 경로를 남기지 않는다.
- GUI 큐 32개의 검사와 자리 예약을 하나의 동기화된 동작으로 묶는다. 연결별 미처리 요청 1개를 유지하고, 성공·실패·취소 모든 경로에서 예약을 정확히 한 번 해제한다.
- 기존 JSON 파서로 한 객체 전체를 소비했는지 확인한다. 정수 필드의 분수·비유한값·표현 범위를 검사한 후 변환하고, 선택 필드도 제공됐다면 타입을 검사한다. `protocolVersion: 1.5`는 `INVALID_REQUEST`, 지원하지 않는 정수 버전은 `UNSUPPORTED_VERSION`으로 거부한다.
- 성공·오류·소켓 직접 오류를 모두 기존 JSON 직렬화 기능으로 만든다. `requestId`, 편집기 이름, 오류 문자열을 직접 이어 붙이지 않는다. 따옴표·역슬래시·개행이 포함돼도 JSON 한 객체와 LF 경계를 유지한다. 새 라이브러리나 vendored 코드 수정은 추가하지 않는다.
- `get_state`의 최상위 `editorId`(`null` 또는 문자열), `supportedParams`의 허용 키·범위·활성·현재 값과 `ppVersion` 보고, 최근 요청 조회도 §2의 계약에 맞는지 확인한다. 그 밖의 연산·필드·오류 코드는 추가하지 않는다.

**작업 3-B — 종료가 가능한 수신 수명 구성.** 3-A 뒤에 `rtgui/liveparamserver.h`, `rtgui/liveparamserver.cc`, `rtgui/main.cc`, `rtgui/rtwindow.cc`, `rtgui/editorpanel.cc`를 연결한다.

- 서버 실행 상태, 연결 목록, 소켓·작업자 소유권을 동기화한다. 연결마다 취소 가능한 대기를 사용하고 종료된 작업자의 자원을 회수한다. 읽기뿐 아니라 응답 쓰기·부분 송신·연결 끊김도 정리할 수 있어야 한다.
- 두 GUI 시작 방식 모두에서 실제 창을 여는 인스턴스의 **종료가 확정된 창 수명**(`RTWindow::on_delete_event`에서 진행 중 처리 보류 검사를 통과한 시점)에 수신 중단을 연결하며, 기존 인스턴스에 인자만 전달하고 끝나는 원격 보조 프로세스에서는 수신부를 열지 않는다. `cleanup_rt()`만 기다렸다가 이미 끝난 GUI 루프에 응답 생성을 맡기지 않고, 닫기를 취소하거나 기존 정책이 종료를 보류한 경우에는 정상 사용 상태를 유지한다.
- 정리 순서는 신규 수신 중단 → GUI 대기 명령 무효화 및 소켓·응답 대기 깨우기 → I/O 작업자 정리 → 기존 처리 대기 → 리스너·편집 대상 해제다. GUI 스레드가 `join()`할 때 작업자가 GUI 콜백을 기다리는 상태를 남기지 않는다.
- 대기 명령의 콜백 등록과 취소 수명을 추적한다. 취소 시에도 대기 결과와 소유 메모리를 정리하며, 타임아웃만 추가하고 나중에 오래된 명령을 적용하는 수정은 허용하지 않는다. 이미 반영한 변경은 취소·롤백하지 않는다.
- 기본 OFF, 사용자·연결 인증, 디렉터리 `0700`·소켓 `0600`, 인스턴스 경로 분리를 재확인한다. 초기화 실패는 수신 비활성 상태로 끝내고 `stop()` 반복 호출도 안전하게 한다.

**완료 조건:** T04~T09를 통과한다. 유휴 연결과 GUI 대기 명령이 있을 때도 수신부 정리는 클라이언트의 자발적인 연결 종료에 의존하지 않아야 한다. 종료 검사의 5초 상한은 이 대기 결함을 검출하는 시험 제한이며, 일반 렌더 지연 보장은 아니다.

### 단계 4. 세대·프레임·완료 응답 연결

**선행 조건:** 단계 3 완료. F03을 해결하고 단계 1~3의 변경을 실제 요청 경로에서 재검증한다.

**작업 4-A — 엔진 결과의 세대 고정.** 대상은 `rtengine/improccoordinator.h`, `rtengine/improccoordinator.cc`, `rtengine/dcrop.h`, `rtengine/dcrop.cc`, `rtengine/rtengine.h`다.

- 작업 파라미터를 복사하는 시점의 편집 세대와 계산에 사용한 뷰 세대를 결과에 묶는다. 조정기의 직접 `Crop::update()` 호출과 `Crop::fullUpdate()` 모두 같은 원칙을 적용한다.
- Navigator 결과에는 해당 갱신 요구의 내부 계산 세대도 같은 스냅샷에서 묶어 GUI까지 운반한다. 동일한 편집 revision으로 여러 Navigator 계산을 예약해도 이전 결과와 현재 필요한 결과를 구분할 수 있어야 한다.
- 완료 시점의 최신 컨트롤러 값을 오래된 프레임에 붙이지 않는다. Crop의 반복 처리에서도 실제 파라미터·뷰포트와 결과 세대가 일치해야 한다. 실패 통지는 빈 마스크 경고 등 렌더가 계속 진행되어 정상 프레임이 도착하는 비치명적 `error()`와 실제 미리보기 프레임 생성이 중단된 실패(`updatePreviewImage` 색 변환 실패 등)를 구분하고, 실제 작업 세대를 식별할 최소 정보를 전달한다. 기존 리스너 호환 동작은 유지하되 세대 미제공을 최신 완료로 취급하지 않는다.

**작업 4-B — GUI 결과 병합과 통지.** 4-A 뒤에 `rtgui/previewhandler.h`, `rtgui/previewhandler.cc`, `rtgui/crophandler.h`, `rtgui/crophandler.cc`, `rtgui/imagearea.cc`, `rtgui/liveparamcontroller.cc`를 보완한다.

- `EditorPanel::open()` 시점뿐 아니라 `ImageArea::on_resized()`에서 `mainCropWindow`가 지연 생성될 때도 주 `iareapanel`의 `mainCropWindow`에만 완료 통지 대상을 연결한다(`beforeIarea` 보조 뷰와 `isDetailWindow == true` 상세 창은 제외한다).
- 이미지·표시 영역·세대 쌍을 같은 보호 범위의 결과로 보관한다. GUI 콜백을 합칠 때 최신 이미지 버퍼와 이전 콜백이 캡처한 세대를 섞지 않는다. 실제 표시 자료를 만들지 못한 결과로 준비 통지를 보내지 않는다.
- 같은 적용 revision·최신 뷰에 유효한 Navigator와 주 Crop의 표시 자료가 모두 준비돼야 `READY`로 보고한다. Navigator는 §2의 재사용 조건을 충족하거나 현재 요구하는 계산 세대의 새 결과여야 한다. 재계산이 필요한데 구세대 Navigator만 있거나 세대가 불명확하면 `PENDING`을 유지한다. 뒤늦은 구세대 통지가 최신 완료 상태를 덮어쓰지 못하게 한다.
- 일반 GUI 편집은 미완료 외부 요청을 `SUPERSEDED`로 전환한다. 실제 프레임 생성이 중단된 렌더 실패도 발생한 작업의 세대를 식별하여 해당 요청만 `FAILED`로 보고하고, 상세와 실제 파라미터 상태를 유지한다.

**작업 4-C — 팬·줌과 대상 수명 통합.** 4-B 뒤에 `rtgui/cropwindow.cc`, `rtgui/crophandler.cc`, `rtgui/imagearea.cc`, `rtgui/editorpanel.cc`, `rtgui/liveparamcontroller.cc`의 뷰 변경·실패 전달 경계를 연결한다.

- 실제 GUI 팬·줌(`CropHandler::setZoom`의 지연 타이머와 100% 경계 `M_HIGHQUAL` 재처리 포함)에서 `viewRevision`을 발급하고 새 뷰포트 처리에 전달한다. 엔진의 이미지 크기 통지를 팬·줌의 대용으로 사용하지 않는다. 팬·줌만으로 편집 revision이나 반영한 노출 값을 바꾸지 않는다.
- `APPLIED` 당시의 뷰 세대는 보존한다. Navigator 재사용 차단은 줌 배율 수치만의 추정이 아니라 `CropHandler::setZoom` 지연 타이머가 대기 중이거나, 주 뷰 `setZoom`·100% 상세 창 최초 추가(`ImageArea::addCropWindow`)의 `M_HIGHQUAL`·색 관리 툴바(`EvMonitorTransform`)·샤프닝 마스크(`EvShrEnabled`)·`refreshPreview()` 등으로 `ImProcCoordinator`에 Navigator 갱신 패스(`endUpdateParams`·`startProcessing`)가 실제 예약되어 완료 전인 상태를 기준으로 삼는다. 지연 타이머를 취소·대체하면 미실행 갱신 요구도 함께 정리한다. 새 Crop이 먼저 도착해도 필요한 새 Navigator가 GUI에 전달될 때까지 `PENDING`이며, 재사용이 검증된 경우에는 불필요한 Navigator 재계산을 기다리지 않는다.
- `get_state`에는 현재 뷰와 실제로 두 표시 자료의 유효성을 확인한 세대 쌍을 보고한다. 재사용한 프레임의 원래 계산 세대와 현재 뷰에 대한 검증 기록은 별도로 보존하며, 오래된 결과의 세대를 단순히 최신 값으로 교체하지 않는다. 원래 뷰의 구세대 Crop 결과로 최신 준비를 선언하거나 취소된 갱신을 기다려 다음 요청을 영구히 `BUSY`로 막지 않는다.
- 이미지 전환·탭 닫기·같은 파일 재열기에는 이전 ID·대기 명령·결과가 새 대상에 적용되지 않아야 한다. `EditorPanel`의 실패 전달도 GUI 콜백에서 실제 작업 세대와 편집기 ID를 확인한 뒤 해당 요청에 연결한다. 이미 실행 중인 내보내기와 별도 상세 창, Before/After 보조 뷰를 주 Crop의 완료 조건에 섞지 않는다.

**완료 조건:** T10~T13을 실제 GUI 경로에서 통과하고 T01~T09를 다시 확인한다. 이어 T14·T15의 저장·렌더 회귀와 스레드·메모리 검사를 통과해야 보수 전체를 완료할 수 있다.

## 11. 보수 검증과 실행 절차

### 검사 경계와 통과 조건

`rtgui/test_liveparam.cc`는 JSON·입력·수신·캐시 경계의 재현 검사를 보강한다. 실제 GUI 적용·revision·히스토리·프레임을 검사할 때는 성공 반환 대체를 사용하지 않는다. `rtgui/test_liveparam_gui.cc`와 `test_liveparam_gui` 타깃은 보수 1에서 추가됐다. 실제 `EditorPanel`·`ToolPanelCoordinator`·처리기·리스너 경로를 사용하며, 현재 구현된 검사와 남은 검사는 §13에서 구분한다. `rtgui/CMakeLists.txt`에서는 `main.cc`를 분리한 GUI 공통 객체(또는 정적) 라이브러리를 `art`와 macOS 전용 `test_liveparam_gui`가 공유하게 하여 Release·ASan·TSan에서의 중복 컴파일과 전역 심볼 충돌을 피하고, 검사 지원을 위해 제품의 새 IPC 연산이나 시작 옵션을 추가하지 않는다.

각 검사는 예상값과 실제값, 명령·종료 코드·구성·결과 자료를 함께 남긴다. 모의 응답이나 최종 성공 문구만으로 아래 단언을 대신하지 않는다. 검사 준비 실패는 통과가 아니다.

| 검사 | 반드시 확인할 결과 | 담당 단계·기존 검증 |
|---|---|---|
| T01 — GUI 상태와 OFF | 크기·오류 통지가 처리 스레드에서 도착해도 컨트롤러 변경은 GUI 콜백에서만 발생한다. OFF 상태의 열기·편집·자동 계산·팬/줌·닫기에서 기존 표시·저장 동작을 보존하고 새 수신 자원이나 상태 경쟁이 없다. | 1/2·V4/V7, F04 |
| T02 — 한 번의 외부 변경 | 기본 RAW 프로필(`M_AUTOEXP` 파생 콜백 활성 포함)에서 한 요청으로 값·노출 이벤트·revision이 한 번 반영되고, `0.05` 배수가 아닌 값(`0.03`, `0.125` 등)에서도 `effectiveParams`·패널·`nextParams`가 일치한다. 발생 세대가 맞는 파생 결과는 그 revision에 반영되고 추가 노출 이벤트·revision·자체 `SUPERSEDED`를 만들지 않는다. 후속 편집 전 `appliedRevision`과 조회 revision이 같으며, 같은 값의 새 요청도 revision은 한 번 증가하고 히스토리 값 포맷·행 동작은 기존 수동 조작과 일치한다. | 2·V2/V5, F02 |
| T03 — GUI 변경과 충돌 | 수동 조작·히스토리 이동·프로필 변경·스냅샷 갱신형 자동 동작의 세대가 실제 엔진 스냅샷과 일치한다. §2에 확정한 파생 콜백(`Crop::update`의 `chromaChanged` 포함) 종류별로 이전 결과를 지연시킨 뒤 새 편집·새 외부 변경·프로필 변경·재열기 후 도착시켜도 패널·`nextParams`·히스토리·저장 대상 값·최신 요청 상태가 불변이며, 수락된 파생값 뒤 `EvMonitorTransform`·`sharpMaskSelected` 등 비패널 `beginUpdateParams()` 경로를 실행해도 파생값이 보존된다. 같은 revision의 계산 대체도 구분하고, 오래된 기준 revision은 거부하며 `SUPERSEDED` 뒤에는 백그라운드 재계산 중이라도 새 기준 revision의 외부 변경이 수락된다. | 2/4·V3/V5, F02/F04 |
| T04 — 응답 JSON | 따옴표·역슬래시·이스케이프된 개행이 든 `requestId`와 파일 이름, 성공·오류 응답이 모두 다시 파싱되고 원래 문자열로 복원된다. `get_state`의 최상위 `editorId`와 `supportedParams`가 §2 계약과 일치하며 응답은 한 프레임을 유지한다. | 3·V1, F05 |
| T05 — 요청 전체와 타입 | `protocolVersion: 1.5`, 분수·음수·변환 범위를 벗어난 `baseRevision`, 잘못된 선택 필드 타입, 후행 쓰레기·두 번째 JSON 객체·중복 키를 거부한다. 정상 정수와 경곗값은 수락하며 거부 시 편집 상태는 불변이다. | 3·V1, F05 |
| T06 — 수신 크기 | 정상·상한·상한 초과 프레임, 조각난 전송, LF 없는 초과 입력을 시험한다. 과대 프레임은 GUI에 전달되지 않고 미완성 버퍼도 한도를 넘겨 계속 증가하지 않는다. | 3·V1, F06 |
| T07 — 큐와 연결 제한 | GUI 처리를 지연한 상태에서 동시 연결로 큐를 채워도 상한 32개를 초과 예약하지 않는다. 연결별 미처리 요청은 1개이며 포화는 `BUSY`다. 취소·오류 뒤에도 예약 수가 복구된다. | 3·V5 |
| T08 — 종료 대기 | 유휴 연결 유지, LF 없는 부분 입력, GUI 명령 대기, 응답 중 연결 끊김을 각각 시험한다. 클라이언트를 먼저 닫아 결함을 감추지 않고 수신부 정리가 5초 내 끝나는지 확인한다. 종료 후 콜백 적용·소켓·작업자가 남지 않는다. | 3·V3/V4, F01 |
| T09 — macOS 시작·인증 | 일반/단독 GUI, 원격 인자 전달 보조 프로세스 비기동, 환경변수 미설정·빈 값·`0`·`1` 이외·`1`, 인증 실패, 권한과 인스턴스 분리를 확인한다. 종료를 취소하거나 처리 중 종료가 보류된 GUI는 계속 편집·연결할 수 있다. | 3·V1/V7 |
| T10 — 첫 열기와 두 Crop 진입 경로 | 첫 이미지 열기에서 지연 생성된 `mainCropWindow`, 일반 노출 변경의 직접 `update()`, 팬·줌의 `fullUpdate()`에서 모두 실제 결과와 세대가 일치한다. `APPLIED/PENDING` → 두 화면 자료 준비 → `READY` 뒤 새 변경이 성공한다. | 4·V5, F03 |
| T11 — 지연된 GUI 결과 | GUI 전달을 지연해 여러 결과를 합쳐도 표시된 이미지와 보고 세대가 같다. 100% 경계 `M_HIGHQUAL` 재처리에서 예전 Navigator가 남은 채 새 Crop을 먼저 전달해도 `PENDING`이고, 필요한 새 계산 세대의 Navigator가 GUI에 도착한 뒤에만 `READY`다. 한쪽 결과만 도착하거나 구세대 Navigator·Crop이 뒤늦게 도착해도 최신 완료를 오인하지 않는다. | 4·V3/V5, F03 |
| T12 — 뷰·대상·실패 | 외부 변경 중 일반 팬·줌에서는 Navigator의 입력·품질·색 변환 불변과 재계산 대기 부재를 확인한 재사용만 허용하고, 원래 계산 세대와 현재 뷰의 유효성 기록을 구분한다. 재사용을 입증하지 못했거나 주 뷰 100% 경계·100% 상세 창 최초 추가(`M_HIGHQUAL`)·색 관리(`EvMonitorTransform`)·샤프닝 마스크(`EvShrEnabled`)로 Navigator 재계산이 실제 예약된 경우 새 Navigator 결과를 기다린다. 지연 타이머 대기·취소·대체 후에도 최신 뷰에서 정상 완료돼야 한다. 100% 상세 창·Before/After 뷰, spot 모드 거부, 전환·닫기·재열기·재연결을 시험하며 잘못된 대상 적용·영구 `BUSY`·완료 오인이 없어야 한다. 비치명적 경고와 실제 실패를 구분하고 해당 세대의 실제 실패만 `FAILED`이며 반영값은 취소되지 않는다. | 4·V3/V5/V7 |
| T13 — 재전송과 캐시 | 같은 ID·같은 내용은 재실행하지 않고 다른 내용은 `REQUEST_ID_CONFLICT`다. 연결 종료·재연결 후에도 유지한다. 시각을 제어하는 검사로 완료 후 5분 경계·미완료 무만료·1024건 포화·기한 후 `UNKNOWN`을 확인한다. | 2/4·V5 |
| T14 — 저장·출력 보존 | 같은 초기 상태의 수동/외부 설정, 다른 노출 필드, 저장·재로드, `APPLIED` 직후 이전 렌더 진행 중 닫기(`saveProfile`)·즉시 내보내기·BatchQueue 등록에서의 반영값 보존, 변경 전후 GUI/CLI 출력, 실행 중 내보내기의 생성 시점 값 고정을 비교한다. | 최종·V2/V6 |
| T15 — 스레드·메모리 | ASan·TSan 별도 GUI 구성에서 T01~T03·T07~T12의 해당 경로를 반복한다. 실제 요청 빈도·팬/줌·닫기·종료에서 경쟁·교착·해제 후 접근이 없어야 한다. | 최종·V4 |

계약 검사만 통과한 결과와 실제 GUI 검사 결과는 따로 기록한다. 기존 §6처럼 전체 지연 조합의 p50/p95 측정, 다른 키·OS·전송 지원은 이번 완료 조건에 추가하지 않는다.

### 빌드·실행 순서

아래는 보수 플랜 수립 당시 정한 **보수 후 검증 명령**이다. 실제 실행한 구성·결과는 §13에 기록한다. 저장소 루트에서 기존 `build/`를 사용하고 in-source 빌드와 `-ffast-math`를 금지한다. 실제 CMake 캐시·컴파일 명령에도 금지 플래그가 없는지 확인한다.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 4 --target art art-cli test_liveparam test_liveparam_gui
build/rtgui/test_liveparam
build/rtgui/test_liveparam_gui
```

GUI 검사는 사전에 기록한 RAW 1~2장과 프로필을 사용하며, `/Applications/ART.app` 번들 설치 여부에 의존하지 않도록 검사 초기화에서 저장소 `rtdata/`(언어·테마·기본 프로필) 경로와 격리된 임시 설정·캐시 디렉터리를 명시적으로 지정한다. 파일이 없거나 실제 편집기·처리기를 구성하지 못하면 실패 또는 미검증으로 기록하며 빈 편집기 목록의 성공으로 대신하지 않는다. 종료 검사에서만 쓰는 5초 제한과 렌더 완료 대기의 검사 제한은 구분한다.

ASan·TSan 구성은 §7의 `build/asan`, `build/tsan` 명령을 사용하되 각 구성에서 `art`, `art-cli`, `test_liveparam`, `test_liveparam_gui`를 빌드하고 해당 검사 실행 결과를 남긴다. 두 검사 구성을 섞지 않는다. 적용할 수 없는 구성이 있으면 원인·영향·남은 경계를 기록하고 전체 스레드 검증 통과로 보고하지 않는다.

영상 비교 기준은 §4를 따른다. 기능 추가 전 기준 `cc9f8dbe3`, 결함 재현 기준 `98dad107e`, 보수 후 커밋을 구분한다. 같은 RAW·프로필·빌드 조건과 실행 전에 정한 허용 오차로 비교하며, 기준 렌더는 독립적인 아웃오브소스 빌드에서 확보한다. 기준 빌드나 원본 출력을 확보할 수 없으면 회귀와 PPVERSION 판정은 미검증으로 남긴다. 보수 후 결과 두 번을 비교한 것으로 변경 전후 회귀를 주장하지 않는다.

검사 자료는 `build/liveparam-checks/` 아래 실행별로 모은다. 커밋, macOS 버전·아키텍처·도구 체인·빌드 플래그, RAW·프로필 해시, 사전 허용 오차, 검사별 실제값·종료 코드와 화면·히스토리·세대 기록을 남긴다. 이 경로는 예정된 실행 자료 위치이며 이번 문서 갱신에서 생성하지 않는다.

## 12. 추가 커밋과 최종 완료 조건

최초 세 커밋은 §7의 이력으로 유지한다. 이번 문서 갱신과 이후 보수는 다음과 같이 추가 분할한다. 실제 커밋·구현은 이번 문서 작성의 범위가 아니다. 각 보수 커밋에 해당 결함을 재현하는 검사와 수정 후 결과를 함께 포함한다.

| 순서 | 범위 | 국문 커밋 제목 후보 |
|---|---|---|
| 보수 플랜 | 이 문서만 갱신 | `docs: 실시간 노출 조정 결함 보수와 재검증 계획 추가` |
| 보수 1 | 단계 1의 GUI 상태 소유권·확인된 공유 상태 보호와 해당 검사 | `fix: 실시간 노출 조정의 스레드 경계 보호` |
| 보수 2 | 단계 2의 단일 변경 확정·파라미터와 revision 전달·해당 검사 | `fix: 노출 변경과 리비전 확정을 한 경로로 통합` |
| 보수 3 | 단계 3의 입력·응답·큐 제한·종료 수명과 해당 검사 | `fix: 로컬 노출 조정의 입력 계약과 종료 처리 보완` |
| 보수 4 | 단계 4의 프레임 세대·뷰 변경·완료 통지, 전체 회귀와 PPVERSION 최종 판정 | `fix: 노출 미리보기의 세대 전달과 완료 판정 보완` |

검사 소스·CMake 등록은 처음 소비하는 보수 커밋에 포함한다. 중간 커밋의 제한된 통과 결과를 전체 기능 완료로 표시하지 않고, 아직 보수하지 않은 F01~F06과 미실행 T01~T15를 명시한다.

- [ ] F01~F06이 해당 재현 검사로 해소되고 T01~T15의 실제 결과가 기록됐다.
- [ ] 기본 OFF와 두 macOS GUI 시작 방식에서 정상 편집·요청·닫기·종료가 확인됐다.
- [ ] 외부 변경 한 번에 revision이 한 번 증가하고, 화면·히스토리·저장 의미가 수동 조작과 일치한다. 자동 계산 결과의 발생 세대를 검사하고 구세대 콜백은 상태 변경 전에 폐기한다.
- [ ] `APPLIED`와 `READY`가 구분되며 프레임·뷰 세대가 일치하고, 다음 요청이 정상 진행된다. Navigator 재사용은 유효성 확인을 거치며 재계산이 필요하면 해당 새 결과의 GUI 전달까지 기다린다.
- [ ] GUI·CLI·검사 타깃 빌드, ASan·TSan의 적용 가능한 전체 경로, 기존 프로필·렌더 회귀가 확인됐다. 미검증 항목이 있으면 전체 완료로 판정하지 않는다.
- [ ] `ProcParams` 직렬화·처리 의미·기본값 보존 증거를 근거로 PPVERSION을 판정했다. 미증가를 예정만으로 확정하지 않는다. 의미 변경이 필요하면 §4에 따라 별도 설계로 돌린다.

전체 완료 체크리스트는 아직 미완료다. 개별 단계의 실행 결과는 아래 기록과 구분하며, 남은 검사를 실행하지 않고 전체 통과로 표시하지 않는다.

## 13. 보수 재개와 실행 기록 — 2026-11-03

### 재개 시 확인한 상태

- 재개 기준은 `e34389859aee4caae3d39167609b79cfbf373c0b`다. 보수 1의 스레드 경계 보호가 커밋됐으며, 보수 2의 히스토리 조회 지원과 GUI 검사 초안 네 파일이 미커밋 상태로 남아 있었다.
- 남은 초안을 보존한 뒤 검사 진입점에 T02·T03·T13을 연결하고 컴파일 오류를 수정했다. 수정 전 실제 GUI의 T02에서 초기 revision 불일치, 적용값·히스토리 불일치와 revision 중복 증가를 재현했다.
- 재개 전 변경의 사본과 실행 자료는 `build/liveparam-checks/resume/`에 보관한다. 작업 전 상태는 `inherited-state.json`·`inherited.patch`, 재현 결과는 `step2-red.log`다.

### 보수 2의 변경

| 경계 | 반영한 내용 |
|---|---|
| 변경 확정 | `ImProcCoordinator::endUpdateParams()`의 파라미터 보호 구간에서 GUI 변경 revision을 함께 확정한다. 초기 `EvPhotoLoaded`는 revision `0`이며, 이후 외부·수동·히스토리·프로필·자동 크롭 변경은 한 번만 증가한다. 처리 시작 후 `procParamsChanged()`에서 다시 증가시키던 경로를 제거했다. |
| 실제 적용값 | 외부 노출 설정은 `Exposure::adjusterChanged()`와 같은 경로로 한 번 통지한다. `0.125` 요청은 실제 컨트롤 값 `0.13`으로 응답하고 히스토리도 같은 소수 둘째 자리 형식을 사용한다. 일반 재계산 중이라는 이유만으로 요청을 거부하지 않는다. |
| 파생 계산 | 사진을 열 때마다 전용 전달 객체를 만들고 실제 계산의 `ProcessingContext`와 값 복사본을 GUI에 전달한다. 대상 수명·편집 revision·필요한 계산 세대가 맞을 때만 해당 위젯과 `nextParams`의 대응 필드를 반영한다. 계산 원래의 정밀도와 다른 필드는 보존하며 별도 변경 이벤트·revision·재계산은 만들지 않는다. |
| 수명·OFF | 같은 파생 통지 보호를 OFF 상태에도 적용하되 소켓·수신 스레드·외부 명령 큐는 생성하지 않는다. 닫을 때 전달 객체를 무효화하고 Navigator 처리를 대기한 뒤, Crop과 공유하는 처리 잠금 아래 리스너를 해제한다. 그 뒤 대기 GUI 통지를 취소하고 객체를 해제한다. |
| 저장·표시 | 저장·새 내보내기·새 큐 등록은 확정한 최신 스냅샷을 사용한다. OFF 상태는 기존 처리 완료 스냅샷 정책을 유지한다. 색 변환·샤프닝 마스크의 표시 재계산은 편집 revision을 발급하지 않고 기존 처리 예약 경로를 사용한다. 실행 중 `ProcessingJob`에는 접근하지 않는다. |
| 재전송·보관 | 요청 원래 값과 실제 적용값을 별도로 보관한다. 동일 요청 여부에 수치 허용 오차를 적용하지 않는다. 모든 편집기의 보관 건수를 합쳐 1024건을 제한하고, 만료 정리는 조회·재전송 판정 전에 수행한다. 시각을 제어하는 검사는 내부 검사 접근부를 사용하며 외부 연산·필드는 추가하지 않는다. |

### 검증 자료와 남은 범위

- macOS arm64, AppleClang, Release·별도 Debug ASan·TSan 구성에서 `art`·`art-cli`·`test_liveparam`·`test_liveparam_gui` 네 타깃을 아웃오브소스로 빌드했다. `-ffast-math`를 사용하지 않는다. 명령과 구성은 `step2-final-build.log`·`step2-asan-build.log`·`step2-tsan-build.log` 및 해당 `CMakeCache.txt`로 확인한다. 실제 플래그·소스 파일 해시는 `step2-build-meta.json`에 기록했다.
- 최신 Release의 T01·T02·T03·T13은 통과했다(`step2-release-green.log`, 종료 코드 `0`). T03의 지연된 파생값 수락·폐기 경계는 실제 편집기의 처리 리스너에 유효한 값을 주입해 검사했다. 유효한 파생값 수락, 수동·프로필·외부 변경과 같은 revision의 계산 대체 뒤 폐기, 닫기·다른 사진 재열기, 비패널 갱신 후 보존과 `APPLIED` 직후 닫기의 저장값을 확인했다. T13은 실제 GUI 변경 1024건으로 포화를 만들고 완료 후 299초·300초 및 미완료 하루 경계를 확인했다. 연결을 통한 재전송은 단계 3 이후 별도로 검증한다.
- ASan이 검사 초안의 불완전한 곡선 좌표 자료를 검출했다. 유효한 좌표 쌍으로 고친 뒤 ASan T03과 별도 실행한 T01·T02·T13이 모두 통과했으며 검사 옵션·단언은 완화하지 않았다. TSan의 T01·T02·T03·T13도 통과했고 해당 실행의 종료 코드는 `0`이며 데이터 경쟁 보고가 없었다. ASan 자료는 `step2-asan-t03-green.log`·`step2-asan-rest-green.log`, TSan 자료는 `step2-tsan-green.log`다. 수정 전 실패와 중단한 이전 실행을 통과 자료로 사용하지 않는다.
- CLI 회귀는 사전 허용 오차 `0`으로 기준 `cc9f8dbe3`의 보관 출력과 동일 RAW·프로필의 TIFF 픽셀을 비교했다. `test_profile.arp`의 `1.5`, `Auto-Matched Curve.arp`와 추가 노출 프로필의 `0.75`·`0.13` 세 건 모두 정확히 일치했다. 다른 출력끼리 비교하는 음수 대조에서 차이가 검출됨도 확인했다. 명령·종료 코드·출력 해시는 `step2-cli-regression.json`, 기준 구성·입력 해시는 `build/liveparam-checks/baseline-cc9f8dbe3/baseline-meta.json`에 기록한다. TIFF의 실행 버전·생성 시각 태그 차이는 픽셀 비교에서 제외했다.
- `PPVERSION`은 현재 `1045`를 유지한다. 이 CLI 회귀만으로 미증가 최종 판정을 완료하지 않으며, T14의 전체 GUI 저장·재로드·새 내보내기·BatchQueue·기존 출력 작업 값 고정 검증이 남아 있다.
- 보수 2 기록 시점에는 보수 3의 F01·F05·F06과 보수 4의 F03이 남아 있었다. 이어 진행한 수신·입력·종료 검사는 §14에서 구분한다. 전체 기능의 지원 완료 판정은 보류한다.

## 14. 수신·계약·종료 보수 기록 — 2026-11-04

### 변경과 재현

- 보수 2는 `1eac121e0`에 기록했다. 이어 T08에서 클라이언트를 닫지 않고 종료를 요청했을 때 5초 제한을 초과하는 F01을 재현했다(`step3-t08-red.log`, 종료 코드 `81`). T04에서는 특수문자 요청 ID의 응답을 다시 파싱할 수 없는 F05를 재현했다(`step3-json-red.log`).
- 수신부는 macOS의 비차단 Unix socket과 단일 수신 스레드로 연결을 관리한다. GUI 대기 요청의 예약·실행·취소·완료를 잠금으로 보호하며 실행 전 취소할 수 있는 GUI 소스 수명을 보관한다. GUI 대기 요청 상한은 32개, 연결당 처리 중 요청은 하나다. 관리 연결 64개의 내부 용량 제한도 포화 시 `BUSY`로 처리한다.
- 프레임의 JSON 본문 64 KiB와 LF 구분자를 처리한다. LF가 없을 때도 본문 상한을 넘는 한 바이트에서 거부하므로 미완성 입력이 계속 쌓이지 않는다. 정상 응답은 부분 송신을 처리하고 끊어진 연결의 송신으로 프로세스가 종료되지 않게 한다.
- 종료는 수신 실행 상태 무효화 → 대기 GUI 소스 취소 → 수신 스레드 정리 → 소유 소켓 해제 → GUI 레지스트리 정리 순서다. 수신 스레드는 GUI 응답을 기다리며 종료를 막지 않는다. 일반 창 닫기가 처리 중 보류되는 경우에는 이 절차를 시작하지 않는다.
- 커널 상대 자격을 읽을 수 있고 GUI 실행 사용자와 일치해야 연결을 허용한다. 사용자 디렉터리는 `lstat()`으로 디렉터리·소유자·`0700`을 확인하며 소켓은 `0600`으로 생성한다. PID·실행 세션으로 경로를 구분하고 다른 인스턴스의 기존 경로는 제거하지 않는다. 실패 시 수신을 열지 않는다.
- 응답은 기존 JSON 라이브러리의 객체·문자열·수치 직렬화를 사용한다. 목록의 최상위 `editorId: null`, 단일 상태의 `supportedParams`·`ppVersion`을 계약대로 제공한다. 요청은 UTF-8과 JSON 전체 소비, 중복 키, 원문 수치의 정수성, 선택 필드 타입을 검사한다. NUL에 의한 문자열 식별자 잘림을 거부하고, 32비트 정수로 잘라 판정하는 경로를 제거했다. 수치형 식별자는 손실 없는 비교 범위에서 처리하며 프레임·정수·타입 위반은 적용 전에 거부한다.
- `main.cc`의 공통 GUI 초기화는 macOS에서 환경변수가 정확히 `1`일 때 수신 시작점에 들어간다. `RTWindow`는 종료가 허용된 뒤 편집기 정리보다 먼저 수신부를 정리한다. 검사 타깃은 macOS로 한정했다.

### 실제 검사와 제한

- Release의 현재 구현된 T01~T09·T13이 모두 통과했다(`step3-release-all-green.log`, 종료 코드 `0`). T04~T09는 실제 Unix socket을 통해 JSON 특수문자 왕복, 음수·분수·후행 데이터·선택 필드 타입, 64 KiB 본문 경계, GUI를 지연한 동시 연결 34개의 예약 32개·거부 2개, 유휴·부분 입력·GUI 대기 상태의 종료를 확인한다. 후자의 클라이언트는 먼저 닫지 않았으며 수정 후 종료는 해당 실행에서 2~4ms였다.
- T09는 미설정·빈 값·`0`·`01`·`true`·`2`의 OFF, 권한·소유자, 실제 Unix peer 자격 조회와 자격을 읽을 수 없는 FD의 거부, 처리 중 종료 보류, 응답을 읽기 전 연결을 끊고 재접속했을 때 중복 반영 없음, 새 수신 수명의 경로·세션 분리를 확인했다. 다른 사용자 계정으로 실행한 실제 접속 시험은 수행하지 않았으며, 커널 자격 비교와 접근 권한 확인을 해당 근거와 구분한다.
- ASan에서 검사 하네스가 종료 보류 반환값을 무시한 채 창을 해제하는 오류를 확인했다. 하네스가 정상 GUI 종료가 허용될 때까지 대기하도록 수정한 뒤 T04~T09 전체가 통과했다(`step3-asan-green.log`). 종료 하네스 수정 후 T09도 별도로 통과했다(`step3-asan-close-green.log`). 제품의 기존 편집 영역 해제 순서는 이 원인으로 변경하지 않았다.
- TSan의 T04~T09와 종료 하네스 수정 후 T09가 각각 통과했고 데이터 경쟁 보고가 없었다(`step3-tsan-green.log`·`step3-tsan-close-green.log`). 원래 계약 검사 `test_liveparam`도 통과했다. 검사 옵션·단언·sanitizer 검출을 완화하지 않았다.
- 세 구성에서 GUI·CLI·두 검사 타깃을 빌드했다. 실제 소스 해시·GUI 컴파일 플래그는 `step3-build-meta.json`, 빌드는 `step3-all-build.log`·`step3-asan-build.log`·`step3-tsan-build.log`에 기록했다.
- 실제 시작 분기는 `main.cc`를 공유하는 선택적 검사 타깃 `test_liveparam_app`으로 확인했다. 검사 전용 애플리케이션 ID를 사용해 실행 중인 다른 ART의 파일 전달과 구분하며 제품 시작 옵션·IPC 연산은 추가하지 않는다. `cmake --build build --parallel 4 --target art test_liveparam_app`으로 빌드하고 격리된 리소스·설정·RAW로 시작했다. OFF의 실제 창·사진 표시와 소켓 부재는 `startup/off-window.png`, 일반·단독 GUI 각각의 PID·세션·편집기·소켓 및 잘못된 대상 거부는 `startup/startup-state.json`에 기록했다.
- macOS 파일 열기 이벤트가 기존 GUI에 전달된 뒤 PID·실행 세션·소켓이 유지되고 추가 프로세스가 없음을 확인했다(`startup/forward-state.json`). 이 환경에는 D-Bus 세션 버스가 없어 직접 재실행이 별도 GUI 주 프로세스가 됐다. 이 실행을 `GApplication` 원격 보조 프로세스 시험의 통과로 집계하지 않는다. 해당 실제 원격 보조 경로와 다른 사용자 계정의 접속은 최종 검증에서 별도 제한으로 유지한다.
- F03의 프레임·뷰·Navigator 계산 세대, T10~T12·T14 및 해당 경로의 T15는 남아 있다. `PPVERSION` 미증가 최종 판정과 전체 기능 완료는 이 기록으로 대체하지 않는다.
