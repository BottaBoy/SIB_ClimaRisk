from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import babysit_complete_analysis_run as babysit  # noqa: E402


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
        latest_event={"event": "shard_complete"},
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


def test_should_restart_when_failed_and_process_absent() -> None:
    state = _make_state(status="failed", process_alive=False)

    should_restart, reason, kill_first = babysit._should_restart(state, stale_after_seconds=20 * 60)

    assert should_restart is True
    assert reason == "status=failed"
    assert kill_first is False


def test_should_restart_when_aborted_and_process_absent() -> None:
    state = _make_state(status="aborted", process_alive=False)

    should_restart, reason, kill_first = babysit._should_restart(state, stale_after_seconds=20 * 60)

    assert should_restart is True
    assert reason == "status=aborted"
    assert kill_first is False


def test_should_not_restart_when_success() -> None:
    state = _make_state(status="success", process_alive=False)

    should_restart, reason, kill_first = babysit._should_restart(state, stale_after_seconds=20 * 60)

    assert should_restart is False
    assert reason == "status=success"
    assert kill_first is False


def test_should_not_restart_when_running_and_process_alive() -> None:
    state = _make_state(status="running", process_alive=True, age_seconds=90.0)

    should_restart, reason, kill_first = babysit._should_restart(
        state,
        stale_after_seconds=20 * 60,
        silent_hang_after_seconds=30 * 60,
    )

    assert should_restart is False
    assert reason == "status=running"
    assert kill_first is False


def test_should_restart_when_running_and_process_alive_but_silent_too_long() -> None:
    state = _make_state(status="running", process_alive=True, age_seconds=31 * 60.0)

    should_restart, reason, kill_first = babysit._should_restart(
        state,
        stale_after_seconds=20 * 60,
        silent_hang_after_seconds=30 * 60,
    )

    assert should_restart is True
    assert "silent" in reason
    assert kill_first is True


