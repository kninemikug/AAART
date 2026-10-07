# Task 9 (A-09) 벡터DB 실행 플랜

작성일: 2026-10-01. 보완일: 2026-10-07. 실행 설계에 저장소 계약·복구 규칙과 검증 기록을 보완했다. 수용기준은 [tasks/todo.md의 Task 9](../tasks/todo.md), 의존 관계와 후속 범위는 [tasks/plan.md](../tasks/plan.md)를 따른다.

## 1. 목적/범위

T08-2가 선정한 두 출처의 청크와 임베딩·검색 절차를 보존하면서, 후속 검색 소비처가 호출할 Chroma 공통 모듈을 설계한다. Task 9의 실행 범위는 전량 적재, 원문 위치를 포함한 top5 검색, 원문 문서 또는 검색 후보 항목 ID별 갱신·검색 제외, 영속 저장소 재개방 및 선정 결과와의 대조 검증이다.

최초 계획 작성 단계의 산출물은 이 문서 하나였고, `src/`, `tests/` 파일 생성·수정, 의존성 설치, 청크 생성, 임베딩 실행 및 저장소 생성은 실행 단계에 남겼다. 구현 검토 후 보완한 저장소 동작과 시험은 아래 계약에 반영한다. **T08-2 산출물 수정 금지**를 적용하며, 기존 규칙·모델·재현 스크립트·기대값 계약을 변경하지 않는다. `tasks/plan.md`와 `tasks/todo.md`도 수정하지 않는다.

인계 입력은 원칙적으로 `docs/T08_2_t9_handoff.md`와 `docs/T08_2_t9_handoff_reference.json`이다. 현재 worktree에는 두 파일과 `scripts/reproduce_t08_2_selected.py`가 없어 다음 파일을 읽기 전용으로 참조했다.

- [T08-2 인계 문서](/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff.md)
- [T08-2 기대값 계약](/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json)

세부 동작은 같은 worktree의 `scripts/benchmark_embeddings.py`, `scripts/verify_embedding_benchmark.py`, `scripts/reproduce_t08_2_selected.py`, `src/artagent/chunking.py`를 대조했다. 실행 착수 전에는 인계 스크립트·청킹 모듈·원문·고정 질문셋이 변경 없이 통합된 저장소 루트를 확보해야 한다. 현재 문서 커밋에서 통합 작업을 수행하지 않는다.

의존 순서는 `T08-2 인계 확보 → 재현 합격 → 공통 적재·검색 경로 → 갱신·제외 → 회귀 검증`이다. T10-2c는 변경분 수집·정제·재청킹과 외부 동기화 상태를 담당하고, T11은 답변 생성, T15는 리랭킹과 k 튜닝을 담당한다.

## 2. 인계 스펙 요약

### 2.1 고정 입력과 임베딩

