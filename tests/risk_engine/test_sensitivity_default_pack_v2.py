from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.risk_engine.sensitivity_scenarios import (
    apply_settings_overrides,
    list_scenarios_from_pack,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = REPO_ROOT / "config" / "sensitivity" / "default-scenario-pack-v2.json"

EXPECTED_SCENARIO_IDS = [
    "all-default",
    "vulnerability_curves_profile-elec-flood-moderate",
    "vulnerability_curves_profile-elec-flood-stress",
    "vulnerability_curves_profile-elec-wind-underground-exposed",
    "runoff_coeff-0-1",
    "runoff_coeff-0-5",
    "direct_state_thresholds-10-20-40",
    "direct_state_thresholds-10-15-50",
    "hazard_dynamic_max_tracks-50",
    "hazard_dynamic_max_tracks-100",
    "hazard_dynamic_max_tracks-800",
    "hazard_dynamic_max_tracks-5000",
    "territory_grid_deg-0-05",
    "territory_grid_deg-0-1",
]


def test_default_pack_v2_has_expected_supported_scenarios() -> None:
    scenarios = list_scenarios_from_pack(PACK_PATH)

    assert [scenario.scenario_id for scenario in scenarios] == EXPECTED_SCENARIO_IDS
    assert all(scenario.supported for scenario in scenarios)


def test_default_pack_v2_excludes_low_influence_scenarios_except_territory_grid() -> None:
    scenario_ids = {scenario.scenario_id for scenario in list_scenarios_from_pack(PACK_PATH)}

    excluded_prefixes = (
        "health_weights-",
        "dependency_state_thresholds-",
        "max_dist_inland_km-",
        "default_sampling_spacing_m-",
        "climada_max_points_per_feature-",
    )
    assert not any(
        scenario_id.startswith(excluded_prefixes)
        for scenario_id in scenario_ids
    )
    assert "vulnerability_curves_profile-manual-profile-required" not in scenario_ids
    assert "hazard_dynamic_max_tracks-500" not in scenario_ids
    assert "hazard_dynamic_max_tracks-1000" not in scenario_ids
    assert {"territory_grid_deg-0-05", "territory_grid_deg-0-1"} <= scenario_ids


def test_default_pack_v2_hazard_track_scenarios_override_matching_v1_manifests() -> None:
    scenarios = {
        scenario.scenario_id: scenario
        for scenario in list_scenarios_from_pack(
            PACK_PATH,
            scenario_ids=[
                "hazard_dynamic_max_tracks-50",
                "hazard_dynamic_max_tracks-100",
                "hazard_dynamic_max_tracks-800",
                "hazard_dynamic_max_tracks-5000",
            ],
        )
    }

    for track_count, sample_slug in (
        (50, "sample_0050"),
        (100, "sample_0100"),
        (800, "sample_0800"),
        (5000, "sample_5000"),
    ):
        settings = apply_settings_overrides(
            Settings(),
            scenarios[f"hazard_dynamic_max_tracks-{track_count}"],
        )

        assert settings.hazard_dynamic_max_tracks == track_count
        assert isinstance(settings.hazard_track_sample_manifest_path, Path)
        assert str(settings.hazard_track_sample_manifest_path).endswith(
            f"Échantillons Tracks_NA_Guadeloupe/{sample_slug}/manifest.json"
        )
