from __future__ import annotations

from collections import defaultdict
from hashlib import blake2b
import math
from typing import Any

from ..config import Settings, load_settings
from .climada_engine import ClimadaRunResult, run_climada_direct_impacts
from .errors import DependencyMissingError
from .exposure_to_climada import build_climada_exposure
from .impact_functions import resolve_tc_impact_func_id
from .interdependency import aggregate_impacts_with_interdependency
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
                "metrics": ["annual_eai", "max_event_loss"],
                "values": {
                    "annual_eai": [round(total_exposure * storm_ratio, 2), round(total_exposure * cmcc_ratio, 2)],
                    "max_event_loss": [round(total_exposure * storm_ratio * 4.5, 2), round(total_exposure * cmcc_ratio * 4.9, 2)],
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

        annual_rp = [10, 20, 50, 100, 200]
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
                "metrics": ["annual_eai", "max_event_loss"],
                "values": {
                    "annual_eai": [
                        round(float((portfolio_results.get("storm") or {}).get("eai_eur", 0.0)), 2),
                        round(float((portfolio_results.get("storm_cmcc") or {}).get("eai_eur", 0.0)), 2),
                    ],
                    "max_event_loss": [
                        round(float((portfolio_results.get("storm") or {}).get("max_event_loss_eur", 0.0)), 2),
                        round(float((portfolio_results.get("storm_cmcc") or {}).get("max_event_loss_eur", 0.0)), 2),
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


def _compute_impacts_climada(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    settings: Settings,
) -> ImpactComputationResult:
    bundle = build_climada_exposure(
        exposure,
        spacing_m=float(disagg.spacing_m),
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=max(1, int(settings.climada_max_points_per_feature)),
        impact_func_id_resolver=resolve_tc_impact_func_id,
    )
    climada = run_climada_direct_impacts(
        bundle,
        hazard_storm_path=settings.hazard_storm_path,
        hazard_storm_cmcc_path=settings.hazard_storm_cmcc_path,
        storm_years=max(1, int(settings.storm_years)),
        top_n_events=max(1, int(settings.climada_top_events_count)),
        prefer_dynamic_hazards=bool(settings.hazard_prefer_dynamic_from_parquet),
        fallback_to_precomputed_hazards=bool(settings.hazard_fallback_to_precomputed),
        storm_parquet_path=settings.storm_parquet_path,
        storm_cmcc_parquet_path=settings.storm_cmcc_parquet_path,
        wind_unit_in=settings.storm_wind_unit_in,
        radius_unit_in=settings.storm_radius_unit_in,
        env_pressure_hpa=float(settings.storm_env_pressure_hpa),
        dynamic_max_tracks=int(settings.hazard_dynamic_max_tracks),
        multi_hazard_enabled=bool(settings.multi_hazard_enabled),
        rain_model=settings.hazard_rain_model,
        surge_topo_path=settings.hazard_surge_topo_path,
        flood_curve_file=settings.d2_flood_curve_file,
    )

    point_count = len(bundle.point_records)
    hazard_direct_eai = {
        "storm": _to_float_list(climada.hazards["storm"].eai_direct_by_point, point_count),
        "storm_cmcc": _to_float_list(climada.hazards["storm_cmcc"].eai_direct_by_point, point_count),
    }
    hazard_max_loss = {
        "storm": _to_float_list(climada.hazards["storm"].max_loss_by_point, point_count),
        "storm_cmcc": _to_float_list(climada.hazards["storm_cmcc"].max_loss_by_point, point_count),
    }

    aggregated = aggregate_impacts_with_interdependency(
        point_records=bundle.point_records,
        hazard_direct_eai=hazard_direct_eai,
        hazard_max_loss=hazard_max_loss,
    )

    storm_direct = float(aggregated.portfolio_by_hazard["storm"]["eai_direct_eur"])
    storm_indirect = float(aggregated.portfolio_by_hazard["storm"]["eai_indirect_eur"])
    storm_total = float(aggregated.portfolio_by_hazard["storm"]["eai_total_eur"])
    cmcc_direct = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_direct_eur"])
    cmcc_indirect = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_indirect_eur"])
    cmcc_total = float(aggregated.portfolio_by_hazard["storm_cmcc"]["eai_total_eur"])

    storm_scaler = float(aggregated.dependency_scaler_by_hazard.get("storm", 1.0))
    cmcc_scaler = float(aggregated.dependency_scaler_by_hazard.get("storm_cmcc", 1.0))

    storm_direct_metrics = climada.hazards["storm"]
    cmcc_direct_metrics = climada.hazards["storm_cmcc"]

    storm_components_raw = (climada.component_hazards or {}).get("storm", {})
    cmcc_components_raw = (climada.component_hazards or {}).get("storm_cmcc", {})

    def _component_direct_eai_map(component_map: dict[str, Any], combined_direct: float) -> dict[str, float]:
        ordered_names = [name for name in ("wind", "rain", "surge") if name in component_map]
        ordered_names.extend(sorted(name for name in component_map.keys() if name not in {"wind", "rain", "surge"}))
        out = {name: round(max(0.0, float(getattr(component_map[name], "aai_agg_eur", 0.0))), 2) for name in ordered_names}
        out["combined_capped"] = round(max(0.0, float(combined_direct)), 2)
        return out

    def _component_direct_max_event_map(component_map: dict[str, Any]) -> dict[str, float]:
        ordered_names = [name for name in ("wind", "rain", "surge") if name in component_map]
        ordered_names.extend(sorted(name for name in component_map.keys() if name not in {"wind", "rain", "surge"}))
        return {
            name: round(max(0.0, float(getattr(component_map[name], "max_event_loss_eur", 0.0))), 2)
            for name in ordered_names
        }

    storm_components_direct = _component_direct_eai_map(storm_components_raw, storm_direct)
    cmcc_components_direct = _component_direct_eai_map(cmcc_components_raw, cmcc_direct)
    storm_components_max = _component_direct_max_event_map(storm_components_raw)
    cmcc_components_max = _component_direct_max_event_map(cmcc_components_raw)

    portfolio_results = {
        "storm": {
            "eai_eur": round(storm_total, 2),
            "aai_agg_eur": round(storm_total, 2),
            "max_event_loss_eur": round(storm_direct_metrics.max_event_loss_eur * storm_scaler, 2),
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
                            float(storm_direct_metrics.max_event_loss_eur),
                        ),
                    )
                ) * storm_scaler,
                2,
            ),
            "tvar_95_eur": round(float(storm_direct_metrics.tvar_95_eur) * storm_scaler, 2),
            "components_direct_eai_eur": storm_components_direct,
            "components_direct_max_event_loss_eur": storm_components_max,
        },
        "storm_cmcc": {
            "eai_eur": round(cmcc_total, 2),
            "aai_agg_eur": round(cmcc_total, 2),
            "max_event_loss_eur": round(cmcc_direct_metrics.max_event_loss_eur * cmcc_scaler, 2),
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
                            float(cmcc_direct_metrics.max_event_loss_eur),
                        ),
                    )
                ) * cmcc_scaler,
                2,
            ),
            "tvar_95_eur": round(float(cmcc_direct_metrics.tvar_95_eur) * cmcc_scaler, 2),
            "components_direct_eai_eur": cmcc_components_direct,
            "components_direct_max_event_loss_eur": cmcc_components_max,
        },
        "delta": {
            "eai_eur": round(cmcc_total - storm_total, 2),
            "eai_pct": round(((cmcc_total / max(storm_total, 1.0)) - 1.0) * 100.0, 2),
        },
        "component_health": aggregated.component_health,
        "interdependency": aggregated.interdependency,
        "event_summary": {
            "storm_top_events": _scale_top_events(storm_direct_metrics.top_events, storm_scaler),
            "storm_cmcc_top_events": _scale_top_events(cmcc_direct_metrics.top_events, cmcc_scaler),
        },
    }

    graphs = _build_climada_graphs(climada, aggregated.dependency_scaler_by_hazard, portfolio_results)
    notes = [
        "CLIMADA production engine is active (STORM + STORM_CMCC with annualized frequencies).",
        "Direct impact is computed by CLIMADA and indirect impact is added by conservative electricity-to-water dependency post-processing.",
        "Component health uses: health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3) / L_total.",
        "Electricity-health lookup for water assets uses local territory, then nearest electric territory, then global fallback.",
        "Per-asset EAI is capped to asset exposure value: EAI_total <= exposure_eur.",
        "When enabled, direct multi-hazard uses additive wind+rain+surge losses with per-point capping before interdependency uplift.",
        *climada.notes,
        *bundle.warnings,
    ]
    modeling = {
        **climada.modeling,
        "dependency_mode": "postprocess_electricity_to_water",
        "scenario_mode": "prudent",
        "metric_crs": settings.climada_metric_crs,
        "sampling_spacing_m": float(disagg.spacing_m),
        "max_points_per_feature": int(settings.climada_max_points_per_feature),
    }

    return ImpactComputationResult(
        engine="climada_with_interdependency_v1",
        territory_results=aggregated.territory_results,
        asset_results=aggregated.asset_results,
        portfolio_results=portfolio_results,
        graphs=graphs,
        notes=notes,
        modeling=modeling,
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
            "max_event_loss_eur": max_event_storm,
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
            "max_event_loss_eur": max_event_cmcc,
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
        },
    )


def compute_impacts(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    settings: Settings | None = None,
) -> ImpactComputationResult:
    runtime_settings = settings or load_settings()
    mode = str(runtime_settings.impact_engine_mode or "climada").strip().lower()

    if mode == "fallback":
        return compute_impacts_fallback(exposure, disagg)
    if mode not in {"climada", "auto"}:
        raise ValueError(f"Unsupported impact engine mode: {mode}")

    try:
        return _compute_impacts_climada(exposure, disagg, runtime_settings)
    except DependencyMissingError as exc:
        if runtime_settings.allow_climada_fallback:
            res = compute_impacts_fallback(exposure, disagg)
            res.notes.append(f"CLIMADA dependency missing ({exc}); fallback enabled by configuration.")
            if isinstance(res.modeling, dict):
                res.modeling["fallback_reason"] = str(exc)
            return res
        raise
    except Exception as exc:
        if runtime_settings.allow_climada_fallback:
            res = compute_impacts_fallback(exposure, disagg)
            res.notes.append(f"CLIMADA runtime failed ({type(exc).__name__}); fallback enabled by configuration.")
            if isinstance(res.modeling, dict):
                res.modeling["fallback_reason"] = f"{type(exc).__name__}: {exc}"
            return res
        raise
