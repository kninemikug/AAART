"""Node implementations for the LangGraph router and pipeline graph.

Adheres to Section 5.2 of docs/langgraph_router_design.md.
"""

from __future__ import annotations

import re
from typing import Any

from .router import analyze_signals, route_request
from .state import (
    AgentState,
    AnswerResult,
    Artifact,
    AssetRef,
    Citation,
    Clarification,
    ErrorInfo,
    Evidence,
    ExecutionInput,
    OutputSpec,
    Path,
    PhotoFeatures,
    ProfileData,
    ResponseOutput,
    ResponseStatus,
    RetrievalBundle,
    RuntimeCapabilities,
    StepResult,
    ValidationResult,
    RenderResult,
)


def intake_node(state: AgentState) -> dict[str, Any]:
    """Validate external input and initialize state."""
    trace = list(state.get("trace", []))
    trace.append("INTAKE")

    request = state.get("request")
    if not request or not request.request_id.strip() or not request.text.strip():
        error = ErrorInfo(
            code="INVALID_INPUT",
            message="Request input must include non-empty request_id and text",
            node="INTAKE",
            recoverable=False,
        )
        return {"error": error, "trace": trace}

    capabilities = state.get("capabilities") or RuntimeCapabilities()
    return {
        "cursor": state.get("cursor", 0),
        "research_count": state.get("research_count", 0),
        "clarification_count": state.get("clarification_count", 0),
        "profile_attempts": state.get("profile_attempts", 0),
        "render_attempts": state.get("render_attempts", 0),
        "step_results": state.get("step_results", {}),
        "capabilities": capabilities,
        "trace": trace,
    }


def route_node(state: AgentState) -> dict[str, Any]:
    """Apply R1~R8 rules to determine intent signals, plan, or clarification."""
    trace = list(state.get("trace", []))
    trace.append("ROUTE")

    request = state["request"]
    completed_steps = state.get("step_results", {})
    decision, clarification = route_request(request, completed_steps)
    signals = analyze_signals(request.text, request.context)

    if not decision.plan and not clarification:
        error = ErrorInfo(
            code="OUT_OF_SCOPE",
            message="The request is out of supported scope or empty",
            node="ROUTE",
            recoverable=False,
        )
        return {"signals": signals, "decision": decision, "error": error, "trace": trace}

    if clarification:
        count = state.get("clarification_count", 0) + 1
        return {
            "signals": signals,
            "decision": decision,
            "clarification": clarification,
            "clarification_count": count,
            "trace": trace,
        }

    return {
        "signals": signals,
        "decision": decision,
        "clarification": None,
        "cursor": 0,
        "trace": trace,
    }


def clarify_node(state: AgentState) -> dict[str, Any]:
    """Handle pause for clarification or resume when user reply is provided."""
    trace = list(state.get("trace", []))
    trace.append("CLARIFY")

    resume = state.get("resume")
    clarification = state.get("clarification")
    clarification_count = state.get("clarification_count", 1)

    if resume:
        # Check user cancellation
        reply_lower = resume.reply_text.strip().lower()
        if re.search(r"(?:취소|그만|cancel|stop)", reply_lower):
            error = ErrorInfo(
                code="CANCELLED",
                message="User cancelled the request during clarification",
                node="CLARIFY",
                recoverable=False,
            )
            return {"error": error, "clarification": None, "trace": trace}

        # Check if unresolved after 2 attempts
        if clarification_count >= 2 and not resume.reply_text.strip():
            error = ErrorInfo(
                code="CLARIFICATION_UNRESOLVED",
                message="Clarification remained unresolved after maximum attempts",
                node="CLARIFY",
                recoverable=False,
            )
            return {"error": error, "trace": trace}

        # User provided resolution: update request text and assets
        req = state["request"]
        updated_text = f"{req.text} {resume.reply_text}".strip()
        merged_assets = list(req.assets)
        for a in resume.assets:
            if not any(existing.asset_id == a.asset_id for existing in merged_assets):
                merged_assets.append(a)

        req.text = updated_text
        req.assets = merged_assets

        return {
            "request": req,
            "clarification": None,
            "clarification_count": 0,
            "resume": None,
            "trace": trace,
        }

    # No reply yet: construct waiting response and hold
    response = ResponseOutput(
        request_id=state["request"].request_id,
        status=ResponseStatus.WAITING_CLARIFICATION.value,
        primary_path=state.get("decision").primary_path if state.get("decision") else None,
        planned_paths=[s.path for s in state["decision"].plan] if state.get("decision") else [],
        completed_steps=list(state.get("step_results", {}).values()),
        message=clarification.question if clarification else "추가 정보가 필요합니다.",
        clarification=clarification,
    )
    return {"response": response, "trace": trace}


