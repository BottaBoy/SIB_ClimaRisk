#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import warnings
from collections import Counter
from pathlib import Path

try:
    import geopandas as gpd
except Exception:  # pragma: no cover
    gpd = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]

from build_guadeloupe_hydraulic_zones import (
    GRAY_COLOR,
    METRIC_CRS,
    _assign_zone_components,
    _build_zone_polygons,
    _categorized_qml,
    _clean_text,
    _embed_qml_styles_in_gpkg,
    _fill_symbol_xml,
    _line_symbol_xml,
    _load_population_areas,
    _marker_symbol_xml,
    _normalize_text,
    _refresh_combined_rework_registry,
    _rework_registry_table,
    _representative_point,
    _require_geo_deps,
    _stable_color,
    _summary_table,
    _valid_geometries,
    _write_rework_registry,
    _zone_style_categories,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "outputs" / "hydraulic_zoning"

AEP_OUTPUT_GPKG = OUTPUT_DIR / "martinique_aep_hydraulic_zones_estimate.gpkg"
AEP_OUTPUT_SUMMARY = OUTPUT_DIR / "martinique_aep_hydraulic_zones_estimate.md"
AEP_OUTPUT_CSV = OUTPUT_DIR / "martinique_aep_hydraulic_zones_estimate_summary.csv"
AEP_OUTPUT_REWORK_REGISTRY = OUTPUT_DIR / "martinique_aep_hydraulic_zones_estimate_rework_registry.csv"

MIXED_OUTPUT_GPKG = OUTPUT_DIR / "martinique_water_systems_estimate.gpkg"
MIXED_OUTPUT_SUMMARY = OUTPUT_DIR / "martinique_water_systems_estimate.md"
MIXED_OUTPUT_CSV = OUTPUT_DIR / "martinique_water_systems_estimate_summary.csv"
MIXED_OUTPUT_REWORK_REGISTRY = OUTPUT_DIR / "martinique_water_systems_estimate_rework_registry.csv"
MTQ_POPULATION_RASTER = Path("/home/ubuntu/uploads/Population/mtq_pop_2020_CN_100m_R2025A_v1.tif")

AEP_LINE_SOURCES = [
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Reseaux/cacem_aep_cana.shp"),
        "fallback_path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Réseaux/cacem_aep_cana.shp"),
        "manager_key": "CACEM",
        "source_layer": "AEP/Reseaux/cacem_aep_cana.shp",
        "zone_field": "sect_dis",
        "commune_field": "ville",
        "commune_code_field": "codeinsee",
        "network_field": "type_resea",
        "id_field": "id",
        "basis_note": "Secteur de distribution (champ sect_dis)",
    },
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Reseaux/caesm_aep_cana.shp"),
        "fallback_path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Réseaux/caesm_aep_cana.shp"),
        "manager_key": "CAESM",
        "source_layer": "AEP/Reseaux/caesm_aep_cana.shp",
        "zone_field": "SECTEUR",
        "commune_field": None,
        "commune_code_field": "CODINSEE",
        "network_field": "RESEAU",
        "id_field": "NUMERO",
        "basis_note": "Secteur hydraulique (champ SECTEUR)",
    },
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Reseaux/capnord_aep_cana.shp"),
        "fallback_path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Réseaux/capnord_aep_cana.shp"),
        "manager_key": "CAP_NORD",
        "source_layer": "AEP/Reseaux/capnord_aep_cana.shp",
        "zone_field": "SECTEUR",
        "commune_field": None,
        "commune_code_field": "CODINSEE",
        "network_field": "RESEAU",
        "id_field": "NUMERO",
        "basis_note": "Secteur hydraulique (champ SECTEUR)",
    },
]

UPEP_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Usines/UPEP_2017.shp")
CAPTAGES_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Martinique/AEP/Forages/AEP_CAPTAGES_FORAGES_2024.shp")

EU_STEP_PUBLIC_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/STEP/steu_communales.shp")
EU_PR_PATH = Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/Poste de refoulement/Postes de refoulement_2024.shp")

EU_LINE_SOURCES = [
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/Reseaux/CACEM_reseau_eu.shp"),
        "territory_key": "CACEM",
        "source_layer": "Assainissement/Reseaux/CACEM_reseau_eu.shp",
        "commune_field": None,
        "commune_code_field": "codeinsee",
        "network_field": None,
    },
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/Reseaux/CAESM_reseau_eu.shp"),
        "territory_key": "CAESM",
        "source_layer": "Assainissement/Reseaux/CAESM_reseau_eu.shp",
        "commune_field": None,
        "commune_code_field": None,
        "network_field": "RESEAU",
    },
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/Reseaux/SCISM_reseau_eu.shp"),
        "territory_key": "CAP_NORD",
        "source_layer": "Assainissement/Reseaux/SCISM_reseau_eu.shp",
        "commune_field": None,
        "commune_code_field": None,
        "network_field": None,
    },
    {
        "path": Path("/home/ubuntu/uploads/Infra_Eau_Martinique/Assainissement/Reseaux/SEA_reseau_eu.shp"),
        "territory_key": "CAP_NORD",
        "source_layer": "Assainissement/Reseaux/SEA_reseau_eu.shp",
        "commune_field": "COMMUNE",
        "commune_code_field": None,
        "network_field": None,
    },
]

MAX_AEP_NEAREST_MANAGER_COMMUNE_M = 1800.0
MAX_AEP_NEAREST_MANAGER_M = 3500.0
MAX_AEP_NEAREST_ANY_M = 7000.0

MAX_EU_NEAREST_COMMUNE_M = 3500.0
MAX_EU_NEAREST_TERRITORY_M = 8000.0
MAX_EU_NEAREST_ANY_M = 12000.0


def _existing_path(primary: Path, fallback: Path | None = None) -> Path:
    if primary.exists():
        return primary
    if fallback is not None and fallback.exists():
        return fallback
    return primary


def _norm_code(value: object | None) -> str:
    text = _clean_text(value).replace('"', "")
    return _normalize_text(text)


