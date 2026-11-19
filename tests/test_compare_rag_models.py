"""NVIDIA 비교의 요청 경로와 원 제공사 요금 환산 계약."""

import gzip
import json
import sys

import pytest

from artagent import answer
from scripts import compare_rag_models as comparison


def test_nvidia_reuses_t17_request_and_values_usage_at_publisher_rates(monkeypatch, tmp_path, capsys):
    model = comparison.NVIDIA_MODELS[0]
    monkeypatch.setenv("NVIDIA_API_KEY", "test-credential")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "different-credential")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-sol")

    def respond(request, _timeout):
        assert request.full_url == f"{comparison.NVIDIA_BASE_URL}/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-credential"
        assert json.loads(request.data)["model"] == model
        return json.dumps({
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "status": "UNSUPPORTED", "answer": "JXL 품질은 고정입니다. [C1S2]", "citation_ids": ["C1S2"],
            })}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 900}},
        })

    monkeypatch.setattr(answer, "_read_api_response", respond)
    command = ["compare_rag_models.py", "--provider", "nvidia", "--model", model,
               "--query", "Q096", "--output-dir", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", command)
    comparison.main()
    path = comparison.attempt_path(tmp_path, "Q096", model)
    assert "test-credential" not in gzip.decompress(path.read_bytes()).decode()
    capsys.readouterr()

    monkeypatch.delenv("NVIDIA_API_KEY")
    monkeypatch.setattr(sys, "argv", [*command, "--summary"])
    comparison.main()
    result = json.loads(capsys.readouterr().out)[model]
    assert result["matched_status"] == result["succeeded"] == 1
    assert result["estimated_api_standard_usd"] == pytest.approx(0.0002)


def test_nvidia_counts_usage_from_rejected_response_and_preserves_missing():
    model = comparison.NVIDIA_MODELS[1]
    assert comparison.estimate_usage(model, {
        "runtime_meta": {"_response_body": {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}},
    }) == pytest.approx(0.000027)
    assert comparison.estimate_usage(model, {"usage": {"prompt_tokens": 100}}) is None


def test_nvidia_preserves_usage_when_publisher_has_no_paid_rate(tmp_path):
    model = "google/gemma-4-31b-it"
    case = {"input_sha256": "input", "query_id": "Q001", "expected_status": "SUPPORTED",
            "search_run": {"bundle_sha256": "bundle"}}
    row = {"input_sha256": "input", "query_id": "Q001", "bundle_sha256": "bundle", "model": model,
           "expected_status": "SUPPORTED", "error": {"code": "ANSWER_GENERATION_FAILED"},
           "observation": {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}}
    path = comparison.attempt_path(tmp_path, "Q001", model)
    path.write_bytes(gzip.compress(json.dumps(row).encode()))

    result = comparison.summary(tmp_path, {"Q001": (case, None)}, [model])[model]

    assert result["prompt_tokens"] == 100
    assert result["completion_tokens"] == 20
    assert result["missing_usage_count"] == 0
    assert result["estimate_count"] == 0
    assert result["estimated_api_standard_usd"] is None
