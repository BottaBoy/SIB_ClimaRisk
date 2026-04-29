#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fiona
except Exception:  # pragma: no cover - optional at import time for CLI --help
    fiona = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

try:
    import rasterio
    from rasterio.features import shapes
    from rasterio.windows import from_bounds
except Exception:  # pragma: no cover - optional at import time for CLI --help
    rasterio = None  # type: ignore[assignment]
    shapes = None  # type: ignore[assignment]
    from_bounds = None  # type: ignore[assignment]

try:
    from shapely.geometry import box, shape
    from shapely.ops import unary_union
except Exception:  # pragma: no cover - optional at import time for CLI --help
    box = None  # type: ignore[assignment]
    shape = None  # type: ignore[assignment]
    unary_union = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.risk_engine.climada_engine import _prepare_topo_raster_with_crs  # noqa: E402
from app.risk_engine.hazard_loader import _normalize_frequency_safe, load_storm_hazards_from_parquet_for_points  # noqa: E402
from case_study_sources import CASE_STUDY_BBOX, normalize_territory  # noqa: E402
from journal_guamar_run import encode_track_ids  # noqa: E402

COLUMNS = [
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

UTC = timezone.utc


def _pick_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return candidates[0]


COMPONENT_ORDER = ("wind", "rain", "surge")
DEFAULT_ADMIN_BOUNDARIES_PATH = Path(
    os.environ.get(
        "SIB_RISK_ADMIN_BOUNDARIES_PATH",
        str(
            _pick_existing_path(
                REPO_ROOT / "data" / "boundaries" / "geoBoundariesCGAZ_ADM0.geojson",
                Path("/home/ubuntu/uploads/DEM_Topo/Limites Pays/geoBoundariesCGAZ_ADM0.geojson"),
            )
        ),
    )
)
DEFAULT_ANTILLES_TOPO_PATH = Path(
    os.environ.get(
        "SIB_RISK_HAZARD_SURGE_TOPO_PATH",
        str(
            _pick_existing_path(
                REPO_ROOT / "data" / "hazards" / "MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc",
                Path("/home/ubuntu/uploads/DEM_Topo/MNT_FACADE_ANTS_HOMONIM_PBMA/DONNEES/MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc"),
            )
        ),
    )
)
TERRITORY_ADMIN_GROUP = {
    "guadeloupe": "FRA",
    "martinique": "FRA",
}


def _require_map_deps() -> None:
    missing: list[str] = []
    if fiona is None:
        missing.append("fiona")
    if np is None:
        missing.append("numpy")
    if pd is None:
        missing.append("pandas")
    if rasterio is None or shapes is None or from_bounds is None:
        missing.append("rasterio")
    if box is None or shape is None or unary_union is None:
        missing.append("shapely")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_guadeloupe_wind_maps.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install backend requirements and retry."
        )


def _progress(message: str) -> None:
    print(message, flush=True)


def _track_ids_from_tracks(tracks: Any) -> list[str]:
    data = list(getattr(tracks, "data", []) or [])
    ids: list[str] = []
    seen: set[str] = set()
    for track in data:
        attrs = getattr(track, "attrs", {}) or {}
        sid = str(attrs.get("sid") or attrs.get("name") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)
    return ids


def _track_journal_entry(hazard_obj: Any, tracks: Any) -> dict[str, Any]:
    freq = np.asarray(getattr(hazard_obj, "frequency", []), dtype=float).reshape(-1)
    track_ids = _track_ids_from_tracks(tracks)
    encoded = encode_track_ids(track_ids)
    return {
        "n_events": int(len(track_ids)),
        "event_frequency_sum": round(float(freq.sum()) if freq.size else 0.0, 8),
        "track_ids_compressed": encoded,
    }


def _require_climada_petals() -> tuple[Any, Any]:
    try:
        from climada_petals.hazard.tc_rainfield import TCRain  # type: ignore
        from climada_petals.hazard.tc_surge_bathtub import TCSurgeBathtub  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError(
            "climada_petals is required to build native rain/surge hazard maps. "
            "Install backend dependencies and retry."
        ) from exc
    return TCRain, TCSurgeBathtub


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
    return wind / 3.6


def _normalize_lon(lon: float) -> float:
    out = float(lon)
    while out > 180.0:
        out -= 360.0
    while out < -180.0:
        out += 360.0
    return out


def _coord_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(float(lat), 5), round(_normalize_lon(float(lon)), 5))


def _parse_file_block_index(path: Path) -> int:
    match = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not match:
        return 0
    return int(match.group(1))


def _iter_storm_files(root: Path, pattern: str) -> list[Path]:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {root}")
    return files


def _load_land_geometry_from_topo(
    *,
    topo_path: Path,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
):
    crop_bounds = (
        float(lon_min) - 0.15,
        float(lat_min) - 0.15,
        float(lon_max) + 0.15,
        float(lat_max) + 0.15,
    )
    with rasterio.open(topo_path) as src:
        window = from_bounds(*crop_bounds, src.transform)
        arr = src.read(1, window=window, masked=True)
        transform = src.window_transform(window)

    land_mask = np.where(arr.mask, 0, (arr.filled(-9999.0) >= 0.0).astype("uint8"))
    geoms = [
        shape(geom)
        for geom, value in shapes(land_mask, mask=(land_mask == 1), transform=transform)
        if int(value) == 1
    ]
    if not geoms:
        return None

    study_bbox = box(float(lon_min), float(lat_min), float(lon_max), float(lat_max))
    land_union = unary_union([geom for geom in geoms if geom.intersects(study_bbox)])
    if land_union.is_empty:
        return None
    return land_union


def _load_territory_geometry_from_admin(
    territory: str,
    *,
    admin_path: Path,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
):
    if not admin_path.exists():
        return None

    bbox_geom = box(float(lon_min), float(lat_min), float(lon_max), float(lat_max))
    target_group = TERRITORY_ADMIN_GROUP.get(territory)
    geometries = []

    with fiona.open(admin_path) as src:
        for feat in src:
            props = dict(feat.get("properties") or {})
            if target_group and str(props.get("shapeGroup") or "").upper() != str(target_group).upper():
                continue
            geom = shape(feat["geometry"])
            if geom.is_empty or not geom.intersects(bbox_geom):
                continue
            clipped = geom.intersection(bbox_geom)
            if not clipped.is_empty:
                geometries.append(clipped)

    if not geometries:
        return None

    territory_geom = unary_union(geometries).buffer(0)
    if territory_geom.is_empty:
        return None
    return territory_geom


