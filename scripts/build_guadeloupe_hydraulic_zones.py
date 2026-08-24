#!/usr/bin/env python3
from __future__ import annotations

import argparse
import colorsys
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZipFile
from xml.etree import ElementTree as ET

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    gpd = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import rasterio
    from rasterio.features import shapes as raster_shapes
    from rasterio.windows import from_bounds
except Exception:  # pragma: no cover - optional at import time for CLI --help
    rasterio = None  # type: ignore[assignment]
    raster_shapes = None  # type: ignore[assignment]
    from_bounds = None  # type: ignore[assignment]

try:
    from shapely import concave_hull
    from shapely.geometry import shape as shapely_shape
    from shapely.ops import unary_union
except Exception:  # pragma: no cover - optional at import time for CLI --help
    concave_hull = None  # type: ignore[assignment]
    shapely_shape = None  # type: ignore[assignment]
    unary_union = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "outputs" / "hydraulic_zoning"
OUTPUT_GPKG = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate.gpkg"
OUTPUT_SUMMARY = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate.md"
OUTPUT_CSV = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_summary.csv"
OUTPUT_REWORK_REGISTRY = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_rework_registry.csv"
COMBINED_REWORK_REGISTRY = OUTPUT_DIR / "hydraulic_zone_rework_registry.csv"

METRIC_CRS = "EPSG:5490"
GRAY_COLOR = "#8B8F96"

AEP_LINES_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/AEP/cana_aep.gpkg")
AEP_ASSETS_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/AEP/ouvrage_aep.gpkg")
EU_LINES_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/cana_eu.gpkg")
EU_PR_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/pr.gpkg")
EU_STEP_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/step.gpkg")
GUA_POPULATION_RASTER = Path("/home/ubuntu/uploads/Population/glp_pop_2020_CN_100m_R2025A_v1.tif")

DICTIONARY_WORKBOOK = Path("/home/ubuntu/uploads/Dictionnaire_donnees_Martinique_Guadeloupe.xlsx")
METADATA_WORKBOOK = Path("/home/ubuntu/uploads/Zonage Hydraulique/Guadeloupe/metadata_aepclass_euclass.xlsx")

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"main": NS_MAIN, "rel": NS_REL}

AEP_ASSET_ROLE_MAP = {
    "CAP": ("captage_aep", "essential"),
    "TRAIT": ("upep_aep", "essential"),
    "STPMP": ("pompage_aep", "essential"),
    "CUV": ("reservoir_aep", "support"),
    "OUVEB": ("ouvrage_eau_brute_aep", "support"),
}

MAX_NEAREST_DISTANCE_LOCAL_M = 2000.0
MAX_NEAREST_DISTANCE_TERRITORY_M = 3000.0
FUZZY_MIN_LEN = 5
COMPONENT_PROXIMITY_THRESHOLD_M = 50.0

POLYGON_BUFFER_SMALL_M = 55.0
POLYGON_BUFFER_MEDIUM_M = 80.0
POLYGON_BUFFER_LARGE_M = 105.0
POLYGON_SIMPLIFY_FACTOR = 0.35
POLYGON_HULL_CLIP_FACTOR = 2.2
POLYGON_HULL_BUFFER_FACTOR = 0.45
POLYGON_ASSET_INCLUDE_HIGH_M = 1200.0
POLYGON_ASSET_INCLUDE_MEDIUM_M = 700.0
POLYGON_ASSET_INCLUDE_LOW_M = 300.0

REWORK_RATIO_THRESHOLD_AEP = 0.6
REWORK_RATIO_THRESHOLD_EU = 0.8
REWORK_MICRO_NETWORK_LINE_KM = 0.05
REWORK_MICRO_NETWORK_AREA_KM2 = 0.2
AEP_SOURCE_REQUIRED_LINE_KM = 0.5

POPULATION_MIN_CELL_VALUE = 2.0
POPULATION_EXPANSION_DISTANCE_MAX_M = 400.0
POPULATION_SMOOTHING_M = 35.0


def _require_geo_deps() -> None:
    missing: list[str] = []
    if gpd is None:
        missing.append("geopandas")
    if pd is None:
        missing.append("pandas")
    if concave_hull is None or unary_union is None:
        missing.append("shapely")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_guadeloupe_hydraulic_zones.py: "
            + ", ".join(sorted(set(missing)))
            + ". Run with sib-work/backend/.venv/bin/python or install backend requirements."
        )


