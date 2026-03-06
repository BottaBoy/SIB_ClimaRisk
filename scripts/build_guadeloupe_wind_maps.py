#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from case_study_sources import CASE_STUDY_BBOX, normalize_territory

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


def _parse_file_block_index(path: Path) -> int:
    m = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not m:
        return 0
    return int(m.group(1))


def _iter_storm_files(root: Path, pattern: str) -> list[Path]:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {root}")
    return files


def _aggregate_mean_wind(
    files: list[Path],
    *,
    basin_id: int,
    wind_unit_in: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    cell_deg: float,
) -> tuple[list[dict], int, int, float, float]:
    sums: dict[tuple[int, int], float] = defaultdict(float)
    counts: dict[tuple[int, int], int] = defaultdict(int)

    year_blocks: set[int] = set()
    unique_tracks = 0

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

            # STORM longitudes are often encoded in [0, 360].
            # Convert to the conventional [-180, 180] before Guadeloupe bbox filtering.
            chunk["lon"] = chunk["lon"].astype(float)
            chunk.loc[chunk["lon"] > 180.0, "lon"] = chunk.loc[chunk["lon"] > 180.0, "lon"] - 360.0

            chunk = chunk[(chunk["basin_id"] == basin_id)]
            if chunk.empty:
                continue

            # Global-year reconstruction: each file is one 1000-year block.
            chunk["year_global"] = chunk["year"].astype(int) + 1000 * block_idx
            unique_tracks += int(chunk[["year_global", "tc_number"]].drop_duplicates().shape[0])

            chunk = chunk[
                (chunk["lat"] >= lat_min)
                & (chunk["lat"] <= lat_max)
                & (chunk["lon"] >= lon_min)
                & (chunk["lon"] <= lon_max)
            ]
            if chunk.empty:
                continue

            chunk["i"] = ((chunk["lat"] - lat_min) / cell_deg).astype(float).apply(math.floor).astype(int)
            chunk["j"] = ((chunk["lon"] - lon_min) / cell_deg).astype(float).apply(math.floor).astype(int)

            grouped = chunk.groupby(["i", "j"], as_index=False).agg(
                sum_wind=("wind_max", "sum"),
                n=("wind_max", "count"),
            )

            for row in grouped.itertuples(index=False):
                key = (int(row.i), int(row.j))
                sums[key] += float(row.sum_wind)
                counts[key] += int(row.n)

    cells: list[dict] = []
    means: list[float] = []

    for (i, j), total in sums.items():
        n = counts[(i, j)]
        if n <= 0:
            continue
        mean_wind = total / n
        lat_center = lat_min + (i + 0.5) * cell_deg
        lon_center = lon_min + (j + 0.5) * cell_deg
        cells.append(
            {
                "lat": round(lat_center, 6),
                "lon": round(lon_center, 6),
                "mean_wind_mps": round(mean_wind, 4),
                "sample_count": int(n),
            }
        )
        means.append(mean_wind)

    cells.sort(key=lambda c: (c["lat"], c["lon"]))

    years_covered = (max(year_blocks) + 1) * 1000 if year_blocks else 0
    mean_min = min(means) if means else 0.0
    mean_max = max(means) if means else 0.0

    return cells, years_covered, unique_tracks, mean_min, mean_max


def main() -> None:
    parser = argparse.ArgumentParser(description="Build territory STORM mean wind map layers from raw STORM text datasets.")
    parser.add_argument("--territory", choices=["guadeloupe", "martinique"], default="guadeloupe")
    parser.add_argument("--storm-dir", default="/home/ubuntu/uploads/STORM/STORM_ds", help="Directory containing STORM present-climate txt files")
    parser.add_argument("--cmcc-dir", default="/home/ubuntu/uploads/STORM/STORM_CMCC_ds", help="Directory containing STORM CMCC txt files")
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--cell-deg", type=float, default=0.05, help="Grid cell size in degrees")
    parser.add_argument("--lat-min", type=float, default=None)
    parser.add_argument("--lat-max", type=float, default=None)
    parser.add_argument("--lon-min", type=float, default=None)
    parser.add_argument("--lon-max", type=float, default=None)
    parser.add_argument("--basin-id", type=int, default=1, help="NA basin id in STORM files")
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in STORM txt files. Supported: m/s, kn, km/h. Output is always m/s.",
    )
    args = parser.parse_args()
    territory = normalize_territory(args.territory)
    default_bbox = CASE_STUDY_BBOX[territory]
    lat_min = float(args.lat_min if args.lat_min is not None else default_bbox["lat_min"])
    lat_max = float(args.lat_max if args.lat_max is not None else default_bbox["lat_max"])
    lon_min = float(args.lon_min if args.lon_min is not None else default_bbox["lon_min"])
    lon_max = float(args.lon_max if args.lon_max is not None else default_bbox["lon_max"])
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)

    storm_dir = Path(args.storm_dir)
    cmcc_dir = Path(args.cmcc_dir)
    out = Path(args.out) if args.out else Path(f"/home/ubuntu/sib-work/web/data/{territory}-wind-maps.json")

    storm_files = _iter_storm_files(storm_dir, "STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt")
    cmcc_files = _iter_storm_files(cmcc_dir, "STORM_DATA_CMCC-CM2-VHR4_NA_1000_YEARS_*_IBTRACSDELTA.txt")

    storm_cells, storm_years, storm_tracks, storm_min, storm_max = _aggregate_mean_wind(
        storm_files,
        basin_id=args.basin_id,
        wind_unit_in=normalized_wind_unit,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        cell_deg=args.cell_deg,
    )

    cmcc_cells, cmcc_years, cmcc_tracks, cmcc_min, cmcc_max = _aggregate_mean_wind(
        cmcc_files,
        basin_id=args.basin_id,
        wind_unit_in=normalized_wind_unit,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        cell_deg=args.cell_deg,
    )

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
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
        },
        "storm": {
            "years_covered": storm_years,
            "tracks_approx": storm_tracks,
            "cell_count": len(storm_cells),
            "mean_wind_min_mps": round(storm_min, 4),
            "mean_wind_max_mps": round(storm_max, 4),
            "cells": storm_cells,
        },
        "storm_cmcc": {
            "years_covered": cmcc_years,
            "tracks_approx": cmcc_tracks,
            "cell_count": len(cmcc_cells),
            "mean_wind_min_mps": round(cmcc_min, 4),
            "mean_wind_max_mps": round(cmcc_max, 4),
            "cells": cmcc_cells,
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out}")
    print(f"territory={territory} bbox=[{lat_min},{lat_max}]x[{lon_min},{lon_max}]")
    print(f"STORM cells={len(storm_cells)} years={storm_years} tracks~={storm_tracks} mean_wind_range=[{storm_min:.3f},{storm_max:.3f}]")
    print(f"STORM_CMCC cells={len(cmcc_cells)} years={cmcc_years} tracks~={cmcc_tracks} mean_wind_range=[{cmcc_min:.3f},{cmcc_max:.3f}]")


if __name__ == "__main__":
    main()
