# Task 8-2 문서 청킹 및 임베딩 벤치마크 실행 플랜

작성일: 2026-09-28 · 담당: 김대성 레인 · 구현 실행자: Antigravity(Gemini 3.8 Flash)

이 문서는 WBS Phase A의 **A-08 2/3·3/3, A-10 3/4**를 실행하기 위한 구현 계약이다. 목표는 두 출처의 후보 청크를 실제로 생성하고, 고정 100개 질문으로 **같은 임시 Chroma의 독립 컬렉션**에서 비교하여 **RawPedia 규칙 1개 + GitHub 규칙 1개 + 공통 임베딩 모델 1개**를 선정하는 것이다. 아래 수치와 모델은 실험 후보이며 선정 결과가 아니다. 이번 커밋은 플랜 작성이고, 구현·모델 설치·벤치마크 완료를 뜻하지 않는다.

권위 문서는 [WBS §5](ART_agentic_wbs.md), [Task 8-2 및 T9 상세 카드](../tasks/todo.md), [T8-1 전달 계약 §8](T08_1_execution_plan.md), [GitHub 정제 규칙](issue_filter_rules.md)다. WBS의 9/5~9/11 계획 일정은 보존하고, 실행 기록에는 실제 날짜를 쓴다.

## 1. 완료 조건과 범위

| Task 8-2 완료 기준 | 이 플랜의 구현 및 검증 증거 |
|---|---|
| 출처별 둘 이상의 청킹 규칙·청크셋과 원문 추적 | §3~4의 후보 JSONL, 청킹 매니페스트, 모든 source segment의 원문·URL·해시·위치 검증 |
| 둘 이상의 모델을 실제 적재·검색하고 출처별·평균 Hit/MRR·부담 기록 | §5~7의 모델 실행 확인, 혼합 코퍼스 Chroma 검색, 100개별 결과 및 조합별 집계 |
| 규칙·모델·전체 비교·선정 순서와 T9 재현 입력 | §8~9의 JSON/Markdown 리포트, 선정 청크셋·해시·모델 revision·적재 설정·재실행 결과 |

- 입력은 RawPedia **116개 전체**와 GitHub **정제 후보 12개**다. 골드가 있는 50개 RawPedia 페이지만 적재하지 않는다.
- 질문 생성, 질의 번역·재작성, 답변 생성, 리랭커, k 튜닝, RAGAS, 증분 갱신 구현은 각각 기존 담당 태스크에 남긴다. 질문과 참고 스팬을 검색 문서에 추가하지 않는다.
- Chroma는 고정이다. NumPy 전수 코사인 검색은 구현 오류·ANN 누락을 확인하는 대조군으로 사용하고, Chroma 실험을 대체하지 않는다.
- Python은 기존 root venv 3.14를 재사용한다. `requirements.txt`, 범용 설정 로더, ART 코어 변경은 추가하지 않는다. CLI는 argparse, docstring, `main()` guard를 갖춘다.
- 최소 완료 조건은 **실행 가능한 모델 2개 이상, 그중 한국어–영어 검색 후보 1개 이상**, 선택 가능한 청킹 규칙 출처별 2개 이상, 해당 Cartesian product 전체의 성공한 실행이다. 실패 모델도 리포트의 실패 행으로 남긴다. 성능이 낮다는 이유로 실행 대상을 빼지 않는다.

## 2. 실제 입력 조사와 고정 방법

### 2.1 2026-09-28 워크트리에서 확인한 구조

조사 기준 HEAD: `b7c105cc1c0ded7647be9bfe891cf4c23f7652eb`(T8-1 PR 병합). 후속 실행에서는 실제 시작 HEAD도 기록한다.

| 입력 | 실측 구조 | 구현상의 의미 |
|---|---|---|
| `data/rawpedia/**/*.md` | 116개, 1,633,045 bytes; 최상위 107개 + `Tutorials/game_changer/` 9개 | 재귀 탐색하고 POSIX 상대 경로로 정렬 |
| RawPedia 문법 | YAML frontmatter, H2/H3 및 더 깊은 제목, 표·목록·코드·HTML/이미지, 제목 없는 본문 | 원문을 보존하는 구간 파서 필요; frontmatter는 본문에서 제외 |
| 긴 문서 | `local_adjustments.md` 346,640 bytes, `Wavelet_Levels.md` 101,428 bytes | 페이지 전체를 모델에 넣거나 묵시적으로 자르지 않음 |
| RawPedia 원본 연결 | `docs/rawpedia_collection.md`의 included 116행, 업스트림 커밋 `3efb99c1d39e8d73266be0e7cc4184814b5f7cc2` | 로컬 파일 → page URL → 업스트림 파일 URL을 그대로 연결 |
| `search-candidates.json` | 최상위 `candidates`, `input_manifest`, `repository`, `rules_version`, `schema_version`; 규칙 `t10-2a-v1` | JSON 전체를 문자열 문서로 만들지 않고 후보 배열을 읽음 |
| GitHub 후보 | Discussion 7개 + Issue 5개; `curated_content` 35개, `source_locations` 35개(부모 12 + 댓글 23) | `candidate_id`와 원문 `ref_id`를 구분 |
| GitHub 원문 | 본문은 스냅샷 JSON의 `/body`; CRLF, 이모지, URL·코드가 실제 포함됨 | 물리 JSON 파일 해시와 디코딩한 body 해시를 각각 검증 |
| GitHub 원문 한계 | `accepted_content=null`; Discussion 채택 답변·답글 계층은 미수집 | 마지막 댓글, 인접 댓글, closed 상태로 Q/A 관계·해결을 추론하지 않음 |
| `search_eval_queries.json` | `dataset_id=t08-1-100-v1`; 최상위 객체의 `queries` 배열 | 배열 자체가 최상위라는 가정을 금지 |
| 질문 분포 | 100개 모두 한국어 포함; RawPedia 80 + GitHub 20; factoid 50 + complex 45 + negative 5 | 한국어 질의를 그대로 공통 모델에 입력 |
| 검색 점수 분모 | 양성 95개 = RawPedia 80 + GitHub 15; negative Q096~Q100은 GitHub 5개 | 출처 평균은 80:15 가중 평균과 구분 |
| 실제 근거 수 | **147개 = support 142 + counterevidence 5** | 모든 근거를 처리; 첫 `evidence_text_span`만 사용하지 않음 |

기존 [검증 보고서](search_eval_validation_report.md)는 총 스팬을 137개로 기재하지만 현재 JSON을 집계하면 147개다. 벤치마크는 JSON 정본을 기준으로 수를 다시 계산하고 이 차이를 입력 주의사항으로 남긴다. 골드를 137개에 맞춰 삭제하거나 수정하지 않는다. 현재 기존 `generate_eval_queries.py check`와 `tests/test_eval_queries.py`의 **13개 테스트는 통과**했다. 이는 아직 청킹·임베딩의 실행 증거가 아니다.

GitHub 후보 번호는 D #412/#420/#424/#440/#442/#489/#494, I #477/#500/#516/#521/#524다. 선택 스레드의 실제 전체 댓글은 합계 **39개**로, 정제된 댓글 23개와 다르다. 예를 들어 D #442는 댓글 4개 중 2개가 정제 후보에 있고, I #524는 댓글 8개 중 4개가 후보에 있다. `source_locations`만으로 전체 댓글을 읽었다고 보고하면 안 된다.

### 2.2 입력 지문과 중단 조건

현재 파일 SHA-256:

| 파일/집계 | SHA-256 |
|---|---|
| `docs/search_eval_queries.json` | `91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8` |
| `docs/search_eval_source_manifest.json` | `9df74aad9b082f4ce908f38f9a53e4850de24fd9f889c60c9da04791fa59d309` |
| `data/issues/search-candidates.json` | `c2074548354406b6bd2e886259ca8eea4a02813dead57fba77e0bf1a5bf86344` |
| `data/issues/sync-state.json` | `0c2c0440ee63795103217495bfc651980f26170e024774b29bf3cc66aa464187` |
| `docs/rawpedia_collection.md` | `234766dbe5ace8f8ccef4965a32ced0b79ad55939a2363bfb0ebae126863a7a0` |
| RawPedia 목록 집계(`input_manifest.rawpedia_files_sha256`) | `241c48434bab72cceacfdcc083869c4e27265e4b474d48988fab0f0cb813f56f` |

`prepare`는 다음을 검증하고 `data/chunks/t08-2/manifest.json`에 고정한다.

