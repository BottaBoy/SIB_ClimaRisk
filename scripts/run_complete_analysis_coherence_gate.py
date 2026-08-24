#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = REPO_ROOT / "outputs"
COMPLETE_ANALYSIS_RUNS_DIR = OUTPUTS_DIR / "complete-analysis-runs"
SENSITIVITY_RUNS_DIR = OUTPUTS_DIR / "sensitivity-runs"
COHERENCE_GATE_OUTPUTS_DIR = OUTPUTS_DIR / "coherence-gates"
DEFAULT_PYTEST_TARGETS = (
    "tests/scripts/test_run_complete_analysis_signals.py",
    "tests/risk_engine/test_impact_runner_aliases.py",
    "tests/risk_engine/test_interdependency_social_summary.py",
    "tests/risk_engine/test_social_impact.py",
    "tests/scripts/test_generate_sensitivity_graphs.py",
    "tests/scripts/test_frontend_rebuild.py",
    "tests/scripts/test_rebuild_frontend_artifacts_for_run.py",
    "tests/scripts/test_publication_contract.py",
    "tests/scripts/test_page_analysis_complete_calibration.py",
)
DEFAULT_SENSITIVITY_SCENARIO_IDS = (
    "all-default",
    "runoff_coeff-0-1",
    "direct_state_thresholds-10-15-50",
)
UTC = timezone.utc