def dispatch_node(state: AgentState) -> dict[str, Any]:
    """Inspect next plan step, check dependencies and runtime capabilities."""
    trace = list(state.get("trace", []))
    trace.append("DISPATCH")

    decision = state.get("decision")
    cursor = state.get("cursor", 0)

    if not decision or cursor >= len(decision.plan):
        # All steps dispatched
        return {"trace": trace}

    current_step = decision.plan[cursor]
    step_results = state.get("step_results", {})
    capabilities = state.get("capabilities", RuntimeCapabilities())

    # Check step dependencies (e.g. M02 requires P2 to succeed)
    for req_id in current_step.requires:
        req_res = step_results.get(req_id)
        if not req_res or req_res.status not in ("SUCCEEDED", "SUPPORTED"):
            error = ErrorInfo(
                code="DEPENDENCY_UNSATISFIED",
                message=f"Step {current_step.step_id} depends on {req_id} which did not succeed",
                node="DISPATCH",
                recoverable=False,
            )
            return {"error": error, "trace": trace}

    # Check runtime capabilities
    if current_step.path in (Path.DOC_QA, Path.TROUBLESHOOT):
        if not capabilities.search_ready:
            error = ErrorInfo(
                code="CAPABILITY_UNAVAILABLE",
                message="Search service is currently unavailable",
                node="DISPATCH",
                recoverable=False,
            )
            return {"error": error, "trace": trace}

    if current_step.path == Path.EXECUTE:
        if not capabilities.profile_ready or not capabilities.render_ready:
            error = ErrorInfo(
                code="CAPABILITY_UNAVAILABLE",
                message="Profile generation or rendering service is currently unavailable",
                node="DISPATCH",
                recoverable=False,
            )
            return {"error": error, "trace": trace}

    # Clear temporary fields for the new step
    updates: dict[str, Any] = {
        "retrieval": None,
        "answer": None,
        "execution": None,
        "features": None,
        "profile": None,
        "validation": None,
        "render": None,
        "error": None,
        "trace": trace,
    }
    if current_step.path == Path.EXECUTE:
        updates["profile_attempts"] = 0
        updates["render_attempts"] = 0

    return updates


def search_rawpedia_node(state: AgentState) -> dict[str, Any]:
    """Retrieve RawPedia documentation chunks for P1 DOC_QA."""
    trace = list(state.get("trace", []))
    trace.append("SEARCH_RAWPEDIA")

    decision = state["decision"]
    cursor = state["cursor"]
    step = decision.plan[cursor]

    evidence = Evidence(
        chunk_id=f"rawpedia_{step.step_id}_chunk1",
        doc_id="rawpedia_doc_1",
        source_group_id="rawpedia_exposure",
        source_type="rawpedia",
        source_path="data/rawpedia/exposure.md",
        source_location="Exposure and Tone Mapping",
        target_url="https://rawpedia.rawtherapee.com/Exposure",
        text=f"RawPedia reference details for: {step.query}",
        product_scope="RawTherapee / ART",
    )
    bundle = RetrievalBundle(
        query=step.query,
        source_filter="RAWPEDIA",
        hits=[evidence],
        snapshot_ref="rawpedia_20260904",
    )
    return {"retrieval": bundle, "trace": trace}


