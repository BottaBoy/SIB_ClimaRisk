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
    snapshot_parts = [
        str(manifest.get("run_id") or ""),
        str(manifest.get("status") or ""),
        str(manifest.get("updated_at") or ""),
        str(latest_event.get("timestamp") or ""),
        str(latest_event.get("event") or ""),
        str((running or {}).get("scenario_id") or ""),
        str((running or {}).get("child_status") or ""),
    ]
    child_manifest_path = (running or {}).get("child_manifest_path")
    if child_manifest_path:
        child_manifest = _load_json(Path(str(child_manifest_path)))
        if child_manifest:
            child_latest_event = child_manifest.get("latest_event") or {}
            snapshot_parts.extend(
                [
                    str(child_manifest.get("updated_at") or ""),
                    str(child_manifest.get("status") or ""),
                    str(child_latest_event.get("timestamp") or ""),
                    str(child_latest_event.get("event") or ""),
                    str(child_latest_event.get("territory") or ""),
                    str(child_latest_event.get("hazard") or ""),
                    str(child_latest_event.get("component") or ""),
                    str(child_latest_event.get("completed_shards") or ""),
                    str(child_latest_event.get("planned_shards") or ""),
                ]
            )
            territories = child_manifest.get("territories") or {}
            if isinstance(territories, dict):
                for territory_name in sorted(territories):
                    territory_entry = territories.get(territory_name) or {}
                    if not isinstance(territory_entry, dict):
                        continue
                    phases = territory_entry.get("phases") or {}
                    if isinstance(phases, dict):
                        for phase_name in ("load_exposure", "disaggregation", "impacts", "export"):
                            phase_entry = phases.get(phase_name)
                            if isinstance(phase_entry, dict):
                                snapshot_parts.extend(
                                    [
                                        territory_name,
                                        phase_name,
                                        str(phase_entry.get("status") or ""),
                                        str(phase_entry.get("updated_at") or ""),
                                        str(phase_entry.get("duration_seconds") or ""),
                                    ]
                                )
                    hazards = territory_entry.get("impacts") or {}
                    hazard_entries = hazards.get("hazards") if isinstance(hazards, dict) else {}
                    if not isinstance(hazard_entries, dict):
                        continue
                    for hazard_name in sorted(hazard_entries):
                        hazard_entry = hazard_entries.get(hazard_name) or {}
                        if not isinstance(hazard_entry, dict):
                            continue
                        components = hazard_entry.get("components") or {}
                        if not isinstance(components, dict):
                            continue
                        for component_name in ("wind", "rain", "surge"):
                            component_entry = components.get(component_name)
                            if isinstance(component_entry, dict):
                                snapshot_parts.extend(
                                    [
                                        territory_name,
                                        hazard_name,
                                        component_name,
                                        str(component_entry.get("status") or ""),
                                        str(component_entry.get("updated_at") or ""),
                                        str(component_entry.get("completed_shards") or ""),
                                        str(component_entry.get("planned_shards") or ""),
                                        str(component_entry.get("retry_splits") or ""),
                                        str(component_entry.get("resumed_shards") or ""),
                                    ]
                                )
    return "|".join(snapshot_parts)


def _format_shard_progress(component_entry: dict | None) -> str:
    if not isinstance(component_entry, dict):
        return "unknown"
    status = str(component_entry.get("status") or "unknown")
    planned = int(component_entry.get("planned_shards") or 0)
    completed = int(component_entry.get("completed_shards") or 0)
    retry_splits = int(component_entry.get("retry_splits") or 0)
    resumed = int(component_entry.get("resumed_shards") or 0)
    fragment = status
    if planned:
        fragment += f" | shards={completed}/{planned}"
    if retry_splits:
        fragment += f" | retries={retry_splits}"
    if resumed:
        fragment += f" | resumed={resumed}"
    last_error = str(component_entry.get("last_error") or "").strip()
    if last_error:
        fragment += f" | last_error={last_error}"
    return fragment


def _print_child_territory_progress(child_manifest: dict) -> None:
    territories = child_manifest.get("territories") or {}
    if not isinstance(territories, dict) or not territories:
        return

    for territory_name, territory_entry in territories.items():
        if not isinstance(territory_entry, dict):
            continue
        territory_status = str(territory_entry.get("status") or "unknown")
        print(f"    Territory {territory_name}: {territory_status}")

        phases = territory_entry.get("phases") or {}
        if isinstance(phases, dict):
            phase_bits: list[str] = []
            for phase_name in ("load_exposure", "disaggregation", "impacts", "export"):
                phase_entry = phases.get(phase_name)
                if not isinstance(phase_entry, dict):
                    continue
                phase_status = str(phase_entry.get("status") or "unknown")
                if phase_name == "impacts" and phase_entry.get("eai_eur") is not None:
                    phase_bits.append(f"{phase_name}={phase_status} | eai={phase_entry.get('eai_eur'):,.0f} EUR")
                elif phase_name == "load_exposure" and phase_entry.get("asset_count") is not None:
                    phase_bits.append(f"{phase_name}={phase_status} | assets={phase_entry.get('asset_count')}")
                elif phase_name == "disaggregation" and phase_entry.get("point_count") is not None:
                    phase_bits.append(f"{phase_name}={phase_status} | points={phase_entry.get('point_count')}")
                else:
                    phase_bits.append(f"{phase_name}={phase_status}")
            if phase_bits:
                print(f"      Phases: {'; '.join(phase_bits)}")

        hazards = territory_entry.get("impacts") or {}
        hazard_entries = hazards.get("hazards") if isinstance(hazards, dict) else {}
        if not isinstance(hazard_entries, dict):
            continue
        for hazard_key, hazard_entry in hazard_entries.items():
            if not isinstance(hazard_entry, dict):
                continue
            components = hazard_entry.get("components") or {}
            if not isinstance(components, dict) or not components:
                continue
            component_bits: list[str] = []
            for component_name in ("wind", "rain", "surge"):
                component_entry = components.get(component_name)
                if not isinstance(component_entry, dict):
                    continue
                component_bits.append(f"{component_name}={_format_shard_progress(component_entry)}")
            if component_bits:
                print(f"      {hazard_key}: {'; '.join(component_bits)}")


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
                latest_event = child_manifest.get("latest_event") or {}
                print(
                    "  Active child: "
                    f"status={child_manifest.get('status')} | "
                    f"latest_event={latest_event.get('event')} | "
                    f"latest_territory={latest_event.get('territory')}"
                )
                _print_child_territory_progress(child_manifest)

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
