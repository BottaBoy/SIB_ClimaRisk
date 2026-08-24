#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Patch


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "outputs" / "hydraulic_zoning"
OUTPUT_PATH = OUTPUT_DIR / "guadeloupe_hydraulic_vs_electric_zoning.png"
OUTPUT_PATH_WITH_EU = OUTPUT_DIR / "guadeloupe_hydraulic_aep_eu_vs_electric_zoning.png"
REFERENCE_MAP_PATH = REPO_ROOT / "outputs" / "Graphs" / "20260701_071828" / "maps" / "guadeloupe_aep_canalisations.png"
WATER_INFRA_PATH = REPO_ROOT / "web" / "data" / "guadeloupe-water-infra.geojson"
NETWORK_STATES_PATH = REPO_ROOT / "web" / "data" / "guadeloupe-network-states.geojson"
HYDRAULIC_ZONES_PATH = REPO_ROOT / "outputs" / "hydraulic_zoning" / "Zonage_V2" / "guadeloupe_hydraulic_zones_estimate.gpkg"
WEB_CRS = "EPSG:3857"
MAP_PAD_RATIO = 0.06


def _clean_label(value: object) -> str:
    text = str(value or "").strip().replace("_", " ")
    return " ".join(text.split())


def _load_reference_extent() -> tuple[float, float, float, float]:
    water = gpd.read_file(WATER_INFRA_PATH)
    aep_lines = water[water["infra_type"] == "aep_cana"].copy()
    if aep_lines.empty:
        raise RuntimeError(f"No AEP lines found in {WATER_INFRA_PATH}")
    if aep_lines.crs is None:
        aep_lines = aep_lines.set_crs(epsg=4326)
    aep_lines = aep_lines.to_crs(WEB_CRS)
    min_x, min_y, max_x, max_y = [float(value) for value in aep_lines.total_bounds]
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    return (
        min_x - (span_x * MAP_PAD_RATIO),
        min_y - (span_y * MAP_PAD_RATIO),
        max_x + (span_x * MAP_PAD_RATIO),
        max_y + (span_y * MAP_PAD_RATIO),
    )


def _prepare_hydraulic_zones(network_kind: str = "AEP") -> gpd.GeoDataFrame:
    zones = gpd.read_file(HYDRAULIC_ZONES_PATH, layer="hydraulic_zones")
    network_kind_upper = network_kind.upper()
    zones = zones[zones["network_kind"].astype(str).str.upper() == network_kind_upper].copy()
    if zones.empty:
        raise RuntimeError(f"No {network_kind_upper} hydraulic zones found in {HYDRAULIC_ZONES_PATH}")
    if zones.crs is None:
        raise RuntimeError("Hydraulic zones layer has no CRS")
    zones = zones.to_crs(WEB_CRS)
    zones["plot_color"] = zones["zone_color"].fillna("#94a3b8")
    return zones


def _prepare_electric_grid() -> gpd.GeoDataFrame:
    grid = gpd.read_file(NETWORK_STATES_PATH)
    grid = grid[grid["layer_key"].astype(str) == "elec_grid_0p1deg"].copy()
    if grid.empty:
        raise RuntimeError(f"No electric grid cells found in {NETWORK_STATES_PATH}")
    if grid.crs is None:
        grid = grid.set_crs(epsg=4326)
    return grid.to_crs(WEB_CRS)


def _apply_extent(ax: plt.Axes, extent: tuple[float, float, float, float]) -> None:
    min_x, min_y, max_x, max_y = extent
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_aspect("equal")
    ax.set_axis_off()


def _style_map_axis(ax: plt.Axes, title: str) -> None:
    ax.set_title(title, fontsize=17, fontweight="bold", color="#0f172a", pad=14)
    ax.set_facecolor("#f8fafc")


def _draw_hydraulic_zones(ax: plt.Axes, zones: gpd.GeoDataFrame, extent: tuple[float, float, float, float], title: str) -> None:
    _style_map_axis(ax, title)
    zones.plot(
        ax=ax,
        color=zones["plot_color"],
        edgecolor="#ffffff",
        linewidth=0.35,
        alpha=0.96,
        zorder=2,
    )
    _apply_extent(ax, extent)


def _draw_electric_grid(
    ax: plt.Axes,
    electric_grid: gpd.GeoDataFrame,
    hydraulic_footprint: gpd.GeoDataFrame,
    extent: tuple[float, float, float, float],
) -> None:
    _style_map_axis(ax, "Zonage electrique")
    hydraulic_footprint.plot(
        ax=ax,
        color="#e2e8f0",
        edgecolor="none",
        alpha=0.65,
        zorder=1,
    )
    electric_grid.plot(
        ax=ax,
        facecolor="#fde68a",
        edgecolor="#a16207",
        linewidth=1.6,
        alpha=0.34,
        zorder=2,
    )
    _apply_extent(ax, extent)


