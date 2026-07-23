from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.risk_engine.sensitivity_scenarios import SensitivityScenario
from scripts import run_sensitivity_analysis as run  # noqa: E402
from scripts.run_sensitivity_analysis import _build_child_command


def test_build_child_command_uses_explicit_child_shard_cap() -> None:
    scenario = SensitivityScenario(
        scenario_id="all-default",
        label="All default",
        parameter_key=None,
        execution_tier="full_rerun",
        supported=True,
        overrides={"settings": {}},
        notes=["reference"],
        source_pack_path=Path("/tmp/dummy-pack.json"),
    )
    args = SimpleNamespace(
        dynamic_max_tracks=1200,
        track_sample_manifest=Path("/tmp/sample_1500/manifest.json"),
        memory_budget_gb=6.0,
        child_max_points_per_shard=1500,
        min_points_per_shard=512,
        scenario_pack="/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
    )

    command = _build_child_command(args, scenario)

    assert "--max-points-per-shard" in command
    shard_cap_index = command.index("--max-points-per-shard")
    assert command[shard_cap_index + 1] == "1500"
    assert "--track-sample-manifest" in command
    sample_index = command.index("--track-sample-manifest")
    assert command[sample_index + 1] == "/tmp/sample_1500/manifest.json"


def test_main_writes_resume_pidfile_for_explicit_run_id(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "sensitivity-runs"
    run_id = "sensitivity_20260614_000000"
    scenario = SensitivityScenario(
        scenario_id="all-default",
        label="All default",
        parameter_key=None,
        execution_tier="full_rerun",
        supported=True,
        overrides={"settings": {}},
        notes=["reference"],
        source_pack_path=Path("/tmp/dummy-pack.json"),
    )

    monkeypatch.setattr(run, "REPO_ROOT", repo_root)
    monkeypatch.setattr(run, "SENSITIVITY_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(run, "COMPLETE_ANALYSIS_LATEST_MANIFEST", repo_root / "outputs" / "complete-analysis-runs" / "latest-manifest.json")
    monkeypatch.setattr(run, "list_scenarios_from_pack", lambda scenario_pack, scenario_ids=None: [scenario])
    monkeypatch.setattr(run, "export_sensitivity_run", lambda run_id, scenario_pack: {"artifacts": {}, "completed_scenario_count": 1, "warning_count": 0})

    class _FakeProc:
        pid = 43210

        def poll(self):
            return 0

    def _fake_popen(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_sensitivity_analysis.py",
            "--scenario-pack",
            "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
            "--scenario-ids",
            "all-default",
            "--track-sample-manifest",
            "/tmp/sample_1500/manifest.json",
            "--run-id",
            run_id,
        ],
    )

    exit_code = run.main()

    assert exit_code == 0
    assert (run_outputs / run_id / "resume.pid").read_text(encoding="utf-8").strip() == str(os.getpid())
    manifest = json.loads((run_outputs / run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["parameters"]["track_sample_manifest"] == "/tmp/sample_1500/manifest.json"


def test_detect_probable_oom_failure_only_flags_sigkill_with_oom_journal(monkeypatch) -> None:
    monkeypatch.setattr(
        run,
        "_journalctl_text",
        lambda **kwargs: "Out of memory: Killed process 1045650 (python)",
    )

    started_at = datetime(2026, 6, 18, 13, 6, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 6, 18, 13, 8, 30, tzinfo=timezone.utc)

    assert run._detect_probable_oom_failure(
        return_code=-9,
        started_at=started_at,
        finished_at=finished_at,
    ) is True
    assert run._detect_probable_oom_failure(
        return_code=1,
        started_at=started_at,
        finished_at=finished_at,
    ) is False


def test_finalize_existing_sensitivity_run_marks_terminal_success(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "sensitivity-runs"
    run_id = "sensitivity_20260619_073544"
    manifest_path = run_outputs / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "parameters": {
                    "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
                    "continue_on_error": False,
                },
                "completed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "scenarios": [
                    {
                        "scenario_id": "all-default",
                        "status": "complete",
                    }
                ],
                "artifacts": {},
                "latest_event": {"event": "start"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(run, "REPO_ROOT", repo_root)
    monkeypatch.setattr(run, "SENSITIVITY_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(run, "DEFAULT_SCENARIO_PACK", repo_root / "config" / "default-pack.json")
    monkeypatch.setattr(
        run,
        "export_sensitivity_run",
        lambda run_id, scenario_pack: {
            "artifacts": {"scenario_summary": "ok"},
            "completed_scenario_count": 1,
            "warning_count": 0,
        },
    )

    final_status = run.finalize_existing_sensitivity_run(run_id)
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert final_status == "success"
    assert updated_manifest["status"] == "success"
    assert updated_manifest["latest_event"]["event"] == "complete"
    assert updated_manifest["artifacts"] == {"scenario_summary": "ok"}


def test_finalize_existing_sensitivity_run_reuses_existing_artifacts(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "sensitivity-runs"
    run_id = "sensitivity_20260619_073544"
    run_dir = run_outputs / run_id
    manifest_path = run_dir / "manifest.json"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "graphs").mkdir(parents=True, exist_ok=True)
    for relative_path in (
        "artifacts/scenario-summary.csv",
        "artifacts/scenario-summary.parquet",
        "artifacts/portfolio-metrics.parquet",
        "artifacts/territory-metrics.parquet",
        "graphs/sensitivity-graphs-summary.json",
        "graphs/sensitivity-results-normalized.csv",
    ):
        (run_dir / relative_path).write_text("ok\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "parameters": {
                    "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
                    "continue_on_error": False,
                },
                "completed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "scenarios": [
                    {
                        "scenario_id": "all-default",
                        "status": "complete",
                    }
                ],
                "artifacts": {},
                "latest_event": {"event": "start"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(run, "REPO_ROOT", repo_root)
    monkeypatch.setattr(run, "SENSITIVITY_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(
        run,
        "export_sensitivity_run",
        lambda run_id, scenario_pack: (_ for _ in ()).throw(AssertionError("export should not run")),
    )

    final_status = run.finalize_existing_sensitivity_run(run_id)
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert final_status == "partial"
    assert updated_manifest["status"] == "partial"
    assert "asset_metrics_parquet" not in updated_manifest["artifacts"]
    assert updated_manifest["latest_event"]["event"] == "complete"
