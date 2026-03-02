#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

import geopandas as gpd


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.analysis_export import build_result_payload  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.impact_runner import compute_impacts  # noqa: E402
from app.risk_engine.types import NormalizedExposure, NormalizedFeature  # noqa: E402


METRIC_CRS = "EPSG:5490"
WGS84 = "EPSG:4326"


def _ensure_crs(gdf: gpd.GeoDataFrame, fallback: str = WGS84) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(fallback)
    return gdf


def _as_wgs84_and_metric(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    gdf = _ensure_crs(gdf)
    gdf_wgs = gdf.to_crs(WGS84)
    gdf_metric = gdf.to_crs(METRIC_CRS)
    return gdf_wgs, gdf_metric


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
    for idx, (geom_wgs, geom_metric) in enumerate(zip(gdf_wgs.geometry, gdf_metric.geometry)):
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


def _aep_ouvrage_value(ovrg_type: str) -> float:
    code = str(ovrg_type or "").strip().upper()
    if code == "TRAIT":
        return 3_500_000.0
    if code == "STPMP":
        return 1_200_000.0
    if code == "CAP":
        return 1_000_000.0
    if code == "CUV":
        return 500_000.0
    return 800_000.0


def _point_features_aep_ouvrages(gdf: gpd.GeoDataFrame) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, row in enumerate(gdf_wgs.itertuples(index=False)):
        geom = getattr(row, "geometry", None)
        if geom is None or getattr(geom, "is_empty", False):
            continue
        ovrg_type = str(getattr(row, "ovrg_type", "") or "").strip().upper()
        asset_type = f"eau_aep_ouvrage_{ovrg_type or 'NA'}"
        centroid = geom.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"aep-ouvrage-{idx + 1}",
                label=f"AEP ouvrage {ovrg_type or 'NA'} {idx + 1}",
                value_eur=_aep_ouvrage_value(ovrg_type),
                geometry_type=str(getattr(geom, "geom_type", "Point")),
                exposure_category="ouvrage_eau",
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def build_complete_exposure(
    *,
    infra_elec_dir: Path,
    infra_eau_dir: Path,
) -> NormalizedExposure:
    features: list[NormalizedFeature] = []

    # Electricity lines
    features.extend(
        _line_features(
            gpd.read_file(infra_elec_dir / "lignes-basse-tension-bt-aerien-gua.geojson"),
            feature_prefix="elec-bt-aerien",
            asset_type="elec_bt_aerien",
            exposure_category="ouvrage_electrique",
            eur_per_km=180_000.0,
        )
    )
    features.extend(
        _line_features(
            gpd.read_file(infra_elec_dir / "lignes-basse-tension-bt-souterrain-gua.geojson"),
            feature_prefix="elec-bt-souterrain",
            asset_type="elec_bt_souterrain",
            exposure_category="ouvrage_electrique",
            eur_per_km=320_000.0,
        )
    )
    features.extend(
        _line_features(
            gpd.read_file(infra_elec_dir / "lignes-haute-tension-hta-aerien-gua.geojson"),
            feature_prefix="elec-hta-aerien",
            asset_type="elec_hta_aerien",
            exposure_category="ouvrage_electrique",
            eur_per_km=260_000.0,
        )
    )
    features.extend(
        _line_features(
            gpd.read_file(infra_elec_dir / "lignes-haute-tension-hta-souterrain-gua.geojson"),
            feature_prefix="elec-hta-souterrain",
            asset_type="elec_hta_souterrain",
            exposure_category="ouvrage_electrique",
            eur_per_km=520_000.0,
        )
    )

    # Potable water
    features.extend(
        _line_features(
            gpd.read_file(infra_eau_dir / "AEP" / "cana_aep.gpkg"),
            feature_prefix="aep-cana",
            asset_type="eau_aep_cana",
            exposure_category="ouvrage_eau",
            eur_per_km=280_000.0,
        )
    )
    features.extend(_point_features_aep_ouvrages(gpd.read_file(infra_eau_dir / "AEP" / "ouvrage_aep.gpkg")))

    # Wastewater
    features.extend(
        _line_features(
            gpd.read_file(infra_eau_dir / "EU" / "cana_eu.gpkg"),
            feature_prefix="eu-cana",
            asset_type="eau_eu_cana",
            exposure_category="ouvrage_eau",
            eur_per_km=340_000.0,
        )
    )
    features.extend(
        _point_features_fixed_value(
            gpd.read_file(infra_eau_dir / "EU" / "pr.gpkg"),
            feature_prefix="eu-pr",
            asset_type="eau_eu_pr",
            exposure_category="ouvrage_eau",
            fixed_value_eur=900_000.0,
        )
    )
    features.extend(
        _point_features_fixed_value(
            gpd.read_file(infra_eau_dir / "EU" / "step.gpkg"),
            feature_prefix="eu-step",
            asset_type="eau_eu_step",
            exposure_category="ouvrage_eau",
            fixed_value_eur=6_000_000.0,
        )
    )

    warnings = [
        "Reference run uses prudent valuation hypotheses per km/ouvrage for Guadeloupe electricity and water infrastructure.",
        "All water assets are conservatively assumed dependent on electricity when service propagation is computed.",
        "For full STORM and STORM_CMCC raw catalogs, use official 4TU datasets linked in result notes and README.",
    ]

    return NormalizedExposure(
        source_name="guadeloupe_complete_infra_reference",
        source_format="mixed_geojson_gpkg",
        input_mode="reference_dataset",
        features=features,
        warnings=warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build complete Guadeloupe electricity+water risk result JSON.")
    parser.add_argument("--infra-elec-dir", default="/home/ubuntu/uploads/Infra_Elec_Guadeloupe")
    parser.add_argument("--infra-eau-dir", default="/home/ubuntu/uploads/Infra_Eau_Guadeloupe")
    parser.add_argument("--out", default=str(REPO_ROOT / "web" / "data" / "guadeloupe-complete-analysis.json"))
    parser.add_argument("--sampling-spacing-m", type=float, default=100.0)
    args = parser.parse_args()

    exposure = build_complete_exposure(
        infra_elec_dir=Path(args.infra_elec_dir),
        infra_eau_dir=Path(args.infra_eau_dir),
    )
    disagg = summarize_disaggregation(exposure, spacing_m=float(args.sampling_spacing_m))
    comp = compute_impacts(exposure, disagg)

    payload = build_result_payload(
        job_id="guadeloupe_complete_reference",
        source="guadeloupe_complete_reference",
        exposure=exposure,
        disagg=disagg,
        comp=comp,
    )
    payload["meta"]["title"] = "Guadeloupe Complete Water+Electric Cyclone Risk"
    payload["meta"]["dataset_links"] = {
        "storm_present": "https://data.4tu.nl/articles/dataset/STORM_IBTrACS_present_climate_synthetic_tropical_cyclone_tracks/12706085",
        "storm_cmcc": "https://data.4tu.nl/datasets/98900e17-8e01-4d70-b3b6-ca1a1da2f194/2",
    }
    payload["exposure_summary"]["asset_type_counts"] = dict(
        Counter(str((feat.properties or {}).get("asset_type") or "unknown") for feat in exposure.features)
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"asset_count={payload['exposure_summary']['asset_count_original']}")
    print(f"total_exposure_eur={payload['exposure_summary']['total_exposure_eur']}")
    print(f"portfolio_eai_storm={payload['portfolio_results']['storm']['eai_eur']}")
    print(f"portfolio_eai_cmcc={payload['portfolio_results']['storm_cmcc']['eai_eur']}")


if __name__ == "__main__":
    main()
