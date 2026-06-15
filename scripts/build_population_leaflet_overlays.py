#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from osgeo import gdal


FILE_PATTERN = re.compile(r"^([a-z]{3})_pop_2020_CN_100m_R2025A_v1\.tif$", re.IGNORECASE)
DEFAULT_PALETTE_HEX = [
    "#f2f2f2",
    "#d9d9d9",
    "#bdbdbd",
    "#969696",
    "#737373",
    "#525252",
    "#3a3a3a",
    "#1f1f1f",
    "#000000",
]
TERRITORY_NAMES = {
    "blm": "Saint-Barthelemy",
    "glp": "Guadeloupe",
    "maf": "Saint-Martin",
    "mtq": "Martinique",
    "myt": "Mayotte",
    "ncl": "Nouvelle-Caledonie",
    "pyf": "Polynesie francaise",
    "reu": "La Reunion",
    "spm": "Saint-Pierre-et-Miquelon",
    "wlf": "Wallis-et-Futuna",
}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    raw = str(hex_color).strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Invalid color '{hex_color}'")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _build_palette_lut(palette_hex: list[str]) -> np.ndarray:
    palette = np.asarray([_hex_to_rgb(c) for c in palette_hex], dtype=np.float32)
    n = palette.shape[0]
    if n < 2:
        raise ValueError("Palette must contain at least two colors")

    x = np.linspace(0.0, float(n - 1), 256, dtype=np.float32)
    idx0 = np.floor(x).astype(np.int32)
    idx1 = np.clip(idx0 + 1, 0, n - 1)
    frac = (x - idx0).reshape((-1, 1))

    lut = np.round(palette[idx0] * (1.0 - frac) + palette[idx1] * frac).astype(np.uint8)
    return lut


def _discover_rasters(input_dir: Path) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for path in sorted(input_dir.glob("*_pop_2020_CN_100m_R2025A_v1.tif")):
        match = FILE_PATTERN.match(path.name)
        if not match:
            continue
        code = match.group(1).lower()
        items.append((code, path))
    return items


def _safe_bounds(ds: gdal.Dataset) -> tuple[float, float, float, float]:
    gt = ds.GetGeoTransform(can_return_null=True)
    if gt is None:
        raise ValueError("Missing geotransform")
    west, north = gdal.ApplyGeoTransform(gt, 0.0, 0.0)
    east, south = gdal.ApplyGeoTransform(gt, float(ds.RasterXSize), float(ds.RasterYSize))
    south_v = float(min(south, north))
    north_v = float(max(south, north))
    west_v = float(min(west, east))
    east_v = float(max(west, east))
    return south_v, north_v, west_v, east_v


def _resampled_shape(width: int, height: int, max_dim: int) -> tuple[int, int]:
    max_src = max(int(width), int(height))
    if max_src <= 0:
        return 1, 1
    scale = min(1.0, float(max_dim) / float(max_src))
    out_w = max(1, int(round(float(width) * scale)))
    out_h = max(1, int(round(float(height) * scale)))
    return out_w, out_h


def _dataset_positive_max(ds: gdal.Dataset, band_index: int = 1) -> float:
    band = ds.GetRasterBand(band_index)
    max_val = band.GetMaximum()
    if max_val is None or not np.isfinite(float(max_val)) or float(max_val) <= 0.0:
        stats = band.GetStatistics(False, True)
        if stats and len(stats) >= 2 and np.isfinite(float(stats[1])):
            max_val = float(stats[1])
    if max_val is None or not np.isfinite(float(max_val)) or float(max_val) <= 0.0:
        sample = band.ReadAsArray(
            0,
            0,
            ds.RasterXSize,
            ds.RasterYSize,
            min(1024, max(1, ds.RasterXSize)),
            min(1024, max(1, ds.RasterYSize)),
        )
        if sample is None:
            return 0.0
        sample_arr = np.asarray(sample, dtype=np.float32)
        nodata = band.GetNoDataValue()
        mask = np.isfinite(sample_arr)
        if nodata is not None and np.isfinite(float(nodata)):
            mask &= sample_arr != np.float32(nodata)
        mask &= sample_arr > 0.0
        if np.any(mask):
            return float(np.max(sample_arr[mask]))
        return 0.0
    return float(max_val)