def _manager_key_from_text(value: object | None) -> str | None:
    norm = _normalize_text(value)
    if not norm:
        return None
    if "ODYSSI" in norm or "CACEM" in norm:
        return "CACEM"
    if "CAESM" in norm or "ESPACESUD" in norm:
        return "CAESM"
    if "CAPNORD" in norm or "CAPN" in norm:
        return "CAP_NORD"
    return None


def _aep_line_zone_uid(manager_key: str, zone_name: str, commune: str, commune_code: str) -> str | None:
    zone_norm = _normalize_text(zone_name)
    if not zone_norm:
        return None
    if manager_key == "CACEM":
        commune_norm = _normalize_text(commune) or _normalize_text(commune_code)
        if commune_norm:
            return f"AEP_{manager_key}_{commune_norm}_{zone_norm}"
    return f"AEP_{manager_key}_{zone_norm}"


def _choose_best_mapping(rows: pd.DataFrame, key_cols: list[str], value_col: str, weight_col: str) -> dict[tuple[str, ...], str]:
    if rows.empty:
        return {}
    ordered = rows.sort_values(key_cols + [weight_col], ascending=[True] * len(key_cols) + [False])
    dedup = ordered.drop_duplicates(key_cols)
    mapping: dict[tuple[str, ...], str] = {}
    for row in dedup.itertuples(index=False):
        key = tuple(str(getattr(row, col)) for col in key_cols)
        mapping[key] = str(getattr(row, value_col))
    return mapping


def _build_aep_lookup(lines_metric: gpd.GeoDataFrame) -> dict[str, object]:
    valid = lines_metric[lines_metric["zone_uid"].notna()].copy()
    zone_meta = (
        valid[["zone_uid", "zone_name", "zone_label", "zone_color", "zone_basis", "zone_basis_note", "manager_key"]]
        .drop_duplicates("zone_uid")
        .set_index("zone_uid")
        .to_dict("index")
    )
    zone_lengths = valid.groupby("zone_uid")["line_length_m"].sum().to_dict()

    zone_rows = (
        valid[valid["zone_name_norm"].astype(bool)]
        .groupby(["manager_key", "zone_name_norm", "zone_uid"], dropna=False)["line_length_m"]
        .sum()
        .reset_index()
    )
    zone_name_by_manager = _choose_best_mapping(zone_rows, ["manager_key", "zone_name_norm"], "zone_uid", "line_length_m")
    zone_name_global = _choose_best_mapping(zone_rows, ["zone_name_norm"], "zone_uid", "line_length_m")

    lines_by_manager_commune: dict[tuple[str, str], gpd.GeoDataFrame] = {}
    for (manager_key, commune_norm), group in valid.groupby(["manager_key", "commune_norm"], dropna=False):
        lines_by_manager_commune[(str(manager_key or ""), str(commune_norm or ""))] = group.copy()

    lines_by_manager: dict[str, gpd.GeoDataFrame] = {}
    for manager_key, group in valid.groupby("manager_key", dropna=False):
        lines_by_manager[str(manager_key or "")] = group.copy()

    return {
        "all_lines": valid,
        "zone_meta": zone_meta,
        "zone_lengths": zone_lengths,
        "zone_name_by_manager": zone_name_by_manager,
        "zone_name_global": zone_name_global,
        "lines_by_manager_commune": lines_by_manager_commune,
        "lines_by_manager": lines_by_manager,
    }


def _best_contains_match(candidate: str, mapping: dict[str, str], zone_lengths: dict[str, float]) -> str | None:
    best: tuple[int, float, str] | None = None
    for option_norm, zone_uid in mapping.items():
        if not option_norm:
            continue
        if option_norm in candidate or candidate in option_norm:
            score = (min(len(option_norm), len(candidate)), float(zone_lengths.get(zone_uid, 0.0)), zone_uid)
            if best is None or score > best:
                best = score
    return None if best is None else best[2]


def _aep_match_by_name(candidate_values: list[str], manager_key: str | None, lookup: dict[str, object]) -> dict[str, object] | None:
    zone_meta = dict(lookup["zone_meta"])
    zone_lengths = dict(lookup["zone_lengths"])
    zone_name_by_manager = dict(lookup["zone_name_by_manager"])
    zone_name_global = dict(lookup["zone_name_global"])

    for candidate in candidate_values:
        if not candidate:
            continue
        if manager_key:
            zone_uid = zone_name_by_manager.get((manager_key, candidate))
            if zone_uid:
                meta = dict(zone_meta[zone_uid])
                return {
                    "zone_uid": zone_uid,
                    "zone_name": meta.get("zone_name"),
                    "zone_label": meta.get("zone_label"),
                    "zone_color": meta.get("zone_color", GRAY_COLOR),
                    "zone_basis": meta.get("zone_basis"),
                    "zone_basis_note": meta.get("zone_basis_note"),
                    "method": "exact_zone_name_manager",
                    "confidence": 0.82,
                    "distance_m": None,
                }
        zone_uid = zone_name_global.get((candidate,))
        if zone_uid:
            meta = dict(zone_meta[zone_uid])
            return {
                "zone_uid": zone_uid,
                "zone_name": meta.get("zone_name"),
                "zone_label": meta.get("zone_label"),
                "zone_color": meta.get("zone_color", GRAY_COLOR),
                "zone_basis": meta.get("zone_basis"),
                "zone_basis_note": meta.get("zone_basis_note"),
                "method": "exact_zone_name_global",
                "confidence": 0.74,
                "distance_m": None,
            }

    for candidate in candidate_values:
        if not candidate:
            continue
        if manager_key:
            manager_map = {k[1]: v for k, v in zone_name_by_manager.items() if k[0] == manager_key}
            zone_uid = _best_contains_match(candidate, manager_map, zone_lengths)
            if zone_uid:
                meta = dict(zone_meta[zone_uid])
                return {
                    "zone_uid": zone_uid,
                    "zone_name": meta.get("zone_name"),
                    "zone_label": meta.get("zone_label"),
                    "zone_color": meta.get("zone_color", GRAY_COLOR),
                    "zone_basis": meta.get("zone_basis"),
                    "zone_basis_note": meta.get("zone_basis_note"),
                    "method": "contains_zone_name_manager",
                    "confidence": 0.66,
                    "distance_m": None,
                }
        global_map = {k[0]: v for k, v in zone_name_global.items()}
        zone_uid = _best_contains_match(candidate, global_map, zone_lengths)
        if zone_uid:
            meta = dict(zone_meta[zone_uid])
            return {
                "zone_uid": zone_uid,
                "zone_name": meta.get("zone_name"),
                "zone_label": meta.get("zone_label"),
                "zone_color": meta.get("zone_color", GRAY_COLOR),
                "zone_basis": meta.get("zone_basis"),
                "zone_basis_note": meta.get("zone_basis_note"),
                "method": "contains_zone_name_global",
                "confidence": 0.56,
                "distance_m": None,
            }
    return None


