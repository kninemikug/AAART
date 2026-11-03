# 실행 중 ART의 실시간 파라미터 조정: 가능성 검토와 설계안

- 상태: 구현 전 검토안
- 검토일: 2026-11-03
- 소스 기준: `9d90bd72b25ede7c0a65d4590113ebc4fe82137c`
- 전제: **GUI가 계속 실행되고, 대상 사진이 편집기에 열려 있어야 한다.**
- 이번 산출물: 읽기 전용 코드 탐색에 근거한 설계 문서. 코드·규칙 파일 수정, 빌드, 실행 검증은 수행하지 않았다.

## 1. 판단과 범위

실현 가능하다. ART에는 이미 파라미터 변경을 모아 백그라운드에서 미리보기를 다시 계산하는 경로가 있다. **후보 B인 로컬 IPC 서버 → GUI 명령 처리 → 기존 이벤트 기반 미리보기 갱신을 권고한다.** 엔진을 새 그래프 실행기로 교체할 필요는 없다. 다만 현재의 잠금·수명 관리가 외부 요청 빈도에서도 안전한지는 별도 검증해야 하며, 지연 시간이나 초당 갱신 횟수는 아직 입증되지 않았다.

여기서 실시간은 프로세스 재시작이나 매번 `.arp` 파일을 거치지 않고, 실행 중인 편집기의 값을 바꾸고 화면 결과를 비동기로 받는다는 뜻이다. 요청 수락, 편집 상태 반영, 미리보기 준비, 파일 저장은 각각 다른 상태다. 하드 실시간이나 모든 처리 단계의 즉시 중단을 뜻하지 않는다.

기존 `.arp` 생성 → ART-cli 렌더 경로는 최종 프로필·출력 검증과 회귀 기준으로 유지한다. 이번 검토는 WBS의 기존 오프라인 루프를 대체하는 구현 승인이 아니며, 별도 후속 범위와 검증 조건을 제안한다. GUI 없는 상시 데몬은 후보에서 제외한다.

## 2. 읽기 전용 탐색 결과

아래 링크의 줄 번호는 소스 기준 커밋에 해당한다. 확인한 동작과 이후의 제안을 구분한다.

### 2.1 미리보기 조정기는 이미 단계별 캐시를 가진다

