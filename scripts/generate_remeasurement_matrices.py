#!/usr/bin/env python3
"""Generate experiment matrices for all remeasurement batches (§15.3 & §15.6).

Batches:
  1. batch-native-common: 1080 experiments (864 formal, 216 diagnostic)
  2. batch-bge: 1548 experiments (1248 formal, 300 diagnostic)
  3. batch-e5: 774 experiments (624 formal, 150 diagnostic)
  4. batch-pooled: 2100 experiments (1980 formal, 120 diagnostic)
Grand total: 5502 experiments (4716 formal, 786 diagnostic).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import sys

from artagent.chunking import sha256_str

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_experiment_entry(
    r_var: dict,
    g_var: dict,
    m_id: str,
    rev: str,
    guard_group: str,
    device: str = "cpu",
    ks: list[int] | None = None,
) -> dict:
    if ks is None:
        ks = [1, 3, 5]
    r_id = r_var["rule_id"]
    g_id = g_var["rule_id"]
    is_diagnostic = g_var.get("is_diagnostic", False) or "full-thread" in g_id
    r_policy = r_var.get("embedding_policy", "direct")
    g_policy = g_var.get("embedding_policy", "direct")
    stage_id = "boundary-native" if r_policy == "direct_native_v3" else ("boundary-pooled" if r_policy == "chunk_window_mean_v2" else "stage-n")

    exp_slug = f"{r_id}__{g_id}__{m_id}__{rev[:8]}__{r_policy}__{g_policy}__{guard_group}__{device}"
    exp_id = f"exp_{sha256_str(exp_slug)[:12]}"

    return {
        "experiment_id": exp_id,
        "stage_id": stage_id,
        "guard_group": guard_group,
        "is_diagnostic": is_diagnostic,
        "rawpedia_variant_id": r_id,
        "rawpedia_variant": r_var,
        "rawpedia_file_path": r_var.get("file_path"),
        "rawpedia_policy": r_policy,
        "github_variant_id": g_id,
        "github_variant": g_var,
        "github_file_path": g_var.get("file_path"),
        "github_policy": g_policy,
        "model_id": m_id,
        "model_revision": rev,
        "ks": ks,
        "device": device,
        "status": "pending",
    }


def build_matrix_payload(experiments: list[dict], counts_meta: dict) -> dict:
    formal_count = sum(1 for e in experiments if not e["is_diagnostic"])
    diagnostic_count = sum(1 for e in experiments if e["is_diagnostic"])
    return {
        "schema_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_experiments_count": len(experiments),
        "formal_experiments_count": formal_count,
        "diagnostic_experiments_count": diagnostic_count,
        "counts_breakdown": counts_meta,
        "experiments": experiments,
    }


def main() -> int:
    env_path = REPO_ROOT / "data/embedding-benchmark/t08-2/grid-001/environment.json"
    env_data = json.loads(env_path.read_bytes())
    models_meta = env_data["models"]

    out_base = REPO_ROOT / "data/embedding-benchmark/t08-2/remeasurement-001"
    out_base.mkdir(parents=True, exist_ok=True)

    all_generated_exp_ids = set()

    # -------------------------------------------------------------------------
    # 1. batch-native-common (1080 experiments)
    # -------------------------------------------------------------------------
    cm_native_path = REPO_ROOT / "data/chunks/t08-2-remeasurement/native-common-256/manifest.json"
    cm_native = json.loads(cm_native_path.read_bytes())
    rules_native = cm_native["chunking_rules"]
    r_native = [v for k, v in sorted(rules_native.items()) if k.startswith("R-")]
    g_native = [v for k, v in sorted(rules_native.items()) if k.startswith("G-")]

    exps_native = []
    for m_id in sorted(models_meta.keys()):
        rev = models_meta[m_id]["revision"]
        for r_var in r_native:
            for g_var in g_native:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "native-common-256")
                exps_native.append(e)

    dir_native = out_base / "batch-native-common"
    dir_native.mkdir(parents=True, exist_ok=True)
    (dir_native / "environment.json").write_text(json.dumps(env_data, indent=2), encoding="utf-8")
    payload_native = build_matrix_payload(
        exps_native,
        {
            "rawpedia_variants": len(r_native),
            "github_variants": len(g_native),
            "models_count": len(models_meta),
        },
    )
    (dir_native / "experiment_matrix.json").write_text(json.dumps(payload_native, indent=2), encoding="utf-8")
    print(f"batch-native-common: {len(exps_native)} rows (formal: {payload_native['formal_experiments_count']}, diag: {payload_native['diagnostic_experiments_count']})")
    assert len(exps_native) == 1080
    assert payload_native["formal_experiments_count"] == 864
    assert payload_native["diagnostic_experiments_count"] == 216
    for e in exps_native:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 2. batch-bge (1548 experiments = 1500 N + 48 Q-N)
    # -------------------------------------------------------------------------
    cm_bge_path = REPO_ROOT / "data/chunks/t08-2-remeasurement/bge-512/manifest.json"
    cm_bge = json.loads(cm_bge_path.read_bytes())
    rules_bge = cm_bge["chunking_rules"]
    bge_models = ["BAAI/bge-base-en-v1.5", "BAAI/bge-small-en-v1.5"]

    # Part 1: BGE N (L in 224, 256, 320, 384, 448; O in 0, 32, 64) -> 30 R variants
    r_n_tokens = {"224", "256", "320", "384", "448"}
    r_bge_n = [
        v for k, v in sorted(rules_bge.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_n_tokens)
    ]
    # G-B (same 5 Ls * 3 Os = 15) + G-A curated (5 Ws) + G-A full (5 Ws) = 25 G variants
    g_n_tokens = {"224", "256", "320", "384", "448"}
    g_bge_n = [
        v for k, v in sorted(rules_bge.items())
        if k.startswith("G-") and (
            ("curated-unit" in k and any(f"-t{t}-" in k for t in g_n_tokens))
            or ("thread" in k and any(f"-w{t}-" in k for t in g_n_tokens))
        )
    ]
    assert len(r_bge_n) == 30, f"Expected 30 r_bge_n, got {len(r_bge_n)}"
    assert len(g_bge_n) == 25, f"Expected 25 g_bge_n, got {len(g_bge_n)}"

    exps_bge = []
    for m_id in bge_models:
        rev = models_meta[m_id]["revision"]
        for r_var in r_bge_n:
            for g_var in g_bge_n:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "bge-512")
                exps_bge.append(e)
    assert len(exps_bge) == 1500

    # Part 2: BGE Q-N (L in 464, 480, 496, 512; O in 0, 32, 64) -> 24 R variants
    r_qn_tokens = {"464", "480", "496", "512"}
    r_bge_qn = [
        v for k, v in sorted(rules_bge.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_qn_tokens)
    ]
    assert len(r_bge_qn) == 24, f"Expected 24 r_bge_qn, got {len(r_bge_qn)}"

    g_bge_base_fixed = rules_bge["G-A-curated-thread-w320-wo0"]
    g_bge_small_fixed = rules_bge["G-A-curated-thread-w384-wo0"]

    for r_var in r_bge_qn:
        e1 = make_experiment_entry(r_var, g_bge_base_fixed, "BAAI/bge-base-en-v1.5", models_meta["BAAI/bge-base-en-v1.5"]["revision"], "bge-512")
        e2 = make_experiment_entry(r_var, g_bge_small_fixed, "BAAI/bge-small-en-v1.5", models_meta["BAAI/bge-small-en-v1.5"]["revision"], "bge-512")
        exps_bge.extend([e1, e2])

    dir_bge = out_base / "batch-bge"
    dir_bge.mkdir(parents=True, exist_ok=True)
    env_bge = dict(env_data)
    env_bge["models"] = {m: models_meta[m] for m in bge_models}
    (dir_bge / "environment.json").write_text(json.dumps(env_bge, indent=2), encoding="utf-8")
    payload_bge = build_matrix_payload(exps_bge, {"bge_models_count": len(bge_models)})
    (dir_bge / "experiment_matrix.json").write_text(json.dumps(payload_bge, indent=2), encoding="utf-8")
    print(f"batch-bge: {len(exps_bge)} rows (formal: {payload_bge['formal_experiments_count']}, diag: {payload_bge['diagnostic_experiments_count']})")
    assert len(exps_bge) == 1548
    assert payload_bge["formal_experiments_count"] == 1248
    assert payload_bge["diagnostic_experiments_count"] == 300
    for e in exps_bge:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 3. batch-e5 (774 experiments = 750 N + 24 Q-N)
    # -------------------------------------------------------------------------
    cm_e5_path = REPO_ROOT / "data/chunks/t08-2-remeasurement/e5-512/manifest.json"
    cm_e5 = json.loads(cm_e5_path.read_bytes())
    rules_e5 = cm_e5["chunking_rules"]
    e5_model = "intfloat/multilingual-e5-small"
    rev_e5 = models_meta[e5_model]["revision"]

    r_e5_n = [
        v for k, v in sorted(rules_e5.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_n_tokens)
    ]
    g_e5_n = [
        v for k, v in sorted(rules_e5.items())
        if k.startswith("G-") and (
            ("curated-unit" in k and any(f"-t{t}-" in k for t in g_n_tokens))
            or ("thread" in k and any(f"-w{t}-" in k for t in g_n_tokens))
        )
    ]
    assert len(r_e5_n) == 30
    assert len(g_e5_n) == 25

    exps_e5 = []
    for r_var in r_e5_n:
        for g_var in g_e5_n:
            e = make_experiment_entry(r_var, g_var, e5_model, rev_e5, "e5-512")
            exps_e5.append(e)
    assert len(exps_e5) == 750

    r_e5_qn = [
        v for k, v in sorted(rules_e5.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_qn_tokens)
    ]
    assert len(r_e5_qn) == 24
    g_e5_fixed = rules_e5["G-A-curated-thread-w224-wo0"]
    for r_var in r_e5_qn:
        e = make_experiment_entry(r_var, g_e5_fixed, e5_model, rev_e5, "e5-512")
        exps_e5.append(e)

    dir_e5 = out_base / "batch-e5"
    dir_e5.mkdir(parents=True, exist_ok=True)
    env_e5 = dict(env_data)
    env_e5["models"] = {e5_model: models_meta[e5_model]}
    (dir_e5 / "environment.json").write_text(json.dumps(env_e5, indent=2), encoding="utf-8")
    payload_e5 = build_matrix_payload(exps_e5, {"e5_models_count": 1})
    (dir_e5 / "experiment_matrix.json").write_text(json.dumps(payload_e5, indent=2), encoding="utf-8")
    print(f"batch-e5: {len(exps_e5)} rows (formal: {payload_e5['formal_experiments_count']}, diag: {payload_e5['diagnostic_experiments_count']})")
    assert len(exps_e5) == 774
    assert payload_e5["formal_experiments_count"] == 624
    assert payload_e5["diagnostic_experiments_count"] == 150
    for e in exps_e5:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 4. batch-pooled (2100 experiments = 2040 P + 36 Q-P + 24 Upper Bound)
    # -------------------------------------------------------------------------
    cm_pooled_path = REPO_ROOT / "data/chunks/t08-2-remeasurement/pooled-common-256/manifest.json"
    cm_pooled = json.loads(cm_pooled_path.read_bytes())
    rules_pooled = cm_pooled["chunking_rules"]

    # Part 1: Pooled P (L in 224, 448, 512, 768, 1024; O in 0, 64, 128) -> 30 R variants
    r_p_tokens = {"224", "448", "512", "768", "1024"}
    r_pooled_p = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_p_tokens)
    ]
    # G-B (5 Ls * 3 Os = 15) + G-A curated W224 (1) + G-A full W224 (1) = 17 G variants
    g_p_tokens = {"224", "448", "512", "768", "1024"}
    g_pooled_p = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("G-") and (
            ("curated-unit" in k and any(f"-t{t}-" in k for t in g_p_tokens))
            or ("thread-w224" in k)
        )
    ]
    assert len(r_pooled_p) == 30, f"Expected 30 r_pooled_p, got {len(r_pooled_p)}"
    assert len(g_pooled_p) == 17, f"Expected 17 g_pooled_p, got {len(g_pooled_p)}"

    exps_pooled = []
    for m_id in sorted(models_meta.keys()):
        rev = models_meta[m_id]["revision"]
        for r_var in r_pooled_p:
            for g_var in g_pooled_p:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "pooled-common-256")
                exps_pooled.append(e)
    assert len(exps_pooled) == 2040

    # Part 2: Pooled Q-P (L in 1536, 2048, 4096; O in 0, 64, 128) -> 18 R variants
    r_qp_tokens = {"1536", "2048", "4096"}
    r_pooled_qp = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_qp_tokens)
    ]
    assert len(r_pooled_qp) == 18
    g_pooled_fixed = rules_pooled["G-A-curated-thread-w224-wo0"]
    pooled_q_models = ["sentence-transformers/all-MiniLM-L6-v2", "intfloat/multilingual-e5-small"]
    for m_id in pooled_q_models:
        rev = models_meta[m_id]["revision"]
        for r_var in r_pooled_qp:
            e = make_experiment_entry(r_var, g_pooled_fixed, m_id, rev, "pooled-common-256")
            exps_pooled.append(e)
    assert len(exps_pooled) == 2076  # 2040 + 36 (Step 4 total)

    # Part 3: Step 5 Upper bound (L in 6144, 8192; O in 0, 64, 128) -> 12 R variants
    r_ub_tokens = {"6144", "8192"}
    r_pooled_ub = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in r_ub_tokens)
    ]
    assert len(r_pooled_ub) == 12
    for m_id in pooled_q_models:
        rev = models_meta[m_id]["revision"]
        for r_var in r_pooled_ub:
            e = make_experiment_entry(r_var, g_pooled_fixed, m_id, rev, "pooled-common-256")
            exps_pooled.append(e)
    assert len(exps_pooled) == 2100  # 2076 + 24 (Grand total with Step 5)

    dir_pooled = out_base / "batch-pooled"
    dir_pooled.mkdir(parents=True, exist_ok=True)
    (dir_pooled / "environment.json").write_text(json.dumps(env_data, indent=2), encoding="utf-8")
    payload_pooled = build_matrix_payload(exps_pooled, {"pooled_models_count": len(models_meta)})
    (dir_pooled / "experiment_matrix.json").write_text(json.dumps(payload_pooled, indent=2), encoding="utf-8")
    print(f"batch-pooled: {len(exps_pooled)} rows (formal: {payload_pooled['formal_experiments_count']}, diag: {payload_pooled['diagnostic_experiments_count']})")
    assert len(exps_pooled) == 2100
    assert payload_pooled["formal_experiments_count"] == 1980
    assert payload_pooled["diagnostic_experiments_count"] == 120
    for e in exps_pooled:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # Grand Totals Verification
    # -------------------------------------------------------------------------
    total_rows = len(all_generated_exp_ids)
    total_formal = (
        payload_native["formal_experiments_count"]
        + payload_bge["formal_experiments_count"]
        + payload_e5["formal_experiments_count"]
        + payload_pooled["formal_experiments_count"]
    )
    total_diag = (
        payload_native["diagnostic_experiments_count"]
        + payload_bge["diagnostic_experiments_count"]
        + payload_e5["diagnostic_experiments_count"]
        + payload_pooled["diagnostic_experiments_count"]
    )
    print("\n================ GRAND TOTALS VERIFICATION ================")
    print(f"Total Unique Experiment IDs: {total_rows} (Expected: 5502)")
    print(f"Total Formal Experiments:    {total_formal} (Expected: 4716)")
    print(f"Total Diagnostic Experiments:{total_diag} (Expected: 786)")
    print("===========================================================")
    assert total_rows == 5502
    assert total_formal == 4716
    assert total_diag == 786
    print("SUCCESS: All 4 batch matrices generated and verified!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
