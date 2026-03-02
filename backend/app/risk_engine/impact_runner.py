from __future__ import annotations

from collections import defaultdict
from hashlib import blake2b
from typing import Any
import math

from .types import DisaggregationSummary, ImpactComputationResult, NormalizedExposure


TERRITORY_GRID_DEG = 0.2
HAZARD_KEYS = ("storm", "storm_cmcc")
STATE_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
STATE_DAMAGE_FLOOR = {"S0": 0.0, "S1": 0.07, "S2": 0.2, "S3": 0.45}
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


def _safe_label(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-") or "territory"


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
    return {
        "total": 0.0,
        "S1": 0.0,
        "S2": 0.0,
        "S3": 0.0,
        "asset_count": 0.0,
    }


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


def _build_fec_curve(total_exposure_eur: float, ratio: float, lifetime_years: int | None = None) -> dict[str, Any]:
    return_periods = [1, 2, 5, 10, 20, 30, 50, 75, 100, 150, 200]
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


def _build_graphs(total_exposure: float, storm_ratio: float, cmcc_ratio: float) -> dict[str, Any]:
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
                "metrics": ["annual_eai", "max_event_loss"],
                "values": {
                    "annual_eai": [round(total_exposure * storm_ratio, 2), round(total_exposure * cmcc_ratio, 2)],
                    "max_event_loss": [round(total_exposure * storm_ratio * 4.5, 2), round(total_exposure * cmcc_ratio * 4.9, 2)],
                },
            }
        },
    }


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

    for feat in exposure.features:
        infra_class = _infer_infra_class(feat)
        if infra_class not in {"elec_aerien", "elec_souterrain"}:
            continue
        territory_id, _, _, _ = _territory_for_feature(feat)
        weight = _feature_weight(feat)
        for hazard in HAZARD_KEYS:
            state = _state_from_damage_ratio(_direct_damage_ratio(feat, hazard, base_damage))
            _bucket_add_state(elec_buckets_by_hazard[hazard][territory_id], state=state, weight=weight)
            _bucket_add_state(elec_global_bucket[hazard], state=state, weight=weight)

    elec_health_by_territory: dict[str, dict[str, float]] = {
        hazard: {territory_id: _health_from_bucket(bucket) for territory_id, bucket in buckets.items()}
        for hazard, buckets in elec_buckets_by_hazard.items()
    }
    elec_health_global = {hazard: _health_from_bucket(bucket) for hazard, bucket in elec_global_bucket.items()}

    territory_acc: dict[str, dict[str, Any]] = {}
    infra_buckets_by_hazard: dict[str, dict[str, dict[str, float]]] = {
        hazard: defaultdict(_new_state_bucket) for hazard in HAZARD_KEYS
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
                "eai_storm_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        )
        row["exposure_eur"] += exposure_value
        if lat is not None and lon is not None:
            row["lat_sum"] += float(lat)
            row["lon_sum"] += float(lon)
            row["loc_count"] += 1

        for hazard in HAZARD_KEYS:
            direct_damage = _direct_damage_ratio(feat, hazard, base_damage)
            direct_state = _state_from_damage_ratio(direct_damage)
            final_state = direct_state
            final_damage = direct_damage

            if infra_class in {"eau_reseau", "eau_ouvrage"}:
                elec_health = elec_health_by_territory[hazard].get(territory_id, elec_health_global[hazard])
                dependency_state = _dependency_state_from_elec_health(elec_health)
                if STATE_ORDER[dependency_state] > STATE_ORDER[direct_state]:
                    dependency_impacted_assets += 1
                    final_state = dependency_state
                final_damage = max(final_damage, STATE_DAMAGE_FLOOR[dependency_state])
                final_damage = _clamp(final_damage + (1.0 - elec_health) * 0.12, 0.0, 0.95)

            eai_ratio = final_damage * ANNUALIZATION_FACTOR[hazard]
            eai_value = exposure_value * eai_ratio
            if hazard == "storm":
                row["eai_storm_eur"] += eai_value
            else:
                row["eai_cmcc_eur"] += eai_value

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
                "eai_storm_eur": round(eai_storm, 2),
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
                "eai_storm_eur": 0.0,
                "eai_cmcc_eur": 0.0,
                "risk_index_storm": 0.0,
                "risk_index_cmcc": 0.0,
            }
        ]

    territory_results.sort(key=lambda row: float(row.get("exposure_eur") or 0.0), reverse=True)

    portfolio_eai_storm = round(sum(float(row["eai_storm_eur"]) for row in territory_results), 2)
    portfolio_eai_cmcc = round(sum(float(row["eai_cmcc_eur"]) for row in territory_results), 2)
    max_event_storm = round(portfolio_eai_storm * 4.5, 2)
    max_event_cmcc = round(portfolio_eai_cmcc * 4.9, 2)

    component_health = {
        hazard: _summarize_component_health(dict(infra_buckets))
        for hazard, infra_buckets in infra_buckets_by_hazard.items()
    }

    portfolio_results = {
        "storm": {
            "eai_eur": portfolio_eai_storm,
            "aai_agg_eur": portfolio_eai_storm,
            "max_event_loss_eur": max_event_storm,
        },
        "storm_cmcc": {
            "eai_eur": portfolio_eai_cmcc,
            "aai_agg_eur": portfolio_eai_cmcc,
            "max_event_loss_eur": max_event_cmcc,
        },
        "delta": {
            "eai_eur": round(portfolio_eai_cmcc - portfolio_eai_storm, 2),
            "eai_pct": round(((portfolio_eai_cmcc / max(portfolio_eai_storm, 1.0)) - 1.0) * 100.0, 2),
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
            "state_thresholds": {
                "S0_to_S1_damage_ratio": 0.05,
                "S1_to_S2_damage_ratio": 0.15,
                "S2_to_S3_damage_ratio": 0.35,
            },
        },
    }

    storm_ratio = portfolio_eai_storm / max(total_exposure, 1.0)
    cmcc_ratio = portfolio_eai_cmcc / max(total_exposure, 1.0)
    graphs = _build_graphs(total_exposure, storm_ratio, cmcc_ratio)

    notes = [
        "Fallback deterministic engine is active while the production CLIMADA path is not wired in compute_impacts().",
        "Each asset receives a direct cyclone damage ratio, mapped to four states (S0/S1/S2/S3) and then annualized into EAI.",
        "Component health uses: health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3) / L_total.",
        "Water assets are conservatively assumed dependent on electricity; weak local electrical health can escalate water states.",
        "For uploads without explicit categories, default_exposure_category=habitation is applied unless overridden.",
    ]

    return ImpactComputationResult(
        engine="fallback_with_interdependency",
        territory_results=territory_results,
        portfolio_results=portfolio_results,
        graphs=graphs,
        notes=notes,
    )


def compute_impacts(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
) -> ImpactComputationResult:
    """Entry point for impact computation.

    Replace this fallback with the full CLIMADA production path.
    """
    return compute_impacts_fallback(exposure, disagg)
