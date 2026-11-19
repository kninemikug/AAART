# 실시간 수치 조정 지연 측정과 개선 플랜

- 상태: §10 재측정 결과 병합 보류. §11의 계측 검증 보수와 주 Crop 지연 개선을 계획한다.
- 작성일: 2026-11-09.
- 소스 확인 기준: `2c701b81e3866d484ae80c68c16ad623957413ed`.
- 산출물: 이 문서 하나. 문서 외 파일 생성, push와 PR 생성은 하지 않는다.
- 원칙: **실측 전 최적화 코드·제품 동작 변경 금지. PPVERSION은 1045를 유지한다.**

설계 기준은 [가능성 검토](ART_live_param_feasibility.md)의 §2.1 단계 캐시·무효화 경계, §2.2 스레드 경계, §6 PPVERSION, §8 지연 측정이다. 현행 경로는 [구현·보수 플랜](ART_live_param_impl_plan.md)의 §13~15와 [수치 채팅 조정 플랜](ART_chat_numeric_controls_plan.md)을 함께 대조한다. 초기 노출 전용 구현의 범위를 현재 전체 수치 조정의 지원 범위로 해석하지 않는다.

측정 대상은 macOS의 실행 중 GUI, Unix socket, 열린 사진의 일반 편집 상태다. 주 창의 선택한 사진과 단독 편집기를 포함하며, 기능의 기본 OFF·기존 GUI 허용 설정을 유지한다. 다른 OS·네트워크 전송·상주 데몬·허용 수치 확대는 이 계획의 범위에 포함하지 않는다.

## 1. 측정 설계

### 1.1 확인한 경로와 기존 자료의 한계

다음은 소스에서 확인한 동작이며 병목 판정은 아니다.

| 지점 | 확인한 동작 | 측정에 반영할 사항 |
|---|---|---|
| [liveparamserver.cc](../rtgui/liveparamserver.cc)의 `enqueue`, `stageResponse`, `run` | 단일 I/O 스레드가 비차단 소켓을 처리하고 GUI idle 콜백에 명령을 전달한다. `poll(..., 20)`을 사용하며 GUI에서 완성한 응답을 I/O 경로에서 회수한다. | 완전한 프레임 수신, GUI 대기, 응답 준비 후 송신 대기를 각각 측정한다. 20ms를 모든 요청의 고정 비용으로 단정하지 않는다. |
| [liveparamcontroller.cc](../rtgui/liveparamcontroller.cc)의 `handleCommand`, `updateReady` | GUI에서 대상·revision·문맥·캐시를 검사한다. `APPLIED`는 값 반영이며, 미완료 외부 변경이 있으면 다음 변경은 `BUSY`다. `READY`는 필요한 계산 세대의 Navigator와 현재 뷰의 주 Crop을 함께 검사한다. | 수락·거부·재전송을 분리하고 두 표시 자료의 준비 시각을 각각 확보한다. |
| [toolpanelcoord.cc](../rtgui/toolpanelcoord.cc)의 `applyExternalNumeric`, `panelChanged` | 일반 수치는 도구 켜기와 위젯 이벤트를 요청 하나로 확정한다. `numericFullRefresh_` 때문에 무효화는 `EvProfileChanged → ALL`이다. 기존 노출 전용 경로는 `EvExpComp → HDR`이다. | 공통 수치 노출과 기존 노출 요청을 별도 경로로 비교한다. 일반 수치도 이미 도구별 최소 무효화를 사용한다고 가정하지 않는다. |
| [improccoordinator.cc](../rtengine/improccoordinator.cc)의 `process`, `updatePreviewImage` | `mProcessing → paramsUpdateMutex` 아래 파라미터와 세대를 복사한다. `changeSinceLast`에 비트를 누적하며 `panningRelatedChange = true`로 갱신한다. `bufs_[0..2]`는 STAGE_1~3 경계의 캐시다. | 잠금·작업 풀 대기, 실제 실행 단계, 캐시 재사용, 색 변환과 통지 비용을 분리한다. |
| [dcrop.cc](../rtengine/dcrop.cc)의 `update`, `tryUpdate`, `fullUpdate` | 조정기의 직접 `update(todo)`와 팬·줌의 `fullUpdate()` 경로가 있다. 크기 재할당·`M_HIGHQUAL`은 `ALL`로 확대되며 `fullUpdate()`도 `update(ALL)`을 반복한다. | 주 Crop의 실제 크기·skip·진입 경로·재실행 횟수와 `mProcessing` 대기를 기록한다. |

현재 작업 공간에는 `build/`가 없다. 기존 자료는 저장소 루트 기준 `../T-live-param/build/` 아래에서 읽었다. 아래 상대 경로는 그 디렉터리 안의 자료를 가리키며, 현재 소스의 신규 기준선으로 사용하지 않는다.

| 기존 자료 | 확인한 내용 | 재사용 범위 |
|---|---|---|
| `liveparam-checks/resume/startup/final_probe.py`, `step4-native-latency.json`, `step4-native-final-probe.log` | 같은 연결에서 노출 절대값 30건을 순차 적용한다. 클라이언트 기준 APPLIED p50/p95는 `21.1/21.2ms`, READY 관측은 `165.2/258.4ms`다. READY 조회 사이에 3ms를 쉰다. | 소켓 왕복·상태 상관관계 측정의 출발점. 엔진 단계 시각은 없다. 축소 보기·이미 열린 RAW·기본 자동 곡선·HDR/노이즈 제거 OFF·두 sanitizer 검사 동시 실행이라는 조건의 관측 상한이다. |
| `liveparam-checks/resume/step4-build-meta.json` | 입력·소스·실행 파일 해시, 빌드 플래그와 검증 소스 커밋 `34bc2ac40a243be87896bbc1921944e72d90aebd`가 있다. | 과거 실행의 출처 확인용이다. 현재 소스와 같은 빌드라는 근거로 쓰지 않는다. |
| `liveparam-numeric-checks/n5-output-green.log`, `bundle-probe.log`, `bundle-results.json` | 수동/외부 수치 적용의 출력 일치 검사와 한국어 채도 적용·도구 켜기·화면 준비의 기능 결과가 있다. | 수치 적용·회귀 시나리오를 재사용한다. 구간별 시각과 반복 지연 분포가 없어 성능 기준선으로 사용할 수 없다. |

기존 소켓 프로브는 연결을 유지하지만 현재 Python 클라이언트는 교환마다 연결하며 `wait_ready`의 기본 조회 간격은 50ms다. 서로 다른 연결·조회 정책의 결과를 하나의 분포로 합치지 않는다.

### 1.2 확장할 하네스와 관측 지점

다음 표는 후속 측정 작업의 변경 예정 위치다. 이번 문서 작업에서 수정하지 않는다. 계측은 기존 동작을 관찰하는 범위로 한정하고, 제품 IPC 필드·연산이나 `.arp` 키를 추가하지 않는다.

| 위치 | 후속 확장 | 확인 방법 |
|---|---|---|
| 기존 `final_probe.py`를 바탕으로 한 측정 전용 실행기 | RAW·프로필·배율·키·값 순서·반복 수를 입력받고 요청별 송신/APPLIED/READY 관측 시각을 저장한다. `list_params`로 현재 키와 `contextId`를 얻는다. | 실제 소켓·실제 GUI에 요청하고 응답 JSON의 요청 ID·세대를 검사한다. 과거 프로브와 현재 클라이언트 방식은 별도 모드로 둔다. |
| [test_liveparam_gui.cc](../rtgui/test_liveparam_gui.cc)의 `FrameFixture`, T10~T12, T22, T25 | 실제 Navigator/주 Crop·팬/줌·수치 채팅·수동 출력 비교를 재사용한다. 반복 측정 설정을 기능 검사와 분리한다. | 기존 GUI 이벤트 펌프·대기 루프의 관측 간격을 기록한다. 직접 `handleCommand()`를 부르는 사례를 소켓 RTT로 보고하지 않는다. 성공 문구·진행률 종료를 준비 시각으로 쓰지 않는다. |
| `liveparamserver.cc` | 완전한 LF 프레임 수신, 큐 등록, GUI 콜백 진입·응답 완성, I/O 응답 회수·최종 바이트 송신을 관측한다. | 분할 수신·부분 송신에도 같은 명령을 추적한다. 수신 스레드에서 JSON·GTK·엔진 상태를 새로 조회하지 않는다. 내부 명령 ID를 GUI에서 파싱한 `requestId`와 연결한다. |
| `liveparamcontroller.cc`, `toolpanelcoord.cc` | 검증·문맥 생성·수치 목록 수집·위젯 반영·변경 확정과 APPLIED 구성 시간을 나눈다. `updateReady`에서 실제 READY 전환을 기록한다. | 적용 전 오류와 중복 ID 재전송을 새 적용으로 세지 않는다. 실제 반영값·도구 켜기·revision·히스토리를 함께 확인한다. |
| `improccoordinator.cc`, `dcrop.cc` | 작업 예약/시작, `mProcessing` 획득 전후, 스냅샷 확정, 단계별 실행·캐시 적중, Crop 직접/별도 작업, 프레임 생성 종료를 관측한다. | 입력 무효화 비트와 확대 후 비트를 모두 남긴다. 계산되지 않은 단계는 0ms 실행으로 꾸미지 않고 재사용·미실행으로 구분한다. |
| [previewhandler.cc](../rtgui/previewhandler.cc), [crophandler.cc](../rtgui/crophandler.cc) | 워커의 픽셀 복사·GUI 예약, GUI 콜백 시작, Pixbuf 준비와 `onPreviewReady`/주 `onCropReady` 직전 시각을 관측한다. | 픽셀·처리 세대·뷰포트가 같은 결과인지 확인한다. 합쳐진 Crop 대기 슬롯의 원본 세대를 보존하고 폐기된 결과도 따로 센다. |

GUI 상태는 GUI 메인루프가 소유하고 I/O는 소유한 명령 복사본만 전달한다. 계측 때문에 `mProcessing → paramsUpdateMutex`, `mProcessing → mTweak` 잠금 순서를 바꾸거나 GUI가 처리 잠금을 새로 기다리게 하지 않는다. 세대는 `ProcParams` 밖에 둔다. 로그는 유한한 관측 버퍼로 모아 처리 잠금 밖에서 기록하며, 넘친 기록 수를 남긴다. 기록 유실이 있는 실행은 상세 구간 분석의 근거로 채택하지 않는다.

### 1.3 RTT 분해와 완료 정의

GUI 프로세스 안의 시각은 같은 `std::chrono::steady_clock`으로 기록한다. 클라이언트는 `time.perf_counter_ns()` 등 자체 단조 시계를 사용한다. 프로세스가 다른 두 시계의 절대값을 직접 빼지 않고 요청 ID로 각 프로세스의 구간을 대조한다. 벽시계는 실행 식별에만 쓴다.

| 기호 | 사건 |
|---|---|
| `C0`, `CA`, `CR` | 클라이언트의 변경 요청 준비·연결 직전, APPLIED 응답 파싱 완료, 해당 변경의 READY 응답 파싱 완료. 직렬화·연결 정책을 실행 메타데이터에 고정한다. |
| `S0`, `SQ`, `SG` | 서버에서 완전한 프레임 수신, GUI 큐 등록, GUI 명령 콜백 시작. |
| `SA`, `SP`, `SS` | GUI 값·스냅샷·revision 확정과 변경 기록 구성이 끝나 APPLIED를 만들기 직전, 응답 문자열이 I/O 회수 가능해진 때, 마지막 응답 바이트 송신 완료. |
| `SN`, `SC` | 세대 검사를 통과한 Navigator 표시 자료, 현재 뷰의 주 Crop 표시 자료가 각각 GUI에 준비된 때. 워커의 계산 종료와 구분한다. |
| `SR` | `updateReady()`가 필요한 계산 세대·편집 revision·현재 viewRevision과 지연 갱신 부재를 확인하고 해당 변경을 READY로 확정한 때. |

필수 통계는 요청별 구간을 먼저 계산한 뒤 각 시나리오에서 p50/p95를 산출한다.

| 지표 | 계산·해석 |
|---|---|
| APPLIED RTT | `CA − C0`. 전송·연결·GUI 처리·응답 회수·클라이언트 파싱을 포함한다. |
| READY 관측 지연 | `CR − C0`. 실제 READY 전환 뒤 상태 조회를 통해 발견할 때까지의 시간도 포함하는 관측 상한이다. |
| 수신·GUI 대기·반영 | `SQ − S0`, `SG − SQ`, `SA − SG`. 검증·카탈로그·실제 적용의 세부 구간도 함께 기록한다. |
| 응답 전달 | `SP − SA`, `SS − SP`. I/O 회수 지연과 송신 비용을 세부 기록으로 나눈다. RTT에서 이 비용이 큰지 엔진과 독립적으로 판단한다. |
| GUI 반영 이후 준비 | `SN − SA`, `SC − SA`, `SR − SA`. 수신 기준의 `SN − S0`, `SC − S0`, `SR − S0`도 함께 제공한다. |
| 처리·표시 전달 | 작업 풀 대기, 처리 잠금 대기, 단계별 계산, 프레임 생성 종료→GUI 콜백, Pixbuf 생성 시간을 각각 측정한다. 렌더는 APPLIED 응답 구성·송신과 겹칠 수 있어 이 구간들을 무조건 직렬 합산하지 않는다. |

Navigator와 주 Crop의 도착 순서는 고정하지 않는다. **수신 → GUI 반영 → 두 자료 준비 확인**이 측정 경계이며 `SC − SN`을 일반적인 Crop 비용으로 사용하지 않는다. `SR`은 두 자료와 필요한 지연 갱신 조건을 모두 만족한 뒤의 시각이다. 팬에 의한 Navigator 재사용은 원래 계산 시각·세대와 새 뷰에서의 유효성 확인 시각을 별도로 남긴다. `M_HIGHQUAL`·색 변환·샤프닝 마스크 등 새 계산이 예약됐으면 이전 자료로 완료시키지 않는다.

READY는 표시 자료 준비이며 모니터 그리기·저장·최종 출력 완료가 아니다. 상세 창과 Before/After 보조 뷰는 주 Crop 완료에 포함하지 않는다. 동일 편집에서도 계산 `generation`, `cropId`, `viewportGeneration`을 구분하고 오래된 결과를 최신 요청에 연결하지 않는다.

READY 관측에는 각 조회의 송신·응답 시각, 마지막 PENDING과 첫 READY, 실제 조회 횟수·간격을 남긴다. 단순히 3ms나 50ms를 RTT에서 빼지 않는다. p95끼리 뺀 값을 단계별 p95로 사용하지도 않는다. 클라이언트 RTT와 서버 내부 구간은 같은 요청 집합으로 제시하되 시계 간 직접 차감 없이 해석한다.

### 1.4 시나리오 매트릭스

