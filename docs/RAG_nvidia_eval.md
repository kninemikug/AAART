# NVIDIA 무료 엔드포인트로 검증한 저비용 RAG 후보

**저비용 운영 검증 후보는 MiniMax M3.1 Flash다.** 독립 8문항의 상태·핵심 답변·인용·제품 범위 기준을 모두 충족했고, 원 제공사 단가로 환산하면 답변 1,000건당 $1.53이다. NVIDIA 시험 엔드포인트의 답변 중앙값은 26.77초였다. 운영 교체와 정식 T23은 유료 경로의 지연 및 기본 라우팅 검증 전까지 보류한다.

NVIDIA NIM 개발용 엔드포인트에서 T17의 고정 검색 문맥과 프롬프트로 답변을 생성했다. 운영 비용은 응답의 `prompt_tokens`와 `completion_tokens`에 **원 제공사 정규 단가**를 적용했다. 원 제공사에서의 캐시 적중률과 서비스 지연은 여기에서 측정되지 않았다. [사전 비교 계획](RAG_stack_selection_plan.md#저비용-api-후속-비교)

| 후보 | 입력 100만 토큰 | 출력 100만 토큰 | 연결과 단가 근거 |
| --- | ---: | ---: | --- |
| GLM-5.3-Flash | $0.15 | $0.50 | [NVIDIA](https://build.nvidia.com/z-ai/glm-5-3-flash), [Z.ai](https://docs.z.ai/guides/overview/pricing) |
| MiniMax M3.1 Flash | $0.15 | $0.60 | [NVIDIA](https://build.nvidia.com/minimaxai/minimax-m3.1-flash), [MiniMax](https://www.minimax.io/blog/minimax-m31f) |
| GPT-5.6 Terra 기준선 | $2.00 | $12.00 | [OpenAI](https://developers.openai.com/api/docs/models/gpt-5.6-terra) |

## 초기 비교 6문항

| 후보 | 기술 성공 | 예상 상태 일치 | 답변 시간 중앙값 | 원 제공사 환산 합계 |
| --- | ---: | ---: | ---: | ---: |
| GLM-5.3-Flash | 0/6 | 0/6 | `null` | `null` |
| MiniMax M3.1 Flash | 6/6 | 6/6 | 29.59초 | $0.01288 |

GLM은 6회 모두 기존 T17 API 시간 제한 60초를 초과했다. 응답·사용량을 확보하지 못해 답변 품질과 토큰 비용은 미검증이다. 요청은 모델별 기본 생성 설정의 영향도 받으므로 이 타임아웃은 측정한 NVIDIA 호출 조건에 해당한다. [초기 응답 기록](../data/eval/stack-selection/nvidia_pilot_v1)

MiniMax의 초기 답변은 질문의 핵심 사실, 상태 및 인용을 검토해 독립 비교에 넘겼다. Q033은 DCP가 필요한 이유를 문맥에 맞게 설명했으나 원문의 `DNG camera profile`을 `DNG Color Profile`로 잘못 풀어 썼다. Q086의 `Liked mask`는 GitHub 댓글의 표기를 인용한 것이다. [Q033 응답](../data/eval/stack-selection/nvidia_pilot_v1/Q033-minimaxai--minimax-m3.1-flash.json.gz)

## 독립 비교 8문항

| 실행 | 기술 성공 | 핵심 답변·상태·인용·범위 통과 | 답변 시간 중앙값 | 입력 / 출력 토큰 | 8문항 환산 | 1,000건 환산 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniMax M3.1 Flash · NVIDIA | 8/8 | 8/8 | 26.77초 | 73,045 / 2,164 | $0.01226 | $1.53 |
| GPT-5.6 Terra · Codex CLI | 8/8 | 8/8 | 7.70초 | 183,694 / 1,572 | $0.38625 | $48.28 |

두 실행의 검색 bundle과 T17 프롬프트 지문은 문항마다 일치했다. 원문 대조에서 RawTherapee의 세 사용법, ART 버전과 RawPedia 범위 구분, GitHub 사례의 실제 확인 범위, 미기재된 수정 커밋, PPI와 EXIF 태그의 차이를 확인했다. 미지원 및 근거 부족 3문항의 상태도 일치했다. [독립 질문·근거](../data/eval/stack-selection/final_questions_v1.json) · [NVIDIA 독립 응답](../data/eval/stack-selection/nvidia_final_v1) · [Terra 기준선](RAG_stack_selection_report.md)

두 실행이 각각 보고한 토큰을 그대로 적용하면 MiniMax의 환산액이 96.8% 낮다. CLI와 NVIDIA의 입력 토큰 집계에 차이가 있어 MiniMax가 보고한 동일 토큰 수를 양쪽 단가에 적용한 비교도 계산했다. 그 경우 Terra는 1,000건당 $21.51이고 MiniMax는 $1.53으로 단가 차이만으로 92.9% 낮다. 표는 캐시 없는 답변 생성의 추정값이다. 질의 재작성, 재시도, 원 제공사의 토큰화 및 서비스 과금은 별도다. NVIDIA 26.77초는 개발용 엔드포인트 관측치이며 공급자 직접 API의 지연은 미측정이다.

기존 F06 기본 라우팅 불일치는 계속 남아 있다. 이번 답변은 사전 지정한 GitHub 검색 bundle을 사용했다. 비교 코드는 현재 RAG 구현의 OpenAI 호환 답변 경로를 재사용하며, 기존 Python 회귀와 NVIDIA 요청·비용 검증 232개가 통과했다. [F06과 운영 인수 범위](RAG_stack_selection_report.md#실제-검색과-인수-범위)

## 재현

라이브 호출은 프로젝트 Python 3.14 환경에서 `NVIDIA_API_KEY`를 사용한다. `--summary`는 보존 응답과 원 제공사 단가로 오프라인 집계한다. 비용에는 답변 생성 단계의 토큰만 포함된다.

```bash
venv/bin/python -B scripts/compare_rag_models.py --provider nvidia \
  --output-dir data/eval/stack-selection/nvidia_pilot_v1 --summary
venv/bin/python -B scripts/compare_rag_models.py --provider nvidia \
  --model minimaxai/minimax-m3.1-flash \
  --output-dir data/eval/stack-selection/nvidia_final_v1 \
  --final-search data/eval/stack-selection/final_search_v1/search_inputs.jsonl.gz --summary
```
