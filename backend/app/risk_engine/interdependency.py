from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any


STATE_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
STATE_THRESHOLDS = {
    "S0_to_S1_damage_ratio": 0.05,
    "S1_to_S2_damage_ratio": 0.15,
    "S2_to_S3_damage_ratio": 0.35,
}
HEALTH_WEIGHTS_BY_STATE = {"S1": 0.3, "S2": 0.7, "S3": 1.0}
DEPENDENCY_STATE_THRESHOLDS = {"S1": 0.75, "S2": 0.55, "S3": 0.35}
UPLIFT_BY_STATE = {"S0": 0.0, "S1": 0.10, "S2": 0.25, "S3": 0.45}
SERVICE_NAMES = ("elec", "water_aep", "water_eu")
ELECTRIC_NATIVE_GRID_DEG = 0.1
WATER_BLOCKING_ROLES_BY_SERVICE = {
    "water_aep": frozenset({"captage_aep", "upep_aep", "pompage_aep"}),
    "water_eu": frozenset({"step", "poste_refoulement"}),
}


@dataclass
class InterdependencyAggregationResult:
    territory_results: list[dict[str, Any]]
    asset_results: list[dict[str, Any]]
    portfolio_by_hazard: dict[str, dict[str, float]]
    component_health: dict[str, dict[str, dict[str, float]]]
    interdependency: dict[str, Any]
    dependency_scaler_by_hazard: dict[str, float]
    detailed_states_by_territory: dict[str, dict[str, dict[str, str]]] = None  # [hazard][territory][infra_classname] -> state
    cell_service_states_by_territory: dict[str, dict[str, dict[str, str]]] = None
    cell_service_coverage_by_territory: dict[str, dict[str, dict[str, bool]]] = None
    native_service_states_by_hazard: dict[str, dict[str, dict[str, dict[str, Any]]]] = None
    projected_service_states_by_territory: dict[str, dict[str, dict[str, str]]] = None
    projected_service_coverage_by_territory: dict[str, dict[str, dict[str, bool]]] = None
    projected_service_units_by_territory: dict[str, dict[str, dict[str, str]]] = None
    state_aggregation_metadata: dict[str, Any] = None


def _new_state_bucket() -> dict[str, float]:
    return {"total": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0, "asset_count": 0.0}


def _new_service_loss_bucket() -> dict[str, float]:
    return {"exposure": 0.0, "direct_max_loss": 0.0}


def _new_service_loss_map() -> dict[str, dict[str, float]]:
    return {service: _new_service_loss_bucket() for service in SERVICE_NAMES}


def _new_service_state_map() -> dict[str, str]:
    return {service: "S0" for service in SERVICE_NAMES}


def _new_service_coverage_map() -> dict[str, bool]:
    return {service: False for service in SERVICE_NAMES}


def _new_native_service_metric_bucket() -> dict[str, float]:
    return {
        "exposure": 0.0,
        "direct_max_loss": 0.0,
        "asset_count": 0.0,
        "exposed_asset_count": 0.0,
    }


def _new_native_service_metric_map() -> dict[str, dict[str, float]]:
    return {service: _new_native_service_metric_bucket() for service in SERVICE_NAMES}


def _grid_cell_id(lat: Any, lon: Any, step_deg: float) -> str | None:
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    lat_bin = round(float(lat) / step_deg) * step_deg
    lon_bin = round(float(lon) / step_deg) * step_deg
    return f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}"


def _parse_cell_id_center(cell_id: str) -> tuple[float | None, float | None]:
    text = str(cell_id or "").strip()
    if not text.startswith("cell-") or "_" not in text:
        return None, None
    try:
        lat_txt, lon_txt = text[5:].split("_", 1)
        return float(lat_txt), float(lon_txt)
    except ValueError:
        return None, None


def _bucket_add_state(bucket: dict[str, float], *, state: str, weight: float) -> None:
    bucket["total"] += float(weight)
    bucket["asset_count"] += 1.0
    if state in {"S1", "S2", "S3"}:
        bucket[state] += float(weight)


def _coerce_state_thresholds(state_thresholds: dict[str, float] | None) -> dict[str, float]:
    merged = dict(STATE_THRESHOLDS)
    for key, value in (state_thresholds or {}).items():
        if key in merged:
            merged[key] = float(value)
    return merged


def _coerce_health_weights(health_weights_by_state: dict[str, float] | None) -> dict[str, float]:
    merged = dict(HEALTH_WEIGHTS_BY_STATE)
    for key, value in (health_weights_by_state or {}).items():
        if key in merged:
            merged[key] = float(value)
    return merged


