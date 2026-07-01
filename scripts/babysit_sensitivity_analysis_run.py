#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "sensitivity-runs"
RESUME_LAUNCHER = REPO_ROOT / "scripts" / "resume_sensitivity_analysis_safe.py"
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
MAX_BACKOFF_SECONDS = 15 * 60
BABYSITTER_PIDFILE_NAME = "babysitter.pid"
BABYSITTER_CHECK_INTERVAL_SECONDS = 5.0


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
    has_pending_work: bool
    child_scenario_id: str | None
    child_manifest_path: Path | None
    child_manifest_status: str | None
    child_pid: int | None
    child_alive: bool

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


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


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


def _babysitter_pidfile_path(run_id: str) -> Path:
    return RUN_OUTPUTS_DIR / str(run_id) / BABYSITTER_PIDFILE_NAME


def _read_babysitter_pidfile(run_id: str) -> tuple[Path, int | None]:
    pidfile_path = _babysitter_pidfile_path(run_id)
    if not pidfile_path.exists():
        return pidfile_path, None
    try:
        payload = json.loads(pidfile_path.read_text(encoding="utf-8"))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        try:
            pid = int(payload.get("pid") or 0)
        except Exception:
            pid = None
        return pidfile_path, pid
    try:
        pid = int(pidfile_path.read_text(encoding="utf-8").strip())
    except Exception:
        return pidfile_path, None
    return pidfile_path, pid


def _write_babysitter_pidfile(run_id: str, pid: int) -> Path:
    pidfile_path = _babysitter_pidfile_path(run_id)
    pidfile_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": str(run_id),
        "pid": int(pid),
        "started_at": _human_ts(),
    }
    tmp_path = pidfile_path.with_suffix(".pid.tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, pidfile_path)
    return pidfile_path


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


def _find_pgrep_pids(run_id: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "run_sensitivity_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    exact_needles = (
        f"--resume-run-id {run_id}",
        f"--resume-run-id={run_id}",
        f"--run-id {run_id}",
        f"--run-id={run_id}",
        f"sensitivity-runs/{run_id}",
    )
    pids: list[int] = []
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
            pids.append(pid)
    return pids


def _find_babysitter_pids(run_id: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "babysit_sensitivity_analysis_run.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    exact_needles = (
        f"--run-id {run_id}",
        f"--run-id={run_id}",
    )
    pids: list[int] = []
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
            pids.append(pid)
    return pids


def _find_child_pids(scenario_id: str, scenario_pack: str | None) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "run_complete_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    exact_needles = (
        f"--scenario-id {scenario_id}",
        f"--scenario-id={scenario_id}",
    )
    if scenario_pack:
        exact_needles = exact_needles + (
            f"--scenario-pack {scenario_pack}",
            f"--scenario-pack={scenario_pack}",
        )
    pids: list[int] = []
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
            pids.append(pid)
    return pids


def _is_superseded_babysitter(run_id: str, self_pid: int) -> tuple[bool, int | None]:
    lease_pidfile_path, lease_pid = _read_babysitter_pidfile(run_id)
    if lease_pid is not None and lease_pid != self_pid and _pid_is_alive(lease_pid):
        return True, lease_pid
    other_pids = [pid for pid in _find_babysitter_pids(run_id) if pid != self_pid and _pid_is_alive(pid)]
    if other_pids:
        return True, other_pids[0]
    return False, None


def _sleep_with_owner_checks(
    run_id: str,
    self_pid: int,
    total_seconds: float,
    *,
    sleep_fn: Any = time.sleep,
) -> bool:
    remaining = max(0.0, float(total_seconds))
    while remaining > 0:
        step = min(remaining, BABYSITTER_CHECK_INTERVAL_SECONDS)
        sleep_fn(step)
        remaining -= step
        superseded, owner_pid = _is_superseded_babysitter(run_id, self_pid)
        if superseded:
            print(
                f"[{_human_ts()}] babysitter superseded by pid={owner_pid}; exiting",
                flush=True,
            )
            return False
    return True


