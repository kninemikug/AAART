# Task 17 Slice 1 15개 질문 답변 대조 보고서

- 생성일: 2026-10-15T13:15:07.928752+09:00
- 질문 원본 SHA-256: `91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8`
- T11 기준선 SHA-256: `5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7`
- 프롬프트 버전: `t17-answer-v1`
- 생성 모델: `codex-cli` / `gpt-5.6-sol`

## 1. 15개 전수 실행 결과 요약

| Query ID | 출처 | T11 상태 / 인용 | T14 A 상태 / 인용 | T14 B 상태 / 인용 | 판정 |
|---|---|---|---|---|---|
| Q001 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q004 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q014 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q021 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q033 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (2) | 일치 |
| Q044 | RAWPEDIA | INSUFFICIENT_EVIDENCE (0) | INSUFFICIENT_EVIDENCE (0) | SUPPORTED (2) | 개선/변화 |
| Q054 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q063 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q072 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q080 | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q084 | GITHUB | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q086 | GITHUB | INSUFFICIENT_EVIDENCE (1) | SUPPORTED (2) | SUPPORTED (2) | 일치 |
| Q092 | GITHUB | SUPPORTED (3) | SUPPORTED (3) | SUPPORTED (3) | 일치 |
| Q093 | GITHUB | SUPPORTED (1) | SUPPORTED (1) | SUPPORTED (1) | 일치 |
| Q096 | GITHUB | UNSUPPORTED (2) | UNSUPPORTED (2) | UNSUPPORTED (1) | 일치 |

## 2. 지정 수동 검토 (Q001, Q086, Q096)

### Q001 (RawPedia: Auto Levels)
- **기대**: T11/A/B 모두 `SUPPORTED`. 히스토그램 분석 및 Exposure 조정 설명 유지, RawTherapee 참고 범위 유지.
- **실제 상태 (B)**: `SUPPORTED`
- **실제 인용수**: 1
- **답변 발췌**: RawTherapee의 Auto Levels는 히스토그램을 분석한 뒤, 이미지가 적절히 노출되도록 Exposure 섹션의 설정을 조정합니다. 구체적으로 Exposure Compensation, Highlight Compression, Highlight Reconstruction, Black, Lightness, Contrast 슬라이더만 사용합니다. [출처...
- **검토 결과**: 히스토그램 분석과 Exposure 조정이 원문 근거에 명확히 기반하며 RawTherapee 범위를 보존함. [합격]

### Q086 (GitHub: Discussion #442 마스크 공유)
- **기대**: T11 재생은 `INSUFFICIENT_EVIDENCE` 유지. T14 A/B는 #442 본문과 댓글(Linked mask)로 `SUPPORTED` 기대.
- **실제 상태 (T11)**: `INSUFFICIENT_EVIDENCE`
- **실제 상태 (B)**: `SUPPORTED`
- **실제 인용수 (B)**: 2
- **답변 발췌 (B)**: 해당 Discussion 스냅샷에 따르면, 원래 마스크를 만든 도구에서 마스크에 이름을 지정하면 이후 도구에서 "Linked mask"로 나타납니다. 다만 제공된 텍스트에는 이름을 입력하기 위한 구체적인 UI 조작법은 설명되어 있지 않습니다.[출처: ART newbie: How to reuse the same mask I painted in one tool in one or more other tools? (discussion-comment:D...
- **검토 결과**: 마스크에 이름을 부여하면 Linked mask로 공유되고, 화면 위→아래 처리 순서상 후속 도구에서만 사용 가능하다는 조건과 댓글 앵커가 정확히 반영됨. [합격]

### Q096 (GitHub: Issue #500 JXL 설정)
- **기대**: T11/A/B 모두 `UNSUPPORTED`. JXL 품질 슬라이더는 지원되지 않으며 visually lossless 고정임을 설명.
- **실제 상태 (B)**: `UNSUPPORTED`
- **실제 인용수 (B)**: 1
- **답변 발췌 (B)**: GitHub Issue #500의 해당 스냅샷 기준으로는 ART에 JXL 내보내기 옵션이 없으므로, JXL 전용 품질 슬라이더를 활성화해 압축 품질을 50으로 직접 설정하는 절차는 지원되지 않습니다. JXL 품질은 사용자가 조정하는 방식이 아니라 "visually lossless"로 고정되어 있습니다.[출처: question: absolute no sett...
- **검토 결과**: JXL 품질 슬라이더 조작 절차를 허위 생성하지 않고, 별도 설정 없이 visually lossless로 고정된다는 반증 댓글을 정확히 인용함. [합격]

## 3. CP2 양성 5개 (Q001, Q004, Q014, Q054, Q063) 검토

| Query ID | T14 A 상태 / 인용 | T14 B 상태 / 인용 | 주요 사실 및 근거 확인 |
|---|---|---|---|
| Q001 | SUPPORTED (1) | SUPPORTED (1) | 주요 사실 및 원문 세그먼트 인용 완전 부합 확인 |
| Q004 | SUPPORTED (1) | SUPPORTED (1) | 주요 사실 및 원문 세그먼트 인용 완전 부합 확인 |
| Q014 | SUPPORTED (1) | SUPPORTED (1) | 주요 사실 및 원문 세그먼트 인용 완전 부합 확인 |
| Q054 | SUPPORTED (1) | SUPPORTED (1) | 주요 사실 및 원문 세그먼트 인용 완전 부합 확인 |
| Q063 | SUPPORTED (1) | SUPPORTED (1) | 주요 사실 및 원문 세그먼트 인용 완전 부합 확인 |

## 4. Q010 / Q077 제품 범위 추가 회귀

- **Q010 (B)**: 상태 `SUPPORTED`, 적용 범위 `제품 범위: RawTherapee; 스냅샷: 09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6` (RawTherapee 근거 보존)
- **Q077 (B)**: 상태 `SUPPORTED`, 적용 범위 `제품 범위: RawTherapee; 스냅샷: 09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6` (RawTherapee 근거 보존)
- **검토 결과**: RawTherapee 근거를 임의로 ART 기능 지원으로 확정하지 않고 제품 범위를 엄격히 보존함. [합격]

## 5. 호출 계약 및 무결성 판정
- 검색 호출: 0회 (상위 검색 결과 그대로 소비)
- 재작성 호출: 0회 (T14 재작성 결과 보존)
- 생성 호출: 항목별 1회
- 구조/출처 매핑 위반: 0건
- **게이트 B 판정**: 통과 (연결 준비 완료)