| 확인 지점 | 현재 동작 | 설계에 주는 의미 |
|---|---|---|
| [improccoordinator.h:45](../rtengine/improccoordinator.h#L45) | `ImProcCoordinator`는 축소 전체 이미지와 여러 `Crop`을 관리한다. 주 편집 화면도 `Crop` 경로를 쓴다. | Navigator 갱신만 완료됐다고 주 편집 화면까지 완료됐다고 볼 수 없다. |
| [improccoordinator.cc:148](../rtengine/improccoordinator.cc#L148) | `updatePreviewImage(todo, ...)`가 RAW 전처리, 디모자이크, 이미지 취득, 단계별 처리, 표시 변환을 선택한다. | 재사용할 무효화 경계가 이미 있다. |
| [improccoordinator.cc:517](../rtengine/improccoordinator.cc#L517) | `M_RGBCURVE`, `M_LUMACURVE`, `M_LUMINANCE/M_COLOR`에 따라 `bufs_[0..2]`를 복사·재처리한다. | 임의 도구 하나보다 기존 단계 묶음 단위의 부분 재계산이 현실적이다. |
| [improcfun.h:98](../rtengine/improcfun.h#L98), [improcfun.cc:636](../rtengine/improcfun.cc#L636) | `STAGE_0..3`을 `switch`로 실행하며 `NAVIGATOR`, `PREVIEW`, `OUTPUT`을 구분한다. | 범용 동적 DAG나 독립 노드별 파라미터 교환 API가 있는 구조는 아니다. |
| [improccoordinator.cc:749](../rtengine/improccoordinator.cc#L749) | `setScale()`이 실제 크기를 계산하고 크기가 달라지면 캐시·표시 버퍼를 해제·재할당한다. | 외부 요청마다 해상도를 바꾸면 빠른 경로의 이득을 잃는다. |
| [dcrop.cc:146](../rtengine/dcrop.cc#L146) | Crop 크기 변경이나 고품질 요청은 `todo = ALL`로 확대한다. | 부분 갱신 비용은 줌·뷰포트에도 의존한다. |

현재 단계 구성은 다음과 같다. 각 단계 내부의 모든 도구에 독립 캐시가 있는 것은 아니다.

```text
RAW 전처리 → 디모자이크 → getImage / 작업 색공간 변환
  → spot 처리 → STAGE_0(안개 제거, 동적 범위 압축) → 기하 변환
  → STAGE_1(채널 믹서, 노출, HSL, 톤 이퀄라이저) → bufs_[0]
  → STAGE_2(선명화, 색 보정, 스무딩 등)             → bufs_[1]
  → STAGE_3(채도, 톤 커브, 필름 효과, 국부 대비 등) → bufs_[2]
  → 모니터/출력 색 변환 → 화면·히스토그램
```

이 도식은 처리 순서를 요약한 것이다. Crop은 별도 버퍼와 노이즈 제거 경로를 가지며, `STAGE_2`의 일부 도구는 `OUTPUT/PREVIEW`에서만 실행한다. 미리보기와 최종 출력의 픽셀이 항상 같다는 뜻이 아니다.

### 2.2 파라미터 전달과 스레드 경계

현재 경로는 다음과 같다.

```text
GUI 도구 값 변경
  → ToolPanelCoordinator::panelChanged(event, description)
  → beginUpdateParams(): paramsUpdateMutex 잠금, nextParams 반환
  → 모든 도구 패널의 write(nextParams)
  → endUpdateParams(flags): 무효화 비트 누적, 잠금 해제, 처리 예약
  → ThreadPool(HIGHEST)의 ImProcCoordinator::process()
  → nextParams를 작업용 params로 복사, 누적 비트를 가져와 재계산
  → PreviewImageListener / Crop 결과
  → GUI idle 콜백에서 표시 자료 갱신
```

근거: [toolpanelcoord.cc:484](../rtgui/toolpanelcoord.cc#L484), [improccoordinator.cc:1484](../rtengine/improccoordinator.cc#L1484), [improccoordinator.cc:1579](../rtengine/improccoordinator.cc#L1579), [previewhandler.cc:115](../rtgui/previewhandler.cc#L115).

- `nextParams`와 작업용 `params`가 분리되어, 재계산 중 다음 변경을 누적할 수 있다. 실행 중인 계산을 즉시 취소하고 새 값으로 도구 하나만 재시작하는 방식은 아니다.
- `mProcessing`은 조정기 계산과 `Crop::fullUpdate()`를 직렬화한다. `mTweak`은 임시 파라미터 변경·복원을 보호하며 두 경로의 잠금 순서는 `mProcessing → mTweak`이다. [조정기 처리](../rtengine/improccoordinator.cc#L1528), [Crop 처리](../rtengine/dcrop.cc#L784).
- **추가 확인이 필요한 경계:** `process()`의 `params = nextParams`는 `mProcessing.lock()`보다 먼저 실행된다. `Crop::fullUpdate()`는 `mProcessing`만 잡고 같은 `params`를 읽거나 임시 변경한다. 현재 코드를 완전한 불변 스냅샷 또는 전체 데이터 레이스 방지 구조로 간주하면 안 된다. 정적 탐색에서 식별한 경쟁 가능성이며, 발생 여부와 수정은 후속 검증 대상이다.
- `getParams()`는 `params`를 잠금 없이 복사한다. `updaterRunning`도 일부 경로에서 잠금 없이 읽으며, `tweakOperator` 설정·해제에는 자체 잠금이 없다. 외부 수신 스레드가 이 API를 추가로 호출하면 보호 범위를 넓히지 않은 채 접근 주체만 늘어난다. [improccoordinator.h:208](../rtengine/improccoordinator.h#L208), [실행·정지](../rtengine/improccoordinator.cc#L1467), [설정·해제](../rtengine/improccoordinator.cc#L685).
- `endUpdateParams()` 뒤에도 GUI가 반환 포인터를 리스너에 전달한다. 새 비동기 코드에서는 이 포인터를 보관하지 말고, 소유한 값 복사본을 전달해야 한다. 잠금 획득 후 예외로 해제가 생략되는 경로도 만들지 않아야 한다.

### 2.3 이벤트·GUI·저장 경로

요구사항에서 지칭한 `RefreshMapEvent`라는 이름의 심볼은 이 소스에서 발견되지 않았다. 실제 체계는 `ProcEvent`, 엔진의 `RefreshMapper`, GUI의 `ProcEventMapper`와 무효화 비트다. [refreshmap.h:29](../rtengine/refreshmap.h#L29), [eventmapper.cc:38](../rtgui/eventmapper.cc#L38).

`M_MINUPDATE/MINUPDATE`는 이미지 변경 없는 표시 갱신 전용이며 다른 이벤트와 결합하면 안 된다는 주석이 있다. `M_VOID`는 파라미터만 바꾸고 프리뷰를 계산하지 않는 의미다. 외부에 내부 이벤트 번호나 비트마스크를 노출하지 않고, 서버가 허용된 키를 기존 이벤트에 매핑해야 한다. 일반 처리 무효화 비트의 합집합과 `MINUPDATE`의 단독 사용 규칙을 혼동하지 않는다.

`ToolPanelCoordinator::panelChanged()`는 모든 패널 값을 다시 쓴 뒤 `hasChanged`와 파라미터 리스너를 갱신한다. 엔진 값만 바꾸면 화면 컨트롤·히스토리와 어긋나고 다음 GUI 조작에 덮어써질 수 있다. `profileChange()`는 부분 프로필 병합, 패널 `read()`, 지오메트리, 리스너 통지를 함께 수행하고 RAW 관련 값이 같을 때 RAW 무효화를 줄인다. [toolpanelcoord.cc:564](../rtgui/toolpanelcoord.cc#L564).

필드 하나를 바꿀 때 전체 프로필을 기본값과 함께 적용해서는 안 된다. `ParamsEdited`에는 `exposure` 같은 그룹 단위 선택이 있으므로, 그룹 선택만으로 `Exposure.Compensation` 이외 필드의 보존이 보장되지 않는다. [paramsedited.h:25](../rtgui/paramsedited.h#L25), [PartialProfile 계열](../rtengine/procparams.h#L1701).

`EditorPanel::open()`은 프로세서와 리스너를 만들고 초기 프리뷰 배율을 지정한다. `close()`는 프로필 저장 후 처리를 멈추고 리스너·뷰를 분리한다. 기존 자동 저장 및 닫을 때 저장 정책이 있으므로 외부 변경도 사용자의 일반 편집과 같은 저장 대상이 된다. [editorpanel.cc:1136](../rtgui/editorpanel.cc#L1136), [close/saveProfile](../rtgui/editorpanel.cc#L1221).

`IdleRegister`는 `gdk_threads_add_idle_full()`로 GUI 작업을 예약하고 파괴 시 미실행 콜백을 제거한다. `PreviewHandler`, 진행률 UI가 이 패턴을 사용한다. Crop 비동기 작업은 프로세서의 공유 소유권을 캡처한다. 외부 명령도 이 수명 관리 패턴에 맞춰야 한다. `GThreadLock`만 잡고 임의 수신 스레드에서 편집기를 변경하는 방식을 새로 만들지 않는다. [guiutils.cc:48](../rtgui/guiutils.cc#L48), [crophandler.cc:589](../rtgui/crophandler.cc#L589).

### 2.4 ProcessingJob·BatchQueue·CLI는 다른 경로다

| 경로 | 확인한 생성·실행·종료 및 스레드 | 실시간 연결 시 판단 |
|---|---|---|
| `ProcessingJob` | `create()`가 파라미터를 값으로 보관한다. `InitialImage*` 생성자는 참조 수를 늘리고 소멸자가 줄인다. [processingjob.h:27](../rtengine/processingjob.h#L27), [processingjob.cc:23](../rtengine/processingjob.cc#L23). | 실행 중 job의 파라미터를 덮어쓰는 계약이 없다. |
| `processImage()` | 호출 스레드에서 동기 처리한다. 정상 종료에서 `delete job`; 로드 실패 경로에서도 삭제한다. [simpleprocess.cc:103](../rtengine/simpleprocess.cc#L103), [종료](../rtengine/simpleprocess.cc#L534), [진입](../rtengine/simpleprocess.cc#L640). | 실행에 넘긴 job은 소비된다. 반복 실행·실행 중 destroy·완료 후 재사용 금지. `destroy()`는 아직 넘기지 않은 job의 취소용이다. |
| `BatchQueue` | GUI 큐가 job을 만들고 `startBatchProcessing()`으로 `ThreadPool(NORMAL)`에 전달한다. 작업자는 `imageReady()`에서 다음 job을 받는다. 큐는 RW 잠금, GUI 잠금과 idle 통지를 사용한다. [batchqueue.cc:690](../rtgui/batchqueue.cc#L690), [imageReady](../rtgui/batchqueue.cc#L996), [simpleprocess.cc:652](../rtengine/simpleprocess.cc#L652). | 편집기 프리뷰와 별도 출력 파이프라인이다. 이미 실행 중인 내보내기에 외부 변경을 전파하지 않는다. |
| ART-cli | `Gio::init()`·설정 로드 후 `processLineParams()`에서 입력별 프로필 병합, job 생성, `processImage()`, 파일 저장을 수행하고 반환한다. [main-cli.cc:129](../rtgui/main-cli.cc#L129), [main-cli.cc:955](../rtgui/main-cli.cc#L955). | 화면이나 편집기 수명, 상시 요청 루프가 없다. 헤드리스 렌더는 가능하나 지속 편집 데몬은 별도 설계가 필요하다. |
| GUI | `main.cc`는 `Gtk::Application` 또는 `Gtk::Main` 루프를 운용한다. 원격 실행의 명령 전달은 파일·세션 열기에 사용된다. [main.cc:270](../rtgui/main.cc#L270), [main.cc:679](../rtgui/main.cc#L679). | 기존 원격 실행 기능이 범용 `set_param` 서버라는 뜻은 아니다. 두 GUI 기동 분기 모두 서버 수명을 연결해야 한다. |

공통 엔진 초기화는 [init.cc:73](../rtengine/init.cc#L73)에서 작업 풀을 만든다. 풀 작업 내부에서는 OpenMP 병렬 처리도 사용한다. IPC 처리를 렌더 풀에 장시간 넣으면 대기·응답이 렌더와 경쟁하므로 I/O와 렌더 작업을 분리한다.

CLI의 실패 분기에는 `processImage()` 이후 `ProcessingJob::destroy(job)` 호출도 보인다. 소비 계약과 충돌할 가능성을 별도 메모로 남기며, 여기서는 안전한 재사용 근거로 삼거나 수정하지 않는다. GUI/CLI가 같은 엔진을 쓴다는 이유로 job 소유권까지 같은 제어 방식으로 취급해서는 안 된다.

## 3. 재계산 범위와 비용

아래는 현재 이벤트 매핑에 따른 보수적 범위다. [refreshmap.cc:25](../rtengine/refreshmap.cc#L25), [복합 플래그 정의](../rtengine/refreshmap.h#L58)가 기준이며, 도구 이름과 플래그 이름만으로 비용을 추측하지 않는다.

| 변경 | 기존 매핑·최소 무효화 범위 | 확대될 수 있는 비용 |
|---|---|---|
| `Exposure.Compensation` | `EvExpComp → HDR`: spot, 선형 노이즈 제거 관련 단계, HDR, 자동 설정, STAGE_1~3 | 노출만 한 번 곱하는 비용이 아니다. 상세 Crop 노이즈 제거·HDR 캐시도 다시 계산할 수 있다. 보통 RAW 전처리·디모자이크는 생략 가능하다. |
| 채도·톤 커브 대비 | `LUMINANCECURVE = M_LUMINANCE \| M_COLOR`: STAGE_3 | 이전 단계 캐시를 재사용해도 색 변환, 화면 통지, 히스토그램 비용은 남는다. |
| 선명화·색 보정 계열 | STAGE_2부터 후속 단계, 연결 마스크 사용 시 범위 확대 | Navigator와 실제 PREVIEW의 도구 활성 조건이 다르다. |
| 화이트밸런스 | `WHITEBALANCE = M_WHITEBALANCE \| ALLNORAW` | `wb_preview_mode`가 전처리 이전 적용을 요구하면 `M_PREPROC \| M_RAW`까지 확대한다. |
| 디모자이크·RAW 전처리 | `DEMOSAIC`, `DARKFRAME`, `ALL` 등 | RAW 단계와 후속 캐시 전반의 재계산. 초기 허용 키에서 제외한다. |
| 줌·크기·회전·뷰포트 | 캐시 재할당 시 `ALL`, 상세 창 `skip == 1`이면 고품질 RAW 경로 가능 | 프리뷰 배율은 단순 출력 리사이즈가 아니다. 기하 변환·Crop 크기·고품질 처리까지 영향을 준다. |

추가 제한은 다음과 같다.

- 현재 `process()`는 `panningRelatedChange = true`를 넘긴다. 따라서 단계별 비트가 적더라도 Navigator 처리 진입, 리스너가 있는 Crop 갱신, 표시 변환을 더 수행할 수 있다. “변경 노드 이후만 정확히 계산”한다고 보장할 수 없다.
- 축소 프리뷰에서는 빠른 디모자이크를 쓰는 경로가 있지만, 100% 상세 창이나 고품질 모드가 있으면 비용이 달라진다. [improccoordinator.cc:168](../rtengine/improccoordinator.cc#L168).
- CPU/GPU 간 동기화도 고려해야 한다. 도구 실행 래퍼가 CPU 접근 전에 이미지 동기화를 수행한다. 캐시나 버퍼 포인터를 외부에서 교체하면 이 규칙을 깨뜨릴 수 있다. [improcfun.cc:616](../rtengine/improcfun.cc#L616).
- 초기 단계에서는 배율·품질 정책을 GUI에 맡기고, 연속 요청 수를 제한한다. 최초 이미지 로드와 캐시가 준비된 상태의 지연을 분리 측정한다.

## 4. 설계 후보와 위험 비교

### 후보 A — 엔진 단계·노드별 갱신 API와 빠른 프리뷰 경로

`ProcParams`의 허용 필드를 논리 노드에 매핑하고, 변경 노드에서 후속 단계로 무효화를 전파하는 live 제어 계층을 만든다. 기존 4단계·캐시부터 활용하고, 성능 근거가 있을 때 도구별 캐시로 세분화한다. GUI는 계속 실행하며, 외부 진입용 얇은 IPC 어댑터와 화면 컨트롤 동기화 계층이 추가로 필요하다. 이 후보의 주된 변경은 전송 방식보다 엔진 실행·캐시 경계다.

| 위험 축 | 분석 및 필요한 조치 |
|---|---|
| 스레드 안전성 | 매우 높음. `ImProcFunctions`는 공유 파라미터 포인터를 읽는다. 실행 중 노드 값·포인터를 직접 교체하면 도구 간 값이 섞이고 Crop·임시 변경과 경쟁한다. 작업별 불변 스냅샷, 버퍼 소유권, 일관된 잠금 순서부터 정의해야 한다. |
| 재구성 비용 | 높음. 동적 DAG가 없어 의존성·캐시 유효성 규칙을 새로 유지해야 한다. HDR·노이즈 제거·마스크·색공간·뷰포트 의존성이 단계 경계를 넘는다. 배율 변경은 버퍼 재할당과 상위 재계산을 요구한다. |
| PPVERSION | 같은 입력·설정의 도구 의미와 저장 형식을 유지하면 증가 생략을 검토할 수 있다. 연산 순서, 근사 처리, 기존 파라미터 의미·기본값을 바꾸면 “도구 동작 변경”에 해당하여 증가가 필요하다. |
| GUI/CLI 분기 | 높음. 공통 `ImProcFunctions`를 바꾸면 CLI 출력도 영향을 받는다. PREVIEW만의 캐시·스케줄링과 OUTPUT 처리 의미를 분리하고 두 경로를 회귀 검증해야 한다. |

장점은 장기적인 세밀한 성능 제어다. 초기 연결부터 선택하기에는 변경 범위와 회귀 위험이 크다. B 구현 후 실측으로 병목 단계가 밝혀질 때 재검토한다.

### 후보 B — 실행 중 GUI의 로컬 IPC 서버와 기존 갱신 경로 연결

ART GUI 프로세스가 명시적으로 켠 로컬 서버를 노출한다. 수신부는 JSON·연결 인증·크기 제한만 다루고, 검증된 명령을 GUI 메인루프로 전달한다. GUI가 대상 편집기를 재확인한 뒤 허용 필드, 컨트롤, 히스토리, `nextParams`를 함께 갱신한다. 엔진은 기존 이벤트·캐시를 사용한다.

macOS/Linux의 1차 전송은 Unix domain socket을 제안한다. Windows의 후속 이식은 named pipe 또는 loopback TCP 어댑터로 분리한다. 대안인 HTTP는 loopback 전용이어야 하며, 인증과 브라우저 출처 검사까지 포함해야 한다. HTTP를 사용한다고 스레드 경계 문제가 해결되는 것은 아니다.

| 위험 축 | 분석 및 필요한 조치 |
|---|---|
| 스레드 안전성 | 중간 이상. GUI로 변경 주체를 모아 새 엔진 작성자를 늘리지 않지만, §2.2의 기존 잠금 경계는 남는다. I/O 스레드에서 GTK·조정기·job 접근 금지, 편집기 세대 확인, 소유한 명령 복사본, 정지·종료 순서와 완료 세대 추적이 필요하다. |
| 재구성 비용 | 낮음~중간. GUI를 다시 열거나 RAW를 매번 로드하지 않고 기존 무효화 범위를 따른다. 노출·WB·고품질 창에서는 계산 범위가 넓으며 요청 병합·유량 제한이 필요하다. |
| PPVERSION | IPC·일시 상태와 기존 값 전달만 추가하면 증가를 생략할 수 있다. `.arp` 키나 기존 도구 의미를 바꾸는 순간 §6 정책에 따라 증가한다. 프로토콜 버전은 별도로 관리한다. |
| GUI/CLI 분기 | 낮음~중간. 서버와 편집 명령은 GUI에만 둔다. `main-cli.cc`에 상시 루프나 서버를 추가하지 않는다. 공유 엔진 잠금·리스너를 손대면 CLI와 내보내기 회귀 검증은 필요하다. |

**권고 후보.** 기존 편집 의미를 재사용하면서 외부 계약을 작게 고정할 수 있다. 특정 OS에서의 최초 검증과 크로스플랫폼 완료는 구분해 보고해야 한다.

### 후보 C — GUI에서 전용 프로필 파일 변경 감시

외부 제어기가 임시 `.arp`를 완성한 뒤 원자적으로 교체하고, 실행 중 GUI가 변경을 감지해 `profileChange()`로 반영한다. 사용자의 실제 sidecar를 통신 파일로 쓰지 않고, 요청 ID·편집기 ID·기준 revision을 별도 봉투와 결과 파일로 전달한다. GUI 없는 데몬 방식이 아니다.

| 위험 축 | 분석 및 필요한 조치 |
|---|---|
| 스레드 안전성 | 중간. 감시 콜백을 GUI로 전달하고 대상 수명·revision을 확인해야 한다. 부분 기록, 중복 이벤트, 자체 저장 재감지, 이미지 전환 시 오래된 파일 적용을 막아야 한다. |
| 재구성 비용 | 중간~높음. 파일 파싱·병합과 넓은 프로필 이벤트가 추가된다. 기존 RAW 필터링은 있지만 키별 최소 무효화보다 보수적이다. 파일 감시 지연도 더해진다. |
| PPVERSION | 기존 `.arp`만 사용하면 증가 불필요. 전송용 키를 `.arp`에 추가하면 형식 변경이 되므로 봉투와 분리해야 한다. |
| GUI/CLI 분기 | 중간. 프로필 의미는 재사용하지만 GUI 감시기와 응답 관리가 새로 필요하다. CLI로 반복 렌더만 하면 실행 중 편집기 조정이라는 목표를 충족하지 않는다. |

짧은 개념 검증에는 사용할 수 있으나, 확인 응답·충돌·연속 조정 계약을 추가하면 파일 기반 프로토콜이 복잡해진다. 초기 제품 경로로 권고하지 않는다.

A는 엔진 최적화 중심, B는 외부 연결 중심의 선택이다. 완전히 배타적인 기술은 아니며, B에서도 기존 단계 캐시를 활용한다. 권고는 B를 먼저 완성하고 필요할 때 A의 세분화를 추가하는 순서다.

## 5. 권고안의 최소 구현 단계

아래 단계는 후속 구현 계획이다. 이번 검토에서 수행한 작업이 아니다.

1. **스레드 경계와 지원 상태 확정.** `params` 복사 위치, Crop 읽기·임시 변경, `getParams()`, 조정기 종료와 실행 플래그의 보호 범위를 확인한다. 잠금 순서를 문서화하고 필요한 동기화 변경만 별도 수정한다. 외부 업데이트의 높은 빈도에서도 데이터 레이스·교착이 없음을 검증하기 전에는 실사용 기능을 켜지 않는다. 초기에는 spot 편집 등 `TweakOperator` 활성 상태의 요청을 `BUSY`로 거부하고, 줌·팬과의 동시 실행도 검증한다.
2. **GUI 내 명령 하나 완성.** 우선 `Exposure.Compensation` 한 키만 지원한다. 새 `applyExternalPatch` 성격의 GUI 메서드에서 패널의 현재 값으로 복사본을 구성하고 필드만 수정한다. `Exposure::read()`처럼 리스너를 차단하여 컨트롤을 갱신한 다음, 기존 `panelChanged(EvExpComp, ...)`와 동등한 경로를 정확히 한 번 실행한다. 검증은 변경 전에 끝내며 미지원 필드·비활성 도구를 임의 활성화하지 않는다. 스냅샷은 잠금 없는 `getParams()`에서 얻지 않는다.
3. **로컬 서버와 편집기 식별 연결.** 기본값은 비활성화한다. GUI 공통 창 수명에 서버를 붙여 `Gtk::Application`과 `Gtk::Main` 기동 모두 처리한다. I/O → 소유된 유한 큐 → `IdleRegister` 등 GUI 전달 → 대상 재확인 순서를 쓴다. raw `EditorPanel*`을 수신부에 보관하지 않고 GUI 소유 레지스트리의 `editorId`로 조회한다. 이미지 재열기에는 새 ID를 발급한다.
4. **세대와 완료 응답 연결.** 모든 GUI 편집·히스토리 이동과 외부 반영에 `revision`을 부여한다. 조정기의 파라미터 스냅샷 시점부터 Navigator·주 Crop의 결과와 GUI 전달까지 같은 세대 번호를 운반한다. 기존 리스너에는 revision 필드가 없으므로 이 추적은 추가 구현이 필요하다. `setProgressState(false)` 하나로 특정 요청의 완료를 추정하지 않는다. 줌·팬은 별도 `viewRevision`으로 구분하고 오래된 결과를 최신 완료로 보고하지 않는다.
5. **검증 후 키 확장.** 요청 단위 GUI 원자성, 컨트롤·히스토리·저장 일치, 오류·재연결·닫기·종료를 확인한다. 외부 변경은 일반 GUI 편집과 동일하게 기존 자동 저장·닫기 저장 정책을 따른다. 실행 중 내보내기는 생성 당시 값을 유지한다. 이후 채도, 마지막으로 WB 등 재계산 범위가 넓은 키를 개별 검증하며 추가한다.

후속 변경 예상 범위는 `rtgui/`의 로컬 서버·명령 처리, `EditorPanel` 수명, `ToolPanelCoordinator` 패치 적용과 필요시 도구 패널 접근부다. `rtengine/`은 확인된 공유 상태 보호 및 revision 전달에 한정한다. `rtengine/rtengine.h` 등 리스너 인터페이스 변경 시 기존 구현체가 계속 동작할 기본 동작이나 내부 확장 방법을 검토한다. CMake에는 필요한 GUI 소스만 등록하며 새 의존성은 필요성이 확인된 경우에만 도입한다.

첫 구현은 편집기당 외부 요청 하나가 미리보기 처리 중이면 다음 변경을 `BUSY`로 거부한다. 기존 GUI 조작은 허용하며, 먼저 반영된 외부 요청이 새 GUI 편집으로 대체되면 `SUPERSEDED`로 보고한다. 처리량이 필요해지면 수신 전에 합칠 수 있는 절대값 변경만 병합하되 각 요청의 대체 상태를 남긴다. 현재 실행 중인 처리의 강제 중단이나 `stopProcessing()`의 요청별 호출은 초기 설계에 넣지 않는다.

## 6. PPVERSION 정책 제안

[ppversion.h:3](../rtgui/ppversion.h#L3)의 현 정책은 “ARP 파일 형식 또는 도구 동작 변경 시 증가”이며, 기준 값은 **1045**다. [procparams.cc:2951](../rtengine/procparams.cc#L2951)에서 저장하고, 로드 시 버전별 호환 분기를 사용한다. IPC를 추가한다는 사실만으로 이 버전을 통신 버전처럼 올릴 이유는 없다.

| 변경 종류 | 정책 |
|---|---|
| 이번 설계 문서만 추가 | 증가하지 않는다. |
| 기존 키의 기존 값을 GUI 이벤트로 전달; 일시적 요청 ID·revision·서버 설정 추가 | 형식·도구 의미·기본값을 유지한다는 검증을 전제로 생략 가능하다. 이 상태는 `.arp`에 저장하지 않는다. |
| 파라미터 구조에 세대·큐 같은 런타임 상태 추가 | 우선 `ProcParams` 밖에 둔다. 구조체 변경 자체보다 직렬화·기본값·연산 의미 영향으로 판단한다. 영향이 없다는 증거가 없으면 생략을 승인하지 않는다. |
| `.arp` 그룹·키·타입·단위·기본값·열거값 해석 변경 | 증가하고 저장·로드·기존 프로필 호환 정책과 `docs/arp_schema.md`를 함께 갱신한다. |
| 동일 프로필의 처리 순서·수식·기존 도구 결과 변경 | 파일 형식이 같아도 도구 동작 변경이므로 증가한다. PREVIEW 전용 근사나 생략을 추가할 때도 이 기준으로 판정한다. |
| 잠금·스케줄링·캐시 유효성 수정 | 기존 도구 의미와 출력 보존이 입증되면 생략 가능하다. 재계산 누락·처리 순서 변경으로 결과가 달라지면 다시 판정한다. |

**생략 조건:** 기존 프로필의 로드·저장 해석, 기본값, 수동 GUI 조정과 외부 조정의 효과, GUI/CLI 최종 출력 의미가 유지되어야 한다. 부동소수점·GPU 차이의 허용 오차는 검증 전에 정하고, 이를 의미 변경의 면책으로 쓰지 않는다. 불확실하면 결과를 비교한 뒤 판정한다. `protocolVersion`은 IPC 계약에만 사용하고 PPVERSION과 독립적으로 증가한다.

AGENTS.md에는 “tool behavior”가 화면 접속 방식까지 포함하는지 모호하므로, 다음 해석을 명시할 것을 제안한다: **PPVERSION의 도구 동작은 저장된 프로필의 해석·기본값·영상 처리 의미를 말한다. 이를 보존하는 IPC 전송·수명·동기화 변경은 회귀 검증 근거를 남겨 증가를 생략할 수 있다.** 기존의 형식·도구 의미 변경 의무를 완화하는 문안은 아니다.

## 7. 외부 계약 초안

### 7.1 전송과 상태

1차 규격은 UTF-8 JSON 한 객체 + LF 단위의 로컬 소켓 프로토콜이다. 줄바꿈은 JSON 문자열 내부에서 이스케이프한다. 중복 JSON 키는 거부한다. 프레임 상한은 64 KiB, 연결별 미처리 요청은 1개, GUI 명령 큐 상한은 32개를 제안한다. 한도 초과 시 적용하지 않고 오류를 보낸다. 이 수치는 구현 전 고정할 초기 제안이며 측정 결과로 조정할 수 있다.

소켓은 사용자 전용 디렉터리·접근 권한으로 만들고, 같은 사용자 확인 및 연결별 인증을 거친다. Windows/loopback 전송은 프로세스마다 발급한 접속 자격을 사용한다. 외부 네트워크 바인딩·임의 파일 열기·임의 명령 실행·범용 구조체 쓰기는 v1 범위에 없다.

지원 연산은 `get_state`, `set_param`이다. 인증 후 `get_state`로 `sessionId`, 편집기 목록과 `editorId`, 현재 `revision`, `viewRevision`, 허용 키·범위·활성 상태 및 최근 요청 상태를 조회한다. 아래 구조와 키 이름은 신규 계약 제안이며 현재 제공되는 API가 아니다.

최초 `get_state`에는 `protocolVersion`, `requestId`, `op`만 필요하다. `editorId`를 생략하면 편집기 목록을, 지정하면 해당 편집기의 상태를 반환한다. 재연결 시 `sessionId`를 함께 보내 기존 실행과 같은지 확인할 수 있다. 상태 조회도 GUI 메인루프에서 일관된 복사본을 만들어 응답하며 수신 스레드에서 엔진 값을 직접 읽지 않는다.

### 7.2 set_param 요청과 응답 예시

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

`Exposure.Compensation`은 `.arp`의 `[Exposure] Compensation`, 내부의 `ProcParams::exposure.expcomp`, 이벤트 `EvExpComp`로 매핑한다. 단위는 EV, 초기 허용 범위는 GUI와 같은 `-12..12`의 유한 실수다. `NaN/Infinity`, 문자열 숫자, 알 수 없는 키, 잘못된 타입과 범위는 거부하며 조용히 보정하지 않는다. GUI의 `0.05` 조작 간격은 입력 범위와 구분한다. [exposure.cc:64](../rtgui/exposure.cc#L64), [프로필 저장](../rtengine/procparams.cc#L2965), [스키마](arp_schema.md#exposure).

도구가 꺼져 있으면 `TOOL_DISABLED`를 반환한다. v1은 한 요청에 위 키 하나만 받으며, 향후 복수 키를 지원할 때는 전부 검증한 뒤 한 번에 반영하거나 전부 거부한다. WB는 method·temperature·green 등의 결합 규칙을 정의한 뒤 추가한다.

GUI 반영 후 응답:

```json
{
  "protocolVersion": 1,
  "requestId": "req-00042",
  "sessionId": "run-7f21",
  "editorId": "editor-c903",
  "status": "APPLIED",
  "result": {
    "appliedRevision": 18,
    "viewRevision": 6,
    "effectiveParams": { "Exposure.Compensation": 0.75 },
    "previewStatus": "PENDING",
    "renderedRevision": 17,
    "renderedViewRevision": 6,
    "ppVersion": 1045
  }
}
```

이는 GUI 컨트롤·편집 상태와 `nextParams`에 변경을 반영했다는 응답이다. 미리보기 준비나 파일 저장 완료를 뜻하지 않는다. 준비 결과는 `get_state`로 확인한다.

```json
{
  "protocolVersion": 1,
  "requestId": "query-00043",
  "sessionId": "run-7f21",
  "editorId": "editor-c903",
  "status": "OK",
  "result": {
    "revision": 18,
    "viewRevision": 6,
    "renderedRevision": 18,
    "renderedViewRevision": 6,
    "lastMutation": {
      "requestId": "req-00042",
      "appliedRevision": 18,
      "previewStatus": "READY"
    }
  }
}
```

`READY`는 같은 편집 세대·뷰 세대의 Navigator와 주 표시 Crop 결과가 GUI에 전달되어 표시 자료가 준비된 상태다. 실제 모니터의 그리기 완료, 별도 상세 창, 전체 해상도 출력까지 포함하지 않는다. 결과 세대를 추적할 수 없으면 `renderedRevision: null`로 두고 완료를 추측하지 않는다. 후속 편집으로 미완료 결과가 대체되면 해당 요청은 `SUPERSEDED`, 처리 실패라면 `FAILED`로 보고한다. 이전 세대의 완료를 최신 `READY`로 보고하지 않는다.

### 7.3 필드와 충돌 규칙

| 필드 | 타입·필수 조건·의미 |
|---|---|
| `protocolVersion` | 정수, 모든 요청에 필수. v1에서는 `1`. 불일치하면 적용 전에 거부한다. |
| `requestId` | 1~128자 문자열, 모든 요청에 필수. 클라이언트가 요청마다 발급하는 상관 ID. |
| `op` | `get_state` 또는 `set_param`. |
| `sessionId` | `set_param`에 필수. GUI 실행마다 발급하여 재시작 전 요청을 무효화한다. |
| `editorId` | `set_param`에 필수. 같은 경로를 다시 열어도 다른 ID를 쓴다. 암묵적인 활성 탭 지정을 사용하지 않는다. |
| `baseRevision` | 음이 아닌 정수, `set_param`에 필수. GUI 적용 직전 revision과 일치할 때만 변경한다. |
| `params` | 허용 키와 값의 객체, `set_param`에 필수. 생략한 값은 유지한다. |
| `mutationRequestId` | `get_state`의 선택 문자열. 해당 편집기의 이전 변경 요청 상태를 조회한다. 조회 자체의 `requestId`와 구분한다. |
| `status` | 응답에 필수. `APPLIED`, `OK`, `ERROR`. |
| `result` / `error` | 성공 시 `result`, 실패 시 `error` 중 하나만 반환한다. |

| 주요 응답 필드 | 타입·의미 |
|---|---|
| `result.appliedRevision` | 정수. 해당 변경을 반영한 편집 세대. |
| `result.revision` | 정수. 조회 시점의 현재 편집 세대. 후속 GUI 편집으로 증가할 수 있다. |
| `result.viewRevision` | 정수. 현재 뷰포트·줌 세대. |
| `result.effectiveParams` | 실제 GUI에 반영한 키와 값의 객체. |
| `result.previewStatus` / `lastMutation.previewStatus` | `PENDING`, `READY`, `SUPERSEDED`, `FAILED`. 반영과 렌더 상태를 구분한다. |
| `result.renderedRevision` / `renderedViewRevision` | 정수 또는 `null`. 같은 결과의 편집·뷰 세대를 쌍으로 판정한다. |
| `result.lastMutation` | 해당 편집기의 최근 외부 변경 ID·반영 revision·렌더 상태. `get_state`에 이전 `mutationRequestId`를 지정하면 캐시에 남은 그 요청의 상태를 조회한다. |
| `result.ppVersion` | 정수. 프로필 버전 진단값이며 프로토콜 버전과 별개다. |
| `error.code`, `message`, `details`, `retryable` | 코드·설명 문자열, 추가 정보 객체, 재시도 가능 여부의 불리언. |

`revision`은 GUI 메인루프에서 단조 증가시킨다. 마우스 조작, 히스토리 이동, 프로필 변경, 처리 결과의 자동값이 편집 상태에 반영되는 경우도 같은 관리에 포함한다. 비교 → GUI 갱신 → revision 발급을 같은 GUI 콜백에서 수행하고, 값이 같은 요청도 성공하면 revision을 한 번 증가시킨다. I/O 측에서 비교만 끝내고 나중에 적용해서는 안 된다.

같은 `requestId`와 같은 내용의 재전송은 응답 캐시로 처리하여, 재실행 없이 처리 중 상태나 원래 응답을 반환한다. 캐시는 연결 객체가 아닌 GUI 프로세스에 두고 `(sessionId, editorId, requestId)`를 키로 사용한다. ID는 연결을 넘어 유일하게 발급한다. 다른 내용으로 ID를 재사용하면 `REQUEST_ID_CONFLICT`를 반환한다.

처리 중 항목은 만료시키지 않고 완료부터 5분 보관하며 최대 1024건을 제안한다. 기한 전 항목을 조기 폐기하지 않고 포화 시 `BUSY`를 반환한다. 수락·ID 등록은 GUI의 직렬 처리에서 확정한다. 기존 ID 조회 → 입력·대상·revision 검사 → 캐시 자리 예약 → 값 적용 순서이며, `BUSY` 등 수락 전 오류는 변경 요청 캐시에 등록하지 않는다. 클라이언트는 실행 세션 내에서 ID를 재사용하지 않는다. 상태 조회에서 해당 ID의 캐시가 없으면 `lastMutation: null`과 `mutationStatus: UNKNOWN`을 반환하여 완료나 실패를 추측하지 않는다.

연결 종료·타임아웃은 실패 확정이 아니다. 캐시 보관 기간 내에는 같은 요청을 재전송할 수 있다. 기한이 지났거나 프로세스가 재시작됐다면 자동 재전송하지 않고 `get_state`로 확인한 뒤 새 revision을 근거로 별도 요청을 만든다. 이전 성공 요청의 재실행은 원래 `baseRevision` 검사로도 거부된다. 연결 타임아웃을 이유로 반영된 변경을 되돌리지 않는다.

### 7.4 최소 오류 코드

모든 오류는 같은 형식으로 반환한다. 내부 예외·로컬 파일의 전체 경로는 응답에 노출하지 않는다.

```json
{
  "protocolVersion": 1,
  "requestId": "req-00042",
  "sessionId": "run-7f21",
  "editorId": "editor-c903",
  "status": "ERROR",
  "error": {
    "code": "REVISION_CONFLICT",
    "message": "편집 상태가 변경되었습니다.",
    "details": { "currentRevision": 19 },
    "retryable": false
  }
}
```

| 코드 | 발생 조건과 호출 측 처리 |
|---|---|
| `INVALID_REQUEST` | JSON, 타입, 알 수 없는 필드, 연산 이름, 크기 위반. 요청을 수정한다. 해석 불가능하면 `requestId`는 `null`을 허용한다. |
| `UNSUPPORTED_VERSION` | 지원하지 않는 프로토콜. 지원 버전을 확인한다. |
| `UNAUTHORIZED` | 연결 인증·사용자 검사 실패. 값을 변경하지 않는다. |
| `SESSION_MISMATCH` | 재시작 등으로 실행 ID 불일치. 상태를 다시 조회한다. |
| `EDITOR_NOT_FOUND` | 존재하지 않거나 닫히거나 다시 열린 편집 대상. 새 대상 ID를 얻는다. |
| `REVISION_CONFLICT` | 기준 revision이 오래됨. 상태를 다시 읽고 변경 의도를 재평가한다. |
| `UNSUPPORTED_PARAM` | 허용 목록 밖의 키. 지원 키를 확인한다. |
| `INVALID_VALUE` | 값의 타입·유한성·범위·결합 조건 위반. 수정 후 요청한다. |
| `TOOL_DISABLED` | 대상 도구가 비활성화됨. 자동 활성화하지 않는다. |
| `BUSY` | 이미지 초기화, 미지원 편집 모드, 처리 중 요청, 큐·캐시 포화, 종료 중. 상태 확인 후 재시도할 수 있다. |
| `REQUEST_ID_CONFLICT` | 같은 ID의 다른 요청. 새로운 변경 의도에는 새 ID를 사용한다. |
| `INTERNAL_ERROR` | 적용 전 또는 적용 결과 불명의 내부 실패. 맹목적으로 재전송하지 않고 상태를 확인한다. |

`retryable`은 같은 기준 상태로 나중에 재시도할 수 있는지를 나타낸다. 결과 불명과 재전송 가능을 동일시하지 않는다. 렌더 실패는 반영한 파라미터를 취소하는 오류로 취급하지 않고, 해당 요청의 `previewStatus: FAILED`와 오류 상세로 보고한다.

## 8. 후속 구현의 검증 절차와 채택 조건

이번 작업에서는 다음 실행 검증을 수행하지 않았다. 후속 변경의 완료 조건으로 수행하고, 대상 OS·빌드 구성·이미지·설정과 결과를 남긴다.

| 검증 | 통과 조건 |
|---|---|
| 계약·입력 | 정상값, 경곗값, 알 수 없는 키, 비유한값, 과대 입력, 미인증을 확인한다. 잘못된 요청은 GUI 값·revision·히스토리를 바꾸지 않는다. |
| 수동 조작과 일치 | 같은 초기 상태에서 GUI로 설정한 경우와 외부에서 설정한 경우의 도구 활성 상태, 파라미터, 히스토리, 저장 프로필, 미리보기를 비교한다. 다른 노출 필드는 보존한다. |
| 동시 조작·수명 | 연속 요청, GUI 충돌, Undo에 해당하는 히스토리 이동, 100% 상세 창, 팬·줌, spot 편집 모드, 이미지 전환, 탭 닫기, 재연결, 종료 중 요청에서 충돌·데이터 레이스·다른 대상 적용·잘못된 완료 통지가 없다. |
| 스레드·메모리 | GUI 빌드에 적용 가능한 ThreadSanitizer와 AddressSanitizer를 별도 구성으로 사용하여 해당 경로를 반복한다. 미검증 경쟁을 기존 동작이라는 이유로 통과시키지 않는다. 종료 시 수신 중단 → GUI 대기 요청 무효화 → 처리 대기 → 리스너/편집 대상 해제를 확인한다. |
| 세대·흐름 제어 | `APPLIED`와 `READY`를 구분하고 이전 프레임을 최신 완료로 보고하지 않는다. 포화 시 `BUSY`, 재전송 중복 방지, 타임아웃 후 상태 조회, 캐시 기한을 확인한다. |
| 저장·CLI 회귀 | 기존 `.arp` 로드/저장, GUI 저장·재읽기, ART-cli의 동일 프로필 출력, BatchQueue·실행 중 내보내기의 값 고정을 확인한다. 이미지 허용 오차는 실행 전에 정한다. |
| 지연 | RAW 1~2장으로 최초/캐시 후, 축소/100%, HDR·노이즈 제거 유무를 나눈다. 수신 → GUI 반영 → Navigator 준비 → 주 Crop 준비를 p50/p95로 기록하고 합의한 응답 목표를 충족한다. 미측정 고정 fps는 제시하지 않는다. |
| OS·시작 방식 | 우선 macOS/Linux의 대상 환경에서 검증하고 일반 GUI와 단독 편집 시작 분기, 인스턴스 분리, 연결 권한을 확인한다. Windows를 포함한 지원 선언은 각 환경 확인 후에 한다. |

코어 변경 시 최소 확인 범위는 GUI·CLI 두 타깃의 아웃오브소스 빌드, 기존 프로필 회귀, GUI 실조작, 위 경쟁 검증이다. `-ffast-math`는 금지한다. 기존 수동 하네스만으로 계약·스레드 검증이 충분하다고 가정하지 않고 필요한 테스트 경계를 추가한다. 미달하면 허용 키·모드·OS를 명시적으로 좁히고 주 경로의 안전성과 화면 반영이 확인될 때까지 기능을 비활성화한다.

## 9. AGENTS.md 조건부 허용 문안

이 절은 갱신 제안이며 이번에 `AGENTS.md` 자체를 수정하지 않는다. 기존 코어 수정 금지 한 항목을 다음 문안으로 바꾸고 §6의 PPVERSION 해석을 함께 기재할 것을 제안한다.

> **파이프라인 기능을 위한 `rtengine/`·`rtgui/` 수정은 원칙적으로 금지한다. 다만 실행 중 GUI의 로컬 IPC 파라미터 조정에 한해, 승인된 설계와 검증 계획에 따라 조건부로 허용한다.**
>
> 허용 조건: 대상 기능, 허용 파라미터, 지원 OS·편집 모드, 변경 예정 지점, PPVERSION 판정, GUI/CLI 회귀 항목을 착수 전에 기록한다. 외부 입력 검증, GUI 메인루프 전달, 편집 대상과 revision 검사, 종료 시 수명 관리를 갖춘다. 초기 상태는 기능 비활성화로 한다.
>
> 허용 범위: `rtgui/`의 로컬 수신, GUI 명령 처리, 패널·히스토리·저장 상태 동기화, 편집기 열기·닫기 관리와 필요한 GUI 빌드 등록. `rtengine/`은 기존 단계의 안전한 파라미터 전달, 확인된 공유 상태의 동기화, 세대 번호를 포함한 프레임 통지에 필요한 최소 변경으로 한정한다. 기존 명시 파일에 대한 `main-cli.cc` 처리 예외는 유지한다.
>
> 유지하는 금지 사항: 실행 중 `ProcessingJob` 수정·재사용·destroy, 무보호 파라미터/이미지 버퍼 교환, `MINUPDATE`와 다른 이벤트 결합, 미검증 무효화 범위 축소, 헤드리스 상주화, 미인증 외부 네트워크 공개, vendored 코드 정리를 이 예외에 포함하지 않는다. 처리식·처리 순서·프로필 형식을 바꾸려면 이 예외를 확대 해석하지 않고 별도 설계와 PPVERSION 판정을 수행한다.
>
> 검증 절차: GUI·CLI 아웃오브소스 빌드, 기존 프로필 로드/저장/렌더 회귀, 수동 GUI 조작과 일치, 연속 요청·GUI 충돌·팬/줌·닫기/종료를 포함한 스레드/메모리 검사, 세대·오류 계약, 대상 OS의 화면 반영을 확인하고 결과를 기록한다. 하나라도 미검증이면 지원 범위를 한정하고 통과를 추측하여 보고하지 않는다. 공통 엔진 변경은 GUI와 CLI 양쪽의 회귀 결과를 필요로 한다.

이 문안의 채택과 후속 구현은 이번 문서 추가와 별도 변경으로 다룬다. 후보 B의 성립 판단은 GUI 상태 동기화와 경쟁 검증을 포함한 최소 구현이 위 조건을 충족하는 것을 전제로 한다.
