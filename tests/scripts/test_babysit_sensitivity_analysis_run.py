from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import babysit_sensitivity_analysis_run as babysit  # noqa: E402


def _make_state(
    *,
    status: str,
    process_alive: bool,
    child_alive: bool = False,
    has_pending_work: bool = True,
    age_seconds: float | None = 600.0,
    child_scenario_id: str | None = "all-default",
) -> babysit.RunState:
    return babysit.RunState(
        run_id="sensitivity_20260609_140911",
        status=status,
        manifest_path=Path("/tmp/manifest.json"),
        pidfile_path=Path("/tmp/resume.pid"),
        updated_at=datetime.now(timezone.utc),
        age_seconds=age_seconds,
        latest_event={"event": "scenario_started"},
        pidfile_pid=4321 if process_alive else None,
        pidfile_alive=process_alive,
        pgrep_pid=4321 if process_alive else None,
        pgrep_alive=process_alive,
        has_pending_work=has_pending_work,
        child_scenario_id=child_scenario_id if child_alive else None,
        child_manifest_path=Path("/tmp/child-manifest.json") if child_alive else None,
        child_manifest_status="running" if child_alive else None,
        child_pid=8765 if child_alive else None,
        child_alive=child_alive,
    )


def test_babysitter_restarts_when_parent_dead_and_child_inactive(monkeypatch, capsys) -> None:
    run_id = "sensitivity_20260609_140911"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {"timestamp": "2026-06-12T10:00:00+00:00", "event": "scenario_started"},
        "parameters": {
            "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
            "scenario_ids": ["all-default"],
            "dynamic_max_tracks": 1200,
            "memory_budget_gb": 6.0,
            "child_max_points_per_shard": 1500,
            "min_points_per_shard": 512,
            "continue_on_error": False,
            "fail_on_unsupported": False,
        },
        "scenarios": [
            {
                "scenario_id": "all-default",
                "status": "running",
                "child_manifest_path": None,
                "child_status": None,
            }
        ],
    }
    success_manifest = {**running_manifest, "status": "success"}
    manifests = iter([running_manifest, success_manifest])
    states = iter(
        [
            _make_state(status="running", process_alive=False, child_alive=False, has_pending_work=True),
            _make_state(status="success", process_alive=False, child_alive=False, has_pending_work=False),
        ]
    )
    launches: list[str] = []

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (False, None))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: next(manifests))
    monkeypatch.setattr(babysit, "_inspect_run", lambda _run_id, manifest=None, now=None: next(states))
    monkeypatch.setattr(babysit, "_launch_resume", lambda restarted_run_id: launches.append(restarted_run_id) or (True, 2222))
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-12T10:00:00+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "10m 0s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: manifest["status"])
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)

    exit_code = babysit.babysit_sensitivity_analysis_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0
    assert launches == [run_id]
    output = capsys.readouterr().out
    assert "SIB Sensitivity Babysitter" in output
    assert "relaunch requested for" in output
    assert "relaunch issued for" in output
    assert "completed successfully; babysitter exiting" in output


