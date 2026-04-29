#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.sensitivity_scenarios import SensitivityScenario, list_scenarios_from_pack
from export_sensitivity_matrix import export_sensitivity_run


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

SENSITIVITY_OUTPUTS_DIR = REPO_ROOT / "outputs" / "sensitivity-runs"
COMPLETE_ANALYSIS_LATEST_MANIFEST = REPO_ROOT / "outputs" / "complete-analysis-runs" / "latest-manifest.json"
DEFAULT_SCENARIO_PACK = REPO_ROOT / "config" / "sensitivity" / "default-scenario-pack.json"
CHILD_SCRIPT = REPO_ROOT / "scripts" / "run_complete_analysis.py"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_scenario_ids_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    scenario_ids: list[str] = []
    for item in str(raw_value).split(","):
        scenario_id = str(item).strip()
        if scenario_id:
            scenario_ids.append(scenario_id)
    return scenario_ids


def _resolve_resume_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("resume_run_id must not be empty")
    if value.lower() != "latest":
        return value
    latest_manifest = SENSITIVITY_OUTPUTS_DIR / "latest-manifest.json"
    payload = _load_json(latest_manifest)
    if not payload:
        raise FileNotFoundError(f"Latest sensitivity manifest not found: {latest_manifest}")
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest sensitivity manifest does not contain a run_id: {latest_manifest}")
    return run_id


def _scenario_entry_from_scenario(scenario: SensitivityScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "label": scenario.label,
        "parameter_key": scenario.parameter_key,
        "execution_tier": scenario.execution_tier,
        "supported": scenario.supported,
        "notes": list(scenario.notes),
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "duration_seconds": None,
        "error": None,
        "command": None,
        "log_path": None,
        "child_run_id": None,
        "child_manifest_path": None,
        "child_status": None,
    }


class SensitivityRunManifest:
    def __init__(
        self,
        *,
        run_id: str,
        parameters: dict[str, Any],
        scenarios: list[SensitivityScenario],
        existing_data: dict[str, Any] | None = None,
    ):
        self.run_id = str(run_id)
        self.root_dir = SENSITIVITY_OUTPUTS_DIR
        self.run_dir = self.root_dir / self.run_id
        self.manifest_path = self.run_dir / "manifest.json"
        self.latest_path = self.root_dir / "latest-manifest.json"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "logs").mkdir(parents=True, exist_ok=True)
        if existing_data is not None:
            self.data = dict(existing_data)
            self.data["status"] = "running"
            self.data["updated_at"] = _utcnow()
        else:
            self.data = {
                "run_id": self.run_id,
                "status": "running",
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                "manifest_path": str(self.manifest_path),
                "parameters": parameters,
                "scenario_count": len(scenarios),
                "completed_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "scenarios": [_scenario_entry_from_scenario(scenario) for scenario in scenarios],
                "artifacts": {},
                "latest_event": None,
            }
        self._recompute_counts()
        self._save()

    def _recompute_counts(self) -> None:
        scenarios = list(self.data.get("scenarios") or [])
        self.data["scenario_count"] = len(scenarios)
        self.data["completed_count"] = sum(1 for item in scenarios if item.get("status") == "complete")
        self.data["failed_count"] = sum(1 for item in scenarios if item.get("status") == "failed")
        self.data["skipped_count"] = sum(1 for item in scenarios if str(item.get("status") or "").startswith("skipped"))

    def _save(self) -> None:
        self.data["updated_at"] = _utcnow()
        self._recompute_counts()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        self.manifest_path.write_text(payload, encoding="utf-8")
        self.latest_path.write_text(payload, encoding="utf-8")

    def record_event(self, event: str, **fields: Any) -> None:
        self.data["latest_event"] = {
            "timestamp": _utcnow(),
            "event": str(event),
            **fields,
        }
        self._save()

    def set_status(self, status: str, *, error: str | None = None) -> None:
        self.data["status"] = str(status)
        if error:
            self.data["error"] = str(error)
        self._save()

    def _find_scenario_index(self, scenario_id: str) -> int:
        for idx, item in enumerate(self.data.get("scenarios") or []):
            if str(item.get("scenario_id") or "") == scenario_id:
                return idx
        raise KeyError(f"Scenario not found in manifest: {scenario_id}")

    def get_scenario_status(self, scenario_id: str) -> str:
        idx = self._find_scenario_index(scenario_id)
        return str(self.data["scenarios"][idx].get("status") or "pending")

    def update_scenario(self, scenario_id: str, **fields: Any) -> None:
        idx = self._find_scenario_index(scenario_id)
        self.data["scenarios"][idx].update(fields)
        self._save()

    def scenario_log_path(self, scenario_id: str) -> Path:
        return self.run_dir / "logs" / f"{scenario_id}.log"


def _load_existing_parent_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = SENSITIVITY_OUTPUTS_DIR / run_id / "manifest.json"
    payload = _load_json(manifest_path)
    if not payload:
        raise FileNotFoundError(f"Sensitivity manifest not found: {manifest_path}")
    return payload


