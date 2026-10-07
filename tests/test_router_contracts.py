"""Regression checks for the router's externally visible state contract."""

from pathlib import Path as FilePath
import sys

sys.path.insert(0, str(FilePath(__file__).resolve().parents[1] / "src"))

from artagent.graph import (
    AssetRef,
    AnswerResult,
    ErrorInfo,
    IntentSignals,
    OutputSpec,
    Path,
    PlanStep,
    ProfileData,
    RequestContext,
    RequestInput,
    ResponseStatus,
    ResumeInput,
    RuntimeCapabilities,
    RouteDecision,
    StepResult,
    create_router_graph,
    route_request,
)
from artagent.graph.nodes import respond_node
from artagent.graph.nodes import validate_profile_node
from artagent.graph.nodes import check_exec_node
from artagent.graph.nodes import advance_node
from artagent.graph.graph import (
    route_after_check_exec,
    route_after_render,
    route_after_validate_profile,
)
from artagent.graph import RenderResult, ValidationResult, Clarification


def test_waiting_without_reply_keeps_the_same_question_count():
    graph = create_router_graph()
    state = graph.invoke({"request": RequestInput("wait", "사진이 너무 노래요. 좀 봐주세요.")})
    clarification_id = state["clarification"].id

    for _ in range(3):
        state = graph.invoke(state)
        assert state["response"].status == ResponseStatus.WAITING_CLARIFICATION.value
        assert state["clarification"].id == clarification_id
        assert state["clarification_count"] == 1


def test_raw_clarification_stops_after_second_unresolved_reply():
    graph = create_router_graph()
    state = graph.invoke({
        "request": RequestInput("raw_wait", "노출을 +0.7 EV로 보정해서 JPEG로 저장해줘."),
        "capabilities": RuntimeCapabilities(
            search_ready=True, profile_ready=True, render_ready=True
        ),
    })
    assert state["response"].status == ResponseStatus.WAITING_CLARIFICATION.value
    assert state["clarification_count"] == 1

    state["resume"] = ResumeInput("raw_wait", state["clarification"].id, "모르겠어요")
    state = graph.invoke(state)
    assert state["response"].status == ResponseStatus.WAITING_CLARIFICATION.value
    assert state["clarification_count"] == 2

    state["resume"] = ResumeInput("raw_wait", state["clarification"].id, "여전히 모르겠어요")
    state = graph.invoke(state)
    assert state["response"].status == ResponseStatus.FAILED.value
    assert state["error"].code == "CLARIFICATION_UNRESOLVED"
    assert "RENDER" not in state["trace"]


def test_old_clarification_id_cannot_answer_a_new_question():
    graph = create_router_graph()
    state = graph.invoke({"request": RequestInput("retry", "사진이 너무 노래요. 좀 봐주세요.")})
    first_id = state["clarification"].id
    state["resume"] = ResumeInput("retry", first_id, "아직 모르겠어요")
    state = graph.invoke(state)
    assert state["clarification_count"] == 2
    assert state["clarification"].id != first_id

    state["resume"] = ResumeInput("retry", first_id, "설명만 해줘")
    state = graph.invoke(state)
    assert state["response"].status == ResponseStatus.FAILED.value
    assert state["response"].error.code == "INVALID_INPUT"


def test_resume_without_an_active_clarification_is_rejected():
    graph = create_router_graph()
    state = graph.invoke({
        "request": RequestInput("no_wait", "화이트밸런스 원리를 알려줘"),
        "resume": ResumeInput("other", "unknown", "파일입니다"),
    })
    assert state["response"].status == ResponseStatus.FAILED.value
    assert state["response"].error.code == "INVALID_INPUT"
    assert "SEARCH_RAWPEDIA" not in state["trace"]


def test_cancellation_preserves_completed_steps_and_cancelled_status():
    completed = StepResult("step_1", Path.DOC_QA, "SUCCEEDED")
    response = respond_node({
        "request": RequestInput("cancel", "질문"),
        "step_results": {completed.step_id: completed},
        "error": ErrorInfo("CANCELLED", "취소됨", "CLARIFY"),
    })["response"]
    assert response.status == ResponseStatus.CANCELLED.value
    assert response.completed_steps == [completed]


def test_completed_plan_step_is_not_run_again_when_routing_resumes():
    graph = create_router_graph()
    request = RequestInput("resume_plan", "화이트밸런스 어떻게 조절하고 바로 이 사진에 적용해줘.")
    completed = StepResult("resume_plan_step_1", Path.DOC_QA, "SUCCEEDED")
    state = graph.invoke({
        "request": request,
        "cursor": 1,
        "step_results": {completed.step_id: completed},
        "capabilities": RuntimeCapabilities(
            search_ready=True, profile_ready=True, render_ready=True
        ),
    })
    assert "SEARCH_RAWPEDIA" not in state["trace"]
    assert state["response"].status == ResponseStatus.WAITING_CLARIFICATION.value
    assert state["step_results"][completed.step_id] == completed


