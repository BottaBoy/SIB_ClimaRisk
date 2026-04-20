#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

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
except Exception:  # pragma: no cover - optional at import time for CLI --help
    box = None  # type: ignore[assignment]


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.exposure_to_climada import ClimadaExposureBundle, build_climada_exposure  # noqa: E402
from app.risk_engine.hazard_loader import load_storm_hazards  # noqa: E402
from app.risk_engine.impact_functions import (  # noqa: E402
    resolve_tc_impact_func_id,
    try_build_climada_impact_funcs,
)
from app.risk_engine.landslide_engine import run_landslide_direct_impacts, scenario_loss_factors  # noqa: E402
from app.risk_engine.types import NormalizedExposure  # noqa: E402
from build_guadeloupe_complete_analysis import (  # noqa: E402
    WGS84,
    _as_wgs84_and_metric,
    _ensure_crs,
    build_complete_exposure,
)
from case_study_sources import get_case_study, normalize_territory, territory_label  # noqa: E402
from valuation_ofb import (  # noqa: E402
    SOURCE_LABEL,
    build_valuation_metadata,
    get_aep_ouvrage_value,
    get_network_values_per_km,
    get_water_values,
)
from journal_guamar_run import record_guamar_run  # noqa: E402


STATE_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
UPLIFT_BY_STATE = {"S0": 0.0, "S1": 0.10, "S2": 0.25, "S3": 0.45}

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

NETWORK_LAYER_PREFIX = {
    "eau_aep": "aep-cana",
    "eau_eu": "eu-cana",
    "elec_bt_souterrain": "elec-bt-souterrain",
    "elec_bt_aerien": "elec-bt-aerien",
    "elec_hta_souterrain": "elec-hta-souterrain",
    "elec_hta_aerien": "elec-hta-aerien",
}

GLOBAL_EVENT_CLASS_KEYS = tuple(DAMAGE_BREAKDOWN_LABELS.keys())
TABLE_SCENARIOS = ("annual", "rp50", "rp100", "event_max")
MAP_SCENARIOS = ("annual", "rp50", "rp100", "event_max", "top10", "top5")
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
WIND_BIN_STEP_MPS = 1.0
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
}


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
        gdf = _clip_case_gdf(_ensure_crs(gpd.read_file(path)), case_cfg)
        count += int(len(gdf))
    return count


