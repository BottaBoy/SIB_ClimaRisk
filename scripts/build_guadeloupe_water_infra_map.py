#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    gpd = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

try:
    from shapely.geometry import box
except Exception:  # pragma: no cover - optional at import time for CLI --help
    box = None  # type: ignore[assignment]

from case_study_sources import get_case_study, parse_territory


WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5490"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_COLUMNS = [
    "feature_id",
    "infra_type",
    "source_group",
    "service_unit_kind",
    "zone_component_key",
    "feature_role",
    "criticality",
    "source_feature_id",
    "geometry",
]

HYDRAULIC_NETWORK_KIND_TO_INFRA_TYPE = {
    "AEP": "aep_cana",
    "EU": "eu_cana",
}

HYDRAULIC_ASSET_ROLE_TO_INFRA_TYPE = {
    "captage_aep": "aep_ouvrage",
    "upep_aep": "aep_ouvrage",
    "pompage_aep": "aep_ouvrage",
    "reservoir_aep": "aep_ouvrage",
    "ouvrage_eau_brute_aep": "aep_ouvrage",
    "poste_refoulement": "eu_pr",
    "step": "eu_step",
}
HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX = "hydraulic-native"


def _require_geo_deps() -> None:
    missing: list[str] = []
    if gpd is None:
        missing.append("geopandas")
    if pd is None:
        missing.append("pandas")
    if box is None:
        missing.append("shapely")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_guadeloupe_water_infra_map.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install backend requirements and retry."
        )


def _ensure_crs(gdf: gpd.GeoDataFrame, fallback: str = METRIC_CRS) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(fallback)
    return gdf


def _read_vector(path: Path, *, layer: str | None = None, source_crs: str | None = None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    return _ensure_crs(gdf, fallback=source_crs or METRIC_CRS)


def _case_bbox_polygon(case_cfg: dict[str, object]):
    _require_geo_deps()
    bbox = dict(case_cfg.get("wind_bbox") or {})
    return box(  # type: ignore[operator]
        float(bbox["lon_min"]),
        float(bbox["lat_min"]),
        float(bbox["lon_max"]),
        float(bbox["lat_max"]),
    )


def _clip_case_gdf(gdf: gpd.GeoDataFrame, case_cfg: dict[str, object]) -> gpd.GeoDataFrame:
    gdf_wgs = _ensure_crs(gdf, fallback=WGS84).to_crs(WGS84).copy()
    gdf_wgs["geometry"] = gdf_wgs.geometry.intersection(_case_bbox_polygon(case_cfg))
    geometry = gdf_wgs.geometry
    return gdf_wgs[(~geometry.is_empty) & (~geometry.isna())].copy()


def _empty_output_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=OUTPUT_COLUMNS, geometry="geometry", crs=WGS84)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _resolve_hydraulic_service_key(
    row: object,
    *,
    feature_id: str,
    context: str,
    allow_unassigned_fallback: bool,
    allow_zone_uid_fallback: bool = False,
) -> tuple[str, str]:
    service_key = _clean_text(getattr(row, "zone_component_key", ""))
    if service_key:
        return service_key, "hydraulic_zone_component"

    zone_uid = _clean_text(getattr(row, "zone_uid", ""))
    if zone_uid:
        if allow_zone_uid_fallback:
            return zone_uid, "hydraulic_zone_uid_legacy"
        raise ValueError(f"{context} requires zone_component_key for {feature_id}")

    if not allow_unassigned_fallback:
        raise ValueError(f"{context} requires zone_component_key for {feature_id}")

    return f"{HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX}:{feature_id}", "native_feature"


def _hydraulic_line_infra_type(network_kind: object) -> str:
    infra_type = HYDRAULIC_NETWORK_KIND_TO_INFRA_TYPE.get(_clean_text(network_kind).upper())
    if not infra_type:
        raise ValueError(f"Unsupported hydraulic line network_kind: {network_kind!r}")
    return infra_type


