from __future__ import annotations

from pathlib import Path
import sys
import types

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

shapely_module = types.ModuleType("shapely")
shapely_geometry_module = types.ModuleType("shapely.geometry")
shapely_geometry_module.box = lambda *args, **kwargs: None
shapely_module.geometry = shapely_geometry_module
sys.modules.setdefault("shapely", shapely_module)
sys.modules.setdefault("shapely.geometry", shapely_geometry_module)

from scripts import build_guadeloupe_page1_data


def test_extract_complete_analysis_public_loss_targets_maps_public_scenarios() -> None:
    payload = {
        "portfolio_results": {
            "storm": {
                "eai_eur": 12.5,
                "pml_50_eur": 40.0,
                "pml_100_eur": 60.0,
                "percentile_99_loss_eur": 80.0,
            }
        }
    }

    assert build_guadeloupe_page1_data._extract_complete_analysis_public_loss_targets(payload, "storm") == {
        "annual": 12.5,
        "rp50": 40.0,
        "rp100": 60.0,
        "event_max": 80.0,
    }


def test_calibrate_scenario_results_to_complete_analysis_hits_requested_totals() -> None:
    values = np.array([100.0, 100.0, 100.0], dtype=float)
    mask = np.array([True, True, True], dtype=bool)
    scenario_results = {
        "annual": {
            "total_loss": np.array([5.0, 10.0, 0.0], dtype=float),
            "direct_loss": np.array([4.0, 8.0, 0.0], dtype=float),
        },
        "rp50": {
            "total_loss": np.array([10.0, 20.0, 0.0], dtype=float),
            "direct_loss": np.array([8.0, 16.0, 0.0], dtype=float),
        },
        "rp100": {
            "total_loss": np.array([12.0, 30.0, 0.0], dtype=float),
            "direct_loss": np.array([10.0, 24.0, 0.0], dtype=float),
        },
        "event_max": {
            "total_loss": np.array([15.0, 35.0, 0.0], dtype=float),
            "direct_loss": np.array([12.0, 28.0, 0.0], dtype=float),
        },
    }

    applied = build_guadeloupe_page1_data._calibrate_scenario_results_to_complete_analysis(
        scenario_results,
        values=values,
        all_infra_mask=mask,
        target_totals={
            "annual": 30.0,
            "rp50": 45.0,
            "rp100": 70.0,
            "event_max": 90.0,
        },
    )

    assert applied["rp50"]["pre_calibration_total_eur"] == 30.0
    assert scenario_results["annual"]["total_loss"].sum() == pytest.approx(30.0)
    assert scenario_results["rp50"]["total_loss"].sum() == pytest.approx(45.0)
    assert scenario_results["rp100"]["total_loss"].sum() == pytest.approx(70.0)
    assert scenario_results["event_max"]["total_loss"].sum() == pytest.approx(90.0)
    assert np.all(scenario_results["event_max"]["direct_loss"] <= scenario_results["event_max"]["total_loss"])