@dataclass
class StepResult:
    name: str
    required: bool
    status: str
    returncode: int | None
    elapsed_seconds: float
    command: list[str] | None
    log_path: str | None
    details: dict[str, Any]


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _slug_now(prefix: str) -> str:
    return datetime.now(UTC).strftime(f"{prefix}_%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _resolve_python() -> Path:
    preferred = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
    if preferred.exists():
        return preferred
    return Path(sys.executable)


def _quote_command(command: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def _run_ids_snapshot(root: Path) -> set[str]:
    return {path.name for path in root.glob("20*") if path.is_dir()}


def _resolve_new_run_id(
    root: Path,
    *,
    before: set[str],
    latest_manifest_path: Path | None = None,
) -> str | None:
    after_paths = [path for path in root.glob("20*") if path.is_dir()]
    new_paths = [path for path in after_paths if path.name not in before]
    if len(new_paths) == 1:
        return new_paths[0].name
    if len(new_paths) > 1:
        return max(new_paths, key=lambda path: path.name).name

    if latest_manifest_path and latest_manifest_path.exists():
        try:
            payload = _load_json(latest_manifest_path)
        except Exception:
            payload = None
        run_id = str((payload or {}).get("run_id") or "").strip() if payload else ""
        if run_id:
            return run_id
    return None


def _write_command_log(
    log_path: Path,
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    completed: subprocess.CompletedProcess[str],
    started_at: str,
    elapsed_seconds: float,
) -> None:
    visible_env = {}
    for key in sorted((env or {}).keys()):
        if key.startswith("SIB_RISK_"):
            visible_env[key] = env[key]

    payload = {
        "started_at": started_at,
        "finished_at": _utcnow(),
        "cwd": str(cwd),
        "command": command,
        "command_pretty": _quote_command(command),
        "returncode": int(completed.returncode),
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "env": visible_env,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_command_step(
    *,
    name: str,
    required: bool,
    command: list[str],
    cwd: Path,
    gate_dir: Path,
    env: dict[str, str] | None = None,
) -> StepResult:
    logs_dir = gate_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{name}.json"
    started_at = _utcnow()
    started_perf = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed_seconds = time.perf_counter() - started_perf
    _write_command_log(
        log_path,
        command=command,
        cwd=cwd,
        env=env,
        completed=completed,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )
    status = "passed" if completed.returncode == 0 else "failed"
    return StepResult(
        name=name,
        required=required,
        status=status,
        returncode=int(completed.returncode),
        elapsed_seconds=round(float(elapsed_seconds), 3),
        command=list(command),
        log_path=str(log_path),
        details={},
    )


def _step_skipped(name: str, *, required: bool, reason: str) -> StepResult:
    return StepResult(
        name=name,
        required=required,
        status="skipped",
        returncode=None,
        elapsed_seconds=0.0,
        command=None,
        log_path=None,
        details={"reason": reason},
    )


def _compute_gate_verdict(steps: list[StepResult]) -> str:
    for step in steps:
        if step.required and step.status != "passed":
            return "blocked"
    return "safe to rerun"


def _collect_gate_alerts(steps: list[StepResult]) -> list[str]:
    alerts: list[str] = []
    for step in steps:
        if step.required and step.status != "passed":
            alerts.append(f"{step.name}={step.status}")
    return alerts


def _complete_analysis_territory_selector(values: list[str] | tuple[str, ...]) -> str:
    normalized = [str(value or "").strip().lower() for value in values if str(value or "").strip()]
    if not normalized:
        raise ValueError("At least one smoke territory is required")
    if len(normalized) == 1:
        return normalized[0]
    normalized_set = set(normalized)
    if normalized_set == {"gua", "mar"} or normalized_set == {"guadeloupe", "martinique"}:
        return "both"
    if normalized_set == {"gua", "mar", "stb"} or normalized_set == {
        "guadeloupe",
        "martinique",
        "saint-barthelemy",
    }:
        return "all"
    raise ValueError(
        "Complete-analysis smoke run only supports a single selector or the built-in pairs both/all"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete-analysis coherence gate: targeted tests, a reduced complete-analysis smoke run, "
            "a reduced sensitivity smoke run, and optional frontend rebuild audit."
        )
    )
    parser.add_argument("--gate-run-id", type=str, default=None)
    parser.add_argument("--pytest-target", action="append", default=None)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-complete-analysis-smoke", action="store_true")
    parser.add_argument("--skip-sensitivity-smoke", action="store_true")
    parser.add_argument("--skip-frontend-audit", action="store_true")
    parser.add_argument("--smoke-territories", nargs="+", default=["stb"])
    parser.add_argument("--smoke-dynamic-max-tracks", type=int, default=150)
    parser.add_argument("--smoke-memory-budget-gb", type=float, default=3.0)
    parser.add_argument("--smoke-max-points-per-shard", type=int, default=0)
    parser.add_argument("--smoke-min-points-per-shard", type=int, default=128)
    parser.add_argument(
        "--sensitivity-scenario-ids",
        type=str,
        default=",".join(DEFAULT_SENSITIVITY_SCENARIO_IDS),
        help="Comma-separated scenario ids for the reduced sensitivity smoke run.",
    )
    parser.add_argument("--sensitivity-dynamic-max-tracks", type=int, default=50)
    parser.add_argument("--sensitivity-memory-budget-gb", type=float, default=2.5)
    parser.add_argument("--sensitivity-max-points-per-shard", type=int, default=0)
    parser.add_argument("--sensitivity-min-points-per-shard", type=int, default=128)
    parser.add_argument("--audit-run-id", type=str, default=None)
    parser.add_argument("--audit-territories", nargs="+", default=None)
    return parser.parse_args()


def _run_targeted_pytests(args: argparse.Namespace, *, python_path: Path, gate_dir: Path) -> StepResult:
    targets = list(args.pytest_target or DEFAULT_PYTEST_TARGETS)
    command = [str(python_path), "-m", "pytest", *targets, "-q"]
    result = _run_command_step(
        name="targeted_pytests",
        required=True,
        command=command,
        cwd=REPO_ROOT,
        gate_dir=gate_dir,
    )
    result.details["pytest_targets"] = targets
    return result


def _run_complete_analysis_smoke(
    args: argparse.Namespace,
    *,
    python_path: Path,
    gate_dir: Path,
) -> StepResult:
    before = _run_ids_snapshot(COMPLETE_ANALYSIS_RUNS_DIR)
    territory_selector = _complete_analysis_territory_selector(args.smoke_territories)
    command = [
        str(python_path),
        str(REPO_ROOT / "scripts" / "run_complete_analysis.py"),
        "--territories",
        territory_selector,
        "--no-deploy",
        "--dynamic-max-tracks",
        str(int(args.smoke_dynamic_max_tracks)),
        "--memory-budget-gb",
        str(float(args.smoke_memory_budget_gb)),
        "--max-points-per-shard",
        str(int(args.smoke_max_points_per_shard)),
        "--min-points-per-shard",
        str(int(args.smoke_min_points_per_shard)),
    ]
    result = _run_command_step(
        name="complete_analysis_smoke",
        required=True,
        command=command,
        cwd=REPO_ROOT,
        gate_dir=gate_dir,
    )

    run_id = _resolve_new_run_id(
        COMPLETE_ANALYSIS_RUNS_DIR,
        before=before,
        latest_manifest_path=COMPLETE_ANALYSIS_RUNS_DIR / "latest-manifest.json",
    )
    result.details["run_id"] = run_id
    if not run_id:
        result.status = "failed"
        result.details["error"] = "Unable to resolve smoke complete-analysis run id"
        return result

    manifest_path = COMPLETE_ANALYSIS_RUNS_DIR / run_id / "manifest.json"
    result.details["manifest_path"] = str(manifest_path)
    if not manifest_path.exists():
        result.status = "failed"
        result.details["error"] = f"Missing smoke complete-analysis manifest: {manifest_path}"
        return result

    manifest = _load_json(manifest_path)
    manifest_status = str(manifest.get("status") or "").strip().lower()
    result.details["manifest_status"] = manifest_status
    result.details["frontend_artifacts"] = manifest.get("frontend_artifacts")
    if result.returncode == 0 and manifest_status == "success":
        result.status = "passed"
    else:
        result.status = "failed"
    return result


def _run_sensitivity_smoke(
    args: argparse.Namespace,
    *,
    python_path: Path,
    gate_dir: Path,
    gate_run_id: str,
) -> StepResult:
    sensitivity_run_id = f"{gate_run_id}_sensitivity"
    scenario_ids = str(args.sensitivity_scenario_ids or "").strip()
    command = [
        str(python_path),
        str(REPO_ROOT / "scripts" / "run_sensitivity_analysis.py"),
        "--run-id",
        sensitivity_run_id,
        "--scenario-ids",
        scenario_ids,
        "--dynamic-max-tracks",
        str(int(args.sensitivity_dynamic_max_tracks)),
        "--memory-budget-gb",
        str(float(args.sensitivity_memory_budget_gb)),
        "--max-points-per-shard",
        str(int(args.sensitivity_max_points_per_shard)),
        "--min-points-per-shard",
        str(int(args.sensitivity_min_points_per_shard)),
    ]
    result = _run_command_step(
        name="sensitivity_smoke",
        required=True,
        command=command,
        cwd=REPO_ROOT,
        gate_dir=gate_dir,
    )
    manifest_path = SENSITIVITY_RUNS_DIR / sensitivity_run_id / "manifest.json"
    result.details["run_id"] = sensitivity_run_id
    result.details["manifest_path"] = str(manifest_path)
    if not manifest_path.exists():
        result.status = "failed"
        result.details["error"] = f"Missing sensitivity manifest: {manifest_path}"
        return result

    manifest = _load_json(manifest_path)
    manifest_status = str(manifest.get("status") or "").strip().lower()
    result.details["manifest_status"] = manifest_status
    if result.returncode == 0 and manifest_status == "success":
        result.status = "passed"
    else:
        result.status = "failed"
        return result

    graphs_command = [
        str(python_path),
        str(REPO_ROOT / "scripts" / "generate_sensitivity_graphs.py"),
        "--manifest",
        str(manifest_path),
    ]
    graphs_result = _run_command_step(
        name="sensitivity_graphs",
        required=True,
        command=graphs_command,
        cwd=REPO_ROOT,
        gate_dir=gate_dir,
    )
    graphs_summary_path = manifest_path.parent / "graphs" / "sensitivity-graphs-summary.json"
    result.details["graphs_step"] = asdict(graphs_result)
    result.details["graphs_summary_path"] = str(graphs_summary_path)
    if graphs_result.status != "passed":
        result.status = "failed"
        return result
    if not graphs_summary_path.exists():
        result.status = "failed"
        result.details["error"] = f"Missing sensitivity graphs summary: {graphs_summary_path}"
        return result

    graphs_summary = _load_json(graphs_summary_path)
    quality_report = graphs_summary.get("quality_report") if isinstance(graphs_summary.get("quality_report"), dict) else {}
    quality_status = str(quality_report.get("status") or "").strip().lower()
    result.details["quality_report_status"] = quality_status
    result.details["quality_report_alerts"] = list(quality_report.get("alerts") or [])
    if quality_status == "failed":
        result.status = "failed"
    elif quality_status == "warning":
        result.status = "failed"
        result.details["error"] = "Sensitivity graphs quality report returned warning status"
    else:
        result.status = "passed"
    return result


def _run_frontend_audit(
    args: argparse.Namespace,
    *,
    python_path: Path,
    gate_dir: Path,
) -> StepResult:
    if not args.audit_run_id:
        return _step_skipped(
            "frontend_audit",
            required=False,
            reason="No --audit-run-id provided",
        )

    command = [
        str(python_path),
        str(REPO_ROOT / "scripts" / "rebuild_frontend_artifacts_for_run.py"),
        "--run-id",
        str(args.audit_run_id),
    ]
    if args.audit_territories:
        command.extend(["--territories", *[str(item) for item in args.audit_territories]])
    result = _run_command_step(
        name="frontend_audit",
        required=True,
        command=command,
        cwd=REPO_ROOT,
        gate_dir=gate_dir,
    )
    manifest_path = COMPLETE_ANALYSIS_RUNS_DIR / str(args.audit_run_id) / "manifest.json"
    result.details["manifest_path"] = str(manifest_path)
    if not manifest_path.exists():
        result.status = "failed"
        result.details["error"] = f"Missing audited manifest: {manifest_path}"
        return result
    manifest = _load_json(manifest_path)
    frontend_artifacts = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else {}
    frontend_status = str(frontend_artifacts.get("status") or "").strip().lower()
    result.details["frontend_artifacts_status"] = frontend_status
    result.details["frontend_artifacts"] = frontend_artifacts
    if result.returncode == 0 and frontend_status == "complete":
        result.status = "passed"
    else:
        result.status = "failed"
    return result


def main() -> int:
    args = _parse_args()
    python_path = _resolve_python()
    gate_run_id = str(args.gate_run_id or _slug_now("coherence_gate"))
    gate_dir = COHERENCE_GATE_OUTPUTS_DIR / gate_run_id
    gate_dir.mkdir(parents=True, exist_ok=True)

    steps: list[StepResult] = []
    if args.skip_tests:
        steps.append(_step_skipped("targeted_pytests", required=False, reason="Skipped by flag"))
    else:
        steps.append(_run_targeted_pytests(args, python_path=python_path, gate_dir=gate_dir))

    if args.skip_complete_analysis_smoke:
        steps.append(_step_skipped("complete_analysis_smoke", required=False, reason="Skipped by flag"))
    else:
        steps.append(_run_complete_analysis_smoke(args, python_path=python_path, gate_dir=gate_dir))

    if args.skip_sensitivity_smoke:
        steps.append(_step_skipped("sensitivity_smoke", required=False, reason="Skipped by flag"))
    else:
        steps.append(
            _run_sensitivity_smoke(
                args,
                python_path=python_path,
                gate_dir=gate_dir,
                gate_run_id=gate_run_id,
            )
        )

    if args.skip_frontend_audit:
        steps.append(_step_skipped("frontend_audit", required=False, reason="Skipped by flag"))
    else:
        steps.append(_run_frontend_audit(args, python_path=python_path, gate_dir=gate_dir))

    verdict = _compute_gate_verdict(steps)
    summary = {
        "gate_run_id": gate_run_id,
        "generated_at": _utcnow(),
        "verdict": verdict,
        "alerts": _collect_gate_alerts(steps),
        "steps": [asdict(step) for step in steps],
    }
    summary_path = gate_dir / "coherence-gate-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[gate] run_id={gate_run_id}")
    print(f"[gate] summary={summary_path}")
    print(f"[gate] verdict={verdict}")
    for step in steps:
        print(
            f"[gate] step={step.name} status={step.status} required={step.required} "
            f"elapsed={step.elapsed_seconds:.3f}s"
        )
    return 0 if verdict == "safe to rerun" else 1


if __name__ == "__main__":
    raise SystemExit(main())
