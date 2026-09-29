# Task 8-2 문서 청킹 및 임베딩 벤치마크 실행 플랜

작성일: 2026-09-28 · 개정일: 2026-09-29 · 담당: 김대성 레인 · 구현 실행자: Antigravity(Gemini 3.8 Flash)

이 문서는 WBS Phase A의 **A-08 2/3·3/3, A-10 3/4**를 실행하기 위한 구현 계약이다. 목표는 두 출처의 후보 청크를 실제로 생성하고, 고정 100개 질문으로 **같은 임시 Chroma의 독립 컬렉션**에서 비교하여 **RawPedia 방식·크기·오버랩 + GitHub 방식·크기·오버랩 또는 내부 윈도우 크기 + 공통 임베딩 모델**을 함께 선정하는 것이다. **이번 개정의 실행 대상은 §15의 guard·검색 재현성 보정과 현행 정책 전체 조합 재측정**이다. §1~14의 이전 계약과 실행 결과는 이력으로 보존하며, 최신 180행으로 과거 전체 탐색을 대체하지 않는다. 새 플랜 작성은 추가 실험의 완료를 뜻하지 않는다.

권위 문서는 [WBS §5](ART_agentic_wbs.md), [Task 8-2 및 T9 상세 카드](../tasks/todo.md), [T8-1 전달 계약 §8](T08_1_execution_plan.md), [GitHub 정제 규칙](issue_filter_rules.md)다. WBS의 9/5~9/11 계획 일정은 보존하고, 실행 기록에는 실제 날짜를 쓴다.

**현재 상태:** 조사 HEAD `8b5719589`의 [현재 리포트](chunking_embedding_benchmark.md)와 JSON은 **180조합(Q-N=108/Q-P=72)** 및 잠정 선정 MRR@5=`0.7730`을 기록한다. 그러나 Q-N 생성에 4모델 공통 manifest를 사용하여 MiniLM의 256 입력 제한이 BGE/E5의 512 그룹에도 적용됐다. E5 448/O=32의 본문 실측 중앙값은 과거 423에서 이번 241 reference tokens로 줄었고, 현재 `check`에서 해당 행의 기록값 `0.7426`과 재계산값 `0.7259`가 달라 재현 검증도 실패했다. **최종 선정·T9 인계는 §15 완료 전까지 잠정 상태**다. 과거 4290조합과 E5/native 448/O=32의 MRR@5=`0.8032`는 보존된 이전 정책의 기준선이며, 이전 코드·청크로 임베딩 및 색인을 재생성한 독립 재현에서 `0.8032`를 확인했다. 새 정책으로 이 기준선과 나머지 과거 후보를 모두 다시 비교한다. 아래 과거 점수는 실행 이력이며 §15의 완료 증거로 사용하지 않는다.

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
- 최초 grid의 최소 완료 조건은 **실행 가능한 모델 2개 이상, 그중 한국어–영어 검색 후보 1개 이상**, 선택 가능한 방식 출처별 2개 이상과 §6.1 전체 행렬의 성공한 실행이다. 최초 grid와 N/P는 과거 정책의 실행 이력으로 보존한다. **이번 재측정의 완료 조건은 §15이며, 겹치는 실행·선정 조항은 §15를 적용**한다. 이전 실행 행을 현행 정책의 완료 증거로 대신하지 않는다. 실패 모델도 리포트의 실패 행으로 남기고 성능이 낮다는 이유로 대상을 빼지 않는다.

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

`prepare`는 다음을 검증하고 새 `data/chunks/t08-2-grid/manifest.json`에 고정한다. 기존 `data/chunks/t08-2/`의 기준선 청크와 manifest는 보존한다.

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

- `schema_version`, `rule_id`, `rule_fingerprint`, `content_sha256`, `source_group_id`, `product_scope`, `range_basis`, `section_kind`, `section_path`, `source_segments`, `rule_family`, `target_tokens`, `overlap_tokens`, `encoder_window_tokens`, `encoder_overlap_tokens`. 적용되지 않는 파라미터는 null로 명시하며, 각 물리 청크의 `actual_tokens`, `actual_overlap_tokens`, 길이/오버랩 조정 사유도 보존한다.
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

ID digest는 `schema_version + rule_fingerprint + source_type + doc_id + 순서 있는 source segment 식별자/해시/범위 + content_sha256`의 canonical JSON(`sort_keys=True`, 고정 separators, UTF-8)의 SHA-256 전체다. 시각, 실행 경로, 배치 순서, 임베딩 모델은 ID에 넣지 않는다. 규칙 fingerprint에는 **방식, target/overlap, encoder window/overlap, 경계 guard 정책**, 직렬화 규칙과 **경계 계산에 사용한 tokenizer revision 집합**을 넣는다. 같은 규칙/입력은 같은 순서·ID·JSONL 바이트를 만들어야 한다.

Chroma에는 `ids=chunk_id`, `documents=content`, **명시적으로 계산한 embeddings**, scalar metadata(`source_type`, `doc_id`, `candidate_id`, `source_group_id`, `rule_id`, `section_title`, `trace_ref`, `content_sha256`, `product_scope`, `knowledge_status` 등)를 넣는다. 해당하지 않는 nullable 값은 metadata에서 생략한다. 복합 배열/객체는 정본 JSONL에 보존하고 `trace_ref=chunk_id`로 조회한다. 이 방식은 source segment를 지우지 않고 Chroma metadata의 중첩 값 처리 차이를 피한다.

`gold_*`, query ID, 질문·참고 스팬·분류 label은 Chroma documents/metadata나 embedding input에 넣지 않는다. T9는 `doc_id`/`candidate_id`로 갱신 대상을 찾고, `trace_ref`로 원문 위치를 반환할 수 있어야 한다.

## 4. 청킹 후보 설계

### 4.1 크기·오버랩 탐색 공간과 공통 경계

경계 기준은 `BAAI/bge-small-en-v1.5`의 fast tokenizer이며 불변 revision을 기록한다. 크기/오버랩은 **원문 본문의 reference token 수**다. 제목/절 정보·모델 prefix·special tokens를 포함한 실제 입력 길이는 모든 비교 모델의 tokenizer로 검사한다.

| 탐색 축 | 필수 후보 | 목적 |
|---|---|---|
| 본문 목표 크기 L | **128, 192, 224 tokens** | 짧은 근거의 정밀성부터 더 넓은 문맥까지 공통 입력 한도 안에서 비교 |
| 물리 청크 오버랩 O | **0, 32, 64 tokens** | 중복 없음/중간/큰 중복의 근거 회수와 저장·검색 부담 비교 |
| 크기×오버랩 | **9쌍 전부** | O 효과와 L 효과 및 상호작용을 분리; 192/32는 기존 기준선 포함 |

```text
(L,O) = (128,0), (128,32), (128,64),
        (192,0), (192,32), (192,64),
        (224,0), (224,32), (224,64)
목표 stride = L - O > 0
```

128은 작은 문맥, 224는 MiniLM 기본 256 안에서 본문 이외 입력을 고려한 큰 공통 후보다. 이 값은 실측 최적값이 아니라 **탐색 범위**다. 모델별 토큰화가 다르므로 224가 항상 그대로 들어간다고 가정하지 않는다. `64/128=50%`, `64/224≈28.6%`처럼 같은 O의 상대 비율도 달라진다. nominal/실측 overlap 비율을 둘 다 보고한다. 최종 주장은 이 등록 범위에서의 최선 조합이며 전체 가능한 길이의 전역 최적값이라는 표현은 쓰지 않는다.

공통 생성 조건:

- 임베딩 입력은 `page_title 또는 thread_title + '\n' + section_title + '\n' + content`다. 동일 제목은 한 번만 넣고 헤더는 최대 32 reference tokens로 제한한다. 표시용 제목 원문은 metadata에 보존한다.
- 같은 `(방식,L,O)`의 청크셋은 모든 모델에서 공통으로 쓴다. 전체 모델 입력 한도를 만족하는 최대 문자 끝점을 찾아 경계를 줄이며 MiniLM 한도를 임의로 늘리지 않는다. guard 정책/fingerprint를 기록하고 **실제 encoder 호출 직전에도 길이를 검사**한다.
- reference tokenizer offset으로 원문을 슬라이스한다. token ID를 decode해서 content를 다시 만들지 않는다. 정상 경계는 문장/블록을 우선하지만, 긴 문장/표/코드는 원문 offset을 유지해 분할한다.
- O는 앞 청크 마지막 reference tokens에 해당하는 **실제 원문 범위**를 다음 청크 시작에 포함한다. 끝 문장이 O보다 길다고 overlap을 0으로 만들지 않는다. 필요하면 문장 중간의 토큰 경계를 쓴다. O=0은 중복이 없는 대조군이다.
- `actual_tokens`는 청크 source 범위에 포함된 reference token 수이며, `actual_overlap_tokens`는 같은 원문 단위에서 인접 청크의 source 범위 교집합에 포함된 reference token 수다. 경계를 만들 때 사용한 원문 token offset 표를 기준으로 집계하고, 제목/prefix/직렬화 구분자는 제외한다. 첫 청크·다른 절/원문으로 넘어간 청크는 0이다. 실제 `O/L` 비율과 모델별 실제 encoder 입력 token 수를 별도로 보고한다.
- guard/tail/절 경계 때문에 O를 줄이면 요청값과 실측값, 사유를 저장한다. 직전 청크의 유효 길이보다 O가 크면 전진을 보장하는 값으로 줄인다. `next_start > current_start`, 원문 tail 도달, 비공백 coverage=100%를 검사한다.
- frontmatter는 본문에서 제외하되 절대 위치를 보존한다. 첫 제목 이전 본문, 제목 없는 페이지, 마지막 짧은 조각도 처리한다. 공백만인 생략 구간은 위치와 이유를 기록한다. 묵시적 truncation은 0건이어야 한다.

모델/tokenizer 집합을 확정하고 grid를 manifest에 저장한 뒤 전 후보를 생성한다. 모델 제외로 guard 조건이 달라지면 전체 후보와 행렬을 다시 고정한다. 점수를 보고 개별 질문에 맞게 경계를 바꾸지 않는다. 문장 경계 때문에 서로 다른 O 후보가 실제 같은 청크를 내는지 검사하고 실제 파라미터 효과를 보고한다.

### 4.2 RawPedia: 방식 2개 × 크기 3개 × 오버랩 3개

| 방식 | 생성 규칙 | 오버랩 적용 위치 | 후보 수 |
|---|---|---|---:|
| `R-A-heading` | H2/H3를 연속 leaf 구간으로 나누고 같은 구간의 문단/목록/표/코드를 L까지 묶음. 짧은 절은 유지 | 같은 H2/H3 구간을 복수 청크로 나눌 때 O 적용. 절 경계는 넘지 않음; 한 청크인 절은 actual overlap=0 | 9 |
| `R-B-window` | frontmatter 이후 본문에 L 크기 문장 우선 sliding window. H2/H3 경계 통과 허용 | 페이지 내 연속 청크에 O 적용; 목표 stride=L-O | 9 |

**합계 18개 후보 청크셋**을 만든다. variant ID/파일명은 `R-A-heading-t128-o0`, `R-B-window-t224-o64` 등이다. `rule_family`에는 기본 방식, `rule_id`에는 variant ID를 넣고 L/O를 manifest와 fingerprint에 포함한다. 파라미터만 바꿔 같은 파일명을 덮어쓰지 않는다.

H4 이하 제목은 해당 H3 본문에 유지하고 실제 전체 heading path를 저장한다. 코드 fence 안 `##`는 제목이 아니다. ATX/setext/HTML/반복 제목을 검사한다. `Channel_Mixer.md`, `RGB_and_Lab.md`, `Impulse_Noise_Reduction.md`는 `section_kind=page_body`, 빈 heading path다. `Sharpening.md`의 반복 `Radius`는 계층/절대 위치로 구별한다.

R-B의 문장 경계는 `.?!` 뒤 공백/줄바꿈을 쓰되 URL/backtick/fenced code 내부에서 끊지 않는다. 정상 청크 끝은 문장 경계를 우선하고, 다음 시작은 §4.1의 token overlap을 적용한다. 처음부터 크기와 O를 함께 교차 비교하므로 192/32에서 방식만 비교한 결과를 전체 최적화로 보고하지 않는다.

### 4.3 GitHub: 전체 스레드와 유의미 단위

전체 스레드 요청과 T10-2a의 정제 범위를 함께 검증하기 위해 A를 두 변형으로 기록한다. **A-full은 전체 댓글을 실제로 포함하는 비교 기준선**, A-curated와 B-unit은 기존 정제 범위 안에서 선택 가능한 두 규칙이다. A-full의 성능이 좋아도 미선택 댓글을 T9의 정제 코퍼스로 자동 승격하지 않는다.

| 규칙 ID | 내용/검색 단위 | T9 선정 자격 |
|---|---|---|
| `G-A-full-thread` | 포함된 12개 후보의 원본 부모 `/body` + 해당 스레드의 **모든 저장된 댓글 39개**를 한 논리 청크로 직렬화; 미선택·감사 댓글도 provenance와 `curated=false`로 구분 | 정제 밖 문맥의 효과·노이즈를 측정하는 진단 기준선 |
| `G-A-curated-thread` | 각 후보의 `curated_content` 35개 조각을 부모/시간순으로 모은 스레드 청크. 제거한 푸터·미선택 댓글은 다시 넣지 않음 | 선택 가능: 스레드 수준 문맥 보존 |
| `G-B-curated-unit` | 각 `curated_content` 조각을 L/O로 분할한 독립 청크. 같은 조각 안에서 O 적용; 서로 다른 댓글은 합치지 않음. 원문 role/후보 연결 보존 | 선택 가능: 작은 기술 문맥의 정밀 검색 |

GitHub variant는 **G-B의 (L,O) 9쌍**과 **G-A-curated의 내부 encoder window L=128/192/224 3개**로 정식 12개다. G-A-full도 같은 window L 3개를 진단 후보로 만든다. 스레드는 부모/댓글을 합친 한 논리 청크라 물리 `target_tokens`/`overlap_tokens`는 null, `encoder_window_tokens=L`, `encoder_overlap_tokens=0`이다. G-B는 `target_tokens=L`, `overlap_tokens=O`, encoder window 파라미터는 null이다. 스레드 내부 window의 0 overlap은 전체 본문을 중복 없이 가중 평균하는 정책이며, 물리 청크 O=0 실험과 구분한다.

variant ID는 `G-B-curated-unit-t128-o0`, `G-A-curated-thread-w224-wo0`, `G-A-full-thread-w192-wo0`처럼 파라미터를 포함한다. 스레드 3variant의 본문/논리 청크 수가 같아도 내부 encoder 입력은 다르므로 다른 embedding cache key와 실험으로 처리한다.

전체 스레드 수집은 `load_sources()`가 만든 thread를 `source_record_key`로 찾아 사용한다. 후보 파일의 `source_locations`는 전체 댓글 목록이 아니다. 관계의 상대 항목 #503/#510 등은 metadata만 보존하고 정제 후보 밖 원문을 추가 적재하지 않는다.

B-unit의 기본은 **이미 정제된 유의미 body/댓글 단위**다. `guidance`, `explanation`, `reported_fix`, `confirmation`, `caveat`, `reproduction`, `context`를 짧다는 이유로 다시 제거하지 않는다. I #500 댓글은 67문자로 실제 제약 근거이고, D #489 댓글은 72문자로 완결된 안내다. `thanks` 단어 포함 여부로 의미 있는 확인을 지우지 않는다.

Q/A를 묶는 확장 후보는 명시적인 질문–답변 관계가 있을 때만 만든다. 현재 Discussion reply 계층이 없으므로 시간상 인접한 두 댓글을 Q/A로 추정하지 않는다. 최초 행렬에서는 B-unit을 쓰고, Q/A 확장은 별도 rule ID/근거가 있을 때 추가한다.

### 4.4 긴 스레드를 한 검색 단위로 유지하는 임베딩 정책

스레드를 한 번 encode하여 256/512 tokens 뒤를 버리면 비교 자체가 잘못된다. G-A 두 변형은 **한 논리 청크/한 벡터**를 유지하되 전체 내용을 공통 guard를 만족하는 내부 window로 나눈다.

