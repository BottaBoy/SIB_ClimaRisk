from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import journal_guamar_run, run_web_artifacts
from scripts.scientific_publication_contract import (
    EVENT_SELECTION_BASIS,
    SCIENTIFIC_SCENARIOS,
    SCIENTIFIC_WEB_CONTRACT_VERSION,
    SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
)


def test_publication_policy_requires_1500_tracks() -> None:
    policy = run_web_artifacts.publication_policy_for_requested_tracks(1499)

    assert policy == {
        "eligible": False,
        "requested_dynamic_max_tracks": 1499,
        "min_dynamic_max_tracks": 1500,
        "reason": "requested_dynamic_max_tracks=1499 is below the publication-safe minimum 1500",
    }

    assert run_web_artifacts.publication_policy_for_requested_tracks(1500)["eligible"] is True


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _complete_analysis_payload(*, updated_at: str) -> dict:
    state_tables = _state_damage_tables_payload()
    breakdowns = _damage_breakdowns_payload()
    return {
        "updated_at": updated_at,
        "meta": {
            "network_state_methodology": {
                "schema_version": "aggregated_service_state_v1",
                "aggregation_method": "aggregated_service_state",
                "electric_state_unit": "fixed_grid_0p1deg",
                "water_state_unit": "zone_component_key",
            },
            "network_state_methodology_breaks_comparability": True,
            "network_state_payload_contract": {
                "native_service_states_key": "native_service_states",
                "population_projected_service_states_key": "population_projected_service_states",
                "population_projected_service_states_coverage_key": "population_projected_service_states_coverage",
            },
        },
        "portfolio_results": {
            "storm": {
                "eai_eur": 10.0,
                "pml_10_eur": 10.0,
                "pml_50_eur": 50.0,
                "pml_100_eur": 100.0,
                "pml_1000_eur": 150.0,
                "percentile_99_loss_eur": 150.0,
            },
            "storm_cmcc": {
                "eai_eur": 12.0,
                "pml_10_eur": 12.0,
                "pml_50_eur": 55.0,
                "pml_100_eur": 110.0,
                "pml_1000_eur": 160.0,
                "percentile_99_loss_eur": 160.0,
            },
        },
        "scientific_graph_inputs": {
            "source_of_truth": "complete_analysis",
            "event_selection_basis": EVENT_SELECTION_BASIS,
            "scenarios": list(SCIENTIFIC_SCENARIOS),
            "state_damage_tables": state_tables,
            "damage_breakdown_by_scenario": breakdowns,
            "social_impact_by_scenario": {
                scenario: {
                    "storm": {"total_population_affected_any_network": 10.0},
                    "storm_cmcc": {"total_population_affected_any_network": 12.0},
                }
                for scenario in SCIENTIFIC_SCENARIOS
            },
            "scenario_availability": {
                scenario: {
                    "state_damage_tables": True,
                    "damage_breakdown_by_scenario": True,
                    "social_impact_by_scenario": True,
                    "network_states": True,
                }
                for scenario in SCIENTIFIC_SCENARIOS
            },
        },
    }


