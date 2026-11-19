# 실제 RAG 그래프의 임베딩·리랭킹 비교

**검색 기준은 MiniLM + BM25를 유지한다.** 같은 158개 청크와 재작성 질의로 두 임베딩과 세 검색 순위 설정을 비교했다. MiniLM + BM25는 원문 ID 재현율 98.0%와 반증 원문 보존 5/5를 유지했고, 순수 벡터 검색과 비교해 첫 근거 원문의 순위가 높았다. [사전 비교 계획](RAG_stack_selection_plan.md#실제-rag-그래프에서-검색-조합-재평가)

## 회귀 100문항

실제 `INTAKE → ROUTE → DISPATCH → SEARCH`를 돌리고 `ANSWER` 직전에 중단했다. 각 실행에 실제 라우터와 T9 Chroma를 연결했다. T14의 보존 재작성과 청크는 후보 간 동일하며, 최종 답변과 라우팅 선택에 골드를 주입하지 않았다. E5-small은 동일 256토큰 가드와 `query: `/`passage: ` 접두사를 사용해 새 임베딩을 적재했다. 후보 20·상위 5로 고정하고 BM25와 MS MARCO 교차 인코더에는 T15의 `min_score=0.5`·가중치 0.25를 적용했다. [600건의 검색 기록](../data/eval/stack-selection/graph_search_v2)

| 임베딩 · 검색 순위 | 원문 ID 정밀도 | 원문 ID 재현율 | RawPedia / GitHub 재현율 | 반증 원문 | 첫 골드 MRR | 검색 중앙값 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniLM · BM25 | 27.87% | 98.00% | 97.50% / 100.00% | 5/5 | 0.9100 | 21.6 ms |
| MiniLM · 벡터 순위 | 27.77% | 98.00% | 97.50% / 100.00% | 5/5 | 0.8967 | 9.3 ms |
| MiniLM · 교차 인코더 | 40.62% | 93.00% | 97.50% / 75.00% | 1/5 | 0.8708 | 3,830.2 ms |
| E5-small · BM25 | 29.78% | 97.00% | 96.25% / 100.00% | 5/5 | 0.9123 | 22.0 ms |
| E5-small · 벡터 순위 | 28.10% | 93.00% | 91.25% / 100.00% | 5/5 | 0.8565 | 12.1 ms |
| E5-small · 교차 인코더 | 40.85% | 91.00% | 95.00% / 75.00% | 1/5 | 0.8733 | 4,099.4 ms |

라우팅과 검색 실행은 모든 조합이 100/100이었다. 문서 ID 정밀도·재현율은 질문별 비율의 평균이며 빈 검색은 0점으로 집계했다. 검색 중앙값은 같은 장비에서 두 임베딩 작업이 함께 실행된 동안의 검색 노드 시간이다. 재작성은 보존 결과를 재사용했다. 기준선 대비 출처별 재현율·반증 근거가 떨어지지 않은 대안은 MiniLM 벡터 순위였다. 두 E5 벡터/BM25 설정은 RawPedia 재현율에서, 두 교차 인코더 설정은 GitHub 재현율과 반증 근거에서 기준에 미달했다.

라우터는 글 번호가 없는 명시적 ART GitHub 요청을 GitHub 검색으로 보내도록 수정했다. Q024처럼 외부 도구의 버그를 문서에서 확인하는 질문도 RawPedia로 분류한다. F06은 검색 출처나 이슈 번호를 넣어주지 않은 일반 요청으로 Issue #518의 근거를 반환했다. F06은 알려진 라우팅 문제를 확인하는 회귀 사례다. [라우팅 규칙](langgraph_router_design.md#2-경로-판단-규칙)

## 실제 답변 비교

독립 F01–F08의 보존 재작성을 사용해 실제 그래프를 `RESPOND`까지 실행했다. MiniMax로 BM25와 벡터 순위를 비교하고, Nemotron은 BM25의 동일 문맥에서 실행했다. 이전 CLI 답변은 새로 호출하지 않았다. F04·F07의 근거 부족에는 실제 `RESEARCH` 전이를 실행했다. 이 비교의 재검색은 보존 재작성을 다시 사용한다. [독립 질문과 근거](../data/eval/stack-selection/final_questions_v1.json) · [원본 호출](../data/eval/stack-selection/graph_final_v2)

BM25에서 MiniMax는 상태 8/8을 맞췄다. Nemotron은 F05에서 `[C1S2, C1S3]`을 한 표식으로 생성해 기존 인용 검증에서 차단됐다. F04에서는 근거 부족 상태를 반환했지만 RawTherapee의 조건을 ART 공식 한도로 설명해 제품 범위 기준에 미달했다. 두 모델 모두 기본 라우팅과 첫 검색의 요구 원문 ID 확보는 8/8이었다.

| 설정 · 답변 모델 | 요구 원문 ID 확보 | 유효 답변 | 상태 일치 | 성공한 답변의 그래프 시간 중앙값 |
| --- | ---: | ---: | ---: | ---: |
| MiniLM + BM25 · MiniMax | 8/8 | 8/8 | 8/8 | 23.78초 |
| MiniLM + BM25 · Nemotron | 8/8 | 7/8 | 7/8 | 13.21초 |
| MiniLM 벡터 순위 · MiniMax | 8/8 | 5/8 | 5/8 | 48.00초 |

벡터 순위의 F04·F05는 응답 제한 60초를 넘겼고, F08은 인용 ID 목록과 답변 본문의 표식이 일치하지 않았다. 벡터 순위에 대한 경과 시간은 순차 재시도와 동시 실행 기록이 함께 포함되며, 검색 설정만의 지연 차이는 회귀 표의 검색 노드 값으로 비교한다. [벡터 순위의 제한 응답 및 재시도](../data/eval/stack-selection/graph_retry_v1)

MiniLM + BM25의 두 모델은 각 10회 호출했다. 검색만 하는 중간 단계에서 호출한 별도 모델은 없다. MiniMax는 입력 89,228·출력 2,276토큰, Nemotron은 입력 94,008·출력 23,900토큰을 응답에서 반환했다. NVIDIA 무료 경로의 관측값이며 직접 유료 API의 품질·지연은 미측정이다.

## 실시간 재작성과 적용 판정

MiniMax로 재작성과 답변을 모두 실호출하니 출처 분류 8/8, 요구 원문 확보 7/8, 유효 답변 7/8, 기대 상태 일치 6/8이었다. F01에서 생성한 한국어 검색 질의는 두 번 모두 RawPedia `Crop` 원문을 놓쳤고, 끝내 근거 부족으로 답했다. F08은 인용 목록과 본문 표식이 달라 검증에서 차단됐다. 보존 재작성 비교와 실시간 재작성 검증에서 각각 3문항이 HTTP 429를 받아 순차 재실행했으며, 최종 429는 0건이다. 첫 시도와 재시도를 함께 보존했다. [실시간 재작성 호출](../data/eval/stack-selection/graph_live_rewrite_v1) · [순차 재시도](../data/eval/stack-selection/graph_live_rewrite_retry_v1)

MiniLM + BM25를 이 비교의 검색 기준으로, MiniMax를 답변 생성 후보로 유지한다. 실시간 재작성의 근거 확보와 인용 검증이 기준에 미달해 GUI·CLI 기본값 전환과 정식 T23 인수는 보류한다. 100문항은 검색 회귀에 사용했으며 빈칸을 채울 새 Sol 응답이나 원자 주장별 평가 호출은 수행하지 않았다. 두 MiniLM 설정을 새 색인에서 다시 검색한 200건의 질의·경로·선택 순서와 원문 ID 지표가 각각 일치했고, 기존 T23 오프라인 리포트도 동일하게 재생성됐다.

## 재현

각 명령은 파이프라인 의존성이 설치된 프로젝트 Python 3.14에서 실행한다. 집계는 저장된 파일만 읽는다. 실제 호출을 재실행할 때는 `.env.local`에서 `NVIDIA_API_KEY`를 불러오고 새 출력 디렉터리를 사용한다.

```bash
python3 -B scripts/eval_rag_graph.py --summary \
  --output-dir data/eval/stack-selection/graph_search_v2
python3 -B scripts/eval_rag_graph.py --summary \
  --output-dir data/eval/stack-selection/graph_final_v2 \
  --retry-dir data/eval/stack-selection/graph_retry_v1
python3 -B scripts/eval_rag_graph.py --summary \
  --output-dir data/eval/stack-selection/graph_live_rewrite_v1 \
  --retry-dir data/eval/stack-selection/graph_live_rewrite_retry_v1
```