def _normalize_text(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().strip()
    return re.sub(r"[^A-Z0-9]+", "", text)


def _clean_text(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split())


def _stable_color(key: str | None) -> str:
    if not key:
        return GRAY_COLOR
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0
    sat = 0.56 + (digest[1] / 255.0) * 0.18
    light = 0.46 + (digest[2] / 255.0) * 0.15
    red, green, blue = colorsys.hls_to_rgb(hue, light, sat)
    return f"#{int(red * 255):02X}{int(green * 255):02X}{int(blue * 255):02X}"


def _hex_to_rgba(color: str | None, *, alpha: int = 255) -> str:
    hex_color = str(color or GRAY_COLOR).strip().lstrip("#")
    if len(hex_color) != 6:
        hex_color = GRAY_COLOR.lstrip("#")
    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    return f"{red},{green},{blue},{max(0, min(255, int(alpha)))}"


def _darken_color(color: str | None, factor: float = 0.68) -> str:
    hex_color = str(color or GRAY_COLOR).strip().lstrip("#")
    if len(hex_color) != 6:
        hex_color = GRAY_COLOR.lstrip("#")
    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    return f"#{max(0, min(255, int(red * factor))):02X}{max(0, min(255, int(green * factor))):02X}{max(0, min(255, int(blue * factor))):02X}"


def _symbol_header(symbol_type: str, name: str) -> str:
    return f'<symbol alpha="1" clip_to_extent="1" type="{symbol_type}" name="{xml_escape(name)}" force_rhr="0">'


def _empty_data_defined_properties() -> str:
    return (
        "<data_defined_properties>"
        "<Option type=\"Map\">"
        "<Option name=\"name\" value=\"\" type=\"QString\"/>"
        "<Option name=\"properties\" type=\"Map\"/>"
        "<Option name=\"type\" value=\"collection\" type=\"QString\"/>"
        "</Option>"
        "</data_defined_properties>"
    )


def _fill_symbol_xml(name: str, color: str) -> str:
    fill_rgba = _hex_to_rgba(color, alpha=110)
    outline_rgba = _hex_to_rgba(_darken_color(color), alpha=220)
    return "\n".join(
        [
            _symbol_header("fill", name),
            '<layer pass="0" class="SimpleFill" enabled="1" locked="0">',
            '<Option type="Map">',
            '<Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            f'<Option name="color" type="QString" value="{fill_rgba}"/>',
            '<Option name="joinstyle" type="QString" value="bevel"/>',
            '<Option name="offset" type="QString" value="0,0"/>',
            '<Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="offset_unit" type="QString" value="MM"/>',
            f'<Option name="outline_color" type="QString" value="{outline_rgba}"/>',
            '<Option name="outline_style" type="QString" value="solid"/>',
            '<Option name="outline_width" type="QString" value="0.55"/>',
            '<Option name="outline_width_unit" type="QString" value="MM"/>',
            '<Option name="style" type="QString" value="solid"/>',
            '</Option>',
            f'<prop k="color" v="{fill_rgba}"/>',
            '<prop k="joinstyle" v="bevel"/>',
            '<prop k="offset" v="0,0"/>',
            f'<prop k="outline_color" v="{outline_rgba}"/>',
            '<prop k="outline_style" v="solid"/>',
            '<prop k="outline_width" v="0.55"/>',
            '<prop k="outline_width_unit" v="MM"/>',
            '<prop k="style" v="solid"/>',
            _empty_data_defined_properties(),
            '</layer>',
            '</symbol>',
        ]
    )


def _line_symbol_xml(name: str, color: str) -> str:
    line_rgba = _hex_to_rgba(color, alpha=255)
    return "\n".join(
        [
            _symbol_header("line", name),
            '<layer pass="0" class="SimpleLine" enabled="1" locked="0">',
            '<Option type="Map">',
            f'<Option name="line_color" type="QString" value="{line_rgba}"/>',
            '<Option name="line_style" type="QString" value="solid"/>',
            '<Option name="line_width" type="QString" value="0.8"/>',
            '<Option name="line_width_unit" type="QString" value="MM"/>',
            '<Option name="joinstyle" type="QString" value="round"/>',
            '<Option name="capstyle" type="QString" value="round"/>',
            '<Option name="customdash" type="QString" value="5;2"/>',
            '<Option name="customdash_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="customdash_unit" type="QString" value="MM"/>',
            '<Option name="draw_inside_polygon" type="QString" value="0"/>',
            '<Option name="offset" type="QString" value="0"/>',
            '<Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="offset_unit" type="QString" value="MM"/>',
            '<Option name="ring_filter" type="QString" value="0"/>',
            '<Option name="trim_distance_end" type="QString" value="0"/>',
            '<Option name="trim_distance_end_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="trim_distance_end_unit" type="QString" value="MM"/>',
            '<Option name="trim_distance_start" type="QString" value="0"/>',
            '<Option name="trim_distance_start_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="trim_distance_start_unit" type="QString" value="MM"/>',
            '<Option name="tweak_dash_pattern_on_corners" type="QString" value="0"/>',
            '<Option name="use_custom_dash" type="QString" value="0"/>',
            '<Option name="width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '</Option>',
            f'<prop k="line_color" v="{line_rgba}"/>',
            '<prop k="line_style" v="solid"/>',
            '<prop k="line_width" v="0.8"/>',
            '<prop k="line_width_unit" v="MM"/>',
            '<prop k="joinstyle" v="round"/>',
            '<prop k="capstyle" v="round"/>',
            _empty_data_defined_properties(),
            '</layer>',
            '</symbol>',
        ]
    )


def _marker_symbol_xml(name: str, color: str, *, marker_name: str, size_mm: float) -> str:
    fill_rgba = _hex_to_rgba(color, alpha=240)
    outline_rgba = _hex_to_rgba(_darken_color(color, factor=0.52), alpha=255)
    return "\n".join(
        [
            _symbol_header("marker", name),
            '<layer pass="0" class="SimpleMarker" enabled="1" locked="0">',
            '<Option type="Map">',
            '<Option name="angle" type="QString" value="0"/>',
            f'<Option name="color" type="QString" value="{fill_rgba}"/>',
            '<Option name="horizontal_anchor_point" type="QString" value="1"/>',
            '<Option name="joinstyle" type="QString" value="bevel"/>',
            f'<Option name="name" type="QString" value="{marker_name}"/>',
            '<Option name="offset" type="QString" value="0,0"/>',
            '<Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="offset_unit" type="QString" value="MM"/>',
            f'<Option name="outline_color" type="QString" value="{outline_rgba}"/>',
            '<Option name="outline_style" type="QString" value="solid"/>',
            '<Option name="outline_width" type="QString" value="0.4"/>',
            '<Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="outline_width_unit" type="QString" value="MM"/>',
            '<Option name="scale_method" type="QString" value="diameter"/>',
            f'<Option name="size" type="QString" value="{size_mm}"/>',
            '<Option name="size_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>',
            '<Option name="size_unit" type="QString" value="MM"/>',
            '<Option name="vertical_anchor_point" type="QString" value="1"/>',
            '</Option>',
            f'<prop k="color" v="{fill_rgba}"/>',
            '<prop k="horizontal_anchor_point" v="1"/>',
            '<prop k="joinstyle" v="bevel"/>',
            f'<prop k="name" v="{marker_name}"/>',
            '<prop k="offset" v="0,0"/>',
            f'<prop k="outline_color" v="{outline_rgba}"/>',
            '<prop k="outline_style" v="solid"/>',
            '<prop k="outline_width" v="0.4"/>',
            '<prop k="outline_width_unit" v="MM"/>',
            '<prop k="scale_method" v="diameter"/>',
            f'<prop k="size" v="{size_mm}"/>',
            '<prop k="size_unit" v="MM"/>',
            '<prop k="vertical_anchor_point" v="1"/>',
            _empty_data_defined_properties(),
            '</layer>',
            '</symbol>',
        ]
    )


def _categorized_qml(
    *,
    attr: str,
    geometry_type: int,
    categories: list[dict[str, str]],
    symbol_xml_builder,
) -> str:
    category_xml: list[str] = []
    symbols_xml: list[str] = []
    for idx, category in enumerate(categories):
        symbol_name = str(idx)
        category_xml.append(
            f'<category render="true" symbol="{symbol_name}" value="{xml_escape(category["value"])}" label="{xml_escape(category["label"])}" type="string"/>'
        )
        symbols_xml.append(symbol_xml_builder(symbol_name, category["color"]))

    source_symbol = symbol_xml_builder("source", GRAY_COLOR)
    return "\n".join(
        [
            '<qgis version="3.34.0" styleCategories="AllStyleCategories">',
            f'<renderer-v2 type="categorizedSymbol" attr="{xml_escape(attr)}" symbollevels="0" forceraster="0" enableorderby="0">',
            '<categories>',
            *category_xml,
            '</categories>',
            '<symbols>',
            *symbols_xml,
            '</symbols>',
            '<source-symbol>',
            source_symbol,
            '</source-symbol>',
            '<rotation/>',
            '<sizescale/>',
            '</renderer-v2>',
            '<selection mode="Default">',
            '<selectionColor invalid="1"/>',
            '</selection>',
            '<blendMode>0</blendMode>',
            '<featureBlendMode>0</featureBlendMode>',
            f'<layerGeometryType>{geometry_type}</layerGeometryType>',
            '</qgis>',
        ]
    )


def _zone_style_categories(gdf: gpd.GeoDataFrame) -> list[dict[str, str]]:
    if gdf.empty:
        return []
    style_key = _require_zone_component_key_field(gdf, context="hydraulic styling")
    style_label = "zone_component_label" if "zone_component_label" in gdf.columns and gdf["zone_component_label"].notna().any() else "zone_label"
    base = gdf[gdf[style_key].notna()][[style_key, style_label, "zone_color"]].drop_duplicates().copy()
    if base.empty:
        return []
    base[style_label] = base[style_label].fillna(base[style_key])
    base["zone_color"] = base["zone_color"].fillna(GRAY_COLOR)
    rows = [
        {
            "value": str(getattr(row, style_key)),
            "label": str(getattr(row, style_label)),
            "color": str(row.zone_color),
        }
        for row in base.sort_values([style_label, style_key]).itertuples(index=False)
    ]
    return rows


def _require_zone_component_key_field(gdf: gpd.GeoDataFrame, *, context: str) -> str:
    if "zone_component_key" not in gdf.columns:
        raise ValueError(f"{context} requires zone_component_key")
    if gdf.empty:
        return "zone_component_key"
    required_mask = pd.Series([True] * len(gdf), index=gdf.index, dtype=bool)
    if "zone_uid" in gdf.columns:
        required_mask &= gdf["zone_uid"].notna()
    if required_mask.any():
        values = gdf.loc[required_mask, "zone_component_key"].astype("string").str.strip()
        if values.isna().any() or (values == "").any():
            raise ValueError(f"{context} requires non-null zone_component_key for assigned hydraulic features")
    return "zone_component_key"


def _ensure_layer_styles_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS layer_styles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            f_table_catalog TEXT,
            f_table_schema TEXT,
            f_table_name TEXT NOT NULL,
            f_geometry_column TEXT NOT NULL,
            styleName TEXT,
            styleQML TEXT,
            styleSLD TEXT,
            useAsDefault INTEGER,
            description TEXT,
            owner TEXT,
            ui TEXT,
            update_time TEXT DEFAULT CURRENT_TIMESTAMP,
            type TEXT
        )
        """
    )


def _embed_qml_styles_in_gpkg(path: Path, styles: dict[str, str]) -> None:
    with sqlite3.connect(path) as conn:
        _ensure_layer_styles_table(conn)
        geom_cols = {row[0]: row[1] for row in conn.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall()}
        for layer_name, style_qml in styles.items():
            geom_col = geom_cols.get(layer_name)
            if not geom_col:
                continue
            conn.execute("DELETE FROM layer_styles WHERE f_table_name = ?", (layer_name,))
            conn.execute(
                """
                INSERT INTO layer_styles (
                    f_table_catalog,
                    f_table_schema,
                    f_table_name,
                    f_geometry_column,
                    styleName,
                    styleQML,
                    styleSLD,
                    useAsDefault,
                    description,
                    owner,
                    ui,
                    type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "",
                    "",
                    layer_name,
                    geom_col,
                    "default",
                    style_qml,
                    "",
                    1,
                    f"Auto-generated default style for {layer_name}",
                    "copilot",
                    "",
                    "default",
                ),
            )
        conn.commit()


def _write_qgis_styles(
    output_gpkg: Path,
    lines: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    captages: gpd.GeoDataFrame,
) -> dict[str, Path]:
    style_attr = _require_zone_component_key_field(polygons, context="hydraulic polygon styling")
    zone_categories = _zone_style_categories(polygons)
    line_categories = _zone_style_categories(lines)
    captage_categories = _zone_style_categories(captages)

    qml_map = {
        "hydraulic_zones": _categorized_qml(
            attr=style_attr,
            geometry_type=2,
            categories=zone_categories,
            symbol_xml_builder=_fill_symbol_xml,
        ),
        "hydraulic_lines": _categorized_qml(
            attr=style_attr,
            geometry_type=1,
            categories=line_categories,
            symbol_xml_builder=_line_symbol_xml,
        ),
        "hydraulic_captages": _categorized_qml(
            attr=style_attr,
            geometry_type=0,
            categories=captage_categories,
            symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="cross_fill", size_mm=7.5),
        ),
    }

    output_qml_styles = {
        "hydraulic_zones": output_gpkg.with_name(f"{output_gpkg.stem}_hydraulic_zones.qml"),
        "hydraulic_lines": output_gpkg.with_name(f"{output_gpkg.stem}_hydraulic_lines.qml"),
        "hydraulic_captages": output_gpkg.with_name(f"{output_gpkg.stem}_hydraulic_captages.qml"),
    }
    for layer_name, qml_path in output_qml_styles.items():
        qml_path.write_text(qml_map[layer_name] + "\n", encoding="utf-8")

    _embed_qml_styles_in_gpkg(output_gpkg, qml_map)
    return output_qml_styles


def _valid_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geometry = gdf.geometry
    return gdf[(~geometry.is_empty) & geometry.notna()].copy()


