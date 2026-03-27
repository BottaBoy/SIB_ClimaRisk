from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any, Iterable
import copy
import threading

from .errors import DependencyMissingError


@dataclass(frozen=True)
class BasinCoverage:
    basin_id: int
    code: str
    label: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


DEFAULT_BASIN_COVERAGES: tuple[BasinCoverage, ...] = (
    BasinCoverage(
        basin_id=1,
        code="NA",
        label="North Atlantic",
        lat_min=5.0,
        lat_max=60.0,
        lon_min=-105.0,
        lon_max=-1.0,
    ),
)


@dataclass
class HazardBundle:
    storm: Any
    storm_cmcc: Any
    storm_years: int
    normalized_on_copy: bool = True
    source: str = "precomputed_hdf5"
    basin_ids: tuple[int, ...] = ()
    point_count: int = 0
    tracks_storm: Any | None = None
    tracks_storm_cmcc: Any | None = None
    centroids: Any | None = None


@dataclass(frozen=True)
class SpatialWindow:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    center_lat: float
    center_lon: float


_TRACK_CACHE_LOCK = threading.Lock()
_TRACK_CACHE: OrderedDict[
    tuple[str, str, tuple[int, ...], str, str, float, tuple[float, float, float, float] | None, int],
    Any,
] = OrderedDict()

logger = logging.getLogger(__name__)

DEFAULT_SPATIAL_PADDING_DEG = 4.0
DEFAULT_MAX_TRACKS = 4000
DEFAULT_TRACK_CACHE_MAX_ENTRIES = 8
DEFAULT_SMALL_SAMPLE_GRID_STEP_DEG = 0.01
DEFAULT_SMALL_SAMPLE_GRID_THRESHOLD = 50


def _resolve_track_cache_limit(track_cache_max_entries: int | None) -> int:
    if track_cache_max_entries is not None:
        try:
            return int(track_cache_max_entries)
        except Exception:
            logger.warning(
                "Invalid explicit track cache size (%r); using default=%d",
                track_cache_max_entries,
                DEFAULT_TRACK_CACHE_MAX_ENTRIES,
            )
            return DEFAULT_TRACK_CACHE_MAX_ENTRIES
    raw = os.environ.get("SIB_RISK_TRACK_CACHE_MAX_ENTRIES")
    if raw is None:
        return DEFAULT_TRACK_CACHE_MAX_ENTRIES
    try:
        return int(raw)
    except Exception:
        logger.warning(
            "Invalid SIB_RISK_TRACK_CACHE_MAX_ENTRIES=%r; using default=%d",
            raw,
            DEFAULT_TRACK_CACHE_MAX_ENTRIES,
        )
        return DEFAULT_TRACK_CACHE_MAX_ENTRIES


def _normalize_frequency_safe(hazard_obj: Any, storm_years: int) -> Any:
    hazard_copy = copy.deepcopy(hazard_obj)
    freq = getattr(hazard_copy, "frequency", None)
    if freq is None:
        return hazard_copy

    # Idempotent normalization marker to avoid double-dividing in reused objects.
    if getattr(hazard_copy, "_sib_frequency_normalized", False):
        return hazard_copy

    try:
        hazard_copy.frequency = freq / float(storm_years)
        setattr(hazard_copy, "_sib_frequency_normalized", True)
    except Exception as exc:
        logger.warning(
            "Failed to normalize hazard frequency on copy (%s): %s",
            type(exc).__name__,
            exc,
        )
    return hazard_copy


def list_default_basin_coverages() -> list[dict[str, Any]]:
    return [
        {
            "basin_id": int(item.basin_id),
            "code": str(item.code),
            "label": str(item.label),
            "lat_min": float(item.lat_min),
            "lat_max": float(item.lat_max),
            "lon_min": float(item.lon_min),
            "lon_max": float(item.lon_max),
        }
        for item in DEFAULT_BASIN_COVERAGES
    ]


def _normalize_lon(lon: float) -> float:
    out = float(lon)
    while out > 180.0:
        out -= 360.0
    while out < -180.0:
        out += 360.0
    return out


def _lon_in_bbox(lon: float, lon_min: float, lon_max: float) -> bool:
    if lon_min <= lon_max:
        return lon_min <= lon <= lon_max
    # Dateline wrap
    return lon >= lon_min or lon <= lon_max


def _point_in_basin(lat: float, lon: float, basin: BasinCoverage) -> bool:
    if lat < float(basin.lat_min) or lat > float(basin.lat_max):
        return False
    return _lon_in_bbox(_normalize_lon(lon), float(basin.lon_min), float(basin.lon_max))


