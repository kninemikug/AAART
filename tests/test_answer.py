"""Task 11 Slice 1 answer.py 단위 및 회귀 테스트."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from artagent.answer import (
    NORMALIZATION_RULE_VERSION,
    build_prompt_and_citations,
    normalize_query,
    run_pipeline,
    validate_and_format_citations,
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
