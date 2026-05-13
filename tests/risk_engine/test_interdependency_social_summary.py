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
    assert coverage["water_aep"] is False
    assert coverage["water_eu"] is False


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


def test_cell_service_water_coverage_requires_local_electricity() -> None:
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

    assert coverage["water_aep"] is False
    assert cell_states["water_aep"] == "S0"