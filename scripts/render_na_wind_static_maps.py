#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import cartopy.crs as ccrs
except Exception:  # pragma: no cover - optional at import time for CLI --help
    ccrs = None  # type: ignore[assignment]

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
except Exception:  # pragma: no cover - optional at import time for CLI --help
    matplotlib = None  # type: ignore[assignment]
    plt = None  # type: ignore[assignment]
    PdfPages = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

from build_na_wind_leaflet_overlays import (
    _build_value_grid,
    _extract_bounds_and_grid,
    _fill_nan_nearest_with_mask,
    _metric_max_key,
    _metric_min_key,
    _metric_value_key,
)


HAZARDS: tuple[tuple[str, str], ...] = (
    ("storm", "STORM"),
    ("storm_cmcc", "STORM_CMCC"),
)
METRICS: tuple[tuple[str, str], ...] = (
    ("mean", "Vents moyens"),
    ("rp50", "Temps de retour 50 ans"),
    ("rp100", "Temps de retour 100 ans"),
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _require_render_deps() -> None:
    missing: list[str] = []
    if ccrs is None:
        missing.append("cartopy")
    if matplotlib is None or plt is None or PdfPages is None:
        missing.append("matplotlib")
    if np is None:
        missing.append("numpy")
    if missing:
        raise RuntimeError(
            "Missing dependencies for render_na_wind_static_maps.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install required packages and retry."
        )


def _metric_ranges(payload: dict, hazards: tuple[str, ...]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for metric, _ in METRICS:
        min_key = _metric_min_key(metric)
        max_key = _metric_max_key(metric)
        mn = min(float(payload[h][min_key]) for h in hazards)
        mx = max(float(payload[h][max_key]) for h in hazards)
        out[metric] = {"min_mps": float(mn), "max_mps": float(mx)}
    return out


def _render_plain_figure(
    *,
    grid: np.ndarray,
    west: float,
    east: float,
    south: float,
    north: float,
    vmin: float,
    vmax: float,
    cmap: str,
    title: str,
    render_mask: np.ndarray,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(14, 8.685), constrained_layout=True)
    ax.set_facecolor("white")
    cmap_obj = matplotlib.colormaps.get_cmap(cmap).copy()
    cmap_obj.set_bad((1.0, 1.0, 1.0, 0.0))
    values = np.ma.masked_where(~render_mask, np.asarray(grid, dtype=np.float32))
    im = ax.imshow(
        values,
        extent=[west, east, south, north],
        origin="lower",
        interpolation="nearest",
        cmap=cmap_obj,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#d9d9d9", linewidth=0.35, alpha=0.6)
    ax.set_title(title, fontsize=13, weight="bold")
    cbar = fig.colorbar(im, ax=ax, orientation="vertical", fraction=0.034, pad=0.02)
    cbar.set_label("Vitesse du vent (m/s)")
    return fig


def _render_basemap_figure(
    *,
    grid: np.ndarray,
    west: float,
    east: float,
    south: float,
    north: float,
    vmin: float,
    vmax: float,
    cmap: str,
    title: str,
    overlay_alpha: float,
    render_mask: np.ndarray,
) -> plt.Figure:
    fig = plt.figure(figsize=(14, 8.685), constrained_layout=True)
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
    # Offline-safe cartopy background raster.
    ax.stock_img()
    cmap_obj = matplotlib.colormaps.get_cmap(cmap).copy()
    cmap_obj.set_bad((1.0, 1.0, 1.0, 0.0))
    values = np.ma.masked_where(~render_mask, np.asarray(grid, dtype=np.float32))
    im = ax.imshow(
        values,
        extent=[west, east, south, north],
        origin="lower",
        interpolation="nearest",
        cmap=cmap_obj,
        vmin=vmin,
        vmax=vmax,
        alpha=float(overlay_alpha),
        transform=ccrs.PlateCarree(),
    )
    gl = ax.gridlines(draw_labels=True, linewidth=0.25, color="white", alpha=0.35, linestyle="-")
    gl.top_labels = False
    gl.right_labels = False
    ax.set_title(title, fontsize=13, weight="bold")
    cbar = fig.colorbar(im, ax=ax, orientation="vertical", fraction=0.034, pad=0.02)
    cbar.set_label("Vitesse du vent (m/s)")
    return fig


def main() -> None:
    default_in = REPO_ROOT / "outputs" / "na_wind_maps_20260310" / "Hazard_maps" / "na-wind-maps-rp50-rp100.json"
    default_out = REPO_ROOT / "outputs" / "na_wind_maps_20260310" / "Hazard_maps"
    default_basemap_out = REPO_ROOT / "outputs" / "na_wind_maps_20260310" / "basemap_alpha50"
    parser = argparse.ArgumentParser(description="Render static NA wind maps from NA hazard JSON")
    parser.add_argument(
        "--input-json",
        default=str(default_in),
        help="Path to NA wind JSON (storm + storm_cmcc with mean/rp50/rp100)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(default_out),
        help="Output directory for plain (no basemap) maps",
    )
    parser.add_argument(
        "--basemap-out-dir",
        default=str(default_basemap_out),
        help="Output directory for basemap maps",
    )
    parser.add_argument("--cmap", default="turbo", help="Matplotlib colormap")
    parser.add_argument(
        "--fill-mode",
        choices=["nearest", "none"],
        default="nearest",
        help="Fill mode for empty grid cells before rendering",
    )
    parser.add_argument(
        "--fill-max-distance-cells",
        type=float,
        default=1.5,
        help="Max nearest-fill distance (in grid cells) for static rendering",
    )
    parser.add_argument("--basemap-alpha", type=float, default=0.5, help="Opacity of hazard layer on basemap")
    parser.add_argument("--dpi", type=int, default=200, help="PNG/PDF render DPI")
    args = parser.parse_args()
    _require_render_deps()

    input_json = Path(args.input_json)
    out_dir = Path(args.out_dir)
    basemap_out_dir = Path(args.basemap_out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    basemap_out_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(input_json.read_text(encoding="utf-8"))

    cell_deg = float(payload.get("meta", {}).get("grid_cell_deg", 0.05))
    if not np.isfinite(cell_deg) or cell_deg <= 0:
        raise ValueError("Invalid grid_cell_deg in payload meta")

    south, north, west, east, n_lat, n_lon = _extract_bounds_and_grid(payload, cell_deg)
    hazard_keys = tuple(h for h, _ in HAZARDS)
    ranges = _metric_ranges(payload, hazard_keys)
    alpha_pct = int(round(float(args.basemap_alpha) * 100.0))

    combined_plain_pdf = out_dir / "na_wind_maps_all_6.pdf"
    combined_basemap_pdf = basemap_out_dir / f"na_wind_maps_all_6_basemap_alpha{alpha_pct}.pdf"

    with PdfPages(combined_plain_pdf) as pdf_plain, PdfPages(combined_basemap_pdf) as pdf_basemap:
        for hazard_key, hazard_label in HAZARDS:
            cells = payload.get(hazard_key, {}).get("cells", [])
            if not isinstance(cells, list):
                raise ValueError(f"Invalid cells payload for hazard {hazard_key}")

            for metric_key, metric_label in METRICS:
                value_key = _metric_value_key(metric_key)
                grid = _build_value_grid(
                    cells,
                    value_key,
                    south=south,
                    west=west,
                    cell_deg=cell_deg,
                    n_lat=n_lat,
                    n_lon=n_lon,
                )
                render_mask = ~np.isnan(grid)
                if args.fill_mode == "nearest":
                    grid, render_mask = _fill_nan_nearest_with_mask(
                        grid,
                        max_distance_cells=float(args.fill_max_distance_cells),
                    )

                vmin = float(ranges[metric_key]["min_mps"])
                vmax = float(ranges[metric_key]["max_mps"])
                title = f"Bassin NA - {hazard_label} - {metric_label}"

                plain_png = out_dir / f"na_{hazard_key}_{metric_key}.png"
                plain_pdf = out_dir / f"na_{hazard_key}_{metric_key}.pdf"
                fig_plain = _render_plain_figure(
                    grid=grid,
                    west=west,
                    east=east,
                    south=south,
                    north=north,
                    vmin=vmin,
                    vmax=vmax,
                    cmap=args.cmap,
                    title=title,
                    render_mask=render_mask,
                )
                fig_plain.savefig(plain_png, dpi=int(args.dpi), bbox_inches="tight")
                fig_plain.savefig(plain_pdf, dpi=int(args.dpi), bbox_inches="tight")
                pdf_plain.savefig(fig_plain)
                plt.close(fig_plain)

                basemap_png = basemap_out_dir / f"na_{hazard_key}_{metric_key}_basemap_alpha{alpha_pct}.png"
                basemap_pdf = basemap_out_dir / f"na_{hazard_key}_{metric_key}_basemap_alpha{alpha_pct}.pdf"
                fig_basemap = _render_basemap_figure(
                    grid=grid,
                    west=west,
                    east=east,
                    south=south,
                    north=north,
                    vmin=vmin,
                    vmax=vmax,
                    cmap=args.cmap,
                    title=title,
                    overlay_alpha=float(args.basemap_alpha),
                    render_mask=render_mask,
                )
                fig_basemap.savefig(basemap_png, dpi=int(args.dpi), bbox_inches="tight")
                fig_basemap.savefig(basemap_pdf, dpi=int(args.dpi), bbox_inches="tight")
                pdf_basemap.savefig(fig_basemap)
                plt.close(fig_basemap)

    print(f"Wrote plain maps to {out_dir}")
    print(f"Wrote combined plain PDF {combined_plain_pdf}")
    print(f"Wrote basemap maps to {basemap_out_dir}")
    print(f"Wrote combined basemap PDF {combined_basemap_pdf}")


if __name__ == "__main__":
    main()
