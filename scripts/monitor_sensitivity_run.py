#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


SENSITIVITY_MANIFEST_PATH = Path("/home/ubuntu/sib-work/outputs/sensitivity-runs/latest-manifest.json")
MONITOR_TIMEOUT_SECONDS = int(
    os.environ.get("SIB_SENSITIVITY_MONITOR_TIMEOUT_SECONDS", str(24 * 60 * 60))
)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _check_process_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "run_sensitivity_analysis.py"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining}s"


def _snapshot_key(manifest: dict | None) -> str:
    if not manifest:
        return ""
    latest_event = manifest.get("latest_event") or {}
    running = None
    for item in manifest.get("scenarios") or []:
        if str(item.get("status") or "") == "running":
            running = item
            break
    return "|".join(
        [
            str(manifest.get("run_id") or ""),
            str(manifest.get("status") or ""),
            str(manifest.get("updated_at") or ""),
            str(latest_event.get("timestamp") or ""),
            str(latest_event.get("event") or ""),
            str((running or {}).get("scenario_id") or ""),
            str((running or {}).get("child_status") or ""),
        ]
    )


def _print_status(manifest: dict, elapsed_seconds: float) -> None:
    run_id = str(manifest.get("run_id") or "unknown")
    status = str(manifest.get("status") or "unknown")
    completed = int(manifest.get("completed_count") or 0)
    skipped = int(manifest.get("skipped_count") or 0)
    failed = int(manifest.get("failed_count") or 0)
    total = int(manifest.get("scenario_count") or 0)
    latest_event = manifest.get("latest_event") or {}
    print(f"[{_format_duration(elapsed_seconds)}] Run ID: {run_id} | status={status}")
    print(
        "  Progress: "
        f"complete={completed}/{total} | skipped={skipped} | failed={failed} | "
        f"event={latest_event.get('event')}"
    )
    parameters = manifest.get("parameters") or {}
    print(
        "  Parameters: "
        f"pack={parameters.get('scenario_pack')} | tracks={parameters.get('dynamic_max_tracks')} | "
        f"memory_budget_gb={parameters.get('memory_budget_gb')}"
    )

    running = None
    for item in manifest.get("scenarios") or []:
        if str(item.get("status") or "") == "running":
            running = item
            break

    if running is not None:
        print(
            "  Active scenario: "
            f"{running.get('scenario_id')} | tier={running.get('execution_tier')} | "
            f"child_run_id={running.get('child_run_id')} | child_status={running.get('child_status')}"
        )
        child_manifest_path = running.get("child_manifest_path")
        if child_manifest_path:
            child_manifest = _load_json(Path(str(child_manifest_path)))
            if child_manifest:
                territories = child_manifest.get("territories") or {}
                territory_entry = territories.get("guadeloupe") or {}
                impacts = ((territory_entry.get("phases") or {}).get("impacts") or {})
                eai = impacts.get("eai_eur")
                duration = impacts.get("duration_seconds")
                print(
                    "  Active child: "
                    f"status={child_manifest.get('status')} | eai={eai} | impacts_duration_seconds={duration}"
                )

    for item in manifest.get("scenarios") or []:
        scenario_id = str(item.get("scenario_id") or "")
        scenario_status = str(item.get("status") or "pending")
        if scenario_status in {"complete", "failed", "skipped_unsupported"}:
            print(
                f"  - {scenario_id}: {scenario_status} | duration={item.get('duration_seconds')} | error={item.get('error')}"
            )


def main() -> int:
    start_time = time.time()
    print("=" * 70)
    print("SIB Sensitivity Analysis Monitor")
    print("=" * 70)
    print(f"Monitoring: {SENSITIVITY_MANIFEST_PATH}")
    print()
    last_snapshot = None
    while True:
        elapsed = time.time() - start_time
        manifest = _load_json(SENSITIVITY_MANIFEST_PATH)
        snapshot = _snapshot_key(manifest)
        if manifest and snapshot != last_snapshot:
            _print_status(manifest, elapsed)
            last_snapshot = snapshot

        running = _check_process_running()
        if manifest:
            final_status = str(manifest.get("status") or "")
            if final_status == "success":
                print(f"[{_format_duration(elapsed)}] Sensitivity run completed successfully")
                print("=" * 70)
                return 0
            if final_status in {"failed", "partial"}:
                print(f"[{_format_duration(elapsed)}] Sensitivity run ended with status={final_status}")
                print("=" * 70)
                return 1

        if not running and manifest and str(manifest.get("status") or "") == "running":
            print(f"[{_format_duration(elapsed)}] ERROR: sensitivity runner process stopped while manifest is still running")
            print("=" * 70)
            return 1

        if elapsed > MONITOR_TIMEOUT_SECONDS:
            timeout_minutes = int(MONITOR_TIMEOUT_SECONDS // 60)
            print(f"[{_format_duration(elapsed)}] TIMEOUT: sensitivity monitor exceeded {timeout_minutes} minutes")
            print("=" * 70)
            return 1

        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())