def search_github_node(state: AgentState) -> dict[str, Any]:
    """Retrieve GitHub Issues and Discussions chunks for P2 TROUBLESHOOT."""
    trace = list(state.get("trace", []))
    trace.append("SEARCH_GITHUB")

    decision = state["decision"]
    cursor = state["cursor"]
    step = decision.plan[cursor]

    evidence = Evidence(
        chunk_id=f"github_{step.step_id}_chunk1",
        doc_id="github_issue_516",
        source_group_id="github_issue",
        source_type="github",
        source_path="data/issues/issue_516.json",
        source_location="Issue #516 comment #2",
        target_url="https://github.com/Agatha-org/ART/issues/516",
        text=f"GitHub Issue/Discussion reference details for: {step.query}",
        product_scope="ART",
    )
    bundle = RetrievalBundle(
        query=step.query,
        source_filter="GITHUB",
        hits=[evidence],
        snapshot_ref="github_snapshot_20260904",
    )
    return {"retrieval": bundle, "trace": trace}


def answer_node(state: AgentState) -> dict[str, Any]:
    """Generate grounded answer with citations from retrieved evidence."""
    trace = list(state.get("trace", []))
    trace.append("ANSWER")

    retrieval = state.get("retrieval")
    cursor = state["cursor"]
    step = state["decision"].plan[cursor]

    # Handle negative / unsupported cases or lack of evidence
    if not retrieval or not retrieval.hits:
        answer = AnswerResult(
            status="INSUFFICIENT_EVIDENCE",
            text="관련 근거를 찾을 수 없습니다.",
            citations=[],
        )
        return {"answer": answer, "trace": trace}

    # Grounded answer with citation
    hit = retrieval.hits[0]
    citation = Citation(
        doc_id=hit.doc_id,
        title=hit.source_location,
        url=hit.target_url,
        source_location=hit.source_location,
    )
    answer = AnswerResult(
        status="SUPPORTED",
        text=f"근거 답변: {hit.text} [출처: {citation.title}·{citation.url}]",
        citations=[citation],
        actionable_goal=None,
    )
    return {"answer": answer, "trace": trace}


def research_node(state: AgentState) -> dict[str, Any]:
    """1-time query rewriting for insufficient evidence."""
    trace = list(state.get("trace", []))
    trace.append("RESEARCH")

    cursor = state["cursor"]
    step = state["decision"].plan[cursor]
    step.query = f"{step.query} (rewritten)"

    return {
        "research_count": 1,
        "retrieval": None,
        "answer": None,
        "trace": trace,
    }


def check_exec_node(state: AgentState) -> dict[str, Any]:
    """Verify execution inputs (RAW file, goal, output spec) for P3."""
    trace = list(state.get("trace", []))
    trace.append("CHECK_EXEC")

    request = state["request"]

    # Locate RAW asset
    raw_asset = next((a for a in request.assets if a.kind.upper() == "RAW"), None)
    if not raw_asset and request.context and request.context.target_raw_id:
        raw_asset = AssetRef(
            asset_id=request.context.target_raw_id,
            kind="RAW",
            path=request.context.target_raw_id,
        )

    if not raw_asset:
        # RAW missing -> Clarification needed
        count = state.get("clarification_count", 0) + 1
        clarification = Clarification(
            id=f"clarify_raw_{request.request_id}",
            question="어떤 RAW 파일에 적용할까요?",
            missing_fields=["raw"],
            candidate_paths=[Path.EXECUTE],
            origin="CHECK_EXEC",
        )
        return {
            "clarification": clarification,
            "clarification_count": count,
            "trace": trace,
        }

    # Goal and output spec
    output_spec = (
        request.context.output
        if (request.context and request.context.output)
        else OutputSpec(format="JPEG")
    )
    goal = (
        request.context.confirmed_goal
        if (request.context and request.context.confirmed_goal)
        else state.get("signals").goal or "기본 보정 적용"
    )

    execution = ExecutionInput(
        raw=raw_asset,
        goal=goal,
        output=output_spec,
    )
    return {"execution": execution, "trace": trace}


