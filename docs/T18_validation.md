# Task 18 보완 검증 기록

검증일: 2026-10-13 · 구현 검토 기준: `73579016d` · 계약: [실행 플랜](T18_execution_plan.md)

## 변경 내용

- `extract_features`와 수치 함수는 float64 계산 정밀도를 유지한다. `dumps_features`만 실수를 소수 6자리로 반올림하며, 입력 객체와 이미 결정한 신호를 바꾸지 않는다. 키 정렬·UTF-8·마지막 개행을 고정한다.
- 휘도 `0.17989951`은 반올림 전 값으로 `is_dark=true`가 된다. 어두움·노란색 지수의 보류 경계 안팎을 실제 픽셀 배열로 검증한다. 셔터 유리수와 WB 계수도 직렬화 전까지 정밀도를 유지한다.
- Exiv2의 선택된 실행 파일로 `--version`과 메타데이터 읽기를 수행한다. 디코더도 PATH에서 선택한 실행 파일을 고정해 호출하고 SHA-256을 기록한다.
- `dcraw_emu`에는 버전 옵션이 없다. 해당 실행 파일 설치의 `lib/pkgconfig/libraw.pc`에서 패키지 버전을 읽고 `decoder.version_source=libraw.pc`로 출처를 표시한다. 패키지 정보가 없으면 버전·출처는 `null`이며 실행 파일 해시로 식별한다. 다른 전역 설치의 버전으로 대체하지 않는다. 이는 설치 패키지의 버전 기록이며 디코더가 직접 출력한 버전은 아니다. 근거: [LibRaw 공식 예제 소스](https://raw.githubusercontent.com/LibRaw/LibRaw/0.22.2/samples/dcraw_emu.cpp).
- 자식 프로세스에 `OMP_NUM_THREADS=1`, `OMP_THREAD_LIMIT=1`, `OMP_DYNAMIC=FALSE`, `LC_ALL=C`, `LANG=C`를 전달한다. 부모 환경은 수정하지 않는다. 설치된 디코더의 별도 진단에서도 `Using 1 threads`를 확인했다. 환경은 프로세스 시작 전에 전달한다. 근거: [OpenMP 환경 변수 규격](https://www.openmp.org/spec-html/5.2/openmpch21.html).
- 16개 bin 각각의 counts·확률, 모든 내부 경계의 바로 아래·경계값·바로 위, 0과 1의 배치를 검증한다. 디코딩 PPM의 해시도 기준값과 대조한다.

JSON의 기존 최상위 구조와 schema/pipeline/rules 버전은 유지한다. `analysis.decoder`에 `sha256`·`version_source`, `analysis`에 `ppm_sha256`을 추가한다. T19는 객체 입력에서 전체 정밀도를 사용할 수 있고, 저장·전달할 JSON 문자열은 `dumps_features`로 만든다. 반올림된 JSON 수치로 신호를 다시 판정하지 않는다.

## 고정 샘플과 독립 대조

| 항목 | 확인값 |
|---|---|
| 입력 | `data/fivek_sample/sample1.nef`, 5,533,313바이트 |
| 입력 SHA-256 | `18e287009b15b20fc73fd2223ed1551231f3853398a38a7b0a4308b630e1f805` |
| 도구 | Exiv2 0.28.8, LibRaw 패키지 0.22.2, NumPy 2.5.3 |
| 선택 디코더 SHA-256 | `87231c7b8e3923e2ae701a8b28074fcc98a8f6932835b2597162dc2687a31e40` |
| PPM SHA-256 | `d6c0d4098988e60104c90d3b737b5ad0172c941c816ccbde858605f0c1bba176` |
| 크기 | 3039×2014, 6,120,546픽셀, 선형 sRGB 16비트 |
| 촬영 정보 | ISO 200, 셔터 1/200초, Nikon D70, WB AUTO |
| 평균 휘도 / 채도 | `0.12383494352000035` / `0.45569380057466047` |
| 그림자 비율 | `0.37190587244994155` |
| 노란색 지수 / 적녹 불균형 | `-0.009399956166449671` / `0.07044517261035904` |
| 신호 | `is_dark=true`, `yellow_tendency=false` |

디코더의 PPM 바이트를 별도로 읽어 정수 bin 인덱스와 counts를 집계했다. 채널 평균의 기준값은 uint16 픽셀을 정수로 합산한 후 `픽셀 수×65535`로 한 번만 나누어 확인했다. R/G/B 정수 합은 각각 `57958062951`, `46785065609`, `53862449764`다. 분포 전체 기준값은 [고정 샘플 테스트](../tests/test_features.py)에 보관한다.

정밀 검증 중 휘도 0.05 경계의 픽셀 하나를 확인했다. RGB 정수 `(4232,3113,2086)`은 `2126R+7152G+722B=500×65535`이므로 그림자 조건 `Y<0.05`에 포함되지 않는다. 소수 계수를 먼저 곱하던 계산은 이를 `0.049999999999999996`으로 만들었다. 동일한 휘도식을 정수 계수로 스케일하여 나눗셈 전에 경계를 비교하도록 수정하고, 이 픽셀과 인접 값의 회귀 사례를 추가했다. 오차 기준을 늘리지 않았다.

## 실행 검증

프로젝트의 기존 Python 3.14 venv를 사용했다. 바이트코드·pytest 캐시를 생성하지 않고 고정 샘플을 읽었다.

```bash
env PYTHONDONTWRITEBYTECODE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests/test_features.py tests/test_smoke.py -q
```

결과: **79 passed**. 새 정밀도·실행 환경 회귀 테스트는 수정 전 실패를 확인했다. 기존의 같은 입력 3회 JSON 바이트 일치와 원본 보존 테스트도 통과했다.

별도 프로세스에서 bin 1·2를 고의로 교환한 결함 주입 검사는 **7 failed, 41 passed**였다. 고정 샘플의 bin별 대조와 경계 테스트가 이 잘못된 분포를 검출했다. 이 검사는 소스 파일을 변경하지 않는다.

fixture 보완 전 전체 회귀 검사는 아래 명령으로 실행했다. `src` import 경로를 지정하고 기존 캐시를 사용하도록 다운로드를 막았다.

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests -q --tb=line
```

보완 전 결과: **463 passed, 39 errors, 1 warning**. 39개는 모두 이 작업 폴더의 `data/vector-store/t09` 부재로 기존 `tests/test_issue_update.py`의 실물 저장소 fixture를 준비하지 못한 오류였다. 테스트 본문에 진입하기 전에 `shutil.copytree`에서 실패했다. 이 시점에는 저장소 준비 로직을 변경하지 않았으며 전체 테스트 통과로 보고하지 않았다. Task 18의 79개 focused 검사는 모두 통과했다.

## T9 테스트 입력 준비 보완

`data/vector-store/`는 Git 추적 대상이 아니다. 메인에 합쳐진 코드를 포함하더라도 각 작업 폴더에 실물 DB가 생기지는 않는다. 테스트는 다른 작업 폴더의 DB를 복사하는 대신, 저장소에 추적된 고정 인계 입력으로 초기 상태를 재현하도록 보완했다.

- [공통 fixture](../tests/conftest.py)는 세션마다 `tmp_path_factory` 아래에서 기존 `scripts/reproduce_t08_2_selected.py`를 실행한다. 현재 작업 폴더의 참조 문서·원문·고정 모델 revision을 사용하며, 모델·토크나이저는 설치된 캐시에서만 읽는다. 캐시가 없으면 준비 오류와 로그 경로를 제공하고 다운로드하거나 검사를 생략하지 않는다.
- [초기 저장소 준비](../tests/t09_test_data.py)는 참조 문서 SHA-256, 선택 실험, 프로토콜, 청크·벡터 지문, 검색 지표와 쿼리 로그의 재현 증거를 대조한다. 원문의 출처·파일 지문을 검증한 154개 청크를 기존 색인 함수로 저장한다.
- 계산 직후 벡터와 재현된 벡터 파일은 고정 SHA-256에 정확히 일치해야 한다. 저장 후 읽은 float32 벡터에는 `rtol=0`, `atol=1.1920928955078125e-7`을 적용한다. 직접 대조에서 저장 전후 최대 차이는 `1.4901161193847656e-8`이었다. 이 기준은 기존 인계 문서의 `atol=1e-6`, `rtol=1e-5`보다 엄격하다. 저장 표현의 미세한 차이 때문에 계산 단계의 지문 기준을 바꾸지 않는다.
- 초기 DB를 만드는 프로세스와 다시 여는 검증 프로세스를 각각 종료한 후 복사한다. 모든 청크 ID·본문·출처 정보·벡터와 `ready` 상태, RawPedia 141개·GitHub 13개를 확인한다. 갱신 테스트는 각자의 `tmp_path`에 독립 복사본을 받는다.
- [검색 테스트](../tests/test_retrieval.py)도 같은 재현 fixture를 사용한다. 다른 작업 폴더 및 `/private/tmp`의 최신 파일을 암묵적으로 선택하던 동작을 제거했다. 명시적인 `T09_REFERENCE_PATH`, `T09_SOURCE_ROOT`, `T09_REPRO_DIR` 지정은 유지하되, 지정한 재현 증거가 불완전하거나 기준과 다르면 실패한다.
- [갱신 테스트](../tests/test_issue_update.py)에 초기 상태와 복사본 변경 후 기준 DB의 파일 바이트 보존 사례를 추가했다. [재현 증거 테스트](../tests/test_t09_test_data.py)는 누락·변경된 증거의 거부를 확인한다. 기존 갱신·검색 테스트의 판정 기준과 실행 여부는 유지한다.

수정 전 새 초기 상태 검사는 기존 실물 DB 부재로 실패했다. 보완 후 관련 검증은 **18 passed, 40 deselected**였다. 검증 중에도 현재 작업 폴더의 `data/vector-store/t09`는 만들지 않았다.

전체 회귀 검증에서는 경로 지정 세 가지를 해제하여 임시 입력과 초기 DB를 새로 준비한다. `src` import 경로는 공통 fixture에서 설정한다.

```bash
env -u T09_REPRO_DIR -u T09_SOURCE_ROOT -u T09_REFERENCE_PATH PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests -q --tb=short
```

보완 후 결과: **520 passed, 1 warning** · 232.17초. 기존 39개 fixture 준비 오류를 포함한 전체 검사가 통과했다. 새 임시 경로의 재현 증거에서 참조 SHA-256 일치, 청크 141개·13개, 검색 기록 300개를 확인했다. Top5 거리의 최대 재현 차이는 `3.5762786865234375e-7`로 기존 `1e-5` 기준 안이다. 작업 폴더의 `data/vector-store/t09`는 검증 전후 모두 부재했다. 경고 1개는 설치된 Chroma가 사용하는 `asyncio.iscoroutinefunction`의 폐기 예고다. skip·xfail·경고 억제는 추가하지 않았다.
