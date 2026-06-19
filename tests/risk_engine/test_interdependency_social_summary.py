from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.interdependency import aggregate_impacts_with_interdependency


def test_detailed_states_use_asset_type_to_split_water_aep_and_water_eu() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "aep-network",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_reseau",
                "asset_type": "eau_aep_cana",
            },
            {
                "feature_id": "eu-network",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_reseau",
                "asset_type": "eau_eu_cana",
            },
        ],
        hazard_direct_eai={"storm": [20.0, 40.0], "storm_cmcc": [0.0, 0.0]},
        hazard_max_loss={"storm": [20.0, 40.0], "storm_cmcc": [0.0, 0.0]},
    )

    states = aggregated.detailed_states_by_territory["storm"]["cell-1"]

    assert states["water_aep"] == "S2"
    assert states["water_eu"] == "S3"
    assert states["elec"] == "S0"

    cell_states = aggregated.cell_service_states_by_territory["storm"]["cell-1"]
    coverage = aggregated.cell_service_coverage_by_territory["storm"]["cell-1"]

    assert cell_states["water_aep"] == "S2"
    assert cell_states["water_eu"] == "S3"
    assert coverage["water_aep"] is True
    assert coverage["water_eu"] is True


def test_cell_service_states_use_aggregated_damage_ratio_not_worst_asset_state() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "elec-large",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 90.0,
                "infra_class": "elec_aerien",
                "asset_type": "elec_distribution",
            },
            {
                "feature_id": "elec-small",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 10.0,
                "infra_class": "elec_aerien",
                "asset_type": "elec_distribution",
            },
        ],
        hazard_direct_eai={"storm": [0.0, 10.0], "storm_cmcc": [0.0, 0.0]},
        hazard_max_loss={"storm": [0.0, 10.0], "storm_cmcc": [0.0, 0.0]},
    )

    legacy_states = aggregated.detailed_states_by_territory["storm"]["cell-1"]
    cell_states = aggregated.cell_service_states_by_territory["storm"]["cell-1"]
    coverage = aggregated.cell_service_coverage_by_territory["storm"]["cell-1"]

    assert legacy_states["elec"] == "S3"
    assert cell_states["elec"] == "S1"
    assert coverage["elec"] is True
    native_elec = aggregated.native_service_states_by_hazard["storm"]["elec"]["cell-1"]
    assert native_elec["degraded_share"] == 0.1
    assert native_elec["state"] == "S1"
    assert native_elec["state_basis"] == "aggregated_damage_ratio_on_fixed_grid_0p1deg"


def test_cell_service_water_coverage_tracks_service_presence_without_local_electricity() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "water-only",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_reseau",
                "asset_type": "eau_aep_cana",
            },
            {
                "feature_id": "remote-elec",
                "territory_id": "cell-2",
                "territory_label": "Cell 2",
                "value_eur": 100.0,
                "infra_class": "elec_aerien",
                "asset_type": "elec_distribution",
            },
        ],
        hazard_direct_eai={"storm": [0.0, 0.0], "storm_cmcc": [0.0, 0.0]},
        hazard_max_loss={"storm": [0.0, 0.0], "storm_cmcc": [0.0, 0.0]},
    )

    coverage = aggregated.cell_service_coverage_by_territory["storm"]["cell-1"]
    cell_states = aggregated.cell_service_states_by_territory["storm"]["cell-1"]

    assert coverage["water_aep"] is True
    assert cell_states["water_aep"] == "S0"


