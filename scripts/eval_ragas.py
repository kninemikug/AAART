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
FAITHFULNESS_VERDICTS = ROOT / EVAL / "ragas_v1/faithfulness_verdicts_v1.jsonl"
SOL_COMPLETION = ROOT / EVAL / "ragas_v2/sol_answers_v1.jsonl.gz"
COMPLETED_VERDICTS = SOL_COMPLETION.with_name(FAITHFULNESS_VERDICTS.name)
PAIR_RESULTS = SOL_COMPLETION.parent / "paired"
MINIMAX_ANSWERS = PAIR_RESULTS / "minimax_answers_v1.jsonl.gz"
PAIR_VERDICTS = PAIR_RESULTS / "faithfulness_verdicts_v1.jsonl"
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


def attach_sol_answer(row, record, sources):
    """누락된 문항에 동일 T15 검색 조건의 실제 Sol 실행을 연결한다."""
    qid = row["query_id"]
    message = f"추가 Sol 실행 입력 또는 생성 조건 불일치: {qid}"
    config = sources["protocol"]["answer"]
    archived = next(r for r in sources["answers"] if r["track"] == "T15")
    original_prompt = archived["prompt"]
    original_full = archived["generation"]["request"]["full_prompt"]
    prefix = f"{original_prompt['system_instruction']}\n\n{original_prompt['user_prompt']}"
    suffix = original_full.removeprefix(prefix)
    obs = record["observation"]
    req = obs["request"]
    meta = obs["runtime_meta"]
    trace = meta["_trace"]
    system, user = obs["system_instruction"], obs["user_prompt"]
    raw = json.loads(obs["raw_response"])
    status = record["actual_status"]
    require(row["answer"] is None and record["query_id"] == qid
            and record["input_sha256"] == row["input_sha256"]
            and record["bundle_sha256"] == row["search_run"]["bundle_sha256"]
            and obs["query"] == row["question"]
            and record["error"] is None and obs["error"] is None
            and obs["custom_generation"] is False and obs["call_count"] == 1
            and record["provider"] == meta["llm_provider"] == config["provider"]
            and record["model"] == meta["model_id"] == req["model"] == config["model"]
            and req["kind"] == "codex" and req["prompt_version"] == req["response_schema"] == config["prompt_version"]
            and system == original_prompt["system_instruction"]
            and user.startswith(prompt_context(row["retrieved_contexts"]))
            and obs["prompt_hash"] == sha256(f"{system}\n{user}")
            and req["full_prompt"] == f"{system}\n\n{user}{suffix}"
            and req["sha256"] == sha256(req["full_prompt"])
            and trace["process_returncode"] == 0 and trace["validation"]["status"] == "verified"
            and trace["execution_policy"] == archived["generation"]["trace"]["execution_policy"]
            and status == obs["status"] == raw["status"]
            and isinstance(raw["answer"], str) and raw["answer"].strip(), message)
    completed = {k: v for k, v in row.items() if k != "input_sha256"}
    completed.update(
        answer=raw["answer"], answer_missing_reason=None, context_origin="t17_prompt",
        answer_run={**config, "run_id": f"t23-sol-completion-v1:{qid}", "track": "T15",
                    "status": status, "prompt_sha256": obs["prompt_hash"], "cli_version": trace["cli_version"],
                    "parent_input_sha256": row["input_sha256"], "record_sha256": sha256(canonical(record))},
    )
    completed["input_sha256"] = sha256(canonical(completed))
    return completed


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
    groups = {"all": paired}
    common = [(r, s) for r, s in paired if all(s[m]["value"] is not None for m in METRICS)]
    if common:
        groups["common"] = common
    supplemental = [(r, s) for r, s in paired if r["answer_run"] and "parent_input_sha256" in r["answer_run"]]
    if supplemental:
        groups["supplemental"] = supplemental
    groups.update({
        "positive": [(r, s) for r, s in paired if not r["is_negative"]],
        "negative": [(r, s) for r, s in paired if r["is_negative"]],
        "t11_slice1": [(r, s) for r, s in paired if r["t11_slice1"]],
        "t14_representative": [(r, s) for r, s in paired if r["t14_representative"]],
    })
    totals = {}
    for name, group in groups.items():
        totals[name] = {"questions": len(group), "answers": sum(r["answer"] is not None for r, _ in group)}
        for metric in METRICS:
            values = [s[metric]["value"] for _, s in group if s[metric]["value"] is not None]
            missing = Counter(s[metric]["reason"] for _, s in group if s[metric]["reason"])
            totals[name][metric] = {"value": mean(values) if values else None, "scored": len(values), "missing": dict(missing)}
    faithfulness = [s["faithfulness"] for s in scores if s["faithfulness"]["value"] is not None]
    summary = {
        "schema_version": 1, "dataset_id": sources["questions"]["dataset_id"],
        "evaluation_scope": "archived_t15_t17_regression", "context_backend": "ragas_id_formula_stdlib",
        "search": {**{k: sources["selection"][k] for k in ("condition_id", "candidate_k", "top_k", "min_score", "rerank_weight")},
                   "reranker": "BM25", "rewrite": True, "hyde": False},
        "generation": sources["protocol"]["answer"], "source_sha256": sources["hashes"],
        "faithfulness_verdicts_sha256": verdict_sha, "groups": totals,
        "faithfulness_evaluators": sorted({s["faithfulness"]["evaluator"] for s in scores
                                           if "evaluator" in s["faithfulness"]}),
        "faithfulness_claims": {"supported": sum(s["numerator"] for s in faithfulness),
                               "total": sum(s["denominator"] for s in faithfulness)},
        "source_counts": dict(Counter(row["source_type"] for row in rows)),
        "answer_status_counts": dict(Counter(row["answer_run"]["status"] for row in rows if row["answer_run"])),
    }
    if supplemental:
        summary.update(schema_version=2, evaluation_scope="t15_t17_sol_completion",
                       answer_sources={"archived": totals["all"]["answers"] - len(supplemental),
                                       "supplemental": len(supplemental),
                                       "archived_cli_versions": sorted({r["generation"]["trace"]["cli_version"]
                                                                        for r in sources["answers"] if r["track"] == "T15"}),
                                       "supplemental_cli_versions": sorted({r["answer_run"]["cli_version"]
                                                                            for r, _ in supplemental})})
    return summary


