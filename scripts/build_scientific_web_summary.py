#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import path depends on module vs CLI execution
    from scripts.scientific_graph_postprocess import (  # type: ignore
        needs_strict_scientific_rebuild,
        rebuild_scientific_graph_inputs,
    )
    from scripts.scientific_publication_contract import (  # type: ignore
        EVENT_SELECTION_BASIS,
        PUBLIC_SERVICE_KEYS,
        SCIENTIFIC_SCENARIOS,
        SCIENTIFIC_WEB_CONTRACT_VERSION,
        SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
        SERVICE_LAYER_TO_PUBLIC_KEY,
    )
except ModuleNotFoundError:  # pragma: no cover
    from scientific_graph_postprocess import (  # type: ignore
        needs_strict_scientific_rebuild,
        rebuild_scientific_graph_inputs,
    )
    from scientific_publication_contract import (  # type: ignore
        EVENT_SELECTION_BASIS,
        PUBLIC_SERVICE_KEYS,
        SCIENTIFIC_SCENARIOS,
        SCIENTIFIC_WEB_CONTRACT_VERSION,
        SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
        SERVICE_LAYER_TO_PUBLIC_KEY,
    )

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

HAZARD_KEYS = ("storm", "storm_cmcc")
SCENARIOS = SCIENTIFIC_SCENARIOS
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
STATE_CODES = ("S0", "S1", "S2", "S3")
CANONICAL_SERVICE_LAYER_TO_KEY = SERVICE_LAYER_TO_PUBLIC_KEY
LEGACY_PUBLIC_SERVICE_KEY_MAP = {
    "water_aep": "eau_aep",
    "water_eu": "eau_eu",
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


def _graph_inputs_have_required_rows(value: Any) -> bool:
    graph_inputs = _safe_dict(value)
    if list(graph_inputs.get("scenarios") or []) != list(SCENARIOS):
        return False
    state_tables = _safe_dict(graph_inputs.get("state_damage_tables"))
    breakdowns = _safe_dict(graph_inputs.get("damage_breakdown_by_scenario"))
    for scenario in SCENARIOS:
        if not _safe_list(state_tables.get(scenario)):
            return False
        scenario_breakdown = _safe_dict(breakdowns.get(scenario))
        if not _safe_list(scenario_breakdown.get("storm")) or not _safe_list(scenario_breakdown.get("storm_cmcc")):
            return False
    return True


def _select_graph_inputs_from_complete_analysis(complete_analysis: dict[str, Any]) -> dict[str, Any]:
    strict_inputs = _safe_dict(complete_analysis.get("scientific_graph_inputs"))
    if _graph_inputs_have_required_rows(strict_inputs) and not needs_strict_scientific_rebuild(complete_analysis):
        return strict_inputs
    pml_inputs = _safe_dict(complete_analysis.get("pml_network_graph_inputs"))
    if _graph_inputs_have_required_rows(pml_inputs):
        return pml_inputs
    if _graph_inputs_have_required_rows(strict_inputs):
        return strict_inputs
    return strict_inputs


def _canonicalize_public_service_text(value: str) -> str:
    out = str(value)
    for legacy_key, canonical_key in LEGACY_PUBLIC_SERVICE_KEY_MAP.items():
        out = out.replace(legacy_key, canonical_key)
    return out


def _canonicalize_public_service_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_canonicalize_public_service_keys(item) for item in value]
    if not isinstance(value, dict):
        if isinstance(value, str):
            return _canonicalize_public_service_text(value)
        return value

    out: dict[str, Any] = {}
    for key, item in value.items():
        canonical_key = _canonicalize_public_service_text(str(key))
        canonical_item = _canonicalize_public_service_keys(item)
        if canonical_key in out and isinstance(out[canonical_key], dict) and isinstance(canonical_item, dict):
            out[canonical_key].update(canonical_item)
        else:
            out[canonical_key] = canonical_item
    return out


def _state_code(value: Any) -> str:
    state = str(value or "S0").strip().upper()
    return state if state in STATE_CODES else "S0"