def test_terminate_live_processes_tries_term_then_kill(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []

    monkeypatch.setattr(babysit, "_read_pidfile", lambda run_id: (Path("/tmp/resume.pid"), 4321))
    monkeypatch.setattr(babysit, "_find_pgrep_pids", lambda run_id: [4321, 6789])
    monkeypatch.setattr(babysit.time, "sleep", lambda _seconds: None)

    alive = {4321, 6789}

    def _fake_pid_is_alive(pid: int | None) -> bool:
        return pid in alive if pid is not None else False

    def _fake_kill(pid: int, signum: int) -> None:
        killed.append((pid, signum))
        if signum == babysit.signal.SIGTERM:
            alive.discard(pid)
        if signum == babysit.signal.SIGKILL:
            alive.discard(pid)

    monkeypatch.setattr(babysit, "_pid_is_alive", _fake_pid_is_alive)
    monkeypatch.setattr(babysit.os, "kill", _fake_kill)

    targets = babysit._terminate_live_processes("20260611_075636", grace_seconds=0.0)

    assert targets == [4321, 6789]
    assert (4321, babysit.signal.SIGTERM) in killed
    assert (6789, babysit.signal.SIGTERM) in killed


def test_find_pgrep_pids_parses_matching_processes(monkeypatch) -> None:
    class _Result:
        stdout = (
            "12345 /home/ubuntu/sib-work/backend/.venv/bin/python "
            "scripts/run_complete_analysis.py --resume-run-id 20260611_075636\n"
            "67890 /home/ubuntu/sib-work/backend/.venv/bin/python run_complete_analysis_20260611_075636.log\n"
            "54321 /home/ubuntu/sib-work/backend/.venv/bin/python scripts/run_complete_analysis.py --run-id 20260611_000000\n"
        )

    monkeypatch.setattr(babysit.subprocess, "run", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(babysit, "_pid_is_alive", lambda pid: pid in {12345, 67890})
    monkeypatch.setattr(
        babysit,
        "_read_process_cmdline",
        lambda pid: (
            ["/home/ubuntu/sib-work/backend/.venv/bin/python", "scripts/run_complete_analysis.py", "--resume-run-id", "20260611_075636"]
            if pid == 12345
            else ["/home/ubuntu/sib-work/backend/.venv/bin/python", "run_complete_analysis_20260611_075636.log"]
        ),
    )

    assert babysit._find_pgrep_pids("20260611_075636") == [12345]


def test_find_pgrep_pids_matches_normal_launch_from_manifest_created_at(monkeypatch) -> None:
    class _Result:
        stdout = (
            "12345 /home/ubuntu/sib-work/backend/.venv/bin/python "
            "scripts/run_complete_analysis.py --dynamic-max-tracks 1500 --memory-budget-gb 6\n"
            "54321 /home/ubuntu/sib-work/backend/.venv/bin/python "
            "scripts/run_complete_analysis.py --dynamic-max-tracks 1500 --memory-budget-gb 6\n"
        )

    manifest = {"created_at": "2026-06-11T07:56:36+00:00"}

    monkeypatch.setattr(babysit.subprocess, "run", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(babysit, "_pid_is_alive", lambda pid: pid in {12345, 54321})
    monkeypatch.setattr(
        babysit,
        "_read_process_cmdline",
        lambda pid: ["/home/ubuntu/sib-work/backend/.venv/bin/python", "scripts/run_complete_analysis.py", "--dynamic-max-tracks", "1500", "--memory-budget-gb", "6"],
    )
    monkeypatch.setattr(
        babysit,
        "_read_process_started_at",
        lambda pid: (
            datetime.fromisoformat("2026-06-11T07:56:35+00:00")
            if pid == 12345
            else datetime.fromisoformat("2026-06-11T08:20:00+00:00")
        ),
    )

    assert babysit._find_pgrep_pids("20260611_075636", manifest=manifest) == [12345]


def test_find_babysitter_pids_ignores_shell_wrappers(monkeypatch) -> None:
    class _Result:
        stdout = (
            "11111 timeout 8s /home/ubuntu/sib-work/backend/.venv/bin/python "
            "/home/ubuntu/sib-work/scripts/babysit_complete_analysis_run.py --run-id 20260611_075636\n"
            "22222 /home/ubuntu/sib-work/backend/.venv/bin/python "
            "/home/ubuntu/sib-work/scripts/babysit_complete_analysis_run.py --run-id 20260611_075636\n"
        )

    monkeypatch.setattr(babysit.subprocess, "run", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(babysit, "_pid_is_alive", lambda pid: pid in {11111, 22222})
    monkeypatch.setattr(
        babysit,
        "_read_process_cmdline",
        lambda pid: (
            ["timeout", "8s", "/home/ubuntu/sib-work/backend/.venv/bin/python", "/home/ubuntu/sib-work/scripts/babysit_complete_analysis_run.py", "--run-id", "20260611_075636"]
            if pid == 11111
            else ["/home/ubuntu/sib-work/backend/.venv/bin/python", "/home/ubuntu/sib-work/scripts/babysit_complete_analysis_run.py", "--run-id", "20260611_075636"]
        ),
    )

    assert babysit._find_babysitter_pids("20260611_075636") == [22222]


def test_take_babysitter_ownership_stops_previous_babysitter(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []
    written: dict[str, object] = {}
    alive = {2222}

    monkeypatch.setattr(babysit, "_read_babysitter_pidfile", lambda run_id: (Path("/tmp/babysitter.pid"), 2222))
    monkeypatch.setattr(babysit, "_find_babysitter_pids", lambda run_id: [2222])
    monkeypatch.setattr(babysit, "_pid_is_alive", lambda pid: pid in alive if pid is not None else False)
    monkeypatch.setattr(babysit.time, "sleep", lambda _seconds: None)

    def _fake_kill(pid: int, signum: int) -> None:
        killed.append((pid, signum))
        alive.discard(pid)

    def _fake_write(run_id: str, pid: int) -> Path:
        written["run_id"] = run_id
        written["pid"] = pid
        return Path("/tmp/babysitter.pid")

    monkeypatch.setattr(babysit.os, "kill", _fake_kill)
    monkeypatch.setattr(babysit, "_write_babysitter_pidfile", _fake_write)

    pidfile_path = babysit._take_babysitter_ownership("20260611_075636", 1111)

    assert pidfile_path == Path("/tmp/babysitter.pid")
    assert (2222, babysit.signal.SIGTERM) in killed
    assert written == {"run_id": "20260611_075636", "pid": 1111}


def test_babysitter_exits_when_superseded_by_new_owner(monkeypatch, capsys) -> None:
    run_id = "20260611_075636"
    manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {"timestamp": "2026-06-12T10:00:00+00:00", "event": "shard_start"},
        "parameters": {"dynamic_max_tracks": 0, "memory_budget_gb": 6.0, "max_points_per_shard": 577},
        "territories": {},
    }
    manifests = iter([manifest])
    states = iter([_make_state(status="running", process_alive=True, age_seconds=60.0)])
    superseded = iter([False, True])

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (next(superseded), 2222))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: next(manifests))
    monkeypatch.setattr(babysit, "_inspect_run", lambda _run_id, manifest=None, now=None: next(states))
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-12T10:00:00+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "1m 0s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: manifest["status"])
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)

    sleeps: list[float] = []
    monkeypatch.setattr(babysit.time, "sleep", lambda delay: sleeps.append(delay))

    exit_code = babysit.babysit_complete_analysis_run(
        run_id,
        poll_seconds=0.0,
        stale_after_minutes=20.0,
        silent_hang_after_minutes=30.0,
        restart_delay_seconds=0.0,
        sleep_fn=lambda delay: sleeps.append(delay),
        now_fn=lambda: datetime.now(timezone.utc),
    )

    assert exit_code == 0
    assert sleeps == []
    output = capsys.readouterr().out
    assert "superseded by pid=2222" in output


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
                "stdout": "run_id=20260611_075636\npid=98765\nmax_points_per_shard=577\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(babysit.subprocess, "run", _fake_run)

    launched, pid = babysit._launch_resume("20260611_075636")

    assert launched is True
    assert pid == 98765
    assert recorded["cmd"][1].endswith("resume_complete_analysis_safe.py")
    assert recorded["cmd"][-1] == "20260611_075636"
    assert recorded["cwd"] == str(babysit.REPO_ROOT)
    assert recorded["env"]["PYTHONUNBUFFERED"] == "1"
    captured = capsys.readouterr().out
    assert "launcher: run_id=20260611_075636" in captured
    assert "relaunch started pid=98765" in captured


def test_babysitter_restarts_and_then_exits_on_success(monkeypatch, capsys) -> None:
    run_id = "20260611_075636"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:00:00+00:00",
            "event": "shard_complete",
            "territory": "guadeloupe",
            "hazard": "storm",
            "component": "wind",
        },
        "parameters": {
            "dynamic_max_tracks": 0,
            "memory_budget_gb": 6.0,
            "max_points_per_shard": 577,
        },
        "territories": {},
    }
    success_manifest = {
        "run_id": run_id,
        "status": "success",
        "updated_at": "2026-06-12T10:05:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:05:00+00:00",
            "event": "complete",
            "territory": "guadeloupe",
            "hazard": "storm",
            "component": "wind",
        },
        "parameters": {
            "dynamic_max_tracks": 0,
            "memory_budget_gb": 6.0,
            "max_points_per_shard": 577,
        },
        "territories": {},
    }
    manifests = iter([running_manifest, success_manifest])
    states = iter(
        [
            _make_state(status="running", process_alive=False, age_seconds=600.0),
            _make_state(status="success", process_alive=False, age_seconds=600.0),
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

    exit_code = babysit.babysit_complete_analysis_run(
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
    assert "SIB Complete Analysis Babysitter" in output
    assert "relaunch requested for" in output
    assert "relaunch issued for" in output
    assert "completed successfully; babysitter exiting" in output


def test_babysitter_kills_silent_hang_before_relaunch(monkeypatch, capsys) -> None:
    run_id = "20260611_075636"
    running_manifest = {
        "run_id": run_id,
        "status": "running",
        "updated_at": "2026-06-12T10:00:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:00:00+00:00",
            "event": "shard_start",
            "territory": "guadeloupe",
            "hazard": "storm",
            "component": "rain",
        },
        "parameters": {
            "dynamic_max_tracks": 0,
            "memory_budget_gb": 6.0,
            "max_points_per_shard": 577,
        },
        "territories": {},
    }
    success_manifest = {
        "run_id": run_id,
        "status": "success",
        "updated_at": "2026-06-12T10:31:00+00:00",
        "latest_event": {
            "timestamp": "2026-06-12T10:31:00+00:00",
            "event": "complete",
            "territory": "guadeloupe",
            "hazard": "storm",
            "component": "rain",
        },
        "parameters": {
            "dynamic_max_tracks": 0,
            "memory_budget_gb": 6.0,
            "max_points_per_shard": 577,
        },
        "territories": {},
    }
    manifests = iter([running_manifest, success_manifest])
    states = iter(
        [
            _make_state(status="running", process_alive=True, age_seconds=31 * 60.0),
            _make_state(status="success", process_alive=False, age_seconds=31 * 60.0),
        ]
    )
    launches: list[str] = []
    terminations: list[str] = []

    monkeypatch.setattr(babysit, "_take_babysitter_ownership", lambda run_id, self_pid: Path("/tmp/babysitter.pid"))
    monkeypatch.setattr(babysit, "_is_superseded_babysitter", lambda run_id, self_pid: (False, None))
    monkeypatch.setattr(babysit, "_load_manifest", lambda _run_id: next(manifests))
    monkeypatch.setattr(babysit, "_inspect_run", lambda _run_id, manifest=None, now=None: next(states))
    monkeypatch.setattr(babysit, "_launch_resume", lambda restarted_run_id: launches.append(restarted_run_id) or (True, 2222))
    monkeypatch.setattr(babysit, "_human_ts", lambda moment=None: "2026-06-12T10:00:00+00:00")
    monkeypatch.setattr(babysit, "_human_duration", lambda seconds: "31m 0s")
    monkeypatch.setattr(babysit, "_snapshot_key", lambda manifest, state=None: manifest["status"])
    monkeypatch.setattr(babysit, "_print_detailed_status", lambda manifest, state: None)

    alive = {1111}

    def _fake_read_pidfile(run_id: str):
        return Path("/tmp/resume.pid"), 1111

    def _fake_find_pgrep_pids(run_id: str):
        return [1111]

    def _fake_pid_is_alive(pid: int | None) -> bool:
        return pid in alive if pid is not None else False

    def _fake_kill(pid: int, signum: int) -> None:
        killed.append((pid, signum))
        alive.discard(pid)

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(babysit, "_read_pidfile", _fake_read_pidfile)
    monkeypatch.setattr(babysit, "_find_pgrep_pids", _fake_find_pgrep_pids)
    monkeypatch.setattr(babysit, "_pid_is_alive", _fake_pid_is_alive)
    monkeypatch.setattr(babysit.os, "kill", _fake_kill)

    sleeps: list[float] = []

    def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    exit_code = babysit.babysit_complete_analysis_run(
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
    assert (1111, babysit.signal.SIGTERM) in killed
    output = capsys.readouterr().out
    assert "silent for" in output
    assert "terminating stale process set" in output
    assert "completed successfully; babysitter exiting" in output
