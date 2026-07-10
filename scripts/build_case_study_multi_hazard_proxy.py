#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
from typing import Any

import numpy as np


UTC = timezone.utc
logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings, resolve_surge_topo_path_for_territory  # noqa: E402
from app.risk_engine.climada_engine import _prepare_topo_raster_with_crs, run_climada_direct_impacts  # noqa: E402
from app.risk_engine.exposure_to_climada import build_climada_exposure  # noqa: E402
from app.risk_engine.hazard_loader import load_storm_hazards_from_parquet_for_points  # noqa: E402
from app.risk_engine.impact_functions import resolve_tc_impact_func_id  # noqa: E402
from app.risk_engine.impact_functions_multi_hazard import get_multi_hazard_vulnerability_payload  # noqa: E402
from app.risk_engine.impact_functions_landslide import LANDSLIDE_HYPOTHESIS_CURVE, LANDSLIDE_INTENSITIES  # noqa: E402
from app.risk_engine.landslide_engine import scenario_loss_factors  # noqa: E402
from build_guadeloupe_page1_data import (  # noqa: E402
    _loss_at_return_period,
    _sample_raster_values_for_point_records,
    _simulate_landslide_portfolio_yearly_losses,
)
from case_study_sources import get_case_study, parse_territory, territory_label  # noqa: E402

try:
    from climada_petals.hazard.tc_surge_bathtub import TCSurgeBathtub  # type: ignore
except Exception:  # pragma: no cover - surfaced through empty fallback at runtime
    TCSurgeBathtub = None


DAMAGE_BREAKDOWN_LABELS: dict[str, str] = {}
MAP_SCENARIOS = ("annual", "rp10", "rp50", "rp100", "rp1000", "event_max", "top10", "top5")
_HELPERS_LOADED = False
PROXY_CLIMADA_MEMORY_BUDGET_GB = 0.75
PROXY_CLIMADA_MAX_POINTS_PER_SHARD = 64
PROXY_CLIMADA_MIN_POINTS_PER_SHARD = 32


