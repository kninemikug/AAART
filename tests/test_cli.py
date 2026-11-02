"""Tests for Task 22 Terminal Chat Minimal REPL (src/artagent/cli.py).

Verifies command-line argument parsing, resource loading validation,
node override behavior (DISPATCH wrapper for EXECUTE, RESEARCH wrapper),
response rendering, REPL loop lifecycle, and graph E2E execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

from artagent.cli import (
    CLARIFICATION_RETRY_MESSAGE,
    EXECUTE_UNSUPPORTED_MESSAGE,
    build_repl_graph,
    create_dispatch_wrapper,
    load_resources,
    main,
    parse_args,
    render_response,
    research_wrapper,
    run_repl,
)
from artagent.graph import (
    AgentState,
    AnswerResult,
    Citation,
    Clarification,
    ErrorInfo,
    Path as AgentPath,
    PlanStep,
    RequestInput,
    ResponseOutput,
    ResponseStatus,
    RouteDecision,
    RuntimeCapabilities,
    StepResult,
)


# =========================================================================
# 1. Argument Parsing Tests
# =========================================================================

def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.reference is None
    assert args.persist_dir is None
    assert args.source_root is None


def test_parse_args_custom() -> None:
    args = parse_args([
        "--reference", "custom_ref.json",
        "--persist-dir", "custom_db",
        "--source-root", "custom_src",
    ])
    assert args.reference == Path("custom_ref.json")
    assert args.persist_dir == Path("custom_db")
    assert args.source_root == Path("custom_src")


# =========================================================================
# 2. Resource Loading & Validation Tests
# =========================================================================

def test_load_resources_explicit_missing_ref_raises(tmp_path: Path) -> None:
    non_existent = tmp_path / "missing_ref.json"
    with pytest.raises(FileNotFoundError, match="지정한 reference 파일이 없습니다"):
        load_resources(reference_path=non_existent)


def test_load_resources_env_missing_ref_no_silent_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T09_REFERENCE_PATH", str(tmp_path / "missing_env_ref.json"))
    with pytest.raises(FileNotFoundError, match="T09_REFERENCE_PATH 파일이 없습니다"):
        load_resources()


def test_load_resources_explicit_missing_persist_dir_raises(tmp_path: Path) -> None:
    ref_file = tmp_path / "ref.json"
    ref_file.write_text("{}", encoding="utf-8")
    non_existent_dir = tmp_path / "missing_db"

    with patch("artagent.cli.load_spec") as mock_load_spec:
        mock_load_spec.return_value = MagicMock()
        with pytest.raises(FileNotFoundError, match="지정한 Chroma persist 디렉터리가 없습니다"):
            load_resources(reference_path=ref_file, persist_dir=non_existent_dir)


def test_load_resources_env_missing_persist_dir_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref_file = tmp_path / "ref.json"
    ref_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("T09_PERSIST_DIR", str(tmp_path / "missing_env_db"))

    with patch("artagent.cli.load_spec") as mock_load_spec:
        mock_load_spec.return_value = MagicMock()
        with pytest.raises(FileNotFoundError, match="T09_PERSIST_DIR 디렉터리가 없습니다"):
            load_resources(reference_path=ref_file)


def test_load_resources_explicit_missing_source_root_raises(tmp_path: Path) -> None:
    ref_file = tmp_path / "ref.json"
    ref_file.write_text("{}", encoding="utf-8")
    persist_dir = tmp_path / "db"
    persist_dir.mkdir()
    non_existent_src = tmp_path / "missing_src"

    with patch("artagent.cli.load_spec") as mock_load_spec, \
         patch("artagent.cli.verify_store_ready"), \
         patch("artagent.cli.load_encoder") as mock_load_encoder, \
         patch("artagent.cli.open_store") as mock_open_store:
        mock_load_spec.return_value = MagicMock()
        mock_load_encoder.return_value = MagicMock()
        mock_open_store.return_value = MagicMock()

        with pytest.raises(FileNotFoundError, match="지정한 source-root 디렉터리가 없습니다"):
            load_resources(
                reference_path=ref_file,
                persist_dir=persist_dir,
                source_root=non_existent_src,
            )


def test_load_resources_env_missing_source_root_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref_file = tmp_path / "ref.json"
    ref_file.write_text("{}", encoding="utf-8")
    persist_dir = tmp_path / "db"
    persist_dir.mkdir()
    monkeypatch.setenv("T09_SOURCE_ROOT", str(tmp_path / "missing_env_src"))

    with patch("artagent.cli.load_spec") as mock_load_spec, \
         patch("artagent.cli.verify_store_ready"), \
         patch("artagent.cli.load_encoder") as mock_load_encoder, \
         patch("artagent.cli.open_store") as mock_open_store:
        mock_load_spec.return_value = MagicMock()
        mock_load_encoder.return_value = MagicMock()
        mock_open_store.return_value = MagicMock()

        with pytest.raises(FileNotFoundError, match="T09_SOURCE_ROOT 디렉터리가 없습니다"):
            load_resources(
                reference_path=ref_file,
                persist_dir=persist_dir,
            )


def test_load_resources_sequence_and_success(tmp_path: Path) -> None:
    ref_file = tmp_path / "ref.json"
    ref_file.write_text("{}", encoding="utf-8")
    persist_dir = tmp_path / "db"
    persist_dir.mkdir()
    source_root = tmp_path / "src"
    source_root.mkdir()

    calls: list[str] = []

    def mock_load_spec(p: Path) -> Any:
        calls.append("load_spec")
        return MagicMock(collection_name="test_col")

    def mock_verify_store_ready(p: Path, spec: Any) -> int:
        calls.append("verify_store_ready")
        return 10

    def mock_load_encoder(spec: Any) -> Any:
        calls.append("load_encoder")
        return MagicMock()

    def mock_open_store(p: Path, spec: Any) -> Any:
        calls.append("open_store")
        return MagicMock()

    with patch("artagent.cli.load_spec", side_effect=mock_load_spec), \
         patch("artagent.cli.verify_store_ready", side_effect=mock_verify_store_ready), \
         patch("artagent.cli.load_encoder", side_effect=mock_load_encoder), \
         patch("artagent.cli.open_store", side_effect=mock_open_store):

        store, encoder, s_root = load_resources(
            reference_path=ref_file,
            persist_dir=persist_dir,
            source_root=source_root,
        )

        assert calls == ["load_spec", "verify_store_ready", "load_encoder", "open_store"]
        assert store is not None
        assert encoder is not None
        assert s_root == source_root.resolve()


# =========================================================================
# 3. Node Wrapper Tests
# =========================================================================

def test_dispatch_wrapper_blocks_execute() -> None:
    wrapper = create_dispatch_wrapper()

    state: AgentState = {
        "request": RequestInput(request_id="r1", text="노출 보정 적용해줘"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=AgentPath.EXECUTE, query="")]
        ),
        "cursor": 0,
        "retrieval": MagicMock(),
        "answer": MagicMock(),
        "trace": ["INTAKE", "ROUTE"],
    }

    result = wrapper(state)

    assert result["error"] is not None
    assert result["error"].code == "UNSUPPORTED"
    assert result["error"].node == "DISPATCH"
    assert result["error"].message == EXECUTE_UNSUPPORTED_MESSAGE
    assert result["retrieval"] is None
    assert result["answer"] is None
    assert result["execution"] is None
    assert result["features"] is None
    assert result["profile"] is None
    assert result["validation"] is None
    assert result["render"] is None
    assert result["trace"] == ["INTAKE", "ROUTE", "DISPATCH"]


def test_dispatch_wrapper_delegates_doc_qa() -> None:
    wrapper = create_dispatch_wrapper()

    state: AgentState = {
        "request": RequestInput(request_id="r1", text="노출 보정 방법"),
        "decision": RouteDecision(
            plan=[PlanStep(step_id="s1", path=AgentPath.DOC_QA, query="")]
        ),
        "cursor": 0,
        "capabilities": RuntimeCapabilities(search_ready=True),
        "trace": ["INTAKE", "ROUTE"],
    }

    result = wrapper(state)

    assert result.get("error") is None
    assert "DISPATCH" in result.get("trace", [])


def test_research_wrapper_returns_insufficient_evidence() -> None:
    state: AgentState = {
        "request": RequestInput(request_id="r1", text="알 수 없는 질문"),
        "trace": ["INTAKE", "ROUTE", "DISPATCH", "SEARCH_RAWPEDIA", "ANSWER"],
    }

    result = research_wrapper(state)

    assert result["error"] is not None
    assert result["error"].code == "INSUFFICIENT_EVIDENCE"
    assert result["error"].node == "RESEARCH"
    assert result["trace"][-1] == "RESEARCH"


# =========================================================================
# 4. Response Rendering Tests
# =========================================================================

def test_render_response_clarification() -> None:
    lines: list[str] = []
    resp = ResponseOutput(
        request_id="req_clarify",
        status=ResponseStatus.WAITING_CLARIFICATION.value,
        clarification=Clarification(
            id="c1",
            question="어떤 작업인지 명확히 알려주세요.",
        ),
    )

    render_response(resp, write_fn=lines.append)

    assert lines == [
        "[WAITING_CLARIFICATION]",
        "어떤 작업인지 명확히 알려주세요.",
        CLARIFICATION_RETRY_MESSAGE,
    ]


def test_render_response_succeeded_qa_preserves_multi_segment_citations() -> None:
    lines: list[str] = []
    cit1 = Citation(
        doc_id="issue:524",
        title="Crash on Spot Removal",
        url="https://github.com/artraweditor/ART/issues/524",
        source_location='{"seg":1}',
    )
    cit2 = Citation(
        doc_id="issue-comment:5648127070",
        title="Crash on Spot Removal",
        url="https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070",
        source_location='{"seg":2}',
    )
    step = StepResult(
        step_id="s1",
        path=AgentPath.TROUBLESHOOT,
        status="SUCCEEDED",
        answer=AnswerResult(
            status="SUPPORTED",
            text=(
                "보고된 증상입니다. "
                "[출처: Crash on Spot Removal·https://github.com/artraweditor/ART/issues/524] "
                "[출처: Crash on Spot Removal·https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070]"
            ),
            citations=[cit1, cit2],
        ),
    )
    resp = ResponseOutput(
        request_id="req_qa",
        status=ResponseStatus.COMPLETED.value,
        message="요청된 모든 단계가 성공적으로 완료되었습니다.",
        completed_steps=[step],
    )

    render_response(resp, write_fn=lines.append)

    full_output = "\n".join(lines)
    assert "[COMPLETED] 요청된 모든 단계가 성공적으로 완료되었습니다." in full_output
    assert "[출처: Crash on Spot Removal·https://github.com/artraweditor/ART/issues/524]" in full_output
    assert "[인용 목록]" in full_output
    assert "- Crash on Spot Removal (https://github.com/artraweditor/ART/issues/524)" in full_output
    assert "- Crash on Spot Removal (https://github.com/artraweditor/ART/issues/524#issuecomment-5648127070)" in full_output


def test_render_response_insufficient_evidence_displays_error_and_status() -> None:
    lines: list[str] = []
    step = StepResult(
        step_id="s1",
        path=AgentPath.DOC_QA,
        status="INSUFFICIENT_EVIDENCE",
        answer=AnswerResult(
            status="INSUFFICIENT_EVIDENCE",
            text="모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.",
            citations=[],
        ),
        error=ErrorInfo(
            code="INSUFFICIENT_EVIDENCE",
            message="근거가 부족하여 답변할 수 없습니다.",
            node="RESEARCH",
        ),
    )
    resp = ResponseOutput(
        request_id="req_insuf",
        status=ResponseStatus.INSUFFICIENT_EVIDENCE.value,
        message="근거가 부족하여 답변할 수 없습니다.",
        completed_steps=[step],
    )

    render_response(resp, write_fn=lines.append)

    full_output = "\n".join(lines)
    assert "[INSUFFICIENT_EVIDENCE] 근거가 부족하여 답변할 수 없습니다." in full_output
    assert "모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다." in full_output
    assert "[COMPLETED]" not in full_output
    assert "[인용 목록]" not in full_output


def test_render_response_unsupported_execute() -> None:
    lines: list[str] = []
    step = StepResult(
        step_id="s1",
        path=AgentPath.EXECUTE,
        status="UNSUPPORTED",
        error=ErrorInfo(
            code="UNSUPPORTED",
            message=EXECUTE_UNSUPPORTED_MESSAGE,
            node="DISPATCH",
        ),
    )
    resp = ResponseOutput(
        request_id="req_exec",
        status=ResponseStatus.UNSUPPORTED.value,
        message="지원되지 않는 요청입니다.",
        completed_steps=[step],
    )

    render_response(resp, write_fn=lines.append)

    full_output = "\n".join(lines)
    assert "[UNSUPPORTED] 지원되지 않는 요청입니다." in full_output
    assert EXECUTE_UNSUPPORTED_MESSAGE in full_output
    assert "[인용 목록]" not in full_output


def test_render_response_partial_mixed() -> None:
    lines: list[str] = []
    cit = Citation(
        doc_id="rawpedia:Exposure",
        title="Exposure",
        url="https://example.com",
        source_location="{}",
    )
    step1 = StepResult(
        step_id="s1",
        path=AgentPath.DOC_QA,
        status="SUCCEEDED",
        answer=AnswerResult(
            status="SUPPORTED",
            text="노출 보정 설명 [출처: Exposure·https://example.com]",
            citations=[cit],
        ),
    )
    step2 = StepResult(
        step_id="s2",
        path=AgentPath.EXECUTE,
        status="UNSUPPORTED",
        error=ErrorInfo(
            code="UNSUPPORTED",
            message=EXECUTE_UNSUPPORTED_MESSAGE,
            node="DISPATCH",
        ),
    )
    resp = ResponseOutput(
        request_id="req_mixed",
        status=ResponseStatus.PARTIAL.value,
        message="일부 단계만 완료되었습니다. (후속 단계 실패)",
        completed_steps=[step1, step2],
    )

    render_response(resp, write_fn=lines.append)

    full_output = "\n".join(lines)
    assert "[PARTIAL] 일부 단계만 완료되었습니다." in full_output
    assert "노출 보정 설명" in full_output
    assert "- Exposure (https://example.com)" in full_output
    assert EXECUTE_UNSUPPORTED_MESSAGE in full_output


def test_render_response_out_of_scope() -> None:
    lines: list[str] = []
    resp = ResponseOutput(
        request_id="req_oos",
        status=ResponseStatus.OUT_OF_SCOPE.value,
        message="The request is out of supported scope or empty",
        error=ErrorInfo(
            code="OUT_OF_SCOPE",
            message="The request is out of supported scope or empty",
            node="ROUTE",
        ),
    )

    render_response(resp, write_fn=lines.append)

    assert lines == [
        "[OUT_OF_SCOPE] (OUT_OF_SCOPE) The request is out of supported scope or empty"
    ]


# =========================================================================
# 5. REPL Loop Tests
# =========================================================================

def test_run_repl_quit_and_exit() -> None:
    for quit_cmd in ("/quit", "/exit", "  /QUIT  "):
        inputs = iter([quit_cmd])
        outputs: list[str] = []
        ret = run_repl(
            MagicMock(),
            input_fn=lambda prompt: next(inputs),
            write_fn=outputs.append,
        )
        assert ret == 0
        assert outputs == []


def test_run_repl_empty_lines_ignored() -> None:
    inputs = iter(["", "   ", "\t", "/quit"])
    mock_graph = MagicMock()
    outputs: list[str] = []

    ret = run_repl(
        mock_graph,
        input_fn=lambda prompt: next(inputs),
        write_fn=outputs.append,
    )

    assert ret == 0
    mock_graph.invoke.assert_not_called()


def test_run_repl_eof_and_interrupt() -> None:
    def raise_eof(p: str) -> str:
        raise EOFError()

    outputs: list[str] = []
    ret = run_repl(MagicMock(), input_fn=raise_eof, write_fn=outputs.append)
    assert ret == 0
    assert outputs == [""]

    def raise_interrupt(p: str) -> str:
        raise KeyboardInterrupt()

    outputs = []
    ret = run_repl(MagicMock(), input_fn=raise_interrupt, write_fn=outputs.append)
    assert ret == 0
    assert outputs == [""]


def test_run_repl_recovers_from_invoke_exception_and_missing_response() -> None:
    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = [
        RuntimeError("네트워크 연결 끊김"),
        {"response": None},
    ]

    inputs = iter(["노출 보정 방법", "두 번째 질문", "/quit"])
    outputs: list[str] = []

    ret = run_repl(
        mock_graph,
        input_fn=lambda prompt: next(inputs),
        write_fn=outputs.append,
    )

    assert ret == 0
    assert any("[FAILED] 요청 처리 중 오류가 발생했습니다: 네트워크 연결 끊김" in out for out in outputs)
    assert any("[FAILED] 응답이 생성되지 않았습니다." in out for out in outputs)


def test_run_repl_independent_requests_no_session_or_resume() -> None:
    captured_states: list[dict[str, Any]] = []

    def fake_invoke(state: dict[str, Any]) -> dict[str, Any]:
        captured_states.append(state)
        req: RequestInput = state["request"]
        return {
            "response": ResponseOutput(
                request_id=req.request_id,
                status=ResponseStatus.WAITING_CLARIFICATION.value,
                clarification=Clarification(id="c1", question="명확화 질문"),
            )
        }

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = fake_invoke

    inputs = iter(["사진이 노래요. 봐주세요", "노출 보정 방법을 알려줘", "/quit"])
    outputs: list[str] = []

    ret = run_repl(
        mock_graph,
        input_fn=lambda prompt: next(inputs),
        write_fn=outputs.append,
    )

    assert ret == 0
    assert len(captured_states) == 2
    for st in captured_states:
        assert "resume" not in st
        req = st["request"]
        assert req.session_id is None
        assert req.assets == []
        assert req.context is None
    assert captured_states[0]["request"].request_id != captured_states[1]["request"].request_id


# =========================================================================
# 6. Graph E2E Scenarios (DOC_QA, TROUBLESHOOT, INSUFFICIENT_EVIDENCE, EXECUTE, Mixed, Clarify)
# =========================================================================

def _make_mock_hit(
    tmp_path: Path,
    *,
    rank: int = 1,
    chunk_id: str = "chunk_exp",
    doc_id: str = "rawpedia:Exposure",
    source_type: str = "rawpedia",
    text: str = "Auto Levels analyzes the image histogram to adjust exposure.",
    url: str = "https://rawpedia.rawtherapee.com/exposure/",
) -> Any:
    from artagent.answer import sha256_bytes
    from artagent.retrieval.provenance import sha256_str
    from artagent.retrieval.types import SearchHit

    rel_path = f"data/{source_type}/Exposure.md"
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = text.encode("utf-8")
    file_path.write_bytes(content_bytes)
    f_sha = sha256_bytes(content_bytes)

    return SearchHit(
        rank=rank,
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_group_id=doc_id,
        source_type=source_type,
        section_title="Exposure",
        content=text,
        content_sha256=sha256_str(text),
        source_segments=[{
            "doc_id": doc_id,
            "source_path": rel_path,
            "target_url": url,
            "source_file_sha256": f_sha,
            "segment_sha256": sha256_str(text),
            "char_start": 0,
            "char_end": len(text),
            "byte_start": 0,
            "byte_end": len(content_bytes),
            "content_char_start": 0,
            "content_char_end": len(text),
        }],
        original_metadata={},
        distance=0.05,
        distance_text="0.050000",
    )


def test_e2e_doc_qa_query(tmp_path: Path) -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()
    mock_store.search.return_value = [_make_mock_hit(tmp_path)]

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "노출 보정은 히스토그램을 분석하여 조정합니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    graph = build_repl_graph(
        store=mock_store,
        session=mock_session,
        source_root=tmp_path,
        generate=mock_gen,
    )

    req = RequestInput(request_id="req_1", text="노출 보정 방법을 알려줘")
    result = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    resp = result["response"]
    assert resp is not None
    assert resp.status == ResponseStatus.COMPLETED.value
    assert len(resp.completed_steps) == 1
    step = resp.completed_steps[0]
    assert step.status == "SUCCEEDED"
    assert "노출 보정은 히스토그램을 분석하여 조정합니다" in step.answer.text
    assert "[출처: Exposure·https://rawpedia.rawtherapee.com/exposure/]" in step.answer.text
    assert len(step.answer.citations) == 1


def test_e2e_insufficient_evidence_terminates_without_re_search(tmp_path: Path) -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()
    mock_store.search.return_value = [_make_mock_hit(tmp_path)]

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        return json.dumps({
            "status": "INSUFFICIENT_EVIDENCE",
            "answer": "모르겠습니다. 제공된 검색 근거로는 확인할 수 없습니다.",
            "citation_ids": [],
        })

    graph = build_repl_graph(
        store=mock_store,
        session=mock_session,
        source_root=tmp_path,
        generate=mock_gen,
    )

    req = RequestInput(request_id="req_insuf", text="노출 보정 방법을 알려줘")
    result = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    resp = result["response"]
    assert resp is not None
    assert resp.status == ResponseStatus.INSUFFICIENT_EVIDENCE.value
    assert mock_store.search.call_count == 1
    assert "RESEARCH" in result["trace"]
    step = resp.completed_steps[0]
    assert step.status == "INSUFFICIENT_EVIDENCE"
    assert step.error is not None
    assert step.error.code == "INSUFFICIENT_EVIDENCE"


def test_e2e_execute_query_blocked(tmp_path: Path) -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    graph = build_repl_graph(
        store=mock_store,
        session=mock_session,
        source_root=tmp_path,
    )

    req = RequestInput(request_id="req_2", text="노출 보정을 적용해줘")
    result = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    resp = result["response"]
    assert resp is not None
    assert resp.status == ResponseStatus.UNSUPPORTED.value
    assert len(resp.completed_steps) == 1
    step = resp.completed_steps[0]
    assert step.status == "UNSUPPORTED"
    assert step.error.message == EXECUTE_UNSUPPORTED_MESSAGE
    assert step.answer is None

    trace = result["trace"]
    for forbidden_node in ("CHECK_EXEC", "FEATURES", "GENERATE_PROFILE", "VALIDATE_PROFILE", "RENDER"):
        assert forbidden_node not in trace


def test_e2e_mixed_query(tmp_path: Path) -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()
    mock_store.search.return_value = [_make_mock_hit(tmp_path)]

    def mock_gen(sys_inst: str, user_prompt: str, ctx_cits: dict, q_norm: str) -> str:
        return json.dumps({
            "status": "SUPPORTED",
            "answer": "노출 보정 가이드입니다 [C1S1].",
            "citation_ids": ["C1S1"],
        })

    graph = build_repl_graph(
        store=mock_store,
        session=mock_session,
        source_root=tmp_path,
        generate=mock_gen,
    )

    req = RequestInput(
        request_id="req_3",
        text="노출 조절 방법도 알려주고 노출 보정을 적용해줘",
    )
    result = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    resp = result["response"]
    assert resp is not None
    assert resp.status == ResponseStatus.PARTIAL.value
    assert len(resp.completed_steps) == 2
    assert resp.completed_steps[0].status == "SUCCEEDED"
    assert resp.completed_steps[0].answer is not None
    assert resp.completed_steps[1].status == "UNSUPPORTED"
    assert resp.completed_steps[1].error.message == EXECUTE_UNSUPPORTED_MESSAGE


def test_e2e_clarification_query(tmp_path: Path) -> None:
    mock_store = MagicMock()
    mock_session = MagicMock()

    graph = build_repl_graph(
        store=mock_store,
        session=mock_session,
        source_root=tmp_path,
    )

    req = RequestInput(request_id="req_4", text="사진이 노래요. 봐주세요")
    result = graph.invoke({
        "request": req,
        "capabilities": RuntimeCapabilities(search_ready=True),
    })

    resp = result["response"]
    assert resp is not None
    assert resp.status == ResponseStatus.WAITING_CLARIFICATION.value
    assert resp.clarification is not None
    assert resp.clarification.question != ""


def test_main_cli_fails_on_missing_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T09_PERSIST_DIR", "/non_existent_path_t09_persist")
    monkeypatch.setenv("T09_REFERENCE_PATH", "docs/T08_2_t9_handoff_reference.json")

    code = main(["--persist-dir", "/non_existent_path_t09_persist"])
    assert code == 1