1. 직렬화된 source segments를 순회하면서 variant에 저장한 `encoder_window_tokens=L`(128/192/224), **encoder overlap 0**인 내부 windows를 만든다. 원문 라벨·title을 포함한 입력 길이를 전 모델에서 검사하고 source coverage 100%를 확인한다.
2. 모델별 prefix를 한 번 붙여 각 window를 encode/L2 normalize한다.
3. `v_thread = normalize(sum(w_i * v_i) / sum(w_i))`; `w_i`는 해당 window에 포함된 원문 본문의 reference token 수다. 생성한 라벨/title token은 가중치에서 제외한다. 빈 본문 window는 생성하지 않는다.
4. `embedding_policy=thread_window_mean_v1`, window L/O, 각 원문 범위·입력 해시·가중치·개수·총 encoder 호출량을 캐시에 저장한다. segment 전체를 window라고 간주하지 않고 L/guard에 맞춰 실제로 분할한다. mean vector의 0/NaN 여부를 검사한다.

단일 길이 안에 들어오는 스레드는 같은 식의 window 1개다. R-A/R-B/G-B는 직접 encode하는 물리 청크를 사용한다. 이 실험은 순수 경계뿐 아니라 **스레드 벡터 집계 정책을 포함한 스택**의 비교라고 리포트에 명시한다. 반환 스레드 content는 전체를 반환하며, 숨은 window를 별도 top-k 결과처럼 세지 않는다. 긴 청크가 Hit를 얻는 대가로 늘리는 context tokens도 §7에서 보고한다.

### 4.5 기존 구현에서 이번 탐색에 필요한 수정

아래는 현행 구현을 조사해 확인한 후속 작업이다. 이 개정에서는 플랜만 갱신한다.

- `scripts/chunk_corpus.py`: 단일 L/O 인자를 **grid 생성**으로 확장하고 manifest에 18 RawPedia/12 정식 GitHub/3 진단 GitHub variant를 등록한다. `check --verify-regeneration`의 고정 `target_tokens=192`, `overlap_tokens=32`와 고정 경로를 제거하고 해당 manifest 값으로 모든 variant를 재생성한다.
- `src/artagent/chunking.py`: 방식과 variant ID를 구분하고 공통 guard/실제 token overlap/실측 파라미터를 구현한다. O=0/32/64가 문장 단위 처리 때문에 모두 0 overlap으로 같아지는 경우를 검출한다. 원문 위치/해시는 기존 계약을 유지한다.
- `scripts/benchmark_embeddings.py`: 고정된 R/G 방식 목록 대신 manifest의 variant를 탐색한다. 긴 스레드 encode는 원문 segment를 실제 L 크기 내부 window로 나누고 길이 guard/원문 coverage를 확인한다. window마다 원문 reference token 가중치를 사용한다. 단순히 segment 전체를 encode하거나 비공백 문자 수를 token 수로 대체하지 않는다.
- cache/collection/리포트에는 양쪽 출처의 크기·O와 window 정책을 포함한다. 선정/재현 검사는 전체 파라미터를 읽는다. 보고서 생성기의 192/32 고정 문구도 실제 선정값으로 바꾼다.

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

이 워크트리에는 `venv/`가 없다. 사용 가능한 기존 interpreter는 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3` **3.14.3**, macOS arm64다. 이번 개정에서 package metadata와 [설치 기록](pipeline_setup.md)을 확인했다. `pytest=9.1.1`, `torch=2.14.0`, `sentence-transformers=6.1.0`, `transformers=5.17.0`, `tokenizers=0.23.2`, `numpy=2.5.3`, `chromadb=1.5.9`가 설치되어 있다. 기존 `run-001/environment.json`에도 4모델 revision과 CPU smoke 상태가 있으며 새 실험 시작 때 다시 확인한다.

- 기존 의존성을 재사용한다. Step 3의 tokenizer, Step 4의 모델/Chroma 소비 직전에 import/version을 확인하며 누락 또는 호환성 실패가 있을 때만 해당 의존성을 설치한다. numpy는 실제 벡터 연산/대조 검색 소비 때 확인한다.
- 설치 전 기존 venv의 `pip --version`, 패키지 목록, macOS/Python wheel 호환성을 확인한다. `pip install --dry-run --only-binary=:all: sentence-transformers` 및 이후 `chromadb`로 의존성 해결을 먼저 점검한다. 실제 설치 버전은 당시 root venv에서 검증된 버전으로 정하고 `pip check`를 통과시킨다.
- 설치 명령·실제 버전·최초 소비처를 `docs/pipeline_setup.md`에 기록한다. 이 플랜에서 미검증 버전 번호를 고정하거나 다른 Python venv로 바꾸지 않는다. 공식 설치 안내는 [Sentence Transformers](https://www.sbert.net/docs/installation.html), PyTorch 배포 확인은 [공식 PyPI 파일 목록](https://pypi.org/project/torch/)을 참조한다. Python 하한 충족만으로 모든 전이 의존성의 3.14 호환성을 단정하지 않는다.
- 각 모델을 CPU에서 불변 revision으로 로드하여 한국어 query 2개/영문 문서 2개를 encode한다. 차원·finite·norm·입력 한도·pooling을 확인한다. `trust_remote_code=False`로 로드 가능한 후보를 사용한다.
- 모델/토크나이저 파일은 명시한 작업 디렉터리에 캐시하고 revision/사용 파일 지문을 기록한다. 다운로드·모델 load 시간은 별도 측정한다. 이후 재실행은 해당 revision의 로컬 캐시로 한다.
- import/wheel/load 실패는 `unavailable`과 원인·명령·환경으로 기록한다. 한국어 대응 후보 또는 모델 2개 최소 조건을 충족하지 못하면 환경 준비 실패 상태이며, 최적 스택을 선정했다고 보고하지 않는다.

### 5.3 재사용할 인터페이스

기존 `src/artagent/chunking.py`와 CLI, `scripts/benchmark_embeddings.py`를 확장한다. T9가 검색 부분을 공통 모듈로 옮길 수 있도록 다음 계약을 유지하며 grid 열거를 추가한다. 패키지 전체 레이아웃을 새로 설계하지 않는다.

```python
load_documents(rawpedia_dir, candidates_path, source_manifest) -> list[SourceDocument]
chunk_document(document, rule, tokenizer_bundle) -> list[Chunk]
enumerate_chunking_variants(search_grid) -> list[ChunkingVariant]
validate_chunk(chunk, source_documents) -> None
map_evidence_to_chunks(queries, chunks) -> GoldMapping
build_experiment_matrix(chunk_manifest, model_manifest, evaluation_contract) -> ExperimentMatrix

load_encoder(model_id, revision, device="cpu") -> Encoder
encode_documents(chunks, encoder, batch_size=16) -> numpy.ndarray  # [N, D]
encode_queries(texts, encoder, batch_size=1) -> numpy.ndarray       # [Q, D]
build_collection(client, experiment_id, chunks, vectors, settings) -> Collection
search(collection, query_vector, k=5) -> list[SearchResult]
evaluate_query(query, results, gold_mapping, ks=(1, 3, 5)) -> QueryMetrics
```

`ChunkingVariant`는 family/variant ID, 적용 가능한 target/overlap/window 파라미터와 fingerprint를 갖는다. `Encoder`는 query/document prefix, revision, dimension, max length, pooling, normalize, thread pooling을 보유한다. `SearchResult`는 `rank`, `chunk_id`, `distance`, `cosine_similarity`, `source_type`, `doc_id`, `trace_ref`, 전체 source segments를 반환한다. T9에서 같은 encoder와 검색 경로를 재사용한다.

벡터는 **float32, L2 norm 1**로 통일한다. SentenceTransformer의 배포된 pooling을 사용하고 `encode(..., normalize_embeddings=True, convert_to_numpy=True)` 뒤 dtype/shape/norm을 검사한다. zero/NaN/Inf 벡터는 실패하고 `abs(norm-1) <= 1e-5`를 확인한다. query prefix는 한 번만 붙인다. 코사인 유사도는 `q @ documents.T`, cosine distance는 `1 - similarity`이며 Chroma distance는 작을수록 가깝다. E5 예제의 `*100`은 적용하지 않는다. 정규화·encode 인자는 [SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)를 참조한다.

## 6. 실험 행렬과 Chroma 실행기

### 6.1 두 출처 파라미터를 독립적으로 교차 비교

RawPedia와 GitHub의 L/O를 같은 값으로 강제하지 않는다. 예를 들어 `R-B-window-t224-o64 + G-B-curated-unit-t128-o0`도 비교해야 한다. 크기→오버랩→모델 순으로 하나씩 승자를 고정하면 상호작용을 놓치므로 등록한 **전체 결합 행렬**에서 하나의 스택을 선정한다.

| 범주 | 계산 | 4모델 | 최소 2모델 |
|---|---|---:|---:|
| RawPedia 후보 | 2방식 × 3크기 × 3오버랩 | 18청크셋 | 18청크셋 |
| 정식 GitHub 후보 | G-B의 3크기×3오버랩 + G-A-curated의 3window 크기 | 12청크셋 | 12청크셋 |
| 진단 GitHub 후보 | G-A-full의 3window 크기 | 3청크셋 | 3청크셋 |
| 정식 혼합 검색 | 18 × 12 × 모델 수 | **864조합** | **432조합** |
| 진단 혼합 검색 | 18 × 3 × 모델 수 | **216조합** | **108조합** |
| 전체 | 18 × 15 × 모델 수 | **1,080조합** | **540조합** |

매 조합에 해당 RawPedia variant의 전체 116문서 청크와 GitHub variant의 전체 12후보 청크를 함께 넣는다. 출처별 독립 검색의 최고 점수를 합쳐 혼합 검색 결과로 쓰지 않는다. 정식/진단 구분과 각 variant의 파라미터를 명시한 `experiment_matrix.json`을 **실행 전에 저장**한다. 모든 등록 행은 완료/실패 상태와 로그를 가져야 한다.

모델 수 M은 전체 4후보의 preflight 결과로 고정한다. 전부 실행 가능하면 M=4를 사용한다. 환경/import/load 실패로 실행 불가인 모델만 사유를 남겨 M에서 제외할 수 있으며, 새 조건으로 청크와 행렬을 재고정한다. `grid_coverage=성공 행 수/(18×15×M)`, `grid_complete=(grid_coverage==1)`로 정의한다. 실패 행의 상태 기록만으로 성공 처리하지 않고, 실행 중 실패한 모델/파라미터를 분모에서 삭제하지 않는다. 후보 전체 대비 제외 모델 수와 이유도 별도 출력한다.

실험 ID는 R/G variant ID·청크 SHA·모델 revision·encoder policy·k·device/dtype·평가/index 설정의 fingerprint다. 같은 `(L,O)`만 짝짓는 축소 행렬이나 기존 최상위 모델만 실행하는 행렬로 바꾸지 않는다. 192/32 기준선도 새 실행 조건에서 재측정하며 이전 점수를 그대로 새 결과에 복사하지 않는다.

1080조합에서 새로 encode할 출처 후보는 **33청크셋 × 4모델 = 최대132개 cache entry**다. 문서 벡터는 출처 후보별로 생성한 뒤 혼합 조합에서 재사용한다. 같은 입력의 vector는 공유 가능하나 각 조합의 실제 Chroma 검색/평가는 수행한다. 시간/디스크/청크 수를 먼저 실측해 일정을 기록하고, 실행 중단 시 상태를 보존해 남은 행을 계속 실행한다. 탐색 공간을 줄여 완료 기준을 충족한 것처럼 보고하지 않는다.

### 6.2 Chroma 고정 조건

- 로컬 `chromadb.PersistentClient(path=<work-dir>/chroma)`을 사용한다. `embedding_function=None`으로 collection을 생성하고, `add/upsert`에 계산한 vectors, `query`에 `query_embeddings`를 명시한다. 다른 기본 모델이 자동 실행되지 않는지 smoke test한다.
- 초기 비교값은 전 조합에서 `configuration={"hnsw": {"space": "cosine", "ef_construction": 200, "ef_search": 200, "max_neighbors": 16, "num_threads": 1}}`로 통일한다. 설치한 Chroma 버전에서 지원 여부를 preflight로 확인하고 적용된 실제 값도 저장한다. 현행 API는 [공식 collection 설정](https://docs.trychroma.com/docs/collections/configure)을 참조한다.
- `chunk_id`로 정렬한 같은 순서/배치 크기로 적재한다. collection 이름은 `t08-2-<fingerprint>`의 ASCII 문자열이다. 전체/source별 count, ID/trace roundtrip이 기대값과 일치해야 측정한다.
- 모든 100문항을 **source/doc/category의 where filter 없이** `n_results=5`로 조회한다. 예상 출처를 검색 전에 사용하지 않는다. 같은 상위 5개에서 Hit@1/3/5를 계산한다. 전체 스레드 기준선의 GitHub 청크가 12개여도 RawPedia와 함께 검색한다.
- 반환 순서는 distance 오름차순, 정확한 동점은 chunk_id 오름차순으로 정한다. Chroma가 반환하지 않은 후보를 추가하지 않는다. 5위 경계의 동점은 로그에 남기고 재현 비교에서 같은 거리의 후보 집합도 확인한다.
- 출처별 지표는 **질문 쪽 source_type으로 집계**한다. 반환 출처로 질문을 재분류하지 않는다. 반환 청크의 출처 구성과 다른 출처로의 혼동도 기록한다.

조회/반환 필드는 [Query and Get 공식 명세](https://docs.trychroma.com/docs/querying-collections/query-and-get)를 참조한다. 지표 산출용 결과는 documents와 metadata도 받아 실제 반환 본문을 확인한다.

### 6.3 캐시와 ANN 검색 누락 검사

embedding cache key는 청크셋 SHA, 전체 L/O·encoder window 파라미터, 모델 revision, 실제 입력 문자열 SHA, prefix/pooling/thread policy, dtype다. query cache에는 질문 JSON SHA와 전체 query ID/원문/prefix를 포함한다. 같은 RawPedia 청크를 GitHub 규칙마다 재인코딩하지 않는다. 실험 결과 캐시는 experiment ID로 구분한다.

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

1. §6.1의 정식 파라미터 행렬 전체가 완료된 뒤 입력/청크/모델/Chroma/ANN 검사를 통과한 행을 선정 대상으로 삼는다. 입력 한도 때문에 후보를 축소/제외하면 원인과 실측 길이를 남기고 `grid_complete`와 `grid_coverage`를 함께 보고한다. 사전 등록한 행을 점수로 제외하지 않는다. G-A-full-thread는 진단 행으로 비교표에 남긴다.
2. 95개 양성의 **Macro MRR@5** 내림차순으로 정렬한다. 동률이면 Macro Hit@5, complex의 Macro FullEvidence_all@5, query p95초, 총 vector bytes, experiment ID 순으로 비교한다. 각 출처 결과도 병기한다.
3. 경량성에 따른 재선정은 미리 정한 범위 안에서만 허용한다. 선두와 Macro MRR@5 및 Macro Hit@5 차이가 모두 **0.01 이내**, 출처별 MRR@5 차이가 각각 **0.02 이내**인 조합을 근접 후보로 표시한다. 이 중 complex FullEvidence_all@5가 선두 이상인 후보에서 p95가 낮은 조합을 고르고, 동률이면 총 vector bytes, experiment ID 순으로 고른다. 선두도 이 후보 집합에 포함한다.
4. `selected`에는 R 방식/L/O와 G 방식/L/O 또는 window L/O를 **서로 독립적인 필드**로 기록하고 모델/policy/index 값, 선두와 차이, 선정 단계, 출처별 득실, 실패 query ID, 문맥 부담을 기록한다. 크기별·오버랩별 MRR/Hit/FullEvidence/p95/저장 크기 표도 생성하여 192/32 기준선과 증감을 보여준다. 근접 대안이 없으면 선두를 선택한다.

크기·오버랩의 효과는 다른 축을 고정한 **쌍별 비교**로 설명한다. 예를 들어 같은 모델/R 방식/L/G variant에서 R의 O=0→32→64만 바꾸고, 같은 모델/R 방식/O/G variant에서 R의 L=128→192→224만 바꾼다. G-B도 R variant와 모델을 고정해 같은 방법으로 비교한다. 각 고정 조건의 3×3 표에 주 지표와 지연/청크 수/vector bytes를 함께 넣고, 최종 선정 조합의 이웃 셀을 본문에 제시한다. 방식·모델까지 다른 행의 점수 차이를 오버랩의 단독 효과로 설명하지 않는다.

1/2 percentage point는 선정 절차의 근접 폭이며 WBS의 품질 합격 임계치나 통계적 유의차가 아니다. 이번에 별도 최소 Hit 합격선을 만들지 않는다. 전 조합의 절대 성능이 낮아도 수치/실패 분석과 고정셋 위의 비교 선정임을 명시한다. 최소 실행 조건을 충족하지 못하면 `selection_status=incomplete`, `selected=null`이다.

같은 100문항을 모델 선정과 후속 T23에 재사용하므로 독립 hold-out 성능이나 일반화 보장으로 표현하지 않는다. `source_group_id` 단위의 질문 상관성을 보존하고 평균 차이를 유의차라고 단정하지 않는다. 그룹 단위 paired resampling/RAGAS는 T23에서 다룬다.

### 8.2 재현 게이트

- 같은 입력/규칙/tokenizer revision으로 다른 위치에 다시 생성하여 **전 후보 JSONL의 바이트/ID/위치/content hash가 일치**해야 한다. 시각이 포함된 실행 로그는 비교 대상에서 분리한다.
- 전 조합의 저장된 query 결과에서 지표를 재계산하여 리포트 JSON의 분자/분모/값과 일치시킨다.
- 정식 선두, 최종 선정 조합(선두와 다르면), 차순위 조합, 192/32 기준선을 **저장한 전체 파라미터로** 새로운 Chroma 작업 위치에 재적재해 100문항을 재검색한다. 주 지표 절대 차이 `1e-9` 이내, vector는 `allclose(atol=1e-6, rtol=1e-5)`, distance 차이는 `1e-5` 이내를 초기 검증값으로 삼는다.
- ANN/동점의 순위 변동이 지표를 바꾸면 차이를 기록하고 원인을 해결한다. 허용 오차를 조용히 넓히지 않는다. latency는 동일값을 요구하지 않고 회차별 분포/환경 차이를 보고한다.

### 8.3 T9에 전달할 입력

리포트 JSON의 `selected`를 기계 판독용 선정 계약의 정본으로 사용한다.

| 인계 항목 | 필수 내용 |
|---|---|
| 청크/파라미터 | 선정 R/G variant ID와 방식, 각 source의 target/overlap 또는 encoder window/overlap, 명목/실측값; JSONL 경로/건수/SHA-256, source_segments schema |
| 원문 고정점 | dataset ID, 질문 JSON SHA, source manifest SHA, RawPedia 집계 SHA, GitHub candidate/rules/thread SHA |
| 모델 | 전체 model ID, Hub commit revision, 로컬 cache 재확보법, tokenizer/pooling/prefix/입력 상한, D/dtype/norm, thread pooling |
| Chroma | 검증한 package version, cosine/HNSW 실제 값, 삽입 순서/배치, metadata flatten 규칙, 검색 결과 계약 |
| 재현 | 청크 재생성/적재/100문항 검색 명령, 환경 versions/seed, 전체 비교표/선정 순서, 재실행 차이 |
| 후속 갱신 | candidate_id→청크 ID 목록, RawPedia doc_id→청크 ID 목록. 원문/규칙 변경 시 ID 변경과 이전 ID 삭제 필요성 |

새 후보 청크는 `data/chunks/t08-2-grid/`에 보존하고 선정 manifest에서 원래 파일을 참조한다. T9의 별도 워크트리에는 실체를 전달하거나 동일 main 입력에서 기록한 명령으로 재생성하고 SHA를 대조한다. 모델 cache/Chroma DB는 git에 커밋하지 않는다. T9는 실제 저장소 구성과 재적재·갱신·검색 제외 구현을 담당한다.

## 9. 산출물 구조와 리포트 명세

기존 module/CLI/test/리포트를 확장한다. grid 산출물은 아래 **새 출력 위치**를 사용한다. 실행 전에 기존 `docs/chunking_embedding_benchmark.md/.json`을 `docs/chunking_embedding_baseline_192_32.md/.json`으로 바이트 그대로 보존하고 SHA를 기록한다. 새 전 조합 결과/재현 검사를 통과한 뒤에만 최종 benchmark 리포트를 원자적으로 갱신한다.

```text
src/artagent/chunking.py                    # 원문/segment/청크 생성·검증
scripts/chunk_corpus.py                     # prepare/build/check CLI
scripts/benchmark_embeddings.py             # preflight/matrix/run/check/report CLI
tests/test_chunking.py                     # 범위·결정성·실제 원문 회귀
tests/test_benchmark_embeddings.py          # 지표 및 Chroma roundtrip
tests/fixtures/chunking/                    # 작은 Markdown/JSON fixture
docs/pipeline_setup.md                      # 실제 설치 의존성 기록
docs/chunking_embedding_benchmark.json       # 전체 비교·선정·재현 정본
docs/chunking_embedding_benchmark.md         # JSON에서 생성한 보고서
docs/chunking_embedding_baseline_192_32.md/.json  # 기존 결과 원본 보존
data/chunks/t08-2-grid/
  manifest.json                             # 입력/규칙/grid/tokenizer revision
  rawpedia/R-A-heading-t128-o0.jsonl         # R-A 9 + R-B 9 = 18개
  rawpedia/R-B-window-t224-o64.jsonl
  github/G-B-curated-unit-t128-o0.jsonl      # G-B 9개
  github/G-A-curated-thread-w192-wo0.jsonl   # G-A-curated 3개
  github/G-A-full-thread-w224-wo0.jsonl      # G-A-full 3개
  gold_mapping.json                         # query/evidence→전체 variant 매핑
