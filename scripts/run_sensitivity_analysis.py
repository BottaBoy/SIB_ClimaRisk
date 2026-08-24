#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import os
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

from app.risk_engine.sensitivity_scenarios import (
    SensitivityScenario,
    build_parameter_traceability_matrix,
    list_scenarios_from_pack,
)
from export_sensitivity_matrix import export_sensitivity_run


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

SENSITIVITY_OUTPUTS_DIR = REPO_ROOT / "outputs" / "sensitivity-runs"
COMPLETE_ANALYSIS_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
COMPLETE_ANALYSIS_LATEST_MANIFEST = REPO_ROOT / "outputs" / "complete-analysis-runs" / "latest-manifest.json"
DEFAULT_SCENARIO_PACK = REPO_ROOT / "config" / "sensitivity" / "default-scenario-pack.json"
CHILD_SCRIPT = REPO_ROOT / "scripts" / "run_complete_analysis.py"
RUN_PIDFILE_NAME = "resume.pid"
COMPLETE_ANALYSIS_MANIFEST_RE = re.compile(
    r"(?P<path>/home/ubuntu/sib-work/outputs/complete-analysis-runs/[^\s\"']+/manifest\.json)"
)
OOM_JOURNAL_PATTERNS = (
    "Out of memory: Killed process",
    "invoked oom-killer",
    "has been killed by the OOM killer",
)
EXPECTED_SENSITIVITY_ARTIFACTS = {
    "scenario_summary_csv": ("artifacts", "scenario-summary.csv"),
    "scenario_summary_parquet": ("artifacts", "scenario-summary.parquet"),
    "portfolio_metrics_parquet": ("artifacts", "portfolio-metrics.parquet"),
    "territory_metrics_parquet": ("artifacts", "territory-metrics.parquet"),
    "asset_metrics_parquet": ("artifacts", "asset-metrics.parquet"),
    "matching_metrics_parquet": ("artifacts", "matching-metrics.parquet"),
    "sensitivity_matrix_netcdf": ("artifacts", "sensitivity-matrix.nc"),
    "sensitivity_graphs_summary_json": ("graphs", "sensitivity-graphs-summary.json"),
    "sensitivity_results_normalized_csv": ("graphs", "sensitivity-results-normalized.csv"),
}


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


def _write_run_pidfile(run_id: str, pid: int) -> Path:
    pidfile_path = SENSITIVITY_OUTPUTS_DIR / str(run_id) / RUN_PIDFILE_NAME
    pidfile_path.parent.mkdir(parents=True, exist_ok=True)
    pidfile_path.write_text(f"{int(pid)}\n", encoding="utf-8")
    return pidfile_path


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
        "complete_analysis_json_path": None,
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
                "parameter_traceability": build_parameter_traceability_matrix(scenarios),
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


def _child_manifest_path_from_log(log_path: Path) -> Path | None:
    try:
        content = log_path.read_text(encoding="utf-8")
    except Exception:
        return None
    matches = list(COMPLETE_ANALYSIS_MANIFEST_RE.finditer(content))
    if not matches:
        return None
    return Path(matches[-1].group("path"))


def _complete_analysis_path_from_child_manifest(child_manifest: dict[str, Any] | None) -> str | None:
    if not isinstance(child_manifest, dict):
        return None
    territories = child_manifest.get("territories") if isinstance(child_manifest.get("territories"), dict) else {}
    for territory_name, territory_entry in territories.items():
        if not isinstance(territory_entry, dict):
            continue
        for candidate in (
            territory_entry.get("archived_complete_analysis_path"),
            territory_entry.get("complete_analysis_path"),
        ):
            if candidate and Path(str(candidate)).exists():
                return str(candidate)
        phases = territory_entry.get("phases") if isinstance(territory_entry.get("phases"), dict) else {}
        export_phase = phases.get("export") if isinstance(phases.get("export"), dict) else {}
        for candidate in (
            export_phase.get("archived_output_file"),
            export_phase.get("output_file"),
        ):
            if candidate and Path(str(candidate)).exists():
                return str(candidate)
        standard_path = (
            Path(str(child_manifest.get("manifest_path") or ""))
            if child_manifest.get("manifest_path")
            else None
        )
        if standard_path:
            fallback = standard_path.parent / "territories" / str(territory_name).lower() / "web" / "data" / f"{str(territory_name).lower()}-complete-analysis.json"
            if fallback.exists():
                return str(fallback)
    return None


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
        str(int(args.child_max_points_per_shard)),
        "--min-points-per-shard",
        str(int(args.min_points_per_shard)),
    ]
    track_sample_manifest = getattr(args, "track_sample_manifest", None)
    if track_sample_manifest:
        command.extend(["--track-sample-manifest", str(track_sample_manifest)])
    command.extend(
        [
            "--scenario-pack",
            str(args.scenario_pack),
            "--scenario-id",
            scenario.scenario_id,
        ]
    )
    return command