def _take_babysitter_ownership(run_id: str, self_pid: int) -> Path:
    existing_pidfile_path, existing_pid = _read_babysitter_pidfile(run_id)
    live_babysitter_pids = [pid for pid in _find_babysitter_pids(run_id) if pid != self_pid]
    takeover_targets: list[int] = []
    if existing_pid is not None and existing_pid != self_pid and _pid_is_alive(existing_pid):
        takeover_targets.append(existing_pid)
    for pid in live_babysitter_pids:
        if pid not in takeover_targets:
            takeover_targets.append(pid)

    if takeover_targets:
        print(
            f"[{_human_ts()}] taking over babysitter for {run_id}; stopping previous babysitter(s): "
            f"{', '.join(str(pid) for pid in takeover_targets)}",
            flush=True,
        )
        for pid in takeover_targets:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            except OSError:
                pass
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if not any(_pid_is_alive(pid) for pid in takeover_targets):
                break
            time.sleep(1.0)
        stubborn_pids = [pid for pid in takeover_targets if _pid_is_alive(pid)]
        for pid in stubborn_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            except OSError:
                pass

    return _write_babysitter_pidfile(run_id, self_pid)


def _find_parent_pids(run_id: str) -> list[int]:
    pidfile_path, pidfile_pid = _read_pidfile(run_id)
    pids = [pidfile_pid] if pidfile_pid is not None else []
    pids.extend(_find_pgrep_pids(run_id))
    return [pid for pid in pids if pid is not None and _pid_is_alive(pid)]


def _running_scenario(manifest: dict[str, Any]) -> dict[str, Any] | None:
    for item in manifest.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") == "running":
            return item
    return None


def _inspect_run(run_id: str, *, manifest: dict[str, Any] | None = None, now: datetime | None = None) -> RunState:
    manifest_data = manifest or {}
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    pidfile_path, pidfile_pid = _read_pidfile(run_id)
    pidfile_alive = _pid_is_alive(pidfile_pid)
    parent_pids = _find_parent_pids(run_id)
    pgrep_pid = parent_pids[0] if parent_pids else None
    pgrep_alive = _pid_is_alive(pgrep_pid)

    status = str(manifest_data.get("status") or "").strip().lower()
    latest_event = (
        manifest_data.get("latest_event")
        if isinstance(manifest_data.get("latest_event"), dict)
        else {}
    )
    updated_at = _parse_iso_datetime(manifest_data.get("updated_at"))
    if updated_at is None and isinstance(latest_event, dict):
        updated_at = _parse_iso_datetime(latest_event.get("timestamp"))
    current_time = now or _now()
    age_seconds = (current_time - updated_at).total_seconds() if updated_at is not None else None

    has_pending_work = False
    for item in manifest_data.get("scenarios") or []:
        status_value = str((item or {}).get("status") or "")
        if status_value in {"pending", "running"}:
            has_pending_work = True
            break

    running = _running_scenario(manifest_data)
    child_scenario_id = None
    child_manifest_path: Path | None = None
    child_manifest_status = None
    child_pid = None
    child_alive = False
    if running is not None:
        child_scenario_id = str(running.get("scenario_id") or "").strip() or None
        child_manifest_path_raw = str(running.get("child_manifest_path") or "").strip()
        if child_manifest_path_raw:
            child_manifest_path = Path(child_manifest_path_raw)
        child_manifest = _load_json(child_manifest_path) if child_manifest_path is not None else None
        child_manifest_status = str(
            (child_manifest or {}).get("status") or running.get("child_status") or ""
        ).strip().lower() or None
        scenario_pack = None
        parameters = manifest_data.get("parameters") if isinstance(manifest_data.get("parameters"), dict) else {}
        if isinstance(parameters, dict):
            scenario_pack = str(parameters.get("scenario_pack") or "").strip() or None
        if child_scenario_id:
            child_pids = _find_child_pids(child_scenario_id, scenario_pack)
            if child_pids:
                child_pid = child_pids[0]
                child_alive = True

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
        has_pending_work=has_pending_work,
        child_scenario_id=child_scenario_id,
        child_manifest_path=child_manifest_path,
        child_manifest_status=child_manifest_status,
        child_pid=child_pid,
        child_alive=child_alive,
    )


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
    ]
    if state is not None:
        pieces.extend(
            [
                str(state.pidfile_pid or ""),
                str(state.pidfile_alive),
                str(state.pgrep_pid or ""),
                str(state.pgrep_alive),
                str(state.child_scenario_id or ""),
                str(state.child_manifest_status or ""),
                str(state.child_pid or ""),
                str(state.child_alive),
            ]
        )
    return "|".join(pieces)


