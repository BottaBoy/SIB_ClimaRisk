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
    from shapely import concave_hull
    from shapely.ops import unary_union
except Exception:  # pragma: no cover - optional at import time for CLI --help
    concave_hull = None  # type: ignore[assignment]
    unary_union = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "outputs" / "hydraulic_zoning"
OUTPUT_GPKG = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate.gpkg"
OUTPUT_SUMMARY = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate.md"
OUTPUT_CSV = OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_summary.csv"
OUTPUT_QML_STYLES = {
    "hydraulic_zones": OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_hydraulic_zones.qml",
    "hydraulic_lines": OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_hydraulic_lines.qml",
    "hydraulic_captages": OUTPUT_DIR / "guadeloupe_hydraulic_zones_estimate_hydraulic_captages.qml",
}

METRIC_CRS = "EPSG:5490"
GRAY_COLOR = "#8B8F96"

AEP_LINES_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/AEP/cana_aep.gpkg")
AEP_ASSETS_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/AEP/ouvrage_aep.gpkg")
EU_LINES_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/cana_eu.gpkg")
EU_PR_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/pr.gpkg")
EU_STEP_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/step.gpkg")

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

MAX_NEAREST_DISTANCE_LOCAL_M = 4000.0
MAX_NEAREST_DISTANCE_TERRITORY_M = 6000.0
FUZZY_MIN_LEN = 5


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
    base = gdf[gdf["zone_uid"].notna()][["zone_uid", "zone_label", "zone_color"]].drop_duplicates().copy()
    if base.empty:
        return []
    base["zone_label"] = base["zone_label"].fillna(base["zone_uid"])
    base["zone_color"] = base["zone_color"].fillna(GRAY_COLOR)
    rows = [
        {
            "value": str(row.zone_uid),
            "label": str(row.zone_label),
            "color": str(row.zone_color),
        }
        for row in base.sort_values(["zone_label", "zone_uid"]).itertuples(index=False)
    ]
    return rows


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
    zone_categories = _zone_style_categories(polygons)
    line_categories = _zone_style_categories(lines)
    captage_categories = _zone_style_categories(captages)

    qml_map = {
        "hydraulic_zones": _categorized_qml(
            attr="zone_uid",
            geometry_type=2,
            categories=zone_categories,
            symbol_xml_builder=_fill_symbol_xml,
        ),
        "hydraulic_lines": _categorized_qml(
            attr="zone_uid",
            geometry_type=1,
            categories=line_categories,
            symbol_xml_builder=_line_symbol_xml,
        ),
        "hydraulic_captages": _categorized_qml(
            attr="zone_uid",
            geometry_type=0,
            categories=captage_categories,
            symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="cross_fill", size_mm=7.5),
        ),
    }

    for layer_name, qml_path in OUTPUT_QML_STYLES.items():
        qml_path.write_text(qml_map[layer_name] + "\n", encoding="utf-8")

    _embed_qml_styles_in_gpkg(output_gpkg, qml_map)
    return dict(OUTPUT_QML_STYLES)


def _valid_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geometry = gdf.geometry
    return gdf[(~geometry.is_empty) & geometry.notna()].copy()


