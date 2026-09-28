# Issues·Discussions 정제 및 검색 후보 구축 규칙

작성일: 2026-09-28 · 규칙 버전: `t10-2a-v1` · 스키마 버전: `1`

## 1. 목적과 대상 입력

이 문서는 수집된 ART GitHub Issues와 Discussions 스냅샷 원문(`data/issues/`)을 정제하여 검색 후보 목록(`data/issues/search-candidates.json`)과 정제 보고서(`data/issues/filter-report.json`)를 생성하는 규칙과 기준을 정의한다.

### 대상 입력 제원
- 저장소: `artraweditor/ART`
- 동기화 기준 시각 (`last_synced_at`): `2026-09-28T02:06:12Z`
- Git HEAD 커밋: `2f4124606`
- `sync-state.json` SHA-256: `0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187`
- 스냅샷 매니페스트 SHA-256: `52b6cdf587e1f5ed12d80570a41a476ef02dd6e2118c9a9c09a871e7889d01c5`
- 총 레코드 수: 3,080개 (Issue 465, Issue 댓글 2,471, Discussion 30, Discussion 댓글 114)
- 총 스레드 수: 495개 (Issue 465, Discussion 30)
- 원문 JSON 크기 합계: 8,245,782 bytes

## 2. 실제 데이터 분석 및 필드 관찰 사실

### 2.1 종류별 원문 필드와 수집 한계
1. **Issue (465개)**:
   - 필드: `number`, `id`, `node_id`, `title`, `body`, `state`, `state_reason`, `html_url`, `url`, `created_at`, `updated_at`, `closed_at`, `author_association`, `user`, `closed_by`, `labels`, `comments`, `reactions`.
   - 한계: 채택 답변 필드 부재, 종료 사유 이벤트 부재. `pull_request` 키는 0개.
2. **Issue 댓글 (2,471개)**:
   - 필드: `id`, `node_id`, `body`, `html_url`, `url`, `issue_url`, `created_at`, `updated_at`, `author_association`, `user`, `reactions`, `minimized`, `pin`.
   - 한계: `state`, `title` 부재. `minimized`는 전부 null.
3. **Discussion (30개)**:
   - 필드: `id`, `title`, `body`, `url`, `createdAt`, `updatedAt`, `databaseId`, `number`, `author`, `category`.
   - 한계: `state`, `closed`, `isAnswered`, `answer`, `reactions`, `authorAssociation` 등 플랫폼 채택 답변 및 상태 신호가 GraphQL 조회 필드에 미수집.
4. **Discussion 댓글 (114개)**:
   - 필드: `id`, `body`, `url`, `createdAt`, `updatedAt`, `databaseId`, `author`.
   - 한계: 답글 계층(`replyTo`), 채택 여부(`isAnswer`), 반응(`reactions`), 소속(`authorAssociation`) 미수집.

### 2.2 신호 분포 및 관찰 특이사항
- Issue 상태: closed 382건, open 83건. 댓글 없는 47개 중 30개가 closed로, 종료 상태는 해결이나 유용성과 무관하다.
- 반응(Reactions): 반응이 1개 이상인 Issue는 8개, 댓글은 39개에 불과하다(98% 이상이 반응 0). 반응 수 기반 임계치는 유용한 데이터를 부당하게 탈락시킨다.
- Discussion 채택 답변 신호: 현재 수집 스키마에서 미수집(`not_collected`) 상태이며, 이는 미해결을 의미하지 않는다.
- Bitbucket 이관 헤더:
  - Issue 328개, 댓글 1,900개에 `**Original comment by ...**` 또는 `**[Original report]...**` 형태의 머리말이 존재한다.
  - 이들의 GitHub REST API `user.login`은 일괄 `agriggio`로 등록되어 있으므로, API 작성자 소속(`COLLABORATOR`)만으로 프로젝트 관리자의 발언으로 취급해서는 안 된다. 원본 화자 정보는 본문 머리말에서 별도 파싱한다.

## 3. 정제 원칙과 판정 체계

### 3.1 처리 단위와 3단계 판정 (Disposition)
기본 처리 단위는 부모 객체와 해당 부모에 연결된 모든 댓글로 구성된 **스레드(Thread)**다.

| 판정 (Disposition) | 설명 및 출력 | 적용 조건 |
|---|---|---|
| `include` | 검색 후보(`search-candidates.json`) 및 보고서에 포함 | 원문 검토 결정이 존재하며 구체적인 기술 증거, 본문 조각, 한계 사항이 검증됨 |
| `exclude` | 보고서(`filter-report.json`)에만 기록 | 구조적 플레이스홀더, 빈 내용, 단순 릴리스 알림, 확정된 노이즈 |
| `review` | 보고서(`filter-report.json`)에만 기록 | 미검토 스레드, 증거 불충분, 상충되는 결과, 지문 불일치(Stale) |