def _build_spatial_window(
    point_coords: Iterable[tuple[float, float]],
    *,
    padding_deg: float,
) -> SpatialWindow | None:
    lat_vals: list[float] = []
    lon_vals: list[float] = []
    for lat, lon in point_coords:
        try:
            latf = float(lat)
            lonf = _normalize_lon(float(lon))
        except Exception:
            continue
        if not (-90.0 <= latf <= 90.0):
            continue
        lat_vals.append(latf)
        lon_vals.append(lonf)

    if not lat_vals or not lon_vals:
        return None

    pad = max(0.0, float(padding_deg))
    lat_min = max(-90.0, min(lat_vals) - pad)
    lat_max = min(90.0, max(lat_vals) + pad)

    lon_min_raw = min(lon_vals)
    lon_max_raw = max(lon_vals)
    # When points span the dateline we cannot represent a compact bbox
    # with this simple min/max; keep full longitude range in that case.
    if (lon_max_raw - lon_min_raw) > 180.0:
        lon_min = -180.0
        lon_max = 180.0
        center_lon = 0.0
    else:
        lon_min = max(-180.0, lon_min_raw - pad)
        lon_max = min(180.0, lon_max_raw + pad)
        center_lon = _normalize_lon((lon_min_raw + lon_max_raw) / 2.0)

    center_lat = (min(lat_vals) + max(lat_vals)) / 2.0
    return SpatialWindow(
        lat_min=float(lat_min),
        lat_max=float(lat_max),
        lon_min=float(lon_min),
        lon_max=float(lon_max),
        center_lat=float(center_lat),
        center_lon=float(center_lon),
    )


def _basin_ids_for_points(
    point_coords: Iterable[tuple[float, float]],
    basins: tuple[BasinCoverage, ...],
) -> tuple[int, ...]:
    if not basins:
        return (1,)
    selected: set[int] = set()
    any_point = False
    for lat, lon in point_coords:
        any_point = True
        if lat is None or lon is None:
            continue
        try:
            latf = float(lat)
            lonf = float(lon)
        except Exception:
            continue
        if not (-90.0 <= latf <= 90.0):
            continue
        for basin in basins:
            if _point_in_basin(latf, lonf, basin):
                selected.add(int(basin.basin_id))
    if selected:
        return tuple(sorted(selected))
    if not any_point:
        return (int(basins[0].basin_id),)
    # Unknown zone: keep all configured basins to avoid false negatives.
    return tuple(sorted({int(basin.basin_id) for basin in basins}))


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


def _convert_wind_to_mps(values: Any, unit_in: str) -> Any:
    import pandas as pd  # type: ignore

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


def _convert_radius_to_nm(values: Any, unit_in: str) -> Any:
    import pandas as pd  # type: ignore

    unit = _normalize_distance_unit(unit_in)
    radius = pd.to_numeric(values, errors="coerce").astype(float)
    if unit == "nm":
        return radius
    if unit == "km":
        return radius / 1.852
    return radius / 1852.0  # m -> nm


