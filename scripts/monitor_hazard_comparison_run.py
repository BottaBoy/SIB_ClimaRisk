#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


HAZARD_COMPARISON_MANIFEST_PATH = Path(
    "/home/ubuntu/sib-work/outputs/hazard-comparison-runs/latest-manifest.json"
)
MONITOR_TIMEOUT_SECONDS = int(
    os.environ.get("SIB_HAZARD_COMPARISON_MONITOR_TIMEOUT_SECONDS", str(24 * 60 * 60))
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
        ["pgrep", "-f", "run_hazard_comparative_analysis.py"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining}s"


def _format_selection(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "all"
    return ",".join(str(value) for value in values)


def _snapshot_key(manifest: dict | None) -> str:
    if not manifest:
        return ""
    latest_event = manifest.get("latest_event") or {}
    return "|".join(
        [
            str(manifest.get("run_id") or ""),
            str(manifest.get("status") or ""),
            str(manifest.get("updated_at") or ""),
            str(manifest.get("mode") or ""),
            str(latest_event.get("timestamp") or ""),
            str(latest_event.get("event") or ""),
            str(latest_event.get("territory") or ""),
            str(latest_event.get("scenario") or ""),
            str(latest_event.get("component") or ""),
        ]
    )


def _phase_summary(territory_payload: dict) -> str:
    ordered_phases = (
        "phase2_preflight",
        "phase3_hazard_build",
        "phase4_metric_extraction",
        "phase5_export_artifacts",
        "phase6_html_report",
    )
    phases = territory_payload.get("phases") or {}
    fragments: list[str] = []
    for phase_name in ordered_phases:
        phase_payload = phases.get(phase_name)
        if not isinstance(phase_payload, dict):
            continue
        status = str(phase_payload.get("status") or "")
        if status:
            fragments.append(f"{phase_name}={status}")
    return " | ".join(fragments)


def _active_scenario_summary(territory_payload: dict) -> str:
    scenarios = territory_payload.get("scenarios") or {}
    fragments: list[str] = []
    for scenario_id, scenario_payload in scenarios.items():
        if not isinstance(scenario_payload, dict):
            continue
        scenario_status = str(scenario_payload.get("status") or "unknown")
        if scenario_status == "complete":
            continue
        component_fragments: list[str] = []
        for component_id, component_payload in (scenario_payload.get("components") or {}).items():
            if not isinstance(component_payload, dict):
                continue
            component_status = str(component_payload.get("status") or "")
            if component_status and component_status != "complete":
                component_fragments.append(f"{component_id}={component_status}")
        fragment = f"{scenario_id}={scenario_status}"
        if component_fragments:
            fragment += f" ({', '.join(component_fragments)})"
        fragments.append(fragment)
        if len(fragments) >= 2:
            break
    return " | ".join(fragments)


def _print_status(manifest: dict, elapsed_seconds: float) -> None:
    run_id = str(manifest.get("run_id") or "unknown")
    status = str(manifest.get("status") or "unknown")
    mode = str(manifest.get("mode") or "unknown")
    parameters = manifest.get("parameters") or {}
    latest_event = manifest.get("latest_event") or {}

    print(f"[{_format_duration(elapsed_seconds)}] Run ID: {run_id} | status={status} | mode={mode}")
    print(
        "  Parameters: "
        f"tracks={parameters.get('dynamic_max_tracks')} | "
        f"territories={_format_selection(parameters.get('territories'))} | "
        f"scenarios={_format_selection(parameters.get('scenarios'))}"
    )
    if latest_event:
        print(
            "  Latest event: "
            f"phase={latest_event.get('phase')} | "
            f"event={latest_event.get('event')} | "
            f"territory={latest_event.get('territory')} | "
            f"scenario={latest_event.get('scenario')} | "
            f"component={latest_event.get('component')}"
        )

    output_fragments: list[str] = []
    for key in ("comparison_metrics", "comparison_exports", "comparison_report"):
        payload = manifest.get(key)
        if isinstance(payload, dict) and payload.get("status"):
            output_fragments.append(f"{key}={payload.get('status')}")
    if output_fragments:
        print(f"  Outputs: {' | '.join(output_fragments)}")

    territories = manifest.get("territories") or {}
    for territory_id, territory_payload in territories.items():
        if not isinstance(territory_payload, dict):
            continue
        territory_status = str(territory_payload.get("status") or "unknown")
        scenarios = territory_payload.get("scenarios") or {}
        total_scenarios = len(scenarios)
        completed_scenarios = sum(
            1
            for scenario_payload in scenarios.values()
            if isinstance(scenario_payload, dict)
            and str(scenario_payload.get("status") or "") == "complete"
        )
        print(
            f"  - {territory_id}: status={territory_status} | "
            f"scenarios={completed_scenarios}/{total_scenarios} complete"
        )
        phase_summary = _phase_summary(territory_payload)
        if phase_summary:
            print(f"    phases: {phase_summary}")
        active_summary = _active_scenario_summary(territory_payload)
        if active_summary:
            print(f"    active: {active_summary}")


def main() -> int:
    start_time = time.time()
    print("=" * 70)
    print("SIB Hazard Comparison Run Monitor")
    print("=" * 70)
    print(f"Monitoring: {HAZARD_COMPARISON_MANIFEST_PATH}")
    print()

    last_snapshot = None
    while True:
        elapsed = time.time() - start_time
        manifest = _load_json(HAZARD_COMPARISON_MANIFEST_PATH)
        snapshot = _snapshot_key(manifest)
        if manifest and snapshot != last_snapshot:
            _print_status(manifest, elapsed)
            last_snapshot = snapshot

        running = _check_process_running()
        if manifest:
            final_status = str(manifest.get("status") or "")
            if final_status in {"complete", "planned"} and not running:
                print(f"[{_format_duration(elapsed)}] Hazard comparison run finished with status={final_status}")
                print("=" * 70)
                return 0
            if final_status == "failed":
                print(f"[{_format_duration(elapsed)}] Hazard comparison run failed")
                print("=" * 70)
                return 1

        if not running and manifest and str(manifest.get("status") or "") in {"running", "ready", "building"}:
            print(
                f"[{_format_duration(elapsed)}] ERROR: comparison runner process stopped while manifest is still active"
            )
            print("=" * 70)
            return 1

        if not manifest and not running and elapsed > 10:
            print(f"[{_format_duration(elapsed)}] ERROR: no active hazard comparison run detected")
            print("=" * 70)
            return 1

        if elapsed > MONITOR_TIMEOUT_SECONDS:
            timeout_minutes = int(MONITOR_TIMEOUT_SECONDS // 60)
            print(
                f"[{_format_duration(elapsed)}] TIMEOUT: hazard comparison monitor exceeded {timeout_minutes} minutes"
            )
            print("=" * 70)
            return 1

        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())