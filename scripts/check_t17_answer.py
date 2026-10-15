#!/usr/bin/env python3
"""Task 17 Slice 1 15개 질문 대조 및 평가 실행기 (Task 17 / A-17).

docs/T17_execution_plan.md §6 및 §8 준수:
- 고정 ID 순서 15개 (Q001, Q004, Q014, Q021, Q033, Q044, Q054, Q063, Q072, Q080, Q084, Q086, Q092, Q093, Q096)
- 기준선 파일 SHA-256 검증 (읽기 전용, 덮어쓰기 금지)
- T11 문맥 재생 (15개) + T14 A (15개) + T14 B (15개) 실제 답변 생성 및 검증
- 수동 3개 (Q001, Q086, Q096), CP2 양성 5개, Q010/Q077 제품 범위 회귀 검증
- data/eval/t17-answer/<run_id>/ 하위에 execution_records.jsonl 및 report.md 생성
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from artagent.answer import get_source_root, normalize_query, sha256_bytes, sha256_str
from artagent.graph.answer import T17_PROMPT_VERSION, answer_standalone, validate_and_project_bundle
from artagent.graph.search import search_hits_to_evidences
from artagent.graph.state import (
    AnswerResult,
    Citation,
    ErrorInfo,
    Evidence,
    RequestContext,
    RetrievalBundle,
)
from artagent.retrieval.types import SearchHit
from artagent.answer_validation import capture_code_state, reference_cases

FIXED_SLICE1_IDS = [
    "Q001", "Q004", "Q014", "Q021", "Q033",
    "Q044", "Q054", "Q063", "Q072", "Q080",
    "Q084", "Q086", "Q092", "Q093", "Q096",
]

# docs/T17_fix_plan.md §7: 필수 19개 수동 검토 타겟 (Q001 x3, Q086 x3, Q096 x3, CP2 x8, Q010 x1, Q077 x1)
REQUIRED_MANUAL_REVIEW_TARGETS: list[tuple[str, str]] = [
    ("Q001", "t11_replay"),
    ("Q001", "t14_a"),
    ("Q001", "t14_b"),
    ("Q086", "t11_replay"),
    ("Q086", "t14_a"),
    ("Q086", "t14_b"),
    ("Q096", "t11_replay"),
    ("Q096", "t14_a"),
    ("Q096", "t14_b"),
    ("Q004", "t14_a"),
    ("Q004", "t14_b"),
    ("Q014", "t14_a"),
    ("Q014", "t14_b"),
    ("Q054", "t14_a"),
    ("Q054", "t14_b"),
    ("Q063", "t14_a"),
    ("Q063", "t14_b"),
    ("Q010", "t14_b_reg_Q010"),
    ("Q077", "t14_b_reg_Q077"),
]

EXPECTED_QUERIES_SHA = "91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8"
EXPECTED_T11_RECORDS_SHA = "5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7"


def verify_file_sha(path: Path, expected_sha: str, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 파일을 찾을 수 없습니다: {path}")
    actual_sha = sha256_bytes(path.read_bytes())
    if actual_sha != expected_sha:
        raise ValueError(
            f"{label} 파일의 SHA-256이 기준선과 일치하지 않습니다: {path} (기대: {expected_sha}, 실제: {actual_sha})"
        )
    return actual_sha


def parse_evidence_from_dict(d: dict[str, Any]) -> Evidence:
    return Evidence(
        chunk_id=d["chunk_id"],
        doc_id=d["doc_id"],
        source_group_id=d["source_group_id"],
        source_type=d["source_type"],
        source_path=d["source_path"],
        source_location=d["source_location"],
        target_url=d["target_url"],
        text=d["text"],
        product_scope=d.get("product_scope", "ART"),
    )


def load_canonical_queries(queries_path: Path) -> dict[str, dict[str, Any]]:
    verify_file_sha(queries_path, EXPECTED_QUERIES_SHA, "질문 원본")
    data = json.loads(queries_path.read_text(encoding="utf-8"))
    return {q["query_id"]: q for q in data.get("queries", [])}


def load_t11_bundles(t11_path: Path) -> dict[str, dict[str, Any]]:
    verify_file_sha(t11_path, EXPECTED_T11_RECORDS_SHA, "T11 실행 기록")
    bundles = {}
    with open(t11_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            qid = rec["query_id"]
            if qid in FIXED_SLICE1_IDS:
                raw_hits = rec.get("retrieval", {}).get("hits", [])
                search_hits = [SearchHit(**h) for h in raw_hits]
                evidences = search_hits_to_evidences(search_hits)
                stypes = {h.source_type for h in search_hits}
                if len(stypes) == 1:
                    sfilter = "RAWPEDIA" if "rawpedia" in stypes else "GITHUB"
                else:
                    sfilter = "ALL"
                bundle = RetrievalBundle(
                    query=rec["input"]["query_normalized"],
                    source_filter=sfilter,
                    hits=evidences,
                    snapshot_ref="t11_baseline_20261014",
                )
                bundles[qid] = {
                    "original_record": rec,
                    "bundle": bundle,
                }
    return bundles


def load_t14_slice1_bundles(slice1_path: Path) -> Tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    bundles_a: dict[str, dict[str, Any]] = {}
    bundles_b: dict[str, dict[str, Any]] = {}

    with open(slice1_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            qid = entry.get("query_id")
            cond = entry.get("condition")
            if qid in FIXED_SLICE1_IDS and cond in ("A", "B"):
                ret = entry.get("retrieval")
                if ret:
                    evidences = [parse_evidence_from_dict(h) for h in ret.get("hits", [])]
                    bundle = RetrievalBundle(
                        query=ret.get("query", ""),
                        source_filter=ret.get("source_filter", "RAWPEDIA"),
                        hits=evidences,
                        snapshot_ref=ret.get("snapshot_ref", "t14_slice1_snapshot"),
                    )
                    data = {
                        "entry": entry,
                        "bundle": bundle,
                    }
                    if cond == "A":
                        bundles_a[qid] = data
                    else:
                        bundles_b[qid] = data
    return bundles_a, bundles_b


def extract_original_run_id(entry: dict[str, Any], default_qid: str = "", default_cond: str = "") -> str:
    plan = entry.get("decision", {}).get("plan", [])
    if plan and isinstance(plan, list) and plan[0].get("step_id"):
        return plan[0]["step_id"]
    if entry.get("request", {}).get("request_id"):
        return entry["request"]["request_id"]
    if entry.get("step_id"):
        return entry["step_id"]
    if default_qid and default_cond:
        return f"{default_qid}_{default_cond}"
    return entry.get("run_id", "")


def run_single_evaluation(
    track: str,
    query_id: str,
    query_info: dict[str, Any],
    bundle: RetrievalBundle,
    original_run_id: str,
    source_root: Path,
    generate_fn: Optional[Callable[..., Any]] = None,
    context: Optional[Any] = None,
    constraints: Optional[list[str]] = None,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).astimezone().isoformat()
    q_original = query_info["query"]
    code_state = capture_code_state(REPO_ROOT)
    input_reference = reference_cases(REPO_ROOT)[query_id, track]["input_reference"]

    observation: dict[str, Any] = {}

    def _obs_cb(rec: dict[str, Any]) -> None:
        observation.update(rec)

    ans, err = answer_standalone(
        query=q_original,
        bundle=bundle,
        context=context,
        constraints=constraints,
        generate=generate_fn,
        source_root=source_root,
        observe=_obs_cb,
    )

    run_id = f"t17_{track}_{query_id}_{int(time.time())}"

    rmeta = observation.get("runtime_meta") or {}
    trace = observation.get("trace") or rmeta.get("_trace")
    is_mock = bool(observation.get("custom_generation")) or bool(rmeta.get("is_mock")) or rmeta.get("llm_provider") in ("mock", "custom")
    provider = rmeta.get("llm_provider")
    model = rmeta.get("model_id") or rmeta.get("model")

    record = {
        "record_schema": "t17-run-v3",
        "runtime": code_state,
        "input_reference": input_reference,
        "run_id": run_id,
        "track": track,
        "query_id": query_id,
        "original_run_id": original_run_id,
        "started_at": started_at,
        "input": {
            "query_original": q_original,
            "query_normalized": normalize_query(q_original),
            "confirmed_context": context,
            "constraints": constraints or [],
        },
        "retrieval": {
            "query": bundle.query,
            "source_filter": bundle.source_filter,
            "snapshot_ref": bundle.snapshot_ref,
            "hits_count": len(bundle.hits),
            "product_scopes": sorted(set(h.product_scope for h in bundle.hits)),
            "hits": [h.__dict__ for h in bundle.hits],
        },
        "prompt": {
            "version": T17_PROMPT_VERSION,
            "system_instruction": observation.get("system_instruction"),
            "user_prompt": observation.get("user_prompt"),
            "prompt_hash": observation.get("prompt_hash"),
        },
        "generation": {
            "call_count": observation["call_count"],
            "request": observation.get("request"),
            "provider": provider,
            "model": model,
            "is_mock": is_mock,
            "runtime_meta": rmeta,
            "trace": trace,
            "usage": observation.get("usage"),
            "raw_response": observation.get("raw_response"),
            "status": ans.status if ans else None,
            "elapsed_ms": observation.get("elapsed_ms"),
        },
        "citations": [c.__dict__ for c in ans.citations] if ans else [],
        "used_citations_provenance": observation.get("used_citations_provenance", []),
        "output": {
            "status": ans.status if ans else None,
            "text": ans.text if ans else None,
            "applicability": ans.applicability if ans else None,
            "actionable_goal": ans.actionable_goal if ans else None,
            "error": err.__dict__ if err else None,
        },
        "verification": {
            "input_matched": True,
            "citations_valid": err is None,
            "manual_review": "pending",
            "review_notes": "",
        },
    }
    return record


def find_manual_review(manual_reviews: Optional[dict[str, Any]], query_id: str, track: str) -> Optional[dict[str, Any]]:
    """수동 검토 딕셔너리에서 (query_id, track)에 해당하는 검토 항목 탐색."""
    if not manual_reviews:
        return None
    for k, v in manual_reviews.items():
        if (v.get("query_id") == query_id and v.get("track") == track) or k == f"run_{query_id}_{track}" or k == f"{query_id}_{track}":
            return v
    return None


def evaluate_gate_b(
    records: list[dict[str, Any]],
    regression_records: Optional[list[dict[str, Any]]] = None,
    manual_reviews: Optional[dict[str, Any]] = None,
    source_root: Optional[Path] = None,
    allow_mock: bool = False,
) -> tuple[str, list[str], list[str]]:
    """Gate B always excludes mock evidence, including compatibility callers."""
    from artagent.answer_validation import evaluate_records
    return evaluate_records(
        records, regression_records or [], manual_reviews or {},
        source_root or REPO_ROOT, REPO_ROOT, REQUIRED_MANUAL_REVIEW_TARGETS,
    )


def generate_comparison_report(
    records: list[dict[str, Any]],
    out_dir: Path,
    q010_reg: Optional[dict[str, Any]] = None,
    q077_reg: Optional[dict[str, Any]] = None,
    manual_reviews: Optional[dict[str, Any]] = None,
    verdict: Optional[str] = None,
    fail_reasons: Optional[list[str]] = None,
    pending_reasons: Optional[list[str]] = None,
) -> str:
    regression_records = []
    if q010_reg:
        regression_records.append(q010_reg)
    if q077_reg:
        regression_records.append(q077_reg)

    if verdict is None:
        verdict, f_reasons, p_reasons = evaluate_gate_b(
            records=records,
            regression_records=regression_records,
            manual_reviews=manual_reviews,
        )
        if fail_reasons is None:
            fail_reasons = f_reasons
        if pending_reasons is None:
            pending_reasons = p_reasons
    else:
        fail_reasons = fail_reasons or []
        pending_reasons = pending_reasons or []

    providers = sorted({r.get("generation", {}).get("provider") for r in records if r.get("generation", {}).get("provider")})
    models = sorted({r.get("generation", {}).get("model") for r in records if r.get("generation", {}).get("model")})
    prompt_versions = sorted({r.get("prompt", {}).get("version") for r in records if r.get("prompt", {}).get("version")})
    has_mock = any(r.get("generation", {}).get("is_mock") for r in records)

    lines = [
        "# Task 17 Slice 1 15개 질문 답변 대조 보고서",
        "",
        f"- 생성일: {datetime.now(timezone.utc).astimezone().isoformat()}",
        f"- 질문 원본 SHA-256: `{EXPECTED_QUERIES_SHA}`",
        f"- T11 기준선 SHA-256: `{EXPECTED_T11_RECORDS_SHA}`",
        f"- 프롬프트 버전: `{', '.join(prompt_versions) if prompt_versions else 't17-answer-v1'}`",
        f"- 생성 모델: `{', '.join(models) if models else 'N/A'}` (제공처: `{', '.join(providers) if providers else 'N/A'}`)",
    ]
    if has_mock:
        lines.append("- **주의**: 모의(mock) 생성 결과가 포함되어 있습니다.")

    lines.extend([
        "",
        "## 1. 15개 전수 실행 결과 요약",
        "",
        "| Query ID | 출처 | T11 상태 / 인용 | T14 A 상태 / 인용 | T14 B 상태 / 인용 |",
        "|---|---|---|---|---|",
    ])

    by_query: dict[str, dict[str, Any]] = {}
    for r in records:
        qid = r.get("query_id")
        trk = r.get("track")
        if qid not in by_query:
            by_query[qid] = {}
        by_query[qid][trk] = r

    for qid in FIXED_SLICE1_IDS:
        t11_rec = by_query.get(qid, {}).get("t11_replay", {})
        t14_a = by_query.get(qid, {}).get("t14_a", {})
        t14_b = by_query.get(qid, {}).get("t14_b", {})

        s11 = t11_rec.get("output", {}).get("status", "N/A")
        c11 = len(t11_rec.get("citations", []))
        sa = t14_a.get("output", {}).get("status", "N/A")
        ca = len(t14_a.get("citations", []))
        sb = t14_b.get("output", {}).get("status", "N/A")
        cb = len(t14_b.get("citations", []))
        stype = t14_b.get("retrieval", {}).get("source_filter") or t11_rec.get("retrieval", {}).get("source_filter") or "RAWPEDIA"

        lines.append(f"| {qid} | {stype} | {s11} ({c11}) | {sa} ({ca}) | {sb} ({cb}) |")

    lines.extend([
        "",
        "## 2. 지정 수동 검토 (Q001, Q086, Q096)",
        "",
        "### Q001 (RawPedia: Auto Levels)",
        "- **기대**: T11/A/B 모두 `SUPPORTED`. 히스토그램 분석 및 Exposure 조정 설명 유지, RawTherapee 참고 범위 유지.",
    ])

    q001_b = by_query.get("Q001", {}).get("t14_b", {})
    q001_text = str(q001_b.get("output", {}).get("text") or "")
    q001_rev = find_manual_review(manual_reviews, "Q001", "t14_b") or {}
    lines.extend([
        f"- **실제 상태 (B)**: `{q001_b.get('output', {}).get('status')}`",
        f"- **실제 인용수**: {len(q001_b.get('citations', []))}",
        f"- **답변 발췌**: {q001_text[:200]}...",
        f"- **수동 검토 상태 (B)**: `{q001_rev.get('status', 'pending')}` (사유: {q001_rev.get('reason', '미검토')})",
        "",
        "### Q086 (GitHub: Discussion #442 마스크 공유)",
        "- **기대**: T11 재생은 `INSUFFICIENT_EVIDENCE` 유지. T14 A/B는 #442 본문과 댓글(Linked mask)로 `SUPPORTED` 기대.",
    ])

    q086_t11 = by_query.get("Q086", {}).get("t11_replay", {})
    q086_b = by_query.get("Q086", {}).get("t14_b", {})
    q086_text = str(q086_b.get("output", {}).get("text") or "")
    q086_t11_rev = find_manual_review(manual_reviews, "Q086", "t11_replay") or {}
    q086_b_rev = find_manual_review(manual_reviews, "Q086", "t14_b") or {}
    lines.extend([
        f"- **실제 상태 (T11)**: `{q086_t11.get('output', {}).get('status')}`",
        f"- **수동 검토 상태 (T11)**: `{q086_t11_rev.get('status', 'pending')}` (사유: {q086_t11_rev.get('reason', '미검토')})",
        f"- **실제 상태 (B)**: `{q086_b.get('output', {}).get('status')}`",
        f"- **실제 인용수 (B)**: {len(q086_b.get('citations', []))}",
        f"- **답변 발췌 (B)**: {q086_text[:250]}...",
        f"- **수동 검토 상태 (B)**: `{q086_b_rev.get('status', 'pending')}` (사유: {q086_b_rev.get('reason', '미검토')})",
        "",
        "### Q096 (GitHub: Issue #500 JXL 설정)",
        "- **기대**: T11/A/B 모두 `UNSUPPORTED`. JXL 품질 슬라이더는 지원되지 않으며 visually lossless 고정임을 설명.",
    ])

    q096_b = by_query.get("Q096", {}).get("t14_b", {})
    q096_text = str(q096_b.get("output", {}).get("text") or "")
    q096_rev = find_manual_review(manual_reviews, "Q096", "t14_b") or {}
    lines.extend([
        f"- **실제 상태 (B)**: `{q096_b.get('output', {}).get('status')}`",
        f"- **실제 인용수 (B)**: {len(q096_b.get('citations', []))}",
        f"- **답변 발췌 (B)**: {q096_text[:200]}...",
        f"- **수동 검토 상태 (B)**: `{q096_rev.get('status', 'pending')}` (사유: {q096_rev.get('reason', '미검토')})",
        "",
        "## 3. CP2 양성 5개 (Q001, Q004, Q014, Q054, Q063) 검토",
        "",
        "| Query ID | T14 A 상태 / 인용 | T14 B 상태 / 인용 | 검토 상태 (B) |",
        "|---|---|---|---|",
    ])

    cp2_ids = ["Q001", "Q004", "Q014", "Q054", "Q063"]
    for qid in cp2_ids:
        a_rec = by_query.get(qid, {}).get("t14_a", {})
        b_rec = by_query.get(qid, {}).get("t14_b", {})
        sa = a_rec.get("output", {}).get("status")
        ca = len(a_rec.get("citations", []))
        sb = b_rec.get("output", {}).get("status")
        cb = len(b_rec.get("citations", []))
        b_rev = find_manual_review(manual_reviews, qid, "t14_b") or {}
        rev_st = b_rev.get("status", "pending")
        lines.append(f"| {qid} | {sa} ({ca}) | {sb} ({cb}) | `{rev_st}` |")

    lines.extend([
        "",
        "## 4. Q010 / Q077 제품 범위 추가 회귀",
        "",
    ])

    if q010_reg:
        lines.append(f"- **Q010 (B)**: 상태 `{q010_reg.get('output', {}).get('status')}`, 적용 범위 `{q010_reg.get('output', {}).get('applicability')}` (RawTherapee 근거 보존)")
    else:
        lines.append("- **Q010 (B)**: [기록 누락]")
    if q077_reg:
        lines.append(f"- **Q077 (B)**: 상태 `{q077_reg.get('output', {}).get('status')}`, 적용 범위 `{q077_reg.get('output', {}).get('applicability')}` (RawTherapee 근거 보존)")
    else:
        lines.append("- **Q077 (B)**: [기록 누락]")

    lines.extend([
        "",
        "## 5. 게이트 B 판정",
        f"- **최종 판정**: `{verdict}`",
    ])

    if fail_reasons:
        lines.append("\n### 실패 사유 (FAIL)")
        for fr in fail_reasons:
            lines.append(f"- {fr}")

    if pending_reasons:
        lines.append("\n### 미결/보류 사유 (PENDING)")
        for pr in pending_reasons:
            lines.append(f"- {pr}")

    lines.append("")
    report_content = "\n".join(lines)
    (out_dir / "report.md").write_text(report_content, encoding="utf-8")
    return report_content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-set", type=Path, default=REPO_ROOT / "docs/search_eval_queries.json")
    parser.add_argument("--t11-records", type=Path, default=REPO_ROOT / "docs/T11_execution_records.jsonl")
    parser.add_argument("--slice1-search", type=Path, default=REPO_ROOT / "data/eval/t14-conn/conn_20261015_pr/slice1_search.jsonl")
    parser.add_argument("--ab-records", type=Path, default=REPO_ROOT / "data/eval/t14-conn/conn_20261015_pr/ab_records.jsonl")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--mock-llm", action="store_true", help="API 호출 없이 모의 응답으로 실행")

    parser.add_argument("--manual-reviews", type=Path, default=None, help="수동 검토 JSON 파일 경로")
    parser.add_argument("--validate", type=Path, default=None, help="생성 없이 기존 실행 폴더만 오프라인 재검증")
    parser.add_argument("--validation-output", type=Path, help="입력 폴더 밖의 새 JSON 파일에 검증 결과 저장")

    args = parser.parse_args()

    if args.validate:
        val_dir = args.validate.resolve()
        if args.validation_output:
            audit_path = args.validation_output.resolve()
            if audit_path.is_relative_to(val_dir) or audit_path.exists():
                parser.error("검증 결과는 입력 폴더 밖의 새 파일에 저장해야 합니다.")
        rec_file = val_dir / "execution_records.jsonl"
        if not rec_file.is_file():
            print(f"오류: 실행 기록 파일이 없습니다: {rec_file}")
            return 1
        with open(rec_file, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        reg_records = []
        reg_file = val_dir / "regression_records.jsonl"
        if reg_file.is_file():
            with open(reg_file, "r", encoding="utf-8") as f:
                reg_records = [json.loads(line) for line in f]
        manual_reviews = {}
        rev_file = args.manual_reviews or (val_dir / "manual_reviews.json")
        if rev_file.is_file():
            with open(rev_file, "r", encoding="utf-8") as f:
                manual_reviews = json.load(f)
        verdict, fail_reasons, pending_reasons = evaluate_gate_b(
            records=records,
            regression_records=reg_records,
            manual_reviews=manual_reviews,
            source_root=REPO_ROOT,
            allow_mock=False,
        )
        if args.validation_output:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("x", encoding="utf-8") as stream:
                json.dump({
                    "verdict": verdict, "fail_reasons": fail_reasons,
                    "pending_reasons": pending_reasons,
                    "input_hashes": {p.name: sha256_bytes(p.read_bytes()) for p in val_dir.iterdir() if p.is_file()},
                    "validator": capture_code_state(REPO_ROOT),
                }, stream, ensure_ascii=False, indent=2)
        print(f"오프라인 재검증 완료 ({val_dir})")
        print(f"게이트 B 판정: {verdict}")
        if fail_reasons:
            print("실패 사유:")
            for fr in fail_reasons:
                print(f"  - {fr}")
        if pending_reasons:
            print("미결 사유:")
            for pr in pending_reasons:
                print(f"  - {pr}")
        if verdict == "PASS":
            return 0
        elif verdict == "PENDING":
            return 2
        else:
            return 1

    # 1. 원본 파일 SHA 무결성 검증
    verify_file_sha(args.query_set, EXPECTED_QUERIES_SHA, "질문 원본")
    verify_file_sha(args.t11_records, EXPECTED_T11_RECORDS_SHA, "T11 실행 기록")
    reference_cases(REPO_ROOT)

    queries = load_canonical_queries(args.query_set)
    t11_bundles = load_t11_bundles(args.t11_records)
    t14_a_bundles, t14_b_bundles = load_t14_slice1_bundles(args.slice1_search)

    run_tag = f"run_{int(time.time())}"
    out_dir = args.out_dir or (REPO_ROOT / f"data/eval/t17-answer/{run_tag}")
    if out_dir.exists():
        parser.error("기존 실행 폴더에 추가 기록하지 않습니다. 새 출력 경로를 지정하십시오.")
    out_dir.mkdir(parents=True)

    records_file = out_dir / "execution_records.jsonl"
    reg_records_file = out_dir / "regression_records.jsonl"

    all_records: list[dict[str, Any]] = []

    generate_fn = None
    if args.mock_llm:
        def _mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> tuple[str, None, dict[str, Any]]:
            cids = list(ctx_cits.keys())
            if not cids:
                resp = json.dumps({
                    "status": "INSUFFICIENT_EVIDENCE",
                    "answer": "모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.",
                    "citation_ids": [],
                })
            else:
                first_cid = cids[0]
                if "jxl" in q_norm.lower() or "500" in q_norm:
                    resp = json.dumps({
                        "status": "UNSUPPORTED",
                        "answer": f"JXL 품질 슬라이더는 지원되지 않습니다 [{first_cid}].",
                        "citation_ids": [first_cid],
                    })
                else:
                    resp = json.dumps({
                        "status": "SUPPORTED",
                        "answer": f"질문에 대한 근거 답변입니다 [{first_cid}].",
                        "citation_ids": [first_cid],
                    })
            return resp, None, {"llm_provider": "mock", "is_mock": True, "model_id": "mock-llm"}
        generate_fn = _mock_gen

    source_root = Path(".").resolve()

    print(f"=== Task 17 Slice 1 15개 질문 대조 시작 (출력: {out_dir}) ===")

    # Track 1: T11 Context Replay (15개)
    print("\n--- Track 1: T11 Context Replay (15개) ---")
    for qid in FIXED_SLICE1_IDS:
        q_info = queries[qid]
        t11_data = t11_bundles[qid]
        rec = run_single_evaluation(
            track="t11_replay",
            query_id=qid,
            query_info=q_info,
            bundle=t11_data["bundle"],
            original_run_id=t11_data["original_record"]["run_id"],
            source_root=source_root,
            generate_fn=generate_fn,
        )
        all_records.append(rec)
        with open(records_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        status = rec["output"]["status"]
        c_count = len(rec["citations"])
        print(f"[{qid} T11] status={status}, citations={c_count}")

    # Track 2: T14 A (15개)
    print("\n--- Track 2: T14 A (off, 15개) ---")
    for qid in FIXED_SLICE1_IDS:
        q_info = queries[qid]
        t14_data = t14_a_bundles[qid]
        rec = run_single_evaluation(
            track="t14_a",
            query_id=qid,
            query_info=q_info,
            bundle=t14_data["bundle"],
            original_run_id=extract_original_run_id(t14_data["entry"], default_qid=qid, default_cond="A"),
            source_root=source_root,
            generate_fn=generate_fn,
        )
        all_records.append(rec)
        with open(records_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        status = rec["output"]["status"]
        c_count = len(rec["citations"])
        print(f"[{qid} A] status={status}, citations={c_count}")

    # Track 3: T14 B (15개)
    print("\n--- Track 3: T14 B (on, 15개) ---")
    for qid in FIXED_SLICE1_IDS:
        q_info = queries[qid]
        t14_data = t14_b_bundles[qid]
        rec = run_single_evaluation(
            track="t14_b",
            query_id=qid,
            query_info=q_info,
            bundle=t14_data["bundle"],
            original_run_id=extract_original_run_id(t14_data["entry"], default_qid=qid, default_cond="B"),
            source_root=source_root,
            generate_fn=generate_fn,
        )
        all_records.append(rec)
        with open(records_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        status = rec["output"]["status"]
        c_count = len(rec["citations"])
        print(f"[{qid} B] status={status}, citations={c_count}")

    # Q010 & Q077 B bundle regression
    q010_reg = None
    q077_reg = None
    regression_records: list[dict[str, Any]] = []
    if args.ab_records.is_file():
        print("\n--- Q010 / Q077 B bundle regression check ---")
        with open(args.ab_records, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                qid = entry.get("query_id")
                cond = entry.get("condition")
                if qid in ("Q010", "Q077") and cond == "B":
                    ret = entry.get("retrieval")
                    if ret:
                        evidences = [parse_evidence_from_dict(h) for h in ret.get("hits", [])]
                        b = RetrievalBundle(
                            query=ret.get("query", ""),
                            source_filter=ret.get("source_filter", "RAWPEDIA"),
                            hits=evidences,
                            snapshot_ref=ret.get("snapshot_ref", "t14_ab_snapshot"),
                        )
                        q_info = queries[qid]
                        r = run_single_evaluation(
                            track=f"t14_b_reg_{qid}",
                            query_id=qid,
                            query_info=q_info,
                            bundle=b,
                            original_run_id=extract_original_run_id(entry, default_qid=qid, default_cond="B"),
                            source_root=source_root,
                            generate_fn=generate_fn,
                        )
                        regression_records.append(r)
                        with open(reg_records_file, "a", encoding="utf-8") as f:
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                            f.flush()
                        if qid == "Q010":
                            q010_reg = r
                        else:
                            q077_reg = r
                        print(f"[{qid} B reg] status={r['output']['status']}, scope={r['output']['applicability']}")

    manual_reviews = {}
    if args.manual_reviews and args.manual_reviews.is_file():
        with open(args.manual_reviews, "r", encoding="utf-8") as f:
            manual_reviews = json.load(f)

    verdict, fail_reasons, pending_reasons = evaluate_gate_b(
        records=all_records,
        regression_records=regression_records,
        manual_reviews=manual_reviews,
        source_root=source_root,
        allow_mock=False,
    )

    # Generate comparison report
    report_text = generate_comparison_report(
        records=all_records,
        out_dir=out_dir,
        q010_reg=q010_reg,
        q077_reg=q077_reg,
        manual_reviews=manual_reviews,
        verdict=verdict,
        fail_reasons=fail_reasons,
        pending_reasons=pending_reasons,
    )
    print(f"\n평가 완료: {records_file}")
    print(f"보고서 완료: {out_dir / 'report.md'}")
    print(f"게이트 B 판정: {verdict}")

    if verdict == "PASS":
        return 0
    elif verdict == "PENDING":
        return 2
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
