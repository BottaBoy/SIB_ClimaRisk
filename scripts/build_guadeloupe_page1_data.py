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
    METRIC_CRS,
    WGS84,
    _aep_ouvrage_value,
    _as_wgs84_and_metric,
    _ensure_crs,
    build_complete_exposure,
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

NETWORK_VALUE_PER_KM = {
    "eau_aep": 280_000.0,
    "eau_eu": 340_000.0,
    "elec_bt_souterrain": 320_000.0,
    "elec_bt_aerien": 180_000.0,
    "elec_hta_souterrain": 520_000.0,
    "elec_hta_aerien": 260_000.0,
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


def _histogram_percent(values: pd.Series, bins: int = 12) -> dict[str, Any]:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    vals = vals[np.isfinite(vals)]
    if vals.empty:
        return {"bins_mps": [], "percent": [], "count": 0}
    hist, edges = np.histogram(vals.to_numpy(dtype=float), bins=bins)
    pct = (hist / max(1, hist.sum())) * 100.0
    bin_centers = 0.5 * (edges[:-1] + edges[1:])
    return {
        "bins_mps": [round(float(x), 3) for x in bin_centers.tolist()],
        "percent": [round(float(x), 4) for x in pct.tolist()],
        "count": int(len(vals)),
    }


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
        "track_max_hist": _histogram_percent(track_series, bins=12),
        "year_max_hist": _histogram_percent(year_series, bins=12),
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
        "track_max_hist": _histogram_percent(storm_track_max, bins=12),
        "year_max_hist": _histogram_percent(storm_year_max, bins=12),
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

    return {"storm": storm, "storm_cmcc": cmcc}


def _line_length_km(gdf: gpd.GeoDataFrame) -> float:
    _, gdf_metric = _as_wgs84_and_metric(gdf)
    total_m = float(gdf_metric.geometry.length.fillna(0.0).sum())
    return max(0.0, total_m / 1000.0)


def _build_exposure_metrics(infra_elec_dir: Path, infra_eau_dir: Path) -> dict[str, Any]:
    elec_bt_aer = _ensure_crs(gpd.read_file(infra_elec_dir / "lignes-basse-tension-bt-aerien-gua.geojson"))
    elec_bt_sou = _ensure_crs(gpd.read_file(infra_elec_dir / "lignes-basse-tension-bt-souterrain-gua.geojson"))
    elec_hta_aer = _ensure_crs(gpd.read_file(infra_elec_dir / "lignes-haute-tension-hta-aerien-gua.geojson"))
    elec_hta_sou = _ensure_crs(gpd.read_file(infra_elec_dir / "lignes-haute-tension-hta-souterrain-gua.geojson"))
    aep_cana = _ensure_crs(gpd.read_file(infra_eau_dir / "AEP" / "cana_aep.gpkg"))
    eu_cana = _ensure_crs(gpd.read_file(infra_eau_dir / "EU" / "cana_eu.gpkg"))
    aep_ouvr = _ensure_crs(gpd.read_file(infra_eau_dir / "AEP" / "ouvrage_aep.gpkg"))
    eu_pr = _ensure_crs(gpd.read_file(infra_eau_dir / "EU" / "pr.gpkg"))
    eu_step = _ensure_crs(gpd.read_file(infra_eau_dir / "EU" / "step.gpkg"))

    lengths_km = {
        "elec_bt_aerien": _line_length_km(elec_bt_aer),
        "elec_bt_souterrain": _line_length_km(elec_bt_sou),
        "elec_hta_aerien": _line_length_km(elec_hta_aer),
        "elec_hta_souterrain": _line_length_km(elec_hta_sou),
        "eau_aep": _line_length_km(aep_cana),
        "eau_eu": _line_length_km(eu_cana),
    }

    value_per_km = dict(NETWORK_VALUE_PER_KM)
    total_value_network = {
        key: round(lengths_km[key] * value_per_km[key], 2) for key in NETWORK_VALUE_PER_KM.keys()
    }

    aep_type_counts = aep_ouvr["ovrg_type"].fillna("NA").astype(str).str.upper().value_counts().to_dict()
    total_value_aep_ouvr = round(sum(_aep_ouvrage_value(k) * int(v) for k, v in aep_type_counts.items()), 2)
    total_value_pr = round(float(len(eu_pr)) * 900_000.0, 2)
    total_value_step = round(float(len(eu_step)) * 6_000_000.0, 2)

    counts = {
        "aep_ouvrages_total": int(len(aep_ouvr)),
        "aep_ouvrages_by_type": {str(k): int(v) for k, v in aep_type_counts.items()},
        "eu_pr_total": int(len(eu_pr)),
        "eu_step_total": int(len(eu_step)),
        "elec_lines_total": int(len(elec_bt_aer) + len(elec_bt_sou) + len(elec_hta_aer) + len(elec_hta_sou)),
        "water_lines_total": int(len(aep_cana) + len(eu_cana)),
    }

    total_value_by_type = {
        **total_value_network,
        "eau_aep_ouvrages": total_value_aep_ouvr,
        "eau_eu_pr": total_value_pr,
        "eau_eu_step": total_value_step,
    }
    total_value_all = round(sum(total_value_by_type.values()), 2)

    summary_text = (
        f"Le jeu de reference comprend {counts['elec_lines_total']} troncons electriques et {counts['water_lines_total']} troncons d'eau. "
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


def _build_network_geometry_features(infra_elec_dir: Path, infra_eau_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def append_lines(path: Path, class_key: str, prefix: str) -> None:
        gdf = _ensure_crs(gpd.read_file(path)).to_crs(WGS84)
        for idx, geom in enumerate(gdf.geometry, start=1):
            if geom is None or getattr(geom, "is_empty", False):
                continue
            out.append(
                {
                    "feature_id": f"{prefix}-{idx}",
                    "class_key": class_key,
                    "class_label": NETWORK_CLASS_LABELS[class_key],
                    "geometry": geom,
                }
            )

    append_lines(infra_elec_dir / "lignes-basse-tension-bt-aerien-gua.geojson", "elec_bt_aerien", "elec-bt-aerien")
    append_lines(infra_elec_dir / "lignes-basse-tension-bt-souterrain-gua.geojson", "elec_bt_souterrain", "elec-bt-souterrain")
    append_lines(infra_elec_dir / "lignes-haute-tension-hta-aerien-gua.geojson", "elec_hta_aerien", "elec-hta-aerien")
    append_lines(infra_elec_dir / "lignes-haute-tension-hta-souterrain-gua.geojson", "elec_hta_souterrain", "elec-hta-souterrain")
    append_lines(infra_eau_dir / "AEP" / "cana_aep.gpkg", "eau_aep", "aep-cana")
    append_lines(infra_eau_dir / "EU" / "cana_eu.gpkg", "eau_eu", "eu-cana")
    return out


def _compute_impact_metrics(
    exposure: NormalizedExposure,
    *,
    spacing_m: float,
    settings: Any,
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
            (float(rec["value_eur"]) / NETWORK_VALUE_PER_KM[class_key]) if class_key in NETWORK_VALUE_PER_KM else 0.0
            for rec, class_key in zip(bundle.point_records, class_keys)
        ],
        dtype=float,
    )

    hazard_outputs: dict[str, Any] = {}
    for hazard_key, hazard_obj in {"storm": hazards.storm, "storm_cmcc": hazards.storm_cmcc}.items():
        impact = ImpactCalc(bundle.exposures, impfset, hazard_obj).impact(save_mat=False, assign_centroids=True)
        eai_direct = np.asarray(impact.eai_exp, dtype=float).reshape(-1)
        eai_direct = np.nan_to_num(eai_direct, nan=0.0, posinf=0.0, neginf=0.0)
        at_event = np.asarray(impact.at_event, dtype=float).reshape(-1)
        at_event = np.nan_to_num(at_event, nan=0.0, posinf=0.0, neginf=0.0)
        event_idx = int(np.argmax(at_event)) if len(at_event) else 0
        event_id_max = int(getattr(impact, "event_id", [event_idx + 1])[event_idx]) if len(getattr(impact, "event_id", [])) else int(event_idx + 1)

        global_event_factor = float(at_event[event_idx] / max(float(eai_direct.sum()), 1e-9)) if len(at_event) else 0.0
        class_event_factor: dict[str, float] = {}
        for class_key in GLOBAL_EVENT_CLASS_KEYS:
            class_mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
            class_eai = float(eai_direct[class_mask].sum())
            if class_eai <= 0.0 or not class_mask.any() or len(at_event) == 0:
                class_event_factor[class_key] = 0.0
                continue

            subset = bundle.exposures.copy(deep=False)
            subset.set_gdf(
                bundle.exposures.gdf.iloc[np.where(class_mask)[0]].reset_index(drop=True),
                crs=bundle.exposures.crs,
            )
            class_impact = ImpactCalc(subset, impfset, hazard_obj).impact(save_mat=False, assign_centroids=True)
            class_at_event = np.asarray(class_impact.at_event, dtype=float).reshape(-1)
            class_at_event = np.nan_to_num(class_at_event, nan=0.0, posinf=0.0, neginf=0.0)
            class_event_loss = float(class_at_event[event_idx]) if event_idx < len(class_at_event) else 0.0
            class_event_factor[class_key] = class_event_loss / class_eai if class_eai > 0.0 else 0.0

        event_loss = np.zeros_like(eai_direct)
        for i, bclass in enumerate(breakdown_class_keys):
            factor = class_event_factor.get(str(bclass), global_event_factor)
            event_loss[i] = float(eai_direct[i]) * max(0.0, float(factor))

        direct_ratio_annual = np.divide(eai_direct, np.maximum(values, 1.0))
        direct_ratio_event = np.divide(event_loss, np.maximum(values, 1.0))
        direct_state_annual = np.array([_state_from_ratio(float(v)) for v in direct_ratio_annual], dtype=object)
        direct_state_event = np.array([_state_from_ratio(float(v)) for v in direct_ratio_event], dtype=object)

        # Electricity health by territory (annual scenario)
        elec_buckets_annual: dict[str, dict[str, float]] = defaultdict(_new_health_bucket)
        elec_buckets_event: dict[str, dict[str, float]] = defaultdict(_new_health_bucket)
        for i, class_key in enumerate(class_keys):
            if class_key is None or not class_key.startswith("elec_"):
                continue
            w = float(weights_km[i])
            _add_state(elec_buckets_annual[territories[i]], str(direct_state_annual[i]), w)
            _add_state(elec_buckets_event[territories[i]], str(direct_state_event[i]), w)
        elec_health_annual = {k: _health(v) for k, v in elec_buckets_annual.items()}
        elec_health_event = {k: _health(v) for k, v in elec_buckets_event.items()}
        global_health_annual = _health(_merge_buckets(list(elec_buckets_annual.values())))
        global_health_event = _health(_merge_buckets(list(elec_buckets_event.values())))

        final_state_annual: list[str] = []
        final_state_event: list[str] = []
        indirect_eai = np.zeros_like(eai_direct)
        total_event_loss = np.array(event_loss, dtype=float)
        indirect_s3_flag_annual = np.zeros_like(eai_direct, dtype=bool)
        indirect_s3_flag_event = np.zeros_like(eai_direct, dtype=bool)

        for i, class_key in enumerate(class_keys):
            state_a = str(direct_state_annual[i])
            state_e = str(direct_state_event[i])
            if class_key in {"eau_aep", "eau_eu"}:
                dep_a = _dependency_state_from_elec_health(elec_health_annual.get(territories[i], global_health_annual))
                dep_e = _dependency_state_from_elec_health(elec_health_event.get(territories[i], global_health_event))
                final_a = dep_a if STATE_ORDER[dep_a] > STATE_ORDER[state_a] else state_a
                final_e = dep_e if STATE_ORDER[dep_e] > STATE_ORDER[state_e] else state_e
                uplift_a = UPLIFT_BY_STATE[dep_a]
                uplift_e = UPLIFT_BY_STATE[dep_e]
                indirect_eai[i] = eai_direct[i] * uplift_a
                total_event_loss[i] = event_loss[i] * (1.0 + uplift_e)
                indirect_s3_flag_annual[i] = final_a == "S3" and state_a != "S3"
                indirect_s3_flag_event[i] = final_e == "S3" and state_e != "S3"
                final_state_annual.append(final_a)
                final_state_event.append(final_e)
            else:
                final_state_annual.append(state_a)
                final_state_event.append(state_e)
        final_state_annual_arr = np.array(final_state_annual, dtype=object)
        final_state_event_arr = np.array(final_state_event, dtype=object)
        total_eai = eai_direct + indirect_eai

        rows: list[dict[str, Any]] = []
        for class_key, label in NETWORK_CLASS_LABELS.items():
            mask = np.array([ck == class_key for ck in class_keys], dtype=bool)
            total_w = float(weights_km[mask].sum())
            if total_w <= 0:
                state_annual_pct = {s: 0.0 for s in ("S0", "S1", "S2", "S3")}
                state_event_pct = {s: 0.0 for s in ("S0", "S1", "S2", "S3")}
                eai_val = 0.0
                event_val = 0.0
            else:
                state_annual_pct = {
                    s: round(float(weights_km[mask & (final_state_annual_arr == s)].sum()) / total_w * 100.0, 3)
                    for s in ("S0", "S1", "S2", "S3")
                }
                state_event_pct = {
                    s: round(float(weights_km[mask & (final_state_event_arr == s)].sum()) / total_w * 100.0, 3)
                    for s in ("S0", "S1", "S2", "S3")
                }
                eai_val = round(float(total_eai[mask].sum()), 2)
                event_val = round(float(total_event_loss[mask].sum()), 2)
            rows.append(
                {
                    "class_key": class_key,
                    "class_label": label,
                    "state_pct_annual": state_annual_pct,
                    "state_pct_event_max": state_event_pct,
                    "eai_eur": eai_val,
                    "event_max_loss_eur": event_val,
                }
            )

        breakdown_rows: list[dict[str, Any]] = []
        for class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
            mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
            breakdown_rows.append(
                {
                    "class_key": class_key,
                    "class_label": label,
                    "eai_eur": round(float(total_eai[mask].sum()), 2),
                    "event_max_loss_eur": round(float(total_event_loss[mask].sum()), 2),
                }
            )

        all_infra_mask = np.array([ck in DAMAGE_BREAKDOWN_LABELS for ck in breakdown_class_keys], dtype=bool)
        network_mask = np.array([ck in NETWORK_CLASS_LABELS for ck in class_keys], dtype=bool)
        network_total_w = float(weights_km[network_mask].sum())
        direct_s3_annual = float(weights_km[network_mask & (direct_state_annual == "S3")].sum())
        direct_s3_event = float(weights_km[network_mask & (direct_state_event == "S3")].sum())
        indirect_s3_annual = float(weights_km[network_mask & indirect_s3_flag_annual].sum())
        indirect_s3_event = float(weights_km[network_mask & indirect_s3_flag_event].sum())

        hazard_outputs[hazard_key] = {
            "rows": rows,
            "summary": {
                "direct_hs_pct_annual": round((direct_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "direct_hs_pct_event_max": round((direct_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_annual": round((indirect_s3_annual / max(network_total_w, 1e-9)) * 100.0, 3),
                "indirect_hs_pct_event_max": round((indirect_s3_event / max(network_total_w, 1e-9)) * 100.0, 3),
                "eai_total_eur": round(float(total_eai[all_infra_mask].sum()), 2),
                "event_max_total_loss_eur": round(float(total_event_loss[all_infra_mask].sum()), 2),
                "event_id_max": event_id_max,
            },
            "feature_states": {
                "annual": _aggregate_feature_states(feature_ids, final_state_annual_arr),
                "event_max": _aggregate_feature_states(feature_ids, final_state_event_arr),
            },
            "breakdown_rows": breakdown_rows,
        }

    merged_rows = _merge_rows_by_class(hazard_outputs)
    summary_text = _build_impact_summary_text(hazard_outputs)

    impact_payload = {
        "summary_text": summary_text,
        "summary_metrics": {haz: hazard_outputs[haz]["summary"] for haz in ("storm", "storm_cmcc")},
        "state_damage_table": merged_rows,
        "damage_breakdown": {
            "storm": hazard_outputs["storm"]["breakdown_rows"],
            "storm_cmcc": hazard_outputs["storm_cmcc"]["breakdown_rows"],
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


def _merge_rows_by_class(hazard_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    by_class: dict[str, dict[str, Any]] = {}
    for hazard_key in ("storm", "storm_cmcc"):
        for row in hazard_outputs[hazard_key]["rows"]:
            class_key = row["class_key"]
            entry = by_class.setdefault(class_key, {"class_key": class_key, "class_label": row["class_label"]})
            entry[hazard_key] = {
                "state_pct_annual": row["state_pct_annual"],
                "state_pct_event_max": row["state_pct_event_max"],
                "eai_eur": row["eai_eur"],
                "event_max_loss_eur": row["event_max_loss_eur"],
            }
    ordered = [by_class[k] for k in NETWORK_CLASS_LABELS.keys() if k in by_class]
    return ordered


def _build_impact_summary_text(hazard_outputs: dict[str, Any]) -> str:
    s = hazard_outputs["storm"]["summary"]
    c = hazard_outputs["storm_cmcc"]["summary"]
    return (
        f"STORM: hors service direct S3 annuel {s['direct_hs_pct_annual']:.2f}% et additionnel lie a la dependance electrique {s['indirect_hs_pct_annual']:.2f}%. "
        f"Evenement le plus fort: direct {s['direct_hs_pct_event_max']:.2f}% et indirect {s['indirect_hs_pct_event_max']:.2f}%. "
        f"STORM_CMCC: hors service direct S3 annuel {c['direct_hs_pct_annual']:.2f}% et additionnel {c['indirect_hs_pct_annual']:.2f}%. "
        f"Evenement le plus fort: direct {c['direct_hs_pct_event_max']:.2f}% et indirect {c['indirect_hs_pct_event_max']:.2f}%."
    )


def _build_conclusion_text(exposure_metrics: dict[str, Any], impact_metrics: dict[str, Any]) -> str:
    storm = impact_metrics["summary_metrics"]["storm"]
    cmcc = impact_metrics["summary_metrics"]["storm_cmcc"]
    worst_hazard = "STORM" if storm["eai_total_eur"] >= cmcc["eai_total_eur"] else "STORM_CMCC"
    return (
        f"L'analyse montre un portefeuille de reseaux valorise a {exposure_metrics['total_value_all_eur'] / 1_000_000:.1f} M€. "
        f"Les dommages annuels moyens modelises sont de {storm['eai_total_eur'] / 1_000_000:.3f} M€ (STORM) et "
        f"{cmcc['eai_total_eur'] / 1_000_000:.3f} M€ (STORM_CMCC). "
        f"Le scenario le plus contraignant en EAI est {worst_hazard}. "
        "Recommandations: renforcer en priorite les troncons classes S2/S3, securiser l'alimentation electrique des reseaux d'eau, "
        "et preparer des plans de reconfiguration rapide en cas d'evenement majeur."
    )


def _build_state_geojson(
    geometry_features: list[dict[str, Any]],
    hazard_feature_states: dict[str, Any],
    out_path: Path,
) -> None:
    rows: list[dict[str, Any]] = []
    geoms: list[Any] = []
    for feat in geometry_features:
        fid = feat["feature_id"]
        rows.append(
            {
                "feature_id": fid,
                "layer_key": feat["class_key"],
                "layer_label": feat["class_label"],
                "state_annual_storm": hazard_feature_states["storm"]["annual"].get(fid, "S0"),
                "state_event_max_storm": hazard_feature_states["storm"]["event_max"].get(fid, "S0"),
                "state_annual_storm_cmcc": hazard_feature_states["storm_cmcc"]["annual"].get(fid, "S0"),
                "state_event_max_storm_cmcc": hazard_feature_states["storm_cmcc"]["event_max"].get(fid, "S0"),
            }
        )
        geoms.append(feat["geometry"])
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=WGS84)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(gdf.to_json(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all computed data for Guadeloupe page 1 (exposition, hazard, impact, conclusion).")
    parser.add_argument("--infra-elec-dir", default="/home/ubuntu/uploads/Infra_Elec_Guadeloupe")
    parser.add_argument("--infra-eau-dir", default="/home/ubuntu/uploads/Infra_Eau_Guadeloupe")
    parser.add_argument("--storm-source", default="/home/ubuntu/uploads/STORM/STORM_ds")
    parser.add_argument("--cmcc-source", default="/home/ubuntu/uploads/STORM/STORM_CMCC_ds")
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in STORM/STORM_CMCC datasets. Supported: m/s, kn, km/h. Output is always m/s.",
    )
    parser.add_argument("--spacing-m", type=float, default=100.0)
    parser.add_argument("--out-json", default=str(REPO_ROOT / "web" / "data" / "guadeloupe-page1-analysis.json"))
    parser.add_argument("--out-state-geojson", default=str(REPO_ROOT / "web" / "data" / "guadeloupe-network-states.geojson"))
    args = parser.parse_args()

    infra_elec_dir = Path(args.infra_elec_dir)
    infra_eau_dir = Path(args.infra_eau_dir)
    out_json = Path(args.out_json)
    out_state_geojson = Path(args.out_state_geojson)

    settings = load_settings()
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)

    exposure_metrics = _build_exposure_metrics(infra_elec_dir, infra_eau_dir)
    hazard_hist = _build_wind_histograms(
        Path(args.storm_source),
        Path(args.cmcc_source),
        wind_unit_in=normalized_wind_unit,
    )
    exposure: NormalizedExposure = build_complete_exposure(infra_elec_dir=infra_elec_dir, infra_eau_dir=infra_eau_dir)
    impact_metrics, aux = _compute_impact_metrics(exposure, spacing_m=float(args.spacing_m), settings=settings)
    conclusion_text = _build_conclusion_text(exposure_metrics, impact_metrics)

    geometry_features = _build_network_geometry_features(infra_elec_dir, infra_eau_dir)
    _build_state_geojson(geometry_features, aux["hazard_feature_states"], out_state_geojson)

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source": "guadeloupe_page1_computed",
            "sampling_spacing_m": float(args.spacing_m),
            "hazards": ["STORM", "STORM_CMCC"],
            "storm_years": int(settings.storm_years),
        },
        "exposition": exposure_metrics,
        "hazard": {
            "summary_text": (
                "STORM et STORM_CMCC sont des catalogues synthetiques de trajectoires cycloniques (10 000 ans, bassin NA). "
                "Les distributions ci-dessous sont calculees directement depuis les fichiers STORM/CMCC en vitesse maximale du vent."
            ),
            "wind_unit_in": normalized_wind_unit,
            "wind_unit_out": "m/s",
            "wind_histograms": hazard_hist,
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
    print(f"State map features: {len(geometry_features)}")
    print(f"EAI STORM: {impact_metrics['summary_metrics']['storm']['eai_total_eur']}")
    print(f"EAI STORM_CMCC: {impact_metrics['summary_metrics']['storm_cmcc']['eai_total_eur']}")


if __name__ == "__main__":
    main()
