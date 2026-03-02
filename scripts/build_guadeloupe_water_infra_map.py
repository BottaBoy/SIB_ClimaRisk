#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd


WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:5490"


def _ensure_crs(gdf: gpd.GeoDataFrame, fallback: str = METRIC_CRS) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs(fallback)
    return gdf


def _load_layer(
    path: Path,
    *,
    infra_type: str,
    source_group: str,
    simplify_tolerance_m: float,
) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    gdf = _ensure_crs(gdf)

    gdf_metric = gdf.to_crs(METRIC_CRS)
    line_like = gdf_metric.geom_type.str.contains("Line", case=False, na=False)
    if simplify_tolerance_m > 0 and line_like.any():
        gdf_metric.loc[line_like, "geometry"] = gdf_metric.loc[line_like, "geometry"].simplify(
            simplify_tolerance_m,
            preserve_topology=False,
        )
    gdf_wgs = gdf_metric.to_crs(WGS84)
    gdf_wgs = gdf_wgs[~gdf_wgs.geometry.is_empty & gdf_wgs.geometry.notna()].copy()

    gdf_wgs["infra_type"] = infra_type
    gdf_wgs["source_group"] = source_group
    gdf_wgs["feature_id"] = [f"{infra_type}-{i+1}" for i in range(len(gdf_wgs))]
    return gdf_wgs[["feature_id", "infra_type", "source_group", "geometry"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Guadeloupe water infrastructure GeoJSON for web visualization.")
    parser.add_argument("--infra-eau-dir", default="/home/ubuntu/uploads/Infra_Eau_Guadeloupe")
    parser.add_argument("--out", default="/home/ubuntu/sib-work/web/data/guadeloupe-water-infra.geojson")
    parser.add_argument("--simplify-tolerance-m", type=float, default=3.0)
    args = parser.parse_args()

    root = Path(args.infra_eau_dir)
    layers = [
        (root / "AEP" / "cana_aep.gpkg", "aep_cana", "AEP"),
        (root / "AEP" / "ouvrage_aep.gpkg", "aep_ouvrage", "AEP"),
        (root / "EU" / "cana_eu.gpkg", "eu_cana", "EU"),
        (root / "EU" / "pr.gpkg", "eu_pr", "EU"),
        (root / "EU" / "step.gpkg", "eu_step", "EU"),
    ]

    gdfs: list[gpd.GeoDataFrame] = []
    for path, infra_type, source_group in layers:
        gdfs.append(
            _load_layer(
                path,
                infra_type=infra_type,
                source_group=source_group,
                simplify_tolerance_m=float(args.simplify_tolerance_m),
            )
        )

    out_gdf = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        geometry="geometry",
        crs=WGS84,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_gdf.to_file(out, driver="GeoJSON")

    print(f"Wrote {out}")
    print(f"features={len(out_gdf)}")
    print(out_gdf["infra_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
