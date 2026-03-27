#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import colormaps
except Exception:  # pragma: no cover - optional at import time for CLI --help
    matplotlib = None  # type: ignore[assignment]
    colormaps = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional at import time for CLI --help
    Image = None  # type: ignore[assignment]

try:
    from scipy import ndimage
except Exception:  # pragma: no cover - optional at import time for CLI --help
    ndimage = None  # type: ignore[assignment]

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
BASIN_LABEL = {
    "na": "Nord Atlantique",
    "si": "Sud Indien",
}
SCENARIO_LABEL = {
    "mean": "Moyenne annuelle",
    "rp50": "Temps de retour 50 ans",
    "rp100": "Temps de retour 100 ans",
    "event_max": "Evenement le plus fort",
}
CMCC_RP_LOW_BAND_HIDE_MAX_MPS = 18.0


def _require_render_deps() -> None:
    missing: list[str] = []
    if matplotlib is None or colormaps is None:
        missing.append("matplotlib")
    if np is None:
        missing.append("numpy")
    if Image is None:
        missing.append("pillow")
    if ndimage is None:
        missing.append("scipy")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_basin_wind_leaflet_overlays.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install required packages and retry."
        )


def _norm_hazard(raw: str) -> str:
    return "storm_cmcc" if str(raw).strip().lower() == "storm_cmcc" else "storm"


def _norm_metric(raw: str) -> str:
    value = str(raw).strip().lower()
    if value == "rp50":
        return "rp50"
    if value == "rp100":
        return "rp100"
    if value == "event_max":
        return "event_max"
    return "mean"


def _metric_value_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_mps"
    if metric == "rp100":
        return "rp100_wind_mps"
    if metric == "event_max":
        return "event_max_wind_mps"
    return "mean_wind_mps"


def _metric_min_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_min_mps"
    if metric == "rp100":
        return "rp100_wind_min_mps"
    if metric == "event_max":
        return "event_max_wind_min_mps"
    return "mean_wind_min_mps"


def _metric_max_key(metric: str) -> str:
    if metric == "rp50":
        return "rp50_wind_max_mps"
    if metric == "rp100":
        return "rp100_wind_max_mps"
    if metric == "event_max":
        return "event_max_wind_max_mps"
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
    rgba = np.flipud(rgba)
    return rgba


def _fill_nan_nearest_with_mask(grid: np.ndarray, *, max_distance_cells: float) -> tuple[np.ndarray, np.ndarray]:
    threshold = float(max_distance_cells)
    if not np.isfinite(threshold):
        threshold = 1.5
    threshold = max(0.0, threshold)

    mask = np.isnan(grid)
    if not np.any(mask):
        clean = np.asarray(grid, dtype=np.float32).copy()
        return clean, np.ones_like(clean, dtype=bool)
    if np.all(mask):
        empty = np.zeros_like(grid, dtype=np.float32)
        return empty, np.zeros_like(empty, dtype=bool)

    distance, nearest_indices = ndimage.distance_transform_edt(mask, return_indices=True)
    filled = np.asarray(grid, dtype=np.float32).copy()
    fillable = mask & (distance <= threshold)
    if np.any(fillable):
        filled[fillable] = filled[tuple(nearest_indices[:, fillable])]
    render_mask = (~mask) | fillable
    return filled, render_mask


def _mask_cmcc_low_rp_band(grid_render: np.ndarray, hazard: str, metric: str) -> np.ndarray:
    if str(hazard).strip().lower() != "storm_cmcc":
        return grid_render
    if str(metric).strip().lower() not in {"rp50", "rp100"}:
        return grid_render
    out = np.asarray(grid_render, dtype=np.float32).copy()
    out[out <= float(CMCC_RP_LOW_BAND_HIDE_MAX_MPS)] = np.nan
    return out


def _finite_metric_values(cells: list[dict], metric_key: str) -> list[float]:
    out: list[float] = []
    for cell in cells:
        value = float(cell.get(metric_key, np.nan))
        if np.isfinite(value):
            out.append(value)
    return out


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    return float(np.mean(arr))