def _hydraulic_asset_infra_type(feature_role: object, network_kind: object) -> str:
    role = _clean_text(feature_role)
    infra_type = HYDRAULIC_ASSET_ROLE_TO_INFRA_TYPE.get(role)
    if infra_type:
        return infra_type
    if _clean_text(network_kind).upper() == "AEP":
        return "aep_ouvrage"
    raise ValueError(f"Unsupported hydraulic asset role: feature_role={feature_role!r} network_kind={network_kind!r}")


def _load_layer(
    path: Path,
    case_cfg: dict[str, object],
    *,
    infra_type: str,
    source_group: str,
    simplify_tolerance_m: float,
    source_crs: str | None = None,
) -> gpd.GeoDataFrame:
    gdf = _clip_case_gdf(_read_vector(path, source_crs=source_crs), case_cfg)
    if gdf.empty:
        return _empty_output_gdf()

    gdf_metric = gdf.to_crs(METRIC_CRS)
    line_like = gdf_metric.geom_type.str.contains("Line", case=False, na=False)
    if simplify_tolerance_m > 0 and line_like.any():
        gdf_metric.loc[line_like, "geometry"] = gdf_metric.loc[line_like, "geometry"].simplify(
            simplify_tolerance_m,
            preserve_topology=False,
        )
    gdf_wgs = gdf_metric.to_crs(WGS84)
    geometry = gdf_wgs.geometry
    gdf_wgs = gdf_wgs[(~geometry.is_empty) & (~geometry.isna())].copy()

    gdf_wgs["feature_id"] = None
    gdf_wgs["infra_type"] = infra_type
    gdf_wgs["source_group"] = source_group
    gdf_wgs["service_unit_kind"] = None
    gdf_wgs["zone_component_key"] = None
    gdf_wgs["feature_role"] = None
    gdf_wgs["criticality"] = None
    gdf_wgs["source_feature_id"] = None
    return gdf_wgs[OUTPUT_COLUMNS]


def _load_hydraulic_zone_layer(
    path: Path,
    case_cfg: dict[str, object],
    *,
    layer: str,
) -> gpd.GeoDataFrame:
    gdf = _clip_case_gdf(_read_vector(path, layer=layer), case_cfg)
    if gdf.empty:
        return _empty_output_gdf()

    rows: list[dict[str, object]] = []
    for idx, row in enumerate(gdf.itertuples(index=False), start=1):
        geometry = getattr(row, "geometry", None)
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        feature_id = _clean_text(getattr(row, "feature_id", "")) or f"hydraulic-zone-{idx}"
        service_key, service_unit_kind = _resolve_hydraulic_service_key(
            row,
            feature_id=feature_id,
            context="hydraulic zone layer",
            allow_unassigned_fallback=False,
        )
        rows.append(
            {
                "feature_id": service_key,
                "infra_type": _hydraulic_line_infra_type(getattr(row, "network_kind", "")),
                "source_group": _clean_text(getattr(row, "network_kind", "")).upper() or "WATER",
                "service_unit_kind": service_unit_kind,
                "zone_component_key": service_key,
                "feature_role": _clean_text(getattr(row, "feature_role", "")) or "canalisation",
                "criticality": None,
                "source_feature_id": _clean_text(getattr(row, "source_feature_id", "")) or None,
                "geometry": geometry,
            }
        )

    if not rows:
        return _empty_output_gdf()
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)[OUTPUT_COLUMNS]


