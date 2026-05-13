#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


UTC = timezone.utc
ENV_FRONTEND_SUPERVISION_JOURNAL = "SIB_FRONTEND_SUPERVISION_JOURNAL"
ENV_FRONTEND_SUPERVISION_RUN_ID = "SIB_FRONTEND_SUPERVISION_RUN_ID"
PARENT_TERMINAL_EVENTS = frozenset({"frontend_rebuild_completed", "frontend_rebuild_failed"})
CHILD_TERMINAL_EVENTS = frozenset({"child_completed", "child_failed"})


def frontend_supervision_journal_path(run_dir: Path) -> Path:
    return Path(run_dir) / "frontend-supervision.jsonl"


def frontend_supervision_journal_from_env() -> Path | None:
    raw = str(os.environ.get(ENV_FRONTEND_SUPERVISION_JOURNAL) or "").strip()
    if not raw:
        return None
    return Path(raw)


def frontend_supervision_run_id_from_env() -> str | None:
    raw = str(os.environ.get(ENV_FRONTEND_SUPERVISION_RUN_ID) or "").strip()
    return raw or None


def write_frontend_supervision_event(
    journal_path: Path | None,
    *,
    actor: str,
    event: str,
    **payload: Any,
) -> None:
    if journal_path is None:
        return
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "actor": str(actor),
        "event": str(event),
        **payload,
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_process_start_ticks(pid: int) -> int | None:
    stat_path = Path(f"/proc/{int(pid)}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        after_comm = raw.rsplit(")", 1)[1].strip()
        fields = after_comm.split()
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def is_same_process_alive(pid: int, start_ticks: int | None) -> bool:
    if int(pid) <= 0:
        return False
    current_start_ticks = read_process_start_ticks(pid)
    if current_start_ticks is None:
        return False
    if start_ticks is None:
        return True
    return int(current_start_ticks) == int(start_ticks)


def has_terminal_event(journal_path: Path, actor: str) -> bool:
    terminal_events = PARENT_TERMINAL_EVENTS if actor == "parent" else CHILD_TERMINAL_EVENTS
    if not journal_path.exists():
        return False
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if str(payload.get("actor") or "") != actor:
            continue
        if str(payload.get("event") or "") in terminal_events:
            return True
    return False