def _network_states_payload(*, metadata: dict | None = None) -> dict:
    features = [
        {
            "type": "Feature",
            "properties": {
                "feature_id": "AEP_001",
                "layer_key": "eau_aep",
                "service_feature_id": "AEP_001",
                "zone_component_key": "AEP_001",
                "state_rp10_storm": "S1",
                "state_rp50_storm": "S2",
                "state_rp100_storm": "S3",
                "state_rp1000_storm": "S3",
                "state_rp10_storm_cmcc": "S2",
                "state_rp50_storm_cmcc": "S2",
                "state_rp100_storm_cmcc": "S3",
                "state_rp1000_storm_cmcc": "S3",
            },
            "geometry": {"type": "Point", "coordinates": [-61.5, 16.2]},
        },
        {
            "type": "Feature",
            "properties": {
                "feature_id": "EU_001",
                "layer_key": "eau_eu",
                "service_feature_id": "EU_001",
                "zone_component_key": "EU_001",
                "state_rp10_storm": "S0",
                "state_rp50_storm": "S1",
                "state_rp100_storm": "S2",
                "state_rp1000_storm": "S3",
                "state_rp10_storm_cmcc": "S1",
                "state_rp50_storm_cmcc": "S2",
                "state_rp100_storm_cmcc": "S2",
                "state_rp1000_storm_cmcc": "S3",
            },
            "geometry": {"type": "Point", "coordinates": [-61.4, 16.3]},
        },
        {
            "type": "Feature",
            "properties": {
                "feature_id": "cell-+16.20_-61.60",
                "layer_key": "elec_grid_0p1deg",
                "service_feature_id": "",
                "zone_component_key": "",
                "state_rp10_storm": "S0",
                "state_rp50_storm": "S1",
                "state_rp100_storm": "S2",
                "state_rp1000_storm": "S3",
                "state_rp10_storm_cmcc": "S1",
                "state_rp50_storm_cmcc": "S1",
                "state_rp100_storm_cmcc": "S2",
                "state_rp1000_storm_cmcc": "S3",
            },
            "geometry": {"type": "Point", "coordinates": [-61.6, 16.2]},
        },
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "state_geometry_mode": "hydraulic_zoning_v2",
            "water_state_geometry_mode": "hydraulic_zoning_v2",
            "water_service_unit": "zone_component_key",
            "electric_state_geometry_mode": "fixed_grid_0p1deg",
            "schema_version": "aggregated_service_state_v1",
            "aggregation_method": "aggregated_service_state",
            "electric_state_unit": "fixed_grid_0p1deg",
            "water_state_unit": "zone_component_key",
            "geometry_semantics": "native_service_geometry",
            "methodology_breaks_comparability": True,
            **(metadata or {}),
        },
    }


def _water_infra_payload() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [],
    }


def _proxy_payload(*, case_study_run_id: str, complete_analysis_run_id: str, frozen_breakdown_shares: bool = False) -> dict:
    annual_shares = {"eau_aep": 0.9, "elec_bt_aerien": 0.1}
    rp50_shares = annual_shares if frozen_breakdown_shares else {"eau_aep": 0.7, "elec_bt_aerien": 0.3}
    rp100_shares = annual_shares if frozen_breakdown_shares else {"eau_aep": 0.6, "elec_bt_aerien": 0.4}
    scenario_payload = {
        "annual": {
            "component_ratios": {"wind": 0.9, "rain": 0.1, "surge": 0.0, "landslide": 0.0},
            "breakdown_shares": annual_shares,
        },
        "rp50": {
            "component_ratios": {"wind": 0.4, "rain": 0.3, "surge": 0.2, "landslide": 0.1},
            "breakdown_shares": rp50_shares,
        },
        "rp100": {
            "component_ratios": {"wind": 0.2, "rain": 0.4, "surge": 0.2, "landslide": 0.2},
            "breakdown_shares": rp100_shares,
        },
    }
    return {
        "meta": {
            "generated_at": "2026-05-11T18:03:00+00:00",
            "case_study_run_id": case_study_run_id,
            "publication_trace": {
                "artifact_kind": "multi_hazard_proxy",
                "source_mode": "lightweight_sampled_climada_proxy",
                "fallback_active": False,
                "complete_analysis_run_id": complete_analysis_run_id,
                "complete_analysis_generated_at": "2026-05-11T18:01:45+00:00",
            },
        },
        "hazards": {
            "storm": {"scenarios": dict(scenario_payload)},
            "storm_cmcc": {"scenarios": dict(scenario_payload)},
        },
    }


