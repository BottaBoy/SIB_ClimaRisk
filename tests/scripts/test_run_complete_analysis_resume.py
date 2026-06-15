from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts.run_complete_analysis import (  # noqa: E402
    _infer_resume_max_points_per_shard,
    _infer_resume_dynamic_hazard_point_cap,
    _resolve_resume_runtime_parameters,
)


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
