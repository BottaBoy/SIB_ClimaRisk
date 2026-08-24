#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_complete_analysis.py"
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
LOGS_DIR = REPO_ROOT / "logs"


def _load_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest payload: {manifest_path}")
    return payload


def _infer_resume_max_points_per_shard(existing_manifest: dict[str, Any]) -> int | None:
    resumed_at = str(existing_manifest.get("resumed_at") or "").strip()
    territories = existing_manifest.get("territories") if isinstance(existing_manifest.get("territories"), dict) else {}
    candidate_counts: list[int] = []
    fallback_counts: list[int] = []

    for territory_entry in territories.values() if isinstance(territories, dict) else []:
        if not isinstance(territory_entry, dict):
            continue
        impacts = territory_entry.get("impacts") if isinstance(territory_entry.get("impacts"), dict) else {}
        hazards = impacts.get("hazards") if isinstance(impacts, dict) else {}
        if not isinstance(hazards, dict):
            continue
        for hazard_entry in hazards.values():
            if not isinstance(hazard_entry, dict):
                continue
            components = hazard_entry.get("components") if isinstance(hazard_entry.get("components"), dict) else {}
            if not isinstance(components, dict):
                continue
            for component_entry in components.values():
                if not isinstance(component_entry, dict):
                    continue
                shards = component_entry.get("shards") if isinstance(component_entry.get("shards"), dict) else {}
                if not isinstance(shards, dict):
                    continue
                for shard_entry in shards.values():
                    if not isinstance(shard_entry, dict):
                        continue
                    if str(shard_entry.get("status") or "") != "complete":
                        continue
                    point_count = int(shard_entry.get("point_count") or 0)
                    if point_count <= 0:
                        continue
                    fallback_counts.append(point_count)
                    if resumed_at:
                        updated_at = str(shard_entry.get("updated_at") or "").strip()
                        if updated_at and updated_at >= resumed_at:
                            continue
                    candidate_counts.append(point_count)

    if candidate_counts:
        return max(candidate_counts)
    if fallback_counts:
        return max(fallback_counts)
    return None


def _infer_resume_dynamic_max_tracks(existing_manifest: dict[str, Any]) -> int | None:
    parameters = existing_manifest.get("parameters") if isinstance(existing_manifest, dict) else {}
    if not isinstance(parameters, dict):
        return None
    for key in ("requested_dynamic_max_tracks", "dynamic_max_tracks"):
        raw_value = parameters.get(key)
        if raw_value is None:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def _find_live_pids(run_id: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "run_complete_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    needle = f"--resume-run-id {run_id}"
    for raw_line in result.stdout.splitlines():
        if needle not in raw_line:
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
    parser = argparse.ArgumentParser(description="Safely resume a complete-analysis run.")
    parser.add_argument("--run-id", required=True, help="Run ID to resume")
    parser.add_argument(
        "--max-points-per-shard",
        type=int,
        default=None,
        help="Optional safety override; the launcher will still prefer the value inferred from the manifest",
    )
    parser.add_argument(
        "--memory-budget-gb",
        type=float,
        default=6.0,
        help="Memory budget passed to the runner for logging only during resume",
    )
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=None,
        help="Optional safety override; the launcher will prefer the value recorded in the manifest",
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        default=True,
        help="Keep deploy disabled during resume (default: true)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional explicit log path; defaults to logs/run_complete_analysis_<run_id>.log",
    )
    args = parser.parse_args()

    run_id = str(args.run_id).strip()
    if not run_id:
        raise SystemExit("run-id must not be empty")

    manifest = _load_manifest(run_id)
    status = str(manifest.get("status") or "").strip().lower()
    if status == "success":
        raise SystemExit(f"Run {run_id} is already successful; no resume needed.")

    live_pids = _find_live_pids(run_id)
    if live_pids:
        raise SystemExit(
            f"Run {run_id} already has a live process: {live_pids}. "
            "Stop that process first before relaunching."
        )

    inferred_max_points = _infer_resume_max_points_per_shard(manifest)
    if inferred_max_points is None:
        raise SystemExit(
            f"Unable to infer max_points_per_shard from manifest checkpoints for {run_id}."
        )

    if args.max_points_per_shard is not None and int(args.max_points_per_shard) != int(inferred_max_points):
        print(
            f"warning: requested max_points_per_shard={int(args.max_points_per_shard)} "
            f"differs from inferred {int(inferred_max_points)}; using inferred value",
            file=sys.stderr,
        )

    inferred_dynamic_max_tracks = _infer_resume_dynamic_max_tracks(manifest)
    if (
        args.dynamic_max_tracks is not None
        and inferred_dynamic_max_tracks is not None
        and int(args.dynamic_max_tracks) != int(inferred_dynamic_max_tracks)
    ):
        print(
            f"warning: requested dynamic_max_tracks={int(args.dynamic_max_tracks)} "
            f"differs from manifest {int(inferred_dynamic_max_tracks)}; using manifest value",
            file=sys.stderr,
        )
    resolved_dynamic_max_tracks = (
        int(inferred_dynamic_max_tracks)
        if inferred_dynamic_max_tracks is not None
        else int(args.dynamic_max_tracks or 0)
    )

    log_file = Path(args.log_file) if args.log_file else LOGS_DIR / f"run_complete_analysis_{run_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pidfile = RUN_OUTPUTS_DIR / run_id / "resume.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(PYTHON),
        str(RUNNER),
        "--resume-run-id",
        run_id,
        "--dynamic-max-tracks",
        str(resolved_dynamic_max_tracks),
        "--max-points-per-shard",
        str(int(inferred_max_points)),
        "--memory-budget-gb",
        str(float(args.memory_budget_gb)),
        "--no-deploy",
    ]

    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write("\n")
        log_handle.write(f"[launcher] starting resume for {run_id} with max_points_per_shard={inferred_max_points}\n")
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
    print(f"max_points_per_shard={inferred_max_points}")
    print(f"dynamic_max_tracks={resolved_dynamic_max_tracks}")
    print("kill_command:")
    print(f"  kill $(cat {pidfile})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