def _state_damage_tables_payload(*, storm_rp100: float = 100.0) -> dict:
    return {
        "rp10": [
            {
                "class_key": "eau_aep",
                "class_label": "Reseau eau AEP",
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 100.0, "S2": 0.0, "S3": 0.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 10.0,
                    "direct_damage_eur": 8.0,
                    "indirect_damage_eur": 2.0,
                    "damage_components_eur": {"wind": 10.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 12.0,
                    "direct_damage_eur": 9.0,
                    "indirect_damage_eur": 3.0,
                    "damage_components_eur": {"wind": 12.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
            }
        ],
        "rp50": [
            {
                "class_key": "eau_aep",
                "class_label": "Reseau eau AEP",
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 50.0,
                    "direct_damage_eur": 40.0,
                    "indirect_damage_eur": 10.0,
                    "damage_components_eur": {"wind": 50.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 55.0,
                    "direct_damage_eur": 45.0,
                    "indirect_damage_eur": 10.0,
                    "damage_components_eur": {"wind": 55.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
            }
        ],
        "rp100": [
            {
                "class_key": "eau_aep",
                "class_label": "Reseau eau AEP",
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 100.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": storm_rp100,
                    "direct_damage_eur": 80.0,
                    "indirect_damage_eur": max(storm_rp100 - 80.0, 0.0),
                    "damage_components_eur": {"wind": storm_rp100, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 110.0,
                    "direct_damage_eur": 90.0,
                    "indirect_damage_eur": 20.0,
                    "damage_components_eur": {"wind": 110.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
            }
        ],
        "rp1000": [
            {
                "class_key": "eau_aep",
                "class_label": "Reseau eau AEP",
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 100.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 150.0,
                    "direct_damage_eur": 120.0,
                    "indirect_damage_eur": 30.0,
                    "damage_components_eur": {"wind": 150.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 100.0},
                    "exposure_eur": 1000.0,
                    "damage_eur": 160.0,
                    "direct_damage_eur": 130.0,
                    "indirect_damage_eur": 30.0,
                    "damage_components_eur": {"wind": 160.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                },
            }
        ],
    }


def _damage_breakdowns_payload(*, storm_rp100: float = 100.0) -> dict:
    def _row(storm_damage: float, storm_cmcc_damage: float) -> dict:
        return {
            "storm": [
                {
                    "class_key": "eau_aep",
                    "class_label": "Reseau eau AEP",
                    "exposure_eur": 1000.0,
                    "damage_eur": storm_damage,
                    "direct_damage_eur": max(storm_damage - 10.0, 0.0),
                    "indirect_damage_eur": min(10.0, storm_damage),
                    "damage_components_eur": {"wind": storm_damage, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                }
            ],
            "storm_cmcc": [
                {
                    "class_key": "eau_aep",
                    "class_label": "Reseau eau AEP",
                    "exposure_eur": 1000.0,
                    "damage_eur": storm_cmcc_damage,
                    "direct_damage_eur": max(storm_cmcc_damage - 10.0, 0.0),
                    "indirect_damage_eur": min(10.0, storm_cmcc_damage),
                    "damage_components_eur": {"wind": storm_cmcc_damage, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                }
            ],
        }

    return {
        "rp10": _row(10.0, 12.0),
        "rp50": _row(50.0, 55.0),
        "rp100": _row(storm_rp100, 110.0),
        "rp1000": _row(150.0, 160.0),
    }


def _page_payload(
    *,
    case_study_run_id: str,
    complete_analysis_run_id: str,
    mismatch_rp100: bool = False,
) -> dict:
    storm_rp100 = 99.0 if mismatch_rp100 else 100.0
    state_tables = _state_damage_tables_payload(storm_rp100=storm_rp100)
    breakdowns = _damage_breakdowns_payload(storm_rp100=storm_rp100)
    return {
        "meta": {
            "generated_at": "2026-05-11T18:04:00+00:00",
            "case_study_run_id": case_study_run_id,
            "publication_trace": {
                "artifact_kind": "case_study_page_analysis",
                "source_mode": "case_study_page_analysis",
                "fallback_active": False,
                "complete_analysis_run_id": complete_analysis_run_id,
                "complete_analysis_generated_at": "2026-05-11T18:01:45+00:00",
                "wind_map_run_id": case_study_run_id,
                "wind_map_generated_at": "2026-05-11T18:02:00+00:00",
                "multi_hazard_proxy_run_id": case_study_run_id,
                "multi_hazard_proxy_fallback_active": False,
                "multi_hazard_proxy_source_mode": "lightweight_sampled_climada_proxy",
                "multi_hazard_proxy_fallback_reason": None,
            },
        },
        "impact": {
            "summary_metrics": {
                "storm": {
                    "eai_total_eur": 10.0,
                    "rp50_total_loss_eur": 50.0,
                    "rp100_total_loss_eur": storm_rp100,
                    "p99_total_loss_eur": 150.0,
                },
                "storm_cmcc": {
                    "eai_total_eur": 12.0,
                    "rp50_total_loss_eur": 55.0,
                    "rp100_total_loss_eur": 110.0,
                    "p99_total_loss_eur": 160.0,
                },
            },
            "state_damage_tables": state_tables,
            "damage_breakdown_by_scenario": breakdowns,
            "component_order": ["wind", "rain", "surge", "landslide"],
            "map_defaults": {"hazard": "storm", "scenario": "p99"},
        },
    }


def _scientific_web_summary_payload(*, run_id: str, territory: str = "guadeloupe", mismatch_rp100: bool = False) -> dict:
    storm_rp100 = 99.0 if mismatch_rp100 else 100.0
    state_tables = _state_damage_tables_payload(storm_rp100=storm_rp100)
    breakdowns = _damage_breakdowns_payload(storm_rp100=storm_rp100)
    scientific_graph_inputs = {
        "source_of_truth": "complete_analysis",
        "event_selection_basis": EVENT_SELECTION_BASIS,
        "scenarios": list(SCIENTIFIC_SCENARIOS),
        "state_damage_tables": state_tables,
        "damage_breakdown_by_scenario": breakdowns,
        "social_impact_by_scenario": {
            scenario: {
                "storm": {"total_population_affected_any_network": 10.0},
                "storm_cmcc": {"total_population_affected_any_network": 12.0},
            }
            for scenario in SCIENTIFIC_SCENARIOS
        },
        "scenario_availability": {
            scenario: {
                "state_damage_tables": True,
                "damage_breakdown_by_scenario": True,
                "social_impact_by_scenario": True,
                "network_states": True,
            }
            for scenario in SCIENTIFIC_SCENARIOS
        },
    }
    return {
        "meta": {
            "territory": territory,
            "run_id": run_id,
            "generated_at": "2026-05-11T18:04:30+00:00",
            "dynamic_max_tracks": 1500,
            "scientific_source": True,
            "schema_version": SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
            "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
            "source_of_truth": "scientific_web_summary",
            "aggregation_unit": "scientific_service_unit",
        },
        "portfolio_summary": {
            "storm": {
                "rp10_eur": 10.0,
                "rp50_eur": 50.0,
                "rp100_eur": 100.0,
                "rp1000_eur": 150.0,
            },
            "storm_cmcc": {
                "rp10_eur": 12.0,
                "rp50_eur": 55.0,
                "rp100_eur": 110.0,
                "rp1000_eur": 160.0,
            },
        },
        "network_states": {
            "scenario_service_state_distribution": {
                "rp10": {
                    "storm": {
                        "eau_aep": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                        "eau_eu": {"S0": 1, "S1": 0, "S2": 0, "S3": 0, "total_units": 1},
                        "elec": {"S0": 1, "S1": 0, "S2": 0, "S3": 0, "total_units": 1},
                    },
                    "storm_cmcc": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                        "elec": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                    },
                },
                "rp50": {
                    "storm": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                        "elec": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                    },
                    "storm_cmcc": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "elec": {"S0": 0, "S1": 1, "S2": 0, "S3": 0, "total_units": 1},
                    },
                },
                "rp100": {
                    "storm": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "elec": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                    },
                    "storm_cmcc": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                        "elec": {"S0": 0, "S1": 0, "S2": 1, "S3": 0, "total_units": 1},
                    },
                },
                "rp1000": {
                    "storm": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "elec": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                    },
                    "storm_cmcc": {
                        "eau_aep": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "eau_eu": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                        "elec": {"S0": 0, "S1": 0, "S2": 0, "S3": 1, "total_units": 1},
                    },
                },
            },
            "scenario_availability": {"rp10": True, "rp50": True, "rp100": True, "rp1000": True},
        },
        "scientific_graph_inputs": scientific_graph_inputs,
        "frontend": {
            "impact": {
                "summary_metrics": {
                    "storm": {
                        "rp10_total_loss_eur": 10.0,
                        "rp50_total_loss_eur": 50.0,
                        "rp100_total_loss_eur": storm_rp100,
                        "rp1000_total_loss_eur": 150.0,
                    },
                    "storm_cmcc": {
                        "rp10_total_loss_eur": 12.0,
                        "rp50_total_loss_eur": 55.0,
                        "rp100_total_loss_eur": 110.0,
                        "rp1000_total_loss_eur": 160.0,
                    },
                },
                "state_damage_tables": state_tables,
                "damage_breakdown_by_scenario": breakdowns,
            },
            "scenario_availability": {
                "rp10": {"damage_tables": True, "social_impact": True, "network_states": True},
                "rp50": {"damage_tables": True, "social_impact": True, "network_states": True},
                "rp100": {"damage_tables": True, "social_impact": True, "network_states": True},
                "rp1000": {"damage_tables": True, "social_impact": True, "network_states": True},
            },
        },
    }


def _vulnerability_curve_payload(*, component: str, case_study_run_id: str = "guadeloupe_case_20260511T180200Z") -> dict:
    return {
        "meta": {
            "generated_at": "2026-05-11T18:03:00+00:00",
            "schema_version": "vulnerability_curve_artifact_v1",
            "hazard_component": component,
            "artifact_kind": "vulnerability_curves",
            "case_study_run_id": case_study_run_id,
        },
        "profile": f"test_{component}_profile",
        "haz_type": component.upper(),
        "hazard_component": component,
        "intensity_unit": "unit",
        "curves": [
            {
                "impf_id": 1,
                "code": f"{component.upper()}_1",
                "name": f"{component} curve",
                "source": "test",
                "geography": "test",
                "sib_asset_types": ["elec_bt_aerien"],
                "intensity": [0.0, 1.0],
                "mdd": [0.0, 1.0],
                "paa": [1.0, 1.0],
            }
        ],
    }


def _landslide_payload(*, case_study_run_id: str) -> dict:
    return {
        "meta": {
            "generated_at": "2026-05-11T18:02:30+00:00",
            "case_study_run_id": case_study_run_id,
        }
    }


def _write_publication_ready_fixture(
    *,
    tmp_path: Path,
    run_id: str,
    frozen_breakdown_shares: bool = False,
    mismatch_rp100: bool = False,
) -> tuple[Path, Path]:
    outputs_dir = tmp_path / "outputs" / "complete-analysis-runs"
    run_dir = outputs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "territories": {
                "guadeloupe": {
                    "status": "complete",
                    "phases": {
                        "export": {"updated_at": "2026-05-11T18:01:45+00:00"},
                    },
                }
            },
        },
    )

    web_dir = tmp_path / "web"
    data_dir = web_dir / "data"
    case_study_run_id = "guadeloupe_case_20260511T180200Z"
    _write_json(
        data_dir / "guadeloupe-complete-analysis.json",
        _complete_analysis_payload(updated_at="2026-05-11T18:01:45+00:00"),
    )
    _write_json(
        data_dir / "guadeloupe-wind-maps.json",
        {
            "meta": {
                "generated_at": "2026-05-11T18:02:00+00:00",
                "case_study_run_id": case_study_run_id,
            }
        },
    )
    _write_json(
        data_dir / "guadeloupe-landslide-maps.json",
        _landslide_payload(case_study_run_id=case_study_run_id),
    )
    _write_json(
        data_dir / "guadeloupe-multi-hazard-proxy.json",
        _proxy_payload(
            case_study_run_id=case_study_run_id,
            complete_analysis_run_id=run_id,
            frozen_breakdown_shares=frozen_breakdown_shares,
        ),
    )
    _write_json(
        data_dir / "guadeloupe-page1-analysis.json",
        _page_payload(
            case_study_run_id=case_study_run_id,
            complete_analysis_run_id=run_id,
            mismatch_rp100=mismatch_rp100,
        ),
    )
    _write_json(
        data_dir / "guadeloupe-scientific-web-summary.json",
        _scientific_web_summary_payload(run_id=run_id, mismatch_rp100=mismatch_rp100),
    )
    for component in ("wind", "rain", "surge", "landslide"):
        _write_json(
            data_dir / f"vulnerability-curves-{component}.json",
            _vulnerability_curve_payload(component=component, case_study_run_id=case_study_run_id),
        )
    _write_json(data_dir / "guadeloupe-water-infra.geojson", _water_infra_payload())
    _write_json(data_dir / "guadeloupe-network-states.geojson", _network_states_payload())
    return outputs_dir, web_dir


