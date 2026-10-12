#!/usr/bin/env python3
"""GitHub 이슈/디스커션 변경분 갱신 및 Chroma 저장소 반영 CLI.

사용법:
  # 1. 실행 계획 준비 (prepare)
  python scripts/update_issue_index.py prepare \
      --source-root . \
      --input-dir data/issues \
      --curation data/issues/curation-decisions.json \
      --reference docs/T08_2_t9_handoff_reference.json \
      --persist-dir data/vector-store/t09 \
      --output-dir data/issues

  # 2. 실행 계획 반영 (apply)
  python scripts/update_issue_index.py apply \
      --plan data/issues/index-updates/<generation_id>/update-plan.json \
      --persist-dir data/vector-store/t09 \
      --reference docs/T08_2_t9_handoff_reference.json
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# src 경로 우선 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artagent.issue_update import apply_plan, prepare_generation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub Issues·Discussions 변경분 갱신 및 Chroma 반영 CLI"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # prepare 서브커맨드
    p_prep = subparsers.add_parser("prepare", help="입력 동결 및 세대별 실행 계획 생성")
    p_prep.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="원문 파일 경로 해석 기준 루트 디렉터리 (기본값: 저장소 루트)",
    )
    p_prep.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "data" / "issues",
        help="수집 원문 및 sync-state 디렉터리 (기본값: data/issues)",
    )
    p_prep.add_argument(
        "--curation",
        type=Path,
        default=ROOT / "data" / "issues" / "curation-decisions.json",
        help="검토 결정 파일 경로 (기본값: data/issues/curation-decisions.json)",
    )
    p_prep.add_argument(
        "--reference",
        type=Path,
        default=ROOT / "docs" / "T08_2_t9_handoff_reference.json",
        help="인계 reference JSON 경로 (기본값: docs/T08_2_t9_handoff_reference.json)",
    )
    p_prep.add_argument(
        "--persist-dir",
        type=Path,
        default=ROOT / "data" / "vector-store" / "t09",
        help="Chroma 영속 저장소 경로 (기본값: data/vector-store/t09)",
    )
    p_prep.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "issues",
        help="index-updates 및 vector-state 출력 디렉터리 (기본값: data/issues)",
    )

    # apply 서브커맨드
    p_apply = subparsers.add_parser("apply", help="동결 계획을 Chroma 저장소에 적용")
    p_apply.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="적용할 update-plan.json 파일 경로",
    )
    p_apply.add_argument(
        "--persist-dir",
        type=Path,
        default=ROOT / "data" / "vector-store" / "t09",
        help="Chroma 영속 저장소 경로 (기본값: data/vector-store/t09)",
    )
    p_apply.add_argument(
        "--reference",
        type=Path,
        default=ROOT / "docs" / "T08_2_t9_handoff_reference.json",
        help="인계 reference JSON 경로 (기본값: docs/T08_2_t9_handoff_reference.json)",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "prepare":
            res = prepare_generation(
                source_root=args.source_root,
                input_dir=args.input_dir,
                curation_path=args.curation,
                reference_path=args.reference,
                persist_dir=args.persist_dir,
                output_dir=args.output_dir,
            )
            print("==================================================")
            print("[PREPARE SUCCESS]")
            print(f"Generation ID: {res['generation_id']}")
            print(f"Plan Path    : {res['plan_path']}")
            print(f"Created      : {res['created']}")
            print(f"Updated      : {res['updated']}")
            print(f"Excluded     : {res['excluded']}")
            print(f"Unchanged    : {res['unchanged']}")
            print(f"Unapplied    : {res['unapplied']}")
            print("==================================================")
            return 0

        elif args.action == "apply":
            res = apply_plan(
                plan_path=args.plan,
                persist_dir=args.persist_dir,
                reference_path=args.reference,
            )
            status_tag = "SUCCESS" if res["status"] == "success" else "PARTIAL"
            print("==================================================")
            print(f"[APPLY {status_tag}]")
            print(f"Generation ID: {res['generation_id']}")
            print(f"Plan Path    : {res['plan_path']}")
            print(f"Status       : {res['status']}")
            print(f"Created      : {res['created']}")
            print(f"Updated      : {res['updated']}")
            print(f"Excluded     : {res['excluded']}")
            print(f"Unchanged    : {res['unchanged']}")
            print(f"Unapplied    : {res['unapplied']}")
            print(f"Total Active : {res['total_active']}")
            print("==================================================")
            return 0 if res["status"] == "success" else 1

        else:
            print(f"알 수 없는 액션: {args.action}", file=sys.stderr)
            return 2

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
