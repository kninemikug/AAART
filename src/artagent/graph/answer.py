"""Answer node and standalone grounded answering for LangGraph router (Task 17 / A-17).

Provides grounded answer generation with immutable citation mapping, evidence verification,
three semantic states (SUPPORTED, UNSUPPORTED, INSUFFICIENT_EVIDENCE), and strict error handling.
Conforms strictly to docs/T17_execution_plan.md.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Optional, Sequence, Tuple

from ..answer import (
    SYSTEM_INSTRUCTION,
    build_prompt_and_citations,
    generate_llm_response,
    get_source_root,
    normalize_query,
    validate_and_format_citations,
)
from ..retrieval.provenance import canonical_json_str, sha256_bytes, sha256_str
from .state import (
    AgentState,
    AnswerResult,
    Citation,
    ErrorInfo,
    Evidence,
    RequestContext,
    RetrievalBundle,
)

T17_PROMPT_VERSION = "t17-answer-v1"
VALID_STATUSES = {"SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE"}
MAX_CONTEXT_CHARS = 500_000


def validate_and_project_bundle(
    bundle: Optional[RetrievalBundle],
    source_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """RetrievalBundle 입력 및 원문 대조를 검증하고 세그먼트 레코드 목록으로 투영.

    불일치나 검증 실패 시 ValueError를 발생시킨다.
    """
    if bundle is None:
        raise ValueError("RetrievalBundle이 None입니다.")

    if not isinstance(bundle.query, str):
        raise ValueError(f"bundle.query가 문자열이 아닙니다: {type(bundle.query).__name__}")
    if not isinstance(bundle.source_filter, str):
        raise ValueError(f"bundle.source_filter가 문자열이 아닙니다: {type(bundle.source_filter).__name__}")
    if bundle.source_filter not in ("RAWPEDIA", "GITHUB", "ALL"):
        raise ValueError(f"지원하지 않는 source_filter입니다: '{bundle.source_filter}'")
    if not isinstance(bundle.snapshot_ref, str):
        raise ValueError(f"bundle.snapshot_ref가 문자열이 아닙니다: {type(bundle.snapshot_ref).__name__}")
    if not isinstance(bundle.hits, list):
        raise ValueError(f"bundle.hits가 리스트가 아닙니다: {type(bundle.hits).__name__}")

    # 정상 빈 검색 허용
    if not bundle.hits:
        return []

    sr = source_root.resolve() if source_root else get_source_root()

    seen_chunks: dict[str, int] = {}
    chunk_segment_counts: dict[str, int] = {}
    segments: list[dict[str, Any]] = []

    expected_source_type = bundle.source_filter.lower()

    for idx, ev in enumerate(bundle.hits):
        # 1. 필수 필드 및 타입 검사
        for field_name in (
            "chunk_id",
            "doc_id",
            "source_group_id",
            "source_type",
            "source_path",
            "source_location",
            "target_url",
            "text",
            "product_scope",
        ):
            val = getattr(ev, field_name, None)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"Evidence[{idx}]의 필수 필드 '{field_name}'이 누락되었거나 유효하지 않습니다.")

        if expected_source_type != "all" and ev.source_type != expected_source_type:
            raise ValueError(
                f"Evidence[{idx}]의 source_type('{ev.source_type}')이 bundle의 source_filter('{bundle.source_filter}')와 일치하지 않습니다."
            )
        if expected_source_type == "all" and ev.source_type not in ("rawpedia", "github"):
            raise ValueError(f"Evidence[{idx}]의 지원되지 않는 source_type: '{ev.source_type}'")

        # 2. 제품 범위 보존 검증 (RawPedia는 RawTherapee, GitHub는 ART)
        if ev.source_type == "rawpedia":
            if ev.product_scope not in ("RawTherapee", "rawtherapee_reference"):
                raise ValueError(
                    f"Evidence[{idx}] RawPedia 근거의 product_scope는 'RawTherapee'여야 합니다 (현재: '{ev.product_scope}')."
                )
        elif ev.source_type == "github":
            if ev.product_scope != "ART":
                raise ValueError(
                    f"Evidence[{idx}] GitHub 근거의 product_scope는 'ART'여야 합니다 (현재: '{ev.product_scope}')."
                )

        # 3. source_location JSON 파싱 및 무결성 검증
        try:
            loc = json.loads(ev.source_location)
        except Exception as e:
            raise ValueError(f"Evidence[{idx}]의 source_location JSON 파싱 실패: {e}") from e

        if not isinstance(loc, dict):
            raise ValueError(f"Evidence[{idx}]의 source_location이 JSON 객체가 아닙니다.")

        section_title = loc.get("section_title")
        if not isinstance(section_title, str):
            raise ValueError(f"Evidence[{idx}]의 section_title이 문자열이 아닙니다.")

        source_segment = loc.get("source_segment")
        if not isinstance(source_segment, dict):
            raise ValueError(f"Evidence[{idx}]의 source_segment가 객체가 아닙니다.")

        # source_segment 내부 필드 대조
        for key in ("doc_id", "source_path", "target_url"):
            if source_segment.get(key) != getattr(ev, key):
                raise ValueError(
                    f"Evidence[{idx}]의 {key}('{getattr(ev, key)}')가 source_segment의 값('{source_segment.get(key)}')과 일치하지 않습니다."
                )
        if not source_segment.get("source_file_sha256"):
            raise ValueError(f"Evidence[{idx}]의 source_segment에 source_file_sha256이 누락되었습니다.")
        if not source_segment.get("segment_sha256"):
            raise ValueError(f"Evidence[{idx}]의 source_segment에 segment_sha256이 누락되었습니다.")

        char_start = source_segment.get("char_start")
        char_end = source_segment.get("char_end")
        byte_start = source_segment.get("byte_start")
        byte_end = source_segment.get("byte_end")

        if (
            type(char_start) is not int
            or type(char_end) is not int
            or type(byte_start) is not int
            or type(byte_end) is not int
            or not (0 <= char_start <= char_end)
            or not (0 <= byte_start <= byte_end)
        ):
            raise ValueError(f"Evidence[{idx}]의 세그먼트 좌표 범위가 유효하지 않습니다.")

        # 4. 원문 파일 대조 (파일 SHA, JSON pointer, 문자/바이트 범위, 본문 해시)
        rel_path = ev.source_path
        target_file = sr / rel_path
        if not target_file.is_file():
            # fallback to local repo if different from source_root
            repo_file = Path(".").resolve() / rel_path
            if repo_file.is_file():
                target_file = repo_file
            else:
                raise FileNotFoundError(f"원문 파일을 찾을 수 없습니다: {target_file}")

        file_bytes = target_file.read_bytes()
        actual_file_sha = sha256_bytes(file_bytes)
        if actual_file_sha != source_segment["source_file_sha256"]:
            raise ValueError(
                f"원문 파일 SHA-256 불일치: {target_file} (기대: {source_segment['source_file_sha256']}, 실제: {actual_file_sha})"
            )

        json_pointer = source_segment.get("json_pointer")
        if json_pointer is None:
            # Markdown 파일
            full_text = file_bytes.decode("utf-8")
            if char_end > len(full_text):
                raise ValueError(f"char_end({char_end})가 원문 텍스트 길이({len(full_text)})를 초과합니다.")
            extracted_text = full_text[char_start:char_end]

            if byte_end > len(file_bytes):
                raise ValueError(f"byte_end({byte_end})가 파일 바이트 크기({len(file_bytes)})를 초과합니다.")
            byte_extracted = file_bytes[byte_start:byte_end].decode("utf-8")
            if extracted_text != byte_extracted:
                raise ValueError("문자 범위 추출 결과와 UTF-8 바이트 범위 추출 결과가 일치하지 않습니다.")

        elif json_pointer == "/body":
            # GitHub JSON 스냅샷
            try:
                json_data = json.loads(file_bytes.decode("utf-8"))
            except Exception as e:
                raise ValueError(f"JSON 원문 파일 파싱 실패: {target_file}: {e}") from e

            body = json_data.get("body")
            if not isinstance(body, str):
                raise ValueError(f"JSON 원문의 '/body' 포인터 필드가 문자열이 아닙니다: {target_file}")

            body_sha = source_segment.get("body_sha256")
            if body_sha and sha256_str(body) != body_sha:
                raise ValueError(f"JSON 본문 body_sha256 불일치: {target_file}")

            body_bytes = body.encode("utf-8")
            if char_end > len(body):
                raise ValueError(f"char_end({char_end})가 body 길이({len(body)})를 초과합니다.")
            extracted_text = body[char_start:char_end]

            if byte_end > len(body_bytes):
                raise ValueError(f"byte_end({byte_end})가 body 바이트 크기({len(body_bytes)})를 초과합니다.")
            byte_extracted = body_bytes[byte_start:byte_end].decode("utf-8")
            if extracted_text != byte_extracted:
                raise ValueError("JSON 본문 문자 범위 추출 결과와 UTF-8 바이트 범위 추출 결과가 일치하지 않습니다.")
        else:
            raise ValueError(f"지원하지 않는 json_pointer입니다: '{json_pointer}'")

        if extracted_text != ev.text:
            raise ValueError(
                f"Evidence[{idx}]의 text가 원문 추출 결과와 일치하지 않습니다 ({target_file})."
            )

        if sha256_str(ev.text) != source_segment["segment_sha256"]:
            raise ValueError(f"Evidence[{idx}]의 segment_sha256 해시가 본문과 일치하지 않습니다.")

        # 5. 인용 ID 부여 ([C{chunk}S{segment}])
        chunk_id = ev.chunk_id
        if chunk_id not in seen_chunks:
            chunk_order = len(seen_chunks) + 1
            seen_chunks[chunk_id] = chunk_order
            chunk_segment_counts[chunk_id] = 0
        else:
            chunk_order = seen_chunks[chunk_id]

        chunk_segment_counts[chunk_id] += 1
        segment_order = chunk_segment_counts[chunk_id]
        cid = f"C{chunk_order}S{segment_order}"

        # 표시명 생성
        if ev.source_type == "rawpedia":
            display_name = section_title or ev.doc_id or "RawPedia"
        else:
            ref_id = source_segment.get("ref_id")
            ident = ref_id if ref_id else ev.doc_id
            if ident and str(ident) not in str(section_title):
                display_name = f"{section_title} ({ident})"
            else:
                display_name = section_title or "GitHub"

        segments.append({
            "cid": cid,
            "chunk_id": ev.chunk_id,
            "doc_id": ev.doc_id,
            "ref_id": source_segment.get("ref_id"),
            "source_group_id": ev.source_group_id,
            "source_type": ev.source_type,
            "source_path": ev.source_path,
            "product_scope": ev.product_scope,
            "section_title": section_title,
            "target_url": ev.target_url,
            "text": ev.text,
            "text_sha256": sha256_str(ev.text),
            "source_location": ev.source_location,
            "source_segment": source_segment,
            "display_name": display_name,
            "chunk_order": chunk_order,
            "segment_order": segment_order,
        })

    return segments


def answer_standalone(
    query: str,
    bundle: Optional[RetrievalBundle],
    *,
    context: Optional[Any] = None,
    generate: Optional[Callable[..., Any]] = None,
    source_root: Optional[Path] = None,
    observe: Optional[Callable[[dict[str, Any]], None]] = None,
) -> Tuple[Optional[AnswerResult], Optional[ErrorInfo]]:
    """단독 답변 생성 및 인용 검증 실행.

    원질문, 확정 문맥, RetrievalBundle, 생성 콜백, source_root를 입력받아
    검색 0회 / 재작성 0회 / 생성 1회(오류 시 0회)로 검증된 AnswerResult 또는 ErrorInfo를 반환한다.
    """
    started = time.perf_counter()

    # 1. 원질문 정규화 (T11 기본 정규화만 수행, T14 재작성/HyDE 재실행 금지)
    try:
        query_normalized = normalize_query(query)
    except Exception as e:
        error = ErrorInfo(
            code="ANSWER_INPUT_INVALID",
            message=f"질문 입력 오류: {e}",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query,
                "error": error.__dict__,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 2. RetrievalBundle 및 원문 대조 검증
    try:
        segments = validate_and_project_bundle(bundle, source_root=source_root)
    except Exception as e:
        error = ErrorInfo(
            code="ANSWER_INPUT_INVALID",
            message=f"RetrievalBundle 또는 원문 대조 검증 실패: {e}",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query_normalized,
                "error": error.__dict__,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 3. 확정 문맥 직렬화
    confirmed_context_str: Optional[str] = None
    if isinstance(context, RequestContext):
        parts = []
        if context.os:
            parts.append(f"OS: {context.os}")
        if context.art_version:
            parts.append(f"ART Version: {context.art_version}")
        if context.confirmed_goal:
            parts.append(f"Confirmed Goal: {context.confirmed_goal}")
        confirmed_context_str = "\n".join(parts) if parts else None
    elif isinstance(context, (list, tuple)):
        confirmed_context_str = "\n".join(str(c) for c in context) if context else None
    elif isinstance(context, dict):
        confirmed_context_str = "\n".join(f"{k}: {v}" for k, v in context.items()) if context else None
    elif isinstance(context, str):
        confirmed_context_str = context.strip() or None

    # 4. 프롬프트 및 인용 매핑 구성 (전체 세그먼트 투영, 5개 절단 금지)
    user_prompt, context_citations, context_citation_ids = build_prompt_and_citations(
        query_normalized=query_normalized,
        segments=segments,
        prompt_version=T17_PROMPT_VERSION,
        confirmed_context=confirmed_context_str,
    )

    # 문맥 한도 초과 검사 (절단 없이 오류 반환)
    if len(user_prompt) > MAX_CONTEXT_CHARS:
        error = ErrorInfo(
            code="ANSWER_INPUT_INVALID",
            message=f"문맥 길이 한도 초과 (길이: {len(user_prompt)} > {MAX_CONTEXT_CHARS})",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query_normalized,
                "error": error.__dict__,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 5. LLM 생성 정확히 1회 호출
    raw_response = ""
    usage = None
    runtime_meta: dict[str, Any] = {}

    try:
        if generate is not None:
            # 주입된 콜백 호출
            import inspect
            sig = inspect.signature(generate)
            param_count = len(sig.parameters)
            if param_count == 1:
                call_res = generate(user_prompt)
            elif param_count == 4:
                call_res = generate(SYSTEM_INSTRUCTION, user_prompt, context_citations, query_normalized)
            else:
                call_res = generate(SYSTEM_INSTRUCTION, user_prompt, context_citations, query_normalized)

            if isinstance(call_res, tuple) and len(call_res) == 3:
                raw_response, usage, runtime_meta = call_res
            elif isinstance(call_res, tuple) and len(call_res) == 2:
                raw_response, usage = call_res
                runtime_meta = {"llm_provider": "custom"}
            else:
                raw_response = str(call_res)
                runtime_meta = {"llm_provider": "custom"}
        else:
            raw_response, usage, runtime_meta = generate_llm_response(
                system_instruction=SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                context_citations=context_citations,
                query_normalized=query_normalized,
                prompt_version=T17_PROMPT_VERSION,
            )
    except Exception as e:
        error = ErrorInfo(
            code="ANSWER_GENERATION_FAILED",
            message=f"LLM 생성 실패: {e}",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query_normalized,
                "error": error.__dict__,
                "user_prompt": user_prompt,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 6. JSON 응답 및 스키마 검증
    try:
        # 마크다운 코드블록 제거
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("응답이 JSON 객체가 아닙니다.")
        if "status" not in parsed:
            raise ValueError("응답에 'status' 필드가 없습니다.")
        if "answer" not in parsed:
            raise ValueError("응답에 'answer' 필드가 없습니다.")
        if "citation_ids" not in parsed:
            raise ValueError("응답에 'citation_ids' 필드가 없습니다.")

        status = parsed["status"]
        if not isinstance(status, str) or status not in VALID_STATUSES:
            raise ValueError(f"유효하지 않은 status 값입니다: '{status}'. (허용: {sorted(VALID_STATUSES)})")

        raw_answer = parsed["answer"]
        if not isinstance(raw_answer, str) or not raw_answer.strip():
            raise ValueError("answer 필드가 비어 있거나 문자열이 아닙니다.")

        citation_ids = parsed["citation_ids"]
        if not isinstance(citation_ids, list) or any(not isinstance(cid, str) for cid in citation_ids):
            raise ValueError("citation_ids 필드가 문자열 리스트가 아닙니다.")

    except Exception as e:
        error = ErrorInfo(
            code="ANSWER_GENERATION_FAILED",
            message=f"응답 JSON/스키마 검증 실패: {e}",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query_normalized,
                "raw_response": raw_response,
                "error": error.__dict__,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 7. 의미 상태와 인용 계약 검증
    if status in ("SUPPORTED", "UNSUPPORTED"):
        if not citation_ids:
            error = ErrorInfo(
                code="ANSWER_CITATION_INVALID",
                message=f"{status} 상태는 1개 이상의 인용이 필수입니다 (현재: 0개).",
                node="ANSWER",
                recoverable=False,
            )
            if observe:
                observe({
                    "query": query_normalized,
                    "status": status,
                    "error": error.__dict__,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                })
            return None, error

        if not segments:
            error = ErrorInfo(
                code="ANSWER_CITATION_INVALID",
                message=f"검색 근거가 없는 빈 문맥에서 {status}를 선언할 수 없습니다.",
                node="ANSWER",
                recoverable=False,
            )
            if observe:
                observe({
                    "query": query_normalized,
                    "status": status,
                    "error": error.__dict__,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                })
            return None, error

    if status == "INSUFFICIENT_EVIDENCE":
        # 안내 문구 취지 검증
        if not any(phrase in raw_answer for phrase in (
            "모르겠습니다",
            "확인할 수 없습니다",
            "근거로는 확인할 수",
            "정보가 없습니다",
            "근거가 부족",
            "제공된 검색",
        )):
            # 취지 안내 보완
            raw_answer = f"{raw_answer.strip()} (모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.)"

    # 8. 인용 표식 일치 및 치환 검증
    try:
        final_answer, stdout_text, used_citations = validate_and_format_citations(
            raw_answer=raw_answer,
            parsed_citation_ids=citation_ids,
            context_citations=context_citations,
        )
    except Exception as e:
        error = ErrorInfo(
            code="ANSWER_CITATION_INVALID",
            message=f"인용 표식/목록 검증 실패: {e}",
            node="ANSWER",
            recoverable=False,
        )
        if observe:
            observe({
                "query": query_normalized,
                "raw_answer": raw_answer,
                "citation_ids": citation_ids,
                "error": error.__dict__,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })
        return None, error

    # 9. Citation 객체 변환 및 적용 범위(applicability) 구성
    citations: list[Citation] = []
    scopes: set[str] = set()

    for uc in used_citations:
        citations.append(Citation(
            doc_id=uc["doc_id"],
            title=uc["display_name"],
            url=uc["target_url"],
            source_location=canonical_json_str({
                "section_title": uc["section_title"],
                "source_segment": uc["source_segment"],
            }),
        ))
        if uc.get("product_scope"):
            scopes.add(uc["product_scope"])

    if not scopes and segments:
        scopes = {s["product_scope"] for s in segments}

    snapshot = bundle.snapshot_ref if bundle and bundle.snapshot_ref else "default"
    scope_desc = ", ".join(sorted(scopes)) if scopes else "None"
    applicability = f"제품 범위: {scope_desc}; 스냅샷: {snapshot}"

    answer_result = AnswerResult(
        status=status,
        text=final_answer,
        citations=citations,
        applicability=applicability,
        actionable_goal=None,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000
    if observe:
        observe({
            "query": query_normalized,
            "status": status,
            "answer_result": {
                "status": answer_result.status,
                "text": answer_result.text,
                "citations": [c.__dict__ for c in answer_result.citations],
                "applicability": answer_result.applicability,
                "actionable_goal": answer_result.actionable_goal,
            },
            "used_citations_provenance": used_citations,
            "runtime_meta": runtime_meta,
            "usage": usage,
            "elapsed_ms": elapsed_ms,
            "error": None,
        })

    return answer_result, None


def create_answer_node(
    generate: Optional[Callable[..., Any]] = None,
    *,
    source_root: Optional[Path] = None,
    observe: Optional[Callable[[dict[str, Any]], None]] = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """LangGraph ANSWER 노드 팩토리.

    AgentState -> 부분 state 갱신({answer, error, trace}만 갱신).
    request, decision.plan, cursor, retrieval, research_count는 변경하지 않는다.
    선행 REWRITE_FAILED / SEARCH_UNAVAILABLE 등 이전 오류가 있으면 보존하고 생성을 호출하지 않는다.
    """
    def answer_node(state: AgentState) -> dict[str, Any]:
        trace = list(state.get("trace", []))
        trace.append("ANSWER")

        # 선행 오류가 이미 존재하면 보존하고 생성 호출 없음
        prior_error = state.get("error")
        if prior_error is not None:
            return {
                "answer": None,
                "error": prior_error,
                "trace": trace,
            }

        # 1. 쿼리 추출 (decision.plan[cursor].query 우선)
        step_query = ""
        decision = state.get("decision")
        cursor = state.get("cursor", 0)
        if decision and cursor < len(decision.plan):
            step_query = decision.plan[cursor].query

        if not step_query:
            request = state.get("request")
            if request and request.text:
                step_query = request.text

        # 2. 확정 문맥 추출
        req = state.get("request")
        ctx = req.context if req else None

        # 3. bundle 추출
        bundle = state.get("retrieval")

        ans, err = answer_standalone(
            query=step_query,
            bundle=bundle,
            context=ctx,
            generate=generate,
            source_root=source_root,
            observe=observe,
        )

        if err is not None:
            return {
                "answer": None,
                "error": err,
                "trace": trace,
            }

        return {
            "answer": ans,
            "error": None,
            "trace": trace,
        }

    return answer_node


# Alias for standalone call
answer_query = answer_standalone
