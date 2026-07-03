#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

try:
    import cartopy.crs as ccrs
except Exception:  # pragma: no cover - optional at import time for CLI --help
    ccrs = None  # type: ignore[assignment]

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
except Exception:  # pragma: no cover - optional at import time for CLI --help
    matplotlib = None  # type: ignore[assignment]
    plt = None  # type: ignore[assignment]
    FuncFormatter = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

try:
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pq = None  # type: ignore[assignment]


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.hazard_comparison_registry import (  # noqa: E402
    DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH,
    load_hazard_comparison_registry,
)
from build_basin_wind_leaflet_overlays import (  # noqa: E402
    _build_value_grid,
    _extract_bounds_and_grid,
    _fill_nan_nearest_with_mask,
    _metric_max_key,
    _metric_min_key,
    _metric_value_key,
)
from build_basin_wind_maps import (  # noqa: E402
    BASIN_DEFAULT_ID,
    BASIN_LABEL,
    _aggregate_dataset,
    _bbox_from_payload,
    _iter_input_files,
    _normalize_wind_unit,
)


DEFAULT_CATALOG_ROOT = REPO_ROOT / "outputs" / "hazard-comparison-inputs" / "catalogs"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "hazard-comparison-visual-pack"
DEFAULT_STORM_DIR = Path("/home/ubuntu/uploads/STORM/STORM_ds")
DEFAULT_STORM_CMCC_DIR = Path("/home/ubuntu/uploads/STORM/STORM_CMCC_ds")

BASIN_ORDER = ("na", "si", "sp")
PROVIDER_ORDER = ("storm", "storm_cmcc")
METRIC_ORDER = ("mean", "rp50", "rp100", "event_max")
TERRITORY_ORDER = (
    "guadeloupe",
    "martinique",
    "saint_barthelemy",
    "saint_martin",
    "saint_pierre_et_miquelon",
    "guyane",
    "la_reunion",
    "mayotte",
    "nouvelle_caledonie",
)
TERRITORY_DISPLAY_LABELS = {
    "guadeloupe": "Guadeloupe",
    "martinique": "Martinique",
    "saint_barthelemy": "Saint-Barthélemy",
    "saint_martin": "Saint-Martin",
    "saint_pierre_et_miquelon": "Saint-Pierre-et-Miquelon",
    "guyane": "Guyane",
    "la_reunion": "La Réunion",
    "mayotte": "Mayotte",
    "nouvelle_caledonie": "Nouvelle-Calédonie",
}
METRIC_LABELS = {
    "mean": "Vents moyens",
    "rp50": "Temps de retour 50 ans",
    "rp100": "Temps de retour 100 ans",
    "event_max": "Événement le plus fort",
}
PROVIDER_LABELS = {
    "storm": "STORM",
    "storm_cmcc": "STORM_CMCC",
}
PROVIDER_COLORS = {
    "storm": "#0f766e",
    "storm_cmcc": "#c2410c",
}
BASEMAP_ALPHA = 0.42
INTENSITY_OVERLAY_ALPHA = 0.96
GLOBAL_WIND_SCALE_MIN_MPS = 3.30
GLOBAL_WIND_SCALE_MAX_MPS = 98.5
KMH_PER_MPS = 3.6


@dataclass(frozen=True)
class TerritorySpec:
    territory_id: str
    label: str
    basin_code: str
    bbox: dict[str, float]


@dataclass(frozen=True)
class BasinDisplaySpec:
    south: float
    north: float
    west: float
    east: float
    n_lat: int
    n_lon: int
    wrapped_dateline: bool
    display_cells_by_provider: dict[str, list[dict[str, Any]]]


def _kmh_from_mps(value_mps: float) -> float:
    return float(value_mps) * KMH_PER_MPS


def _format_speed_kmh(value_mps: float) -> str:
    return f"{_kmh_from_mps(value_mps):.1f}".rstrip("0").rstrip(".")


def _resolve_global_basin_map_scale() -> tuple[float, float]:
    return (float(GLOBAL_WIND_SCALE_MIN_MPS), float(GLOBAL_WIND_SCALE_MAX_MPS))