def test_babysitter_waits_for_active_child_before_relaunching(monkeypatch) -> None:
    run_id = "sensitivity_20260609_140911"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {"timestamp": "2026-06-12T10:00:00+00:00", "event": "scenario_started"},
        "parameters": {
            "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
            "scenario_ids": ["all-default"],
            "dynamic_max_tracks": 1200,
            "memory_budget_gb": 6.0,
            "child_max_points_per_shard": 1500,
            "min_points_per_shard": 512,
            "continue_on_error": False,
            "fail_on_unsupported": False,
        },
        "scenarios": [
            {
                "scenario_id": "all-default",
                "status": "running",
                "child_manifest_path": "/tmp/child-manifest.json",
                "child_status": "running",
            }
        ],
    }
    success_manifest = {**running_manifest, "status": "success"}
    manifests = iter([running_manifest, running_manifest, success_manifest])
    child_cleared = {"value": False}
    state_calls = {"count": 0}

    def _fake_inspect(_run_id, manifest=None, now=None):
        state_calls["count"] += 1
        if state_calls["count"] == 1:
            return _make_state(
                status="running",
                process_alive=False,
                child_alive=True,
                has_pending_work=True,
            )
        child_cleared["value"] = True
        if state_calls["count"] == 2:
            return _make_state(
                status="running",
                process_alive=False,
                child_alive=False,
                has_pending_work=True,
            )
        return _make_state(
            status="success",
            process_alive=False,
            child_alive=False,
            has_pending_work=False,
        )

    def _fake_launch(restarted_run_id: str):
        assert child_cleared["value"] is True
        return True, 2222

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (False, None))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: next(manifests))
    monkeypatch.setattr(babysit, "_inspect_run", _fake_inspect)
    monkeypatch.setattr(babysit, "_launch_resume", _fake_launch)
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-12T10:00:00+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "10m 0s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: f"{manifest['status']}:{state.child_alive if state else False}")
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)

    sleeps: list[float] = []

    exit_code = babysit.babysit_sensitivity_analysis_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=lambda seconds: sleeps.append(seconds),
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0
    assert sleeps == []


def test_babysitter_exits_cleanly_on_success(monkeypatch) -> None:
    run_id = "sensitivity_20260609_140911"
    success_manifest = {
        "run_id": run_id,
        "status": "success",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {"timestamp": "2026-06-12T10:00:00+00:00", "event": "complete"},
        "parameters": {
            "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
            "scenario_ids": ["all-default"],
            "dynamic_max_tracks": 1200,
            "memory_budget_gb": 6.0,
            "child_max_points_per_shard": 1500,
            "min_points_per_shard": 512,
            "continue_on_error": False,
            "fail_on_unsupported": False,
        },
        "scenarios": [],
    }

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (False, None))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: success_manifest)
    monkeypatch.setattr(
        babysit,
        "_inspect_run",
        lambda _run_id, manifest=None, now=None: _make_state(
            status="success",
            process_alive=False,
            child_alive=False,
            has_pending_work=False,
        ),
    )
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-12T10:00:00+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "10m 0s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: manifest["status"])
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)
    monkeypatch.setattr(babysit, "_launch_resume", lambda restarted_run_id: (_ for _ in ()).throw(AssertionError("should not relaunch")))

    exit_code = babysit.babysit_sensitivity_analysis_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0


def test_babysitter_finalizes_when_parent_dead_and_no_scenarios_left(monkeypatch) -> None:
    run_id = "sensitivity_20260609_140911"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-15T08:46:37+00:00",
        "latest_event": {"timestamp": "2026-06-15T08:46:37+00:00", "event": "scenario_completed"},
        "parameters": {
            "scenario_pack": "/home/ubuntu/sib-work/config/sensitivity/default-scenario-pack.json",
            "scenario_ids": ["all-default"],
            "dynamic_max_tracks": 1200,
            "memory_budget_gb": 6.0,
            "child_max_points_per_shard": 1500,
            "min_points_per_shard": 512,
            "continue_on_error": False,
            "fail_on_unsupported": False,
        },
        "scenarios": [
            {
                "scenario_id": "all-default",
                "status": "complete",
                "child_manifest_path": None,
                "child_status": "success",
            }
        ],
    }
    states = iter([_make_state(status="running", process_alive=False, child_alive=False, has_pending_work=False)])
    launches: list[str] = []
    finalized: list[str] = []

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (False, None))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: running_manifest)
    monkeypatch.setattr(babysit, "_inspect_run", lambda _run_id, manifest=None, now=None: next(states))
    monkeypatch.setattr(babysit, "_launch_resume", lambda restarted_run_id: launches.append(restarted_run_id) or (True, 2222))
    monkeypatch.setattr(babysit, "_finalize_terminal_run", lambda finalized_run_id: finalized.append(finalized_run_id) or "success")
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-15T08:46:37+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "6h 59m 16s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: manifest["status"])
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)

    exit_code = babysit.babysit_sensitivity_analysis_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0
    assert launches == []
    assert finalized == [run_id]
