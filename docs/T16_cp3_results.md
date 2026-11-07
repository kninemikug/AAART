# T16 실제 검색·생성 연결 검증

2026-11-07. **검색·생성·그래프·GUI 브리지·REPL 연결은 통과했다. 실제 화면의 전송·답변 표시·취소·종료는 접근성 권한 오류로 미검증이며, CP3 전체 완료로 판정하지 않는다.** 제품 소스는 수정하지 않았다.

## 실행 조건과 증거

실행 코드는 `4a1a9e21e`다. Python 3.14.3, 루트 venv, `codex-cli 0.166.0`, 기본 생성 모델 `gpt-5.6-sol`을 사용했다. 실제 생성 제공처는 한 곳만 사용했으며, 재실행으로 모델이나 검색 설정을 튜닝하지 않았다.

증거는 [cp3_20261107](../data/eval/t16-cp3/cp3_20261107/)에 보존했다.

- [manifest.json](../data/eval/t16-cp3/cp3_20261107/manifest.json): 고정 질문·T11 기록·검색 참조의 해시, 실행 커밋과 등록 코드 24개, 모델·검색 설정.
- [runtime-files.json](../data/eval/t16-cp3/cp3_20261107/runtime-files.json): CLI·GUI 브리지를 포함한 실행 소스 32개의 Git 원본·작업 파일 해시.
- [records.jsonl.gz](../data/eval/t16-cp3/cp3_20261107/records.jsonl.gz): 원질문, 실제 생성 입력·원응답·호출 수, 검색 후보·근거·출처, 노드 갱신과 최종 상태. 추가 외부 도구 실행은 0건이다.
- [store-verification.json](../data/eval/t16-cp3/cp3_20261107/store-verification.json): 선택 참조와 재현 증거가 일치하는 별도 Chroma 저장소를 원문·메타데이터·154개 청크·벡터와 대조한 결과. 사용한 재현 입력은 pytest-452의 보존 자료이며 새로운 검색 품질 반복 실험으로 세지 않는다. 운영 저장소는 수정하지 않았다.
- [bridge-records.jsonl](../data/eval/t16-cp3/cp3_20261107/bridge-records.jsonl), [gui-records.jsonl](../data/eval/t16-cp3/cp3_20261107/gui-records.jsonl), [cli-record.json](../data/eval/t16-cp3/cp3_20261107/cli-record.json): 실제 프로세스의 입출력과 브리지 관측 기록.

15문항과 추가 3문항의 그래프 실행은 T15 채택 설정을 명시했다. 최초 재작성 on·HyDE off, BM25, 후보 20, top5, `min_score=0.5`, 결합가중치 0.25다. 검색·인용의 제품 범위는 RawPedia=RawTherapee 참조, GitHub=ART의 수집 시점 기록으로 유지했다. 추가 재검색은 같은 설정·출처·지정 글 필터를 사용했다.

GUI 브리지와 REPL은 현재 기본 설정인 최초 재작성 off·HyDE off·리랭커 없음·후보 10/top5를 사용했다. 두 설정을 같은 조건의 반복 실험으로 합산하지 않는다. 검색 점수는 기존 후보 선택에만 쓰고, 폴백은 T17의 `INSUFFICIENT_EVIDENCE`에만 연결된다.

첫 샌드박스 생성 호출은 하위 프로세스의 로컬 통신 권한 부족으로 실패했고, 허용된 실행에서는 정상 응답했다. 최초 Q001 연결 실행은 관측 콜백의 JSON 직렬화 오류로 완성 기록을 보존하지 못했다. 관측기만 수정한 뒤 고정 묶음을 실행했으며, 이 준비 실패를 성공 건수나 품질 반복 횟수에 포함하지 않았다. 제품 코드의 생성 실패로 분류하지 않는다.

## 실제 실행 결과

| 범위 | 관측 결과 |
| --- | --- |
| 고정 Slice 1 15문항 | 14건 `SUPPORTED` → `COMPLETED`, Q096 1건 `UNSUPPORTED`. 기술 오류 0건, 추가 재검색 0건. 각 최초 재작성 1회·검색 1회·답변 1회. |
| 제품 범위 Q010·Q077 | 모두 근거 인용과 RawTherapee 범위 유지. ART의 동일 기능·UI를 단정하지 않음. |
| 자료에 없는 지정 Issue 질문 | 실제 생성의 `INSUFFICIENT_EVIDENCE` → 추가 재작성 → 정상 빈 검색 → 실제 재답변도 부족 → 종료. `research_count=1`, 검색 2회·답변 2회. 최초 재작성까지 생성 4회. |
| GUI 브리지 5요청 | Q001 문서, Q086 문제 해결, Q096 반증, 지정 Issue 부족, 일반 자동 보정 실행 요청 차단. 모두 정상 JSON·종료 코드 0, 4.06~15.40초. |
| 실제 REPL 3요청 | Q001·Q096·지정 Issue를 연속 처리하고 `/quit`로 정상 종료. 출처 URL과 세 상태가 콘솔에 유지됨. 전체 27.73초. |

