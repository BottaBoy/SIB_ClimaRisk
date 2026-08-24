#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import numpy as np
from osgeo import gdal


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from case_study_sources import parse_territory  # noqa: E402

DEFAULT_WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DEFAULT_LANDSLIDE_ROOT = Path("/home/ubuntu/uploads/Landslide")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expanded_grid(meta: dict[str, Any]) -> dict[str, Any]:
    bbox = meta.get("bbox") if isinstance(meta.get("bbox"), dict) else {}
    cell_deg = float(meta.get("grid_cell_deg") or 0.02)
    south = float(bbox.get("lat_min"))
    west = float(bbox.get("lon_min"))
    north = float(bbox.get("lat_max"))
    east = float(bbox.get("lon_max"))
    if not all(map(math.isfinite, [south, west, north, east, cell_deg])) or cell_deg <= 0.0:
        raise ValueError(f"Invalid grid metadata in {meta!r}")
    n_lat = int(math.ceil((north - south) / cell_deg))
    n_lon = int(math.ceil((east - west) / cell_deg))
    north = south + (n_lat * cell_deg)
    east = west + (n_lon * cell_deg)
    return {
        "cell_deg": cell_deg,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "n_lat": n_lat,
        "n_lon": n_lon,
    }


def _warp_average(path: Path, grid: dict[str, Any]) -> np.ndarray:
    src = gdal.Open(str(path))
    if src is None:
        raise FileNotFoundError(f"Unable to open raster: {path}")

    options = gdal.WarpOptions(
        format="MEM",
        outputBounds=(grid["west"], grid["south"], grid["east"], grid["north"]),
        width=int(grid["n_lon"]),
        height=int(grid["n_lat"]),
        resampleAlg=gdal.GRA_Average,
        dstNodata=0.0,
    )
    warped = gdal.Warp("", src, options=options)
    if warped is None:
        raise RuntimeError(f"Unable to warp raster to case-study grid: {path}")

    arr = warped.ReadAsArray()
    if arr is None:
        raise RuntimeError(f"Unable to read warped raster: {path}")
    return np.asarray(arr, dtype=float)


def _warp_average_multiple(paths: list[Path], grid: dict[str, Any]) -> np.ndarray:
    if not paths:
        raise ValueError("At least one raster path is required to compute a visual landslide map")

    total: np.ndarray | None = None
    count = 0
    for path in paths:
        raster = _warp_average(path, grid)
        if total is None:
            total = np.zeros_like(raster, dtype=float)
        if total.shape != raster.shape:
            raise RuntimeError(
                "Warped landslide rasters do not share the same shape: "
                f"{total.shape if total is not None else None} vs {raster.shape} for {path}"
            )
        total += np.nan_to_num(raster, nan=0.0, posinf=0.0, neginf=0.0)
        count += 1

    if total is None or count == 0:
        raise RuntimeError("Unable to compute average landslide raster from empty source list")
    return total / float(count)


def _prefer_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    if not candidates:
        raise ValueError("No candidate path provided")
    return candidates[0]


def _approx_sample_count(path: Path, cell_deg: float) -> int:
    src = gdal.Open(str(path))
    if src is None:
        return 1
    gt = src.GetGeoTransform()
    if not gt:
        return 1
    x_res = abs(float(gt[1]) or 0.0)
    y_res = abs(float(gt[5]) or 0.0)
    if x_res <= 0.0 or y_res <= 0.0:
        return 1
    return max(1, int(round((cell_deg / x_res) * (cell_deg / y_res))))