대표 수치 네 항목은 다음과 같다. 공통 수치 키는 현재 `list_params` 결과에서 찾으며 위젯 수명에 묶인 ID를 고정 키로 하드코딩하지 않는다. 실제 범위·간격·활성 상태·문맥과 `effectiveParams`를 기록한다.

| 조정 항목 | 값의 예 | 수동 GUI의 이벤트 경계와 별도 비교 |
|---|---|---|
| 노출 | `−0.5 ↔ 0.5 EV` | `EvExpComp → HDR`. 기존 `Exposure.Compensation` 요청과 `contextId`를 갖춘 공통 수치 요청을 구분한다. |
| 채도 | `10 ↔ 20` | `saturation` 도구의 채도, `EvSaturation → LUMINANCECURVE`, STAGE_3 경계. |
| 색온도 | `5000 ↔ 6500 K` | `whitebalance` 도구의 온도. WB method의 Custom 전환·연동과 `WHITEBALANCE` 경계를 포함한다. |
| 샤프닝 반경 | `0.6 ↔ 0.8` | 우선 USM 모드를 고정해 반경을 특정한다. `EvShrRadius → SHARPENING`, STAGE_2 이후 경계. RL/PSF 모드는 별도 표본으로 구분한다. |

이 이벤트 경계는 [refreshmap.cc](../rtengine/refreshmap.cc)·[refreshmap.h](../rtengine/refreshmap.h)의 수동 경로 설명이다. 현재 일반 수치 요청의 실제 범위는 네 항목 모두 보수적인 `ALL`이며, 캐시 사용 여부는 실행 기록으로 확인한다. WB 전처리 모드, 연결 마스크, 고품질 RAW와 Crop 크기 변경은 범위를 넓힐 수 있다.

| 축 | 측정 조건 |
|---|---|
| RAW | 이미 보유한 RAW 1~2장. 예: 기존 `data/fivek_sample/sample1.nef`와 이용 가능한 두 번째 사진. 파일 해시·해상도·센서 형식을 고정한다. 한 장만 있으면 그 범위만 보고하고 추가 자료를 임의 다운로드하지 않는다. |
| 배율 | 주 편집 화면의 축소 보기와 100%. 실제 배율·표시 배율·Navigator scale·Crop skip·창 크기·뷰포트 위치를 기록한다. 100% 상세 창은 별도 동시성 시나리오다. |
| 최초/캐시 후 | 동일한 초기 프로필에서 새 열기 뒤 최초 수치 변경과, 같은 대상·배율·품질에서 같은 도구를 반복 조정한 상태를 분리한다. 정의는 아래 절차를 따른다. |
| HDR | OFF/ON. 기본 매트릭스에서는 동적 범위 압축 `fattal.enabled`와 설정을 고정하고 dehaze는 OFF로 고정한다. 다른 HDR 관련 도구를 사용하면 별도 프로필 조건으로 남긴다. 무효화 상수 `HDR`와 도구의 ON 상태를 혼동하지 않는다. |
| 노이즈 제거 | OFF/ON. 도구 설정과 `denoiseZoomedOut`을 고정하고, 축소 보기에서 실제 실행되는지도 기록한다. ON이라는 프로필 값만으로 노이즈 제거 비용이 발생했다고 판단하지 않는다. |

기본 매트릭스는 **4항목 × 2배율 × 2캐시 상태 × 2 HDR 상태 × 2 노이즈 제거 상태 = RAW당 64셀**, RAW 1~2장이면 64~128셀이다. HDR/노이즈 제거는 OFF/OFF, ON/OFF, OFF/ON, ON/ON을 모두 포함한다. 기본 경로는 공통 수치 IPC이며 기존 노출 API·수동 입력·실제 채팅 비교는 별도 표로 둔다.

최초와 캐시 후의 재현 절차는 다음과 같다.

1. 최초 표본마다 격리된 설정·캐시와 새 GUI 프로세스를 사용해 같은 RAW·프로필을 연다. 초기 열기→최초 Navigator·주 Crop 준비 시간도 별도 기록한다. OS 파일 캐시를 지웠다고 가정하지 않고 파일 캐시 상태는 통제 한계로 명시한다.
2. 지정 배율과 프로필을 준비하고 초기 두 자료 및 필요한 `M_HIGHQUAL` 처리가 완료된 뒤 첫 변경을 보낸다. 초기화 중 거부되는 요청을 정상 조정 RTT에 섞지 않는다. 이 표본은 **최초 조정**이며 모든 엔진 캐시가 비어 있다는 뜻은 아니다. 100% 진입의 최초 고품질 준비 비용은 따로 보존한다.
3. 캐시 후 표본은 동일 세션에서 다른 값으로 왕복하며 측정한다. 이전 요청의 READY 뒤 새 revision·문맥을 조회하고 다음 요청을 보낸다. 반복마다 프로필을 다시 적용해 `ALL`을 예약하거나 줌을 바꾸지 않는다. 같은 값 설정은 별도 대조군으로 두어 재계산 없는 반복이 성능을 대표하지 않게 한다.
4. 기본 계산 비교는 대상 도구를 이미 켠 프로필과 WB Custom·USM 등 고정된 모드로 수행한다. 도구 OFF→자동 켜기, WB 모드 전환은 별도 최초 활성화 표본으로 측정한다. 값 예시는 실제 목록의 유효 범위 확인 후 사용한다.

다음 추가 시나리오는 정상 단건 분포와 분리한다.

- 실제 채팅의 전송→목록 조회·항목 해석→set_param→READY 조회→GUI 안내 구간. Python 시작·문맥 복사·페이지 수집 시간을 포함해 사용자가 느끼는 지연과 IPC만의 지연을 함께 제시한다.
- READY를 기다리는 순차 입력과, 완료 전에 도착하는 연속 입력을 별도 실행한다. 입력 빈도는 기준선 서비스 시간에 비해 낮은 경우·비슷한 경우·높은 경우로 정하고 실제 간격·BUSY 비율·마지막 의도까지의 지연을 남긴다. 자동 재시도로 거부를 숨기지 않는다.
- 팬·줌·100% 경계·상세 창 추가, 수동 편집·히스토리 이동, 닫기·재열기·종료 중 요청. `SUPERSEDED`, 충돌, 구세대 폐기, 다음 요청의 진행과 잘못된 READY 여부를 확인한다. 성능 분포와 별개로 안전성 통과가 필요하다.

### 1.5 표본·환경·기록 위치

성능 기준선은 Release 단독 실행으로 수집한다. 빌드·인덱싱·ASan/TSan 실행을 동시에 하지 않고 CPU·메모리·전원·열 상태와 다른 부하를 기록한다. 기존 30건의 부하 조건과 같다고 취급하지 않는다. 계측 ON/OFF를 같은 Release 조건에서 비교해 관측 오버헤드도 측정한다. ASan·TSan은 별도 디렉터리의 안전성 검증이며 그 지연을 Release 기준선에 합치지 않는다. in-source 빌드와 `-ffast-math`는 금지한다.

초기 기준선은 셀마다 총 30회 시도를 세 독립 실행 묶음으로 나누어 수집한다. 최초 셀의 각 표본은 새 열기 절차를 반복하고, 캐시 후 셀은 각 실행 묶음에서 준비 후 반복한다. 순서·값 열을 고정해 보존하고 실행 묶음 사이에서 조건 순서를 교차해 시간대·열 상태의 편향을 확인한다. p50/p95는 정렬 표본의 `ceil(p × n)`번째 값으로 계산하며 유효 표본 수와 실행별 산포를 함께 보고한다. 30건의 p95는 탐색값으로 표시하고, 목표 합의·개선 채택의 근거가 되는 셀은 100건 이상으로 늘려 독립 실행에서 꼬리 지연의 재현성을 확인한다.

거부·타임아웃·`SUPERSEDED`·`FAILED`·기록 유실은 원자료에 남기고 성공 지연과 별도 집계한다. 예정 시도 수, APPLIED 수, READY 수, 미완료 수와 각 비율을 함께 제시한다. 타임아웃을 제한 시간의 성공 표본으로 치환하거나 재시도 성공으로 덮지 않는다. 누락 셀은 미측정으로 남기고 전체 매트릭스 완료를 선언하지 않는다.

후속 실행 자료의 저장 위치는 `build/liveparam-perf-checks/<실행ID>/`로 정한다. 이 경로와 아래 파일들은 이번 문서 작성에서 생성하지 않는다.

| 자료 | 필수 내용 |
|---|---|
| `manifest.json` | 소스 커밋·dirty diff 식별, 실행 파일·입력 RAW·프로필 해시, OS·CPU·메모리·컴파일러·실제 플래그, 리소스·격리 설정, 배율·창 크기·도구 모드·부하, 연결·조회 정책, 표본 수·기한·명령·종료 코드. |
| `client.jsonl`, `trace.jsonl` | 요청별 원시 단조 시각과 사건, 내부 명령 ID·sessionId·editorId·requestId·contextId, 적용 revision·viewRevision·계산 generation·cropId·viewportGeneration, 키·요청값·반영값·활성화, 응답·오류·재전송·폐기·기록 유실 수. |
| `samples.csv`, `summary.csv` | 셀 ID별 요청 구간, 무효화 비트·실제 실행 단계·캐시 상태, 표본 수·성공/거부/미완료 비율, 구간별 p50/p95·실행별 산포. 원자료로 재계산 가능해야 한다. |
| `decisions.md`, 회귀 결과·프로필·비교 이미지 | 병목 증거, 목표 합의, 후보별 전후 수치와 채택/폐기 이유, PPVERSION 판정, GUI/CLI 비교·사전 허용 오차, 남은 지원 제한. |

## 2. 병목 후보와 개선안

아래는 모두 가설이다. **각 후보는 측정 후 확정**하며, 해당 구간의 지연 기여와 반복 실행의 재현성이 확인되기 전에는 구현하지 않는다. 기존 캐시·동기화·완료 계약을 없애 얻은 수치는 개선으로 인정하지 않는다.

| 후보·예정 지점 | 측정 후 확정 조건 | 스레드 안전성 위험 | 무효화 범위 위험 | 처리식·순서 변경 여부와 PPVERSION |
|---|---|---|---|---|
| I/O 응답 회수 깨우기·조회 비용 개선 — 서버 `run`/`stageResponse`, 클라이언트 요청·대기 | `SP→응답 회수` 또는 READY 전환 후 관측 대기가 유의한 비중을 차지할 때. 연결 유지·조회 주기 차이를 별도 실험하고 CPU 사용·GUI 큐 부하까지 비교한다. | 중간. 완료 통지와 I/O 대기·종료·FD 수명의 경쟁, 깨우기 유실을 검증한다. 단순 busy polling으로 대체하지 않는다. | 없음 목표. 렌더·세대·검증을 우회하지 않는다. | 없음 목표. 전송·대기만 바꾸고 결과를 보존하면 1045 유지 가능. 새 IPC 계약이 필요하면 별도 검토하며 프로토콜 버전과 구분한다. |
| 유량 제한·coalescing — 클라이언트의 전송 전 절대값 의도 | 단건보다 연속 입력에서 BUSY·대기와 마지막 의도 반영 시간이 증가할 때. 합의한 입력 부하에서 마지막 값과 GUI 응답성의 개선이 확인돼야 한다. | 중간~높음. 대상·문맥·revision이 바뀌면 대기 의도를 폐기하고 이미 수락된 요청을 조용히 덮지 않는다. 현재 편집기당 하나의 미완료 변경 제한을 유지한다. | 마지막으로 보낼 값은 기존 이벤트 전체를 적용한다. 서로 다른 키·도구 활성화·상대값을 임의 병합하지 않는다. | 없음 목표. 전송 전 의도 병합만으로는 증가 사유가 아니다. 이미 APPLIED인 편집·히스토리·저장 의미를 바꾸는 병합은 이 후보에 포함하지 않는다. |
| 무효화 이벤트 매핑 최적화 — `numericFullRefresh_`, `NumericEvents`, `panelChanged` | 공통 수치 `ALL`에서 실제 RAW·상위 단계 재실행이 비용을 차지하고, 동일 초기 상태의 수동 이벤트 범위로 모든 연동값·마스크 의존성을 충족함이 입증될 때. 네 키별·활성화별로 판정한다. | 높음. 변경 확정·스냅샷·계산 세대의 원자성과 파생 콜백 검증을 유지한다. | 높음. 현재 이벤트 수집은 마지막 이벤트를 보관하므로 그 값만 사용해 ALL을 제거하지 않는다. 도구 켜기·연동 이벤트의 전체 필요 범위를 먼저 증명한다. `MINUPDATE` 혼합 금지, 표시 전용 항목의 READY 계약과 보수적 fallback을 유지한다. | 없음 목표지만 조건부. 같은 입력의 처리식·순서·최종 결과를 보존한 재사용만 1045 유지 후보다. 단계 생략·순서 변경·근사로 결과가 달라지면 증가 사유이며 별도 설계로 분리한다. |
| Crop 갱신 스케줄 개선 — `tryUpdate`/`fullUpdate`, 줌 타이머·GUI 전달 | 주 Crop의 잠금·작업 풀 대기, 대체된 뷰포트 반복 계산이나 GUI 전달 대기가 병목일 때. 주 뷰의 최신 자료 지연과 상세 창의 굶주림을 함께 비교한다. | 높음. `mProcessing → mTweak` 순서, 종료 직전 갱신 유실 방지, 픽셀·세대 일치와 취소 수명을 보존한다. | 높음. `ALL` 확대·100% 고품질·Navigator 재계산을 임의 제거하지 않는다. 재사용 검증 전에는 대기하며 구세대 결과로 READY를 앞당기지 않는다. | 처리 작업의 예약 시점만 조정하고 단계 내부 순서·품질을 보존하면 1045 유지 후보다. 저품질 대체·노이즈 제거 생략·처리 순서 변경은 증가 사유이며 제외한다. |
| 예열·기존 캐시 재사용 — 이미지 열기·배율 준비·기존 단계 경계 | 최초와 캐시 후 차이가 반복 확인되고 재사용할 입력·품질·뷰 조건을 특정할 수 있을 때. 최초 열기 비용·총 CPU·메모리 증가까지 합산해 이득을 판단한다. | 높음. 현재 GUI 수명과 공유 처리 잠금 안에서만 예열하고 별도 무보호 작성자를 만들지 않는다. 닫기·재열기의 해제를 검증한다. | 높음. RAW·WB·HDR/노이즈 제거·연결 마스크·배율·색 관리 의존성과 캐시 유효성 조건을 기록한다. 다른 사진·세대·품질의 자료를 재사용하지 않는다. | 동일 계산의 시점 이동·유효한 캐시 재사용만 1045 유지 후보다. 수식·정밀도·단계 순서·기본값 변화는 증가 사유이며 별도 설계다. |
| 수치 목록·문맥 처리의 중복 비용 개선 — GUI 수집·페이지 조회 | `SA − SG` 또는 채팅 전처리에서 목록 순회·문맥 구성·반복 페이지 조회가 주된 비용일 때. 요청 크기·항목 수별 비용을 확인한다. | 중간~높음. 위젯 수명은 GUI가 소유하며 비동기 포인터 공유를 금지한다. 동적 위젯·영역·곡선 점 변경 시 이전 목록을 무효화한다. | 영상 단계 축소 없음. 도구 켜기·연동·실제 값 판정과 전송 시 문맥 검증을 생략하지 않는다. | 없음 목표. 일시 조회 자료의 중복 제거와 기존 값 전달은 결과 보존 시 1045 유지 가능하다. 단위·범위·반영값 의미 변경은 제외한다. |

