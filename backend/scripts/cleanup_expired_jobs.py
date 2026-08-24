#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.job_store import JobStore
from app.run_state_cleanup import backfill_missing_finished_at, reconcile_stale_run_manifests


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean expired API jobs and reconcile stale complete-analysis manifests.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stale run manifests without mutating them.",
    )
    parser.add_argument(
        "--run-manifest-stale-minutes",
        type=int,
        default=30,
        help="Minimum age in minutes before a running complete-analysis manifest is considered stale.",
    )
    args = parser.parse_args()

    settings = load_settings()
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours)
    removed = [] if args.dry_run else store.cleanup_expired()
    repo_root = Path(__file__).resolve().parents[2]
    reconciled = reconcile_stale_run_manifests(
        repo_root / "outputs" / "complete-analysis-runs",
        stale_after_minutes=args.run_manifest_stale_minutes,
        dry_run=args.dry_run,
    )
    backfilled = backfill_missing_finished_at(
        repo_root / "outputs" / "complete-analysis-runs",
        dry_run=args.dry_run,
    )

    print(f"Removed {len(removed)} expired job director{'y' if len(removed)==1 else 'ies'}")
    for job_id in removed:
        print(f" - {job_id}")
    print(
        f"Reconciled {len(reconciled)} stale complete-analysis manifest"
        f"{'s' if len(reconciled) != 1 else ''}"
        f"{' (dry-run)' if args.dry_run else ''}"
    )
    for item in reconciled:
        print(
            " - {run_id} -> {new_status} (completed_territories={completed_territories}, last_seen_at={last_seen_at})".format(
                **item,
            )
        )
    print(
        f"Backfilled finished_at on {len(backfilled)} terminal manifest"
        f"{'s' if len(backfilled) != 1 else ''}"
        f"{' (dry-run)' if args.dry_run else ''}"
    )
    for item in backfilled:
        print(
            " - {run_id} [{status}] finished_at={finished_at}".format(
                **item,
            )
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
