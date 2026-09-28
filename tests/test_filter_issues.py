"""ART GitHub Issues·Discussions 정제 파이프라인 단위 및 회귀 테스트."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artagent.issue_filter import (
    FilterError,
    compute_thread_sha256,
    filter_corpus,
    load_sources,
)

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "issue_filter"
CORPUS_DIR = FIXTURE_DIR / "corpus"
CURATION_PATH = FIXTURE_DIR / "curation-decisions.json"
DATA_ISSUES_DIR = ROOT / "data" / "issues"
PYTHON_BIN = sys.executable


# ---------------------------------------------------------------------------
# Actual Fixture Verification Tests
# ---------------------------------------------------------------------------


def test_actual_issue_500_schema_and_excerpt_roundtrip():
    """raw.id와 number를 구별하고 67문자 답변, URL, file/body SHA 및 슬라이스 일치를 검증한다."""
    cands_doc, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_500 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:500")

    assert cand_500["source_id"] == "4667542094"
    assert cand_500["source_number"] == 500
    assert cand_500["source_type"] == "issue"
    assert cand_500["url"] == "https://github.com/artraweditor/ART/issues/500"
    assert cand_500["accepted_content"] is None

    # Curated content slice check
    assert len(cand_500["curated_content"]) == 2
    context_item = cand_500["curated_content"][0]
    explanation_item = cand_500["curated_content"][1]

    assert context_item["role"] == "context"
    assert context_item["ref_id"] == "issue:500"
    assert context_item["char_start"] == 0
    assert context_item["char_end"] == 219

    assert explanation_item["role"] == "explanation"
    assert explanation_item["ref_id"] == "issue-comment:4711197631"
    assert explanation_item["char_start"] == 0
    assert explanation_item["char_end"] == 67
    assert explanation_item["text"] == 'Yes, there\'s no option. The quality is fixed to "visually lossless"'

    # Verify SHA in source locations
    loc_parent = next(l for l in cand_500["source_locations"] if l["ref_id"] == "issue:500")
    loc_comment = next(l for l in cand_500["source_locations"] if l["ref_id"] == "issue-comment:4711197631")

    assert loc_parent["file_sha256"] == "210e95a36a0726bbb7fbb3ee1949cd8af571367cc44127228c5ea6360506bc8f"
    assert loc_parent["body_sha256"] == "590abe7e573eb2a063c3d46872800ad348b60282ff79ed4ee0eb9edbd12bff76"
    assert loc_comment["file_sha256"] == "32dcb0afb1e0f5a456a78c7d3e16a4b512ad1d244b58f75af53a1895147d8cad"
    assert loc_comment["body_sha256"] == "1a72636b6373fabc9ebbd0e99ee806d629fcf943837d8059a87a247e14473dc2"


def test_actual_discussion_420_has_no_accepted_signal():
    """Discussion 420의 wrapper 보존, accepted_content=null, not_collected 및 감사 댓글 비선택을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_420 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:420")

    assert cand_420["accepted_content"] is None
    assert cand_420["metadata"]["accepted_answer_availability"] == "not_collected"
    assert cand_420["metadata"]["platform_fields"]["reactions"] is None
    assert cand_420["metadata"]["platform_fields"]["category"] == "Q&A"

    # Wrapper script preserved
    guidance = cand_420["curated_content"][1]
    assert guidance["ref_id"] == "discussion-comment:DC_kwDONWPV1M4A6DN4"
    assert "/usr/bin/flatpak run" in guidance["text"]

    # Comment 15218439 ("Thank you so much!") is not selected
    selected_refs = {c["ref_id"] for c in cand_420["curated_content"]}
    assert "discussion-comment:DC_kwDONWPV1M4A6DcH" not in selected_refs


