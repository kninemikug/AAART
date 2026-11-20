"""T23의 두 생성 모델이 동일한 문맥과 독립 평가기에서 비교되는지 검증."""

import gzip
import json

import pytest

from scripts.eval_ragas import ROOT, index_rows, read_rows
from scripts.judge_t23_faithfulness import response_rows
from scripts.t23_minimax_pairs import (
    attach_minimax_answer, check_paired_extraction, check_passage_entailment,
    paired_context, prepare_pair, segment_passages, summarize_pairs,
)


def test_minimax_answer_requires_the_exact_sol_prompt():
    source = ROOT / "data/eval/ragas_v2/inputs.jsonl.gz"
    sol = index_rows(read_rows(source))["Q001"]
    pilot = ROOT / "data/eval/stack-selection/nvidia_pilot_v1/Q001-minimaxai--minimax-m3.1-flash.json.gz"
    with gzip.open(pilot, "rt", encoding="utf-8") as stream:
        observed = json.load(stream)
    candidate = attach_minimax_answer(sol, observed)
    assert candidate["retrieved_contexts"] == sol["retrieved_contexts"]
    assert candidate["input_sha256"] != sol["input_sha256"]
    with pytest.raises(ValueError, match="Q001"):
        attach_minimax_answer(sol, {**observed, "bundle_sha256": "wrong"})


def test_paired_judging_blinds_order_and_shares_exact_claims():
    sol = {"query_id": "Q001", "question": "prompt", "answer": "Sol text", "retrieved_contexts": []}
    minimax = {**sol, "answer": "MiniMax text"}
    ordered = prepare_pair(sol, minimax)
    assert ordered[0]["answer"] == "MiniMax text"
    assert set(ordered[0]) == {"query_id", "question", "answer"}
    claims = {ordered[0]["query_id"]: ["shared", "first"], ordered[1]["query_id"]: ["shared", "second"]}
    assert paired_context(sol, claims, ordered)["claims"] == ["shared", "first", "second"]


def test_paired_averages_use_identical_answered_questions():
    def score(value):
        return {"value": value, "numerator": int(value == 1), "denominator": int(value is not None)}

    rows = [
        {"sol": score(0), "minimax": score(1)},
        {"sol": score(1), "minimax": score(None)},
    ]
    summary = summarize_pairs(rows)
    assert summary["sol"]["value"] == 0.5
    assert summary["sol"]["common_value"] == 0
    assert summary["minimax"]["common_value"] == 1
    assert summary["common_count"] == 1


def test_passage_verdicts_resolve_verbatim_evidence_and_reject_unknown_ids():
    raw = json.dumps({"support": {"Q001.1": "C1S1:1", "Q001.2": ""}})
    found = response_rows(raw, "passage_verdicts")["Q001"]["passage_verdicts"]
    text = "evidence with newlines\n" * 100
    item = segment_passages({"query_id": "Q001", "claims": ["a", "b"],
                             "contexts": [{"id": "C1S1", "text": text}]})
    assert "".join(chunk for _, chunk in item["contexts"][0]["text"]) == text
    claims = check_passage_entailment(item, found)
    assert claims[0]["supported"] is True and claims[0]["evidence"][0]["quote"] in text
    assert claims[1]["supported"] is False
    plain = response_rows('{"Q001.1":"C1S1:1-2","Q001.2":""}', "passage_verdicts")
    assert len(check_passage_entailment(item, plain["Q001"]["passage_verdicts"])[0]["evidence"]) == 2
    short = segment_passages({**item, "contexts": [{"id": "C1S1", "text": "short evidence"}]})
    bare_id = response_rows('{"Q001.1":"C1S1","Q001.2":""}', "passage_verdicts")
    assert check_passage_entailment(short, bare_id["Q001"]["passage_verdicts"])[0]["evidence"][0]["passage_id"] == "C1S1:1"
    found[0]["passage_ids"] = ["C2S1:1"]
    with pytest.raises(ValueError, match="Q001"):
        check_passage_entailment(item, found)


def test_claim_parser_keeps_every_statement_from_repeated_claim_fields():
    emitted = '{"rows":[{"query_id":"Q001A","claims":[{"claim":"first","claim":"second"}]}]}'
    claims = response_rows(emitted, "claims")["Q001A"]["claims"]
    assert check_paired_extraction({}, claims) == ["first", "second"]
    assert check_paired_extraction({}, [
        {"claim": "first", "qualifier": "[C1S1]"}, {"claim": "second", "qualifier": "only if enabled"},
    ]) == ["first", "second (only if enabled)"]