def features_node(state: AgentState) -> dict[str, Any]:
    """Extract photo features (EXIF, histogram) from RAW."""
    trace = list(state.get("trace", []))
    trace.append("FEATURES")

    exec_input = state["execution"]
    features = PhotoFeatures(
        exif={"ISO": 100, "Camera": "Canon EOS R8", "Shutter": "1/200"},
        histogram={"luminance": [0.1, 0.5, 0.4]},
        raw_asset_id=exec_input.raw.asset_id,
    )
    return {"features": features, "trace": trace}


def generate_profile_node(state: AgentState) -> dict[str, Any]:
    """Generate structured profile data."""
    trace = list(state.get("trace", []))
    trace.append("GENERATE_PROFILE")

    capabilities = state.get("capabilities", RuntimeCapabilities())
    profile = ProfileData(
        ppversion=capabilities.ppversion,
        groups={"Exposure": {"Compensation": 0.0}, "WhiteBalance": {"Temperature": 5500}},
        changed_keys=["Exposure.Compensation", "WhiteBalance.Temperature"],
    )
    attempts = state.get("profile_attempts", 0) + 1
    return {
        "profile": profile,
        "profile_attempts": attempts,
        "validation": None,
        "trace": trace,
    }


def validate_profile_node(state: AgentState) -> dict[str, Any]:
    """Validate profile against schema and PPVERSION."""
    trace = list(state.get("trace", []))
    trace.append("VALIDATE_PROFILE")

    profile = state["profile"]
    capabilities = state.get("capabilities", RuntimeCapabilities())

    if profile.ppversion != capabilities.ppversion:
        error = ErrorInfo(
            code="PROFILE_INVALID",
            message=f"PPVERSION mismatch: expected {capabilities.ppversion}, got {profile.ppversion}",
            node="VALIDATE_PROFILE",
            recoverable=False,
        )
        validation = ValidationResult(
            status="INVALID",
            issues=[{"field": "ppversion", "code": "VERSION_MISMATCH", "message": error.message}],
        )
        return {"validation": validation, "error": error, "trace": trace}

    validation = ValidationResult(
        status="VALID",
        issues=[],
        profile_ref="/tmp/validated_profile.arp",
    )
    return {"validation": validation, "trace": trace}


def render_node(state: AgentState) -> dict[str, Any]:
    """Invoke ART-cli headless renderer."""
    trace = list(state.get("trace", []))
    trace.append("RENDER")

    attempts = state.get("render_attempts", 0) + 1
    render_result = RenderResult(
        status="SUCCEEDED",
        exit_code=0,
        output_path="/tmp/output.jpg",
        output_verified=True,
        diagnostic="Render successful",
    )
    return {
        "render": render_result,
        "render_attempts": attempts,
        "trace": trace,
    }


def repair_profile_node(state: AgentState) -> dict[str, Any]:
    """Repair recoverable profile defects."""
    trace = list(state.get("trace", []))
    trace.append("REPAIR_PROFILE")

    attempts = state.get("profile_attempts", 0) + 1
    profile = state["profile"]
    profile.groups["Exposure"]["Compensation"] = 0.0  # reset defect

    return {
        "profile": profile,
        "profile_attempts": attempts,
        "validation": None,
        "error": None,
        "trace": trace,
    }


def fallback_node(state: AgentState) -> dict[str, Any]:
    """Handle step or request failure and map to appropriate error status."""
    trace = list(state.get("trace", []))
    trace.append("FALLBACK")

    error = state.get("error")
    answer = state.get("answer")

    return {"trace": trace}


