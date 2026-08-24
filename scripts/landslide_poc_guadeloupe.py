#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from climada.entity import Exposures, ImpactFunc, ImpactFuncSet
from climada.engine import ImpactCalc
from climada_petals.hazard.landslide import Landslide

from valuation_ofb import get_water_values


DEFAULT_EXPOSURE_SOURCE = Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe/EU/pr.gpkg")
DEFAULT_HAZARD_SOURCE = Path("/home/ubuntu/uploads/Landslide/LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif")


def _load_selected_points(source_path: Path, point_count: int) -> list[dict[str, object]]:
    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise RuntimeError(f"No features found in {source_path}")

    transformer = Transformer.from_crs(gdf.crs, "EPSG:4326", always_xy=True)
    selected: list[dict[str, object]] = []
    for idx, row in gdf.head(point_count).iterrows():
        geom = row.geometry
        if geom is None or getattr(geom, "is_empty", False):
            continue
        if geom.geom_type == "MultiPoint":
            geom = list(geom.geoms)[0]
        lon, lat = transformer.transform(float(geom.x), float(geom.y))
        selected.append(
            {
                "idx": int(idx),
                "name": str(row.get("pelem_nom") or row.get("ovrg_nom") or f"feature-{idx}"),
                "lon": float(lon),
                "lat": float(lat),
            }
        )
    return selected


def _default_value_eur(exposure_source_path: Path) -> float:
    name = exposure_source_path.name.lower()
    values = get_water_values("guadeloupe")
    if "step" in name:
        return float(values["eau_eu_step"])
    if "pr" in name:
        return float(values["eau_eu_pr"])
    return 1_000_000.0


def _build_exposure(points: list[dict[str, object]], value_eur: float) -> Exposures:
    rows = []
    for idx, item in enumerate(points, start=1):
        rows.append(
            {
                "value": float(value_eur),
                "impf_LS": 1,
                "longitude": float(item["lon"]),
                "latitude": float(item["lat"]),
                "point_id": f"p{idx}",
                "name": str(item["name"]),
                "geometry": Point(float(item["lon"]), float(item["lat"])),
            }
        )
    exp = Exposures(gpd.GeoDataFrame(rows, crs="EPSG:4326"))
    exp.check()
    return exp


def _build_impact_func() -> ImpactFuncSet:
    impf = ImpactFunc()
    impf.haz_type = "LS"
    impf.id = 1
    impf.name = "LS step function example"
    impf.intensity_unit = "m/m"
    impf.intensity = np.linspace(0.0, 1.0, num=15)
    impf.mdd = np.array([0.0] * 8 + [1.0] * 7, dtype=float)
    impf.paa = np.ones(15, dtype=float)
    impf.check()

    ifset = ImpactFuncSet()
    ifset.append(impf)
    return ifset


def _run_once(
    *,
    exposure_source_path: Path,
    hazard_path: Path,
    point_count: int,
    padding_deg: float,
    corr_fact: float,
    n_years: int,
    dist: str,
    seed: int,
    value_eur: float | None,
) -> dict[str, object]:
    np.random.seed(seed)
    points = _load_selected_points(exposure_source_path, point_count)
    if not points:
        raise RuntimeError("No usable point features could be read from the source dataset")

    lon_min = min(float(item["lon"]) for item in points) - float(padding_deg)
    lon_max = max(float(item["lon"]) for item in points) + float(padding_deg)
    lat_min = min(float(item["lat"]) for item in points) - float(padding_deg)
    lat_max = max(float(item["lat"]) for item in points) + float(padding_deg)
    bbox = (lon_min, lat_min, lon_max, lat_max)

    exp_value = float(value_eur) if value_eur is not None else _default_value_eur(exposure_source_path)
    exp = _build_exposure(points, exp_value)
    ifset = _build_impact_func()

    hazard = Landslide.from_prob(
        bbox=bbox,
        path_sourcefile=str(hazard_path),
        corr_fact=float(corr_fact),
        n_years=int(n_years),
        dist=str(dist),
    )
    impact = ImpactCalc(exp, ifset, hazard).impact(save_mat=False, assign_centroids=True)

    at_event = np.asarray(getattr(impact, "at_event", []), dtype=float)
    frequency = np.asarray(getattr(impact, "frequency", []), dtype=float)

    return {
        "exposure_source_path": str(exposure_source_path),
        "hazard_path": str(hazard_path),
        "bbox": [round(v, 8) for v in bbox],
        "selected_points": points,
        "point_count": int(len(points)),
        "value_eur_per_point": round(float(exp_value), 2),
        "total_exposure_eur": round(float(exp.gdf["value"].sum()), 2),
        "corr_fact": float(corr_fact),
        "n_years": int(n_years),
        "dist": str(dist),
        "hazard_shape": [int(v) for v in hazard.intensity.shape],
        "hazard_nnz": int(getattr(hazard.intensity, "nnz", 0)),
        "aai_agg_eur": round(float(getattr(impact, "aai_agg", 0.0) or 0.0), 2),
        "max_event_loss_eur": round(float(at_event.max()) if at_event.size else 0.0, 2),
        "nonzero_events": int(np.count_nonzero(at_event)),
        "event_frequency_sum": round(float(frequency.sum()) if frequency.size else 0.0, 8),
        "sample_top_losses": [round(float(v), 2) for v in at_event[at_event > 0][:10]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick CLIMADA Petals landslide proof-of-concept for Guadeloupe.")
    parser.add_argument("--exposure-path", type=Path, default=DEFAULT_EXPOSURE_SOURCE)
    parser.add_argument("--hazard-path", type=Path, default=DEFAULT_HAZARD_SOURCE)
    parser.add_argument("--point-count", type=int, default=3)
    parser.add_argument("--padding-deg", type=float, default=0.02)
    parser.add_argument(
        "--corr-fact",
        type=float,
        default=500.0,
        help=(
            "Scaling factor applied to the raster values before sampling. "
            "The CLIMADA tutorial uses a correction factor for the NGI rasters; "
            "this default is only for a quick feasibility test on the supplied uint8 raster."
        ),
    )
    parser.add_argument("--n-years", type=int, default=200)
    parser.add_argument("--dist", choices=["poisson", "binom"], default="poisson")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--value-eur", type=float, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if not args.exposure_path.exists():
        raise FileNotFoundError(f"Missing exposure source: {args.exposure_path}")
    if not args.hazard_path.exists():
        raise FileNotFoundError(f"Missing hazard raster: {args.hazard_path}")

    result = _run_once(
        exposure_source_path=args.exposure_path,
        hazard_path=args.hazard_path,
        point_count=args.point_count,
        padding_deg=args.padding_deg,
        corr_fact=args.corr_fact,
        n_years=args.n_years,
        dist=args.dist,
        seed=args.seed,
        value_eur=args.value_eur,
    )

    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json_out is not None:
        args.json_out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