def _count_aep_ouvrage_types(case_cfg: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for src in case_cfg["aep_ouvrage_sources"]:
        mode = str(src.get("mode", "")).strip().lower()
        for path in src["paths"]:
            gdf = _ensure_crs(gpd.read_file(path))
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
            gdf = _clip_case_gdf(_ensure_crs(gpd.read_file(path)), case_cfg)
            if gdf.empty:
                continue
            lengths_km[class_key] += _line_length_km(gdf)
            elec_lines_total += int(len(gdf))

    for src in case_cfg["water_line_sources"]:
        class_key = str(src["class_key"])
        for path in src["paths"]:
            gdf = _clip_case_gdf(_ensure_crs(gpd.read_file(path)), case_cfg)
            if gdf.empty:
                continue
            lengths_km[class_key] += _line_length_km(gdf)
            water_lines_total += int(len(gdf))

    value_per_km = get_network_values_per_km(territory)
    total_value_network = {key: round(lengths_km[key] * value_per_km[key], 2) for key in value_per_km.keys()}
    water_values = get_water_values(territory)

    aep_type_counts = _count_aep_ouvrage_types(case_cfg)
    total_value_aep_ouvr = round(sum(get_aep_ouvrage_value(k) * int(v) for k, v in aep_type_counts.items()), 2)

    eu_pr_total = 0
    eu_step_total = 0
    for src in case_cfg["water_point_fixed_sources"]:
        if str(src["asset_type"]) == "eau_eu_pr":
            eu_pr_total += _count_features(list(src["paths"]), case_cfg)
        if str(src["asset_type"]) == "eau_eu_step":
            eu_step_total += _count_features(list(src["paths"]), case_cfg)
    total_value_pr = round(float(eu_pr_total) * float(water_values["eau_eu_pr"]), 2)
    total_value_step = round(float(eu_step_total) * float(water_values["eau_eu_step"]), 2)

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


def _breakdown_class_from_point(point_record: dict[str, Any]) -> str | None:
    asset_type = str(point_record.get("asset_type") or "")
    if asset_type.startswith("eau_aep_ouvrage_"):
        return "eau_aep_ouvrages"
    if asset_type == "eau_eu_pr":
        return "eau_eu_pr"
    if asset_type == "eau_eu_step":
        return "eau_eu_step"
    return ASSET_TYPE_TO_NETWORK_CLASS.get(asset_type)


def _build_network_geometry_features(case_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def append_lines(path: Path, class_key: str, prefix: str, source_idx: int) -> None:
        gdf = _clip_case_gdf(_ensure_crs(gpd.read_file(path)), case_cfg).to_crs(WGS84)
        if gdf.empty:
            return
        for idx, geom in enumerate(gdf.geometry, start=1):
            if geom is None or getattr(geom, "is_empty", False):
                continue
            out.append(
                {
                    "feature_id": f"{prefix}-{source_idx}-{idx}",
                    "class_key": class_key,
                    "class_label": NETWORK_CLASS_LABELS[class_key],
                    "geometry": geom,
                }
            )

    for src in case_cfg["network_geometry_sources"]:
        class_key = str(src["class_key"])
        prefix = str(src["prefix"])
        for source_idx, path in enumerate(src["paths"], start=1):
            append_lines(path, class_key, prefix, source_idx)
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
) -> dict[str, dict[str, dict[str, Any]]]:
    out = _default_multi_hazard_proxy(component_ratios_by_hazard)
    if path is None or not path.exists():
        return out

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out

    hazards = payload.get("hazards") if isinstance(payload, dict) else None
    if not isinstance(hazards, dict):
        return out

    for hazard in ("storm", "storm_cmcc"):
        hazard_payload = hazards.get(hazard)
        if not isinstance(hazard_payload, dict):
            continue
        scenarios = hazard_payload.get("scenarios")
        if not isinstance(scenarios, dict):
            continue
        for scenario in MAP_SCENARIOS:
            scenario_payload = scenarios.get(scenario)
            if not isinstance(scenario_payload, dict):
                continue
            ratios = scenario_payload.get("component_ratios")
            if isinstance(ratios, dict):
                out[hazard]["component_ratios"][scenario] = _normalize_component_ratio_map(ratios)
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
            result = run_landslide_direct_impacts(
                exposure_bundle,
                bbox=bbox,
                path_sourcefile=path,
                corr_fact=float(settings.landslide_corr_fact),
                n_years=int(settings.landslide_n_years),
                dist=str(settings.landslide_dist),
                random_seed=_stable_seed(territory, hazard_key, source_name, path.name),
            )
            factors = scenario_loss_factors(result)
            annual = np.asarray(getattr(result, "eai_direct_by_point", []), dtype=float).reshape(-1)
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
    if not proxy_share_map:
        proxy_share_map = _normalize_breakdown_share_map(
            shares_by_scenario.get("annual")
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
        if ratio_map == {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0} and isinstance(component_ratios, dict):
            ratio_map = _normalize_component_ratio_map(component_ratios.get("annual"))
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
    component_light_spacing_m: float = DEFAULT_COMPONENT_LIGHT_SPACING_M,
    component_light_max_points_total: int = DEFAULT_COMPONENT_LIGHT_MAX_POINTS_TOTAL,
    component_light_max_points_per_feature: int = DEFAULT_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE,
    component_light_dynamic_max_tracks: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise RuntimeError("Unable to instantiate CLIMADA impact functions")
    impfset = ImpactFuncSet(impact_funcs)

    disagg = summarize_disaggregation(exposure, spacing_m=spacing_m)
    bundle = build_climada_exposure(
        exposure,
        spacing_m=spacing_m,
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=settings.climada_max_points_per_feature,
        impact_func_id_resolver=resolve_tc_impact_func_id,
    )
    hazards = load_storm_hazards(hazard_storm_path, hazard_storm_cmcc_path, settings.storm_years)

    values = np.array([float(rec["value_eur"]) for rec in bundle.point_records], dtype=float)
    territories = [str(rec["territory_id"]) for rec in bundle.point_records]
    feature_ids = [str(rec["feature_id"]) for rec in bundle.point_records]
    class_keys = [_network_class_from_point(rec) for rec in bundle.point_records]
    breakdown_class_keys = [_breakdown_class_from_point(rec) for rec in bundle.point_records]
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
    for hazard_key, hazard_obj in {"storm": hazards.storm, "storm_cmcc": hazards.storm_cmcc}.items():
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
            direct = np.minimum(np.maximum(np.asarray(direct_loss, dtype=float), 0.0), values)
            direct_ratio = np.divide(direct, np.maximum(values, 1.0))
            direct_state = np.array([_state_from_ratio(float(v)) for v in direct_ratio], dtype=object)

            elec_buckets: dict[str, dict[str, float]] = defaultdict(_new_health_bucket)
            for i, ckey in enumerate(class_keys):
                if ckey is None or not ckey.startswith("elec_"):
                    continue
                _add_state(elec_buckets[territories[i]], str(direct_state[i]), float(weights_km[i]))
            elec_health = {k: _health(v) for k, v in elec_buckets.items()}
            global_health = _health(_merge_buckets(list(elec_buckets.values())))

            total_loss = np.array(direct, dtype=float)
            final_state: list[str] = []
            indirect_s3_flag = np.zeros_like(direct, dtype=bool)
            for i, ckey in enumerate(class_keys):
                state_code = str(direct_state[i])
                if ckey in {"eau_aep", "eau_eu"}:
                    dep_state = _dependency_state_from_elec_health(elec_health.get(territories[i], global_health))
                    final_code = dep_state if STATE_ORDER[dep_state] > STATE_ORDER[state_code] else state_code
                    uplift = UPLIFT_BY_STATE[dep_state]
                    total_with_dep = min(float(values[i]), float(direct[i]) * (1.0 + float(uplift)))
                    total_loss[i] = max(0.0, total_with_dep)
                    indirect_s3_flag[i] = final_code == "S3" and state_code != "S3"
                    final_state.append(final_code)
                else:
                    final_state.append(state_code)

            final_state_arr = np.array(final_state, dtype=object)
            return {
                "direct_loss": np.minimum(np.maximum(direct, 0.0), values),
                "direct_state": direct_state,
                "final_state": final_state_arr,
                "total_loss": np.minimum(np.maximum(total_loss, 0.0), values),
                "indirect_s3_flag": indirect_s3_flag,
        }

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

        rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in TABLE_SCENARIOS:
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
                            float(weights_km[mask & (scenario_results[scenario]["final_state"] == s)].sum())
                            / total_w
                            * 100.0,
                            3,
                        )
                        for s in ("S0", "S1", "S2", "S3")
                    }
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

        all_infra_mask = np.array([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
        network_mask = np.array([ck in NETWORK_CLASS_LABELS for ck in class_keys], dtype=bool)
        network_total_w = float(weights_km[network_mask].sum())

        direct_s3_annual = float(weights_km[network_mask & (scenario_results["annual"]["direct_state"] == "S3")].sum())
        direct_s3_event = float(weights_km[network_mask & (scenario_results["event_max"]["direct_state"] == "S3")].sum())
        indirect_s3_annual = float(weights_km[network_mask & scenario_results["annual"]["indirect_s3_flag"]].sum())
        indirect_s3_event = float(weights_km[network_mask & scenario_results["event_max"]["indirect_s3_flag"]].sum())

        hazard_outputs[hazard_key] = {
            "rows_by_scenario": rows_by_scenario,
            "breakdown_by_scenario": breakdown_by_scenario,
            "summary": {
                "direct_hs_pct_annual": round((direct_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "direct_hs_pct_event_max": round((direct_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_annual": round((indirect_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_event_max": round((indirect_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "eai_total_eur": round(float(scenario_results["annual"]["total_loss"][all_infra_mask].sum()), 2),
                "rp50_total_loss_eur": round(float(scenario_results["rp50"]["total_loss"][all_infra_mask].sum()), 2),
                "rp100_total_loss_eur": round(float(scenario_results["rp100"]["total_loss"][all_infra_mask].sum()), 2),
                "event_max_total_loss_eur": round(float(scenario_results["event_max"]["total_loss"][all_infra_mask].sum()), 2),
                "top10_total_loss_eur": round(float(scenario_results["top10"]["total_loss"][all_infra_mask].sum()), 2),
                "top5_total_loss_eur": round(float(scenario_results["top5"]["total_loss"][all_infra_mask].sum()), 2),
                "event_id_max": event_id_max,
            },
            "feature_states": {
                scenario: _aggregate_feature_states(feature_ids, scenario_results[scenario]["final_state"])
                for scenario in MAP_SCENARIOS
            },
        }

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
                    "state_pct_event_max": dict(row_storm_event.get("state_pct", {})),
                    "exposure_eur": float(row_storm_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_storm_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_storm_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_storm_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_storm_annual.get("indirect_damage_eur", 0.0)),
                    "direct_event_max_loss_eur": float(row_storm_event.get("direct_damage_eur", 0.0)),
                    "indirect_event_max_loss_eur": float(row_storm_event.get("indirect_damage_eur", 0.0)),
                },
                "storm_cmcc": {
                    "state_pct_annual": dict(row_cmcc_annual.get("state_pct", {})),
                    "state_pct_event_max": dict(row_cmcc_event.get("state_pct", {})),
                    "exposure_eur": float(row_cmcc_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_cmcc_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_cmcc_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_cmcc_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_cmcc_annual.get("indirect_damage_eur", 0.0)),
                    "direct_event_max_loss_eur": float(row_cmcc_event.get("direct_damage_eur", 0.0)),
                    "indirect_event_max_loss_eur": float(row_cmcc_event.get("indirect_damage_eur", 0.0)),
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
                "storm": hazard_outputs["storm"]["breakdown_by_scenario"][scenario],
                "storm_cmcc": hazard_outputs["storm_cmcc"]["breakdown_by_scenario"][scenario],
            }
            for scenario in MAP_SCENARIOS
        },
        "map_defaults": {
            "hazard": "storm",
            "scenario": "event_max",
        },
    }
    aux = {
        "hazard_feature_states": {
            "storm": hazard_outputs["storm"]["feature_states"],
            "storm_cmcc": hazard_outputs["storm_cmcc"]["feature_states"],
        },
        "disaggregation": {
            "sampling_spacing_m": float(disagg.spacing_m),
            "asset_count_points": int(disagg.asset_count_points),
        },
    }
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
    for row in hazard_outputs[hazard_key]["rows_by_scenario"][scenario]:
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
                "event_max_loss_eur": round(float(event_max.get(class_key, {}).get("damage_eur", 0.0)), 2),
                "direct_eai_eur": round(float(annual.get(class_key, {}).get("direct_damage_eur", 0.0)), 2),
                "indirect_eai_eur": round(float(annual.get(class_key, {}).get("indirect_damage_eur", 0.0)), 2),
                "direct_event_max_loss_eur": round(float(event_max.get(class_key, {}).get("direct_damage_eur", 0.0)), 2),
                "indirect_event_max_loss_eur": round(float(event_max.get(class_key, {}).get("indirect_damage_eur", 0.0)), 2),
            }
        )
    return rows


def _build_impact_summary_text(hazard_outputs: dict[str, Any]) -> str:
    s = hazard_outputs["storm"]["summary"]
    c = hazard_outputs["storm_cmcc"]["summary"]
    return (
        f"STORM: EAI {s['eai_total_eur']:.0f} €, RP50 {s['rp50_total_loss_eur']:.0f} €, "
        f"RP100 {s['rp100_total_loss_eur']:.0f} €, evt max {s['event_max_total_loss_eur']:.0f} €. "
        f"STORM_CMCC: EAI {c['eai_total_eur']:.0f} €, RP50 {c['rp50_total_loss_eur']:.0f} €, "
        f"RP100 {c['rp100_total_loss_eur']:.0f} €, evt max {c['event_max_total_loss_eur']:.0f} €."
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
        f"Evenement le plus extreme: STORM {m_eur_rounded(storm['event_max_total_loss_eur'])} M€ ({pct_of_portfolio(storm['event_max_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['event_max_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['event_max_total_loss_eur'])} %)."
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
        raise FileNotFoundError(f"Missing complete-analysis JSON for fallback synthesis: {path}")

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


def _scenario_targets_from_complete_analysis(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    portfolio = payload.get("portfolio_results") if isinstance(payload, dict) else None
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    event_summary = portfolio.get("event_summary") if isinstance(portfolio.get("event_summary"), dict) else {}

    out: dict[str, dict[str, float]] = {}
    for hazard_key, top_events_key in (
        ("storm", "storm_top_events"),
        ("storm_cmcc", "storm_cmcc_top_events"),
    ):
        hazard_payload = portfolio.get(hazard_key) if isinstance(portfolio.get(hazard_key), dict) else {}
        annual = _safe_float(hazard_payload.get("eai_eur"), 0.0)
        rp50 = _safe_float(hazard_payload.get("pml_50_eur"), 0.0)
        rp100 = _safe_float(hazard_payload.get("pml_100_eur"), 0.0)
        event_max = _safe_float(hazard_payload.get("max_event_loss_eur"), 0.0)
        top_events = event_summary.get(top_events_key) if isinstance(event_summary.get(top_events_key), list) else []
        top10 = _mean_top_event_loss(top_events, 10)
        top5 = _mean_top_event_loss(top_events, 5)
        if top10 <= 0.0:
            top10 = event_max or rp100 or annual
        if top5 <= 0.0:
            top5 = top10 or event_max or rp100 or annual
        out[hazard_key] = {
            "annual": annual,
            "rp50": rp50 or rp100 or annual,
            "rp100": rp100 or rp50 or annual,
            "event_max": event_max or top5 or rp100 or annual,
            "top10": top10,
            "top5": top5,
        }
    return out


def _event_id_max_from_complete_analysis(payload: dict[str, Any], hazard_key: str) -> int:
    portfolio = payload.get("portfolio_results") if isinstance(payload, dict) else None
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    event_summary = portfolio.get("event_summary") if isinstance(portfolio.get("event_summary"), dict) else {}
    event_key = "storm_top_events" if hazard_key == "storm" else "storm_cmcc_top_events"
    events = event_summary.get(event_key) if isinstance(event_summary.get(event_key), list) else []
    if not events:
        return 0
    first = events[0] if isinstance(events[0], dict) else {}
    try:
        return int(first.get("event_id") or 0)
    except Exception:
        return 0


def _allocate_additional_loss(
    target_total: float,
    base_loss: np.ndarray,
    values: np.ndarray,
    preferred_weights: np.ndarray,
) -> np.ndarray:
    base = np.minimum(np.maximum(np.asarray(base_loss, dtype=float).reshape(-1), 0.0), values)
    vals = np.asarray(values, dtype=float).reshape(-1)
    weights = np.maximum(np.asarray(preferred_weights, dtype=float).reshape(-1), 0.0)

    residual = max(0.0, float(target_total) - float(base.sum()))
    if residual <= 0.0:
        return np.zeros_like(base, dtype=float)

    available = np.minimum(np.maximum(vals - base, 0.0), vals)
    if not np.any(available > 1e-9):
        return np.zeros_like(base, dtype=float)

    allocation = np.zeros_like(base, dtype=float)
    remaining = residual
    active = available > 1e-9
    current_weights = np.where(active, weights, 0.0)

    for _ in range(6):
        if remaining <= 1e-6 or not np.any(active):
            break
        basis = np.where(active, current_weights, 0.0)
        if float(basis.sum()) <= 0.0:
            basis = np.where(active, available, 0.0)
        basis_sum = float(basis.sum())
        if basis_sum <= 0.0:
            break
        proposed = (basis / basis_sum) * remaining
        clipped = np.minimum(proposed, available)
        spent = float(clipped.sum())
        if spent <= 1e-9:
            break
        allocation += clipped
        available -= clipped
        remaining -= spent
        active = available > 1e-9
        current_weights = np.where(active, current_weights, 0.0)

    return np.minimum(np.maximum(allocation, 0.0), np.maximum(vals - base, 0.0))


def _compute_impact_metrics_from_complete_analysis(
    complete_analysis_payload: dict[str, Any],
    *,
    spacing_m: float,
    network_value_per_km: dict[str, float],
    exposure_value_by_class: dict[str, float],
    component_ratios_by_hazard: dict[str, dict[str, dict[str, float]]] | None = None,
    multi_hazard_proxy: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    assets_raw = complete_analysis_payload.get("asset_results") if isinstance(complete_analysis_payload, dict) else None
    assets = [row for row in (assets_raw or []) if isinstance(row, dict)]
    if not assets:
        raise ValueError("Complete-analysis payload has no asset_results for page-analysis fallback")

    values = np.asarray([max(0.0, _safe_float(row.get("exposure_eur"), 0.0)) for row in assets], dtype=float)
    feature_ids = [str(row.get("asset_id") or f"asset-{idx + 1}") for idx, row in enumerate(assets)]
    class_keys = [_network_class_from_point(row) for row in assets]
    breakdown_class_keys = [_breakdown_class_from_point(row) for row in assets]
    weights_km = np.asarray(
        [
            (float(values[idx]) / float(network_value_per_km[class_key]))
            if class_key in network_value_per_km and float(network_value_per_km[class_key]) > 0.0
            else 0.0
            for idx, class_key in enumerate(class_keys)
        ],
        dtype=float,
    )

    if component_ratios_by_hazard is None:
        component_ratios_by_hazard = _default_component_ratios()
    if multi_hazard_proxy is None:
        multi_hazard_proxy = _default_multi_hazard_proxy(component_ratios_by_hazard)

    scenario_targets = _scenario_targets_from_complete_analysis(complete_analysis_payload)
    all_infra_mask = np.asarray([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
    network_mask = np.asarray([ck in NETWORK_CLASS_LABELS for ck in class_keys], dtype=bool)
    water_mask = np.asarray(
        [
            ck in {"eau_aep", "eau_eu", "eau_aep_ouvrages", "eau_eu_pr", "eau_eu_step"}
            for ck in breakdown_class_keys
        ],
        dtype=bool,
    )

    hazard_outputs: dict[str, Any] = {}
    for hazard_key, asset_key_suffix in (("storm", "storm"), ("storm_cmcc", "cmcc")):
        annual_direct = np.asarray(
            [max(0.0, _safe_float(row.get(f"eai_{asset_key_suffix}_direct_eur"), 0.0)) for row in assets],
            dtype=float,
        )
        annual_total = np.asarray(
            [max(0.0, _safe_float(row.get(f"eai_{asset_key_suffix}_eur"), 0.0)) for row in assets],
            dtype=float,
        )
        annual_total = np.minimum(np.maximum(annual_total, 0.0), values)
        annual_direct = np.minimum(np.maximum(annual_direct, 0.0), annual_total)
        annual_indirect = np.maximum(annual_total - annual_direct, 0.0)

        annual_reference_total = float(scenario_targets.get(hazard_key, {}).get("annual") or float(annual_total[all_infra_mask].sum()))
        if annual_reference_total <= 0.0:
            annual_reference_total = float(annual_total[all_infra_mask].sum())

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

        scenario_results: dict[str, dict[str, Any]] = {}
        direct_losses_by_scenario: dict[str, np.ndarray] = {}
        for scenario in MAP_SCENARIOS:
            base_target_total = float(
                (scenario_targets.get(hazard_key) or {}).get(scenario, annual_reference_total) or annual_reference_total
            )
            if scenario == "annual" or annual_reference_total <= 0.0:
                scenario_scale = 1.0
            else:
                scenario_scale = max(0.0, base_target_total) / max(annual_reference_total, 1e-9)

            raw_direct = np.minimum(np.maximum(annual_direct * scenario_scale, 0.0), values)
            adjusted_direct = _apply_multi_hazard_proxy_to_direct_losses(
                raw_direct,
                values=values,
                breakdown_class_keys=breakdown_class_keys,
                scenario=scenario,
                global_multipliers=scenario_global_multipliers,
                breakdown_shares=scenario_breakdown_shares,
                component_ratios=scenario_component_ratios if isinstance(scenario_component_ratios, dict) else None,
            )

            scenario_multiplier = _safe_float(
                scenario_global_multipliers.get(scenario, scenario_global_multipliers.get("annual", 1.0)),
                1.0,
            )
            target_total = min(float(values[all_infra_mask].sum()), max(0.0, base_target_total * max(0.0, scenario_multiplier)))
            indirect_weights = np.where(water_mask, np.maximum(annual_indirect * scenario_scale, 0.0), 0.0)
            if float(indirect_weights.sum()) <= 0.0:
                indirect_weights = np.where(water_mask, np.maximum(values - adjusted_direct, 0.0), 0.0)
            indirect_alloc = _allocate_additional_loss(
                target_total,
                adjusted_direct,
                values,
                indirect_weights,
            )
            total_loss = np.minimum(values, adjusted_direct + indirect_alloc)

            direct_ratio = np.divide(adjusted_direct, np.maximum(values, 1.0))
            final_ratio = np.divide(total_loss, np.maximum(values, 1.0))
            direct_state = np.asarray([_state_from_ratio(float(v)) for v in direct_ratio], dtype=object)
            final_state = np.asarray([_state_from_ratio(float(v)) for v in final_ratio], dtype=object)
            scenario_results[scenario] = {
                "direct_state": direct_state,
                "final_state": final_state,
                "total_loss": total_loss,
                "indirect_s3_flag": (final_state == "S3") & (direct_state != "S3"),
            }
            direct_losses_by_scenario[scenario] = adjusted_direct

        rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in TABLE_SCENARIOS:
            rows: list[dict[str, Any]] = []
            for network_class_key, label in NETWORK_CLASS_LABELS.items():
                mask = np.asarray([ck == network_class_key for ck in class_keys], dtype=bool)
                total_w = float(weights_km[mask].sum())
                class_exposure = round(float(exposure_value_by_class.get(network_class_key, 0.0)), 2)
                if total_w <= 0.0:
                    state_pct = {s: 0.0 for s in ("S0", "S1", "S2", "S3")}
                    damage_val = 0.0
                else:
                    state_pct = {
                        s: round(
                            float(weights_km[mask & (scenario_results[scenario]["final_state"] == s)].sum())
                            / total_w
                            * 100.0,
                            3,
                        )
                        for s in ("S0", "S1", "S2", "S3")
                    }
                    damage_val = round(float(scenario_results[scenario]["total_loss"][mask].sum()), 2)
                direct_val = round(
                    float(
                        np.minimum(
                            direct_losses_by_scenario[scenario],
                            scenario_results[scenario]["total_loss"],
                        )[mask].sum()
                    ),
                    2,
                )
                indirect_val = round(max(float(damage_val) - float(direct_val), 0.0), 2)
                component_ratios = _normalize_component_ratio_map(
                    scenario_component_ratios.get(scenario) if isinstance(scenario_component_ratios, dict) else None
                )
                rows.append(
                    {
                        "class_key": network_class_key,
                        "class_label": label,
                        "exposure_eur": class_exposure,
                        "state_pct": state_pct,
                        "damage_eur": damage_val,
                        "direct_damage_eur": direct_val,
                        "indirect_damage_eur": indirect_val,
                        "damage_components_eur": _allocate_damage_components(damage_val, component_ratios),
                    }
                )
            rows_by_scenario[scenario] = rows

        breakdown_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in MAP_SCENARIOS:
            rows: list[dict[str, Any]] = []
            for breakdown_class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
                mask = np.asarray([ck == breakdown_class_key for ck in breakdown_class_keys], dtype=bool)
                damage_val = round(float(scenario_results[scenario]["total_loss"][mask].sum()), 2)
                direct_val = round(
                    float(
                        np.minimum(
                            direct_losses_by_scenario[scenario],
                            scenario_results[scenario]["total_loss"],
                        )[mask].sum()
                    ),
                    2,
                )
                indirect_val = round(max(float(damage_val) - float(direct_val), 0.0), 2)
                component_ratios = _normalize_component_ratio_map(
                    scenario_component_ratios.get(scenario) if isinstance(scenario_component_ratios, dict) else None
                )
                rows.append(
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
            breakdown_by_scenario[scenario] = rows

        network_total_w = float(weights_km[network_mask].sum())
        direct_s3_annual = float(weights_km[network_mask & (scenario_results["annual"]["direct_state"] == "S3")].sum())
        direct_s3_event = float(weights_km[network_mask & (scenario_results["event_max"]["direct_state"] == "S3")].sum())
        indirect_s3_annual = float(weights_km[network_mask & scenario_results["annual"]["indirect_s3_flag"]].sum())
        indirect_s3_event = float(weights_km[network_mask & scenario_results["event_max"]["indirect_s3_flag"]].sum())

        hazard_outputs[hazard_key] = {
            "rows_by_scenario": rows_by_scenario,
            "breakdown_by_scenario": breakdown_by_scenario,
            "summary": {
                "direct_hs_pct_annual": round((direct_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "direct_hs_pct_event_max": round((direct_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_annual": round((indirect_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_event_max": round((indirect_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "eai_total_eur": round(float(scenario_results["annual"]["total_loss"][all_infra_mask].sum()), 2),
                "rp50_total_loss_eur": round(float(scenario_results["rp50"]["total_loss"][all_infra_mask].sum()), 2),
                "rp100_total_loss_eur": round(float(scenario_results["rp100"]["total_loss"][all_infra_mask].sum()), 2),
                "event_max_total_loss_eur": round(float(scenario_results["event_max"]["total_loss"][all_infra_mask].sum()), 2),
                "top10_total_loss_eur": round(float(scenario_results["top10"]["total_loss"][all_infra_mask].sum()), 2),
                "top5_total_loss_eur": round(float(scenario_results["top5"]["total_loss"][all_infra_mask].sum()), 2),
                "event_id_max": _event_id_max_from_complete_analysis(complete_analysis_payload, hazard_key),
            },
            "feature_states": {
                scenario: _aggregate_feature_states(feature_ids, scenario_results[scenario]["final_state"])
                for scenario in MAP_SCENARIOS
            },
        }

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
                    "state_pct_event_max": dict(row_storm_event.get("state_pct", {})),
                    "exposure_eur": float(row_storm_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_storm_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_storm_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_storm_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_storm_annual.get("indirect_damage_eur", 0.0)),
                    "direct_event_max_loss_eur": float(row_storm_event.get("direct_damage_eur", 0.0)),
                    "indirect_event_max_loss_eur": float(row_storm_event.get("indirect_damage_eur", 0.0)),
                },
                "storm_cmcc": {
                    "state_pct_annual": dict(row_cmcc_annual.get("state_pct", {})),
                    "state_pct_event_max": dict(row_cmcc_event.get("state_pct", {})),
                    "exposure_eur": float(row_cmcc_annual.get("exposure_eur", 0.0)),
                    "eai_eur": float(row_cmcc_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_cmcc_event.get("damage_eur", 0.0)),
                    "direct_eai_eur": float(row_cmcc_annual.get("direct_damage_eur", 0.0)),
                    "indirect_eai_eur": float(row_cmcc_annual.get("indirect_damage_eur", 0.0)),
                    "direct_event_max_loss_eur": float(row_cmcc_event.get("direct_damage_eur", 0.0)),
                    "indirect_event_max_loss_eur": float(row_cmcc_event.get("indirect_damage_eur", 0.0)),
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
                "storm": hazard_outputs["storm"]["breakdown_by_scenario"][scenario],
                "storm_cmcc": hazard_outputs["storm_cmcc"]["breakdown_by_scenario"][scenario],
            }
            for scenario in MAP_SCENARIOS
        },
        "map_defaults": {
            "hazard": "storm",
            "scenario": "event_max",
        },
    }
    exposure_summary = complete_analysis_payload.get("exposure_summary") if isinstance(complete_analysis_payload, dict) else None
    aux = {
        "hazard_feature_states": {
            "storm": hazard_outputs["storm"]["feature_states"],
            "storm_cmcc": hazard_outputs["storm_cmcc"]["feature_states"],
        },
        "disaggregation": {
            "sampling_spacing_m": float(spacing_m),
            "asset_count_points": int(_safe_float((exposure_summary or {}).get("asset_count_points"), float(len(assets)))),
        },
    }
    return impact_payload, aux


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

    table_lines: list[str] = []
    for line in lines[start_idx + 1 :]:
        if line.strip().startswith("## "):
            break
        if line.strip().startswith("|"):
            table_lines.append(line.rstrip())
    if len(table_lines) < 3:
        return []

    rows: list[dict[str, str]] = []
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
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for feat in geometry_features:
        fid = feat["feature_id"]
        row = {
            "feature_id": fid,
            "layer_key": feat["class_key"],
            "layer_label": feat["class_label"],
        }
        for hazard_key in ("storm", "storm_cmcc"):
            for scenario in MAP_SCENARIOS:
                row[f"state_{scenario}_{hazard_key}"] = hazard_feature_states[hazard_key][scenario].get(fid, "S0")
        rows.append(row)
        geoms.append(feat["geometry"])
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=WGS84)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(gdf.to_json(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all computed data for territory case-study pages (exposition, hazard, impact, conclusion).")
    parser.add_argument("--territory", choices=["guadeloupe", "martinique"], default="guadeloupe")
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
    parser.add_argument(
        "--allow-stale-proxy",
        action="store_true",
        help="Allow page-analysis rebuilds to reuse an older multi-hazard proxy when wind maps are newer.",
    )
    parser.add_argument(
        "--prefer-complete-analysis-fallback",
        action="store_true",
        help="Skip the heavy CLIMADA page-analysis rerun and synthesize page-analysis/network-states directly from complete-analysis asset results.",
    )
    args = parser.parse_args()
    _require_runtime_deps()

    territory = normalize_territory(args.territory)
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
    component_ratios_by_hazard = _load_component_ratio_reference(complete_analysis_json)
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
    allow_stale_proxy = bool(args.allow_stale_proxy)
    if provided_run_id and not wind_map_run_id:
        raise ValueError(
            f"case-study run id provided ({provided_run_id}) but wind map has no case_study_run_id: {wind_map_json}"
        )
    if provided_run_id and not proxy_run_id and multi_hazard_proxy_json.exists() and not allow_stale_proxy:
        raise ValueError(
            f"case-study run id provided ({provided_run_id}) but proxy has no case_study_run_id: {multi_hazard_proxy_json}"
        )
    if wind_map_run_id and not proxy_run_id and multi_hazard_proxy_json.exists() and not allow_stale_proxy:
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
    if provided_run_id and proxy_run_id and provided_run_id != proxy_run_id and not allow_stale_proxy:
        raise ValueError(
            f"case-study run id mismatch: provided={provided_run_id}, multi_hazard_proxy={proxy_run_id}"
        )
    if wind_map_run_id and proxy_run_id and wind_map_run_id != proxy_run_id and not allow_stale_proxy:
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
    fallback_reason: str | None = None
    if bool(args.prefer_complete_analysis_fallback):
        fallback_reason = "forced_complete_analysis_fallback"
        complete_analysis_payload = _load_complete_analysis_payload(complete_analysis_json)
        impact_metrics, aux = _compute_impact_metrics_from_complete_analysis(
            complete_analysis_payload,
            spacing_m=float(args.spacing_m),
            network_value_per_km=exposure_metrics["value_per_km_eur"],
            exposure_value_by_class=exposure_metrics["total_value_by_type_eur"],
            component_ratios_by_hazard=component_ratios_by_hazard,
            multi_hazard_proxy=multi_hazard_proxy,
        )
    else:
        try:
            exposure: NormalizedExposure = build_complete_exposure(
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
                component_light_spacing_m=float(args.component_light_spacing_m),
                component_light_max_points_total=int(args.component_light_max_points_total),
                component_light_max_points_per_feature=int(args.component_light_max_points_per_feature),
                component_light_dynamic_max_tracks=(
                    int(args.component_light_dynamic_max_tracks)
                    if args.component_light_dynamic_max_tracks is not None
                    else None
                ),
            )
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
            complete_analysis_payload = _load_complete_analysis_payload(complete_analysis_json)
            impact_metrics, aux = _compute_impact_metrics_from_complete_analysis(
                complete_analysis_payload,
                spacing_m=float(args.spacing_m),
                network_value_per_km=exposure_metrics["value_per_km_eur"],
                exposure_value_by_class=exposure_metrics["total_value_by_type_eur"],
                component_ratios_by_hazard=component_ratios_by_hazard,
                multi_hazard_proxy=multi_hazard_proxy,
            )
    conclusion_text = _build_conclusion_text(exposure_metrics, impact_metrics)
    zone_wind_compare_rows = _build_zone_wind_comparison_table_from_wind_map_payload(wind_map_payload)
    if not zone_wind_compare_rows:
        raise ValueError(
            f"Unable to build wind comparison table from wind map payload: {wind_map_json}"
        )

    geometry_features = _build_network_geometry_features(case_cfg)
    _build_state_geojson(geometry_features, aux["hazard_feature_states"], out_state_geojson)

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
            "valuation_source": SOURCE_LABEL,
            "valuation_territory": str(valuation_metadata["territory_effective"]),
            "valuation_version": str(valuation_metadata["valuation_version"]),
            "notes": (
                [
                    "Fallback page analysis generated from complete-analysis asset results because the heavy case-study CLIMADA page-analysis rerun was skipped or failed.",
                    f"Fallback reason: {fallback_reason}",
                ]
                if fallback_reason
                else []
            ),
            "modeling": {
                "source": "complete_analysis_asset_fallback" if fallback_reason else "case_study_page_analysis",
                "fallback": bool(fallback_reason),
            },
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
    if fallback_reason:
        print(f"fallback_page_analysis=true reason={fallback_reason}")


if __name__ == "__main__":
    main()
