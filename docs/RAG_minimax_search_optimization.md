# MiniMax 검색어로 평가한 임베딩·리랭킹 최적화

MiniMax M3.1 Flash가 만든 검색어로 비교한 83개 검색 설정 중 **MiniLM + BM25, 후보 20, 최종 5, `min_score=0.5`, `rerank_weight=0.75`**가 검색 기준을 충족한 최고 조합이었다. 기존 기준선 대비 유일한 파라미터 차이는 BM25 결합 가중치 `0.25 → 0.75`다. 두 설정은 같은 158청크와 MiniMax 재작성 결과를 사용했다. [최적화 계획](RAG_stack_selection_plan.md#minimax-검색어-기준-최적화) · [83개 검색 설정의 문항별 기록](../data/eval/stack-selection/minimax_search_grid_v1/grid.jsonl.gz)

## 검색 최적화 100문항

MiniMax를 NVIDIA 무료 API로 실제 호출했다. 초기 동시 배치의 100문항 중 15개는 성공했고 85개는 HTTP 429를 반환했다. 제한된 85개만 최소 5초 간격으로 다시 호출해 429를 모두 해소했다. 전체 100문항 중 98개가 검색에 도달했고, 그중 66개 검색어에 한글이 포함됐다. Q086은 원질문에 없던 제품명 `ART`를 추가했고 Q094는 필수 식별값 `1`을 빠뜨렸다. 두 문항은 공통 재작성 실패로 100문항 집계에 남겼다. [첫 요청](../data/eval/stack-selection/minimax_rewrites_v1) · [순차 요청](../data/eval/stack-selection/minimax_rewrites_retry_v1)

MiniLM·다국어 E5-small·BGE-small을 동일한 청크와 256토큰 가드에서 비교했다. 임베딩별 순수 벡터 검색 1개, BM25 설정 24개에 더해, 앞선 MiniLM 후보에 다국어 MS MARCO 교차 인코더 설정 8개를 비교했다. 후보 수, 리랭커 가중치 및 임계값은 계획대로 조합했다. 출처별 재현율과 반증 원문을 먼저 보존하고, 그 기준을 만족한 후보를 전체 재현율·정밀도·첫 골드 MRR 순으로 정렬했다.

| 모델 · 설정 | 원문 ID 재현율 | 원문 ID 정밀도 | RawPedia / GitHub 재현율 | 반증 원문 | 첫 골드 MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| **MiniLM · BM25 가중치 0.75** | **94.00%** | **27.75%** | **95.00% / 90.00%** | 5/5 | **0.8833** |
| MiniLM · 기존 BM25 가중치 0.25 | 92.00% | 26.75% | 92.50% / 90.00% | 5/5 | 0.8783 |
| MiniLM · 벡터 순위 | 91.00% | 25.73% | 91.25% / 90.00% | 5/5 | 0.8583 |
| MiniLM · 다국어 교차 인코더 최상 설정 | 93.00% | 27.15% | 93.75% / 90.00% | 5/5 | 0.8737 |
| E5-small · 최상 설정 | 93.00% | 27.47% | 93.75% / 90.00% | 5/5 | 0.8345 |
| BGE-small · 최상 설정 | 93.00% | 27.57% | 93.75% / 90.00% | 5/5 | 0.8737 |

새 가중치로 Q070·Q078의 골드 원문이 추가됐고, 기존에 확보한 원문 ID 재현율이 떨어진 문항은 0개였다. 재작성을 통과한 98문항 기준 재현율은 93.88%에서 95.92%로 올랐다. 전체 100문항에 대한 지표는 원문 ID 기반이며 답변 정확도와 별도다. 73문항의 선택 청크나 순서가 바뀌었다.

## 실제 검색 그래프 재현

기준선과 후보를 `INTAKE → ROUTE → DISPATCH → SEARCH`에서 다시 실행했다. 기대 출처는 두 설정 모두 100/100이었다. 검색에 도달한 98문항에서 오프라인 격자와 실제 그래프의 선택 청크 ID·순서·원문 지표가 문항별로 일치했다. 같은 장비에서 보존 검색어를 사용하는 첫 검색 노드의 지연 중앙값은 16.44ms에서 16.12ms였다. API를 통한 재작성과 답변 시간은 이 측정에서 제외했다. [실제 그래프 문항별 기록](../data/eval/stack-selection/minimax_search_verify_v1)

## MiniMax 답변 회귀 8문항

F01–F08은 이 격자의 설정 선정에서 제외했다. 이전 평가에 사용한 표본으로, 당시 NVIDIA MiniMax가 생성한 재작성·재검색 질의를 양쪽 그래프에 그대로 사용했다. 답변은 두 설정 모두 같은 MiniMax 모델로 새로 생성했다. 각 설정에서 11회 답변을 호출했고, 전부 사용량을 반환했으며 HTTP 429는 없었다. [8개 질문과 원문](../data/eval/stack-selection/final_questions_v1.json) · [기존 재작성 실호출](../data/eval/stack-selection/graph_live_rewrite_v2) · [16개 답변 실행 기록](../data/eval/stack-selection/minimax_search_final_v1)

| 지표 | 기존 BM25 0.25 | 후보 BM25 0.75 |
| --- | ---: | ---: |
| 기대 경로 · 검색 성공 | 8/8 · 8/8 | 8/8 · 8/8 |
| 첫 검색에서 요구 원문 ID 모두 확보 | 7/8 | 7/8 |
| 유효 답변 | 7/8 | 6/8 |
| 기대 상태 일치 | 6/8 | 6/8 |
| 인용 검증 실패 | 1건 | 2건 |
| 유효 답변 그래프 시간 중앙값 | 35.84초 | 24.53초 |
| 답변 입력 / 출력 토큰 | 117,483 / 2,861 | 97,920 / 2,559 |
| 정규 API 환산액 · 8문항 답변 | $0.01934 | $0.01622 |

- F01은 두 설정에서 `Crop` 원문을 확보하지 못했다. 기존 설정은 근거 부족 답변을 반환했다. 후보는 본문에 인용 표식 5개를 넣고 `citation_ids`를 빈 배열로 반환해 차단됐다.
- F08은 양쪽에 같은 근거 문맥이 들어갔다. 두 답변은 Resize의 PPI만으로 EXIF 태그를 바꿀 수 없다고 설명했지만, 본문에 없는 `C1S1`을 인용 목록에 넣어 차단됐다.
- F02–F07은 양쪽 모두 기대 상태와 핵심 답변 행동을 충족했다. F04는 RawTherapee의 업스케일 한도와 ART에서 확인 가능한 사실을 구분했고, F06은 실제 기본 라우팅을 통해 Finder 동작·경로의 `%20`·후속 확인을 제시했다.

답변 생성·재검색 답변 토큰에 MiniMax의 캐시 미적용 정규 단가인 입력 100만 토큰당 $0.15, 출력 100만 토큰당 $0.60을 적용했다. 100문항의 공통 재작성 100회는 입력 71,086·출력 3,480토큰으로 $0.01275에 해당한다. 실제 호출은 NVIDIA 무료 API로 했으며, 답변 그래프 시간 중앙값은 각 설정의 유효 답변을 집계한 관측값이다. [MiniMax 정규 단가](https://www.minimax.io/blog/minimax-m31f)

**적용 판정.** BM25 가중치 0.75를 MiniMax 경로의 검색 후보로 기록한다. 운영 기본값 전환과 정식 T23 인수는 보류한다. 검색 100문항의 개선을 실제 그래프에서 재현했지만, 답변 회귀 검증에서 기대 상태가 6/8에 그쳤고 유효 답변이 한 건 줄었다. 100문항에는 새 답변을 생성하지 않았으므로 답변 faithfulness는 미측정이다.

## 모델을 고정한 검색어·인용 개선

MiniMax M3.1 Flash, MiniLM + BM25 `20/5/0.5/0.75`, 158청크 색인을 고정했다. RawPedia 검색어에서 확인된 한글 UI 용어를 영어 문서의 표기에 맞췄다. 재작성 실패 때는 원질문을 사용하고 오류 분류와 기존 출처·이슈 범위를 보존한다. 재검색 질의가 최초 검색과 같으면 원질문으로 변형을 시도하고, 질의가 여전히 같으면 첫 근거 부족 답변을 반환한다. 인용 목록은 본문 표식 순서에 따라 조립하고 검색 문맥에 없는 ID와 잘못된 표식 형식은 계속 거부한다. 평가 옵션 `--improved`로 이 경로를 실행한다.

| 지표 · 동일한 MiniMax 재작성 100건 | 변경 전 | 변경 후 |
| --- | ---: | ---: |
| 검색 도달 | 98/100 | **100/100** |
| 원문 ID 재현율 | 94.00% | **98.00%** |
| 원문 ID 정밀도 | 27.75% | **29.22%** |
| RawPedia / GitHub 재현율 | 95.00% / 90.00% | **97.50% / 100.00%** |
| 반증 원문 | 5/5 | 5/5 |
| 첫 골드 MRR | 0.8833 | **0.9233** |

`Dark-Frame`과 `Sidecar Processing Profiles` 표기로 Q046·Q071을, 원질문 복구로 Q086·Q094를 회복했다. 기준선에서 확보한 원문 재현율이 낮아진 문항은 없었다. Q038·Q077은 여전히 목표 원문을 놓쳤다. [100문항 실제 검색 그래프](../data/eval/stack-selection/minimax_quality_search_v1)

F01–F08에서는 요구 원문을 7/8에서 8/8로 확보했다. F01의 `Crop` 문서가 1위에 오르고 사용자 정의 비율을 유지하는 절차가 답변 프롬프트에 포함됐다. NVIDIA 답변 실호출의 첫 시도는 HTTP 529 6건·429 2건, 간격을 둔 재시도는 HTTP 529 8건이었다. 이후 F01 단독 호출도 HTTP 529를 반환했다. 새로 생성한 답변 성능은 미측정이다. [첫 시도](../data/eval/stack-selection/minimax_quality_final_initial_v1) · [순차 재시도](../data/eval/stack-selection/minimax_quality_final_v1) · [F01 단독 호출](../data/eval/stack-selection/minimax_quality_final_followup_v1)

색인과 시스템·사용자 프롬프트가 정확히 같은 이전 MiniMax 응답을 재생한 F02–F08은 기대 상태 7/7에 일치했다. F08의 기존 원본에서 본문에 쓰인 표식 `C1S2`, `C1S3`을 조립하니 실제 인용 검증을 통과해 `UNSUPPORTED` 응답을 반환했다. F01은 문맥이 개선되어 같은 프롬프트의 보존 답변이 없으므로 상태 집계에서 제외했다. 운영 기본값 전환 판정에는 새 MiniMax 답변과 새 질문 검증이 남아 있다. [답변 재생 및 원본 계보](../data/eval/stack-selection/minimax_quality_answer_replay_v1/replay.jsonl.gz)

### 요청 후 재시도

같은 모델·색인·검색 설정으로 F01–F08을 다시 순차 호출했다. 검색과 요구 원문 확보는 각각 8/8이었고, 답변 요청 8건은 모두 HTTP 529를 반환했다. 같은 엔드포인트에 평가 문맥을 뺀 `Reply with OK.`를 보내도 스트리밍과 비스트리밍 모두 HTTP 529였으며, 두 응답 본문에 `overload`가 있었다. 두 응답에 재시도 시점을 지정하는 `Retry-After` 헤더는 없었다. 신규 답변 품질은 계속 미측정이다. [8문항 재시도 기록](../data/eval/stack-selection/minimax_quality_final_retry_v2) · [NVIDIA 모델 API 명세](https://build.nvidia.com/minimaxai/minimax-m3.1-flash/apireference)

## 재현

프로젝트 Python 3.14 환경에서 보존 기록을 집계한다. 세 명령은 로컬 파일만 읽는다.

```bash
eval_dir=data/eval/stack-selection
python3 -B scripts/eval_rag_graph.py --summary \
  --output-dir "$eval_dir/minimax_rewrites_v1" \
  --retry-dir "$eval_dir/minimax_rewrites_retry_v1"
python3 -B scripts/optimize_minimax_search.py summary \
  --grid "$eval_dir/minimax_search_grid_v1/grid.jsonl.gz"
python3 -B scripts/eval_rag_graph.py --summary \
  --output-dir "$eval_dir/minimax_search_final_v1"
```

격자와 실제 그래프를 다시 실행하려면 아래 명령을 사용한다. 실행 환경에 고정 revision의 임베딩 및 교차 인코더 모델이 필요하다. 답변을 재호출할 때는 `.env.local`에서 `NVIDIA_API_KEY`를 불러온 뒤 `final`을 사용한다. `verify`와 `final`에서 `--baseline`을 넣으면 기준선, 생략하면 격자의 최상위 후보를 실행한다.

```bash
python3 -B scripts/optimize_minimax_search.py grid \
  --rewrites "$eval_dir/minimax_rewrites_v1" \
  --rewrite-retries "$eval_dir/minimax_rewrites_retry_v1" \
  --output-dir /tmp/art-minimax-grid
python3 -B scripts/optimize_minimax_search.py verify \
  --grid /tmp/art-minimax-grid/grid.jsonl.gz \
  --rewrites "$eval_dir/minimax_rewrites_v1" \
  --rewrite-retries "$eval_dir/minimax_rewrites_retry_v1" \
  --output-dir /tmp/art-minimax-verify
python3 -B scripts/optimize_minimax_search.py final \
  --grid /tmp/art-minimax-grid/grid.jsonl.gz \
  --output-dir /tmp/art-minimax-final
```

모델 고정 후 개선은 `verify --improved`와 `final --improved`로 재현한다. 두 명령은 보존 격자에서 MiniLM + BM25 `20/5/0.5/0.75`를 찾는다. `final --improved`의 `--query F01`은 해당 문항만 호출한다. 새 API 시도는 새 출력 디렉터리에 보존한다.
