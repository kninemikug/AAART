#!/usr/bin/env python3
"""T17의 같은 질문·검색 문맥을 기준 모델과 경량 후보에 전달한다."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

INPUT = ROOT / "data/eval/ragas_v1/inputs.jsonl.gz"
INPUT_SHA = "a35ebf60e27547d1c687c2a9b71a30fa46b2d7971e2a8aaa62c2c7400f465571"
MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
FINAL_MODELS = MODELS[:2]
FINAL_SEARCH_SHA = "38567146fd4a4d04c5f9a9dc0199c6a0a0485fb1490a4cb5b53810cd8c29955f"
API_PRICES = dict(zip(MODELS, ((4, 0.4, 20), (2, 0.2, 12), (0.2, 0.02, 1.2)), strict=True))
NVIDIA_MODELS = ("z-ai/glm-5.3-flash", "minimaxai/minimax-m3.1-flash")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# 원 제공사의 정규 USD 단가(1M 토큰). NVIDIA 측 캐시 동작은 환산에서 제외한다.
NVIDIA_API_PRICES = dict(zip(NVIDIA_MODELS, ((0.15, 0.50), (0.15, 0.60)), strict=True))
PILOT = {"Q001": "SUPPORTED", "Q033": "SUPPORTED", "Q070": "INSUFFICIENT_EVIDENCE",
         "Q086": "SUPPORTED", "Q092": "SUPPORTED", "Q096": "UNSUPPORTED"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_cases():
    with INPUT.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != INPUT_SHA:
            raise ValueError("고정 T23 입력 지문 불일치")
    with gzip.open(INPUT, "rt", encoding="utf-8") as stream:
        rows = {row["query_id"]: row for row in map(json.loads, stream) if row["query_id"] in PILOT}
    if rows.keys() != PILOT.keys():
        raise ValueError("비교 질문 누락")
    return rows


def pilot_bundle(row):
    search = row["search_run"]
    hits = []
    for context in row["retrieved_contexts"]:
        hit = {key: value for key, value in context.items() if key != "citation_id"}
        hit["source_location"] = canonical(hit["source_location"])
        hits.append(hit)
    bundle = {"query": search["query"], "source_filter": search["source_filter"], "hits": hits,
              "snapshot_ref": "09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6"}
    if digest(bundle) != search["bundle_sha256"]:
        raise ValueError(f"검색 bundle 지문 불일치: {row['query_id']}")
    return bundle


def final_cases(path):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != FINAL_SEARCH_SHA:
            raise ValueError("동결한 독립 검색 입력 지문 불일치")
    fixed_path = ROOT / "data/eval/stack-selection/final_questions_v1.json"
    fixed = {row["id"]: row for row in json.loads(fixed_path.read_bytes())}
    cases = {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for row in map(json.loads, stream):
            qid = row["id"]
            expected = fixed[qid]
            if qid in cases or any(row[k] != expected[k] for k in ("question", "expected_status", "group_id")):
                raise ValueError(f"독립 검색 입력이나 질문 불일치: {qid}")
            retrieval = row["retrieval"]
            if retrieval is None or row["search"]["error"] is not None:
                raise ValueError(f"독립 질문 검색 실패: {qid}")
            for evidence in expected["evidence"]:
                if not any(hit["doc_id"] == evidence["doc_id"] and evidence["quote"] in hit["text"]
                           for hit in retrieval["hits"]):
                    raise ValueError(f"동결 검색 문맥에 지정한 원문 구간이 없음: {qid}/{evidence['doc_id']}")
            case = {"query_id": qid, "question": row["question"], "expected_status": row["expected_status"],
                    "input_sha256": digest({"question": row["question"], "retrieval": retrieval}),
                    "search_run": {"bundle_sha256": digest(retrieval)}, "answer_run": None}
            cases[qid] = (case, retrieval)
    if cases.keys() != fixed.keys():
        raise ValueError("독립 검색 입력 질문 누락")
    return cases


def evaluate(case, bundle, model, timeout):
    from artagent.answer import generation_time_budget
    from artagent.graph.answer import answer_standalone
    from artagent.graph.state import Evidence, RetrievalBundle

    retrieval = RetrievalBundle(**{**bundle, "hits": [Evidence(**hit) for hit in bundle["hits"]]})
    os.environ["LLM_MODEL"] = model
    observation = {}
    with generation_time_budget(timeout):
        answer, error = answer_standalone(case["question"], retrieval, source_root=ROOT, observe=observation.update)
    request = observation.get("request") or {}
    meta = observation.get("runtime_meta") or {}
    archived = case["answer_run"]
    same_prompt = observation.get("prompt_hash") == archived["prompt_sha256"] if archived else None
    if answer and (same_prompt is False or request.get("model") != model or meta.get("model_id") != model):
        raise ValueError(f"실제 프롬프트 또는 모델 불일치: {case['query_id']}/{model}")
    return {
        "query_id": case["query_id"], "model": model, "provider": meta.get("llm_provider"),
        "input_sha256": case["input_sha256"], "bundle_sha256": case["search_run"]["bundle_sha256"],
        "archived_run_id": archived["run_id"] if archived else None, "archived_prompt_match": same_prompt,
        "expected_status": case["expected_status"], "actual_status": answer.status if answer else None,
        "actual_cost_usd": None, "error": asdict(error) if error else None, "observation": observation,
    }


def read_attempt(path, case, model):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        row = json.load(stream)
    fixed = (case["input_sha256"], case["query_id"], case["search_run"]["bundle_sha256"], model)
    actual = tuple(row.get(key) for key in ("input_sha256", "query_id", "bundle_sha256", "model"))
    if actual != fixed or row["expected_status"] != case["expected_status"]:
        raise ValueError(f"보존한 시도 기록 불일치: {path}")
    return row


def attempt_path(directory, qid, model):
    return directory / f"{qid}-{model.replace('/', '--')}.json.gz"


def request_matches(row, case, model):
    observed = row["observation"]
    system, user = observed["system_instruction"], observed["user_prompt"]
    prompt = hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()
    request = observed["request"]
    if request["model"] != model or prompt != observed["prompt_hash"]:
        return False
    if case["answer_run"] and case["answer_run"]["prompt_sha256"] != prompt:
        return False
    if model in NVIDIA_MODELS:
        payload = request["payload"]
        return (row["provider"] == "openai-compatible" and request["kind"] == "chat-completions"
                and observed["runtime_meta"]["endpoint"] == f"{NVIDIA_BASE_URL}/chat/completions"
                and payload["model"] == model and digest(payload) == request["sha256"]
                and payload["messages"] == [{"role": "system", "content": system}, {"role": "user", "content": user}])
    return (row["provider"] == "codex-cli"
            and hashlib.sha256(request["full_prompt"].encode()).hexdigest() == request["sha256"])


def estimate_usage(model, observation):
    usage = observation.get("usage")
    if model in NVIDIA_MODELS:
        # JSON/인용 검증에서 실패한 응답도 API가 사용량을 반환했다면 집계한다.
        if not usage:
            response = (observation.get("runtime_meta") or {}).get("_response_body") or {}
            usage = response.get("usage") if isinstance(response, dict) else None
        keys = ("prompt_tokens", "completion_tokens")
        if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in keys):
            in_price, out_price = NVIDIA_API_PRICES[model]
            return (usage[keys[0]] * in_price + usage[keys[1]] * out_price) / 1_000_000
    elif isinstance(usage, dict) and all(type(usage.get(k)) is int for k in ("input_tokens", "cached_input_tokens", "output_tokens")):
        input_price, cached_price, output_price = API_PRICES[model]
        cached = usage["cached_input_tokens"]
        return ((usage["input_tokens"] - cached) * input_price
                + cached * cached_price + usage["output_tokens"] * output_price) / 1_000_000
    return None


def summary(output_dir, cases, models):
    result = {}
    prompts = {}
    for model in models:
        runtimes, estimates = [], []
        attempted = matched = 0
        for qid, (case, _bundle) in cases.items():
            path = attempt_path(output_dir, qid, model)
            if not path.exists():
                continue
            row = read_attempt(path, case, model)
            attempted += 1
            observed = row["observation"]
            if row["error"] is None or model in NVIDIA_MODELS:
                estimate = estimate_usage(model, observed)
                if estimate is not None:
                    estimates.append(estimate)
            if row["error"] is not None:
                continue
            prompt = observed["prompt_hash"]
            if not request_matches(row, case, model):
                raise ValueError(f"실제 요청 또는 프롬프트 지문 불일치: {qid}/{model}")
            if prompts.setdefault(qid, prompt) != prompt:
                raise ValueError(f"모델 간 프롬프트 불일치: {qid}")
            matched += row["actual_status"] == row["expected_status"]
            runtimes.append(observed["elapsed_ms"] / 1000)
        result[model] = {"planned": len(cases), "attempted": attempted, "succeeded": len(runtimes),
                         "matched_status": matched, "p50_answer_s": median(runtimes) if runtimes else None,
                         "estimated_api_standard_usd": sum(estimates) if estimates else None,
                         "estimate_count": len(estimates)}
        if model in NVIDIA_MODELS:
            result[model].update(estimate_policy="original_provider_uncached", missing_usage_count=attempted - len(estimates),
                                 actual_nvidia_cost_usd=None)
        else:
            result[model]["actual_cli_cost_usd"] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--query", action="append")
    parser.add_argument("--model", choices=MODELS + NVIDIA_MODELS, action="append")
    parser.add_argument("--provider", choices=("codex", "nvidia"), default="codex")
    parser.add_argument("--final-search", type=Path, help="독립 문항의 검증된 동일 검색 bundle JSONL(gzip)")
    parser.add_argument("--summary", action="store_true", help="보존한 결과를 오프라인으로 재집계")
    args = parser.parse_args()
    models = NVIDIA_MODELS if args.provider == "nvidia" else (FINAL_MODELS if args.final_search else MODELS)
    if args.final_search:
        cases = final_cases(args.final_search)
    else:
        cases = {qid: ({**row, "expected_status": PILOT[qid]}, pilot_bundle(row)) for qid, row in load_cases().items()}
    selected = set(args.query or cases)
    selected_models = set(args.model or models)
    if not selected <= cases.keys() or not selected_models <= set(models):
        parser.error("고정 비교 범위 밖 질문 또는 모델")
    if args.summary:
        print(json.dumps(summary(args.output_dir, {q: cases[q] for q in cases if q in selected},
                                 [m for m in models if m in selected_models]), ensure_ascii=False, indent=2))
        return
    if args.provider == "nvidia":
        key = os.environ.get("NVIDIA_API_KEY", "").strip()
        if not key:
            parser.error("실호출에는 NVIDIA_API_KEY 환경 변수가 필요합니다.")
        os.environ.update(LLM_PROVIDER="openai-compatible", LLM_BASE_URL=NVIDIA_BASE_URL, LLM_API_KEY=key)
    else:
        os.environ["LLM_PROVIDER"] = "codex"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, (qid, (case, bundle)) in enumerate(cases.items()):
        if qid not in selected:
            continue
        offset = index % len(models)
        for model in models[offset:] + models[:offset]:
            if model not in selected_models:
                continue
            path = attempt_path(args.output_dir, qid, model)
            if path.exists():
                read_attempt(path, case, model)
                continue
            print(f"요청 {qid} {model}", flush=True)
            record = evaluate(case, bundle, model, timeout=120)
            with path.open("xb") as stream:
                stream.write(gzip.compress((canonical(record) + "\n").encode(), mtime=0))
            print(f"결과 {qid} {model} {record['actual_status'] or record['error']['code']}", flush=True)


if __name__ == "__main__":
    main()
