# Task 10-2c 실행 플랜 — GitHub 변경분 갱신·Chroma 반영

작성일: 2026-10-12 · 담당: 고태우 · WBS: A-10 (4/4)

이 문서는 [tasks/todo.md의 Task 10-2c](../tasks/todo.md#task-10-2c-github-변경분-갱신chroma-반영-a-10-44) 전체와 [tasks/plan.md](../tasks/plan.md)의 코퍼스 정책·의존 관계를 실행 계약으로 구체화한다. 일정과 전체 범위의 권위 문서는 [WBS v2.5](ART_agentic_wbs.md)다. **이번 작업의 산출물은 이 계획 문서 한 건과 지정 커밋 한 건이다.** 아래 프로그램·데이터·시험은 후속 구현 명세이며, 현재 구현·수집·정제 실행·재청킹·임베딩·저장소 갱신을 수행하지 않는다.

## 1. 목적과 범위

T10-1이 로컬에 동기화한 GitHub Issues·Discussions 및 댓글을 T10-2a의 동일 정제 규칙으로 판정하고, T08-2에서 선정한 `G-C-curated-group-t1024-o64`로 변환한다. 생성·수정·재포함된 후보의 완전한 청크셋을 같은 후보 ID로 T09 Chroma에 반영하고, `exclude` 또는 `review`로 바뀐 기존 후보는 검색에서 제외한다. 변환 대상 확인과 실제 벡터 쓰기를 구분하여, 변경 없는 후보는 재임베딩하지 않는다.

필수 완료 조건은 다음 세 가지다.

1. 생성·수정 후보가 안정적인 `candidate_id`를 유지하며 T09 저장소에 적재·갱신된다.
2. 정제 기준에서 빠진 기존 후보의 모든 청크가 검색에서 제외된다.
3. 동일 변경분의 재실행이 중복을 만들지 않으며, 저장소 검증과 성공 반환 뒤에만 해당 후보의 벡터 반영 상태를 확정한다.

원문 수집 완료는 T10-1의 `sync-state.json`, 벡터 반영 완료는 신규 `vector-state.json`이 담당한다. 원문 동기화 시각을 벡터 완료 시각으로 복사하지 않는다. 공개 GitHub 자료는 검색 용도로 사용하며 재배포 기능은 추가하지 않는다.

## 2. 읽기 전용으로 확인한 전제와 입력 4종

조사 기준 HEAD는 `5f5139e2e6172e71ce225cbd3c43d31b7e89bdfa`다. 현재 작업 폴더의 원문·결정·후보·보고서와 `src/artagent/retrieval/`를 읽고, 등록 원문 3,080개의 파일 SHA로 매니페스트를 재계산했다. 기존 산출물은 수정하지 않았다.

현재 폴더에는 `src/artagent/chunking.py`, T08-2 인계 파일·재현 스크립트와 `data/vector-store/t09/`가 없다. T09 문서가 지정한 아래 위치에서 T08-2 자료를 **파일 읽기로만** 확인했다. 해당 작업의 터미널이나 실행 상태를 접촉하지 않았다.

- [T08-2 선정 인계](/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff.md)
- [T08-2 기대값 계약](/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json)
- [T08-2 청킹 구현](/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/src/artagent/chunking.py), 같은 폴더의 `scripts/chunk_corpus.py` 및 `scripts/build_rule_expansion_chunks.py`

이 절대 경로는 조사 출처다. 후속 프로그램의 실행 경로에는 넣지 않는다. 구현 착수 전 선행 산출물이 변경 없이 통합된 저장소 루트와 실제 T09 persist 경로를 명시적으로 확보해야 한다.

### 2.1 수집 입력 — T10-1

| 항목 | 현재 형식과 소비 계약 |
| --- | --- |
| 원문 상태 | `data/issues/sync-state.json`: `version=1`, `repository=artraweditor/ART`, `last_synced_at`, `records` |
| 레코드 | 키는 `issue:{number}`, `issue-comment:{id}`, `discussion:{GraphQL id}`, `discussion-comment:{GraphQL id}`. 값은 `kind`, `object_id`, `source_url`, `storage_path`, `updated_at` |
| 원문 파일 | `storage_path`는 상태 디렉터리 기준 `snapshots/{issues,issue-comments,discussions,discussion-comments}/...json`; API 객체 원문을 보존 |
| 현재 범위 | Issue 465, Issue 댓글 2,471, Discussion 30, Discussion 댓글 114; 총 3,080레코드·495스레드 |
| 완료 시각 | `2026-09-28T02:06:12Z`; 수집 시작 시각을 완료 후 기록한 증분 조회 경계이며 원격 완전성·해결 시점을 뜻하지 않음 |
| 변경 판정 | 시각만 비교하지 않고 파일 SHA, 스레드 SHA, 후보 내용·정제 결과를 비교 |

수집기 [issues.py](../src/artagent/issues.py)는 변경 파일을 기존 경로에 덮어쓰고 상태 레코드를 유지한다. 변경 ID 목록·삭제 이벤트·과거 원문 버전을 제공하지 않는다. 따라서 갱신기는 현재 완료 입력을 동결하고 이전 벡터 반영 기록과 대조해야 한다. 상태에 등록된 파일 누락은 삭제로 해석하지 않고 입력 오류로 처리한다.

### 2.2 정제 입력 — T10-2a

정본은 [issue_filter_rules.md](issue_filter_rules.md), [issue_filter.py](../src/artagent/issue_filter.py), 다음 세 파일이다.

| 입력 | 필수 계약 |
| --- | --- |
| `curation-decisions.json` | `schema_version=1`, `rules_version=t10-2a-v1`, 저장소명, 부모 `record_key`별 검토 결정·`thread_sha256`·원문 범위·증거·제약 |
| `search-candidates.json` | 동일 버전과 `input_manifest`, 포함 후보 배열. `candidate_id`, `curated_content`, `source_locations`, `metadata` 보존 |
| `filter-report.json` | 전체 스레드의 `include/exclude/review`, 이유 코드, 댓글 판정, 입력 매니페스트·건수 수지 |

현재 포함 후보는 12개, 제외 13개, 검토 대기 470개다. 포함 후보에는 원문 조각 35개와 선택 댓글 23개가 있다. 이는 초기 기준선이며 미래 후보 수의 고정 조건이 아니다.

`candidate_id=github:artraweditor/ART:{issue|discussion}:{number}`는 스레드 갱신 키다. 댓글의 `ref_id`, REST 숫자 ID, GraphQL ID와 구분한다. `thread_sha256`은 부모와 **선택 여부와 무관한 모든 저장 댓글**의 `{record_key: file_sha256}`을 기존 canonical JSON 절차로 계산한 값이다.

`filter_corpus(input_dir, curation_path)`를 재사용하여 전체 입력을 판정한다. 변경된 검토 지문은 `STALE_CURATION`으로 `review`가 되며 이전 include가 유지되지 않는다. 새 원문을 읽고 작성한 유효 검토 결정이 입력으로 제공돼야 재포함할 수 있다. 갱신기가 이전 결정의 SHA만 새 값으로 고쳐 include를 유지해서는 안 된다.

닫힘·`[Solved]`·작성자 소속·반응 수·마지막 댓글을 단독 해결 증거로 쓰지 않는다. `accepted_content=null`, Discussion 채택 신호의 `not_collected`, 이관 원본 화자, 버전·플랫폼 제한과 반례를 유지한다. include만 청킹하고 review/exclude는 보고서에 남긴다. 정제 보고서의 `candidate_id`는 비포함이면 null이므로, 제외 대상 ID는 원문 부모의 종류·번호 또는 이전 벡터 상태에서 복원한다.

### 2.3 청킹 입력 — T08-2

| 항목 | 고정값·동작 |
| --- | --- |
| 규칙 | `G-C-curated-group-t1024-o64` |
| 기준 토크나이저 | `BAAI/bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| 물리 청크 | 목표 1,024 reference tokens, 요청 오버랩 64; 후보의 `curated_content` 순서로 원문 조각을 그룹화 |
| 생성 호출 | 기존 `chunk_github_curated_group_rule`에 `target_tokens=1024`, `overlap_tokens=64`, `guard_group=pooled-common-256`, `physical_embedding_policy=chunk_window_mean_v2`, `encoder_window_tokens=224`, `encoder_overlap_tokens=0`을 명시 |
| 규칙 지문 | `G-C-curated-group-t1024-o64:pooled-common-256:chunk_window_mean_v2:5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| 청크 ID | `t08c:v1:github:{rule_id}:{sha256}`; 기존 ID 계산을 그대로 재사용 |
| 그룹 ID | 청크 최상위 `doc_id`, `metadata.source_group_id`, `metadata.candidate_id` 모두 후보 ID |
| 위치 기준 | `metadata.range_basis=serialized_content`, 최상위 `char_range=[0,len(content))`; 각 segment는 원문 JSON `/body` 기준 |

기존 문장 분리·긴 문장의 token offset 분할·조각 사이 구분자·꼬리와 오버랩 선택 동작을 재사용한다. 조각 사이 구분자는 기존 `\n\n[{source_kind} {ref_id}]\n`이다. 오버랩 64는 요청값이며 문장 경계·꼬리·전진 조건에 따라 실제 겹침이 달라질 수 있다. 모든 출력의 실제 겹침을 정확히 64로 강제하거나 고정 stride로 재설계하지 않는다. 기존 `actual_tokens`·`actual_overlap_tokens` 필드를 보존하고 원문 구간 교집합을 별도로 대조한다.

청킹과 임베딩의 크기를 혼동하지 않는다. 물리 본문은 1,024토큰 규칙으로 생성하고, T09가 이를 내부 224토큰·오버랩 0 윈도우로 임베딩한다. 선정 풀링 분기에서 물리 본문을 MiniLM의 256토큰 한도로 절단하지 않는다. 기존 함수 기본값인 192/32나 비선정 direct 정책을 묵시적으로 사용하지 않는다.

### 2.4 저장소 입력 — T09

정본은 [T09_execution_plan.md](T09_execution_plan.md)와 실제 [retrieval/](../src/artagent/retrieval/) 모듈이다.

| 항목 | 계약 |
| --- | --- |
| 컬렉션·경로 | 두 출처 공통 `art_retrieval_t09_v1`; 계획 기본 경로 `data/vector-store/t09/`, 실행 시 기존 persist 절대 경로를 명시 |
| 모델 | `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| 벡터·계산 | 384차원 `float32`, L2 정규화; `chunk_window_mean_v2`, 본문 토큰 수 가중 평균·재정규화, 헤더 최대 32 reference tokens |
| 인코더 | CPU, 문서 배치 16, torch 스레드 4; 특수 토큰 포함 최대 256토큰, 문서·질의 prefix는 빈 문자열 |
| HNSW | cosine, `ef_construction=200`, `ef_search=200`, `max_neighbors=16`, `num_threads=1` |
| 검색 | fetch10 → `(round(distance,6), chunk_id)` 오름차순 → top5; `excluded=False`를 조회 조건으로 적용 |
| 저장 계약 | `retrieval_schema_version=1`, 모델·규칙·토크나이저·풀링·인계 SHA·protocol SHA와 실제 HNSW 설정 대조 |
| 갱신 호출 | `replace_source(SourceKey("github", candidate_id), chunks, session, source_root=...)` |
| 제외 호출 | `exclude_source(SourceKey("github", candidate_id))`; 저장 청크를 `excluded=True`로 표시 |

`open_store`는 경로·컬렉션이 없으면 새 저장소를 만든다. 운영 갱신기는 호출 전에 기존 DB·컬렉션과 T09 초기 적재 완료 증거를 확인하여, 경로 오타로 빈 저장소를 만들고 성공하는 일을 막는다. 빈 저장소의 두 출처 최초 전량 적재는 T09의 책임이다. T10-2c의 최초 반영은 기존 T09 저장소에 GitHub 항목 상태를 처음 맞추는 실행이다.

초기 기준선은 RawPedia 141청크·GitHub 13청크·합계 154다. 이후 GitHub 갱신에는 13/154 건수와 초기 GitHub 파일 SHA를 강제하지 않는다. `load_selected_chunks`는 초기 인계셋 검증용이고, 증분 청크는 `Chunk` 변환·`validate_provenance`를 거쳐 `replace_source`에 전달한다.

### 2.5 조사 지문

아래는 실제 읽은 파일의 SHA-256이다. 현재 기준선 확인에 사용하며, 후속 변경 입력은 새 지문으로 따로 기록한다.

| 대상 | SHA-256 |
| --- | --- |
| `sync-state.json` | `0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187` |
| 원문 매니페스트 | `52b6cdf587e1f5ed12d80570a41a476ef02dd6e2118c9a9c09a871e7889d01c5` |
| `curation-decisions.json` | `e7925afe3a9cd5041d492f318bebf9c7bdc627023d29e5008713630e4d2a430e` |
| `search-candidates.json` | `c2074548354406b6bd2e886259ca8eea4a02813dead57fba77e0bf1a5bf86344` |
| `filter-report.json` | `e25b4ffdcfb5f190a82c795d809eb5606d0a23f1f18635559523480686ac1c08` |
| T08-2 reference | `2c7081ba6a7c37b00735b0be2ef362f5b0c2a86cd41fe97bbb2a3b5ebdc195bc` |
| T08-2 `chunking.py` | `2640ba76d7afb1a67237e9415501baeddaee6cbf5cbe638553bdf4fed1a672d0` |
| 인계 protocol | `3694eb3cb0a8b8e989e6bc828adf1f067b4f988f9be0a04a4d43507850412dc5` |
| 초기 선정 GitHub JSONL | `7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571` |

원문 매니페스트는 `{storage_path: 파일 바이트 SHA}`의 키 정렬·구분자 `(',', ':')` JSON을 UTF-8로 해시한 T10-2a 계약이다. thread SHA와 청크 SHA는 각각 기존 함수의 계약을 사용하며 하나의 지문으로 대체하지 않는다.

## 3. 변환·갱신 프로그램 스펙

### 3.1 책임과 인터페이스

후속 구현은 `src/artagent/issue_update.py`에 조정 로직, `scripts/update_issue_index.py`에 argparse CLI를 두는 소규모 구성으로 제안한다. docstring과 `main()` guard, 기존 프로젝트 Python 3.14 venv를 사용한다. 수집·정제·청킹·저장소 알고리즘은 선행 모듈에서 재사용하고 복제하거나 수정하지 않는다.

CLI는 `prepare`와 `apply` 두 동작을 제공한다.

| 동작 | 입력·출력 계약 |
| --- | --- |
| `prepare` | `--source-root`, `--input-dir`, `--curation`, `--reference`, `--persist-dir`, `--output-dir`를 명시. 완료 원문 입력을 동결·정제하고 차이를 계산하여 검증된 세대별 실행 계획·청크를 생성. Chroma 쓰기와 완료 상태 전진은 없음 |
| `apply` | `--plan`과 동일한 `--persist-dir`, `--reference`를 명시. 저장된 계획·동결 원문·청크의 지문을 확인하고 T09 갱신/제외 호출 후 항목별 성공을 기록. 수집·정제·재청킹을 새로 수행하지 않음 |

성공·동일 입력 무변경은 종료 0, 입력/계약 오류 또는 일부 미반영은 종료 1, 인자 오류는 종료 2로 구분한다. stdout에는 세대·계획 경로·생성/갱신/제외/변경 없음/미반영 건수를 출력한다. 오류에는 후보 ID와 실패 단계를 기록한다. 인증 정보는 소비하지 않는다.

### 3.2 입력 동결과 변경분 산출

1. T10-1의 정상 동기화 완료 이후 실행한다. 원문 수집·검토 결정 작성·벡터 갱신은 순차 실행하고 단일 작성자를 유지한다. 수집 실패로 상태 파일과 원문이 불일치하면 기존 정제 검증으로 거부한다.
2. `load_sources`와 `filter_corpus`의 전수 검증을 사용한다. state·등록 파일·curation의 SHA를 읽기 전후에 대조한다. 누락·미등록 파일·경로 이탈·ID/URL/부모 불일치·도중 변경이면 계획을 공개하지 않는다.
3. 해당 시점의 state·등록 원문·curation을 신규 세대의 `source/data/issues/` 아래에 바이트 그대로 보존한다. 복사 후 매니페스트를 다시 대조한다. 동결 루트를 T09 `source_root`로 사용하면 기존 segment의 `data/issues/snapshots/...` 상대 경로를 변경하지 않아도 된다.
4. 동결 입력으로 `filter_corpus`를 호출하여 세대별 후보·보고서를 만든다. 기존 초기 `search-candidates.json`·`filter-report.json`·결정 파일을 덮어쓰지 않는다. 정제는 전체 입력으로 수행하여 중복 관계·반례·전체 수지를 보존하고, 청킹·벡터 쓰기를 변경 후보로 제한한다.
5. 이전 반영 항목과 현재 스레드를 안정적인 후보 ID로 대조한다. 부모/댓글 추가·수정뿐 아니라 검토 결정 변경, 선택 조각·제약·제목·출처 메타데이터 변경도 확인한다. 후보별 canonical SHA에는 전체 후보 객체를 쓰고, 파일 공통 `input_manifest`·실행 시각은 넣지 않는다.
6. 첫 실행은 T09 컬렉션의 GitHub 그룹 전체를 읽고 포함 후보와 맞춘다. 외부 vector-state가 없다는 이유로 기존 청크를 무조건 신규로 보거나 삭제하지 않는다. include 그룹은 전체 청크를 생성·대조하고, 기존 활성 그룹의 현재 review/exclude는 제외 작업으로 계획한다. 원문에 없는 기존 그룹은 원격 삭제로 추론하지 않고 원인 불명 오류로 남긴다.

파일 수정 시각이나 `updated_at > last_synced_at`만으로 변경 후보를 찾지 않는다. 같은 원문 상태에서도 재검토 결정만 바뀌면 후보가 생성·제외될 수 있다. 전체 원문 지문 조회가 필요해도 변경 없는 그룹의 임베딩·쓰기까지 수행하지 않는다.

### 3.3 항목별 변환·저장 동작

| 이전/현재 결과 | 실행 |
| --- | --- |
| 미적재 또는 제외 → 유효 include | 같은 후보 ID로 전체 청크셋을 생성·검증 후 `replace_source`; 재포함 시 `excluded=False` 복구 |
| 활성 include → 수정된 include | 후보 전체 새 청크셋으로 `replace_source`; 구 ID 중 새 집합에 없는 청크는 T09가 삭제 |
| 활성 include → exclude/review | `exclude_source`; `STALE_CURATION`도 동일하며 이유와 재검토 필요를 기록 |
| 유효 include와 동일 입력 | 저장 본문·ID·전체 직렬화 metadata가 일치하면 쓰기 생략. T09의 멱등 비교도 활용 |
| 미적재 review/exclude | 청킹·임베딩 없음. 검색 가능 청크 0임을 확인하고 판정만 기록; 적재 성공으로 표현하지 않음 |
| 제외 유지 | 반복 제외 또는 상태 대조로 검색 가능 청크 0 확인; 이전 성공 시각을 재실행마다 갱신하지 않음 |

include 결과가 빈 청크셋이면 변환 오류다. 이를 제외로 바꾸지 않는다. 다른 후보의 청크를 섞거나 한 후보의 일부 청크만 `replace_source`에 전달하지 않는다. T08-2 청크는 `to_dict()` → T09 `Chunk.from_dict()`로 연결하여 타입 경계만 변환하고, 본문·ID·metadata를 재작성하지 않는다.

모든 segment의 파일 SHA·body SHA·문자/UTF-8 바이트 범위·본문 SHA·청크 내 범위·URL을 대조하고 `validate_provenance`를 통과시킨다. 한 청크에 여러 댓글이 있으면 전체 segment와 순서를 보존한다. 규칙·풀링·윈도우 metadata도 갱신기에서 명시적으로 검사한다. T09의 출처 검증만으로 선정 청킹 규칙 준수가 증명된다고 간주하지 않는다.

후보 SHA가 바뀌어도 청크 payload가 동일할 수 있다. 이 경우 새 정제 판정·thread 지문을 기록하되, 저장 payload 일치 확인 후 완료 처리하고 임베딩을 생략할 수 있다. 반대로 청크 ID가 같아도 제목·파일 SHA·metadata가 바뀌면 변경 없음으로 처리하지 않는다.

### 3.4 성공 상태와 실패 복구

실행 계획은 먼저 영속화하고, 각 작업을 T09에 전달한다. 저장소가 검증한 `IndexReport.status=success`를 반환하고 대상 그룹의 저장 ID·본문·metadata 또는 제외 플래그를 다시 대조한 뒤에만 `vector-state.json`의 해당 항목 `applied`를 원자적으로 교체한다. 제외도 성공 반환 뒤에 확정한다. 이전 성공값과 현재 목표값은 별도 필드로 유지한다.

T09는 upsert/delete/update 전에 컬렉션 `store_state=updating`과 작업·입력 지문·그룹 키를 남긴다. 중단되면 검색을 거부하고 **동일 작업·동일 입력**으로만 복구한다. 갱신기는 다음과 같이 대응한다.

- `prepare` 중 실패: 기존 저장소와 반영 상태는 유지하고 불완전 세대는 적용 불가로 남긴다.
- 임베딩/출처 검증 실패: T09가 쓰기 전에 실패하면 기존 반영값을 유지한다. 실행 실패와 재시도 대상을 보고한다.
- 저장 호출 중 실패: 항목 완료값을 전진시키지 않고 배치를 중단한다. 동결 계획의 동일 그룹·청크를 재전달한다. 다음 그룹이나 최신 세대부터 적용하지 않는다.
- T09 성공 뒤 외부 상태 저장 실패: 성공을 추측하여 체크포인트를 건너뛰지 않는다. 같은 계획을 재실행하여 T09의 멱등 확인과 그룹 읽기 검증 후 상태 기록을 완료한다.
- 미완료 `updating`이 있을 때: 컬렉션의 실제 영속 metadata를 새로 읽고 보존 계획의 operation·T09 입력 지문·키와 대조한다. 맞는 계획이 없으면 오류로 중단하며 상태를 임의로 ready로 바꾸지 않는다.

T09 입력 지문은 `chunk_id` 순으로 정렬한 `chunk_id/document/serialize_metadata(...,excluded=False)` 레코드의 canonical SHA와 동일하게 기록한다. 제외는 T09의 출처 키 지문을 기록한다. 서로 다른 세대나 수정된 동결 파일로 복구하지 않는다.

계획에는 준비 시점의 이전 성공 세대·상태 SHA와 작업별 기존 저장 payload 지문을 남긴다. apply는 해당 기준 상태, 같은 세대의 부분 성공 상태, 또는 같은 세대의 완료 재실행만 허용한다. 다른 세대가 이미 반영됐거나 저장 레코드가 외부에서 바뀌었으면 오래된 계획을 거부하여 새 데이터를 이전 입력으로 되돌리지 않는다. 동일 입력의 정상 재실행과 오래된 세대의 재적용을 구분한다.

배치는 후보별 순차 적용이다. 완료된 항목은 유지하고 실패 항목부터 재시도하며, 전체 배치 원자성이나 자동 롤백을 약속하지 않는다. T09의 잠금은 같은 프로세스 안에서만 유효하므로 수집·갱신·다른 작성자의 동시 실행은 지원하지 않는다. 배치의 모든 작업이 검증된 뒤에만 `last_completed_generation`을 전진시킨다. review가 남아도 그 검색 제외가 완료되면 벡터 반영 배치는 완료될 수 있다. 재검토 완료와 벡터 반영 완료는 구분한다.

## 4. 후속 산출물과 data/issues/ 갱신 형식

다음은 후속 구현에서 필요한 파일 제안이다. 이번 문서 커밋에서는 생성하지 않는다.

| 산출물 | 역할·형식 |
| --- | --- |
| `src/artagent/issue_update.py` | 동결·정제 호출·후보 비교·선정 청킹 어댑터·T09 적용·상태 기록 |
| `scripts/update_issue_index.py` | prepare/apply CLI; 경로 인자를 명시하고 요약·종료코드 반환 |
| `tests/test_issue_update.py` | 생성·수정·제외·재실행·부분 실패·복구를 원문 fixture와 실제 임시 Chroma로 검증 |
| `data/issues/index-updates/{generation_id}/source/data/issues/` | state·등록 원문·curation 동결본. 최초 검증 후 불변이며 이전 성공/미완료 세대는 삭제하지 않음 |
| 같은 세대의 `search-candidates.json`, `filter-report.json` | 기존 T10-2a 스키마 그대로 생성한 현재 판정. 기존 초기 후보와 분리 |
| 같은 세대의 `chunks.jsonl` | 변환 대상 include 그룹의 **완전한** 청크셋만 포함; T08-2 `Chunk.to_dict()` 형식·UTF-8·행 단위 JSON |
| 같은 세대의 `update-plan.json` | 입력 지문·저장소 계약·그룹 작업·청크 ID/파일 지문·복구 입력을 가진 불변 계획 |
| 같은 세대의 `apply-report.json` | 작업별 pending/success/failed/noop·IndexReport·검증 결과·실패 단계와 배치 완료 여부 |
| `data/issues/vector-state.json` | 스키마 1의 저장소 식별 정보·후보별 마지막 성공값·전체 완료 세대. raw sync 상태와 분리 |

`generation_id`는 저장소 식별값, 입력 state/원문 매니페스트/curation SHA, 정제 규칙, 청킹 구현·규칙 지문, reference/protocol SHA의 canonical digest다. 실행 시각과 무작위 UUID는 식별값에 넣지 않는다. 같은 입력·대상에는 같은 세대를 재사용하고 기존 파일의 SHA를 확인한다. 입력이 다른데 같은 세대 파일을 덮어쓰지 않는다.

`update-plan.json`은 `schema_version`, `generation_id`, `repository`, `input_manifest`, `source_root`, `base_generation`, `base_state_sha256`, `store` 및 `operations`를 가진다. `store`에는 persist 절대 경로·컬렉션·reference/protocol SHA와 계약 지문을, 각 operation에는 `candidate_id`, 부모 `record_key`, `thread_sha256`, `disposition`, `reason_codes`, `action`, `candidate_sha256`, 기존 payload 지문, 전체 새 `chunk_ids`, 청크 payload SHA와 T09 작업 지문을 둔다. 정제 결과·반영 대상·재시도 입력을 각각 역추적할 수 있어야 한다.

`vector-state.json`의 항목 키는 `candidate_id`다. 각 항목의 성공 기록은 `applied_generation`, `applied_input_manifest`, `thread_sha256`, `candidate_sha256`, 정제 판정·이유, 청크 ID·payload SHA, `active/excluded/never_indexed`, 동결 `source_root`, `applied_at`을 보존한다. 제외 항목도 tombstone으로 유지해 재포함·반복 제외를 추적한다. 아직 검증되지 않은 목표값과 실패 정보는 실행 계획·보고서에 두고 이전 applied를 바꾸지 않는다. 서로 다른 DB의 상태 파일을 재사용하면 오류다.

청크는 T08-2 후보 정렬 `(source_type,source_number)`과 후보 내부 생성 순서를 유지한다. JSONL은 기존 `json.dumps(chunk.to_dict(),ensure_ascii=False)`·행 구분·마지막 개행 계약을 따른다. Chroma 적용용 ID 정렬은 T09 내부에서 한다. 모든 ID·segment·추가 metadata를 보존하며 청크 스키마를 새로 만들지 않는다.

프로그램은 임시 파일 작성·검증·원자적 이름 교체로 완성 파일을 공개하고, 동일 바이트면 다시 쓰지 않는다. 실행 시각은 최초 성공 기록을 유지한다. `apply-report`의 실행 상태는 갱신될 수 있지만 동일 성공 입력 재실행으로 성공 상태 파일·청크·적용 시각이 바뀌지 않아야 한다. 배치 완료 receipt와 성공 항목 수를 대조하여 중간 파일 저장 실패도 복구한다.

원문·후보·청크·벡터 상태는 위 계층으로 구분한다. 원문 파일 SHA 검증에는 해당 후보의 마지막 적용 세대 `source_root`를 사용하여 수집 덮어쓰기 이후에도 근거를 복원한다. 현재 저장소의 상대 경로와 세대 동결 루트 연결을 보고서·상태에서 제공한다. 원문 복사본·임시 파일·Chroma DB를 프로그램이 자동으로 Git에 추가하지 않으며, DB 파일은 커밋 산출물이 아니다.

## 5. 검증 기준

시험은 고정 API 응답/원문 fixture, 유효 검토 결정, 임시 데이터 루트·Chroma에서 수행한다. 실제 `data/issues/`와 기존 운영 저장소를 시험 대상으로 갱신하지 않는다. 테스트용 수정 원문에는 state 대응 필드와 필요한 새 검토 지문을 함께 제공하고, stale 시험에서는 의도적으로 이전 지문을 유지한다.

| 검증 | 합격 기준 |
| --- | --- |
| 선행 기준선 | 읽은 원문·정제 SHA 일치; 변경 없는 T08-2 입력으로 생성한 GitHub 13청크 파일 SHA가 §2.5와 일치 |
| 청킹 규칙 | 같은 후보를 기존 선정 함수와 어댑터로 독립 생성해 ID·순서·본문·규칙 지문·전체 metadata/segment와 JSONL 바이트가 일치 |
| 청킹 경계 | 긴 조각·다중 댓글·코드·CRLF·한글/이모지·꼬리·요청 오버랩 사례에서 기존 경계 재현, 전진·종료, curated 비공백 구간 coverage 100%; 임의 절단 0 |
| 출처 추적 | 전체 chunk ID와 본문/파일/body/segment SHA, Python 문자·UTF-8 바이트·청크 내부 범위·URL 대조 및 metadata roundtrip 통과 |
| 저장소 계약 | 모델/revision·384 float32·노름 오차 ≤1e-5·풀링·빈 prefix·윈도우·reference/protocol·실제 cosine/HNSW 일치. 불일치·빈 운영 경로는 쓰기 전 거부 |
| 최초 반영 | 초기 T09 저장소의 기존 12그룹·13 GitHub 청크와 대조하여 중복 없이 상태를 구축. 초기 RawPedia 141청크의 ID·본문·metadata·벡터 불변 |
| 생성·재포함 | 현재 지문에 맞는 include 결정이 있는 새/기존 후보가 같은 후보 ID로 반영되고 전체 새 청크만 active. 처음 등장한 미검토 후보는 never_indexed |
| 수정 | 청크 수 감소·본문 변경·동일 ID의 제목/출처 metadata 변경 모두 반영; 구 ID 잔류 0, 비대상 그룹 레코드·벡터 불변 |
| 제외·보류 | include→exclude와 include→STALE_CURATION/review 모두 해당 그룹 active 청크 0, source_key 검색 결과 0. 재포함 전까지 전역 검색에서도 미반환 |
| 재실행 | 동일 변경분으로 ID 집합·청크 수·본문·metadata·벡터·applied 값 불변. 불필요한 임베딩·DB 쓰기 0, 반복 제외 중복 없음 |
| 메타데이터만 변경 | 청크 ID가 같아도 payload 차이는 저장; 정제 판정만 바뀌고 payload가 같으면 읽기 검증 뒤 상태만 확정 |
| 실패·재시도 | prepare/임베딩/upsert/delete/exclude/외부 상태 기록 실패를 주입. 성공 전 applied 전진 0, partial 상태 검색 거부, 동일 동결 계획 재개방·복구 성공 |
| 입력·상태 경계 | 파일 누락/외부 경로/ID 혼합/빈 include/중간 원문 변경/다른 DB 상태/없는 복구 계획/새 세대 적용 후 옛 계획 재적용 거부. 이전 세대 바이트·성공값 불변 |
| 검색 정합성 | rank·chunk ID·그룹·전체 원문 위치·거리 6자리 반환과 fetch10/top5 유지. 갱신 후 원문은 적용 세대에서 복원 |

초기 선정 회귀는 변경 전 독립 저장소에서 T09의 100질문×3회 기대값 전체와 top5 거리 오차 ≤1e-5를 확인한다. GitHub 변경 뒤 전체 검색 순위나 Hit/MRR가 초기와 같아야 한다고 요구하지 않는다. 변경 후에는 대상의 반영/제외·비대상 저장 레코드 불변·검색 반환 계약을 확인하고 관찰한 검색 변화를 기록한다.

후속 구현의 집중 검증은 새 `tests/test_issue_update.py`와 기존 `tests/test_github_issues.py`, `tests/test_filter_issues.py`, `tests/test_retrieval.py`, `tests/test_retrieval_state.py`를 프로젝트 venv로 실행한다. 실제 선정 회귀에는 T09 문서의 재현 출력·reference·source-root 인자를 명시하여 최신 임시 폴더 자동 선택을 피한다. 필요한 통합 선행물이 없는 현재 계획 작성 단계에서 이 시험을 실행하거나 통과했다고 보고하지 않는다.

## 6. 단계별 작업 순서와 완료 증거

의존 순서는 `T10-1 완료 원문 + T10-2a 규칙/검토 결정 + T08-2 선정 구현 + T09 초기 저장소 → 입력 동결/차이 → 후보 전체 청킹 → 항목별 적용 → 성공 상태 기록 → 재실행 검증`이다.

| 단계 | 의존·작업 | 예상 파일 | 완료·검증 증거 |
| --- | --- | --- | --- |
| P1. 실행 전제 고정 | 네 입력과 통합 루트·기존 DB·모델 cache·기존 venv 확인. T08-2 인계 지문·T09 초기 적재 증거와 현재 상태 대조 | 기존 산출물 읽기만 | 초기 13 GitHub/141 RawPedia 재현 증거·현재 DB 계약/반영 상태 확인, 실제 경로·SHA 기록 |
| P2. 최초 후보 한 건 연결 | 동결·prepare 및 선정 청킹 어댑터를 만들고 기존 Issue #500으로 처음부터 상태 기록까지 연결 | 조정 모듈, CLI, 새 시험 | 초기 기존 ID 유지·원문 복원·성공 뒤 기록·동일 입력 무변경 |
| P3. 생성·수정·제외 연결 | 후보 차이 표와 다중 조각 Discussion, 재검토 입력·stale 제외를 구현 | 동일 3개 파일 | 생성/수정/제외와 재포함, 구 청크 삭제·비대상 불변 시험 |
| CP1. 변환·저장 계약 확인 | P2/P3 증거 확인 | 시험 로그·임시 산출물 | 선정 함수와 byte parity, 전체 segment roundtrip·상태 분리 합격 |
| P4. 중단 복구·멱등성 | 불변 실행 계획과 원자적 성공 상태, T09 updating 복구를 연결 | 동일 3개 파일 | 부분 실패·프로세스 재개방·다른 입력 거부·외부 상태 기록 실패 재시도 합격 |
| P5. 수용 검증·실행 인계 | 집중 시험과 초기 선정 회귀 후 승인된 실제 입력에 prepare/apply 수행 | 후속 data/issues 세대별 산출물 | 최초/생성/수정/제외/재실행 증거, 실제 counts·보류 수·적용/미반영 ID·계약 기록 |

P5의 실제 적용은 이 문서 작성 작업에 포함되지 않는다. 각 단계에서 실패한 검증은 다음 단계로 넘기지 않는다. 이미 갱신된 DB의 현재 건수에는 초기 13/154를 강제하지 않고 성공 상태와 현재 계획을 대조한다. 새 의존성이 실제로 필요하면 소비 시점에 설치 필요성과 기록을 남기고, 미리 패키지 목록·새 venv·설정 로더를 만들지 않는다.

### Task 10-2c 수용기준 대응

| tasks/todo.md 기준 | 설계·최종 증거 |
| --- | --- |
| 생성·수정 후보를 같은 ID로 적재·갱신 | §2.3~2.4, §3.3; 생성/수정/재포함의 그룹 키·새 ID 집합·원문 대조 |
| 제외 항목 검색 결과 제거 | §3.3; review 포함 제외 플래그 전수와 source_key/전역 검색 미반환 |
| 같은 변경분 재실행 중복 없음·성공 뒤 상태 전진 | §3.4~4; 동일 입력 DB/상태 불변·실패 주입·복구 결과 |
| 최초+생성·수정·제외+재실행 확인 | §5~6의 독립 임시 저장소 시험과 실행별 보고서 |

- [ ] 네 선행 입력과 실제 T09 저장소 계약을 고정한다.
- [ ] 선정 청킹의 ID·본문·원문 위치·직렬화 재현을 증명한다.
- [ ] 후보별 생성·수정·제외·재포함과 비대상 불변을 증명한다.
- [ ] 저장 성공 뒤 상태 전진과 동일 동결 계획 복구를 증명한다.
- [ ] 최초·변경분·재실행 증거와 후속 소비처용 적용 세대 연결을 인계한다.

체크박스는 후속 구현 완료 조건이며 이번 계획 작성으로 완료 처리하지 않는다.

## 7. 리스크와 제외 범위

| 리스크 | 영향·대응 |
| --- | --- |
| 현재 폴더의 T08-2 통합물·운영 DB 부재 | 준비 완료를 추측하지 않고 P1에서 통합 루트와 초기 적재 증거를 확보. 읽기 fallback을 실행 import로 사용하지 않음 |
| 수집기는 덮어쓰기·삭제 미탐지 | 적용 세대의 원문을 보존. 원격 삭제/비공개 전환을 로컬 누락으로 추론하지 않으며 입력 누락은 실패 |
| 새 댓글 때문에 기존 후보가 review | stale 후보는 검색 제외하고 이유·재검토 필요를 공개. 자동 SHA 교체나 기준 완화로 후보를 유지하지 않음 |
| 제외 보고서의 candidate_id=null | 검증된 부모 종류·번호와 이전 상태로 그룹 키를 복원. 댓글 ID로 그룹을 제외하지 않음 |
| 규칙 이름만 맞고 실제 경계·정책이 다름 | 모든 생성 인자와 지문을 고정하고 기존 함수와 독립 byte parity. nominal overlap과 실제 범위를 구분 |
| 같은 청크 ID의 파일 SHA·제목 변경 누락 | ID 집합 외에 본문·직렬화 metadata·후보 지문을 비교 |
| 동결 복사·청크·Chroma·상태 사이 중단 | 입력 전후 해시·불변 계획·그룹 단위 성공 체크포인트. T09 동일 작업 복구 뒤 재시도 |
| 과거 적용본의 source_path와 현재 원문 불일치 | candidate별 applied 세대 source_root로 SHA 검증·역추적; 동결본 보존 정책의 임의 삭제 금지 |
| 배치 중 부분 성공 또는 동시 작성 | 배치 원자성 없음과 미반영 항목 기록. 단일 작성자·순차 수집/검토/반영, 분산 잠금 도입 없음 |
| 초기 기준선과 갱신 후 평가 혼동 | 13/154와 초기 SHA는 기준선에서만 검사. 변경 후 그룹·active 수지는 실제 계획으로 계산 |

제외 범위는 GitHub API 수집기 변경·실제 원격 수집, 원격 삭제 탐지·도달성 검사, 미수집 채택 신호/답글 계층 보강, 자동 해결 추론, 모델/청킹 재선정·전체 비교 행렬 재실행, RawPedia 갱신, T11 답변 생성·번역·요약, 질문 재작성·리랭킹·k 튜닝, 프로필 생성·ART-cli 실행, ART 코어 변경, `tool/lang` 필터, 분산/다중 작성자 운영, 주간 자동화 배포다. 주 1회 원문 동기화 정책은 유지하되 스케줄러 구현은 추가하지 않는다.

이번 작업에서는 이 문서만 Git에 추가하고 `docs: Task 10-2c 실행 플랜 추가` 메시지로 한 번 커밋한다. push·PR·프로그램 구현·실제 data/issues/ 또는 벡터 저장소 갱신·다른 터미널 접촉은 수행하지 않는다.
