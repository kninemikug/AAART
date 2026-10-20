"""Task 22: Terminal Chat Minimal REPL for ART Master Agent.

Provides an interactive CLI REPL executing grounded Q&A and troubleshooting
queries against the LangGraph router graph, while blocking execution requests
with an explicit unsupported notice according to docs/T22_execution_plan.md.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Optional, Sequence
import uuid

from langgraph.graph.state import CompiledStateGraph

from .answer import (
    get_source_root,
    load_spec,
    open_store,
    resolve_persist_dir,
    resolve_reference_path,
    verify_store_ready,
)
from .graph import (
    AgentState,
    ErrorInfo,
    Path as AgentPath,
    RequestInput,
    ResponseOutput,
    ResponseStatus,
    RuntimeCapabilities,
    create_answer_node,
    create_router_graph,
    create_search_nodes,
)
from .graph.nodes import dispatch_node
from .retrieval.embedding import EncoderSession, load_encoder
from .retrieval.store import RetrievalStore

EXECUTE_UNSUPPORTED_MESSAGE = (
    "실행 요청은 아직 미지원입니다. 프로필 생성·렌더링 루프와\n"
    "세션 저장·증분 수정이 완료되면 제공됩니다.\n"
    "현재는 질문·답변만 이용할 수 있습니다."
)

CLARIFICATION_RETRY_MESSAGE = "질문 전체를 구체적으로 다시 입력해주세요."


def create_dispatch_wrapper() -> Callable[[AgentState], dict[str, Any]]:
    """EXECUTE 단계는 미지원 오류로 차단하고 나머지는 dispatch_node에 위임."""

    def dispatch_wrapper(state: AgentState) -> dict[str, Any]:
        decision = state.get("decision")
        cursor = state.get("cursor", 0)
        if decision and 0 <= cursor < len(decision.plan):
            current_step = decision.plan[cursor]
            if (
                current_step.path == AgentPath.EXECUTE
                or str(current_step.path) == "EXECUTE"
            ):
                trace = list(state.get("trace", []))
                trace.append("DISPATCH")
                return {
                    "error": ErrorInfo(
                        code="UNSUPPORTED",
                        message=EXECUTE_UNSUPPORTED_MESSAGE,
                        node="DISPATCH",
                        recoverable=False,
                    ),
                    "retrieval": None,
                    "answer": None,
                    "execution": None,
                    "features": None,
                    "profile": None,
                    "validation": None,
                    "render": None,
                    "trace": trace,
                }
        return dispatch_node(state)

    return dispatch_wrapper


def research_wrapper(state: AgentState) -> dict[str, Any]:
    """재검색 없이 INSUFFICIENT_EVIDENCE 오류로 종결하는 RESEARCH 래퍼."""
    trace = list(state.get("trace", []))
    trace.append("RESEARCH")
    return {
        "error": ErrorInfo(
            code="INSUFFICIENT_EVIDENCE",
            message="근거가 부족하여 답변할 수 없습니다.",
            node="RESEARCH",
            recoverable=False,
        ),
        "trace": trace,
    }


def build_repl_graph(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    source_root: Optional[Path] = None,
    generate: Optional[Callable[..., Any]] = None,
) -> CompiledStateGraph:
    """최소 REPL용 라우터 그래프 빌드 및 override 노드 연결."""
    search_nodes = create_search_nodes(
        store=store,
        session=session,
        generate=generate,
        snapshot_ref="",
        rewrite_enabled=False,
        hyde_enabled=False,
    )
    ans_node = create_answer_node(
        generate=generate,
        source_root=source_root,
    )
    overrides = {
        **search_nodes,
        "ANSWER": ans_node,
        "DISPATCH": create_dispatch_wrapper(),
        "RESEARCH": research_wrapper,
    }
    return create_router_graph(node_overrides=overrides)


def render_response(
    response: ResponseOutput,
    write_fn: Callable[[str], None] = print,
) -> None:
    """ResponseOutput을 콘솔에 서식화하여 출력."""
    if response.status == ResponseStatus.WAITING_CLARIFICATION.value:
        write_fn(f"[{response.status}]")
        q = (
            response.clarification.question
            if response.clarification
            else response.message
        )
        write_fn(q)
        write_fn(CLARIFICATION_RETRY_MESSAGE)
        return

    if response.error is not None:
        write_fn(
            f"[{response.status}] ({response.error.code}) "
            f"{response.error.message}"
        )
    else:
        write_fn(f"[{response.status}] {response.message}")

    if not response.completed_steps:
        return

    for step in response.completed_steps:
        write_fn("")
        if step.status == "SUCCEEDED" and step.answer:
            write_fn(step.answer.text)
            if step.answer.citations:
                write_fn("\n[인용 목록]")
                for cit in step.answer.citations:
                    write_fn(f"- {cit.title} ({cit.url})")
        elif (
            step.path == AgentPath.EXECUTE
            or str(step.path) == "EXECUTE"
        ) and step.status == "UNSUPPORTED":
            code = step.error.code if step.error else "UNSUPPORTED"
            msg = (
                step.error.message
                if step.error
                else EXECUTE_UNSUPPORTED_MESSAGE
            )
            write_fn(f"[{code}]")
            write_fn(msg)
        else:
            if step.error is not None:
                write_fn(f"[{step.error.code}] {step.error.message}")
            else:
                write_fn(f"[{step.status}]")
            if step.answer and step.answer.text:
                write_fn(step.answer.text)
                if step.answer.citations:
                    write_fn("\n[인용 목록]")
                    for cit in step.answer.citations:
                        write_fn(f"- {cit.title} ({cit.url})")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """CLI 옵션 파싱."""
    parser = argparse.ArgumentParser(
        prog="python -m artagent.cli",
        description="ART Master Agent 터미널 대화형 인터페이스 (최소 REPL)",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help=(
            "T09 handoff reference JSON 경로 "
            "(기본값: T09_REFERENCE_PATH 또는 "
            "docs/T08_2_t9_handoff_reference.json)"
        ),
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=None,
        help=(
            "T09 Chroma 저장소 디렉터리 경로 "
            "(기본값: T09_PERSIST_DIR 또는 data/vector-store/t09)"
        ),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help=(
            "원문 검증 소스 루트 디렉터리 경로 "
            "(기본값: T09_SOURCE_ROOT 또는 레포지토리 루트)"
        ),
    )
    return parser.parse_args(argv)


def load_resources(
    reference_path: Optional[Path] = None,
    persist_dir: Optional[Path] = None,
    source_root: Optional[Path] = None,
) -> tuple[RetrievalStore, EncoderSession, Path]:
    """검색 저장소, 임베딩 인코더, 소스 루트를 검증하고 로드한다."""
    if reference_path is not None:
        resolved_ref = reference_path.resolve()
        if not resolved_ref.is_file():
            raise FileNotFoundError(
                f"지정한 reference 파일이 없습니다: {resolved_ref}"
            )
    else:
        env_ref = os.getenv("T09_REFERENCE_PATH")
        if env_ref:
            resolved_ref = Path(env_ref).resolve()
            if not resolved_ref.is_file():
                raise FileNotFoundError(
                    f"T09_REFERENCE_PATH 파일이 없습니다: {resolved_ref}"
                )
        else:
            resolved_ref = resolve_reference_path()

    spec = load_spec(resolved_ref)

    if persist_dir is not None:
        resolved_persist = persist_dir.resolve()
        if not resolved_persist.is_dir():
            raise FileNotFoundError(
                f"지정한 Chroma persist 디렉터리가 없습니다: {resolved_persist}"
            )
    else:
        env_persist = os.getenv("T09_PERSIST_DIR")
        if env_persist:
            resolved_persist = Path(env_persist).resolve()
            if not resolved_persist.is_dir():
                raise FileNotFoundError(
                    f"T09_PERSIST_DIR 디렉터리가 없습니다: {resolved_persist}"
                )
        else:
            resolved_persist = resolve_persist_dir()

    verify_store_ready(resolved_persist, spec)
    encoder = load_encoder(spec)
    store = open_store(resolved_persist, spec)

    if source_root is not None:
        resolved_source = source_root.resolve()
        if not resolved_source.is_dir():
            raise FileNotFoundError(
                f"지정한 source-root 디렉터리가 없습니다: {resolved_source}"
            )
    else:
        env_source = os.getenv("T09_SOURCE_ROOT")
        if env_source:
            resolved_source = Path(env_source).resolve()
            if not resolved_source.is_dir():
                raise FileNotFoundError(
                    f"T09_SOURCE_ROOT 디렉터리가 없습니다: {resolved_source}"
                )
        else:
            resolved_source = get_source_root()
            if not resolved_source.is_dir():
                raise FileNotFoundError(
                    f"기본 source-root 디렉터리가 없습니다: {resolved_source}"
                )

    return store, encoder, resolved_source


def run_repl(
    graph: CompiledStateGraph,
    *,
    input_fn: Callable[[str], str] = input,
    write_fn: Callable[[str], None] = print,
) -> int:
    """REPL 루프 실행: 입력 반복, 독립 요청 생성, 그래프 호출 및 출력."""
    while True:
        try:
            line = input_fn("art> ")
        except (EOFError, KeyboardInterrupt):
            write_fn("")
            break

        query = line.strip()
        if not query:
            continue

        if query.lower() in ("/quit", "/exit"):
            break

        request = RequestInput(
            request_id=f"req_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            text=query,
            session_id=None,
            assets=[],
            context=None,
        )

        try:
            result = graph.invoke(
                {
                    "request": request,
                    "capabilities": RuntimeCapabilities(
                        search_ready=True,
                        profile_ready=False,
                        render_ready=False,
                    ),
                }
            )
            response: Optional[ResponseOutput] = result.get("response")
            if response is None:
                write_fn("[FAILED] 응답이 생성되지 않았습니다.")
            else:
                render_response(response, write_fn=write_fn)
        except Exception as ex:
            write_fn(f"[FAILED] 요청 처리 중 오류가 발생했습니다: {ex}")

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 메인 진입점."""
    args = parse_args(argv)

    try:
        store, encoder, source_root = load_resources(
            reference_path=args.reference,
            persist_dir=args.persist_dir,
            source_root=args.source_root,
        )
        graph = build_repl_graph(
            store=store,
            session=encoder,
            source_root=source_root,
        )
    except Exception as ex:
        sys.stderr.write(f"오류: 준비 실패: {ex}\n")
        return 1

    return run_repl(graph)


if __name__ == "__main__":
    sys.exit(main())
