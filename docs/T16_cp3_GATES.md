# Gates: T16 실제 연결 검증

OWNS: docs/T16_cp3_GATES.md, docs/T16_cp3_results.md, data/eval/t16-cp3/**

Scope: 고정 검색 자료와 실제 생성 호출을 연결한 15문항 비교, 단일 재검색, 네이티브 화면의 응답·취소·종료를 검증하고 한계를 기록한다.

- [x] G1: 참조 자료와 일치하는 검색 저장소를 별도로 검증한다.
  CHECK: /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 data/eval/t16-cp3/cp3_20261107/run.py verify-store
  EXPECT: STORE_VERIFIED
  EVIDENCE: 2026-11-07; 저장소 루트; exit=0; STORE_VERIFIED. 선택 참조·재현 증거·154개 청크·원문·메타데이터·벡터 대조. data/eval/t16-cp3/cp3_20261107/store-verification.json.

- [x] G2: 고정 15문항과 두 제품 범위 회귀 질문의 실제 호출·출처·상태·횟수를 검증한다.
  CHECK: /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 data/eval/t16-cp3/cp3_20261107/audit.py records
  EXPECT: RECORDS_VERIFIED
  EVIDENCE: 2026-11-07; 저장소 루트; exit=0; RECORDS_VERIFIED. 15문항·범위 2문항·빈 검색 1문항의 실제 호출과 원문·Git 지문 대조. 코드와 입출력을 검토한 직접 실행이며 별도 자동 검사기 승인을 부여하지 않음. 5개 변조 반례 거부도 확인.

- [x] G3: 실제 근거 부족 요청에서 재작성·검색·답변이 한 번 추가되고 다시 부족하면 종료한다.
  CHECK: /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 data/eval/t16-cp3/cp3_20261107/audit.py fallback
  EXPECT: FALLBACK_VERIFIED
  EVIDENCE: 2026-11-07; 저장소 루트; exit=0; FALLBACK_VERIFIED. 고정 자료에 없는 지정 Issue 통제 질문, 실제 답변 부족→재작성→정상 빈 검색→실제 재답변 부족. research_count=1·검색 2회·답변 2회, 세 번째 검색 반례 거부. GUI 기본 설정의 실제 브리지에서도 같은 trace 확인.

- [x] G4: 15문항의 핵심 사실·인용·제품 범위를 기존 답변과 원문으로 대조한다.
  EVIDENCE: 2026-11-07; docs/T16_cp3_results.md의 질문별 대조표. T11 원응답·고정 근거·실제 세그먼트와 비교해 13개 동등·Q044/Q086 개선. 집중 3개·CP2 양성 5개와 추가 Q010/Q077 범위도 검토. T16만의 개선 효과나 독립 평가셋으로 세지 않음.

- [ ] G5: 네이티브 화면에서 문서 질문·문제 해결·실행 요청 차단·부족 응답과 취소·종료를 관찰한다.
  EVIDENCE: 2026-11-07; 별도 설정의 시작 화면만 확보. window_not_focused 뒤 permission_denied, 실제 AX 창 접근 차단. 사용자에게 접근성 권한 재설정 요청. 브리지 5요청과 REPL 3요청은 통과했으나 실제 화면의 전송·답변 표시·취소·종료를 대신하지 않음. gui-observation.json, gui-startup.png 참조. 대기 상태이며 포기·완료로 처리하지 않음.
