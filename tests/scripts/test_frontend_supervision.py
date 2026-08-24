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

from scripts import frontend_supervision


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_manifest(run_dir: Path, *, run_id: str, status: str = "running") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "status": status,
        "created_at": "2026-05-26T12:20:16Z",
        "updated_at": "2026-05-26T12:39:12Z",
        "manifest_path": str(run_dir / "manifest.json"),
        "territories": {
            "guadeloupe": {"status": "complete"},
            "martinique": {"status": "complete"},
        },
        "frontend_artifacts": {
            "status": "running",
            "territories": ["guadeloupe", "martinique"],
            "supervision_journal": str(run_dir / "frontend-supervision.jsonl"),
        },
    }
    manifest_path = run_dir / "manifest.json"
    latest_path = run_dir.parent / "latest-manifest.json"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    manifest_path.write_text(encoded, encoding="utf-8")
    latest_path.write_text(encoded, encoding="utf-8")
    return manifest_path


def test_monitor_records_missing_parent_and_child_without_terminal_events(tmp_path: Path) -> None:
    run_id = "20260511_141135"
    run_dir = tmp_path / "outputs" / "complete-analysis-runs" / run_id
    _write_manifest(run_dir, run_id=run_id)
    journal_path = run_dir / "frontend-supervision.jsonl"
    states = iter(
        [
            {101: True, 202: True},
            {101: False, 202: True},
            {101: False, 202: False},
        ]
    )
    current = {"value": next(states)}

    def fake_process_alive(pid: int, _start_ticks: int | None) -> bool:
        return bool(current["value"].get(pid, False))

    def fake_sleep(_seconds: float) -> None:
        try:
            current["value"] = next(states)
        except StopIteration:
            pass

    summary = frontend_supervision.monitor_frontend_processes(
        journal_path=journal_path,
        run_id=run_id,
        territories=["guadeloupe", "martinique"],
        parent_pid=101,
        parent_start_ticks=11,
        child_pid=202,
        child_start_ticks=22,
        poll_interval_seconds=0.0,
        max_wait_seconds=1.0,
        process_alive_fn=fake_process_alive,
        sleep_fn=fake_sleep,
    )

    events = _read_events(journal_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    latest_manifest = json.loads((run_dir.parent / "latest-manifest.json").read_text(encoding="utf-8"))

    assert any(event["event"] == "parent_process_missing" for event in events)
    assert any(event["event"] == "child_process_missing" for event in events)
    assert any(event["event"] == "manifest_reconciled" for event in events)
    assert summary["parent_missing_logged"] is True
    assert summary["child_missing_logged"] is True
    assert summary["parent_terminal_event_seen"] is False
    assert summary["child_terminal_event_seen"] is False
    assert summary["manifest_reconciled"] is True
    assert manifest["status"] == "partial"
    assert manifest["frontend_artifacts"]["status"] == "failed"
    assert manifest["frontend_artifacts_success"] is False
    assert latest_manifest["status"] == "partial"


def test_monitor_exits_cleanly_when_terminal_events_already_exist(tmp_path: Path) -> None:
    run_id = "20260511_141135"
    run_dir = tmp_path / "outputs" / "complete-analysis-runs" / run_id
    _write_manifest(run_dir, run_id=run_id)
    journal_path = run_dir / "frontend-supervision.jsonl"
    frontend_supervision.write_frontend_supervision_event(
        journal_path,
        actor="parent",
        event="frontend_rebuild_completed",
        run_id=run_id,
    )
    frontend_supervision.write_frontend_supervision_event(
        journal_path,
        actor="child",
        event="child_completed",
        run_id=run_id,
    )

    calls: list[int] = []

    def fake_process_alive(pid: int, _start_ticks: int | None) -> bool:
        calls.append(pid)
        return True

    summary = frontend_supervision.monitor_frontend_processes(
        journal_path=journal_path,
        run_id="20260511_141135",
        territories=["guadeloupe"],
        parent_pid=101,
        parent_start_ticks=11,
        child_pid=202,
        child_start_ticks=22,
        poll_interval_seconds=0.0,
        max_wait_seconds=0.0,
        process_alive_fn=fake_process_alive,
        sleep_fn=lambda _seconds: None,
    )

    events = _read_events(journal_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert not any(event["event"] == "parent_process_missing" for event in events)
    assert not any(event["event"] == "child_process_missing" for event in events)
    assert not any(event["event"] == "manifest_reconciled" for event in events)
    assert summary["parent_terminal_event_seen"] is True
    assert summary["child_terminal_event_seen"] is True
    assert summary["manifest_reconciled"] is False
    assert calls == []
    assert manifest["status"] == "running"