def test_default_graph_never_reports_unconnected_search_as_success():
    graph = create_router_graph()
    state = graph.invoke({"request": RequestInput("unconnected", "화이트밸런스 원리를 알려줘")})
    assert state["response"].status == ResponseStatus.FAILED.value
    assert state["step_results"]["unconnected_step_1"].error.code == "CAPABILITY_UNAVAILABLE"
    assert state["response"].citations == []
    assert state["response"].artifacts == []


def test_ready_flags_alone_do_not_fabricate_search_or_render_results():
    graph = create_router_graph()
    ready = RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True)
    docs = graph.invoke({
        "request": RequestInput("ready_docs", "화이트밸런스 원리를 알려줘"),
        "capabilities": ready,
    })
    assert docs["response"].status == ResponseStatus.FAILED.value
    assert docs["response"].citations == []
    assert docs["step_results"]["ready_docs_step_1"].error.code == "CAPABILITY_UNAVAILABLE"

    photo = graph.invoke({
        "request": RequestInput(
            "ready_photo", "이 사진 노출을 +0.5 EV로 보정해서 JPEG로 저장해줘",
            assets=[AssetRef("raw", "RAW", "data/sample.raw")],
            context=RequestContext(
                confirmed_goal="노출 +0.5 EV 보정",
                output=OutputSpec("JPEG", "result.jpg"),
            ),
        ),
        "capabilities": ready,
    })
    assert photo["response"].status == ResponseStatus.FAILED.value
    assert photo["response"].artifacts == []
    assert photo["step_results"]["ready_photo_step_1"].error.code == "CAPABILITY_UNAVAILABLE"
    assert "RENDER" not in photo["trace"]


def test_unknown_profile_group_and_key_are_not_accepted_as_valid():
    for profile in (
        ProfileData(groups={"InventedGroup": {"Magic": 1}}, changed_keys=["InventedGroup.Magic"]),
        ProfileData(groups={"Exposure": {"Magic": 1}}, changed_keys=["Exposure.Magic"]),
    ):
        result = validate_profile_node({"profile": profile, "capabilities": RuntimeCapabilities()})
        assert result["validation"].status == "INVALID"
        assert result["error"].code == "PROFILE_INVALID"

    known = validate_profile_node({
        "profile": ProfileData(
            groups={"Exposure": {"Compensation": 0.5}},
            changed_keys=["Exposure.Compensation"],
        ),
        "capabilities": RuntimeCapabilities(),
    })
    assert known["validation"].status == "INVALID"
    assert known["validation"].profile_ref is None
    assert known["error"].code == "PROFILE_WRITE_FAILED"


def _execution_state(assets, goal=None, output=None, answer=None, target_raw_id=None):
    step = PlanStep("exec_step", Path.EXECUTE, "보정해서 저장해줘")
    return {
        "request": RequestInput(
            "exec", "이 사진을 보정해서 JPEG로 저장해줘",
            assets=assets,
            context=RequestContext(
                target_raw_id=target_raw_id, confirmed_goal=goal, output=output
            ),
        ),
        "decision": RouteDecision(primary_path=Path.EXECUTE, plan=[step]),
        "signals": IntentSignals(wants_execute=True),
        "cursor": 0,
        "answer": answer,
    }


def test_execution_requires_one_real_raw_and_explicit_goal_and_output():
    raw_a = AssetRef("a", "RAW", "a.raw")
    raw_b = AssetRef("b", "RAW", "b.raw")
    output = OutputSpec("JPEG", "result.jpg")

    multiple = check_exec_node(_execution_state([raw_a, raw_b], "중립 WB", output))
    assert multiple["clarification"] is not None
    assert "raw" in multiple["clarification"].missing_fields

    invented = check_exec_node(_execution_state([], "중립 WB", output, target_raw_id="missing"))
    assert invented["clarification"] is not None
    assert "execution" not in invented

    no_goal = check_exec_node(_execution_state([raw_a], output=output))
    assert no_goal["clarification"] is not None
    assert "confirmed_goal" in no_goal["clarification"].missing_fields

    no_destination = check_exec_node(_execution_state([raw_a], "중립 WB", OutputSpec("JPEG")))
    assert no_destination["clarification"] is not None
    assert "output" in no_destination["clarification"].missing_fields

    ready = check_exec_node(_execution_state([raw_a], "중립 WB", output))
    assert ready["execution"].raw == raw_a
    assert ready["execution"].goal == "중립 WB"
    assert ready["execution"].output.destination == "result.jpg"


def test_dependent_execution_needs_actionable_workaround():
    raw = AssetRef("raw", "RAW", "a.raw")
    state = _execution_state(
        [raw], output=OutputSpec("JPEG", "result.jpg"),
        answer=AnswerResult(status="SUPPORTED", text="앱 재설치 필요"),
    )
    state["decision"].plan[0].requires = ["troubleshoot_step"]
    state["step_results"] = {
        "troubleshoot_step": StepResult(
            "troubleshoot_step", Path.TROUBLESHOOT, "SUCCEEDED", answer=state["answer"]
        )
    }
    result = check_exec_node(state)
    assert result["error"].code == "DEPENDENCY_UNSATISFIED"
    assert "execution" not in result