data/embedding-benchmark/t08-2/grid-001/
  experiment_matrix.json                    # 정식864/진단216 등록 행
  results.json                              # 검증·재현 전 작업 리포트
  environment.json                          # versions/hardware/model settings
  models/                                   # 고정 revision 로컬 cache
  vectors/<cache-key>.npy                    # ID 순서 sidecar와 벡터
  runs/<experiment-id>.jsonl                 # 100문항 top5/coverage/latency
  chroma/                                   # 공통 client의 실험 collection들
```

원문 snapshots, 정제 후보, 청크, vector state를 별도 영역에 보존한다. 큰 생성물인 `data/chunks/`, `data/embedding-benchmark/`는 구현 시 `.gitignore`에 추가하고 로컬에 보존해 T9로 인계한다. **git 관리하는 리포트에는 규칙, 입력/산출 SHA, 건수, 생성 명령을 남긴다.** 부동소수점 vector나 Chroma 내부 파일의 git 저장을 재현성의 대체물로 삼지 않는다.

JSON 리포트 필수 키:

- `schema_version`, `run_id`, `dataset_id`, `input_fingerprints`, `environment`, `model_candidates`(unavailable 포함), `chunking_candidates`, `evaluation_contract`, `search_grid`, `grid_complete`, `grid_coverage`, `baseline`, `chroma_settings`, `experiments`, `selection_order`, `selection_status`, `selected`, `reproduction`, `limitations`.
- `evaluation_contract`: ks=`[1,3,5]`, relevance coverage threshold=`0.5`, strict threshold=`1.0`, 합집합 정의, denominators rawpedia=`80`/github=`15`/positive=`95`/negative=`5`, evidence_count=`147`.
- `search_grid`: L=`[128,192,224]`, O=`[0,32,64]`, R=18/G정식=12/G진단=3, source별 독립 결합, 모델 수와 예상/완료/실패 행 수. `baseline`은 원래 24조합 리포트 SHA와 192/32 재측정 행을 연결한다.
- `experiments[]`: ID, 정식/진단 구분, R/G variant/family/L/O/encoder window, model/revision/policy, count/bytes, rawpedia/github/macro/micro의 Hit@1/3/5 및 MRR@1/3/5, complex Any/All/Full, negative 별도 표, latency 세부/분포, ANN 검사, 실패 원인, 100문항 로그 경로/SHA.
- query 로그: ID/source/category/intent/difficulty/group, 실제 top5 전체 ID/순위/source/distance/원문 위치, 대응 evidence/coverage, 지표/null, 3회 latency. 실패 문항도 오류 행으로 보존한다. 한 회차라도 100문항 검색에 실패한 조합은 완료 행으로 처리하지 않는다.
- Markdown 순서: 입력 요약→전 조합 비교표→출처별/complex/negative 세부→속도/크기→선정 순서/득실→재현법→제약. JSON에서 수치를 생성하며 수동으로 다른 수치로 고치지 않는다.

## 10. 필수 단위·회귀 테스트

| 검증 축 | 필수 사례와 판정 |
|---|---|
| Markdown 구조 | frontmatter 제외 뒤 절대 위치, H2/H3/H4/setext, code 안 가짜 heading, 반복 Radius, 첫 도입/제목 없음, 긴 표/코드, 마지막 tail |
| 문자/바이트 | CRLF, 한국어/이모지/결합문자, UTF-8 중간 경계 거부, 원문 범위와 content 범위 구분 |
| 크기/오버랩 | 9쌍/18 R/12 정식 G/3 진단 G, O=0 및 32/64 실제 token 중복, 문장이 O보다 긴 경우, L=128 O=64 전진, 독립 source 조합, 명목/실측값 |
| sliding window | stride 전진, guard로 줄인 overlap 사유, tail/긴 문장, 의미 문자 coverage100%, 비공백 누락0 |
| GitHub 원문 | body/file hash 분리, candidate/ref 구분, D #442 다중 segment, D #494 삭제 footer 보존, I #524 실패 버전 caveat 유지 |
| 짧은 정답 보존 | I #500의 67문자와 D #489의 72문자 유지, negative를 support로 바꾸지 않음 |
| 전체 스레드 | 선정 12부모+39댓글, 후보 밖 스레드 비적재, G-A-curated의 35조각/23댓글 범위 유지, reply 관계 비추론 |
| 변조 거부 | content 1문자, source hash/range/URL/ref/body hash 변조, manifest drift, path traversal 실패 |
| ID/결정성 | 두 번 생성 바이트 일치, 탐색 순서/작업 위치와 무관한 ID, L/O/window 변경 시 ID/cache 분리, variant 출력 비덮어쓰기, duplicate ID0 |
| 모델 입력 | prefix 한 번, 실제 token 상한, truncation0, thread windows 전체 범위, weighted mean/norm/float32, pooling 설정 보존 |
| 골드 매핑 | 동일 doc의 다른 절/다른 body의 동일 문장 거부, 50% 직전/경계, 범위 중복 비가산, 전체 147 evidence |
| 지표 | rank1/3/5/범위 밖, MRR 예, Any/All/Full, macro/micro, negative N/A/분모95, 부분 실패 조합 거부 |
| Chroma | 실제 2출처/vector add→query→trace roundtrip, count/차원, distance 방향, source filter 비사용, 동점 순서, 재개방 |
| 재현/표시 | manifest의 128/0·224/64 및 스레드 w128/w224 재생성, 고정192/32 제거, 전체 grid 로그 재집계, JSON→Markdown 파라미터 일치, 기준선 보존, 재적재 결과/지표 일치 |

주 로직은 작은 fixture와 수작업 vectors로 검증한다. 모델 semantic 성능을 고정 기대값의 단위 테스트로 만들지 않는다. 실제 원문/147스팬 회귀와 실제 Chroma roundtrip은 의존성 준비 뒤 반드시 실행한다. 테스트 중 숨은 네트워크 다운로드 대신 사전 cache를 쓰며 skip/xfail로 필수 검증을 줄이지 않는다.

## 11. Antigravity Step 1~6 체크리스트

이 체크리스트는 완료된 **128~224토큰/1080조합 단계의 구현·재현 순서**다. 완료 상태의 정본은 `tasks/todo.md`이고, 아래 체크박스는 원래 실행 계약을 보존한 것이다. 이번 추가 실험은 **§13.6의 확장 Step 1~6**을 사용한다. WBS의 최초 8h 배분은 보존하고 추가 실행 시간은 청크 수·encode/index/query 실측으로 추정한다. 문서 벡터 캐시와 실행 상태를 보존하여 남은 행을 이어서 수행한다.

### Step 1 — 기준선 보존과 입력·환경 재확인 (선행: 기존 T8-2 구현)

대상: 기존 리포트/청크/환경, `scripts/chunk_corpus.py`, 새 grid manifest.

- [ ] 기존 24조합 리포트 MD/JSON을 §9의 기준선 파일로 바이트 그대로 보존하고 SHA를 기록한다. 기존 청크/벡터/환경 디렉터리를 덮어쓰지 않는다.
- [ ] 116파일/12후보/35조각/39전체댓글/100문항/147스팬을 재집계하고 고정 manifest·원문을 전수 대조한다. 기존 query/filter check를 통과한다.
- [ ] root Python/package/hardware를 확인하고 기존 모델 revision/cache를 재사용한다. 필요한 의존성이 이미 있으면 다시 설치하지 않는다.
- [ ] L=`[128,192,224]`, 물리 O=`[0,32,64]`, thread window L 동일/내부 O=0, 비교 방식·모델·선정 순서를 실험 전에 선언한다.

검증: 기준선 보존 SHA 일치, 입력 오류0, query ID 유일, 95/5 분모, 원문·골드 변경0. 다음 단계: Step 2.

### Step 2 — 파라미터·variant·원문 좌표 계약 확장 (선행: Step 1)

대상: `src/artagent/chunking.py`, `scripts/chunk_corpus.py`, `tests/test_chunking.py`.

- [ ] `rule_family`와 variant ID, L/O/window, 명목/실측 token 수·overlap·조정 사유를 schema/manifest에 넣는다. 파일/ID/cache가 다른 파라미터에서 충돌하지 않게 한다.
- [ ] 짧은 fixture로 O=0/32/64, 마지막 문장이 O보다 긴 경우, L=128/O=64의 전진과 tail을 검증한다. 스레드의 물리 overlap과 내부 window 정책을 구분한다.
- [ ] 기존 범위/hash/변조/coverage 회귀를 통과하고 CRLF/이모지/비연속 source segment, candidate/ref 구분, negative N/A를 유지한다.

검증/checkpoint 1: 실제 overlap 보존, 전진/coverage100%, 좌표 복원, 파라미터별 결정성·비덮어쓰기. 이후 전체 청크 생성으로 진행한다.

### Step 3 — 전체 크기·오버랩 후보 생성 (선행: Step 2)

대상: 청킹 module/CLI/tests, 신규 `data/chunks/t08-2-grid/`, `docs/pipeline_setup.md`.

- [ ] 기존 tokenizer/model revision과 배포된 pooling/prefix/입력 한도를 고정한다. 필요한 의존성만 소비 시 설치하고 변경된 버전을 기록한다.
- [ ] R-A 9개/R-B 9개/G-B 9개/G-A-curated 내부 window 3개/G-A-full 내부 window 3개, **합계 33variant**를 생성한다. 출력 이름/fingerprint에 모든 파라미터를 반영한다.
- [ ] 9쌍의 요청값·실측값, 실제 encoder 길이, overlap/stride/tail, 전체 원문 범위/segment/URL/ID를 전수 검사한다. 요청값이 다르지만 실제 청크가 같은 경우를 보고한다.
- [ ] 모든 JSONL/gold mapping을 생성하고 147스팬의 출처별 전체 청크셋 coverage를 검사한다. `check --verify-regeneration`은 각 variant의 manifest 값으로 다른 위치에 재생성하여 바이트를 비교한다.

검증: R=18/G정식=12/G진단=3, 각 variant의 의미 문자 coverage100%, 복원 불가0, truncation0, 결정성. 청크 수·실제 overlap 분포는 실행으로 채운다.

### Step 4 — encoder 확장·행렬 고정·실행 부담 실측 (선행: Step 3)

대상: `scripts/benchmark_embeddings.py`, `tests/test_benchmark_embeddings.py`, 실험 행렬/환경.

- [ ] Chroma/import/CPU smoke를 확인하고 스레드를 manifest의 window L로 실제 분할하여 encode한다. 가중치는 reference token 수를 사용하고 전체 segment coverage를 검사한다.
- [ ] metric, 실제 Chroma roundtrip, query cache 미사용 latency, 파라미터별 cache/collection 분리 테스트를 통과한다. report/check의 고정192/32 및 고정경로를 제거한다.
- [ ] `matrix` 명령으로 source별 독립 Cartesian product를 저장한다. 4모델이면 **정식864 + 진단216 = 1080**, 실행 불가 사유가 있는 2모델이면 **432 + 108 = 540**을 확인한다.
- [ ] 고정 Q001/Q002/Q025/Q049/Q060/Q071/Q081/Q085/Q096/Q099 10문항으로 각 모델/출처와 크기·O 경계 사례를 smoke한다. 점수로 후보를 제거하지 않는다.
- [ ] 33 source variant의 벡터 캐시를 설계하고 최대132 encode entry를 재사용한다. 실측 청크 수/index 시간/쿼리 지연/디스크로 전체 실행의 추가 시간·공간을 추정해 기록한다.

검증/checkpoint 2: 모델 2개 이상(다국어 1개 이상), 모든 행의 파라미터·예상 수 명시, 혼합 검색, truncation0, negative null, distance/지표/분모 일치. tokenizer 집합이 바뀌면 후보와 행렬을 모두 재고정한다.

### Step 5 — 전체 등록 행과 100문항 정량 실행 (선행: Step 4)

대상: runner, 실험 logs/vectors/Chroma, 작업 리포트 `grid-001/results.json`.

- [ ] 행렬 전체를 순서대로 적재하고 각 조합에서 warmup10 뒤 **100문항×3회**를 실행한다. 4모델/1080조합이면 주 지연 관측324,000개이며, 품질 분모는 조합당 고유 양성95/negative5다.
- [ ] 문서 벡터만 재사용하고 주 지연의 query encode는 매회 실제 호출한다. 모든 행에 상태·오류·100문항 top5/coverage/latency 로그를 저장하고 중단 시 미완료 행에서 재개한다.
- [ ] 출처/macro/micro Hit/MRR, complex 전체 근거, negative 별도 평가, 지연/크기/메모리/문맥 부담, ANN 검사를 집계한다.
- [ ] L/O 3×3의 쌍별 비교와 기준선 재측정 값을 생성한다. 정식/진단/실패 행을 구분하며 실패 행을 조용히 제거하여 완료율을 높이지 않는다.

검증: `grid_complete=true`, 정식·진단 모든 등록 행의 결과/상태, 선정 대상 모델들의 전 조합 성공, 100문항 로그, 95/5 분모, 비교표/재집계 일치. 후보 모델 전체가 실행 가능하면 1080행을 완주한다.

### Step 6 — 파라미터 포함 선정·재현·T9 인계 (선행: Step 5)

대상: 최종 `docs/chunking_embedding_benchmark.md/.json`, 선정 manifest, Task 8-2 추가 체크 항목.

- [ ] §8.1로 공통 모델과 **R/G 각각의 방식·L/O 또는 내부 window L/O**를 선정한다. 기준선 대비 증감, 출처별 득실, 이웃 셀, 동률/근접 후보를 기록한다.
- [ ] 선두/선정 조합/차순위/192·32 기준선을 저장된 전체 파라미터로 새 Chroma에서 재실행한다. 청크 재생성/재집계/필수 tests를 통과한다.
- [ ] 검증을 마친 작업 JSON에서 최종 MD/JSON을 생성하고 기존 리포트를 원자적으로 갱신한다. 기준선 파일과 SHA는 유지한다.
- [ ] 각 source의 최종 파라미터·variant/실체/SHA·모델 revision/prefix/window policy/index/재생성 명령을 T9로 전달한다. 새 탐색 증거가 모두 갖춰진 뒤 추가 완료 체크를 갱신한다.
- [ ] 코드/docs/작은 fixture의 diff를 확인하고 국문 commit/PR에 실측값과 검증을 쓴다. 원문/모델 cache/DB/큰 vectors의 의도치 않은 추가를 검사한다.

최종 게이트: **선언한 크기·오버랩 전체 행렬 완주, 100문항 검색, 95양성/5negative 분리, 147근거 원문/청크 추적, 원문 coverage100%, truncation0, 파라미터별 재현 통과, 선정 JSON과 T9 실체 일치**. 대형 청크의 추가 체크 항목은 §13의 새 실행 증거가 생길 때까지 미완료다.

## 12. 후속 CLI 계약과 실행 명령

기존 CLI를 다음 계약으로 **확장한 뒤** 실행한다. `matrix` 및 grid 인자, 기준선 보존/최종 JSON 출력 인자는 후속 구현 대상이다. 명령의 help/동작/manifest를 함께 갱신하고 저장소 root에서 실행한다.

```bash
ART_PIPELINE_PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3

