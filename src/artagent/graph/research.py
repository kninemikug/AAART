"""근거 부족에 한정한 요청당 1회 추가 검색 입력 준비."""

from dataclasses import asdict
from typing import Any, Callable, Optional

from ..retrieval.provenance import canonical_json_str, sha256_str
from .rewrite import prepare_search_input
from .state import AgentState, ErrorInfo, Path, ResearchInput


def research_identity(state: AgentState) -> tuple[str, str, tuple[str, ...]]:
    """원질문·확정 문맥·항목을 묶어 준비 입력의 재사용 범위를 고정한다."""
    # 검색의 기존 문맥 추출 규칙을 공유하며 모듈 초기화 순환을 피한다.
    from .search import _extract_query_and_constraints

    request = state.get("request")
    decision = state.get("decision")
    cursor = state.get("cursor", 0)
    if (not request or not decision or type(cursor) is not int
            or not 0 <= cursor < len(decision.plan)):
        raise ValueError("유효한 요청과 현재 검색 항목이 필요합니다.")
    step = decision.plan[cursor]
    if step.path not in (Path.DOC_QA, Path.TROUBLESHOOT):
        raise ValueError("검색 항목만 재검색할 수 있습니다.")
    query, constraints = _extract_query_and_constraints(state, preserve_literals=True)
    if not query.strip():
        raise ValueError("원질문이 비어 있습니다.")
    signature = sha256_str(canonical_json_str({
        "request": asdict(request), "step": asdict(step), "constraints": constraints,
    }))
    return signature, query, constraints


def validate_research_input(state: AgentState) -> ResearchInput:
    """다른 요청·항목·문맥의 준비 입력과 손상된 재개 상태를 거부한다."""
    prepared = state.get("research_input")
    if not isinstance(prepared, ResearchInput):
        raise ValueError("재검색 준비 기록이 없습니다.")
    signature, _, _ = research_identity(state)
    step = state["decision"].plan[state.get("cursor", 0)]
    source_type = "rawpedia" if step.path == Path.DOC_QA else "github"
    if (type(state.get("research_count")) is not int or state["research_count"] != 1
            or prepared.request_id != state["request"].request_id
            or prepared.step_id != step.step_id or prepared.signature != signature
            or prepared.source_type != source_type
            or prepared.phase not in ("PREPARED", "SEARCHED")):
        raise ValueError("재검색 준비 기록의 요청·항목·예산이 일치하지 않습니다.")
    return prepared


def create_research_node(
    generate: Optional[Callable[[str], str]] = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """검색·답변을 호출하지 않고 T14 입력 준비와 예산 소진만 수행한다."""
    def research(state: AgentState) -> dict[str, Any]:
        trace = [*state.get("trace", []), "RESEARCH"]
        if state.get("error"):
            return {"error": state["error"], "trace": trace}
        try:
            if state.get("research_input") is not None:
                validate_research_input(state)
                return {"trace": trace}
            count = state.get("research_count", 0)
            answer = state.get("answer")
            if (type(count) is not int or count != 0 or not answer
                    or answer.status != "INSUFFICIENT_EVIDENCE"):
                raise ValueError("근거 부족이며 추가 시도 예산이 0이어야 합니다.")
            signature, query, constraints = research_identity(state)
            step = state["decision"].plan[state.get("cursor", 0)]
            settings = state.get("search_settings")
            bundle = state.get("retrieval")
            if not isinstance(settings, dict) or bundle is None:
                raise ValueError("최초 검색의 설정과 bundle이 필요합니다.")
        except (ValueError, TypeError, AttributeError) as exc:
            return {"error": ErrorInfo("CONTRACT_VIOLATION", str(exc), "RESEARCH"),
                    "trace": trace}
        search_input = prepare_search_input(
            query, generate=generate, rewrite_enabled=True, hyde_enabled=False,
            constraints=constraints,
        )
        prepared = ResearchInput(
            state["request"].request_id, step.step_id,
            "rawpedia" if step.path == Path.DOC_QA else "github",
            signature, search_input, dict(settings),
        )
        error = None
        if search_input.status == "error":
            error = ErrorInfo("REWRITE_FAILED", search_input.error_message or "재작성 실패", "RESEARCH")
        return {"research_count": 1, "research_request_id": prepared.request_id,
                "research_input": prepared, "retrieval": None, "answer": None,
                "error": error, "trace": trace}

    return research
