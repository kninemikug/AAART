"""StateGraph definition and compilation for ART Master Agent.

Constructs the routing and execution state machine conforming to Sections 5.1 and 5.3
of docs/langgraph_router_design.md.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .nodes import (
    advance_node,
    answer_node,
    check_exec_node,
    clarify_node,
    dispatch_node,
    fallback_node,
    features_node,
    generate_profile_node,
    intake_node,
    render_node,
    repair_profile_node,
    research_node,
    respond_node,
    route_node,
    search_github_node,
    search_rawpedia_node,
    validate_profile_node,
)
from .state import AgentState, Path


def route_after_intake(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    if state.get("clarification") or state.get("resume"):
        return "CLARIFY"
    return "ROUTE"


def route_after_route(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    if state.get("clarification"):
        return "CLARIFY"
    return "DISPATCH"


def route_after_clarify(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    if state.get("clarification"):
        # Paused waiting for user response
        return END
    if state.get("resume_origin") == "CHECK_EXEC":
        return "CHECK_EXEC"
    return "ROUTE"


def route_after_dispatch(state: AgentState) -> str:
    decision = state.get("decision")
    cursor = state.get("cursor", 0)
    if not decision or cursor >= len(decision.plan):
        return "RESPOND"
    if state.get("error"):
        return "FALLBACK"

    current_step = decision.plan[cursor]
    if current_step.path == Path.DOC_QA:
        return "SEARCH_RAWPEDIA"
    if current_step.path == Path.TROUBLESHOOT:
        return "SEARCH_GITHUB"
    if current_step.path == Path.EXECUTE:
        return "CHECK_EXEC"
    return "FALLBACK"


def route_after_search_rawpedia(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    return "ANSWER"


def route_after_search_github(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    return "ANSWER"


def route_after_answer(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    ans = state.get("answer")
    if ans and ans.status == "SUPPORTED":
        return "ADVANCE"
    if ans and ans.status == "UNSUPPORTED":
        return "FALLBACK"
    if ans and ans.status == "INSUFFICIENT_EVIDENCE":
        if state.get("research_count", 0) == 0:
            return "RESEARCH"
        return "FALLBACK"
    return "FALLBACK"


def route_after_research(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    cursor = state.get("cursor", 0)
    step = state["decision"].plan[cursor]
    if step.path == Path.DOC_QA:
        return "SEARCH_RAWPEDIA"
    if step.path == Path.TROUBLESHOOT:
        return "SEARCH_GITHUB"
    return "FALLBACK"


def route_after_check_exec(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    if state.get("clarification"):
        return "CLARIFY"
    return "FEATURES"


def route_after_features(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    return "GENERATE_PROFILE"


def route_after_generate_profile(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    return "VALIDATE_PROFILE"


def route_after_validate_profile(state: AgentState) -> str:
    val = state.get("validation")
    if state.get("error") and (not val or val.status != "INVALID" or state["error"].code != "PROFILE_INVALID"):
        return "FALLBACK"
    if val and val.status == "VALID":
        if state.get("render_attempts", 0) < 3:
            return "RENDER"
        return "FALLBACK"
    if val and val.status == "INVALID":
        err = state.get("error")
        if err and err.recoverable and state.get("profile_attempts", 0) < 3:
            return "REPAIR_PROFILE"
        return "FALLBACK"
    return "FALLBACK"


def route_after_render(state: AgentState) -> str:
    render = state.get("render")
    if state.get("error") and (not render or render.status != "FAILED" or state["error"].code != "RENDER_FAILED"):
        return "FALLBACK"
    if render and render.status == "SUCCEEDED":
        return "ADVANCE"
    if render and render.status == "UNKNOWN":
        return "FALLBACK"
    if render and render.status == "FAILED":
        err = state.get("error")
        if (
            err
            and err.recoverable
            and state.get("profile_attempts", 0) < 3
            and state.get("render_attempts", 0) < 3
        ):
            return "REPAIR_PROFILE"
        return "FALLBACK"
    return "FALLBACK"


def route_after_repair_profile(state: AgentState) -> str:
    if state.get("error"):
        return "FALLBACK"
    return "VALIDATE_PROFILE"


def route_after_fallback(state: AgentState) -> str:
    err = state.get("error")
    if err and err.code in (
        "INVALID_INPUT",
        "OUT_OF_SCOPE",
        "CANCELLED",
        "CLARIFICATION_UNRESOLVED",
        "CONTRACT_VIOLATION",
    ):
        return "RESPOND"
    return "ADVANCE"


def route_after_advance(state: AgentState) -> str:
    cursor = state.get("cursor", 0)
    decision = state.get("decision")
    if decision and cursor < len(decision.plan):
        return "DISPATCH"
    return "RESPOND"


def create_router_graph(
    node_overrides: Mapping[str, Callable[[AgentState], dict]] | None = None,
) -> CompiledStateGraph:
    """Build the router; integrations may provide concrete service nodes."""
    graph = StateGraph(AgentState)
    overrides = dict(node_overrides or {})
    nodes = {
        "INTAKE": intake_node,
        "ROUTE": route_node,
        "CLARIFY": clarify_node,
        "DISPATCH": dispatch_node,
        "SEARCH_RAWPEDIA": search_rawpedia_node,
        "SEARCH_GITHUB": search_github_node,
        "ANSWER": answer_node,
        "RESEARCH": research_node,
        "CHECK_EXEC": check_exec_node,
        "FEATURES": features_node,
        "GENERATE_PROFILE": generate_profile_node,
        "VALIDATE_PROFILE": validate_profile_node,
        "RENDER": render_node,
        "REPAIR_PROFILE": repair_profile_node,
        "FALLBACK": fallback_node,
        "ADVANCE": advance_node,
        "RESPOND": respond_node,
    }
    unknown = set(overrides) - set(nodes)
    if unknown:
        raise ValueError(f"Unknown graph nodes: {sorted(unknown)}")

    for name, default in nodes.items():
        graph.add_node(name, overrides.get(name, default))

    # Entry point
    graph.add_edge(START, "INTAKE")

    # Conditional transitions
    graph.add_conditional_edges(
        "INTAKE",
        route_after_intake,
        {"FALLBACK": "FALLBACK", "ROUTE": "ROUTE", "CLARIFY": "CLARIFY"},
    )
    graph.add_conditional_edges(
        "ROUTE",
        route_after_route,
        {"FALLBACK": "FALLBACK", "CLARIFY": "CLARIFY", "DISPATCH": "DISPATCH"},
    )
    graph.add_conditional_edges(
        "CLARIFY",
        route_after_clarify,
        {"FALLBACK": "FALLBACK", "ROUTE": "ROUTE", "CHECK_EXEC": "CHECK_EXEC", END: END},
    )
    graph.add_conditional_edges(
        "DISPATCH",
        route_after_dispatch,
        {
            "RESPOND": "RESPOND",
            "FALLBACK": "FALLBACK",
            "SEARCH_RAWPEDIA": "SEARCH_RAWPEDIA",
            "SEARCH_GITHUB": "SEARCH_GITHUB",
            "CHECK_EXEC": "CHECK_EXEC",
        },
    )
    graph.add_conditional_edges(
        "SEARCH_RAWPEDIA",
        route_after_search_rawpedia,
        {"FALLBACK": "FALLBACK", "ANSWER": "ANSWER"},
    )
    graph.add_conditional_edges(
        "SEARCH_GITHUB",
        route_after_search_github,
        {"FALLBACK": "FALLBACK", "ANSWER": "ANSWER"},
    )
    graph.add_conditional_edges(
        "ANSWER",
        route_after_answer,
        {"ADVANCE": "ADVANCE", "FALLBACK": "FALLBACK", "RESEARCH": "RESEARCH"},
    )
    graph.add_conditional_edges(
        "RESEARCH",
        route_after_research,
        {
            "FALLBACK": "FALLBACK",
            "SEARCH_RAWPEDIA": "SEARCH_RAWPEDIA",
            "SEARCH_GITHUB": "SEARCH_GITHUB",
        },
    )
    graph.add_conditional_edges(
        "CHECK_EXEC",
        route_after_check_exec,
        {"CLARIFY": "CLARIFY", "FALLBACK": "FALLBACK", "FEATURES": "FEATURES"},
    )
    graph.add_conditional_edges(
        "FEATURES",
        route_after_features,
        {"FALLBACK": "FALLBACK", "GENERATE_PROFILE": "GENERATE_PROFILE"},
    )
    graph.add_conditional_edges(
        "GENERATE_PROFILE",
        route_after_generate_profile,
        {"FALLBACK": "FALLBACK", "VALIDATE_PROFILE": "VALIDATE_PROFILE"},
    )
    graph.add_conditional_edges(
        "VALIDATE_PROFILE",
        route_after_validate_profile,
        {"RENDER": "RENDER", "REPAIR_PROFILE": "REPAIR_PROFILE", "FALLBACK": "FALLBACK"},
    )
    graph.add_conditional_edges(
        "RENDER",
        route_after_render,
        {"ADVANCE": "ADVANCE", "FALLBACK": "FALLBACK", "REPAIR_PROFILE": "REPAIR_PROFILE"},
    )
    graph.add_conditional_edges(
        "REPAIR_PROFILE",
        route_after_repair_profile,
        {"FALLBACK": "FALLBACK", "VALIDATE_PROFILE": "VALIDATE_PROFILE"},
    )
    graph.add_conditional_edges(
        "FALLBACK",
        route_after_fallback,
        {"RESPOND": "RESPOND", "ADVANCE": "ADVANCE"},
    )
    graph.add_conditional_edges(
        "ADVANCE",
        route_after_advance,
        {"DISPATCH": "DISPATCH", "RESPOND": "RESPOND"},
    )

    # Final transition
    graph.add_edge("RESPOND", END)

    return graph.compile()