def _build_basin_colorbar_ticks(vmin_mps: float, vmax_mps: float, tick_count: int = 6) -> list[float]:
    if math.isclose(vmin_mps, vmax_mps):
        return [float(vmin_mps)]
    return np.linspace(vmin_mps, vmax_mps, tick_count, dtype=float).tolist()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_runtime_deps() -> None:
    missing: list[str] = []
    if matplotlib is None or plt is None:
        missing.append("matplotlib")
    if np is None:
        missing.append("numpy")
    if pd is None:
        missing.append("pandas")
    if pq is None:
        missing.append("pyarrow")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_hazard_comparison_visual_pack.py: "
            + ", ".join(sorted(set(missing)))
            + ". Run with /home/ubuntu/sib-work/backend/.venv/bin/python."
        )


def _latest_existing_basin_json(basin_code: str) -> Path | None:
    pattern = f"outputs/{basin_code}_wind_maps_*/Hazard_maps/{basin_code}-wind-maps-mean-rp50-rp100-eventmax.json"
    matches = sorted(REPO_ROOT.glob(pattern))
    if not matches:
        return None
    return matches[-1]


def _storm_patterns_from_registry(registry_payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    shared = registry_payload.get("shared_sources") if isinstance(registry_payload.get("shared_sources"), dict) else {}
    raw_catalogs = shared.get("raw_track_catalogs") if isinstance(shared.get("raw_track_catalogs"), dict) else {}
    patterns_by_basin = raw_catalogs.get("patterns_by_basin")
    if not isinstance(patterns_by_basin, dict):
        raise ValueError("Registry is missing shared_sources.raw_track_catalogs.patterns_by_basin")

    patterns: dict[str, dict[str, str]] = {}
    for basin_tag in ("NA", "SI", "SP"):
        basin_patterns = patterns_by_basin.get(basin_tag)
        if not isinstance(basin_patterns, dict):
            raise ValueError(f"Registry is missing raw patterns for basin {basin_tag}")
        patterns[basin_tag.lower()] = {
            "storm": str(basin_patterns.get("storm") or "").strip(),
            "storm_cmcc": str(basin_patterns.get("storm_cmcc") or "").strip(),
        }
    return patterns


def _resolve_ordered_territory_specs(registry_payload: dict[str, Any]) -> list[TerritorySpec]:
    territories = registry_payload.get("territories")
    if not isinstance(territories, dict):
        raise ValueError("Registry must contain a territories object")

    specs: list[TerritorySpec] = []
    for territory_id in TERRITORY_ORDER:
        entry = territories.get(territory_id)
        if not isinstance(entry, dict):
            raise ValueError(f"Missing territory {territory_id} in registry")
        if not bool(entry.get("include_in_comparison")):
            raise ValueError(f"Territory {territory_id} is not enabled for comparison")
        basin_code = str(entry.get("storm_basin_code") or "").strip().lower()
        if basin_code not in BASIN_ORDER:
            raise ValueError(f"Unsupported basin code for {territory_id}: {basin_code!r}")
        raw_bbox = entry.get("comparison_bbox_hint")
        if not isinstance(raw_bbox, dict):
            raise ValueError(f"Territory {territory_id} is missing comparison_bbox_hint")
        bbox = {
            "lon_min": float(raw_bbox.get("lon_min")),
            "lat_min": float(raw_bbox.get("lat_min")),
            "lon_max": float(raw_bbox.get("lon_max")),
            "lat_max": float(raw_bbox.get("lat_max")),
        }
        specs.append(
            TerritorySpec(
                territory_id=territory_id,
                label=TERRITORY_DISPLAY_LABELS.get(territory_id, str(entry.get("label") or territory_id)),
                basin_code=basin_code,
                bbox=bbox,
            )
        )
    return specs


def _resolve_basin_source_json(
    *,
    basin_code: str,
    registry_payload: dict[str, Any],
    storm_dir: Path,
    storm_cmcc_dir: Path,
    output_root: Path,
    cell_deg: float,
    wind_unit_in: str,
) -> tuple[Path, str]:
    existing = _latest_existing_basin_json(basin_code)
    if existing is not None:
        return existing, "reused_existing"

    patterns_by_basin = _storm_patterns_from_registry(registry_payload)
    basin_patterns = patterns_by_basin[basin_code]
    storm_files = _iter_input_files(storm_dir, basin_patterns["storm"])
    cmcc_files = _iter_input_files(storm_cmcc_dir, basin_patterns["storm_cmcc"])

    basin_id = int(BASIN_DEFAULT_ID[basin_code])
    normalized_unit = _normalize_wind_unit(wind_unit_in)
    storm_payload = _aggregate_dataset(
        storm_files,
        basin_id=basin_id,
        wind_unit_in=normalized_unit,
        cell_deg=float(cell_deg),
    )
    cmcc_payload = _aggregate_dataset(
        cmcc_files,
        basin_id=basin_id,
        wind_unit_in=normalized_unit,
        cell_deg=float(cell_deg),
    )
    payload = {
        "meta": {
            "generated_at": _utc_now(),
            "region": basin_code,
            "region_label": BASIN_LABEL.get(basin_code, basin_code.upper()),
            "bbox": _bbox_from_payload(storm_payload.get("cells", []), cmcc_payload.get("cells", []), float(cell_deg)),
            "grid_cell_deg": float(cell_deg),
            "basin_id": basin_id,
            "wind_unit_in": normalized_unit,
            "wind_unit_out": "m/s",
            "scenarios": list(METRIC_ORDER),
            "dataset_links": {
                "storm": [str(path) for path in storm_files],
                "storm_cmcc": [str(path) for path in cmcc_files],
            },
        },
        "storm": storm_payload,
        "storm_cmcc": cmcc_payload,
    }

    source_dir = output_root / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    output_path = source_dir / f"{basin_code}-wind-maps-mean-rp50-rp100-eventmax.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, "rebuilt"


def _render_basin_panel(
    ax: Any,
    *,
    grid: Any,
    render_mask: Any,
    bounds: tuple[float, float, float, float],
    vmin: float,
    vmax: float,
    title: str,
    use_basemap: bool,
    wrapped_dateline: bool,
) -> Any:
    south, north, west, east = bounds
    values = np.ma.masked_where(~render_mask, np.asarray(grid, dtype=np.float32))
    cmap_obj = matplotlib.colormaps.get_cmap("turbo").copy()
    cmap_obj.set_bad((1.0, 1.0, 1.0, 0.0))

    if use_basemap and ccrs is not None:
        ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
        basemap = ax.stock_img()
        if basemap is not None:
            basemap.set_alpha(BASEMAP_ALPHA)
        image = ax.imshow(
            values,
            extent=[west, east, south, north],
            origin="lower",
            interpolation="nearest",
            cmap=cmap_obj,
            vmin=vmin,
            vmax=vmax,
            alpha=INTENSITY_OVERLAY_ALPHA,
            transform=ccrs.PlateCarree(),
            zorder=3,
        )
        ax.coastlines(resolution="110m", linewidth=0.35, color="#334155", alpha=0.7, zorder=4)
        gridlines = ax.gridlines(draw_labels=True, linewidth=0.25, color="white", alpha=0.4, linestyle="-")
        gridlines.top_labels = False
        gridlines.right_labels = False
    else:
        image = ax.imshow(
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
        if wrapped_dateline and FuncFormatter is not None:
            ax.xaxis.set_major_formatter(
                FuncFormatter(lambda value, _pos: f"{(value - 360.0) if value > 180.0 else value:.0f}")
            )

    ax.set_title(title, fontsize=12, fontweight="bold")
    return image


def _resolve_basin_display_spec(payload: dict[str, Any], cell_deg: float) -> BasinDisplaySpec:
    south, north, west, east, n_lat, n_lon = _extract_bounds_and_grid(payload, cell_deg)
    direct_span = float(east - west)

    raw_cells_by_provider: dict[str, list[dict[str, Any]]] = {}
    shifted_lon_values: list[float] = []
    for provider in PROVIDER_ORDER:
        raw_cells: list[dict[str, Any]] = []
        for cell in payload.get(provider, {}).get("cells", []):
            raw_cell = dict(cell)
            raw_cells.append(raw_cell)
            lon = float(raw_cell.get("lon", 0.0))
            shifted_lon_values.append(lon + 360.0 if lon < 0.0 else lon)
        raw_cells_by_provider[provider] = raw_cells

    shifted_span = 0.0
    wrapped_dateline = False
    display_west = float(west)
    display_east = float(east)
    if shifted_lon_values:
        shifted_span = float(max(shifted_lon_values) - min(shifted_lon_values) + float(cell_deg))
        # Only treat a basin as dateline-wrapped when the original extent is genuinely
        # near-global and the shifted 0..360 representation meaningfully reduces it.
        wrap_gain = direct_span - shifted_span
        if direct_span > 180.0 and wrap_gain > max(float(cell_deg) * 2.0, 0.5):
            wrapped_dateline = True
            display_west = float(min(shifted_lon_values) - (cell_deg / 2.0))
            display_east = float(max(shifted_lon_values) + (cell_deg / 2.0))
            n_lon = int(round((display_east - display_west) / float(cell_deg)))

    display_cells_by_provider: dict[str, list[dict[str, Any]]] = {}
    for provider, raw_cells in raw_cells_by_provider.items():
        display_cells: list[dict[str, Any]] = []
        for raw_cell in raw_cells:
            display_cell = dict(raw_cell)
            lon = float(display_cell.get("lon", 0.0))
            if wrapped_dateline and lon < 0.0:
                lon = lon + 360.0
            display_cell["lon"] = lon
            display_cells.append(display_cell)
        display_cells_by_provider[provider] = display_cells

    return BasinDisplaySpec(
        south=float(south),
        north=float(north),
        west=display_west,
        east=display_east,
        n_lat=int(n_lat),
        n_lon=int(n_lon),
        wrapped_dateline=wrapped_dateline,
        display_cells_by_provider=display_cells_by_provider,
    )


def _render_basin_maps(
    basin_payloads: dict[str, dict[str, Any]],
    *,
    output_dir: Path,
    fill_max_distance_cells: float,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    use_basemap = ccrs is not None

    for basin_code in BASIN_ORDER:
        payload = basin_payloads[basin_code]
        cell_deg = float(payload.get("meta", {}).get("grid_cell_deg", 0.05))
        display_spec = _resolve_basin_display_spec(payload, cell_deg)
        bounds = (display_spec.south, display_spec.north, display_spec.west, display_spec.east)
        scale_vmin_mps, scale_vmax_mps = _resolve_global_basin_map_scale()
        fig_kwargs = {"figsize": (16, 7)}
        basin_uses_basemap = use_basemap
        basin_projection = (
            ccrs.PlateCarree(central_longitude=180.0)
            if basin_uses_basemap and display_spec.wrapped_dateline and ccrs is not None
            else (ccrs.PlateCarree() if basin_uses_basemap and ccrs is not None else None)
        )

        for metric in METRIC_ORDER:
            if basin_uses_basemap:
                fig, axes = plt.subplots(
                    1,
                    2,
                    subplot_kw={"projection": basin_projection},
                    **fig_kwargs,
                )
            else:
                fig, axes = plt.subplots(1, 2, **fig_kwargs)

            fig.subplots_adjust(left=0.04, right=0.9, bottom=0.08, top=0.9, wspace=0.08)
            image = None
            for axis_index, provider in enumerate(PROVIDER_ORDER):
                cells = display_spec.display_cells_by_provider[provider]
                value_key = _metric_value_key(metric)
                grid = _build_value_grid(
                    cells,
                    value_key,
                    south=display_spec.south,
                    west=display_spec.west,
                    cell_deg=cell_deg,
                    n_lat=display_spec.n_lat,
                    n_lon=display_spec.n_lon,
                )
                grid, render_mask = _fill_nan_nearest_with_mask(
                    grid,
                    max_distance_cells=float(fill_max_distance_cells),
                )
                image = _render_basin_panel(
                    axes[axis_index],
                    grid=grid,
                    render_mask=render_mask,
                    bounds=bounds,
                    vmin=scale_vmin_mps,
                    vmax=scale_vmax_mps,
                    title=PROVIDER_LABELS[provider],
                    use_basemap=basin_uses_basemap,
                    wrapped_dateline=display_spec.wrapped_dateline,
                )

            figure_title = f"Bassin {basin_code.upper()} - {METRIC_LABELS[metric]}"
            fig.suptitle(figure_title, fontsize=14, fontweight="bold")
            if image is not None:
                ticks = _build_basin_colorbar_ticks(scale_vmin_mps, scale_vmax_mps)
                cax = fig.add_axes([0.92, 0.17, 0.015, 0.62])
                colorbar = fig.colorbar(image, cax=cax, orientation="vertical", ticks=ticks)
                colorbar.set_label("Vitesse du vent (km/h)")
                if FuncFormatter is not None:
                    colorbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_speed_kmh(value)))
                colorbar.ax.tick_params(labelsize=9)
            output_path = output_dir / f"{basin_code}_{metric}_storm_vs_storm_cmcc.png"
            fig.savefig(output_path, dpi=180, bbox_inches="tight")
            plt.close(fig)
            written.append(str(output_path))
    return written


def _normalize_longitudes(values: Any) -> Any:
    arr = np.asarray(values, dtype=float)
    return np.where(arr > 180.0, arr - 360.0, arr)


def _accumulate_territory_statistics_from_batches(
    parquet_path: Path,
    territory_specs: list[TerritorySpec],
) -> dict[str, dict[str, Any]]:
    annual_maxima = {spec.territory_id: {} for spec in territory_specs}
    track_ids = {spec.territory_id: set() for spec in territory_specs}
    parquet_file = pq.ParquetFile(parquet_path)
    for batch in parquet_file.iter_batches(columns=["Year", "lat", "lon", "wind_max", "track_id"], batch_size=250_000):
        chunk = batch.to_pandas()
        if chunk.empty:
            continue
        chunk["lon"] = _normalize_longitudes(chunk["lon"].to_numpy())
        chunk["lat"] = pd.to_numeric(chunk["lat"], errors="coerce")
        chunk["wind_max"] = pd.to_numeric(chunk["wind_max"], errors="coerce")
        chunk["Year"] = pd.to_numeric(chunk["Year"], errors="coerce")
        chunk = chunk[np.isfinite(chunk["lat"]) & np.isfinite(chunk["lon"]) & np.isfinite(chunk["wind_max"]) & np.isfinite(chunk["Year"])]
        if chunk.empty:
            continue

        for spec in territory_specs:
            bbox = spec.bbox
            territory_chunk = chunk[
                (chunk["lat"] >= float(bbox["lat_min"]))
                & (chunk["lat"] <= float(bbox["lat_max"]))
                & (chunk["lon"] >= float(bbox["lon_min"]))
                & (chunk["lon"] <= float(bbox["lon_max"]))
            ]
            if territory_chunk.empty:
                continue
            grouped = territory_chunk.groupby("Year", as_index=False)["wind_max"].max()
            maxima = annual_maxima[spec.territory_id]
            for row in grouped.itertuples(index=False):
                year = int(float(row.Year))
                value = float(row.wind_max)
                previous = maxima.get(year)
                if previous is None or value > previous:
                    maxima[year] = value
            track_ids[spec.territory_id].update(
                str(value).strip()
                for value in territory_chunk["track_id"].dropna().tolist()
                if str(value).strip()
            )
    return {
        territory_id: {
            "annual_maxima_by_year": annual_maxima[territory_id],
            "track_count": int(len(track_ids[territory_id])),
        }
        for territory_id in annual_maxima
    }


def _resolve_catalog_path(catalog_root: Path, basin_code: str, provider: str) -> Path:
    return catalog_root / basin_code / f"{provider}_tracks.parquet"


def _build_territory_annual_maxima(
    *,
    territory_specs: list[TerritorySpec],
    catalog_root: Path,
) -> tuple[dict[str, dict[str, list[float]]], dict[str, dict[str, dict[str, int]]]]:
    by_territory = {
        spec.territory_id: {provider: [] for provider in PROVIDER_ORDER}
        for spec in territory_specs
    }
    territory_counts = {
        spec.territory_id: {
            provider: {"year_count": 0, "track_count": 0}
            for provider in PROVIDER_ORDER
        }
        for spec in territory_specs
    }
    by_basin: dict[str, list[TerritorySpec]] = {basin_code: [] for basin_code in BASIN_ORDER}
    for spec in territory_specs:
        by_basin[spec.basin_code].append(spec)

    for basin_code, basin_specs in by_basin.items():
        if not basin_specs:
            continue
        for provider in PROVIDER_ORDER:
            parquet_path = _resolve_catalog_path(catalog_root, basin_code, provider)
            territory_statistics = _accumulate_territory_statistics_from_batches(parquet_path, basin_specs)
            for territory_id, territory_payload in territory_statistics.items():
                maxima_by_year = territory_payload["annual_maxima_by_year"]
                values = [float(value) for _, value in sorted(maxima_by_year.items())]
                by_territory[territory_id][provider] = values
                territory_counts[territory_id][provider] = {
                    "year_count": int(len(values)),
                    "track_count": int(territory_payload["track_count"]),
                }
    return by_territory, territory_counts


def _territory_subplot_title(
    label: str,
    provider_counts: dict[str, dict[str, int]],
) -> str:
    storm_years = int(provider_counts["storm"]["year_count"])
    storm_cmcc_years = int(provider_counts["storm_cmcc"]["year_count"])
    storm_tracks = int(provider_counts["storm"]["track_count"])
    storm_cmcc_tracks = int(provider_counts["storm_cmcc"]["track_count"])
    return (
        f"{label} "
        f"({storm_years}/{storm_cmcc_years} années & "
        f"{storm_tracks}/{storm_cmcc_tracks} tracks)"
    )


def _compute_histogram_payloads(
    annual_maxima: dict[str, dict[str, list[float]]],
    *,
    bins_count: int,
    bin_width_kmh: float | None,
) -> dict[str, Any]:
    all_values_kmh: list[float] = []
    for provider_map in annual_maxima.values():
        for values in provider_map.values():
            all_values_kmh.extend(float(value) * 3.6 for value in values)
    if not all_values_kmh:
        raise ValueError("No annual maxima were resolved from the comparison catalogs")

    minimum = min(all_values_kmh)
    maximum = max(all_values_kmh)
    if not math.isfinite(minimum) or not math.isfinite(maximum):
        raise ValueError("Annual maxima contain non-finite values")

    if math.isclose(minimum, maximum):
        minimum -= 1.8
        maximum += 1.8

    if bin_width_kmh is not None:
        if bin_width_kmh <= 0.0:
            raise ValueError("--bin-width-kmh must be strictly positive")
        lower = math.floor(minimum / bin_width_kmh) * bin_width_kmh
        upper = math.ceil(maximum / bin_width_kmh) * bin_width_kmh
        if math.isclose(lower, upper):
            upper = lower + bin_width_kmh
        edges = np.arange(lower, upper + (bin_width_kmh * 0.5), bin_width_kmh, dtype=float)
        if edges.size < 2:
            edges = np.array([lower, upper], dtype=float)
    else:
        resolved_bins_count = max(int(bins_count), 1)
        edges = np.linspace(minimum, maximum, resolved_bins_count + 1, dtype=float)

    centers = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    territory_payloads: dict[str, dict[str, list[float]]] = {}
    ymax = 0.0
    for territory_id, provider_map in annual_maxima.items():
        territory_payloads[territory_id] = {}
        for provider, values_mps in provider_map.items():
            values_kmh = np.asarray([float(value) * 3.6 for value in values_mps], dtype=float)
            if values_kmh.size == 0:
                percentages = np.zeros(len(centers), dtype=float)
            else:
                counts, _ = np.histogram(values_kmh, bins=edges)
                percentages = (counts.astype(float) / float(values_kmh.size)) * 100.0
            ymax = max(ymax, float(np.max(percentages)) if percentages.size else 0.0)
            territory_payloads[territory_id][provider] = percentages.tolist()

    x_limits = (float(edges[0]), float(edges[-1]))
    y_limit = max(1.0, ymax * 1.08)
    return {
        "edges": edges.tolist(),
        "centers": centers,
        "x_limits": x_limits,
        "y_limit": y_limit,
        "territories": territory_payloads,
    }


def _build_territory_supergraph_figure(
    territory_specs: list[TerritorySpec],
    histogram_payload: dict[str, Any],
    territory_counts: dict[str, dict[str, dict[str, int]]],
) -> Any:
    centers = [float(value) for value in histogram_payload["centers"]]
    x_limits = tuple(float(value) for value in histogram_payload["x_limits"])
    y_limit = float(histogram_payload["y_limit"])
    territory_payloads = histogram_payload["territories"]

    fig, axes = plt.subplots(3, 3, figsize=(17, 13), sharex=True, sharey=True)
    axes_list = list(np.asarray(axes).reshape(-1))
    for index, spec in enumerate(territory_specs):
        ax = axes_list[index]
        for provider in PROVIDER_ORDER:
            ax.plot(
                centers,
                territory_payloads[spec.territory_id][provider],
                color=PROVIDER_COLORS[provider],
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label=PROVIDER_LABELS[provider],
            )
        ax.set_title(
            _territory_subplot_title(spec.label, territory_counts[spec.territory_id]),
            fontsize=9.25,
            fontweight="bold",
        )
        ax.set_xlim(*x_limits)
        ax.set_ylim(0.0, y_limit)
        ax.grid(True, axis="y", alpha=0.25)
        if index % 3 == 0:
            ax.set_ylabel("% d'événements")
        if index >= 6:
            ax.set_xlabel("Vitesse de vent max (km/h)")
        ax.tick_params(axis="x", rotation=20)

    handles, labels = axes_list[0].get_legend_handles_labels()
    fig.subplots_adjust(top=0.82, hspace=0.32, wspace=0.16)
    fig.suptitle(
        "Vent max par année simulée - distribution des maxima annuels",
        fontsize=15,
        fontweight="bold",
        y=0.975,
    )
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.93))
    return fig


