from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import sparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import scripts.build_guadeloupe_wind_maps as wind_maps


def test_validate_rain_metric_relationships_rejects_flat_positive_return_levels():
    with pytest.raises(ValueError, match="collapsed to the event maximum"):
        wind_maps._validate_rain_metric_relationships(
            {
                (16.25, -61.5): {
                    "rp50": 800.0,
                    "rp100": 800.0,
                    "event_max": 800.0,
                    "sample_count": 12,
                }
            },
            hazard_key="storm",
        )


def test_build_native_wind_and_rain_maps_normalizes_rain_frequency(monkeypatch: pytest.MonkeyPatch):
    wind_hazard = SimpleNamespace(
        intensity=sparse.csr_matrix(np.array([[12.0], [18.0]], dtype=float)),
        frequency=np.array([0.02, 0.02], dtype=float),
        centroids=SimpleNamespace(lat=np.array([16.2]), lon=np.array([-61.5])),
    )
    rain_hazard_raw = SimpleNamespace(
        intensity=sparse.csr_matrix(np.array([[100.0], [200.0]], dtype=float)),
        frequency=np.array([1.0, 1.0], dtype=float),
        centroids=SimpleNamespace(lat=np.array([16.2]), lon=np.array([-61.5])),
    )
    bundle = SimpleNamespace(
        storm=wind_hazard,
        storm_cmcc=wind_hazard,
        storm_years=100,
        source="dynamic_parquet",
        basin_ids=(1,),
        tracks_storm=SimpleNamespace(data=[{"track_id": 1}, {"track_id": 2}]),
        tracks_storm_cmcc=SimpleNamespace(data=[{"track_id": 3}, {"track_id": 4}]),
    )

    class _FakeTCRain:
        @staticmethod
        def from_tracks(*args, **kwargs):
            return SimpleNamespace(
                intensity=rain_hazard_raw.intensity,
                frequency=np.array(rain_hazard_raw.frequency, dtype=float),
                centroids=rain_hazard_raw.centroids,
            )

    seen_rain_frequencies: list[list[float]] = []

    def fake_summarize(hazard_obj):
        freq = np.asarray(getattr(hazard_obj, "frequency", []), dtype=float).reshape(-1)
        if freq.size and np.allclose(freq, [0.01, 0.01]):
            seen_rain_frequencies.append(freq.tolist())
            return {
                (16.2, -61.5): {
                    "mean": 150.0,
                    "rp50": 100.0,
                    "rp100": 200.0,
                    "event_max": 300.0,
                    "sample_count": 2,
                }
            }
        return {
            (16.2, -61.5): {
                "mean": 15.0,
                "rp50": 12.0,
                "rp100": 18.0,
                "event_max": 18.0,
                "sample_count": 2,
            }
        }

    monkeypatch.setattr(wind_maps, "_require_climada_petals", lambda: (_FakeTCRain, object()))
    monkeypatch.setattr(wind_maps, "load_storm_hazards_from_parquet_for_points", lambda **kwargs: bundle)
    monkeypatch.setattr(wind_maps, "_summarize_hazard_by_coord", fake_summarize)

    rain_maps, meta = wind_maps._build_native_rain_maps(
        point_coords=[(16.2, -61.5)],
        dynamic_max_tracks=2,
        settings=SimpleNamespace(
            storm_years=100,
            storm_wind_unit_in="m/s",
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_track_cache_max_entries=8,
            hazard_rain_model="R-CLIPER",
        ),
        storm_parquet_path=wind_maps.REPO_ROOT / "dummy-storm.parquet",
        storm_cmcc_parquet_path=wind_maps.REPO_ROOT / "dummy-storm-cmcc.parquet",
    )

    assert seen_rain_frequencies == [[0.01, 0.01], [0.01, 0.01]]
    assert rain_maps["storm"][(16.2, -61.5)]["rp50_rain_mm"] == pytest.approx(100.0)
    assert rain_maps["storm"][(16.2, -61.5)]["rp50_rain_mmph"] == pytest.approx(100.0)
    assert meta["storm_tracks"] == 2