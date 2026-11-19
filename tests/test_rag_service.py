"""GUI와 CLI의 RAG 서비스 설정을 실제 그래프 진입점에서 검증한다."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from artagent import gui_bridge
from artagent import rag_service
from artagent.answer import GenerationError, generation_time_budget
from artagent.cli import build_repl_graph
from artagent.graph import RequestInput, RuntimeCapabilities


class Store:
    def __init__(self):
        self.calls = []
        self.changed = False

    @contextmanager
    def active_search_corpus(self):
        yield "corpus-sha", ["Crop\n\nSelect a crop ratio."]
        if self.changed:
            raise RuntimeError("색인 변경")

    def search(self, query, _encoder, **filters):
        self.calls.append((query, filters))
        return []

    def search_candidates(self, query, _encoder, **filters):
        self.calls.append((query, filters))
        return []


def graph_for(entry, store, monkeypatch):
    encoder = object()
    if entry == "cli":
        return build_repl_graph(store, encoder)
    monkeypatch.setattr("artagent.answer.verify_store_ready", lambda *_: None)
    monkeypatch.setattr("artagent.retrieval.types.load_spec", lambda _: SimpleNamespace(reference_sha256="ref"))
    monkeypatch.setattr("artagent.retrieval.embedding.load_encoder", lambda _: encoder)
    monkeypatch.setattr("artagent.retrieval.store.open_store", lambda *_: store)
    return gui_bridge.create_gui_graph(Path("reference"), Path("store"), Path.cwd())


def search(graph, question):
    return graph.invoke({"request": RequestInput("service-test", question),
                         "capabilities": RuntimeCapabilities(search_ready=True)},
                        interrupt_before=["ANSWER"])


@pytest.mark.parametrize("entry", ["cli", "gui"])
def test_local_profile_uses_the_same_search_contract_at_both_entry_points(entry, monkeypatch):
    monkeypatch.setenv("ART_RAG_PROFILE", "local")
    store = Store()
    graph = graph_for(entry, store, monkeypatch)

    docs = search(graph, "RawTherapee 5:4 크롭 방법은?")
    issue = search(graph, "GitHub Issue #317 Resize PPI 제한은 무엇인가요?")

    assert store.calls[0] == ("RawTherapee 5:4 Crop 방법은?", {"candidate_k": 20, "source_type": "rawpedia"})
    assert store.calls[1][1]["source_group_ids"] == ["github:artraweditor/ART:issue:317"]
    assert issue["retrieval"].source_filter == "GITHUB"
    assert docs["retrieval"].snapshot_ref == "corpus-sha"
    assert docs["search_settings"]["rerank_weight"] == 0.75


def test_unset_profile_keeps_original_query(monkeypatch):
    monkeypatch.delenv("ART_RAG_PROFILE", raising=False)
    store = Store()
    state = search(build_repl_graph(store, object()), "RawTherapee 5:4 크롭 방법은?")
    assert store.calls == [("RawTherapee 5:4 크롭 방법은?", {"source_type": "rawpedia"})]
    assert state["search_settings"]["candidate_k"] == 10


def test_local_search_discards_results_if_the_corpus_changes(monkeypatch):
    monkeypatch.setenv("ART_RAG_PROFILE", "local")
    store = Store()
    store.changed = True
    state = search(build_repl_graph(store, object()), "RawTherapee 5:4 크롭 방법은?")
    assert state["response"].completed_steps[0].error.code == "SEARCH_UNAVAILABLE"
    assert state.get("retrieval") is None


@pytest.mark.parametrize("code, fallback, expect_calls", [(529, True, 2), (429, False, 1), (401, True, 1)])
def test_minimax_answer_fallback_is_explicit_and_limited(monkeypatch, code, fallback, expect_calls):
    monkeypatch.setenv("ART_RAG_ANSWER_PROVIDER", "minimax")
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setenv("LLM_MODEL", "existing-model")
    monkeypatch.setenv("ART_RAG_ANSWER_FALLBACK", "existing" if fallback else "none")
    attempts = []
    observed = []

    def generate(**kwargs):
        endpoint = kwargs.get("api_endpoint")
        model = endpoint.model_id if endpoint else "existing-model"
        attempts.append(model)
        kwargs["observe_request"]({"call_count": 1, "request": {"model": model}})
        if endpoint:
            raise GenerationError("test API failure") from HTTPError("https://example.test", code, "test", {}, None)
        return "raw", {"completion_tokens": 1}, {"model_id": model}

    monkeypatch.setattr("artagent.answer.generate_llm_response", generate)
    service = rag_service.service_answer_generator()
    kwargs = {"observe_request": observed.append, "user_prompt": "unchanged evidence"}

    if expect_calls == 2:
        raw, _, metadata = service(**kwargs)
        assert raw == "raw" and metadata["model_id"] == "existing-model"
        assert observed[-1]["call_count"] == 2
        assert [item["model"] for item in observed[-1]["requests"]] == attempts
    else:
        with pytest.raises(GenerationError):
            service(**kwargs)
    assert len(attempts) == expect_calls
    assert attempts[0] == "minimaxai/minimax-m3.1-flash"


def test_minimax_does_not_start_a_call_after_the_request_deadline(monkeypatch):
    monkeypatch.setenv("ART_RAG_ANSWER_PROVIDER", "minimax")
    monkeypatch.setenv("ART_RAG_ANSWER_FALLBACK", "existing")
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setattr("artagent.answer.generate_llm_response", lambda **_: pytest.fail("expired request"))
    with generation_time_budget(0), pytest.raises(TimeoutError):
        rag_service.service_answer_generator()(observe_request=None)


@pytest.mark.parametrize("from_env", [False, True])
def test_configured_nvidia_key_selects_minimax_by_default(monkeypatch, tmp_path, from_env):
    monkeypatch.delenv("ART_RAG_ANSWER_PROVIDER", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    (tmp_path / ".env.local").write_text("export NVIDIA_API_KEY='saved-test-key'\n", encoding="utf-8")
    if from_env:
        monkeypatch.setenv("NVIDIA_API_KEY", "environment-test-key")

    def generate(**kwargs):
        endpoint = kwargs["api_endpoint"]
        assert endpoint.model_id == "minimaxai/minimax-m3.1-flash"
        assert endpoint.base_url == "https://integrate.api.nvidia.com/v1"
        assert endpoint.api_key == ("environment-test-key" if from_env else "saved-test-key")
        return "response", None, {}

    monkeypatch.setattr("artagent.answer.generate_llm_response", generate)
    provider = rag_service.service_answer_generator(tmp_path)
    assert provider(observe_request=None)[0] == "response"


def test_explicit_default_provider_override_and_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("ART_RAG_ANSWER_PROVIDER", raising=False)
    assert rag_service.service_answer_generator(tmp_path) is None

    # Only a literal assignment is treated as an API key.
    (tmp_path / ".env.local").write_text("NVIDIA_API_KEY=$(other-command)\n", encoding="utf-8")
    assert rag_service.service_answer_generator(tmp_path) is None
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setenv("ART_RAG_ANSWER_PROVIDER", "existing")
    assert rag_service.service_answer_generator(tmp_path) is None