def _render_territory_supergraph(
    territory_specs: list[TerritorySpec],
    annual_maxima: dict[str, dict[str, list[float]]],
    territory_counts: dict[str, dict[str, dict[str, int]]],
    *,
    output_path: Path,
    bins_count: int,
    bin_width_kmh: float | None,
) -> dict[str, Any]:
    histogram_payload = _compute_histogram_payloads(
        annual_maxima,
        bins_count=bins_count,
        bin_width_kmh=bin_width_kmh,
    )
    fig = _build_territory_supergraph_figure(territory_specs, histogram_payload, territory_counts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return histogram_payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a one-shot hazard comparison visual pack (basin maps + territory supergraph).")
    parser.add_argument("--registry-path", default=str(DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH))
    parser.add_argument("--catalog-root", default=str(DEFAULT_CATALOG_ROOT))
    parser.add_argument("--storm-dir", default=str(DEFAULT_STORM_DIR))
    parser.add_argument("--storm-cmcc-dir", default=str(DEFAULT_STORM_CMCC_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--cell-deg", type=float, default=0.05, help="Grid cell size for rebuilt basin JSON sources.")
    parser.add_argument("--wind-unit-in", default="m/s", help="Raw STORM wind unit (m/s, kn, km/h).")
    parser.add_argument("--bins-count", type=int, default=24, help="Histogram bin count when --bin-width-kmh is omitted.")
    parser.add_argument("--bin-width-kmh", type=float, default=None, help="Optional shared histogram bin width in km/h.")
    parser.add_argument("--fill-max-distance-cells", type=float, default=1.5, help="Nearest-fill distance for basin map rendering.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _require_runtime_deps()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    registry = load_hazard_comparison_registry(Path(args.registry_path))
    territory_specs = _resolve_ordered_territory_specs(registry.payload)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.out_dir)
    if output_root == DEFAULT_OUTPUT_ROOT:
        output_root = output_root / timestamp
    maps_dir = output_root / "maps"
    charts_dir = output_root / "charts"
    maps_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    basin_payloads: dict[str, dict[str, Any]] = {}
    basin_sources: dict[str, dict[str, str]] = {}
    for basin_code in BASIN_ORDER:
        source_path, source_mode = _resolve_basin_source_json(
            basin_code=basin_code,
            registry_payload=registry.payload,
            storm_dir=Path(args.storm_dir),
            storm_cmcc_dir=Path(args.storm_cmcc_dir),
            output_root=output_root,
            cell_deg=float(args.cell_deg),
            wind_unit_in=str(args.wind_unit_in),
        )
        basin_sources[basin_code] = {"json_path": str(source_path), "mode": source_mode}
        basin_payloads[basin_code] = json.loads(source_path.read_text(encoding="utf-8"))

    map_paths = _render_basin_maps(
        basin_payloads,
        output_dir=maps_dir,
        fill_max_distance_cells=float(args.fill_max_distance_cells),
    )

    annual_maxima, territory_counts = _build_territory_annual_maxima(
        territory_specs=territory_specs,
        catalog_root=Path(args.catalog_root),
    )
    supergraph_path = charts_dir / "territories_vent_max_par_annee_supergraph.png"
    histogram_payload = _render_territory_supergraph(
        territory_specs,
        annual_maxima,
        territory_counts,
        output_path=supergraph_path,
        bins_count=int(args.bins_count),
        bin_width_kmh=float(args.bin_width_kmh) if args.bin_width_kmh is not None else None,
    )
    map_scale_min_mps, map_scale_max_mps = _resolve_global_basin_map_scale()

    manifest = {
        "generated_at": _utc_now(),
        "registry_path": str(Path(args.registry_path)),
        "catalog_root": str(Path(args.catalog_root)),
        "storm_dir": str(Path(args.storm_dir)),
        "storm_cmcc_dir": str(Path(args.storm_cmcc_dir)),
        "output_root": str(output_root),
        "map_renderer": "cartopy_stock_img" if ccrs is not None else "plain_lon_lat_grid",
        "parameters": {
            "cell_deg": float(args.cell_deg),
            "wind_unit_in": str(args.wind_unit_in),
            "bins_count": int(args.bins_count),
            "bin_width_kmh": float(args.bin_width_kmh) if args.bin_width_kmh is not None else None,
            "fill_max_distance_cells": float(args.fill_max_distance_cells),
            "map_scale_mps": [map_scale_min_mps, map_scale_max_mps],
            "map_scale_kmh": [round(_kmh_from_mps(map_scale_min_mps), 1), round(_kmh_from_mps(map_scale_max_mps), 1)],
        },
        "basins": {
            basin_code: {
                "label": BASIN_LABEL.get(basin_code, basin_code.upper()),
                "source_json": basin_sources[basin_code]["json_path"],
                "source_mode": basin_sources[basin_code]["mode"],
                "map_outputs": {
                    metric: str(maps_dir / f"{basin_code}_{metric}_storm_vs_storm_cmcc.png")
                    for metric in METRIC_ORDER
                },
            }
            for basin_code in BASIN_ORDER
        },
        "territories": {
            spec.territory_id: {
                "label": spec.label,
                "basin_code": spec.basin_code,
                "bbox": spec.bbox,
                "annual_maxima_count": {
                    provider: int(len(annual_maxima[spec.territory_id][provider]))
                    for provider in PROVIDER_ORDER
                },
                "track_count": {
                    provider: int(territory_counts[spec.territory_id][provider]["track_count"])
                    for provider in PROVIDER_ORDER
                },
            }
            for spec in territory_specs
        },
        "histogram": {
            "x_limits_kmh": [float(value) for value in histogram_payload["x_limits"]],
            "y_limit_percent": float(histogram_payload["y_limit"]),
            "bin_edges_kmh": [float(value) for value in histogram_payload["edges"]],
            "supergraph_path": str(supergraph_path),
        },
        "outputs": {
            "maps": map_paths,
            "charts": [str(supergraph_path)],
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote 12 basin maps to {maps_dir}")
    print(f"Wrote territory supergraph to {supergraph_path}")
    print(f"Wrote manifest to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