# 기존 입력 검증
"$ART_PIPELINE_PY" scripts/generate_eval_queries.py check
"$ART_PIPELINE_PY" scripts/filter_issues.py --check
"$ART_PIPELINE_PY" -m pytest tests/test_eval_queries.py tests/test_filter_issues.py -q

# Step 1: 기준선 바이트 보존·입력 고정; 이미 있는 보존본은 SHA 일치 확인
"$ART_PIPELINE_PY" scripts/chunk_corpus.py prepare \
  --rawpedia-dir data/rawpedia \
  --rawpedia-collection docs/rawpedia_collection.md \
  --github-candidates data/issues/search-candidates.json \
  --github-dir data/issues \
  --source-manifest docs/search_eval_source_manifest.json \
  --queries docs/search_eval_queries.json \
  --baseline-md docs/chunking_embedding_benchmark.md \
  --baseline-json docs/chunking_embedding_benchmark.json \
  --output-dir data/chunks/t08-2-grid

# Step 3: 기존 모델 revision 재사용, 새 작업 위치에 tokenizer/환경 고정
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
  --stage tokenizers \
  --models BAAI/bge-small-en-v1.5 BAAI/bge-base-en-v1.5 \
    sentence-transformers/all-MiniLM-L6-v2 intfloat/multilingual-e5-small \
  --model-manifest data/embedding-benchmark/t08-2/run-001/environment.json \
  --device cpu --work-dir data/embedding-benchmark/t08-2/grid-001

"$ART_PIPELINE_PY" scripts/chunk_corpus.py build \
  --manifest data/chunks/t08-2-grid/manifest.json \
  --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
  --rawpedia-rules R-A-heading R-B-window \
  --github-rules G-A-full-thread G-A-curated-thread G-B-curated-unit \
  --target-tokens-grid 128 192 224 --overlap-tokens-grid 0 32 64 \
  --thread-window-tokens-grid 128 192 224

"$ART_PIPELINE_PY" scripts/chunk_corpus.py check \
  --manifest data/chunks/t08-2-grid/manifest.json \
  --queries docs/search_eval_queries.json --verify-regeneration

# Step 4: 같은 revision으로 모델/Chroma smoke, 실제 실행 전 행렬 저장
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
  --stage runtime \
  --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
  --device cpu --work-dir data/embedding-benchmark/t08-2/grid-001

"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py matrix \
  --chunk-manifest data/chunks/t08-2-grid/manifest.json \
  --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
  --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
  --output-json data/embedding-benchmark/t08-2/grid-001/experiment_matrix.json

# Step 5: 고정한 전체 행렬 실행; 작업 결과로 저장하고 완료 행만 재사용
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py run \
  --matrix data/embedding-benchmark/t08-2/grid-001/experiment_matrix.json \
  --chunk-manifest data/chunks/t08-2-grid/manifest.json \
  --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
  --queries docs/search_eval_queries.json \
  --ks 1 3 5 --device cpu --batch-size 16 --seed 42 \
  --warmup-queries 10 --query-repeat 3 \
  --work-dir data/embedding-benchmark/t08-2/grid-001 \
  --output-json data/embedding-benchmark/t08-2/grid-001/results.json

# Step 6: 재집계/별도 DB 재적재/필수 테스트 후 최종 리포트 갱신
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py check \
  --input-json data/embedding-benchmark/t08-2/grid-001/results.json \
  --verify-top-candidates \
  --work-dir data/embedding-benchmark/t08-2/grid-recheck-001

"$ART_PIPELINE_PY" -m pytest tests/test_chunking.py \
  tests/test_benchmark_embeddings.py tests/test_eval_queries.py \
  tests/test_filter_issues.py -q

"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py report \
  --input-json data/embedding-benchmark/t08-2/grid-001/results.json \
  --output-json docs/chunking_embedding_benchmark.json \
  --output-md docs/chunking_embedding_benchmark.md
```

`prepare --baseline-*`는 §9의 고정 보존 경로에 원본 바이트를 저장하고 SHA를 manifest에 기록한다. 보존본이 이미 있으면 덮어쓰지 않고 manifest의 SHA와 대조한다. `preflight --stage tokenizers --model-manifest`는 기존 revision을 재사용하고 새 작업 위치에 환경을 저장하며, `--stage runtime`은 동일 revision의 모델/Chroma smoke를 수행한다. 환경 기록이 늘어도 tokenizer 집합/규칙 fingerprint는 바꾸지 않는다.

`build`는 9쌍의 R/G-B와 스레드 window 3개를 모두 생성하며 manifest에 각 variant의 파라미터를 저장한다. `chunk_corpus check --verify-regeneration`은 variant마다 manifest 값을 읽어 임시 출력에서 비교한다. `matrix`는 전체 variant의 source별 독립 결합을 만들고 모델 수에 맞는 예상 행 수를 검사한다. `run --matrix`는 현재 입력/파라미터와 행렬의 지문을 대조하고 동일 fingerprint의 완료 행만 재사용한다. 행렬 지문은 불변 실험 정의를 기준으로 하며 진행 상태/시각은 별도 필드여서 재개 때 지문을 바꾸지 않는다.

`benchmark check`는 전체 로그 재집계와 파라미터별 재현 증거를 작업 JSON에 저장한다. `report`는 완료율/선정/재현 게이트를 확인한 뒤 해당 JSON과 수치로 최종 MD/JSON을 임시 파일에 생성하고 성공 시 교체한다. 실패하면 작업 결과와 기존 기준선 리포트를 보존한다. 기준선 대비 표는 새 실행에서 다시 측정한 192/32 행을 사용하고 과거 리포트 값은 별도로 표시한다.

Antigravity는 위 순서를 따르고 미확인 항목을 추측으로 PASS 처리하지 않는다. 실행 불가 후보, 보존되지 않은 산출물, 미완료 재현 검사는 상태와 남은 작업을 JSON/Markdown 모두에 기록한다.

## 13. 대형 청크 추가 실험: 224토큰 상한 이후

§1~12의 원문/스팬/지표/선정/Chroma 계약을 재사용한다. 이 절은 **추가 크기 범위, 길이 guard 집합, 임베딩 정책, 출력 위치**를 확장한다. 신규 질문·새 모델·질의 번역을 추가하지 않으며 기존 원문과 100문항을 그대로 사용한다.

### 13.1 확장 근거와 보존할 기준선

현재 JSON SHA-256: `4c9034d1ce2bc35ee6133c50af78d4680d6a568ebc851677aab6f441adc8ceb5`.

`BAAI/bge-base-en-v1.5`와 R-B 방식에서 다른 조건을 고정한 기존 점수는 다음과 같다.

| 바꾸는 축 | 고정 조건 | 128 | 192 | 224 |
|---|---|---:|---:|---:|
| RawPedia 본문 L | R의 O=0, G=`G-A-curated-thread-w224-wo0` | 0.6981 | 0.7582 | **0.7655** |
| GitHub encoder window W | R=`R-B-window-t224-o0` | 0.7155 | 0.7489 | **0.7655** |

표의 값은 **Macro MRR@5**다. 해당 조건의 개선은 상한 확대의 근거이며 모든 방식/O/모델에서 단조 증가한다는 주장은 아니다. 예를 들어 R-B/O=64의 기존 192 점수는 128보다 낮다. 같은 100문항의 반복 탐색이므로 추가 결과도 이 고정셋 안의 비교로 표현한다.

실행 전에 현재 MD/JSON을 `docs/chunking_embedding_baseline_grid_128_224.md/.json`으로 원본 바이트 그대로 보존하고 SHA를 기록한다. 기존 `chunking_embedding_baseline_192_32.*`, `data/chunks/t08-2-grid/`, `grid-001/`도 보존한다. 기존 selected stack은 새 선정이 검증될 때까지 T9 기준점으로 유지한다. 새 구현 조건에서 **224 및 448 비교 기준점은 재측정**하며, 과거의 점수/지연을 새 행에 복사하지 않는다.

### 13.2 입력 한도에 따른 실험 그룹과 실제 크기

BGE 두 모델의 배포 입력 한도는 512, MiniLM은 256이다. [BGE-small 배포 설정](https://huggingface.co/BAAI/bge-small-en-v1.5/blob/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/sentence_bert_config.json), [BGE-base 배포 설정](https://huggingface.co/BAAI/bge-base-en-v1.5/blob/main/sentence_bert_config.json), [MiniLM 배포 설정](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/main/sentence_bert_config.json). E5도 512를 넘으면 잘린다고 [공식 모델 카드](https://huggingface.co/intfloat/multilingual-e5-small/blob/main/README.md)에 명시되어 있다. 실행에서는 기존 고정 revision의 로컬 설정 및 실제 `encoder.max_seq_length`를 다시 대조한다.

| 그룹 | 포함 모델 | 청크 경계/encoder 길이 guard |
|---|---|---|
| `bge-512` | `BAAI/bge-small-en-v1.5`, `BAAI/bge-base-en-v1.5` | 두 모델의 전체 입력이 모두 512 이하인 동일 청크셋 |
| `e5-512` | `intfloat/multilingual-e5-small` | E5의 실제 tokenizer와 `passage: `를 포함해 512 이하인 청크셋 |
| `pooled-common-256` | 기존 4모델 전부, 조건부 단계만 | 검색 청크는 큰 L 유지; 내부 encoder windows만 모든 모델의 배포 한도 이하로 제한 |

512 그룹에서 MiniLM을 제외하는 사유는 **입력 한도**다. 기존 4모델 전체 guard를 대형 청크에 그대로 적용하여 256 근처로 축소하지 않는다. BGE/E5의 토큰화가 달라 서로 경계를 제한하지 않도록 두 그룹을 분리한다. 그룹 사이의 비교는 **모델과 경계를 함께 포함한 스택 비교**이며 동일 청크에서 모델만 바꾼 효과로 설명하지 않는다. BGE 그룹 내에서는 같은 청크의 모델 비교가 가능하다.

모든 그룹에서 reference tokenizer/revision은 기존 BGE-small과 같다. `L/W`는 본문 reference tokens이고, encoder 입력은 실제 title/section/라벨/prefix/special tokens를 포함한다. 헤더는 §4.1의 32 reference tokens로 제한한다. 생성 단계와 **실제 `encoder.encode()` 호출 직전**에 `truncation=False`로 token 수를 검사하며 query/document 모두 검사 대상이다. 배포된 `max_seq_length`를 임의로 늘리지 않는다.

- native 물리 청크는 그룹 전체 guard에 맞게 끝점을 조정하고 requested/actual tokens·조정 사유·모델별 입력 token 수를 저장한다.
- 스레드 내부 W도 그대로 encode하지 않고 그룹 guard에 맞는 실제 windows로 조정한다. segment 전체 coverage=100%와 원문 token 가중치를 유지한다.
- pooled 물리 청크는 **L 자체를 모델 입력 한도로 축소하지 않는다**. 내부 windows를 조정하여 모든 원문을 encode한다.
- 각 variant에 L/W 요청값, 실제 min/median/p95/max, guard 축소율, 같은 원문 범위/청크셋을 만든 인접 후보를 기록한다. 384/448이 실질적으로 같은 입력이면 크기 증가 효과를 관측했다고 해석하지 않는다.
- `guard_group_id`, guard 모델/revision/한도/prefix 집합, `embedding_policy`, 정책 버전, L/O/W/내부 overlap을 schema·규칙 fingerprint·cache/experiment ID에 포함한다. 같은 variant 문자열이라도 그룹별 파일/청크/cache는 분리한다.

### 13.3 필수 단계 N: native 입력 한도 안의 확대

R-A/R-B와 G-B는 `direct_native_v2`로 직접 encode한다. G-A-curated/full은 전체 스레드 한 벡터를 유지하되, 길이 guard 및 공통 입력 조립을 적용한 `thread_window_mean_v2`를 사용한다. 기존 정책과 입력이 달라지는 부분은 별도 버전으로 남겨 과거 vector cache를 재사용하지 않는다.

| 축 | 후보 |
|---|---|
| RawPedia 및 G-B 본문 L | **224, 256, 320, 384, 448** (224는 비교 기준점) |
| 물리 청크 O | **0, 32, 64**; 각 L에서 모두 비교 |
| G-A-curated/full 내부 W | **224, 256, 320, 384, 448**, 내부 overlap=0 |
| 모델 | `bge-512` 2개 + `e5-512` 1개, 총 **3개** |

448은 512 입력 안에서 헤더/prefix/special tokens의 여유를 둔 본문 후보이며 모든 tokenizer에서 그대로 들어간다는 보장은 아니다. 절 경계/짧은 본문/guard로 실측 크기는 달라질 수 있다. **R/G의 L/O/W는 독립적으로 결합**하고 현재 O=0이나 현재 선정 모델을 고정하지 않는다.

| 항목 | 그룹당 후보 수 | 전체 3모델 실험 수 |
|---|---:|---:|
| RawPedia | 2×5×3 = **30** | — |
| GitHub 정식 | G-B 5×3 + G-A-curated 5 = **20** | — |
| GitHub 진단 | G-A-full 5 = **5** | — |
| 정식 혼합 검색 | 30×20×모델 수 | **1800** |
| 진단 혼합 검색 | 30×5×모델 수 | **450** |
| 전체 | 30×25×모델 수 | **2250** |

BGE 그룹은 정식1200/진단300=1500행, E5 그룹은 정식600/진단150=750행이다. 원문 청크셋은 **그룹당55개, 두 그룹 합계110개**이며 문서 vector cache는 **55×3=최대165 entry**로 재사용한다. 주 query latency 관측은 **2250×100×3=675,000개**다. §7의 분모/측정법을 바꾸지 않으며 예상 시간/공간은 작은 smoke의 실측으로 계산한다.

### 13.4 조건부 단계 P: 512·768·1024 검색 청크

N 완주 후 각 모델의 정식 선두에서 **R 물리 L 또는 G-B 물리 L이 448**이고, 같은 다른 축을 고정한 384 행보다 Macro MRR@5가 높으면 P를 실행한다. 추가로, 같은 방식/O/그룹의 384·448 후보가 **encoder guard 축소 때문에 동일한 전체 본문·원문 범위**를 만들어 큰 물리 청크를 관측하지 못한 경우도 P를 실행한다. 짧은 원문 때문에 같아진 경우는 이 조건에 넣지 않는다. 비교는 반올림 전 값/분자로 하며 `1e-9`는 수치 동률 판정용이다. 실행 전에 `extension_decision.json`에 대상 모델/실험 ID·384/448 점수·실측 크기·guard 사유를 기록한다. 조건을 만족한 모델/후보가 하나라도 있으면 P의 사전 정의된 전체 행렬을 실행한다.

조건을 만족하지 않으면 P는 `not_triggered`와 비교 근거로 기록하고 N에서 선정한다. **G-A의 내부 W만 상한에 있는 경우는 encoder 문맥 한도의 제약**으로 기록한다. 이미 전체 스레드가 한 검색 청크이므로 W=768/1024를 직접 입력한 것처럼 표시하지 않는다. N의 guard 포화만으로 크기 효과가 확인되지 않으면 그 한계를 명시한다.

P는 기존 경량 모델을 유지하면서 **큰 검색 청크를 여러 내부 windows로 encode하고 한 벡터로 집계하는 별도 정책**이다. 큰 L을 한 번에 native encode하는 실험으로 설명하지 않는다. 새 장문 모델 도입은 이번 범위에 포함하지 않는다.

| 축 | 후보/정책 |
|---|---|
| R-A/R-B 및 G-B 검색 청크 L | **224, 448, 512, 768, 1024**; 224/448은 동일 pooled 정책의 비교 기준점 |
| 물리 청크 O | **0, 64, 128**; L마다 모두 비교, 명목/실측 O/L 비율 병기 |
| 내부 encoder W/O | **W=224, 내부 O=0**을 모든 모델에서 고정; 실제 길이는 `pooled-common-256` guard 적용 |
| 모델 | 기존 **4개 전부**, MiniLM 포함 |
| G-A-curated/full | 전체 스레드 유지, W=224/내부 O=0의 각 **1variant** |

R/G-B metadata는 `target_tokens=L`, `overlap_tokens=O`, `encoder_window_tokens=224`, `encoder_overlap_tokens=0`, `embedding_policy=chunk_window_mean_v1`이다. G-A는 물리 L/O=null, `thread_window_mean_v2`로 같은 W=224를 쓴다. R의 헤딩 경계·G-B의 서로 다른 원문 분리 원칙은 유지한다.

각 검색 청크의 source segments를 내부 windows로 빠짐없이 분할하고 `v_chunk=normalize(sum(w_i*v_i)/sum(w_i))`로 집계한다. `w_i`는 실제 원문 reference tokens이며 생성 라벨/title은 제외한다. 물리 청크끼리의 overlap은 허용하되 한 청크 내부의 원문은 중복 가중하지 않는다. 내부 windows의 원문 범위/입력 해시/입력 token 수/가중치/호출 수를 저장한다. 토큰 ID decode나 임의 truncation 없이 모든 내용이 임베딩에 기여해야 한다. hidden window는 별도 top-k 결과가 아니다.

| 항목 | 계산 | 수 |
|---|---|---:|
| RawPedia | 2×5×3 | **30variant** |
| GitHub 정식 | G-B 5×3 + curated thread 1 | **16variant** |
| GitHub 진단 | full thread 1 | **1variant** |
| 정식 혼합 검색 | 30×16×4 | **1920행** |
| 진단 혼합 검색 | 30×1×4 | **120행** |
| 전체 | 30×17×4 | **2040행** |
| 문서 vector cache | (30+16+1)×4 | **최대188 entry** |

P의 주 지연 관측은 **612,000개**다. 실제 원문이 짧아 동일 청크가 생성되는 경우를 숨기지 않는다. P 안에서는 모든 모델/길이에 같은 집계 정책을 쓰므로 크기 효과를 비교할 수 있다. N과 P의 차이는 임베딩 정책도 포함한다. native 224↔pooled 224, native 448↔pooled 448의 대응 행으로 정책 변경의 영향을 따로 보여준다.

### 13.5 후속 구현·산출물·선정 계약

현행 코드를 확인했으며 큰 숫자를 기존 CLI에 전달하는 것만으로 이 추가 계약을 충족하지 않는다. 다음은 **후속 구현 작업**이다.

- `src/artagent/chunking.py`: 실제 입력 조립/헤더 제한/길이 검사와 그룹별 guard를 생성·encode에서 재사용한다. 현재 `TokenizerBundle.check_length_guard()`는 정의되어 있으나 생성/encode 경로에서 호출되지 않는다. N에서는 실제 경계를 검사·조정하고 P에서는 큰 source chunk와 작은 encoder window를 분리한다.
- `scripts/chunk_corpus.py`: 그룹/정책/실측 길이를 manifest에 저장하고 보존 파일명의 `--baseline-prefix`를 추가한다. 재생성 시 현재 고정 `grid-001/environment.json` 대신 해당 manifest의 모델/정책/출력 경로를 사용한다. N/P의 규칙·그룹·정책별 모든 JSONL을 재생성한다.
- `scripts/benchmark_embeddings.py`: 그룹 및 정책을 manifest에서 읽고 물리 pooled 청크의 encode를 추가한다. 전 encode 호출에 실제 길이 검사를 적용한다. Chroma `documents`에 현재 `content[:200]` 대신 **전체 content**를 적재하고 trace를 반환한다. 큰 청크의 끝 근거도 실제 반환 본문에 있어야 한다.
- 현행 `run`은 query vector를 사전 encode하고 첫 query encode 시간 하나를 검색 시간에 더하며 `--query-repeat`를 측정 루프에 적용하지 않는다. 확장에서는 **100문항×3회의 실제 query encode→검색→전체 결과 구조화**를 계측한다. 진단 검색 cache와 주 latency 경로를 구분하고 예전 지연은 동일 조건의 측정값으로 재사용하지 않는다.
- matrix/report/check의 고정 variant 수·grid 값·`data/chunks/t08-2-grid/` 경로·192/32 기준선 조회를 해당 행/manifest 참조로 바꾼다. input/protocol fingerprint, 정책, 모델 한도, 실패 상태, 100문항 로그를 저장하고 미완료 행을 이어서 수행한다.
- `decide-extension --inputs ... --output-json ...`은 검증한 N 전체 행과 청크 실측으로 §13.4의 trigger를 계산하고 판정 파일을 저장한다. `combine --inputs ... --extension-decision ... --output-json ...`은 그룹별 **검증된 새 실행 결과**를 합친다. 질문/원문 지문, k/관련도/분모, CPU/dtype/계측/index 조건이 같아야 한다. 그룹·정책 차이는 행에 명시하고 N/P 행 수와 P trigger 판정을 보존한다. 이전 1080행은 과거 기준선 링크로 연결하며 새 성공 행 수에 더하지 않는다.

공통 `protocol_fingerprint`는 입력/질문·지표·계측·index 조건의 지문이다. 그룹/모델/청크 파라미터/임베딩 정책은 비교할 실험 축이므로 각 행의 `experiment_id`에 넣고 통합 시 차이를 허용한다. 모델별 revision은 동일 모델을 N/P에서 비교할 때 일치해야 한다.

새 작업 위치:

```text
docs/chunking_embedding_baseline_grid_128_224.md/.json
data/chunks/t08-2-large-native/bge-512/       # manifest/55 variant/gold mapping
data/chunks/t08-2-large-native/e5-512/        # manifest/55 variant/gold mapping
data/chunks/t08-2-large-pooled/              # 조건부 manifest/47 variant/gold mapping
data/embedding-benchmark/t08-2/large-native-bge-512-001/
data/embedding-benchmark/t08-2/large-native-e5-512-001/
data/embedding-benchmark/t08-2/large-pooled-001/
data/embedding-benchmark/t08-2/large-combined-001/
  results.json                              # N + 실행한 P의 새 결과/선정 정본
  extension_decision.json                    # P 실행/미실행, 상한·guard 포화 근거
  reproduction.json                         # 별도 DB 재적재 증거
