from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.monitor_sensitivity_run import _print_child_territory_progress, _snapshot_key


def test_print_child_territory_progress_shows_hazard_and_shard_counts(capsys) -> None:
    child_manifest = {
        "territories": {
            "guadeloupe": {
                "status": "running",
                "phases": {
                    "load_exposure": {"status": "complete", "asset_count": 1234},
                    "disaggregation": {"status": "complete", "point_count": 5678},
                    "impacts": {"status": "running"},
                },
                "impacts": {
                    "hazards": {
                        "storm": {
                            "components": {
                                "wind": {"status": "running", "planned_shards": 23, "completed_shards": 7},
                                "rain": {"status": "running", "planned_shards": 23, "completed_shards": 7},
                                "surge": {"status": "running", "planned_shards": 23, "completed_shards": 7},
                            }
                        },
                        "storm_cmcc": {
                            "components": {
                                "wind": {"status": "running", "planned_shards": 19, "completed_shards": 5},
                                "rain": {"status": "running", "planned_shards": 19, "completed_shards": 5},
                                "surge": {"status": "running", "planned_shards": 19, "completed_shards": 5},
                            }
                        },
                    }
                },
            }
        }
    }

    _print_child_territory_progress(child_manifest)
    captured = capsys.readouterr().out

    assert "Territory guadeloupe: running" in captured
    assert "Phases: load_exposure=complete | assets=1234" in captured
    assert "disaggregation=complete | points=5678" in captured
    assert "storm: wind=running | shards=7/23" in captured
    assert "storm_cmcc: wind=running | shards=5/19" in captured


def test_snapshot_key_changes_when_child_manifest_progresses(tmp_path: Path) -> None:
    child_manifest_path = tmp_path / "child-manifest.json"
    child_manifest_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-02T12:00:00+00:00",
                "status": "running",
                "latest_event": {
                    "timestamp": "2026-06-02T12:00:00+00:00",
                    "event": "shard_complete",
                    "territory": "guadeloupe",
                    "hazard": "storm",
                    "component": "wind",
                    "completed_shards": 1,
                    "planned_shards": 83,
                },
                "territories": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "run_id": "sensitivity_1",
        "status": "running",
        "updated_at": "2026-06-02T12:00:01+00:00",
        "latest_event": {"timestamp": "2026-06-02T12:00:01+00:00", "event": "scenario_started"},
        "scenarios": [
            {
                "scenario_id": "all-default",
                "status": "running",
                "child_status": "running",
                "child_manifest_path": str(child_manifest_path),
            }
        ],
    }

    first = _snapshot_key(manifest)
    child_manifest_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-02T12:05:00+00:00",
                "status": "running",
                "latest_event": {
                    "timestamp": "2026-06-02T12:05:00+00:00",
                    "event": "shard_complete",
                    "territory": "guadeloupe",
                    "hazard": "storm",
                    "component": "wind",
                    "completed_shards": 2,
                    "planned_shards": 83,
                },
                "territories": {},
            }
        ),
        encoding="utf-8",
    )

    second = _snapshot_key(manifest)

    assert first != second
