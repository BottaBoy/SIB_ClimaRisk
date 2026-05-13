from __future__ import annotations

from pathlib import Path
import pytest
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import case_study_proxy_utils


def test_normalize_proxy_scenario_loss_totals_enforces_monotonic_rp_order() -> None:
    normalized = case_study_proxy_utils._normalize_proxy_scenario_loss_totals(
        {
            "annual": 10.0,
            "rp50": 120.0,
            "rp100": 70.0,
            "event_max": 140.0,
            "top10": 30.0,
            "top5": 20.0,
        }
    )

    assert normalized["annual"] == 10.0
    assert normalized["rp50"] == 95.0
    assert normalized["rp100"] == 95.0
    assert normalized["event_max"] == 140.0
    assert normalized["annual"] <= normalized["rp50"] <= normalized["rp100"] <= normalized["event_max"]
    assert normalized["annual"] <= normalized["top10"] <= normalized["top5"] <= normalized["event_max"]


def test_scenario_breakdown_shares_follow_component_mix() -> None:
    point_records = [
        {"asset_type": "elec_bt_aerien"},
        {"asset_type": "eau_eu_cana"},
    ]
    shares = case_study_proxy_utils._scenario_breakdown_shares_from_component_arrays(
        point_records,
        {
            "wind": [90.0, 10.0],
            "landslide": [10.0, 90.0],
        },
        {"wind": 0.8, "rain": 0.0, "surge": 0.0, "landslide": 0.2},
    )

    assert shares["elec_bt_aerien"] == pytest.approx(0.74)
    assert shares["eau_eu"] == pytest.approx(0.26)