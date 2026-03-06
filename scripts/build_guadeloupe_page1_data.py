#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from climada.engine import ImpactCalc
from climada.entity.impact_funcs import ImpactFuncSet


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.exposure_to_climada import build_climada_exposure  # noqa: E402
from app.risk_engine.hazard_loader import load_storm_hazards  # noqa: E402
from app.risk_engine.impact_functions import try_build_climada_impact_func  # noqa: E402
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
TABLE_SCENARIOS = ("annual", "rp100", "rp1000", "event_max")
MAP_SCENARIOS = ("annual", "rp100", "rp1000", "event_max", "top10", "top5")
WIND_BIN_STEP_MPS = 1.0


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


def _line_length_km(gdf: gpd.GeoDataFrame) -> float:
    _, gdf_metric = _as_wgs84_and_metric(gdf)
    total_m = float(gdf_metric.geometry.length.fillna(0.0).sum())
    return max(0.0, total_m / 1000.0)


def _count_features(paths: list[Path]) -> int:
    count = 0
    for path in paths:
        gdf = _ensure_crs(gpd.read_file(path))
        count += int(len(gdf))
    return count


def _count_aep_ouvrage_types(case_cfg: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for src in case_cfg["aep_ouvrage_sources"]:
        mode = str(src.get("mode", "")).strip().lower()
        for path in src["paths"]:
            gdf = _ensure_crs(gpd.read_file(path))
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
            gdf = _ensure_crs(gpd.read_file(path))
            lengths_km[class_key] += _line_length_km(gdf)
            elec_lines_total += int(len(gdf))

    for src in case_cfg["water_line_sources"]:
        class_key = str(src["class_key"])
        for path in src["paths"]:
            gdf = _ensure_crs(gpd.read_file(path))
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
            eu_pr_total += _count_features(list(src["paths"]))
        if str(src["asset_type"]) == "eau_eu_step":
            eu_step_total += _count_features(list(src["paths"]))
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
        gdf = _ensure_crs(gpd.read_file(path)).to_crs(WGS84)
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


def _compute_impact_metrics(
    exposure: NormalizedExposure,
    *,
    spacing_m: float,
    settings: Any,
    network_value_per_km: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    impf = try_build_climada_impact_func()
    if impf is None:
        raise RuntimeError("Unable to instantiate CLIMADA impact function")
    impfset = ImpactFuncSet([impf])

    disagg = summarize_disaggregation(exposure, spacing_m=spacing_m)
    bundle = build_climada_exposure(
        exposure,
        spacing_m=spacing_m,
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=settings.climada_max_points_per_feature,
    )
    hazards = load_storm_hazards(settings.hazard_storm_path, settings.hazard_storm_cmcc_path, settings.storm_years)

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

    hazard_outputs: dict[str, Any] = {}
    for hazard_key, hazard_obj in {"storm": hazards.storm, "storm_cmcc": hazards.storm_cmcc}.items():
        impact = ImpactCalc(bundle.exposures, impfset, hazard_obj).impact(save_mat=False, assign_centroids=True)
        eai_direct = np.asarray(impact.eai_exp, dtype=float).reshape(-1)
        eai_direct = np.nan_to_num(eai_direct, nan=0.0, posinf=0.0, neginf=0.0)
        eai_direct = np.minimum(np.maximum(eai_direct, 0.0), values)
        at_event = np.asarray(impact.at_event, dtype=float).reshape(-1)
        at_event = np.nan_to_num(at_event, nan=0.0, posinf=0.0, neginf=0.0)
        freq = np.asarray(getattr(hazard_obj, "frequency", np.array([])), dtype=float).reshape(-1)
        if freq.size != at_event.size or float(np.nansum(freq)) <= 0.0:
            freq = np.full(at_event.size, 1.0 / max(1, at_event.size), dtype=float)
        event_idx = int(np.argmax(at_event)) if len(at_event) else 0
        event_id_max = int(getattr(impact, "event_id", [event_idx + 1])[event_idx]) if len(getattr(impact, "event_id", [])) else int(event_idx + 1)
        global_scenario_losses = {
            "event_max": float(at_event[event_idx]) if len(at_event) else 0.0,
            "rp100": _loss_at_return_period(at_event, freq, 100.0),
            "rp1000": _loss_at_return_period(at_event, freq, 1000.0),
            "top10": _mean_top_fraction(at_event, 0.10),
            "top5": _mean_top_fraction(at_event, 0.05),
        }
        global_eai = float(eai_direct.sum())
        global_scenario_factors = {
            scenario: (max(0.0, loss) / max(global_eai, 1e-9)) for scenario, loss in global_scenario_losses.items()
        }

        class_scenario_factors: dict[str, dict[str, float]] = {
            "event_max": {},
            "rp100": {},
            "rp1000": {},
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
                "rp100": _loss_at_return_period(class_at_event, freq, 100.0),
                "rp1000": _loss_at_return_period(class_at_event, freq, 1000.0),
                "top10": _mean_top_fraction(class_at_event, 0.10),
                "top5": _mean_top_fraction(class_at_event, 0.05),
            }
            for scenario, scenario_loss in class_scenario_losses.items():
                class_scenario_factors[scenario][class_key] = max(0.0, float(scenario_loss)) / max(class_eai, 1e-9)

        direct_losses_by_scenario: dict[str, np.ndarray] = {"annual": np.array(eai_direct, dtype=float)}
        for scenario in ("event_max", "rp100", "rp1000", "top10", "top5"):
            scenario_direct = np.zeros_like(eai_direct, dtype=float)
            for i, bclass in enumerate(breakdown_class_keys):
                factor = class_scenario_factors[scenario].get(str(bclass), global_scenario_factors[scenario])
                scenario_direct[i] = float(eai_direct[i]) * max(0.0, float(factor))
            direct_losses_by_scenario[scenario] = np.minimum(np.maximum(scenario_direct, 0.0), values)

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
                "direct_state": direct_state,
                "final_state": final_state_arr,
                "total_loss": np.minimum(np.maximum(total_loss, 0.0), values),
                "indirect_s3_flag": indirect_s3_flag,
            }

        scenario_results = {
            scenario: evaluate_scenario(direct_losses_by_scenario[scenario]) for scenario in MAP_SCENARIOS
        }

        rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in TABLE_SCENARIOS:
            rows: list[dict[str, Any]] = []
            for network_class_key, label in NETWORK_CLASS_LABELS.items():
                mask = np.array([ck == network_class_key for ck in class_keys], dtype=bool)
                total_w = float(weights_km[mask].sum())
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
                rows.append(
                    {
                        "class_key": network_class_key,
                        "class_label": label,
                        "state_pct": state_pct,
                        "damage_eur": damage_val,
                    }
                )
            rows_by_scenario[scenario] = rows

        breakdown_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for scenario in MAP_SCENARIOS:
            breakdown_rows: list[dict[str, Any]] = []
            for breakdown_class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
                mask = np.array([ck == breakdown_class_key for ck in breakdown_class_keys], dtype=bool)
                breakdown_rows.append(
                    {
                        "class_key": breakdown_class_key,
                        "class_label": label,
                        "damage_eur": round(float(scenario_results[scenario]["total_loss"][mask].sum()), 2),
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
                "rp100_total_loss_eur": round(float(scenario_results["rp100"]["total_loss"][all_infra_mask].sum()), 2),
                "rp1000_total_loss_eur": round(float(scenario_results["rp1000"]["total_loss"][all_infra_mask].sum()), 2),
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
                    "eai_eur": float(row_storm_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_storm_event.get("damage_eur", 0.0)),
                },
                "storm_cmcc": {
                    "state_pct_annual": dict(row_cmcc_annual.get("state_pct", {})),
                    "state_pct_event_max": dict(row_cmcc_event.get("state_pct", {})),
                    "eai_eur": float(row_cmcc_annual.get("damage_eur", 0.0)),
                    "event_max_loss_eur": float(row_cmcc_event.get("damage_eur", 0.0)),
                },
            }
        )

    impact_payload = {
        "summary_text": summary_text,
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
    return {"class_key": class_key, "class_label": NETWORK_CLASS_LABELS.get(class_key, class_key), "state_pct": {s: 0.0 for s in ("S0", "S1", "S2", "S3")}, "damage_eur": 0.0}


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
                        "damage_eur": float(storm_row.get("damage_eur", 0.0)),
                    },
                    "storm_cmcc": {
                        "state_pct": dict(cmcc_row.get("state_pct", {})),
                        "damage_eur": float(cmcc_row.get("damage_eur", 0.0)),
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
            }
        )
    return rows


