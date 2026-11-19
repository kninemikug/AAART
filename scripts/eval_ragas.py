#!/usr/bin/env python3
"""T23 고정 질문에 대해 T15/T17 보존 기록으로 RAGAS 지표를 재집계한다."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
EVAL = Path("data/eval")
T15 = EVAL / "t15-rerank"
SEARCH_RUN = T15 / "regression_v5"
ANSWER_RUN = T15 / "t17_v5_complete_20261020_r3"
ANSWER_AUDIT = T15 / "audit_v6/answers.json"
T14_RECORDS = Path("docs/T14_ab_eval_records.jsonl")
T14_MANIFEST = Path("docs/T14_ab_eval_manifest.json")
CONDITION = "R3_c20_k5_min0.5_w0.25"
METRICS = ("context_precision", "context_recall", "faithfulness")
REASONS = {
    "empty_retrieval": "검색 원문 ID 없음",
    "empty_reference": "허용 원문 ID 없음",
    "missing_answer": "T15 설정의 T17 답변 미실행",
    "missing_claim_verdicts": "동일 입력의 원자 주장 판정 미확보",
    "no_factual_claims": "판정 파일에 사실 주장 없음",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def index_rows(rows):
    indexed = {}
    for row in rows:
        qid = row["query_id"]
        require(qid not in indexed, f"중복 질문: {qid}")
        indexed[qid] = row
    return indexed


def read_sources():
    """고정 실행의 manifest에서 실제로 사용한 증거 파일을 검증한다."""
    hashes = {}

    def checked(path, expected=None):
        path = Path(path)
        require((ROOT / path).resolve().is_relative_to(ROOT), f"저장소 밖 증거 경로: {path}")
        with (ROOT / path).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(expected is None or actual == expected, f"원본 SHA-256 불일치: {path}")
        hashes[path.as_posix()] = actual
        return ROOT / path

    def read_json(path, expected=None):
        return json.loads(checked(path, expected).read_bytes())

    t17 = read_json(ANSWER_RUN / "manifest.json")
    search = read_json(SEARCH_RUN / "manifest.json", t17["retrieval_manifest_sha256"])
    require(t17["retrieval_run"] == SEARCH_RUN.as_posix()
            and t17["protocol_sha256"] == search["protocol_sha256"]
            and t17["selected_sha256"] == search["selected_sha256"], "T15/T17 실행 설정 불일치")
    protocol = read_json(search["protocol_path"], search["protocol_sha256"])
    selection = read_json(search["selected_path"], search["selected_sha256"])
    require(selection["selected_condition"] == CONDITION, "T15 채택 조건 불일치")
    require(read_json(ANSWER_AUDIT)["overall_verdict"] == "PASS", "T17 최종 감사 미통과")

    def protocol_input(name):
        entry = protocol["inputs"][name]
        return checked(entry["path"], entry["sha256"])

    questions = json.loads(protocol_input("queries").read_bytes())
    snapshot = json.loads(protocol_input("snapshot").read_bytes())
    require(sha256(canonical(snapshot)) == protocol["snapshot_fingerprint"], "스냅샷 지문 불일치")
    t14 = read_json(T14_MANIFEST)
    return {
        "hashes": hashes, "protocol": protocol, "selection": selection["configuration"],
        "questions": questions, "snapshot": snapshot, "slice1": read_rows(protocol_input("slice1")),
        "t14": read_rows(checked(T14_RECORDS, t14["legacy_artifacts_sha256"][T14_RECORDS.as_posix()])),
        "trials": read_rows(checked(SEARCH_RUN / "records.jsonl.gz", search["artifacts"]["records.jsonl.gz"])),
        "searches": read_rows(checked(SEARCH_RUN / "search_records.jsonl.gz",
                                      search["artifacts"]["search_records.jsonl.gz"])),
        "answers": read_rows(checked(ANSWER_RUN / "answer_records.jsonl", t17["artifacts"]["answer_records.jsonl"])),
    }


def project_chunk(chunk):
    """스냅샷의 T09 ID를 T15/T17 bundle의 원문 세그먼트로 펼친다."""
    chunk_id, content, metadata, _vector = chunk
    require(sha256(content) == metadata["content_sha256"], f"청크 본문 불일치: {chunk_id}")
    source_type = metadata["source_type"]
    segments = json.loads(metadata["source_segments_json"])
    require(segments and not metadata["excluded"], f"선택 청크 원문 없음: {chunk_id}")
    evidence = []
    for segment in segments:
        start, end = segment["content_char_start"], segment["content_char_end"]
        text = content[start:end]
        require(0 <= start < end <= len(content) and sha256(text) == segment["segment_sha256"],
                f"원문 세그먼트 범위/지문 불일치: {chunk_id}")
        evidence.append({
            "chunk_id": chunk_id, "doc_id": segment["doc_id"],
            "source_group_id": metadata["source_group_id"], "source_type": source_type,
            "source_path": segment["source_path"], "target_url": segment["target_url"],
            "source_location": canonical({"source_segment": segment, "section_title": metadata["section_title"]}),
            "text": text, "product_scope": {"github": "ART", "rawpedia": "RawTherapee"}[source_type],
        })
    return evidence


def prompt_context(contexts):
    """저장된 T17 프롬프트의 검색 문맥 블록과 대조할 문자열을 만든다."""
    blocks = []
    for hit in contexts:
        section = hit["source_location"]["section_title"]
        blocks.append("\n".join((
            f"[{hit['citation_id']}]", f"- Chunk ID: {hit['chunk_id']}",
            f"- Source Type: {hit['source_type']}", f"- Product Scope: {hit['product_scope']}",
            f"- Doc ID / Group ID: {hit['doc_id']} / {hit['source_group_id']}",
            f"- Section Title: {section}", f"- Target URL: {hit['target_url']}", f"- 본문:\n{hit['text']}",
        )))
    text = "\n\n---\n\n".join(blocks) or "(검색된 문맥이 없습니다.)"
    return f"[검색 문맥]\n\n{text}\n\n[제공된 인용 목록]\n"


def read_answer(qid, question, archived, bundle, contexts, config):
    prompt, gen, output = (archived[k] for k in ("prompt", "generation", "output"))
    require(archived["input"]["query_original"] == question
            and archived["original_run_id"] == f"{SEARCH_RUN.name}:T15:{qid}"
            and archived["retrieval"] == bundle, f"T17 질문 또는 부모 검색 불일치: {qid}")
    require(gen["provider"] == config["provider"] and gen["model"] == config["model"]
            and gen["is_mock"] is False and gen["call_count"] == 1 and output["error"] is None
            and prompt["version"] == config["prompt_version"], f"T17 실행 조건 불일치: {qid}")
    system, user = prompt["system_instruction"], prompt["user_prompt"]
    request = gen["request"]
    require(user.startswith(prompt_context(contexts))
            and sha256(f"{system}\n{user}") == prompt["prompt_hash"]
            and request["full_prompt"].startswith(f"{system}\n\n{user}")
            and sha256(request["full_prompt"]) == request["sha256"], f"T17 문맥 또는 요청 불일치: {qid}")
    raw = json.loads(gen["raw_response"])
    require(raw["status"] == output["status"] and isinstance(raw["answer"], str)
            and raw["answer"].strip(), f"T17 원응답 불일치: {qid}")
    return raw["answer"], {
        **config, "run_id": archived["run_id"], "track": archived["track"],
        "status": raw["status"], "prompt_sha256": prompt["prompt_hash"],
    }


def assemble_inputs(sources):
    dataset, protocol = sources["questions"], sources["protocol"]
    questions = index_rows(dataset["queries"])
    require(dataset["dataset_id"] == "t08-1-100-v1"
            and set(questions) == {f"Q{i:03}" for i in range(1, 101)}, "고정 질문셋 불일치")

    def first_b(kind):
        rows = index_rows(row for row in sources[kind] if row["condition"] == "B" and row["repeat_index"] == 1)
        require(rows.keys() == questions.keys(), f"T15 B 첫 반복 질문 불일치: {kind}")
        return rows

    trials, searches = first_b("trials"), first_b("searches")
    answers = index_rows(row for row in sources["answers"] if row["track"] == "T15")
    require(len(answers) == 69 and answers.keys() <= questions.keys(), "최종 T17 답변 표본 불일치")
    t11_sample = index_rows(sources["slice1"])
    t14_sample = index_rows(row for row in sources["t14"] if row["condition"] == "A" and row["is_representative"])
    require(len(t11_sample) == len(t14_sample) == 15 and (t11_sample.keys() | t14_sample.keys()) <= questions.keys(),
            "T11/T14 대표 표본 불일치")
    chunks = {chunk[0]: project_chunk(chunk) for chunk in sources["snapshot"] if not chunk[2]["excluded"]}
    rows = []
    for qid, q in sorted(questions.items()):
        question = q["query"]
        if qid in t11_sample:
            require(t11_sample[qid]["input"]["query_original"] == question, f"T11 대표 질문 불일치: {qid}")
        if qid in t14_sample:
            require(t14_sample[qid]["query_original"] == question, f"T14 대표 질문 불일치: {qid}")
        trial, search = trials[qid], searches[qid]
        selected = trial["selected_chunk_ids"]
        require(trial["condition_id"] == CONDITION and len(selected) == len(set(selected))
                and set(selected) <= {hit["chunk_id"] for hit in search["candidates"]}, f"T15 청크 선택 불일치: {qid}")
        hits, contexts = [], []
        for rank, chunk_id in enumerate(selected, 1):
            for segment, hit in enumerate(chunks[chunk_id], 1):
                hits.append(hit)
                contexts.append({**hit, "citation_id": f"C{rank}S{segment}",
                                 "source_location": json.loads(hit["source_location"])})
        bundle = {"query": search["search_query"], "source_filter": search["source_type"].upper(),
                  "hits": hits, "snapshot_ref": protocol["snapshot_fingerprint"]}
        require(sha256(canonical(bundle)) == trial["bundle_digest"], f"T15 검색 bundle 불일치: {qid}")

        answer, answer_run = None, None
        if qid in answers:
            answer, answer_run = read_answer(qid, question, answers[qid], bundle, contexts, protocol["answer"])
        support_ids = sorted(set(q["gold_support_doc_ids"]))
        counter_ids = sorted({e["doc_id"] for e in q["evidence"] if e["role"] == "counterevidence"})
        row = {
            "query_id": qid, "question": question, "source_type": q["source_type"],
            "is_negative": q["difficulty"] == "negative", "t11_slice1": qid in t11_sample,
            "t14_representative": qid in t14_sample, "gold_support_doc_ids": support_ids,
            "counterevidence_doc_ids": counter_ids, "allowed_source_doc_ids": sorted(set(support_ids + counter_ids)),
            "allowed_evidence": q["evidence"], "retrieved_source_doc_ids": sorted({h["doc_id"] for h in hits}),
            "retrieved_contexts": contexts, "context_origin": "t17_prompt" if answer_run else "t15_bundle",
            "search_run": {"condition": "B", "condition_id": CONDITION, "repeat_index": 1,
                           "query": bundle["query"], "source_filter": bundle["source_filter"],
                           "bundle_sha256": trial["bundle_digest"]},
            "answer": answer, "answer_run": answer_run,
            "answer_missing_reason": None if answer_run else "missing_answer",
        }
        row["input_sha256"] = sha256(canonical(row))
        rows.append(row)
    return rows


def ratio(numerator, denominator, missing_reason):
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "reason": None if denominator else missing_reason}


def context_scores(allowed_ids, retrieved_ids):
    allowed, retrieved = set(allowed_ids), set(retrieved_ids)
    overlap = len(allowed & retrieved)
    return {"context_precision": ratio(overlap, len(retrieved), "empty_retrieval"),
            "context_recall": ratio(overlap, len(allowed), "empty_reference")}


def faithfulness_score(row, review):
    if review is None:
        reason = "missing_answer" if row["answer"] is None else "missing_claim_verdicts"
        return ratio(None, None, reason)
    qid = row["query_id"]
    require(row["answer"] is not None and review.get("input_sha256") == row["input_sha256"], f"판정 입력 불일치: {qid}")
    evaluator, claims = review.get("evaluator"), review.get("claims")
    require(isinstance(evaluator, str) and evaluator.strip() and isinstance(claims, list), f"판정 형식 오류: {qid}")
    statements = set()
    for claim in claims:
        statement = claim.get("statement") if isinstance(claim, dict) else None
        require(isinstance(statement, str) and statement.strip() and statement.strip() not in statements
                and type(claim.get("supported")) is bool, f"원자 주장 판정 형식/중복 오류: {qid}")
        statements.add(statement.strip())
    score = ratio(sum(c["supported"] for c in claims), len(claims), "no_factual_claims")
    return {**score, "evaluator": evaluator, "verdict_sha256": sha256(canonical(review))}


def build_summary(sources, rows, scores, verdict_sha):
    paired = list(zip(rows, scores, strict=True))
    groups = {
        "all": paired, "positive": [(r, s) for r, s in paired if not r["is_negative"]],
        "negative": [(r, s) for r, s in paired if r["is_negative"]],
        "t11_slice1": [(r, s) for r, s in paired if r["t11_slice1"]],
        "t14_representative": [(r, s) for r, s in paired if r["t14_representative"]],
    }
    totals = {}
    for name, group in groups.items():
        totals[name] = {"questions": len(group), "answers": sum(r["answer"] is not None for r, _ in group)}
        for metric in METRICS:
            values = [s[metric]["value"] for _, s in group if s[metric]["value"] is not None]
            missing = Counter(s[metric]["reason"] for _, s in group if s[metric]["reason"])
            totals[name][metric] = {"value": mean(values) if values else None, "scored": len(values), "missing": dict(missing)}
    return {
        "schema_version": 1, "dataset_id": sources["questions"]["dataset_id"],
        "evaluation_scope": "archived_t15_t17_regression", "context_backend": "ragas_id_formula_stdlib",
        "search": {**{k: sources["selection"][k] for k in ("condition_id", "candidate_k", "top_k", "min_score", "rerank_weight")},
                   "reranker": "BM25", "rewrite": True, "hyde": False},
        "generation": sources["protocol"]["answer"], "source_sha256": sources["hashes"],
        "faithfulness_verdicts_sha256": verdict_sha, "groups": totals,
        "source_counts": dict(Counter(row["source_type"] for row in rows)),
        "answer_status_counts": dict(Counter(row["answer_run"]["status"] for row in rows if row["answer_run"])),
    }


def render_report(summary):
    labels = {"all": "T8-1 전체", "positive": "근거형", "negative": "반증형",
              "t11_slice1": "T11 Slice 1 대표", "t14_representative": "T14 대표"}
    groups = summary["groups"]
    overall = groups["all"]
    search = summary["search"]
    generation = summary["generation"]

    def display(metric):
        value = metric["value"]
        return f"{value:.6f}" if value is not None else "`null`"

    table = []
    for name, group in groups.items():
        metrics = [f"{display(group[m])} ({group[m]['scored']}/{group['questions']})" for m in METRICS]
        table.append("| " + " | ".join((labels[name], str(group["questions"]), str(group["answers"]), *metrics)) + " |")

    missing = overall["faithfulness"]["missing"]
    reasons = ", ".join(f"{REASONS[key]} {count}건" for key, count in sorted(missing.items()))
    status = ", ".join(f"`{key}` {count}건" for key, count in sorted(summary["answer_status_counts"].items()))
    return f"""# T23 RAGAS 평가 리포트 v1

