from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import resume_sensitivity_analysis_safe as safe  # noqa: E402


def test_main_uses_resume_launcher_and_writes_pidfile(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "sensitivity-runs"
    log_root = repo_root / "logs"
    run_id = "sensitivity_20260609_140911"
    manifest_path = run_outputs / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "parameters": {
                    "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
                    "scenario_ids": ["all-default"],
                    "dynamic_max_tracks": 1200,
                    "memory_budget_gb": 6.0,
                    "child_max_points_per_shard": 1500,
                    "min_points_per_shard": 512,
                    "continue_on_error": True,
                    "fail_on_unsupported": False,
                },
                "scenarios": [
                    {
                        "scenario_id": "all-default",
                        "status": "running",
                        "child_status": "running",
                        "child_manifest_path": None,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(safe, "REPO_ROOT", repo_root)
    monkeypatch.setattr(safe, "RUN_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(safe, "LOGS_DIR", log_root)
    monkeypatch.setattr(safe, "_find_parent_pids", lambda run_id: [])
    monkeypatch.setattr(safe, "_find_child_pids", lambda scenario_id, scenario_pack: [])

    recorded: dict[str, object] = {}

    class _FakeProc:
        pid = 98765

    def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, start_new_session=None, env=None):
        recorded["cmd"] = cmd
        recorded["cwd"] = cwd
        recorded["env"] = env
        return _FakeProc()

    monkeypatch.setattr(safe.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(sys, "argv", ["resume_sensitivity_analysis_safe.py", "--run-id", run_id])

    exit_code = safe.main()

    assert exit_code == 0
    assert recorded["cmd"][1].endswith("run_sensitivity_analysis.py")
    assert "--resume-run-id" in recorded["cmd"]
    assert "--run-id" in recorded["cmd"]
    assert recorded["cwd"] == str(repo_root)
    assert recorded["env"]["PYTHONUNBUFFERED"] == "1"
    assert (run_outputs / run_id / "resume.pid").read_text(encoding="utf-8").strip() == "98765"


def test_main_waits_for_active_child_before_launching(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "sensitivity-runs"
    log_root = repo_root / "logs"
    run_id = "sensitivity_20260609_140911"
    manifest_path = run_outputs / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "parameters": {
                    "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
                    "scenario_ids": ["all-default"],
                    "dynamic_max_tracks": 1200,
                    "memory_budget_gb": 6.0,
                    "child_max_points_per_shard": 1500,
                    "min_points_per_shard": 512,
                    "continue_on_error": True,
                    "fail_on_unsupported": False,
                },
                "scenarios": [
                    {
                        "scenario_id": "all-default",
                        "status": "running",
                        "child_status": "running",
                        "child_manifest_path": None,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(safe, "REPO_ROOT", repo_root)
    monkeypatch.setattr(safe, "RUN_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(safe, "LOGS_DIR", log_root)
    monkeypatch.setattr(safe, "_find_parent_pids", lambda run_id: [])

    child_pid_sequence = iter([[12345], []])

    def _fake_find_child_pids(scenario_id, scenario_pack):
        return next(child_pid_sequence)

    monkeypatch.setattr(safe, "_find_child_pids", _fake_find_child_pids)

    sleep_calls: list[float] = []
    monkeypatch.setattr(safe.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    recorded: dict[str, object] = {}

    class _FakeProc:
        pid = 98765

    def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, start_new_session=None, env=None):
        recorded["cmd"] = cmd
        recorded["cwd"] = cwd
        recorded["env"] = env
        return _FakeProc()

    monkeypatch.setattr(safe.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(sys, "argv", ["resume_sensitivity_analysis_safe.py", "--run-id", run_id])

    exit_code = safe.main()

    assert exit_code == 0
    assert sleep_calls
    assert recorded["cmd"][1].endswith("run_sensitivity_analysis.py")
    assert (run_outputs / run_id / "resume.pid").read_text(encoding="utf-8").strip() == "98765"
