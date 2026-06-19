from __future__ import annotations

from datetime import datetime, timezone
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
        memory_budget_gb=6.0,
        child_max_points_per_shard=1500,
        min_points_per_shard=512,
        scenario_pack="/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
    )

    command = _build_child_command(args, scenario)

    assert "--max-points-per-shard" in command
    shard_cap_index = command.index("--max-points-per-shard")
    assert command[shard_cap_index + 1] == "1500"


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
            "--run-id",
            run_id,
        ],
    )

    exit_code = run.main()

    assert exit_code == 0
    assert (run_outputs / run_id / "resume.pid").read_text(encoding="utf-8").strip() == str(os.getpid())


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