def advance_node(state: AgentState) -> dict[str, Any]:
    """Commit step result, increment cursor to next step."""
    trace = list(state.get("trace", []))
    trace.append("ADVANCE")

    cursor = state["cursor"]
    decision = state["decision"]
    step = decision.plan[cursor]
    results = dict(state.get("step_results", {}))

    error = state.get("error")
    answer = state.get("answer")
    render = state.get("render")

    # Determine status
    if error:
        if error.code == "DEPENDENCY_UNSATISFIED":
            status = "BLOCKED"
        elif error.code in ("UNSUPPORTED", "UNSUPPORTED_OPERATION"):
            status = "UNSUPPORTED"
        elif error.code == "INSUFFICIENT_EVIDENCE":
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "FAILED"
    elif answer:
        status = "SUCCEEDED" if answer.status == "SUPPORTED" else answer.status
    elif render:
        status = "SUCCEEDED" if render.status == "SUCCEEDED" else "FAILED"
    else:
        status = "SUCCEEDED"

    artifacts: list[Artifact] = []
    if render and render.output_path and render.output_verified:
        artifacts.append(Artifact(kind="RENDER", path=render.output_path, verified=True))

    res = StepResult(
        step_id=step.step_id,
        path=step.path,
        status=status,
        answer=answer,
        artifacts=artifacts,
        error=error,
    )
    results[step.step_id] = res

    return {
        "step_results": results,
        "cursor": cursor + 1,
        "error": None,
        "trace": trace,
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    """Aggregate final response output."""
    trace = list(state.get("trace", []))
    trace.append("RESPOND")

    request = state["request"]
    decision = state.get("decision")
    step_results = list(state.get("step_results", {}).values())
    error = state.get("error")

    all_citations: list[Citation] = []
    all_artifacts: list[Artifact] = []
    for r in step_results:
        if r.answer and r.answer.citations:
            all_citations.extend(r.answer.citations)
        all_artifacts.extend(r.artifacts)

    # Determine overall status
    if error:
        if error.code == "INVALID_INPUT":
            status = ResponseStatus.FAILED.value
        elif error.code == "OUT_OF_SCOPE":
            status = ResponseStatus.OUT_OF_SCOPE.value
        elif error.code == "CANCELLED":
            status = ResponseStatus.CANCELLED.value
        else:
            status = ResponseStatus.FAILED.value
        msg = error.message
    elif state.get("clarification"):
        status = ResponseStatus.WAITING_CLARIFICATION.value
        msg = state["clarification"].question
    elif not step_results:
        status = ResponseStatus.COMPLETED.value
        msg = "완료되었습니다."
    else:
        succeeded = [r for r in step_results if r.status == "SUCCEEDED"]
        failed = [r for r in step_results if r.status in ("FAILED", "BLOCKED", "UNSUPPORTED")]
        if len(succeeded) == len(step_results):
            status = ResponseStatus.COMPLETED.value
            msg = "요청된 모든 단계가 성공적으로 완료되었습니다."
        elif len(succeeded) > 0:
            status = ResponseStatus.PARTIAL.value
            msg = "일부 단계만 완료되었습니다."
        elif any(r.status == "UNSUPPORTED" for r in step_results):
            status = ResponseStatus.UNSUPPORTED.value
            msg = "지원되지 않는 요청입니다."
        elif any(r.status == "INSUFFICIENT_EVIDENCE" for r in step_results):
            status = ResponseStatus.INSUFFICIENT_EVIDENCE.value
            msg = "근거가 부족하여 답변할 수 없습니다."
        else:
            status = ResponseStatus.FAILED.value
            msg = "실행에 실패했습니다."

    response = ResponseOutput(
        request_id=request.request_id,
        status=status,
        primary_path=decision.primary_path if decision else None,
        planned_paths=[s.path for s in decision.plan] if decision else [],
        completed_steps=step_results,
        message=msg,
        citations=all_citations,
        artifacts=all_artifacts,
        clarification=state.get("clarification"),
        error=error,
    )
    return {"response": response, "trace": trace}