def test_actual_org_discussion_and_repo_comment_join():
    """Discussion 420의 org URL 부모와 repo URL 댓글이 올바르게 연결됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_420 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:420")

    loc_parent = next(l for l in cand_420["source_locations"] if l["ref_id"] == "discussion:D_kwDONWPV1M4AjNbf")
    loc_comment = next(l for l in cand_420["source_locations"] if l["ref_id"] == "discussion-comment:DC_kwDONWPV1M4A6DN4")

    assert loc_parent["url"] == "https://github.com/orgs/artraweditor/discussions/420"
    assert loc_comment["url"] == "https://github.com/artraweditor/ART/discussions/420#discussioncomment-15217528"
    assert loc_comment["source_number"] == 420


def test_actual_idea_with_guidance_is_included():
    """Ideas 카테고리인 424와 489가 유효한 기술 지침이 있어 후보에 포함됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_ids = {c["candidate_id"] for c in cands_doc["candidates"]}

    assert "github:artraweditor/ART:discussion:424" in cand_ids
    assert "github:artraweditor/ART:discussion:489" in cand_ids

    cand_424 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:424")
    assert "LUT" in cand_424["curated_content"][1]["text"]

    cand_489 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:489")
    assert "roundness to 100%" in cand_489["curated_content"][1]["text"]


def test_actual_short_explanation_is_not_length_filtered():
    """500의 짧은 67문자 답변이 임의의 길이 임계치로 걸러지지 않음을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_500 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:500")
    assert len(cand_500["curated_content"][1]["text"]) == 67


def test_actual_mask_limitations_are_preserved():
    """Discussion 442의 후속 도구 제한 및 copy/paste 제약 원문과 limitation이 보존됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_442 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:442")

    caveat = cand_442["curated_content"][2]
    assert "pipeline" in caveat["text"]
    assert "copy/paste" in caveat["text"]
    assert len(cand_442["metadata"]["limitations"]) >= 1


def test_actual_lensfun_path_confirmation():
    """Issue 521에서 제안과 동작 확인이 연결되고 version_1 경로가 보존됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_521 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:521")

    assert "version_1" in cand_521["curated_content"][2]["text"]
    ev = cand_521["metadata"]["evidence"][0]
    assert ev["signal"] == "USER_CONFIRMED_ACTION"
    assert ev["content_index"] == 2
    assert ev["confirms_content_index"] == 1


def test_actual_build_and_cache_case_is_not_duplicate():
    """Issue 516이 503에 병합되지 않고 캐시 삭제 맥락 및 related_to 관계를 유지함을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_516 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:516")

    assert "LibRaw: N/A" in cand_516["curated_content"][1]["text"]
    assert "cache clearing helped" in cand_516["curated_content"][3]["text"]
    rel = cand_516["metadata"]["relations"][0]
    assert rel["relation"] == "related_to"
    assert rel["target_record_key"] == "issue:503"


