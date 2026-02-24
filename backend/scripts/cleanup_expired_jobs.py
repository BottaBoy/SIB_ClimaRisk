#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.job_store import JobStore


def main() -> int:
    settings = load_settings()
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours)
    removed = store.cleanup_expired()
    print(f"Removed {len(removed)} expired job director{'y' if len(removed)==1 else 'ies'}")
    for job_id in removed:
        print(f" - {job_id}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