def _aep_nearest_line_assignment(geom, manager_key: str | None, commune_norm: str, lookup: dict[str, object]) -> dict[str, object] | None:
    zone_meta = dict(lookup["zone_meta"])
    point = _representative_point(geom)

    candidate_group = None
    max_distance = MAX_AEP_NEAREST_ANY_M
    method = "nearest_line_any"
    confidence = 0.38
    if manager_key and commune_norm:
        candidate_group = lookup["lines_by_manager_commune"].get((manager_key, commune_norm))
        max_distance = MAX_AEP_NEAREST_MANAGER_COMMUNE_M
        method = "nearest_line_manager_commune"
        confidence = 0.62
    if candidate_group is None or candidate_group.empty:
        if manager_key:
            candidate_group = lookup["lines_by_manager"].get(manager_key)
            max_distance = MAX_AEP_NEAREST_MANAGER_M
            method = "nearest_line_manager"
            confidence = 0.52
    if candidate_group is None or candidate_group.empty:
        candidate_group = lookup["all_lines"]
    if candidate_group is None or candidate_group.empty:
        return None

    distances = candidate_group.geometry.distance(point)
    nearest_idx = distances.idxmin()
    nearest_distance = float(distances.loc[nearest_idx])
    if nearest_distance > max_distance:
        return None
    zone_uid = str(candidate_group.loc[nearest_idx, "zone_uid"])
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
        "distance_m": round(nearest_distance, 2),
    }


def _load_martinique_aep_lines() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, object]]:
    rows: list[gpd.GeoDataFrame] = []
    for src in AEP_LINE_SOURCES:
        path = _existing_path(src["path"], src.get("fallback_path"))
        gdf = gpd.read_file(path)
        gdf = _valid_geometries(gdf)
        metric = gdf.to_crs(METRIC_CRS).copy()
        line_length_m = metric.geometry.length.astype(float)

        commune = gdf[src["commune_field"]].map(_clean_text) if src["commune_field"] in gdf.columns and src["commune_field"] else pd.Series([""] * len(gdf))
        commune_code = gdf[src["commune_code_field"]].astype(str).str.strip() if src["commune_code_field"] in gdf.columns and src["commune_code_field"] else pd.Series([""] * len(gdf))
        zone_name = gdf[src["zone_field"]].map(_clean_text) if src["zone_field"] in gdf.columns else pd.Series([""] * len(gdf))
        network_subtype = gdf[src["network_field"]].map(_clean_text) if src["network_field"] in gdf.columns and src["network_field"] else pd.Series([""] * len(gdf))
        source_id = gdf[src["id_field"]].astype(str) if src["id_field"] in gdf.columns else pd.Series([f"{src['manager_key']}-{idx}" for idx in range(len(gdf))])

        out = gdf[["geometry"]].copy()
        out["feature_id"] = [f"martinique-aep-line-{src['manager_key'].lower()}-{idx + 1}" for idx in range(len(out))]
        out["source_feature_id"] = source_id
        out["network_kind"] = "AEP"
        out["service_scope"] = "hydraulic_zone"
        out["manager_key"] = src["manager_key"]
        out["source_layer"] = src["source_layer"]
        out["feature_role"] = "canalisation"
        out["commune"] = commune
        out["commune_code"] = commune_code
        out["commune_norm"] = out["commune"].map(_normalize_text)
        out["zone_name"] = zone_name
        out["zone_name_norm"] = out["zone_name"].map(_normalize_text)
        out["zone_uid"] = [
            _aep_line_zone_uid(src["manager_key"], zone_name.iloc[i], commune.iloc[i], commune_code.iloc[i])
            for i in range(len(out))
        ]
        out["zone_label"] = out.apply(
            lambda row: f"{src['manager_key']} - {row['zone_name']}" if row["zone_name"] else f"{src['manager_key']} - non affecte",
            axis=1,
        )
        out["zone_color"] = out["zone_uid"].map(_stable_color)
        out["zone_basis"] = src["zone_field"]
        out["zone_basis_note"] = src["basis_note"]
        out["network_subtype"] = network_subtype
        out["zone_method"] = out["zone_uid"].map(lambda value: "source_field" if value else "missing")
        out["zone_confidence"] = out["zone_uid"].map(lambda value: 0.97 if value else 0.0)
        out["line_length_m"] = line_length_m
        rows.append(out)

    all_lines = gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), geometry="geometry", crs=METRIC_CRS)
    all_lines_metric = all_lines.to_crs(METRIC_CRS).copy()
    lookup = _build_aep_lookup(all_lines_metric)
    return all_lines, all_lines_metric, lookup