def test_validate_territory_web_snapshot_rejects_fallback_publication(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260506_065034"
    outputs_dir = tmp_path / "outputs" / "complete-analysis-runs"
    run_dir = outputs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "territories": {
                "guadeloupe": {
                    "status": "complete",
                    "phases": {
                        "export": {"updated_at": "2026-05-06T10:00:00+00:00"},
                    },
                }
            },
        },
    )

    web_dir = tmp_path / "web"
    data_dir = web_dir / "data"
    _write_json(
        data_dir / "guadeloupe-complete-analysis.json",
        _complete_analysis_payload(updated_at="2026-05-06T10:00:00+00:00"),
    )
    _write_json(
        data_dir / "guadeloupe-wind-maps.json",
        {
            "meta": {
                "generated_at": "2026-05-06T10:10:00+00:00",
                "case_study_run_id": "guadeloupe_case_20260506T101000Z",
            }
        },
    )
    _write_json(
        data_dir / "guadeloupe-landslide-maps.json",
        _landslide_payload(case_study_run_id="guadeloupe_case_20260506T101000Z"),
    )
    _write_json(
        data_dir / "guadeloupe-multi-hazard-proxy.json",
        {
            "meta": {
                "generated_at": "2026-05-06T10:11:00+00:00",
                "case_study_run_id": "guadeloupe_case_20260506T101000Z",
                "publication_trace": {
                    "artifact_kind": "multi_hazard_proxy",
                    "source_mode": "lightweight_sampled_climada_proxy",
                    "fallback_active": True,
                },
            }
        },
    )
    _write_json(
        data_dir / "guadeloupe-page1-analysis.json",
        {
            "meta": {
                "generated_at": "2026-05-06T10:12:00+00:00",
                "case_study_run_id": "guadeloupe_case_20260506T101000Z",
                "publication_trace": {
                    "artifact_kind": "page_analysis",
                    "source_mode": "case_study_page_analysis",
                    "multi_hazard_proxy_source_mode": "lightweight_sampled_climada_proxy",
                    "multi_hazard_proxy_fallback_active": True,
                },
            }
        },
    )
    _write_json(
        data_dir / "guadeloupe-scientific-web-summary.json",
        _scientific_web_summary_payload(run_id=run_id),
    )
    for component in ("wind", "rain", "surge", "landslide"):
        _write_json(
            data_dir / f"vulnerability-curves-{component}.json",
            _vulnerability_curve_payload(component=component, case_study_run_id="guadeloupe_case_20260506T101000Z"),
        )
    _write_json(data_dir / "guadeloupe-water-infra.geojson", _water_infra_payload())
    _write_json(data_dir / "guadeloupe-network-states.geojson", _network_states_payload())

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="fallback publication is forbidden"):
        run_web_artifacts.validate_territory_web_snapshot(
            run_id,
            "guadeloupe",
            source_web_dir=web_dir,
        )