def _draw_hydraulic_legend(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_axis_off()
    ax.set_facecolor("#f8fafc")
    ax.text(
        0.5,
        0.74,
        title,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color="#111827",
    )
    ax.text(
        0.5,
        0.62,
        subtitle,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=11,
        color="#334155",
    )


def _draw_electric_legend(ax: plt.Axes) -> None:
    ax.set_axis_off()
    ax.set_facecolor("#f8fafc")
    electric_patch = Patch(facecolor="#fde68a", edgecolor="#a16207", linewidth=1.6, label="Maille electrique 0.1 deg")
    ax.legend(
        handles=[electric_patch],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.78),
        fontsize=11,
        title="Legende electrique",
        title_fontsize=12,
        frameon=False,
        borderaxespad=0.0,
    )


def build_png(output_path: Path = OUTPUT_PATH) -> Path:
    extent = _load_reference_extent()
    hydraulic_zones = _prepare_hydraulic_zones("AEP")
    electric_grid = _prepare_electric_grid()
    hydraulic_footprint = hydraulic_zones.dissolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(20, 14), facecolor="#f8fafc")
    gs = GridSpec(
        nrows=2,
        ncols=2,
        figure=fig,
        height_ratios=[3.5, 1.8],
        width_ratios=[1, 1],
        hspace=0.08,
        wspace=0.08,
    )

    ax_h = fig.add_subplot(gs[0, 0])
    ax_e = fig.add_subplot(gs[0, 1])
    ax_h_legend = fig.add_subplot(gs[1, 0])
    ax_e_legend = fig.add_subplot(gs[1, 1])

    _draw_hydraulic_zones(ax_h, hydraulic_zones, extent, "Zonage hydraulique AEP")
    _draw_electric_grid(ax_e, electric_grid, hydraulic_footprint, extent)

    fig.suptitle(
        "Guadeloupe - Comparaison des zonages du projet SIB",
        fontsize=24,
        fontweight="bold",
        color="#020617",
        y=0.975,
    )

    _draw_hydraulic_legend(ax_h_legend, "Legende hydraulique", "Couleurs : zonage hydraulique independant")
    _draw_electric_legend(ax_e_legend)

    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def build_png_with_eu(output_path: Path = OUTPUT_PATH_WITH_EU) -> Path:
    extent = _load_reference_extent()
    aep_zones = _prepare_hydraulic_zones("AEP")
    eu_zones = _prepare_hydraulic_zones("EU")
    electric_grid = _prepare_electric_grid()
    hydraulic_footprint = gpd.GeoDataFrame(
        geometry=[aep_zones.dissolve().geometry.iloc[0].union(eu_zones.dissolve().geometry.iloc[0])],
        crs=WEB_CRS,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(30, 14), facecolor="#f8fafc")
    gs = GridSpec(
        nrows=2,
        ncols=3,
        figure=fig,
        height_ratios=[3.5, 1.8],
        width_ratios=[1, 1, 1],
        hspace=0.08,
        wspace=0.08,
    )

    ax_aep = fig.add_subplot(gs[0, 0])
    ax_eu = fig.add_subplot(gs[0, 1])
    ax_elec = fig.add_subplot(gs[0, 2])
    ax_aep_legend = fig.add_subplot(gs[1, 0])
    ax_eu_legend = fig.add_subplot(gs[1, 1])
    ax_elec_legend = fig.add_subplot(gs[1, 2])

    _draw_hydraulic_zones(ax_aep, aep_zones, extent, "Zonage hydraulique AEP")
    _draw_hydraulic_zones(ax_eu, eu_zones, extent, "Zonage hydraulique EU")
    _draw_electric_grid(ax_elec, electric_grid, hydraulic_footprint, extent)

    fig.suptitle(
        "Guadeloupe - Comparaison des zonages du projet SIB",
        fontsize=24,
        fontweight="bold",
        color="#020617",
        y=0.975,
    )

    _draw_hydraulic_legend(ax_aep_legend, "Legende hydraulique AEP", "Couleurs : zones AEP independantes")
    _draw_hydraulic_legend(ax_eu_legend, "Legende hydraulique EU", "Couleurs : zones EU independantes")
    _draw_electric_legend(ax_elec_legend)

    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


if __name__ == "__main__":
    result = build_png()
    print(result)
    result_with_eu = build_png_with_eu()
    print(result_with_eu)