def _load_martinique_aep_assets(aep_lookup: dict[str, object]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    upep = gpd.read_file(UPEP_PATH)
    upep = _valid_geometries(upep).to_crs(METRIC_CRS)
    upep_rows: list[dict[str, object]] = []
    for idx, row in upep.iterrows():
        asset_name = _clean_text(row.get("UPEP"))
        manager_key = _manager_key_from_text(row.get("BENEF")) or _manager_key_from_text(row.get("EXPL"))
        by_name = _aep_match_by_name([_normalize_text(asset_name)], manager_key, aep_lookup)
        if by_name is None:
            by_name = _aep_nearest_line_assignment(row.geometry, manager_key, "", aep_lookup)
        assignment = by_name or {
            "zone_uid": None,
            "zone_name": None,
            "zone_label": None,
            "zone_color": GRAY_COLOR,
            "zone_basis": None,
            "zone_basis_note": None,
            "method": "unassigned",
            "confidence": 0.0,
            "distance_m": None,
        }
        upep_rows.append(
            {
                "feature_id": f"martinique-upep-{idx + 1}",
                "source_feature_id": asset_name or f"upep-{idx + 1}",
                "network_kind": "AEP",
                "service_scope": "hydraulic_zone",
                "source_layer": "AEP/Usines/UPEP_2017.shp",
                "feature_role": "upep_aep",
                "criticality": "essential",
                "manager_key": manager_key or "",
                "commune": "",
                "commune_code": "",
                "asset_name": asset_name,
                "asset_type_code": "TRAIT",
                "asset_subtype_code": _clean_text(row.get("EXPL")),
                "matched_field": "UPEP",
                "matched_value": asset_name,
                "geometry": row.geometry,
                **assignment,
            }
        )
    upep_gdf = gpd.GeoDataFrame(upep_rows, geometry="geometry", crs=METRIC_CRS)

    upep_zone_by_name = {
        _normalize_text(row.asset_name): {
            "zone_uid": row.zone_uid,
            "zone_name": row.zone_name,
            "zone_label": row.zone_label,
            "zone_color": row.zone_color,
            "zone_basis": row.zone_basis,
            "zone_basis_note": row.zone_basis_note,
            "method": row.method,
            "confidence": float(row.confidence),
        }
        for row in upep_gdf.itertuples(index=False)
        if row.zone_uid
    }

    captages = gpd.read_file(CAPTAGES_PATH)
    captages = _valid_geometries(captages).to_crs(METRIC_CRS)
    captage_rows: list[dict[str, object]] = []
    for idx, row in captages.iterrows():
        asset_name = _clean_text(row.get("CAPTAGE"))
        commune = _clean_text(row.get("COMMUNE"))
        commune_norm = _normalize_text(commune)
        manager_key = _manager_key_from_text(row.get("MO"))
        upep_name = _clean_text(row.get("UPEP"))
        upep_norm = _normalize_text(upep_name)
        assignment = None
        if upep_norm and upep_norm in upep_zone_by_name:
            src = dict(upep_zone_by_name[upep_norm])
            assignment = {
                **src,
                "method": "upep_link_exact",
                "confidence": min(0.9, float(src["confidence"]) + 0.18),
                "distance_m": None,
            }
        if assignment is None:
            assignment = _aep_match_by_name([upep_norm, _normalize_text(asset_name)], manager_key, aep_lookup)
        if assignment is None:
            assignment = _aep_nearest_line_assignment(row.geometry, manager_key, commune_norm, aep_lookup)
        if assignment is None:
            assignment = {
                "zone_uid": None,
                "zone_name": None,
                "zone_label": None,
                "zone_color": GRAY_COLOR,
                "zone_basis": None,
                "zone_basis_note": None,
                "method": "unassigned",
                "confidence": 0.0,
                "distance_m": None,
            }
        captage_rows.append(
            {
                "feature_id": f"martinique-captage-{idx + 1}",
                "source_feature_id": asset_name or f"captage-{idx + 1}",
                "network_kind": "AEP",
                "service_scope": "hydraulic_zone",
                "source_layer": "AEP/Forages/AEP_CAPTAGES_FORAGES_2024.shp",
                "feature_role": "captage_aep",
                "criticality": "essential",
                "manager_key": manager_key or "",
                "commune": commune,
                "commune_code": "",
                "asset_name": asset_name,
                "asset_type_code": _clean_text(row.get("TYPE")) or "CAP",
                "asset_subtype_code": upep_name,
                "matched_field": "UPEP" if upep_name else "CAPTAGE",
                "matched_value": upep_name or asset_name,
                "geometry": row.geometry,
                **assignment,
            }
        )
    captage_gdf = gpd.GeoDataFrame(captage_rows, geometry="geometry", crs=METRIC_CRS)

    all_assets = gpd.GeoDataFrame(pd.concat([upep_gdf, captage_gdf], ignore_index=True), geometry="geometry", crs=METRIC_CRS)
    return all_assets, captage_gdf, upep_gdf


def _public_territory_from_text(value: object | None) -> str | None:
    norm = _normalize_text(value)
    if not norm:
        return None
    if "CACEM" in norm or "ODYSSI" in norm:
        return "CACEM"
    if "CAESM" in norm:
        return "CAESM"
    if "CAPNORD" in norm:
        return "CAP_NORD"
    return None


def _load_public_steps() -> gpd.GeoDataFrame:
    step = gpd.read_file(EU_STEP_PUBLIC_PATH)
    step = _valid_geometries(step).to_crs(METRIC_CRS)
    rows: list[dict[str, object]] = []
    for idx, row in step.iterrows():
        code_norm = _norm_code(row.get("code_steu"))
        commune = _clean_text(row.get("Commune"))
        rows.append(
            {
                "feature_id": f"martinique-step-{idx + 1}",
                "source_feature_id": _clean_text(row.get("code_steu")) or _clean_text(row.get("station")) or f"step-{idx + 1}",
                "network_kind": "EU",
                "service_scope": "functional_system",
                "territory_key": _public_territory_from_text(row.get("maitre_ouv")) or _public_territory_from_text(row.get("exploitant")) or "",
                "source_layer": "Assainissement/STEP/steu_communales.shp",
                "feature_role": "step",
                "criticality": "essential",
                "commune": commune,
                "commune_norm": _normalize_text(commune),
                "commune_code": _clean_text(row.get("cd_insee")),
                "asset_name": _clean_text(row.get("station")),
                "asset_type_code": "STEP",
                "asset_subtype_code": _clean_text(row.get("type_sta")),
                "zone_uid": f"EU_{code_norm or _normalize_text(row.get('station'))}",
                "zone_name": _clean_text(row.get("station")),
                "zone_label": f"{commune} - {_clean_text(row.get('station'))}" if commune else _clean_text(row.get("station")),
                "zone_color": _stable_color(f"EU_{code_norm or _normalize_text(row.get('station'))}"),
                "zone_basis": "code_steu",
                "zone_basis_note": "Systeme fonctionnel EU centre sur la STEP receptrice",
                "method": "source_asset",
                "confidence": 0.98,
                "distance_m": 0.0,
                "matched_field": "code_steu",
                "matched_value": _clean_text(row.get("code_steu")),
                "code_norm": code_norm,
                "name_norm": _normalize_text(row.get("station")),
                "geometry": row.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _build_step_lookup(step_gdf: gpd.GeoDataFrame) -> dict[str, object]:
    code_lookup = {row.code_norm: row.index for row in step_gdf.reset_index().itertuples(index=False) if row.code_norm}
    name_lookup = {row.name_norm: row.index for row in step_gdf.reset_index().itertuples(index=False) if row.name_norm}
    steps_by_commune: dict[str, gpd.GeoDataFrame] = {}
    for commune_norm, group in step_gdf.groupby("commune_norm", dropna=False):
        steps_by_commune[str(commune_norm or "")] = group.copy()
    steps_by_territory: dict[str, gpd.GeoDataFrame] = {}
    for territory_key, group in step_gdf.groupby("territory_key", dropna=False):
        steps_by_territory[str(territory_key or "")] = group.copy()
    return {
        "code_lookup": code_lookup,
        "name_lookup": name_lookup,
        "steps_by_commune": steps_by_commune,
        "steps_by_territory": steps_by_territory,
        "all_steps": step_gdf,
    }


def _step_row_assignment(row, step_gdf: gpd.GeoDataFrame) -> dict[str, object]:
    return {
        "zone_uid": row.zone_uid,
        "zone_name": row.zone_name,
        "zone_label": row.zone_label,
        "zone_color": row.zone_color,
        "zone_basis": row.zone_basis,
        "zone_basis_note": row.zone_basis_note,
        "distance_m": 0.0,
    }


def _nearest_step_assignment(geom, candidates: gpd.GeoDataFrame, method: str, confidence: float, max_distance: float) -> dict[str, object] | None:
    if candidates.empty:
        return None
    point = _representative_point(geom)
    distances = candidates.geometry.distance(point)
    nearest_idx = distances.idxmin()
    nearest_distance = float(distances.loc[nearest_idx])
    if nearest_distance > max_distance:
        return None
    step = candidates.loc[nearest_idx]
    return {
        "zone_uid": step["zone_uid"],
        "zone_name": step["zone_name"],
        "zone_label": step["zone_label"],
        "zone_color": step["zone_color"],
        "zone_basis": step["zone_basis"],
        "zone_basis_note": step["zone_basis_note"],
        "method": method,
        "confidence": confidence,
        "distance_m": round(nearest_distance, 2),
    }


def _assign_pr_to_step(step_gdf: gpd.GeoDataFrame, step_lookup: dict[str, object]) -> gpd.GeoDataFrame:
    pr = gpd.read_file(EU_PR_PATH)
    pr = _valid_geometries(pr).to_crs(METRIC_CRS)
    rows: list[dict[str, object]] = []
    for idx, row in pr.iterrows():
        territory_key = _public_territory_from_text(row.get("moa")) or _public_territory_from_text(row.get("exploitant")) or ""
        commune = _clean_text(row.get("commune"))
        commune_norm = _normalize_text(commune)
        code_norm = _norm_code(row.get("cd_steu"))
        step_name_candidates = [
            _normalize_text(row.get("steu")),
            _normalize_text(row.get("steu.1")),
            _normalize_text(row.get("pr aval")),
        ]

        assignment = None
        if code_norm and code_norm in step_lookup["code_lookup"]:
            step_row = step_gdf.loc[step_lookup["code_lookup"][code_norm]]
            assignment = {
                **_step_row_assignment(step_row, step_gdf),
                "method": "exact_cd_steu",
                "confidence": 0.95,
                "distance_m": 0.0,
            }
        if assignment is None:
            for candidate in step_name_candidates:
                if candidate and candidate in step_lookup["name_lookup"]:
                    step_row = step_gdf.loc[step_lookup["name_lookup"][candidate]]
                    assignment = {
                        **_step_row_assignment(step_row, step_gdf),
                        "method": "exact_step_name",
                        "confidence": 0.86,
                        "distance_m": 0.0,
                    }
                    break
        if assignment is None:
            for candidate in step_name_candidates:
                if not candidate:
                    continue
                best_idx = None
                best_score = None
                for step_idx, step_row in step_gdf.iterrows():
                    step_name_norm = str(step_row["name_norm"])
                    if not step_name_norm:
                        continue
                    if candidate in step_name_norm or step_name_norm in candidate:
                        score = min(len(candidate), len(step_name_norm))
                        if best_score is None or score > best_score:
                            best_score = score
                            best_idx = step_idx
                if best_idx is not None:
                    step_row = step_gdf.loc[best_idx]
                    assignment = {
                        **_step_row_assignment(step_row, step_gdf),
                        "method": "contains_step_name",
                        "confidence": 0.72,
                        "distance_m": 0.0,
                    }
                    break

        if assignment is None and commune_norm:
            candidates = step_lookup["steps_by_commune"].get(commune_norm, step_gdf.iloc[0:0])
            assignment = _nearest_step_assignment(row.geometry, candidates, "nearest_step_same_commune", 0.54, MAX_EU_NEAREST_COMMUNE_M)
        if assignment is None and territory_key:
            candidates = step_lookup["steps_by_territory"].get(territory_key, step_gdf.iloc[0:0])
            assignment = _nearest_step_assignment(row.geometry, candidates, "nearest_step_same_territory", 0.42, MAX_EU_NEAREST_TERRITORY_M)
        if assignment is None and territory_key != "PRIVATE":
            assignment = _nearest_step_assignment(row.geometry, step_lookup["all_steps"], "nearest_step_any", 0.28, MAX_EU_NEAREST_ANY_M)
        if assignment is None:
            assignment = {
                "zone_uid": None,
                "zone_name": None,
                "zone_label": None,
                "zone_color": GRAY_COLOR,
                "zone_basis": None,
                "zone_basis_note": None,
                "method": "unassigned",
                "confidence": 0.0,
                "distance_m": None,
            }

        rows.append(
            {
                "feature_id": f"martinique-pr-{idx + 1}",
                "source_feature_id": _clean_text(row.get("id")) or _clean_text(row.get("poste")) or f"pr-{idx + 1}",
                "network_kind": "EU",
                "service_scope": "functional_system",
                "territory_key": territory_key,
                "source_layer": "Assainissement/Poste de refoulement/Postes de refoulement_2024.shp",
                "feature_role": "poste_refoulement",
                "criticality": "essential",
                "commune": commune,
                "commune_norm": commune_norm,
                "commune_code": _clean_text(row.get("cd_insee")),
                "asset_name": _clean_text(row.get("poste")),
                "asset_type_code": "PR",
                "asset_subtype_code": _clean_text(row.get("exploitant")),
                "matched_field": "steu/cd_steu",
                "matched_value": _clean_text(row.get("cd_steu")) or _clean_text(row.get("steu")) or _clean_text(row.get("steu.1")),
                "geometry": row.geometry,
                **assignment,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def _eu_system_assets(step_gdf: gpd.GeoDataFrame, pr_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(pd.concat([step_gdf, pr_gdf[pr_gdf["zone_uid"].notna()]], ignore_index=True), geometry="geometry", crs=METRIC_CRS)


def _assign_eu_line(geom, territory_key: str, commune: str, commune_code: str, system_assets: gpd.GeoDataFrame) -> dict[str, object]:
    point = _representative_point(geom)
    commune_norm = _normalize_text(commune)
    candidates = system_assets.iloc[0:0]
    method = "nearest_system_any"
    confidence = 0.18
    max_distance = MAX_EU_NEAREST_ANY_M

    if commune_code:
        candidates = system_assets[system_assets["commune_code"].astype(str).str.strip() == commune_code].copy()
        method = "nearest_system_same_commune_code"
        confidence = 0.42
        max_distance = MAX_EU_NEAREST_COMMUNE_M
    elif commune_norm:
        candidates = system_assets[system_assets["commune_norm"] == commune_norm].copy()
        method = "nearest_system_same_commune"
        confidence = 0.38
        max_distance = MAX_EU_NEAREST_COMMUNE_M

    if candidates.empty and territory_key:
        candidates = system_assets[system_assets["territory_key"] == territory_key].copy()
        method = "nearest_system_same_territory"
        confidence = 0.26
        max_distance = MAX_EU_NEAREST_TERRITORY_M
    if candidates.empty:
        candidates = system_assets.copy()

    nearest = _nearest_step_assignment(point, candidates, method, confidence, max_distance)
    if nearest is None:
        return {
            "zone_uid": None,
            "zone_name": None,
            "zone_label": None,
            "zone_color": GRAY_COLOR,
            "zone_basis": None,
            "zone_basis_note": None,
            "method": "unassigned",
            "confidence": 0.0,
            "distance_m": None,
        }
    return nearest


def _load_eu_lines(system_assets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[gpd.GeoDataFrame] = []
    for src in EU_LINE_SOURCES:
        gdf = gpd.read_file(src["path"])
        gdf = _valid_geometries(gdf).to_crs(METRIC_CRS)
        metric = gdf.to_crs(METRIC_CRS)
        line_length_m = metric.geometry.length.astype(float)
        commune = gdf[src["commune_field"]].map(_clean_text) if src["commune_field"] in gdf.columns and src["commune_field"] else pd.Series([""] * len(gdf))
        commune_code = gdf[src["commune_code_field"]].astype(str).str.strip() if src["commune_code_field"] in gdf.columns and src["commune_code_field"] else pd.Series([""] * len(gdf))
        network_subtype = gdf[src["network_field"]].map(_clean_text) if src["network_field"] in gdf.columns and src["network_field"] else pd.Series([""] * len(gdf))

        assigned_rows: list[dict[str, object]] = []
        for idx, row in gdf.iterrows():
            assignment = _assign_eu_line(row.geometry, src["territory_key"], _clean_text(commune.iloc[idx]), _clean_text(commune_code.iloc[idx]), system_assets)
            assigned_rows.append(assignment)

        out = gdf[["geometry"]].copy()
        out["feature_id"] = [f"martinique-eu-line-{src['territory_key'].lower()}-{idx + 1}" for idx in range(len(out))]
        out["source_feature_id"] = [f"{src['territory_key']}-{idx + 1}" for idx in range(len(out))]
        out["network_kind"] = "EU"
        out["service_scope"] = "functional_system"
        out["manager_key"] = src["territory_key"]
        out["source_layer"] = src["source_layer"]
        out["feature_role"] = "canalisation"
        out["commune"] = commune
        out["commune_code"] = commune_code
        out["commune_norm"] = out["commune"].map(_normalize_text)
        out["zone_uid"] = [row["zone_uid"] for row in assigned_rows]
        out["zone_name"] = [row["zone_name"] for row in assigned_rows]
        out["zone_label"] = [row["zone_label"] for row in assigned_rows]
        out["zone_color"] = [row["zone_color"] for row in assigned_rows]
        out["zone_basis"] = [row["zone_basis"] for row in assigned_rows]
        out["zone_basis_note"] = [row["zone_basis_note"] for row in assigned_rows]
        out["network_subtype"] = network_subtype
        out["zone_method"] = [row["method"] for row in assigned_rows]
        out["zone_confidence"] = [row["confidence"] for row in assigned_rows]
        out["line_length_m"] = line_length_m
        rows.append(out)
    return gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), geometry="geometry", crs=METRIC_CRS)


def _line_columns() -> list[str]:
    return [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "service_scope",
        "manager_key",
        "source_layer",
        "feature_role",
        "commune",
        "commune_code",
        "zone_uid",
        "geometry_part_id",
        "zone_component_key",
        "zone_component_label",
        "zone_name",
        "zone_label",
        "zone_color",
        "zone_basis",
        "zone_basis_note",
        "network_subtype",
        "zone_method",
        "zone_confidence",
        "line_length_m",
        "geometry",
    ]


def _asset_columns() -> list[str]:
    return [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "service_scope",
        "territory_key" if "territory_key" in [] else "manager_key",
    ]


def _shared_asset_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    cols = [
        "feature_id",
        "source_feature_id",
        "network_kind",
        "service_scope",
    ]
    if "manager_key" in gdf.columns:
        cols.append("manager_key")
    if "territory_key" in gdf.columns:
        cols.append("territory_key")
    cols.extend(
        [
            "source_layer",
            "feature_role",
            "criticality",
            "commune",
            "commune_code",
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
    )
    return cols


def _polygon_columns() -> list[str]:
    return [
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
        "polygon_method",
        "geometry",
    ]


def _style_file_map(base_output_gpkg: Path, layer_names: list[str]) -> dict[str, Path]:
    return {layer_name: base_output_gpkg.with_name(f"{base_output_gpkg.stem}_{layer_name}.qml") for layer_name in layer_names}


def _write_qgis_styles(base_output_gpkg: Path, layer_defs: dict[str, tuple[gpd.GeoDataFrame, str]]) -> dict[str, Path]:
    style_paths = _style_file_map(base_output_gpkg, list(layer_defs))
    qml_map: dict[str, str] = {}
    for layer_name, (gdf, style_kind) in layer_defs.items():
        categories = _zone_style_categories(gdf)
        style_attr = "zone_component_key" if "zone_component_key" in gdf.columns and gdf["zone_component_key"].notna().any() else "zone_uid"
        if style_kind == "fill":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=2, categories=categories, symbol_xml_builder=_fill_symbol_xml)
        elif style_kind == "line":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=1, categories=categories, symbol_xml_builder=_line_symbol_xml)
        elif style_kind == "captage":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=0, categories=categories, symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="cross_fill", size_mm=7.5))
        elif style_kind == "upep":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=0, categories=categories, symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="triangle", size_mm=6.0))
        elif style_kind == "pr":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=0, categories=categories, symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="diamond", size_mm=5.5))
        elif style_kind == "step":
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=0, categories=categories, symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="square", size_mm=5.8))
        else:
            qml_map[layer_name] = _categorized_qml(attr=style_attr, geometry_type=0, categories=categories, symbol_xml_builder=lambda name, color: _marker_symbol_xml(name, color, marker_name="circle", size_mm=4.0))
        style_paths[layer_name].write_text(qml_map[layer_name] + "\n", encoding="utf-8")
    _embed_qml_styles_in_gpkg(base_output_gpkg, qml_map)
    return style_paths


