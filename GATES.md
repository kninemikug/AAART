# Gates: Task 15 검색 품질과 실제 답변 영향 검증

OWNS: src/artagent/retrieval/**, src/artagent/graph/search.py, scripts/*t15*, tests/*t15*, tests/test_rerank.py, docs/T15*, data/eval/t15-rerank/**, tasks/todo.md, GATES.md

Scope: 기존 입력·A0/B0·비저하 기준을 보존한 추가 검색 튜닝, 전체 반복 회귀, 실제 T17 대조와 인계를 수행한다. T16 구현과 CP3 전체 판정은 별도 의존 작업이다.

- [x] G1: 모든 단위·통합 회귀 검사가 성공한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests -q --tb=short
  EXPECT: /[0-9]+ passed(?:, [0-9]+ warnings?)? in [0-9.]+s/
  EVIDENCE: 2026-10-20; 구현08e484294; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; 1015 passed, 3 warnings in 334.60s (0:05:34); EXPECT 일치; 터미널 요약 SHA256=dc11a767ccae6815c63af0a184052a3bf358380576b5ccf0961f4e5d33cdb4b4. 집중18개 통과.

- [x] G2: 추가 격자에서 원시 증거 감사와 A/B 집계·개별순위 비저하를 통과한 설정이 존재한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -c 'from pathlib import Path; from scripts.t15_evaluation import audit_run; r=audit_run(Path("data/eval/t15-rerank/grid_v5")); assert r["summary_verified"] and r["selected_condition"] is not None; print("GRID_QUALITY_PASS")'
  EXPECT: GRID_QUALITY_PASS
  EVIDENCE: 2026-10-19; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; GRID_QUALITY_PASS 일치. 720개 조건·144000건 전수 감사, R3_c20_k5_min0.5_w0.25 선정. sealed manifest의 새 감사에서도 동일 판정. 2026-10-20 저장 기록 전수 재감사도 GRID_QUALITY_PASS; audit_v6/grid_readonly.json.

- [x] G3: 선정 설정의 실제 검색·채점 600건과 그래프 경로가 3회 동일하고 검색 게이트를 모두 통과한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -c 'from pathlib import Path; from scripts.t15_evaluation import audit_run; r=audit_run(Path("data/eval/t15-rerank/regression_v5")); assert r["record_count"] == 600 and r["repeated"] == "PASS" and all(r["gates"][g]["status"] == "PASS" for g in ("G0","G1","G2","G3","G4")); print("RETRIEVAL_REGRESSION_PASS")'
  EXPECT: RETRIEVAL_REGRESSION_PASS
  EVIDENCE: 2026-10-19; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; RETRIEVAL_REGRESSION_PASS 일치. regression_v5의 600건·3회 동일성·G0~G4 PASS. 당시 실제 답변 G5는 별도 미완료였으며 현재 G4에서 확인한다. 2026-10-20 읽기 전용 재감사도 RETRIEVAL_REGRESSION_PASS; audit_v6/regression_readonly.json.

- [x] G4: 필수31개와 모든 문맥 변경 질문의 실제 B0/T15 답변·인용 및 주장 검토가 합격한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 scripts/resume_t15_answers.py --check-run data/eval/t15-rerank/t17_v5_complete_20261020_r3 --manual-reviews data/eval/t15-rerank/review_v5_complete_20261020/manual_reviews.json
  EXPECT: /"overall_verdict": "PASS"/
  EVIDENCE: 2026-10-20; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; EXPECT 일치; 실제138건·주장/인용검토138건·오류/미검토0; 재사용135건+마지막신규3건. 기존129건의원응답보존과신규성공9건을별도대조. stdout SHA256=1658e4dad0ad91f90422e7bcee25b67e0de3d0baca335a5f691e3a9f1eb1f044; audit_v6/answers.json, answers_command.json, preservation.json.

- [x] G5: 기준선·변경 조건·실측 결과·잔여 의존성·재실행 명령이 문서와 커밋에 일치한다
  EVIDENCE: 2026-10-20; 코드7c78e7893/08e484294·고정기준선·720조건·600회귀·실제138답변/전수검토/최종PASS를 문서·원시증거와 대조했다. 재생성금지와오류중단·기본설정·B미도달3개·T16/CP3범위도명시. 상대링크존재와git diff --check 확인.

- [x] G6: 미응답 질문·문맥·부모 변조를 호출 전에 거부하고 재사용 계보와 실패 판정을 검증한다
  CHECK: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /Users/user/Workspace/Programming/Projects/AAART/venv/bin/python3 -m pytest -p no:cacheprovider tests/test_t15_answer_resume.py -q --tb=short
  EXPECT: /[0-9]+ passed/
  EVIDENCE: 2026-10-20; 08e484294; /bin/zsh, 저장소 루트에서 CHECK 실행; exit=0; 18 passed, 1 warning in 10.07s; EXPECT 일치. 미응답 질문/문맥/부모/manifest/선정 조건과 계보·실패 판정의8개 반례가 보완 전 실패하고 보완 후 통과. 과거 봉인 기록 검증도 통과.

- [x] G7: 검색·평가·답변 재개의 구현을 검토하고 확인된 결함과 잔여 범위를 기록한다
  EVIDENCE: 2026-10-20; docs/T15_review_20261020.md에 정확성·구조·입력/파일·성능·증거를 검토했다. 미응답부모연결/원본계보/실패판정의3개결함은실패테스트로재현후수정. 보완후전체1015개·실제138답변감사PASS. 현재T15검증범위의미해결P1/P2결함은확인되지않으며검색미도달/외부지연/CP3잔여를구분했다.
