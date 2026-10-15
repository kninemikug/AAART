"""Offline evidence checks for Task 17. Never generates or writes run files."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from typing import Any

from .answer import (
    SYSTEM_INSTRUCTION, _extract_json_text, _validate_llm_json_obj,
    build_prompt_and_citations, normalize_query, validate_and_format_citations,
    validate_codex_execution,
)
from .graph.answer import validate_and_project_bundle, serialize_confirmed_context
from .graph.state import Evidence, RetrievalBundle
from .graph.search import search_hits_to_evidences
from .retrieval.provenance import canonical_json_str, sha256_bytes, sha256_str
from .retrieval.types import SearchHit

SLICE_IDS = (
    "Q001", "Q004", "Q014", "Q021", "Q033", "Q044", "Q054", "Q063",
    "Q072", "Q080", "Q084", "Q086", "Q092", "Q093", "Q096",
)
BASELINE_HASHES = {
    "docs/search_eval_queries.json": "91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8",
    "docs/T11_execution_records.jsonl": "5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7",
    "data/eval/t14-conn/conn_20261015_pr/slice1_search.jsonl": "7362973a835ca69e3375e2980e6c79d83cccab31a221a750ee2b23724c520a4d",
    "data/eval/t14-conn/conn_20261015_pr/ab_records.jsonl": "96f11d6d63f41896c1b8cf028f52b0932d121d3d5ad4093c69a33802ea0dfd0e",
}
CODE_PATHS = (
    "src/artagent/answer.py", "src/artagent/graph/answer.py",
    "scripts/check_t17_answer.py",
)


def capture_code_state(root: Path) -> dict[str, Any]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
    ).strip()
    return {"code_commit": commit, "code_files": {
        path: sha256_bytes((root / path).read_bytes()) for path in CODE_PATHS
    }}


def record_digest(record: dict[str, Any]) -> str:
    """The existing review-file digest convention, shared by writer and reader."""
    return sha256_str(json.dumps(record, ensure_ascii=False, sort_keys=True))


def reference_cases(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Read the fixed inputs, checking their hashes before trusting any labels."""
    loaded = {}
    for relative, expected_sha in BASELINE_HASHES.items():
        data = (root / relative).read_bytes()
        if sha256_bytes(data) != expected_sha:
            raise ValueError(f"기준선 SHA 불일치: {relative}")
        loaded[relative] = data.decode("utf-8")
    queries = {q["query_id"]: q["query"] for q in json.loads(loaded["docs/search_eval_queries.json"])["queries"]}
    cases = {}
    for path, content in loaded.items():
        if not path.endswith("jsonl"):
            continue
        for row in map(json.loads, content.splitlines()):
            qid = row["query_id"]
            if path == "docs/T11_execution_records.jsonl":
                hits = [SearchHit(**h) for h in row["retrieval"]["hits"]]
                types = {h.source_type for h in hits}
                source_filter = next(iter(types)).upper() if len(types) == 1 else "ALL"
                bundle = asdict(RetrievalBundle(
                    row["input"]["query_normalized"], source_filter,
                    search_hits_to_evidences(hits), "t11_baseline_20261014",
                ))
                track, parent = "t11_replay", row["run_id"]
            else:
                condition = row["condition"]
                if path.endswith("ab_records.jsonl"):
                    if qid not in ("Q010", "Q077") or condition != "B":
                        continue
                    track = f"t14_b_reg_{qid}"
                else:
                    track = f"t14_{condition.lower()}"
                bundle = row["retrieval"]
                parent = row["decision"]["plan"][0]["step_id"]
            cases[qid, track] = {
                "query": queries[qid], "retrieval": bundle, "parent": parent,
                "input_reference": {"path": path, "sha256": BASELINE_HASHES[path]},
            }
    return cases