def _representative_point(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == "Point":
        return geom
    return geom.representative_point()


def _polygon_buffer_distance(line_length_m: float) -> float:
    if line_length_m < 2_000.0:
        return POLYGON_BUFFER_SMALL_M
    if line_length_m < 15_000.0:
        return POLYGON_BUFFER_MEDIUM_M
    return POLYGON_BUFFER_LARGE_M


def _polygon_simplify_distance(buffer_m: float) -> float:
    return max(12.0, buffer_m * POLYGON_SIMPLIFY_FACTOR)


def _polygon_hull_ratio(line_length_m: float, included_asset_count: int) -> float:
    if line_length_m < 1_500.0:
        return 0.58
    if included_asset_count <= 1:
        return 0.5
    if line_length_m < 10_000.0:
        return 0.46
    return 0.4


def _polygon_asset_include_distance(method: object | None, confidence: object | None) -> float:
    method_text = str(method or "")
    confidence_value = float(confidence or 0.0)
    if "territory" in method_text or method_text.endswith("_any"):
        return 0.0
    if "commune" in method_text or "manager" in method_text or "same_commune" in method_text:
        return POLYGON_ASSET_INCLUDE_LOW_M if confidence_value < 0.6 else POLYGON_ASSET_INCLUDE_MEDIUM_M
    if confidence_value < 0.5:
        return POLYGON_ASSET_INCLUDE_LOW_M
    if confidence_value < 0.75:
        return POLYGON_ASSET_INCLUDE_MEDIUM_M
    return POLYGON_ASSET_INCLUDE_HIGH_M


def _zone_component_key(zone_uid: object | None, geometry_part_id: int, component_count: int) -> str | None:
    zone_text = str(zone_uid or "").strip()
    if not zone_text:
        return None
    if component_count <= 1:
        return zone_text
    return f"{zone_text}__P{geometry_part_id}"


def _zone_component_label(zone_label: object | None, zone_uid: object | None, geometry_part_id: int, component_count: int) -> str:
    base_label = str(zone_label or zone_uid or "").strip() or str(zone_uid or "")
    if component_count <= 1:
        return base_label
    return f"{base_label} [part {geometry_part_id}]"


def _line_component_groups(zone_lines: gpd.GeoDataFrame) -> list[list[int]]:
    if zone_lines.empty:
        return []
    local = zone_lines.reset_index().rename(columns={"index": "_line_index"})
    geoms = list(local.geometry)
    sindex = local.geometry.sindex
    visited: set[int] = set()
    components: list[list[int]] = []

    for position, geom in enumerate(geoms):
        if position in visited:
            continue
        visited.add(position)
        if geom is None or geom.is_empty:
            components.append([int(local.loc[position, "_line_index"])])
            continue

        stack = [position]
        component_positions: list[int] = []
        while stack:
            current = stack.pop()
            component_positions.append(current)
            current_geom = geoms[current]
            if current_geom is None or current_geom.is_empty:
                continue
            search_geom = current_geom.buffer(COMPONENT_PROXIMITY_THRESHOLD_M)
            for neighbor in sindex.query(search_geom, predicate="intersects"):
                neighbor = int(neighbor)
                if neighbor in visited:
                    continue
                neighbor_geom = geoms[neighbor]
                if neighbor_geom is None or neighbor_geom.is_empty:
                    continue
                if current_geom.distance(neighbor_geom) <= COMPONENT_PROXIMITY_THRESHOLD_M:
                    visited.add(neighbor)
                    stack.append(neighbor)
        components.append([int(local.loc[pos, "_line_index"]) for pos in component_positions])

    sortable_components: list[tuple[str, list[int]]] = []
    for component_indexes in components:
        component_rows = zone_lines.loc[component_indexes]
        if "feature_id" in component_rows.columns and component_rows["feature_id"].notna().any():
            sort_key = min(component_rows["feature_id"].astype(str).tolist())
        else:
            sort_key = str(min(component_indexes))
        sortable_components.append((sort_key, component_indexes))
    sortable_components.sort(key=lambda item: item[0])
    return [indexes for _, indexes in sortable_components]


def _assign_zone_components(lines: gpd.GeoDataFrame, assets: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    lines_out = lines.copy()
    assets_out = assets.copy()
    for gdf in (lines_out, assets_out):
        gdf["geometry_part_id"] = pd.Series([pd.NA] * len(gdf), dtype="Int64")
        gdf["zone_component_key"] = None
        gdf["zone_component_label"] = None

    component_rows: list[dict[str, object]] = []
    metric_lines = lines_out.to_crs(METRIC_CRS)
    for zone_uid, line_group in metric_lines[metric_lines["zone_uid"].notna()].groupby("zone_uid", dropna=False):
        component_indexes_list = _line_component_groups(line_group)
        component_count = len(component_indexes_list)
        for geometry_part_id, component_indexes in enumerate(component_indexes_list, start=1):
            zone_component_key = _zone_component_key(zone_uid, geometry_part_id, component_count)
            component_lines_metric = metric_lines.loc[component_indexes]
            component_lines_out = lines_out.loc[component_indexes]
            zone_component_label = _zone_component_label(
                component_lines_out.iloc[0].get("zone_label"),
                zone_uid,
                geometry_part_id,
                component_count,
            )
            lines_out.loc[component_indexes, "geometry_part_id"] = geometry_part_id
            lines_out.loc[component_indexes, "zone_component_key"] = zone_component_key
            lines_out.loc[component_indexes, "zone_component_label"] = zone_component_label
            component_rows.append(
                {
                    "zone_uid": zone_uid,
                    "geometry_part_id": geometry_part_id,
                    "zone_component_key": zone_component_key,
                    "zone_component_label": zone_component_label,
                    "zone_name": component_lines_out.iloc[0].get("zone_name"),
                    "zone_label": component_lines_out.iloc[0].get("zone_label"),
                    "zone_color": component_lines_out.iloc[0].get("zone_color"),
                    "network_kind": component_lines_out.iloc[0].get("network_kind"),
                    "geometry": unary_union([geom for geom in component_lines_metric.geometry if geom is not None and not geom.is_empty]),
                }
            )

    component_lookup = gpd.GeoDataFrame(component_rows, geometry="geometry", crs=METRIC_CRS)
    if component_lookup.empty:
        return lines_out, assets_out, component_lookup

    components_by_zone = {
        zone_uid: group.copy()
        for zone_uid, group in component_lookup.groupby("zone_uid", dropna=False)
    }
    assets_metric = assets_out.to_crs(METRIC_CRS)
    for idx, asset_row in assets_metric[assets_metric["zone_uid"].notna()].iterrows():
        candidates = components_by_zone.get(asset_row["zone_uid"])
        if candidates is None or candidates.empty:
            continue
        if len(candidates) == 1:
            component_row = candidates.iloc[0]
        else:
            asset_point = _representative_point(asset_row.geometry)
            if asset_point is None or asset_point.is_empty:
                continue
            distances = candidates.geometry.distance(asset_point)
            component_row = candidates.loc[distances.idxmin()]
        assets_out.at[idx, "geometry_part_id"] = int(component_row["geometry_part_id"])
        assets_out.at[idx, "zone_component_key"] = component_row["zone_component_key"]
        assets_out.at[idx, "zone_component_label"] = component_row["zone_component_label"]

    return lines_out, assets_out, component_lookup


def _empty_population_areas() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"population_value": pd.Series(dtype="float64")},
        geometry=gpd.GeoSeries([], crs=METRIC_CRS),
        crs=METRIC_CRS,
    )


