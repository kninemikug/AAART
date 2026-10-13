# Task 18 실행 플랜 — 사진 특성 추출

작성일: 2026-10-13 · 대상: T18 / A-19 · 구현 담당: B · 상태: 계획 작성 완료, 구현 전

## 1. 목적과 범위

고정 입력 `data/fivek_sample/sample1.nef`에서 EXIF의 ISO·셔터·카메라·화이트밸런스(WB)와 히스토그램 통계의 평균 휘도·평균 채도·RGB 채널별 분포를 추출한다. 결과를 JSON으로 전달하여 T19가 사용자 요청과 함께 사진의 밝기·색 경향을 판단하는 데 사용하도록 한다.

근거는 [tasks/todo.md의 Task 18](../tasks/todo.md#task-18-사진-특성-추출-a-19) 전문, 같은 문서의 [Task 1](../tasks/todo.md#task-1-프로젝트-부트스트랩-a-01)과 [Task 19](../tasks/todo.md#task-19-arp-구조화-생성기-a-18), [실행 WBS v2.5 §5](ART_agentic_wbs.md), [의존 구조](../tasks/plan.md)다. Task 18의 완료 조건 두 가지를 그대로 유지한다.

- `sample1.nef`에서 표준 EXIF 필드를 추출한다.
- 히스토그램 통계가 “어둡다/노랗다” 판단에 쓸 수 있는 수치로 출력된다. 검증은 샘플을 고정한 pytest로 수행한다.

이번 작업의 산출물은 이 문서 한 개다. 아래 모듈·함수·테스트는 구현 계획이며 아직 작성하지 않았다. 이번 작업에서는 `src/`·`tests/` 변경, 샘플 다운로드, 의존성 설치, RAW 디코딩을 수행하지 않는다. 기존 터미널의 세션·내용을 조작하지 않으며 push와 PR 생성도 수행하지 않는다.

후속 T18 구현은 특성 추출에 한정한다. `.arp` 키 선택·프로필 생성·PPVERSION 검증은 T19, ART-cli 실행과 재시도는 T20의 범위다. ART 코어, 전체 FiveK 확보, 씬 라벨링, 새 패키징·설정 로더는 작업 범위에 포함하지 않는다.

## 2. 확인한 현황과 착수 조건

조사 기준은 현재 작업 폴더의 HEAD `a676913b6`이다. 설치 현황은 PATH 검색, 도구의 버전·사용법 출력, 프로젝트 venv의 배포 패키지 메타데이터로 확인했다.

| 항목 | 확인 결과 | 구현 시 처리 |
|---|---|---|
| `data/fivek_sample/sample1.nef` | **부재** | 확보·정합 확인 후 해시와 기준값을 고정한다. 현 상태에서 실제 샘플 검증 완료로 보고할 수 없다. |
| `data/fivek_sample/sample1.dng` | 29바이트, 내용은 `DUMMY_RAW_CONTENT_FOR_TESTING` | 실제 RAW가 아니므로 고정 입력의 대체 파일로 사용하지 않는다. |
| 기존 샘플 확보 스크립트 | `scripts/download_sample_raw.py`가 Nikon D70 NEF를 `sample1.nef`로 저장하도록 작성되어 있음 | 스크립트는 읽기만 했다. 다운로드 성공·파일 출처 정합은 미확인이다. 폴더 이름만으로 FiveK 소속을 주장하지 않는다. |
| `src/artagent/__init__.py`, `tests/test_smoke.py` | 존재. 기존 venv로 실행한 스모크 테스트 **1 passed** | T1의 import·테스트 실행 방식을 재사용한다. |
| 실행·설치 기록 | `docs/pipeline_setup.md` 존재 | 추가 설치가 실제로 필요해지는 구현 단계에서 같은 기록에 추가한다. |
| 프로젝트 venv | `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3`, Python 3.14.3 | 작업 폴더에는 별도 `venv/`가 없다. 기존 프로젝트 venv를 사용한다. |
| venv 패키지 | pytest 9.1.1, NumPy 2.5.3 설치. rawpy·Pillow·ExifRead·PyExifTool 미설치 | 설치된 도구를 우선 검토한다. 새 패키지 목록이나 `requirements.txt`를 만들지 않는다. |
| `exiftool` / `exiv2` | `exiftool` 부재. `/opt/homebrew/bin/exiv2`, 버전 0.28.8 | Exiv2의 읽기 출력과 원문 태그를 표준 필드로 정규화하는 방안을 우선한다. |
| RAW·WB 도구 | `/opt/homebrew/bin/raw-identify`, `/opt/homebrew/bin/dcraw_emu`, LibRaw 설치 경로 버전 0.22.2 | WB 정보 확인과 계산용 RGB 디코딩에 사용할 수 있는 후보다. 실제 NEF 호환성은 확보 후 검증한다. |
| `dcraw`, PATH의 `ART-cli`, `build/rtgui/ART-cli` | 모두 부재 | T18을 ART-cli 빌드에 의존시키지 않는다. T19의 렌더 검증은 별도로 준비한다. |

T1의 계약은 최소 코드 디렉토리·스모크 테스트·기존 venv 실행·설치 기록 한 곳이다. 새 가상환경, `pyproject.toml`, 설정 로더를 추가하는 작업은 T18로 가져오지 않는다. 스모크 테스트는 소스 바이트코드와 pytest 캐시 생성을 끄고 실행했다.

구현 착수 전에는 다음을 확인한다.

1. T1 산출물과 [실행·설치 기록](pipeline_setup.md)의 명령을 확인한다.
2. `sample1.nef`의 실제 RAW 여부·출처·SHA-256을 확인한다. 지금은 파일이 없어 해시와 실측 EXIF·통계 기준값을 기입할 수 없다.
3. EXIF 태그와 WB 계수의 읽기 가능 여부, RGB 디코더의 옵션·버전을 확인하고 고정한다. 필요한 도구가 없으면 설치 필요 상태를 명시한다.

## 3. 추출 방법과 수치의 의미

### 3.1 EXIF 정규화

Exiv2는 NEF와 제조사 MakerNote 읽기를 지원한다. 표준 태그와 제조사 태그를 구분하고 읽기 출력만 사용한다. 근거: [Exiv2 공식 사용 설명서](https://exiv2.org/manpage.html), [Nikon MakerNote 태그 목록](https://exiv2.org/tags-nikon.html).

| 표준 출력 | 타입·단위 | 원문 후보와 규칙 |
|---|---|---|
| `exif.iso` | 양의 정수 또는 `null` | `Exif.Photo.ISOSpeedRatings` 우선. 없을 때 실제 확인한 Nikon ISO 태그를 사용하고 선택한 태그를 기록한다. 복수 값이 모호하면 임의로 하나를 고르지 않는다. |
| `exif.shutter_seconds` | 양의 실수, 초 또는 `null` | `Exif.Photo.ExposureTime`의 유리수를 초로 변환한다. 예: `1/125` → `0.008`. 분모 0·음수·형식 오류는 경고와 `null`로 처리한다. |
| `exif.camera.make`, `model` | 문자열 또는 `null` | `Exif.Image.Make`, `Exif.Image.Model`. 공백을 정리하고 원문 태그 키를 보존한다. |
| `exif.white_balance.mode` | `auto` / `manual` / `null` | `Exif.Photo.WhiteBalance`를 정규화한다. 모드를 색온도나 WB 계수와 혼동하지 않는다. |
| `exif.white_balance.preset` | 문자열 또는 `null` | 실제 존재하는 제조사 WB 태그. Nikon3의 `WhiteBalance` 등은 샘플 확인 후 선택한다. |
| `exif.white_balance.temperature_kelvin` | 양의 수, K 또는 `null` | 원문에 온도가 명시된 경우만 채운다. 계수나 `AUTO` 문자열로 온도를 추정하지 않는다. |
| `exif.white_balance.camera_multipliers` | `r/g1/b/g2` 양의 계수 객체 또는 `null` | 제조사 태그 또는 `raw-identify -w`의 실제 출력과 채널 순서를 확인한다. 첫 녹색 계수로 나누어 `g1=1`로 정규화한다. |

표준 필드 키는 항상 존재한다. 없는 값은 `null`과 `warnings`의 원인으로 구분하고, `exif.source_tags`에 채택한 원문 위치를 연결한다. WB 계수가 LibRaw에서 얻어진 경우 그 도구를 출처로 표시한다. Kelvin·계수는 선택 정보이며 실제 샘플의 ISO·셔터·카메라·WB 모드 또는 프리셋이 확보되었는지는 별도로 대조한다. 누락값만 있는 JSON을 실제 샘플 추출 성공으로 간주하지 않는다.

### 3.2 계산용 RGB 고정

센서 배열의 Bayer 값이나 내장 JPEG 미리보기를 그대로 RGB 통계로 취급하지 않는다. RAW를 같은 조건의 RGB로 변환하고 그 이미지 전체에서 통계를 계산한다. 설치된 `dcraw_emu`로 선형 16비트 PPM을 얻어 NumPy 배열로 읽는 경로를 우선 검증한다. 이 경로를 선택하면 Pillow 등의 추가 설치 없이 필요한 배열을 얻을 수 있는지 먼저 확인한다. LibRaw의 예제 도구라는 근거는 [공식 사용 예제](https://www.libraw.org/docs/Samples-LibRaw.html)이며, 아래 옵션은 설치된 도구의 사용법 출력에서도 확인했다.

| 조건 | 고정안 |
|---|---|
| 색·감마·정밀도 | `-o 1`, `-4`: 선형 sRGB, 16비트. 배열은 출력 최대값으로 나누어 `[0,1]`로 정규화하고 float64로 집계한다. |
| 노출·정규화 | 자동 밝기 보정 해제, 밝기 배율 `-b 1`, 자동 최대값 추정 `-c 0`. 추가 노출 보정을 적용하지 않는다. |
| 디모자이크·하이라이트 | `-q 3`, `-H 0`으로 고정. 노이즈·중앙값 필터는 해제한다. |
| WB | 확인한 촬영 WB 계수를 `-r r g1 b g2`로 명시해 적용한다. `-w`의 “가능하면 적용” 폴백에 의존하지 않는다. 계수가 없으면 단위 계수를 명시하고 `wb_applied=unity`와 경고를 기록하며 노란색 경향 판정을 보류한다. |
| 크기·영역 | 반해상도·크롭·리사이즈 없이 디코더의 유효 이미지 전체, 회전 `-t 0`. 센서 차원 대신 실제 출력 `width/height/pixel_count`를 기록한다. |
| 결과·파일 보존 | PPM은 `-Z -`의 표준 출력으로 받거나 pytest 임시 폴더에 둔다. 원본 폴더에 출력물을 생성하거나 RAW를 덮어쓰지 않는다. |
| 실행 조건 | 디코더 버전·옵션·스레드 수를 고정하여 기록한다. 다른 백엔드로 바꾸면 같은 기준값을 재사용하지 않는다. |

실제 NEF에서 옵션 적용·PPM 형식·WB 채널 순서를 확인한 뒤 `analysis.pipeline_version`을 고정한다. 디코드 실패·비어 있는 배열·NaN·무한대·범위 밖 값은 명시적 오류이며 정상 JSON으로 전달하지 않는다. 이 RGB는 정해진 측정 조건의 결과이고 ART 렌더 결과와 동일하다는 계약은 아니다.

### 3.3 히스토그램과 판단용 통계

모든 평균은 같은 유효 픽셀 `N`을 사용한다. RGB 각 채널과 휘도는 `[0,1]`이며 bin은 16개로 고정한다. 경계는 `0, 1/16, …, 1`이고 구간은 왼쪽 포함·오른쪽 제외, 마지막 구간만 1을 포함한다. 채널마다 정수 `counts`와 `probabilities=counts/N`, 평균을 기록한다. 채널 분포의 합과 평균을 함께 전달하면 T19가 밝기·색 편향의 수치 근거를 확인할 수 있다.

- 평균 휘도: 픽셀마다 `Y=0.2126R+0.7152G+0.0722B`를 계산해 평균한다. 선형 sRGB의 상대 휘도이며 단위는 없다.
- 평균 채도: 같은 선형 RGB에서 `M=max(R,G,B)`, `m=min(R,G,B)`로 두고, `M=0`이면 0, 그 외에는 `S=(M-m)/M`를 평균한다. HSV형 채도라는 계산 정의를 고정하며 감마 적용 이미지의 채도와 혼용하지 않는다.
- 어두운 영역 비율: `Y<0.05`인 픽셀 수를 `N`으로 나눈다. 휘도 평균과 함께 분포의 보조 근거로 제공한다.
- 노란색 경향 지수: 채널 평균을 `R̄/Ḡ/B̄`로 두고 `D=R̄+Ḡ+B̄`에 대해 `yellow_excess=((R̄+Ḡ)/2-B̄)/D`를 계산한다. `D=0`이면 지수는 `null`이다. 범위는 `[-1,0.5]`다.
- 적녹 불균형: `red_green_imbalance=abs(R̄-Ḡ)/D`. 노란색과 강한 빨강·녹색 우세를 구분하는 보조값이다. `D=0`이면 `null`이다.

초기 임계값은 아래의 **계획상 휴리스틱**이다. 실제 샘플의 실측값이나 보정 필요성의 정답을 뜻하지 않는다. 하나의 샘플에 맞춰 임계값을 조정하지 않으며, 변경하면 `signals.rules_version`을 바꾸고 경계값 검증을 갱신한다.

| 신호 | 초기 활용안 | 판정 한계·보류 |
|---|---|---|
| `signals.is_dark` | `mean_luminance<0.18`이면 어두운 경향 후보. `shadow_fraction`은 근거로 함께 전달한다. | 임계값과의 차이가 `0.0001` 이내면 `null`로 보류한다. 야경·검은 피사체는 요청의 맥락으로 해석한다. |
| `signals.yellow_tendency` | `yellow_excess>0.08`이면서 `red_green_imbalance<0.10`, 평균 채도 `>0.10`이면 노란색 경향 후보. | 휘도 `≤0.02`, WB 단위 계수 사용, 지수 부재 또는 어느 판단 경계에서든 `0.0001` 이내면 `null`. 그 외 조건 미충족은 `false`. |

노란 물체·석양·조명 자체도 같은 통계를 낼 수 있다. 따라서 “노랗다” 신호만으로 WB 오류나 특정 Kelvin 보정을 확정하지 않는다. T19에는 숫자·측정 조건·보류 이유를 전달하고 사용자의 요청과 함께 활용한다.

## 4. 출력 스키마안과 JSON 예시

최상위 구조는 `schema_version`, `source`, `exif`, `analysis`, `histogram`, `signals`, `warnings`로 고정한다. `schema_version=1`은 사진 특성 JSON의 버전이며 `.arp`의 PPVERSION과 별개다. `source.sha256`은 실제 입력 바이트의 64자리 해시, `source.path`는 프로젝트 기준 상대 경로다. `analysis`에는 측정 조건과 도구 버전을 담는다. 모든 수는 유한해야 하며 누락은 `null`만 허용한다.

아래는 **형식 설명용 가상 예시**다. EXIF와 해시는 가상값이고, 통계는 동일한 `(R,G,B)=(0.14,0.13,0.08)` 픽셀 4개의 계산 예시다. `sample1.nef`의 크기·촬영 정보·실측 통계로 사용하지 않는다.

```json
{
  "schema_version": 1,
  "source": {
    "path": "data/fivek_sample/sample1.nef",
    "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
  },
  "exif": {
    "iso": 200,
    "shutter_seconds": 0.008,
    "camera": {"make": "NIKON", "model": "NIKON D70"},
    "white_balance": {
      "mode": "auto",
      "preset": "AUTO",
      "temperature_kelvin": null,
      "camera_multipliers": {"r": 2.1, "g1": 1.0, "b": 1.6, "g2": 1.0}
    },
    "source_tags": {
      "iso": "Exif.Photo.ISOSpeedRatings",
      "shutter_seconds": "Exif.Photo.ExposureTime",
      "camera.make": "Exif.Image.Make",
      "camera.model": "Exif.Image.Model",
      "white_balance.mode": "Exif.Photo.WhiteBalance",
      "white_balance.preset": "Exif.Nikon3.WhiteBalance",
      "white_balance.temperature_kelvin": null,
      "white_balance.camera_multipliers": "LibRaw/raw-identify:camera multipliers"
    }
  },
  "analysis": {
    "pipeline_version": "t18-linear-rgb-v1",
    "metadata_tool": {"name": "exiv2", "version": "0.28.8"},
    "decoder": {"name": "dcraw_emu", "version": "0.22.2"},
    "numpy_version": "2.5.3",
    "color_space": "linear_srgb",
    "bit_depth": 16,
    "wb_applied": "camera",
    "width": 2,
    "height": 2,
    "pixel_count": 4,
    "decoder_options": ["-4", "-o", "1", "-q", "3", "-H", "0", "-b", "1", "-c", "0", "-m", "0", "-n", "0", "-t", "0", "-r", "2.1", "1", "1.6", "1", "-Z", "-"],
    "threads": 1
  },
  "histogram": {
    "bin_count": 16,
    "bin_edges": [0, 0.0625, 0.125, 0.1875, 0.25, 0.3125, 0.375, 0.4375, 0.5, 0.5625, 0.625, 0.6875, 0.75, 0.8125, 0.875, 0.9375, 1],
    "luminance": {"mean": 0.128516, "shadow_fraction": 0.0},
    "saturation": {"mean": 0.428571},
    "channels": {
      "r": {"mean": 0.14, "counts": [0, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "probabilities": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
      "g": {"mean": 0.13, "counts": [0, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "probabilities": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
      "b": {"mean": 0.08, "counts": [0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "probabilities": [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}
    }
  },
  "signals": {
    "rules_version": "t18-thresholds-v1",
    "yellow_excess": 0.157143,
    "red_green_imbalance": 0.028571,
    "is_dark": true,
    "yellow_tendency": true,
    "thresholds": {"dark_mean": 0.18, "yellow_excess": 0.08, "red_green_imbalance_max": 0.10, "saturation_min": 0.10, "yellow_luminance_min": 0.02, "boundary_margin": 0.0001},
    "deferred_reasons": []
  },
  "warnings": []
}
```

`warnings`와 `deferred_reasons`는 이유 코드 배열이며 순서를 고정한다. 예를 들어 `wb_coefficients_missing`, `yellow_check_deferred`를 기록한다. JSON은 키 순서·UTF-8·개행을 고정하고, 측정 실수는 소수 6자리로 반올림한다. 판정에는 반올림 전 값을 사용하고 시각·임시 폴더·호스트 이름은 출력에 넣지 않는다. 디코더 실패는 성공 형태의 JSON으로 반환하지 않으며 입력 경로와 실패 단계를 포함하는 예외로 T19 전달을 중단한다.

## 5. 산출물 계획 — 파일과 함수 계약

T1의 `src/` import 방식을 따른다. 아래는 책임과 시그니처 수준의 제안이며 함수 본문·실제 파일은 작성하지 않는다. `np.ndarray`는 이미 설치된 NumPy의 배열, 반환 `dict[str, object]`는 §4의 JSON 호환 객체를 뜻한다.

| 예정 파일 | 함수 시그니처안 | 역할·입출력 계약 |
|---|---|---|
| `src/artagent/features/__init__.py` | `extract_features(raw_path: Path) -> dict[str, object]` | 파일 존재·유효성 확인 → EXIF → RGB → 통계·신호 → 스키마 확인의 단일 진입점. RAW를 수정하지 않는다. |
| 같은 파일 | `dumps_features(features: dict[str, object]) -> str` | 정렬·반올림·유한값 검증을 거친 재현 가능한 JSON 문자열. 호출자가 저장 위치를 결정한다. |
| `src/artagent/features/exif.py` | `read_exif(raw_path: Path) -> dict[str, object]` | Exiv2와 필요 시 WB 읽기 도구의 출력을 수집한다. 원문 태그·도구 출처를 보존한다. |
| 같은 파일 | `normalize_exif(tags: dict[str, object]) -> dict[str, object]` | 표준 EXIF 필드와 출처·경고를 반환한다. 유리수·빈 문자열·미지원 WB 값을 처리한다. |
| `src/artagent/features/histogram.py` | `decode_raw_rgb(raw_path: Path, exif: dict[str, object]) -> tuple[np.ndarray, dict[str, object]]` | 고정 옵션의 H×W×3 정규화 배열과 `analysis` 조건을 반환한다. 실행 실패·손상 PPM은 명시적 오류다. |
| 같은 파일 | `summarize_rgb(rgb: np.ndarray) -> dict[str, object]` | 평균 휘도·채도·채널별 16-bin 분포·그림자 비율을 계산한다. RAW와 외부 도구에 의존하지 않는다. |
| 같은 파일 | `derive_signals(histogram: dict[str, object], analysis: dict[str, object]) -> dict[str, object]` | 연속 지수·임계값·판정·보류 이유를 반환한다. `.arp` 값은 생성하지 않는다. |
| `tests/test_features.py` | 아래 §6의 pytest 사례 | 실제 NEF 고정 검증, 작은 수치 배열·고정 메타데이터 응답 검증, 오류·재현성 검증을 한 파일에서 수행한다. |

총 예정 파일은 모듈 3개와 테스트 1개다. 스키마와 오류 계약은 이 문서·테스트에 유지하여 별도 설정 파일이나 검증 패키지를 미리 추가하지 않는다. 외부 명령은 인자 배열과 고정 로케일로 호출하고, 읽기 작업의 종료코드·출력 형식·시간 초과를 확인하도록 구현한다.

## 6. 검증 계획 — `tests/test_features.py`

### 6.1 고정 샘플과 기준값 준비

fixture는 저장소 기준 **정확히** `data/fivek_sample/sample1.nef`를 가리킨다. 파일 이름만 일치하는 다른 RAW, DNG, JPEG로 대체하지 않는다. 확보 후 실제 SHA-256·도구 버전·WB·디코드 옵션을 테스트 상수와 함께 고정한다. EXIF는 원문 태그 출력으로 대조하고, 통계는 고정 PPM을 대상으로 작은 별도 집계 또는 독립 검산으로 확인해 기준값을 검토한다. 구현 함수의 첫 출력만 그대로 정답으로 삼지 않는다.

검증 중 네트워크 접근·다운로드를 수행하지 않는다. 샘플·필수 도구 부재나 해시 불일치는 명시적 테스트 실패로 처리한다. 전체 테스트를 skip하거나 고정 샘플 검증을 작은 배열로 대체해 Task 18 완료로 표시하지 않는다. 현재 파일 부재로 실제 EXIF와 통계 기대값은 **미확정**이며, 이 문서의 가상 JSON을 기준값으로 복사하지 않는다.

### 6.2 테스트 사례 목록

| 사례명 제안 | 입력·검증 |
|---|---|
| `test_sample_identity` | 고정 경로·실제 RAW·사전 확정 SHA-256을 확인한다. 부재·해시 변경은 실패다. |
| `test_sample_exif_reference` | 실제 샘플 ISO·초 단위 셔터·카메라·WB 모드/프리셋을 검토한 기준값과 대조한다. 선택 정보 누락과 필수값 누락을 구분한다. |
| `test_sample_histogram_reference` | 고정 디코더의 크기·픽셀 수·평균 휘도·채도·RGB 평균·분포를 독립 검산한 기준값과 대조한다. |
| `test_rgb_known_values` | 검정·흰색·회색·단색 작은 배열. 검정 `Y=0/S=0`, 흰색 `Y=1/S=0`, 회색 `S=0`, 순수 노랑의 지수 `0.5`를 검증한다. |
| `test_histogram_bins_and_counts` | 0·1·모든 bin 경계·경계 양옆 값에서 bin 배정, 배열 길이 16, counts 합 `N`, 확률 합 1을 확인한다. |
| `test_signal_thresholds` | 어두움·노란색·채도·적녹 불균형의 각 임계값 아래·위·보류대역. 푸른색·녹색 우세를 노란색으로 판정하지 않는지 확인한다. |
| `test_missing_or_invalid_exif` | 고정 도구 응답으로 ISO 누락, `1/125`·분모 0, WB 모드만 존재, 계수·Kelvin 부재를 검증한다. 누락을 0이나 추정값으로 채우지 않는다. |
| `test_wb_fallback_defers_yellow` | WB 계수 부재 시 단위 계수의 명시적 적용, 경고, 노란색 판정 `null`을 확인한다. |
| `test_invalid_pixels_and_raw` | 빈 배열·잘못된 shape·NaN·무한대·범위 밖 값·손상 RAW·잘린 PPM에서 명시적 오류를 확인한다. |
| `test_tool_failures` | 도구 부재·비정상 종료·시간 초과·예상과 다른 출력 형식을 주입해 실패 단계가 드러나고 T19로 성공 객체가 넘어가지 않는지 확인한다. |
| `test_repeatable_json` | 같은 샘플·설정에서 3회 실행한 JSON의 바이트 일치. float 유한성·null·키·출처·규칙 버전도 검사한다. |
| `test_source_unchanged` | 실행 전후 RAW 해시 일치, 원본 옆 부가 파일 부재, 임시 결과의 테스트 임시 폴더 사용을 확인한다. |
| `test_t19_input_contract` | JSON 왕복 직렬화 뒤 필드 타입·버전·단위·16-bin 분포·보류 이유가 유지되어 생성기 입력으로 읽힐 수 있음을 확인한다. 프로필 생성은 수행하지 않는다. |

### 6.3 재현성과 오차 기준

| 비교 항목 | 통과 기준 |
|---|---|
| 샘플·환경 식별 | 입력 SHA-256, schema/pipeline/rules 버전, 도구 버전·설정이 정확히 일치한다. |
| ISO·카메라·WB 모드/프리셋 | 원문 대조값과 정확히 일치. WB·경고·출처 키도 정확히 일치한다. |
| 셔터 초·WB 계수의 내부 변환 | 고정 유리수·계수 기준과 절대 오차 `≤1e-9`. JSON에서의 반올림 오차는 별도로 `≤5e-7`이다. |
| 같은 배열의 평균·지수 | 독립 수치 기준과 절대 오차 `≤1e-12`. JSON 직렬화 값은 절대 오차 `≤5e-7`이다. |
| 분포 | 동일 픽셀 배열의 counts는 정확히 일치하며 합 `N`. 내부 확률 합 오차 `≤1e-12`, 6자리 반올림 후 합 오차 `≤8e-6`이다. |
| 같은 환경의 실제 샘플 | 고정 PPM 해시·counts·픽셀 수 정확 일치, 내부 통계 절대 오차 `≤1e-12`, 직렬화한 JSON 3회 바이트 일치. |
| 다른 운영체제·빌드 비교 | 같은 도구 버전·옵션·차원 조건에서 평균·색 지수 절대 오차 `≤1e-4`, 채널별 정규화 분포의 L1 거리 `≤0.002`를 목표로 별도 확인한다. 미검증 플랫폼은 지원 확인 완료로 기록하지 않는다. |

플랫폼 비교 한도를 넘으면 버전·WB·디코드 조건부터 원인을 조사한다. 통과시키기 위해 허용 오차를 늘리거나 기준값을 덮어쓰지 않는다. threshold 보류대역으로 플랫폼의 작은 차이가 즉시 보정 명령으로 바뀌는 것을 막는다.

후속 구현 검증 명령은 프로젝트 venv의 Python으로 `-m pytest tests/test_features.py -q`와 `-m pytest tests/test_smoke.py -q`를 실행하는 것이다. 현재 확인한 인터프리터는 §2의 절대 경로다. Task 18 구현·샘플 준비 후 두 결과와 실행 환경을 인계 기록에 남긴다.

## 7. 실행 순서와 의존·연계

`T1 → T18(EXIF + 고정 RGB 통계 + JSON) → T19(요청과 결합한 프로필 생성) → T20(렌더·재시도)` 순서다. T18의 명시적 선행 태스크는 T1이며 샘플 준비는 실제 완료 검증의 선행 조건이다. T19는 T18 외에 T2의 PPVERSION·빌드 기록과 자체 생성 실행 환경을 필요로 한다.

| 순서 | 구현 작업 | 통과 조건·확인 지점 |
|---|---|---|
| 1 | T1·샘플·도구 확인, 출력 계약과 기준 환경 고정 | 스모크 통과, 실제 NEF 해시·EXIF 원문·WB·디코드 설정이 기록되어 있다. 샘플 부재를 먼저 해결한다. |
| 2 | 샘플의 EXIF → RGB → 통계 → JSON 한 경로 구현 | 필수 EXIF, 평균 휘도·채도·RGB 분포가 §4 구조로 나오고 기준값과 일치한다. 여기서 첫 실제 샘플 검증을 수행한다. |
| 3 | 누락·경계·오류·재현성 사례 확인 | §6의 focused pytest와 기존 스모크가 통과하고 원본이 보존된다. |
| 4 | T19 입력 인계 | 스키마 버전·단위·출처·측정 조건·기준값·경고·한계와 테스트 실행 기록을 전달한다. |

WBS의 A-19 구현 예산은 2시간이다. 샘플 부재·도구 호환성 미확인은 착수 위험으로 남기며, 이를 해결하지 못한 상태에서 실제 샘플 검증을 생략하여 예산에 맞추지 않는다.

T19에는 `extract_features`의 JSON 호환 객체 또는 `dumps_features` 결과를 전달한다. T19는 먼저 버전·필수 키·유한값·소스 해시를 확인하고, `exif`·`histogram`·`signals`를 사용자 요청과 결합한다. 경고와 `null`은 생성 단계까지 전달하며 어두움·노란색 신호를 특정 `.arp` 키나 보정량으로 일대일 매핑하지 않는다. 지원하지 않는 스키마·추출 실패는 생성 전에 중단한다. T19 테스트는 고정 JSON으로 연결 계약을 검증하고, 실제 프로필 검증과 ART-cli 렌더 성공은 T19의 완료 조건으로 남긴다.

## 8. 완료 체크리스트와 구현 인계

### 이번 계획 문서의 완료 확인

- [x] Task 18 전문과 Task 1·Task 19의 범위를 읽고 고정 입력·연계를 기록했다.
- [x] 실제 파일 부재, DNG 자리표시자, EXIF·RAW 도구와 프로젝트 venv 현황을 확인했다.
- [x] JSON 스키마안·계산 정의·초기 임계값·판정 보류 조건을 작성했다.
- [x] 모듈 책임·함수 시그니처·pytest 사례·재현성·오차 기준을 작성했다.
- [x] 실측값이 없는 상태와 가상 JSON 예시를 구분했다.

### 후속 T18 구현의 완료 조건

- [ ] 실제 `sample1.nef`의 출처·해시·EXIF 기준값을 고정했다.
- [ ] T1의 기존 venv·import·설치 기록 계약을 따른다.
- [ ] ISO·셔터·카메라·WB 표준 필드를 실제 샘플에서 추출하고 누락을 구분한다.
- [ ] 고정 RGB 조건에서 평균 휘도·채도·채널 분포와 판단용 연속 수치를 출력한다.
- [ ] 같은 환경에서 3회 JSON 바이트 일치, 기준값 오차·분포 합 조건, 원본 보존을 확인했다.
- [ ] `tests/test_features.py`와 기존 스모크가 통과하고 샘플 검증을 skip하지 않았다.
- [ ] T19가 입력 계약과 보류·경고를 읽을 수 있으며 프로필 값 결정은 T19에 남겼다.

다음 구현 담당자에게 이 문서, T1의 실행·설치 기록 위치, `sample1.nef` 부재 사실, 확인한 도구 버전, 실제 기대값 미확정 항목을 먼저 전달한다. 샘플이 준비되면 독립 대조값·고정 디코드 설정을 확정하고 §7 순서대로 구현한다. 구현 결과 인계에는 샘플 해시, EXIF 원문 출처, 통계 기준값, 명령·도구 버전, pytest 결과, T19용 JSON과 아직 확인하지 않은 플랫폼을 포함한다.