def _normalize_columns(df: Any) -> Any:
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
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None = None,
    max_tracks: int = DEFAULT_MAX_TRACKS,
    timestep_hours: int = 3,
    wind_unit_in: str = "m/s",
    radius_unit_in: str = "km",
    env_pressure_hpa: float = 1010.0,
) -> Any:
    try:
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
        import xarray as xr  # type: ignore
        from climada.hazard import TCTracks  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("CLIMADA runtime dependencies are required to build hazards from parquet") from exc

    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing parquet dataset: {parquet_path}")

    read_kwargs: dict[str, Any] = {}
    if basin_ids:
        read_kwargs["filters"] = [("Basin ID", "in", [int(b) for b in basin_ids])]
    try:
        df = pd.read_parquet(parquet_path, **read_kwargs)
    except Exception as exc:
        logger.warning(
            "Parquet predicate read failed for %s (filters=%s, %s: %s); retrying full read",
            parquet_path,
            read_kwargs.get("filters"),
            type(exc).__name__,
            exc,
        )
        df = pd.read_parquet(parquet_path)
    df = _normalize_columns(df)

    if "Basin ID" in df.columns and basin_ids:
        df = df[df["Basin ID"].astype(int).isin([int(b) for b in basin_ids])].copy()
    if df.empty:
        raise ValueError(f"No rows remain after basin filter {list(basin_ids)} on {parquet_path}")

    required = {"Year", "track_id", "time_step", "lat", "lon", "p_c", "wind_max", "rmax"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns in {parquet_path}: {missing}")

    df["lon"] = df["lon"].astype(float)
    df.loc[df["lon"] > 180.0, "lon"] = df.loc[df["lon"] > 180.0, "lon"] - 360.0

    if spatial_window is not None:
        lat_mask = df["lat"].astype(float).between(float(spatial_window.lat_min), float(spatial_window.lat_max))
        if spatial_window.lon_min <= spatial_window.lon_max:
            lon_mask = df["lon"].astype(float).between(float(spatial_window.lon_min), float(spatial_window.lon_max))
        else:
            lon_mask = (df["lon"].astype(float) >= float(spatial_window.lon_min)) | (df["lon"].astype(float) <= float(spatial_window.lon_max))
        df = df[lat_mask & lon_mask].copy()
        if df.empty:
            raise ValueError(
                "No rows remain after spatial filter "
                f"lat=[{spatial_window.lat_min:.3f},{spatial_window.lat_max:.3f}] "
                f"lon=[{spatial_window.lon_min:.3f},{spatial_window.lon_max:.3f}] on {parquet_path}"
            )

    try:
        max_tracks_int = int(max_tracks)
    except Exception as exc:
        logger.warning(
            "Invalid max_tracks=%r (%s: %s); using default=%d",
            max_tracks,
            type(exc).__name__,
            exc,
            DEFAULT_MAX_TRACKS,
        )
        max_tracks_int = DEFAULT_MAX_TRACKS
    if max_tracks_int > 0:
        track_count = int(df["track_id"].nunique(dropna=True))
        if track_count > max_tracks_int:
            lat_center = float(spatial_window.center_lat if spatial_window is not None else df["lat"].astype(float).mean())
            lon_center = float(spatial_window.center_lon if spatial_window is not None else df["lon"].astype(float).mean())
            dlat = df["lat"].astype(float) - lat_center
            dlon = (df["lon"].astype(float) - lon_center).abs()
            dlon = dlon.where(dlon <= 180.0, 360.0 - dlon)
            dist2 = (dlat * dlat) + (dlon * dlon)
            ranked_tracks = (
                df.assign(_dist2=dist2)
                .groupby("track_id", sort=False)["_dist2"]
                .min()
                .nsmallest(max_tracks_int)
            )
            keep_track_ids = set(ranked_tracks.index.tolist())
            df = df[df["track_id"].isin(keep_track_ids)].copy()

    df["wind_max"] = _convert_wind_to_mps(df["wind_max"], wind_unit_in)
    df["rmax"] = _convert_radius_to_nm(df["rmax"], radius_unit_in)

    df = df.sort_values(["track_id", "time_step"]).reset_index(drop=True)
    groups = df.groupby("track_id", sort=False)

    track_list: list[Any] = []
    for idx, (track_id, grp) in enumerate(groups, start=1):
        grp = grp.sort_values("time_step").drop_duplicates(subset=["time_step"], keep="first")
        if grp.empty:
            continue

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


def _get_or_build_tracks(
    parquet_path: Path,
    *,
    provider_name: str,
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None,
    max_tracks: int,
    wind_unit_in: str,
    radius_unit_in: str,
    env_pressure_hpa: float,
    track_cache_max_entries: int | None = None,
) -> Any:
    window_key = None
    if spatial_window is not None:
        window_key = (
            round(float(spatial_window.lat_min), 4),
            round(float(spatial_window.lat_max), 4),
            round(float(spatial_window.lon_min), 4),
            round(float(spatial_window.lon_max), 4),
        )
    cache_key = (
        str(parquet_path.expanduser().resolve(strict=False)),
        str(provider_name),
        tuple(sorted(int(b) for b in basin_ids)),
        str(wind_unit_in),
        str(radius_unit_in),
        float(env_pressure_hpa),
        window_key,
        int(max_tracks),
    )
    cache_limit = _resolve_track_cache_limit(track_cache_max_entries)
    if cache_limit != 0:
        with _TRACK_CACHE_LOCK:
            cached = _TRACK_CACHE.get(cache_key)
            if cached is not None:
                _TRACK_CACHE.move_to_end(cache_key)
                return cached

    tracks = _build_tracks_from_parquet(
        parquet_path,
        provider_name=provider_name,
        basin_ids=tuple(sorted(int(b) for b in basin_ids)),
        spatial_window=spatial_window,
        max_tracks=max_tracks,
        wind_unit_in=wind_unit_in,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
    )
    if cache_limit == 0:
        return tracks
    with _TRACK_CACHE_LOCK:
        _TRACK_CACHE[cache_key] = tracks
        _TRACK_CACHE.move_to_end(cache_key)
        if cache_limit > 0:
            while len(_TRACK_CACHE) > cache_limit:
                evicted_key, _ = _TRACK_CACHE.popitem(last=False)
                logger.debug("Evicted dynamic track cache entry: %s", evicted_key)
    return tracks


def _build_centroids_from_points(point_coords: Iterable[tuple[float, float]]) -> Any:
    try:
        from climada.hazard import Centroids  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("CLIMADA is required to build centroids for dynamic hazards") from exc

    seen: set[tuple[float, float]] = set()
    lat_vals: list[float] = []
    lon_vals: list[float] = []
    for lat, lon in point_coords:
        try:
            latf = float(lat)
            lonf = _normalize_lon(float(lon))
        except Exception:
            continue
        if not (-90.0 <= latf <= 90.0 and -180.0 <= lonf <= 180.0):
            continue
        key = (round(latf, 5), round(lonf, 5))
        if key in seen:
            continue
        seen.add(key)
        lat_vals.append(key[0])
        lon_vals.append(key[1])

    if not lat_vals:
        raise ValueError("No valid coordinates available to build dynamic hazard centroids")

    if len(seen) <= DEFAULT_SMALL_SAMPLE_GRID_THRESHOLD:
        augmented = set(seen)
        step = float(DEFAULT_SMALL_SAMPLE_GRID_STEP_DEG)
        for latf, lonf in list(seen):
            for dlat in (-step, 0.0, step):
                for dlon in (-step, 0.0, step):
                    new_lat = max(-90.0, min(90.0, latf + dlat))
                    new_lon = _normalize_lon(lonf + dlon)
                    augmented.add((round(new_lat, 5), round(new_lon, 5)))
        seen = augmented
        lat_vals = [item[0] for item in sorted(seen)]
        lon_vals = [item[1] for item in sorted(seen)]
    return Centroids.from_lat_lon(lat=lat_vals, lon=lon_vals, crs="EPSG:4326")


def _build_hazard_from_tracks(tracks: Any, centroids: Any) -> Any:
    try:
        from climada.hazard import TropCyclone  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("CLIMADA is required to build dynamic tropical cyclone hazards") from exc
    return TropCyclone.from_tracks(
        tracks,
        centroids=centroids,
        ignore_distance_to_coast=True,
    )


def load_storm_hazards_from_parquet_for_points(
    *,
    storm_parquet_path: Path,
    cmcc_parquet_path: Path,
    point_coords: Iterable[tuple[float, float]],
    storm_years: int,
    basin_coverages: tuple[BasinCoverage, ...] = DEFAULT_BASIN_COVERAGES,
    spatial_padding_deg: float = DEFAULT_SPATIAL_PADDING_DEG,
    max_tracks: int = DEFAULT_MAX_TRACKS,
    track_cache_max_entries: int | None = None,
    wind_unit_in: str = "m/s",
    radius_unit_in: str = "km",
    env_pressure_hpa: float = 1010.0,
) -> HazardBundle:
    coords = list(point_coords)
    if not coords:
        raise ValueError("Dynamic hazard build requires at least one exposure coordinate")

    basin_ids = _basin_ids_for_points(coords, basin_coverages)
    spatial_window = _build_spatial_window(coords, padding_deg=spatial_padding_deg)
    centroids = _build_centroids_from_points(coords)
    tracks_storm = _get_or_build_tracks(
        storm_parquet_path,
        provider_name="STORM",
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        max_tracks=max_tracks,
        track_cache_max_entries=track_cache_max_entries,
        wind_unit_in=wind_unit_in,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
    )
    tracks_cmcc = _get_or_build_tracks(
        cmcc_parquet_path,
        provider_name="STORM_CMCC",
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        max_tracks=max_tracks,
        track_cache_max_entries=track_cache_max_entries,
        wind_unit_in=wind_unit_in,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
    )

    storm = _build_hazard_from_tracks(tracks_storm, centroids)
    storm_cmcc = _build_hazard_from_tracks(tracks_cmcc, centroids)
    return HazardBundle(
        storm=_normalize_frequency_safe(storm, storm_years),
        storm_cmcc=_normalize_frequency_safe(storm_cmcc, storm_years),
        storm_years=storm_years,
        normalized_on_copy=True,
        source="dynamic_parquet",
        basin_ids=tuple(sorted(int(v) for v in basin_ids)),
        point_count=int(len(coords)),
        tracks_storm=tracks_storm,
        tracks_storm_cmcc=tracks_cmcc,
        centroids=centroids,
    )


def load_storm_hazards(storm_path: Path, cmcc_path: Path, storm_years: int) -> HazardBundle:
    try:
        from climada.hazard import Hazard  # type: ignore
    except Exception as exc:  # pragma: no cover - optional at scaffold stage
        raise DependencyMissingError("CLIMADA is required to load STORM hazards") from exc

    storm = Hazard.from_hdf5(str(storm_path))
    storm_cmcc = Hazard.from_hdf5(str(cmcc_path))

    return HazardBundle(
        storm=_normalize_frequency_safe(storm, storm_years),
        storm_cmcc=_normalize_frequency_safe(storm_cmcc, storm_years),
        storm_years=storm_years,
        normalized_on_copy=True,
        source="precomputed_hdf5",
    )
