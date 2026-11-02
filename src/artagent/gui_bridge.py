"""Serve one JSON request from ART's native chat panel over standard I/O."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Callable


UNSUPPORTED_MESSAGE = (
    "실행 요청은 아직 미지원입니다. 프로필 생성·렌더링 루프와 "
    "세션 저장·증분 수정이 완료되면 제공됩니다. "
    "현재는 질문·답변만 이용할 수 있습니다."
)
MAX_REQUEST_BYTES = 65536


def create_gui_graph(
    reference: Path,
    persist_dir: Path,
    source_root: Path,
    *,
    search_nodes: dict | None = None,
    answer_node: Callable | None = None,
) -> Any:
    """Connect Q&A nodes; keep execution disabled and retrieval lazy."""
    from artagent.graph import (
        ErrorInfo, Path as RoutePath, create_answer_node,
        create_router_graph, create_search_nodes,
    )
    from artagent.graph.nodes import dispatch_node

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

    def stop_research(state):
        return {
            "error": ErrorInfo(
                "INSUFFICIENT_EVIDENCE", "근거가 부족하여 답변할 수 없습니다.",
                "RESEARCH",
            ),
            "trace": [*state.get("trace", []), "RESEARCH"],
        }

    return create_router_graph(node_overrides={
        "SEARCH_RAWPEDIA": search, "SEARCH_GITHUB": search,
        "ANSWER": answer_node or create_answer_node(source_root=source_root),
        "DISPATCH": dispatch, "RESEARCH": stop_research,
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

    from artagent.graph import RequestInput, RuntimeCapabilities

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
