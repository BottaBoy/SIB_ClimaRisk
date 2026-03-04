#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import xarray as xr
from climada.hazard import Hazard, TCTracks, TropCyclone, Centroids


def _normalize_wind_unit(raw: str) -> str:
    unit = str(raw or "m/s").strip().lower()
    aliases = {
        "m/s": "m/s",
        "ms": "m/s",
        "mps": "m/s",
        "meter_per_second": "m/s",
        "meters_per_second": "m/s",
        "knot": "kn",
        "knots": "kn",
        "kt": "kn",
        "kts": "kn",
        "kn": "kn",
        "km/h": "km/h",
        "kmh": "km/h",
        "kph": "km/h",
    }
    if unit not in aliases:
        raise ValueError(f"Unsupported wind unit '{raw}'. Supported: m/s, kn, km/h")
    return aliases[unit]


def _convert_wind_to_mps(values: pd.Series, unit_in: str) -> pd.Series:
    unit = _normalize_wind_unit(unit_in)
    wind = pd.to_numeric(values, errors="coerce").astype(float)
    if unit == "m/s":
        return wind
    if unit == "kn":
        return wind * 0.514444
    return wind / 3.6  # km/h -> m/s


def _normalize_distance_unit(raw: str) -> str:
    unit = str(raw or "km").strip().lower()
    aliases = {
        "km": "km",
        "kilometer": "km",
        "kilometers": "km",
        "kilometre": "km",
        "kilometres": "km",
        "nm": "nm",
        "nmi": "nm",
        "nautical_mile": "nm",
        "nautical_miles": "nm",
        "m": "m",
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
    }
    if unit not in aliases:
        raise ValueError(f"Unsupported distance unit '{raw}'. Supported: km, nm, m")
    return aliases[unit]


