from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
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
    track_count_storm: int = 0
    track_count_storm_cmcc: int = 0
    centroids: Any | None = None
    global_hazards_built: bool = True
    storm_track_load_spec: _DynamicTrackLoadSpec | None = None
    storm_cmcc_track_load_spec: _DynamicTrackLoadSpec | None = None
    track_sample_manifest_path: Path | None = None
    track_sample_id: str | None = None
    track_sample_size_by_provider: dict[str, int] | None = None


@dataclass(frozen=True)
class SpatialWindow:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    center_lat: float
    center_lon: float


@dataclass(frozen=True)
class _DynamicTrackLoadSpec:
    parquet_path: Path
    provider_name: str
    basin_ids: tuple[int, ...]
    spatial_window: SpatialWindow | None
    max_tracks: int
    wind_unit_in: str
    convert_10min_to_1min: bool
    radius_unit_in: str
    env_pressure_hpa: float
    track_cache_max_entries: int | None = None
    track_sample_provider: TrackSampleProvider | None = None


@dataclass(frozen=True)
class TrackSampleEntry:
    year: int
    track_id: str
    track_instance_id: str
    sample_weight: float
    frequency_annual: float | None = None
    stratum: str | None = None
    loss_eur: float | None = None
    rank: int | None = None


@dataclass(frozen=True)
class TrackSampleProvider:
    provider_key: str
    provider_name: str
    manifest_path: Path
    manifest_id: str
    source_hash: str
    sample_size: int
    population_track_count: int | None
    entries_by_instance_id: dict[str, TrackSampleEntry]

    @property
    def selected_instance_ids(self) -> set[str]:
        return set(self.entries_by_instance_id.keys())


_TRACK_CACHE_LOCK = threading.Lock()
_TRACK_CACHE: OrderedDict[
    tuple[str, str, tuple[int, ...], str, str, float, tuple[float, float, float, float] | None, int, str | None],
    Any,
] = OrderedDict()

logger = logging.getLogger(__name__)

DEFAULT_SPATIAL_PADDING_DEG = 4.0
DEFAULT_MAX_TRACKS = 4000
DEFAULT_TRACK_CACHE_MAX_ENTRIES = 8
DEFAULT_SMALL_SAMPLE_GRID_STEP_DEG = 0.01
DEFAULT_SMALL_SAMPLE_GRID_THRESHOLD = 50
STORM_10MIN_TO_1MIN_WIND_FACTOR = 1.0 / 0.88