1. 위 파일 지문과 골드의 `input_manifest`를 대조한다. RawPedia 집계는 기존 `compute_rawpedia_files_sha256()`의 직렬화 방식으로 계산하고, 저장된 T8-1 source manifest의 **116개 파일별 해시**도 대조한다. 현재 원문에서 다시 만든 해시만 서로 비교하는 검사는 입력 드리프트를 놓친다.
2. GitHub 후보의 모든 `source_locations` 파일/본문 해시, `curated_content` 범위·복사 텍스트, thread 지문을 검증한다. `src/artagent/issue_filter.py`의 `load_sources()`와 thread 구성·지문 함수를 재사용한다. 전체 스레드 기준선에 쓰는 추가 댓글도 별도 파일·본문 해시로 고정한다.
3. 100개 query ID의 유일성, 95/5 분리, 147개 근거의 원문·UTF-8 경계·해시를 전수 검사한다. 각 GitHub 근거는 해당 `curated_content_index`의 허용 범위 안이어야 한다.
4. dataset/schema/rules 버전, 조사 HEAD/실행 HEAD, 동기화 시각(`2026-09-28T02:06:12Z`), 출처 목록 및 입력 지문을 저장한다. 벤치마크 직전·재실행 직전에도 검사한다.

경로 이탈, 원문 누락·추가, 해시 불일치, stale curation, 유효하지 않은 근거가 하나라도 있으면 실패한다. 원문을 다시 수집하거나 골드를 자동 재생성하여 실험을 계속하지 않는다. 재고정이 필요하면 별도 dataset/run ID와 변경 근거를 남기고 전 조합을 다시 실행한다.

## 3. 공통 청크·원문 위치 계약

### 3.1 필수 스키마

후보별 **UTF-8 JSONL, 1행=1검색 청크**를 사용한다. 청크 본문과 임베딩 벡터는 분리 저장한다.

| 필드 | 타입 및 규칙 |
|---|---|
| `chunk_id` | string. `t08c:v1:<source_type>:<rule_id>:<digest>`; 아래 결정적 ID 규칙 적용 |
| `source_type` | `rawpedia` 또는 `github`; Issue/Discussion 구분은 metadata의 `source_kind` |
| `doc_id` | RawPedia는 T8-1과 같은 `rawpedia:<상대 경로에서 .md 제거>`; GitHub 단일 원문 청크는 `ref_id`, 다중 원문 스레드/Q&A는 `candidate_id` |
| `section_title` | RawPedia 실제 제목 경로, 제목 없으면 실제 page title; GitHub 단일 원문은 `/body`, 스레드는 원본 title |
| `content` | 검색에 반환할 원문 텍스트. 단일 segment는 원문 슬라이스 그대로; 다중 segment는 명시한 순서와 구분자로 직렬화 |
| `char_range` | `[start,end)`의 두 정수. 단위는 Python Unicode code point; 기준은 `metadata.range_basis` |
| `metadata` | 아래 provenance·규칙·범위·제품/지식 상태 정보; 원문 위치를 재구성할 수 있어야 함 |

`metadata` 필수 내용:

- `schema_version`, `rule_id`, `rule_fingerprint`, `content_sha256`, `source_group_id`, `product_scope`, `range_basis`, `section_kind`, `section_path`, `source_segments`.
- RawPedia: `page_title`, `target_url`, `upstream_source_url`, `source_path`, `source_file_sha256`. `product_scope=rawtherapee_reference`; ART로 도구명·PP3·CLI를 치환하지 않는다.
- GitHub: `candidate_id`, `source_kind`, `thread_sha256`, 원본 title/URL, `knowledge_status`, `limitations`, `relations`, `accepted_answer_availability`, source별 actor/시각/`source_role`. `product_scope=art_snapshot`. 원문 내 가설·실패 보고·버전/플랫폼 한계를 유지한다.
- `source_segments` 각 원소: `doc_id`, `source_path`, `source_file_sha256`, `json_pointer`, `char_start`, `char_end`, `byte_start`, `byte_end`, `content_char_start`, `content_char_end`, `target_url`, `segment_sha256`. GitHub는 추가로 `ref_id`, `body_sha256`, `curated_content_index`(미선택 원문이면 null), `source_role`, `curated`를 기록한다.

### 3.2 범위의 기준과 복합 청크

| 청크 | `char_range` 기준 | source segment의 기준 |
|---|---|---|
| RawPedia 단일 구간 | `range_basis=source_file`: frontmatter 포함 **전체 Markdown**을 디코딩한 문자열의 절대 위치 | 같은 물리 파일의 문자/UTF-8 바이트 위치; `json_pointer=null` |
| GitHub 단일 body 구간 | `range_basis=json_body`: 원본 JSON의 `/body` 디코딩 문자열 전체 | body 문자/바이트 위치; 물리 JSON 파일 바이트 위치와 구분 |
| 스레드 또는 복합 Q&A | `range_basis=serialized_content`: `[0,len(content))` | 서로 다른 body 각각의 절대 위치와 content 안의 위치를 별도로 보존 |

RawPedia는 `read_bytes().decode('utf-8')`, GitHub는 `json.loads(read_bytes())['body']`로 읽는다. `read_text()`의 줄바꿈 정규화나 `.strip()` 후 위치를 원문 위치처럼 저장하지 않는다. `byte_start=len(container[:char_start].encode('utf-8'))`, `byte_end`도 같은 방식으로 계산한다.

단일 원문 예: Q001의 source segment는 `rawpedia:Exposure`, 원문 `[156,288)` bytes이며 segment hash는 `b2051fffe4e88a3a4c93e57fadca2140280e446283ee0533341c517f76febbbd`다. ASCII인 이 구간은 문자 위치도 같지만, 일반적으로 문자와 바이트 수는 다르다.

복합 청크 예: D #442의 원문 본문 + 두 정제 댓글을 스레드로 묶으면 top-level `doc_id=github:artraweditor/ART:discussion:442`다. 그러나 Q099/Q100 등의 근거 연결은 `source_segments[].doc_id=discussion-comment:DC_kwDONWPV1M4A7hf1` 등 **실제 댓글 ID**로 해야 한다. top-level ID를 `gold_support_doc_ids`와 바로 비교하면 정답 스레드도 오답 처리된다.

다중 원문은 `부모 → (created_at, ref_id) 오름차순 댓글`로 연결한다. 구분자/원문 라벨은 `\n\n[<source_kind> <ref_id>]\n`으로 고정하고, 생성한 구분자·title·임베딩 prefix는 evidence 범위에 포함하지 않는다. 모든 원문 조각의 `content_char_*`를 기록하여 원문과 역대조한다. Discussion의 시간순은 표시 순서일 뿐 답글/확인 관계 증거가 아니다.

### 3.3 결정적 ID와 T9 Chroma 직렬화

ID digest는 `schema_version + rule_fingerprint + source_type + doc_id + 순서 있는 source segment 식별자/해시/범위 + content_sha256`의 canonical JSON(`sort_keys=True`, 고정 separators, UTF-8)의 SHA-256 전체다. 시각, 실행 경로, 배치 순서, 임베딩 모델은 ID에 넣지 않는다. 규칙 fingerprint에는 경계·오버랩·직렬화 규칙과 **경계 계산에 사용한 tokenizer revision 집합**을 넣는다. 같은 규칙/입력은 같은 순서·ID·JSONL 바이트를 만들어야 한다.

Chroma에는 `ids=chunk_id`, `documents=content`, **명시적으로 계산한 embeddings**, scalar metadata(`source_type`, `doc_id`, `candidate_id`, `source_group_id`, `rule_id`, `section_title`, `trace_ref`, `content_sha256`, `product_scope`, `knowledge_status` 등)를 넣는다. 해당하지 않는 nullable 값은 metadata에서 생략한다. 복합 배열/객체는 정본 JSONL에 보존하고 `trace_ref=chunk_id`로 조회한다. 이 방식은 source segment를 지우지 않고 Chroma metadata의 중첩 값 처리 차이를 피한다.

`gold_*`, query ID, 질문·참고 스팬·분류 label은 Chroma documents/metadata나 embedding input에 넣지 않는다. T9는 `doc_id`/`candidate_id`로 갱신 대상을 찾고, `trace_ref`로 원문 위치를 반환할 수 있어야 한다.

## 4. 청킹 후보 설계

### 4.1 공통 경계 규칙: 모델 간 같은 청크셋

