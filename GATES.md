# Gates: Task 15 검색 품질과 실제 답변 영향 검증

OWNS: src/artagent/retrieval/**, src/artagent/graph/search.py, scripts/*t15*, tests/*t15*, tests/test_rerank.py, docs/T15*, data/eval/t15-rerank/**, GATES.md

Scope: 기존 입력·A0/B0·비저하 기준을 보존한 추가 검색 튜닝, 전체 반복 회귀, 실제 T17 대조와 인계를 수행한다. T16 구현과 CP3 전체 판정은 별도 의존 작업이다.

- [x] G1: 모든 단위·통합 회귀 검사가 성공한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests -q --tb=short
  EXPECT: /[0-9]+ passed(?:, [0-9]+ warnings?)? in [0-9.]+s/
  EVIDENCE: 2026-10-20; 구현 b56e63e5c; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; 1002 passed, 3 warnings in 332.86s (0:05:32); EXPECT 일치; 터미널 최종 요약 SHA256=69960328d246d1750793f885c2b3dba09e4bcb3d8935a67dba507ecf74d1bfb4. 별도 재개 집중 검사 5개 통과.

- [x] G2: 추가 격자에서 원시 증거 감사와 A/B 집계·개별순위 비저하를 통과한 설정이 존재한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -c 'from pathlib import Path; from scripts.t15_evaluation import audit_run; r=audit_run(Path("data/eval/t15-rerank/grid_v5")); assert r["summary_verified"] and r["selected_condition"] is not None; print("GRID_QUALITY_PASS")'
  EXPECT: GRID_QUALITY_PASS
  EVIDENCE: 2026-10-19; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; GRID_QUALITY_PASS 일치. 720개 조건·144000건 전수 감사, R3_c20_k5_min0.5_w0.25 선정. sealed manifest의 새 감사에서도 동일 판정.

- [x] G3: 선정 설정의 실제 검색·채점 600건과 그래프 경로가 3회 동일하고 검색 게이트를 모두 통과한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -c 'from pathlib import Path; from scripts.t15_evaluation import audit_run; r=audit_run(Path("data/eval/t15-rerank/regression_v5")); assert r["record_count"] == 600 and r["repeated"] == "PASS" and all(r["gates"][g]["status"] == "PASS" for g in ("G0","G1","G2","G3","G4")); print("RETRIEVAL_REGRESSION_PASS")'
  EXPECT: RETRIEVAL_REGRESSION_PASS
  EVIDENCE: 2026-10-19; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; RETRIEVAL_REGRESSION_PASS 일치. regression_v5의 600건·3회 동일성·G0~G4 PASS. 실제 답변 G5는 별도 미완료.

- [ ] G4: 필수31개와 모든 문맥 변경 질문의 실제 B0/T15 답변·인용 및 주장 검토가 합격한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/resume_t15_answers.py --check-run data/eval/t15-rerank/t17_v5_resumed_20261020_final --manual-reviews data/eval/t15-rerank/review_v5_resumed_20261020_final/manual_reviews.json
  EXPECT: /"overall_verdict": "PASS"/
  EVIDENCE: 2026-10-20; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=1; EXPECT 불일치; 필수 B0/T15 쌍 누락. 성공129건·미완료9건, 시간 초과에서 첫 오류 중단. stdout/stderr 지문과 원본 연결 검사는 data/eval/t15-rerank/audit_v5/t17_final_command.json 및 *_origins.json에 보존. PASS로 표시하지 않음.

- [x] G5: 기준선·변경 조건·실측 결과·잔여 의존성·재실행 명령이 문서와 커밋에 일치한다
  EVIDENCE: 2026-10-20; 문서의 코드/기준선/720조건/600회귀/실제답변129건/미완료9건/재개명령을 저장 증거와 대조했다. 결과·인계·보완 플랜의 상대 링크 모두 존재. git diff --check exit=0. 최종 답변 게이트 미달과 B0 유지, T16/CP3 별도 미완료를 명시했다.
