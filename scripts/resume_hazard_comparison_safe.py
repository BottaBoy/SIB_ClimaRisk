#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_hazard_comparative_analysis.py"
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "hazard-comparison-runs"
LOGS_DIR = REPO_ROOT / "logs"


def _load_manifest(run_id: str) -> dict:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest payload: {manifest_path}")
    return payload


def _find_live_pids(run_id: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "run_hazard_comparative_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    needles = (
        f"--resume-run-id {run_id}",
        f"--resume-run-id={run_id}",
        f"--run-id {run_id}",
        f"--run-id={run_id}",
        f"hazard-comparison-runs/{run_id}",
    )
    for raw_line in result.stdout.splitlines():
        if not any(needle in raw_line for needle in needles):
            continue
        parts = raw_line.split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        pids.append(pid)
    return pids


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely resume a hazard-comparison run.")
    parser.add_argument("--run-id", required=True, help="Run ID to resume")
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=None,
        help="Optional override for the dynamic track cap; the launcher will prefer the value stored in the manifest",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional explicit log path; defaults to logs/resume_hazard_comparison_<run_id>.log",
    )
    args = parser.parse_args()

    run_id = str(args.run_id).strip()
    if not run_id:
        raise SystemExit("run-id must not be empty")

    manifest = _load_manifest(run_id)
    status = str(manifest.get("status") or "").strip().lower()
    if status in {"success", "complete", "planned"}:
        raise SystemExit(f"Run {run_id} is already successful; no resume needed.")

    live_pids = _find_live_pids(run_id)
    if live_pids:
        raise SystemExit(
            f"Run {run_id} already has a live process: {live_pids}. "
            "Stop that process first before relaunching."
        )

    manifest_parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    inferred_dynamic_max_tracks = manifest_parameters.get("dynamic_max_tracks")
    if args.dynamic_max_tracks is not None and inferred_dynamic_max_tracks is not None and int(args.dynamic_max_tracks) != int(inferred_dynamic_max_tracks):
        print(
            f"warning: requested dynamic_max_tracks={int(args.dynamic_max_tracks)} "
            f"differs from manifest value {int(inferred_dynamic_max_tracks)}; using the manifest value",
            file=sys.stderr,
        )

    effective_dynamic_max_tracks = (
        int(inferred_dynamic_max_tracks)
        if inferred_dynamic_max_tracks is not None
        else (int(args.dynamic_max_tracks) if args.dynamic_max_tracks is not None else None)
    )

    log_file = Path(args.log_file) if args.log_file else LOGS_DIR / f"resume_hazard_comparison_{run_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pidfile = RUN_OUTPUTS_DIR / run_id / "resume.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(PYTHON),
        str(RUNNER),
        "--resume-run-id",
        run_id,
    ]
    if effective_dynamic_max_tracks is not None:
        cmd.extend(["--dynamic-max-tracks", str(int(effective_dynamic_max_tracks))])

    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write("\n")
        log_handle.write(
            f"[launcher] starting resume for {run_id} "
            f"with dynamic_max_tracks={effective_dynamic_max_tracks}\n"
        )
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
    if effective_dynamic_max_tracks is not None:
        print(f"dynamic_max_tracks={effective_dynamic_max_tracks}")
    print("kill_command:")
    print(f"  kill $(cat {pidfile})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
