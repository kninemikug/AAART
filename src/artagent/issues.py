"""ART GitHub Issues·Discussions 원문 스냅샷의 증분 수집을 지원한다.

Issues와 Issue 댓글은 GitHub REST API를 사용한다. Discussions와 그 댓글은
GitHub GraphQL API 전용이므로 ``GITHUB_TOKEN``이 필요하다. 저장 파일에는 API가
반환한 객체만 보존하고, 추후 단계의 후보 선별·청킹·벡터 변환은 수행하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "artraweditor/ART"
GITHUB_API = "https://api.github.com"
GITHUB_REST_API_VERSION = "2026-03-10"
USER_AGENT = "ART-issues-corpus/1.0 (+https://github.com/artraweditor/ART)"
STATE_FILENAME = "sync-state.json"
NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


DISCUSSIONS_QUERY = """
query ListDiscussions($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 100, after: $after,
      orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        databaseId
        number
        url
        title
        body
        createdAt
        updatedAt
        author { login }
        category { name }
      }
    }
  }
}
"""

DISCUSSION_COMMENTS_QUERY = """
query ListDiscussionComments(
  $owner: String!, $name: String!, $number: Int!, $after: String
) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      comments(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          databaseId
          url
          body
          createdAt
          updatedAt
          author { login }
        }
      }
    }
  }
}
"""

DISCUSSION_REPLIES_QUERY = """
query ListDiscussionReplies($id: ID!, $after: String) {
  node(id: $id) {
    ... on DiscussionComment {
      replies(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          databaseId
          url
          body
          createdAt
          updatedAt
          author { login }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class SnapshotObject:
    """저장할 GitHub 원문 객체와 추적 메타데이터."""

    key: str
    kind: str
    object_id: str
    source_url: str
    storage_path: Path
    updated_at: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    """한 번의 동기화 결과 요약."""

    snapshots_written: int
    snapshots_unchanged: int
    last_synced_at: str


def utc_now() -> str:
    """초 단위 UTC ISO-8601 시각을 반환한다."""
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def overlap_since(last_synced_at: str | None) -> str | None:
    """초 경계에서의 누락을 피하기 위해 이전 동기화와 1초 겹친 범위를 만든다."""
    if last_synced_at is None:
        return None
    parsed = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
    return (parsed - timedelta(seconds=1)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def timestamp_is_after_or_equal(value: str | None, cutoff: str | None) -> bool:
    """GitHub UTC 시각이 cutoff와 같거나 뒤인지 확인한다."""
    return cutoff is None or (value is not None and value >= cutoff)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _snapshot_filename(object_id: object) -> str:
    filename = SAFE_FILENAME_RE.sub("_", str(object_id)).strip("._")
    if not filename:
        raise ValueError("GitHub 객체 ID로 안전한 파일명을 만들 수 없습니다.")
    return filename


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"GitHub 응답에 필수 문자열 필드가 없습니다: {field}")
    return value


def _required_integer(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int):
        raise ValueError(f"GitHub 응답에 필수 정수 필드가 없습니다: {field}")
    return value


def _issue_number_from_comment(raw: dict[str, Any]) -> int | None:
    issue_url = raw.get("issue_url")
    if not isinstance(issue_url, str):
        return None
    path_segments = [segment for segment in urlparse(issue_url).path.split("/") if segment]
    if not path_segments:
        return None
    try:
        return int(path_segments[-1])
    except ValueError:
        return None


class GitHubApiClient:
    """GitHub의 공개 Issues와 토큰 기반 Discussions를 읽는 최소 클라이언트."""

    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        token: str | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        owner, separator, name = repository.partition("/")
        if not separator or not owner or not name:
            raise ValueError("repository는 'owner/name' 형식이어야 합니다.")
        self.repository = repository
        self.owner = owner
        self.name = name
        self.token = token
        self.opener = opener

    def list_issues(self, since: str | None) -> list[dict[str, Any]]:
        """수정 시각 순으로 공개 Issue를 페이지 끝까지 가져온다."""
        parameters = {
            "state": "all",
            "sort": "updated",
            "direction": "asc",
            "per_page": "100",
        }
        if since is not None:
            parameters["since"] = since
        url = f"{GITHUB_API}/repos/{self.repository}/issues?{urlencode(parameters)}"
        return self._get_rest_pages(url)

    def list_issue_comments(self, since: str | None) -> list[dict[str, Any]]:
        """수정된 repository-wide Issue 댓글을 페이지 끝까지 가져온다."""
        parameters = {"sort": "updated", "direction": "asc", "per_page": "100"}
        if since is not None:
            parameters["since"] = since
        url = (
            f"{GITHUB_API}/repos/{self.repository}/issues/comments?"
            f"{urlencode(parameters)}"
        )
        return self._get_rest_pages(url)

    def list_discussions(self, since: str | None) -> list[dict[str, Any]]:
        """수정 시각 내림차순 GraphQL 페이지를 경계까지 읽는다."""
        discussions: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            payload = self._post_graphql(
                DISCUSSIONS_QUERY,
                {"owner": self.owner, "name": self.name, "after": after},
            )
            connection = self._graphql_path(payload, "repository", "discussions")
            nodes = self._graphql_nodes(connection)
            discussions.extend(
                node
                for node in nodes
                if timestamp_is_after_or_equal(node.get("updatedAt"), since)
            )
            if (
                since is not None
                and any(
                    not timestamp_is_after_or_equal(node.get("updatedAt"), since)
                    for node in nodes
                )
            ):
                return discussions
            page_info = self._graphql_page_info(connection)
            if not page_info["hasNextPage"]:
                return discussions
            after = page_info["endCursor"]

    def list_discussion_comments(self, number: int) -> list[dict[str, Any]]:
        """Discussion의 최상위 댓글과 재귀적인 답글을 모두 반환한다."""
        comments: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            payload = self._post_graphql(
                DISCUSSION_COMMENTS_QUERY,
                {
                    "owner": self.owner,
                    "name": self.name,
                    "number": number,
                    "after": after,
                },
            )
            discussion = self._graphql_path(payload, "repository", "discussion")
            if discussion is None:
                return comments
            connection = self._graphql_path(discussion, "comments")
            nodes = self._graphql_nodes(connection)
            for comment in nodes:
                comments.append(comment)
                comments.extend(self._list_discussion_replies(_required_string(comment, "id")))
            page_info = self._graphql_page_info(connection)
            if not page_info["hasNextPage"]:
                return comments
            after = page_info["endCursor"]

    def _list_discussion_replies(self, comment_id: str) -> list[dict[str, Any]]:
        replies: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            payload = self._post_graphql(
                DISCUSSION_REPLIES_QUERY, {"id": comment_id, "after": after}
            )
            node = self._graphql_path(payload, "node")
            if node is None:
                return replies
            connection = self._graphql_path(node, "replies")
            nodes = self._graphql_nodes(connection)
            for reply in nodes:
                replies.append(reply)
                replies.extend(self._list_discussion_replies(_required_string(reply, "id")))
            page_info = self._graphql_page_info(connection)
            if not page_info["hasNextPage"]:
                return replies
            after = page_info["endCursor"]

    def _get_rest_pages(self, url: str) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url is not None:
            payload, link_header = self._request_json(next_url)
            if not isinstance(payload, list) or not all(
                isinstance(item, dict) for item in payload
            ):
                raise ValueError("GitHub REST 목록 응답이 객체 배열이 아닙니다.")
            objects.extend(payload)
            next_url = self._next_link(link_header)
        return objects

    def _request_json(self, url: str, data: bytes | None = None) -> tuple[Any, str | None]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with self.opener(request, timeout=30) as response:
                body = response.read()
                return json.loads(body.decode("utf-8")), response.headers.get("Link")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"GitHub API 연결 실패: {error.reason}") from error

    def _post_graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError(
                "GitHub Discussions 수집에는 GITHUB_TOKEN 환경변수가 필요합니다."
            )
        payload, _ = self._request_json(
            f"{GITHUB_API}/graphql",
            _json_bytes({"query": query, "variables": variables}),
        )
        if not isinstance(payload, dict):
            raise ValueError("GitHub GraphQL 응답이 객체가 아닙니다.")
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"GitHub GraphQL 오류: {errors}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("GitHub GraphQL 응답에 data 객체가 없습니다.")
        return data

    @staticmethod
    def _next_link(link_header: str | None) -> str | None:
        if not link_header:
            return None
        match = NEXT_LINK_RE.search(link_header)
        return match.group(1) if match else None

    @staticmethod
    def _graphql_path(value: object, *keys: str) -> Any:
        current = value
        for key in keys:
            if not isinstance(current, dict):
                raise ValueError(f"GitHub GraphQL 응답 경로가 객체가 아닙니다: {key}")
            current = current.get(key)
        return current

    @staticmethod
    def _graphql_nodes(connection: object) -> list[dict[str, Any]]:
        if not isinstance(connection, dict):
            raise ValueError("GitHub GraphQL connection이 없습니다.")
        nodes = connection.get("nodes")
        if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
            raise ValueError("GitHub GraphQL connection nodes가 객체 배열이 아닙니다.")
        return nodes

    @staticmethod
    def _graphql_page_info(connection: object) -> dict[str, Any]:
        if not isinstance(connection, dict):
            raise ValueError("GitHub GraphQL connection이 없습니다.")
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict) or not isinstance(
            page_info.get("hasNextPage"), bool
        ):
            raise ValueError("GitHub GraphQL pageInfo가 올바르지 않습니다.")
        return page_info


class IncrementalCollector:
    """단일 ``data/issues`` 디렉터리에 중복 없는 원문 스냅샷을 유지한다."""

    def __init__(
        self, output_dir: Path, repository: str = DEFAULT_REPOSITORY
    ) -> None:
        self.output_dir = output_dir
        self.repository = repository

    def sync(self, client: Any, now: str | None = None) -> SyncResult:
        """지난 완료 시각 이후 변경분을 원문 파일과 상태 파일에 반영한다."""
        state = self._load_state()
        previous_sync = state["last_synced_at"]
        since = overlap_since(previous_sync)
        sync_started_at = now or utc_now()

        objects = self._collect_objects(client, state["records"], since, previous_sync)
        writes = 0
        unchanged = 0
        for snapshot in objects:
            destination = self.output_dir / snapshot.storage_path
            if self._write_if_changed(destination, _json_bytes(snapshot.raw)):
                writes += 1
            else:
                unchanged += 1
            state["records"][snapshot.key] = {
                "kind": snapshot.kind,
                "object_id": snapshot.object_id,
                "source_url": snapshot.source_url,
                "storage_path": snapshot.storage_path.as_posix(),
                "updated_at": snapshot.updated_at,
            }

        # 수집 중 새로 수정된 항목은 다음 실행에서 다시 포함되어야 한다. 따라서
        # 종료 시각이 아니라 수집 시작 시각을 다음 증분 조회의 경계로 기록한다.
        state["last_synced_at"] = sync_started_at
        state["repository"] = self.repository
        state["version"] = 1
        self._write_if_changed(self.output_dir / STATE_FILENAME, _json_bytes(state))
        return SyncResult(writes, unchanged, sync_started_at)

    def _collect_objects(
        self,
        client: Any,
        records: dict[str, Any],
        since: str | None,
        previous_sync: str | None,
    ) -> list[SnapshotObject]:
        issues = [
            raw
            for raw in client.list_issues(since)
            if isinstance(raw, dict) and "pull_request" not in raw
        ]
        known_issue_numbers = {
            int(record["object_id"])
            for key, record in records.items()
            if key.startswith("issue:")
            and isinstance(record, dict)
            and str(record.get("object_id", "")).isdigit()
        }
        known_issue_numbers.update(_required_integer(raw, "number") for raw in issues)

        objects = [self._issue_snapshot(raw) for raw in issues]
        for raw in client.list_issue_comments(since):
            if not isinstance(raw, dict):
                raise ValueError("GitHub Issue 댓글 응답이 객체가 아닙니다.")
            if _issue_number_from_comment(raw) in known_issue_numbers:
                objects.append(self._issue_comment_snapshot(raw))

        discussions = client.list_discussions(since)
        if not all(isinstance(raw, dict) for raw in discussions):
            raise ValueError("GitHub Discussion 응답이 객체 배열이 아닙니다.")
        for raw in discussions:
            objects.append(self._discussion_snapshot(raw))
            number = _required_integer(raw, "number")
            for comment in client.list_discussion_comments(number):
                if not isinstance(comment, dict):
                    raise ValueError("GitHub Discussion 댓글 응답이 객체가 아닙니다.")
                if timestamp_is_after_or_equal(comment.get("updatedAt"), previous_sync):
                    objects.append(self._discussion_comment_snapshot(comment))
        return objects

    @staticmethod
    def _issue_snapshot(raw: dict[str, Any]) -> SnapshotObject:
        number = _required_integer(raw, "number")
        return SnapshotObject(
            key=f"issue:{number}",
            kind="issue",
            object_id=str(number),
            source_url=_required_string(raw, "html_url"),
            storage_path=Path("snapshots/issues") / f"{number}.json",
            updated_at=raw.get("updated_at"),
            raw=raw,
        )

    @staticmethod
    def _issue_comment_snapshot(raw: dict[str, Any]) -> SnapshotObject:
        comment_id = _required_integer(raw, "id")
        return SnapshotObject(
            key=f"issue-comment:{comment_id}",
            kind="issue-comment",
            object_id=str(comment_id),
            source_url=_required_string(raw, "html_url"),
            storage_path=Path("snapshots/issue-comments") / f"{comment_id}.json",
            updated_at=raw.get("updated_at"),
            raw=raw,
        )

    @staticmethod
    def _discussion_snapshot(raw: dict[str, Any]) -> SnapshotObject:
        number = _required_integer(raw, "number")
        object_id = _required_string(raw, "id")
        return SnapshotObject(
            key=f"discussion:{object_id}",
            kind="discussion",
            object_id=object_id,
            source_url=_required_string(raw, "url"),
            storage_path=Path("snapshots/discussions") / f"{number}.json",
            updated_at=raw.get("updatedAt"),
            raw=raw,
        )

    @staticmethod
    def _discussion_comment_snapshot(raw: dict[str, Any]) -> SnapshotObject:
        object_id = _required_string(raw, "id")
        database_id = raw.get("databaseId")
        filename = _snapshot_filename(database_id if database_id is not None else object_id)
        return SnapshotObject(
            key=f"discussion-comment:{object_id}",
            kind="discussion-comment",
            object_id=object_id,
            source_url=_required_string(raw, "url"),
            storage_path=Path("snapshots/discussion-comments") / f"{filename}.json",
            updated_at=raw.get("updatedAt"),
            raw=raw,
        )

    def _load_state(self) -> dict[str, Any]:
        state_path = self.output_dir / STATE_FILENAME
        if not state_path.exists():
            return {"version": 1, "repository": self.repository, "last_synced_at": None, "records": {}}
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"동기화 상태 파일 JSON이 올바르지 않습니다: {state_path}") from error
        if not isinstance(state, dict) or not isinstance(state.get("records"), dict):
            raise ValueError(f"동기화 상태 파일 형식이 올바르지 않습니다: {state_path}")
        if state.get("repository") != self.repository:
            raise ValueError("동기화 상태 파일의 repository가 현재 수집 대상과 다릅니다.")
        if state.get("last_synced_at") is not None and not isinstance(
            state["last_synced_at"], str
        ):
            raise ValueError("동기화 상태 파일의 last_synced_at 형식이 올바르지 않습니다.")
        return state

    @staticmethod
    def _write_if_changed(destination: Path, content: bytes) -> bool:
        if destination.is_file() and destination.read_bytes() == content:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        return True
