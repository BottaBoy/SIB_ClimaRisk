from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
BACKEND_ROOT = REPO_ROOT / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.generate_sensitivity_graphs import add_baseline_deltas, build_quality_report


def test_add_baseline_deltas_uses_service_and_network_metric_for_network_states() -> None:
    df = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.0,
            },
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "outage_pct",
                "value": 10.0,
            },
            {
                "scenario_id": "scenario-a",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 55.0,
            },
            {
                "scenario_id": "scenario-a",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "outage_pct",
                "value": 15.0,
            },
        ]
    )

    merged = add_baseline_deltas(df)
    non_nominal = merged[
        (merged["scenario_id"] == "scenario-a")
        & (merged["network_metric"] == "non_nominal_pct")
    ].iloc[0]
    outage = merged[
        (merged["scenario_id"] == "scenario-a")
        & (merged["network_metric"] == "outage_pct")
    ].iloc[0]

    assert non_nominal["baseline_value"] == 40.0
    assert non_nominal["delta_abs"] == 15.0
    assert outage["baseline_value"] == 10.0
    assert outage["delta_abs"] == 5.0


def test_build_quality_report_flags_duplicate_network_state_baselines() -> None:
    df = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.0,
                "baseline_value": 40.0,
                "delta_abs": 0.0,
                "parameter_key": None,
            },
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 41.0,
                "baseline_value": 41.0,
                "delta_abs": 0.0,
                "parameter_key": None,
            },
        ]
    )

    report = build_quality_report(df)

    assert report["status"] == "failed"
    duplicate_check = next(item for item in report["checks"] if item["check"] == "baseline_uniqueness::network_state_pct")
    assert duplicate_check["status"] == "failed"
    assert duplicate_check["duplicate_key_count"] == 1
