#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import geopandas as gpd
except Exception:  # pragma: no cover
    gpd = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    from shapely.geometry import LineString, Point
except Exception:  # pragma: no cover
    LineString = None  # type: ignore[assignment]
    Point = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "hydraulic_zoning"
DEFAULT_OUTPUT_DIR = OUTPUT_ROOT / "Zonage_V2"
INPUT_WATER_DIR = Path("/home/ubuntu/uploads/Infra_eau_Saint_Barthelemy")
METRIC_CRS = "EPSG:32620"
WGS84 = "EPSG:4326"
CRS_REFERENCE_NOTE = "Reference territory CRS: WGS 84 / UTM zone 20N (EPSG:32620). Any EPSG:3620 mention is treated as a documentation typo."

AEP_LINES_PATH = INPUT_WATER_DIR / "AEP_EAU_Conduites.shp"
EU_LINES_PATH = INPUT_WATER_DIR / "EU_SBH_ASS_Conduites.shp"
AEP_POMPAGE_PATH = INPUT_WATER_DIR / "AEP_EAU_Pompage.shp"
AEP_PRELEVEMENT_PATH = INPUT_WATER_DIR / "AEP_EAU_Prelevement.shp"
AEP_TRAITEMENT_PATH = INPUT_WATER_DIR / "AEP_EAU_Production_Traitement.shp"
AEP_STOCKAGE_PATH = INPUT_WATER_DIR / "AEP_EAU_Stockage.shp"
EU_PR_DBF_PATH = INPUT_WATER_DIR / "EU_SBH_ASS_Pompage.dbf"


def _require_geo_deps() -> None:
    missing: list[str] = []
    if gpd is None:
        missing.append("geopandas")
    if pd is None:
        missing.append("pandas")
    if LineString is None or Point is None:
        missing.append("shapely")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_saint_barthelemy_hydraulic_zones.py: "
            + ", ".join(sorted(set(missing)))
        )


def _clean_text(value: object | None) -> str:
    return str(value or "").strip()


def _slug_text(value: object | None) -> str:
    text = _clean_text(value).lower()
    out = []
    for char in text:
        if char.isalnum():
            out.append(char)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "na"


def _load_vector(path: Path, *, fallback_crs: str = METRIC_CRS) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(fallback_crs)
    elif str(gdf.crs).upper() != fallback_crs:
        gdf = gdf.to_crs(fallback_crs)
    return gdf


def _load_dbf_points(path: Path) -> gpd.GeoDataFrame:
    table = gpd.read_file(path)
    if "X" not in table.columns or "Y" not in table.columns:
        raise ValueError(f"DBF point reconstruction requires X/Y columns: {path}")
    rows = []
    for row in table.itertuples(index=False):
        x = getattr(row, "X", None)
        y = getattr(row, "Y", None)
        if x is None or y is None:
            continue
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            continue
        payload = row._asdict() if hasattr(row, "_asdict") else dict(zip(table.columns, row, strict=False))
        payload["geometry"] = Point(float(x), float(y))
        rows.append(payload)
    if not rows:
        return gpd.GeoDataFrame(columns=list(table.columns) + ["geometry"], geometry="geometry", crs=METRIC_CRS)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _line_length_m(gdf: gpd.GeoDataFrame) -> float:
    return float(gdf.geometry.length.sum()) if not gdf.empty else 0.0


