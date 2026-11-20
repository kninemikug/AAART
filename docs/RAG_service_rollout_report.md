# GUI·CLI RAG 서비스 적용 검증

GUI Python 브리지와 대화형 CLI의 실행 경로에 로컬 검색·인용 개선을 연결했다. 두 진입점은 같은 설정과 검색 노드를 사용한다. 기본 설정은 `legacy`이며, `ART_RAG_PROFILE=local`에서 영문 UI 명칭 보강, BM25 `20/5/0.5/0.75`, 인용 자동 조립과 원질문 복구가 작동한다. 검색에 사용하는 Chroma 활성 청크로 BM25를 구성하고, 검색 사이에 색인이 바뀌면 기존 점수와 새 청크를 섞은 결과를 반환하지 않는다. `.arp` 생성, ART 편집·렌더링과 GUI JSON 응답 형식은 기존 경로를 따른다. [구현 계획](../tasks/plan.md#후속-계획--rag-서비스-적용)

## 실제 서비스 색인의 원질문 검색

T22 GUI 검증에 사용했던 Chroma 저장소를 복사했다. 컬렉션은 `art_retrieval_t09_v1`, 임베딩은 `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`이다. 활성 청크는 RawPedia 141개와 GitHub 13개이며, 활성 목록 지문은 `f355624b09aba51538de3167aa1fca2032401f6487b2d0c91d9a14deeca8593f`다. CLI와 GUI의 실제 검색 그래프를 답변 전에 중단했고, 같은 프로필에서 두 진입점의 검색어·문서 ID 순위가 문항별로 일치했다. [문항별 결과](../data/eval/rag-service/search_v1)

| 지표 | `legacy` | `local` |
| --- | ---: | ---: |
| 회귀 100문항 원문 재현율 | 92.00% | **97.00%** |
| 회귀 100문항 원문 정밀도 | 27.15% | **29.42%** |
| RawPedia / GitHub 재현율 | 90.00% / 100.00% | **96.25% / 100.00%** |
| 반증 원문 | 5/5 | 5/5 |
| 새 질문의 정답 원문 확보 | 4/6 | **6/6** |
| CLI 준비 후 검색 그래프 p95 | 10.19ms | 33.04ms |
| GUI 준비 후 검색 그래프 p95 | 10.28ms | 32.85ms |
| GUI 그래프의 첫 검색 | 58.20ms | 118.91ms |

Q046·Q070·Q071·Q077·Q078에서 정답 원문을 회복했고, 기준선에서 확보하던 정답 원문은 모두 유지됐다. 새 6문항의 질문·정답 원문·기대 행동은 실행 전에 고정했다. 기존 문서로 만든 새 질문 검증이며 출처 자체를 분리한 홀드아웃과는 별개다. p95는 같은 프로세스에서 반복한 검색 경로이며 GUI 프로세스 시작·답변 지연은 제외했다. [사전 입력](../data/eval/rag-service/questions_v1.json)

154청크 저장소에는 기존 검증 F05–F08의 GitHub 글 4개가 없다. 이 저장소에서 F01–F08의 정답 원문 확보는 3/8에서 4/8로 올랐으며, 새로 확보한 F01의 `Crop`은 1위였다. F08 인용 검증에는 보존 평가에 사용했던 GitHub 글 4개를 동일 규칙으로 추가한 별도 158청크 색인을 사용했다.

## GUI 브리지·CLI 응답 계약

`python -m artagent.gui_bridge`의 JSON 입출력과 `python -m artagent.cli`의 대화 경로를 둘 다 실행했다. F01은 테스트 응답 서버에서 `citation_ids`가 빈 답변을 보내도 본문의 `Crop` 표식으로 인용하고 `COMPLETED`를 반환했다. F08은 이전 실제 MiniMax 응답과 시스템·사용자 프롬프트가 정확히 일치함을 확인한 뒤 그 응답을 재생했다. `local`에서 GUI와 CLI 모두 인용을 포함한 `UNSUPPORTED`를 반환했다. GUI 프로필을 `legacy`로 되돌리면 같은 F08 응답이 기존 인용 불일치 오류로 복귀했다. macOS 패널의 화면은 이 검증 범위 밖이며 실제 Python 브리지 프로세스를 검증했다. [프로세스 실행 결과](../data/eval/rag-service/wire_v1.json)

## MiniMax 실답변과 기본값 판정

NVIDIA의 MiniMax M3.1 Flash로 답변을 새로 생성했다. F01–F08에는 확장 158청크 색인을, 새 S01–S06에는 기존 154청크 서비스 색인을 사용했다. 실험에서는 근거 부족 재검색의 제공처에도 동일한 MiniMax를 지정했다. 서비스의 두 역할 설정은 독립적이다. 첫 순차 실행은 11/14문항에서 기대 상태와 일치했다. HTTP 429가 난 F03·S04·S05만 30초 뒤 최소 12초 간격으로 다시 호출해 모두 복구했다. 대체 모델은 실호출에 사용하지 않았다. 테스트에서는 529의 단일 폴백과 429에서 폴백을 끈 동작, 인증 오류와 기한 소진 시 추가 호출이 없는 동작을 확인했다. [첫 시도](../data/eval/rag-service/answers_v1) · [429 재시도](../data/eval/rag-service/answers_retry_v1) · [요약](../data/eval/rag-service/answers_summary_v1.json)

| 범위 | 재시도 후 기대 상태 | 성공한 그래프 중앙값 |
| --- | ---: | ---: |
| 기존 F01–F08 | **8/8** | 9.66초 |
| 새 S01–S06 | **6/6** | 7.17초 |

같은 F01–F08에서 동일한 MiniMax 모델을 쓴 서비스 개선 전 실호출은 기대 상태 6/8이었다. 이전 실행은 보존 재작성과 BM25 `0.75`를 사용했고, 이번 실행은 원질문과 로컬 용어 보강·인용 조립을 사용했다. 검색어와 문맥까지 포함한 경로 전체의 비교다. F01·F08이 회복됐고 나머지 6문항의 기대 상태는 유지됐다. 같은 문맥으로 서로 다른 답변 모델을 맞비교하는 일은 답변 모델 자체의 기본값을 바꿀 때 별도로 판단한다. [개선 전 실호출 원본](../data/eval/stack-selection/minimax_search_final_v1)

F01은 `Crop`을 인용해 Lock ratio 해제·5:4 설정·Shift 조작을 안내했다. F08은 Resize의 PPI만으로 EXIF 해상도 태그를 바꿀 수 없음을 설명하고 두 원문을 인용했다. 모든 최종 답변의 상태·인용 계약을 확인했다. 답변 생성 성공 16회의 입력 114,287토큰과 출력 3,534토큰을 MiniMax 정규 단가로 환산하면 **$0.01926**이다. 계측에는 답변 재생성의 토큰을 포함했다. 재검색 질의 재작성과 사용량이 없는 실패는 이 환산에서 제외했다. 실제 호출에는 NVIDIA 무료 API를 사용했다. [MiniMax 정규 단가](https://www.minimax.io/blog/minimax-m31f)

첫 서비스 검증에서는 검색과 답변을 선택할 수 있게 연결했다. 기존 운영 색인에 네 GitHub 원문 그룹이 빠져 있고 GUI 검색 그래프 p95가 약 23ms 늘어 검색 기본값은 `legacy`로 유지했다. MiniMax 실답변의 첫 시도에는 429가 세 건 있었고 재시도에서 모두 응답했다. 이 단계의 Python 회귀는 1,528개가 통과했다. 후속 기본 연결에서는 키가 준비된 환경의 RAG 답변 모델을 MiniMax로 설정했다. A-23의 고정 100문항과 아래의 서비스 답변 14문항은 각각 별도 표본이다.

## 서비스 답변 faithfulness

서비스 검증의 14개 최종 MiniMax 실답변을 평가했다. HTTP 429가 났던 문항은 동일 입력의 성공한 재시도를 사용했다. 모델 요청 지문과 최종 표시 답변을 대조하고, 모델에게 실제로 전달한 `[검색 문맥]` 블록만 판정 근거로 삼았다. Codex가 답변을 원자 사실 주장으로 나누고, 같은 주장의 반복은 한 번만 셌다. 조건·범위·주체·확실성이 달라진 표현은 따로 판정했다. 주장이 제출 문맥에 명시돼 있거나 문맥에서 도출되면 지지로 집계했다. 각 판정의 근거 위치와 구절을 보존했다. 문항별 `지지 주장 수 ÷ 전체 사실 주장 수`를 평균한 값이 주 지표다. [RAGAS faithfulness 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/faithfulness/) · [주장별 판정](../data/eval/rag-service/faithfulness_verdicts_v1.jsonl) · [점수 원본](../data/eval/rag-service/faithfulness_summary_v1.json)

| 표본 | 평가 답변 | 문항 평균 faithfulness | 전체 주장 중 지지 |
| --- | ---: | ---: | ---: |
| 서비스 합계 | 14/14 | **94.98%** | **88/92 (95.65%)** |
| F01–F08 회귀 | 8/8 | 97.17% | 58/60 (96.67%) |
| S01–S06 새 질문 | 6/6 | 92.06% | 30/32 (93.75%) |

| 문항 | 지지되지 않은 주장 |
| --- | --- |
| F05 | 잠정 수정이 푸시된 뒤 제보자가 이를 요청했다고 썼다. 근거에는 유지보수자가 제보자에게 테스트를 요청한 기록이 있다. |
| F07 | 문맥이 누수 보고와 접수 답변으로만 구성됐다고 썼다. 문맥에는 제보자가 확인한 우회 방법도 있다. |
| S01 | Long Edge 여백이 긴 변 길이에 비례한다고 썼다. 문맥은 길이를 기준으로 균일한 여백을 쓴다고 설명한다. |
| S02 | 완전 일치 후보가 있을 때 전체 목록에서 촬영 시각이 가장 가까운 것을 고른다고 썼다. 문맥에서 전체 목록 탐색은 완전 일치 후보가 없을 때 적용된다. |

공식 산식을 기존 집계 함수로 실행하고 주장 판정은 단일 평가 결과로 남겼다. T23 고정 100문항의 검색 정밀도·재현율과 보존 Sol 답변의 faithfulness는 T15·T17의 실제 제출 문맥을 사용한 리포트에 함께 기록했다. [T23 통합 리포트](../data/eval/report_v1.md)

```bash
venv/bin/python -B scripts/eval_rag_service_faithfulness.py
```

## 검증용 설정

- `ART_RAG_PROFILE=local`은 로컬 검색과 인용을 켠다. `legacy` 또는 설정 생략은 기존 경로를 사용한다.
- GUI와 CLI는 `NVIDIA_API_KEY`가 준비돼 있으면 RAG 답변에 MiniMax M3.1 Flash를 기본 사용한다. 실행 환경의 값을 우선 읽고, 값이 없으면 실행 중인 Python 코드가 속한 프로젝트의 `.env.local`에서 이 키의 리터럴 할당만 읽는다. 셸 스크립트 실행이나 전역 환경 변경은 없다. 키가 없는 설치는 기존 답변 모델을 쓴다. `ART_RAG_ANSWER_PROVIDER=existing`을 지정하면 키가 있어도 기존 모델을 사용한다. `minimax`를 명시하면 키가 없을 때 답변 오류를 반환한다.
- `ART_RAG_ANSWER_FALLBACK=existing`을 선택하면 `429`, `529`, 요청 타임아웃에서 남은 시간 안에 기존 답변 제공처를 한 번 호출한다. 생략하거나 `none`이면 오류를 반환한다. MiniMax 설정은 근거 부족 재검색의 기존 제공처 설정과 독립적이다.

GUI는 위 설정을 ART 프로그램의 실행 환경에서 상속한다. CLI 예시와 로컬 색인 검증은 다음 명령을 사용한다. 경로 자리에는 기존 검증된 T09 저장소를 지정한다.

```bash
ART_RAG_PROFILE=local PYTHONPATH=src venv/bin/python -m artagent.cli \
  --persist-dir /path/to/t09
venv/bin/python -B scripts/eval_rag_service.py \
  --persist-dir /path/to/t09 --output-dir /tmp/art-rag-service-eval
```

## MiniMax 기본 연결 실호출

별도의 모델 환경변수와 키 환경변수 없이 프로젝트 `.env.local`로 GUI·CLI의 F02 요청을 실행했다. 두 진입점에서 `minimaxai/minimax-m3.1-flash` HTTP 200과 `Metadata Copy Mode` 인용을 확인했다. 저장된 ART 채팅 설정에서도 기존 Python·Chroma 위치를 보존하고 소스 경로만 현재 작업 공간으로 연결했다. 해당 설정의 인수로 Python 브리지를 다시 실행해 MiniMax HTTP 200과 같은 인용을 확인했다. ART는 시작할 때 저장된 채팅 설정을 읽는다. 관련 Python 테스트 108개가 통과했다. [실제 요청 결과](../data/eval/rag-service/default_minimax_v1.json)