def _build_landslide_payload(
    *,
    territory: str,
    wind_maps: dict[str, Any],
    source_paths: dict[str, list[Path]],
    generated_at: str,
) -> dict[str, Any]:
    meta = wind_maps.get("meta") if isinstance(wind_maps, dict) else {}
    if not isinstance(meta, dict):
        raise ValueError(f"Wind map metadata missing for {territory}")

    grid = _expanded_grid(meta)
    template_cells = list((wind_maps.get("storm") or {}).get("cells") or [])
    if not template_cells:
        raise ValueError(f"No wind-map template cells found for {territory}")

    sample_count = _approx_sample_count(source_paths["storm"][0], grid["cell_deg"])

    payload: dict[str, Any] = {
        "meta": {
            "generated_at": generated_at,
            "case_study_run_id": str(meta.get("case_study_run_id") or "").strip(),
            "territory": str(meta.get("territory") or territory).strip().lower(),
            "territory_label": str(meta.get("territory_label") or territory.title()).strip(),
            "bbox": meta.get("bbox"),
            "grid_cell_deg": grid["cell_deg"],
            "hazard_components": ["landslide"],
            "component_units": {
                "landslide": "risque score",
            },
            "landslide_sources": {
                "storm": [str(path) for path in source_paths["storm"]],
                "storm_cmcc": [str(path) for path in source_paths["storm_cmcc"]],
            },
            "landslide_class_mapping": {
                "0": "probabilite nulle",
                "1": "probabilite nulle",
                "2": "faible",
                "3": "moyenne",
                "4": "forte",
                "5": "tres forte",
            },
            "territory_mask_path": meta.get("territory_mask_path"),
            "territory_mask_source": meta.get("territory_mask_source"),
            "cell_clip_rule": meta.get("cell_clip_rule"),
        },
    }

    for hazard_key in ("storm", "storm_cmcc"):
        raster = _warp_average_multiple(source_paths[hazard_key], grid)
        values: list[float] = []
        cells: list[dict[str, Any]] = []
        for cell in template_cells:
            try:
                i = int(cell["i"])
                j = int(cell["j"])
            except Exception:
                continue
            row = int(grid["n_lat"]) - 1 - i
            if row < 0 or row >= raster.shape[0] or j < 0 or j >= raster.shape[1]:
                continue
            value = float(raster[row, j])
            if not np.isfinite(value):
                value = 0.0
            values.append(value)
            cells.append(
                {
                    "i": i,
                    "j": j,
                    "lat": float(cell.get("lat")),
                    "lon": float(cell.get("lon")),
                    "mean_landslide_score": round(value, 6),
                    "sample_count": sample_count,
                }
            )

        value_array = np.asarray(values, dtype=float)
        payload[hazard_key] = {
            "cell_count": len(cells),
            "mean_landslide_score_min": round(float(np.nanmin(value_array)) if value_array.size else 0.0, 6),
            "mean_landslide_score_max": round(float(np.nanmax(value_array)) if value_array.size else 0.0, 6),
            "mean_landslide_score_mean": round(float(np.nanmean(value_array)) if value_array.size else 0.0, 6),
            "source_tifs": [str(path) for path in source_paths[hazard_key]],
            "sample_count": sample_count,
            "cells": cells,
        }

    return payload


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build case-study landslide map JSON files from NGI probabilistic rasters.")
    parser.add_argument(
        "--web-data-dir",
        type=Path,
        default=DEFAULT_WEB_DATA_DIR,
        help="Directory containing the case-study wind map JSON files and the output landslide JSON files.",
    )
    parser.add_argument(
        "--landslide-root",
        type=Path,
        default=DEFAULT_LANDSLIDE_ROOT,
        help="Directory containing the landslide GeoTIFF rasters.",
    )
    parser.add_argument(
        "--territories",
        nargs="+",
        default=["guadeloupe", "martinique"],
        help="Territories to process.",
    )
    args = parser.parse_args()
    try:
        args.territories = [parse_territory(value) for value in args.territories]
    except ValueError as exc:
        parser.error(str(exc))

    web_data_dir = Path(args.web_data_dir)
    landslide_root = Path(args.landslide_root)
    settings = load_settings()
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    for territory in args.territories:
        base = str(territory).strip().lower()
        wind_map_path = web_data_dir / f"{base}-wind-maps.json"
        if not wind_map_path.exists():
            raise FileNotFoundError(f"Missing wind map JSON: {wind_map_path}")

        wind_maps = _load_json(wind_map_path)
        source_paths = {
            "storm": [
                _prefer_existing_path(
                    landslide_root / "LS_GuaMar_Precipitation_ClimatActuel.tif",
                    Path(settings.landslide_precip_current_path),
                ),
                _prefer_existing_path(
                    landslide_root / "LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif",
                    landslide_root / "LS_GuaMar_Eathquake.tif",
                    landslide_root / "LS_GuaMar_Earthquake.tif",
                    Path(settings.landslide_earthquake_path),
                ),
            ],
            "storm_cmcc": [
                _prefer_existing_path(
                    landslide_root / "LS_GuaMar_Precipitation_ClimatSSP585.tif",
                    Path(settings.landslide_precip_ssp585_path),
                ),
                _prefer_existing_path(
                    landslide_root / "LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif",
                    landslide_root / "LS_GuaMar_Eathquake.tif",
                    landslide_root / "LS_GuaMar_Earthquake.tif",
                    Path(settings.landslide_earthquake_path),
                ),
            ],
        }
        for key, paths in source_paths.items():
            if not paths:
                raise FileNotFoundError(f"Missing landslide raster list for {base}/{key}")
            for path in paths:
                if not path.exists():
                    raise FileNotFoundError(f"Missing landslide raster for {base}/{key}: {path}")

        payload = _build_landslide_payload(
            territory=base,
            wind_maps=wind_maps,
            source_paths=source_paths,
            generated_at=generated_at,
        )
        output_path = web_data_dir / f"{base}-landslide-maps.json"
        _write_payload(output_path, payload)
        print(
            f"Wrote {output_path} with {payload['storm']['cell_count']} {base} cells "
            f"(storm mean={payload['storm']['mean_landslide_score_mean']}, "
            f"storm_cmcc mean={payload['storm_cmcc']['mean_landslide_score_mean']})."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
