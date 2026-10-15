# Task 17 Slice 1 15개 질문 답변 대조 보고서

- 생성일: 2026-10-15T17:23:27.758965+09:00
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
| Q021 | RAWPEDIA | SUPPORTED (2) | SUPPORTED (1) | SUPPORTED (1) |
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
- **답변 발췌**: RawTherapee의 Auto Levels는 히스토그램을 분석한 뒤, 노출이 적절한 이미지가 되도록 Exposure 섹션의 설정을 조정합니다. 구체적으로 Exposure Compensation, Highlight Compression, Highlight Reconstruction, Black, Lightness, Contrast 슬라이더만 사용합니다. [...
- **수동 검토 상태 (B)**: `verified` (사유: T14 B 검색 근거 원문과 정확히 부합하며 제품 범위를 RawTherapee로 유지하고 필수 인용 매핑 확인됨.)

### Q086 (GitHub: Discussion #442 마스크 공유)
- **기대**: T11 재생은 `INSUFFICIENT_EVIDENCE` 유지. T14 A/B는 #442 본문과 댓글(Linked mask)로 `SUPPORTED` 기대.
- **실제 상태 (T11)**: `INSUFFICIENT_EVIDENCE`
- **수동 검토 상태 (T11)**: `verified` (사유: T11 문맥에는 #442 논의가 없으므로 근거 부족 취지 안내를 충족하며, 존재하지 않는 이름 입력 절차를 생성하지 않고 안전하게 종료됨.)
- **실제 상태 (B)**: `SUPPORTED`
- **실제 인용수 (B)**: 2
- **답변 발췌 (B)**: 해당 Discussion 스냅샷에 따르면, 원래 마스크를 정의한 도구에서 마스크에 이름을 지정하면 이후 도구에서 그 마스크가 "Linked mask"로 나타납니다. 다만 제공된 문맥은 이름을 입력하는 구체적인 UI 조작법까지는 설명하지 않습니다. [출처: ART newbie: How to reuse the same mask I painted in one tool in one or more other tools? (discussion-commen...
- **수동 검토 상태 (B)**: `verified` (사유: GitHub Discussion #442 댓글(#discussioncomment-15597989)에 정확히 매핑되며, Linked mask 조건과 화면 위아래 처리 순서를 충실히 전달함.)

### Q096 (GitHub: Issue #500 JXL 설정)
- **기대**: T11/A/B 모두 `UNSUPPORTED`. JXL 품질 슬라이더는 지원되지 않으며 visually lossless 고정임을 설명.
- **실제 상태 (B)**: `UNSUPPORTED`
- **실제 인용수 (B)**: 1
- **답변 발췌 (B)**: GitHub Issue #500의 해당 스냅샷 기준으로는 ART에 JXL 내보내기 옵션이 없으므로, 전용 품질 슬라이더를 활성화해 압축 품질을 50으로 직접 설정하는 절차는 없습니다. JXL 품질은 "visually lossless"로 고정되어 있습니다. [출처: question: absolute no settings for jxl export? (issu...
- **수동 검토 상태 (B)**: `verified` (사유: T14 B 문맥에서 #issuecomment-4711197631을 정확히 인용하여 JXL 품질 슬라이더 부재를 직접 반증함.)

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
