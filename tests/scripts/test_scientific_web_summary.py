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
    network_states_path = tmp_path / "network-states.geojson"
    page_analysis_path = tmp_path / "page-analysis.json"
    out_path = tmp_path / "summary.json"
    complete_path.write_text(json.dumps(complete_payload), encoding="utf-8")
    network_states_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "feature_id": "AEP_001",
                            "layer_key": "eau_aep",
                            "service_feature_id": "AEP_001",
                            "zone_component_key": "AEP_001",
                            "state_annual_storm": "S1",
                            "state_rp50_storm": "S2",
                            "state_rp100_storm": "S3",
                            "state_p99_storm": "S3",
                            "state_annual_storm_cmcc": "S2",
                            "state_rp50_storm_cmcc": "S2",
                            "state_rp100_storm_cmcc": "S3",
                            "state_p99_storm_cmcc": "S3",
                        },
                        "geometry": {"type": "Point", "coordinates": [-61.5, 16.2]},
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "feature_id": "cell-+16.20_-61.60",
                            "layer_key": "elec_grid_0p1deg",
                            "state_annual_storm": "S0",
                            "state_rp50_storm": "S1",
                            "state_rp100_storm": "S2",
                            "state_p99_storm": "S3",
                            "state_annual_storm_cmcc": "S1",
                            "state_rp50_storm_cmcc": "S1",
                            "state_rp100_storm_cmcc": "S2",
                            "state_p99_storm_cmcc": "S3",
                        },
                        "geometry": {"type": "Point", "coordinates": [-61.6, 16.2]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    page_analysis_path.write_text(
        json.dumps(
            {
                "impact": {
                    "component_order": ["wind", "rain", "surge", "landslide"],
                    "summary_metrics": {
                        "storm": {
                            "eai_total_eur": 10.0,
                            "rp50_total_loss_eur": 50.0,
                            "rp100_total_loss_eur": 100.0,
                            "p99_total_loss_eur": 150.0,
                        },
                        "storm_cmcc": {
                            "eai_total_eur": 12.0,
                            "rp50_total_loss_eur": 55.0,
                            "rp100_total_loss_eur": 110.0,
                            "p99_total_loss_eur": 160.0,
                        },
                    },
                    "state_damage_tables": {
                        "annual": [{"class_key": "eau_aep", "storm": {"damage_eur": 10.0}, "storm_cmcc": {"damage_eur": 20.0}}],
                        "rp50": [{"class_key": "eau_aep", "storm": {"damage_eur": 50.0}, "storm_cmcc": {"damage_eur": 55.0}}],
                        "rp100": [{"class_key": "eau_aep", "storm": {"damage_eur": 100.0}, "storm_cmcc": {"damage_eur": 110.0}}],
                        "p99": [{"class_key": "eau_aep", "storm": {"damage_eur": 150.0}, "storm_cmcc": {"damage_eur": 160.0}}],
                    },
                    "damage_breakdown_by_scenario": {
                        "annual": {"storm": [], "storm_cmcc": []},
                        "rp50": {"storm": [], "storm_cmcc": []},
                        "rp100": {"storm": [], "storm_cmcc": []},
                        "p99": {"storm": [], "storm_cmcc": []},
                    },
                    "map_defaults": {"hazard": "storm", "scenario": "p99"},
                }
            }
        ),
        encoding="utf-8",
    )

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=complete_path,
        out_path=out_path,
        network_states_geojson_path=network_states_path,
        page_analysis_path=page_analysis_path,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["meta"]["scientific_source"] is True
    assert payload["meta"]["schema_version"] == "scientific_web_summary_v2"
    assert payload["meta"]["contract_version"] == "scientific_web_contract_v2"
    assert payload["portfolio_summary"]["storm"]["annual_eur"] == 10.0
    assert payload["portfolio_summary"]["storm_cmcc"]["p99_eur"] == 160.0
    assert payload["frontend"]["impact"]["summary_metrics"]["storm"]["rp100_total_loss_eur"] == 100.0
    assert payload["network_damage_tables"]["annual"][0]["class_key"] == "eau_aep"
    assert payload["network_damage_tables"]["annual"][0]["storm"]["damage_eur"] == 10.0
    assert payload["network_states"]["scenario_service_state_distribution"]["annual"]["storm"]["water_aep"]["S1"] == 1
    assert payload["network_states"]["scenario_service_state_distribution"]["p99"]["storm"]["elec"]["S3"] == 1
    assert payload["network_states"]["scenario_availability"] == {
        "annual": True,
        "rp50": True,
        "rp100": True,
        "p99": True,
    }
    assert payload["social_impact"]["scenario_summary"]["annual"]["storm"]["total_population_affected_any_network"] >= 0.0
