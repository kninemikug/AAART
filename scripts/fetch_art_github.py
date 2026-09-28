"""ART GitHub Issues·Discussions 원문 스냅샷을 증분 동기화한다."""

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artagent.issues import DEFAULT_REPOSITORY, GitHubApiClient, IncrementalCollector


def parse_arguments() -> argparse.Namespace:
    """명시적인 대상 저장소와 출력 경로 인자를 읽는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "data" / "issues",
        help="원문 스냅샷과 sync-state.json을 저장할 경로",
    )
    parser.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
        help="수집할 공개 GitHub 저장소 (기본값: artraweditor/ART)",
    )
    return parser.parse_args()


def main() -> int:
    """한 번 동기화하고 저장 결과만 출력한다."""
    arguments = parse_arguments()
    client = GitHubApiClient(
        repository=arguments.repository, token=os.environ.get("GITHUB_TOKEN")
    )
    result = IncrementalCollector(arguments.outdir, arguments.repository).sync(client)
    print(
        json.dumps(
            {
                "outdir": str(arguments.outdir),
                "snapshots_written": result.snapshots_written,
                "snapshots_unchanged": result.snapshots_unchanged,
                "last_synced_at": result.last_synced_at,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