def _format_restart_reason(state: RunState, *, stale_after_seconds: float, silent_hang_after_seconds: float) -> tuple[bool, str, bool]:
    if state.status == "success":
        return False, "status=success", False
    if state.child_alive:
        return False, f"child-active scenario={state.child_scenario_id}", False
    if state.status in {"partial", "failed", "aborted"}:
        if not state.has_pending_work:
            return False, f"status={state.status}", False
        if state.process_alive:
            if state.age_seconds is not None and state.age_seconds >= silent_hang_after_seconds:
                return True, f"status={state.status} but silent for {_human_duration(state.age_seconds)}", True
            return False, f"status={state.status} but process still alive", False
        return True, f"status={state.status}", False
    if state.status == "running":
        if not state.has_pending_work:
            return False, "status=running but no pending work", False
        if state.process_alive:
            if state.age_seconds is not None and state.age_seconds >= silent_hang_after_seconds:
                return True, f"status=running but silent for {_human_duration(state.age_seconds)}", True
            return False, "status=running", False
        if state.age_seconds is None:
            return True, "status=running but process missing", False
        if state.age_seconds >= stale_after_seconds:
            return True, f"status=running but stale for {_human_duration(state.age_seconds)}", False
        return True, "status=running but process missing", False
    if not state.status:
        if state.process_alive:
            return False, "manifest status missing but process alive", False
        if state.has_pending_work:
            return True, "manifest status missing", False
        return False, "manifest status missing and no pending work", False
    return False, f"status={state.status}", False


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
            f"event={latest_event.get('event')} | "
            f"scenario={latest_event.get('scenario_id') or latest_event.get('scenario')}"
        )
    parameters = manifest.get("parameters") or {}
    print(
        "  Parameters: "
        f"pack={parameters.get('scenario_pack')} | "
        f"tracks={parameters.get('dynamic_max_tracks')} | "
        f"memory_budget_gb={parameters.get('memory_budget_gb')} | "
        f"child_max_points_per_shard={parameters.get('child_max_points_per_shard')}"
    )
    if state.child_scenario_id:
        print(
            "  Active child: "
            f"scenario={state.child_scenario_id} | "
            f"status={state.child_manifest_status} | "
            f"pid={state.child_pid}"
        )


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
            f"[{_human_ts()}] launcher exited with code {result.returncode}; will keep monitoring and retry if needed",
            flush=True,
        )
        return False, pid
    if pid is not None:
        print(f"[{_human_ts()}] relaunch started pid={pid}", flush=True)
    return True, pid


def _finalize_terminal_run(run_id: str) -> str:
    import run_sensitivity_analysis as sensitivity_runner

    final_status = str(sensitivity_runner.finalize_existing_sensitivity_run(run_id))
    print(
        f"[{_human_ts()}] finalized terminal sensitivity run {run_id} with status={final_status}",
        flush=True,
    )
    return final_status


def _restart_delay_seconds(base_delay_seconds: float, restart_count: int) -> float:
    delay = float(base_delay_seconds) * (2 ** max(0, restart_count))
    return min(delay, float(MAX_BACKOFF_SECONDS))


def _terminate_live_processes(run_id: str, *, grace_seconds: float = 30.0) -> list[int]:
    pidfile_path, pidfile_pid = _read_pidfile(run_id)
    target_pids = {pidfile_pid} if pidfile_pid is not None else set()
    target_pids.update(_find_pgrep_pids(run_id))
    targets = sorted(pid for pid in target_pids if pid is not None and pid > 0)
    if not targets:
        return []

    print(
        f"[{_human_ts()}] terminating stale process set for {run_id}: "
        f"{', '.join(str(pid) for pid in targets)}",
        flush=True,
    )
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        except OSError:
            pass

    deadline = time.monotonic() + float(grace_seconds)
    while time.monotonic() < deadline:
        if not any(_pid_is_alive(pid) for pid in targets):
            return targets
        time.sleep(1.0)

    stubborn_pids = [pid for pid in targets if _pid_is_alive(pid)]
    if stubborn_pids:
        print(
            f"[{_human_ts()}] forcing kill for stale process set on {run_id}: "
            f"{', '.join(str(pid) for pid in stubborn_pids)}",
            flush=True,
        )
    for pid in stubborn_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        except OSError:
            pass
    return targets