def _load_hydraulic_asset_layer(
    path: Path,
    case_cfg: dict[str, object],
    *,
    layer: str,
) -> gpd.GeoDataFrame:
    gdf = _clip_case_gdf(_read_vector(path, layer=layer), case_cfg)
    if gdf.empty:
        return _empty_output_gdf()

    rows: list[dict[str, object]] = []
    for idx, row in enumerate(gdf.itertuples(index=False), start=1):
        geometry = getattr(row, "geometry", None)
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        feature_id = _clean_text(getattr(row, "feature_id", "")) or _clean_text(getattr(row, "source_feature_id", "")) or f"hydraulic-asset-{idx}"
        service_key, service_unit_kind = _resolve_hydraulic_service_key(
            row,
            feature_id=feature_id,
            context="hydraulic asset layer",
            allow_unassigned_fallback=True,
            allow_zone_uid_fallback=True,
        )
        rows.append(
            {
                "feature_id": feature_id,
                "infra_type": _hydraulic_asset_infra_type(
                    getattr(row, "feature_role", ""),
                    getattr(row, "network_kind", ""),
                ),
                "source_group": _clean_text(getattr(row, "network_kind", "")).upper() or "WATER",
                "service_unit_kind": service_unit_kind,
                "zone_component_key": service_key,
                "feature_role": _clean_text(getattr(row, "feature_role", "")) or None,
                "criticality": _clean_text(getattr(row, "criticality", "")) or None,
                "source_feature_id": _clean_text(getattr(row, "source_feature_id", "")) or None,
                "geometry": geometry,
            }
        )

    if not rows:
        return _empty_output_gdf()
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)[OUTPUT_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build territory water+electric infrastructure GeoJSON for web visualization.")
    parser.add_argument("--territory", default="guadeloupe")
    parser.add_argument("--infra-eau-dir", default=None)
    parser.add_argument("--infra-elec-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--simplify-tolerance-m", type=float, default=3.0)
    args = parser.parse_args()
    _require_geo_deps()

    territory = parse_territory(args.territory)
    cfg = get_case_study(
        territory,
        infra_elec_dir=Path(args.infra_elec_dir) if args.infra_elec_dir else None,
        infra_eau_dir=Path(args.infra_eau_dir) if args.infra_eau_dir else None,
    )
    out = Path(args.out) if args.out else (REPO_ROOT / "web" / "data" / f"{territory}-water-infra.geojson")

    gdfs: list[gpd.GeoDataFrame] = []
    for layer in cfg["elec_line_sources"]:
        for path in layer["paths"]:
            gdfs.append(
                _load_layer(
                    path,
                    cfg,
                    infra_type=str(layer["infra_type"]),
                    source_group=str(layer["source_group"]),
                    simplify_tolerance_m=float(args.simplify_tolerance_m),
                    source_crs=str(layer.get("source_crs", "") or "") or None,
                )
            )

    for source in cfg["hydraulic_zone_sources"]:
        gdfs.append(
            _load_hydraulic_zone_layer(
                Path(source["path"]),
                cfg,
                layer=str(source["zone_layer"]),
            )
        )
        gdfs.append(
            _load_hydraulic_asset_layer(
                Path(source["path"]),
                cfg,
                layer=str(source["asset_layer"]),
            )
        )

    if not gdfs:
        raise RuntimeError("No infrastructure features found after territory bbox filtering.")

    out_gdf = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        geometry="geometry",
        crs=WGS84,
    )

    counters: dict[str, int] = defaultdict(int)
    used_feature_ids: set[str] = set()
    feature_ids: list[str] = []
    for row in out_gdf.itertuples(index=False):
        existing_feature_id = _clean_text(getattr(row, "feature_id", ""))
        if existing_feature_id and existing_feature_id not in used_feature_ids:
            feature_ids.append(existing_feature_id)
            used_feature_ids.add(existing_feature_id)
            continue

        key = _clean_text(getattr(row, "infra_type", "")) or "infra"
        counters[key] += 1
        candidate = f"{key}-{counters[key]}"
        while candidate in used_feature_ids:
            counters[key] += 1
            candidate = f"{key}-{counters[key]}"
        feature_ids.append(candidate)
        used_feature_ids.add(candidate)
    out_gdf["feature_id"] = feature_ids
    out_gdf = out_gdf[OUTPUT_COLUMNS]

    out.parent.mkdir(parents=True, exist_ok=True)
    out_gdf.to_file(out, driver="GeoJSON")

    print(f"Wrote {out}")
    print(f"territory={territory}")
    print(f"features={len(out_gdf)}")
    print(out_gdf["infra_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
