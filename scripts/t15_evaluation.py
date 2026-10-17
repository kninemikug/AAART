"""Task 15 순수 지표·채택 판정과 모델 호출 없는 증거 검증."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, Sequence
import gzip
import hashlib
import json
import math

import numpy as np
from artagent.retrieval.types import SearchHit
from artagent.retrieval.rerank import BM25Reranker
from artagent.retrieval.provenance import canonical_json_str, deserialize_chunk, validate_provenance
from artagent.graph.search import search_hits_to_evidences, resolve_github_targets
from artagent.graph.state import RetrievalBundle

ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = {"R1": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "R2": "cross-encoder/ms-marco-MiniLM-L6-v2"}
CODE_PATHS = ["scripts/eval_t15_rerank.py", "scripts/t15_evaluation.py", "scripts/t15_answer_validation.py", "scripts/check_t14_graph_connection.py",
              "scripts/run_t14_ab_eval.py", "tests/test_router.py"] + [str(p.relative_to(ROOT)) for folder in ("retrieval", "graph")
              for p in sorted((ROOT / "src/artagent" / folder).glob("*.py"))] + ["src/artagent/answer.py", "src/artagent/answer_validation.py"]
SLICE1_QIDS = ['Q001','Q004','Q014','Q021','Q033','Q044','Q054','Q063','Q072','Q080','Q084','Q086','Q092','Q093','Q096']
FOCUS_12_QIDS = ['Q017','Q024','Q025','Q026','Q030','Q033','Q041','Q053','Q055','Q057','Q070','Q072']
T17_CRITICAL_31_QIDS = sorted(set(SLICE1_QIDS + FOCUS_12_QIDS + ['Q010','Q077','Q097','Q098','Q099','Q100']))
EXPECTED_FILES = {
 'docs/search_eval_queries.json': '91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8',
 'docs/T08_2_t9_handoff_reference.json': '2c7081ba6a7c37b00735b0be2ef362f5b0c2a86cd41fe97bbb2a3b5ebdc195bc',
 'data/eval/t14-conn/conn_20261015_pr/ab_records.jsonl': '96f11d6d63f41896c1b8cf028f52b0932d121d3d5ad4093c69a33802ea0dfd0e',
}

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def doc_ids_from_hit(hit: SearchHit | dict[str, Any]) -> set[str]:
    """선택된 청크의 실제 source_segments[].doc_id를 합쳐 중복 제거한 집합 반환."""
    if isinstance(hit, SearchHit):
        segs = hit.source_segments
        ids = {s["doc_id"] for s in segs if isinstance(s, dict) and s.get("doc_id")}
        if not ids and hit.doc_id:
            ids = {hit.doc_id}
        return ids
    segs = hit.get("source_segments", [])
    ids = {s["doc_id"] for s in segs if isinstance(s, dict) and s.get("doc_id")}
    if not ids and hit.get("doc_id"):
        ids = {hit["doc_id"]}
    return {i for i in ids if i}


def extract_counter_evidence_ids(q: dict[str, Any]) -> set[str]:
    """부정 질문의 반증 문서 ID를 evidence[].doc_id에서 중복 제거하여 추출 (F02/R4)."""
    counter = set()
    for ev in q.get("evidence", []):
        if isinstance(ev, dict) and ev.get("doc_id"):
            counter.add(ev["doc_id"])
    if not counter and q.get("counter_evidence_doc_ids"):
        counter = set(q["counter_evidence_doc_ids"])
    return counter


def fit_bm25_from_snapshot(snapshot_rows: Sequence[Sequence[Any]]) -> BM25Reranker:
    """Chroma 스냅샷 154개 물리 청크에 BM25 적합 및 코퍼스 지문 생성 (F04/R5)."""
    corpus = [
        f"{m.get('section_title', '')}\n\n{d}".strip() if m.get("section_title") else d
        for _, d, m, _ in snapshot_rows
    ]
    return BM25Reranker(corpus, model_id="lexical_bm25")


def calculate_first_gold_rank(
    hits: Sequence[SearchHit | dict[str, Any]],
    gold_ids: set[str],
    max_k: Optional[int] = None,
) -> Optional[int]:
    if not gold_ids:
        return None
    for idx, hit in enumerate(hits, start=1):
        if max_k is not None and idx > max_k:
            break
        h_docs = doc_ids_from_hit(hit)
        if h_docs & gold_ids:
            return idx
    return None


def compute_metrics_for_records(
    per_query_results: dict[str, dict[str, Any]],
    query_set_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """문서 ID 집합 기반 context precision/recall 및 Hit@5, MRR@5, 반증 도달 계산."""
    positives = [qid for qid, q in query_set_map.items() if q.get("gold_support_doc_ids")]
    negatives = [qid for qid, q in query_set_map.items() if not q.get("gold_support_doc_ids")]

    def _eval_subset(qids: list[str]) -> dict[str, Any]:
        if not qids:
            return {
                "precision": 0.0, "recall": 0.0, "hit_at_5": 0.0, "mrr_at_5": 0.0,
                "micro_precision": 0.0, "micro_recall": 0.0, "count": 0,
            }
        prec_list, rec_list, hit_list, mrr_list = [], [], [], []
        total_intersect = 0
        total_selected = 0
        total_gold = 0
        for qid in qids:
            res = per_query_results.get(qid, {})
            p = res.get("precision", 0.0)
            r = res.get("recall", 0.0)
            prec_list.append(p)
            rec_list.append(r)
            f_rank = res.get("first_gold_rank")
            hit_list.append(1.0 if f_rank is not None and f_rank <= 5 else 0.0)
            mrr_list.append(1.0 / f_rank if f_rank is not None and f_rank <= 5 else 0.0)
            total_intersect += res.get("intersect_count", 0)
            total_selected += res.get("selected_doc_count", 0)
            total_gold += res.get("gold_count", 0)

        n = len(qids)
        return {
            "count": n,
            "precision": sum(prec_list) / n,
            "recall": sum(rec_list) / n,
            "hit_at_5": sum(hit_list) / n,
            "mrr_at_5": sum(mrr_list) / n,
            "micro_precision": total_intersect / total_selected if total_selected else 0.0,
            "micro_recall": total_intersect / total_gold if total_gold else 0.0,
        }

    rawpedia_pos = [qid for qid in positives if query_set_map[qid]["source_type"] == "rawpedia"]
    github_pos = [qid for qid in positives if query_set_map[qid]["source_type"] == "github"]
    slice1_pos = [qid for qid in positives if qid in SLICE1_QIDS]

    neg_counter_retrieved = sum(
        1 for qid in negatives if per_query_results.get(qid, {}).get("counter_evidence_retrieved")
    )

    return {
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "negative_counter_retrieved_count": neg_counter_retrieved,
        "total": _eval_subset(positives),
        "rawpedia": _eval_subset(rawpedia_pos),
        "github": _eval_subset(github_pos),
        "slice1": _eval_subset(slice1_pos),
    }


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_str(value).encode()).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def summarize(hits: Sequence[SearchHit | dict], question: dict) -> dict:
    gold = set(question["gold_support_doc_ids"])
    counter = extract_counter_evidence_ids(question) if not gold else set()
    ids = set().union(*(doc_ids_from_hit(hit) for hit in hits)) if hits else set()
    overlap = len(ids & gold)
    return {
        "precision": (overlap / len(ids) if ids else 0.0) if gold else None,
        "recall": overlap / len(gold) if gold else None,
        "first_gold_rank": calculate_first_gold_rank(hits, gold),
        "intersect_count": overlap, "selected_doc_count": len(ids), "gold_count": len(gold),
        "counter_evidence_retrieved": bool(ids & counter),
        "counter_precision": len(ids & counter) / len(ids) if counter and ids else None,
        "counter_recall": len(ids & counter) / len(counter) if counter else None,
    }


def compare_quality(current: dict, baseline: dict) -> list[str]:
    issues = []
    for subset in ("total", "rawpedia", "github", "slice1"):
        for metric in ("precision", "recall", "hit_at_5", "mrr_at_5"):
            if current[subset][metric] < baseline[subset][metric] - 1e-12:
                issues.append(f"{subset}.{metric}")
    return issues


def regressions(current: dict, baseline: dict) -> list[tuple]:
    return [(qid, old["first_gold_rank"], current[qid]["first_gold_rank"])
            for qid, old in baseline.items() if old["gold_count"]
            and (current[qid]["first_gold_rank"] or math.inf) > (old["first_gold_rank"] or math.inf)]


def select_condition(results: Sequence[dict]) -> Optional[dict]:
    passing = [row for row in results if row["G2"] and row["G3"]]
    return min(passing, key=lambda row: (
        -min(row["on_metrics"]["total"]["recall"], row["off_metrics"]["total"]["recall"]),
        -sum(row[key]["total"]["precision"] for key in ("on_metrics", "off_metrics")),
        row["top_k"], row["condition_id"],
    )) if passing else None


def should_expand_candidates(results: Sequence[dict], focus_ranks: dict) -> bool:
    return (not any(row["G2"] and row["G3"] for row in results)
            or any(focus_ranks.get(qid) is None for qid in ("Q024", "Q030", "Q070")))


def repeat_verdict(summaries: Optional[list[dict]]) -> str:
    if not summaries or len(summaries) != 3:
        return "PENDING"
    if ({row.get("repeat_index") for row in summaries} != {1, 2, 3}
            or any(row.get("record_count") != 200 or not row.get("result_digest") for row in summaries)):
        return "PENDING"
    return "PASS" if len({row["result_digest"] for row in summaries}) == 1 else "FAIL"


def evaluate_gates(*, g0_reproduced: bool, router_results: dict, b_metrics: dict,
                   b0_metrics: dict, b_regressions: list, a_metrics: Optional[dict] = None,
                   a0_metrics: Optional[dict] = None, a_regressions: Optional[list] = None,
                   repeat_summaries: Optional[list] = None, t17_summary: Optional[dict] = None,
                   coverage_complete: bool = False) -> dict:
    gates = {"G0": {"status": "PASS" if g0_reproduced else "FAIL", "detail": "기준선 원시 결과 대조"}}
    routed = router_results.get("passed") == router_results.get("total") == 40
    gates["G1"] = {"status": ("PASS" if routed else "FAIL") if router_results.get("verified") else "PENDING",
                   "detail": "실제 그래프 경로40건·필터·상태 검증"}
    issues = ["B:" + item for item in compare_quality(b_metrics, b0_metrics)]
    if a_metrics is not None and a0_metrics is not None:
        issues += ["A:" + item for item in compare_quality(a_metrics, a0_metrics)]
    gates["G2"] = {"status": "FAIL" if issues else ("PASS" if a_metrics is not None else "PENDING"),
                   "detail": ", ".join(issues) or "양경로·전체/출처/Slice 1 비저하"}
    g3_bad = bool(b_regressions or a_regressions)
    g3_bad |= b_metrics.get("negative_counter_retrieved_count", 0) < b0_metrics.get("negative_counter_retrieved_count", 5)
    if a_metrics is not None and a0_metrics is not None:
        g3_bad |= a_metrics.get("negative_counter_retrieved_count", 0) < a0_metrics.get("negative_counter_retrieved_count", 5)
    gates["G3"] = {"status": "FAIL" if g3_bad else ("PASS" if a_regressions is not None else "PENDING"),
                   "detail": f"B 순위저하 {len(b_regressions)}건·A 순위저하 {len(a_regressions or [])}건"}
    gates["G4"] = {"status": "PASS" if coverage_complete else "PENDING", "detail": "전수 기록·집중12개 검증"}
    repeated = repeat_verdict(repeat_summaries)
    live = t17_summary or {}
    live_bad = any(live.get(key, 0) for key in ("error_count", "unsupported_as_supported_count")) or live.get("product_scope_safe") is False
    complete = (live.get("live_verified") is True and live.get("manual_review_complete") is True
                and live.get("record_count", 0) >= 62 and live.get("is_mock") is False)
    gates["G5"] = {"status": "FAIL" if repeated == "FAIL" or live_bad else ("PASS" if repeated == "PASS" and complete else "PENDING"),
                   "detail": f"전체200개×3회={repeated}; 실제 답변/인용·수동 검토={'PASS' if complete else 'PENDING'}"}
    verdict = "FAIL" if any(g["status"] == "FAIL" for g in gates.values()) else ("PENDING" if any(g["status"] == "PENDING" for g in gates.values()) else "PASS")
    return {"gates": gates, "overall_verdict": verdict, "exit_code": {"PASS": 0, "FAIL": 1, "PENDING": 2}[verdict],
            "adoption_status": "PASS" if verdict == "PASS" else "B0_MAINTAINED",
            "violations": [f"{name}: {g['detail']}" for name, g in gates.items() if g["status"] == "FAIL"]}


class MissingEvidence(ValueError):
    """요구된 실측 증거가 없어 합격 여부를 확인할 수 없음."""


def verify_protocol(path: Path) -> dict:
    protocol = json.loads(path.read_bytes())
    if protocol.get("schema_version") != 3:
        raise MissingEvidence("v3 프로토콜·원시 증거가 필요합니다. 과거 기록은 소급 보완하지 않습니다.")
    if set(protocol["code_sha256"]) != set(CODE_PATHS):
        raise ValueError("실행 코드 지문 목록 누락/추가")
    if protocol["grid"] != {"candidate_k": [20, 40], "top_k": [3, 5, 10, 20], "min_score": [None, 0., .2, .5, .7]}:
        raise ValueError("고정 격자 조건 변경")
    if set(protocol["models"]) != {"R1", "R2", "R3"}:
        raise ValueError("사전 등록한 후보 누락")
    for name, model_id in MODEL_IDS.items():
        model = protocol["models"][name]
        if (model["model_id"] != model_id or len(model["revision"]) != 40 or not model["files"]
                or model["max_length"] != 512 or model["overlap_tokens"] != 64
                or model["max_header_tokens"] != 32 or model["aggregation"] != "max_window_v2_offsets"):
            raise ValueError("고정 리랭커 조건 변경")
    for name, entry in protocol["inputs"].items():
        target = ROOT / entry["path"]
        if sha256_file(target) != entry["sha256"]:
            raise ValueError(f"입력 해시 불일치: {name}")
    for name, expected_path in (("queries", "docs/search_eval_queries.json"),
                                ("reference", "docs/T08_2_t9_handoff_reference.json"),
                                ("ab_records", "data/eval/t14-conn/conn_20261015_pr/ab_records.jsonl")):
        if protocol["inputs"][name]["sha256"] != EXPECTED_FILES[expected_path]:
            raise ValueError("고정 평가 입력의 대체 금지")
    snapshot = json.loads((ROOT / protocol["inputs"]["snapshot"]["path"]).read_bytes())
    if digest(snapshot) != protocol["snapshot_fingerprint"] or digest(snapshot) != "09e7ce0af1a4744bbb02f0d07eb716b5f0a4e2ba6d1e20d7a727707c8ffcbae6":
        raise ValueError("고정 스냅샷 변경")
    bm25 = fit_bm25_from_snapshot(snapshot)
    if protocol["models"]["R3"]["corpus_fingerprint"] != bm25.corpus_fingerprint or protocol["models"]["R3"]["n_docs"] != 154:
        raise ValueError("BM25 적합 코퍼스 변경")
    for name, expected in EXPECTED_FILES.items():
        if sha256_file(ROOT / name) != expected:
            raise ValueError(f"고정 기준선 변경: {name}")
    for name, expected in protocol["code_sha256"].items():
        if sha256_file(ROOT / name) != expected:
            raise ValueError(f"실행 코드 불일치: {name}")
    for model in protocol["models"].values():
        if model.get("files"):
            for name, expected in model["files"].items():
                if sha256_file(Path(model["cache_path"]) / name) != expected:
                    raise ValueError(f"모델/토크나이저 파일 변경: {name}")
    return protocol


def verify_manifest(run_dir: Path, protocol_path: Optional[Path] = None) -> tuple[dict, dict]:
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise MissingEvidence("실행 manifest와 입력/코드·원문 연결 증거가 없습니다.")
    manifest = json.loads(path.read_bytes())
    if manifest.get("schema_version") != 3 or manifest.get("execution_error"):
        raise ValueError("실행 실패 또는 잘못된 manifest")
    actual_protocol = protocol_path or ROOT / manifest["protocol_path"]
    if sha256_file(actual_protocol) != manifest["protocol_sha256"]:
        raise ValueError("프로토콜 해시 불일치")
    protocol = verify_protocol(actual_protocol)
    actual_files = {p.name for p in run_dir.iterdir() if p.is_file() and p.name != "manifest.json"}
    if set(manifest["artifacts"]) != actual_files:
        raise ValueError("manifest 증거 파일 목록 불일치")
    for name, expected in manifest["artifacts"].items():
        target = (run_dir / name).resolve()
        if not target.is_relative_to(run_dir.resolve()) or sha256_file(target) != expected:
            raise ValueError(f"증거 파일 변경/누락: {name}")
    return protocol, manifest


class RecordVerifier:
    """스냅샷 원문·거리·채점·선택을 저장 데이터만으로 전수 대조한다."""

    def __init__(self, protocol: dict):
        self.protocol = protocol
        self.questions = {q["query_id"]: q for q in json.loads((ROOT / protocol["inputs"]["queries"]["path"]).read_bytes())["queries"]}
        self.t14 = {(r["condition"], r["query_id"]): r for r in read_rows(ROOT / protocol["inputs"]["ab_records"]["path"])}
        rows = json.loads((ROOT / protocol["inputs"]["snapshot"]["path"]).read_bytes())
        self.snapshot = {row[0]: row for row in rows}
        for cid, text, metadata, vector in rows:
            chunk = deserialize_chunk(cid, text, metadata)
            validate_provenance(chunk, ROOT)
            if metadata["content_sha256"] != hashlib.sha256(text.encode()).hexdigest():
                raise ValueError(f"원문 청크 해시 불일치: {cid}")

    def hydrate(self, item: dict) -> SearchHit:
        cid = item["chunk_id"]
        if cid not in self.snapshot:
            raise ValueError(f"스냅샷에 없는 청크: {cid}")
        _, text, meta, _ = self.snapshot[cid]
        chunk = deserialize_chunk(cid, text, meta)
        return SearchHit(item["rank"], cid, meta["source_type"], meta["doc_id"], meta["source_group_id"],
                         meta.get("section_title", ""), text, meta["content_sha256"],
                         chunk.metadata["source_segments"], chunk.metadata,
                         item["distance"], item["distance_text"])

    def search(self, record: dict) -> list[SearchHit]:
        qid, condition = record["query_id"], record["condition"]
        parent = self.t14[condition, qid]
        observation = parent["search_observations"][0]
        expected_query = observation["search_input"]["search_query"]
        source = "github" if observation["node"] == "SEARCH_GITHUB" else "rawpedia"
        groups = resolve_github_targets(expected_query, self.questions[qid]["query"]) if source == "github" else None
        if record["search_query"] != expected_query or record["source_type"] != source or record["source_group_ids"] != groups:
            raise ValueError(f"질의/출처/대상 글 변경: {qid}")
        vector = np.asarray(record["query_vector"], dtype=np.float32)
        if vector.shape != (384,) or not np.isfinite(vector).all() or abs(np.linalg.norm(vector) - 1) > 1e-5:
            raise ValueError("질의 벡터 계약 위반")
        candidates = record["candidates"]
        if len({c["chunk_id"] for c in candidates}) != len(candidates):
            raise ValueError("중복 검색 후보")
        eligible = {cid: row for cid, row in self.snapshot.items() if not row[2]["excluded"]
                    and row[2]["source_type"] == source and (groups is None or row[2]["source_group_id"] in groups)}
        if len(candidates) != min(record["candidate_k"], len(eligible)):
            raise ValueError("후보 풀 개수 불일치")
        distances = {cid: 1 - float(np.dot(vector, np.asarray(row[3], dtype=np.float32))) for cid, row in eligible.items()}
        for index, item in enumerate(candidates, 1):
            cid = item["chunk_id"]
            if cid not in eligible or item["rank"] != index or abs(distances[cid] - item["distance"]) > 1e-5:
                raise ValueError("후보 순위/거리/출처 계약 위반")
            if item["distance_text"] != format(item["distance"], ".6f"):
                raise ValueError("거리 표시 계약 위반")
        if candidates != sorted(candidates, key=lambda x: (round(x["distance"], 6), x["chunk_id"])):
            raise ValueError("dense 정렬 계약 위반")
        if candidates:
            selected_ids = {c["chunk_id"] for c in candidates}
            cutoff = candidates[-1]["distance"]
            if any(value < cutoff - 1e-5 for cid, value in distances.items() if cid not in selected_ids):
                raise ValueError("상위 후보 누락")
        return [self.hydrate(item) for item in candidates]

    def selected(self, search: dict, scored: dict, config: dict) -> tuple[list[SearchHit], dict]:
        candidates = self.search(search)
        ids = [h.chunk_id for h in candidates]
        if [s["chunk_id"] for s in scored["scores"]] != ids:
            raise ValueError("후보와 채점 레코드 불일치")
        for hit, item in zip(candidates, scored["scores"]):
            raw, selection = item["raw_score"], item["selection_score"]
            if not math.isfinite(raw) or not math.isfinite(selection):
                raise ValueError("비유한 리랭크 점수")
            if config["model"] == "R3":
                expected = raw / (1 + raw)
            else:
                expected = 1 / (1 + math.exp(-raw)) if raw >= 0 else math.exp(raw) / (1 + math.exp(raw))
                windows = item["windows"]
                covered = 0
                for window in windows:
                    start, end = window["content_char_start"], window["content_char_end"]
                    if not 0 <= start <= covered <= len(hit.content) or not start <= end <= len(hit.content):
                        raise ValueError("채점 윈도우 원문 누락/좌표 오류")
                    if window["pair_tokens"] > self.protocol["models"][config["model"]]["max_length"]:
                        raise ValueError("채점 pair 길이 초과")
                    if (window["content_byte_start"] != len(hit.content[:start].encode())
                            or window["content_byte_end"] != len(hit.content[:end].encode())):
                        raise ValueError("채점 윈도우 바이트 좌표 오류")
                    covered = max(covered, end)
                if covered != len(hit.content) or max(w["raw_score"] for w in windows) != raw:
                    raise ValueError("윈도우 누락/집계 점수 불일치")
            if abs(expected - selection) > 1e-12:
                raise ValueError("점수 변환 불일치")
        ordered = sorted(zip(candidates, scored["scores"]), key=lambda pair: (-pair[1]["selection_score"], pair[0].rank, pair[0].chunk_id))
        chosen = [h for h, score in ordered[:config["top_k"]]
                  if config["min_score"] is None or score["selection_score"] >= config["min_score"]]
        return chosen, summarize(chosen, self.questions[search["query_id"]])


def unique_rows(rows: list[dict], keys: tuple[str, ...]) -> dict:
    indexed = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        if key in indexed:
            raise ValueError(f"중복 실행 조합: {key}")
        indexed[key] = row
    return indexed


def verify_routes(rows: list[dict], verifier: Optional[RecordVerifier] = None) -> dict:
    from tests.test_router import BENCHMARK_CASES
    cases = {case["id"]: case for case in BENCHMARK_CASES}
    indexed = unique_rows(rows, ("condition", "case_id"))
    if set(indexed) != {(condition, qid) for condition in ("A", "B") for qid in cases}:
        raise ValueError("실제 그래프40개 요청의 중복/누락")
    passed = 0
    for (condition, qid), row in indexed.items():
        case = cases[qid]
        wanted = (str(case["primary_path"]), [str(p) for p in case["plan"]], case["first_branch"], case["needs_clarify"])
        actual = (row["actual_primary"], row["actual_plan"], row["actual_first_branch"], row["actual_clarify"])
        if row["request"]["text"] != case["text"] or "ROUTE" not in row["trace"]:
            raise ValueError("실제 라우터 입력/trace 누락")
        if not all(observation["state_preserved"] and observation["error"] is None for observation in row["search_observations"]):
            raise ValueError("검색 노드 상태/오류 계약 위반")
        traced_searches = [name for name in row["trace"] if name in ("SEARCH_RAWPEDIA", "SEARCH_GITHUB")]
        if traced_searches != [o["node"] for o in row["search_observations"]]:
            raise ValueError("그래프 검색 trace와 실제 검색 관측 불일치")
        for observation in row["search_observations"]:
            source = "github" if observation["node"] == "SEARCH_GITHUB" else "rawpedia"
            search_input = observation["search_input"]
            groups = resolve_github_targets(search_input["search_query"], search_input["query"]) if source == "github" else None
            if observation["source_type"] != source or observation["source_group_ids"] != groups or observation["search_call_count"] != 1:
                raise ValueError("실제 검색 출처/대상 글/호출 계약 위반")
            if verifier is not None:
                hits = []
                for item in observation["hits"]:
                    hit = verifier.hydrate(item)
                    if (hit.source_type != source or verifier.snapshot[hit.chunk_id][2]["excluded"] or
                            (groups is not None and hit.source_group_id not in groups)):
                        raise ValueError("그래프 검색 출처/제외/대상 글 위반")
                    for name in ("content", "content_sha256", "source_segments", "doc_id", "source_group_id", "section_title"):
                        if item[name] != getattr(hit, name):
                            raise ValueError("그래프 검색 원문/세그먼트 위반")
                    hits.append(hit)
                if digest(observation["evidences"]) != digest([asdict(e) for e in search_hits_to_evidences(hits)]):
                    raise ValueError("그래프 Evidence 전달 계약 위반")
        first = next((name for name in row["trace"][row["trace"].index("ROUTE") + 1:]
                      if name in ("SEARCH_RAWPEDIA", "SEARCH_GITHUB", "CHECK_EXEC", "CLARIFY")), None)
        if first != row["actual_first_branch"]:
            raise ValueError("라우터 trace와 관측 요약 불일치")
        passed += int(actual == wanted)
    return {"passed": passed, "total": 40, "verified": verifier is not None}


def score_result_digest(score: dict) -> str:
    return digest({key: score[key] for key in ("model", "condition", "query_id", "candidate_k", "scores")})


def result_digest(rows: list[dict]) -> str:
    return digest(sorted([{key: row[key] for key in ("condition", "query_id", "selected_chunk_ids", "score_result_digest", "bundle_digest", "metrics")}
                          for row in rows], key=lambda row: (row["condition"], row["query_id"])))


def audit_run(run_dir: Path, protocol_path: Optional[Path] = None,
              selected_path: Optional[Path] = None, manual_path: Optional[Path] = None) -> dict:
    protocol, manifest = verify_manifest(run_dir, protocol_path)
    verifier = RecordVerifier(protocol)
    phase = manifest["phase"]
    if phase not in ("grid", "regression", "t17"):
        raise ValueError("알 수 없는 실행 단계")
    if phase != "grid":
        linked = ROOT / manifest["selected_path"]
        verify_manifest(linked.parent)
        if sha256_file(linked) != manifest["selected_sha256"]:
            raise ValueError("선정 설정 연결 불일치")
        if (run_dir / "skipped.json").exists():
            parent = audit_run(linked.parent)
            if parent.get("selected_condition") is not None:
                raise ValueError("합격 후보가 있는데 후속 검증을 생략함")
            return {"overall_verdict": "PENDING", "exit_code": 2, "adoption_status": "B0_MAINTAINED",
                    "reason": json.loads((run_dir / "skipped.json").read_bytes())["reason"]}
    if selected_path is not None and sha256_file(selected_path) != manifest.get("selected_sha256"):
        raise ValueError("선정 설정 해시 불일치")
    if phase == "t17":
        return audit_answers(run_dir, protocol, manifest, verifier, manual_path)
    search_rows = read_rows(run_dir / "search_records.jsonl.gz")
    score_rows = read_rows(run_dir / "score_records.jsonl.gz")
    searches = unique_rows(search_rows, ("condition", "query_id", "candidate_k", "repeat_index"))
    scores = unique_rows(score_rows, ("model", "condition", "query_id", "candidate_k", "repeat_index"))
    # 전체 후보와 윈도우는 컷/필터 조건 수와 무관하게 한 번만 검증한다.
    verified = {}
    for key, scored in scores.items():
        model, condition, qid, pool, repetition = key
        search = searches[condition, qid, pool, repetition]
        hits, _ = verifier.selected(search, scored, {"model": model, "top_k": pool, "min_score": None})
        verified[key] = hits
    baseline = {"A": {}, "B": {}}
    for row in read_rows(run_dir / "baseline_records.jsonl.gz"):
        hits = verifier.search(row)[:5]
        expected = verifier.t14[row["condition"], row["query_id"]]["hits"]
        if [h.chunk_id for h in hits] != [h["chunk_id"] for h in expected]:
            raise ValueError("기준선 top5 ID/순서 불일치")
        for hit, original in zip(hits, expected):
            if hit.distance_text != original["distance_text"] or hit.source_segments != original["source_segments"]:
                raise ValueError("기준선 거리/원문 위치 불일치")
        if row["query_id"] in baseline[row["condition"]]:
            raise ValueError("중복 기준선")
        baseline[row["condition"]][row["query_id"]] = summarize(hits, verifier.questions[row["query_id"]])
    if any(set(rows) != set(verifier.questions) for rows in baseline.values()):
        raise ValueError("A0/B0 전수 기준선 누락")
    baseline_metrics = {c: compute_metrics_for_records(rows, verifier.questions) for c, rows in baseline.items()}
    trials = read_rows(run_dir / "records.jsonl.gz")
    unique_rows(trials, ("condition_id", "condition", "query_id", "repeat_index"))
    configs = {row["condition_id"]: row for row in json.loads((run_dir / "conditions.json").read_bytes())}
    if phase == "regression":
        chosen = json.loads(linked.read_bytes())["configuration"]
        if len(configs) != 1 or digest(next(iter(configs.values()))) != digest(chosen):
            raise ValueError("선정 설정과 실제 회귀 조건 불일치")
    grouped: dict[tuple, dict] = {}
    by_repeat: dict[int, list] = {}
    for row in trials:
        config = configs[row["condition_id"]]
        key = (config["model"], row["condition"], row["query_id"], config["candidate_k"], row["repeat_index"])
        ordered = verified[key]
        score = scores[key]
        value_by_id = {item["chunk_id"]: item for item in score["scores"]}
        chosen = [h for h in ordered[:config["top_k"]] if config["min_score"] is None
                  or value_by_id[h.chunk_id]["selection_score"] >= config["min_score"]]
        metrics = summarize(chosen, verifier.questions[row["query_id"]])
        if row["selected_chunk_ids"] != [h.chunk_id for h in chosen] or row["metrics"] != metrics:
            raise ValueError("선택/지표 원시 기록 불일치")
        if row["scores_digest"] != digest(score) or row["score_result_digest"] != score_result_digest(score):
            raise ValueError("조건·채점 연결 불일치")
        bundle = RetrievalBundle(searches[key[1:]]["search_query"],
                                 searches[key[1:]]["source_type"].upper(),
                                 search_hits_to_evidences(chosen), protocol["snapshot_fingerprint"])
        if row["bundle_digest"] != digest(asdict(bundle)):
            raise ValueError("실제 전달 bundle 불일치")
        grouped.setdefault((row["condition_id"], row["repeat_index"], row["condition"]), {})[row["query_id"]] = metrics
        by_repeat.setdefault(row["repeat_index"], []).append(row)
    repetitions = (1,) if phase == "grid" else (1, 2, 3)
    expected = {(cid, repetition, condition) for cid in configs for repetition in repetitions for condition in ("A", "B")}
    if set(grouped) != expected or any(set(rows) != set(verifier.questions) for rows in grouped.values()):
        raise ValueError("조건×양경로×질문×반복 전수 조합 누락")
    summaries = []
    for cid, config in configs.items():
        a, b = grouped[cid, 1, "A"], grouped[cid, 1, "B"]
        am, bm = (compute_metrics_for_records(rows, verifier.questions) for rows in (a, b))
        ar, br = regressions(a, baseline["A"]), regressions(b, baseline["B"])
        summaries.append({**config, "on_metrics": bm, "off_metrics": am, "on_regressions": br, "off_regressions": ar,
                          "focus_ranks": {qid: b[qid]["first_gold_rank"] for qid in FOCUS_12_QIDS},
                          "G2": not compare_quality(am, baseline_metrics["A"]) and not compare_quality(bm, baseline_metrics["B"]),
                          "G3": not ar and not br and am["negative_counter_retrieved_count"] == bm["negative_counter_retrieved_count"] == 5})
    if phase == "grid":
        routes = verify_routes(read_rows(run_dir / "routes.jsonl"), verifier)
        if routes["passed"] != 40:
            raise ValueError("실제 그래프 경로 실패")
        saved = json.loads((run_dir / "selected_condition.json").read_bytes())
        selected = select_condition(summaries)
        if saved["selected_condition"] != (selected["condition_id"] if selected else None):
            raise ValueError("선정 결과 불일치")
        if digest(saved["configuration"]) != digest(selected):
            raise ValueError("선정 설정 내용 불일치")
        # 모든 후보의 기본 비교와 단계적 축소·40개 확대 발동을 재검증한다.
        models = {c["model"] for c in configs.values()}
        if models != {"R1", "R2", "R3"}:
            raise ValueError("리랭커 비교 누락")
        pool20 = [row for row in summaries if row["candidate_k"] == 20]
        pools = {c["candidate_k"] for c in configs.values()}
        expected_configs = {(model, pool, k, threshold) for model in models for pool in pools
                            for k in protocol["grid"]["top_k"] for threshold in protocol["grid"]["min_score"]}
        if {(c["model"], c["candidate_k"], c["top_k"], c["min_score"]) for c in configs.values()} != expected_configs:
            raise ValueError("사전 등록한 격자 조합 누락")
        focus = next(row["focus_ranks"] for row in pool20 if row["model"] == "R1" and row["top_k"] == 5 and row["min_score"] is None)
        if should_expand_candidates(pool20, focus) and {c["candidate_k"] for c in configs.values()} != {20, 40}:
            raise ValueError("필수 후보40 확대 미실행")
        if digest(summaries) != digest(read_rows(run_dir / "grid_records.jsonl")):
            raise ValueError("격자 요약 불일치")
        return {"overall_verdict": "PENDING" if selected else "FAIL", "exit_code": 2 if selected else 1,
                "selected_condition": saved["selected_condition"], "adoption_status": "B0_MAINTAINED",
                "conditions": len(configs), "record_count": len(trials), "summary_verified": True}
    routes = verify_routes(read_rows(run_dir / "routes.jsonl"), verifier)
    repeats = read_rows(run_dir / "repeat_records.jsonl")
    for row in repeats:
        raw = by_repeat[row["repeat_index"]]
        if row["record_count"] != len(raw) or row["result_digest"] != result_digest(raw):
            raise ValueError("반복 원시 결과 요약 불일치")
    result = evaluate_gates(g0_reproduced=True, router_results=routes,
                            b_metrics=summaries[0]["on_metrics"], b0_metrics=baseline_metrics["B"],
                            b_regressions=summaries[0]["on_regressions"],
                            a_metrics=summaries[0]["off_metrics"], a0_metrics=baseline_metrics["A"],
                            a_regressions=summaries[0]["off_regressions"],
                            repeat_summaries=repeats, coverage_complete=True)
    result.update(record_count=len(trials), repeated=repeat_verdict(repeats))
    return result


def audit_answers(run_dir: Path, protocol: dict, manifest: dict,
                  verifier: RecordVerifier, manual_path: Optional[Path]) -> dict:
    from scripts.t15_answer_validation import audit_answers as validate_answers
    return validate_answers(run_dir, protocol, manifest, verifier, manual_path)