def _child_manifest_for_scenario(scenario_id: str) -> dict[str, Any] | None:
    payload = _load_json(COMPLETE_ANALYSIS_LATEST_MANIFEST)
    if not payload:
        return None
    if str(payload.get("scenario_id") or "") != scenario_id:
        return None
    return payload


def _build_child_command(args: argparse.Namespace, scenario: SensitivityScenario) -> list[str]:
    command = [
        sys.executable,
        str(CHILD_SCRIPT),
        "--territories",
        "gua",
        "--no-deploy",
        "--dynamic-max-tracks",
        str(int(args.dynamic_max_tracks)),
        "--memory-budget-gb",
        str(float(args.memory_budget_gb)),
        "--max-points-per-shard",
        str(int(args.max_points_per_shard)),
        "--min-points-per-shard",
        str(int(args.min_points_per_shard)),
        "--scenario-pack",
        str(args.scenario_pack),
        "--scenario-id",
        scenario.scenario_id,
    ]
    return command


def _print_scenarios(scenarios: list[SensitivityScenario]) -> None:
    for scenario in scenarios:
        marker = "supported" if scenario.supported else "unsupported"
        print(f"{scenario.scenario_id}\t{marker}\t{scenario.execution_tier}\t{scenario.label}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Guadeloupe sensitivity-analysis scenario pack")
    parser.add_argument("--scenario-pack", type=Path, default=DEFAULT_SCENARIO_PACK)
    parser.add_argument(
        "--scenario-ids",
        type=str,
        default="",
        help="Optional comma-separated subset of scenario ids to run; blank means the full pack order",
    )
    parser.add_argument("--dynamic-max-tracks", type=int, default=1200)
    parser.add_argument("--memory-budget-gb", type=float, default=6.0)
    parser.add_argument("--max-points-per-shard", type=int, default=0)
    parser.add_argument("--min-points-per-shard", type=int, default=512)
    parser.add_argument("--allow-degraded-components", action="store_true")
    parser.add_argument("--resume-run-id", type=str, default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-unsupported", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--list-scenarios", action="store_true")
    args = parser.parse_args()
    if args.allow_degraded_components:
        parser.error("--allow-degraded-components has been removed; scientific runs must remain strict multi-hazard")

    scenario_ids = _parse_scenario_ids_csv(args.scenario_ids)
    scenarios = list_scenarios_from_pack(args.scenario_pack, scenario_ids=scenario_ids or None)
    if args.list_scenarios:
        _print_scenarios(scenarios)
        return 0
    if not scenarios:
        raise ValueError(f"No scenarios selected from {args.scenario_pack}")

    existing_data: dict[str, Any] | None = None
    if args.resume_run_id:
        resolved_run_id = _resolve_resume_run_id(args.resume_run_id)
        existing_data = _load_existing_parent_manifest(resolved_run_id)
        run_id = resolved_run_id
        existing_ids = [str(item.get("scenario_id") or "") for item in existing_data.get("scenarios") or []]
        requested_ids = [scenario.scenario_id for scenario in scenarios]
        if existing_ids != requested_ids:
            raise ValueError(
                "Resume run scenario order does not match the requested scenario pack selection"
            )
    else:
        run_id = datetime.now(timezone.utc).strftime("sensitivity_%Y%m%d_%H%M%S")

    parameters = {
        "scenario_pack": str(args.scenario_pack),
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "dynamic_max_tracks": int(args.dynamic_max_tracks),
        "memory_budget_gb": float(args.memory_budget_gb),
        "max_points_per_shard": int(args.max_points_per_shard),
        "min_points_per_shard": int(args.min_points_per_shard),
        "allow_degraded_components": bool(args.allow_degraded_components),
        "continue_on_error": bool(args.continue_on_error),
        "fail_on_unsupported": bool(args.fail_on_unsupported),
        "territories": ["guadeloupe"],
    }
    manifest = SensitivityRunManifest(
        run_id=run_id,
        parameters=parameters,
        scenarios=scenarios,
        existing_data=existing_data,
    )
    manifest.record_event("start", scenario_count=len(scenarios))

    active_process: subprocess.Popen[str] | None = None
    active_scenario_id: str | None = None
    termination_recorded = False

    def _record_termination(reason: str) -> None:
        nonlocal termination_recorded
        if termination_recorded:
            return
        if active_process is None and active_scenario_id is None:
            return
        termination_recorded = True
        if active_process is not None and active_process.poll() is None:
            active_process.terminate()
        if active_scenario_id:
            manifest.update_scenario(
                active_scenario_id,
                status="failed",
                completed_at=_utcnow(),
                error=reason,
            )
        manifest.set_status("partial", error=reason)

    def _handle_atexit() -> None:
        _record_termination("Parent sensitivity runner interrupted")

    def _handle_signal(signum: int, _frame: Any | None) -> None:
        _record_termination(f"Parent sensitivity runner interrupted by signal {signum}")
        raise SystemExit(1)

    atexit.register(_handle_atexit)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    for scenario in scenarios:
        scenario_id = scenario.scenario_id
        previous_status = manifest.get_scenario_status(scenario_id)
        if previous_status in {"complete", "skipped_unsupported"}:
            logger.info("Skipping already finished scenario %s (%s)", scenario_id, previous_status)
            continue

        if not scenario.supported:
            message = (
                f"Scenario '{scenario_id}' is not yet automatable and requires a manual profile definition"
            )
            if args.fail_on_unsupported:
                manifest.update_scenario(
                    scenario_id,
                    status="failed",
                    completed_at=_utcnow(),
                    error=message,
                )
                manifest.set_status("failed", error=message)
                return 1
            manifest.update_scenario(
                scenario_id,
                status="skipped_unsupported",
                completed_at=_utcnow(),
                error=message,
            )
            manifest.record_event("scenario_skipped", scenario_id=scenario_id, reason="unsupported")
            continue

        command = _build_child_command(args, scenario)
        log_path = manifest.scenario_log_path(scenario_id)
        logger.info("Running scenario %s", scenario_id)
        manifest.update_scenario(
            scenario_id,
            status="running",
            started_at=_utcnow(),
            completed_at=None,
            duration_seconds=None,
            error=None,
            command=command,
            log_path=str(log_path),
            child_run_id=None,
            child_manifest_path=None,
            child_status=None,
        )
        manifest.record_event("scenario_started", scenario_id=scenario_id)

        start_time = time.time()
        active_scenario_id = scenario_id
        with log_path.open("w", encoding="utf-8") as handle:
            active_process = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

            while True:
                child_manifest = _child_manifest_for_scenario(scenario_id)
                if child_manifest is not None:
                    manifest.update_scenario(
                        scenario_id,
                        child_run_id=str(child_manifest.get("run_id") or "") or None,
                        child_manifest_path=str(child_manifest.get("manifest_path") or "") or None,
                        child_status=str(child_manifest.get("status") or "") or None,
                    )
                return_code = active_process.poll()
                if return_code is not None:
                    break
                time.sleep(max(1.0, float(args.poll_seconds)))

        duration_seconds = int(max(0.0, time.time() - start_time))
        child_manifest = _child_manifest_for_scenario(scenario_id)
        child_status = str((child_manifest or {}).get("status") or "")
        child_run_id = str((child_manifest or {}).get("run_id") or "") or None
        child_manifest_path = str((child_manifest or {}).get("manifest_path") or "") or None
        active_process = None
        active_scenario_id = None

        if child_manifest is not None and active_process is None:
            manifest.update_scenario(
                scenario_id,
                child_run_id=child_run_id,
                child_manifest_path=child_manifest_path,
                child_status=child_status or None,
            )

        if (child_status == "success" and return_code == 0) or (not child_status and return_code == 0):
            manifest.update_scenario(
                scenario_id,
                status="complete",
                completed_at=_utcnow(),
                duration_seconds=duration_seconds,
                error=None,
            )
            manifest.record_event(
                "scenario_completed",
                scenario_id=scenario_id,
                duration_seconds=duration_seconds,
                child_run_id=child_run_id,
            )
            continue

        error = (
            f"Scenario failed with returncode={return_code}, child_status={child_status or 'unknown'}; "
            f"see {log_path}"
        )
        manifest.update_scenario(
            scenario_id,
            status="failed",
            completed_at=_utcnow(),
            duration_seconds=duration_seconds,
            error=error,
        )
        manifest.record_event("scenario_failed", scenario_id=scenario_id, error=error)
        if not args.continue_on_error:
            manifest.set_status("failed", error=error)
            return 1

    export_error: str | None = None
    if int(manifest.data.get("completed_count") or 0) > 0:
        try:
            export_summary = export_sensitivity_run(run_id=run_id, scenario_pack=Path(args.scenario_pack))
            manifest.data["artifacts"] = dict(export_summary.get("artifacts") or {})
            manifest.record_event(
                "matrix_export_completed",
                completed_scenario_count=int(export_summary.get("completed_scenario_count") or 0),
                warning_count=int(export_summary.get("warning_count") or 0),
                artifacts=manifest.data["artifacts"],
            )
        except Exception as exc:
            export_error = f"Sensitivity matrix export failed ({type(exc).__name__}): {exc}"
            manifest.record_event("matrix_export_failed", error=export_error)

    final_status = "success"
    if int(manifest.data.get("failed_count") or 0) > 0:
        final_status = "partial" if args.continue_on_error else "failed"
    if export_error and final_status == "success":
        final_status = "partial"
    manifest.set_status(final_status, error=export_error)
    manifest.record_event("complete", status=final_status)
    logger.info("Sensitivity run %s finished with status=%s", run_id, final_status)
    return 0 if final_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())