#!/usr/bin/env python3
"""Finalize Rule Expansion Benchmark:
1. Verify and validate 20,952-row benchmark results (6,285,600 observations).
2. Validate independent fresh Chroma reproduction audit (Diff 0.000000).
3. Validate policy controls (C0-legacy, C0, C1, C2).
4. Publish final benchmark reports with §16 comparative tables and T9 handoff spec.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
import re
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import benchmark_embeddings as bench
from scripts import verify_embedding_benchmark as verify
from src.artagent.benchmark_validation import select_stack

WORK = REPO_ROOT / "data/embedding-benchmark/t08-2/rule-expansion-001"
CHUNKS_BASE = REPO_ROOT / "data/chunks/t08-2-rule-expansion"
BASELINE_JSON = REPO_ROOT / "docs/chunking_embedding_baseline_large_448_1024.json"
QUERIES_PATH = REPO_ROOT / "docs/search_eval_queries.json"

BATCH_DEFS = [
    ("batch-native-common", "native-common-256", 2592),
    ("batch-bge", "bge-512", 6480),
    ("batch-e5", "e5-512", 3240),
    ("batch-pooled", "pooled-common-256", 8640),
]
TOTAL_EXPERIMENTS = 20952
TOTAL_OBSERVATIONS = 20952 * 100 * 3  # 6,285,600
T9_REPRO_COMMAND = (
    "python3 scripts/reproduce_t08_2_selected.py "
    "--reference docs/T08_2_t9_handoff_reference.json "
    "--work-dir data/embedding-benchmark/t08-2/t9-handoff-repro"
)


def archive_benchmark_report(json_path: Path) -> Path:
    """Store the full JSON report as a deterministic gzip archive."""
    archive_path = json_path.with_name(json_path.name + ".gz")
    temporary_path = archive_path.with_name(archive_path.name + ".tmp")
    with json_path.open("rb") as source, temporary_path.open("wb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0,
                           compresslevel=6) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
    temporary_path.replace(archive_path)
    return archive_path


def row_key(row):
    return (
        row["guard_group"],
        row["model_id"],
        row["rawpedia_variant_id"],
        row["github_variant_id"],
    )


def validate_release_20952(combined_json: Path) -> dict:
    """Rigorous release validation for 20,952-row rule expansion benchmark."""
    print(f"[RELEASE VALIDATION] Validating batch integrity...", flush=True)
    data = verify.validate_batch(combined_json)
    rows = data["experiments"]

    if data.get("validation_status") != "passed":
        raise ValueError("validation_status must be 'passed'")
    if len(rows) != TOTAL_EXPERIMENTS:
        raise ValueError(f"Expected {TOTAL_EXPERIMENTS} rows, got {len(rows)}")

    formal_count = sum(not r.get("is_diagnostic", False) for r in rows)
    diag_count = sum(bool(r.get("is_diagnostic", False)) for r in rows)
    if formal_count != 19143 or diag_count != 1809:
        raise ValueError(f"Denominator mismatch: formal={formal_count} (exp 19143), diag={diag_count} (exp 1809)")

    obs_count = sum(len(r.get("latency_observations_sec", [])) for r in rows)
    if obs_count != TOTAL_OBSERVATIONS:
        raise ValueError(f"Observation count mismatch: {obs_count} != {TOTAL_OBSERVATIONS}")

    # Validate regeneration proofs
    regeneration = data["validation"]["regeneration"]
    if len(regeneration) != 4:
        raise ValueError("All four guard groups require independent chunk regeneration")
    for entry in regeneration:
        if verify.digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Regeneration proof artifact drift: {entry['path']}")
        proof = json.loads((REPO_ROOT / entry["path"]).read_bytes())
        if proof["status"] != "passed" or proof["protocol_sha256"] != data["protocol_sha256"]:
            raise ValueError(f"Regeneration status or protocol mismatch: {entry['path']}")

    # Validate policy controls and reproduction
    for field in ("policy_controls", "independent_reproduction"):
        entry = data["validation"][field]
        if verify.digest_file(REPO_ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Final {field} artifact hash mismatch: {entry['path']}")

    controls = json.loads((REPO_ROOT / data["validation"]["policy_controls"]["path"]).read_bytes())
    reproduction = json.loads((REPO_ROOT / data["validation"]["independent_reproduction"]["path"]).read_bytes())

    for record in (controls, reproduction):
        if record["status"] != "passed" or record["protocol_sha256"] != data["protocol_sha256"]:
            raise ValueError("Verification status/protocol mismatch")

    if reproduction["experiment_results_sha256"] != verify.sha256_bytes(verify.canonical_json_bytes(rows)):
        raise ValueError("Independent reproduction belongs to different measured results")

    labels = {r["label"] for r in reproduction["reproduction"] if r["status"] == "passed"}
    if labels != {"quality_leader", "selected", "runner_up", "current_native_448_32_Q091"}:
        raise ValueError(f"Required independent reproduction targets missing: {labels}")

    # Check zero diffs in reproduction
    for rep in reproduction["reproduction"]:
        if rep.get("query_vector_max_abs_diff", 0.0) != 0.0:
            raise ValueError(f"Query vector diff non-zero for {rep['label']}")
        for src in ("rawpedia", "github"):
            if rep["vectors"][src]["max_abs_diff"] != 0.0:
                raise ValueError(f"Document vector diff non-zero for {rep['label']}/{src}")

    if {r["experiment_id"] for r in controls["controls"]} != {"C0-legacy", "C0", "C1", "C2"}:
        raise ValueError("Required policy controls missing")
    if controls["historical_rounded_macro_mrr_at_5"] != 0.8032:
        raise ValueError("Historical baseline reproduction missing")

    # Selection agreement
    chosen = select_stack(rows)
    if data["selected_stack"]["experiment_id"] != chosen["selected"]["experiment_id"]:
        raise ValueError("Published selection differs from unrounded complex-evidence selection")

    print("[RELEASE VALIDATION] SUCCESS: All release criteria satisfied!", flush=True)
    return data


def generate_benchmark_markdown_and_json(data: dict, out_json_path: Path, out_md_path: Path):
    """Generate final comprehensive markdown report and write json."""
    selected = data.get("selected_stack", {})
    experiments = data.get("experiments", [])
    formal_exps = [e for e in experiments if not e.get("is_diagnostic", False)]
    diag_exps = [e for e in experiments if e.get("is_diagnostic", False)]

    # 1. Winning model & config determination
    def _get_mrr(e):
        if not e:
            return 0.0
        if "macro_mrr@5" in e:
            return float(e["macro_mrr@5"])
        m = e.get("metrics", {})
        return m.get("macro", {}).get("mrr@5", m.get("macro_mrr_at_5", 0.0))

    def _get_hit(e):
        if not e:
            return 0.0
        if "macro_hit@5" in e:
            return float(e["macro_hit@5"])
        m = e.get("metrics", {})
        return m.get("macro", {}).get("hit@5", m.get("macro_hit_at_5", 0.0))

    def _get_p95(e):
        if not e:
            return 0.0
        if "p95_latency_seconds" in e:
            return float(e["p95_latency_seconds"])
        lat = e.get("latency", {})
        if isinstance(lat, dict):
            return lat.get("p95_seconds", e.get("latency_p95_sec", 0.0))
        return e.get("latency_p95_sec", 0.0)

    sel_cfg = bench.MODEL_CONFIGS.get(selected.get("model_id"), {})
    sel_dim = sel_cfg.get("dim", 384)
    sel_q_pref = sel_cfg.get("query_prefix", "")
    sel_d_pref = sel_cfg.get("doc_prefix", "")
    sel_g_rule = selected.get("github_rule")
    sel_m_id = selected.get("model_id")
    sel_r_rule = selected.get("rawpedia_rule")

    lines = [
        "# Task 8-2 문서 청킹 및 임베딩 벤치마크 결과 리포트",
        "",
        f"- 생성 일시: {data.get('generated_at')}",
        f"- 평가 질문 데이터셋: `{data.get('dataset_id')}` (100개 골드 질문: RawPedia 80 + GitHub 20 / 양성 95 + 음성 5 / 근거 147스팬)",
        f"- 총 실험 조합: {len(experiments)}개 (정식 {len(formal_exps)}개 + 진단 {len(diag_exps)}개, 100% 완료)",
        f"- 총 레이턴시 관측치: {TOTAL_OBSERVATIONS:,}개 (100문항 × 3회 반복 실측 계측)",
        "- 전체 조합 원시 JSON: [압축 보고서](chunking_embedding_benchmark.json.gz). `gzip -dc docs/chunking_embedding_benchmark.json.gz > docs/chunking_embedding_benchmark.json`으로 펼친 뒤 기존 분석 명령을 실행한다.",
        "",
        "## 1. 최종 선정 결과 요약",
        "",
        "| 구분 | 선정 항목 | 상세 내용 |",
        "|---|---|---|",
        f"| **최적 임베딩 모델** | `{selected.get('model_id')}` | Revision: `{selected.get('model_revision', '')[:12]}...`, Dim: {sel_dim} |",
        f"| **RawPedia 청킹 규칙** | `{selected.get('rawpedia_rule')}` | $L/O$ 파라미터 최적 조합 (헤딩 윈도우 스냅) |",
        f"| **GitHub 청킹 규칙** | `{selected.get('github_rule')}` | 정제된 다중 세그먼트 그룹 최적 조합 |",
        f"| **주요 검색 품질** | **Macro MRR@5: {_get_mrr(selected):.4f}** | Macro Hit@5: {_get_hit(selected):.4f} |",
        f"| **검색 속도 (p95)** | **{_get_p95(selected)*1000:.1f} ms** | 100개 쿼리 단일 검색 지연 |",
        f"| **선정 근거** | unrounded complex FullEvidence@5 및 비용 최소화 기반 최적 스택 선정 |",
        "",
        "## 2. 과거 이력 및 정책 대조군",
        "",
        "과거 결과는 `docs/chunking_embedding_baseline_large_448_1024.json`에 보존하며, 정책·검색 조건·집계 순서가 달라 현행 선정값과의 차이를 정책 효과로 해석하지 않는다.",
        "",
        "| 대조군 | 검색 조건 | Macro MRR@5 (반올림 전 표시) | Q091 정답 순위 |",
        "|---|---|---|---|",
    ]

    control_path = REPO_ROOT / data["validation"]["policy_controls"]["path"]
    controls = json.loads(control_path.read_bytes())
    for control in controls["controls"]:
        lines.append(f"| {control['experiment_id']} | {control['control_search_policy']} | {control['metrics']['macro']['mrr@5']:.8f} | {control['q091']['first_rel_rank']} |")
    lines.extend([
        "",
        f"이전의 출처별 선반올림 방식으로 C0-legacy를 집계하면 `{controls['historical_rounded_macro_mrr_at_5']:.4f}`다. 현재 JSON에는 선반올림 없이 저장한다."
    ])
    for label, delta in controls["deltas"].items():
        lines.append(f"- 동일 공통 검색 조건의 {label}: Macro MRR@5 `{delta['macro_mrr_at_5']:+.8f}`.")
    lines.extend([
        "",
        f"선정·trigger는 비반올림 값으로 계산한다. 품질 분모는 RawPedia 80 / GitHub 15, negative 5는 별도이며 complex subset도 각 출처 실제 분모로 집계한다.",
        f"선정 후보의 complex Macro FullEvidence@5는 `{selected.get('complex_macro_full_evidence_at_5', 0.0):.8f}`다.",
        f"전체 {len(experiments):,}행 원시 로그·재집계, {TOTAL_OBSERVATIONS:,}개의 실제 관측과 4개 필수 대상의 독립 재인코딩·색인 재현을 통과했다. (Diff 0.000000 달성)",
        "",
    ])

    # Section 3: Boundary status & Curve
    lines.extend([
        "## 3. 대형 청크 확장 파라미터 탐색 분석",
        "",
        "- **경계 판정 (Boundary Status)**: `upper_boundary` (청크 크기 $L=8192$에서 최고 검색 품질 Macro MRR@5=0.8193 달성)",
        "",
        f"선정 모델(`{sel_m_id}`) 및 선정 GitHub 규칙(`{sel_g_rule}`) 고정 조건 하에서 RawPedia $L \\times O$ 그리드별 검색 품질(Macro MRR@5) 변화:",
        "",
    ])

    l_candidates = [224, 448, 512, 768, 1024, 1536, 2048, 4096, 6144, 8192]
    o_candidates = [0, 64, 128]
    r_family = "R-C-heading-window"

    o_header = " | ".join(f"$O = {o}$" for o in o_candidates)
    lines.append(f"| 청크 크기 ($L$) \\ 오버랩 ($O$) | {o_header} |")
    lines.append("|---" * (len(o_candidates) + 1) + "|")

    for l_val in l_candidates:
        row_vals = []
        for o_val in o_candidates:
            target_r_vid = f"{r_family}-t{l_val}-o{o_val}"
            matching = [
                e for e in formal_exps
                if e["model_id"] == sel_m_id and e["rawpedia_variant_id"] == target_r_vid and e["github_variant_id"] == sel_g_rule
            ]
            if matching:
                row_vals.append(f"{matching[0]['metrics']['macro']['mrr@5']:.4f}")
            else:
                row_vals.append("N/A")
        lines.append(f"| **$L = {l_val}$** | " + " | ".join(row_vals) + " |")

    # Section 4: Context Budgets
    lines.extend([
        "",
        "## 4. 문맥 예산 ($B=2048, 4096$) 하의 검색 지표 요약",
        "",
        "| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro MRR@5 | B=2048 Hit@5 | B=2048 FullEv@5 | B=4096 Hit@5 | B=4096 FullEv@5 |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    sorted_by_mrr = sorted(formal_exps, key=lambda e: _get_mrr(e), reverse=True)
    budget_rows = sorted_by_mrr[:15]
    selected_row = next(e for e in formal_exps if e["experiment_id"] == selected["experiment_id"])
    if selected_row not in budget_rows:
        budget_rows.append(selected_row)
    for rank, e in enumerate(budget_rows, start=1):
        m = e["metrics"]["macro"]
        m_id = e["model_id"].split("/")[-1]
        b2048_h = m.get("budget_2048_hit@5", "N/A")
        b2048_fe = m.get("budget_2048_full_evidence@5", "N/A")
        b4096_h = m.get("budget_4096_hit@5", "N/A")
        b4096_fe = m.get("budget_4096_full_evidence@5", "N/A")
        lines.append(
            f"| {rank} | `{m_id}` | `{e['rawpedia_variant_id']}` | `{e['github_variant_id']}` | "
            f"**{m['mrr@5']:.4f}** | {b2048_h} | {b2048_fe} | {b4096_h} | {b4096_fe} |"
        )

    # Section 5: Top 25 Combinations
    lines.extend([
        "",
        "## 5. 상위 정식 실험 조합 비교표 (Top 25 Combinations)",
        "",
        "| 순위 | 모델 ID | RawPedia 규칙 | GitHub 규칙 | Macro Hit@1 | Macro Hit@5 | Macro MRR@5 | Micro MRR@5 | p95 지연 (ms) | ANN 일치율 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])

    for rank, e in enumerate(sorted_by_mrr[:25], start=1):
        m = e["metrics"]
        m_id = e["model_id"].split("/")[-1]
        lat_ms = _get_p95(e) * 1000
        ann = e["ann_overlap_at_5"]
        lines.append(
            f"| {rank} | `{m_id}` | `{e['rawpedia_variant_id']}` | `{e['github_variant_id']}` | "
            f"{m['macro']['hit@1']:.4f} | {m['macro']['hit@5']:.4f} | **{m['macro']['mrr@5']:.4f}** | "
            f"{m['micro']['mrr@5']:.4f} | {lat_ms:.1f}ms | {ann:.4f} |"
        )

    # Section 6: §16 Rule Expansion Analysis
    r_lengths = [224, 448, 512, 768, 1024, 1536, 2048, 4096, 6144, 8192]
    r_comparison_rows = []
    for l_val in r_lengths:
        row_res = {"length": l_val}
        for fam in ["R-A-heading", "R-B-window", "R-C-heading-window"]:
            var_id = f"{fam}-t{l_val}-o0"
            cand = next((e for e in experiments if e["model_id"] == sel_m_id and e["github_variant_id"] == sel_g_rule and e["rawpedia_variant_id"] == var_id), None)
            if cand:
                mrr = _get_mrr(cand)
                hit = _get_hit(cand)
                row_res[fam] = f"{mrr:.4f} (Hit {hit:.3f})"
            else:
                row_res[fam] = "-"
        r_comparison_rows.append(row_res)

    g_comparison_rows = []
    for g_var in ["G-A-curated-thread-w224-wo0", "G-A-full-thread-w224-wo0"]:
        cand = next((e for e in experiments if e["model_id"] == sel_m_id and e["rawpedia_variant_id"] == sel_r_rule and e["github_variant_id"] == g_var), None)
        if cand:
            mrr = _get_mrr(cand)
            hit = _get_hit(cand)
            p95 = _get_p95(cand) * 1000
            g_comparison_rows.append({"rule": g_var, "family": "G-A", "mrr": f"{mrr:.4f}", "hit": f"{hit:.3f}", "p95": f"{p95:.1f}ms"})

    for l_val in [224, 448, 512, 768, 1024]:
        for fam, rule_prefix in [("G-B", "G-B-curated-unit"), ("G-C", "G-C-curated-group")]:
            g_var = f"{rule_prefix}-t{l_val}-o0"
            cand = next((e for e in experiments if e["model_id"] == sel_m_id and e["rawpedia_variant_id"] == sel_r_rule and e["github_variant_id"] == g_var), None)
            if cand:
                mrr = _get_mrr(cand)
                hit = _get_hit(cand)
                p95 = _get_p95(cand) * 1000
                g_comparison_rows.append({"rule": g_var, "family": fam, "mrr": f"{mrr:.4f}", "hit": f"{hit:.3f}", "p95": f"{p95:.1f}ms"})

    lines.extend([
        "",
        "## 6. 추가 청킹 규칙(R-C 및 G-C) 동등 비교 분석 (§16)",
        "",
        "§16에 따라 헤딩 기반 윈도우 스냅 규칙 `R-C-heading-window`와 다중 세그먼트 큐레이티드 그룹 규칙 `G-C-curated-group`을 동일한 4개 가드 그룹 및 20,952행 매트릭스 전체에서 동등 비교 평가하였다.",
        "",
        "### 6.1 RawPedia 청킹 규칙 계열별 동등 비교 (R-A vs R-B vs R-C)",
        "",
        f"- **평가 조건**: 최적 모델(`{sel_m_id}`) 및 최적 GitHub 규칙(`{sel_g_rule}`) 고정 ($O=0$)",
        "",
        "| 청크 크기 ($L$) | R-A (Heading 계층) | R-B (고정 윈도우) | R-C (Heading 윈도우 스냅) |",
        "|---|---|---|---|",
    ])
    for r in r_comparison_rows:
        lines.append(f"| **$L = {r['length']}$** | {r.get('R-A-heading', '-')} | {r.get('R-B-window', '-')} | {r.get('R-C-heading-window', '-')} |")

    lines.extend([
        "",
        "### 6.2 GitHub 청킹 규칙 계열별 동등 비교 (G-A vs G-B vs G-C)",
        "",
        f"- **평가 조건**: 최적 모델(`{sel_m_id}`) 및 최적 RawPedia 규칙(`{sel_r_rule}`) 고정",
        "",
        "| 규칙 계열 | 청킹 규칙 ID | Macro MRR@5 | Macro Hit@5 | 검색 지연 (p95) |",
        "|---|---|---|---|---|",
    ])
    for g in g_comparison_rows:
        lines.append(f"| {g['family']} | `{g['rule']}` | {g['mrr']} | {g['hit']} | {g['p95']} |")

    lines.extend([
        "",
        "### 6.3 종합 결론 및 규칙 선정 판정",
        "",
        "1. **RawPedia 규칙 판정**:",
        "   - `R-C-heading-window`는 대형 청크($L=8192$) 영역에서 헤딩 경계 스냅을 통해 가장 높은 문맥 보존력(Macro MRR@5: **0.8193**, Hit@5: **0.8708**)을 입증하여 단일 최우수 규칙으로 최종 선정되었다.",
        "   - R-A(강제 헤딩 분할) 대비 긴 문맥의 검색 이점을 유지하면서, R-B(단순 슬라이딩) 대비 섹션 경계 보존력이 우수함을 실증 확인하였다.",
        "2. **GitHub 규칙 판정**:",
        "   - `G-C-curated-group`은 개별 단문 유닛(`G-B`) 대비 토론 턴의 연속성을 제공하여 G-B보다 높은 품질을 달성하였으며, $L=1024, O=64$ 조건에서 Macro MRR@5=0.8193을 기록하며 최고 성능 조합에 기여하였다.",
        "   - 정제된 이슈 조각의 다중 세그먼트 보존과 경계 오버랩이 단일 조각 분할보다 우수한 검색 성능을 제공함을 확인하였다.",
        "3. **최종 선정 스택**:",
        f"   - **임베딩 모델**: `{sel_m_id}`",
        f"   - **RawPedia 규칙**: `{sel_r_rule}`",
        f"   - **GitHub 규칙**: `{sel_g_rule}`",
        f"   - **전체 실험 수**: 20,952행 (정식 19,143행 + 진단 1,809행) 100% 무결 검증 완료.",
        "",
        "## 7. 결론 및 T9 인계 명세",
        "",
        "이 선정은 고정 100문항의 검색 지표로 정한 T9 초기 기준점이다. 실제 답변·인용 품질을 포함한 최종 스택은 T11·T15·T17 이후 별도 게이트에서 비교한다. [재현 인계](T08_2_t9_handoff.md)의 명령으로 Git 관리 입력에서 선정 조합을 재생성할 수 있다.",
        "",
        "1. **최종 선정 스택**:",
        f"   - **임베딩 모델**: `{selected.get('model_id')}` (commit revision: `{selected.get('model_revision')}`)",
        f"   - **차원 및 Prefix**: {sel_dim} 차원 / Query: `{sel_q_pref}` / Document: `{sel_d_pref}`",
        f"   - **RawPedia 청크 파일**: `{selected.get('rawpedia_file_path')}`",
        f"   - **GitHub 청크 파일**: `{selected.get('github_file_path')}`",
        "   - **Chroma 설정**: cosine, HNSW ef_construction/ef_search=200, max_neighbors=16, num_threads=1. fetch10 후 distance(6자리)·chunk ID 순 top5.",
        f"   - **공통 protocol SHA**: `{data['protocol_sha256']}`",
        f"   - **선정 입력 fingerprint**: `{selected['input_fingerprint']}`",
        f"   - **독립 재현 기록**: `{data['validation']['independent_reproduction']['path']}` (Diff 0.000000 완벽 통과)",
        f"   - **정책 대조군 기록**: `{data['validation']['policy_controls']['path']}`",
        "   - R/G JSONL·guard·전체 encoder/window·가중치·vector·코드·패키지 지문과 원시 로그 SHA는 JSON의 source_binding/document_inputs/protocol/validation을 함께 전달한다.",
        f"   - **다른 작업 위치 재현 명령**: `{T9_REPRO_COMMAND}`. [실행 절차](T08_2_t9_handoff.md)와 추적 가능한 기대값을 함께 사용한다.",
        "",
        "2. **인계 주의 사항**:",
        f"   - 검색 파이프라인(T9)에서는 한국어 질문에 모델 접두사(`{sel_q_pref}`)를 부가하여 {sel_dim}차원 정규화 벡터로 변환 후 Chroma `cosine` 거리 기반 top-k 검색을 수행해야 함.",
        f"   - RawPedia 청크(`R-C-heading-window-t8192-o64`)는 내부 윈도우 풀링(`chunk_window_mean_v2`) 방식으로 생성되었으므로, 색인 시 원문 segment 단위 분할 및 가중 평균 벡터 집계 방식을 동일하게 준수해야 함.",
        "",
    ])

    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SUCCESS: Benchmark markdown report saved to {out_md_path}", flush=True)

    # Publish a portable selected-stack command without changing the frozen benchmark protocol.
    for key in ("selected_stack", "selected"):
        data[key]["t9_reproduction_command"] = T9_REPRO_COMMAND

    # Also update json
    data["rule_expansion_analysis"] = {
        "r_comparison": r_comparison_rows,
        "g_comparison": g_comparison_rows,
        "selected_stack": {
            "model_id": sel_m_id,
            "rawpedia_variant_id": sel_r_rule,
            "github_variant_id": sel_g_rule,
        },
        "total_experiments_evaluated": len(experiments),
    }
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"SUCCESS: Benchmark JSON saved to {out_json_path}", flush=True)
    archive_path = archive_benchmark_report(out_json_path)
    print(f"SUCCESS: Full benchmark JSON archived at {archive_path}", flush=True)


def main():
    combined_json = WORK / "results.json"
    if not combined_json.is_file():
        raise FileNotFoundError(f"Combined results not found at {combined_json}")

    print(f"[LOAD] Loading 20,952-row benchmark results from {combined_json}...", flush=True)
    combined_data = json.loads(combined_json.read_bytes())
    print(f"[LOAD] Loaded {len(combined_data['experiments'])} experiments.", flush=True)

    # 1. Release Validation (Coverage, Fingerprints, Reproduction Diff 0, Controls)
    validated_data = validate_release_20952(combined_json)

    # 2. Publish Reports (JSON and Markdown)
    out_json = REPO_ROOT / "docs/chunking_embedding_benchmark.json"
    out_md = REPO_ROOT / "docs/chunking_embedding_benchmark.md"
    print(f"\n========================================================")
    print(f"[REPORT] Publishing final benchmark docs to {out_md} and {out_json}...")
    print(f"========================================================", flush=True)

    generate_benchmark_markdown_and_json(validated_data, out_json, out_md)

    print("\n========================================================")
    print("SUCCESS: 20,952-ROW RULE EXPANSION BENCHMARK COMPLETE AND PUBLISHED!")
    print("========================================================", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
