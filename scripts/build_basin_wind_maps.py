#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]

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

USECOLS = ["Year", "Basin ID", "Latitude", "Longitude", "Maximum wind speed", "TC number"]

BASIN_DEFAULT_ID: dict[str, int] = {
    "na": 1,
    "si": 3,
}

BASIN_LABEL: dict[str, str] = {
    "na": "Nord Atlantique",
    "si": "Sud Indien",
}


def _require_runtime_deps() -> None:
    missing: list[str] = []
    if np is None:
        missing.append("numpy")
    if pd is None:
        missing.append("pandas")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_basin_wind_maps.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install backend requirements and retry."
        )


def _parse_block_index(path: Path) -> int:
    match = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not match:
        raise ValueError(f"Could not parse block index from file name: {path.name}")
    return int(match.group(1))


def _normalize_wind_unit(raw: str) -> str:
    unit = str(raw or "m/s").strip().lower()
    aliases = {
        "m/s": "m/s",
        "ms": "m/s",
        "mps": "m/s",
        "meter_per_second": "m/s",
        "meters_per_second": "m/s",
        "kn": "kn",
        "kt": "kn",
        "kts": "kn",
        "knot": "kn",
        "knots": "kn",
        "km/h": "km/h",
        "kmh": "km/h",
        "kph": "km/h",
    }
    if unit not in aliases:
        raise ValueError(f"Unsupported wind unit '{raw}'. Supported: m/s, kn, km/h")
    return aliases[unit]


def _wind_to_mps(series: pd.Series, unit_in: str) -> pd.Series:
    unit = _normalize_wind_unit(unit_in)
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    if unit == "m/s":
        return numeric
    if unit == "kn":
        return numeric * 0.514444
    return numeric / 3.6  # km/h -> m/s


def _iter_input_files(root: Path, pattern: str) -> list[Path]:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching pattern '{pattern}' under '{root}'")
    return files


def _cell_center(index_i: int, index_j: int, cell_deg: float) -> tuple[float, float]:
    lat = (float(index_i) + 0.5) * float(cell_deg)
    lon = (float(index_j) + 0.5) * float(cell_deg)
    return round(lat, 6), round(lon, 6)


def _metric_ranges(cells: list[dict], key: str) -> tuple[float, float]:
    vals = [float(cell.get(key, 0.0)) for cell in cells]
    if not vals:
        return 0.0, 0.0
    return float(min(vals)), float(max(vals))


