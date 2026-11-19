"""T23 원문 ID 점수와 보존 기록 재생 검증."""

import gzip
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.eval_ragas import context_scores, faithfulness_score
from scripts.judge_t23_faithfulness import check_entailment, response_rows


def test_id_metrics_deduplicate_and_ignore_order():
    scores = context_scores(["d2", "d2", "d3"], ["d1", "d1", "d2", "d4"])
    assert scores["context_precision"]["value"] == 1 / 3
    assert scores["context_recall"]["value"] == 1 / 2
    assert context_scores(["d3", "d2"], ["d4", "d2", "d1"]) == scores


def test_id_metrics_distinguish_empty_denominators_from_zero_overlap():
    scores = context_scores(["allowed"], [])
    assert scores["context_precision"]["value"] is None
    assert scores["context_recall"]["value"] == 0
    scores = context_scores([], ["retrieved"])
    assert scores["context_precision"]["value"] == 0
    assert scores["context_recall"]["value"] is None


def test_faithfulness_counts_entailment_for_the_exact_input():
    row = {"query_id": "Q001", "input_sha256": "digest", "answer": "생성된 답변"}
    review = {"input_sha256": "digest", "evaluator": "test-judge/v1", "claims": [
        {"statement": "뒷받침된 주장", "supported": True},
        {"statement": "뒷받침되지 않은 주장", "supported": False},
    ]}
    assert faithfulness_score(row, review)["value"] == 0.5
    assert faithfulness_score(row, None)["reason"] == "missing_claim_verdicts"
    assert faithfulness_score({**row, "answer": None}, None)["reason"] == "missing_answer"
    assert faithfulness_score(row, {**review, "claims": []})["reason"] == "no_factual_claims"
    with pytest.raises(ValueError, match="Q001"):
        faithfulness_score(row, {**review, "input_sha256": "other"})
    with pytest.raises(ValueError, match="Q001"):
        faithfulness_score(row, {**review, "claims": [{"statement": "주장", "supported": 1}]})


def test_judge_requires_support_from_the_same_submitted_context():
    item = {"query_id": "Q001", "claims": ["claim"], "contexts": [
        {"id": "C1S1", "text": "The original\n  evidence."},
    ]}
    verdict = {"claim": 1, "supported": True, "reason": "Matches the statement.",
               "evidence": [{"id": "C1S1", "quote": "The original evidence."}]}
    assert check_entailment(item, [verdict])[0]["statement"] == "claim"
    squeezed = {**verdict, "evidence": [{"id": "C1S1", "quote": "The originalevidence."}]}
    assert check_entailment(item, [squeezed])[0]["evidence"][0]["quote"] == "The original\n  evidence."
    with pytest.raises(ValueError, match="Q001"):
        check_entailment(item, [{**verdict, "evidence": [{"id": "C2S1", "quote": "The original evidence."}]}])
    with pytest.raises(ValueError, match="Q001"):
        check_entailment(item, [{**verdict, "evidence": [{"id": "C1S1", "quote": "fabricated"}]}])
    with pytest.raises(ValueError, match="Q001"):
        check_entailment(item, [verdict, verdict])


def test_judge_recovers_unambiguously_misnested_verdicts():
    first = {"claim": 1, "supported": False, "evidence": []}
    second = {**first, "claim": 2, "reason": "Evidence differs"}
    raw = json.dumps({"rows": [{"query_id": "Q001", "verdicts": [first], "reason": "Missing evidence"},
                              second]})
    assert response_rows(raw, "verdicts")["Q001"]["verdicts"] == [
        {**first, "reason": "Missing evidence"}, second,
    ]


def test_cli_replays_all_fixed_inputs_with_selected_track_only(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/eval_ragas.py"
    subprocess.run([sys.executable, str(script), "--output-dir", str(tmp_path)],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    output = tmp_path / "ragas_v1"
    with gzip.open(output / "inputs.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = {r["query_id"]: r for r in map(json.loads, stream)}
    scores = [json.loads(line) for line in (output / "scores.jsonl").read_text().splitlines()]
    summary = json.loads((output / "summary.json").read_text())

    assert list(rows) == [f"Q{i:03}" for i in range(1, 101)]
    assert sum(r["answer"] is not None for r in rows.values()) == 69
    assert all(r["retrieved_contexts"] for r in rows.values())
    assert all(r["input_sha256"] == s["input_sha256"] for r, s in zip(rows.values(), scores, strict=True))
    assert rows["Q001"]["answer_run"]["track"] == "T15"
    assert rows["Q096"]["allowed_source_doc_ids"] == ["issue-comment:4711197631"]
    assert "issue-comment:4711197631" in rows["Q096"]["retrieved_source_doc_ids"]
    assert summary["groups"]["all"]["context_precision"]["value"] == pytest.approx(0.27666666666666667)
    assert summary["groups"]["all"]["context_recall"]["value"] == 0.97
    assert summary["groups"]["all"]["faithfulness"]["missing"] == {
        "missing_answer": 31, "no_factual_claims": 1,
    }
    assert next(score for score in scores if score["query_id"] == "Q024")["faithfulness"]["reason"] == "no_factual_claims"
    common = summary["groups"]["common"]
    assert common["questions"] == 68 == sum(all(
        s[m]["value"] is not None for m in ("context_precision", "context_recall", "faithfulness")
    ) for s in scores)
    assert all(common[m]["scored"] == common["questions"]
               for m in ("context_precision", "context_recall", "faithfulness"))
    assert (tmp_path / "report_v1.md").is_file()