def _existing_artifacts_for_run(run_id: str) -> dict[str, str]:
    run_dir = SENSITIVITY_OUTPUTS_DIR / str(run_id)
    artifacts: dict[str, str] = {}
    for key, relative_parts in EXPECTED_SENSITIVITY_ARTIFACTS.items():
        path = run_dir.joinpath(*relative_parts)
        if path.exists():
            artifacts[key] = str(path)
    return artifacts


def _finalize_manifest(
    manifest: SensitivityRunManifest,
    *,
    run_id: str,
    scenario_pack: Path,
    continue_on_error: bool,
) -> str:
    export_error: str | None = None
    if int(manifest.data.get("completed_count") or 0) > 0:
        try:
            export_summary = export_sensitivity_run(run_id=run_id, scenario_pack=scenario_pack)
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
        final_status = "partial" if continue_on_error else "failed"
    if export_error and final_status == "success":
        final_status = "partial"
    manifest.set_status(final_status, error=export_error)
    manifest.record_event("complete", status=final_status)
    logger.info("Sensitivity run %s finished with status=%s", run_id, final_status)
    return final_status


def finalize_existing_sensitivity_run(run_id: str) -> str:
    existing_data = _load_existing_parent_manifest(run_id)
    parameters = existing_data.get("parameters") if isinstance(existing_data.get("parameters"), dict) else {}
    scenario_pack_raw = str(parameters.get("scenario_pack") or "").strip()
    scenario_pack = Path(scenario_pack_raw) if scenario_pack_raw else DEFAULT_SCENARIO_PACK
    manifest = SensitivityRunManifest(
        run_id=run_id,
        parameters=parameters,
        scenarios=[],
        existing_data=existing_data,
    )
    existing_artifacts = _existing_artifacts_for_run(run_id)
    if existing_artifacts:
        manifest.data["artifacts"] = existing_artifacts
        missing_required = sorted(
            key
            for key in (
                "scenario_summary_csv",
                "scenario_summary_parquet",
                "portfolio_metrics_parquet",
                "territory_metrics_parquet",
                "asset_metrics_parquet",
                "matching_metrics_parquet",
                "sensitivity_matrix_netcdf",
            )
            if key not in existing_artifacts
        )
        export_error = None
        if missing_required:
            export_error = (
                "Sensitivity export recovery reused existing artifacts but is missing: "
                + ", ".join(missing_required)
            )
            manifest.record_event("matrix_export_reused_partial", missing_artifacts=missing_required)
        else:
            manifest.record_event("matrix_export_reused", artifact_count=len(existing_artifacts))

        final_status = "success"
        if int(manifest.data.get("failed_count") or 0) > 0:
            final_status = "partial" if bool(parameters.get("continue_on_error")) else "failed"
        if export_error and final_status == "success":
            final_status = "partial"
        manifest.set_status(final_status, error=export_error)
        manifest.record_event("complete", status=final_status)
        logger.info("Sensitivity run %s finished with status=%s via artifact recovery", run_id, final_status)
        return final_status
    return _finalize_manifest(
        manifest,
        run_id=run_id,
        scenario_pack=scenario_pack,
        continue_on_error=bool(parameters.get("continue_on_error")),
    )


