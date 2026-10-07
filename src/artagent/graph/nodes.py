"""Node implementations for the LangGraph router and pipeline graph.

Adheres to Section 5.2 of docs/langgraph_router_design.md.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path as FilePath
from typing import Any

from .router import analyze_signals, route_request
from .state import (
    AgentState,
    Artifact,
    Citation,
    Clarification,
    ErrorInfo,
    ExecutionInput,
    OutputSpec,
    Path,
    ResponseOutput,
    ResponseStatus,
    RuntimeCapabilities,
    StepResult,
    ValidationIssue,
    ValidationResult,
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
    decision, clarification = route_request(request, completed_steps, state.get("resolved_goal"))
    signals = analyze_signals(request.text, request.context)
    if state.get("resolved_goal"):
        signals.goal = state["resolved_goal"]
        signals.ambiguous_reasons = [
            reason for reason in signals.ambiguous_reasons
            if reason != "CONFLICTING_GLOBAL_EXPOSURE_GOALS"
        ]

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
        if count > 2:
            error = ErrorInfo(
                code="CLARIFICATION_UNRESOLVED",
                message="Clarification remained unresolved after maximum attempts",
                node="ROUTE",
                recoverable=False,
            )
            return {"error": error, "clarification": None, "trace": trace}
        clarification = replace(clarification, id=f"{clarification.id}_{count}")
        return {
            "signals": signals,
            "decision": decision,
            "clarification": clarification,
            "clarification_count": count,
            "trace": trace,
        }

    cursor = 0
    for step in decision.plan:
        result = completed_steps.get(step.step_id)
        if result and result.path == step.path and result.status == "SUCCEEDED":
            cursor += 1
        else:
            break
    return {
        "signals": signals,
        "decision": decision,
        "clarification": None,
        "clarification_count": 0,
        "cursor": cursor,
        "trace": trace,
    }


def clarify_node(state: AgentState) -> dict[str, Any]:
    """Handle pause for clarification or resume when user reply is provided."""
    trace = list(state.get("trace", []))
    trace.append("CLARIFY")

    resume = state.get("resume")
    clarification = state.get("clarification")
    clarification_count = state.get("clarification_count", 1)
    req = state.get("request")

    if resume:
        # 1. Validate clarification presence and ID match
        if not clarification:
            error = ErrorInfo(
                code="INVALID_INPUT",
                message="No active clarification to resume",
                node="CLARIFY",
                recoverable=False,
            )
            return {"error": error, "clarification": None, "resume": None, "trace": trace}

        if (
            resume.clarification_id != clarification.id
            or (req and resume.request_id != req.request_id)
        ):
            error = ErrorInfo(
                code="INVALID_INPUT",
                message=(
                    f"Clarification ID or Request ID mismatch: expected "
                    f"({clarification.id}, {req.request_id if req else ''}), "
                    f"got ({resume.clarification_id}, {resume.request_id})"
                ),
                node="CLARIFY",
                recoverable=False,
            )
            return {"error": error, "clarification": None, "resume": None, "trace": trace}

        # 2. Check user cancellation
        reply_lower = resume.reply_text.strip().lower()
        if re.search(r"(?:취소|그만|cancel|stop)", reply_lower):
            error = ErrorInfo(
                code="CANCELLED",
                message="User cancelled the request during clarification",
                node="CLARIFY",
                recoverable=False,
            )
            return {"error": error, "clarification": None, "resume": None, "trace": trace}

        # 3. Check if empty reply provided
        is_empty_reply = not resume.reply_text.strip() and not resume.assets
        if is_empty_reply:
            if clarification_count >= 2:
                error = ErrorInfo(
                    code="CLARIFICATION_UNRESOLVED",
                    message="Clarification remained unresolved after maximum attempts",
                    node="CLARIFY",
                    recoverable=False,
                )
                return {"error": error, "clarification": None, "resume": None, "trace": trace}
            next_clarification = replace(clarification, id=f"{clarification.id}_retry2")
            response = ResponseOutput(
                request_id=req.request_id if req else "",
                status=ResponseStatus.WAITING_CLARIFICATION.value,
                primary_path=state.get("decision").primary_path if state.get("decision") else None,
                planned_paths=[s.path for s in state["decision"].plan] if state.get("decision") else [],
                completed_steps=list(state.get("step_results", {}).values()),
                message=next_clarification.question,
                clarification=next_clarification,
            )
            return {
                "clarification_count": clarification_count + 1,
                "clarification": next_clarification,
                "resume": None,
                "response": response,
                "trace": trace,
            }

        # 4. User provided reply text/assets: update request, preserve clarification_count
        updated_text = f"{req.text} {resume.reply_text}".strip() if req else resume.reply_text.strip()
        merged_assets = list(req.assets) if req else []
        for a in resume.assets:
            if not any(existing.asset_id == a.asset_id for existing in merged_assets):
                merged_assets.append(a)

        updated_request = replace(req, text=updated_text, assets=merged_assets) if req else None
        resolved_goal = state.get("resolved_goal")
        if state.get("decision") and "R7_CONFLICTING_GOALS" in state["decision"].reason_codes:
            if re.search(r"밝게|올려", resume.reply_text):
                resolved_goal = "전체 노출 밝게 보정"
            elif re.search(r"어둡게|낮춰", resume.reply_text):
                resolved_goal = "전체 노출 낮춰 보정"

        return {
            "request": updated_request,
            "signals": analyze_signals(updated_text, req.context) if req else None,
            "resolved_goal": resolved_goal,
            "clarification": None,
            "clarification_count": clarification_count,
            "resume_origin": clarification.origin,
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
    return _unavailable(state, "SEARCH_RAWPEDIA")


def search_github_node(state: AgentState) -> dict[str, Any]:
    """Retrieve GitHub Issues and Discussions chunks for P2 TROUBLESHOOT."""
    return _unavailable(state, "SEARCH_GITHUB")


def _unavailable(state: AgentState, node: str) -> dict[str, Any]:
    trace = list(state.get("trace", []))
    trace.append(node)
    return {
        "error": ErrorInfo(
            code="CAPABILITY_UNAVAILABLE",
            message=f"{node} integration is not connected",
            node=node,
            recoverable=False,
        ),
        "trace": trace,
    }


def answer_node(state: AgentState) -> dict[str, Any]:
    """Generate grounded answer with citations from retrieved evidence."""
    return _unavailable(state, "ANSWER")


def research_node(state: AgentState) -> dict[str, Any]:
    """1-time query rewriting for insufficient evidence."""
    return _unavailable(state, "RESEARCH")


def check_exec_node(state: AgentState) -> dict[str, Any]:
    """Verify execution inputs (RAW file, goal, output spec) for P3."""
    trace = list(state.get("trace", []))
    trace.append("CHECK_EXEC")

    request = state["request"]
    decision = state.get("decision")
    cursor = state.get("cursor", 0)
    if not decision or cursor >= len(decision.plan) or not state.get("signals") or not state["signals"].wants_execute:
        return {
            "error": ErrorInfo("CONTRACT_VIOLATION", "Explicit execution intent is required", "CHECK_EXEC"),
            "trace": trace,
        }

    step = decision.plan[cursor]
    derived_goal = None
    for prerequisite_id in step.requires:
        prerequisite = state.get("step_results", {}).get(prerequisite_id)
        if not prerequisite or prerequisite.status != "SUCCEEDED":
            return {
                "error": ErrorInfo("DEPENDENCY_UNSATISFIED", "Prerequisite did not succeed", "CHECK_EXEC"),
                "trace": trace,
            }
        actionable = prerequisite.answer.actionable_goal if prerequisite.answer else None
        if not actionable:
            return {
                "error": ErrorInfo(
                    "DEPENDENCY_UNSATISFIED",
                    "Prerequisite did not supply a supported profile adjustment",
                    "CHECK_EXEC",
                ),
                "trace": trace,
            }
        derived_goal = actionable

    raw_assets = [asset for asset in request.assets if asset.kind.upper() == "RAW" and asset.path.strip()]
    target_id = request.context.target_raw_id if request.context else None
    selected = [asset for asset in raw_assets if asset.asset_id == target_id] if target_id else raw_assets
    if len(selected) != 1:
        return _ask_execution_input(state, "raw", "어떤 RAW 파일에 적용할까요?", trace)
    raw_asset = selected[0]

    goal = derived_goal or state["signals"].goal
    goal = goal or (request.context.confirmed_goal if request.context else None)
    if not goal or not goal.strip():
        return _ask_execution_input(state, "confirmed_goal", "어떤 보정 목표를 적용할까요?", trace)

    output_spec = request.context.output if request.context else None
    destination = re.search(r"(?:/|\./)?[\w./-]+\.(?:jpe?g|png|tiff?)(?![A-Za-z0-9])", request.text, re.IGNORECASE)
    if destination and (not output_spec or not output_spec.destination.strip()):
        suffix = destination.group().rsplit(".", 1)[1].upper()
        output_spec = OutputSpec(
            format="JPEG" if suffix in ("JPG", "JPEG") else "TIFF" if suffix in ("TIF", "TIFF") else "PNG",
            destination=destination.group(),
        )
    if (
        not output_spec
        or output_spec.format.upper() not in ("JPEG", "PNG", "TIFF")
        or not output_spec.destination.strip()
    ):
        return _ask_execution_input(state, "output", "출력 형식과 저장 위치를 알려주세요.", trace)

    execution = ExecutionInput(
        raw=raw_asset,
        goal=goal,
        output=output_spec,
    )
    return {
        "execution": execution,
        "clarification": None,
        "clarification_count": 0,
        "clarification_field": None,
        "resume_origin": None,
        "trace": trace,
    }


def _ask_execution_input(
    state: AgentState, field: str, question: str, trace: list[str]
) -> dict[str, Any]:
    count = (
        state.get("clarification_count", 0) + 1
        if state.get("clarification_field") == field else 1
    )
    if count > 2:
        return {
            "error": ErrorInfo(
                "CLARIFICATION_UNRESOLVED",
                "Execution input clarification unresolved after maximum attempts",
                "CHECK_EXEC",
            ),
            "clarification": None,
            "trace": trace,
        }
    clarification = Clarification(
        id=f"clarify_{field}_{state['request'].request_id}_{count}",
        question=question,
        missing_fields=[field],
        candidate_paths=[Path.EXECUTE],
        origin="CHECK_EXEC",
    )
    return {
        "clarification": clarification,
        "clarification_count": count,
        "clarification_field": field,
        "trace": trace,
    }


def features_node(state: AgentState) -> dict[str, Any]:
    """Extract photo features (EXIF, histogram) from RAW."""
    return _unavailable(state, "FEATURES")


def generate_profile_node(state: AgentState) -> dict[str, Any]:
    """Generate structured profile data."""
    return _unavailable(state, "GENERATE_PROFILE")


def validate_profile_node(state: AgentState) -> dict[str, Any]:
    """Validate profile against schema and PPVERSION."""
    trace = list(state.get("trace", []))
    trace.append("VALIDATE_PROFILE")

    profile = state.get("profile")
    capabilities = state.get("capabilities", RuntimeCapabilities())
    issues: list[ValidationIssue] = []

    # 1. Profile existence check
    if profile is None:
        issues.append(
            ValidationIssue(
                field="profile",
                code="MISSING_PROFILE",
                message="Profile data is missing",
            )
        )
        error = ErrorInfo(
            code="PROFILE_INVALID",
            message="Profile data is missing",
            node="VALIDATE_PROFILE",
            recoverable=False,
        )
        validation = ValidationResult(status="INVALID", issues=issues)
        return {"validation": validation, "error": error, "trace": trace}

    # 2. PPVERSION check
    if not isinstance(profile.ppversion, int) or profile.ppversion != capabilities.ppversion:
        issues.append(
            ValidationIssue(
                field="ppversion",
                code="VERSION_MISMATCH",
                message=f"PPVERSION mismatch: expected {capabilities.ppversion}, got {profile.ppversion}",
            )
        )

    # 3. Reject names absent from the checked-in ART .arp key inventory.
    schema_keys = _arp_schema_keys()
    if not isinstance(profile.groups, dict) or len(profile.groups) == 0:
        issues.append(
            ValidationIssue(
                field="groups",
                code="EMPTY_GROUPS",
                message="Profile groups must be a non-empty dictionary",
            )
        )
    else:
        for group_name, group_data in profile.groups.items():
            if not isinstance(group_name, str) or not group_name.strip():
                issues.append(
                    ValidationIssue(
                        field="groups",
                        code="INVALID_GROUP_NAME",
                        message="Group name must be a non-empty string",
                    )
                )
            elif group_name not in schema_keys:
                issues.append(
                    ValidationIssue(
                        field=f"groups.{group_name}",
                        code="UNKNOWN_GROUP",
                        message=f"Group '{group_name}' is absent from the ART profile schema",
                    )
                )
            if not isinstance(group_data, dict):
                issues.append(
                    ValidationIssue(
                        field=f"groups.{group_name}",
                        code="INVALID_GROUP_DATA",
                        message=f"Group '{group_name}' must be a dictionary",
                    )
                )
            else:
                for key, val in group_data.items():
                    if not isinstance(key, str) or not key.strip():
                        issues.append(
                            ValidationIssue(
                                field=f"{group_name}.{key}",
                                code="INVALID_KEY_NAME",
                                message="Key name must be a non-empty string",
                            )
                        )
                    elif group_name in schema_keys and key not in schema_keys[group_name]:
                        issues.append(
                            ValidationIssue(
                                field=f"{group_name}.{key}",
                                code="UNKNOWN_KEY",
                                message=f"Key '{key}' is absent from group '{group_name}'",
                            )
                        )
                    if val is None:
                        issues.append(
                            ValidationIssue(
                                field=f"{group_name}.{key}",
                                code="NULL_VALUE",
                                message="Profile value cannot be None",
                            )
                        )
                    elif isinstance(val, float):
                        if math.isnan(val) or math.isinf(val):
                            issues.append(
                                ValidationIssue(
                                    field=f"{group_name}.{key}",
                                    code="NON_FINITE_FLOAT",
                                    message="Profile float value must be finite",
                                )
                            )
                    elif isinstance(val, list):
                        for idx, item in enumerate(val):
                            if item is None:
                                issues.append(
                                    ValidationIssue(
                                        field=f"{group_name}.{key}[{idx}]",
                                        code="NULL_VALUE",
                                        message="List item cannot be None",
                                    )
                                )
                            elif isinstance(item, float):
                                if math.isnan(item) or math.isinf(item):
                                    issues.append(
                                        ValidationIssue(
                                            field=f"{group_name}.{key}[{idx}]",
                                            code="NON_FINITE_FLOAT",
                                            message="List float item must be finite",
                                        )
                                    )
                            elif not isinstance(item, (bool, int, str)):
                                issues.append(
                                    ValidationIssue(
                                        field=f"{group_name}.{key}[{idx}]",
                                        code="INVALID_TYPE",
                                        message=f"Unsupported list item type: {type(item).__name__}",
                                    )
                                )
                    elif not isinstance(val, (bool, int, str)):
                        issues.append(
                            ValidationIssue(
                                field=f"{group_name}.{key}",
                                code="INVALID_TYPE",
                                message=f"Unsupported value type: {type(val).__name__}",
                            )
                        )

    # 4. Changed keys check
    if not isinstance(profile.changed_keys, list) or len(profile.changed_keys) == 0:
        issues.append(
            ValidationIssue(
                field="changed_keys",
                code="EMPTY_CHANGED_KEYS",
                message="changed_keys must be a non-empty list",
            )
        )
    else:
        for k in profile.changed_keys:
            if not isinstance(k, str) or "." not in k:
                issues.append(
                    ValidationIssue(
                        field="changed_keys",
                        code="INVALID_KEY_FORMAT",
                        message=f"changed_key '{k}' must follow 'Group.Key' format",
                    )
                )
            else:
                grp, subk = k.split(".", 1)
                if (
                    not isinstance(profile.groups, dict)
                    or grp not in profile.groups
                    or not isinstance(profile.groups[grp], dict)
                    or subk not in profile.groups[grp]
                ):
                    issues.append(
                        ValidationIssue(
                            field="changed_keys",
                            code="KEY_NOT_FOUND",
                            message=f"Changed key '{k}' not found in groups",
                        )
                    )

    if issues:
        is_recoverable = all(
            iss.code not in ("VERSION_MISMATCH", "MISSING_PROFILE", "UNKNOWN_GROUP", "UNKNOWN_KEY")
            for iss in issues
        )
        error = ErrorInfo(
            code="PROFILE_INVALID",
            message="; ".join(iss.message for iss in issues[:3]),
            node="VALIDATE_PROFILE",
            recoverable=is_recoverable,
        )
        validation = ValidationResult(status="INVALID", issues=issues)
        return {"validation": validation, "error": error, "trace": trace}

    issue = ValidationIssue(
        field="profile_ref",
        code="WRITER_UNAVAILABLE",
        message="Profile serializer and persistent writer are not connected",
    )
    return {
        "validation": ValidationResult(status="INVALID", issues=[issue]),
        "error": ErrorInfo(
            code="PROFILE_WRITE_FAILED",
            message=issue.message,
            node="VALIDATE_PROFILE",
            recoverable=False,
        ),
        "trace": trace,
    }


@lru_cache(maxsize=1)
def _arp_schema_keys() -> dict[str, frozenset[str]]:
    """Read the project's checked-in key inventory until T19 supplies a validator."""
    schema_path = FilePath(__file__).resolve().parents[3] / "docs" / "arp_schema.md"
    if not schema_path.is_file():
        return {}
    groups: dict[str, set[str]] = {}
    group = None
    for line in schema_path.read_text(encoding="utf-8").splitlines():
        heading = re.fullmatch(r"## \[(.+)]", line.strip())
        if heading:
            group = heading.group(1)
            groups[group] = set()
        elif group:
            key = re.fullmatch(r"- `([^`]+)`.*", line.strip())
            if key:
                groups[group].add(key.group(1))
    return {name: frozenset(keys) for name, keys in groups.items()}