def _build_grid_cells(
    *,
    territory_geom,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    cell_deg: float,
) -> dict[tuple[int, int], dict[str, float | int]]:
    full_grid_cells: dict[tuple[int, int], dict[str, float | int]] = {}
    target_cells: dict[tuple[int, int], dict[str, float | int]] = {}
    n_lat = int(math.ceil((lat_max - lat_min) / cell_deg))
    n_lon = int(math.ceil((lon_max - lon_min) / cell_deg))

    for i in range(n_lat):
        cell_lat_min = lat_min + (i * cell_deg)
        cell_lat_max = min(lat_max, cell_lat_min + cell_deg)
        for j in range(n_lon):
            cell_lon_min = lon_min + (j * cell_deg)
            cell_lon_max = min(lon_max, cell_lon_min + cell_deg)
            cell_geom = box(cell_lon_min, cell_lat_min, cell_lon_max, cell_lat_max)
            center_lat = float(cell_lat_min + 0.5 * (cell_lat_max - cell_lat_min))
            center_lon = float(cell_lon_min + 0.5 * (cell_lon_max - cell_lon_min))
            full_grid_cells[(i, j)] = {
                "i": int(i),
                "j": int(j),
                "grid_lat": round(center_lat, 6),
                "grid_lon": round(center_lon, 6),
            }

            if territory_geom is not None:
                land_part = cell_geom.intersection(territory_geom)
                if land_part.is_empty:
                    continue
                rep = land_part.representative_point()
                lat = float(rep.y)
                lon = float(rep.x)
            else:
                lat = center_lat
                lon = center_lon

            target_cells[(i, j)] = {
                "i": int(i),
                "j": int(j),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "grid_lat": round(center_lat, 6),
                "grid_lon": round(center_lon, 6),
            }

    return full_grid_cells, target_cells


def _build_regular_grid_cells(
    *,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    cell_deg: float,
) -> dict[tuple[int, int], dict[str, float | int]]:
    grid_cells: dict[tuple[int, int], dict[str, float | int]] = {}
    n_lat = int(math.ceil((lat_max - lat_min) / cell_deg))
    n_lon = int(math.ceil((lon_max - lon_min) / cell_deg))
    for i in range(n_lat):
        cell_lat_min = lat_min + (i * cell_deg)
        cell_lat_max = min(lat_max, cell_lat_min + cell_deg)
        center_lat = float(cell_lat_min + 0.5 * (cell_lat_max - cell_lat_min))
        for j in range(n_lon):
            cell_lon_min = lon_min + (j * cell_deg)
            cell_lon_max = min(lon_max, cell_lon_min + cell_deg)
            center_lon = float(cell_lon_min + 0.5 * (cell_lon_max - cell_lon_min))
            grid_cells[(i, j)] = {
                "i": int(i),
                "j": int(j),
                "grid_lat": round(center_lat, 6),
                "grid_lon": round(center_lon, 6),
            }
    return grid_cells


def _aggregate_wind_metrics(
    files: list[Path],
    *,
    basin_id: int,
    wind_unit_in: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    cell_deg: float,
    target_cells: dict[tuple[int, int], dict[str, float | int]],
) -> tuple[list[dict], int, int, dict[str, float]]:
    target_keys = set(target_cells.keys())
    sums: dict[tuple[int, int], float] = defaultdict(float)
    counts: dict[tuple[int, int], int] = defaultdict(int)
    year_cell_max: dict[tuple[int, int, int], float] = {}

    year_blocks: set[int] = set()
    track_keys: set[tuple[int, int]] = set()

    usecols = ["Year", "Basin ID", "Latitude", "Longitude", "Maximum wind speed", "TC number"]

    for txt in files:
        block_idx = _parse_file_block_index(txt)
        year_blocks.add(block_idx)

        for chunk in pd.read_csv(
            txt,
            names=COLUMNS,
            sep=",",
            usecols=usecols,
            chunksize=250_000,
            low_memory=False,
        ):
            chunk = chunk.rename(
                columns={
                    "Year": "year",
                    "Basin ID": "basin_id",
                    "Latitude": "lat",
                    "Longitude": "lon",
                    "Maximum wind speed": "wind_max",
                    "TC number": "tc_number",
                }
            )
            chunk["wind_max"] = _convert_wind_to_mps(chunk["wind_max"], wind_unit_in)
            chunk["lon"] = chunk["lon"].astype(float)
            chunk.loc[chunk["lon"] > 180.0, "lon"] = chunk.loc[chunk["lon"] > 180.0, "lon"] - 360.0

            chunk = chunk[(chunk["basin_id"] == basin_id)]
            if chunk.empty:
                continue

            chunk["year_global"] = chunk["year"].astype(int) + 1000 * block_idx
            chunk = chunk[
                (chunk["lat"] >= lat_min)
                & (chunk["lat"] <= lat_max)
                & (chunk["lon"] >= lon_min)
                & (chunk["lon"] <= lon_max)
            ]
            if chunk.empty:
                continue

            for row in chunk[["year_global", "tc_number"]].drop_duplicates().itertuples(index=False):
                track_keys.add((int(row.year_global), int(row.tc_number)))

            chunk["i"] = ((chunk["lat"] - lat_min) / cell_deg).astype(float).apply(math.floor).astype(int)
            chunk["j"] = ((chunk["lon"] - lon_min) / cell_deg).astype(float).apply(math.floor).astype(int)

            grouped = chunk.groupby(["i", "j"], as_index=False).agg(
                sum_wind=("wind_max", "sum"),
                n=("wind_max", "count"),
            )
            grouped_year = chunk.groupby(["i", "j", "year_global"], as_index=False)["wind_max"].max()

            for row in grouped.itertuples(index=False):
                key = (int(row.i), int(row.j))
                if key not in target_keys:
                    continue
                sums[key] += float(row.sum_wind)
                counts[key] += int(row.n)
            for row in grouped_year.itertuples(index=False):
                key = (int(row.i), int(row.j))
                if key not in target_keys:
                    continue
                year_key = (key[0], key[1], int(row.year_global))
                value = float(row.wind_max)
                prev = year_cell_max.get(year_key)
                if prev is None or value > prev:
                    year_cell_max[year_key] = value

    years_covered = (max(year_blocks) + 1) * 1000 if year_blocks else 0
    year_values_by_cell: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)
    for (i, j, year_global), value in year_cell_max.items():
        year_values_by_cell[(i, j)][int(year_global)] = float(value)

    cells: list[dict] = []
    means: list[float] = []
    rp50_values: list[float] = []
    rp100_values: list[float] = []
    event_max_values: list[float] = []

    for key in sorted(target_cells.keys()):
        cell_info = target_cells[key]
        n = int(counts.get(key, 0))
        total = float(sums.get(key, 0.0))
        mean_wind = (total / n) if n > 0 else 0.0

        yearly_vals = year_values_by_cell.get(key, {})
        if years_covered > 0:
            annual_series = np.zeros(years_covered, dtype=float)
            for year_idx, wind_val in yearly_vals.items():
                if 0 <= int(year_idx) < years_covered:
                    annual_series[int(year_idx)] = max(float(annual_series[int(year_idx)]), float(wind_val))
            rp50_wind = float(np.quantile(annual_series, 0.98)) if annual_series.size else 0.0
            rp100_wind = float(np.quantile(annual_series, 0.99)) if annual_series.size else 0.0
            event_max_wind = float(annual_series.max()) if annual_series.size else 0.0
        else:
            rp50_wind = 0.0
            rp100_wind = 0.0
            event_max_wind = 0.0

        cells.append(
            {
                "i": int(cell_info["i"]),
                "j": int(cell_info["j"]),
                "lat": float(cell_info["lat"]),
                "lon": float(cell_info["lon"]),
                "grid_lat": float(cell_info["grid_lat"]),
                "grid_lon": float(cell_info["grid_lon"]),
                "mean_wind_mps": round(mean_wind, 4),
                "rp50_wind_mps": round(rp50_wind, 4),
                "rp100_wind_mps": round(rp100_wind, 4),
                "event_max_wind_mps": round(event_max_wind, 4),
                "sample_count": int(n),
            }
        )
        means.append(mean_wind)
        rp50_values.append(rp50_wind)
        rp100_values.append(rp100_wind)
        event_max_values.append(event_max_wind)

    ranges = {
        "mean_wind_min_mps": min(means) if means else 0.0,
        "mean_wind_max_mps": max(means) if means else 0.0,
        "rp50_wind_min_mps": min(rp50_values) if rp50_values else 0.0,
        "rp50_wind_max_mps": max(rp50_values) if rp50_values else 0.0,
        "rp100_wind_min_mps": min(rp100_values) if rp100_values else 0.0,
        "rp100_wind_max_mps": max(rp100_values) if rp100_values else 0.0,
        "event_max_wind_min_mps": min(event_max_values) if event_max_values else 0.0,
        "event_max_wind_max_mps": max(event_max_values) if event_max_values else 0.0,
    }
    return cells, years_covered, len(track_keys), ranges


