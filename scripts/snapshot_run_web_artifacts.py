#!/usr/bin/env python3
"""Snapshot validated web artefacts into a run archive.

Usage:
    python3 snapshot_run_web_artifacts.py --run-id latest
    python3 snapshot_run_web_artifacts.py --run-id latest-published
    python3 snapshot_run_web_artifacts.py --run-id 20260416_065806 --territories guadeloupe
"""

from __future__ import annotations

import argparse
import sys

from run_web_artifacts import snapshot_run_web_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive validated web artefacts under outputs/complete-analysis-runs/<run_id>/territories/.../web"
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help=(
            "Run identifier under outputs/complete-analysis-runs "
            "(or use 'latest' for the newest complete-analysis run, or 'latest-published' for the newest archived publication-safe run)."
        ),
    )
    parser.add_argument(
        "--territories",
        nargs="+",
        choices=["guadeloupe", "martinique"],
        default=None,
        help="Optional subset of territories to snapshot from the current web workspace.",
    )
    args = parser.parse_args()

    resolved_run_id, archived, validation = snapshot_run_web_artifacts(args.run_id, args.territories)
    print(f"[ok] archived web artefacts for run {resolved_run_id}")
    for territory in sorted(archived.keys()):
        territory_archived = archived[territory]
        territory_validation = validation.get(territory) or {}
        print(
            f"  - {territory}: {len(territory_archived)} files, "
            f"case_study_run_id={territory_validation.get('case_study_run_id')}, "
            f"complete_updated_at={territory_validation.get('complete_analysis_updated_at')}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)