def test_actual_fix_and_counterexample_sequence():
    """Issue 524의 이전 nightly 실패 반례와 b11089b 성공이 보존되고 510과 follow_up_to로 연결됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_524 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:524")

    # Counterexample (earlier nightly failure) preserved
    assert "froze and crashed" in cand_524["curated_content"][1]["text"]
    # Success confirmed
    assert "b11089b-linux64" in cand_524["curated_content"][3]["text"]

    rel = cand_524["metadata"]["relations"][0]
    assert rel["relation"] == "follow_up_to"
    assert rel["target_record_key"] == "issue:510"


def test_actual_closed_issue_without_solution_is_review():
    """Issue 510이 closed/completed 상태이고 협력자 댓글이 있어도 review로 유지됨을 검증한다."""
    cands_doc, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_ids = {c["candidate_id"] for c in cands_doc["candidates"]}
    assert "github:artraweditor/ART:issue:510" not in cand_ids

    th_510 = next(t for t in report_doc["threads"] if t["record_key"] == "issue:510")
    assert th_510["decision"] == "review"
    assert "INSUFFICIENT_EVIDENCE" in th_510["reason_codes"]


def test_actual_unresolved_conflicting_report_is_review():
    """Issue 511의 Mode=0 우회 보고가 상충 증거로 인해 review로 유지됨을 검증한다."""
    cands_doc, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_ids = {c["candidate_id"] for c in cands_doc["candidates"]}
    assert "github:artraweditor/ART:issue:511" not in cand_ids

    th_511 = next(t for t in report_doc["threads"] if t["record_key"] == "issue:511")
    assert th_511["decision"] == "review"
    assert "CONFLICTING_EVIDENCE" in th_511["reason_codes"]


def test_actual_importer_is_not_original_speaker():
    """Issue 1 댓글에서 API 작성자 agriggio와 원본 작성자 Gaaned92가 구별되고 원본 association이 null임을 검증한다."""
    inv = load_sources(CORPUS_DIR)
    comment_1 = inv.items["issue-comment:2507490549"]

    assert comment_1.actor.api_login == "agriggio"
    assert comment_1.actor.api_association == "COLLABORATOR"
    assert comment_1.actor.origin == "bitbucket_migration"
    assert comment_1.actor.original_display_name == "Gaaned92"
    assert comment_1.actor.original_github_login == "Gaaned92"
    assert comment_1.actor.original_bitbucket_login == "Gaaned92"
    assert comment_1.actor.original_association is None


def test_actual_empty_discussion_and_ack_is_excluded():
    """Discussion 525가 body 공백 및 확인 인사 댓글로 인해 NO_SUBSTANTIVE_CONTEXT로 제외됨을 검증한다."""
    _, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    th_525 = next(t for t in report_doc["threads"] if t["snapshot_path"] == "snapshots/discussions/525.json")

    assert th_525["decision"] == "exclude"
    assert "NO_SUBSTANTIVE_CONTEXT" in th_525["reason_codes"]


def test_actual_migration_filler_is_excluded():
    """10개의 bitbucket 이관 placeholder가 MIGRATION_PLACEHOLDER로 자동 제외됨을 검증한다."""
    _, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    filler_nums = [84, 293, 295, 297, 301, 302, 303, 315, 319, 323]

    for num in filler_nums:
        th = next(t for t in report_doc["threads"] if t["record_key"] == f"issue:{num}")
        assert th["decision"] == "exclude"
        assert "MIGRATION_PLACEHOLDER" in th["reason_codes"]


def test_actual_release_stubs_and_substantive_announcement():
    """432와 446은 RELEASE_STUB_ONLY로 제외되고, 토론이 있는 436은 review로 유지됨을 검증한다."""
    _, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)

    th_432 = next(t for t in report_doc["threads"] if t["snapshot_path"] == "snapshots/discussions/432.json")
    th_446 = next(t for t in report_doc["threads"] if t["snapshot_path"] == "snapshots/discussions/446.json")
    th_436 = next(t for t in report_doc["threads"] if t["snapshot_path"] == "snapshots/discussions/436.json")

    assert th_432["decision"] == "exclude"
    assert "RELEASE_STUB_ONLY" in th_432["reason_codes"]

    assert th_446["decision"] == "exclude"
    assert "RELEASE_STUB_ONLY" in th_446["reason_codes"]

    assert th_436["decision"] == "review"


def test_actual_email_footer_is_not_selected():
    """Discussion 494에서 성공 확인 본문만 선택되고 이메일 알림 푸터와 인용문이 제외됨을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_494 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:discussion:494")

    confirm_item = cand_494["curated_content"][3]
    assert confirm_item["ref_id"] == "discussion-comment:DC_kwDONWPV1M4BBpDW"
    assert "it works perfectly :)" in confirm_item["text"]
    assert "Sent with [Proton Mail]" not in confirm_item["text"]
    assert "unsubscribe" not in confirm_item["text"]


def test_actual_possible_conversion_is_not_confirmed():
    """Issue 517과 Discussion 519의 관계가 확정 duplicate가 아닌 possible_conversion으로 보존됨을 검증한다."""
    _, report_doc = filter_corpus(CORPUS_DIR, CURATION_PATH)
    th_517 = next(t for t in report_doc["threads"] if t["record_key"] == "issue:517")

    assert th_517["decision"] == "review"
    cur_dec = json.loads(CURATION_PATH.read_text())["threads"]["issue:517"]
    rel = cur_dec["relations"][0]
    assert rel["relation"] == "possible_conversion"
    assert rel["target_record_key"] == "discussion:D_kwDONWPV1M4Aoba5"


