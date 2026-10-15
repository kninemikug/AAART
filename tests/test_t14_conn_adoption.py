"""원형 보존 보완 후의 실제 검색 채택 기록 검증."""

import json
from pathlib import Path
import re

import pytest

from scripts import check_t14_graph_connection as checker


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/eval/t14-conn/conn_20261015_pr"


@pytest.fixture(scope="module")
def records():
    return checker._read_rows(RUN / "ab_records.jsonl")


def test_adopted_bundle_passes_every_gate():
    assert checker.validate_artifacts(
        RUN, ROOT / "docs/search_eval_queries.json",
        ROOT / "data/eval/t14-live-20261014-final/generation_cache.json",
    ) == {"G1": True, "G2": True, "G3": True, "accepted": True}


def test_adopted_run_replays_real_generation_without_counting_new_calls():
    protocol = json.loads((RUN / "protocol.json").read_text())
    assert protocol["generation_totals"]["unique_events"] == 104
    assert protocol["generation_totals"]["reused_source_call_count"] == 104
    assert protocol["generation_totals"]["new_call_count"] == 0
    assert protocol["generation_totals"]["replay_count"] == 149


def test_fixed_identifiers_no_longer_block_search(records):
    selected = {r["query_id"]: r for r in records if r["condition"] == "B"}
    assert len(selected) == 100
    for row in selected.values():
        assert row["search_observations"][0]["search_input"]["status"] == "success"
    for qid in ("Q060", "Q070", "Q094"):
        observation = selected[qid]["search_observations"][0]
        assert observation["error"] is None
        assert observation["search_call_count"] == 1
    assert "RawTherapee" in selected["Q070"]["search_observations"][0]["search_input"]["search_query"]
    assert selected["Q094"]["first_gold_rank"] == 1


def test_reference_product_scope_is_preserved_for_manual_review_cases(records):
    for row in records:
        if row["query_id"] in ("Q010", "Q077"):
            evidences = row["search_observations"][0]["evidences"]
            assert evidences
            assert all(ev["source_type"] == "rawpedia" and ev["product_scope"] == "RawTherapee" for ev in evidences)


def test_unscoped_questions_do_not_gain_product_names(records):
    selected = {r["query_id"]: r for r in records if r["condition"] == "B"}
    for qid in ("Q010", "Q077"):
        prepared = selected[qid]["search_observations"][0]["search_input"]
        assert prepared["status"] == "success"
        assert not re.search(r"(?<![A-Za-z0-9_])(?:ART|RawTherapee)(?![A-Za-z0-9_])",
                             prepared["search_query"], re.IGNORECASE)
