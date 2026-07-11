from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts.run_complete_analysis import (  # noqa: E402
    _build_fresh_frontend_resume_command,
    _completed_frontend_journal_min_mtime_epoch,
    _infer_resume_max_points_per_shard,
    _infer_resume_dynamic_hazard_point_cap,
    _resolve_resume_runtime_parameters,
    _should_exec_fresh_frontend_resume,
    ENV_FRESH_FRONTEND_RESUME,
)
from scripts import resume_complete_analysis_safe  # noqa: E402


def test_infer_resume_max_points_per_shard_prefers_pre_resume_completed_shards() -> None:
    manifest = {
        "resumed_at": "2026-06-10T06:00:00+00:00",
        "territories": {
            "guadeloupe": {
                "impacts": {
                    "hazards": {
                        "storm": {
                            "components": {
                                "wind": {
                                    "shards": {
                                        "hazard-0001": {
                                            "status": "complete",
                                            "point_count": 1500,
                                            "updated_at": "2026-06-09T16:41:31+00:00",
                                        },
                                        "hazard-0002": {
                                            "status": "complete",
                                            "point_count": 479,
                                            "updated_at": "2026-06-10T06:01:00+00:00",
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    assert _infer_resume_max_points_per_shard(manifest) == 1500


def test_resolve_resume_runtime_parameters_uses_manifest_values_for_resume() -> None:
    args = SimpleNamespace(
        dynamic_max_tracks=0,
        memory_budget_gb=6.0,
        max_points_per_shard=479,
        min_points_per_shard=512,
        territories="gua",
    )
    existing_manifest = {
        "resumed_at": "2026-06-10T06:00:00+00:00",
        "parameters": {
            "dynamic_max_tracks": 0,
            "requested_dynamic_max_tracks": 0,
            "memory_budget_gb": 6.0,
            "max_points_per_shard": 1500,
            "min_points_per_shard": 512,
            "territories": ["guadeloupe"],
        },
        "territories": {},
    }

    resolved, warnings = _resolve_resume_runtime_parameters(
        args=args,
        existing_manifest=existing_manifest,
        scenario=None,
    )

    assert resolved["max_points_per_shard"] == 1500
    assert resolved["memory_budget_gb"] == 6.0
    assert resolved["territories"] == ["guadeloupe"]
    assert warnings
    assert "max_points_per_shard" in warnings[0]


def test_infer_resume_dynamic_hazard_point_cap_uses_completed_shards() -> None:
    class _DummyManifest:
        def __init__(self) -> None:
            self.data = {
                "territories": {
                    "guadeloupe": {
                        "impacts": {
                            "hazards": {
                                "storm": {
                                    "components": {
                                        "wind": {
                                            "shards": {
                                                "hazard-0001": {
                                                    "status": "complete",
                                                    "point_count": 636,
                                                },
                                                "hazard-0002": {
                                                    "status": "running",
                                                    "point_count": 615,
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

    assert _infer_resume_dynamic_hazard_point_cap(_DummyManifest(), "guadeloupe") == 636


def test_resolve_resume_runtime_parameters_supports_all_selector() -> None:
    args = SimpleNamespace(
        dynamic_max_tracks=1500,
        memory_budget_gb=6.0,
        max_points_per_shard=0,
        min_points_per_shard=512,
        territories="all",
    )

    resolved, warnings = _resolve_resume_runtime_parameters(
        args=args,
        existing_manifest=None,
        scenario=None,
    )

    assert resolved["territories"] == [
        "guadeloupe",
        "martinique",
        "saint-barthelemy",
    ]
    assert warnings == []


def test_resume_launcher_uses_manifest_dynamic_tracks(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "complete-analysis-runs"
    log_root = repo_root / "logs"
    run_id = "20260710_194300"
    manifest_path = run_outputs / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "failed",
                "parameters": {
                    "dynamic_max_tracks": 100,
                    "requested_dynamic_max_tracks": 100,
                    "memory_budget_gb": 6.0,
                    "max_points_per_shard": 15000,
                },
                "territories": {
                    "guadeloupe": {
                        "impacts": {
                            "hazards": {
                                "storm": {
                                    "components": {
                                        "wind": {
                                            "shards": {
                                                "hazard-0001": {
                                                    "status": "complete",
                                                    "point_count": 15000,
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(resume_complete_analysis_safe, "REPO_ROOT", repo_root)
    monkeypatch.setattr(resume_complete_analysis_safe, "RUNNER", repo_root / "scripts" / "run_complete_analysis.py")
    monkeypatch.setattr(resume_complete_analysis_safe, "PYTHON", repo_root / "backend" / ".venv" / "bin" / "python")
    monkeypatch.setattr(resume_complete_analysis_safe, "RUN_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(resume_complete_analysis_safe, "LOGS_DIR", log_root)
    monkeypatch.setattr(resume_complete_analysis_safe, "_find_live_pids", lambda run_id: [])

    recorded: dict[str, object] = {}

    class _FakeProc:
        pid = 98765

    def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, start_new_session=None, env=None):
        recorded["cmd"] = list(cmd)
        recorded["cwd"] = cwd
        recorded["env"] = dict(env or {})
        return _FakeProc()

    monkeypatch.setattr(resume_complete_analysis_safe.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(sys, "argv", ["resume_complete_analysis_safe.py", "--run-id", run_id])

    exit_code = resume_complete_analysis_safe.main()

    assert exit_code == 0
    cmd = recorded["cmd"]
    assert cmd[cmd.index("--dynamic-max-tracks") + 1] == "100"
    assert cmd[cmd.index("--max-points-per-shard") + 1] == "15000"
    assert recorded["cwd"] == str(repo_root)
    assert recorded["env"]["PYTHONUNBUFFERED"] == "1"


def test_fresh_frontend_resume_command_preserves_run_parameters() -> None:
    args = SimpleNamespace(
        territories="gua",
        no_deploy=True,
        require_legacy_web=False,
        abort_on_sighup=True,
    )
    resolved_args = {
        "requested_dynamic_max_tracks": 100,
        "memory_budget_gb": 6.0,
        "min_points_per_shard": 512,
        "track_sample_manifest": "/tmp/sample_0100/manifest.json",
    }
    effective_settings = SimpleNamespace(climada_max_points_per_shard=15000)

    command = _build_fresh_frontend_resume_command(
        args=args,
        resolved_args=resolved_args,
        effective_settings=effective_settings,
        run_id="20260710_194300",
    )

    assert command[command.index("--resume-run-id") + 1] == "20260710_194300"
    assert command[command.index("--dynamic-max-tracks") + 1] == "100"
    assert command[command.index("--max-points-per-shard") + 1] == "15000"
    assert command[command.index("--track-sample-manifest") + 1] == "/tmp/sample_0100/manifest.json"
    assert "--no-deploy" in command
    assert "--abort-on-sighup" in command


def test_fresh_frontend_resume_guard_allows_resume_once(monkeypatch) -> None:
    monkeypatch.delenv(ENV_FRESH_FRONTEND_RESUME, raising=False)
    assert _should_exec_fresh_frontend_resume(
        calculation_complete=True,
        frontend_required=True,
        territories_for_frontend=["guadeloupe"],
    )

    monkeypatch.setenv(ENV_FRESH_FRONTEND_RESUME, "1")
    assert not _should_exec_fresh_frontend_resume(
        calculation_complete=True,
        frontend_required=True,
        territories_for_frontend=["guadeloupe"],
    )


def test_completed_frontend_journal_min_mtime_epoch_detects_child_completed(tmp_path: Path) -> None:
    journal_path = tmp_path / "frontend-supervision.jsonl"
    journal_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-11T06:15:56+00:00",
                        "actor": "parent",
                        "event": "frontend_phase_started",
                        "run_id": "20260710_204310",
                        "territories": ["guadeloupe"],
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-11T06:28:32+00:00",
                        "actor": "child",
                        "event": "child_completed",
                        "complete_analysis_run_id": "20260710_204310",
                        "territories": ["guadeloupe"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    min_mtime = _completed_frontend_journal_min_mtime_epoch(
        journal_path,
        run_id="20260710_204310",
        territories=["guadeloupe"],
    )

    assert min_mtime is not None
    assert min_mtime < datetime(2026, 7, 11, 6, 15, 56, tzinfo=timezone.utc).timestamp()


def test_completed_frontend_journal_ignores_child_failed(tmp_path: Path) -> None:
    journal_path = tmp_path / "frontend-supervision.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-11T06:28:32+00:00",
                "actor": "child",
                "event": "child_failed",
                "complete_analysis_run_id": "20260710_204310",
                "territories": ["guadeloupe"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        _completed_frontend_journal_min_mtime_epoch(
            journal_path,
            run_id="20260710_204310",
            territories=["guadeloupe"],
        )
        is None
    )
