#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_run_graphs as run_graphs

TERMINAL_RUN_STATUSES = {"success", "partial"}
FAILED_RUN_STATUSES = {"failed", "aborted"}


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str], argparse.Namespace]:
    parser = argparse.ArgumentParser(
        description="Wait until a selected run has strict scientific graph inputs, then call generate_run_graphs.py.",
        add_help=False,
    )
    parser.add_argument("--wait-timeout-seconds", type=float, default=21600.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--help", action="store_true")
    wrapper_args, remaining = parser.parse_known_args(argv)

    run_parser = argparse.ArgumentParser(add_help=False)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--latest-success", action="store_true")
    run_parser.add_argument("--territories", nargs="+", default=[])
    run_args, _ = run_parser.parse_known_args(remaining)
    return wrapper_args, remaining, run_args


def _summary_ready(record: run_graphs.RunRecord, territory: str) -> tuple[bool, Path]:
    base_dir = run_graphs._archived_web_data_dir(record, territory)
    summary_path = base_dir / f"{territory}-scientific-web-summary.json"
    return summary_path.is_file(), summary_path


def _resolve_record(run_id: str | None, latest_success: bool) -> run_graphs.RunRecord:
    records = run_graphs.list_run_records()
    return run_graphs.resolve_run_record(run_id, latest_success or not run_id, records)


def _selected_territories(record: run_graphs.RunRecord, requested: list[str]) -> list[str]:
    return run_graphs._resolve_selected_territories(record, requested)


def _wait_until_ready(
    run_id: str | None,
    latest_success: bool,
    requested_territories: list[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> run_graphs.RunRecord:
    started = time.monotonic()
    last_message = ""
    while True:
        record = _resolve_record(run_id, latest_success)
        territories = _selected_territories(record, requested_territories)
        missing: list[str] = []
        for territory in territories:
            ready, summary_path = _summary_ready(record, territory)
            if not ready:
                missing.append(str(summary_path))

        if record.status in TERMINAL_RUN_STATUSES and not missing:
            print(
                f"[ready] run_id={record.run_id} status={record.status} "
                f"territories={','.join(territories)}",
                flush=True,
            )
            return record

        if record.status in FAILED_RUN_STATUSES:
            missing_text = ", ".join(missing) if missing else "none"
            raise SystemExit(
                "Run is terminal but not graph-ready: "
                f"run_id={record.run_id} status={record.status} missing_scientific_summaries={missing_text}"
            )

        elapsed = time.monotonic() - started
        if elapsed >= timeout_seconds:
            missing_text = ", ".join(missing) if missing else "none"
            raise SystemExit(
                "Timed out while waiting for graph-ready scientific artefacts: "
                f"run_id={record.run_id} status={record.status} missing_scientific_summaries={missing_text} "
                f"waited_seconds={int(elapsed)}"
            )

        message = (
            f"[wait] run_id={record.run_id} status={record.status} "
            f"missing_scientific_summaries={len(missing)} next_check_in={poll_seconds:.0f}s"
        )
        if message != last_message:
            print(message, flush=True)
            last_message = message
        time.sleep(poll_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    wrapper_args, passthrough_args, run_args = _parse_args(argv or sys.argv[1:])
    if wrapper_args.help:
        raise SystemExit(
            "Usage: generate_run_graphs_when_ready.py [--wait-timeout-seconds N] [--poll-seconds N] "
            + "then any generate_run_graphs.py arguments"
        )

    _wait_until_ready(
        run_id=run_args.run_id,
        latest_success=bool(run_args.latest_success),
        requested_territories=list(run_args.territories or []),
        timeout_seconds=float(wrapper_args.wait_timeout_seconds),
        poll_seconds=max(float(wrapper_args.poll_seconds), 1.0),
    )

    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "generate_run_graphs.py"), *passthrough_args]
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
