from __future__ import annotations

from types import ModuleType, SimpleNamespace
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine import targeted_cyclone_loader


class _FakeArray:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)


class _FakeTrack(dict):
    def __init__(self, *, name: str, sid: str, winds, lats, lons):
        super().__init__(
            {
                "max_sustained_wind": _FakeArray(winds),
                "lat": _FakeArray(lats),
                "lon": _FakeArray(lons),
            }
        )
        self.attrs = {"name": name, "sid": sid}


def test_resolve_ibtracs_cyclone_matches_unique_preset(monkeypatch) -> None:
    irma_track = _FakeTrack(
        name="IRMA",
        sid="2017242N16333",
        winds=[40.0, 55.0],
        lats=[16.1, 16.3],
        lons=[-58.2, -60.1],
    )
    other_track = _FakeTrack(
        name="IRMA",
        sid="2017001N00000",
        winds=[30.0, 35.0],
        lats=[10.0, 10.4],
        lons=[-40.0, -40.4],
    )

    monkeypatch.setattr(targeted_cyclone_loader, "ensure_ibtracs_file", lambda: Path("/tmp/IBTrACS.ALL.v04r01.nc"))
    monkeypatch.setattr(
        targeted_cyclone_loader,
        "_resolve_ibtracs_track_manually",
        lambda request, ibtracs_file: irma_track,
    )

    resolved = targeted_cyclone_loader.resolve_ibtracs_cyclone(
        targeted_cyclone_loader.TargetedCycloneRequest(
            preset_id="irma-2017",
            source="ibtracs",
            name="IRMA",
            season=2017,
            basin="NA",
            storm_id="2017242N16333",
        )
    )

    assert resolved.storm_id == "2017242N16333"
    assert resolved.original_name == "IRMA"


def test_resolve_ibtracs_cyclone_matches_storm_id_even_if_name_differs(monkeypatch) -> None:
    track = _FakeTrack(
        name="IRMA-ALT",
        sid="2017242N16333",
        winds=[40.0, 55.0],
        lats=[16.1, 16.3],
        lons=[-58.2, -60.1],
    )

    monkeypatch.setattr(targeted_cyclone_loader, "ensure_ibtracs_file", lambda: Path("/tmp/IBTrACS.ALL.v04r01.nc"))
    monkeypatch.setattr(
        targeted_cyclone_loader,
        "_resolve_ibtracs_track_manually",
        lambda request, ibtracs_file: track,
    )

    resolved = targeted_cyclone_loader.resolve_ibtracs_cyclone(
        targeted_cyclone_loader.TargetedCycloneRequest(
            preset_id="irma-2017",
            source="ibtracs",
            name="IRMA",
            season=2017,
            basin="NA",
            storm_id="2017242N16333",
        )
    )

    assert resolved.storm_id == "2017242N16333"
    assert resolved.original_name == "IRMA-ALT"


def test_transpose_track_to_territory_anchor_preserves_series_and_shifts_geometry() -> None:
    resolved = targeted_cyclone_loader.ResolvedTargetedCyclone(
        preset_id="irma-2017",
        source="ibtracs",
        name="IRMA",
        season=2017,
        basin="NA",
        storm_id="2017242N16333",
        original_name="IRMA",
        original_track=_FakeTrack(
            name="IRMA",
            sid="2017242N16333",
            winds=[35.0, 80.0, 60.0],
            lats=[10.0, 11.0, 12.0],
            lons=[-50.0, -51.0, -52.0],
        ),
    )

    transposed = targeted_cyclone_loader.transpose_track_to_territory_anchor(
        resolved,
        target_lat=17.92,
        target_lon=-62.86,
        territory_key="saint-barthelemy",
    )

    translated = transposed.translated_track
    np.testing.assert_allclose(translated["max_sustained_wind"].values, np.array([35.0, 80.0, 60.0]))
    np.testing.assert_allclose(translated["lat"].values, np.array([16.92, 17.92, 18.92]))
    np.testing.assert_allclose(translated["lon"].values, np.array([-61.86, -62.86, -63.86]))
    assert translated.attrs["name"] == "IRMA (transposed saint-barthelemy)"


def test_build_targeted_cyclone_hazard_bundle_uses_translated_tracks(monkeypatch) -> None:
    monkeypatch.setattr(targeted_cyclone_loader, "_build_centroids_from_points", lambda coords: {"coords": list(coords)})
    monkeypatch.setattr(targeted_cyclone_loader, "_build_hazard_from_tracks", lambda tracks, centroids: {"tracks": tracks, "centroids": centroids})
    monkeypatch.setattr(targeted_cyclone_loader, "_normalize_frequency_safe", lambda hazard, storm_years: {"hazard": hazard, "storm_years": storm_years})

    class _FakeTCTracks:
        def __init__(self):
            self.data = []

    climada_module = ModuleType("climada")
    hazard_module = ModuleType("climada.hazard")
    hazard_module.TCTracks = _FakeTCTracks
    monkeypatch.setitem(sys.modules, "climada", climada_module)
    monkeypatch.setitem(sys.modules, "climada.hazard", hazard_module)

    cyclone = targeted_cyclone_loader.TransposedTargetedCyclone(
        resolved=targeted_cyclone_loader.ResolvedTargetedCyclone(
            preset_id="irma-2017",
            source="ibtracs",
            name="IRMA",
            season=2017,
            basin="NA",
            storm_id="2017242N16333",
            original_name="IRMA",
            original_track=None,
        ),
        translated_track=_FakeTrack(
            name="IRMA",
            sid="2017242N16333",
            winds=[70.0],
            lats=[17.9],
            lons=[-62.8],
        ),
        anchor_index=0,
        anchor_lat=11.0,
        anchor_lon=-51.0,
        target_lat=17.9,
        target_lon=-62.8,
        lat_shift=6.9,
        lon_shift=-11.8,
    )

    bundle = targeted_cyclone_loader.build_targeted_cyclone_hazard_bundle(
        cyclones=[cyclone],
        point_coords=[(17.9, -62.8)],
    )

    assert bundle.source == "explicit_ibtracs_targeted"
    assert bundle.track_count_storm == 1
    assert bundle.storm_cmcc is None
    assert len(bundle.tracks_storm.data) == 1
