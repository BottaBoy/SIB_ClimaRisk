#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import warnings

import netCDF4 as nc
import numpy as np
import xarray as xr

from climada.hazard.tc_tracks import (
    BASIN_ENV_PRESSURE,
    IBTRACS_AGENCIES,
    SAFFIR_SIM_CAT,
    _estimate_pressure,
    _estimate_vmax,
    estimate_rmw,
    estimate_roci,
    ibtracs_add_official_variable,
)


def _normalize_lon(lon: float) -> float:
    out = float(lon)
    while out > 180.0:
        out -= 360.0
    while out < -180.0:
        out += 360.0
    return out


def _masked_numeric(values):
    masked = np.ma.asarray(values, dtype=float)
    return np.asarray(masked.filled(np.nan), dtype=float)


def _char_bytes(values):
    return nc.chartostring(values).astype("S")


def _build_track_payload(args: argparse.Namespace) -> dict[str, object]:
    root = nc.Dataset(str(Path(args.ibtracs_file).expanduser()), mode="r")
    try:
        sid_values = _char_bytes(root.variables["sid"][:]).astype(str)
        if args.storm_id:
            storm_mask = sid_values == str(args.storm_id)
        else:
            name_values = _char_bytes(root.variables["name"][:]).astype(str)
            storm_mask = np.char.upper(name_values) == str(args.name).strip().upper()
        if "season" in root.variables and int(args.season) > 0:
            season_values = np.asarray(root.variables["season"][:], dtype=int)
            storm_mask = storm_mask & (season_values == int(args.season))

        matched_indices = np.nonzero(np.asarray(storm_mask, dtype=bool))[0]
        if matched_indices.size == 0:
            raise ValueError(
                f"No IBTrACS cyclone matched preset={args.preset_id} "
                f"(storm_id={args.storm_id or 'n/a'}, name={args.name!r}, season={int(args.season)}, basin={args.basin!r})"
            )
        if matched_indices.size > 1:
            matched_ids = sid_values[matched_indices].tolist()
            raise ValueError(f"Multiple IBTrACS cyclones matched preset={args.preset_id}: {matched_ids}")

        storm_sel = matched_indices.tolist()
        data_vars: dict[str, tuple[tuple[str, ...], object]] = {}
        coords = {
            "storm": ("storm", np.arange(len(storm_sel), dtype=int)),
            "date_time": ("date_time", np.arange(root.dimensions["date_time"].size, dtype=int)),
        }
        for dim_name in root.dimensions:
            if dim_name in {"storm", "date_time"}:
                continue
            coords[dim_name] = (dim_name, np.arange(root.dimensions[dim_name].size, dtype=int))

        phys_vars = ["lat", "lon", "wind", "pres", "rmw", "poci", "roci"]
        raw_var_names = {"sid", "name", "season", "basin", "time", "wmo_agency", *phys_vars}
        for tc_var in phys_vars:
            for agency in IBTRACS_AGENCIES:
                candidate = f"{agency}_{tc_var}"
                if candidate in root.variables:
                    raw_var_names.add(candidate)

        for var_name in sorted(raw_var_names):
            if var_name not in root.variables:
                continue
            variable = root.variables[var_name]
            values = variable[storm_sel, ...] if variable.dimensions and variable.dimensions[0] == "storm" else variable[:]
            dims = tuple(variable.dimensions)
            if var_name == "time":
                units = getattr(variable, "units", None)
                calendar = getattr(variable, "calendar", "standard")
                time_objects = nc.num2date(values, units=units, calendar=calendar, only_use_cftime_datetimes=False)
                values = np.asarray(time_objects, dtype="datetime64[ns]")
            elif getattr(variable, "dtype", None).kind in {"S", "U"} or (hasattr(variable, "dtype") and str(variable.dtype) == "|S1"):
                values = _char_bytes(values)
                dims = dims[:-1]
            elif np.issubdtype(getattr(variable, "dtype", np.dtype("float64")), np.number):
                values = _masked_numeric(values)
            data_vars[var_name] = (dims, values)

        ibtracs_ds = xr.Dataset(data_vars=data_vars, coords=coords)
    finally:
        root.close()

    ibtracs_ds["valid_t"] = ibtracs_ds["time"].notnull()
    provider = ["official_3h"]
    phys_vars = ["lat", "lon", "wind", "pres", "rmw", "poci", "roci"]
    for tc_var in phys_vars:
        ibtracs_add_official_variable(ibtracs_ds, tc_var, add_3h=True)
        ag_vars = [f"{ag}_{tc_var}" for ag in provider if f"{ag}_{tc_var}" in ibtracs_ds.data_vars.keys()]
        if len(ag_vars) == 0:
            ag_vars = [f"{provider[0]}_{tc_var}"]
            ibtracs_ds[ag_vars[0]] = xr.full_like(ibtracs_ds[f"usa_{tc_var}"], np.nan)
        all_vals = ibtracs_ds[ag_vars].to_array(dim="agency")
        preferred_idx = all_vals.notnull().any(dim="date_time").argmax(dim="agency")
        ibtracs_ds[tc_var] = all_vals.isel(agency=preferred_idx)
        selected_ags = np.array([v[: -len(f"_{tc_var}")].encode() for v in ag_vars])
        ibtracs_ds[f"{tc_var}_agency"] = ("storm", selected_ags[preferred_idx.values])

        if tc_var == "lon":
            lons = ibtracs_ds[tc_var].values.copy()
            lon_valid_mask = np.isfinite(lons)
            lons[lon_valid_mask] = np.vectorize(_normalize_lon)(lons[lon_valid_mask])
            ibtracs_ds[tc_var].values[:] = lons
            crossing_mask = (
                (ibtracs_ds[tc_var] > 170).any(dim="date_time")
                & (ibtracs_ds[tc_var] < -170).any(dim="date_time")
                & (ibtracs_ds[tc_var] < 0)
            ).values
            ibtracs_ds[tc_var].values[crossing_mask] += 360

        with warnings.catch_warnings():
            warnings.simplefilter(action="ignore", category=FutureWarning)
            nonsingular_mask = (ibtracs_ds[tc_var].notnull().sum(dim="date_time") > 1).values
            if nonsingular_mask.sum() > 0:
                ibtracs_ds[tc_var].values[nonsingular_mask] = (
                    ibtracs_ds[tc_var].sel(storm=nonsingular_mask).interpolate_na(dim="date_time", method="linear")
                )

    ibtracs_ds = ibtracs_ds[
        ["sid", "name", "basin", "time", "valid_t"] + phys_vars + [f"{v}_agency" for v in phys_vars]
    ]
    ibtracs_ds["pres"][:] = _estimate_pressure(
        ibtracs_ds["pres"], ibtracs_ds["lat"], ibtracs_ds["lon"], ibtracs_ds["wind"]
    )
    ibtracs_ds["wind"][:] = _estimate_vmax(
        ibtracs_ds["wind"], ibtracs_ds["lat"], ibtracs_ds["lon"], ibtracs_ds["pres"]
    )

    ibtracs_ds["valid_t"] &= (
        ibtracs_ds["lat"].notnull()
        & ibtracs_ds["lon"].notnull()
        & ibtracs_ds["wind"].notnull()
        & ibtracs_ds["pres"].notnull()
    )
    valid_storms_mask = ibtracs_ds["valid_t"].sum(dim="date_time") > 1
    if not bool(valid_storms_mask.values[0]):
        raise ValueError(f"IBTrACS cyclone {args.storm_id or args.name} does not expose at least two valid timesteps")

    max_wind = ibtracs_ds["wind"].max(dim="date_time").data.ravel()
    category_test = max_wind[:, None] < np.array(SAFFIR_SIM_CAT)[None]
    category = np.argmax(category_test, axis=1) - 1
    basin_map = {b.encode("utf-8"): v for b, v in BASIN_ENV_PRESSURE.items()}
    basin_fun = lambda b: basin_map[b]

    t_msk = ibtracs_ds["valid_t"].data[0]
    track_ds = ibtracs_ds.sel(storm=0, date_time=t_msk)
    tr_basin_penv = xr.apply_ufunc(basin_fun, track_ds.basin, vectorize=True)
    if str(args.basin or "").strip() and str(args.basin).encode() not in track_ds.basin.values:
        raise ValueError(
            f"Resolved cyclone {args.storm_id or args.name} does not intersect requested basin {args.basin!r}"
        )
    if (track_ds["lon"].values > 180).all():
        track_ds["lon"] -= 360

    track_ds["time_step"] = xr.ones_like(track_ds["time"], dtype=float)
    if track_ds["time"].size > 1:
        track_ds["time_step"].values[1:] = track_ds["time"].diff(dim="date_time") / np.timedelta64(1, "h")
        track_ds["time_step"].values[0] = track_ds["time_step"][1]

    with warnings.catch_warnings():
        warnings.simplefilter(action="ignore", category=FutureWarning)
        track_ds["rmw"] = track_ds["rmw"].ffill(dim="date_time", limit=1).bfill(dim="date_time", limit=1).fillna(0)
        track_ds["roci"] = track_ds["roci"].ffill(dim="date_time", limit=1).bfill(dim="date_time", limit=1).fillna(0)
        track_ds["poci"] = track_ds["poci"].ffill(dim="date_time", limit=4).bfill(dim="date_time", limit=4)
        track_ds["poci"] = track_ds["poci"].fillna(tr_basin_penv)

    track_ds["rmw"][:] = estimate_rmw(track_ds["rmw"].values, track_ds["pres"].values)
    track_ds["roci"][:] = estimate_roci(track_ds["roci"].values, track_ds["pres"].values)
    track_ds["roci"][:] = np.fmax(track_ds["rmw"].values, track_ds["roci"].values)
    track_ds["poci"][:] = np.fmax(track_ds["poci"], track_ds["pres"])

    sid = str(track_ds["sid"].astype(str).item())
    return {
        "coords": {
            "time": [
                np.datetime_as_string(np.datetime64(value, "ns"), unit="s")
                for value in track_ds["time"].dt.round("s").values
            ],
            "lat": track_ds["lat"].values.astype(float).tolist(),
            "lon": track_ds["lon"].values.astype(float).tolist(),
        },
        "data_vars": {
            "radius_max_wind": track_ds["rmw"].values.astype(float).tolist(),
            "radius_oci": track_ds["roci"].values.astype(float).tolist(),
            "max_sustained_wind": track_ds["wind"].values.astype(float).tolist(),
            "central_pressure": track_ds["pres"].values.astype(float).tolist(),
            "environmental_pressure": track_ds["poci"].values.astype(float).tolist(),
            "time_step": track_ds["time_step"].values.astype(float).tolist(),
            "basin": track_ds["basin"].astype(str).values.tolist(),
        },
        "attrs": {
            "max_sustained_wind_unit": "kn",
            "central_pressure_unit": "mb",
            "orig_event_flag": True,
            "data_provider": "ibtracs_official_3h_manual",
            "category": int(category[0]),
            "name": str(track_ds["name"].astype(str).item()),
            "sid": sid,
            "id_no": float(sid.replace("N", "0").replace("S", "1")),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract one targeted IBTrACS storm as JSON payload.")
    parser.add_argument("--ibtracs-file", required=True)
    parser.add_argument("--preset-id", required=True)
    parser.add_argument("--storm-id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--basin", required=True)
    args = parser.parse_args()
    payload = _build_track_payload(args)
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
