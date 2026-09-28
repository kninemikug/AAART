# ART Master 검색 평가 질문 데이터셋 명세 (100문항)

이 문서는 `docs/search_eval_queries.json` 정본 데이터셋으로부터 생성된 사람이 읽는 명세 문서이다.

## 1. 데이터셋 개요 및 분포 요약

- 총 질문 수: 100개
- 출처 분포: RawPedia 80개, GitHub 20개
- 난이도 분포: Factoid 50개, Complex 45개, Negative 5개

### 카테고리별 / 의도별 분포

| 카테고리 | usage/how-to | concept | troubleshooting | workflow | 합계 |
|---|---:|---:|---:|---:|---:|
| `exposure_tone` | 6 | 6 | 3 | 1 | 16 |
| `color_wb` | 8 | 8 | 2 | 3 | 21 |
| `demosaic_raw` | 3 | 4 | 5 | 2 | 14 |
| `sharpening_noise` | 4 | 3 | 3 | 2 | 12 |
| `mask_local` | 9 | 3 | 4 | 3 | 19 |
| `settings_workflow` | 5 | 1 | 3 | 9 | 18 |

## 2. 전체 질문 목록 요약표

| ID | 출처 | 카테고리 | 의도 | 난이도 | 질문 제목 | 첫 근거 위치 |
|---|---|---|---|---|---|---|
| `Q001` | `rawpedia` | `exposure_tone` | `concept` | `factoid` | RawPedia 설명에서 Auto Levels는 무엇을 분석해 Exposure 설정을 조정하나요? | [Auto Levels](https://rawpedia.rawtherapee.com/exposure/) |
| `Q002` | `rawpedia` | `exposure_tone` | `usage/how-to` | `complex` | RawPedia 기준으로 하이라이트 복원(Highlight Reconstruction) 시 Color Propagation 방식의 동작 원리와 한계는 무엇인가요? | [Highlight Reconstruction](https://rawpedia.rawtherapee.com/exposure/) |
| `Q003` | `rawpedia` | `exposure_tone` | `concept` | `factoid` | Dynamic Range Compression 도구의 Anchor 슬라이더는 어떤 역할을 하나요? | [Anchor](https://rawpedia.rawtherapee.com/dynamic_range_compression/) |
| `Q004` | `rawpedia` | `exposure_tone` | `usage/how-to` | `complex` | Dynamic Range Compression을 적용할 때 압축 강도(Amount)와 로컬 대비(Detail) 슬라이더는 이미지 톤과 대비에 각각 어떤 영향을 주나요? | [Amount](https://rawpedia.rawtherapee.com/dynamic_range_compression/) |
| `Q005` | `rawpedia` | `exposure_tone` | `usage/how-to` | `factoid` | Shadows & Highlights 도구에서 Lab 색공간 대신 RGB 색공간을 사용할 때의 장점과 주의할 점은 무엇인가요? | [Color Space](https://rawpedia.rawtherapee.com/shadows-highlights/) |
| `Q006` | `rawpedia` | `exposure_tone` | `usage/how-to` | `complex` | Shadows & Highlights 도구에서 Tonal Width와 Radius 슬라이더는 효과 적용 범위를 각각 어떻게 제어하나요? | [Tonal Width](https://rawpedia.rawtherapee.com/shadows-highlights/) |
| `Q007` | `rawpedia` | `exposure_tone` | `concept` | `factoid` | Tone Mapping 도구에서 Gamma 슬라이더의 동작 원리는 무엇인가요? | [Gamma](https://rawpedia.rawtherapee.com/tone_mapping/) |
| `Q008` | `rawpedia` | `exposure_tone` | `usage/how-to` | `factoid` | Tone Mapping 적용 후 만화 같은 과장된 외관(cartoonish appearance)이나 소프트 후광 문제가 발생할 때 어떤 옵션 값을 올려야 하나요? | [Reweighting Iterates](https://rawpedia.rawtherapee.com/tone_mapping/) |
| `Q009` | `rawpedia` | `exposure_tone` | `concept` | `factoid` | Local Contrast 도구의 Amount 슬라이더는 이미지 대비에 어떤 영향을 주나요? | [Amount](https://rawpedia.rawtherapee.com/local_contrast/) |
| `Q010` | `rawpedia` | `exposure_tone` | `troubleshooting` | `complex` | Local Contrast 도구에서 Darkness Level과 Lightness Level 슬라이더는 각각 어떤 영역을 변경하며, 둘 다 0으로 설정하면 도구는 어떻게 동작하나요? | [Darkness/Lightness Levels](https://rawpedia.rawtherapee.com/local_contrast/) |
| `Q011` | `rawpedia` | `exposure_tone` | `concept` | `complex` | RGB Curves 도구의 Luminosity Mode는 어떤 목적으로 사용되며, 다른 도구(HSV Equalizer, Channel Mixer)와 비교할 때 어떤 제어 특성을 갖나요? | [Luminosity Mode](https://rawpedia.rawtherapee.com/rgb_curves/) |
| `Q012` | `rawpedia` | `exposure_tone` | `troubleshooting` | `factoid` | RawPedia 설명 기준으로 RGB curves를 각 채널별로 다르게 적용하면 어떤 색조 효과를 연출할 수 있나요? | [RGB Curves](https://rawpedia.rawtherapee.com/rgb_curves/) |
| `Q013` | `rawpedia` | `exposure_tone` | `usage/how-to` | `factoid` | 에디터의 클리핑 표시기(Clipping Indication)에서 clipped highlight 경고는 어떤 조건에서 표시되나요? | [Clipping Indication](https://rawpedia.rawtherapee.com/clipping_indication/) |
| `Q014` | `rawpedia` | `exposure_tone` | `troubleshooting` | `factoid` | Haze Removal 도구 사용 시 안개 제거 효과가 가장 강하게 적용되는 영역을 시각적으로 확인하려면 어떤 기능을 켜야 하나요? | [Usage](https://rawpedia.rawtherapee.com/haze_removal/) |
| `Q015` | `rawpedia` | `exposure_tone` | `concept` | `complex` | Soft Light 도구는 어떤 소프트웨어의 블렌드 모드를 모방하며, 결과 이미지에 어떤 시각적 변화를 주나요? | [Soft Light](https://rawpedia.rawtherapee.com/soft_light/) |
| `Q016` | `rawpedia` | `exposure_tone` | `workflow` | `complex` | Unclipped 프로필을 적용하여 저장할 때 요구되는 출력 ICC 프로필 조건과 권장 저장 파일 포맷은 무엇인가요? | [Usage](https://rawpedia.rawtherapee.com/unclipped/) |
| `Q017` | `rawpedia` | `color_wb` | `concept` | `factoid` | White Balance 도구의 temperature 슬라이더는 어떤 색상 축을 기준으로 이미지를 조절하나요? | [Temperature and Tint](https://rawpedia.rawtherapee.com/white_balance/) |
| `Q018` | `rawpedia` | `color_wb` | `usage/how-to` | `complex` | RAW 이미지에서 화이트 밸런스가 RGB 채널 가중치로 변환될 때 클리핑 제어 방식과, Temperature correlation 알고리즘이 잘못된 결과를 낼 수 있는 조명 조건은 무엇인가요? | [White Balance Connection to Exposure](https://rawpedia.rawtherapee.com/white_balance/) |
| `Q019` | `rawpedia` | `color_wb` | `concept` | `factoid` | Color Management에서 카메라 RAW 데이터를 내부 작업 색공간으로 변환할 때 입력 프로필(Input Profile)이 없으면 어떤 문제가 발생하나요? | [Input Profile](https://rawpedia.rawtherapee.com/color_management/) |
| `Q020` | `rawpedia` | `color_wb` | `usage/how-to` | `complex` | Color Management에서 기본 작업 프로필(Working Profile)의 권장 설정과 출력 프로필(Output Profile)의 동작 특성은 무엇인가요? | [Working Profile](https://rawpedia.rawtherapee.com/color_management/) |
| `Q021` | `rawpedia` | `color_wb` | `concept` | `factoid` | Gamut Compression 도구의 기본 목적은 무엇인가요? | [Gamut Compression](https://rawpedia.rawtherapee.com/gamut_compression/) |
| `Q022` | `rawpedia` | `color_wb` | `usage/how-to` | `complex` | Gamut Compression 도구에서 Threshold 슬라이더의 동작 방식과 별표(*) 표시 작업공간의 사전 계산 임계값 특성은 무엇인가요? | [Threshold](https://rawpedia.rawtherapee.com/gamut_compression/) |
| `Q023` | `rawpedia` | `color_wb` | `concept` | `factoid` | Film Simulation 도구는 필름 색감을 재현하기 위해 어떤 포맷의 참조 이미지를 요구하나요? | [Film Simulation](https://rawpedia.rawtherapee.com/film_simulation/) |
| `Q024` | `rawpedia` | `color_wb` | `usage/how-to` | `factoid` | Film Simulation용 아이덴티티 HaldCLUT를 직접 생성할 때 하이라이트 버그가 있어 사용을 피해야 하는 프로그램은 무엇인가요? | [Caveat](https://rawpedia.rawtherapee.com/film_simulation/) |
| `Q025` | `rawpedia` | `color_wb` | `concept` | `factoid` | Lab 색공간에서 L 컴포넌트는 인간의 시각 인지와 어떻게 연관되나요? | [Lab Adjustments](https://rawpedia.rawtherapee.com/lab_adjustments/) |
| `Q026` | `rawpedia` | `color_wb` | `usage/how-to` | `complex` | Lab Adjustments에서 Chromaticity 슬라이더의 동작 방식과 슬라이더를 -100으로 설정했을 때의 결과는 무엇인가요? | [Chromaticity](https://rawpedia.rawtherapee.com/lab_adjustments/) |
| `Q027` | `rawpedia` | `color_wb` | `concept` | `complex` | Vibrance 도구의 기본 개념과 Pastel Tones 및 Saturated Tones 슬라이더의 분리 제어 기능은 무엇인가요? | [Vibrance](https://rawpedia.rawtherapee.com/vibrance/) |
| `Q028` | `rawpedia` | `color_wb` | `troubleshooting` | `factoid` | Vibrance 도구에서 피부톤이 채도 조정의 영향을 받지 않도록 보호하려면 어떤 옵션을 활성화해야 하나요? | [Protect Skin Tones](https://rawpedia.rawtherapee.com/vibrance/) |
| `Q029` | `rawpedia` | `color_wb` | `usage/how-to` | `factoid` | Black-and-White 도구의 Color Filter는 어떤 방식으로 흑백 변환 결과에 영향을 주나요? | [Color Filter](https://rawpedia.rawtherapee.com/black-and-white_addon/) |
| `Q030` | `rawpedia` | `color_wb` | `workflow` | `complex` | RawTherapee에서 Black-and-White 도구를 사용하지 않고 흑백 이미지를 만드는 대안적인 절차들은 무엇인가요? | [General remarks](https://rawpedia.rawtherapee.com/black-and-white_addon/) |
| `Q031` | `rawpedia` | `color_wb` | `concept` | `complex` | RGB와 CIE Lab 색공간의 정의와 두 색공간 간 보정 차이에 대한 일반적인 의문은 무엇인가요? | [RGB and Lab](https://rawpedia.rawtherapee.com/rgb_and_lab/) |
| `Q032` | `rawpedia` | `color_wb` | `troubleshooting` | `factoid` | Channel Mixer 도구는 어떤 용도로 사용되며 출력 채널 섹션은 어떻게 구성되어 있나요? | [Channel Mixer](https://rawpedia.rawtherapee.com/channel_mixer/) |
| `Q033` | `rawpedia` | `color_wb` | `workflow` | `complex` | 디지털 카메라 센서의 물리적 한계와 이를 보정하기 위해 DCP 프로필이 필요한 이유는 무엇인가요? | [What Are DCP Profiles and Why Do I Need Them?](https://rawpedia.rawtherapee.com/how_to_create_dcp_color_profiles/) |
| `Q034` | `rawpedia` | `color_wb` | `workflow` | `factoid` | ICC Profile Creator 도구를 사용하여 사용자 정의 ICC 프로필을 생성할 때 지원되는 값 설정 방식은 무엇인가요? | [Introduction](https://rawpedia.rawtherapee.com/icc_profile_creator/) |
| `Q035` | `rawpedia` | `demosaic_raw` | `concept` | `factoid` | 디지털 카메라 센서에서 가장 널리 사용되는 Bayer 필터의 2x2 컬러 매트릭스 구성은 어떻게 되나요? | [Introduction](https://rawpedia.rawtherapee.com/demosaicing/) |
| `Q036` | `rawpedia` | `demosaic_raw` | `usage/how-to` | `complex` | Dual Demosaic 방식(예: AMaZE+VNG4)의 영역 분할 장점과 연산상의 단점은 무엇인가요? | [Dual Demosaic](https://rawpedia.rawtherapee.com/demosaicing/) |
| `Q037` | `rawpedia` | `demosaic_raw` | `concept` | `factoid` | Preprocessing 단계에서 Hot pixel이 발생하는 물리적 원인은 센서에서 어떻게 설명되나요? | [Hot/Dead Pixel Filter](https://rawpedia.rawtherapee.com/preprocessing/) |
| `Q038` | `rawpedia` | `demosaic_raw` | `troubleshooting` | `complex` | 센서 제조 공정의 한계로 두 초록 채널 간 감도 차이가 날 때 발생하는 보간 아티팩트와 Green equilibration의 임계값(threshold) 역할은 무엇인가요? | [Green Equilibration](https://rawpedia.rawtherapee.com/preprocessing/) |
| `Q039` | `rawpedia` | `demosaic_raw` | `usage/how-to` | `complex` | Flat-Field 도구가 보정할 수 있는 렌즈 비네팅 및 렌즈 캐스트 현상과 플랫 필드 샷 촬영 시 권장 감도(ISO)는 무엇인가요? | [Flat-Field](https://rawpedia.rawtherapee.com/flat-field/) |
| `Q040` | `rawpedia` | `demosaic_raw` | `troubleshooting` | `factoid` | 장노출 사진에서 Dark-frame subtraction 기법이 대처할 수 있는 노이즈 유형들은 무엇인가요? | [Dark-Frame](https://rawpedia.rawtherapee.com/dark-frame/) |
| `Q041` | `rawpedia` | `demosaic_raw` | `concept` | `factoid` | Raw Black Points 도구의 주된 사용 목적은 무엇인가요? | [Raw Black Points](https://rawpedia.rawtherapee.com/raw_black_points/) |
| `Q042` | `rawpedia` | `demosaic_raw` | `usage/how-to` | `factoid` | Raw White Points 도구의 주된 사용 목적은 무엇인가요? | [Raw White Points](https://rawpedia.rawtherapee.com/raw_white_points/) |
| `Q043` | `rawpedia` | `demosaic_raw` | `troubleshooting` | `factoid` | Raw Tab에 위치한 Chromatic Aberration 도구는 파이프라인의 어느 시점에서 작동하나요? | [Chromatic Aberration](https://rawpedia.rawtherapee.com/chromatic_aberration/) |
| `Q044` | `rawpedia` | `demosaic_raw` | `concept` | `complex` | 디지털 이미지에서 비트 심도가 높아질 때의 이점과 그에 따른 대가(트레이드오프)는 무엇인가요? | [Introduction](https://rawpedia.rawtherapee.com/bit_depth/) |
| `Q045` | `rawpedia` | `demosaic_raw` | `workflow` | `complex` | Flat-Field 도구의 Blur Radius 슬라이더의 기본값(32) 역할과 0으로 설정했을 때의 동작은 무엇인가요? | [Blur Radius](https://rawpedia.rawtherapee.com/flat-field/) |
| `Q046` | `rawpedia` | `demosaic_raw` | `workflow` | `factoid` | 다크 프레임 Auto-selection 모드 설정 시 RawTherapee가 최적의 매칭을 탐색하는 참조 디렉터리는 환경설정의 어디에 지정하나요? | [Dark-Frame](https://rawpedia.rawtherapee.com/dark-frame/) |
| `Q047` | `rawpedia` | `sharpening_noise` | `concept` | `factoid` | Capture Sharpening 도구는 촬영 시 광학적으로 발생하는 어떤 요인들로 인한 블러를 보정하기 위해 사용되나요? | [What is it](https://rawpedia.rawtherapee.com/capture_sharpening/) |
| `Q048` | `rawpedia` | `sharpening_noise` | `usage/how-to` | `complex` | Capture Sharpening에서 RL Deconvolution 사용 시 아티팩트를 최소화하는 반경/임계값 설정 요령과 설정 변경의 전체 적용 범위는 무엇인가요? | [Is it the definitive sharpening tool?](https://rawpedia.rawtherapee.com/capture_sharpening/) |
| `Q049` | `rawpedia` | `sharpening_noise` | `concept` | `factoid` | Sharpening 도구의 Unsharp Mask 기법은 이미지의 어떤 시각적 특성을 향상시키는 전통적인 방식인가요? | [Unsharp Mask](https://rawpedia.rawtherapee.com/sharpening/) |
| `Q050` | `rawpedia` | `sharpening_noise` | `usage/how-to` | `complex` | Sharpening 도구에서 지나친 USM 샤프닝 시 후광을 억제하는 Halo Control의 동작 방식과 RL Deconvolution의 점 확산 함수(PSF) 기반 역변환 원리는 무엇인가요? | [Halo Control](https://rawpedia.rawtherapee.com/sharpening/) |
| `Q051` | `rawpedia` | `sharpening_noise` | `usage/how-to` | `complex` | Noise Reduction 도구에서 휘도 노이즈(Luminance noise)와 색상 노이즈(Chrominance noise)에 대한 시각적 특성과 제거 필요성의 차이는 무엇인가요? | [Introduction](https://rawpedia.rawtherapee.com/noise_reduction/) |
| `Q052` | `rawpedia` | `sharpening_noise` | `troubleshooting` | `factoid` | 노이즈가 심한 고감도(예: ISO 6400) 사진에서 AMaZE 디모자이킹을 적용했을 때 어떤 아티팩트 패턴이 나타날 수 있나요? | [Introduction](https://rawpedia.rawtherapee.com/noise_reduction/) |
| `Q053` | `rawpedia` | `sharpening_noise` | `concept` | `complex` | Contrast by Detail Levels 도구의 웨이블릿 분해 레벨 수와 Slider 0(Finest)부터 Slider 5까지의 대략적인 픽셀 반경은 얼마인가요? | [Contrast by Detail Levels](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/) |
| `Q054` | `rawpedia` | `sharpening_noise` | `workflow` | `complex` | Contrast by Detail Levels 도구에서 특정 레벨 슬라이더 값을 1.0보다 작게 하거나 크게 할 때 로컬 대비는 각각 어떻게 변하나요? | [Contrast by Detail Levels](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/) |
| `Q055` | `rawpedia` | `sharpening_noise` | `usage/how-to` | `factoid` | Edges 도구가 일반적인 Unsharp Mask와 비교할 때 갖는 특징(후광, 노이즈 환경, 색공간)은 무엇인가요? | [General](https://rawpedia.rawtherapee.com/edges_and_microcontrast/) |
| `Q056` | `rawpedia` | `sharpening_noise` | `workflow` | `factoid` | Microcontrast의 정의와 저주파 영역 대비를 다루는 local contrast와의 차이점은 무엇인가요? | [Microcontrast](https://rawpedia.rawtherapee.com/edges_and_microcontrast/) |
| `Q057` | `rawpedia` | `sharpening_noise` | `troubleshooting` | `factoid` | Impulse Noise Reduction 도구는 어떤 형태의 노이즈를 제거하기 위해 사용되며 파이프라인의 어느 시점에서 작동하나요? | [Impulse Noise Reduction](https://rawpedia.rawtherapee.com/impulse_noise_reduction/) |
| `Q058` | `rawpedia` | `sharpening_noise` | `troubleshooting` | `factoid` | Defringe 도구가 다루는 퍼플 프린지(Purple fringes)는 색수차의 어떤 형태이며 주로 어떤 가장자리에서 발생하나요? | [Defringe](https://rawpedia.rawtherapee.com/defringe/) |
| `Q059` | `rawpedia` | `mask_local` | `concept` | `factoid` | RawPedia 설명 기준으로 Local adjustments의 RT-spots는 어떤 소프트웨어들의 U-Point 개념과 유사한 원리로 동작하나요? | [Introduction](https://rawpedia.rawtherapee.com/local_adjustments/) |
| `Q060` | `rawpedia` | `mask_local` | `usage/how-to` | `complex` | RawTherapee Local adjustments에서 RT-spot을 구성하는 요소(중심점 C 및 4개 경계점 TBLR)와 이를 기반으로 형성되는 3가지 그래디언트(Dissymetry, Transition, Color)의 동작 방식은 무엇인가요? | [Overview of the RT-spot area](https://rawpedia.rawtherapee.com/local_adjustments/) |
| `Q061` | `rawpedia` | `mask_local` | `concept` | `complex` | Local Lab Controls에서 컨트롤 포인트 조작 편의를 위해 도입된 GUI 인터페이스의 특징과 긴 메뉴 회피 설계는 무엇인가요? | [What kind of local control?](https://rawpedia.rawtherapee.com/local_lab_controls/) |
| `Q062` | `rawpedia` | `mask_local` | `usage/how-to` | `complex` | Local Lab Controls에서 Scope 슬라이더 조절 시 각 사분면(quadrant)에서 tint 및 deltaE(색차) 기반으로 적용량을 계산하는 알고리즘 원리와, 슬라이더 값을 증감할 때의 선택 영역 변화는 무엇인가요? | [Tint, chroma, luminance references and the algorithm principle in “normal” mode](https://rawpedia.rawtherapee.com/local_lab_controls/) |
| `Q063` | `rawpedia` | `mask_local` | `usage/how-to` | `factoid` | Spot Removal 도구에서 새로운 스팟을 추가할 때 마우스 조작 방법(Ctrl-click 및 드래그)은 무엇인가요? | [Adding spots](https://rawpedia.rawtherapee.com/spot_removal/) |
| `Q064` | `rawpedia` | `mask_local` | `usage/how-to` | `complex` | Spot Removal 도구에서 기존 스팟을 제거하는 마우스 조작 방법과 스팟 편집 모드를 토글하는 절차는 무엇인가요? | [Removing spots](https://rawpedia.rawtherapee.com/spot_removal/) |
| `Q065` | `rawpedia` | `mask_local` | `usage/how-to` | `factoid` | Graduated Filter 도구는 실제 어떤 사진 광학 필터를 모방하며 주로 어떤 상황에 사용되나요? | [Graduated Filter](https://rawpedia.rawtherapee.com/graduated_filter/) |
| `Q066` | `rawpedia` | `mask_local` | `troubleshooting` | `factoid` | Graduated Filter 도구의 적용 강도(Strength) 단위는 무엇인가요? | [Strength](https://rawpedia.rawtherapee.com/graduated_filter/) |
| `Q067` | `rawpedia` | `mask_local` | `usage/how-to` | `factoid` | Vignetting Filter 도구에서 크롭(Crop)이 적용되었을 때 비네팅 효과는 어디를 기준으로 배치되나요? | [Vignetting Filter](https://rawpedia.rawtherapee.com/vignetting_filter/) |
| `Q068` | `rawpedia` | `mask_local` | `troubleshooting` | `complex` | Vignetting Filter에서 예술적 비네팅과 렌즈 광량 저하(Flat-Field/Raw Tab) 보정의 차이점 및 원형/직사각형 모양 제어 방식은 무엇인가요? | [Vignetting Filter](https://rawpedia.rawtherapee.com/vignetting_filter/) |
| `Q069` | `rawpedia` | `mask_local` | `workflow` | `factoid` | Preview Modes에서 Focus mask의 미리보기 목적은 무엇인가요? | [Introduction](https://rawpedia.rawtherapee.com/preview_modes/) |
| `Q070` | `rawpedia` | `mask_local` | `workflow` | `complex` | RawTherapee 설명 기준 튜토리얼(rocks.md)에서 Selective Editing 시 몇 개의 RT-spots를 사용하며 첫 번째 spot에는 어떤 도구(GHS 등)가 적용되었나요? | [Selective Editing - 5 RT-spots](https://rawpedia.rawtherapee.com/tutorials/game_changer/rocks/) |
| `Q071` | `rawpedia` | `settings_workflow` | `workflow` | `factoid` | RawTherapee에서 편집 중인 사이드카 처리 프로필(PP3)이 디스크에 실제 파일로 기록되는 시점이나 트리거 조건들은 무엇인가요? | [Saving](https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/) |
| `Q072` | `rawpedia` | `settings_workflow` | `workflow` | `complex` | RawTherapee에서 부분 처리 프로필(partial profile)을 적용할 때 Fill 모드와 Preserve 모드의 동작 차이 및 누락된 파라미터 처리 방식은 무엇인가요? | [Partial Processing Profiles and Fill Modes](https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/) |
| `Q073` | `rawpedia` | `settings_workflow` | `workflow` | `factoid` | RawTherapee에서 에디터 탭의 즉시 저장(Save immediately)을 실행했을 때 에디터의 반응성에 미치는 영향과 큐(Queue) 사용을 권장하는 이유는 무엇인가요? | [Save Immediately](https://rawpedia.rawtherapee.com/saving_images/) |
| `Q074` | `rawpedia` | `settings_workflow` | `troubleshooting` | `complex` | RawTherapee에서 동일한 원본 파일로 여러 버전을 저장할 때 파일명 덮어쓰기 충돌을 방지하는 옵션과 Save 창을 통해 큐에 보낼 때 개별 설정 장점은 무엇인가요? | [Put to the Head / Tail of the Processing Queue](https://rawpedia.rawtherapee.com/saving_images/) |
| `Q075` | `rawpedia` | `settings_workflow` | `usage/how-to` | `factoid` | RawTherapee의 Queue 설정 중 Use template에서 원본 파일명(%f), 상위 폴더(%d1), 절대 경로(%p1) 및 사진 등급(%r) 서식 문자의 치환 규칙은 무엇인가요? | [Queue Settings](https://rawpedia.rawtherapee.com/queue/) |
| `Q076` | `rawpedia` | `settings_workflow` | `workflow` | `complex` | RawTherapee에서 큐 탭의 전역 설정 대신 Save 창의 설정을 강제 적용하는 조건(Force saving options)과 큐의 지속성(Persistence) 동작은 어떠한가요? | [Introduction](https://rawpedia.rawtherapee.com/queue/) |
| `Q077` | `rawpedia` | `settings_workflow` | `workflow` | `complex` | 범용으로 재사용 가능한 처리 프로필을 만들 때 필요한 파라미터만 부분 저장(Ctrl+Save)하는 방법과, 다양한 사진 간 호환성을 위해 노출값 대신 Auto Levels 사용 및 불필요한 설정(WB, 노이즈 감소 등) 배제를 권장하는 이유는 무엇인가요? | [Partial Processing Profiles](https://rawpedia.rawtherapee.com/creating_processing_profiles_for_general_use/) |
| `Q078` | `rawpedia` | `settings_workflow` | `usage/how-to` | `factoid` | RawTherapee File Browser의 일괄 조정(Sync) 도구 패널에서 Set 모드와 Add 모드의 차이점(파라미터 교체 vs 기존 값 누적 가산)은 무엇인가요? | [Sync](https://rawpedia.rawtherapee.com/batch_adjustments_-_sync/) |
| `Q079` | `rawpedia` | `settings_workflow` | `usage/how-to` | `factoid` | RawTherapee의 Resize(크기 조정) 도구는 파이프라인에서 언제 실행되며, 다운스케일링 시 디테일 손실을 보완하기 위해 제공되는 구성요소는 무엇인가요? | [Resize](https://rawpedia.rawtherapee.com/resize/) |
| `Q080` | `rawpedia` | `settings_workflow` | `workflow` | `complex` | RawTherapee에서 config 폴더와 cache 폴더의 주요 역할 차이와, 용량 확보를 위해 캐시 내 images 서브폴더를 삭제했을 때 설정 유지 여부는 어떠한가요? | [Config](https://rawpedia.rawtherapee.com/file_paths/) |
| `Q081` | `github` | `settings_workflow` | `workflow` | `complex` | GitHub Discussion #412에 정리된 Windows 환경 ART 빌드 절차에서 MSYS2 환경 업데이트 및 패키지 설치 후 VS Code에서 설정해야 하는 CMake Kit과 Launch Target은 무엇인가요? | [/body](https://github.com/orgs/artraweditor/discussions/412) |
| `Q082` | `github` | `settings_workflow` | `usage/how-to` | `complex` | GitHub Discussion #420에서 Flatpak 기반 PhotoGIMP를 ART의 외부 편집기로 연동할 때 래퍼 셸 스크립트 작성 시 파일 인수를 어떻게 전달해야 하나요? | [/body](https://github.com/orgs/artraweditor/discussions/420) |
| `Q083` | `github` | `settings_workflow` | `workflow` | `complex` | GitHub Discussion #420에서 Flatpak 기반 외부 편집기를 연동하기 위해 래퍼 셸 스크립트를 작성하는 단계와, 이를 ART 환경설정(Preferences)에 등록할 때의 경로 지정 및 실행 권한 부여 절차는 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528) |
| `Q084` | `github` | `color_wb` | `concept` | `factoid` | GitHub Discussion #424 설명 기준, ART의 Film Simulation에서 LUT가 점 단위(point-wise) 연산만 지원하여 halation과 grain을 직접 포함하지 못하는 기술적 이유와 ART 내의 대체 도구 경로는 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221) |
| `Q085` | `github` | `settings_workflow` | `workflow` | `factoid` | GitHub Discussion #440 설명 기준으로, ART의 파일 브라우저 컨텍스트 메뉴에 별도의 'Move(이동)' 메뉴가 없을 때 파일을 다른 폴더로 이동시키는 공식 대안 기능은 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/440#discussioncomment-15585143) |
| `Q086` | `github` | `mask_local` | `usage/how-to` | `complex` | GitHub Discussion #442에서 한 도구에서 생성한 마스크를 다른 도구에서 재사용하려 할 때 마스크에 이름을 부여하는 방법과, 파이프라인에서 Linked mask가 나타나는 후속(subsequent) 도구들의 순서 조건은 무엇인가요? | [/body](https://github.com/orgs/artraweditor/discussions/442) |
| `Q087` | `github` | `mask_local` | `concept` | `complex` | GitHub Discussion #442 설명 기준, 마스크 재사용 시 파이프라인 후속 도구에 대한 Linked mask 연결 방식과 일반 복사/붙여넣기(copy/paste) 방식의 파이프라인 방향 제약 및 파라메트릭 마스크 결과 차이는 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15597989) |
| `Q088` | `github` | `mask_local` | `usage/how-to` | `factoid` | GitHub Discussion #489 설명 기준으로, ART에서 타원형(ellipse) 마스크를 생성하고자 할 때 권장되는 설정 조작법은 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/489#discussioncomment-17042242) |
| `Q089` | `github` | `settings_workflow` | `troubleshooting` | `complex` | GitHub Discussion #494에서 Fedora 환경의 Flatpak 패키지로 설치한 ART가 홈 디렉토리 외의 로컬 디스크 드라이브에 접근하지 못할 때 제시된 의심 원인과 검증된 해결 방법은 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/494#discussioncomment-17204509) |
| `Q090` | `github` | `demosaic_raw` | `troubleshooting` | `factoid` | GitHub Issue #477에서 Sony Alpha A7 V 무손실 .ARW 파일 열기 시 톤 커브 왜곡 및 검은 테두리 버그가 보고되었을 때 사용자의 실제 빌드로 정상 동작이 확인된 ART 소스 트리 계열은 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/477#issuecomment-4433310082) |
| `Q091` | `github` | `settings_workflow` | `concept` | `factoid` | GitHub Issue #500 설명 기준, ART의 JPEG XL(JXL) 이미지 내보내기 시 세부 압축 설정 옵션의 제공 여부와 고정된 품질 기준은 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631) |
| `Q092` | `github` | `demosaic_raw` | `troubleshooting` | `complex` | GitHub Issue #516에서 Canon EOS R8 RAW 파일이 흰색으로 표시될 때 구형 빌드 스크립트로 생성한 자가 빌드와 AppImage 간의 동작 차이 및 썸네일 정상화를 위해 확인된 조치는 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/516#issuecomment-5102797884) |
| `Q093` | `github` | `settings_workflow` | `troubleshooting` | `factoid` | GitHub Issue #521에서 Xubuntu 사용자가 렌즈 보정 프로필 드롭다운이 비활성화되는 문제를 해결하기 위해 ART의 options 파일에 설정한 lensfun db 경로는 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/521#issuecomment-5315824799) |
| `Q094` | `github` | `mask_local` | `troubleshooting` | `complex` | GitHub Issue #524에서 1.26.8 릴리스 및 1차 나이틀리 빌드(ART-165b246-linux64)에서 여전히 발생했던 크래시 증상과 최종적으로 해결이 확인된 나이틀리 빌드 식별자는 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070) |
| `Q095` | `github` | `mask_local` | `troubleshooting` | `complex` | GitHub Issue #524에서 스팟 제거 활성화 후 100% 확대 시 발생하는 동결/크래시 버그의 구체적인 재현 절차와 개발자가 안내한 Debug 빌드 생성 옵션은 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/524) |
| `Q096` | `github` | `settings_workflow` | `usage/how-to` | `negative` | GitHub Issue #500 설명 기준으로, ART의 내보내기 대화상자에서 JPEG XL(JXL) 전용 품질 슬라이더를 활성화하여 압축 품질을 50으로 직접 설정하는 절차는 무엇인가요? | [/body](https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631) |
| `Q097` | `github` | `color_wb` | `usage/how-to` | `negative` | GitHub Discussion #424 설명 기준으로, Film Simulation 모듈 내의 3D LUT 파일 하나만을 사용하여 주변 픽셀을 참조하는 halation(빛 번짐) 공간 연산을 직접 구현 및 적용하는 설정 절차는 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221) |
| `Q098` | `github` | `color_wb` | `usage/how-to` | `negative` | GitHub Discussion #424 설명 기준으로, Film Simulation LUT 자체 내부에서 공간 연산(spatial operation) 알고리즘을 구동하여 픽셀 이웃 기반의 필름 그레인(film grain)을 직접 생성하도록 설정하는 방법은 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221) |
| `Q099` | `github` | `mask_local` | `usage/how-to` | `negative` | GitHub Discussion #442 설명 기준으로, 파이프라인 뒤쪽에 위치한 도구에서 정의한 named mask를 파이프라인 앞쪽(upstream) 도구에 동적 'Linked mask'로 직접 연결하여 사용하는 절차는 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701) |
| `Q100` | `github` | `mask_local` | `workflow` | `negative` | GitHub Discussion #442 설명 기준으로, 파이프라인상 서로 다른 처리 위치를 갖는 도구 간에 parametric mask를 복사/붙여넣기할 때 생성되는 마스크 픽셀 결과가 완전히 100% 동일함을 강제 보장하는 워크플로우 설정법은 무엇인가요? | [/body](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701) |

## 3. 문항별 상세 명세 및 원문 근거 스팬

### Q001. RawPedia 설명에서 Auto Levels는 무엇을 분석해 Exposure 설정을 조정하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Exposure`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Exposure"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Exposure`
   - 소스 파일: `data/rawpedia/Exposure.md` (절: `Auto Levels`)
   - URL: [https://rawpedia.rawtherapee.com/exposure/](https://rawpedia.rawtherapee.com/exposure/)
   - 바이트 범위: `[156:288]` (UTF-8)
   - SHA-256: `b2051fffe4e88a3a4c93e57fadca2140280e446283ee0533341c517f76febbbd`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The *Auto Levels* tool analyzes the histogram and then adjusts the\ncontrols in the Exposure section to achieve a well-exposed image."
     ```

### Q002. RawPedia 기준으로 하이라이트 복원(Highlight Reconstruction) 시 Color Propagation 방식의 동작 원리와 한계는 무엇인가요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Exposure`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Exposure"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Exposure`
   - 소스 파일: `data/rawpedia/Exposure.md` (절: `Highlight Reconstruction`)
   - URL: [https://rawpedia.rawtherapee.com/exposure/](https://rawpedia.rawtherapee.com/exposure/)
   - 바이트 범위: `[2787:3006]` (UTF-8)
   - SHA-256: `ba525ea9390efb7c5eb41725647b5316685ab06b9a76a8d5319f371d20367ae2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This is the most powerful recovery method. In addition to restoring\n    luminosity, *Color Propagation* tries to restore color information\n    by 'bleeding' the surrounding known color into the missing clipped\n    area."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Exposure`
   - 소스 파일: `data/rawpedia/Exposure.md` (절: `Highlight Reconstruction`)
   - URL: [https://rawpedia.rawtherapee.com/exposure/](https://rawpedia.rawtherapee.com/exposure/)
   - 바이트 범위: `[3104:3389]` (UTF-8)
   - SHA-256: `99530d705d7e8e7c77cf1010a256828cc3719dc3a106f0a36537ca081cf28dce`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Its weakness is that it may\n    sometimes 'bleed' the incorrect colors, depending on the image\n    elements surrounding the blown highlights, or the colors can bleed\n    into undesirable patterns. It is also computationally intensive and\n    is therefore slower than the other methods."
     ```

### Q003. Dynamic Range Compression 도구의 Anchor 슬라이더는 어떤 역할을 하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Dynamic_Range_Compression`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Dynamic_Range_Compression"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Dynamic_Range_Compression`
   - 소스 파일: `data/rawpedia/Dynamic_Range_Compression.md` (절: `Anchor`)
   - URL: [https://rawpedia.rawtherapee.com/dynamic_range_compression/](https://rawpedia.rawtherapee.com/dynamic_range_compression/)
   - 바이트 범위: `[3810:3920]` (UTF-8)
   - SHA-256: `edbfa1bc32a4b759f81dc52a6532a72766d15c43f5b364d4aaa8d9766295f652`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Biases the compression towards the shadows or highlights, effectively\nfunctioning as an exposure compensation."
     ```

### Q004. Dynamic Range Compression을 적용할 때 압축 강도(Amount)와 로컬 대비(Detail) 슬라이더는 이미지 톤과 대비에 각각 어떤 영향을 주나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Dynamic_Range_Compression`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Dynamic_Range_Compression"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Dynamic_Range_Compression`
   - 소스 파일: `data/rawpedia/Dynamic_Range_Compression.md` (절: `Amount`)
   - URL: [https://rawpedia.rawtherapee.com/dynamic_range_compression/](https://rawpedia.rawtherapee.com/dynamic_range_compression/)
   - 바이트 범위: `[3493:3637]` (UTF-8)
   - SHA-256: `ed6aba12119508fcf8170e77552ce057fed64f6fb190c204db4fed0953042121`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Sets the strength of the compression. Higher values lead to a narrower\ndynamic range (you can easily see the effect by observing the\nhistogram)."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Dynamic_Range_Compression`
   - 소스 파일: `data/rawpedia/Dynamic_Range_Compression.md` (절: `Detail`)
   - URL: [https://rawpedia.rawtherapee.com/dynamic_range_compression/](https://rawpedia.rawtherapee.com/dynamic_range_compression/)
   - 바이트 범위: `[3651:3796]` (UTF-8)
   - SHA-256: `59d7f054b03caeff3d71341945fde4ca65fae5af16bd661e3c1f16ba73941892`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Sets how much local contrast is preserved. Positive values reduce the\ncompression in favor of more contrast, negative values reduce the\ncontrast."
     ```

### Q005. Shadows & Highlights 도구에서 Lab 색공간 대신 RGB 색공간을 사용할 때의 장점과 주의할 점은 무엇인가요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Shadows & Highlights`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Shadows & Highlights"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Shadows & Highlights`
   - 소스 파일: `data/rawpedia/Shadows & Highlights.md` (절: `Color Space`)
   - URL: [https://rawpedia.rawtherapee.com/shadows-highlights/](https://rawpedia.rawtherapee.com/shadows-highlights/)
   - 바이트 범위: `[818:1001]` (UTF-8)
   - SHA-256: `b53ba3253a7500264c8dd721da160dffa69fec009377f8422d40cecd45faa5b0`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Adjusting shadows and highlights in the RGB space preserves image\nsaturation which usually looks more natural than working in L\\*a\\*b\\*\nspace which tends to desaturate affected areas."
     ```

### Q006. Shadows & Highlights 도구에서 Tonal Width와 Radius 슬라이더는 효과 적용 범위를 각각 어떻게 제어하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Shadows & Highlights`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Shadows & Highlights"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Shadows & Highlights`
   - 소스 파일: `data/rawpedia/Shadows & Highlights.md` (절: `Tonal Width`)
   - URL: [https://rawpedia.rawtherapee.com/shadows-highlights/](https://rawpedia.rawtherapee.com/shadows-highlights/)
   - 바이트 범위: `[1286:1487]` (UTF-8)
   - SHA-256: `735610ee5f585b91358f3287891b55cd90d5fbc14e71566e3a6978c57573ce57`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Shadows/Highlights Tonal Width allows you to control how bright an area\nmust be for it to be affected by the highlights slider, and how dark an\narea must be for it to be affected by the shadows slider."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Shadows & Highlights`
   - 소스 파일: `data/rawpedia/Shadows & Highlights.md` (절: `Radius`)
   - URL: [https://rawpedia.rawtherapee.com/shadows-highlights/](https://rawpedia.rawtherapee.com/shadows-highlights/)
   - 바이트 범위: `[1905:2004]` (UTF-8)
   - SHA-256: `e3a97034ec04088a26119a2ce08e5103236537a998875c0b47bf72cdcea623fb`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The value of the Radius slider influences the effective area of the\nShadows and Highlights sliders."
     ```

### Q007. Tone Mapping 도구에서 Gamma 슬라이더의 동작 원리는 무엇인가요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Tone_Mapping`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Tone_Mapping"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Tone_Mapping`
   - 소스 파일: `data/rawpedia/Tone_Mapping.md` (절: `Gamma`)
   - URL: [https://rawpedia.rawtherapee.com/tone_mapping/](https://rawpedia.rawtherapee.com/tone_mapping/)
   - 바이트 범위: `[3617:3681]` (UTF-8)
   - SHA-256: `d571f63a1ab1bf193d161612dc4fd9ba1a80ad9d711bf1885b2cc91df3c02869`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Gamma moves the action of tone-mapping to shadows or highlights."
     ```

### Q008. Tone Mapping 적용 후 만화 같은 과장된 외관(cartoonish appearance)이나 소프트 후광 문제가 발생할 때 어떤 옵션 값을 올려야 하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Tone_Mapping`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Tone_Mapping"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Tone_Mapping`
   - 소스 파일: `data/rawpedia/Tone_Mapping.md` (절: `Reweighting Iterates`)
   - URL: [https://rawpedia.rawtherapee.com/tone_mapping/](https://rawpedia.rawtherapee.com/tone_mapping/)
   - 바이트 범위: `[4245:4451]` (UTF-8)
   - SHA-256: `b53743f2874547d9785d2115ebb400e6e81e8f614e79ec6aa6200a28cc1e8ee9`
   - 원문 스팬 (JSON String Literal):
     ```json
     "In some cases tone mapping may result in a cartoonish appearance, and in\nsome rare cases soft but wide halos may appear. Increasing the number of\nreweighting iterates will help fight some of these problems."
     ```

### Q009. Local Contrast 도구의 Amount 슬라이더는 이미지 대비에 어떤 영향을 주나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Local_Contrast`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Local_Contrast"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Local_Contrast`
   - 소스 파일: `data/rawpedia/Local_Contrast.md` (절: `Amount`)
   - URL: [https://rawpedia.rawtherapee.com/local_contrast/](https://rawpedia.rawtherapee.com/local_contrast/)
   - 바이트 범위: `[1269:1432]` (UTF-8)
   - SHA-256: `37279c47c25002fcd334645d82a1c160a291f9637d2bfbc5c0a75bb8de44b851`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Determines the overall strength of the effect. Higher values amplify the\ndifferences between the original image and the blurred image, thereby\nincreasing contrast."
     ```

### Q010. Local Contrast 도구에서 Darkness Level과 Lightness Level 슬라이더는 각각 어떤 영역을 변경하며, 둘 다 0으로 설정하면 도구는 어떻게 동작하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Local_Contrast`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Local_Contrast"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Local_Contrast`
   - 소스 파일: `data/rawpedia/Local_Contrast.md` (절: `Darkness/Lightness Levels`)
   - URL: [https://rawpedia.rawtherapee.com/local_contrast/](https://rawpedia.rawtherapee.com/local_contrast/)
   - 바이트 범위: `[1465:1774]` (UTF-8)
   - SHA-256: `e8e1526805a92d82391355b9236b7bd7275c17cbb3b5a8ccd5bf3fba49803e15`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The \"Darkness Level\" parameter modifies only those areas of the image\nthat were darkened with respect to the original. Higher values amplify\nthe change (making darker parts even darker), lower values diminish the\nchange. N.B. A value of 0 means the local contrast is only modified by\nmaking the image lighter."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Local_Contrast`
   - 소스 파일: `data/rawpedia/Local_Contrast.md` (절: `Darkness/Lightness Levels`)
   - URL: [https://rawpedia.rawtherapee.com/local_contrast/](https://rawpedia.rawtherapee.com/local_contrast/)
   - 바이트 범위: `[1776:1966]` (UTF-8)
   - SHA-256: `a51a6b54ba537ca9e66184dd8f93d826693a6ce58bed9cf4830673ac438d541f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The \"Lightness Level\" parameter works similarly, but only on areas that\nwere lightened.\n\nNote that setting both the \"Darkness Level\" and \"Lightness Level\" to 0\neffectively disables the tool."
     ```

### Q011. RGB Curves 도구의 Luminosity Mode는 어떤 목적으로 사용되며, 다른 도구(HSV Equalizer, Channel Mixer)와 비교할 때 어떤 제어 특성을 갖나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:RGB_Curves`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:RGB_Curves"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:RGB_Curves`
   - 소스 파일: `data/rawpedia/RGB_Curves.md` (절: `Luminosity Mode`)
   - URL: [https://rawpedia.rawtherapee.com/rgb_curves/](https://rawpedia.rawtherapee.com/rgb_curves/)
   - 바이트 범위: `[456:634]` (UTF-8)
   - SHA-256: `41bfc7296b8749a71ff426559b10e5ffbdbd4270ef4475b81553c51221d69c8f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The purpose of *Luminosity Mode* in the *RGB Curves* tool is to alter\nimage luminosity by changing the contribution of the RGB channels to it,\nwhile keeping image color the same."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:RGB_Curves`
   - 소스 파일: `data/rawpedia/RGB_Curves.md` (절: `Luminosity Mode`)
   - URL: [https://rawpedia.rawtherapee.com/rgb_curves/](https://rawpedia.rawtherapee.com/rgb_curves/)
   - 바이트 범위: `[636:933]` (UTF-8)
   - SHA-256: `293dcf4c118cae8b1c9a00c0adb2fcbe3e3e51bf83c2c6265f50a852c277220f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The effect is somewhat similar to *V* changes in the\n[HSV Equalizer](hsv_equalizer), but is smoother and broader across\nhues, not as selective. When working on black-and-white images, similar\nadjustments could be made via the\n[Channel Mixer](channel_mixer), but *RGB Curves* allow a finer\ncontrol."
     ```

### Q012. RawPedia 설명 기준으로 RGB curves를 각 채널별로 다르게 적용하면 어떤 색조 효과를 연출할 수 있나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:RGB_Curves`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:RGB_Curves"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:RGB_Curves`
   - 소스 파일: `data/rawpedia/RGB_Curves.md` (절: `RGB Curves`)
   - URL: [https://rawpedia.rawtherapee.com/rgb_curves/](https://rawpedia.rawtherapee.com/rgb_curves/)
   - 바이트 범위: `[322:434]` (UTF-8)
   - SHA-256: `dc0ce57b8a1b2f899352884055a072b468f1bcb00eeda65d92ed3adc8215161c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Using RGB\ncurves one could make warmer highlights or colder shadows, simulate film\ncross-processing effect, etc."
     ```

### Q013. 에디터의 클리핑 표시기(Clipping Indication)에서 clipped highlight 경고는 어떤 조건에서 표시되나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Clipping_Indication`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Clipping_Indication"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Clipping_Indication`
   - 소스 파일: `data/rawpedia/Clipping_Indication.md` (절: `Clipping Indication`)
   - URL: [https://rawpedia.rawtherapee.com/clipping_indication/](https://rawpedia.rawtherapee.com/clipping_indication/)
   - 바이트 범위: `[651:786]` (UTF-8)
   - SHA-256: `fe6223bd60c11819d39891fba4214073e2b11df73297db90118c252d5b227e36`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The clipped **highlight** indicator will highlight areas where at least\none channel lies at or above the specified highlight threshold."
     ```

### Q014. Haze Removal 도구 사용 시 안개 제거 효과가 가장 강하게 적용되는 영역을 시각적으로 확인하려면 어떤 기능을 켜야 하나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Haze_Removal`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Haze_Removal"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Haze_Removal`
   - 소스 파일: `data/rawpedia/Haze_Removal.md` (절: `Usage`)
   - URL: [https://rawpedia.rawtherapee.com/haze_removal/](https://rawpedia.rawtherapee.com/haze_removal/)
   - 바이트 범위: `[548:677]` (UTF-8)
   - SHA-256: `ab338b44a4c44e42eb6a0c32f829670556aeae00373b9760d4578e593d1f9573`
   - 원문 스팬 (JSON String Literal):
     ```json
     "You can visualize which areas\nare most affected by enabling the depth map - the lighter the color, the\nmore that area is dehazed."
     ```

### Q015. Soft Light 도구는 어떤 소프트웨어의 블렌드 모드를 모방하며, 결과 이미지에 어떤 시각적 변화를 주나요?

- **분류**: 카테고리 `exposure_tone` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Soft_Light`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Soft_Light"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Soft_Light`
   - 소스 파일: `data/rawpedia/Soft_Light.md` (절: `Soft Light`)
   - URL: [https://rawpedia.rawtherapee.com/soft_light/](https://rawpedia.rawtherapee.com/soft_light/)
   - 바이트 범위: `[175:333]` (UTF-8)
   - SHA-256: `2a8b26e1ea1e2983a3603eb7b7b43fae34f760cec7853958ed1698f1dbe72f03`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This tool emulates the effect of blending an image with a copy of itself\nin [\"soft-light\"](https://en.wikipedia.org/wiki/Blend_modes#Soft_Light)\nmode in GIMP."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Soft_Light`
   - 소스 파일: `data/rawpedia/Soft_Light.md` (절: `Soft Light`)
   - URL: [https://rawpedia.rawtherapee.com/soft_light/](https://rawpedia.rawtherapee.com/soft_light/)
   - 바이트 범위: `[334:433]` (UTF-8)
   - SHA-256: `684f77f6c79c4afe12ff299c6de6064493adbae2d6f299d66d81f42330de9cc4`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The resulting image has a little extra contrast and\nsaturation, which is usually visually pleasing."
     ```

### Q016. Unclipped 프로필을 적용하여 저장할 때 요구되는 출력 ICC 프로필 조건과 권장 저장 파일 포맷은 무엇인가요?

- **분류**: 카테고리 `exposure_tone` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Unclipped`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Unclipped"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Unclipped`
   - 소스 파일: `data/rawpedia/Unclipped.md` (절: `Usage`)
   - URL: [https://rawpedia.rawtherapee.com/unclipped/](https://rawpedia.rawtherapee.com/unclipped/)
   - 바이트 범위: `[2739:2832]` (UTF-8)
   - SHA-256: `36c7d9964bc0c8f67d643fdef4e073cb7e81e781c2bd00d792dc6e570e5565e8`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Ensure\n    that your output ICC profile is either v4, or a linear tone response\n    curve v2."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Unclipped`
   - 소스 파일: `data/rawpedia/Unclipped.md` (절: `Usage`)
   - URL: [https://rawpedia.rawtherapee.com/unclipped/](https://rawpedia.rawtherapee.com/unclipped/)
   - 바이트 범위: `[3469:3559]` (UTF-8)
   - SHA-256: `d9a370adfaec586d7271caa3a634347a71b47484adf7173c6064779811c6b7d7`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Save the image as either a 16-bit floating-point TIFF or a 32-bit\n    floating-point TIFF."
     ```

### Q017. White Balance 도구의 temperature 슬라이더는 어떤 색상 축을 기준으로 이미지를 조절하나요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:White_Balance`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:White_Balance"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:White_Balance`
   - 소스 파일: `data/rawpedia/White_Balance.md` (절: `Temperature and Tint`)
   - URL: [https://rawpedia.rawtherapee.com/white_balance/](https://rawpedia.rawtherapee.com/white_balance/)
   - 바이트 범위: `[6968:7140]` (UTF-8)
   - SHA-256: `9e400349f4574b64d9c8bd1e81215645d9d60158e0aad489b16a4bb859f17869`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The temperature slider adjusts colors along the blue-yellow axis. Moving\nit to the left makes the image cooler (bluish); moving it to the right\nmakes it warmer (yellowish)."
     ```

### Q018. RAW 이미지에서 화이트 밸런스가 RGB 채널 가중치로 변환될 때 클리핑 제어 방식과, Temperature correlation 알고리즘이 잘못된 결과를 낼 수 있는 조명 조건은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:White_Balance`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:White_Balance"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:White_Balance`
   - 소스 파일: `data/rawpedia/White_Balance.md` (절: `White Balance Connection to Exposure`)
   - URL: [https://rawpedia.rawtherapee.com/white_balance/](https://rawpedia.rawtherapee.com/white_balance/)
   - 바이트 범위: `[7988:8316]` (UTF-8)
   - SHA-256: `80cb395a5868713f2cc2713bfd42ad6a908d74ae3fb819cc1fe8554f960e433b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The white balance is described in temperature and tint, but when working\nwith raw images it will be translated into weights of the red, green and\nblue channels. The weights will be adjusted so that the channel with the\nsmallest weight reaches clipping in the working space (usually ProPhoto\nRGB) when the raw channel is clipped."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:White_Balance`
   - 소스 파일: `data/rawpedia/White_Balance.md` (절: `Method`)
   - URL: [https://rawpedia.rawtherapee.com/white_balance/](https://rawpedia.rawtherapee.com/white_balance/)
   - 바이트 범위: `[3798:4205]` (UTF-8)
   - SHA-256: `b96fed2cba0be47ae54396313885a71d9e8e3b0aa25a218b68b882a4bc68235f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This algorithm may give erroneous results:\n      - If the illuminant does not have a CRI (Color Rendering Index)\n        close to 100, e.g. \"Underwater\", \"Fluorescent\", \"Led\" lighting\n        conditions may give bad results.\n      - Some DNG-type files obtained after conversion with a DNG or\n        other converter.\n      - If the shooting conditions are extreme (very low luminance\n        values, etc.)."
     ```

### Q019. Color Management에서 카메라 RAW 데이터를 내부 작업 색공간으로 변환할 때 입력 프로필(Input Profile)이 없으면 어떤 문제가 발생하나요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Color_Management`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Color_Management"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Color_Management`
   - 소스 파일: `data/rawpedia/Color_Management.md` (절: `Input Profile`)
   - URL: [https://rawpedia.rawtherapee.com/color_management/](https://rawpedia.rawtherapee.com/color_management/)
   - 바이트 범위: `[774:1350]` (UTF-8)
   - SHA-256: `dffba3599585b6be9a59fa1d82658afb2c2d4ddcd34742d6264278bf15d0e463`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This conversion requires an input profile made\nspecifically for the camera. Such a profile is the result of the\nanalysis of how specific colors and tones are captured, processed and\nrepresented as raw data by the camera (for more details, see e.g.\n[Elle Stone's article](https://ninedegreesbelow.com/photography/articles.html#profile-digital-camera),\n[DCamProf's documentation](https://torger.se/anders/dcamprof.html) or\n[How to create DCP color profiles](how_to_create_dcp_color_profiles). Without a\ncamera-specific input profile, accurate color representation is\nimpossible."
     ```

### Q020. Color Management에서 기본 작업 프로필(Working Profile)의 권장 설정과 출력 프로필(Output Profile)의 동작 특성은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Color_Management`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Color_Management"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Color_Management`
   - 소스 파일: `data/rawpedia/Color_Management.md` (절: `Working Profile`)
   - URL: [https://rawpedia.rawtherapee.com/color_management/](https://rawpedia.rawtherapee.com/color_management/)
   - 바이트 범위: `[15663:15968]` (UTF-8)
   - SHA-256: `b28fcdf610175f07864f3605355d5584d58e0d5ea0cfccb2971ce6bee9f59572`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The default working profile is ProPhoto and should not be changed for\nnormal use.\n\nThe working profile specifies the working color space, which is the\ncolor space used for internal calculations, for instance for calculating\nsaturation, RGB brightness/contrast and tone curve adjustments,\nchrominance, etc."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Color_Management`
   - 소스 파일: `data/rawpedia/Color_Management.md` (절: `Output Profile`)
   - URL: [https://rawpedia.rawtherapee.com/color_management/](https://rawpedia.rawtherapee.com/color_management/)
   - 바이트 범위: `[66941:67161]` (UTF-8)
   - SHA-256: `056f9d6161263e70645efcd8b4edc6af238d1bd5b3fb195e1e8b5aa1d935cfaa`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Specify the output color profile; the saved image will be transformed\ninto this color space and the profile will be embedded in the metadata.\nThe effects the output profile has on the image cannot be seen in the\npreview."
     ```

### Q021. Gamut Compression 도구의 기본 목적은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Gamut_compression`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Gamut_compression"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Gamut_compression`
   - 소스 파일: `data/rawpedia/Gamut_compression.md` (절: `Gamut Compression`)
   - URL: [https://rawpedia.rawtherapee.com/gamut_compression/](https://rawpedia.rawtherapee.com/gamut_compression/)
   - 바이트 범위: `[111:237]` (UTF-8)
   - SHA-256: `965ffef165a6ee76fe7e8e70dfaff875a345add715426b37ab914d8984e310da`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Gamut Compression is a tool that allows you to compress highly chromatic camera-source colorimetric data into a smaller gamut."
     ```

### Q022. Gamut Compression 도구에서 Threshold 슬라이더의 동작 방식과 별표(*) 표시 작업공간의 사전 계산 임계값 특성은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Gamut_compression`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Gamut_compression"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Gamut_compression`
   - 소스 파일: `data/rawpedia/Gamut_compression.md` (절: `Threshold`)
   - URL: [https://rawpedia.rawtherapee.com/gamut_compression/](https://rawpedia.rawtherapee.com/gamut_compression/)
   - 바이트 범위: `[2524:2725]` (UTF-8)
   - SHA-256: `4464042e86e594a472dec83bd9e28ad7238456829e84c9be4c6bf4a1950fb067`
   - 원문 스팬 (JSON String Literal):
     ```json
     "controls the percentage of the outer gamut that will be affected. A value of 0.8 will compress out of gamut values into the outer 20% of the gamut. The inner 80% of the gamut core will not be affected."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Gamut_compression`
   - 소스 파일: `data/rawpedia/Gamut_compression.md` (절: `Gamut Compression`)
   - URL: [https://rawpedia.rawtherapee.com/gamut_compression/](https://rawpedia.rawtherapee.com/gamut_compression/)
   - 바이트 범위: `[1039:1374]` (UTF-8)
   - SHA-256: `b42efdf4c83a2f9981721f4eb4100a6ca6c5294ccc80da4adbea8341e1366c68`
   - 원문 스팬 (JSON String Literal):
     ```json
     "* Workspaces marked with an asterisk (*) have pre-calculated threshold values ​​for Cyan, Magenta, and Yellow. Note that these values ​​are approximate and correspond to a Working profile set to Rec2020. For challenging images (LED, sunset, etc.), manual adjustment is necessary; be mindful of potential artifacts.\n\n[Aces gamut"
     ```

### Q023. Film Simulation 도구는 필름 색감을 재현하기 위해 어떤 포맷의 참조 이미지를 요구하나요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Film_Simulation`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Film_Simulation"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Film_Simulation`
   - 소스 파일: `data/rawpedia/Film_Simulation.md` (절: `Film Simulation`)
   - URL: [https://rawpedia.rawtherapee.com/film_simulation/](https://rawpedia.rawtherapee.com/film_simulation/)
   - 바이트 범위: `[372:473]` (UTF-8)
   - SHA-256: `b160c3eaae353dcb2a2e18385609b022d307c7a88ab4d3fa6dc6e5bf76736c0c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This tool requires the use of reference images in the\nHaldCLUT pattern, in either PNG or TIFF format."
     ```

### Q024. Film Simulation용 아이덴티티 HaldCLUT를 직접 생성할 때 하이라이트 버그가 있어 사용을 피해야 하는 프로그램은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Film_Simulation`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Film_Simulation"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Film_Simulation`
   - 소스 파일: `data/rawpedia/Film_Simulation.md` (절: `Caveat`)
   - URL: [https://rawpedia.rawtherapee.com/film_simulation/](https://rawpedia.rawtherapee.com/film_simulation/)
   - 바이트 범위: `[6314:6496]` (UTF-8)
   - SHA-256: `42181a053370be6ffbd74951521e39d6aa40ea4a978b46818aeac33d7e44f41c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "If you need to generate your own identity HaldCLUT, do not use the\nprogram for generating HaldCLUT images from www.quelsolaar.com as it has\na bug which causes issues with highlights."
     ```

### Q025. Lab 색공간에서 L 컴포넌트는 인간의 시각 인지와 어떻게 연관되나요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Lab_Adjustments`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Lab_Adjustments"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Lab_Adjustments`
   - 소스 파일: `data/rawpedia/Lab_Adjustments.md` (절: `Lab Adjustments`)
   - URL: [https://rawpedia.rawtherapee.com/lab_adjustments/](https://rawpedia.rawtherapee.com/lab_adjustments/)
   - 바이트 범위: `[530:594]` (UTF-8)
   - SHA-256: `3a8e21ac4689aaca232fef5d7343ba7f03a5948c6255b052b998be68240d022f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "- The L component closely matches human perception of lightness."
     ```

### Q026. Lab Adjustments에서 Chromaticity 슬라이더의 동작 방식과 슬라이더를 -100으로 설정했을 때의 결과는 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Lab_Adjustments`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Lab_Adjustments"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Lab_Adjustments`
   - 소스 파일: `data/rawpedia/Lab_Adjustments.md` (절: `Chromaticity`)
   - URL: [https://rawpedia.rawtherapee.com/lab_adjustments/](https://rawpedia.rawtherapee.com/lab_adjustments/)
   - 바이트 범위: `[1300:1449]` (UTF-8)
   - SHA-256: `eb57d00a3d6cfc08d0c3fd5f32794513716783c7bb352bfe1e91ecfb5991c41c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The Lab Chromaticity slider increases or decreases the chromaticity of\nthe image, by applying a contrast curve to the a- and b-channels of Lab\nspace."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Lab_Adjustments`
   - 소스 파일: `data/rawpedia/Lab_Adjustments.md` (절: `Chromaticity`)
   - URL: [https://rawpedia.rawtherapee.com/lab_adjustments/](https://rawpedia.rawtherapee.com/lab_adjustments/)
   - 바이트 범위: `[1450:1530]` (UTF-8)
   - SHA-256: `b1f5764bb365f40980d3ad8a5dd7e8331a7f5409c7fd4cbe25f86d5603c463ec`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Setting this slider to -100 removes all color, making the image\nblack and white."
     ```

### Q027. Vibrance 도구의 기본 개념과 Pastel Tones 및 Saturated Tones 슬라이더의 분리 제어 기능은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Vibrance`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Vibrance"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Vibrance`
   - 소스 파일: `data/rawpedia/Vibrance.md` (절: `Vibrance`)
   - URL: [https://rawpedia.rawtherapee.com/vibrance/](https://rawpedia.rawtherapee.com/vibrance/)
   - 바이트 범위: `[124:237]` (UTF-8)
   - SHA-256: `47066adfd038350f7474eb54e0a73f9b24c7d4ff6215d2f5fe1493e7c8107d5b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "*Vibrance* is an intelligent saturation adjustment tuned to correlate\nwith the color sensitivity of human vision."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Vibrance`
   - 소스 파일: `data/rawpedia/Vibrance.md` (절: `Vibrance`)
   - URL: [https://rawpedia.rawtherapee.com/vibrance/](https://rawpedia.rawtherapee.com/vibrance/)
   - 바이트 범위: `[401:551]` (UTF-8)
   - SHA-256: `c957e51c64673676a75919d0c61d8130c4391603143cecf7989e96a486af147b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "can separately control the vibrance of *pastel* tones (tones of low\nsaturation) and *saturated* tones (as the name implies, tones of high\nsaturation)."
     ```

### Q028. Vibrance 도구에서 피부톤이 채도 조정의 영향을 받지 않도록 보호하려면 어떤 옵션을 활성화해야 하나요?

- **분류**: 카테고리 `color_wb` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Vibrance`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Vibrance"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Vibrance`
   - 소스 파일: `data/rawpedia/Vibrance.md` (절: `Protect Skin Tones`)
   - URL: [https://rawpedia.rawtherapee.com/vibrance/](https://rawpedia.rawtherapee.com/vibrance/)
   - 바이트 범위: `[971:1075]` (UTF-8)
   - SHA-256: `985f723508f42248852ee79e35f7e52cfe2cce61525a4d49332ac3db7d0c14e2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "When enabled, colors closely resembling natural skin tones are not\naffected by the vibrance adjustments."
     ```

### Q029. Black-and-White 도구의 Color Filter는 어떤 방식으로 흑백 변환 결과에 영향을 주나요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Black-and-White_addon`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Black-and-White_addon"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Black-and-White_addon`
   - 소스 파일: `data/rawpedia/Black-and-White_addon.md` (절: `Color Filter`)
   - URL: [https://rawpedia.rawtherapee.com/black-and-white_addon/](https://rawpedia.rawtherapee.com/black-and-white_addon/)
   - 바이트 범위: `[5556:5643]` (UTF-8)
   - SHA-256: `851fcf527c1d0b8e65a6ce079ec3dc997bb95fc65c0f37b029749d87bc78ccb9`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The color filter simulates shootings with a colored filter placed in\nfront of the lens."
     ```

### Q030. RawTherapee에서 Black-and-White 도구를 사용하지 않고 흑백 이미지를 만드는 대안적인 절차들은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Black-and-White_addon`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Black-and-White_addon"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Black-and-White_addon`
   - 소스 파일: `data/rawpedia/Black-and-White_addon.md` (절: `General remarks`)
   - URL: [https://rawpedia.rawtherapee.com/black-and-white_addon/](https://rawpedia.rawtherapee.com/black-and-white_addon/)
   - 바이트 범위: `[346:439]` (UTF-8)
   - SHA-256: `2bca4eaef8bcc18fac19ad6772fde82a89addd207de39f9c30c5f469f9ad978f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Please note that Rawtherapee can produce black-and-white images without\nthe use of this tool:"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Black-and-White_addon`
   - 소스 파일: `data/rawpedia/Black-and-White_addon.md` (절: `General remarks`)
   - URL: [https://rawpedia.rawtherapee.com/black-and-white_addon/](https://rawpedia.rawtherapee.com/black-and-white_addon/)
   - 바이트 범위: `[441:703]` (UTF-8)
   - SHA-256: `8fef8740fc7a243491d64a9820984d205ef8fe713ee2ccf6ad1f3306cb65b978`
   - 원문 스팬 (JSON String Literal):
     ```json
     "1.  by setting the [Saturation](exposure#saturation) slider\n    in the [Exposure](exposure) tool of the Exposure tab to\n    -100;\n2.  by setting the\n    [Chromaticity](lab_adjustments#chromaticity) slider in\n    the [Lab Adjustments](lab_adjustments) tab to -100"
     ```

### Q031. RGB와 CIE Lab 색공간의 정의와 두 색공간 간 보정 차이에 대한 일반적인 의문은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:RGB_and_Lab`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:RGB_and_Lab"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:RGB_and_Lab`
   - 소스 파일: `data/rawpedia/RGB_and_Lab.md` (절: `RGB and Lab`)
   - URL: [https://rawpedia.rawtherapee.com/rgb_and_lab/](https://rawpedia.rawtherapee.com/rgb_and_lab/)
   - 바이트 범위: `[87:335]` (UTF-8)
   - SHA-256: `c73293e28f1766e3708d4f7ade9a463186a2b92f72d1f5052fbe65e8c7dc6ab6`
   - 원문 스팬 (JSON String Literal):
     ```json
     "*[RGB](https://en.wikipedia.org/wiki/RGB_color_space)* and *[CIE L\\*a\\*b\\*](https://en.wikipedia.org/wiki/Lab_color_space)* (or just\n\"*Lab*\") are two different [color spaces](https://en.wikipedia.org/wiki/Color_space), or ways of\ndescribing colors."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:RGB_and_Lab`
   - 소스 파일: `data/rawpedia/RGB_and_Lab.md` (절: `RGB and Lab`)
   - URL: [https://rawpedia.rawtherapee.com/rgb_and_lab/](https://rawpedia.rawtherapee.com/rgb_and_lab/)
   - 바이트 범위: `[337:521]` (UTF-8)
   - SHA-256: `129dc83ba78adae50bd45fbaba88f3893392f08dd9e4ccaa23f3e8a5a64a5e8f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Many people wonder what the differences are between adjusting lightness,\ncontrast and saturation in the RGB color space, or lightness, contrast\nand chromaticity in the Lab color space."
     ```

### Q032. Channel Mixer 도구는 어떤 용도로 사용되며 출력 채널 섹션은 어떻게 구성되어 있나요?

- **분류**: 카테고리 `color_wb` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Channel_Mixer`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Channel_Mixer"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Channel_Mixer`
   - 소스 파일: `data/rawpedia/Channel_Mixer.md` (절: `Channel Mixer`)
   - URL: [https://rawpedia.rawtherapee.com/channel_mixer/](https://rawpedia.rawtherapee.com/channel_mixer/)
   - 바이트 범위: `[122:363]` (UTF-8)
   - SHA-256: `90305573a6dcc782986b11ed02dd7d82e9c94ef30d3c3d3f6bbf4dc8bae52c49`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The *Channel Mixer* is used for special effects, for color and\nblack-and-white alike. The *Channel Mixer* is divided into three\nsections: Red, Green and Blue. Those sections represent the three\navailable color output channels in a RGB image."
     ```

### Q033. 디지털 카메라 센서의 물리적 한계와 이를 보정하기 위해 DCP 프로필이 필요한 이유는 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:How_to_create_DCP_color_profiles`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:How_to_create_DCP_color_profiles"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:How_to_create_DCP_color_profiles`
   - 소스 파일: `data/rawpedia/How_to_create_DCP_color_profiles.md` (절: `What Are DCP Profiles and Why Do I Need Them?`)
   - URL: [https://rawpedia.rawtherapee.com/how_to_create_dcp_color_profiles/](https://rawpedia.rawtherapee.com/how_to_create_dcp_color_profiles/)
   - 바이트 범위: `[177:426]` (UTF-8)
   - SHA-256: `f98a1ebb07085c9866cb5b74b4c94b55b7668b764497d4faf90b0c5b8838e608`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Technically, each photosite in a digital photography camera's [image sensor](http://en.wikipedia.org/wiki/Image_sensor) outputs a certain\ncurrent based on the number of\n[photons](http://en.wikipedia.org/wiki/Photon) of light that hit that\nphotosite."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:How_to_create_DCP_color_profiles`
   - 소스 파일: `data/rawpedia/How_to_create_DCP_color_profiles.md` (절: `What Are DCP Profiles and Why Do I Need Them?`)
   - URL: [https://rawpedia.rawtherapee.com/how_to_create_dcp_color_profiles/](https://rawpedia.rawtherapee.com/how_to_create_dcp_color_profiles/)
   - 바이트 범위: `[1134:1293]` (UTF-8)
   - SHA-256: `27e606c634e3f10aae822d354c6b5e04445816e6e4bab9d9a5292fa3aef1b132`
   - 원문 스팬 (JSON String Literal):
     ```json
     "DNG camera profile\" (DCP for short - do not confuse with the entirely\nunrelated [Digital Cinema Package](http://en.wikipedia.org/wiki/Digital_Cinema_Package))."
     ```

### Q034. ICC Profile Creator 도구를 사용하여 사용자 정의 ICC 프로필을 생성할 때 지원되는 값 설정 방식은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:icc_profile_creator`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:icc_profile_creator"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:icc_profile_creator`
   - 소스 파일: `data/rawpedia/icc_profile_creator.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/icc_profile_creator/](https://rawpedia.rawtherapee.com/icc_profile_creator/)
   - 바이트 범위: `[164:288]` (UTF-8)
   - SHA-256: `f5307a7c2dad5e5369f96e78393cb69c55a21eb30f0636a5d210b434bd4fa4b3`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The ICC Profile Creator allows you to generate your own ICC profiles.\nYou can use standard presets as well as custom values."
     ```

### Q035. 디지털 카메라 센서에서 가장 널리 사용되는 Bayer 필터의 2x2 컬러 매트릭스 구성은 어떻게 되나요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Demosaicing`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Demosaicing"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Demosaicing`
   - 소스 파일: `data/rawpedia/Demosaicing.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/demosaicing/](https://rawpedia.rawtherapee.com/demosaicing/)
   - 바이트 범위: `[678:834]` (UTF-8)
   - SHA-256: `a5dfec31ee089c025ebe50fc594c9676ef05f35a7f1a02c2f0654bf3d6c4c019`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The \"[Bayer filter](https://en.wikipedia.org/wiki/Bayer_filter)\" is the most\ncommon - it uses a repetitive 2x2 matrix of green, blue, red and green\npatches."
     ```

### Q036. Dual Demosaic 방식(예: AMaZE+VNG4)의 영역 분할 장점과 연산상의 단점은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Demosaicing`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Demosaicing"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Demosaicing`
   - 소스 파일: `data/rawpedia/Demosaicing.md` (절: `Dual Demosaic`)
   - URL: [https://rawpedia.rawtherapee.com/demosaicing/](https://rawpedia.rawtherapee.com/demosaicing/)
   - 바이트 범위: `[10146:10363]` (UTF-8)
   - SHA-256: `f6cddd8a1cd0027e1c52a7eaa4bb4c3ba7f6a412411ab04d16fc834d421d36bb`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The dual-demosaic methods, such as AMaZE+VNG4, allow you to demosaic\nareas of high contrast (i.e. detail) using one method and areas of low\ncontrast (i.e. no detail, plain areas such as sky) using the other\nalgorithm."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Demosaicing`
   - 소스 파일: `data/rawpedia/Demosaicing.md` (절: `Dual Demosaic`)
   - URL: [https://rawpedia.rawtherapee.com/demosaicing/](https://rawpedia.rawtherapee.com/demosaicing/)
   - 바이트 범위: `[10669:10788]` (UTF-8)
   - SHA-256: `5a9e8ff4a29d4dd8bcf7e724fe5a322128d220a6cb91d40eb87d8acf2c0dd555`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The downside is that the image needs to\nbe demosaiced twice, thus taking longer than using a single demosaicing\nmethod."
     ```

### Q037. Preprocessing 단계에서 Hot pixel이 발생하는 물리적 원인은 센서에서 어떻게 설명되나요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Preprocessing`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Preprocessing"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Preprocessing`
   - 소스 파일: `data/rawpedia/Preprocessing.md` (절: `Hot/Dead Pixel Filter`)
   - URL: [https://rawpedia.rawtherapee.com/preprocessing/](https://rawpedia.rawtherapee.com/preprocessing/)
   - 바이트 범위: `[4602:4751]` (UTF-8)
   - SHA-256: `54e38da2954f67b3d4469fff8f2b5d143bb55f50eee5fb7c6040c62e1842c029`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Hot pixels\" appear as bright and saturated\ntiny dots. Each one is the result of a photosite on the sensor\noutputting a higher current than it should."
     ```

### Q038. 센서 제조 공정의 한계로 두 초록 채널 간 감도 차이가 날 때 발생하는 보간 아티팩트와 Green equilibration의 임계값(threshold) 역할은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Preprocessing`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Preprocessing"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Preprocessing`
   - 소스 파일: `data/rawpedia/Preprocessing.md` (절: `Green Equilibration`)
   - URL: [https://rawpedia.rawtherapee.com/preprocessing/](https://rawpedia.rawtherapee.com/preprocessing/)
   - 바이트 범위: `[2935:3095]` (UTF-8)
   - SHA-256: `44cb4f1724c637c3ef0100bbe17ee6223bbdb9c5e1bb88d355ee211956968cf5`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Green equilibration suppresses interpolation artifacts that\ncan result from using demosaic algorithms which assume identical\nresponse of the two green channels."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Preprocessing`
   - 소스 파일: `data/rawpedia/Preprocessing.md` (절: `Green Equilibration`)
   - URL: [https://rawpedia.rawtherapee.com/preprocessing/](https://rawpedia.rawtherapee.com/preprocessing/)
   - 바이트 범위: `[3096:3195]` (UTF-8)
   - SHA-256: `597376c40b4a88eed0a955100a9b9b263c943d35e2de5ce41feae10f26b0afa3`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The threshold sets the percentage\ndifference below which neighboring green values are equilibrated."
     ```

### Q039. Flat-Field 도구가 보정할 수 있는 렌즈 비네팅 및 렌즈 캐스트 현상과 플랫 필드 샷 촬영 시 권장 감도(ISO)는 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Flat-Field`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Flat-Field"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Flat-Field`
   - 소스 파일: `data/rawpedia/Flat-Field.md` (절: `Flat-Field`)
   - URL: [https://rawpedia.rawtherapee.com/flat-field/](https://rawpedia.rawtherapee.com/flat-field/)
   - 바이트 범위: `[378:624]` (UTF-8)
   - SHA-256: `412bd4bd0f145924e25d58f9cf674ccabd178aca0981aeb386b67f8af180a85c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "vignetting - a peripheral darkening of the image, more pronounced in the\ncorner areas. Another example, more familiar to users of digital medium\nformat cameras, is the lens cast effect - both color and luminance\nnon-uniformity of the image field."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Flat-Field`
   - 소스 파일: `data/rawpedia/Flat-Field.md` (절: `Creating and Using Flat-Field Images for the Correction of Camera/Lens Aberrations`)
   - URL: [https://rawpedia.rawtherapee.com/flat-field/](https://rawpedia.rawtherapee.com/flat-field/)
   - 바이트 범위: `[3921:4017]` (UTF-8)
   - SHA-256: `49731e8e935b078e44c0b75c8f65fb9f8f0fb82a73ff6d2811c6e906fb50ecdd`
   - 원문 스팬 (JSON String Literal):
     ```json
     "as the flat-field image gets\nblurred and should have a low ISO. Shoot it at ISO-100 if possible."
     ```

### Q040. 장노출 사진에서 Dark-frame subtraction 기법이 대처할 수 있는 노이즈 유형들은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Dark-Frame`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Dark-Frame"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Dark-Frame`
   - 소스 파일: `data/rawpedia/Dark-Frame.md` (절: `Dark-Frame`)
   - URL: [https://rawpedia.rawtherapee.com/dark-frame/](https://rawpedia.rawtherapee.com/dark-frame/)
   - 바이트 범위: `[116:269]` (UTF-8)
   - SHA-256: `bfb7ccd048f4ef68ec7df74d1a9c44f6e7303f81dde487f35d66ab16496d94ba`
   - 원문 스팬 (JSON String Literal):
     ```json
     "[Dark-frame subtraction](https://en.wikipedia.org/wiki/Dark-frame_subtraction) is a\nmethod of dealing with thermal, dark-current and fixed-pattern noise."
     ```

### Q041. Raw Black Points 도구의 주된 사용 목적은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Raw_Black_Points`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Raw_Black_Points"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Raw_Black_Points`
   - 소스 파일: `data/rawpedia/Raw_Black_Points.md` (절: `Raw Black Points`)
   - URL: [https://rawpedia.rawtherapee.com/raw_black_points/](https://rawpedia.rawtherapee.com/raw_black_points/)
   - 바이트 범위: `[130:232]` (UTF-8)
   - SHA-256: `a8bfc858e21d221de6160e06c40dda88b2b0fb83a12bbec8362ea1d6afb4ac04`
   - 원문 스팬 (JSON String Literal):
     ```json
     "It is unlikely you will ever need to use the Raw Black Points tool other\nthan for diagnostic purposes."
     ```

### Q042. Raw White Points 도구의 주된 사용 목적은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Raw_White_Points`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Raw_White_Points"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Raw_White_Points`
   - 소스 파일: `data/rawpedia/Raw_White_Points.md` (절: `Raw White Points`)
   - URL: [https://rawpedia.rawtherapee.com/raw_white_points/](https://rawpedia.rawtherapee.com/raw_white_points/)
   - 바이트 범위: `[122:224]` (UTF-8)
   - SHA-256: `5ad54ba094f0767e110f2160961e9134a58c0adf58db96529d6e9ebc577df69c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "It is unlikely you will ever need to use the Raw White Points tool other\nthan for diagnostic purposes."
     ```

### Q043. Raw Tab에 위치한 Chromatic Aberration 도구는 파이프라인의 어느 시점에서 작동하나요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Chromatic_Aberration`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Chromatic_Aberration"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Chromatic_Aberration`
   - 소스 파일: `data/rawpedia/Chromatic_Aberration.md` (절: `Chromatic Aberration`)
   - URL: [https://rawpedia.rawtherapee.com/chromatic_aberration/](https://rawpedia.rawtherapee.com/chromatic_aberration/)
   - 바이트 범위: `[272:389]` (UTF-8)
   - SHA-256: `d34b334842a4689134847c4b848b6d655716228146f7eea5796ac72ac71f2582`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This \"Chromatic Aberration\" tool\nworks on the image **before** demosaicing, that's why it's located in\nthe *Raw* tab."
     ```

### Q044. 디지털 이미지에서 비트 심도가 높아질 때의 이점과 그에 따른 대가(트레이드오프)는 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:bit_depth`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:bit_depth"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:bit_depth`
   - 소스 파일: `data/rawpedia/bit_depth.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/bit_depth/](https://rawpedia.rawtherapee.com/bit_depth/)
   - 바이트 범위: `[1151:1297]` (UTF-8)
   - SHA-256: `c9eb7437263a70107cd6f83e7f19d4e04fff4a845a614eb950c2845cce8a590b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The higher the bit depth, the more precisely a color can be described,\nat a cost of requiring longer computation, more RAM and more storage\nspace."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:bit_depth`
   - 소스 파일: `data/rawpedia/bit_depth.md` (절: `Bits Per What?`)
   - URL: [https://rawpedia.rawtherapee.com/bit_depth/](https://rawpedia.rawtherapee.com/bit_depth/)
   - 바이트 범위: `[1318:1445]` (UTF-8)
   - SHA-256: `64d1cee01b8748e1dcab1e1a31a7c114014eb9a2b31728cbeb2b0bff4788b123`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Bit depth is expressed as a value which describes either the number of\n**bits per pixel** (BPP), or **bits per channel** (BPC)."
     ```

### Q045. Flat-Field 도구의 Blur Radius 슬라이더의 기본값(32) 역할과 0으로 설정했을 때의 동작은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Flat-Field`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Flat-Field"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Flat-Field`
   - 소스 파일: `data/rawpedia/Flat-Field.md` (절: `Blur Radius`)
   - URL: [https://rawpedia.rawtherapee.com/flat-field/](https://rawpedia.rawtherapee.com/flat-field/)
   - 바이트 범위: `[17061:17248]` (UTF-8)
   - SHA-256: `b1786ed8f413c89e330a3f8797ec8a5c0777b2d0fd304c6fb562a11230b6752b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The \"Blur Radius\" slider controls the degree of blurring of the\nflat-field data. The default value of 32 is usually sufficient to get\nrid of localized variations of raw data due to noise."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Flat-Field`
   - 소스 파일: `data/rawpedia/Flat-Field.md` (절: `Blur Radius`)
   - URL: [https://rawpedia.rawtherapee.com/flat-field/](https://rawpedia.rawtherapee.com/flat-field/)
   - 바이트 범위: `[17249:17304]` (UTF-8)
   - SHA-256: `99a3ebd57f85426154bcc4603ecf8e0b279ec427868e4d9a67a8be475f768655`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Setting the blur\nradius to 0 skips the blurring process"
     ```

### Q046. 다크 프레임 Auto-selection 모드 설정 시 RawTherapee가 최적의 매칭을 탐색하는 참조 디렉터리는 환경설정의 어디에 지정하나요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Dark-Frame`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Dark-Frame"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Dark-Frame`
   - 소스 파일: `data/rawpedia/Dark-Frame.md` (절: `Dark-Frame`)
   - URL: [https://rawpedia.rawtherapee.com/dark-frame/](https://rawpedia.rawtherapee.com/dark-frame/)
   - 바이트 범위: `[1039:1183]` (UTF-8)
   - SHA-256: `df1fd237deb70a93467213c4816a93245f8d2fe1f3f0b79d1258b38c8f9c911f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Auto-Selection\" and let RT choose the best\nmatch from the directory specified in\n\"[Preferences](preferences) \\> Image Processing \\>\nDark-Frame\"."
     ```

### Q047. Capture Sharpening 도구는 촬영 시 광학적으로 발생하는 어떤 요인들로 인한 블러를 보정하기 위해 사용되나요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Capture_Sharpening`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Capture_Sharpening"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Capture_Sharpening`
   - 소스 파일: `data/rawpedia/Capture_Sharpening.md` (절: `What is it`)
   - URL: [https://rawpedia.rawtherapee.com/capture_sharpening/](https://rawpedia.rawtherapee.com/capture_sharpening/)
   - 바이트 범위: `[241:493]` (UTF-8)
   - SHA-256: `ba2a2cd8d2052aaf81dd0cb59f7e398b6a4392e8dbbd393276def078ed0eb88d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "diffraction](https://www.cambridgeincolour.com/tutorials/diffraction-photography.htm),\n[the anti-aliasing filter](https://en.wikipedia.org/wiki/Anti-aliasing_filter), or other\nsources of [Gaussian-type blur](https://en.wikipedia.org/wiki/Gaussian_blur)"
     ```

### Q048. Capture Sharpening에서 RL Deconvolution 사용 시 아티팩트를 최소화하는 반경/임계값 설정 요령과 설정 변경의 전체 적용 범위는 무엇인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Capture_Sharpening`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Capture_Sharpening"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Capture_Sharpening`
   - 소스 파일: `data/rawpedia/Capture_Sharpening.md` (절: `Is it the definitive sharpening tool?`)
   - URL: [https://rawpedia.rawtherapee.com/capture_sharpening/](https://rawpedia.rawtherapee.com/capture_sharpening/)
   - 바이트 범위: `[1671:1944]` (UTF-8)
   - SHA-256: `94e2007d54ed62bd3a44b35357c00a1109f219efcee641c89e964dd035ca4e13`
   - 원문 스팬 (JSON String Literal):
     ```json
     "- with RL Deconvolution: find an appropriate radius value (through trial\n  and error to avoid halos) and choose a high contrast threshold so that\n  you only enhance the largest details and edges. This will allow you to\n  keep artifacts (common with this tool) to a minimum."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Capture_Sharpening`
   - 소스 파일: `data/rawpedia/Capture_Sharpening.md` (절: `How it works (settings)`)
   - URL: [https://rawpedia.rawtherapee.com/capture_sharpening/](https://rawpedia.rawtherapee.com/capture_sharpening/)
   - 바이트 범위: `[2047:2137]` (UTF-8)
   - SHA-256: `c9c00337c2edc5623718a8f1147dbc8991910e11f764771818b0cfd55a799f40`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Any changes in the settings are applied to the whole image, no matter\nwhat the zoom level,"
     ```

### Q049. Sharpening 도구의 Unsharp Mask 기법은 이미지의 어떤 시각적 특성을 향상시키는 전통적인 방식인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Sharpening`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Sharpening"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Sharpening`
   - 소스 파일: `data/rawpedia/Sharpening.md` (절: `Unsharp Mask`)
   - URL: [https://rawpedia.rawtherapee.com/sharpening/](https://rawpedia.rawtherapee.com/sharpening/)
   - 바이트 범위: `[1020:1211]` (UTF-8)
   - SHA-256: `9fbf9ac7d3d9c4f9c38667396ac7eec18f83c2f97d94901e7d3c6152687a768f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "[Unsharp masking](https://en.wikipedia.org/wiki/Unsharp_mask) (USM) is a\ntechnique used to increase the apparent\n[acutance](https://en.wikipedia.org/wiki/Acutance) (edge contrast) of an\nimage"
     ```

### Q050. Sharpening 도구에서 지나친 USM 샤프닝 시 후광을 억제하는 Halo Control의 동작 방식과 RL Deconvolution의 점 확산 함수(PSF) 기반 역변환 원리는 무엇인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Sharpening`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Sharpening"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Sharpening`
   - 소스 파일: `data/rawpedia/Sharpening.md` (절: `Halo Control`)
   - URL: [https://rawpedia.rawtherapee.com/sharpening/](https://rawpedia.rawtherapee.com/sharpening/)
   - 바이트 범위: `[4349:4573]` (UTF-8)
   - SHA-256: `4967e7e5b518a8aed851714436547dada2d59e543bc6c951e1adea33ac208c63`
   - 원문 스팬 (JSON String Literal):
     ```json
     "\"Halo Control\" is used to avoid halo effects around light objects when\nsharpening too aggressively. When activated, a new slider appears:\n\n- Amount. At 100 it works at maximum, reducing the visual impact of the\n  USM filter."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Sharpening`
   - 소스 파일: `data/rawpedia/Sharpening.md` (절: `RL Deconvolution`)
   - URL: [https://rawpedia.rawtherapee.com/sharpening/](https://rawpedia.rawtherapee.com/sharpening/)
   - 바이트 범위: `[4754:4904]` (UTF-8)
   - SHA-256: `9415b08fb54bae72da039ab3d269322dd1412f925ecd19ed9531a8127e289f9c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "uses the [point spread function](https://en.wikipedia.org/wiki/Point_spread_function) (PSF) to\ndeconvolve (reverse) the effects of Gaussian-like blur."
     ```

### Q051. Noise Reduction 도구에서 휘도 노이즈(Luminance noise)와 색상 노이즈(Chrominance noise)에 대한 시각적 특성과 제거 필요성의 차이는 무엇인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Noise_Reduction`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Noise_Reduction"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Noise_Reduction`
   - 소스 파일: `data/rawpedia/Noise_Reduction.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/noise_reduction/](https://rawpedia.rawtherapee.com/noise_reduction/)
   - 바이트 범위: `[3555:3681]` (UTF-8)
   - SHA-256: `00aef1bf12b141c2b83564e200bc40daf1a9fe1c311c064b8a13f60be13ad7a9`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Chrominance noise is endemic to digital images, it is generally\n    unattractive and something you will always want to remove."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Noise_Reduction`
   - 소스 파일: `data/rawpedia/Noise_Reduction.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/noise_reduction/](https://rawpedia.rawtherapee.com/noise_reduction/)
   - 바이트 범위: `[3686:3857]` (UTF-8)
   - SHA-256: `9aab8751f467e36f8135b02eff19ce49485718e8696ec90866a4778d919e3dd5`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Luminance noise, on the other hand, looks like film grain and can be\n    attractive, so it's not uncommon to want to remove chrominance noise\n    but keep luminance noise."
     ```

### Q052. 노이즈가 심한 고감도(예: ISO 6400) 사진에서 AMaZE 디모자이킹을 적용했을 때 어떤 아티팩트 패턴이 나타날 수 있나요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Noise_Reduction`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Noise_Reduction"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Noise_Reduction`
   - 소스 파일: `data/rawpedia/Noise_Reduction.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/noise_reduction/](https://rawpedia.rawtherapee.com/noise_reduction/)
   - 바이트 범위: `[3973:4025]` (UTF-8)
   - SHA-256: `fa9529db952e3fc2d2e6d7f579bc405355a029294263a58bea23efdf4c259d14`
   - 원문 스팬 (JSON String Literal):
     ```json
     "AMaZE demosaicing leads to small maze-like patterns."
     ```

### Q053. Contrast by Detail Levels 도구의 웨이블릿 분해 레벨 수와 Slider 0(Finest)부터 Slider 5까지의 대략적인 픽셀 반경은 얼마인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Contrast_by_Detail_Levels`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Contrast_by_Detail_Levels"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Contrast_by_Detail_Levels`
   - 소스 파일: `data/rawpedia/Contrast_by_Detail_Levels.md` (절: `Contrast by Detail Levels`)
   - URL: [https://rawpedia.rawtherapee.com/contrast_by_detail_levels/](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/)
   - 바이트 범위: `[167:255]` (UTF-8)
   - SHA-256: `67214f77be141bc7a1c166ca96b1b3d89781d182a51d44beaec5891ffe022e98`
   - 원문 스팬 (JSON String Literal):
     ```json
     "wavelet decomposition to decompose the\nimage into six levels, each adjusted by a slider."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Contrast_by_Detail_Levels`
   - 소스 파일: `data/rawpedia/Contrast_by_Detail_Levels.md` (절: `Contrast by Detail Levels`)
   - URL: [https://rawpedia.rawtherapee.com/contrast_by_detail_levels/](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/)
   - 바이트 범위: `[256:377]` (UTF-8)
   - SHA-256: `40cbf6b5093fa027cc6b81d06ce87bfef84582408ed1424d395a2dd3d80beee2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Slider 0 (Finest) has\na pixel radius of 1, sliders 1 to 5 have a pixel radius of approximately\n2, 4, 8, 16 and 32 pixels."
     ```

### Q054. Contrast by Detail Levels 도구에서 특정 레벨 슬라이더 값을 1.0보다 작게 하거나 크게 할 때 로컬 대비는 각각 어떻게 변하나요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Contrast_by_Detail_Levels`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Contrast_by_Detail_Levels"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Contrast_by_Detail_Levels`
   - 소스 파일: `data/rawpedia/Contrast_by_Detail_Levels.md` (절: `Contrast by Detail Levels`)
   - URL: [https://rawpedia.rawtherapee.com/contrast_by_detail_levels/](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/)
   - 바이트 범위: `[378:455]` (UTF-8)
   - SHA-256: `880bd8f741eae38d5582fdf7002dac7004f8d7402e4de0035efacc02a9e5a308`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Giving a slider a value less than 1.0\ndecreases local contrast at that level,"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Contrast_by_Detail_Levels`
   - 소스 파일: `data/rawpedia/Contrast_by_Detail_Levels.md` (절: `Contrast by Detail Levels`)
   - URL: [https://rawpedia.rawtherapee.com/contrast_by_detail_levels/](https://rawpedia.rawtherapee.com/contrast_by_detail_levels/)
   - 바이트 범위: `[456:565]` (UTF-8)
   - SHA-256: `b587b74db6ab86ef8a4716884a625ce845a1920609d2bf0545f86377fc66ffd1`
   - 원문 스팬 (JSON String Literal):
     ```json
     "while giving it a higher value\nincreases it. Thus you can use it to increase perceived sharpness of an\nimage,"
     ```

### Q055. Edges 도구가 일반적인 Unsharp Mask와 비교할 때 갖는 특징(후광, 노이즈 환경, 색공간)은 무엇인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Edges_and_Microcontrast`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Edges_and_Microcontrast"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Edges_and_Microcontrast`
   - 소스 파일: `data/rawpedia/Edges_and_Microcontrast.md` (절: `General`)
   - URL: [https://rawpedia.rawtherapee.com/edges_and_microcontrast/](https://rawpedia.rawtherapee.com/edges_and_microcontrast/)
   - 바이트 범위: `[161:347]` (UTF-8)
   - SHA-256: `90e4237e7bc791feb25a1e3c8646f7873ea6cf8d7d3a9fe5a6f898876234d316`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Unlike *[Unsharp Mask](sharpening#unsharp_mask)*, *Edges* is\na true sharpening algorithm. It does not introduce halos, it can be used\non noisy images and it works in the Lab color space."
     ```

### Q056. Microcontrast의 정의와 저주파 영역 대비를 다루는 local contrast와의 차이점은 무엇인가요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Edges_and_Microcontrast`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Edges_and_Microcontrast"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Edges_and_Microcontrast`
   - 소스 파일: `data/rawpedia/Edges_and_Microcontrast.md` (절: `Microcontrast`)
   - URL: [https://rawpedia.rawtherapee.com/edges_and_microcontrast/](https://rawpedia.rawtherapee.com/edges_and_microcontrast/)
   - 바이트 범위: `[2082:2341]` (UTF-8)
   - SHA-256: `d3d30fa84b18759e86816ff73d7ef6f8635ff0aeb5e60269c64bd80321687dbf`
   - 원문 스팬 (JSON String Literal):
     ```json
     "\"Microcontrast\" can be defined as contrast on a pixel\nlevel[1](https://web.archive.org/web/20110625093654/http://www.rawness.es/sharpening/?lang=en#comment-306),\nas opposed to \"local contrast\" which pertains to contrast between larger\n(lower frequency) areas."
     ```

### Q057. Impulse Noise Reduction 도구는 어떤 형태의 노이즈를 제거하기 위해 사용되며 파이프라인의 어느 시점에서 작동하나요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Impulse_Noise_Reduction`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Impulse_Noise_Reduction"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Impulse_Noise_Reduction`
   - 소스 파일: `data/rawpedia/Impulse_Noise_Reduction.md` (절: `Impulse Noise Reduction`)
   - URL: [https://rawpedia.rawtherapee.com/impulse_noise_reduction/](https://rawpedia.rawtherapee.com/impulse_noise_reduction/)
   - 바이트 범위: `[239:310]` (UTF-8)
   - SHA-256: `198f6c6d4ab1776a73317af23ad89b69c20610cfa81c5b02b45576f2e61126d2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "salt and pepper sprinkled over a photo. This is done after\ndemosaicing."
     ```

### Q058. Defringe 도구가 다루는 퍼플 프린지(Purple fringes)는 색수차의 어떤 형태이며 주로 어떤 가장자리에서 발생하나요?

- **분류**: 카테고리 `sharpening_noise` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Defringe`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Defringe"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Defringe`
   - 소스 파일: `data/rawpedia/Defringe.md` (절: `Defringe`)
   - URL: [https://rawpedia.rawtherapee.com/defringe/](https://rawpedia.rawtherapee.com/defringe/)
   - 바이트 범위: `[183:310]` (UTF-8)
   - SHA-256: `9e7729cdf915fc75c4c0851a8f6c36fbd276f128e578218df3798b16a8f98988`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Purple fringes are a form\nof axial (or longitudinal) chromatic aberration, and appear along dark\nedges adjacent to bright areas"
     ```

### Q059. RawPedia 설명 기준으로 Local adjustments의 RT-spots는 어떤 소프트웨어들의 U-Point 개념과 유사한 원리로 동작하나요?

- **분류**: 카테고리 `mask_local` · 의도 `concept` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:local_adjustments`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:local_adjustments"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:local_adjustments`
   - 소스 파일: `data/rawpedia/local_adjustments.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/local_adjustments/](https://rawpedia.rawtherapee.com/local_adjustments/)
   - 바이트 범위: `[244:414]` (UTF-8)
   - SHA-256: `7660be42ad382756c80c21bcd7d89bc625709ae4ba80c6dd7593e26ba31e3bfb`
   - 원문 스팬 (JSON String Literal):
     ```json
     "RT-spots, which are similar in\nprinciple to the U-Point concept originally used in Nikon Capture NX2\nand subsequently in the Nik Collection, DxO PhotoLab and Capture NXD."
     ```

### Q060. RawTherapee Local adjustments에서 RT-spot을 구성하는 요소(중심점 C 및 4개 경계점 TBLR)와 이를 기반으로 형성되는 3가지 그래디언트(Dissymetry, Transition, Color)의 동작 방식은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:local_adjustments`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:local_adjustments"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:local_adjustments`
   - 소스 파일: `data/rawpedia/local_adjustments.md` (절: `Overview of the RT-spot area`)
   - URL: [https://rawpedia.rawtherapee.com/local_adjustments/](https://rawpedia.rawtherapee.com/local_adjustments/)
   - 바이트 범위: `[238800:239143]` (UTF-8)
   - SHA-256: `4a38db956d663439de5ecd3242d5c0fa8e0ac18c44b13f65eb3ab26f820402b1`
   - 원문 스팬 (JSON String Literal):
     ```json
     "When the user selects an RT-spot, the image on the screen shows:\n\n- A center C consisting of an adjustable circle whose size (diameter)\n  and position can be varied using the mouse or cursors.\n- Four horizontal and vertical delimiting points T (top), B (bottom), L\n  (left), R (right) whose positions can be varied with the mouse or\n  cursors."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:local_adjustments`
   - 소스 파일: `data/rawpedia/local_adjustments.md` (절: `The 3 types of gradient`)
   - URL: [https://rawpedia.rawtherapee.com/local_adjustments/](https://rawpedia.rawtherapee.com/local_adjustments/)
   - 바이트 범위: `[240092:241171]` (UTF-8)
   - SHA-256: `bdd9384f5bf304046e2666ef9516c8634a5aec86dead56536538ba9b9ec125b4`
   - 원문 스팬 (JSON String Literal):
     ```json
     "### The 3 types of gradient\n\nThe RT-spot object is based on 3 types of gradient:\n\n- Dissymetry: a natural gradient inside the area bounded by the RT-spot\n  can be created by placing the four points TBLR dissymetrically around\n  the center C.\n- Transition: this is an adjustable gradient that operates from the\n  center C to the periphery of the spot.\n- Color (deltaE): the Scope slider adjusts the extent of any applied\n  adjustments as a function of deltaE (ΔE). Lower values limit the color\n  deviations (L, C, H) that will be taken into account whereas higher\n  values (Scope = 80 and above) will allow the tool to act on a wider\n  range of values. When the Scope value reaches 100 there is no longer\n  any differentiation and all colors will be adjusted equally.\n\nThe three types of gradient described can be used in conjunction with\nany of the tools (including Contrast By Detail Levels, Retinex, Tone\nMapping, etc.), many of which also have their own graduated filter\nfunction. In all cases the center C of the RT-spot is the reference\npoint for the start of the gradient."
     ```

### Q061. Local Lab Controls에서 컨트롤 포인트 조작 편의를 위해 도입된 GUI 인터페이스의 특징과 긴 메뉴 회피 설계는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `concept` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Local_Lab_Controls`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Local_Lab_Controls"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Local_Lab_Controls`
   - 소스 파일: `data/rawpedia/Local_Lab_Controls.md` (절: `What kind of local control?`)
   - URL: [https://rawpedia.rawtherapee.com/local_lab_controls/](https://rawpedia.rawtherapee.com/local_lab_controls/)
   - 바이트 범위: `[1760:1877]` (UTF-8)
   - SHA-256: `d44a67e5047a42f3c4962d9eeef1eb5fa1fafe9f150285436c39f19a25b9ca33`
   - 원문 스팬 (JSON String Literal):
     ```json
     "control points, as done in Nik Software.\n\nHowever, those two aspects don’t harm everyday use, nor code\nportability."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Local_Lab_Controls`
   - 소스 파일: `data/rawpedia/Local_Lab_Controls.md` (절: `What kind of local control?`)
   - URL: [https://rawpedia.rawtherapee.com/local_lab_controls/](https://rawpedia.rawtherapee.com/local_lab_controls/)
   - 바이트 범위: `[1879:2020]` (UTF-8)
   - SHA-256: `390d2a172821a0a376665231cc0f40077b32979d1ffb78f7672e0d222fa24f18`
   - 원문 스팬 (JSON String Literal):
     ```json
     "In order to improve manipulation and avoid long menus on screen, I added\na GUI interface which is similar to the one used in the Wavelet tab,"
     ```

### Q062. Local Lab Controls에서 Scope 슬라이더 조절 시 각 사분면(quadrant)에서 tint 및 deltaE(색차) 기반으로 적용량을 계산하는 알고리즘 원리와, 슬라이더 값을 증감할 때의 선택 영역 변화는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Local_Lab_Controls`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Local_Lab_Controls"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Local_Lab_Controls`
   - 소스 파일: `data/rawpedia/Local_Lab_Controls.md` (절: `Tint, chroma, luminance references and the algorithm principle in “normal” mode`)
   - URL: [https://rawpedia.rawtherapee.com/local_lab_controls/](https://rawpedia.rawtherapee.com/local_lab_controls/)
   - 바이트 범위: `[15069:15663]` (UTF-8)
   - SHA-256: `f45d6b2df9b8ec407652c79816ce8e0ff16fa64c19ba47690ffc9e1fb427e9d4`
   - 원문 스팬 (JSON String Literal):
     ```json
     "- For each quadrant, depending on the the value of the “Scope” slider,\n  the algorithm does:\n\n1.  take into account the tint difference between the zone centre and\n    the affected pixel;\n2.  through a complex algorithm based on the deltaE notion (perceived\n    difference between two colors, taking tint, chroma and luminance\n    into account), decrease the amount of applied effect as a function\n    of the difference between the central zone and the affected pixel;\n3.  follow either a linear or a parabolic law to adjust the amount of\n    applied effect, based on the specific the case."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Local_Lab_Controls`
   - 소스 파일: `data/rawpedia/Local_Lab_Controls.md` (절: `Tint, chroma, luminance references and the algorithm principle in “normal” mode`)
   - URL: [https://rawpedia.rawtherapee.com/local_lab_controls/](https://rawpedia.rawtherapee.com/local_lab_controls/)
   - 바이트 범위: `[16356:16666]` (UTF-8)
   - SHA-256: `60ebb5f54acae2c68899963f7c0b7bb14d961e9c8f6aa061da8f9e2251c16eae`
   - 원문 스팬 (JSON String Literal):
     ```json
     "- By increasing the value of “Scope”, progressively more of the selected\n  area is taken into account, whatever the tint, chroma and luminance;\n- Conversely, by decreasing the “Scope” value the effect will get\n  limited to the pixels which are more similar (in terms of deltaE) to\n  the reference zone."
     ```

### Q063. Spot Removal 도구에서 새로운 스팟을 추가할 때 마우스 조작 방법(Ctrl-click 및 드래그)은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Spot_Removal`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Spot_Removal"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Spot_Removal`
   - 소스 파일: `data/rawpedia/Spot_Removal.md` (절: `Adding spots`)
   - URL: [https://rawpedia.rawtherapee.com/spot_removal/](https://rawpedia.rawtherapee.com/spot_removal/)
   - 바이트 범위: `[613:835]` (UTF-8)
   - SHA-256: `92a92cc7eacba320aa18ba13904bed61200fe92cc47259f9ed0d5add0b6a470d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Ctrl-click on the location that you want to mask (\"destination\", solid\nlines) and drag the mouse to set the replacement location (\"source\",\ndotted lines). The area under the source will replace the area of the\ndestination."
     ```

### Q064. Spot Removal 도구에서 기존 스팟을 제거하는 마우스 조작 방법과 스팟 편집 모드를 토글하는 절차는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Spot_Removal`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Spot_Removal"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Spot_Removal`
   - 소스 파일: `data/rawpedia/Spot_Removal.md` (절: `Removing spots`)
   - URL: [https://rawpedia.rawtherapee.com/spot_removal/](https://rawpedia.rawtherapee.com/spot_removal/)
   - 바이트 범위: `[1267:1336]` (UTF-8)
   - SHA-256: `9e5627926662ac7258fc82c4070f1f08484eb763e9199f4c191ccf2a8bd94f31`
   - 원문 스팬 (JSON String Literal):
     ```json
     "### Removing spots\n\nRight click on any part of the spot to remove it."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Spot_Removal`
   - 소스 파일: `data/rawpedia/Spot_Removal.md` (절: `Activate spot editing mode`)
   - URL: [https://rawpedia.rawtherapee.com/spot_removal/](https://rawpedia.rawtherapee.com/spot_removal/)
   - 바이트 범위: `[392:593]` (UTF-8)
   - SHA-256: `336445f0dfeb37597d6e9c1bc6f912bbd5d69082a69fa97ca612a568f4808dec`
   - 원문 스팬 (JSON String Literal):
     ```json
     "### Activate spot editing mode\n\nIn order to add, remove or change spots, the spot editing mode needs to\nbe active. Toggle this mode using the\n![edit-point.png>](edit-point.png \"edit-point.png\") button."
     ```

### Q065. Graduated Filter 도구는 실제 어떤 사진 광학 필터를 모방하며 주로 어떤 상황에 사용되나요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Graduated_Filter`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Graduated_Filter"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Graduated_Filter`
   - 소스 파일: `data/rawpedia/Graduated_Filter.md` (절: `Graduated Filter`)
   - URL: [https://rawpedia.rawtherapee.com/graduated_filter/](https://rawpedia.rawtherapee.com/graduated_filter/)
   - 바이트 범위: `[117:289]` (UTF-8)
   - SHA-256: `a875a94a87cfd6f9158b79cf4fac1c73f52a49e389ca48e17d2467d589bb2467`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The graduated filter tool simulates a real neutral density graduated\nfilter. These can be used used in for example landscape photography to\nlimit the brightness of the sky."
     ```

### Q066. Graduated Filter 도구의 적용 강도(Strength) 단위는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Graduated_Filter`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Graduated_Filter"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Graduated_Filter`
   - 소스 파일: `data/rawpedia/Graduated_Filter.md` (절: `Strength`)
   - URL: [https://rawpedia.rawtherapee.com/graduated_filter/](https://rawpedia.rawtherapee.com/graduated_filter/)
   - 바이트 범위: `[365:402]` (UTF-8)
   - SHA-256: `6d56b917067d06a6cb3a50d121b2afb0bd408b0a4c6296ef414100ad6a167ff7`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The strength of the filter, in stops."
     ```

### Q067. Vignetting Filter 도구에서 크롭(Crop)이 적용되었을 때 비네팅 효과는 어디를 기준으로 배치되나요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Vignetting_Filter`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Vignetting_Filter"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Vignetting_Filter`
   - 소스 파일: `data/rawpedia/Vignetting_Filter.md` (절: `Vignetting Filter`)
   - URL: [https://rawpedia.rawtherapee.com/vignetting_filter/](https://rawpedia.rawtherapee.com/vignetting_filter/)
   - 바이트 범위: `[196:271]` (UTF-8)
   - SHA-256: `fafde3d31cd52725bb5ce744d39e1e32295d381c069b690e49996090a595128a`
   - 원문 스팬 (JSON String Literal):
     ```json
     "This vignetting filter is placed relative to the crop, if\ncropping is used."
     ```

### Q068. Vignetting Filter에서 예술적 비네팅과 렌즈 광량 저하(Flat-Field/Raw Tab) 보정의 차이점 및 원형/직사각형 모양 제어 방식은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Vignetting_Filter`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Vignetting_Filter"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Vignetting_Filter`
   - 소스 파일: `data/rawpedia/Vignetting_Filter.md` (절: `Vignetting Filter`)
   - URL: [https://rawpedia.rawtherapee.com/vignetting_filter/](https://rawpedia.rawtherapee.com/vignetting_filter/)
   - 바이트 범위: `[273:593]` (UTF-8)
   - SHA-256: `e8d697f84cfce705465ee8dd778755b52879ddaa0661f8cba3cca7b0687b0997`
   - 원문 스팬 (JSON String Literal):
     ```json
     "For correcting vignetting caused by the lens light fall-off (as opposed\nto this filter which is not for correction but for artistic effect), use\nthe [Vignetting Correction](/lens--geometry/#vignetting-correction) filter in\nthe Transform tab, in the Lens/Geometry tool. Even better, use the\n[Flat Field](flat_field) tool."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Vignetting_Filter`
   - 소스 파일: `data/rawpedia/Vignetting_Filter.md` (절: `Roundness`)
   - URL: [https://rawpedia.rawtherapee.com/vignetting_filter/](https://rawpedia.rawtherapee.com/vignetting_filter/)
   - 바이트 범위: `[1229:1537]` (UTF-8)
   - SHA-256: `97f13a10d1b004efc5ba2922edcf44a4d99a52ecf5d6dddc7c2504ad66a5509e`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The roundness slider controls the geometry of the filter. At 0 the shape\nis rectangular (with rounded corners), at 50 it is a fitted ellipse, and\nat 100 it’s circular. Note that if your image is square the fitted\nellipse will of course be a circle, so the shape will then not change in\nthe range 50 to 100."
     ```

### Q069. Preview Modes에서 Focus mask의 미리보기 목적은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Preview_Modes`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Preview_Modes"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Preview_Modes`
   - 소스 파일: `data/rawpedia/Preview_Modes.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/preview_modes/](https://rawpedia.rawtherapee.com/preview_modes/)
   - 바이트 범위: `[495:538]` (UTF-8)
   - SHA-256: `31f8b270c615cb31ad29604d0ffb8713b7ab2aacc6548be5757111de85645608`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Focus mask, to see which areas are in focus"
     ```

### Q070. RawTherapee 설명 기준 튜토리얼(rocks.md)에서 Selective Editing 시 몇 개의 RT-spots를 사용하며 첫 번째 spot에는 어떤 도구(GHS 등)가 적용되었나요?

- **분류**: 카테고리 `mask_local` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Tutorials/game_changer/rocks`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Tutorials/game_changer/rocks"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Tutorials/game_changer/rocks`
   - 소스 파일: `data/rawpedia/Tutorials/game_changer/rocks.md` (절: `Selective Editing - 5 RT-spots`)
   - URL: [https://rawpedia.rawtherapee.com/tutorials/game_changer/rocks/](https://rawpedia.rawtherapee.com/tutorials/game_changer/rocks/)
   - 바이트 범위: `[3825:3855]` (UTF-8)
   - SHA-256: `c396c16dc3fa6bb1c674265e32f31ca62c69a0318d4d384c840cef22b0368568`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Selective Editing - 5 RT-spots"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Tutorials/game_changer/rocks`
   - 소스 파일: `data/rawpedia/Tutorials/game_changer/rocks.md` (절: `First spot : Generalized hyperbolic stretch (GHS)`)
   - URL: [https://rawpedia.rawtherapee.com/tutorials/game_changer/rocks/](https://rawpedia.rawtherapee.com/tutorials/game_changer/rocks/)
   - 바이트 범위: `[3857:3910]` (UTF-8)
   - SHA-256: `63a1d2c0f3452b9aecb39e55474293635d0510a92fc369c5412c7ee4a98217ad`
   - 원문 스팬 (JSON String Literal):
     ```json
     "### First spot : Generalized hyperbolic stretch (GHS)"
     ```

### Q071. RawTherapee에서 편집 중인 사이드카 처리 프로필(PP3)이 디스크에 실제 파일로 기록되는 시점이나 트리거 조건들은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Sidecar_Files_-_Processing_Profiles`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Sidecar_Files_-_Processing_Profiles"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Sidecar_Files_-_Processing_Profiles`
   - 소스 파일: `data/rawpedia/Sidecar_Files_-_Processing_Profiles.md` (절: `Saving`)
   - URL: [https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/](https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/)
   - 바이트 범위: `[3376:4149]` (UTF-8)
   - SHA-256: `858b3663180e8d2b75a45b288b4abb903703a126436cd6208c766fd1884b32c0`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The processing profile is written to disk:\n\n- When you apply a processing profile manually or using a dynamic\n  profile.\n- When you close the current image (the Editor tab) if using\n  [Multiple Editor Tabs Mode](the_image_editor_tab#editor_tab_modes)\n  (METM).\n- When you close the current image by opening a different image if using\n  [Single Editor Tab Mode](the_image_editor_tab#editor_tab_modes) (SETM).\n- When you close the current image by closing RawTherapee.\n- When you manually save the processing profile using the [Processing Profile Selector](the_image_editor_tab#processing_profile_selector)\n  panel in the Editor tab.\n- When you use the \"force saving current settings to the processing\n  profile\" [keyboard shortcut](keyboard_shortcuts) from the\n  Editor tab."
     ```

### Q072. RawTherapee에서 부분 처리 프로필(partial profile)을 적용할 때 Fill 모드와 Preserve 모드의 동작 차이 및 누락된 파라미터 처리 방식은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Sidecar_Files_-_Processing_Profiles`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Sidecar_Files_-_Processing_Profiles"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Sidecar_Files_-_Processing_Profiles`
   - 소스 파일: `data/rawpedia/Sidecar_Files_-_Processing_Profiles.md` (절: `Partial Processing Profiles and Fill Modes`)
   - URL: [https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/](https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/)
   - 바이트 범위: `[7425:7878]` (UTF-8)
   - SHA-256: `83bdc58612bed85cb43e57e7f60f2053d82808db57f4c4a82596e589d7169ca7`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The processing profile fill mode allows you to decide what happens when\nyou apply (load or paste) a partial processing profile.\n\n- [image:Profile-filled.png](/images/profile-filled.png) \"Fill\"\n  mode takes missing values from RawTherapee's hard-coded defaults. For\n  instance, if you apply a partial profile containing only sharpening\n  settings, all of the remaining tools will be set to their default\n  parameters, overwriting any edits you have made."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Sidecar_Files_-_Processing_Profiles`
   - 소스 파일: `data/rawpedia/Sidecar_Files_-_Processing_Profiles.md` (절: `Partial Processing Profiles and Fill Modes`)
   - URL: [https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/](https://rawpedia.rawtherapee.com/sidecar_files_-_processing_profiles/)
   - 바이트 범위: `[7940:8066]` (UTF-8)
   - SHA-256: `80f97706910718b41fab91a79d3f9a0bfadc19ec935325e9b105739bc1749da8`
   - 원문 스팬 (JSON String Literal):
     ```json
     "\"Preserve\" mode applies only those parameters that are available in\n  the partial profile and leaves missing values unchanged."
     ```

### Q073. RawTherapee에서 에디터 탭의 즉시 저장(Save immediately)을 실행했을 때 에디터의 반응성에 미치는 영향과 큐(Queue) 사용을 권장하는 이유는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Saving_Images`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Saving_Images"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Saving_Images`
   - 소스 파일: `data/rawpedia/Saving_Images.md` (절: `Save Immediately`)
   - URL: [https://rawpedia.rawtherapee.com/saving_images/](https://rawpedia.rawtherapee.com/saving_images/)
   - 바이트 범위: `[1329:1723]` (UTF-8)
   - SHA-256: `75e5ebf47e11e3b4d373610eddc08c6395ce9753e3ed0e98c1dcfdee771f5dff`
   - 원문 스팬 (JSON String Literal):
     ```json
     "If you choose to \"*Save\nimmediately*\", RawTherapee will be busy saving your photo as soon as you\nclick \"*OK*\", so it will be less responsive to any adjustments you might\ntry doing while it's busy saving, and it will also take longer to open\nother images as long as it's busy saving this one. For this reason it is\nrecommended that you use the queue if you want to tweak other photos\nright away."
     ```

### Q074. RawTherapee에서 동일한 원본 파일로 여러 버전을 저장할 때 파일명 덮어쓰기 충돌을 방지하는 옵션과 Save 창을 통해 큐에 보낼 때 개별 설정 장점은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Saving_Images`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Saving_Images"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Saving_Images`
   - 소스 파일: `data/rawpedia/Saving_Images.md` (절: `Put to the Head / Tail of the Processing Queue`)
   - URL: [https://rawpedia.rawtherapee.com/saving_images/](https://rawpedia.rawtherapee.com/saving_images/)
   - 바이트 범위: `[2674:2950]` (UTF-8)
   - SHA-256: `402964504a72ec51b3070837ddc2061cd8d99b85a26f268602f092251522d521`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The benefit of putting it to the queue using the \"*Save*\" window is that\nyou can individually change the file format, name and destination of\neach image, whereas putting images to the queue without using the\n\"*Save*\" window will use the settings from the\n\"[Queue](queue)\" tab."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Saving_Images`
   - 소스 파일: `data/rawpedia/Saving_Images.md` (절: `Naming`)
   - URL: [https://rawpedia.rawtherapee.com/saving_images/](https://rawpedia.rawtherapee.com/saving_images/)
   - 바이트 범위: `[3098:3448]` (UTF-8)
   - SHA-256: `e142f89bf13d342c5584f4c2a5fa947dfe17a204da06517ac1ba28dacfd8eb9d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "There is an option in the \"*Save current image*\" window: \"*Automatically\nadd a suffix if the file already exists*\". When checked, you can make\ndifferent versions of one raw, which will be saved as `photo_1000.jpg`,\n`photo_1000-1.jpg`, `photo_1000-2.jpg`, etc. The same applies when you\nsend different versions of the same image to the\n[Queue](queue)."
     ```

### Q075. RawTherapee의 Queue 설정 중 Use template에서 원본 파일명(%f), 상위 폴더(%d1), 절대 경로(%p1) 및 사진 등급(%r) 서식 문자의 치환 규칙은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Queue`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Queue"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Queue`
   - 소스 파일: `data/rawpedia/Queue.md` (절: `Queue Settings`)
   - URL: [https://rawpedia.rawtherapee.com/queue/](https://rawpedia.rawtherapee.com/queue/)
   - 바이트 범위: `[3482:4362]` (UTF-8)
   - SHA-256: `f7de800bc048e08d3aa190c67a78f91816d0803413a6569b1ffa94473b332886`
   - 원문 스팬 (JSON String Literal):
     ```json
     "<b>`/home/tom/photos/2010-10-31/photo1.raw`</b>\n`the meaning of the formatting strings follows:`\n<b>`%d4`</b>` = `<i>`home`</i>\n<b>`%d3`</b>` = `<i>`tom`</i>\n<b>`%d2`</b>` = `<i>`photos`</i>\n<b>`%d1`</b>` = `<i>`2010-10-31`</i>\n<b>`%f`</b>` = `<i>`photo1`</i>\n<b>`%p1`</b>` = `<i>`/home/tom/photos/2010-10-31/`</i>\n<b>`%p2`</b>` = `<i>`/home/tom/photos/`</i>\n<b>`%p3`</b>` = `<i>`/home/tom/`</i>\n<b>`%p4`</b>` = `<i>`/home/`</i>\n\n<b>`%r`</b>` will be replaced by the photo's rank. If the photo is unranked, '`<i>`0`</i>`' is used. If the photo is in the trash, '`<i>`x`</i>`' is used.`\n\n<b>`%s1`</b>`, ..., `<b>`%s9`</b>` will be replaced by the photo's initial position in the queue at the time the queue is started. The number specifies the padding, e.g. `<b>`%s3`</b>` results in '`<i>`001`</i>`'.`"
     ```

### Q076. RawTherapee에서 큐 탭의 전역 설정 대신 Save 창의 설정을 강제 적용하는 조건(Force saving options)과 큐의 지속성(Persistence) 동작은 어떠한가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Queue`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Queue"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Queue`
   - 소스 파일: `data/rawpedia/Queue.md` (절: `Introduction`)
   - URL: [https://rawpedia.rawtherapee.com/queue/](https://rawpedia.rawtherapee.com/queue/)
   - 바이트 범위: `[1100:1247]` (UTF-8)
   - SHA-256: `270579cb15adfdb06e094513457371823450aa3369d501880cd53a5b02ed26e5`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The queue is persistent - you can exit RawTherapee and restart it later;\nthe queued images will still be there. The queue can even survive a\ncrash."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Queue`
   - 소스 파일: `data/rawpedia/Queue.md` (절: `Queue Settings`)
   - URL: [https://rawpedia.rawtherapee.com/queue/](https://rawpedia.rawtherapee.com/queue/)
   - 바이트 범위: `[2140:2641]` (UTF-8)
   - SHA-256: `b55192f739a87edfb3007b2c1e44e56842b7dc2f97dda2ca9e957c471a64e607`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The Queue has several settings, such as the output file format and\ndestination. These settings take effect in all cases except when you use\nthe \"Save current image\" button\n![<File:Save.png>](/images/Save.png \"File:Save.png\"), select \"Put to the\nhead/tail of the processing queue\" and enable the \"Force saving options\"\ncheckbox. In this case, the settings seen in the \"Save\" window will be\nused, and the ones from the Queue tab ignored. In all other cases, the\nsettings from the Queue tab will be used."
     ```

### Q077. 범용으로 재사용 가능한 처리 프로필을 만들 때 필요한 파라미터만 부분 저장(Ctrl+Save)하는 방법과, 다양한 사진 간 호환성을 위해 노출값 대신 Auto Levels 사용 및 불필요한 설정(WB, 노이즈 감소 등) 배제를 권장하는 이유는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:Creating_processing_profiles_for_general_use`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Creating_processing_profiles_for_general_use"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Creating_processing_profiles_for_general_use`
   - 소스 파일: `data/rawpedia/Creating_processing_profiles_for_general_use.md` (절: `Partial Processing Profiles`)
   - URL: [https://rawpedia.rawtherapee.com/creating_processing_profiles_for_general_use/](https://rawpedia.rawtherapee.com/creating_processing_profiles_for_general_use/)
   - 바이트 범위: `[3157:3560]` (UTF-8)
   - SHA-256: `8c3235afe20ee86a751a5abbf1f58746276955f01fd2a95b6e8213460c3e06bf`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Sometimes, you will want to save only a subset of the parameters\navailable, e.g. to avoid storing geometric parameters like rotate, crop\nand resize. In this case, hold the *Control* key while clicking on the\n*Save* button. When you select the output file name and click *Save*, a\nwindow will let you choose which parameters to select. You can then\nshare these profiles with your friends or in our forum."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:Creating_processing_profiles_for_general_use`
   - 소스 파일: `data/rawpedia/Creating_processing_profiles_for_general_use.md` (절: `Partial Processing Profiles`)
   - URL: [https://rawpedia.rawtherapee.com/creating_processing_profiles_for_general_use/](https://rawpedia.rawtherapee.com/creating_processing_profiles_for_general_use/)
   - 바이트 범위: `[3562:5048]` (UTF-8)
   - SHA-256: `9847d08eb0744ec25014eb88deb912d6de9a348af03ae56139589fb17a20d7c5`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Remember that in order for a profile to be universally applicable to all\nphotos of the same scene and situation (baby portrait photos in this\nexample), you need to think of all the variations in all of the baby\nportrait photos you might want to apply it to. Remember that exposure\nwill vary between shots, even if you shot the baby in a studio, as the\nlittle one is likely to be crawling around, and even more so if you\nupload your profile on the internet for other baby photographers with\ndifferent cameras and different lighting gear to use, so instead of\nsetting a specific exposure, such as +0.60, you should rather turn on\n*Auto Levels*. This applies to all other settings - remember to set just\nthe bare minimum number of options to achieve the effect you want. Leave\nthe rest untouched, as it is very likely that if you had set those other\noptions, they will not apply well to other photos. If your processing\nprofile is meant to make baby face photos look soft and cuddly by a\nclever mixture of highlight recovery, auto exposure, Lab and RGB tone\ncurves, then don't enable noise reduction (as photos might be shot at\ndifferent ISO values), don't set custom white balance (as light may have\nchanged between shots), don’t rotate the photo, and so forth. All these\nsuperfluous parameters are likely to change between photos and not\ninfluence your soft baby look in any way, so turning them on will just\nlitter your profile. Double-check these things before sharing your\nprofiles."
     ```

### Q078. RawTherapee File Browser의 일괄 조정(Sync) 도구 패널에서 Set 모드와 Add 모드의 차이점(파라미터 교체 vs 기존 값 누적 가산)은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:batch_adjustments_-_sync`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:batch_adjustments_-_sync"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:batch_adjustments_-_sync`
   - 소스 파일: `data/rawpedia/batch_adjustments_-_sync.md` (절: `Sync`)
   - URL: [https://rawpedia.rawtherapee.com/batch_adjustments_-_sync/](https://rawpedia.rawtherapee.com/batch_adjustments_-_sync/)
   - 바이트 범위: `[3171:3650]` (UTF-8)
   - SHA-256: `69dd01156c7a4bfff14cfdff778ceea3ad1759e9e48de42bba9c5e8a33a092ee`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Your tweaks can either replace the existing ones (\"Set\"\nmode), or be added to them (\"Add\" mode). For example if you select two\nphotos, one of which has previously been tweaked with +1EV Exposure\nCompensation and one which has not, and you set Exposure Compensation to\n+0.6EV, then the previously-tweaked photo would end up having +1.6EV\nExposure Compensation in \"Add\" mode and just +0.6EV in \"Set\" mode. The\nphoto which was not previously tweaked would have +0.6EV in both modes."
     ```

### Q079. RawTherapee의 Resize(크기 조정) 도구는 파이프라인에서 언제 실행되며, 다운스케일링 시 디테일 손실을 보완하기 위해 제공되는 구성요소는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `rawpedia` (`rawpedia:Resize`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:Resize"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:Resize`
   - 소스 파일: `data/rawpedia/Resize.md` (절: `Resize`)
   - URL: [https://rawpedia.rawtherapee.com/resize/](https://rawpedia.rawtherapee.com/resize/)
   - 바이트 범위: `[213:508]` (UTF-8)
   - SHA-256: `b581d5b19974f525e9558e8d510610024a929ea93527c067dcb1cf3c14591090`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Resizing is one of the last things to happen when saving an image - this\ntool runs after most other tools and transformations. As downscaling an\nimage involves a certain loss of detail, this tool includes a\n\"Post-Resize Sharpening\" component which you can use to make the\ndownscaled image crisp."
     ```

### Q080. RawTherapee에서 config 폴더와 cache 폴더의 주요 역할 차이와, 용량 확보를 위해 캐시 내 images 서브폴더를 삭제했을 때 설정 유지 여부는 어떠한가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `rawpedia` (`rawpedia:file_paths`) · 제품 범위: `rawtherapee_reference`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["rawpedia:file_paths"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `rawpedia:file_paths`
   - 소스 파일: `data/rawpedia/file_paths.md` (절: `Config`)
   - URL: [https://rawpedia.rawtherapee.com/file_paths/](https://rawpedia.rawtherapee.com/file_paths/)
   - 바이트 범위: `[1223:2142]` (UTF-8)
   - SHA-256: `d7eac7803533df9464e74b6a14ef89940cc296565d9951369bbc5149e5798725`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The RawTherapee config folder contains:\n\n- the \"options\" file, which contains all of your settings from\n  [Preferences](preferences),\n- the \"batch\" folder, which stores temporary [processing profiles](sidecar_files_-_processing_profiles) of the\n  photos you sent to the [Queue](queue),\n- the user-editable\n  [camconst.json](adding_support_for_new_raw_formats) file,\n  where you can define details of how a specific raw format is to be\n  treated (this overrides the values from the system camconst.json\n  file),\n- the [dynamic profile](dynamic_processing_profiles) rules,\n- and the \"profiles\" folder where you can save your custom [processing profiles](sidecar_files_-_processing_profiles) to if you\n  want them to appear in RawTherapee's drop-down list.\n\nYou could include this folder in your backups so that you can regain all\nof your settings and custom processing profiles if you install\nRawTherapee on a new system."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `rawpedia:file_paths`
   - 소스 파일: `data/rawpedia/file_paths.md` (절: `Cache`)
   - URL: [https://rawpedia.rawtherapee.com/file_paths/](https://rawpedia.rawtherapee.com/file_paths/)
   - 바이트 범위: `[3089:3624]` (UTF-8)
   - SHA-256: `e56c86cbb40c0bd26d77b6bd3f838fce3123b479bde2e77e63c7a815624b83c5`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The RawTherapee cache folder contains sets of cached items, where each\nset consists of:\n\n- a thumbnail,\n- metadata,\n- a sidecar file,\n- and optionally an embedded profile.\n\nBy default, RawTherapee keeps up to 20 000 cached sets. Keep an eye on\nthe \"cache\" folder as over time it may grow considerably in size! This\nis mostly due to the cached thumbnails which are stored in the \"images\"\nsub-folder. Deleting the \"images\" sub-folder is safe, you will not lose\nany image settings, RawTherapee will just have to regenerate the\nthumbnails."
     ```

### Q081. GitHub Discussion #412에 정리된 Windows 환경 ART 빌드 절차에서 MSYS2 환경 업데이트 및 패키지 설치 후 VS Code에서 설정해야 하는 CMake Kit과 Launch Target은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:412`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion:D_kwDONWPV1M4Ai6_I"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion:D_kwDONWPV1M4Ai6_I`
   - 소스 파일: `data/issues/snapshots/discussions/412.json` (절: `/body`)
   - URL: [https://github.com/orgs/artraweditor/discussions/412](https://github.com/orgs/artraweditor/discussions/412)
   - 바이트 범위: `[187:326]` (UTF-8)
   - SHA-256: `2205058287c35d2624f127a717e46f48a96b7e42b30e91c75cd72ad0a23b348d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "- Install [MSYS2](https://www.msys2.org) and accept defaults\r\n  - When the install finishes, in the console that opens type:\r\n`pacman -Syu`"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion:D_kwDONWPV1M4Ai6_I`
   - 소스 파일: `data/issues/snapshots/discussions/412.json` (절: `/body`)
   - URL: [https://github.com/orgs/artraweditor/discussions/412](https://github.com/orgs/artraweditor/discussions/412)
   - 바이트 범위: `[1536:1906]` (UTF-8)
   - SHA-256: `86aa5dda9eebcd4dd5d59084aa514e73dc441b5bab5f15e8edfdb7dda331fb11`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Open the command palette (Ctrl+Shift+P) and choose `CMake: Set Launch/Debug Target`. First you'll be prompted to select a kit. Choose `CC xx.x.x x86_64-w64-mingw32 (mingw64)`, where xx.x.x is the version number of the compiler you have installed. Wait until VS is done configuring the project, then you will be prompted to choose a launch target. Choose `art (Install)`."
     ```

### Q082. GitHub Discussion #420에서 Flatpak 기반 PhotoGIMP를 ART의 외부 편집기로 연동할 때 래퍼 셸 스크립트 작성 시 파일 인수를 어떻게 전달해야 하나요?

- **분류**: 카테고리 `settings_workflow` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:420`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion:D_kwDONWPV1M4AjNbf", "discussion-comment:DC_kwDONWPV1M4A6DN4"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion:D_kwDONWPV1M4AjNbf`
   - 소스 파일: `data/issues/snapshots/discussions/420.json` (절: `/body`)
   - URL: [https://github.com/orgs/artraweditor/discussions/420](https://github.com/orgs/artraweditor/discussions/420)
   - 바이트 범위: `[292:440]` (UTF-8)
   - SHA-256: `7417f3eb05e6701a71542cd2c32ae9c53eaf041b2db8992ce739de334834c72f`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The Rawtherapee's custom command:\r\n`/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=gimp-3.0 --file-forwarding org.gimp.GIMP @@u %U @@`"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6DN4`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15217528.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528](https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528)
   - 바이트 범위: `[0:194]` (UTF-8)
   - SHA-256: `72583f324d7f740e42c34a733dbc9102e6b7e7bf7057b82790f8ce09131eb95e`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Hi, try with a wrapper shell script, something like this:\r\n\r\n```bash\r\n#!/bin/sh\r\n\r\n/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=gimp-3.0 --file-forwarding org.gimp.GIMP \"$1\"\r\n```"
     ```

### Q083. GitHub Discussion #420에서 Flatpak 기반 외부 편집기를 연동하기 위해 래퍼 셸 스크립트를 작성하는 단계와, 이를 ART 환경설정(Preferences)에 등록할 때의 경로 지정 및 실행 권한 부여 절차는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:420`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4A6DN4"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6DN4`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15217528.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528](https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528)
   - 바이트 범위: `[0:194]` (UTF-8)
   - SHA-256: `72583f324d7f740e42c34a733dbc9102e6b7e7bf7057b82790f8ce09131eb95e`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Hi, try with a wrapper shell script, something like this:\r\n\r\n```bash\r\n#!/bin/sh\r\n\r\n/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=gimp-3.0 --file-forwarding org.gimp.GIMP \"$1\"\r\n```"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6DN4`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15217528.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528](https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528)
   - 바이트 범위: `[198:345]` (UTF-8)
   - SHA-256: `164c29be97e987313d2f462afc0d55dcf597b942af65d732751c860c5ba81515`
   - 원문 스팬 (JSON String Literal):
     ```json
     "If you call the script e.g.  `photogimp.sh`, then simply specify its path in the preferences (and make sure that the script is actually executable)"
     ```

### Q084. GitHub Discussion #424 설명 기준, ART의 Film Simulation에서 LUT가 점 단위(point-wise) 연산만 지원하여 halation과 grain을 직접 포함하지 못하는 기술적 이유와 ART 내의 대체 도구 경로는 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `concept` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:discussion:424`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4A6YYd"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6YYd`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15304221.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221)
   - 바이트 범위: `[7:512]` (UTF-8)
   - SHA-256: `29759bc190cdf8c4111c86465877258062bd1947cc6f52d45a4bee8e7315ce54`
   - 원문 스팬 (JSON String Literal):
     ```json
     "ART uses a LUT for the film simulations. This means that it can only apply \"point-wise\" functions, i.e. effects that look at a single pixel at a time. Both halation and grain are \"spatial\" operations, that need to look at a neighborhood of each pixel, and are not possible to implement with a LUT. That's why they are not available in the film simulations. \r\nBut they exist in other forms in ART, specifically in \"Local Editing -> Smoothing\" (mode \"Halation\" for halation, and mode \"Add noise\" for grain)."
     ```

### Q085. GitHub Discussion #440 설명 기준으로, ART의 파일 브라우저 컨텍스트 메뉴에 별도의 'Move(이동)' 메뉴가 없을 때 파일을 다른 폴더로 이동시키는 공식 대안 기능은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `workflow` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:discussion:440`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4A7c93"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7c93`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15585143.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/440#discussioncomment-15585143](https://github.com/artraweditor/ART/discussions/440#discussioncomment-15585143)
   - 바이트 범위: `[5:54]` (UTF-8)
   - SHA-256: `370b4304fe128fc42e78f174040878f3f0a239036634d750418e1845b1ea11ed`
   - 원문 스팬 (JSON String Literal):
     ```json
     "There's rename which also works as a move.\r\n\r\nHTH"
     ```

### Q086. GitHub Discussion #442에서 한 도구에서 생성한 마스크를 다른 도구에서 재사용하려 할 때 마스크에 이름을 부여하는 방법과, 파이프라인에서 Linked mask가 나타나는 후속(subsequent) 도구들의 순서 조건은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:442`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion:D_kwDONWPV1M4Ajzpk", "discussion-comment:DC_kwDONWPV1M4A7gGl"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion:D_kwDONWPV1M4Ajzpk`
   - 소스 파일: `data/issues/snapshots/discussions/442.json` (절: `/body`)
   - URL: [https://github.com/orgs/artraweditor/discussions/442](https://github.com/orgs/artraweditor/discussions/442)
   - 바이트 범위: `[216:351]` (UTF-8)
   - SHA-256: `ac53afa7ba479b1c74632b1fbd9974ebffa984cfb23d7515f22b4e31e5df3355`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Now I want to reuse this same mask elsewhere ... but I don't see / find a way how to refer to it. How can I achieve the intended reuse?"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7gGl`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15597989.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/442#discussioncomment-15597989](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15597989)
   - 바이트 범위: `[23:328]` (UTF-8)
   - SHA-256: `13f49b9ea1c5f0d66ff27ccef83d598ea718bb1cffd19b14379acb2f92bb1657`
   - 원문 스팬 (JSON String Literal):
     ```json
     "You just have to give a name to the mask, and then it will appear in subsequent tools as a \"Liked mask\". \"Subsequent\" here means that the tool / region follows the one in which you originally defined the mask in the processing pipeline (the order is the same as you see on the screen, from top to bottom)."
     ```

### Q087. GitHub Discussion #442 설명 기준, 마스크 재사용 시 파이프라인 후속 도구에 대한 Linked mask 연결 방식과 일반 복사/붙여넣기(copy/paste) 방식의 파이프라인 방향 제약 및 파라메트릭 마스크 결과 차이는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `concept` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:442`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4A7gGl", "discussion-comment:DC_kwDONWPV1M4A7hf1"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7gGl`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15597989.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/442#discussioncomment-15597989](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15597989)
   - 바이트 범위: `[128:328]` (UTF-8)
   - SHA-256: `d25a648ec9053df63c5e221a94c1ee3f7659d05dfcc396050ff5a4f984b3c835`
   - 원문 스팬 (JSON String Literal):
     ```json
     "\"Subsequent\" here means that the tool / region follows the one in which you originally defined the mask in the processing pipeline (the order is the same as you see on the screen, from top to bottom)."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7hf1`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15603701.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701)
   - 바이트 범위: `[202:459]` (UTF-8)
   - SHA-256: `0fac979519b1b1729b5e06f0ed2ca183c40bbf29a4535ce0bc2a0304f5560570`
   - 원문 스팬 (JSON String Literal):
     ```json
     "However, you can copy/paste a mask from a tool to another freely. The masks might not be identical (because the result of parametric masks depend on where they are applied in the pipeline), but should be close enough to give you a reasonable starting point."
     ```

### Q088. GitHub Discussion #489 설명 기준으로, ART에서 타원형(ellipse) 마스크를 생성하고자 할 때 권장되는 설정 조작법은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:discussion:489`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4BBAtC"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4BBAtC`
   - 소스 파일: `data/issues/snapshots/discussion-comments/17042242.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/489#discussioncomment-17042242](https://github.com/artraweditor/ART/discussions/489#discussioncomment-17042242)
   - 바이트 범위: `[5:72]` (UTF-8)
   - SHA-256: `3b0b4699c3f1af1a6e8d47886eea2180bb13222f31ffbc0b9838657f540ced62`
   - 원문 스팬 (JSON String Literal):
     ```json
     "You can just use a rectangle mask and set roundness to 100%.\r\n\r\nHTH"
     ```

### Q089. GitHub Discussion #494에서 Fedora 환경의 Flatpak 패키지로 설치한 ART가 홈 디렉토리 외의 로컬 디스크 드라이브에 접근하지 못할 때 제시된 의심 원인과 검증된 해결 방법은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:discussion:494`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["discussion-comment:DC_kwDONWPV1M4BBoUd", "discussion-comment:DC_kwDONWPV1M4BBoVr", "discussion-comment:DC_kwDONWPV1M4BBpDW"]`

**근거 스팬 (3개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4BBoUd`
   - 소스 파일: `data/issues/snapshots/discussion-comments/17204509.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/494#discussioncomment-17204509](https://github.com/artraweditor/ART/discussions/494#discussioncomment-17204509)
   - 바이트 범위: `[8:215]` (UTF-8)
   - SHA-256: `c8b54c9e299e2276a2d1dec2197c0bf4fc278c86171a3b09254bc2c7489bb6ad`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I am using the flatpack that was suggested by the Fedora Discover package, I am running\nFedora 44, KDE Plasma. The menu does not list internal disk drives and manually enetering the path does nothing at all."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4BBoVr`
   - 소스 파일: `data/issues/snapshots/discussion-comments/17204587.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/494#discussioncomment-17204587](https://github.com/artraweditor/ART/discussions/494#discussioncomment-17204587)
   - 바이트 범위: `[48:195]` (UTF-8)
   - SHA-256: `54f5005111d8691e04ce5a524a46c97d8d6ef7f9881146a0c5b77ff299ecd6da`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I think it runs in a sandbox and that might be the reason for this behaviour. Maybe you can try with the appimage that is available here on GitHub?"
     ```

3. **근거 3** (`role=support`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4BBpDW`
   - 소스 파일: `data/issues/snapshots/discussion-comments/17207510.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/494#discussioncomment-17207510](https://github.com/artraweditor/ART/discussions/494#discussioncomment-17207510)
   - 바이트 범위: `[4:72]` (UTF-8)
   - SHA-256: `bc7bf4117af138b6331d5b58a8556230e381f2beac8c875b31513539ae69587c`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I tried the appimage, it works perfectly :) Thank you for your help!"
     ```

### Q090. GitHub Issue #477에서 Sony Alpha A7 V 무손실 .ARW 파일 열기 시 톤 커브 왜곡 및 검은 테두리 버그가 보고되었을 때 사용자의 실제 빌드로 정상 동작이 확인된 ART 소스 트리 계열은 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:issue:477`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue-comment:4433310082"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue-comment:4433310082`
   - 소스 파일: `data/issues/snapshots/issue-comments/4433310082.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/477#issuecomment-4433310082](https://github.com/artraweditor/ART/issues/477#issuecomment-4433310082)
   - 바이트 범위: `[17:121]` (UTF-8)
   - SHA-256: `3b8d48d25cd02709389b1afca0d6698c8562f8f0c138c48e4b9f463db06c7337`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I built the latest master and the Sony A7 V raw files work perfectly now. 🎉 \nThanks for the quick fix"
     ```

### Q091. GitHub Issue #500 설명 기준, ART의 JPEG XL(JXL) 이미지 내보내기 시 세부 압축 설정 옵션의 제공 여부와 고정된 품질 기준은 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `concept` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:issue:500`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue-comment:4711197631"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue-comment:4711197631`
   - 소스 파일: `data/issues/snapshots/issue-comments/4711197631.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631](https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631)
   - 바이트 범위: `[0:67]` (UTF-8)
   - SHA-256: `1a72636b6373fabc9ebbd0e99ee806d629fcf943837d8059a87a247e14473dc2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Yes, there's no option. The quality is fixed to \"visually lossless\""
     ```

### Q092. GitHub Issue #516에서 Canon EOS R8 RAW 파일이 흰색으로 표시될 때 구형 빌드 스크립트로 생성한 자가 빌드와 AppImage 간의 동작 차이 및 썸네일 정상화를 위해 확인된 조치는 무엇인가요?

- **분류**: 카테고리 `demosaic_raw` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:issue:516`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue-comment:5102797884", "issue-comment:5102851028", "issue-comment:5103254495"]`

**근거 스팬 (3개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue-comment:5102797884`
   - 소스 파일: `data/issues/snapshots/issue-comments/5102797884.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/516#issuecomment-5102797884](https://github.com/artraweditor/ART/issues/516#issuecomment-5102797884)
   - 바이트 범위: `[209:417]` (UTF-8)
   - SHA-256: `9a04bb190df9284fe2280d938db65ec7e0a4d1252ad5e397246c90aafcce35bc`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I've tried two versions: self-built and the AppImage. \n\n- Self-built shows white thumbnails in browser and and a white image in the editor\n- AppImage shows white in browser, but the actual image in the editor"
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `issue-comment:5102851028`
   - 소스 파일: `data/issues/snapshots/issue-comments/5102851028.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/516#issuecomment-5102851028](https://github.com/artraweditor/ART/issues/516#issuecomment-5102851028)
   - 바이트 범위: `[4:176]` (UTF-8)
   - SHA-256: `754a932e17d5f6823e587ddcea4588581d3932f66b237dd664106c7e503e0442`
   - 원문 스팬 (JSON String Literal):
     ```json
     "That build script is very outdated, sorry about that. I should remove it from the repo. The app image should work, if you clear the cache also the thumbnail should be fine."
     ```

3. **근거 3** (`role=support`)
   - 문서 ID: `issue-comment:5103254495`
   - 소스 파일: `data/issues/snapshots/issue-comments/5103254495.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/516#issuecomment-5103254495](https://github.com/artraweditor/ART/issues/516#issuecomment-5103254495)
   - 바이트 범위: `[0:76]` (UTF-8)
   - SHA-256: `66b1fdba109e05a365a849e11af6e0559b18e0cb71701d1cbf0a51c366daa86d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Thanks, can confirm cache clearing helped - will use the AppImage going fwd!"
     ```

### Q093. GitHub Issue #521에서 Xubuntu 사용자가 렌즈 보정 프로필 드롭다운이 비활성화되는 문제를 해결하기 위해 ART의 options 파일에 설정한 lensfun db 경로는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `troubleshooting` · 난이도 `factoid`
- **출처**: `github` (`github:artraweditor/ART:issue:521`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue-comment:5315824799"]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue-comment:5315824799`
   - 소스 파일: `data/issues/snapshots/issue-comments/5315824799.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/521#issuecomment-5315824799](https://github.com/artraweditor/ART/issues/521#issuecomment-5315824799)
   - 바이트 범위: `[10:185]` (UTF-8)
   - SHA-256: `04791d314fccd5207c5fe64f56b17aaff1541d8a71a80842c87e50dffcedb26d`
   - 원문 스팬 (JSON String Literal):
     ```json
     "On my system the lensfun db is at /usr/share/lensfun/**version_1**\nAfter setting that path in ARTs option file, everything works as usual and no grayed-out dropdowns any more."
     ```

### Q094. GitHub Issue #524에서 1.26.8 릴리스 및 1차 나이틀리 빌드(ART-165b246-linux64)에서 여전히 발생했던 크래시 증상과 최종적으로 해결이 확인된 나이틀리 빌드 식별자는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:issue:524`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue-comment:5648127070", "issue-comment:5670040673"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue-comment:5648127070`
   - 소스 파일: `data/issues/snapshots/issue-comments/5648127070.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070](https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070)
   - 바이트 범위: `[196:1551]` (UTF-8)
   - SHA-256: `ac96a971351514a27d1f6289c9d7407583acfd2013c57260b0277c5d9b4f0e6a`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I have downloaded the ART-165b246-linux64.tar.xz release, and installed it to test.  \n\nFirst I tested by opening the RAW file, applying the arp settings file, and then double-clicking on the image to zoom to 100%.  I did this three times, and each time the progress bar got 10% through the noise reduction (NR), then froze and crashed after 20 seconds.  \n\nThen I tested by opening the RAW file, applying the arp settings file, and clicking on the 1:1 button to zoom in to 100%.  I did this three times:\n\n1st time - the noise reduction got to 100%, then it froze and ART crashed 20sec later.  \n\n2nd time - the NR progress meter flickered a few times, then slowly moved to 100%, and the image rendered at 100% magnification.  I tried moving around the image by dragging it, which worked fine, then clicked Fit to Screen and the view changed back to fit the whole image on the screen.  I then clicked the 1:1 button again, but this time the NR got to 10%, then froze and crashed.  \n\n3rd time - as the 2nd time, the NR progress meter flickered a few times, moved to 100% and the image rendered at 100% magnification.  I tried to move around the image by dragging, but the first time I did this, the NR got stuck at 10% then ART froze and crashed.  \n\nSo I am sorry to have to report that the nightly binary does work occasionally, but not reliably  I'm afraid."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `issue-comment:5670040673`
   - 소스 파일: `data/issues/snapshots/issue-comments/5670040673.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/524#issuecomment-5670040673](https://github.com/artraweditor/ART/issues/524#issuecomment-5670040673)
   - 바이트 범위: `[436:577]` (UTF-8)
   - SHA-256: `3cc3c938beabca5f9d16b7158fad84a2f9600956c1acb80316334a21ff03785b`
   - 원문 스팬 (JSON String Literal):
     ```json
     "I have tested the new nightly build b11089b-linux64, and it works fine, I can zoom in to 100% and move around without any freezes or crashes."
     ```

### Q095. GitHub Issue #524에서 스팟 제거 활성화 후 100% 확대 시 발생하는 동결/크래시 버그의 구체적인 재현 절차와 개발자가 안내한 Debug 빌드 생성 옵션은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `troubleshooting` · 난이도 `complex`
- **출처**: `github` (`github:artraweditor/ART:issue:524`) · 제품 범위: `art_snapshot`
- **기대 처리**: `grounded_answer` · Gold 지원 문서 ID: `["issue:524", "issue-comment:5655898791"]`

**근거 스팬 (2개)**:

1. **근거 1** (`role=support`)
   - 문서 ID: `issue:524`
   - 소스 파일: `data/issues/snapshots/issues/524.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/524](https://github.com/artraweditor/ART/issues/524)
   - 바이트 범위: `[295:443]` (UTF-8)
   - SHA-256: `002fd089bb4b1365cb4032eac37530923885a04a484829bdfabb71396b68af46`
   - 원문 스팬 (JSON String Literal):
     ```json
     "open the RAW in ART, apply the arp profile, then zoom into 100% - still ART gets to 10% through the noise reduction, freezes for 20sec then crashes."
     ```

2. **근거 2** (`role=support`)
   - 문서 ID: `issue-comment:5655898791`
   - 소스 파일: `data/issues/snapshots/issue-comments/5655898791.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/524#issuecomment-5655898791](https://github.com/artraweditor/ART/issues/524#issuecomment-5655898791)
   - 바이트 범위: `[219:350]` (UTF-8)
   - SHA-256: `f0de39296e1b3ee4d9a919d865ee6f832e75f87025ed3cc077c2a464d11dff75`
   - 원문 스팬 (JSON String Literal):
     ```json
     "To get a debug build, just replace `-DCMAKE_BUILD_TYPE=Release` with `-DCMAKE_BUILD_TYPE=Debug` in Step 3 (configure and build ART)"
     ```

### Q096. GitHub Issue #500 설명 기준으로, ART의 내보내기 대화상자에서 JPEG XL(JXL) 전용 품질 슬라이더를 활성화하여 압축 품질을 50으로 직접 설정하는 절차는 무엇인가요?

- **분류**: 카테고리 `settings_workflow` · 의도 `usage/how-to` · 난이도 `negative`
- **출처**: `github` (`github:artraweditor/ART:issue:500`) · 제품 범위: `art_snapshot`
- **기대 처리**: `unsupported_or_insufficient_evidence` · Gold 지원 문서 ID: `[]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=counterevidence`)
   - 문서 ID: `issue-comment:4711197631`
   - 소스 파일: `data/issues/snapshots/issue-comments/4711197631.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631](https://github.com/artraweditor/ART/issues/500#issuecomment-4711197631)
   - 바이트 범위: `[0:67]` (UTF-8)
   - SHA-256: `1a72636b6373fabc9ebbd0e99ee806d629fcf943837d8059a87a247e14473dc2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Yes, there's no option. The quality is fixed to \"visually lossless\""
     ```

### Q097. GitHub Discussion #424 설명 기준으로, Film Simulation 모듈 내의 3D LUT 파일 하나만을 사용하여 주변 픽셀을 참조하는 halation(빛 번짐) 공간 연산을 직접 구현 및 적용하는 설정 절차는 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `negative`
- **출처**: `github` (`github:artraweditor/ART:discussion:424`) · 제품 범위: `art_snapshot`
- **기대 처리**: `unsupported_or_insufficient_evidence` · Gold 지원 문서 ID: `[]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=counterevidence`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6YYd`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15304221.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221)
   - 바이트 범위: `[158:363]` (UTF-8)
   - SHA-256: `50a3b586eeeb369f88f2b9442c068db680952220ce2cc7452a99e957dbe1c4c8`
   - 원문 스팬 (JSON String Literal):
     ```json
     "Both halation and grain are \"spatial\" operations, that need to look at a neighborhood of each pixel, and are not possible to implement with a LUT. That's why they are not available in the film simulations."
     ```

### Q098. GitHub Discussion #424 설명 기준으로, Film Simulation LUT 자체 내부에서 공간 연산(spatial operation) 알고리즘을 구동하여 픽셀 이웃 기반의 필름 그레인(film grain)을 직접 생성하도록 설정하는 방법은 무엇인가요?

- **분류**: 카테고리 `color_wb` · 의도 `usage/how-to` · 난이도 `negative`
- **출처**: `github` (`github:artraweditor/ART:discussion:424`) · 제품 범위: `art_snapshot`
- **기대 처리**: `unsupported_or_insufficient_evidence` · Gold 지원 문서 ID: `[]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=counterevidence`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A6YYd`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15304221.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221](https://github.com/artraweditor/ART/discussions/424#discussioncomment-15304221)
   - 바이트 범위: `[7:304]` (UTF-8)
   - SHA-256: `fc091c70bb97225e279fe8b4ef83129e495c4a4b021d9b60dd8496484709c3a2`
   - 원문 스팬 (JSON String Literal):
     ```json
     "ART uses a LUT for the film simulations. This means that it can only apply \"point-wise\" functions, i.e. effects that look at a single pixel at a time. Both halation and grain are \"spatial\" operations, that need to look at a neighborhood of each pixel, and are not possible to implement with a LUT."
     ```

### Q099. GitHub Discussion #442 설명 기준으로, 파이프라인 뒤쪽에 위치한 도구에서 정의한 named mask를 파이프라인 앞쪽(upstream) 도구에 동적 'Linked mask'로 직접 연결하여 사용하는 절차는 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `usage/how-to` · 난이도 `negative`
- **출처**: `github` (`github:artraweditor/ART:discussion:442`) · 제품 범위: `art_snapshot`
- **기대 처리**: `unsupported_or_insufficient_evidence` · Gold 지원 문서 ID: `[]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=counterevidence`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7hf1`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15603701.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701)
   - 바이트 범위: `[6:201]` (UTF-8)
   - SHA-256: `4bf5545ad22184e5c83899fbd258316eccb9e0903d1be9200bbd159ee51f9e2e`
   - 원문 스팬 (JSON String Literal):
     ```json
     "you are right, you can only reuse masks in tools that appear later in the pipeline. This is not something that can be relaxed easily, and I have no plans of changing it in the near future, sorry."
     ```

### Q100. GitHub Discussion #442 설명 기준으로, 파이프라인상 서로 다른 처리 위치를 갖는 도구 간에 parametric mask를 복사/붙여넣기할 때 생성되는 마스크 픽셀 결과가 완전히 100% 동일함을 강제 보장하는 워크플로우 설정법은 무엇인가요?

- **분류**: 카테고리 `mask_local` · 의도 `workflow` · 난이도 `negative`
- **출처**: `github` (`github:artraweditor/ART:discussion:442`) · 제품 범위: `art_snapshot`
- **기대 처리**: `unsupported_or_insufficient_evidence` · Gold 지원 문서 ID: `[]`

**근거 스팬 (1개)**:

1. **근거 1** (`role=counterevidence`)
   - 문서 ID: `discussion-comment:DC_kwDONWPV1M4A7hf1`
   - 소스 파일: `data/issues/snapshots/discussion-comments/15603701.json` (절: `/body`)
   - URL: [https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701](https://github.com/artraweditor/ART/discussions/442#discussioncomment-15603701)
   - 바이트 범위: `[268:459]` (UTF-8)
   - SHA-256: `2dd2755a4363ba19fbad4b2c2a2e86779b5b7384b5c33198cea7f85c2db4a051`
   - 원문 스팬 (JSON String Literal):
     ```json
     "The masks might not be identical (because the result of parametric masks depend on where they are applied in the pipeline), but should be close enough to give you a reasonable starting point."
     ```