def _provider_key_from_name(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower().replace("-", "_")
    if normalized in {"storm_cmcc", "cmcc", "stormcmcc"}:
        return "storm_cmcc"
    return "storm"


def _track_instance_id(year: Any, track_id: Any, provider_key: str | None = None) -> str:
    base_id = f"{int(year)}|{str(track_id)}"
    if provider_key:
        return f"{_provider_key_from_name(provider_key)}|{base_id}"
    return base_id


def _sample_cache_key(track_sample_provider: TrackSampleProvider | None) -> str | None:
    if track_sample_provider is None:
        return None
    return (
        f"{track_sample_provider.manifest_id}:"
        f"{track_sample_provider.provider_key}:"
        f"{track_sample_provider.source_hash}:"
        f"{track_sample_provider.sample_size}"
    )


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _load_track_sample_manifest(track_sample_manifest_path: Path | None) -> dict[str, TrackSampleProvider] | None:
    if track_sample_manifest_path is None:
        return None
    path = Path(track_sample_manifest_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Track sample manifest not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid track sample manifest payload at {path}")

    providers = payload.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError(f"Track sample manifest must contain a non-empty providers object: {path}")

    manifest_id = str(payload.get("sample_id") or payload.get("id") or path.stem).strip() or path.stem
    storm_years = int(payload.get("storm_years") or 0)
    out: dict[str, TrackSampleProvider] = {}

    for raw_key, raw_provider in providers.items():
        if not isinstance(raw_provider, dict):
            continue
        provider_name = str(raw_provider.get("provider_name") or raw_provider.get("provider") or raw_key).strip()
        provider_key = _provider_key_from_name(provider_name or str(raw_key))
        tracks = raw_provider.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            raise ValueError(f"Track sample provider '{raw_key}' has no tracks in {path}")

        entries: dict[str, TrackSampleEntry] = {}
        for index, raw_entry in enumerate(tracks):
            if not isinstance(raw_entry, dict):
                raise ValueError(f"Invalid track entry #{index} for provider '{raw_key}' in {path}")
            if raw_entry.get("year") is None or raw_entry.get("track_id") is None:
                raise ValueError(f"Track entry #{index} for provider '{raw_key}' must contain year and track_id")
            year = int(raw_entry.get("year"))
            track_id = str(raw_entry.get("track_id"))
            base_track_instance_id = _track_instance_id(year, track_id)
            canonical_track_instance_id = _track_instance_id(year, track_id, provider_key=provider_key)
            raw_track_instance_id = str(raw_entry.get("track_instance_id") or canonical_track_instance_id)
            track_instance_id = (
                canonical_track_instance_id
                if raw_track_instance_id in {base_track_instance_id, canonical_track_instance_id}
                else raw_track_instance_id
            )
            sample_weight = _coerce_optional_float(
                raw_entry.get("sample_weight", raw_entry.get("weight"))
            )
            frequency_annual = _coerce_optional_float(raw_entry.get("frequency_annual"))
            if sample_weight is None:
                if frequency_annual is None or storm_years <= 0:
                    raise ValueError(
                        f"Track entry {track_instance_id!r} for provider '{raw_key}' must contain sample_weight "
                        "or frequency_annual plus manifest storm_years"
                    )
                sample_weight = float(frequency_annual) * float(storm_years)
            if sample_weight <= 0.0:
                raise ValueError(f"Track entry {track_instance_id!r} has non-positive sample_weight={sample_weight}")
            if frequency_annual is not None and frequency_annual <= 0.0:
                raise ValueError(f"Track entry {track_instance_id!r} has non-positive frequency_annual={frequency_annual}")
            if track_instance_id in entries:
                raise ValueError(f"Duplicate sampled track {track_instance_id!r} for provider '{raw_key}' in {path}")
            entries[track_instance_id] = TrackSampleEntry(
                year=year,
                track_id=track_id,
                track_instance_id=track_instance_id,
                sample_weight=float(sample_weight),
                frequency_annual=frequency_annual,
                stratum=(str(raw_entry.get("stratum")) if raw_entry.get("stratum") is not None else None),
                loss_eur=_coerce_optional_float(raw_entry.get("loss_eur")),
                rank=(int(raw_entry.get("rank")) if raw_entry.get("rank") is not None else None),
            )

        out[provider_key] = TrackSampleProvider(
            provider_key=provider_key,
            provider_name=provider_name or ("STORM_CMCC" if provider_key == "storm_cmcc" else "STORM"),
            manifest_path=path,
            manifest_id=manifest_id,
            source_hash=source_hash,
            sample_size=int(raw_provider.get("sample_size") or len(entries)),
            population_track_count=(
                int(raw_provider.get("population_track_count"))
                if raw_provider.get("population_track_count") is not None
                else None
            ),
            entries_by_instance_id=entries,
        )

    return out


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


def _resolve_max_tracks(max_tracks: int) -> int:
    try:
        return int(max_tracks)
    except Exception as exc:
        logger.warning(
            "Invalid max_tracks=%r (%s: %s); using default=%d",
            max_tracks,
            type(exc).__name__,
            exc,
            DEFAULT_MAX_TRACKS,
        )
        return DEFAULT_MAX_TRACKS


def _normalize_frequency_safe(hazard_obj: Any, storm_years: int) -> Any:
    # Keep large hazard matrices shared and only replace the frequency vector.
    hazard_copy = copy.copy(hazard_obj)
    freq = getattr(hazard_copy, "frequency", None)
    if freq is None:
        return hazard_copy

    # Idempotent normalization marker to avoid double-dividing in reused objects.
    if getattr(hazard_copy, "_sib_frequency_normalized", False):
        return hazard_copy

    try:
        import numpy as np  # type: ignore

        annual_years = float(max(1, int(storm_years)))
        try:
            hazard_copy.frequency = freq / annual_years
        except Exception:
            hazard_copy.frequency = np.asarray(freq, dtype=float) / annual_years
        setattr(hazard_copy, "_sib_frequency_normalized", True)
    except Exception as exc:
        logger.warning(
            "Failed to normalize hazard frequency on copy (%s): %s",
            type(exc).__name__,
            exc,
        )
    return hazard_copy


def _track_frequency_annual_from_tracks(tracks: Any, storm_years: int) -> Any | None:
    data = list(getattr(tracks, "data", []) or [])
    if not data:
        return None
    try:
        import numpy as np  # type: ignore
    except Exception:
        return None

    annual_values: list[float] = []
    weights: list[float] = []
    has_any_sample_attr = False
    all_annual = True
    all_weights = True
    for ds in data:
        attrs = getattr(ds, "attrs", {}) or {}
        annual_raw = attrs.get("sib_frequency_annual")
        weight_raw = attrs.get("sib_sample_weight")
        if annual_raw is not None or weight_raw is not None:
            has_any_sample_attr = True
        try:
            annual_values.append(float(annual_raw))
        except Exception:
            all_annual = False
            annual_values.append(float("nan"))
        try:
            weights.append(float(weight_raw))
        except Exception:
            all_weights = False
            weights.append(float("nan"))

    if not has_any_sample_attr:
        return None
    if all_annual and all(value > 0.0 and np.isfinite(value) for value in annual_values):
        return np.asarray(annual_values, dtype=float)
    if all_weights and all(value > 0.0 and np.isfinite(value) for value in weights):
        return np.asarray(weights, dtype=float) / float(max(1, int(storm_years)))
    return None


def normalize_hazard_frequency_from_tracks(hazard_obj: Any, tracks: Any, storm_years: int) -> Any:
    annual_frequency = _track_frequency_annual_from_tracks(tracks, storm_years)
    if annual_frequency is None:
        return _normalize_frequency_safe(hazard_obj, storm_years)

    hazard_copy = copy.copy(hazard_obj)
    existing = getattr(hazard_copy, "frequency", None)
    try:
        existing_len = len(existing) if existing is not None else int(annual_frequency.size)
    except Exception:
        existing_len = int(annual_frequency.size)
    if int(existing_len) != int(annual_frequency.size):
        logger.warning(
            "Sample-weighted hazard frequency length mismatch: hazard=%s sample=%s; falling back to uniform normalization.",
            int(existing_len),
            int(annual_frequency.size),
        )
        return _normalize_frequency_safe(hazard_obj, storm_years)

    hazard_copy.frequency = annual_frequency
    setattr(hazard_copy, "_sib_frequency_normalized", True)
    setattr(hazard_copy, "_sib_sample_weighted_frequency", True)
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


def _convert_storm_wind_to_climada_mps(
    values: Any,
    unit_in: str,
    *,
    convert_10min_to_1min: bool,
) -> Any:
    wind = _convert_wind_to_mps(values, unit_in)
    if not convert_10min_to_1min:
        return wind
    return wind * STORM_10MIN_TO_1MIN_WIND_FACTOR


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


def _resolve_requested_parquet_columns(parquet_path: Path, columns: list[str] | None) -> list[str] | None:
    if not columns:
        return None

    requested = list(dict.fromkeys(str(value) for value in columns))
    try:
        import pyarrow.parquet as pq  # type: ignore

        available = {str(name) for name in pq.read_schema(parquet_path).names}
    except Exception:
        return requested

    resolved = [name for name in requested if name in available]
    return resolved or None


def _read_filtered_track_dataframe(
    parquet_path: Path,
    *,
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None = None,
    columns: list[str] | None = None,
) -> Any:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("Pandas is required to read STORM parquet catalogs") from exc

    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing parquet dataset: {parquet_path}")

    read_kwargs: dict[str, Any] = {}
    resolved_columns = _resolve_requested_parquet_columns(parquet_path, columns)
    if resolved_columns:
        read_kwargs["columns"] = resolved_columns
    if basin_ids:
        read_kwargs["filters"] = [("Basin ID", "in", [int(b) for b in basin_ids])]
    try:
        df = pd.read_parquet(parquet_path, **read_kwargs)
    except Exception as exc:
        logger.warning(
            "Parquet predicate read failed for %s (filters=%s, columns=%s, %s: %s); retrying full read",
            parquet_path,
            read_kwargs.get("filters"),
            read_kwargs.get("columns"),
            type(exc).__name__,
            exc,
        )
        df = pd.read_parquet(parquet_path)

    df = _normalize_columns(df)
    if "Basin ID" in df.columns and basin_ids:
        df = df[df["Basin ID"].astype(int).isin([int(b) for b in basin_ids])].copy()
    if df.empty:
        raise ValueError(f"No rows remain after basin filter {list(basin_ids)} on {parquet_path}")

    if "lon" in df.columns:
        df["lon"] = df["lon"].astype(float)
        df.loc[df["lon"] > 180.0, "lon"] = df.loc[df["lon"] > 180.0, "lon"] - 360.0

    if spatial_window is not None:
        if "lat" not in df.columns or "lon" not in df.columns:
            raise ValueError(
                f"Missing spatial filter columns in {parquet_path}: {sorted({'lat', 'lon'} - set(df.columns))}"
            )
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
    return df


def _with_track_instance_id(df: Any, provider_key: str | None = None) -> Any:
    missing = sorted({"Year", "track_id"} - set(df.columns))
    if missing:
        raise ValueError(f"Missing required track identity columns: {missing}")
    if provider_key is not None or "_track_instance_id" not in df.columns:
        df = df.copy()
        base_id = (
            df["Year"].astype(int).astype(str)
            + "|"
            + df["track_id"].astype(str)
        )
        if provider_key is not None:
            df["_track_instance_id"] = _provider_key_from_name(provider_key) + "|" + base_id
        else:
            df["_track_instance_id"] = base_id
    return df


def _apply_track_sample_filter(
    df: Any,
    *,
    track_sample_provider: TrackSampleProvider | None,
    parquet_path: Path,
) -> Any:
    if track_sample_provider is None:
        return df
    df = _with_track_instance_id(df, provider_key=track_sample_provider.provider_key)
    selected_ids = track_sample_provider.selected_instance_ids
    present_ids = set(str(value) for value in df["_track_instance_id"].dropna().unique().tolist())
    missing_ids = sorted(selected_ids - present_ids)
    if missing_ids:
        preview = ", ".join(missing_ids[:10])
        suffix = "..." if len(missing_ids) > 10 else ""
        raise ValueError(
            "Track sample manifest references tracks that are absent after basin/spatial filtering "
            f"for {track_sample_provider.provider_name} in {parquet_path}: {preview}{suffix}"
        )
    return df[df["_track_instance_id"].isin(selected_ids)].copy()


def _count_tracks_from_parquet(
    parquet_path: Path,
    *,
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None = None,
    max_tracks: int = DEFAULT_MAX_TRACKS,
    track_sample_provider: TrackSampleProvider | None = None,
) -> int:
    df = _read_filtered_track_dataframe(
        parquet_path,
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        columns=["Basin ID", "Year", "track_id", "lat", "Latitude", "lon", "Longitude"],
    )
    missing = sorted({"Year", "track_id"} - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns in {parquet_path}: {missing}")

    df = _apply_track_sample_filter(
        df,
        track_sample_provider=track_sample_provider,
        parquet_path=parquet_path,
    )
    track_count = int(df[["Year", "track_id"]].drop_duplicates().shape[0])
    if track_sample_provider is not None:
        return track_count
    max_tracks_int = _resolve_max_tracks(max_tracks)
    if max_tracks_int > 0:
        return min(track_count, max_tracks_int)
    return track_count


def _build_tracks_from_parquet(
    parquet_path: Path,
    *,
    provider_name: str,
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None = None,
    max_tracks: int = DEFAULT_MAX_TRACKS,
    timestep_hours: int = 3,
    wind_unit_in: str = "m/s",
    convert_10min_to_1min: bool = True,
    radius_unit_in: str = "km",
    env_pressure_hpa: float = 1010.0,
    track_sample_provider: TrackSampleProvider | None = None,
) -> Any:
    try:
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
        import xarray as xr  # type: ignore
        from climada.hazard import TCTracks  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("CLIMADA runtime dependencies are required to build hazards from parquet") from exc

    df = _read_filtered_track_dataframe(
        parquet_path,
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        columns=[
            "Basin ID",
            "Category",
            "Year",
            "track_id",
            "time_step",
            "Time step",
            "lat",
            "Latitude",
            "lon",
            "Longitude",
            "p_c",
            "Minimum pressure",
            "wind_max",
            "Maximum wind speed",
            "rmax",
            "Radius to maximum winds",
        ],
    )

    required = {"Year", "track_id", "time_step", "lat", "lon", "p_c", "wind_max", "rmax"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns in {parquet_path}: {missing}")

    df = _with_track_instance_id(
        df,
        provider_key=(track_sample_provider.provider_key if track_sample_provider is not None else None),
    )
    df = _apply_track_sample_filter(
        df,
        track_sample_provider=track_sample_provider,
        parquet_path=parquet_path,
    )

    max_tracks_int = _resolve_max_tracks(max_tracks)
    if track_sample_provider is not None:
        logger.info(
            "Using prefabricated track sample %s/%s for %s: selected_tracks=%d",
            track_sample_provider.manifest_id,
            track_sample_provider.provider_key,
            provider_name,
            int(df["_track_instance_id"].nunique(dropna=True)),
        )
    elif max_tracks_int > 0:
        track_count = int(df["_track_instance_id"].nunique(dropna=True))
        if track_count > max_tracks_int:
            lat_center = float(spatial_window.center_lat if spatial_window is not None else df["lat"].astype(float).mean())
            lon_center = float(spatial_window.center_lon if spatial_window is not None else df["lon"].astype(float).mean())
            dlat = df["lat"].astype(float) - lat_center
            dlon = (df["lon"].astype(float) - lon_center).abs()
            dlon = dlon.where(dlon <= 180.0, 360.0 - dlon)
            dist2 = (dlat * dlat) + (dlon * dlon)
            ranked_tracks = (
                df.assign(_dist2=dist2)
                .groupby("_track_instance_id", sort=False)["_dist2"]
                .min()
                .nsmallest(max_tracks_int)
            )
            keep_track_ids = set(ranked_tracks.index.tolist())
            df = df[df["_track_instance_id"].isin(keep_track_ids)].copy()

    df["wind_max"] = _convert_storm_wind_to_climada_mps(
        df["wind_max"],
        wind_unit_in,
        convert_10min_to_1min=convert_10min_to_1min,
    )
    df["rmax"] = _convert_radius_to_nm(df["rmax"], radius_unit_in)

    df = df.sort_values(["_track_instance_id", "time_step"]).reset_index(drop=True)
    groups = df.groupby("_track_instance_id", sort=False)

    track_list: list[Any] = []
    for idx, (track_instance_id, grp) in enumerate(groups, start=1):
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
        track_id = str(grp["track_id"].iloc[0])
        sample_entry = (
            track_sample_provider.entries_by_instance_id.get(str(track_instance_id))
            if track_sample_provider is not None
            else None
        )
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
                "max_sustained_wind_averaging_period_minutes": 1 if convert_10min_to_1min else 10,
                "radius_max_wind_unit": "nm",
                "central_pressure_unit": "hPa",
                "sid": f"{provider_name}_{track_instance_id}",
                "name": f"synthetic_{provider_name}_{track_instance_id}",
                "orig_event_flag": False,
                "data_provider": provider_name,
                "id_no": int(idx),
                "category": category,
                "sib_track_instance_id": str(track_instance_id),
                "sib_year": int(year),
                "sib_track_id": str(track_id),
            },
        )
        if sample_entry is not None:
            ds.attrs["sib_sample_manifest_id"] = track_sample_provider.manifest_id
            ds.attrs["sib_sample_weight"] = float(sample_entry.sample_weight)
            if sample_entry.frequency_annual is not None:
                ds.attrs["sib_frequency_annual"] = float(sample_entry.frequency_annual)
            if sample_entry.stratum is not None:
                ds.attrs["sib_sample_stratum"] = sample_entry.stratum
            if sample_entry.loss_eur is not None:
                ds.attrs["sib_sample_loss_eur"] = float(sample_entry.loss_eur)
            if sample_entry.rank is not None:
                ds.attrs["sib_sample_rank"] = int(sample_entry.rank)
        track_list.append(ds)

    tracks = TCTracks()
    tracks.data = track_list
    try:
        setattr(tracks, "sib_track_instance_ids", tuple(str(ds.attrs.get("sib_track_instance_id") or "") for ds in track_list))
        if track_sample_provider is not None:
            setattr(tracks, "sib_sample_manifest_id", track_sample_provider.manifest_id)
            setattr(tracks, "sib_sample_provider_key", track_sample_provider.provider_key)
            setattr(tracks, "sib_sample_size", int(track_sample_provider.sample_size))
            setattr(
                tracks,
                "sib_sample_weights",
                tuple(float(ds.attrs.get("sib_sample_weight", 1.0)) for ds in track_list),
            )
            annual = []
            for ds in track_list:
                value = ds.attrs.get("sib_frequency_annual")
                annual.append(float(value) if value is not None else float("nan"))
            setattr(tracks, "sib_frequency_annual", tuple(annual))
    except Exception:
        pass
    return tracks


def _get_or_build_tracks(
    parquet_path: Path,
    *,
    provider_name: str,
    basin_ids: tuple[int, ...],
    spatial_window: SpatialWindow | None,
    max_tracks: int,
    wind_unit_in: str,
    convert_10min_to_1min: bool,
    radius_unit_in: str,
    env_pressure_hpa: float,
    track_cache_max_entries: int | None = None,
    track_sample_provider: TrackSampleProvider | None = None,
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
        bool(convert_10min_to_1min),
        str(radius_unit_in),
        float(env_pressure_hpa),
        window_key,
        int(max_tracks),
        _sample_cache_key(track_sample_provider),
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
        convert_10min_to_1min=convert_10min_to_1min,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
        track_sample_provider=track_sample_provider,
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
    convert_10min_to_1min: bool = True,
    radius_unit_in: str = "km",
    env_pressure_hpa: float = 1010.0,
    build_hazards: bool = True,
    track_sample_manifest_path: Path | None = None,
) -> HazardBundle:
    coords = list(point_coords)
    if not coords:
        raise ValueError("Dynamic hazard build requires at least one exposure coordinate")

    basin_ids = _basin_ids_for_points(coords, basin_coverages)
    spatial_window = _build_spatial_window(coords, padding_deg=spatial_padding_deg)
    track_sample_providers = _load_track_sample_manifest(track_sample_manifest_path)
    storm_sample_provider = (track_sample_providers or {}).get("storm")
    cmcc_sample_provider = (track_sample_providers or {}).get("storm_cmcc")
    if not build_hazards:
        track_count_storm = _count_tracks_from_parquet(
            storm_parquet_path,
            basin_ids=basin_ids,
            spatial_window=spatial_window,
            max_tracks=max_tracks,
            track_sample_provider=storm_sample_provider,
        )
        track_count_cmcc = _count_tracks_from_parquet(
            cmcc_parquet_path,
            basin_ids=basin_ids,
            spatial_window=spatial_window,
            max_tracks=max_tracks,
            track_sample_provider=cmcc_sample_provider,
        )
        return HazardBundle(
            storm=None,
            storm_cmcc=None,
            storm_years=storm_years,
            normalized_on_copy=True,
            source="dynamic_parquet",
            basin_ids=tuple(sorted(int(v) for v in basin_ids)),
            point_count=int(len(coords)),
            track_count_storm=track_count_storm,
            track_count_storm_cmcc=track_count_cmcc,
            global_hazards_built=False,
            track_sample_manifest_path=Path(track_sample_manifest_path) if track_sample_manifest_path is not None else None,
            track_sample_id=(
                str(next(iter(track_sample_providers.values())).manifest_id)
                if track_sample_providers
                else None
            ),
            track_sample_size_by_provider={
                key: int(provider.sample_size)
                for key, provider in (track_sample_providers or {}).items()
            },
            storm_track_load_spec=_DynamicTrackLoadSpec(
                parquet_path=storm_parquet_path,
                provider_name="STORM",
                basin_ids=tuple(sorted(int(v) for v in basin_ids)),
                spatial_window=spatial_window,
                max_tracks=int(max_tracks),
                wind_unit_in=wind_unit_in,
                convert_10min_to_1min=convert_10min_to_1min,
                radius_unit_in=radius_unit_in,
                env_pressure_hpa=float(env_pressure_hpa),
                track_cache_max_entries=0,
                track_sample_provider=storm_sample_provider,
            ),
            storm_cmcc_track_load_spec=_DynamicTrackLoadSpec(
                parquet_path=cmcc_parquet_path,
                provider_name="STORM_CMCC",
                basin_ids=tuple(sorted(int(v) for v in basin_ids)),
                spatial_window=spatial_window,
                max_tracks=int(max_tracks),
                wind_unit_in=wind_unit_in,
                convert_10min_to_1min=convert_10min_to_1min,
                radius_unit_in=radius_unit_in,
                env_pressure_hpa=float(env_pressure_hpa),
                track_cache_max_entries=0,
                track_sample_provider=cmcc_sample_provider,
            ),
        )

    tracks_storm = _get_or_build_tracks(
        storm_parquet_path,
        provider_name="STORM",
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        max_tracks=max_tracks,
        track_cache_max_entries=track_cache_max_entries,
        wind_unit_in=wind_unit_in,
        convert_10min_to_1min=convert_10min_to_1min,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
        track_sample_provider=storm_sample_provider,
    )
    tracks_cmcc = _get_or_build_tracks(
        cmcc_parquet_path,
        provider_name="STORM_CMCC",
        basin_ids=basin_ids,
        spatial_window=spatial_window,
        max_tracks=max_tracks,
        track_cache_max_entries=track_cache_max_entries,
        wind_unit_in=wind_unit_in,
        convert_10min_to_1min=convert_10min_to_1min,
        radius_unit_in=radius_unit_in,
        env_pressure_hpa=env_pressure_hpa,
        track_sample_provider=cmcc_sample_provider,
    )
    track_count_storm = int(len(getattr(tracks_storm, "data", [])))
    track_count_cmcc = int(len(getattr(tracks_cmcc, "data", [])))

    centroids = _build_centroids_from_points(coords) if build_hazards else None
    storm = _build_hazard_from_tracks(tracks_storm, centroids) if centroids is not None else None
    storm_cmcc = _build_hazard_from_tracks(tracks_cmcc, centroids) if centroids is not None else None
    return HazardBundle(
        storm=normalize_hazard_frequency_from_tracks(storm, tracks_storm, storm_years) if storm is not None else None,
        storm_cmcc=normalize_hazard_frequency_from_tracks(storm_cmcc, tracks_cmcc, storm_years) if storm_cmcc is not None else None,
        storm_years=storm_years,
        normalized_on_copy=True,
        source="dynamic_parquet",
        basin_ids=tuple(sorted(int(v) for v in basin_ids)),
        point_count=int(len(coords)),
        tracks_storm=tracks_storm,
        tracks_storm_cmcc=tracks_cmcc,
        track_count_storm=track_count_storm,
        track_count_storm_cmcc=track_count_cmcc,
        centroids=centroids,
        global_hazards_built=bool(centroids is not None),
        track_sample_manifest_path=Path(track_sample_manifest_path) if track_sample_manifest_path is not None else None,
        track_sample_id=(
            str(next(iter(track_sample_providers.values())).manifest_id)
            if track_sample_providers
            else None
        ),
        track_sample_size_by_provider={
            key: int(provider.sample_size)
            for key, provider in (track_sample_providers or {}).items()
        },
    )


def _bundle_track_attrs(hazard_key: str) -> tuple[str, str]:
    if hazard_key == "storm":
        return "tracks_storm", "storm_track_load_spec"
    if hazard_key == "storm_cmcc":
        return "tracks_storm_cmcc", "storm_cmcc_track_load_spec"
    raise ValueError(f"Unsupported hazard key for dynamic tracks: {hazard_key}")


def resolve_hazard_bundle_tracks(bundle: Any, hazard_key: str) -> Any | None:
    tracks_attr, spec_attr = _bundle_track_attrs(hazard_key)
    tracks = getattr(bundle, tracks_attr, None)
    if tracks is not None:
        return tracks

    spec = getattr(bundle, spec_attr, None)
    if spec is None:
        return None

    tracks = _get_or_build_tracks(
        Path(spec.parquet_path),
        provider_name=str(spec.provider_name),
        basin_ids=tuple(int(value) for value in spec.basin_ids),
        spatial_window=spec.spatial_window,
        max_tracks=int(spec.max_tracks),
        wind_unit_in=str(spec.wind_unit_in),
        convert_10min_to_1min=bool(spec.convert_10min_to_1min),
        radius_unit_in=str(spec.radius_unit_in),
        env_pressure_hpa=float(spec.env_pressure_hpa),
        track_cache_max_entries=spec.track_cache_max_entries,
        track_sample_provider=getattr(spec, "track_sample_provider", None),
    )
    setattr(bundle, tracks_attr, tracks)
    return tracks


def release_hazard_bundle_tracks(bundle: Any, hazard_key: str) -> None:
    tracks_attr, _ = _bundle_track_attrs(hazard_key)
    if getattr(bundle, tracks_attr, None) is not None:
        setattr(bundle, tracks_attr, None)


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
        track_count_storm=int(len(getattr(storm, "event_id", []))),
        track_count_storm_cmcc=int(len(getattr(storm_cmcc, "event_id", []))),
    )


def load_storm_hazard(hazard_path: Path, storm_years: int) -> Any:
    try:
        from climada.hazard import Hazard  # type: ignore
    except Exception as exc:  # pragma: no cover - optional at scaffold stage
        raise DependencyMissingError("CLIMADA is required to load STORM hazards") from exc

    hazard = Hazard.from_hdf5(str(hazard_path))
    return _normalize_frequency_safe(hazard, storm_years)