def _aggregate_dataset(
    files: list[Path],
    *,
    basin_id: int,
    wind_unit_in: str,
    cell_deg: float,
) -> dict:
    sums: dict[tuple[int, int], float] = defaultdict(float)
    counts: dict[tuple[int, int], int] = defaultdict(int)
    year_max_by_cell: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)

    block_indices: set[int] = set()
    track_keys: set[tuple[int, int]] = set()

    for txt_path in files:
        block_idx = _parse_block_index(txt_path)
        block_indices.add(block_idx)

        for chunk in pd.read_csv(
            txt_path,
            names=COLUMNS,
            sep=",",
            usecols=USECOLS,
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

            chunk["year"] = pd.to_numeric(chunk["year"], errors="coerce")
            chunk["basin_id"] = pd.to_numeric(chunk["basin_id"], errors="coerce")
            chunk["lat"] = pd.to_numeric(chunk["lat"], errors="coerce")
            chunk["lon"] = pd.to_numeric(chunk["lon"], errors="coerce")
            chunk["tc_number"] = pd.to_numeric(chunk["tc_number"], errors="coerce")
            chunk["wind_max"] = _wind_to_mps(chunk["wind_max"], wind_unit_in)
            chunk["lon"] = chunk["lon"].astype(float)
            chunk.loc[chunk["lon"] > 180.0, "lon"] = chunk.loc[chunk["lon"] > 180.0, "lon"] - 360.0

            chunk = chunk[
                (chunk["basin_id"] == float(basin_id))
                & np.isfinite(chunk["year"])
                & np.isfinite(chunk["lat"])
                & np.isfinite(chunk["lon"])
                & np.isfinite(chunk["wind_max"])
                & np.isfinite(chunk["tc_number"])
            ]
            if chunk.empty:
                continue

            chunk["year_global"] = chunk["year"].astype(int) + (1000 * int(block_idx))
            chunk["i"] = np.floor(chunk["lat"] / float(cell_deg)).astype(int)
            chunk["j"] = np.floor(chunk["lon"] / float(cell_deg)).astype(int)

            grouped_mean = chunk.groupby(["i", "j"], as_index=False).agg(
                sum_wind=("wind_max", "sum"),
                n=("wind_max", "count"),
            )
            for row in grouped_mean.itertuples(index=False):
                key = (int(row.i), int(row.j))
                sums[key] += float(row.sum_wind)
                counts[key] += int(row.n)

            grouped_year = chunk.groupby(["i", "j", "year_global"], as_index=False).agg(
                max_wind=("wind_max", "max")
            )
            for row in grouped_year.itertuples(index=False):
                key = (int(row.i), int(row.j))
                year_global = int(row.year_global)
                val = float(row.max_wind)
                prev = year_max_by_cell[key].get(year_global)
                if prev is None or val > prev:
                    year_max_by_cell[key][year_global] = val

            for row in chunk[["year_global", "tc_number"]].drop_duplicates().itertuples(index=False):
                track_keys.add((int(row.year_global), int(row.tc_number)))

    years_covered = (max(block_indices) + 1) * 1000 if block_indices else 0

    cells: list[dict] = []
    for key in sorted(counts.keys()):
        sample_count = int(counts.get(key, 0))
        if sample_count <= 0:
            continue

        mean_wind = float(sums.get(key, 0.0)) / float(sample_count)
        annual_values = [float(v) for v in list(year_max_by_cell.get(key, {}).values()) if np.isfinite(v) and v > 0.0]
        if annual_values:
            annual_arr = np.asarray(annual_values, dtype=float)
            rp50 = float(np.quantile(annual_arr, 0.98))
            rp100 = float(np.quantile(annual_arr, 0.99))
            event_max = float(np.max(annual_arr))
        else:
            rp50 = 0.0
            rp100 = 0.0
            event_max = 0.0

        lat_center, lon_center = _cell_center(key[0], key[1], cell_deg)
        cells.append(
            {
                "lat": float(lat_center),
                "lon": float(lon_center),
                "mean_wind_mps": round(float(mean_wind), 4),
                "rp50_wind_mps": round(float(rp50), 4),
                "rp100_wind_mps": round(float(rp100), 4),
                "event_max_wind_mps": round(float(event_max), 4),
                "sample_count": int(sample_count),
            }
        )

    mean_min, mean_max = _metric_ranges(cells, "mean_wind_mps")
    rp50_min, rp50_max = _metric_ranges(cells, "rp50_wind_mps")
    rp100_min, rp100_max = _metric_ranges(cells, "rp100_wind_mps")
    event_min, event_max = _metric_ranges(cells, "event_max_wind_mps")

    return {
        "years_covered": int(years_covered),
        "tracks_approx": int(len(track_keys)),
        "cell_count": int(len(cells)),
        "mean_wind_min_mps": round(float(mean_min), 4),
        "mean_wind_max_mps": round(float(mean_max), 4),
        "rp50_wind_min_mps": round(float(rp50_min), 4),
        "rp50_wind_max_mps": round(float(rp50_max), 4),
        "rp100_wind_min_mps": round(float(rp100_min), 4),
        "rp100_wind_max_mps": round(float(rp100_max), 4),
        "event_max_wind_min_mps": round(float(event_min), 4),
        "event_max_wind_max_mps": round(float(event_max), 4),
        "cells": cells,
    }


def _bbox_from_payload(storm_cells: list[dict], cmcc_cells: list[dict], cell_deg: float) -> dict[str, float]:
    all_cells = list(storm_cells) + list(cmcc_cells)
    if not all_cells:
        return {"south": 0.0, "north": 0.0, "west": 0.0, "east": 0.0}
    lats = [float(cell.get("lat", 0.0)) for cell in all_cells]
    lons = [float(cell.get("lon", 0.0)) for cell in all_cells]
    return {
        "south": round(float(min(lats) - (cell_deg / 2.0)), 6),
        "north": round(float(max(lats) + (cell_deg / 2.0)), 6),
        "west": round(float(min(lons) - (cell_deg / 2.0)), 6),
        "east": round(float(max(lons) + (cell_deg / 2.0)), 6),
    }


def _default_output_path(basin_code: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return (
        REPO_ROOT
        / "outputs"
        / f"{basin_code}_wind_maps_{stamp}"
        / "Hazard_maps"
        / f"{basin_code}-wind-maps-mean-rp50-rp100-eventmax.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build basin-scale STORM/STORM_CMCC wind map JSON (mean/rp50/rp100/event_max)."
    )
    parser.add_argument("--basin", choices=sorted(BASIN_DEFAULT_ID.keys()), required=True, help="Basin code to process.")
    parser.add_argument("--basin-id", type=int, default=None, help="Override basin ID (default depends on --basin).")
    parser.add_argument("--cell-deg", type=float, default=0.05, help="Grid cell size in degrees.")
    parser.add_argument("--wind-unit-in", default="m/s", help="Input wind unit in STORM files (m/s, kn, km/h).")
    parser.add_argument(
        "--storm-dir",
        default="/home/ubuntu/uploads/STORM/STORM_ds",
        help="Directory containing STORM txt files.",
    )
    parser.add_argument(
        "--storm-pattern",
        default=None,
        help="Glob pattern for STORM files. Default is inferred from basin.",
    )
    parser.add_argument(
        "--cmcc-dir",
        default="/home/ubuntu/uploads/STORM/STORM_CMCC_ds",
        help="Directory containing STORM_CMCC txt files.",
    )
    parser.add_argument(
        "--cmcc-pattern",
        default=None,
        help="Glob pattern for STORM_CMCC files. Default is inferred from basin.",
    )
    parser.add_argument(
        "--out-json",
        default=None,
        help="Output JSON path. Defaults to outputs/<basin>_wind_maps_<date>/Hazard_maps/<basin>-wind-maps-mean-rp50-rp100-eventmax.json",
    )
    args = parser.parse_args()

    _require_runtime_deps()
    basin_code = str(args.basin).strip().lower()
    basin_tag = basin_code.upper()
    basin_id = int(args.basin_id) if args.basin_id is not None else int(BASIN_DEFAULT_ID[basin_code])
    if not np.isfinite(float(args.cell_deg)) or float(args.cell_deg) <= 0.0:
        raise ValueError("--cell-deg must be a positive finite number")

    storm_pattern = args.storm_pattern or f"STORM_DATA_IBTRACS_{basin_tag}_1000_YEARS_*.txt"
    cmcc_pattern = args.cmcc_pattern or f"STORM_DATA_CMCC-CM2-VHR4_{basin_tag}_1000_YEARS_*_IBTRACSDELTA.txt"

    storm_files = _iter_input_files(Path(args.storm_dir), storm_pattern)
    cmcc_files = _iter_input_files(Path(args.cmcc_dir), cmcc_pattern)

    print(
        f"Building basin '{basin_code}' (basin_id={basin_id}) "
        f"from {len(storm_files)} STORM files and {len(cmcc_files)} STORM_CMCC files...",
        flush=True,
    )

    storm = _aggregate_dataset(
        storm_files,
        basin_id=basin_id,
        wind_unit_in=args.wind_unit_in,
        cell_deg=float(args.cell_deg),
    )
    cmcc = _aggregate_dataset(
        cmcc_files,
        basin_id=basin_id,
        wind_unit_in=args.wind_unit_in,
        cell_deg=float(args.cell_deg),
    )

    bbox = _bbox_from_payload(storm.get("cells", []), cmcc.get("cells", []), float(args.cell_deg))
    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "region": basin_code,
            "region_label": BASIN_LABEL.get(basin_code, basin_code.upper()),
            "bbox": bbox,
            "grid_cell_deg": float(args.cell_deg),
            "basin_id": int(basin_id),
            "wind_unit_in": _normalize_wind_unit(args.wind_unit_in),
            "wind_unit_out": "m/s",
            "scenarios": ["mean", "rp50", "rp100", "event_max"],
            "dataset_links": {
                "storm": [str(path) for path in storm_files],
                "storm_cmcc": [str(path) for path in cmcc_files],
            },
        },
        "storm": storm,
        "storm_cmcc": cmcc,
    }

    out_json = Path(args.out_json) if args.out_json else _default_output_path(basin_code)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_json}", flush=True)
    print(
        f"Summary {basin_code.upper()}: "
        f"STORM years={storm['years_covered']}, cells={storm['cell_count']} | "
        f"STORM_CMCC years={cmcc['years_covered']}, cells={cmcc['cell_count']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
