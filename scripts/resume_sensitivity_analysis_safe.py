#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_sensitivity_analysis.py"
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "sensitivity-runs"
LOGS_DIR = REPO_ROOT / "logs"
RUN_PIDFILE_NAME = "resume.pid"
PARENT_CHECK_INTERVAL_SECONDS = 5.0


def _human_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_resume_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise SystemExit("run-id must not be empty")
    if value.lower() != "latest":
        return value
    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    payload = _load_json(latest_manifest)
    if not payload:
        raise SystemExit(f"Latest sensitivity manifest not found: {latest_manifest}")
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise SystemExit(f"Latest sensitivity manifest does not contain a run_id: {latest_manifest}")
    return run_id


def _load_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest payload: {manifest_path}")
    return payload


def _read_pidfile(run_id: str) -> tuple[Path, int | None]:
    pidfile_path = RUN_OUTPUTS_DIR / str(run_id) / RUN_PIDFILE_NAME
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


def _find_parent_pids(run_id: str) -> list[int]:
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


def _parent_process_running(run_id: str) -> bool:
    pidfile_path, pidfile_pid = _read_pidfile(run_id)
    if _pid_is_alive(pidfile_pid):
        return True
    return bool(_find_parent_pids(run_id))


def _running_scenario(manifest: dict[str, Any]) -> dict[str, Any] | None:
    for item in manifest.get("scenarios") or []:
        if str(item.get("status") or "") == "running":
            return item if isinstance(item, dict) else None
    return None


def _has_pending_or_running_scenarios(manifest: dict[str, Any]) -> bool:
    for item in manifest.get("scenarios") or []:
        status = str((item or {}).get("status") or "")
        if status in {"pending", "running"}:
            return True
    return False


def _child_is_active(manifest: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    running = _running_scenario(manifest)
    if not running:
        return False, None
    scenario_id = str(running.get("scenario_id") or "").strip()
    if not scenario_id:
        return False, running
    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    scenario_pack = str((parameters or {}).get("scenario_pack") or "").strip() or None
    child_manifest_path_raw = str(running.get("child_manifest_path") or "").strip()
    child_manifest = _load_json(Path(child_manifest_path_raw)) if child_manifest_path_raw else None
    child_status = str(
        (child_manifest or {}).get("status") or running.get("child_status") or ""
    ).strip().lower()
    child_pids = _find_child_pids(scenario_id, scenario_pack)
    child_pid = child_pids[0] if child_pids else None
    child_active = bool(child_pids) and child_status in {"", "running", "pending"}
    enriched = {
        **running,
        "scenario_id": scenario_id,
        "child_manifest_path": child_manifest_path_raw or None,
        "child_manifest_status": child_status or None,
        "child_process_pid": child_pid,
        "child_process_alive": bool(child_active),
    }
    return child_active, enriched


def _build_resume_command(run_id: str, manifest: dict[str, Any]) -> list[str]:
    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    scenario_ids = list(parameters.get("scenario_ids") or [])
    cmd = [
        str(PYTHON),
        str(RUNNER),
        "--resume-run-id",
        str(run_id),
        "--run-id",
        str(run_id),
    ]
    scenario_pack = str(parameters.get("scenario_pack") or "").strip()
    if scenario_pack:
        cmd.extend(["--scenario-pack", scenario_pack])
    if scenario_ids:
        cmd.extend(["--scenario-ids", ",".join(str(item) for item in scenario_ids)])
    if parameters.get("dynamic_max_tracks") is not None:
        cmd.extend(["--dynamic-max-tracks", str(int(parameters.get("dynamic_max_tracks")))])
    if parameters.get("memory_budget_gb") is not None:
        cmd.extend(["--memory-budget-gb", str(float(parameters.get("memory_budget_gb")))])
    if parameters.get("child_max_points_per_shard") is not None:
        cmd.extend(
            [
                "--child-max-points-per-shard",
                str(int(parameters.get("child_max_points_per_shard"))),
            ]
        )
    if parameters.get("min_points_per_shard") is not None:
        cmd.extend(["--min-points-per-shard", str(int(parameters.get("min_points_per_shard")))])
    if parameters.get("continue_on_error"):
        cmd.append("--continue-on-error")
    if parameters.get("fail_on_unsupported"):
        cmd.append("--fail-on-unsupported")
    return cmd


def _wait_for_child_completion(run_id: str, manifest: dict[str, Any], *, poll_seconds: float) -> dict[str, Any]:
    while True:
        child_active, child_state = _child_is_active(manifest)
        if not child_active:
            return manifest
        scenario_id = str((child_state or {}).get("scenario_id") or "unknown")
        child_status = str((child_state or {}).get("child_manifest_status") or "running")
        child_pid = (child_state or {}).get("child_process_pid")
        print(
            f"[{_human_ts()}] child complete-analysis still active for scenario={scenario_id} "
            f"status={child_status} pid={child_pid}; waiting {float(poll_seconds):.0f}s before relaunch",
            flush=True,
        )
        time.sleep(max(1.0, float(poll_seconds)))
        manifest = _load_manifest(run_id)


def _launch_resume(run_id: str, manifest: dict[str, Any]) -> tuple[bool, int | None]:
    run_dir = RUN_OUTPUTS_DIR / str(run_id)
    log_file = LOGS_DIR / f"run_sensitivity_analysis_{run_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pidfile = run_dir / RUN_PIDFILE_NAME
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    cmd = _build_resume_command(run_id, manifest)
    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write("\n")
        log_handle.write(f"[launcher] {_human_ts()} starting resume for {run_id}\n")
        log_handle.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
    print(f"run_id={run_id}")
    print(f"pid={proc.pid}")
    print(f"log_file={log_file}")
    print(f"pidfile={pidfile}")
    print("kill_command:")
    print(f"  kill $(cat {pidfile})")
    return True, proc.pid


def _finalize_terminal_run(run_id: str) -> str:
    import run_sensitivity_analysis as sensitivity_runner

    return str(sensitivity_runner.finalize_existing_sensitivity_run(run_id))


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely resume a sensitivity run.")
    parser.add_argument("--run-id", required=True, help="Run ID to resume, or 'latest'")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Seconds to wait before re-checking an active child complete-analysis run",
    )
    args = parser.parse_args()

    run_id = _resolve_resume_run_id(args.run_id)
    manifest = _load_manifest(run_id)
    status = str(manifest.get("status") or "").strip().lower()
    has_pending_work = _has_pending_or_running_scenarios(manifest)
    parent_running = _parent_process_running(run_id)

    if status == "success":
        raise SystemExit(f"Run {run_id} is already successful; no resume needed.")
    if status in {"partial", "failed", "aborted"} and not has_pending_work:
        raise SystemExit(f"Run {run_id} is terminal with status={status}; no resume needed.")
    if status == "running" and not has_pending_work:
        if parent_running:
            raise SystemExit(f"Run {run_id} already has a live parent process; let it finish.")
        final_status = _finalize_terminal_run(run_id)
        print(f"[{_human_ts()}] finalized terminal sensitivity run {run_id} with status={final_status}")
        return 0 if final_status == "success" else 1
    if parent_running:
        raise SystemExit(f"Run {run_id} already has a live parent process; stop it first.")

    manifest = _wait_for_child_completion(run_id, manifest, poll_seconds=float(args.poll_seconds))

    if _parent_process_running(run_id):
        raise SystemExit(f"Run {run_id} already has a live parent process; stop it first.")

    launched, pid = _launch_resume(run_id, manifest)
    if launched and pid is not None:
        print(f"[{_human_ts()}] relaunch started pid={pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
