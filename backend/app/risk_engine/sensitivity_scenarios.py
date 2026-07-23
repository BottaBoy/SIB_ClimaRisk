from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings


SUPPORTED_SCENARIO_PACK_VERSION = 1

PATH_SETTING_KEYS = {
    "job_root",
    "demo_result_path",
    "data_root",
    "hazard_storm_path",
    "hazard_storm_cmcc_path",
    "storm_parquet_path",
    "storm_cmcc_parquet_path",
    "hazard_track_sample_manifest_path",
    "hazard_surge_topo_path",
    "d2_flood_curve_file",
    "landslide_precip_current_path",
    "landslide_precip_ssp585_path",
    "landslide_earthquake_path",
    "population_data_dir",
    "example_qgis_points_path",
    "example_qgis_lines_path",
    "example_qgis_polygons_path",
}

SENSITIVITY_PARAMETER_SPECS: dict[str, dict[str, Any]] = {
    "vulnerability_curves_profile": {
        "setting_keys": [
            "wind_asset_type_to_curve_code",
            "flood_asset_type_to_curve_code",
        ],
        "consumed_by": [
            "tc_impact_function_mapping",
            "multi_hazard_flood_depth_mapping",
        ],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "vulnerability_mapping_profile",
        "default_pack_behavior": "manual_or_explicit_profile",
    },
    "runoff_coeff": {
        "setting_keys": ["multi_hazard_rain_base_runoff_coeff"],
        "consumed_by": ["hazard_rain_proxy"],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "monetary_driver",
        "default_pack_behavior": "include",
    },
    "direct_state_thresholds": {
        "setting_keys": [
            "interdependency_state_threshold_s0_to_s1",
            "interdependency_state_threshold_s1_to_s2",
            "interdependency_state_threshold_s2_to_s3",
        ],
        "consumed_by": ["interdependency_state_mapping"],
        "expected_metric_families": ["network_state", "social"],
        "non_effect_metric_families": ["monetary"],
        "parameter_class": "network_state_driver",
        "default_pack_behavior": "include_if_network_graphs",
    },
    "health_weights": {
        "setting_keys": [
            "interdependency_health_weight_s1",
            "interdependency_health_weight_s2",
            "interdependency_health_weight_s3",
        ],
        "consumed_by": ["interdependency_electric_health"],
        "expected_metric_families": ["network_state", "social"],
        "non_effect_metric_families": ["monetary"],
        "parameter_class": "network_state_driver",
        "default_pack_behavior": "include_if_network_graphs",
    },
    "dependency_state_thresholds": {
        "setting_keys": [
            "interdependency_dependency_state_threshold_s1",
            "interdependency_dependency_state_threshold_s2",
            "interdependency_dependency_state_threshold_s3",
        ],
        "consumed_by": ["interdependency_dependency_state"],
        "expected_metric_families": ["network_state", "social"],
        "non_effect_metric_families": ["monetary"],
        "parameter_class": "network_state_driver",
        "default_pack_behavior": "include_if_network_graphs",
    },
    "uplift_by_state": {
        "setting_keys": [
            "interdependency_uplift_s0",
            "interdependency_uplift_s1",
            "interdependency_uplift_s2",
            "interdependency_uplift_s3",
        ],
        "consumed_by": ["interdependency_uplift_disabled"],
        "expected_metric_families": [],
        "non_effect_metric_families": ["monetary", "network_state", "social"],
        "parameter_class": "inactive_by_design",
        "default_pack_behavior": "exclude",
    },
    "max_dist_inland_km": {
        "setting_keys": ["hazard_rain_max_dist_inland_km"],
        "consumed_by": ["hazard_rain_proxy"],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "monetary_driver",
        "default_pack_behavior": "include",
    },
    "hazard_dynamic_max_tracks": {
        "setting_keys": ["hazard_dynamic_max_tracks"],
        "consumed_by": ["hazard_dynamic_tracks"],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "monetary_driver",
        "default_pack_behavior": "include",
    },
    "territory_grid_deg": {
        "setting_keys": ["territory_grid_deg"],
        "consumed_by": ["climada_territory_binning", "population_grid_alignment"],
        "expected_metric_families": ["network_state", "social"],
        "non_effect_metric_families": ["monetary_total_should_be_stable"],
        "parameter_class": "spatial_aggregation_driver",
        "default_pack_behavior": "include_if_network_graphs",
    },
    "default_sampling_spacing_m": {
        "setting_keys": ["default_sampling_spacing_m"],
        "consumed_by": ["exposure_disaggregation", "climada_exposure_sampling"],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "disaggregation_driver",
        "default_pack_behavior": "include",
    },
    "climada_max_points_per_feature": {
        "setting_keys": ["climada_max_points_per_feature"],
        "consumed_by": ["climada_exposure_sampling"],
        "expected_metric_families": ["monetary", "network_state", "social"],
        "non_effect_metric_families": [],
        "parameter_class": "disaggregation_driver",
        "default_pack_behavior": "include",
    },
}


@dataclass(frozen=True)
class SensitivityScenario:
    scenario_id: str
    label: str
    parameter_key: str | None
    execution_tier: str
    supported: bool
    overrides: dict[str, Any]
    notes: list[str]
    source_pack_path: Path