def _build_impact_summary_text(hazard_outputs: dict[str, Any]) -> str:
    s = hazard_outputs["storm"]["summary"]
    c = hazard_outputs["storm_cmcc"]["summary"]
    return (
        f"STORM: EAI {s['eai_total_eur']:.0f} €, RP100 {s['rp100_total_loss_eur']:.0f} €, "
        f"RP1000 {s['rp1000_total_loss_eur']:.0f} €, evt max {s['event_max_total_loss_eur']:.0f} €. "
        f"STORM_CMCC: EAI {c['eai_total_eur']:.0f} €, RP100 {c['rp100_total_loss_eur']:.0f} €, "
        f"RP1000 {c['rp1000_total_loss_eur']:.0f} €, evt max {c['event_max_total_loss_eur']:.0f} €."
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
        f"Scenario temps de retour 100 ans: STORM {m_eur_rounded(storm['rp100_total_loss_eur'])} M€ ({pct_of_portfolio(storm['rp100_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['rp100_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['rp100_total_loss_eur'])} %). "
        f"Scenario temps de retour 1000 ans: STORM {m_eur_rounded(storm['rp1000_total_loss_eur'])} M€ ({pct_of_portfolio(storm['rp1000_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['rp1000_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['rp1000_total_loss_eur'])} %). "
        f"Evenement le plus extreme: STORM {m_eur_rounded(storm['event_max_total_loss_eur'])} M€ ({pct_of_portfolio(storm['event_max_total_loss_eur'])} %), "
        f"STORM_CMCC {m_eur_rounded(cmcc['event_max_total_loss_eur'])} M€ ({pct_of_portfolio(cmcc['event_max_total_loss_eur'])} %)."
    )


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
        rows.append(
            {
                "indicator": cells[0],
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
    parser.add_argument("--storm-source", default="/home/ubuntu/uploads/STORM/STORM_ds")
    parser.add_argument("--cmcc-source", default="/home/ubuntu/uploads/STORM/STORM_CMCC_ds")
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in STORM/STORM_CMCC datasets. Supported: m/s, kn, km/h. Output is always m/s.",
    )
    parser.add_argument("--spacing-m", type=float, default=100.0)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-state-geojson", default=None)
    parser.add_argument("--diagnostic-md", default=str(REPO_ROOT / "docs" / "diagnostic-vents-et-mailles.md"))
    args = parser.parse_args()

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
    diagnostic_md = Path(args.diagnostic_md)

    settings = load_settings()
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)
    valuation_metadata = build_valuation_metadata(territory)

    exposure_metrics = _build_exposure_metrics(case_cfg, territory)
    hazard_hist = _build_wind_histograms(
        Path(args.storm_source),
        Path(args.cmcc_source),
        wind_unit_in=normalized_wind_unit,
    )
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
    )
    conclusion_text = _build_conclusion_text(exposure_metrics, impact_metrics)
    zone_wind_compare_rows = _load_zone_wind_comparison_table(
        diagnostic_md,
        str(case_cfg["wind_comparison_heading"]),
    )

    geometry_features = _build_network_geometry_features(case_cfg)
    _build_state_geojson(geometry_features, aux["hazard_feature_states"], out_state_geojson)

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source": f"{territory}_case_study_computed",
            "case_study_territory": territory,
            "case_study_label": territory_label(territory),
            "sampling_spacing_m": float(args.spacing_m),
            "hazards": ["STORM", "STORM_CMCC"],
            "storm_years": int(settings.storm_years),
            "valuation_source": SOURCE_LABEL,
            "valuation_territory": str(valuation_metadata["territory_effective"]),
            "valuation_version": str(valuation_metadata["valuation_version"]),
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

    print(f"Wrote {out_json}")
    print(f"Wrote {out_state_geojson}")
    print(f"territory={territory}")
    print(f"State map features: {len(geometry_features)}")
    print(f"EAI STORM: {impact_metrics['summary_metrics']['storm']['eai_total_eur']}")
    print(f"EAI STORM_CMCC: {impact_metrics['summary_metrics']['storm_cmcc']['eai_total_eur']}")


if __name__ == "__main__":
    main()
