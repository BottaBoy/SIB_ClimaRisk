#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
from pathlib import Path
from typing import Iterable

from climada.hazard import Hazard

from rebuild_tc_hazard_na import (
    _build_centroids,
    _build_hazard,
    _build_tracks_from_parquet,
    _normalize_distance_unit,
    _normalize_wind_unit,
)


def _parse_dataset_ids(raw: str) -> list[int]:
    txt = str(raw or "").strip()
    if not txt:
        return list(range(10))
    ids = []
    for part in txt.split(","):
        p = part.strip()
        if not p:
            continue
        ids.append(int(p))
    return sorted(set(ids))


def _build_one_block(
    *,
    parquet_path: Path,
    provider_name: str,
    basin_id: int,
    timestep_hours: int,
    wind_unit_in: str,
    radius_unit_in: str,
    env_pressure_hpa: float,
    dataset_id: int,
    centroids,
    out_block: Path,
) -> None:
    print(f"[{provider_name}] block dataset_id={dataset_id} -> {out_block}", flush=True)
    tracks = _build_tracks_from_parquet(
        parquet_path,
        provider_name=provider_name,
        basin_id=basin_id,
        timestep_hours=timestep_hours,
        wind_unit_in=wind_unit_in,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
        dataset_ids={dataset_id},
    )
    print(f"[{provider_name}] tracks in block {dataset_id}: {len(tracks.data)}", flush=True)
    hazard = _build_hazard(tracks, centroids)
    out_block.parent.mkdir(parents=True, exist_ok=True)
    hazard.write_hdf5(str(out_block))
    print(
        f"[{provider_name}] wrote block {dataset_id}: "
        f"shape={hazard.intensity.shape} max_intensity={float(hazard.intensity.max()):.6f} nnz={hazard.intensity.nnz}",
        flush=True,
    )
    del tracks
    del hazard
    gc.collect()


def _merge_blocks(block_paths: Iterable[Path], out_path: Path, label: str) -> None:
    paths = [p for p in block_paths if p.exists()]
    if not paths:
        raise FileNotFoundError(f"No block hazards found for {label}")

    merged = Hazard.from_hdf5(str(paths[0]))
    print(f"[{label}] merge start with {paths[0].name}", flush=True)
    for path in paths[1:]:
        nxt = Hazard.from_hdf5(str(path))
        merged.append(nxt)
        print(
            f"[{label}] merged {path.name} -> events={merged.event_id.size} "
            f"centroids={merged.centroids.size} nnz={merged.intensity.nnz}",
            flush=True,
        )
        del nxt
        gc.collect()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.write_hdf5(str(out_path))
    print(
        f"[{label}] final written to {out_path} "
        f"(events={merged.event_id.size}, centroids={merged.centroids.size}, "
        f"max_intensity={float(merged.intensity.max()):.6f}, nnz={merged.intensity.nnz})",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild STORM/STORM_CMCC NA hazards in memory-safe blocks (dataset_id 0..9) then merge."
    )
    parser.add_argument("--build", choices=["storm", "cmcc", "both"], default="both")
    parser.add_argument("--storm-parquet", default="/home/ubuntu/uploads/STORM/storm_ds")
    parser.add_argument("--cmcc-parquet", default="/home/ubuntu/uploads/STORM/storm_ds_CMCC")
    parser.add_argument("--out-storm", default="/home/ubuntu/uploads/sib_demo-main/scripts/tc_hazard_guadeloupe.h5")
    parser.add_argument("--out-cmcc", default="/home/ubuntu/uploads/sib_demo-main/scripts/tc_hazard_guadeloupe_CMCC.h5")
    parser.add_argument("--tmp-dir", default="/tmp")
    parser.add_argument("--dataset-ids", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--basin-id", type=int, default=1)
    parser.add_argument("--timestep-hours", type=int, default=3)
    parser.add_argument("--wind-unit-in", default="m/s")
    parser.add_argument("--radius-unit-in", default="km")
    parser.add_argument("--env-pressure-hpa", type=float, default=1010.0)
    parser.add_argument("--centroids-mode", choices=["grid", "from_hazard"], default="grid")
    parser.add_argument("--centroids-from-hazard", default="/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe.h5")
    parser.add_argument("--grid-lat-min", type=float, default=15.5)
    parser.add_argument("--grid-lat-max", type=float, default=16.96)
    parser.add_argument("--grid-lon-min", type=float, default=-62.48)
    parser.add_argument("--grid-lon-max", type=float, default=-60.66)
    parser.add_argument("--grid-step-deg", type=float, default=0.02)
    parser.add_argument("--reuse-blocks", action="store_true", help="Skip rebuilding a block if its HDF5 file already exists.")
    args = parser.parse_args()

    wind_unit = _normalize_wind_unit(args.wind_unit_in)
    radius_unit = _normalize_distance_unit(args.radius_unit_in)
    dataset_ids = _parse_dataset_ids(args.dataset_ids)

    centroids = _build_centroids(
        mode=args.centroids_mode,
        centroids_from_hazard=Path(args.centroids_from_hazard),
        grid_lat_min=float(args.grid_lat_min),
        grid_lat_max=float(args.grid_lat_max),
        grid_lon_min=float(args.grid_lon_min),
        grid_lon_max=float(args.grid_lon_max),
        grid_step_deg=float(args.grid_step_deg),
    )
    print(
        f"Centroids mode={args.centroids_mode} count={centroids.size} "
        f"grid_step_deg={args.grid_step_deg if args.centroids_mode == 'grid' else 'n/a'}",
        flush=True,
    )

    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    if args.build in {"storm", "both"}:
        storm_blocks: list[Path] = []
        for dsid in dataset_ids:
            out_block = tmp_dir / f"tc_hazard_guadeloupe_storm_block_{dsid}.h5"
            storm_blocks.append(out_block)
            if args.reuse_blocks and out_block.exists():
                print(f"[STORM] reuse block dataset_id={dsid}: {out_block}", flush=True)
                continue
            _build_one_block(
                parquet_path=Path(args.storm_parquet),
                provider_name="STORM",
                basin_id=int(args.basin_id),
                timestep_hours=int(args.timestep_hours),
                wind_unit_in=wind_unit,
                radius_unit_in=radius_unit,
                env_pressure_hpa=float(args.env_pressure_hpa),
                dataset_id=int(dsid),
                centroids=centroids,
                out_block=out_block,
            )
        _merge_blocks(storm_blocks, Path(args.out_storm), "STORM")

    if args.build in {"cmcc", "both"}:
        cmcc_blocks: list[Path] = []
        for dsid in dataset_ids:
            out_block = tmp_dir / f"tc_hazard_guadeloupe_cmcc_block_{dsid}.h5"
            cmcc_blocks.append(out_block)
            if args.reuse_blocks and out_block.exists():
                print(f"[STORM_CMCC] reuse block dataset_id={dsid}: {out_block}", flush=True)
                continue
            _build_one_block(
                parquet_path=Path(args.cmcc_parquet),
                provider_name="STORM_CMCC",
                basin_id=int(args.basin_id),
                timestep_hours=int(args.timestep_hours),
                wind_unit_in=wind_unit,
                radius_unit_in=radius_unit,
                env_pressure_hpa=float(args.env_pressure_hpa),
                dataset_id=int(dsid),
                centroids=centroids,
                out_block=out_block,
            )
        _merge_blocks(cmcc_blocks, Path(args.out_cmcc), "STORM_CMCC")


if __name__ == "__main__":
    main()

