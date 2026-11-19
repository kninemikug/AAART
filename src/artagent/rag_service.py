"""GUI와 CLI가 공유하는 서비스 검색 설정."""

import os
from subprocess import TimeoutExpired
from urllib.error import HTTPError, URLError

from .graph import ErrorInfo, create_search_nodes
from .retrieval.rerank import BM25Reranker


def use_local_rag() -> bool:
    """서비스 프로필을 읽고 잘못된 명시 설정을 거부한다."""
    profile = os.getenv("ART_RAG_PROFILE", "legacy").strip().lower()
    if profile not in ("legacy", "local"):
        raise RuntimeError("ART_RAG_PROFILE에는 legacy 또는 local을 지정해야 합니다.")
    return profile == "local"


def service_answer_generator():
    """MiniMax를 명시한 답변만 변경하고 선택한 대체 제공처를 한 번 호출한다."""
    provider = os.getenv("ART_RAG_ANSWER_PROVIDER", "existing").strip().lower()
    if provider == "existing":
        return None
    if provider != "minimax":
        raise RuntimeError("ART_RAG_ANSWER_PROVIDER에는 existing 또는 minimax를 지정해야 합니다.")
    fallback = os.getenv("ART_RAG_ANSWER_FALLBACK", "none").strip().lower()
    if fallback not in ("none", "existing"):
        raise RuntimeError("ART_RAG_ANSWER_FALLBACK에는 none 또는 existing을 지정해야 합니다.")

    def generate(*, observe_request, **kwargs):
        from .answer import GenerationError, OpenAIEndpoint, _generation_timeout, generate_llm_response, generation_time_budget

        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            raise RuntimeError("MiniMax 답변에 NVIDIA_API_KEY가 필요합니다.")
        endpoint = OpenAIEndpoint("https://integrate.api.nvidia.com/v1", "minimaxai/minimax-m3.1-flash", key)
        attempts = []

        def record(event):
            attempts.append(event["request"])
            if observe_request is not None:
                observe_request({**event, "requests": list(attempts), "call_count": len(attempts)})

        with generation_time_budget(120):
            _generation_timeout(60)
            try:
                return generate_llm_response(**kwargs, api_endpoint=endpoint, observe_request=record)
            except GenerationError as error:
                cause = error.__cause__
                if isinstance(cause, URLError) and not isinstance(cause, HTTPError):
                    cause = cause.reason
                retryable = (isinstance(cause, (TimeoutError, TimeoutExpired))
                             or isinstance(cause, HTTPError) and cause.code in (429, 529))
                if fallback != "existing" or not retryable:
                    raise
                _generation_timeout(60)
                return generate_llm_response(**kwargs, observe_request=record)

    return generate


def create_service_search_nodes(store, encoder, *, local, snapshot_ref=""):
    if not local:
        return create_search_nodes(store, encoder, snapshot_ref=snapshot_ref)

    fitted_snapshot = None
    nodes = None

    def wrap(name):
        def search(state):
            nonlocal fitted_snapshot, nodes
            if state.get("error"):
                return {"error": state["error"], "trace": [*state.get("trace", []), name]}
            try:
                with store.active_search_corpus() as (snapshot, corpus):
                    if snapshot != fitted_snapshot:
                        reranker = BM25Reranker(corpus, model_id="lexical_bm25")
                        nodes = create_search_nodes(
                            store, encoder, snapshot_ref=snapshot, reranker=reranker,
                            candidate_k=20, top_k=5, min_score=0.5, rerank_weight=0.75,
                            rawpedia_ui_terms=True, recover_rewrite=True,
                        )
                        fitted_snapshot = snapshot
                    return nodes[name](state)
            except (ValueError, RuntimeError, OSError) as exc:
                return {"error": ErrorInfo("SEARCH_UNAVAILABLE", str(exc), name),
                        "trace": [*state.get("trace", []), name]}

        return search

    return {name: wrap(name) for name in ("SEARCH_RAWPEDIA", "SEARCH_GITHUB")}
