#!/usr/bin/env python3
"""Isolate legacy/native/thread policy effects with C0-legacy, C0, C1, C2."""
from __future__ import annotations

import argparse
import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import chromadb
import numpy as np
from transformers import AutoTokenizer
from scripts import benchmark_embeddings as bench
from scripts import verify_embedding_benchmark as verify
from src.artagent.chunking import BGE_REVISION, canonical_json_bytes, sha256_bytes, sha256_str

LEGACY_COMMIT = "7b4dbe8f7"
MODEL = "intfloat/multilingual-e5-small"


def legacy_encoder():
    """Load only the real historical encoder function, without its CLI or globals."""
    source = subprocess.check_output(["git", "show", f"{LEGACY_COMMIT}:scripts/benchmark_embeddings.py"], cwd=ROOT).decode()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "encode_chunk_list")
    function_source = ast.get_source_segment(source, function)
    current_tree = ast.parse(inspect.getsource(bench.encode_chunk_list))
    def thread_body(tree):
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and "thread_window_mean_v2" in ast.unparse(n.test))
        body = [n for n in branch.body if not (isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "trace")]
        return ast.dump(ast.Module(body=body, type_ignores=[]))
    if thread_body(function) != thread_body(current_tree):
        raise ValueError("Legacy window assembly/pooling weights differ from the preserved implementation")
    namespace = dict(vars(bench))
    exec(compile(ast.Module(body=[function], type_ignores=[]), "legacy-7b4dbe8f7-encoder", "exec"), namespace)
    return namespace["encode_chunk_list"], {"commit": LEGACY_COMMIT,
        "script_sha256": sha256_str(source), "function_sha256": sha256_str(function_source),
        "thread_branch_ast_equal": True,
        "function_source": function_source}


