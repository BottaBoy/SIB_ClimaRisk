from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.risk_engine.hazard_loader import (
    HazardBundle,
    STORM_10MIN_TO_1MIN_WIND_FACTOR,
    _convert_storm_wind_to_climada_mps,
    load_storm_hazards_from_parquet_for_points,
    release_hazard_bundle_tracks,
    resolve_hazard_bundle_tracks,
)


def test_convert_storm_wind_to_climada_mps_applies_10min_to_1min_once():
    converted = _convert_storm_wind_to_climada_mps(
        [50.0],
        "m/s",
        convert_10min_to_1min=True,
    )

    assert float(converted[0]) == pytest.approx(50.0 * STORM_10MIN_TO_1MIN_WIND_FACTOR, abs=1e-9)


def test_convert_storm_wind_to_climada_mps_can_preserve_input_convention():
    converted = _convert_storm_wind_to_climada_mps(
        [50.0],
        "m/s",
        convert_10min_to_1min=False,
    )

    assert float(converted[0]) == pytest.approx(50.0, abs=1e-9)


def test_load_storm_hazards_from_parquet_for_points_defers_track_build(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.app.risk_engine.hazard_loader._count_tracks_from_parquet",
        lambda parquet_path, **kwargs: 800 if Path(parquet_path).stem == "storm" else 750,
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.hazard_loader._get_or_build_tracks",
        lambda *args, **kwargs: pytest.fail("track datasets should not be built during planning-only load"),
    )

    bundle = load_storm_hazards_from_parquet_for_points(
        storm_parquet_path=Path("storm.parquet"),
        cmcc_parquet_path=Path("storm_cmcc.parquet"),
        point_coords=[(16.2, -61.6)],
        storm_years=10000,
        build_hazards=False,
    )

    assert bundle.track_count_storm == 800
    assert bundle.track_count_storm_cmcc == 750
    assert bundle.tracks_storm is None
    assert bundle.tracks_storm_cmcc is None
    assert bundle.global_hazards_built is False
    assert bundle.storm_track_load_spec is not None
    assert bundle.storm_cmcc_track_load_spec is not None
    assert bundle.storm_track_load_spec.track_cache_max_entries == 0
    assert bundle.storm_cmcc_track_load_spec.track_cache_max_entries == 0


def test_resolve_hazard_bundle_tracks_loads_requested_provider_only(monkeypatch: pytest.MonkeyPatch):
    load_calls: list[tuple[str, int | None]] = []

    def _fake_get_or_build_tracks(parquet_path, **kwargs):
        load_calls.append((str(kwargs["provider_name"]), kwargs.get("track_cache_max_entries")))
        return SimpleNamespace(provider=str(kwargs["provider_name"]), path=Path(parquet_path).name)

    monkeypatch.setattr(
        "backend.app.risk_engine.hazard_loader._get_or_build_tracks",
        _fake_get_or_build_tracks,
    )

    bundle = HazardBundle(
        storm=None,
        storm_cmcc=None,
        storm_years=10000,
        normalized_on_copy=True,
        source="dynamic_parquet",
        global_hazards_built=False,
        storm_track_load_spec=SimpleNamespace(
            parquet_path=Path("storm.parquet"),
            provider_name="STORM",
            basin_ids=(1,),
            spatial_window=None,
            max_tracks=800,
            wind_unit_in="m/s",
            convert_10min_to_1min=True,
            radius_unit_in="km",
            env_pressure_hpa=1010.0,
            track_cache_max_entries=0,
        ),
        storm_cmcc_track_load_spec=SimpleNamespace(
            parquet_path=Path("storm_cmcc.parquet"),
            provider_name="STORM_CMCC",
            basin_ids=(1,),
            spatial_window=None,
            max_tracks=800,
            wind_unit_in="m/s",
            convert_10min_to_1min=True,
            radius_unit_in="km",
            env_pressure_hpa=1010.0,
            track_cache_max_entries=0,
        ),
    )

    storm_tracks = resolve_hazard_bundle_tracks(bundle, "storm")
    assert storm_tracks.provider == "STORM"
    assert load_calls == [("STORM", 0)]
    assert resolve_hazard_bundle_tracks(bundle, "storm") is storm_tracks
    assert load_calls == [("STORM", 0)]

    release_hazard_bundle_tracks(bundle, "storm")
    assert bundle.tracks_storm is None

    cmcc_tracks = resolve_hazard_bundle_tracks(bundle, "storm_cmcc")
    assert cmcc_tracks.provider == "STORM_CMCC"
    assert load_calls == [("STORM", 0), ("STORM_CMCC", 0)]