# ---------------------------------------------------------------------------
# Synthetic Edge Case Tests
# ---------------------------------------------------------------------------


def test_synthetic_missing_author_and_null_body(tmp_path):
    """author가 null이거나 body가 null일 때 예외 없이 처리되며, null body에 문자 범위 include는 실패함을 검증한다."""
    # Copy corpus to tmp_path
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Set issue 500 body to null in raw snapshot
    issue_500_path = tmp_path / "corpus" / state["records"]["issue:500"]["storage_path"]
    issue_raw = json.loads(issue_500_path.read_text())
    issue_raw["body"] = None
    issue_raw["user"] = None
    issue_500_path.write_text(json.dumps(issue_raw))

    # Re-reading inventory should succeed
    inv = load_sources(tmp_path / "corpus")
    item = inv.items["issue:500"]
    assert item.body == ""
    assert item.actor.api_login is None

    # But curation include with positive char range must fail
    th_500 = next(t for t in inv.threads if t.record_key == "issue:500")
    cur_doc = json.loads(CURATION_PATH.read_text())
    cur_doc["threads"]["issue:500"]["thread_sha256"] = th_500.thread_sha256
    cur_file = tmp_path / "curation.json"
    cur_file.write_text(json.dumps(cur_doc))

    with pytest.raises(FilterError, match="out of bounds"):
        filter_corpus(tmp_path / "corpus", cur_file)


def test_synthetic_closed_association_reactions_are_not_sufficient(tmp_path):
    """원문 검토 없이 closed/completed/COLLABORATOR 및 높은 반응 수만으로 후보가 생성되지 않음을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    # Empty curation
    cur_file = tmp_path / "curation.json"
    cur_file.write_text(json.dumps({
        "schema_version": 1,
        "rules_version": "t10-2a-v1",
        "repository": "artraweditor/ART",
        "threads": {}
    }))

    cands_doc, report_doc = filter_corpus(tmp_path / "corpus", cur_file)
    assert len(cands_doc["candidates"]) == 0
    assert report_doc["counts"]["candidate_count"] == 0
    assert report_doc["counts"]["include_count"] == 0


def test_synthetic_open_case_can_have_reviewed_guidance(tmp_path):
    """open 상태의 이슈라도 검토된 유효 지침이 있으면 정상적으로 후보로 포함됨을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    # Change issue 500 state to open
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())
    issue_path = tmp_path / "corpus" / state["records"]["issue:500"]["storage_path"]
    raw = json.loads(issue_path.read_text())
    raw["state"] = "open"
    raw["state_reason"] = None
    issue_path.write_text(json.dumps(raw))

    # Recalculate thread SHA
    inv = load_sources(tmp_path / "corpus")
    th_500 = next(t for t in inv.threads if t.record_key == "issue:500")

    cur_doc = json.loads(CURATION_PATH.read_text())
    cur_doc["threads"]["issue:500"]["thread_sha256"] = th_500.thread_sha256
    cur_file = tmp_path / "curation.json"
    cur_file.write_text(json.dumps(cur_doc))

    cands_doc, _ = filter_corpus(tmp_path / "corpus", cur_file)
    cand_500 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:500")
    assert cand_500["metadata"]["platform_fields"]["state"] == "open"


