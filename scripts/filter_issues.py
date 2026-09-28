"""ART GitHub Issues·Discussions 정제 및 검색 후보 목록 생성 CLI."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artagent.issue_filter import FilterError, filter_corpus


def parse_arguments() -> argparse.Namespace:
    """명시적인 입력·결정·출력 경로 및 검사 플래그를 읽는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "data" / "issues",
        help="sync-state.json과 snapshots가 위치한 디렉터리 (기본값: data/issues)",
    )
    parser.add_argument(
        "--curation",
        type=Path,
        default=ROOT / "data" / "issues" / "curation-decisions.json",
        help="원문 검토 결정 파일 경로 (기본값: data/issues/curation-decisions.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "issues" / "search-candidates.json",
        help="검색 후보 목록 출력 경로 (기본값: data/issues/search-candidates.json)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "issues" / "filter-report.json",
        help="정제 보고서 출력 경로 (기본값: data/issues/filter-report.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="출력 파일을 새로 쓰지 않고 기존 파일과 바이트 일치 여부만 검증",
    )
    return parser.parse_args()


def write_atomic_if_changed(target_path: Path, content_bytes: bytes) -> bool:
    """기존 파일과 내용이 다를 때만 동일 디렉터리 임시 파일을 통해 원자적으로 쓴다."""
    if target_path.is_file():
        existing_bytes = target_path.read_bytes()
        if existing_bytes == content_bytes:
            return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_file_path = tempfile.mkstemp(
        dir=target_path.parent, prefix=f".{target_path.name}.tmp_"
    )
    try:
        with os.fdopen(temp_fd, "wb") as f:
            f.write(content_bytes)
        os.replace(temp_file_path, target_path)
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
    return True


def main() -> int:
    """CLI 진입점: 정제 실행 또는 기존 출력 검증."""
    try:
        args = parse_arguments()
    except SystemExit as e:
        return 2 if e.code != 0 else 0

    input_dir = args.input_dir.resolve()
    curation_path = args.curation.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()

    # Safety checks: do not allow overwriting input files
    forbidden_targets = {
        input_dir / "sync-state.json",
        curation_path,
    }
    if output_path in forbidden_targets or report_path in forbidden_targets:
        sys.stderr.write("Error: output or report cannot overwrite input files.\n")
        return 1
    if output_path == report_path:
        sys.stderr.write("Error: output and report must be different paths.\n")
        return 1

    try:
        candidates_doc, report_doc = filter_corpus(input_dir, curation_path)
    except FilterError as e:
        sys.stderr.write(f"Validation Error: {e}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Unexpected Error: {e}\n")
        return 1

    candidates_bytes = (
        json.dumps(candidates_doc, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    report_bytes = (
        json.dumps(report_doc, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    if args.check:
        if not output_path.is_file():
            sys.stderr.write(f"Check failed: output file does not exist: {output_path}\n")
            return 1
        if not report_path.is_file():
            sys.stderr.write(f"Check failed: report file does not exist: {report_path}\n")
            return 1

        if output_path.read_bytes() != candidates_bytes:
            sys.stderr.write(f"Check failed: output content mismatch in {output_path}\n")
            return 1
        if report_path.read_bytes() != report_bytes:
            sys.stderr.write(f"Check failed: report content mismatch in {report_path}\n")
            return 1

        print(
            json.dumps(
                {
                    "status": "check_passed",
                    "output": str(output_path),
                    "report": str(report_path),
                    "counts": report_doc["counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # Write files atomically if changed
    write_atomic_if_changed(output_path, candidates_bytes)
    write_atomic_if_changed(report_path, report_bytes)

    print(
        json.dumps(
            {
                "status": "generated",
                "output": str(output_path),
                "report": str(report_path),
                "counts": report_doc["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