```

§8.1의 선정 순서는 유지한다. 최종 후보 집합은 N의 정식1800행과, P를 실행한 경우 P의 정식1920행이다. 각 진단 행은 전 비교표에 남긴다. 선정 JSON은 현행 `selected_stack`에서 모델/R/G만 쓰던 필드를 확장하여 **그룹, 각 출처 L/O/W, physical/thread embedding policy, guard 모델 및 한도, manifest/JSONL 경로·SHA, 입력/protocol SHA, T9 재생성 명령**을 모두 갖춘다. `selected`와 `selected_stack`을 동시에 유지한다면 같은 객체를 참조하도록 정하고 서로 다른 선정값을 쓰지 않는다.

추가 보고 내용:

- N/P별 grid 정의·예상/성공/실패 행 수·성공률; 2250 또는 P 포함 **4290행**을 분모로 쓰고 실패를 분모에서 지우지 않는다. P가 `not_triggered`면 N의 2250이 분모다.
- 각 source의 길이/O를 다른 축을 고정해 비교한 표, 224 대비 품질/실제 크기/지연/vector bytes/상위 문맥 tokens 증감. R/G 같은 크기만 짝짓지 않는다.
- 큰 청크는 정답 스팬을 포함하기 쉬우므로 Hit/MRR 외에 **FullEvidence_all@5, complex 전체 근거, top5 총/중복 제거 tokens, 근거 밀도**를 병기한다. 근거 밀도는 대응 support 근거의 비공백 문자 합집합/반환 원문 비공백 문자 합집합이며 생성 prefix/라벨은 제외한다. 핵심이 적은 긴 본문 반환을 품질 상승과 구분한다.
- `boundary_status`: `interior_peak`, `upper_boundary`, `encoder_limited`, `no_effect` 중 판정값과 원문 실측 근거. 같은 값의 plateau면 §8의 비용/동률 규칙으로 선정한다. 1024에서 계속 개선되면 **탐색 상한까지의 최선**으로 표시하고 전역 최적값을 주장하지 않는다.

N/P의 해당 전체 행렬·§7 계측·회귀·재현을 통과한 뒤 최종 `docs/chunking_embedding_benchmark.md/.json`을 갱신하고 T9로 인계한다. 그 전까지 작업 리포트와 기준선 파일을 보존한다.

### 13.6 Antigravity 확장 Step 1~6 및 회귀

1. **기준선/입력 고정:** 현재 1080 MD/JSON 바이트·SHA, 원문/100문항/147스팬, 모델 revision/배포 한도/환경을 고정한다. 확장 전용 디렉터리와 N/P 정의를 저장한다.
2. **guard 수직 구현:** 한 RawPedia 구간과 한 긴 GitHub body로 N의 448 입력 조립→실제 tokenizer guard→encode→Chroma 전체 content 반환→gold trace를 통과한다. 헤더/prefix로 입력이 초과하는 사례를 먼저 검증한다.
3. **N 후보 생성/회귀:** 두 그룹의 55variant씩을 생성하고 실제 크기/O/스레드 windows·전진/tail/전체 의미 문자 coverage/147근거 추적을 검사한다. 그룹 manifest로 다른 위치에서 재생성하고 바이트를 대조한다. checkpoint: truncation0, 모델별 실제 입력 상한 준수, 그룹별 ID/cache 비충돌.
4. **N 전 행렬 실행:** 1500+750=2250행을 사전 등록하고 고정 100문항×3회 실행·로그·계측·ANN 대조·실패 분석을 마친다. 시간/공간은 실측하고 진행 상태를 보존한다.
5. **상한 판정/P 실행:** §13.4의 trigger 및 실측 guard 상태를 저장한다. trigger면 pooled 수직 구현/회귀를 통과한 뒤 2040행 전부 실행한다. trigger가 없으면 근거와 `not_triggered`를 남긴다. checkpoint: 원문 내용의 인코딩 누락0, P 내부 중복 가중0, N/P 별도 해석, 전체 실행율100%.
6. **통합 선정/재현/T9:** 새 그룹 결과를 합쳐 §8로 선정하고 현재 224 비교점·N 선두·P 선두(실행 시)·최종 선정·차순위를 별도 DB에서 재현한다. MD/JSON을 새 결과로 생성하고 최종 전체 파라미터/실체/SHA/재생성법을 T9로 전달한다. 증거가 갖춰진 뒤 추가 체크 항목을 완료한다.

필수 추가 테스트는 기존 `tests/test_chunking.py`, `tests/test_benchmark_embeddings.py`에 둔다.

- 224/256/320/384/448×O의 전진/실제 중복/결정성, BGE/E5 서로 다른 guard와 MiniLM 제외; 헤더+prefix+special token 때문에 512를 넘는 입력의 분할/거부, encode 직전 길이 검사.
- 512/768/1024 청크의 **tail 근거가 실제 encoder window와 Chroma 반환 content에 포함**됨; requested 큰 L 유지, 내부 W guard, 전체 coverage, 생성 라벨 가중치 제외, zero/NaN/Inf 거부. MiniLM W 입력은 256 이하.
- 그룹/정책 변경 시 ID/cache/experiment 분리, 단일/두 모델 그룹의 행렬 수, manifest 기반 경로·policy 재생성, 3회 실제 query encoder 호출 및 지연 관측 수, 분모95/negative5/147근거 유지.
- trigger의 양성/음성·동률/실측 plateau/encoder 한도 사례, 통합 시 다른 dataset/protocol 거부, 실패 행/부분 로그를 성공 처리하지 않음, 선정 객체/JSON→MD/재현/기준선 보존 일치.

검증 명령은 아래 CLI 이후의 pytest와 §8의 새 DB 재현이다. 의미 성능의 고정 수치를 unit test로 만들거나 단순 ID 일치로 스팬 검증을 대체하지 않는다.

### 13.7 추가 CLI 계약과 실행 예시

**후속 구현 후 실행할 계약**이다. 기존 grid 인자는 재사용하고 `--baseline-prefix`, `--guard-group`, `--physical-embedding-policy`, `--encoder-window-tokens`, `--encoder-overlap-tokens`, `decide-extension`, `combine`을 구현한다. check/report/run은 각 manifest/행의 경로·정책·전체 파라미터를 읽어야 한다. Bash의 변수/배열은 아래 실험 디렉터리에만 쓰며 모델 revision은 기존 환경에서 상속한다.

```bash
set -e
ART_PIPELINE_PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3

