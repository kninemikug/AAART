"""ART GitHub 원문 스냅샷 증분 수집기의 동작 테스트."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from artagent.issues import IncrementalCollector


ISSUE_URL = "https://github.com/artraweditor/ART/issues/1"
ISSUE_COMMENT_URL = f"{ISSUE_URL}#issuecomment-900"
DISCUSSION_URL = "https://github.com/artraweditor/ART/discussions/1"
DISCUSSION_COMMENT_URL = f"{DISCUSSION_URL}#discussioncomment-1001"


def issue(body: str, updated_at: str) -> dict:
    return {
        "id": 1,
        "number": 1,
        "html_url": ISSUE_URL,
        "title": "JPEG export problem",
        "body": body,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": updated_at,
    }


def pull_request() -> dict:
    return {
        "id": 2,
        "number": 2,
        "html_url": "https://github.com/artraweditor/ART/pull/2",
        "title": "Not an issue",
        "body": "",
        "updated_at": "2026-09-01T00:00:00Z",
        "pull_request": {"url": "https://api.github.com/repos/artraweditor/ART/pulls/2"},
    }


def issue_comment(comment_id: int, body: str, updated_at: str) -> dict:
    return {
        "id": comment_id,
        "html_url": f"{ISSUE_URL}#issuecomment-{comment_id}",
        "issue_url": "https://api.github.com/repos/artraweditor/ART/issues/1",
        "body": body,
        "created_at": "2026-09-01T00:02:00Z",
        "updated_at": updated_at,
    }


def discussion(body: str, updated_at: str) -> dict:
    return {
        "id": "D_kwDOART1",
        "databaseId": 10,
        "number": 1,
        "url": DISCUSSION_URL,
        "title": "Workflow question",
        "body": body,
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": updated_at,
    }


def discussion_comment(body: str, updated_at: str) -> dict:
    return {
        "id": "DC_kwDOART1",
        "databaseId": 1001,
        "url": DISCUSSION_COMMENT_URL,
        "body": body,
        "createdAt": "2026-09-01T00:03:00Z",
        "updatedAt": updated_at,
    }


class FixedGitHubResponses:
    """네트워크 없이 GitHub API 응답 범위를 재현하는 고정 응답 클라이언트."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.since_arguments: list[str | None] = []

    def list_issues(self, since: str | None):
        self.since_arguments.append(since)
        if self.phase == "initial":
            return [issue("original issue text", "2026-09-01T00:01:00Z"), pull_request()]
        return [issue("edited issue text", "2026-09-01T10:05:00Z")]

    def list_issue_comments(self, since: str | None):
        self.since_arguments.append(since)
        if self.phase == "initial":
            return [issue_comment(900, "original issue comment", "2026-09-01T00:02:00Z")]
        return [issue_comment(901, "new issue comment", "2026-09-01T10:06:00Z")]

    def list_discussions(self, since: str | None):
        self.since_arguments.append(since)
        if self.phase == "initial":
            return [discussion("original discussion text", "2026-09-01T00:03:00Z")]
        return [discussion("edited discussion text", "2026-09-01T10:07:00Z")]

    def list_discussion_comments(self, number: int):
        self.assert_discussion_number(number)
        if self.phase == "initial":
            return [discussion_comment("original discussion comment", "2026-09-01T00:04:00Z")]
        return [discussion_comment("edited discussion comment", "2026-09-01T10:08:00Z")]

    @staticmethod
    def assert_discussion_number(number: int) -> None:
        if number != 1:
            raise AssertionError(f"unexpected discussion number: {number}")


class IncrementalCollectorTests(unittest.TestCase):
    def test_initial_sync_saves_public_items_comments_and_traceable_state(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "issues"
            result = IncrementalCollector(output_dir).sync(
                FixedGitHubResponses("initial"), now="2026-09-01T10:00:00Z"
            )

            state = json.loads((output_dir / "sync-state.json").read_text(encoding="utf-8"))
            snapshot_paths = sorted(
                path.relative_to(output_dir).as_posix()
                for path in (output_dir / "snapshots").rglob("*.json")
            )

        self.assertEqual(result.snapshots_written, 4)
        self.assertEqual(state["last_synced_at"], "2026-09-01T10:00:00Z")
        self.assertEqual(
            snapshot_paths,
            [
                "snapshots/discussion-comments/1001.json",
                "snapshots/discussions/1.json",
                "snapshots/issue-comments/900.json",
                "snapshots/issues/1.json",
            ],
        )
        self.assertNotIn("issue:2", state["records"])
        self.assertEqual(state["records"]["issue:1"]["source_url"], ISSUE_URL)
        self.assertEqual(
            state["records"]["discussion-comment:DC_kwDOART1"]["storage_path"],
            "snapshots/discussion-comments/1001.json",
        )

    def test_follow_up_sync_writes_only_new_or_changed_objects(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "issues"
            IncrementalCollector(output_dir).sync(
                FixedGitHubResponses("initial"), now="2026-09-01T10:00:00Z"
            )
            follow_up_client = FixedGitHubResponses("follow-up")
            result = IncrementalCollector(output_dir).sync(
                follow_up_client, now="2026-09-01T10:10:00Z"
            )

            issue_snapshot = json.loads(
                (output_dir / "snapshots/issues/1.json").read_text(encoding="utf-8")
            )
            comment_paths = sorted(
                path.name for path in (output_dir / "snapshots/issue-comments").glob("*.json")
            )
            state = json.loads((output_dir / "sync-state.json").read_text(encoding="utf-8"))

        self.assertEqual(result.snapshots_written, 4)
        self.assertEqual(issue_snapshot["body"], "edited issue text")
        self.assertEqual(comment_paths, ["900.json", "901.json"])
        self.assertEqual(state["last_synced_at"], "2026-09-01T10:10:00Z")
        self.assertTrue(all(argument is not None for argument in follow_up_client.since_arguments[:3]))

    def test_rerunning_the_same_range_does_not_duplicate_or_rewrite_snapshots(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "issues"
            IncrementalCollector(output_dir).sync(
                FixedGitHubResponses("initial"), now="2026-09-01T10:00:00Z"
            )
            IncrementalCollector(output_dir).sync(
                FixedGitHubResponses("follow-up"), now="2026-09-01T10:10:00Z"
            )
            before = {
                path.relative_to(output_dir).as_posix(): path.read_bytes()
                for path in (output_dir / "snapshots").rglob("*.json")
            }

            result = IncrementalCollector(output_dir).sync(
                FixedGitHubResponses("follow-up"), now="2026-09-01T10:10:00Z"
            )
            after = {
                path.relative_to(output_dir).as_posix(): path.read_bytes()
                for path in (output_dir / "snapshots").rglob("*.json")
            }

        self.assertEqual(result.snapshots_written, 0)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
