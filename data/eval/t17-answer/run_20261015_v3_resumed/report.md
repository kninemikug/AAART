# Task 17 Slice 1 15개 질문 답변 대조 보고서

- 생성일: 2026-10-16T00:12:42.454199+09:00
- 질문 원본 SHA-256: `91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8`
- T11 기준선 SHA-256: `5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7`
- 프롬프트 버전: `t17-answer-v1`
- 생성 모델: `gpt-5.6-sol` (제공처: `codex-cli`)

## 1. 15개 전수 실행 결과 요약

| Query ID | 출처 | T11 상태 / 인용 | T14 A 상태 / 인용 | T14 B 상태 / 인용 |
|---|---|---|---|---|
| Q001 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q004 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q014 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q021 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (2) | SUPPORTED (1) |
| Q033 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (2) |
| Q044 | RAWPEDIA | INSUFFICIENT_EVIDENCE (0) | INSUFFICIENT_EVIDENCE (0) | SUPPORTED (2) |
| Q054 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q063 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q072 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q080 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q084 | GITHUB | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q086 | GITHUB | INSUFFICIENT_EVIDENCE (1) | SUPPORTED (2) | SUPPORTED (2) |
| Q092 | GITHUB | SUPPORTED (3) | SUPPORTED (3) | SUPPORTED (3) |
| Q093 | GITHUB | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) |
| Q096 | GITHUB | UNSUPPORTED (2) | UNSUPPORTED (1) | UNSUPPORTED (1) |

## 2. 지정 수동 검토 (Q001, Q086, Q096)