def _load_population_areas(population_raster_path: Path, reference_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if rasterio is None or np is None or raster_shapes is None or from_bounds is None or shapely_shape is None:
        return _empty_population_areas()
    if reference_gdf.empty or not population_raster_path.exists():
        return _empty_population_areas()

    metric_bounds = reference_gdf.to_crs(METRIC_CRS).total_bounds
    if len(metric_bounds) != 4:
        return _empty_population_areas()
    minx, miny, maxx, maxy = metric_bounds
    metric_clip = gpd.GeoDataFrame(
        geometry=[gpd.GeoSeries.from_wkt([f"POLYGON(({minx - POPULATION_EXPANSION_DISTANCE_MAX_M} {miny - POPULATION_EXPANSION_DISTANCE_MAX_M},{maxx + POPULATION_EXPANSION_DISTANCE_MAX_M} {miny - POPULATION_EXPANSION_DISTANCE_MAX_M},{maxx + POPULATION_EXPANSION_DISTANCE_MAX_M} {maxy + POPULATION_EXPANSION_DISTANCE_MAX_M},{minx - POPULATION_EXPANSION_DISTANCE_MAX_M} {maxy + POPULATION_EXPANSION_DISTANCE_MAX_M},{minx - POPULATION_EXPANSION_DISTANCE_MAX_M} {miny - POPULATION_EXPANSION_DISTANCE_MAX_M}))"], crs=METRIC_CRS).iloc[0]],
        crs=METRIC_CRS,
    )

    try:
        with rasterio.open(population_raster_path) as src:
            clip_bounds = metric_clip.to_crs(src.crs).total_bounds
            window = from_bounds(*clip_bounds, transform=src.transform)
            data = src.read(1, window=window, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
            if data is None or data.size == 0:
                return _empty_population_areas()
            valid_mask = np.isfinite(data)
            if src.nodata is not None:
                valid_mask &= data != src.nodata
            populated_mask = valid_mask & (data >= POPULATION_MIN_CELL_VALUE)
            if not np.any(populated_mask):
                return _empty_population_areas()

            transform = src.window_transform(window)
            rows: list[dict[str, object]] = []
            for geom_json, value in raster_shapes(data.astype("float32"), mask=populated_mask, transform=transform):
                if float(value) < POPULATION_MIN_CELL_VALUE:
                    continue
                geom = shapely_shape(geom_json)
                if geom.is_empty:
                    continue
                rows.append({"population_value": float(value), "geometry": geom})
    except Exception:
        return _empty_population_areas()

    if not rows:
        return _empty_population_areas()
    population_areas = gpd.GeoDataFrame(rows, geometry="geometry", crs=src.crs if 'src' in locals() else None)
    if population_areas.crs is None:
        return _empty_population_areas()
    return population_areas.to_crs(METRIC_CRS)


def _expand_polygon_to_population(
    polygon,
    corridor,
    population_areas: gpd.GeoDataFrame | None,
    *,
    expansion_distance_m: float,
    simplify_m: float,
) -> tuple[object, float, int]:
    if population_areas is None or population_areas.empty or expansion_distance_m <= 0.0:
        return polygon, 0.0, 0
    search_geom = corridor.buffer(expansion_distance_m)
    nearby = population_areas[population_areas.geometry.intersects(search_geom)].copy()
    if nearby.empty:
        return polygon, 0.0, 0
    populated_geom = unary_union([geom for geom in nearby.geometry if geom is not None and not geom.is_empty])
    if populated_geom is None or populated_geom.is_empty:
        return polygon, 0.0, 0
    expanded = unary_union([polygon, populated_geom.buffer(POPULATION_SMOOTHING_M)])
    expanded = expanded.intersection(search_geom).buffer(0)
    if expanded.is_empty:
        return polygon, 0.0, 0
    expanded = expanded.simplify(max(simplify_m, 18.0), preserve_topology=True).buffer(0)
    added_area_km2 = max(0.0, float(expanded.area - polygon.area) / 1_000_000.0)
    return expanded, round(added_area_km2, 4), int(len(nearby))


def _population_expansion_distance(line_length_m: float) -> float:
    if line_length_m < 400.0:
        return 0.0
    if line_length_m < 2_000.0:
        return 120.0
    if line_length_m < 10_000.0:
        return 250.0
    return POPULATION_EXPANSION_DISTANCE_MAX_M


def _col_ref(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def _read_sheet_cells(path: Path, sheet_name: str) -> list[dict[str, str | None]]:
    with ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//main:t", NS)))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        target = None
        for sheet in workbook.find("main:sheets", NS):
            if sheet.attrib["name"] == sheet_name:
                target = rel_map[sheet.attrib[f"{{{NS_REL}}}id"]]
                break
        if target is None:
            return []

        worksheet_path = "xl/" + (target if target.startswith("worksheets/") else f"worksheets/{target.split('/')[-1]}")
        root = ET.fromstring(zf.read(worksheet_path))
        rows: list[dict[str, str | None]] = []
        for row in root.findall(".//main:sheetData/main:row", NS):
            cells: dict[str, str | None] = {}
            for cell in row.findall("main:c", NS):
                col = _col_ref(cell.attrib.get("r", ""))
                value = None
                value_node = cell.find("main:v", NS)
                cell_type = cell.attrib.get("t")
                if value_node is not None:
                    raw = value_node.text
                    if cell_type == "s" and raw is not None:
                        value = shared[int(raw)]
                    else:
                        value = raw
                inline = cell.find("main:is", NS)
                if inline is not None:
                    value = "".join(t.text or "" for t in inline.findall(".//main:t", NS))
                cells[col] = value
            rows.append(cells)
        return rows


def _dictionary_notes() -> dict[str, str]:
    notes: dict[str, str] = {}

    if DICTIONARY_WORKBOOK.exists():
        for row in _read_sheet_cells(DICTIONARY_WORKBOOK, "DICT_Gua_deduit"):
            sheet_name = _clean_text(row.get("A"))
            field_name = _clean_text(row.get("B"))
            certainty = _clean_text(row.get("C"))
            description = _clean_text(row.get("D"))
            if not sheet_name or not field_name or not description:
                continue
            key = f"{sheet_name}.{field_name}"
            if key in {
                "Ouvrages_AEP_Gua.ovrg_type",
                "Ouvrages_AEP_Gua.ovrg_capfor_type",
                "PR_EU_Gua.reseau_type",
                "PR_EU_Gua.pelem_secteur",
                "STEP_EU_GUA.pelem_secteur",
                "Cana_EU_Gua.pelem_secteur",
            }:
                suffix = f" (confiance dictionnaire: {certainty})" if certainty else ""
                notes[key] = f"{description}{suffix}"

    if METADATA_WORKBOOK.exists():
        for row in _read_sheet_cells(METADATA_WORKBOOK, "Feuil1"):
            schema_name = _clean_text(row.get("B"))
            table_name = _clean_text(row.get("C"))
            field_name = _clean_text(row.get("D"))
            complement = _clean_text(row.get("E"))
            if (schema_name, table_name, field_name) == ("aep_class", "cana", "pelem_zonehydraulique"):
                notes["AEP.zone_basis"] = complement or "Zone d'alimentation"
            if (schema_name, table_name, field_name) == ("aep_class", "cana", "pelem_secteur"):
                notes["AEP.sector_basis"] = complement or "Zone de distribution"

    return notes


def _prepare_aep_lines(notes: dict[str, str]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, object]]:
    gdf = gpd.read_file(AEP_LINES_PATH)[
        [
            "pelem_id",
            "pelem_commune",
            "pelem_secteur",
            "pelem_zonehydraulique",
            "geometry",
        ]
    ].copy()
    gdf = _valid_geometries(gdf)
    metric = gdf.to_crs(METRIC_CRS).copy()
    gdf["line_length_m"] = metric.geometry.length.astype(float)
    gdf["commune"] = gdf["pelem_commune"].map(_clean_text)
    gdf["commune_norm"] = gdf["commune"].map(_normalize_text)
    gdf["zone_name"] = gdf["pelem_zonehydraulique"].map(_clean_text)
    gdf["zone_norm"] = gdf["zone_name"].map(_normalize_text)
    gdf["sector_name"] = gdf["pelem_secteur"].map(_clean_text)
    gdf["sector_norm"] = gdf["sector_name"].map(_normalize_text)
    gdf["zone_uid"] = gdf["zone_norm"].map(lambda val: f"AEP_{val}" if val else None)
    gdf["zone_label"] = gdf["zone_name"]
    gdf["zone_color"] = gdf["zone_uid"].map(_stable_color)
    gdf["network_kind"] = "AEP"
    gdf["feature_role"] = "canalisation"
    gdf["source_layer"] = "AEP/cana_aep.gpkg"
    gdf["zone_basis"] = "pelem_zonehydraulique"
    gdf["zone_basis_note"] = notes.get("AEP.zone_basis", "Zone d'alimentation")
    gdf["zone_method"] = gdf["zone_uid"].map(lambda val: "source_field" if val else "missing")
    gdf["zone_confidence"] = gdf["zone_uid"].map(lambda val: 0.98 if val else 0.0)
    gdf["source_feature_id"] = gdf["pelem_id"].astype(str)
    gdf["feature_id"] = [f"aep-line-{idx + 1}" for idx in range(len(gdf))]

    metric = gdf.to_crs(METRIC_CRS).copy()
    info = {
        "zone_name_by_uid": dict(gdf[["zone_uid", "zone_name"]].dropna().drop_duplicates().values.tolist()),
        "zone_label_by_uid": dict(gdf[["zone_uid", "zone_label"]].dropna().drop_duplicates().values.tolist()),
        "zone_color_by_uid": dict(gdf[["zone_uid", "zone_color"]].dropna().drop_duplicates().values.tolist()),
    }
    return gdf, metric, info


def _prepare_eu_lines(notes: dict[str, str]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, object]]:
    gdf = gpd.read_file(EU_LINES_PATH)[
        [
            "pelem_id",
            "pelem_commune",
            "pelem_secteur",
            "pelem_soussecteur",
            "geometry",
        ]
    ].copy()
    gdf = _valid_geometries(gdf)
    metric = gdf.to_crs(METRIC_CRS).copy()
    gdf["line_length_m"] = metric.geometry.length.astype(float)
    gdf["commune"] = gdf["pelem_commune"].map(_clean_text)
    gdf["commune_norm"] = gdf["commune"].map(_normalize_text)
    gdf["zone_name"] = gdf["pelem_secteur"].map(_clean_text)
    gdf["zone_norm"] = gdf["zone_name"].map(_normalize_text)
    gdf["sector_name"] = gdf["pelem_soussecteur"].map(_clean_text)
    gdf["sector_norm"] = gdf["sector_name"].map(_normalize_text)
    gdf["zone_uid"] = gdf.apply(
        lambda row: f"EU_{row['commune_norm']}_{row['zone_norm']}" if row["commune_norm"] and row["zone_norm"] else None,
        axis=1,
    )
    gdf["zone_label"] = gdf.apply(
        lambda row: f"{row['commune']} - {row['zone_name']}" if row["commune"] and row["zone_name"] else row["zone_name"],
        axis=1,
    )
    gdf["zone_color"] = gdf["zone_uid"].map(_stable_color)
    gdf["network_kind"] = "EU"
    gdf["feature_role"] = "canalisation"
    gdf["source_layer"] = "EU/cana_eu.gpkg"
    gdf["zone_basis"] = "pelem_secteur"
    gdf["zone_basis_note"] = notes.get("Cana_EU_Gua.pelem_secteur", "Secteur hydraulique")
    gdf["zone_method"] = gdf["zone_uid"].map(lambda val: "source_field" if val else "missing")
    gdf["zone_confidence"] = gdf["zone_uid"].map(lambda val: 0.85 if val else 0.0)
    gdf["source_feature_id"] = gdf["pelem_id"].astype(str)
    gdf["feature_id"] = [f"eu-line-{idx + 1}" for idx in range(len(gdf))]

    metric = gdf.to_crs(METRIC_CRS).copy()
    info = {
        "zone_name_by_uid": dict(gdf[["zone_uid", "zone_name"]].dropna().drop_duplicates().values.tolist()),
        "zone_label_by_uid": dict(gdf[["zone_uid", "zone_label"]].dropna().drop_duplicates().values.tolist()),
        "zone_color_by_uid": dict(gdf[["zone_uid", "zone_color"]].dropna().drop_duplicates().values.tolist()),
    }
    return gdf, metric, info


def _build_line_indexes(lines_metric: gpd.GeoDataFrame) -> dict[str, object]:
    valid = lines_metric[lines_metric["zone_uid"].notna()].copy()
    zone_lengths = valid.groupby("zone_uid", dropna=True)["line_length_m"].sum().to_dict()

    zone_meta = (
        valid[["zone_uid", "zone_name", "zone_label", "zone_color", "zone_basis", "zone_basis_note", "network_kind"]]
        .drop_duplicates("zone_uid")
        .set_index("zone_uid")
        .to_dict("index")
    )

    local_zone_map: dict[str, dict[str, str]] = defaultdict(dict)
    local_sector_map: dict[str, dict[str, str]] = defaultdict(dict)
    global_zone_map: dict[str, str] = {}

    zone_choice = (
        valid[valid["zone_norm"].astype(bool)]
        .groupby(["commune_norm", "zone_norm", "zone_uid"], dropna=False)["line_length_m"]
        .sum()
        .reset_index()
        .sort_values(["commune_norm", "zone_norm", "line_length_m"], ascending=[True, True, False])
    )
    for _, row in zone_choice.drop_duplicates(["commune_norm", "zone_norm"]).iterrows():
        local_zone_map[str(row["commune_norm"])][str(row["zone_norm"])] = str(row["zone_uid"])

    global_zone_choice = (
        valid[valid["zone_norm"].astype(bool)]
        .groupby(["zone_norm", "zone_uid"], dropna=False)["line_length_m"]
        .sum()
        .reset_index()
        .sort_values(["zone_norm", "line_length_m"], ascending=[True, False])
    )
    for _, row in global_zone_choice.drop_duplicates(["zone_norm"]).iterrows():
        global_zone_map[str(row["zone_norm"])] = str(row["zone_uid"])

    sector_choice = (
        valid[valid["zone_uid"].notna() & valid["zone_name"].astype(bool) & valid["sector_norm"].astype(bool)]
        .groupby(["commune_norm", "sector_norm", "zone_uid"], dropna=False)["line_length_m"]
        .sum()
        .reset_index()
        .sort_values(["commune_norm", "sector_norm", "line_length_m"], ascending=[True, True, False])
    )
    for _, row in sector_choice.drop_duplicates(["commune_norm", "sector_norm"]).iterrows():
        local_sector_map[str(row["commune_norm"] or "")][str(row["sector_norm"])] = str(row["zone_uid"])

    lines_by_commune: dict[str, gpd.GeoDataFrame] = {}
    for commune_norm, group in valid.groupby("commune_norm", dropna=False):
        lines_by_commune[str(commune_norm or "")] = group.copy()

    return {
        "zone_lengths": zone_lengths,
        "zone_meta": zone_meta,
        "local_zone_map": local_zone_map,
        "local_sector_map": local_sector_map,
        "global_zone_map": global_zone_map,
        "lines_by_commune": lines_by_commune,
        "all_lines": valid,
    }


def _best_contains_match(candidate: str, options: dict[str, str], zone_lengths: dict[str, float]) -> tuple[str, str] | None:
    best: tuple[int, float, str, str] | None = None
    for option_norm, zone_uid in options.items():
        if not option_norm or len(option_norm) < FUZZY_MIN_LEN:
            continue
        if option_norm in candidate or candidate in option_norm:
            score = (min(len(option_norm), len(candidate)), float(zone_lengths.get(zone_uid, 0.0)))
            current = (score[0], score[1], option_norm, zone_uid)
            if best is None or current > best:
                best = current
    if best is None:
        return None
    return best[2], best[3]


def _zone_match_from_candidates(
    candidates: list[tuple[str, str]],
    commune_norm: str,
    indexes: dict[str, object],
    *,
    use_global_zone_map: bool,
    allow_global_sector_map: bool,
) -> dict[str, object] | None:
    local_zone_map = dict(indexes["local_zone_map"].get(commune_norm, {}))
    local_sector_map = dict(indexes["local_sector_map"].get(commune_norm, {}))
    global_zone_map = dict(indexes["global_zone_map"])
    zone_meta = dict(indexes["zone_meta"])
    zone_lengths = dict(indexes["zone_lengths"])

    def build(zone_uid: str, method: str, confidence: float, matched_field: str, matched_value: str) -> dict[str, object]:
        meta = dict(zone_meta.get(zone_uid, {}))
        return {
            "zone_uid": zone_uid,
            "zone_name": meta.get("zone_name"),
            "zone_label": meta.get("zone_label"),
            "zone_color": meta.get("zone_color", GRAY_COLOR),
            "zone_basis": meta.get("zone_basis"),
            "zone_basis_note": meta.get("zone_basis_note"),
            "method": method,
            "confidence": confidence,
            "matched_field": matched_field,
            "matched_value": matched_value,
            "distance_m": None,
        }

    for field_name, candidate in candidates:
        if candidate in local_zone_map:
            return build(local_zone_map[candidate], "exact_zone_name", 0.92, field_name, candidate)
        if candidate in local_sector_map:
            return build(local_sector_map[candidate], "exact_sector_name", 0.86, field_name, candidate)
        if use_global_zone_map and candidate in global_zone_map:
            return build(global_zone_map[candidate], "exact_zone_name_global", 0.82, field_name, candidate)

    for field_name, candidate in candidates:
        fuzzy = _best_contains_match(candidate, local_zone_map, zone_lengths)
        if fuzzy is not None:
            return build(fuzzy[1], "contains_zone_name", 0.76, field_name, candidate)
        fuzzy = _best_contains_match(candidate, local_sector_map, zone_lengths)
        if fuzzy is not None:
            return build(fuzzy[1], "contains_sector_name", 0.72, field_name, candidate)
        if use_global_zone_map:
            fuzzy = _best_contains_match(candidate, global_zone_map, zone_lengths)
            if fuzzy is not None:
                return build(fuzzy[1], "contains_zone_name_global", 0.66, field_name, candidate)

    if allow_global_sector_map:
        global_sector_map: dict[str, str] = {}
        for sector_map in indexes["local_sector_map"].values():
            for sector_norm, zone_uid in sector_map.items():
                if sector_norm not in global_sector_map:
                    global_sector_map[sector_norm] = zone_uid
        for field_name, candidate in candidates:
            if candidate in global_sector_map:
                return build(global_sector_map[candidate], "exact_sector_name_global", 0.62, field_name, candidate)
            fuzzy = _best_contains_match(candidate, global_sector_map, zone_lengths)
            if fuzzy is not None:
                return build(fuzzy[1], "contains_sector_name_global", 0.58, field_name, candidate)

    return None


def _nearest_line_match(geom, commune_norm: str, indexes: dict[str, object]) -> dict[str, object] | None:
    zone_meta = dict(indexes["zone_meta"])
    local = indexes["lines_by_commune"].get(commune_norm)
    scope = "commune"
    max_distance = MAX_NEAREST_DISTANCE_LOCAL_M
    if local is None or local.empty:
        local = indexes["all_lines"]
        scope = "territory"
        max_distance = MAX_NEAREST_DISTANCE_TERRITORY_M
    if local is None or local.empty:
        return None

    point = _representative_point(geom)
    distances = local.geometry.distance(point)
    nearest_idx = distances.idxmin()
    nearest_distance = float(distances.loc[nearest_idx])
    if nearest_distance > max_distance:
        return None

    zone_uid = str(local.loc[nearest_idx, "zone_uid"])
    meta = dict(zone_meta.get(zone_uid, {}))
    confidence = 0.45 if scope == "commune" else 0.35
    return {
        "zone_uid": zone_uid,
        "zone_name": meta.get("zone_name"),
        "zone_label": meta.get("zone_label"),
        "zone_color": meta.get("zone_color", GRAY_COLOR),
        "zone_basis": meta.get("zone_basis"),
        "zone_basis_note": meta.get("zone_basis_note"),
        "method": f"nearest_line_{scope}",
        "confidence": confidence,
        "matched_field": "geometry",
        "matched_value": "",
        "distance_m": nearest_distance,
    }


def _asset_assignment_rows(
    assets_metric: gpd.GeoDataFrame,
    indexes: dict[str, object],
    candidate_fields: list[str],
    *,
    use_global_zone_map: bool,
    allow_global_sector_map: bool,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx, row in assets_metric.iterrows():
        commune_norm = _normalize_text(row.get("commune"))
        candidates: list[tuple[str, str]] = []
        for field_name in candidate_fields:
            raw_value = _clean_text(row.get(field_name))
            norm_value = _normalize_text(raw_value)
            if norm_value:
                candidates.append((field_name, norm_value))
        seen = set()
        ordered_candidates: list[tuple[str, str]] = []
        for field_name, candidate in candidates:
            key = (field_name, candidate)
            if key in seen:
                continue
            seen.add(key)
            ordered_candidates.append((field_name, candidate))

        match = _zone_match_from_candidates(
            ordered_candidates,
            commune_norm,
            indexes,
            use_global_zone_map=use_global_zone_map,
            allow_global_sector_map=allow_global_sector_map,
        )
        if match is None:
            match = _nearest_line_match(row.geometry, commune_norm, indexes)
        if match is None:
            match = {
                "zone_uid": None,
                "zone_name": None,
                "zone_label": None,
                "zone_color": GRAY_COLOR,
                "zone_basis": None,
                "zone_basis_note": None,
                "method": "unassigned",
                "confidence": 0.0,
                "matched_field": None,
                "matched_value": None,
                "distance_m": None,
            }
        rows.append({"_asset_index": idx, **match})
    return pd.DataFrame(rows).set_index("_asset_index")


def _prepare_aep_assets(indexes: dict[str, object]) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(AEP_ASSETS_PATH)[
        [
            "ovrg_idu",
            "ovrg_id",
            "ovrg_nom",
            "ovrg_type",
            "ovrg_capfor_type",
            "up_ebtyp",
            "pmp_typ",
            "pelem_commune",
            "geometry",
        ]
    ].copy()
    gdf = _valid_geometries(gdf)
    gdf["asset_name"] = gdf["ovrg_nom"].map(_clean_text)
    gdf["commune"] = gdf["pelem_commune"].map(_clean_text)
    gdf["asset_type_code"] = gdf["ovrg_type"].map(_clean_text)
    gdf["asset_subtype_code"] = gdf.apply(
        lambda row: _clean_text(row["ovrg_capfor_type"] or row["up_ebtyp"] or row["pmp_typ"]),
        axis=1,
    )
    gdf["source_feature_id"] = gdf["ovrg_id"].fillna(gdf["ovrg_idu"]).astype(str)
    gdf["network_kind"] = "AEP"
    gdf["source_layer"] = "AEP/ouvrage_aep.gpkg"
    gdf["feature_role"] = gdf["asset_type_code"].map(lambda code: AEP_ASSET_ROLE_MAP.get(code, ("ouvrage_aep", "support"))[0])
    gdf["criticality"] = gdf["asset_type_code"].map(lambda code: AEP_ASSET_ROLE_MAP.get(code, ("ouvrage_aep", "support"))[1])
    gdf["feature_id"] = [f"aep-asset-{idx + 1}" for idx in range(len(gdf))]

    metric = gdf.to_crs(METRIC_CRS).copy()
    assignments = _asset_assignment_rows(
        metric,
        indexes,
        ["asset_name"],
        use_global_zone_map=True,
        allow_global_sector_map=False,
    )
    gdf = gdf.join(assignments)
    gdf["zone_color"] = gdf["zone_color"].fillna(GRAY_COLOR)
    return gdf


def _prepare_eu_pr_assets(indexes: dict[str, object], notes: dict[str, str]) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(EU_PR_PATH)[
        [
            "eu_pr_id",
            "stpmp_id",
            "pelem_nom",
            "pelem_commune",
            "reseau_nom",
            "reseau_type",
            "pelem_secteur",
            "geometry",
        ]
    ].copy()
    gdf = _valid_geometries(gdf)
    gdf["asset_name"] = gdf["pelem_nom"].map(_clean_text)
    gdf["commune"] = gdf["pelem_commune"].map(_clean_text)
    gdf["asset_type_code"] = gdf["reseau_type"].map(_clean_text)
    gdf["asset_subtype_code"] = gdf["reseau_nom"].map(_clean_text)
    gdf["declared_sector"] = gdf["pelem_secteur"].map(_clean_text)
    gdf["source_feature_id"] = gdf["eu_pr_id"].fillna(gdf["stpmp_id"]).astype(str)
    gdf["network_kind"] = "EU"
    gdf["source_layer"] = "EU/pr.gpkg"
    gdf["feature_role"] = "poste_refoulement"
    gdf["criticality"] = "essential"
    gdf["feature_id"] = [f"eu-pr-{idx + 1}" for idx in range(len(gdf))]
    gdf["type_note"] = notes.get("PR_EU_Gua.reseau_type", "Type d'ouvrage")

    metric = gdf.to_crs(METRIC_CRS).copy()
    assignments = _asset_assignment_rows(
        metric,
        indexes,
        ["declared_sector", "asset_subtype_code", "asset_name"],
        use_global_zone_map=False,
        allow_global_sector_map=True,
    )
    gdf = gdf.join(assignments)
    gdf["zone_color"] = gdf["zone_color"].fillna(GRAY_COLOR)
    return gdf


def _prepare_eu_step_assets(indexes: dict[str, object], notes: dict[str, str]) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(EU_STEP_PATH)[
        [
            "eu_stepn_id",
            "pelem_nom",
            "pelem_commune",
            "pelem_secteur",
            "type_egis",
            "geometry",
        ]
    ].copy()
    gdf = _valid_geometries(gdf)
    gdf["asset_name"] = gdf["pelem_nom"].map(_clean_text)
    gdf["commune"] = gdf["pelem_commune"].map(_clean_text)
    gdf["asset_type_code"] = gdf["type_egis"].map(_clean_text)
    gdf["asset_subtype_code"] = ""
    gdf["declared_sector"] = gdf["pelem_secteur"].map(_clean_text)
    gdf["source_feature_id"] = gdf["eu_stepn_id"].astype(str)
    gdf["network_kind"] = "EU"
    gdf["source_layer"] = "EU/step.gpkg"
    gdf["feature_role"] = "step"
    gdf["criticality"] = "essential"
    gdf["feature_id"] = [f"eu-step-{idx + 1}" for idx in range(len(gdf))]
    gdf["type_note"] = notes.get("STEP_EU_GUA.pelem_secteur", "Secteur hydraulique")

    metric = gdf.to_crs(METRIC_CRS).copy()
    assignments = _asset_assignment_rows(
        metric,
        indexes,
        ["declared_sector", "asset_name"],
        use_global_zone_map=False,
        allow_global_sector_map=True,
    )
    gdf = gdf.join(assignments)
    gdf["zone_color"] = gdf["zone_color"].fillna(GRAY_COLOR)
    return gdf


def _build_zone_polygons(lines: gpd.GeoDataFrame, assets: gpd.GeoDataFrame, population_areas: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    lines_metric = lines.to_crs(METRIC_CRS).copy()
    assets_metric = assets.to_crs(METRIC_CRS).copy()
    assets_metric["asset_point_geom"] = assets_metric.geometry.apply(_representative_point)
    group_field = _require_zone_component_key_field(lines_metric, context="hydraulic polygon build")
    _require_zone_component_key_field(assets_metric, context="hydraulic polygon build assets")

    rows: list[dict[str, object]] = []
    for component_key, line_group in lines_metric[lines_metric[group_field].notna()].groupby(group_field, dropna=False):
        zone_lines = line_group.copy()
        zone_assets = assets_metric[assets_metric[group_field] == component_key].copy()
        line_geoms = [geom.simplify(20.0, preserve_topology=False) for geom in zone_lines.geometry if geom is not None and not geom.is_empty]
        if not line_geoms:
            continue
        merged_lines = unary_union(line_geoms)
        if merged_lines is None or merged_lines.is_empty:
            continue

        zone_line_length_m = float(zone_lines["line_length_m"].sum())
        buffer_m = _polygon_buffer_distance(zone_line_length_m)
        simplify_m = _polygon_simplify_distance(buffer_m)
        corridor = merged_lines.buffer(buffer_m)

        included_asset_geoms = []
        for asset_row in zone_assets.itertuples(index=False):
            asset_geom = asset_row.asset_point_geom
            if asset_geom is None or asset_geom.is_empty:
                continue
            include_distance = _polygon_asset_include_distance(getattr(asset_row, "method", None), getattr(asset_row, "confidence", None))
            if include_distance <= 0.0:
                continue
            asset_distance = float(asset_geom.distance(merged_lines))
            if asset_distance <= include_distance:
                included_asset_geoms.append(asset_geom)

        polygon = corridor
        if included_asset_geoms:
            hull_input = unary_union([merged_lines, *included_asset_geoms])
            try:
                hull = concave_hull(hull_input, ratio=_polygon_hull_ratio(zone_line_length_m, len(included_asset_geoms)))
            except Exception:
                hull = hull_input.convex_hull
            if hull is not None and not hull.is_empty and hull.geom_type in {"Polygon", "MultiPolygon"}:
                hull_zone = hull.buffer(buffer_m * POLYGON_HULL_BUFFER_FACTOR)
                polygon = unary_union([corridor, hull_zone])
                polygon = polygon.intersection(corridor.buffer(buffer_m * POLYGON_HULL_CLIP_FACTOR))

        polygon = polygon.simplify(simplify_m, preserve_topology=True)
        if polygon.is_empty:
            polygon = corridor
        population_added_area_km2 = 0.0
        population_patch_count = 0
        population_expansion_distance_m = _population_expansion_distance(zone_line_length_m)
        polygon, population_added_area_km2, population_patch_count = _expand_polygon_to_population(
            polygon,
            corridor,
            population_areas,
            expansion_distance_m=population_expansion_distance_m,
            simplify_m=simplify_m,
        )
        polygon = polygon.buffer(0)

        confidence_values = [float(val) for val in zone_assets["confidence"].tolist() if val is not None]
        confidence_values.extend(float(val) for val in zone_lines["zone_confidence"].tolist() if val is not None)
        asset_methods = Counter(str(val) for val in zone_assets["method"].tolist() if val)

        sample = zone_lines.iloc[0]
        rows.append(
            {
                "zone_fid": len(rows) + 1,
                "zone_uid": sample["zone_uid"],
                "geometry_part_id": sample.get("geometry_part_id"),
                "zone_component_key": component_key,
                "zone_component_label": sample.get("zone_component_label") or sample["zone_label"],
                "zone_name": sample["zone_name"],
                "zone_label": sample["zone_label"],
                "zone_color": sample["zone_color"],
                "network_kind": sample["network_kind"],
                "zone_basis": sample["zone_basis"],
                "zone_basis_note": sample["zone_basis_note"],
                "line_count": int(len(zone_lines)),
                "line_km": round(float(zone_lines["line_length_m"].sum()) / 1000.0, 3),
                "asset_count": int(len(zone_assets)),
                "critical_asset_count": int((zone_assets["criticality"] == "essential").sum()),
                "asset_conf_mean": round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0,
                "asset_low_conf_count": int((zone_assets["confidence"].fillna(0.0) < 0.5).sum()),
                "asset_method_counts": json.dumps(asset_methods, ensure_ascii=True, sort_keys=True),
                "population_added_area_km2": population_added_area_km2,
                "population_patch_count": population_patch_count,
                "polygon_method": "buffered_lines_clipped_hull",
                "geometry": polygon,
            }
        )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _summary_table(lines: gpd.GeoDataFrame, assets: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    group_field = _require_zone_component_key_field(polygons, context="hydraulic summary table polygons")
    _require_zone_component_key_field(lines, context="hydraulic summary table lines")
    _require_zone_component_key_field(assets, context="hydraulic summary table assets")
    assigned_assets = assets[assets[group_field].notna()].copy()
    assigned_lines = lines[lines[group_field].notna()].copy()
    assets_grouped = assigned_assets.groupby(group_field, dropna=True)
    line_grouped = assigned_lines.groupby(group_field, dropna=True)
    polygon_lookup = polygons.set_index(group_field) if not polygons.empty else pd.DataFrame().set_index(pd.Index([], name=group_field))
    zone_ids = set(line_grouped.groups.keys()) | set(assets_grouped.groups.keys())

    for zone_component_key in sorted(zone_ids, key=lambda value: str(value)):
        if zone_component_key is None:
            continue
        line_group = line_grouped.get_group(zone_component_key) if zone_component_key in line_grouped.groups else lines.iloc[0:0]
        asset_group = assets_grouped.get_group(zone_component_key) if zone_component_key in assets_grouped.groups else assets.iloc[0:0]
        if not line_group.empty:
            sample = line_group.iloc[0]
        elif not asset_group.empty:
            sample = asset_group.iloc[0]
        else:
            continue
        area_km2 = 0.0
        zone_fid = None
        if zone_component_key in polygon_lookup.index:
            polygon_row = polygon_lookup.loc[zone_component_key]
            if isinstance(polygon_row, pd.DataFrame):
                polygon_row = polygon_row.iloc[0]
            area_km2 = round(float(polygon_row.geometry.area) / 1_000_000.0, 4)
            zone_fid = int(polygon_row["zone_fid"])
        line_km = round(float(line_group["line_length_m"].sum()) / 1000.0, 3) if not line_group.empty else 0.0
        coherence_ratio = round(area_km2 / max(line_km, 0.001), 4) if area_km2 else 0.0
        method_counts = Counter(str(value) for value in asset_group["method"].tolist() if value)
        source_asset_count = int(
            (
                asset_group["feature_role"].fillna("").isin(["captage_aep"]) |
                (asset_group["asset_type_code"].fillna("") == "CAP")
            ).sum()
        ) if not asset_group.empty else 0
        records.append(
            {
                "zone_fid": zone_fid,
                "zone_uid": sample.get("zone_uid"),
                "geometry_part_id": sample.get("geometry_part_id"),
                "zone_component_key": zone_component_key,
                "zone_component_label": sample.get("zone_component_label") or sample.get("zone_label"),
                "zone_label": sample.get("zone_label"),
                "network_kind": sample.get("network_kind"),
                "zone_color": sample.get("zone_color"),
                "line_count": int(len(line_group)),
                "line_km": line_km,
                "asset_count": int(len(asset_group)),
                "critical_asset_count": int((asset_group["criticality"] == "essential").sum()) if not asset_group.empty else 0,
                "source_asset_count": source_asset_count,
                "asset_method_counts": json.dumps(method_counts, ensure_ascii=True, sort_keys=True),
                "polygon_area_km2": area_km2,
                "coherence_ratio": coherence_ratio,
                "population_added_area_km2": round(float(polygon_row.get("population_added_area_km2", 0.0)), 4) if zone_component_key in polygon_lookup.index else 0.0,
                "population_patch_count": int(polygon_row.get("population_patch_count", 0) or 0) if zone_component_key in polygon_lookup.index else 0,
            }
        )
    return pd.DataFrame(records)


def _rework_registry_issue(row: pd.Series) -> tuple[str, str, str, str] | None:
    line_km = float(row.get("line_km") or 0.0)
    area_km2 = float(row.get("polygon_area_km2") or 0.0)
    asset_count = int(row.get("asset_count") or 0)
    network_kind = str(row.get("network_kind") or "")
    ratio = float(row.get("coherence_ratio") or 0.0)
    method_counts_raw = row.get("asset_method_counts") or "{}"
    try:
        method_counts = json.loads(method_counts_raw)
    except Exception:
        method_counts = {}
    methods = list(method_counts)
    has_remote_fallback = any("territory" in method or method.endswith("_any") for method in methods)
    has_local_fallback = any("commune" in method or "manager" in method for method in methods)

    if line_km <= 0.0 and asset_count > 0:
        notes = f"{asset_count} asset(s) assigned without any line support"
        return ("asset_only_system", "track_without_polygon", "track_only", notes)
    if network_kind == "AEP" and line_km >= AEP_SOURCE_REQUIRED_LINE_KM and int(row.get("source_asset_count") or 0) == 0:
        notes = "AEP component has network lines but no associated captage/source candidate"
        return ("source_required", "review_source_assignment", "candidate_review", notes)
    if line_km <= REWORK_MICRO_NETWORK_LINE_KM and area_km2 >= REWORK_MICRO_NETWORK_AREA_KM2:
        notes = f"Micro-network envelope ({line_km:.3f} km of lines for {area_km2:.4f} km2)"
        return ("micro_network_envelope", "trim_polygon", "candidate_review", notes)

    ratio_threshold = REWORK_RATIO_THRESHOLD_AEP if network_kind == "AEP" else REWORK_RATIO_THRESHOLD_EU
    if ratio >= ratio_threshold:
        notes = f"Coherence ratio {ratio:.3f} exceeds threshold {ratio_threshold:.2f}"
        return ("oversized_polygon", "split_or_trim_polygon", "candidate_review", notes)
    if has_remote_fallback:
        notes = "Remote fallback assignment present in asset linkage"
        return ("weak_fallback_assignment", "review_assignment_and_polygon", "candidate_review", notes)
    if has_local_fallback and ratio >= ratio_threshold * 0.75:
        notes = "Local fallback assignment likely inflates the polygon envelope"
        return ("fallback_inflated_polygon", "trim_polygon", "candidate_review", notes)
    return None


def _rework_registry_table(territory: str, bundle: str, zone_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in zone_summary.iterrows():
        issue = _rework_registry_issue(row)
        if issue is None:
            continue
        issue_type, planned_action, change_status, notes = issue
        ratio = float(row.get("coherence_ratio") or 0.0)
        has_polygon_fid = pd.notna(row.get("zone_fid"))
        priority_band = "medium"
        if issue_type == "asset_only_system" or ratio >= 1.5:
            priority_band = "critical"
        elif issue_type in {"oversized_polygon", "micro_network_envelope", "source_required"} or ratio >= 0.9:
            priority_band = "high"
        rows.append(
            {
                "territory": territory,
                "bundle": bundle,
                "has_polygon_fid": bool(has_polygon_fid),
                "fid": str(int(row["zone_fid"])) if has_polygon_fid else "",
                "zone_uid": row["zone_uid"],
                "geometry_part_id": row.get("geometry_part_id"),
                "zone_component_key": row.get("zone_component_key"),
                "zone_component_label": row.get("zone_component_label"),
                "zone_label": row["zone_label"],
                "network_kind": row["network_kind"],
                "line_count": int(row["line_count"]),
                "line_km": float(row["line_km"]),
                "asset_count": int(row["asset_count"]),
                "source_asset_count": int(row.get("source_asset_count") or 0),
                "polygon_area_km2": float(row["polygon_area_km2"]),
                "coherence_ratio": ratio,
                "population_added_area_km2": float(row.get("population_added_area_km2") or 0.0),
                "population_patch_count": int(row.get("population_patch_count") or 0),
                "issue_type": issue_type,
                "planned_action": planned_action,
                "change_status": change_status,
                "priority_band": priority_band,
                "notes": notes,
            }
        )
    columns = [
        "territory",
        "bundle",
        "has_polygon_fid",
        "fid",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_label",
        "network_kind",
        "line_count",
        "line_km",
        "asset_count",
        "source_asset_count",
        "polygon_area_km2",
        "coherence_ratio",
        "population_added_area_km2",
        "population_patch_count",
        "issue_type",
        "planned_action",
        "change_status",
        "priority_band",
        "notes",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["priority_band", "coherence_ratio", "territory", "bundle", "zone_uid"],
        ascending=[True, False, True, True, True],
    )


def _write_rework_registry(path: Path, registry: pd.DataFrame) -> None:
    registry.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def _refresh_combined_rework_registry() -> None:
    registry_paths = [path for path in sorted(OUTPUT_DIR.glob("*_rework_registry.csv")) if path.name != COMBINED_REWORK_REGISTRY.name]
    if not registry_paths:
        return
    frames = [pd.read_csv(path, dtype={"fid": "string"}) for path in registry_paths if path.exists()]
    if not frames:
        return
    combined = pd.concat(frames, ignore_index=True)
    if "fid" in combined.columns:
        combined["fid"] = combined["fid"].fillna("")
    combined.to_csv(COMBINED_REWORK_REGISTRY, index=False, quoting=csv.QUOTE_MINIMAL)


def _write_summary_markdown(
    path: Path,
    notes: dict[str, str],
    lines: gpd.GeoDataFrame,
    assets: gpd.GeoDataFrame,
    zone_summary: pd.DataFrame,
    output_gpkg: Path,
    style_files: dict[str, Path],
) -> None:
    assets_assigned = int(assets["zone_uid"].notna().sum())
    assets_total = int(len(assets))
    aep_zones = int(zone_summary[zone_summary["network_kind"] == "AEP"].shape[0])
    eu_zones = int(zone_summary[zone_summary["network_kind"] == "EU"].shape[0])
    method_counts = (
        assets.groupby(["network_kind", "method"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["network_kind", "count", "method"], ascending=[True, False, True])
    )

    lines_out: list[str] = [
        "# Estimation initiale des zonages hydrauliques - Guadeloupe",
        "",
        f"GeoPackage QGIS: {output_gpkg}",
        f"CRS de sortie: {METRIC_CRS}",
        "",
        "## Methode",
        "",
        "- AEP: les troncons sont zonés directement a partir de pelem_zonehydraulique.",
        "- EU: les troncons sont zonés directement a partir de pelem_secteur, interprete ici comme un secteur hydraulique local par commune.",
        "- Ouvrages: rattachement par nom/commune d'abord, puis par troncon du meme reseau le plus proche en dernier recours.",
        "- Polygones: enveloppe concave des troncons et ouvrages rattaches, puis leger tampon pour une lecture plus facile dans QGIS.",
        "",
        "## Resultats",
        "",
        f"- Zones AEP estimees: {aep_zones}",
        f"- Zones EU estimees: {eu_zones}",
        f"- Troncons hydrauliques exportes: {len(lines)}",
        f"- Ouvrages exportes: {assets_total}",
        f"- Ouvrages avec zone attribuee: {assets_assigned}/{assets_total}",
        "",
        "## Affectation des ouvrages",
        "",
    ]

    for _, row in method_counts.iterrows():
        lines_out.append(f"- {row['network_kind']} / {row['method']}: {int(row['count'])}")

    lines_out.extend(
        [
            "",
            "## Ouverture dans QGIS",
            "",
            "- Charger les couches hydraulic_zones, hydraulic_lines, hydraulic_assets et hydraulic_captages depuis le GeoPackage.",
            "- Les styles par defaut sont embarques dans le GeoPackage pour hydraulic_zones, hydraulic_lines et hydraulic_captages.",
            f"- Des fichiers QML sont aussi ecrits a cote du GeoPackage: {style_files['hydraulic_zones']}, {style_files['hydraulic_lines']}, {style_files['hydraulic_captages']}",
            "- hydraulic_zones et hydraulic_lines utilisent une couleur differente par zone.",
            "- hydraulic_captages met en evidence les points de captage AEP sous forme de grande croix, coloree par zone.",
            "- Utiliser zone_uid ou zone_label pour les etiquettes et pour les filtres de verification.",
            "",
            "## Notes dictionnaire",
            "",
        ]
    )
    if notes:
        for key in sorted(notes):
            lines_out.append(f"- {key}: {notes[key]}")
    else:
        lines_out.append("- Aucun extrait de dictionnaire n'a pu etre relu automatiquement au moment de l'export.")

    lines_out.extend(
        [
            "",
            "## Incertitudes principales",
            "",
            "- Les zones AEP sont solides sur les troncons car elles viennent du champ pelem_zonehydraulique deja renseigne dans la couche source.",
            "- Les ouvrages AEP sans correspondance toponymique claire sont rattaches au troncon AEP le plus proche, ce qui reste une approximation fonctionnelle.",
            "- Les zones EU reposent sur pelem_secteur et sur des correspondances de noms reseau/ouvrage; elles doivent etre considerees comme une premiere estimation d'exploitation.",
            "- Les STEP et certains PR gardent une incertitude plus forte quand le nom du reseau ne correspond pas directement au secteur des conduites.",
        ]
    )

    path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def _write_gpkg(
    path: Path,
    lines: gpd.GeoDataFrame,
    assets: gpd.GeoDataFrame,
    captages: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
) -> None:
    if path.exists():
        path.unlink()

    line_cols = [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "source_layer",
        "feature_role",
        "commune",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_name",
        "zone_label",
        "zone_color",
        "zone_basis",
        "zone_basis_note",
        "sector_name",
        "zone_method",
        "zone_confidence",
        "line_length_m",
        "geometry",
    ]
    asset_cols = [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "source_layer",
        "feature_role",
        "criticality",
        "commune",
        "asset_name",
        "asset_type_code",
        "asset_subtype_code",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_name",
        "zone_label",
        "zone_color",
        "zone_basis",
        "zone_basis_note",
        "method",
        "confidence",
        "distance_m",
        "matched_field",
        "matched_value",
        "geometry",
    ]
    polygon_cols = [
        "zone_fid",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_name",
        "zone_label",
        "zone_color",
        "network_kind",
        "zone_basis",
        "zone_basis_note",
        "line_count",
        "line_km",
        "asset_count",
        "critical_asset_count",
        "asset_conf_mean",
        "asset_low_conf_count",
        "asset_method_counts",
        "population_added_area_km2",
        "population_patch_count",
        "polygon_method",
        "geometry",
    ]
    captage_cols = [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "source_layer",
        "feature_role",
        "criticality",
        "commune",
        "asset_name",
        "asset_type_code",
        "asset_subtype_code",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_name",
        "zone_label",
        "zone_color",
        "zone_basis",
        "zone_basis_note",
        "method",
        "confidence",
        "distance_m",
        "matched_field",
        "matched_value",
        "geometry",
    ]

    lines[line_cols].to_file(path, layer="hydraulic_lines", driver="GPKG")
    assets[asset_cols].to_file(path, layer="hydraulic_assets", driver="GPKG")
    captages[captage_cols].to_file(path, layer="hydraulic_captages", driver="GPKG")
    polygons[polygon_cols].to_file(path, layer="hydraulic_zones", driver="GPKG")


def _write_csv(path: Path, zone_summary: pd.DataFrame) -> None:
    if zone_summary.empty:
        path.write_text("zone_fid,zone_uid,geometry_part_id,zone_component_key,zone_component_label,zone_label,network_kind,line_count,line_km,asset_count,critical_asset_count,source_asset_count,asset_method_counts,polygon_area_km2,coherence_ratio,population_added_area_km2,population_patch_count\n", encoding="utf-8")
        return
    zone_summary.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def build_outputs(output_gpkg: Path, output_summary: Path, output_csv: Path) -> None:
    _require_geo_deps()
    warnings.filterwarnings("ignore", message="GeoSeries.notna", category=UserWarning)
    warnings.filterwarnings("ignore", message=".*Non-conformant content for record.*", category=RuntimeWarning)

    notes = _dictionary_notes()
    aep_lines, aep_lines_metric, _ = _prepare_aep_lines(notes)
    eu_lines, eu_lines_metric, _ = _prepare_eu_lines(notes)
    all_lines = gpd.GeoDataFrame(pd.concat([aep_lines, eu_lines], ignore_index=True), geometry="geometry", crs=METRIC_CRS)
    all_lines_metric = gpd.GeoDataFrame(pd.concat([aep_lines_metric, eu_lines_metric], ignore_index=True), geometry="geometry", crs=METRIC_CRS)

    aep_indexes = _build_line_indexes(aep_lines_metric)
    eu_indexes = _build_line_indexes(eu_lines_metric)

    aep_assets = _prepare_aep_assets(aep_indexes)
    eu_pr_assets = _prepare_eu_pr_assets(eu_indexes, notes)
    eu_step_assets = _prepare_eu_step_assets(eu_indexes, notes)
    all_assets = gpd.GeoDataFrame(pd.concat([aep_assets, eu_pr_assets, eu_step_assets], ignore_index=True), geometry="geometry", crs=METRIC_CRS)
    all_lines, all_assets, _ = _assign_zone_components(all_lines, all_assets)
    captages = all_assets[all_assets["feature_role"] == "captage_aep"].copy()
    population_areas = _load_population_areas(GUA_POPULATION_RASTER, all_lines)

    polygons = _build_zone_polygons(all_lines, all_assets, population_areas=population_areas)
    zone_summary = _summary_table(all_lines, all_assets, polygons)
    rework_registry = _rework_registry_table("guadeloupe", output_gpkg.stem, zone_summary)

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    _write_gpkg(output_gpkg, all_lines, all_assets, captages, polygons)
    style_files = _write_qgis_styles(output_gpkg, all_lines, polygons, captages)
    _write_csv(output_csv, zone_summary)
    _write_rework_registry(OUTPUT_REWORK_REGISTRY, rework_registry)
    _refresh_combined_rework_registry()
    _write_summary_markdown(output_summary, notes, all_lines, all_assets, zone_summary, output_gpkg, style_files)

    print(f"Wrote {output_gpkg}")
    print(f"Wrote {output_csv}")
    print(f"Wrote {OUTPUT_REWORK_REGISTRY}")
    print(f"Wrote {output_summary}")
    for layer_name, style_path in style_files.items():
        print(f"style_{layer_name}={style_path}")
    print(f"line_features={len(all_lines)}")
    print(f"asset_features={len(all_assets)}")
    print(f"captage_features={len(captages)}")
    print(f"zone_polygons={len(polygons)}")
    print(all_assets.groupby(["network_kind", "method"]).size().to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate Guadeloupe hydraulic zones and export QGIS-ready layers.")
    parser.add_argument("--output-subdir", type=str, default="", help="Optional subdirectory under outputs/hydraulic_zoning for GPKG/QML/summary outputs")
    parser.add_argument("--out-gpkg", type=Path, default=OUTPUT_GPKG)
    parser.add_argument("--out-summary", type=Path, default=OUTPUT_SUMMARY)
    parser.add_argument("--out-csv", type=Path, default=OUTPUT_CSV)
    args = parser.parse_args()
    out_gpkg = args.out_gpkg
    out_summary = args.out_summary
    out_csv = args.out_csv
    if args.output_subdir:
        output_dir = OUTPUT_DIR / args.output_subdir
        if args.out_gpkg == OUTPUT_GPKG:
            out_gpkg = output_dir / OUTPUT_GPKG.name
        if args.out_summary == OUTPUT_SUMMARY:
            out_summary = output_dir / OUTPUT_SUMMARY.name
        if args.out_csv == OUTPUT_CSV:
            out_csv = output_dir / OUTPUT_CSV.name
    build_outputs(out_gpkg, out_summary, out_csv)


if __name__ == "__main__":
    main()