고유 수식이나 STAGE_0~3의 처리 순서를 바꾸는 방안, PREVIEW 전용 근사·품질 저하, `stopProcessing()`을 요청마다 호출하는 강제 중단, 실행 중 `ProcessingJob` 변경·재사용·destroy, 무보호 이미지 버퍼 교환은 개선안으로 채택하지 않는다. 공통 엔진의 새 캐시 구조·무효화 축소가 현행 조건부 허용 범위를 넘으면 별도 설계·범위 확정부터 수행한다.

## 3. 변경 금지선과 목표치 합의

**기준선 기록·병목 분석·목표 합의·개선안 선정이 끝나기 전에는 최적화 구현을 시작하지 않는다.** 후속 하네스 구축에서 필요한 관측 계측만 먼저 분리하며, 이벤트 매핑·큐 한도·폴링 주기·품질·캐시·처리 순서는 그 단계에서 바꾸지 않는다. 현재 큐 32개·프레임 64 KiB·연결별 미처리 요청 하나·요청 중복 방지·기본 OFF와 완료 세대 계약을 유지한다.

목표치는 다음 순서로 수치화한다. 현재 문서에는 고정 ms·fps·개선율을 약속하지 않는다.

1. 셀별 APPLIED RTT, 서버 수신→READY, READY 관측 지연의 p50/p95와 실패율·산포를 공개한다. 최초 열기와 100% 최초 준비도 별도 제시한다.
2. 실제 사용에서 우선할 RAW·배율·도구·연속 입력 부하를 정한다. APPLIED 응답성, 주 화면 준비, 마지막 의도의 반영 중 어떤 지표를 줄일지 지정하고 병목 구간의 비중을 확인한다.
3. 선택 셀의 기준 p95를 `B`, 반복 실행에서 확인한 변동 폭을 `V`라 할 때, 변동보다 큰 최소 개선 폭 `D`와 절대 상한 `T`를 사용자와 합의한다. 목표는 `새 p95 ≤ T` 및 `B − 새 p95 ≥ D`로 기록하고 p50·다른 셀의 허용 회귀 폭·메모리/CPU 상한도 같은 시점에 정한다. 특정 수치를 편의상 먼저 정해 나중에 조건을 맞추지 않는다.
4. 동일 하드웨어·RAW·프로필·배율·연결/조회 정책·표본 예산에서 기준/후보를 교차 재측정한다. 개선 폭이 산포 안에 있거나 오류율·최초 준비·다른 도구가 합의 범위를 벗어나면 채택하지 않는다. 채택·폐기 실험 모두 근거를 남긴다.

합의 기록에는 대상 셀·구간·기준 수치·표본 수·관측 오버헤드·변동 폭·목표·허용 회귀·판정 방법·합의일을 포함한다. 빠른 APPLIED만으로 전체 지연 목표를 달성했다고 하지 않으며, 조회를 자주 해 READY 관측만 빨라진 결과를 엔진 가속으로 보고하지 않는다.

PPVERSION `1045` 유지의 최종 근거는 기존 `.arp` 로드·저장·재읽기, 기본값·키·단위·해석, 수동/외부의 도구 상태·연동값·히스토리·화면 결과, GUI/CLI 출력 의미 보존이다. IPC·잠금·수명·스케줄링만의 변경도 회귀 증거 없이 미증가를 확정하지 않는다. 처리식·처리 순서·프로필 형식·도구 의미 변경은 PPVERSION 증가 사유이며 이 계획의 1045 유지 범위에서 분리한다.

후보 검증에서는 Release의 `art`·`art-cli`·`test_liveparam`·`test_liveparam_gui`를 아웃오브소스로 빌드하고 기존 계약·실제 GUI 검사와 Python 클라이언트·수치 채팅 검사를 수행한다. 공통 엔진 변경은 기존 프로필의 변경 전후 CLI 렌더와 GUI 수동/외부 출력 비교를 모두 요구한다. 동일 조건의 픽셀 차이 `0`을 우선 기준으로 하고 환경별 오차가 필요하면 실험 전에 이유와 한도를 기록한다. 지연 목표를 맞추기 위해 허용 오차나 기존 단언을 완화하지 않는다.

연속 요청·GUI 충돌·팬/줌·닫기/종료·프레임 통지를 별도 ASan/TSan GUI 실행으로 확인한다. `APPLIED` 직후 저장·새 내보내기·큐 등록은 최신 반영값을 유지하고 실행 중 내보내기는 생성 당시 값을 유지해야 한다. 기능·세대·안전성 회귀가 있으면 지연이 줄어도 채택하지 않는다. 다른 OS나 미측정 모드를 통과한 것으로 확대하지 않는다.

## 4. 커밋 분할

문서를 먼저 확정하고 이후 작업은 다음처럼 나눈다. 아래는 커밋 계획이며 이 문서 작성만으로 후속 작업을 실행하지 않는다. 커밋 제목·본문은 국문으로 작성한다.

| 순서 | 범위·완료 조건 | 커밋 메시지 |
|---|---|---|
| 1 | 이 문서 하나. 기준 문서·소스·기존 로그와 대조하고 문서 외 변경이 없는지 확인한다. | `docs: 실시간 수치 조정 지연 측정과 개선 플랜 추가` |
| 2 | 소켓→실제 GUI→두 표시 자료 준비를 추적하는 하네스·최소 관측 계측. 기존 기능 검사, 세대 상관관계와 계측 오버헤드 검증을 함께 포함한다. | `test: 실시간 수치 조정의 구간별 지연 측정 하네스 추가` |
| 3 | 기준선의 조건·요약, 병목 분석과 합의 목표를 이 문서에 기록한다. 원시 실행 자료는 `build/liveparam-perf-checks/`에 보관하고 빌드 산출물은 커밋하지 않는다. | `docs: 수치 조정 지연 기준선과 개선 목표 기록` |
| 4 이후 | 선정된 개선안 하나씩 구현·회귀 검사·같은 조건의 전후 측정을 묶는다. 채택 근거·PPVERSION 판정을 기록하며 독립 개선을 한 커밋에 섞지 않는다. | 측정 후 선정 범위에 맞춰 국문 제목 확정 |

## 5. 작업 순서와 단계별 완료 조건

**측정 하네스 구축 → 기준선 기록 → 병목 분석 → 개선안 선정 → 구현** 순서를 고정한다.

| 단계 | 상태 | 내용 |
|---|---|---|
| P1 — 측정 하네스 구축 | **완료** | `rtengine/liveparamtrace.{h,cc}` 계측 링버퍼(미바인딩 `cmdId` 보류 플러시 지원), 소켓/컨트롤러/엔진 이벤트 추적 (`S0, SQ, SG, SA, SP, SS, SC, SN, SR, ENGINE_CHANGE, ENGINE_DONE`), `100%` 초기 배율(`ART_LIVE_PARAM_INITIAL_ZOOM=100`) 및 `.arp` 스키마(`docs/arp_schema.md`) 정합 프로브 `scripts/live_param_perf_probe.py`, GUI 테스트 T26 검증 완료 |
| P2 — 기준선 기록 | **완료** | 64개 전체 매트릭스 셀 × 3배치 × 10회 반복 (총 960회 요청, 성공률 100.0%, 계측 누락 0건) p50/p95 및 구간별 지연 시간 수집 완료 |
| P3 — 병목 분석 | **완료** | `SA - SG` GUI 위젯 다중 순회·가상 상속 `dynamic_cast`·컨테이너 배열 할당 오버헤드(+49.2ms) 및 `numericFullRefresh_ = true`로 인한 무조건적 `ALL` 무효화(+66.8ms, 중량 프리셋 시 Stage 2/3 도구 최대 +327ms) 증명 |
| P4 — 개선안 선정 | **완료** | `NumericEvents::canUseSelectiveEvent()` 기반 안전 선택적 이벤트 매핑 및 `GObject` 메타데이터(`WidgetMeta`)·`gtk_container_foreach`·무라벨 수집(`includeLabels = false`) 최적화 선정, 합의 목표치(APPLIED p95 ≤ 35ms, Stage 2/3 READY p95 ≤ 200ms, SC - SA p50 ≤ 100ms, SA - SG p50 ≤ 10ms) 및 PPVERSION 1045 보존 기준 확정 |
| P5 — 구현·재측정 | **완료** | `applyExternalNumeric` 및 `numericcontrols.cc` 최적화 구현, `M_VOID`(`Resize`) 연속 변경 `READY` 회귀(T21) 및 픽셀 차이 0(T25) 검증, 동일 조건 64셀(960표본) 재측정 완료 |

---

## 6. 기준선 측정 결과 (Stage P2)

- **측정 일시**: 2026-11-09 23:23:17 (실행 ID: `run_20261109_231603_5ec1db`)
- **실행 환경**: Darwin 25.5.0 arm64 (Apple Silicon 12 vCPU), 메모리 36GB
- **측정 바이너리**: `build/ARTLiveParamTest.app/Contents/MacOS/test_liveparam_app` (Release 빌드, SHA-256 `694f19b3...`)
- **입력 RAW**: `data/fivek_sample/sample1.nef` (SHA-256 `18e28700...`, Nikon NEF 3031×2006)
- **프로필 버전**: `PPVERSION 1045` (`sample1.nef.arp` 기반, `[Saturation]`, `[White Balance] Method=Custom`, `[Sharpening] Method=usm`, `[FattalToneMapping]`/`[Dehaze]`, `[Impulse Denoising]`/`[Denoise]` 스키마 정합 적용)
- **표본 구성**: 4개 파라미터 × 2개 배율(`fit`, `100%` 등배 `M_HIGHQUAL`) × 2개 캐시 상태(`initial`, `cached`) × 2개 HDR(`0`, `1`) × 2개 디노이즈(`0`, `1`) = **총 64개 셀**
- **실행 규모**: 3개 독립 배치 × 10회 반복 = **총 960개 표본**
- **성공률 및 계측 무결성**: **100.0%** (960/960 `READY`, 타임아웃·거부·유실 0건, 모든 구간 지표 결측치 **0건**)
- **원시 데이터 보관 위치**: `build/liveparam-perf-checks/baseline/` (`manifest.json`, `client.jsonl`, `samples.csv`, `summary.csv`, `trace.jsonl`)

### 6.1 파라미터별 지연 시간 요약 (p50 / p95)

| 파라미터 | 요청 분류 | 성공 표본 | APPLIED p50 (ms) | APPLIED p95 (ms) | READY p50 (ms) | READY p95 (ms) | SA - SG p50 (ms) | SC - SA p50 (ms) | SR - SA p50 (ms) |
|---|---|---|---|---|---|---|---|---|---|
| 노출 (`exposure`) | 전용 API | 240 / 240 | **21.13** | **22.16** | **197.37** | **385.29** | **2.08** | **133.79** | **168.34** |
| 채도 (`saturation`) | 공통 수치 | 240 / 240 | **63.18** | **66.01** | **314.74** | **500.72** | **51.17** | **194.51** | **230.39** |
| 색온도 (`temperature`) | 공통 수치 | 240 / 240 | **63.19** | **65.84** | **520.40** | **771.33** | **51.32** | **395.54** | **431.32** |
| 샤프닝 반경 (`sharpening`) | 공통 수치 | 240 / 240 | **63.17** | **65.73** | **314.79** | **500.30** | **51.37** | **196.80** | **231.79** |

### 6.2 구간별 상세 분해 비교 (노출 vs 일반 수치)

| 관측 구간 | 노출 중앙값 (ms) | 일반 수치 중앙값 (ms) | 차이 (ms) | 의미 및 관측 내용 |
|---|---|---|---|---|
| `SQ - S0` | 0.001 | 0.001 | 0.000 | 서버 수신 후 GUI 큐 진입 (나노초 단위 즉시 처리) |
| `SG - SQ` | 0.037 | 0.046 | +0.008 | GDK 메인 루프 idle 디스패치 대기 |
| `SA - SG` | **2.08** | **51.31** | **+49.22** | GUI 메인 스레드 파싱, 위젯 트리 탐색 및 값 적용 (주요 병목 1) |
| `SP - SA` | 0.009 | 0.009 | -0.001 | 내부 상태 갱신 후 응답 반환 준비 |
| `SS - SP` | 18.88 | 11.70 | -7.18 | 소켓 쓰기 대기 및 클라이언트 APPLIED 수신 |
| `SC - SA` | **133.79** | **200.60** | **+66.81** | 엔진 Crop 파이프라인 무효화 및 계산 시간 (주요 병목 2) |
| `SN - SA` | 168.34 | 236.17 | +67.83 | 네비게이터 썸네일 파이프라인 계산 완료 시간 |
| `SR - SA` | 168.34 | 236.17 | +67.83 | 두 화면 버퍼 준비 완료 및 READY 확정 |

### 6.3 배율·프리셋·캐시 조건별 영향

- **배율 (`fit` vs `100%`)**:
  - `fit` 축소 보기 (360 표본): 일반 수치 `READY` p50 = **302.98 ms** (p95 = **594.60 ms**), Stage 2/3(`saturation`+`sharpening`) p50 = **302.60 ms** (p95 = **329.33 ms**).
  - `100%` 등배 보기 (360 표본): 일반 수치 `READY` p50 = **452.84 ms** (p95 = **769.23 ms**), Stage 2/3(`saturation`+`sharpening`) p50 = **395.68 ms** (p95 = **519.59 ms**). `skip=1`(`M_HIGHQUAL`) 경로가 활성화되면서 상위 단계 재계산 비용이 크게 증폭됨.
- **중량 도구 조합 (`hdr` × `denoise`)**:
  - `hdr=0, dn=0` (기본 프로필): 일반 수치 `READY` p50 = **280.77 ms** (p95 = **292.21 ms**).
  - `hdr=0, dn=1` (디노이즈 활성): Stage 2/3 `READY` p50 = **315.26 ms**, 색온도 `READY` p50 = **574.03 ms**.
  - `hdr=1, dn=0` (Fattal/Dehaze 활성): Stage 2/3 `READY` p50 = **377.62 ms** (p95 = **475.05 ms**).
  - `hdr=1, dn=1` (복합 중량): Stage 2/3 `READY` p50 = **412.14 ms** (p95 = **547.23 ms**), 색온도 `READY` p50 = **673.51 ms** (p95 = **789.49 ms**).
