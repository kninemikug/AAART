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

## 검증 기록

### 빌드와 실제 렌더

`./scripts/build_art_cli.sh`로 이 워크트리에서 macOS arm64 Release 빌드에 성공했다. `build/AboutThisBuild.txt`에 기록된 빌드 기준은 `4000eb3eb`이다. `build/rtgui/ART-cli`의 SHA-256은 `f9d121456bdb6aaf28ac08500031c3ed21edcd258822dc0b88a9debd3ba332e8`이다. 엔진과 CLI의 CMake 컴파일 플래그에서 `-ffast-math` 미사용을 확인했다.

| 항목 | 실제 결과 |
| --- | --- |
| 입력과 요청 | `data/fivek_sample/sample1.nef`의 T18 특성, `노출 +0.5 EV` |
| 1차 시도 | 교체 런타임이 낸 미등록 키를 T19이 거부(`validation_error`). 오류 요약을 다음 프롬프트에서 확인 |
| 2차 시도 | 유효한 `.arp`로 실제 ART-cli 실행, 종료 코드 0 |
| JPEG | `build/t20-checks/sample1.jpg`, **1,548,386바이트**, 2006×3031, `djpeg -strict` 종료 코드 0 |
| JPEG SHA-256 | `c2a9bcc7c206a7714be3e45e0005e6534978cae6c77a24f862d45a3e4d1ae4ff` |
| 원본 보존 | 렌더 전후 RAW SHA-256 `18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805` 및 입력 디렉터리 파일 목록 일치 |
| 실행 증거 | `build/t20-checks/render.json`에 시도별 결과와 해시, `build/t20-checks/sample1.arp`에 실제 적용 프로필 보관 |

CLI는 사용자 처리 프로필 디렉터리 부재를 `stderr`로 보고했다. 시도 이력에서도 이 진단을 확인할 수 있다. 명시적으로 넘긴 프로필로 종료 코드 0과 새 JPEG 전체 디코딩을 확인했다. 기존 `scripts/test_art_cli.sh`에 같은 프로필을 넘긴 재실행도 성공했다. 외부 LLM을 사용하는 재생성과 macOS arm64 외 환경은 미검증이다.

아래 명령은 별도의 JPEG를 생성해 1차 결함 거부와 2차 실제 렌더를 재현한다.

```bash
T20_PYTHON=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python
mkdir -p build/t20-checks
PYTHONPATH=src ART_SETTINGS="$PWD/build/t20-checks/settings" \
  ART_CACHE="$PWD/build/t20-checks/cache" "$T20_PYTHON" - <<'PY'
import json
from pathlib import Path

from artagent.features import extract_features
from artagent.render.loop import render_or_retry


def fixture_runtime(prompt):
    exposure = {"Compensation": 0.5}
    _, marker, diagnostic = prompt.rpartition("\n렌더 재시도 진단(JSON): ")
    if marker:
        assert json.loads(diagnostic)["status"] == "validation_error"
    else:
        exposure["NonexistentKey"] = 1
    return {"raw_response": json.dumps({"groups": {"Exposure": exposure}, "reason": "요청 노출 반영"}),
            "metadata": {"provider": "deterministic-fixture"}}


raw = Path("data/fivek_sample/sample1.nef")
result = render_or_retry(raw, "build/t20-checks/sample1-replay.jpg", "노출 +0.5 EV",
                         extract_features(raw), cli_path="build/rtgui/ART-cli", runtime=fixture_runtime)
assert [entry.status for entry in result.attempts] == ["validation_error", "success"]
print(result.output_path, result.output_path.stat().st_size)
PY
djpeg -strict -outfile /dev/null build/t20-checks/sample1-replay.jpg
```

### pytest

`/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python -m pytest tests/test_render_loop.py -q`에서 **8개 통과**했다. 구현 전에는 새 렌더 모듈이 없어 수집에 실패했다. 실제 바이너리와 분리한 테스트에서 결함 프로필, 비정상 종료, 누락 및 빈 출력, 타임아웃, 진단 전달, 기존 파일 보존과 3회 상한을 확인했다.

같은 Python으로 `-m pytest tests/test_render_loop.py tests/test_arp_generator.py tests/test_arp_runtime.py tests/test_art_cli_script.py tests/test_features.py -q`를 실행해 관련 테스트 **279개 통과**를 확인했다.

기존 IPC 단일 테스트는 샌드박스에서 Unix 소켓 `bind` 권한 오류로 실패했다. 전체 검사는 로컬 소켓이 허용된 환경에서 실행했다. 첫 전체 검사는 T09 기준선의 프로토콜 지문 불일치로 **1,443개 통과, 51개 설정 오류, 경고 3개**였다. 저장된 프로토콜과 재현 결과를 비교해 `environment.python_executable`의 `venv/bin/python3`와 `venv/bin/python` 경로만 다른 것을 확인했다. 재실행은 기준선과 동일한 경로를 사용했다.

```bash
env -u T09_REPRO_DIR -u T09_SOURCE_ROOT -u T09_REFERENCE_PATH \
  PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 \
  -m pytest -p no:cacheprovider tests -q --tb=short
```

재실행은 종료 코드 0으로 **1,494개 통과, 경고 3개(436.23초)**였다. 경고는 Chroma의 `asyncio.iscoroutinefunction`과 Torch의 `max_length` 폐기 예고다. 전체 로그는 `build/t20-checks/pytest-full-python3.log`에 보관했다.
