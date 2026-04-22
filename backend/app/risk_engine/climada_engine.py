from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import math
from pathlib import Path
from typing import Any, Callable
import copy
import hashlib

from .errors import DependencyMissingError
from .exposure_to_climada import ClimadaExposureBundle, subset_climada_exposure_bundle
from .hazard_loader import (
    DEFAULT_BASIN_COVERAGES,
    BasinCoverage,
    _build_centroids_from_points,
    _build_hazard_from_tracks,
    load_storm_hazards,
    load_storm_hazards_from_parquet_for_points,
)
from .impact_functions import get_tc_vulnerability_payload, try_build_climada_impact_funcs
from .impact_functions_multi_hazard import (
    build_multi_hazard_impact_model,
    resolve_rain_impf_id,
    resolve_surge_impf_id,
)


RETURN_PERIODS = (10, 20, 50, 100, 200)
_TOPO_RASTER_CACHE: dict[str, Path] = {}
_SHARD_MEMORY_MULTIPLIER = {
    "wind": 0.95,
    "rain": 1.2,
    "surge": 1.75,
}
_DYNAMIC_HAZARD_MEMORY_MULTIPLIER = 6.0
CENTROID_ASSIGNMENT_THRESHOLD_DEG = 5.0
logger = logging.getLogger(__name__)


@dataclass
class HazardImpactResult:
    eai_direct_by_point: Any
    max_loss_by_point: Any
    at_event_loss: Any
    event_frequency: Any
    event_id: Any
    event_name: Any
    aai_agg_eur: float
    max_event_loss_eur: float
    pml_eur: dict[int, float]
    tvar_95_eur: float
    top_events: list[dict[str, Any]]
    matching: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClimadaRunResult:
    hazards: dict[str, HazardImpactResult]
    component_hazards: dict[str, dict[str, HazardImpactResult]] = field(default_factory=dict)
    modeling: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _SimpleImpactView:
    event_id: Any
    event_name: Any


@dataclass(frozen=True)
class _ExposureShard:
    shard_id: str
    point_indices: tuple[int, ...]
    territory_id: str
    infra_class: str
    retry_depth: int = 0

    @property
    def point_count(self) -> int:
        return len(self.point_indices)


def _require_runtime() -> dict[str, Any]:
    try:
        import numpy as np  # type: ignore
        from climada.engine import ImpactCalc  # type: ignore
        from climada.entity.impact_funcs import ImpactFuncSet  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA runtime dependencies are required for impact computation") from exc
    return {"np": np, "ImpactCalc": ImpactCalc, "ImpactFuncSet": ImpactFuncSet}


def _as_1d_float(np: Any, values: Any) -> Any:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _max_loss_per_point(np: Any, impact_obj: Any, expected_len: int) -> Any:
    imp_mat = getattr(impact_obj, "imp_mat", None)
    if imp_mat is None:
        return np.zeros(expected_len, dtype=float)
    try:
        col_max = imp_mat.max(axis=0)
        if hasattr(col_max, "toarray"):
            arr = np.asarray(col_max.toarray(), dtype=float).reshape(-1)
        else:
            arr = np.asarray(col_max, dtype=float).reshape(-1)
        if arr.size == expected_len:
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    except Exception:
        pass
    return np.zeros(expected_len, dtype=float)


def _approx_max_loss_per_point(np: Any, eai_exp: Any, at_event: Any) -> Any:
    eai = _as_1d_float(np, eai_exp)
    evt = _as_1d_float(np, at_event)
    if eai.size == 0:
        return np.zeros(0, dtype=float)
    eai_sum = float(eai.sum())
    evt_max = float(evt.max()) if evt.size else 0.0
    factor = (evt_max / eai_sum) if eai_sum > 0.0 else 0.0
    return eai * max(0.0, factor)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2) + math.cos(lat1_rad) * math.cos(lat2_rad) * (math.sin(dlon / 2.0) ** 2)
    return radius_km * (2.0 * math.asin(math.sqrt(a)))


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _resolve_centroid_assignment_column(exposures: Any, hazard_obj: Any) -> str | None:
    gdf = getattr(exposures, "gdf", None)
    columns = getattr(gdf, "columns", None)
    if gdf is None or columns is None:
        return None

    column_names = [str(col) for col in list(columns)]
    haz_type = str(getattr(hazard_obj, "haz_type", "") or "").strip()
    preferred = f"centr_{haz_type}" if haz_type else None
    if preferred and preferred in column_names:
        return preferred

    centroid_columns = [name for name in column_names if name.startswith("centr_")]
    if len(centroid_columns) == 1:
        return centroid_columns[0]
    if centroid_columns:
        return centroid_columns[0]
    return None


def _coerce_centroid_index(raw_value: Any, centroid_count: int) -> int | None:
    if raw_value is None:
        return None
    try:
        numeric = float(raw_value)
    except Exception:
        return None
    if not math.isfinite(numeric):
        return None
    index = int(numeric)
    if index < 0 or index >= max(0, int(centroid_count)):
        return None
    return index


def _positive_intensity_centroid_mask(np: Any, hazard_obj: Any, centroid_count: int) -> Any:
    if centroid_count <= 0:
        return np.zeros(0, dtype=bool)

    intensity = getattr(hazard_obj, "intensity", None)
    if intensity is None:
        return np.zeros(int(centroid_count), dtype=bool)

    try:
        positive = (intensity > 0).sum(axis=0)
        if hasattr(positive, "A1"):
            arr = np.asarray(positive.A1, dtype=float).reshape(-1)
        elif hasattr(positive, "toarray"):
            arr = np.asarray(positive.toarray(), dtype=float).reshape(-1)
        else:
            arr = np.asarray(positive, dtype=float).reshape(-1)
        if arr.size == centroid_count:
            return arr > 0.0
    except Exception:
        pass

    try:
        dense = np.asarray(intensity, dtype=float)
        if dense.ndim == 1:
            dense = dense.reshape(1, -1)
        if dense.ndim >= 2 and dense.shape[-1] == centroid_count:
            return np.nan_to_num(dense, nan=0.0, posinf=0.0, neginf=0.0).max(axis=0) > 0.0
    except Exception:
        pass

    return np.zeros(int(centroid_count), dtype=bool)


def _compute_matching_summary(
    np: Any,
    *,
    exposures: Any,
    point_records: list[dict[str, Any]],
    hazard_obj: Any,
    direct_eai_by_point: Any,
    component_name: str,
    hazard_key: str | None,
) -> dict[str, Any]:
    point_count = int(len(point_records))
    point_values = np.asarray(
        [max(0.0, float(rec.get("value_eur", 0.0) or 0.0)) for rec in point_records],
        dtype=float,
    )
    point_value_total = float(point_values.sum()) if point_values.size else 0.0
    centroid_count = int(getattr(getattr(hazard_obj, "centroids", None), "size", 0) or 0)
    centroid_column = _resolve_centroid_assignment_column(exposures, hazard_obj)
    haz_type = str(getattr(hazard_obj, "haz_type", "") or "").strip() or None

    summary: dict[str, Any] = {
        "status": "complete",
        "hazard": str(hazard_key or "unknown"),
        "component": str(component_name),
        "haz_type": haz_type,
        "centroid_column": centroid_column,
        "point_count": point_count,
        "point_value_total_eur": round(point_value_total, 2),
        "centroid_count": centroid_count,
        "assignment_threshold_deg": float(CENTROID_ASSIGNMENT_THRESHOLD_DEG),
    }

    gdf = getattr(exposures, "gdf", None)
    if gdf is None or centroid_column is None or centroid_column not in getattr(gdf, "columns", []):
        summary.update(
            {
                "status": "unavailable",
                "reason": "missing_centroid_assignment",
                "assigned_point_count": 0,
                "assigned_point_fraction": 0.0,
                "positive_hazard_point_count": 0,
                "positive_hazard_point_fraction": 0.0,
                "positive_direct_loss_point_count": 0,
                "positive_direct_loss_point_fraction": 0.0,
            }
        )
        return summary

    assignment_values = list(gdf[centroid_column])
    centroid_lats = _as_1d_float(np, getattr(getattr(hazard_obj, "centroids", None), "lat", []))
    centroid_lons = _as_1d_float(np, getattr(getattr(hazard_obj, "centroids", None), "lon", []))
    positive_centroid_mask = _positive_intensity_centroid_mask(np, hazard_obj, centroid_count)

    assigned_mask = np.zeros(point_count, dtype=bool)
    positive_hazard_mask = np.zeros(point_count, dtype=bool)
    direct_eai = _as_1d_float(np, direct_eai_by_point)
    positive_direct_mask = np.zeros(point_count, dtype=bool)
    positive_direct_mask[: min(point_count, direct_eai.size)] = direct_eai[: min(point_count, direct_eai.size)] > 0.0
    unique_assigned_centroids: set[int] = set()
    distance_km_values: list[float] = []

    for idx, rec in enumerate(point_records):
        assigned_idx = _coerce_centroid_index(
            assignment_values[idx] if idx < len(assignment_values) else None,
            centroid_count,
        )
        if assigned_idx is None:
            continue
        assigned_mask[idx] = True
        unique_assigned_centroids.add(int(assigned_idx))

        if assigned_idx < positive_centroid_mask.size and bool(positive_centroid_mask[assigned_idx]):
            positive_hazard_mask[idx] = True

        lat = rec.get("lat")
        lon = rec.get("lon")
        if (
            lat is not None
            and lon is not None
            and assigned_idx < centroid_lats.size
            and assigned_idx < centroid_lons.size
        ):
            distance_km = _haversine_km(
                float(lon),
                float(lat),
                float(centroid_lons[assigned_idx]),
                float(centroid_lats[assigned_idx]),
            )
            if math.isfinite(distance_km):
                distance_km_values.append(float(distance_km))

    assigned_value = float(point_values[assigned_mask].sum()) if point_values.size else 0.0
    positive_hazard_value = float(point_values[positive_hazard_mask].sum()) if point_values.size else 0.0
    positive_direct_value = float(point_values[positive_direct_mask].sum()) if point_values.size else 0.0
    distance_arr = np.asarray(distance_km_values, dtype=float) if distance_km_values else np.zeros(0, dtype=float)

    summary.update(
        {
            "assigned_centroid_count": int(len(unique_assigned_centroids)),
            "positive_centroid_count": int(positive_centroid_mask.sum()) if positive_centroid_mask.size else 0,
            "positive_centroid_fraction": _round_or_none(
                float(positive_centroid_mask.sum()) / float(max(centroid_count, 1)),
                digits=4,
            ),
            "assigned_point_count": int(assigned_mask.sum()),
            "assigned_point_fraction": _round_or_none(float(assigned_mask.sum()) / float(max(point_count, 1)), digits=4),
            "assigned_value_eur": round(assigned_value, 2),
            "assigned_value_fraction": _round_or_none(assigned_value / float(max(point_value_total, 1.0)), digits=4),
            "unassigned_point_count": int(point_count - int(assigned_mask.sum())),
            "positive_hazard_point_count": int(positive_hazard_mask.sum()),
            "positive_hazard_point_fraction": _round_or_none(
                float(positive_hazard_mask.sum()) / float(max(point_count, 1)),
                digits=4,
            ),
            "positive_hazard_value_eur": round(positive_hazard_value, 2),
            "positive_hazard_value_fraction": _round_or_none(
                positive_hazard_value / float(max(point_value_total, 1.0)),
                digits=4,
            ),
            "positive_direct_loss_point_count": int(positive_direct_mask.sum()),
            "positive_direct_loss_point_fraction": _round_or_none(
                float(positive_direct_mask.sum()) / float(max(point_count, 1)),
                digits=4,
            ),
            "positive_direct_loss_value_eur": round(positive_direct_value, 2),
            "positive_direct_loss_value_fraction": _round_or_none(
                positive_direct_value / float(max(point_value_total, 1.0)),
                digits=4,
            ),
            "assignment_distance_mean_km": _round_or_none(distance_arr.mean() if distance_arr.size else None, digits=3),
            "assignment_distance_p95_km": _round_or_none(
                np.percentile(distance_arr, 95) if distance_arr.size else None,
                digits=3,
            ),
            "assignment_distance_max_km": _round_or_none(distance_arr.max() if distance_arr.size else None, digits=3),
        }
    )
    return summary