def test_synthetic_quotes_and_crlf_offsets(tmp_path):
    """CRLF 및 유니코드가 포함된 raw body에서 슬라이스가 정확히 복원됨을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())
    issue_path = tmp_path / "corpus" / state["records"]["issue:500"]["storage_path"]
    raw = json.loads(issue_path.read_text())
    
    # Introduce CRLF and unicode emoji
    special_body = "Line 1\r\nLine 2 with emoji 🎨\r\n> Quoted text: works fine!\r\nLast line"
    raw["body"] = special_body
    issue_path.write_text(json.dumps(raw))

    inv = load_sources(tmp_path / "corpus")
    th_500 = next(t for t in inv.threads if t.record_key == "issue:500")

    # Curate line 2 with emoji
    start = special_body.index("Line 2")
    end = special_body.index("\r\n> Quoted")
    expected_slice = special_body[start:end]

    cur_doc = json.loads(CURATION_PATH.read_text())
    cur_doc["threads"]["issue:500"]["thread_sha256"] = th_500.thread_sha256
    cur_doc["threads"]["issue:500"]["curated_content"][0]["char_start"] = start
    cur_doc["threads"]["issue:500"]["curated_content"][0]["char_end"] = end

    cur_file = tmp_path / "curation.json"
    cur_file.write_text(json.dumps(cur_doc))

    cands_doc, _ = filter_corpus(tmp_path / "corpus", cur_file)
    cand_500 = next(c for c in cands_doc["candidates"] if c["candidate_id"] == "github:artraweditor/ART:issue:500")
    assert cand_500["curated_content"][0]["text"] == expected_slice


def test_synthetic_same_text_different_sources_stay_distinct(tmp_path):
    """서로 다른 부모가 동일한 본문을 갖더라도 본문 해시만으로 중복 제거되지 않음을 검증한다."""
    cands_doc, _ = filter_corpus(CORPUS_DIR, CURATION_PATH)
    cand_ids = [c["candidate_id"] for c in cands_doc["candidates"]]
    # All candidates have distinct candidate_ids
    assert len(cand_ids) == len(set(cand_ids))


def test_synthetic_new_comment_invalidates_curation(tmp_path):
    """비선택 댓글이 추가되거나 변경되어 thread_sha256이 달라지면 STALE_CURATION으로 전환됨을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Modify an unselected comment of issue 500 (comment 4717365452)
    c_path = tmp_path / "corpus" / state["records"]["issue-comment:4717365452"]["storage_path"]
    c_raw = json.loads(c_path.read_text())
    c_raw["body"] = "Wait, it actually still crashes under certain conditions!"
    c_path.write_text(json.dumps(c_raw))

    # Run filter_corpus with original curation (which has old thread_sha256)
    cands_doc, report_doc = filter_corpus(tmp_path / "corpus", CURATION_PATH)
    cand_ids = {c["candidate_id"] for c in cands_doc["candidates"]}
    assert "github:artraweditor/ART:issue:500" not in cand_ids

    th_500 = next(t for t in report_doc["threads"] if t["record_key"] == "issue:500")
    assert th_500["decision"] == "review"
    assert "STALE_CURATION" in th_500["reason_codes"]
    assert report_doc["counts"]["stale_count"] == 1


def test_synthetic_invalid_reference_and_range_fail(tmp_path):
    """다른 부모의 댓글 참조, 역순/초과 범위, bool ID 등 잘못된 참조에서 실패함을 검증한다."""
    cur_doc = json.loads(CURATION_PATH.read_text())

    # 1. Reverse range
    cur_doc_bad = copy.deepcopy(cur_doc)
    cur_doc_bad["threads"]["issue:500"]["curated_content"][0]["char_start"] = 50
    cur_doc_bad["threads"]["issue:500"]["curated_content"][0]["char_end"] = 10
    cur_file = tmp_path / "cur_bad1.json"
    cur_file.write_text(json.dumps(cur_doc_bad))
    with pytest.raises(FilterError, match="out of bounds"):
        filter_corpus(CORPUS_DIR, cur_file)

    # 2. Reference comment of another issue
    cur_doc_bad2 = copy.deepcopy(cur_doc)
    cur_doc_bad2["threads"]["issue:500"]["curated_content"][1]["record_key"] = "issue-comment:4428738434"
    cur_file2 = tmp_path / "cur_bad2.json"
    cur_file2.write_text(json.dumps(cur_doc_bad2))
    with pytest.raises(FilterError, match="references unknown record"):
        filter_corpus(CORPUS_DIR, cur_file2)


