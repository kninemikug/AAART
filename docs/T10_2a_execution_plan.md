# Task 10-2a 실행 플랜 — Issues·Discussions 정제

작성일: 2026-09-28 · 구현 담당: Antigravity(Gemini 3.8 Flash)

이 문서는 실제로 읽은 T10-1 스냅샷을 근거로 A-10 (2/4)의 구현 계약을 정한다. 이번 커밋은 계획 문서만 추가한다. 아래 구현·테스트·후보 생성 체크리스트는 다음 단계에서 Antigravity가 수행한다.

## 1. 범위와 완료 조건

권위 문서는 [WBS v2.5 §5](ART_agentic_wbs.md), 상세 완료 조건은 [tasks/todo.md의 Task 10-2a](../tasks/todo.md#task-10-2a-수집한-issuesdiscussions-정제-a-10-24)이다.

- 입력: `data/issues/sync-state.json`과 그 파일이 가리키는 원문 JSON.
- 결과: 재현 가능한 정제 규칙, 검색 후보 목록, 포함·제외·보류 근거, 후보에서 원문으로 돌아가는 연결.
- 닫힘·작성자 소속·반응 수·마지막 댓글만으로 해결 여부를 결정하지 않는다.
- 원문 검토 결정을 데이터로 기록한다. Antigravity가 아래 사례를 읽고 결정 파일을 작성하며, 구현 중 별도 사용자 승인을 기다리는 절차를 추가하지 않는다.
- T8-1에 후보 ID와 허용 가능한 원문 위치를 제공한다. 질문 15개·정답 답변 작성은 T8-1의 작업이다.
- 청킹·오버랩·청크 직렬화·임베딩 모델·Chroma 적재·변경분 반영은 T8-2/T9/T10-2c의 작업이다. 여기서 정하는 JSON은 **검색 후보 목록**의 형식이며 청크 형식이 아니다.
- T10-1 수집기, 원문, 동기화 상태, ART C++ 코어를 수정하지 않는다. 추가 Python 의존성이나 `requirements.txt`도 필요 없다.

구현 완료의 필수 조건:

1. 모든 입력 객체가 검증되고 모든 스레드에 `include / exclude / review` 중 하나의 결정이 있다.
2. 포함 후보의 모든 본문 조각을 지정된 JSON 필드·문자 범위에서 그대로 복원할 수 있다.
3. 실제 확인된 신호와 수집하지 않은 신호를 구별하며, 포함 근거에 닫힘 상태만 사용한 후보가 없다.
4. 고정 실제 샘플·경계 조건·CLI 테스트가 통과하고 같은 입력의 재실행 출력이 바이트 단위로 같다.

## 2. 실제 데이터 조사 결과

### 2.1 조사 기준과 전수 구조 검사

계획 작성 시 `sync-state.json`을 파싱하고 `snapshots/**/*.json` 3,080개를 모두 파싱했다. 키·타입·상태·소속·반응·원문 길이·부모 연결을 집계했으며, 아래 대표 스레드는 본문과 댓글을 직접 읽었다.

| 항목 | 실제 값 |
|---|---|
| 조사 시점의 Git HEAD | `2f4124606` |
| 상태 형식 / 저장소 | `version: 1` / `artraweditor/ART` |
| `last_synced_at` | `2026-09-28T02:06:12Z` |
| Issue / Issue 댓글 | 465 / 2,471 |
| Discussion / Discussion 댓글 | 30 / 114 |
| 원문 JSON 바이트 합계 | 8,245,782 bytes |
| 상태 레코드 / 실제 파일 | 각각 3,080개 |
| 미등록 파일 / 없는 파일 / 중복 저장 경로 | 각각 0 |
| 레코드 키·객체 ID·URL·수정 시각과 원문의 불일치 | 0 |
| Issue 댓글 부모 누락 / Discussion 댓글 부모 누락 | 각각 0 |
| Issue의 `comments` 값과 저장된 댓글 수의 불일치 | 0 |

입력 고정용 실제 해시:

- `sync-state.json` 파일 SHA-256: `0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187`
- 스냅샷 매니페스트 SHA-256: `52b6cdf587e1f5ed12d80570a41a476ef02dd6e2118c9a9c09a871e7889d01c5`

매니페스트 계산 계약은 `{상태 디렉터리 기준 POSIX 상대 경로: 파일 바이트의 SHA-256}`을 `json.dumps(mapping, sort_keys=True, separators=(",", ":"))`로 UTF-8 인코딩하고 다시 SHA-256을 계산하는 것이다. 경로는 현재 모두 ASCII다. 상태 파일 해시와 원문 매니페스트 해시는 별개로 남긴다.

이 수치는 **이번 입력 범위의 내부 일관성**을 확인한 결과다. Discussion에는 댓글 총수·답글 계층이 없어 원격 전체 수집 완료를 증명하지 못한다. 수집기는 현재 파일을 덮어쓰고 삭제 탐지·과거 버전 보존을 하지 않는다. `last_synced_at`은 수집 시작 시각으로 기록되므로 완전성·해결 시점으로 해석하지 않는다.

### 2.2 상태 파일과 ID의 실제 의미

`sync-state.json`은 다음 구조다. 레코드 값의 키 5개는 실제 객체에서 확인했다.

```json
{
  "version": 1,
  "repository": "artraweditor/ART",
  "last_synced_at": "2026-09-28T02:06:12Z",
  "records": {
    "issue:500": {
      "kind": "issue",
      "object_id": "500",
      "source_url": "https://github.com/artraweditor/ART/issues/500",
      "storage_path": "snapshots/issues/500.json",
      "updated_at": "2026-06-16T10:07:18Z"
    }
  }
}
```

위는 레코드 하나만 발췌한 예다. 실제 원문과 시각까지 대조한 뒤 사용한다.

| 종류 | 상태 레코드 키 / `object_id` | 파일명 | 원문 객체 ID |
|---|---|---|---|
| Issue | `issue:{number}` / number 문자열 | `issues/{number}.json` | REST `id` 정수와 `number` 정수는 서로 다름 |
| Issue 댓글 | `issue-comment:{id}` / id 문자열 | `issue-comments/{id}.json` | REST `id` 정수 |
| Discussion | `discussion:{id}` / GraphQL id | `discussions/{number}.json` | `id` 문자열, `databaseId` 정수, `number` 정수 |
| Discussion 댓글 | `discussion-comment:{id}` / GraphQL id | `discussion-comments/{databaseId}.json` | `id` 문자열, `databaseId` 정수 |

Discussion 댓글의 수집기에는 `databaseId`가 없을 때 GraphQL ID를 안전한 파일명으로 바꾸는 경로도 있다. 필터는 파일명에서 ID를 추측하지 않고 상태 레코드와 원문을 대조한다.

### 2.3 실제 원문 필드

각 행의 필드는 해당 종류의 **모든 실제 파일**에서 확인했다. 존재하는 키의 값이 null인 것과 아예 수집하지 않은 필드를 구별한다.

| 종류 | 실제 필드와 타입 | 중요한 부재·한계 |
|---|---|---|
| Issue, 465개 | `number/id:int`, `node_id/title/body/state/html_url/url/created_at/updated_at/author_association:str`, `state_reason/closed_at:str 또는 null`, `user:object`, `closed_by:object 또는 null`, `labels:list[object]`, `comments:int`, `reactions:object` | 채택 답변 필드·종료 사유 이벤트·수정 커밋의 검증 결과 없음. `pull_request` 키는 현재 0개 |
| Issue 댓글, 2,471개 | `id:int`, `node_id/body/html_url/url/issue_url/created_at/updated_at/author_association:str`, `user/reactions:object`, `minimized:null`, `pin:object 또는 null` | `state/title` 없음. `minimized`는 전부 null이므로 숨김·스팸의 양성 증거가 아님 |
| Discussion, 30개 | `id/title/body/url/createdAt/updatedAt:str`, `databaseId/number:int`, `author:{login:str}`, `category:{name:str}` | `state/closed/isAnswered/answer/answerChosenAt/answerChosenBy/authorAssociation/author_association/reactions` 모두 없음 |
| Discussion 댓글, 114개 | `id/body/url/createdAt/updatedAt:str`, `databaseId:int`, `author:{login:str}` | `isAnswer/answerChosen/authorAssociation/author_association/reactions/replyTo` 모두 없음 |

REST의 `url`은 API URL이다. 후보의 웹 URL은 `html_url`을 사용한다. GraphQL은 `url`이 웹 URL이다. REST `user`에서는 `login`·`type`을, `labels`에서는 `name`을 사용한다. 그 외 아바타·알림 URL 같은 필드는 검색 본문에 넣지 않는다.

REST `reactions`에는 `total_count`, `+1`, `-1`, `laugh`, `hooray`, `confused`, `heart`, `rocket`, `eyes`, `url`이 있다. 반응은 인기도 보조 정보이고 정답·수정 확인 신호가 아니다.

Discussion의 채택 답변 신호 부재는 현재 수집기의 GraphQL 조회 필드와 일치한다. **미채택·미해결이라는 뜻이 아니다.** 이번 버전의 `accepted_content`는 항상 null이며 Discussion의 채택 여부는 `not_collected`로 남긴다. 플랫폼 채택 답변 지원이 필요해지면 별도 수집 작업과 스키마 변경으로 처리한다.

### 2.4 내용·신호 분포

- Issue: closed 382, open 83. `state_reason`은 completed 378, not_planned 4, null 83이다.
- 댓글 없는 Issue 47개 중 closed 30, open 17이다. 종료 상태와 답변 존재는 독립적이다.
- Issue 작성자 소속: COLLABORATOR 339, NONE 120, CONTRIBUTOR 6.
- Issue 댓글 소속: COLLABORATOR 2,166, NONE 295, CONTRIBUTOR 10.
- 반응 0인 Issue 457개, 반응 있는 Issue 8개. 댓글은 각각 2,432개와 39개다. 임계 반응 수 필터는 대부분의 유용한 원문을 버린다.
- Issue 댓글의 pin은 2,470개가 null, 1개가 객체다. 고정 여부도 해결·채택 신호로 사용하지 않는다.
- Discussion 분류: General 13, Ideas 9, Q&A 4, Announcements 3, Show and tell 1.
- Discussion 댓글 없는 항목은 #432, #446, #496이다. body가 빈 Discussion은 #525 한 개다.
- Issue·Issue 댓글·Discussion 댓글의 body는 모두 비어 있지 않은 문자열이다.
- Issue label은 bug 238, major 144, minor 127, enhancement 50, trivial 44, proposal 35, blocker 8, task 6, critical 6이다. 여러 label이 공존하므로 합계가 Issue 수와 같지 않다.

**이관 작성자 함정:** Issue 328개는 `**[Original report](https://bitbucket.org/agriggio/art/issues/...) by ...**` 머리말이 있다. Issue 댓글 1,900개는 `**Original comment by ...**` 머리말이 있고 이들의 REST `user.login`은 모두 agriggio다. 머리말의 GitHub 링크 기준으로 795개는 agriggio, 375개는 다른 사용자, 730개는 GitHub 링크가 없다. 따라서 이 1,900개를 API 작성자 소속만 보고 프로젝트 관계자의 답변으로 취급하면 안 된다. 표시 이름과 GitHub 로그인도 같은 식별자가 아니다.

**이관 filler:** #84, #293, #295, #297, #301, #302, #303, #315, #319, #323의 body는 정확히 `filler issue created by bitbucket_issue_migration`이다. 동일 body인 Issue 10개는 중복 기술 보고가 아니라 placeholder다.

### 2.5 URL·댓글 연결에서 발견한 예외

Discussion 30개의 URL은 모두 다음 형식이고, 댓글 114개는 다른 형식이다.

```text
부모: https://github.com/orgs/artraweditor/discussions/420
댓글: https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528
```

- 부모 웹 URL의 문자열 prefix로 댓글을 연결하면 모두 누락된다.
- Issue 댓글은 `issue_url`의 `/repos/artraweditor/ART/issues/{number}`로 연결하고, `html_url`의 번호·댓글 fragment를 교차 검사한다.
- Discussion 댓글은 허용된 두 Discussion 경로에서 번호를 파싱해 같은 저장소 입력의 Discussion에 연결한다. 웹 URL은 각각 원문 값을 그대로 보존한다.
- `https`, `github.com` 또는 REST의 `api.github.com`, 정확한 조직·저장소 경로, 양의 정수 번호를 검사한다. 다른 저장소·비슷한 prefix·임의 쿼리의 숫자로 연결하지 않는다.
- GraphQL 댓글 `id`는 후보의 원문 ID이고, `databaseId`는 fragment의 숫자와 교차 검사한다.
- Discussion 수집기는 최상위 댓글과 replies를 평탄화한다. `replyTo`가 없어 시간순 인접만으로 직접 답글 관계를 만들 수 없다. `(createdAt, id)` 정렬은 표시 순서일 뿐 확인 대상 연결의 증거가 아니다.

## 3. 정제 원칙과 구체적인 결정 규칙

### 3.1 검색 후보와 보류 항목을 구별한다

기본 처리 단위는 부모와 저장된 모든 댓글로 구성된 **스레드**다. 후보는 스레드당 최대 하나이고, 선택한 복수의 원문 조각을 포함한다.

| 결정 | 출력 | 조건 |
|---|---|---|
| `include` | 검색 후보와 보고서 | 유효한 원문 검토 결정에 구체적 증거·선택 본문·적용 한계가 있음 |
| `exclude` | 보고서에만 남김 | 정확한 placeholder·빈 내용·단순 확인 글 또는 원문 검토로 확정한 노이즈·중복 |
| `review` | 보고서에만 남김 | 증거 부족, 답변 없음, 작성자 불명확, 상충, 변경된 검토 결정, 아직 검토하지 않은 유효한 스레드 |

정제 대상에 unresolved 보고를 남길 수 있지만, 이를 자동으로 답변 후보에 넣지 않는다. 환경·재현 방법·증상과 불확실성이 원문 검토로 확인된 경우에만 `unresolved_report` 후보로 명시적으로 포함할 수 있다. 초기 포함 사례에는 이런 항목을 넣지 않는다.

### 3.2 포함에 사용할 신호

아래 신호는 필터의 자동 정답 판정 점수가 아니다. Antigravity가 전체 스레드와 후속 반례를 읽고 `curation-decisions.json`에 신호와 증거 위치를 기록한다. 필터는 그 기록의 원문 일치·규칙·재현성을 검증한다. 키워드만 검출한 결과는 `suggested_signals`로 보고서에만 남긴다.

| 신호 코드 | 필요한 증거 | 후보 상태 |
|---|---|---|
| `ACTIONABLE_GUIDANCE` | 원문에 조작 대상과 수행 방법이 명시됨. 예: 외부 편집기 wrapper 스크립트와 설정 방법 | `curated_guidance` |
| `ART_TECHNICAL_EXPLANATION` | 질문에 대응하는 구체적 ART 동작·제약 설명. 짧아도 포함 가능 | `curated_guidance` |
| `SELF_CONTAINED_TECHNICAL_GUIDE` | 부모 body 자체에 실행 단계·환경·대상이 있음. 댓글 수가 필수 조건이 아님 | `curated_guidance` |
| `USER_CONFIRMED_ACTION` | 같은 조치에 대해 작성자 또는 독립 시험자가 무엇을 바꿨고 어떻게 동작했는지 구체적으로 확인함 | `curated_guidance` 또는 `reported_fix` |
| `FIX_VERSION_CONFIRMED` | 수정 제안과 이후 성공 보고가 같은 버전·커밋·빌드 또는 명확한 동일 조치에 연결됨 | `reported_fix` |
| `DETAILED_UNRESOLVED_REPORT` | 증상, 환경, 재현 경로와 미해결·상충 상태를 함께 선택함 | `unresolved_report` |

확인 규칙:

1. `closed`, `completed`, `closed_by`, `[Solved]` 제목, COLLABORATOR, 많은 반응, 마지막 댓글이라는 조건은 독립 포함 근거가 될 수 없다.
2. `thanks`, `Thank you so much!`, `I have got it. Thanks!`, `It does. Thanks!`처럼 적용한 조치가 불명확한 문장을 단독 성공 확인으로 쓰지 않는다. 조치 연결이 전체 대화에서 명확하면 원문 검토 근거를 별도로 기록한다.
3. `fixed / solved / works / can confirm` 같은 단어는 조치·대상·시점을 검토해야 한다. `not fixed / still crashes / could not reproduce`와 인용된 과거 성공을 구별한다.
4. 수정 커밋·버전이 원문에 없으면 만들어 넣지 않는다. `latest master / nightly`는 게시 시점의 표현이며 현재 최신 버전의 보장이 아니다.
5. 반대 증거가 있으면 대응하는 제한을 같은 후보에 포함하거나 `review`로 보낸다. 최종 성공 보고가 있어도 이전 실패·적용 조건을 삭제해 일반적인 성공으로 바꾸지 않는다.
6. 원문 검토 결정은 어떤 댓글이 어떤 조치를 확인하는지 `content_index`와 명시적 `confirms_content_index`로 연결한다. 평탄화된 Discussion에서 자동으로 직전 댓글을 확인 대상으로 삼지 않는다.

### 3.3 작성자·플랫폼 신호 사용

- 네이티브 Issue 댓글의 `author_association`은 출처 정보로 보존한다. COLLABORATOR라도 단순 질문·예정 답변이면 포함 근거가 없다. NONE의 구체적인 재현·성공 보고는 유효한 증거가 될 수 있다.
- 네이티브 Discussion의 `author.login`만으로 소속을 생성하지 않는다. agriggio의 기술 설명도 `curated_guidance`이며 플랫폼 채택 답변이라고 부르지 않는다.
- Bitbucket 이관 머리말은 body **맨 앞**에서만 인식한다. 최초 빈 줄과 구분선까지의 형식을 검증한 뒤 원본 표시 이름·GitHub 링크·Bitbucket 링크를 추출한다.
- `api_login`과 `original_github_login/original_bitbucket_login/original_display_name`을 별도 보존한다. 이관 머리말도 원문에 적힌 주장이지 GitHub가 인증한 원본 소속이 아니다. 원본 소속은 null이다.
- 본문 중간이나 인용문에 있는 “Original comment by”는 이관 신호가 아니다. 불완전한 머리말은 `MIGRATION_AUTHOR_UNKNOWN`으로 기록한다.
- `reactions`는 실제 값만 보존한다. Discussion의 미수집 반응은 null이며 0으로 대체하지 않는다.
- `state_reason=not_planned`는 해결책 증거가 아니다. 구체적 대체 조치·동작 설명이 있다면 그 내용을 검토해 포함할 수 있다.
- `minimized=null`, `pin`, `locked`, label, category는 스팸·해결을 확정하지 않는다. 실제 봇 작성자는 현재 REST 자료에서 관찰되지 않았다.

### 3.4 노이즈·질문·중복 규칙

필터 우선순위는 입력 검증 → 변경된 검토 결정의 보류 → 구조적 제외 → 유효한 검토 결정 → 미검토 보류다. 손상된 입력을 노이즈로 숨기지 않는다.

| reason code | 판정과 처리 |
|---|---|
| `MIGRATION_PLACEHOLDER` | `body.strip()`이 실제 filler 문장과 정확히 같고 유의미한 댓글도 없으면 자동 제외. 댓글이 있으면 review |
| `NO_SUBSTANTIVE_CONTEXT` | 부모 body가 null/공백이고 댓글도 없거나 전부 확인 인사만이면 자동 제외. 제목만으로 문제·조치가 복원되지 않는 #525가 실제 사례 |
| `COMMENT_ACK_ONLY` | 댓글 전체가 제한된 확인 인사 목록과 일치하면 검색 본문에서 제외. 기술 내용을 뒤에 덧붙인 댓글은 제외하지 않음 |
| `NOT_SELECTED_BY_CURATION` | 검토한 스레드에서 의도적으로 선택하지 않은 댓글의 보고서 이유. 댓글의 오류·노이즈를 뜻하지 않음 |
| `OUT_OF_SCOPE_PR` | pull_request 키가 있는 부모와 연결된 댓글을 후보에서 제외. 현재 실제 입력에서는 0개 |
| `RELEASE_STUB_ONLY` | Announcements에서 #432의 release 생성 wrapper 또는 #446의 “New version just released”만 있고 기술 댓글도 없으면 자동 제외. #436처럼 설치·실행 논의가 있으면 review |
| `UNANSWERED_QUESTION` | 구체적 답변·자가 해결 절차가 없는 질문은 기본 review, 검색 목록에서 제외. 원문 검토 후 exclude로 확정 가능 |
| `FEATURE_REQUEST_ONLY` | 희망 기능·찬성·계획만 있고 현재 동작 설명·우회 방법이 없으면 검토 결정으로 제외. Ideas 전체를 일괄 제외하지 않음 |
| `SPAM_CONFIRMED` | ART와 무관한 광고·반복 홍보가 원문 검토로 확인되면 제외. 이번 조사에서 확정한 스팸 사례는 없으므로 광고 키워드·외부 링크만으로 자동 제외하지 않음 |
| `DUPLICATE_CONFIRMED` | 동일 사실·동일 범위이고 별도 근거가 없는 중복은 검토 결정에서 대표 스레드·이유를 지정해 제외 |
| `INSUFFICIENT_EVIDENCE` | “고쳤다”는 주장만 있거나 조치·대상이 불명확하면 review |
| `CONFLICTING_EVIDENCE` | 성공·실패·재현 불가 또는 서로 다른 진단이 남아 있으면 review, 혹은 상충 내용을 포함한 명시적 unresolved 후보 |
| `NOT_REVIEWED` | 아직 원문 검토 결정이 없는 유효한 스레드는 review |
| `STALE_CURATION` | 스레드 지문이 바뀐 검토 결정은 review. 이전 후보를 그대로 재사용하지 않음 |

확인 인사 목록은 `thanks`, `thank you`, `thank you so much`, `ok`, `ok thanks`, `+1`, `me too`, `i have got it thanks`, `ok i found it sorry guys`로 시작한다. 먼저 코드 fence·명시적 조작 내용이 없는지 확인하고, 비교용 텍스트에만 소문자화·공백 압축·양끝 및 문장부호 정리를 적용하여 **전체 일치**로 판정한다. `+1`은 문장부호 제거 전에 따로 비교한다. 원문·출력 본문을 이 방식으로 변경하지 않는다. `It does. Thanks!`는 맥락 확인이 필요하므로 자동 인사 목록에 넣지 않는다.

release wrapper 자동 제외는 실제 #432 형식의 본문 전체 일치로 제한한다. wrapper 뒤에 릴리스 설명이 있으면 자동 제외하지 않는다. 현재 “New version just released” 비교도 body 전체 일치다.

중복은 후보 ID 중복, 같은 스레드 안의 동일 원문 조각 중복, 별도 스레드의 유사 증상을 구별한다. 전역 body 해시만으로 서로 다른 부모·댓글을 합치지 않는다. Issue 댓글에는 정확히 같은 body를 가진 그룹이 28개 있지만 같은 인사·이관 형식일 수 있다.

- #516은 #503을 언급하지만 다른 카메라·빌드·캐시 문제와 성공 보고가 있다. 삭제하거나 #503에 병합하지 않는다.
- #524는 #510의 재발·후속 수정 기록이다. `follow_up_to` 관계로 보존하며 중복 제외하지 않는다.
- Issue #517과 Discussion #519는 body가 정확히 같아 전환 후보지만 수집된 변환 이벤트는 없다. `possible_conversion` 제안만 남긴다. 제목·body 일치만으로 변환을 확정하지 않는다.
- 중복 대표가 입력에 없거나 review/exclude 상태면 대표를 검색할 수 있다고 주장하지 않는다. 후보로 포함된 대표를 참조하는 중복 제외만 최종 확정한다.

### 3.5 본문을 선택하는 방법

선택은 원문 검토 결정의 문자 범위로 수행한다. 자동 요약·번역·의미 수정은 하지 않는다.

- `json.loads`로 얻은 body 문자열의 Python 문자 인덱스 `[start:end)`를 사용한다. 바이트 오프셋이 아니다.
- CRLF·Unicode·공백을 정규화하기 **전**의 문자열에 범위를 계산한다. 원문 file SHA와 body UTF-8 SHA를 모두 남긴다.
- 이관 머리말, 이메일 서명·알림 링크, 반복 알림 인용은 본문 조각에서 선택하지 않는다. 인사만 있는 댓글·단락을 독립된 기술 근거로 선택하지 않는다. 실제 #494 댓글과 Issue #511의 이메일 footer가 회귀 사례다.
- 코드 fence·명령·설정 키·경로·버전·원문 첨부 링크·적용 제한은 의미에 필요하면 그대로 포함한다. 코드 fence 중간을 잘라 불완전한 코드로 만들지 않는다.
- blockquote를 일괄 삭제하지 않는다. 인용은 맥락을 보여 줄 수 있지만 새 성공 보고로 집계하지 않는다.
- 첨부 이미지·영상·외부 링크를 다운로드하거나 실행하지 않는다. 링크만으로 조치가 복원되지 않으면 review다. 원문에 같이 적힌 설명은 선택할 수 있다.
- 별도 메타데이터의 rationale·limitations는 검토 설명이다. 실제 해결책 본문은 반드시 원문 조각이며 서로 구별한다.

## 4. 구현 시 먼저 고정할 실제 사례

### 4.1 초기 포함 결정 12개

다음 스레드 12개는 초기 검토 결정 파일의 필수 포함 사례다. 구현자가 전체 스레드를 다시 읽고 범위와 지문을 기록한다. 이것은 전체 495개 스레드의 최종 포함 수를 12개로 제한하는 조건이 아니다.

| 스레드 | 선택할 실제 근거 | 상태와 제한 |
|---|---|---|
| Issue #477 | 댓글 4428738434의 latest master 제안 + 4433310082의 실제 빌드·Sony A7 V 성공 보고 | reported_fix. 게시 당시 master이며 릴리스 버전·커밋을 추정하지 않음 |
| Issue #500 | 댓글 4711197631의 JXL export “visually lossless” 설명 | curated_guidance / ART_TECHNICAL_EXPLANATION. 짧은 질문·답변도 유용함 |
| Issue #516 | 댓글 5102797884의 빌드 환경, 5102851028의 AppImage·캐시·빌드 설명, 5103254495의 캐시 삭제 성공 | curated_guidance / USER_CONFIRMED_ACTION. #503과 병합 금지 |
| Issue #521 | 5309120735의 lensfun DB 경로 제안 + 5315824799의 `/usr/share/lensfun/version_1` 설정·동작 확인 | curated_guidance / USER_CONFIRMED_ACTION. 해당 시스템 경로이며 보편 경로로 제시하지 않음 |
| Issue #524 | 5648127070의 이전 nightly 실패, 5655898791의 새 nightly 제안, 5670040673의 b11089b-linux64 성공, 5670999476의 응답 | reported_fix / FIX_VERSION_CONFIRMED. #510과 follow_up_to 연결, 1.26.8 자체가 해결됐다고 쓰지 않음 |
| Discussion #412 | 부모의 MSYS2·Windows 빌드 단계. 15005389의 workflow 참고는 필요한 경우 보조 근거 | curated_guidance / SELF_CONTAINED_TECHNICAL_GUIDE. 댓글은 채택 답변 아님 |
| Discussion #420 | 댓글 15217528의 wrapper 전체 코드 + executable·preferences 설정 설명 | curated_guidance / ACTIONABLE_GUIDANCE. 15218439의 감사는 성공 확인 아님 |
| Discussion #424 | 댓글 15304221의 LUT 제약과 Local Editing → Smoothing의 Halation/Add noise 설명 | curated_guidance / ART_TECHNICAL_EXPLANATION. Ideas 분류지만 포함 |
| Discussion #440 | 댓글 15585143의 Rename/Move 설명 + 15591494의 “Works so far”와 동반 제한 | curated_guidance. XMP 이동 등 미확인 개선 요청은 구현 완료로 쓰지 않음 |
| Discussion #442 | 15597989의 mask 이름·뒤쪽 도구 제한 + 15603701의 copy/paste와 parametric mask 제약 | curated_guidance. 제한을 빼고 “모든 도구에서 재사용 가능”으로 바꾸지 않음 |
| Discussion #489 | 댓글 17042242의 rectangle mask, roundness 100% 방법 | curated_guidance / ACTIONABLE_GUIDANCE. Ideas·성공 댓글 없음이 자동 제외 사유가 아님 |
| Discussion #494 | 17204509의 Fedora 44·Flatpak 환경, 17204587의 AppImage 제안, 17207510의 실행 성공 본문 | curated_guidance / USER_CONFIRMED_ACTION. 이메일 footer 제외, sandbox 원인은 추정임을 유지 |

### 4.2 반드시 보류·제외와 대조할 사례

| 스레드·댓글 | 기대 결과 |
|---|---|
| Issue #510 | closed/completed여도 댓글 5002278174는 향후 조사 약속뿐. 초기 review / INSUFFICIENT_EVIDENCE. 부모의 Noise Reduction off 관찰도 보편적인 수정으로 승격하지 않음 |
| Issue #511 | open. 5017181748은 사용자 우회 보고지만 5029155417에서 재현 불가, 5030525547에서 미해결 유지. 초기 review / CONFLICTING_EVIDENCE. 자동 성공·원인 확정 금지 |
| Issue #503 | “latest master에서 수정됐을 것”이라는 4874521835만으로 현재 수정 버전을 특정하지 않음. 초기 review / INSUFFICIENT_EVIDENCE |
| Issue #497 | tar.gz 대안 제안과 “I have got it. Thanks!”를 ART-cli 실행 명령 해결로 바꾸지 않음. 초기 review |
| Issue #1, 댓글 2507490549/2507490554 | API 작성자 agriggio지만 머리말의 실제 원본 발언자는 Gaaned92. 댓글의 “resolved with commit 9f6ea2b”는 reporter 주장. 초기 review; 관계자 검증으로 자동 승격 금지 |
| Issue #493 | 단순 감사 4606997959와 “Should be fixed now” 4610067970. 구체적 수정 버전·시험 없음. 초기 review |
| Discussion #525 | body 공백, 댓글 18524177은 “Ok I found it, sorry guys !”. 자동 exclude / NO_SUBSTANTIVE_CONTEXT |
| Discussion #432/#446 | 기술 설명 없는 release stub. 자동 exclude / RELEASE_STUB_ONLY |
| 이관 filler Issue 10개 | 자동 exclude / MIGRATION_PLACEHOLDER |
| Discussion #436 | Announcements라는 이유로 제외 금지. nightly 링크·404·서로 다른 빌드의 시험이 있으므로 초기 review |
| Discussion #496 | 댓글 없음. 현재 기능 답변이 없는 요청은 기본 review / UNANSWERED_QUESTION 또는 검토 후 FEATURE_REQUEST_ONLY |
| Issue #517 ↔ Discussion #519 | possible_conversion만 제안. 자동 변환·중복 제거 금지 |

미검토 나머지도 보고서에 남긴다. 후보 수를 늘리기 위해 포함 기준을 낮추지 않는다.

## 5. 원문 검토 결정 파일 계약

실제 필드를 수집하지 않았는데 해결 여부를 자동 추론하는 일을 막기 위해 **선택된 증거의 검토 결정**을 버전 관리한다. 별도 LLM 호출·자동 점수 임계값·설정 프레임워크는 만들지 않는다.

파일: `data/issues/curation-decisions.json`. 스레드 지문은 부모와 **모든 저장된 댓글**의 `{record_key: file_sha256}`을 §2.1과 같은 canonical JSON 방식으로 해시한다. 선택하지 않은 댓글도 지문에 포함하므로 새 반례가 추가되면 재검토된다.

필수 최상위 필드: `schema_version:1`, `rules_version:"t10-2a-v1"`, `repository`, `threads:object`.

각 스레드 결정:

| 필드 | 계약 |
|---|---|
| key | 정확한 상태 레코드 키: `issue:500` 또는 `discussion:D_...` |
| `thread_sha256` | 검토한 전체 스레드의 SHA-256 |
| `disposition` | include / exclude / review |
| `reviewed_by` / `rationale` | 비어 있지 않은 문자열. 실제 검토 주체를 기록하고 사람 검토로 가장하지 않음 |
| `reason_codes` | 규칙 문서의 코드 목록. include는 §3.2의 긍정 신호를 최소 하나 포함 |
| `knowledge_status` | include일 때 curated_guidance / reported_fix / unresolved_report. 그 외 null |
| `curated_content` | include일 때 최소 2개: 부모 context와 기술 근거. record_key·role·char_start·char_end를 기록 |
| `evidence` | signal과 근거의 content_index. 확인 신호에는 confirms_content_index도 필수 |
| `limitations` | 코드·설명·content_indices 목록. 버전·플랫폼·추정·반례를 관련 원문과 연결 |
| `relations` | relation·target_record_key·reason. relation은 follow_up_to / related_to / duplicate_of / possible_conversion. 기본은 빈 배열 |

role은 `context / guidance / explanation / reported_fix / reproduction / confirmation / caveat` 중 하나다. 부모 context는 반드시 선택한다. char_start/end는 bool을 제외한 정수이며 `0 <= start < end <= len(body)`여야 한다. reported_fix는 수정 제안과 성공 확인을 함께 선택한다. unresolved_report는 미해결·상충 원문을 caveat로 함께 선택한다. 범위 중복은 같은 record_key 안에서 허용하지 않으며 필요하면 합친다.

limitations의 code는 `AS_OF_SOURCE_ONLY / PLATFORM_SPECIFIC / VERSION_SPECIFIC / HYPOTHESIS / COUNTEREVIDENCE` 중 하나다. 미확인 원인에는 HYPOTHESIS, 이전 실패에는 COUNTEREVIDENCE를 사용한다. include는 최소 하나의 한계와 관련 content_indices를 기록한다. evidence·limitations의 인덱스는 curated_content 배열을 가리키며 양의 확인 신호의 대상은 선택된 조치 또는 수정 내용이어야 한다.

같은 입력에서 그대로 사용할 수 있는 Issue #500 예:

```json
{
  "schema_version": 1,
  "rules_version": "t10-2a-v1",
  "repository": "artraweditor/ART",
  "threads": {
    "issue:500": {
      "thread_sha256": "c51769f25343d903c59f612ddb96e8546e038415b3e65933124e587a099ca4c0",
      "disposition": "include",
      "reviewed_by": "Antigravity",
      "rationale": "JXL export 품질 설정에 직접 답하는 기술 설명이다.",
      "reason_codes": ["ART_TECHNICAL_EXPLANATION"],
      "knowledge_status": "curated_guidance",
      "curated_content": [
        {"record_key": "issue:500", "role": "context", "char_start": 0, "char_end": 219},
        {"record_key": "issue-comment:4711197631", "role": "explanation", "char_start": 0, "char_end": 67}
      ],
      "evidence": [
        {"signal": "ART_TECHNICAL_EXPLANATION", "content_index": 1}
      ],
      "limitations": [
        {"code": "AS_OF_SOURCE_ONLY", "note": "게시 당시 동작 설명이며 이후 버전의 보장이 아니다.", "content_indices": [1]}
      ],
      "relations": []
    }
  }
}
```

위 예시는 형식과 실제 범위를 보여 주는 계획 자료다. 다음 구현자가 직접 검토한 후 자신의 결정 파일에 기록한다.

오류 처리:

- 결정 파일이 없거나 JSON·버전·repository·타입·코드가 잘못되면 실패한다. 초기 구현 단계에서는 명시적인 `threads:{}` 파일로 인벤토리·보류 경로를 시험한다.
- 존재하지 않는 스레드·다른 부모의 댓글·범위 밖 인덱스·허용되지 않은 상태/role/코드는 실패한다.
- 현재 스레드 지문과 다른 결정은 먼저 STALE_CURATION/review로 전환한다. 이전 오프셋을 적용하지 않고 출력 후보를 만들지 않는다. 해당 결정의 원문 참조가 삭제·변경된 경우도 이 경로를 따른다.
- exclude 중복 결정의 대표가 실제 include 후보인지 최종 검증한다. 관계 순환·자기 참조·다른 저장소 참조는 실패한다.
- 구조적 제외 대상과 include 결정이 충돌하면 실패하고 원문 검토 결정을 수정한다. 조용히 어느 한쪽을 우선하지 않는다.

## 6. 검색 후보와 원문 위치 스키마

파일: `data/issues/search-candidates.json`. UTF-8 JSON 한 개이며 다음 wrapper를 사용한다.

```json
{
  "schema_version": 1,
  "rules_version": "t10-2a-v1",
  "repository": "artraweditor/ART",
  "input_manifest": {
    "last_synced_at": "2026-09-28T02:06:12Z",
    "sync_state_sha256": "0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187",
    "snapshot_manifest_sha256": "52b6cdf587e1f5ed12d80570a41a476ef02dd6e2118c9a9c09a871e7889d01c5",
    "curation_sha256": "<실제 결정 파일 바이트의 SHA-256>",
    "snapshot_count": 3080,
    "thread_count": 495
  },
  "candidates": []
}
```

각 후보의 필수 필드:

| 필드 | 타입·정확한 의미 |
|---|---|
| `candidate_id` | `github:artraweditor/ART:{issue 또는 discussion}:{number}`. 내용·상태·규칙 버전 변경에도 같은 스레드의 ID 유지 |
| `source_type` | issue / discussion |
| `source_id` | Issue는 REST raw.id의 문자열, Discussion은 GraphQL raw.id. number와 혼용 금지 |
| `source_number` | 양의 정수 |
| `source_record_key` | sync-state의 부모 레코드 키 |
| `url` / `title` | 부모 웹 URL / 원문 title. 그대로 보존 |
| `accepted_content` | 이번 스키마에서는 null만 허용. 채택 답변을 만들어 내지 않음 |
| `curated_content` | 선택된 순서의 원문 조각 배열. role·ref_id·json_pointer·char_start/end·text |
| `source_locations` | 부모와 선택된 댓글의 원문 위치 배열. ref_id는 후보 안에서 유일한 record_key |
| `metadata` | 아래 출처·판정·한계 정보 |

`source_locations`의 각 항목은 `ref_id / source_kind / source_id / source_number / database_id / url / snapshot_path / file_sha256 / body_sha256 / created_at / updated_at / actor`를 가진다. source_number는 댓글에도 부모 번호를 기록한다. database_id는 Issue·댓글은 REST id의 문자열, GraphQL은 databaseId의 문자열 또는 null이다.

`snapshot_path`는 `data/issues` 기준 상대 경로다. `ref_id`와 snapshot_path를 통해 상태 파일을 다시 찾을 수 있다. `actor`는 `api_login / api_association / origin / original_display_name / original_github_login / original_bitbucket_login / original_association`을 보존한다. 수집하지 않은 값·원본 소속은 null이다. origin은 native / bitbucket_migration / migration_unknown이다.

`metadata` 필수 키:

- `knowledge_status`, `selection_method:"reviewed_snapshot"`, `reason_codes`, `evidence`, `reviewed_by`, `rationale`, `limitations`, `relations`.
- `thread_sha256`, `thread_updated_at`(저장된 스레드 객체 updated 시각의 최댓값).
- `platform_fields`: 부모의 state·state_reason·author_association·labels·category·reactions. 존재하지 않는 값은 null. labels는 이름 목록이며 없는 label 필드도 빈 배열로 위장하지 않는다.
- `field_availability`: 해당 플랫폼 필드의 수집 여부를 각각 boolean으로 기록. null인 관측 값도 availability는 true일 수 있다.
- `accepted_answer_availability`: Issue는 not_applicable, 현재 Discussion은 not_collected.

Issue #500에서 생성되어야 할 실제 값과 조각 예:

```json
{
  "candidate_id": "github:artraweditor/ART:issue:500",
  "source_type": "issue",
  "source_id": "4667542094",
  "source_number": 500,
  "source_record_key": "issue:500",
  "url": "https://github.com/artraweditor/ART/issues/500",
  "title": "question: absolute no settings for jxl export?",
  "accepted_content": null,
  "curated_content": [
    {
      "role": "context",
      "ref_id": "issue:500",
      "json_pointer": "/body",
      "char_start": 0,
      "char_end": 219,
      "text": "Is it right, that there are no export options for jxl and the other export formats?\n\nThe exported quality seems to be good, but i can't see, which options, quality, color-subsampling (4:4:4, 4:2:2) is set ...\n\nThank you"
    },
    {
      "role": "explanation",
      "ref_id": "issue-comment:4711197631",
      "json_pointer": "/body",
      "char_start": 0,
      "char_end": 67,
      "text": "Yes, there's no option. The quality is fixed to \"visually lossless\""
    }
  ]
}
```

위 예제는 후보 본체의 주요 필드 발췌다. 완전한 출력에는 필수 source_locations와 metadata를 추가한다. 이 예제의 원문 해시는 다음 값과 일치한다.

| 원문 | file_sha256 | body_sha256 |
|---|---|---|
| `snapshots/issues/500.json` | `210e95a36a0726bbb7fbb3ee1949cd8af571367cc44127228c5ea6360506bc8f` | `590abe7e573eb2a063c3d46872800ad348b60282ff79ed4ee0eb9edbd12bff76` |
| `snapshots/issue-comments/4711197631.json` | `32dcb0afb1e0f5a456a78c7d3e16a4b512ad1d244b58f75af53a1895147d8cad` | `1a72636b6373fabc9ebbd0e99ee806d629fcf943837d8059a87a247e14473dc2` |

모든 후보에 다음 원문 왕복 검증을 수행한다.

`candidate → source_record_key/ref_id → state.records → snapshot_path → raw ID/URL → raw["body"][start:end] == text`

부모 제목도 raw["title"]과 대조한다. 이번에 허용하는 본문 pointer는 `/body`뿐이다. 다른 JSON 필드를 본문으로 사용하지 않는다.

보고서: `data/issues/filter-report.json`. 후보 목록과 같은 schema_version/rules_version/input_manifest에 `counts`와 `threads`를 추가한다.

- counts: source_kind별 입력 수, 스레드 수, include/exclude/review 수, 후보 수, stale 수, 선택/비선택 댓글 수, 채택 답변 신호 미수집 스레드 수.
- threads: 전체 495스레드를 한 번씩 열거한다. record_key·source URL·snapshot_path·thread_sha256·decision·reason_codes·candidate_id(미포함이면 null)·suggested_signals·전체 댓글의 comment_decisions를 기록한다.
- comment_decisions: record_key·URL·snapshot_path·selected/ignored/review·reason_codes. 같은 댓글에서 여러 범위를 선택해도 선택 댓글 수는 1이다.
- 미검토 댓글은 review, 확인 인사는 ignored/COMMENT_ACK_ONLY, 의도적으로 선택하지 않은 비노이즈 댓글은 ignored/NOT_SELECTED_BY_CURATION이다. 보고서에도 본문·메일 알림 URL 전체를 복제하지 않는다.
- `include + exclude + review == thread_count`, `candidate_count == include`, 부모와 전체 comment_decisions의 레코드 키 집합이 입력 레코드 집합과 같음을 검증한다.

같은 입력의 출력에 현재 시각·절대 경로·실행 소요 시간을 섞지 않는다. JSON 출력은 `ensure_ascii=False, indent=2, sort_keys=True`, 끝에 개행 1개다. 스레드·후보는 `(source_type, source_number)`, 댓글은 `(created_at, source_id)`, 위치 목록은 ref_id로 정렬한다. curated_content는 검토한 context→설명/조치→확인/제한 순서를 유지한다.

## 7. 모듈과 CLI

### 7.1 추가 파일과 책임

| 파일 | 책임 |
|---|---|
| `src/artagent/issue_filter.py` | 순수한 검증·정규화·부모 연결·신호 기록·결정 적용·후보 구성·원문 왕복 검증 |
| `scripts/filter_issues.py` | argparse, ROOT/src 추가, 입력 읽기, 출력 쓰기, 종료 코드. 기존 fetch_art_github.py 방식에 맞춤 |
| `tests/test_filter_issues.py` | unittest 또는 기존 pytest로 실행할 고정 데이터·경계·CLI 테스트 |
| `tests/fixtures/issue_filter/` | 실제 JSON 바이트를 복사한 고정 원문, 최소 state, 검증용 결정, manifest |
| `docs/issue_filter_rules.md` | 관찰 사실, 규칙, 예시, 코드, 재현 명령, 출력의 의미 |
| `data/issues/curation-decisions.json` | 초기 12건과 필요한 제외·보류의 원문 검토 결과 |
| `data/issues/search-candidates.json`, `data/issues/filter-report.json` | 실제 입력으로 생성한 후보와 전체 입력의 판정 목록 |

T10-1의 `src/artagent/issues.py`와 구분한다. 신규 모듈은 네트워크 클라이언트를 import하지 않는다. 표준 라이브러리로 구현하며 일반적인 플러그인·설정 로더·클래스 계층을 추가하지 않는다.

권장 함수 경계:

1. `load_sources(input_dir) -> SourceInventory`: state와 등록 원문을 읽는다. ID·URL·날짜·타입·파일 대응을 검증한다.
2. `build_threads(inventory) -> list[Thread]`: kind별 ID 규칙과 §2.5로 연결하고 전체 레코드를 정확히 한 번씩 소속시킨다.
3. `inspect_thread(thread) -> Inspection`: placeholder, 확인 인사, 이관 정보, 사용 가능한 신호, 검토할 관계를 열거한다.
4. `apply_curation(thread, inspection, decision_or_none) -> Decision`: 스레드 지문·증거 범위·긍정 근거·제약을 검증한다.
5. `build_candidate(thread, decision) -> dict`: 원문 slice를 그대로 후보로 구성하고 위치·metadata를 추가한다.
6. `validate_outputs(inventory, candidates, report) -> None`: 전체 후보의 왕복 검증·ID 유일성·전체 레코드 수지 일치를 확인한다.
7. `filter_corpus(input_dir, curation_path) -> (candidates_document, report_document)`: 위 함수를 순서대로 실행한다. 파일 출력은 CLI에서 수행한다.

SourceInventory/Thread 등은 필요한 항목만 가진 dataclass 또는 dict면 충분하다. 순수 함수에 표준 라이브러리 dict/list를 전달할 수 있는 테스트 경계를 유지한다.

### 7.2 CLI 계약

```text
python scripts/filter_issues.py
  --input-dir PATH
  --curation PATH
  --output PATH
  --report PATH
  [--check]
```

| 인자 | 기본값·동작 |
|---|---|
| `--input-dir` | ROOT/data/issues. 내부 sync-state.json과 snapshots를 입력으로 사용 |
| `--curation` | ROOT/data/issues/curation-decisions.json |
| `--output` | ROOT/data/issues/search-candidates.json |
| `--report` | ROOT/data/issues/filter-report.json |
| `--check` | 재계산·검증만 수행. 기존 output/report의 내용·바이트가 기대 출력과 일치하는지 확인하며 쓰지 않음 |

상대 경로 인자는 호출자 cwd 기준, 기본값은 스크립트 ROOT 기준이다. input-dir만 바꿔도 다른 기본값은 바뀌지 않으므로 고정 fixture나 다른 입력 시험에서는 모든 경로를 명시한다.

종료 코드: 0=생성/check 성공, 1=입력·결정·출력 검증 오류 또는 check 불일치, 2=argparse 인자 오류. review 잔여 항목은 정상 종료이며 stdout JSON 집계로 건수를 표시한다. 오류는 stderr에 안전한 상대 경로·record_key·이유를 출력하고 body·환경 변수·알림 링크는 출력하지 않는다.

I/O 계약:

- state.version==1, repository 일치, records 객체를 검사한다. ID는 bool을 int로 허용하지 않는다. null body/author는 내용 없음/불명 화자로 처리하지만 기타 잘못된 타입은 실패한다.
- raw 필수 필드는 kind에 맞는 ID/number·title(부모)·body 키·URL·created/updated 시각이다. author/association/reactions 등의 미수집은 기록하고 계속 처리할 수 있다. timestamp는 ISO-8601로 검증하고 UTC로 정규화해 비교한다.
- storage_path는 상대 경로이며 snapshots 내부여야 한다. 해석 후 입력 루트 밖을 가리키는 path traversal·symlink는 실패한다. 미등록·누락 파일, 여러 레코드의 동일 원문 경로, 부모 누락도 실패한다.
- 전체 레코드에서 state의 ID·URL·updated 시각과 원문을 대조한다. pull_request 키가 있는 부모는 먼저 PR로 식별하고 부모·댓글의 /pull/{number} 웹 경로를 검증한 후 모두 exclude/OUT_OF_SCOPE_PR로 보고한다. 부모 연결에는 REST issue_url의 /issues/{number}를 사용한다. 현재 실제 PR은 0이며 이 방어 경로는 synthetic fixture로 시험한다.
- output/report는 서로 다른 경로이며 state·curation·snapshots·fixture 입력에 덮어쓸 수 없다. 모든 계산·검증을 마치기 전에 쓰지 않는다.
- 두 출력을 각각 해당 출력의 부모 디렉터리 안 임시 파일에 준비한 뒤 replace한다. 기존 내용이 같으면 쓰지 않아 mtime도 유지한다. 여러 파일의 replace는 일괄 트랜잭션이 아니므로 check에서 두 input_manifest의 일치도 확인한다.
- 읽기 전후 state·원문·curation의 해시를 확인하고 계산 중 입력 변경은 실패시킨다. 동시 T10-1 수집의 중간 상태를 채택하지 않는다.

이 워크트리에는 `venv/`가 없음을 확인했다. 기존 루트 venv를 사용한다. 이번에 확인한 Python은 3.14.3이고 pytest는 [설정 기록](pipeline_setup.md)의 기존 의존성을 사용한다.

```bash
ART_PIPELINE_PYTHON=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
"$ART_PIPELINE_PYTHON" scripts/filter_issues.py --input-dir data/issues --curation data/issues/curation-decisions.json --output data/issues/search-candidates.json --report data/issues/filter-report.json
"$ART_PIPELINE_PYTHON" scripts/filter_issues.py --input-dir data/issues --curation data/issues/curation-decisions.json --output data/issues/search-candidates.json --report data/issues/filter-report.json --check
"$ART_PIPELINE_PYTHON" -m pytest tests/test_filter_issues.py -q
"$ART_PIPELINE_PYTHON" -m pytest -q
git diff --check
```

다른 환경에서는 ART_PIPELINE_PYTHON을 실제 루트 venv의 Python으로 바꾼다. 새 venv를 만들지 않는다.

## 8. 고정 fixture와 테스트 설계

### 8.1 fixture 작성 방법

- §4의 초기 12스레드와 경계 사례의 전체 댓글을 현재 실제 JSON에서 복사한다. 네트워크를 쓰지 않고 테스트는 변경 가능한 `data/issues/`에 의존하지 않는다.
- 경로는 `tests/fixtures/issue_filter/corpus/{sync-state.json,snapshots/...}`. state는 복사한 레코드만 원본 state에서 추출한다. 관련 댓글을 모두 유지하며 불리한 후속 댓글도 생략하지 않는다.
- fixture raw 파일은 원본 바이트 그대로, state는 최소화한 파생 파일이다. manifest에 원본 커밋·원본 상대 경로·원본 파일 SHA·fixture SHA·가공 여부를 기록한다.
- `tests/fixtures/issue_filter/curation-decisions.json`에 고정 결정을 둔다. 원문 offset/hash의 알려진 기대값을 직접 검증해 적고 구현 함수로 기대 출력을 생성하지 않는다.
- 기대값은 후보 ID 집합, 선택한 raw ID, role, 구체적인 본문 조각, 제외 이유, availability를 중심으로 검증한다. 큰 자동 golden 파일을 정답으로 간주하지 않는다.
- synthetic 사례는 fixture를 deepcopy하여 테스트 또는 TemporaryDirectory 안에서 변경하고 테스트 이름에 명시한다. 실제로 관찰한 채택 답변으로 취급하지 않는다.
- 테스트의 src 추가는 기존 `tests/test_github_issues.py` 방식에 맞춘다.

### 8.2 필수 테스트 행렬

| 테스트 이름 예 | 입력·기대 검증 |
|---|---|
| `test_actual_issue_500_schema_and_excerpt_roundtrip` | raw.id=4667542094와 number=500을 구별. 67문자 답변·URL·file/body SHA·본문 복원 일치 |
| `test_actual_discussion_420_has_no_accepted_signal` | wrapper 전체 보존, accepted_content=null, not_collected, 반응 null. 15218439는 확인 증거가 아님 |
| `test_actual_org_discussion_and_repo_comment_join` | 420의 org URL과 repo 댓글 URL을 같은 부모로 연결. 각각의 URL 보존 |
| `test_actual_idea_with_guidance_is_included` | 424/489를 Ideas라는 이유로 제외하지 않음. 15304221/17042242 선택 |
| `test_actual_short_explanation_is_not_length_filtered` | 500의 짧은 답변 보존. 최소 글자 수·최소 반응 수 기준 없음 |
| `test_actual_mask_limitations_are_preserved` | 442의 subsequent/pipeline·copy/paste·parametric 제약 원문 보존 |
| `test_actual_lensfun_path_confirmation` | 521의 5309120735→5315824799를 명시적으로 연결하고 version_1 보존 |
| `test_actual_build_and_cache_case_is_not_duplicate` | 516을 503에 합치지 않고 LibRaw:N/A·캐시 삭제 맥락 보존 |
| `test_actual_fix_and_counterexample_sequence` | 524의 이전 nightly 실패와 b11089b 성공 보존. 510 자동 승격 없음 |
| `test_actual_closed_issue_without_solution_is_review` | 510의 closed/completed·협력자 댓글만으로 후보를 만들지 않음 |
| `test_actual_unresolved_conflicting_report_is_review` | 511의 Mode=0만 성공 해결책으로 추출하지 않고 CONFLICTING_EVIDENCE |
| `test_actual_importer_is_not_original_speaker` | 1의 2507490549/2507490554: API agriggio, 원본 GitHub Gaaned92, 원본 association=null |
| `test_actual_empty_discussion_and_ack_is_excluded` | 525를 NO_SUBSTANTIVE_CONTEXT로 제외 |
| `test_actual_migration_filler_is_excluded` | 실제 filler 10개를 MIGRATION_PLACEHOLDER로 제외. 다른 스레드의 유용한 댓글과 합치지 않음 |
| `test_actual_release_stubs_and_substantive_announcement` | 432/446 제외, 436은 category만으로 제외하지 않고 review |
| `test_actual_email_footer_is_not_selected` | 494의 17207510 성공 문장 보존. 알림 token·unsubscribe·인용 알림 footer는 본문에서 제외 |
| `test_actual_possible_conversion_is_not_confirmed` | 517/519의 동일 body는 possible_conversion이며 확정 duplicate가 아님 |
| `test_synthetic_missing_author_and_null_body` | author=null/body=null에서 예외 없음. null body의 문자 범위 include는 생성 불가 |
| `test_synthetic_closed_association_reactions_are_not_sufficient` | curation 없이 closed/completed/COLLABORATOR·고반응으로 변경해도 include 아님 |
| `test_synthetic_open_case_can_have_reviewed_guidance` | 521을 open으로 바꾸고 결정 지문 갱신. 내용 근거가 있으면 include |
| `test_synthetic_quotes_and_crlf_offsets` | Unicode/CRLF raw body에서 slice 복원. 인용한 “works”를 새 확인으로 쓰지 않음 |
| `test_synthetic_same_text_different_sources_stay_distinct` | 다른 부모의 동일 본문을 전체 해시만으로 중복 제거하지 않음 |
| `test_synthetic_new_comment_invalidates_curation` | 비선택 댓글에 추가된 반례도 지문을 변경하여 STALE_CURATION, 이전 후보 없음 |
| `test_synthetic_invalid_reference_and_range_fail` | 다른 부모 댓글, 음수/역순/초과 offset, 없는 키, bool ID에서 실패 |
| `test_synthetic_manifest_integrity_and_unsafe_paths_fail` | 누락·미등록 원문, 잘못된 JSON, state 불일치, 부모 누락, ../·외부 symlink에서 실패 |
| `test_synthetic_other_repo_url_and_fragment_mismatch_fail` | 다른 owner/repo·ID·가짜 GitHub host·유사 org prefix URL을 오연결하지 않음 |
| `test_synthetic_duplicate_target_and_cycle_fail` | duplicate 대표 누락·미포함 대표·순환·자기 참조 거부 |
| `test_synthetic_pull_request_and_comments_are_excluded` | pull_request 키와 /pull URL이 있는 합성 부모 및 댓글을 OUT_OF_SCOPE_PR로 보고. 검색 후보 없음 |
| `test_cli_generation_check_and_mismatch` | subprocess 명시 경로 생성→check 성공→출력 한 문자 변경 후 check=1, 재기록 없음 |
| `test_cli_invalid_input_does_not_overwrite` | 잘못된 입력에서 종료=1, 기존 출력 바이트 유지. 입력 덮어쓰기 지정도 거부 |
| `test_synthetic_input_change_during_read_fails` | 읽기 중 state·원문·결정 파일을 변경하면 해시 대조로 실패하고 기존 출력 유지 |
| `test_cli_deterministic_order_and_unchanged_input` | state 레코드 순서를 바꿔도 후보 내용·ID 동일. state SHA 차이는 manifest에 반영. 동일 입력 두 번은 모든 출력 바이트·mtime 동일 |
| `test_all_candidates_and_report_records_roundtrip` | 전체 후보의 전체 span·title·URL·ID를 원문 JSON과 대조. 입력 키 수지·candidate 수=include·ID 유일성 |

후보 순수 데이터 비교와 file/state SHA를 포함한 전체 출력 비교를 구별한다. synthetic에서 raw를 바꾸면 state 대응 값·지문도 테스트 의도에 맞게 바꾼다. stale 테스트는 의도적으로 이전 지문을 유지한다.

## 9. docs/issue_filter_rules.md의 필수 구성

다음 순서로 기록하고 이 계획의 규칙 코드·스키마·CLI와 일치시킨다.

1. 목적·rules_version·대상 입력 날짜/커밋/해시.
2. 실제 종류별 필드·누락·상태/반응/이관 분포. 미수집과 false/null의 차이.
3. include/exclude/review, knowledge_status, 채택 근거와 금지 추론.
4. 긍정 증거·노이즈/질문/중복/보류 코드 목록과 우선순위.
5. 이관 원본 화자·Discussion URL 예외·답글 계층 부재의 제한.
6. 초기 포함 12건과 negative 예시. 원문 상대 경로·ID·web URL을 반드시 연결.
7. 검토 결정·후보·보고서의 필드와 ID·SHA·문자 범위 계약.
8. 재생성·check·fixture/CLI 테스트 명령과 실제 결과.
9. 전체 후보 원문 대조 결과, include/exclude/review 건수, 미검토·변경된 결정 건수.
10. 후속 작업 인계: T8-1 허용 원문 위치, T8-2 미결정 사항, T10-2c 재검토 조건.

## 10. Antigravity의 단계별 실행 체크리스트

WBS의 2h는 계획 시간이며 아래 수락 조건을 줄이는 이유로 사용하지 않는다. 예상 배분은 입력 계약 20분, 최소 후보 경로 25분, 규칙/판정 30분, 실데이터 검증/문서화 45분이다. 초과하면 실적과 잔여 작업을 보고하고 미완료 조건을 완료로 처리하지 않는다.

### Step 1 — 입력 고정과 fixture (의존 없음)

- [ ] §2의 state SHA·manifest SHA·종류별 수·URL 예외를 로컬에서 재계산해 일치 여부를 확인한다. 다르면 입력 변경을 기록하고 재조사한다.
- [ ] 원문 바이트를 fixture로 복사하고 최소 state·원본 SHA 대응 manifest를 만든다.
- [ ] Issue #500의 219/67문자·SHA·ID·thread SHA를 독립 검산한다.
- [ ] threads:{} 초기 결정 파일과 입력 검증·닫힘 비해결·ID 구별 테스트를 먼저 작성하고 미구현으로 실패함을 확인한다.

대상 파일: fixture, tests/test_filter_issues.py. 검증: 실제 fixture 구조·SHA 대조. 이 단계에서는 실제 입력에 필터를 적용하지 않는다.

### Step 2 — Issue #500 전체 경로 (Step 1에 의존)

- [ ] load_sources/build_threads와 필수 입력 검증을 구현한다.
- [ ] #500 결정을 기록하고 state→raw→결정→후보→원문 span 대조 경로를 구현한다.
- [ ] CLI로 TemporaryDirectory에 후보·판정 목록을 생성하고 check가 통과하게 한다.
- [ ] source_id/number·null 의미·입력 불변 테스트를 통과시킨다.

대상 파일: issue_filter.py, filter_issues.py, tests, 검토 결정. 검증: #500 고정 기대값·CLI 왕복 실행.

### Checkpoint 1

- [ ] 검토 결정 없이 closed/completed를 줘도 후보가 0이다.
- [ ] #500 원문 범위·URL·해시가 독립 고정 기대값과 같다.

### Step 3 — Discussion과 원본 화자 (Step 2에 의존)

- [ ] org/repo URL 연결과 GraphQL ID/databaseId 구별을 구현한다.
- [ ] #420을 추가하고 wrapper 전체·미수집 accepted/association/reactions를 검증한다.
- [ ] #1의 이관 화자, #494 이메일 footer, #442 적용 제약을 fixture로 검증한다.
- [ ] category·작성자·단어 수·반응 수를 일괄 포함 조건으로 쓰지 않음을 테스트한다.

대상 파일: 모듈, tests, 검토 결정. 검증: Discussion·이관·범위 복원 테스트.

### Step 4 — 노이즈·반례·변경 대비 (Step 3에 의존)

- [ ] filler, 빈 body+확인 인사, release stub의 제한된 자동 제외를 구현한다.
- [ ] #510/#511/#503/#497/#493을 보류하고 #516/#524를 잘못 중복 제외하지 않는다.
- [ ] 새 댓글·수정 댓글로 thread SHA가 바뀌면 이전 결정이 후보가 되지 않음을 검증한다.
- [ ] relation·range·path·state·입력 변경·output 덮어쓰기 오류 처리를 구현한다.
- [ ] 전체 부모·댓글의 판정 목록과 입력 수지 검증을 구현한다.

대상 파일: 모듈, tests. 검증: negative·synthetic 테스트.

### Checkpoint 2

- [ ] 마지막 댓글·닫힘만으로 성공·채택을 만들어 내는 사례가 없다.
- [ ] 후속 관계·보류·변경된 검토 결정을 보고서에서 추적할 수 있다.
- [ ] 집중 테스트가 통과한다.

### Step 5 — 전체 입력 재생성·규칙 기록 (Step 4에 의존)

- [ ] 초기 12후보의 전체 스레드를 다시 읽고 고정 offset·명시적 확인 대상·적용 제약을 결정 파일에 기록한다.
- [ ] 실제 3,080레코드/495스레드로 CLI를 실행하고 미검토 항목도 report에 남긴다.
- [ ] 포함 후보 전부를 원본 파일·state·원본 web URL 문자열과 대조한다. 현재 URL 도달성은 별개이며 네트워크 확인을 포함 판정 조건으로 쓰지 않는다.
- [ ] 전체 span 일치, ID/URL/부모 관계, 입력 수지, 닫힘만으로 포함 0, 채택 답변 날조 0을 기계 검증한다.
- [ ] 같은 입력을 두 번 생성해 바이트·mtime 불변과 check 성공을 확인한다.
- [ ] docs/issue_filter_rules.md에 실제 건수·source SHA·검증 결과·보류 범위를 기록하고 후보·결정·보고서를 같은 입력 범위로 저장한다.

대상 파일: 결정, 후보, 보고서, 규칙 문서. 검증: 전체 후보 원문 왕복 검증·check.

### Step 6 — 회귀 확인과 인계 (Step 5에 의존)

- [ ] §7의 집중 pytest, 기존 전체 pytest, git diff --check를 실행한다.
- [ ] 변경이 위 파일에 한정되고 src/artagent/issues.py·원문·sync-state·ART 코어가 바뀌지 않았음을 확인한다.
- [ ] 후보 ID 목록, 결정 이유, 검토 잔여 건, 미수집 신호, 원본 JSON 연결을 인계 문서에서 확인한다.
- [ ] T8-1은 include 후보만 사용한다고 명시한다. review 항목을 허용 정답 원문으로 전달하지 않는다.
- [ ] T10-2c에 안정적인 candidate_id·thread SHA·stale 재검토 규칙을 전달한다. 벡터 반영 상태를 sync-state에 섞지 않는다.
- [ ] 구현 결과·실행 명령·실제 건수·제한을 보고하고 실제 충족한 Task 10-2a 완료 조건만 완료로 기록한다.

## 11. 위험과 대응

| 위험 | 구체적 대응 |
|---|---|
| 미수집 채택·소속 정보를 추측 | availability 보존, accepted_content=null, 포함은 원문 검토 증거에 한정 |
| 이관 게시물 전부를 agriggio의 답변으로 해석 | API 화자와 원본 화자 구별, 원본 소속 null, 고정 회귀 사례 유지 |
| 과거 fixed/nightly를 현재 해결로 해석 | 원문 날짜·지문·버전 제한을 보존하고 보고된 수정으로 취급 |
| 성공만 선택하고 후속 실패 누락 | 전체 스레드 지문, 확인 대상 연결, caveat, negative fixture |
| 수집 갱신 중 중간 데이터 읽기 | 입력 해시 전후 대조, 전체 검증 후 출력, check로 정합성 확인 |
| 보수적인 규칙으로 적은 후보 | 실제 12건에서 시작하고 review 수 공개. 기준을 낮추지 않고 추가 검토로 확대 |
| 삭제된 원문이 로컬에 잔존 | 이번 수집 범위의 한계 기록. 삭제 탐지·원본 도달성 검증은 별도 수집 작업 |
