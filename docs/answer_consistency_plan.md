# RAG 답변의 보정 방향 일관성 개선 계획

## 목표와 범위

사용자가 색감이나 밝기의 문제를 설명하고 보정 방법을 물으면, 첫 권장 조작이 그 증상을 완화해야 한다. 조작 효과는 맞게 설명해도 권장 방향이 증상을 악화하거나, 같은 적용 조건에서 답변이 서로 반대 방향을 지시하면 사용자에게 표시하기 전에 걸러낸다. 첫 적용 대상은 White Balance의 Temperature 사용법 질문이다. 틴트·노출·대비·채도를 평가에 포함하고, 적용 범위는 도구별 근거와 오탐 결과에 따라 넓힌다.

이 계획은 Master Q&A의 A-17 답변 단계에 해당하며 A-16 재검색 계약과 A-23 고정 100문항 평가를 따른다. 후속 구현은 Python 답변 경로와 평가에 한정한다. `rtengine/`·`rtgui/` 수정, `.arp` 생성·렌더링·FiveK 변경, 코퍼스 수정·재색인, 검색 설정 및 답변 모델 교체는 범위 밖이다. 기존 프로젝트 Python 3.14 환경을 사용한다. 추가 의존성은 실제 소비 태스크에서 필요성이 확인될 때 설치하고 그때 기록한다. [AGENTS.md](../AGENTS.md#conventions) · [WBS §5](ART_agentic_wbs.md#L118-L153) · [기존 서비스 적용 계획](../tasks/plan.md#L118-L138) · [A-23 완료 기준](../tasks/todo.md#L363-L374)

## 재현 기록과 원인

2026-11-20 제공 기록에서 `ART_RAG_PROFILE=local`로 `python -m artagent.gui_bridge`에 “사진이 노랗게 나와요. White Balance에서 무엇부터 조정해야 하나요?”를 세 번 보냈고 모두 `COMPLETED`였다. 첫 두 답변은 오른쪽으로 옮겨 더 따뜻하게 하라고 권했다. 세 번째는 오른쪽이 더 차갑다고 지시한 뒤 같은 답변에서 노란 기를 줄이려면 왼쪽이라고 뒤집었다. 앞선 정답 실행의 생성 경로는 미확인이다. 이번 계획 작성에서는 제공 기록을 사용했으며 당시 세 요청의 정규화된 질문·실제 제출 문맥·인용 ID·원시 응답·요청 지문과 세 실행 간 동일 여부는 미확인이다.

저장소 원문은 Temperature를 왼쪽으로 옮기면 더 차가워지고 오른쪽으로 옮기면 더 따뜻해진다고 설명한다. 노란 기를 줄이는 것이 목적이면, 더 차가워지는 쪽인 왼쪽이 질문에 맞는 첫 조작이라는 결론을 도출할 수 있다. 원문에 명시된 것은 조작의 효과이며, 처방은 질문의 증상과 그 효과를 연결한 추론이다. RawPedia 설명의 제품 적용 범위도 함께 지켜야 한다. [data/rawpedia/White_Balance.md:161–169](../data/rawpedia/White_Balance.md#L161-L169) · [src/artagent/answer.py:107–113](../src/artagent/answer.py#L107-L113)

| 단계 | 저장소에서 확인한 동작과 개선 지점 |
| --- | --- |
| GUI 브리지와 그래프 | `create_gui_graph`는 `create_answer_node`에 `service_answer_generator()`를 연결하고 `local`에서 인용 자동 조립을 켠다. `create_answer_node`는 계획 항목의 질문을 사용하고 비어 있으면 원요청으로 대체한다. `answer_standalone`은 이 질문을 정규화하고 원문 대조를 거친 검색 세그먼트로 답변을 만든다. 방향 검사는 이 항목의 질문과 적용 조건을 사용해야 한다. 검색용 재작성문은 평가 기준에서 제외한다. [src/artagent/gui_bridge.py:94–102](../src/artagent/gui_bridge.py#L94-L102) · [src/artagent/graph/answer.py:722–729](../src/artagent/graph/answer.py#L722-L729) · [src/artagent/graph/answer.py:772–789](../src/artagent/graph/answer.py#L772-L789) · [src/artagent/graph/answer.py:343–389](../src/artagent/graph/answer.py#L343-L389) |
| 프롬프트 | `build_prompt_and_citations`는 검색 문맥·인용 ID·질문을 제공하고 한국어 답변, 근거 사용, 제품 범위와 답변 상태를 지시한다. 증상에서 목표 효과를 정하고, 권장 방향이 그 효과를 내는지나 앞뒤 설명이 일치하는지를 대조하는 요구는 없다. 문서에 효과만 있는 경우의 추론 방법을 이 단계에서 명시할 수 있다. [src/artagent/answer.py:399–414](../src/artagent/answer.py#L399-L414) · [src/artagent/answer.py:461–499](../src/artagent/answer.py#L461-L499) |
| 생성 설정과 JSON 검증 | `service_answer_generator`는 설정과 키 조건에 따라 NVIDIA MiniMax `minimaxai/minimax-m3.1-flash`를 선택한다. 검색 프로필과 제공처 선택은 별개다. `generate_llm_response`의 API 요청은 `temperature=0.0`과 `response_format`의 `json_object`를 전달한다. `_validate_llm_json_obj`와 그래프의 응답 파서는 상태 열거값, 비어 있지 않은 `answer`, 문자열 목록인 `citation_ids`를 확인한다. 이 계약에는 증상·목표·조작·효과를 대조할 정보가 없다. 제공 기록상 같은 온도 설정에서 결과도 달랐다. [src/artagent/rag_service.py:13–18](../src/artagent/rag_service.py#L13-L18) · [src/artagent/rag_service.py:41–82](../src/artagent/rag_service.py#L41-L82) · [src/artagent/answer.py:1050–1085](../src/artagent/answer.py#L1050-L1085) · [src/artagent/answer.py:516–539](../src/artagent/answer.py#L516-L539) · [src/artagent/graph/answer.py:471–503](../src/artagent/graph/answer.py#L471-L503) |
| 생성 후 검사와 완료 상태 | 그래프는 `SUPPORTED`·`UNSUPPORTED`에 인용과 문맥을 요구한다. `local`은 본문 표식에서 목록을 조립한다. `validate_and_format_citations`는 엄격 모드에서 표식 형식을, 공통으로 표식과 ID 목록의 집합 일치 및 문맥 내 ID·표시명·URL을 검사한 뒤 출처를 치환한다. 질문·조작 효과·결론의 일치와 같은 답 안의 상충은 검사 대상에 없다. 그래프가 `SUPPORTED`를 `SUCCEEDED`로 매핑하고 성공한 단계를 `COMPLETED`로 집계하는 흐름이 관찰과 일치한다. 검사 위치는 JSON 파싱과 기존 인용 검증 이후, `AnswerResult` 생성 직전이다. [src/artagent/graph/answer.py:526–599](../src/artagent/graph/answer.py#L526-L599) · [src/artagent/answer.py:1107–1151](../src/artagent/answer.py#L1107-L1151) · [src/artagent/graph/answer.py:623–650](../src/artagent/graph/answer.py#L623-L650) · [src/artagent/graph/nodes.py:750–763](../src/artagent/graph/nodes.py#L750-L763) · [src/artagent/graph/nodes.py:818–829](../src/artagent/graph/nodes.py#L818-L829) |
| 직선 파이프라인과 평가 | `run_pipeline`에도 프롬프트·생성·인용 검증이 있지만 GUI는 그래프를 호출한다. T11 직선 경로는 공유 함수 변경에 대한 호환성 검증 대상으로 둔다. T23의 근거 충실도는 제출 문맥이 뒷받침하는 원자 주장 비율이다. 예컨대 ‘오른쪽으로 옮기면 따뜻해진다’는 지지된다. ‘노란 기를 줄이려면 오른쪽으로 옮긴다’까지 별도 주장으로 추출하면 감점될 수 있다. 질문의 목표 달성과 답변 전체의 일관성을 이 점수에서 직접 판정하지는 않으며, 제공된 세 답변의 실제 점수는 미확인이다. [src/artagent/answer.py:1357–1386](../src/artagent/answer.py#L1357-L1386) · [src/artagent/answer.py:1473–1478](../src/artagent/answer.py#L1473-L1478) · [src/artagent/gui_bridge.py:157–165](../src/artagent/gui_bridge.py#L157-L165) · [scripts/eval_ragas.py:295–310](../scripts/eval_ragas.py#L295-L310) · [scripts/judge_t23_faithfulness.py:27–49](../scripts/judge_t23_faithfulness.py#L27-L49) |

## 후보 비교

| 후보 | 추가 호출과 지연 | 오탐과 적용 범위 |
| --- | --- | --- |
| A. 프롬프트에 증상·목표·효과 대조 지시 | 외부 호출 추가 없음. 입력 토큰과 생성 지연 변화는 측정한다. | 여러 보정 도구에 적용할 수 있다. 모든 질문에 방향을 강제하면 기능 설명·창작 의도를 오독할 수 있으므로 조작을 권하는 답변에만 지시를 적용한다. 모델이 지시를 놓친 답변은 그대로 통과할 수 있다. |
| B. 내부 답변 JSON에 증상·목표 효과·도구·조작·기대 효과·근거를 구조화하고 규칙 검사 | 외부 호출 추가 없음. 토큰, JSON 오류율, 버전 호환성 검증 비용이 늘어난다. | 축과 부호가 정의된 도구에 확장 가능하다. 필드끼리 일치해도 모델이 증상이나 근거를 함께 바꾸면 통과할 수 있다. 원질문 및 실제 인용 문맥과 독립적으로 대조하고 최종 표시 문장도 검사하거나 검증된 값에서 표시 문장을 조립해야 한다. 조건부 처방과 복수 도구는 별도 설계가 필요하다. |
| C. 생성 후 방향과 답변 내부 상충 검사 | 로컬 검사로 외부 호출 추가 없음. 지연은 실측한다. | 확인한 도구·문맥·표현부터 적용할 수 있어 차단 이유를 추적하기 쉽다. 좌·우의 단순 동시 출현을 기준으로 삼으면 비교 설명, 부정, 서로 다른 조건을 오탐한다. 표현 분석의 적용 범위를 넘어서는 질문에는 검사 보장이 제한된다. |
| D. 상충 시 안내 또는 제한적 재생성 | 검증 실패 안내는 추가 호출 없음. 같은 문맥에서 한 번 재생성하는 안은 추가 호출·대기·실패 가능성이 생긴다. | 안내는 오답 노출을 줄이지만 정상 답변의 보류가 늘 수 있다. 재생성은 여러 유형에 적용할 수 있으나 같은 오류가 반복될 수 있어 같은 검사와 요청 전체 예산을 적용해야 한다. |

## 권장안

**A와 C를 함께 적용하고, 확인된 모순은 D의 무호출 안내로 처리한다.** 프롬프트가 바른 추론을 돕고 공통 그래프 답변 단계가 실제 표시 문장을 판정한다. Temperature에서 실패 패턴과 정상 답변을 함께 검증한 뒤, 규칙이 신뢰할 수 있는 도구와 표현만 확장한다. 자유 텍스트 처리에서 미판정이나 오탐이 많으면 B를 별도 후보로 비교한다. 이때 JSON 계약 변경과 API·Codex 응답 파서·보존 기록 호환 비용을 함께 평가한다.

1. **프롬프트.** 조작을 권할 때 질문의 현재 상태와 원하는 변화를 먼저 구분하고, 인용 문맥이 말하는 조작 효과와 대조하게 한다. 증상을 악화할 방향은 권장하지 않고, 첫 조작과 후속 설명에서 방향을 일치시킨다. 조작 효과에서 도출한 권장임을 답변에서 드러내고 제품·버전·모드가 불명확하면 적용 범위를 밝힌다. 명시된 창작 목표는 그대로 사용한다. 프롬프트 버전·지문을 조건별로 남기고, 기존 `t17-answer-v1` 응답 스키마와 보존 응답의 원래 프롬프트 재생 경로를 유지한다. T17 기록을 만드는 스크립트는 프롬프트 버전 상수를 기록하므로 실제 적용한 버전과 기록값도 대조한다. [src/artagent/graph/answer.py:379–391](../src/artagent/graph/answer.py#L379-L391) · [src/artagent/graph/answer.py:439–449](../src/artagent/graph/answer.py#L439-L449) · [src/artagent/answer.py:461–481](../src/artagent/answer.py#L461-L481) · [scripts/check_t17_answer.py:246–251](../scripts/check_t17_answer.py#L246-L251)
2. **방향 검사.** 적용 대상의 현재 상태·목표를 항목 질문과 확정 조건에서 읽고, 허용된 원문 세그먼트가 뒷받침하는 해당 도구의 조작→효과와 분리해 비교한다. 답변의 첫 권장과 후속 지시를 추출해 ① 목표와 권장 효과, ② 권장 방향과 원문의 효과, ③ 동일 도구·적용 조건 안의 지시끼리 대조한다. 사용자가 원하는 조작의 부호와 그 결과를 별개로 봐서 ‘오른쪽으로 차갑게’도 잡는다. 인용된 설명, ‘오른쪽이 아니라’ 같은 명시적 부정, 조건이 다른 좌·우 비교는 실제 권장과 구분한다. 확인된 대상에 방향 권장이 있는데 해석이 불가능하거나 결론을 지지하는 세그먼트가 없으면 해당 조작을 보류하고 그 사유를 집계한다. 대상 밖의 일반 Q&A에는 기존 검사를 적용하고 미검사 범위를 평가에 명시한다. [src/artagent/graph/answer.py:361–389](../src/artagent/graph/answer.py#L361-L389) · [src/artagent/graph/answer.py:592–650](../src/artagent/graph/answer.py#L592-L650)
3. **보류 처리.** 확인된 모순이나 검증할 수 없는 권장 조작은 원래 답변·인용을 제거하고 기존 `INSUFFICIENT_EVIDENCE` 오류 코드의 안전한 안내를 사용한다. 내부 관찰 기록에는 차단 사유와 검사 근거를 남긴다. 그래프가 오류를 먼저 처리하므로 이 경로에서는 재검색·재생성을 시작하지 않는다. 기존 `AnswerResult.status=INSUFFICIENT_EVIDENCE`로 표현되는 검색 근거 부족은 A-16의 요청 전체 1회 재검색과 중복 검색 생략을 따른다. 공급자 장애의 명시적 폴백은 별개로 유지한다. 이후 재생성을 검토할 때는 같은 문맥에서 한 번만 시도하는 조건을 비교하고, 기존 재검색 및 공급자 폴백과 합친 호출 수·기한을 검증한다. [src/artagent/graph/graph.py:99–122](../src/artagent/graph/graph.py#L99-L122) · [src/artagent/graph/research.py:109–139](../src/artagent/graph/research.py#L109-L139) · [src/artagent/graph/nodes.py:750–761](../src/artagent/graph/nodes.py#L750-L761) · [src/artagent/gui_bridge.py:114–131](../src/artagent/gui_bridge.py#L114-L131) · [src/artagent/rag_service.py:69–82](../src/artagent/rag_service.py#L69-L82)

## 평가 계약

### 방향·부호 회귀 문항 고정

후보 실행 전에 질문 ID와 원문, 제품·버전과 도구/모드, 관찰 증상, 명시된 목표, 허용할 첫 조작과 효과, 금지 방향·내부 상충, 기대 상태, 허용 원문 ID와 근거 절·행·지문을 고정한다. 동의어 또는 조건부 답변을 허용할 범위도 사전에 기록한다. 원문에 직접 적힌 효과와 질문에서 도출한 처방을 각각 기록하고, 제품이나 조작 방향을 확인할 근거가 부족한 사례에는 조건부 안내 또는 근거 부족을 기대한다. 기존 T8-1 100문항의 내용과 정답 원문 표는 그대로 사용한다. [docs/search_eval_queries.json:1–21](search_eval_queries.json#L1-L21) · [독립 평가 입력 기준](../tasks/todo.md#L315-L329)

| 축 | 문항 설계와 확인한 근거 |
| --- | --- |
| 색온도 | 노란 기 완화와 푸른 기 완화를 짝으로 만든다. 명시적 따뜻한 분위기 요청과 좌·우 효과 설명 질문을 대조 사례로 둔다. 제공된 질문은 이미 알려진 개발·회귀 사례다. [data/rawpedia/White_Balance.md:161–165](../data/rawpedia/White_Balance.md#L161-L165) |
| 틴트 | 초록 기 완화와 마젠타 기 완화를 짝으로 만들고 색온도와 섞인 질문도 넣는다. RawPedia는 왼쪽으로 마젠타, 오른쪽으로 초록이라고 설명한다. [data/rawpedia/White_Balance.md:167–169](../data/rawpedia/White_Balance.md#L167-L169) |
| 노출 | 과다·부족 노출의 Exposure Compensation 부호를 짝으로 만들고, 단순 노출 변화와 클리핑 복구 질문을 대조한다. 클리핑 조건에서 밝기를 내리는 조작만으로 복구된다고 채점하지 않는다. [data/rawpedia/Exposure.md:118–136](../data/rawpedia/Exposure.md#L118-L136) |
| 대비·채도 | 과한 대비/낮은 대비, 과한 채도/낮은 채도를 짝으로 만든다. 해당 슬라이더의 증가·감소와 기대 변화를 채점하고, 마우스 이동 방향과 구체 수치는 적용 제품·모드 근거를 확인한 문항에서만 채점한다. 채도를 낮추는 예시는 Lab 문서에서도 확인된다. [data/rawpedia/Exposure.md:282–294](../data/rawpedia/Exposure.md#L282-L294) · [data/rawpedia/Lab_Adjustments.md:117–123](../data/rawpedia/Lab_Adjustments.md#L117-L123) |

양방향 처방 외에 부정문, 명시적 창작 목표, 여러 도구, 조건별로 달라지는 방향, 방향 없는 기능 설명, 제품 범위 불확실, 근거 누락을 고정한다. 알려진 사례와 동의어 변형은 개발·회귀용으로 묶는다. 최종 평가용은 후보 답변을 보기 전에 분리하고 동일한 문서/스레드·원문 절과 질문 변형이 양쪽에 유출되지 않았는지 점검한다. 같은 절을 사용하는 문항은 방향 회귀로 집계한다. 독립 문항 수는 고유 근거와 실행 예산을 확인한 뒤, 후보 실행 전에 고정한다. [WBS의 독립 검증 기준](ART_agentic_wbs.md#L147-L153) · [최종 스택 선정 카드](../tasks/todo.md#L331-L350)

### 실행과 합격 기준

1. **오프라인 회귀.** 제공된 세 답변의 핵심 지시를 테스트용 JSON 응답으로 재구성하고, 저장소 원문과 연결한 유효 인용 표식을 붙여 생성 콜백으로 주입한다. 이 입력은 제공 기록을 재구성한 테스트 입력으로 표시한다. 방향 검사 전후의 사용자 표시 상태·본문·인용을 대조한다. 세 오류는 전부 차단하고, 올바른 왼쪽 안내·푸른 기에 대한 반대 방향·조건별 좌우 설명은 통과해야 한다. 부정과 정정 자체는 허용하고, 같은 조건에서 잘못된 긍정 지시가 남아 있는 답변은 차단한다. 기존 형식·인용 오류, 미지원, 실제 근거 부족, 혼합 요청, 재검색 예산, GUI·CLI 상태 차이가 없는지도 고정 입력으로 확인한다. [src/artagent/graph/answer.py:417–449](../src/artagent/graph/answer.py#L417-L449) · [그래프 답변 테스트](../tests/test_graph_answer.py) · [재검색 테스트](../tests/test_graph_research.py) · [GUI 브리지 테스트](../tests/test_gui_bridge.py)
2. **같은 문맥의 비교.** 후속 실측이 가능한 환경에서 기준선·프롬프트만·프롬프트와 검사 적용 조건을 같은 질문·검색 bundle·문맥 순서·모델·생성 설정에서 비교한다. 방향 회귀는 조건별로 문항당 **3회**를 기본 반복 설계로 삼는다. 제공 기록이 세 시도에서 방향 오류와 내부 상충을 모두 보여 줬으므로 이 사례와 대조할 수 있는 반복 수다. 기준선 예비 측정으로 표본과 호출 예산을 확인하고 반복 수를 조정해야 하면 후보와 최종 평가 실행 전에 확정한다. 각 시도를 별도 기록하고 올바른 첫 조작·효과·인용, 방향 오류, 내부 상충, 과잉 보류, 기술 실패를 판정한다. 모델과 조건을 가린 채 원질문·허용 조작·제출 문맥을 대조한다. 문항별 전회 통과와 시도별 비율을 함께 기록하며 실패한 첫 시도를 삭제하거나 성공한 재시도로 대체하지 않는다. 검사 유무만 비교할 때는 동일한 생성 원문을 양쪽에 주입해 생성 편차를 통제한다. 프롬프트 변경 전 응답의 재생 결과는 검사 동작을 입증하는 데 사용한다.
3. **100문항 검색 비저하.** `t08-1-100-v1`의 동일 서비스 색인·프로필·임베딩 revision·활성 청크 지문·설정에서 첫 검색의 질의·원문 ID 순위·ID 기반 context precision/recall을 문항별로 대조한다. 순위와 반증 원문 확보를 유지하고 전체 및 RawPedia/GitHub별 지표 비저하를 확인한다. `scripts/eval_rag_service.py`는 `ANSWER` 전에 중단하므로, 선택 후보의 전체 그래프 실행에서도 최종 검색 문맥과 재검색 발생 여부를 따로 대조한다. 검색 차이가 생기면 최초 검색·A-16 재검색·문맥 전달 중 발생 위치를 찾는다. 기존 서비스 검색 기록과 T15/A-23 보존 결과는 각자의 입력 조건으로 비교한다. [scripts/eval_rag_service.py:23–51](../scripts/eval_rag_service.py#L23-L51) · [data/eval/rag-service/search_v1](../data/eval/rag-service/search_v1) · [data/eval/report_v1.md:3–35](../data/eval/report_v1.md#L3-L35)
4. **100문항 답변 근거 충실도 비저하.** 같은 100문항과 고정 검색 문맥에서 개선 전후 새 답변을 짝지어 확보한다. 양쪽에 같은 추출·판정 기준을 적용하고 실제 제출 문맥을 근거로 `faithfulness_score`와 동일 산식으로 집계한다. 보존 판정 재사용 여부는 입력 지문으로 결정한다. 공통 채점 가능 문항의 매크로 평균과 문항별 하락, 전체 시도의 채점 가능 비율·무주장·근거 부족·기술 실패 및 인용 오류를 함께 본다. 과잉 보류로 공통 표본이 줄고 점수만 오르면 통과를 보류한다. 기존 100문항 기록 재집계와 서비스 보존 답변 재집계는 채점 계약 확인에 사용한다. 두 스크립트의 기본 입력은 각각 보존 T15/T17 자료와 F/S 서비스 자료로 고정되어 있으므로 새 후보의 채점에는 입력을 명시하는 평가 경로가 필요하다. [scripts/eval_ragas.py:288–310](../scripts/eval_ragas.py#L288-L310) · [scripts/eval_ragas.py:479–505](../scripts/eval_ragas.py#L479-L505) · [scripts/eval_rag_service_faithfulness.py:31–58](../scripts/eval_rag_service_faithfulness.py#L31-L58) · [data/eval/ragas_v2/paired](../data/eval/ragas_v2/paired)
5. **채택 판정.** 고정한 오프라인 필수 사례를 모두 통과해야 한다. 최종 평가에서 모순 조작이 정상 완료로 노출되면 채택을 보류한다. 근거가 충분한 정방향 답변과 비교·조건부 설명도 유지해야 한다. 검색과 근거 충실도 비저하, 유효 답변과 기술 성공률, 과잉 보류, 호출 수·토큰·비용, GUI 브리지/CLI의 전체 지연과 폴백 여부를 함께 대조한다. 지연은 시작 비용을 포함해 기록한다. 수치 목표와 표본·변동에 대한 판정 기준은 현행 기준선 및 개발 문항의 예비 측정 후 정하고 후보 최종 실행 전에 고정한다. 실측이 빠진 항목은 미확인으로 남기고 기본 적용 여부 판단을 보류한다. [WBS의 사전 확정 기준](ART_agentic_wbs.md#L147-L153) · [기존 서비스 전환 기준](../tasks/plan.md#L131-L138)

## 후속 작업 카드

아래 명령은 구현 단계에서 저장소 루트의 기존 프로젝트 가상환경과 보존 자료로 실행한다. 현재 워크트리에는 `venv/`와 `.env.local`이 없다. 검증된 프로젝트 가상환경 위치와 Chroma 스냅샷을 인수한다. 검색 명령은 이미 캐시된 임베딩을 사용한다. 검증 출력은 별도 임시 경로에 둔다. 이번 계획 작성에서는 아래 명령이나 외부 API를 실행하지 않았다.

| 카드 및 의존성 | 변경 후보 파일 | 완료 조건과 검증 |
| --- | --- | --- |
| 1. 재현 입력과 평가 기준 고정 | `tests/test_graph_answer.py` 및 `data/eval/`의 별도 방향 회귀 입력. 새 입력 파일명은 미확인. | 재현 응답·정상 대조·근거 누락 입력을 원문에 대조한다. 현행 검사에서 유효 인용이 붙은 재현 응답이 통과함을 고정 콜백으로 확인하고 목표 회귀를 등록한다. 최종 평가 문항의 출처·중복·분리·지문과 기준선 수집 조건을 점검한다. 명령 A와 B. |
| 2. 방향 대조 프롬프트 적용 · 카드 1 후 | `src/artagent/answer.py`, `src/artagent/graph/answer.py`, `tests/test_answer.py`, `tests/test_graph_answer.py` | T17에 방향·목표 대조 지시를 넣고 JSON·인용 계약과 T11 직선 경로를 회귀 검증한다. 프롬프트의 버전과 지문을 기록하고 기존 응답 지문을 원본대로 검증할 수 있어야 한다. 명령 B. |
| 3. 답변 모순 차단과 안전한 응답 · 카드 2 후 | `src/artagent/graph/answer.py`, `tests/test_graph_answer.py`, `tests/test_graph_research.py`, `tests/test_gui_bridge.py`, `tests/test_cli.py` | 재현 오류와 미검증 권장을 숨기고 안전한 기존 상태로 종결한다. 올바른 조작과 설명형 답변, 상태·인용·혼합 요청, A-16 요청 전체 예산을 확인한다. 차단 응답 때문에 생성·재검색 호출이 늘지 않아야 한다. GUI·CLI는 고정 응답으로 표시 계약까지 확인한다. 명령 C. |
| 4. 고정 문항의 대조 집계와 채택 판정 · 카드 3 후 | `scripts/eval_rag_service.py`, `scripts/eval_rag_service_faithfulness.py`, `tests/test_eval_ragas.py`. 새 평가 입력·기록은 `data/eval/`의 기존 보존 자료와 별도 위치에 둔다. 세부 파일명과 새 실행 옵션은 미확인. | 기존 첫 검색 모드와 별도로 선택한 조건의 답변·문맥을 수집할 수 있게 한다. 수집한 입력을 명시해 기존 산식으로 평가하고 미산출 사유도 집계한다. 기본 보존 자료 재집계, 두 프로필의 검색 순위, 후보의 GUI·CLI 전체 경로, 방향 판정 및 100문항 근거 충실도를 검증한다. 명령 A·C·D와 동일 조건 입력/판정 지문 대조. 별도 실행 가능 환경이 확보된 뒤에 모델 실측 결과를 채택 근거로 사용한다. |

```bash
# A. 보존된 평가 기록 재집계
venv/bin/python -B scripts/eval_ragas.py --output-dir "$(mktemp -d)"
venv/bin/python -B scripts/eval_rag_service_faithfulness.py

# B. 답변 생성·인용 계약과 방향 회귀
PYTHONPATH=src venv/bin/python -B -m pytest -p no:cacheprovider -q \
  tests/test_answer.py tests/test_graph_answer.py tests/test_t17_answer_eval.py

# C. 답변·재검색·진입점·공급자와 평가 산식 회귀
PYTHONPATH=src venv/bin/python -B -m pytest -p no:cacheprovider -q \
  tests/test_graph_answer.py tests/test_graph_research.py tests/test_gui_bridge.py \
  tests/test_cli.py tests/test_rag_service.py tests/test_eval_ragas.py

# D. 기존 서비스 색인에서 GUI와 CLI의 첫 검색 비교
# ART_CONSISTENCY_STORE에는 검증된 기존 T09 저장소 경로를 지정한다.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 venv/bin/python -B scripts/eval_rag_service.py \
  --reference docs/T08_2_t9_handoff_reference.json \
  --persist-dir "${ART_CONSISTENCY_STORE:?}" --output-dir "$(mktemp -d)"
```

명령 A는 보존 판정의 재집계, B·C는 생성 주입과 계약 검증, D는 첫 검색 검증에 해당한다. 프롬프트 변경 이후의 실답변 효과와 사용자 수준 지연은 별도 실측으로 확인한다. [T23 재현 명령](T23_execution_plan.md#L68-L76) · [서비스 검색 재현 명령](RAG_service_rollout_report.md#L72-L79)

## 위험과 미확인 사항

- RawPedia Temperature·Tint 설명의 ART 버전·편집 모드별 동작 일치와 당시 질문 화면의 편집 상태는 미확인이다. 답변의 적용 범위를 근거와 함께 표시하고, 제품 명시 질문은 적용 근거를 확보한 뒤 해당 도구를 적용 범위에 넣는다.
- 최초 문제의 실제 제출 문맥이 확인되면 효과 설명이 모델에 전달됐는지 먼저 대조한다. 원문 문장이 저장소에 있다는 사실만으로 제출 문맥 포함을 단정할 수 없다. 동일 조건의 새 실답변, 재현 빈도와 개선 효과, 비용·지연·오탐은 미확인이다.
- 검색 성공·인용 형식·근거 충실도를 모두 만족해도 잘못된 조작을 권할 수 있다. 방향 정확성은 별도 판정으로 유지한다. 반대로, 방향 검사 적용 밖의 문항은 검사가 보장하는 범위를 명시하고 과잉 보류에 의한 지표 상승과 구별한다.
- 정규화·부정·조건 처리가 약하면 같은 단어가 들어간 정상 비교문을 막거나 간접 지시를 놓칠 수 있다. 고정 대조 문항으로 드러난 오탐·미탐을 기준으로 표현 범위를 조정하고, 검증하지 않은 축으로 확장을 보류한다.
