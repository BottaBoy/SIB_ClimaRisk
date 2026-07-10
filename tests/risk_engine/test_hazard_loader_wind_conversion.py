from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.app.risk_engine.hazard_loader import (
    HazardBundle,
    STORM_10MIN_TO_1MIN_WIND_FACTOR,
    _count_tracks_from_parquet,
    _convert_storm_wind_to_climada_mps,
    _load_track_sample_manifest,
    load_storm_hazards_from_parquet_for_points,
    normalize_hazard_frequency_from_tracks,
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


def test_count_tracks_from_parquet_uses_year_aware_track_identity(tmp_path: Path) -> None:
    parquet_path = tmp_path / "storm.parquet"
    pd.DataFrame(
        {
            "Basin ID": [1, 1, 1, 1],
            "Year": [0, 0, 1, 1],
            "track_id": ["storm:NA:0:10", "storm:NA:0:10", "storm:NA:1:10", "storm:NA:1:10"],
            "lat": [15.0, 15.1, 15.0, 15.1],
            "lon": [-61.0, -61.1, -61.0, -61.1],
        }
    ).to_parquet(parquet_path, index=False)

    track_count = _count_tracks_from_parquet(
        parquet_path,
        basin_ids=(1,),
        spatial_window=None,
        max_tracks=0,
    )

    assert track_count == 2


def test_count_tracks_from_parquet_uses_manifest_selection_before_max_tracks(tmp_path: Path) -> None:
    parquet_path = tmp_path / "storm.parquet"
    pd.DataFrame(
        {
            "Basin ID": [1, 1, 1, 1, 1, 1],
            "Year": [0, 0, 1, 1, 2, 2],
            "track_id": ["a", "a", "b", "b", "c", "c"],
            "lat": [15.0, 15.1, 16.0, 16.1, 17.0, 17.1],
            "lon": [-61.0, -61.1, -62.0, -62.1, -63.0, -63.1],
        }
    ).to_parquet(parquet_path, index=False)
    manifest_path = tmp_path / "sample.json"
    manifest_path.write_text(
        """
        {
          "sample_id": "unit-sample",
          "storm_years": 10000,
          "providers": {
            "storm": {
              "provider_name": "STORM",
              "tracks": [
                {"year": 0, "track_id": "a", "sample_weight": 10.0},
                {"year": 2, "track_id": "c", "sample_weight": 10.0}
              ]
            }
          }
        }
        """,
        encoding="utf-8",
    )
    sample_provider = _load_track_sample_manifest(manifest_path)["storm"]
    assert set(sample_provider.entries_by_instance_id) == {"storm|0|a", "storm|2|c"}

    track_count = _count_tracks_from_parquet(
        parquet_path,
        basin_ids=(1,),
        spatial_window=None,
        max_tracks=1,
        track_sample_provider=sample_provider,
    )

    assert track_count == 2


def test_count_tracks_from_parquet_rejects_missing_manifest_track(tmp_path: Path) -> None:
    parquet_path = tmp_path / "storm.parquet"
    pd.DataFrame(
        {
            "Basin ID": [1, 1],
            "Year": [0, 0],
            "track_id": ["a", "a"],
            "lat": [15.0, 15.1],
            "lon": [-61.0, -61.1],
        }
    ).to_parquet(parquet_path, index=False)
    manifest_path = tmp_path / "sample.json"
    manifest_path.write_text(
        """
        {
          "sample_id": "unit-sample",
          "storm_years": 10000,
          "providers": {
            "storm": {
              "provider_name": "STORM",
              "tracks": [
                {"year": 1, "track_id": "missing", "sample_weight": 10.0}
              ]
            }
          }
        }
        """,
        encoding="utf-8",
    )
    sample_provider = _load_track_sample_manifest(manifest_path)["storm"]

    with pytest.raises(ValueError, match="absent after basin/spatial filtering"):
        _count_tracks_from_parquet(
            parquet_path,
            basin_ids=(1,),
            spatial_window=None,
            max_tracks=0,
            track_sample_provider=sample_provider,
        )


def test_normalize_hazard_frequency_from_tracks_uses_sample_weights() -> None:
    hazard = SimpleNamespace(frequency=np.ones(2, dtype=float))
    tracks = SimpleNamespace(
        data=[
            SimpleNamespace(attrs={"sib_sample_weight": 2.0}),
            SimpleNamespace(attrs={"sib_sample_weight": 5.0}),
        ]
    )

    out = normalize_hazard_frequency_from_tracks(hazard, tracks, storm_years=10000)

    assert out.frequency.tolist() == pytest.approx([0.0002, 0.0005])
    assert getattr(out, "_sib_sample_weighted_frequency") is True
