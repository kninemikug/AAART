"""T23 원문 ID 점수와 보존 기록 재생 검증."""

import gzip
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.eval_ragas import context_scores, faithfulness_score


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
    assert summary["groups"]["all"]["context_precision"]["scored"] == 100
    assert summary["groups"]["all"]["faithfulness"]["missing"] == {
        "missing_answer": 31, "missing_claim_verdicts": 69,
    }
    assert (tmp_path / "report_v1.md").is_file()
