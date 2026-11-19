#!/usr/bin/env python3
"""독립 8문항의 T10 정제·T9 실험 색인·T15 검색 bundle을 고정한다."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from compare_rag_models import ROOT, canonical, digest, load_cases

sys.path.insert(0, str(ROOT))

from artagent.answer import generation_time_budget
from artagent.chunking import TokenizerBundle
from artagent.graph.search import create_search_nodes
from artagent.graph.state import RequestInput
from artagent.issue_filter import filter_corpus, load_sources
from artagent.issue_update import generate_candidate_chunks
from artagent.retrieval.types import SourceKey
from scripts.eval_t15_rerank import runtime_store, score_record, search_record, trial
from scripts.run_t14_ab_eval import _runtime_generate
from scripts.t15_evaluation import RecordVerifier, fit_bm25_from_snapshot, read_rows, sha256_file
from transformers import AutoTokenizer


BASE = ROOT / "data/eval/stack-selection"
QUESTIONS = BASE / "final_questions_v1.json"
QUESTION_SHA = "222813bc4ca316ab459c6ac252c8c220ae069a0c6be4e400e16a0f84498ccfae"
PROTOCOL = ROOT / "data/eval/t15-rerank/plan_v5/protocol.json"
T15 = PROTOCOL.parent.parent
ISSUES = ROOT / "data/issues"
CURATION = {
    "issue:317": ("curated_guidance", [("2507526862", "explanation"), ("2507526869", "guidance")],
                  "ART_TECHNICAL_EXPLANATION", 2, None),
    "issue:445": ("reported_fix", [("3871653739", "reported_fix"), ("3882260754", "confirmation")],
                  "USER_CONFIRMED_ACTION", 2, 1),
    "issue:518": ("reported_fix", [("5269564179", "reproduction"), ("5276706849", "reported_fix"),
                                  ("5277075153", "confirmation")], "USER_CONFIRMED_ACTION", 3, 2),
    "issue:522": ("unresolved_report", [("5461739634", "caveat")], "DETAILED_UNRESOLVED_REPORT", 0, None),
}


def verify_questions():
    if sha256_file(QUESTIONS) != QUESTION_SHA:
        raise ValueError("독립 질문 동결 지문 불일치")
    rows = json.loads(QUESTIONS.read_bytes())
    original = json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())["queries"]
    used_groups = {q["source_group_id"] for q in original}
    used_docs = {e["doc_id"] for q in original for e in q["evidence"]}
    pilot_docs = {doc for row in load_cases().values() for doc in row["retrieved_source_doc_ids"]}
    if len({r["group_id"] for r in rows}) != len(rows):
        raise ValueError("독립 질문의 원문 그룹 중복")
    for row in rows:
        if row["group_id"] in used_groups or any(q["query"] == row["question"] for q in original):
            raise ValueError(f"기존 질문 또는 원문 그룹과 중복: {row['id']}")
        for evidence in row["evidence"]:
            path = ROOT / evidence["path"]
            if evidence["doc_id"] in used_docs | pilot_docs:
                raise ValueError(f"기존 골드 또는 조정 문맥과 원문 중복: {row['id']}")
            text = path.read_bytes().decode("utf-8")
            if path.suffix == ".json":
                text = json.loads(text)["body"]
            if text.count(evidence["quote"]) != 1:
                raise ValueError(f"원문 위치 검증 실패: {path}")
            evidence["char_start"] = text.index(evidence["quote"])
            evidence["char_end"] = evidence["char_start"] + len(evidence["quote"])
            evidence["source_sha256"] = sha256_file(path)
    return rows


def new_candidates(curation_path):
    inventory = load_sources(ISSUES)
    threads = {t.record_key: t for t in inventory.threads}
    choices = {"schema_version": 1, "rules_version": "t10-2a-v1", "repository": "artraweditor/ART", "threads": {}}
    for key, (status, comments, signal, index, confirms) in CURATION.items():
        thread = threads[key]
        roles = [(key, "context"), *((f"issue-comment:{number}", role) for number, role in comments)]
        snippets = [{"record_key": item, "role": role, "char_start": 0, "char_end": len(inventory.items[item].body)}
                    for item, role in roles]
        evidence = {"signal": signal, "content_index": index}
        if confirms is not None:
            evidence["confirms_content_index"] = confirms
        choices["threads"][key] = {
            "disposition": "include", "thread_sha256": thread.thread_sha256, "reviewed_by": "RAG 선정 실험 원문 검토",
            "knowledge_status": status, "rationale": "독립 질문에 필요한 제보, 유지보수자 답변, 확인 범위를 원문에서 검토했다.",
            "reason_codes": [signal], "curated_content": snippets, "evidence": [evidence], "relations": [],
            "limitations": [{"code": "AS_OF_SOURCE_ONLY", "content_indices": list(range(len(roles))),
                             "note": "해당 스레드의 보고 시점과 확인 범위에 한정한다."}],
        }
    serialized = canonical(choices) + "\n"
    if curation_path.exists() and curation_path.read_text(encoding="utf-8") != serialized:
        raise ValueError("보존한 정제 결정 지문 불일치")
    if not curation_path.exists():
        curation_path.write_text(serialized, encoding="utf-8")
    candidates, _ = filter_corpus(ISSUES, curation_path)
    rows = candidates["candidates"]
    if len(rows) != len(CURATION):
        raise ValueError("독립 스레드 정제 누락")
    return rows


def expanded_snapshot(store):
    found = store.collection.get(include=["documents", "metadatas", "embeddings"])
    return sorted(zip(found["ids"], found["documents"], found["metadatas"],
                      found["embeddings"].tolist(), strict=True), key=lambda row: row[0])


@contextmanager
def expanded_store(protocol, candidates):
    with runtime_store(protocol) as (store, encoder):
        spec = store.spec
        tokenizer = AutoTokenizer.from_pretrained(spec.ref_tokenizer_id, revision=spec.ref_tokenizer_revision,
                                                  local_files_only=True)
        tokenizers = TokenizerBundle(bge_tokenizer=tokenizer)
        for candidate in candidates:
            chunks = generate_candidate_chunks(candidate, ISSUES, tokenizers, spec)
            store.replace_source(SourceKey("github", candidate["candidate_id"]), chunks, encoder, source_root=ROOT)
        snapshot = expanded_snapshot(store)
        snapshot_sha = digest(snapshot)
        print(f"검색 스냅샷 {len(snapshot)}청크 {snapshot_sha}", flush=True)
        yield store, encoder, fit_bm25_from_snapshot(snapshot), snapshot_sha


def compare_regression(store, encoder, bm25, snapshot_sha, protocol):
    verifier = RecordVerifier(protocol)
    previous = {r["query_id"]: r for r in read_rows(T15 / "regression_v5/records.jsonl.gz")
                if r["condition"] == "B" and r["repeat_index"] == 1}
    condition = json.loads((T15 / "grid_v5/selected_condition.json").read_bytes())["configuration"]
    new_protocol = {**protocol, "snapshot_fingerprint": snapshot_sha}
    rows = []
    for qid, question in sorted(verifier.questions.items()):
        search, hits = search_record(store, encoder, verifier, "B", qid, pool=condition["candidate_k"])
        score = score_record(bm25, "R3", search, hits)
        current, _bundle = trial(search, score, hits, condition, new_protocol, question)
        before = previous[qid]["metrics"]
        after = current["metrics"]
        rows.append({"query_id": qid, "before": before, "after": after,
                     "same_selected_chunks": previous[qid]["selected_chunk_ids"] == current["selected_chunk_ids"]})
    return {"snapshot_sha256": snapshot_sha, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-questions", action="store_true")
    mode.add_argument("--regression", action="store_true", help="보존 재작성만으로 기존 100문항 회귀 비교")
    args = parser.parse_args()
    questions = verify_questions()
    if args.verify_questions:
        with TemporaryDirectory() as temp:
            assert len(new_candidates(Path(temp) / "curation.json")) == 4
        print(f"독립 질문과 정제 원문 검증 {len(questions)}개")
        return
    name = "regression.json" if args.regression else "search_inputs.jsonl.gz"
    output = args.output_dir / name
    if output.exists():
        parser.error("이미 검색 기록이 있습니다.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = new_candidates(args.output_dir / "curation.json")
    protocol = json.loads(PROTOCOL.read_bytes())
    os.environ["LLM_PROVIDER"] = "codex"
    os.environ["LLM_MODEL"] = "gpt-5.6-sol"
    with expanded_store(protocol, candidates) as (store, encoder, bm25, snapshot_sha):
        if args.regression:
            report = compare_regression(store, encoder, bm25, snapshot_sha, protocol)
            output.write_text(canonical(report) + "\n", encoding="utf-8")
            return
        observations = []
        generation = []

        def rewrite(prompt):
            text, runtime = _runtime_generate(prompt)
            generation.append({"prompt": prompt, "output": text, "runtime": runtime})
            return text

        nodes = create_search_nodes(store, encoder, generate=rewrite, snapshot_ref=snapshot_sha,
                                    rewrite_enabled=True, reranker=bm25,
                                    candidate_k=20, top_k=5, min_score=0.5, rerank_weight=0.25,
                                    observe=observations.append)
        rows = []
        for question in questions:
            print(f"검색 {question['id']}", flush=True)
            with generation_time_budget(120):
                request = RequestInput(request_id=question["id"], text=question["question"])
                found = nodes[f"SEARCH_{question['source_type'].upper()}"]({"request": request})
            rows.append({**question, "retrieval": asdict(found["retrieval"]) if found.get("retrieval") else None,
                         "search": observations.pop(), "rewrite": generation.pop() if generation else None})
    with output.open("xb") as stream:
        stream.write(gzip.compress("".join(canonical(r) + "\n" for r in rows).encode(), mtime=0))


if __name__ == "__main__":
    main()
