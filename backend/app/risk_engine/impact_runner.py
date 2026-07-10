from __future__ import annotations

from collections import defaultdict
from hashlib import blake2b
import logging
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..config import Settings, load_settings
from .climada_engine import ClimadaRunResult, HazardImpactResult, RETURN_PERIODS, run_climada_direct_impacts
from .exposure_to_climada import ClimadaExposureBundle, build_climada_exposure, validate_exposure_geometry_contract
from .impact_functions import resolve_tc_impact_func_id
from .interdependency import aggregate_impacts_with_interdependency
from .population_loader import load_population_data, get_population_for_cell
from .social_impact import (
    aggregate_population_state_distribution_by_territory,
    aggregate_population_state_distribution_summary,
    aggregate_social_metrics_by_territory,
    aggregate_social_summary,
    build_social_impact_summary_payload,
    calculate_population_state_distribution,
    calculate_social_impact_metrics,
    SOCIAL_IMPACT_SUMMARY_BASIS,
)
from .types import DisaggregationSummary, ImpactComputationResult, NormalizedExposure

logger = logging.getLogger(__name__)


TERRITORY_GRID_DEG = 0.2
HAZARD_KEYS = ("storm", "storm_cmcc")
STATE_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
STATE_DAMAGE_FLOOR = {"S0": 0.0, "S1": 0.07, "S2": 0.2, "S3": 0.45}
PML_NETWORK_GRAPH_SCHEMA_VERSION = "pml_network_graph_inputs_v1"
PML_NETWORK_SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
RETURN_PERIOD_BY_PML_SCENARIO = {"rp10": 10, "rp50": 50, "rp100": 100, "rp1000": 1000}
PML_FIELD_BY_SCENARIO = {
    "rp10": "pml_10_eur",
    "rp50": "pml_50_eur",
    "rp100": "pml_100_eur",
    "rp1000": "pml_1000_eur",
}
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
PUBLIC_SERVICE_KEYS = ("eau_aep", "eau_eu", "elec")
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
WATER_BLOCKING_ROLES_BY_PUBLIC_SERVICE = {
    "eau_aep": frozenset({"captage_aep", "upep_aep", "pompage_aep"}),
    "eau_eu": frozenset({"step", "poste_refoulement"}),
}
ANNUALIZATION_FACTOR = {"storm": 0.22, "storm_cmcc": 0.25}
CMCC_DAMAGE_SCALER = 1.24
DIRECT_CLASS_FACTOR = {
    "elec_aerien": 1.2,
    "elec_souterrain": 0.75,
    "eau_reseau": 0.95,
    "eau_ouvrage": 1.08,
    "habitation": 0.82,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _state_from_damage_ratio(damage_ratio: float) -> str:
    if damage_ratio >= 0.35:
        return "S3"
    if damage_ratio >= 0.15:
        return "S2"
    if damage_ratio >= 0.05:
        return "S1"
    return "S0"


def _dependency_state_from_elec_health(health: float) -> str:
    if health < 0.35:
        return "S3"
    if health < 0.55:
        return "S2"
    if health < 0.75:
        return "S1"
    return "S0"


def _iter_lines_from_coords(coords: Any) -> list[list[tuple[float, float]]]:
    lines: list[list[tuple[float, float]]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, (list, tuple)) or not node:
            return
        first = node[0]
        if (
            isinstance(first, (list, tuple))
            and first
            and len(first) >= 2
            and isinstance(first[0], (int, float))
            and isinstance(first[1], (int, float))
        ):
            line: list[tuple[float, float]] = []
            for pt in node:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2 and isinstance(pt[0], (int, float)) and isinstance(pt[1], (int, float)):
                    line.append((float(pt[0]), float(pt[1])))
            if len(line) >= 2:
                lines.append(line)
            return
        for child in node:
            walk(child)

    walk(coords)
    return lines


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2) + math.cos(lat1r) * math.cos(lat2r) * (math.sin(dlon / 2.0) ** 2)
    return r * (2.0 * math.asin(math.sqrt(a)))


def _feature_weight(feature: Any) -> float:
    gtype = str(feature.geometry_type or "").lower()
    if "line" in gtype and feature.geometry_geojson and isinstance(feature.geometry_geojson, dict):
        coords = feature.geometry_geojson.get("coordinates")
        if coords is not None:
            total_km = 0.0
            for line in _iter_lines_from_coords(coords):
                for i in range(len(line) - 1):
                    lon1, lat1 = line[i]
                    lon2, lat2 = line[i + 1]
                    total_km += _haversine_km(lon1, lat1, lon2, lat2)
            if total_km > 0:
                return total_km
    if "polygon" in gtype:
        return 3.0
    return 1.0


def _infer_infra_class(feature: Any) -> str:
    category = str(getattr(feature, "exposure_category", "habitation") or "habitation").strip().lower()
    props = getattr(feature, "properties", {}) or {}
    asset_type = str(props.get("asset_type") or "").strip().lower()
    gtype = str(getattr(feature, "geometry_type", "")).lower()

    if category == "ouvrage_electrique":
        if "souterrain" in asset_type or "underground" in asset_type:
            return "elec_souterrain"
        return "elec_aerien"

    if category == "ouvrage_eau":
        if (
            "step" in asset_type
            or "station" in asset_type
            or "stpmp" in asset_type
            or asset_type.startswith("pr")
            or "ouvrage" in asset_type
            or "point" in gtype
        ):
            return "eau_ouvrage"
        return "eau_reseau"

    return "habitation"


def _territory_for_feature(feature: Any) -> tuple[str, str, float | None, float | None]:
    lat = getattr(feature, "lat", None)
    lon = getattr(feature, "lon", None)
    if lat is None or lon is None:
        return "uploaded-aggregate", "Uploaded Exposure (aggregate)", None, None

    lat_bin = round(float(lat) / TERRITORY_GRID_DEG) * TERRITORY_GRID_DEG
    lon_bin = round(float(lon) / TERRITORY_GRID_DEG) * TERRITORY_GRID_DEG
    return (
        f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}",
        f"Zone ({lat_bin:.2f}, {lon_bin:.2f})",
        float(lat),
        float(lon),
    )


def _resolve_electric_health_for_territory(
    *,
    hazard: str,
    territory_id: str,
    lat: float | None,
    lon: float | None,
    elec_health_by_territory: dict[str, dict[str, float]],
    elec_health_global: dict[str, float],
    elec_territory_centroids: dict[str, tuple[float, float]],
) -> tuple[float, str]:
    by_territory = elec_health_by_territory.get(hazard, {})
    if territory_id in by_territory:
        return float(by_territory[territory_id]), "local_territory"

    if lat is not None and lon is not None and elec_territory_centroids:
        nearest_tid: str | None = None
        nearest_dist: float | None = None
        for candidate_tid, (cand_lat, cand_lon) in elec_territory_centroids.items():
            if candidate_tid not in by_territory:
                continue
            dist = _haversine_km(float(lon), float(lat), float(cand_lon), float(cand_lat))
            if (
                nearest_dist is None
                or dist < nearest_dist
                or (abs(dist - nearest_dist) <= 1e-12 and nearest_tid is not None and candidate_tid < nearest_tid)
            ):
                nearest_tid = candidate_tid
                nearest_dist = dist
        if nearest_tid is not None:
            return float(by_territory[nearest_tid]), "nearest_territory"

    return float(elec_health_global.get(hazard, 1.0)), "global"


def _stable_factor(seed: str, lo: float, hi: float) -> float:
    digest = blake2b(seed.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, byteorder="big", signed=False) / float(2**64)
    return lo + (hi - lo) * raw


def _direct_damage_ratio(feature: Any, hazard_key: str, base_damage: float) -> float:
    infra_class = _infer_infra_class(feature)
    class_factor = DIRECT_CLASS_FACTOR.get(infra_class, 1.0)
    hazard_factor = CMCC_DAMAGE_SCALER if hazard_key == "storm_cmcc" else 1.0
    spatial_factor = _stable_factor(
        f"{getattr(feature, 'feature_id', 'x')}|{hazard_key}|{infra_class}",
        0.82,
        1.18,
    )
    return _clamp(base_damage * class_factor * hazard_factor * spatial_factor, 0.0, 0.95)


def _new_state_bucket() -> dict[str, float]:
    return {"total": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0, "asset_count": 0.0}


def _bucket_add_state(bucket: dict[str, float], *, state: str, weight: float) -> None:
    bucket["total"] += float(weight)
    bucket["asset_count"] += 1.0
    if state in {"S1", "S2", "S3"}:
        bucket[state] += float(weight)


def _health_from_bucket(bucket: dict[str, float]) -> float:
    total = float(bucket.get("total", 0.0))
    if total <= 0:
        return 1.0
    weighted_damage = (
        0.3 * float(bucket.get("S1", 0.0))
        + 0.7 * float(bucket.get("S2", 0.0))
        + 1.0 * float(bucket.get("S3", 0.0))
    )
    return _clamp(1.0 - (weighted_damage / total), 0.0, 1.0)