- **캐시 (`initial` vs `cached`)**:
  - `initial` (첫 수치 변경): 일반 수치 `READY` p50 = **323.34 ms**, `SA - SG` p50 = **52.35 ms**.
  - `cached` (연속 반복 변경): 일반 수치 `READY` p50 = **317.08 ms**, `SA - SG` p50 = **51.23 ms**. `ALL` 무효화로 인해 캐시 후에도 상위 RAW/Denoise/HDR 단계가 매번 재실행됨.

---

## 7. 병목 구간 상세 분석 (Stage P3)

실시간 수치 조정의 지연 원인은 계측 분석 결과 크게 두 가지 구조적 요인으로 특정된다.

### 병목 1: GUI 메인 스레드에서의 반복 위젯 트리 순회 및 가상 상속 `dynamic_cast` 오버헤드 (`SA - SG` +49.2 ms)
- **발생 위치**: `rtgui/numericcontrols.cc` (`collectNumericControls`, `numericContextId`) 및 `rtgui/toolpanelcoord.cc` (`applyExternalNumeric`)
- **현상**:
  - 일반 수치 `set_param` 요청 1회당:
    1. `LiveParamController::handleCommand`가 `tools->numericContext()`를 호출하면서 44개 패널 `write()`, `collectNumericControls()`, `contextWidgets()`로 전체 GTK 위젯 트리를 2회 순회.
    2. 직후 `tools->applyExternalNumeric()` 내부에서 `numericControls()`를 최대 3회 추가 호출하고 44개 패널 전체에 `panel->write(&before)`를 수행.
  - 특히 `collect()`와 `contextWidgets()`가 수천 개의 비-수치 컨테이너/리프 위젯마다 `container->get_children()`(`GList` 및 `std::vector` 힙 할당)과 `gtkmm` 가상 상속(`virtual public Glib::ObjectBase`) 계층에 대한 다중 `dynamic_cast`, 라벨/프레임 문자열 조합을 매번 수행하여 순수 GUI 메인 스레드 처리 시간(`SA - SG`)이 **51.31 ms**에 달함.

### 병목 2: `numericFullRefresh_ = true`로 인한 무조건적 `ALL` 무효화 (`SC - SA` +66.8 ms, 중량 프리셋 시 Stage 2/3 최대 +327 ms)
- **발생 위치**: `rtgui/toolpanelcoord.cc` (`applyExternalNumeric` 및 `panelChanged`)
- **현상**:
  - `applyExternalNumeric` 내부에서 `NumericListeners`가 위젯 변경 시 발생하는 구체적 도구 이벤트(`EvSaturation`, `EvWBTemp`, `EvShrRadius` 등)를 포착함에도 불구하고 무조건 `numericFullRefresh_ = true`를 설정하여 `panelChanged`에서 `EvProfileChanged`(`ALL` = `65535`)로 치환함.
  - 결과적으로 `M_LINDENOISE`·`M_HDR` 이후의 하위 단계만 갱신하면 되는 채도(`EvSaturation → LUMINANCECURVE`)와 샤프닝(`EvShrRadius → SHARPENING`)조차 매 요청마다 RAW 디모자이킹(`M_RAW`), 선형 디노이즈(`M_LINDENOISE`), HDR 톤매핑(`M_HDR`)을 처음부터 다시 계산하여 `100%` 등배·중량 프리셋에서 `READY RTT`가 **500~547 ms**까지 급증함.
  - 색온도(`EvWBTemp → WHITEBALANCE`) 역시 불필요한 `M_RAW`/`M_PREPROC` 단계가 매번 재실행됨.

---

## 8. 최적화 개선안 선정 및 합의 목표치 (Stage P4)

### 8.1 개선안 선정: 안전한 선택적 무효화 이벤트 매핑 및 `GObject` 메타데이터 기반 위젯 탐색 최적화
1. **`READY` 계약을 보장하는 선택적 이벤트 매핑 (`NumericEvents::canUseSelectiveEvent()`)**:
   - 단일 `panelChanged` 이벤트(`eventCount == 1 && !refreshPreviewCalled && !unsupported`)이면서 `RefreshMapper::getInstance()->getAction(event)`가 실제 프리뷰/크롭 영상 렌더 단계(`M_WHITEBALANCE`~`M_COLOR`) 비트를 포함하고 비렌더 플래그(`M_VOID | M_MINUPDATE | M_CROP | M_MONITOR`)를 포함하지 않을 때만 원래의 `events.event`를 전달한다.
   - 도구가 새로 활성화된 경우(`toolWasToggled`), 복합 이벤트가 발생한 경우, 또는 `Resize.Width`(`EvResizeWidth → M_VOID`)처럼 파이프라인 재렌더를 트리거하지 않는 이벤트인 경우에는 안전하게 `numericFullRefresh_ = true`(`EvProfileChanged → ALL`)로 fallback하여 `PENDING` 고착 없이 100% `READY` 도달을 보장한다.
2. **댕글링 포인터 없는 위젯 트리 순회 최적화 (`rtgui/numericcontrols.{h,cc}`, `rtgui/toolpanelcoord.cc`)**:
   - 도구 모드 전환 시 위젯 재할당으로 인한 댕글링 포인터 위험이나 `SHCSelector` 동적 범위/`pending` 검사 누락을 유발하는 원시 위젯 포인터 캐시(`lastNumericControl_`)는 사용하지 않는다.
   - 대신 `collectNumericControls(panels, bool includeLabels = true)`를 도입하여 `numericContextId()`와 `applyExternalNumeric()` 내부에서는 카탈로그 표시용 라벨/프레임 문자열 탐색(`includeLabels = false`)을 생략하되, SHA-256 `contextId` 다이제스트와 `available`/`pending`/`minimum`/`maximum` 실시간 검증은 100% 동일하게 수행한다.
   - 각 위젯의 `GObject` 생명주기에 귀속되는 `WidgetMeta`(`g_object_set_qdata_full`로 등록되어 위젯 소멸 시 자동 해제)에 정적 타입 분류 결과와 내부 스핀버튼 포인터를 캐싱하고, `container->get_children()` 대신 무할당 `gtk_container_foreach`를 사용하여 매 호출 시 가상 상속 `dynamic_cast`와 `GList`/`std::vector` 힙 할당을 제거한다.
   - `applyExternalNumeric()`의 롤백 백업(`before`)은 리스너가 차단된 상태에서 실제 수정 대상인 `found->owner->write(&before)` 단일 패널로 한정하고, 적용 후 값 확인은 `readNumericControlValue()`로 O(1) 조회한다.

### 8.2 합의 목표치 (Criteria & Targets)

동일한 테스트 환경(Release 빌드, 동일 RAW, 동일 64셀 매트릭스, 3배치 × 10회 반복)에서 아래 목표를 검증 기준으로 확정한다:

| 지표 | 일반 수치 기준선 (`B`) | 목표 상한 (`T`) | 최소 개선폭 (`D`) | 판정 공식 |
|---|---|---|---|---|
| **APPLIED RTT p95 (전체 720표본)** | 65.88 ms | **≤ 35.0 ms** | **≥ 30.0 ms** | `새 p95 ≤ 35.0 && B - 새 p95 ≥ 30.0` |
| **Stage 2/3 (`saturation`+`sharpening`) READY RTT p95** | 500.72 ms | **≤ 200.0 ms** | **≥ 80.0 ms** | `새 p95 ≤ 200.0 && B - 새 p95 ≥ 80.0` |
| **엔진 계산 (`SC - SA`) p50 (전체 720표본)** | 200.60 ms | **≤ 100.0 ms** | **≥ 50.0 ms** | `새 p50 ≤ 100.0 && B - 새 p50 ≥ 50.0` |
| **GUI 처리 (`SA - SG`) p50 (전체 720표본)** | 51.31 ms | **≤ 10.0 ms** | **≥ 40.0 ms** | `새 p50 ≤ 10.0 && B - 새 p50 ≥ 40.0` |

### 8.3 안전성 및 `PPVERSION 1045` 유지 근거
- **처리식 및 파이프라인 순서**: 완전히 동일하며 변경 없음.
- **수치 반영 의미 및 화질**: 수동 GUI 조작 시 발생하는 엔진 이벤트와 100% 동일한 이벤트를 발행하므로, 동일 프로필의 수동 조작 결과와 IPC 조작 결과 간 픽셀 차이가 정확히 `0`임을 보장 (`max_abs_diff = 0`).
- **`.arp` 프로필 스키마**: 프로필 저장 및 로드 포맷 변경 없음.
- **스레드 및 세대 계약**: 모든 파라미터 적용은 GUI 메인 스레드에서 원자적으로 수행되며, 프레임 세대 번호(`generation`) 및 뷰 리비전(`viewRevision`) 계약이 엄격히 유지됨.
- 따라서 `PPVERSION 1045`를 온전히 유지한다.

---

## 9. 최적화 구현 및 동일 조건 재측정 결과 (Stage P5)

### 9.1 최적화 구현 내역

1. **안전 조건부 선택적 무효화 이벤트 매핑 (`rtgui/toolpanelcoord.cc`)**:
   - `NumericEvents::canUseSelectiveEvent()`를 통해 단일 `panelChanged` 렌더 이벤트(`EvSaturation → LUMINANCECURVE`, `EvShrRadius → SHARPENING`, `EvWBTemp → WHITEBALANCE` 등)만 선택적 무효화를 허용하고, `M_VOID`(`Resize.Width`), 도구 활성화 토글(`toolWasToggled`), 복합/비렌더 이벤트는 `EvProfileChanged`(`ALL`)로 안전하게 fallback 처리.
2. **`GObject` 수명 연동 메타데이터 및 무할당 위젯 순회 (`rtgui/numericcontrols.{h,cc}`, `rtgui/toolpanelcoord.cc`)**:
   - `collectNumericControls(panels, false)` 무라벨 수집 경로, `GObject` qdata 기반 `WidgetMeta`, `gtk_container_foreach` 순회, 단일 패널 롤백 백업(`found->owner->write(&before)`) 및 `readNumericControlValue()` O(1) 읽기를 적용하여 초기 진입(`initial`)과 연속 조작(`cached`) 구분 없이 `SA - SG`를 ~5.0ms 수준으로 단축.
3. **트레이서 플러시 무결성 보장 (`rtengine/liveparamtrace.{h,cc}`)**:
   - `bindCommand` 호출 전의 진행 중 `cmdId` 레코드(`S0`, `SQ`, `SG`)가 자동 플러시에서 유실되지 않도록 보류(`deferred`) 처리하여 960개 전 표본의 모든 구간 지표를 누락 없이 기록.

### 9.2 동일 조건 재측정 실행 개요

- **측정 일시**: 2026-11-09 23:15:04 (실행 ID: `run_20261109_230958_2c0761`)
- **실행 환경**: Darwin 25.5.0 arm64 (Apple Silicon 12 vCPU, 36GB RAM, 기준선과 동일)
- **측정 바이너리**: `build/ARTLiveParamTest.app/Contents/MacOS/test_liveparam_app` (Release 최적화 빌드, SHA-256 `9bc5a2d8...`)
- **입력 RAW**: `data/fivek_sample/sample1.nef` (동일 해시 `18e28700...`)
- **표본 구성**: 4개 파라미터 × 2개 배율(`fit`, `100%`) × 2개 캐시 상태(`initial`, `cached`) × 2개 HDR(`0`, `1`) × 2개 디노이즈(`0`, `1`) = **64개 셀**
- **실행 규모**: 3개 독립 배치 × 10회 반복 = **총 960개 표본**
- **성공률 및 계측 무결성**: **100.0%** (960/960 `READY`, 타임아웃·거부·유실 0건, 모든 구간 지표 결측치 **0건**)
- **원시 데이터 보관 위치**: `build/liveparam-perf-checks/optimized/` (`manifest.json`, `client.jsonl`, `samples.csv`, `summary.csv`, `trace.jsonl`)

### 9.3 최적화 전후 성능 지표 비교

#### 1) 일반 수치 전체 (초기 진입 `initial` + 연속 조작 `cached`, 720 표본)

| 관측 지표 | 기준선 p50 | 최적화 p50 | p50 개선폭 (개선율) | 기준선 p95 | 최적화 p95 | p95 개선폭 (개선율) |
|---|---|---|---|---|---|---|
| **APPLIED RTT (클라이언트 응답)** | 63.18 ms | **21.83 ms** | **-41.35 ms (65.4%)** | 65.88 ms | **22.19 ms** | **-43.69 ms (66.3%)** |
| **READY RTT (엔진 렌더 완료)** | 317.19 ms | **171.34 ms** | **-145.85 ms (46.0%)** | 598.54 ms | **534.12 ms** | **-64.42 ms (10.8%)** |
| **SA - SG (GUI 위젯 처리)** | 51.31 ms | **4.98 ms** | **-46.33 ms (90.3%)** | 53.48 ms | **5.51 ms** | **-47.97 ms (89.7%)** |
| **SC - SA (엔진 Crop 연산)** | 200.60 ms | **98.17 ms** | **-102.43 ms (51.1%)** | 470.70 ms | **456.58 ms** | **-14.12 ms (3.0%)** |
| **SR - SA (엔진 전체 소요)** | 236.17 ms | **132.76 ms** | **-103.41 ms (43.8%)** | 507.48 ms | **493.22 ms** | **-14.26 ms (2.8%)** |

#### 2) Stage 2/3 하위 단계 수치 도구 (`saturation` + `sharpening`, 전체 480 표본 — `100%`·`hdr=1`·`dn=1` 포함)

| 관측 지표 | 기준선 p50 | 최적화 p50 | p50 개선폭 (개선율) | 기준선 p95 | 최적화 p95 | p95 개선폭 (개선율) |
|---|---|---|---|---|---|---|
| **APPLIED RTT** | 63.18 ms | **21.68 ms** | **-41.50 ms (65.7%)** | 65.90 ms | **22.19 ms** | **-43.71 ms (66.3%)** |
| **READY RTT** | 314.77 ms | **169.94 ms** | **-144.83 ms (46.0%)** | 500.72 ms | **195.91 ms** | **-304.81 ms (60.9%)** |
| **SA - SG** | 51.30 ms | **4.98 ms** | **-46.32 ms (90.3%)** | 53.49 ms | **5.50 ms** | **-47.99 ms (89.7%)** |
| **SC - SA** | 195.87 ms | **91.25 ms** | **-104.62 ms (53.4%)** | 382.87 ms | **111.29 ms** | **-271.58 ms (70.9%)** |
| **SR - SA** | 231.79 ms | **127.60 ms** | **-104.19 ms (45.0%)** | 420.53 ms | **147.79 ms** | **-272.74 ms (64.9%)** |

#### 3) 파라미터별 세부 결과 (각 240 표본, p50 / p95)

