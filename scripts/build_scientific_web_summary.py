#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DATA_DIR = REPO_ROOT / "web" / "data"

NETWORK_CLASS_LABELS = {
    "eau_aep": "Eau AEP",
    "eau_eu": "Eau EU",
    "elec_bt_souterrain": "Elec BT souterrain",
    "elec_bt_aerien": "Elec BT aerien",
    "elec_hta_souterrain": "Elec HTA souterrain",
    "elec_hta_aerien": "Elec HTA aerien",
}

DAMAGE_BREAKDOWN_LABELS = {
    "eau_aep": "Reseau eau AEP",
    "eau_eu": "Reseau eau EU",
    "elec_bt_souterrain": "Basse tension souterrain",
    "elec_bt_aerien": "Basse tension aerien",
    "elec_hta_souterrain": "Haute tension souterrain",
    "elec_hta_aerien": "Haute tension aerien",
    "eau_aep_ouvrages": "Ouvrages AEP",
    "eau_eu_pr": "Postes de refoulement",
    "eau_eu_step": "STEP",
}

ASSET_TYPE_TO_NETWORK_CLASS = {
    "eau_aep_cana": "eau_aep",
    "eau_eu_cana": "eau_eu",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
}

ASSET_TYPE_TO_BREAKDOWN_CLASS = {
    **ASSET_TYPE_TO_NETWORK_CLASS,
    "eau_aep_ouvrage_cap": "eau_aep_ouvrages",
    "eau_aep_ouvrage_stpmp": "eau_aep_ouvrages",
    "eau_aep_ouvrage_ouveb": "eau_aep_ouvrages",
    "eau_aep_ouvrage_trait": "eau_aep_ouvrages",
    "eau_aep_ouvrage_cuv": "eau_aep_ouvrages",
    "eau_aep_ouvrage_captage": "eau_aep_ouvrages",
    "eau_aep_ouvrage_production_traitement": "eau_aep_ouvrages",
    "eau_aep_ouvrage_stockage": "eau_aep_ouvrages",
    "eau_eu_pr": "eau_eu_pr",
    "eau_eu_step": "eau_eu_step",
}

