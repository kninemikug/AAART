"""Task 14-CONN: A-14 최초 검색 연결 및 종합 검증 실행기.

세 검증 집합 수행:
1. 경로 20개 (Router Benchmark 20건 x off/on)
2. Slice 1 15개 검색 계층 대조 (직접 검색 vs 그래프 검색 100% 일치)
3. 전체 100개 질의 Graph A/B 평가 (200행, Hit@5 및 MRR@5 비저하 검증)

산출물 위치: data/eval/t14-conn/<run_id>/
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import subprocess
import time
from typing import Any, Callable, Optional

# 프로젝트 루트 경로 설정
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from artagent.graph import (
    AnswerResult,
    Path as AgentPath,
    RequestInput,
    RuntimeCapabilities,
    AssetRef, OutputSpec, RequestContext, analyze_signals, route_request,
    create_router_graph,
    create_search_nodes,
    resolve_github_targets,
    search_hits_to_evidences,
)
from artagent.answer import verify_store_ready
from artagent.graph.rewrite import PRESERVATION_POLICY_VERSION, build_rewrite_prompt, normalize_query, prepare_search_input, rewrite_query
from artagent.graph.search import _extract_query_and_constraints
from artagent.retrieval.embedding import load_encoder
from artagent.retrieval.provenance import Chunk, canonical_json_bytes, deserialize_chunk, sha256_str, validate_provenance
from artagent.retrieval.store import open_store
from artagent.retrieval.types import SearchHit, load_spec
from scripts.run_t14_ab_eval import _fingerprint, _runtime_generate, _runtime_identity, _store_fingerprint, validate_generation_cache

from tests.test_router import BENCHMARK_CASES

SLICE1_QIDS = [
    "Q001", "Q004", "Q014", "Q021", "Q033",
    "Q044", "Q054", "Q063", "Q072", "Q080",
    "Q084", "Q086", "Q092", "Q093", "Q096",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_reference_path(value: str) -> Path:
    """과거 절대 경로도 현재 저장소의 동일 해시 기준 파일로 검증한다."""
    path = Path(value)
    if path.is_absolute():
        path = Path("docs") / path.name
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("인계 기준 파일의 저장소 외부 경로는 허용하지 않습니다.")
    return path


def _doc_ids_from_hit(hit: dict[str, Any]) -> set[str]:
    ids = {hit.get("doc_id", "")}
    for seg in hit.get("source_segments", []):
        if seg.get("doc_id"):
            ids.add(seg["doc_id"])
    return {i for i in ids if i}


def _first_rank(record: dict[str, Any], k: int = 5) -> Optional[int]:
    gold = set(record["gold_support_doc_ids"])
    for hit in record["hits"]:
        rank = hit["rank"]
        if 1 <= rank <= k and _doc_ids_from_hit(hit) & gold:
            return rank
    return None


def recompute_metrics(records: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    positives = [r for r in records if not r.get("is_negative")]
    negatives = [r for r in records if r.get("is_negative")]
    res: dict[str, Any] = {
        "total_count": len(records),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "negative_counter_retrieved_count": sum(
            any(1 <= h["rank"] <= k and _doc_ids_from_hit(h) & set(r.get("counter_evidence_doc_ids", []))
                for h in r["hits"]) for r in negatives
        ),
    }

    for name, subset in (
        ("total", positives),
        ("rawpedia", [r for r in positives if r["source_type"] == "rawpedia"]),
        ("github", [r for r in positives if r["source_type"] == "github"]),
    ):
        ranks = [_first_rank(r, k) for r in subset]
        count = len(subset)
        hit_cnt = sum(rk is not None for rk in ranks)
        res[f"{name}_total"] = count
        res[f"{name}_hit_count"] = hit_cnt
        res[f"{name}_hit"] = hit_cnt / count if count else 0.0
        res[f"{name}_mrr"] = (
            sum(1.0 / rk for rk in ranks if rk is not None) / count if count else 0.0
        )

    return res


def acceptance_decisions(metrics_a: dict[str, Any], metrics_b: dict[str, Any], *,
                         routes_passed: int, slice1_matches: int, execution_errors: int,
                         provenance_verified: bool) -> dict[str, bool]:
    non_degrading = all(metrics_b[f"{source}_{metric}"] >= metrics_a[f"{source}_{metric}"]
                        for source in ("total", "rawpedia", "github") for metric in ("hit", "mrr"))
    gates = {"G1": provenance_verified and execution_errors == 0,
             "G2": routes_passed == 40 and slice1_matches == 30,
             "G3": provenance_verified and execution_errors == 0 and non_degrading}
    return {**gates, "accepted": all(gates.values())}


def build_playback_generator(cache_path: Path, query_set: Optional[dict[str, Any]] = None
                             ) -> tuple[Callable[[str], str], dict[str, int]]:
    cache_data = json.loads(cache_path.read_bytes())
    if query_set is None:
        query_set = json.loads((ROOT / "docs/search_eval_queries.json").read_bytes())
    validate_generation_cache(cache_data, query_set)
    entries = cache_data.get("entries", {})
    prompt_to_output: dict[str, str] = {}

    for qid, entry in entries.items():
        rw = entry.get("rewrite", {})
        prompt = rw.get("prompt", "")
        raw_out = rw.get("raw_output", "")
        if prompt and raw_out is not None:
            prompt_to_output[prompt] = raw_out

    call_stats = {"calls": 0, "hits": 0}

    def generate(prompt: str) -> str:
        call_stats["calls"] += 1
        if prompt in prompt_to_output:
            call_stats["hits"] += 1
            return prompt_to_output[prompt]
        raise ValueError("현재 입력·제약·프롬프트와 일치하는 검증된 생성 출처가 없습니다.")

    return generate, call_stats



CODE_PATHS = ["scripts/check_t14_graph_connection.py", "scripts/run_t14_ab_eval.py",
              *[f"src/artagent/graph/{name}.py" for name in ("search", "rewrite", "router", "graph", "nodes", "state")],
              *[f"src/artagent/retrieval/{name}.py" for name in ("store", "embedding", "provenance")], "tests/test_router.py"]
ARTIFACT_NAMES = {"routes.jsonl", "slice1_search.jsonl", "ab_records.jsonl", "generation_events.json", "store_snapshot.json"}
SLICE1_REFERENCE = ROOT / "docs/T11_execution_records.jsonl"
SLICE1_REFERENCE_SHA = "5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7"
QUERIES_SHA = "91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8"


def _json_copy(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _replay_event(event: dict[str, Any], prompt: str) -> str:
    if event["prompt"] != prompt:
        raise ValueError("입력·제약·프롬프트 불일치")
    if event["raw_output"] is None:
        raise RuntimeError(event["generation_error"])
    return event["raw_output"]


def load_connection_generation(run_dir: Path, query_path: Path, cache_path: Path) -> dict[str, Any]:
    """그래프 수정 후에도 실제 생성 출처는 동일 프롬프트에 한해 독립 재사용한다."""
    protocol = json.loads((run_dir / "protocol.json").read_bytes())
    path = run_dir / "generation_events.json"
    cache = json.loads(cache_path.read_bytes())
    validate_generation_cache(cache, json.loads(query_path.read_bytes()))
    if (protocol.get("schema_version") != 2 or protocol.get("preservation_policy") != PRESERVATION_POLICY_VERSION
            or protocol["queries_sha256"] != sha256_file(query_path)
            or protocol["cache_sha256"] != sha256_file(cache_path)
            or protocol["artifact_sha256"]["generation_events.json"] != sha256_file(path)):
        raise ValueError("생성 출처의 정책·정본·파일 지문 불일치")
    for name in ("src/artagent/graph/rewrite.py", "scripts/run_t14_ab_eval.py"):
        if protocol["code_sha256"][name] != sha256_file(ROOT / name):
            raise ValueError("원형 보존 또는 실제 생성 헬퍼가 출처 실행과 다릅니다.")
    events = json.loads(path.read_bytes())
    if not events:
        raise ValueError("생성 출처가 비어 있습니다.")
    for identifier, event in events.items():
        prompt = build_rewrite_prompt(normalize_query(event["input"]), tuple(event["constraints"]))
        if (event["origin"] != "live" or type(event["source_call_count"]) is not int or event["source_call_count"] != 1
                or event["raw_output"] is None or event["prompt"] != prompt
                or identifier != sha256_str(prompt) or event["prompt_sha256"] != identifier
                or event["raw_output_sha256"] != sha256_str(event["raw_output"])
                or not math.isfinite(event["source_elapsed_ms"]) or event["source_elapsed_ms"] < 0
                or _runtime_identity(event["runtime_metadata"]) != _runtime_identity(cache["runtime"])):
            raise ValueError("실제 생성의 입력·응답·호출·모델 출처 불일치")
        result = rewrite_query(event["input"], constraints=tuple(event["constraints"]),
                               generate=lambda p, e=event: _replay_event(e, p))
        if _json_copy(asdict(result)) != event["result"]:
            raise ValueError("실제 생성의 정제 출력·보존 검사 판정 불일치")
    return events


class GenerationRecorder:
    """고유 생성 출처와 이번 실행의 실제 생성/재생 호출을 따로 보존한다."""

    def __init__(self, cache: dict[str, Any], capture_missing: bool = False, *, checkpoint_path: Optional[Path] = None,
                 connection_events: Optional[dict[str, Any]] = None):
        self.lookup = {v["rewrite"]["prompt"]: (qid, v["rewrite"]) for qid, v in cache["entries"].items()}
        self.runtime = cache["runtime"]
        self.capture_missing = capture_missing
        self.checkpoint_path = checkpoint_path
        self.connection_events = connection_events or {}
        self.context: tuple[str, tuple[str, ...]] = ("", ())
        self.events: dict[str, Any] = {}
        self.attempts: list[dict[str, Any]] = []

    def generate(self, prompt: str) -> str:
        started = time.perf_counter()
        identifier = sha256_str(prompt)
        mode, actual_calls = "evaluation_replay", 0
        if identifier not in self.events:
            query, constraints = self.context
            event = {"input": query, "constraints": list(constraints), "prompt": prompt,
                     "prompt_sha256": identifier, "raw_output": None, "runtime_metadata": None,
                     "source_call_count": 0, "source_elapsed_ms": 0.0, "generation_error": None}
            if prompt in self.lookup:
                qid, source = self.lookup[prompt]
                event.update(origin="t14_cache", source_query_id=qid, raw_output=source["raw_output"],
                             runtime_metadata=source["runtime_metadata"], source_call_count=source["generation_call_count"],
                             source_elapsed_ms=source["elapsed_ms"], generation_error=source.get("generation_error"))
                mode = "source_replay"
            elif identifier in self.connection_events:
                source = self.connection_events[identifier]
                if source["prompt"] != prompt:
                    raise ValueError("생성 출처 프롬프트 불일치")
                event.update(origin="conn_cache", source_event_id=identifier, raw_output=source["raw_output"],
                             runtime_metadata=copy.deepcopy(source["runtime_metadata"]), source_call_count=source["source_call_count"],
                             source_elapsed_ms=source["source_elapsed_ms"], generation_error=source.get("generation_error"))
                mode = "source_replay"
            elif self.capture_missing:
                event["origin"] = mode = "live"
                event["source_call_count"] = actual_calls = 1
                try:
                    raw, metadata = _runtime_generate(prompt)
                    if _runtime_identity(metadata) != _runtime_identity(self.runtime):
                        raise ValueError("새 생성의 모델·설정이 고정 출처와 다릅니다.")
                    event.update(raw_output=raw, runtime_metadata=metadata)
                except Exception as exc:
                    event["generation_error"] = f"{type(exc).__name__}: {exc}"
                event["source_elapsed_ms"] = (time.perf_counter() - started) * 1000
            else:
                event["origin"] = mode = "cache_miss"
                event["generation_error"] = "현재 입력·제약·프롬프트의 생성 출처 없음"
            event["raw_output_sha256"] = sha256_str(event["raw_output"]) if event["raw_output"] is not None else None
            result = rewrite_query(query, constraints=constraints, generate=lambda p: _replay_event(event, p))
            event["result"] = asdict(result)
            self.events[identifier] = event
            if self.checkpoint_path is not None:
                temporary = self.checkpoint_path.with_suffix(".tmp")
                _write_json(temporary, self.events)
                temporary.replace(self.checkpoint_path)
            if mode == "live" and (len(self.events) % 10 == 0 or result.status == "error"):
                print(f"고유 생성 {len(self.events)}건: {result.status} ({result.error_category or '정상'})", flush=True)
        self.attempts.append({"event_id": identifier, "mode": mode, "generation_call_count": actual_calls,
                              "elapsed_ms": (time.perf_counter() - started) * 1000})
        return _replay_event(self.events[identifier], prompt)


def _route_observation(state: dict[str, Any]) -> dict[str, Any]:
    decision = state.get("decision")
    trace = state.get("trace", [])
    route_idx = trace.index("ROUTE") if "ROUTE" in trace else -1
    first = next((n for n in trace[route_idx + 1:]
                  if n in ("SEARCH_RAWPEDIA", "SEARCH_GITHUB", "CHECK_EXEC", "CLARIFY")), None)
    return {"actual_primary": str(decision.primary_path) if decision else "None",
            "actual_plan": [str(p.path) for p in decision.plan] if decision else [],
            "actual_first_branch": first, "actual_clarify": state.get("clarification") is not None}


def _route_pass(record: dict[str, Any]) -> bool:
    return all(record[f"actual_{key}"] == record[f"expected_{key}"]
               for key in ("primary", "plan", "first_branch", "clarify"))


def _graph_runner(store: Any, session: Any, recorder: GenerationRecorder, condition: str,
                  snapshot_ref: str) -> Callable[[RequestInput], dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    nodes = create_search_nodes(store, session, generate=recorder.generate, snapshot_ref=snapshot_ref,
                                rewrite_enabled=condition == "B", hyde_enabled=False, observe=observations.append)

    def wrap(node: Callable) -> Callable:
        def invoke(state: dict[str, Any]) -> dict[str, Any]:
            recorder.context = _extract_query_and_constraints(state, preserve_literals=True)
            attempt_start = len(recorder.attempts)
            watched = ("request", "decision", "cursor", "research_count")
            before = copy.deepcopy({key: state.get(key) for key in watched})
            result = node(state)
            observations[-1].update(generation_attempts=copy.deepcopy(recorder.attempts[attempt_start:]),
                                    state_preserved=before == {key: state.get(key) for key in watched})
            return result
        return invoke

    # 검색 경계 검증용 대역이다. T17 답변·인용 완료의 증거가 아니다.
    def answer_double(state: dict[str, Any]) -> dict[str, Any]:
        return {"answer": AnswerResult("SUPPORTED", "검색 연결 검증 대역"),
                "trace": [*state.get("trace", []), "ANSWER"]}

    graph = create_router_graph(node_overrides={
        **{name: wrap(node) for name, node in nodes.items()},
        "INTAKE": lambda state: {"capabilities": RuntimeCapabilities(True, True, True)}, "ANSWER": answer_double,
    })

    def run(request: RequestInput) -> dict[str, Any]:
        observations.clear()
        started = time.perf_counter()
        state = graph.invoke({"request": request})
        response, bundle = state.get("response"), state.get("retrieval")
        return _json_copy({"condition": condition, "rewrite_enabled": condition == "B", "hyde_enabled": False,
                           "request": asdict(request), **_route_observation(state), "trace": state.get("trace", []),
                           "decision": asdict(state["decision"]) if state.get("decision") else None,
                           "search_observations": copy.deepcopy(observations), "retrieval": asdict(bundle) if bundle else None,
                           "service_error": asdict(state["error"]) if state.get("error") else None,
                           "service_status": str(response.status) if response else None,
                           "answer_test_double": True, "capabilities_test_double": True,
                           "elapsed_ms": (time.perf_counter() - started) * 1000})
    return run


def _slice_match(record: dict[str, Any]) -> bool:
    observations, direct = record["search_observations"], record["direct"]
    if len(observations) != 1 or direct["error"] or observations[0]["error"]:
        return False
    graph = observations[0]
    return (all(graph[key] == direct[key] for key in ("search_input", "source_type", "source_group_ids", "hits", "evidences"))
            and [h["chunk_id"] for h in direct["hits"]]
            == list(dict.fromkeys(ev["chunk_id"] for ev in graph["evidences"])))


def _execution_errors(records: list[dict[str, Any]], events: dict[str, Any]) -> int:
    return (sum(o["error"] is not None and o["error"]["code"] == "SEARCH_UNAVAILABLE"
                for r in records for o in r["search_observations"])
            + sum(e["raw_output"] is None for e in events.values()))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check_grid(rows: list[dict[str, Any]], ids: set[str], key: str) -> None:
    expected = {(qid, cond) for qid in ids for cond in "AB"}
    actual = [(r[key], r["condition"]) for r in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("검증 행 누락·중복·조건 불일치")


def _request_from_record(value: dict[str, Any]) -> RequestInput:
    fields = {**value, "assets": [AssetRef(**asset) for asset in value["assets"]]}
    if value["context"]:
        ctx = dict(value["context"])
        if ctx["output"]:
            ctx["output"] = OutputSpec(**ctx["output"])
        fields["context"] = RequestContext(**ctx)
    return RequestInput(**fields)


def _generation_totals(records: list[dict[str, Any]], events: dict[str, Any]) -> dict[str, Any]:
    attempts = [a for r in records for o in r["search_observations"] + ([r["direct"]] if "direct" in r else [])
                for a in o["generation_attempts"]]
    for identifier, event in events.items():
        linked = [a for a in attempts if a["event_id"] == identifier]
        expected_first = {"t14_cache": "source_replay", "conn_cache": "source_replay", "live": "live", "cache_miss": "cache_miss"}[event["origin"]]
        if (len([a for a in linked if a["mode"] == expected_first]) != 1
                or any(a["mode"] not in (expected_first, "evaluation_replay") for a in linked)):
            raise ValueError("실제 생성·원출처 재생·이번 실행 재생 방식 불일치")
        for attempt in linked:
            if (type(attempt["generation_call_count"]) is not int
                    or attempt["generation_call_count"] != int(attempt["mode"] == "live")
                    or not math.isfinite(attempt["elapsed_ms"]) or attempt["elapsed_ms"] < 0):
                raise ValueError("실측 생성 호출 수·시간 불일치")
    return {"unique_events": len(events),
            "reused_source_call_count": sum(e["source_call_count"] for e in events.values() if e["origin"] in ("t14_cache", "conn_cache")),
            "source_elapsed_ms": sum(e["source_elapsed_ms"] for e in events.values()),
            "new_call_count": sum(a["generation_call_count"] for a in attempts),
            "replay_count": sum(a["generation_call_count"] == 0 for a in attempts)}


def _validate_artifacts(out_dir: Path, query_path: Path, cache_path: Path) -> dict[str, bool]:
    """생성 출처·동결 스냅샷·원문 위치·기록·지표·게이트를 독립 재검증한다."""
    protocol = json.loads((out_dir / "protocol.json").read_bytes())
    if protocol.get("schema_version") != 2:
        raise ValueError("독립 검증에 필요한 증거가 없는 이전 스키마입니다.")
    policy = protocol.get("preservation_policy", "legacy")
    if policy not in ("legacy", PRESERVATION_POLICY_VERSION):
        raise ValueError("알 수 없는 보존 정책 버전")
    queries, cache = json.loads(query_path.read_bytes()), json.loads(cache_path.read_bytes())
    validate_generation_cache(cache, queries)
    if (protocol["queries_sha256"] != sha256_file(query_path) or protocol["queries_sha256"] != QUERIES_SHA
            or protocol["cache_sha256"] != sha256_file(cache_path)
            or protocol["slice1_reference_sha256"] != sha256_file(SLICE1_REFERENCE)
            or protocol["slice1_reference_sha256"] != SLICE1_REFERENCE_SHA):
        raise ValueError("정본·생성 출처 해시 불일치")
    if set(protocol["artifact_sha256"]) != ARTIFACT_NAMES or set(protocol["code_sha256"]) != set(CODE_PATHS):
        raise ValueError("필수 증거·실행 코드 지문 누락")
    for name, digest in protocol["artifact_sha256"].items():
        if sha256_file(out_dir / name) != digest:
            raise ValueError(f"증거 파일 변경: {name}")
    for name, digest in protocol["code_sha256"].items():
        if sha256_file(ROOT / name) != digest:
            raise ValueError(f"실행 코드 변경: {name}")
    contract = protocol["retrieval_contract"]
    spec = load_spec(_recorded_reference_path(contract["reference_path"]))
    if (spec.reference_sha256 != contract["reference_sha256"]
            or any(getattr(spec, key) != contract[key] for key in ("model_id", "model_revision", "collection_name"))
            or contract["k"] != 5 or contract["k0"] != 10 or protocol["hyde_enabled"] is not False):
        raise ValueError("검색 계약·모델·k·HyDE 변경")
    snapshot = json.loads((out_dir / "store_snapshot.json").read_bytes())
    if (_fingerprint(snapshot) != contract["snapshot_sha256"]
            or contract["snapshot_sha256"] != contract["snapshot_after_sha256"]):
        raise ValueError("검색 스냅샷 변경")
    frozen = {row[0]: deserialize_chunk(row[0], row[1], row[2]) for row in snapshot}
    events = json.loads((out_dir / "generation_events.json").read_bytes())
    connection_events: dict[str, Any] = {}
    if any(event["origin"] == "conn_cache" for event in events.values()):
        source_contract = protocol["generation_source_contract"]
        source_dir = Path(source_contract["run_path"])
        source_dir = source_dir if source_dir.is_absolute() else ROOT / source_dir
        if (source_contract["protocol_sha256"] != sha256_file(source_dir / "protocol.json")
                or source_contract["events_sha256"] != sha256_file(source_dir / "generation_events.json")):
            raise ValueError("인수한 실제 생성 출처 파일 변경")
        connection_events = load_connection_generation(source_dir, query_path, cache_path)
    for identifier, event in events.items():
        expected_prompt = build_rewrite_prompt(normalize_query(event["input"]), tuple(event["constraints"]))
        if (event["prompt"] != expected_prompt or identifier != sha256_str(expected_prompt)
                or event["prompt_sha256"] != identifier
                or event["raw_output_sha256"] != (sha256_str(event["raw_output"]) if event["raw_output"] is not None else None)
                or event["source_call_count"] not in (0, 1)
                or not math.isfinite(event["source_elapsed_ms"]) or event["source_elapsed_ms"] < 0):
            raise ValueError("생성 입력·제약·프롬프트·원응답 지문 오류")
        if event["origin"] == "t14_cache":
            source = cache["entries"][event["source_query_id"]]["rewrite"]
            for key, source_key in (("input", "input"), ("prompt", "prompt"), ("raw_output", "raw_output"),
                                    ("runtime_metadata", "runtime_metadata"), ("source_call_count", "generation_call_count"),
                                    ("source_elapsed_ms", "elapsed_ms")):
                if event[key] != source[source_key]:
                    raise ValueError("기존 생성 출처와 재생 이벤트 불일치")
        elif event["origin"] == "conn_cache":
            source = connection_events[event["source_event_id"]]
            if any(event[key] != source[key] for key in ("input", "constraints", "prompt", "raw_output", "runtime_metadata",
                                                         "source_call_count", "source_elapsed_ms", "generation_error", "result")):
                raise ValueError("인수한 실제 생성과 재생 기록 불일치")
        elif event["origin"] not in ("live", "cache_miss"):
            raise ValueError("생성 방식 불일치")
        if event["raw_output"] is not None and _runtime_identity(event["runtime_metadata"]) != _runtime_identity(cache["runtime"]):
            raise ValueError("생성 모델·설정 불일치")
        result = rewrite_query(event["input"], constraints=tuple(event["constraints"]),
                               generate=lambda p, e=event: _replay_event(e, p))
        if _json_copy(asdict(result)) != event["result"]:
            raise ValueError("정제 출력·실패 판정 불일치")
    routes, slices, ab = (_read_rows(out_dir / name) for name in ("routes.jsonl", "slice1_search.jsonl", "ab_records.jsonl"))
    _check_grid(routes, {c["id"] for c in BENCHMARK_CASES}, "case_id")
    _check_grid(slices, set(SLICE1_QIDS), "query_id")
    _check_grid(ab, {q["query_id"] for q in queries["queries"]}, "query_id")
    validated: set[str] = set()
    for record in routes + slices + ab:
        if (record["rewrite_enabled"] != (record["condition"] == "B") or record["hyde_enabled"] is not False
                or record["answer_test_double"] is not True or record["capabilities_test_double"] is not True):
            raise ValueError("조건·대역 표시 불일치")
        request = _request_from_record(record["request"])
        decision, _ = route_request(request)
        if _json_copy(asdict(decision)) != record["decision"]:
            raise ValueError("원요청에서 결정한 경로·계획 변경")
        if (record["actual_primary"] != str(decision.primary_path)
                or record["actual_plan"] != [str(step.path) for step in decision.plan]):
            raise ValueError("계획과 실제 경로 라벨 불일치")
        for observation in record["search_observations"] + ([record["direct"]] if "direct" in record else []):
            prepared, attempts = observation["search_input"], observation["generation_attempts"]
            steps = {step.step_id: (index, step) for index, step in enumerate(decision.plan)}
            if observation["step_id"] not in steps:
                raise ValueError("계획에 없는 검색 항목")
            index, step = steps[observation["step_id"]]
            query, constraints = _extract_query_and_constraints({"request": request, "decision": decision, "cursor": index,
                                                                 "signals": analyze_signals(request.text, request.context)},
                                                                preserve_literals=policy == PRESERVATION_POLICY_VERSION)
            if prepared["query"] != query or prepared["constraints"] != list(constraints):
                raise ValueError("검색 항목의 원입력·제약 변경")
            if len(attempts) != int(record["condition"] == "B"):
                raise ValueError("재작성 호출 수 불일치")
            event = events[attempts[0]["event_id"]] if attempts else None
            expected = prepare_search_input(prepared["query"], constraints=tuple(prepared["constraints"]),
                                            rewrite_enabled=record["condition"] == "B", hyde_enabled=False,
                                            generate=(lambda p: _replay_event(event, p)) if event else None)
            if (_json_copy(asdict(expected)) != prepared
                    or observation["search_call_count"] != int(prepared["status"] != "error")
                    or not observation["state_preserved"]):
                raise ValueError("검색 입력·호출·state 보존 불일치")
            source = observation["source_type"]
            targets = resolve_github_targets(prepared["query"], record["request"]["text"]) if source == "github" else None
            if (observation["source_group_ids"] != targets or source not in ("rawpedia", "github")
                    or observation["node"] != ("SEARCH_RAWPEDIA" if source == "rawpedia" else "SEARCH_GITHUB")
                    or step.path != (AgentPath.DOC_QA if source == "rawpedia" else AgentPath.TROUBLESHOOT)):
                raise ValueError("출처·지정 글 필터 불일치")
            hits = [SearchHit(**hit) for hit in observation["hits"]]
            if ([h.rank for h in hits] != list(range(1, len(hits) + 1)) or len(hits) > 5
                    or len({h.chunk_id for h in hits}) != len(hits)
                    or hits != sorted(hits, key=lambda h: (round(h.distance, 6), h.chunk_id))
                    or any(not math.isfinite(h.distance) or h.distance_text != format(h.distance, ".6f") for h in hits)
                    or any(h.source_type != source or (targets and h.source_group_id not in targets) for h in hits)):
                raise ValueError("검색 순위·출처·그룹 위반")
            for hit in hits:
                chunk = Chunk.from_dict({**asdict(hit), "metadata": hit.original_metadata,
                                         "char_range": frozen[hit.chunk_id].char_range})
                if chunk.to_dict() != frozen[hit.chunk_id].to_dict():
                    raise ValueError("동결 스냅샷과 본문·메타데이터 불일치")
                if (hit.source_segments != chunk.metadata["source_segments"] or hit.content_sha256 != chunk.content_sha256
                        or hit.source_group_id != chunk.metadata["source_group_id"]):
                    raise ValueError("본문·원문 세그먼트 변경")
                if hit.chunk_id not in validated:
                    validate_provenance(chunk, ROOT)
                    validated.add(hit.chunk_id)
            if _json_copy([asdict(ev) for ev in search_hits_to_evidences(hits)]) != observation["evidences"]:
                raise ValueError("Evidence 텍스트·URL·원문 위치 변경")
        if record["retrieval"]:
            successful = [o for o in record["search_observations"] if not o["error"]]
            if not successful:
                raise ValueError("검색 호출 없는 그래프 근거")
            last = successful[-1]
            if (record["retrieval"]["snapshot_ref"] != contract["snapshot_sha256"]
                    or record["retrieval"]["hits"] != last["evidences"]
                    or record["retrieval"]["source_filter"] != ("RAWPEDIA" if last["source_type"] == "rawpedia" else "GITHUB")
                    or record["retrieval"]["query"] != last["search_input"]["search_query"]):
                raise ValueError("그래프 검색 결과·스냅샷 불일치")
    cases = {c["id"]: c for c in BENCHMARK_CASES}
    for record in routes:
        case = cases[record["case_id"]]
        if (record["request"]["text"] != case["text"]
                or record["request"]["assets"] != _json_copy([asdict(a) for a in case["assets"]])
                or record["request"]["context"] != _json_copy(asdict(case["context"]) if case["context"] else None)):
            raise ValueError("고정 경로 원요청 변경")
        expected = {"expected_primary": str(case["primary_path"]), "expected_plan": [str(p) for p in case["plan"]],
                    "expected_first_branch": case["first_branch"], "expected_clarify": case["needs_clarify"]}
        if any(record[key] != value for key, value in expected.items()) or record["pass"] != _route_pass(record):
            raise ValueError("고정 경로 라벨 판정 불일치")
        if case["first_branch"] in ("CHECK_EXEC", "CLARIFY") and record["search_observations"]:
            raise ValueError("실행 전용·명확화 경로에 변환/검색 호출 발생")
    if any(r["match"] != _slice_match(r) for r in slices):
        raise ValueError("Slice 1 대조 판정 불일치")
    by_id = {q["query_id"]: q for q in queries["queries"]}
    for record in slices + ab:
        if record["request"]["text"] != by_id[record["query_id"]]["query"]:
            raise ValueError("고정 질문 변경")
    for record in ab:
        query = by_id[record["query_id"]]
        gold = query["gold_support_doc_ids"]
        counter = sorted({e["doc_id"] for e in query["evidence"]}) if not gold else []
        observations = record["search_observations"]
        hits = observations[-1]["hits"] if observations and not observations[-1]["error"] else []
        rank = _first_rank(record)
        if (record["gold_support_doc_ids"] != gold or record["source_type"] != query["source_type"]
                or record["is_negative"] != (not gold) or record["counter_evidence_doc_ids"] != counter
                or record["hits"] != hits or record["first_gold_rank"] != rank
                or record["hit_at_5"] != (rank is not None if gold else None)
                or record["mrr_at_5"] != ((1.0 / rank if rank else 0.0) if gold else None)
                or record["counter_evidence_retrieved"] != _counter_retrieved(record)):
            raise ValueError("원문 ID에서 재계산한 A/B 지표 불일치")
    metrics = {c: recompute_metrics([r for r in ab if r["condition"] == c]) for c in "AB"}
    errors = _execution_errors(routes + slices + ab, events)
    gates = acceptance_decisions(metrics["A"], metrics["B"], routes_passed=sum(r["pass"] for r in routes),
                                 slice1_matches=sum(r["match"] for r in slices), execution_errors=errors, provenance_verified=True)
    if (protocol["metrics_a"] != metrics["A"] or protocol["metrics_b"] != metrics["B"]
            or protocol["gates"] != gates or protocol["execution_errors"] != errors
            or protocol["routes_pass_count"] != sum(r["pass"] for r in routes)
            or protocol["slice1_match_count"] != sum(r["match"] for r in slices)
            or protocol["generation_totals"] != _generation_totals(routes + slices + ab, events)):
        raise ValueError("지표·오류·완료 게이트 집계 불일치")
    return gates


def validate_artifacts(out_dir: Path, query_path: Path, cache_path: Path) -> dict[str, bool]:
    try:
        return _validate_artifacts(out_dir, query_path, cache_path)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"연결 증거의 필수 필드·계약 오류: {exc}") from exc


def _counter_retrieved(record: dict[str, Any], k: int = 5) -> bool:
    counter = set(record.get("counter_evidence_doc_ids", []))
    return any(1 <= h["rank"] <= k and bool(_doc_ids_from_hit(h) & counter) for h in record["hits"])


def render_report(protocol: dict[str, Any], ab: list[dict[str, Any]], routes: list[dict[str, Any]]) -> str:
    a, b, gates = protocol["metrics_a"], protocol["metrics_b"], protocol["gates"]
    decision = ("재작성 on 채택 확정. 전체·RawPedia·GitHub의 Hit@5/MRR@5와 G1~G3가 모두 통과하여 "
                "T14-CONN/A-14 연결분을 완료로 판정한다. 인수 설정은 rewrite_enabled=True, hyde_enabled=False다."
                if gates["accepted"] else
                "재작성 on 채택 보류. A-14 연결분은 미완료다. 실패 원인을 보완한 새 실제 생성과 "
                "같은 질문·k·출처 정책의 전체 A/B로 다시 판정한다.")
    table = ["| 지표 | A: off | B: on | 비저하 |", "|---|---:|---:|---|"]
    for source in ("total", "rawpedia", "github"):
        for metric in ("hit", "mrr"):
            key = f"{source}_{metric}"
            table.append(f"| {source} {metric}@5 | {a[key]:.6f} | {b[key]:.6f} | {'통과' if b[key] >= a[key] else '실패'} |")
    failures = [f"{r['query_id']}:{r['condition']}:{o['error']['code']}:{o['search_input']['error_category']}"
                for r in ab for o in r["search_observations"] if o["error"]]
    route_errors = [f"{r['case_id']}:{r['condition']}:{o['error']['code']}"
                    for r in routes for o in r["search_observations"] if o["error"]]
    return (f"# T14-CONN 연결 검증 결과\n\n실행 `{protocol['run_id']}` ({protocol['generated_at']}).\n\n"
            f"완료 판정: **{'통과' if gates['accepted'] else '미완료'}**. 종료 코드: {0 if gates['accepted'] else 1}.\n\n"
            f"경로 라벨 {protocol['routes_pass_count']}/40, Slice 1 검색 대조 {protocol['slice1_match_count']}/30, A/B {len(ab)}행. "
            f"양성 {a['positive_count']}개·부정 {a['negative_count']}개, k=5·HyDE off.\n\n" + "\n".join(table) + "\n\n"
            f"부정 반증 검색: A {a['negative_counter_retrieved_count']}/{a['negative_count']}, B {b['negative_counter_retrieved_count']}/{b['negative_count']}.\n\n"
            f"게이트: G1={gates['G1']}, G2={gates['G2']}, G3={gates['G3']}. 기술/생성 출처 오류 {protocol['execution_errors']}건.\n\n"
            f"A/B 변환·검색 실패: {', '.join(failures) or '없음'}. 경로 집합 검색 실패: {', '.join(route_errors) or '없음'}. "
            "경로 라벨 통과와 서비스 완료를 구분한다.\n\n"
            f"고유 재작성 출처 {protocol['generation_totals']['unique_events']}개, 기존 실측 호출 "
            f"{protocol['generation_totals']['reused_source_call_count']}회, 이번 추가 생성 {protocol['generation_totals']['new_call_count']}회, "
            f"이번 재생 {protocol['generation_totals']['replay_count']}회. 공유 생성 시간은 고유 출처에서 한 번만 합산한다.\n\n"
            f"{decision}\n\n"
            f"보존 정책: `{protocol.get('preservation_policy', 'legacy')}`. 제품명·파일명·빌드 식별자와 숫자 원형 검사를 유지한다.\n\n"
            "답변·준비 상태는 대역이다. 답변 상태·인용 품질, 프로필·렌더, T17/T16 및 CP3 완료의 증거가 아니다. "
            "T17은 실제 답변·인용 검증, T16은 요청 전체 1회 폴백·종료·재개 검증을 별도 인수한다.\n\n"
            "기록 재검증은 파일·코드 해시, 생성 원응답·모델·설정, 전체 SearchHit·Evidence, 실행 전후 스냅샷, 실제 원문 파일의 위치·해시를 대조한다.\n")


def run_checks(args: argparse.Namespace) -> int:
    out = args.output_dir or ROOT / "data/eval/t14-conn" / f"conn_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    if out.exists():
        raise ValueError("출력 디렉터리가 이미 존재합니다. 새 실행 경로를 지정하십시오.")
    reference_path = args.reference.resolve()
    if not reference_path.is_relative_to(ROOT):
        raise ValueError("인계 기준 파일은 저장소 내부에 있어야 합니다.")
    queries, cache = json.loads(args.queries.read_bytes()), json.loads(args.cache.read_bytes())
    validate_generation_cache(cache, queries)
    if sha256_file(args.queries) != QUERIES_SHA or sha256_file(SLICE1_REFERENCE) != SLICE1_REFERENCE_SHA:
        raise ValueError("고정 질문 또는 Slice 1 기준 기록 변경")
    generation_run = getattr(args, "generation_run", None)
    connection_events = load_connection_generation(generation_run, args.queries, args.cache) if generation_run else None
    spec = load_spec(args.reference)
    verify_store_ready(args.store_dir, spec)
    session, store = load_encoder(spec), open_store(args.store_dir, spec)
    data = store.collection.get(include=["documents", "metadatas", "embeddings"])
    snapshot = sorted([(cid, data["documents"][i], data["metadatas"][i], data["embeddings"][i].tolist())
                       for i, cid in enumerate(data["ids"])], key=lambda row: row[0])
    snapshot_hash = _fingerprint(snapshot)
    out.mkdir(parents=True, exist_ok=False)
    recorder = GenerationRecorder(cache, args.capture_missing, checkpoint_path=out / "generation_events.json",
                                  connection_events=connection_events)
    routes, slices, ab = [], [], []
    for condition in "AB":
        run = _graph_runner(store, session, recorder, condition, snapshot_hash)
        print(f"{condition}: 경로 20개", flush=True)
        for case in BENCHMARK_CASES:
            record = run(RequestInput(request_id=f"route_{case['id']}_{condition}", text=case["text"], assets=case["assets"], context=case["context"]))
            record.update(case_id=case["id"], expected_primary=str(case["primary_path"]), expected_plan=[str(p) for p in case["plan"]],
                          expected_first_branch=case["first_branch"], expected_clarify=case["needs_clarify"])
            record["pass"] = _route_pass(record)
            routes.append(record)
        print(f"{condition}: Slice 1 15개", flush=True)
        for query in queries["queries"]:
            if query["query_id"] not in SLICE1_QIDS:
                continue
            record = run(RequestInput(request_id=f"slice_{query['query_id']}_{condition}", text=query["query"]))
            record["query_id"] = query["query_id"]
            observed = record["search_observations"]
            if len(observed) != 1:
                raise ValueError("Slice 1 단일 검색 항목을 관측하지 못했습니다.")
            graph_observation = observed[0]
            prepared = graph_observation["search_input"]
            recorder.context = (prepared["query"], tuple(prepared["constraints"]))
            attempt_start = len(recorder.attempts)
            direct_input = prepare_search_input(prepared["query"], constraints=tuple(prepared["constraints"]),
                                                generate=recorder.generate, rewrite_enabled=condition == "B", hyde_enabled=False)
            direct = {"node": graph_observation["node"], "source_type": graph_observation["source_type"],
                      "step_id": graph_observation["step_id"],
                      "source_group_ids": graph_observation["source_group_ids"], "search_input": asdict(direct_input), "error": None,
                      "hits": [], "evidences": [], "state_preserved": True, "search_call_count": 0,
                      "generation_attempts": copy.deepcopy(recorder.attempts[attempt_start:])}
            if direct_input.status != "error":
                direct["search_call_count"] = 1
                hits = store.search(direct_input.search_query, session, source_type=direct["source_type"], source_group_ids=direct["source_group_ids"])
                direct.update(hits=[asdict(h) for h in hits], evidences=[asdict(e) for e in search_hits_to_evidences(hits)])
            else:
                direct["error"] = {"code": "REWRITE_FAILED"}
            record["direct"] = _json_copy(direct)
            record["match"] = _slice_match(record)
            slices.append(record)
        print(f"{condition}: 전체 A/B 100개", flush=True)
        for query in queries["queries"]:
            record = run(RequestInput(request_id=f"ab_{query['query_id']}_{condition}", text=query["query"]))
            gold, observations = query["gold_support_doc_ids"], record["search_observations"]
            record.update(query_id=query["query_id"], query_original=query["query"], source_type=query["source_type"],
                          gold_support_doc_ids=gold, is_negative=not gold,
                          counter_evidence_doc_ids=sorted({e["doc_id"] for e in query["evidence"]}) if not gold else [],
                          hits=observations[-1]["hits"] if observations and not observations[-1]["error"] else [])
            rank = _first_rank(record)
            record.update(first_gold_rank=rank, hit_at_5=rank is not None if gold else None,
                          mrr_at_5=(1.0 / rank if rank else 0.0) if gold else None, counter_evidence_retrieved=_counter_retrieved(record))
            ab.append(record)
    errors = _execution_errors(routes + slices + ab, recorder.events)
    a, b = (recompute_metrics([r for r in ab if r["condition"] == c]) for c in "AB")
    protocol = {
        "schema_version": 2, "run_id": out.name, "generated_at": datetime.now(timezone.utc).isoformat(),
        "preservation_policy": PRESERVATION_POLICY_VERSION,
        "queries_sha256": sha256_file(args.queries), "cache_sha256": sha256_file(args.cache),
        "slice1_reference_sha256": sha256_file(SLICE1_REFERENCE),
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "code_sha256": {name: sha256_file(ROOT / name) for name in CODE_PATHS},
        "runtime": {"python": sys.version, "executable": sys.executable},
        "retrieval_contract": {"reference_path": str(reference_path.relative_to(ROOT)), "reference_sha256": spec.reference_sha256,
                               "model_id": spec.model_id, "model_revision": spec.model_revision, "collection_name": spec.collection_name,
                               "k": 5, "k0": 10, "snapshot_sha256": snapshot_hash, "snapshot_after_sha256": _store_fingerprint(store),
                               "filter_policy": "route_source_and_request_issue_discussion"},
        "hyde_enabled": False, "answer_test_double": True, "capabilities_test_double": True,
        "routes_pass_count": sum(r["pass"] for r in routes), "slice1_match_count": sum(r["match"] for r in slices),
        "metrics_a": a, "metrics_b": b, "execution_errors": errors,
        "generation_totals": _generation_totals(routes + slices + ab, recorder.events),
    }
    protocol["gates"] = acceptance_decisions(a, b, routes_passed=protocol["routes_pass_count"], slice1_matches=protocol["slice1_match_count"],
                                             execution_errors=errors, provenance_verified=True)
    if generation_run:
        source_dir = generation_run.resolve()
        protocol["generation_source_contract"] = {
            "run_path": str(source_dir.relative_to(ROOT)) if source_dir.is_relative_to(ROOT) else str(source_dir),
            "protocol_sha256": sha256_file(source_dir / "protocol.json"),
            "events_sha256": sha256_file(source_dir / "generation_events.json"),
        }
    for filename, records in (("routes.jsonl", routes), ("slice1_search.jsonl", slices), ("ab_records.jsonl", ab)):
        (out / filename).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    _write_json(out / "generation_events.json", recorder.events)
    _write_json(out / "store_snapshot.json", snapshot)
    protocol["artifact_sha256"] = {name: sha256_file(out / name) for name in ("routes.jsonl", "slice1_search.jsonl", "ab_records.jsonl", "generation_events.json", "store_snapshot.json")}
    _write_json(out / "protocol.json", protocol)
    gates = validate_artifacts(out, args.queries, args.cache)
    (out / "report.md").write_text(render_report(protocol, ab, routes), encoding="utf-8")
    print(f"기록 재검증 완료: {out}\n{gates}", flush=True)
    return 0 if gates["accepted"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=ROOT / "docs/search_eval_queries.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "docs/T08_2_t9_handoff_reference.json")
    parser.add_argument("--store-dir", type=Path, default=ROOT / "data/vector-store/t09")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/eval/t14-live-20261014-final/generation_cache.json")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--capture-missing", action="store_true", help="기존 출처와 일치하지 않는 입력·제약만 새로 실제 생성")
    parser.add_argument("--generation-run", type=Path, help="완료된 연결 실행의 실제 생성 출처를 정확한 프롬프트로 재생")
    parser.add_argument("--validate", action="store_true", help="저장된 기록을 실행 없이 독립 재검증")
    args = parser.parse_args()
    if args.validate:
        if args.output_dir is None:
            parser.error("--validate에는 --output-dir이 필요합니다.")
        gates = validate_artifacts(args.output_dir, args.queries, args.cache)
        print(gates)
        return 0 if gates["accepted"] else 1
    return run_checks(args)


if __name__ == "__main__":
    sys.exit(main())
