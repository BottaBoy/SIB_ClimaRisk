#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    gpd = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

try:
    from climada.engine import ImpactCalc
    from climada.entity.impact_funcs import ImpactFuncSet
except Exception:  # pragma: no cover - optional at import time for CLI --help
    ImpactCalc = None  # type: ignore[assignment]
    ImpactFuncSet = None  # type: ignore[assignment]

try:
    from shapely.geometry import box
    from shapely.ops import unary_union
except Exception:  # pragma: no cover - optional at import time for CLI --help
    box = None  # type: ignore[assignment]
    unary_union = None  # type: ignore[assignment]

try:
    from osgeo import gdal, osr
except Exception:  # pragma: no cover - optional at import time for CLI --help
    gdal = None  # type: ignore[assignment]
    osr = None  # type: ignore[assignment]


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.exposure_to_climada import ClimadaExposureBundle, build_climada_exposure  # noqa: E402
from app.risk_engine.hazard_loader import load_storm_hazard  # noqa: E402
from app.risk_engine.impact_functions import (  # noqa: E402
    resolve_tc_impact_func_id,
    try_build_climada_impact_funcs,
)
from app.risk_engine.impact_functions_landslide import (  # noqa: E402
    LANDSLIDE_HYPOTHESIS_CURVE,
    LANDSLIDE_INTENSITIES,
)
from app.risk_engine.landslide_engine import run_landslide_direct_impacts, scenario_loss_factors  # noqa: E402
from app.risk_engine.types import NormalizedExposure  # noqa: E402
from build_guadeloupe_complete_analysis import (  # noqa: E402
    WGS84,
    _as_wgs84_and_metric,
    _ensure_crs,
    _read_vector,
    build_complete_exposure,
)
from case_study_sources import get_case_study, parse_territory, territory_label  # noqa: E402
from valuation_ofb import (  # noqa: E402
    SOURCE_LABEL,
    build_valuation_metadata,
    get_aep_ouvrage_value_for_territory,
    get_network_values_per_km,
    get_water_values,
)
from journal_guamar_run import record_guamar_run  # noqa: E402


STATE_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
WATER_BLOCKING_ROLES_BY_SERVICE = {
    "eau_aep": frozenset({"captage_aep", "upep_aep", "pompage_aep"}),
    "eau_eu": frozenset({"step", "poste_refoulement"}),
}

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
HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX = "hydraulic-native"

ASSET_TYPE_TO_NETWORK_CLASS = {
    "eau_aep_cana": "eau_aep",
    "eau_eu_cana": "eau_eu",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
}

NETWORK_LAYER_PREFIX = {
    "eau_aep": "aep-cana",
    "eau_eu": "eu-cana",
    "elec_bt_souterrain": "elec-bt-souterrain",
    "elec_bt_aerien": "elec-bt-aerien",
    "elec_hta_souterrain": "elec-hta-souterrain",
    "elec_hta_aerien": "elec-hta-aerien",
}

GLOBAL_EVENT_CLASS_KEYS = tuple(DAMAGE_BREAKDOWN_LABELS.keys())
TABLE_SCENARIOS = ("annual", "rp50", "rp100", "p99")
MAP_SCENARIOS = ("annual", "rp50", "rp100", "event_max", "top10", "top5")
PUBLIC_MAP_SCENARIOS = ("annual", "rp50", "rp100", "p99", "top10", "top5")
WEB_NETWORK_STATE_METHODOLOGY_METADATA = {
    "schema_version": "aggregated_service_state_v1",
    "aggregation_method": "aggregated_service_state",
    "electric_state_unit": "fixed_grid_0p1deg",
    "water_state_unit": "zone_component_key",
    "methodology_breaks_comparability": True,
}
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
WIND_BIN_STEP_MPS = 1.0
ELECTRIC_NATIVE_GRID_DEG = 0.1
DEFAULT_COMPONENT_LIGHT_SPACING_M = 800.0
DEFAULT_COMPONENT_LIGHT_MAX_POINTS_TOTAL = 4000
DEFAULT_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE = 10
CASE_HAZARD_PATHS = {
    "guadeloupe": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
    "martinique": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique_CMCC.h5",
    ),
    "saint-barthelemy": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
}


def _public_loss_scenario_source(scenario: str) -> str:
    return "event_max" if str(scenario) == "p99" else str(scenario)


def _stable_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def _require_runtime_deps() -> None:
    missing: list[str] = []
    if gpd is None:
        missing.append("geopandas")
    if np is None:
        missing.append("numpy")
    if pd is None:
        missing.append("pandas")
    if ImpactCalc is None or ImpactFuncSet is None:
        missing.append("climada")
    if box is None:
        missing.append("shapely")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_guadeloupe_page1_data.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install backend requirements and retry."
        )


def _prefer_case_study_hdf5_path(configured_path: Path, case_default_path: Path) -> Path:
    builtin_case_paths = {path for pair in CASE_HAZARD_PATHS.values() for path in pair}
    if configured_path.exists():
        if configured_path == case_default_path:
            return configured_path
        if configured_path in builtin_case_paths and case_default_path.exists():
            return case_default_path
        return configured_path
    return case_default_path if case_default_path.exists() else configured_path


def _resolve_hazard_paths_for_case_study(territory: str, settings) -> tuple[Path, Path]:
    default_storm_path, default_cmcc_path = CASE_HAZARD_PATHS[territory]
    settings_storm_path = Path(settings.hazard_storm_path)
    settings_cmcc_path = Path(settings.hazard_storm_cmcc_path)

    if settings.multi_hazard_enabled:
        hazard_storm_path = _prefer_case_study_hdf5_path(settings_storm_path, default_storm_path)
        hazard_storm_cmcc_path = _prefer_case_study_hdf5_path(settings_cmcc_path, default_cmcc_path)
    else:
        hazard_storm_path = default_storm_path if default_storm_path.exists() else settings_storm_path
        hazard_storm_cmcc_path = default_cmcc_path if default_cmcc_path.exists() else settings_cmcc_path

    return hazard_storm_path, hazard_storm_cmcc_path


def _normalize_wind_unit(raw: str) -> str:
    unit = str(raw or "m/s").strip().lower()
    aliases = {
        "m/s": "m/s",
        "ms": "m/s",
        "mps": "m/s",
        "meter_per_second": "m/s",
        "meters_per_second": "m/s",
        "knot": "kn",
        "knots": "kn",
        "kt": "kn",
        "kts": "kn",
        "kn": "kn",
        "km/h": "km/h",
        "kmh": "km/h",
        "kph": "km/h",
    }
    if unit not in aliases:
        raise ValueError(f"Unsupported wind unit '{raw}'. Supported: m/s, kn, km/h")
    return aliases[unit]


def _convert_wind_to_mps(values: pd.Series, unit_in: str) -> pd.Series:
    unit = _normalize_wind_unit(unit_in)
    wind = pd.to_numeric(values, errors="coerce").astype(float)
    if unit == "m/s":
        return wind
    if unit == "kn":
        return wind * 0.514444
    return wind / 3.6  # km/h -> m/s


def _case_bbox_polygon(case_cfg: dict[str, Any]):
    bbox = dict(case_cfg.get("wind_bbox") or {})
    return box(
        float(bbox["lon_min"]),
        float(bbox["lat_min"]),
        float(bbox["lon_max"]),
        float(bbox["lat_max"]),
    )


def _clip_case_gdf(gdf: gpd.GeoDataFrame, case_cfg: dict[str, Any]) -> gpd.GeoDataFrame:
    gdf_wgs = _ensure_crs(gdf, fallback=WGS84).to_crs(WGS84).copy()
    gdf_wgs["geometry"] = gdf_wgs.geometry.intersection(_case_bbox_polygon(case_cfg))
    geometry = gdf_wgs.geometry
    return gdf_wgs[(~geometry.is_empty) & (~geometry.isna())].copy()


def _state_from_ratio(ratio: float) -> str:
    if ratio >= 0.35:
        return "S3"
    if ratio >= 0.15:
        return "S2"
    if ratio >= 0.05:
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


def _new_health_bucket() -> dict[str, float]:
    return {"total": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}


def _add_state(bucket: dict[str, float], state: str, weight: float) -> None:
    bucket["total"] += float(weight)
    if state in {"S1", "S2", "S3"}:
        bucket[state] += float(weight)


def _health(bucket: dict[str, float]) -> float:
    total = float(bucket.get("total", 0.0))
    if total <= 0.0:
        return 1.0
    weighted = 0.3 * float(bucket["S1"]) + 0.7 * float(bucket["S2"]) + 1.0 * float(bucket["S3"])
    return max(0.0, min(1.0, 1.0 - weighted / total))


def _evaluate_network_dependency_scenario(
    *,
    direct_loss: np.ndarray,
    values: np.ndarray,
    class_keys: list[str | None],
    territories: list[str],
    weights_km: np.ndarray,
    water_service_classes: list[str | None] | None = None,
    service_feature_ids: list[str | None] | None = None,
    is_service_network: list[bool] | None = None,
    is_blocking_asset: list[bool] | None = None,
) -> dict[str, Any]:
    direct = np.minimum(np.maximum(np.asarray(direct_loss, dtype=float), 0.0), values)
    direct_ratio = np.divide(direct, np.maximum(values, 1.0))
    direct_state = np.array([_state_from_ratio(float(v)) for v in direct_ratio], dtype=object)

    item_count = len(class_keys)
    if water_service_classes is None:
        water_service_classes = [None] * item_count
    if service_feature_ids is None:
        service_feature_ids = [None] * item_count
    if is_service_network is None:
        is_service_network = [False] * item_count
    if is_blocking_asset is None:
        is_blocking_asset = [False] * item_count

    elec_buckets: dict[str, dict[str, float]] = defaultdict(_new_health_bucket)
    for i, ckey in enumerate(class_keys):
        if ckey is None or not ckey.startswith("elec_"):
            continue
        _add_state(elec_buckets[territories[i]], str(direct_state[i]), float(weights_km[i]))
    elec_health = {k: _health(v) for k, v in elec_buckets.items()}
    global_health = _health(_merge_buckets(list(elec_buckets.values())))

    state_after_dependency: list[str] = []
    for i, ckey in enumerate(class_keys):
        state_code = str(direct_state[i])
        water_service_class = water_service_classes[i]
        if water_service_class in {"eau_aep", "eau_eu"}:
            dep_state = _dependency_state_from_elec_health(elec_health.get(territories[i], global_health))
            final_code = dep_state if STATE_ORDER[dep_state] > STATE_ORDER[state_code] else state_code
            state_after_dependency.append(final_code)
            continue
        state_after_dependency.append(state_code)

    blocking_state_by_service: dict[str, str] = {}
    for i, blocking in enumerate(is_blocking_asset):
        if not blocking:
            continue
        service_feature_id = str(service_feature_ids[i] or "").strip()
        if not service_feature_id:
            continue
        blocking_state = str(state_after_dependency[i])
        current_state = blocking_state_by_service.get(service_feature_id, "S0")
        if STATE_ORDER[blocking_state] > STATE_ORDER[current_state]:
            blocking_state_by_service[service_feature_id] = blocking_state

    final_state: list[str] = []
    indirect_s3_flag = np.zeros_like(direct, dtype=bool)
    for i, state_code in enumerate(state_after_dependency):
        final_code = str(state_code)
        if is_service_network[i]:
            service_feature_id = str(service_feature_ids[i] or "").strip()
            blocker_state = blocking_state_by_service.get(service_feature_id)
            if blocker_state and STATE_ORDER[blocker_state] > STATE_ORDER[final_code]:
                final_code = blocker_state
        indirect_s3_flag[i] = final_code == "S3" and str(direct_state[i]) != "S3"
        final_state.append(final_code)

    final_state_arr = np.array(final_state, dtype=object)
    return {
        "direct_loss": direct,
        "direct_state": direct_state,
        "final_state": final_state_arr,
        "total_loss": np.array(direct, dtype=float),
        "indirect_s3_flag": indirect_s3_flag,
    }


def _histogram_percent(
    values: pd.Series,
    bins: int | np.ndarray = 12,
    *,
    bin_step_mps: float | None = None,
) -> dict[str, Any]:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    vals = vals[np.isfinite(vals)]
    if vals.empty:
        return {"bins_mps": [], "percent": [], "count": 0}
    hist, edges = np.histogram(vals.to_numpy(dtype=float), bins=bins)
    pct = (hist / max(1, hist.sum())) * 100.0
    bin_centers = 0.5 * (edges[:-1] + edges[1:])
    payload = {
        "bins_mps": [round(float(x), 3) for x in bin_centers.tolist()],
        "percent": [round(float(x), 4) for x in pct.tolist()],
        "count": int(len(vals)),
    }
    if bin_step_mps is not None:
        payload["bin_step_mps"] = round(float(bin_step_mps), 3)
    return payload


def _build_common_wind_edges(
    values_a: pd.Series,
    values_b: pd.Series,
    *,
    step_mps: float = WIND_BIN_STEP_MPS,
) -> np.ndarray:
    step = float(step_mps)
    if not np.isfinite(step) or step <= 0.0:
        raise ValueError(f"Invalid wind bin step: {step_mps}")

    vals_a = pd.to_numeric(values_a, errors="coerce").to_numpy(dtype=float)
    vals_b = pd.to_numeric(values_b, errors="coerce").to_numpy(dtype=float)
    vals = np.concatenate([vals_a[np.isfinite(vals_a)], vals_b[np.isfinite(vals_b)]])
    if vals.size == 0:
        return np.array([0.0, step], dtype=float)

    lower = float(np.floor(np.min(vals)))
    upper = float(np.ceil(np.max(vals)))
    if upper <= lower:
        upper = lower + step

    n_steps = int(np.ceil((upper - lower) / step))
    edges = lower + (np.arange(n_steps + 1, dtype=float) * step)
    if edges[-1] < upper:
        edges = np.append(edges, upper)
    return edges