### 3.2 금지된 자동 추론 규칙
1. `closed`, `completed`, `[Solved]` 제목, `COLLABORATOR` 소속, 높은 반응 수, 마지막 댓글 여부를 독립적인 해결 증거로 취급하지 않는다.
2. `thanks`, `Thank you!`, `+1` 등 단순 감사/확인 표현을 독립된 기술적 조치 확인으로 쓰지 않는다.
3. `fixed`, `solved`, `works` 단어가 본문에 포함되어 있더라도 조치 대상, 적용 버전, 재현 여부가 원문 검토를 통해 확인되지 않으면 해결로 승격하지 않는다.
4. Discussion의 평탄화된 댓글 목록에서 시간순 인접성만으로 앞선 댓글의 확인 답변으로 단정하지 않는다.

### 3.3 지식 상태 분류 (Knowledge Status)
`include`로 결정된 후보는 다음 중 하나의 지식 상태를 부여받는다:
- `curated_guidance`: 원문에 조작 방법, 설정 경로, ART 동작 제약에 대한 구체적 안내가 있는 경우.
- `reported_fix`: 특정 버전, 커밋, 빌드에 대한 조치와 성공 보고가 연결된 경우.
- `unresolved_report`: 재현 환경, 증상, 상충 및 미해결 상태가 구체적으로 기술된 경우.

## 4. 증거 신호 및 이유 코드 (Reason Codes)

### 4.1 긍정 증거 신호
- `ACTIONABLE_GUIDANCE`: 구체적인 작업 지침 (예: 외부 편집기 래퍼 스크립트 작성 및 설정 경로).
- `ART_TECHNICAL_EXPLANATION`: ART 내부 동작 원리 및 파이프라인 제약에 대한 기술 설명.
- `SELF_CONTAINED_TECHNICAL_GUIDE`: 본문 자체에 환경, 의존성 설치, 빌드 단계가 완비된 기술 문서.
- `USER_CONFIRMED_ACTION`: 동일 조치에 대해 사용자가 구체적으로 변경 사항과 동작 성공을 확인한 경우.
- `FIX_VERSION_CONFIRMED`: 수정 제안과 성공 확인이 동일 버전/빌드(nightly 등)에 명확히 연결된 경우.
- `DETAILED_UNRESOLVED_REPORT`: 문제 증상, 환경, 상충 결과가 명확히 서술된 미해결 보고.