def test_validate_territory_web_snapshot_rejects_public_loss_total_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
        mismatch_rp100=True,
    )

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="scientific web summary must republish"):
        run_web_artifacts.validate_territory_web_snapshot(
            run_id,
            "guadeloupe",
            source_web_dir=web_dir,
        )


def test_validate_territory_web_snapshot_rejects_network_states_without_hydraulic_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
    )
    _write_json(
        web_dir / "data" / "guadeloupe-network-states.geojson",
        {
            "type": "FeatureCollection",
            "features": [],
        },
    )

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="missing hydraulic network-state metadata"):
        run_web_artifacts.validate_territory_web_snapshot(
            run_id,
            "guadeloupe",
            source_web_dir=web_dir,
        )


def test_validate_territory_web_snapshot_ignores_legacy_proxy_breakdown_shares(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
        frozen_breakdown_shares=True,
    )

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    validation = run_web_artifacts.validate_territory_web_snapshot(
        run_id,
        "guadeloupe",
        source_web_dir=web_dir,
    )
    assert "proxy_breakdown_share_validation" not in validation


def test_validate_territory_web_snapshot_accepts_aligned_publication_fixture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
    )

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    validation = run_web_artifacts.validate_territory_web_snapshot(
        run_id,
        "guadeloupe",
        source_web_dir=web_dir,
    )

    assert validation["geojson_contract"]["data/guadeloupe-network-states.geojson"]["water_service_unit"] == "zone_component_key"
    assert validation["geojson_contract"]["data/guadeloupe-network-states.geojson"]["schema_version"] == "aggregated_service_state_v1"
    assert validation["complete_analysis_contract"]["aggregation_method"] == "aggregated_service_state"
    assert validation["complete_analysis_contract"]["population_projected_service_states_key"] == "population_projected_service_states"
    assert validation["scientific_web_summary_alignment"]["hazards"]["storm"]["rp10_eur"] == pytest.approx(10.0)
    assert validation["scientific_web_summary_alignment"]["hazards"]["storm_cmcc"]["rp1000_eur"] == pytest.approx(160.0)
    assert validation["scientific_web_summary_alignment"]["network_states"]["rp100"]["storm"]["eau_aep"]["total_units"] == 1
    assert validation["scientific_web_summary_alignment"]["scientific_graph_inputs"]["rp10"]["table_rows"] == 1