### Q001 (RawPedia: Auto Levels)
- **기대**: T11/A/B 모두 `SUPPORTED`. 히스토그램 분석 및 Exposure 조정 설명 유지, RawTherapee 참고 범위 유지.
- **실제 상태 (B)**: `SUPPORTED`
- **실제 인용수**: 1
- **답변 발췌**: RawTherapee의 Auto Levels는 히스토그램을 분석한 뒤, 이미지가 적절히 노출되도록 Exposure 섹션의 설정을 조정합니다. 구체적으로 Exposure Compensation, Highlight Compression, Highlight Reconstruction, Black, Lightness, Contrast 슬라이더만 사용합니다. [출처...
- **수동 검토 상태 (B)**: `verified` (사유: Exposure Auto Levels 첫 두 문단과 분석 대상·노출 목적 및 Exposure compensation/Highlight compression/Highlight reconstruction/Black/Lightness/Contrast 여섯 항목을 대조했다.)

### Q086 (GitHub: Discussion #442 마스크 공유)
- **기대**: T11 재생은 `INSUFFICIENT_EVIDENCE` 유지. T14 A/B는 #442 본문과 댓글(Linked mask)로 `SUPPORTED` 기대.
- **실제 상태 (T11)**: `INSUFFICIENT_EVIDENCE`
- **수동 검토 상태 (T11)**: `verified` (사유: T11과 동일하게 #442가 없는 문맥에서 부족 상태다. 부수 설명은 RawTherapee Local Adjustments의 추가 마스크와 파이프라인 순서에 한정하고 Linked mask 이름 입력 UI나 후속 조건을 추측하지 않았다.)
- **실제 상태 (B)**: `SUPPORTED`
- **실제 인용수 (B)**: 2
- **답변 발췌 (B)**: 해당 Discussion 스냅샷에 따르면, 먼저 원래 도구에서 만든 마스크에 이름을 지정하면 이후 도구에서 해당 마스크가 “Linked mask”로 나타납니다. 다만 제공된 텍스트에는 이름을 입력하는 구체적인 UI 조작 방법은 설명되어 있지 않습니다.[출처: ART newbie: How to reuse the same mask I painted in one tool in one or more other tools? (discussion-comm...
- **수동 검토 상태 (B)**: `verified` (사유: Discussion #442의 실제 댓글 #15597989와 #15603701을 직접 대조했다. 반드시 필요한 이름·후속·위→아래 조건을 모두 설명하고 UI 조작을 발명하지 않으며, 앞쪽 도구에 대한 복사붙여넣기 대안을 제한과 함께 제시한다.)

### Q096 (GitHub: Issue #500 JXL 설정)
- **기대**: T11/A/B 모두 `UNSUPPORTED`. JXL 품질 슬라이더는 지원되지 않으며 visually lossless 고정임을 설명.
- **실제 상태 (B)**: `UNSUPPORTED`
- **실제 인용수 (B)**: 1
- **답변 발췌 (B)**: GitHub Issue #500의 해당 스냅샷 기준으로는 ART의 JXL 내보내기에 별도 옵션이 없으므로, 전용 품질 슬라이더를 활성화해 압축 품질을 50으로 직접 설정하는 절차는 지원되지 않습니다. JXL 품질은 "visually lossless"로 고정되어 있다고 설명되어 있습니다. [출처: question: absolute no settings for...
- **수동 검토 상태 (B)**: `verified` (사유: Issue #500의 #4711197631 직접 반증과 답변이 일치한다. UNSUPPORTED를 반환하고 슬라이더를 활성화하는 가상 절차를 만들지 않았다.)

## 3. CP2 양성 5개 (Q001, Q004, Q014, Q054, Q063) 검토

| Query ID | T14 A 상태 / 인용 | T14 B 상태 / 인용 | 검토 상태 (B) |
|---|---|---|---|
| Q001 | SUPPORTED (1) | SUPPORTED (1) | `verified` |
| Q004 | SUPPORTED (1) | SUPPORTED (1) | `verified` |
| Q014 | SUPPORTED (1) | SUPPORTED (1) | `verified` |
| Q054 | SUPPORTED (1) | SUPPORTED (1) | `verified` |
| Q063 | SUPPORTED (1) | SUPPORTED (1) | `verified` |

## 4. Q010 / Q077 제품 범위 추가 회귀

- **Q010 (B)**: 상태 `SUPPORTED`, 적용 범위 `제품 범위: RawTherapee; 스냅샷: 09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6` (RawTherapee 근거 보존)
- **Q077 (B)**: 상태 `SUPPORTED`, 적용 범위 `제품 범위: RawTherapee; 스냅샷: 09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6` (RawTherapee 근거 보존)

## 5. 게이트 B 판정
- **최종 판정**: `PASS`

## 6. 재개 계보와 독립 검증

실패 실행은 ../run_20261015_v3/에 그대로 보존했다. 해당 실행에서 실제 요청·원응답·코드/입력 지문 검증을 통과한 정상 9건은 run ID와 레코드 해시를 바꾸지 않고 재사용했다. 사용량 한도로 실패했던 38건만 같은 제공처·모델·고정 bundle로 새로 생성했다. 선택된 47건은 모두 정상 실행이며 항목별 생성 1회다. 이 두 실행 폴더 전체에는 실패 38회를 포함해 총 85회 생성 시도가 남는다. 재사용 계보는 resume_manifest.json, 컨트롤러는 resume_evaluation.py에 보존했다.

전체 47건의 주요 사실·상태·제품 범위·인용을 원문과 대조했고, 고정 15개 질문은 T11 기존 답변 및 새 A/B 문맥을 함께 비교했다. 필수 19개 검토는 각 실제 run ID·레코드 해시·주장·cid·URL·source_location·판정 이유로 연결했다. T14 A/B 30건은 독립 원문 대조도 통과했다. 전체 대조는 comparison_review.json, 독립 검토는 independent_t14_review.json에 있다.

Q001은 세 track 모두 히스토그램과 Exposure 조정 및 RawTherapee 범위를 유지했다. Q086은 T11에서 #442 부재로 부족, A/B에서 #15597989·#15603701의 이름/후속/위→아래 처리 순서로 답변 가능했다. Q096은 세 track 모두 #4711197631 반증을 근거로 UNSUPPORTED다. Q044는 T11/A의 무관 문맥에서 부족 상태를 유지하고, B의 Bit Depth·Floating Point Engine 근거로 답변 가능해졌다. 그 외 질문은 T11의 핵심 사실·절차·제품 범위를 유지했다. 문장 일치나 상태 일치만으로 동등성을 판정하지 않았다.

Q021 A의 Film Simulation 인용은 보조 자료이고 기본 목적의 직접 근거는 Gamut Compression이다. Q033 B의 마지막 문장은 제공 문맥에서 DCP의 역할을 제한한 설명이며 센서 물리 현상에 관한 별도 실험 증거로 해석하지 않는다. Q044 B의 RAM 2배는 원문에서 32비트 float와 16비트 integer 수치 표현량의 비교이며 프로그램 전체 RSS가 항상 2배라는 측정 결과가 아니다. 세 항목의 비차단 검토 메모를 보존했다.

최종 코드는 전체 pytest 906 passed, 1 warning을 통과했다. 경고는 기존 Chroma의 asyncio.iscoroutinefunction 폐기 예정 안내다. 이 결과는 T17 단독 연결 준비 판정이며 T13-2 실제 접합·T16 실제 폴백·CP3 완료를 포함하지 않는다. 기존 질문 반복이며 독립 확대 평가나 경량 모델 비교 결과도 아니다.