### 4.2 제외 및 보류 이유 코드
- `MIGRATION_PLACEHOLDER`: Bitbucket 이관 당시 생성된 filler issue (`filler issue created by bitbucket_issue_migration`).
- `NO_SUBSTANTIVE_CONTEXT`: 부모 본문이 비어 있고 의미 있는 기술 댓글이 없는 경우 (예: Discussion #525).
- `RELEASE_STUB_ONLY`: Announcements 분류의 단순 릴리스 태그 생성 wrapper (예: Discussion #432, #446).
- `COMMENT_ACK_ONLY`: 댓글 전체가 단순 감사/확인 단문(`thanks`, `thank you`, `+1` 등)으로만 구성된 경우.
- `NOT_SELECTED_BY_CURATION`: 검토된 스레드에서 기술적 핵심 근거로 선택되지 않은 댓글.
- `OUT_OF_SCOPE_PR`: Pull Request 객체 및 관련 댓글.
- `UNANSWERED_QUESTION`: 답변이나 자가 해결 절차가 없는 질문.
- `INSUFFICIENT_EVIDENCE`: 해결 주장만 있거나 조치 내용 및 검증이 불명확한 경우.
- `CONFLICTING_EVIDENCE`: 우회책 보고 후 재현 불가 또는 추가 실패 보고가 상충하는 경우.
- `NOT_REVIEWED`: 원문 검토가 아직 수행되지 않은 유효 스레드.
- `STALE_CURATION`: 검토 이후 댓글 추가/수정으로 스레드 지문(`thread_sha256`)이 변경된 경우.

## 5. 초기 포함 12건 및 주요 대조 사례

### 5.1 고정 포함 후보 (12건)
1. **Issue #477** (`github:artraweditor/ART:issue:477`):
   - 내용: Sony Alpha A7 V raw 지원 제안 및 최신 master 빌드 성공 확인.
   - 상태: `reported_fix`, 신호: `FIX_VERSION_CONFIRMED`.
   - 한계: `VERSION_SPECIFIC` (게시 당시 master 기준).
2. **Issue #500** (`github:artraweditor/ART:issue:500`):
   - 내용: JXL export 품질 설정 부재 및 고정 품질("visually lossless") 설명.
   - 상태: `curated_guidance`, 신호: `ART_TECHNICAL_EXPLANATION`.
   - 한계: `AS_OF_SOURCE_ONLY`.
3. **Issue #516** (`github:artraweditor/ART:issue:516`):
   - 내용: Canon EOS R8 흰색 화면 문제 해결 (캐시 삭제 및 AppImage 안내).
   - 상태: `curated_guidance`, 신호: `USER_CONFIRMED_ACTION`.
   - 한계: `PLATFORM_SPECIFIC`, 관계: `related_to` `issue:503`.
4. **Issue #521** (`github:artraweditor/ART:issue:521`):
   - 내용: Lensfun DB 경로 인식 실패에 따른 `/usr/share/lensfun/version_1` 설정 해결.
   - 상태: `curated_guidance`, 신호: `USER_CONFIRMED_ACTION`.
   - 한계: `PLATFORM_SPECIFIC`.
5. **Issue #524** (`github:artraweditor/ART:issue:524`):
   - 내용: #510 스팟 제거 확대 크래시 재발에 대한 b11089b nightly 해결.
   - 상태: `reported_fix`, 신호: `FIX_VERSION_CONFIRMED`.
   - 한계: `VERSION_SPECIFIC`, `COUNTEREVIDENCE` (이전 165b246 nightly 실패 보존), 관계: `follow_up_to` `issue:510`.
6. **Discussion #412** (`github:artraweditor/ART:discussion:412`):
   - 내용: Windows MSYS2 개발 환경 구성 및 빌드 절차 안내.
   - 상태: `curated_guidance`, 신호: `SELF_CONTAINED_TECHNICAL_GUIDE`.
   - 한계: `PLATFORM_SPECIFIC`.
7. **Discussion #420** (`github:artraweditor/ART:discussion:420`):
   - 내용: 외부 편집기(PhotoGIMP/GIMP Flatpak) 연동 래퍼 스크립트 작성 및 설정 안내.
   - 상태: `curated_guidance`, 신호: `ACTIONABLE_GUIDANCE`.
   - 한계: `PLATFORM_SPECIFIC`.
8. **Discussion #424** (`github:artraweditor/ART:discussion:424`):
   - 내용: LUT 점단위 연산 제약과 Local Editing -> Smoothing (Halation/Add noise) 사용법.
   - 상태: `curated_guidance`, 신호: `ART_TECHNICAL_EXPLANATION`.
   - 한계: `AS_OF_SOURCE_ONLY`.
9. **Discussion #440** (`github:artraweditor/ART:discussion:440`):
   - 내용: Rename 메뉴를 통한 파일 이동 동작 및 XMP 동반 이동 제약.
   - 상태: `curated_guidance`, 신호: `USER_CONFIRMED_ACTION`.
   - 한계: `AS_OF_SOURCE_ONLY`.
10. **Discussion #442** (`github:artraweditor/ART:discussion:442`):
    - 내용: 마스크 이름 부여 및 파이프라인 후속 도구 재사용/복사 제약.
    - 상태: `curated_guidance`, 신호: `ART_TECHNICAL_EXPLANATION`.
    - 한계: `AS_OF_SOURCE_ONLY`.
11. **Discussion #489** (`github:artraweditor/ART:discussion:489`):
    - 내용: 사각형 마스크 roundness 100%를 통한 타원형 마스크 생성 지침.
    - 상태: `curated_guidance`, 신호: `ACTIONABLE_GUIDANCE`.
    - 한계: `AS_OF_SOURCE_ONLY`.
12. **Discussion #494** (`github:artraweditor/ART:discussion:494`):
    - 내용: Flatpak 샌드박스 드라이브 접근 제약과 AppImage 대안 실행 확인 (이메일 푸터 제거).
    - 상태: `curated_guidance`, 신호: `USER_CONFIRMED_ACTION`.
    - 한계: `PLATFORM_SPECIFIC`, `HYPOTHESIS`.

### 5.2 주요 대조 및 제외 사례
- **Issue #510**: closed 상태이나 "조사 예정" 댓글만 존재 -> `review` (`INSUFFICIENT_EVIDENCE`).
- **Issue #511**: 우회책 제시 후 재현 불가 및 미해결 유지 -> `review` (`CONFLICTING_EVIDENCE`).
- **Issue #1**: API 작성자는 agriggio이나 원본 발언자는 Gaaned92 -> `review` (`INSUFFICIENT_EVIDENCE`).
- **Discussion #525**: 본문 공백 및 단순 단문 댓글 -> `exclude` (`NO_SUBSTANTIVE_CONTEXT`).
- **이관 filler 이슈 (10건)**: `exclude` (`MIGRATION_PLACEHOLDER`).
- **Discussion #432, #446**: 릴리스 태그 생성 알림 단문 -> `exclude` (`RELEASE_STUB_ONLY`).
- **Discussion #436**: Announcements이나 nightly 시험 토론 존재 -> `review`.
- **Issue #517 ↔ Discussion #519**: 동일 본문이나 변환 이벤트 미확정 -> `possible_conversion` 관계 보존.

## 6. 스키마 및 입출력 계약

### 6.1 원문 검토 결정 (`curation-decisions.json`)
- 경로: `data/issues/curation-decisions.json`
- 스레드 지문(`thread_sha256`): 부모 및 **모든 저장된 댓글**의 `{record_key: file_sha256}`을 Canonical JSON으로 직렬화한 SHA-256 해시.
- `curated_content`: 원문 body 문자열의 Python 슬라이스 범위 `[char_start:char_end)`를 정확히 기록.

### 6.2 검색 후보 목록 (`search-candidates.json`)
- 경로: `data/issues/search-candidates.json`
- `candidate_id`: `github:artraweditor/ART:{issue|discussion}:{number}`
- `accepted_content`: 항상 `null`.
- `source_locations`: 부모 및 선택된 댓글의 원문 스냅샷 경로, file SHA, body SHA, 작성자(Actor) 정보 보존.
- `metadata`: `platform_fields`, `field_availability`, `limitations`, `evidence`, `relations` 수록.

### 6.3 정제 보고서 (`filter-report.json`)
- 경로: `data/issues/filter-report.json`
- 495개 전체 스레드와 2,585개 전체 댓글의 결정 및 이유 코드 전수 기록.
- 입력 키 수지 및 카운트 수지 검증 보증.

## 7. CLI 실행 및 검증 결과

### 7.1 실행 명령어
```bash
# 가상환경 Python 경로 지정
PYTHON_BIN=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3

# 검색 후보 및 보고서 생성
"$PYTHON_BIN" scripts/filter_issues.py \
  --input-dir data/issues \
  --curation data/issues/curation-decisions.json \
  --output data/issues/search-candidates.json \
  --report data/issues/filter-report.json

# 변경 검증 모드 (--check)
"$PYTHON_BIN" scripts/filter_issues.py \
  --input-dir data/issues \
  --curation data/issues/curation-decisions.json \
  --output data/issues/search-candidates.json \
  --report data/issues/filter-report.json \
  --check

# 단위 및 통합 테스트 실행
"$PYTHON_BIN" -m pytest tests/test_filter_issues.py -v
```

### 7.2 실제 데이터 정제 집계 현황
```json
{
  "by_kind": {
    "issue": 465,
    "issue-comment": 2471,
    "discussion": 30,
    "discussion-comment": 114
  },
  "thread_count": 495,
  "include_count": 12,
  "exclude_count": 13,
  "review_count": 470,
  "candidate_count": 12,
  "stale_count": 0,
  "selected_comments_count": 23,
  "unselected_comments_count": 2562,
  "threads_without_accepted_answer_signal": 495
}
```

- 모든 후보의 본문 슬라이스가 원문 snapshot과 100% 일치함을 기계 검증 완료.
- 입력 레코드 키 3,080개 수지 100% 일치 확인.

## 8. 후속 작업 인계 사항

1. **Task 8-1 (골든 Q&A 작성)**:
   - `search-candidates.json`에 포함된 12개 후보 ID(`candidate_id`)와 해당 후보의 `curated_content` 및 `source_locations`만을 허용된 정답 원문 위치로 사용해야 한다.
   - `review` 상태인 470개 항목은 검증되지 않았으므로 정답 원문으로 사용하지 않는다.
2. **Task 8-2 / Task 9 (청킹 및 벡터 저장소 구축)**:
   - 본 정제 단계의 결과물은 검색 후보 목록이며 청크 직렬화 파일이 아니다.
   - 각 후보는 `candidate_id`, `thread_sha256`, 그리고 선택된 원문 조각 목록(`curated_content`)을 제공하므로, 이후 청킹 시 `ref_id` 및 원문 위치를 추적할 수 있다.
3. **Task 10-2c (증분 갱신 및 재검토)**:
   - 원격 수집(T10-1)으로 스레드에 새로운 댓글이 추가되거나 원문이 변경되면 해당 스레드의 `thread_sha256`이 변경되어 자동으로 `STALE_CURATION` 상태가 된다.
   - 변경된 스레드는 자동으로 제외되거나 잘못된 후보로 방치되지 않고 `review` 목록으로 넘어가 재검토를 유도한다.
