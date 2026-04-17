#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
import os
from pathlib import Path
import sys

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    gpd = None  # type: ignore[assignment]

try:
    from shapely.geometry import box
except Exception:  # pragma: no cover - optional at import time for CLI --help
    box = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.analysis_export import build_result_payload  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.impact_runner import compute_impacts  # noqa: E402
from app.risk_engine.types import NormalizedExposure, NormalizedFeature  # noqa: E402
from case_study_sources import (  # noqa: E402
    get_case_study,
    normalize_territory,
    territory_label,
)
from valuation_ofb import (  # noqa: E402
    SOURCE_LABEL,
    VALUATION_VERSION,
    build_valuation_metadata,
    get_aep_ouvrage_value,
    get_elec_values,
    get_water_values,
)


METRIC_CRS = "EPSG:5490"
WGS84 = "EPSG:4326"
CASE_HAZARD_PATHS = {
    "guadeloupe": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
    "martinique": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique_CMCC.h5",
    ),
}


def _require_geo_deps() -> None:
    if gpd is None or box is None:
        raise RuntimeError(
            "Missing geospatial dependencies for this script. Install backend requirements "
            "(including geopandas/shapely) and retry."
        )


def _prefer_case_study_hdf5_path(configured_path: Path, case_default_path: Path) -> Path:
    builtin_case_paths = {path for pair in CASE_HAZARD_PATHS.values() for path in pair}
    if configured_path.exists():
        if configured_path == case_default_path:
            return configured_path
        if configured_path in builtin_case_paths and case_default_path.exists():
            return case_default_path
        return configured_path
    return case_default_path if case_default_path.exists() else configured_path


def _resolve_hazard_paths_for_case_study(territory_key: str) -> tuple[Path, Path]:
    settings = load_settings()
    default_storm_path, default_cmcc_path = CASE_HAZARD_PATHS[territory_key]
    settings_storm_path = Path(settings.hazard_storm_path)
    settings_cmcc_path = Path(settings.hazard_storm_cmcc_path)

    if settings.multi_hazard_enabled:
        hazard_storm_path = _prefer_case_study_hdf5_path(settings_storm_path, default_storm_path)
        hazard_cmcc_path = _prefer_case_study_hdf5_path(settings_cmcc_path, default_cmcc_path)
    else:
        hazard_storm_path = default_storm_path if default_storm_path.exists() else settings_storm_path
        hazard_cmcc_path = default_cmcc_path if default_cmcc_path.exists() else settings_cmcc_path

    return hazard_storm_path, hazard_cmcc_path


def _ensure_crs(gdf: gpd.GeoDataFrame, fallback: str = WGS84) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(fallback)
    return gdf


def _as_wgs84_and_metric(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    gdf = _ensure_crs(gdf)
    gdf_wgs = gdf.to_crs(WGS84)
    gdf_metric = gdf.to_crs(METRIC_CRS)
    return gdf_wgs, gdf_metric


def _bbox_polygon_from_cfg(cfg: dict[str, object]):
    _require_geo_deps()
    bbox = dict(cfg.get("wind_bbox") or {})
    return box(  # type: ignore[operator]
        float(bbox["lon_min"]),
        float(bbox["lat_min"]),
        float(bbox["lon_max"]),
        float(bbox["lat_max"]),
    )


def _clip_to_bbox(gdf: gpd.GeoDataFrame, bbox_polygon) -> gpd.GeoDataFrame:
    gdf_wgs = _ensure_crs(gdf, fallback=WGS84).to_crs(WGS84).copy()
    gdf_wgs["geometry"] = gdf_wgs.geometry.intersection(bbox_polygon)
    geometry = gdf_wgs.geometry
    return gdf_wgs[(~geometry.is_empty) & (~geometry.isna())].copy()


def _line_features(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    asset_type: str,
    exposure_category: str,
    eur_per_km: float,
) -> list[NormalizedFeature]:
    gdf_wgs, gdf_metric = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, (geom_wgs, geom_metric) in enumerate(zip(gdf_wgs.geometry, gdf_metric.geometry, strict=False)):
        if geom_wgs is None or geom_metric is None or getattr(geom_wgs, "is_empty", False) or getattr(geom_metric, "is_empty", False):
            continue
        centroid = geom_wgs.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        length_km = max(0.0, float(getattr(geom_metric, "length", 0.0)) / 1000.0)
        value_eur = max(5_000.0, length_km * eur_per_km)
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"{asset_type} {idx + 1}",
                value_eur=float(value_eur),
                geometry_type=str(getattr(geom_wgs, "geom_type", "LineString")),
                exposure_category=exposure_category,
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_fixed_value(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    asset_type: str,
    exposure_category: str,
    fixed_value_eur: float,
) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, geom in enumerate(gdf_wgs.geometry):
        if geom is None or getattr(geom, "is_empty", False):
            continue
        centroid = geom.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"{asset_type} {idx + 1}",
                value_eur=float(fixed_value_eur),
                geometry_type=str(getattr(geom, "geom_type", "Point")),
                exposure_category=exposure_category,
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_aep_ouvrages_from_field(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    field_name: str = "ovrg_type",
) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, row in enumerate(gdf_wgs.itertuples(index=False)):
        geom = getattr(row, "geometry", None)
        if geom is None or getattr(geom, "is_empty", False):
            continue
        ovrg_type = str(getattr(row, field_name, "") or "").strip().upper()
        asset_type = f"eau_aep_ouvrage_{ovrg_type or 'NA'}"
        centroid = geom.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"AEP ouvrage {ovrg_type or 'NA'} {idx + 1}",
                value_eur=get_aep_ouvrage_value(ovrg_type),
                geometry_type=str(getattr(geom, "geom_type", "Point")),
                exposure_category="ouvrage_eau",
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_aep_ouvrages_fixed_type(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    ovrg_type: str,
) -> list[NormalizedFeature]:
    code = str(ovrg_type or "").strip().upper() or "NA"
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, geom in enumerate(gdf_wgs.geometry):
        if geom is None or getattr(geom, "is_empty", False):
            continue
        centroid = geom.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"AEP ouvrage {code} {idx + 1}",
                value_eur=get_aep_ouvrage_value(code),
                geometry_type=str(getattr(geom, "geom_type", "Point")),
                exposure_category="ouvrage_eau",
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=None,
                properties={"asset_type": f"eau_aep_ouvrage_{code}"},
            )
        )
    return out


