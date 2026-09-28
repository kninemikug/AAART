"""ART GitHub Issues·Discussions 정제 및 검색 후보 목록 생성 모듈.

스냅샷 원문과 동기화 상태, 원문 검토 결정을 읽어 검증하고,
검색 후보 목록(search-candidates.json)과 정제 보고서(filter-report.json)를 생성한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = 1
RULES_VERSION = "t10-2a-v1"
DEFAULT_REPOSITORY = "artraweditor/ART"

BITBUCKET_MIGRATION_PATTERN = re.compile(
    r"^\*\*(?:\[Original report\]\(https://bitbucket\.org/agriggio/art/issues/\d+\)|Original comment) by (.*?)\.\*\*$"
)
BITBUCKET_SUB_PATTERN = re.compile(
    r"^(.*?)(?:\s+\(Bitbucket:\s+\[(.*?)\]\(https://bitbucket\.org/[^\)]*\)(?:,\s*GitHub:\s+\[(.*?)\]\(https://github\.com/[^\)]*\))?.*?\))?$"
)

ACK_PHRASES = {
    "thanks",
    "thank you",
    "thank you so much",
    "ok",
    "ok thanks",
    "+1",
    "me too",
    "i have got it thanks",
    "ok i found it sorry guys",
    "thats ok thank you",
    "that is ok thank you",
    "yes",
}

POSITIVE_SIGNALS = {
    "ACTIONABLE_GUIDANCE",
    "ART_TECHNICAL_EXPLANATION",
    "SELF_CONTAINED_TECHNICAL_GUIDE",
    "USER_CONFIRMED_ACTION",
    "FIX_VERSION_CONFIRMED",
    "DETAILED_UNRESOLVED_REPORT",
}

ROLES = {
    "context",
    "guidance",
    "explanation",
    "reported_fix",
    "reproduction",
    "confirmation",
    "caveat",
}

LIMITATION_CODES = {
    "AS_OF_SOURCE_ONLY",
    "PLATFORM_SPECIFIC",
    "VERSION_SPECIFIC",
    "HYPOTHESIS",
    "COUNTEREVIDENCE",
}

RELATIONS = {
    "follow_up_to",
    "related_to",
    "duplicate_of",
    "possible_conversion",
}

KNOWLEDGE_STATUSES = {
    "curated_guidance",
    "reported_fix",
    "unresolved_report",
}


class FilterError(Exception):
    """정제 파이프라인 검증 또는 처리 오류."""


@dataclass(frozen=True)
class Actor:
    api_login: str | None
    api_association: str | None
    origin: str  # native | bitbucket_migration | migration_unknown
    original_display_name: str | None
    original_github_login: str | None
    original_bitbucket_login: str | None
    original_association: str | None  # Always None

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": {
                "api_association": self.api_association,
                "api_login": self.api_login,
                "origin": self.origin,
                "original_association": self.original_association,
                "original_bitbucket_login": self.original_bitbucket_login,
                "original_display_name": self.original_display_name,
                "original_github_login": self.original_github_login,
            }
        }


@dataclass
class SnapshotItem:
    record_key: str
    kind: str
    storage_path: str
    file_sha256: str
    raw_bytes: bytes
    raw: dict[str, Any]
    body: str
    body_sha256: str
    actor: Actor
    url: str
    created_at: str
    updated_at: str
    source_id: str
    source_number: int
    database_id: str | None


@dataclass
class Thread:
    record_key: str
    source_type: str  # issue | discussion
    parent: SnapshotItem
    comments: list[SnapshotItem]
    thread_sha256: str
    thread_updated_at: str


@dataclass
class SourceInventory:
    input_dir: Path
    state_bytes: bytes
    state_sha256: str
    snapshot_manifest_sha256: str
    state: dict[str, Any]
    items: dict[str, SnapshotItem]
    threads: list[Thread]


def parse_actor(kind: str, raw: dict[str, Any]) -> Actor:
    """원문 JSON에서 API 작성자와 Bitbucket 이관 작성자 정보를 파싱한다."""
    api_login: str | None = None
    api_association: str | None = None

    if kind in ("issue", "issue-comment"):
        user = raw.get("user")
        if isinstance(user, dict):
            api_login = user.get("login")
        api_association = raw.get("author_association")
    elif kind in ("discussion", "discussion-comment"):
        author = raw.get("author")
        if isinstance(author, dict):
            api_login = author.get("login")
        # GraphQL discussions do not have author_association collected

    body = raw.get("body")
    if not isinstance(body, str) or not body:
        return Actor(
            api_login=api_login,
            api_association=api_association,
            origin="native",
            original_display_name=None,
            original_github_login=None,
            original_bitbucket_login=None,
            original_association=None,
        )

    # Check for migration header on the first line
    first_line = body.split("\n", 1)[0].strip()
    if first_line.startswith("**[Original report]") or first_line.startswith("**Original comment"):
        m = BITBUCKET_MIGRATION_PATTERN.match(first_line)
        if m:
            info = m.group(1).strip()
            # If "by me."
            if info == "me":
                return Actor(
                    api_login=api_login,
                    api_association=api_association,
                    origin="bitbucket_migration",
                    original_display_name="me",
                    original_github_login=None,
                    original_bitbucket_login=None,
                    original_association=None,
                )
            sub_m = BITBUCKET_SUB_PATTERN.match(info)
            if sub_m:
                disp_name = sub_m.group(1).strip()
                bb_user = sub_m.group(2)
                gh_user = sub_m.group(3)
                return Actor(
                    api_login=api_login,
                    api_association=api_association,
                    origin="bitbucket_migration",
                    original_display_name=disp_name or None,
                    original_github_login=gh_user or None,
                    original_bitbucket_login=bb_user or None,
                    original_association=None,
                )
        return Actor(
            api_login=api_login,
            api_association=api_association,
            origin="migration_unknown",
            original_display_name=None,
            original_github_login=None,
            original_bitbucket_login=None,
            original_association=None,
        )

    return Actor(
        api_login=api_login,
        api_association=api_association,
        origin="native",
        original_display_name=None,
        original_github_login=None,
        original_bitbucket_login=None,
        original_association=None,
    )


def compute_file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_canonical_manifest_sha256(mapping: dict[str, str]) -> str:
    canonical_json = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()


def compute_thread_sha256(parent_key: str, parent_sha: str, comment_items: list[SnapshotItem]) -> str:
    mapping = {parent_key: parent_sha}
    for c in comment_items:
        mapping[c.record_key] = c.file_sha256
    canonical_json = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()


def is_ack_only_comment(body: str) -> bool:
    """코드 fence나 조작 지침이 없는 순수 확인/감사 댓글인지 판정한다."""
    if not body:
        return True
    if "```" in body:
        return False
    
    # Strip quotes/reply headers if present, but check basic text
    cleaned_lines = []
    for line in body.splitlines():
        line_s = line.strip()
        if line_s.startswith(">"):
            continue
        cleaned_lines.append(line_s)
    
    cleaned = " ".join(cleaned_lines).strip()
    if not cleaned:
        return True
    
    # Exact +1
    if cleaned == "+1":
        return True
    
    # Lowercase, strip punctuation and extra spaces
    norm = re.sub(r"[^\w\s]", "", cleaned.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    
    return norm in ACK_PHRASES


def load_sources(input_dir: Path) -> SourceInventory:
    """sync-state.json과 스냅샷 원문 전체를 검증하고 메모리에 적재한다."""
    state_file = input_dir / "sync-state.json"
    if not state_file.is_file():
        raise FilterError(f"sync-state.json not found in {input_dir}")

    state_bytes = state_file.read_bytes()
    state_sha256 = compute_file_sha256(state_bytes)

    try:
        state = json.loads(state_bytes.decode("utf-8"))
    except Exception as e:
        raise FilterError(f"Failed to parse sync-state.json: {e}") from e

    if state.get("version") != 1:
        raise FilterError(f"Unsupported state version: {state.get('version')}")
    if state.get("repository") != DEFAULT_REPOSITORY:
        raise FilterError(f"Repository mismatch: expected {DEFAULT_REPOSITORY}, got {state.get('repository')}")

    records = state.get("records")
    if not isinstance(records, dict):
        raise FilterError("Invalid records in sync-state.json")

    items: dict[str, SnapshotItem] = {}
    file_sha_mapping: dict[str, str] = {}
    seen_storage_paths: set[str] = set()

    for rec_key, rec in records.items():
        if not isinstance(rec, dict):
            raise FilterError(f"Record {rec_key} must be an object")
        kind = rec.get("kind")
        storage_path = rec.get("storage_path")
        object_id = rec.get("object_id")
        updated_at = rec.get("updated_at")

        if not isinstance(storage_path, str) or not storage_path.startswith("snapshots/"):
            raise FilterError(f"Invalid storage path in {rec_key}: {storage_path}")

        # Path traversal guard
        target_path = (input_dir / storage_path).resolve()
        if not target_path.is_relative_to(input_dir.resolve()):
            raise FilterError(f"Storage path escapes input directory: {storage_path}")
        if storage_path in seen_storage_paths:
            raise FilterError(f"Duplicate storage path: {storage_path}")
        seen_storage_paths.add(storage_path)

        if not target_path.is_file():
            raise FilterError(f"Snapshot file not found: {storage_path}")

        raw_bytes = target_path.read_bytes()
        file_sha = compute_file_sha256(raw_bytes)
        file_sha_mapping[storage_path] = file_sha

        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            raise FilterError(f"Invalid JSON in snapshot {storage_path}: {e}") from e

        body = raw.get("body")
        if body is None:
            body = ""
        elif not isinstance(body, str):
            raise FilterError(f"Body must be string or null in {storage_path}")

        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        actor = parse_actor(kind, raw)

        # Kind-specific validations
        if kind == "issue":
            if bool(raw.get("id")) is True and isinstance(raw.get("id"), bool):
                raise FilterError(f"Invalid id in {rec_key}")
            source_id = str(raw["id"])
            source_number = int(raw["number"])
            database_id = source_id
            url = raw.get("html_url", "")
            created_at = raw.get("created_at", "")
            rec_updated = raw.get("updated_at", "")
        elif kind == "issue-comment":
            source_id = str(raw["id"])
            database_id = source_id
            # Source number will be linked to parent
            source_number = 0
            url = raw.get("html_url", "")
            created_at = raw.get("created_at", "")
            rec_updated = raw.get("updated_at", "")
        elif kind == "discussion":
            source_id = str(raw["id"])
            source_number = int(raw["number"])
            database_id = str(raw["databaseId"]) if raw.get("databaseId") is not None else None
            url = raw.get("url", "")
            created_at = raw.get("createdAt", "")
            rec_updated = raw.get("updatedAt", "")
        elif kind == "discussion-comment":
            source_id = str(raw["id"])
            database_id = str(raw["databaseId"]) if raw.get("databaseId") is not None else None
            source_number = 0
            url = raw.get("url", "")
            created_at = raw.get("createdAt", "")
            rec_updated = raw.get("updatedAt", "")
        else:
            raise FilterError(f"Unknown kind in {rec_key}: {kind}")

        items[rec_key] = SnapshotItem(
            record_key=rec_key,
            kind=kind,
            storage_path=storage_path,
            file_sha256=file_sha,
            raw_bytes=raw_bytes,
            raw=raw,
            body=body,
            body_sha256=body_sha256,
            actor=actor,
            url=url,
            created_at=created_at,
            updated_at=rec_updated,
            source_id=source_id,
            source_number=source_number,
            database_id=database_id,
        )

    manifest_sha256 = compute_canonical_manifest_sha256(file_sha_mapping)
    threads = build_threads(items)

    return SourceInventory(
        input_dir=input_dir,
        state_bytes=state_bytes,
        state_sha256=state_sha256,
        snapshot_manifest_sha256=manifest_sha256,
        state=state,
        items=items,
        threads=threads,
    )


def build_threads(items: dict[str, SnapshotItem]) -> list[Thread]:
    """모든 레코드를 부모(Issue/Discussion)에 정확히 한 번씩 소속시켜 Thread 목록을 구성한다."""
    issues: dict[int, SnapshotItem] = {}
    discussions: dict[int, SnapshotItem] = {}
    comments_by_issue: dict[int, list[SnapshotItem]] = {}
    comments_by_discussion: dict[int, list[SnapshotItem]] = {}

    for k, item in items.items():
        if item.kind == "issue":
            issues[item.source_number] = item
            comments_by_issue[item.source_number] = []
        elif item.kind == "discussion":
            discussions[item.source_number] = item
            comments_by_discussion[item.source_number] = []

    for k, item in items.items():
        if item.kind == "issue-comment":
            issue_url = item.raw.get("issue_url", "")
            m = re.match(r"^https://api\.github\.com/repos/artraweditor/ART/issues/(\d+)$", issue_url)
            if not m:
                raise FilterError(f"Invalid issue_url in {k}: {issue_url}")
            num = int(m.group(1))
            if num not in issues:
                raise FilterError(f"Parent issue not found for comment {k}: issue {num}")
            item.source_number = num
            comments_by_issue[num].append(item)
        elif item.kind == "discussion-comment":
            url = item.raw.get("url", "")
            m = re.match(
                r"^https://github\.com/(?:artraweditor/ART|orgs/artraweditor)/discussions/(\d+)#discussioncomment-(\d+)$",
                url,
            )
            if not m:
                raise FilterError(f"Invalid discussion comment URL in {k}: {url}")
            num = int(m.group(1))
            db_id = int(m.group(2))
            if item.database_id != str(db_id):
                raise FilterError(f"Database ID mismatch in comment {k}: {item.database_id} vs {db_id}")
            if num not in discussions:
                raise FilterError(f"Parent discussion not found for comment {k}: discussion {num}")
            item.source_number = num
            comments_by_discussion[num].append(item)

    threads: list[Thread] = []

    # Sort comments by (created_at, source_id)
    def comment_sort_key(c: SnapshotItem):
        return (c.created_at, c.source_id)

    # Process issues
    for num, parent in issues.items():
        cmts = sorted(comments_by_issue[num], key=comment_sort_key)
        thread_sha = compute_thread_sha256(parent.record_key, parent.file_sha256, cmts)
        all_updates = [parent.updated_at] + [c.updated_at for c in cmts]
        thread_updated = max(all_updates) if all_updates else parent.updated_at
        threads.append(
            Thread(
                record_key=parent.record_key,
                source_type="issue",
                parent=parent,
                comments=cmts,
                thread_sha256=thread_sha,
                thread_updated_at=thread_updated,
            )
        )

    # Process discussions
    for num, parent in discussions.items():
        cmts = sorted(comments_by_discussion[num], key=comment_sort_key)
        thread_sha = compute_thread_sha256(parent.record_key, parent.file_sha256, cmts)
        all_updates = [parent.updated_at] + [c.updated_at for c in cmts]
        thread_updated = max(all_updates) if all_updates else parent.updated_at
        threads.append(
            Thread(
                record_key=parent.record_key,
                source_type="discussion",
                parent=parent,
                comments=cmts,
                thread_sha256=thread_sha,
                thread_updated_at=thread_updated,
            )
        )

    # Deterministic thread ordering: (source_type, source_number)
    threads.sort(key=lambda t: (t.source_type, t.parent.source_number))
    return threads


@dataclass
class Inspection:
    thread: Thread
    structural_disposition: str | None  # exclude | review | None
    structural_reasons: list[str]
    suggested_signals: list[str]
    comment_ack_status: dict[str, bool]


def inspect_thread(thread: Thread) -> Inspection:
    """스레드의 구조적 제외/보류 조건 및 휴리스틱 신호를 점검한다."""
    parent = thread.parent
    comments = thread.comments
    p_body = parent.body.strip()

    structural_disposition: str | None = None
    structural_reasons: list[str] = []
    suggested_signals: list[str] = []
    comment_ack_status: dict[str, bool] = {}

    # Check ack status for each comment
    for c in comments:
        comment_ack_status[c.record_key] = is_ack_only_comment(c.body)

    # 1. PR guard
    if "pull_request" in parent.raw:
        return Inspection(
            thread=thread,
            structural_disposition="exclude",
            structural_reasons=["OUT_OF_SCOPE_PR"],
            suggested_signals=[],
            comment_ack_status=comment_ack_status,
        )

    # 2. Migration placeholder
    if p_body == "filler issue created by bitbucket_issue_migration":
        if any(not comment_ack_status.get(c.record_key, False) for c in comments):
            structural_disposition = "review"
            structural_reasons = ["MIGRATION_PLACEHOLDER"]
        else:
            structural_disposition = "exclude"
            structural_reasons = ["MIGRATION_PLACEHOLDER"]
        return Inspection(
            thread=thread,
            structural_disposition=structural_disposition,
            structural_reasons=structural_reasons,
            suggested_signals=[],
            comment_ack_status=comment_ack_status,
        )

    # 3. Empty body / No substantive context
    if not p_body:
        if not comments or all(comment_ack_status.get(c.record_key, False) for c in comments):
            return Inspection(
                thread=thread,
                structural_disposition="exclude",
                structural_reasons=["NO_SUBSTANTIVE_CONTEXT"],
                suggested_signals=[],
                comment_ack_status=comment_ack_status,
            )

    # 4. Release stub only
    category = parent.raw.get("category", {}).get("name") if isinstance(parent.raw.get("category"), dict) else None
    if category == "Announcements":
        is_wrapper = (
            p_body.startswith("<hr /><em>This discussion was created from the release")
            and p_body.endswith("</em>")
        )
        is_just_released = p_body == "New version just released"
        if is_wrapper or is_just_released:
            if not comments or all(comment_ack_status.get(c.record_key, False) for c in comments):
                return Inspection(
                    thread=thread,
                    structural_disposition="exclude",
                    structural_reasons=["RELEASE_STUB_ONLY"],
                    suggested_signals=[],
                    comment_ack_status=comment_ack_status,
                )

    # Suggested heuristic signals for reporting
    full_text = parent.body + " " + " ".join(c.body for c in comments)
    if "fix" in full_text.lower() or "solved" in full_text.lower():
        suggested_signals.append("FIX_VERSION_CONFIRMED")
    if "works" in full_text.lower() or "confirm" in full_text.lower():
        suggested_signals.append("USER_CONFIRMED_ACTION")
    if "?" in parent.body and not comments:
        suggested_signals.append("UNANSWERED_QUESTION")

    return Inspection(
        thread=thread,
        structural_disposition=structural_disposition,
        structural_reasons=structural_reasons,
        suggested_signals=suggested_signals,
        comment_ack_status=comment_ack_status,
    )


@dataclass
class CuratedDecision:
    thread_sha256: str
    disposition: str  # include | exclude | review
    reviewed_by: str
    rationale: str
    reason_codes: list[str]
    knowledge_status: str | None
    curated_content: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    limitations: list[dict[str, Any]]
    relations: list[dict[str, Any]]


def apply_curation(
    thread: Thread,
    inspection: Inspection,
    raw_decision: dict[str, Any] | None,
    items_by_key: dict[str, SnapshotItem],
) -> CuratedDecision:
    """스레드에 대한 검토 결정을 적용하고 지문·범위·규칙을 검증한다."""
    # 1. Structural exclusion overrides or conflicts
    if inspection.structural_disposition == "exclude":
        if raw_decision and raw_decision.get("disposition") == "include":
            raise FilterError(
                f"Conflict in {thread.record_key}: structurally excluded by "
                f"{inspection.structural_reasons} but curated as include."
            )
        return CuratedDecision(
            thread_sha256=thread.thread_sha256,
            disposition="exclude",
            reviewed_by="filter_rules",
            rationale="Structurally excluded by filter rules.",
            reason_codes=inspection.structural_reasons,
            knowledge_status=None,
            curated_content=[],
            evidence=[],
            limitations=[],
            relations=[],
        )

    # 2. Check curation existence
    if not raw_decision:
        if inspection.structural_disposition == "review":
            return CuratedDecision(
                thread_sha256=thread.thread_sha256,
                disposition="review",
                reviewed_by="filter_rules",
                rationale="Structural review required.",
                reason_codes=inspection.structural_reasons,
                knowledge_status=None,
                curated_content=[],
                evidence=[],
                limitations=[],
                relations=[],
            )
        return CuratedDecision(
            thread_sha256=thread.thread_sha256,
            disposition="review",
            reviewed_by="filter_rules",
            rationale="Not yet reviewed.",
            reason_codes=["NOT_REVIEWED"],
            knowledge_status=None,
            curated_content=[],
            evidence=[],
            limitations=[],
            relations=[],
        )

    # 3. Check thread fingerprint staleness
    dec_thread_sha = raw_decision.get("thread_sha256")
    if dec_thread_sha != thread.thread_sha256:
        return CuratedDecision(
            thread_sha256=thread.thread_sha256,
            disposition="review",
            reviewed_by=raw_decision.get("reviewed_by", "unknown"),
            rationale="Thread fingerprint changed since curation.",
            reason_codes=["STALE_CURATION"],
            knowledge_status=None,
            curated_content=[],
            evidence=[],
            limitations=[],
            relations=[],
        )

    disposition = raw_decision.get("disposition")
    if disposition not in ("include", "exclude", "review"):
        raise FilterError(f"Invalid disposition '{disposition}' in {thread.record_key}")

    reviewed_by = raw_decision.get("reviewed_by", "")
    rationale = raw_decision.get("rationale", "")
    if not reviewed_by or not isinstance(reviewed_by, str):
        raise FilterError(f"reviewed_by must be a non-empty string in {thread.record_key}")
    if not rationale or not isinstance(rationale, str):
        raise FilterError(f"rationale must be a non-empty string in {thread.record_key}")

    reason_codes = raw_decision.get("reason_codes", [])
    if not isinstance(reason_codes, list) or not reason_codes:
        raise FilterError(f"reason_codes must be a non-empty list in {thread.record_key}")

    knowledge_status = raw_decision.get("knowledge_status")
    curated_content = raw_decision.get("curated_content", [])
    evidence = raw_decision.get("evidence", [])
    limitations = raw_decision.get("limitations", [])
    relations = raw_decision.get("relations", [])

    if disposition == "include":
        if knowledge_status not in KNOWLEDGE_STATUSES:
            raise FilterError(f"Invalid knowledge_status '{knowledge_status}' for include in {thread.record_key}")

        pos_codes = [c for c in reason_codes if c in POSITIVE_SIGNALS]
        if not pos_codes:
            raise FilterError(f"Include decision in {thread.record_key} must contain at least one positive signal code")

        if not isinstance(curated_content, list) or len(curated_content) < 2:
            raise FilterError(f"curated_content in {thread.record_key} must have at least 2 entries")

        # First entry must be parent context
        if curated_content[0].get("role") != "context" or curated_content[0].get("record_key") != thread.record_key:
            raise FilterError(f"First curated_content entry in {thread.record_key} must be parent context")

        # Validate each curated_content entry
        seen_ranges: dict[str, list[tuple[int, int]]] = {}
        thread_record_keys = {thread.parent.record_key} | {c.record_key for c in thread.comments}

        for idx, item in enumerate(curated_content):
            rec_key = item.get("record_key")
            role = item.get("role")
            c_start = item.get("char_start")
            c_end = item.get("char_end")

            if rec_key not in thread_record_keys:
                raise FilterError(f"curated_content[{idx}] in {thread.record_key} references unknown record {rec_key}")
            if role not in ROLES:
                raise FilterError(f"Invalid role '{role}' in {thread.record_key} content[{idx}]")

            # Validate char_start and char_end (must be non-bool int)
            if isinstance(c_start, bool) or not isinstance(c_start, int):
                raise FilterError(f"char_start in {thread.record_key}[{idx}] must be integer")
            if isinstance(c_end, bool) or not isinstance(c_end, int):
                raise FilterError(f"char_end in {thread.record_key}[{idx}] must be integer")

            target_item = items_by_key[rec_key]
            body_len = len(target_item.body)
            if not (0 <= c_start < c_end <= body_len):
                raise FilterError(
                    f"char range [{c_start}:{c_end}) out of bounds (len {body_len}) in {thread.record_key}[{idx}]"
                )

            # Check for range overlap in same record
            for prev_s, prev_e in seen_ranges.get(rec_key, []):
                if max(c_start, prev_s) < min(c_end, prev_e):
                    raise FilterError(f"Overlapping ranges in {rec_key} in {thread.record_key}")
            seen_ranges.setdefault(rec_key, []).append((c_start, c_end))

        # Validate evidence
        if not isinstance(evidence, list) or not evidence:
            raise FilterError(f"Include decision in {thread.record_key} must have evidence")
        for ev in evidence:
            sig = ev.get("signal")
            c_idx = ev.get("content_index")
            if sig not in POSITIVE_SIGNALS:
                raise FilterError(f"Invalid evidence signal '{sig}' in {thread.record_key}")
            if not isinstance(c_idx, int) or not (0 <= c_idx < len(curated_content)):
                raise FilterError(f"Invalid content_index '{c_idx}' in evidence of {thread.record_key}")
            if sig in ("USER_CONFIRMED_ACTION", "FIX_VERSION_CONFIRMED"):
                conf_idx = ev.get("confirms_content_index")
                if not isinstance(conf_idx, int) or not (0 <= conf_idx < len(curated_content)):
                    raise FilterError(
                        f"Confirmation signal '{sig}' in {thread.record_key} requires valid confirms_content_index"
                    )

        # Validate limitations
        if not isinstance(limitations, list) or not limitations:
            raise FilterError(f"Include decision in {thread.record_key} must have at least one limitation")
        for lim in limitations:
            l_code = lim.get("code")
            note = lim.get("note")
            c_indices = lim.get("content_indices")
            if l_code not in LIMITATION_CODES:
                raise FilterError(f"Invalid limitation code '{l_code}' in {thread.record_key}")
            if not note or not isinstance(note, str):
                raise FilterError(f"Limitation note must be non-empty string in {thread.record_key}")
            if not isinstance(c_indices, list) or not c_indices:
                raise FilterError(f"Limitation content_indices must be non-empty in {thread.record_key}")
            for c_i in c_indices:
                if not isinstance(c_i, int) or not (0 <= c_i < len(curated_content)):
                    raise FilterError(f"Invalid content_index '{c_i}' in limitation of {thread.record_key}")

    else:
        # exclude or review
        knowledge_status = None
        curated_content = []
        evidence = []
        limitations = []

    # Validate relations
    if not isinstance(relations, list):
        raise FilterError(f"relations must be list in {thread.record_key}")
    for rel in relations:
        r_type = rel.get("relation")
        target_k = rel.get("target_record_key")
        r_reason = rel.get("reason")
        if r_type not in RELATIONS:
            raise FilterError(f"Invalid relation '{r_type}' in {thread.record_key}")
        if not target_k or not isinstance(target_k, str):
            raise FilterError(f"Invalid target_record_key in {thread.record_key}")
        if target_k == thread.record_key:
            raise FilterError(f"Self-referential relation in {thread.record_key}")
        if not r_reason or not isinstance(r_reason, str):
            raise FilterError(f"Relation reason must be non-empty string in {thread.record_key}")

    return CuratedDecision(
        thread_sha256=thread.thread_sha256,
        disposition=disposition,
        reviewed_by=reviewed_by,
        rationale=rationale,
        reason_codes=reason_codes,
        knowledge_status=knowledge_status,
        curated_content=curated_content,
        evidence=evidence,
        limitations=limitations,
        relations=relations,
    )


def build_candidate(
    thread: Thread,
    decision: CuratedDecision,
    items_by_key: dict[str, SnapshotItem],
) -> dict[str, Any]:
    """포함 스레드에서 정밀한 검색 후보 객체를 구성한다."""
    parent = thread.parent
    candidate_id = f"github:artraweditor/ART:{thread.source_type}:{parent.source_number}"

    # Build curated content items
    curated_items = []
    selected_record_keys = set()
    for item in decision.curated_content:
        rec_key = item["record_key"]
        selected_record_keys.add(rec_key)
        target = items_by_key[rec_key]
        c_start = item["char_start"]
        c_end = item["char_end"]
        extracted_text = target.body[c_start:c_end]
        curated_items.append(
            {
                "char_end": c_end,
                "char_start": c_start,
                "json_pointer": "/body",
                "ref_id": rec_key,
                "role": item["role"],
                "text": extracted_text,
            }
        )

    # Build source locations for parent and selected comments
    locations = []
    # Always include parent
    needed_keys = {parent.record_key} | selected_record_keys
    for k in sorted(needed_keys):
        item = items_by_key[k]
        locations.append(
            {
                "actor": {
                    "api_association": item.actor.api_association,
                    "api_login": item.actor.api_login,
                    "origin": item.actor.origin,
                    "original_association": item.actor.original_association,
                    "original_bitbucket_login": item.actor.original_bitbucket_login,
                    "original_display_name": item.actor.original_display_name,
                    "original_github_login": item.actor.original_github_login,
                },
                "body_sha256": item.body_sha256,
                "created_at": item.created_at,
                "database_id": item.database_id,
                "file_sha256": item.file_sha256,
                "ref_id": item.record_key,
                "snapshot_path": item.storage_path,
                "source_id": item.source_id,
                "source_kind": item.kind,
                "source_number": parent.source_number,
                "updated_at": item.updated_at,
                "url": item.url,
            }
        )

    # Build metadata
    if thread.source_type == "issue":
        labels_list = [lb["name"] for lb in parent.raw.get("labels", []) if isinstance(lb, dict) and "name" in lb]
        platform_fields = {
            "author_association": parent.actor.api_association,
            "category": None,
            "labels": labels_list,
            "reactions": parent.raw.get("reactions"),
            "state": parent.raw.get("state"),
            "state_reason": parent.raw.get("state_reason"),
        }
        field_availability = {
            "author_association": True,
            "category": False,
            "labels": True,
            "reactions": True,
            "state": True,
            "state_reason": True,
        }
        accepted_answer_availability = "not_applicable"
    else:
        # Discussion
        cat_name = parent.raw.get("category", {}).get("name") if isinstance(parent.raw.get("category"), dict) else None
        platform_fields = {
            "author_association": None,
            "category": cat_name,
            "labels": None,
            "reactions": None,
            "state": None,
            "state_reason": None,
        }
        field_availability = {
            "author_association": False,
            "category": True,
            "labels": False,
            "reactions": False,
            "state": False,
            "state_reason": False,
        }
        accepted_answer_availability = "not_collected"

    metadata = {
        "accepted_answer_availability": accepted_answer_availability,
        "evidence": decision.evidence,
        "field_availability": field_availability,
        "knowledge_status": decision.knowledge_status,
        "limitations": decision.limitations,
        "platform_fields": platform_fields,
        "rationale": decision.rationale,
        "reason_codes": decision.reason_codes,
        "relations": decision.relations,
        "reviewed_by": decision.reviewed_by,
        "selection_method": "reviewed_snapshot",
        "thread_sha256": thread.thread_sha256,
        "thread_updated_at": thread.thread_updated_at,
    }

    return {
        "accepted_content": None,
        "candidate_id": candidate_id,
        "curated_content": curated_items,
        "metadata": metadata,
        "source_id": parent.source_id,
        "source_locations": locations,
        "source_number": parent.source_number,
        "source_record_key": parent.record_key,
        "source_type": thread.source_type,
        "title": parent.raw.get("title", ""),
        "url": parent.url,
    }


def validate_outputs(
    inventory: SourceInventory,
    candidates_doc: dict[str, Any],
    report_doc: dict[str, Any],
) -> None:
    """출력 스키마, 원문 복원 일치, 키 수지 일치를 엄격히 검증한다."""
    candidates = candidates_doc.get("candidates", [])
    report_threads = report_doc.get("threads", [])
    counts = report_doc.get("counts", {})

    # 1. Candidate roundtrip check
    seen_cand_ids = set()
    candidate_id_to_cand = {}
    for cand in candidates:
        cid = cand["candidate_id"]
        if cid in seen_cand_ids:
            raise FilterError(f"Duplicate candidate_id: {cid}")
        seen_cand_ids.add(cid)
        candidate_id_to_cand[cid] = cand

        if cand.get("accepted_content") is not None:
            raise FilterError(f"accepted_content must be null in candidate {cid}")

        source_rec_key = cand["source_record_key"]
        if source_rec_key not in inventory.items:
            raise FilterError(f"source_record_key {source_rec_key} not in inventory")
        parent_item = inventory.items[source_rec_key]

        if cand["title"] != parent_item.raw.get("title", ""):
            raise FilterError(f"Title mismatch in candidate {cid}")
        if cand["url"] != parent_item.url:
            raise FilterError(f"URL mismatch in candidate {cid}")

        # Check curated content slices
        for c_idx, c_item in enumerate(cand["curated_content"]):
            ref_id = c_item["ref_id"]
            if ref_id not in inventory.items:
                raise FilterError(f"ref_id {ref_id} not in inventory in candidate {cid}")
            target_item = inventory.items[ref_id]
            start = c_item["char_start"]
            end = c_item["char_end"]
            expected_text = target_item.body[start:end]
            if c_item["text"] != expected_text:
                raise FilterError(f"Text slice mismatch in candidate {cid} content[{c_idx}]")

    # 2. Count balance check
    thread_count = counts["thread_count"]
    include_count = counts["include_count"]
    exclude_count = counts["exclude_count"]
    review_count = counts["review_count"]
    candidate_count = counts["candidate_count"]

    if len(candidates) != include_count:
        raise FilterError(f"Candidate count {len(candidates)} != include_count {include_count}")
    if candidate_count != include_count:
        raise FilterError(f"candidate_count {candidate_count} != include_count {include_count}")
    if include_count + exclude_count + review_count != thread_count:
        raise FilterError(
            f"Balance error: {include_count} + {exclude_count} + {review_count} != {thread_count}"
        )
    if len(report_threads) != thread_count:
        raise FilterError(f"Report thread entries {len(report_threads)} != thread_count {thread_count}")

    # 3. Record balance check
    reported_record_keys = set()
    for th in report_threads:
        reported_record_keys.add(th["record_key"])
        for cd in th["comment_decisions"]:
            ck = cd["record_key"]
            if ck in reported_record_keys:
                raise FilterError(f"Duplicate comment record key in report: {ck}")
            reported_record_keys.add(ck)

    inv_record_keys = set(inventory.items.keys())
    if reported_record_keys != inv_record_keys:
        missing = inv_record_keys - reported_record_keys
        extra = reported_record_keys - inv_record_keys
        raise FilterError(f"Record key set mismatch: missing {len(missing)}, extra {len(extra)}")

    # 4. Duplicate relations check: targets must exist as included candidates
    for cand in candidates:
        for rel in cand["metadata"].get("relations", []):
            if rel.get("relation") == "duplicate_of":
                t_key = rel.get("target_record_key")
                # Find candidate for t_key
                target_cand = [c for c in candidates if c["source_record_key"] == t_key]
                if not target_cand:
                    raise FilterError(f"Duplicate target {t_key} not in included candidates")


def filter_corpus(
    input_dir: Path,
    curation_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """전체 정제 파이프라인을 실행하고 후보 문서와 보고서 문서를 반환한다."""
    inventory = load_sources(input_dir)

    # Read curation decisions file
    if not curation_path.is_file():
        raise FilterError(f"Curation decisions file not found: {curation_path}")

    curation_bytes = curation_path.read_bytes()
    curation_sha256 = compute_file_sha256(curation_bytes)

    try:
        curation_doc = json.loads(curation_bytes.decode("utf-8"))
    except Exception as e:
        raise FilterError(f"Failed to parse curation decisions file: {e}") from e

    if curation_doc.get("schema_version") != SCHEMA_VERSION:
        raise FilterError(f"Curation schema_version must be {SCHEMA_VERSION}")
    if curation_doc.get("rules_version") != RULES_VERSION:
        raise FilterError(f"Curation rules_version must be {RULES_VERSION}")
    if curation_doc.get("repository") != DEFAULT_REPOSITORY:
        raise FilterError(f"Curation repository must be {DEFAULT_REPOSITORY}")

    curation_threads = curation_doc.get("threads")
    if not isinstance(curation_threads, dict):
        raise FilterError("curation threads must be an object")

    # Check for invalid thread keys in curation
    all_parent_keys = {t.record_key for t in inventory.threads}
    for k in curation_threads:
        if k not in all_parent_keys:
            raise FilterError(f"Unknown thread key in curation file: {k}")

    # Process all threads
    candidates: list[dict[str, Any]] = []
    report_threads: list[dict[str, Any]] = []

    include_count = 0
    exclude_count = 0
    review_count = 0
    stale_count = 0
    selected_comments_count = 0
    unselected_comments_count = 0

    for thread in inventory.threads:
        inspection = inspect_thread(thread)
        raw_dec = curation_threads.get(thread.record_key)
        decision = apply_curation(thread, inspection, raw_dec, inventory.items)

        cand_id: str | None = None
        if decision.disposition == "include":
            cand = build_candidate(thread, decision, inventory.items)
            candidates.append(cand)
            cand_id = cand["candidate_id"]
            include_count += 1
        elif decision.disposition == "exclude":
            exclude_count += 1
        else:
            review_count += 1
            if "STALE_CURATION" in decision.reason_codes:
                stale_count += 1

        # Track comments
        selected_keys_in_thread = set()
        if decision.disposition == "include":
            for c_item in decision.curated_content:
                if c_item["record_key"] != thread.parent.record_key:
                    selected_keys_in_thread.add(c_item["record_key"])

        comment_decisions = []
        for c in thread.comments:
            if "OUT_OF_SCOPE_PR" in decision.reason_codes:
                c_dec = "ignored"
                c_reasons = ["OUT_OF_SCOPE_PR"]
                unselected_comments_count += 1
            elif c.record_key in selected_keys_in_thread:
                c_dec = "selected"
                c_reasons = decision.reason_codes
                selected_comments_count += 1
            elif inspection.comment_ack_status.get(c.record_key, False):
                c_dec = "ignored"
                c_reasons = ["COMMENT_ACK_ONLY"]
                unselected_comments_count += 1
            elif decision.disposition in ("include", "exclude"):
                c_dec = "ignored"
                c_reasons = ["NOT_SELECTED_BY_CURATION"]
                unselected_comments_count += 1
            else:
                c_dec = "review"
                c_reasons = decision.reason_codes
                unselected_comments_count += 1

            comment_decisions.append(
                {
                    "decision": c_dec,
                    "reason_codes": c_reasons,
                    "record_key": c.record_key,
                    "snapshot_path": c.storage_path,
                    "url": c.url,
                }
            )

        report_threads.append(
            {
                "candidate_id": cand_id,
                "comment_decisions": comment_decisions,
                "decision": decision.disposition,
                "reason_codes": decision.reason_codes,
                "record_key": thread.record_key,
                "snapshot_path": thread.parent.storage_path,
                "source_url": thread.parent.url,
                "suggested_signals": inspection.suggested_signals,
                "thread_sha256": thread.thread_sha256,
            }
        )

    # Sort candidates deterministically: (source_type, source_number)
    candidates.sort(key=lambda c: (c["source_type"], c["source_number"]))
    # report_threads are already sorted since inventory.threads is sorted

    input_manifest = {
        "curation_sha256": curation_sha256,
        "last_synced_at": inventory.state.get("last_synced_at"),
        "snapshot_count": len(inventory.items),
        "snapshot_manifest_sha256": inventory.snapshot_manifest_sha256,
        "sync_state_sha256": inventory.state_sha256,
        "thread_count": len(inventory.threads),
    }

    candidates_doc = {
        "candidates": candidates,
        "input_manifest": input_manifest,
        "repository": DEFAULT_REPOSITORY,
        "rules_version": RULES_VERSION,
        "schema_version": SCHEMA_VERSION,
    }

    by_kind: dict[str, int] = {}
    for item in inventory.items.values():
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1

    counts = {
        "by_kind": by_kind,
        "candidate_count": len(candidates),
        "exclude_count": exclude_count,
        "include_count": include_count,
        "review_count": review_count,
        "selected_comments_count": selected_comments_count,
        "stale_count": stale_count,
        "thread_count": len(inventory.threads),
        "threads_without_accepted_answer_signal": len(inventory.threads),
        "unselected_comments_count": unselected_comments_count,
    }

    report_doc = {
        "counts": counts,
        "input_manifest": input_manifest,
        "repository": DEFAULT_REPOSITORY,
        "rules_version": RULES_VERSION,
        "schema_version": SCHEMA_VERSION,
        "threads": report_threads,
    }

    # Validate output integrity
    validate_outputs(inventory, candidates_doc, report_doc)

    return candidates_doc, report_doc