def _convert_radius_to_nm(values: pd.Series, unit_in: str) -> pd.Series:
    unit = _normalize_distance_unit(unit_in)
    radius = pd.to_numeric(values, errors="coerce").astype(float)
    if unit == "nm":
        return radius
    if unit == "km":
        return radius / 1.852
    return radius / 1852.0  # m -> nm


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    if "Time step" in df.columns:
        rename_map["Time step"] = "time_step"
    if "Latitude" in df.columns:
        rename_map["Latitude"] = "lat"
    if "Longitude" in df.columns:
        rename_map["Longitude"] = "lon"
    if "Minimum pressure" in df.columns:
        rename_map["Minimum pressure"] = "p_c"
    if "Maximum wind speed" in df.columns:
        rename_map["Maximum wind speed"] = "wind_max"
    if "Radius to maximum winds" in df.columns:
        rename_map["Radius to maximum winds"] = "rmax"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def _build_tracks_from_parquet(
    parquet_path: Path,
    *,
    provider_name: str,
    basin_id: int,
    timestep_hours: int,
    wind_unit_in: str,
    radius_unit_in: str,
    env_pressure_hpa: float,
    dataset_ids: set[int] | None = None,
) -> TCTracks:
    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing parquet dataset: {parquet_path}")

    df = pd.read_parquet(parquet_path)
    df = _normalize_columns(df)

    if "Basin ID" in df.columns:
        df = df[df["Basin ID"].astype(float) == float(basin_id)].copy()
    if dataset_ids is not None:
        if "dataset_id" not in df.columns:
            raise ValueError(f"dataset_ids filter requested but column 'dataset_id' is missing in {parquet_path}")
        df = df[df["dataset_id"].astype(int).isin(dataset_ids)].copy()
    if df.empty:
        raise ValueError(
            f"No rows remain after filters (Basin ID={basin_id}, dataset_ids={sorted(dataset_ids) if dataset_ids else 'all'}) on {parquet_path}"
        )

    required = {"Year", "track_id", "time_step", "lat", "lon", "p_c", "wind_max", "rmax"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns in {parquet_path}: {missing}")

    # STORM longitudes are often in [0, 360]; convert to [-180, 180] for consistency.
    df["lon"] = df["lon"].astype(float)
    df.loc[df["lon"] > 180.0, "lon"] = df.loc[df["lon"] > 180.0, "lon"] - 360.0
    df["wind_max"] = _convert_wind_to_mps(df["wind_max"], wind_unit_in)
    df["rmax"] = _convert_radius_to_nm(df["rmax"], radius_unit_in)

    df = df.sort_values(["track_id", "time_step"]).reset_index(drop=True)
    groups = df.groupby("track_id", sort=False)

    track_list: list[xr.Dataset] = []
    for idx, (track_id, grp) in enumerate(groups, start=1):
        grp = grp.sort_values("time_step").drop_duplicates(subset=["time_step"], keep="first")
        if grp.empty:
            continue

        # STORM uses 3-hourly indexing (0,1,2,...) by default.
        # CLIMADA expects per-step time deltas in hours, not cumulative index.
        step_idx = grp["time_step"].to_numpy(dtype=float)
        n_steps = len(step_idx)
        if n_steps >= 2:
            step_delta_idx = np.diff(step_idx)
            step_delta_idx = np.where(np.isfinite(step_delta_idx) & (step_delta_idx > 0.0), step_delta_idx, 1.0)
            time_step_hours = np.empty(n_steps, dtype=float)
            time_step_hours[1:] = step_delta_idx * float(timestep_hours)
            time_step_hours[0] = time_step_hours[1]
        else:
            time_step_hours = np.array([float(timestep_hours)], dtype=float)

        elapsed_hours = np.zeros(n_steps, dtype=float)
        if n_steps >= 2:
            elapsed_hours[1:] = np.cumsum(time_step_hours[1:])
        times = pd.Timestamp("2000-01-01") + pd.to_timedelta(elapsed_hours, unit="h")
        year = int(grp["Year"].iloc[0])
        category_raw = float(grp["Category"].max()) if "Category" in grp.columns else 0.0
        category = int(category_raw) if np.isfinite(category_raw) else 0
        central_pressure_hpa = grp["p_c"].to_numpy(dtype=float)
        env_pressure = np.maximum(central_pressure_hpa + 5.0, float(env_pressure_hpa))

        ds = xr.Dataset(
            {
                "time": (("time",), times),
                "lat": (("time",), grp["lat"].to_numpy(dtype=float)),
                "lon": (("time",), grp["lon"].to_numpy(dtype=float)),
                "time_step": (("time",), time_step_hours),
                "radius_max_wind": (("time",), grp["rmax"].to_numpy(dtype=float)),
                "max_sustained_wind": (("time",), grp["wind_max"].to_numpy(dtype=float)),
                "central_pressure": (("time",), central_pressure_hpa),
                "environmental_pressure": (("time",), env_pressure),
                "basin": (("time",), np.array(["NA"] * len(grp), dtype=object)),
            },
            attrs={
                "max_sustained_wind_unit": "m/s",
                "radius_max_wind_unit": "nm",
                "central_pressure_unit": "hPa",
                "sid": f"{provider_name}_{year}_{track_id}",
                "name": f"synthetic_{provider_name}_{year}_{track_id}",
                "orig_event_flag": False,
                "data_provider": provider_name,
                "id_no": int(idx),
                "category": category,
            },
        )
        track_list.append(ds)

    tracks = TCTracks()
    tracks.data = track_list
    return tracks


def _build_centroids(
    *,
    mode: str,
    centroids_from_hazard: Path,
    grid_lat_min: float,
    grid_lat_max: float,
    grid_lon_min: float,
    grid_lon_max: float,
    grid_step_deg: float,
) -> Centroids:
    if mode == "from_hazard":
        return Hazard.from_hdf5(str(centroids_from_hazard)).centroids

    if grid_step_deg <= 0:
        raise ValueError("grid_step_deg must be > 0")
    if grid_lat_max <= grid_lat_min or grid_lon_max <= grid_lon_min:
        raise ValueError("Invalid grid bounds for centroid generation")

    lat_vals = np.arange(grid_lat_min, grid_lat_max + (0.5 * grid_step_deg), grid_step_deg, dtype=float)
    lon_vals = np.arange(grid_lon_min, grid_lon_max + (0.5 * grid_step_deg), grid_step_deg, dtype=float)
    lat_grid, lon_grid = np.meshgrid(lat_vals, lon_vals, indexing="ij")
    centroids = Centroids.from_lat_lon(
        lat=lat_grid.reshape(-1),
        lon=lon_grid.reshape(-1),
        crs="EPSG:4326",
    )
    return centroids


def _build_hazard(tracks: TCTracks, centroids: Centroids) -> TropCyclone:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        return TropCyclone.from_tracks(
            tracks,
            centroids=centroids,
            ignore_distance_to_coast=True,
        )


def _write_hazard(hazard: TropCyclone, out_path: Path, label: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hazard.write_hdf5(str(out_path))
    print(f"Saved {label} hazard to {out_path}")
    print(f"{label} shape={hazard.intensity.shape} max_intensity={float(hazard.intensity.max()):.6f} nnz={hazard.intensity.data.size}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild STORM/STORM_CMCC NA tropical cyclone hazards for Guadeloupe centroids.")
    parser.add_argument("--build", choices=["storm", "cmcc", "both"], default="cmcc")
    parser.add_argument("--storm-parquet", default="/home/ubuntu/uploads/STORM/storm_ds")
    parser.add_argument("--cmcc-parquet", default="/home/ubuntu/uploads/STORM/storm_ds_CMCC")
    parser.add_argument("--centroids-from-hazard", default="/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe.h5")
    parser.add_argument("--out-storm", default="/home/ubuntu/uploads/sib_demo-main/scripts/tc_hazard_guadeloupe.h5")
    parser.add_argument("--out-cmcc", default="/home/ubuntu/uploads/sib_demo-main/scripts/tc_hazard_guadeloupe_CMCC.h5")
    parser.add_argument("--basin-id", type=int, default=1)
    parser.add_argument("--timestep-hours", type=int, default=3)
    parser.add_argument(
        "--centroids-mode",
        choices=["from_hazard", "grid"],
        default="from_hazard",
        help="Use existing centroids from hazard file or generate a regular lat/lon grid.",
    )
    parser.add_argument("--grid-lat-min", type=float, default=15.5)
    parser.add_argument("--grid-lat-max", type=float, default=16.96)
    parser.add_argument("--grid-lon-min", type=float, default=-62.48)
    parser.add_argument("--grid-lon-max", type=float, default=-60.66)
    parser.add_argument("--grid-step-deg", type=float, default=0.02)
    parser.add_argument(
        "--wind-unit-in",
        default="m/s",
        help="Input wind unit in parquet datasets. Supported: m/s, kn, km/h. Hazard output is always in m/s.",
    )
    parser.add_argument(
        "--radius-unit-in",
        default="km",
        help="Input radius-to-maximum-wind unit in parquet datasets. Supported: km, nm, m. Track value passed to CLIMADA is normalized to nm.",
    )
    parser.add_argument(
        "--dataset-ids",
        default="",
        help="Optional comma-separated dataset_id values to include (example: 0,1,2). Empty means all dataset_id values.",
    )
    parser.add_argument(
        "--env-pressure-hpa",
        type=float,
        default=1010.0,
        help="Environmental pressure assumption (hPa) when source data has no explicit p_env column.",
    )
    args = parser.parse_args()
    normalized_wind_unit = _normalize_wind_unit(args.wind_unit_in)
    normalized_radius_unit = _normalize_distance_unit(args.radius_unit_in)
    print(f"Wind unit convention: input={normalized_wind_unit}, output=m/s")
    print(f"Radius unit convention: input={normalized_radius_unit}, output=nm")

    dataset_ids: set[int] | None = None
    if str(args.dataset_ids).strip():
        dataset_ids = {int(x.strip()) for x in str(args.dataset_ids).split(",") if x.strip()}
        print(f"Applying dataset_id filter: {sorted(dataset_ids)}")

    centroids_from_hazard = Path(args.centroids_from_hazard)
    if args.centroids_mode == "from_hazard" and not centroids_from_hazard.exists():
        raise FileNotFoundError(f"Missing centroids source hazard: {centroids_from_hazard}")
    centroids = _build_centroids(
        mode=args.centroids_mode,
        centroids_from_hazard=centroids_from_hazard,
        grid_lat_min=float(args.grid_lat_min),
        grid_lat_max=float(args.grid_lat_max),
        grid_lon_min=float(args.grid_lon_min),
        grid_lon_max=float(args.grid_lon_max),
        grid_step_deg=float(args.grid_step_deg),
    )
    print(
        f"Centroids mode={args.centroids_mode} count={centroids.size} "
        f"grid_step_deg={args.grid_step_deg if args.centroids_mode == 'grid' else 'n/a'}"
    )

    if args.build in {"storm", "both"}:
        print("Building STORM NA tracks...")
        tracks_storm = _build_tracks_from_parquet(
            Path(args.storm_parquet),
            provider_name="STORM",
            basin_id=args.basin_id,
            timestep_hours=args.timestep_hours,
            wind_unit_in=normalized_wind_unit,
            radius_unit_in=normalized_radius_unit,
            env_pressure_hpa=float(args.env_pressure_hpa),
            dataset_ids=dataset_ids,
        )
        print(f"STORM tracks: {len(tracks_storm.data)}")
        hazard_storm = _build_hazard(tracks_storm, centroids)
        _write_hazard(hazard_storm, Path(args.out_storm), "STORM")

    if args.build in {"cmcc", "both"}:
        print("Building STORM_CMCC NA tracks...")
        tracks_cmcc = _build_tracks_from_parquet(
            Path(args.cmcc_parquet),
            provider_name="STORM_CMCC",
            basin_id=args.basin_id,
            timestep_hours=args.timestep_hours,
            wind_unit_in=normalized_wind_unit,
            radius_unit_in=normalized_radius_unit,
            env_pressure_hpa=float(args.env_pressure_hpa),
            dataset_ids=dataset_ids,
        )
        print(f"STORM_CMCC tracks: {len(tracks_cmcc.data)}")
        hazard_cmcc = _build_hazard(tracks_cmcc, centroids)
        _write_hazard(hazard_cmcc, Path(args.out_cmcc), "STORM_CMCC")


if __name__ == "__main__":
    main()