def _proxy_progress_callback(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    event = str(payload.get("event") or "").strip().lower()
    hazard = str(payload.get("hazard") or "?")
    component = str(payload.get("component") or "?")
    if event == "component_plan":
        print(
            "[progress] "
            f"{hazard}.{component}: planned_shards={int(payload.get('planned_shards') or 0)} "
            f"max_points_per_shard={int(payload.get('max_points_per_shard') or 0)} "
            f"estimated_full_memory_gb={float(payload.get('estimated_full_memory_gb') or 0.0):.3f}",
            flush=True,
        )
        return
    if event == "shard_start":
        print(
            "[progress] "
            f"{hazard}.{component}: shard_start="
            f"{int(payload.get('completed_shards') or 0) + 1}/{int(payload.get('planned_shards') or 0)} "
            f"points={int(payload.get('point_count') or 0)} "
            f"retry_depth={int(payload.get('retry_depth') or 0)}",
            flush=True,
        )
        return
    if event == "shard_complete":
        print(
            "[progress] "
            f"{hazard}.{component}: shard_complete="
            f"{int(payload.get('completed_shards') or 0)}/{int(payload.get('planned_shards') or 0)} "
            f"points={int(payload.get('point_count') or 0)}",
            flush=True,
        )
        return
    if event == "component_failed":
        print(
            f"[progress] {hazard}.{component}: failed={payload.get('error')}",
            flush=True,
        )


def _stable_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def _load_case_study_helpers() -> None:
    global DAMAGE_BREAKDOWN_LABELS, MAP_SCENARIOS, _HELPERS_LOADED
    global build_complete_exposure
    global _breakdown_class_from_point
    global _component_ratios_from_climada_run
    global _default_multi_hazard_proxy
    global _load_component_ratio_reference
    global _normalize_proxy_scenario_loss_totals
    global _normalize_breakdown_share_map
    global _normalize_component_ratio_map
    global _resolve_hazard_paths_for_case_study
    global _scenario_breakdown_shares_from_component_arrays
    global _subset_bundle_for_component_ratios
    if _HELPERS_LOADED:
        return
    from build_guadeloupe_complete_analysis import build_complete_exposure as _build_complete_exposure
    from case_study_proxy_utils import (
        DAMAGE_BREAKDOWN_LABELS as _DAMAGE_BREAKDOWN_LABELS,
        MAP_SCENARIOS as _MAP_SCENARIOS,
        _breakdown_class_from_point as _breakdown_class_from_point_impl,
        _component_ratios_from_climada_run as _component_ratios_from_climada_run_impl,
        _default_multi_hazard_proxy as _default_multi_hazard_proxy_impl,
        _load_component_ratio_reference as _load_component_ratio_reference_impl,
        _normalize_proxy_scenario_loss_totals as _normalize_proxy_scenario_loss_totals_impl,
        _normalize_breakdown_share_map as _normalize_breakdown_share_map_impl,
        _normalize_component_ratio_map as _normalize_component_ratio_map_impl,
        _resolve_hazard_paths_for_case_study as _resolve_hazard_paths_for_case_study_impl,
        _scenario_breakdown_shares_from_component_arrays as _scenario_breakdown_shares_from_component_arrays_impl,
        _subset_bundle_for_component_ratios as _subset_bundle_for_component_ratios_impl,
    )

    build_complete_exposure = _build_complete_exposure
    DAMAGE_BREAKDOWN_LABELS = _DAMAGE_BREAKDOWN_LABELS
    MAP_SCENARIOS = _MAP_SCENARIOS
    _breakdown_class_from_point = _breakdown_class_from_point_impl
    _component_ratios_from_climada_run = _component_ratios_from_climada_run_impl
    _default_multi_hazard_proxy = _default_multi_hazard_proxy_impl
    _load_component_ratio_reference = _load_component_ratio_reference_impl
    _normalize_proxy_scenario_loss_totals = _normalize_proxy_scenario_loss_totals_impl
    _normalize_breakdown_share_map = _normalize_breakdown_share_map_impl
    _normalize_component_ratio_map = _normalize_component_ratio_map_impl
    _resolve_hazard_paths_for_case_study = _resolve_hazard_paths_for_case_study_impl
    _scenario_breakdown_shares_from_component_arrays = _scenario_breakdown_shares_from_component_arrays_impl
    _subset_bundle_for_component_ratios = _subset_bundle_for_component_ratios_impl
    _HELPERS_LOADED = True


def _load_surge_priority_scores_from_map(
    hazard_map_json: Path | None,
    point_records: list[dict[str, Any]],
) -> dict[int, float]:
    if hazard_map_json is None or not hazard_map_json.exists() or not point_records:
        return {}

    try:
        payload = json.loads(hazard_map_json.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "Unable to parse hazard map JSON for surge priority (%s): %s",
            hazard_map_json,
            exc,
        )
        return {}

    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return {}
    bbox = meta.get("bbox")
    if not isinstance(bbox, dict):
        return {}

    try:
        lat_min = float(bbox.get("lat_min"))
        lon_min = float(bbox.get("lon_min"))
        cell_deg = float(meta.get("grid_cell_deg") or 0.0)
    except Exception as exc:
        logger.warning(
            "Invalid bbox/grid metadata in hazard map JSON for surge priority (%s): %s",
            hazard_map_json,
            exc,
        )
        return {}
    if not np.isfinite(lat_min) or not np.isfinite(lon_min) or not np.isfinite(cell_deg) or cell_deg <= 0.0:
        return {}

    surge_cells: dict[tuple[int, int], float] = {}
    for hazard_key in ("storm", "storm_cmcc"):
        hazard_payload = payload.get(hazard_key)
        cells = hazard_payload.get("cells") if isinstance(hazard_payload, dict) else None
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            try:
                i = int(cell.get("i"))
                j = int(cell.get("j"))
            except Exception:
                continue
            score = max(
                float(cell.get("mean_surge_m") or 0.0),
                float(cell.get("rp50_surge_m") or 0.0),
                float(cell.get("rp100_surge_m") or 0.0),
                float(cell.get("event_max_surge_m") or 0.0),
            )
            if not np.isfinite(score) or score <= 0.0:
                continue
            surge_cells[(i, j)] = max(float(surge_cells.get((i, j), 0.0)), float(score))

    if not surge_cells:
        return {}

    out: dict[int, float] = {}
    for idx, rec in enumerate(point_records):
        try:
            lat = float(rec.get("lat"))
            lon = float(rec.get("lon"))
        except Exception:
            continue
        if not np.isfinite(lat) or not np.isfinite(lon):
            continue
        i = int(np.floor((lat - lat_min) / cell_deg))
        j = int(np.floor((lon - lon_min) / cell_deg))
        score = float(surge_cells.get((i, j), 0.0))
        if score > 0.0:
            out[int(idx)] = score
    return out


def _load_surge_priority_scores_from_native_chain(
    point_records: list[dict[str, Any]],
    *,
    settings: Any,
    surge_topo_path: Path,
    dynamic_max_tracks: int,
) -> dict[int, float]:
    if TCSurgeBathtub is None or not point_records:
        return {}

    point_coords: list[tuple[float, float]] = []
    valid_indices: list[int] = []
    for idx, rec in enumerate(point_records):
        try:
            lat = float(rec.get("lat"))
            lon = float(rec.get("lon"))
        except Exception:
            continue
        if not np.isfinite(lat) or not np.isfinite(lon):
            continue
        point_coords.append((lat, lon))
        valid_indices.append(int(idx))

    if not point_coords:
        return {}

    try:
        bundle = load_storm_hazards_from_parquet_for_points(
            storm_parquet_path=Path(settings.storm_parquet_path),
            cmcc_parquet_path=Path(settings.storm_cmcc_parquet_path),
            point_coords=point_coords,
            storm_years=int(settings.storm_years),
            wind_unit_in=str(settings.storm_wind_unit_in),
            radius_unit_in=str(settings.storm_radius_unit_in),
            env_pressure_hpa=float(settings.storm_env_pressure_hpa),
            max_tracks=int(dynamic_max_tracks),
            track_cache_max_entries=int(getattr(settings, "hazard_track_cache_max_entries", 8)),
        )
        prepared_topo = _prepare_topo_raster_with_crs(Path(surge_topo_path))
    except Exception as exc:
        logger.warning(
            "Native surge priority scoring failed (%s: %s); continuing without native priority scores",
            type(exc).__name__,
            exc,
        )
        return {}

    score_by_idx: dict[int, float] = {}
    for wind_hazard in (bundle.storm, bundle.storm_cmcc):
        try:
            surge_hazard = TCSurgeBathtub.from_tc_winds(wind_hazard, str(prepared_topo))
        except Exception as exc:
            logger.warning(
                "TCSurgeBathtub.from_tc_winds failed during surge priority scoring (%s: %s)",
                type(exc).__name__,
                exc,
            )
            continue
        max_raw = surge_hazard.intensity.max(axis=0)
        if hasattr(max_raw, "toarray"):
            max_by_point = np.asarray(max_raw.toarray()).reshape(-1)
        else:
            max_by_point = np.asarray(max_raw).reshape(-1)
        max_by_point = np.nan_to_num(max_by_point, nan=0.0, posinf=0.0, neginf=0.0)
        for raw_idx, score in zip(valid_indices, max_by_point.tolist()):
            score_f = float(score)
            if not np.isfinite(score_f) or score_f <= 0.0:
                continue
            score_by_idx[int(raw_idx)] = max(float(score_by_idx.get(int(raw_idx), 0.0)), score_f)
    return score_by_idx


def _derive_landslide_bbox(
    point_records: list[dict[str, Any]],
    *,
    fallback_bbox: tuple[float, float, float, float],
    padding_deg: float,
) -> tuple[float, float, float, float]:
    lats: list[float] = []
    lons: list[float] = []
    for rec in point_records:
        try:
            lat = float(rec.get("lat"))
            lon = float(rec.get("lon"))
        except Exception:
            continue
        if not np.isfinite(lat) or not np.isfinite(lon):
            continue
        lats.append(lat)
        lons.append(lon)

    if not lats or not lons:
        return fallback_bbox

    pad = max(float(padding_deg), 1e-4)
    lon_min = max(float(fallback_bbox[0]), min(lons) - pad)
    lat_min = max(float(fallback_bbox[1]), min(lats) - pad)
    lon_max = min(float(fallback_bbox[2]), max(lons) + pad)
    lat_max = min(float(fallback_bbox[3]), max(lats) + pad)
    if lon_min >= lon_max or lat_min >= lat_max:
        return fallback_bbox
    return (lon_min, lat_min, lon_max, lat_max)


def _scenario_loss_from_result(result: Any, scenario: str) -> float:
    scenario_key = str(scenario or "annual")
    if result is None:
        return 0.0
    if scenario_key == "annual":
        return float(np.asarray(getattr(result, "eai_direct_by_point", []), dtype=float).sum())
    match = re.fullmatch(r"rp(\d+)", scenario_key)
    if match:
        return_period = int(match.group(1))
        return float((getattr(result, "pml_eur", {}) or {}).get(return_period, 0.0) or 0.0)
    if scenario_key == "event_max":
        return float(getattr(result, "max_event_loss_eur", 0.0) or 0.0)
    return float(np.asarray(getattr(result, "eai_direct_by_point", []), dtype=float).sum())


def _is_effectively_wind_only_ratio_map(ratio_map: dict[str, float] | None, *, tol: float = 1e-9) -> bool:
    normalized = _normalize_component_ratio_map(ratio_map if isinstance(ratio_map, dict) else None)
    non_wind = float(normalized.get("rain", 0.0)) + float(normalized.get("surge", 0.0)) + float(normalized.get("landslide", 0.0))
    return non_wind <= float(tol)


def _load_hazard_map_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to parse hazard map payload from %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_complete_analysis_source_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
    checkpoint_dir = str(modeling.get("sharding_checkpoint_dir") or "")
    match = re.search(r"/complete-analysis-runs/([^/]+)/", checkpoint_dir)
    run_id = match.group(1) if match else ""
    return {
        "run_id": run_id or None,
        "generated_at": str(meta.get("updated_at") or meta.get("generated_at") or "") or None,
        "source": str(meta.get("source") or "") or None,
    }


def _build_publication_trace(
    *,
    artifact_kind: str,
    source_mode: str,
    fallback_active: bool,
    fallback_reason: str | None,
    complete_analysis_source: dict[str, Any] | None,
    hazard_map_run_id: str | None,
    hazard_map_generated_at: str | None,
) -> dict[str, Any]:
    source_meta = complete_analysis_source if isinstance(complete_analysis_source, dict) else {}
    return {
        "artifact_kind": str(artifact_kind),
        "source_mode": str(source_mode),
        "fallback_active": bool(fallback_active),
        "fallback_reason": str(fallback_reason or "") or None,
        "complete_analysis_run_id": str(source_meta.get("run_id") or "") or None,
        "complete_analysis_generated_at": str(source_meta.get("generated_at") or "") or None,
        "complete_analysis_source": str(source_meta.get("source") or "") or None,
        "wind_map_run_id": str(hazard_map_run_id or "") or None,
        "wind_map_generated_at": str(hazard_map_generated_at or "") or None,
    }


def _surge_depth_from_map_cell(cell: dict[str, Any], scenario: str) -> float:
    scenario_key = str(scenario or "annual").strip().lower()
    if scenario_key in {"annual", "top10", "top5"}:
        value = float(cell.get("mean_surge_m") or 0.0)
    elif scenario_key.startswith("rp"):
        value = float(cell.get(f"{scenario_key}_surge_m") or 0.0)
    elif scenario_key == "event_max":
        value = float(cell.get("event_max_surge_m") or 0.0)
    else:
        value = 0.0
    return value if np.isfinite(value) and value > 0.0 else 0.0


def _build_surge_proxy_losses_from_hazard_map(
    hazard_map_json: Path | None,
    point_records: list[dict[str, Any]],
    *,
    flood_curve_file: Path,
) -> dict[str, dict[str, float]]:
    payload = _load_hazard_map_payload(hazard_map_json)
    meta = payload.get("meta") if isinstance(payload, dict) else None
    bbox = meta.get("bbox") if isinstance(meta, dict) else None
    if not isinstance(meta, dict) or not isinstance(bbox, dict):
        return {}

    try:
        lat_min = float(bbox.get("lat_min"))
        lon_min = float(bbox.get("lon_min"))
        cell_deg = float(meta.get("grid_cell_deg") or 0.0)
    except Exception:
        return {}
    if not np.isfinite(lat_min) or not np.isfinite(lon_min) or not np.isfinite(cell_deg) or cell_deg <= 0.0:
        return {}

    try:
        vulnerability = get_multi_hazard_vulnerability_payload(
            hazard_component="surge",
            flood_curve_file=Path(flood_curve_file),
        )
    except Exception as exc:
        logger.warning(
            "Unable to load multi-hazard surge vulnerability payload (%s: %s)",
            type(exc).__name__,
            exc,
        )
        return {}

    curves = vulnerability.get("curves")
    explicit_mapping = vulnerability.get("explicit_asset_type_mapping")
    if not isinstance(curves, list) or not isinstance(explicit_mapping, dict):
        return {}

    curve_by_impf_id: dict[int, dict[str, Any]] = {}
    for curve in curves:
        if not isinstance(curve, dict):
            continue
        try:
            curve_by_impf_id[int(curve.get("impf_id"))] = curve
        except Exception:
            continue

    out: dict[str, dict[str, float]] = {
        hazard_key: {scenario: 0.0 for scenario in MAP_SCENARIOS}
        for hazard_key in ("storm", "storm_cmcc")
    }

    for hazard_key in ("storm", "storm_cmcc"):
        hazard_payload = payload.get(hazard_key) if isinstance(payload, dict) else None
        cells = hazard_payload.get("cells") if isinstance(hazard_payload, dict) else None
        if not isinstance(cells, list):
            continue
        cell_lookup: dict[tuple[int, int], dict[str, Any]] = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            try:
                cell_lookup[(int(cell.get("i")), int(cell.get("j")))] = cell
            except Exception:
                continue
        if not cell_lookup:
            continue

        for rec in point_records:
            try:
                lat = float(rec.get("lat"))
                lon = float(rec.get("lon"))
                value_eur = max(0.0, float(rec.get("value_eur") or 0.0))
            except Exception:
                continue
            if value_eur <= 0.0 or not np.isfinite(lat) or not np.isfinite(lon):
                continue

            i = int(np.floor((lat - lat_min) / cell_deg))
            j = int(np.floor((lon - lon_min) / cell_deg))
            cell = cell_lookup.get((i, j))
            if not cell:
                continue

            asset_type = str(rec.get("asset_type") or "").strip().lower()
            mapping = explicit_mapping.get(asset_type)
            if not isinstance(mapping, dict):
                continue
            try:
                impf_id = int(mapping.get("impf_id"))
            except Exception:
                continue
            curve = curve_by_impf_id.get(impf_id)
            if not isinstance(curve, dict):
                continue

            intensity = np.asarray(curve.get("intensity") or [], dtype=float)
            mdd = np.asarray(curve.get("mdd") or [], dtype=float)
            if intensity.size == 0 or mdd.size == 0:
                continue

            for scenario in MAP_SCENARIOS:
                depth = _surge_depth_from_map_cell(cell, scenario)
                if depth <= 0.0:
                    continue
                damage_ratio = float(np.interp(depth, intensity, mdd, left=0.0, right=float(mdd[-1])))
                if damage_ratio <= 0.0:
                    continue
                out[hazard_key][scenario] += value_eur * damage_ratio

    return out


def _build_landslide_proxy_losses(
    exposure_bundle: Any,
    point_records: list[dict[str, Any]],
    *,
    territory: str,
    settings: Any,
    bbox: tuple[float, float, float, float],
) -> dict[str, dict[str, Any]]:
    values = np.asarray(
        [max(0.0, float(rec.get("value_eur") or 0.0)) for rec in point_records],
        dtype=float,
    ).reshape(-1)
    if values.size == 0:
        return {}

    source_map = {
        "storm": (
            ("precipitation", Path(settings.landslide_precip_current_path)),
            ("earthquake", Path(settings.landslide_earthquake_path)),
        ),
        "storm_cmcc": (
            ("precipitation", Path(settings.landslide_precip_ssp585_path)),
            ("earthquake", Path(settings.landslide_earthquake_path)),
        ),
    }

    out: dict[str, dict[str, Any]] = {}
    for hazard_key, sources in source_map.items():
        scenario_arrays = {
            scenario: np.zeros_like(values, dtype=float)
            for scenario in MAP_SCENARIOS
        }
        source_paths: list[str] = []
        for source_name, source_path in sources:
            path = Path(source_path)
            if not path.exists():
                raise FileNotFoundError(f"Missing landslide raster for {hazard_key}/{source_name}: {path}")
            source_paths.append(str(path))
            print(f"[progress] landslide_proxy_start: hazard={hazard_key} source={source_name}", flush=True)
            source_payload = _run_landslide_proxy_source(
                exposure_bundle,
                bbox=bbox,
                path_sourcefile=path,
                corr_fact=float(settings.landslide_corr_fact),
                n_years=int(settings.landslide_n_years),
                dist=str(settings.landslide_dist),
                random_seed=_stable_seed(territory, hazard_key, source_name, path.name),
            )
            factors = dict(source_payload.get("factors") or {})
            annual = np.asarray(source_payload.get("annual") or [], dtype=float).reshape(-1)
            annual = np.nan_to_num(annual, nan=0.0, posinf=0.0, neginf=0.0)
            annual = np.minimum(np.maximum(annual, 0.0), values)
            for scenario in MAP_SCENARIOS:
                factor = 1.0 if scenario == "annual" else float(factors.get(scenario, 0.0) or 0.0)
                if factor <= 0.0:
                    continue
                scenario_arrays[scenario] = np.minimum(
                    values,
                    scenario_arrays[scenario] + np.minimum(np.maximum(annual * factor, 0.0), values),
                )
            print(f"[progress] landslide_proxy_complete: hazard={hazard_key} source={source_name}", flush=True)

        out[hazard_key] = {
            "scenario_arrays": scenario_arrays,
            "scenario_totals": {scenario: float(arr.sum()) for scenario, arr in scenario_arrays.items()},
            "source_paths": source_paths,
        }
    return out


def _compute_landslide_proxy_source_payload(
    exposure_bundle: Any,
    *,
    bbox: tuple[float, float, float, float],
    path_sourcefile: Path,
    corr_fact: float,
    n_years: int,
    dist: str,
    random_seed: int,
) -> dict[str, Any]:
    del bbox
    point_records = list(getattr(exposure_bundle, "point_records", []) or [])
    values = np.asarray(
        [max(0.0, float(rec.get("value_eur") or 0.0)) for rec in point_records],
        dtype=float,
    ).reshape(-1)
    raw_classes = _sample_raster_values_for_point_records(path_sourcefile, point_records)
    class_values = np.where(np.asarray(raw_classes, dtype=float).reshape(-1) > 1.0, raw_classes, 0.0)
    occurrence_rates = np.clip(class_values / max(float(corr_fact), 1e-9), 0.0, 1.0)
    damage_ratios = np.interp(
        class_values,
        np.asarray(LANDSLIDE_INTENSITIES, dtype=float),
        np.asarray(LANDSLIDE_HYPOTHESIS_CURVE, dtype=float),
        left=0.0,
        right=float(LANDSLIDE_HYPOTHESIS_CURVE[-1]),
    )
    damage_amounts = np.minimum(np.maximum(values * damage_ratios, 0.0), values)
    annual_arr = np.minimum(np.maximum(damage_amounts * occurrence_rates, 0.0), values)
    yearly_losses = _simulate_landslide_portfolio_yearly_losses(
        damage_amounts,
        occurrence_rates,
        n_years=int(n_years),
        dist=str(dist),
        seed=int(random_seed),
    )
    yearly_freq = np.full(max(1, yearly_losses.size), 1.0 / max(1, yearly_losses.size), dtype=float)
    metrics_stub = SimpleNamespace(
        aai_agg_eur=float(annual_arr.sum()),
        pml_eur={
            10: _loss_at_return_period(yearly_losses, yearly_freq, 10.0),
            50: _loss_at_return_period(yearly_losses, yearly_freq, 50.0),
            100: _loss_at_return_period(yearly_losses, yearly_freq, 100.0),
            1000: _loss_at_return_period(yearly_losses, yearly_freq, 1000.0),
        },
        max_event_loss_eur=float(np.max(yearly_losses)) if yearly_losses.size else 0.0,
    )
    annual = annual_arr.tolist()
    factors = {scenario: float(value or 0.0) for scenario, value in (scenario_loss_factors(metrics_stub) or {}).items()}
    return {
        "annual": annual,
        "factors": factors,
    }


def _landslide_proxy_source_worker(
    exposure_bundle: Any,
    bbox: tuple[float, float, float, float],
    path_sourcefile: str,
    corr_fact: float,
    n_years: int,
    dist: str,
    random_seed: int,
    output_path: str,
) -> None:
    try:
        payload = _compute_landslide_proxy_source_payload(
            exposure_bundle,
            bbox=bbox,
            path_sourcefile=Path(path_sourcefile),
            corr_fact=float(corr_fact),
            n_years=int(n_years),
            dist=str(dist),
            random_seed=int(random_seed),
        )
    except Exception as exc:
        payload = {"error": f"{type(exc).__name__}: {exc}"}
        Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
        raise

    Path(output_path).write_text(json.dumps(payload), encoding="utf-8")


def _run_landslide_proxy_source(
    exposure_bundle: Any,
    *,
    bbox: tuple[float, float, float, float],
    path_sourcefile: Path,
    corr_fact: float,
    n_years: int,
    dist: str,
    random_seed: int,
) -> dict[str, Any]:
    try:
        ctx = multiprocessing.get_context("spawn")
    except ValueError:
        return _compute_landslide_proxy_source_payload(
            exposure_bundle,
            bbox=bbox,
            path_sourcefile=path_sourcefile,
            corr_fact=corr_fact,
            n_years=n_years,
            dist=dist,
            random_seed=random_seed,
        )

    with tempfile.NamedTemporaryFile(prefix="landslide-proxy-", suffix=".json", delete=False) as handle:
        output_path = handle.name
    process = ctx.Process(
        target=_landslide_proxy_source_worker,
        args=(
            exposure_bundle,
            bbox,
            str(path_sourcefile),
            float(corr_fact),
            int(n_years),
            str(dist),
            int(random_seed),
            output_path,
        ),
    )
    process.start()
    process.join()

    payload: dict[str, Any] = {}
    output_text = ""
    output_file = Path(output_path)
    if output_file.exists():
        try:
            output_text = output_file.read_text(encoding="utf-8")
        finally:
            output_file.unlink(missing_ok=True)

    if output_text.strip():
        payload = json.loads(output_text)

    if process.exitcode != 0:
        detail = str(payload.get("error") or f"child process exited with code {process.exitcode}")
        raise RuntimeError(f"Landslide proxy source failed for {path_sourcefile}: {detail}")
    if not payload:
        raise RuntimeError(f"Landslide proxy source produced no payload for {path_sourcefile}")
    return payload


def _breakdown_shares_from_point_losses(point_losses: np.ndarray, point_records: list[dict[str, Any]]) -> dict[str, float]:
    raw = {class_key: 0.0 for class_key in DAMAGE_BREAKDOWN_LABELS}
    losses = np.asarray(point_losses, dtype=float).reshape(-1)
    for idx, rec in enumerate(point_records):
        if idx >= losses.size:
            break
        class_key = _breakdown_class_from_point(rec)
        if class_key in raw:
            raw[class_key] += max(0.0, float(losses[idx]))
    return _normalize_breakdown_share_map(raw)


def _build_proxy_payload(
    run: Any,
    exposure_bundle: Any,
    point_records: list[dict[str, Any]],
    *,
    territory: str,
    sample_point_count: int,
    landslide_bbox: tuple[float, float, float, float],
    settings: Any,
    args: argparse.Namespace,
) -> dict[str, Any]:
    component_ratios = _component_ratios_from_climada_run(run)
    default_proxy = _default_multi_hazard_proxy(component_ratios)
    notes = list(getattr(run, "notes", []) or [])
    print("[progress] proxy_payload_landslide_start", flush=True)
    landslide_proxy_losses = _build_landslide_proxy_losses(
        exposure_bundle,
        point_records,
        territory=territory,
        settings=settings,
        bbox=landslide_bbox,
    )
    print("[progress] proxy_payload_landslide_complete", flush=True)
    if landslide_proxy_losses:
        notes.append(
            "Landslide probabilistic rasters integrated for the case-study proxy (precipitation current / SSP585 + earthquake)."
        )

    hazards_payload: dict[str, Any] = {}
    point_values = np.asarray(
        [max(0.0, float(rec.get("value_eur") or 0.0)) for rec in point_records],
        dtype=float,
    ).reshape(-1)
    for hazard_key in ("storm", "storm_cmcc"):
        hazard_total = (getattr(run, "hazards", {}) or {}).get(hazard_key)
        hazard_components = (getattr(run, "component_hazards", {}) or {}).get(hazard_key, {}) or {}
        wind_result = hazard_components.get("wind")
        rain_result = hazard_components.get("rain")
        surge_result = hazard_components.get("surge")
        landslide_payload = landslide_proxy_losses.get(hazard_key, {}) if isinstance(landslide_proxy_losses, dict) else {}
        landslide_scenario_arrays = (landslide_payload.get("scenario_arrays") or {}) if isinstance(landslide_payload, dict) else {}
        landslide_annual_losses = np.asarray(
            landslide_scenario_arrays.get("annual", np.zeros_like(point_values)),
            dtype=float,
        ).reshape(-1)
        combined_annual_losses = np.asarray(
            getattr(hazard_total, "eai_direct_by_point", getattr(wind_result, "eai_direct_by_point", [])),
            dtype=float,
        ).reshape(-1)
        if landslide_annual_losses.size:
            n = min(combined_annual_losses.size, landslide_annual_losses.size, point_values.size)
            combined_annual_losses[:n] = np.minimum(
                np.maximum(combined_annual_losses[:n] + landslide_annual_losses[:n], 0.0),
                point_values[:n],
            )
        annual_shares = _breakdown_shares_from_point_losses(combined_annual_losses, point_records)

        raw_scenario_losses = {
            scenario: float(_scenario_loss_from_result(hazard_total, scenario))
            + float((landslide_payload.get("scenario_totals") or {}).get(scenario, 0.0) or 0.0)
            for scenario in MAP_SCENARIOS
        }
        scenario_losses = _normalize_proxy_scenario_loss_totals(raw_scenario_losses)
        if any(abs(float(scenario_losses.get(s, 0.0)) - float(raw_scenario_losses.get(s, 0.0))) > 1e-6 for s in MAP_SCENARIOS):
            notes.append(
                f"Normalized {hazard_key} proxy scenario losses to preserve monotonic annual/RP ordering."
            )

        component_point_losses = {
            "wind": np.asarray(getattr(wind_result, "eai_direct_by_point", np.zeros_like(point_values)), dtype=float).reshape(-1),
            "rain": np.asarray(getattr(rain_result, "eai_direct_by_point", np.zeros_like(point_values)), dtype=float).reshape(-1),
            "surge": np.asarray(getattr(surge_result, "eai_direct_by_point", np.zeros_like(point_values)), dtype=float).reshape(-1),
        }

        scenarios: dict[str, Any] = {}
        for scenario in MAP_SCENARIOS:
            landslide_loss = float((landslide_payload.get("scenario_totals") or {}).get(scenario, 0.0) or 0.0)
            combined_loss = float(scenario_losses.get(scenario, 0.0) or 0.0)
            wind_loss = _scenario_loss_from_result(wind_result, scenario)
            base_loss = wind_loss + landslide_loss
            if base_loss > 0.0:
                multiplier = max(0.0, combined_loss / base_loss)
            else:
                multiplier = 1.0 if combined_loss <= 0.0 else 1.0
            scenario_ratio_map = _normalize_component_ratio_map(
                ((component_ratios.get(hazard_key) or {}).get(scenario))
                or ((default_proxy.get(hazard_key) or {}).get("component_ratios") or {}).get(scenario)
            )
            landslide_share = max(0.0, min(1.0, landslide_loss / max(combined_loss, 1e-9))) if combined_loss > 0.0 else 0.0
            if landslide_share > 0.0:
                scenario_ratio_map = _normalize_component_ratio_map(
                    {
                        "wind": float(scenario_ratio_map.get("wind", 0.0)) * (1.0 - landslide_share),
                        "rain": float(scenario_ratio_map.get("rain", 0.0)) * (1.0 - landslide_share),
                        "surge": float(scenario_ratio_map.get("surge", 0.0)) * (1.0 - landslide_share),
                        "landslide": landslide_share,
                    }
                )
            scenario_breakdown_shares = _scenario_breakdown_shares_from_component_arrays(
                point_records,
                {
                    **component_point_losses,
                    "landslide": np.asarray(
                        landslide_scenario_arrays.get(scenario, np.zeros_like(point_values)),
                        dtype=float,
                    ).reshape(-1),
                },
                scenario_ratio_map,
                fallback_share_map=annual_shares,
            )
            scenarios[scenario] = {
                "global_multiplier": round(float(multiplier), 6),
                "component_ratios": scenario_ratio_map,
                "breakdown_shares": scenario_breakdown_shares,
            }

        hazards_payload[hazard_key] = {
            "scenarios": scenarios,
        }

    print("[progress] proxy_payload_build_complete", flush=True)
    return {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "case_study_run_id": str(getattr(args, "case_study_run_id", "") or ""),
            "territory": territory,
            "territory_label": territory_label(territory),
            "sample_point_count": int(sample_point_count),
            "sampling_spacing_m": float(args.spacing_m),
            "max_points_total": int(args.max_points_total),
            "max_points_per_feature": int(args.max_points_per_feature),
            "dynamic_max_tracks": int(args.dynamic_max_tracks),
            "hazard_map_json": str(args.hazard_map_json) if getattr(args, "hazard_map_json", None) else None,
            "surge_priority_point_count": int(getattr(args, "surge_priority_point_count", 0) or 0),
            "surge_priority_source": str(getattr(args, "surge_priority_source", "") or ""),
            "storm_years": int(settings.storm_years),
            "hazard_storm_path": str(args.hazard_storm_path),
            "hazard_storm_cmcc_path": str(args.hazard_storm_cmcc_path),
            "landslide_sources": {
                "storm": [str(Path(settings.landslide_precip_current_path)), str(Path(settings.landslide_earthquake_path))],
                "storm_cmcc": [str(Path(settings.landslide_precip_ssp585_path)), str(Path(settings.landslide_earthquake_path))],
            },
            "notes": notes,
            "modeling": getattr(run, "modeling", {}) or {},
        },
        "hazards": hazards_payload,
    }