def test_electric_dependency_changes_water_state_without_adding_monetary_loss() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "elec-down",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "elec_aerien",
                "asset_type": "elec_distribution",
            },
            {
                "feature_id": "water-aep",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_reseau",
                "asset_type": "eau_aep_cana",
            },
        ],
        hazard_direct_eai={"storm": [100.0, 20.0], "storm_cmcc": [0.0, 0.0]},
        hazard_max_loss={"storm": [100.0, 20.0], "storm_cmcc": [0.0, 0.0]},
    )

    water_asset = next(row for row in aggregated.asset_results if row["asset_id"] == "water-aep")
    territory = next(row for row in aggregated.territory_results if row["territory_id"] == "cell-1")
    states = aggregated.detailed_states_by_territory["storm"]["cell-1"]

    assert states["water_aep"] == "S3"
    assert water_asset["eai_storm_direct_eur"] == 20.0
    assert water_asset["eai_storm_indirect_eur"] == 0.0
    assert water_asset["eai_storm_eur"] == 20.0
    assert territory["eai_storm_indirect_eur"] == 0.0
    assert aggregated.interdependency["electricity_to_water_enabled"] is True
    assert aggregated.interdependency["electricity_to_water_monetary_uplift_enabled"] is False
    assert aggregated.interdependency["uplift_by_state"] == {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}


def test_blocking_ouvrage_forces_linked_wastewater_network_state_without_adding_loss() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "step-1",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_ouvrage",
                "asset_type": "eau_eu_step",
                "service_feature_id": "EU_001__P1",
                "zone_component_key": "EU_001__P1",
                "feature_role": "step",
                "criticality": "essential",
            },
            {
                "feature_id": "eu-line-1",
                "territory_id": "cell-1",
                "territory_label": "Cell 1",
                "value_eur": 100.0,
                "infra_class": "eau_reseau",
                "asset_type": "eau_eu_cana",
                "service_feature_id": "EU_001__P1",
                "zone_component_key": "EU_001__P1",
                "feature_role": "canalisation",
            },
        ],
        hazard_direct_eai={"storm": [80.0, 0.0], "storm_cmcc": [0.0, 0.0]},
        hazard_max_loss={"storm": [20.0, 0.0], "storm_cmcc": [0.0, 0.0]},
    )

    eu_line = next(row for row in aggregated.asset_results if row["asset_id"] == "eu-line-1")
    cell_states = aggregated.cell_service_states_by_territory["storm"]["cell-1"]
    detailed_states = aggregated.detailed_states_by_territory["storm"]["cell-1"]

    assert eu_line["service_feature_id"] == "EU_001__P1"
    assert eu_line["feature_role"] == "canalisation"
    assert eu_line["eai_storm_direct_eur"] == 0.0
    assert eu_line["eai_storm_indirect_eur"] == 0.0
    assert eu_line["eai_storm_eur"] == 0.0
    assert detailed_states["water_eu"] == "S2"
    assert cell_states["water_eu"] == "S2"
    assert aggregated.interdependency["water_service_outage_enabled"] is True
    assert aggregated.interdependency["water_service_unit"] == "zone_component_key"
    native_eu = aggregated.native_service_states_by_hazard["storm"]["water_eu"]["EU_001__P1"]
    assert native_eu["state"] == "S2"
    assert native_eu["state_basis"].endswith("plus_blocking_asset")


def test_projected_states_use_fixed_0p1deg_electric_grid_and_publish_metadata() -> None:
    aggregated = aggregate_impacts_with_interdependency(
        point_records=[
            {
                "feature_id": "elec-grid-1",
                "territory_id": "cell-+16.20_-061.40",
                "territory_label": "Cell 1",
                "lat": 16.24,
                "lon": -61.44,
                "value_eur": 100.0,
                "infra_class": "elec_aerien",
                "asset_type": "elec_distribution",
            }
        ],
        hazard_direct_eai={"storm": [20.0], "storm_cmcc": [0.0]},
        hazard_max_loss={"storm": [20.0], "storm_cmcc": [0.0]},
    )

    native_elec = aggregated.native_service_states_by_hazard["storm"]["elec"]["cell-+16.20_-61.40"]
    projected_elec = aggregated.projected_service_states_by_territory["storm"]["cell-+16.20_-061.40"]
    projected_cov = aggregated.projected_service_coverage_by_territory["storm"]["cell-+16.20_-061.40"]

    assert native_elec["state"] == "S2"
    assert projected_elec["elec"] == "S2"
    assert projected_cov["elec"] is True
    assert aggregated.state_aggregation_metadata["electric_state_unit"] == "fixed_grid_0p1deg"
    assert aggregated.state_aggregation_metadata["aggregation_method"] == "aggregated_service_state"
