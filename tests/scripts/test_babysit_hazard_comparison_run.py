from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import babysit_hazard_comparison_run as babysit  # noqa: E402


def _make_state(
    *,
    status: str,
    process_alive: bool,
    age_seconds: float | None = 600.0,
) -> babysit.RunState:
    return babysit.RunState(
        run_id="20260611_075636",
        status=status,
        manifest_path=Path("/tmp/manifest.json"),
        pidfile_path=Path("/tmp/resume.pid"),
        updated_at=datetime.now(timezone.utc),
        age_seconds=age_seconds,
        latest_event={"event": "component_completed", "territory": "demo", "scenario": "storm", "component": "wind"},
        pidfile_pid=4321 if process_alive else None,
        pidfile_alive=process_alive,
        pgrep_pid=4321 if process_alive else None,
        pgrep_alive=process_alive,
    )


def test_should_restart_when_running_and_process_missing() -> None:
    state = _make_state(status="running", process_alive=False, age_seconds=90.0)

    should_restart, reason, kill_first = babysit._should_restart(state, stale_after_seconds=20 * 60)

    assert should_restart is True
    assert "process missing" in reason
    assert kill_first is False


def test_should_not_restart_when_complete() -> None:
    state = _make_state(status="complete", process_alive=False)

    should_restart, reason, kill_first = babysit._should_restart(state, stale_after_seconds=20 * 60)

    assert should_restart is False
    assert reason == "status=complete"
    assert kill_first is False


def test_launch_resume_uses_safe_launcher_and_parses_pid(monkeypatch, capsys) -> None:
    recorded: dict[str, object] = {}

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, check=None, env=None):
        recorded["cmd"] = cmd
        recorded["cwd"] = cwd
        recorded["env"] = env
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "run_id=20260611_075636\npid=98765\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(babysit.subprocess, "run", _fake_run)

    launched, pid = babysit._launch_resume("20260611_075636")

    assert launched is True
    assert pid == 98765
    assert recorded["cmd"][1].endswith("resume_hazard_comparison_safe.py")
    assert recorded["cmd"][-1] == "20260611_075636"
    assert recorded["cwd"] == str(babysit.REPO_ROOT)
    assert recorded["env"]["PYTHONUNBUFFERED"] == "1"
    captured = capsys.readouterr().out
    assert "launcher: run_id=20260611_075636" in captured
    assert "relaunch started pid=98765" in captured


def test_babysitter_restarts_and_then_exits_on_complete(monkeypatch, capsys) -> None:
    run_id = "20260611_075636"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:00:00+00:00",
            "event": "component_completed",
            "territory": "demo",
            "scenario": "storm",
            "component": "wind",
        },
        "parameters": {
            "dynamic_max_tracks": 1200,
            "territories": ["demo"],
            "scenarios": ["storm"],
        },
        "territories": {},
    }
    complete_manifest = {
        "run_id": run_id,
        "status": "complete",
        "updated_at": "2026-06-12T10:05:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:05:00+00:00",
            "event": "run_completed",
            "territory": "demo",
            "scenario": "storm",
            "component": "wind",
        },
        "parameters": {
            "dynamic_max_tracks": 1200,
            "territories": ["demo"],
            "scenarios": ["storm"],
        },
        "territories": {},
    }
    manifests = iter([running_manifest, complete_manifest])
    states = iter(
        [
            _make_state(status="running", process_alive=False, age_seconds=600.0),
            _make_state(status="complete", process_alive=False, age_seconds=600.0),
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

    sleeps: list[float] = []

    def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    exit_code = babysit.babysit_hazard_comparison_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=_fake_sleep,
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0
    assert launches == [run_id]
    output = capsys.readouterr().out
    assert "SIB Hazard Comparison Babysitter" in output
    assert "relaunch requested for" in output
    assert "relaunch issued for" in output
    assert "completed successfully; babysitter exiting" in output