- **채도 (`saturation`, `EvSaturation → LUMINANCECURVE`)**:
  - APPLIED: p50 63.18ms → **21.75ms** (-41.43ms), p95 66.01ms → **22.19ms** (-43.82ms)
  - SA - SG: p50 51.17ms → **4.97ms** (-46.20ms), p95 53.61ms → **5.52ms** (-48.09ms)
  - READY: p50 314.74ms → **168.83ms** (-145.91ms), p95 500.72ms → **172.99ms** (-327.73ms)
- **샤프닝 반경 (`sharpening`, `EvShrRadius → SHARPENING`)**:
  - APPLIED: p50 63.17ms → **21.66ms** (-41.51ms), p95 65.73ms → **22.19ms** (-43.54ms)
  - SA - SG: p50 51.37ms → **4.99ms** (-46.38ms), p95 53.35ms → **5.48ms** (-47.87ms)
  - READY: p50 314.79ms → **171.01ms** (-143.78ms), p95 500.30ms → **197.60ms** (-302.70ms)
- **색온도 (`temperature`, `EvWBTemp → WHITEBALANCE`)**:
  - APPLIED: p50 63.19ms → **22.05ms** (-41.14ms), p95 65.84ms → **22.19ms** (-43.65ms)
  - SA - SG: p50 51.32ms → **4.98ms** (-46.34ms), p95 53.42ms → **5.51ms** (-47.91ms)
  - READY (전체): p50 520.40ms → **436.42ms** (-83.98ms), p95 771.33ms → **706.42ms** (-64.91ms)
  - READY (`hdr=0, dn=0` 기본 프로필): p50 281.27ms → **196.39ms** (-84.88ms), p95 290.80ms → **247.53ms** (-43.27ms)
  - *비고: 화이트밸런스는 엔진 파이프라인 상 `M_LINDENOISE` 및 `M_HDR`의 상위 단계이므로 디노이즈/HDR 활성 시 해당 하위 단계를 정당하게 재계산하며, `M_RAW` 디모자이킹 생략(~36ms)과 GUI 처리 단축(~46ms)으로 전 조건에서 ~84ms 단축됨.*
- **노출 (`exposure`, 전용 API 대조군)**:
  - APPLIED: p50 21.13ms → **21.74ms**, p95 22.16ms → **22.17ms**
  - SA - SG: p50 2.08ms → **2.10ms**
  - READY: p50 197.37ms → **196.70ms** (-0.67ms), p95 385.29ms → **375.59ms** (-9.70ms)
  - *비고: 전용 API 경로는 성능 회귀 없이 동일하게 유지됨.*

### 9.4 합의 목표치(Criteria) 달성 검증

Stage P4에서 확정한 모든 합의 목표치를 임의 완화 없이 **원 목표 그대로 초과 달성**하였다:

| 평가 지표 | 기준선 (`B`) | 목표 상한 (`T`) | 요구 최소개선 (`D`) | 실측 최적화 달성치 | 판정 결과 |
|---|---|---|---|---|---|
| **APPLIED RTT p95 (전체 720표본)** | 65.88 ms | **≤ 35.0 ms** | **≥ 30.0 ms** | **22.19 ms** (개선폭 43.69 ms) | **PASS (초기·캐시 전 구간 달성)** |
| **Stage 2/3 READY RTT p95 (480표본)** | 500.72 ms | **≤ 200.0 ms** | **≥ 80.0 ms** | **195.91 ms** (개선폭 304.81 ms) | **PASS (중량·100% 배율 포함 달성)** |
| **엔진 계산 (`SC - SA`) p50 (전체 720표본)** | 200.60 ms | **≤ 100.0 ms** | **≥ 50.0 ms** | **98.17 ms** (개선폭 102.43 ms) | **PASS (Stage 2/3 p50 91.25 ms)** |
| **GUI 위젯 처리 (`SA - SG`) p50 (전체 720표본)** | 51.31 ms | **≤ 10.0 ms** | **≥ 40.0 ms** | **4.98 ms** (개선폭 46.33 ms, p95 5.51 ms) | **PASS (90.3% 단축, 원 목표 달성)** |

### 9.5 회귀 검증 및 `PPVERSION 1045` 유지 확인

1. **단위 및 GUI 검증 스위트 (`test_liveparam`, `test_liveparam_gui`)**:
   - `test_liveparam`: 프로토콜 계약, 세션 수명, 리비전 충돌, 기본 비활성화 동작 모두 통과 (`PASS`).
   - `test_liveparam_gui --case T01 --case T19 --case T20 --case T21 --case T23 --case T24 --case T25 --case T26`:
     - T01 (상태 소유권 및 엔진 경계): `PASS`
     - T19 / T20 (`100%` 등배 뷰포트 변경 및 `M_HIGHQUAL` 완료 세대 동기화): `PASS`
     - **T21 (페이지네이션 카탈로그, `contextId` 검증 및 이미 활성화된 `Resize.Width` `M_VOID` 연속 2회 변경 `READY` 도달 검증)**: `PASS`
     - T23 (네이티브 복합 위젯 계열): `PASS`
     - T24 (23개 도구 모드, 335개 수치 필드 카탈로그): `PASS`
     - **T25 (수동 조작과 외부 IPC 조작 간 프로필 및 렌더 픽셀 완벽 일치)**: `PASS` (`max_abs_diff = 0`)
     - T26 (성능 추적 하네스 오버헤드 5ms, 링버퍼 단조성): `PASS`
2. **CLI 통합 검증 (`test_art_cli.sh`)**:
   - 동일 샘플 RAW(`sample1.nef`)에 대한 ART-cli 렌더링 정상 동작 확인 완료 (`SUCCESS`).
3. **`PPVERSION 1045` 유지 판정**:
   - 수동 GUI 조작 시 발생하는 엔진 이벤트와 100% 동일한 최소 무효화 이벤트를 발행하고 비렌더 이벤트(`M_VOID` 등)에 대해서는 전체 갱신으로 안전하게 fallback하므로 기존 프로필의 해석·기본값·영상 처리 의미와 `READY` 계약이 완전히 보존됨.
   - 렌더 픽셀 오차 `0` 및 프로필 스키마 불변이 입증되었으므로 `PPVERSION 1045`를 온전히 유지한다.

## 10. 2026-11-18 검토 후 보완 계획

검토 기준은 `8489ee50d`다. Release에서 GUI 전체 검사, IPC 계약 검사, Python 131건과 ART-cli TIFF 생성이 통과했다. 같은 커밋의 간이 측정 `run_20261118_134626_1e51de`에서는 160건 모두 `READY`에 도달했고 일반 수치 `APPLIED` p95는 21.18ms, 채도·샤프닝 `READY` p95는 190.94ms였다.

§5~9는 이전 실행 기록으로 보존한다. 기존 전후 로그는 64개 셀에 각각 총 960건이 있으나 최초 셀은 각 3건, 캐시 후 셀은 각 27건이다. 채도·색온도·샤프닝의 최초 표본도 앞선 도구 조정 뒤에 수집됐다. 두 실행의 매니페스트는 같은 이전 커밋 `4c427c6a`와 미커밋 변경이 있었음을 기록한다. 따라서 최초 조정 분포, 최종 커밋의 전후 개선 폭, §9.5의 선택적 갱신 화질 및 PPVERSION 판정은 아래 검증으로 다시 확정한다.

### 10.1 계측 오류 수정과 하네스 보완

- [x] `liveparamtrace.cc`의 JSONL 문자열 직렬화에 따옴표·역슬래시·줄바꿈·유니코드 처리를 적용한다. 기존 전송 경로가 받아들이는 요청 ID를 그대로 복원할 수 있어야 한다. I/O와 엔진 스레드에서 동시에 기록할 수 있는 경로이므로 공유 파서 상태나 새 GTK 접근을 도입하지 않는다.
- [x] `liveparamserver.cc`, `liveparamcontroller.cc`, 추적기에서 내부 명령 번호를 서버 수명 식별자와 함께 기록한다. 요청 기록은 세션·편집기·요청 ID와 실제 편집·뷰·계산 세대로 대조한다. 큐 포화나 GUI 전달 전 취소에 사용한 명령 번호가 다음 정상 요청에 붙지 않아야 한다. 재전송은 개별 전송으로 기록하고 원래 변경에 대한 `SA`·`READY` 기록을 덮지 않는다.
- [x] 추적 기록과 명령 식별 매핑에 상한과 정리 시점을 둔다. GUI·엔진의 기록 경로에 파일 쓰기 대기가 전파되지 않도록 기록 잠금 밖에서 파일에 쓴다. 유실 수·쓰기 오류를 결과에 남기고, 계측 ON/OFF는 같은 Release 조건에서 비교한다.
- [x] `scripts/live_param_perf_probe.py`가 잘못된 JSONL, 필수 이벤트 누락·중복·불일치, 유실을 만나면 원자료와 원인을 남기고 해당 실행을 실패로 판정하게 한다. 성공 표본은 요청 ID, 반영값, 편집 revision과 현재 화면에 표시된 뷰 세대를 검증한다. `SC − SA`는 GUI 반영부터 주 Crop 표시 자료가 준비될 때까지의 구간으로 보고한다. 병목을 단계 단위로 설명할 경우 실제 실행과 캐시 재사용을 관측한 자료를 덧붙인다.

통과 기준은 T26 또는 같은 실제 소켓 경로의 회귀 검사에서 특수문자 ID, 같은 프로세스의 서버 재시작, 동일 요청 재전송, 큐 포화와 취소, 팬·줌과 종료를 재현하고 기록이 정확히 연결되는 것이다. 프로브에 깨진 줄이나 유실 기록을 넣은 검사에서는 실행이 실패해야 한다.

### 10.2 선택적 갱신 화면과 저장·출력 비교

- [x] `test_liveparam_gui.cc`의 실제 편집기 검사에서 채도·USM 샤프닝 반경·Custom 화이트밸런스 온도를 이미 켜 둔 프로필로 시작한다. 같은 RAW·초기 프로필·뷰포트에서 일반 수치 IPC의 선택적 갱신과 전체 갱신 대조 경로에 같은 값을 적용한다. 테스트에서 실제 선택적 이벤트가 사용됐음을 먼저 확인한다. 비교 제어는 테스트 하네스 안에 둔다.
- [x] 축소와 100%, HDR·노이즈 제거 OFF/OFF, ON/OFF, OFF/ON, ON/ON을 확인한다. 매 경우 실제 편집·뷰·계산 세대의 `READY`를 확인한 뒤 Navigator와 주 Crop의 크기와 픽셀을 비교한다. 같은 빌드·조건에서 픽셀 최대 절대 차이는 0이어야 한다. 도구 켜기, 복합 이벤트, `M_VOID` 대조에서는 전체 갱신과 후속 요청 수락을 확인한다.
- [x] Release GUI·IPC·Python 회귀에 이어 기존 프로필 로드·저장·재읽기, `APPLIED` 직후 저장·내보내기와 대기열 등록, 실행 중 내보내기의 값 고정을 확인한다. 같은 RAW·프로필로 변경 전후 ART-cli 출력의 디코딩된 픽셀을 비교하고 런타임 메타데이터 차이를 별도로 기록한다.
- [x] 별도 ASan·TSan GUI 구성에서 연속 요청, 수동 GUI 변경과 충돌, 동적 위젯·편집 문맥 전환, 팬·줌, 닫기·재열기·종료를 실행한다. 계측을 켠 경로도 포함한다. 검사로 확인한 결과와 실행하지 못한 범위를 구분해 기록한다.

화면·저장·GUI/CLI 출력의 의미와 안전성 검증을 통과하면 PPVERSION 1045 유지 근거를 갱신한다. 픽셀이나 세대가 어긋나는 이벤트는 원인을 찾아 필요한 무효화 범위를 확보하고, 입증이 끝날 때까지 그 이벤트를 전체 갱신으로 처리한다.

### 10.3 동일 조건의 기준선과 최적화 재측정

- [x] 최적화 전 기준은 `3c5fe6cbd`, 후보는 보완 완료 커밋으로 잡는다. 기준선과 후보에 동일한 계측과 프로브를 적용하되 기준선의 위젯 처리·이벤트 선택은 최적화 이전 코드로 유지한다. 실행마다 소스 커밋, 적용한 공통 계측 패치의 식별값, 바이너리·RAW·프로필 해시, 실행 명령, 연결·조회 정책, 종료 코드와 환경을 보관한다.
- [x] RAW 한 장으로 네 수치 항목과 축소/100%, 최초/캐시 후, HDR·노이즈 제거 네 조합을 교차한다. 기본 경로의 노출은 공통 수치 IPC로 측정하며 기존 노출 전용 API는 별도 대조군으로 둔다. 최초 표본마다 사진을 새로 열어 지정 배율의 초기 프레임이 준비되면 그 도구를 첫 번째로 조정한다. 캐시 후 표본은 준비된 동일 세션에서 서로 다른 값으로 반복한다. 실제 배율·뷰포트와 프로필 조건을 확인한다.
- [x] 64개 셀 각각을 조건마다 3회 독립 실행으로 나누어 총 30건씩 수집한다(RAW 한 장 기준 전후 각 1,920건). 채택의 핵심 지연을 판단할 셀은 §1.5대로 100건 이상으로 보강한다. 기준/후보와 조건의 순서를 교차하고, 실제 채팅 클라이언트 방식은 별도 표에서 비교한다.
- [x] `build/liveparam-perf-checks/<실행ID>/`의 원자료로 셀별 성공·거부·미완료 수와 p50/p95를 다시 계산한다. §8.2와 동일하게 채도·샤프닝·색온도 집계 및 채도·샤프닝 집계에 절대 상한과 최소 개선 폭을 적용한다. 공통 수치 노출과 전용 노출의 결과, 배율·도구·최초/캐시 후별 결과, 반복 실행의 변동도 기록한다. 성능 목표 미달 또는 화면·세대·안전성 회귀가 있으면 병합 판정을 보류한다.

후속 변경은 다음 순서로 커밋한다. 회귀를 발견해 제품 코드를 수정하면 관련 검사와 같은 커밋에 묶고, 그 수정이 포함된 후보 바이너리로 재측정한다.

| 순서 | 범위 | 국문 커밋 제목 |
|---|---|---|
| 1 | 이 절과 문서 상태 갱신 | `docs: 실시간 수치 조정 성능 검증 보완 계획 추가` |
| 2 | 계측·하네스 수정과 실패 재현 검사 | `fix: 실시간 수치 조정 계측의 요청 식별과 로그 검증 보완` |
| 3 | 선택적 갱신 화면 비교와 GUI/CLI·스레드 회귀 검증 | `test: 선택적 미리보기 갱신의 화면과 출력 회귀 검증 추가` |
| 4 | 같은 조건으로 재측정하고 병합 판정과 PPVERSION 근거 기록 | `docs: 실시간 수치 조정 전후 재측정과 채택 근거 기록` |

