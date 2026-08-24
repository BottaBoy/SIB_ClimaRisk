#!/usr/bin/env python3
"""Monitor run progress and notify when complete or failed."""

import json
import os
import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime


MANIFEST_PATH = Path("/home/ubuntu/sib-work/outputs/complete-analysis-runs/latest-manifest.json")
RUN_TIMEOUT_SECONDS = int(
    os.environ.get("SIB_COMPLETE_ANALYSIS_MONITOR_TIMEOUT_SECONDS", str(4 * 60 * 60))
)

def check_process_running():
    """Check if run_complete_analysis.py is still running."""
    result = subprocess.run(
        ["pgrep", "-f", "run_complete_analysis.py"],
        capture_output=True,
        text=True
    )
    return bool(result.stdout.strip())

def check_file_updated(filepath, threshold_minutes=2):
    """Check if file was recently modified."""
    if not Path(filepath).exists():
        return False, None
    
    mtime = Path(filepath).stat().st_mtime
    age_minutes = (time.time() - mtime) / 60
    return age_minutes < threshold_minutes, age_minutes

def format_duration(seconds):
    """Format seconds to mm:ss."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}m {secs}s"


def load_manifest():
    """Load latest run manifest if available."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def manifest_snapshot_key(manifest):
    if not manifest:
        return ""
    latest = manifest.get("latest_event") or {}
    return "|".join(
        [
            str(manifest.get("run_id") or ""),
            str(manifest.get("status") or ""),
            str(manifest.get("updated_at") or ""),
            str(latest.get("timestamp") or ""),
            str(latest.get("event") or ""),
            str(latest.get("hazard") or ""),
            str(latest.get("component") or ""),
        ]
    )


def print_manifest_status(manifest, elapsed):
    run_id = str(manifest.get("run_id") or "unknown")
    status = str(manifest.get("status") or "unknown")
    params = manifest.get("parameters") or {}
    latest_event = manifest.get("latest_event") or {}

    print(f"[{format_duration(elapsed)}] Run ID: {run_id} | status={status}")
    print(
        "  Parameters: "
        f"tracks={params.get('dynamic_max_tracks')} | "
        f"memory_budget_gb={params.get('memory_budget_gb')} | "
        f"max_points_per_shard={params.get('max_points_per_shard')}"
    )
    if latest_event:
        print(
            "  Latest: "
            f"territory={latest_event.get('territory')} | "
            f"event={latest_event.get('event')} | "
            f"hazard={latest_event.get('hazard')} | "
            f"component={latest_event.get('component')}"
        )

    territories = manifest.get("territories") or {}
    for territory, territory_entry in territories.items():
        terr_status = str(territory_entry.get("status") or "unknown")
        print(f"  - {territory}: {terr_status}")
        phases = territory_entry.get("phases") or {}
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
        for hazard_key, hazard_entry in hazards.items():
            components = (hazard_entry.get("components") or {})
            for component_name, component_entry in components.items():
                comp_status = str(component_entry.get("status") or "unknown")
                planned = int(component_entry.get("planned_shards") or 0)
                completed = int(component_entry.get("completed_shards") or 0)
                fragment = f"    {hazard_key}/{component_name}: {comp_status}"
                if planned:
                    fragment += f" | shards={completed}/{planned}"
                if component_entry.get("retry_splits"):
                    fragment += f" | retries={component_entry.get('retry_splits')}"
                if component_entry.get("last_error"):
                    fragment += f" | last_error={component_entry.get('last_error')}"
                print(fragment)

def main():
    """Monitor run and notify completion."""
    start_time = time.time()
    gua_file = "/home/ubuntu/sib-work/web/data/guadeloupe-complete-analysis.json"
    mar_file = "/home/ubuntu/sib-work/web/data/martinique-complete-analysis.json"
    
    print("=" * 70)
    print("SIB Complete Analysis Run Monitor")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Monitoring: {gua_file}")
    print(f"           {mar_file}")
    print()
    print("Status updates:")
    
    last_snapshot = None
    last_gua_time = None
    last_mar_time = None
    gua_completed = False
    mar_completed = False
    
    while True:
        elapsed = time.time() - start_time
        running = check_process_running()
        manifest = load_manifest()
        snapshot = manifest_snapshot_key(manifest)

        if manifest and snapshot != last_snapshot:
            print_manifest_status(manifest, elapsed)
            last_snapshot = snapshot
        
        gua_updated, gua_age = check_file_updated(gua_file)
        mar_updated, mar_age = check_file_updated(mar_file)
        
        if gua_updated and not gua_completed:
            print(f"[{format_duration(elapsed)}] ✓ Guadeloupe completed!")
            gua_completed = True
            last_gua_time = time.time()
        
        if mar_updated and not mar_completed:
            print(f"[{format_duration(elapsed)}] ✓ Martinique completed!")
            mar_completed = True
            last_mar_time = time.time()
        
        if not running and manifest:
            final_status = str(manifest.get("status") or "unknown")
            if final_status == "success":
                print(f"[{format_duration(elapsed)}] ✓✓ ALL TASKS COMPLETED!")
                print("=" * 70)
                return 0
            if final_status in {"failed", "partial"}:
                print(f"[{format_duration(elapsed)}] ✗ RUN ENDED WITH STATUS={final_status}")
                print("=" * 70)
                return 1

        if not running and not gua_completed:
            print(f"[{format_duration(elapsed)}] ✗ ERROR: Process died before completing Guadeloupe")
            return 1
        
        if not running and gua_completed and not mar_completed:
            print(f"[{format_duration(elapsed)}] ✗ ERROR: Process died during Martinique")
            return 1
        
        if gua_completed and mar_completed:
            print(f"[{format_duration(elapsed)}] ✓✓ ALL TASKS COMPLETED!")
            print("=" * 70)
            return 0
        
        # Check for timeout (default: 4 hours, configurable via env var)
        if elapsed > RUN_TIMEOUT_SECONDS:
            timeout_minutes = int(RUN_TIMEOUT_SECONDS // 60)
            print(f"[{format_duration(elapsed)}] ✗ TIMEOUT: Run exceeded {timeout_minutes} minutes")
            return 1
        
        time.sleep(5)

if __name__ == "__main__":
    sys.exit(main())
