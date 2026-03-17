from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DependencyMissingError
from .exposure_to_climada import ClimadaExposureBundle
from .hazard_loader import (
    DEFAULT_BASIN_COVERAGES,
    BasinCoverage,
    load_storm_hazards,
    load_storm_hazards_from_parquet_for_points,
)
from .impact_functions import get_tc_vulnerability_payload, try_build_climada_impact_funcs


RETURN_PERIODS = (10, 20, 50, 100, 200)


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
    modeling: dict[str, Any]
    notes: list[str]


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
) -> ClimadaRunResult:
    runtime = _require_runtime()
    np = runtime["np"]
    ImpactCalc = runtime["ImpactCalc"]
    ImpactFuncSet = runtime["ImpactFuncSet"]

    vulnerability_payload = get_tc_vulnerability_payload()
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise DependencyMissingError("Unable to instantiate CLIMADA impact functions for tropical cyclone.")
    impfset = ImpactFuncSet(impact_funcs)

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

    hazards = {"storm": bundle.storm, "storm_cmcc": bundle.storm_cmcc}

    out: dict[str, HazardImpactResult] = {}
    hazard_zero_intensity: dict[str, bool] = {}
    for hazard_key, hazard_obj in hazards.items():
        try:
            intensity_max = float(hazard_obj.intensity.max())
        except Exception:
            intensity_max = 0.0
        hazard_zero_intensity[hazard_key] = intensity_max <= 0.0
        if hazard_zero_intensity[hazard_key]:
            notes.append(f"Warning: hazard '{hazard_key}' has zero intensity values; computed impacts can be null.")

        # Explicit centroid assignment avoids CLIMADA auto-threshold estimation
        # failures when the dynamic hazard has very few centroids (e.g. 1 point).
        exposure_bundle.exposures.assign_centroids(
            hazard_obj,
            distance="euclidean",
            threshold=5.0,
            overwrite=True,
        )
        impact = ImpactCalc(exposure_bundle.exposures, impfset, hazard_obj).impact(
            save_mat=False,
            assign_centroids=False,
        )
        eai_exp = _as_1d_float(np, getattr(impact, "eai_exp", []))
        at_event = _as_1d_float(np, getattr(impact, "at_event", []))
        max_loss_point = _approx_max_loss_per_point(np, eai_exp, at_event)
        frequency = _as_1d_float(np, getattr(impact, "frequency", []))

        out[hazard_key] = HazardImpactResult(
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
    }

    return ClimadaRunResult(hazards=out, modeling=modeling, notes=notes)
