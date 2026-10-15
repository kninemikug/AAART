"""연결 평가의 캐시 출처와 완료 판정에 대한 반례 검증."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

import pytest

from artagent.graph.rewrite import build_rewrite_prompt, normalize_query
from scripts import check_t14_graph_connection as checker


ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data/eval/t14-live-20261014-final/generation_cache.json"
QUERIES_PATH = ROOT / "docs/search_eval_queries.json"
PROTOCOL_PATH = ROOT / "data/eval/t14-conn/conn_run_1791958105/protocol.json"
VERIFIED_RUN = ROOT / "data/eval/t14-conn/conn_20261014_final_review"
PRESERVATION_RUN = ROOT / "data/eval/t14-conn/conn_20261015_product_scope_v3_live"


@pytest.fixture(scope="module")
def generation_cache():
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def query_set():
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rewrite_entry(generation_cache):
    return next(
        stages["rewrite"]
        for stages in generation_cache["entries"].values()
        if stages["rewrite"]["status"] == "success"
    )


def test_playback_reuses_the_exact_verified_prompt(rewrite_entry):
    generate, stats = checker.build_playback_generator(CACHE_PATH)

    assert generate(rewrite_entry["prompt"]) == rewrite_entry["raw_output"]
    assert stats["calls"] == 1
    assert stats["hits"] == 1


def test_playback_rejects_changed_constraints_even_with_same_query(rewrite_entry):
    generate, _ = checker.build_playback_generator(CACHE_PATH)
    changed_prompt = build_rewrite_prompt(
        normalize_query(rewrite_entry["input"]),
        constraints=("Preserve highlight detail.",),
    )
    assert changed_prompt != rewrite_entry["prompt"]

    with pytest.raises(ValueError):
        generate(changed_prompt)


def test_playback_accepts_an_explicit_canonical_query_set(rewrite_entry, query_set):
    generate, _ = checker.build_playback_generator(CACHE_PATH, query_set=query_set)

    assert generate(rewrite_entry["prompt"]) == rewrite_entry["raw_output"]


def test_playback_rejects_tampered_raw_output(tmp_path, generation_cache):
    cache = deepcopy(generation_cache)
    entry = next(
        stages["rewrite"]
        for stages in cache["entries"].values()
        if stages["rewrite"]["status"] == "success"
    )
    entry["raw_output"] = "tampered search query"
    cache_path = tmp_path / "tampered_generation_cache.json"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")

    with pytest.raises(ValueError):
        checker.build_playback_generator(cache_path)


@pytest.fixture(scope="module")
def recorded_metrics():
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    return protocol["metrics_a"], protocol["metrics_b"]


def _decision(metrics_a, metrics_b, **overrides):
    gates = {
        "routes_passed": 40,
        "slice1_matches": 30,
        "execution_errors": 0,
        "provenance_verified": True,
    }
    gates.update(overrides)
    return checker.acceptance_decisions(metrics_a, metrics_b, **gates)


def test_actual_github_regression_prevents_acceptance(recorded_metrics):
    metrics_a, metrics_b = recorded_metrics
    assert metrics_b["total_hit"] >= metrics_a["total_hit"]
    assert metrics_b["rawpedia_mrr"] >= metrics_a["rawpedia_mrr"]
    assert metrics_b["github_hit"] < metrics_a["github_hit"]

    decisions = _decision(metrics_a, metrics_b)

    assert decisions["G3"] is False
    assert decisions["accepted"] is False


@pytest.mark.parametrize(
    "metric",
    [
        "total_hit", "total_mrr", "rawpedia_hit", "rawpedia_mrr",
        "github_hit", "github_mrr",
    ],
)
def test_every_source_and_metric_must_be_non_degrading(recorded_metrics, metric):
    metrics_a = deepcopy(recorded_metrics[0])
    metrics_b = deepcopy(metrics_a)
    metrics_b[metric] -= 0.01

    decisions = _decision(metrics_a, metrics_b)

    assert decisions["G3"] is False
    assert decisions["accepted"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution_errors": 1},
        {"provenance_verified": False},
        {"routes_passed": 39},
        {"slice1_matches": 29},
    ],
)
def test_metrics_alone_cannot_override_failed_connection_gates(recorded_metrics, overrides):
    metrics_a = recorded_metrics[0]

    decisions = _decision(metrics_a, deepcopy(metrics_a), **overrides)

    assert decisions["accepted"] is False


def test_all_gates_allow_equal_retrieval_metrics(recorded_metrics):
    metrics_a = recorded_metrics[0]

    decisions = _decision(metrics_a, deepcopy(metrics_a))

    assert decisions == {"G1": True, "G2": True, "G3": True, "accepted": True}


def test_report_states_adoption_only_when_every_gate_passes():
    protocol = json.loads((VERIFIED_RUN / "protocol.json").read_text())
    protocol["gates"] = {"G1": True, "G2": True, "G3": True, "accepted": True}
    assert "재작성 on 채택 확정" in checker.render_report(protocol, [], [])
    protocol["gates"]["G3"] = protocol["gates"]["accepted"] = False
    assert "재작성 on 채택 보류" in checker.render_report(protocol, [], [])


@pytest.mark.parametrize(
    ("stored_flag", "hits", "expected_count"),
    [
        (False, [{"rank": 1, "doc_id": "github:counter"}], 1),
        (True, [{"rank": 1, "doc_id": "github:unrelated"}], 0),
        (True, [{"rank": 6, "doc_id": "github:counter"}], 0),
        (
            False,
            [{
                "rank": 2,
                "doc_id": "github:parent",
                "source_segments": [{"doc_id": "github:counter"}],
            }],
            1,
        ),
    ],
)
def test_negative_counter_is_recomputed_from_ranked_source_ids(
    stored_flag, hits, expected_count,
):
    records = [{
        "source_type": "github",
        "is_negative": True,
        "gold_support_doc_ids": [],
        "counter_evidence_doc_ids": ["github:counter"],
        "counter_evidence_retrieved": stored_flag,
        "hits": hits,
    }]

    metrics = checker.recompute_metrics(records, k=5)

    assert metrics["negative_count"] == 1
    assert metrics["negative_counter_retrieved_count"] == expected_count


def _check_args(output_dir, *, cache=CACHE_PATH):
    return argparse.Namespace(
        output_dir=output_dir, queries=QUERIES_PATH, cache=cache,
        reference=ROOT / "docs/T08_2_t9_handoff_reference.json",
        store_dir=ROOT / "data/vector-store/t09", capture_missing=False,
    )


def test_existing_output_is_rejected_before_loading_inputs(tmp_path, monkeypatch):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "protocol.json"
    sentinel.write_text("existing report", encoding="utf-8")
    args = _check_args(output, cache=tmp_path / "absent-cache.json")
    args.queries = tmp_path / "absent-queries.json"
    monkeypatch.setattr(checker, "load_encoder", lambda _: pytest.fail("encoder loaded"))
    monkeypatch.setattr(checker, "open_store", lambda *_: pytest.fail("store opened"))

    with pytest.raises(ValueError, match="출력 디렉터리"):
        checker.run_checks(args)

    assert sentinel.read_text(encoding="utf-8") == "existing report"
    assert sorted(path.name for path in output.iterdir()) == ["protocol.json"]


def test_invalid_cache_cannot_create_output_or_load_search_resources(tmp_path, monkeypatch):
    cache = tmp_path / "invalid-cache.json"
    cache.write_text('{"schema_version": 0}', encoding="utf-8")
    output = tmp_path / "uncreated"
    monkeypatch.setattr(checker, "load_encoder", lambda _: pytest.fail("encoder loaded"))
    monkeypatch.setattr(checker, "open_store", lambda *_: pytest.fail("store opened"))

    with pytest.raises(ValueError):
        checker.run_checks(_check_args(output, cache=cache))

    assert not output.exists()


@pytest.fixture
def segmented_slice_record():
    direct = {
        "search_input": {"search_query": "test query"},
        "source_type": "github", "source_group_ids": ["github:thread"],
        "error": None,
        "hits": [{"chunk_id": "parent_1", "rank": 1}, {"chunk_id": "parent_2", "rank": 2}],
        "evidences": [
            {"chunk_id": "parent_1", "text": "body", "target_url": "url/body", "source_location": "body:0:4"},
            {"chunk_id": "parent_1", "text": "comment", "target_url": "url/comment", "source_location": "comment:0:7"},
            {"chunk_id": "parent_2", "text": "next", "target_url": "url/next", "source_location": "next:0:4"},
        ],
    }
    return {"direct": direct, "search_observations": [deepcopy(direct)]}


def test_slice_compares_distinct_parent_order_after_segment_expansion(segmented_slice_record):
    assert checker._slice_match(segmented_slice_record) is True


@pytest.mark.parametrize("field", ["text", "target_url", "source_location"])
def test_slice_compares_full_evidence_provenance(segmented_slice_record, field):
    segmented_slice_record["search_observations"][0]["evidences"][1][field] = "changed"

    assert checker._slice_match(segmented_slice_record) is False


def test_slice_rejects_direct_errors(segmented_slice_record):
    segmented_slice_record["direct"]["error"] = {"code": "SEARCH_UNAVAILABLE"}

    assert checker._slice_match(segmented_slice_record) is False


def test_slice_rejects_reversed_parent_order(segmented_slice_record):
    evidences = segmented_slice_record["search_observations"][0]["evidences"]
    evidences[:] = [evidences[2], evidences[0], evidences[1]]

    assert checker._slice_match(segmented_slice_record) is False


def test_generation_recorder_separates_cached_source_and_replay_calls(generation_cache, rewrite_entry):
    recorder = checker.GenerationRecorder(generation_cache)
    recorder.context = (rewrite_entry["input"], ())

    assert recorder.generate(rewrite_entry["prompt"]) == rewrite_entry["raw_output"]
    assert recorder.generate(rewrite_entry["prompt"]) == rewrite_entry["raw_output"]

    event = next(iter(recorder.events.values()))
    assert event["origin"] == "t14_cache"
    assert event["source_call_count"] == 1
    assert [attempt["mode"] for attempt in recorder.attempts] == ["source_replay", "evaluation_replay"]
    assert [attempt["generation_call_count"] for attempt in recorder.attempts] == [0, 0]
    assert len(recorder.events) == 1


def test_generation_recorder_records_exact_constraint_cache_miss(generation_cache, rewrite_entry, monkeypatch):
    monkeypatch.setattr(checker, "_runtime_generate", lambda _: pytest.fail("unrequested generation"))
    recorder = checker.GenerationRecorder(generation_cache, capture_missing=False)
    constraints = ("Preserve highlight detail.",)
    recorder.context = (rewrite_entry["input"], constraints)
    prompt = build_rewrite_prompt(normalize_query(rewrite_entry["input"]), constraints)

    with pytest.raises(RuntimeError):
        recorder.generate(prompt)

    event = next(iter(recorder.events.values()))
    assert event["origin"] == "cache_miss"
    assert event["raw_output"] is None
    assert event["source_call_count"] == 0
    assert recorder.attempts[0]["mode"] == "cache_miss"
    assert recorder.attempts[0]["generation_call_count"] == 0


def test_generation_recorder_captures_missing_prompt_once(generation_cache, monkeypatch):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "new documentation search query", generation_cache["runtime"]

    monkeypatch.setattr(checker, "_runtime_generate", generate)
    recorder = checker.GenerationRecorder(generation_cache, capture_missing=True)
    recorder.context = ("new documentation search query", ())
    prompt = build_rewrite_prompt("new documentation search query")

    assert recorder.generate(prompt) == "new documentation search query"
    assert recorder.generate(prompt) == "new documentation search query"

    assert calls == [prompt]
    event = next(iter(recorder.events.values()))
    assert event["origin"] == "live"
    assert event["source_call_count"] == 1
    assert [attempt["mode"] for attempt in recorder.attempts] == ["live", "evaluation_replay"]
    assert [attempt["generation_call_count"] for attempt in recorder.attempts] == [1, 0]


def test_generation_recorder_checkpoints_completed_responses(generation_cache, tmp_path, monkeypatch):
    monkeypatch.setattr(checker, "_runtime_generate", lambda _: ("new documentation search query", generation_cache["runtime"]))
    path = tmp_path / "generation_events.json"
    recorder = checker.GenerationRecorder(generation_cache, capture_missing=True, checkpoint_path=path)
    recorder.context = ("new documentation search query", ())
    prompt = build_rewrite_prompt("new documentation search query")
    assert recorder.generate(prompt) == "new documentation search query"
    saved = json.loads(path.read_text())
    assert len(saved) == 1
    assert next(iter(saved.values()))["raw_output"] == "new documentation search query"
    assert next(iter(saved.values()))["source_call_count"] == 1


def test_completed_connection_generation_replays_without_new_calls(generation_cache, monkeypatch):
    events = checker.load_connection_generation(PRESERVATION_RUN, QUERIES_PATH, CACHE_PATH)
    assert len(events) == 104
    source = next(iter(events.values()))
    monkeypatch.setattr(checker, "_runtime_generate", lambda _: pytest.fail("cached response regenerated"))
    recorder = checker.GenerationRecorder(generation_cache, connection_events=events)
    recorder.context = (source["input"], tuple(source["constraints"]))
    assert recorder.generate(source["prompt"]) == source["raw_output"]
    assert recorder.generate(source["prompt"]) == source["raw_output"]
    entry = next(iter(recorder.events.values()))
    assert entry["origin"] == "conn_cache"
    assert entry["source_call_count"] == 1
    assert [attempt["generation_call_count"] for attempt in recorder.attempts] == [0, 0]
    assert [attempt["mode"] for attempt in recorder.attempts] == ["source_replay", "evaluation_replay"]


@pytest.mark.parametrize("previous", ["conn_20261014_preservation_v1", "conn_20261015_product_scope_v2_live"])
def test_previous_policy_generation_cannot_be_reused_under_current_policy(previous):
    with pytest.raises(ValueError, match="정책"):
        checker.load_connection_generation(
            ROOT / "data/eval/t14-conn" / previous, QUERIES_PATH, CACHE_PATH,
        )


@pytest.mark.parametrize("change", ["response", "policy", "generation_code"])
def test_connection_generation_source_rejects_tampering(tmp_path, change):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("protocol.json", "generation_events.json"):
        shutil.copyfile(PRESERVATION_RUN / name, source / name)
    if change == "response":
        path = source / "generation_events.json"
        data = json.loads(path.read_text())
        next(iter(data.values()))["raw_output"] = "tampered query"
    else:
        path = source / "protocol.json"
        data = json.loads(path.read_text())
        if change == "policy":
            data["preservation_policy"] = "legacy"
        else:
            data["code_sha256"]["src/artagent/graph/rewrite.py"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        checker.load_connection_generation(source, QUERIES_PATH, CACHE_PATH)


@pytest.fixture(scope="module")
def frozen_bundle(tmp_path_factory):
    """실측 기록을 복사하고 코드 계약은 해당 실행 시점의 지문으로 대조한다."""
    source = Path(os.environ.get("T14_CONN_VERIFIED_RUN", str(VERIFIED_RUN)))
    destination = tmp_path_factory.mktemp("t14_conn_bundle") / source.name
    shutil.copytree(source, destination)
    protocol = json.loads((destination / "protocol.json").read_text(encoding="utf-8"))
    return destination, protocol["code_sha256"]


@pytest.fixture
def bundle_copy(tmp_path, frozen_bundle, monkeypatch):
    source, frozen_code_hashes = frozen_bundle
    destination = tmp_path / source.name
    shutil.copytree(source, destination, copy_function=os.link)
    actual_sha256_file = checker.sha256_file

    def sha256_file(path):
        relative = Path(path).relative_to(ROOT).as_posix() if Path(path).is_relative_to(ROOT) else None
        return frozen_code_hashes[relative] if relative in frozen_code_hashes else actual_sha256_file(path)

    monkeypatch.setattr(checker, "sha256_file", sha256_file)
    return destination


def _replace_json(path, payload):
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replacement.replace(path)


def _replace_rows(path, rows):
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    replacement.replace(path)


def _reseal(bundle, name):
    """파일 봉인만 갱신해도 의미 검증이 변조를 검출해야 한다."""
    protocol_path = bundle / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["artifact_sha256"][name] = checker.sha256_file(bundle / name)
    _replace_json(protocol_path, protocol)


@pytest.mark.parametrize("recorded_path", [
    "/different/checkout/AAART/docs/T08_2_t9_handoff_reference.json",
    "docs/T08_2_t9_handoff_reference.json",
])
def test_reference_is_verified_in_the_current_checkout(bundle_copy, recorded_path, monkeypatch):
    path = bundle_copy / "protocol.json"
    protocol = json.loads(path.read_text())
    protocol["retrieval_contract"]["reference_path"] = recorded_path
    _replace_json(path, protocol)
    monkeypatch.chdir(bundle_copy.parent)
    assert checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH) == {
        "G1": True, "G2": True, "G3": False, "accepted": False,
    }


def test_relocated_reference_still_requires_its_recorded_hash(bundle_copy):
    path = bundle_copy / "protocol.json"
    protocol = json.loads(path.read_text())
    protocol["retrieval_contract"]["reference_path"] = "docs/T08_2_t9_handoff_reference.json"
    protocol["retrieval_contract"]["reference_sha256"] = "0" * 64
    _replace_json(path, protocol)
    with pytest.raises(ValueError, match="검색 계약"):
        checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH)


def test_recorded_reference_cannot_escape_the_repository(bundle_copy):
    path = bundle_copy / "protocol.json"
    protocol = json.loads(path.read_text())
    protocol["retrieval_contract"]["reference_path"] = "../outside/reference.json"
    _replace_json(path, protocol)
    with pytest.raises(ValueError, match="기준 파일.*외부"):
        checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH)


def test_verified_bundle_remains_unaccepted_for_github_regression(bundle_copy):
    assert checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH) == {
        "G1": True, "G2": True, "G3": False, "accepted": False,
    }


def test_validate_cli_returns_failure_for_github_regression(bundle_copy, monkeypatch):
    monkeypatch.setattr(checker.sys, "argv", ["checker", "--validate", "--output-dir", str(bundle_copy)])
    assert checker.main() == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "gold", "segment_range", "content", "evidence_url", "attempt_mode", "attempt_calls", "attempt_time", "retrieval_source", "decision_source", "decision_query", "rank", "distance_text", "source_group"])
def test_resealed_ab_records_reject_semantic_tampering(bundle_copy, mutation):
    path = bundle_copy / "ab_records.jsonl"
    records = checker._read_rows(path)
    record = records[0]
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records[-1] = deepcopy(records[0])
    elif mutation == "gold":
        record["gold_support_doc_ids"] = ["rawpedia:unrelated"]
    elif mutation == "segment_range":
        record["search_observations"][0]["hits"][0]["source_segments"][0]["content_char_end"] += 1
    elif mutation == "content":
        record["search_observations"][0]["hits"][0]["content"] += " changed"
    elif mutation == "evidence_url":
        record["search_observations"][0]["evidences"][0]["target_url"] += "#changed"
    elif mutation in ("attempt_mode", "attempt_calls", "attempt_time"):
        record = next(row for row in records if row["condition"] == "B" and row["search_observations"])
        attempt = record["search_observations"][0]["generation_attempts"][0]
        attempt[{"attempt_mode": "mode", "attempt_calls": "generation_call_count", "attempt_time": "elapsed_ms"}[mutation]] = {
            "attempt_mode": "live", "attempt_calls": 1, "attempt_time": -1,
        }[mutation]
    elif mutation == "retrieval_source":
        record["retrieval"]["source_filter"] = "github"
    elif mutation == "decision_source":
        record["decision"]["primary_path"] = "TROUBLESHOOT"
        record["decision"]["plan"][0]["path"] = "TROUBLESHOOT"
        record["actual_primary"] = "TROUBLESHOOT"
        record["actual_plan"] = ["TROUBLESHOOT"]
    elif mutation == "decision_query":
        record["decision"]["plan"][0]["query"] = "changed query"
    elif mutation == "rank":
        record["search_observations"][0]["hits"][0]["rank"] = 5
    elif mutation == "distance_text":
        record["search_observations"][0]["hits"][0]["distance_text"] = "0.000000"
    elif mutation == "source_group":
        record["search_observations"][0]["hits"][0]["source_group_id"] = "rawpedia:forged"
    _replace_rows(path, records)
    _reseal(bundle_copy, path.name)

    with pytest.raises(ValueError):
        checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH)


@pytest.mark.parametrize("mutation", ["metric", "snapshot_drift", "code_hash", "routes_count", "slice_count", "unique_events", "reused_source_call_count", "source_elapsed_ms", "new_call_count", "replay_count"])
def test_protocol_totals_and_contracts_are_independently_verified(bundle_copy, mutation):
    path = bundle_copy / "protocol.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "metric":
        protocol["metrics_b"]["github_mrr"] += 0.01
    elif mutation == "snapshot_drift":
        protocol["retrieval_contract"]["snapshot_after_sha256"] = "0" * 64
    elif mutation == "code_hash":
        protocol["code_sha256"]["scripts/check_t14_graph_connection.py"] = "0" * 64
    elif mutation == "routes_count":
        protocol["routes_pass_count"] -= 1
    elif mutation == "slice_count":
        protocol["slice1_match_count"] -= 1
    else:
        protocol["generation_totals"][mutation] += 1
    _replace_json(path, protocol)

    with pytest.raises(ValueError):
        checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH)


def test_resealed_route_request_cannot_replace_fixed_case_input(bundle_copy):
    path = bundle_copy / "routes.jsonl"
    records = checker._read_rows(path)
    records[0]["request"]["text"] = "changed benchmark input"
    _replace_rows(path, records)
    _reseal(bundle_copy, path.name)

    with pytest.raises(ValueError):
        checker.validate_artifacts(bundle_copy, QUERIES_PATH, CACHE_PATH)