def _comparison_rows(payload: dict) -> list[dict]:
    rows: list[dict] = []
    storm_cells = payload.get("storm", {}).get("cells", [])
    cmcc_cells = payload.get("storm_cmcc", {}).get("cells", [])
    if not isinstance(storm_cells, list) or not isinstance(cmcc_cells, list):
        return rows

    for scenario in ("mean", "rp50", "rp100", "event_max"):
        metric_key = _metric_value_key(scenario)
        storm_avg = _average(_finite_metric_values(storm_cells, metric_key))
        cmcc_avg = _average(_finite_metric_values(cmcc_cells, metric_key))
        rows.append(
            {
                "scenario": scenario,
                "indicator": f"Vent - {SCENARIO_LABEL[scenario]} (m/s)",
                "storm_mps": round(float(storm_avg), 4),
                "storm_cmcc_mps": round(float(cmcc_avg), 4),
                "delta_mps": round(float(cmcc_avg - storm_avg), 4),
            }
        )

    # Explicit absolute maximum over basin cells (event_max per cell, then max over cells).
    event_metric = _metric_value_key("event_max")
    storm_event_values = _finite_metric_values(storm_cells, event_metric)
    cmcc_event_values = _finite_metric_values(cmcc_cells, event_metric)
    if storm_event_values and cmcc_event_values:
        storm_abs_max = float(np.max(np.asarray(storm_event_values, dtype=float)))
        cmcc_abs_max = float(np.max(np.asarray(cmcc_event_values, dtype=float)))
        rows.append(
            {
                "scenario": "absolute_max",
                "indicator": "Vent - Maximum absolu (m/s)",
                "storm_mps": round(storm_abs_max, 4),
                "storm_cmcc_mps": round(cmcc_abs_max, 4),
                "delta_mps": round(float(cmcc_abs_max - storm_abs_max), 4),
            }
        )
    return rows


def _metric_ranges(payload: dict) -> dict[str, dict[str, float]]:
    metrics = ("mean", "rp50", "rp100", "event_max")
    hazards = ("storm", "storm_cmcc")
    out: dict[str, dict[str, float]] = {}
    for metric in metrics:
        min_key = _metric_min_key(metric)
        max_key = _metric_max_key(metric)
        mins: list[float] = []
        maxs: list[float] = []
        for hazard in hazards:
            hz = payload.get(hazard, {})
            value_min = float(hz.get(min_key, np.nan))
            value_max = float(hz.get(max_key, np.nan))
            if np.isfinite(value_min):
                mins.append(value_min)
            if np.isfinite(value_max):
                maxs.append(value_max)
        out[metric] = {
            "min_mps": float(min(mins)) if mins else 0.0,
            "max_mps": float(max(maxs)) if maxs else 0.0,
        }
    return out


def _parse_update_basins(raw: str) -> list[str]:
    values = [str(v).strip().lower() for v in str(raw or "").split(",")]
    clean = [v for v in values if v in {"na", "si"}]
    dedup: list[str] = []
    for basin in clean:
        if basin not in dedup:
            dedup.append(basin)
    return dedup