T8-1 `{summary['dataset_id']}` {overall['questions']}문항(RawPedia {summary['source_counts']['rawpedia']}·GitHub {summary['source_counts']['github']})의 T15 검색 기록과 {overall['answers']}개 T17 실답변을 재평가했다. T8-2와 T15에서 사용한 회귀 표본이다. WBS §4에 적힌 15개 규모의 대표 실행은 T11·T14에서 서로 다른 부분집합으로 확인했다. Task 23 카드와 WBS의 A-23 상세 항목에 따라 전체 100개를 사용했다. [평가 계획](../../docs/T23_execution_plan.md)

| 입력 | 질문 | 보존 답변 | ID-based context precision | ID-based context recall | Faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(table)}

점수 옆 괄호는 실제 점수를 집계한 행 수와 대상 질문 수다. 질문별 점수를 매크로 평균했다. 근거형은 정본의 지원 원문 ID, 반증형은 사전 지정한 반증 원문 ID를 사용했다. 정밀도는 검색한 고유 원문 ID 중 허용된 ID의 비율이고, 재현율은 허용 원문 ID 중 검색된 ID의 비율이다. 평가 단위는 원문 문서이며 GitHub에서는 각 이슈·Discussion·댓글 세그먼트를 해당 원문 ID로 센다. [Precision 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_precision/) · [Recall 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_recall/)