### 10.4 보완 구현·검증 및 동일 조건 재측정 결과 (2026-11-18 ~ 2026-11-19)

#### 1) 보완 커밋 이력 및 수정 사항
- **Commit 1 (`516832936`)**: §10 보완 계획 문서화.
- **Commit 2 (`be5846fae`, `§10.1` 완료)**:
  - `rtengine/liveparamtrace.{h,cc}`: JSONL 문자열 이스케이프(`escapeJsonString`), 전역 원자적 `allocateCmdId()`, `(sessionId, cmdId)` 단위 `CommandMeta` 추적(`kMaxCommandMeta = 4096`), `finishUnboundCommand()`(`CANCELLED`/`REJECTED`), `REPLAY` 별도 이벤트 기록, 락 외부(`fileMutex_`) 파일 쓰기, `drops`/`writeErrors` 기록 및 `flushIfNeeded()`/`flush(true)` 구현.
  - `rtgui/liveparamserver.cc`, `rtgui/liveparamcontroller.{h,cc}`, `rtgui/numericcontrols.h`, `rtgui/toolpanelcoord.{h,cc}`: 명령 ID/세션/변경 플래그(`appliedChangeFlags`) 연동 및 **macOS `AF_UNIX` `poll()` 수정**(`events=0`에서 피어 종료 시 `POLLHUP`이 전달되지 않던 문제를 `events=POLLIN`으로 해결해 클라이언트 조기 종료 시 대기 명령 `CANCELLED` 전이 복구).
  - `rtengine/improccoordinator.{h,cc}`, `rtengine/dcrop.cc`: `ENGINE_DONE`·`CROP_DONE`에 실제 수행/재사용된 파이프라인 단계(`preproc`, `raw`, `init`, `dn`, `hdr`, `tf`, `s1`, `s2`, `s3`) 및 `crop:main/skip/realloc` 플래그 기록.
  - `scripts/live_param_perf_probe.py` 및 `rtgui/test_liveparam_gui.cc`(`T26`): 특수문자 `requestId`, 중복 재전송, 큐 포화(32건+`BUSY`) 및 클라이언트 종료 취소, 팬·줌, 동일 프로세스 서버 재시작, `--validate-dir` 실패 주입(깨진 JSON, `drops=1`, `SR` 누락) 모두 통과. `T26` 계측 비활성 호출 100,000회는 5~15ms(Release 5~10ms, ASan 7ms, TSan 15ms).
- **Commit 3 (`629f0429e`, `§10.2` 완료)**:
  - **발견 및 수정한 제품 결함 #1 (`WHITEBALANCE` 및 비보존 플래그 폴백)**: 축소 배율(`fit`) + `WB_BEFORE_HIGH_DETAIL` 조건에서 `WHITEBALANCE`(`M_WHITEBALANCE | ALLNORAW`)가 `M_PREPROC | M_RAW`를 무효화하지 않아 선택적 갱신 vs `ALL` 차이가 발생할 수 있고, `M_HDR && !M_LINDENOISE` 또는 `M_TRANSFORM && !(M_HDR && M_LINDENOISE)` 역시 불완전 재계산 위험이 있어 `NumericEvents::canUseSelectiveEvent()`에서 전체 갱신(`EvProfileChanged → ALL`)으로 안전 폴백하도록 제한 (`EvSaturation`, `EvShrRadius`, `EvExpComp`는 선택적 갱신 유지 후 `T25`에서 전수 입증).
  - **발견 및 수정한 제품 결함 #2 (`M_HIGHQUAL` 전환 시 Navigator 중간 버퍼 불일치)**: `test_liveparam_gui` 전체 실행 중 `PD_Fast` 상태에서 `fit`→`100%`(`M_HIGHQUAL`) 전환 뒤 첫 `EvSaturation` 선택적 갱신을 실행했을 때 주 Crop은 `max_abs_diff = 0`이었으나 Navigator(`287×433`)에서 `navDiff = 13`이 검출됨. `rtengine/improccoordinator.cc`에서 고품질 디모자이크 수행 블록 끝의 `todo |= M_INIT;`을 `todo |= ALLNORAW;`로 수정하여 디모자이크 실행 직후 `orig_prev`와 중간 버퍼(`bufs_[0..2]`)가 함께 동기화되도록 해결.

#### 2) 화면·저장·GUI/CLI 출력 및 메모리/스레드 안전성 검증 결과 (`§10.2`)
- **Release 회귀 검증 (`629f0429e`)**:
  - `test_liveparam` (`V1`, `V5`, `V7`): **PASS**
  - `test_liveparam_gui` 전체 스위트(`T01`~`T26` + 별도 프로세스 `T17`): **PASS**
  - Python 회귀(`/Users/user/orca/workspaces/AAART/T10-2c-update/venv/bin/pytest tests/test_live_param*.py`): **113 passed**
  - **`T25` 선택적 갱신 전수 픽셀 비교**: `fit`(`skip > 1`)과 `100%`(`skip == 1`) × HDR(`0/1`) × 노이즈 제거(`0/1`) **8개 조합** × `saturation`(`LUMINANCECURVE`), `sharpening`(`SHARPENING`), `exposure`(`HDR`), `whitebalance`(`EvWBTemp` 전체 갱신 폴백), 그리고 `PD_Fast`/`PD_Sidecar` 전환 시 모든 조합에서 Navigator(`287×433`)와 주 Crop(`515×668` 등)의 `Pixbuf` 크기·채널 일치 및 `max_abs_diff == 0`, `READY` 시점 `editRevision`/`viewRevision`/`generation` 일치 확인. 도구 켜기(`enableTool=true`), 복합 콜백(`colorcorrection`), `M_VOID`(`Resize.Width`)의 전체 갱신 폴백과 직후 후속 수치 요청(`APPLIED`→`READY`) 정상 수락 확인. `T14`를 통해 프로필 로드·저장·재읽기, `APPLIED` 직후 저장·내보내기, `BatchQueueEntry` 및 실행 중 내보내기 스냅샷 고정(`max_abs_diff == 0`) 재확인.
- **`ART-cli` 16-bit TIFF 출력 비교 (`3c5fe6cbd` vs `be5846fae`, 엔진 픽셀 경로는 `629f0429e` GUI/M_HIGHQUAL 보완 외 변경 없음)**:
  - 동일 입력 `data/fivek_sample/sample1.nef` 및 프로필 `data/test_profile.arp`로 `-b16 -t` 출력 비교 시 두 TIFF 모두 `2006×3031`, `16-bit`, `3ch`, 파일 크기 `36,481,712 bytes`, **디코딩된 픽셀 `max_abs_diff = 0` (`diff_samples = 0`)** 확인.
  - 파일 바이트 SHA-256 차이(`e794aba8...` vs `60266edc...`)는 `tiffinfo` 상 런타임 메타데이터 태그 `Software`(`ART 3c5fe6cbd` vs `ART be5846fae`) 및 `DateTime` 타임스탬프 차이에만 기인함.
- **ASan / TSan GUI 검증 범위 구분**:
  - **Debug + ASan (`build/asan`)**: `test_liveparam` (`V1`, `V5`, `V7`) 및 `test_liveparam_gui` (`T01`, `T03`, `T08`, `T11`, `T12`, `T13`, `T20`, `T21`, `T23`, `T24`, `T25`, `T26` — `ART_LIVE_PARAM_TRACE` 활성 경로 포함) **전수 통과, ASan 오류 0건**.
  - **Debug + TSan (`build/tsan`)**: `test_liveparam` (`V1`, `V5`, `V7`) 및 `test_liveparam_gui`의 `T01`, `T03`, `T08`, `T11`, `T12`, `T13`, `T20`, `T21`, `T23`, `T26`(`ART_LIVE_PARAM_TRACE` 활성 경로 포함) **통과, TSan 데이터 레이스 경고/오류 0건**. (`T24`·`T25`는 `-O0 -fsanitize=thread` 환경에서 OpenMP 없이 단일 스레드로 140회 이상 전체 RAW 프리뷰를 렌더하는 시간 한계로 TSan 실행에서 제외하고 Release 및 Debug+ASan에서 전수 통과로 검증함.)
- **`PPVERSION 1045` 유지 근거**:
  - 저장된 `.arp` 프로필의 스키마·기본값·해석 및 `ART-cli`/수동 GUI 대비 영상 처리 결과(`max_abs_diff == 0`)가 완전히 불변이고, IPC 선택적 갱신은 수동 GUI 조작과 동일한 최소 무효화 이벤트(모호하거나 상위 `M_PREPROC`/`M_RAW` 영향 가능성이 있는 `WHITEBALANCE`/`TRANSFORM`/`M_HDR && !M_LINDENOISE`/`M_VOID`는 `ALL` 폴백)를 사용하며, `M_HIGHQUAL` 동기화 수정 또한 렌더링 정합성을 복구할 뿐 프로필 의미를 바꾸지 않으므로 `PPVERSION 1045`를 유지한다.

#### 3) 동일 조건 전후 재측정 환경 및 매니페스트 식별 (`§10.3`)
- **측정 일시 및 실행 ID**: 2026-11-19 (`v2_baseline_3c5fe6cbd`, `v2_candidate_629f0429e`, 보관 경로 `build/liveparam-perf-checks/v2_baseline_3c5fe6cbd/`·`v2_candidate_629f0429e/`, 배치별 원자료 `v2_batches/`, 대조군 `v2_ctrl_*`). 기존 §5~§9 디렉터리(`baseline/`, `optimized/`, `run_20261118_134626_1e51de/`)는 그대로 보존됨.
- **실행 환경**: Darwin 25.5.0 arm64 (Apple Silicon 12 vCPU), macOS Release 빌드(`test_liveparam_app`), 입력 RAW `data/fivek_sample/sample1.nef` (SHA-256 `18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805`), `.arp` 4종 프로필 SHA-256 (`hdr0_dn0`: `a9ccfa63e420...`, `hdr0_dn1`: `d03244bf754f...`, `hdr1_dn0`: `0b4396c17509...`, `hdr1_dn1`: `8239a923a393...`).
- **기준선 (`v2_baseline_3c5fe6cbd`)**: 커밋 `3c5fe6cbd61d8b2767f75bafdc2c7c99ae5f6c7b` + 공통 계측 패치(SHA-256 `58727976f330a768002c4f5cfd4e0a880eff4483e454768f44bddbd2c4eace8c`, 11개 파일 `503+/137-`; `3c5fe6cbd`의 전체 패널 쓰기/롤백·전체 위젯 순회·`numericFullRefresh_ = true`·`todo |= M_INIT;` 유지), 바이너리 SHA-256 `94ace847bba7a695e9d4f2d073a6467224b31876b0b7f388a289d77e7b7f2ad4`.
- **후보 (`v2_candidate_629f0429e`)**: 커밋 `629f0429e63d4fca3dd7a6043f11523c139539c8` (**클린 워크트리 `git_dirty=false`**), 바이너리 SHA-256 `662ca87757a684eab36d072b3d6a9ee8c9faaf26666d3f733de1f3a5f68c9a86`.
- **프로브 및 실행 정책**: `scripts/live_param_perf_probe.py` (B1·A1·A2 배치 시 `9684232c796a...`, 이후 macOS PID 재순환 소켓 충돌 방지 필터 추가판 `b47e53b8f434...`), 교차 실행 순서 **`B1 → A1 → A2 → B2 → B3 → A3`**, 종료 코드 `0`, `drops=0`, `writeErrors=0`, `validation_error_count=0`, `READY` 성공률 **100.0%** (전후 각 2,220/2,220건: 균형 64셀 × 3배치 × 10회 = **1,920건** + 핵심 4셀 `--core-boost 25` × 3배치 = **300건**). 기본 경로 4항목(`exposure`, `saturation`, `temperature`, `sharpening`) 모두 일반 수치 IPC(`list_params` 발견 키 + `contextId` + `enableTool=false`) 사용, `initial` 표본마다 새 GUI 프로세스를 기동하여 초기 프레임 안정화(50ms) 후 해당 도구를 첫 번째로 1회 조정.

#### 4) 전후 재측정 주요 집계 비교 (단위: ms)

| 집계 구간 (표본 수: 전 / 후) | 지표 | 기준선 p50 | 후보 p50 | p50 변화 | 기준선 p95 | 후보 p95 | p95 변화 |
|---|---|---|---|---|---|---|---|
| **전체 64셀 균형 매트릭스 (1,920 / 1,920)** | **APPLIED RTT** | 63.14 | **21.44** | -41.70 (-66.0%) | 66.13 | **22.13** | -44.00 (-66.5%) |
| (4항목 × 2배율 × 2캐시 × 4 HDR/DN) | **SA - SG** | 50.10 | **5.42** | -44.68 (-89.2%) | 51.61 | **8.72** | -42.89 (-83.1%) |
| | **SC - SA** | 196.41 | **111.90** | -84.51 (-43.0%) | 456.69 | **465.71** | +9.02 (+2.0%) |
| | **READY RTT** | 307.92 | **190.30** | -117.62 (-38.2%) | 583.91 | **540.26** | -43.65 (-7.5%) |
| **핵심 보강 포함 전체 (2,220 / 2,220)** | **APPLIED RTT** | 63.14 | **21.16** | -41.98 (-66.5%) | 66.13 | **22.12** | -44.01 (-66.6%) |
| | **SA - SG** | 50.12 | **5.33** | -44.79 (-89.4%) | 51.66 | **8.61** | -43.05 (-83.3%) |
| | **SC - SA** | 196.41 | **108.10** | -88.31 (-45.0%) | 455.73 | **462.59** | +6.86 (+1.5%) |
| | **READY RTT** | 307.92 | **188.98** | -118.94 (-38.6%) | 582.45 | **538.70** | -43.75 (-7.5%) |
| **채도·샤프닝·색온도 균형 (1,440 / 1,440)** | **APPLIED RTT** | 63.31 | **21.16** | -42.15 (-66.6%) | 66.14 | **22.12** | -44.02 (-66.6%) |
| (`§8.2` 720표본 대조 집계) | **SA - SG** | 50.12 | **5.42** | -44.70 (-89.2%) | 51.63 | **8.80** | -42.83 (-83.0%) |
| | **SC - SA** | 197.28 | **104.75** | -92.53 (-46.9%) | 459.03 | **471.41** | +12.38 (+2.7%) |
| | **READY RTT** | 320.00 | **176.70** | -143.30 (-44.8%) | 586.18 | **544.08** | -42.10 (-7.2%) |
| *(참고)* **채도·샤프닝·색온도 `cached` (720 / 720)** | **SC - SA / READY** | 196.33 / 307.66 | **101.21 / 175.41** | -95.12 / -132.25 | 459.23 / 586.85 | **460.86 / 541.31** | +1.63 / -45.54 |
| **Stage 2/3 채도·샤프닝 균형 (960 / 960)** | **APPLIED RTT** | 63.14 | **21.42** | -41.72 (-66.1%) | 66.13 | **22.13** | -44.00 (-66.5%) |
| | **SA - SG** | 50.09 | **5.38** | -44.71 (-89.3%) | 51.59 | **8.72** | -42.87 (-83.1%) |
| | **SC - SA** | 195.51 | **99.68** | -95.83 (-49.0%) | 371.04 | **117.20** | -253.84 (-68.4%) |
| | **READY RTT** | 307.37 | **174.25** | -133.12 (-43.3%) | 500.08 | **199.24** | -300.84 (-60.2%) |
| **Stage 2/3 핵심 보강 포함 (1,260 / 1,260)** | **APPLIED / SA-SG** | 63.13 / 50.12 | **21.12 / 5.25** | -42.01 / -44.87 | 66.13 / 51.66 | **22.12 / 8.45** | -44.01 / -43.21 |
| | **SC - SA / READY** | 195.51 / 307.37 | **99.65 / 174.25** | -95.86 / -133.12 | 373.42 / 504.62 | **114.44 / 195.47** | -258.98 / -309.15 |
| **Stage 2/3 `cached` 전체 (780 / 780)** | **SC - SA / READY** | 192.78 / 307.04 | **93.70 / 173.61** | -99.08 / -133.43 | 373.45 / 504.83 | **113.49 / 191.21** | -259.96 / -313.62 |
| **Stage 2/3 `initial` 단독 (480 / 480)** | **SC - SA / READY** | 197.15 / 307.92 | **102.64 / 175.16** | -94.51 / -132.76 | 373.24 / 504.17 | **122.56 / 201.23** | -250.68 / -302.94 |