def _portfolio_summary(portfolio: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard in HAZARD_KEYS:
        payload = _safe_dict(portfolio.get(hazard))
        out[hazard] = {
            "rp10_eur": _round2(payload.get("pml_10_eur")),
            "rp50_eur": _round2(payload.get("pml_50_eur")),
            "rp100_eur": _round2(payload.get("pml_100_eur")),
            "rp1000_eur": _round2(payload.get("pml_1000_eur")),
        }
    out["delta"] = _safe_dict(portfolio.get("delta"))
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


def _has_network_state_features(network_states_geojson: dict[str, Any] | None) -> bool:
    return bool(_safe_list(_safe_dict(network_states_geojson).get("features")))


def _build_network_state_distribution_from_geojson(
    network_states_geojson: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, bool], dict[str, dict[str, int]]]:
    features = _safe_list(_safe_dict(network_states_geojson).get("features"))
    distribution: dict[str, Any] = {scenario: {hazard: {} for hazard in HAZARD_KEYS} for scenario in SCENARIOS}
    canonical_service_unit_counts: dict[str, dict[str, int]] = {
        hazard: {service_key: 0 for service_key in PUBLIC_SERVICE_KEYS}
        for hazard in HAZARD_KEYS
    }
    seen_units: dict[str, dict[str, dict[str, set[str]]]] = {
        scenario: {
            hazard: {service_key: set() for service_key in PUBLIC_SERVICE_KEYS}
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
        for service_key in PUBLIC_SERVICE_KEYS:
            canonical_service_unit_counts[hazard][service_key] = int(
                len(seen_units[SCENARIOS[-1]][hazard][service_key])
            )

    scenario_availability: dict[str, bool] = {}
    for scenario in SCENARIOS:
        scenario_availability[scenario] = all(
            any(int(_safe_dict(distribution[scenario][hazard].get(service_key)).get("total_units", 0)) > 0 for service_key in PUBLIC_SERVICE_KEYS)
            for hazard in HAZARD_KEYS
        )
    return distribution, scenario_availability, canonical_service_unit_counts


def _has_precomputed_network_distribution(graph_inputs: dict[str, Any]) -> bool:
    distribution = _safe_dict(graph_inputs.get("network_state_service_distribution_by_scenario"))
    return all(
        isinstance(_safe_dict(distribution.get(scenario)).get("storm"), dict)
        and isinstance(_safe_dict(distribution.get(scenario)).get("storm_cmcc"), dict)
        for scenario in SCENARIOS
    )


def _build_network_state_distribution_from_graph_inputs(
    graph_inputs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool], dict[str, dict[str, int]]]:
    distribution = {
        scenario: {
            hazard: {
                service_key: {
                    state: int(_safe_dict(_safe_dict(_safe_dict(graph_inputs.get("network_state_service_distribution_by_scenario")).get(scenario)).get(hazard)).get(service_key, {}).get(state, 0) or 0)
                    for state in (*STATE_CODES, "total_units")
                }
                for service_key in PUBLIC_SERVICE_KEYS
            }
            for hazard in HAZARD_KEYS
        }
        for scenario in SCENARIOS
    }
    unit_counts_block = _safe_dict(graph_inputs.get("network_state_service_unit_counts"))
    canonical_service_unit_counts = {
        hazard: {
            service_key: int(_safe_dict(unit_counts_block.get(hazard)).get(service_key, 0) or 0)
            for service_key in PUBLIC_SERVICE_KEYS
        }
        for hazard in HAZARD_KEYS
    }
    scenario_availability = {
        scenario: all(
            any(int(_safe_dict(distribution[scenario][hazard].get(service_key)).get("total_units", 0) or 0) > 0 for service_key in PUBLIC_SERVICE_KEYS)
            for hazard in HAZARD_KEYS
        )
        for scenario in SCENARIOS
    }
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
                    {"elec": "S0", "eau_aep": "S0", "eau_eu": "S0"},
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
                "total_without_eau_aep": 0.0,
                "total_without_eau_eu": 0.0,
                "total_without_eau": 0.0,
                "total_with_degraded_elec": 0.0,
                "total_with_degraded_eau_aep": 0.0,
                "total_with_degraded_eau_eu": 0.0,
                "state_breakdown": {
                    "elec": _empty_state_breakdown_row(),
                    "eau_aep": _empty_state_breakdown_row(),
                    "eau_eu": _empty_state_breakdown_row(),
                },
            }
            for cell_id, population in population_by_cell.items():
                if population <= 0:
                    continue
                states = worst_states[scenario][hazard].get(
                    cell_id,
                    {"elec": "S0", "eau_aep": "S0", "eau_eu": "S0"},
                )
                elec_state = _state_code(states.get("elec"))
                water_aep_state = _state_code(states.get("eau_aep"))
                water_eu_state = _state_code(states.get("eau_eu"))
                totals["state_breakdown"]["elec"][elec_state] += population
                totals["state_breakdown"]["eau_aep"][water_aep_state] += population
                totals["state_breakdown"]["eau_eu"][water_eu_state] += population
                if elec_state != "S0" or water_aep_state != "S0" or water_eu_state != "S0":
                    totals["total_population_affected_any_network"] += population
                if elec_state == "S3":
                    totals["total_without_elec"] += population
                if water_aep_state == "S3":
                    totals["total_without_eau_aep"] += population
                if water_eu_state == "S3":
                    totals["total_without_eau_eu"] += population
                if elec_state in {"S1", "S2"}:
                    totals["total_with_degraded_elec"] += population
                if water_aep_state in {"S1", "S2"}:
                    totals["total_with_degraded_eau_aep"] += population
                if water_eu_state in {"S1", "S2"}:
                    totals["total_with_degraded_eau_eu"] += population
            totals["total_without_eau"] = (
                float(totals["total_without_eau_aep"]) + float(totals["total_without_eau_eu"])
            )
            summary[scenario][hazard] = totals
            population_distribution[scenario][hazard] = totals["state_breakdown"]
    return summary, population_distribution, scenario_availability