def render_node(state: AgentState) -> dict[str, Any]:
    """Invoke ART-cli headless renderer."""
    return _unavailable(state, "RENDER")


def repair_profile_node(state: AgentState) -> dict[str, Any]:
    """Repair recoverable profile defects."""
    return _unavailable(state, "REPAIR_PROFILE")


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
        error = ErrorInfo(
            code="CONTRACT_VIOLATION",
            message="Step ended without an answer, render result, or error",
            node="ADVANCE",
            recoverable=False,
        )
        status = "FAILED"

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
    succeeded = [r for r in step_results if r.status == "SUCCEEDED"]
    failed = [r for r in step_results if r.status in ("FAILED", "BLOCKED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE")]
    has_failure = bool(error) or len(failed) > 0

    if error and error.code in ("CANCELLED", "OUT_OF_SCOPE"):
        status = ResponseStatus(error.code).value
        msg = error.message
    elif state.get("clarification") and not error:
        status = ResponseStatus.WAITING_CLARIFICATION.value
        msg = state["clarification"].question
    elif len(succeeded) > 0 and has_failure:
        status = ResponseStatus.PARTIAL.value
        msg = f"일부 단계만 완료되었습니다. ({error.message if error else '후속 단계 실패'})"
    elif len(succeeded) == len(step_results) and not error and step_results:
        status = ResponseStatus.COMPLETED.value
        msg = "요청된 모든 단계가 성공적으로 완료되었습니다."
    elif error:
        if error.code == "OUT_OF_SCOPE":
            status = ResponseStatus.OUT_OF_SCOPE.value
        elif error.code == "CANCELLED":
            status = ResponseStatus.CANCELLED.value
        elif error.code == "UNSUPPORTED":
            status = ResponseStatus.UNSUPPORTED.value
        elif error.code == "INSUFFICIENT_EVIDENCE":
            status = ResponseStatus.INSUFFICIENT_EVIDENCE.value
        else:
            status = ResponseStatus.FAILED.value
        msg = error.message
    elif any(r.status == "UNSUPPORTED" for r in step_results):
        status = ResponseStatus.UNSUPPORTED.value
        msg = "지원되지 않는 요청입니다."
    elif any(r.status == "INSUFFICIENT_EVIDENCE" for r in step_results):
        status = ResponseStatus.INSUFFICIENT_EVIDENCE.value
        msg = "근거가 부족하여 답변할 수 없습니다."
    elif not step_results:
        status = ResponseStatus.COMPLETED.value
        msg = "완료되었습니다."
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
