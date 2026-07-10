from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Iterable
import copy
import socket
from contextlib import contextmanager
import json
import subprocess
import sys

from .errors import DependencyMissingError
from .hazard_loader import (
    HazardBundle,
    _build_centroids_from_points,
    _build_hazard_from_tracks,
    _normalize_frequency_safe,
)

LOGGER = logging.getLogger(__name__)
IBTRACS_URL = (
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/netcdf/IBTrACS.ALL.v04r01.nc"
)
IBTRACS_FILE_NAME = "IBTrACS.ALL.v04r01.nc"
REPO_ROOT = Path(__file__).resolve().parents[3]
IBTRACS_EXTRACTOR_SCRIPT = REPO_ROOT / "scripts" / "extract_targeted_ibtracs_track.py"


def _normalize_lon(lon: float) -> float:
    out = float(lon)
    while out > 180.0:
        out -= 360.0
    while out < -180.0:
        out += 360.0
    return out


def _as_text(raw_value: Any) -> str:
    if isinstance(raw_value, bytes):
        return raw_value.decode("utf-8", errors="ignore")
    return str(raw_value or "")


@contextmanager
def _prefer_ipv4_dns() -> Iterable[None]:
    original_getaddrinfo = socket.getaddrinfo

    def _ipv4_first(
        host: Any,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        results = original_getaddrinfo(host, port, family, type, proto, flags)
        ipv4_results = [item for item in results if item[0] == socket.AF_INET]
        return ipv4_results or results

    socket.getaddrinfo = _ipv4_first
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _ibtracs_local_dir() -> Path:
    try:
        from climada.util.config import CONFIG  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA config is required to resolve the IBTrACS cache directory") from exc
    raw_dir = Path(CONFIG.local_data.save_dir.dir()).expanduser()
    home_results_dir = Path.home() / "results"
    cwd_results_dir = Path.cwd() / "results"
    if raw_dir == cwd_results_dir and raw_dir != home_results_dir:
        return home_results_dir
    if raw_dir.is_absolute():
        return raw_dir
    return Path.home() / raw_dir


def _download_ibtracs_file(target_path: Path) -> None:
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("requests is required to download IBTrACS cyclone tracks") from exc

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(target_path.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()

    LOGGER.info("Downloading IBTrACS archive to %s", target_path)
    bytes_written = 0
    next_log_threshold = 10 * 1024 * 1024

    try:
        with _prefer_ipv4_dns():
            with requests.get(IBTRACS_URL, stream=True, timeout=(10, 120)) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length") or 0)
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        bytes_written += len(chunk)
                        if total_size > 0 and bytes_written >= next_log_threshold:
                            LOGGER.info(
                                "IBTrACS download progress: %.1f%% (%s / %s MB)",
                                (bytes_written / total_size) * 100.0,
                                round(bytes_written / (1024 * 1024), 1),
                                round(total_size / (1024 * 1024), 1),
                            )
                            next_log_threshold += 10 * 1024 * 1024
                        elif total_size <= 0 and bytes_written >= next_log_threshold:
                            LOGGER.info(
                                "IBTrACS download progress: %s MB received",
                                round(bytes_written / (1024 * 1024), 1),
                            )
                            next_log_threshold += 10 * 1024 * 1024
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def ensure_ibtracs_file() -> Path:
    target_path = _ibtracs_local_dir() / IBTRACS_FILE_NAME
    if target_path.exists() and target_path.stat().st_size > 0:
        return target_path
    _download_ibtracs_file(target_path)
    return target_path


def _resolve_ibtracs_track_manually(request: TargetedCycloneRequest, ibtracs_file: Path) -> Any:
    try:
        import numpy as np  # type: ignore
        import xarray as xr  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("NumPy and xarray are required to load targeted IBTrACS cyclone tracks") from exc

    cmd = [
        sys.executable,
        str(IBTRACS_EXTRACTOR_SCRIPT),
        "--ibtracs-file",
        str(ibtracs_file),
        "--preset-id",
        str(request.preset_id),
        "--name",
        str(request.name),
        "--season",
        str(int(request.season)),
        "--basin",
        str(request.basin),
    ]
    if request.storm_id:
        cmd.extend(["--storm-id", str(request.storm_id)])

    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    return xr.Dataset(
        data_vars={
            "radius_max_wind": ("time", payload["data_vars"]["radius_max_wind"]),
            "radius_oci": ("time", payload["data_vars"]["radius_oci"]),
            "max_sustained_wind": ("time", payload["data_vars"]["max_sustained_wind"]),
            "central_pressure": ("time", payload["data_vars"]["central_pressure"]),
            "environmental_pressure": ("time", payload["data_vars"]["environmental_pressure"]),
            "time_step": ("time", payload["data_vars"]["time_step"]),
            "basin": ("time", payload["data_vars"]["basin"]),
        },
        coords={
            "time": ("time", np.asarray(payload["coords"]["time"], dtype="datetime64[ns]")),
            "lat": ("time", payload["coords"]["lat"]),
            "lon": ("time", payload["coords"]["lon"]),
        },
        attrs=dict(payload["attrs"]),
    )


@dataclass(frozen=True)
class TargetedCycloneRequest:
    preset_id: str
    source: str
    name: str
    season: int
    basin: str
    storm_id: str | None = None


@dataclass(frozen=True)
class ResolvedTargetedCyclone:
    preset_id: str
    source: str
    name: str
    season: int
    basin: str
    storm_id: str
    original_name: str
    original_track: Any


@dataclass(frozen=True)
class TransposedTargetedCyclone:
    resolved: ResolvedTargetedCyclone
    translated_track: Any
    anchor_index: int
    anchor_lat: float
    anchor_lon: float
    target_lat: float
    target_lon: float
    lat_shift: float
    lon_shift: float

    def to_metadata(self) -> dict[str, Any]:
        return {
            "preset_id": self.resolved.preset_id,
            "source": self.resolved.source,
            "name": self.resolved.name,
            "season": int(self.resolved.season),
            "basin": self.resolved.basin,
            "storm_id": self.resolved.storm_id,
            "original_name": self.resolved.original_name,
            "transposition": {
                "mode": "max_wind_anchor_translation",
                "anchor_index": int(self.anchor_index),
                "anchor_lat": float(self.anchor_lat),
                "anchor_lon": float(self.anchor_lon),
                "target_lat": float(self.target_lat),
                "target_lon": float(self.target_lon),
                "lat_shift": float(self.lat_shift),
                "lon_shift": float(self.lon_shift),
            },
        }


def resolve_ibtracs_cyclone(request: TargetedCycloneRequest) -> ResolvedTargetedCyclone:
    wanted_storm_id = str(request.storm_id or "").strip()
    ibtracs_file = ensure_ibtracs_file()
    LOGGER.info(
        "Resolving targeted cyclone preset=%s storm_id=%s season=%s basin=%s from %s",
        request.preset_id,
        wanted_storm_id or "n/a",
        int(request.season),
        request.basin,
        ibtracs_file,
    )
    track = _resolve_ibtracs_track_manually(request, ibtracs_file)
    storm_id = _as_text(getattr(track, "attrs", {}).get("sid")).strip()
    original_name = _as_text(getattr(track, "attrs", {}).get("name")).strip() or str(request.name)
    return ResolvedTargetedCyclone(
        preset_id=str(request.preset_id),
        source=str(request.source),
        name=str(request.name),
        season=int(request.season),
        basin=str(request.basin),
        storm_id=storm_id,
        original_name=original_name,
        original_track=track,
    )


def transpose_track_to_territory_anchor(
    resolved: ResolvedTargetedCyclone,
    *,
    target_lat: float,
    target_lon: float,
    territory_key: str,
) -> TransposedTargetedCyclone:
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("NumPy is required to transpose IBTrACS cyclone tracks") from exc

    track = copy.deepcopy(resolved.original_track)
    winds = np.asarray(track["max_sustained_wind"].values, dtype=float).reshape(-1)
    if winds.size == 0:
        raise ValueError(f"Resolved cyclone {resolved.preset_id} does not expose any wind timestep")
    anchor_index = int(np.nanargmax(winds))
    lat_values = np.asarray(track["lat"].values, dtype=float).reshape(-1)
    lon_values = np.asarray(track["lon"].values, dtype=float).reshape(-1)
    anchor_lat = float(lat_values[anchor_index])
    anchor_lon = _normalize_lon(float(lon_values[anchor_index]))
    lat_shift = float(target_lat) - anchor_lat
    lon_shift = _normalize_lon(float(target_lon) - anchor_lon)

    shifted_lats = lat_values + float(lat_shift)
    shifted_lons = [_normalize_lon(float(value) + float(lon_shift)) for value in lon_values]
    track["lat"].values[:] = shifted_lats
    track["lon"].values[:] = shifted_lons
    track.attrs = dict(getattr(track, "attrs", {}) or {})
    track.attrs["name"] = f"{resolved.original_name} (transposed {territory_key})"
    track.attrs["sid"] = resolved.storm_id
    track.attrs["orig_event_flag"] = True
    track.attrs["data_provider"] = f"ibtracs_targeted_{territory_key}"

    return TransposedTargetedCyclone(
        resolved=resolved,
        translated_track=track,
        anchor_index=anchor_index,
        anchor_lat=anchor_lat,
        anchor_lon=anchor_lon,
        target_lat=float(target_lat),
        target_lon=float(target_lon),
        lat_shift=float(lat_shift),
        lon_shift=float(lon_shift),
    )


def build_targeted_cyclone_hazard_bundle(
    *,
    cyclones: list[TransposedTargetedCyclone],
    point_coords: Iterable[tuple[float, float]],
    source_label: str = "explicit_ibtracs_targeted",
    storm_years: int = 1,
) -> HazardBundle:
    try:
        from climada.hazard import TCTracks  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA is required to build targeted cyclone hazards") from exc

    translated_tracks = [item.translated_track for item in cyclones]
    if not translated_tracks:
        raise ValueError("At least one targeted cyclone must be provided")

    tracks = TCTracks()
    tracks.data = translated_tracks
    coords = [(float(lat), float(lon)) for lat, lon in point_coords]
    centroids = _build_centroids_from_points(coords)
    storm = _build_hazard_from_tracks(tracks, centroids)
    storm = _normalize_frequency_safe(storm, max(1, int(storm_years)))

    return HazardBundle(
        storm=storm,
        storm_cmcc=None,
        storm_years=max(1, int(storm_years)),
        normalized_on_copy=True,
        source=str(source_label),
        point_count=int(len(coords)),
        tracks_storm=tracks,
        tracks_storm_cmcc=None,
        track_count_storm=int(len(translated_tracks)),
        track_count_storm_cmcc=0,
        centroids=centroids,
        global_hazards_built=True,
    )


def build_transposed_targeted_cyclones(
    requests: list[TargetedCycloneRequest],
    *,
    target_lat: float,
    target_lon: float,
    territory_key: str,
) -> list[TransposedTargetedCyclone]:
    out: list[TransposedTargetedCyclone] = []
    for request in requests:
        resolved = resolve_ibtracs_cyclone(request)
        out.append(
            transpose_track_to_territory_anchor(
                resolved,
                target_lat=float(target_lat),
                target_lon=float(target_lon),
                territory_key=str(territory_key),
            )
        )
    return out