def _check_record(record, case, source_root, failures, pending):
    label = f"{record.get('query_id')} ({record.get('track')})"

    def fail(message):
        failures.append(f"{message}: {label}")

    def missing(message):
        pending.append(f"{message}: {label}")

    output = record.get("output", {})
    gen = record.get("generation", {})
    if record.get("record_schema") not in ("t17-run-v1", "t17-run-v2", "t17-run-v3"):
        fail("유효하지 않은 실행 기록 스키마")
    if output.get("status") not in ("SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE"):
        fail("유효하지 않은 답변 상태")
    if output.get("status") in ("SUPPORTED", "UNSUPPORTED") and not record.get("citations"):
        fail("근거 답변 인용 누락")
    if output.get("error") is not None or record.get("error") is not None:
        fail("실행 기술 오류")
    if type(gen.get("call_count")) is not int or gen["call_count"] != 1:
        fail("생성 호출 수 초과/누락: 정상 답변은 정확히 1회")
    if gen.get("is_mock") or gen.get("provider") in ("mock", "custom"):
        missing("모의(mock) 결과는 게이트 B 증거가 아님")
    if not gen.get("provider") or not gen.get("model"):
        missing("실제 제공처/모델 누락")
    runtime_meta = gen.get("runtime_meta") or {}
    if runtime_meta.get("is_mock"):
        missing("실행 메타데이터에 모의(mock) 생성 표시")
    if gen.get("provider") and runtime_meta.get("llm_provider") != gen["provider"]:
        fail("제공처 메타데이터 불일치")
    if gen.get("model") and runtime_meta.get("model_id") != gen["model"]:
        fail("모델 메타데이터 불일치")

    if case:
        inp = record.get("input", {})
        if inp.get("query_original") != case["query"] or inp.get("query_normalized") != normalize_query(case["query"]):
            fail("고정 질문 입력 불일치")
        if not record.get("original_run_id"):
            missing("원본 실행 ID 누락")
        elif record["original_run_id"] != case["parent"]:
            fail("원본 실행 ID 불일치")
        for field in ("query", "source_filter", "snapshot_ref", "hits"):
            if record.get("retrieval", {}).get(field) != case["retrieval"][field]:
                fail(f"기준 검색 bundle 불일치 ({field})")
        inp = record.get("input", {})
        if inp.get("confirmed_context") is not None or inp.get("constraints", []) not in (None, []):
            fail("고정 재생 입력의 확정 문맥/제약 불일치")
        ref = record.get("input_reference")
        if ref is None:
            missing("입력 파일 지문 누락")
        elif ref != case["input_reference"]:
            fail("입력 파일 지문 불일치")

    segs = None
    try:
        ret = record["retrieval"]
        segs = validate_and_project_bundle(RetrievalBundle(
            ret["query"], ret["source_filter"], [Evidence(**h) for h in ret["hits"]],
            ret["snapshot_ref"],
        ), source_root=source_root)
    except Exception as exc:
        fail(f"원문/좌표 독립 검증 실패 ({exc})")
    ret = record.get("retrieval", {})
    if "hits_count" in ret and ret["hits_count"] != len(ret.get("hits", [])):
        fail("검색 근거 개수 요약 불일치")
    if "product_scopes" in ret and ret["product_scopes"] != sorted({h["product_scope"] for h in ret.get("hits", [])}):
        fail("검색 제품 범위 요약 불일치")

    prompt = record.get("prompt", {})
    if not prompt.get("version"):
        missing("필수 프롬프트 버전 누락")
    system, user, digest = (prompt.get(k) for k in ("system_instruction", "user_prompt", "prompt_hash"))
    if not system or not user or not digest:
        missing("실제 프롬프트/해시 누락")
    elif sha256_str(f"{system}\n{user}") != digest:
        fail("프롬프트 해시 불일치")
    if segs is not None and user and system and case:
        inp = record.get("input", {})
        expected_prompt, _, _ = build_prompt_and_citations(
            normalize_query(case["query"]), segments=segs,
            prompt_version=prompt.get("version", "t17-answer-v1"),
            response_schema="t17-answer-v1",
            confirmed_context=serialize_confirmed_context(inp.get("confirmed_context"), inp.get("constraints")),
        )
        if system != SYSTEM_INSTRUCTION or user != expected_prompt:
            fail("실제 프롬프트와 입력/문맥 불일치")

    parsed = None
    raw = gen.get("raw_response")
    if raw is None:
        missing("원생성 응답(raw_response) 누락")
    else:
        try:
            parsed = json.loads(_extract_json_text(raw))
            _validate_llm_json_obj(parsed, schema="t17-answer-v1")
            if parsed["status"] != output.get("status"):
                fail("원생성 응답의 status와 출력 불일치")
            if "status" in gen and gen["status"] != parsed["status"]:
                fail("생성 상태 요약 불일치")
            if parsed["status"] in ("SUPPORTED", "UNSUPPORTED") and not parsed["citation_ids"]:
                fail("근거 답변 인용 누락")
            if segs is not None:
                answer = parsed["answer"]
                if parsed["status"] == "INSUFFICIENT_EVIDENCE" and not any(p in answer for p in (
                    "모르겠습니다", "확인할 수 없습니다", "근거로는 확인할 수", "정보가 없습니다", "근거가 부족", "제공된 검색",
                )):
                    answer = f"{answer.strip()} (모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.)"
                formatted, _, used = validate_and_format_citations(answer, parsed["citation_ids"], {s["cid"]: s for s in segs})
                expected_citations = [{"doc_id": s["doc_id"], "title": s["display_name"], "url": s["target_url"], "source_location": s["source_location"]} for s in used]
                if output.get("text") != formatted:
                    fail("원응답에서 재구성한 최종 답변 불일치")
                if record.get("citations") != expected_citations:
                    fail("인용-근거 매핑 불일치")
                if record.get("used_citations_provenance") != used:
                    fail("사용 인용 provenance 불일치")
                scopes = {s["product_scope"] for s in used or segs}
                ret = record["retrieval"]
                app = f"제품 범위: {', '.join(sorted(scopes)) if scopes else 'None'}; 스냅샷: {ret['snapshot_ref'] or 'default'}"
                if output.get("applicability") != app or output.get("actionable_goal") is not None:
                    fail("적용 범위/실행 목표 불일치")
        except Exception as exc:
            fail(f"원응답/인용 검증 실패 ({exc})")

    trace = gen.get("trace")
    runtime = gen.get("runtime_meta") or {}
    nested_trace = runtime.get("_trace")
    if trace is not None and nested_trace is not None and trace != nested_trace:
        fail("실행 trace 사본 불일치")
    trace = trace if trace is not None else nested_trace
    if gen.get("provider") == "codex-cli":
        if not trace:
            missing("실제 실행 trace 누락")
        else:
            try:
                if trace.get("process_returncode") is None:
                    missing("프로세스 정상 종료 코드 미확인")
                elif type(trace["process_returncode"]) is not int:
                    fail("프로세스 종료 코드 타입 오류")
                if trace["execution_policy"]["model_id"] != gen.get("model"):
                    fail("실행 모델과 trace 정책 불일치")
                file_content = runtime.get("_output_file_content", raw)
                if file_content is None:
                    # Audit the events independently; this is not a recovered output file.
                    messages = [event["item"]["text"] for event in map(json.loads, trace["stdout_jsonl"].splitlines())
                                if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
                    file_content = messages[-1] if messages else None
                actual, _, _ = validate_codex_execution(
                    stdout_raw=trace["stdout_jsonl"], stderr_raw=trace.get("stderr", ""),
                    process_returncode=trace["process_returncode"],
                    out_file_content=file_content,
                    execution_policy=trace["execution_policy"], cli_version=trace["cli_version"],
                    process_error=trace.get("process_error"), schema="t17-answer-v1",
                )
                if parsed is not None and actual != parsed:
                    fail("실행 이벤트와 원응답 불일치")
            except Exception as exc:
                fail(f"실행 trace 재검증 실패 ({exc})")

    request = gen.get("request")
    if not request:
        missing("실제 최종 요청 전문 누락")
    else:
        try:
            if request["response_schema"] != "t17-answer-v1":
                fail("응답 스키마 불일치")
            if request.get("model") != gen.get("model") or request.get("prompt_version") != prompt.get("version"):
                fail("실제 요청 모델/프롬프트 버전 불일치")
            if request["kind"] == "codex":
                if gen.get("provider") != "codex-cli":
                    fail("요청 종류와 제공처 불일치")
                full = f"{system}\n\n{user}\n\n반드시 마크다운 코드블록(```json 등) 없이 순수 JSON 객체(키: status, answer, citation_ids) 하나만 출력하십시오."
                if request["full_prompt"] != full or request["sha256"] != sha256_str(full):
                    fail("실제 최종 요청 전문/해시 불일치")
                if runtime.get("_output_file_content") is None:
                    missing("실제 출력 파일 내용 누락")
            elif request["kind"] == "chat-completions":
                if gen.get("provider") != "openai-compatible":
                    fail("요청 종류와 제공처 불일치")
                payload = request["payload"]
                if payload.get("model") != gen.get("model"):
                    fail("실제 payload 모델 불일치")
                if payload["messages"] != [{"role": "system", "content": system}, {"role": "user", "content": user}] or request["sha256"] != sha256_str(canonical_json_str(payload)):
                    fail("실제 요청 payload 불일치")
                if runtime.get("_response_body") is None:
                    missing("실제 제공처 응답 누락")
                else:
                    api_parsed = json.loads(_extract_json_text(runtime["_response_body"]["choices"][0]["message"]["content"]))
                    _validate_llm_json_obj(api_parsed, schema="t17-answer-v1")
                    if parsed is not None and api_parsed != parsed:
                        fail("제공처 응답과 파싱 결과 불일치")
            else:
                missing("검증할 수 없는 생성 요청 종류")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            fail(f"실제 요청 구조 오류 ({exc})")


def _check_code_state(record, repo_root, checked, failures, pending):
    state = record.get("runtime", {})
    commit, files = state.get("code_commit"), state.get("code_files")
    if not commit or not files:
        pending.append(f"실행 코드 커밋/파일 지문 누락: {record.get('run_id')}")
        return
    key = commit, canonical_json_str(files)
    if key in checked:
        return
    checked.add(key)
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        failures.append("유효하지 않은 실행 코드 커밋")
        return
    for path in CODE_PATHS:
        try:
            content = subprocess.check_output(
                ["git", "show", f"{commit}:{path}"], cwd=repo_root, stderr=subprocess.DEVNULL,
            )
            if files.get(path) != sha256_bytes(content):
                failures.append(f"실행 코드 지문이 커밋과 불일치: {path}")
        except subprocess.CalledProcessError:
            failures.append(f"실행 코드 커밋을 확인할 수 없음: {commit}")


def evaluate_records(records, regressions, reviews, source_root, repo_root, review_targets):
    """Validate every record with the same checks; missing proof never becomes PASS."""
    failures, pending = [], []
    try:
        cases = reference_cases(repo_root)
    except Exception as exc:
        return "FAIL", [f"고정 입력 검증 실패: {exc}"], []
    expected = {(q, t) for q in SLICE_IDS for t in ("t11_replay", "t14_a", "t14_b")}
    reg_expected = {(q, f"t14_b_reg_{q}") for q in ("Q010", "Q077")}
    found, run_ids, by_key, checked_code = set(), set(), {}, set()
    for group, allowed in ((records, expected), (regressions, reg_expected)):
        for record in group:
            try:
                key = record.get("query_id"), record.get("track")
                if key not in allowed:
                    failures.append(f"허용되지 않은 질문/track: {key}")
                if key in found:
                    failures.append(f"중복 실행 기록: {key}")
                found.add(key)
                run_id = record.get("run_id")
                if not isinstance(run_id, str) or not run_id or run_id in run_ids:
                    failures.append(f"누락/중복 run ID: {key}")
                run_ids.add(run_id)
                by_key[key] = record
                _check_record(record, cases.get(key), source_root, failures, pending)
                _check_code_state(record, repo_root, checked_code, failures, pending)
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                failures.append(f"실행 기록 구조 오류: {exc}")
    for key in sorted((expected | reg_expected) - found):
        pending.append(f"필수 실행 기록 누락: {key}")

    for key in review_targets:
        record = by_key.get(key)
        matches = [v for v in reviews.values() if (v.get("query_id"), v.get("track")) == key]
        if not matches:
            pending.append(f"필수 수동 검토 누락: {key}")
            continue
        if len(matches) != 1:
            failures.append(f"중복 수동 검토: {key}")
            continue
        review = matches[0]
        if record:
            if review.get("run_id") != record.get("run_id") or review.get("record_hash") != record_digest(record):
                failures.append(f"수동 검토 실행/레코드 해시 불일치: {key}")
        status = review.get("status")
        if status == "failed":
            failures.append(f"수동 검토 불합격: {key}")
        elif status in (None, "pending"):
            pending.append(f"수동 검토 미결: {key}")
        elif status != "verified":
            failures.append(f"잘못된 수동 검토 상태: {key}")
        elif not review.get("reviewed_claims") or not review.get("reason"):
            pending.append(f"수동 검토 주장/사유 누락: {key}")
    return ("FAIL" if failures else "PENDING" if pending else "PASS"), failures, pending