def _has_precomputed_social_outputs(graph_inputs: dict[str, Any]) -> bool:
    summary = _safe_dict(graph_inputs.get("social_impact_by_scenario"))
    population_distribution = _safe_dict(graph_inputs.get("social_population_state_distribution_by_scenario"))
    return all(
        isinstance(_safe_dict(summary.get(scenario)).get("storm"), dict)
        and isinstance(_safe_dict(summary.get(scenario)).get("storm_cmcc"), dict)
        and isinstance(_safe_dict(population_distribution.get(scenario)).get("storm"), dict)
        and isinstance(_safe_dict(population_distribution.get(scenario)).get("storm_cmcc"), dict)
        for scenario in SCENARIOS
    )


def _build_social_impact_from_graph_inputs(
    graph_inputs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    summary = {
        scenario: {
            hazard: _safe_dict(_safe_dict(_safe_dict(graph_inputs.get("social_impact_by_scenario")).get(scenario)).get(hazard))
            for hazard in HAZARD_KEYS
        }
        for scenario in SCENARIOS
    }
    population_distribution = {
        scenario: {
            hazard: _safe_dict(_safe_dict(_safe_dict(graph_inputs.get("social_population_state_distribution_by_scenario")).get(scenario)).get(hazard))
            for hazard in HAZARD_KEYS
        }
        for scenario in SCENARIOS
    }
    scenario_availability = {
        scenario: all(
            bool(_safe_dict(summary[scenario].get(hazard))) and bool(_safe_dict(population_distribution[scenario].get(hazard)))
            for hazard in HAZARD_KEYS
        )
        for scenario in SCENARIOS
    }
    return summary, population_distribution, scenario_availability


def _scenario_breakdown_has_rows(value: Any) -> bool:
    block = _safe_dict(value)
    return bool(_safe_list(block.get("storm")) or _safe_list(block.get("storm_cmcc")))


def _build_scientific_graph_inputs(
    *,
    complete_analysis: dict[str, Any],
    network_state_distribution: dict[str, Any],
    network_service_unit_counts: dict[str, Any],
    social_summaries: dict[str, Any],
    social_population_distribution: dict[str, Any],
    network_state_availability: dict[str, bool],
    social_availability: dict[str, bool],
) -> dict[str, Any]:
    existing = _select_graph_inputs_from_complete_analysis(complete_analysis)
    existing_source = str(existing.get("source_of_truth") or "").strip()
    if existing_source and existing_source != "complete_analysis":
        raise ValueError(
            "complete-analysis graph inputs source_of_truth must be 'complete_analysis'"
        )

    existing_state_tables = _safe_dict(existing.get("state_damage_tables"))
    existing_breakdowns = _safe_dict(existing.get("damage_breakdown_by_scenario"))

    state_damage_tables: dict[str, list[dict[str, Any]]] = {
        scenario: _safe_list(existing_state_tables.get(scenario))
        for scenario in SCENARIOS
    }
    damage_breakdowns: dict[str, dict[str, list[dict[str, Any]]]] = {
        scenario: _safe_dict(existing_breakdowns.get(scenario)) or {"storm": [], "storm_cmcc": []}
        for scenario in SCENARIOS
    }

    scenario_availability: dict[str, dict[str, bool]] = {}
    for scenario in SCENARIOS:
        scenario_availability[scenario] = {
            "state_damage_tables": bool(state_damage_tables.get(scenario)),
            "damage_breakdown_by_scenario": _scenario_breakdown_has_rows(damage_breakdowns.get(scenario)),
            "social_impact_by_scenario": bool(social_availability.get(scenario)),
            "network_states": bool(network_state_availability.get(scenario)),
        }

    return {
        "source_of_truth": "complete_analysis",
        "event_selection_basis": EVENT_SELECTION_BASIS,
        "source_method": str(existing.get("method") or "strict_scientific_v4"),
        "source_schema_version": str(existing.get("schema_version") or "") or None,
        "approximation": bool(existing.get("approximation")),
        "scenarios": list(SCENARIOS),
        "state_damage_tables": state_damage_tables,
        "damage_breakdown_by_scenario": damage_breakdowns,
        "social_impact_by_scenario": {
            scenario: _safe_dict(social_summaries.get(scenario))
            for scenario in SCENARIOS
        },
        "social_population_state_distribution_by_scenario": {
            scenario: _safe_dict(social_population_distribution.get(scenario))
            for scenario in SCENARIOS
        },
        "network_state_service_distribution_by_scenario": {
            scenario: _safe_dict(network_state_distribution.get(scenario))
            for scenario in SCENARIOS
        },
        "network_state_service_unit_counts": {
            hazard: {
                service_key: int(_safe_dict(network_service_unit_counts.get(hazard)).get(service_key, 0) or 0)
                for service_key in PUBLIC_SERVICE_KEYS
            }
            for hazard in HAZARD_KEYS
        },
        "scenario_availability": scenario_availability,
    }


def _build_scientific_web_summary(
    complete_analysis: dict[str, Any],
    territory: str,
    *,
    network_states_geojson: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _safe_dict(complete_analysis.get("meta"))
    portfolio = _safe_dict(complete_analysis.get("portfolio_results"))
    existing_graph_inputs = _select_graph_inputs_from_complete_analysis(complete_analysis)

    portfolio_summary = _portfolio_summary(portfolio)
    has_network_state_geojson = _has_network_state_features(network_states_geojson)
    if has_network_state_geojson:
        network_state_distribution, network_state_availability, canonical_service_unit_counts = (
            _build_network_state_distribution_from_geojson(network_states_geojson)
        )
    elif _has_precomputed_network_distribution(existing_graph_inputs):
        network_state_distribution, network_state_availability, canonical_service_unit_counts = (
            _build_network_state_distribution_from_graph_inputs(existing_graph_inputs)
        )
    else:
        network_state_distribution, network_state_availability, canonical_service_unit_counts = (
            _build_network_state_distribution_from_geojson(network_states_geojson)
        )
    if has_network_state_geojson:
        social_summaries, social_population_distribution, social_availability = _build_social_impact_from_geojson(
            complete_analysis=complete_analysis,
            network_states_geojson=network_states_geojson,
        )
    elif _has_precomputed_social_outputs(existing_graph_inputs):
        social_summaries, social_population_distribution, social_availability = (
            _build_social_impact_from_graph_inputs(existing_graph_inputs)
        )
    else:
        social_summaries, social_population_distribution, social_availability = _build_social_impact_from_geojson(
            complete_analysis=complete_analysis,
            network_states_geojson=network_states_geojson,
        )
    scientific_graph_inputs = _build_scientific_graph_inputs(
        complete_analysis=complete_analysis,
        network_state_distribution=network_state_distribution,
        network_service_unit_counts=canonical_service_unit_counts,
        social_summaries=social_summaries,
        social_population_distribution=social_population_distribution,
        network_state_availability=network_state_availability,
        social_availability=social_availability,
    )
    state_damage_tables = _safe_dict(scientific_graph_inputs.get("state_damage_tables"))
    damage_breakdowns = _safe_dict(scientific_graph_inputs.get("damage_breakdown_by_scenario"))
    scenario_availability = _safe_dict(scientific_graph_inputs.get("scenario_availability"))

    summary_metrics = {
        "storm": {
            "rp10_total_loss_eur": _round2(portfolio_summary["storm"].get("rp10_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm"].get("rp100_eur")),
            "rp1000_total_loss_eur": _round2(portfolio_summary["storm"].get("rp1000_eur")),
        },
        "storm_cmcc": {
            "rp10_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp10_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp100_eur")),
            "rp1000_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp1000_eur")),
        },
    }

    scientific_summary = {
        "meta": {
            "territory": territory,
            "run_id": str(meta.get("run_id") or complete_analysis.get("run_id") or ""),
            "generated_at": datetime.now(UTC).isoformat(),
            "dynamic_max_tracks": meta.get("requested_dynamic_max_tracks"),
            "scientific_source": True,
            "schema_version": SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
            "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
            "source_artifact": f"{territory}-complete-analysis.json",
            "source_of_truth": "scientific_web_summary",
            "aggregation_unit": "scientific_service_unit",
            "scenarios": list(SCENARIOS),
            "comparability_guaranteed": True,
        },
        "portfolio_summary": portfolio_summary,
        "scientific_graph_inputs": scientific_graph_inputs,
        "network_damage_tables": {
            **{scenario: _safe_list(state_damage_tables.get(scenario)) for scenario in SCENARIOS},
            "scenario_availability": {
                scenario: (
                    "scientific_widget_contract"
                    if bool(_safe_dict(scenario_availability.get(scenario)).get("state_damage_tables"))
                    else "unavailable"
                )
                for scenario in SCENARIOS
            },
        },
        "component_breakdowns": {
            **{scenario: _safe_dict(damage_breakdowns.get(scenario)) for scenario in SCENARIOS},
        },
        "network_states": {
            "contract": {
                "source_of_truth": "scientific_web_summary",
                "aggregation_unit": "scientific_service_unit",
                "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
                "canonical_service_layer_keys": list(CANONICAL_SERVICE_LAYER_TO_KEY.keys()),
                "service_keys": list(PUBLIC_SERVICE_KEYS),
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
            "worst_case_native_service_states": _canonicalize_public_service_keys(_safe_dict(portfolio.get("network_states_native"))),
            "worst_case_projected_service_states": _canonicalize_public_service_keys(_safe_dict(portfolio.get("network_states_projected"))),
            "worst_case_projected_service_coverage": _canonicalize_public_service_keys(_safe_dict(portfolio.get("network_states_projected_coverage"))),
            "scenario_availability": network_state_availability,
        },
        "social_impact": {
            "scenario_summary": social_summaries,
            "scenario_population_state_distribution": social_population_distribution,
            "worst_case_summary": _canonicalize_public_service_keys(_safe_dict(portfolio.get("social_impact_summary"))),
            "worst_case_population_state_distribution": _canonicalize_public_service_keys(_safe_dict(portfolio.get("social_impact_population_state_distribution"))),
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
                "component_order": list(COMPONENT_ORDER),
                "summary_metrics": summary_metrics,
                "state_damage_tables": {
                    scenario: _safe_list(state_damage_tables.get(scenario))
                    for scenario in SCENARIOS
                },
                "damage_breakdown_by_scenario": {
                    scenario: _safe_dict(damage_breakdowns.get(scenario))
                    for scenario in SCENARIOS
                },
                "map_defaults": {"hazard": "storm", "scenario": "rp1000"},
            },
            "scenario_availability": {
                scenario: {
                    "damage_tables": bool(_safe_dict(scenario_availability.get(scenario)).get("state_damage_tables")),
                    "social_impact": bool(_safe_dict(scenario_availability.get(scenario)).get("social_impact_by_scenario")),
                    "network_states": bool(_safe_dict(scenario_availability.get(scenario)).get("network_states")),
                }
                for scenario in SCENARIOS
            },
        },
        "notes": [
            "Ce payload aligne les widgets web sur une source scientifique unique.",
            "Les totaux portefeuille proviennent du complete-analysis publie.",
            "Les distributions d etat reseau et les impacts sociaux par scenario sont recomptes depuis la couche canonique network-states.geojson.",
            "Les tableaux d impact front proviennent de complete_analysis.scientific_graph_inputs strict si disponible, sinon de complete_analysis.pml_network_graph_inputs.",
        ],
    }
    return scientific_summary


