"""Task 11 Slice 1 answer.py 단위 및 회귀 테스트."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from artagent.answer import (
    DEFAULT_QUERY_SET_PATH,
    DEFAULT_REFERENCE_PATH,
    DEFAULT_SOURCE_ROOT,
    NORMALIZATION_RULE_VERSION,
    GenerationError,
    build_prompt_and_citations,
    check_input_matched,
    generate_llm_response,
    main,
    normalize_query,
    run_pipeline,
    validate_and_format_citations,
    validate_record_path,
)
from artagent.retrieval.types import SearchHit


def test_normalize_query_success():
    raw = "  RawPedia\t설명에서   Auto Levels는  무엇을 \n분석하나요?  "
    normalized = normalize_query(raw)
    assert normalized == "RawPedia 설명에서 Auto Levels는 무엇을 분석하나요?"


def test_normalize_query_empty_fails():
    with pytest.raises(ValueError, match="질문이 비어 있습니다"):
        normalize_query("")
    with pytest.raises(ValueError, match="질문이 비어 있습니다"):
        normalize_query("   \t\n  ")


def test_build_prompt_and_citations():
    hit1 = SearchHit(
        rank=1,
        chunk_id="chk1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure",
        section_title="Exposure",
        content="Auto Levels analyzes the histogram to adjust exposure.",
        content_sha256="abc",
        source_segments=[
            {
                "doc_id": "rawpedia:Exposure",
                "target_url": "https://rawpedia.es/Exposure",
                "content_char_start": 0,
                "content_char_end": 50,
            }
        ],
        original_metadata={"page_title": "Exposure"},
        distance=0.1,
        distance_text="0.100000",
    )
    user_prompt, citations, cids = build_prompt_and_citations("Auto Levels 질문", [hit1])
    assert "C1S1" in citations
    assert cids == ["C1S1"]
    assert citations["C1S1"]["display_name"] == "Exposure"
    assert citations["C1S1"]["target_url"] == "https://rawpedia.es/Exposure"
    assert "Auto Levels 질문" in user_prompt


def test_validate_and_format_citations_success():
    context_citations = {
        "C1S1": {
            "citation_id": "C1S1",
            "display_name": "Exposure",
            "target_url": "https://rawpedia.es/Exposure",
            "chunk_id": "chk1",
            "source_segment": {"doc_id": "rawpedia:Exposure"},
        }
    }
    raw_answer = "히스토그램을 분석합니다 [C1S1]."
    parsed_ids = ["C1S1"]
    final_ans, stdout_text, used = validate_and_format_citations(raw_answer, parsed_ids, context_citations)
    assert "[출처: Exposure·https://rawpedia.es/Exposure]" in final_ans
    assert "[인용 목록]" in stdout_text
    assert "- C1S1: Exposure (https://rawpedia.es/Exposure)" in stdout_text
    assert len(used) == 1


def test_validate_and_format_citations_empty_answer_fails():
    context_citations = {"C1S1": {"display_name": "A", "target_url": "http://a"}}
    with pytest.raises(ValueError, match="답변 문자열이 비어 있습니다"):
        validate_and_format_citations("", ["C1S1"], context_citations)
    with pytest.raises(ValueError, match="답변 문자열이 비어 있습니다"):
        validate_and_format_citations("   ", ["C1S1"], context_citations)


def test_validate_and_format_citations_marker_mismatch_fails():
    context_citations = {
        "C1S1": {"display_name": "A", "target_url": "http://a"},
        "C1S2": {"display_name": "B", "target_url": "http://b"},
    }
    # Marker has C1S1, but parsed_ids has C1S2
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        validate_and_format_citations("답변입니다 [C1S1].", ["C1S2"], context_citations)

    # Marker omitted in text
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        validate_and_format_citations("답변입니다.", ["C1S1"], context_citations)


def test_validate_and_format_citations_unknown_id_fails():
    context_citations = {"C1S1": {"display_name": "A", "target_url": "http://a"}}
    with pytest.raises(ValueError, match="문맥에 없는 인용 ID"):
        validate_and_format_citations("답변입니다 [C2S1].", ["C2S1"], context_citations)


def test_validate_and_format_citations_missing_metadata_fails():
    context_citations = {"C1S1": {"display_name": "", "target_url": ""}}
    with pytest.raises(ValueError, match="필수 정보"):
        validate_and_format_citations("답변입니다 [C1S1].", ["C1S1"], context_citations)


def test_run_pipeline_generation_failure_recording():
    ref_path = Path("/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json")
    persist_dir = Path("data/vector-store/t09")

    with patch("artagent.answer.generate_llm_response", side_effect=RuntimeError("API connection timeout")):
        record = run_pipeline(
            query_original="Auto Levels",
            reference_path=ref_path,
            persist_dir=persist_dir,
            query_id="Q_TEST",
        )
        assert record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "generation"
        assert "API connection timeout" in record["execution"]["error_message"]
        assert record["output"]["exit_code"] == 1
        assert record["verification"]["citations_valid"] is False
        assert record["verification"]["manual_review"] == "pending"


def test_record_isolation():
    ref_path = Path("/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json")
    persist_dir = Path("data/vector-store/t09")

    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl") as tmp_file:
        tmp_record_path = Path(tmp_file.name)
        # Mocking generation to return a valid grounded JSON response
        mock_response = json.dumps({"answer": "결과 [C1S1]", "citation_ids": ["C1S1"]})
        with patch("artagent.answer.generate_llm_response", return_value=(mock_response, None, {"llm_provider": "mock"})):
            record = run_pipeline(
                query_original="Exposure compensation",
                reference_path=ref_path,
                persist_dir=persist_dir,
                query_id="Q_ISOLATION",
            )
            assert record["execution"]["status"] == "success"
            # Write to tmp_record_path
            tmp_record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            assert tmp_record_path.is_file()
            lines = tmp_record_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            loaded = json.loads(lines[0])
            assert loaded["query_id"] == "Q_ISOLATION"


def test_validate_record_path_rejections():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    query_set_path = Path("docs/search_eval_queries.json").resolve()
    persist_dir = Path("data/vector-store").resolve()

    # 1. Reference file rejection
    with pytest.raises(ValueError, match="보호된 파일"):
        validate_record_path(ref_path, ref_path, persist_dir, query_set_path)

    # 2. Query set file rejection
    with pytest.raises(ValueError, match="보호된 파일"):
        validate_record_path(query_set_path, ref_path, persist_dir, query_set_path)

    # 3. Corpus directory & subpath rejection
    rawpedia_file = Path("data/rawpedia/sample.jsonl")
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(rawpedia_file, ref_path, persist_dir, query_set_path)

    issues_file = Path("data/issues/comments.json")
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(issues_file, ref_path, persist_dir, query_set_path)

    # 4. DB directory & subpath rejection
    db_file = persist_dir / "chroma.sqlite3"
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(db_file, ref_path, persist_dir, query_set_path)

    # 5. Allowed record path
    valid_record_path = Path("docs/T11_execution_records.jsonl")
    validate_record_path(valid_record_path, ref_path, persist_dir, query_set_path)


def test_cli_record_path_rejection(capsys):
    test_argv = [
        "answer.py",
        "Test query",
        "--record", "data/rawpedia/forbidden.jsonl",
    ]
    with patch("sys.argv", test_argv):
        ret = main()
        assert ret == 2
        captured = capsys.readouterr()
        assert "[validation]" in captured.err
        assert "보호된 디렉터리" in captured.err


def test_llm_provider_selection_errors():
    # 1. Invalid provider -> ValueError
    with patch.dict("os.environ", {"LLM_PROVIDER": "unsupported_ai"}):
        with pytest.raises(ValueError, match="지원되지 않는 LLM_PROVIDER"):
            generate_llm_response("sys", "user", {}, "q")

    # 2. Codex missing on PATH -> RuntimeError (no fallback to openai)
    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="PATH에서 찾을 수 없습니다"):
                generate_llm_response("sys", "user", {}, "q")

    # 3. OpenAI missing API key & base URL -> RuntimeError (no fallback to codex)
    with patch.dict("os.environ", {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "", "LLM_API_KEY": "", "LLM_BASE_URL": ""}, clear=True):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY 또는 LLM_BASE_URL이 설정되지 않았습니다"):
            generate_llm_response("sys", "user", {}, "q")


def test_check_input_matched():
    query_set_path = Path("docs/search_eval_queries.json")
    if not query_set_path.is_file():
        pytest.skip("Query set file not present at docs/search_eval_queries.json")

    q_data = json.loads(query_set_path.read_bytes())
    first_q = q_data["queries"][0]
    qid = first_q["query_id"]
    qtext = first_q["query"]

    # Exactly matching
    assert check_input_matched(qid, qtext, query_set_path) is True

    # Modified query text
    assert check_input_matched(qid, qtext + " modified", query_set_path) is False

    # Non-existent query id
    assert check_input_matched("Q_DOES_NOT_EXIST", qtext, query_set_path) is False


def test_codex_runner_metadata_null():
    ref_path = Path("/Users/user/orca/workspaces/AAART/T08-2-chunking-embedding/docs/T08_2_t9_handoff_reference.json")
    persist_dir = Path("data/vector-store/t09")

    mock_resp = json.dumps({"answer": "Auto Levels 설명 [C1S1]", "citation_ids": ["C1S1"]})
    mock_meta = {
        "llm_provider": "codex-cli",
        "model_id": "gpt-5.6-sol",
        "endpoint": "codex exec",
        "generation_config": {"temperature": None, "prompt_version": 1},
        "_finish_reason": None,
    }

    with patch("artagent.answer.generate_llm_response", return_value=(mock_resp, {"total_tokens": 120}, mock_meta)):
        record = run_pipeline(
            query_original="Auto Levels",
            reference_path=ref_path,
            persist_dir=persist_dir,
            query_id="Q001",
        )
        assert record["execution"]["status"] == "success"
        # Confirm temperature and finish_reason are null / None
        assert record["runtime"]["generation_config"]["temperature"] is None
        assert record["generation"]["finish_reason"] is None
        assert record["generation"]["usage"] == {"total_tokens": 120}


def test_record_path_external_source_root_without_env_var_rejected():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    with patch.dict("os.environ", {}, clear=True):
        # 1. External rawpedia file without T09_SOURCE_ROOT env var
        ext_rawpedia = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_rawpedia, ref_path, persist_dir, query_set_path)

        # 2. External issues existing or non-existing file
        ext_issues_nonexist = DEFAULT_SOURCE_ROOT / "data/issues/comments_99999.jsonl"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_issues_nonexist, ref_path, persist_dir, query_set_path)


def test_record_path_custom_t09_source_root_both_protected(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    custom_root = tmp_path / "custom_root"
    custom_root.mkdir()
    (custom_root / "data" / "rawpedia").mkdir(parents=True)

    with patch.dict("os.environ", {"T09_SOURCE_ROOT": str(custom_root)}):
        # Default external root still protected
        ext_rawpedia = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_rawpedia, ref_path, persist_dir, query_set_path)

        # Custom root also protected
        custom_rawpedia = custom_root / "data/rawpedia/NewDoc.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(custom_rawpedia, ref_path, persist_dir, query_set_path)


def test_record_path_inputs_and_custom_persist_rejected(tmp_path):
    custom_ref = tmp_path / "my_ref.json"
    custom_ref.write_text("{}", encoding="utf-8")
    custom_persist = tmp_path / "my_persist_db"
    custom_persist.mkdir()
    custom_qset = tmp_path / "my_qset.json"
    custom_qset.write_text("{}", encoding="utf-8")

    # Default external reference & query set rejected
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(DEFAULT_REFERENCE_PATH, custom_ref, custom_persist, custom_qset)
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(DEFAULT_QUERY_SET_PATH, custom_ref, custom_persist, custom_qset)

    # Custom inputs rejected
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(custom_ref, custom_ref, custom_persist, custom_qset)
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(custom_qset, custom_ref, custom_persist, custom_qset)

    # File inside custom persist dir rejected
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(custom_persist / "sqlite3.db", custom_ref, custom_persist, custom_qset)


def test_record_path_symlink_to_protected_rejected(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    symlink_file = tmp_path / "sneaky_symlink.jsonl"
    target_prohibited = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
    symlink_file.symlink_to(target_prohibited)

    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(symlink_file, ref_path, persist_dir, query_set_path)


def test_safe_temporary_record_path_allowed(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    safe_path = tmp_path / "safe_record.jsonl"
    validate_record_path(safe_path, ref_path, persist_dir, query_set_path)


def test_prohibited_record_path_stops_before_calls_in_run_pipeline_and_cli():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    prohibited = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"

    with patch("artagent.answer.load_spec") as mock_load_spec, \
         patch("artagent.answer.open_store") as mock_open_store, \
         patch("artagent.answer.generate_llm_response") as mock_gen:

        # 1. run_pipeline direct call
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            run_pipeline("test query", ref_path, persist_dir, record_path=prohibited)
        assert mock_load_spec.call_count == 0
        assert mock_open_store.call_count == 0
        assert mock_gen.call_count == 0

        # 2. main() CLI call
        with patch("sys.argv", ["artagent-answer", "test query", "--record", str(prohibited)]):
            ret = main()
            assert ret == 2
        assert mock_load_spec.call_count == 0
        assert mock_open_store.call_count == 0
        assert mock_gen.call_count == 0


def _make_mock_completed_proc(stdout: str, stderr: str = "", returncode: int = 0):
    class MockProc:
        pass
    p = MockProc()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


def test_codex_empty_stdout_rejected(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout="", returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "이벤트 로그가 비어 있습니다" in str(err)
                assert err.trace is not None
                assert err.trace["trace_schema"] == "t11-codex-trace-v1"
                assert err.trace["validation"]["status"] == "rejected"


def test_codex_broken_json_and_non_json_lines_rejected(tmp_path):
    events = [
        json.dumps({"type": "thread.started"}),
        "THIS IS NOT JSON",
        json.dumps({"type": "turn.completed"}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "JSON 파싱 실패" in str(err)
                assert err.trace["validation"]["status"] == "rejected"
                assert "THIS IS NOT JSON" in err.trace["stdout_jsonl"]


def test_codex_lifecycle_incomplete_or_failed_rejected(tmp_path):
    # Missing turn.completed
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ans", "citation_ids": []})}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "이벤트 생명주기 불일치" in str(exc_info.value)


def test_codex_tool_item_in_item_updated_rejected(tmp_path):
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ans", "citation_ids": []})}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "web_search" in str(exc_info.value)
                assert exc_info.value.trace["validation"]["additional_tool_count"] == 1


def test_codex_content_mismatch_with_output_file_rejected(tmp_path):
    event_payload = {"answer": "Event Answer [C1S1]", "citation_ids": ["C1S1"]}
    file_payload = {"answer": "Different File Answer [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(event_payload)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(file_payload), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "일치하지 않습니다" in str(exc_info.value)


def test_codex_process_failure_and_partial_trace_preserved(tmp_path):
    partial_stdout = json.dumps({"type": "thread.started"}) + "\n"
    partial_stderr = "Fatal error in codex exec"

    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(stdout=partial_stdout, stderr=partial_stderr, returncode=1)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "비정상 종료" in str(err)
                assert err.trace["process_returncode"] == 1
                assert err.trace["stderr"] == partial_stderr
                assert err.trace["validation"]["status"] == "rejected"


def test_codex_success_trace_verified(tmp_path):
    ans_obj = {"answer": "정상 답변 [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-123"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(ans_obj)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(ans_obj), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                raw_resp, usage, meta = generate_llm_response(
                    "sys", "user", {"C1S1": {"display_name": "Doc", "target_url": "http://doc"}}, "q"
                )
                trace = meta["_trace"]
                assert trace is not None
                assert trace["trace_schema"] == "t11-codex-trace-v1"
                assert trace["validation"]["status"] == "verified"
                assert trace["validation"]["thread_id"] == "th-123"
                assert trace["validation"]["additional_tool_count"] == 0
                assert trace["validation"]["turn_started_count"] == 1
                assert trace["validation"]["turn_completed_count"] == 1


def test_cli_failure_event_recorded_in_safe_jsonl_with_trace(tmp_path):
    record_file = tmp_path / "cli_fail_run.jsonl"
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "whoami"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    class MockSpec:
        reference_sha256 = "ref_sha"
        protocol_sha256 = "proto_sha"
        collection_name = "col"
        model_id = "mod"
        dimension = 384
        space = "cosine"
        rawpedia_rule = "rr"
        github_rule = "gr"

    class MockHit:
        rank = 1
        chunk_id = "c1"
        source_type = "rawpedia"
        doc_id = "doc1"
        source_group_id = "doc1"
        section_title = "Sec"
        content = "Content"
        content_sha256 = "sha"
        source_segments = [{"doc_id": "doc1", "target_url": "http://doc1"}]
        original_metadata = {}
        distance = 0.1
        distance_text = "0.1"

    class MockStore:
        class collection:
            @staticmethod
            def count():
                return 10
        @staticmethod
        def search(q, sess):
            return [MockHit()]

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(record_file)]):
                        ret = main()
                        assert ret == 1

    assert record_file.is_file()
    rec = json.loads(record_file.read_text(encoding="utf-8").strip())
    assert rec["execution"]["status"] == "error"
    assert rec["execution"]["failed_step"] == "generation"
    assert rec["output"]["stdout"] == ""
    assert rec["generation"]["trace"]["validation"]["status"] == "rejected"
    assert rec["generation"]["trace"]["validation"]["additional_tool_count"] == 1