def _coerce_dependency_state_thresholds(
    dependency_state_thresholds: dict[str, float] | None,
) -> dict[str, float]:
    merged = dict(DEPENDENCY_STATE_THRESHOLDS)
    for key, value in (dependency_state_thresholds or {}).items():
        if key in merged:
            merged[key] = float(value)
    return merged


def _coerce_uplift_by_state(uplift_by_state: dict[str, float] | None) -> dict[str, float]:
    merged = dict(UPLIFT_BY_STATE)
    for key, value in (uplift_by_state or {}).items():
        if key in merged:
            merged[key] = float(value)
    return merged


def _health_from_bucket(
    bucket: dict[str, float],
    *,
    health_weights_by_state: dict[str, float] | None = None,
) -> float:
    total = float(bucket.get("total", 0.0))
    if total <= 0.0:
        return 1.0
    weights = _coerce_health_weights(health_weights_by_state)
    weighted = (
        float(weights["S1"]) * float(bucket.get("S1", 0.0))
        + float(weights["S2"]) * float(bucket.get("S2", 0.0))
        + float(weights["S3"]) * float(bucket.get("S3", 0.0))
    )
    return max(0.0, min(1.0, 1.0 - (weighted / total)))


def _state_from_damage_ratio(
    damage_ratio: float,
    *,
    state_thresholds: dict[str, float] | None = None,
) -> str:
    thresholds = _coerce_state_thresholds(state_thresholds)
    if damage_ratio >= thresholds["S2_to_S3_damage_ratio"]:
        return "S3"
    if damage_ratio >= thresholds["S1_to_S2_damage_ratio"]:
        return "S2"
    if damage_ratio >= thresholds["S0_to_S1_damage_ratio"]:
        return "S1"
    return "S0"


def _dependency_state_from_elec_health(
    health: float,
    *,
    dependency_state_thresholds: dict[str, float] | None = None,
) -> str:
    thresholds = _coerce_dependency_state_thresholds(dependency_state_thresholds)
    if health < thresholds["S3"]:
        return "S3"
    if health < thresholds["S2"]:
        return "S2"
    if health < thresholds["S1"]:
        return "S1"
    return "S0"


def _infra_class_to_standardized_name(infra_class: str, *, asset_type: str | None = None) -> str:
    """
    Map infrastructure records to standardized names for social impact metrics.

    Uses asset_type first so potable and wastewater assets are not merged when they
    share the same infra_class bucket.
    """
    infra_class_lower = str(infra_class or "").strip().lower()
    asset_type_lower = str(asset_type or "").strip().lower()

    if "elec" in infra_class_lower or asset_type_lower.startswith("elec_"):
        return "elec"

    if (
        asset_type_lower.startswith("eau_aep")
        or "_aep_" in asset_type_lower
        or "potable" in asset_type_lower
        or "drinking" in asset_type_lower
    ):
        return "water_aep"
    if (
        asset_type_lower.startswith("eau_eu")
        or "_eu_" in asset_type_lower
        or "assain" in asset_type_lower
        or "waste" in asset_type_lower
        or "sewer" in asset_type_lower
    ):
        return "water_eu"

    if "eau" in infra_class_lower or "water" in infra_class_lower:
        if (
            "eu" in infra_class_lower
            or "used" in infra_class_lower
            or "waste" in infra_class_lower
            or "assain" in infra_class_lower
        ):
            return "water_eu"
        return "water_aep"

    return "other"


def _water_service_feature_id(rec: dict[str, Any]) -> str | None:
    for key in ("service_feature_id", "zone_component_key"):
        value = str(rec.get(key) or "").strip()
        if value:
            return value
    return None


def _water_feature_role(rec: dict[str, Any]) -> str:
    return str(rec.get("feature_role") or "").strip().lower()


def _is_water_network_record(rec: dict[str, Any], *, infra_class: str) -> bool:
    infra_class_lower = str(infra_class or "").strip().lower()
    if infra_class_lower == "eau_reseau":
        return True
    if _water_feature_role(rec) == "canalisation":
        return True
    asset_type = str(rec.get("asset_type") or "").strip().lower()
    return asset_type in {"eau_aep_cana", "eau_eu_cana"}


def _is_blocking_water_asset(
    rec: dict[str, Any],
    *,
    infra_standardized_name: str,
    infra_class: str,
) -> bool:
    if str(infra_class or "").strip().lower() != "eau_ouvrage":
        return False
    return _water_feature_role(rec) in WATER_BLOCKING_ROLES_BY_SERVICE.get(infra_standardized_name, frozenset())


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2) + math.cos(lat1r) * math.cos(lat2r) * (math.sin(dlon / 2.0) ** 2)
    return r * (2.0 * math.asin(math.sqrt(a)))