def _build_combined_matching_summary(
    np: Any,
    *,
    hazard_key: str,
    point_records: list[dict[str, Any]],
    total_metrics: HazardImpactResult,
    component_metrics: dict[str, HazardImpactResult],
    hazard_zero_intensity: bool,
) -> dict[str, Any]:
    point_values = np.asarray(
        [max(0.0, float(rec.get("value_eur", 0.0) or 0.0)) for rec in point_records],
        dtype=float,
    )
    point_count = int(point_values.size)
    point_value_total = float(point_values.sum()) if point_values.size else 0.0
    direct_eai = _as_1d_float(np, total_metrics.eai_direct_by_point)
    positive_direct_mask = np.zeros(point_count, dtype=bool)
    positive_direct_mask[: min(point_count, direct_eai.size)] = direct_eai[: min(point_count, direct_eai.size)] > 0.0
    positive_direct_value = float(point_values[positive_direct_mask].sum()) if point_values.size else 0.0

    reference_component_name = None
    reference_matching: dict[str, Any] | None = None
    for candidate_name in ("wind", "rain", "surge"):
        candidate = component_metrics.get(candidate_name)
        candidate_matching = dict(getattr(candidate, "matching", {}) or {}) if candidate is not None else {}
        if candidate_matching.get("status") == "complete":
            reference_component_name = candidate_name
            reference_matching = candidate_matching
            break

    summary: dict[str, Any] = {
        "status": "complete" if reference_matching else "unavailable",
        "hazard": str(hazard_key),
        "component": "combined",
        "component_names": [name for name in ("wind", "rain", "surge") if name in component_metrics],
        "reference_component": reference_component_name,
        "point_count": point_count,
        "point_value_total_eur": round(point_value_total, 2),
        "hazard_zero_intensity": bool(hazard_zero_intensity),
        "positive_direct_loss_point_count": int(positive_direct_mask.sum()),
        "positive_direct_loss_point_fraction": _round_or_none(
            float(positive_direct_mask.sum()) / float(max(point_count, 1)),
            digits=4,
        ),
        "positive_direct_loss_value_eur": round(positive_direct_value, 2),
        "positive_direct_loss_value_fraction": _round_or_none(
            positive_direct_value / float(max(point_value_total, 1.0)),
            digits=4,
        ),
    }
    if reference_matching is not None:
        for key in (
            "haz_type",
            "centroid_column",
            "centroid_count",
            "positive_centroid_count",
            "positive_centroid_fraction",
            "assigned_centroid_count",
            "assigned_point_count",
            "assigned_point_fraction",
            "assigned_value_eur",
            "assigned_value_fraction",
            "unassigned_point_count",
            "positive_hazard_point_count",
            "positive_hazard_point_fraction",
            "positive_hazard_value_eur",
            "positive_hazard_value_fraction",
            "assignment_distance_mean_km",
            "assignment_distance_p95_km",
            "assignment_distance_max_km",
            "assignment_threshold_deg",
        ):
            if key in reference_matching:
                summary[key] = reference_matching[key]
    return summary


def _compute_pml(np: Any, losses: Any, frequency: Any, return_periods: tuple[int, ...]) -> dict[int, float]:
    losses_arr = _as_1d_float(np, losses)
    freq_arr = _as_1d_float(np, frequency)
    valid = (losses_arr > 0.0) & (freq_arr > 0.0)
    if not valid.any():
        return {rp: 0.0 for rp in return_periods}

    losses_sorted = losses_arr[valid][np.argsort(-losses_arr[valid])]
    freq_sorted = freq_arr[valid][np.argsort(-losses_arr[valid])]
    cum_rate = np.cumsum(freq_sorted)

    out: dict[int, float] = {}
    for rp in return_periods:
        target_rate = 1.0 / float(rp)
        idx = int(np.searchsorted(cum_rate, target_rate, side="left"))
        if idx >= losses_sorted.size:
            out[rp] = 0.0
        else:
            out[rp] = float(max(0.0, losses_sorted[idx]))
    return out


def _compute_tvar_95(np: Any, losses: Any, frequency: Any) -> float:
    losses_arr = _as_1d_float(np, losses)
    weights = _as_1d_float(np, frequency)
    weights = np.clip(weights, 0.0, None)
    total_w = float(weights.sum())
    if total_w <= 0.0:
        return 0.0

    probs = weights / total_w
    order = np.argsort(losses_arr)
    sorted_losses = losses_arr[order]
    sorted_probs = probs[order]
    cdf = np.cumsum(sorted_probs)
    idx = int(np.searchsorted(cdf, 0.95, side="left"))
    idx = max(0, min(idx, sorted_losses.size - 1))
    var95 = float(sorted_losses[idx])

    tail = losses_arr >= var95
    tail_w = weights[tail]
    tail_losses = losses_arr[tail]
    if tail_losses.size == 0 or float(tail_w.sum()) <= 0.0:
        return max(0.0, var95)
    return float((tail_losses * tail_w).sum() / tail_w.sum())


def _extract_top_events(np: Any, impact_obj: Any, losses: Any, frequency: Any, top_n: int) -> list[dict[str, Any]]:
    losses_arr = _as_1d_float(np, losses)
    freq_arr = _as_1d_float(np, frequency)
    event_ids = getattr(impact_obj, "event_id", None)
    event_names = getattr(impact_obj, "event_name", None)

    if losses_arr.size == 0:
        return []

    order = np.argsort(-losses_arr)
    out: list[dict[str, Any]] = []
    for idx in order[:max(1, top_n)]:
        loss = float(losses_arr[idx])
        if loss <= 0.0:
            continue
        freq = float(freq_arr[idx]) if idx < freq_arr.size else 0.0
        out.append(
            {
                "event_id": int(event_ids[idx]) if event_ids is not None and idx < len(event_ids) else int(idx + 1),
                "event_name": str(event_names[idx]) if event_names is not None and idx < len(event_names) else None,
                "loss_eur": round(loss, 2),
                "frequency_annual": round(freq, 8),
                "return_period_years_approx": round((1.0 / freq), 4) if freq > 0.0 else None,
            }
        )
    return out


def _normalize_frequency_on_copy(hazard_obj: Any, storm_years: int) -> Any:
    hazard_copy = copy.deepcopy(hazard_obj)
    freq = getattr(hazard_copy, "frequency", None)
    if freq is None:
        return hazard_copy
    if getattr(hazard_copy, "_sib_frequency_normalized", False):
        return hazard_copy
    try:
        hazard_copy.frequency = freq / float(max(1, int(storm_years)))
        setattr(hazard_copy, "_sib_frequency_normalized", True)
    except Exception:
        return hazard_obj
    return hazard_copy


def _normalize_rain_model(raw_model: str | None) -> str:
    model = str(raw_model or "R-CLIPER").strip().upper().replace("_", "-")
    if model in {"RCLIPER", "R-CLIPER"}:
        return "R-CLIPER"
    if model == "TCR":
        return "TCR"
    return "R-CLIPER"


def _build_exposure_with_impf_column(
    base_exposure: Any,
    *,
    haz_type: str,
    impf_ids: list[int],
) -> Any:
    exposure_copy = copy.deepcopy(base_exposure)
    column = f"impf_{str(haz_type)}"
    gdf = getattr(exposure_copy, "gdf", None)
    if gdf is None:
        return exposure_copy

    n_rows = int(len(gdf.index))
    values = [int(v) for v in list(impf_ids)[:n_rows]]
    if len(values) < n_rows:
        filler = int(values[-1]) if values else 1
        values.extend([filler] * (n_rows - len(values)))
    gdf[column] = values
    return exposure_copy