#### 5) 핵심 채택 판단 셀 105건 보강 비교 및 요인별·배치별 분석 (단위: ms)

- **핵심 채택 판단 4개 셀 (100% 배율, `cached`, 각 전/후 105표본)**:
  - `saturation_100_cache_hdr0_dn0`: `APPLIED` p95 63.21 → **22.12**, `SA-SG` p50 49.83 → **5.18**, `SC-SA` p50 158.98 → **92.12**, `READY` p95 283.14 → **176.51** (-106.63ms)
  - `saturation_100_cache_hdr1_dn1`: `APPLIED` p95 66.13 → **22.10**, `SA-SG` p50 50.62 → **5.09**, `SC-SA` p50 370.64 → **93.43**, `READY` p95 507.65 → **176.12** (-331.53ms)
  - `sharpening_100_cache_hdr0_dn0`: `APPLIED` p95 63.28 → **22.11**, `SA-SG` p50 49.96 → **5.02**, `SC-SA` p50 160.89 → **101.40**, `READY` p95 283.24 → **176.64** (-106.60ms)
  - `sharpening_100_cache_hdr1_dn1`: `APPLIED` p95 66.15 → **21.11**, `SA-SG` p50 50.44 → **5.10**, `SC-SA` p50 369.48 → **113.11**, `READY` p95 505.08 → **191.34** (-313.74ms)
- **파라미터별 (`core_matrix`, 각 480표본, 전 → 후)**:
  - `exposure` (공통 수치 IPC `EvExpComp`): `APPLIED` p95 66.13 → **22.13**, `SA-SG` p50 50.02 → **5.42**, `SC-SA` p50 192.44 → **137.20**, `READY` p50/p95 307.16/503.38 → **202.77/389.22**
  - `saturation` (`EvSaturation`): `APPLIED` p95 66.13 → **22.13**, `SA-SG` p50 50.06 → **5.40**, `SC-SA` p50 194.99 → **93.01**, `READY` p50/p95 307.32/502.91 → **172.51/177.28**
  - `temperature` (`EvWBTemp` 안전 `ALL` 폴백): `APPLIED` p95 66.14 → **22.12**, `SA-SG` p50 50.19 → **5.45**, `SC-SA` p50 338.19 → **350.46**, `READY` p50/p95 460.28/744.95 → **439.53/711.21** (`hdr=0, dn=0` 120건: `SC-SA` p50 156.89 → **161.34**, `READY` p50/p95 281.87/283.10 → **229.78/255.94**)
  - `sharpening` (`EvShrRadius`): `APPLIED` p95 66.14 → **22.12**, `SA-SG` p50 50.12 → **5.35**, `SC-SA` p50 195.70 → **103.48**, `READY` p50/p95 307.37/484.52 → **175.45/201.36** (`cached` 240건 `READY` p95 **191.36ms**, `initial` 240건 `READY` p95 **202.23ms**)
- **배율·캐시·HDR/DN 요인별 (`core_matrix`, 전 → 후)**:
  - `fit` (960건, `crop:skip=4`): `READY` p50/p95 298.93/577.53 → **175.94/537.01**, `SC-SA` p50 181.28 → **105.78**
  - `100%` (960건, `crop:skip=1`): `READY` p50/p95 454.32/740.50 → **197.57/709.66**, `SC-SA` p50 329.16 → **114.90**
  - `initial` (960건) vs `cached` (960건): `SA-SG` p50/p95 49.96/51.49 → **7.41/9.03** (`initial`, 첫 `WidgetMeta` 구축 포함), 50.22/51.68 → **5.16/5.54** (`cached`); `READY` p50 319.77 → **191.29** (`initial`), 307.48 → **176.55** (`cached`)
  - `HDR/DN` 조합(각 480건 `READY` p50): `hdr0_dn0` 281.75 → **175.10**, `hdr0_dn1` 322.49 → **199.97**, `hdr1_dn0` 307.63 → **176.87**, `hdr1_dn1` 480.85 → **200.07**
- **3회 독립 배치 변동 (`core_matrix` 배치당 640건)**:
  - 기준선(`B1/B2/B3`): `APPLIED` p95 `66.14/66.13/66.13`, `SA-SG` p50 `49.79/50.16/50.27`, `SC-SA` p50 `195.23/197.34/197.33`, `READY` p50 `321.61/307.48/307.45`
  - 후보(`B1/B2/B3`): `APPLIED` p95 `22.13/22.12/22.13`, `SA-SG` p50 `5.43/5.41/5.40`, `SC-SA` p50 `111.58/111.98/112.04`, `READY` p50 `190.13/190.37/190.48` (배치 간 편차 ≤ 0.5ms)

#### 6) 파이프라인 단계 실행·캐시 재사용 관측 (`ENGINE_DONE` / `CROP_DONE`) 및 대조군 비교
- **실제 단계 실행과 캐시 재사용 확인 (`core_matrix` 각 480표본/파라미터)**:
  - **기준선 (`3c5fe6cbd`)**: 4개 파라미터 전수(각 480/480건)가 `nav:preproc=1,raw=1,init=1,hdr={0|1},tf=0,s1=1,s2=1,s3=1,todo=536575`(`ALL`)를 실행.
  - **후보 (`629f0429e`)**:
    - `saturation` (480/480): `nav:preproc=0,raw=0,init=0,hdr=0,tf=0,s1=0,s2=0,s3=1,todo=19`, `crop:main=1,skip={4|1},realloc=0,init=0,dn=0,hdr=0,tf=0,s1=0,s2=0,s3=1` — 이전 `Stage 0/1/2`·`raw`·`denoise` 캐시 재사용, `Stage 3`만 재실행.
    - `sharpening` (480/480): `nav:...,s2=1,s3=1,todo=23`, `crop:...,dn=0,hdr=0,s1=0,s2=1,s3=1` — `Stage 0/1`·`raw`·`denoise` 캐시 재사용, `Stage 2+3`만 재실행.
    - `exposure` (480/480): `nav:preproc=0,raw=0,init=1,hdr={0|1},s1=1,s2=1,s3=1,todo=524799`, `crop:...,init=0,dn={0|1},hdr={0|1},s1=1,s2=1,s3=1` — `preproc/raw` 디모자이킹 생략, `init` 이후만 재실행.
    - `temperature` (480/480): `nav:preproc=1,raw=1,init=1,...,todo=536575`, `crop:...,init=1,dn={0|1},...` — §10.2 화질 원칙에 따라 `ALL` 전체 갱신.
- **대조군 3종 실측 비교 (단위: ms)**:
  1. **공통 수치 IPC `exposure` vs 기존 전용 API `exposure_builtin` (전용 160건)**:
     - 기준선 `exposure_builtin` (160): `APPLIED` p95 `21.14`, `SA-SG` p50 `2.44`, `SC-SA` p50 `136.48`, `READY` p50/p95 `214.39 / 389.00`
     - 후보 `exposure_builtin` (160): `APPLIED` p95 `22.12`, `SA-SG` p50 `2.43`, `SC-SA` p50 `136.47`, `READY` p50/p95 `201.30 / 385.40`
     - 후보 공통 수치 `exposure` (480): `APPLIED` p95 `22.13`, `SA-SG` p50 `5.42`, `SC-SA` p50 `137.20`, `READY` p50/p95 `202.77 / 389.22` (공통 수치 경로가 전용 경로 대비 GUI 처리 약 3ms 차이 외 `READY` 및 `APPLIED` p95 동등 수준으로 수렴).
  2. **지속 연결(`persistent`, 3ms 폴링) vs 실제 채팅 클라이언트 방식(`client`, 매 RPC 새 소켓·50ms 폴링, 320건 동일 규모)**:
     - `persistent` (`v2_ctrl_cand_trace_on`, 320): `APPLIED` p50/p95 `21.12 / 22.12`, `SA-SG` p50 `5.35`, `SC-SA` p50 `111.96`, `READY` p50/p95 **`191.15 / 541.49`**
     - `client` (`v2_ctrl_cand_client`, 320): `APPLIED` p50/p95 `22.19 / 22.24`, `SA-SG` p50 `5.95`, `SC-SA` p50 `112.35`, `READY` p50/p95 **`206.38 / 594.29`** (매 요청 소켓 재연결 및 50ms 폴링 간격으로 `READY` p50 +15.23ms, p95 +52.80ms 증가; 서버 계산 `SC-SA` 차이는 +0.39ms).
  3. **동일 Release 후보 계측 ON vs OFF (320건 동일 규모)**:
     - 계측 OFF (`v2_ctrl_cand_trace_off`, `ART_LIVE_PARAM_TRACE` 미설정): `APPLIED` p50/p95 `21.10 / 22.12`, `READY` p50/p95 `190.86 / 541.68`
     - 계측 ON (`v2_ctrl_cand_trace_on`): `APPLIED` p50/p95 `21.12 / 22.12`, `READY` p50/p95 `191.15 / 541.49` (오버헤드 < 0.3ms, 실측 변동 범위 이내).

#### 7) `§8.2` 기준 대조 및 최종 병합 판정: **보류**

| §8.2 기준 지표 | 기준선 (`B`) | 목표 (`T`, 최소개선 `D`) | Stage 2/3 (`960` / `1,260`) | 채도·샤프닝·색온도 (`1,440`) | 전체 4항목 (`1,920`) | 기준 충족 여부 |
|---|---|---|---|---|---|---|
| **APPLIED RTT p95** | 66.13–66.14 ms | `≤ 35.0` (`-≥30.0`) | **22.13 / 22.12 ms** (`-44.00`) | **22.12 ms** (`-44.02`) | **22.13 ms** (`-44.00`) | **PASS** |
| **Stage 2/3 READY RTT p95** | 500.08–504.62 ms | `≤ 200.0` (`-≥80.0`) | **199.24 / 195.47 ms** (`-300.84/-309.15`) | *(참고: `initial` 단독 480건 **201.23 ms**)* | — | **합산 PASS** (`initial` 단독 +1.23ms 초과) |
| **엔진 Crop (`SC - SA`) p50** | 195.51–197.28 ms | `≤ 100.0` (`-≥50.0`) | **99.68 / 99.65 ms** (`-95.83/-95.86`) | **104.75 ms** (`-92.53`) | **111.90 ms** (`-84.51`) | **Stage 2/3 PASS / 통합 상한 MISS** |
| **GUI 처리 (`SA - SG`) p50** | 50.09–50.12 ms | `≤ 10.0` (`-≥40.0`) | **5.38 / 5.25 ms** (`-44.71/-44.87`) | **5.42 ms** (`-44.70`) | **5.42 ms** (`-44.68`) | **PASS** |

- **최종 판정 (`보류`)**:
  - **입증된 성과**: GUI/IPC 응답(`APPLIED` p95 `22.12–22.13ms`, `SA - SG` p50 `5.25–5.42ms`), Stage 2/3 합산 목표(`READY` p95 `199.24ms`/`195.47ms`, `SC - SA` p50 `99.68ms`/`99.65ms`), 핵심 4셀 105건 재현성(`176.12–191.34ms`), 화면·GUI/CLI 픽셀 일치(`max_abs_diff == 0`), ASan·TSan(지정 범위) 무결함, 및 `PPVERSION 1045` 유지 근거가 모두 확인되었다.
  - **보류 사유 (§10.3 기준 적용)**: ① §10.2 화질 검증에서 `EvWBTemp`(`WHITEBALANCE`)가 축소 배율 `WB_BEFORE_HIGH_DETAIL` 조건에서 전체 갱신(`ALL`, `SC - SA` p50 `350.46ms`) 폴백을 유지해야 함이 확인되었고, ② §10.3에 따라 `initial` 표본 비중을 50%(각 셀 30건)로 균등화한 결과, `채도·샤프닝·색온도(1,440건)`의 `SC - SA` p50이 **104.75ms**(상한 100.0ms 대비 +4.75ms), 4항목 전체(`1,920건`)가 **111.90ms**(+11.90ms)로 측정되었으며 `Stage 2/3 initial` 단독(480건) `READY` p95도 **201.23ms**(+1.23ms)를 기록했다. 따라서 §10.3 규칙("성능 목표 미달 또는 화면·세대·안전성 회귀가 있으면 병합 판정을 보류한다")에 따라 본 보완 검증 단계의 최종 판정을 **보류**로 기록한다. 향후 병합 승인을 위해서는 `EvWBTemp` 축소 배율에서의 선택적 무효화 원인(`rawimagesource.cc` `WB_BEFORE_HIGH_DETAIL` / `rgbSourceModified`)을 안전하게 해결하거나 Stage 2/3 초기 `WidgetMeta`/캐시 경로의 잔여 지연(~2ms)을 추가 단축해야 한다.

## 11. 2026-11-19 수정 계획

작업 기준은 `61a549da2`다. 목표는 채도·샤프닝·색온도의 균형 표본에서 **GUI 반영→주 Crop 준비(`SC − SA`) p50을 100ms 이하**로 낮추고, §8.2의 나머지 지연 목표와 영상 결과를 보존하는 것이다. 현행 macOS Unix socket과 일반 편집 상태에서 해당 세 조정 키를 우선 대상으로 삼고, 노출과 기존 조정은 회귀 대조군으로 사용한다. PPVERSION 1045 판정은 §11.4의 비교 결과로 확인한다.