# 필수 N: BGE 두 모델 그룹 및 E5 한 모델 그룹을 순서대로 실행
for ART_GUARD_GROUP in bge-512 e5-512; do
  if [ "$ART_GUARD_GROUP" = bge-512 ]; then
    ART_MODEL_IDS=(BAAI/bge-small-en-v1.5 BAAI/bge-base-en-v1.5)
  else
    ART_MODEL_IDS=(intfloat/multilingual-e5-small)
  fi
  ART_LARGE_CHUNKS="data/chunks/t08-2-large-native/$ART_GUARD_GROUP"
  ART_LARGE_WORK="data/embedding-benchmark/t08-2/large-native-$ART_GUARD_GROUP-001"

  "$ART_PIPELINE_PY" scripts/chunk_corpus.py prepare \
    --baseline-md docs/chunking_embedding_benchmark.md \
    --baseline-json docs/chunking_embedding_benchmark.json \
    --baseline-prefix docs/chunking_embedding_baseline_grid_128_224 \
    --output-dir "$ART_LARGE_CHUNKS"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
    --stage tokenizers --models "${ART_MODEL_IDS[@]}" \
    --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
    --device cpu --work-dir "$ART_LARGE_WORK"
  "$ART_PIPELINE_PY" scripts/chunk_corpus.py build \
    --manifest "$ART_LARGE_CHUNKS/manifest.json" \
    --model-manifest "$ART_LARGE_WORK/environment.json" \
    --guard-group "$ART_GUARD_GROUP" --physical-embedding-policy direct_native_v2 \
    --target-tokens-grid 224 256 320 384 448 --overlap-tokens-grid 0 32 64 \
    --thread-window-tokens-grid 224 256 320 384 448
  "$ART_PIPELINE_PY" scripts/chunk_corpus.py check \
    --manifest "$ART_LARGE_CHUNKS/manifest.json" --verify-regeneration
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
    --stage runtime --model-manifest "$ART_LARGE_WORK/environment.json" \
    --device cpu --work-dir "$ART_LARGE_WORK"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py matrix \
    --chunk-manifest "$ART_LARGE_CHUNKS/manifest.json" \
    --model-manifest "$ART_LARGE_WORK/environment.json" \
    --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
    --output-json "$ART_LARGE_WORK/experiment_matrix.json"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py run \
    --matrix "$ART_LARGE_WORK/experiment_matrix.json" \
    --chunk-manifest "$ART_LARGE_CHUNKS/manifest.json" \
    --model-manifest "$ART_LARGE_WORK/environment.json" \
    --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
    --batch-size 16 --seed 42 --warmup-queries 10 --query-repeat 3 \
    --work-dir "$ART_LARGE_WORK" --output-json "$ART_LARGE_WORK/results.json"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py check \
    --input-json "$ART_LARGE_WORK/results.json" --verify-top-candidates \
    --work-dir "$ART_LARGE_WORK/recheck"
done
```

앞 Bash 블록에 이어 실행한다. 두 N 결과를 검증한 뒤 `decide-extension`이 trigger를 계산한다. `trigger`는 JSON boolean이며 아래 분기는 이를 읽어 P를 수행한다. 판정 파일 생성/읽기 실패는 `set -e`로 중단한다.

```bash
set -e
ART_LARGE_INPUTS=(
  data/embedding-benchmark/t08-2/large-native-bge-512-001/results.json
  data/embedding-benchmark/t08-2/large-native-e5-512-001/results.json
)
ART_EXTENSION_DECISION=data/embedding-benchmark/t08-2/large-combined-001/extension_decision.json
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py decide-extension \
  --inputs "${ART_LARGE_INPUTS[@]}" --output-json "$ART_EXTENSION_DECISION"
ART_RUN_POOL="$("$ART_PIPELINE_PY" -c 'import json; from pathlib import Path; print("yes" if json.loads(Path("data/embedding-benchmark/t08-2/large-combined-001/extension_decision.json").read_bytes())["trigger"] else "no")')"

if [ "$ART_RUN_POOL" = yes ]; then
  ART_POOL_CHUNKS=data/chunks/t08-2-large-pooled
  ART_POOL_WORK=data/embedding-benchmark/t08-2/large-pooled-001
  "$ART_PIPELINE_PY" scripts/chunk_corpus.py prepare \
    --baseline-md docs/chunking_embedding_benchmark.md \
    --baseline-json docs/chunking_embedding_benchmark.json \
    --baseline-prefix docs/chunking_embedding_baseline_grid_128_224 \
    --output-dir "$ART_POOL_CHUNKS"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
    --stage tokenizers \
    --models BAAI/bge-small-en-v1.5 BAAI/bge-base-en-v1.5 \
      sentence-transformers/all-MiniLM-L6-v2 intfloat/multilingual-e5-small \
    --model-manifest data/embedding-benchmark/t08-2/grid-001/environment.json \
    --device cpu --work-dir "$ART_POOL_WORK"
  "$ART_PIPELINE_PY" scripts/chunk_corpus.py build \
    --manifest "$ART_POOL_CHUNKS/manifest.json" \
    --model-manifest "$ART_POOL_WORK/environment.json" \
    --guard-group pooled-common-256 --physical-embedding-policy chunk_window_mean_v1 \
    --target-tokens-grid 224 448 512 768 1024 --overlap-tokens-grid 0 64 128 \
    --thread-window-tokens-grid 224 \
    --encoder-window-tokens 224 --encoder-overlap-tokens 0
  "$ART_PIPELINE_PY" scripts/chunk_corpus.py check \
    --manifest "$ART_POOL_CHUNKS/manifest.json" --verify-regeneration
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py preflight \
    --stage runtime --model-manifest "$ART_POOL_WORK/environment.json" \
    --device cpu --work-dir "$ART_POOL_WORK"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py matrix \
    --chunk-manifest "$ART_POOL_CHUNKS/manifest.json" \
    --model-manifest "$ART_POOL_WORK/environment.json" \
    --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
    --output-json "$ART_POOL_WORK/experiment_matrix.json"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py run \
    --matrix "$ART_POOL_WORK/experiment_matrix.json" \
    --chunk-manifest "$ART_POOL_CHUNKS/manifest.json" \
    --model-manifest "$ART_POOL_WORK/environment.json" \
    --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
    --batch-size 16 --seed 42 --warmup-queries 10 --query-repeat 3 \
    --work-dir "$ART_POOL_WORK" --output-json "$ART_POOL_WORK/results.json"
  "$ART_PIPELINE_PY" scripts/benchmark_embeddings.py check \
    --input-json "$ART_POOL_WORK/results.json" --verify-top-candidates \
    --work-dir "$ART_POOL_WORK/recheck"
  ART_LARGE_INPUTS+=("$ART_POOL_WORK/results.json")
fi

"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py combine \
  --inputs "${ART_LARGE_INPUTS[@]}" --extension-decision "$ART_EXTENSION_DECISION" \
  --output-json data/embedding-benchmark/t08-2/large-combined-001/results.json
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py check \
  --input-json data/embedding-benchmark/t08-2/large-combined-001/results.json \
  --verify-top-candidates --work-dir data/embedding-benchmark/t08-2/large-recheck-001
"$ART_PIPELINE_PY" -m pytest tests/test_chunking.py \
  tests/test_benchmark_embeddings.py tests/test_eval_queries.py tests/test_filter_issues.py -q
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py report \
  --input-json data/embedding-benchmark/t08-2/large-combined-001/results.json \
  --output-json docs/chunking_embedding_benchmark.json \
  --output-md docs/chunking_embedding_benchmark.md