def _serialize_impact_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "eai_direct_by_point": np.asarray(getattr(result, "eai_direct_by_point", []), dtype=float).reshape(-1).tolist(),
        "max_loss_by_point": np.asarray(getattr(result, "max_loss_by_point", []), dtype=float).reshape(-1).tolist(),
        "aai_agg_eur": float(getattr(result, "aai_agg_eur", 0.0) or 0.0),
        "max_event_loss_eur": float(getattr(result, "max_event_loss_eur", 0.0) or 0.0),
        "pml_eur": {str(key): float(value or 0.0) for key, value in ((getattr(result, "pml_eur", {}) or {}).items())},
        "tvar_95_eur": float(getattr(result, "tvar_95_eur", 0.0) or 0.0),
    }


def _deserialize_impact_result(payload: dict[str, Any] | None) -> Any:
    data = payload if isinstance(payload, dict) else {}
    return SimpleNamespace(
        eai_direct_by_point=np.asarray(data.get("eai_direct_by_point") or [], dtype=float).reshape(-1),
        max_loss_by_point=np.asarray(data.get("max_loss_by_point") or [], dtype=float).reshape(-1),
        aai_agg_eur=float(data.get("aai_agg_eur", 0.0) or 0.0),
        max_event_loss_eur=float(data.get("max_event_loss_eur", 0.0) or 0.0),
        pml_eur={int(key): float(value or 0.0) for key, value in ((data.get("pml_eur") or {}).items())},
        tvar_95_eur=float(data.get("tvar_95_eur", 0.0) or 0.0),
        top_events=[],
        matching={},
    )