def _territory_name(code: str) -> str:
    if code in TERRITORY_NAMES:
        return TERRITORY_NAMES[code]
    return code.upper()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Leaflet population overlays from WorldPop rasters.")
    parser.add_argument("--input-dir", default="/home/ubuntu/uploads/Population", help="Directory containing *_pop_2020*.tif files")
    parser.add_argument("--out-dir", default="/home/ubuntu/sib-work/web/hazard-maps", help="Output base directory")
    parser.add_argument("--max-dimension", type=int, default=3000, help="Max output width/height in pixels per overlay")
    parser.add_argument("--alpha", type=int, default=235, help="Alpha channel value for populated pixels (0-255)")
    parser.add_argument("--json-name", default="population-overlays.json", help="Output metadata JSON filename")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    overlay_dir = out_dir / "population_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    rasters = _discover_rasters(input_dir)
    if not rasters:
        raise SystemExit(f"No population rasters found in {input_dir}")

    gdal.UseExceptions()
    scale_max = 0.0
    for code, tif_path in rasters:
        ds = gdal.Open(str(tif_path), gdal.GA_ReadOnly)
        if ds is None:
            print(f"Skipped {tif_path.name}: cannot open")
            continue
        try:
            local_max = _dataset_positive_max(ds, 1)
            if np.isfinite(local_max):
                scale_max = max(scale_max, float(local_max))
        finally:
            ds = None

    if not np.isfinite(scale_max) or scale_max <= 0:
        scale_max = 1.0

    lut = _build_palette_lut(DEFAULT_PALETTE_HEX)
    territories: list[dict] = []
    alpha = int(max(0, min(255, int(args.alpha))))

    for code, tif_path in rasters:
        ds = gdal.Open(str(tif_path), gdal.GA_ReadOnly)
        if ds is None:
            print(f"Skipped {tif_path.name}: cannot open")
            continue
        try:
            band = ds.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            src_w = int(ds.RasterXSize)
            src_h = int(ds.RasterYSize)
            out_w, out_h = _resampled_shape(src_w, src_h, int(args.max_dimension))

            raw = band.ReadAsArray(0, 0, src_w, src_h, out_w, out_h)
            if raw is None:
                print(f"Skipped {tif_path.name}: cannot read raster band")
                continue

            arr = np.asarray(raw, dtype=np.float32)
            valid = np.isfinite(arr)
            if nodata is not None and np.isfinite(float(nodata)):
                valid &= arr != np.float32(nodata)
            valid &= arr > 0.0
            if not np.any(valid):
                print(f"Skipped {tif_path.name}: no positive population cells")
                continue

            norm = np.zeros_like(arr, dtype=np.float32)
            norm[valid] = np.sqrt(np.clip(arr[valid] / float(scale_max), 0.0, 1.0))
            idx = np.clip(np.round(norm * 255.0), 0.0, 255.0).astype(np.uint8)

            rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
            rgba[..., :3] = lut[idx]
            rgba[..., 3] = np.where(valid, alpha, 0).astype(np.uint8)
            rgba[~valid, :3] = 0

            file_name = f"{code}_population_overlay.png"
            out_png = overlay_dir / file_name
            mem_drv = gdal.GetDriverByName("MEM")
            png_drv = gdal.GetDriverByName("PNG")
            if mem_drv is None or png_drv is None:
                raise RuntimeError("GDAL MEM/PNG drivers are required to write overlays")
            mem_ds = mem_drv.Create("", int(arr.shape[1]), int(arr.shape[0]), 4, gdal.GDT_Byte)
            if mem_ds is None:
                raise RuntimeError("Could not allocate in-memory GDAL dataset")
            for band_idx in range(4):
                mem_ds.GetRasterBand(band_idx + 1).WriteArray(rgba[:, :, band_idx])
            created = png_drv.CreateCopy(str(out_png), mem_ds, strict=0, options=["ZLEVEL=9"])
            if created is None:
                raise RuntimeError(f"Could not write PNG overlay {out_png}")
            created = None
            mem_ds = None

            south, north, west, east = _safe_bounds(ds)
            valid_values = arr[valid]
            territories.append(
                {
                    "code": code,
                    "name": _territory_name(code),
                    "source_tif": str(tif_path),
                    "overlay": f"population_overlays/{file_name}",
                    "bounds": {
                        "south": south,
                        "north": north,
                        "west": west,
                        "east": east,
                    },
                    "raster": {
                        "source_width": src_w,
                        "source_height": src_h,
                        "render_width": int(arr.shape[1]),
                        "render_height": int(arr.shape[0]),
                    },
                    "stats": {
                        "min_people_per_pixel": float(np.min(valid_values)),
                        "max_people_per_pixel": float(np.max(valid_values)),
                        "mean_people_per_pixel": float(np.mean(valid_values)),
                    },
                }
            )
            print(f"Wrote {out_png}")
        finally:
            ds = None

    territories.sort(key=lambda item: str(item.get("name", "")))
    metadata = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_dir": str(input_dir),
            "unit": "people_per_pixel",
            "palette_hex": list(DEFAULT_PALETTE_HEX),
            "normalization": "sqrt(value / global_scale_max)",
            "scale": {
                "min_people_per_pixel": 0.0,
                "max_people_per_pixel": float(scale_max),
            },
            "resampled_max_dimension": int(args.max_dimension),
        },
        "territories": territories,
    }

    out_json = out_dir / str(args.json_name)
    out_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote metadata {out_json}")


if __name__ == "__main__":
    main()