def test_synthetic_manifest_integrity_and_unsafe_paths_fail(tmp_path):
    """누락 원문, 손상된 JSON, 상위 경로 탈출(../)에 대해 FilterError가 발생함을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Traversal attack
    state["records"]["issue:500"]["storage_path"] = "snapshots/../../etc/passwd"
    state_file.write_text(json.dumps(state))

    with pytest.raises(FilterError, match="escapes input directory"):
        load_sources(tmp_path / "corpus")


def test_synthetic_other_repo_url_and_fragment_mismatch_fail(tmp_path):
    """다른 저장소 URL이거나 fragment 숫자가 일치하지 않는 경우 FilterError가 발생함을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Alter comment issue_url to point to other repo
    c_path = tmp_path / "corpus" / state["records"]["issue-comment:4711197631"]["storage_path"]
    c_raw = json.loads(c_path.read_text())
    c_raw["issue_url"] = "https://api.github.com/repos/eviluser/ART/issues/500"
    c_path.write_text(json.dumps(c_raw))

    with pytest.raises(FilterError, match="Invalid issue_url"):
        load_sources(tmp_path / "corpus")


def test_synthetic_duplicate_target_and_cycle_fail(tmp_path):
    """duplicate_of 대상이 포함 후보에 없거나 자기 참조/순환일 때 실패함을 검증한다."""
    cur_doc = json.loads(CURATION_PATH.read_text())
    cur_doc_bad = copy.deepcopy(cur_doc)
    cur_doc_bad["threads"]["issue:500"]["relations"] = [
        {"relation": "duplicate_of", "target_record_key": "issue:999", "reason": "duplicate of missing"}
    ]
    cur_file = tmp_path / "cur_dup.json"
    cur_file.write_text(json.dumps(cur_doc_bad))

    with pytest.raises(FilterError, match="Duplicate target issue:999 not in included candidates"):
        filter_corpus(CORPUS_DIR, cur_file)


def test_synthetic_pull_request_and_comments_are_excluded(tmp_path):
    """pull_request 키가 있는 부모와 댓글이 OUT_OF_SCOPE_PR로 제외됨을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Add pull_request key to issue 500
    issue_path = tmp_path / "corpus" / state["records"]["issue:500"]["storage_path"]
    raw = json.loads(issue_path.read_text())
    raw["pull_request"] = {"url": "https://api.github.com/repos/artraweditor/ART/pulls/500"}
    issue_path.write_text(json.dumps(raw))

    # Empty curation so there is no conflict
    cur_file = tmp_path / "curation_empty.json"
    cur_file.write_text(json.dumps({
        "schema_version": 1,
        "rules_version": "t10-2a-v1",
        "repository": "artraweditor/ART",
        "threads": {}
    }))

    cands_doc, report_doc = filter_corpus(tmp_path / "corpus", cur_file)
    th_500 = next(t for t in report_doc["threads"] if t["record_key"] == "issue:500")
    assert th_500["decision"] == "exclude"
    assert "OUT_OF_SCOPE_PR" in th_500["reason_codes"]
    # Comments should also be ignored with OUT_OF_SCOPE_PR
    assert all("OUT_OF_SCOPE_PR" in cd["reason_codes"] for cd in th_500["comment_decisions"])


# ---------------------------------------------------------------------------
# CLI and Determinism Tests
# ---------------------------------------------------------------------------


def test_cli_generation_check_and_mismatch(tmp_path):
    """CLI 생성 후 check 성공, 바이트 1개 변조 시 check=1 반환을 검증한다."""
    out_file = tmp_path / "candidates.json"
    rep_file = tmp_path / "report.json"

    cmd = [
        PYTHON_BIN,
        str(ROOT / "scripts" / "filter_issues.py"),
        "--input-dir", str(CORPUS_DIR),
        "--curation", str(CURATION_PATH),
        "--output", str(out_file),
        "--report", str(rep_file),
    ]

    # Generate
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert out_file.is_file()
    assert rep_file.is_file()

    # Check mode
    res_check = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
    assert res_check.returncode == 0, res_check.stderr

    # Tamper with 1 byte in output
    original_bytes = out_file.read_bytes()
    tampered_bytes = original_bytes.replace(b"issue:500", b"issue:501", 1)
    out_file.write_bytes(tampered_bytes)

    # Check mode should now fail with code 1
    res_tampered = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
    assert res_tampered.returncode == 1
    assert "Check failed" in res_tampered.stderr

    # File was not overwritten
    assert out_file.read_bytes() == tampered_bytes


def test_cli_invalid_input_does_not_overwrite(tmp_path):
    """잘못된 입력에서 종료 코드 1을 반환하고 기존 출력을 덮어쓰지 않음을 검증한다."""
    out_file = tmp_path / "candidates.json"
    rep_file = tmp_path / "report.json"
    out_file.write_text("existing content")
    rep_file.write_text("existing report")

    # Pass non-existent curation
    cmd = [
        PYTHON_BIN,
        str(ROOT / "scripts" / "filter_issues.py"),
        "--input-dir", str(CORPUS_DIR),
        "--curation", str(tmp_path / "non_existent.json"),
        "--output", str(out_file),
        "--report", str(rep_file),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 1
    assert out_file.read_text() == "existing content"
    assert rep_file.read_text() == "existing report"


def test_synthetic_input_change_during_read_fails(tmp_path):
    """입력 state 파일이 손상되었을 때 FilterError로 실패함을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state_file.write_text("corrupted json content")

    with pytest.raises(FilterError, match="Failed to parse sync-state.json"):
        load_sources(tmp_path / "corpus")


