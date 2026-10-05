#!/usr/bin/env python3
"""Generate unreduced 20,952-row experiment matrices for §16 Rule Expansion.

Matrix Breakdown (§16.3):
  1. batch-native-common: 2,592 experiments (2,268 formal, 324 diagnostic)
  2. batch-bge:          6,480 experiments (5,670 formal, 810 diagnostic)
  3. batch-e5:           3,240 experiments (2,835 formal, 405 diagnostic)
  4. batch-pooled:       8,640 experiments (8,370 formal, 270 diagnostic)
Grand Total: 20,952 experiments (19,143 formal, 1,809 diagnostic).
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.artagent.chunking import sha256_str


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunks-base-dir",
        default="data/chunks/t08-2-rule-expansion",
        help="Base directory for rule expansion chunk sets.",
    )
    parser.add_argument(
        "--output-base-dir",
        default="data/embedding-benchmark/t08-2/rule-expansion-001",
        help="Base directory for rule expansion benchmark matrices.",
    )
    args = parser.parse_args()

    chunks_base = Path(args.chunks_base_dir).resolve()
    out_base = Path(args.output_base_dir).resolve()
    out_base.mkdir(parents=True, exist_ok=True)

    all_generated_exp_ids = set()

    # -------------------------------------------------------------------------
    # 1. batch-native-common (2592 experiments = 2268 formal + 324 diagnostic)
    # -------------------------------------------------------------------------
    cm_native_path = chunks_base / "native-common-256/manifest.json"
    cm_native = json.loads(cm_native_path.read_bytes())
    rules_native = cm_native["chunking_rules"]
    env_native_path = REPO_ROOT / cm_native["model_manifest_path"]
    env_native = json.loads(env_native_path.read_bytes())
    models_native = env_native["models"]

    r_native = [v for k, v in sorted(rules_native.items()) if k.startswith("R-")]
    g_native = [v for k, v in sorted(rules_native.items()) if k.startswith("G-")]
    assert len(r_native) == 27, f"Expected 27 R variants, got {len(r_native)}"
    assert len(g_native) == 24, f"Expected 24 G variants, got {len(g_native)}"

    exps_native = []
    for m_id in sorted(models_native.keys()):
        rev = models_native[m_id]["revision"]
        for r_var in r_native:
            for g_var in g_native:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "native-common-256")
                exps_native.append(e)

    dir_native = out_base / "batch-native-common"
    dir_native.mkdir(parents=True, exist_ok=True)
    (dir_native / "environment.json").write_text(json.dumps(env_native, indent=2), encoding="utf-8")
    payload_native = build_matrix_payload(
        exps_native,
        {
            "rawpedia_variants": len(r_native),
            "github_variants": len(g_native),
            "models_count": len(models_native),
        },
    )
    (dir_native / "experiment_matrix.json").write_text(json.dumps(payload_native, indent=2), encoding="utf-8")
    print(f"batch-native-common: {len(exps_native)} rows (formal: {payload_native['formal_experiments_count']}, diag: {payload_native['diagnostic_experiments_count']})")
    assert len(exps_native) == 2592
    assert payload_native["formal_experiments_count"] == 2268
    assert payload_native["diagnostic_experiments_count"] == 324
    for e in exps_native:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 2. batch-bge (6480 experiments = 5670 formal + 810 diagnostic)
    # -------------------------------------------------------------------------
    cm_bge_path = chunks_base / "bge-512/manifest.json"
    cm_bge = json.loads(cm_bge_path.read_bytes())
    rules_bge = cm_bge["chunking_rules"]
    env_bge_path = REPO_ROOT / cm_bge["model_manifest_path"]
    env_bge = json.loads(env_bge_path.read_bytes())
    bge_models = ["BAAI/bge-base-en-v1.5", "BAAI/bge-small-en-v1.5"]

    r_bge = [v for k, v in sorted(rules_bge.items()) if k.startswith("R-")]
    g_bge = [v for k, v in sorted(rules_bge.items()) if k.startswith("G-")]
    assert len(r_bge) == 81, f"Expected 81 R variants for bge-512, got {len(r_bge)}"
    assert len(g_bge) == 40, f"Expected 40 G variants for bge-512, got {len(g_bge)}"

    exps_bge = []
    for m_id in sorted(bge_models):
        rev = env_bge["models"][m_id]["revision"]
        for r_var in r_bge:
            for g_var in g_bge:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "bge-512")
                exps_bge.append(e)

    dir_bge = out_base / "batch-bge"
    dir_bge.mkdir(parents=True, exist_ok=True)
    env_bge_subset = {**env_bge, "models": {m: env_bge["models"][m] for m in bge_models}}
    (dir_bge / "environment.json").write_text(json.dumps(env_bge_subset, indent=2), encoding="utf-8")
    payload_bge = build_matrix_payload(
        exps_bge,
        {
            "rawpedia_variants": len(r_bge),
            "github_variants": len(g_bge),
            "models_count": len(bge_models),
        },
    )
    (dir_bge / "experiment_matrix.json").write_text(json.dumps(payload_bge, indent=2), encoding="utf-8")
    print(f"batch-bge: {len(exps_bge)} rows (formal: {payload_bge['formal_experiments_count']}, diag: {payload_bge['diagnostic_experiments_count']})")
    assert len(exps_bge) == 6480
    assert payload_bge["formal_experiments_count"] == 5670
    assert payload_bge["diagnostic_experiments_count"] == 810
    for e in exps_bge:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 3. batch-e5 (3240 experiments = 2835 formal + 405 diagnostic)
    # -------------------------------------------------------------------------
    cm_e5_path = chunks_base / "e5-512/manifest.json"
    cm_e5 = json.loads(cm_e5_path.read_bytes())
    rules_e5 = cm_e5["chunking_rules"]
    env_e5_path = REPO_ROOT / cm_e5["model_manifest_path"]
    env_e5 = json.loads(env_e5_path.read_bytes())
    e5_models = ["intfloat/multilingual-e5-small"]

    r_e5 = [v for k, v in sorted(rules_e5.items()) if k.startswith("R-")]
    g_e5 = [v for k, v in sorted(rules_e5.items()) if k.startswith("G-")]
    assert len(r_e5) == 81, f"Expected 81 R variants for e5-512, got {len(r_e5)}"
    assert len(g_e5) == 40, f"Expected 40 G variants for e5-512, got {len(g_e5)}"

    exps_e5 = []
    for m_id in sorted(e5_models):
        rev = env_e5["models"][m_id]["revision"]
        for r_var in r_e5:
            for g_var in g_e5:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "e5-512")
                exps_e5.append(e)

    dir_e5 = out_base / "batch-e5"
    dir_e5.mkdir(parents=True, exist_ok=True)
    env_e5_subset = {**env_e5, "models": {m: env_e5["models"][m] for m in e5_models}}
    (dir_e5 / "environment.json").write_text(json.dumps(env_e5_subset, indent=2), encoding="utf-8")
    payload_e5 = build_matrix_payload(
        exps_e5,
        {
            "rawpedia_variants": len(r_e5),
            "github_variants": len(g_e5),
            "models_count": len(e5_models),
        },
    )
    (dir_e5 / "experiment_matrix.json").write_text(json.dumps(payload_e5, indent=2), encoding="utf-8")
    print(f"batch-e5: {len(exps_e5)} rows (formal: {payload_e5['formal_experiments_count']}, diag: {payload_e5['diagnostic_experiments_count']})")
    assert len(exps_e5) == 3240
    assert payload_e5["formal_experiments_count"] == 2835
    assert payload_e5["diagnostic_experiments_count"] == 405
    for e in exps_e5:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # 4. batch-pooled (8640 experiments = 8370 formal + 270 diagnostic)
    #    Part A: 기본 (5760 experiments = 5580 formal + 180 diagnostic)
    #    Part B: 확장 (2880 experiments = 2790 formal + 90 diagnostic)
    # -------------------------------------------------------------------------
    cm_pooled_path = chunks_base / "pooled-common-256/manifest.json"
    cm_pooled = json.loads(cm_pooled_path.read_bytes())
    rules_pooled = cm_pooled["chunking_rules"]
    env_pooled_path = REPO_ROOT / cm_pooled["model_manifest_path"]
    env_pooled = json.loads(env_pooled_path.read_bytes())
    all_pooled_models = sorted(env_pooled["models"].keys())
    ext_models = ["intfloat/multilingual-e5-small", "sentence-transformers/all-MiniLM-L6-v2"]

    # R base: 224, 448, 512, 768, 1024 -> 45 variants (3 rules * 5 L * 3 O)
    base_r_tokens = {"224", "448", "512", "768", "1024"}
    r_pooled_base = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in base_r_tokens)
    ]
    assert len(r_pooled_base) == 45, f"Expected 45 r_pooled_base, got {len(r_pooled_base)}"

    # R ext: 1536, 2048, 4096, 6144, 8192 -> 45 variants (3 rules * 5 L * 3 O)
    ext_r_tokens = {"1536", "2048", "4096", "6144", "8192"}
    r_pooled_ext = [
        v for k, v in sorted(rules_pooled.items())
        if k.startswith("R-") and any(f"-t{t}-" in k for t in ext_r_tokens)
    ]
    assert len(r_pooled_ext) == 45, f"Expected 45 r_pooled_ext, got {len(r_pooled_ext)}"

    # G pooled: G-B (15) + G-C (15) + curated W224 (1) + full W224 (1) = 32 variants
    g_pooled = [v for k, v in sorted(rules_pooled.items()) if k.startswith("G-")]
    assert len(g_pooled) == 32, f"Expected 32 g_pooled, got {len(g_pooled)}"

    exps_pooled = []
    # Part A: All 4 models across base R (45) and G (32) -> 4 * 45 * 32 = 5760
    for m_id in all_pooled_models:
        rev = env_pooled["models"][m_id]["revision"]
        for r_var in r_pooled_base:
            for g_var in g_pooled:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "pooled-common-256")
                exps_pooled.append(e)

    # Part B: 2 extension models across ext R (45) and G (32) -> 2 * 45 * 32 = 2880
    for m_id in ext_models:
        rev = env_pooled["models"][m_id]["revision"]
        for r_var in r_pooled_ext:
            for g_var in g_pooled:
                e = make_experiment_entry(r_var, g_var, m_id, rev, "pooled-common-256")
                exps_pooled.append(e)

    dir_pooled = out_base / "batch-pooled"
    dir_pooled.mkdir(parents=True, exist_ok=True)
    (dir_pooled / "environment.json").write_text(json.dumps(env_pooled, indent=2), encoding="utf-8")
    payload_pooled = build_matrix_payload(
        exps_pooled,
        {
            "rawpedia_base_variants": len(r_pooled_base),
            "rawpedia_ext_variants": len(r_pooled_ext),
            "github_variants": len(g_pooled),
            "models_count": len(all_pooled_models),
            "ext_models_count": len(ext_models),
        },
    )
    (dir_pooled / "experiment_matrix.json").write_text(json.dumps(payload_pooled, indent=2), encoding="utf-8")
    print(f"batch-pooled: {len(exps_pooled)} rows (formal: {payload_pooled['formal_experiments_count']}, diag: {payload_pooled['diagnostic_experiments_count']})")
    assert len(exps_pooled) == 8640
    assert payload_pooled["formal_experiments_count"] == 8370
    assert payload_pooled["diagnostic_experiments_count"] == 270
    for e in exps_pooled:
        assert e["experiment_id"] not in all_generated_exp_ids
        all_generated_exp_ids.add(e["experiment_id"])

    # -------------------------------------------------------------------------
    # Grand Total Verification
    # -------------------------------------------------------------------------
    total_experiments = len(all_generated_exp_ids)
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
    print("\n========================================================")
    print(f"Grand Total Experiments: {total_experiments} (formal: {total_formal}, diag: {total_diag})")
    print("========================================================")
    assert total_experiments == 20952, f"Expected 20,952 experiments, got {total_experiments}"
    assert total_formal == 19143, f"Expected 19,143 formal, got {total_formal}"
    assert total_diag == 1809, f"Expected 1,809 diagnostic, got {total_diag}"

    summary_payload = {
        "schema_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_experiments_count": total_experiments,
        "formal_experiments_count": total_formal,
        "diagnostic_experiments_count": total_diag,
        "batches": {
            "batch-native-common": {
                "guard_group": "native-common-256",
                "total": len(exps_native),
                "formal": payload_native["formal_experiments_count"],
                "diagnostic": payload_native["diagnostic_experiments_count"],
                "matrix_file": "batch-native-common/experiment_matrix.json",
            },
            "batch-bge": {
                "guard_group": "bge-512",
                "total": len(exps_bge),
                "formal": payload_bge["formal_experiments_count"],
                "diagnostic": payload_bge["diagnostic_experiments_count"],
                "matrix_file": "batch-bge/experiment_matrix.json",
            },
            "batch-e5": {
                "guard_group": "e5-512",
                "total": len(exps_e5),
                "formal": payload_e5["formal_experiments_count"],
                "diagnostic": payload_e5["diagnostic_experiments_count"],
                "matrix_file": "batch-e5/experiment_matrix.json",
            },
            "batch-pooled": {
                "guard_group": "pooled-common-256",
                "total": len(exps_pooled),
                "formal": payload_pooled["formal_experiments_count"],
                "diagnostic": payload_pooled["diagnostic_experiments_count"],
                "matrix_file": "batch-pooled/experiment_matrix.json",
            },
        },
    }
    (out_base / "summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(f"Summary written to {out_base / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