def _representative_point(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == "Point":
        return geom
    return geom.representative_point()


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


def _build_zone_polygons(lines: gpd.GeoDataFrame, assets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    lines_metric = lines.to_crs(METRIC_CRS).copy()
    assets_metric = assets.to_crs(METRIC_CRS).copy()
    assets_metric["asset_point_geom"] = assets_metric.geometry.apply(_representative_point)

    rows: list[dict[str, object]] = []
    for zone_uid, line_group in lines_metric[lines_metric["zone_uid"].notna()].groupby("zone_uid", dropna=False):
        zone_lines = line_group.copy()
        zone_assets = assets_metric[assets_metric["zone_uid"] == zone_uid].copy()
        line_geoms = [geom.simplify(20.0, preserve_topology=False) for geom in zone_lines.geometry if geom is not None and not geom.is_empty]
        asset_geoms = [geom for geom in zone_assets["asset_point_geom"] if geom is not None and not geom.is_empty]
        geoms = [*line_geoms, *asset_geoms]
        if not geoms:
            continue
        merged = unary_union(geoms)
        try:
            polygon = concave_hull(merged, ratio=0.25)
        except Exception:
            polygon = merged.convex_hull
        if polygon.is_empty or polygon.geom_type not in {"Polygon", "MultiPolygon"}:
            polygon = merged.buffer(150.0)
        else:
            polygon = polygon.buffer(120.0).simplify(30.0, preserve_topology=True)
        if polygon.is_empty:
            polygon = merged.buffer(150.0)
        polygon = polygon.buffer(0)

        confidence_values = [float(val) for val in zone_assets["confidence"].tolist() if val is not None]
        confidence_values.extend(float(val) for val in zone_lines["zone_confidence"].tolist() if val is not None)
        asset_methods = Counter(str(val) for val in zone_assets["method"].tolist() if val)

        sample = zone_lines.iloc[0]
        rows.append(
            {
                "zone_uid": zone_uid,
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
                "polygon_method": "concave_hull_buffer",
                "geometry": polygon,
            }
        )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _summary_table(lines: gpd.GeoDataFrame, assets: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    assigned_assets = assets[assets["zone_uid"].notna()].copy()
    assigned_lines = lines[lines["zone_uid"].notna()].copy()
    assets_grouped = assigned_assets.groupby("zone_uid", dropna=True)
    line_grouped = assigned_lines.groupby("zone_uid", dropna=True)
    polygon_lookup = polygons.set_index("zone_uid") if not polygons.empty else pd.DataFrame().set_index(pd.Index([], name="zone_uid"))
    zone_ids = set(line_grouped.groups.keys()) | set(assets_grouped.groups.keys())

    for zone_uid in sorted(zone_ids, key=lambda value: str(value)):
        if zone_uid is None:
            continue
        line_group = line_grouped.get_group(zone_uid) if zone_uid in line_grouped.groups else lines.iloc[0:0]
        asset_group = assets_grouped.get_group(zone_uid) if zone_uid in assets_grouped.groups else assets.iloc[0:0]
        if not line_group.empty:
            sample = line_group.iloc[0]
        elif not asset_group.empty:
            sample = asset_group.iloc[0]
        else:
            continue
        area_km2 = 0.0
        if zone_uid in polygon_lookup.index:
            area_km2 = round(float(polygon_lookup.loc[zone_uid].geometry.area) / 1_000_000.0, 4)
        method_counts = Counter(str(value) for value in asset_group["method"].tolist() if value)
        records.append(
            {
                "zone_uid": zone_uid,
                "zone_label": sample.get("zone_label"),
                "network_kind": sample.get("network_kind"),
                "zone_color": sample.get("zone_color"),
                "line_count": int(len(line_group)),
                "line_km": round(float(line_group["line_length_m"].sum()) / 1000.0, 3) if not line_group.empty else 0.0,
                "asset_count": int(len(asset_group)),
                "critical_asset_count": int((asset_group["criticality"] == "essential").sum()) if not asset_group.empty else 0,
                "asset_method_counts": json.dumps(method_counts, ensure_ascii=True, sort_keys=True),
                "polygon_area_km2": area_km2,
            }
        )
    return pd.DataFrame(records)


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
        "zone_uid",
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
        path.write_text("zone_uid,zone_label,network_kind,line_count,line_km,asset_count,critical_asset_count,asset_method_counts,polygon_area_km2\n", encoding="utf-8")
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
    captages = all_assets[all_assets["feature_role"] == "captage_aep"].copy()

    polygons = _build_zone_polygons(all_lines_metric, all_assets)
    zone_summary = _summary_table(all_lines, all_assets, polygons)

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    _write_gpkg(output_gpkg, all_lines, all_assets, captages, polygons)
    style_files = _write_qgis_styles(output_gpkg, all_lines, polygons, captages)
    _write_csv(output_csv, zone_summary)
    _write_summary_markdown(output_summary, notes, all_lines, all_assets, zone_summary, output_gpkg, style_files)

    print(f"Wrote {output_gpkg}")
    print(f"Wrote {output_csv}")
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
    parser.add_argument("--out-gpkg", type=Path, default=OUTPUT_GPKG)
    parser.add_argument("--out-summary", type=Path, default=OUTPUT_SUMMARY)
    parser.add_argument("--out-csv", type=Path, default=OUTPUT_CSV)
    args = parser.parse_args()
    build_outputs(args.out_gpkg, args.out_summary, args.out_csv)


if __name__ == "__main__":
    main()