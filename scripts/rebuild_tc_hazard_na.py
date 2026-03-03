#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import xarray as xr
from climada.hazard import Hazard, TCTracks, TropCyclone


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

    df = df.sort_values(["track_id", "time_step"]).reset_index(drop=True)
    groups = df.groupby("track_id", sort=False)

    track_list: list[xr.Dataset] = []
    for idx, (track_id, grp) in enumerate(groups, start=1):
        grp = grp.sort_values("time_step").drop_duplicates(subset=["time_step"], keep="first")
        if grp.empty:
            continue

        times = pd.Timestamp("2000-01-01") + pd.to_timedelta(grp["time_step"].to_numpy(dtype=float) * float(timestep_hours), unit="h")
        year = int(grp["Year"].iloc[0])
        category_raw = float(grp["Category"].max()) if "Category" in grp.columns else 0.0
        category = int(category_raw) if np.isfinite(category_raw) else 0

        ds = xr.Dataset(
            {
                "time": (("time",), times),
                "lat": (("time",), grp["lat"].to_numpy(dtype=float)),
                "lon": (("time",), grp["lon"].to_numpy(dtype=float)),
                "time_step": (("time",), grp["time_step"].to_numpy(dtype=float)),
                "radius_max_wind": (("time",), grp["rmax"].to_numpy(dtype=float)),
                "max_sustained_wind": (("time",), grp["wind_max"].to_numpy(dtype=float)),
                "central_pressure": (("time",), grp["p_c"].to_numpy(dtype=float)),
                "environmental_pressure": (("time",), grp["p_c"].to_numpy(dtype=float) + 15.0),
                "basin": (("time",), np.array(["NA"] * len(grp), dtype=object)),
            },
            attrs={
                "max_sustained_wind_unit": "m/s",
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


def _build_hazard(tracks: TCTracks, centroids_from_hazard: Path) -> TropCyclone:
    centroids = Hazard.from_hdf5(str(centroids_from_hazard)).centroids
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        return TropCyclone.from_tracks(tracks, centroids=centroids)


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
        "--dataset-ids",
        default="",
        help="Optional comma-separated dataset_id values to include (example: 0,1,2). Empty means all dataset_id values.",
    )
    args = parser.parse_args()

    dataset_ids: set[int] | None = None
    if str(args.dataset_ids).strip():
        dataset_ids = {int(x.strip()) for x in str(args.dataset_ids).split(",") if x.strip()}
        print(f"Applying dataset_id filter: {sorted(dataset_ids)}")

    centroids_from_hazard = Path(args.centroids_from_hazard)
    if not centroids_from_hazard.exists():
        raise FileNotFoundError(f"Missing centroids source hazard: {centroids_from_hazard}")

    if args.build in {"storm", "both"}:
        print("Building STORM NA tracks...")
        tracks_storm = _build_tracks_from_parquet(
            Path(args.storm_parquet),
            provider_name="STORM",
            basin_id=args.basin_id,
            timestep_hours=args.timestep_hours,
            dataset_ids=dataset_ids,
        )
        print(f"STORM tracks: {len(tracks_storm.data)}")
        hazard_storm = _build_hazard(tracks_storm, centroids_from_hazard)
        _write_hazard(hazard_storm, Path(args.out_storm), "STORM")

    if args.build in {"cmcc", "both"}:
        print("Building STORM_CMCC NA tracks...")
        tracks_cmcc = _build_tracks_from_parquet(
            Path(args.cmcc_parquet),
            provider_name="STORM_CMCC",
            basin_id=args.basin_id,
            timestep_hours=args.timestep_hours,
            dataset_ids=dataset_ids,
        )
        print(f"STORM_CMCC tracks: {len(tracks_cmcc.data)}")
        hazard_cmcc = _build_hazard(tracks_cmcc, centroids_from_hazard)
        _write_hazard(hazard_cmcc, Path(args.out_cmcc), "STORM_CMCC")


if __name__ == "__main__":
    main()