| 항목 | 실행 계약 |
| --- | --- |
| 모델 | `sentence-transformers/all-MiniLM-L6-v2` |
| 모델 revision | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| 벡터 | 384dim, `float32`, L2 정규화 |
| RawPedia 청크 규칙 | `R-C-heading-window-t8192-o64` |
| RawPedia 건수 | 141개 |
| GitHub 청크 규칙 | `G-C-curated-group-t1024-o64` |
| GitHub 건수 | 13개 |
| 최초 적재 합계 | 154개 |
| 물리 청크 임베딩 정책 | `chunk_window_mean_v2` — 두 출처 공통 |
| 인코더 내부 윈도우 | 기준 토크나이저로 본문 224토큰, 오버랩 0 |
| 헤더 | 기존 제목 조합 절차, 기준 토크나이저로 최대 32토큰 |
| 길이 guard | `pooled-common-256`, 모델 입력은 특수 토큰 포함 최대 256토큰 |
| 기준 토크나이저 | T08-2의 `bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| 문서 prefix | 빈 문자열 `""` |
| 쿼리 prefix | 빈 문자열 `""` |
| 기준 실행 환경 | 프로젝트 루트 Python 3.14 가상환경, CPU, 문서 배치 16, seed 42 |
| 검색 계약 | 후보 10개 → `(round(distance, 6), chunk_id)` 오름차순 → top5 |

물리 청크 규칙의 `o64`는 청크 간 64토큰 오버랩이며, 인코더 내부 윈도우의 오버랩 0과 별개다. 기대값 JSON의 `thread_window_mean_v2`는 재생성 후보 구성 정보다. 선정된 두 청크셋에는 물리 청크 정책인 `chunk_window_mean_v2`를 적용한다.

### 2.2 Chroma 파라미터

| 설정 | 값 | 적용 위치 |
| --- | --- | --- |
| `space` | `cosine` | `configuration.hnsw` |
| `ef_construction` | 200 | `configuration.hnsw` |
| `ef_search` | 200 | `configuration.hnsw` |
| `max_neighbors` | 16 | `configuration.hnsw` |
| `num_threads` | 1 | `configuration.hnsw` |

`num_threads=1`은 Chroma 인덱스의 설정이다. T08-2 인코더의 `torch.set_num_threads(4)`와 구분하여 각각 유지한다. 임의의 성능 튜닝으로 값을 바꾸지 않는다.

### 2.3 검증 지문

| 대상 | 기대 SHA-256 |
| --- | --- |
| 인계 기대값 JSON 파일 | `2c7081ba6a7c37b00735b0be2ef362f5b0c2a86cd41fe97bbb2a3b5ebdc195bc` |
| RawPedia 청크 파일 | `8e8f163d2ce8da99fec3dc7e38652ea3d7aecb35997dc20a3d2202c09753c4cd` |
| GitHub 청크 파일 | `7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571` |
| RawPedia 문서 벡터 파일 | `88f5bf0e1ed5dfee85a4ee77768fd88e8d5088cd73c5a72b2725d9bd754ea018` |
| GitHub 문서 벡터 파일 | `6a851588ab8b2a466e033bb13e4de296d9c5ced58b0ca4cd7eb8d24d27b2a2ef` |
| 질문 벡터 파일 | `abe189f84bb4d7276b920c72569e78d151e4b1ca41babae5e406857f6a699822` |
| 공통 protocol | `3694eb3cb0a8b8e989e6bc828adf1f067b4f988f9be0a04a4d43507850412dc5` |
| 300회 top5 순서 | `a8ac9685ce31717b4d2b7cfe10bb635f5016dec41f4b8be0ca273b4bb0dbf25c` |
| 질문별 근거·문맥 예산 평가 | `107d6485229e45e94f533b77c649275e03abcea73d413348f374808b1201bd9e` |

파일 지문, 벡터 지문, 순위 지문은 서로 다른 검증 대상이다. 문서 벡터 파일은 출처별 원래 청크 순서로 비교하고, Chroma 적재를 위한 전역 ID 정렬은 그 뒤에 수행한다. 주요 지표는 Macro Hit@5 `0.8708333333333333`, Macro MRR@5 `0.8192708333333334`이며, 합격은 이 두 값만이 아니라 기대값 계약 전체를 기준으로 판정한다.

## 3. chunk_id / source_segments 보존 설계

### 3.1 ID와 갱신 단위

Chroma의 `ids`에는 인계 청크의 `chunk_id`를 그대로 사용한다. 순번, 새 UUID, 절대 경로, 적재 시각으로 대체하지 않는다. 기존 ID 형식은 `t08c:v1:{source_type}:{rule_id}:{sha256}`이다.

기존 `compute_chunk_id`는 스키마 버전, 전체 규칙 지문, 출처 유형, 문서 ID, 본문 SHA 및 순서가 보존된 segment 식별 정보에 대해 canonical JSON을 만들고 SHA-256을 계산한다. segment 식별 정보는 `doc_id`, `ref_id`, `segment_sha256`, 원문 문자 범위, 청크 내 문자 범위다. canonical JSON은 키 정렬, UTF-8, `ensure_ascii=False`, 구분자 `(',', ':')`를 사용한다. Task 9는 이 규칙을 변경하지 않고 기존 검증 함수를 재사용한다.

갱신·제외 키는 `(source_type, source_group_id)`이다. RawPedia에서는 원문 `doc_id`, GitHub에서는 정제 후보 `candidate_id`가 `source_group_id`다. GitHub 그룹 청크의 `doc_id`도 후보 ID이므로, 댓글별 ID인 segment의 `doc_id`·`ref_id`와 혼동하지 않는다. 출처 유형을 함께 지정하여 두 출처의 같은 문자열 ID가 섞이지 않게 한다.

본문 또는 출처 구간이 바뀌면 청크 ID도 바뀔 수 있다. 따라서 같은 그룹을 갱신할 때 새 ID를 upsert하고, 그 그룹의 기존 ID 중 새 전체 청크셋에 없는 ID를 제거한다. 같은 ID만 덮어쓰는 방식으로는 오래된 청크가 남을 수 있다.

### 3.2 저장 메타데이터 스키마

| Chroma 필드/키 | 타입 | 규칙 |
| --- | --- | --- |
| `ids` | 문자열 | 원본 `chunk_id` |
| `documents` | 문자열 | 원본 `content` 그대로, 헤더 추가·공백 재정제 없음 |
| `embeddings` | 384차원 벡터 | §4에서 재현한 `float32` 정규화 벡터 |
| `source_type` | 문자열 | `rawpedia` 또는 `github` |
| `doc_id` | 문자열 | 인계 청크의 최상위 `doc_id` |
| `source_group_id` | 문자열 | 원문 문서 ID 또는 검색 후보 항목 ID |
| `section_title` | 문자열 | 원본 전체 제목, 임의 길이 절단 없음 |
| `rule_id`, `rule_fingerprint` | 문자열 | 인계값 그대로 |
| `content_sha256` | 문자열 | 원본 본문 검증 지문 |
| `range_basis` | 문자열 | `source_file` 또는 `serialized_content` 등 인계값 |
| `char_range_json` | JSON 문자열 | 최상위 `char_range` 보존 |
| `source_segments_json` | JSON 문자열 | 전체 `source_segments` 배열, 순서·키·null 보존 |
| `original_metadata_json` | JSON 문자열 | 원본 `metadata` 전체, 추가 필드까지 손실 없이 보존 |
| `retrieval_schema_version` | 정수 | 공통 모듈의 저장 스키마 버전 1 |
| `reference_sha256` | 문자열 | 적용한 인계 기대값 JSON 지문 |
| `excluded` | 불리언 | 최초 적재·정상 재포함 시 `False`, 제외 시 `True` |

중첩 배열·객체는 canonical JSON 문자열로 저장하고 검색 응답에서는 다시 구조화한다. 선택적 최상위 값의 부재를 빈 문자열로 바꾸지 않으며, 원본 메타데이터 내부의 null은 보존한다. `original_metadata_json`의 `source_segments`와 `source_segments_json`이 다르면 적재 또는 반환 검증을 실패시킨다. 이 직렬화는 Chroma 저장용 표현일 뿐 청크 파일과 ID 계산 입력을 바꾸지 않는다.

`candidate_id`, 제목 경로, 제품 범위, 청킹·윈도우 설정 등 나머지 필드는 `original_metadata_json`에 그대로 남긴다. 검색·갱신용으로 승격하는 값은 위 표의 최소 키로 한정하며 `tool`·`lang` 필터를 추가하지 않는다.

### 3.3 원문 위치와 역추적

`source_segments`에서 다음 필드 전체를 유지한다.

- 공통: `doc_id`, `source_path`, `source_file_sha256`, `json_pointer`, `char_start`, `char_end`, `byte_start`, `byte_end`, `content_char_start`, `content_char_end`, `target_url`, `segment_sha256`.
- GitHub 선택 필드: `ref_id`, `body_sha256`, `curated_content_index`, `source_role`, `curated`. 값이 null인 경우도 원본 표현을 유지한다.

문자·바이트 범위는 모두 반개구간 `[start, end)`이다. 문자 범위는 Python 문자열 인덱스, 바이트 범위는 해당 텍스트의 UTF-8 기준이다. GitHub의 바이트 범위는 JSON 파일 자체의 바이트 위치가 아니라 `json_pointer=/body`로 읽은 본문 기준이다. 여러 댓글을 묶은 GitHub 청크는 하나의 대표 URL로 축약하지 않는다.

역추적 순서는 `SearchHit.chunk_id → source_segments → 고정 source_root/source_path → 파일 SHA 검사 → json_pointer 본문 선택 → 문자 구간 추출 → segment SHA·바이트 범위·청크 내 구간 대조 → target_url 반환`이다. RawPedia는 Markdown 파일 전체, GitHub는 스냅샷 파일 SHA와 본문 SHA를 구분해 검증한다. 경로는 저장소 상대 경로로 유지하고, 해석할 때 `source_root` 밖으로 나가는 경로를 거부한다.

검색 결과는 `rank`, `chunk_id`, `source_type`, `doc_id`, `source_group_id`, `section_title`, `content`, `content_sha256`, `source_segments`, 원본 메타데이터 및 거리값을 반환한다. 모든 반환 청크에서 저장 본문과 원문 구간의 대응을 확인할 수 있어야 한다.

## 4. chunk_window_mean_v2 정의

물리 청크 하나당 최종 벡터 하나를 만든다. 다음 절차는 `encode_chunk_list`의 선정 분기와 동일한 결과를 내도록 공통 모듈에 옮겨 담되, 기존 파일은 수정하지 않는다.

1. 기존 헤더 규칙을 적용한다. `page_title` 또는 `title`과 `section_title`이 모두 있고 서로 다르면 `제목\n절 제목`을 사용한다. 그렇지 않으면 존재하는 제목을 사용하고, 없으면 빈 헤더다. 기준 토크나이저의 offset으로 헤더를 최대 32토큰으로 제한한다.
2. 기준 토크나이저의 `add_special_tokens=False`, `return_offsets_mapping=True`로 본문을 토큰화한다. 본문을 224토큰 간격으로 나누고 오버랩은 0으로 둔다. 각 구간의 첫·마지막 offset으로 원래 문자열을 잘라 사용하며, 토큰을 decode하여 본문을 재작성하지 않는다.
3. 각 윈도우에 헤더를 붙인다. 헤더가 있으면 기존 `(header + '\n' + body_slice).strip()` 처리를 그대로 적용한다. 문서 prefix는 `""`이므로 추가 텍스트나 구분자를 넣지 않는다. 정리된 인코더 입력과 저장하는 원본 `content`는 별개다.
4. 모델 토크나이저의 특수 토큰 포함 길이가 256 이하인지 검사한다. 초과하면 헤더는 유지하고 본문만 재분할한다. 초기 간격은 기존 `avail_tokens=max(16, 256-header_tokens-5)`, `sub_step=min(max(50, 224//2), avail_tokens)`를 따른다. 적합할 때까지 간격을 절반씩 줄이며, 최종 구간마다 길이를 다시 확인한다. 자동 truncation을 허용하지 않는다.
5. 각 최종 윈도우의 가중치 `w_i`는 기준 토크나이저가 센 **본문 토큰 수**다. 헤더·prefix·특수 토큰은 가중치에서 제외한다. 재분할한 구간은 재분할 후 본문 토큰 수를 사용한다. 토큰 수가 0인 기존 fallback은 가중치 1을 사용하되, 실제 인계 청크의 빈 본문은 입력 검증에서 거부한다.
6. 고정 모델·revision으로 `normalize_embeddings=True`, NumPy 출력, 문서 배치 16을 사용하여 윈도우별 정규화 벡터 `v_i`를 얻는다. 윈도우·청크 처리 순서도 기존 순서를 유지한다.
7. 가중치를 `float32`로 만들고 `m = sum(w_i * v_i) / sum(w_i)`를 기존 NumPy 연산 순서로 계산한다. `||m||₂ > 1e-6`이면 `m / ||m||₂`로 재정규화한다. 가중치 없는 단순 평균으로 대체하지 않는다.
8. 최종 출력은 `(청크 수, 384)` 형태의 `float32` 배열이다. 유한값, 차원, `abs(||v||₂-1) <= 1e-5`를 검사한다. 0벡터·NaN·무한대는 적재 전에 오류로 처리한다. 출처별 벡터 파일과 윈도우 입력·가중치 trace를 §2의 계약과 대조한다.

224토큰 윈도우를 나누는 기준 토크나이저와 256토큰 입력 길이를 검사하는 모델 토크나이저는 구분한다. 본문 전체를 한 번에 인코딩하거나 첫 윈도우만 사용하는 경로는 선정 벡터를 재현하지 못한다. 쿼리는 §7의 단일 인코딩 경로를 사용한다.

## 5. Chroma 스키마/설정

### 5.1 컬렉션과 영속 경로

두 출처를 **하나의 컬렉션 `art_retrieval_t09_v1`**에 적재한다. T08-2가 두 출처를 합쳐 전역 ID 정렬 후 검색한 방식과 일치시키기 위한 선택이다. 최초 건수는 154개이며 출처별 검증은 `source_type`으로 한다. 출처별 컬렉션 분리와 결과 병합은 하지 않는다.

제안하는 기본 persist 경로는 저장소 루트 기준 `data/vector-store/t09/`이며, 호출자는 `persist_dir: Path`로 명시적으로 바꿀 수 있다. 시작 시 절대 경로로 해석하여 실행 위치에 따른 다른 저장소 생성을 막는다. 재현용 `work-dir`, 원문·후보·청크 입력 경로와 별도로 관리하며, 시험에서는 pytest 임시 경로를 사용한다. 실행 중 생성되는 DB 파일은 커밋 대상에서 제외한다.

`PersistentClient(path=...)`로 저장·재개방하는 동작을 사용한다. 별도의 수동 `persist()` 호출을 가정하지 않는다. [Chroma Python Client 문서](https://docs.trychroma.com/reference/python)의 영속 클라이언트 계약을 따른다.

### 5.2 생성·재개방 계약

새 컬렉션은 `embedding_function=None`과 §2.2의 `configuration.hnsw`를 지정한다. 문서와 질문 임베딩은 공통 모듈에서 명시적으로 계산하여 `embeddings`·`query_embeddings`로 전달한다. Chroma 기본 임베딩 경로에 문서나 쿼리를 맡기지 않는다.

생성 직후 및 재개방 시 실제 적용된 벡터 인덱스 설정을 읽어 cosine과 HNSW 네 값을 검증한다. 인계 코드에서 확인한 `schema.keys['#embedding'].float_list.vector_index.config` 경로의 지원 여부를 실행 환경에서 먼저 확인한다. 단순히 컬렉션 metadata에 설정명을 남기는 것으로 검증을 대신하지 않는다. `configuration`의 HNSW 필드는 [Chroma 컬렉션 설정 문서](https://docs.trychroma.com/docs/collections/configure)를 따른다.

컬렉션 metadata에는 저장 스키마 버전, 모델 ID·revision, dimension·dtype·정규화 여부, 두 청크 규칙, 물리·스레드 풀링 정책, 기준 토크나이저 ID·revision, 윈도우·오버랩·헤더·최대 입력 길이, 빈 prefix, 인계 reference SHA·protocol SHA 및 `store_state`를 기록한다. 기존 컬렉션을 열 때와 적재·갱신·제외·검색 호출에서 이 계약을 대조하고, 불일치하면 오류를 반환한다. 임베딩 세션의 계산 설정도 저장소 계약과 대조한다. `get_or_create_collection`만 호출하여 기존 설정이 교체되었다고 간주하지 않는다.

초기 구현의 저장소에 기록되지 않았던 `ref_tokenizer_id`, `thread_embedding_policy`, `encoder_window_tokens`, `encoder_overlap_tokens`, `max_header_tokens`, `max_seq_length` 여섯 필드는 당시 인계의 고정 기본값으로만 해석한다. 다른 값으로 재개방하면 오류를 반환하며 열기·검색만으로 metadata를 다시 쓰지 않는다. 그 외 기존 필수 계약 필드의 누락은 오류다.

인계 환경 설치 기록의 Chroma는 `1.5.9`다. 기존 프로젝트 가상환경에서 실제 버전을 확인하고 적용 설정을 검증한다. 구형 `hnsw:*` metadata 방식으로의 묵시적 fallback이나 자동 패키지 업그레이드는 계획에 포함하지 않는다.

## 6. 인덱싱 절차

### 6.1 최초 전량 적재

1. **입력 로드:** §8 재현이 합격한 출력의 청크 manifest에서 정확히 두 선정 규칙의 파일을 찾는다. 경로를 추측하지 않고 manifest와 `selected-results.json`이 가리키는 산출물로 결정한다. 141/13개, 청크 파일 SHA, 유일 ID, 본문 SHA, 원문 segment 대응, 규칙·풀링·윈도우 설정을 검증한다.
2. **임베딩 재현:** §4의 공통 인코더로 두 청크셋을 인계 파일 순서대로 임베딩한다. 출처별 벡터 파일 SHA와 윈도우 trace를 재현 출력에 대조한 뒤 384dim·`float32`·정규화 검사에 합격해야 저장소를 변경한다.
3. **계약 확인:** 새 영속 경로에 컬렉션을 만들거나 기존 컬렉션의 계약·상태를 검사한다. 전역 `(chunk_id, vector)` 쌍을 ID 오름차순으로 정렬한다. 한 청크의 벡터를 다른 청크에 연결하지 않도록 쌍 단위로 처리한다.
4. **upsert:** `ids`, `embeddings`, `documents`, 직렬화된 `metadatas`를 같은 순서로 전달한다. 인계의 적재 상한 500과 클라이언트 허용 배치 크기 중 작은 값을 사용한다. 최초 154개는 허용 크기 안이면 하나의 배치로 적재한다.
5. **읽기 검증:** 건수 154 및 출처별 141/13, 저장 ID 집합, 본문, 메타데이터, 구조화한 segment를 전량 대조한다. 검증 후에만 `store_state=ready`로 표시하고 성공 결과를 반환한다.
6. **재개방·검색:** 같은 persist 경로를 새 프로세스에서 열고 건수·계약 및 고정 질문의 top5를 다시 확인한다. 완료 증거는 persist 경로, 입력 지문, 실제 설정, 건수, 검사 결과로 남긴다.

Chroma의 upsert는 ID별 생성·갱신을 수행한다. [Chroma Collection 문서](https://docs.trychroma.com/reference/python/collection)의 해당 메서드를 사용하며, 신규 ID 추가만 수행하는 `add`로 재적재를 처리하지 않는다.

### 6.2 멱등성·그룹 갱신·검색 제외

같은 그룹의 **완전한 새 청크셋**을 받는 `replace_source`와 그 그룹 전체를 제외하는 `exclude_source`를 제공한다. 그룹 일부만 전달하는 요청은 받지 않는다. 빈 청크셋으로 제외를 암묵적으로 표현하지 않고 전용 제외 함수를 사용한다.

그룹 갱신은 다음 순서로 수행한다.

1. 저장소·세션 계약과 진행 중 작업을 검사하고 새 청크셋의 원문·그룹 키·유일 ID를 검증한다. 이 단계의 오류는 기존 저장소를 바꾸지 않는다.
2. 해당 `(source_type, source_group_id)`의 기존 ID와 저장 내용을 읽는다. ID 집합·본문·제목·원본 메타데이터·전체 직렬화 레코드가 같고 `excluded=False`이면 임베딩 계산과 쓰기를 생략한다. ID와 본문이 같아도 제목·원문 SHA·URL·segment 변경은 갱신한다.
3. 변경이 있으면 임베딩을 계산·검증한 뒤 작업 기록을 저장한다. 새 청크셋을 ID순으로 upsert하며 `excluded=False`로 둔다. 같은 ID는 덮어쓰고 새 ID는 추가한다.
4. `기존 ID 집합 - 새 ID 집합`만 삭제한다. 다른 원문 문서·후보 항목의 청크는 건드리지 않는다.
5. 그룹의 ID 집합·본문·segment를 다시 읽어 새 청크셋과 같음을 확인한 뒤 성공을 반환한다. 같은 변경분 재실행은 동일한 최종 상태가 되어야 한다.

검색 제외는 해당 그룹 전체의 `excluded=True`를 저장하며, 모든 조회에서 이 조건을 후보 조회 전에 적용한다. 같은 제외 요청을 반복해도 상태·건수가 변하지 않는다. 아직 저장되지 않은 그룹의 제외는 변경 0건을 반환한다. 재포함은 완전한 청크셋의 `replace_source`로 수행하며 오래된 ID도 정리한다. 물리 건수와 검색 가능한 건수를 구분한다.

공통 모듈 내부에서 해석한 persist 경로·컬렉션 이름을 기준으로 같은 프로세스의 읽기·쓰기 잠금을 공유하고 단일 작성자를 전제로 한다. 호출 시 컬렉션 래퍼의 캐시 대신 영속 metadata에서 최신 계약과 상태를 읽는다. 변경 직전에 `store_state=updating`으로 표시하고 `operation`·그룹 키·`input_fingerprint`를 함께 남긴다. 입력 지문은 ID순 청크의 ID·본문·전체 직렬화 메타데이터를 canonical JSON으로 만든 SHA-256이다. 제외 작업은 대상 그룹 키를 지문화한다. 검증 성공 후 `ready`로 바꾸고 작업 기록을 제거한다. 오류나 재시작으로 `updating`이 남으면 검색을 거부하고 같은 작업 재시도로 정합성을 복구한다. 여러 호출을 묶은 upsert/delete의 원자성을 가정하지 않는다.

초기 적재 실패는 검증한 동일 입력으로 재시도한다. 갱신 실패는 같은 그룹의 완전한 청크셋으로 재시도하고, 제외 실패는 같은 그룹 제외를 재시도한다. 작업 종류·그룹 키·입력 지문이 다르면 미완료 작업을 덮어쓰지 않는다. 데이터 반영은 끝났지만 `ready` 전환이 실패한 경우도, 같은 입력의 저장 내용을 확인하고 `ready`를 복구한 뒤 성공을 반환한다. 입력 지문이 없는 과거 미완료 기록은 안전한 재시도 대상을 증명할 수 없으므로 거부하며, 검증한 입력으로 새 persist 경로에 다시 적재한다. `IndexReport.total_active`에는 제외 청크를 세지 않는다. 외부 원문 동기화 상태나 벡터 반영 완료 표시는 Task 9가 쓰지 않으며, 후속 호출자가 검증된 성공 반환을 받은 뒤 갱신하도록 한다.

## 7. 검색 절차

1. 컬렉션 계약과 `store_state=ready`를 확인한다. 빈 문자열·공백뿐인 쿼리는 오류로 처리한다. 고정 질문셋의 원래 문자열을 변경하지 않고, 번역·재작성·대소문자 치환·추가 prefix를 적용하지 않는다.
2. 모델 토크나이저로 특수 토큰 포함 길이를 검사한다. 256토큰을 초과하면 truncation 없이 오류를 반환한다. `query_prefix=""`와 고정 모델·revision으로 `encode([query], normalize_embeddings=True)`를 수행하고 `(384,)` `float32`·유한값·정규화를 검증한다. 문서용 윈도우 평균은 쿼리에 적용하지 않는다.
3. `where`의 `excluded=False` 조건으로 검색 가능한 ID 수를 구한다. 선택적 `source_key`가 있으면 출처 유형·그룹 ID의 동등 조건을 함께 적용한다. 추가 자유 형식 필터는 제공하지 않는다. 기본 검색은 두 출처 전체를 대상으로 한다.
4. 검색 가능 건수가 0이면 빈 결과를 반환한다. 그 외에는 `n_results=min(10, 검색 가능 건수)`와 `query_embeddings`로 후보를 조회한다. `documents`, `metadatas`, `distances`를 포함한다. 선정 결과 대조에서는 그룹 제한 없이 후보 10개를 사용한다.
5. 후보를 **`(round(float(distance), 6), str(chunk_id))` 오름차순**으로 정렬하고 앞의 최대 5개만 반환한다. 반올림한 거리가 같으면 청크 ID의 문자열 오름차순으로 결정한다. 원시 거리 우선 정렬이나 조회된 5개만 사후 정렬하는 방식으로 바꾸지 않는다.
6. 순위는 1부터 부여한다. 원시 수치 `distance`를 비교용으로 보존하고, 표시용 `distance_text`는 `format(distance, '.6f')`로 항상 소수 6자리를 출력한다. cosine distance는 작을수록 가깝다. 소수 6자리 동점 판정과 §8의 원시 거리 허용 오차는 별개다.
7. 직렬화된 원본 메타데이터·`source_segments`를 복원하고 §3의 필드를 반환한다. 저장 본문 SHA와 segment 배열의 일치를 검사한다. 제외 그룹이 top5에 들어오지 않으며, 검색 가능한 청크가 5개 미만이면 실제 건수만 반환한다.

동점 규칙은 **조회된 후보 집합 내부**의 순서를 결정한다. 전 데이터에 대해 근사 검색을 완전 검색으로 바꾸거나 경계 동점을 전량 조회하는 변경은 하지 않는다. 인덱스·삽입 순서·실행 환경을 고정하고 기준 300회 검색으로 후보 경계 변동을 확인한다.

## 8. 재현/검증 명령

### 8.1 기존 선정 스택 재현

인계 스크립트와 기대값 파일이 있는 저장소 루트에서 프로젝트 Python 3.14 가상환경을 활성화하고 **다음 명령 그대로** 실행한다. `<empty-dir>`는 실제로 비어 있는 새 디렉토리의 경로로 치환한다.

```bash
python3 scripts/reproduce_t08_2_selected.py --reference docs/T08_2_t9_handoff_reference.json --work-dir <empty-dir>
```

새 빈 디렉토리를 매번 확보하는 실행 예시는 다음과 같다.

```bash
T09_REPRO_DIR=$(mktemp -d /private/tmp/t09-repro.XXXXXX)
python3 scripts/reproduce_t08_2_selected.py --reference docs/T08_2_t9_handoff_reference.json --work-dir "$T09_REPRO_DIR"
```

현재 worktree에 선행 산출물이 없는 상태에서 확인한다면, 앞서 명시한 T08-2 worktree를 실행 루트로 사용하고 출력만 새 임시 디렉토리에 남긴다. 그 worktree의 원문·스크립트·기대값 파일은 수정하지 않는다. 기존 출력 디렉토리를 비우거나 기존 `data/chunks/` 결과를 재현 입력으로 사용하는 방법은 사용하지 않는다.

실행은 고정 원문·질문·스크립트에서 입력 검증, 청크 생성·독립 재생성 검사, 선정 조합 1행의 임베딩·새 Chroma 적재, 100문항 × 3회 검색, 로그 재집계를 수행한다. 전체 비교 행렬을 다시 실행하지 않는다. 성공 증거는 `<empty-dir>/reproduction.json`의 `status=passed`와 종료 코드 0이다.

모델과 토크나이저의 고정 revision이 로컬 cache에 모두 있을 때는 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`로 동일 명령을 실행할 수 있다. cache가 없으면 실행 단계에서 필요한 고정 revision을 확보한다. 의존성은 실제 소비 시점에 기존 가상환경에서 확인하고 설치 이력을 남기며, 이 계획을 위해 패키지를 설치하거나 `requirements.txt`를 만들지 않는다.

### 8.2 공통 모듈 검증

구현 후, 재현 출력과 고정 원문을 pytest fixture 입력으로 연결하여 다음 명령으로 실행한다. 환경 변수는 시험 입력 경로를 지정하는 제안 계약이며 실행 단계에서 적용한다.

```bash
T09_REPRO_DIR="$T09_REPRO_DIR" T09_SOURCE_ROOT="$PWD" PYTHONPATH=src python3 -m pytest tests/test_retrieval.py tests/test_retrieval_state.py -q
```

`T09_SOURCE_ROOT`는 재현에 사용한 고정 원문 저장소 루트다. fallback 루트에서 재현했다면 그 절대 경로를 지정하고, 시험 명령은 Task 9 구현 저장소 루트에서 실행한다. 재현 결과나 고정 revision이 없으면 수용 검증은 명시적으로 오류를 내며, 실제 청크·모델 roundtrip을 mock 또는 skip으로 대체하지 않는다.

검증은 새 persist 경로에 154개를 적재하고, 공통 쿼리 인코더로 동일 100문항을 각각 3회 검색하여 다음 항목을 대조한다.

- 141/13개 청크 파일·문서 벡터·질문 벡터 및 공통 protocol의 기대 지문.
- 재현 로그의 질문 ID·반복별 top5 청크 ID와 순위 전체, 300개 로그의 순위 지문.
- 원문 위치는 같은 ID의 재현 로그 `source_segments`, 원본 청크, 고정 원문과 전수 대조.
- 원시 top5 거리의 기대값과 최대 절대 차이 `1e-5` 이하. 표시 문자열 6자리 일치만으로 수치 검증을 대신하지 않음.
- 기존 집계기를 읽기 전용으로 재사용하여 출처별·복합·Macro·Micro·부정 질문 및 2048/4096토큰 문맥 예산 평가를 기대값 계약과 대조.
- 같은 입력 재적재·프로세스 재개방 후에도 ID·순위·원문 위치·설정이 유지됨.

실험 ID, 작업 절대 경로, 실행 지연은 환경에 따라 달라질 수 있어 합격의 동일성 비교 대상에서 제외한다. 질문셋은 RawPedia 긍정 80개, GitHub 긍정 15개, 부정 5개로 총 100개이며 대략적인 질문 수 계획을 실제 검증 건수로 사용하지 않는다.

### 8.3 저장소 보완 검증 기록 (2026-10-06)

기존 구현에서 계약·갱신·상태 시험 42개 중 39개 실패로 문제를 재현한 뒤 저장소를 보완했다. 최종 실행은 아래 명령으로 완료했다. 모델·토크나이저는 기존 로컬 cache와 프로젝트 가상환경을 사용하고, 기준선은 이미 `status=passed`인 `/private/tmp/t09-repro.PR4bPW`의 재현 출력과 읽기 전용 원문이다.

```bash
PYTHONDONTWRITEBYTECODE=1 \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
T09_REPRO_DIR=/private/tmp/t09-repro.PR4bPW \
T09_SOURCE_ROOT=/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding \
PYTHONPATH=src \
/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python -m pytest -q -p no:cacheprovider
```

결과는 **146 passed, 1 warning in 97.13s**다. 검색 관련 시험은 실제 인계 입력 시험 15개와 상태·계약 시험 66개로 총 81개이며, 나머지 기존 시험 65개도 통과했다. 경고는 설치된 Chroma의 `asyncio.iscoroutinefunction` 사용에 대한 기존 폐기 예정 알림이다.

- 실제 141/13개 청크와 고정 revision의 문서·쿼리 벡터 기대 지문을 대조했다.
- 100문항 × 3회 top5 순위 지문 `a8ac9685ce31717b4d2b7cfe10bb635f5016dec41f4b8be0ca273b4bb0dbf25c`가 일치하고 원시 거리 최대 차이는 `1e-5` 이하였다.
- 두 출처 모두 본문 변경·새 ID 생성·구 ID 삭제·다른 그룹의 본문·메타데이터·벡터 보존·동일 변경분 재실행을 검증했다.
- 같은 ID의 제목·출처 SHA·URL 변경, 제외 후 실제 활성 건수, segment 두 사본 불일치 거부를 검증했다.
- 부분 upsert/delete/update 및 `ready` 직전 실패에서 같은 입력 재시도로 복구하고 다른 작업을 거부했다.
- 미리 열린 핸들의 최신 상태 확인·공유 잠금과 새 프로세스의 영속 상태 조회·검색 거부·제외 재시도 복구를 검증했다.
- 기존 저장소 계약 호환, 필수 필드 누락 거부, 잘못된 차원·dtype·NaN·0벡터·노름 허용치 초과 거부를 검증했다.

T08-2 산출물과 풀링 계산은 변경하지 않았고 의존성을 추가하지 않았다. 단일 작성자와 동일 프로세스의 공유 잠금이라는 §6·§11의 운영 범위는 유지한다.

### 8.4 main 통합 재현 (2026-10-07)

T08-2의 PR #8이 머지된 main `97dd5bf36`과 T09를 별도 임시 checkout에서 통합했다. main의 보고서 압축 커밋 `82bdf97ed`는 인계 JSON의 `source_report`를 `.json.gz` 경로로 바꾸고 `source_report_sha256`을 추가했다. 그 외 선정 모델·청크·벡터·평가 기대값·protocol은 같음을 JSON 항목별로 확인했다. 이에 따라 T09의 기본 인계 지문과 고정 기대값을 §2의 현재 SHA로 맞추고 기본 스펙과 로드한 스펙의 지문 일치 검사도 추가했다.

인계 protocol은 Python 실행 파일의 절대 경로도 포함한다. 재현에는 기존 가상환경의 `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3`를 사용했다. 매번 새 빈 디렉토리를 준비하며, 이번 합격 출력은 `/private/tmp/t09-repro.kVTr0x`다. 통합 checkout 루트는 `/private/tmp/t09-main-merge-check.c7ltm3gt`다.

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/reproduce_t08_2_selected.py --reference docs/T08_2_t9_handoff_reference.json --work-dir /private/tmp/t09-repro.kVTr0x

PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
T09_REPRO_DIR=/private/tmp/t09-repro.kVTr0x \
T09_REFERENCE_PATH=/private/tmp/t09-main-merge-check.c7ltm3gt/docs/T08_2_t9_handoff_reference.json \
T09_SOURCE_ROOT=/private/tmp/t09-main-merge-check.c7ltm3gt \
PYTHONPATH=src \
/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -q -p no:cacheprovider
```

`reproduction.json`은 `status=passed`이며 protocol SHA는 §2의 기존 값과 같다. 300회 순위 지문도 기존 값과 일치하고 최대 top5 거리 차이는 `3.5762786865234375e-07`이다. 실제 청크·벡터 SHA와 전체 평가 지표 대조도 재현 스크립트의 고정 검사를 통과했다. T08-2 원본 스크립트·인계 파일은 수정하지 않았다.

통합 checkout의 전체 시험 결과는 **235 passed, 1 warning in 98.11s**다. T09 검색 시험 81개와 main의 청킹·벤치마크·라우터 및 기존 시험을 모두 포함하며, 경고는 기존 Chroma의 폐기 예정 알림이다.

## 9. 산출물 파일 설계

### 9.1 모듈과 함수 계약

아래 경로는 구현 단계의 산출물 설계다. 기존 T08-2의 `Chunk`와 출처 검증 계약을 보존하고, 공통 모듈은 실행 스크립트의 동적 import나 절대 경로 삽입에 의존하지 않게 한다.

| 예정 파일 | 책임 및 함수 시그니처 |
| --- | --- |
| `src/artagent/retrieval/types.py` | `RetrievalSpec`, `SourceKey`, `SearchHit`, `IndexReport` 정의. `load_spec(reference_path: Path) -> RetrievalSpec`. 모델·설정 계약과 반환 필드를 한곳에서 정의 |
| `src/artagent/retrieval/provenance.py` | `load_selected_chunks(manifest_path: Path, spec: RetrievalSpec, source_root: Path) -> list[Chunk]`; `validate_provenance(chunk: Chunk, source_root: Path) -> None`; `serialize_metadata(chunk: Chunk, spec: RetrievalSpec, *, excluded: bool = False) -> dict[str, Union[str, int, float, bool]]`; `deserialize_chunk(chunk_id: str, content: str, metadata: Mapping[str, object]) -> Chunk` |
| `src/artagent/retrieval/embedding.py` | `load_encoder(spec: RetrievalSpec) -> EncoderSession`; `embed_chunks(chunks: Sequence[Chunk], session: EncoderSession, *, batch_size: int = 16) -> Float32Array`; `embed_query(query: str, session: EncoderSession) -> Float32Array`. 윈도우 trace를 검증할 수 있는 내부 경로 제공 |
| `src/artagent/retrieval/store.py` | `open_store(persist_dir: Path, spec: RetrievalSpec) -> RetrievalStore`; `RetrievalStore.index_all(chunks: Sequence[Chunk], session: EncoderSession, *, source_root: Path) -> IndexReport`; `RetrievalStore.replace_source(key: SourceKey, chunks: Sequence[Chunk], session: EncoderSession, *, source_root: Path) -> IndexReport`; `RetrievalStore.exclude_source(key: SourceKey) -> IndexReport`; `RetrievalStore.search(query: str, session: EncoderSession, *, source_key: Optional[SourceKey] = None) -> list[SearchHit]` |
| `src/artagent/retrieval/__init__.py` | 위 계약 타입·입력 로드·저장소 개방 함수의 공개 진입점. 동일 함수와 타입을 내보내며 별도 처리 경로를 추가하지 않음 |
| `tests/test_retrieval.py` | 아래 단위·통합·회귀 시험을 구성. 실제 데이터는 재현 출력과 고정 원문을 읽고 저장소는 임시 경로를 사용 |
| `tests/test_retrieval_state.py` | 실제 임시 Chroma와 유효한 원문 snapshot으로 계약 불일치·동일 ID의 메타데이터 변경·부분 실패·입력 지문·잠금·상태 복구를 시험. 계산 경계에는 통제된 384차원 벡터 사용 |

`Float32Array`는 NumPy `float32` 배열을 뜻하며, 문서 출력은 `(N, 384)`, 쿼리 출력은 `(384,)`다. `EncoderSession`은 고정 모델과 두 토크나이저 및 실행 설정을 보유한다. `SourceKey`는 `source_type`·`source_group_id`, `SearchHit`는 §3의 반환 필드와 `rank`·원시 `distance`·6자리 `distance_text`를 보유한다. `IndexReport`는 적용 그룹, 생성·갱신·변경 없음·제외·오래된 청크 삭제 건수와 검증 성공 상태를 반환한다.

검색은 Task 9의 top5·fetch10을 함수 내부 계약으로 고정한다. k 변경 인자, 임의의 모델 선택 인자, `tool`·`lang` 필터, 새 설정 로더를 추가하지 않는다. `index_all`은 최초 인계셋 154개 적재·동일 입력 재시도용이고, 이후 그룹 변경은 `replace_source`로 구분한다. 부분 청크셋을 받아 전량 동기화로 처리하지 않는다.

### 9.2 tests/test_retrieval.py 테스트 케이스

| 케이스 | 검증 내용 |
| --- | --- |
| 인계 입력 계약 | 모델 revision·규칙·풀링·prefix·차원·윈도우 설정과 reference SHA 검사, 다른 계약 거부 |
| 출처 정보 직렬화 | 다중 segment, null·선택 필드, 한글·UTF-8, 문자/바이트 범위와 원본 metadata 전체의 roundtrip |
| 출처 불일치 거부 | 원문 파일 SHA·본문/구간 SHA·경로·ID·중복 ID 불일치에서 저장 전에 오류 |
| 윈도우 평균 | 224토큰 경계, 짧은 마지막 윈도우의 토큰 가중치, 헤더 32토큰 제한, guard 재분할, 빈 prefix·무절단 확인 |
| 실제 임베딩 재현 | 두 출처 문서·100개 질문의 고정 revision 벡터 파일 및 윈도우 입력·가중치 trace 대조 |
| 실제 적재·검색 roundtrip | 실제 141/13개 전량, 본문·ID·segment 복원, 새 컬렉션의 5개 인덱스 설정 및 top5 반환 |
| 영속 저장소 재개방 | 새 프로세스에서 계약·154개 건수·검색 순위·원문 위치 유지 |
| 선정 검색 회귀 | 100문항 × 3회 ID·순위·원문 위치·거리 허용 오차·전체 집계 지표 비교 |
| 동점·6자리 표시 | 원시 거리가 달라도 6자리 반올림 결과가 같으면 ID순, 작은 거리 우선, 끝자리 0을 포함한 6자리 표시 |
| 후보 수·빈 저장소 | 후보 10개에서 top5 선택, 검색 가능 0개·1~4개·5~9개 처리 |
| 멱등 재적재 | 같은 154개 및 같은 후보 ID 재적재 후 중복 없음, 불필요한 쓰기 생략·순위 유지 |
| 그룹 갱신 | 본문 변경으로 ID가 바뀌는 경우와 청크 수 감소를 검증, 오래된 ID 삭제·다른 그룹 유지·변경분 재실행 동일성 |
| 검색 제외·재포함 | 두 출처 각각 그룹 전체 제외, 조회 전 조건 적용, 반복 제외·미존재 그룹·재포함 처리 |
| 저장소 계약 오류 | 모델·차원·실제 cosine/HNSW 설정 불일치 및 잘못된 dtype·NaN·0벡터 거부 |
| 부분 실패·재시도 | 임베딩 단계 실패는 무변경, upsert/delete 중 오류 이후 검색 거부, 재개방 후 같은 작업 재시도로 ready 복구 |
| 입력 경계 | 빈 쿼리·256토큰 초과 쿼리 거부, 다른 그룹 청크를 섞은 갱신·빈 갱신 요청 거부 |

좁은 단위 검증에서는 통제된 벡터로 동점·가중치·실패를 유발할 수 있지만, 실제 전량 적재·검색 및 선정 결과 대조는 실제 모델·데이터·Chroma로 실행한다.

### 9.3 실행 순서와 검증 지점

| 단계 | 의존 | 예상 수정 파일 | 완료·검증 지점 |
| --- | --- | --- | --- |
| P1. 인계 기준선 확보 | T08-2 산출물 통합 | 기존 파일 변경 없음 | §8.1 합격, 빈 출력 경로·SHA·환경 기록 |
| P2. 출처 계약과 임베딩 재현 | P1 | `types.py`, `provenance.py`, `embedding.py`, 시험 파일 | §3 직렬화와 §4 실제 벡터 재현 합격 |
| P3. 전량 적재·top5·재개방 | P2 | `store.py`, `__init__.py`, 시험 파일 | 154개 전량 roundtrip, 실제 설정·300회 검색 대조 |
| P4. 갱신·제외·최종 회귀 | P3 | `store.py`, 시험 파일 | 멱등성·오래된 청크 삭제·제외·부분 실패 복구 및 수용 검증 명령 합격 |

각 단계는 앞 단계의 증거가 확보된 뒤 진행한다. 실행 스크립트의 기존 분기를 공통 모듈에 옮기는 범위는 적재·임베딩·검색 계약으로 한정하고, 후보 생성·선정 보고서·평가 규칙을 다시 설계하지 않는다.

## 10. 체크리스트 — Task 9 수용기준 매핑

아래 체크박스는 실행 단계에서 확인할 항목이며 이번 문서 작성으로 완료 처리하지 않는다.

| tasks/todo.md Task 9 기준 | 계획 위치 | 완료 증거 |
| --- | --- | --- |
| T8-2 실행 경로를 공통 모듈로 정리하고 선정 두 청크셋 전량 Chroma 적재 | §2, §4~6, §9 P2/P3 | 141/13개 및 총 154개, 실제 설정, 문서·벡터·원문 구간 대조 |
| 검색 결과마다 순위·청크 ID·원문 위치 확인 | §3, §7, §9 P3 | 각 SearchHit의 1기준 순위·원본 ID·전체 segment·URL 및 roundtrip |
| 선정 모델·적재 설정으로 재현 가능 | §2, §5, §8 | `reproduction.json` passed, 기대 지문·100문항 × 3회 top5·지표 대조 |
| 같은 후보 ID 재적재 중복 없음, 갱신·검색 제외 반영 | §3.1, §6.2, §9 P4 | 반복 입력 무변경, 새 청크 반영·구 ID 정리, 제외 그룹 미반환·재포함 |
| pytest 실제 두 출처 roundtrip·재적재·갱신·제외 및 T8-2 결과 일치 | §8.2, §9.2 | `tests/test_retrieval.py` 수용 검증 합격과 실제 입력 기반 로그 |

- [ ] 선행 산출물을 변경 없이 확보하고 고정 revision·가상환경을 확인한다.
- [ ] 빈 `work-dir`에서 기존 재현 명령을 실행하여 기대값 계약 전체에 합격한다.
- [ ] 공통 임베딩·출처 직렬화·영속 Chroma 적재·top5 경로를 검증한다.
- [ ] 그룹 갱신·반복 반영·검색 제외·재포함·중단 복구를 검증한다.
- [ ] 수용 검증을 실행하고 persist 경로·입력 지문·실제 설정·검색 비교 결과를 남긴다.
- [ ] 후속 소비처에 함수 계약과 성공 반환 후 상태 갱신 규칙을 인계한다.

## 11. 리스크/제외사항

| 주의점 | 영향 | 대응 계획 |
| --- | --- | --- |
| 현재 worktree의 선행 산출물 부재 | 즉시 실행할 수 있는 루트가 아님 | P1에서 변경 없는 통합 상태를 확보하고 fallback 참조와 실행 루트를 구분 |
| 토크나이저·헤더·가중치 처리 차이 | 같은 모델이어도 벡터·순위 변경 | 두 토크나이저 revision, offset 절단, 길이 guard, 윈도우 trace와 벡터 SHA 전수 대조 |
| 패키지·CPU 연산 환경 차이 | 벡터 파일 지문 또는 근접 거리 변동 | 인계 설치 기록·실제 버전·CPU·배치·스레드를 기록하고 계약의 오차 범위를 임의 확대하지 않음 |
| Chroma 설정 API 차이·기존 저장소 재사용 | 설정이 기본값으로 남거나 다른 모델 벡터 혼입 | 실제 적용 설정과 계약 검사, 불일치 오류, 새로운 검증 저장소에서 재현 |
| 중첩 메타데이터 축약·JSON 본문 위치 오해 | 댓글·원문 근거 추적 손실 | 배열·null·원문 SHA·본문 SHA·offset 전량 보존과 구조화 roundtrip |
| 청크 ID와 갱신 키 혼동 | 수정 전 청크 잔류 또는 다른 후보의 삭제 | 출처 유형·그룹 ID로 갱신하고 구 ID와 새 전체 ID 집합의 차이만 정리 |
| 다중 저장 호출 중 중단 | 부분 반영된 검색 결과 노출 | 단일 작성자·잠금·updating 상태 검사·검색 거부·동일 작업 재시도, 호출 간 원자성 가정 배제 |
| 근사 검색 후보 경계의 동점 | 후보 집합이 달라지면 순서 규칙만으로 회복 불가 | 삽입 순서·HNSW 고정, fetch10 내부 타이브레이크와 300회 기준 대조 |
| 긴 물리 청크의 문맥 예산 소비 | 검색 적중이 후속 답변 품질을 보장하지 않음 | 기존 2048/4096 예산 지표를 보존하고 후속 품질 판단과 구분 |
| 검색 후보 제외 이후의 데이터 변화 | 초기 154개 기준과 변경 후 저장소를 혼동 | 선정 회귀는 최초 기준선에서 수행하고 갱신·제외 시험은 별도 임시 저장소에서 수행 |

모델·청킹 재선정, 전체 비교 행렬 재실행, 데이터 재수집·정제·재청킹, GitHub 증분 동기화 상태의 관리, 답변 생성, 번역·질문 재작성, 리랭킹·k 튜닝, 프로필 생성·렌더링, `tool`·`lang` 필터, 다중 작성자·분산 Chroma 운영은 Task 9 범위에서 제외한다. RawPedia의 설명을 ART의 동작과 동일하다고 단정하지 않으며 원본 제품 범위 메타데이터를 유지한다.
