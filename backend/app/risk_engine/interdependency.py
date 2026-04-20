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


@dataclass
class InterdependencyAggregationResult:
    territory_results: list[dict[str, Any]]
    asset_results: list[dict[str, Any]]
    portfolio_by_hazard: dict[str, dict[str, float]]
    component_health: dict[str, dict[str, dict[str, float]]]
    interdependency: dict[str, Any]
    dependency_scaler_by_hazard: dict[str, float]
    detailed_states_by_territory: dict[str, dict[str, dict[str, str]]] = None  # [hazard][territory][infra_classname] -> state


def _new_state_bucket() -> dict[str, float]:
    return {"total": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0, "asset_count": 0.0}


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


def _infra_class_to_standardized_name(infra_class: str) -> str:
    """
    Map infrastructure class to standardized names for social impact metrics.

    Maps asset types to: "elec", "water_aep", "water_eu", or "other"
    """
    infra_class_lower = str(infra_class or "").lower()
    
    # Electricity
    if "elec" in infra_class_lower:
        return "elec"
    
    # Water - requires distinguishing between AEP (potable) and EU (wastewater)
    if "eau" in infra_class_lower or "water" in infra_class_lower:
        # Try to distinguish AEP vs EU from asset_type if needed
        # For now, default based on common patterns
        if "eu" in infra_class_lower or "used" in infra_class_lower or "waste" in infra_class_lower:
            return "water_eu"
        else:
            return "water_aep"
    
    return "other"


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
    elec_classes = {"elec_aerien", "elec_souterrain"}
    water_classes = {"eau_reseau", "eau_ouvrage"}

    elec_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in hazard_keys
    }
    elec_global_bucket: dict[str, dict[str, float]] = {hazard: _new_state_bucket() for hazard in hazard_keys}
    elec_territory_loc_acc: dict[str, dict[str, float]] = {}

    for idx, rec in enumerate(point_records):
        value = max(0.0, float(rec.get("value_eur", 0.0)))
        infra_class = str(rec.get("infra_class") or "habitation")
        if infra_class not in elec_classes:
            continue
        territory_id = str(rec.get("territory_id") or "uploaded-aggregate")
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
                "exposure_eur": 0.0,
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        )
        asset_row["exposure_eur"] += value

        for hazard in hazard_keys:
            direct_eai = min(value, max(0.0, float(hazard_direct_eai[hazard][idx])))
            direct_max_loss = max(0.0, float(hazard_max_loss[hazard][idx]))
            direct_ratio = direct_max_loss / max(value, 1.0)
            direct_state = _state_from_damage_ratio(direct_ratio, state_thresholds=effective_state_thresholds)
            final_state = direct_state
            indirect_eai = 0.0

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
                    dependency_impacted_feature_hazard.add((feature_id, hazard))
                    final_state = dependency_state
                indirect_eai = max(0.0, direct_eai * effective_uplift[dependency_state])

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
            infra_std_name = _infra_class_to_standardized_name(infra_class)
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

    interdependency = {
        "electricity_to_water_enabled": True,
        "water_assets_dependency_assumption": "all_water_assets_dependent",
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
        "uplift_by_state": effective_uplift,
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
    )