청크 크기를 문자 수로 토큰 수처럼 취급하지 않는다. 경계 기준 tokenizer는 `BAAI/bge-small-en-v1.5`의 fast tokenizer로 고정하고 revision을 기록한다. 실험 대상 모든 모델의 tokenizer로 **title/절 정보·모델 prefix·special tokens까지 포함한 실제 입력 길이**를 검사한다.

- 첫 후보 값은 본문 목표 **192 reference tokens**, 슬라이딩 overlap **32 tokens**다. 이것은 실험 시작 값이며 최종 운영 규칙으로 확정한 값이 아니다.
- 제목/절 정보는 임베딩 입력에 `page_title 또는 thread_title + '\n' + section_title + '\n' + content`로 추가하되, 이미 같은 제목이면 한 번만 넣는다. 헤더가 32 reference tokens를 넘으면 tokenizer offset의 원문 경계에서 32개로 자르고 표시용 전체 제목은 metadata에 보존한다.
- 각 모델의 실제 `max_seq_length` 이하로 들어오도록 **동일한 공통 경계**를 줄인다. MiniLM의 기본 256을 임의로 512로 늘리지 않는다. 줄인 청크를 모델마다 따로 만들지 않는다.
- 토큰 경계는 tokenizer offset mapping을 문자 경계로 변환한다. 인코딩한 ID를 decode하여 content를 재생성하면 원문 공백·Unicode가 달라질 수 있으므로 사용하지 않는다.
- 길이를 초과한 문장/표/목록/코드 블록은 강제 분할하되 source segment를 보존하고 `oversize_split` 사유를 기록한다. 모든 실제 임베딩 입력에서 묵시적 truncation은 **0건**이어야 한다.
- 마지막 조각, 첫 제목 이전 본문, 제목 없는 페이지를 버리지 않는다. 공백만인 구간은 생략 가능하나 생략 위치·이유를 기록한다. 본문 의미 문자와 정제 구간의 합집합 coverage는 100%여야 한다.

네 모델의 tokenizer가 준비되면 경계 규칙·revision·파일 지문을 고정한다. 특정 모델을 실행 환경 문제로 제외하면 그 사실과 확정된 tokenizer 집합을 기록한 뒤 청크셋과 전체 실험 행렬을 다시 고정한다. 결과 점수를 본 뒤 경계나 overlap을 조합별로 바꾸지 않는다.

### 4.2 RawPedia 두 후보

| 규칙 ID | 생성 규칙 | 긴 구간/오버랩 | 비교할 가설 |
|---|---|---|---|
| `R-A-heading` | frontmatter를 위치만 유지해 제외. H2/H3의 실제 계층으로 원문을 연속 leaf 구간으로 나누고 같은 구간의 문단·목록·표·코드 블록을 목표 192 tokens까지 묶음 | 짧은 H3를 다른 H2/H3와 합치지 않음. 보통 overlap 0; 한 블록 자체가 초과하면 문장/토큰으로 나누고 그 블록 안에서만 overlap 32 | 도구/하위 제어의 의미 경계를 보존하면 혼동이 줄어드는가 |
| `R-B-window` | frontmatter 이후 페이지 본문을 문장 경계를 우선하는 192-token sliding window로 순회. H2/H3 경계를 넘는 것을 허용 | overlap 32, 목표 stride 160; 한 문장이 너무 길면 토큰 경계로 분할. 최종 tail 보존 | 경계 근처의 조건·비교 근거를 overlap으로 더 잘 회수하는가 |

`R-A-heading`의 H4 이하 제목은 해당 H3 본문 안에 보존하며 metadata에는 실제 전체 heading path를 담는다. 코드 fence 내부의 `##`를 제목으로 파싱하지 않는다. ATX/setext 제목·반복 제목·HTML 블록을 fixture로 확인한다. 제목 없는 `Channel_Mixer.md`, `RGB_and_Lab.md`, `Impulse_Noise_Reduction.md`는 `section_kind=page_body`, 빈 heading path로 같은 본문 분할을 적용한다. `Sharpening.md`의 반복 `Radius`는 제목 문자열만으로 구분하지 않고 계층과 절대 위치로 구분한다.

R-B의 문장은 `.?!` 뒤 공백/줄바꿈 경계를 사용하되 backtick/fenced code와 URL 내부에서는 끊지 않는다. 문장 offset을 원문에서 유지하고 구간을 선택한 뒤 전체 모델 길이 guard를 적용한다. overlap은 직전 window 끝에서 reference tokens 32개에 대응하는 문자 시작점으로 계산한다. 길이 guard로 window가 짧아져 overlap이 전진을 막으면 overlap을 줄이고 실제 값을 저장한다. `next_start > current_start`, tail 도달, 의미 문자 coverage를 검사한다.

첫 실행은 위 두 후보로 제한한다. 크기 민감도를 추가한다면 기존 후보를 유지한 채 `R-B-window-128-o24` 같은 **새 rule ID**를 미리 등록하고 모든 모델/양쪽 GitHub 규칙에 교차 실행한다. 점수 보고 후 특정 질문에만 맞춘 분할은 금지한다.

### 4.3 GitHub: 전체 스레드와 유의미 단위

전체 스레드 요청과 T10-2a의 정제 범위를 함께 검증하기 위해 A를 두 변형으로 기록한다. **A-full은 전체 댓글을 실제로 포함하는 비교 기준선**, A-curated와 B-unit은 기존 정제 범위 안에서 선택 가능한 두 규칙이다. A-full의 성능이 좋아도 미선택 댓글을 T9의 정제 코퍼스로 자동 승격하지 않는다.

| 규칙 ID | 내용/검색 단위 | T9 선정 자격 |
|---|---|---|
| `G-A-full-thread` | 포함된 12개 후보의 원본 부모 `/body` + 해당 스레드의 **모든 저장된 댓글 39개**를 한 논리 청크로 직렬화; 미선택·감사 댓글도 provenance와 `curated=false`로 구분 | 정제 밖 문맥의 효과·노이즈를 측정하는 진단 기준선 |
| `G-A-curated-thread` | 각 후보의 `curated_content` 35개 조각을 부모/시간순으로 모은 스레드 청크. 제거한 푸터·미선택 댓글은 다시 넣지 않음 | 선택 가능: 스레드 수준 문맥 보존 |
| `G-B-curated-unit` | 각 `curated_content` 조각을 독립 청크로 사용. 긴 조각은 공통 길이 guard로 문단/문장 분할; 원문 role과 후보 연결 보존 | 선택 가능: 작은 기술 문맥의 정밀 검색 |

전체 스레드 수집은 `load_sources()`가 만든 thread를 `source_record_key`로 찾아 사용한다. 후보 파일의 `source_locations`는 전체 댓글 목록이 아니다. 관계의 상대 항목 #503/#510 등은 metadata만 보존하고 정제 후보 밖 원문을 추가 적재하지 않는다.

B-unit의 기본은 **이미 정제된 유의미 body/댓글 단위**다. `guidance`, `explanation`, `reported_fix`, `confirmation`, `caveat`, `reproduction`, `context`를 짧다는 이유로 다시 제거하지 않는다. I #500 댓글은 67문자로 실제 제약 근거이고, D #489 댓글은 72문자로 완결된 안내다. `thanks` 단어 포함 여부로 의미 있는 확인을 지우지 않는다.

Q/A를 묶는 확장 후보는 명시적인 질문–답변 관계가 있을 때만 만든다. 현재 Discussion reply 계층이 없으므로 시간상 인접한 두 댓글을 Q/A로 추정하지 않는다. 최초 행렬에서는 B-unit을 쓰고, Q/A 확장은 별도 rule ID/근거가 있을 때 추가한다.

### 4.4 긴 스레드를 한 검색 단위로 유지하는 임베딩 정책

스레드를 한 번 encode하여 256/512 tokens 뒤를 버리면 비교 자체가 잘못된다. G-A 두 변형은 **한 논리 청크/한 벡터**를 유지하되 전체 내용을 공통 guard를 만족하는 내부 window로 나눈다.

