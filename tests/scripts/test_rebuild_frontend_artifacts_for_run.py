from pathlib import Path
import json
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import rebuild_frontend_artifacts_for_run


def test_resolve_selected_run_id_supports_latest_success(monkeypatch, tmp_path) -> None:
    failed_manifest = tmp_path / "20260527_160919" / "manifest.json"
    success_manifest = tmp_path / "20260527_072457" / "manifest.json"
    failed_manifest.parent.mkdir(parents=True, exist_ok=True)
    success_manifest.parent.mkdir(parents=True, exist_ok=True)
    failed_manifest.write_text(json.dumps({"run_id": "20260527_160919", "status": "partial"}), encoding="utf-8")
    success_manifest.write_text(json.dumps({"run_id": "20260527_072457", "status": "success"}), encoding="utf-8")
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "RUN_OUTPUTS_DIR", tmp_path)

    resolved = rebuild_frontend_artifacts_for_run.resolve_selected_run_id("latest-success")

    assert resolved == "20260527_072457"


def test_main_rebuilds_and_snapshots_selected_run(monkeypatch, tmp_path) -> None:
    run_id = "20260527_160919"
    run_dir = tmp_path / run_id
    archived_path = (
        run_dir / "territories" / "guadeloupe" / "web" / "data" / "guadeloupe-complete-analysis.json"
    )
    archived_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.write_text(
        json.dumps({"hazard_dynamic_max_tracks_requested": 1500, "updated_at": "2026-06-16T15:52:29+00:00"}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "territories": {
                    "guadeloupe": {
                        "status": "complete",
                        "archived_complete_analysis_path": str(archived_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    subprocess_calls: list[dict[str, object]] = []
    snapshot_calls: list[dict[str, object]] = []
    web_data_dir = tmp_path / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    live_complete_path = web_data_dir / "guadeloupe-complete-analysis.json"
    live_complete_path.write_text(
        json.dumps({"hazard_dynamic_max_tracks_requested": 999, "updated_at": "2026-06-18T11:39:47+00:00"}),
        encoding="utf-8",
    )

    def _fake_subprocess_run(cmd, check, env):
        staged_payload = json.loads(live_complete_path.read_text(encoding="utf-8"))
        subprocess_calls.append({"cmd": list(cmd), "check": check, "env": dict(env)})
        assert staged_payload["hazard_dynamic_max_tracks_requested"] == 1500

    def _fake_snapshot_run_web_artifacts(resolved_run_id, territories):
        snapshot_calls.append(
            {"run_id": resolved_run_id, "territories": list(territories)}
        )

    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "RUN_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "WEB_DATA_DIR", web_data_dir)
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "resolve_run_id", lambda value: value)
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run.subprocess, "run", _fake_subprocess_run)
    monkeypatch.setattr(
        rebuild_frontend_artifacts_for_run,
        "snapshot_run_web_artifacts",
        _fake_snapshot_run_web_artifacts,
    )

    exit_code = rebuild_frontend_artifacts_for_run.main(["--run-id", run_id])

    assert exit_code == 0
    assert len(subprocess_calls) == 1
    env = subprocess_calls[0]["env"]
    assert env["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] == "1500"
    assert env[rebuild_frontend_artifacts_for_run.ENV_FRONTEND_SUPERVISION_RUN_ID] == run_id
    assert env[rebuild_frontend_artifacts_for_run.ENV_FRONTEND_SUPERVISION_JOURNAL] == str(
        run_dir / "frontend-supervision.jsonl"
    )
    cmd = subprocess_calls[0]["cmd"]
    assert "rerun_case_studies_light.py" in " ".join(str(part) for part in cmd)
    assert "--page-component-light-dynamic-max-tracks" in cmd
    assert "1500" in cmd
    assert snapshot_calls == [{"run_id": run_id, "territories": ["guadeloupe"]}]
    restored_payload = json.loads(live_complete_path.read_text(encoding="utf-8"))
    assert restored_payload["hazard_dynamic_max_tracks_requested"] == 999


def test_main_rejects_requested_territory_missing_from_selected_run(monkeypatch, tmp_path) -> None:
    run_id = "20260527_160919"
    run_dir = tmp_path / run_id
    archived_path = (
        run_dir / "territories" / "guadeloupe" / "web" / "data" / "guadeloupe-complete-analysis.json"
    )
    archived_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.write_text(
        json.dumps({"hazard_dynamic_max_tracks_requested": 1500}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "territories": {
                    "guadeloupe": {
                        "status": "complete",
                        "archived_complete_analysis_path": str(archived_path),
                    },
                    "martinique": {
                        "status": "failed",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "RUN_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "resolve_run_id", lambda value: value)

    with pytest.raises(RuntimeError, match="martinique"):
        rebuild_frontend_artifacts_for_run.main([
            "--run-id",
            run_id,
            "--territories",
            "guadeloupe",
            "martinique",
        ])


def test_staged_archived_complete_analysis_payloads_removes_staged_file_without_backup(
    monkeypatch,
    tmp_path,
) -> None:
    run_id = "20260527_160919"
    archived_path = (
        tmp_path / run_id / "territories" / "guadeloupe" / "web" / "data" / "guadeloupe-complete-analysis.json"
    )
    archived_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.write_text(
        json.dumps({"hazard_dynamic_max_tracks_requested": 1500}),
        encoding="utf-8",
    )
    manifest = {
        "run_id": run_id,
        "territories": {
            "guadeloupe": {
                "status": "complete",
                "archived_complete_analysis_path": str(archived_path),
            }
        },
    }
    web_data_dir = tmp_path / "web" / "data"
    monkeypatch.setattr(rebuild_frontend_artifacts_for_run, "WEB_DATA_DIR", web_data_dir)

    target_path = web_data_dir / "guadeloupe-complete-analysis.json"
    assert not target_path.exists()

    with rebuild_frontend_artifacts_for_run.staged_archived_complete_analysis_payloads(
        manifest,
        ["guadeloupe"],
    ):
        assert target_path.exists()

    assert not target_path.exists()
