# Task 15 T17 답변 및 인용 검증 보고서

- 생성 시각: `2026-10-16T09:44:22.446377+00:00`
- 핵심 대조 질문 수: `31개`
- 생성 모드: `모의 생성기 (mock LLM)` -> **G5 최종 판정: `FAIL`** (실제 LLM 호출 증거 대기)

## 1. 핵심 질문 대조 결과

| 질문 ID | 출처 | 실제 경로 | B0 상태 | T15 상태 | 상태 일치 | 제품 범위 |
|---|---|---|---|---|:---:|---|
| Q001 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q004 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q010 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q014 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q017 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q021 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q024 | rawpedia | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q025 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q026 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q030 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q033 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q041 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q044 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q053 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q054 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q055 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q057 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q063 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q070 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q072 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q077 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q080 | rawpedia | RAWPEDIA | SUPPORTED (1) | SUPPORTED (1) | 일치 | RawTherapee |
| Q084 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q086 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q092 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q093 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q096 | github | GITHUB | UNSUPPORTED (1) | UNSUPPORTED (1) | 일치 | ART |
| Q097 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q098 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q099 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |
| Q100 | github | GITHUB | SUPPORTED (1) | SUPPORTED (1) | 일치 | ART |

## 2. Q010 / Q077 제품 범위 안전성
- Q010 제품 범위: `['RawTherapee']`
- Q077 제품 범위: `['RawTherapee']`
- ART로의 무단 승격 차단 판정: `PASS`

## 3. G5 게이트 최종 판정
- 답변 생성 기술 오류: 0건
- 부정 질문 허위 지원: 4건
- 모의 생성기(mock) 사용으로 실제 생성 호출 및 정밀 인용 매핑 검증은 PENDING으로 유지함.
- **G5 최종 판정:** `FAIL`