def _loss_at_return_period(losses: np.ndarray, frequencies: np.ndarray, return_period_years: float) -> float:
    if losses.size == 0:
        return 0.0
    vals = np.nan_to_num(np.asarray(losses, dtype=float).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    vals = np.maximum(vals, 0.0)
    freq = np.nan_to_num(np.asarray(frequencies, dtype=float).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    if freq.size != vals.size or float(freq.sum()) <= 0.0:
        freq = np.full(vals.size, 1.0 / max(1, vals.size), dtype=float)

    order = np.argsort(vals)[::-1]
    vals_sorted = vals[order]
    freq_sorted = freq[order]
    exceed = np.cumsum(freq_sorted)
    target = 1.0 / max(1.0, float(return_period_years))
    idx = int(np.searchsorted(exceed, target, side="left"))
    idx = max(0, min(idx, vals_sorted.size - 1))
    return float(vals_sorted[idx])


def _mean_top_fraction(losses: np.ndarray, fraction: float) -> float:
    vals = np.nan_to_num(np.asarray(losses, dtype=float).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    vals = np.maximum(vals, 0.0)
    if vals.size == 0:
        return 0.0
    k = max(1, int(np.ceil(vals.size * max(0.0, min(1.0, fraction)))))
    top = np.partition(vals, -k)[-k:]
    return float(np.mean(top)) if top.size else 0.0


def _normalize_storm_df(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    if "Maximum wind speed" in df.columns:
        rename_map["Maximum wind speed"] = "wind_max"
    if "TC number" in df.columns and "track_id" not in df.columns:
        rename_map["TC number"] = "tc_number"
    if rename_map:
        df = df.rename(columns=rename_map)
    if "lon" in df.columns:
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df.loc[df["lon"] > 180.0, "lon"] = df.loc[df["lon"] > 180.0, "lon"] - 360.0
    return df


def _parse_file_block_index(path: Path) -> int:
    m = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not m:
        return 0
    return int(m.group(1))


def _iter_storm_txt_files(source: Path, pattern: str) -> list[Path]:
    files = sorted(source.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {source}")
    return files


def _build_wind_distributions_from_txt(
    source: Path,
    pattern: str,
    basin_id: int = 1,
    *,
    wind_unit_in: str = "m/s",
) -> dict[str, Any]:
    cols = [
        "Year",
        "Month",
        "TC number",
        "Time step",
        "Basin ID",
        "Latitude",
        "Longitude",
        "Minimum pressure",
        "Maximum wind speed",
        "Radius to maximum winds",
        "Category",
        "Landfall",
        "Distance to land",
    ]
    usecols = ["Year", "Basin ID", "Maximum wind speed", "TC number"]

    track_max: dict[str, float] = {}
    year_max: dict[int, float] = {}
    files = _iter_storm_txt_files(source, pattern)

    for txt in files:
        block_idx = _parse_file_block_index(txt)
        for chunk in pd.read_csv(
            txt,
            names=cols,
            sep=",",
            usecols=usecols,
            chunksize=250_000,
            low_memory=False,
        ):
            chunk = chunk.rename(
                columns={
                    "Year": "year",
                    "Basin ID": "basin_id",
                    "Maximum wind speed": "wind_max",
                    "TC number": "tc_number",
                }
            )
            chunk["year"] = pd.to_numeric(chunk["year"], errors="coerce")
            chunk["basin_id"] = pd.to_numeric(chunk["basin_id"], errors="coerce")
            chunk["wind_max"] = _convert_wind_to_mps(chunk["wind_max"], wind_unit_in)
            chunk["tc_number"] = pd.to_numeric(chunk["tc_number"], errors="coerce")
            chunk = chunk[
                (chunk["basin_id"] == float(basin_id))
                & np.isfinite(chunk["year"])
                & np.isfinite(chunk["wind_max"])
                & np.isfinite(chunk["tc_number"])
            ]
            if chunk.empty:
                continue
            chunk["year_global"] = chunk["year"].astype(int) + (1000 * int(block_idx))

            grouped_year = chunk.groupby("year_global", as_index=False)["wind_max"].max()
            for row in grouped_year.itertuples(index=False):
                year_key = int(row.year_global)
                wind_val = float(row.wind_max)
                prev = year_max.get(year_key)
                if prev is None or wind_val > prev:
                    year_max[year_key] = wind_val

            grouped_track = chunk.groupby(["year_global", "tc_number"], as_index=False)["wind_max"].max()
            for row in grouped_track.itertuples(index=False):
                track_key = f"{int(block_idx)}_{int(row.year_global)}_{int(row.tc_number)}"
                wind_val = float(row.wind_max)
                prev = track_max.get(track_key)
                if prev is None or wind_val > prev:
                    track_max[track_key] = wind_val

    track_series = pd.Series(list(track_max.values()), dtype=float)
    year_series = pd.Series(list(year_max.values()), dtype=float)
    return {
        "track_series": track_series,
        "year_series": year_series,
        "track_count": int(len(track_max)),
        "year_count": int(len(year_max)),
    }


def _build_wind_distributions_from_parquet(
    parquet_path: Path,
    basin_id: int = 1,
    *,
    wind_unit_in: str = "m/s",
) -> dict[str, Any]:
    df = _normalize_storm_df(pd.read_parquet(parquet_path))
    df["wind_max"] = _convert_wind_to_mps(df["wind_max"], wind_unit_in)
    if "Basin ID" in df.columns:
        basin_values = pd.to_numeric(df["Basin ID"], errors="coerce")
        df = df[basin_values == float(basin_id)].copy()
    storm_track_max = df.groupby("track_id", as_index=False)["wind_max"].max()["wind_max"]
    storm_year_max = df.groupby("Year", as_index=False)["wind_max"].max()["wind_max"]
    return {
        "track_series": pd.Series(storm_track_max.to_numpy(dtype=float), dtype=float),
        "year_series": pd.Series(storm_year_max.to_numpy(dtype=float), dtype=float),
        "track_count": int(df["track_id"].nunique()),
        "year_count": int(df["Year"].nunique()),
    }


def _build_wind_histograms(
    storm_source: Path,
    cmcc_source: Path,
    *,
    wind_unit_in: str = "m/s",
) -> dict[str, Any]:
    if storm_source.is_dir():
        storm = _build_wind_distributions_from_txt(
            storm_source,
            "STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt",
            basin_id=1,
            wind_unit_in=wind_unit_in,
        )
    else:
        storm = _build_wind_distributions_from_parquet(storm_source, basin_id=1, wind_unit_in=wind_unit_in)

    if cmcc_source.is_dir():
        cmcc = _build_wind_distributions_from_txt(
            cmcc_source,
            "STORM_DATA_CMCC-CM2-VHR4_NA_1000_YEARS_*_IBTRACSDELTA.txt",
            basin_id=1,
            wind_unit_in=wind_unit_in,
        )
    else:
        cmcc = _build_wind_distributions_from_parquet(cmcc_source, basin_id=1, wind_unit_in=wind_unit_in)

    year_edges = _build_common_wind_edges(storm["year_series"], cmcc["year_series"], step_mps=WIND_BIN_STEP_MPS)
    track_edges = _build_common_wind_edges(storm["track_series"], cmcc["track_series"], step_mps=WIND_BIN_STEP_MPS)

    storm_out = {
        "track_max_hist": _histogram_percent(storm["track_series"], bins=track_edges, bin_step_mps=WIND_BIN_STEP_MPS),
        "year_max_hist": _histogram_percent(storm["year_series"], bins=year_edges, bin_step_mps=WIND_BIN_STEP_MPS),
        "track_count": int(storm["track_count"]),
        "year_count": int(storm["year_count"]),
    }
    cmcc_out = {
        "track_max_hist": _histogram_percent(cmcc["track_series"], bins=track_edges, bin_step_mps=WIND_BIN_STEP_MPS),
        "year_max_hist": _histogram_percent(cmcc["year_series"], bins=year_edges, bin_step_mps=WIND_BIN_STEP_MPS),
        "track_count": int(cmcc["track_count"]),
        "year_count": int(cmcc["year_count"]),
    }
    return {"storm": storm_out, "storm_cmcc": cmcc_out}


def _load_json_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _finite_series_from_cells(cells: list[dict[str, Any]], value_key: str) -> pd.Series:
    values: list[float] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        try:
            value = float(cell.get(value_key))
        except Exception:
            continue
        if np.isfinite(value):
            values.append(float(value))
    return pd.Series(values, dtype=float)


def _build_wind_histograms_from_wind_map_payload(payload: dict[str, Any]) -> dict[str, Any]:
    storm_cells = payload.get("storm", {}).get("cells") if isinstance(payload.get("storm"), dict) else None
    cmcc_cells = payload.get("storm_cmcc", {}).get("cells") if isinstance(payload.get("storm_cmcc"), dict) else None
    if not isinstance(storm_cells, list) or not isinstance(cmcc_cells, list):
        raise ValueError("Invalid wind map payload: missing storm/storm_cmcc cells")

    storm_track_series = _finite_series_from_cells(storm_cells, "event_max_wind_mps")
    cmcc_track_series = _finite_series_from_cells(cmcc_cells, "event_max_wind_mps")
    storm_year_series = _finite_series_from_cells(storm_cells, "mean_wind_mps")
    cmcc_year_series = _finite_series_from_cells(cmcc_cells, "mean_wind_mps")

    year_edges = _build_common_wind_edges(storm_year_series, cmcc_year_series, step_mps=WIND_BIN_STEP_MPS)
    track_edges = _build_common_wind_edges(storm_track_series, cmcc_track_series, step_mps=WIND_BIN_STEP_MPS)

    return {
        "storm": {
            "track_max_hist": _histogram_percent(storm_track_series, bins=track_edges, bin_step_mps=WIND_BIN_STEP_MPS),
            "year_max_hist": _histogram_percent(storm_year_series, bins=year_edges, bin_step_mps=WIND_BIN_STEP_MPS),
            "track_count": int(len(storm_track_series)),
            "year_count": int(len(storm_year_series)),
        },
        "storm_cmcc": {
            "track_max_hist": _histogram_percent(cmcc_track_series, bins=track_edges, bin_step_mps=WIND_BIN_STEP_MPS),
            "year_max_hist": _histogram_percent(cmcc_year_series, bins=year_edges, bin_step_mps=WIND_BIN_STEP_MPS),
            "track_count": int(len(cmcc_track_series)),
            "year_count": int(len(cmcc_year_series)),
        },
    }


def _mean_metric_from_cells(cells: list[dict[str, Any]], value_key: str) -> float:
    series = _finite_series_from_cells(cells, value_key)
    if series.empty:
        return float("nan")
    return float(series.mean())


def _build_zone_wind_comparison_table_from_wind_map_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    storm_payload = payload.get("storm") if isinstance(payload, dict) else None
    cmcc_payload = payload.get("storm_cmcc") if isinstance(payload, dict) else None
    storm_cells = storm_payload.get("cells") if isinstance(storm_payload, dict) else None
    cmcc_cells = cmcc_payload.get("cells") if isinstance(cmcc_payload, dict) else None
    if not isinstance(storm_cells, list) or not isinstance(cmcc_cells, list):
        return []

    rows: list[dict[str, Any]] = []
    scenarios = [
        ("mean_wind_mps", "Moyenne annuelle (m/s)"),
        ("rp50_wind_mps", "Temps de retour 50 ans (m/s)"),
        ("rp100_wind_mps", "Temps de retour 100 ans (m/s)"),
        ("event_max_wind_mps", "Evenement le plus fort (m/s)"),
    ]
    for metric_key, label in scenarios:
        storm_value = _mean_metric_from_cells(storm_cells, metric_key)
        cmcc_value = _mean_metric_from_cells(cmcc_cells, metric_key)
        if not np.isfinite(storm_value) or not np.isfinite(cmcc_value):
            continue
        rows.append(
            {
                "indicator": f"Vents - {label}",
                "storm": round(float(storm_value), 4),
                "storm_cmcc": round(float(cmcc_value), 4),
                "delta": round(float(cmcc_value - storm_value), 4),
            }
        )
    return rows


def _line_length_km(gdf: gpd.GeoDataFrame) -> float:
    _, gdf_metric = _as_wgs84_and_metric(gdf)
    total_m = float(gdf_metric.geometry.length.fillna(0.0).sum())
    return max(0.0, total_m / 1000.0)


def _count_features(paths: list[Path], case_cfg: dict[str, Any]) -> int:
    count = 0
    for path in paths:
        gdf = _clip_case_gdf(_read_vector(path), case_cfg)
        count += int(len(gdf))
    return count


def _count_aep_ouvrage_types(case_cfg: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for src in case_cfg["aep_ouvrage_sources"]:
        mode = str(src.get("mode", "")).strip().lower()
        for path in src["paths"]:
            gdf = _read_vector(path, source_crs=str(src.get("source_crs", "") or "") or None)
            gdf = _clip_case_gdf(gdf, case_cfg)
            if gdf.empty:
                continue
            if mode == "fixed_type":
                code = str(src.get("ovrg_type", "NA") or "NA").strip().upper()
                counts[code] += int(len(gdf))
                continue
            col = str(src.get("field_name", "ovrg_type"))
            if col in gdf.columns:
                value_counts = gdf[col].fillna("NA").astype(str).str.upper().value_counts().to_dict()
                for k, v in value_counts.items():
                    counts[str(k)] += int(v)
            else:
                counts["NA"] += int(len(gdf))
    return counts


def _hydraulic_asset_value_code(row: Any) -> str:
    feature_role = str(getattr(row, "feature_role", "") or "").strip().lower()
    asset_type_code = str(getattr(row, "asset_type_code", "") or "").strip().upper()
    if feature_role == "captage_aep":
        return "CAP"
    if feature_role == "upep_aep":
        return "TRAIT"
    if feature_role == "pompage_aep":
        return "STPMP"
    if feature_role == "reservoir_aep":
        return "CUV"
    if feature_role == "ouvrage_eau_brute_aep":
        return "OUVEB"
    return asset_type_code or "NA"


def _build_hydraulic_water_exposure_metrics(case_cfg: dict[str, Any], territory: str) -> dict[str, Any]:
    lengths_km = {"eau_aep": 0.0, "eau_eu": 0.0}
    water_lines_total = 0
    aep_type_counts: dict[str, int] = defaultdict(int)
    eu_pr_total = 0
    eu_step_total = 0

    for src in case_cfg.get("hydraulic_zone_sources", []):
        bundle_path = Path(src["path"])
        lines_gdf = _clip_case_gdf(_read_vector(bundle_path, layer=str(src["line_layer"])), case_cfg)
        if not lines_gdf.empty:
            water_lines_total += int(len(lines_gdf))
            for network_kind, group in lines_gdf.groupby("network_kind", dropna=False):
                network_kind_upper = str(network_kind or "").strip().upper()
                if network_kind_upper == "AEP":
                    lengths_km["eau_aep"] += _line_length_km(group)
                elif network_kind_upper == "EU":
                    lengths_km["eau_eu"] += _line_length_km(group)

        assets_gdf = _clip_case_gdf(_read_vector(bundle_path, layer=str(src["asset_layer"])), case_cfg)
        if assets_gdf.empty:
            continue
        for row in assets_gdf.itertuples(index=False):
            network_kind_upper = str(getattr(row, "network_kind", "") or "").strip().upper()
            feature_role = str(getattr(row, "feature_role", "") or "").strip().lower()
            if network_kind_upper == "EU":
                if feature_role == "poste_refoulement":
                    eu_pr_total += 1
                elif feature_role == "step":
                    eu_step_total += 1
            elif network_kind_upper == "AEP":
                aep_type_counts[_hydraulic_asset_value_code(row)] += 1

    water_values = get_water_values(territory)
    return {
        "lengths_km": {k: round(float(v), 3) for k, v in lengths_km.items()},
        "water_lines_total": int(water_lines_total),
        "aep_type_counts": {str(k): int(v) for k, v in aep_type_counts.items()},
        "eu_pr_total": int(eu_pr_total),
        "eu_step_total": int(eu_step_total),
        "total_value_network": {
            "eau_aep": round(float(lengths_km["eau_aep"]) * float(water_values["eau_aep"]), 2),
            "eau_eu": round(float(lengths_km["eau_eu"]) * float(water_values["eau_eu"]), 2),
        },
        "total_value_aep_ouvrages": round(
            sum(
                get_aep_ouvrage_value_for_territory(territory, code) * int(count)
                for code, count in aep_type_counts.items()
            ),
            2,
        ),
        "total_value_pr": round(float(eu_pr_total) * float(water_values["eau_eu_pr"]), 2),
        "total_value_step": round(float(eu_step_total) * float(water_values["eau_eu_step"]), 2),
    }


def _build_exposure_metrics(case_cfg: dict[str, Any], territory: str) -> dict[str, Any]:
    lengths_km = {
        "elec_bt_aerien": 0.0,
        "elec_bt_souterrain": 0.0,
        "elec_hta_aerien": 0.0,
        "elec_hta_souterrain": 0.0,
        "eau_aep": 0.0,
        "eau_eu": 0.0,
    }

    elec_lines_total = 0
    water_lines_total = 0

    for src in case_cfg["elec_line_sources"]:
        class_key = str(src["class_key"])
        for path in src["paths"]:
            gdf = _clip_case_gdf(
                _read_vector(path, source_crs=str(src.get("source_crs", "") or "") or None),
                case_cfg,
            )
            if gdf.empty:
                continue
            lengths_km[class_key] += _line_length_km(gdf)
            elec_lines_total += int(len(gdf))

    value_per_km = get_network_values_per_km(territory)
    hydraulic_water_metrics = _build_hydraulic_water_exposure_metrics(case_cfg, territory)
    lengths_km["eau_aep"] = float(hydraulic_water_metrics["lengths_km"]["eau_aep"])
    lengths_km["eau_eu"] = float(hydraulic_water_metrics["lengths_km"]["eau_eu"])
    water_lines_total = int(hydraulic_water_metrics["water_lines_total"])

    total_value_network = {key: round(lengths_km[key] * value_per_km[key], 2) for key in value_per_km.keys()}
    total_value_network["eau_aep"] = float(hydraulic_water_metrics["total_value_network"]["eau_aep"])
    total_value_network["eau_eu"] = float(hydraulic_water_metrics["total_value_network"]["eau_eu"])

    aep_type_counts = dict(hydraulic_water_metrics["aep_type_counts"])
    total_value_aep_ouvr = float(hydraulic_water_metrics["total_value_aep_ouvrages"])
    eu_pr_total = int(hydraulic_water_metrics["eu_pr_total"])
    eu_step_total = int(hydraulic_water_metrics["eu_step_total"])
    total_value_pr = float(hydraulic_water_metrics["total_value_pr"])
    total_value_step = float(hydraulic_water_metrics["total_value_step"])

    aep_ouvrages_total = int(sum(int(v) for v in aep_type_counts.values()))
    counts = {
        "aep_ouvrages_total": aep_ouvrages_total,
        "aep_ouvrages_by_type": {str(k): int(v) for k, v in aep_type_counts.items()},
        "eu_pr_total": int(eu_pr_total),
        "eu_step_total": int(eu_step_total),
        "elec_lines_total": int(elec_lines_total),
        "water_lines_total": int(water_lines_total),
    }

    total_value_by_type = {
        **total_value_network,
        "eau_aep_ouvrages": total_value_aep_ouvr,
        "eau_eu_pr": total_value_pr,
        "eau_eu_step": total_value_step,
    }
    total_value_all = round(sum(total_value_by_type.values()), 2)

    territory_name = territory_label(territory)
    summary_text = (
        f"Le jeu de reference {territory_name} comprend {counts['elec_lines_total']} troncons electriques et {counts['water_lines_total']} troncons d'eau. "
        f"Longueurs reseaux: BT aerien {lengths_km['elec_bt_aerien']:.1f} km, BT souterrain {lengths_km['elec_bt_souterrain']:.1f} km, "
        f"HTA aerien {lengths_km['elec_hta_aerien']:.1f} km, HTA souterrain {lengths_km['elec_hta_souterrain']:.1f} km, "
        f"AEP {lengths_km['eau_aep']:.1f} km, EU {lengths_km['eau_eu']:.1f} km. "
        f"Ouvrages eau: {counts['aep_ouvrages_total']} AEP, {counts['eu_pr_total']} PR, {counts['eu_step_total']} STEP."
    )

    return {
        "summary_text": summary_text,
        "component_order": list(COMPONENT_ORDER),
        "lengths_km": {k: round(float(v), 3) for k, v in lengths_km.items()},
        "counts": counts,
        "value_per_km_eur": value_per_km,
        "total_value_by_type_eur": total_value_by_type,
        "total_value_all_eur": total_value_all,
        "valuation_metadata": build_valuation_metadata(territory),
    }


def _network_class_from_point(point_record: dict[str, Any]) -> str | None:
    return ASSET_TYPE_TO_NETWORK_CLASS.get(str(point_record.get("asset_type") or ""))


def _water_service_class_from_point(point_record: dict[str, Any]) -> str | None:
    asset_type = str(point_record.get("asset_type") or "")
    if asset_type.startswith("eau_aep"):
        return "eau_aep"
    if asset_type.startswith("eau_eu"):
        return "eau_eu"
    return None


def _water_service_feature_id_from_point(point_record: dict[str, Any]) -> str | None:
    water_service_class = _water_service_class_from_point(point_record)
    if water_service_class is None:
        return None
    service_feature_id = str(point_record.get("service_feature_id") or point_record.get("zone_component_key") or "").strip()
    if not service_feature_id:
        raise ValueError(
            f"Water dependency record requires service_feature_id/zone_component_key for {point_record.get('feature_id')}"
        )
    return service_feature_id


def _water_feature_role_from_point(point_record: dict[str, Any]) -> str:
    return str(point_record.get("feature_role") or "").strip().lower()


def _is_water_service_network_point(point_record: dict[str, Any]) -> bool:
    return _network_class_from_point(point_record) in {"eau_aep", "eau_eu"}


def _is_blocking_water_asset_point(point_record: dict[str, Any]) -> bool:
    water_service_class = _water_service_class_from_point(point_record)
    if water_service_class is None:
        return False
    if str(point_record.get("infra_class") or "").strip().lower() != "eau_ouvrage":
        return False
    return _water_feature_role_from_point(point_record) in WATER_BLOCKING_ROLES_BY_SERVICE.get(
        water_service_class,
        frozenset(),
    )


def _breakdown_class_from_point(point_record: dict[str, Any]) -> str | None:
    asset_type = str(point_record.get("asset_type") or "")
    if asset_type.startswith("eau_aep_ouvrage_"):
        return "eau_aep_ouvrages"
    if asset_type == "eau_eu_pr":
        return "eau_eu_pr"
    if asset_type == "eau_eu_step":
        return "eau_eu_step"
    return ASSET_TYPE_TO_NETWORK_CLASS.get(asset_type)


def _public_state_feature_id(point_record: dict[str, Any]) -> str:
    class_key = _network_class_from_point(point_record)
    if class_key in {"eau_aep", "eau_eu"}:
        service_feature_id = str(point_record.get("service_feature_id") or point_record.get("zone_component_key") or "").strip()
        if not service_feature_id:
            raise ValueError(
                f"Water public state feature requires service_feature_id/zone_component_key for {point_record.get('feature_id')}"
            )
        return service_feature_id
    return str(point_record.get("feature_id") or "")


def _electric_native_unit_id_from_point(point_record: dict[str, Any]) -> str:
    lat = point_record.get("lat")
    lon = point_record.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        lat_bin = round(float(lat) / ELECTRIC_NATIVE_GRID_DEG) * ELECTRIC_NATIVE_GRID_DEG
        lon_bin = round(float(lon) / ELECTRIC_NATIVE_GRID_DEG) * ELECTRIC_NATIVE_GRID_DEG
        return f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}"
    return str(point_record.get("territory_id") or point_record.get("feature_id") or "")


def _grid_geometry_from_cell_id(cell_id: str):
    text = str(cell_id or "").strip()
    if not text.startswith("cell-") or "_" not in text or box is None:
        return None
    try:
        lat_txt, lon_txt = text[5:].split("_", 1)
        lat = float(lat_txt)
        lon = float(lon_txt)
    except ValueError:
        return None
    half = ELECTRIC_NATIVE_GRID_DEG / 2.0
    return box(lon - half, lat - half, lon + half, lat + half)


def _aggregate_native_service_states_for_public_map(
    *,
    bundle: ClimadaExposureBundle,
    values: np.ndarray,
    class_keys: list[str | None],
    water_service_classes: list[str | None],
    service_feature_ids: list[str | None],
    is_blocking_asset: list[bool],
    weights_km: np.ndarray,
    hazard_outputs: dict[str, Any],
) -> tuple[dict[str, dict[str, dict[str, str]]], set[str]]:
    native_states_by_hazard: dict[str, dict[str, dict[str, str]]] = {}
    electric_unit_ids: set[str] = set()
    point_records = list(bundle.point_records or [])
    electric_units = [
        _electric_native_unit_id_from_point(rec) if str(class_keys[idx] or "").startswith("elec_") else ""
        for idx, rec in enumerate(point_records)
    ]

    for hazard_key, hazard_payload in hazard_outputs.items():
        scenario_results = hazard_payload.get("scenario_results") if isinstance(hazard_payload, dict) else None
        if not isinstance(scenario_results, dict):
            continue
        native_states_by_hazard[hazard_key] = {}
        for public_scenario in PUBLIC_MAP_SCENARIOS:
            scenario_key = _public_loss_scenario_source(public_scenario)
            scenario_result = scenario_results.get(scenario_key)
            if not isinstance(scenario_result, dict):
                raise RuntimeError(f"Missing scenario results for {hazard_key}.{public_scenario}")
            direct_loss = np.asarray(scenario_result.get("total_loss"), dtype=float).reshape(-1)
            direct_state = np.asarray(scenario_result.get("direct_state"), dtype=object).reshape(-1)
            final_state = np.asarray(scenario_result.get("final_state"), dtype=object).reshape(-1)

            elec_buckets: dict[str, dict[str, float]] = defaultdict(_new_health_bucket)
            elec_exposure: dict[str, float] = defaultdict(float)
            elec_loss: dict[str, float] = defaultdict(float)
            water_exposure: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            water_loss: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            water_lat_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            water_lon_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            water_count: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            blocking_state_by_service: dict[str, str] = {}

            for idx, rec in enumerate(point_records):
                class_key = class_keys[idx]
                water_service_class = water_service_classes[idx]
                if isinstance(class_key, str) and class_key.startswith("elec_"):
                    unit_id = electric_units[idx]
                    if not unit_id:
                        continue
                    electric_unit_ids.add(unit_id)
                    _add_state(elec_buckets[unit_id], str(direct_state[idx]), float(weights_km[idx]))
                    elec_exposure[unit_id] += float(values[idx])
                    elec_loss[unit_id] += float(direct_loss[idx])
                    continue

                if water_service_class not in {"eau_aep", "eau_eu"}:
                    continue
                service_unit_id = str(service_feature_ids[idx] or "").strip() or str(rec.get("territory_id") or "")
                if not service_unit_id:
                    continue
                water_exposure[water_service_class][service_unit_id] += float(values[idx])
                water_loss[water_service_class][service_unit_id] += float(direct_loss[idx])
                lat = rec.get("lat")
                lon = rec.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    water_lat_sum[water_service_class][service_unit_id] += float(lat)
                    water_lon_sum[water_service_class][service_unit_id] += float(lon)
                    water_count[water_service_class][service_unit_id] += 1.0
                if is_blocking_asset[idx]:
                    current_state = blocking_state_by_service.get(service_unit_id, "S0")
                    candidate_state = str(final_state[idx])
                    if STATE_ORDER.get(candidate_state, 0) > STATE_ORDER.get(current_state, 0):
                        blocking_state_by_service[service_unit_id] = candidate_state

            elec_health = {unit_id: _health(bucket) for unit_id, bucket in elec_buckets.items()}
            global_elec_health = _health(_merge_buckets(list(elec_buckets.values())))

            scenario_state_map: dict[str, str] = {}
            for unit_id, exposure_value in elec_exposure.items():
                ratio = float(elec_loss[unit_id]) / max(float(exposure_value), 1.0)
                scenario_state_map[unit_id] = _state_from_ratio(ratio)

            for water_service_class in ("eau_aep", "eau_eu"):
                for service_unit_id, exposure_value in water_exposure[water_service_class].items():
                    ratio = float(water_loss[water_service_class][service_unit_id]) / max(float(exposure_value), 1.0)
                    state_code = _state_from_ratio(ratio)
                    count = float(water_count[water_service_class].get(service_unit_id, 0.0))
                    elec_unit_id = ""
                    if count > 0.0:
                        lat = float(water_lat_sum[water_service_class][service_unit_id]) / count
                        lon = float(water_lon_sum[water_service_class][service_unit_id]) / count
                        elec_unit_id = _electric_native_unit_id_from_point({"lat": lat, "lon": lon})
                    dep_state = _dependency_state_from_elec_health(
                        elec_health.get(elec_unit_id, global_elec_health)
                    )
                    if STATE_ORDER[dep_state] > STATE_ORDER[state_code]:
                        state_code = dep_state
                    blocker_state = blocking_state_by_service.get(service_unit_id)
                    if blocker_state and STATE_ORDER[blocker_state] > STATE_ORDER[state_code]:
                        state_code = blocker_state
                    scenario_state_map[service_unit_id] = state_code

            native_states_by_hazard[hazard_key][public_scenario] = scenario_state_map

    return native_states_by_hazard, electric_unit_ids


def _hydraulic_zone_class_key(network_kind: str) -> str:
    network_kind_upper = str(network_kind or "").strip().upper()
    if network_kind_upper == "AEP":
        return "eau_aep"
    if network_kind_upper == "EU":
        return "eau_eu"
    raise ValueError(f"Unsupported hydraulic network_kind for public state geometry: {network_kind!r}")

def _hydraulic_asset_class_key(feature_role: str, network_kind: str) -> str:
    feature_role_text = str(feature_role or "").strip().lower()
    network_kind_upper = str(network_kind or "").strip().upper()
    if feature_role_text == "poste_refoulement":
        return "eau_eu_pr"
    if feature_role_text == "step":
        return "eau_eu_step"
    if network_kind_upper == "AEP":
        return "eau_aep_ouvrages"
    raise ValueError(
        f"Unsupported hydraulic asset for public state geometry: feature_role={feature_role!r} network_kind={network_kind!r}"
    )


def _hydraulic_native_service_feature_id(feature_id: str) -> str:
    return f"{HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX}:{feature_id}"


def _sorted_non_empty_text_values(series: Any) -> list[str]:
    values: list[str] = []
    for raw_value in getattr(series, "tolist", lambda: list(series))():
        text = str(raw_value or "").strip()
        if text:
            values.append(text)
    return sorted(set(values))


def _hydraulic_zone_service_ids_align_with_lines(
    zone_gdf,
    lines_gdf,
    *,
    network_kind: str,
) -> bool:
    zone_ids = set(
        _sorted_non_empty_text_values(
            zone_gdf.loc[zone_gdf["network_kind"] == network_kind, "zone_component_key"]
        )
    )
    line_ids = set(
        _sorted_non_empty_text_values(
            lines_gdf.loc[lines_gdf["network_kind"] == network_kind, "zone_component_key"]
        )
    )
    if not zone_ids or not line_ids:
        return True
    return bool(zone_ids & line_ids)


def _build_hydraulic_service_features_from_lines(
    lines_gdf,
    *,
    network_kind: str,
    class_labels: dict[str, str],
) -> list[dict[str, Any]]:
    if unary_union is None:
        raise RuntimeError("shapely.ops.unary_union is required to build hydraulic service geometries")

    groupable = lines_gdf.loc[
        (lines_gdf["network_kind"] == network_kind)
        & lines_gdf["zone_component_key"].notna()
        & (lines_gdf["zone_component_key"].astype(str).str.strip() != "")
    ].copy()
    if groupable.empty:
        return []

    class_key = _hydraulic_zone_class_key(network_kind)
    features: list[dict[str, Any]] = []
    for service_unit_id, group in groupable.groupby("zone_component_key", dropna=False):
        service_key = str(service_unit_id or "").strip()
        if not service_key:
            continue
        geometries = [geom for geom in group.geometry if geom is not None and not getattr(geom, "is_empty", False)]
        if not geometries:
            continue
        zone_uid_values = _sorted_non_empty_text_values(group["zone_uid"])
        zone_uid = zone_uid_values[0] if zone_uid_values else service_key
        merged_geometry = unary_union(geometries)
        features.append(
            {
                "feature_id": service_key,
                "class_key": class_key,
                "class_label": class_labels.get(class_key, class_key),
                "geometry": merged_geometry,
                "state_geometry_mode": "hydraulic_zoning_v2",
                "service_unit_kind": "hydraulic_zone_component",
                "service_feature_id": service_key,
                "zone_component_key": service_key,
                "zone_uid": zone_uid,
                "network_kind": network_kind,
                "feature_role": "canalisation",
            }
        )
    return features


def _build_network_geometry_features(
    case_cfg: dict[str, Any],
    *,
    electric_unit_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    class_labels = {**DAMAGE_BREAKDOWN_LABELS, **NETWORK_CLASS_LABELS}
    electric_feature_ids = sorted({str(unit_id) for unit_id in (electric_unit_ids or set()) if str(unit_id).strip()})

    def append_geometries(
        path: Path,
        class_key: str,
        prefix: str,
        source_idx: int,
        *,
        layer: str | None = None,
        source_crs: str | None = None,
    ) -> None:
        gdf = _clip_case_gdf(
            _read_vector(path, layer=layer, source_crs=source_crs),
            case_cfg,
        ).to_crs(WGS84)
        if gdf.empty:
            return
        for idx, geom in enumerate(gdf.geometry, start=1):
            if geom is None or getattr(geom, "is_empty", False):
                continue
            out.append(
                {
                    "feature_id": f"{prefix}-{source_idx}-{idx}",
                    "class_key": class_key,
                    "class_label": class_labels.get(class_key, class_key),
                    "geometry": geom,
                    "state_geometry_mode": "native_network_geometry",
                    "service_unit_kind": "native_feature",
                    "service_feature_id": "",
                    "zone_component_key": "",
                    "zone_uid": "",
                    "network_kind": "",
                    "feature_role": "",
                }
            )

    if electric_feature_ids:
        for unit_id in electric_feature_ids:
            geom = _grid_geometry_from_cell_id(unit_id)
            if geom is None:
                continue
            out.append(
                {
                    "feature_id": unit_id,
                    "class_key": "elec_grid_0p1deg",
                    "class_label": "Electricite agrégée 0.1°",
                    "geometry": geom,
                    "state_geometry_mode": "fixed_grid_0p1deg",
                    "service_unit_kind": "fixed_grid_0p1deg",
                    "service_feature_id": "",
                    "zone_component_key": "",
                    "zone_uid": "",
                    "network_kind": "ELEC",
                    "feature_role": "aggregated_service_grid",
                }
            )
    else:
        for src in case_cfg["network_geometry_sources"]:
            class_key = str(src["class_key"])
            if not class_key.startswith("elec_"):
                continue
            prefix = str(src["prefix"])
            for source_idx, path in enumerate(src["paths"], start=1):
                append_geometries(
                    path,
                    class_key,
                    prefix,
                    source_idx,
                    source_crs=str(src.get("source_crs", "") or "") or None,
                )

    for src in case_cfg.get("hydraulic_zone_sources", []):
        gdf = _clip_case_gdf(
            _read_vector(Path(src["path"]), layer=str(src["zone_layer"])),
            case_cfg,
        ).to_crs(WGS84)
        lines_gdf = _clip_case_gdf(
            _read_vector(Path(src["path"]), layer=str(src["line_layer"])),
            case_cfg,
        ).to_crs(WGS84)
        fallback_network_kinds: set[str] = set()
        if not gdf.empty and not lines_gdf.empty:
            for network_kind in _sorted_non_empty_text_values(gdf["network_kind"]):
                if not _hydraulic_zone_service_ids_align_with_lines(
                    gdf,
                    lines_gdf,
                    network_kind=network_kind,
                ):
                    fallback_network_kinds.add(network_kind)

        if not gdf.empty:
            for row in gdf.itertuples(index=False):
                geom = getattr(row, "geometry", None)
                if geom is None or getattr(geom, "is_empty", False):
                    continue
                network_kind = str(getattr(row, "network_kind", "") or "").strip()
                if network_kind in fallback_network_kinds:
                    continue
                feature_id = str(getattr(row, "zone_component_key", "") or "").strip()
                if not feature_id:
                    raise ValueError(f"Hydraulic public state geometry requires zone_component_key in {src['path']}")
                class_key = _hydraulic_zone_class_key(network_kind)
                out.append(
                    {
                        "feature_id": feature_id,
                        "class_key": class_key,
                        "class_label": class_labels.get(class_key, class_key),
                        "geometry": geom,
                        "state_geometry_mode": "hydraulic_zoning_v2",
                        "service_unit_kind": "hydraulic_zone_component",
                        "service_feature_id": feature_id,
                        "zone_component_key": feature_id,
                        "zone_uid": str(getattr(row, "zone_uid", "") or "").strip(),
                        "network_kind": network_kind,
                        "feature_role": "canalisation",
                    }
                )
        for network_kind in sorted(fallback_network_kinds):
            out.extend(
                _build_hydraulic_service_features_from_lines(
                    lines_gdf,
                    network_kind=network_kind,
                    class_labels=class_labels,
                )
            )
        if not lines_gdf.empty:
            for idx, row in enumerate(lines_gdf.itertuples(index=False), start=1):
                geom = getattr(row, "geometry", None)
                if geom is None or getattr(geom, "is_empty", False):
                    continue
                zone_component_key = str(getattr(row, "zone_component_key", "") or "").strip()
                if zone_component_key:
                    continue
                feature_id = str(
                    getattr(row, "feature_id", "")
                    or getattr(row, "source_feature_id", "")
                    or f"hydraulic-line-{idx}"
                ).strip()
                zone_uid = str(getattr(row, "zone_uid", "") or "").strip()
                if zone_uid:
                    raise ValueError(
                        f"Hydraulic public state geometry requires zone_component_key for assigned line {feature_id} in {src['path']}"
                    )
                network_kind = str(getattr(row, "network_kind", "") or "").strip()
                class_key = _hydraulic_zone_class_key(network_kind)
                service_feature_id = _hydraulic_native_service_feature_id(feature_id)
                out.append(
                    {
                        "feature_id": service_feature_id,
                        "class_key": class_key,
                        "class_label": class_labels.get(class_key, class_key),
                        "geometry": geom,
                        "state_geometry_mode": "native_network_geometry",
                        "service_unit_kind": "native_feature",
                        "service_feature_id": service_feature_id,
                        "zone_component_key": service_feature_id,
                        "zone_uid": "",
                        "network_kind": network_kind,
                        "feature_role": str(getattr(row, "feature_role", "") or "canalisation").strip(),
                    }
                )
        assets_gdf = _clip_case_gdf(
            _read_vector(Path(src["path"]), layer=str(src["asset_layer"])),
            case_cfg,
        ).to_crs(WGS84)
        if assets_gdf.empty:
            continue
        for idx, row in enumerate(assets_gdf.itertuples(index=False), start=1):
            geom = getattr(row, "geometry", None)
            if geom is None or getattr(geom, "is_empty", False):
                continue
            feature_id = str(
                getattr(row, "feature_id", "")
                or getattr(row, "source_feature_id", "")
                or f"hydraulic-asset-{idx}"
            ).strip()
            network_kind = str(getattr(row, "network_kind", "") or "").strip()
            feature_role = str(getattr(row, "feature_role", "") or "").strip()
            zone_component_key = str(getattr(row, "zone_component_key", "") or "").strip()
            service_feature_id = zone_component_key or _hydraulic_native_service_feature_id(feature_id)
            class_key = _hydraulic_asset_class_key(
                feature_role,
                network_kind,
            )
            out.append(
                {
                    "feature_id": feature_id,
                    "class_key": class_key,
                    "class_label": class_labels.get(class_key, class_key),
                    "geometry": geom,
                    "state_geometry_mode": "native_network_geometry",
                    "service_unit_kind": "native_feature",
                    "service_feature_id": service_feature_id,
                    "zone_component_key": service_feature_id,
                    "zone_uid": str(getattr(row, "zone_uid", "") or "").strip(),
                    "network_kind": network_kind,
                    "feature_role": feature_role,
                }
            )
    return out




def _normalize_component_ratio_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out = {comp: 0.0 for comp in COMPONENT_ORDER}
    source = raw or {}
    for comp in COMPONENT_ORDER:
        if comp not in source:
            continue
        try:
            out[comp] = max(0.0, float(source.get(comp) or 0.0))
        except Exception:
            out[comp] = 0.0
    total = sum(out.values())
    if total <= 0.0:
        return {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0}
    return {comp: out[comp] / total for comp in COMPONENT_ORDER}


def _default_component_ratios() -> dict[str, dict[str, dict[str, float]]]:
    base = {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0}
    return {
        hazard: {scenario: dict(base) for scenario in MAP_SCENARIOS}
        for hazard in ("storm", "storm_cmcc")
    }


def _combine_component_ratios_with_landslide(
    base_ratios: dict[str, Any] | None,
    *,
    non_landslide_total: float,
    landslide_total: float,
) -> dict[str, float]:
    non_landslide_total = max(0.0, float(non_landslide_total))
    landslide_total = max(0.0, float(landslide_total))
    normalized = _normalize_component_ratio_map(base_ratios or {})

    raw = {comp: 0.0 for comp in COMPONENT_ORDER}
    non_landslide_weight = sum(float(normalized.get(comp, 0.0)) for comp in ("wind", "rain", "surge"))
    if non_landslide_total > 0.0:
        if non_landslide_weight <= 0.0:
            non_landslide_shares = {"wind": 1.0, "rain": 0.0, "surge": 0.0}
        else:
            non_landslide_shares = {
                comp: float(normalized.get(comp, 0.0)) / non_landslide_weight
                for comp in ("wind", "rain", "surge")
            }
        for comp in ("wind", "rain", "surge"):
            raw[comp] = non_landslide_total * float(non_landslide_shares.get(comp, 0.0))
    raw["landslide"] = landslide_total
    return _normalize_component_ratio_map(raw)


def _extract_complete_analysis_source_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
    state_methodology = (
        meta.get("network_state_methodology")
        if isinstance(meta.get("network_state_methodology"), dict)
        else modeling.get("state_aggregation_metadata")
    )
    if not isinstance(state_methodology, dict):
        state_methodology = {}
    checkpoint_dir = str(modeling.get("sharding_checkpoint_dir") or "")
    match = re.search(r"/complete-analysis-runs/([^/]+)/", checkpoint_dir)
    run_id = match.group(1) if match else ""
    dynamic_max_tracks = {
        "storm": int(_safe_float(modeling.get("hazard_track_count_storm"), 0.0)),
        "storm_cmcc": int(_safe_float(modeling.get("hazard_track_count_storm_cmcc"), 0.0)),
    }
    return {
        "run_id": run_id or None,
        "generated_at": str(meta.get("updated_at") or "") or None,
        "sampling_spacing_m": float(_safe_float(meta.get("sampling_spacing_m"), 0.0)),
        "dynamic_max_tracks": dynamic_max_tracks,
        "network_state_methodology": dict(state_methodology),
        "network_state_methodology_breaks_comparability": bool(
            meta.get("network_state_methodology_breaks_comparability", bool(state_methodology))
        ),
    }


def _extract_complete_analysis_native_service_state_overlays(
    payload: dict[str, Any] | None,
) -> dict[str, dict[str, str]]:
    overlays: dict[str, dict[str, str]] = {
        "storm": {},
        "storm_cmcc": {},
    }
    territory_results = payload.get("territory_results") if isinstance(payload, dict) else None
    if not isinstance(territory_results, list):
        return overlays

    for territory_row in territory_results:
        if not isinstance(territory_row, dict):
            continue
        network_states_native = (
            territory_row.get("network_states_native")
            if isinstance(territory_row.get("network_states_native"), dict)
            else {}
        )
        for hazard_key in ("storm", "storm_cmcc"):
            hazard_states = (
                network_states_native.get(hazard_key)
                if isinstance(network_states_native.get(hazard_key), dict)
                else {}
            )
            for service_name in ("water_aep", "water_eu"):
                state_row = hazard_states.get(service_name)
                if not isinstance(state_row, dict):
                    continue
                service_unit_id = str(state_row.get("service_unit_id") or "").strip()
                state_code = str(state_row.get("state") or "").strip().upper()
                if not service_unit_id or state_code not in STATE_ORDER:
                    continue
                current_state = overlays[hazard_key].get(service_unit_id, "S0")
                if STATE_ORDER[state_code] > STATE_ORDER.get(current_state, 0):
                    overlays[hazard_key][service_unit_id] = state_code
    return overlays


def _overlay_complete_analysis_service_states_on_public_map(
    geometry_features: list[dict[str, Any]],
    hazard_feature_states: dict[str, dict[str, dict[str, str]]],
    *,
    complete_analysis_payload: dict[str, Any] | None,
) -> None:
    overlays = _extract_complete_analysis_native_service_state_overlays(complete_analysis_payload)
    if not any(overlays[hazard_key] for hazard_key in overlays):
        return

    scenario_keys = ("p99", "top10", "top5")
    service_name_for_class = {
        "eau_aep": "water_aep",
        "eau_eu": "water_eu",
    }
    fallback_state_by_hazard_and_class: dict[str, dict[str, str]] = {
        "storm": {},
        "storm_cmcc": {},
    }
    for hazard_key in ("storm", "storm_cmcc"):
        for class_key, service_name in service_name_for_class.items():
            service_states: dict[str, str] = {}
            territory_results = (
                complete_analysis_payload.get("territory_results")
                if isinstance(complete_analysis_payload, dict)
                else None
            )
            if not isinstance(territory_results, list):
                continue
            for territory_row in territory_results:
                if not isinstance(territory_row, dict):
                    continue
                native_by_hazard = (
                    territory_row.get("network_states_native")
                    if isinstance(territory_row.get("network_states_native"), dict)
                    else {}
                )
                hazard_states = native_by_hazard.get(hazard_key) if isinstance(native_by_hazard.get(hazard_key), dict) else {}
                state_row = hazard_states.get(service_name)
                if not isinstance(state_row, dict):
                    continue
                service_unit_id = str(state_row.get("service_unit_id") or "").strip()
                state_code = str(state_row.get("state") or "").strip().upper()
                if service_unit_id and state_code in STATE_ORDER:
                    service_states[service_unit_id] = state_code
            if len(service_states) == 1:
                fallback_state_by_hazard_and_class[hazard_key][class_key] = next(iter(service_states.values()))

    for feature in geometry_features:
        class_key = str(feature.get("class_key") or "").strip()
        if class_key not in {"eau_aep", "eau_eu"}:
            continue
        service_feature_id = str(feature.get("service_feature_id") or feature.get("feature_id") or "").strip()
        if not service_feature_id:
            continue
        for hazard_key in ("storm", "storm_cmcc"):
            state_code = overlays.get(hazard_key, {}).get(service_feature_id)
            if state_code not in STATE_ORDER:
                state_code = fallback_state_by_hazard_and_class.get(hazard_key, {}).get(class_key, "")
            if state_code not in STATE_ORDER:
                continue
            scenario_map = hazard_feature_states.get(hazard_key)
            if not isinstance(scenario_map, dict):
                continue
            for scenario_key in scenario_keys:
                feature_states = scenario_map.get(scenario_key)
                if isinstance(feature_states, dict):
                    feature_states[service_feature_id] = state_code


def _build_publication_trace(
    *,
    source_mode: str,
    fallback_reason: str | None,
    complete_analysis_source: dict[str, Any] | None,
    wind_map_meta: dict[str, Any] | None,
    proxy_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    complete_meta = complete_analysis_source if isinstance(complete_analysis_source, dict) else {}
    wind_meta = wind_map_meta if isinstance(wind_map_meta, dict) else {}
    proxy_meta_dict = proxy_meta if isinstance(proxy_meta, dict) else {}
    proxy_trace = (
        proxy_meta_dict.get("publication_trace")
        if isinstance(proxy_meta_dict.get("publication_trace"), dict)
        else {}
    )
    proxy_modeling = proxy_meta_dict.get("modeling") if isinstance(proxy_meta_dict.get("modeling"), dict) else {}
    return {
        "artifact_kind": "case_study_page_analysis",
        "source_mode": str(source_mode),
        "fallback_active": bool(fallback_reason),
        "fallback_reason": str(fallback_reason or "") or None,
        "complete_analysis_run_id": str(complete_meta.get("run_id") or "") or None,
        "complete_analysis_generated_at": str(complete_meta.get("generated_at") or "") or None,
        "wind_map_run_id": str(wind_meta.get("case_study_run_id") or "") or None,
        "wind_map_generated_at": str(wind_meta.get("generated_at") or "") or None,
        "multi_hazard_proxy_run_id": str(proxy_meta_dict.get("case_study_run_id") or "") or None,
        "multi_hazard_proxy_fallback_active": bool(
            proxy_trace.get("fallback_active") if proxy_trace else proxy_modeling.get("fallback")
        ),
        "multi_hazard_proxy_source_mode": str(
            proxy_trace.get("source_mode") if proxy_trace else proxy_modeling.get("source") or ""
        ) or None,
        "multi_hazard_proxy_fallback_reason": str(proxy_trace.get("fallback_reason") or "") or None,
    }


def _load_component_ratio_reference(path: Path | None) -> dict[str, dict[str, dict[str, float]]]:
    out = _default_component_ratios()
    if path is None or not path.exists():
        return out

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return out

    portfolio = payload.get('portfolio_results') if isinstance(payload, dict) else None
    if not isinstance(portfolio, dict):
        return out

    for hazard in ("storm", "storm_cmcc"):
        hazard_payload = portfolio.get(hazard)
        if not isinstance(hazard_payload, dict):
            continue

        annual_raw = hazard_payload.get('components_direct_eai_eur')
        if isinstance(annual_raw, dict):
            annual_clean = {k: v for k, v in annual_raw.items() if str(k) != 'combined_capped'}
            annual_ratio = _normalize_component_ratio_map(annual_clean)
            for scenario in ("annual", "rp50", "rp100", "top10", "top5"):
                out[hazard][scenario] = dict(annual_ratio)

        event_raw = hazard_payload.get('components_direct_percentile_99_loss_eur')
        if not isinstance(event_raw, dict):
            event_raw = hazard_payload.get('components_direct_max_event_loss_eur')
        if isinstance(event_raw, dict):
            event_ratio = _normalize_component_ratio_map(event_raw)
            out[hazard]['event_max'] = dict(event_ratio)
        elif isinstance(annual_raw, dict):
            annual_clean = {k: v for k, v in annual_raw.items() if str(k) != 'combined_capped'}
            out[hazard]['event_max'] = _normalize_component_ratio_map(annual_clean)

        out[hazard]['rp50'] = dict(out[hazard].get('rp100') or out[hazard].get('annual') or {"wind": 1.0, "rain": 0.0, "surge": 0.0})

    return out


def _normalize_breakdown_share_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out = {class_key: 0.0 for class_key in DAMAGE_BREAKDOWN_LABELS}
    source = raw or {}
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        if class_key not in source:
            continue
        try:
            out[class_key] = max(0.0, float(source.get(class_key) or 0.0))
        except Exception:
            out[class_key] = 0.0
    total = float(sum(out.values()))
    if total <= 0.0:
        return {}
    return {class_key: float(value) / total for class_key, value in out.items()}


def _default_multi_hazard_proxy(
    component_ratios_by_hazard: dict[str, dict[str, dict[str, float]]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    ratios = component_ratios_by_hazard or _default_component_ratios()
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for hazard in ("storm", "storm_cmcc"):
        out[hazard] = {
            "component_ratios": {
                scenario: _normalize_component_ratio_map((ratios.get(hazard) or {}).get(scenario))
                for scenario in MAP_SCENARIOS
            },
            "global_multipliers": {scenario: 1.0 for scenario in MAP_SCENARIOS},
            "breakdown_shares": {scenario: {} for scenario in MAP_SCENARIOS},
        }
    return out


def _load_multi_hazard_proxy(
    path: Path | None,
    component_ratios_by_hazard: dict[str, dict[str, dict[str, float]]] | None = None,
    *,
    strict: bool = False,
) -> dict[str, dict[str, dict[str, Any]]]:
    out = _default_multi_hazard_proxy(component_ratios_by_hazard)
    if path is None:
        if strict:
            raise FileNotFoundError("Missing multi-hazard proxy JSON path")
        return out
    if not path.exists():
        if strict:
            raise FileNotFoundError(f"Missing multi-hazard proxy JSON: {path}")
        return out

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Unable to parse multi-hazard proxy JSON {path}: {exc}") from exc
        return out

    hazards = payload.get("hazards") if isinstance(payload, dict) else None
    if not isinstance(hazards, dict):
        if strict:
            raise RuntimeError(f"Invalid multi-hazard proxy payload: missing hazards in {path}")
        return out

    if strict:
        meta = payload.get("meta") if isinstance(payload, dict) else None
        publication_trace = meta.get("publication_trace") if isinstance(meta, dict) else None
        if not isinstance(publication_trace, dict):
            raise RuntimeError(f"Invalid multi-hazard proxy payload: missing meta.publication_trace in {path}")
        if bool(publication_trace.get("fallback_active")):
            raise RuntimeError(f"Fallback multi-hazard proxy is forbidden: {path}")

    for hazard in ("storm", "storm_cmcc"):
        hazard_payload = hazards.get(hazard)
        if not isinstance(hazard_payload, dict):
            if strict:
                raise RuntimeError(f"Invalid multi-hazard proxy payload: missing hazard '{hazard}' in {path}")
            continue
        scenarios = hazard_payload.get("scenarios")
        if not isinstance(scenarios, dict):
            if strict:
                raise RuntimeError(f"Invalid multi-hazard proxy payload: missing scenarios for '{hazard}' in {path}")
            continue
        for scenario in MAP_SCENARIOS:
            scenario_payload = scenarios.get(scenario)
            if not isinstance(scenario_payload, dict):
                if strict:
                    raise RuntimeError(
                        f"Invalid multi-hazard proxy payload: missing scenario '{hazard}.{scenario}' in {path}"
                    )
                continue
            ratios = scenario_payload.get("component_ratios")
            if isinstance(ratios, dict):
                out[hazard]["component_ratios"][scenario] = _normalize_component_ratio_map(ratios)
            elif strict:
                raise RuntimeError(
                    f"Invalid multi-hazard proxy payload: missing component_ratios for '{hazard}.{scenario}' in {path}"
                )
            try:
                multiplier = float(scenario_payload.get("global_multiplier", 1.0) or 1.0)
            except Exception:
                multiplier = 1.0
            out[hazard]["global_multipliers"][scenario] = max(0.0, multiplier)
            shares = scenario_payload.get("breakdown_shares")
            if isinstance(shares, dict):
                out[hazard]["breakdown_shares"][scenario] = _normalize_breakdown_share_map(shares)

        annual_shares = dict(out[hazard]["breakdown_shares"].get("annual") or {})
        for scenario in MAP_SCENARIOS:
            if not out[hazard]["breakdown_shares"].get(scenario):
                out[hazard]["breakdown_shares"][scenario] = dict(annual_shares)

    return out


def _build_landslide_proxy_losses(
    exposure_bundle: ClimadaExposureBundle,
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
    del exposure_bundle, bbox
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
        scenario_arrays = {scenario: np.zeros_like(values, dtype=float) for scenario in MAP_SCENARIOS}
        source_paths: list[str] = []
        for source_name, source_path in sources:
            path = Path(source_path)
            if not path.exists():
                raise FileNotFoundError(f"Missing landslide raster for {hazard_key}/{source_name}: {path}")
            source_paths.append(str(path))
            class_values = _sample_raster_values_for_point_records(path, point_records)
            class_values = np.where(np.asarray(class_values, dtype=float).reshape(-1) > 1.0, class_values, 0.0)
            occurrence_rates = np.clip(class_values / max(float(settings.landslide_corr_fact), 1e-9), 0.0, 1.0)
            damage_ratios = np.interp(
                class_values,
                np.asarray(LANDSLIDE_INTENSITIES, dtype=float),
                np.asarray(LANDSLIDE_HYPOTHESIS_CURVE, dtype=float),
                left=0.0,
                right=float(LANDSLIDE_HYPOTHESIS_CURVE[-1]),
            )
            damage_amounts = np.minimum(np.maximum(values * damage_ratios, 0.0), values)
            annual = np.minimum(np.maximum(damage_amounts * occurrence_rates, 0.0), values)
            yearly_losses = _simulate_landslide_portfolio_yearly_losses(
                damage_amounts,
                occurrence_rates,
                n_years=int(settings.landslide_n_years),
                dist=str(settings.landslide_dist),
                seed=_stable_seed(territory, hazard_key, source_name, path.name),
            )
            yearly_freq = np.full(max(1, yearly_losses.size), 1.0 / max(1, yearly_losses.size), dtype=float)
            factors = scenario_loss_factors(
                SimpleNamespace(
                    aai_agg_eur=float(annual.sum()),
                    pml_eur={
                        50: _loss_at_return_period(yearly_losses, yearly_freq, 50.0),
                        100: _loss_at_return_period(yearly_losses, yearly_freq, 100.0),
                    },
                    max_event_loss_eur=float(np.max(yearly_losses)) if yearly_losses.size else 0.0,
                )
            )
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

        out[hazard_key] = {
            "scenario_arrays": scenario_arrays,
            "scenario_totals": {scenario: float(arr.sum()) for scenario, arr in scenario_arrays.items()},
            "source_paths": source_paths,
        }
    return out


def _sample_raster_values_for_point_records(
    path_sourcefile: Path,
    point_records: list[dict[str, Any]],
) -> np.ndarray:
    if gdal is None:
        raise RuntimeError("GDAL runtime is required for lightweight landslide raster sampling")

    dataset = gdal.Open(str(path_sourcefile))
    if dataset is None:
        raise FileNotFoundError(f"Unable to open landslide raster: {path_sourcefile}")

    band = dataset.GetRasterBand(1)
    if band is None:
        raise RuntimeError(f"Unable to read landslide raster band: {path_sourcefile}")
    width = int(dataset.RasterXSize)
    height = int(dataset.RasterYSize)
    raster_bytes = band.ReadRaster(
        0,
        0,
        width,
        height,
        buf_xsize=width,
        buf_ysize=height,
        buf_type=gdal.GDT_Float32,
    )
    if raster_bytes is None:
        raise RuntimeError(f"Unable to read landslide raster array: {path_sourcefile}")
    raster_arr = np.frombuffer(raster_bytes, dtype=np.float32).reshape(height, width).astype(float, copy=False)
    nodata = band.GetNoDataValue()

    geotransform = dataset.GetGeoTransform()
    if geotransform is None:
        raise RuntimeError(f"Missing geotransform for landslide raster: {path_sourcefile}")
    origin_x, pixel_width, rot_x, origin_y, rot_y, pixel_height = geotransform
    if abs(float(rot_x or 0.0)) > 1e-9 or abs(float(rot_y or 0.0)) > 1e-9:
        raise RuntimeError(f"Rotated landslide rasters are not supported for lightweight sampling: {path_sourcefile}")
    if float(pixel_width or 0.0) == 0.0 or float(pixel_height or 0.0) == 0.0:
        raise RuntimeError(f"Invalid pixel size in landslide raster: {path_sourcefile}")

    transform = None
    projection = str(dataset.GetProjection() or "").strip()
    if projection and osr is not None:
        try:
            source_srs = osr.SpatialReference()
            source_srs.ImportFromEPSG(4326)
            target_srs = osr.SpatialReference()
            target_srs.ImportFromWkt(projection)
            if not bool(source_srs.IsSame(target_srs)):
                transform = osr.CoordinateTransformation(source_srs, target_srs)
        except Exception:
            transform = None

    out = np.zeros(len(point_records), dtype=float)
    rows = int(raster_arr.shape[0])
    cols = int(raster_arr.shape[1]) if raster_arr.ndim >= 2 else 0
    for idx, record in enumerate(point_records):
        try:
            lon = float(record.get("lon"))
            lat = float(record.get("lat"))
        except Exception:
            continue
        if not np.isfinite(lon) or not np.isfinite(lat):
            continue

        x = lon
        y = lat
        if transform is not None:
            try:
                x_t, y_t, _ = transform.TransformPoint(float(lon), float(lat))
                x = float(x_t)
                y = float(y_t)
            except Exception:
                continue

        col = int(np.floor((x - float(origin_x)) / float(pixel_width)))
        row = int(np.floor((y - float(origin_y)) / float(pixel_height)))
        if row < 0 or row >= rows or col < 0 or col >= cols:
            continue
        value = float(raster_arr[row, col])
        if nodata is not None and abs(value - float(nodata)) <= 1e-9:
            continue
        if np.isfinite(value):
            out[idx] = value

    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _simulate_landslide_portfolio_yearly_losses(
    damage_amounts: np.ndarray,
    occurrence_rates: np.ndarray,
    *,
    n_years: int,
    dist: str,
    seed: int,
) -> np.ndarray:
    losses = np.asarray(damage_amounts, dtype=float).reshape(-1)
    rates = np.asarray(occurrence_rates, dtype=float).reshape(-1)
    if losses.size == 0 or rates.size == 0 or n_years <= 0:
        return np.zeros(0, dtype=float)

    rng = np.random.default_rng(int(seed))
    yearly = np.zeros(int(n_years), dtype=float)
    chunk_size = 2048
    dist_key = str(dist or "poisson").strip().lower()

    for start in range(0, losses.size, chunk_size):
        end = min(losses.size, start + chunk_size)
        chunk_losses = losses[start:end]
        chunk_rates = np.maximum(rates[start:end], 0.0)
        if dist_key == "poisson":
            draws = rng.poisson(chunk_rates.reshape(1, -1), size=(int(n_years), end - start))
            yearly += draws @ chunk_losses
        else:
            draws = rng.random((int(n_years), end - start)) < chunk_rates.reshape(1, -1)
            yearly += draws.astype(float) @ chunk_losses
    return yearly


def _component_ratios_from_climada_run(climada_run: Any) -> dict[str, dict[str, dict[str, float]]]:
    out = _default_component_ratios()
    component_hazards = getattr(climada_run, "component_hazards", {}) or {}

    for hazard in ("storm", "storm_cmcc"):
        hazard_components = component_hazards.get(hazard)
        if not isinstance(hazard_components, dict) or not hazard_components:
            continue

        annual_raw: dict[str, float] = {}
        event_raw: dict[str, float] = {}
        rp50_raw: dict[str, float] = {}
        rp100_raw: dict[str, float] = {}

        for component in COMPONENT_ORDER:
            comp_result = hazard_components.get(component)
            if comp_result is None:
                continue
            annual_raw[component] = float(np.asarray(getattr(comp_result, "eai_direct_by_point", []), dtype=float).sum())
            event_raw[component] = float(getattr(comp_result, "max_event_loss_eur", 0.0) or 0.0)
            pml = getattr(comp_result, "pml_eur", {}) or {}
            rp50_raw[component] = float(pml.get(50, 0.0) or 0.0)
            rp100_raw[component] = float(pml.get(100, 0.0) or 0.0)

        annual_ratio = _normalize_component_ratio_map(annual_raw)
        out[hazard]["annual"] = dict(annual_ratio)
        out[hazard]["top10"] = dict(annual_ratio)
        out[hazard]["top5"] = dict(annual_ratio)
        out[hazard]["rp100"] = _normalize_component_ratio_map(rp100_raw)
        rp50_ratio = _normalize_component_ratio_map(rp50_raw)
        out[hazard]["rp50"] = dict(rp50_ratio if any(float(v) > 0.0 for v in rp50_ratio.values()) else (out[hazard].get("rp100") or annual_ratio))
        out[hazard]["event_max"] = _normalize_component_ratio_map(event_raw)

    return out


def _pick_evenly_spaced_indices(indices: list[int], keep: int) -> list[int]:
    if keep <= 0 or not indices:
        return []
    if keep >= len(indices):
        return list(indices)
    if keep == 1:
        return [indices[0]]
    positions = np.linspace(0, len(indices) - 1, keep)
    selected: list[int] = []
    used: set[int] = set()
    for pos in positions:
        idx = indices[int(round(float(pos)))]
        if idx in used:
            continue
        selected.append(idx)
        used.add(idx)
    if len(selected) < keep:
        for idx in indices:
            if idx in used:
                continue
            selected.append(idx)
            used.add(idx)
            if len(selected) >= keep:
                break
    return selected[:keep]


def _subset_bundle_for_component_ratios(
    bundle: ClimadaExposureBundle,
    *,
    max_points_total: int,
    priority_scores: dict[int, float] | None = None,
) -> ClimadaExposureBundle:
    point_records = list(bundle.point_records or [])
    total = len(point_records)
    max_points_total = max(1, int(max_points_total))
    if total <= max_points_total:
        return bundle

    normalized_priority_scores: dict[int, float] = {}
    for idx, raw in (priority_scores or {}).items():
        try:
            score = float(raw)
        except Exception:
            continue
        if idx < 0 or idx >= total or not np.isfinite(score) or score <= 0.0:
            continue
        normalized_priority_scores[int(idx)] = score

    groups: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(point_records):
        asset_type = str(rec.get("asset_type") or "unknown").strip().lower()
        territory_id = str(rec.get("territory_id") or "unknown").strip().lower()
        groups[f"{asset_type}|{territory_id}"].append(idx)

    group_keys = sorted(groups.keys())
    base_alloc = {key: 1 for key in group_keys}
    remaining = max(0, max_points_total - sum(base_alloc.values()))
    total_points = sum(len(groups[key]) for key in group_keys)

    allocations: dict[str, int] = {}
    for key in group_keys:
        group_size = len(groups[key])
        extra = int(round((group_size / max(1, total_points)) * remaining)) if remaining > 0 else 0
        allocations[key] = min(group_size, base_alloc[key] + max(0, extra))

    allocated = sum(allocations.values())
    if allocated > max_points_total:
        overflow = allocated - max_points_total
        for key in sorted(group_keys, key=lambda item: allocations[item], reverse=True):
            if overflow <= 0:
                break
            reducible = max(0, allocations[key] - 1)
            if reducible <= 0:
                continue
            delta = min(reducible, overflow)
            allocations[key] -= delta
            overflow -= delta
    elif allocated < max_points_total:
        deficit = max_points_total - allocated
        for key in sorted(group_keys, key=lambda item: len(groups[item]), reverse=True):
            if deficit <= 0:
                break
            capacity = len(groups[key]) - allocations[key]
            if capacity <= 0:
                continue
            delta = min(capacity, deficit)
            allocations[key] += delta
            deficit -= delta

    selected_indices: list[int] = []
    for key in group_keys:
        indices = list(groups[key])
        keep = allocations[key]
        if keep <= 0:
            continue

        priority_indices = [
            idx for idx in indices
            if idx in normalized_priority_scores
        ]
        priority_indices.sort(
            key=lambda idx: (-normalized_priority_scores.get(idx, 0.0), idx)
        )
        if priority_indices:
            max_priority_keep = keep if keep <= 2 else max(1, int(np.ceil(keep * 0.4)))
            priority_keep = min(len(priority_indices), max_priority_keep)
        else:
            priority_keep = 0

        if priority_keep > 0:
            selected_indices.extend(priority_indices[:priority_keep])
        remaining = keep - priority_keep
        remaining_indices = [idx for idx in indices if idx not in normalized_priority_scores]
        selected_non_priority = _pick_evenly_spaced_indices(remaining_indices, remaining)
        selected_indices.extend(selected_non_priority)
        if len(selected_non_priority) < remaining:
            deficit = remaining - len(selected_non_priority)
            leftover_priority = [idx for idx in priority_indices[priority_keep:] if idx not in selected_indices]
            selected_indices.extend(leftover_priority[:deficit])
    selected_indices = sorted(set(selected_indices))[:max_points_total]

    subset_exposures = bundle.exposures.copy(deep=False)
    subset_exposures.set_gdf(
        bundle.exposures.gdf.iloc[selected_indices].reset_index(drop=True),
        crs=bundle.exposures.crs,
    )
    subset_point_records = [point_records[idx] for idx in selected_indices]
    return ClimadaExposureBundle(
        exposures=subset_exposures,
        point_records=subset_point_records,
        metric_crs=bundle.metric_crs,
        warnings=list(bundle.warnings or []) + [
            f"Component ratio bundle reduced from {total} to {len(subset_point_records)} points."
        ],
    )


def _allocate_damage_components(total_eur: float, ratios: dict[str, float] | None) -> dict[str, float]:
    cents_total = max(0, int(round(float(total_eur or 0.0) * 100.0)))
    if cents_total <= 0:
        return {comp: 0.0 for comp in COMPONENT_ORDER}

    normalized = _normalize_component_ratio_map(ratios or {})
    weights = [max(0.0, float(normalized.get(comp, 0.0))) for comp in COMPONENT_ORDER]
    weight_sum = float(sum(weights))
    if weight_sum <= 0.0:
        weights = [1.0, 0.0, 0.0, 0.0]
        weight_sum = 1.0

    cents_by_component: dict[str, int] = {}
    assigned = 0
    for idx, comp in enumerate(COMPONENT_ORDER):
        if idx == len(COMPONENT_ORDER) - 1:
            cents = max(0, cents_total - assigned)
        else:
            share = weights[idx] / weight_sum
            cents = int(round(cents_total * share))
            cents = max(0, min(cents_total - assigned, cents))
        cents_by_component[comp] = cents
        assigned += cents

    return {comp: round(cents_by_component.get(comp, 0) / 100.0, 2) for comp in COMPONENT_ORDER}


def _breakdown_share_map_from_losses(
    losses: np.ndarray,
    breakdown_class_keys: list[str | None],
) -> dict[str, float]:
    raw = {}
    arr = np.asarray(losses, dtype=float).reshape(-1)
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
        raw[class_key] = float(arr[mask].sum()) if mask.any() else 0.0
    return _normalize_breakdown_share_map(raw)


def _apply_multi_hazard_proxy_to_direct_losses(
    direct_loss: np.ndarray,
    *,
    values: np.ndarray,
    breakdown_class_keys: list[str | None],
    scenario: str,
    global_multipliers: dict[str, float] | None,
    breakdown_shares: dict[str, dict[str, float]] | None,
    component_ratios: dict[str, dict[str, float]] | None,
) -> np.ndarray:
    direct = np.minimum(np.maximum(np.asarray(direct_loss, dtype=float).reshape(-1), 0.0), values)

    scenario_key = str(scenario or "annual")
    multiplier_map = global_multipliers or {}
    try:
        global_multiplier = float(multiplier_map.get(scenario_key, multiplier_map.get("annual", 1.0)) or 1.0)
    except Exception:
        global_multiplier = 1.0
    global_multiplier = max(0.0, global_multiplier)

    shares_by_scenario = breakdown_shares or {}
    proxy_share_map = _normalize_breakdown_share_map(
        shares_by_scenario.get(scenario_key)
        if isinstance(shares_by_scenario, dict)
        else None
    )
    wind_share_map = _breakdown_share_map_from_losses(direct, breakdown_class_keys)
    if not proxy_share_map:
        share_map = dict(wind_share_map)
    else:
        ratio_map = _normalize_component_ratio_map(
            (component_ratios or {}).get(scenario_key)
            if isinstance(component_ratios, dict)
            else None
        )
        non_wind_weight = max(0.0, min(1.0, 1.0 - float(ratio_map.get("wind", 1.0))))
        if not wind_share_map:
            share_map = dict(proxy_share_map)
        elif non_wind_weight <= 0.0:
            share_map = dict(wind_share_map)
        else:
            blended = {
                class_key: (
                    (float(wind_share_map.get(class_key, 0.0)) * (1.0 - non_wind_weight))
                    + (float(proxy_share_map.get(class_key, 0.0)) * non_wind_weight)
                )
                for class_key in DAMAGE_BREAKDOWN_LABELS
            }
            share_map = _normalize_breakdown_share_map(blended) or dict(wind_share_map)

    present_mask = np.array([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
    current_total = float(direct[present_mask].sum()) if present_mask.any() else float(direct.sum())
    target_total = max(0.0, current_total * global_multiplier)
    if target_total <= 0.0:
        out = np.array(direct, dtype=float, copy=True)
        out[present_mask] = 0.0
        return out

    adjusted = np.array(direct, dtype=float, copy=True)
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
        if not mask.any():
            continue
        target_class_total = max(0.0, target_total * float(share_map.get(class_key, 0.0)))
        if target_class_total <= 0.0:
            adjusted[mask] = 0.0
            continue

        current_class_total = float(direct[mask].sum())
        if current_class_total > 0.0:
            adjusted[mask] = direct[mask] * (target_class_total / current_class_total)
            continue

        class_values = np.asarray(values[mask], dtype=float)
        class_capacity = float(class_values.sum())
        if class_capacity > 0.0:
            adjusted[mask] = class_values * (target_class_total / class_capacity)
        else:
            adjusted[mask] = target_class_total / float(max(1, int(mask.sum())))

    return np.minimum(np.maximum(adjusted, 0.0), values)

def _compute_impact_metrics(
    exposure: NormalizedExposure,
    *,
    spacing_m: float,
    settings: Any,
    network_value_per_km: dict[str, float],
    exposure_value_by_class: dict[str, float],
    territory: str,
    landslide_bbox: tuple[float, float, float, float],
    hazard_storm_path: Path,
    hazard_storm_cmcc_path: Path,
    component_ratios_by_hazard: dict[str, dict[str, dict[str, float]]] | None = None,
    multi_hazard_proxy: dict[str, dict[str, dict[str, Any]]] | None = None,
    complete_analysis_payload: dict[str, Any] | None = None,
    component_light_spacing_m: float = DEFAULT_COMPONENT_LIGHT_SPACING_M,
    component_light_max_points_total: int = DEFAULT_COMPONENT_LIGHT_MAX_POINTS_TOTAL,
    component_light_max_points_per_feature: int = DEFAULT_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE,
    component_light_dynamic_max_tracks: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise RuntimeError("Unable to instantiate CLIMADA impact functions")
    impfset = ImpactFuncSet(impact_funcs)

    disagg = summarize_disaggregation(
        exposure,
        spacing_m=spacing_m,
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=int(settings.climada_max_points_per_feature),
    )
    bundle = build_climada_exposure(
        exposure,
        spacing_m=spacing_m,
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=settings.climada_max_points_per_feature,
        impact_func_id_resolver=resolve_tc_impact_func_id,
    )

    values = np.array([float(rec["value_eur"]) for rec in bundle.point_records], dtype=float)
    territories = [str(rec["territory_id"]) for rec in bundle.point_records]
    feature_ids = [_public_state_feature_id(rec) for rec in bundle.point_records]
    class_keys = [_network_class_from_point(rec) for rec in bundle.point_records]
    breakdown_class_keys = [_breakdown_class_from_point(rec) for rec in bundle.point_records]
    water_service_classes = [_water_service_class_from_point(rec) for rec in bundle.point_records]
    service_feature_ids = [_water_service_feature_id_from_point(rec) for rec in bundle.point_records]
    is_service_network = [_is_water_service_network_point(rec) for rec in bundle.point_records]
    is_blocking_asset = [_is_blocking_water_asset_point(rec) for rec in bundle.point_records]
    weights_km = np.array(
        [
            (float(rec["value_eur"]) / network_value_per_km[class_key]) if class_key in network_value_per_km else 0.0
            for rec, class_key in zip(bundle.point_records, class_keys)
        ],
        dtype=float,
    )

    if component_ratios_by_hazard is None:
        component_ratios_by_hazard = _default_component_ratios()
    if multi_hazard_proxy is None:
        multi_hazard_proxy = _default_multi_hazard_proxy(component_ratios_by_hazard)
    landslide_proxy_losses = _build_landslide_proxy_losses(
        bundle,
        list(bundle.point_records or []),
        territory=territory,
        settings=settings,
        bbox=landslide_bbox,
    )

    hazard_outputs: dict[str, Any] = {}
    calibration_by_hazard: dict[str, dict[str, dict[str, float]]] = {}
    hazard_paths = {
        "storm": hazard_storm_path,
        "storm_cmcc": hazard_storm_cmcc_path,
    }
    for hazard_key, hazard_path in hazard_paths.items():
        hazard_obj = load_storm_hazard(hazard_path, settings.storm_years)
        impact = ImpactCalc(bundle.exposures, impfset, hazard_obj).impact(save_mat=False, assign_centroids=True)
        landslide_scenario_arrays = (landslide_proxy_losses.get(hazard_key) or {}).get("scenario_arrays") or {}
        wind_eai_direct = np.asarray(impact.eai_exp, dtype=float).reshape(-1)
        wind_at_event = np.asarray(impact.at_event, dtype=float).reshape(-1)
        eai_direct = np.asarray(wind_eai_direct, dtype=float).reshape(-1)
        eai_direct = np.nan_to_num(eai_direct, nan=0.0, posinf=0.0, neginf=0.0)
        eai_direct = np.minimum(np.maximum(eai_direct, 0.0), values)
        at_event = np.asarray(wind_at_event, dtype=float).reshape(-1)
        at_event = np.nan_to_num(at_event, nan=0.0, posinf=0.0, neginf=0.0)
        freq = np.asarray(
            getattr(hazard_obj, "frequency", np.array([])),
            dtype=float,
        ).reshape(-1)
        if freq.size != at_event.size or float(np.nansum(freq)) <= 0.0:
            freq = np.full(at_event.size, 1.0 / max(1, at_event.size), dtype=float)
        event_idx = int(np.argmax(at_event)) if len(at_event) else 0
        event_id_source = getattr(impact, "event_id", [])
        event_id_max = int(event_id_source[event_idx]) if len(event_id_source) else int(event_idx + 1)
        global_scenario_losses = {
            "event_max": float(at_event[event_idx]) if len(at_event) else 0.0,
            "rp50": _loss_at_return_period(at_event, freq, 50.0),
            "rp100": _loss_at_return_period(at_event, freq, 100.0),
            "top10": _mean_top_fraction(at_event, 0.10),
            "top5": _mean_top_fraction(at_event, 0.05),
        }
        global_eai = float(eai_direct.sum())
        global_scenario_factors = {
            scenario: (max(0.0, loss) / max(global_eai, 1e-9)) for scenario, loss in global_scenario_losses.items()
        }

        class_scenario_factors: dict[str, dict[str, float]] = {
            "event_max": {},
            "rp50": {},
            "rp100": {},
            "top10": {},
            "top5": {},
        }
        for class_key in GLOBAL_EVENT_CLASS_KEYS:
            class_mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
            class_eai = float(eai_direct[class_mask].sum())
            if class_eai <= 0.0 or not class_mask.any() or len(at_event) == 0:
                for scenario in class_scenario_factors:
                    class_scenario_factors[scenario][class_key] = 0.0
                continue

            subset = bundle.exposures.copy(deep=False)
            subset.set_gdf(
                bundle.exposures.gdf.iloc[np.where(class_mask)[0]].reset_index(drop=True),
                crs=bundle.exposures.crs,
            )
            class_impact = ImpactCalc(subset, impfset, hazard_obj).impact(save_mat=False, assign_centroids=True)
            class_at_event = np.asarray(class_impact.at_event, dtype=float).reshape(-1)
            class_at_event = np.nan_to_num(class_at_event, nan=0.0, posinf=0.0, neginf=0.0)
            class_total_value = float(values[class_mask].sum())
            class_at_event = np.minimum(np.maximum(class_at_event, 0.0), class_total_value)
            class_scenario_losses = {
                "event_max": float(class_at_event[event_idx]) if event_idx < len(class_at_event) else 0.0,
                "rp50": _loss_at_return_period(class_at_event, freq, 50.0),
                "rp100": _loss_at_return_period(class_at_event, freq, 100.0),
                "top10": _mean_top_fraction(class_at_event, 0.10),
                "top5": _mean_top_fraction(class_at_event, 0.05),
            }
            for scenario, scenario_loss in class_scenario_losses.items():
                class_scenario_factors[scenario][class_key] = max(0.0, float(scenario_loss)) / max(class_eai, 1e-9)
            del class_impact
            del subset
            gc.collect()

        direct_losses_by_scenario: dict[str, np.ndarray] = {"annual": np.array(eai_direct, dtype=float)}
        for scenario in ("event_max", "rp50", "rp100", "top10", "top5"):
            scenario_direct = np.zeros_like(eai_direct, dtype=float)
            for i, bclass in enumerate(breakdown_class_keys):
                factor = class_scenario_factors[scenario].get(str(bclass), global_scenario_factors[scenario])
                scenario_direct[i] = float(eai_direct[i]) * max(0.0, float(factor))
            direct_losses_by_scenario[scenario] = np.minimum(np.maximum(scenario_direct, 0.0), values)

        for scenario, landslide_values in landslide_scenario_arrays.items():
            landslide_arr = np.asarray(landslide_values, dtype=float).reshape(-1)
            if not landslide_arr.size:
                continue
            combined = np.array(direct_losses_by_scenario.get(scenario, np.zeros_like(eai_direct, dtype=float)), dtype=float, copy=True)
            n = min(combined.size, landslide_arr.size, values.size)
            if n <= 0:
                continue
            combined[:n] = np.minimum(
                np.maximum(combined[:n] + landslide_arr[:n], 0.0),
                values[:n],
            )
            direct_losses_by_scenario[scenario] = combined

        def evaluate_scenario(direct_loss: np.ndarray) -> dict[str, Any]:
            return _evaluate_network_dependency_scenario(
                direct_loss=direct_loss,
                values=values,
                class_keys=class_keys,
                territories=territories,
                weights_km=weights_km,
                water_service_classes=water_service_classes,
                service_feature_ids=service_feature_ids,
                is_service_network=is_service_network,
                is_blocking_asset=is_blocking_asset,
            )

        hazard_proxy = (multi_hazard_proxy or {}).get(hazard_key, {}) if isinstance(multi_hazard_proxy, dict) else {}
        scenario_component_ratios = (
            hazard_proxy.get("component_ratios")
            if isinstance(hazard_proxy, dict)
            else None
        ) or (component_ratios_by_hazard or {}).get(hazard_key, {})
        scenario_global_multipliers = (
            hazard_proxy.get("global_multipliers")
            if isinstance(hazard_proxy, dict)
            else None
        ) or {}
        scenario_breakdown_shares = (
            hazard_proxy.get("breakdown_shares")
            if isinstance(hazard_proxy, dict)
            else None
        ) or {}
        scenario_results = {
            scenario: evaluate_scenario(
                _apply_multi_hazard_proxy_to_direct_losses(
                    direct_losses_by_scenario[scenario],
                    values=values,
                    breakdown_class_keys=breakdown_class_keys,
                    scenario=scenario,
                    global_multipliers=scenario_global_multipliers,
                    breakdown_shares=scenario_breakdown_shares,
                    component_ratios=scenario_component_ratios if isinstance(scenario_component_ratios, dict) else None,
                )
            )
            for scenario in MAP_SCENARIOS
        }

        all_infra_mask = np.array([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
        applied_calibration = _calibrate_scenario_results_to_complete_analysis(
            scenario_results,
            values=values,
            all_infra_mask=all_infra_mask,
            target_totals=_extract_complete_analysis_public_loss_targets(complete_analysis_payload, hazard_key),
        )
        if applied_calibration:
            calibration_by_hazard[hazard_key] = applied_calibration
            _recalculate_calibrated_scenario_states(
                scenario_results,
                scenario_keys=tuple(applied_calibration.keys()),
                values_size=int(values.size),
                evaluator=evaluate_scenario,
            )

        rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in TABLE_SCENARIOS:
            source_scenario = _public_loss_scenario_source(scenario)
            rows: list[dict[str, Any]] = []
            for network_class_key, label in NETWORK_CLASS_LABELS.items():
                mask = np.array([ck == network_class_key for ck in class_keys], dtype=bool)
                total_w = float(weights_km[mask].sum())
                class_exposure = round(float(exposure_value_by_class.get(network_class_key, 0.0)), 2)
                if total_w <= 0.0:
                    state_pct = {s: 0.0 for s in ("S0", "S1", "S2", "S3")}
                    damage_val = 0.0
                else:
                    state_pct = {
                        s: round(
                            float(weights_km[mask & (scenario_results[source_scenario]["final_state"] == s)].sum())
                            / total_w
                            * 100.0,
                            3,
                        )
                        for s in ("S0", "S1", "S2", "S3")
                    }
                    damage_val = round(float(scenario_results[source_scenario]["total_loss"][mask].sum()), 2)
                direct_val = round(
                    float(
                        np.minimum(
                            scenario_results[source_scenario]["direct_loss"],
                            scenario_results[source_scenario]["total_loss"],
                        )[mask].sum()
                    ),
                    2,
                )
                indirect_val = round(max(float(damage_val) - float(direct_val), 0.0), 2)
                component_ratios = _normalize_component_ratio_map(
                    scenario_component_ratios.get(source_scenario) if isinstance(scenario_component_ratios, dict) else None
                )
                damage_components = _allocate_damage_components(damage_val, component_ratios)
                rows.append(
                    {
                        "class_key": network_class_key,
                        "class_label": label,
                        "exposure_eur": class_exposure,
                        "state_pct": state_pct,
                        "damage_eur": damage_val,
                        "direct_damage_eur": direct_val,
                        "indirect_damage_eur": indirect_val,
                        "damage_components_eur": damage_components,
                    }
                )
            rows_by_scenario[scenario] = rows

        breakdown_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in MAP_SCENARIOS:
            breakdown_rows: list[dict[str, Any]] = []
            for breakdown_class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
                mask = np.array([ck == breakdown_class_key for ck in breakdown_class_keys], dtype=bool)
                damage_val = round(float(scenario_results[scenario]["total_loss"][mask].sum()), 2)
                direct_val = round(
                    float(
                        np.minimum(
                            scenario_results[scenario]["direct_loss"],
                            scenario_results[scenario]["total_loss"],
                        )[mask].sum()
                    ),
                    2,
                )
                indirect_val = round(max(float(damage_val) - float(direct_val), 0.0), 2)
                component_ratios = _normalize_component_ratio_map(
                    scenario_component_ratios.get(scenario) if isinstance(scenario_component_ratios, dict) else None
                )
                breakdown_rows.append(
                    {
                        "class_key": breakdown_class_key,
                        "class_label": label,
                        "exposure_eur": round(float(exposure_value_by_class.get(breakdown_class_key, 0.0)), 2),
                        "damage_eur": damage_val,
                        "direct_damage_eur": direct_val,
                        "indirect_damage_eur": indirect_val,
                        "damage_components_eur": _allocate_damage_components(damage_val, component_ratios),
                    }
                )
            breakdown_by_scenario[scenario] = breakdown_rows

        network_mask = np.array([ck in NETWORK_CLASS_LABELS for ck in class_keys], dtype=bool)
        network_total_w = float(weights_km[network_mask].sum())

        direct_s3_annual = float(weights_km[network_mask & (scenario_results["annual"]["direct_state"] == "S3")].sum())
        direct_s3_event = float(weights_km[network_mask & (scenario_results["event_max"]["direct_state"] == "S3")].sum())
        indirect_s3_annual = float(weights_km[network_mask & scenario_results["annual"]["indirect_s3_flag"]].sum())
        indirect_s3_event = float(weights_km[network_mask & scenario_results["event_max"]["indirect_s3_flag"]].sum())

        hazard_outputs[hazard_key] = {
            "rows_by_scenario": rows_by_scenario,
            "breakdown_by_scenario": breakdown_by_scenario,
            "scenario_results": scenario_results,
            "summary": {
                "direct_hs_pct_annual": round((direct_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "direct_hs_pct_p99": round((direct_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_annual": round((indirect_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_p99": round((indirect_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "eai_total_eur": round(float(scenario_results["annual"]["total_loss"][all_infra_mask].sum()), 2),
                "rp50_total_loss_eur": round(float(scenario_results["rp50"]["total_loss"][all_infra_mask].sum()), 2),
                "rp100_total_loss_eur": round(float(scenario_results["rp100"]["total_loss"][all_infra_mask].sum()), 2),
                "p99_total_loss_eur": round(float(scenario_results["event_max"]["total_loss"][all_infra_mask].sum()), 2),
                "top10_total_loss_eur": round(float(scenario_results["top10"]["total_loss"][all_infra_mask].sum()), 2),
                "top5_total_loss_eur": round(float(scenario_results["top5"]["total_loss"][all_infra_mask].sum()), 2),
                "event_id_max": event_id_max,
            },
            "feature_states": {
                scenario: _aggregate_feature_states(
                    feature_ids,
                    scenario_results[_public_loss_scenario_source(scenario)]["final_state"],
                )
                for scenario in PUBLIC_MAP_SCENARIOS
            },
        }
        del impact
        del hazard_obj
        gc.collect()

    merged_rows = _merge_rows_by_scenario(hazard_outputs)
    summary_text = _build_impact_summary_text(hazard_outputs)

    legacy_rows: list[dict[str, Any]] = []
    for class_key in NETWORK_CLASS_LABELS.keys():
        row_storm_annual = _row_for_class(hazard_outputs, "storm", "annual", class_key)
        row_storm_event = _row_for_class(hazard_outputs, "storm", "event_max", class_key)
        row_cmcc_annual = _row_for_class(hazard_outputs, "storm_cmcc", "annual", class_key)
        row_cmcc_event = _row_for_class(hazard_outputs, "storm_cmcc", "event_max", class_key)
        legacy_rows.append(
            {
                "class_key": class_key,
                "class_label": NETWORK_CLASS_LABELS[class_key],
                "storm": {
                    "state_pct_annual": dict(row_storm_annual.get("state_pct", {})),
                    "state_pct_p99": dict(row_storm_event.get("state_pct", {})),
                    "exposure_eur": float(row_storm_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_storm_annual.get("damage_eur", 0.0)),
                    "p99_loss_eur": float(row_storm_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_storm_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_storm_annual.get("indirect_damage_eur", 0.0)),
                    "direct_p99_loss_eur": float(row_storm_event.get("direct_damage_eur", 0.0)),
                    "indirect_p99_loss_eur": float(row_storm_event.get("indirect_damage_eur", 0.0)),
                },
                "storm_cmcc": {
                    "state_pct_annual": dict(row_cmcc_annual.get("state_pct", {})),
                    "state_pct_p99": dict(row_cmcc_event.get("state_pct", {})),
                    "exposure_eur": float(row_cmcc_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_cmcc_annual.get("damage_eur", 0.0)),
                    "p99_loss_eur": float(row_cmcc_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_cmcc_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_cmcc_annual.get("indirect_damage_eur", 0.0)),
                    "direct_p99_loss_eur": float(row_cmcc_event.get("direct_damage_eur", 0.0)),
                    "indirect_p99_loss_eur": float(row_cmcc_event.get("indirect_damage_eur", 0.0)),
                },
            }
        )

    impact_payload = {
        "summary_text": summary_text,
        "component_order": list(COMPONENT_ORDER),
        "summary_metrics": {haz: hazard_outputs[haz]["summary"] for haz in ("storm", "storm_cmcc")},
        "state_damage_tables": merged_rows,
        "state_damage_table": legacy_rows,
        "damage_breakdown": {
            "storm": _legacy_breakdown_rows(hazard_outputs, "storm"),
            "storm_cmcc": _legacy_breakdown_rows(hazard_outputs, "storm_cmcc"),
        },
        "damage_breakdown_by_scenario": {
            scenario: {
                "storm": hazard_outputs["storm"]["breakdown_by_scenario"][_public_loss_scenario_source(scenario)],
                "storm_cmcc": hazard_outputs["storm_cmcc"]["breakdown_by_scenario"][_public_loss_scenario_source(scenario)],
            }
            for scenario in PUBLIC_MAP_SCENARIOS
        }
        ,
        "map_defaults": {
            "hazard": "storm",
            "scenario": "p99",
        },
    }
    aux = {
        "disaggregation": {
            "sampling_spacing_m": float(disagg.spacing_m),
            "asset_count_points": int(disagg.asset_count_points),
        },
        "complete_analysis_calibration": calibration_by_hazard,
    }
    hazard_feature_states, electric_unit_ids = _aggregate_native_service_states_for_public_map(
        bundle=bundle,
        values=values,
        class_keys=class_keys,
        water_service_classes=water_service_classes,
        service_feature_ids=service_feature_ids,
        is_blocking_asset=is_blocking_asset,
        weights_km=weights_km,
        hazard_outputs=hazard_outputs,
    )
    aux["hazard_feature_states"] = hazard_feature_states
    aux["electric_unit_ids"] = sorted(electric_unit_ids)
    return impact_payload, aux


def _merge_buckets(buckets: list[dict[str, float]]) -> dict[str, float]:
    out = _new_health_bucket()
    for b in buckets:
        out["total"] += float(b.get("total", 0.0))
        out["S1"] += float(b.get("S1", 0.0))
        out["S2"] += float(b.get("S2", 0.0))
        out["S3"] += float(b.get("S3", 0.0))
    return out


def _aggregate_feature_states(feature_ids: list[str], states: np.ndarray) -> dict[str, str]:
    grouped: dict[str, str] = {}
    for fid, state in zip(feature_ids, states, strict=False):
        current = grouped.get(fid, "S0")
        candidate = str(state)
        if STATE_ORDER.get(candidate, 0) > STATE_ORDER.get(current, 0):
            grouped[fid] = candidate
        elif fid not in grouped:
            grouped[fid] = current
    return grouped


def _row_for_class(
    hazard_outputs: dict[str, Any],
    hazard_key: str,
    scenario: str,
    class_key: str,
) -> dict[str, Any]:
    rows_by_scenario = hazard_outputs[hazard_key]["rows_by_scenario"]
    public_scenario = "p99" if scenario == "event_max" else scenario
    for row in rows_by_scenario.get(public_scenario, rows_by_scenario.get(scenario, [])):
        if str(row.get("class_key")) == class_key:
            return row
    return {
        "class_key": class_key,
        "class_label": NETWORK_CLASS_LABELS.get(class_key, class_key),
        "state_pct": {s: 0.0 for s in ("S0", "S1", "S2", "S3")},
        "exposure_eur": 0.0,
        "damage_eur": 0.0,
        "direct_damage_eur": 0.0,
        "indirect_damage_eur": 0.0,
        "damage_components_eur": {comp: 0.0 for comp in COMPONENT_ORDER},
    }


def _merge_rows_by_scenario(hazard_outputs: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for scenario in TABLE_SCENARIOS:
        rows: list[dict[str, Any]] = []
        for class_key in NETWORK_CLASS_LABELS.keys():
            storm_row = _row_for_class(hazard_outputs, "storm", scenario, class_key)
            cmcc_row = _row_for_class(hazard_outputs, "storm_cmcc", scenario, class_key)
            rows.append(
                {
                    "class_key": class_key,
                    "class_label": NETWORK_CLASS_LABELS[class_key],
                    "storm": {
                        "state_pct": dict(storm_row.get("state_pct", {})),
                        "exposure_eur": float(storm_row.get("exposure_eur", 0.0)),
                        "damage_eur": float(storm_row.get("damage_eur", 0.0)),
                        "direct_damage_eur": float(storm_row.get("direct_damage_eur", 0.0)),
                        "indirect_damage_eur": float(storm_row.get("indirect_damage_eur", 0.0)),
                        "damage_components_eur": {
                            comp: float((storm_row.get("damage_components_eur") or {}).get(comp, 0.0))
                            for comp in COMPONENT_ORDER
                        },
                    },
                    "storm_cmcc": {
                        "state_pct": dict(cmcc_row.get("state_pct", {})),
                        "exposure_eur": float(cmcc_row.get("exposure_eur", 0.0)),
                        "damage_eur": float(cmcc_row.get("damage_eur", 0.0)),
                        "direct_damage_eur": float(cmcc_row.get("direct_damage_eur", 0.0)),
                        "indirect_damage_eur": float(cmcc_row.get("indirect_damage_eur", 0.0)),
                        "damage_components_eur": {
                            comp: float((cmcc_row.get("damage_components_eur") or {}).get(comp, 0.0))
                            for comp in COMPONENT_ORDER
                        },
                    },
                }
            )
        out[scenario] = rows
    return out


def _legacy_breakdown_rows(hazard_outputs: dict[str, Any], hazard_key: str) -> list[dict[str, Any]]:
    annual = {str(r["class_key"]): r for r in hazard_outputs[hazard_key]["breakdown_by_scenario"]["annual"]}
    event_max = {str(r["class_key"]): r for r in hazard_outputs[hazard_key]["breakdown_by_scenario"]["event_max"]}
    rows: list[dict[str, Any]] = []
    for class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
        rows.append(
            {
                "class_key": class_key,
                "class_label": label,
                "eai_eur": round(float(annual.get(class_key, {}).get("damage_eur", 0.0)), 2),
                "p99_loss_eur": round(float(event_max.get(class_key, {}).get("damage_eur", 0.0)), 2),
                "direct_eai_eur": round(float(annual.get(class_key, {}).get("direct_damage_eur", 0.0)), 2),
                "indirect_eai_eur": round(float(annual.get(class_key, {}).get("indirect_damage_eur", 0.0)), 2),
                "direct_p99_loss_eur": round(float(event_max.get(class_key, {}).get("direct_damage_eur", 0.0)), 2),
                "indirect_p99_loss_eur": round(float(event_max.get(class_key, {}).get("indirect_damage_eur", 0.0)), 2),
            }
        )
    return rows


def _build_impact_summary_text(hazard_outputs: dict[str, Any]) -> str:
    s = hazard_outputs["storm"]["summary"]
    c = hazard_outputs["storm_cmcc"]["summary"]
    return (
        f"STORM: EAI {s['eai_total_eur']:.0f} €, RP50 {s['rp50_total_loss_eur']:.0f} €, "
        f"RP100 {s['rp100_total_loss_eur']:.0f} €, p99 {s['p99_total_loss_eur']:.0f} €. "
        f"STORM_CMCC: EAI {c['eai_total_eur']:.0f} €, RP50 {c['rp50_total_loss_eur']:.0f} €, "
        f"RP100 {c['rp100_total_loss_eur']:.0f} €, p99 {c['p99_total_loss_eur']:.0f} €."
    )


def _build_conclusion_text(exposure_metrics: dict[str, Any], impact_metrics: dict[str, Any]) -> str:
    storm = impact_metrics["summary_metrics"]["storm"]
    cmcc = impact_metrics["summary_metrics"]["storm_cmcc"]
    total_value = max(1.0, float(exposure_metrics["total_value_all_eur"]))

    def m_eur_rounded(value_eur: float) -> str:
        return f"{int(round(float(value_eur) / 1_000_000.0))}"

    def pct_of_portfolio(value_eur: float) -> str:
        return f"{(float(value_eur) / total_value) * 100.0:.2f}"

    return (
        f"Valeur totale du portefeuille d'infrastructures: {m_eur_rounded(total_value)} M€. "
        f"Dommages annuels moyens: STORM {m_eur_rounded(storm['eai_total_eur'])} M€ ({pct_of_portfolio(storm['eai_total_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['eai_total_eur'])} M€ ({pct_of_portfolio(cmcc['eai_total_eur'])} %). "
        f"Scenario temps de retour 50 ans: STORM {m_eur_rounded(storm['rp50_total_loss_eur'])} M€ ({pct_of_portfolio(storm['rp50_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['rp50_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['rp50_total_loss_eur'])} %). "
        f"Scenario temps de retour 100 ans: STORM {m_eur_rounded(storm['rp100_total_loss_eur'])} M€ ({pct_of_portfolio(storm['rp100_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['rp100_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['rp100_total_loss_eur'])} %). "
        f"Scenario percentile 99: STORM {m_eur_rounded(storm['p99_total_loss_eur'])} M€ ({pct_of_portfolio(storm['p99_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['p99_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['p99_total_loss_eur'])} %)."
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not np.isfinite(out):
        return float(default)
    return out


def _load_complete_analysis_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        raise FileNotFoundError(f"Missing complete-analysis JSON required for page-analysis build: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Unable to read complete-analysis JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid complete-analysis payload (expected object): {path}")
    if not isinstance(payload.get("portfolio_results"), dict):
        raise ValueError(f"Invalid complete-analysis payload (missing portfolio_results): {path}")
    if not isinstance(payload.get("asset_results"), list):
        raise ValueError(f"Invalid complete-analysis payload (missing asset_results): {path}")
    return payload


def _extract_complete_analysis_public_loss_targets(
    payload: dict[str, Any] | None,
    hazard_key: str,
) -> dict[str, float]:
    portfolio = payload.get("portfolio_results") if isinstance(payload, dict) else None
    hazard_payload = portfolio.get(hazard_key) if isinstance(portfolio, dict) else None
    if not isinstance(hazard_payload, dict):
        return {}

    key_map = {
        "annual": "eai_eur",
        "rp50": "pml_50_eur",
        "rp100": "pml_100_eur",
        "event_max": "percentile_99_loss_eur",
    }
    out: dict[str, float] = {}
    for scenario, field in key_map.items():
        value = _safe_float(hazard_payload.get(field), 0.0)
        if value > 0.0:
            out[scenario] = value
    return out


def _rescale_loss_array_to_total(
    losses: np.ndarray,
    capacities: np.ndarray,
    target_total: float,
) -> np.ndarray:
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
    scaled_total = float(np.minimum(current * hi, cap_arr).sum())
    for _ in range(32):
        if scaled_total >= target:
            break
        hi *= 2.0
        scaled_total = float(np.minimum(current * hi, cap_arr).sum())

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


def _calibrate_scenario_results_to_complete_analysis(
    scenario_results: dict[str, dict[str, Any]],
    *,
    values: np.ndarray,
    all_infra_mask: np.ndarray,
    target_totals: dict[str, float],
) -> dict[str, dict[str, float]]:
    if not target_totals:
        return {}

    infra_capacities = np.asarray(values[all_infra_mask], dtype=float)
    applied: dict[str, dict[str, float]] = {}
    for scenario, target_total in target_totals.items():
        result = scenario_results.get(scenario)
        if not isinstance(result, dict):
            continue

        total_loss = np.asarray(result.get("total_loss"), dtype=float).reshape(-1)
        if total_loss.size != values.size:
            continue
        current_total = float(total_loss[all_infra_mask].sum())
        scaled_total_loss = _rescale_loss_array_to_total(total_loss[all_infra_mask], infra_capacities, target_total)

        updated_total_loss = np.array(total_loss, dtype=float, copy=True)
        updated_total_loss[all_infra_mask] = scaled_total_loss
        result["total_loss"] = updated_total_loss

        direct_loss = np.asarray(result.get("direct_loss"), dtype=float).reshape(-1)
        if direct_loss.size == values.size:
            current_direct = np.minimum(direct_loss[all_infra_mask], total_loss[all_infra_mask])
            scaling = np.divide(
                scaled_total_loss,
                np.maximum(total_loss[all_infra_mask], 1e-12),
                out=np.zeros_like(scaled_total_loss),
                where=total_loss[all_infra_mask] > 0.0,
            )
            scaled_direct = np.minimum(current_direct * scaling, scaled_total_loss)
            zero_support = (total_loss[all_infra_mask] <= 0.0) & (scaled_total_loss > 0.0)
            if zero_support.any():
                scaled_direct[zero_support] = scaled_total_loss[zero_support]
            updated_direct_loss = np.array(direct_loss, dtype=float, copy=True)
            updated_direct_loss[all_infra_mask] = np.minimum(np.maximum(scaled_direct, 0.0), scaled_total_loss)
            result["direct_loss"] = updated_direct_loss

        applied[scenario] = {
            "pre_calibration_total_eur": round(current_total, 2),
            "target_total_eur": round(float(target_total), 2),
            "post_calibration_total_eur": round(float(updated_total_loss[all_infra_mask].sum()), 2),
        }

    return applied


def _recalculate_calibrated_scenario_states(
    scenario_results: dict[str, dict[str, Any]],
    *,
    scenario_keys: list[str] | tuple[str, ...] | set[str],
    values_size: int,
    evaluator: Callable[[np.ndarray], dict[str, Any]],
) -> None:
    for scenario in scenario_keys:
        calibrated_result = scenario_results.get(str(scenario))
        if not isinstance(calibrated_result, dict):
            continue
        calibrated_direct_loss = np.asarray(calibrated_result.get("direct_loss"), dtype=float).reshape(-1)
        if calibrated_direct_loss.size != int(values_size):
            continue
        recalculated_states = evaluator(calibrated_direct_loss)
        calibrated_result["direct_state"] = recalculated_states["direct_state"]
        calibrated_result["final_state"] = recalculated_states["final_state"]
        calibrated_result["indirect_s3_flag"] = recalculated_states["indirect_s3_flag"]


def _mean_top_event_loss(events: Any, keep: int) -> float:
    losses: list[float] = []
    for row in list(events or [])[: max(1, int(keep))]:
        if not isinstance(row, dict):
            continue
        loss = _safe_float(row.get("loss_eur"), 0.0)
        if loss > 0.0:
            losses.append(loss)
    if not losses:
        return 0.0
    return float(np.mean(np.asarray(losses, dtype=float)))


def _load_zone_wind_comparison_table(doc_path: Path, zone_heading: str) -> list[dict[str, str]]:
    if not doc_path.exists():
        return []
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    start_idx = None
    target = f"## comparaison vitesses max - zone {zone_heading}".strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower() == target:
            start_idx = i
            break
    if start_idx is None:
        return []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        indicator = cells[0]
        # The note may contain additional return periods, but the UI is intentionally
        # constrained to mean / RP50 / RP100 / strongest event only.
        if "1000" in indicator:
            continue
        rows.append(
            {
                "indicator": indicator,
                "storm": cells[1],
                "storm_cmcc": cells[2],
                "delta": cells[3],
            }
        )
    return rows


def _build_state_geojson(
    geometry_features: list[dict[str, Any]],
    hazard_feature_states: dict[str, Any],
    out_path: Path,
) -> None:
    expected_state_ids = [
        str(feat.get("service_feature_id") or feat.get("feature_id") or "")
        for feat in geometry_features
    ]
    expected_feature_id_set = {state_id for state_id in expected_state_ids if state_id}
    validated_feature_states: dict[str, dict[str, dict[str, str]]] = {}
    for hazard_key in ("storm", "storm_cmcc"):
        hazard_states = hazard_feature_states.get(hazard_key)
        if not isinstance(hazard_states, dict):
            raise RuntimeError(f"Missing feature states for hazard '{hazard_key}'")
        validated_feature_states[hazard_key] = {}
        for scenario in PUBLIC_MAP_SCENARIOS:
            scenario_states = hazard_states.get(scenario)
            if not isinstance(scenario_states, dict):
                raise RuntimeError(f"Missing feature states for scenario '{hazard_key}.{scenario}'")
            scenario_feature_ids = {str(fid) for fid in scenario_states.keys()}
            missing_feature_ids = sorted(expected_feature_id_set - scenario_feature_ids)
            if missing_feature_ids:
                preview = ", ".join(missing_feature_ids[:5])
                suffix = "..." if len(missing_feature_ids) > 5 else ""
                raise RuntimeError(
                    f"Incomplete feature states for {hazard_key}.{scenario}: "
                    f"missing {len(missing_feature_ids)} expected features ({preview}{suffix})"
                )
            unexpected_feature_ids = sorted(scenario_feature_ids - expected_feature_id_set)
            if unexpected_feature_ids:
                preview = ", ".join(unexpected_feature_ids[:5])
                suffix = "..." if len(unexpected_feature_ids) > 5 else ""
                raise RuntimeError(
                    f"Unexpected feature states for {hazard_key}.{scenario}: "
                    f"unknown features ({preview}{suffix})"
                )
            invalid_states = sorted(
                {str(state) for state in scenario_states.values()} - set(STATE_ORDER.keys())
            )
            if invalid_states:
                raise RuntimeError(
                    f"Invalid feature states for {hazard_key}.{scenario}: {', '.join(invalid_states)}"
                )
            validated_feature_states[hazard_key][scenario] = {
                str(fid): str(state)
                for fid, state in scenario_states.items()
            }

    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for feat in geometry_features:
        fid = feat["feature_id"]
        state_lookup_id = str(feat.get("service_feature_id") or fid)
        row = {
            "feature_id": fid,
            "layer_key": feat["class_key"],
            "layer_label": feat["class_label"],
            "state_geometry_mode": str(feat.get("state_geometry_mode") or "native_network_geometry"),
            "service_unit_kind": str(feat.get("service_unit_kind") or "native_feature"),
            "service_feature_id": str(feat.get("service_feature_id") or ""),
            "zone_component_key": str(feat.get("zone_component_key") or ""),
            "zone_uid": str(feat.get("zone_uid") or ""),
            "network_kind": str(feat.get("network_kind") or ""),
            "feature_role": str(feat.get("feature_role") or ""),
        }
        for hazard_key in ("storm", "storm_cmcc"):
            for scenario in PUBLIC_MAP_SCENARIOS:
                row[f"state_{scenario}_{hazard_key}"] = validated_feature_states[hazard_key][scenario][state_lookup_id]
        rows.append(row)
        geoms.append(feat["geometry"])
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=WGS84)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    geojson = json.loads(gdf.to_json())
    water_rows = [feat for feat in geometry_features if str(feat.get("class_key") or "") in {"eau_aep", "eau_eu"}]
    water_state_modes = sorted({str(feat.get("state_geometry_mode") or "native_network_geometry") for feat in water_rows})
    payload = {
        **geojson,
        "metadata": {
            "state_geometry_mode": "hydraulic_zoning_v2" if "hydraulic_zoning_v2" in water_state_modes else "native_network_geometry",
            "water_state_geometry_mode": "hydraulic_zoning_v2" if water_rows else "native_network_geometry",
            "water_service_unit": "zone_component_key" if water_rows else "feature_id",
            "electric_state_geometry_mode": "fixed_grid_0p1deg",
            "geometry_semantics": "native_service_geometry",
            **WEB_NETWORK_STATE_METHODOLOGY_METADATA,
        },
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all computed data for territory case-study pages (exposition, hazard, impact, conclusion).")
    parser.add_argument("--territory", default="guadeloupe")
    parser.add_argument("--infra-elec-dir", default=None)
    parser.add_argument("--infra-eau-dir", default=None)
    parser.add_argument("--storm-source", default=os.environ.get("SIB_RISK_STORM_TXT_DIR", str(REPO_ROOT / "data" / "hazards" / "STORM_ds")))
    parser.add_argument(
        "--cmcc-source",
        default=os.environ.get("SIB_RISK_STORM_CMCC_TXT_DIR", str(REPO_ROOT / "data" / "hazards" / "STORM_CMCC_ds")),
    )
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in STORM/STORM_CMCC datasets. Supported: m/s, kn, km/h. Output is always m/s.",
    )
    parser.add_argument("--spacing-m", type=float, default=100.0)
    parser.add_argument("--component-light-spacing-m", type=float, default=DEFAULT_COMPONENT_LIGHT_SPACING_M)
    parser.add_argument("--component-light-max-points-total", type=int, default=DEFAULT_COMPONENT_LIGHT_MAX_POINTS_TOTAL)
    parser.add_argument("--component-light-max-points-per-feature", type=int, default=DEFAULT_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE)
    parser.add_argument("--component-light-dynamic-max-tracks", type=int, default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-state-geojson", default=None)
    parser.add_argument("--diagnostic-md", default=str(REPO_ROOT / "docs" / "diagnostic-vents-et-mailles.md"))
    parser.add_argument("--complete-analysis-json", default=None)
    parser.add_argument("--multi-hazard-proxy-json", default=None)
    parser.add_argument(
        "--wind-map-json",
        default=None,
        help="Case-study wind map JSON used as the single source for hazard tables/graphs coherence.",
    )
    parser.add_argument(
        "--case-study-run-id",
        default=None,
        help="Optional coherence token propagated across case-study artefacts (maps/proxy/page analysis).",
    )
    args = parser.parse_args()
    _require_runtime_deps()

    territory = parse_territory(args.territory)
    case_cfg = get_case_study(
        territory,
        infra_elec_dir=Path(args.infra_elec_dir) if args.infra_elec_dir else None,
        infra_eau_dir=Path(args.infra_eau_dir) if args.infra_eau_dir else None,
    )
    out_json = (
        Path(args.out_json)
        if args.out_json
        else (REPO_ROOT / "web" / "data" / str(case_cfg["analysis_json_name"]))
    )
    out_state_geojson = (
        Path(args.out_state_geojson)
        if args.out_state_geojson
        else (REPO_ROOT / "web" / "data" / f"{territory}-network-states.geojson")
    )
    settings = load_settings()
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)
    valuation_metadata = build_valuation_metadata(territory)
    hazard_storm_path, hazard_storm_cmcc_path = _resolve_hazard_paths_for_case_study(territory, settings)
    default_complete_analysis_json = REPO_ROOT / "web" / "data" / f"{territory}-complete-analysis.json"
    complete_analysis_json = Path(args.complete_analysis_json) if args.complete_analysis_json else default_complete_analysis_json
    complete_analysis_payload = _load_complete_analysis_payload(complete_analysis_json)
    complete_analysis_source = _extract_complete_analysis_source_metadata(complete_analysis_payload)
    component_ratios_by_hazard = None
    default_multi_hazard_proxy_json = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"
    multi_hazard_proxy_json = (
        Path(args.multi_hazard_proxy_json)
        if args.multi_hazard_proxy_json
        else default_multi_hazard_proxy_json
    )
    proxy_payload = _load_json_payload(multi_hazard_proxy_json)
    proxy_meta = proxy_payload.get("meta") if isinstance(proxy_payload, dict) else None
    proxy_run_id = (
        str(proxy_meta.get("case_study_run_id") or "").strip()
        if isinstance(proxy_meta, dict)
        else ""
    )
    multi_hazard_proxy = _load_multi_hazard_proxy(
        multi_hazard_proxy_json,
        component_ratios_by_hazard=component_ratios_by_hazard,
        strict=True,
    )

    default_wind_map_json = REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"
    wind_map_json = Path(args.wind_map_json) if args.wind_map_json else default_wind_map_json
    wind_map_payload = _load_json_payload(wind_map_json)
    if not wind_map_payload:
        raise FileNotFoundError(
            f"Missing or invalid wind map payload for case-study coherence: {wind_map_json}"
        )
    wind_map_meta = wind_map_payload.get("meta") if isinstance(wind_map_payload, dict) else None
    wind_map_territory = (
        str(wind_map_meta.get("territory") or "").strip().lower()
        if isinstance(wind_map_meta, dict)
        else ""
    )
    if wind_map_territory and wind_map_territory != territory:
        raise ValueError(
            f"Wind map territory mismatch: expected {territory}, got {wind_map_territory} in {wind_map_json}"
        )
    wind_map_run_id = (
        str(wind_map_meta.get("case_study_run_id") or "").strip()
        if isinstance(wind_map_meta, dict)
        else ""
    )
    provided_run_id = str(args.case_study_run_id or "").strip()
    if provided_run_id and not wind_map_run_id:
        raise ValueError(
            f"case-study run id provided ({provided_run_id}) but wind map has no case_study_run_id: {wind_map_json}"
        )
    if provided_run_id and not proxy_run_id and multi_hazard_proxy_json.exists():
        raise ValueError(
            f"case-study run id provided ({provided_run_id}) but proxy has no case_study_run_id: {multi_hazard_proxy_json}"
        )
    if wind_map_run_id and not proxy_run_id and multi_hazard_proxy_json.exists():
        raise ValueError(
            f"case-study run id mismatch: wind map has {wind_map_run_id} but proxy has no case_study_run_id"
        )
    if proxy_run_id and not wind_map_run_id:
        raise ValueError(
            f"case-study run id mismatch: proxy has {proxy_run_id} but wind map has no case_study_run_id"
        )
    if provided_run_id and wind_map_run_id and provided_run_id != wind_map_run_id:
        raise ValueError(
            f"case-study run id mismatch: provided={provided_run_id}, wind_map={wind_map_run_id}"
        )
    if provided_run_id and proxy_run_id and provided_run_id != proxy_run_id:
        raise ValueError(
            f"case-study run id mismatch: provided={provided_run_id}, multi_hazard_proxy={proxy_run_id}"
        )
    if wind_map_run_id and proxy_run_id and wind_map_run_id != proxy_run_id:
        raise ValueError(
            f"case-study run id mismatch between wind_map={wind_map_run_id} and multi_hazard_proxy={proxy_run_id}"
        )
    case_study_run_id = (
        provided_run_id
        or wind_map_run_id
        or proxy_run_id
        or datetime.now(UTC).strftime(f"{territory}_case_%Y%m%dT%H%M%SZ")
    )

    exposure_metrics = _build_exposure_metrics(case_cfg, territory)
    hazard_hist = _build_wind_histograms_from_wind_map_payload(wind_map_payload)
    bbox_cfg = dict(case_cfg.get("wind_bbox") or {})
    landslide_bbox = (
        float(bbox_cfg["lon_min"]),
        float(bbox_cfg["lat_min"]),
        float(bbox_cfg["lon_max"]),
        float(bbox_cfg["lat_max"]),
    )
    exposure = build_complete_exposure(
        infra_elec_dir=case_cfg["infra_elec_dir"],
        infra_eau_dir=case_cfg["infra_eau_dir"],
        territory=territory,
    )
    impact_metrics, aux = _compute_impact_metrics(
        exposure,
        spacing_m=float(args.spacing_m),
        settings=settings,
        network_value_per_km=exposure_metrics["value_per_km_eur"],
        exposure_value_by_class=exposure_metrics["total_value_by_type_eur"],
        territory=territory,
        landslide_bbox=landslide_bbox,
        hazard_storm_path=hazard_storm_path,
        hazard_storm_cmcc_path=hazard_storm_cmcc_path,
        component_ratios_by_hazard=component_ratios_by_hazard,
        multi_hazard_proxy=multi_hazard_proxy,
        complete_analysis_payload=complete_analysis_payload,
        component_light_spacing_m=float(args.component_light_spacing_m),
        component_light_max_points_total=int(args.component_light_max_points_total),
        component_light_max_points_per_feature=int(args.component_light_max_points_per_feature),
        component_light_dynamic_max_tracks=(
            int(args.component_light_dynamic_max_tracks)
            if args.component_light_dynamic_max_tracks is not None
            else None
        ),
    )
    conclusion_text = _build_conclusion_text(exposure_metrics, impact_metrics)
    zone_wind_compare_rows = _build_zone_wind_comparison_table_from_wind_map_payload(wind_map_payload)
    if not zone_wind_compare_rows:
        raise ValueError(
            f"Unable to build wind comparison table from wind map payload: {wind_map_json}"
        )

    geometry_features = _build_network_geometry_features(
        case_cfg,
        electric_unit_ids=set(aux.get("electric_unit_ids") or []),
    )
    _overlay_complete_analysis_service_states_on_public_map(
        geometry_features,
        aux["hazard_feature_states"],
        complete_analysis_payload=complete_analysis_payload,
    )
    _build_state_geojson(geometry_features, aux["hazard_feature_states"], out_state_geojson)

    complete_analysis_calibration = aux.get("complete_analysis_calibration") if isinstance(aux, dict) else None
    notes: list[str] = []
    if isinstance(complete_analysis_calibration, dict) and complete_analysis_calibration:
        notes.append(
            "Public annual/RP50/RP100/P99 loss totals are calibrated to complete-analysis portfolio quantiles."
        )

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "case_study_run_id": case_study_run_id,
            "source": f"{territory}_case_study_computed",
            "case_study_territory": territory,
            "case_study_label": territory_label(territory),
            "sampling_spacing_m": float(args.spacing_m),
            "hazards": ["STORM", "STORM_CMCC"],
            "hazard_components": ["wind", "rain", "surge", "landslide"],
            "storm_years": int(settings.storm_years),
            "component_light_rerun": {
                "spacing_m": float(args.component_light_spacing_m),
                "max_points_total": int(args.component_light_max_points_total),
                "max_points_per_feature": int(args.component_light_max_points_per_feature),
                "dynamic_max_tracks": (
                    int(args.component_light_dynamic_max_tracks)
                    if args.component_light_dynamic_max_tracks is not None
                    else int(settings.hazard_dynamic_max_tracks)
                ),
            },
            "multi_hazard_proxy_json": str(multi_hazard_proxy_json) if multi_hazard_proxy_json.exists() else None,
            "multi_hazard_proxy_run_id": proxy_run_id or None,
            "wind_map_json": str(wind_map_json),
            "wind_map_generated_at": wind_map_meta.get("generated_at") if isinstance(wind_map_meta, dict) else None,
            "wind_map_run_id": wind_map_run_id or None,
            "complete_analysis_json": str(complete_analysis_json) if complete_analysis_json.exists() else None,
            "complete_analysis_source": complete_analysis_source if isinstance(complete_analysis_source, dict) else None,
            "network_state_methodology": (
                dict(complete_analysis_source.get("network_state_methodology") or {})
                if isinstance(complete_analysis_source, dict)
                else {}
            ),
            "network_state_methodology_breaks_comparability": bool(
                complete_analysis_source.get("network_state_methodology_breaks_comparability")
                if isinstance(complete_analysis_source, dict)
                else True
            ),
            "complete_analysis_calibration": complete_analysis_calibration if isinstance(complete_analysis_calibration, dict) else None,
            "valuation_source": SOURCE_LABEL,
            "valuation_territory": str(valuation_metadata["territory_effective"]),
            "valuation_version": str(valuation_metadata["valuation_version"]),
            "notes": notes,
            "modeling": {
                "source": "case_study_page_analysis",
                "fallback": False,
                "fallback_landslide_component_supported": True,
            },
            "publication_trace": _build_publication_trace(
                source_mode="case_study_page_analysis",
                fallback_reason=None,
                complete_analysis_source=complete_analysis_source if isinstance(complete_analysis_source, dict) else None,
                wind_map_meta=wind_map_meta if isinstance(wind_map_meta, dict) else None,
                proxy_meta=proxy_meta if isinstance(proxy_meta, dict) else None,
            ),
        },
        "exposition": exposure_metrics,
        "hazard": {
            "summary_text": (
                "Cette section décrit les aléas qui sont utilisés comme sources de dommages sur l’exposition (les infrastructures d’eau et d'électricité). "
                "Le catalogue STORM est une base de données simulant 10 000 ans de cyclones tropicaux synthétiques. "
                "Le catalogue STORM CMCC représente la même base de données auquel un facteur de changement climatique, le scénario RCP 8.5 du GIEC a été appliqué.\n\n"
                "Les graphiques ci-dessous décrivent la vitesse moyenne des vents maximums par année des bases de données STORM et STORM_CMCC. "
                "En d’autres termes cela représente la probabilité moyenne des vents sur la zone d’étude d’après les bases de données utilisées."
            ),
            "wind_unit_in": normalized_wind_unit,
            "wind_unit_out": "m/s",
            "wind_histograms": hazard_hist,
            "zone_wind_comparison_table": zone_wind_compare_rows,
        },
        "impact": impact_metrics,
        "conclusion": {
            "text": conclusion_text,
        },
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    record_guamar_run(territory)

    print(f"Wrote {out_json}")
    print(f"Wrote {out_state_geojson}")
    print(f"territory={territory}")
    print(f"State map features: {len(geometry_features)}")
    print(f"EAI STORM: {impact_metrics['summary_metrics']['storm']['eai_total_eur']}")
    print(f"EAI STORM_CMCC: {impact_metrics['summary_metrics']['storm_cmcc']['eai_total_eur']}")


if __name__ == "__main__":
    main()