def _safe_read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_basin_entry(
    *,
    basin: str,
    source_json_path: Path,
    overlay_dir: Path,
    cmap: str,
    fill_mode: str,
    fill_max_distance_cells: float,
) -> dict:
    payload = json.loads(source_json_path.read_text(encoding="utf-8"))
    cell_deg = float(payload.get("meta", {}).get("grid_cell_deg", 0.05))
    if not np.isfinite(cell_deg) or cell_deg <= 0.0:
        raise ValueError(f"Invalid grid_cell_deg in payload for basin {basin}")

    south, north, west, east, n_lat, n_lon = _extract_bounds_and_grid(payload, cell_deg)
    metrics = ("mean", "rp50", "rp100", "event_max")
    hazards = ("storm", "storm_cmcc")

    ranges = _metric_ranges(payload)
    overlays: dict[str, dict[str, str]] = {"storm": {}, "storm_cmcc": {}}
    for hazard in hazards:
        cells = payload.get(hazard, {}).get("cells", [])
        if not isinstance(cells, list):
            raise ValueError(f"Invalid cells for basin={basin}, hazard={hazard}")
        for metric in metrics:
            metric_key = _metric_value_key(metric)
            grid = _build_value_grid(
                cells,
                metric_key,
                south=south,
                west=west,
                cell_deg=cell_deg,
                n_lat=n_lat,
                n_lon=n_lon,
            )
            render_mask = ~np.isnan(grid)
            if fill_mode == "nearest":
                grid, render_mask = _fill_nan_nearest_with_mask(
                    grid,
                    max_distance_cells=float(fill_max_distance_cells),
                )
            grid_render = np.where(render_mask, grid, np.nan)
            grid_render = _mask_cmcc_low_rp_band(grid_render, hazard, metric)
            rgba = _grid_to_rgba(
                grid_render,
                vmin=float(ranges[metric]["min_mps"]),
                vmax=float(ranges[metric]["max_mps"]),
                cmap_name=cmap,
            )
            file_name = f"{basin}_{hazard}_{metric}_overlay.png"
            out_png = overlay_dir / file_name
            Image.fromarray(rgba, mode="RGBA").save(out_png, format="PNG", optimize=True)
            overlays[hazard][metric] = f"leaflet_overlays/{file_name}"

    return {
        "label": BASIN_LABEL.get(basin, basin.upper()),
        "source_json": str(source_json_path),
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
        "metrics": ranges,
        "overlays": overlays,
        "comparison_rows": _comparison_rows(payload),
        "storm_years_covered": int(payload.get("storm", {}).get("years_covered", 0)),
        "storm_cmcc_years_covered": int(payload.get("storm_cmcc", {}).get("years_covered", 0)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build/merge basin Leaflet wind overlays and metadata (NA/SI) from basin wind JSON files."
    )
    parser.add_argument("--na-input-json", default=None, help="Path to NA wind JSON source.")
    parser.add_argument("--si-input-json", default=None, help="Path to SI wind JSON source.")
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "web" / "hazard-maps"),
        help="Output directory for overlays and metadata.",
    )
    parser.add_argument(
        "--metadata-file",
        default="basin-leaflet-overlays.json",
        help="Output metadata JSON filename (inside --out-dir).",
    )
    parser.add_argument(
        "--update-basins",
        default="na",
        help="Comma-separated list of basins to regenerate: na, si, na,si. Non-updated basins are preserved from existing metadata.",
    )
    parser.add_argument("--cmap", default="turbo", help="Matplotlib colormap.")
    parser.add_argument(
        "--fill-mode",
        choices=["nearest", "none"],
        default="nearest",
        help="Fill mode for empty grid cells before rendering.",
    )
    parser.add_argument(
        "--fill-max-distance-cells",
        type=float,
        default=1.5,
        help="Max nearest-fill distance (in grid cells) for transparent overlays.",
    )
    args = parser.parse_args()
    _require_render_deps()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir = out_dir / "leaflet_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    out_metadata = out_dir / str(args.metadata_file)

    update_basins = _parse_update_basins(args.update_basins)
    if not update_basins:
        raise ValueError("--update-basins must contain at least one basin among: na, si")

    source_paths = {
        "na": Path(args.na_input_json) if args.na_input_json else None,
        "si": Path(args.si_input_json) if args.si_input_json else None,
    }
    for basin in update_basins:
        src = source_paths.get(basin)
        if src is None:
            raise ValueError(f"Missing --{basin}-input-json while basin '{basin}' is requested in --update-basins")
        if not src.exists():
            raise FileNotFoundError(f"Input JSON not found for basin '{basin}': {src}")

    existing = _safe_read_json(out_metadata)
    existing_basins = existing.get("basins", {}) if isinstance(existing.get("basins"), dict) else {}
    merged_basins: dict[str, dict] = dict(existing_basins)

    for basin in update_basins:
        print(f"Building overlays for basin '{basin}'...", flush=True)
        source_json = source_paths[basin]
        assert source_json is not None
        merged_basins[basin] = _build_basin_entry(
            basin=basin,
            source_json_path=source_json,
            overlay_dir=overlay_dir,
            cmap=str(args.cmap),
            fill_mode=str(args.fill_mode),
            fill_max_distance_cells=float(args.fill_max_distance_cells),
        )

    if not merged_basins:
        raise RuntimeError("No basin metadata available after merge.")

    metadata = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": 1,
            "updated_basins": update_basins,
            "default_basin": "na",
            "colormap": str(args.cmap),
            "fill_mode": str(args.fill_mode),
            "fill_max_distance_cells": float(args.fill_max_distance_cells),
            "cmcc_rp_low_band_hidden_mps_lte": float(CMCC_RP_LOW_BAND_HIDE_MAX_MPS),
        },
        "basins": merged_basins,
    }

    out_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote metadata {out_metadata}", flush=True)


if __name__ == "__main__":
    main()
