"""Task 14의 원검색 기록 검증, 지표 재계산 및 평가 실행."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from artagent.graph.rewrite import (
    HYDE_PROMPT_VERSION, REWRITE_PROMPT_VERSION, build_hyde_prompt,
    build_rewrite_prompt, generate_hyde_document, normalize_query,
    prepare_search_input, rewrite_query,
)
from artagent.retrieval.provenance import canonical_json_bytes, sha256_str

ROOT = Path(__file__).resolve().parents[1]
QUERY_SET_PATH = ROOT / "docs/search_eval_queries.json"
REFERENCE_PATH = ROOT / "docs/T08_2_t9_handoff_reference.json"
STORE_DIR = ROOT / "data/vector-store/t09"
REPRESENTATIVE_15_QIDS = {
    "Q001", "Q008", "Q010", "Q017", "Q018", "Q036", "Q051", "Q063",
    "Q072", "Q077", "Q084", "Q089", "Q092", "Q095", "Q096",
}
CONDITIONS = {"A": (False, False), "B": (True, False),
              "C": (False, True), "D": (True, True)}
METRIC_KEYS = ("total_hit", "total_mrr", "rawpedia_hit", "rawpedia_mrr",
               "github_hit", "github_mrr")


def compute_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _doc_ids(hit: dict[str, Any]) -> set[str]:
    return {hit["doc_id"]} | {
        segment["doc_id"] for segment in hit["source_segments"]
    }


def _first_rank(record: dict[str, Any], k: int) -> int | None:
    gold = set(record["gold_support_doc_ids"])
    return min(
        (hit["rank"] for hit in record["hits"]
         if 1 <= hit["rank"] <= k and _doc_ids(hit) & gold),
        default=None,
    )


def recompute_metrics(records: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """저장된 파생 점수 대신 원검색 순위와 원문 ID로 집계한다."""
    positives = [r for r in records if r["gold_support_doc_ids"]]
    negatives = [r for r in records if not r["gold_support_doc_ids"]]
    result: dict[str, Any] = {
        "total_count": len(records), "positive_count": len(positives),
        "negative_count": len(negatives),
        "negative_counter_retrieved_count": sum(
            bool(r["counter_evidence_retrieved"]) for r in negatives
        ),
    }
    for name, subset in (
        ("total", positives),
        ("rawpedia", [r for r in positives if r["source_type"] == "rawpedia"]),
        ("github", [r for r in positives if r["source_type"] == "github"]),
    ):
        ranks = [_first_rank(record, k) for record in subset]
        count = len(subset)
        result[f"{name}_hit_count"] = sum(rank is not None for rank in ranks)
        result[f"{name}_total"] = count
        result[f"{name}_hit"] = result[f"{name}_hit_count"] / count if count else 0.0
        result[f"{name}_mrr"] = (
            sum(1 / rank for rank in ranks if rank is not None) / count
            if count else 0.0
        )
    for suffix in ("hit", "mrr"):
        result[f"macro_{suffix}"] = (
            result[f"rawpedia_{suffix}"] + result[f"github_{suffix}"]
        ) / 2
    return result


def validate_records(
    records: list[dict[str, Any]], query_set: dict[str, Any], k: int = 5,
) -> None:
    """정본 및 원검색 결과와 모든 파생 필드를 대조한다."""
    if type(k) is not int or k <= 0:
        raise ValueError("기준 k가 유효하지 않습니다.")
    queries = {q["query_id"]: q for q in query_set["queries"]}
    if len(queries) != len(query_set["queries"]):
        raise ValueError("정본 질문 ID가 중복되었습니다.")
    expected = {(condition, qid) for condition in CONDITIONS for qid in queries}
    seen: set[tuple[str, str]] = set()
    run_ids = set()
    try:
        for record in records:
            key = (record["condition"], record["query_id"])
            if key not in expected or key in seen:
                raise ValueError(f"미지정 또는 중복 실행: {key}")
            seen.add(key)
            run_ids.add(record["run_id"])
            query = queries[record["query_id"]]
            for field, canonical in (
                ("query_original", query["query"]),
                ("source_type", query["source_type"]),
                ("gold_support_doc_ids", query["gold_support_doc_ids"]),
                ("is_negative", not bool(query["gold_support_doc_ids"])),
            ):
                if record[field] != canonical:
                    raise ValueError(f"{key}: 정본과 {field} 불일치")
            if record["generation_status"] not in ("success", "off", "error"):
                raise ValueError(f"{key}: 생성 상태 오류")
            if record.get("search_status") == "error":
                raise ValueError(f"{key}: 검색 장애로 실행 무효")
            if record["generation_status"] == "error" and record["hits"]:
                raise ValueError(f"{key}: 생성 실패 뒤 검색 결과 존재")
            if record["generation_status"] == "off" and record["condition"] != "A":
                raise ValueError(f"{key}: 생성 조건 불일치")
            ranks = []
            for hit in record["hits"]:
                rank = hit["rank"]
                if type(rank) is not int or not 1 <= rank <= k:
                    raise ValueError(f"{key}: 잘못된 순위")
                if not isinstance(hit["doc_id"], str) or not hit["doc_id"]:
                    raise ValueError(f"{key}: 원문 ID 부재")
                if not isinstance(hit["source_segments"], list):
                    raise ValueError(f"{key}: 원문 연결 정보 부재")
                if any(not isinstance(s.get("doc_id"), str)
                       or not s["doc_id"] for s in hit["source_segments"]):
                    raise ValueError(f"{key}: 원문 연결 ID 부재")
                ranks.append(rank)
            if ranks != list(range(1, len(ranks) + 1)):
                raise ValueError(f"{key}: 중복 또는 불연속 순위")
            rank = _first_rank(record, k)
            negative = not query["gold_support_doc_ids"]
            hit_value = None if negative else float(rank is not None)
            rr_value = None if negative else (1 / rank if rank is not None else 0.0)
            if record["first_correct_rank"] != rank or record["hit_at_5"] != hit_value:
                raise ValueError(f"{key}: 원검색과 정답 순위/Hit 불일치")
            rr = record["rr_at_5"]
            if rr_value is None:
                if rr is not None:
                    raise ValueError(f"{key}: 부정 질문 RR은 N/A여야 함")
            elif (not isinstance(rr, (int, float)) or not math.isfinite(rr)
                  or abs(rr - rr_value) > 1e-12):
                raise ValueError(f"{key}: 원검색과 RR 불일치")
            counter_ids = {e["doc_id"] for e in query.get("evidence", [])}
            counter = negative and any(
                _doc_ids(hit) & counter_ids for hit in record["hits"]
            )
            if record["counter_evidence_retrieved"] != counter:
                raise ValueError(f"{key}: 반대 근거 집계 불일치")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"필수 기록 필드 누락 또는 타입 오류: {exc}") from exc
    if seen != expected or len(run_ids) != 1:
        raise ValueError("질문/조건 누락 또는 실행 ID 혼합")


def adoption_decisions(metrics: dict[str, dict[str, Any]]) -> dict[str, bool]:
    """전체와 두 출처의 두 지표가 모두 비저하일 때만 채택한다."""
    for values in metrics.values():
        for key in METRIC_KEYS:
            value = values[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"잘못된 지표: {key}")

    def matches(candidate: str, baseline: str) -> bool:
        return all(metrics[candidate][key] >= metrics[baseline][key]
                   for key in METRIC_KEYS)

    return {"rewrite_pass": matches("B", "A"),
            "hyde_c_pass": matches("C", "A"),
            "hyde_d_pass": matches("D", "A") and matches("D", "B")}


def render_report(manifest: dict[str, Any], records: list[dict[str, Any]]) -> str:
    """채택 여부와 회귀를 동적으로 표시하며 미검증 실행은 보류한다."""
    lines = ["# Task 14 A/B 평가 검증 보고서", "",
             f"- 실행 ID: `{manifest['run_id']}`",
             f"- 기준 k: `{manifest['retrieval_contract']['k0']}`", ""]
    contract = manifest.get("generation_contract", {})
    if contract.get("status") != "verified":
        lines += ["판정: **보류 — 생성 출처 또는 원검색 기록 미검증**", "",
                  "기존 수치는 검증된 재작성·HyDE 효과로 사용할 수 없습니다.",
                  "질문별 실제 프롬프트·입력·출력·모델·설정과 원문 연결 정보를 확보한 뒤 다시 평가해야 합니다."]
        reasons = manifest.get("validation_errors", [])
        lines += [""] + [f"- {reason}" for reason in reasons]
        return "\n".join(lines).rstrip() + "\n"
    metrics = manifest["metrics_summary"]["all_100"]
    decisions = adoption_decisions(metrics)
    lines += ["| 조건 | 전체 Hit | 전체 MRR | RawPedia Hit/MRR | GitHub Hit/MRR |",
              "|---|---:|---:|---|---|"]
    for condition in CONDITIONS:
        m = metrics[condition]
        lines.append(
            f"| {condition} | {m['total_hit']:.6f} | {m['total_mrr']:.6f} | "
            f"{m['rawpedia_hit']:.6f}/{m['rawpedia_mrr']:.6f} | "
            f"{m['github_hit']:.6f}/{m['github_mrr']:.6f} |"
        )
    lines.append("")
    for label, key in (("재작성 B−A", "rewrite_pass"),
                       ("HyDE C−A", "hyde_c_pass"), ("결합 D−A 및 D−B", "hyde_d_pass")):
        lines.append(f"- {label} 판정: {'통과' if decisions[key] else '실패'}")
    by_condition = {c: {r["query_id"]: r for r in records if r["condition"] == c}
                    for c in CONDITIONS}
    k = manifest["retrieval_contract"]["k0"]
    regressions = []
    for qid, original in by_condition["A"].items():
        if not original["gold_support_doc_ids"]:
            continue
        rank_a = _first_rank(original, k)
        rank_b = _first_rank(by_condition["B"][qid], k)
        if (rank_b or k + 1) > (rank_a or k + 1):
            regressions.append(f"- {qid}: {rank_a} → {rank_b}")
    lines += ["", "재작성 회귀 문항:", ""] + (regressions or ["- 없음"])
    lines += ["", "대표 질문 집계:", ""]
    for condition, values in manifest["metrics_summary"].get("rep_15", {}).items():
        lines.append(f"- {condition}: 양성 {values['positive_count']}개, "
                     f"Hit {values['total_hit']:.6f}, MRR {values['total_mrr']:.6f}")
    if manifest.get("execution_mode") == "replay":
        replay_calls = sum(r.get("generation_call_count", 0) for r in records)
        source_calls = contract.get("source_call_count", 0)
        source_elapsed = contract.get("source_elapsed_ms")
        lines += ["", f"- 재생 중 생성 호출: {replay_calls}회"]
        if source_calls and source_elapsed is not None:
            lines.append(f"- 최초 생성 호출: {source_calls}회, "
                         f"합산 {source_elapsed:.2f}ms, 평균 {source_elapsed / source_calls:.2f}ms")
        else:
            lines.append("- 최초 생성 시간: 측정 기록 없음.")
    else:
        generation_times = [r["generation_elapsed_ms"] for r in records
                            if "generation_elapsed_ms" in r]
        lines += ["", (f"기록된 생성 시간 평균: {sum(generation_times) / len(generation_times):.2f}ms"
                       if generation_times else "생성 시간: 측정 기록 없음.")]
    return "\n".join(lines) + "\n"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _generation_totals(cache: dict[str, Any]) -> dict[str, int | float]:
    """조건 간 공유되는 재작성 호출은 캐시의 실제 단계에서 한 번만 센다."""
    stages = [stage for entry in cache["entries"].values() for stage in entry.values()]
    return {"source_call_count": sum(stage["generation_call_count"] for stage in stages),
            "source_elapsed_ms": sum(stage["elapsed_ms"] for stage in stages)}


def _runtime_identity(metadata: dict[str, Any]) -> dict[str, Any]:
    if (not isinstance(metadata, dict)
            or not isinstance(metadata.get("model_id"), str)
            or not metadata["model_id"].strip()
            or not isinstance(metadata.get("generation_config"), dict)):
        raise ValueError("생성 모델·설정의 실제 호출 정보가 없습니다.")
    return {key: metadata.get(key) for key in (
        "model_id", "model_revision", "generation_config", "runtime_version",
    )}


def build_generation_cache(query_set: dict[str, Any], generate: Any) -> dict[str, Any]:
    """원질문과 재작성 질문에서 각각 실제 생성하고 호출 정보를 저장한다."""
    cache: dict[str, Any] = {
        "schema_version": 2, "dataset_id": query_set["dataset_id"],
        "dataset_fingerprint": _fingerprint(query_set),
        "rewrite_prompt_version": REWRITE_PROMPT_VERSION,
        "hyde_prompt_version": HYDE_PROMPT_VERSION, "entries": {},
    }

    def capture(query: str, *, rewrite: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "input": query, "raw_output": None, "runtime_metadata": None,
            "elapsed_ms": 0.0, "generation_call_count": 0,
        }

        def call(prompt: str) -> str:
            entry.update(prompt=prompt, prompt_sha256=sha256_str(prompt),
                         generation_call_count=1)
            start = time.perf_counter()
            try:
                text, metadata = generate(prompt)
                entry.update(raw_output=text, runtime_metadata=copy.deepcopy(metadata))
                if not isinstance(text, str):
                    raise ValueError("생성 출력은 문자열이어야 합니다.")
                return text
            except Exception as exc:
                entry["generation_error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                entry["elapsed_ms"] = (time.perf_counter() - start) * 1000

        result = (rewrite_query(query, generate=call) if rewrite
                  else generate_hyde_document(query, generate=call))
        output = (result.rewritten_query if rewrite else result.hypothetical_document)
        entry.update(output=output, status=result.status,
                     error_category=result.error_category,
                     output_sha256=sha256_str(output))
        return entry

    for query in query_set["queries"]:
        original = query["query"]
        rewritten = capture(original, rewrite=True)
        original_hyde = capture(original, rewrite=False)
        combined = (capture(rewritten["output"], rewrite=False)
                    if rewritten["status"] == "success" else {
                        "input": "", "output": "", "status": "skipped",
                        "generation_call_count": 0, "elapsed_ms": 0.0,
                    })
        cache["entries"][query["query_id"]] = {
            "rewrite": rewritten, "hyde_original": original_hyde,
            "hyde_rewritten": combined,
        }
    identities = [
        _runtime_identity(entry["runtime_metadata"])
        for stages in cache["entries"].values() for entry in stages.values()
        if entry.get("raw_output") is not None
    ]
    if not identities:
        raise ValueError("출처를 확인할 수 있는 생성 응답이 없습니다.")
    cache["runtime"] = identities[0]
    cache["events_fingerprint"] = _fingerprint(cache["entries"])
    validate_generation_cache(cache, query_set)
    return cache


def validate_generation_cache(cache: dict[str, Any], query_set: dict[str, Any]) -> None:
    """입력·프롬프트·출력·모델·설정이 연결된 캐시만 재생한다."""
    try:
        if (cache["schema_version"] != 2
                or cache["dataset_id"] != query_set["dataset_id"]
                or cache["dataset_fingerprint"] != _fingerprint(query_set)
                or cache["rewrite_prompt_version"] != REWRITE_PROMPT_VERSION
                or cache["hyde_prompt_version"] != HYDE_PROMPT_VERSION
                or cache["events_fingerprint"] != _fingerprint(cache["entries"])):
            raise ValueError("생성 캐시의 정본·프롬프트·호출 지문 불일치")
        if set(cache["entries"]) != {q["query_id"] for q in query_set["queries"]}:
            raise ValueError("생성 캐시의 질문 누락 또는 중복")
        runtime = _runtime_identity(cache["runtime"])
        for query in query_set["queries"]:
            stages = cache["entries"][query["query_id"]]
            if set(stages) != {"rewrite", "hyde_original", "hyde_rewritten"}:
                raise ValueError("생성 캐시의 조건 누락")
            for stage, entry in stages.items():
                if stage == "hyde_rewritten" and stages["rewrite"]["status"] != "success":
                    if entry != {"input": "", "output": "", "status": "skipped",
                                 "generation_call_count": 0, "elapsed_ms": 0.0}:
                        raise ValueError("재작성 실패 이후 생성 기록이 존재합니다.")
                    continue
                expected_input = (stages["rewrite"]["output"]
                                  if stage == "hyde_rewritten" else query["query"])
                prompt_builder = build_rewrite_prompt if stage == "rewrite" else build_hyde_prompt
                expected_prompt = prompt_builder(normalize_query(expected_input))
                if (entry["input"] != expected_input or entry["prompt"] != expected_prompt
                        or entry["prompt_sha256"] != sha256_str(expected_prompt)
                        or entry["output_sha256"] != sha256_str(entry["output"])
                        or entry["generation_call_count"] != 1
                        or not isinstance(entry["elapsed_ms"], (int, float))
                        or not math.isfinite(entry["elapsed_ms"]) or entry["elapsed_ms"] < 0):
                    raise ValueError("생성 캐시의 입력·출력·호출 기록 불일치")
                if entry["raw_output"] is not None:
                    if not isinstance(entry["raw_output"], str):
                        raise ValueError("생성 출력 타입 불일치")
                    if _runtime_identity(entry["runtime_metadata"]) != runtime:
                        raise ValueError("생성 모델 또는 설정이 실행 도중 변경되었습니다.")

                def replay(prompt: str) -> str:
                    if entry["raw_output"] is None:
                        if not entry.get("generation_error"):
                            raise ValueError("생성 실패 원인 부재")
                        raise RuntimeError(entry["generation_error"])
                    return entry["raw_output"]

                result = (rewrite_query(expected_input, generate=replay) if stage == "rewrite"
                          else generate_hyde_document(expected_input, generate=replay))
                output = result.rewritten_query if stage == "rewrite" else result.hypothetical_document
                if (entry["status"] != result.status or entry["output"] != output
                        or entry["error_category"] != result.error_category):
                    raise ValueError("생성 캐시를 현재 계약으로 재현할 수 없습니다.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"생성 출처 또는 필수 캐시 필드 부재: {exc}") from exc


def validate_artifacts(
    manifest: dict[str, Any], records: list[dict[str, Any]], query_set_path: Path,
) -> None:
    """실제 정본 해시와 원검색 재집계 및 저장된 판정을 대조한다."""
    if manifest["dataset"]["query_set_sha256"] != compute_file_sha256(query_set_path):
        raise ValueError("정본 파일 SHA-256 불일치")
    query_set = json.loads(query_set_path.read_text(encoding="utf-8"))
    if (manifest["dataset"]["dataset_id"] != query_set["dataset_id"]
            or manifest["dataset"]["query_count"] != len(query_set["queries"])):
        raise ValueError("정본 ID 또는 질문 수 불일치")
    k = manifest["retrieval_contract"]["k0"]
    validate_records(records, query_set, k)
    dataset = manifest["dataset"]
    representative_ids = set(dataset.get("representative_qids", []))
    query_ids = {q["query_id"] for q in query_set["queries"]}
    if not representative_ids <= query_ids:
        raise ValueError("대표 질문 ID가 정본에 없습니다.")
    positives = sum(bool(q["gold_support_doc_ids"]) for q in query_set["queries"])
    for field, value in (("positive_count", positives),
                         ("negative_count", len(query_ids) - positives),
                         ("representative_15_count", len(representative_ids))):
        if field in dataset and dataset[field] != value:
            raise ValueError(f"정본과 {field} 불일치")
    for record in records:
        if (record["run_id"] != manifest["run_id"]
                or record["is_representative"] != (record["query_id"] in representative_ids)
                or ("k0" in record and record["k0"] != k)):
            raise ValueError("실행 ID·대표 질문 또는 기준 k 불일치")
    all_metrics = {}
    for condition in CONDITIONS:
        subset = [r for r in records if r["condition"] == condition]
        all_metrics[condition] = recompute_metrics(subset, k)
        for group, rows in (("all_100", subset), ("rep_15", [r for r in subset if r["is_representative"]])):
            calculated = recompute_metrics(rows, k)
            saved = manifest["metrics_summary"][group][condition]
            if any(key not in saved or not isinstance(saved[key], (int, float))
                   or not math.isfinite(saved[key]) or abs(saved[key] - value) > 1e-12
                   for key, value in calculated.items()):
                raise ValueError(f"{group}/{condition}: 원검색과 집계 불일치")
    if manifest["verification_result"] != adoption_decisions(all_metrics):
        raise ValueError("지표와 저장된 채택 판정 불일치")


def _prepare_from_cache(query: str, condition: str, stages: dict[str, Any]) -> Any:
    def replay(prompt: str) -> str:
        stage = ("rewrite" if prompt.rstrip().endswith("Rewritten Query:")
                 else "hyde_original" if condition == "C" else "hyde_rewritten")
        entry = stages[stage]
        if prompt != entry["prompt"]:
            raise ValueError("생성 캐시와 호출 프롬프트 불일치")
        if entry["raw_output"] is None:
            raise RuntimeError(entry["generation_error"])
        return entry["raw_output"]

    rewrite_enabled, hyde_enabled = CONDITIONS[condition]
    return prepare_search_input(
        query, generate=replay, rewrite_enabled=rewrite_enabled, hyde_enabled=hyde_enabled,
    )


def validate_bundle(
    manifest: dict[str, Any], records: list[dict[str, Any]],
    query_set_path: Path, cache_path: Path,
) -> None:
    """지표뿐 아니라 실제 생성 캐시 및 청크의 원문 위치까지 검증한다."""
    from artagent.retrieval.provenance import Chunk, validate_provenance
    from artagent.retrieval.types import load_spec

    validate_artifacts(manifest, records, query_set_path)
    contract = manifest["generation_contract"]
    if contract.get("status") != "verified" or contract.get("cache_sha256") != compute_file_sha256(cache_path):
        raise ValueError("생성 출처 미검증 또는 캐시 파일 해시 불일치")
    query_set = json.loads(query_set_path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    validate_generation_cache(cache, query_set)
    for key, value in _generation_totals(cache).items():
        if contract.get(key) != value:
            raise ValueError("매니페스트와 실제 생성 호출 수·측정 시간 불일치")
    if contract.get("runtime") != cache["runtime"]:
        raise ValueError("매니페스트와 실제 생성 모델·설정 불일치")
    for key in ("rewrite_prompt_version", "hyde_prompt_version"):
        if contract.get(key) != cache[key]:
            raise ValueError("매니페스트와 실제 생성 프롬프트 버전 불일치")
    reference_path = ROOT / manifest["retrieval_contract"]["reference_path"]
    if compute_file_sha256(reference_path) != manifest["retrieval_contract"]["reference_sha256"]:
        raise ValueError("검색 인계 설정 파일 해시 불일치")
    snapshots = manifest["retrieval_contract"]
    spec = load_spec(reference_path)
    for key in ("model_id", "model_revision", "collection_name"):
        if snapshots.get(key) != getattr(spec, key):
            raise ValueError(f"검색 인계 설정과 {key} 불일치")
    if not snapshots.get("snapshot_sha256") or snapshots["snapshot_sha256"] != snapshots.get("snapshot_after_sha256"):
        raise ValueError("검색 스냅샷이 실행 도중 변경되었습니다.")
    queries = {q["query_id"]: q for q in query_set["queries"]}
    validated_chunks: dict[str, str] = {}
    for record in records:
        query = queries[record["query_id"]]
        prepared = _prepare_from_cache(query["query"], record["condition"], cache["entries"][record["query_id"]])
        rewritten = prepared.rewrite_result.rewritten_query if prepared.rewrite_result else None
        hypothetical = prepared.hyde_result.hypothetical_document if prepared.hyde_result else None
        if (record["search_query"] != prepared.search_query
                or record["generation_status"] != prepared.status
                or record["rewritten_query"] != rewritten
                or record["hypothetical_document"] != hypothetical
                or record["generation_call_count"] != 0
                or record["k0"] != snapshots["k0"]):
            raise ValueError("실제 생성 캐시와 검색 실행 기록 불일치")
        for hit in record["hits"]:
            metadata = hit["original_metadata"]
            if hit["source_segments"] != metadata["source_segments"]:
                raise ValueError("원문 연결 정보가 변경되었습니다.")
            if hit["content_sha256"] != metadata["content_sha256"]:
                raise ValueError("본문 해시가 변경되었습니다.")
            chunk = Chunk.from_dict({**hit, "metadata": metadata})
            fingerprint = _fingerprint(chunk.to_dict())
            if hit["chunk_id"] in validated_chunks:
                if validated_chunks[hit["chunk_id"]] != fingerprint:
                    raise ValueError("같은 청크 ID의 본문·원문 정보가 변경되었습니다.")
            else:
                validate_provenance(chunk, ROOT)
                validated_chunks[hit["chunk_id"]] = fingerprint


def _store_fingerprint(store: Any) -> str:
    data = store.collection.get(include=["documents", "metadatas", "embeddings"])
    rows = [(identifier, data["documents"][i], data["metadatas"][i],
             data["embeddings"][i].tolist()) for i, identifier in enumerate(data["ids"])]
    return _fingerprint(sorted(rows, key=lambda row: row[0]))


def run_eval(cache_path: Path, output_dir: Path, query_set_path: Path = QUERY_SET_PATH,
             store_dir: Path = STORE_DIR) -> None:
    """검증된 생성 출력으로 고정 저장소를 검색해 새로운 실행 기록을 만든다."""
    from artagent.retrieval.embedding import load_encoder
    from artagent.retrieval.store import open_store
    from artagent.retrieval.types import load_spec
    from artagent.answer import verify_store_ready

    if output_dir.exists():
        raise ValueError("출력 디렉터리가 이미 존재합니다. 새 실행 경로를 지정하십시오.")
    query_set = json.loads(query_set_path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    validate_generation_cache(cache, query_set)
    query_hash = compute_file_sha256(query_set_path)
    cache_hash = compute_file_sha256(cache_path)
    spec = load_spec(REFERENCE_PATH)
    active_chunks = verify_store_ready(store_dir, spec)
    store = open_store(store_dir, spec)
    session = load_encoder(spec)
    snapshot = _store_fingerprint(store)
    run_id = f"t14_{time.time_ns()}"
    records = []
    for condition in CONDITIONS:
        for query in query_set["queries"]:
            stages = cache["entries"][query["query_id"]]
            prepared = _prepare_from_cache(query["query"], condition, stages)
            start = time.perf_counter()
            hits = store.search(prepared.search_query, session) if prepared.status == "success" else []
            elapsed = (time.perf_counter() - start) * 1000
            serialized = [{
                "rank": h.rank, "chunk_id": h.chunk_id, "doc_id": h.doc_id,
                "source_type": h.source_type, "source_group_id": h.source_group_id,
                "section_title": h.section_title, "content": h.content,
                "content_sha256": h.content_sha256, "source_segments": h.source_segments,
                "original_metadata": h.original_metadata, "distance": h.distance,
                "distance_text": h.distance_text,
            } for h in hits]
            record = {
                "run_id": run_id, "condition": condition, "query_id": query["query_id"],
                "query_original": query["query"], "source_type": query["source_type"],
                "gold_support_doc_ids": query["gold_support_doc_ids"],
                "is_negative": not bool(query["gold_support_doc_ids"]),
                "is_representative": query["query_id"] in REPRESENTATIVE_15_QIDS,
                "search_query": prepared.search_query, "generation_status": prepared.status,
                "generation_error": prepared.error_message, "search_status": "success",
                "rewritten_query": prepared.rewrite_result.rewritten_query if prepared.rewrite_result else None,
                "hypothetical_document": prepared.hyde_result.hypothetical_document if prepared.hyde_result else None,
                "hits": serialized, "k0": 5, "generation_call_count": 0,
                "generation_elapsed_ms": 0.0, "search_elapsed_ms": elapsed,
            }
            keys = {"A": [], "B": ["rewrite"], "C": ["hyde_original"],
                    "D": ["rewrite", "hyde_rewritten"]}[condition]
            record["source_generation_call_count"] = sum(stages[key]["generation_call_count"] for key in keys)
            record["source_generation_elapsed_ms"] = sum(stages[key]["elapsed_ms"] for key in keys)
            rank = _first_rank(record, 5)
            negative = record["is_negative"]
            record.update(
                first_correct_rank=rank,
                hit_at_5=None if negative else float(rank is not None),
                rr_at_5=None if negative else (1 / rank if rank is not None else 0.0),
                counter_evidence_retrieved=negative and any(
                    _doc_ids(hit) & {e["doc_id"] for e in query["evidence"]} for hit in serialized
                ),
            )
            records.append(record)
    after = _store_fingerprint(store)
    if (snapshot != after or query_hash != compute_file_sha256(query_set_path)
            or cache_hash != compute_file_sha256(cache_path)
            or active_chunks != verify_store_ready(store_dir, spec)):
        raise ValueError("평가 중 입력 또는 검색 스냅샷이 변경되었습니다.")
    metrics = {c: recompute_metrics([r for r in records if r["condition"] == c]) for c in CONDITIONS}
    representatives = {c: recompute_metrics([r for r in records if r["condition"] == c and r["is_representative"]])
                       for c in CONDITIONS}
    manifest = {
        "schema_version": 2, "run_id": run_id, "execution_mode": "replay",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "code_sha256": {str(p.relative_to(ROOT)): compute_file_sha256(p) for p in (
            Path(__file__), ROOT / "src/artagent/graph/rewrite.py",
        )},
        "dataset": {"dataset_id": query_set["dataset_id"], "query_set_sha256": query_hash,
                    "query_count": len(query_set["queries"]), "input_manifest": query_set.get("input_manifest", {}),
                    "positive_count": sum(bool(q["gold_support_doc_ids"]) for q in query_set["queries"]),
                    "negative_count": sum(not q["gold_support_doc_ids"] for q in query_set["queries"]),
                    "representative_qids": sorted(REPRESENTATIVE_15_QIDS & {q["query_id"] for q in query_set["queries"]})},
        "retrieval_contract": {"k0": 5, "reference_path": str(REFERENCE_PATH.relative_to(ROOT)),
                               "reference_sha256": compute_file_sha256(REFERENCE_PATH),
                               "model_id": spec.model_id, "model_revision": spec.model_revision,
                               "collection_name": spec.collection_name, "snapshot_sha256": snapshot,
                               "snapshot_after_sha256": after, "active_chunks": active_chunks},
        "generation_contract": {"status": "verified", "cache_sha256": cache_hash,
                                "runtime": cache["runtime"], "rewrite_prompt_version": REWRITE_PROMPT_VERSION,
                                "hyde_prompt_version": HYDE_PROMPT_VERSION,
                                **_generation_totals(cache)},
        "metrics_summary": {"all_100": metrics, "rep_15": representatives},
        "verification_result": adoption_decisions(metrics),
    }
    validate_bundle(manifest, records, query_set_path, cache_path)
    output_dir.mkdir(parents=True)
    shutil.copyfile(cache_path, output_dir / "generation_cache.json")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(manifest, records), encoding="utf-8")


def _runtime_generate(prompt: str) -> tuple[str, dict[str, Any]]:
    from artagent.answer import generate_llm_response

    instruction = "검색 입력 변환만 수행하십시오. 출력은 answer에 넣고 citation_ids는 빈 목록으로 두십시오."
    raw, _, metadata = generate_llm_response(instruction, prompt, {}, prompt)
    response = json.loads(raw)
    if response["citation_ids"] or not isinstance(response["answer"], str):
        raise ValueError("검색 입력 변환 출력 계약 위반")
    trace = metadata.get("_trace")
    runtime = {"model_id": metadata["model_id"],
               "generation_config": {**metadata["generation_config"], "system_instruction": instruction},
               "trace_sha256": _fingerprint(trace) if trace is not None else None}
    return response["answer"], runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-set", type=Path, default=QUERY_SET_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="기존 생성 런타임으로 조건별 캐시 생성")
    generate.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("replay", help="검증한 캐시로 새 검색 평가 실행")
    replay.add_argument("--cache", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)
    replay.add_argument("--store-dir", type=Path, default=STORE_DIR)
    validate = commands.add_parser("validate", help="원검색·정본·생성 캐시 연결 검증")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--records", type=Path, required=True)
    validate.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            if args.output.exists():
                raise ValueError("생성 캐시 출력 파일이 이미 존재합니다.")
            query_set = json.loads(args.query_set.read_text(encoding="utf-8"))
            cache = build_generation_cache(query_set, _runtime_generate)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
        elif args.command == "replay":
            run_eval(args.cache, args.output_dir, args.query_set, args.store_dir)
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
            validate_bundle(manifest, records, args.query_set, args.cache)
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(f"검증 또는 실행 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