def _return_level(values: np.ndarray, weights: np.ndarray, return_period: int) -> float:
    if values.size == 0:
        return 0.0
    target_rate = 1.0 / float(return_period)
    order = np.argsort(-values)
    values_sorted = values[order]
    weights_sorted = weights[order]
    cumulative = np.cumsum(weights_sorted)
    idx = int(np.searchsorted(cumulative, target_rate, side="left"))
    if idx >= values_sorted.size:
        return 0.0
    return float(values_sorted[idx])


def _summarize_hazard_by_coord(hazard_obj) -> dict[tuple[float, float], dict[str, float]]:
    intensity_csc = hazard_obj.intensity.tocsc()
    frequency = np.asarray(getattr(hazard_obj, "frequency", []), dtype=float).reshape(-1)
    if frequency.size != intensity_csc.shape[0]:
        frequency = np.ones(intensity_csc.shape[0], dtype=float)

    cent_lats = np.asarray(hazard_obj.centroids.lat, dtype=float).reshape(-1)
    cent_lons = np.asarray(hazard_obj.centroids.lon, dtype=float).reshape(-1)
    out: dict[tuple[float, float], dict[str, float]] = {}

    for col in range(intensity_csc.shape[1]):
        start = int(intensity_csc.indptr[col])
        end = int(intensity_csc.indptr[col + 1])
        rows = intensity_csc.indices[start:end]
        values = intensity_csc.data[start:end]
        if values.size == 0:
            stats = {"mean": 0.0, "rp50": 0.0, "rp100": 0.0, "event_max": 0.0, "sample_count": 0}
        else:
            valid = np.isfinite(values) & (values > 0.0)
            values = values[valid]
            rows = rows[valid]
            if values.size == 0:
                stats = {"mean": 0.0, "rp50": 0.0, "rp100": 0.0, "event_max": 0.0, "sample_count": 0}
            else:
                weights = np.clip(frequency[rows], 0.0, None)
                if float(weights.sum()) > 0.0:
                    mean_val = float(np.average(values, weights=weights))
                else:
                    weights = np.ones(values.size, dtype=float)
                    mean_val = float(values.mean())
                stats = {
                    "mean": mean_val,
                    "rp50": _return_level(values, weights, 50),
                    "rp100": _return_level(values, weights, 100),
                    "event_max": float(np.max(values)),
                    "sample_count": int(values.size),
                }
        out[_coord_key(cent_lats[col], cent_lons[col])] = stats
    return out


def _validate_rain_metric_relationships(
    rain_stats: dict[tuple[float, float], dict[str, float]],
    *,
    hazard_key: str,
    tol: float = 1e-9,
) -> None:
    degenerate_cells: list[tuple[tuple[float, float], float]] = []
    for coord, stats in rain_stats.items():
        sample_count = int(stats.get("sample_count") or 0)
        rp50 = float(stats.get("rp50") or 0.0)
        rp100 = float(stats.get("rp100") or 0.0)
        event_max = float(stats.get("event_max") or 0.0)
        if sample_count < 3 or event_max <= 0.0:
            continue
        if abs(rp50 - rp100) <= tol and abs(rp100 - event_max) <= tol:
            degenerate_cells.append((coord, event_max))
            if len(degenerate_cells) >= 3:
                break
    if degenerate_cells:
        preview = ", ".join(
            f"({lat:.4f},{lon:.4f})={value:.4f}"
            for (lat, lon), value in degenerate_cells
        )
        raise ValueError(
            f"{hazard_key} rain return-period metrics collapsed to the event maximum on sampled cells: {preview}. "
            "This usually indicates that rain-event frequencies are not normalized or that the catalogue sampling is inconsistent with return-level extraction."
        )


