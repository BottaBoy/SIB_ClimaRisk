#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
import numpy as np
from PIL import Image


def _norm_hazard(raw: str) -> str:
    return "storm_cmcc" if str(raw).strip().lower() == "storm_cmcc" else "storm"


def _norm_metric(raw: str) -> str:
    value = str(raw).strip().lower()
    if value == "rp50":
        return "rp50"
    if value == "rp100":
        return "rp100"
    return "mean"


def _metric_value_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_mps"
    if metric == "rp100":
        return "rp100_wind_mps"
    return "mean_wind_mps"


def _metric_min_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_min_mps"
    if metric == "rp100":
        return "rp100_wind_min_mps"
    return "mean_wind_min_mps"


def _metric_max_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_max_mps"
    if metric == "rp100":
        return "rp100_wind_max_mps"
    return "mean_wind_max_mps"


def _extract_bounds_and_grid(payload: dict, cell_deg: float) -> tuple[float, float, float, float, int, int]:
    all_cells: list[dict] = []
    for hazard in ("storm", "storm_cmcc"):
        all_cells.extend(payload.get(hazard, {}).get("cells", []))
    if not all_cells:
        raise ValueError("No cells found in payload")

    lats = np.array([float(c["lat"]) for c in all_cells], dtype=float)
    lons = np.array([float(c["lon"]) for c in all_cells], dtype=float)

    min_lat_center = float(np.min(lats))
    max_lat_center = float(np.max(lats))
    min_lon_center = float(np.min(lons))
    max_lon_center = float(np.max(lons))

    south = min_lat_center - (cell_deg / 2.0)
    north = max_lat_center + (cell_deg / 2.0)
    west = min_lon_center - (cell_deg / 2.0)
    east = max_lon_center + (cell_deg / 2.0)

    n_lat = int(round((north - south) / cell_deg))
    n_lon = int(round((east - west) / cell_deg))
    if n_lat <= 0 or n_lon <= 0:
        raise ValueError("Invalid grid dimensions computed from cells")

    return south, north, west, east, n_lat, n_lon


def _build_value_grid(cells: list[dict], value_key: str, *, south: float, west: float, cell_deg: float, n_lat: int, n_lon: int) -> np.ndarray:
    grid = np.full((n_lat, n_lon), np.nan, dtype=np.float32)
    for cell in cells:
        lat = float(cell.get("lat", np.nan))
        lon = float(cell.get("lon", np.nan))
        value = float(cell.get(value_key, np.nan))
        if not np.isfinite(lat) or not np.isfinite(lon) or not np.isfinite(value):
            continue

        i = int(np.floor((lat - south) / cell_deg))
        j = int(np.floor((lon - west) / cell_deg))
        if i < 0 or i >= n_lat or j < 0 or j >= n_lon:
            continue

        prev = grid[i, j]
        if np.isnan(prev) or value > prev:
            grid[i, j] = value

    return grid


def _grid_to_rgba(grid: np.ndarray, *, vmin: float, vmax: float, cmap_name: str = "turbo") -> np.ndarray:
    den = max(vmax - vmin, 1e-9)
    norm = np.clip((grid - vmin) / den, 0.0, 1.0)
    cmap = colormaps.get_cmap(cmap_name)
    rgba = (cmap(norm) * 255.0).astype(np.uint8)
    rgba[..., 3] = np.where(np.isnan(grid), 0, 255).astype(np.uint8)
    # Leaflet imageOverlay expects row 0 at north, while our i=0 is south.
    rgba = np.flipud(rgba)
    return rgba


def main() -> None:
    parser = argparse.ArgumentParser(description="Build transparent NA wind overlays for Leaflet from NA hazard JSON")
    parser.add_argument(
        "--input-json",
        default="/home/ubuntu/sib-work/outputs/na_wind_maps_20260310/Hazard_maps/na-wind-maps-rp50-rp100.json",
        help="Path to NA wind JSON (storm + storm_cmcc with mean/rp50/rp100)",
    )
    parser.add_argument(
        "--out-dir",
        default="/home/ubuntu/sib-work/outputs/na_wind_maps_20260310/Hazard_maps",
        help="Output directory for overlays and metadata",
    )
    parser.add_argument("--cmap", default="turbo", help="Matplotlib colormap")
    args = parser.parse_args()

    input_json = Path(args.input_json)
    out_dir = Path(args.out_dir)
    overlay_dir = out_dir / "leaflet_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(input_json.read_text(encoding="utf-8"))

    cell_deg = float(payload.get("meta", {}).get("grid_cell_deg", 0.05))
    if not np.isfinite(cell_deg) or cell_deg <= 0:
        raise ValueError("Invalid grid_cell_deg in payload meta")

    south, north, west, east, n_lat, n_lon = _extract_bounds_and_grid(payload, cell_deg)

    metrics = ["mean", "rp50", "rp100"]
    hazards = ["storm", "storm_cmcc"]

    metric_ranges: dict[str, dict[str, float]] = {}
    for metric in metrics:
        min_key = _metric_min_key(metric)
        max_key = _metric_max_key(metric)
        mn = min(float(payload[h][min_key]) for h in hazards)
        mx = max(float(payload[h][max_key]) for h in hazards)
        metric_ranges[metric] = {
            "min_mps": float(mn),
            "max_mps": float(mx),
        }

    overlays: dict[str, dict[str, str]] = {"storm": {}, "storm_cmcc": {}}
    for hazard in hazards:
        cells = payload.get(hazard, {}).get("cells", [])
        if not isinstance(cells, list):
            raise ValueError(f"Invalid cells for hazard {hazard}")
        for metric in metrics:
            value_key = _metric_value_key(metric)
            grid = _build_value_grid(
                cells,
                value_key,
                south=south,
                west=west,
                cell_deg=cell_deg,
                n_lat=n_lat,
                n_lon=n_lon,
            )
            rgba = _grid_to_rgba(
                grid,
                vmin=float(metric_ranges[metric]["min_mps"]),
                vmax=float(metric_ranges[metric]["max_mps"]),
                cmap_name=args.cmap,
            )
            file_name = f"na_{hazard}_{metric}_overlay.png"
            out_png = overlay_dir / file_name
            Image.fromarray(rgba, mode="RGBA").save(out_png, format="PNG", optimize=True)
            overlays[hazard][metric] = f"leaflet_overlays/{file_name}"

    metadata = {
        "meta": {
            "source_json": str(input_json),
            "bounds": {
                "south": float(south),
                "north": float(north),
                "west": float(west),
                "east": float(east),
            },
            "grid": {
                "cell_deg": float(cell_deg),
                "n_lat": int(n_lat),
                "n_lon": int(n_lon),
            },
            "colormap": str(args.cmap),
        },
        "metrics": metric_ranges,
        "overlays": overlays,
    }

    out_json = out_dir / "na-leaflet-overlays.json"
    out_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote overlays in {overlay_dir}")
    print(f"Wrote metadata {out_json}")


if __name__ == "__main__":
    main()
