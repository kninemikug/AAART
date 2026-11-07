"""Serve one JSON request from ART's native chat panel over standard I/O."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any, Callable


UNSUPPORTED_MESSAGE = (
    "일반 프로필 적용·자동 보정은 아직 미지원입니다. "
    "사진 수치 조정을 허용한 편집기에서는 항목의 절대값을 지정할 수 있습니다. "
    "예: 채도를 20으로 설정해줘. 목록: 조정 가능한 항목 보여줘"
)
MAX_REQUEST_BYTES = 65536
# 네이티브 패널의 300초 제한 전에 응답 직렬화·프로세스 정리를 마친다.
GUI_GENERATION_BUDGET_SECONDS = 270


def create_gui_graph(
    reference: Path,
    persist_dir: Path,
    source_root: Path,
    *,
    search_nodes: dict | None = None,
    answer_node: Callable | None = None,
    research_generate: Callable[[str], str] | None = None,
) -> Any:
    """Connect Q&A nodes; keep execution disabled and retrieval lazy."""
    from artagent.graph import (
        ErrorInfo, Path as RoutePath, create_answer_node,
        create_router_graph, create_search_nodes,
    )
    from artagent.graph.nodes import dispatch_node
    from artagent.graph.research import create_research_node, generate_search_query

    services = search_nodes

    def search(state):
        nonlocal services
        node = (
            "SEARCH_RAWPEDIA"
            if state["decision"].plan[state["cursor"]].path == RoutePath.DOC_QA
            else "SEARCH_GITHUB"
        )
        try:
            if services is None:
                from artagent.answer import verify_store_ready
                from artagent.retrieval.embedding import load_encoder
                from artagent.retrieval.store import open_store
                from artagent.retrieval.types import load_spec

                spec = load_spec(reference)
                verify_store_ready(persist_dir, spec)
                encoder = load_encoder(spec)
                services = create_search_nodes(
                    open_store(persist_dir, spec), encoder,
                    snapshot_ref=spec.reference_sha256,
                    rewrite_enabled=False, hyde_enabled=False,
                )
            return services[node](state)
        except Exception as exc:
            print(f"GUI search preparation: {type(exc).__name__}",
                  file=sys.stderr)
            return {
                "error": ErrorInfo(
                    "SEARCH_UNAVAILABLE",
                    "검색 자료를 준비하지 못했습니다. 연결 설정의 자료 폴더와 "
                    "검색 저장소, 설치된 실행 환경을 확인해주세요.", node,
                ),
                "trace": [*state.get("trace", []), node],
            }

    def dispatch(state):
        decision, cursor = state.get("decision"), state.get("cursor", 0)
        if (decision and 0 <= cursor < len(decision.plan)
                and decision.plan[cursor].path == RoutePath.EXECUTE):
            return {
                **dict.fromkeys(("retrieval", "answer", "execution", "features",
                                 "profile", "validation", "render")),
                "error": ErrorInfo(
                    "UNSUPPORTED", UNSUPPORTED_MESSAGE, "DISPATCH",
                ),
                "trace": [*state.get("trace", []), "DISPATCH"],
            }
        return dispatch_node(state)

    return create_router_graph(node_overrides={
        "SEARCH_RAWPEDIA": search, "SEARCH_GITHUB": search,
        "ANSWER": answer_node or create_answer_node(source_root=source_root),
        "DISPATCH": dispatch,
        "RESEARCH": create_research_node(
            generate=research_generate if research_generate is not None else generate_search_query,
        ),
    })


def error_response(request_id: str, code: str, message: str) -> dict:
    """Keep transport and preparation failures in the same response envelope."""
    return {
        "version": 1, "request_id": request_id, "status": "FAILED",
        "message": message, "steps": [], "citations": [],
        "error": {"code": code, "message": message},
    }


def display_error(error: Any) -> dict | None:
    """Keep private diagnostics off the GUI boundary."""
    if error is None:
        return None
    messages = {
        "UNSUPPORTED": UNSUPPORTED_MESSAGE,
        "UNSUPPORTED_OPERATION": UNSUPPORTED_MESSAGE,
        "INSUFFICIENT_EVIDENCE": "근거가 부족하여 답변할 수 없습니다.",
        "SEARCH_UNAVAILABLE": "검색 자료를 준비하지 못했습니다. 연결 설정의 "
        "자료 폴더와 검색 저장소, 설치된 실행 환경을 확인해주세요.",
        "ANSWER_GENERATION_FAILED": "답변을 생성하지 못했습니다. "
        "실행 환경의 접속·인증 설정을 확인하고 다시 시도해주세요.",
    }
    return {
        "code": error.code,
        "message": messages.get(error.code, "요청을 처리하지 못했습니다. "
                                "연결 설정을 확인하고 다시 시도해주세요."),
    }


def process_request(payload: Any, graph_factory: Callable[[], Any]) -> dict:
    """Validate a request and serialize the router response."""
    started = monotonic()
    request_id = (
        payload.get("request_id", "") if isinstance(payload, dict) else ""
    )
    if not isinstance(request_id, str) or len(request_id) > 128:
        request_id = ""
    text = payload.get("text") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or type(payload.get("version")) is not int
            or payload["version"] != 1 or not request_id.strip()
            or not isinstance(text, str) or not text.strip()
            or len(text) > 8192 or "\x00" in text):
        return error_response(
            request_id, "INVALID_INPUT", "질문을 1~8192자 이내로 입력해주세요.",
        )

    from .live_param_chat import try_apply

    live_response = try_apply(text, payload.get("live_param"), request_id)
    if live_response is not None:
        return live_response

    from artagent.graph import RequestInput, RuntimeCapabilities
    from artagent.answer import generation_time_budget

    remaining = max(0.0, GUI_GENERATION_BUDGET_SECONDS - (monotonic() - started))
    with generation_time_budget(remaining):
        result = graph_factory().invoke({
            "request": RequestInput(request_id=request_id, text=text.strip()),
            "capabilities": RuntimeCapabilities(search_ready=True),
        })
    response = result.get("response")
    if response is None:
        return error_response(
            request_id, "MISSING_RESPONSE", "답변을 받지 못했습니다.",
        )
    public_error = display_error(response.error)
    message = public_error["message"] if public_error else response.message
    if response.status == "WAITING_CLARIFICATION":
        message += " 질문 전체를 구체적으로 다시 입력해주세요."
    return {
        "version": 1, "request_id": request_id,
        "status": response.status, "message": message,
        "steps": [{
            "path": step.path.value, "status": step.status,
            "text": step.answer.text if step.answer else "",
            "citations": [asdict(c) for c in step.answer.citations]
            if step.answer else [],
            "error": display_error(step.error),
        } for step in response.completed_steps],
        "citations": [asdict(c) for c in response.citations],
        "error": public_error,
    }


def main(argv: list[str] | None = None) -> int:
    """Read one bounded JSON document; keep diagnostics off protocol stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--persist-dir", type=Path)
    args = parser.parse_args(argv)
    request_id = ""
    try:
        raw = sys.stdin.read(MAX_REQUEST_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("Request is too large")
        payload = json.loads(raw)
        if (isinstance(payload, dict)
                and isinstance(payload.get("request_id"), str)):
            request_id = payload["request_id"][:128]
        with redirect_stdout(sys.stderr):
            response = process_request(payload, lambda: create_gui_graph(
                args.reference or args.source_root / "docs"
                / "T08_2_t9_handoff_reference.json",
                args.persist_dir or args.source_root / "data/vector-store/t09",
                args.source_root,
            ))
    except (ValueError, UnicodeError):
        response = error_response(
            request_id, "INVALID_INPUT", "질문 입력 형식을 확인해주세요.",
        )
    except Exception as exc:
        print(f"GUI request failed: {type(exc).__name__}", file=sys.stderr)
        response = error_response(
            request_id, "BRIDGE_ERROR",
            "질문을 처리하지 못했습니다. 연결 설정과 실행 환경을 확인해주세요.",
        )
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    return 1 if response["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