## 실행 증거와 범위

- 검색은 T15 v5의 B 첫 반복을 사용했다. 재작성 on, HyDE off, {search['reranker']} 후보 {search['candidate_k']}·top {search['top_k']}·최소 점수 {search['min_score']}·가중치 {search['rerank_weight']}에서 선택한 청크를 보존 스냅샷으로 복원했다. [T15 결과와 실행 인계](../../docs/T15_results_v5.md)
- 같은 검색 bundle이 확인된 T17 `T15` 트랙(`{generation['provider']} / {generation['model']} / {generation['prompt_version']}`)의 응답 상태는 {status}이다. 답변 기록이 없는 {overall['questions'] - overall['answers']}문항은 검색 문맥과 `answer: null`을 기록했다. [T17 최종 감사](t15-rerank/audit_v6/answers.json)
- T17 감사는 당시 코드 `08e484294`에서 138건 전부 재통과했다. 현재 브랜치에서는 계보 검증이 통과했고 뒤이은 감사가 T15 당시 코드 지문 목록과의 차이로 중단됐다. T23은 보존 manifest, 원문 세그먼트, 검색 bundle 지문과 실제 생성 요청 문맥을 대조했다.
- Faithfulness는 제출 문맥에서 뒷받침된 원자 주장 수를 전체 사실 주장 수로 나눈다. 미산출 사유는 {reasons or '없음'}이다. 기존 T15 수동 검토는 답변 전체를 묶은 판정도 포함하므로 원자 주장별 entailment 입력으로 사용할 수 없다. [Faithfulness 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/faithfulness/)
- 별도 최종 스택 선정 게이트와 독립 평가가 미완료다. 이 결과는 보존된 T15·T17 조건에 적용된다. [Task 23 및 선행 게이트](../../tasks/todo.md#task-23-ragas-평가-a-23)

## 재실행

```bash
venv/bin/python scripts/eval_ragas.py
```

2026-11-20 KST에 RAGAS 0.4.0의 PyPI 설치 dry-run을 확인했다. 공개된 공식 ID 산식은 Python 3.14.3 표준 라이브러리로 실행했다. 기본 실행에서 임시 출력 경로 두 곳의 산출물 네 파일이 바이트 단위로 일치했다. `--output-dir`로 출력 경로를 지정할 수 있다. [비교 명령과 원자 주장 판정 파일 형식](../../docs/T23_execution_plan.md)

질문별 검색 문맥·답변·출처는 [입력 JSONL(gzip)](ragas_v1/inputs.jsonl.gz), 점수·분모·누락 사유는 [점수 JSONL](ragas_v1/scores.jsonl), 원본 SHA-256 및 집계는 [요약 JSON](ragas_v1/summary.json)에 있다.
"""


def write_outputs(output, rows, scores, summary):
    output.mkdir(parents=True, exist_ok=True)
    target = output / "ragas_v1"
    target.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=output) as temporary:
        stage = Path(temporary)
        with (stage / "inputs.jsonl.gz").open("wb") as stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                for row in rows:
                    compressed.write((canonical(row) + "\n").encode("utf-8"))
        (stage / "scores.jsonl").write_text("".join(canonical(s) + "\n" for s in scores), encoding="utf-8")
        (stage / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (stage / "report_v1.md").write_text(render_report(summary), encoding="utf-8")
        for name in ("inputs.jsonl.gz", "scores.jsonl", "summary.json"):
            (stage / name).replace(target / name)
        (stage / "report_v1.md").replace(output / "report_v1.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / EVAL, help="리포트와 ragas_v1 산출물의 상위 경로")
    parser.add_argument("--faithfulness-verdicts", type=Path, help="고정 입력에 대한 원자 주장별 판정 JSONL")
    args = parser.parse_args()
    try:
        sources = read_sources()
        rows = assemble_inputs(sources)
        reviews, verdict_sha = {}, None
        if args.faithfulness_verdicts:
            data = args.faithfulness_verdicts.read_bytes()
            verdict_sha = hashlib.sha256(data).hexdigest()
            reviews = index_rows(json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip())
            require(reviews.keys() <= {row["query_id"] for row in rows}, "고정 질문셋 밖 판정")
        scores = [{"query_id": row["query_id"], "input_sha256": row["input_sha256"],
                   **context_scores(row["allowed_source_doc_ids"], row["retrieved_source_doc_ids"]),
                   "faithfulness": faithfulness_score(row, reviews.get(row["query_id"]))} for row in rows]
        summary = build_summary(sources, rows, scores, verdict_sha)
        write_outputs(args.output_dir, rows, scores, summary)
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"평가 실패 — {error}\n")
    print(json.dumps(summary["groups"]["all"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