def babysit_sensitivity_analysis_run(
    run_id: str,
    *,
    poll_seconds: float = 60.0,
    stale_after_minutes: float = 20.0,
    silent_hang_after_minutes: float = 30.0,
    restart_delay_seconds: float = 30.0,
    max_restarts: int | None = None,
    sleep_fn: Any = time.sleep,
    now_fn: Any = _now,
) -> int:
    run_id = str(run_id).strip()
    if not run_id:
        raise ValueError("run_id must not be empty")

    self_pid = os.getpid()
    babysitter_pidfile = _take_babysitter_ownership(run_id, self_pid)

    print("=" * 70, flush=True)
    print("SIB Sensitivity Babysitter", flush=True)
    print(f"Run ID: {run_id}", flush=True)
    print(f"Babysitter pidfile: {babysitter_pidfile}", flush=True)
    print(
        "Poll interval: "
        f"{float(poll_seconds):.1f}s | stale_after: {float(stale_after_minutes):.1f}m | "
        f"silent_hang_after: {float(silent_hang_after_minutes):.1f}m",
        flush=True,
    )
    print(f"Resume launcher: {RESUME_LAUNCHER}", flush=True)
    print("=" * 70, flush=True)

    restart_count = 0
    last_snapshot = ""
    stale_after_seconds = float(stale_after_minutes) * 60.0
    silent_hang_after_seconds = float(silent_hang_after_minutes) * 60.0

    while True:
        superseded, owner_pid = _is_superseded_babysitter(run_id, self_pid)
        if superseded:
            print(
                f"[{_human_ts()}] babysitter superseded by pid={owner_pid}; exiting",
                flush=True,
            )
            return 0

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
            heartbeat += f" latest={state.latest_event.get('event')}"
        print(heartbeat, flush=True)

        if snapshot != last_snapshot:
            _print_detailed_status(manifest, state)
            last_snapshot = snapshot

        if state.status == "success":
            print(f"[{_human_ts()}] run {run_id} completed successfully; babysitter exiting", flush=True)
            return 0

        if state.status in {"partial", "failed", "aborted"} and not state.has_pending_work and not state.child_alive:
            print(
                f"[{_human_ts()}] run {run_id} reached terminal status={state.status}; babysitter exiting",
                flush=True,
            )
            return 1

        if state.status == "running" and not state.process_alive and not state.has_pending_work and not state.child_alive:
            final_status = _finalize_terminal_run(run_id)
            if final_status == "success":
                print(f"[{_human_ts()}] run {run_id} completed successfully; babysitter exiting", flush=True)
                return 0
            print(
                f"[{_human_ts()}] run {run_id} reached terminal status={final_status}; babysitter exiting",
                flush=True,
            )
            return 1

        if state.child_alive:
            print(
                f"[{_human_ts()}] child complete-analysis still active for scenario={state.child_scenario_id}; "
                f"waiting before relaunch",
                flush=True,
            )
            if not _sleep_with_owner_checks(run_id, self_pid, float(poll_seconds), sleep_fn=sleep_fn):
                return 0
            continue

        should_restart, reason, kill_first = _format_restart_reason(
            state,
            stale_after_seconds=stale_after_seconds,
            silent_hang_after_seconds=silent_hang_after_seconds,
        )
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
            if not _sleep_with_owner_checks(run_id, self_pid, delay, sleep_fn=sleep_fn):
                return 0
            if kill_first:
                _terminate_live_processes(run_id)
            launched, pid = _launch_resume(run_id)
            restart_count += 1
            if launched and pid is not None:
                print(
                    f"[{_human_ts()}] relaunch issued for {run_id} with pid={pid}; continuing supervision",
                    flush=True,
                )
            if not _sleep_with_owner_checks(run_id, self_pid, min(5.0, float(poll_seconds)), sleep_fn=sleep_fn):
                return 0
            continue

        if not _sleep_with_owner_checks(run_id, self_pid, float(poll_seconds), sleep_fn=sleep_fn):
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Babysit a sensitivity run and relaunch it when it dies.")
    parser.add_argument("--run-id", required=True, help="Run ID to supervise")
    parser.add_argument("--poll-seconds", type=float, default=60.0, help="Seconds between checks (default: 60)")
    parser.add_argument(
        "--stale-after-minutes",
        type=float,
        default=20.0,
        help="Consider a running manifest stale after this many minutes without updates (default: 20)",
    )
    parser.add_argument(
        "--silent-hang-after-minutes",
        type=float,
        default=30.0,
        help="Relaunch a running process that has not updated its manifest for this many minutes (default: 30)",
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
        return babysit_sensitivity_analysis_run(
            args.run_id,
            poll_seconds=args.poll_seconds,
            stale_after_minutes=args.stale_after_minutes,
            silent_hang_after_minutes=args.silent_hang_after_minutes,
            restart_delay_seconds=args.restart_delay_seconds,
            max_restarts=args.max_restarts,
        )
    except KeyboardInterrupt:
        print(f"[{_human_ts()}] babysitter interrupted by user", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
