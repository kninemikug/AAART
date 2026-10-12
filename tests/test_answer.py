"""Task 11 Slice 1 answer.py 단위 및 회귀 테스트."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from artagent.answer import (
    NORMALIZATION_RULE_VERSION,
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


def test_pipeline_record_path_rejection_before_execution():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()

    # Prohibited corpus path
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        run_pipeline(
            query_original="Test query",
            reference_path=ref_path,
            persist_dir=persist_dir,
            record_path=Path("data/rawpedia/forbidden.jsonl"),
        )

    # Directory path
    with pytest.raises(ValueError, match="디렉터리입니다"):
        run_pipeline(
            query_original="Test query",
            reference_path=ref_path,
            persist_dir=persist_dir,
            record_path=Path("docs"),
        )


def test_codex_event_log_tool_call_rejected(tmp_path):
    mock_events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 10}}),
    ]
    stdout_content = "\n".join(mock_events)

    class MockCompletedProcess:
        returncode = 0
        stdout = stdout_content
        stderr = ""

    # Prepare temp output file that codex exec writes to
    def mock_subprocess_run(cmd, **kwargs):
        # Find -o <path>
        out_idx = cmd.index("-o") + 1
        out_p = Path(cmd[out_idx])
        out_p.write_text(json.dumps({"answer": "test", "citation_ids": []}), encoding="utf-8")
        return MockCompletedProcess()

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(RuntimeError, match="추가 도구 사용\\(command_execution\\)이 감지되어"):
                    generate_llm_response("sys", "user", {}, "q")


def test_codex_event_log_success_usage_parsing(tmp_path):
    mock_events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 30}}),
    ]
    stdout_content = "\n".join(mock_events)

    class MockCompletedProcess:
        returncode = 0
        stdout = stdout_content
        stderr = ""

    def mock_subprocess_run(cmd, **kwargs):
        out_idx = cmd.index("-o") + 1
        out_p = Path(cmd[out_idx])
        out_p.write_text(json.dumps({"answer": "답변 [C1S1]", "citation_ids": ["C1S1"]}), encoding="utf-8")
        return MockCompletedProcess()

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                raw_resp, usage, meta = generate_llm_response(
                    "sys", "user", {"C1S1": {"display_name": "Doc", "target_url": "http://doc"}}, "q"
                )
                assert usage == {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
                assert meta["llm_provider"] == "codex-cli"
                assert meta["generation_config"]["temperature"] is None
                assert meta["_finish_reason"] is None