def _prepare_topo_raster_with_crs(topo_path: Path) -> Path:
    path = Path(topo_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"DEM file not found: {path}")

    try:
        import rasterio  # type: ignore
    except Exception:
        return path

    with rasterio.open(path) as src:
        if src.crs:
            return path
        meta = src.meta.copy()
        data = src.read()

    cache_key = f"{path.resolve(strict=False)}::{path.stat().st_mtime_ns}::{path.stat().st_size}"
    cached = _TOPO_RASTER_CACHE.get(cache_key)
    if cached is not None and cached.exists():
        return cached

    cache_hash = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16]
    cache_dir = Path("/tmp/sib-risk-topo-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{path.stem}_{cache_hash}_epsg4326.tif"

    meta.update(driver="GTiff", crs="EPSG:4326", compress="deflate")
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(data)

    _TOPO_RASTER_CACHE[cache_key] = out_path
    return out_path


def _point_records_bounds_wgs84(
    point_records: list[dict[str, Any]],
    *,
    padding_degrees: float = 0.5,
) -> tuple[float, float, float, float] | None:
    coords = [
        (float(rec.get("lon")), float(rec.get("lat")))
        for rec in list(point_records or [])
        if rec.get("lon") is not None and rec.get("lat") is not None
    ]
    if not coords:
        return None

    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    pad = max(0.0, float(padding_degrees))
    min_lon = max(-180.0, min(lons) - pad)
    max_lon = min(180.0, max(lons) + pad)
    min_lat = max(-90.0, min(lats) - pad)
    max_lat = min(90.0, max(lats) + pad)
    if min_lon >= max_lon or min_lat >= max_lat:
        return None
    return (min_lon, min_lat, max_lon, max_lat)


def _prepare_topo_raster_for_exposure(
    topo_path: Path,
    *,
    point_records: list[dict[str, Any]],
    padding_degrees: float = 0.5,
) -> Path:
    prepared_path = _prepare_topo_raster_with_crs(topo_path)
    bounds_wgs84 = _point_records_bounds_wgs84(point_records, padding_degrees=padding_degrees)
    if bounds_wgs84 is None:
        return prepared_path

    try:
        import rasterio  # type: ignore
        from rasterio.windows import Window  # type: ignore
        from rasterio.windows import from_bounds as window_from_bounds  # type: ignore
        from rasterio.warp import transform_bounds  # type: ignore
    except Exception:
        return prepared_path

    cache_key = (
        f"{prepared_path.resolve(strict=False)}::{prepared_path.stat().st_mtime_ns}::{prepared_path.stat().st_size}"
        f"::{bounds_wgs84!r}"
    )
    cached = _TOPO_RASTER_CACHE.get(cache_key)
    if cached is not None and cached.exists():
        return cached

    with rasterio.open(prepared_path) as src:
        src_crs = src.crs
        if src_crs is None:
            return prepared_path

        try:
            left, bottom, right, top = transform_bounds("EPSG:4326", src_crs, *bounds_wgs84, densify_pts=21)
            window = window_from_bounds(left, bottom, right, top, transform=src.transform)
            window = window.round_offsets().round_lengths()
            full_window = Window(0, 0, src.width, src.height)
            window = window.intersection(full_window)
        except Exception:
            return prepared_path

        if int(window.width) <= 0 or int(window.height) <= 0:
            return prepared_path
        if int(window.width) >= int(src.width) and int(window.height) >= int(src.height):
            return prepared_path

        data = src.read(window=window)
        meta = src.meta.copy()
        meta.update(
            driver="GTiff",
            height=int(window.height),
            width=int(window.width),
            transform=src.window_transform(window),
            compress="deflate",
        )

    cache_hash = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16]
    cache_dir = Path("/tmp/sib-risk-topo-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{prepared_path.stem}_{cache_hash}_cropped.tif"

    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(data)

    _TOPO_RASTER_CACHE[cache_key] = out_path
    return out_path


def _estimate_fraction_raster_shape(
    centroids: Any,
    *,
    get_resolution_fn: Callable[[Any, Any], Any] | None = None,
    pts_to_raster_meta_fn: Callable[..., Any] | None = None,
) -> dict[str, int] | None:
    if centroids is None:
        return None

    try:
        if get_resolution_fn is None or pts_to_raster_meta_fn is None:
            import climada.util.coordinates as u_coord  # type: ignore

            get_resolution_fn = get_resolution_fn or u_coord.get_resolution
            pts_to_raster_meta_fn = pts_to_raster_meta_fn or u_coord.pts_to_raster_meta

        lat = getattr(centroids, "lat", None)
        lon = getattr(centroids, "lon", None)
        bounds = getattr(centroids, "total_bounds", None)
        centroid_count = int(getattr(centroids, "size", 0) or 0)
        if lat is None or lon is None or bounds is None or centroid_count <= 0:
            return None

        resolution = get_resolution_fn(lat, lon)
        res_x = abs(float(resolution[0]))
        res_y = abs(float(resolution[1]))
        res = min(value for value in (res_x, res_y) if value > 0.0)
        rows, cols, _ = pts_to_raster_meta_fn(
            points_bounds=[float(value) for value in list(bounds)],
            res=res,
        )
        rows_i = int(rows)
        cols_i = int(cols)
        if rows_i <= 0 or cols_i <= 0:
            return None
        return {
            "rows": rows_i,
            "cols": cols_i,
            "cells": rows_i * cols_i,
            "centroid_count": centroid_count,
        }
    except Exception:
        return None


def _should_use_pointwise_surge_fraction(
    centroids: Any,
    *,
    fraction_grid_info: dict[str, int] | None = None,
    max_fraction_cells: int = 5_000_000,
    raster_cell_ratio_threshold: float = 25.0,
    get_resolution_fn: Callable[[Any, Any], Any] | None = None,
    pts_to_raster_meta_fn: Callable[..., Any] | None = None,
) -> bool:
    info = fraction_grid_info or _estimate_fraction_raster_shape(
        centroids,
        get_resolution_fn=get_resolution_fn,
        pts_to_raster_meta_fn=pts_to_raster_meta_fn,
    )
    if not info:
        return False
    cells = int(info.get("cells") or 0)
    centroid_count = max(1, int(info.get("centroid_count") or 0))
    return cells > int(max_fraction_cells) and cells > int(raster_cell_ratio_threshold * centroid_count)


def _build_pointwise_surge_hazard(
    np: Any,
    *,
    surge_hazard_cls: Any,
    wind_hazard: Any,
    topo_path: Path | str,
    inland_decay_rate: float = 0.2,
    add_sea_level_rise: float = 0.0,
    read_raster_sample_fn: Callable[..., Any] | None = None,
) -> Any:
    if read_raster_sample_fn is None:
        import climada.util.coordinates as u_coord  # type: ignore

        read_raster_sample_fn = u_coord.read_raster_sample

    centroids = copy.deepcopy(wind_hazard.centroids)

    centroids_dist_coast = centroids.get_dist_coast(signed=True)
    coastal_msk = (wind_hazard.intensity > 0).sum(axis=0).A1 > 0
    coastal_msk &= (centroids_dist_coast < 0)
    coastal_msk &= (centroids_dist_coast >= -50 * 1000)
    coastal_msk &= (np.abs(centroids.lat) <= 61)

    coastal_centroids_h = read_raster_sample_fn(
        str(topo_path),
        centroids.lat[coastal_msk],
        centroids.lon[coastal_msk],
    )

    elevation_msk = coastal_centroids_h >= 0
    elevation_msk &= coastal_centroids_h <= 10 + add_sea_level_rise
    coastal_msk[coastal_msk] = elevation_msk

    coastal_centroids_h = coastal_centroids_h[elevation_msk]
    coastal_idx = coastal_msk.nonzero()[0]

    cent_to_coastal_idx = np.full(coastal_msk.shape, coastal_idx.size, dtype=np.int64)
    cent_to_coastal_idx[coastal_msk] = np.arange(coastal_idx.size)

    inten_surge = wind_hazard.intensity.copy()
    inten_surge.data[~coastal_msk[inten_surge.indices]] = 0
    inten_surge.eliminate_zeros()
    inten_surge.data = 0.1023 * np.fmax(inten_surge.data - 26.8224, 0) + 1.8288

    if inland_decay_rate != 0:
        dist_coast_km = np.abs(centroids_dist_coast[coastal_idx]) / 1000
        coastal_centroids_h += inland_decay_rate * dist_coast_km
    coastal_centroids_h -= add_sea_level_rise

    inten_surge.data -= coastal_centroids_h[cent_to_coastal_idx[inten_surge.indices]]
    inten_surge.data = np.fmax(inten_surge.data, 0)
    inten_surge.eliminate_zeros()

    fract_surge = inten_surge.copy()
    fract_surge.data[:] = 1.0

    haz = surge_hazard_cls()
    haz.centroids = centroids
    haz.units = "m"
    haz.event_id = wind_hazard.event_id
    haz.event_name = wind_hazard.event_name
    haz.date = wind_hazard.date
    haz.orig = wind_hazard.orig
    haz.frequency = wind_hazard.frequency
    haz.intensity = inten_surge
    haz.fraction = fract_surge
    return haz


def _build_surge_hazard(
    np: Any,
    *,
    surge_hazard_cls: Any,
    wind_hazard: Any,
    topo_path: Path | str,
    hazard_source: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    fraction_grid_info = _estimate_fraction_raster_shape(getattr(wind_hazard, "centroids", None))
    source_name = str(hazard_source or "").strip().lower()
    use_pointwise = source_name == "dynamic_parquet"
    reason = "dynamic_exposure_centroids" if use_pointwise else "raster_fraction"

    if not use_pointwise and _should_use_pointwise_surge_fraction(
        getattr(wind_hazard, "centroids", None),
        fraction_grid_info=fraction_grid_info,
    ):
        use_pointwise = True
        reason = "fraction_grid_explodes"

    if use_pointwise:
        surge_hazard = _build_pointwise_surge_hazard(
            np,
            surge_hazard_cls=surge_hazard_cls,
            wind_hazard=wind_hazard,
            topo_path=topo_path,
        )
        return surge_hazard, {
            "fraction_mode": "pointwise",
            "reason": reason,
            **(fraction_grid_info or {}),
        }

    surge_hazard = surge_hazard_cls.from_tc_winds(wind_hazard, str(topo_path))
    return surge_hazard, {
        "fraction_mode": "raster",
        "reason": reason,
        **(fraction_grid_info or {}),
    }


def _component_checkpoint_dir(
    checkpoint_dir: Path | None,
    *,
    hazard_key: str | None,
    component_name: str,
) -> Path | None:
    if checkpoint_dir is None:
        return None
    root = Path(checkpoint_dir) / str(hazard_key or "unknown") / str(component_name)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _shard_result_path(
    checkpoint_dir: Path | None,
    *,
    hazard_key: str | None,
    component_name: str,
    shard_id: str,
) -> Path | None:
    base_dir = _component_checkpoint_dir(checkpoint_dir, hazard_key=hazard_key, component_name=component_name)
    if base_dir is None:
        return None
    result_dir = base_dir / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir / f"{shard_id}.npz"


def _shard_split_plan_path(
    checkpoint_dir: Path | None,
    *,
    hazard_key: str | None,
    component_name: str,
    shard_id: str,
) -> Path | None:
    base_dir = _component_checkpoint_dir(checkpoint_dir, hazard_key=hazard_key, component_name=component_name)
    if base_dir is None:
        return None
    split_dir = base_dir / "splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    return split_dir / f"{shard_id}.json"


def _point_id_values(point_records: list[dict[str, Any]]) -> list[str]:
    return [str(rec.get("point_id") or rec.get("feature_id") or "") for rec in list(point_records or [])]


def _save_shard_checkpoint(
    np: Any,
    *,
    checkpoint_dir: Path | None,
    hazard_key: str | None,
    component_name: str,
    shard: _ExposureShard,
    point_records: list[dict[str, Any]],
    metrics: HazardImpactResult,
) -> Path | None:
    result_path = _shard_result_path(
        checkpoint_dir,
        hazard_key=hazard_key,
        component_name=component_name,
        shard_id=shard.shard_id,
    )
    if result_path is None:
        return None

    raw_event_ids = getattr(metrics, "event_id", None)
    raw_event_names = getattr(metrics, "event_name", None)
    event_ids = np.asarray([str(value) for value in ([] if raw_event_ids is None else list(raw_event_ids))], dtype=str)
    event_names = np.asarray(
        ["" if value is None else str(value) for value in ([] if raw_event_names is None else list(raw_event_names))],
        dtype=str,
    )
    point_ids = np.asarray(_point_id_values(point_records), dtype=str)
    np.savez_compressed(
        result_path,
        eai_direct_by_point=_as_1d_float(np, metrics.eai_direct_by_point),
        at_event_loss=_as_1d_float(np, metrics.at_event_loss),
        event_frequency=_as_1d_float(np, metrics.event_frequency),
        event_id=event_ids,
        event_name=event_names,
        point_id=point_ids,
    )
    return result_path


def _load_shard_checkpoint(
    np: Any,
    *,
    checkpoint_dir: Path | None,
    hazard_key: str | None,
    component_name: str,
    shard: _ExposureShard,
    point_records: list[dict[str, Any]],
    top_n_events: int,
) -> HazardImpactResult | None:
    result_path = _shard_result_path(
        checkpoint_dir,
        hazard_key=hazard_key,
        component_name=component_name,
        shard_id=shard.shard_id,
    )
    if result_path is None or not result_path.exists():
        return None

    expected_point_ids = _point_id_values(point_records)
    try:
        with np.load(result_path, allow_pickle=False) as payload:
            stored_point_ids = [str(value) for value in list(payload.get("point_id", []))]
            if stored_point_ids != expected_point_ids:
                return None
            return _rebuild_component_result(
                np,
                eai_by_point=payload["eai_direct_by_point"],
                at_event_loss=payload["at_event_loss"],
                event_frequency=payload["event_frequency"],
                event_id=[str(value) for value in list(payload.get("event_id", []))],
                event_name=[(str(value) if str(value) else None) for value in list(payload.get("event_name", []))],
                top_n_events=top_n_events,
            )
    except Exception as exc:
        logger.warning(
            "Ignoring unreadable shard checkpoint %s (%s: %s)",
            result_path,
            type(exc).__name__,
            exc,
        )
        return None


def _save_shard_split_plan(
    *,
    checkpoint_dir: Path | None,
    hazard_key: str | None,
    component_name: str,
    parent_shard: _ExposureShard,
    child_shards: list[_ExposureShard],
) -> Path | None:
    plan_path = _shard_split_plan_path(
        checkpoint_dir,
        hazard_key=hazard_key,
        component_name=component_name,
        shard_id=parent_shard.shard_id,
    )
    if plan_path is None:
        return None
    payload = {
        "parent_shard_id": parent_shard.shard_id,
        "retry_depth": int(parent_shard.retry_depth),
        "children": [
            {
                "shard_id": shard.shard_id,
                "point_indices": [int(value) for value in shard.point_indices],
                "territory_id": shard.territory_id,
                "infra_class": shard.infra_class,
                "retry_depth": int(shard.retry_depth),
            }
            for shard in child_shards
        ],
    }
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path


def _load_shard_split_plan(
    *,
    checkpoint_dir: Path | None,
    hazard_key: str | None,
    component_name: str,
    shard: _ExposureShard,
) -> list[_ExposureShard] | None:
    plan_path = _shard_split_plan_path(
        checkpoint_dir,
        hazard_key=hazard_key,
        component_name=component_name,
        shard_id=shard.shard_id,
    )
    if plan_path is None or not plan_path.exists():
        return None
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "Ignoring unreadable shard split plan %s (%s: %s)",
            plan_path,
            type(exc).__name__,
            exc,
        )
        return None
    children = payload.get("children") if isinstance(payload, dict) else None
    if not isinstance(children, list) or not children:
        return None
    out: list[_ExposureShard] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        indices = tuple(int(value) for value in list(child.get("point_indices") or []))
        if not indices:
            continue
        out.append(
            _ExposureShard(
                shard_id=str(child.get("shard_id") or f"{shard.shard_id}-child"),
                point_indices=indices,
                territory_id=str(child.get("territory_id") or shard.territory_id),
                infra_class=str(child.get("infra_class") or shard.infra_class),
                retry_depth=int(child.get("retry_depth") or (int(shard.retry_depth) + 1)),
            )
        )
    return out or None


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(dict(payload))
    except Exception as exc:
        logger.warning("Progress callback failed (%s: %s)", type(exc).__name__, exc)


def _estimate_component_memory_bytes(
    *,
    event_count: int,
    point_count: int,
    component_name: str,
) -> int:
    if event_count <= 0 or point_count <= 0:
        return 0
    multiplier = float(_SHARD_MEMORY_MULTIPLIER.get(str(component_name), 1.0))
    dense_bytes = float(event_count) * float(point_count) * 8.0
    return int(max(0.0, dense_bytes * 1.35 * multiplier))


def _resolve_component_point_cap(
    *,
    total_points: int,
    event_count: int,
    component_name: str,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
) -> int:
    if total_points <= 0:
        return 0
    if max_points_per_shard > 0:
        return max(1, min(total_points, int(max_points_per_shard)))
    if memory_budget_gb <= 0.0 or event_count <= 0:
        return total_points

    min_points = max(1, int(min_points_per_shard))
    budget_bytes = float(memory_budget_gb) * float(1024**3)
    per_point_bytes = max(
        1.0,
        float(
            _estimate_component_memory_bytes(
                event_count=event_count,
                point_count=1,
                component_name=component_name,
            )
        ),
    )
    point_cap = int(budget_bytes / per_point_bytes)
    point_cap = max(min_points, point_cap)
    return max(1, min(total_points, point_cap))


def _estimate_dynamic_hazard_memory_bytes(
    *,
    event_count: int,
    point_count: int,
) -> int:
    if event_count <= 0 or point_count <= 0:
        return 0
    dense_bytes = float(event_count) * float(point_count) * 8.0
    return int(max(0.0, dense_bytes * float(_DYNAMIC_HAZARD_MEMORY_MULTIPLIER)))


def _resolve_dynamic_hazard_point_cap(
    *,
    total_points: int,
    event_count: int,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
) -> int:
    if total_points <= 0:
        return 0
    if max_points_per_shard > 0:
        return max(1, min(total_points, int(max_points_per_shard)))
    if memory_budget_gb <= 0.0 or event_count <= 0:
        return total_points

    min_points = max(1, int(min_points_per_shard))
    budget_bytes = float(memory_budget_gb) * float(1024**3)
    per_point_bytes = max(
        1.0,
        float(
            _estimate_dynamic_hazard_memory_bytes(
                event_count=event_count,
                point_count=1,
            )
        ),
    )
    point_cap = int(budget_bytes / per_point_bytes)
    point_cap = max(min_points, point_cap)
    return max(1, min(total_points, point_cap))


def _dynamic_hazard_budget_exceeded_at_min_shard(
    *,
    event_count: int,
    memory_budget_gb: float,
    min_points_per_shard: int,
) -> bool:
    if memory_budget_gb <= 0.0 or event_count <= 0:
        return False
    min_points = max(1, int(min_points_per_shard))
    shard_bytes = _estimate_dynamic_hazard_memory_bytes(
        event_count=event_count,
        point_count=min_points,
    )
    return float(shard_bytes) > float(memory_budget_gb) * float(1024**3)


def _plan_hazard_shards(
    point_records: list[dict[str, Any]],
    *,
    max_points_per_shard: int,
) -> list[_ExposureShard]:
    total_points = len(point_records)
    if total_points <= 0:
        return []
    point_cap = max(1, int(max_points_per_shard))
    if total_points <= point_cap:
        first = point_records[0] if point_records else {}
        return [
            _ExposureShard(
                shard_id="hazard-0001",
                point_indices=tuple(range(total_points)),
                territory_id=str(first.get("territory_id") or "mixed"),
                infra_class="mixed",
            )
        ]

    grouped_indices: dict[str, list[int]] = {}
    for idx, rec in enumerate(point_records):
        territory_id = str(rec.get("territory_id") or "unknown")
        grouped_indices.setdefault(territory_id, []).append(idx)

    shards: list[_ExposureShard] = []
    counter = 1
    for territory_id, indices in grouped_indices.items():
        for start in range(0, len(indices), point_cap):
            chunk = tuple(indices[start : start + point_cap])
            if not chunk:
                continue
            shards.append(
                _ExposureShard(
                    shard_id=f"hazard-{counter:04d}",
                    point_indices=chunk,
                    territory_id=territory_id,
                    infra_class="mixed",
                )
            )
            counter += 1
    return shards


def _init_component_result_accumulator(np: Any, *, total_points: int) -> dict[str, Any]:
    return {
        "eai_by_point": np.zeros(total_points, dtype=float),
        "at_event_total": None,
        "event_frequency": None,
        "event_id": None,
        "event_name": None,
    }


def _merge_component_result_accumulator(
    np: Any,
    *,
    accumulator: dict[str, Any],
    shard: _ExposureShard,
    metrics: HazardImpactResult,
) -> None:
    shard_eai = _as_1d_float(np, metrics.eai_direct_by_point)
    for offset, point_idx in enumerate(shard.point_indices):
        if offset >= shard_eai.size:
            break
        accumulator["eai_by_point"][int(point_idx)] = float(shard_eai[offset])

    shard_at_event = _as_1d_float(np, metrics.at_event_loss)
    if accumulator["at_event_total"] is None:
        accumulator["at_event_total"] = np.zeros(shard_at_event.size, dtype=float)
    elif shard_at_event.size != accumulator["at_event_total"].size:
        raise RuntimeError(
            "Hazard-sharded component aggregation produced inconsistent event counts: "
            f"expected {accumulator['at_event_total'].size}, got {shard_at_event.size}."
        )
    if shard_at_event.size:
        accumulator["at_event_total"] += shard_at_event

    if accumulator["event_frequency"] is None:
        accumulator["event_frequency"] = _as_1d_float(np, metrics.event_frequency)
    if accumulator["event_id"] is None:
        accumulator["event_id"] = getattr(metrics, "event_id", [])
    if accumulator["event_name"] is None:
        accumulator["event_name"] = getattr(metrics, "event_name", [])


def _finalize_component_result_accumulator(
    np: Any,
    *,
    accumulator: dict[str, Any],
    event_count: int,
    top_n_events: int,
) -> HazardImpactResult:
    at_event_total = accumulator["at_event_total"]
    if at_event_total is None:
        at_event_total = np.zeros(event_count, dtype=float)
    event_frequency = accumulator["event_frequency"]
    if event_frequency is None:
        event_frequency = np.zeros(event_count, dtype=float)
    event_id = accumulator["event_id"] if accumulator["event_id"] is not None else []
    event_name = accumulator["event_name"] if accumulator["event_name"] is not None else []
    return _rebuild_component_result(
        np,
        eai_by_point=accumulator["eai_by_point"],
        at_event_loss=at_event_total,
        event_frequency=event_frequency,
        event_id=event_id,
        event_name=event_name,
        top_n_events=top_n_events,
    )


def _scoped_dynamic_progress_callback(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    hazard_shard_id: str,
) -> Callable[[dict[str, Any]], None] | None:
    if progress_callback is None:
        return None

    def _callback(payload: dict[str, Any]) -> None:
        event_name = str(payload.get("event") or "")
        if event_name in {"component_plan", "component_complete"}:
            return
        scoped = dict(payload)
        scoped["hazard_shard_id"] = str(hazard_shard_id)
        shard_id = scoped.get("shard_id")
        if shard_id is not None:
            scoped["shard_id"] = f"{hazard_shard_id}__{shard_id}"
        progress_callback(scoped)

    return _callback


def _plan_exposure_shards(
    point_records: list[dict[str, Any]],
    *,
    max_points_per_shard: int,
) -> list[_ExposureShard]:
    total_points = len(point_records)
    if total_points <= 0:
        return []
    point_cap = max(1, int(max_points_per_shard))
    if total_points <= point_cap:
        first = point_records[0] if point_records else {}
        return [
            _ExposureShard(
                shard_id="shard-0001",
                point_indices=tuple(range(total_points)),
                territory_id=str(first.get("territory_id") or "mixed"),
                infra_class=str(first.get("infra_class") or "mixed"),
            )
        ]

    grouped_indices: dict[tuple[str, str], list[int]] = {}
    for idx, rec in enumerate(point_records):
        key = (
            str(rec.get("territory_id") or "unknown"),
            str(rec.get("infra_class") or "unknown"),
        )
        grouped_indices.setdefault(key, []).append(idx)

    shards: list[_ExposureShard] = []
    counter = 1
    for (territory_id, infra_class), indices in grouped_indices.items():
        for start in range(0, len(indices), point_cap):
            chunk = tuple(indices[start : start + point_cap])
            if not chunk:
                continue
            shards.append(
                _ExposureShard(
                    shard_id=f"shard-{counter:04d}",
                    point_indices=chunk,
                    territory_id=territory_id,
                    infra_class=infra_class,
                )
            )
            counter += 1
    return shards


def _split_exposure_shard(
    shard: _ExposureShard,
    *,
    min_points_per_shard: int,
) -> list[_ExposureShard] | None:
    min_points = max(1, int(min_points_per_shard))
    if shard.point_count < (min_points * 2):
        return None

    mid = shard.point_count // 2
    left = tuple(shard.point_indices[:mid])
    right = tuple(shard.point_indices[mid:])
    if len(left) < min_points or len(right) < min_points:
        return None

    next_depth = int(shard.retry_depth) + 1
    return [
        _ExposureShard(
            shard_id=f"{shard.shard_id}a",
            point_indices=left,
            territory_id=shard.territory_id,
            infra_class=shard.infra_class,
            retry_depth=next_depth,
        ),
        _ExposureShard(
            shard_id=f"{shard.shard_id}b",
            point_indices=right,
            territory_id=shard.territory_id,
            infra_class=shard.infra_class,
            retry_depth=next_depth,
        ),
    ]


def _rebuild_component_result(
    np: Any,
    *,
    eai_by_point: Any,
    at_event_loss: Any,
    event_frequency: Any,
    event_id: Any,
    event_name: Any,
    top_n_events: int,
) -> HazardImpactResult:
    eai = _as_1d_float(np, eai_by_point)
    at_event = _as_1d_float(np, at_event_loss)
    frequency = _as_1d_float(np, event_frequency)
    max_loss_by_point = _approx_max_loss_per_point(np, eai, at_event)
    view = _SimpleImpactView(event_id=event_id, event_name=event_name)
    return HazardImpactResult(
        eai_direct_by_point=eai,
        max_loss_by_point=max_loss_by_point,
        at_event_loss=at_event,
        event_frequency=frequency,
        event_id=event_id,
        event_name=event_name,
        aai_agg_eur=float(eai.sum()),
        max_event_loss_eur=float(at_event.max()) if at_event.size else 0.0,
        pml_eur=_compute_pml(np, at_event, frequency, RETURN_PERIODS),
        tvar_95_eur=_compute_tvar_95(np, at_event, frequency),
        top_events=_extract_top_events(np, view, at_event, frequency, top_n_events),
    )


def _compute_component_impact_sharded(
    np: Any,
    ImpactCalc: Any,
    *,
    exposure_bundle: ClimadaExposureBundle,
    exposure_builder: Callable[[ClimadaExposureBundle], Any],
    impfset: Any,
    hazard_obj: Any,
    top_n_events: int,
    component_name: str,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
    max_shard_retry_depth: int,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    hazard_key: str | None = None,
    checkpoint_dir: Path | None = None,
    resume_enabled: bool = False,
) -> tuple[HazardImpactResult, dict[str, Any]]:
    point_records = list(exposure_bundle.point_records or [])
    total_points = len(point_records)
    event_count = int(_as_1d_float(np, getattr(hazard_obj, "frequency", [])).size)
    full_estimated_bytes = _estimate_component_memory_bytes(
        event_count=event_count,
        point_count=total_points,
        component_name=component_name,
    )
    point_cap = _resolve_component_point_cap(
        total_points=total_points,
        event_count=event_count,
        component_name=component_name,
        memory_budget_gb=memory_budget_gb,
        max_points_per_shard=max_points_per_shard,
        min_points_per_shard=min_points_per_shard,
    )

    sharding_info: dict[str, Any] = {
        "component": str(component_name),
        "total_points": int(total_points),
        "event_count": int(event_count),
        "memory_budget_gb": round(float(memory_budget_gb), 3),
        "estimated_full_memory_gb": round(float(full_estimated_bytes) / float(1024**3), 3),
        "max_points_per_shard": int(point_cap),
        "planned_shards": 1,
        "completed_shards": 0,
        "retry_splits": 0,
        "resumed_shards": 0,
        "sharded": bool(point_cap > 0 and point_cap < total_points),
        "status": "running",
    }

    if total_points <= 0:
        result = _rebuild_component_result(
            np,
            eai_by_point=np.zeros(0, dtype=float),
            at_event_loss=np.zeros(event_count, dtype=float),
            event_frequency=np.asarray(getattr(hazard_obj, "frequency", []), dtype=float).reshape(-1),
            event_id=getattr(hazard_obj, "event_id", []),
            event_name=getattr(hazard_obj, "event_name", []),
            top_n_events=top_n_events,
        )
        result.matching = {
            "status": "complete",
            "hazard": str(hazard_key or "unknown"),
            "component": str(component_name),
            "point_count": 0,
            "point_value_total_eur": 0.0,
            "centroid_count": int(getattr(getattr(hazard_obj, "centroids", None), "size", 0) or 0),
            "assignment_threshold_deg": float(CENTROID_ASSIGNMENT_THRESHOLD_DEG),
            "assigned_point_count": 0,
            "assigned_point_fraction": 0.0,
            "positive_hazard_point_count": 0,
            "positive_hazard_point_fraction": 0.0,
            "positive_direct_loss_point_count": 0,
            "positive_direct_loss_point_fraction": 0.0,
        }
        sharding_info["status"] = "complete"
        return result, sharding_info

    if not sharding_info["sharded"]:
        single_shard = _ExposureShard(
            shard_id="shard-0001",
            point_indices=tuple(range(total_points)),
            territory_id=str((point_records[0] or {}).get("territory_id") or "mixed") if point_records else "mixed",
            infra_class=str((point_records[0] or {}).get("infra_class") or "mixed") if point_records else "mixed",
        )
        _emit_progress(
            progress_callback,
            {
                "event": "component_plan",
                "hazard": hazard_key,
                "component": component_name,
                **sharding_info,
            },
        )
        if resume_enabled:
            cached_metrics = _load_shard_checkpoint(
                np,
                checkpoint_dir=checkpoint_dir,
                hazard_key=hazard_key,
                component_name=component_name,
                shard=single_shard,
                point_records=point_records,
                top_n_events=top_n_events,
            )
            if cached_metrics is not None:
                sharding_info["completed_shards"] = 1
                sharding_info["resumed_shards"] = 1
                sharding_info["status"] = "complete"
                _emit_progress(
                    progress_callback,
                    {
                        "event": "shard_complete",
                        "hazard": hazard_key,
                        "component": component_name,
                        "shard_id": single_shard.shard_id,
                        "retry_depth": int(single_shard.retry_depth),
                        "point_count": int(single_shard.point_count),
                        "completed_shards": 1,
                        "planned_shards": 1,
                        "territory_id": single_shard.territory_id,
                        "infra_class": single_shard.infra_class,
                        "resumed": True,
                    },
                )
                _emit_progress(
                    progress_callback,
                    {
                        "event": "component_complete",
                        "hazard": hazard_key,
                        "component": component_name,
                        **sharding_info,
                    },
                )
                return cached_metrics, sharding_info
        component_exposures = exposure_builder(exposure_bundle)
        metrics = _compute_component_impact(
            np,
            ImpactCalc,
            exposures=component_exposures,
            impfset=impfset,
            hazard_obj=hazard_obj,
            top_n_events=top_n_events,
        )
        metrics.matching = _compute_matching_summary(
            np,
            exposures=component_exposures,
            point_records=point_records,
            hazard_obj=hazard_obj,
            direct_eai_by_point=metrics.eai_direct_by_point,
            component_name=component_name,
            hazard_key=hazard_key,
        )
        _save_shard_checkpoint(
            np,
            checkpoint_dir=checkpoint_dir,
            hazard_key=hazard_key,
            component_name=component_name,
            shard=single_shard,
            point_records=point_records,
            metrics=metrics,
        )
        sharding_info["completed_shards"] = 1
        sharding_info["status"] = "complete"
        _emit_progress(
            progress_callback,
            {
                "event": "component_complete",
                "hazard": hazard_key,
                "component": component_name,
                **sharding_info,
            },
        )
        return metrics, sharding_info

    pending_shards = _plan_exposure_shards(
        point_records,
        max_points_per_shard=point_cap,
    )
    sharding_info["planned_shards"] = len(pending_shards)
    _emit_progress(
        progress_callback,
        {
            "event": "component_plan",
            "hazard": hazard_key,
            "component": component_name,
            **sharding_info,
        },
    )

    eai_by_point = np.zeros(total_points, dtype=float)
    at_event_total = None
    event_frequency = None
    event_id = None
    event_name = None

    while pending_shards:
        shard = pending_shards.pop(0)
        if resume_enabled:
            split_plan = _load_shard_split_plan(
                checkpoint_dir=checkpoint_dir,
                hazard_key=hazard_key,
                component_name=component_name,
                shard=shard,
            )
            if split_plan:
                pending_shards = list(split_plan) + pending_shards
                sharding_info["planned_shards"] = int(sharding_info["completed_shards"]) + len(pending_shards)
                continue

            cached_metrics = _load_shard_checkpoint(
                np,
                checkpoint_dir=checkpoint_dir,
                hazard_key=hazard_key,
                component_name=component_name,
                shard=shard,
                point_records=[point_records[idx] for idx in shard.point_indices],
                top_n_events=top_n_events,
            )
            if cached_metrics is not None:
                shard_eai = _as_1d_float(np, cached_metrics.eai_direct_by_point)
                for offset, point_idx in enumerate(shard.point_indices):
                    if offset >= shard_eai.size:
                        break
                    eai_by_point[int(point_idx)] = float(shard_eai[offset])

                shard_at_event = _as_1d_float(np, cached_metrics.at_event_loss)
                if at_event_total is None:
                    at_event_total = np.zeros(shard_at_event.size, dtype=float)
                elif shard_at_event.size != at_event_total.size:
                    raise RuntimeError(
                        f"Sharded component '{component_name}' produced inconsistent cached event counts: "
                        f"expected {at_event_total.size}, got {shard_at_event.size}."
                    )
                if shard_at_event.size:
                    at_event_total += shard_at_event

                if event_frequency is None:
                    event_frequency = _as_1d_float(np, cached_metrics.event_frequency)
                if event_id is None:
                    event_id = getattr(cached_metrics, "event_id", [])
                if event_name is None:
                    event_name = getattr(cached_metrics, "event_name", [])

                sharding_info["completed_shards"] = int(sharding_info["completed_shards"]) + 1
                sharding_info["resumed_shards"] = int(sharding_info["resumed_shards"]) + 1
                _emit_progress(
                    progress_callback,
                    {
                        "event": "shard_complete",
                        "hazard": hazard_key,
                        "component": component_name,
                        "shard_id": shard.shard_id,
                        "retry_depth": int(shard.retry_depth),
                        "point_count": int(shard.point_count),
                        "completed_shards": int(sharding_info["completed_shards"]),
                        "planned_shards": int(sharding_info["planned_shards"]),
                        "territory_id": shard.territory_id,
                        "infra_class": shard.infra_class,
                        "resumed": True,
                    },
                )
                continue

        _emit_progress(
            progress_callback,
            {
                "event": "shard_start",
                "hazard": hazard_key,
                "component": component_name,
                "shard_id": shard.shard_id,
                "retry_depth": int(shard.retry_depth),
                "point_count": int(shard.point_count),
                "planned_shards": int(sharding_info["planned_shards"]),
                "completed_shards": int(sharding_info["completed_shards"]),
                "territory_id": shard.territory_id,
                "infra_class": shard.infra_class,
            },
        )
        try:
            shard_bundle = subset_climada_exposure_bundle(
                exposure_bundle,
                point_indices=list(shard.point_indices),
            )
            shard_metrics = _compute_component_impact(
                np,
                ImpactCalc,
                exposures=exposure_builder(shard_bundle),
                impfset=impfset,
                hazard_obj=hazard_obj,
                top_n_events=top_n_events,
            )
        except MemoryError as exc:
            split_shards = None
            if int(shard.retry_depth) < max(0, int(max_shard_retry_depth)):
                split_shards = _split_exposure_shard(
                    shard,
                    min_points_per_shard=min_points_per_shard,
                )
            if split_shards:
                pending_shards = list(split_shards) + pending_shards
                sharding_info["retry_splits"] = int(sharding_info["retry_splits"]) + 1
                sharding_info["planned_shards"] = int(sharding_info["completed_shards"]) + len(pending_shards)
                _save_shard_split_plan(
                    checkpoint_dir=checkpoint_dir,
                    hazard_key=hazard_key,
                    component_name=component_name,
                    parent_shard=shard,
                    child_shards=split_shards,
                )
                _emit_progress(
                    progress_callback,
                    {
                        "event": "shard_split_retry",
                        "hazard": hazard_key,
                        "component": component_name,
                        "shard_id": shard.shard_id,
                        "retry_depth": int(shard.retry_depth),
                        "point_count": int(shard.point_count),
                        "error": f"{type(exc).__name__}: {exc}",
                        "planned_shards": int(sharding_info["planned_shards"]),
                    },
                )
                continue
            raise

        shard_eai = _as_1d_float(np, shard_metrics.eai_direct_by_point)
        for offset, point_idx in enumerate(shard.point_indices):
            if offset >= shard_eai.size:
                break
            eai_by_point[int(point_idx)] = float(shard_eai[offset])

        shard_at_event = _as_1d_float(np, shard_metrics.at_event_loss)
        if at_event_total is None:
            at_event_total = np.zeros(shard_at_event.size, dtype=float)
        elif shard_at_event.size != at_event_total.size:
            raise RuntimeError(
                f"Sharded component '{component_name}' produced inconsistent event counts: "
                f"expected {at_event_total.size}, got {shard_at_event.size}."
            )
        if shard_at_event.size:
            at_event_total += shard_at_event

        _save_shard_checkpoint(
            np,
            checkpoint_dir=checkpoint_dir,
            hazard_key=hazard_key,
            component_name=component_name,
            shard=shard,
            point_records=[point_records[idx] for idx in shard.point_indices],
            metrics=shard_metrics,
        )

        if event_frequency is None:
            event_frequency = _as_1d_float(np, shard_metrics.event_frequency)
        if event_id is None:
            event_id = getattr(shard_metrics, "event_id", [])
        if event_name is None:
            event_name = getattr(shard_metrics, "event_name", [])

        sharding_info["completed_shards"] = int(sharding_info["completed_shards"]) + 1
        _emit_progress(
            progress_callback,
            {
                "event": "shard_complete",
                "hazard": hazard_key,
                "component": component_name,
                "shard_id": shard.shard_id,
                "retry_depth": int(shard.retry_depth),
                "point_count": int(shard.point_count),
                "completed_shards": int(sharding_info["completed_shards"]),
                "planned_shards": int(sharding_info["planned_shards"]),
                "territory_id": shard.territory_id,
                "infra_class": shard.infra_class,
            },
        )

    if at_event_total is None:
        at_event_total = np.zeros(event_count, dtype=float)
    if event_frequency is None:
        event_frequency = _as_1d_float(np, getattr(hazard_obj, "frequency", []))
    if event_id is None:
        event_id = getattr(hazard_obj, "event_id", [])
    if event_name is None:
        event_name = getattr(hazard_obj, "event_name", [])

    result = _rebuild_component_result(
        np,
        eai_by_point=eai_by_point,
        at_event_loss=at_event_total,
        event_frequency=event_frequency,
        event_id=event_id,
        event_name=event_name,
        top_n_events=top_n_events,
    )
    matching_exposures = exposure_builder(exposure_bundle)
    result.matching = _compute_matching_summary(
        np,
        exposures=matching_exposures,
        point_records=point_records,
        hazard_obj=hazard_obj,
        direct_eai_by_point=result.eai_direct_by_point,
        component_name=component_name,
        hazard_key=hazard_key,
    )
    sharding_info["status"] = "complete"
    _emit_progress(
        progress_callback,
        {
            "event": "component_complete",
            "hazard": hazard_key,
            "component": component_name,
            **sharding_info,
        },
    )
    return result, sharding_info


def _compute_component_impact(
    np: Any,
    ImpactCalc: Any,
    *,
    exposures: Any,
    impfset: Any,
    hazard_obj: Any,
    top_n_events: int,
) -> HazardImpactResult:
    exposures.assign_centroids(
        hazard_obj,
        distance="euclidean",
        threshold=float(CENTROID_ASSIGNMENT_THRESHOLD_DEG),
        overwrite=True,
    )
    impact = ImpactCalc(exposures, impfset, hazard_obj).impact(
        save_mat=False,
        assign_centroids=False,
    )
    eai_exp = _as_1d_float(np, getattr(impact, "eai_exp", []))
    at_event = _as_1d_float(np, getattr(impact, "at_event", []))
    max_loss_point = _approx_max_loss_per_point(np, eai_exp, at_event)
    frequency = _as_1d_float(np, getattr(impact, "frequency", []))

    return HazardImpactResult(
        eai_direct_by_point=eai_exp,
        max_loss_by_point=max_loss_point,
        at_event_loss=at_event,
        event_frequency=frequency,
        event_id=getattr(impact, "event_id", []),
        event_name=getattr(impact, "event_name", []),
        aai_agg_eur=float(getattr(impact, "aai_agg", 0.0) or 0.0),
        max_event_loss_eur=float(at_event.max()) if at_event.size else 0.0,
        pml_eur=_compute_pml(np, at_event, frequency, RETURN_PERIODS),
        tvar_95_eur=_compute_tvar_95(np, at_event, frequency),
        top_events=_extract_top_events(np, impact, at_event, frequency, top_n_events),
    )


def _combine_component_results(
    np: Any,
    *,
    components: list[HazardImpactResult],
    point_values_eur: list[float],
    top_n_events: int,
) -> HazardImpactResult:
    if len(components) == 1:
        return components[0]

    point_values = _as_1d_float(np, point_values_eur)
    if point_values.size == 0:
        point_values = np.zeros(0, dtype=float)

    sum_eai = np.zeros(point_values.size, dtype=float)
    sum_max = np.zeros(point_values.size, dtype=float)
    for comp in components:
        eai = _as_1d_float(np, comp.eai_direct_by_point)
        max_loss = _as_1d_float(np, comp.max_loss_by_point)
        n_eai = min(sum_eai.size, eai.size)
        n_max = min(sum_max.size, max_loss.size)
        if n_eai > 0:
            sum_eai[:n_eai] += eai[:n_eai]
        if n_max > 0:
            sum_max[:n_max] += max_loss[:n_max]

    capped_eai = np.minimum(np.maximum(point_values, 0.0), np.maximum(sum_eai, 0.0))
    capped_max = np.minimum(np.maximum(point_values, 0.0), np.maximum(sum_max, 0.0))

    base = components[0]
    at_event = _as_1d_float(np, base.at_event_loss).copy()
    frequency = _as_1d_float(np, base.event_frequency)
    event_id = getattr(base, "event_id", [])
    event_name = getattr(base, "event_name", [])
    for comp in components[1:]:
        comp_at_event = _as_1d_float(np, comp.at_event_loss)
        if comp_at_event.size == at_event.size:
            at_event += comp_at_event

    view = _SimpleImpactView(event_id=event_id, event_name=event_name)
    return HazardImpactResult(
        eai_direct_by_point=capped_eai,
        max_loss_by_point=capped_max,
        at_event_loss=at_event,
        event_frequency=frequency,
        event_id=event_id,
        event_name=event_name,
        aai_agg_eur=float(capped_eai.sum()),
        max_event_loss_eur=float(at_event.max()) if at_event.size else 0.0,
        pml_eur=_compute_pml(np, at_event, frequency, RETURN_PERIODS),
        tvar_95_eur=_compute_tvar_95(np, at_event, frequency),
        top_events=_extract_top_events(np, view, at_event, frequency, top_n_events),
    )


def _compute_dynamic_hazard_sharded_results(
    np: Any,
    ImpactCalc: Any,
    *,
    exposure_bundle: ClimadaExposureBundle,
    tracks: Any,
    hazard_key: str,
    storm_years: int,
    top_n_events: int,
    hazard_shards: list[_ExposureShard],
    hazard_point_cap: int,
    impfset_wind: Any,
    requested_rain_model: str,
    rain_max_dist_inland_km: float,
    multi_hazard_ready: bool,
    multi_hazard_model: Any,
    impfset_rain: Any,
    impfset_surge: Any,
    TCRain: Any,
    TCSurgeBathtub: Any,
    surge_topo_path: Path | None,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
    max_shard_retry_depth: int,
    strict_required_components: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
    resume_enabled: bool = False,
) -> tuple[HazardImpactResult, dict[str, HazardImpactResult], dict[str, str], dict[str, dict[str, Any]], list[str]]:
    point_records = list(exposure_bundle.point_records or [])
    total_points = len(point_records)
    point_values_eur = [max(0.0, float(rec.get("value_eur", 0.0))) for rec in point_records]
    event_count = int(len(getattr(tracks, "data", []))) if tracks is not None else 0
    planned_shards = max(1, len(hazard_shards))
    full_hazard_bytes = _estimate_dynamic_hazard_memory_bytes(
        event_count=event_count,
        point_count=total_points,
    )

    component_notes: list[str] = [
        f"{hazard_key}: dynamic hazard construction sharded across {planned_shards} centroid shard(s) with a cap of {int(max(1, hazard_point_cap))} points per shard.",
    ]
    components: dict[str, HazardImpactResult] = {}
    component_status: dict[str, str] = {}
    component_sharding: dict[str, dict[str, Any]] = {}

    if total_points <= 0:
        empty = _rebuild_component_result(
            np,
            eai_by_point=np.zeros(0, dtype=float),
            at_event_loss=np.zeros(event_count, dtype=float),
            event_frequency=np.zeros(event_count, dtype=float),
            event_id=[],
            event_name=[],
            top_n_events=top_n_events,
        )
        components["wind"] = empty
        component_status["wind"] = "complete"
        component_sharding["wind"] = {
            "component": "wind",
            "status": "complete",
            "sharded": False,
            "hazard_sharded": False,
            "planned_shards": 0,
            "completed_shards": 0,
            "retry_splits": 0,
            "resumed_shards": 0,
        }
        return empty, components, component_status, component_sharding, component_notes

    component_enabled = {
        "wind": True,
        "rain": bool(multi_hazard_ready and multi_hazard_model is not None and impfset_rain is not None and TCRain is not None and tracks is not None),
        "surge": bool(multi_hazard_ready and multi_hazard_model is not None and impfset_surge is not None and TCSurgeBathtub is not None and surge_topo_path is not None and Path(surge_topo_path).exists()),
    }
    if multi_hazard_ready and not component_enabled["rain"]:
        component_status["rain"] = "skipped"
        component_sharding["rain"] = {"status": "skipped", "reason": "dynamic_tracks_unavailable"}
        component_notes.append(
            f"{hazard_key}: rain component skipped because dynamic tracks are unavailable for hazard-sharded execution."
        )
    if multi_hazard_ready and surge_topo_path is None:
        component_status["surge"] = "skipped"
        component_sharding["surge"] = {"status": "skipped", "reason": "missing_topo_path"}
        component_notes.append(f"{hazard_key}: surge component skipped (no DEM path configured).")
    elif multi_hazard_ready and surge_topo_path is not None and not Path(surge_topo_path).exists():
        component_status["surge"] = "skipped"
        component_sharding["surge"] = {"status": "skipped", "reason": f"missing_topo:{surge_topo_path}"}
        component_notes.append(f"{hazard_key}: surge component skipped (DEM not found at {surge_topo_path}).")

    component_accumulators: dict[str, dict[str, Any] | None] = {}
    component_completed_shards: dict[str, int] = {}
    component_resumed_shards: dict[str, int] = {}
    component_retry_splits: dict[str, int] = {}
    component_inner_sharded: dict[str, bool] = {}
    component_plan_payloads: dict[str, dict[str, Any]] = {}

    for component_name in ("wind", "rain", "surge"):
        if not component_enabled.get(component_name):
            continue
        component_accumulators[component_name] = _init_component_result_accumulator(np, total_points=total_points)
        component_completed_shards[component_name] = 0
        component_resumed_shards[component_name] = 0
        component_retry_splits[component_name] = 0
        component_inner_sharded[component_name] = False
        component_plan_payloads[component_name] = {
            "event": "component_plan",
            "hazard": hazard_key,
            "component": component_name,
            "total_points": int(total_points),
            "event_count": int(event_count),
            "memory_budget_gb": round(float(memory_budget_gb), 3),
            "estimated_full_memory_gb": round(
                float(
                    max(
                        full_hazard_bytes,
                        _estimate_component_memory_bytes(
                            event_count=event_count,
                            point_count=total_points,
                            component_name=component_name,
                        ),
                    )
                )
                / float(1024**3),
                3,
            ),
            "max_points_per_shard": int(max(1, hazard_point_cap)),
            "planned_shards": int(planned_shards),
            "completed_shards": 0,
            "retry_splits": 0,
            "resumed_shards": 0,
            "sharded": bool(planned_shards > 1),
            "hazard_sharded": True,
        }
        _emit_progress(progress_callback, component_plan_payloads[component_name])

    surge_fraction_note_added = False
    surge_topo_note_added = False

    for hazard_shard in hazard_shards:
        shard_point_indices = list(hazard_shard.point_indices)
        shard_bundle = subset_climada_exposure_bundle(
            exposure_bundle,
            point_indices=shard_point_indices,
        )
        shard_point_records = list(shard_bundle.point_records or [])
        shard_coords = [
            (float(rec.get("lat")), float(rec.get("lon")))
            for rec in shard_point_records
            if rec.get("lat") is not None and rec.get("lon") is not None
        ]
        if not shard_coords:
            continue

        centroids = _build_centroids_from_points(shard_coords)
        wind_hazard = _normalize_frequency_on_copy(
            _build_hazard_from_tracks(tracks, centroids),
            storm_years,
        )
        scoped_progress_callback = _scoped_dynamic_progress_callback(
            progress_callback,
            hazard_shard_id=hazard_shard.shard_id,
        )

        for component_name in ("wind", "surge", "rain"):
            if not component_enabled.get(component_name):
                continue
            if component_accumulators.get(component_name) is None:
                continue

            inner_checkpoint_dir = (
                Path(checkpoint_dir) / "dynamic-hazard-shards" / hazard_key / component_name / hazard_shard.shard_id
                if checkpoint_dir is not None
                else None
            )

            _emit_progress(
                progress_callback,
                {
                    "event": "shard_start",
                    "hazard": hazard_key,
                    "component": component_name,
                    "shard_id": hazard_shard.shard_id,
                    "retry_depth": int(hazard_shard.retry_depth),
                    "point_count": int(hazard_shard.point_count),
                    "completed_shards": int(component_completed_shards.get(component_name, 0)),
                    "planned_shards": int(planned_shards),
                    "territory_id": hazard_shard.territory_id,
                    "infra_class": hazard_shard.infra_class,
                },
            )

            try:
                if component_name == "wind":
                    shard_metrics, inner_sharding = _compute_component_impact_sharded(
                        np,
                        ImpactCalc,
                        exposure_bundle=shard_bundle,
                        exposure_builder=lambda hazard_shard_bundle: hazard_shard_bundle.exposures,
                        impfset=impfset_wind,
                        hazard_obj=wind_hazard,
                        top_n_events=top_n_events,
                        component_name="wind",
                        memory_budget_gb=float(memory_budget_gb),
                        max_points_per_shard=int(max_points_per_shard),
                        min_points_per_shard=int(min_points_per_shard),
                        max_shard_retry_depth=int(max_shard_retry_depth),
                        progress_callback=scoped_progress_callback,
                        hazard_key=hazard_key,
                        checkpoint_dir=inner_checkpoint_dir,
                        resume_enabled=resume_enabled,
                    )
                elif component_name == "surge":
                    prepared_topo = _prepare_topo_raster_for_exposure(
                        Path(surge_topo_path),
                        point_records=shard_point_records,
                    )
                    if prepared_topo != Path(surge_topo_path) and not surge_topo_note_added:
                        component_notes.append(
                            f"{hazard_key}: prepared cropped DEM for surge hazard at {prepared_topo}."
                        )
                        surge_topo_note_added = True
                    surge_hazard, surge_meta = _build_surge_hazard(
                        np,
                        surge_hazard_cls=TCSurgeBathtub,
                        wind_hazard=wind_hazard,
                        topo_path=prepared_topo,
                        hazard_source="dynamic_parquet",
                    )
                    if str(surge_meta.get("fraction_mode") or "") == "pointwise" and not surge_fraction_note_added:
                        rows = surge_meta.get("rows")
                        cols = surge_meta.get("cols")
                        grid_desc = f" estimated fraction grid {rows}x{cols}" if rows and cols else ""
                        component_notes.append(
                            f"{hazard_key}: surge used pointwise land fractions for exposure-aligned centroid shards ({surge_meta.get('reason')}).{grid_desc}"
                        )
                        surge_fraction_note_added = True
                    surge_hazard = _normalize_frequency_on_copy(surge_hazard, storm_years)
                    shard_metrics, inner_sharding = _compute_component_impact_sharded(
                        np,
                        ImpactCalc,
                        exposure_bundle=shard_bundle,
                        exposure_builder=lambda hazard_shard_bundle: _build_exposure_with_impf_column(
                            hazard_shard_bundle.exposures,
                            haz_type=multi_hazard_model.surge_haz_type,
                            impf_ids=[
                                resolve_surge_impf_id(rec.get("asset_type"), multi_hazard_model)
                                for rec in list(hazard_shard_bundle.point_records or [])
                            ],
                        ),
                        impfset=impfset_surge,
                        hazard_obj=surge_hazard,
                        top_n_events=top_n_events,
                        component_name="surge",
                        memory_budget_gb=float(memory_budget_gb),
                        max_points_per_shard=int(max_points_per_shard),
                        min_points_per_shard=int(min_points_per_shard),
                        max_shard_retry_depth=int(max_shard_retry_depth),
                        progress_callback=scoped_progress_callback,
                        hazard_key=hazard_key,
                        checkpoint_dir=inner_checkpoint_dir,
                        resume_enabled=resume_enabled,
                    )
                else:
                    rain_hazard = TCRain.from_tracks(
                        tracks,
                        centroids=wind_hazard.centroids,
                        model=requested_rain_model,
                        ignore_distance_to_coast=True,
                        max_dist_inland_km=float(rain_max_dist_inland_km),
                    )
                    rain_hazard = _normalize_frequency_on_copy(rain_hazard, storm_years)
                    shard_metrics, inner_sharding = _compute_component_impact_sharded(
                        np,
                        ImpactCalc,
                        exposure_bundle=shard_bundle,
                        exposure_builder=lambda hazard_shard_bundle: _build_exposure_with_impf_column(
                            hazard_shard_bundle.exposures,
                            haz_type=multi_hazard_model.rain_haz_type,
                            impf_ids=[
                                resolve_rain_impf_id(rec.get("asset_type"), multi_hazard_model)
                                for rec in list(hazard_shard_bundle.point_records or [])
                            ],
                        ),
                        impfset=impfset_rain,
                        hazard_obj=rain_hazard,
                        top_n_events=top_n_events,
                        component_name="rain",
                        memory_budget_gb=float(memory_budget_gb),
                        max_points_per_shard=int(max_points_per_shard),
                        min_points_per_shard=int(min_points_per_shard),
                        max_shard_retry_depth=int(max_shard_retry_depth),
                        progress_callback=scoped_progress_callback,
                        hazard_key=hazard_key,
                        checkpoint_dir=inner_checkpoint_dir,
                        resume_enabled=resume_enabled,
                    )
            except Exception as exc:
                component_status[component_name] = "failed"
                component_sharding[component_name] = {
                    "component": component_name,
                    "status": "failed",
                    "hazard_sharded": True,
                    "planned_shards": int(planned_shards),
                    "completed_shards": int(component_completed_shards.get(component_name, 0)),
                    "retry_splits": int(component_retry_splits.get(component_name, 0)),
                    "resumed_shards": int(component_resumed_shards.get(component_name, 0)),
                    "max_points_per_shard": int(max(1, hazard_point_cap)),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                component_accumulators[component_name] = None
                _emit_progress(
                    progress_callback,
                    {
                        "event": "component_failed",
                        "hazard": hazard_key,
                        "component": component_name,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                if component_name == "wind" or strict_required_components:
                    raise RuntimeError(
                        f"{hazard_key} {component_name} component failed under hazard sharding: {type(exc).__name__}: {exc}"
                    ) from exc
                logger.warning(
                    "%s %s component failed during hazard-sharded execution (%s: %s)",
                    hazard_key,
                    component_name,
                    type(exc).__name__,
                    exc,
                )
                component_notes.append(
                    f"{hazard_key}: {component_name} component failed during hazard-sharded execution ({type(exc).__name__}): {exc}"
                )
                continue

            _merge_component_result_accumulator(
                np,
                accumulator=component_accumulators[component_name],
                shard=hazard_shard,
                metrics=shard_metrics,
            )
            component_completed_shards[component_name] = int(component_completed_shards.get(component_name, 0)) + 1
            component_resumed_shards[component_name] = int(component_resumed_shards.get(component_name, 0)) + int(inner_sharding.get("resumed_shards") or 0)
            component_retry_splits[component_name] = int(component_retry_splits.get(component_name, 0)) + int(inner_sharding.get("retry_splits") or 0)
            component_inner_sharded[component_name] = bool(component_inner_sharded.get(component_name) or inner_sharding.get("sharded"))
            _emit_progress(
                progress_callback,
                {
                    "event": "shard_complete",
                    "hazard": hazard_key,
                    "component": component_name,
                    "shard_id": hazard_shard.shard_id,
                    "retry_depth": int(hazard_shard.retry_depth),
                    "point_count": int(hazard_shard.point_count),
                    "completed_shards": int(component_completed_shards.get(component_name, 0)),
                    "planned_shards": int(planned_shards),
                    "territory_id": hazard_shard.territory_id,
                    "infra_class": hazard_shard.infra_class,
                    "resumed": bool(
                        int(inner_sharding.get("completed_shards") or 0) > 0
                        and int(inner_sharding.get("completed_shards") or 0) == int(inner_sharding.get("resumed_shards") or 0)
                    ),
                },
            )

    for component_name in ("wind", "rain", "surge"):
        accumulator = component_accumulators.get(component_name)
        if accumulator is None:
            continue
        metrics = _finalize_component_result_accumulator(
            np,
            accumulator=accumulator,
            event_count=event_count,
            top_n_events=top_n_events,
        )
        components[component_name] = metrics
        component_status[component_name] = "complete"
        component_sharding[component_name] = {
            "component": component_name,
            "status": "complete",
            "hazard_sharded": True,
            "sharded": bool(planned_shards > 1 or component_inner_sharded.get(component_name)),
            "planned_shards": int(planned_shards),
            "completed_shards": int(component_completed_shards.get(component_name, 0)),
            "retry_splits": int(component_retry_splits.get(component_name, 0)),
            "resumed_shards": int(component_resumed_shards.get(component_name, 0)),
            "max_points_per_shard": int(max(1, hazard_point_cap)),
            "estimated_full_memory_gb": component_plan_payloads.get(component_name, {}).get("estimated_full_memory_gb"),
            "inner_sharded": bool(component_inner_sharded.get(component_name)),
        }
        _emit_progress(
            progress_callback,
            {
                "event": "component_complete",
                "hazard": hazard_key,
                "component": component_name,
                **component_plan_payloads.get(component_name, {}),
                "event": "component_complete",
                "completed_shards": int(component_completed_shards.get(component_name, 0)),
                "retry_splits": int(component_retry_splits.get(component_name, 0)),
                "resumed_shards": int(component_resumed_shards.get(component_name, 0)),
            },
        )

    total_metrics = _combine_component_results(
        np,
        components=[components[name] for name in ("wind", "rain", "surge") if name in components],
        point_values_eur=point_values_eur,
        top_n_events=top_n_events,
    )
    total_metrics.matching = _build_combined_matching_summary(
        np,
        hazard_key=hazard_key,
        point_records=point_records,
        total_metrics=total_metrics,
        component_metrics=components,
        hazard_zero_intensity=bool(
            float(total_metrics.max_event_loss_eur) <= 0.0 and float(sum(total_metrics.eai_direct_by_point)) <= 0.0
        ),
    )
    return total_metrics, components, component_status, component_sharding, component_notes


def run_climada_direct_impacts(
    exposure_bundle: ClimadaExposureBundle,
    *,
    hazard_storm_path: Path,
    hazard_storm_cmcc_path: Path,
    storm_years: int,
    top_n_events: int = 20,
    prefer_dynamic_hazards: bool = True,
    fallback_to_precomputed_hazards: bool = True,
    storm_parquet_path: Path | None = None,
    storm_cmcc_parquet_path: Path | None = None,
    basin_coverages: tuple[BasinCoverage, ...] = DEFAULT_BASIN_COVERAGES,
    wind_unit_in: str = "m/s",
    radius_unit_in: str = "km",
    env_pressure_hpa: float = 1010.0,
    dynamic_max_tracks: int = 1200,
    track_cache_max_entries: int | None = None,
    multi_hazard_enabled: bool = True,
    rain_model: str = "R-CLIPER",
    rain_max_dist_inland_km: float = 2000.0,
    surge_topo_path: Path | None = None,
    flood_curve_file: Path | None = None,
    wind_asset_type_to_curve_code: dict[str, str] | None = None,
    flood_asset_type_to_curve_code: dict[str, str] | None = None,
    rain_proxy_base_runoff_coeff: float = 0.25,
    execution_profile: str = "default",
    memory_budget_gb: float = 0.0,
    max_points_per_shard: int = 0,
    min_points_per_shard: int = 512,
    max_shard_retry_depth: int = 4,
    strict_required_components: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
    resume_enabled: bool = False,
) -> ClimadaRunResult:
    runtime = _require_runtime()
    np = runtime["np"]
    ImpactCalc = runtime["ImpactCalc"]
    ImpactFuncSet = runtime["ImpactFuncSet"]

    vulnerability_payload = get_tc_vulnerability_payload(
        asset_type_to_curve_code=wind_asset_type_to_curve_code,
    )
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise DependencyMissingError("Unable to instantiate CLIMADA impact functions for tropical cyclone.")
    impfset_wind = ImpactFuncSet(impact_funcs)

    notes = [
        "Direct damages are computed with CLIMADA ImpactCalc on STORM and STORM_CMCC hazards.",
        "Hazard frequencies are normalized by the synthetic catalog length before annualized metrics are reported.",
        f"Impact functions: profile={vulnerability_payload.get('profile')} with {len(impact_funcs)} TC curves.",
    ]
    execution_profile_name = str(execution_profile or "default").strip().lower()
    sharding_enabled = bool(max_points_per_shard > 0 or memory_budget_gb > 0.0)
    if execution_profile_name != "default":
        notes.append(f"Execution profile: {execution_profile_name}.")
    if sharding_enabled:
        if max_points_per_shard > 0:
            notes.append(f"Impact execution uses exposure shards capped at {int(max_points_per_shard)} points per shard.")
        else:
            notes.append(f"Impact execution uses exposure shards derived from an approximate memory budget of {float(memory_budget_gb):.2f} GiB per component.")
    if strict_required_components:
        notes.append("Eligible multi-hazard components run in strict mode: failures stop the complete-analysis territory run.")
    if checkpoint_dir is not None:
        notes.append(f"Shard checkpoints directory: {Path(checkpoint_dir)}.")
    if resume_enabled:
        notes.append("Resume mode enabled: completed shards are reused from on-disk checkpoints when available.")

    bundle = None
    dynamic_hazard_shards: list[_ExposureShard] = []
    dynamic_hazard_point_cap = 0
    dynamic_hazard_estimated_full_memory_bytes = 0
    if (
        prefer_dynamic_hazards
        and storm_parquet_path is not None
        and storm_cmcc_parquet_path is not None
    ):
        point_coords = [
            (float(rec.get("lat")), float(rec.get("lon")))
            for rec in list(exposure_bundle.point_records or [])
            if rec.get("lat") is not None and rec.get("lon") is not None
        ]
        if point_coords:
            try:
                bundle = load_storm_hazards_from_parquet_for_points(
                    storm_parquet_path=storm_parquet_path,
                    cmcc_parquet_path=storm_cmcc_parquet_path,
                    point_coords=point_coords,
                    storm_years=storm_years,
                    basin_coverages=basin_coverages,
                    wind_unit_in=wind_unit_in,
                    radius_unit_in=radius_unit_in,
                    env_pressure_hpa=env_pressure_hpa,
                    max_tracks=max(100, int(dynamic_max_tracks)),
                    track_cache_max_entries=track_cache_max_entries,
                    build_hazards=False,
                )
                dynamic_hazard_event_count = max(
                    int(bundle.track_count_storm or 0),
                    int(bundle.track_count_storm_cmcc or 0),
                )
                dynamic_hazard_estimated_full_memory_bytes = _estimate_dynamic_hazard_memory_bytes(
                    event_count=dynamic_hazard_event_count,
                    point_count=len(point_coords),
                )
                if _dynamic_hazard_budget_exceeded_at_min_shard(
                    event_count=dynamic_hazard_event_count,
                    memory_budget_gb=float(memory_budget_gb),
                    min_points_per_shard=1,
                ):
                    raise RuntimeError(
                        "Dynamic hazard construction exceeds the configured memory budget even for a single centroid shard. "
                        f"tracks={dynamic_hazard_event_count}, memory_budget_gb={float(memory_budget_gb):.2f}"
                    )

                dynamic_hazard_budget_cap = _resolve_dynamic_hazard_point_cap(
                    total_points=len(point_coords),
                    event_count=dynamic_hazard_event_count,
                    memory_budget_gb=float(memory_budget_gb),
                    max_points_per_shard=0,
                    min_points_per_shard=1,
                )
                if int(max_points_per_shard) > 0:
                    dynamic_hazard_point_cap = max(1, min(int(max_points_per_shard), int(dynamic_hazard_budget_cap)))
                else:
                    dynamic_hazard_point_cap = max(1, int(dynamic_hazard_budget_cap))

                dynamic_hazard_shards = _plan_hazard_shards(
                    list(exposure_bundle.point_records or []),
                    max_points_per_shard=max(1, int(dynamic_hazard_point_cap)),
                )
                if len(dynamic_hazard_shards) <= 1:
                    centroids = _build_centroids_from_points(point_coords)
                    bundle.centroids = centroids
                    bundle.storm = _normalize_frequency_on_copy(
                        _build_hazard_from_tracks(bundle.tracks_storm, centroids),
                        storm_years,
                    )
                    bundle.storm_cmcc = _normalize_frequency_on_copy(
                        _build_hazard_from_tracks(bundle.tracks_storm_cmcc, centroids),
                        storm_years,
                    )
                    bundle.global_hazards_built = True
                notes.append(
                    "Hazard source: dynamic STORM/STORM_CMCC parquet "
                    f"(basin_id={list(bundle.basin_ids) or ['n/a']}, points={bundle.point_count}, "
                    f"tracks={int(bundle.track_count_storm or 0)}/{int(bundle.track_count_storm_cmcc or 0)})."
                )
                if len(dynamic_hazard_shards) > 1:
                    notes.append(
                        "Dynamic hazard construction uses centroid sharding before ImpactCalc "
                        f"({len(dynamic_hazard_shards)} shards, cap={int(max(1, dynamic_hazard_point_cap))} points per shard, "
                        f"estimated full build={float(dynamic_hazard_estimated_full_memory_bytes) / float(1024**3):.2f} GiB)."
                    )
            except Exception as exc:
                if not fallback_to_precomputed_hazards:
                    raise
                logger.warning(
                    "Dynamic hazard build failed; falling back to precomputed HDF5 (%s: %s)",
                    type(exc).__name__,
                    exc,
                )
                notes.append(
                    f"Dynamic hazard build failed ({type(exc).__name__}): {exc}. Falling back to precomputed HDF5 hazards."
                )

    if bundle is None:
        bundle = load_storm_hazards(hazard_storm_path, hazard_storm_cmcc_path, storm_years)
        notes.append(
            f"Hazard source: precomputed HDF5 ({hazard_storm_path.name}, {hazard_storm_cmcc_path.name})."
        )

    hazards_wind = {"storm": bundle.storm, "storm_cmcc": bundle.storm_cmcc}
    point_values_eur = [max(0.0, float(rec.get("value_eur", 0.0))) for rec in list(exposure_bundle.point_records or [])]

    requested_rain_model = _normalize_rain_model(rain_model)
    multi_hazard_model = None
    multi_hazard_ready = False
    impfset_rain = None
    impfset_surge = None
    TCRain = None
    TCSurgeBathtub = None

    if bool(multi_hazard_enabled):
        if flood_curve_file is None:
            notes.append("Multi-hazard disabled: no flood depth curve file configured.")
        elif not Path(flood_curve_file).exists():
            notes.append(f"Multi-hazard disabled: missing flood depth curve file at {flood_curve_file}.")
        else:
            try:
                from climada_petals.hazard.tc_rainfield import TCRain as _TCRain  # type: ignore
                from climada_petals.hazard.tc_surge_bathtub import TCSurgeBathtub as _TCSurgeBathtub  # type: ignore

                multi_hazard_model = build_multi_hazard_impact_model(
                    surge_haz_type="TCSurgeBathtub",
                    rain_haz_type="TR",
                    flood_curve_file=Path(flood_curve_file),
                    asset_type_to_curve_code=flood_asset_type_to_curve_code,
                    rain_proxy_base_runoff_coeff=rain_proxy_base_runoff_coeff,
                )
                impfset_rain = ImpactFuncSet(multi_hazard_model.rain_funcs)
                impfset_surge = ImpactFuncSet(multi_hazard_model.surge_funcs)
                TCRain = _TCRain
                TCSurgeBathtub = _TCSurgeBathtub
                multi_hazard_ready = True
                notes.append(
                    "Multi-hazard V1 enabled: wind (TC) + rain proxy (TCRain) + coastal surge (TCSurgeBathtub)."
                )
            except Exception as exc:
                logger.warning(
                    "Multi-hazard setup failed; running wind-only mode (%s: %s)",
                    type(exc).__name__,
                    exc,
                )
                notes.append(f"Multi-hazard setup failed ({type(exc).__name__}): {exc}. Using wind-only impacts.")

    out: dict[str, HazardImpactResult] = {}
    component_out: dict[str, dict[str, HazardImpactResult]] = {}
    hazard_zero_intensity: dict[str, bool] = {}
    components_by_hazard: dict[str, list[str]] = {}
    component_status_by_hazard: dict[str, dict[str, str]] = {}
    component_sharding_by_hazard: dict[str, dict[str, dict[str, Any]]] = {}
    dynamic_hazard_sharding_active = bool(
        str(getattr(bundle, "source", "") or "") == "dynamic_parquet"
        and not bool(getattr(bundle, "global_hazards_built", True))
        and bool(dynamic_hazard_shards)
    )

    for hazard_key in ("storm", "storm_cmcc"):
        if dynamic_hazard_sharding_active:
            tracks = bundle.tracks_storm if hazard_key == "storm" else bundle.tracks_storm_cmcc
            total_metrics, components, component_status, component_sharding, hazard_notes = _compute_dynamic_hazard_sharded_results(
                np,
                ImpactCalc,
                exposure_bundle=exposure_bundle,
                tracks=tracks,
                hazard_key=hazard_key,
                storm_years=storm_years,
                top_n_events=top_n_events,
                hazard_shards=dynamic_hazard_shards,
                hazard_point_cap=max(1, int(dynamic_hazard_point_cap or len(exposure_bundle.point_records or []))),
                impfset_wind=impfset_wind,
                requested_rain_model=requested_rain_model,
                rain_max_dist_inland_km=float(rain_max_dist_inland_km),
                multi_hazard_ready=multi_hazard_ready,
                multi_hazard_model=multi_hazard_model,
                impfset_rain=impfset_rain,
                impfset_surge=impfset_surge,
                TCRain=TCRain,
                TCSurgeBathtub=TCSurgeBathtub,
                surge_topo_path=surge_topo_path,
                memory_budget_gb=float(memory_budget_gb),
                max_points_per_shard=int(max_points_per_shard),
                min_points_per_shard=int(min_points_per_shard),
                max_shard_retry_depth=int(max_shard_retry_depth),
                strict_required_components=bool(strict_required_components),
                progress_callback=progress_callback,
                checkpoint_dir=checkpoint_dir,
                resume_enabled=resume_enabled,
            )
            notes.extend(hazard_notes)
            out[hazard_key] = total_metrics
            component_out[hazard_key] = components
            components_by_hazard[hazard_key] = [name for name in ("wind", "rain", "surge") if name in components]
            component_status_by_hazard[hazard_key] = component_status
            component_sharding_by_hazard[hazard_key] = component_sharding
            hazard_zero_intensity[hazard_key] = bool(
                float(total_metrics.max_event_loss_eur) <= 0.0 and float(sum(total_metrics.eai_direct_by_point)) <= 0.0
            )
            if hazard_zero_intensity[hazard_key]:
                notes.append(f"Warning: hazard '{hazard_key}' has zero combined intensity values; computed impacts can be null.")
            continue

        wind_hazard = hazards_wind.get(hazard_key)
        components: dict[str, HazardImpactResult] = {}
        component_status: dict[str, str] = {}
        component_sharding: dict[str, dict[str, Any]] = {}

        try:
            wind_metrics, wind_sharding = _compute_component_impact_sharded(
                np,
                ImpactCalc,
                exposure_bundle=exposure_bundle,
                exposure_builder=lambda shard_bundle: shard_bundle.exposures,
                impfset=impfset_wind,
                hazard_obj=wind_hazard,
                top_n_events=top_n_events,
                component_name="wind",
                memory_budget_gb=float(memory_budget_gb),
                max_points_per_shard=int(max_points_per_shard),
                min_points_per_shard=int(min_points_per_shard),
                max_shard_retry_depth=int(max_shard_retry_depth),
                progress_callback=progress_callback,
                hazard_key=hazard_key,
                checkpoint_dir=checkpoint_dir,
                resume_enabled=resume_enabled,
            )
            components["wind"] = wind_metrics
            component_status["wind"] = "complete"
            component_sharding["wind"] = wind_sharding
        except Exception as exc:
            _emit_progress(
                progress_callback,
                {
                    "event": "component_failed",
                    "hazard": hazard_key,
                    "component": "wind",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise

        if multi_hazard_ready and multi_hazard_model is not None and impfset_surge is not None and TCSurgeBathtub is not None:
            if surge_topo_path is None:
                component_status["surge"] = "skipped"
                component_sharding["surge"] = {"status": "skipped", "reason": "missing_topo_path"}
                notes.append(f"{hazard_key}: surge component skipped (no DEM path configured).")
            elif not Path(surge_topo_path).exists():
                component_status["surge"] = "skipped"
                component_sharding["surge"] = {"status": "skipped", "reason": f"missing_topo:{surge_topo_path}"}
                notes.append(f"{hazard_key}: surge component skipped (DEM not found at {surge_topo_path}).")
            else:
                try:
                    prepared_topo = _prepare_topo_raster_for_exposure(
                        Path(surge_topo_path),
                        point_records=list(exposure_bundle.point_records or []),
                    )
                    if prepared_topo != Path(surge_topo_path):
                        notes.append(
                            f"{hazard_key}: prepared cropped DEM for surge hazard at {prepared_topo}."
                        )
                    surge_hazard, surge_meta = _build_surge_hazard(
                        np,
                        surge_hazard_cls=TCSurgeBathtub,
                        wind_hazard=wind_hazard,
                        topo_path=prepared_topo,
                        hazard_source=getattr(bundle, "source", None),
                    )
                    if str(surge_meta.get("fraction_mode") or "") == "pointwise":
                        rows = surge_meta.get("rows")
                        cols = surge_meta.get("cols")
                        grid_desc = f" estimated fraction grid {rows}x{cols}" if rows and cols else ""
                        notes.append(
                            f"{hazard_key}: surge used pointwise land fractions for exposure-aligned centroids ({surge_meta.get('reason')}).{grid_desc}"
                        )
                    surge_hazard = _normalize_frequency_on_copy(surge_hazard, storm_years)
                    surge_metrics, surge_sharding = _compute_component_impact_sharded(
                        np,
                        ImpactCalc,
                        exposure_bundle=exposure_bundle,
                        exposure_builder=lambda shard_bundle: _build_exposure_with_impf_column(
                            shard_bundle.exposures,
                            haz_type=multi_hazard_model.surge_haz_type,
                            impf_ids=[
                                resolve_surge_impf_id(rec.get("asset_type"), multi_hazard_model)
                                for rec in list(shard_bundle.point_records or [])
                            ],
                        ),
                        impfset=impfset_surge,
                        hazard_obj=surge_hazard,
                        top_n_events=top_n_events,
                        component_name="surge",
                        memory_budget_gb=float(memory_budget_gb),
                        max_points_per_shard=int(max_points_per_shard),
                        min_points_per_shard=int(min_points_per_shard),
                        max_shard_retry_depth=int(max_shard_retry_depth),
                        progress_callback=progress_callback,
                        hazard_key=hazard_key,
                        checkpoint_dir=checkpoint_dir,
                        resume_enabled=resume_enabled,
                    )
                    components["surge"] = surge_metrics
                    component_status["surge"] = "complete"
                    component_sharding["surge"] = surge_sharding
                except Exception as exc:
                    component_status["surge"] = "failed"
                    component_sharding["surge"] = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "component_failed",
                            "hazard": hazard_key,
                            "component": "surge",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    logger.warning(
                        "%s surge component failed (%s: %s)",
                        hazard_key,
                        type(exc).__name__,
                        exc,
                    )
                    notes.append(f"{hazard_key}: surge component failed ({type(exc).__name__}): {exc}")
                    if strict_required_components:
                        raise RuntimeError(
                            f"{hazard_key} surge component failed under strict mode: {type(exc).__name__}: {exc}"
                        ) from exc

        if multi_hazard_ready and multi_hazard_model is not None and impfset_rain is not None and TCRain is not None:
            tracks = bundle.tracks_storm if hazard_key == "storm" else bundle.tracks_storm_cmcc
            if tracks is None:
                component_status["rain"] = "skipped"
                component_sharding["rain"] = {"status": "skipped", "reason": "dynamic_tracks_unavailable"}
                notes.append(
                    f"{hazard_key}: rain component skipped because dynamic tracks are unavailable (precomputed HDF5 source)."
                )
            else:
                try:
                    rain_hazard = TCRain.from_tracks(
                        tracks,
                        centroids=wind_hazard.centroids,
                        model=requested_rain_model,
                        ignore_distance_to_coast=True,
                        max_dist_inland_km=float(rain_max_dist_inland_km),
                    )
                    rain_hazard = _normalize_frequency_on_copy(rain_hazard, storm_years)
                    rain_metrics, rain_sharding = _compute_component_impact_sharded(
                        np,
                        ImpactCalc,
                        exposure_bundle=exposure_bundle,
                        exposure_builder=lambda shard_bundle: _build_exposure_with_impf_column(
                            shard_bundle.exposures,
                            haz_type=multi_hazard_model.rain_haz_type,
                            impf_ids=[
                                resolve_rain_impf_id(rec.get("asset_type"), multi_hazard_model)
                                for rec in list(shard_bundle.point_records or [])
                            ],
                        ),
                        impfset=impfset_rain,
                        hazard_obj=rain_hazard,
                        top_n_events=top_n_events,
                        component_name="rain",
                        memory_budget_gb=float(memory_budget_gb),
                        max_points_per_shard=int(max_points_per_shard),
                        min_points_per_shard=int(min_points_per_shard),
                        max_shard_retry_depth=int(max_shard_retry_depth),
                        progress_callback=progress_callback,
                        hazard_key=hazard_key,
                        checkpoint_dir=checkpoint_dir,
                        resume_enabled=resume_enabled,
                    )
                    components["rain"] = rain_metrics
                    component_status["rain"] = "complete"
                    component_sharding["rain"] = rain_sharding
                except Exception as exc:
                    component_status["rain"] = "failed"
                    component_sharding["rain"] = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "component_failed",
                            "hazard": hazard_key,
                            "component": "rain",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    logger.warning(
                        "%s rain component failed (%s: %s)",
                        hazard_key,
                        type(exc).__name__,
                        exc,
                    )
                    notes.append(f"{hazard_key}: rain component failed ({type(exc).__name__}): {exc}")
                    if strict_required_components:
                        raise RuntimeError(
                            f"{hazard_key} rain component failed under strict mode: {type(exc).__name__}: {exc}"
                        ) from exc

        component_list = [components[name] for name in ("wind", "rain", "surge") if name in components]
        total_metrics = _combine_component_results(
            np,
            components=component_list,
            point_values_eur=point_values_eur,
            top_n_events=top_n_events,
        )
        total_metrics.matching = _build_combined_matching_summary(
            np,
            hazard_key=hazard_key,
            point_records=list(exposure_bundle.point_records or []),
            total_metrics=total_metrics,
            component_metrics=components,
            hazard_zero_intensity=bool(
                float(total_metrics.max_event_loss_eur) <= 0.0 and float(sum(total_metrics.eai_direct_by_point)) <= 0.0
            ),
        )

        out[hazard_key] = total_metrics
        component_out[hazard_key] = components
        components_by_hazard[hazard_key] = [name for name in ("wind", "rain", "surge") if name in components]
        component_status_by_hazard[hazard_key] = component_status
        component_sharding_by_hazard[hazard_key] = component_sharding
        hazard_zero_intensity[hazard_key] = bool(
            float(total_metrics.max_event_loss_eur) <= 0.0 and float(sum(total_metrics.eai_direct_by_point)) <= 0.0
        )
        if hazard_zero_intensity[hazard_key]:
            notes.append(f"Warning: hazard '{hazard_key}' has zero combined intensity values; computed impacts can be null.")

    effective_multi_hazard = any(
        any(name in {"rain", "surge"} for name in names)
        for names in components_by_hazard.values()
    )

    matching_qa = {
        "status": "complete",
        "point_count": int(len(exposure_bundle.point_records or [])),
        "point_value_total_eur": round(sum(point_values_eur), 2),
        "assignment_threshold_deg": float(CENTROID_ASSIGNMENT_THRESHOLD_DEG),
        "hazards": {},
    }
    for hazard_key in ("storm", "storm_cmcc"):
        if hazard_key not in out:
            continue
        matching_qa["hazards"][hazard_key] = {
            "combined": dict(getattr(out[hazard_key], "matching", {}) or {}),
            "components": {
                component_name: dict(getattr(component_metrics, "matching", {}) or {})
                for component_name, component_metrics in (component_out.get(hazard_key) or {}).items()
            },
        }

    modeling = {
        "storm_years": int(storm_years),
        "execution_profile": execution_profile_name,
        "strict_required_components": bool(strict_required_components),
        "sharding_enabled": bool(sharding_enabled),
        "sharding_memory_budget_gb": round(float(memory_budget_gb), 3),
        "sharding_max_points_per_shard_requested": int(max_points_per_shard),
        "sharding_min_points_per_shard": int(min_points_per_shard),
        "sharding_max_retry_depth": int(max_shard_retry_depth),
        "sharding_checkpoint_dir": str(checkpoint_dir) if checkpoint_dir else None,
        "resume_enabled": bool(resume_enabled),
        "frequency_normalized": bool(bundle.normalized_on_copy),
        "top_events_count": int(top_n_events),
        "hazard_zero_intensity": hazard_zero_intensity,
        "hazard_source": str(bundle.source),
        "hazard_basin_ids": [int(v) for v in list(bundle.basin_ids or [])],
        "hazard_point_count": int(bundle.point_count or 0),
        "hazard_track_count_storm": int(getattr(bundle, "track_count_storm", 0) or 0),
        "hazard_track_count_storm_cmcc": int(getattr(bundle, "track_count_storm_cmcc", 0) or 0),
        "hazard_global_hazards_built": bool(getattr(bundle, "global_hazards_built", True)),
        "hazard_build_sharded": bool(dynamic_hazard_sharding_active),
        "hazard_build_planned_shards": int(len(dynamic_hazard_shards)),
        "hazard_build_max_points_per_shard": int(dynamic_hazard_point_cap or 0),
        "hazard_build_estimated_full_memory_gb": round(
            float(dynamic_hazard_estimated_full_memory_bytes) / float(1024**3),
            3,
        ),
        "impact_function_profile": str(vulnerability_payload.get("profile") or "unknown"),
        "impact_function_default_curve": vulnerability_payload.get("default_curve"),
        "impact_function_mapping": vulnerability_payload.get("explicit_asset_type_mapping") or {},
        "multi_hazard_enabled_requested": bool(multi_hazard_enabled),
        "multi_hazard_enabled_effective": bool(effective_multi_hazard),
        "multi_hazard_components_by_hazard": components_by_hazard,
        "multi_hazard_component_status_by_hazard": component_status_by_hazard,
        "climada_component_sharding": component_sharding_by_hazard,
        "multi_hazard_rain_model": requested_rain_model,
        "multi_hazard_surge_topo_path": str(surge_topo_path) if surge_topo_path else None,
        "multi_hazard_flood_curve_file": str(flood_curve_file) if flood_curve_file else None,
        "hazard_exposure_matching_qa": matching_qa,
    }
    if multi_hazard_model is not None:
        modeling["multi_hazard_impact_mapping"] = multi_hazard_model.mapping_info

    return ClimadaRunResult(
        hazards=out,
        component_hazards=component_out,
        modeling=modeling,
        notes=notes,
    )