def _journalctl_text(*, since: datetime, until: datetime) -> str:
    try:
        result = subprocess.run(
            [
                "journalctl",
                "--since",
                since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "--until",
                until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return ""
    return str(result.stdout or "")


def _detect_probable_oom_failure(
    *,
    return_code: int | None,
    started_at: datetime,
    finished_at: datetime,
) -> bool:
    if int(return_code or 0) != -9:
        return False
    journal_text = _journalctl_text(
        since=started_at - timedelta(minutes=2),
        until=finished_at + timedelta(minutes=2),
    )
    return any(pattern in journal_text for pattern in OOM_JOURNAL_PATTERNS)


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
    parser.add_argument(
        "--track-sample-manifest",
        type=Path,
        default=None,
        help="Optional track sample manifest passed through to complete-analysis child runs.",
    )
    parser.add_argument("--memory-budget-gb", type=float, default=6.0)
    parser.add_argument(
        "--max-points-per-shard",
        "--child-max-points-per-shard",
        dest="child_max_points_per_shard",
        type=int,
        default=1500,
        help="Hard cap applied to complete-analysis child runs launched by sensitivity analysis (default: 1500)",
    )
    parser.add_argument("--min-points-per-shard", type=int, default=512)
    parser.add_argument("--allow-degraded-components", action="store_true")
    parser.add_argument("--resume-run-id", type=str, default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-unsupported", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--run-id", type=str, default=None)
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
    requested_run_id = str(args.run_id).strip() if args.run_id else ""
    if args.resume_run_id:
        resolved_run_id = _resolve_resume_run_id(args.resume_run_id)
        if requested_run_id and requested_run_id != resolved_run_id:
            raise ValueError(
                f"Explicit run-id {requested_run_id} does not match resume target {resolved_run_id}"
            )
        existing_data = _load_existing_parent_manifest(resolved_run_id)
        run_id = requested_run_id or resolved_run_id
        existing_ids = [str(item.get("scenario_id") or "") for item in existing_data.get("scenarios") or []]
        requested_ids = [scenario.scenario_id for scenario in scenarios]
        if existing_ids != requested_ids:
            raise ValueError(
                "Resume run scenario order does not match the requested scenario pack selection"
            )
    else:
        run_id = requested_run_id or datetime.now(timezone.utc).strftime("sensitivity_%Y%m%d_%H%M%S")

    parameters = {
        "scenario_pack": str(args.scenario_pack),
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "dynamic_max_tracks": int(args.dynamic_max_tracks),
        "track_sample_manifest": str(args.track_sample_manifest) if args.track_sample_manifest else None,
        "memory_budget_gb": float(args.memory_budget_gb),
        "child_max_points_per_shard": int(args.child_max_points_per_shard),
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
    _write_run_pidfile(run_id, os.getpid())
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
        scenario_started_at = datetime.now(timezone.utc)
        manifest.update_scenario(
            scenario_id,
            status="running",
            started_at=scenario_started_at.isoformat(),
            completed_at=None,
            duration_seconds=None,
            error=None,
            command=command,
            log_path=str(log_path),
            child_run_id=None,
            child_manifest_path=None,
            child_status=None,
            complete_analysis_json_path=None,
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
                if child_manifest is None:
                    child_manifest_path = _child_manifest_path_from_log(log_path)
                    if child_manifest_path is not None:
                        child_manifest = _load_json(child_manifest_path)
                        if child_manifest is not None and str(child_manifest.get("scenario_id") or "") != scenario_id:
                            child_manifest = None
                if child_manifest is not None:
                    manifest.update_scenario(
                        scenario_id,
                        child_run_id=str(child_manifest.get("run_id") or "") or None,
                        child_manifest_path=str(child_manifest.get("manifest_path") or "") or None,
                        child_status=str(child_manifest.get("status") or "") or None,
                        complete_analysis_json_path=_complete_analysis_path_from_child_manifest(child_manifest),
                    )
                return_code = active_process.poll()
                if return_code is not None:
                    break
                time.sleep(max(1.0, float(args.poll_seconds)))

        scenario_finished_at = datetime.now(timezone.utc)
        duration_seconds = int(max(0.0, time.time() - start_time))
        child_manifest = _child_manifest_for_scenario(scenario_id)
        if child_manifest is None:
            child_manifest_path = _child_manifest_path_from_log(log_path)
            if child_manifest_path is not None:
                child_manifest = _load_json(child_manifest_path)
                if child_manifest is not None and str(child_manifest.get("scenario_id") or "") != scenario_id:
                    child_manifest = None
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
                complete_analysis_json_path=_complete_analysis_path_from_child_manifest(child_manifest),
            )

        if (child_status == "success" and return_code == 0) or (not child_status and return_code == 0):
            manifest.update_scenario(
                scenario_id,
                status="complete",
                completed_at=scenario_finished_at.isoformat(),
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
        if _detect_probable_oom_failure(
            return_code=return_code,
            started_at=scenario_started_at,
            finished_at=scenario_finished_at,
        ):
            error += " Probable cause: host OOM killer (kernel out-of-memory kill), not a Python exception in the scenario code."
        manifest.update_scenario(
            scenario_id,
            status="failed",
            completed_at=scenario_finished_at.isoformat(),
            duration_seconds=duration_seconds,
            error=error,
        )
        manifest.record_event("scenario_failed", scenario_id=scenario_id, error=error)
        if not args.continue_on_error:
            manifest.set_status("failed", error=error)
            return 1

    final_status = _finalize_manifest(
        manifest,
        run_id=run_id,
        scenario_pack=Path(args.scenario_pack),
        continue_on_error=bool(args.continue_on_error),
    )
    return 0 if final_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
