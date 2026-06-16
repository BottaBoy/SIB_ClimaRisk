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

from scripts.build_scientific_web_summary import build_scientific_web_summary


def test_build_scientific_web_summary_publishes_canonical_portfolio_totals(tmp_path: Path) -> None:
    complete_payload = {
        "meta": {
            "run_id": "20260616_101010",
            "requested_dynamic_max_tracks": 1500,
        },
        "portfolio_results": {
            "storm": {
                "eai_eur": 10.0,
                "pml_50_eur": 50.0,
                "pml_100_eur": 100.0,
                "percentile_99_loss_eur": 150.0,
                "components_direct_eai_eur": {"wind": 8.0},
                "components_direct_percentile_99_loss_eur": {"wind": 120.0},
                "network_states_native": {"elec": {"cell-1": {"state": "S2"}}},
            },
            "storm_cmcc": {
                "eai_eur": 12.0,
                "pml_50_eur": 55.0,
                "pml_100_eur": 110.0,
                "percentile_99_loss_eur": 160.0,
                "components_direct_eai_eur": {"wind": 9.0},
                "components_direct_percentile_99_loss_eur": {"wind": 130.0},
            },
            "network_states_native": {
                "storm": {"elec": {"cell-1": {"state": "S2"}}},
                "storm_cmcc": {"elec": {"cell-1": {"state": "S3"}}},
            },
            "network_states_projected": {},
            "network_states_projected_coverage": {},
            "social_impact_summary": {
                "storm": {"total_population_affected_any_network": 25.0},
                "storm_cmcc": {"total_population_affected_any_network": 30.0},
            },
            "social_impact_population_state_distribution": {
                "storm": {"elec": {"S0": 5.0, "S1": 20.0}},
                "storm_cmcc": {"elec": {"S0": 2.0, "S3": 28.0}},
            },
        },
        "asset_results": [
            {
                "asset_type": "eau_aep_cana",
                "exposure_eur": 1000.0,
                "eai_storm_eur": 10.0,
                "eai_storm_direct_eur": 7.0,
                "eai_storm_indirect_eur": 3.0,
                "eai_cmcc_eur": 20.0,
                "eai_cmcc_direct_eur": 14.0,
                "eai_cmcc_indirect_eur": 6.0,
            },
            {
                "asset_type": "elec_bt_aerien",
                "exposure_eur": 2000.0,
                "eai_storm_eur": 5.0,
                "eai_storm_direct_eur": 5.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_cmcc_eur": 8.0,
                "eai_cmcc_direct_eur": 8.0,
                "eai_cmcc_indirect_eur": 0.0,
            },
        ],
    }
    complete_path = tmp_path / "complete.json"
    out_path = tmp_path / "summary.json"
    complete_path.write_text(json.dumps(complete_payload), encoding="utf-8")

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=complete_path,
        out_path=out_path,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["meta"]["scientific_source"] is True
    assert payload["portfolio_summary"]["storm"]["annual_eur"] == 10.0
    assert payload["portfolio_summary"]["storm_cmcc"]["p99_eur"] == 160.0
    assert payload["frontend"]["impact"]["summary_metrics"]["storm"]["rp100_total_loss_eur"] == 100.0
    assert payload["network_damage_tables"]["annual"][0]["class_key"] == "eau_aep"
    assert payload["network_damage_tables"]["annual"][0]["storm"]["damage_eur"] == 10.0
    assert payload["network_states"]["scenario_service_state_distribution"]["p99"]["storm"]["elec"]["S2"] == 1
    assert payload["social_impact"]["scenario_summary"]["p99"]["storm"]["total_population_affected_any_network"] == 25.0