def test_validate_territory_web_snapshot_rejects_scientific_summary_network_state_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
    )
    summary_path = web_dir / "data" / "guadeloupe-scientific-web-summary.json"
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_payload["network_states"]["scenario_service_state_distribution"]["rp100"]["storm"]["eau_aep"]["S3"] = 0
    summary_payload["network_states"]["scenario_service_state_distribution"]["rp100"]["storm"]["eau_aep"]["S2"] = 1
    _write_json(summary_path, summary_payload)

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="scientific summary network-state mismatch"):
        run_web_artifacts.validate_territory_web_snapshot(
            run_id,
            "guadeloupe",
            source_web_dir=web_dir,
        )


def test_extract_run_entry_keeps_wind_map_track_count_when_page_meta_mentions_fallback() -> None:
    track_blob = journal_guamar_run.encode_track_ids(["track-1", "track-2"])

    row = journal_guamar_run._extract_run_entry(
        territory="guadeloupe",
        hazard_key="storm",
        wind_meta={
            "generated_at": "2026-04-21T12:41:05+00:00",
            "dynamic_max_tracks": 300,
            "track_journal": {
                "storm": {
                    "track_ids_compressed": track_blob,
                    "n_events": 2,
                    "event_frequency_sum": 0.25,
                }
            },
        },
        page_meta={
            "generated_at": "2026-04-21T12:41:06+00:00",
            "case_study_run_id": "guadeloupe_case_20260421T124106Z",
            "sampling_spacing_m": 1000.0,
            "component_light_rerun": {"max_points_total": 400, "max_points_per_feature": 4},
            "modeling": {"fallback": True},
            "complete_analysis_source": {
                "run_id": "20260421_091134",
                "generated_at": "2026-04-21T10:39:56+00:00",
                "dynamic_max_tracks": {"storm": 1500, "storm_cmcc": 1500},
            },
        },
        proxy_meta={"max_points_total": 600, "max_points_per_feature": 6},
        impact_summary={"storm": {"rp50_total_loss_eur": 123.0, "rp100_total_loss_eur": 456.0}},
    )

    assert row["dynamic_max_tracks"] == 300
    assert row["wind_map_dynamic_max_tracks"] == 300
    assert row["source_dynamic_max_tracks"] == 1500
    assert row["complete_analysis_run_id"] == "20260421_091134"
    assert row["track_ids_count"] == 2


