"""Task 14 원검색 기록 검증 및 채택 판정 회귀 테스트."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import run_t14_ab_eval as evaluator


METRIC_KEYS = (
    "total_hit", "total_mrr", "rawpedia_hit", "rawpedia_mrr",
    "github_hit", "github_mrr", "macro_hit", "macro_mrr",
)
ADOPTION_KEYS = METRIC_KEYS[:6]


@pytest.fixture
def query_set() -> dict[str, Any]:
    return {
        "dataset_id": "t14-three-queries",
        "queries": [
            {
                "query_id": "Q001", "query": "How do Auto Levels work?",
                "source_type": "rawpedia", "difficulty": "factoid",
                "expected_behavior": "grounded_answer",
                "gold_support_doc_ids": ["rawpedia:Exposure"],
                "evidence": [{"doc_id": "rawpedia:Exposure", "role": "support"}],
            },
            {
                "query_id": "Q084", "query": "What does issue #524 describe?",
                "source_type": "github", "difficulty": "factoid",
                "expected_behavior": "grounded_answer",
                "gold_support_doc_ids": ["github:issue:524"],
                "evidence": [{"doc_id": "github:issue:524", "role": "support"}],
            },
            {
                "query_id": "Q096", "query": "Does ART process video?",
                "source_type": "github", "difficulty": "negative",
                "expected_behavior": "unsupported_or_refute",
                "gold_support_doc_ids": [],
                "evidence": [{"doc_id": "github:issue:700", "role": "counter"}],
            },
        ],
    }


def search_hits(doc_id: str, rank: int, *, via_segment: bool = False) -> list[dict[str, Any]]:
    hits = [
        {
            "rank": number, "chunk_id": f"chunk-{number}",
            "doc_id": f"other:document:{number}", "source_segments": [],
            "source_type": "github" if doc_id.startswith("github:") else "rawpedia",
        }
        for number in range(1, rank + 1)
    ]
    if via_segment:
        hits[-1]["source_segments"] = [{"doc_id": doc_id}]
    else:
        hits[-1]["doc_id"] = doc_id
    return hits


@pytest.fixture
def records(query_set: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in "ABCD":
        for query in query_set["queries"]:
            negative = not query["gold_support_doc_ids"]
            rank = 3 if query["source_type"] == "rawpedia" else 2
            doc_id = query["evidence"][0]["doc_id"]
            rows.append({
                "run_id": "t14-test", "condition": condition,
                "query_id": query["query_id"], "query_original": query["query"],
                "source_type": query["source_type"],
                "gold_support_doc_ids": list(query["gold_support_doc_ids"]),
                "is_negative": negative, "is_representative": True,
                "generation_status": "off" if condition == "A" else "success",
                "generation_error": None, "search_query": query["query"],
                "rewritten_query": query["query"] if condition in "BD" else None,
                "hypothetical_document": "A short reference text." if condition in "CD" else None,
                "hits": search_hits(doc_id, rank, via_segment=not negative and rank == 3),
                "first_correct_rank": None if negative else rank,
                "hit_at_5": None if negative else 1.0,
                "rr_at_5": None if negative else 1.0 / rank,
                "counter_evidence_retrieved": negative,
                "generation_call_count": {"A": 0, "B": 1, "C": 1, "D": 2}[condition],
                "elapsed_ms": 4.0,
            })
    return rows


def test_recompute_metrics_uses_raw_hits_and_segment_ids(records: list[dict[str, Any]]) -> None:
    subset = copy.deepcopy(records[:3])
    for row in subset:
        row["first_correct_rank"] = 5
        row["hit_at_5"] = 0.0
        row["rr_at_5"] = 0.0

    metrics = evaluator.recompute_metrics(subset, k=5)

    assert metrics["total_hit"] == 1.0
    assert metrics["total_mrr"] == pytest.approx(5.0 / 12.0)
    assert metrics["rawpedia_hit"] == 1.0
    assert metrics["rawpedia_mrr"] == pytest.approx(1.0 / 3.0)
    assert metrics["github_hit"] == 1.0
    assert metrics["github_mrr"] == 0.5
    assert metrics["macro_hit"] == 1.0
    assert metrics["macro_mrr"] == pytest.approx(5.0 / 12.0)
    assert metrics["total_count"] == 3
    assert metrics["positive_count"] == 2
    assert metrics["negative_count"] == 1
    assert metrics["rawpedia_hit_count"] == metrics["github_hit_count"] == 1
    assert metrics["rawpedia_total"] == metrics["github_total"] == 1


def test_recompute_metrics_obeys_k_cutoff(records: list[dict[str, Any]]) -> None:
    metrics = evaluator.recompute_metrics(records[:3], k=2)

    assert metrics["total_hit"] == 0.5
    assert metrics["total_mrr"] == 0.25
    assert metrics["rawpedia_hit"] == metrics["rawpedia_mrr"] == 0.0
    assert metrics["github_mrr"] == 0.5


def test_validate_records_accepts_jsonl_round_trip(
    records: list[dict[str, Any]], query_set: dict[str, Any], tmp_path: Path,
) -> None:
    records_path = tmp_path / "records.jsonl"
    records_path.write_text(
        "\n".join(json.dumps(row) for row in reversed(records)) + "\n", encoding="utf-8",
    )
    loaded = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]

    evaluator.validate_records(loaded, query_set, k=5)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_query", "unknown_condition"])
def test_validate_records_rejects_incomplete_or_duplicate_grid(
    records: list[dict[str, Any]], query_set: dict[str, Any], change: str,
) -> None:
    if change == "missing":
        records.pop()
    elif change == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif change == "unknown_query":
        records[0]["query_id"] = "Q999"
    else:
        records[0]["condition"] = "E"

    with pytest.raises(ValueError):
        evaluator.validate_records(records, query_set, k=5)


@pytest.mark.parametrize("field,value", [
    ("query_original", "A different question"),
    ("source_type", "github"),
    ("gold_support_doc_ids", ["forged:correct-answer"]),
    ("is_negative", True),
    ("first_correct_rank", 2),
    ("hit_at_5", 0.0),
    ("rr_at_5", 0.9),
])
def test_validate_records_rejects_canonical_or_derived_field_changes(
    records: list[dict[str, Any]], query_set: dict[str, Any], field: str, value: Any,
) -> None:
    records[0][field] = value

    with pytest.raises(ValueError):
        evaluator.validate_records(records, query_set, k=5)


@pytest.mark.parametrize("change", ["empty_hits", "segment_removed", "rank_zero", "rank_over_k", "duplicate_rank"])
def test_validate_records_rejects_search_evidence_changes(
    records: list[dict[str, Any]], query_set: dict[str, Any], change: str,
) -> None:
    row = records[0]
    if change == "empty_hits":
        row["hits"] = []
    elif change == "segment_removed":
        row["hits"][-1]["source_segments"] = []
    elif change == "rank_zero":
        row["hits"][-1]["rank"] = 0
    elif change == "rank_over_k":
        row["hits"][-1]["rank"] = 6
    else:
        row["hits"][-1]["rank"] = 2

    with pytest.raises(ValueError):
        evaluator.validate_records(records, query_set, k=5)


def test_validate_records_rejects_negative_question_scored_as_positive(
    records: list[dict[str, Any]], query_set: dict[str, Any],
) -> None:
    records[2].update(first_correct_rank=1, hit_at_5=1.0, rr_at_5=1.0)

    with pytest.raises(ValueError):
        evaluator.validate_records(records, query_set, k=5)


def test_validate_records_rejects_failed_generation_with_search_hits(
    records: list[dict[str, Any]], query_set: dict[str, Any],
) -> None:
    records[3]["generation_status"] = "error"

    with pytest.raises(ValueError):
        evaluator.validate_records(records, query_set, k=5)


def test_failed_positive_generation_stays_in_metric_denominator(
    records: list[dict[str, Any]], query_set: dict[str, Any],
) -> None:
    records[3].update(
        generation_status="error", generation_error="empty output", hits=[],
        first_correct_rank=None, hit_at_5=0.0, rr_at_5=0.0,
    )

    evaluator.validate_records(records, query_set, k=5)
    metrics = evaluator.recompute_metrics(records[3:6], k=5)

    assert metrics["positive_count"] == 2
    assert metrics["total_hit"] == 0.5
    assert metrics["total_mrr"] == 0.25
    assert metrics["rawpedia_hit"] == metrics["rawpedia_mrr"] == 0.0


def metric_values(value: float) -> dict[str, Any]:
    return {
        **dict.fromkeys(METRIC_KEYS, value),
        "total_count": 3, "positive_count": 2, "negative_count": 1,
        "rawpedia_hit_count": 1, "rawpedia_total": 1,
        "github_hit_count": 1, "github_total": 1,
        "negative_counter_retrieved_count": 1,
    }


def test_adoption_decisions_accept_equal_metrics() -> None:
    metrics = {condition: metric_values(0.5) for condition in "ABCD"}

    assert evaluator.adoption_decisions(metrics) == {
        "rewrite_pass": True, "hyde_c_pass": True, "hyde_d_pass": True,
    }


@pytest.mark.parametrize("condition,key", [(condition, key) for condition in "BCD" for key in ADOPTION_KEYS])
def test_adoption_decisions_reject_each_required_metric_regression(condition: str, key: str) -> None:
    metrics = {name: metric_values(0.5) for name in "ABCD"}
    metrics[condition] = metric_values(0.7)
    metrics[condition][key] = 0.49

    decisions = evaluator.adoption_decisions(metrics)

    decision_key = {"B": "rewrite_pass", "C": "hyde_c_pass", "D": "hyde_d_pass"}[condition]
    assert decisions[decision_key] is False


@pytest.mark.parametrize("stronger_baseline", ["A", "B"])
def test_combined_hyde_must_match_both_baselines(stronger_baseline: str) -> None:
    metrics = {name: metric_values(0.5) for name in "ABCD"}
    metrics[stronger_baseline] = metric_values(0.8)
    metrics["D"] = metric_values(0.7)

    assert evaluator.adoption_decisions(metrics)["hyde_d_pass"] is False


def test_hyde_alone_compares_against_original_query_baseline() -> None:
    metrics = {name: metric_values(0.5) for name in "ABCD"}
    metrics["B"] = metric_values(0.9)
    metrics["C"] = metric_values(0.6)

    assert evaluator.adoption_decisions(metrics)["hyde_c_pass"] is True


def report_manifest(*, passed: bool, provenance: str) -> dict[str, Any]:
    metrics = {name: metric_values(1.0 if name == "A" or passed else 0.5) for name in "ABCD"}
    return {
        "run_id": "t14-test", "timestamp": "2026-10-13T00:00:00+00:00",
        "dataset": {"dataset_id": "t14-three-queries", "query_count": 3, "query_set_sha256": "abc"},
        "retrieval_contract": {
            "k0": 5, "model_id": "existing-model", "model_revision": "12345678",
            "collection_name": "test-collection", "active_chunks": 3,
        },
        "generation_contract": {
            "status": provenance, "rewrite_prompt_version": "rewrite_v1", "hyde_prompt_version": "hyde_v1",
        },
        "metrics_summary": {"all_100": metrics, "rep_15": copy.deepcopy(metrics)},
        "verification_result": {"rewrite_pass": passed, "hyde_c_pass": passed, "hyde_d_pass": passed},
    }


def test_report_renders_failed_decisions_instead_of_fixed_success(records: list[dict[str, Any]]) -> None:
    report = evaluator.render_report(report_manifest(passed=False, provenance="verified"), records)

    assert report.count("실패") >= 3
    assert "판정: 통과" not in report
    assert "채택 권장" not in report


def test_report_renders_verified_passing_decisions(records: list[dict[str, Any]]) -> None:
    report = evaluator.render_report(report_manifest(passed=True, provenance="verified"), records)

    assert "통과" in report
    assert "실패" not in report


def test_report_defers_adoption_when_generation_provenance_unverified(records: list[dict[str, Any]]) -> None:
    report = evaluator.render_report(report_manifest(passed=True, provenance="unverified"), records)

    assert "보류" in report
    assert "채택 권장" not in report


def test_report_lists_rewrite_regressions_by_question_id(records: list[dict[str, Any]]) -> None:
    for row in records[:2]:
        row["hits"] = search_hits(row["gold_support_doc_ids"][0], 1)
        row.update(first_correct_rank=1, hit_at_5=1.0, rr_at_5=1.0)

    report = evaluator.render_report(report_manifest(passed=False, provenance="verified"), records)

    assert "Q001" in report
    assert "Q084" in report


def test_report_does_not_invent_generation_latency(records: list[dict[str, Any]]) -> None:
    report = evaluator.render_report(report_manifest(passed=True, provenance="verified"), records)

    assert "200~500" not in report
    assert "200–500" not in report


@pytest.mark.parametrize("create_directory", [False, True])
def test_replay_rejects_missing_or_empty_store_before_opening(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]],
    cache_query_set: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    create_directory: bool,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(generated_cache[0]), encoding="utf-8")
    query_path = tmp_path / "queries.json"
    query_path.write_text(json.dumps(cache_query_set), encoding="utf-8")
    store_path = tmp_path / "missing-store"
    if create_directory:
        store_path.mkdir()

    def unexpected_open(*args: Any, **kwargs: Any) -> None:
        pytest.fail("읽기 검증 전에 저장소를 열거나 만들었습니다.")

    monkeypatch.setattr("artagent.retrieval.store.open_store", unexpected_open)
    with pytest.raises(FileNotFoundError):
        evaluator.run_eval(cache_path, tmp_path / "run", query_path, store_path)
    assert not (store_path / "chroma.sqlite3").exists()
    assert not (tmp_path / "run").exists()


@pytest.fixture
def cache_query_set() -> dict[str, Any]:
    return {
        "dataset_id": "t14-generation-two-queries",
        "queries": [
            {
                "query_id": "Q101", "query": "How do exposure controls work?",
                "source_type": "rawpedia",
                "gold_support_doc_ids": ["private-gold-exposure-marker"],
                "evidence": [{"text_span": "private-evidence-exposure-marker"}],
            },
            {
                "query_id": "Q102", "query": "How do tone curves work?",
                "source_type": "rawpedia",
                "gold_support_doc_ids": ["private-gold-tone-marker"],
                "evidence": [{"text_span": "private-evidence-tone-marker"}],
            },
        ],
    }


def canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.fixture
def generated_cache(cache_query_set: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def generate(prompt: str) -> tuple[str, dict[str, Any]]:
        topic = "exposure" if "exposure" in prompt.lower() else "tone curve"
        if prompt.rstrip().endswith("Rewritten Query:"):
            output = f"Rewritten Query: ART {topic} tool adjustment workflow"
        else:
            output = (
                f"Hypothetical Document: The {topic} tool can adjust the image. "
                "The controls support an editing workflow with a preview."
            )
        metadata = {"model_id": "existing-runtime", "generation_config": {"temperature": 0}}
        calls.append({"prompt": prompt, "raw_output": output, "runtime_metadata": copy.deepcopy(metadata)})
        return output, metadata

    return evaluator.build_generation_cache(cache_query_set, generate), calls


def test_generation_cache_records_real_calls_and_independent_hyde_inputs(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any],
) -> None:
    from artagent.graph.rewrite import (
        HYDE_PROMPT_VERSION, REWRITE_PROMPT_VERSION, build_hyde_prompt, build_rewrite_prompt,
    )

    cache, calls = generated_cache
    assert len(calls) == 6
    assert cache["schema_version"] == 2
    assert cache["dataset_id"] == cache_query_set["dataset_id"]
    assert cache["dataset_fingerprint"] == canonical_fingerprint(cache_query_set)
    assert cache["rewrite_prompt_version"] == REWRITE_PROMPT_VERSION
    assert cache["hyde_prompt_version"] == HYDE_PROMPT_VERSION
    assert set(cache["entries"]) == {"Q101", "Q102"}
    calls_by_prompt = {call["prompt"]: call for call in calls}
    assert len(calls_by_prompt) == 6

    for query in cache_query_set["queries"]:
        stages = cache["entries"][query["query_id"]]
        assert set(stages) == {"rewrite", "hyde_original", "hyde_rewritten"}
        assert stages["rewrite"]["input"] == query["query"]
        assert stages["hyde_original"]["input"] == query["query"]
        assert stages["hyde_rewritten"]["input"] == stages["rewrite"]["output"]
        assert stages["hyde_original"]["prompt"] != stages["hyde_rewritten"]["prompt"]
        assert stages["hyde_original"]["output"] == stages["hyde_rewritten"]["output"]
        for stage, entry in stages.items():
            prompt_builder = build_rewrite_prompt if stage == "rewrite" else build_hyde_prompt
            assert entry["prompt"] == prompt_builder(entry["input"])
            assert entry["prompt_sha256"] == hashlib.sha256(entry["prompt"].encode("utf-8")).hexdigest()
            call = calls_by_prompt[entry["prompt"]]
            assert entry["raw_output"] == call["raw_output"]
            assert entry["runtime_metadata"] == call["runtime_metadata"]
            prefix = "Rewritten Query:" if stage == "rewrite" else "Hypothetical Document:"
            assert entry["output"] == entry["raw_output"].removeprefix(prefix).strip()
            assert entry["status"] == "success"
            assert entry["error_category"] is None
            assert isinstance(entry["elapsed_ms"], (int, float))
            assert entry["elapsed_ms"] >= 0
            assert "private-gold-" not in entry["prompt"]
            assert "private-evidence-" not in entry["prompt"]

    evaluator.validate_generation_cache(cache, cache_query_set)


@pytest.mark.parametrize("field", ["input", "prompt", "prompt_sha256", "raw_output", "output", "status"])
def test_generation_cache_rejects_tampered_stage_fields(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any], field: str,
) -> None:
    cache, _ = generated_cache
    entry = cache["entries"]["Q101"]["hyde_rewritten"]
    entry[field] = "error" if field == "status" else "changed stage value"

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(cache, cache_query_set)


def test_generation_cache_rejects_original_input_substituted_for_rewritten_input(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any],
) -> None:
    cache, _ = generated_cache
    stages = cache["entries"]["Q101"]
    stages["hyde_rewritten"] = copy.deepcopy(stages["hyde_original"])

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(cache, cache_query_set)


def test_generation_cache_rejects_changed_prompt_even_with_matching_hash(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any],
) -> None:
    cache, _ = generated_cache
    entry = cache["entries"]["Q101"]["hyde_original"]
    entry["prompt"] += "\nUse unrelated input."
    entry["prompt_sha256"] = hashlib.sha256(entry["prompt"].encode("utf-8")).hexdigest()

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(cache, cache_query_set)


@pytest.mark.parametrize("change", [
    "metadata_missing", "model_missing", "model_empty", "model_changed",
    "config_missing", "config_not_mapping", "config_changed",
])
def test_generation_cache_rejects_missing_or_inconsistent_runtime_metadata(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any], change: str,
) -> None:
    cache, _ = generated_cache
    entry = cache["entries"]["Q101"]["hyde_rewritten"]
    if change == "metadata_missing":
        entry.pop("runtime_metadata")
    elif change == "model_missing":
        entry["runtime_metadata"].pop("model_id")
    elif change == "model_empty":
        entry["runtime_metadata"]["model_id"] = ""
    elif change == "model_changed":
        entry["runtime_metadata"]["model_id"] = "different-runtime"
    elif change == "config_missing":
        entry["runtime_metadata"].pop("generation_config")
    elif change == "config_not_mapping":
        entry["runtime_metadata"]["generation_config"] = "temperature=0"
    else:
        entry["runtime_metadata"]["generation_config"]["temperature"] = 1

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(cache, cache_query_set)


@pytest.mark.parametrize("change", ["question", "evidence", "dataset_id", "missing_entry"])
def test_generation_cache_rejects_changed_dataset_or_missing_entry(
    generated_cache: tuple[dict[str, Any], list[dict[str, Any]]], cache_query_set: dict[str, Any], change: str,
) -> None:
    cache, _ = generated_cache
    if change == "question":
        cache_query_set["queries"][0]["query"] = "How does a different tool work?"
    elif change == "evidence":
        cache_query_set["queries"][0]["evidence"][0]["text_span"] = "changed evidence"
    elif change == "dataset_id":
        cache_query_set["dataset_id"] = "different-dataset"
    else:
        cache["entries"].pop("Q102")

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(cache, cache_query_set)


def test_generation_cache_rejects_legacy_shared_hyde_map(cache_query_set: dict[str, Any]) -> None:
    old_cache = {"rewrite_map": {"Q101": "exposure tool"}, "hyde_map": {"Q101": "A shared passage."}}

    with pytest.raises(ValueError):
        evaluator.validate_generation_cache(old_cache, cache_query_set)


@pytest.mark.parametrize("stage,raw_output,error_category", [
    ("rewrite", "", "EMPTY_OUTPUT"),
    ("hyde_original", "short", "LENGTH_VIOLATION"),
])
def test_generation_cache_preserves_rewrite_and_hyde_validation_failures(
    cache_query_set: dict[str, Any], stage: str, raw_output: str, error_category: str,
) -> None:
    def generate(prompt: str) -> tuple[str, dict[str, Any]]:
        rewriting = prompt.rstrip().endswith("Rewritten Query:")
        if (stage == "rewrite" and rewriting) or (stage == "hyde_original" and not rewriting):
            output = raw_output
        elif rewriting:
            output = "ART exposure and tone curve tool adjustment workflow"
        else:
            output = "The exposure and tone curve tool can adjust an image using a preview."
        return output, {"model_id": "existing-runtime", "generation_config": {"temperature": 0}}

    cache = evaluator.build_generation_cache(cache_query_set, generate)
    entry = cache["entries"]["Q101"][stage]

    assert entry["raw_output"] == raw_output
    assert entry["output"] == ""
    assert entry["status"] == "error"
    assert entry["error_category"] == error_category
    evaluator.validate_generation_cache(cache, cache_query_set)


@pytest.fixture
def saved_artifacts(
    records: list[dict[str, Any]], query_set: dict[str, Any], tmp_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    query_path = tmp_path / "queries.json"
    query_path.write_text(json.dumps(query_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    all_metrics = {
        condition: evaluator.recompute_metrics([r for r in records if r["condition"] == condition])
        for condition in "ABCD"
    }
    manifest = report_manifest(passed=True, provenance="verified")
    manifest["dataset"].update(
        query_set_sha256=hashlib.sha256(query_path.read_bytes()).hexdigest(),
        positive_count=2, negative_count=1, representative_15_count=3,
        representative_qids=[query["query_id"] for query in query_set["queries"]],
    )
    manifest["metrics_summary"] = {"all_100": all_metrics, "rep_15": copy.deepcopy(all_metrics)}
    manifest["verification_result"] = evaluator.adoption_decisions(all_metrics)
    return manifest, records, query_path


def test_validate_artifacts_accepts_real_query_bytes_and_recomputed_metrics(
    saved_artifacts: tuple[dict[str, Any], list[dict[str, Any]], Path],
) -> None:
    manifest, records, query_path = saved_artifacts

    evaluator.validate_artifacts(manifest, records, query_path)


@pytest.mark.parametrize("change", ["saved_hash", "query_file_bytes", "all_metrics", "representative_metrics", "decision", "raw_record"])
def test_validate_artifacts_rejects_hash_metrics_decision_or_record_changes(
    saved_artifacts: tuple[dict[str, Any], list[dict[str, Any]], Path], change: str,
) -> None:
    manifest, records, query_path = saved_artifacts
    if change == "saved_hash":
        manifest["dataset"]["query_set_sha256"] = "0" * 64
    elif change == "query_file_bytes":
        query_path.write_bytes(query_path.read_bytes() + b"\n")
    elif change == "all_metrics":
        manifest["metrics_summary"]["all_100"]["B"]["total_mrr"] = 0.9
    elif change == "representative_metrics":
        manifest["metrics_summary"]["rep_15"]["B"]["total_mrr"] = 0.9
    elif change == "decision":
        manifest["verification_result"]["rewrite_pass"] = False
    else:
        records[0]["query_original"] = "A forged question"

    with pytest.raises(ValueError):
        evaluator.validate_artifacts(manifest, records, query_path)


@pytest.fixture
def provenance_bundle(tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], Path, Path]:
    from artagent.retrieval.provenance import compute_chunk_id
    from artagent.retrieval.types import load_spec

    source_path = evaluator.ROOT / "data/rawpedia/Exposure.md"
    source_bytes = source_path.read_bytes()
    content = source_bytes.decode("utf-8")[:200]
    content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    segment = {
        "doc_id": "rawpedia:Exposure", "ref_id": None,
        "source_path": "data/rawpedia/Exposure.md",
        "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "char_start": 0, "char_end": len(content),
        "byte_start": 0, "byte_end": len(content.encode("utf-8")),
        "content_char_start": 0, "content_char_end": len(content),
        "segment_sha256": content_sha, "json_pointer": None,
    }
    metadata = {"source_segments": [segment], "content_sha256": content_sha,
                "range_basis": "source_file", "rule_fingerprint": "review-fixture"}
    chunk_id = compute_chunk_id(
        "t08c:v1", metadata["rule_fingerprint"], "rawpedia", "rawpedia:Exposure",
        metadata["source_segments"], content_sha,
    )
    hit = {
        "rank": 1, "chunk_id": chunk_id, "source_type": "rawpedia",
        "doc_id": "rawpedia:Exposure", "source_group_id": "Exposure", "section_title": "Exposure",
        "content": content, "content_sha256": content_sha, "source_segments": [segment],
        "original_metadata": metadata, "distance": 0.1, "distance_text": "0.100000",
    }
    query = {
        "query_id": "Q001", "query": "How does the exposure tool work?", "source_type": "rawpedia",
        "gold_support_doc_ids": ["rawpedia:Exposure"], "evidence": [],
    }
    query_set = {"dataset_id": "t14-provenance-one-query", "queries": [query]}

    def generate(prompt: str) -> tuple[str, dict[str, Any]]:
        return (
            "ART exposure tool adjustment workflow with an image preview",
            {"model_id": "existing-runtime", "generation_config": {"temperature": 0}},
        )

    cache = evaluator.build_generation_cache(query_set, generate)
    query_path = tmp_path / "queries.json"
    cache_path = tmp_path / "cache.json"
    query_path.write_text(json.dumps(query_set), encoding="utf-8")
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    records = []
    for condition in "ABCD":
        stages = cache["entries"][query["query_id"]]
        prepared = evaluator._prepare_from_cache(query["query"], condition, stages)
        stage_keys = {"A": [], "B": ["rewrite"], "C": ["hyde_original"],
                      "D": ["rewrite", "hyde_rewritten"]}[condition]
        records.append({
            "run_id": "t14-provenance-test", "condition": condition, "query_id": query["query_id"],
            "query_original": query["query"], "source_type": "rawpedia",
            "gold_support_doc_ids": ["rawpedia:Exposure"], "is_negative": False,
            "is_representative": True, "generation_status": prepared.status, "search_status": "success",
            "search_query": prepared.search_query,
            "rewritten_query": prepared.rewrite_result.rewritten_query if prepared.rewrite_result else None,
            "hypothetical_document": prepared.hyde_result.hypothetical_document if prepared.hyde_result else None,
            "generation_call_count": 0, "generation_elapsed_ms": 0.0,
            "source_generation_call_count": sum(stages[key]["generation_call_count"] for key in stage_keys),
            "source_generation_elapsed_ms": sum(stages[key]["elapsed_ms"] for key in stage_keys),
            "hits": [copy.deepcopy(hit)], "first_correct_rank": 1,
            "hit_at_5": 1.0, "rr_at_5": 1.0, "counter_evidence_retrieved": False, "k0": 5,
        })
    spec = load_spec(evaluator.REFERENCE_PATH)
    metrics = {condition: evaluator.recompute_metrics([r for r in records if r["condition"] == condition])
               for condition in "ABCD"}
    manifest = {
        "schema_version": 2, "run_id": "t14-provenance-test", "execution_mode": "replay",
        "dataset": {
            "dataset_id": query_set["dataset_id"], "query_count": 1,
            "query_set_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
            "positive_count": 1, "negative_count": 0,
            "representative_qids": ["Q001"], "representative_15_count": 1,
        },
        "generation_contract": {
            "status": "verified", "cache_sha256": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
            "runtime": cache["runtime"], "rewrite_prompt_version": cache["rewrite_prompt_version"],
            "hyde_prompt_version": cache["hyde_prompt_version"],
        },
        "retrieval_contract": {
            "k0": 5, "reference_path": str(evaluator.REFERENCE_PATH.relative_to(evaluator.ROOT)),
            "reference_sha256": evaluator.compute_file_sha256(evaluator.REFERENCE_PATH),
            "model_id": spec.model_id, "model_revision": spec.model_revision,
            "collection_name": spec.collection_name, "snapshot_sha256": "fixture-snapshot",
            "snapshot_after_sha256": "fixture-snapshot", "active_chunks": 1,
        },
        "metrics_summary": {"all_100": metrics, "rep_15": copy.deepcopy(metrics)},
        "verification_result": evaluator.adoption_decisions(metrics),
    }
    return manifest, records, query_path, cache_path


def test_bundle_accepts_real_source_provenance_and_matching_model_contract(
    provenance_bundle: tuple[dict[str, Any], list[dict[str, Any]], Path, Path],
) -> None:
    evaluator.validate_bundle(*provenance_bundle)


@pytest.mark.parametrize("contract,field,value", [
    ("retrieval_contract", "model_id", "different-embedding-model"),
    ("retrieval_contract", "model_revision", "different-revision"),
    ("retrieval_contract", "collection_name", "different-collection"),
    ("generation_contract", "hyde_prompt_version", "different-prompt-version"),
])
def test_bundle_rejects_model_or_prompt_contract_disagreement(
    provenance_bundle: tuple[dict[str, Any], list[dict[str, Any]], Path, Path],
    contract: str, field: str, value: str,
) -> None:
    manifest, records, query_path, cache_path = provenance_bundle
    manifest[contract][field] = value

    with pytest.raises(ValueError):
        evaluator.validate_bundle(manifest, records, query_path, cache_path)