def _rain_metric_payload(stats: dict[str, float]) -> dict[str, float]:
    mean_rain = round(float(stats.get("mean") or 0.0), 4)
    rp50_rain = round(float(stats.get("rp50") or 0.0), 4)
    rp100_rain = round(float(stats.get("rp100") or 0.0), 4)
    event_max_rain = round(float(stats.get("event_max") or 0.0), 4)
    return {
        "mean_rain_mm": mean_rain,
        "rp50_rain_mm": rp50_rain,
        "rp100_rain_mm": rp100_rain,
        "event_max_rain_mm": event_max_rain,
        # Legacy aliases kept until all consumers switch to the corrected unit suffix.
        "mean_rain_mmph": mean_rain,
        "rp50_rain_mmph": rp50_rain,
        "rp100_rain_mmph": rp100_rain,
        "event_max_rain_mmph": event_max_rain,
        "sample_count": int(stats.get("sample_count") or 0),
    }


def _build_native_wind_cells(
    *,
    target_cells: dict[tuple[int, int], dict[str, float | int]],
    wind_component_map: dict[tuple[float, float], dict[str, float]],
) -> tuple[list[dict], dict[str, float]]:
    cells: list[dict] = []
    mean_values: list[float] = []
    rp50_values: list[float] = []
    rp100_values: list[float] = []
    event_max_values: list[float] = []

    for key in sorted(target_cells.keys()):
        cell_info = target_cells[key]
        coord = _coord_key(float(cell_info["grid_lat"]), float(cell_info["grid_lon"]))
        wind_metrics = wind_component_map.get(
            coord,
            {
                "mean_wind_mps": 0.0,
                "rp50_wind_mps": 0.0,
                "rp100_wind_mps": 0.0,
                "event_max_wind_mps": 0.0,
                "sample_count": 0,
            },
        )
        cell = {
            "i": int(cell_info["i"]),
            "j": int(cell_info["j"]),
            "lat": float(cell_info["lat"]),
            "lon": float(cell_info["lon"]),
            "grid_lat": float(cell_info["grid_lat"]),
            "grid_lon": float(cell_info["grid_lon"]),
            "mean_wind_mps": round(float(wind_metrics.get("mean_wind_mps") or 0.0), 4),
            "rp50_wind_mps": round(float(wind_metrics.get("rp50_wind_mps") or 0.0), 4),
            "rp100_wind_mps": round(float(wind_metrics.get("rp100_wind_mps") or 0.0), 4),
            "event_max_wind_mps": round(float(wind_metrics.get("event_max_wind_mps") or 0.0), 4),
            "sample_count": int(wind_metrics.get("sample_count") or 0),
        }
        cells.append(cell)
        mean_values.append(float(cell["mean_wind_mps"]))
        rp50_values.append(float(cell["rp50_wind_mps"]))
        rp100_values.append(float(cell["rp100_wind_mps"]))
        event_max_values.append(float(cell["event_max_wind_mps"]))

    ranges = {
        "mean_wind_min_mps": min(mean_values) if mean_values else 0.0,
        "mean_wind_max_mps": max(mean_values) if mean_values else 0.0,
        "rp50_wind_min_mps": min(rp50_values) if rp50_values else 0.0,
        "rp50_wind_max_mps": max(rp50_values) if rp50_values else 0.0,
        "rp100_wind_min_mps": min(rp100_values) if rp100_values else 0.0,
        "rp100_wind_max_mps": max(rp100_values) if rp100_values else 0.0,
        "event_max_wind_min_mps": min(event_max_values) if event_max_values else 0.0,
        "event_max_wind_max_mps": max(event_max_values) if event_max_values else 0.0,
    }
    return cells, ranges


def _build_native_wind_and_rain_maps(
    *,
    point_coords: list[tuple[float, float]],
    dynamic_max_tracks: int,
    settings: Any,
    storm_parquet_path: Path,
    storm_cmcc_parquet_path: Path,
) -> tuple[
    dict[str, dict[tuple[float, float], dict[str, float]]],
    dict[str, dict[tuple[float, float], dict[str, float]]],
    dict[str, object],
]:
    if not point_coords:
        empty = {"storm": {}, "storm_cmcc": {}}
        return empty, empty, {
            "storm_tracks": 0,
            "storm_cmcc_tracks": 0,
            "rain_model": None,
            "dynamic_max_tracks": int(dynamic_max_tracks),
            "storm_years": 0,
            "track_journal": {
                "storm": {"n_events": 0, "event_frequency_sum": 0.0, "track_ids_compressed": encode_track_ids([])},
                "storm_cmcc": {"n_events": 0, "event_frequency_sum": 0.0, "track_ids_compressed": encode_track_ids([])},
            },
        }

    TCRain, _ = _require_climada_petals()
    _progress(
        "Building native CLIMADA wind/rain hazards "
        f"(points={len(point_coords)}, max_tracks={int(dynamic_max_tracks)})"
    )
    bundle = load_storm_hazards_from_parquet_for_points(
        storm_parquet_path=Path(storm_parquet_path),
        cmcc_parquet_path=Path(storm_cmcc_parquet_path),
        point_coords=point_coords,
        storm_years=int(settings.storm_years),
        wind_unit_in=str(settings.storm_wind_unit_in),
        radius_unit_in=str(settings.storm_radius_unit_in),
        env_pressure_hpa=float(settings.storm_env_pressure_hpa),
        max_tracks=int(dynamic_max_tracks),
        track_cache_max_entries=int(getattr(settings, "hazard_track_cache_max_entries", 8)),
    )

    rain_model = str(settings.hazard_rain_model or "R-CLIPER")
    _progress(
        "Native wind/rain inputs ready "
        f"(source={bundle.source}, basin_ids={list(bundle.basin_ids or [])}, "
        f"storm_tracks={len(getattr(bundle.tracks_storm, 'data', []) or [])}, "
        f"cmcc_tracks={len(getattr(bundle.tracks_storm_cmcc, 'data', []) or [])})"
    )

    wind_out: dict[str, dict[tuple[float, float], dict[str, float]]] = {}
    rain_out: dict[str, dict[tuple[float, float], dict[str, float]]] = {}
    for hazard_key, wind_hazard, tracks in (
        ("storm", bundle.storm, bundle.tracks_storm),
        ("storm_cmcc", bundle.storm_cmcc, bundle.tracks_storm_cmcc),
    ):
        _progress(f"{hazard_key}: summarizing native wind fields")
        wind_stats = _summarize_hazard_by_coord(wind_hazard)
        wind_out[hazard_key] = {
            key: {
                "mean_wind_mps": round(float(stats["mean"]), 4),
                "rp50_wind_mps": round(float(stats["rp50"]), 4),
                "rp100_wind_mps": round(float(stats["rp100"]), 4),
                "event_max_wind_mps": round(float(stats["event_max"]), 4),
                "sample_count": int(stats.get("sample_count") or 0),
            }
            for key, stats in wind_stats.items()
        }

        _progress(f"{hazard_key}: building TCRain.from_tracks")
        rain_hazard = TCRain.from_tracks(
            tracks,
            centroids=wind_hazard.centroids,
            model=rain_model,
            ignore_distance_to_coast=True,
            max_dist_inland_km=2000,
        )
        rain_hazard = _normalize_frequency_safe(rain_hazard, int(settings.storm_years))
        _progress(f"{hazard_key}: summarizing rain fields")
        rain_stats = _summarize_hazard_by_coord(rain_hazard)
        _validate_rain_metric_relationships(rain_stats, hazard_key=hazard_key)
        rain_out[hazard_key] = {
            key: _rain_metric_payload(stats)
            for key, stats in rain_stats.items()
        }

    meta = {
        "storm_tracks": int(len(getattr(bundle.tracks_storm, "data", []) or [])),
        "storm_cmcc_tracks": int(len(getattr(bundle.tracks_storm_cmcc, "data", []) or [])),
        "rain_model": rain_model,
        "dynamic_max_tracks": int(dynamic_max_tracks),
        "storm_years": int(settings.storm_years),
        "storm_parquet_path": str(storm_parquet_path),
        "storm_cmcc_parquet_path": str(storm_cmcc_parquet_path),
        "hazard_source": str(bundle.source),
        "hazard_basin_ids": [int(v) for v in list(bundle.basin_ids or [])],
        "track_journal": {
            "storm": _track_journal_entry(bundle.storm, bundle.tracks_storm),
            "storm_cmcc": _track_journal_entry(bundle.storm_cmcc, bundle.tracks_storm_cmcc),
        },
    }
    return wind_out, rain_out, meta


