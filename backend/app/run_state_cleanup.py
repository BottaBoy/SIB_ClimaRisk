from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
from typing import Any


UTC = timezone.utc


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _parse_timestamp(raw_value: Any) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _has_live_complete_analysis_process() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "run_complete_analysis.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _terminal_status_for_manifest(payload: dict[str, Any]) -> tuple[str, int]:
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    completed = 0
    for entry in territories.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status") or "") == "complete":
            completed += 1
    return ("partial" if completed else "failed"), completed


def _reconcile_territory_states(payload: dict[str, Any]) -> None:
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    finished_at = str(payload.get("finished_at") or "")
    for entry in territories.values():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "")
        if status == "complete":
            continue
        entry["status"] = "failed"
        entry["current_phase"] = None
        if finished_at and not entry.get("finished_at"):
            entry["finished_at"] = finished_at


def reconcile_stale_run_manifests(
    root_dir: Path,
    *,
    stale_after_minutes: int = 30,
    dry_run: bool = False,
    live_run_active: bool | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    root = Path(root_dir)
    if not root.exists():
        return []

    reference_now = now or datetime.now(UTC)
    stale_before = reference_now - timedelta(minutes=max(1, int(stale_after_minutes)))
    active = _has_live_complete_analysis_process() if live_run_active is None else bool(live_run_active)

    latest_manifest_path = root / "latest-manifest.json"
    latest_payload = _read_json(latest_manifest_path) if latest_manifest_path.exists() else {}
    latest_run_id = str(latest_payload.get("run_id") or "").strip()
    latest_status = str(latest_payload.get("status") or "").strip().lower()
    protected_run_id = latest_run_id if active and latest_status == "running" else ""

    reconciled: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        payload = _read_json(manifest_path)
        if str(payload.get("status") or "").strip().lower() != "running":
            continue

        run_id = str(payload.get("run_id") or manifest_path.parent.name).strip()
        if protected_run_id and run_id == protected_run_id:
            continue

        last_seen = _parse_timestamp(payload.get("updated_at")) or _parse_timestamp(payload.get("created_at"))
        if last_seen is None or last_seen > stale_before:
            continue

        terminal_status, completed_territories = _terminal_status_for_manifest(payload)
        finished_at = reference_now.replace(microsecond=0).isoformat()
        payload["status"] = terminal_status
        payload["finished_at"] = finished_at
        payload["reconciled_at"] = finished_at
        payload["reconcile_reason"] = "process_missing_during_cleanup"
        payload["territories_completed"] = completed_territories
        payload["current_phase"] = None
        latest_event = payload.get("latest_event") if isinstance(payload.get("latest_event"), dict) else None
        if latest_event is not None:
            latest_event["reconciled_at"] = finished_at
        _reconcile_territory_states(payload)

        reconciled.append(
            {
                "run_id": run_id,
                "manifest_path": str(manifest_path),
                "new_status": terminal_status,
                "completed_territories": completed_territories,
                "last_seen_at": last_seen.isoformat(),
            }
        )

        if dry_run:
            continue

        _write_json(manifest_path, payload)
        if latest_run_id and run_id == latest_run_id:
            _write_json(latest_manifest_path, payload)

    return reconciled


def backfill_missing_finished_at(
    root_dir: Path,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    root = Path(root_dir)
    if not root.exists():
        return []

    latest_manifest_path = root / "latest-manifest.json"
    latest_payload = _read_json(latest_manifest_path) if latest_manifest_path.exists() else {}
    latest_run_id = str(latest_payload.get("run_id") or "").strip()
    terminal_statuses = {"success", "partial", "failed", "aborted"}

    normalized: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        payload = _read_json(manifest_path)
        status = str(payload.get("status") or "").strip().lower()
        if status not in terminal_statuses or payload.get("finished_at"):
            continue

        run_id = str(payload.get("run_id") or manifest_path.parent.name).strip()
        finished_at = (
            _parse_timestamp(payload.get("updated_at"))
            or _parse_timestamp(payload.get("created_at"))
            or datetime.now(UTC)
        ).replace(microsecond=0).isoformat()
        payload["finished_at"] = finished_at

        normalized.append(
            {
                "run_id": run_id,
                "manifest_path": str(manifest_path),
                "status": status,
                "finished_at": finished_at,
            }
        )

        if dry_run:
            continue

        _write_json(manifest_path, payload)
        if latest_run_id and run_id == latest_run_id:
            _write_json(latest_manifest_path, payload)

    return normalized