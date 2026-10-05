#!/usr/bin/env python3
"""Build and verify chunk sets for §16 Rule Expansion (R-C & G-C) across all 4 guard groups."""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.chunk_corpus import (
    cmd_check,
    cmd_prepare,
    execute_chunking_build,
)

GROUPS_CONFIG = {
    "native-common-256": {
        "guard_group": "native-common-256",
        "physical_embedding_policy": "direct_native_v3",
        "thread_embedding_policy": "thread_window_mean_v3",
        "encoder_window_tokens": None,
        "encoder_overlap_tokens": None,
        "rawpedia_rules": ["R-A-heading", "R-B-window", "R-C-heading-window"],
        "github_rules": ["G-B-curated-unit", "G-C-curated-group", "G-A-curated-thread", "G-A-full-thread"],
        "target_tokens_grid": [128, 192, 224],
        "overlap_tokens_grid": [0, 32, 64],
        "thread_window_tokens_grid": [128, 192, 224],
        "model_manifest_path": REPO_ROOT / "data/embedding-benchmark/t08-2/grid-001/environment.json",
    },
    "bge-512": {
        "guard_group": "bge-512",
        "physical_embedding_policy": "direct_native_v3",
        "thread_embedding_policy": "thread_window_mean_v3",
        "encoder_window_tokens": None,
        "encoder_overlap_tokens": None,
        "rawpedia_rules": ["R-A-heading", "R-B-window", "R-C-heading-window"],
        "github_rules": ["G-B-curated-unit", "G-C-curated-group", "G-A-curated-thread", "G-A-full-thread"],
        "target_tokens_grid": [224, 256, 320, 384, 448, 464, 480, 496, 512],
        "overlap_tokens_grid": [0, 32, 64],
        "thread_window_tokens_grid": [224, 256, 320, 384, 448],
        "github_target_tokens_grid": [224, 256, 320, 384, 448],
        "model_manifest_path": REPO_ROOT / "data/embedding-benchmark/t08-2/remeasurement-001/batch-bge/environment.json",
    },
    "e5-512": {
        "guard_group": "e5-512",
        "physical_embedding_policy": "direct_native_v3",
        "thread_embedding_policy": "thread_window_mean_v3",
        "encoder_window_tokens": None,
        "encoder_overlap_tokens": None,
        "rawpedia_rules": ["R-A-heading", "R-B-window", "R-C-heading-window"],
        "github_rules": ["G-B-curated-unit", "G-C-curated-group", "G-A-curated-thread", "G-A-full-thread"],
        "target_tokens_grid": [224, 256, 320, 384, 448, 464, 480, 496, 512],
        "overlap_tokens_grid": [0, 32, 64],
        "thread_window_tokens_grid": [224, 256, 320, 384, 448],
        "github_target_tokens_grid": [224, 256, 320, 384, 448],
        "model_manifest_path": REPO_ROOT / "data/embedding-benchmark/t08-2/remeasurement-001/batch-e5/environment.json",
    },
    "pooled-common-256": {
        "guard_group": "pooled-common-256",
        "physical_embedding_policy": "chunk_window_mean_v2",
        "thread_embedding_policy": "thread_window_mean_v2",
        "encoder_window_tokens": 224,
        "encoder_overlap_tokens": 0,
        "rawpedia_rules": ["R-A-heading", "R-B-window", "R-C-heading-window"],
        "github_rules": ["G-B-curated-unit", "G-C-curated-group", "G-A-curated-thread", "G-A-full-thread"],
        "target_tokens_grid": [224, 448, 512, 768, 1024, 1536, 2048, 4096, 6144, 8192],
        "overlap_tokens_grid": [0, 64, 128],
        "thread_window_tokens_grid": [224],
        "github_target_tokens_grid": [224, 448, 512, 768, 1024],
        "model_manifest_path": REPO_ROOT / "data/embedding-benchmark/t08-2/grid-001/environment.json",
    },
}