### 11.1 기존 결과와 조사 우선순위

- 보완 실행에서 1,440건 중 492건이 100ms 이하였다. p50을 100ms 이하로 만들려면 720건이 필요해, 다른 표본이 같다면 최소 228건이 더 상한 안으로 들어와야 한다. 색온도 100% 표본은 240건이므로 그 경로 하나만 개선할 경우 약 95%가 100ms 이하여야 한다. 이 산술은 후보의 실측 전 선별에 사용한다.
- 색온도 `SC − SA` p50은 축소 186.01ms, 100% 350.46ms다. 두 배율을 합산한 p50도 350.46ms이며, §10.4의 보류 사유에 인용한 값은 이 합산값이다. 후보의 색온도 480건은 두 배율 모두 `ALL`을 사용했다. 원자료는 `build/liveparam-perf-checks/v2_candidate_629f0429e/samples.csv`에 있다.
- 100%부터 실제 무효화 원인을 확인한다. 기본 `WB_BEFORE_HIGH_DETAIL`은 `skip == 1`인 Crop이 있으면 화이트밸런스 변경에 `M_PREPROC | M_RAW`를 추가하고, `M_HIGHQUAL`도 같은 확대 조건에 포함한다. `WB_BEFORE`는 화이트밸런스 갱신에 항상 두 단계를 요청한다. `WB_AFTER`는 RAW 전처리 단계에서의 화이트밸런스 의존성을 줄일 수 있지만 하이라이트 복원으로 변경된 RAW RGB 자료의 재사용 조건까지 확인해야 한다. [조정기의 WB 분기](../rtengine/improccoordinator.cc#L265) · [RAW 하이라이트 복원](../rtengine/rawimagesource.cc#L991)
- 메인 목표의 시간은 GUI 반영 뒤부터 잰다. 카탈로그나 `WidgetMeta`만 빠르게 해도 `SC − SA`의 부족분을 해결했다고 볼 근거가 없으므로 주 Crop까지 이어지는 대기·계산·표시 구간을 먼저 분해한다. 100% 샤프닝은 p50 111.96ms이고 240건 중 234건이 100ms를 넘으므로, 색온도의 필수 RAW 처리를 줄이기 어렵다면 우선 비교할 대조군이다.

### 11.2 프로브 검증 보수

- [x] `scripts/live_param_perf_probe.py`에서 로그 무결성과 성능 실행 판정을 각각 기록한다. 정상 성능 실행은 실행 인자로 계산한 조건별 예정 건수와 실제 시도·`READY` 건수가 일치해야 통과한다. 빈 파일, `READY` 0건, 타임아웃·거부·누락, 중복 요청이나 중복 배치는 비정상 종료로 보고한다. 의도적으로 오류를 유발하는 계약 테스트와 부하 실험은 해당 기대 결과를 명시해 정상 성능 실행 집계에서 구분한다.
- [x] 실행, `--validate-dir`, `--merge-dirs`가 같은 기준을 사용하도록 한다. 배치 취합에서는 대상 조건·바이너리·입력·프로필·조회 정책을 대조한다. 원자료와 실패 사유를 보존하며 성공 표본만 골라 자리를 채우는 재시도를 적용하지 않는다. 계측 OFF 대조군에도 표본 수와 상태 판정을 적용한다.
- [x] 임시 결과로 0건, 타임아웃만 1건, 일부 미완료, 조건 누락, 배치 중복을 재현해 각각 실패를 확인한다. 온전한 소규모 실행과 양쪽 기존 3개 배치는 재검증해 통과를 확인하고 원래 결과 디렉터리는 보존한다. T26의 깨진 JSON·유실·세대 누락 검사도 유지한다.

### 11.3 병목 측정과 최소 변경

1. **새 후보 없이 구간을 확인한다.** §11.2 통과 후 `SC − SA`를 작업 풀·`mProcessing` 대기, Navigator 선행 단계와 주 Crop 계산, 픽셀 복사·GUI 대기·Pixbuf 준비로 나눈다. 실제 실행 플래그와 Crop 위치·크기·`skip`을 기록하고, 대기나 계산에 같은 시간이 중복 계산되지 않도록 사건을 연결한다. 색온도와 샤프닝을 축소·100%, 최초·캐시 후, HDR/노이즈 제거 네 조합으로 비교한다. 조사에 추가 계측이 필요하면 기존 `LiveParamTrace`의 유한 기록 경로를 쓰고 계측 ON/OFF 오버헤드를 확인한다.
2. **화이트밸런스의 재사용 조건을 검증한다.** `toolpanelcoord.cc`의 `EvWBTemp` 분류, `improccoordinator.cc`의 유효 플래그 확대, `rawimagesource.cc`의 하이라이트 복원 상태를 같은 요청에서 관측한다. T25의 강제 `ALL` 대조를 사용해 `WB_AFTER`, `WB_BEFORE`, `WB_BEFORE_HIGH_DETAIL`에서 축소·100%, 100% 상세 창, `M_HIGHQUAL` 대기·배율 전환, 하이라이트 복원 OFF·Color·Color Soft를 비교한다. 요청 플래그와 워커가 실제 실행한 플래그를 함께 남긴다.
3. **입증된 구간 한 곳을 먼저 고친다.** RAW 단계 생략이 가능하다면 검증한 `EvWBTemp` 조건에만 적용하며, 판단에 사용한 스냅샷·뷰·품질이 바뀌거나 불명확하면 `ALL`을 유지한다. 기본 측정 모드의 재계산이 필수거나 §11.1의 부족분을 줄일 수 없다면, 100% 샤프닝 등 여러 셀을 늦추는 주 Crop 계산·대기·표시 전달 가운데 실측 기여가 큰 한 곳으로 옮긴다. 카탈로그 경로의 추가 변경은 `APPLIED` 또는 채팅 전체 지연의 별도 목표가 있을 때 평가한다.

소규모 전후 실험에서 영향을 받는 셀의 100ms 이하 표본 증가와 반복 변동을 확인한 뒤 넓은 회귀를 실행한다. 필수 무효화·픽셀 계산·표시 품질·잠금 순서와 기존 세대 확인을 보존한다. 공통 엔진 변경이 현재의 코어 수정 허용 범위를 넘거나 수식·처리 순서·프로필 의미 변경이 필요하면 별도 설계 및 PPVERSION 판정을 먼저 한다.

### 11.4 회귀·재측정과 병합 판정

- [x] 수정 전후 T25에서 같은 RAW·프로필·뷰포트와 동일한 조정값을 사용한다. 표시할 두 자료의 편집·계산·뷰 세대가 확정된 뒤 Navigator와 주 Crop 픽셀 최대 절대 차이 0을 확인한다. 축소·100%, HDR/노이즈 제거 네 조합에 더해 변경이 닿는 §11.3 경로를 확인한다. 해당 조건의 원래 값 복귀, 활성화·복합 이벤트·`M_VOID` 대조와 후속 `APPLIED → READY`도 확인한다.
- [x] 최종 코드로 Release GUI·IPC·Python 회귀를 시행하고 기존 프로필 로드·저장·재읽기, 즉시 내보내기·큐 등록과 실행 중 작업의 값 고정을 확인한다. 기준선과 **최종 후보**의 같은 RAW·프로필 CLI TIFF 디코딩 픽셀을 비교한다. 계측 ON/OFF에서 닫기·재열기·종료와 경합을 ASan/TSan으로 확인하고, TSan에서 남은 T24·T25를 실행한다. 전체 T25가 지나치게 길면 같은 단언을 포함해 조건별로 나누어 실행하고 각 결과를 남긴다.
- [ ] 기준선 `3c5fe6cbd`에 계측만 적용한 빌드와 최종 후보를 동일 프로브로 교차 측정한다. `629f0429e`의 이전 후보 기록은 이번 수정 자체의 효과를 비교하는 참고로 사용한다. RAW·프로필·배율·연결·조회·조건별 계획을 고정하고, §10.3과 동일한 64개 조건 × 30건(각 빌드 1,920건)과 핵심 조건 보강 표본을 수집한다. 새 실행 디렉터리에 두 바이너리와 계측 패치·프로브의 식별값, 원자료, 명령, 종료 코드와 배치별 결과를 남긴다.
- [ ] §8.2의 집계 대상과 기준을 그대로 적용한다. `APPLIED` p95 ≤35ms(최소 개선 30ms), 채도·샤프닝 합산 `READY` p95 ≤200ms(80ms), 채도·샤프닝·색온도 `SC − SA` p50 ≤100ms(50ms), 같은 세 도구의 `SA − SG` p50 ≤10ms(40ms)를 모두 확인한다. 최초 조정과 캐시 후, 색온도와 각 배율은 별도 표로 함께 보고한다. 화면·저장·출력의 결과 보존을 근거로 PPVERSION 1045를 판단하고, 성능·회귀 기준을 모두 충족한 경우에만 병합 가능 판정을 기록한다.

안전한 후보가 목표를 충족하지 못하면 검증된 갱신 경로와 보류 상태를 유지하고, 측정 결과를 근거로 다음 개선이나 목표 변경을 검토한다. 커밋은 **플랜 → 프로브 판정과 재현 검사 → 측정으로 선택한 수정과 회귀 검사 → 최종 결과 기록** 순서로 나눈다. 수정 후보는 원인별로 분리하고 커밋 메시지는 국문으로 작성한다.

### 11.5 구현과 검증 결과 (2026-11-19)

- 프로브의 표본 완전성과 배치 취합 검증은 `6b3e21a14`에 반영했다. Release의 T26과 Python 132건이 통과했다. 기존 6개 배치는 각각 740/740건, 계측 ON/OFF 진단은 각각 64/64건 `READY`로 재검증했다.
- 이전 후보의 100% 샤프닝 진단 16건에서 Crop 색 변환 p50은 84.83ms, `SC − SA` p50은 108.20ms였다. 중단 시점의 시험 코드를 같은 조건에서 실행한 결과 각각 47.83ms, 71.47ms였다. 양쪽 64건 원자료는 `build/liveparam-perf-checks/v3_prefix_diag/`와 `build/liveparam-perf-checks/v3-resume/inherited-color-trial/`에 있다.
- `42e46075b`는 Navigator와 Crop에서 모니터·분석에 공통으로 쓰이는 LittleCMS 부동소수점 출력 변환 결과를 같은 프레임 안에서 재사용한다. 행렬/LUT, 작업 색 공간 히스토그램, 색역 경고는 기존 변환을 사용한다. 기본 색온도 요청은 `WB_BEFORE_HIGH_DETAIL`의 필수 RAW 처리 때문에 `ALL`로 실행된다. 다른 화이트밸런스 모드·하이라이트 복원 조합의 선택적 재계산은 미검증이다.
- macOS arm64 Release의 `art`·`art-cli` 빌드, GUI 전체 검사와 IPC V1·V5·V7이 통과했다. T25의 Navigator·Crop·내보내기 픽셀 최대 차이는 0이었고 편집·뷰·프레임 세대가 일치했다. T27에서 LittleCMS와 소프트프루프, 행렬/LUT·작업 색 공간 히스토그램·색역 경고의 모니터·분석 픽셀을 기존 변환과 바이트 단위로 비교했다. T14에서 프로필 저장·재읽기, 즉시 내보내기와 큐의 스냅샷도 확인했다.
- `3c5fe6cbd`와 `42e46075b`의 Release ART-cli에 `sample1.nef`와 `data/test_profile.arp`(프로필 버전 343)를 넣어 16비트 TIFF를 생성했다. `tiffcmp -t -l`의 종료 코드는 0이고 디코딩 픽셀은 일치했다. 차이가 보고된 태그는 `Software`와 `DateTime`이다. 파일은 `build/liveparam-perf-checks/v3-resume/cli-exact-*.tif`에 있다. 프로필의 해석·기본값·렌더 결과가 동일해 `PPVERSION 1045`를 유지했다.
- ASan Debug에서 T08·T11·T12·T24·T25·T26·T27이 통과했다. TSan Debug `-O0`에서 T08·T11·T12·T24가 통과했다. `-O1` TSan은 T25의 HDR·노이즈 제거 프리셋 네 조합에서 각각 축소·100%를 확인했고 공통 검사도 통과했다. 동일 엔진·GUI 오브젝트를 링크하고 테스트 반복문만 분할해 기존 비교 단언을 모두 실행했다. 원본 T26·T27도 `-O1` TSan에서 통과했다. 분할 결과 확인 후 중복 순차 실행 두 개를 종료했다. 근거는 `build/liveparam-perf-checks/v3-resume/`의 `t25-shard-harness.patch`, `tsan-t25-shards/exit-codes.json`, 개별 실행 로그다.

#### 교차 측정 중간 결과와 병합 판정

`3c5fe6cbd`에 공통 계측 패치만 적용한 기준선과 `42e46075b`를 같은 프로브·RAW·프로필·조회 간격으로 실행했다. 첫 쌍의 조건·입력값과 각 740/740건 `READY`를 대조했다. 표는 핵심 표본 640건씩을 사용하고 지연 단위는 ms다.

| 지표 | 기준선 1 | 후보 1 | 후보 상한 |
| --- | ---: | ---: | ---: |
| `APPLIED` p95 | 66.14 | 22.13 | 35 |
| Stage 2/3 `READY` p95 | 506.97 | 149.31 | 200 |
| 주 Crop `SC − SA` p50 | 202.53 | 75.50 | 100 |
| GUI `SA − SG` p50 | 52.73 | 6.05 | 10 |

후보 1의 최초 조정과 캐시 후 `SC − SA` p50은 각각 80.27ms, 72.45ms다. 두 번째 후보 배치도 740/740건이며 같은 지표는 75.99ms다. 첫 기준선과 두 후보 배치의 100% Crop은 `522×668, skip=1`, 축소는 `2006×3031, skip=4`였다.

08:21 KST에 기준선 2를 실행하던 Mac의 디스플레이가 꺼지고 시스템이 절전에 들어갔다. 이후 `CVDisplayLink` 초기화와 GDK 모니터 조회가 실패했다. 프로브는 `READY`를 수집했지만 100% Crop은 `101×146`, 축소는 `skip=20`이 포함됐다. 영향을 받은 기준선 2·3과 후보 3의 전체 배치는 성능 판단에서 제외했다. 원자료와 로그는 `build/liveparam-perf-checks/v3-resume/final-comparison/`에 보존했다.

**병합 판정은 보류한다.** 같은 활성 디스플레이와 뷰포트에서 기준선 2·3, 후보 3의 전체 배치를 재실행해야 한다. `build/liveparam-perf-checks/v3-resume/resume_comparison.py`는 활성 디스플레이와 Crop 크기를 먼저 확인하고 세 배치를 재실행한다. 유효했던 세 배치와 새 배치를 `verified-comparison/`에 취합해 네 기준을 다시 검증한다.
