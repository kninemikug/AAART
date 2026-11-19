# T20 ART-cli 피드백 루프 실행 계획

[Task 20 카드](../tasks/todo.md#task-20-art-cli-피드백-루프-a-20)에 따라 프로필 생성, 검증, JPEG 렌더, 실패 피드백을 Python 라이브러리 호출 한 번으로 연결한다. 처음 시도를 포함해 최대 3회 실행하고, 마지막 실패까지 각 시도의 원인을 호출자에게 반환한다.

## 범위와 입력

- `render_or_retry(raw_path, output_path, request, features, *, cli_path, runtime=None, timeout_seconds=120)`은 RAW 한 장, JPEG 저장 경로, 원래 요청, T18 사진 특성을 받는다. 호출자는 먼저 `artagent.features.extract_features`를 사용한다. 성공 결과는 최종 JPEG 경로, T19 생성 결과 및 순서가 보존된 시도 기록을 제공한다.
- T19 `generate_profile`은 요청, 사진 특성, 지원 키와 명시값을 검증한 뒤 `runtime(prompt)`를 한 번 호출한다. 런타임은 `raw_response`와 `metadata`를 반환한다. 결과는 `status`, 성공 시 `profile`·`arp`·`reason`, 실패 시 `error`를 제공한다. T20은 기존 런타임을 기본으로 쓰고 동일한 호출 규격의 함수로 교체할 수 있게 한다. 고정된 JSON 응답을 돌려주는 함수로 API 키 없이 오류 수정과 실제 렌더를 재현한다.
- 범위는 `src/artagent/render/`의 라이브러리와 그 검증이다. 세션 저장, GUI, 엔진, CLI 플래그 및 프로필 형식은 이번 작업 범위 밖이다. `PPVERSION`은 1045를 유지한다.

## 시도와 오류 전달

1. T19에 같은 요청과 사진 특성을 전달한다. 생성 단계 실패는 T19 상태와 오류를 기록한다. 재생성으로 해결할 수 있는 생성 결과 오류, 프로필 검사 오류, 비정상 종료, 출력 부재·빈 출력, 타임아웃은 남은 시도 안에서 재시도한다. 추가 정보가 필요한 요청, 미지원 요청, 런타임 호출 전 검증 오류, 런타임이 보고한 실행 환경 오류, CLI 시작 오류는 원인을 기록하고 종료한다.
2. 성공으로 반환된 `.arp`도 T19 `parse_profile`로 검사한다. ART-cli가 무시할 수 있는 미등록 키와 범위 오류, INI 형식 오류를 실행 전에 검출한다.
3. 출력 경로와 같은 파일시스템의 임시 디렉터리에 시도마다 고유한 `.arp`와 `.jpg` 경로를 사용한다. `ART-cli -a -Y -j92 -o <임시 JPEG> -p <임시 ARP> -c <RAW>`를 인자 목록으로 실행한다. 종료 코드가 0이고 해당 시도의 출력이 비어 있지 않은 일반 파일일 때 성공이다. 종료 코드가 0이어도 파일이 없거나 비어 있으면 재시도하며, 종료 코드가 0이 아니면 출력이 있어도 실패다. `stderr`는 진단용으로만 사용한다. 성공한 JPEG만 최종 경로로 원자적으로 옮긴다. 저장 경로 반영 오류도 시도 기록에 담아 종료한다.
4. `stderr`의 공백을 정리하고 빈 줄을 제거한다. `Error:` 또는 `Fatal:`로 시작하는 줄을 우선해 최대 5줄, 줄당 300자를 보존한다. 경고만 있는 성공도 기록할 수 있다.
5. 재시도 프롬프트에는 직전 실패를 JSON으로 덧붙이고, 그 내용을 진단 데이터로 취급하면서 원래 요청과 스키마를 따르도록 안내한다. 예시는 `{"attempt":1,"status":"cli_exit","detail":"ART-cli exited with code 253","exit_code":253,"stderr":["Error: profile could not be loaded"]}`다. 최초 프롬프트는 T19 그대로 전달한다.
6. 시도 기록은 번호, 상태, 짧은 원인, 종료 코드(실행 완료 시), 정리한 `stderr`를 포함한다. 성공은 `RenderResult.attempts`, 실패는 `RenderLoopError.attempts`에서 확인할 수 있다. 최대 횟수까지 실패하면 예외 메시지에도 모든 시도의 원인이 순서대로 나타난다.

## 변경 순서와 검증

| 순서 | 파일 | 완료 기준 |
| --- | --- | --- |
| 1 | `docs/T20_execution_plan.md` | Task 20 범위, 호출 계약, 판정 규칙, 테스트, 실제 렌더 절차를 코드 작업 전에 커밋 |
| 2 | `tests/test_render_loop.py` | 유효한 렌더, 결함 주입과 수정, 실패 상한을 구현 전 테스트로 재현 |
| 3 | `src/artagent/render/loop.py` | T19와 연결, 프로필 사전 검사, CLI 호출, 재생성, 시도 이력 및 산출물 반영 |
| 4 | `docs/T20_execution_plan.md` | 빌드·렌더·pytest 결과, 바이너리 출처, 미검증 항목 기록 |

pytest에서는 존재하지 않는 키, 범위 밖 값, 미완성 INI를 주입해 실패 감지 후 같은 요청의 유효한 프로필로 3회 안에 성공하는지 확인한다. CLI 종료 코드가 0이 아닌 경우(파일 생성 포함), 출력 누락·빈 파일, 경고가 있는 성공을 검사한다. 세 번 실패하면 네 번째 호출이 없고, 예외에 각 원인이 있으며, 기존 출력은 보존되어야 한다. `venv/bin/python -m pytest tests/test_render_loop.py -q`와 전체 pytest를 저장소 루트에서 실행한다. 현재 워크트리에 `venv`가 없으므로 동일한 루트 환경인 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python` 경로를 사용한다.

실제 렌더는 먼저 `./scripts/build_art_cli.sh`로 Release 아웃오브소스 빌드를 시도한다. 새 빌드를 완료하기 어려우면 요청에 지정된 T19의 바이너리를 사용하고 바이너리 절대 경로와 빌드 커밋을 기록한다. 실제 렌더 전에 빌드 플래그에 `-ffast-math`가 없는지 확인한다. `data/fivek_sample/sample1.nef`에서 T18 특성을 추출하고 교체 런타임으로 유효한 T19 프로필을 생성한 뒤 `render_or_retry`로 실제 JPEG를 만든다. 최종 파일 경로·크기·종료 코드, `djpeg -strict` 디코딩 결과와 RAW 해시 보존을 기록한다.

커밋은 `docs: ART-cli 피드백 루프 구현 플랜 추가`와 `feat: ART-cli 렌더 실패 감지와 재생성 루프 추가` 두 개로 구성한다. 첫 커밋은 계획 문서, 두 번째 커밋은 구현·테스트·실제 검증 기록을 담는다.