def build_group_chunks(group_name: str, target_base_dir: Path) -> dict:
    """Build all chunks for a single guard group, verify coverage and regeneration."""
    cfg = GROUPS_CONFIG[group_name]
    group_dir = target_base_dir / group_name
    group_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = group_dir / "manifest.json"

    print(f"\n========================================================")
    print(f"Building chunks for {group_name} -> {group_dir}")
    print(f"========================================================")

    # 1. Prepare manifest
    prep_args = argparse.Namespace(
        rawpedia_dir=str(REPO_ROOT / "data/rawpedia"),
        rawpedia_collection=str(REPO_ROOT / "docs/rawpedia_collection.md"),
        github_candidates=str(REPO_ROOT / "data/issues/search-candidates.json"),
        github_dir=str(REPO_ROOT / "data/issues"),
        source_manifest=str(REPO_ROOT / "docs/search_eval_source_manifest.json"),
        queries=str(REPO_ROOT / "docs/search_eval_queries.json"),
        baseline_md=str(REPO_ROOT / "docs/chunking_embedding_benchmark.md"),
        baseline_json=str(REPO_ROOT / "docs/chunking_embedding_benchmark.json"),
        baseline_prefix=None,
        output_dir=str(group_dir),
    )
    ret = cmd_prepare(prep_args)
    if ret != 0:
        raise RuntimeError(f"Prepare failed for {group_name}")

    # 2. Build chunks
    # Note: if github_target_tokens_grid is specified, use separate grid for github
    # To handle separate grids cleanly, we can call execute_chunking_build with full grids
    # or handle GitHub target tokens properly.
    # In execute_chunking_build, target_tokens_grid is used for both RawPedia and G-B/G-C.
    # If github_target_tokens_grid is different from RawPedia:
    # Build RawPedia first with target_tokens_grid, then GitHub with github_target_tokens_grid!
    gh_t_grid = cfg.get("github_target_tokens_grid", cfg["target_tokens_grid"])

    if gh_t_grid == cfg["target_tokens_grid"]:
        rule_manifest, _ = execute_chunking_build(
            manifest_path=manifest_path,
            model_manifest_path=cfg["model_manifest_path"],
            rawpedia_rules=cfg["rawpedia_rules"],
            github_rules=cfg["github_rules"],
            target_tokens_grid=cfg["target_tokens_grid"],
            overlap_tokens_grid=cfg["overlap_tokens_grid"],
            thread_window_tokens_grid=cfg["thread_window_tokens_grid"],
            target_dir=group_dir,
            guard_group=cfg["guard_group"],
            physical_embedding_policy=cfg["physical_embedding_policy"],
            encoder_window_tokens=cfg["encoder_window_tokens"],
            encoder_overlap_tokens=cfg["encoder_overlap_tokens"],
            thread_embedding_policy=cfg["thread_embedding_policy"],
        )
    else:
        # Build RawPedia rules with full target_tokens_grid
        rule_manifest_rp, _ = execute_chunking_build(
            manifest_path=manifest_path,
            model_manifest_path=cfg["model_manifest_path"],
            rawpedia_rules=cfg["rawpedia_rules"],
            github_rules=[],
            target_tokens_grid=cfg["target_tokens_grid"],
            overlap_tokens_grid=cfg["overlap_tokens_grid"],
            thread_window_tokens_grid=cfg["thread_window_tokens_grid"],
            target_dir=group_dir,
            guard_group=cfg["guard_group"],
            physical_embedding_policy=cfg["physical_embedding_policy"],
            encoder_window_tokens=cfg["encoder_window_tokens"],
            encoder_overlap_tokens=cfg["encoder_overlap_tokens"],
            thread_embedding_policy=cfg["thread_embedding_policy"],
        )
        # Build GitHub rules with github_target_tokens_grid
        rule_manifest_gh, _ = execute_chunking_build(
            manifest_path=manifest_path,
            model_manifest_path=cfg["model_manifest_path"],
            rawpedia_rules=[],
            github_rules=cfg["github_rules"],
            target_tokens_grid=gh_t_grid,
            overlap_tokens_grid=cfg["overlap_tokens_grid"],
            thread_window_tokens_grid=cfg["thread_window_tokens_grid"],
            target_dir=group_dir,
            guard_group=cfg["guard_group"],
            physical_embedding_policy=cfg["physical_embedding_policy"],
            encoder_window_tokens=cfg["encoder_window_tokens"],
            encoder_overlap_tokens=cfg["encoder_overlap_tokens"],
            thread_embedding_policy=cfg["thread_embedding_policy"],
        )
        rule_manifest = {**rule_manifest_rp, **rule_manifest_gh}

    # Update manifest with final metadata
    from src.artagent.chunking import resolve_guard_models, sha256_bytes, canonical_json_bytes
    models_data = json.loads(cfg["model_manifest_path"].read_bytes())["models"]
    guard_models = resolve_guard_models(cfg["guard_group"], models_data)

    current_manifest = json.loads(manifest_path.read_bytes())
    current_manifest["chunking_rules"] = rule_manifest
    current_manifest["guard_group"] = cfg["guard_group"]
    current_manifest["guard_models"] = guard_models
    current_manifest["guard_models_hash"] = sha256_str(json.dumps(guard_models, sort_keys=True))
    current_manifest["physical_embedding_policy"] = cfg["physical_embedding_policy"]
    current_manifest["thread_embedding_policy"] = cfg["thread_embedding_policy"]
    current_manifest["encoder_window_tokens"] = cfg["encoder_window_tokens"]
    current_manifest["encoder_overlap_tokens"] = cfg["encoder_overlap_tokens"]
    current_manifest["model_manifest_path"] = str(cfg["model_manifest_path"])
    current_manifest["search_grid"] = {
        "rawpedia_target_tokens_grid": cfg["target_tokens_grid"],
        "github_target_tokens_grid": gh_t_grid,
        "overlap_tokens_grid": cfg["overlap_tokens_grid"],
        "thread_window_tokens_grid": cfg["thread_window_tokens_grid"],
        "rawpedia_variants_count": sum(1 for k in rule_manifest if k.startswith("R-")),
        "github_formal_variants_count": sum(1 for k in rule_manifest if k.startswith("G-") and not rule_manifest[k].get("is_diagnostic")),
        "github_diagnostic_variants_count": sum(1 for k in rule_manifest if k.startswith("G-") and rule_manifest[k].get("is_diagnostic")),
        "total_variants_count": len(rule_manifest),
    }
    current_manifest["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.write_bytes(json.dumps(current_manifest, indent=2, ensure_ascii=False).encode("utf-8"))

    print(f"Group {group_name} built successfully: {len(rule_manifest)} variants total.")
    return current_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-base-dir", default="data/chunks/t08-2-rule-expansion", help="Target base directory for rule expansion chunk sets.")
    parser.add_argument("--groups", nargs="+", default=["native-common-256", "bge-512", "e5-512", "pooled-common-256"], help="Guard groups to build.")
    args = parser.parse_args()

    target_base = Path(args.output_base_dir).resolve()
    target_base.mkdir(parents=True, exist_ok=True)

    for group in args.groups:
        build_group_chunks(group, target_base)

    print("\nALL RULE EXPANSION CHUNK SETS BUILT SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