@dataclass
class ZoneLookup:
    by_node: dict[str, str]
    label_by_key: dict[str, str]
    uid_by_key: dict[str, str]
    component_size_by_key: dict[str, int]
    line_count_by_key: dict[str, int]
    method_by_key: dict[str, str]


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.size: dict[str, int] = {}

    def add(self, item: str) -> None:
        if item in self.parent:
            return
        self.parent[item] = item
        self.size[item] = 1

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if self.size[root_left] < self.size[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        self.size[root_left] += self.size[root_right]


def _build_zone_lookup(
    lines_gdf: gpd.GeoDataFrame,
    *,
    network_kind: str,
    attribute_field: str | None = None,
) -> ZoneLookup:
    uf = UnionFind()
    component_key_by_root: dict[str, str] = {}
    key_labels: dict[str, str] = {}
    key_uids: dict[str, str] = {}
    key_methods: dict[str, str] = {}
    key_component_sizes: dict[str, int] = {}
    key_line_counts: dict[str, int] = {}
    by_node: dict[str, str] = {}
    line_counts_by_root: dict[str, int] = {}

    for row in lines_gdf.itertuples(index=False):
        from_node = _clean_text(getattr(row, "FROM_NODE", ""))
        to_node = _clean_text(getattr(row, "TO_NODE", ""))
        if not from_node or not to_node:
            continue
        uf.union(from_node, to_node)
        root = uf.find(from_node)
        line_counts_by_root[root] = line_counts_by_root.get(root, 0) + 1

    for node in list(uf.parent):
        root = uf.find(node)
        by_node[node] = root

    attr_counts: dict[str, dict[str, int]] = {}
    if attribute_field and attribute_field in lines_gdf.columns:
        for row in lines_gdf.itertuples(index=False):
            from_node = _clean_text(getattr(row, "FROM_NODE", ""))
            attr_value = _clean_text(getattr(row, attribute_field, ""))
            if not from_node or not attr_value:
                continue
            root = by_node.get(from_node)
            if not root:
                continue
            attr_counts.setdefault(root, {})
            attr_counts[root][attr_value] = attr_counts[root].get(attr_value, 0) + 1

    for root in sorted(set(by_node.values())):
        attr_value = ""
        if root in attr_counts:
            attr_value = max(
                attr_counts[root].items(),
                key=lambda item: (item[1], item[0]),
            )[0]
        if network_kind == "AEP" and attr_value:
            zone_uid = f"AEP_SECT_{_slug_text(attr_value).upper()}"
            zone_key = zone_uid
            zone_label = f"AEP secteur {attr_value}"
            method = "attribute_plus_topology"
        else:
            zone_uid = f"{network_kind}_COMP_{_slug_text(root)[-10:].upper()}"
            zone_key = zone_uid
            zone_label = f"{network_kind} composante {root[-6:]}"
            method = "topology_only"
        component_key_by_root[root] = zone_key
        key_labels[zone_key] = zone_label
        key_uids[zone_key] = zone_uid
        key_methods[zone_key] = method
        key_component_sizes[zone_key] = int(uf.size.get(root, 1))
        key_line_counts[zone_key] = int(line_counts_by_root.get(root, 0))

    resolved_by_node = {
        node: component_key_by_root[root]
        for node, root in by_node.items()
    }
    return ZoneLookup(
        by_node=resolved_by_node,
        label_by_key=key_labels,
        uid_by_key=key_uids,
        component_size_by_key=key_component_sizes,
        line_count_by_key=key_line_counts,
        method_by_key=key_methods,
    )


def _decorate_lines(
    lines_gdf: gpd.GeoDataFrame,
    *,
    network_kind: str,
    lookup: ZoneLookup,
    source_layer: str,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(lines_gdf.itertuples(index=False), start=1):
        from_node = _clean_text(getattr(row, "FROM_NODE", ""))
        to_node = _clean_text(getattr(row, "TO_NODE", ""))
        zone_component_key = lookup.by_node.get(from_node) or lookup.by_node.get(to_node)
        if not zone_component_key:
            zone_component_key = f"{network_kind}_UNASSIGNED_{idx:04d}"
            lookup.label_by_key.setdefault(zone_component_key, f"{network_kind} unassigned {idx}")
            lookup.uid_by_key.setdefault(zone_component_key, zone_component_key)
            lookup.method_by_key.setdefault(zone_component_key, "unassigned_fallback")
            lookup.component_size_by_key.setdefault(zone_component_key, 1)
            lookup.line_count_by_key.setdefault(zone_component_key, 1)
        source_feature_id = (
            _clean_text(getattr(row, "ID_COLL", ""))
            or f"{network_kind.lower()}-line-{idx}"
        )
        rows.append(
            {
                "feature_id": f"{network_kind.lower()}-line-{idx}",
                "source_feature_id": source_feature_id,
                "network_kind": network_kind,
                "feature_role": "canalisation",
                "zone_uid": lookup.uid_by_key.get(zone_component_key, zone_component_key),
                "zone_label": lookup.label_by_key.get(zone_component_key, zone_component_key),
                "zone_component_key": zone_component_key,
                "zone_component_label": lookup.label_by_key.get(zone_component_key, zone_component_key),
                "zone_assignment_method": lookup.method_by_key.get(zone_component_key, "topology_only"),
                "line_length_m": float(getattr(row.geometry, "length", 0.0)),
                "source_layer": source_layer,
                "geometry": row.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _nearest_zone_component(
    geometry,
    lines_gdf: gpd.GeoDataFrame,
    *,
    default_key: str,
) -> tuple[str, float]:
    if lines_gdf.empty or geometry is None or getattr(geometry, "is_empty", False):
        return default_key, math.inf
    distances = lines_gdf.geometry.distance(geometry)
    idx = int(distances.idxmin())
    distance = float(distances.loc[idx])
    key = _clean_text(lines_gdf.loc[idx, "zone_component_key"]) or default_key
    return key, distance


def _decorate_assets(
    assets_gdf: gpd.GeoDataFrame,
    *,
    network_kind: str,
    feature_role: str,
    asset_type_code: str,
    source_layer: str,
    lines_gdf: gpd.GeoDataFrame,
    default_prefix: str,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(assets_gdf.itertuples(index=False), start=1):
        geom = getattr(row, "geometry", None)
        if geom is None or getattr(geom, "is_empty", False):
            continue
        fallback_key = f"{network_kind}_{default_prefix}_{idx:04d}"
        zone_component_key, nearest_distance_m = _nearest_zone_component(geom, lines_gdf, default_key=fallback_key)
        zone_match = lines_gdf[lines_gdf["zone_component_key"] == zone_component_key]
        zone_uid = zone_component_key
        zone_label = zone_component_key
        assignment_method = "nearest_line"
        if not zone_match.empty:
            zone_uid = _clean_text(zone_match.iloc[0].get("zone_uid")) or zone_component_key
            zone_label = _clean_text(zone_match.iloc[0].get("zone_component_label")) or zone_component_key
            assignment_method = f"nearest_line_{int(round(nearest_distance_m))}m"
        label = (
            _clean_text(getattr(row, "LIBELLE_I", ""))
            or _clean_text(getattr(row, "LIBELLE_E", ""))
            or _clean_text(getattr(row, "NUMERO", ""))
            or f"{feature_role}-{idx}"
        )
        source_feature_id = (
            _clean_text(getattr(row, "ID_COLL", ""))
            or _clean_text(getattr(row, "Id_node", ""))
            or f"{default_prefix}-{idx}"
        )
        rows.append(
            {
                "feature_id": f"{default_prefix}-{idx}",
                "source_feature_id": source_feature_id,
                "network_kind": network_kind,
                "feature_role": feature_role,
                "asset_type_code": asset_type_code,
                "asset_name": label,
                "criticality": "best_effort",
                "zone_uid": zone_uid,
                "zone_label": zone_label,
                "zone_component_key": zone_component_key,
                "zone_component_label": zone_label,
                "zone_assignment_method": assignment_method,
                "nearest_line_distance_m": round(nearest_distance_m, 3) if math.isfinite(nearest_distance_m) else None,
                "source_layer": source_layer,
                "geometry": geom,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _build_zone_polygons(
    lines_gdf: gpd.GeoDataFrame,
    assets_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    all_keys = sorted(
        {
            *[str(value) for value in lines_gdf.get("zone_component_key", pd.Series(dtype="object")).dropna().tolist()],
            *[str(value) for value in assets_gdf.get("zone_component_key", pd.Series(dtype="object")).dropna().tolist()],
        }
    )
    for zone_component_key in all_keys:
        zone_lines = lines_gdf[lines_gdf["zone_component_key"] == zone_component_key]
        zone_assets = assets_gdf[assets_gdf["zone_component_key"] == zone_component_key]
        if zone_lines.empty and zone_assets.empty:
            continue
        geometries = []
        if not zone_lines.empty:
            geometries.extend(zone_lines.geometry.tolist())
        if not zone_assets.empty:
            geometries.extend(zone_assets.geometry.tolist())
        geo_series = gpd.GeoSeries(geometries, crs=METRIC_CRS)
        merged = geo_series.union_all() if hasattr(geo_series, "union_all") else geo_series.unary_union
        polygon = merged.buffer(40.0)
        if zone_assets.empty:
            polygon = polygon.buffer(15.0)
        if polygon.is_empty:
            continue
        label_source = zone_lines if not zone_lines.empty else zone_assets
        zone_uid = _clean_text(label_source.iloc[0].get("zone_uid")) or zone_component_key
        zone_label = _clean_text(label_source.iloc[0].get("zone_label")) or zone_component_key
        network_kind = _clean_text(label_source.iloc[0].get("network_kind")) or "WATER"
        rows.append(
            {
                "feature_id": zone_component_key,
                "zone_uid": zone_uid,
                "zone_label": zone_label,
                "zone_component_key": zone_component_key,
                "zone_component_label": zone_label,
                "network_kind": network_kind,
                "feature_role": "canalisation",
                "line_count": int(len(zone_lines)),
                "asset_count": int(len(zone_assets)),
                "critical_asset_count": int(len(zone_assets[zone_assets["feature_role"] != "poste_refoulement"])),
                "polygon_area_km2": round(float(polygon.area) / 1_000_000.0, 6),
                "geometry": polygon,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _input_summary(path: Path, *, expected_crs: str, geometry_expected: bool) -> dict[str, Any]:
    exists = path.exists()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
        "expected_crs": expected_crs,
        "geometry_expected": geometry_expected,
    }
    if not exists:
        return payload
    try:
        if geometry_expected:
            gdf = gpd.read_file(path)
            payload["feature_count"] = int(len(gdf))
            payload["declared_crs"] = None if gdf.crs is None else str(gdf.crs)
        else:
            table = gpd.read_file(path)
            payload["feature_count"] = int(len(table))
            payload["declared_crs"] = None
    except Exception as exc:
        payload["error"] = str(exc)
    return payload


def _quality_payload(
    *,
    aep_lines_raw: gpd.GeoDataFrame,
    eu_lines_raw: gpd.GeoDataFrame,
    aep_lines: gpd.GeoDataFrame,
    eu_lines: gpd.GeoDataFrame,
    assets: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
) -> dict[str, Any]:
    aep_secto = aep_lines_raw["SECTO"].fillna("").astype(str).str.strip() if "SECTO" in aep_lines_raw.columns else pd.Series(dtype="object")
    eu_pr_assets = assets[assets["feature_role"] == "poste_refoulement"] if not assets.empty else assets
    summary = {
        "territory": "saint-barthelemy",
        "crs_reference": METRIC_CRS,
        "crs_reference_note": CRS_REFERENCE_NOTE,
        "aep_line_count": int(len(aep_lines)),
        "eu_line_count": int(len(eu_lines)),
        "zone_count": int(len(zones)),
        "asset_count": int(len(assets)),
        "aep_zone_count": int(len(zones[zones["network_kind"] == "AEP"])),
        "eu_zone_count": int(len(zones[zones["network_kind"] == "EU"])),
        "aep_component_count": int(aep_lines["zone_component_key"].nunique()),
        "eu_component_count": int(eu_lines["zone_component_key"].nunique()),
        "aep_lines_with_secto": int((aep_secto != "").sum()),
        "aep_lines_without_secto": int((aep_secto == "").sum()),
        "aep_secto_coverage_ratio": round(float((aep_secto != "").mean()) if len(aep_secto) else 0.0, 6),
        "eu_pr_count": int(len(eu_pr_assets)),
        "eu_step_count": int(len(assets[assets["feature_role"] == "step"])) if not assets.empty else 0,
        "eu_zoning_quality": "heuristic_topological_non_validated",
        "aep_zoning_quality": "best_effort_attribute_plus_topology",
    }
    assignment_counts = assets["zone_assignment_method"].fillna("unknown").astype(str).value_counts().to_dict() if not assets.empty else {}
    return {
        "summary": summary,
        "asset_zone_assignment_counts": {str(key): int(value) for key, value in assignment_counts.items()},
        "notes": [
            CRS_REFERENCE_NOTE,
            "AEP zoning is best-effort: topology skeleton from FROM_NODE/TO_NODE, sector fields used when available, otherwise nearest-network fallback.",
            "EU zoning is heuristic only: conduites are partitioned by connected components and pumping stations are reconstructed from DBF X/Y coordinates.",
            "No STEP geometry was available in the provided Saint-Barthélemy datasets.",
        ],
        "inputs": {
            "AEP_EAU_Conduites": _input_summary(AEP_LINES_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "EU_SBH_ASS_Conduites": _input_summary(EU_LINES_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "AEP_EAU_Pompage": _input_summary(AEP_POMPAGE_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "AEP_EAU_Prelevement": _input_summary(AEP_PRELEVEMENT_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "AEP_EAU_Production_Traitement": _input_summary(AEP_TRAITEMENT_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "AEP_EAU_Stockage": _input_summary(AEP_STOCKAGE_PATH, expected_crs=METRIC_CRS, geometry_expected=True),
            "EU_SBH_ASS_Pompage": _input_summary(EU_PR_DBF_PATH, expected_crs=METRIC_CRS, geometry_expected=False),
        },
    }


def _write_quality_summary(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    json_path = output_dir / "saint-barthelemy_water_systems_quality.json"
    md_path = output_dir / "saint-barthelemy_water_systems_quality.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# Saint-Barthelemy Water Systems Quality",
        "",
        f"- Territory: `{summary.get('territory', 'saint-barthelemy')}`",
        f"- CRS reference: `{payload.get('crs_reference', METRIC_CRS)}`",
        f"- AEP zoning quality: `{summary.get('aep_zoning_quality', 'unknown')}`",
        f"- EU zoning quality: `{summary.get('eu_zoning_quality', 'unknown')}`",
        f"- AEP lines: `{summary.get('aep_line_count', 0)}`",
        f"- EU lines: `{summary.get('eu_line_count', 0)}`",
        f"- AEP zones: `{summary.get('aep_zone_count', 0)}`",
        f"- EU zones: `{summary.get('eu_zone_count', 0)}`",
        f"- AEP lines with SECTO: `{summary.get('aep_lines_with_secto', 0)}`",
        f"- AEP lines without SECTO: `{summary.get('aep_lines_without_secto', 0)}`",
        f"- Reconstructed EU pumping stations: `{summary.get('eu_pr_count', 0)}`",
        f"- STEP geometries available: `{summary.get('eu_step_count', 0)}`",
        "",
        "## Notes",
    ]
    for note in payload.get("notes") or []:
        lines.append(f"- {note}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def build(output_dir: Path) -> dict[str, Path]:
    _require_geo_deps()
    output_dir.mkdir(parents=True, exist_ok=True)

    aep_lines_raw = _load_vector(AEP_LINES_PATH)
    eu_lines_raw = _load_vector(EU_LINES_PATH)
    aep_lookup = _build_zone_lookup(aep_lines_raw, network_kind="AEP", attribute_field="SECTO")
    eu_lookup = _build_zone_lookup(eu_lines_raw, network_kind="EU", attribute_field=None)

    aep_lines = _decorate_lines(
        aep_lines_raw,
        network_kind="AEP",
        lookup=aep_lookup,
        source_layer=AEP_LINES_PATH.name,
    )
    eu_lines = _decorate_lines(
        eu_lines_raw,
        network_kind="EU",
        lookup=eu_lookup,
        source_layer=EU_LINES_PATH.name,
    )

    aep_pompage = _decorate_assets(
        _load_vector(AEP_POMPAGE_PATH),
        network_kind="AEP",
        feature_role="pompage_aep",
        asset_type_code="CAP",
        source_layer=AEP_POMPAGE_PATH.name,
        lines_gdf=aep_lines,
        default_prefix="aep-pompage",
    )
    aep_prelevement = _decorate_assets(
        _load_vector(AEP_PRELEVEMENT_PATH),
        network_kind="AEP",
        feature_role="captage_aep",
        asset_type_code="CAP",
        source_layer=AEP_PRELEVEMENT_PATH.name,
        lines_gdf=aep_lines,
        default_prefix="aep-prelevement",
    )
    aep_traitement = _decorate_assets(
        _load_vector(AEP_TRAITEMENT_PATH),
        network_kind="AEP",
        feature_role="upep_aep",
        asset_type_code="TRAIT",
        source_layer=AEP_TRAITEMENT_PATH.name,
        lines_gdf=aep_lines,
        default_prefix="aep-traitement",
    )
    aep_stockage = _decorate_assets(
        _load_vector(AEP_STOCKAGE_PATH),
        network_kind="AEP",
        feature_role="reservoir_aep",
        asset_type_code="CUV",
        source_layer=AEP_STOCKAGE_PATH.name,
        lines_gdf=aep_lines,
        default_prefix="aep-stockage",
    )
    eu_pr = _decorate_assets(
        _load_dbf_points(EU_PR_DBF_PATH),
        network_kind="EU",
        feature_role="poste_refoulement",
        asset_type_code="",
        source_layer=EU_PR_DBF_PATH.name,
        lines_gdf=eu_lines,
        default_prefix="eu-pr",
    )

    hydraulic_lines = pd.concat([aep_lines, eu_lines], ignore_index=True)
    hydraulic_assets = pd.concat(
        [aep_pompage, aep_prelevement, aep_traitement, aep_stockage, eu_pr],
        ignore_index=True,
    )
    hydraulic_lines_gdf = gpd.GeoDataFrame(hydraulic_lines, geometry="geometry", crs=METRIC_CRS)
    hydraulic_assets_gdf = gpd.GeoDataFrame(hydraulic_assets, geometry="geometry", crs=METRIC_CRS)
    hydraulic_zones_gdf = _build_zone_polygons(hydraulic_lines_gdf, hydraulic_assets_gdf)

    gpkg_path = output_dir / "saint-barthelemy_water_systems_estimate.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()
    hydraulic_lines_gdf.to_file(gpkg_path, layer="hydraulic_lines", driver="GPKG")
    hydraulic_assets_gdf.to_file(gpkg_path, layer="hydraulic_assets", driver="GPKG")
    hydraulic_zones_gdf.to_file(gpkg_path, layer="hydraulic_zones", driver="GPKG")

    quality_payload = _quality_payload(
        aep_lines_raw=aep_lines_raw,
        eu_lines_raw=eu_lines_raw,
        aep_lines=hydraulic_lines_gdf[hydraulic_lines_gdf["network_kind"] == "AEP"].copy(),
        eu_lines=hydraulic_lines_gdf[hydraulic_lines_gdf["network_kind"] == "EU"].copy(),
        assets=hydraulic_assets_gdf,
        zones=hydraulic_zones_gdf,
    )
    quality_json_path, quality_md_path = _write_quality_summary(quality_payload, output_dir)

    return {
        "gpkg": gpkg_path,
        "quality_json": quality_json_path,
        "quality_md": quality_md_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build best-effort hydraulic zoning layers for Saint-Barthélemy water systems."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for the GeoPackage and quality summary files.",
    )
    args = parser.parse_args()
    outputs = build(Path(args.output_dir))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