def build_complete_exposure(
    *,
    infra_elec_dir: Path | None = None,
    infra_eau_dir: Path | None = None,
    territory: str = "guadeloupe",
) -> NormalizedExposure:
    _require_geo_deps()
    territory_key = normalize_territory(territory)
    cfg = get_case_study(
        territory_key,
        infra_elec_dir=infra_elec_dir,
        infra_eau_dir=infra_eau_dir,
    )
    valuation_meta = build_valuation_metadata(territory_key)
    water_values = get_water_values(territory_key)
    elec_values = get_elec_values()
    features: list[NormalizedFeature] = []
    bbox_polygon = _bbox_polygon_from_cfg(cfg)

    for src in cfg["elec_line_sources"]:
        eur_per_km = float(elec_values[str(src["asset_type"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
            if gdf.empty:
                continue
            features.extend(
                _line_features(
                    gdf,
                    feature_prefix=f"{src['prefix']}-{p_idx}",
                    asset_type=str(src["asset_type"]),
                    exposure_category="ouvrage_electrique",
                    eur_per_km=eur_per_km,
                )
            )

    for src in cfg["water_line_sources"]:
        eur_per_km = float(water_values[str(src["value_key"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
            if gdf.empty:
                continue
            features.extend(
                _line_features(
                    gdf,
                    feature_prefix=f"{src['prefix']}-{p_idx}",
                    asset_type=str(src["asset_type"]),
                    exposure_category="ouvrage_eau",
                    eur_per_km=eur_per_km,
                )
            )

    for src in cfg["aep_ouvrage_sources"]:
        mode = str(src.get("mode", "")).strip().lower()
        for p_idx, path in enumerate(src["paths"], start=1):
            gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
            if gdf.empty:
                continue
            if mode == "fixed_type":
                features.extend(
                    _point_features_aep_ouvrages_fixed_type(
                        gdf,
                        feature_prefix=f"{src['prefix']}-{p_idx}",
                        ovrg_type=str(src.get("ovrg_type", "NA")),
                    )
                )
            else:
                features.extend(
                    _point_features_aep_ouvrages_from_field(
                        gdf,
                        feature_prefix=f"{src['prefix']}-{p_idx}",
                        field_name=str(src.get("field_name", "ovrg_type")),
                    )
                )

    for src in cfg["water_point_fixed_sources"]:
        fixed_value_eur = float(water_values[str(src["value_key"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
            if gdf.empty:
                continue
            features.extend(
                _point_features_fixed_value(
                    gdf,
                    feature_prefix=f"{src['prefix']}-{p_idx}",
                    asset_type=str(src["asset_type"]),
                    exposure_category="ouvrage_eau",
                    fixed_value_eur=fixed_value_eur,
                )
            )

    warnings = [
        "Water valuation based on OFB cost comparator (territory mean).",
        f"Valuation source: {SOURCE_LABEL}.",
        f"Territory selection fixed by case-study input: {territory_key}, effective={valuation_meta['territory_effective']}.",
        "All water assets are conservatively assumed dependent on electricity when service propagation is computed.",
        "For full STORM and STORM_CMCC raw catalogs, use official 4TU datasets linked in result notes and README.",
    ]

    return NormalizedExposure(
        source_name=f"{territory_key}_complete_infra_reference",
        source_format="mixed_geojson_gpkg_shp",
        input_mode="reference_dataset",
        features=features,
        warnings=warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build complete territory electricity+water risk result JSON.")
    parser.add_argument("--territory", choices=["guadeloupe", "martinique"], default="guadeloupe")
    parser.add_argument("--infra-elec-dir", default=None)
    parser.add_argument("--infra-eau-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--sampling-spacing-m", type=float, default=100.0)
    args = parser.parse_args()

    territory_key = normalize_territory(args.territory)
    case_cfg = get_case_study(
        territory_key,
        infra_elec_dir=Path(args.infra_elec_dir) if args.infra_elec_dir else None,
        infra_eau_dir=Path(args.infra_eau_dir) if args.infra_eau_dir else None,
    )
    out_path = Path(args.out) if args.out else (REPO_ROOT / "web" / "data" / f"{territory_key}-complete-analysis.json")

    valuation_meta = build_valuation_metadata(territory_key)
    exposure = build_complete_exposure(
        infra_elec_dir=case_cfg["infra_elec_dir"],
        infra_eau_dir=case_cfg["infra_eau_dir"],
        territory=territory_key,
    )
    disagg = summarize_disaggregation(exposure, spacing_m=float(args.sampling_spacing_m))
    hazard_storm_path, hazard_cmcc_path = _resolve_hazard_paths_for_case_study(territory_key)
    prev_storm = os.environ.get("SIB_RISK_HAZARD_STORM_PATH")
    prev_cmcc = os.environ.get("SIB_RISK_HAZARD_STORM_CMCC_PATH")
    if hazard_storm_path.exists():
        os.environ["SIB_RISK_HAZARD_STORM_PATH"] = str(hazard_storm_path)
    if hazard_cmcc_path.exists():
        os.environ["SIB_RISK_HAZARD_STORM_CMCC_PATH"] = str(hazard_cmcc_path)
    try:
        comp = compute_impacts(exposure, disagg)
    finally:
        if prev_storm is None:
            os.environ.pop("SIB_RISK_HAZARD_STORM_PATH", None)
        else:
            os.environ["SIB_RISK_HAZARD_STORM_PATH"] = prev_storm
        if prev_cmcc is None:
            os.environ.pop("SIB_RISK_HAZARD_STORM_CMCC_PATH", None)
        else:
            os.environ["SIB_RISK_HAZARD_STORM_CMCC_PATH"] = prev_cmcc

    source_key = f"{territory_key}_complete_reference"
    payload = build_result_payload(
        job_id=source_key,
        source=source_key,
        run_label=None,
        exposure=exposure,
        disagg=disagg,
        comp=comp,
    )
    payload["meta"]["title"] = f"{territory_label(territory_key)} Complete Water+Electric Cyclone Risk"
    payload["meta"]["dataset_links"] = {
        "storm_present": "https://data.4tu.nl/articles/dataset/STORM_IBTrACS_present_climate_synthetic_tropical_cyclone_tracks/12706085",
        "storm_cmcc": "https://data.4tu.nl/datasets/98900e17-8e01-4d70-b3b6-ca1a1da2f194/2",
    }
    payload["meta"]["valuation_source"] = SOURCE_LABEL
    payload["meta"]["valuation_territory"] = str(valuation_meta["territory_effective"])
    payload["meta"]["valuation_version"] = VALUATION_VERSION
    payload["meta"]["case_study_territory"] = territory_key
    payload["exposure_summary"]["asset_type_counts"] = dict(
        Counter(str((feat.properties or {}).get("asset_type") or "unknown") for feat in exposure.features)
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"territory={territory_key}")
    print(f"asset_count={payload['exposure_summary']['asset_count_original']}")
    print(f"total_exposure_eur={payload['exposure_summary']['total_exposure_eur']}")
    print(f"portfolio_eai_storm={payload['portfolio_results']['storm']['eai_eur']}")
    print(f"portfolio_eai_cmcc={payload['portfolio_results']['storm_cmcc']['eai_eur']}")


if __name__ == "__main__":
    main()