def render_report(summary):
    labels = {"all": "T8-1 전체", "common": "세 지표 공통 표본", "supplemental": "추가 평가 문항",
              "positive": "근거형", "negative": "반증형",
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
    evaluator_ids = ", ".join(f"`{name}`" for name in summary["faithfulness_evaluators"])
    claim_counts = summary["faithfulness_claims"]
    judging = (f"평가기 {evaluator_ids}의 원자 주장 판정을 사용했다. "
               f"전체 사실 주장 {claim_counts['total']}개 중 {claim_counts['supported']}개가 지지됐다. "
               if evaluator_ids else "")
    version = summary["schema_version"]
    answer_sources = summary.get("answer_sources")
    answer_notes = f"답변 기록이 없는 {overall['questions'] - overall['answers']}문항은 검색 문맥과 `answer: null`을 기록했다."
    sources_link = "[T17 최종 감사](t15-rerank/audit_v6/answers.json)"
    if answer_sources:
        previous_cli = ", ".join(answer_sources["archived_cli_versions"])
        new_cli = ", ".join(answer_sources["supplemental_cli_versions"])
        answer_notes = (f"기존 {answer_sources['archived']}건과 동일 검색 문맥·모델·프롬프트의 추가 실호출 "
                        f"{answer_sources['supplemental']}건을 합쳤다. 기존 실행은 {previous_cli}, 추가 실행은 "
                        f"{new_cli}로 수행했다. 기존 주장별 판정은 입력 지문을 대조해 재사용했다.")
        if overall["answers"] < overall["questions"]:
            answer_notes += f" 미생성 {overall['questions'] - overall['answers']}문항을 기록했다."
        sources_link = ("[추가 생성 원본](ragas_v2/sol_answers_v1.jsonl.gz) · "
                        "[주장별 판정](ragas_v2/faithfulness_verdicts_v1.jsonl) · " + sources_link)
    paired_text = ""
    if comparison := summary.get("paired_comparison"):
        paired_rows = []
        for key, model in (("sol", "GPT-5.6 Sol"), ("minimax", "MiniMax M3.1 Flash")):
            metric = comparison[key]
            paired_rows.append(
                f"| {model} | {comparison[key + '_answers']}/{comparison['questions']} | "
                f"{display(overall['context_precision'])} | {display(overall['context_recall'])} | "
                f"{display(metric)} ({metric['scored']}/{comparison['questions']}) | "
                f"{display({'value': metric['common_value']})} |"
            )
        paired_text = f"""

## 동일 검색 입력의 Sol·MiniMax 비교

두 모델에 동일 T15 문맥과 `t17-answer-v1` 프롬프트를 전달했다. `{comparison['evaluator']}`가 생성 모델명을 숨긴 답변에서 주장을 분해하고 같은 문맥을 사용해 두 답변을 판정했다. 동일 문항에서 양쪽에 점수가 있는 공통 표본은 {comparison['common_count']}개다. 위 표의 기존 Sol 점수는 MiniMax가 채점한 보존 결과다.

| 답변 모델 | 실답변 | Context precision | Context recall | Faithfulness | 공통 표본 faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(paired_rows)}

검색 지표 열은 100문항 전체의 값이다. 공통 {comparison['common_count']}문항만 집계한 context precision은 {display(comparison['common_search']['context_precision'])}, context recall은 {display(comparison['common_search']['context_recall'])}이다.

[MiniMax 실답변과 요청 원본](ragas_v2/paired/minimax_answers_v1.jsonl.gz) · [독립 판정 원본](ragas_v2/paired/faithfulness_verdicts_v1.jsonl) · [문항별 비교 점수](ragas_v2/paired/scores.jsonl)"""
    return f"""# T23 RAGAS 평가 리포트 v{version}

T8-1 `{summary['dataset_id']}` {overall['questions']}문항(RawPedia {summary['source_counts']['rawpedia']}·GitHub {summary['source_counts']['github']})의 T15 검색 기록과 {overall['answers']}개 T17 실답변을 재평가했다. T8-2와 T15에서 사용한 회귀 표본이다. WBS §4에 적힌 15개 규모의 대표 실행은 T11·T14에서 서로 다른 부분집합으로 확인했다. Task 23 카드와 WBS의 A-23 상세 항목에 따라 전체 100개를 사용했다. [평가 계획](../../docs/T23_execution_plan.md)

| 입력 | 질문 | 보존 답변 | ID-based context precision | ID-based context recall | Faithfulness |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(table)}

점수 옆 괄호는 실제 점수를 집계한 행 수와 대상 질문 수다. 질문별 점수를 매크로 평균했다. 세 지표 공통 표본은 세 점수가 모두 있는 동일 문항에서 각 평균을 계산한다. 근거형은 정본의 지원 원문 ID, 반증형은 사전 지정한 반증 원문 ID를 사용했다. 정밀도는 검색한 고유 원문 ID 중 허용된 ID의 비율이고, 재현율은 허용 원문 ID 중 검색된 ID의 비율이다. 평가 단위는 원문 문서이며 GitHub에서는 각 이슈·Discussion·댓글 세그먼트를 해당 원문 ID로 센다. [Precision 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_precision/) · [Recall 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/context_recall/){paired_text}

## 실행 증거와 범위

- 검색은 T15 v5의 B 첫 반복을 사용했다. 재작성 on, HyDE off, {search['reranker']} 후보 {search['candidate_k']}·top {search['top_k']}·최소 점수 {search['min_score']}·가중치 {search['rerank_weight']}에서 선택한 청크를 보존 스냅샷으로 복원했다. [T15 결과와 실행 인계](../../docs/T15_results_v5.md)
- 같은 검색 bundle이 확인된 T17 `T15` 트랙(`{generation['provider']} / {generation['model']} / {generation['prompt_version']}`)의 응답 상태는 {status}이다. {answer_notes} {sources_link}
- T17 감사는 당시 코드 `08e484294`에서 138건 전부 재통과했다. 현재 브랜치에서는 계보 검증이 통과했고 뒤이은 감사가 T15 당시 코드 지문 목록과의 차이로 중단됐다. T23은 보존 manifest, 원문 세그먼트, 검색 bundle 지문과 실제 생성 요청 문맥을 대조했다.
- Faithfulness는 제출 문맥에서 뒷받침된 원자 주장 수를 전체 사실 주장 수로 나눈다. {judging}미산출 사유는 {reasons or '없음'}이다. [Faithfulness 정의](https://docs.ragas.io/en/v0.4.0/concepts/metrics/available_metrics/faithfulness/) · [보존 판정과 방법](../../docs/T23_execution_plan.md#구현과-산출물)
- 별도 최종 스택 선정 게이트와 독립 평가가 미완료다. 이 결과는 보존된 T15·T17 조건에 적용된다. [Task 23 및 선행 게이트](../../tasks/todo.md#task-23-ragas-평가-a-23)

## 재실행

```bash
venv/bin/python scripts/eval_ragas.py
```

2026-11-20 KST에 RAGAS 0.4.0의 PyPI 설치 dry-run을 확인했다. 공개된 공식 ID 산식은 Python 3.14.3 표준 라이브러리로 실행했다. 기본 실행에서 임시 출력 경로 두 곳의 산출물 네 파일이 바이트 단위로 일치했다. `--output-dir`로 출력 경로를 지정할 수 있다. [비교 명령과 원자 주장 판정 파일 형식](../../docs/T23_execution_plan.md)

질문별 검색 문맥·답변·출처는 [입력 JSONL(gzip)](ragas_v{version}/inputs.jsonl.gz), 점수·분모·누락 사유는 [점수 JSONL](ragas_v{version}/scores.jsonl), 원본 SHA-256 및 집계는 [요약 JSON](ragas_v{version}/summary.json)에 있다.
"""


def write_outputs(output, rows, scores, summary, paired_scores=None):
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"ragas_v{summary['schema_version']}"
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
        if paired_scores is not None:
            pair_output = target / "paired"
            pair_output.mkdir(exist_ok=True)
            staged_scores = stage / "paired_scores.jsonl"
            staged_scores.write_text("".join(canonical(s) + "\n" for s in paired_scores), encoding="utf-8")
            staged_scores.replace(pair_output / "scores.jsonl")
        (stage / "report_v1.md").replace(output / "report_v1.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / EVAL, help="리포트와 평가 산출물의 상위 경로")
    supplements = parser.add_mutually_exclusive_group()
    supplements.add_argument("--archived-only", action="store_true", help="T17 보존 답변 69건만 집계")
    supplements.add_argument("--supplemental-answers", type=Path, help="누락 문항의 추가 Sol 실호출 JSONL")
    parser.add_argument("--faithfulness-verdicts", type=Path,
                        help="보존 판정을 대신할 고정 입력의 원자 주장별 판정 JSONL")
    args = parser.parse_args()
    try:
        sources = read_sources()
        rows = assemble_inputs(sources)
        supplemental_path = args.supplemental_answers
        if not args.archived_only and supplemental_path is None and SOL_COMPLETION.is_file():
            supplemental_path = SOL_COMPLETION
        if supplemental_path is not None:
            additions = index_rows(read_rows(supplemental_path))
            require(additions and additions.keys() <= {r["query_id"] for r in rows if r["answer"] is None},
                    "추가 Sol 실행은 답변 미보존 문항에만 결합 가능")
            rows = [attach_sol_answer(row, additions[row["query_id"]], sources) if row["query_id"] in additions
                    else row for row in rows]
            sources["hashes"]["t23_sol_completion"] = hashlib.sha256(supplemental_path.read_bytes()).hexdigest()
        reviews, verdict_sha = {}, None
        verdicts_path = args.faithfulness_verdicts
        if (verdicts_path is None and supplemental_path is not None
                and supplemental_path.resolve() == SOL_COMPLETION and COMPLETED_VERDICTS.is_file()):
            verdicts_path = COMPLETED_VERDICTS
        elif verdicts_path is None and FAITHFULNESS_VERDICTS.is_file():
            verdicts_path = FAITHFULNESS_VERDICTS
        if verdicts_path is not None:
            data = verdicts_path.read_bytes()
            verdict_sha = hashlib.sha256(data).hexdigest()
            reviews = index_rows(json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip())
            require(reviews.keys() <= {row["query_id"] for row in rows}, "고정 질문셋 밖 판정")
        scores = [{"query_id": row["query_id"], "input_sha256": row["input_sha256"],
                   **context_scores(row["allowed_source_doc_ids"], row["retrieved_source_doc_ids"]),
                   "faithfulness": faithfulness_score(row, reviews.get(row["query_id"]))} for row in rows]
        summary = build_summary(sources, rows, scores, verdict_sha)
        paired_scores = None
        if (supplemental_path is not None and supplemental_path.resolve() == SOL_COMPLETION
                and MINIMAX_ANSWERS.is_file() and PAIR_VERDICTS.is_file()):
            if __package__:
                from .t23_minimax_pairs import score_comparison
            else:
                from t23_minimax_pairs import score_comparison
            comparison, paired_scores = score_comparison(
                rows, index_rows(read_rows(MINIMAX_ANSWERS)), index_rows(read_rows(PAIR_VERDICTS)),
            )
            summary["paired_comparison"] = comparison
            for path in (MINIMAX_ANSWERS, PAIR_VERDICTS):
                summary["source_sha256"][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_outputs(args.output_dir, rows, scores, summary, paired_scores)
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"평가 실패 — {error}\n")
    print(json.dumps(summary["groups"]["all"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