```

`combine --extension-decision`은 N의 원본 실행 로그/반올림 전 집계를 이용한 trigger를 다시 계산하여 decision 파일과 대조한다. trigger=true인데 P 결과가 없으면 통합은 미완료로 남기고 최종 report 갱신을 거부한다. trigger=false인데 P를 임의 생략한 것처럼 상태를 바꾸지 않는다. 기준선 prefix의 보존본은 존재 시 SHA를 대조하며 다른 바이트를 덮어쓰지 않는다.

## 14. 두 번째 상한 검증: native 입력 예산과 1536·2048 검색 청크

### 14.1 최신 결과의 해석과 확장 근거

2026-09-29 조사 기준 HEAD는 `7b4dbe8f7`이다. 현재 `docs/chunking_embedding_benchmark.json` SHA-256은 `c2c0beec2a4d80b05486e52dbe8f562d6f5a317110fd1ec100b7123fe67046e3`이다. 먼저 현재 MD/JSON을 `docs/chunking_embedding_baseline_large_448_1024.md/.json`으로 원본 바이트 그대로 보존한다. 기존 4290행과 모든 과거 기준선도 보존한다.

아래는 **R-B 방식, GitHub=`G-A-curated-thread-w224-wo0`를 고정**한 Macro MRR@5다. 표 안에서는 모델·임베딩 정책·O가 같고 L만 바뀐다. 과거 저장 집계는 소수점 4자리이므로 새 trigger는 재측정한 query별 원시 점수로 계산한다.

| 모델/정책/물리 O | L=224 | 384 | 448 | 512 | 768 | 1024 |
|---|---:|---:|---:|---:|---:|---:|
| E5 / native / O=32 | 0.7295 | 0.7863 | **0.8032** | 미실행 | 입력 한도 초과 | 입력 한도 초과 |
| E5 / pooled W=224 / O=0 | **0.7673** | 미실행 | 0.6609 | 0.6663 | 0.6339 | 0.6278 |
| MiniLM / pooled W=224 / O=128 | 0.5486 | 미실행 | 0.6170 | 0.6546 | 0.6812 | **0.7101** |

- **native 후속 질문:** 448보다 실제로 긴 본문을 512 encoder 입력 예산 안에서 encode하면 개선되는가? E5 선두뿐 아니라 N의 BGE 두 모델 선두도 물리 L=448이므로 세 모델을 검증한다.
- **pooled 후속 질문:** MiniLM에서 1024보다 긴 검색 청크를 같은 W=224로 평균하면 개선이 이어지는가? E5를 같은 정책의 대조 모델로 함께 측정한다. MiniLM O=0은 768→1024에서 0.7018→0.6539로 낮아져 O까지 고정한 비교가 필요하다.
- 현재 전체 선두 E5/native의 0.8032와 E5/pooled의 0.6278을 L만 다른 실험처럼 잇지 않는다. 정책 변경에 따른 정보 집계 효과도 포함된다. 기존 1080행 대비 MRR은 올랐지만 Hit@5는 0.9000→0.8854로 내려갔으므로 지표별 증감을 함께 보고한다.

현재 report의 경계 판정은 `L==448`을 검사하고 크기 표도 native의 224~448만 표시한다. 이는 N의 경계를 설명하며 P의 1024 결과를 포함한 전체 크기 곡선이 아니다. 후속 report는 **모델·출처·방식·guard 그룹·정책·O·고정된 다른 출처 variant**별 곡선과 경계를 출력하고 manifest의 실제 탐색 상한으로 판정한다. 다른 정책에서 같은 `R-B-window-t448-o0` 문자열을 쓰더라도 별도 행으로 식별한다.

### 14.2 확대 전에 보정할 실행 계약

새 숫자를 넣기 전에 아래 항목을 구현·검증한다. 기존 Task 8-2 체크는 실행 이력으로 보존하고 이번 보정 및 확장은 별도 미완료 항목으로 추적한다.

| 현재 확인한 사항 | 구현·검증 조건 |
|---|---|
| `truncate_text_to_guard()`가 본문 끝을 줄인 뒤 R-B가 원래 `curr_idx` 또는 `t_end`로 전진함 | 길이 guard는 **새 청크 경계 결정**에 사용한다. 줄어든 실제 끝점 이후의 원문을 다음 청크에서 반드시 회수한다. 긴 한 문장·표·마지막 청크에서도 누락/무한 루프가 없어야 한다. R-A와 G-B도 같은 조건으로 검사한다. |
| 현재 E5/native R-B 448/O=0은 pooled의 같은 L/O 구간 합집합 대비 비공백 내용을 가진 42구간, 총 11,130문자가 빠짐 | 원문 파일별 허용 본문 구간 합집합과 생성된 source segment 합집합을 직접 대조한다. 비공백 원문 누락0을 필수로 하고 누락 위치·길이를 로그로 남긴다. 골드 스팬 147개만 모두 덮는 검사로 대신하지 않는다. |
| 현재 선정된 E5/native 448/O=32도 pooled 448/O=0 합집합 대비 비공백 내용을 가진 8구간, 총 4,585문자가 빠짐 | 위 수는 비교된 누락 구간의 전체 문자 길이 합이며 모든 문자가 비공백이라는 뜻은 아니다. `Tutorials/game_changer/introduction.md`, `keyboard_shortcuts.md`의 잘린 tail을 회귀 fixture로 포함한다. 현재 선정 행도 보정한 경계로 재측정한다. |
| thread/pooled 초과 window 재분할이 생성 헤더까지 reference tokenize하고 그 token 수를 가중치로 사용함 | 내부 windows는 원문 body offsets에서 만들고 prefix/헤더는 입력 조립 때 붙인다. 가중치는 window가 담당한 원문 reference token 수다. 모든 encoder 입력을 검사하고 원문 coverage=100%, 생성 라벨 가중0을 보장한다. |
| query encode 시간을 모델별로 미리 측정하고 cached vector 검색 시간에 더하여 p95를 계산함 | 각 행의 각 query/repeat에서 실제 `encode → Chroma query → 전체 content/metadata 수신 및 결과 구성`을 하나의 타이머로 잰다. 검색 부분/encode 부분은 보조 지표로 분리한다. 사전 계측 합을 end-to-end p95로 표기하지 않는다. |
| 통합 행/선정 JSON에서 정책·guard 정보가 파일 경로에 의존함 | 각 행에 `stage_id`, `guard_group`, source별 정책/L/O/W, protocol/input/manifest/JSONL SHA를 저장한다. 행 ID와 vector cache 키에 모델 revision·정책 버전·실제 입력 hash를 포함한다. report가 경로 이름이나 `_p` 접미사로 실험 유형을 추측하지 않게 한다. |

누락 수는 원문 Unicode 문자 좌표의 반열린 구간 합집합 차이를 로컬 JSONL에서 계산한 조사 결과다. 실제 판정에서는 §2의 고정 원문/허용 범위를 기준으로 RawPedia 116개와 GitHub 정제 35개 piece를 전수 검사한다. frontmatter·생성 라벨·명시적으로 제외한 비본문 범위는 coverage 분모에서 분리해 기록한다.

보정 정책은 `direct_native_v3`, `chunk_window_mean_v2`, `thread_window_mean_v3`로 버전을 올린다. 모델/reference tokenizer revision, query prefix, 데이터, k, source별 분모와 Chroma 설정은 유지한다. **현재 v2/v1 vector 및 결과 cache를 새 정책의 결과로 재사용하지 않는다.** 원문 경계 또는 window 가중치가 바뀐 과거 행은 보존된 이력으로 표시하고 같은 실행 protocol의 새 기준점과 비교한다.

### 14.3 필수 단계 Q-N: 512 입력 예산 안의 추가 후보

이번에는 모델별 경계를 확인하는 **부분 행렬**을 사전 등록한다. 각 모델의 GitHub 선두 스레드 variant를 고정하여 R의 L/O 효과를 분리한다. GitHub 물리 L/W 전체 최적화를 다시 수행했다는 주장은 하지 않는다. 검색은 계속 두 출처가 함께 들어간 코퍼스에서 수행한다.

| 축 | 후보/고정값 |
|---|---|
| RawPedia 방식 | R-A-heading, R-B-window 둘 다 |
| 요청 본문 reference L | **384, 448, 464, 480, 496, 512**; 384/448은 보정한 기준점 |
| 물리 reference O | **0, 32, 64**, 모든 L에서 교차 비교 |
| 모델/guard | N과 같은 BGE 두 모델의 `bge-512`, E5 한 모델의 `e5-512` |
| 고정 GitHub variant | BGE-base: curated thread W=320; BGE-small: W=384; E5: W=224; 모두 내부 O=0 |
| 정책 | R=`direct_native_v3`, G=`thread_window_mean_v3` |

**L=512는 요청 본문 상한이다. 전체 encoder 입력 한도 512와 구분한다.** 생성 헤더·prefix·special tokens를 포함한 실제 모델 token 수가 512 이하가 되도록 끝점을 정하고 잘린 나머지를 이어서 청킹한다. `encoder.max_seq_length`나 모델 설정을 늘리지 않는다. 요청 L/실제 reference L/모델 입력 tokens/guard 조정 사유를 모두 기록한다. O도 조정된 실제 경계를 기준으로 적용하고 실측 overlap을 기록한다.

정식 행은 모델마다 `2×6×3×1=36`, 합계 **108행**이다. BGE 두 모델은 같은 guard 청크셋을 사용하되 GitHub W만 각각 고정한다. requested L이 달라도 guard 때문에 동일 본문·범위를 만든 경우 `geometry_equivalent=true`로 남기며 새 크기 개선으로 해석하지 않는다. 실제 입력 예산이 포화되면 `encoder_limited`로 종료한다. 같은 경량 모델의 native L을 768/1024로 계속 늘려 테스트하지 않는다.

### 14.4 필수 단계 Q-P: 1536·2048 검색 청크

MiniLM의 1024/O=128 개선을 검증하기 위해 아래 부분 행렬을 실행한다. E5는 동일 pooled 정책에서 확대 효과를 비교하는 대조군이다. E5 직접 방식과의 실용 스택 비교에는 Q-N의 재측정 행을 사용하며 L·guard 경계·정책이 함께 달라지는 비교로 표기한다.

| 축 | 후보/고정값 |
|---|---|
| RawPedia 방식 | R-A-heading, R-B-window 둘 다 |
| 검색 청크 L | **224, 768, 1024, 1536, 2048**; 224/768/1024는 보정한 기준점 |
| 물리 O | **0, 64, 128**, 모든 L에서 교차 비교 |
| 모델 | `sentence-transformers/all-MiniLM-L6-v2`, `intfloat/multilingual-e5-small` |
| encoder W/내부 O | **224/0** 고정, 기존 4모델의 `pooled-common-256` guard 집합/revision 유지 |
| 고정 GitHub variant | curated thread W=224/내부 O=0, 전체 정제 스레드 한 벡터 |
| 정책 | R=`chunk_window_mean_v2`, G=`thread_window_mean_v3` |

정식 행은 `2×5×3×1×2=60`이다. 큰 검색 청크 L을 실제로 유지하면서 원문 전체를 여러 encoder windows로 분할해 가중 평균한다. 1536/2048은 MiniLM 한 번의 입력 길이를 뜻하지 않는다. window의 원문/내용 위치, 모델별 실제 입력 tokens, 가중치, 원문 token 합집합 coverage, chunk당 window 수를 저장한다. 원문 tail까지 encode한 뒤 Chroma에는 전체 청크 본문을 반환한다.

**조건부 4096:** Q-P 완주 후 모델별 정식 선두가 L=2048이고, 같은 R 방식/O/G variant/정책의 1536 및 1024보다 반올림 전 Macro MRR@5가 높으며, 아래 B=4096의 budget FullEvidence_all@5가 1024보다 낮지 않을 때 실행한다. 하나 이상의 모델이 충족하면 두 모델 모두 R 두 방식×O 세 값×L=4096을 추가하여 **12행**을 실행한다. `boundary_extension_decision.json`에 대응 행 ID·query별 차이·품질/문맥 비용·trigger를 저장한다. 조건 불충족이면 `not_triggered`와 비교 근거를 남긴다.

Q-N 108 + Q-P 60 = **정식168행**, 4096 실행 시 **180행**이다. 새 진단 full-thread 행은 추가하지 않으며 기존 570개 진단 행은 보존한다. 실제 query latency 관측 수는 100문항×3회로 **50,400개**, 4096 포함 시 **54,000개**다. 기존 4290행을 이 수에 합쳐 새 protocol 완주율로 계산하지 않는다. 선언한 부분 행렬 안의 누락/실패 행은 그대로 분모에 포함한다.

### 14.5 큰 청크의 품질·문맥 비용과 중단 기준

기존 **Hit@1/3/5, MRR@5, FullEvidence_all@5, 출처별/micro/macro 집계, 95양성/5negative 분리**를 유지한다. 아래를 query별로 추가하여 Hit/MRR 상승이 더 긴 문맥 반환만으로 얻어진 것인지 확인한다.

- 반환 top5의 총 reference tokens, 원문 위치 합집합 기준 중복 제거 tokens, 전체/complex support 근거 coverage 및 §13.5의 근거 밀도, vector bytes·색인 시간·chunk/window 수·실제 end-to-end p50/p95.
- **문맥 예산 B=2048/4096**에서 `budget Hit@5`, `budget FullEvidence_all@5`. 원래 top5 순서대로 전체 청크를 넣고 남은 예산에 안 들어가는 청크는 건너뛴다. 예산 소비량은 고정 직렬화 `section_title + '\n' + content`의 reference tokens이며 스레드 생성 라벨도 포함한다. 이미 넣은 chunk ID만 제거하고 위치가 겹친다고 본문을 임의 축약하지 않는다. packing 결과의 원문 segment 합집합으로 기존 스팬 coverage 판정을 재사용한다. 골드 위치를 보고 자르거나 선택하지 않고 top6 이후에서 채워 넣지 않는다. 전부 못 담으면 빈 결과와 실패를 그대로 집계한다.
- 같은 다른 축을 고정한 인접 L의 query별 reciprocal-rank 차이와 개선/악화/동률 문항 수. Macro와 두 출처를 각각 보고하며 원시 점수를 보존한다. O 변경이나 모델 변경을 크기 단독 효과에 합치지 않는다.

최종 선정은 §8의 순서와 근접 후보 규칙을 유지하되 문맥 예산 결과/근거 밀도/실제 tokens를 함께 공개한다. 예산 초과로 일부 청크가 빠지는 결과는 전체 top5 결과와 별도 표로 제시한다. 예산 실험을 기존 MRR 정의의 변경으로 처리하지 않는다.

경계는 모델/정책/축마다 판정한다. 더 큰 L에서 저하하면 `interior_peak`, 동일 실제 경계면 `encoder_limited` 또는 크기 효과 `no_effect`, 최고점이 실제 탐색 상한에 있고 인접 비교도 개선이면 `upper_boundary`다. 선두에 오른 L만 검사하여 단조 증가를 선언하지 않는다. 4096까지 개선되면 **이 고정 질문셋과 탐색 범위의 최선**으로 기록한다. 이후 확대는 개선 문항·예산 결과·비용 근거를 별도 제안으로 남긴다. 이번 실행에서 장문 모델 도입, 8192 이상 자동 확장, 신규 골드 질문 생성은 포함하지 않는다.

### 14.6 Antigravity Step 1~6 및 산출물

1. **보존·등록:** 현재 4290 MD/JSON 및 원문/147스팬/모델 revision을 고정한다. Q-N/Q-P 부분 행렬, 고정 GitHub map, 새 policy/protocol hash와 168행 예상 수를 저장한다. 기존 selected는 과거 실행 기준점으로 보존한다.
2. **보정·회귀:** §14.2의 실제 끝점 기반 전진, body-only window 가중치, end-to-end 타이머, 명시적 정책 ID를 구현한다. 긴 문장·표·tail·비ASCII·512 입력 경계·정책별 cache 분리 테스트를 먼저 통과한다.
3. **수직 검증·생성:** 선정 E5 448/32와 MiniLM 1024/128로 원문→청크→encode→Chroma 전체 반환→스팬 추적을 확인한다. Q-N/Q-P의 모든 후보를 생성하고 116개/35개 piece의 누락0, 실제 입력 상한, 요청/실측 L/O/W 분포와 manifest 재생성을 전수 검증한다. checkpoint: 검사 실패 시 행렬 실행을 시작하지 않는다.
4. **168행 실행:** 두 출처 전량 혼합 검색, 100문항, k=1/3/5, seed=42, CPU, warmup=10, query-repeat=3 조건으로 실행한다. query/repeat 로그·ANN 대조·문맥 예산·실패 상태와 실제 지연을 기록한다. §14.1의 기준점을 복사하지 않고 새 정책으로 재측정한다.
5. **4096 판정·실행:** Q-P의 대응 행과 예산 결과로 trigger를 계산한다. 조건 충족 시 12행 추가, 불충족 시 근거와 `not_triggered`를 저장한다. checkpoint: 168 또는 180행 완주·50,400 또는 54,000개 실제 지연 관측·원문 누락0.
6. **보고·재현·T9:** 새 protocol의 native/pooled 기준점, 모델별 선두, 최종 후보/차순위를 새 Chroma DB에서 재현한다. 기존 4290행은 역사 표에 두고 새 정책의 검증된 행으로 선정한다. 모델·guard·정책·각 출처 파라미터·입력/청크/vector hash·전체 인코딩/반환 증거·재생성법을 최종 MD/JSON과 T9 인계에 기록한다. 이후 이번 추가 체크를 완료한다.

후속 구현은 기존 `src/artagent/chunking.py`, `scripts/chunk_corpus.py`, `scripts/benchmark_embeddings.py`, `tests/test_chunking.py`, `tests/test_benchmark_embeddings.py`에 둔다. 새 의존성/일반 설정 로더는 필요하지 않다. 산출물은 다음처럼 기존 실행과 분리한다.

| 산출물 | 위치/내용 |
|---|---|
| Q-N 청크·manifest | `data/chunks/t08-2-boundary-native/{bge-512,e5-512}/` |
| Q-P 청크·manifest | `data/chunks/t08-2-boundary-pooled/` |
| 모델별 Q-N 실행 | `data/embedding-benchmark/t08-2/boundary-native-{bge-base,bge-small,e5}-001/` |
| Q-P 실행 | `data/embedding-benchmark/t08-2/boundary-pooled-001/` |
| 사전 행렬/결정/통합 | `data/embedding-benchmark/t08-2/boundary-combined-001/`; manifest, 원시 query/repeat 로그, `boundary_extension_decision.json`, `results.json`, 재현 증거 |
| 최종 리포트 | 검증 후 `docs/chunking_embedding_benchmark.md/.json`; 과거 4290행은 새 protocol의 완주율과 분리 |

### 14.7 CLI 확장 계약과 실행 연결

**아래 인자는 후속 구현 대상**이다. 기존 §13의 prepare→preflight→build→check→matrix→run→check→report 순서를 유지한다.

- `chunk_corpus build`: 새 physical 정책 두 개와 `--thread-embedding-policy thread_window_mean_v3`를 지원한다. manifest에 전체 정책/guard 설정과 coverage 검사 결과를 저장한다. Q-N은 L=`384 448 464 480 496 512`, O=`0 32 64`; BGE 그룹 thread W=`320 384`, E5 W=`224`로 curated thread만 생성한다. Q-P는 L=`224 768 1024 1536 2048`, O=`0 64 128`, encoder W/O=`224/0`, curated thread W=`224`다.
- `matrix`: `--model-ids`, `--github-variant-ids` 필터를 추가하여 **모델별 다른 고정 GitHub**를 명시적으로 등록한다. 필터 ID의 존재/유일성, source별 파일/policy/guard 호환성을 검증한다. Q-N은 같은 BGE manifest에서 모델별 36행씩 별도 matrix를 만들고 E5 36행을 더한다. BGE 두 작업의 환경에는 두 모델의 guard 설정을 모두 유지하고 평가 모델만 필터한다. Q-P도 기존 4모델 guard 환경에서 평가 모델 두 개만 골라 60행을 만든다. 평가 모델 필터로 guard 집합을 바꾸지 않는다.
- `run`: `--context-budgets 2048 4096`을 지원하고 직접 계측한 300개의 query/repeat 관측을 행마다 저장한다. 각 query의 정렬된 top5/score/source segments, support별 coverage, budget packing 결과와 구성 시간을 남긴다. 동일 fingerprint의 새 protocol 완료 행만 resume한다.
- `decide-extension`: 기존 N→P 판정과 구분하는 `--stage boundary-pooled`을 추가하여 §14.4의 4096 조건을 계산한다. `combine/check/report`는 예상 168/180행, 실패/미실행 상태, protocol 호환성, 명시적 stage/group/policy와 원문 누락 검사를 확인한다. `report`는 기준선 보존·재현/coverage 게이트를 통과한 뒤 최종 파일을 갱신한다.

예를 들어 BGE-base용 matrix/run은 **위 확장 구현과 청크 검사 후** 다음처럼 호출한다. 다른 모델/단계도 같은 계약으로 해당 표의 모델·GitHub 고정값·작업 경로를 사용한다.

```bash
set -e
ART_PIPELINE_PY=/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3
ART_BOUNDARY_WORK=data/embedding-benchmark/t08-2/boundary-native-bge-base-001

"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py matrix \
  --chunk-manifest data/chunks/t08-2-boundary-native/bge-512/manifest.json \
  --model-manifest "$ART_BOUNDARY_WORK/environment.json" \
  --model-ids BAAI/bge-base-en-v1.5 \
  --github-variant-ids G-A-curated-thread-w320-wo0 \
  --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
  --output-json "$ART_BOUNDARY_WORK/experiment_matrix.json"
"$ART_PIPELINE_PY" scripts/benchmark_embeddings.py run \
  --matrix "$ART_BOUNDARY_WORK/experiment_matrix.json" \
  --chunk-manifest data/chunks/t08-2-boundary-native/bge-512/manifest.json \
  --model-manifest "$ART_BOUNDARY_WORK/environment.json" \
  --queries docs/search_eval_queries.json --ks 1 3 5 --device cpu \
  --batch-size 16 --seed 42 --warmup-queries 10 --query-repeat 3 \
  --context-budgets 2048 4096 --work-dir "$ART_BOUNDARY_WORK" \
  --output-json "$ART_BOUNDARY_WORK/results.json"

"$ART_PIPELINE_PY" -m pytest tests/test_chunking.py \
  tests/test_benchmark_embeddings.py tests/test_eval_queries.py tests/test_filter_issues.py -q
