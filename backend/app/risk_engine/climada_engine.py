from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import copy
import hashlib

from .errors import DependencyMissingError
from .exposure_to_climada import ClimadaExposureBundle
from .hazard_loader import (
    DEFAULT_BASIN_COVERAGES,
    BasinCoverage,
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
        threshold=5.0,
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
    multi_hazard_enabled: bool = True,
    rain_model: str = "R-CLIPER",
    surge_topo_path: Path | None = None,
    flood_curve_file: Path | None = None,
) -> ClimadaRunResult:
    runtime = _require_runtime()
    np = runtime["np"]
    ImpactCalc = runtime["ImpactCalc"]
    ImpactFuncSet = runtime["ImpactFuncSet"]

    vulnerability_payload = get_tc_vulnerability_payload()
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise DependencyMissingError("Unable to instantiate CLIMADA impact functions for tropical cyclone.")
    impfset_wind = ImpactFuncSet(impact_funcs)

    notes = [
        "Direct damages are computed with CLIMADA ImpactCalc on STORM and STORM_CMCC hazards.",
        "Hazard frequencies are normalized by the synthetic catalog length before annualized metrics are reported.",
        f"Impact functions: profile={vulnerability_payload.get('profile')} with {len(impact_funcs)} TC curves.",
    ]

    bundle = None
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
                )
                notes.append(
                    f"Hazard source: dynamic STORM/STORM_CMCC parquet (basin_id={list(bundle.basin_ids) or ['n/a']}, points={bundle.point_count})."
                )
            except Exception as exc:
                if not fallback_to_precomputed_hazards:
                    raise
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
                notes.append(f"Multi-hazard setup failed ({type(exc).__name__}): {exc}. Using wind-only impacts.")

    out: dict[str, HazardImpactResult] = {}
    component_out: dict[str, dict[str, HazardImpactResult]] = {}
    hazard_zero_intensity: dict[str, bool] = {}
    components_by_hazard: dict[str, list[str]] = {}

    for hazard_key, wind_hazard in hazards_wind.items():
        components: dict[str, HazardImpactResult] = {}

        wind_metrics = _compute_component_impact(
            np,
            ImpactCalc,
            exposures=exposure_bundle.exposures,
            impfset=impfset_wind,
            hazard_obj=wind_hazard,
            top_n_events=top_n_events,
        )
        components["wind"] = wind_metrics

        if multi_hazard_ready and multi_hazard_model is not None and impfset_surge is not None and TCSurgeBathtub is not None:
            if surge_topo_path is None:
                notes.append(f"{hazard_key}: surge component skipped (no DEM path configured).")
            elif not Path(surge_topo_path).exists():
                notes.append(f"{hazard_key}: surge component skipped (DEM not found at {surge_topo_path}).")
            else:
                try:
                    prepared_topo = _prepare_topo_raster_with_crs(Path(surge_topo_path))
                    if prepared_topo != Path(surge_topo_path):
                        notes.append(
                            f"{hazard_key}: DEM had no CRS; converted to temporary EPSG:4326 GeoTIFF ({prepared_topo})."
                        )
                    surge_hazard = TCSurgeBathtub.from_tc_winds(wind_hazard, str(prepared_topo))
                    surge_hazard = _normalize_frequency_on_copy(surge_hazard, storm_years)
                    surge_ids = [
                        resolve_surge_impf_id(rec.get("asset_type"), multi_hazard_model)
                        for rec in list(exposure_bundle.point_records or [])
                    ]
                    surge_exposure = _build_exposure_with_impf_column(
                        exposure_bundle.exposures,
                        haz_type=multi_hazard_model.surge_haz_type,
                        impf_ids=surge_ids,
                    )
                    components["surge"] = _compute_component_impact(
                        np,
                        ImpactCalc,
                        exposures=surge_exposure,
                        impfset=impfset_surge,
                        hazard_obj=surge_hazard,
                        top_n_events=top_n_events,
                    )
                except Exception as exc:
                    notes.append(f"{hazard_key}: surge component failed ({type(exc).__name__}): {exc}")

        if multi_hazard_ready and multi_hazard_model is not None and impfset_rain is not None and TCRain is not None:
            tracks = bundle.tracks_storm if hazard_key == "storm" else bundle.tracks_storm_cmcc
            if tracks is None:
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
                        max_dist_inland_km=2000,
                    )
                    rain_hazard = _normalize_frequency_on_copy(rain_hazard, storm_years)
                    rain_ids = [
                        resolve_rain_impf_id(rec.get("asset_type"), multi_hazard_model)
                        for rec in list(exposure_bundle.point_records or [])
                    ]
                    rain_exposure = _build_exposure_with_impf_column(
                        exposure_bundle.exposures,
                        haz_type=multi_hazard_model.rain_haz_type,
                        impf_ids=rain_ids,
                    )
                    components["rain"] = _compute_component_impact(
                        np,
                        ImpactCalc,
                        exposures=rain_exposure,
                        impfset=impfset_rain,
                        hazard_obj=rain_hazard,
                        top_n_events=top_n_events,
                    )
                except Exception as exc:
                    notes.append(f"{hazard_key}: rain component failed ({type(exc).__name__}): {exc}")

        component_list = [components[name] for name in ("wind", "rain", "surge") if name in components]
        total_metrics = _combine_component_results(
            np,
            components=component_list,
            point_values_eur=point_values_eur,
            top_n_events=top_n_events,
        )

        out[hazard_key] = total_metrics
        component_out[hazard_key] = components
        components_by_hazard[hazard_key] = [name for name in ("wind", "rain", "surge") if name in components]
        hazard_zero_intensity[hazard_key] = bool(
            float(total_metrics.max_event_loss_eur) <= 0.0 and float(sum(total_metrics.eai_direct_by_point)) <= 0.0
        )
        if hazard_zero_intensity[hazard_key]:
            notes.append(f"Warning: hazard '{hazard_key}' has zero combined intensity values; computed impacts can be null.")

    effective_multi_hazard = any(
        any(name in {"rain", "surge"} for name in names)
        for names in components_by_hazard.values()
    )

    modeling = {
        "storm_years": int(storm_years),
        "frequency_normalized": bool(bundle.normalized_on_copy),
        "top_events_count": int(top_n_events),
        "hazard_zero_intensity": hazard_zero_intensity,
        "hazard_source": str(bundle.source),
        "hazard_basin_ids": [int(v) for v in list(bundle.basin_ids or [])],
        "hazard_point_count": int(bundle.point_count or 0),
        "impact_function_profile": str(vulnerability_payload.get("profile") or "unknown"),
        "impact_function_default_curve": vulnerability_payload.get("default_curve"),
        "impact_function_mapping": vulnerability_payload.get("explicit_asset_type_mapping") or {},
        "multi_hazard_enabled_requested": bool(multi_hazard_enabled),
        "multi_hazard_enabled_effective": bool(effective_multi_hazard),
        "multi_hazard_components_by_hazard": components_by_hazard,
        "multi_hazard_rain_model": requested_rain_model,
        "multi_hazard_surge_topo_path": str(surge_topo_path) if surge_topo_path else None,
        "multi_hazard_flood_curve_file": str(flood_curve_file) if flood_curve_file else None,
    }
    if multi_hazard_model is not None:
        modeling["multi_hazard_impact_mapping"] = multi_hazard_model.mapping_info

    return ClimadaRunResult(
        hazards=out,
        component_hazards=component_out,
        modeling=modeling,
        notes=notes,
    )