그래프 18요청에는 실제 생성 38회가 보존됐다. 브리지 5요청의 생성은 6회, REPL 3요청은 5회다. 총 **26개 완성 요청·49개 생성 호출**이며, 별도 연결 확인 1회와 준비 실패는 이 합계에서 제외했다. 모델 응답을 대역으로 바꾸거나 부족 상태를 강제로 주입하지 않았다.

자료에 없는 질문은 `GitHub Issue #999999999에서 보고한 ART 오류의 원인과 해결 방법은 무엇인가요?`다. 고정 코퍼스에 없는 대상을 지정해 정상 빈 검색을 만드는 통제 질문이며, 실제 보고된 문제나 지원 답변의 복구 성공 사례로 해석하지 않는다. 지정 글 필터를 넓히지 않았고 두 답변은 모두 실제 생성 결과다.

GUI 기본 설정의 부족 trace는 다음과 같다.

```text
INTAKE → ROUTE → DISPATCH → SEARCH_GITHUB → ANSWER
→ RESEARCH → SEARCH_GITHUB → ANSWER → FALLBACK → ADVANCE → RESPOND
```

Q096은 `RESEARCH` 없이 `UNSUPPORTED`로 종료했다. 반증 출처는 Issue #500의 `#issuecomment-4711197631`이며, 품질이 visually lossless로 고정되어 있다는 설명을 근거로 존재하지 않는 품질 슬라이더 절차를 거부했다. EXECUTE 요청은 `DISPATCH → FALLBACK → ADVANCE → RESPOND`로 차단했고 검색·생성은 수행하지 않았다. 이는 분기 확인이며 프로필 생성·렌더링 기능의 완료 증거가 아니다.

## 고정 15문항 수동 대조

T11 원응답, 이번 답변, 고정 질문의 근거 구절과 실제 인용 세그먼트를 대조했다. 문장 일치가 아니라 질문의 핵심 사실·제품 범위·인용의 지지 관계를 평가했다. 13문항은 동등, Q044·Q086은 근거 확보 측면에서 개선됐다. 이는 T15 설정을 포함한 연결 전체의 결과다. 15문항에서는 폴백이 발생하지 않았으므로 이 개선을 T16만의 효과로 주장하지 않는다. 기존 고정 질문을 독립 평가셋으로 세지 않는다.

| 질문 | 검토한 핵심 사실·범위·인용 | T11 대비 |
| --- | --- | --- |
| Q001 | 히스토그램 분석 후 Exposure 조정. RawTherapee로 범위를 명시하고 Exposure 인용. | 동등 |
| Q004 | Amount 증가 시 범위 축소, Detail 양수는 대비 보존·음수는 대비 감소. 해당 문서 인용. | 동등 |
| Q014 | Depth Map의 밝은 영역에 효과가 강함. Haze Removal 인용. | 동등 |
| Q021 | 고채도 카메라 데이터를 작은 색역으로 압축. 작업 프로파일 복원·음수 값 설명도 실제 세그먼트와 일치. | 동등 |
| Q033 | 포토사이트 수치와 색 매핑·DCP의 역할. 노이즈·동적 범위 등 모든 물리 한계를 보정한다고 추측하지 않음. | 동등 |
| Q044 | 계조 정밀도와 계산·메모리·공간 비용을 Bit Depth에서 확보. 추가 부동소수점 설명도 인용 문서에 존재. 기존 답변은 근거 부족. | 개선 |
| Q054 | 1.0 미만 대비 감소, 초과 대비 증가. Contrast by Detail Levels 인용. | 동등 |
| Q063 | 대상 Ctrl-click 후 드래그로 소스 지정, 소스가 대상을 대체. Spot Removal 인용. | 동등 |
| Q072 | Fill의 기본값 대체와 Preserve의 누락값 유지. RawTherapee 부분 프로필 범위 유지. | 동등 |
| Q080 | config·cache 역할, images 삭제 후 설정 유지·썸네일 재생성. 실제 삭제 없이 File Paths 설명만 검토. | 동등 |
| Q084 | LUT 점 연산과 공간 연산 차이, Smoothing의 Halation·Add noise 경로. Discussion #424의 정확한 댓글 인용. | 동등 |
| Q086 | 이름 지정 후 Linked mask, 처리 순서상 뒤·화면상 아래 도구에서 재사용. #15597989 인용, 텍스트에 없는 이름 입력 UI를 만들지 않음. 복사·붙여넣기 제약도 #15603701로 지지. 기존 답변은 대상 글을 찾지 못함. | 개선 |
| Q092 | 자가 빌드와 AppImage의 브라우저·편집기 차이, 구형 스크립트·캐시 삭제와 해결 확인. 세 댓글 인용. | 동등 |
| Q093 | `/usr/share/lensfun/version_1` 경로와 드롭다운 회복. Issue #521의 해당 댓글 인용. | 동등 |
| Q096 | JXL 품질 슬라이더 전제 거부, fixed visually lossless와 정확한 반증 댓글. 재검색 없음. | 동등 |

