"""Search nodes for LangGraph router connection (Task 14-CONN / A-14).

Provides SEARCH_RAWPEDIA and SEARCH_GITHUB node factories connecting
query rewriting (rewrite.py) and T09 vector search (store.py) to AgentState.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Sequence

from ..retrieval.embedding import EncoderSession
from ..retrieval.store import RetrievalStore
from ..retrieval.types import SearchHit
from .rewrite import prepare_search_input
from .state import AgentState, ErrorInfo, Evidence, RetrievalBundle

# GitHub Issue / Discussion URL and keyword patterns
_RE_GH_ISSUE_URL = re.compile(
    r"https?://github\.com/artraweditor/ART/issues/(\d+)",
    re.IGNORECASE,
)
_RE_GH_DISC_URL = re.compile(
    r"https?://github\.com/artraweditor/ART/discussions/(\d+)",
    re.IGNORECASE,
)
_RE_GH_ISSUE_KW = re.compile(
    r"(?:(?:GitHub\s*)?Issue|이슈)\s*#?(\d+)",
    re.IGNORECASE,
)
_RE_GH_DISC_KW = re.compile(
    r"(?:(?:GitHub\s*)?Discussion|디스커션)\s*#?(\d+)",
    re.IGNORECASE,
)


def resolve_github_targets(query: str, request_text: str = "") -> Optional[list[str]]:
    """원요청 및 쿼리에서 GitHub Issue / Discussion 번호를 추출하여 group_id 목록 반환.

    명시된 대상이 없으면 None 반환 (전체 검색).
    """
    combined = f"{query} {request_text}"
    targets: list[str] = []

    for num in _RE_GH_ISSUE_URL.findall(combined):
        gid = f"github:artraweditor/ART:issue:{num}"
        if gid not in targets:
            targets.append(gid)

    for num in _RE_GH_DISC_URL.findall(combined):
        gid = f"github:artraweditor/ART:discussion:{num}"
        if gid not in targets:
            targets.append(gid)

    for num in _RE_GH_ISSUE_KW.findall(combined):
        gid = f"github:artraweditor/ART:issue:{num}"
        if gid not in targets:
            targets.append(gid)

    for num in _RE_GH_DISC_KW.findall(combined):
        gid = f"github:artraweditor/ART:discussion:{num}"
        if gid not in targets:
            targets.append(gid)

    return targets if targets else None


def search_hits_to_evidences(hits: Sequence[SearchHit]) -> list[Evidence]:
    """T09 SearchHit 목록을 그래프 Evidence 객체 목록으로 변환.

    세그먼트별 실제 doc/ref ID, URL, 파일, char 범위, 제품 범위 및 해당 텍스트를 보존한다.
    """
    evidences: list[Evidence] = []
    for hit in hits:
        scope = "RawTherapee" if hit.source_type == "rawpedia" else "ART"
        if hit.source_segments:
            for seg in hit.source_segments:
                c_start = seg.get("content_char_start")
                c_end = seg.get("content_char_end")
                if c_start is not None and c_end is not None and 0 <= c_start <= c_end <= len(hit.content):
                    text = hit.content[c_start:c_end]
                else:
                    text = hit.content

                ev = Evidence(
                    chunk_id=hit.chunk_id,
                    doc_id=seg.get("doc_id") or hit.doc_id,
                    source_group_id=hit.source_group_id,
                    source_type=hit.source_type,
                    source_path=seg.get("source_path") or hit.original_metadata.get("source_path", ""),
                    source_location=hit.section_title or seg.get("doc_id", ""),
                    target_url=seg.get("target_url") or hit.original_metadata.get("target_url", ""),
                    text=text,
                    product_scope=scope,
                )
                evidences.append(ev)
        else:
            ev = Evidence(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                source_group_id=hit.source_group_id,
                source_type=hit.source_type,
                source_path=hit.original_metadata.get("source_path", ""),
                source_location=hit.section_title or hit.doc_id,
                target_url=hit.original_metadata.get("target_url", ""),
                text=hit.content,
                product_scope=scope,
            )
            evidences.append(ev)
    return evidences


def _extract_query_and_constraints(state: AgentState) -> tuple[str, tuple[str, ...]]:
    """state에서 현재 실행할 쿼리와 제약조건 목록을 추출."""
    step_query = ""
    decision = state.get("decision")
    cursor = state.get("cursor", 0)
    if decision and cursor < len(decision.plan):
        step_query = decision.plan[cursor].query

    if not step_query:
        request = state.get("request")
        if request and request.text:
            step_query = request.text

    constraints: list[str] = []
    request = state.get("request")
    if request and request.context:
        ctx = request.context
        if ctx.os:
            constraints.append(f"OS: {ctx.os}")
        if ctx.art_version:
            constraints.append(f"Version: {ctx.art_version}")
        if ctx.confirmed_goal:
            constraints.append(f"Goal: {ctx.confirmed_goal}")

    signals = state.get("signals")
    if signals and signals.constraints:
        constraints.extend(signals.constraints)

    return step_query, tuple(constraints)


def create_search_rawpedia_node(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = True,
    hyde_enabled: bool = False,
) -> Callable[[AgentState], dict[str, Any]]:
    """SEARCH_RAWPEDIA 노드 팩토리."""

    def search_rawpedia(state: AgentState) -> dict[str, Any]:
        node_name = "SEARCH_RAWPEDIA"
        trace = list(state.get("trace", []))
        trace.append(node_name)

        step_query, constraints = _extract_query_and_constraints(state)

        # 1. T14 재작성 입력 준비
        search_input = prepare_search_input(
            step_query,
            generate=generate,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
            constraints=constraints,
        )

        if search_input.status == "error":
            return {
                "error": ErrorInfo(
                    code="REWRITE_FAILED",
                    message=f"Query rewrite failed: {search_input.error_category}: {search_input.error_message}",
                    node=node_name,
                    recoverable=False,
                ),
                "trace": trace,
            }

        # 2. T9 검색 실행 (source_type="rawpedia")
        try:
            hits = store.search(
                search_input.search_query,
                session,
                source_type="rawpedia",
            )
        except Exception as ex:
            return {
                "error": ErrorInfo(
                    code="SEARCH_UNAVAILABLE",
                    message=f"Search service failed in {node_name}: {ex}",
                    node=node_name,
                    recoverable=False,
                ),
                "trace": trace,
            }

        # 3. Evidence 매핑 및 RetrievalBundle 구성
        evidence_list = search_hits_to_evidences(hits)
        bundle = RetrievalBundle(
            query=search_input.search_query,
            source_filter="RAWPEDIA",
            hits=evidence_list,
            snapshot_ref=snapshot_ref,
        )

        return {
            "retrieval": bundle,
            "error": None,
            "trace": trace,
        }

    return search_rawpedia


def create_search_github_node(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = True,
    hyde_enabled: bool = False,
) -> Callable[[AgentState], dict[str, Any]]:
    """SEARCH_GITHUB 노드 팩토리."""

    def search_github(state: AgentState) -> dict[str, Any]:
        node_name = "SEARCH_GITHUB"
        trace = list(state.get("trace", []))
        trace.append(node_name)

        step_query, constraints = _extract_query_and_constraints(state)

        # 대상 Issue/Discussion 번호 파싱
        req_text = state.get("request").text if state.get("request") else ""
        target_group_ids = resolve_github_targets(step_query, req_text)

        # 1. T14 재작성 입력 준비
        search_input = prepare_search_input(
            step_query,
            generate=generate,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
            constraints=constraints,
        )

        if search_input.status == "error":
            return {
                "error": ErrorInfo(
                    code="REWRITE_FAILED",
                    message=f"Query rewrite failed: {search_input.error_category}: {search_input.error_message}",
                    node=node_name,
                    recoverable=False,
                ),
                "trace": trace,
            }

        # 2. T9 검색 실행 (source_type="github", source_group_ids=target_group_ids)
        try:
            hits = store.search(
                search_input.search_query,
                session,
                source_type="github",
                source_group_ids=target_group_ids,
            )
        except Exception as ex:
            return {
                "error": ErrorInfo(
                    code="SEARCH_UNAVAILABLE",
                    message=f"Search service failed in {node_name}: {ex}",
                    node=node_name,
                    recoverable=False,
                ),
                "trace": trace,
            }

        # 3. Evidence 매핑 및 RetrievalBundle 구성
        evidence_list = search_hits_to_evidences(hits)
        bundle = RetrievalBundle(
            query=search_input.search_query,
            source_filter="GITHUB",
            hits=evidence_list,
            snapshot_ref=snapshot_ref,
        )

        return {
            "retrieval": bundle,
            "error": None,
            "trace": trace,
        }

    return search_github


def create_search_nodes(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = True,
    hyde_enabled: bool = False,
) -> dict[str, Callable[[AgentState], dict[str, Any]]]:
    """SEARCH_RAWPEDIA 및 SEARCH_GITHUB 노드 override 매핑 생성."""
    return {
        "SEARCH_RAWPEDIA": create_search_rawpedia_node(
            store,
            session,
            generate=generate,
            snapshot_ref=snapshot_ref,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
        ),
        "SEARCH_GITHUB": create_search_github_node(
            store,
            session,
            generate=generate,
            snapshot_ref=snapshot_ref,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
        ),
    }
