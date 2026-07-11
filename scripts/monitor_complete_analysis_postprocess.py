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
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
POSTPROCESS_PROCESS_NEEDLES = (
    "run_complete_analysis.py",
    "rerun_case_studies_light.py",
    "frontend_supervision.py",
    "build_",
    "scientific_graph_postprocess.py",
    "generate_run_graphs.py",
)
FRONTEND_STEP_ORDER = (
    "build_wind_maps",
    "build_landslide_maps",
    "build_multi_hazard_proxy",
    "build_water_infra_map",
    "build_vulnerability_curve_artifacts",
    "build_page_analysis",
    "build_scientific_web_summary",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _human_ts(moment: datetime | None = None) -> str:
    return (moment or datetime.now().astimezone()).astimezone().isoformat(timespec="seconds")


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


def _format_file_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        stat = path.stat()
    except OSError:
        return "unreadable"
    age = time.time() - stat.st_mtime
    size_mb = stat.st_size / (1024 * 1024)
    return f"present | age={_human_duration(age)} | size={size_mb:.1f} MB"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON object: {path}")
    return payload


def _resolve_run_id(raw_run_id: str) -> str:
    run_id = str(raw_run_id or "latest").strip()
    if run_id not in {"latest", "latest-manifest"}:
        return run_id
    latest_path = RUN_OUTPUTS_DIR / "latest-manifest.json"
    payload = _load_json(latest_path)
    resolved = str(payload.get("run_id") or "").strip()
    if not resolved:
        raise ValueError(f"Could not resolve run_id from {latest_path}")
    return resolved


def _manifest_path(run_id: str) -> Path:
    return RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"


def _journal_path(run_id: str, manifest: dict[str, Any] | None = None) -> Path:
    frontend = manifest.get("frontend_artifacts") if isinstance(manifest, dict) else None
    if isinstance(frontend, dict) and frontend.get("supervision_journal"):
        return Path(str(frontend.get("supervision_journal")))
    return RUN_OUTPUTS_DIR / str(run_id) / "frontend-supervision.jsonl"


def _read_journal_events(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _status_from_step_event(event_name: str) -> str:
    if event_name == "step_started":
        return "running"
    if event_name == "step_completed":
        return "complete"
    if event_name == "step_failed":
        return "failed"
    return event_name


def _summarize_frontend_steps(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    steps: dict[str, dict[str, Any]] = {}
    for event in events:
        event_name = str(event.get("event") or "")
        if event_name not in {"step_started", "step_completed", "step_failed"}:
            continue
        step = str(event.get("step") or "").strip()
        if not step:
            continue
        entry = dict(steps.get(step) or {})
        entry.update(
            {
                "status": _status_from_step_event(event_name),
                "timestamp": str(event.get("timestamp") or ""),
                "territory": str(event.get("territory") or ""),
            }
        )
        if event.get("returncode_normalized") is not None:
            entry["returncode"] = event.get("returncode_normalized")
        steps[step] = entry
    return steps


def _latest_frontend_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return events[-1] if events else None


def _frontend_warnings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warning_names = {
        "parent_process_missing",
        "child_process_missing",
        "frontend_rebuild_failed",
        "child_failed",
        "step_failed",
        "manifest_reconciled",
    }
    return [event for event in events if str(event.get("event") or "") in warning_names]


def _format_component(component_entry: dict[str, Any] | None) -> str:
    if not isinstance(component_entry, dict):
        return "unknown"
    status = str(component_entry.get("status") or "unknown")
    planned = int(component_entry.get("planned_shards") or 0)
    completed = int(component_entry.get("completed_shards") or 0)
    resumed = int(component_entry.get("resumed_shards") or 0)
    fragment = status
    if planned:
        fragment += f" {completed}/{planned}"
    if resumed:
        fragment += f" resumed={resumed}"
    if component_entry.get("last_error"):
        fragment += " last_error=present"
    return fragment


def _phase_line(name: str, phase: dict[str, Any] | None) -> str:
    if not isinstance(phase, dict):
        return f"{name}: pending"
    status = str(phase.get("status") or "unknown")
    bits = [f"{name}: {status}"]
    if phase.get("attempt") is not None:
        bits.append(f"attempt={phase.get('attempt')}")
    if phase.get("territories"):
        territories = ",".join(str(item) for item in phase.get("territories") or [])
        bits.append(f"territories={territories}")
    if phase.get("generated_count") is not None:
        bits.append(f"generated={phase.get('generated_count')}")
    if phase.get("duration_seconds") is not None:
        bits.append(f"duration={_human_duration(float(phase.get('duration_seconds') or 0))}")
    if phase.get("last_error"):
        bits.append("last_error=present")
    if phase.get("error"):
        bits.append("error=present")
    return " | ".join(bits)


def _territories_from_manifest(manifest: dict[str, Any]) -> list[str]:
    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    return [str(key) for key in territories.keys()]


def _default_territory(manifest: dict[str, Any], requested: str | None) -> str:
    if requested:
        return requested
    territories = _territories_from_manifest(manifest)
    return territories[0] if territories else "guadeloupe"


def _active_processes() -> list[dict[str, str]]:
    result = subprocess.run(
        ["ps", "-eo", "pid,ppid,%cpu,%mem,rss,etime,state,cmd"],
        capture_output=True,
        text=True,
        check=False,
    )
    rows: list[dict[str, str]] = []
    self_pid = os.getpid()
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, ppid, cpu, mem, rss, etime, state, cmd = parts
        try:
            if int(pid) == self_pid:
                continue
        except ValueError:
            pass
        if not any(needle in cmd for needle in POSTPROCESS_PROCESS_NEEDLES):
            continue
        rows.append(
            {
                "pid": pid,
                "ppid": ppid,
                "cpu": cpu,
                "mem": mem,
                "rss": rss,
                "etime": etime,
                "state": state,
                "cmd": cmd,
            }
        )
    return rows


def _short_cmd(command: str) -> str:
    pieces = command.split()
    if not pieces:
        return command
    script_index = None
    for index, piece in enumerate(pieces):
        if piece.endswith(".py"):
            script_index = index
            break
    if script_index is None:
        return " ".join(pieces[:6])
    script = Path(pieces[script_index]).name
    tail = []
    for piece in pieces[script_index + 1 :]:
        tail.append(piece)
        if len(" ".join(tail)) > 110:
            break
    suffix = " ".join(tail)
    return f"{script} {suffix}".strip()


def _snapshot_key(
    manifest: dict[str, Any],
    events: list[dict[str, Any]],
    processes: list[dict[str, str]],
) -> str:
    latest = manifest.get("latest_event") if isinstance(manifest.get("latest_event"), dict) else {}
    frontend = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else {}
    post = manifest.get("post_run_phases") if isinstance(manifest.get("post_run_phases"), dict) else {}
    latest_journal = _latest_frontend_event(events) or {}
    process_key = ",".join(
        f"{row.get('pid')}:{row.get('state')}:{_short_cmd(row.get('cmd') or '')}"
        for row in processes
    )
    return "|".join(
        [
            str(manifest.get("status") or ""),
            str(manifest.get("updated_at") or ""),
            str(latest.get("timestamp") or ""),
            str(latest.get("event") or ""),
            str(frontend.get("status") or ""),
            json.dumps(post, sort_keys=True, default=str),
            str(latest_journal.get("timestamp") or ""),
            str(latest_journal.get("event") or ""),
            str(latest_journal.get("step") or ""),
            process_key,
        ]
    )


def _print_snapshot(
    *,
    run_id: str,
    manifest: dict[str, Any],
    territory: str,
    journal_path: Path,
    events: list[dict[str, Any]],
    processes: list[dict[str, str]],
    compact: bool = False,
) -> None:
    status = str(manifest.get("status") or "unknown")
    updated_at = _parse_iso_datetime(manifest.get("updated_at"))
    age_seconds = (_now() - updated_at).total_seconds() if updated_at is not None else None
    latest = manifest.get("latest_event") if isinstance(manifest.get("latest_event"), dict) else {}
    print(f"[{_human_ts()}] Post-process monitor run_id={run_id} status={status} age={_human_duration(age_seconds)}")
    if compact:
        latest_event = _latest_frontend_event(events) or {}
        event_bits = [
            str(latest_event.get("event") or "no_frontend_event"),
            str(latest_event.get("territory") or "").strip(),
            str(latest_event.get("step") or "").strip(),
        ]
        print(f"  Latest frontend: {' '.join(bit for bit in event_bits if bit)}")
        return

    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    print(
        "  Parameters: "
        f"tracks={parameters.get('dynamic_max_tracks')} | "
        f"memory_budget_gb={parameters.get('memory_budget_gb')} | "
        f"max_points_per_shard={parameters.get('max_points_per_shard')}"
    )
    if latest:
        print(
            "  Latest impact: "
            f"territory={latest.get('territory')} | "
            f"event={latest.get('event')} | "
            f"hazard={latest.get('hazard')} | "
            f"component={latest.get('component')}"
        )

    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    territory_entry = territories.get(territory) if isinstance(territories, dict) else None
    if isinstance(territory_entry, dict):
        phases = territory_entry.get("phases") if isinstance(territory_entry.get("phases"), dict) else {}
        print(f"  Territory {territory}: {territory_entry.get('status')}")
        for phase_name in ("load_exposure", "disaggregation", "impacts", "export", "scientific_publication"):
            phase = phases.get(phase_name) if isinstance(phases, dict) else None
            if isinstance(phase, dict):
                print(f"    {_phase_line(phase_name, phase)}")
        hazards = ((territory_entry.get("impacts") or {}).get("hazards") or {})
        if isinstance(hazards, dict):
            print("  Impact shards:")
            for hazard_key, hazard_entry in hazards.items():
                components = hazard_entry.get("components") if isinstance(hazard_entry, dict) else {}
                if not isinstance(components, dict):
                    continue
                bits = []
                for component_name in ("wind", "rain", "surge"):
                    bits.append(f"{component_name}={_format_component(components.get(component_name))}")
                print(f"    {hazard_key}: {'; '.join(bits)}")

    frontend = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else None
    post = manifest.get("post_run_phases") if isinstance(manifest.get("post_run_phases"), dict) else {}
    print("  Post-process phases:")
    print(f"    {_phase_line('frontend_artifacts', frontend)}")
    print(f"    {_phase_line('scientific_publication', post.get('scientific_publication') if isinstance(post, dict) else None)}")
    print(f"    {_phase_line('graphs', post.get('graphs') if isinstance(post, dict) else None)}")

    latest_frontend = _latest_frontend_event(events)
    print("  Frontend journal:")
    if latest_frontend:
        print(
            "    latest="
            f"{latest_frontend.get('event')} | "
            f"actor={latest_frontend.get('actor')} | "
            f"territory={latest_frontend.get('territory') or '-'} | "
            f"step={latest_frontend.get('step') or '-'}"
        )
    else:
        print(f"    waiting for {journal_path}")
    steps = _summarize_frontend_steps(events)
    if steps:
        ordered_steps = [step for step in FRONTEND_STEP_ORDER if step in steps]
        ordered_steps.extend(sorted(step for step in steps if step not in set(ordered_steps)))
        for step in ordered_steps:
            entry = steps[step]
            line = f"    {step}: {entry.get('status')}"
            if entry.get("returncode") is not None:
                line += f" | rc={entry.get('returncode')}"
            print(line)
    warnings = _frontend_warnings(events)
    if warnings:
        warning = warnings[-1]
        print(
            "    warning="
            f"{warning.get('event')} | "
            f"actor={warning.get('actor')} | "
            f"step={warning.get('step') or '-'}"
        )

    run_dir = RUN_OUTPUTS_DIR / str(run_id)
    archived_dir = run_dir / "territories" / territory / "web" / "data"
    print("  Outputs:")
    print(f"    complete_analysis: {_format_file_state(archived_dir / f'{territory}-complete-analysis.json')}")
    print(f"    scientific_summary: {_format_file_state(archived_dir / f'{territory}-scientific-web-summary.json')}")
    print(f"    frontend_journal: {_format_file_state(journal_path)}")
    print(f"    graphs_manifest: {_format_file_state(REPO_ROOT / 'outputs' / 'Graphs' / str(run_id) / 'graphs-manifest.json')}")

    print("  Active matching processes:")
    if not processes:
        print("    none")
    else:
        for row in processes:
            print(
                "    "
                f"pid={row['pid']} ppid={row['ppid']} state={row['state']} "
                f"cpu={row['cpu']} mem={row['mem']} rss={row['rss']}KB "
                f"etime={row['etime']} cmd={_short_cmd(row['cmd'])}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only monitor for complete-analysis post-process rebuilds."
    )
    parser.add_argument("run_id", nargs="?", default="latest", help="Run id, or latest.")
    parser.add_argument("--territory", default=None, help="Territory to display. Defaults to the first run territory.")
    parser.add_argument("--poll-seconds", type=float, default=15.0, help="Polling interval.")
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0, help="Compact heartbeat interval.")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    args = parser.parse_args()

    run_id = _resolve_run_id(args.run_id)
    manifest_path = _manifest_path(run_id)
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 2

    print("=" * 70)
    print("SIB Complete Analysis Post-Process Monitor")
    print("=" * 70)
    print(f"Run ID: {run_id}")
    print(f"Manifest: {manifest_path}")
    print("Mode: read-only; no resume, no restart, no manifest writes")
    print("=" * 70)

    last_snapshot = ""
    last_heartbeat = 0.0
    while True:
        try:
            manifest = _load_json(manifest_path)
        except Exception as exc:
            print(f"[{_human_ts()}] unable to read manifest: {exc}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(max(1.0, float(args.poll_seconds)))
            continue

        territory = _default_territory(manifest, args.territory)
        journal_path = _journal_path(run_id, manifest)
        events = _read_journal_events(journal_path)
        processes = _active_processes()
        snapshot = _snapshot_key(manifest, events, processes)
        now_mono = time.monotonic()
        should_print = snapshot != last_snapshot
        compact = False
        if not should_print and now_mono - last_heartbeat >= float(args.heartbeat_seconds):
            should_print = True
            compact = True
        if should_print:
            _print_snapshot(
                run_id=run_id,
                manifest=manifest,
                territory=territory,
                journal_path=journal_path,
                events=events,
                processes=processes,
                compact=compact,
            )
            last_snapshot = snapshot
            last_heartbeat = now_mono

        if args.once:
            return 0

        status = str(manifest.get("status") or "").strip().lower()
        if status in {"success", "failed", "partial"} and not processes:
            return 0 if status == "success" else 1
        time.sleep(max(1.0, float(args.poll_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