집중 표본 Q001·Q086·Q096, CP2 양성 Q001·Q004·Q014·Q054·Q063을 모두 포함한다. 추가 Q010은 Local Contrast의 Darkness/Lightness와 둘 다 0일 때 비활성화를 RawTherapee 범위로 답했다. Q077은 부분 저장 Ctrl+Save·최소 설정·촬영별 변동 이유를 인용하고 ART의 동일 UI를 단정하지 않았다.

## 화면 검증의 남은 조건

현재 채팅 패널·연결·입력 소스 및 헤더 5개가 일치하는 `T-live-param`의 `ARTChatControls.app`을 별도 `ART_SETTINGS`·`ART_CACHE`로 실행했다. [gui-launch.json](../data/eval/t16-cp3/cp3_20261107/gui-launch.json)에 바이너리와 소스 지문을 남겼다. 새 설정은 현재 Python 소스·검증용 저장소를 가리키며 수치 조정은 꺼져 있다. 사용자 사진은 열거나 수정하지 않았다.

[시작 화면](../data/eval/t16-cp3/cp3_20261107/gui-startup.png)은 확인했지만, 조작 도구가 `window_not_focused` 후 `permission_denied`를 반환했다. 권한 조회에는 허용으로 표시되지만 실제 창 접근은 차단됐다. [관찰 기록](../data/eval/t16-cp3/cp3_20261107/gui-observation.json)에 시도와 오류를 구분했다. 이후 화면 조작을 우회하지 않았으며 접근성 권한 재설정을 요청했다. 검증용 프로세스만 정리했고 기존 앱은 유지했다.

`gui-python`은 환경을 고정하고 실제 `gui_bridge.main()`·그래프 결과를 관측하는 실행기다. 응답과 라우팅은 바꾸지 않는다. 표준입출력 브리지 검증은 통과했지만 실제 패널에서 질문 전송·답변·출처 표시·취소·종료를 확인한 증거를 대신하지 않는다. 이 화면 항목과 실제 프로필 실행·렌더링은 미검증으로 남긴다.

## 재검사

아래 명령은 외부 생성 호출 없이 압축된 기록을 검사한다. 원문과 Git 원본이 있는 저장소 루트, 같은 Python 환경에서 실행한다. 저장소·캐시·앱 설정은 로컬 검증 자료여서 커밋에 포함하지 않는다. 저장소를 다시 만들려면 기존 `scripts/reproduce_t08_2_selected.py`와 `tests/t09_test_data.py build/verify` 절차를 새 디렉터리에서 사용한다.

```bash
T16_PYTHON=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
PYTHONDONTWRITEBYTECODE=1 "$T16_PYTHON" data/eval/t16-cp3/cp3_20261107/audit.py records
PYTHONDONTWRITEBYTECODE=1 "$T16_PYTHON" data/eval/t16-cp3/cp3_20261107/audit.py fallback
PYTHONDONTWRITEBYTECODE=1 "$T16_PYTHON" data/eval/t16-cp3/cp3_20261107/audit.py interfaces
PYTHONDONTWRITEBYTECODE=1 "$T16_PYTHON" data/eval/t16-cp3/cp3_20261107/check_audit_controls.py
```

실행 당시 관측기 원본은 `run-at-execution.py.gz`에 보존했으며 manifest의 해시와 일치한다. 현재 `run.py`에는 압축된 기존 결과가 있을 때 재실행을 거부하는 검사만 추가했다. 봉인된 디렉터리에서 생성 명령을 다시 실행하지 않는다. 과거 T11/T14/T15 기록은 변경하지 않았다.

검사는 원질문, 코드·입력 지문, 실제 생성 정책·도구 사용 0건, 원문 세그먼트, 출처·설정·지정 글 보존과 호출 수를 확인한다. 추가 예산 초과·미지원 상태 변조·외부 도구 실행·원문 변조·세 번째 검색의 5개 반례를 모두 거부했다. 관련 pytest는 **133개 통과**, 종료 코드 0, 7.02초이며 기존 Chroma 경고 1건을 숨기지 않았다. 제품 소스가 기존 전체 회귀 1,272개 통과 시점과 같아 전체 검사를 반복하지 않았다.

[검증표](T16_cp3_GATES.md)는 5개 중 4개 충족, 화면 항목 1개 대기다. 품질·연결 범위의 오류는 발견하지 못했으나 화면 검증과 실행 기능까지 문제가 없다고 결론내리지 않는다. C++·프로필·영상 처리 의미 변경과 새 의존성 설치는 없으며, PPVERSION 증가와 재빌드는 수행하지 않았다.