def _build_native_rain_maps(
    *,
    point_coords: list[tuple[float, float]],
    dynamic_max_tracks: int,
    settings: Any,
    storm_parquet_path: Path,
    storm_cmcc_parquet_path: Path,
) -> tuple[dict[str, dict[tuple[float, float], dict[str, float]]], dict[str, object]]:
    if not point_coords:
        return {"storm": {}, "storm_cmcc": {}}, {
            "storm_tracks": 0,
            "storm_cmcc_tracks": 0,
            "rain_model": None,
            "dynamic_max_tracks": int(dynamic_max_tracks),
        }

    TCRain, _ = _require_climada_petals()
    _progress(
        "Building native CLIMADA hazards "
        f"(points={len(point_coords)}, max_tracks={int(dynamic_max_tracks)})"
    )
    bundle = load_storm_hazards_from_parquet_for_points(
        storm_parquet_path=Path(storm_parquet_path),
        cmcc_parquet_path=Path(storm_cmcc_parquet_path),
        point_coords=point_coords,
        storm_years=int(settings.storm_years),
        wind_unit_in=str(settings.storm_wind_unit_in),
        radius_unit_in=str(settings.storm_radius_unit_in),
        env_pressure_hpa=float(settings.storm_env_pressure_hpa),
        max_tracks=int(dynamic_max_tracks),
        track_cache_max_entries=int(getattr(settings, "hazard_track_cache_max_entries", 8)),
    )

    rain_model = str(settings.hazard_rain_model or "R-CLIPER")
    _progress(
        "Native hazard inputs ready "
        f"(source={bundle.source}, basin_ids={list(bundle.basin_ids or [])}, "
        f"storm_tracks={len(getattr(bundle.tracks_storm, 'data', []) or [])}, "
        f"cmcc_tracks={len(getattr(bundle.tracks_storm_cmcc, 'data', []) or [])})"
    )

    out: dict[str, dict[tuple[float, float], dict[str, float]]] = {}
    for hazard_key, wind_hazard, tracks in (
        ("storm", bundle.storm, bundle.tracks_storm),
        ("storm_cmcc", bundle.storm_cmcc, bundle.tracks_storm_cmcc),
    ):
        _progress(f"{hazard_key}: building TCRain.from_tracks")
        rain_hazard = TCRain.from_tracks(
            tracks,
            centroids=wind_hazard.centroids,
            model=rain_model,
            ignore_distance_to_coast=True,
            max_dist_inland_km=2000,
        )
        rain_hazard = _normalize_frequency_safe(rain_hazard, int(settings.storm_years))
        _progress(f"{hazard_key}: summarizing rain fields")
        rain_stats = _summarize_hazard_by_coord(rain_hazard)
        _validate_rain_metric_relationships(rain_stats, hazard_key=hazard_key)
        out[hazard_key] = {
            key: _rain_metric_payload(stats)
            for key, stats in rain_stats.items()
        }

    meta = {
        "storm_tracks": int(len(getattr(bundle.tracks_storm, "data", []) or [])),
        "storm_cmcc_tracks": int(len(getattr(bundle.tracks_storm_cmcc, "data", []) or [])),
        "rain_model": rain_model,
        "dynamic_max_tracks": int(dynamic_max_tracks),
        "storm_parquet_path": str(storm_parquet_path),
        "storm_cmcc_parquet_path": str(storm_cmcc_parquet_path),
        "hazard_source": str(bundle.source),
        "hazard_basin_ids": [int(v) for v in list(bundle.basin_ids or [])],
    }
    return out, meta


def _aggregate_subgrid_stats_to_target_cells(
    *,
    subgrid_stats: dict[tuple[float, float], dict[str, float]],
    target_cells: dict[tuple[int, int], dict[str, float | int]],
    lat_min: float,
    lon_min: float,
    output_cell_deg: float,
) -> dict[tuple[float, float], dict[str, float]]:
    grouped: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(
        lambda: {"mean": [], "rp50": [], "rp100": [], "event_max": []}
    )
    for (lat, lon), stats in subgrid_stats.items():
        i = int(math.floor((float(lat) - lat_min) / output_cell_deg))
        j = int(math.floor((float(lon) - lon_min) / output_cell_deg))
        key = (i, j)
        if key not in target_cells:
            continue
        grouped[key]["mean"].append(float(stats["mean"]))
        grouped[key]["rp50"].append(float(stats["rp50"]))
        grouped[key]["rp100"].append(float(stats["rp100"]))
        grouped[key]["event_max"].append(float(stats["event_max"]))

    out: dict[tuple[float, float], dict[str, float]] = {}
    for key, cell_info in target_cells.items():
        values = grouped.get(key, {"mean": [], "rp50": [], "rp100": [], "event_max": []})
        coord = _coord_key(cell_info["grid_lat"], cell_info["grid_lon"])
        out[coord] = {
            "mean_surge_m": round(max(values["mean"]) if values["mean"] else 0.0, 4),
            "rp50_surge_m": round(max(values["rp50"]) if values["rp50"] else 0.0, 4),
            "rp100_surge_m": round(max(values["rp100"]) if values["rp100"] else 0.0, 4),
            "event_max_surge_m": round(max(values["event_max"]) if values["event_max"] else 0.0, 4),
        }
    return out


