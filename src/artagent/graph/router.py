"""Router logic and intent classification for ART Master Agent.

Implements rules R1~R8 from docs/langgraph_router_design.md.
"""

from __future__ import annotations

import re
from typing import Optional

from .state import (
    Clarification,
    IntentSignals,
    Path,
    PlanStep,
    RequestContext,
    RequestInput,
    RouteDecision,
    StepResult,
)


def analyze_signals(text: str, context: Optional[RequestContext] = None) -> IntentSignals:
    """Analyze intent signals and rule triggers from the request text."""
    # R8: Check execution negation
    negation_patterns = [
        r"적용하지\s*마",
        r"적용\s*금지",
        r"변경하지\s*마",
        r"파일에는\s*적용하지\s*마",
        r"수정하지\s*마",
        r"설명만\s*해줘",
        r"설명만",
        r"적용하지\s*않",
    ]
    execution_negated = any(re.search(p, text) for p in negation_patterns)

    # R4: Specific ART GitHub Issue / Discussion references
    source_refs = re.findall(
        r"(?:GitHub\s*(?:Issue|Discussion)\s*#\d+|Issue\s*#\d+|Discussion\s*#\d+)",
        text,
        re.IGNORECASE,
    )
    has_github_ref = len(source_refs) > 0

    # R2 vs R5: Software runtime malfunctions vs photographic correction artifacts
    # R2: Abnormal termination, freeze, white display, file access failure, preview not updating
    malfunction_pattern = (
        r"(?:종료돼|종료되|비정상\s*종료|crash|크래시|동결|freeze|멈춤|"
        r"흰\s*화면|흰색으로\s*표시|"
        r"접근하지\s*못할\s*때|접근\s*실패|디스크.*접근|"
        r"미리보기가\s*갱신되지\s*않|미리보기\s*미갱신|설정\s*미반영|반영되지\s*않|"
        r"버그|우회\s*설정|동작\s*오류)"
    )
    has_crash_or_bug = bool(re.search(malfunction_pattern, text))

    # R3: Explicit command to apply adjustments or save rendered image
    has_exec_cmd = False
    if not execution_negated:
        exec_pattern = (
            r"(?:적용해줘|적용해\s*줘|"
            r"저장해줘|저장해\s*줘|"
            r"보정해줘|보정해\s*줘|"
            r"생성해줘|생성해\s*줘|"
            r"렌더링해줘|렌더링해\s*줘)"
        )
        has_exec_cmd = bool(re.search(exec_pattern, text))

    # Check for informational phrasing (R8 questions: how-to, why, principle)
    is_info_question = bool(
        re.search(
            r"(?:방법은|방법과|절차는|방식은|차이는|이유는|무엇인가요|어떻게\s*동작하나요|어떤\s*옵션|어떻게\s*조절|설명만|설명해|알려줘)",
            text,
        )
    )

    # R7: Ambiguity detection
    is_ambiguous = False
    ambiguous_reasons: list[str] = []
    if not has_exec_cmd and not is_info_question and not has_github_ref and not has_crash_or_bug:
        if re.search(r"(?:노래요|어두워요|이상해요|밝아요)", text) and re.search(
            r"(?:봐주세요|봐줘|어때요)", text
        ):
            is_ambiguous = True
            ambiguous_reasons.append("AMBIGUOUS_GUIDE_OR_EXECUTION")

    # Composite doc guide signals
    has_explicit_doc = bool(
        re.search(
            r"(?:어떻게\s*조절하고|조절\s*방법도\s*알려주고|방법도\s*알려주고|알려주고)",
            text,
        )
    )

    wants_troubleshoot = has_github_ref or has_crash_or_bug
    wants_execute = has_exec_cmd and not execution_negated

    wants_doc = False
    if not is_ambiguous:
        if has_explicit_doc or (not wants_troubleshoot and not wants_execute):
            wants_doc = True

    # Extract goal if present
    goal = None
    if wants_execute:
        goal_match = re.search(r"([^\.\,\n]+(?:보정|맞춰|적용))", text)
        if goal_match:
            goal = goal_match.group(1).strip()
        elif context and context.confirmed_goal:
            goal = context.confirmed_goal

    return IntentSignals(
        wants_doc=wants_doc,
        wants_troubleshoot=wants_troubleshoot,
        wants_execute=wants_execute,
        execution_negated=execution_negated,
        ambiguous_reasons=ambiguous_reasons,
        source_refs=source_refs,
        goal=goal,
        constraints=[],
    )