def _resolve_electric_health(
    *,
    hazard: str,
    territory_id: str,
    lat: Any,
    lon: Any,
    elec_health_by_territory: dict[str, dict[str, float]],
    elec_health_global: dict[str, float],
    elec_territory_centroids: dict[str, tuple[float, float]],
) -> tuple[float, str]:
    by_territory = elec_health_by_territory.get(hazard, {})
    if territory_id in by_territory:
        return float(by_territory[territory_id]), "local_territory"

    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and elec_territory_centroids:
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


def _summarize_component_health(
    buckets_by_class: dict[str, dict[str, float]],
    *,
    health_weights_by_state: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for infra_class, bucket in buckets_by_class.items():
        total = float(bucket.get("total", 0.0))
        s1 = float(bucket.get("S1", 0.0))
        s2 = float(bucket.get("S2", 0.0))
        s3 = float(bucket.get("S3", 0.0))
        out[infra_class] = {
            "health": round(_health_from_bucket(bucket, health_weights_by_state=health_weights_by_state), 4),
            "L_total": round(total, 4),
            "L_S1": round(s1, 4),
            "L_S2": round(s2, 4),
            "L_S3": round(s3, 4),
            "asset_count": int(bucket.get("asset_count", 0.0)),
        }
    return out


def _build_native_service_state_row(
    *,
    service: str,
    service_unit_id: str,
    degraded_share: float,
    state: str,
    state_basis: str,
    asset_count: float,
    exposed_asset_count: float,
) -> dict[str, Any]:
    return {
        "service_unit_id": str(service_unit_id),
        "service": str(service),
        "network_metric": "service_state",
        "degraded_share": round(max(0.0, degraded_share), 6),
        "state": str(state),
        "state_basis": str(state_basis),
        "asset_count": int(asset_count),
        "exposed_asset_count": int(exposed_asset_count),
    }


def aggregate_impacts_with_interdependency(
    *,
    point_records: list[dict[str, Any]],
    hazard_direct_eai: dict[str, list[float]],
    hazard_max_loss: dict[str, list[float]],
    state_thresholds: dict[str, float] | None = None,
    health_weights_by_state: dict[str, float] | None = None,
    dependency_state_thresholds: dict[str, float] | None = None,
    uplift_by_state: dict[str, float] | None = None,
) -> InterdependencyAggregationResult:
    hazard_keys = tuple(hazard_direct_eai.keys())
    effective_state_thresholds = _coerce_state_thresholds(state_thresholds)
    effective_health_weights = _coerce_health_weights(health_weights_by_state)
    effective_dependency_thresholds = _coerce_dependency_state_thresholds(dependency_state_thresholds)
    effective_uplift = _coerce_uplift_by_state(uplift_by_state)
    disabled_uplift = {state: 0.0 for state in effective_uplift}
    elec_classes = {"elec_aerien", "elec_souterrain"}
    water_classes = {"eau_reseau", "eau_ouvrage"}

    elec_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in hazard_keys
    }
    elec_global_bucket: dict[str, dict[str, float]] = {hazard: _new_state_bucket() for hazard in hazard_keys}
    elec_territory_loc_acc: dict[str, dict[str, float]] = {}
    native_service_metrics_by_hazard: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        hazard: defaultdict(_new_native_service_metric_map) for hazard in hazard_keys
    }
    native_service_loc_acc_by_hazard: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        hazard: defaultdict(lambda: defaultdict(lambda: {"lat_sum": 0.0, "lon_sum": 0.0, "count": 0.0}))
        for hazard in hazard_keys
    }
    dominant_water_unit_by_territory: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    dominant_elec_unit_by_territory: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for idx, rec in enumerate(point_records):
        value = max(0.0, float(rec.get("value_eur", 0.0)))
        infra_class = str(rec.get("infra_class") or "habitation")
        if infra_class not in elec_classes:
            continue
        territory_id = _grid_cell_id(rec.get("lat"), rec.get("lon"), ELECTRIC_NATIVE_GRID_DEG) or str(
            rec.get("territory_id") or "uploaded-aggregate"
        )
        lat = rec.get("lat")
        lon = rec.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            loc = elec_territory_loc_acc.setdefault(territory_id, {"lat_sum": 0.0, "lon_sum": 0.0, "count": 0.0})
            loc["lat_sum"] += float(lat)
            loc["lon_sum"] += float(lon)
            loc["count"] += 1.0
        for hazard in hazard_keys:
            direct_max_loss = max(0.0, float(hazard_max_loss[hazard][idx]))
            ratio = direct_max_loss / max(value, 1.0)
            state = _state_from_damage_ratio(ratio, state_thresholds=effective_state_thresholds)
            _bucket_add_state(elec_buckets_by_hazard[hazard][territory_id], state=state, weight=value)
            _bucket_add_state(elec_global_bucket[hazard], state=state, weight=value)

    elec_health_by_territory: dict[str, dict[str, float]] = {
        hazard: {
            territory_id: _health_from_bucket(bucket, health_weights_by_state=effective_health_weights)
            for territory_id, bucket in buckets.items()
        }
        for hazard, buckets in elec_buckets_by_hazard.items()
    }
    elec_health_global = {
        hazard: _health_from_bucket(bucket, health_weights_by_state=effective_health_weights)
        for hazard, bucket in elec_global_bucket.items()
    }
    elec_territory_centroids = {
        tid: (loc["lat_sum"] / loc["count"], loc["lon_sum"] / loc["count"])
        for tid, loc in elec_territory_loc_acc.items()
        if loc.get("count", 0.0) > 0.0
    }

    territory_acc: dict[str, dict[str, Any]] = {}
    asset_acc: dict[str, dict[str, Any]] = {}
    component_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in hazard_keys
    }
    dependency_impacted_assets_by_hazard = {hazard: 0 for hazard in hazard_keys}
    dependency_impacted_feature_hazard: set[tuple[str, str]] = set()
    health_resolution_by_hazard = {
        hazard: {"local_territory": 0, "nearest_territory": 0, "global": 0}
        for hazard in hazard_keys
    }
    
    # Track detailed states for social impact metrics: [hazard][territory][infra_standardized_name] = state
    detailed_states_by_territory: dict[str, dict[str, dict[str, str]]] = {
        hazard: defaultdict(lambda: {
            "elec": "S0",
            "water_aep": "S0",
            "water_eu": "S0",
        })
        for hazard in hazard_keys
    }

    point_state_rows_by_hazard: dict[str, list[dict[str, Any]]] = {
        hazard: [{} for _ in point_records]
        for hazard in hazard_keys
    }
    blocking_service_state_by_hazard: dict[str, dict[str, str]] = {
        hazard: {}
        for hazard in hazard_keys
    }

    for idx, rec in enumerate(point_records):
        territory_id = str(rec.get("territory_id") or "uploaded-aggregate")
        lat = rec.get("lat")
        lon = rec.get("lon")
        infra_class = str(rec.get("infra_class") or "habitation")
        value = max(0.0, float(rec.get("value_eur", 0.0)))
        infra_std_name = _infra_class_to_standardized_name(
            infra_class,
            asset_type=str(rec.get("asset_type") or ""),
        )
        service_feature_id = _water_service_feature_id(rec) if infra_class in water_classes else None
        is_service_network = _is_water_network_record(rec, infra_class=infra_class) if infra_class in water_classes else False
        is_blocking_asset = _is_blocking_water_asset(
            rec,
            infra_standardized_name=infra_std_name,
            infra_class=infra_class,
        ) if infra_class in water_classes else False
        electric_native_unit_id = _grid_cell_id(lat, lon, ELECTRIC_NATIVE_GRID_DEG) or territory_id
        if infra_std_name == "elec":
            dominant_elec_unit_by_territory[territory_id][electric_native_unit_id] += value
        elif infra_std_name in {"water_aep", "water_eu"}:
            dominant_water_unit_id = str(service_feature_id or territory_id)
            dominant_water_unit_by_territory[territory_id][infra_std_name][dominant_water_unit_id] += value

        for hazard in hazard_keys:
            direct_eai = min(value, max(0.0, float(hazard_direct_eai[hazard][idx])))
            direct_max_loss = max(0.0, float(hazard_max_loss[hazard][idx]))
            direct_ratio = direct_max_loss / max(value, 1.0)
            direct_state = _state_from_damage_ratio(direct_ratio, state_thresholds=effective_state_thresholds)
            final_state = direct_state

            if infra_class in water_classes:
                elec_health, source = _resolve_electric_health(
                    hazard=hazard,
                    territory_id=territory_id,
                    lat=lat,
                    lon=lon,
                    elec_health_by_territory=elec_health_by_territory,
                    elec_health_global=elec_health_global,
                    elec_territory_centroids=elec_territory_centroids,
                )
                health_resolution_by_hazard[hazard][source] += 1
                dependency_state = _dependency_state_from_elec_health(
                    elec_health,
                    dependency_state_thresholds=effective_dependency_thresholds,
                )
                if STATE_ORDER[dependency_state] > STATE_ORDER[direct_state]:
                    final_state = dependency_state

            point_state_rows_by_hazard[hazard][idx] = {
                "direct_eai": direct_eai,
                "direct_max_loss": direct_max_loss,
                "direct_state": direct_state,
                "final_state": final_state,
                "infra_standardized_name": infra_std_name,
                "service_feature_id": service_feature_id,
                "is_service_network": is_service_network,
                "electric_native_unit_id": electric_native_unit_id,
            }

            if is_blocking_asset and service_feature_id and STATE_ORDER[final_state] > STATE_ORDER[blocking_service_state_by_hazard[hazard].get(service_feature_id, "S0")]:
                blocking_service_state_by_hazard[hazard][service_feature_id] = final_state

    for idx, rec in enumerate(point_records):
        territory_id = str(rec.get("territory_id") or "uploaded-aggregate")
        territory_label = str(rec.get("territory_label") or "Uploaded Exposure (aggregate)")
        lat = rec.get("lat")
        lon = rec.get("lon")
        infra_class = str(rec.get("infra_class") or "habitation")
        feature_id = str(rec.get("feature_id") or rec.get("point_id") or f"idx-{idx}")
        value = max(0.0, float(rec.get("value_eur", 0.0)))

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
        row["exposure_eur"] += value
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            row["lat_sum"] += float(lat)
            row["lon_sum"] += float(lon)
            row["loc_count"] += 1

        asset_row = asset_acc.setdefault(
            feature_id,
            {
                "asset_id": feature_id,
                "asset_label": str(rec.get("label") or feature_id),
                "geometry_type": str(rec.get("geometry_type") or "Unknown"),
                "asset_type": str(rec.get("asset_type") or ""),
                "service_feature_id": str(rec.get("service_feature_id") or rec.get("zone_component_key") or ""),
                "zone_component_key": str(rec.get("zone_component_key") or rec.get("service_feature_id") or ""),
                "zone_uid": str(rec.get("zone_uid") or ""),
                "network_kind": str(rec.get("network_kind") or ""),
                "feature_role": str(rec.get("feature_role") or ""),
                "criticality": str(rec.get("criticality") or ""),
                "uses_default_value": bool(rec.get("uses_default_value")),
                "valuation_source": str(rec.get("valuation_source") or ""),
                "valuation_version": str(rec.get("valuation_version") or ""),
                "default_value_eur": rec.get("default_value_eur"),
                "exposure_eur": 0.0,
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        )
        asset_row["uses_default_value"] = bool(asset_row.get("uses_default_value")) or bool(rec.get("uses_default_value"))
        if not asset_row.get("valuation_source") and rec.get("valuation_source"):
            asset_row["valuation_source"] = str(rec.get("valuation_source") or "")
        if not asset_row.get("valuation_version") and rec.get("valuation_version"):
            asset_row["valuation_version"] = str(rec.get("valuation_version") or "")
        if asset_row.get("default_value_eur") is None and rec.get("default_value_eur") is not None:
            asset_row["default_value_eur"] = rec.get("default_value_eur")
        if not asset_row.get("service_feature_id") and (rec.get("service_feature_id") or rec.get("zone_component_key")):
            asset_row["service_feature_id"] = str(rec.get("service_feature_id") or rec.get("zone_component_key") or "")
        if not asset_row.get("zone_component_key") and (rec.get("zone_component_key") or rec.get("service_feature_id")):
            asset_row["zone_component_key"] = str(rec.get("zone_component_key") or rec.get("service_feature_id") or "")
        if not asset_row.get("zone_uid") and rec.get("zone_uid"):
            asset_row["zone_uid"] = str(rec.get("zone_uid") or "")
        if not asset_row.get("network_kind") and rec.get("network_kind"):
            asset_row["network_kind"] = str(rec.get("network_kind") or "")
        if not asset_row.get("feature_role") and rec.get("feature_role"):
            asset_row["feature_role"] = str(rec.get("feature_role") or "")
        if not asset_row.get("criticality") and rec.get("criticality"):
            asset_row["criticality"] = str(rec.get("criticality") or "")
        asset_row["exposure_eur"] += value

        for hazard in hazard_keys:
            state_row = point_state_rows_by_hazard[hazard][idx]
            direct_eai = float(state_row["direct_eai"])
            direct_max_loss = float(state_row["direct_max_loss"])
            direct_state = str(state_row["direct_state"])
            final_state = str(state_row["final_state"])
            indirect_eai = 0.0
            infra_std_name = str(state_row["infra_standardized_name"])
            service_feature_id = state_row.get("service_feature_id")

            if infra_std_name != "other":
                if infra_std_name == "elec":
                    native_unit_id = str(state_row.get("electric_native_unit_id") or territory_id)
                else:
                    native_unit_id = str(service_feature_id or territory_id)
                service_loss_bucket = native_service_metrics_by_hazard[hazard][native_unit_id][infra_std_name]
                service_loss_bucket["exposure"] += value
                service_loss_bucket["direct_max_loss"] += direct_max_loss
                service_loss_bucket["asset_count"] += 1.0
                if direct_max_loss > 0.0:
                    service_loss_bucket["exposed_asset_count"] += 1.0
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    loc_acc = native_service_loc_acc_by_hazard[hazard][infra_std_name][native_unit_id]
                    loc_acc["lat_sum"] += float(lat)
                    loc_acc["lon_sum"] += float(lon)
                    loc_acc["count"] += 1.0

            if bool(state_row.get("is_service_network")) and service_feature_id:
                blocker_state = blocking_service_state_by_hazard[hazard].get(str(service_feature_id))
                if blocker_state and STATE_ORDER[blocker_state] > STATE_ORDER[final_state]:
                    final_state = blocker_state

            if STATE_ORDER[final_state] > STATE_ORDER[direct_state]:
                dependency_impacted_feature_hazard.add((feature_id, hazard))

            total_eai = min(value, direct_eai + indirect_eai)
            indirect_eai = max(0.0, total_eai - direct_eai)
            if hazard == "storm":
                row["eai_storm_direct_eur"] += direct_eai
                row["eai_storm_indirect_eur"] += indirect_eai
                row["eai_storm_eur"] += total_eai
                asset_row["eai_storm_direct_eur"] += direct_eai
                asset_row["eai_storm_indirect_eur"] += indirect_eai
                asset_row["eai_storm_eur"] += total_eai
            elif hazard == "storm_cmcc":
                row["eai_cmcc_direct_eur"] += direct_eai
                row["eai_cmcc_indirect_eur"] += indirect_eai
                row["eai_cmcc_eur"] += total_eai
                asset_row["eai_cmcc_direct_eur"] += direct_eai
                asset_row["eai_cmcc_indirect_eur"] += indirect_eai
                asset_row["eai_cmcc_eur"] += total_eai
            _bucket_add_state(component_buckets_by_hazard[hazard][infra_class], state=final_state, weight=value)
            
            # Update detailed states for social impact metrics
            # Keep worst state (highest order) seen for each infrastructure type
            if infra_std_name != "other":
                current_state = detailed_states_by_territory[hazard][territory_id].get(infra_std_name, "S0")
                if STATE_ORDER.get(final_state, 0) > STATE_ORDER.get(current_state, 0):
                    detailed_states_by_territory[hazard][territory_id][infra_std_name] = final_state

    for _, hazard in dependency_impacted_feature_hazard:
        dependency_impacted_assets_by_hazard[hazard] += 1

    territory_results: list[dict[str, Any]] = []
    for row in territory_acc.values():
        exp_eur = float(row["exposure_eur"])
        eai_storm = float(row["eai_storm_eur"])
        eai_cmcc = float(row["eai_cmcc_eur"])
        risk_index_storm = max(0.0, min(100.0, (eai_storm / max(exp_eur, 1.0)) * 1000.0))
        risk_index_cmcc = max(0.0, min(100.0, (eai_cmcc / max(exp_eur, 1.0)) * 1000.0))
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
                "exposure_eur": 0.0,
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
        risk_index_storm = max(0.0, min(100.0, (eai_storm / max(exp_eur, 1.0)) * 1000.0))
        risk_index_cmcc = max(0.0, min(100.0, (eai_cmcc / max(exp_eur, 1.0)) * 1000.0))
        asset_results.append(
            {
                "asset_id": row["asset_id"],
                "asset_label": row["asset_label"],
                "geometry_type": row["geometry_type"],
                "asset_type": row["asset_type"],
                "service_feature_id": str(row.get("service_feature_id") or ""),
                "zone_component_key": str(row.get("zone_component_key") or ""),
                "zone_uid": str(row.get("zone_uid") or ""),
                "network_kind": str(row.get("network_kind") or ""),
                "feature_role": str(row.get("feature_role") or ""),
                "criticality": str(row.get("criticality") or ""),
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

    portfolio_by_hazard: dict[str, dict[str, float]] = {}
    scaler_by_hazard: dict[str, float] = {}
    for hazard in hazard_keys:
        if hazard == "storm":
            eai_direct = sum(float(row["eai_storm_direct_eur"]) for row in territory_results)
            eai_indirect = sum(float(row["eai_storm_indirect_eur"]) for row in territory_results)
            eai_total = sum(float(row["eai_storm_eur"]) for row in territory_results)
        else:
            eai_direct = sum(float(row["eai_cmcc_direct_eur"]) for row in territory_results)
            eai_indirect = sum(float(row["eai_cmcc_indirect_eur"]) for row in territory_results)
            eai_total = sum(float(row["eai_cmcc_eur"]) for row in territory_results)
        portfolio_by_hazard[hazard] = {
            "eai_direct_eur": round(eai_direct, 2),
            "eai_indirect_eur": round(eai_indirect, 2),
            "eai_total_eur": round(eai_total, 2),
        }
        scaler_by_hazard[hazard] = float(eai_total / max(eai_direct, 1.0))

    component_health = {
        hazard: _summarize_component_health(
            dict(class_buckets),
            health_weights_by_state=effective_health_weights,
        )
        for hazard, class_buckets in component_buckets_by_hazard.items()
    }

    native_service_states_by_hazard: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
        hazard: {service: {} for service in SERVICE_NAMES}
        for hazard in hazard_keys
    }
    projected_service_states_by_territory: dict[str, dict[str, dict[str, str]]] = {
        hazard: defaultdict(_new_service_state_map) for hazard in hazard_keys
    }
    projected_service_coverage_by_territory: dict[str, dict[str, dict[str, bool]]] = {
        hazard: defaultdict(_new_service_coverage_map) for hazard in hazard_keys
    }
    projected_service_units_by_territory: dict[str, dict[str, dict[str, str]]] = {
        hazard: defaultdict(dict) for hazard in hazard_keys
    }
    for hazard in hazard_keys:
        local_elec_health = elec_health_by_territory.get(hazard, {})
        native_units = native_service_metrics_by_hazard[hazard]
        for native_unit_id, service_loss_map in native_units.items():
            elec_loss = service_loss_map["elec"]
            if float(elec_loss["exposure"]) > 0.0:
                elec_ratio = float(elec_loss["direct_max_loss"]) / max(float(elec_loss["exposure"]), 1.0)
                native_service_states_by_hazard[hazard]["elec"][native_unit_id] = _build_native_service_state_row(
                    service="elec",
                    service_unit_id=native_unit_id,
                    degraded_share=elec_ratio,
                    state=_state_from_damage_ratio(elec_ratio, state_thresholds=effective_state_thresholds),
                    state_basis="aggregated_damage_ratio_on_fixed_grid_0p1deg",
                    asset_count=elec_loss["asset_count"],
                    exposed_asset_count=elec_loss["exposed_asset_count"],
                )
            for water_service in ("water_aep", "water_eu"):
                water_loss = service_loss_map[water_service]
                if float(water_loss["exposure"]) <= 0.0:
                    continue
                water_ratio = float(water_loss["direct_max_loss"]) / max(float(water_loss["exposure"]), 1.0)
                water_state = _state_from_damage_ratio(
                    water_ratio,
                    state_thresholds=effective_state_thresholds,
                )
                loc_acc = native_service_loc_acc_by_hazard[hazard][water_service].get(native_unit_id, {})
                unit_lat = None
                unit_lon = None
                if float(loc_acc.get("count", 0.0)) > 0.0:
                    unit_lat = float(loc_acc["lat_sum"]) / float(loc_acc["count"])
                    unit_lon = float(loc_acc["lon_sum"]) / float(loc_acc["count"])
                elec_health, _ = _resolve_electric_health(
                    hazard=hazard,
                    territory_id=_grid_cell_id(unit_lat, unit_lon, ELECTRIC_NATIVE_GRID_DEG) or native_unit_id,
                    lat=unit_lat,
                    lon=unit_lon,
                    elec_health_by_territory=elec_health_by_territory,
                    elec_health_global=elec_health_global,
                    elec_territory_centroids=elec_territory_centroids,
                )
                dependency_state = _dependency_state_from_elec_health(
                    elec_health,
                    dependency_state_thresholds=effective_dependency_thresholds,
                )
                final_state = water_state
                state_basis = "aggregated_damage_ratio_on_zone_component_key"
                if STATE_ORDER[dependency_state] > STATE_ORDER[water_state]:
                    final_state = dependency_state
                    state_basis = "aggregated_damage_ratio_plus_electric_dependency_on_zone_component_key"
                blocker_state = blocking_service_state_by_hazard[hazard].get(native_unit_id)
                if blocker_state and STATE_ORDER[blocker_state] > STATE_ORDER[final_state]:
                    final_state = blocker_state
                    state_basis = f"{state_basis}_plus_blocking_asset"
                native_service_states_by_hazard[hazard][water_service][native_unit_id] = _build_native_service_state_row(
                    service=water_service,
                    service_unit_id=native_unit_id,
                    degraded_share=water_ratio,
                    state=final_state,
                    state_basis=state_basis,
                    asset_count=water_loss["asset_count"],
                    exposed_asset_count=water_loss["exposed_asset_count"],
                )

        for territory_id in {str(rec.get("territory_id") or "uploaded-aggregate") for rec in point_records}:
            state_row = projected_service_states_by_territory[hazard][territory_id]
            coverage_row = projected_service_coverage_by_territory[hazard][territory_id]

            territory_lat, territory_lon = _parse_cell_id_center(territory_id)
            electric_native_unit_id = _grid_cell_id(territory_lat, territory_lon, ELECTRIC_NATIVE_GRID_DEG)
            if not electric_native_unit_id:
                elec_weights = dominant_elec_unit_by_territory.get(territory_id, {})
                if elec_weights:
                    electric_native_unit_id = max(
                        elec_weights.items(),
                        key=lambda item: (float(item[1]), str(item[0])),
                    )[0]
            if electric_native_unit_id and electric_native_unit_id in native_service_states_by_hazard[hazard]["elec"]:
                coverage_row["elec"] = True
                state_row["elec"] = str(
                    native_service_states_by_hazard[hazard]["elec"][electric_native_unit_id]["state"]
                )
                projected_service_units_by_territory[hazard][territory_id]["elec"] = str(electric_native_unit_id)

            for water_service in ("water_aep", "water_eu"):
                water_weights = dominant_water_unit_by_territory.get(territory_id, {}).get(water_service, {})
                if not water_weights:
                    continue
                service_unit_id = max(
                    water_weights.items(),
                    key=lambda item: (float(item[1]), str(item[0])),
                )[0]
                native_state = native_service_states_by_hazard[hazard][water_service].get(service_unit_id)
                if not native_state:
                    continue
                coverage_row[water_service] = True
                state_row[water_service] = str(native_state["state"])
                projected_service_units_by_territory[hazard][territory_id][water_service] = str(service_unit_id)

    interdependency = {
        "electricity_to_water_enabled": True,
        "electricity_to_water_monetary_uplift_enabled": False,
        "water_service_outage_enabled": True,
        "water_service_unit": "zone_component_key",
        "electric_state_unit": "fixed_grid_0p1deg",
        "water_assets_dependency_assumption": "all_water_assets_dependent",
        "water_service_blocking_roles": {
            service_name: sorted(roles)
            for service_name, roles in WATER_BLOCKING_ROLES_BY_SERVICE.items()
        },
        "dependency_impacted_assets": int(sum(dependency_impacted_assets_by_hazard.values())),
        "dependency_impacted_assets_by_hazard": {k: int(v) for k, v in dependency_impacted_assets_by_hazard.items()},
        "electric_health_global": {hazard: round(elec_health_global[hazard], 4) for hazard in hazard_keys},
        "electric_health_resolution_rule": "local_territory_else_nearest_electric_territory_else_global",
        "electric_health_resolution_by_hazard": {
            hazard: {k: int(v) for k, v in src.items()}
            for hazard, src in health_resolution_by_hazard.items()
        },
        "state_thresholds": effective_state_thresholds,
        "health_weights_by_state": effective_health_weights,
        "dependency_state_thresholds": effective_dependency_thresholds,
        "uplift_by_state": disabled_uplift,
    }
    state_aggregation_metadata = {
        "schema_version": "aggregated_service_state_v1",
        "electric_state_unit": "fixed_grid_0p1deg",
        "water_state_unit": "zone_component_key",
        "aggregation_method": "aggregated_service_state",
        "projection_method": (
            "elec:population_cell_centroid_to_fixed_0p1deg;"
            "water:dominant_zone_component_by_exposure_within_population_cell"
        ),
        "state_thresholds_used": effective_state_thresholds,
    }

    return InterdependencyAggregationResult(
        territory_results=territory_results,
        asset_results=asset_results,
        portfolio_by_hazard=portfolio_by_hazard,
        component_health=component_health,
        interdependency=interdependency,
        dependency_scaler_by_hazard=scaler_by_hazard,
        detailed_states_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in detailed_states_by_territory.items()
        },
        cell_service_states_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in projected_service_states_by_territory.items()
        },
        cell_service_coverage_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in projected_service_coverage_by_territory.items()
        },
        native_service_states_by_hazard=native_service_states_by_hazard,
        projected_service_states_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in projected_service_states_by_territory.items()
        },
        projected_service_coverage_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in projected_service_coverage_by_territory.items()
        },
        projected_service_units_by_territory={
            hazard: dict(states_dict) for hazard, states_dict in projected_service_units_by_territory.items()
        },
        state_aggregation_metadata=state_aggregation_metadata,
    )
