# ART Master 검색 평가 질문 데이터셋 검증 보고서

- **검증 일시**: `2026-09-28T05:11:28.325834+00:00`
- **데이터셋 ID**: `t08-1-100-v1` (규칙 버전: `t10-2a-v1`)
- **총 질문 수**: 100개 (RawPedia 80개 + GitHub 20개)
- **검증 결과**: **100% PASS** (모든 원문 바이트/해시 일치 및 제약 조건 충족)

## 1. 입력 원문 무결성 및 지문(Fingerprint) 검증

| 대상 문서 | 예상 SHA-256 | 검증 결과 | 상태 |
|---|---|---|:---:|
| `docs/rawpedia_collection.md` | `234766dbe5ace8f8ccef4965a32ced0b79ad55939a2363bfb0ebae126863a7a0` | 일치 | PASS |
| `data/issues/search-candidates.json` | `c2074548354406b6bd2e886259ca8eea4a02813dead57fba77e0bf1a5bf86344` | 일치 | PASS |
| `data/issues/sync-state.json` | `0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187` | 일치 | PASS |
| RawPedia 116개 원문 목록 | `241c48434bab72cceacfdcc083869c4e27265e4b474d48988fab0f0cb813f56f` | 일치 (`241c48434bab72cceacfdcc083869c4e27265e4b474d48988fab0f0cb813f56f`) | PASS |

## 2. 데이터셋 분류 및 분포 통계

### 2.1 카테고리별 / 난이도별 분포

| 카테고리 | 전체 문항 | Factoid | Complex | Negative | RawPedia 고유 페이지 수 |
|---|---:|---:|---:|---:|---:|
| `exposure_tone` | 16 | 9 | 7 | 0 | 10개 |
| `color_wb` | 21 | 11 | 8 | 2 | 11개 |
| `demosaic_raw` | 14 | 8 | 6 | 0 | 8개 |
| `sharpening_noise` | 12 | 7 | 5 | 0 | 7개 |
| `mask_local` | 19 | 7 | 10 | 2 | 7개 |
| `settings_workflow` | 18 | 8 | 9 | 1 | 7개 |
| **합계** | **100** | **50** | **45** | **5** | **50개 페이지** |

### 2.2 의도(Intent)별 분포

| 의도 (Intent) | RawPedia | GitHub | 합계 | WBS 플랜 목표 |
|---|---:|---:|---:|---:|
| `usage/how-to` | 28 | 7 | 35 | 35 |
| `concept` | 22 | 3 | 25 | 25 |
| `troubleshooting` | 14 | 6 | 20 | 20 |
| `workflow` | 16 | 4 | 20 | 20 |
| **합계** | **80** | **20** | **100** | **100** |

## 3. 원문 대조 검증 및 테스트 요약

- **바이트 슬라이스 전수 일치**: 100개 문항의 모든 근거 스팬(총 137개 스팬)이 원문 파일의 정확한 바이트 오프셋에서 100% 동일하게 추출됨.
- **해시 무결성**: 모든 근거 스팬의 SHA-256 해시와 소스 파일 SHA-256 해시가 실제 파일 내용과 100% 일치함.
- **Negative 5개 무결성**: Q096~Q100 문항은 `expected_behavior='unsupported_or_insufficient_evidence'`, `role='counterevidence'`, `gold_support_doc_ids=[]` 규칙을 완벽 준수함.
- **Markdown 명세 재현성**: `docs/search_eval_queries.md`와 JSON 정본에서 재직렬화한 마크다운 바이트가 100% 일치함을 확인.