def test_quoted_command_is_guidance_not_execution():
    decision, clarification = route_request(RequestInput(
        "quoted", "문서에 '이 사진을 보정해줘'라고 쓰여 있는데 이 문장의 의미가 무엇인가요?"
    ))
    assert clarification is None
    assert decision.primary_path == Path.DOC_QA
    assert [step.path for step in decision.plan] == [Path.DOC_QA]


def test_three_purposes_preserve_all_steps_and_dependent_guide():
    decision, clarification = route_request(RequestInput(
        "triple",
        "ART가 크래시 나는데 해결법을 확인해주고, 화이트밸런스 조절 방법도 알려주고, "
        "이 RAW에 노출 +0.5 EV를 적용해줘.",
    ))
    assert clarification is None
    assert [step.path for step in decision.plan] == [
        Path.TROUBLESHOOT, Path.DOC_QA, Path.EXECUTE
    ]

    dependent, _ = route_request(RequestInput(
        "dependent", "화이트밸런스 어떻게 조절하고 그 설정 그대로 이 사진에 적용해줘"
    ))
    assert [step.path for step in dependent.plan] == [Path.DOC_QA, Path.EXECUTE]
    assert dependent.plan[0].step_id in dependent.plan[1].requires


def test_conflicting_global_exposure_goals_ask_for_clarification():
    decision, clarification = route_request(RequestInput(
        "conflict", "이 사진을 전체적으로 밝게 보정해줘. 동시에 전체 노출은 낮춰서 저장해줘"
    ))
    assert clarification is not None
    assert decision.plan == []

    graph = create_router_graph()
    state = graph.invoke({
        "request": RequestInput(
            "conflict", "이 사진을 전체적으로 밝게 보정해줘. 동시에 전체 노출은 낮춰서 저장해줘"
        ),
        "capabilities": RuntimeCapabilities(True, True, True),
    })
    state["resume"] = ResumeInput("conflict", state["clarification"].id, "전체 노출을 밝게 해줘")
    state = graph.invoke(state)
    assert state["decision"].primary_path == Path.EXECUTE
    assert state["signals"].goal == "전체 노출 밝게 보정"
    assert state["clarification"].missing_fields == ["raw"]


def test_clarification_of_distinct_execution_fields_resets_question_budget():
    graph = create_router_graph()
    ready = RuntimeCapabilities(search_ready=True, profile_ready=True, render_ready=True)
    state = graph.invoke({
        "request": RequestInput("fields", "이 사진을 보정해서 JPEG로 저장해줘"),
        "capabilities": ready,
    })
    assert state["clarification"].missing_fields == ["raw"]
    assert state["clarification_count"] == 1

    state["resume"] = ResumeInput(
        "fields", state["clarification"].id, "", [AssetRef("raw", "RAW", "input.raw")]
    )
    state = graph.invoke(state)
    assert state["clarification"].missing_fields == ["confirmed_goal"]
    assert state["clarification_count"] == 1

    state["resume"] = ResumeInput("fields", state["clarification"].id, "노출 +0.5 EV로 보정해줘")
    state = graph.invoke(state)
    assert state["clarification"].missing_fields == ["output"]
    assert state["clarification_count"] == 1

    state["resume"] = ResumeInput("fields", state["clarification"].id, "result.jpg로 저장해줘")
    state = graph.invoke(state)
    assert state["execution"].output.destination == "result.jpg"
    assert state["response"].status == ResponseStatus.FAILED.value
    assert state["error"] is None
    assert state["step_results"]["fields_step_1"].error.code == "CAPABILITY_UNAVAILABLE"


def test_conflicting_success_and_error_never_proceeds():
    error = ErrorInfo("CONTRACT_VIOLATION", "inconsistent", "TEST")
    assert route_after_validate_profile({
        "validation": ValidationResult("VALID", profile_ref="fake.arp"), "error": error,
    }) == "FALLBACK"
    assert route_after_render({
        "render": RenderResult("SUCCEEDED", output_path="fake.jpg", output_verified=True),
        "error": error,
    }) == "FALLBACK"
    assert route_after_check_exec({
        "clarification": Clarification("id", "question"), "error": error,
    }) == "FALLBACK"


def test_advance_without_a_result_records_contract_violation():
    step = PlanStep("empty", Path.DOC_QA, "question")
    result = advance_node({
        "decision": RouteDecision(primary_path=Path.DOC_QA, plan=[step]),
        "cursor": 0,
    })["step_results"]["empty"]
    assert result.status == "FAILED"
    assert result.error.code == "CONTRACT_VIOLATION"