def _serialize_climada_hazard_slice(run: Any, hazard_key: str) -> dict[str, Any]:
    return {
        "hazard_key": hazard_key,
        "hazard_total": _serialize_impact_result((getattr(run, "hazards", {}) or {}).get(hazard_key)),
        "hazard_components": {
            component_name: _serialize_impact_result(component_result)
            for component_name, component_result in (((getattr(run, "component_hazards", {}) or {}).get(hazard_key, {}) or {}).items())
        },
        "notes": list(getattr(run, "notes", []) or []),
        "modeling": dict(getattr(run, "modeling", {}) or {}),
    }


def _proxy_climada_slice_worker(
    sample_bundle: Any,
    climada_kwargs: dict[str, Any],
    hazard_key: str,
    output_path: str,
) -> None:
    try:
        run = run_climada_direct_impacts(
            sample_bundle,
            **climada_kwargs,
            hazard_keys=(hazard_key,),
        )
        payload = _serialize_climada_hazard_slice(run, hazard_key)
    except Exception as exc:
        payload = {
            "hazard_key": hazard_key,
            "error": f"{type(exc).__name__}: {exc}",
        }
        Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
        raise

    Path(output_path).write_text(json.dumps(payload), encoding="utf-8")


def _merge_proxy_modeling(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merge_keys = {
        "hazard_zero_intensity",
        "multi_hazard_components_by_hazard",
        "multi_hazard_component_status_by_hazard",
        "climada_component_sharding",
    }
    for key, value in incoming.items():
        if key in merge_keys and isinstance(value, dict):
            current = merged.get(key)
            current_dict = dict(current) if isinstance(current, dict) else {}
            current_dict.update(value)
            merged[key] = current_dict
            continue
        if key == "requested_hazard_keys":
            existing = list(merged.get(key) or [])
            merged[key] = sorted({str(entry) for entry in existing + list(value or [])})
            continue
        merged[key] = value
    merged["process_sliced_by_hazard"] = True
    return merged


def _assemble_climada_run_from_slices(payloads: dict[str, dict[str, Any]]) -> Any:
    hazards: dict[str, Any] = {}
    component_hazards: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    seen_notes: set[str] = set()
    modeling: dict[str, Any] = {}

    for hazard_key in ("storm", "storm_cmcc"):
        payload = payloads.get(hazard_key)
        if not isinstance(payload, dict):
            continue
        hazards[hazard_key] = _deserialize_impact_result(payload.get("hazard_total"))
        component_hazards[hazard_key] = {
            component_name: _deserialize_impact_result(component_payload)
            for component_name, component_payload in ((payload.get("hazard_components") or {}).items())
        }
        for note in list(payload.get("notes") or []):
            note_text = str(note)
            if note_text in seen_notes:
                continue
            notes.append(note_text)
            seen_notes.add(note_text)
        modeling = _merge_proxy_modeling(modeling, dict(payload.get("modeling") or {}))

    return SimpleNamespace(
        hazards=hazards,
        component_hazards=component_hazards,
        notes=notes,
        modeling=modeling,
    )


def _run_proxy_climada(sample_bundle: Any, climada_kwargs: dict[str, Any]) -> Any:
    try:
        ctx = multiprocessing.get_context("fork")
    except ValueError:
        return run_climada_direct_impacts(sample_bundle, **climada_kwargs)

    payloads: dict[str, dict[str, Any]] = {}
    for hazard_key in ("storm", "storm_cmcc"):
        with tempfile.NamedTemporaryFile(prefix=f"proxy-{hazard_key}-", suffix=".json", delete=False) as handle:
            output_path = handle.name
        print(f"[progress] strict_climada_slice_start: hazard={hazard_key}", flush=True)
        process = ctx.Process(
            target=_proxy_climada_slice_worker,
            args=(sample_bundle, climada_kwargs, hazard_key, output_path),
        )
        process.start()
        process.join()

        output_payload: dict[str, Any] = {}
        output_file = Path(output_path)
        if output_file.exists():
            try:
                output_text = output_file.read_text(encoding="utf-8")
                if output_text.strip():
                    output_payload = json.loads(output_text)
            finally:
                output_file.unlink(missing_ok=True)

        if process.exitcode != 0:
            detail = str(output_payload.get("error") or f"child process exited with code {process.exitcode}")
            raise RuntimeError(f"Strict CLIMADA slice failed for {hazard_key}: {detail}")
        if not output_payload:
            raise RuntimeError(f"Strict CLIMADA slice produced no payload for {hazard_key}")
        if str(output_payload.get("hazard_key") or "") != hazard_key:
            raise RuntimeError(f"Strict CLIMADA slice returned an unexpected hazard payload for {hazard_key}")

        payloads[hazard_key] = output_payload
        print(f"[progress] strict_climada_slice_complete: hazard={hazard_key}", flush=True)

    return _assemble_climada_run_from_slices(payloads)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a lightweight sampled multi-hazard proxy for explicit SIB case-study territories.")
    parser.add_argument("--territory", default="guadeloupe")
    parser.add_argument("--infra-elec-dir", default=None)
    parser.add_argument("--infra-eau-dir", default=None)
    parser.add_argument("--complete-analysis-json", default=None)
    parser.add_argument("--spacing-m", type=float, default=800.0)
    parser.add_argument("--max-points-total", type=int, default=800)
    parser.add_argument("--max-points-per-feature", type=int, default=8)
    parser.add_argument("--dynamic-max-tracks", type=int, default=100)
    parser.add_argument("--hazard-map-json", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument(
        "--case-study-run-id",
        default=None,
        help="Optional coherence token propagated across case-study artefacts (maps/proxy/page analysis).",
    )
    args = parser.parse_args()
    _load_case_study_helpers()

    territory = parse_territory(args.territory)
    case_cfg = get_case_study(
        territory,
        infra_elec_dir=Path(args.infra_elec_dir) if args.infra_elec_dir else None,
        infra_eau_dir=Path(args.infra_eau_dir) if args.infra_eau_dir else None,
    )
    settings = load_settings()
    resolved_surge_topo_path = resolve_surge_topo_path_for_territory(territory, settings=settings)
    hazard_storm_path, hazard_storm_cmcc_path = _resolve_hazard_paths_for_case_study(territory, settings)
    args.hazard_storm_path = str(hazard_storm_path)
    args.hazard_storm_cmcc_path = str(hazard_storm_cmcc_path)
    complete_analysis_json = (
        Path(args.complete_analysis_json)
        if args.complete_analysis_json
        else (REPO_ROOT / "web" / "data" / f"{territory}-complete-analysis.json")
    )
    complete_analysis_payload = _load_hazard_map_payload(complete_analysis_json)
    complete_analysis_source = _extract_complete_analysis_source_metadata(complete_analysis_payload)

    out_json = (
        Path(args.out_json)
        if args.out_json
        else (REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json")
    )
    args.hazard_map_json = str(
        Path(args.hazard_map_json)
        if args.hazard_map_json
        else (REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json")
    )
    hazard_map_payload = _load_hazard_map_payload(Path(args.hazard_map_json))
    hazard_map_meta = hazard_map_payload.get("meta") if isinstance(hazard_map_payload, dict) else None
    hazard_map_run_id = (
        str(hazard_map_meta.get("case_study_run_id") or "").strip()
        if isinstance(hazard_map_meta, dict)
        else ""
    )
    hazard_map_generated_at = (
        str(hazard_map_meta.get("generated_at") or "").strip()
        if isinstance(hazard_map_meta, dict)
        else ""
    )
    provided_run_id = str(args.case_study_run_id or "").strip()
    if provided_run_id and not hazard_map_run_id:
        raise ValueError(
            f"case-study run id provided ({provided_run_id}) but wind map has no case_study_run_id: {args.hazard_map_json}"
        )
    if provided_run_id and hazard_map_run_id and provided_run_id != hazard_map_run_id:
        raise ValueError(
            f"case-study run id mismatch: provided={provided_run_id} "
            f"but wind map meta has {hazard_map_run_id}"
        )
    args.case_study_run_id = provided_run_id or hazard_map_run_id or datetime.now(UTC).strftime(
        f"{territory}_case_%Y%m%dT%H%M%SZ"
    )

    exposure = build_complete_exposure(
        infra_elec_dir=case_cfg["infra_elec_dir"],
        infra_eau_dir=case_cfg["infra_eau_dir"],
        territory=territory,
    )
    bbox_cfg = dict(case_cfg.get("wind_bbox") or {})
    default_landslide_bbox = (
        float(bbox_cfg["lon_min"]),
        float(bbox_cfg["lat_min"]),
        float(bbox_cfg["lon_max"]),
        float(bbox_cfg["lat_max"]),
    )
    sample_bundle = build_climada_exposure(
        exposure,
        spacing_m=float(args.spacing_m),
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=max(1, int(args.max_points_per_feature)),
        impact_func_id_resolver=resolve_tc_impact_func_id,
    )
    point_records = list(sample_bundle.point_records or [])
    priority_scores = _load_surge_priority_scores_from_map(
        Path(args.hazard_map_json),
        point_records,
    )
    args.surge_priority_source = "hazard_map_cells" if priority_scores else "none"
    if not priority_scores:
        priority_scores = _load_surge_priority_scores_from_native_chain(
            point_records,
            settings=settings,
            surge_topo_path=Path(resolved_surge_topo_path),
            dynamic_max_tracks=int(args.dynamic_max_tracks),
        )
        args.surge_priority_source = "native_tcsurge_bathtub" if priority_scores else "none"
    args.surge_priority_point_count = int(len(priority_scores))
    sample_bundle = _subset_bundle_for_component_ratios(
        sample_bundle,
        max_points_total=max(1, int(args.max_points_total)),
        priority_scores=priority_scores,
    )
    sampled_point_records = list(sample_bundle.point_records or [])
    landslide_bbox = _derive_landslide_bbox(
        sampled_point_records,
        fallback_bbox=default_landslide_bbox,
        padding_deg=max(float(args.spacing_m) / 111000.0 * 2.0, 0.01),
    )
    print(
        "[progress] "
        f"proxy_input: territory={territory} sample_points={len(sampled_point_records)} "
        f"dynamic_max_tracks={int(args.dynamic_max_tracks)} surge_priority_source={args.surge_priority_source}",
        flush=True,
    )
    proxy_memory_budget_gb = max(
        float(getattr(settings, "climada_memory_budget_gb", 0.0) or 0.0),
        PROXY_CLIMADA_MEMORY_BUDGET_GB,
    )
    configured_max_points_per_shard = int(
        getattr(settings, "climada_max_points_per_shard", PROXY_CLIMADA_MAX_POINTS_PER_SHARD)
        or PROXY_CLIMADA_MAX_POINTS_PER_SHARD
    )
    proxy_max_points_per_shard = configured_max_points_per_shard
    if proxy_max_points_per_shard <= 0 or proxy_max_points_per_shard > PROXY_CLIMADA_MAX_POINTS_PER_SHARD:
        proxy_max_points_per_shard = PROXY_CLIMADA_MAX_POINTS_PER_SHARD
    configured_min_points_per_shard = int(
        getattr(settings, "climada_min_points_per_shard", PROXY_CLIMADA_MIN_POINTS_PER_SHARD)
        or PROXY_CLIMADA_MIN_POINTS_PER_SHARD
    )
    proxy_min_points_per_shard = configured_min_points_per_shard
    if proxy_min_points_per_shard <= 0 or proxy_min_points_per_shard > proxy_max_points_per_shard:
        proxy_min_points_per_shard = min(PROXY_CLIMADA_MIN_POINTS_PER_SHARD, proxy_max_points_per_shard)

    try:
        print(
            "[progress] "
            f"strict_climada_start: memory_budget_gb={proxy_memory_budget_gb:.3f} "
            f"max_points_per_shard={proxy_max_points_per_shard} "
            f"min_points_per_shard={proxy_min_points_per_shard}",
            flush=True,
        )
        climada_kwargs = {
            "hazard_storm_path": Path(hazard_storm_path),
            "hazard_storm_cmcc_path": Path(hazard_storm_cmcc_path),
            "storm_years": max(1, int(settings.storm_years)),
            "top_n_events": max(1, int(settings.climada_top_events_count)),
            "prefer_dynamic_hazards": bool(settings.hazard_prefer_dynamic_from_parquet),
            "fallback_to_precomputed_hazards": False,
            "storm_parquet_path": Path(settings.storm_parquet_path),
            "storm_cmcc_parquet_path": Path(settings.storm_cmcc_parquet_path),
            "wind_unit_in": settings.storm_wind_unit_in,
            "radius_unit_in": settings.storm_radius_unit_in,
            "env_pressure_hpa": float(settings.storm_env_pressure_hpa),
            "dynamic_max_tracks": int(args.dynamic_max_tracks),
            "track_cache_max_entries": 0,
            "multi_hazard_enabled": bool(settings.multi_hazard_enabled),
            "rain_model": settings.hazard_rain_model,
            "surge_topo_path": Path(resolved_surge_topo_path),
            "flood_curve_file": Path(settings.d2_flood_curve_file),
            "execution_profile": "case-study-proxy",
            "memory_budget_gb": proxy_memory_budget_gb,
            "max_points_per_shard": proxy_max_points_per_shard,
            "min_points_per_shard": proxy_min_points_per_shard,
            "max_shard_retry_depth": int(getattr(settings, "climada_max_shard_retry_depth", 4) or 4),
            "strict_required_components": bool(getattr(settings, "climada_strict_required_components", True)),
            "progress_callback": _proxy_progress_callback,
            "return_full_impact_data": False,
        }
        run = _run_proxy_climada(sample_bundle, climada_kwargs)
    except Exception as exc:
        raise RuntimeError(f"Lightweight sampled proxy build failed for {territory}") from exc

    payload = _build_proxy_payload(
        run,
        sample_bundle,
        sampled_point_records,
        territory=territory,
        sample_point_count=len(sampled_point_records),
        landslide_bbox=landslide_bbox,
        settings=settings,
        args=args,
    )
    payload_meta = payload.get("meta") if isinstance(payload, dict) else None
    if isinstance(payload_meta, dict):
        payload_meta["publication_trace"] = _build_publication_trace(
            artifact_kind="multi_hazard_proxy",
            source_mode="lightweight_sampled_climada_proxy",
            fallback_active=False,
            fallback_reason=None,
            complete_analysis_source=complete_analysis_source,
            hazard_map_run_id=hazard_map_run_id,
            hazard_map_generated_at=hazard_map_generated_at,
        )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_json}")
    print(f"territory={territory}")
    print(f"sample_points={len(list(sample_bundle.point_records or []))}")
    for hazard_key in ("storm", "storm_cmcc"):
        annual = (((payload.get('hazards') or {}).get(hazard_key) or {}).get('scenarios') or {}).get("annual", {})
        print(
            f"{hazard_key}: annual multiplier={annual.get('global_multiplier')} "
            f"ratios={annual.get('component_ratios')}"
        )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