def test_repair_manifest_status_after_frontend_snapshot_promotes_complete_run() -> None:
    manifest = {
        "status": "partial",
        "current_phase": "cleanup",
        "reconcile_reason": "process_missing_during_cleanup",
        "territories": {
            "guadeloupe": {"status": "complete"},
            "martinique": {"status": "complete"},
        },
        "frontend_artifacts": {
            "status": "complete",
            "territories": ["guadeloupe", "martinique"],
        },
    }

    run_web_artifacts._repair_manifest_status_after_frontend_snapshot(
        manifest,
        "2026-05-12T07:17:17+00:00",
    )

    assert manifest["status"] == "success"
    assert manifest["current_phase"] is None
    assert manifest["territories_completed"] == 2
    assert manifest["frontend_artifacts_success"] is True
    assert manifest["reconciled_at"] == "2026-05-12T07:17:17+00:00"
    assert "reconcile_reason" not in manifest


def test_snapshot_run_web_artifacts_clears_stale_frontend_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
    )
    manifest_path = outputs_dir / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend_artifacts"] = {
        "status": "failed",
        "territories": ["guadeloupe"],
        "error": "stale frontend failure",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    run_web_artifacts.snapshot_run_web_artifacts(
        run_id,
        ["guadeloupe"],
        source_web_dir=web_dir,
    )

    repaired_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frontend_artifacts = repaired_manifest["frontend_artifacts"]
    assert frontend_artifacts["status"] == "complete"
    assert "error" not in frontend_artifacts


