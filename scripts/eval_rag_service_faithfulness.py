#!/usr/bin/env python3
"""보존된 서비스 답변과 원자 주장 판정으로 faithfulness를 재집계한다."""

import argparse
from pathlib import Path
import re
from statistics import mean

from eval_ragas import canonical, faithfulness_score, index_rows, read_rows, require, sha256


BASE = Path(__file__).resolve().parents[1] / "data/eval/rag-service"
SEGMENT_START = re.compile(r"^\[(C[1-9]\d*S[1-9]\d*)\]\n- Chunk ID: ", re.MULTILINE)


def submitted_segments(prompt):
    heading, start, remaining = prompt.partition("[검색 문맥]\n")
    context, end, _ = remaining.partition("\n[제공된 인용 목록]\n")
    require(start and end and not heading.strip(), "응답 프롬프트에서 실제 검색 문맥을 찾을 수 없습니다.")
    parts = SEGMENT_START.split(context)
    require(not parts[0].strip(), "검색 문맥의 세그먼트 시작을 확인할 수 없습니다.")
    segments = {}
    for cid, block in zip(parts[1::2], parts[2::2], strict=True):
        metadata, delimiter, body = block.partition("\n- 본문:\n")
        require(cid not in segments and metadata and delimiter and body.strip(), f"잘못된 문맥 세그먼트: {cid}")
        segments[cid] = body.removesuffix("\n\n---\n\n").strip()
    require(segments, "비어 있는 제출 문맥")
    return segments


def evaluation_inputs():
    initial = index_rows(row for file in sorted((BASE / "answers_v1").glob("*.jsonl.gz")) for row in read_rows(file))
    retries = index_rows(row for file in sorted((BASE / "answers_retry_v1").glob("*.jsonl.gz")) for row in read_rows(file))
    require(len(initial) == 14 and retries.keys() == {qid for qid, row in initial.items() if row["http"] == ["429"]},
            "서비스 고정 표본 또는 429 재시도 누락")
    for qid, retry in retries.items():
        require(retry["case"] == initial[qid]["case"] and retry["store"] == initial[qid]["store"],
                f"재시도 입력 불일치: {qid}")
    rows = {}
    for qid, row in sorted((initial | retries).items()):
        observation = row["answers"][-1]
        request = observation["request"]
        system, prompt = observation["system_instruction"], observation["user_prompt"]
        require(not observation["custom_generation"] and request["model"] == "minimaxai/minimax-m3.1-flash"
                and request["payload"]["model"] == request["model"]
                and observation["runtime_meta"]["endpoint"] == "https://integrate.api.nvidia.com/v1/chat/completions",
                f"서비스 MiniMax 실호출 계보 불일치: {qid}")
        require(observation["error"] is None and observation["answer_result"]["text"] == row["answer"]
                and observation["answer_result"]["status"] == row["status"], f"최종 응답 관측 불일치: {qid}")
        require(request["payload"]["messages"] == [{"role": "system", "content": system},
                                                   {"role": "user", "content": prompt}]
                and request["sha256"] == sha256(canonical(request["payload"]))
                and observation["prompt_hash"] == sha256(system + "\n" + prompt), f"실제 요청 지문 불일치: {qid}")
        item = {"query_id": qid, "question": row["case"]["question"], "answer": row["answer"],
                "contexts": submitted_segments(prompt), "request_sha256": request["sha256"]}
        rows[qid] = {**item, "input_sha256": sha256(canonical(item))}
    return rows


def summarize(rows, reviews):
    require(rows.keys() == reviews.keys(), "서비스 답변과 주장 판정의 문항 목록 불일치")
    scores = {}
    for qid, row in rows.items():
        review = reviews[qid]
        scores[qid] = faithfulness_score(row, review)
        require(scores[qid]["denominator"], f"원자 주장 누락: {qid}")
        for claim in review["claims"]:
            evidence = claim.get("evidence")
            require(isinstance(evidence, list) and evidence and isinstance(claim.get("reason"), str)
                    and claim["reason"].strip(), f"판정 설명 또는 원문 위치 누락: {qid}")
            for citation_id, quote in evidence:
                context = row["contexts"].get(citation_id, "")
                require(isinstance(quote, str) and quote.strip() and " ".join(quote.split()) in " ".join(context.split()),
                        f"제출 문맥에 존재하지 않는 근거 구절: {qid}/{citation_id}")

    def aggregate(items):
        numerator = sum(item["numerator"] for item in items)
        denominator = sum(item["denominator"] for item in items)
        return {"answers": len(items), "macro": mean(item["value"] for item in items),
                "supported_claims": numerator, "claims": denominator, "micro": numerator / denominator}

    return {"overall": aggregate(list(scores.values())),
            "regression": aggregate([v for q, v in scores.items() if q.startswith("F")]),
            "new_questions": aggregate([v for q, v in scores.items() if q.startswith("S")]), "answers": scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdicts", type=Path, default=BASE / "faithfulness_verdicts_v1.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = canonical(summarize(evaluation_inputs(), index_rows(read_rows(args.verdicts)))) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