def _build_native_surge_maps(
    *,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    output_cell_deg: float,
    surge_native_cell_deg: float,
    target_cells: dict[tuple[int, int], dict[str, float | int]],
    topo_path: Path,
    dynamic_max_tracks: int,
    settings: Any,
    storm_parquet_path: Path,
    storm_cmcc_parquet_path: Path,
) -> tuple[dict[str, dict[tuple[float, float], dict[str, float]]], dict[str, object]]:
    fine_grid_cells = _build_regular_grid_cells(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        cell_deg=surge_native_cell_deg,
    )
    point_coords = [
        (float(cell_info["grid_lat"]), float(cell_info["grid_lon"]))
        for _, cell_info in sorted(fine_grid_cells.items())
    ]
    _, TCSurgeBathtub = _require_climada_petals()
    _progress(
        "Building native CLIMADA surge hazards "
        f"(points={len(point_coords)}, max_tracks={int(dynamic_max_tracks)}, "
        f"native_cell_deg={surge_native_cell_deg})"
    )
    bundle = load_storm_hazards_from_parquet_for_points(
        storm_parquet_path=Path(storm_parquet_path),
        cmcc_parquet_path=Path(storm_cmcc_parquet_path),
        point_coords=point_coords,
        storm_years=int(settings.storm_years),
        wind_unit_in=str(settings.storm_wind_unit_in),
        radius_unit_in=str(settings.storm_radius_unit_in),
        env_pressure_hpa=float(settings.storm_env_pressure_hpa),
        max_tracks=int(dynamic_max_tracks),
        track_cache_max_entries=int(getattr(settings, "hazard_track_cache_max_entries", 8)),
    )
    prepared_topo = _prepare_topo_raster_with_crs(Path(topo_path))
    _progress(
        "Native surge inputs ready "
        f"(source={bundle.source}, basin_ids={list(bundle.basin_ids or [])}, "
        f"storm_tracks={len(getattr(bundle.tracks_storm, 'data', []) or [])}, "
        f"cmcc_tracks={len(getattr(bundle.tracks_storm_cmcc, 'data', []) or [])})"
    )

    out: dict[str, dict[tuple[float, float], dict[str, float]]] = {}
    for hazard_key, wind_hazard in (
        ("storm", bundle.storm),
        ("storm_cmcc", bundle.storm_cmcc),
    ):
        _progress(f"{hazard_key}: building TCSurgeBathtub.from_tc_winds on fine grid")
        surge_hazard = TCSurgeBathtub.from_tc_winds(wind_hazard, str(prepared_topo))
        _progress(f"{hazard_key}: summarizing fine-grid surge fields")
        surge_stats = _summarize_hazard_by_coord(surge_hazard)
        out[hazard_key] = _aggregate_subgrid_stats_to_target_cells(
            subgrid_stats=surge_stats,
            target_cells=target_cells,
            lat_min=lat_min,
            lon_min=lon_min,
            output_cell_deg=output_cell_deg,
        )

    meta = {
        "storm_tracks": int(len(getattr(bundle.tracks_storm, "data", []) or [])),
        "storm_cmcc_tracks": int(len(getattr(bundle.tracks_storm_cmcc, "data", []) or [])),
        "topo_path_prepared": str(prepared_topo),
        "dynamic_max_tracks": int(dynamic_max_tracks),
        "native_cell_deg": float(surge_native_cell_deg),
        "storm_parquet_path": str(storm_parquet_path),
        "storm_cmcc_parquet_path": str(storm_cmcc_parquet_path),
        "hazard_source": str(bundle.source),
        "hazard_basin_ids": [int(v) for v in list(bundle.basin_ids or [])],
    }
    return out, meta


def _merge_component_metrics(
    wind_cells: list[dict],
    rain_component_map: dict[tuple[float, float], dict[str, float]],
    surge_component_map: dict[tuple[float, float], dict[str, float]],
) -> tuple[list[dict], dict[str, float]]:
    cells: list[dict] = []
    mean_rain_values: list[float] = []
    rp50_rain_values: list[float] = []
    rp100_rain_values: list[float] = []
    event_max_rain_values: list[float] = []
    mean_surge_values: list[float] = []
    rp50_surge_values: list[float] = []
    rp100_surge_values: list[float] = []
    event_max_surge_values: list[float] = []

    for cell in wind_cells:
        key = _coord_key(cell["grid_lat"], cell["grid_lon"])
        merged = dict(cell)
        merged.update(
            rain_component_map.get(
                key,
                {
                    "mean_rain_mm": 0.0,
                    "rp50_rain_mm": 0.0,
                    "rp100_rain_mm": 0.0,
                    "event_max_rain_mm": 0.0,
                    "mean_rain_mmph": 0.0,
                    "rp50_rain_mmph": 0.0,
                    "rp100_rain_mmph": 0.0,
                    "event_max_rain_mmph": 0.0,
                },
            )
        )
        merged.update(
            surge_component_map.get(
                key,
                {
                    "mean_surge_m": 0.0,
                    "rp50_surge_m": 0.0,
                    "rp100_surge_m": 0.0,
                    "event_max_surge_m": 0.0,
                },
            )
        )
        merged.pop("grid_lat", None)
        merged.pop("grid_lon", None)
        cells.append(merged)
        mean_rain_values.append(float(merged["mean_rain_mm"]))
        rp50_rain_values.append(float(merged["rp50_rain_mm"]))
        rp100_rain_values.append(float(merged["rp100_rain_mm"]))
        event_max_rain_values.append(float(merged["event_max_rain_mm"]))
        mean_surge_values.append(float(merged["mean_surge_m"]))
        rp50_surge_values.append(float(merged["rp50_surge_m"]))
        rp100_surge_values.append(float(merged["rp100_surge_m"]))
        event_max_surge_values.append(float(merged["event_max_surge_m"]))

    ranges = {
        "mean_rain_min_mm": min(mean_rain_values) if mean_rain_values else 0.0,
        "mean_rain_max_mm": max(mean_rain_values) if mean_rain_values else 0.0,
        "rp50_rain_min_mm": min(rp50_rain_values) if rp50_rain_values else 0.0,
        "rp50_rain_max_mm": max(rp50_rain_values) if rp50_rain_values else 0.0,
        "rp100_rain_min_mm": min(rp100_rain_values) if rp100_rain_values else 0.0,
        "rp100_rain_max_mm": max(rp100_rain_values) if rp100_rain_values else 0.0,
        "event_max_rain_min_mm": min(event_max_rain_values) if event_max_rain_values else 0.0,
        "event_max_rain_max_mm": max(event_max_rain_values) if event_max_rain_values else 0.0,
        "mean_surge_min_m": min(mean_surge_values) if mean_surge_values else 0.0,
        "mean_surge_max_m": max(mean_surge_values) if mean_surge_values else 0.0,
        "rp50_surge_min_m": min(rp50_surge_values) if rp50_surge_values else 0.0,
        "rp50_surge_max_m": max(rp50_surge_values) if rp50_surge_values else 0.0,
        "rp100_surge_min_m": min(rp100_surge_values) if rp100_surge_values else 0.0,
        "rp100_surge_max_m": max(rp100_surge_values) if rp100_surge_values else 0.0,
        "event_max_surge_min_m": min(event_max_surge_values) if event_max_surge_values else 0.0,
        "event_max_surge_max_m": max(event_max_surge_values) if event_max_surge_values else 0.0,
    }
    ranges.update(
        {
            "mean_rain_min_mmph": ranges["mean_rain_min_mm"],
            "mean_rain_max_mmph": ranges["mean_rain_max_mm"],
            "rp50_rain_min_mmph": ranges["rp50_rain_min_mm"],
            "rp50_rain_max_mmph": ranges["rp50_rain_max_mm"],
            "rp100_rain_min_mmph": ranges["rp100_rain_min_mm"],
            "rp100_rain_max_mmph": ranges["rp100_rain_max_mm"],
            "event_max_rain_min_mmph": ranges["event_max_rain_min_mm"],
            "event_max_rain_max_mmph": ranges["event_max_rain_max_mm"],
        }
    )
    return cells, ranges