def test_build_staging_web_dir_rejects_low_track_run_for_publication(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260512_080434"
    outputs_dir = tmp_path / "outputs" / "complete-analysis-runs"
    run_dir = outputs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "parameters": {
                "requested_dynamic_max_tracks": 150,
                "dynamic_max_tracks": 150,
            },
            "territories": {
                "guadeloupe": {"status": "complete"},
            },
        },
    )

    web_dir = tmp_path / "web"
    web_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="not publication-eligible"):
        run_web_artifacts.build_staging_web_dir_from_run(run_id, base_web_dir=web_dir)


def test_build_staging_web_dir_revalidates_archived_snapshot(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260511_141135"
    outputs_dir, web_dir = _write_publication_ready_fixture(
        tmp_path=tmp_path,
        run_id=run_id,
        mismatch_rp100=True,
    )
    archive_root = outputs_dir / run_id / "territories" / "guadeloupe" / "web"
    for relative_path in run_web_artifacts.territory_run_generated_relative_paths("guadeloupe"):
        source_path = web_dir / relative_path
        if not source_path.exists():
            continue
        destination_path = archive_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(source_path.read_bytes())

    manifest_path = outputs_dir / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parameters"] = {
        "requested_dynamic_max_tracks": 1500,
        "dynamic_max_tracks": 1500,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(run_web_artifacts, "RUN_OUTPUTS_DIR", outputs_dir)

    with pytest.raises(RuntimeError, match="scientific web summary must republish"):
        run_web_artifacts.build_staging_web_dir_from_run(run_id, base_web_dir=web_dir)
