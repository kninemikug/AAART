"""재작성의 제품 범위·숫자·빌드 식별자 원형 보존 계약 검증."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from artagent.graph import rewrite
from artagent.graph.search import (
    _extract_query_and_constraints,
    create_search_github_node,
    create_search_rawpedia_node,
    resolve_github_targets,
)
from artagent.graph.state import IntentSignals, RequestContext, RequestInput
from scripts.run_t14_ab_eval import validate_generation_cache


ROOT = Path(__file__).resolve().parents[1]
QUERY_SET = json.loads((ROOT / "docs/search_eval_queries.json").read_text(encoding="utf-8"))
QUERIES = {entry["query_id"]: entry["query"] for entry in QUERY_SET["queries"]}


def _policy_literals(constraints: tuple[str, ...]) -> list[str]:
    """설명 문구와 무관하게 별도 JSON 데이터 목록을 확인한다."""
    candidates = []
    for constraint in constraints:
        start = constraint.find("[")
        if start < 0:
            continue
        try:
            value = json.loads(constraint[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            candidates.append(value)
    assert len(candidates) == 1, "보존 대상은 별도의 JSON 데이터 목록이어야 한다"
    return candidates[0]


def test_preservation_policy_has_a_separate_version() -> None:
    assert rewrite.PRESERVATION_POLICY_VERSION == "literal_preservation_v3"
    assert rewrite.REWRITE_PROMPT_VERSION == "rewrite_v2"
    assert rewrite.HYDE_PROMPT_VERSION == "hyde_v3"


def test_policy_lists_only_input_literals_including_products_and_files() -> None:
    query = "RawTherapee ART RAW rocks.md ART-165b246-linux64 #524 1.26.8 1차 Linux -Y .arp"
    constraints = rewrite.build_preservation_constraints(query)
    assert isinstance(constraints, tuple)
    assert all(isinstance(item, str) for item in constraints)
    assert rewrite.PRESERVATION_POLICY_VERSION in " ".join(constraints)
    literals = _policy_literals(constraints)
    assert len(literals) == len(set(literals))
    assert {"RawTherapee", "ART", "RAW", "rocks.md", "ART-165b246-linux64",
            "#524", "1.26.8", "1", "Linux", "-Y", ".arp"} <= set(literals)
    assert not any(item.startswith(("rawpedia:", "github:")) for item in literals)
    assert "#500" not in literals


def test_policy_does_not_invent_product_literals() -> None:
    constraints = rewrite.build_preservation_constraints("Temperature slider operation")
    assert _policy_literals(constraints) == []


def test_policy_explicitly_requires_standalone_literal_tokens() -> None:
    instruction = rewrite.build_preservation_constraints("Flatpak 1차 nightly")[0]
    assert "standalone tokens" in instruction
    assert "Never hyphenate" in instruction
    assert "'st', 'nd', 'rd', 'th'" in instruction


@pytest.mark.parametrize(
    "query_id,rewritten",
    [
        ("Q010", "ART Local Contrast Darkness Level Lightness Level sliders affected areas behavior when both set to 0"),
        ("Q077", "ART reusable processing profile partial save Ctrl+Save Auto Levels WB noise reduction compatibility"),
    ],
)
def test_fixed_questions_reject_added_product_scope(query_id: str, rewritten: str) -> None:
    original = QUERIES[query_id]
    result = rewrite.rewrite_query(
        original, generate=lambda _: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "error"
    assert result.error_category == "PRODUCT_SCOPE_VIOLATION"
    assert result.rewritten_query == ""
    assert "ART" in result.error_message


@pytest.mark.parametrize(
    "original,rewritten",
    [
        ("exposure slider", "ART exposure slider"),
        ("exposure slider", "art exposure slider"),
        ("exposure slider", "ART-cli exposure slider"),
        ("exposure slider", "Another RawTherapee exposure slider"),
        ("exposure slider", "RawTherapee exposure slider"),
        ("exposure slider", "rawtherapee exposure slider"),
        ("RawTherapee exposure slider", "RawTherapee and ART exposure slider"),
        ("ART exposure slider", "ART and RawTherapee exposure slider"),
    ],
)
def test_policy_rejects_introduced_products(original: str, rewritten: str) -> None:
    result = rewrite.rewrite_query(
        original, generate=lambda _: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "error"
    assert result.error_category == "PRODUCT_SCOPE_VIOLATION"
    assert result.rewritten_query == ""


@pytest.mark.parametrize(
    "original,rewritten",
    [
        ("exposure slider", "exposure slider starting value"),
        ("ART exposure slider", "ART (Another RawTherapee) exposure slider"),
        ("rawtherapee exposure slider", "RawTherapee exposure slider"),
        ("ART and RawTherapee comparison", "ART and RawTherapee exposure comparison"),
        ("ART에서 노출 조정", "ART exposure adjustment"),
    ],
)
def test_product_guard_accepts_existing_scope_and_word_boundaries(original: str, rewritten: str) -> None:
    result = rewrite.rewrite_query(
        original, generate=lambda _: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "success", result.error_message


def test_product_explicitly_named_in_context_is_allowed() -> None:
    original = "exposure slider"
    context = ("Goal: ART exposure adjustment",)
    result = rewrite.rewrite_query(
        original, generate=lambda _: "ART exposure slider adjustment",
        constraints=context + rewrite.build_preservation_constraints(" ".join((original, *context))),
    )
    assert result.status == "success", result.error_message


def test_scope_metadata_cannot_authorize_a_product_absent_from_input() -> None:
    original = "exposure slider"
    constraints = tuple(
        'Allowed product scope (JSON data): {"products": ["ART"]}'
        if condition.startswith("Allowed product scope (JSON data): ") else condition
        for condition in rewrite.build_preservation_constraints(original)
    )
    result = rewrite.rewrite_query(original, generate=lambda _: "ART exposure slider", constraints=constraints)
    assert result.status == "error"
    assert result.error_category == "PRODUCT_SCOPE_VIOLATION"


def test_legacy_prompt_is_unchanged_without_scope_policy() -> None:
    result = rewrite.rewrite_query("exposure slider", generate=lambda _: "ART exposure slider")
    assert result.status == "success"


@pytest.mark.parametrize("factory", [create_search_rawpedia_node, create_search_github_node])
def test_graph_does_not_search_an_introduced_product(factory) -> None:
    store = MagicMock()
    observed = []
    result = factory(
        store, MagicMock(), generate=lambda _: "ART exposure slider", rewrite_enabled=True,
        observe=observed.append,
    )({"request": RequestInput(request_id="introduced_product", text="exposure slider")})
    assert result["error"].code == "REWRITE_FAILED"
    assert "PRODUCT_SCOPE_VIOLATION" in result["error"].message
    assert "retrieval" not in result
    store.search.assert_not_called()
    assert observed[0]["search_call_count"] == 0


@pytest.mark.parametrize(
    "query_id,rewritten",
    [
        ("Q060", "RawTherapee Local adjustments RT-spot center C, 4 TBLR boundary points, 3 Dissymetry Transition Color gradients"),
        ("Q070", "RawTherapee rocks.md Selective Editing RT-spots count and GHS tools applied to first spot"),
        ("Q082", "ART GitHub Discussion #420 Flatpak PhotoGIMP external editor wrapper shell script file argument forwarding"),
        ("Q094", "GitHub Issue #524 ART 1.26.8 1 nightly build ART-165b246-linux64 crash symptoms and final fixed nightly identifier"),
    ],
)
def test_fixed_question_rewrites_preserve_all_literals(query_id: str, rewritten: str) -> None:
    original = QUERIES[query_id]
    result = rewrite.rewrite_query(
        original, generate=lambda prompt: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "success", result.error_message
    assert result.rewritten_query == rewritten


@pytest.mark.parametrize(
    "query_id,rewritten",
    [
        ("Q060", "RawTherapee Local adjustments RT-spot center C, four TBLR boundary points, 3 Dissymetry Transition Color gradients"),
        ("Q060", "RawTherapee Local adjustments RT-spot center C, 4 TBLR boundary points, Dissymetry Transition Color gradients"),
        ("Q070", "ART rocks.md Selective Editing RT-spots count and GHS tools applied to first spot"),
        ("Q082", "ART GitHub Discussion #420 Flatpak-based PhotoGIMP external editor wrapper shell script file argument forwarding"),
        ("Q094", "GitHub Issue #524 ART 1.26.8 first nightly build ART-165b246-linux64 crash symptoms and final fixed nightly identifier"),
    ],
)
def test_fixed_question_identifier_regressions_are_rejected(query_id: str, rewritten: str) -> None:
    original = QUERIES[query_id]
    result = rewrite.rewrite_query(
        original, generate=lambda prompt: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "error"
    assert result.error_category == rewrite.ERROR_MISSING_IDENTIFIER
    assert result.rewritten_query == ""


@pytest.mark.parametrize(
    "original,rewritten,missing",
    [
        ("ART exposure slider", "exposure slider", "ART"),
        ("RawTherapee rocks.md tutorial", "RawTherapee tutorial", "rocks.md"),
        ("ART-165b246-linux64 crash", "ART nightly crash", "ART-165b246-linux64"),
    ],
)
def test_policy_rejects_missing_extended_literals(original: str, rewritten: str, missing: str) -> None:
    result = rewrite.rewrite_query(
        original, generate=lambda prompt: rewritten,
        constraints=rewrite.build_preservation_constraints(original),
    )
    assert result.status == "error"
    assert result.error_category == rewrite.ERROR_MISSING_IDENTIFIER
    assert missing in result.error_message


@pytest.mark.parametrize("replacement", ["1st", "1.26.8"])
def test_number_cannot_be_replaced_by_ordinal_suffix_or_version(replacement: str) -> None:
    preserved, missing = rewrite.validate_identifier_preservation(
        "1차 빌드", f"{replacement} nightly build", extra_identifiers=("1",),
    )
    assert preserved is False
    assert "1" in missing


def test_extra_literals_are_opt_in_for_legacy_validation() -> None:
    assert rewrite.validate_identifier_preservation("ART exposure", "exposure") == (True, [])
    assert rewrite.validate_identifier_preservation(
        "ART exposure", "exposure", extra_identifiers=("ART",),
    ) == (False, ["ART"])


def _context_state() -> dict:
    return {
        "request": RequestInput(
            request_id="preservation_context", text="RawTherapee rocks.md tutorial",
            context=RequestContext(os="Linux", art_version="1.26.8", confirmed_goal="Preserve highlights"),
        ),
        "signals": IntentSignals(constraints=["RAW output"]),
    }


def test_legacy_state_extraction_keeps_existing_constraints() -> None:
    query, constraints = _extract_query_and_constraints(_context_state(), preserve_literals=False)
    assert query == "RawTherapee rocks.md tutorial"
    assert constraints == ("OS: Linux", "Version: 1.26.8", "Goal: Preserve highlights", "RAW output")


def test_policy_extraction_preserves_query_and_context_identifiers() -> None:
    state = _context_state()
    query, constraints = _extract_query_and_constraints(state, preserve_literals=True)
    expected_base = ("OS: Linux", "Version: 1.26.8", "Goal: Preserve highlights", "RAW output")
    assert constraints[:len(expected_base)] == expected_base
    assert constraints[len(expected_base):] == rewrite.build_preservation_constraints(
        " ".join((query, *expected_base)),
    )
    assert {"RawTherapee", "rocks.md", "Linux", "1.26.8", "RAW"} <= set(_policy_literals(constraints))


@pytest.mark.parametrize("factory", [create_search_rawpedia_node, create_search_github_node])
def test_search_nodes_use_preservation_policy_for_enabled_rewrites(factory) -> None:
    store = MagicMock()
    store.search.return_value = []
    generate = MagicMock(return_value="RawTherapee rocks.md tutorial Linux 1.26.8 RAW Preserve highlights")
    result = factory(store, MagicMock(), generate=generate, rewrite_enabled=True)(_context_state())
    assert result["error"] is None
    assert generate.call_count == 1
    prompt = generate.call_args.args[0]
    assert rewrite.PRESERVATION_POLICY_VERSION in prompt
    assert '"rocks.md"' in prompt
    assert store.search.call_args.args[0] == generate.return_value


def test_original_generation_cache_remains_valid_without_new_policy() -> None:
    cache = json.loads((ROOT / "data/eval/t14-live-20261014-final/generation_cache.json").read_text(encoding="utf-8"))
    validate_generation_cache(cache, QUERY_SET)
    assert cache["rewrite_prompt_version"] == "rewrite_v2"
    assert all(
        "literal_preservation_v1" not in stages["rewrite"]["prompt"]
        for stages in cache["entries"].values()
    )


def test_discussion_source_organization_url_sets_the_target() -> None:
    assert resolve_github_targets(
        "https://github.com/orgs/artraweditor/discussions/424",
    ) == ["github:artraweditor/ART:discussion:424"]


def test_discussion_source_urls_preserve_target_with_case_and_comment_fragments() -> None:
    source_urls = [
        "https://GITHUB.com/ARTRAWEDITOR/art/discussions/424#discussioncomment-15601",
        "HTTPS://Github.COM/ORGS/ARTRAWEDITOR/DISCUSSIONS/424#discussioncomment-15601",
        "https://github.com/orgs/artraweditor/discussions/424#discussioncomment-15601",
    ]
    for source_url in source_urls:
        assert resolve_github_targets(source_url) == ["github:artraweditor/ART:discussion:424"], source_url


def test_discussion_source_url_target_is_deduplicated_across_query_and_request() -> None:
    query = "https://github.com/orgs/artraweditor/discussions/424#discussioncomment-15601"
    request = "https://github.com/orgs/artraweditor/discussions/424"
    assert resolve_github_targets(query, request) == ["github:artraweditor/ART:discussion:424"]
    assert resolve_github_targets(
        f"{query} https://github.com/artraweditor/ART/discussions/424", request,
    ) == ["github:artraweditor/ART:discussion:424"]


def test_discussion_source_urls_from_other_organizations_are_not_art_targets() -> None:
    for source_url in [
        "https://github.com/orgs/other-editor/discussions/424",
        "https://github.com/other-editor/ART/discussions/424#discussioncomment-15601",
    ]:
        assert resolve_github_targets(source_url) is None, source_url