def _summarize_component_health(
    buckets_by_class: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for infra_class, bucket in buckets_by_class.items():
        total = float(bucket.get("total", 0.0))
        s1 = float(bucket.get("S1", 0.0))
        s2 = float(bucket.get("S2", 0.0))
        s3 = float(bucket.get("S3", 0.0))
        out[infra_class] = {
            "health": round(_health_from_bucket(bucket), 4),
            "L_total": round(total, 4),
            "L_S1": round(s1, 4),
            "L_S2": round(s2, 4),
            "L_S3": round(s3, 4),
            "asset_count": int(bucket.get("asset_count", 0.0)),
        }
    return out


def _build_fec_curve(total_exposure_eur: float, ratio: float, lifetime_years: int | None = None) -> dict[str, Any]:
    return_periods = [int(rp) for rp in RETURN_PERIODS]
    curve_y: list[float] = []
    for rp in return_periods:
        damp = 1.0 / math.sqrt(max(1.0, rp))
        life_factor = 1.0
        if lifetime_years:
            life_factor = 1.0 + (lifetime_years / 100.0) * 0.35
        curve_y.append(total_exposure_eur * ratio * damp * life_factor)
    return {
        "return_period_years": return_periods,
        "damage_eur": [round(v, 2) for v in curve_y],
    }


def _build_fallback_graphs(total_exposure: float, storm_ratio: float, cmcc_ratio: float) -> dict[str, Any]:
    bins = [20, 30, 40, 50, 60, 70, 80]
    base_hist = [6, 18, 24, 20, 16, 10, 6]
    cmcc_hist = [4, 12, 22, 24, 20, 12, 8]

    def hazard_graphs(name: str, hist_vals: list[int], ratio: float) -> dict[str, Any]:
        return {
            "wind_year_hist": {
                "title": f"{name} - Max wind per year",
                "bins_mps": bins,
                "percent": hist_vals,
            },
            "wind_track_hist": {
                "title": f"{name} - Max wind per track",
                "bins_mps": bins,
                "percent": [max(0, v - 2) for v in hist_vals],
            },
            "annual_fec": {
                "title": f"{name} - Annual frequency-exceedance curve",
                **_build_fec_curve(total_exposure, ratio, lifetime_years=None),
                "y_scale": "linear",
            },
            "lifetime_fec": {
                "title": f"{name} - Lifetime FEC (30y / 50y)",
                "series": [
                    {"name": "30-year FEC", **_build_fec_curve(total_exposure, ratio, lifetime_years=30)},
                    {"name": "50-year FEC", **_build_fec_curve(total_exposure, ratio, lifetime_years=50)},
                ],
                "y_scale": "log",
            },
        }

    return {
        "storm": hazard_graphs("STORM", base_hist, storm_ratio),
        "storm_cmcc": hazard_graphs("STORM_CMCC", cmcc_hist, cmcc_ratio),
        "comparison": {
            "side_by_side": {
                "hazards": ["STORM", "STORM_CMCC"],
                "metrics": ["annual_eai", "pml_1000"],
                "values": {
                    "annual_eai": [round(total_exposure * storm_ratio, 2), round(total_exposure * cmcc_ratio, 2)],
                    "pml_1000": [round(total_exposure * storm_ratio * 4.5, 2), round(total_exposure * cmcc_ratio * 4.9, 2)],
                },
            }
        },
    }


def _build_hist_percent(values: list[float], bins_count: int = 7) -> tuple[list[float], list[float]]:
    cleaned = [max(0.0, float(v)) for v in values if isinstance(v, (int, float))]
    if not cleaned:
        return [0.0] * bins_count, [0.0] * bins_count
    v_min = min(cleaned)
    v_max = max(cleaned)
    if v_max <= v_min:
        return [round(v_max, 4)] * bins_count, ([100.0] + [0.0] * (bins_count - 1))
    width = (v_max - v_min) / bins_count
    bins = [v_min + width * (i + 1) for i in range(bins_count)]
    counts = [0] * bins_count
    for value in cleaned:
        idx = int((value - v_min) / width)
        if idx >= bins_count:
            idx = bins_count - 1
        counts[idx] += 1
    total = max(1, sum(counts))
    perc = [round((c / total) * 100.0, 2) for c in counts]
    return [round(b, 4) for b in bins], perc


def _build_climada_graphs(
    climada_result: ClimadaRunResult,
    scaler_by_hazard: dict[str, float],
    portfolio_results: dict[str, Any],
) -> dict[str, Any]:
    def hazard_graph(hazard_key: str, label: str) -> dict[str, Any]:
        raw = climada_result.hazards[hazard_key]
        scaler = float(scaler_by_hazard.get(hazard_key, 1.0))
        losses = [float(v) * scaler for v in list(raw.at_event_loss)]
        bins1, perc1 = _build_hist_percent(losses, bins_count=7)
        bins2, perc2 = _build_hist_percent([math.sqrt(v) if v > 0.0 else 0.0 for v in losses], bins_count=7)

        annual_rp = [int(rp) for rp in RETURN_PERIODS]
        annual_dmg = [round(float(raw.pml_eur.get(rp, 0.0)) * scaler, 2) for rp in annual_rp]
        fec30 = [round(v * 1.105, 2) for v in annual_dmg]
        fec50 = [round(v * 1.175, 2) for v in annual_dmg]
        return {
            "wind_year_hist": {
                "title": f"{label} - Event loss distribution",
                "bins_mps": bins1,
                "percent": perc1,
            },
            "wind_track_hist": {
                "title": f"{label} - Event loss intensity proxy",
                "bins_mps": bins2,
                "percent": perc2,
            },
            "annual_fec": {
                "title": f"{label} - Annual frequency-exceedance curve",
                "return_period_years": annual_rp,
                "damage_eur": annual_dmg,
                "y_scale": "linear",
            },
            "lifetime_fec": {
                "title": f"{label} - Lifetime FEC (30y / 50y)",
                "series": [
                    {"name": "30-year FEC", "return_period_years": annual_rp, "damage_eur": fec30},
                    {"name": "50-year FEC", "return_period_years": annual_rp, "damage_eur": fec50},
                ],
                "y_scale": "log",
            },
        }

    return {
        "storm": hazard_graph("storm", "STORM"),
        "storm_cmcc": hazard_graph("storm_cmcc", "STORM_CMCC"),
        "comparison": {
            "side_by_side": {
                "hazards": ["STORM", "STORM_CMCC"],
                "metrics": ["annual_eai", "pml_1000"],
                "values": {
                    "annual_eai": [
                        round(float((portfolio_results.get("storm") or {}).get("eai_eur", 0.0)), 2),
                        round(float((portfolio_results.get("storm_cmcc") or {}).get("eai_eur", 0.0)), 2),
                    ],
                    "pml_1000": [
                        round(float((portfolio_results.get("storm") or {}).get("pml_1000_eur", 0.0)), 2),
                        round(float((portfolio_results.get("storm_cmcc") or {}).get("pml_1000_eur", 0.0)), 2),
                    ],
                },
            }
        },
    }


def _scale_top_events(events: list[dict[str, Any]], scaler: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        item = dict(event)
        item["loss_eur"] = round(max(0.0, float(event.get("loss_eur", 0.0))) * scaler, 2)
        out.append(item)
    return out


def _to_float_list(values: Any, expected_len: int) -> list[float]:
    out = [max(0.0, float(v)) for v in list(values)]
    if len(out) < expected_len:
        out.extend([0.0] * (expected_len - len(out)))
    if len(out) > expected_len:
        out = out[:expected_len]
    return out


def _pml_asset_type(record: dict[str, Any]) -> str:
    return str(record.get("asset_type") or "").strip().lower()


def _pml_network_class_from_point(record: dict[str, Any]) -> str | None:
    return ASSET_TYPE_TO_NETWORK_CLASS.get(_pml_asset_type(record))


def _pml_breakdown_class_from_point(record: dict[str, Any]) -> str | None:
    asset_type = _pml_asset_type(record)
    if asset_type.startswith("eau_aep_ouvrage_"):
        return "eau_aep_ouvrages"
    if asset_type == "eau_eu_pr":
        return "eau_eu_pr"
    if asset_type == "eau_eu_step":
        return "eau_eu_step"
    return ASSET_TYPE_TO_NETWORK_CLASS.get(asset_type)


def _pml_water_service_class_from_point(record: dict[str, Any]) -> str | None:
    asset_type = _pml_asset_type(record)
    if asset_type.startswith("eau_aep"):
        return "eau_aep"
    if asset_type.startswith("eau_eu"):
        return "eau_eu"
    return None


def _pml_service_feature_id_from_point(record: dict[str, Any]) -> str:
    for key in ("service_feature_id", "zone_component_key", "feature_id", "territory_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _pml_electric_unit_id_from_point(record: dict[str, Any]) -> str:
    lat = record.get("lat")
    lon = record.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        lat_bin = round(float(lat) / 0.1) * 0.1
        lon_bin = round(float(lon) / 0.1) * 0.1
        return f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}"
    return str(record.get("territory_id") or record.get("feature_id") or "")


def _pml_public_service_key(record: dict[str, Any], network_class: str | None) -> str | None:
    if isinstance(network_class, str) and network_class.startswith("elec_"):
        return "elec"
    water_service = _pml_water_service_class_from_point(record)
    if water_service in {"eau_aep", "eau_eu"}:
        return water_service
    return None


def _pml_is_water_service_network_point(record: dict[str, Any]) -> bool:
    return _pml_network_class_from_point(record) in {"eau_aep", "eau_eu"}


def _pml_is_blocking_water_asset_point(record: dict[str, Any]) -> bool:
    water_service = _pml_water_service_class_from_point(record)
    if water_service is None:
        return False
    if str(record.get("infra_class") or "").strip().lower() != "eau_ouvrage":
        return False
    role = str(record.get("feature_role") or "").strip().lower()
    return role in WATER_BLOCKING_ROLES_BY_PUBLIC_SERVICE.get(water_service, frozenset())


def _pml_state_counts_row() -> dict[str, int]:
    return {"S0": 0, "S1": 0, "S2": 0, "S3": 0, "total_units": 0}


def _pml_normalize_component_ratio_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out = {component: 0.0 for component in COMPONENT_ORDER}
    for component, value in (raw or {}).items():
        key = str(component or "").strip()
        if key not in out:
            continue
        try:
            out[key] = max(0.0, float(value or 0.0))
        except Exception:
            out[key] = 0.0
    total = float(sum(out.values()))
    if total <= 0.0:
        return {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0}
    return {component: float(value) / total for component, value in out.items()}


def _pml_component_ratios_for_scenario(
    component_hazards: dict[str, HazardImpactResult],
    scenario: str,
) -> dict[str, float]:
    period = RETURN_PERIOD_BY_PML_SCENARIO.get(str(scenario))
    raw: dict[str, float] = {}
    for component in COMPONENT_ORDER:
        metrics = component_hazards.get(component)
        if metrics is None:
            raw[component] = 0.0
            continue
        if period is None:
            value = float(getattr(metrics, "aai_agg_eur", 0.0) or 0.0)
        else:
            value = float((getattr(metrics, "pml_eur", {}) or {}).get(int(period), 0.0) or 0.0)
        raw[component] = max(0.0, value)
    return _pml_normalize_component_ratio_map(raw)


def _pml_allocate_damage_components(total_eur: float, ratios: dict[str, float]) -> dict[str, float]:
    total = max(0.0, float(total_eur or 0.0))
    normalized = _pml_normalize_component_ratio_map(ratios)
    assigned = 0.0
    out: dict[str, float] = {}
    for idx, component in enumerate(COMPONENT_ORDER):
        if idx == len(COMPONENT_ORDER) - 1:
            value = max(0.0, total - assigned)
        else:
            value = round(total * float(normalized.get(component, 0.0)), 2)
            assigned += value
        out[component] = round(value, 2)
    return out


def _pml_rescale_loss_array_to_total(np: Any, losses: Any, capacities: Any, target_total: float) -> Any:
    loss_arr = np.asarray(losses, dtype=float).reshape(-1)
    cap_arr = np.maximum(np.asarray(capacities, dtype=float).reshape(-1), 0.0)
    if loss_arr.size != cap_arr.size:
        raise ValueError("losses and capacities must share the same shape")
    current = np.minimum(np.maximum(loss_arr, 0.0), cap_arr)
    target = max(0.0, float(target_total))
    capacity_total = float(cap_arr.sum())
    if current.size == 0 or target <= 0.0 or capacity_total <= 0.0:
        return np.zeros_like(current)
    if target >= capacity_total:
        return np.array(cap_arr, dtype=float, copy=True)
    current_total = float(current.sum())
    if abs(current_total - target) <= 1e-6:
        return current
    if current_total <= 0.0:
        return cap_arr * (target / capacity_total)
    lo = 0.0
    hi = max(1.0, target / max(current_total, 1e-12))
    for _ in range(32):
        if float(np.minimum(current * hi, cap_arr).sum()) >= target:
            break
        hi *= 2.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        total = float(np.minimum(current * mid, cap_arr).sum())
        if total < target:
            lo = mid
        else:
            hi = mid
    scaled = np.minimum(current * hi, cap_arr)
    residual = target - float(scaled.sum())
    if residual > 1e-6:
        remaining = np.maximum(cap_arr - scaled, 0.0)
        remaining_total = float(remaining.sum())
        if remaining_total > 0.0:
            scaled = scaled + (remaining * min(1.0, residual / remaining_total))
    return np.minimum(np.maximum(scaled, 0.0), cap_arr)


def _pml_allocate_direct_loss_by_class(
    np: Any,
    *,
    prior_direct: Any,
    values: Any,
    breakdown_class_keys: list[str | None],
    target_total: float,
) -> Any:
    prior = np.minimum(np.maximum(np.asarray(prior_direct, dtype=float).reshape(-1), 0.0), values)
    caps = np.maximum(np.asarray(values, dtype=float).reshape(-1), 0.0)
    target = max(0.0, float(target_total))
    if prior.size == 0 or target <= 0.0:
        return np.zeros_like(prior)

    annual_by_class: dict[str, float] = {}
    exposure_by_class: dict[str, float] = {}
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        mask = np.asarray([ck == class_key for ck in breakdown_class_keys], dtype=bool)
        annual_by_class[class_key] = float(prior[mask].sum()) if mask.any() else 0.0
        exposure_by_class[class_key] = float(caps[mask].sum()) if mask.any() else 0.0
    annual_total = float(sum(annual_by_class.values()))
    exposure_total = float(sum(exposure_by_class.values()))

    allocated = np.zeros_like(prior)
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        mask = np.asarray([ck == class_key for ck in breakdown_class_keys], dtype=bool)
        if not mask.any():
            continue
        if annual_total > 0.0:
            class_share = annual_by_class[class_key] / annual_total
        elif exposure_total > 0.0:
            class_share = exposure_by_class[class_key] / exposure_total
        else:
            class_share = 0.0
        class_target = target * max(0.0, float(class_share))
        class_prior = prior[mask]
        if float(class_prior.sum()) <= 0.0:
            class_prior = caps[mask]
        allocated[mask] = _pml_rescale_loss_array_to_total(np, class_prior, caps[mask], class_target)
    infra_mask = np.asarray([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
    allocated[infra_mask] = _pml_rescale_loss_array_to_total(
        np,
        allocated[infra_mask],
        caps[infra_mask],
        target,
    )
    return np.minimum(np.maximum(allocated, 0.0), caps)


def _pml_health_from_bucket(bucket: dict[str, float]) -> float:
    total = float(bucket.get("total", 0.0))
    if total <= 0.0:
        return 1.0
    weighted = 0.3 * float(bucket.get("S1", 0.0)) + 0.7 * float(bucket.get("S2", 0.0)) + float(bucket.get("S3", 0.0))
    return max(0.0, min(1.0, 1.0 - (weighted / total)))


def _pml_add_state(bucket: dict[str, float], state: str, weight: float) -> None:
    bucket["total"] += float(weight)
    if state in {"S1", "S2", "S3"}:
        bucket[state] += float(weight)


def _pml_empty_health_bucket() -> dict[str, float]:
    return {"total": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}


def _pml_evaluate_network_scenario(
    np: Any,
    *,
    direct_loss: Any,
    values: Any,
    point_records: list[dict[str, Any]],
    network_class_keys: list[str | None],
    breakdown_class_keys: list[str | None],
    weights_km: Any,
) -> dict[str, Any]:
    del breakdown_class_keys
    direct = np.minimum(np.maximum(np.asarray(direct_loss, dtype=float).reshape(-1), 0.0), values)
    caps = np.maximum(np.asarray(values, dtype=float).reshape(-1), 0.0)
    ratios = np.divide(direct, np.maximum(caps, 1.0))
    direct_state = np.asarray([_state_from_damage_ratio(float(value)) for value in ratios], dtype=object)

    territories = [str(record.get("territory_id") or "uploaded-aggregate") for record in point_records]
    water_service_classes = [_pml_water_service_class_from_point(record) for record in point_records]
    service_feature_ids = [_pml_service_feature_id_from_point(record) for record in point_records]
    service_network_flags = [_pml_is_water_service_network_point(record) for record in point_records]
    blocking_flags = [_pml_is_blocking_water_asset_point(record) for record in point_records]

    elec_buckets: dict[str, dict[str, float]] = defaultdict(_pml_empty_health_bucket)
    for idx, class_key in enumerate(network_class_keys):
        if not isinstance(class_key, str) or not class_key.startswith("elec_"):
            continue
        _pml_add_state(elec_buckets[territories[idx]], str(direct_state[idx]), float(weights_km[idx]))
    global_bucket = _pml_empty_health_bucket()
    for bucket in elec_buckets.values():
        for key, value in bucket.items():
            global_bucket[key] += float(value)
    elec_health = {territory: _pml_health_from_bucket(bucket) for territory, bucket in elec_buckets.items()}
    global_health = _pml_health_from_bucket(global_bucket)

    dependency_state: list[str] = []
    state_after_dependency: list[str] = []
    for idx, direct_code in enumerate(direct_state):
        dep_code = "S0"
        if water_service_classes[idx] in {"eau_aep", "eau_eu"}:
            dep_code = _dependency_state_from_elec_health(elec_health.get(territories[idx], global_health))
        dependency_state.append(dep_code)
        direct_txt = str(direct_code)
        state_after_dependency.append(dep_code if STATE_ORDER[dep_code] > STATE_ORDER[direct_txt] else direct_txt)

    blocking_state_by_service: dict[str, str] = {}
    for idx, is_blocking in enumerate(blocking_flags):
        if not is_blocking:
            continue
        service_feature_id = service_feature_ids[idx]
        if not service_feature_id:
            continue
        candidate = state_after_dependency[idx]
        current = blocking_state_by_service.get(service_feature_id, "S0")
        if STATE_ORDER[candidate] > STATE_ORDER[current]:
            blocking_state_by_service[service_feature_id] = candidate

    final_state: list[str] = []
    blocking_state: list[str] = []
    cause: list[str] = []
    direct_component = np.array(direct, dtype=float, copy=True)
    dysfunction_component = np.zeros_like(direct_component)
    blocking_component = np.zeros_like(direct_component)
    total_loss = np.array(direct, dtype=float, copy=True)
    indirect_s3_flag = np.zeros_like(direct_component, dtype=bool)

    for idx, dep_or_direct in enumerate(state_after_dependency):
        final_code = str(dep_or_direct)
        blocker_code = "S0"
        if service_network_flags[idx]:
            blocker_code = blocking_state_by_service.get(service_feature_ids[idx], "S0")
            if STATE_ORDER[blocker_code] > STATE_ORDER[final_code]:
                final_code = blocker_code
        blocking_state.append(blocker_code)
        final_state.append(final_code)
        direct_code = str(direct_state[idx])
        indirect_s3_flag[idx] = final_code == "S3" and direct_code != "S3"
        if STATE_ORDER[final_code] <= 0:
            cause_code = "none"
        elif STATE_ORDER[direct_code] >= STATE_ORDER[final_code]:
            cause_code = "direct_damage"
        elif STATE_ORDER[blocker_code] >= STATE_ORDER[final_code] and service_network_flags[idx]:
            cause_code = "blocking_ouvrage"
        else:
            cause_code = "electric_dependency"
        cause.append(cause_code)

        if STATE_ORDER[final_code] > STATE_ORDER[direct_code]:
            proxy_total = max(float(total_loss[idx]), float(caps[idx]) * float(STATE_DAMAGE_FLOOR.get(final_code, 0.0)))
            proxy_total = min(float(caps[idx]), proxy_total)
            extra = max(0.0, proxy_total - float(direct_component[idx]))
            total_loss[idx] = proxy_total
            if cause_code == "blocking_ouvrage":
                blocking_component[idx] = extra
            else:
                dysfunction_component[idx] = extra

    return {
        "direct_loss": direct_component,
        "dysfunction_loss": dysfunction_component,
        "blocking_loss": blocking_component,
        "total_loss": np.minimum(np.maximum(total_loss, 0.0), caps),
        "direct_state": direct_state,
        "dependency_state": np.asarray(dependency_state, dtype=object),
        "blocking_state": np.asarray(blocking_state, dtype=object),
        "final_state": np.asarray(final_state, dtype=object),
        "dominant_outage_cause": np.asarray(cause, dtype=object),
        "indirect_s3_flag": indirect_s3_flag,
    }


def _pml_calibrate_network_scenario(
    np: Any,
    scenario_result: dict[str, Any],
    *,
    values: Any,
    target_total: float,
) -> dict[str, float]:
    total = np.asarray(scenario_result.get("total_loss"), dtype=float).reshape(-1)
    caps = np.asarray(values, dtype=float).reshape(-1)
    pre_total = float(total.sum())
    scaled_total = _pml_rescale_loss_array_to_total(np, total, caps, target_total)
    scale = np.divide(
        scaled_total,
        np.maximum(total, 1e-12),
        out=np.zeros_like(scaled_total),
        where=total > 0.0,
    )
    for key in ("direct_loss", "dysfunction_loss", "blocking_loss"):
        arr = np.asarray(scenario_result.get(key), dtype=float).reshape(-1)
        if arr.size != scaled_total.size:
            continue
        scaled = np.minimum(np.maximum(arr * scale, 0.0), scaled_total)
        zero_support = (total <= 0.0) & (scaled_total > 0.0) & (key == "direct_loss")
        if zero_support.any():
            scaled[zero_support] = scaled_total[zero_support]
        scenario_result[key] = scaled
    direct = np.asarray(scenario_result.get("direct_loss"), dtype=float).reshape(-1)
    dysfunction = np.asarray(scenario_result.get("dysfunction_loss"), dtype=float).reshape(-1)
    blocking = np.asarray(scenario_result.get("blocking_loss"), dtype=float).reshape(-1)
    indirect = np.maximum(dysfunction + blocking, 0.0)
    overflow = np.maximum(direct + indirect - scaled_total, 0.0)
    if overflow.any():
        indirect_total = np.maximum(indirect, 1e-12)
        dysfunction = np.maximum(dysfunction - overflow * (dysfunction / indirect_total), 0.0)
        blocking = np.maximum(blocking - overflow * (blocking / indirect_total), 0.0)
    scenario_result["direct_loss"] = np.minimum(direct, scaled_total)
    scenario_result["dysfunction_loss"] = dysfunction
    scenario_result["blocking_loss"] = blocking
    scenario_result["total_loss"] = scaled_total
    return {
        "pre_calibration_total_eur": round(pre_total, 2),
        "target_total_eur": round(float(target_total), 2),
        "post_calibration_total_eur": round(float(scaled_total.sum()), 2),
    }


def _pml_state_pct_for_mask(np: Any, states: Any, weights: Any, mask: Any) -> dict[str, float]:
    total = float(np.asarray(weights, dtype=float)[mask].sum())
    if total <= 0.0:
        count = int(np.asarray(mask, dtype=bool).sum())
        if count <= 0:
            return {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}
        total = float(count)
        local_weights = np.ones_like(np.asarray(weights, dtype=float)[mask])
    else:
        local_weights = np.asarray(weights, dtype=float)[mask]
    local_states = np.asarray(states, dtype=object)[mask]
    return {
        state: round(float(local_weights[local_states == state].sum()) / total * 100.0, 3)
        for state in ("S0", "S1", "S2", "S3")
    }


def _build_pml_network_graph_inputs(
    np: Any,
    *,
    point_records: list[dict[str, Any]],
    hazard_direct_eai: dict[str, list[float]],
    portfolio_results: dict[str, Any],
    component_hazards: dict[str, dict[str, HazardImpactResult]],
    state_aggregation_metadata: dict[str, Any],
    modeling: dict[str, Any],
) -> dict[str, Any]:
    values = np.asarray([max(0.0, float(record.get("value_eur") or 0.0)) for record in point_records], dtype=float)
    network_class_keys = [_pml_network_class_from_point(record) for record in point_records]
    breakdown_class_keys = [_pml_breakdown_class_from_point(record) for record in point_records]
    weights_km = np.asarray(
        [
            max(0.0, float(record.get("length_km") or 0.0))
            or max(0.0, float(record.get("value_eur") or 0.0))
            for record in point_records
        ],
        dtype=float,
    )
    all_infra_mask = np.asarray([class_key in DAMAGE_BREAKDOWN_LABELS for class_key in breakdown_class_keys], dtype=bool)

    state_damage_tables: dict[str, list[dict[str, Any]]] = {scenario: [] for scenario in PML_NETWORK_SCENARIOS}
    damage_breakdown_by_scenario: dict[str, dict[str, list[dict[str, Any]]]] = {
        scenario: {hazard: [] for hazard in HAZARD_KEYS}
        for scenario in PML_NETWORK_SCENARIOS
    }
    network_distribution: dict[str, dict[str, dict[str, dict[str, int]]]] = {
        scenario: {hazard: {service: _pml_state_counts_row() for service in PUBLIC_SERVICE_KEYS} for hazard in HAZARD_KEYS}
        for scenario in PML_NETWORK_SCENARIOS
    }
    network_unit_counts: dict[str, dict[str, int]] = {
        hazard: {service: 0 for service in PUBLIC_SERVICE_KEYS}
        for hazard in HAZARD_KEYS
    }
    outage_cause_by_scenario: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        scenario: {hazard: {} for hazard in HAZARD_KEYS}
        for scenario in PML_NETWORK_SCENARIOS
    }
    calibration: dict[str, dict[str, dict[str, float]]] = {}
    target_totals: dict[str, dict[str, float]] = {}

    scenario_results_by_hazard: dict[str, dict[str, dict[str, Any]]] = {hazard: {} for hazard in HAZARD_KEYS}
    for hazard in HAZARD_KEYS:
        hazard_payload = portfolio_results.get(hazard) if isinstance(portfolio_results.get(hazard), dict) else {}
        eai_total = max(0.0, float(hazard_payload.get("eai_eur") or hazard_payload.get("aai_agg_eur") or 0.0))
        eai_direct_total = max(0.0, float(hazard_payload.get("eai_direct_eur") or 0.0))
        direct_share = 1.0 if eai_total <= 0.0 else max(0.0, min(1.0, eai_direct_total / max(eai_total, 1e-9)))
        direct_prior = np.asarray(hazard_direct_eai.get(hazard) or [], dtype=float).reshape(-1)
        if direct_prior.size != values.size:
            direct_prior = np.zeros_like(values)
        direct_prior = np.minimum(np.maximum(direct_prior, 0.0), values)
        calibration[hazard] = {}
        target_totals[hazard] = {}

        for scenario in PML_NETWORK_SCENARIOS:
            target_total = max(0.0, float(hazard_payload.get(PML_FIELD_BY_SCENARIO[scenario]) or 0.0))
            target_totals[hazard][scenario] = round(target_total, 2)
            direct_target = target_total * direct_share
            direct_loss = _pml_allocate_direct_loss_by_class(
                np,
                prior_direct=direct_prior,
                values=values,
                breakdown_class_keys=breakdown_class_keys,
                target_total=direct_target,
            )
            scenario_result = _pml_evaluate_network_scenario(
                np,
                direct_loss=direct_loss,
                values=values,
                point_records=point_records,
                network_class_keys=network_class_keys,
                breakdown_class_keys=breakdown_class_keys,
                weights_km=weights_km,
            )
            calibration[hazard][scenario] = _pml_calibrate_network_scenario(
                np,
                scenario_result,
                values=values,
                target_total=target_total,
            )
            calibration[hazard][scenario]["direct_target_total_eur"] = round(float(direct_target), 2)
            calibration[hazard][scenario]["annual_direct_share"] = round(float(direct_share), 6)
            scenario_results_by_hazard[hazard][scenario] = scenario_result

    for scenario in PML_NETWORK_SCENARIOS:
        for class_key, class_label in NETWORK_CLASS_LABELS.items():
            row: dict[str, Any] = {"class_key": class_key, "class_label": class_label}
            mask = np.asarray([ck == class_key for ck in network_class_keys], dtype=bool)
            for hazard in HAZARD_KEYS:
                result = scenario_results_by_hazard[hazard][scenario]
                component_ratios = _pml_component_ratios_for_scenario(component_hazards.get(hazard, {}), scenario)
                damage_val = round(float(np.asarray(result["total_loss"], dtype=float)[mask].sum()), 2)
                direct_val = round(float(np.asarray(result["direct_loss"], dtype=float)[mask].sum()), 2)
                dysfunction_val = round(float(np.asarray(result["dysfunction_loss"], dtype=float)[mask].sum()), 2)
                blocking_val = round(float(np.asarray(result["blocking_loss"], dtype=float)[mask].sum()), 2)
                indirect_val = round(max(0.0, dysfunction_val + blocking_val), 2)
                row[hazard] = {
                    "state_pct": _pml_state_pct_for_mask(np, result["final_state"], weights_km, mask),
                    "exposure_eur": round(float(values[mask].sum()), 2),
                    "damage_eur": damage_val,
                    "direct_damage_eur": direct_val,
                    "dysfunction_eur": dysfunction_val,
                    "blocking_ouvrage_eur": blocking_val,
                    "indirect_damage_eur": indirect_val,
                    "total_damage_eur": damage_val,
                    "damage_components_eur": _pml_allocate_damage_components(damage_val, component_ratios),
                }
                total_cause = direct_val + indirect_val
                outage_cause_by_scenario[scenario][hazard][class_key] = {
                    "direct_damage_eur": direct_val,
                    "dysfunction_eur": dysfunction_val,
                    "blocking_ouvrage_eur": blocking_val,
                    "indirect_damage_eur": indirect_val,
                    "total_damage_eur": round(total_cause, 2),
                    "direct_pct": round((direct_val / total_cause) * 100.0, 4) if total_cause > 0.0 else 0.0,
                    "indirect_pct": round((indirect_val / total_cause) * 100.0, 4) if total_cause > 0.0 else 0.0,
                }
            state_damage_tables[scenario].append(row)

        for hazard in HAZARD_KEYS:
            result = scenario_results_by_hazard[hazard][scenario]
            component_ratios = _pml_component_ratios_for_scenario(component_hazards.get(hazard, {}), scenario)
            for class_key, class_label in DAMAGE_BREAKDOWN_LABELS.items():
                mask = np.asarray([ck == class_key for ck in breakdown_class_keys], dtype=bool)
                damage_val = round(float(np.asarray(result["total_loss"], dtype=float)[mask].sum()), 2)
                damage_breakdown_by_scenario[scenario][hazard].append(
                    {
                        "class_key": class_key,
                        "class_label": class_label,
                        "exposure_eur": round(float(values[mask].sum()), 2),
                        "damage_eur": damage_val,
                        "direct_damage_eur": round(float(np.asarray(result["direct_loss"], dtype=float)[mask].sum()), 2),
                        "dysfunction_eur": round(float(np.asarray(result["dysfunction_loss"], dtype=float)[mask].sum()), 2),
                        "blocking_ouvrage_eur": round(float(np.asarray(result["blocking_loss"], dtype=float)[mask].sum()), 2),
                        "indirect_damage_eur": round(
                            float(np.asarray(result["dysfunction_loss"], dtype=float)[mask].sum())
                            + float(np.asarray(result["blocking_loss"], dtype=float)[mask].sum()),
                            2,
                        ),
                        "total_damage_eur": damage_val,
                        "damage_components_eur": _pml_allocate_damage_components(damage_val, component_ratios),
                    }
                )

            unit_state: dict[tuple[str, str], str] = {}
            for idx, record in enumerate(point_records):
                service_key = _pml_public_service_key(record, network_class_keys[idx])
                if service_key is None:
                    continue
                if service_key == "elec":
                    unit_id = _pml_electric_unit_id_from_point(record)
                else:
                    unit_id = _pml_service_feature_id_from_point(record)
                if not unit_id:
                    continue
                key = (service_key, unit_id)
                state = str(np.asarray(result["final_state"], dtype=object)[idx])
                current = unit_state.get(key, "S0")
                if STATE_ORDER[state] > STATE_ORDER[current]:
                    unit_state[key] = state
            for (service_key, _unit_id), state in unit_state.items():
                row = network_distribution[scenario][hazard][service_key]
                row[state] += 1
                row["total_units"] += 1
            for service_key in PUBLIC_SERVICE_KEYS:
                network_unit_counts[hazard][service_key] = max(
                    int(network_unit_counts[hazard][service_key]),
                    int(network_distribution[scenario][hazard][service_key]["total_units"]),
                )

    return {
        "schema_version": PML_NETWORK_GRAPH_SCHEMA_VERSION,
        "source_of_truth": "complete_analysis",
        "method": "pml_calibrated_network_states",
        "approximation": True,
        "event_selection_basis": "portfolio_pml_calibrated_from_annual_point_priors",
        "scenarios": list(PML_NETWORK_SCENARIOS),
        "return_period_by_scenario": dict(RETURN_PERIOD_BY_PML_SCENARIO),
        "hazards": list(HAZARD_KEYS),
        "target_totals_by_hazard": target_totals,
        "calibration_by_hazard": calibration,
        "state_damage_tables": state_damage_tables,
        "damage_breakdown_by_scenario": damage_breakdown_by_scenario,
        "network_state_service_distribution_by_scenario": network_distribution,
        "network_state_service_unit_counts": network_unit_counts,
        "outage_cause_by_scenario": outage_cause_by_scenario,
        "scenario_availability": {
            scenario: {
                "state_damage_tables": bool(state_damage_tables.get(scenario)),
                "damage_breakdown_by_scenario": bool(damage_breakdown_by_scenario.get(scenario)),
                "network_states": bool(network_distribution.get(scenario)),
                "social_impact_by_scenario": False,
            }
            for scenario in PML_NETWORK_SCENARIOS
        },
        "state_methodology": dict(state_aggregation_metadata or {}),
        "inputs": {
            "point_count": int(len(point_records)),
            "infra_point_count": int(all_infra_mask.sum()),
            "annual_point_prior": "hazard_direct_eai_by_point",
            "class_share_priority": ["annual_direct_loss_by_class", "exposure_value_by_class"],
            "track_sample_manifest_path": str(modeling.get("hazard_track_sample_manifest_path") or "") or None,
            "track_sample_id": modeling.get("hazard_track_sample_id"),
        },
    }


def _selected_hazard_keys(hazard_keys: tuple[str, ...] | None) -> tuple[str, ...]:
    requested = tuple(str(value) for value in (hazard_keys or HAZARD_KEYS))
    return tuple(hazard_key for hazard_key in HAZARD_KEYS if hazard_key in requested)


def _zero_hazard_result(point_count: int) -> HazardImpactResult:
    return HazardImpactResult(
        eai_direct_by_point=[0.0] * point_count,
        max_loss_by_point=[0.0] * point_count,
        at_event_loss=[],
        event_frequency=[],
        event_id=[],
        event_name=[],
        aai_agg_eur=0.0,
        max_event_loss_eur=0.0,
        pml_eur={int(rp): 0.0 for rp in RETURN_PERIODS},
        tvar_95_eur=0.0,
        top_events=[],
        raw_max_event_loss_eur=0.0,
    )


def _metric_family_classification() -> dict[str, dict[str, Any]]:
    return {
        "direct_physical": {
            "description": "CLIMADA direct hazard outputs before interdependency post-processing.",
            "affected_by": [
                "hazard_dynamic_max_tracks",
                "runoff_coeff",
                "max_dist_inland_km",
                "default_sampling_spacing_m",
                "climada_max_points_per_feature",
            ],
        },
        "indirect_monetary": {
            "description": "Indirect monetary uplift is disabled in the current prudent mode.",
            "affected_by": [],
            "disabled_by_design": True,
        },
        "network_state_social": {
            "description": "Cell/service states and derived population metrics after dependency post-processing.",
            "affected_by": [
                "hazard_dynamic_max_tracks",
                "runoff_coeff",
                "max_dist_inland_km",
                "default_sampling_spacing_m",
                "climada_max_points_per_feature",
                "territory_grid_deg",
                "direct_state_thresholds",
                "health_weights",
                "dependency_state_thresholds",
            ],
            "not_affected_by": ["uplift_by_state"],
        },
    }


def _build_climada_coherence_report(
    *,
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    point_records: list[dict[str, Any]],
    matching_qa: dict[str, Any],
    settings: Settings,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    geometry_issues = validate_exposure_geometry_contract(exposure)
    if geometry_issues:
        issues.append(
            {
                "check": "feature_geometry_contract",
                "status": "failed",
                "details": geometry_issues[:20],
                "issue_count": len(geometry_issues),
            }
        )

    expected_points = int(disagg.asset_count_points)
    actual_points = int(len(point_records))
    point_ratio = (
        abs(actual_points - expected_points) / float(max(expected_points, actual_points, 1))
        if max(expected_points, actual_points, 1) > 0
        else 0.0
    )
    point_status = "passed"
    if max(expected_points, actual_points) >= 1000 and point_ratio > 0.25:
        point_status = "failed"
    elif point_ratio > 0.05:
        point_status = "warning"
    if point_status != "passed":
        issues.append(
            {
                "check": "disaggregation_point_count_alignment",
                "status": point_status,
                "expected_points": expected_points,
                "actual_points": actual_points,
                "relative_diff": round(point_ratio, 6),
            }
        )

    matching_point_count = matching_qa.get("point_count")
    if matching_point_count is not None:
        matching_status = "passed"
        if int(matching_point_count) != actual_points:
            matching_status = "failed"
            issues.append(
                {
                    "check": "matching_qa_point_count_alignment",
                    "status": "failed",
                    "matching_qa_point_count": int(matching_point_count),
                    "actual_points": actual_points,
                }
            )
        else:
            issues.append(
                {
                    "check": "matching_qa_point_count_alignment",
                    "status": "passed",
                    "matching_qa_point_count": int(matching_point_count),
                    "actual_points": actual_points,
                }
            )

    territory_ids = {str(record.get("territory_id") or "") for record in point_records if record.get("territory_id")}
    point_count_by_feature: dict[str, int] = defaultdict(int)
    for record in point_records:
        point_count_by_feature[str(record.get("feature_id") or "")] += 1
    capped_feature_count = sum(
        1 for point_count in point_count_by_feature.values() if point_count >= int(settings.climada_max_points_per_feature)
    )

    for issue in issues:
        if issue.get("status") == "warning":
            warnings.append(
                f"{issue['check']}: expected={issue.get('expected_points')} actual={issue.get('actual_points')}"
            )

    report = {
        "status": "failed" if any(issue.get("status") == "failed" for issue in issues) else "passed",
        "checks": issues,
        "stats": {
            "asset_count_original": int(exposure.asset_count_original),
            "expected_point_count_from_disaggregation": expected_points,
            "actual_point_count_for_climada": actual_points,
            "unique_territory_cell_count": len(territory_ids),
            "capped_feature_count": int(capped_feature_count),
            "sampling_spacing_m": float(disagg.spacing_m),
            "territory_grid_deg": float(settings.territory_grid_deg),
            "max_points_per_feature": int(settings.climada_max_points_per_feature),
        },
    }
    return report, warnings


def _network_state_plausibility_warnings(
    population_state_distribution_by_hazard: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    warnings: list[str] = []
    for hazard, by_service in population_state_distribution_by_hazard.items():
        if not isinstance(by_service, dict):
            continue
        binary_services = 0
        inspected_services = 0
        for service, distribution in by_service.items():
            if not isinstance(distribution, dict):
                continue
            inspected_services += 1
            values = []
            for key in ("S0", "S1", "S2", "S3"):
                try:
                    values.append(float(distribution.get(key, 0.0)))
                except Exception:
                    values.append(0.0)
            positive_values = [value for value in values if value > 0.0]
            if len(positive_values) <= 1:
                binary_services += 1
        if inspected_services and binary_services == inspected_services:
            warnings.append(
                f"All published network-state distributions are binary for hazard={hazard}; validate whether this all-or-nothing pattern is expected."
            )
    return warnings


def _attach_service_state_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    native_states = payload.get("network_states_native")
    projected_states = payload.get("network_states_projected")
    projected_coverage = payload.get("network_states_projected_coverage")
    if isinstance(native_states, dict):
        payload["native_service_states"] = native_states
    if isinstance(projected_states, dict):
        payload["population_projected_service_states"] = projected_states
    if isinstance(projected_coverage, dict):
        payload["population_projected_service_states_coverage"] = projected_coverage
    return payload


def prepare_climada_exposure_bundle(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    settings: Settings,
) -> ClimadaExposureBundle:
    wind_asset_mapping = dict(settings.wind_asset_type_to_curve_code or {}) or None
    return build_climada_exposure(
        exposure,
        spacing_m=float(disagg.spacing_m),
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=max(1, int(settings.climada_max_points_per_feature)),
        territory_grid_deg=float(settings.territory_grid_deg),
        impact_func_id_resolver=lambda asset_type: resolve_tc_impact_func_id(
            asset_type,
            asset_type_to_curve_code=wind_asset_mapping,
        ),
    )


def _compute_impacts_climada(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    settings: Settings,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
    resume_enabled: bool = False,
    resume_dynamic_hazard_point_cap: int | None = None,
    prebuilt_bundle: ClimadaExposureBundle | None = None,
    hazard_keys: tuple[str, ...] | None = None,
    explicit_hazard_bundle: Any | None = None,
) -> ImpactComputationResult:
    wind_asset_mapping = dict(settings.wind_asset_type_to_curve_code or {}) or None
    flood_asset_mapping = dict(settings.flood_asset_type_to_curve_code or {}) or None
    state_thresholds = {
        "S0_to_S1_damage_ratio": float(settings.interdependency_state_threshold_s0_to_s1),
        "S1_to_S2_damage_ratio": float(settings.interdependency_state_threshold_s1_to_s2),
        "S2_to_S3_damage_ratio": float(settings.interdependency_state_threshold_s2_to_s3),
    }
    health_weights_by_state = {
        "S1": float(settings.interdependency_health_weight_s1),
        "S2": float(settings.interdependency_health_weight_s2),
        "S3": float(settings.interdependency_health_weight_s3),
    }
    dependency_state_thresholds = {
        "S1": float(settings.interdependency_dependency_state_threshold_s1),
        "S2": float(settings.interdependency_dependency_state_threshold_s2),
        "S3": float(settings.interdependency_dependency_state_threshold_s3),
    }
    uplift_by_state = {
        "S0": float(settings.interdependency_uplift_s0),
        "S1": float(settings.interdependency_uplift_s1),
        "S2": float(settings.interdependency_uplift_s2),
        "S3": float(settings.interdependency_uplift_s3),
    }

    bundle = prebuilt_bundle or prepare_climada_exposure_bundle(exposure, disagg, settings)
    climada = run_climada_direct_impacts(
        bundle,
        hazard_storm_path=settings.hazard_storm_path,
        hazard_storm_cmcc_path=settings.hazard_storm_cmcc_path,
        storm_years=max(1, int(settings.storm_years)),
        top_n_events=max(1, int(settings.climada_top_events_count)),
        prefer_dynamic_hazards=bool(settings.hazard_prefer_dynamic_from_parquet),
        fallback_to_precomputed_hazards=False,
        storm_parquet_path=settings.storm_parquet_path,
        storm_cmcc_parquet_path=settings.storm_cmcc_parquet_path,
        track_sample_manifest_path=settings.hazard_track_sample_manifest_path,
        wind_unit_in=settings.storm_wind_unit_in,
        convert_10min_to_1min=bool(settings.storm_convert_10min_to_1min),
        radius_unit_in=settings.storm_radius_unit_in,
        env_pressure_hpa=float(settings.storm_env_pressure_hpa),
        dynamic_max_tracks=int(settings.hazard_dynamic_max_tracks),
        track_cache_max_entries=int(settings.hazard_track_cache_max_entries),
        multi_hazard_enabled=bool(settings.multi_hazard_enabled),
        rain_model=settings.hazard_rain_model,
        rain_max_dist_inland_km=float(settings.hazard_rain_max_dist_inland_km),
        surge_topo_path=settings.hazard_surge_topo_path,
        flood_curve_file=settings.d2_flood_curve_file,
        wind_asset_type_to_curve_code=wind_asset_mapping,
        flood_asset_type_to_curve_code=flood_asset_mapping,
        rain_proxy_base_runoff_coeff=float(settings.multi_hazard_rain_base_runoff_coeff),
        execution_profile=settings.climada_execution_profile,
        memory_budget_gb=float(settings.climada_memory_budget_gb),
        max_points_per_shard=int(settings.climada_max_points_per_shard),
        min_points_per_shard=int(settings.climada_min_points_per_shard),
        max_shard_retry_depth=int(settings.climada_max_shard_retry_depth),
        strict_required_components=True,
        progress_callback=progress_callback,
        checkpoint_dir=checkpoint_dir,
        resume_enabled=resume_enabled,
        resume_dynamic_hazard_point_cap=resume_dynamic_hazard_point_cap,
        hazard_keys=hazard_keys,
        explicit_hazard_bundle=explicit_hazard_bundle,
    )

    point_count = len(bundle.point_records)
    selected_hazard_keys = _selected_hazard_keys(hazard_keys)
    resolved_hazards: dict[str, HazardImpactResult] = {}
    resolved_component_hazards: dict[str, dict[str, HazardImpactResult]] = {}
    for hazard_key in HAZARD_KEYS:
        if hazard_key in climada.hazards:
            resolved_hazards[hazard_key] = climada.hazards[hazard_key]
            resolved_component_hazards[hazard_key] = dict((climada.component_hazards or {}).get(hazard_key) or {})
            continue
        resolved_hazards[hazard_key] = _zero_hazard_result(point_count)
        resolved_component_hazards[hazard_key] = {}
    omitted_hazard_keys = [hazard_key for hazard_key in HAZARD_KEYS if hazard_key not in selected_hazard_keys]
    if omitted_hazard_keys:
        climada.notes.append(
            "Hazard outputs omitted by selection were zero-filled for downstream export compatibility: "
            + ", ".join(omitted_hazard_keys)
            + "."
        )

    hazard_direct_eai = {
        "storm": _to_float_list(resolved_hazards["storm"].eai_direct_by_point, point_count),
        "storm_cmcc": _to_float_list(resolved_hazards["storm_cmcc"].eai_direct_by_point, point_count),
    }
    hazard_max_loss = {
        "storm": _to_float_list(resolved_hazards["storm"].max_loss_by_point, point_count),
        "storm_cmcc": _to_float_list(resolved_hazards["storm_cmcc"].max_loss_by_point, point_count),
    }

    aggregated = aggregate_impacts_with_interdependency(
        point_records=bundle.point_records,
        hazard_direct_eai=hazard_direct_eai,
        hazard_max_loss=hazard_max_loss,
        state_thresholds=state_thresholds,
        health_weights_by_state=health_weights_by_state,
        dependency_state_thresholds=dependency_state_thresholds,
        uplift_by_state=uplift_by_state,
    )

    # Load and integrate population data for social impact metrics
    population_by_territory = {}
    social_summary_by_hazard = {}
    population_state_distribution_by_hazard = {}
    
    try:
        population_data_dir = settings.population_data_dir or Path("/home/ubuntu/uploads/Population")
        if Path(population_data_dir).exists():
            pop_data = load_population_data(
                population_data_dir=population_data_dir,
                territories=["GUA", "MTQ", "BLM"],
                cell_size_deg=float(settings.territory_grid_deg),
            )
            # Flatten the nested dict: {territory_id -> {cell_id -> pop}} => {cell_id -> pop}
            for territory_pop_dict in pop_data.values():
                population_by_territory.update(territory_pop_dict)
            
            # Calculate social impact metrics
            if population_by_territory and aggregated.projected_service_states_by_territory:
                social_metrics = aggregate_social_metrics_by_territory(
                    population_by_territory=population_by_territory,
                    detailed_states=aggregated.projected_service_states_by_territory,
                    coverage_by_territory=aggregated.projected_service_coverage_by_territory,
                )
                social_summary_by_hazard = aggregate_social_summary(social_metrics)
                population_state_distribution = aggregate_population_state_distribution_by_territory(
                    population_by_territory=population_by_territory,
                    detailed_states=aggregated.projected_service_states_by_territory,
                    coverage_by_territory=aggregated.projected_service_coverage_by_territory,
                )
                population_state_distribution_by_hazard = aggregate_population_state_distribution_summary(
                    population_state_distribution
                )
            else:
                logger.info("Population data available but detailed states not available for social impact")
        else:
            logger.info(f"Population data directory not found: {population_data_dir}")
    except Exception as e:
        logger.warning(f"Failed to load population data for social impact: {e}")
        social_summary_by_hazard = {}

    storm_direct = float(aggregated.portfolio_by_hazard["storm"]["eai_direct_eur"])
    storm_indirect = float(aggregated.portfolio_by_hazard["storm"]["eai_indirect_eur"])
    storm_total = float(aggregated.portfolio_by_hazard["storm"]["eai_total_eur"])
    cmcc_direct = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_direct_eur"])
    cmcc_indirect = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_indirect_eur"])
    cmcc_total = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_total_eur"])

    storm_scaler = float(aggregated.dependency_scaler_by_hazard.get("storm", 1.0))
    cmcc_scaler = float(aggregated.dependency_scaler_by_hazard.get("storm_cmcc", 1.0))

    storm_direct_metrics = resolved_hazards["storm"]
    cmcc_direct_metrics = resolved_hazards["storm_cmcc"]

    storm_components_raw = resolved_component_hazards["storm"]
    cmcc_components_raw = resolved_component_hazards["storm_cmcc"]

    def _component_direct_eai_map(component_map: dict[str, Any], combined_direct: float) -> dict[str, float]:
        ordered_names = [name for name in ("wind", "rain", "surge") if name in component_map]
        ordered_names.extend(sorted(name for name in component_map.keys() if name not in {"wind", "rain", "surge"}))
        out = {name: round(max(0.0, float(getattr(component_map[name], "aai_agg_eur", 0.0))), 2) for name in ordered_names}
        out["combined_capped"] = round(max(0.0, float(combined_direct)), 2)
        return out

    def _component_direct_percentile_99_map(component_map: dict[str, Any]) -> dict[str, float]:
        ordered_names = [name for name in ("wind", "rain", "surge") if name in component_map]
        ordered_names.extend(sorted(name for name in component_map.keys() if name not in {"wind", "rain", "surge"}))
        return {
            name: round(max(0.0, float(getattr(component_map[name], "max_event_loss_eur", 0.0))), 2)
            for name in ordered_names
        }

    storm_components_direct = _component_direct_eai_map(storm_components_raw, storm_direct)
    cmcc_components_direct = _component_direct_eai_map(cmcc_components_raw, cmcc_direct)
    storm_components_p99 = _component_direct_percentile_99_map(storm_components_raw)
    cmcc_components_p99 = _component_direct_percentile_99_map(cmcc_components_raw)
    social_summary_payload = build_social_impact_summary_payload(
        social_summary_by_hazard,
        population_state_distribution_by_hazard,
        aggregated.state_aggregation_metadata,
    )
    network_state_plausibility_notes = _network_state_plausibility_warnings(
        population_state_distribution_by_hazard
    )

    portfolio_results = {
        "storm": {
            "eai_eur": round(storm_total, 2),
            "aai_agg_eur": round(storm_total, 2),
            "percentile_99_loss_eur": round(storm_direct_metrics.max_event_loss_eur * storm_scaler, 2),
            "eai_direct_eur": round(storm_direct, 2),
            "eai_indirect_eur": round(storm_indirect, 2),
            "pml_10_eur": round(float(storm_direct_metrics.pml_eur.get(10, 0.0)) * storm_scaler, 2),
            "pml_20_eur": round(float(storm_direct_metrics.pml_eur.get(20, 0.0)) * storm_scaler, 2),
            "pml_50_eur": round(float(storm_direct_metrics.pml_eur.get(50, 0.0)) * storm_scaler, 2),
            "pml_100_eur": round(float(storm_direct_metrics.pml_eur.get(100, 0.0)) * storm_scaler, 2),
            "pml_200_eur": round(float(storm_direct_metrics.pml_eur.get(200, 0.0)) * storm_scaler, 2),
            "pml_1000_eur": round(
                float(
                    storm_direct_metrics.pml_eur.get(
                        1000,
                        max(
                            float(storm_direct_metrics.pml_eur.get(200, 0.0)),
                            float(storm_direct_metrics.raw_max_event_loss_eur),
                        ),
                    )
                ) * storm_scaler,
                2,
            ),
            "tvar_95_eur": round(float(storm_direct_metrics.tvar_95_eur) * storm_scaler, 2),
            "components_direct_eai_eur": storm_components_direct,
            "components_direct_percentile_99_loss_eur": storm_components_p99,
        },
        "storm_cmcc": {
            "eai_eur": round(cmcc_total, 2),
            "aai_agg_eur": round(cmcc_total, 2),
            "percentile_99_loss_eur": round(cmcc_direct_metrics.max_event_loss_eur * cmcc_scaler, 2),
            "eai_direct_eur": round(cmcc_direct, 2),
            "eai_indirect_eur": round(cmcc_indirect, 2),
            "pml_10_eur": round(float(cmcc_direct_metrics.pml_eur.get(10, 0.0)) * cmcc_scaler, 2),
            "pml_20_eur": round(float(cmcc_direct_metrics.pml_eur.get(20, 0.0)) * cmcc_scaler, 2),
            "pml_50_eur": round(float(cmcc_direct_metrics.pml_eur.get(50, 0.0)) * cmcc_scaler, 2),
            "pml_100_eur": round(float(cmcc_direct_metrics.pml_eur.get(100, 0.0)) * cmcc_scaler, 2),
            "pml_200_eur": round(float(cmcc_direct_metrics.pml_eur.get(200, 0.0)) * cmcc_scaler, 2),
            "pml_1000_eur": round(
                float(
                    cmcc_direct_metrics.pml_eur.get(
                        1000,
                        max(
                            float(cmcc_direct_metrics.pml_eur.get(200, 0.0)),
                            float(cmcc_direct_metrics.raw_max_event_loss_eur),
                        ),
                    )
                ) * cmcc_scaler,
                2,
            ),
            "tvar_95_eur": round(float(cmcc_direct_metrics.tvar_95_eur) * cmcc_scaler, 2),
            "components_direct_eai_eur": cmcc_components_direct,
            "components_direct_percentile_99_loss_eur": cmcc_components_p99,
        },
        "delta": {
            "eai_eur": round(cmcc_total - storm_total, 2),
            "eai_pct": round(((cmcc_total / max(storm_total, 1.0)) - 1.0) * 100.0, 2),
        },
        "component_health": aggregated.component_health,
        "interdependency": aggregated.interdependency,
        "network_states_native": aggregated.native_service_states_by_hazard,
        "network_states_projected": aggregated.projected_service_states_by_territory,
        "network_states_projected_coverage": aggregated.projected_service_coverage_by_territory,
        "state_aggregation_metadata": aggregated.state_aggregation_metadata,
        **social_summary_payload,
        "event_summary": {
            "storm_top_events": _scale_top_events(storm_direct_metrics.top_events, storm_scaler),
            "storm_cmcc_top_events": _scale_top_events(cmcc_direct_metrics.top_events, cmcc_scaler),
        },
    }
    portfolio_results = _attach_service_state_aliases(portfolio_results)

    graphs = _build_climada_graphs(
        ClimadaRunResult(
            hazards=resolved_hazards,
            component_hazards=resolved_component_hazards,
            modeling=climada.modeling,
            notes=climada.notes,
        ),
        aggregated.dependency_scaler_by_hazard,
        portfolio_results,
    )
    notes = [
        "CLIMADA production engine is active (STORM + STORM_CMCC with annualized frequencies).",
        "Direct impact is computed by CLIMADA and indirect impact is added by conservative electricity-to-water dependency post-processing.",
        (
            "Component health uses: health = 1 - "
            f"({health_weights_by_state['S1']}*L_S1 + {health_weights_by_state['S2']}*L_S2 + "
            f"{health_weights_by_state['S3']}*L_S3) / L_total."
        ),
        "Electricity-health lookup for water assets uses local territory, then nearest electric territory, then global fallback.",
        "Per-asset EAI is capped to asset exposure value: EAI_total <= exposure_eur.",
        "When enabled, direct multi-hazard uses additive wind+rain+surge losses with per-point capping before interdependency uplift.",
        (
            "Social impact summaries use population-projected service states derived from aggregated native "
            "electric 0.1 deg cells and hydraulic zone_component_key water states; canonical key "
            "social_impact_summary, legacy alias social_impact_worst_case_summary."
        ),
        *network_state_plausibility_notes,
        *climada.notes,
        *bundle.warnings,
    ]
    
    # Enrich territory_results with population and social impact metrics
    enriched_territory_results = []
    for tr in aggregated.territory_results:
        territory_id = str(tr.get("territory_id") or "uploaded-aggregate")
        pop_total = population_by_territory.get(territory_id, 0.0)
        
        # Add population
        tr["population_total"] = round(pop_total, 0)
        
        # Add social metrics per hazard if available
        if social_summary_by_hazard and aggregated.projected_service_states_by_territory:
            tr["social_metrics"] = {}
            tr["social_metrics_basis"] = SOCIAL_IMPACT_SUMMARY_BASIS
            tr["social_impact_population_state_distribution"] = {}
            tr["network_states_native"] = {}
            tr["network_states_projected"] = {}
            tr["network_states_projected_coverage"] = {}
            for hazard in aggregated.projected_service_states_by_territory.keys():
                if (
                    hazard in aggregated.projected_service_states_by_territory
                    and territory_id in aggregated.projected_service_states_by_territory[hazard]
                ):
                    infra_states = aggregated.projected_service_states_by_territory[hazard][territory_id]
                    infra_coverage = {}
                    if aggregated.projected_service_coverage_by_territory:
                        infra_coverage = (aggregated.projected_service_coverage_by_territory.get(hazard) or {}).get(
                            territory_id,
                            {},
                        )
                    native_units = (aggregated.projected_service_units_by_territory.get(hazard) or {}).get(
                        territory_id,
                        {},
                    )
                    tr["network_states_projected"][hazard] = dict(infra_states)
                    tr["network_states_projected_coverage"][hazard] = dict(infra_coverage)
                    tr["network_states_native"][hazard] = {}
                    for service_name, service_unit_id in native_units.items():
                        native_row = (
                            (aggregated.native_service_states_by_hazard.get(hazard) or {})
                            .get(service_name, {})
                            .get(service_unit_id)
                        )
                        if native_row:
                            tr["network_states_native"][hazard][service_name] = dict(native_row)
                    metrics = calculate_social_impact_metrics(
                        hazard=hazard,
                        territory_id=territory_id,
                        population_total=pop_total,
                        infra_states=infra_states,
                        infra_coverage=infra_coverage,
                    )
                    tr["social_metrics"][hazard] = metrics.to_dict()
                    tr["social_impact_population_state_distribution"][hazard] = {
                        service: distribution.to_dict()
                        for service, distribution in calculate_population_state_distribution(
                            hazard=hazard,
                            territory_id=territory_id,
                            population_total=pop_total,
                            infra_states=infra_states,
                            infra_coverage=infra_coverage,
                        ).items()
                    }
            tr["state_aggregation_metadata"] = aggregated.state_aggregation_metadata
            _attach_service_state_aliases(tr)

        enriched_territory_results.append(tr)
    
    modeling = {
        **climada.modeling,
        "dependency_mode": "postprocess_electricity_to_water",
        "scenario_mode": "prudent",
        "metric_crs": settings.climada_metric_crs,
        "sampling_spacing_m": float(disagg.spacing_m),
        "territory_grid_deg": float(settings.territory_grid_deg),
        "max_points_per_feature": int(settings.climada_max_points_per_feature),
        "rain_max_dist_inland_km": float(settings.hazard_rain_max_dist_inland_km),
        "rain_proxy_base_runoff_coeff": float(settings.multi_hazard_rain_base_runoff_coeff),
        "state_thresholds": state_thresholds,
        "health_weights_by_state": health_weights_by_state,
        "dependency_state_thresholds": dependency_state_thresholds,
        "uplift_by_state": uplift_by_state,
        "indirect_monetary_uplift_enabled": False,
        "state_aggregation_metadata": aggregated.state_aggregation_metadata,
        "metric_family_classification": _metric_family_classification(),
        "wind_asset_type_to_curve_code": wind_asset_mapping,
        "flood_asset_type_to_curve_code": flood_asset_mapping,
    }
    matching_qa = dict(climada.modeling.get("hazard_exposure_matching_qa") or {})
    coherence_report, coherence_warnings = _build_climada_coherence_report(
        exposure=exposure,
        disagg=disagg,
        point_records=bundle.point_records,
        matching_qa=matching_qa,
        settings=settings,
    )
    if coherence_report["status"] == "failed":
        failed_checks = [
            str(check.get("check") or "unknown")
            for check in coherence_report.get("checks", [])
            if check.get("status") == "failed"
        ]
        raise ValueError(
            "Complete-analysis coherence checks failed before result export: "
            + ", ".join(failed_checks)
        )
    notes.extend(coherence_warnings)
    pml_network_graph_inputs = _build_pml_network_graph_inputs(
        np,
        point_records=list(bundle.point_records or []),
        hazard_direct_eai=hazard_direct_eai,
        portfolio_results=portfolio_results,
        component_hazards=resolved_component_hazards,
        state_aggregation_metadata=aggregated.state_aggregation_metadata,
        modeling=modeling,
    )

    return ImpactComputationResult(
        engine="climada_with_interdependency_v1",
        territory_results=enriched_territory_results,
        asset_results=aggregated.asset_results,
        portfolio_results=portfolio_results,
        graphs=graphs,
        notes=notes,
        modeling=modeling,
        matching_qa=matching_qa,
        artifacts={
            "coherence_report": [coherence_report],
            "pml_network_graph_inputs": pml_network_graph_inputs,
        },
    )


def compute_impacts_fallback(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
) -> ImpactComputationResult:
    total_exposure = max(0.0, exposure.total_exposure_eur)
    complexity = _clamp(disagg.asset_count_points / max(1, exposure.asset_count_original), 1.0, 200.0)
    base_damage = _clamp(0.055 + (0.008 * math.log10(complexity + 1.0)), 0.045, 0.22)

    elec_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in HAZARD_KEYS
    }
    elec_global_bucket: dict[str, dict[str, float]] = {hazard: _new_state_bucket() for hazard in HAZARD_KEYS}
    elec_territory_loc_acc: dict[str, dict[str, float]] = {}

    for feat in exposure.features:
        infra_class = _infer_infra_class(feat)
        if infra_class not in {"elec_aerien", "elec_souterrain"}:
            continue
        territory_id, _, lat, lon = _territory_for_feature(feat)
        weight = _feature_weight(feat)
        if lat is not None and lon is not None:
            loc = elec_territory_loc_acc.setdefault(territory_id, {"lat_sum": 0.0, "lon_sum": 0.0, "count": 0.0})
            loc["lat_sum"] += float(lat)
            loc["lon_sum"] += float(lon)
            loc["count"] += 1.0
        for hazard in HAZARD_KEYS:
            state = _state_from_damage_ratio(_direct_damage_ratio(feat, hazard, base_damage))
            _bucket_add_state(elec_buckets_by_hazard[hazard][territory_id], state=state, weight=weight)
            _bucket_add_state(elec_global_bucket[hazard], state=state, weight=weight)

    elec_health_by_territory: dict[str, dict[str, float]] = {
        hazard: {territory_id: _health_from_bucket(bucket) for territory_id, bucket in buckets.items()}
        for hazard, buckets in elec_buckets_by_hazard.items()
    }
    elec_health_global = {hazard: _health_from_bucket(bucket) for hazard, bucket in elec_global_bucket.items()}
    elec_territory_centroids = {
        tid: (loc["lat_sum"] / loc["count"], loc["lon_sum"] / loc["count"])
        for tid, loc in elec_territory_loc_acc.items()
        if loc.get("count", 0.0) > 0.0
    }

    territory_acc: dict[str, dict[str, Any]] = {}
    asset_acc: dict[str, dict[str, Any]] = {}
    infra_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in HAZARD_KEYS
    }
    health_resolution_by_hazard = {
        hazard: {"local_territory": 0, "nearest_territory": 0, "global": 0}
        for hazard in HAZARD_KEYS
    }

    dependency_impacted_assets = 0
    for feat in exposure.features:
        territory_id, territory_label, lat, lon = _territory_for_feature(feat)
        infra_class = _infer_infra_class(feat)
        weight = _feature_weight(feat)
        exposure_value = max(0.0, float(feat.value_eur))

        row = territory_acc.setdefault(
            territory_id,
            {
                "territory_id": territory_id,
                "territory_label": territory_label,
                "lat_sum": 0.0,
                "lon_sum": 0.0,
                "loc_count": 0,
                "exposure_eur": 0.0,
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        )
        row["exposure_eur"] += exposure_value
        if lat is not None and lon is not None:
            row["lat_sum"] += float(lat)
            row["lon_sum"] += float(lon)
            row["loc_count"] += 1

        asset_row = asset_acc.setdefault(
            str(feat.feature_id),
            {
                "asset_id": str(feat.feature_id),
                "asset_label": str(feat.label or feat.feature_id),
                "geometry_type": str(feat.geometry_type or "Unknown"),
                "asset_type": str((feat.properties or {}).get("asset_type") or ""),
                "uses_default_value": bool((feat.properties or {}).get("uses_default_value")),
                "valuation_source": str((feat.properties or {}).get("valuation_source") or ""),
                "valuation_version": str((feat.properties or {}).get("valuation_version") or ""),
                "default_value_eur": (feat.properties or {}).get("default_value_eur"),
                "exposure_eur": 0.0,
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        )
        asset_row["exposure_eur"] += exposure_value

        for hazard in HAZARD_KEYS:
            direct_damage = _direct_damage_ratio(feat, hazard, base_damage)
            direct_state = _state_from_damage_ratio(direct_damage)
            final_state = direct_state
            final_damage = direct_damage

            if infra_class in {"eau_reseau", "eau_ouvrage"}:
                elec_health, source = _resolve_electric_health_for_territory(
                    hazard=hazard,
                    territory_id=territory_id,
                    lat=lat,
                    lon=lon,
                    elec_health_by_territory=elec_health_by_territory,
                    elec_health_global=elec_health_global,
                    elec_territory_centroids=elec_territory_centroids,
                )
                health_resolution_by_hazard[hazard][source] += 1
                dependency_state = _dependency_state_from_elec_health(elec_health)
                if STATE_ORDER[dependency_state] > STATE_ORDER[direct_state]:
                    dependency_impacted_assets += 1
                    final_state = dependency_state
                final_damage = max(final_damage, STATE_DAMAGE_FLOOR[dependency_state])
                final_damage = _clamp(final_damage + (1.0 - elec_health) * 0.12, 0.0, 0.95)

            direct_eai = min(exposure_value, max(0.0, exposure_value * (direct_damage * ANNUALIZATION_FACTOR[hazard])))
            final_eai = min(exposure_value, max(0.0, exposure_value * (final_damage * ANNUALIZATION_FACTOR[hazard])))
            if final_eai < direct_eai:
                final_eai = direct_eai
            indirect_eai = max(0.0, final_eai - direct_eai)

            if hazard == "storm":
                row["eai_storm_direct_eur"] += direct_eai
                row["eai_storm_indirect_eur"] += indirect_eai
                row["eai_storm_eur"] += final_eai
                asset_row["eai_storm_direct_eur"] += direct_eai
                asset_row["eai_storm_indirect_eur"] += indirect_eai
                asset_row["eai_storm_eur"] += final_eai
            else:
                row["eai_cmcc_direct_eur"] += direct_eai
                row["eai_cmcc_indirect_eur"] += indirect_eai
                row["eai_cmcc_eur"] += final_eai
                asset_row["eai_cmcc_direct_eur"] += direct_eai
                asset_row["eai_cmcc_indirect_eur"] += indirect_eai
                asset_row["eai_cmcc_eur"] += final_eai

            _bucket_add_state(infra_buckets_by_hazard[hazard][infra_class], state=final_state, weight=weight)

    territory_results: list[dict[str, Any]] = []
    for row in territory_acc.values():
        exp_eur = float(row["exposure_eur"])
        eai_storm = float(row["eai_storm_eur"])
        eai_cmcc = float(row["eai_cmcc_eur"])
        risk_index_storm = _clamp((eai_storm / max(exp_eur, 1.0)) * 1000.0, 0.0, 100.0)
        risk_index_cmcc = _clamp((eai_cmcc / max(exp_eur, 1.0)) * 1000.0, 0.0, 100.0)
        territory_results.append(
            {
                "territory_id": row["territory_id"],
                "territory_label": row["territory_label"],
                "lat": (row["lat_sum"] / row["loc_count"]) if row["loc_count"] > 0 else None,
                "lon": (row["lon_sum"] / row["loc_count"]) if row["loc_count"] > 0 else None,
                "exposure_eur": round(exp_eur, 2),
                "eai_storm_direct_eur": round(float(row["eai_storm_direct_eur"]), 2),
                "eai_storm_indirect_eur": round(float(row["eai_storm_indirect_eur"]), 2),
                "eai_storm_eur": round(eai_storm, 2),
                "eai_cmcc_direct_eur": round(float(row["eai_cmcc_direct_eur"]), 2),
                "eai_cmcc_indirect_eur": round(float(row["eai_cmcc_indirect_eur"]), 2),
                "eai_cmcc_eur": round(eai_cmcc, 2),
                "risk_index_storm": round(risk_index_storm, 2),
                "risk_index_cmcc": round(risk_index_cmcc, 2),
            }
        )

    if not territory_results:
        territory_results = [
            {
                "territory_id": "uploaded-aggregate",
                "territory_label": "Uploaded Exposure (aggregate)",
                "lat": None,
                "lon": None,
                "exposure_eur": round(total_exposure, 2),
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
                "risk_index_storm": 0.0,
                "risk_index_cmcc": 0.0,
            }
        ]

    territory_results.sort(key=lambda row: float(row.get("exposure_eur") or 0.0), reverse=True)

    asset_results: list[dict[str, Any]] = []
    for row in asset_acc.values():
        exp_eur = float(row["exposure_eur"])
        eai_storm = float(row["eai_storm_eur"])
        eai_cmcc = float(row["eai_cmcc_eur"])
        risk_index_storm = _clamp((eai_storm / max(exp_eur, 1.0)) * 1000.0, 0.0, 100.0)
        risk_index_cmcc = _clamp((eai_cmcc / max(exp_eur, 1.0)) * 1000.0, 0.0, 100.0)
        asset_results.append(
            {
                "asset_id": row["asset_id"],
                "asset_label": row["asset_label"],
                "geometry_type": row["geometry_type"],
                "asset_type": row["asset_type"],
                "uses_default_value": bool(row.get("uses_default_value")),
                "valuation_source": str(row.get("valuation_source") or ""),
                "valuation_version": str(row.get("valuation_version") or ""),
                "default_value_eur": row.get("default_value_eur"),
                "exposure_eur": round(exp_eur, 2),
                "eai_storm_direct_eur": round(float(row["eai_storm_direct_eur"]), 2),
                "eai_storm_indirect_eur": round(float(row["eai_storm_indirect_eur"]), 2),
                "eai_storm_eur": round(eai_storm, 2),
                "eai_cmcc_direct_eur": round(float(row["eai_cmcc_direct_eur"]), 2),
                "eai_cmcc_indirect_eur": round(float(row["eai_cmcc_indirect_eur"]), 2),
                "eai_cmcc_eur": round(eai_cmcc, 2),
                "risk_index_storm": round(risk_index_storm, 2),
                "risk_index_cmcc": round(risk_index_cmcc, 2),
            }
        )
    asset_results.sort(key=lambda row: float(row.get("exposure_eur") or 0.0), reverse=True)

    storm_direct = round(sum(float(row["eai_storm_direct_eur"]) for row in territory_results), 2)
    storm_indirect = round(sum(float(row["eai_storm_indirect_eur"]) for row in territory_results), 2)
    storm_total = round(sum(float(row["eai_storm_eur"]) for row in territory_results), 2)
    cmcc_direct = round(sum(float(row["eai_cmcc_direct_eur"]) for row in territory_results), 2)
    cmcc_indirect = round(sum(float(row["eai_cmcc_indirect_eur"]) for row in territory_results), 2)
    cmcc_total = round(sum(float(row["eai_cmcc_eur"]) for row in territory_results), 2)
    max_event_storm = round(storm_total * 4.5, 2)
    max_event_cmcc = round(cmcc_total * 4.9, 2)

    component_health = {
        hazard: _summarize_component_health(dict(infra_buckets))
        for hazard, infra_buckets in infra_buckets_by_hazard.items()
    }

    portfolio_results = {
        "storm": {
            "eai_eur": storm_total,
            "aai_agg_eur": storm_total,
            "percentile_99_loss_eur": max_event_storm,
            "eai_direct_eur": storm_direct,
            "eai_indirect_eur": storm_indirect,
            "pml_10_eur": round(storm_total * 2.3, 2),
            "pml_20_eur": round(storm_total * 2.0, 2),
            "pml_50_eur": round(storm_total * 1.7, 2),
            "pml_100_eur": round(storm_total * 1.45, 2),
            "pml_200_eur": round(storm_total * 1.25, 2),
            "pml_1000_eur": round(storm_total * 1.9, 2),
            "tvar_95_eur": round(storm_total * 1.8, 2),
        },
        "storm_cmcc": {
            "eai_eur": cmcc_total,
            "aai_agg_eur": cmcc_total,
            "percentile_99_loss_eur": max_event_cmcc,
            "eai_direct_eur": cmcc_direct,
            "eai_indirect_eur": cmcc_indirect,
            "pml_10_eur": round(cmcc_total * 2.3, 2),
            "pml_20_eur": round(cmcc_total * 2.0, 2),
            "pml_50_eur": round(cmcc_total * 1.7, 2),
            "pml_100_eur": round(cmcc_total * 1.45, 2),
            "pml_200_eur": round(cmcc_total * 1.25, 2),
            "pml_1000_eur": round(cmcc_total * 1.9, 2),
            "tvar_95_eur": round(cmcc_total * 1.8, 2),
        },
        "delta": {
            "eai_eur": round(cmcc_total - storm_total, 2),
            "eai_pct": round(((cmcc_total / max(storm_total, 1.0)) - 1.0) * 100.0, 2),
        },
        "component_health": component_health,
        "interdependency": {
            "electricity_to_water_enabled": True,
            "water_assets_dependency_assumption": "all_water_assets_dependent",
            "dependency_impacted_assets": int(dependency_impacted_assets),
            "electric_health_global": {
                "storm": round(elec_health_global["storm"], 4),
                "storm_cmcc": round(elec_health_global["storm_cmcc"], 4),
            },
            "electric_health_resolution_rule": "local_territory_else_nearest_electric_territory_else_global",
            "electric_health_resolution_by_hazard": {
                hazard: {k: int(v) for k, v in src.items()}
                for hazard, src in health_resolution_by_hazard.items()
            },
            "state_thresholds": {
                "S0_to_S1_damage_ratio": 0.05,
                "S1_to_S2_damage_ratio": 0.15,
                "S2_to_S3_damage_ratio": 0.35,
            },
            "uplift_by_state": {"S0": 0.0, "S1": 0.10, "S2": 0.25, "S3": 0.45},
        },
        "event_summary": {
            "storm_top_events": [],
            "storm_cmcc_top_events": [],
        },
    }

    storm_ratio = storm_total / max(total_exposure, 1.0)
    cmcc_ratio = cmcc_total / max(total_exposure, 1.0)
    graphs = _build_fallback_graphs(total_exposure, storm_ratio, cmcc_ratio)

    notes = [
        "Fallback deterministic engine is active while CLIMADA production engine is disabled.",
        "Each asset receives a direct cyclone damage ratio, mapped to four states (S0/S1/S2/S3) and annualized into EAI.",
        "Component health uses: health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3) / L_total.",
        "Water assets are conservatively assumed dependent on electricity; weak local electrical health can escalate water states.",
        "Electricity-health lookup for water assets uses local territory, then nearest electric territory, then global fallback.",
        "Per-asset EAI is capped to asset exposure value: EAI_total <= exposure_eur.",
        "For uploads without explicit categories, default_exposure_category=habitation is applied unless overridden.",
    ]

    return ImpactComputationResult(
        engine="fallback_with_interdependency",
        territory_results=territory_results,
        portfolio_results=portfolio_results,
        graphs=graphs,
        notes=notes,
        asset_results=asset_results,
        modeling={
            "dependency_mode": "postprocess_electricity_to_water",
            "scenario_mode": "prudent",
            "fallback_reason": "explicit_fallback_mode",
            "indirect_monetary_uplift_enabled": False,
            "metric_family_classification": _metric_family_classification(),
        },
        matching_qa={
            "status": "not_available",
            "reason": "fallback_engine",
        },
    )


def compute_impacts(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    settings: Settings | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
    resume_enabled: bool = False,
    resume_dynamic_hazard_point_cap: int | None = None,
    prebuilt_bundle: ClimadaExposureBundle | None = None,
    hazard_keys: tuple[str, ...] | None = None,
    explicit_hazard_bundle: Any | None = None,
) -> ImpactComputationResult:
    runtime_settings = settings or load_settings()
    if bool(runtime_settings.allow_climada_fallback):
        raise ValueError(
            "SIB_RISK_ALLOW_CLIMADA_FALLBACK is no longer supported: scientific CLIMADA fallback has been removed."
        )
    if bool(runtime_settings.hazard_fallback_to_precomputed):
        raise ValueError(
            "SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED is no longer supported: dynamic hazard failures must stop the scientific run."
        )
    if not bool(runtime_settings.climada_strict_required_components):
        raise ValueError(
            "SIB_RISK_CLIMADA_STRICT_REQUIRED_COMPONENTS must remain enabled: incomplete multi-hazard scientific runs now fail explicitly."
        )
    mode = str(runtime_settings.impact_engine_mode or "climada").strip().lower()

    if mode == "fallback":
        raise ValueError("Scientific fallback impact mode has been removed; use 'climada'.")
    if mode not in {"climada", "auto"}:
        raise ValueError(f"Unsupported impact engine mode: {mode}")

    return _compute_impacts_climada(
        exposure,
        disagg,
        runtime_settings,
        progress_callback=progress_callback,
        checkpoint_dir=checkpoint_dir,
        resume_enabled=resume_enabled,
        resume_dynamic_hazard_point_cap=resume_dynamic_hazard_point_cap,
        prebuilt_bundle=prebuilt_bundle,
        hazard_keys=hazard_keys,
        explicit_hazard_bundle=explicit_hazard_bundle,
    )
