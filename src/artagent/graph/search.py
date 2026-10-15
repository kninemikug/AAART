"""Search nodes for LangGraph router connection (Task 14-CONN / A-14).

Provides SEARCH_RAWPEDIA and SEARCH_GITHUB node factories connecting
query rewriting (rewrite.py) and T09 vector search (store.py) to AgentState.
"""

from __future__ import annotations

from dataclasses import asdict
import re
import time
from typing import Any, Callable, Optional, Sequence

from ..retrieval.embedding import EncoderSession
from ..retrieval.store import RetrievalStore
from ..retrieval.types import SearchHit
from ..retrieval.provenance import canonical_json_str, sha256_str
from .rewrite import build_preservation_constraints, prepare_search_input
from .state import AgentState, ErrorInfo, Evidence, RetrievalBundle

# GitHub Issue / Discussion URL and keyword patterns
_RE_GH_ISSUE_URL = re.compile(
    r"https?://github\.com/artraweditor/ART/issues/(\d+)",
    re.IGNORECASE,
)
_RE_GH_DISC_URL = re.compile(
    r"https?://github\.com/(?:artraweditor/ART|orgs/artraweditor)/discussions/(\d+)",
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
        if hit.source_type not in ("rawpedia", "github"):
            raise ValueError("지원하지 않는 검색 출처")
        if not hit.source_segments or hit.content_sha256 != sha256_str(hit.content):
            raise ValueError(f"본문 해시 또는 원문 세그먼트 누락: {hit.chunk_id}")
        for seg in hit.source_segments:
            c_start = seg.get("content_char_start")
            c_end = seg.get("content_char_end")
            if (type(c_start) is not int or type(c_end) is not int
                    or not 0 <= c_start <= c_end <= len(hit.content)):
                raise ValueError(f"원문 세그먼트 범위 오류: {hit.chunk_id}")
            text = hit.content[c_start:c_end]
            if (any(not seg.get(key) for key in ("doc_id", "source_path", "target_url",
                                                "source_file_sha256", "segment_sha256"))
                    or seg["segment_sha256"] != sha256_str(text)):
                raise ValueError(f"원문 세그먼트 출처 또는 해시 오류: {hit.chunk_id}")
            ev = Evidence(
                chunk_id=hit.chunk_id,
                doc_id=seg["doc_id"],
                source_group_id=hit.source_group_id,
                source_type=hit.source_type,
                source_path=seg["source_path"],
                source_location=canonical_json_str({
                    "section_title": hit.section_title, "source_segment": seg,
                }),
                target_url=seg["target_url"],
                text=text,
                product_scope=scope,
            )
            evidences.append(ev)
    return evidences


def _extract_query_and_constraints(
    state: AgentState, *, preserve_literals: bool = False,
) -> tuple[str, tuple[str, ...]]:
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

    if preserve_literals:
        constraints.extend(build_preservation_constraints(" ".join((step_query, *constraints))))
    return step_query, tuple(constraints)


def create_search_rawpedia_node(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = False,
    hyde_enabled: bool = False,
    observe: Optional[Callable[[dict[str, Any]], None]] = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """SEARCH_RAWPEDIA 노드 팩토리. 비저하 채택 전에는 재작성을 명시적으로 켠다."""

    return _create_search_node(store, session, source_type="rawpedia", generate=generate,
                               snapshot_ref=snapshot_ref, rewrite_enabled=rewrite_enabled,
                               hyde_enabled=hyde_enabled, observe=observe)


def create_search_github_node(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = False,
    hyde_enabled: bool = False,
    observe: Optional[Callable[[dict[str, Any]], None]] = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """SEARCH_GITHUB 노드 팩토리."""

    return _create_search_node(store, session, source_type="github", generate=generate,
                               snapshot_ref=snapshot_ref, rewrite_enabled=rewrite_enabled,
                               hyde_enabled=hyde_enabled, observe=observe)


def _create_search_node(
    store: RetrievalStore, session: EncoderSession, *, source_type: str,
    generate: Optional[Callable[[str], str]], snapshot_ref: str,
    rewrite_enabled: bool, hyde_enabled: bool,
    observe: Optional[Callable[[dict[str, Any]], None]],
) -> Callable[[AgentState], dict[str, Any]]:
    """검색 관측은 state 밖으로 전달하며 원본 SearchHit을 손실 없이 보존한다."""
    def search(state: AgentState) -> dict[str, Any]:
        node_name = "SEARCH_RAWPEDIA" if source_type == "rawpedia" else "SEARCH_GITHUB"
        trace = list(state.get("trace", []))
        trace.append(node_name)
        step_query, constraints = _extract_query_and_constraints(state, preserve_literals=True)
        req_text = state.get("request").text if state.get("request") else ""
        target_group_ids = resolve_github_targets(step_query, req_text) if source_type == "github" else None
        started = time.perf_counter()
        search_input = prepare_search_input(
            step_query,
            generate=generate,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
            constraints=constraints,
        )

        hits: list[SearchHit] = []
        search_calls = 0
        evidence_list: list[Evidence] = []
        error = None
        if search_input.status == "error":
            error = ErrorInfo(
                    code="REWRITE_FAILED",
                    message=f"Query rewrite failed: {search_input.error_category}: {search_input.error_message}",
                    node=node_name,
                    recoverable=False,
                )
        else:
            try:
                filters: dict[str, Any] = {"source_type": source_type}
                if source_type == "github":
                    filters["source_group_ids"] = target_group_ids
                search_calls = 1
                hits = store.search(search_input.search_query, session, **filters)
                if any(hit.source_type != source_type or (target_group_ids and hit.source_group_id not in target_group_ids)
                       for hit in hits):
                    raise ValueError("검색 출처·대상 글 계약 위반")
                evidence_list = search_hits_to_evidences(hits)
            except Exception as ex:
                error = ErrorInfo(
                    code="SEARCH_UNAVAILABLE",
                    message=f"Search service failed in {node_name}: {ex}",
                    node=node_name,
                    recoverable=False,
                )
        if observe is not None:
            decision = state.get("decision")
            cursor = state.get("cursor", 0)
            observe({
                "node": node_name, "step_id": decision.plan[cursor].step_id if decision else "",
                "source_type": source_type, "source_group_ids": target_group_ids,
                "search_input": asdict(search_input), "hits": [asdict(hit) for hit in hits],
                "evidences": [asdict(ev) for ev in evidence_list],
                "search_call_count": search_calls, "elapsed_ms": (time.perf_counter() - started) * 1000,
                "error": asdict(error) if error else None,
            })
        if error is not None:
            return {"error": error, "trace": trace}
        bundle = RetrievalBundle(
            query=search_input.search_query,
            source_filter="RAWPEDIA" if source_type == "rawpedia" else "GITHUB",
            hits=evidence_list,
            snapshot_ref=snapshot_ref,
        )

        return {
            "retrieval": bundle,
            "error": None,
            "trace": trace,
        }

    return search


def create_search_nodes(
    store: RetrievalStore,
    session: EncoderSession,
    *,
    generate: Optional[Callable[[str], str]] = None,
    snapshot_ref: str = "",
    rewrite_enabled: bool = False,
    hyde_enabled: bool = False,
    observe: Optional[Callable[[dict[str, Any]], None]] = None,
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
            observe=observe,
        ),
        "SEARCH_GITHUB": create_search_github_node(
            store,
            session,
            generate=generate,
            snapshot_ref=snapshot_ref,
            rewrite_enabled=rewrite_enabled,
            hyde_enabled=hyde_enabled,
            observe=observe,
        ),
    }
