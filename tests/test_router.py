"""Unit and integration tests for LangGraph router and execution graph.

Verifies the 20 benchmark queries and state transition contracts from docs/langgraph_router_design.md.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Optional

import pytest

# Ensure src/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from artagent.graph import (
    AgentState,
    AssetRef,
    ErrorInfo,
    OutputSpec,
    Path as AgentPath,
    PlanStep,
    RequestContext,
    RequestInput,
    ResponseStatus,
    ResumeInput,
    RouteDecision,
    RuntimeCapabilities,
    StepResult,
    analyze_signals,
    create_router_graph,
    route_request,
)


# 20 benchmark test cases defined in docs/langgraph_router_design.md Sections 7.2 and 7.3
BENCHMARK_CASES = [
    # 01
    {
        "id": "Q001",
        "text": "RawPedia 설명에서 Auto Levels는 무엇을 분석해 Exposure 설정을 조정하나요?",
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 02
    {
        "id": "Q008",
        "text": (
            "Tone Mapping 적용 후 만화 같은 과장된 외관(cartoonish appearance)이나 "
            "소프트 후광 문제가 발생할 때 어떤 옵션 값을 올려야 하나요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 03
    {
        "id": "Q010",
        "text": (
            "Local Contrast 도구에서 Darkness Level과 Lightness Level 슬라이더는 각각 어떤 영역을 변경하며, "
            "둘 다 0으로 설정하면 도구는 어떻게 동작하나요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 04
    {
        "id": "Q017",
        "text": "White Balance 도구의 temperature 슬라이더는 어떤 색상 축을 기준으로 이미지를 조절하나요?",
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 05
    {
        "id": "Q018",
        "text": (
            "RAW 이미지에서 화이트 밸런스가 RGB 채널 가중치로 변환될 때 클리핑 제어 방식과, "
            "Temperature correlation 알고리즘이 잘못된 결과를 낼 수 있는 조명 조건은 무엇인가요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 06
    {
        "id": "Q036",
        "text": "Dual Demosaic 방식(예: AMaZE+VNG4)의 영역 분할 장점과 연산상의 단점은 무엇인가요?",
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 07
    {
        "id": "Q051",
        "text": (
            "Noise Reduction 도구에서 휘도 노이즈(Luminance noise)와 색상 노이즈(Chrominance noise)에 대한 "
            "시각적 특성과 제거 필요성의 차이는 무엇인가요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 08
    {
        "id": "Q063",
        "text": "Spot Removal 도구에서 새로운 스팟을 추가할 때 마우스 조작 방법(Ctrl-click 및 드래그)은 무엇인가요?",
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 09
    {
        "id": "Q072",
        "text": (
            "RawTherapee에서 부분 처리 프로필(partial profile)을 적용할 때 Fill 모드와 Preserve 모드의 "
            "동작 차이 및 누락된 파라미터 처리 방식은 무엇인가요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 10
    {
        "id": "Q077",
        "text": (
            "범용으로 재사용 가능한 처리 프로필을 만들 때 필요한 파라미터만 부분 저장(Ctrl+Save)하는 방법과, "
            "다양한 사진 간 호환성을 위해 노출값 대신 Auto Levels 사용 및 불필요한 설정(WB, 노이즈 감소 등) 배제를 권장하는 이유는 무엇인가요?"
        ),
        "primary_path": AgentPath.DOC_QA,
        "plan": [AgentPath.DOC_QA],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 11
    {
        "id": "Q084",
        "text": (
            "GitHub Discussion #424 설명 기준, ART의 Film Simulation에서 LUT가 점 단위(point-wise) 연산만 지원하여 "
            "halation과 grain을 직접 포함하지 못하는 기술적 이유와 ART 내의 대체 도구 경로는 무엇인가요?"
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 12
    {
        "id": "Q089",
        "text": (
            "GitHub Discussion #494에서 Fedora 환경의 Flatpak 패키지로 설치한 ART가 홈 디렉토리 외의 "
            "로컬 디스크 드라이브에 접근하지 못할 때 제시된 의심 원인과 검증된 해결 방법은 무엇인가요?"
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 13
    {
        "id": "Q092",
        "text": (
            "GitHub Issue #516에서 Canon EOS R8 RAW 파일이 흰색으로 표시될 때 구형 빌드 스크립트로 생성한 "
            "자가 빌드와 AppImage 간의 동작 차이 및 썸네일 정상화를 위해 확인된 조치는 무엇인가요?"
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 14
    {
        "id": "Q095",
        "text": (
            "GitHub Issue #524에서 스팟 제거 활성화 후 100% 확대 시 발생하는 동결/크래시 버그의 "
            "구체적인 재현 절차와 개발자가 안내한 Debug 빌드 생성 옵션은 무엇인가요?"
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 15
    {
        "id": "Q096",
        "text": (
            "GitHub Issue #500 설명 기준으로, ART의 내보내기 대화상자에서 JPEG XL(JXL) 전용 품질 슬라이더를 "
            "활성화하여 압축 품질을 50으로 직접 설정하는 절차는 무엇인가요?"
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
    # 16 (M01: Guide + Execute)
    {
        "id": "M01",
        "text": "화이트밸런스 어떻게 조절하고 바로 이 사진에 적용해줘.",
        "primary_path": AgentPath.EXECUTE,
        "plan": [AgentPath.DOC_QA, AgentPath.EXECUTE],
        "first_branch": "SEARCH_RAWPEDIA",
        "needs_clarify": False,
        "assets": [AssetRef(asset_id="raw_m01", kind="RAW", path="data/sample.raw")],
        "context": RequestContext(confirmed_goal="중립 WB", output=OutputSpec(format="JPEG")),
    },
    # 17 (M02: Troubleshoot + Execute)
    {
        "id": "M02",
        "text": (
            "이 RAW에 노이즈 감소를 켜면 ART가 종료돼. 관련 보고와 우회 설정을 확인한 뒤 "
            "그 설정을 적용해 JPEG로 저장해줘."
        ),
        "primary_path": AgentPath.EXECUTE,
        "plan": [AgentPath.TROUBLESHOOT, AgentPath.EXECUTE],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [AssetRef(asset_id="raw_m02", kind="RAW", path="data/sample.raw")],
        "context": RequestContext(output=OutputSpec(format="JPEG")),
    },
    # 18 (M03: Ambiguous)
    {
        "id": "M03",
        "text": "사진이 너무 노래요. 좀 봐주세요.",
        "primary_path": None,
        "plan": [],
        "first_branch": "CLARIFY",
        "needs_clarify": True,
        "assets": [AssetRef(asset_id="raw_m03", kind="RAW", path="data/sample.raw")],
        "context": None,
    },
    # 19 (M04: Execute with missing RAW asset)
    {
        "id": "M04",
        "text": "노출을 +0.7 EV로 보정해서 JPEG로 저장해줘.",
        "primary_path": AgentPath.EXECUTE,
        "plan": [AgentPath.EXECUTE],
        "first_branch": "CHECK_EXEC",
        "needs_clarify": True,
        "assets": [],
        "context": RequestContext(output=OutputSpec(format="JPEG")),
    },
    # 20 (M05: Troubleshoot + Guide, Execution Negated)
    {
        "id": "M05",
        "text": (
            "화이트밸런스 조절 방법도 알려주고, ART에서 값을 바꿔도 미리보기가 갱신되지 않는 원인을 확인해줘. "
            "파일에는 적용하지 마."
        ),
        "primary_path": AgentPath.TROUBLESHOOT,
        "plan": [AgentPath.TROUBLESHOOT, AgentPath.DOC_QA],
        "first_branch": "SEARCH_GITHUB",
        "needs_clarify": False,
        "assets": [],
        "context": None,
    },
]


@pytest.fixture(scope="module")
def router_graph():
    """Compile and reuse the router graph for testing."""
    return create_router_graph()


def test_20_benchmark_queries_accuracy(router_graph):
    """Verify that routing decision and first branch match with >= 90% accuracy."""
    total = len(BENCHMARK_CASES)
    passed = 0
    failures = []

    for case in BENCHMARK_CASES:
        req = RequestInput(
            request_id=f"req_{case['id']}",
            text=case["text"],
            assets=case["assets"],
            context=case["context"],
        )

        # 1. Routing decision check
        decision, clarify = route_request(req)

        # 2. Graph execution to verify first branch
        initial_state: AgentState = {
            "request": req,
            "capabilities": RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True),
        }
        res = router_graph.invoke(initial_state)
        trace = res.get("trace", [])

        # Find first task or clarify node visited after ROUTE
        route_idx = trace.index("ROUTE") if "ROUTE" in trace else -1
        first_branch = None
        for node in trace[route_idx + 1:]:
            if node in ("SEARCH_RAWPEDIA", "SEARCH_GITHUB", "CHECK_EXEC", "CLARIFY"):
                first_branch = node
                break

        # Verification items
        primary_match = (decision.primary_path == case["primary_path"])
        plan_match = ([p.path for p in decision.plan] == case["plan"])
        branch_match = (first_branch == case["first_branch"])
        clarify_match = (bool(clarify or res.get("clarification")) == case["needs_clarify"])

        all_matched = primary_match and plan_match and branch_match and clarify_match
        if all_matched:
            passed += 1
        else:
            failures.append(
                f"[{case['id']}] primary={decision.primary_path} (exp: {case['primary_path']}), "
                f"plan={[p.path for p in decision.plan]} (exp: {case['plan']}), "
                f"branch={first_branch} (exp: {case['first_branch']}), "
                f"clarify={bool(clarify)} (exp: {case['needs_clarify']})"
            )

    accuracy = passed / total
    assert accuracy >= 0.90, f"Routing accuracy {accuracy*100:.1f}% below 90%. Failures: {failures}"
    assert passed == 20, f"Expected 20/20 benchmark queries to pass, got {passed}/20. Failures: {failures}"


def test_m02_dependency_rule():
    """Verify that M02 has P3 step explicitly depending on P2 step."""
    case_m02 = next(c for c in BENCHMARK_CASES if c["id"] == "M02")
    req = RequestInput(
        request_id="test_m02",
        text=case_m02["text"],
        assets=case_m02["assets"],
        context=case_m02["context"],
    )
    decision, clarify = route_request(req)

    assert clarify is None
    assert decision.primary_path == AgentPath.EXECUTE
    assert len(decision.plan) == 2
    step_tb, step_ex = decision.plan[0], decision.plan[1]
    assert step_tb.path == AgentPath.TROUBLESHOOT
    assert step_ex.path == AgentPath.EXECUTE
    assert step_tb.step_id in step_ex.requires, "M02 P3 step must require P2 step ID"


def test_m03_ambiguous_purpose_clarification():
    """Verify that M03 triggers ROUTE clarification with empty plan and both candidate paths."""
    case_m03 = next(c for c in BENCHMARK_CASES if c["id"] == "M03")
    req = RequestInput(
        request_id="test_m03",
        text=case_m03["text"],
        assets=case_m03["assets"],
    )
    decision, clarify = route_request(req)

    assert decision.primary_path is None
    assert decision.plan == []
    assert set(decision.candidate_paths) == {AgentPath.DOC_QA, AgentPath.EXECUTE}
    assert clarify is not None
    assert clarify.origin == "ROUTE"
    assert "조절 방법 안내" in clarify.question


def test_m04_missing_raw_clarification(router_graph):
    """Verify that M04 plans P3, but triggers CHECK_EXEC clarification due to missing RAW asset."""
    case_m04 = next(c for c in BENCHMARK_CASES if c["id"] == "M04")
    req = RequestInput(
        request_id="test_m04",
        text=case_m04["text"],
        assets=[],
        context=RequestContext(output=OutputSpec(format="JPEG")),
    )
    decision, clarify = route_request(req)

    # Route decision itself is confirmed P3
    assert decision.primary_path == AgentPath.EXECUTE
    assert [p.path for p in decision.plan] == [AgentPath.EXECUTE]
    assert clarify is None

    # Graph execution reaches CHECK_EXEC which triggers clarification
    res = router_graph.invoke({"request": req})
    assert "CHECK_EXEC" in res["trace"]
    assert "CLARIFY" in res["trace"]
    assert res["clarification"] is not None
    assert res["clarification"].origin == "CHECK_EXEC"
    assert "raw" in res["clarification"].missing_fields
    assert res["response"].status == ResponseStatus.WAITING_CLARIFICATION.value


def test_m05_execution_negation_rule():
    """Verify that M05 negates execution (R8), resulting in P2 primary and P2->P1 independent plan."""
    case_m05 = next(c for c in BENCHMARK_CASES if c["id"] == "M05")
    signals = analyze_signals(case_m05["text"])

    assert signals.execution_negated is True
    assert signals.wants_execute is False
    assert signals.wants_troubleshoot is True
    assert signals.wants_doc is True

    req = RequestInput(request_id="test_m05", text=case_m05["text"])
    decision, clarify = route_request(req)

    assert clarify is None
    assert decision.primary_path == AgentPath.TROUBLESHOOT
    assert [p.path for p in decision.plan] == [AgentPath.TROUBLESHOOT, AgentPath.DOC_QA]
    assert decision.plan[1].requires == [], "M05 P1 step must be independent (requires=[])"


def test_graph_state_transition_p1(router_graph):
    """Verify complete state transition pipeline for a P1 DOC_QA query."""
    req = RequestInput(request_id="test_p1", text="Auto Levels의 보정 원리는 무엇인가요?")
    res = router_graph.invoke({"request": req})

    assert res["trace"] == [
        "INTAKE",
        "ROUTE",
        "DISPATCH",
        "SEARCH_RAWPEDIA",
        "ANSWER",
        "ADVANCE",
        "RESPOND",
    ]
    assert res["response"].status == ResponseStatus.COMPLETED.value
    assert len(res["response"].citations) > 0


def test_graph_state_transition_p2(router_graph):
    """Verify complete state transition pipeline for a P2 TROUBLESHOOT query."""
    req = RequestInput(request_id="test_p2", text="GitHub Issue #516 흰색 화면 표시 버그 해결 방법은 무엇인가요?")
    res = router_graph.invoke({"request": req})

    assert res["trace"] == [
        "INTAKE",
        "ROUTE",
        "DISPATCH",
        "SEARCH_GITHUB",
        "ANSWER",
        "ADVANCE",
        "RESPOND",
    ]
    assert res["response"].status == ResponseStatus.COMPLETED.value
    assert len(res["response"].citations) > 0


def test_graph_state_transition_p3(router_graph):
    """Verify complete state transition pipeline for a P3 EXECUTE query with RAW provided."""
    raw_asset = AssetRef(asset_id="raw_1", kind="RAW", path="data/sample.raw")
    ctx = RequestContext(confirmed_goal="노출 +0.5 EV 보정", output=OutputSpec(format="JPEG"))
    req = RequestInput(
        request_id="test_p3",
        text="노출을 +0.5 EV로 보정해서 JPEG로 저장해줘.",
        assets=[raw_asset],
        context=ctx,
    )
    res = router_graph.invoke({"request": req})

    assert res["trace"] == [
        "INTAKE",
        "ROUTE",
        "DISPATCH",
        "CHECK_EXEC",
        "FEATURES",
        "GENERATE_PROFILE",
        "VALIDATE_PROFILE",
        "RENDER",
        "ADVANCE",
        "RESPOND",
    ]
    assert res["response"].status == ResponseStatus.COMPLETED.value
    assert len(res["response"].artifacts) > 0


def test_clarification_pause_and_resume_to_doc(router_graph):
    """Verify M03 clarification pause followed by user resume answering for doc guidance."""
    req = RequestInput(request_id="test_m03_resume", text="사진이 너무 노래요. 좀 봐주세요.")
    state_paused = router_graph.invoke({"request": req})

    assert state_paused["response"].status == ResponseStatus.WAITING_CLARIFICATION.value
    assert state_paused["clarification"] is not None

    # User resumes with guide request
    state_paused["resume"] = ResumeInput(
        request_id="test_m03_resume",
        clarification_id=state_paused["clarification"].id,
        reply_text="화이트밸런스 어떻게 조절하는지 설명만 해줘",
        assets=[],
    )
    state_resumed = router_graph.invoke(state_paused)

    assert state_resumed["response"].status == ResponseStatus.COMPLETED.value
    assert state_resumed["decision"].primary_path == AgentPath.DOC_QA
    assert "SEARCH_RAWPEDIA" in state_resumed["trace"]


def test_clarification_pause_and_resume_to_exec(router_graph):
    """Verify M04 clarification pause followed by user resume attaching a RAW asset."""
    req = RequestInput(
        request_id="test_m04_resume",
        text="노출을 +0.7 EV로 보정해서 JPEG로 저장해줘.",
        assets=[],
        context=RequestContext(output=OutputSpec(format="JPEG")),
    )
    state_paused = router_graph.invoke({"request": req})
    assert state_paused["response"].status == ResponseStatus.WAITING_CLARIFICATION.value

    # User resumes by providing RAW asset
    state_paused["resume"] = ResumeInput(
        request_id="test_m04_resume",
        clarification_id=state_paused["clarification"].id,
        reply_text="첨부된 RAW 파일을 적용해줘",
        assets=[AssetRef(asset_id="raw_supplied", kind="RAW", path="data/sample.raw")],
    )
    state_resumed = router_graph.invoke(state_paused)

    assert state_resumed["response"].status == ResponseStatus.COMPLETED.value
    assert "RENDER" in state_resumed["trace"]


def test_clarification_cancellation(router_graph):
    """Verify that user cancellation during clarification ends with CANCELLED status."""
    req = RequestInput(request_id="test_cancel", text="사진이 너무 노래요. 좀 봐주세요.")
    state_paused = router_graph.invoke({"request": req})

    state_paused["resume"] = ResumeInput(
        request_id="test_cancel",
        clarification_id=state_paused["clarification"].id,
        reply_text="취소할게요",
        assets=[],
    )
    state_cancelled = router_graph.invoke(state_paused)

    assert state_cancelled["response"].status == ResponseStatus.CANCELLED.value
    assert "FALLBACK" in state_cancelled["trace"]


def test_dependency_blocked_when_prerequisite_fails():
    """Verify DISPATCH sets DEPENDENCY_UNSATISFIED when required step did not succeed."""
    from artagent.graph.nodes import dispatch_node

    s1 = PlanStep("step_tb", AgentPath.TROUBLESHOOT, "check error", [])
    s2 = PlanStep("step_ex", AgentPath.EXECUTE, "render JPEG", requires=["step_tb"])
    decision = RouteDecision(primary_path=AgentPath.EXECUTE, plan=[s1, s2])

    state: AgentState = {
        "decision": decision,
        "cursor": 1,
        "step_results": {
            "step_tb": StepResult(step_id="step_tb", path=AgentPath.TROUBLESHOOT, status="FAILED")
        },
        "capabilities": RuntimeCapabilities(),
    }
    updates = dispatch_node(state)
    assert updates.get("error") is not None
    assert updates["error"].code == "DEPENDENCY_UNSATISFIED"


def test_capability_unavailable_handling():
    """Verify DISPATCH errors with CAPABILITY_UNAVAILABLE when service is flagged not ready."""
    from artagent.graph.nodes import dispatch_node

    s1 = PlanStep("step_1", AgentPath.DOC_QA, "doc query", [])
    decision = RouteDecision(primary_path=AgentPath.DOC_QA, plan=[s1])

    state: AgentState = {
        "decision": decision,
        "cursor": 0,
        "step_results": {},
        "capabilities": RuntimeCapabilities(search_ready=False),
    }
    updates = dispatch_node(state)
    assert updates.get("error") is not None
    assert updates["error"].code == "CAPABILITY_UNAVAILABLE"


def test_invalid_input_rejection(router_graph):
    """Verify INTAKE rejects requests with empty ID or empty text."""
    req = RequestInput(request_id="", text="")
    res = router_graph.invoke({"request": req})

    assert "INTAKE" in res["trace"]
    assert "FALLBACK" in res["trace"]
    assert res["response"].status == ResponseStatus.FAILED.value
    assert res["response"].error.code == "INVALID_INPUT"