def _write_bundle(
    output_gpkg: Path,
    output_summary: Path,
    output_csv: Path,
    output_registry: Path,
    lines: gpd.GeoDataFrame,
    assets: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    extra_layers: dict[str, gpd.GeoDataFrame],
    style_kinds: dict[str, str],
    summary_title: str,
    method_notes: list[str],
    uncertainty_notes: list[str],
) -> None:
    if output_gpkg.exists():
        output_gpkg.unlink()
    lines[_line_columns()].to_file(output_gpkg, layer="hydraulic_lines", driver="GPKG")
    assets[_shared_asset_columns(assets)].to_file(output_gpkg, layer="hydraulic_assets", driver="GPKG")
    polygons[_polygon_columns()].to_file(output_gpkg, layer="hydraulic_zones", driver="GPKG")
    for layer_name, gdf in extra_layers.items():
        gdf[_shared_asset_columns(gdf)].to_file(output_gpkg, layer=layer_name, driver="GPKG")

    layer_defs = {
        "hydraulic_zones": (polygons, "fill"),
        "hydraulic_lines": (lines, "line"),
    }
    for layer_name, gdf in extra_layers.items():
        layer_defs[layer_name] = (gdf, style_kinds[layer_name])
    style_paths = _write_qgis_styles(output_gpkg, layer_defs)

    zone_summary = _summary_table(lines, assets, polygons)
    zone_summary.to_csv(output_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    rework_registry = _rework_registry_table("martinique", output_gpkg.stem, zone_summary)
    _write_rework_registry(output_registry, rework_registry)
    _refresh_combined_rework_registry()

    method_counts = (
        assets.groupby(["network_kind", "method"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["network_kind", "count", "method"], ascending=[True, False, True])
    )
    confidence_buckets = pd.cut(
        assets["confidence"].fillna(0.0),
        bins=[-0.001, 0.2, 0.5, 0.8, 1.0],
        labels=["very_low", "low", "medium", "high"],
    )
    confidence_counts = confidence_buckets.value_counts().sort_index()

    lines_out: list[str] = [
        f"# {summary_title}",
        "",
        f"GeoPackage QGIS: {output_gpkg}",
        f"CRS de sortie: {METRIC_CRS}",
        "",
        "## Methode",
        "",
    ]
    for note in method_notes:
        lines_out.append(f"- {note}")

    lines_out.extend(
        [
            "",
            "## Resultats",
            "",
            f"- Zones estimees: {len(polygons)}",
            f"- Troncons exportes: {len(lines)}",
            f"- Ouvrages exportes: {len(assets)}",
            f"- Ouvrages avec zone attribuee: {int(assets['zone_uid'].notna().sum())}/{len(assets)}",
            "",
            "## Confiance des ouvrages",
            "",
        ]
    )
    for label, count in confidence_counts.items():
        lines_out.append(f"- {label}: {int(count)}")

    lines_out.extend(
        [
            "",
            "## Affectation des ouvrages",
            "",
        ]
    )
    for _, row in method_counts.iterrows():
        lines_out.append(f"- {row['network_kind']} / {row['method']}: {int(row['count'])}")

    lines_out.extend(
        [
            "",
            "## Ouverture dans QGIS",
            "",
            "- Charger hydraulic_zones, hydraulic_lines et hydraulic_assets depuis le GeoPackage.",
        ]
    )
    for layer_name in extra_layers:
        lines_out.append(f"- Charger aussi {layer_name} pour les actifs critiques specialises.")
    lines_out.append("- Les styles par defaut sont embarques dans le GeoPackage pour les couches thematiques.")
    for layer_name, style_path in style_paths.items():
        lines_out.append(f"- QML {layer_name}: {style_path}")

    lines_out.extend(
        [
            "",
            "## Incertitudes principales",
            "",
        ]
    )
    for note in uncertainty_notes:
        lines_out.append(f"- {note}")
    output_summary.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def build_outputs(mode: str, output_dir: Path = OUTPUT_DIR) -> None:
    _require_geo_deps()
    warnings.filterwarnings("ignore", message="GeoSeries.notna", category=UserWarning)

    output_dir.mkdir(parents=True, exist_ok=True)
    aep_output_gpkg = output_dir / AEP_OUTPUT_GPKG.name
    aep_output_summary = output_dir / AEP_OUTPUT_SUMMARY.name
    aep_output_csv = output_dir / AEP_OUTPUT_CSV.name
    mixed_output_gpkg = output_dir / MIXED_OUTPUT_GPKG.name
    mixed_output_summary = output_dir / MIXED_OUTPUT_SUMMARY.name
    mixed_output_csv = output_dir / MIXED_OUTPUT_CSV.name

    aep_lines, aep_lines_metric, aep_lookup = _load_martinique_aep_lines()
    aep_assets, aep_captages, aep_upep = _load_martinique_aep_assets(aep_lookup)
    aep_lines, aep_assets, _ = _assign_zone_components(aep_lines, aep_assets)
    aep_captages = aep_assets[aep_assets["feature_role"] == "captage_aep"].copy()
    aep_upep = aep_assets[aep_assets["feature_role"] == "upep_aep"].copy()
    aep_population_areas = _load_population_areas(MTQ_POPULATION_RASTER, aep_lines)
    aep_polygons = _build_zone_polygons(aep_lines, aep_assets, population_areas=aep_population_areas)

    if mode in {"aep", "both"}:
        _write_bundle(
            aep_output_gpkg,
            aep_output_summary,
            aep_output_csv,
            AEP_OUTPUT_REWORK_REGISTRY,
            aep_lines,
            aep_assets,
            aep_polygons,
            {
                "hydraulic_captages": aep_captages,
                "hydraulic_upep": aep_upep,
            },
            {
                "hydraulic_captages": "captage",
                "hydraulic_upep": "upep",
            },
            "Estimation initiale des zonages hydrauliques AEP - Martinique",
            [
                "Les troncons AEP sont zones directement a partir des champs sect_dis ou SECTEUR selon le gestionnaire.",
                "Les UPEP sont rattachees par correspondance toponymique quand c'est possible, sinon par proximite au reseau AEP.",
                "Les captages sont rattaches a leur UPEP quand le champ UPEP permet une correspondance, sinon au reseau AEP le plus probable.",
            ],
            [
                "Le zonage AEP est solide sur les troncons car les secteurs sont portes par les couches reseau.",
                "Les UPEP manquent d'attribut communal dans la couche fournie, donc une part du rattachement repose sur la proximite au reseau.",
                "Les captages ne couvrent qu'une partie des ressources AEP presentes dans la realite operationnelle.",
            ],
        )

    if mode in {"mixed", "both"}:
        step_public = _load_public_steps()
        step_lookup = _build_step_lookup(step_public)
        pr_assets = _assign_pr_to_step(step_public, step_lookup)
        eu_system_assets = _eu_system_assets(step_public, pr_assets)
        eu_lines = _load_eu_lines(eu_system_assets)

        mixed_lines = gpd.GeoDataFrame(pd.concat([aep_lines, eu_lines], ignore_index=True), geometry="geometry", crs=METRIC_CRS)
        mixed_assets = gpd.GeoDataFrame(pd.concat([aep_assets, step_public, pr_assets], ignore_index=True), geometry="geometry", crs=METRIC_CRS)
        mixed_lines, mixed_assets, _ = _assign_zone_components(mixed_lines, mixed_assets)
        mixed_population_areas = _load_population_areas(MTQ_POPULATION_RASTER, mixed_lines)
        mixed_polygons = _build_zone_polygons(mixed_lines, mixed_assets, population_areas=mixed_population_areas)

        _write_bundle(
            mixed_output_gpkg,
            mixed_output_summary,
            mixed_output_csv,
            MIXED_OUTPUT_REWORK_REGISTRY,
            mixed_lines,
            mixed_assets,
            mixed_polygons,
            {
                "hydraulic_captages": mixed_assets[mixed_assets["feature_role"] == "captage_aep"].copy(),
                "hydraulic_upep": mixed_assets[mixed_assets["feature_role"] == "upep_aep"].copy(),
                "hydraulic_pr": mixed_assets[(mixed_assets["feature_role"] == "poste_refoulement") & mixed_assets["zone_uid"].notna()].copy(),
                "hydraulic_step": mixed_assets[mixed_assets["feature_role"] == "step"].copy(),
            },
            {
                "hydraulic_captages": "captage",
                "hydraulic_upep": "upep",
                "hydraulic_pr": "pr",
                "hydraulic_step": "step",
            },
            "Estimation initiale des systemes eau AEP + EU - Martinique",
            [
                "Le volet AEP reprend le zonage hydraulique direct porte par les champs de secteur reseau.",
                "Le volet EU est un zonage fonctionnel prudent centre sur les STEP publiques, avec rattachement des PR par cd_steu, nom de STEU, commune ou proximite.",
                "Les troncons EU sont rattaches au systeme PR/STEP le plus probable selon la commune, le territoire gestionnaire et la proximite geometrica.",
                "Le champ confidence permet de separer les affectations solides des affectations faibles, en particulier pour l'EU.",
            ],
            [
                "Le volet AEP est le plus fiable du livrable mixte.",
                "Le volet EU ne doit pas etre lu comme un zonage hydraulique fin troncon par troncon: c'est une premiere estimation fonctionnelle des systemes d'assainissement collectifs.",
                "Les reseaux EU Martinique portent peu de champs de secteur; plusieurs affectations de troncons reposent donc sur les relations PR -> STEP et sur la proximite aux actifs publics.",
                "Les STEP privees et les systemes non collectifs ne sont pas integres dans le zonage mixte principal, pour eviter de melanger reseaux publics et installations privees isolees.",
            ],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Martinique AEP and mixed water zoning estimates for QGIS.")
    parser.add_argument("--mode", choices=["aep", "mixed", "both"], default="both")
    parser.add_argument("--output-subdir", type=str, default="", help="Optional subdirectory under outputs/hydraulic_zoning for GPKG/QML/summary outputs")
    args = parser.parse_args()
    output_dir = OUTPUT_DIR / args.output_subdir if args.output_subdir else OUTPUT_DIR
    build_outputs(args.mode, output_dir=output_dir)


if __name__ == "__main__":
    main()