def route_request(
    request: RequestInput,
    completed_steps: Optional[dict[str, StepResult]] = None,
) -> tuple[RouteDecision, Optional[Clarification]]:
    """Determine routing decision and optional clarification based on request."""
    text = request.text.strip()
    signals = analyze_signals(text, request.context)

    # Empty text or out of scope validation
    if not text:
        decision = RouteDecision(
            primary_path=None,
            candidate_paths=[],
            reason_codes=["EMPTY_INPUT"],
            plan=[],
        )
        return decision, None

    # R7: Ambiguous intent -> Clarification
    if len(signals.ambiguous_reasons) > 0:
        candidates = [Path.DOC_QA, Path.EXECUTE]
        clarification = Clarification(
            id=f"clarify_{request.request_id}",
            question="조절 방법 안내를 원하시나요, 이 사진의 보정 결과 생성을 원하시나요?",
            missing_fields=["confirmed_goal"],
            candidate_paths=candidates,
            origin="ROUTE",
        )
        decision = RouteDecision(
            primary_path=None,
            candidate_paths=candidates,
            reason_codes=["R7_AMBIGUOUS_PURPOSE"],
            plan=[],
        )
        return decision, clarification

    # Extract sub-clauses for composite queries
    # R3 / R6: Execute requests (Primary = P3)
    if signals.wants_execute:
        primary = Path.EXECUTE
        plan: list[PlanStep] = []
        reason_codes = ["R3_EXECUTION"]

        if signals.wants_troubleshoot:
            # Composite P2 -> P3 (e.g. M02)
            # P3 depends on P2 workaround/fix
            step_tb = PlanStep(
                step_id=f"{request.request_id}_step_1",
                path=Path.TROUBLESHOOT,
                query=_extract_troubleshoot_subquery(text),
                requires=[],
            )
            step_ex = PlanStep(
                step_id=f"{request.request_id}_step_2",
                path=Path.EXECUTE,
                query=_extract_execute_subquery(text),
                requires=[step_tb.step_id],
            )
            plan = [step_tb, step_ex]
            reason_codes.extend(["R2_MALFUNCTION", "R6_COMPOSITE_P2_P3"])
        elif signals.wants_doc:
            # Composite P1 -> P3 (e.g. M01)
            # Goal is independently confirmed, so P3 requires=[]
            step_doc = PlanStep(
                step_id=f"{request.request_id}_step_1",
                path=Path.DOC_QA,
                query=_extract_doc_subquery(text),
                requires=[],
            )
            step_ex = PlanStep(
                step_id=f"{request.request_id}_step_2",
                path=Path.EXECUTE,
                query=_extract_execute_subquery(text),
                requires=[],
            )
            plan = [step_doc, step_ex]
            reason_codes.extend(["R1_USAGE", "R6_COMPOSITE_P1_P3"])
        else:
            # Pure execution (e.g. M04)
            step_ex = PlanStep(
                step_id=f"{request.request_id}_step_1",
                path=Path.EXECUTE,
                query=text,
                requires=[],
            )
            plan = [step_ex]

        decision = RouteDecision(
            primary_path=primary,
            candidate_paths=[primary],
            reason_codes=reason_codes,
            plan=plan,
        )
        return decision, None

    # R2 / R4 / R6: Troubleshooting requests
    if signals.wants_troubleshoot:
        primary = Path.TROUBLESHOOT
        reason_codes = ["R2_MALFUNCTION" if not signals.source_refs else "R4_SPECIFIED_REFERENCE"]

        if signals.wants_doc and _has_explicit_doc_clause(text):
            # Composite P2 -> P1 (e.g. M05)
            # Independent guide, so P1 requires=[]
            step_tb = PlanStep(
                step_id=f"{request.request_id}_step_1",
                path=Path.TROUBLESHOOT,
                query=_extract_troubleshoot_subquery(text),
                requires=[],
            )
            step_doc = PlanStep(
                step_id=f"{request.request_id}_step_2",
                path=Path.DOC_QA,
                query=_extract_doc_subquery(text),
                requires=[],
            )
            plan = [step_tb, step_doc]
            reason_codes.extend(["R1_USAGE", "R6_COMPOSITE_P2_P1"])
            if signals.execution_negated:
                reason_codes.append("R8_EXECUTION_NEGATED")
        else:
            step_tb = PlanStep(
                step_id=f"{request.request_id}_step_1",
                path=Path.TROUBLESHOOT,
                query=text,
                requires=[],
            )
            plan = [step_tb]

        decision = RouteDecision(
            primary_path=primary,
            candidate_paths=[primary],
            reason_codes=reason_codes,
            plan=plan,
        )
        return decision, None

    # R1 / R5: Pure Doc QA requests
    step_doc = PlanStep(
        step_id=f"{request.request_id}_step_1",
        path=Path.DOC_QA,
        query=text,
        requires=[],
    )
    decision = RouteDecision(
        primary_path=Path.DOC_QA,
        candidate_paths=[Path.DOC_QA],
        reason_codes=["R1_CONCEPT_OR_USAGE"],
        plan=[step_doc],
    )
    return decision, None


def _has_explicit_doc_clause(text: str) -> bool:
    return bool(
        re.search(
            r"(?:어떻게\s*조절하고|조절\s*방법도\s*알려주고|방법도\s*알려주고|알려주고)",
            text,
        )
    )


def _extract_doc_subquery(text: str) -> str:
    m = re.search(r"([^,\.]*(?:조절하고|알려주고|방법|원리)[^,\.]*)", text)
    if m:
        return m.group(1).strip()
    return text


def _extract_troubleshoot_subquery(text: str) -> str:
    m = re.search(r"([^,\.]*(?:종료돼|크래시|동결|원인|버그|우회\s*설정)[^,\.]*)", text)
    if m:
        return m.group(1).strip()
    return text


def _extract_execute_subquery(text: str) -> str:
    m = re.search(r"([^,\.]*(?:적용해줘|저장해줘|보정해줘|생성해줘)[^,\.]*)", text)
    if m:
        return m.group(1).strip()
    return text