HAZARD_KEYS = ("storm", "storm_cmcc")
SCENARIOS = ("annual", "rp50", "rp100", "p99")
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
STATE_CODES = ("S0", "S1", "S2", "S3")
SCIENTIFIC_WEB_CONTRACT_VERSION = "scientific_web_contract_v2"
CANONICAL_SERVICE_LAYER_TO_KEY = {
    "eau_aep": "water_aep",
    "eau_eu": "water_eu",
    "elec_grid_0p1deg": "elec",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _round2(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except Exception:
        return 0.0


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _state_code(value: Any) -> str:
    state = str(value or "S0").strip().upper()
    return state if state in STATE_CODES else "S0"


def _portfolio_summary(portfolio: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard in HAZARD_KEYS:
        payload = _safe_dict(portfolio.get(hazard))
        out[hazard] = {
            "annual_eur": _round2(payload.get("eai_eur")),
            "rp50_eur": _round2(payload.get("pml_50_eur")),
            "rp100_eur": _round2(payload.get("pml_100_eur")),
            "p99_eur": _round2(payload.get("percentile_99_loss_eur")),
            "pml_1000_eur": _round2(payload.get("pml_1000_eur")),
            "direct_annual_eur": _round2(payload.get("eai_direct_eur")),
            "indirect_annual_eur": _round2(payload.get("eai_indirect_eur")),
        }
    out["delta"] = _safe_dict(portfolio.get("delta"))
    return out


def _normalized_asset_type(asset_type_raw: Any) -> str:
    return str(asset_type_raw or "").strip().lower()


def _blank_component_map() -> dict[str, float]:
    return {component: 0.0 for component in COMPONENT_ORDER}


def _new_damage_bucket() -> dict[str, float]:
    return {
        "exposure_eur": 0.0,
        "damage_eur": 0.0,
        "direct_damage_eur": 0.0,
        "indirect_damage_eur": 0.0,
    }


def _group_asset_results(asset_results: list[dict[str, Any]], class_mapping: dict[str, str]) -> dict[str, dict[str, dict[str, float]]]:
    grouped: dict[str, dict[str, dict[str, float]]] = {}
    for asset in asset_results:
        if not isinstance(asset, dict):
            continue
        class_key = class_mapping.get(_normalized_asset_type(asset.get("asset_type")))
        if not class_key:
            continue
        class_bucket = grouped.setdefault(
            class_key,
            {
                "storm": _new_damage_bucket(),
                "storm_cmcc": _new_damage_bucket(),
            },
        )
        exposure = _round2(asset.get("exposure_eur"))
        for hazard in HAZARD_KEYS:
            bucket = class_bucket[hazard]
            bucket["exposure_eur"] += exposure
            if hazard == "storm":
                bucket["damage_eur"] += _round2(asset.get("eai_storm_eur"))
                bucket["direct_damage_eur"] += _round2(asset.get("eai_storm_direct_eur"))
                bucket["indirect_damage_eur"] += _round2(asset.get("eai_storm_indirect_eur"))
            else:
                bucket["damage_eur"] += _round2(asset.get("eai_cmcc_eur"))
                bucket["direct_damage_eur"] += _round2(asset.get("eai_cmcc_direct_eur"))
                bucket["indirect_damage_eur"] += _round2(asset.get("eai_cmcc_indirect_eur"))
    return grouped


def _build_annual_rows(grouped: dict[str, dict[str, dict[str, float]]], labels: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for class_key in labels.keys():
        by_hazard = grouped.get(class_key) or {"storm": _new_damage_bucket(), "storm_cmcc": _new_damage_bucket()}
        rows.append(
            {
                "class_key": class_key,
                "class_label": labels[class_key],
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
                    "exposure_eur": _round2(by_hazard["storm"].get("exposure_eur")),
                    "damage_eur": _round2(by_hazard["storm"].get("damage_eur")),
                    "direct_damage_eur": _round2(by_hazard["storm"].get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(by_hazard["storm"].get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
                    "exposure_eur": _round2(by_hazard["storm_cmcc"].get("exposure_eur")),
                    "damage_eur": _round2(by_hazard["storm_cmcc"].get("damage_eur")),
                    "direct_damage_eur": _round2(by_hazard["storm_cmcc"].get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(by_hazard["storm_cmcc"].get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                },
            }
        )
    return rows


def _build_annual_breakdown_rows(grouped: dict[str, dict[str, dict[str, float]]], labels: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    by_hazard: dict[str, list[dict[str, Any]]] = {"storm": [], "storm_cmcc": []}
    for class_key in labels.keys():
        grouped_row = grouped.get(class_key) or {"storm": _new_damage_bucket(), "storm_cmcc": _new_damage_bucket()}
        for hazard in HAZARD_KEYS:
            bucket = grouped_row[hazard]
            by_hazard[hazard].append(
                {
                    "class_key": class_key,
                    "class_label": labels[class_key],
                    "exposure_eur": _round2(bucket.get("exposure_eur")),
                    "damage_eur": _round2(bucket.get("damage_eur")),
                    "direct_damage_eur": _round2(bucket.get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(bucket.get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                }
            )
    return by_hazard


def _service_state_distribution(network_states_native: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard in HAZARD_KEYS:
        by_service = _safe_dict(network_states_native.get(hazard))
        out[hazard] = {}
        for service_key, service_map_raw in by_service.items():
            service_map = _safe_dict(service_map_raw)
            counts = {"S0": 0, "S1": 0, "S2": 0, "S3": 0}
            for state_row in service_map.values():
                if not isinstance(state_row, dict):
                    continue
                state = _state_code(state_row.get("state"))
                counts[state] += 1
            counts["total_units"] = int(sum(counts.values()))
            out[hazard][service_key] = counts
    return out


def _canonical_service_key_from_feature(feature: dict[str, Any]) -> str | None:
    props = _safe_dict(feature.get("properties"))
    layer_key = str(props.get("layer_key") or "").strip().lower()
    return CANONICAL_SERVICE_LAYER_TO_KEY.get(layer_key)


def _service_unit_id_from_feature(feature: dict[str, Any]) -> str:
    props = _safe_dict(feature.get("properties"))
    for raw_value in (
        props.get("service_feature_id"),
        props.get("zone_component_key"),
        props.get("feature_id"),
    ):
        value = str(raw_value or "").strip()
        if value:
            return value
    return ""


def _empty_state_count_row() -> dict[str, int]:
    return {
        "S0": 0,
        "S1": 0,
        "S2": 0,
        "S3": 0,
        "total_units": 0,
    }


def _empty_state_breakdown_row() -> dict[str, float]:
    return {state_code: 0.0 for state_code in STATE_CODES}


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load_json(path)


def _build_network_state_distribution_from_geojson(
    network_states_geojson: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, bool], dict[str, dict[str, int]]]:
    features = _safe_list(_safe_dict(network_states_geojson).get("features"))
    distribution: dict[str, Any] = {scenario: {hazard: {} for hazard in HAZARD_KEYS} for scenario in SCENARIOS}
    canonical_service_unit_counts: dict[str, dict[str, int]] = {
        hazard: {service_key: 0 for service_key in CANONICAL_SERVICE_LAYER_TO_KEY.values()}
        for hazard in HAZARD_KEYS
    }
    seen_units: dict[str, dict[str, dict[str, set[str]]]] = {
        scenario: {
            hazard: {service_key: set() for service_key in CANONICAL_SERVICE_LAYER_TO_KEY.values()}
            for hazard in HAZARD_KEYS
        }
        for scenario in SCENARIOS
    }

    for feature in features:
        if not isinstance(feature, dict):
            continue
        service_key = _canonical_service_key_from_feature(feature)
        if service_key is None:
            continue
        service_unit_id = _service_unit_id_from_feature(feature)
        if not service_unit_id:
            continue
        for scenario in SCENARIOS:
            for hazard in HAZARD_KEYS:
                hazard_bucket = distribution[scenario][hazard]
                service_bucket = hazard_bucket.setdefault(service_key, _empty_state_count_row())
                if service_unit_id in seen_units[scenario][hazard][service_key]:
                    continue
                props = _safe_dict(feature.get("properties"))
                state_code = _state_code(props.get(f"state_{scenario}_{hazard}"))
                service_bucket[state_code] += 1
                service_bucket["total_units"] += 1
                seen_units[scenario][hazard][service_key].add(service_unit_id)

    for hazard in HAZARD_KEYS:
        for service_key in CANONICAL_SERVICE_LAYER_TO_KEY.values():
            canonical_service_unit_counts[hazard][service_key] = int(
                len(seen_units["p99"][hazard][service_key])
            )

    scenario_availability: dict[str, bool] = {}
    for scenario in SCENARIOS:
        scenario_availability[scenario] = all(
            any(int(_safe_dict(distribution[scenario][hazard].get(service_key)).get("total_units", 0)) > 0 for service_key in CANONICAL_SERVICE_LAYER_TO_KEY.values())
            for hazard in HAZARD_KEYS
        )
    return distribution, scenario_availability, canonical_service_unit_counts


def _feature_representative_point(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = _safe_dict(feature.get("geometry"))
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return None

    points: list[tuple[float, float]] = []

    def _walk(node: Any) -> None:
        if not isinstance(node, list):
            return
        if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
            points.append((float(node[0]), float(node[1])))
            return
        for child in node:
            _walk(child)

    _walk(coordinates)
    if not points:
        return None
    lon = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)
    return lat, lon


def _territory_cell_id_from_lat_lon(lat_raw: Any, lon_raw: Any) -> str | None:
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except Exception:
        return None
    lat_bin = round(lat / 0.2) * 0.2
    lon_bin = round(lon / 0.2) * 0.2
    return f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}"


def _state_severity(state_raw: Any) -> int:
    state_code = _state_code(state_raw)
    if state_code == "S3":
        return 3
    if state_code == "S2":
        return 2
    if state_code == "S1":
        return 1
    return 0


def _population_by_cell_from_complete_analysis(complete_analysis: dict[str, Any]) -> dict[str, float]:
    rows = _safe_list(complete_analysis.get("territory_results"))
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        territory_id = str(row.get("territory_id") or "").strip()
        if territory_id:
            out[territory_id] = float(row.get("population_total") or 0.0)
    return out


def _build_social_impact_from_geojson(
    *,
    complete_analysis: dict[str, Any],
    network_states_geojson: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    population_by_cell = _population_by_cell_from_complete_analysis(complete_analysis)
    features = _safe_list(_safe_dict(network_states_geojson).get("features"))
    worst_states: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        scenario: {hazard: {} for hazard in HAZARD_KEYS}
        for scenario in SCENARIOS
    }

    for feature in features:
        if not isinstance(feature, dict):
            continue
        service_key = _canonical_service_key_from_feature(feature)
        if service_key is None:
            continue
        point = _feature_representative_point(feature)
        if point is None:
            continue
        cell_id = _territory_cell_id_from_lat_lon(point[0], point[1])
        if not cell_id or cell_id not in population_by_cell:
            continue
        props = _safe_dict(feature.get("properties"))
        for scenario in SCENARIOS:
            for hazard in HAZARD_KEYS:
                service_states = worst_states[scenario][hazard].setdefault(
                    cell_id,
                    {"elec": "S0", "water_aep": "S0", "water_eu": "S0"},
                )
                state_code = _state_code(props.get(f"state_{scenario}_{hazard}"))
                if _state_severity(state_code) > _state_severity(service_states.get(service_key)):
                    service_states[service_key] = state_code

    summary: dict[str, Any] = {}
    population_distribution: dict[str, Any] = {}
    scenario_availability: dict[str, bool] = {}
    for scenario in SCENARIOS:
        summary[scenario] = {}
        population_distribution[scenario] = {}
        scenario_availability[scenario] = True
        for hazard in HAZARD_KEYS:
            totals = {
                "total_population_affected_any_network": 0.0,
                "total_without_elec": 0.0,
                "total_without_water_aep": 0.0,
                "total_without_water_eu": 0.0,
                "total_without_water": 0.0,
                "total_with_degraded_elec": 0.0,
                "total_with_degraded_water_aep": 0.0,
                "total_with_degraded_water_eu": 0.0,
                "state_breakdown": {
                    "elec": _empty_state_breakdown_row(),
                    "water_aep": _empty_state_breakdown_row(),
                    "water_eu": _empty_state_breakdown_row(),
                },
            }
            for cell_id, population in population_by_cell.items():
                if population <= 0:
                    continue
                states = worst_states[scenario][hazard].get(
                    cell_id,
                    {"elec": "S0", "water_aep": "S0", "water_eu": "S0"},
                )
                elec_state = _state_code(states.get("elec"))
                water_aep_state = _state_code(states.get("water_aep"))
                water_eu_state = _state_code(states.get("water_eu"))
                totals["state_breakdown"]["elec"][elec_state] += population
                totals["state_breakdown"]["water_aep"][water_aep_state] += population
                totals["state_breakdown"]["water_eu"][water_eu_state] += population
                if elec_state != "S0" or water_aep_state != "S0" or water_eu_state != "S0":
                    totals["total_population_affected_any_network"] += population
                if elec_state == "S3":
                    totals["total_without_elec"] += population
                if water_aep_state == "S3":
                    totals["total_without_water_aep"] += population
                if water_eu_state == "S3":
                    totals["total_without_water_eu"] += population
                if elec_state in {"S1", "S2"}:
                    totals["total_with_degraded_elec"] += population
                if water_aep_state in {"S1", "S2"}:
                    totals["total_with_degraded_water_aep"] += population
                if water_eu_state in {"S1", "S2"}:
                    totals["total_with_degraded_water_eu"] += population
            totals["total_without_water"] = (
                float(totals["total_without_water_aep"]) + float(totals["total_without_water_eu"])
            )
            summary[scenario][hazard] = totals
            population_distribution[scenario][hazard] = totals["state_breakdown"]
    return summary, population_distribution, scenario_availability


def _load_page_analysis_impact(page_analysis: dict[str, Any] | None) -> dict[str, Any]:
    impact = _safe_dict(_safe_dict(page_analysis).get("impact"))
    return impact if impact else {}


def _build_scientific_web_summary(
    complete_analysis: dict[str, Any],
    territory: str,
    *,
    network_states_geojson: dict[str, Any] | None = None,
    page_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _safe_dict(complete_analysis.get("meta"))
    portfolio = _safe_dict(complete_analysis.get("portfolio_results"))
    asset_results = [row for row in _safe_list(complete_analysis.get("asset_results")) if isinstance(row, dict)]
    grouped_network = _group_asset_results(asset_results, ASSET_TYPE_TO_NETWORK_CLASS)
    grouped_breakdown = _group_asset_results(asset_results, ASSET_TYPE_TO_BREAKDOWN_CLASS)

    portfolio_summary = _portfolio_summary(portfolio)
    network_tables_annual = _build_annual_rows(grouped_network, NETWORK_CLASS_LABELS)
    breakdown_annual = _build_annual_breakdown_rows(grouped_breakdown, DAMAGE_BREAKDOWN_LABELS)
    page_impact = _load_page_analysis_impact(page_analysis)
    network_state_distribution, network_state_availability, canonical_service_unit_counts = (
        _build_network_state_distribution_from_geojson(network_states_geojson)
    )
    social_summaries, social_population_distribution, social_availability = _build_social_impact_from_geojson(
        complete_analysis=complete_analysis,
        network_states_geojson=network_states_geojson,
    )

    fallback_state_tables = {
        "annual": network_tables_annual,
        "rp50": [],
        "rp100": [],
        "p99": [],
    }
    fallback_breakdowns = {
        "annual": {
            "storm": breakdown_annual["storm"],
            "storm_cmcc": breakdown_annual["storm_cmcc"],
        },
        "rp50": {"storm": [], "storm_cmcc": []},
        "rp100": {"storm": [], "storm_cmcc": []},
        "p99": {"storm": [], "storm_cmcc": []},
    }

    page_state_tables = _safe_dict(page_impact.get("state_damage_tables"))
    page_breakdowns = _safe_dict(page_impact.get("damage_breakdown_by_scenario"))
    page_component_order = page_impact.get("component_order")
    damage_table_availability = {
        scenario: bool(_safe_list(page_state_tables.get(scenario)))
        for scenario in SCENARIOS
    }
    if not any(damage_table_availability.values()):
        damage_table_availability = {
            "annual": True,
            "rp50": False,
            "rp100": False,
            "p99": False,
        }

    summary_metrics = {
        "storm": {
            "eai_total_eur": _round2(portfolio_summary["storm"].get("annual_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm"].get("rp100_eur")),
            "p99_total_loss_eur": _round2(portfolio_summary["storm"].get("p99_eur")),
        },
        "storm_cmcc": {
            "eai_total_eur": _round2(portfolio_summary["storm_cmcc"].get("annual_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp100_eur")),
            "p99_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("p99_eur")),
        },
    }

    scientific_summary = {
        "meta": {
            "territory": territory,
            "run_id": str(meta.get("run_id") or complete_analysis.get("run_id") or ""),
            "generated_at": datetime.now(UTC).isoformat(),
            "dynamic_max_tracks": meta.get("requested_dynamic_max_tracks"),
            "scientific_source": True,
            "schema_version": "scientific_web_summary_v2",
            "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
            "source_artifact": f"{territory}-complete-analysis.json",
            "source_of_truth": "scientific_web_summary",
            "aggregation_unit": "scientific_service_unit",
            "scenarios": list(SCENARIOS),
            "comparability_guaranteed": True,
        },
        "portfolio_summary": portfolio_summary,
        "network_damage_tables": {
            "annual": _safe_list(page_state_tables.get("annual")) or fallback_state_tables["annual"],
            "rp50": _safe_list(page_state_tables.get("rp50")),
            "rp100": _safe_list(page_state_tables.get("rp100")),
            "p99": _safe_list(page_state_tables.get("p99")),
            "scenario_availability": {
                scenario: (
                    "scientific_widget_contract"
                    if damage_table_availability.get(scenario)
                    else "unavailable"
                )
                for scenario in SCENARIOS
            },
        },
        "component_breakdowns": {
            "annual": _safe_dict(page_breakdowns.get("annual")) or fallback_breakdowns["annual"],
            "rp50": _safe_dict(page_breakdowns.get("rp50")) or fallback_breakdowns["rp50"],
            "rp100": _safe_dict(page_breakdowns.get("rp100")) or fallback_breakdowns["rp100"],
            "p99": _safe_dict(page_breakdowns.get("p99")) or fallback_breakdowns["p99"],
            "portfolio_component_totals": {
                "annual": {
                    "storm": _safe_dict(_safe_dict(portfolio.get("storm")).get("components_direct_eai_eur")),
                    "storm_cmcc": _safe_dict(_safe_dict(portfolio.get("storm_cmcc")).get("components_direct_eai_eur")),
                },
                "p99": {
                    "storm": _safe_dict(_safe_dict(portfolio.get("storm")).get("components_direct_percentile_99_loss_eur")),
                    "storm_cmcc": _safe_dict(_safe_dict(portfolio.get("storm_cmcc")).get("components_direct_percentile_99_loss_eur")),
                },
            },
        },
        "network_states": {
            "contract": {
                "source_of_truth": "scientific_web_summary",
                "aggregation_unit": "scientific_service_unit",
                "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
                "canonical_service_layer_keys": list(CANONICAL_SERVICE_LAYER_TO_KEY.keys()),
                "service_keys": list(CANONICAL_SERVICE_LAYER_TO_KEY.values()),
                "scenarios": list(SCENARIOS),
                "comparable_widgets": [
                    "network_state_map",
                    "network_state_pie",
                    "network_state_table",
                    "network_state_kpi",
                ],
            },
            "scenario_service_state_distribution": network_state_distribution,
            "canonical_service_unit_counts": canonical_service_unit_counts,
            "worst_case_native_service_states": _safe_dict(portfolio.get("network_states_native")),
            "worst_case_projected_service_states": _safe_dict(portfolio.get("network_states_projected")),
            "worst_case_projected_service_coverage": _safe_dict(portfolio.get("network_states_projected_coverage")),
            "scenario_availability": network_state_availability,
        },
        "social_impact": {
            "scenario_summary": social_summaries,
            "scenario_population_state_distribution": social_population_distribution,
            "worst_case_summary": _safe_dict(portfolio.get("social_impact_summary")),
            "worst_case_population_state_distribution": _safe_dict(portfolio.get("social_impact_population_state_distribution")),
            "scenario_availability": social_availability,
        },
        "frontend": {
            "contract": {
                "source_of_truth": "scientific_web_summary",
                "aggregation_unit": "scientific_service_unit",
                "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
                "strict_widget_source": True,
            },
            "impact": {
                "component_order": (
                    list(page_component_order)
                    if isinstance(page_component_order, list) and page_component_order
                    else list(COMPONENT_ORDER)
                ),
                "summary_metrics": summary_metrics,
                "state_damage_tables": {
                    scenario: _safe_list(page_state_tables.get(scenario)) or fallback_state_tables[scenario]
                    for scenario in SCENARIOS
                },
                "damage_breakdown_by_scenario": {
                    scenario: _safe_dict(page_breakdowns.get(scenario)) or fallback_breakdowns[scenario]
                    for scenario in SCENARIOS
                },
                "map_defaults": _safe_dict(page_impact.get("map_defaults")) or {"hazard": "storm", "scenario": "p99"},
            },
            "scenario_availability": {
                scenario: {
                    "damage_tables": bool(damage_table_availability.get(scenario)),
                    "social_impact": bool(social_availability.get(scenario)),
                    "network_states": bool(network_state_availability.get(scenario)),
                }
                for scenario in SCENARIOS
            },
        },
        "notes": [
            "Ce payload aligne les widgets web sur une source scientifique unique.",
            "Les totaux portefeuille proviennent du complete-analysis publie.",
            "Les distributions d etat reseau et les impacts sociaux par scenario sont recomptes depuis la couche canonique network-states.geojson.",
            "Les tableaux d impact front sont republies ici pour eviter tout fallback metier silencieux dans le client.",
        ],
    }
    return scientific_summary


def build_scientific_web_summary(
    *,
    territory: str,
    complete_analysis_path: Path,
    out_path: Path,
    network_states_geojson_path: Path | None = None,
    page_analysis_path: Path | None = None,
) -> Path:
    complete_analysis = _load_json(complete_analysis_path)
    network_states_geojson = _load_optional_json(network_states_geojson_path)
    page_analysis = _load_optional_json(page_analysis_path)
    payload = _build_scientific_web_summary(
        complete_analysis,
        territory,
        network_states_geojson=network_states_geojson,
        page_analysis=page_analysis,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build scientific web summary from a published complete-analysis payload.")
    parser.add_argument("--territory", required=True)
    parser.add_argument("--complete-analysis-json", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--network-states-geojson", default=None)
    parser.add_argument("--page-analysis-json", default=None)
    args = parser.parse_args(argv)

    territory = str(args.territory).strip().lower()
    complete_analysis_path = (
        Path(args.complete_analysis_json)
        if args.complete_analysis_json
        else (WEB_DATA_DIR / f"{territory}-complete-analysis.json")
    )
    out_path = (
        Path(args.out_json)
        if args.out_json
        else (WEB_DATA_DIR / f"{territory}-scientific-web-summary.json")
    )
    network_states_geojson_path = (
        Path(args.network_states_geojson)
        if args.network_states_geojson
        else (WEB_DATA_DIR / f"{territory}-network-states.geojson")
    )
    page_suffix = "page7" if territory == "saint-barthelemy" else ("page2" if territory == "martinique" else "page1")
    page_analysis_path = (
        Path(args.page_analysis_json)
        if args.page_analysis_json
        else (WEB_DATA_DIR / f"{territory}-{page_suffix}-analysis.json")
    )
    build_scientific_web_summary(
        territory=territory,
        complete_analysis_path=complete_analysis_path,
        out_path=out_path,
        network_states_geojson_path=network_states_geojson_path,
        page_analysis_path=page_analysis_path,
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