1. 직렬화된 source segments를 순회하면서 reference 목표 192 tokens, **overlap 0**인 내부 windows를 만든다. 원문 라벨·title을 포함한 입력 길이를 전 모델에서 검사하고 source coverage 100%를 확인한다.
2. 모델별 prefix를 한 번 붙여 각 window를 encode/L2 normalize한다.
3. `v_thread = normalize(sum(w_i * v_i) / sum(w_i))`; `w_i`는 해당 window에 포함된 원문 본문의 reference token 수다. 생성한 라벨/title token은 가중치에서 제외한다. 빈 본문 window는 생성하지 않는다.
4. `embedding_policy=thread_window_mean_v1`, window 범위·입력 해시·가중치·개수·총 encoder 호출량을 캐시에 저장한다. mean vector의 0/NaN 여부를 검사한다.

단일 길이 안에 들어오는 스레드는 같은 식의 window 1개다. R-A/R-B/G-B는 직접 encode하는 물리 청크를 사용한다. 이 실험은 순수 경계뿐 아니라 **스레드 벡터 집계 정책을 포함한 스택**의 비교라고 리포트에 명시한다. 반환 스레드 content는 전체를 반환하며, 숨은 window를 별도 top-k 결과처럼 세지 않는다. 긴 청크가 Hit를 얻는 대가로 늘리는 context tokens도 §7에서 보고한다.

## 5. 임베딩 모델 후보와 로컬 실행 계약

### 5.1 비교 후보

아래 문서의 사양을 확인했다. 실행 시 Hub의 **불변 commit revision**과 실제 `get_sentence_embedding_dimension()`, `max_seq_length`, tokenizer/pooling 설정을 확인하여 기록한다. 온라인 leaderboard 수치를 이 코퍼스의 성능으로 대입하지 않는다.

| 모델 ID | 차원 / 기본 입력 한도 | 임베딩 입력 처리 | 후보 역할 |
|---|---|---|---|
| `BAAI/bge-small-en-v1.5` | 384 / 512 tokens | query에 `Represent this sentence for searching relevant passages: `, 문서에는 instruction 없음 | 영문 경량 검색 기준선 |
| `BAAI/bge-base-en-v1.5` | 768 / 512 tokens | BGE-small과 동일 instruction | 품질 증가가 속도·메모리 증가를 상쇄하는지 비교 |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 / **256 tokens** | query/doc prefix 없음, 배포된 SentenceTransformer pooling 사용 | 작은 일반 임베딩 모델의 속도 기준선 |
| `intfloat/multilingual-e5-small` | 384 / 512 tokens | query에 `query: `, 문서에 `passage: `; 한국어도 같은 prefix 적용 | 한국어 질문–영문 코퍼스의 언어 간 검색 후보 |

