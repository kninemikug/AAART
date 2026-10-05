# Task 8-2 → T9 선정 스택 재현 인계

T8-2의 검색 단계 선정값은 MiniLM (`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`) + RawPedia `R-C-heading-window-t8192-o64` + GitHub `G-C-curated-group-t1024-o64`다. T9는 이 값을 초기 적재·검색 기준으로 사용한다. 실제 답변 품질에 따른 스택 최종 선정은 T11·T15·T17 이후 별도 게이트에서 다룬다.

## 재현 명령

저장소 루트에서 프로젝트 Python 3.14 가상환경을 활성화한 뒤 실행한다. 이 워크트리에는 `venv/`가 없으므로 기존 프로젝트 가상환경의 Python을 지정할 수도 있다.

```bash
python3 scripts/reproduce_t08_2_selected.py \
  --reference docs/T08_2_t9_handoff_reference.json \
  --work-dir data/embedding-benchmark/t08-2/t9-handoff-repro
```

`--work-dir`는 **비어 있는 새 디렉터리**여야 한다. 명령은 Git 관리 원문·질문·스크립트와 고정 모델 revision으로 입력 검증 → 두 규칙 청크 재생성 및 독립 재생성 검사 → 선정 조합 1행의 문서·질의 임베딩 → 새 Chroma 적재 → 100문항×3회 검색 → 로그 재집계를 수행한다. 기존 `data/chunks/` 또는 `data/embedding-benchmark/` 산출물을 입력으로 읽지 않는다. 모델 가중치는 로컬 cache 또는 해당 고정 revision에서 확보해야 한다. 원격 접근 없이 확인하려면 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`을 설정한다.

전체 비교 결과인 `docs/chunking_embedding_benchmark.json`은 Git LFS 파일이다. 새 checkout에서 전체 결과를 읽을 때는 Git LFS를 설치하고 `git lfs pull --include=docs/chunking_embedding_benchmark.json`로 확보한다. 위 선정 조합 재현 명령은 이 대형 JSON을 입력으로 사용하지 않는다.

성공 시 `<work-dir>/reproduction.json`에 `status=passed`가 기록된다. [기대값 계약](T08_2_t9_handoff_reference.json)은 두 청크셋의 건수·파일 SHA, 문서/질의 벡터 SHA, 공통 protocol SHA, 출처별·복합 질문 지표, 300개 질문/반복의 top5 순서 및 근거·문맥 예산 평가 지문을 고정한다. top5 거리는 기존값과 최대 `1e-5` 차이까지 허용한다. 재생성한 실험 ID와 실행 지연은 작업 경로와 실행 환경에 따라 달라질 수 있으므로 합격 비교 대상이 아니다.

2026-10-01 독립 출력 디렉터리에서 실행한 결과, RawPedia **141개** (`8e8f163d2ce8da99fec3dc7e38652ea3d7aecb35997dc20a3d2202c09753c4cd`)와 GitHub **13개** (`7f8943d6bed8a482e7f34602099ade665a99c341a8870a16ed32da2196512571`)의 파일 SHA가 일치했다. 문서·질의 벡터 SHA, 300개 top5 순서, 전체 검색·문맥 예산 지표도 일치했다. Macro MRR@5=`0.8192708333333334`, Macro Hit@5=`0.8708333333333333`이었다. 이 명령은 전체 20,952행 재실행이나 T9 서비스 코드의 완료를 뜻하지 않는다.

## T9 적용 계약

- 선정 청크 두 개의 `chunk_id`·`source_segments`·원문 SHA를 유지해 Chroma에 적재한다. RawPedia/GitHub 모두 물리 청크를 내부 224토큰 윈도우로 나눠 `chunk_window_mean_v2`로 임베딩한다. 원문 전체를 한 번에 MiniLM에 넣거나 첫 윈도우만 쓰면 다른 벡터가 된다.
- 모델 revision·384차원 float32 정규화 벡터·빈 query/document prefix와 Chroma cosine/HNSW(ef_construction=200, ef_search=200, max_neighbors=16, num_threads=1)를 사용한다. 후보 10개를 가져와 distance 6자리·chunk ID 순으로 정렬한 top5를 평가 기준 검색 결과로 사용한다.
- T9 공통 모듈 구현 후 같은 입력을 적재·검색해 이 재현 결과와 청크 ID·순위·원문 위치를 대조한다. 향후 스택 교체 시 새 선정 manifest와 동일한 재현 검사를 먼저 통과시킨다.

기존 벤치마크 JSON의 옛 절대 경로 `check` 명령은 원래 작업 폴더의 Git 제외 결과 파일을 필요로 했다. 현재 `selected`와 `selected_stack`의 `t9_reproduction_command`는 위 재생성 명령으로 교체했다. `baseline` 안의 옛 명령은 이력으로만 남긴다.