def build_scientific_web_summary(
    *,
    territory: str,
    complete_analysis_path: Path,
    out_path: Path,
    network_states_geojson_path: Path | None = None,
    repair_legacy_scientific_inputs: bool = False,
) -> Path:
    complete_analysis = _load_json(complete_analysis_path)
    has_pml_network_graph_inputs = _graph_inputs_have_required_rows(
        complete_analysis.get("pml_network_graph_inputs")
    )
    if needs_strict_scientific_rebuild(complete_analysis) and not has_pml_network_graph_inputs:
        if not repair_legacy_scientific_inputs:
            raise RuntimeError(
                "complete-analysis is missing strict V4 scientific_graph_inputs and PML-light network graph inputs; "
                "new runs must produce pml_network_graph_inputs natively before scientific publication. "
                "For archived/pre-V4 runs only, rerun this command with "
                "--repair-legacy-scientific-inputs."
            )
        rebuild_scientific_graph_inputs(
            territory=territory,
            complete_analysis_path=complete_analysis_path,
        )
        complete_analysis = _load_json(complete_analysis_path)
        archived_network_states_path = complete_analysis_path.parent / f"{territory}-network-states.geojson"
        if archived_network_states_path.exists():
            network_states_geojson_path = archived_network_states_path
    network_states_geojson = _load_optional_json(network_states_geojson_path)
    payload = _build_scientific_web_summary(
        complete_analysis,
        territory,
        network_states_geojson=network_states_geojson,
    )
    scientific_graph_inputs = _safe_dict(payload.get("scientific_graph_inputs"))
    if complete_analysis.get("scientific_graph_inputs") != scientific_graph_inputs:
        complete_analysis["scientific_graph_inputs"] = scientific_graph_inputs
        complete_analysis_path.write_text(
            json.dumps(complete_analysis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    default_complete_analysis_path = WEB_DATA_DIR / f"{territory}-complete-analysis.json"
    if complete_analysis_path.resolve() != default_complete_analysis_path.resolve() and default_complete_analysis_path.exists():
        default_complete_analysis = _load_json(default_complete_analysis_path)
        source_run_id = str(_safe_dict(complete_analysis.get("meta")).get("run_id") or "").strip()
        default_run_id = str(_safe_dict(default_complete_analysis.get("meta")).get("run_id") or "").strip()
        if source_run_id and default_run_id and source_run_id != default_run_id:
            raise RuntimeError(
                "Refusing to mirror scientific_graph_inputs to mutable web complete-analysis "
                f"because run_id differs: source={source_run_id} web={default_run_id}"
            )
        if default_complete_analysis.get("scientific_graph_inputs") != scientific_graph_inputs:
            default_complete_analysis["scientific_graph_inputs"] = scientific_graph_inputs
            default_complete_analysis_path.write_text(
                json.dumps(default_complete_analysis, ensure_ascii=False, indent=2),
                encoding="utf-8",
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
    parser.add_argument(
        "--repair-legacy-scientific-inputs",
        action="store_true",
        help=(
            "Explicitly repair archived/pre-V4 complete-analysis payloads by running the "
            "heavy scientific_graph_postprocess reconstruction. New V4 runs should not use this."
        ),
    )
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
    build_scientific_web_summary(
        territory=territory,
        complete_analysis_path=complete_analysis_path,
        out_path=out_path,
        network_states_geojson_path=network_states_geojson_path,
        repair_legacy_scientific_inputs=bool(args.repair_legacy_scientific_inputs),
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