BGE 사양/instruction: [BGE-small 공식 모델 카드](https://huggingface.co/BAAI/bge-small-en-v1.5), [BGE-base 공식 모델 카드](https://huggingface.co/BAAI/bge-base-en-v1.5). MiniLM 차원/사용법: [공식 모델 카드](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), 256 한도: [배포 설정](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/main/sentence_bert_config.json). E5 차원·언어·prefix·입력 한도: [제공자의 모델 카드](https://huggingface.co/intfloat/multilingual-e5-small/blob/main/README.md).

100개 질문 모두 한국어를 포함한다. 영문 BGE/MiniLM의 언어 간 성능은 확인 전 보장하지 않으며, 다국어 E5도 자동 선정하지 않는다. **같은 원본 한국어 질의**로 비교한다. 모델별로 번역 질의를 제공하거나 한국어를 삭제하면 같은 실험이 아니다.

### 5.2 환경 준비 및 설치 시점

이 워크트리에는 `venv/`가 없다. 현재 사용 가능한 기존 interpreter는 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3` **3.14.3**, macOS arm64이고 `pytest=9.1.1`은 설치되어 있다. 조사 시 `torch`, `sentence-transformers`, `transformers`, `tokenizers`, `numpy`, `chromadb`는 미설치였다.

- Step 1~2는 표준 라이브러리와 기존 pytest로 진행한다. Step 3의 실제 tokenizer 소비 직전에 `sentence-transformers`와 필요한 전이 의존성을, Step 4의 Chroma 소비 직전에 `chromadb`를 설치한다. numpy는 실제 벡터 연산/대조 검색 소비 때 확인한다.
- 설치 전 기존 venv의 `pip --version`, 패키지 목록, macOS/Python wheel 호환성을 확인한다. `pip install --dry-run --only-binary=:all: sentence-transformers` 및 이후 `chromadb`로 의존성 해결을 먼저 점검한다. 실제 설치 버전은 당시 root venv에서 검증된 버전으로 정하고 `pip check`를 통과시킨다.
- 설치 명령·실제 버전·최초 소비처를 `docs/pipeline_setup.md`에 기록한다. 이 플랜에서 미검증 버전 번호를 고정하거나 다른 Python venv로 바꾸지 않는다. 공식 설치 안내는 [Sentence Transformers](https://www.sbert.net/docs/installation.html), PyTorch 배포 확인은 [공식 PyPI 파일 목록](https://pypi.org/project/torch/)을 참조한다. Python 하한 충족만으로 모든 전이 의존성의 3.14 호환성을 단정하지 않는다.
- 각 모델을 CPU에서 불변 revision으로 로드하여 한국어 query 2개/영문 문서 2개를 encode한다. 차원·finite·norm·입력 한도·pooling을 확인한다. `trust_remote_code=False`로 로드 가능한 후보를 사용한다.
- 모델/토크나이저 파일은 명시한 작업 디렉터리에 캐시하고 revision/사용 파일 지문을 기록한다. 다운로드·모델 load 시간은 별도 측정한다. 이후 재실행은 해당 revision의 로컬 캐시로 한다.
- import/wheel/load 실패는 `unavailable`과 원인·명령·환경으로 기록한다. 한국어 대응 후보 또는 모델 2개 최소 조건을 충족하지 못하면 환경 준비 실패 상태이며, 최적 스택을 선정했다고 보고하지 않는다.

### 5.3 재사용할 인터페이스

초기 구현은 `src/artagent/chunking.py`와 얇은 CLI, `scripts/benchmark_embeddings.py`의 함수로 시작한다. T9가 검색 부분을 공통 모듈로 옮길 수 있도록 다음 계약을 분리한다. 패키지 전체 레이아웃을 새로 설계하지 않는다.

```python
load_documents(rawpedia_dir, candidates_path, source_manifest) -> list[SourceDocument]
chunk_document(document, rule, tokenizer_bundle) -> list[Chunk]
validate_chunk(chunk, source_documents) -> None
map_evidence_to_chunks(queries, chunks) -> GoldMapping

load_encoder(model_id, revision, device="cpu") -> Encoder
encode_documents(chunks, encoder, batch_size=16) -> numpy.ndarray  # [N, D]
encode_queries(texts, encoder, batch_size=1) -> numpy.ndarray       # [Q, D]
build_collection(client, experiment_id, chunks, vectors, settings) -> Collection
search(collection, query_vector, k=5) -> list[SearchResult]
evaluate_query(query, results, gold_mapping, ks=(1, 3, 5)) -> QueryMetrics
```

`Encoder`는 query/document prefix, revision, dimension, max length, pooling, normalize, thread pooling을 보유한다. `SearchResult`는 `rank`, `chunk_id`, `distance`, `cosine_similarity`, `source_type`, `doc_id`, `trace_ref`, 전체 source segments를 반환한다. T9에서 같은 encoder와 검색 경로를 재사용한다.

벡터는 **float32, L2 norm 1**로 통일한다. SentenceTransformer의 배포된 pooling을 사용하고 `encode(..., normalize_embeddings=True, convert_to_numpy=True)` 뒤 dtype/shape/norm을 검사한다. zero/NaN/Inf 벡터는 실패하고 `abs(norm-1) <= 1e-5`를 확인한다. query prefix는 한 번만 붙인다. 코사인 유사도는 `q @ documents.T`, cosine distance는 `1 - similarity`이며 Chroma distance는 작을수록 가깝다. E5 예제의 `*100`은 적용하지 않는다. 정규화·encode 인자는 [SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)를 참조한다.

## 6. 실험 행렬과 Chroma 실행기

### 6.1 결과를 보기 전에 행렬 고정

정식 선정 행렬은 `(R-A-heading, R-B-window) × (G-A-curated-thread, G-B-curated-unit) × 실행 가능한 모델`이다. 4모델이면 **16조합**, 최소 2개 모델이면 8조합이다. 전체 댓글 기준선은 `RawPedia 2규칙 × G-A-full-thread × 동일 모델`로 추가 8조합(최소 4조합)이다. **4모델 실행 시 총 24조합**을 비교표에 남긴다.

각 조합에는 RawPedia 116문서에서 생성한 해당 규칙의 모든 청크와 GitHub 12후보에서 생성한 해당 규칙의 모든 청크를 함께 적재한다. 두 출처를 각각 독립 검색한 최선 점수를 혼합 검색 결과처럼 합치지 않는다.

후보 JSONL, encoding policy, 모델 revision, k, dtype, device, prefix, index 설정, 평가 기준의 fingerprint로 `experiment_id`를 만든다. 모델/차원/규칙이 다른 조합은 별도 collection에 둔다. 동일 client/work-dir에서 조건을 맞추며 T9의 실제 저장소는 후속 작업에서 구성한다.

### 6.2 Chroma 고정 조건

- 로컬 `chromadb.PersistentClient(path=<work-dir>/chroma)`을 사용한다. `embedding_function=None`으로 collection을 생성하고, `add/upsert`에 계산한 vectors, `query`에 `query_embeddings`를 명시한다. 다른 기본 모델이 자동 실행되지 않는지 smoke test한다.
- 초기 비교값은 전 조합에서 `configuration={"hnsw": {"space": "cosine", "ef_construction": 200, "ef_search": 200, "max_neighbors": 16, "num_threads": 1}}`로 통일한다. 설치한 Chroma 버전에서 지원 여부를 preflight로 확인하고 적용된 실제 값도 저장한다. 현행 API는 [공식 collection 설정](https://docs.trychroma.com/docs/collections/configure)을 참조한다.
- `chunk_id`로 정렬한 같은 순서/배치 크기로 적재한다. collection 이름은 `t08-2-<fingerprint>`의 ASCII 문자열이다. 전체/source별 count, ID/trace roundtrip이 기대값과 일치해야 측정한다.
- 모든 100문항을 **source/doc/category의 where filter 없이** `n_results=5`로 조회한다. 예상 출처를 검색 전에 사용하지 않는다. 같은 상위 5개에서 Hit@1/3/5를 계산한다. 전체 스레드 기준선의 GitHub 청크가 12개여도 RawPedia와 함께 검색한다.
- 반환 순서는 distance 오름차순, 정확한 동점은 chunk_id 오름차순으로 정한다. Chroma가 반환하지 않은 후보를 추가하지 않는다. 5위 경계의 동점은 로그에 남기고 재현 비교에서 같은 거리의 후보 집합도 확인한다.
- 출처별 지표는 **질문 쪽 source_type으로 집계**한다. 반환 출처로 질문을 재분류하지 않는다. 반환 청크의 출처 구성과 다른 출처로의 혼동도 기록한다.

조회/반환 필드는 [Query and Get 공식 명세](https://docs.trychroma.com/docs/querying-collections/query-and-get)를 참조한다. 지표 산출용 결과는 documents와 metadata도 받아 실제 반환 본문을 확인한다.

### 6.3 캐시와 ANN 검색 누락 검사

embedding cache key는 청크셋 SHA, 모델 revision, 실제 입력 문자열 SHA, prefix/pooling/thread policy, dtype다. query cache에는 질문 JSON SHA와 전체 query ID/원문/prefix를 포함한다. 같은 RawPedia 청크를 GitHub 규칙마다 재인코딩하지 않는다. 실험 결과 캐시는 experiment ID로 구분한다.

전체 100문항의 float32 정규화 벡터로 NumPy 전수 코사인 top5도 별도로 계산한다. Chroma top5와의 집합 일치율(`ANN overlap@5`), 동점, 최대 score 차이를 보고한다. 이 검사는 gold와 무관하다. 조합별 평균 overlap이 0.98 미만이면 index 적용/설정/encode 오류를 조사하고 해결 전에는 선정 대상으로 삼지 않는다. index 조건을 바꾸면 새 공통 조건으로 **전 조합을 재적재·재측정**한다. NumPy 결과를 Chroma의 Hit/MRR로 기록하지 않는다.

주 실험은 CPU/float32, torch thread 수 4(논리 CPU가 4개 미만이면 해당 수), seed 42, 문서 encode batch 16으로 통일한다. OOM으로 batch를 줄이면 해당 모델의 모든 조합을 같은 값으로 다시 실행하고 기록한다. MPS/CUDA는 선택적인 추가 속도 실험으로 따로 보고한다. 모델 실행, index 구성, 시간 측정을 동시에 돌리지 않는다.

## 7. 골드 매핑과 평가 지표

### 7.1 원문 스팬에서 정답 청크 집합 만들기

T8-1 정본은 `queries[]`다. `doc_id`/`gold_support_doc_ids` 일치는 필요조건이며, 같은 페이지의 다른 절을 정답으로 처리하지 않는다. 각 `evidence`와 청크의 source segments를 다음 순서로 대응한다.

1. `source_path`, `source_file_sha256`, `json_pointer`, `doc_id/ref_id`, GitHub의 `body_sha256`가 같은 원문인지 확인한다. GitHub는 `candidate_id`와 허용 curated 범위도 대조한다.
2. 문자/UTF-8 바이트 범위를 동일 원문 좌표에서 비교한다. 청크 본문과 실제 원문 슬라이스의 일치는 §3에서 검증한다. 제목·구분자·prefix는 근거 범위에 포함하지 않는다.
3. `coverage(e, C)`는 청크 집합 C의 일치 segment 범위의 **합집합**에 포함되는 evidence 비공백 문자 수 / evidence 전체 비공백 문자 수다. overlap 청크가 같은 범위를 반환해도 중복 가산하지 않는다.
4. 단일 청크 관련성은 `rel(q,c) = any(coverage(e,{c}) >= 0.5 for e in support_evidence(q))`다. **50%를 사전에 고정**하여 한 문자 교차만으로 정답 처리하지 않는다. 상당 부분의 원문 근거 회수를 주 관련성 기준으로 삼고 완전한 근거 회수는 별도 지표로 판정한다.

`gold_mapping.json`에는 query ID, 모든 evidence의 위치/역할, 대응 청크와 coverage, 여러 청크로 나뉜 스팬을 저장한다. 청크 생성은 gold를 보고 경계를 조정하지 않고 매핑을 별도 후처리로 수행한다. **각 후보 규칙의 전체 청크셋**에서 해당 출처의 모든 evidence coverage가 1.0인지 검사한다. 단일 청크에서 0.5에 도달하지 못하는 긴 스팬은 해당 규칙의 구조적 한계로 기록하고 gold를 줄이지 않는다.

현재 JSON의 GitHub `section_kind`는 `json_pointer`, `section_path=["body"]`다. 기존 플랜의 `json_field` 표기로 바꾸지 않고 실제 `json_pointer="/body"`와 원문 좌표를 우선한다. `section_title` 또는 URL 문자열만으로 정답을 판정하지 않는다.

### 7.2 Hit/MRR 및 복합 근거

`P_s`는 출처 s의 양성 질문 집합, `R_q`는 동일 혼합 collection이 반환한 순위별 청크다. k는 **1, 3, 5**, 주 선정 지표는 MRR@5로 고정한다.

```text
r_any(q) = rel(q, R_q[r])가 처음 true인 순위, 없으면 infinity
Hit_any@k(q) = 1 if r_any(q) <= k else 0
RR_any@k(q) = 1 / r_any(q) if r_any(q) <= k else 0

Hit_all@k(q) = 1 if 모든 support evidence e에서 coverage(e, R_q[:k]) >= 0.5 else 0
FullEvidence_all@k(q) = 1 if 모든 support evidence e에서 coverage(e, R_q[:k]) = 1.0 else 0

Hit@k(s) = sum(Hit_any@k(q), q in P_s) / len(P_s)
MRR@k(s) = sum(RR_any@k(q), q in P_s) / len(P_s)
Macro(metric) = (metric(rawpedia) + metric(github)) / 2
Micro(metric) = (80 * metric(rawpedia) + 15 * metric(github)) / 95
```

리포트의 `Hit@1/3/5`, `MRR@5`는 위 **any** 기준이라고 명시한다. MRR@1/3도 출력한다. All/FullEvidence는 별도 열로 둔다. complex 45문항에서는 일부 근거/전체 필수 근거의 회수를 구분한다. All은 top-k의 원문 범위 합집합이므로 분할된 스팬도 회수할 수 있다. 단일 청크 관련성인 any와 계산 방식이 다르다.

원문 ID 일치의 doc-level Hit는 진단 열로 추가할 수 있지만 주 지표를 대체하지 않는다. 순위는 **청크 순위**이며 같은 문서의 overlap 청크도 top-k 자리를 차지한다. 문서 중복을 제거하고 추가 검색하면 다른 실험이다.

단위 테스트 예: 2위가 e1의 80%, 3위가 나머지 20%, 4위가 e2의 60%, 5위가 나머지 40%를 포함하면 Hit@1=0, Hit@3=1, Hit@5=1, MRR@5=0.5, All@3=0, All@5=1, FullEvidence_all@5=1이다. 다른 doc/body의 같은 문자열은 coverage가 0이다.

### 7.3 negative 5문항

Q096~Q100은 `expected_behavior=unsupported_or_insufficient_evidence`, `gold_support_doc_ids=[]`, evidence role=`counterevidence`다. 전체 100문항을 검색하되 이 5문항의 양성 Hit/MRR는 **null/N/A**, 분모는 95다. 실패 0점이나 자동 성공 1점으로 넣지 않는다.

별도 5문항에서는 같은 원문 위치 대응으로 `counterevidence_Hit@1/3/5`, `counterevidence_FullEvidence_all@5`, 반환 청크 및 제약/대안의 원문을 저장한다. 이는 반증 검색 성능이며 답변 거절·환각 억제 성공률은 아니다. 답변을 생성하지 않는 T8-2에서는 해당 평가는 미실시라고 적고 T11/T23에 전달한다. 코사인 값만으로 거절하는 threshold를 이 5문항에 맞춰 학습하지 않는다.

### 7.4 지연·크기·실행 부담

| 지표 | 측정 방법/단위 |
|---|---|
| 주 query latency | `perf_counter_ns`: prefix/tokenize→query encode→Chroma query→반환 구조화. **초/쿼리**, batch 1, query embedding cache 미사용 |
| 지연 세부 항목 | `encode_seconds`, `search_seconds`, `result_materialization_seconds`, `total_seconds`; 지표 계산/로그 쓰기는 측정 밖 |
| warm 측정 | 모델/collection마다 고정 첫 10문항 warmup 뒤 seed 42 순서의 100문항을 3회 실행. 총 300관측(출처별 240/60), 평균/중앙값/p95를 보고; p95는 nearest-rank `ceil(0.95*N)-1` 인덱스 |
| cold 및 구축 부담 | 모델 download/load, 첫 encode, 전체 문서 encode, Chroma 구성 시간을 query latency와 구분 |
| 임베딩 크기 | D/dtype, `D * 4` bytes/vector(384→1,536, 768→3,072), 출처별 N, `N * D * 4`, 실제 `.npy` 크기 |
| 메모리/저장 크기 | 모델 파일 bytes, 처리 RSS peak(측정 방식·OS 단위 명시), Chroma 전체 크기/collection 수/증가량. DB 크기와 순수 vector 용량 구분 |
| 청크/문맥 부담 | 출처별 청크 수, token/char min/median/p95/max, top5 반환 tokens와 원문 중복 제거 뒤 tokens, thread window 수/encoder 호출량 |
| 무결성 | truncation=0, 원문 의미 문자 coverage=100%, ID 중복=0, 복원 불가 segment=0, embedding finite/norm, 실패 행 수 |

품질 점수는 각 회차의 순위를 확인하고, 순위가 같으면 95개의 고유 양성 질문 점수로 보고한다. 3회 반복한 285개 관측을 독립 질문으로 취급하지 않는다. 캐시한 query vector로 순수 검색 속도를 측정할 수 있지만 주 latency를 대체하지 않는다.

## 8. 선정·재현·T9 인계

### 8.1 결과를 보기 전에 선정 순서 고정

1. 입력/청크/모델/Chroma 실행/ANN 검사를 통과한 **정식 행렬**만 선정 대상이다. G-A-full-thread는 진단 행으로 비교표에 남긴다.
2. 95개 양성의 **Macro MRR@5** 내림차순으로 정렬한다. 동률이면 Macro Hit@5, complex의 Macro FullEvidence_all@5, query p95초, 총 vector bytes, experiment ID 순으로 비교한다. 각 출처 결과도 병기한다.
3. 경량성에 따른 재선정은 미리 정한 범위 안에서만 허용한다. 선두와 Macro MRR@5 및 Macro Hit@5 차이가 모두 **0.01 이내**, 출처별 MRR@5 차이가 각각 **0.02 이내**인 조합을 근접 후보로 표시한다. 이 중 complex FullEvidence_all@5가 선두 이상인 후보에서 p95가 낮은 조합을 고르고, 동률이면 총 vector bytes, experiment ID 순으로 고른다. 선두도 이 후보 집합에 포함한다.
4. `selected`에 최종 R/G/model/policy/index 값, 선두와 차이, 적용한 선정 단계, 출처별 득실, 실패 query ID, 긴 청크의 문맥 부담을 기록한다. 근접 대안이 없으면 선두를 선택한다.

1/2 percentage point는 선정 절차의 근접 폭이며 WBS의 품질 합격 임계치나 통계적 유의차가 아니다. 이번에 별도 최소 Hit 합격선을 만들지 않는다. 전 조합의 절대 성능이 낮아도 수치/실패 분석과 고정셋 위의 비교 선정임을 명시한다. 최소 실행 조건을 충족하지 못하면 `selection_status=incomplete`, `selected=null`이다.

같은 100문항을 모델 선정과 후속 T23에 재사용하므로 독립 hold-out 성능이나 일반화 보장으로 표현하지 않는다. `source_group_id` 단위의 질문 상관성을 보존하고 평균 차이를 유의차라고 단정하지 않는다. 그룹 단위 paired resampling/RAGAS는 T23에서 다룬다.

### 8.2 재현 게이트

- 같은 입력/규칙/tokenizer revision으로 다른 위치에 다시 생성하여 **전 후보 JSONL의 바이트/ID/위치/content hash가 일치**해야 한다. 시각이 포함된 실행 로그는 비교 대상에서 분리한다.
- 전 조합의 저장된 query 결과에서 지표를 재계산하여 리포트 JSON의 분자/분모/값과 일치시킨다.
- 정식 선두, 최종 선정 조합(선두와 다르면), 차순위 조합을 새로운 Chroma 작업 위치에 재적재해 100문항을 재검색한다. 주 지표 절대 차이 `1e-9` 이내, vector는 `allclose(atol=1e-6, rtol=1e-5)`, distance 차이는 `1e-5` 이내를 초기 검증값으로 삼는다.
- ANN/동점의 순위 변동이 지표를 바꾸면 차이를 기록하고 원인을 해결한다. 허용 오차를 조용히 넓히지 않는다. latency는 동일값을 요구하지 않고 회차별 분포/환경 차이를 보고한다.

### 8.3 T9에 전달할 입력

리포트 JSON의 `selected`를 기계 판독용 선정 계약의 정본으로 사용한다.

| 인계 항목 | 필수 내용 |
|---|---|
| 청크 | 선정 RawPedia/GitHub JSONL 상대/실체 경로, 출처별 건수/SHA-256, source_segments 포함 schema version |
| 원문 고정점 | dataset ID, 질문 JSON SHA, source manifest SHA, RawPedia 집계 SHA, GitHub candidate/rules/thread SHA |
| 모델 | 전체 model ID, Hub commit revision, 로컬 cache 재확보법, tokenizer/pooling/prefix/입력 상한, D/dtype/norm, thread pooling |
| Chroma | 검증한 package version, cosine/HNSW 실제 값, 삽입 순서/배치, metadata flatten 규칙, 검색 결과 계약 |
| 재현 | 청크 재생성/적재/100문항 검색 명령, 환경 versions/seed, 전체 비교표/선정 순서, 재실행 차이 |
| 후속 갱신 | candidate_id→청크 ID 목록, RawPedia doc_id→청크 ID 목록. 원문/규칙 변경 시 ID 변경과 이전 ID 삭제 필요성 |

후보 청크는 `data/chunks/t08-2/`에 보존하고 선정 manifest에서 원래 파일을 참조한다. T9의 별도 워크트리에는 실체를 전달하거나 동일 main 입력에서 기록한 명령으로 재생성하고 SHA를 대조한다. 모델 cache/Chroma DB는 git에 커밋하지 않는다. T9는 실제 저장소 구성과 재적재·갱신·검색 제외 구현을 담당한다.

## 9. 산출물 구조와 리포트 명세

아래는 **후속 구현에서 만들 구조**다.

```text
src/artagent/chunking.py                    # 원문/segment/청크 생성·검증
scripts/chunk_corpus.py                     # prepare/build/check CLI
scripts/benchmark_embeddings.py             # preflight/run/check/report CLI
tests/test_chunking.py                     # 범위·결정성·실제 원문 회귀
tests/test_benchmark_embeddings.py          # 지표 및 Chroma roundtrip
tests/fixtures/chunking/                    # 작은 Markdown/JSON fixture
docs/pipeline_setup.md                      # 실제 설치 의존성 기록
docs/chunking_embedding_benchmark.json       # 전체 비교·선정·재현 정본
docs/chunking_embedding_benchmark.md         # JSON에서 생성한 보고서
data/chunks/t08-2/
  manifest.json                             # 입력/규칙/tokenizer revision
  rawpedia/R-A-heading.jsonl
  rawpedia/R-B-window.jsonl
  github/G-A-full-thread.jsonl
  github/G-A-curated-thread.jsonl
  github/G-B-curated-unit.jsonl
  gold_mapping.json                         # query/evidence→청크/coverage
data/embedding-benchmark/t08-2/<run-id>/
  environment.json                          # versions/hardware/model settings
  models/                                   # 고정 revision 로컬 cache
  vectors/<cache-key>.npy                    # ID 순서 sidecar와 벡터
  runs/<experiment-id>.jsonl                 # 100문항 top5/coverage/latency
  chroma/                                   # 공통 client의 실험 collection들
```

원문 snapshots, 정제 후보, 청크, vector state를 별도 영역에 보존한다. 큰 생성물인 `data/chunks/`, `data/embedding-benchmark/`는 구현 시 `.gitignore`에 추가하고 로컬에 보존해 T9로 인계한다. **git 관리하는 리포트에는 규칙, 입력/산출 SHA, 건수, 생성 명령을 남긴다.** 부동소수점 vector나 Chroma 내부 파일의 git 저장을 재현성의 대체물로 삼지 않는다.

JSON 리포트 필수 키:

- `schema_version`, `run_id`, `dataset_id`, `input_fingerprints`, `environment`, `model_candidates`(unavailable 포함), `chunking_candidates`, `evaluation_contract`, `chroma_settings`, `experiments`, `selection_order`, `selection_status`, `selected`, `reproduction`, `limitations`.
- `evaluation_contract`: ks=`[1,3,5]`, relevance coverage threshold=`0.5`, strict threshold=`1.0`, 합집합 정의, denominators rawpedia=`80`/github=`15`/positive=`95`/negative=`5`, evidence_count=`147`.
- `experiments[]`: ID, 정식/진단 구분, R/G/model/revision/policy, count/bytes, rawpedia/github/macro/micro의 Hit@1/3/5 및 MRR@1/3/5, complex Any/All/Full, negative 별도 표, latency 세부/분포, ANN 검사, 실패 원인, 100문항 로그 경로/SHA.
- query 로그: ID/source/category/intent/difficulty/group, 실제 top5 전체 ID/순위/source/distance/원문 위치, 대응 evidence/coverage, 지표/null, 3회 latency. 실패 문항도 오류 행으로 보존한다. 한 회차라도 100문항 검색에 실패한 조합은 완료 행으로 처리하지 않는다.
- Markdown 순서: 입력 요약→전 조합 비교표→출처별/complex/negative 세부→속도/크기→선정 순서/득실→재현법→제약. JSON에서 수치를 생성하며 수동으로 다른 수치로 고치지 않는다.

## 10. 필수 단위·회귀 테스트

| 검증 축 | 필수 사례와 판정 |
|---|---|
| Markdown 구조 | frontmatter 제외 뒤 절대 위치, H2/H3/H4/setext, code 안 가짜 heading, 반복 Radius, 첫 도입/제목 없음, 긴 표/코드, 마지막 tail |
| 문자/바이트 | CRLF, 한국어/이모지/결합문자, UTF-8 중간 경계 거부, 원문 범위와 content 범위 구분 |
| sliding window | stride 전진, overlap 양/경계, 짧은 페이지/긴 문장, 의미 문자 coverage100%, 비공백 누락0 |
| GitHub 원문 | body/file hash 분리, candidate/ref 구분, D #442 다중 segment, D #494 삭제 footer 보존, I #524 실패 버전 caveat 유지 |
| 짧은 정답 보존 | I #500의 67문자와 D #489의 72문자 유지, negative를 support로 바꾸지 않음 |
| 전체 스레드 | 선정 12부모+39댓글, 후보 밖 스레드 비적재, G-A-curated의 35조각/23댓글 범위 유지, reply 관계 비추론 |
| 변조 거부 | content 1문자, source hash/range/URL/ref/body hash 변조, manifest drift, path traversal 실패 |
| ID/결정성 | 두 번 생성 바이트 일치, 탐색 순서/작업 위치와 무관한 ID, 원문/규칙 변경 시 ID 변경, duplicate ID0 |
| 모델 입력 | prefix 한 번, 실제 token 상한, truncation0, thread windows 전체 범위, weighted mean/norm/float32, pooling 설정 보존 |
| 골드 매핑 | 동일 doc의 다른 절/다른 body의 동일 문장 거부, 50% 직전/경계, 범위 중복 비가산, 전체 147 evidence |
| 지표 | rank1/3/5/범위 밖, MRR 예, Any/All/Full, macro/micro, negative N/A/분모95, 부분 실패 조합 거부 |
| Chroma | 실제 2출처/vector add→query→trace roundtrip, count/차원, distance 방향, source filter 비사용, 동점 순서, 재개방 |
| 재현/표시 | 저장한 100문항 재집계, JSON→Markdown 일치, 실패 시 기존 성공 산출물 보존, 재적재 결과/지표 일치 |

주 로직은 작은 fixture와 수작업 vectors로 검증한다. 모델 semantic 성능을 고정 기대값의 단위 테스트로 만들지 않는다. 실제 원문/147스팬 회귀와 실제 Chroma roundtrip은 의존성 준비 뒤 반드시 실행한다. 테스트 중 숨은 네트워크 다운로드 대신 사전 cache를 쓰며 skip/xfail로 필수 검증을 줄이지 않는다.

## 11. Antigravity Step 1~6 체크리스트

WBS 8h를 다음과 같이 배분한다. 모델 download/전체 encode 대기 시간은 별도로 측정한다. 시간 내 미완료 조합은 상태를 저장하고 계속 실행하며 일부 조합만으로 완료를 보고하지 않는다.

### Step 1 — 입력 고정과 환경 조사 (0.75h, 선행: T4/T10-2a/T8-1)

대상: `scripts/chunk_corpus.py`, 청크 manifest, 기존 검증기. 새 의존성 설치는 아직 필요 없다.

- [ ] 116파일/12후보/35조각/39전체댓글/100문항/147스팬을 재집계하고 고정 manifest·원문을 전수 대조한다.
- [ ] prepare CLI로 입력/schema/rules/dataset/HEAD/URL/hash를 저장하고 기존 query/filter check를 실행한다.
- [ ] root Python/package/hardware/wheel 상황을 조사하고 모델 preflight 절차를 기록한다.

검증: 입력 오류0, query ID 유일, 95/5 분모, 기존 13개 query tests 통과. 다음 단계: Step 2.

### Step 2 — segment 및 골드 매핑의 작은 수직 구현 (1.25h, 선행: Step 1)

대상: `src/artagent/chunking.py`, `scripts/chunk_corpus.py`, `tests/test_chunking.py`, 작은 fixture.

- [ ] 범위/hash/변조/관련도 경계의 실패 테스트부터 작성한다.
- [ ] RawPedia 단락과 GitHub 단일/복합 segment로 원문→청크→저장→재읽기→gold coverage를 통과한다. 처음에는 fixture 경계를 쓴다.
- [ ] CRLF/이모지/비연속 source segment, candidate/ref 구분, negative N/A를 검증한다.

검증/checkpoint 1: 원문 위치 복원 및 관련도 분자/분모 테스트 통과. 좌표 계약을 확정한 뒤 전체 생성한다.

### Step 3 — tokenizer 준비와 전체 후보 생성 (1.75h, 선행: Step 2)

대상: 청킹 module/CLI/tests, `docs/pipeline_setup.md`, 생성 청크, `.gitignore`.

- [ ] 실제 tokenizer 소비 의존성을 root venv에 설치하고 실제 버전/최초 사용처를 기록한다. 모델/tokenizer revision을 고정한다.
- [ ] R-A/R-B/G-A-full/G-A-curated/G-B를 구현하고 길이/overlap/비공백 coverage/ID/segment/URL을 전수 검사한다.
- [ ] 모든 JSONL/gold mapping을 생성하고 147스팬의 출처별 전체 청크셋 coverage와 허용 범위를 확인한다. 다른 출력 위치에서 다시 생성해 바이트 비교한다.

검증: 정식 후보 출처별 2규칙 + 진단 1규칙, 원문 추적, 실제 tokenizer guard 통과. 청크 수는 실행 후 실측한다.

### Step 4 — 모델·Chroma smoke와 계측 구현 (1.25h, 선행: Step 3)

대상: `scripts/benchmark_embeddings.py`, `tests/test_benchmark_embeddings.py`, `docs/pipeline_setup.md`.

- [ ] chromadb를 소비 시 설치하고 pip check/import, 전체 모델 CPU smoke/thread pooling을 실행한다. 실행 가능한 모델을 확정한다.
- [ ] metric, 수작업 vector Chroma roundtrip, query cache 미사용 latency 테스트를 통과하고 정식 16 + 진단 8조합의 행렬을 저장한다.
- [ ] 고정 Q001/Q002/Q025/Q049/Q060/Q071/Q081/Q085/Q096/Q099의 10문항으로 각 모델/양쪽 출처의 encode→Chroma→trace→metric을 smoke한다. 점수를 보고 골드/규칙을 바꾸지 않는다.

검증/checkpoint 2: 2개 모델 이상(다국어 1개 이상), 혼합 검색, 명시 embedding, truncation0, negative null, distance/지표/분모 일치. smoke를 100문항 결과로 보고하지 않는다. tokenizer 준비 후 모델 제외가 발생하면 §4.1대로 후보 manifest와 전 행렬을 재고정한다.

### Step 5 — 전 조합·100문항 정량 실행 (2h, 선행: Step 4)

대상: runner, 실험 logs/vectors/Chroma, 리포트 JSON experiments.

- [ ] 고정 행렬 전체를 순서대로 적재하고 100문항×3회를 실행한다. 4개 모델이면 24조합, 각 조합 95양성 + 5negative다.
- [ ] 출처/macro/micro Hit/MRR, complex 전체 근거, negative 별도 평가, 지연/크기/메모리/문맥 부담, ANN 검사를 집계한다.
- [ ] 실패/출처 혼동/분할 스팬을 원문과 확인하고 순위·위치가 있는 100문항 로그를 저장한다. 실패 행을 제외하여 평균을 내지 않는다.

검증: 정식 전 조합 완주, 100문항 로그, 95/5 분모, 전체 비교표/재집계 일치. 다운로드/encode 초과 시간도 기록하고 남은 조합을 계속 실행한다.

### Step 6 — 선정·재현·T9 확정 인계 (1h, 선행: Step 5)

대상: `docs/chunking_embedding_benchmark.md/.json`, 선정 청크 manifest, 관련 상세 카드.

- [ ] §8.1로 공통 모델/R/G를 선정하고 정식 전체 비교/진단 차이/근거/출처별 득실/근접 후보를 기록한다.
- [ ] 선두/선정 조합/차순위를 새 Chroma에서 재실행하고 JSON→Markdown, 청크 재생성, 필수 tests를 통과한다.
- [ ] 실체/SHA/모델 revision/prefix/thread policy/index 설정/명령을 T9로 전달한다. 증거가 갖춰진 뒤 Task 8-2 완료 체크를 갱신한다.
- [ ] 코드/docs/작은 fixture의 diff를 확인하고 국문 commit/PR에 실측값과 검증을 쓴다. 원문/모델 cache/DB/큰 vectors의 의도치 않은 추가를 검사한다.

최종 게이트: **정식 전 조합 완주, 100문항 검색, 95양성/5negative 분리, 147근거 원문/청크 추적, 원문 coverage100%, truncation0, 재현 통과, 선정 JSON과 T9 실체 일치**.

## 12. 후속 CLI 계약과 실행 명령

기존 query/filter check 외에는 **후속 구현이 제공해야 하는 CLI**다. help와 실제 동작을 이 계약에 맞추고 저장소 root에서 실행한다.

```bash
ART_PIPELINE_PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3

# 기존 입력 검증
"$ART_PIPELINE_PY" scripts/generate_eval_queries.py check
"$ART_PIPELINE_PY" scripts/filter_issues.py --check
"$ART_PIPELINE_PY" -m pytest tests/test_eval_queries.py tests/test_filter_issues.py -q

# Step 1: 표준 라이브러리로 입력 고정
"$ART_PIPELINE_PY" scripts/chunk_corpus.py prepare \
  --rawpedia-dir data/rawpedia \
  --rawpedia-collection docs/rawpedia_collection.md \
  --github-candidates data/issues/search-candidates.json \
  --github-dir data/issues \
  --source-manifest docs/search_eval_source_manifest.json \
  --queries docs/search_eval_queries.json \
  --output-dir data/chunks/t08-2

# Step 3: 의존성 소비 시 설치한 뒤 tokenizer/revision 고정
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
  --stage tokenizers \
  --models BAAI/bge-small-en-v1.5 BAAI/bge-base-en-v1.5 \
    sentence-transformers/all-MiniLM-L6-v2 intfloat/multilingual-e5-small \
  --device cpu --work-dir data/embedding-benchmark/t08-2/run-001

"$ART_PIPELINE_PY" scripts/chunk_corpus.py build \
  --manifest data/chunks/t08-2/manifest.json \
  --model-manifest data/embedding-benchmark/t08-2/run-001/environment.json \
  --rawpedia-rules R-A-heading R-B-window \
  --github-rules G-A-full-thread G-A-curated-thread G-B-curated-unit \
  --target-tokens 192 --overlap-tokens 32

"$ART_PIPELINE_PY" scripts/chunk_corpus.py check \
  --manifest data/chunks/t08-2/manifest.json \
  --queries docs/search_eval_queries.json --verify-regeneration

# Step 4: 같은 revision으로 모델/Chroma 실제 실행 확인
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
  --stage runtime \
  --model-manifest data/embedding-benchmark/t08-2/run-001/environment.json \
  --device cpu --work-dir data/embedding-benchmark/t08-2/run-001

# Step 5: 고정 행렬과 100문항 실행
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py run \
  --chunk-manifest data/chunks/t08-2/manifest.json \
  --model-manifest data/embedding-benchmark/t08-2/run-001/environment.json \
  --queries docs/search_eval_queries.json \
  --ks 1 3 5 --device cpu --batch-size 16 --seed 42 \
  --warmup-queries 10 --query-repeat 3 \
  --work-dir data/embedding-benchmark/t08-2/run-001 \
  --output-json docs/chunking_embedding_benchmark.json

# Step 6: 재집계 및 별도 DB 재적재로 재현 확인
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py check \
  --input-json docs/chunking_embedding_benchmark.json \
  --verify-top-candidates \
  --work-dir data/embedding-benchmark/t08-2/recheck-001

"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py report \
  --input-json docs/chunking_embedding_benchmark.json \
  --output-md docs/chunking_embedding_benchmark.md

"$ART_PIPELINE_PY" -m pytest tests/test_chunking.py \
  tests/test_benchmark_embeddings.py tests/test_eval_queries.py \
  tests/test_filter_issues.py -q
```

`preflight --stage tokenizers`는 revision/tokenizer 준비만, `--stage runtime`은 같은 revision의 모델/Chroma smoke를 수행한다. 환경 기록이 늘어도 이미 고정한 tokenizer 집합/규칙 fingerprint는 변경하지 않는다. `build`는 원문 manifest를 보존하며 규칙/청크 SHA를 추가한다. `chunk_corpus check --verify-regeneration`은 임시 출력 위치에 생성하여 비교한다. `run`은 동일 fingerprint의 완료 행만 재사용하고 미완료 행은 다시 실행한다. `benchmark check`는 재현 로그를 work-dir에 저장하고 리포트의 reproduction 증거를 갱신한다. `report`는 해당 JSON에서 Markdown을 생성한다. 이 과정에서 원문/모델 선정 값/골드는 변경하지 않는다.

Antigravity는 위 순서를 따르고 미확인 항목을 추측으로 PASS 처리하지 않는다. 실행 불가 후보, 보존되지 않은 산출물, 미완료 재현 검사는 상태와 남은 작업을 JSON/Markdown 모두에 기록한다.