```

추가 회귀는 **guard로 줄인 tail의 다음 청크 회수와 원문 합집합**, 입력 한도에 닿은 여러 L의 실제 경계 동률, 1536/2048/4096 tail의 실제 encoder/반환 coverage, 생성 헤더 가중0, budget 경계/빈 결과/중복 chunk ID, 모델별 고정 G 필터와 행 수, 매 query/repeat의 실제 encoder 호출 및 단일 타이머를 확인한다. 통합은 새 공통 평가 protocol 아래 Q-N/Q-P 정책 차이를 실험 요인으로 허용하며 과거 protocol의 결과/cache 혼입은 거부한다. 의미 성능 수치를 unit test에 고정하지 않는다. 계획 문서 수정 자체는 실행 증거가 아니며 새 CLI/회귀/168행과 조건부 실행 검증은 Antigravity가 수행한다.

## 15. 현행 정책 전체 조합 재측정과 선정 재검증

### 15.1 재측정 범위와 과거 결과 보존

2026-09-29 조사 HEAD는 `8b5719589`다. 현재 정책은 물리 native=`direct_native_v3`, 물리 pooled=`chunk_window_mean_v2`, 스레드=`thread_window_mean_v3`다. §14에서 원문 누락과 초과 window의 본문 분할·헤더 가중치를 함께 보정했으므로, **과거 v1/v2 점수와 최신 v3 일부 행을 섞어 모델·방식·L/O/W를 선정하지 않는다.** §14의 고정 GitHub 부분 행렬만으로 GitHub 규칙이나 전체 모델 조합을 다시 최적화했다고 표시하지 않는다.

현재 JSON SHA-256은 `324f2bf05ed0b697125deb443d1652b506bb25b3a20ed1b03129d4f6f35c8766`이다. 실행 전에 MD/JSON을 `docs/chunking_embedding_baseline_boundary_4096.md/.json`에 원본 바이트 그대로 보존한다. 기존 128~224 기준선, 4290 기준선, 원문·청크·벡터·결과 경로도 보존한다. 최신 180행은 검토 전 실행 이력으로 남기고 `provisional` 상태 및 사유를 새 실행 기록에 연결한다.

재측정의 최소 범위는 **최초 grid 1080 + N/P 4290 + Q-N/Q-P 180의 조합 합집합**이다. 원래의 모델·출처별 방식·요청 L/O/W·guard 의도를 현행 정책으로 옮긴다. 점수가 낮았던 후보, GitHub 개별 원문 후보, BGE pooled 후보도 포함한다. 과거 상한 trigger를 다시 통과해야만 이미 실행한 후보를 재측정하는 방식으로 범위를 줄이지 않는다.

### 15.2 먼저 통과할 guard·검색 재현성 게이트

청크 생성·matrix·run에서 그룹의 **실제 guard 모델 집합**을 검증한다. 그룹명만 저장하고 전체 환경의 모델을 적용하는 현재 경로를 보정한다. reference tokenizer를 로드한 사실과 경계를 제한할 guard 모델에 포함한 사실을 구분한다.

| 그룹 | 정확히 허용하는 guard 모델 | 사용할 물리 정책 |
|---|---|---|
| `native-common-256` | 기존 BGE 두 모델·MiniLM·E5 네 모델, 각각 배포 한도 유지 | 최초 grid를 재측정하는 `direct_native_v3` |
| `bge-512` | BGE-small, BGE-base 두 모델만 | `direct_native_v3` |
| `e5-512` | E5-small 한 모델만 | `direct_native_v3` |
| `pooled-common-256` | 기존 네 모델, 각각 배포 한도 유지 | `chunk_window_mean_v2` |

`native-common-256`은 최초 공통 청크 비교를 현행 정책으로 다시 수행하기 위한 명시적 그룹이다. CLI의 `--guard-group`에 추가하고 그룹별 preflight manifest를 만든다. MiniLM만 배포 한도256이며 다른 모델의 설정을256으로 변경하지 않는다. pooled에서는 검색 청크 L을256으로 줄이지 않고 내부 입력 window를 검사한다. 평가 대상 모델의 필터와 guard 집합은 각각 별도 필드·해시로 저장한다.

- **집합 검사:** manifest 모델 ID/revision/한도/prefix와 그룹 계약이 불일치하면 생성·matrix·run을 실패시킨다. `e5-512`/`bge-512`에 MiniLM이 섞인 입력, 존재하지 않는 필터 ID, 실제 guard 집합과 선언이 다른 청크도 거부한다. 실행 환경에 tokenizer 네 개가 있더라도 E5 청크 경계에는 E5만 적용되는 회귀를 추가한다.
- **청크 검사:** 116개 RawPedia·35개 curated piece의 비공백 누락0과 모든 segment의 원문/해시/좌표 일치를 확인한다. 모델별 전체 입력 tokens, 요청/실제 L/O/W 분포, guard 조정 사유를 기록한다. 448~512 요청이 다른 모델의256 제한 때문에 축소되지 않았음을 guard 집합과 fixture로 검증한다. 숫자 중앙값423 자체를 테스트의 고정 정답으로 삼지 않는다.
- **검색 검사:** 이전 E5 448/32·G-W224의 기록값 `0.7426`과 현재 `check` 재계산값 `0.7259` 차이를 재현·해결한다. Q091의 정답 청크가2위에서 top5 밖으로 빠진 사례를 조사하며, 캐시 벡터와 새 벡터가 일치했다는 관측만으로 검색 문제를 해소했다고 처리하지 않는다. query 입력/벡터, 문서 벡터, 색인 적재 순서·설정, Chroma/NumPy top5·score 및 동점부터 대조한다. 원인은 확인한 증거로 기록한다.
- **공통 경로:** `run`과 `check`가 동일 입력 조립·query encode·Chroma 검색·정렬·스팬 평가 함수를 사용하도록 정리한다. 거리 동점의 chunk ID 순서와5위 후보 집합을 기록하고, 독립적으로 재생성한 색인에서 query별 RR 차이를 검사한다. 기존 허용오차를 넓혀 실패를 통과시키지 않는다. HNSW 등 검색 조건을 변경해야 하면 새 공통 protocol을 고정하고 **전체 합집합**에 적용한다.

이 게이트를 통과한 코드 commit, runtime/package 버전, 실제 모델 설정, 입력·평가 protocol SHA를 고정한 후 전체 실행을 시작한다. 이후 같은 정책명의 구현을 바꾸면 code/encoder fingerprint를 바꾸고 영향을 받는 결과의 유효성을 다시 검사한다.

### 15.3 필수 행렬 R: 과거 탐색의 현행 정책 합집합

아래 L/O/W는 reference tokens이며 R/G 축은 독립적으로 결합한다. 네 모델은 §5의 고정 revision·query/document prefix를 유지한다. 모든 행에서 전체 혼합 코퍼스, 고정100문항, k=1/3/5, 양성80+15·부정5의 분모와 §7~8 지표·선정 순서를 유지한다.

| 원래 탐색 | 현행 정책으로 재측정할 조합 | 원래 행 수 | 합집합에 추가되는 행 |
|---|---|---:|---:|
| 최초 grid | 네 모델/common guard. R-A/R-B: L=128/192/224×O=0/32/64. G-B: 같은 L/O 9개 + curated/full thread W=128/192/224 각3개 | 1080 | 1080 |
| N | BGE 두 모델/bge guard·E5/e5 guard. R-A/R-B: L=224/256/320/384/448×O=0/32/64. G-B: 같은 L/O 15개 + curated/full thread W=224/256/320/384/448 각5개 | 2250 | 2250 |
| P | 네 모델/pooled guard. R-A/R-B: L=224/448/512/768/1024×O=0/64/128. G-B: 같은 L/O 15개 + curated/full thread W=224 각1개. 내부 W/O=224/0 | 2040 | 2040 |
| Q-N | 세 native 모델. R-A/R-B: L=384/448/464/480/496/512×O=0/32/64. G-curated 고정 W: BGE-base320/BGE-small384/E5 224 | 108 | 72 |
| Q-P 및4096 | E5·MiniLM/pooled guard. R-A/R-B: L=224/768/1024/1536/2048/4096×O=0/64/128. G-curated W=224, 내부 W/O=224/0 | 72 | 36 |
| **중복 제거 합계** | **정식4692 / full-thread 진단786** | 5550 | **5478** |

native 그룹의 R/G-B는 `direct_native_v3`, pooled 그룹의 R/G-B는 `chunk_window_mean_v2`, 모든 G-A는 `thread_window_mean_v3`를 적용한다. full-thread 진단 행은 계속 최종 선정에서 제외한다. Q-N의384/448 36행과 Q-P의224/768/1024 36행은 각각 N/P와 중복된다. common guard와512 그룹의224 행은 guard 집합이 달라 별도 조합이다. Q의464~512는 기존 고정 GitHub 조합만 추가하며, 이를 해당 길이의 모든 GitHub 교차 조합까지 탐색한 결과로 표시하지 않는다.

행렬 생성은 보존된 `grid-001/results.json` 또는 최초 grid 보존 JSON, `docs/chunking_embedding_baseline_large_448_1024.json`, 이번 보존한180 JSON의 **파라미터 이력**과 위 표를 대조한다. 과거 파일에 없는 필드는 원래 manifest에서 읽고, grid 결과의 file path 누락을 모델/청크 파일 누락으로 오판하지 않는다. 다음 계약을 기계적으로 검사한다.

1. 요청 조합 키는 `model_id/revision + 정확한 guard 모델 집합/revisions/한도/prefix + R/G family·L/O/W/내부O + 현행 source별 정책 + dataset/protocol hash`다. `stage_id`·시각·출력 경로는 중복 제거 키에 넣지 않고 `origin_stages`로 남긴다.
2. 기존5550행은 각 원본 행→새 조합 키→실행 행 ID로 연결한다. 중복72행과 제외0행을 명시하고 합계5478, 정식4692/진단786을 검증한다. 그룹별 기대 수는 common1080/bge1548/e5 774/pooled2076이다. 요청 파라미터가 다르지만 실제 청크가 같은 경우에는 행을 지우지 않고 `geometry_equivalent`를 기록한다.
3. 물리 청크를 현행 생성 코드·정확한 guard로 재생성한다. 같은 조합의 원문/전체 content/section title/segments/windows/가중치·입력 tokens 및 JSONL SHA가 일치해야 한다. manifest가 실제로 적용한 guard를 증명한다.
4. 실제 실행 ID에는 위 키와 생성된 R/G JSONL·전체 encoder 입력·가중치·구현 fingerprint를 포함한다. cache는 전체 입력 hash를 사용한다. 동일 정책 문자열이나 `content[:40]`만으로 결과를 재사용하지 않는다.

`matrix`에 `--rawpedia-variant-ids` 필터를 추가하여 Q의 추가 R 후보만 등록할 수 있게 한다. 모델/R/G 필터 모두 요청 ID 전체의 존재·유일성을 검사한다. 배치는 common grid1080, BGE N1500+추가48, E5 N750+추가24, pooled P2040+추가36으로 나누고, 각 배치의 정확한 manifest로 `run`한다. Q-N 추가분은 R의 L=464/480/496/512만, Q-P 추가분은 L=1536/2048/4096만이며 표의 모델별 G 고정값을 유지한다. **서로 다른 guard의 같은 rule ID를 한 `chunksets[rule_id]`에 넣어 덮어쓰지 않는다.** 새 ID에 guard/protocol을 포함하고 `combine`은 입력·protocol 일치, 원본 행 매핑, 중복 및 예상 행 수를 검사한 뒤 합친다.

모든5478행은 현행 protocol에서 새로 검색·계측한다. 과거1080/4290 점수는 복사하지 않는다. 현재180행도 protocol SHA와 query별 원시 검색 로그가 없어 이번 실행의 완료 행으로 편입하지 않는다. 새 실행 안의 정확히 같은 encoder 입력은 문서 벡터 cache로 재사용할 수 있지만, 각 행의100문항×3회 `encode→query→전체 결과 구성`은 실제로 수행한다. 필수 지연 관측은 **5478×100×3=1,643,400개**다. 작은 실제 실행으로 예상 시간·저장량을 기록하고 단계별 checkpoint/resume를 제공한다. 소요 시간이 길다는 이유로 모델·GitHub 후보·작은 크기를 조용히 빼지 않는다.

### 15.4 정책 보정의 영향을 분리하는 기준선

아래 세 대조군은 E5·R-B448/O32·G-curated W224를 고정하고, 동일 데이터/모델 revision/prefix/k/Chroma 조건으로 실행한다. 최종 후보의 비교표와 별도 표에 둔다.

| 대조군 | RawPedia 경계/정책 | GitHub 임베딩 | 목적 |
|---|---|---|---|
| C0 | `7b4dbe8f7`의 원래 청크·native v2 구현 | 보존된 thread v2 구현 | 과거 `0.8032` 재현 |
| C1 | 정확한 E5 guard로 생성한 native v3 | C0와 동일한 thread v2 입력/구현 | 청킹 경계·오버랩 보정의 영향 |
| C2 | C1과 동일한 native v3 | 현행 thread v3 | window 재분할·헤더 입력·가중치 보정의 영향 |

**정책 이름만 v2로 바꾸어 현행 encoder 함수를 실행하면 과거 구현 재현이 아니다.** 현재 함수는 여러 버전 이름을 같은 보정 분기로 처리한다. C0/C1은 보존 commit의 실제 encoder 경로를 격리하여 사용하거나 동일 동작의 legacy 분기를 검증한다. C1/C2는 같은 R JSONL SHA를 사용하고, C0/C1의 G 입력 및 legacy encoder fingerprint가 같아야 한다. C2는 필수5478행에 이미 포함된다. C0/C1과 대조군 반복 검증은5478행의 완료 수에 합치지 않는다.

검색 문제 해결에 공통 Chroma 조건 변경이 필요하면, 원래 검색 조건의 `.8032` 재현은 `C0-legacy`로 별도 보존하고 새 공통 조건으로 C0/C1/C2를 모두 측정한다. 이전 검색 조건의 C0와 새 조건의 C1을 빼서 청킹 보정 효과라고 기록하지 않는다. `C0-legacy`도 필수 행 수와 선정 후보에서 제외한다.

세 대조군의 query별 top5·score·RR·support coverage와 출처별/평균 지표를 저장하여 C1−C0, C2−C1을 구분한다. 과거 정책 재현은 원문 누락0을 충족한 현행 스택 선정의 대체물이 아니다. 재계산 결과를 목표값에 맞춰 고치지 않으며 원문 복구가 성능에 미친 영향은 실제 결과로 보고한다.

### 15.5 로그·재현·선정 완료 조건

작업 경로는 새 `data/chunks/t08-2-remeasurement/`, `data/embedding-benchmark/t08-2/remeasurement-001/`을 사용한다. 최소 산출물은 입력·모델/guard manifest, 선언 행렬과 원본 행 매핑, JSONL/gold mapping, 문서 입력/window trace, 행별 결과, query/repeat별 원시 로그, 실패·재개 이력, 기준선/독립 재현 기록이다. 신규 범용 설정 로더는 만들지 않는다.

- 원시 로그에 `experiment_id`, query ID/repeat, query input hash, 실제 타이머 관측, 정렬된 top5 ID/distance/score/source segments, support별 coverage와 RR@1/3/5, 예산2048/4096 packing·소비량·근거 coverage를 저장한다. 집계 전 값을 보존하고, JSON에는 로그 경로·SHA를 남긴다.100×3 로그와300개 latency 관측을 행 ID로 연결한다.
- JSON→원시 로그 재집계로 Hit@1/3/5·MRR@5·문맥 예산 지표 및 지연 분포가 일치해야 한다. source별 분모와 반올림 순서를 명시한다. 선택·trigger는 반올림 전 값으로 계산한다. negative5는 품질 분모에서 계속 분리한다.
- 선언5478행의 `pending/failed`가0, 성공5478, 원문 누락0, source/hash 오류0, 입력 truncation0, 그룹 불일치0을 검사한다. 미완주·재현 실패는 최종 report 갱신을 막는다.
- 전체 실행이 끝난 뒤 정식 선두·선정 후보·runner-up·현행448/32 기준점·Q091 실패 사례를 독립적으로 재인코딩·재적재·검색한다. query별 RR와 top5/동점 집합 차이를 설명하고 §7의 ANN 검사를 통과한다. 일부 선두만 재현됐다는 이유로 실패한 기준점을 무시하지 않는다.
- 현행 정책5478행과 정책별 크기/O/W 곡선으로 §8의 선정 순서를 다시 적용한다. 작은 크기, GitHub 개별/스레드 후보, 네 모델을 모두 포함한다. 과거 `.8032`, 현재 잠정 `.7730`, 새 선정값은 서로의 protocol을 붙여 구분한다. 최종 표현은 **이번 질문셋·선언 조합 범위 내 최선**이며 전역 최적값을 주장하지 않는다.

검증 완료 후 `docs/chunking_embedding_benchmark.md/.json`을 갱신하고 T9에 선정 R/G JSONL 및 manifest SHA, 모델·guard·window/prefix/정규화·검색 설정, 전수 coverage와 재현 기록을 인계한다. 완료 체크는 실행 근거를 확인한 뒤 변경한다.

### 15.6 6144·8192 후속 실험의 등록

현행 정책 재측정과 검색 재현성 해결 후, 이미 상한4096에서 개선된 MiniLM을 더 큰 검색 청크로 확인한다. **R-A/R-B×L=6144/8192×O=0/64/128×MiniLM/E5×G-curated W224 고정 =24행**을 별도 등록한다. E5는 같은 정책의 대조군이다. pooled guard, 내부 W/O=224/0, 전체 corpus·100문항, encode/평균·검색 경로는 필수 재측정과 같다. MiniLM 모델 자체의 입력 한도를 늘리지 않는다.

각 행은 필수 집합의 같은 모델/R 방식/O/G 조건인1024·1536·2048·4096과 비교한다. MRR 개선과 예산2048/4096의 근거 보존·비용을 함께 보고한다. 큰 청크가 예산에 안 들어가면 skip/실패를 그대로 기록한다. 확장 행의 성공24 및 latency7200 관측을 별도 검사한다. 실행하면 합계 **5502행(정식4716/진단786), latency1,650,600개**이며 C0/C1 검증 반복은 별도다. 현행 재측정 후4096 개선이 달라졌다면 그 사실도 기록하고 과거값으로 새 곡선을 이어 붙이지 않는다. 이후 추가 크기는 해당 결과의 경계·비용 근거를 새로 등록한다.

### 15.7 Antigravity Step 1~6

- [ ] **Step 1 — 보존·인벤토리:** 세 실행 이력·최신 report를 보존하고 원본5550행→현행5478행 매핑과 그룹별 분모를 고정한다. 입력/모델 revision·평가 protocol을 저장한다. 의존: 기존 자산. checkpoint: 제외0·중복72.
- [ ] **Step 2 — 실행 오류 보정:** 그룹별 manifest·실제 guard 강제 검사와 `native-common-256`을 구현하고, `run/check` 공통 검색 경로·Q091 재현 실패를 해결한다. 관련 단위/회귀와 작은 실제 Chroma 검색을 통과한다. 의존: Step1. checkpoint: 잘못된256 guard 거부·동일 입력의 재현 검사 통과.
- [ ] **Step 3 — 수직 검증·전체 생성:** C0/C1/C2로 원문→청크→실제 encoder 입력→색인→검색→스팬을 검증하고 모든 현행 variant를 생성한다. 의존: Step2. checkpoint: 전수 누락0·truncation0·SHA/guard 일치·독립 재생성 일치.
- [ ] **Step 4 — 전체 재측정:** common/N/P/Q 합집합5478행을 실행하고 row/query/repeat 로그·실제 latency를 저장한다. 의존: Step3. checkpoint: 정식4692/진단786 성공·1,643,400 관측·전수 재집계 일치.
- [ ] **Step 5 — 추가 상한 측정:** 6144/8192의24행을 같은 protocol로 실행하고 대응 크기 곡선·예산/비용을 평가한다. 의존: Step4. checkpoint: 추가24 성공·7200 관측·정책/출처/G 고정 비교.
- [ ] **Step 6 — 재선정·인계:** 선두/runner-up/기준점의 독립 재현, 전체 coverage·입력/hash 및 로그 검사를 통과한 뒤 report·T9 입력과 Task8-2 완료 체크를 갱신한다. 의존: Step4/5. checkpoint: 현행 성공5502·과거 행/대조군 혼입0·최종 선정과 JSON/MD 일치.

이 절은 후속 구현·실행 플랜이다. 계획 작성·행렬 수 검산·과거 `.8032`의 개별 재현을 전체 재측정 완료로 보고하지 않는다.