def monitor_frontend_processes(
    *,
    journal_path: Path,
    run_id: str | None,
    territories: list[str],
    parent_pid: int,
    parent_start_ticks: int | None,
    child_pid: int,
    child_start_ticks: int | None,
    poll_interval_seconds: float = 1.0,
    max_wait_seconds: float | None = 7200.0,
    process_alive_fn: Callable[[int, int | None], bool] = is_same_process_alive,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    journal_path = Path(journal_path)
    write_frontend_supervision_event(
        journal_path,
        actor="monitor",
        event="monitor_started",
        monitor_pid=os.getpid(),
        run_id=run_id,
        territories=list(territories),
        parent_pid=int(parent_pid),
        parent_start_ticks=parent_start_ticks,
        child_pid=int(child_pid),
        child_start_ticks=child_start_ticks,
        poll_interval_seconds=float(poll_interval_seconds),
    )

    deadline = None if max_wait_seconds is None else (time.monotonic() + float(max_wait_seconds))
    parent_missing_logged = False
    child_missing_logged = False
    parent_terminal_event_seen = False
    child_terminal_event_seen = False

    while True:
        parent_terminal_event_seen = has_terminal_event(journal_path, "parent")
        child_terminal_event_seen = has_terminal_event(journal_path, "child")
        if parent_terminal_event_seen and child_terminal_event_seen:
            break

        parent_alive = bool(process_alive_fn(int(parent_pid), parent_start_ticks))
        child_alive = bool(process_alive_fn(int(child_pid), child_start_ticks))

        if not parent_alive and not parent_missing_logged:
            write_frontend_supervision_event(
                journal_path,
                actor="monitor",
                event="parent_process_missing",
                run_id=run_id,
                parent_pid=int(parent_pid),
                child_pid=int(child_pid),
                parent_terminal_event_seen=parent_terminal_event_seen,
                child_alive=child_alive,
            )
            parent_missing_logged = True

        if not child_alive and not child_missing_logged:
            write_frontend_supervision_event(
                journal_path,
                actor="monitor",
                event="child_process_missing",
                run_id=run_id,
                parent_pid=int(parent_pid),
                child_pid=int(child_pid),
                child_terminal_event_seen=child_terminal_event_seen,
                parent_alive=parent_alive,
            )
            child_missing_logged = True

        if (parent_missing_logged or parent_terminal_event_seen) and (child_missing_logged or child_terminal_event_seen):
            break

        if deadline is not None and time.monotonic() >= deadline:
            write_frontend_supervision_event(
                journal_path,
                actor="monitor",
                event="monitor_timeout",
                run_id=run_id,
                parent_missing_logged=parent_missing_logged,
                child_missing_logged=child_missing_logged,
                parent_terminal_event_seen=parent_terminal_event_seen,
                child_terminal_event_seen=child_terminal_event_seen,
            )
            break

        sleep_fn(max(0.0, float(poll_interval_seconds)))

    summary = {
        "run_id": run_id,
        "parent_missing_logged": parent_missing_logged,
        "child_missing_logged": child_missing_logged,
        "parent_terminal_event_seen": parent_terminal_event_seen,
        "child_terminal_event_seen": child_terminal_event_seen,
    }
    write_frontend_supervision_event(
        journal_path,
        actor="monitor",
        event="monitor_completed",
        **summary,
    )
    return summary


def launch_frontend_supervision_monitor(
    *,
    journal_path: Path,
    run_id: str | None,
    territories: list[str],
    parent_pid: int,
    parent_start_ticks: int | None,
    child_pid: int,
    child_start_ticks: int | None,
    poll_interval_seconds: float = 1.0,
    max_wait_seconds: float = 7200.0,
) -> subprocess.Popen[Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "monitor",
        "--journal-path",
        str(journal_path),
        "--parent-pid",
        str(int(parent_pid)),
        "--child-pid",
        str(int(child_pid)),
        "--poll-interval-seconds",
        str(float(poll_interval_seconds)),
        "--max-wait-seconds",
        str(float(max_wait_seconds)),
    ]
    if run_id:
        command.extend(["--run-id", str(run_id)])
    if territories:
        command.extend(["--territories", *[str(territory) for territory in territories]])
    if parent_start_ticks is not None:
        command.extend(["--parent-start-ticks", str(int(parent_start_ticks))])
    if child_start_ticks is not None:
        command.extend(["--child-start-ticks", str(int(child_start_ticks))])

    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frontend rebuild supervision helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor_parser = subparsers.add_parser("monitor", help="Monitor parent/child PID disappearance during frontend rebuilds.")
    monitor_parser.add_argument("--journal-path", required=True)
    monitor_parser.add_argument("--run-id", default=None)
    monitor_parser.add_argument("--territories", nargs="*", default=[])
    monitor_parser.add_argument("--parent-pid", required=True, type=int)
    monitor_parser.add_argument("--parent-start-ticks", default=None, type=int)
    monitor_parser.add_argument("--child-pid", required=True, type=int)
    monitor_parser.add_argument("--child-start-ticks", default=None, type=int)
    monitor_parser.add_argument("--poll-interval-seconds", default=1.0, type=float)
    monitor_parser.add_argument("--max-wait-seconds", default=7200.0, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "monitor":
        parser.error(f"Unsupported command: {args.command}")

    monitor_frontend_processes(
        journal_path=Path(args.journal_path),
        run_id=args.run_id,
        territories=list(args.territories),
        parent_pid=int(args.parent_pid),
        parent_start_ticks=args.parent_start_ticks,
        child_pid=int(args.child_pid),
        child_start_ticks=args.child_start_ticks,
        poll_interval_seconds=float(args.poll_interval_seconds),
        max_wait_seconds=float(args.max_wait_seconds),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())