def test_cli_deterministic_order_and_unchanged_input(tmp_path):
    """state 레코드 순서를 바꿔도 후보 및 보고서 순서와 내용이 동일하고 mtime이 유지됨을 검증한다."""
    shutil.copytree(CORPUS_DIR, tmp_path / "corpus")
    state_file = tmp_path / "corpus" / "sync-state.json"
    state = json.loads(state_file.read_text())

    # Reverse record keys
    reversed_records = {k: state["records"][k] for k in reversed(list(state["records"].keys()))}
    state["records"] = reversed_records
    state_file.write_text(json.dumps(state))

    out_file = tmp_path / "candidates.json"
    rep_file = tmp_path / "report.json"

    cmd = [
        PYTHON_BIN,
        str(ROOT / "scripts" / "filter_issues.py"),
        "--input-dir", str(tmp_path / "corpus"),
        "--curation", str(CURATION_PATH),
        "--output", str(out_file),
        "--report", str(rep_file),
    ]

    res1 = subprocess.run(cmd, capture_output=True, text=True)
    assert res1.returncode == 0
    bytes1 = out_file.read_bytes()
    mtime1 = out_file.stat().st_mtime_ns

    # Run again without changes
    res2 = subprocess.run(cmd, capture_output=True, text=True)
    assert res2.returncode == 0
    bytes2 = out_file.read_bytes()
    mtime2 = out_file.stat().st_mtime_ns

    assert bytes1 == bytes2
    assert mtime1 == mtime2


def test_all_candidates_and_report_records_roundtrip():
    """실제 전체 data/issues 디렉터리 기준 12개 후보 전수의 원문 슬라이스, URL, 키 수지 일치를 검증한다."""
    cands_doc, report_doc = filter_corpus(
        DATA_ISSUES_DIR,
        DATA_ISSUES_DIR / "curation-decisions.json",
    )

    candidates = cands_doc["candidates"]
    assert len(candidates) == 12

    counts = report_doc["counts"]
    assert counts["candidate_count"] == 12
    assert counts["include_count"] == 12
    assert counts["exclude_count"] == 13
    assert counts["review_count"] == 470
    assert counts["thread_count"] == 495
    assert counts["include_count"] + counts["exclude_count"] + counts["review_count"] == 495
    assert counts["threads_without_accepted_answer_signal"] == 495

    inv = load_sources(DATA_ISSUES_DIR)

    # Candidate roundtrip verification
    for cand in candidates:
        source_rec_key = cand["source_record_key"]
        parent_item = inv.items[source_rec_key]
        assert cand["title"] == parent_item.raw.get("title", "")
        assert cand["url"] == parent_item.url

        for cc in cand["curated_content"]:
            target_item = inv.items[cc["ref_id"]]
            expected_slice = target_item.body[cc["char_start"]:cc["char_end"]]
            assert cc["text"] == expected_slice