def load_scenario_pack(pack_path: str | Path) -> dict[str, Any]:
    path = Path(pack_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario pack must be a JSON object: {path}")
    version = int(payload.get("version") or 0)
    if version != SUPPORTED_SCENARIO_PACK_VERSION:
        raise ValueError(
            f"Unsupported scenario pack version {version} in {path}; expected {SUPPORTED_SCENARIO_PACK_VERSION}"
        )
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"Scenario pack does not contain any scenarios: {path}")
    payload["_path"] = str(path)
    return payload


def _scenario_from_payload_item(item: dict[str, Any], *, source_pack_path: Path) -> SensitivityScenario:
    scenario_id = str(item.get("scenario_id") or "").strip()
    if not scenario_id:
        raise ValueError(f"Scenario entry is missing a scenario_id in {source_pack_path}")
    return SensitivityScenario(
        scenario_id=scenario_id,
        label=str(item.get("label") or scenario_id),
        parameter_key=str(item.get("parameter_key") or "").strip() or None,
        execution_tier=str(item.get("execution_tier") or "full_rerun"),
        supported=bool(item.get("supported", True)),
        overrides=dict(item.get("overrides") or {}),
        notes=[str(value) for value in list(item.get("notes") or [])],
        source_pack_path=source_pack_path,
    )


def list_scenarios_from_pack(
    pack_path: str | Path,
    *,
    scenario_ids: list[str] | tuple[str, ...] | None = None,
) -> list[SensitivityScenario]:
    payload = load_scenario_pack(pack_path)
    source_pack_path = Path(str(payload.get("_path") or pack_path))
    selected_ids = None
    if scenario_ids:
        selected_ids = {str(value).strip() for value in scenario_ids if str(value).strip()}
    scenarios: list[SensitivityScenario] = []
    for item in payload.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        scenario = _scenario_from_payload_item(item, source_pack_path=source_pack_path)
        if selected_ids is not None and scenario.scenario_id not in selected_ids:
            continue
        scenarios.append(scenario)

    if selected_ids is not None:
        found_ids = {scenario.scenario_id for scenario in scenarios}
        missing_ids = sorted(selected_ids - found_ids)
        if missing_ids:
            raise ValueError(
                f"Scenarios not found in {source_pack_path}: {', '.join(missing_ids)}"
            )
    return scenarios


def resolve_scenario_from_pack(pack_path: str | Path, scenario_id: str) -> SensitivityScenario:
    payload = load_scenario_pack(pack_path)
    requested_id = str(scenario_id or "").strip()
    if not requested_id:
        raise ValueError("scenario_id must not be empty")

    for item in payload.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("scenario_id") or "").strip() != requested_id:
            continue
        return _scenario_from_payload_item(
            item,
            source_pack_path=Path(str(payload.get("_path") or pack_path)),
        )

    raise ValueError(f"Scenario '{requested_id}' was not found in {pack_path}")


def parameter_traceability(parameter_key: str | None) -> dict[str, Any]:
    key = str(parameter_key or "").strip()
    if not key:
        return {
            "parameter_key": None,
            "setting_keys": [],
            "consumed_by": [],
            "expected_metric_families": ["monetary", "network_state", "social"],
            "non_effect_metric_families": [],
            "parameter_class": "baseline_reference",
            "default_pack_behavior": "include",
        }
    spec = dict(SENSITIVITY_PARAMETER_SPECS.get(key) or {})
    spec["parameter_key"] = key
    if not spec:
        spec = {
            "parameter_key": key,
            "setting_keys": [],
            "consumed_by": [],
            "expected_metric_families": [],
            "non_effect_metric_families": [],
            "parameter_class": "unclassified",
            "default_pack_behavior": "review",
        }
    return spec


def build_parameter_traceability_matrix(scenarios: list[SensitivityScenario]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    rows.append(parameter_traceability(None))
    for scenario in scenarios:
        key = str(scenario.parameter_key or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        row = parameter_traceability(key)
        row["scenario_ids"] = sorted(
            s.scenario_id for s in scenarios if str(s.parameter_key or "").strip() == key
        )
        rows.append(row)
    return rows


def apply_settings_overrides(settings: Settings, scenario: SensitivityScenario | None) -> Settings:
    if scenario is None:
        return settings
    if not scenario.supported:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' is marked as unsupported for automated execution. "
            "Define the requested manual profile first or choose another scenario."
        )

    settings_overrides = dict((scenario.overrides or {}).get("settings") or {})
    if not settings_overrides:
        return settings

    settings_dict = dataclasses.asdict(settings)
    unknown_keys = sorted(set(settings_overrides) - set(settings_dict))
    if unknown_keys:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' contains unknown Settings override keys: {', '.join(unknown_keys)}"
        )

    for key, value in list(settings_overrides.items()):
        if key in PATH_SETTING_KEYS and value is not None:
            settings_overrides[key] = Path(str(value)).expanduser()

    settings_dict.update(settings_overrides)
    return Settings(**settings_dict)


def scenario_manifest_fields(scenario: SensitivityScenario | None) -> dict[str, Any]:
    if scenario is None:
        return {}
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_label": scenario.label,
        "scenario_parameter_key": scenario.parameter_key,
        "scenario_execution_tier": scenario.execution_tier,
        "scenario_pack_path": str(scenario.source_pack_path),
    }