def main() -> None:
    parser = argparse.ArgumentParser(description="Build territory hazard map layers from STORM using native CLIMADA rain/surge generation.")
    parser.add_argument("--territory", choices=["guadeloupe", "martinique"], default="guadeloupe")
    parser.add_argument(
        "--storm-dir",
        default=None,
        help="Path to STORM dynamic source directory/file (defaults to backend settings).",
    )
    parser.add_argument(
        "--cmcc-dir",
        default=None,
        help="Path to STORM_CMCC dynamic source directory/file (defaults to backend settings).",
    )
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--cell-deg", type=float, default=0.02, help="Grid cell size in degrees")
    parser.add_argument("--lat-min", type=float, default=None)
    parser.add_argument("--lat-max", type=float, default=None)
    parser.add_argument("--lon-min", type=float, default=None)
    parser.add_argument("--lon-max", type=float, default=None)
    parser.add_argument("--basin-id", type=int, default=1, help="NA basin id in STORM files")
    parser.add_argument(
        "--topo-path",
        default=str(DEFAULT_ANTILLES_TOPO_PATH),
        help="Topography/bathymetry raster used by TCSurgeBathtub.",
    )
    parser.add_argument(
        "--admin-boundaries-path",
        default=str(DEFAULT_ADMIN_BOUNDARIES_PATH),
        help="Administrative coastline mask used to clip cells to the exposed territory.",
    )
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=None,
        help="Maximum number of STORM tracks to keep when building native CLIMADA rain/surge hazards (0 disables the cap).",
    )
    parser.add_argument(
        "--surge-native-cell-deg",
        type=float,
        default=0.01,
        help="Regular grid spacing in degrees used internally for the native TCSurgeBathtub computation before clipping back to the output cells.",
    )
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in STORM txt files. Supported: m/s, kn, km/h. Output is always m/s.",
    )
    parser.add_argument(
        "--case-study-run-id",
        default=None,
        help="Optional coherence token propagated across case-study artefacts (maps/proxy/page analysis).",
    )
    args = parser.parse_args()
    _require_map_deps()

    settings = load_settings()
    territory = normalize_territory(args.territory)
    case_study_run_id = str(args.case_study_run_id or "").strip()
    if not case_study_run_id:
        case_study_run_id = datetime.now(UTC).strftime(f"{territory}_case_%Y%m%dT%H%M%SZ")
    default_bbox = CASE_STUDY_BBOX[territory]
    lat_min = float(args.lat_min if args.lat_min is not None else default_bbox["lat_min"])
    lat_max = float(args.lat_max if args.lat_max is not None else default_bbox["lat_max"])
    lon_min = float(args.lon_min if args.lon_min is not None else default_bbox["lon_min"])
    lon_max = float(args.lon_max if args.lon_max is not None else default_bbox["lon_max"])
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)
    dynamic_max_tracks = int(args.dynamic_max_tracks if args.dynamic_max_tracks is not None else 300)

    storm_parquet_path = Path(args.storm_dir) if args.storm_dir else Path(settings.storm_parquet_path)
    cmcc_parquet_path = Path(args.cmcc_dir) if args.cmcc_dir else Path(settings.storm_cmcc_parquet_path)
    topo_path = Path(args.topo_path)
    admin_path = Path(args.admin_boundaries_path)
    out = Path(args.out) if args.out else (REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json")

    territory_geom = _load_territory_geometry_from_admin(
        territory,
        admin_path=admin_path,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
    )
    mask_source = "ADM0 administrative boundaries"
    if territory_geom is None and topo_path.exists():
        territory_geom = _load_land_geometry_from_topo(
            topo_path=topo_path,
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
        )
        mask_source = "DEM-derived land mask fallback"

    full_grid_cells, target_cells = _build_grid_cells(
        territory_geom=territory_geom,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        cell_deg=args.cell_deg,
    )
    _progress(
        f"{territory}: prepared {len(target_cells)} clipped cells on a {len(full_grid_cells)}-point regular grid "
        f"(mask_source={mask_source}, dynamic_max_tracks={dynamic_max_tracks})"
    )
    ordered_point_coords = [
        (float(cell_info["grid_lat"]), float(cell_info["grid_lon"]))
        for _, cell_info in sorted(full_grid_cells.items())
    ]

    native_wind_components, native_rain_components, native_hazard_meta = _build_native_wind_and_rain_maps(
        point_coords=ordered_point_coords,
        dynamic_max_tracks=dynamic_max_tracks,
        settings=settings,
        storm_parquet_path=storm_parquet_path,
        storm_cmcc_parquet_path=cmcc_parquet_path,
    )
    storm_wind_cells, storm_wind_ranges = _build_native_wind_cells(
        target_cells=target_cells,
        wind_component_map=native_wind_components.get("storm", {}),
    )
    cmcc_wind_cells, cmcc_wind_ranges = _build_native_wind_cells(
        target_cells=target_cells,
        wind_component_map=native_wind_components.get("storm_cmcc", {}),
    )
    native_surge_components, native_surge_meta = _build_native_surge_maps(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        output_cell_deg=args.cell_deg,
        surge_native_cell_deg=float(args.surge_native_cell_deg),
        target_cells=target_cells,
        topo_path=topo_path,
        dynamic_max_tracks=dynamic_max_tracks,
        settings=settings,
        storm_parquet_path=storm_parquet_path,
        storm_cmcc_parquet_path=cmcc_parquet_path,
    )

    storm_cells, storm_component_ranges = _merge_component_metrics(
        storm_wind_cells,
        native_rain_components.get("storm", {}),
        native_surge_components.get("storm", {}),
    )
    cmcc_cells, cmcc_component_ranges = _merge_component_metrics(
        cmcc_wind_cells,
        native_rain_components.get("storm_cmcc", {}),
        native_surge_components.get("storm_cmcc", {}),
    )

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "case_study_run_id": case_study_run_id,
            "bbox": {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min,
                "lon_max": lon_max,
            },
            "grid_cell_deg": args.cell_deg,
            "basin_id": args.basin_id,
            "territory": territory,
            "dataset_links": {
                "storm_present": "https://data.4tu.nl/articles/dataset/STORM_IBTrACS_present_climate_synthetic_tropical_cyclone_tracks/12706085",
                "storm_cmcc": "https://data.4tu.nl/datasets/98900e17-8e01-4d70-b3b6-ca1a1da2f194/2",
            },
            "wind_unit_in": normalized_wind_unit,
            "wind_unit_out": "m/s",
            "hazard_components": list(COMPONENT_ORDER),
            "component_units": {
                "wind": "m/s",
                "rain": "mm",
                "surge": "m",
            },
            "surge_topo_path": str(topo_path) if topo_path.exists() else None,
            "surge_topo_path_prepared": native_surge_meta.get("topo_path_prepared"),
            "wind_generation": "Native CLIMADA chain: STORM -> tracks -> TropCyclone.from_tracks",
            "surge_generation": "Native CLIMADA chain: STORM -> TropCyclone -> TCSurgeBathtub.from_tc_winds",
            "rain_generation": "Native CLIMADA chain: STORM -> tracks -> TCRain.from_tracks (event-total intensity in mm)",
            "rain_intensity_semantics": "event_total_mm",
            "territory_mask_path": str(admin_path) if admin_path.exists() else None,
            "territory_mask_source": mask_source,
            "territory_mask_shape_group": TERRITORY_ADMIN_GROUP.get(territory),
            "cell_clip_rule": "Only cells intersecting the territory mask are retained; each display point is the representative point of the land portion of the cell.",
            "native_dynamic_max_tracks": int(native_hazard_meta.get("dynamic_max_tracks") or dynamic_max_tracks),
            "native_rain_model": native_hazard_meta.get("rain_model"),
            "native_hazard_source": native_hazard_meta.get("hazard_source"),
            "native_hazard_basin_ids": native_hazard_meta.get("hazard_basin_ids") or [],
            "track_journal": native_hazard_meta.get("track_journal") or {},
            "surge_native_cell_deg": float(args.surge_native_cell_deg),
        },
        "storm": {
            "years_covered": int(native_hazard_meta.get("storm_years") or 0),
            "tracks_approx": int(native_hazard_meta.get("storm_tracks") or 0),
            "native_tracks_used": int(native_hazard_meta.get("storm_tracks") or 0),
            "native_surge_tracks_used": int(native_surge_meta.get("storm_tracks") or 0),
            "cell_count": len(storm_cells),
            **{k: round(float(v), 4) for k, v in {**storm_wind_ranges, **storm_component_ranges}.items()},
            "cells": storm_cells,
        },
        "storm_cmcc": {
            "years_covered": int(native_hazard_meta.get("storm_years") or 0),
            "tracks_approx": int(native_hazard_meta.get("storm_cmcc_tracks") or 0),
            "native_tracks_used": int(native_hazard_meta.get("storm_cmcc_tracks") or 0),
            "native_surge_tracks_used": int(native_surge_meta.get("storm_cmcc_tracks") or 0),
            "cell_count": len(cmcc_cells),
            **{k: round(float(v), 4) for k, v in {**cmcc_wind_ranges, **cmcc_component_ranges}.items()},
            "cells": cmcc_cells,
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _progress(f"Wrote {out}")
    _progress(f"territory={territory} bbox=[{lat_min},{lat_max}]x[{lon_min},{lon_max}] cells={len(target_cells)}")
    _progress(
        "STORM "
        f"cells={len(storm_cells)} years={payload['storm']['years_covered']} tracks~={payload['storm']['tracks_approx']} native_tracks={payload['storm']['native_tracks_used']} "
        f"mean_wind=[{payload['storm']['mean_wind_min_mps']:.3f},{payload['storm']['mean_wind_max_mps']:.3f}] "
        f"mean_rain=[{payload['storm']['mean_rain_min_mm']:.3f},{payload['storm']['mean_rain_max_mm']:.3f}] "
        f"mean_surge=[{payload['storm']['mean_surge_min_m']:.3f},{payload['storm']['mean_surge_max_m']:.3f}]"
    )
    _progress(
        "STORM_CMCC "
        f"cells={len(cmcc_cells)} years={payload['storm_cmcc']['years_covered']} tracks~={payload['storm_cmcc']['tracks_approx']} native_tracks={payload['storm_cmcc']['native_tracks_used']} "
        f"mean_wind=[{payload['storm_cmcc']['mean_wind_min_mps']:.3f},{payload['storm_cmcc']['mean_wind_max_mps']:.3f}] "
        f"mean_rain=[{payload['storm_cmcc']['mean_rain_min_mm']:.3f},{payload['storm_cmcc']['mean_rain_max_mm']:.3f}] "
        f"mean_surge=[{payload['storm_cmcc']['mean_surge_min_m']:.3f},{payload['storm_cmcc']['mean_surge_max_m']:.3f}]"
    )

    # Some geospatial C extensions occasionally segfault during interpreter shutdown
    # even after the output file has been written successfully.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
