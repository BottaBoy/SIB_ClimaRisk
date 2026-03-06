#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd

from case_study_sources import get_case_study, normalize_territory


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
    return gdf_wgs[["infra_type", "source_group", "geometry"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build territory water+electric infrastructure GeoJSON for web visualization.")
    parser.add_argument("--territory", choices=["guadeloupe", "martinique"], default="guadeloupe")
    parser.add_argument("--infra-eau-dir", default=None)
    parser.add_argument("--infra-elec-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--simplify-tolerance-m", type=float, default=3.0)
    args = parser.parse_args()

    territory = normalize_territory(args.territory)
    cfg = get_case_study(
        territory,
        infra_elec_dir=Path(args.infra_elec_dir) if args.infra_elec_dir else None,
        infra_eau_dir=Path(args.infra_eau_dir) if args.infra_eau_dir else None,
    )
    out = Path(args.out) if args.out else (Path("/home/ubuntu/sib-work/web/data") / f"{territory}-water-infra.geojson")

    gdfs: list[gpd.GeoDataFrame] = []
    for layer in cfg["water_map_layers"]:
        for path in layer["paths"]:
            gdfs.append(
                _load_layer(
                    path,
                    infra_type=str(layer["infra_type"]),
                    source_group=str(layer["source_group"]),
                    simplify_tolerance_m=float(args.simplify_tolerance_m),
                )
            )

    out_gdf = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        geometry="geometry",
        crs=WGS84,
    )

    counters: dict[str, int] = defaultdict(int)
    feature_ids: list[str] = []
    for infra_type in out_gdf["infra_type"].tolist():
        key = str(infra_type)
        counters[key] += 1
        feature_ids.append(f"{key}-{counters[key]}")
    out_gdf["feature_id"] = feature_ids
    out_gdf = out_gdf[["feature_id", "infra_type", "source_group", "geometry"]]

    out.parent.mkdir(parents=True, exist_ok=True)
    out_gdf.to_file(out, driver="GeoJSON")

    print(f"Wrote {out}")
    print(f"territory={territory}")
    print(f"features={len(out_gdf)}")
    print(out_gdf["infra_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
