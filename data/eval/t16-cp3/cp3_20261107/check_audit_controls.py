#!/usr/bin/env python3
"""저장 증거의 의미 있는 변조를 같은 감사기가 거부하는지 확인한다."""
from copy import deepcopy
import importlib.util
from pathlib import Path

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cp3_audit", OUT / "audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
original_rows = audit.rows
records = original_rows("records.jsonl")


def rejects(label, mutate, check=audit.verify_records):
    modified = deepcopy(records)
    mutate(modified)
    audit.rows = lambda name: modified if name == "records.jsonl" else original_rows(name)
    try:
        check()
    except (AssertionError, ValueError):
        print("REJECTED", label)
    else:
        raise AssertionError("변조를 거부하지 못했습니다: " + label)
    finally:
        audit.rows = original_rows


audit.verify_records()
audit.verify_fallback()
rejects("추가 재검색 예산 초과", lambda r: r[-1]["result"].update(research_count=2))
rejects("미지원 답변 상태 변조", lambda r: r[14]["result"]["response"].update(status="COMPLETED"))
rejects("외부 도구 실행 기록", lambda r: r[0]["calls"][0]["execution"]["validation"].update(additional_tool_count=1))
rejects("원문 세그먼트 변조", lambda r: r[0]["nodes"][0]["update"]["retrieval"]["hits"][0].update(text="원문과 다른 내용"))
rejects("세 번째 검색 시도", lambda r: r[-1]["result"]["trace"].append("SEARCH_GITHUB"), audit.verify_fallback)
print("AUDIT_CONTROLS_VERIFIED")
