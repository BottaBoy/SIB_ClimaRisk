#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
RUN_LOGS_DIR = REPO_ROOT / "logs"
RESUME_LAUNCHER = REPO_ROOT / "scripts" / "resume_complete_analysis_safe.py"
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
MAX_BACKOFF_SECONDS = 15 * 60


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: str
    manifest_path: Path
    pidfile_path: Path
    updated_at: datetime | None
    age_seconds: float | None
    latest_event: dict[str, Any]
    pidfile_pid: int | None
    pidfile_alive: bool
    pgrep_pid: int | None
    pgrep_alive: bool

    @property
    def process_alive(self) -> bool:
        return bool(self.pidfile_alive or self.pgrep_alive)

    @property
    def process_source(self) -> str:
        if self.pidfile_alive:
            return "pidfile"
        if self.pgrep_alive:
            return "pgrep"
        if self.pidfile_pid is not None:
            return "pidfile-stale"
        return "none"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _human_ts(moment: datetime | None = None) -> str:
    return (moment or datetime.now().astimezone()).astimezone().isoformat(timespec="seconds")


def _human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {remainder}s"
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"


def _parse_iso_datetime(raw_value: Any) -> datetime | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest payload: {manifest_path}")
    return payload


def _read_pidfile(run_id: str) -> tuple[Path, int | None]:
    pidfile_path = RUN_OUTPUTS_DIR / str(run_id) / "resume.pid"
    if not pidfile_path.exists():
        return pidfile_path, None
    try:
        pid = int(pidfile_path.read_text(encoding="utf-8").strip())
    except Exception:
        return pidfile_path, None
    return pidfile_path, pid


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _find_pgrep_pid(run_id: str) -> int | None:
    result = subprocess.run(
        ["pgrep", "-af", "run_complete_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    exact_needles = (
        f"--resume-run-id {run_id}",
        f"--resume-run-id={run_id}",
        f"run_complete_analysis_{run_id}.log",
    )
    for raw_line in result.stdout.splitlines():
        if not any(needle in raw_line for needle in exact_needles):
            continue
        parts = raw_line.split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if _pid_is_alive(pid):
            return pid
    return None


def _inspect_run(run_id: str, *, manifest: dict[str, Any] | None = None, now: datetime | None = None) -> RunState:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    pidfile_path, pidfile_pid = _read_pidfile(run_id)
    pidfile_alive = _pid_is_alive(pidfile_pid)
    pgrep_pid = _find_pgrep_pid(run_id)
    pgrep_alive = _pid_is_alive(pgrep_pid)

    status = str((manifest or {}).get("status") or "").strip().lower()
    latest_event = manifest.get("latest_event") if isinstance(manifest, dict) and isinstance(manifest.get("latest_event"), dict) else {}
    updated_at = _parse_iso_datetime((manifest or {}).get("updated_at"))
    if updated_at is None and isinstance(latest_event, dict):
        updated_at = _parse_iso_datetime(latest_event.get("timestamp"))
    current_time = now or _now()
    age_seconds = (current_time - updated_at).total_seconds() if updated_at is not None else None

    return RunState(
        run_id=str(run_id),
        status=status,
        manifest_path=manifest_path,
        pidfile_path=pidfile_path,
        updated_at=updated_at,
        age_seconds=age_seconds,
        latest_event=latest_event,
        pidfile_pid=pidfile_pid,
        pidfile_alive=pidfile_alive,
        pgrep_pid=pgrep_pid,
        pgrep_alive=pgrep_alive,
    )


def _format_component(component_entry: dict[str, Any] | None) -> str:
    if not isinstance(component_entry, dict):
        return "unknown"
    status = str(component_entry.get("status") or "unknown")
    planned = int(component_entry.get("planned_shards") or 0)
    completed = int(component_entry.get("completed_shards") or 0)
    resumed = int(component_entry.get("resumed_shards") or 0)
    fragment = status
    if planned:
        fragment += f" | shards={completed}/{planned}"
    if resumed:
        fragment += f" | resumed={resumed}"
    last_error = str(component_entry.get("last_error") or "").strip()
    if last_error:
        fragment += f" | last_error={last_error}"
    return fragment


def _print_detailed_status(manifest: dict[str, Any], state: RunState) -> None:
    run_id = str(manifest.get("run_id") or state.run_id)
    latest_event = manifest.get("latest_event") or {}
    print(f"[{_human_ts()}] Run ID: {run_id} | status={state.status}")
    print(
        "  Health: "
        f"age={_human_duration(state.age_seconds)} | "
        f"process={state.process_source}"
        + (f"({state.pidfile_pid})" if state.pidfile_pid is not None else "")
    )
    if latest_event:
        print(
            "  Latest: "
            f"territory={latest_event.get('territory')} | "
            f"event={latest_event.get('event')} | "
            f"hazard={latest_event.get('hazard')} | "
            f"component={latest_event.get('component')}"
        )
    parameters = manifest.get("parameters") or {}
    print(
        "  Parameters: "
        f"tracks={parameters.get('dynamic_max_tracks')} | "
        f"memory_budget_gb={parameters.get('memory_budget_gb')} | "
        f"max_points_per_shard={parameters.get('max_points_per_shard')}"
    )
    territories = manifest.get("territories") or {}
    for territory_name, territory_entry in territories.items():
        if not isinstance(territory_entry, dict):
            continue
        print(f"  - {territory_name}: {territory_entry.get('status')}")
        phases = territory_entry.get("phases") or {}
        if isinstance(phases, dict):
            for phase_name in ("load_exposure", "disaggregation", "impacts", "export"):
                phase_entry = phases.get(phase_name)
                if not isinstance(phase_entry, dict):
                    continue
                line = f"    {phase_name}: {phase_entry.get('status')}"
                if phase_name == "load_exposure" and phase_entry.get("asset_count") is not None:
                    line += f" | assets={phase_entry.get('asset_count')}"
                if phase_name == "disaggregation" and phase_entry.get("point_count") is not None:
                    line += f" | points={phase_entry.get('point_count')}"
                if phase_name == "impacts" and phase_entry.get("eai_eur") is not None:
                    line += f" | eai={phase_entry.get('eai_eur'):,.0f} EUR"
                if phase_entry.get("error"):
                    line += f" | error={phase_entry.get('error')}"
                print(line)
        hazards = ((territory_entry.get("impacts") or {}).get("hazards") or {})
        if isinstance(hazards, dict):
            for hazard_key, hazard_entry in hazards.items():
                if not isinstance(hazard_entry, dict):
                    continue
                components = hazard_entry.get("components") or {}
                if not isinstance(components, dict):
                    continue
                component_bits = []
                for component_name in ("wind", "rain", "surge"):
                    component_bits.append(
                        f"{component_name}={_format_component(components.get(component_name))}"
                    )
                print(f"    {hazard_key}: {'; '.join(component_bits)}")


def _snapshot_key(manifest: dict[str, Any] | None, state: RunState | None = None) -> str:
    if not manifest:
        return ""
    latest_event = manifest.get("latest_event") or {}
    pieces = [
        str(manifest.get("run_id") or ""),
        str(manifest.get("status") or ""),
        str(manifest.get("updated_at") or ""),
        str(latest_event.get("timestamp") or ""),
        str(latest_event.get("event") or ""),
        str(latest_event.get("territory") or ""),
        str(latest_event.get("hazard") or ""),
        str(latest_event.get("component") or ""),
    ]
    if state is not None:
        pieces.extend(
            [
                str(state.pidfile_pid or ""),
                str(state.pidfile_alive),
                str(state.pgrep_pid or ""),
                str(state.pgrep_alive),
            ]
        )
    return "|".join(pieces)


def _launch_resume(run_id: str) -> tuple[bool, int | None]:
    cmd = [
        str(PYTHON),
        str(RESUME_LAUNCHER),
        "--run-id",
        str(run_id),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        for line in stdout.splitlines():
            print(f"[{_human_ts()}] launcher: {line}", flush=True)
    if stderr:
        for line in stderr.splitlines():
            print(f"[{_human_ts()}] launcher: {line}", file=sys.stderr, flush=True)
    pid = None
    for raw_line in stdout.splitlines():
        if raw_line.startswith("pid="):
            try:
                pid = int(raw_line.split("=", 1)[1].strip())
            except ValueError:
                pid = None
    if result.returncode != 0:
        print(
            f"[{_human_ts()}] launcher exited with code {result.returncode}; "
            "will keep monitoring and retry if needed",
            flush=True,
        )
        return False, pid
    if pid is not None:
        print(f"[{_human_ts()}] relaunch started pid={pid}", flush=True)
    return True, pid


def _restart_delay_seconds(base_delay_seconds: float, restart_count: int) -> float:
    delay = float(base_delay_seconds) * (2 ** max(0, restart_count))
    return min(delay, float(MAX_BACKOFF_SECONDS))


def _should_restart(state: RunState, *, stale_after_seconds: float) -> tuple[bool, str]:
    if state.status == "success":
        return False, "status=success"
    if state.status in {"failed", "aborted", "partial"}:
        if state.process_alive:
            return False, f"status={state.status} but process still alive"
        return True, f"status={state.status}"
    if state.status == "running":
        if state.process_alive:
            return False, "status=running"
        if state.age_seconds is None:
            return True, "status=running but process missing"
        if state.age_seconds >= stale_after_seconds:
            return True, f"status=running but stale for {_human_duration(state.age_seconds)}"
        return True, "status=running but process missing"
    if not state.status:
        if state.process_alive:
            return False, "manifest status missing but process alive"
        return True, "manifest status missing"
    return False, f"status={state.status}"


def babysit_complete_analysis_run(
    run_id: str,
    *,
    poll_seconds: float = 60.0,
    stale_after_minutes: float = 20.0,
    restart_delay_seconds: float = 30.0,
    max_restarts: int | None = None,
    sleep_fn: Any = time.sleep,
    now_fn: Any = _now,
) -> int:
    run_id = str(run_id).strip()
    if not run_id:
        raise ValueError("run_id must not be empty")

    print("=" * 70, flush=True)
    print("SIB Complete Analysis Babysitter", flush=True)
    print(f"Run ID: {run_id}", flush=True)
    print(f"Poll interval: {float(poll_seconds):.1f}s | stale_after: {float(stale_after_minutes):.1f}m", flush=True)
    print(f"Resume launcher: {RESUME_LAUNCHER}", flush=True)
    print("=" * 70, flush=True)

    restart_count = 0
    last_snapshot = ""
    stale_after_seconds = float(stale_after_minutes) * 60.0

    while True:
        manifest = _load_manifest(run_id)
        state = _inspect_run(run_id, manifest=manifest, now=now_fn())
        snapshot = _snapshot_key(manifest, state)

        heartbeat = (
            f"[{_human_ts()}] babysit run_id={run_id} "
            f"status={state.status or 'unknown'} "
            f"age={_human_duration(state.age_seconds)} "
            f"process={state.process_source}"
        )
        if state.latest_event:
            heartbeat += (
                f" latest={state.latest_event.get('event')} "
                f"{state.latest_event.get('territory')} "
                f"{state.latest_event.get('hazard')} "
                f"{state.latest_event.get('component')}"
            )
        print(heartbeat, flush=True)

        if snapshot != last_snapshot:
            _print_detailed_status(manifest, state)
            last_snapshot = snapshot

        if state.status == "success":
            print(f"[{_human_ts()}] run {run_id} completed successfully; babysitter exiting", flush=True)
            return 0

        should_restart, reason = _should_restart(state, stale_after_seconds=stale_after_seconds)
        if should_restart:
            if max_restarts is not None and restart_count >= int(max_restarts):
                print(
                    f"[{_human_ts()}] restart limit reached ({restart_count}/{int(max_restarts)}); exiting",
                    flush=True,
                )
                return 1

            delay = _restart_delay_seconds(restart_delay_seconds, restart_count)
            print(
                f"[{_human_ts()}] relaunch requested for {run_id}: {reason}; "
                f"waiting {delay:.0f}s before retry #{restart_count + 1}",
                flush=True,
            )
            sleep_fn(delay)
            launched, pid = _launch_resume(run_id)
            restart_count += 1
            if launched and pid is not None:
                print(
                    f"[{_human_ts()}] relaunch issued for {run_id} with pid={pid}; "
                    "continuing supervision",
                    flush=True,
                )
            sleep_fn(min(5.0, float(poll_seconds)))
            continue

        sleep_fn(float(poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Babysit a complete-analysis run and relaunch it when it dies.")
    parser.add_argument("--run-id", required=True, help="Run ID to supervise")
    parser.add_argument("--poll-seconds", type=float, default=60.0, help="Seconds between checks (default: 60)")
    parser.add_argument(
        "--stale-after-minutes",
        type=float,
        default=20.0,
        help="Consider a running manifest stale after this many minutes without updates (default: 20)",
    )
    parser.add_argument(
        "--restart-delay-seconds",
        type=float,
        default=30.0,
        help="Initial delay before a relaunch; later retries use exponential backoff (default: 30)",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=None,
        help="Optional hard limit on automatic relaunches; default is unlimited with backoff",
    )
    args = parser.parse_args()
    try:
        return babysit_complete_analysis_run(
            args.run_id,
            poll_seconds=args.poll_seconds,
            stale_after_minutes=args.stale_after_minutes,
            restart_delay_seconds=args.restart_delay_seconds,
            max_restarts=args.max_restarts,
        )
    except KeyboardInterrupt:
        print(f"[{_human_ts()}] babysitter interrupted by user", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