def run_controls(work_dir, settings):
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    queries = verify.prepare_queries(ROOT / "docs/search_eval_queries.json")
    ref = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5", revision=BGE_REVISION, local_files_only=True)
    info = {**bench.MODEL_CONFIGS[MODEL], "hidden_size": 384}
    encoder = bench.load_encoder(MODEL, info["revision"], "cpu")
    historical, legacy_proof = legacy_encoder()
    (work / "legacy_encoder.py").write_text(legacy_proof.pop("function_source"))
    old_root = ROOT / "data/chunks/t08-2-large-native/e5-512"
    new_root = ROOT / "data/chunks/t08-2-remeasurement/e5-512"
    r_name, g_name = "R-B-window-t448-o32", "G-A-curated-thread-w224-wo0"
    paths = {"old_rawpedia": old_root / "rawpedia" / (r_name + ".jsonl"),
             "old_github": old_root / "github" / (g_name + ".jsonl"),
             "new_rawpedia": new_root / "rawpedia" / (r_name + ".jsonl"),
             "new_github": new_root / "github" / (g_name + ".jsonl")}
    chunks = {key: verify.load_chunks(path) for key, path in paths.items()}
    contract = verify.protocol(settings)
    contract_sha = sha256_bytes(canonical_json_bytes(contract))
    vectors, inputs = {}, {}
    for key, current in chunks.items():
        # Preserve and check every source coordinate even when C0 intentionally has omissions.
        if key.startswith("new"):
            verify.verify_chunks(current, "rawpedia" if "rawpedia" in key else "github")
        vecs, trace = verify.traced_vectors(key, current, encoder, MODEL, info, work / "vectors", ref)
        if key.startswith("old"):
            actual = historical(current, encoder, MODEL, info["doc_prefix"], ref, 16)
            if not np.allclose(actual, vecs, atol=1e-6, rtol=1e-5):
                raise ValueError(f"Current legacy branch differs from actual {LEGACY_COMMIT}: {key}")
            trace["legacy_branch_max_abs_diff"] = float(np.max(np.abs(actual-vecs)))
            trace["legacy_encoder"] = legacy_proof
            # Retrieval uses actual preserved implementation output, not its policy label.
            vecs = actual
        vectors[key], inputs[key] = vecs, trace
    cases = [("C0-legacy", "old_rawpedia", "old_github", True),
             ("C0", "old_rawpedia", "old_github", False),
             ("C1", "new_rawpedia", "old_github", False),
             ("C2", "new_rawpedia", "new_github", False)]
    client = chromadb.PersistentClient(path=str(work / "chroma"))
    results = []
    for label, raw, github, legacy_search in cases:
        row = {"experiment_id": label, "is_diagnostic": True, "guard_group": "e5-512",
               "model_id": MODEL, "model_revision": info["revision"],
               "rawpedia_variant_id": r_name, "rawpedia_rule": r_name, "github_variant_id": g_name, "github_rule": g_name,
               "rawpedia_file_path": verify.relative(paths[raw]), "github_file_path": verify.relative(paths[github]),
               "rawpedia_policy": chunks[raw][0].metadata["embedding_policy"],
               "github_policy": chunks[github][0].metadata["embedding_policy"],
               "protocol_sha256": contract_sha, "control_search_policy": "legacy-fetch5-unsorted" if legacy_search else "common-fetch10-round6-id",
               "document_inputs": {"rawpedia": inputs[raw], "github": inputs[github]},
               "source_binding": {"rawpedia": verify.artifact(paths[raw]), "github": verify.artifact(paths[github])}}
        result = verify.execute_row(row, chunks[raw]+chunks[github], np.vstack([vectors[raw], vectors[github]]),
                                    encoder, info, queries, ref, client, work, settings, legacy=legacy_search)
        verify.validate_row(result, queries, 3)
        results.append(result)
        print(f"CONTROL {label}: MRR={result['metrics']['macro']['mrr@5']:.12f} Q091={result['q091']['first_rel_rank']}", flush=True)
    lookup = {r["experiment_id"]: r for r in results}
    # Historical report rounded each source mean before the macro; report both definitions.
    historic_metric = round((round(lookup["C0-legacy"]["metrics"]["rawpedia"]["mrr@5"], 4) +
                             round(lookup["C0-legacy"]["metrics"]["github"]["mrr@5"], 4)) / 2, 4)
    if historic_metric != .8032:
        raise ValueError(f"Historical .8032 reproduction failed: {historic_metric}")
    if lookup["C0"]["source_binding"]["github"] != lookup["C1"]["source_binding"]["github"]:
        raise ValueError("C0/C1 legacy thread input mismatch")
    if lookup["C1"]["source_binding"]["rawpedia"] != lookup["C2"]["source_binding"]["rawpedia"]:
        raise ValueError("C1/C2 native input mismatch")
    deltas = {}
    for before, after in (("C0", "C1"), ("C1", "C2")):
        b_rows, a_rows = verify.validate_row(lookup[before], queries, 3), verify.validate_row(lookup[after], queries, 3)
        b = {q["query_id"]: q for q in b_rows}
        deltas[f"{after}-{before}"] = {"macro_mrr_at_5": lookup[after]["metrics"]["macro"]["mrr@5"] - lookup[before]["metrics"]["macro"]["mrr@5"],
            "queries": [{"query_id": q["query_id"], "rr_at_5_delta": q["rr"]["5"] - b[q["query_id"]]["rr"]["5"],
                         "before_top5": b[q["query_id"]]["top5_ids"], "after_top5": q["top5_ids"],
                         "before_coverage": b[q["query_id"]]["evidence_coverage"], "after_coverage": q["evidence_coverage"]} for q in a_rows]}
    output = {"status": "passed", "protocol_sha256": contract_sha, "protocol": contract, "legacy_encoder": legacy_proof,
              "legacy_search_encoder_match": True, "historical_rounded_macro_mrr_at_5": historic_metric,
              "controls": results, "deltas": deltas, "excluded_from_formal_row_count": True}
    verify.write_json(work / "policy_controls.json", output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    settings = argparse.Namespace(queries=str(ROOT / "docs/search_eval_queries.json"), device="cpu", seed=42,
        batch_size=16, query_repeat=3, warmup_queries=10, ks=[1, 3, 5], context_budgets=[2048, 4096])
    run_controls(args.work_dir, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
