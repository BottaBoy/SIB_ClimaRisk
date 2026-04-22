import numpy as np
import pytest
from scipy import sparse
from types import SimpleNamespace

from backend.app.risk_engine.climada_engine import (
    _ExposureShard,
    _build_pointwise_surge_hazard,
    _build_surge_hazard,
    _compute_dynamic_hazard_sharded_results,
    _finalize_component_result_accumulator,
    _estimate_fraction_raster_shape,
    _init_component_result_accumulator,
    _load_shard_checkpoint,
    _load_shard_split_plan,
    _merge_component_result_accumulator,
    _plan_hazard_shards,
    _point_records_bounds_wgs84,
    _plan_exposure_shards,
    _rebuild_component_result,
    _resolve_component_point_cap,
    _resolve_dynamic_hazard_point_cap,
    _scoped_dynamic_progress_callback,
    _save_shard_checkpoint,
    _save_shard_split_plan,
    _split_exposure_shard,
    _should_use_pointwise_surge_fraction,
    HazardImpactResult,
)


def test_plan_exposure_shards_groups_and_caps_points():
    point_records = [
        {"territory_id": "gua-a", "infra_class": "elec_aerien"},
        {"territory_id": "gua-a", "infra_class": "elec_aerien"},
        {"territory_id": "gua-a", "infra_class": "elec_aerien"},
        {"territory_id": "gua-a", "infra_class": "eau_reseau"},
        {"territory_id": "gua-a", "infra_class": "eau_reseau"},
        {"territory_id": "mar-b", "infra_class": "elec_aerien"},
    ]

    shards = _plan_exposure_shards(point_records, max_points_per_shard=2)

    assert [tuple(shard.point_indices) for shard in shards] == [
        (0, 1),
        (2,),
        (3, 4),
        (5,),
    ]
    assert [shard.territory_id for shard in shards] == ["gua-a", "gua-a", "gua-a", "mar-b"]
    assert [shard.infra_class for shard in shards] == [
        "elec_aerien",
        "elec_aerien",
        "eau_reseau",
        "elec_aerien",
    ]


def test_split_exposure_shard_respects_min_points():
    shard = _ExposureShard(
        shard_id="shard-0007",
        point_indices=tuple(range(8)),
        territory_id="gua",
        infra_class="surge",
    )

    split = _split_exposure_shard(shard, min_points_per_shard=4)
    assert split is not None
    assert [tuple(item.point_indices) for item in split] == [(0, 1, 2, 3), (4, 5, 6, 7)]
    assert [item.retry_depth for item in split] == [1, 1]

    assert _split_exposure_shard(shard, min_points_per_shard=5) is None


def test_resolve_component_point_cap_uses_memory_budget():
    cap = _resolve_component_point_cap(
        total_points=60_000,
        event_count=79_321,
        component_name="surge",
        memory_budget_gb=6.0,
        max_points_per_shard=0,
        min_points_per_shard=512,
    )

    assert 512 <= cap < 60_000


def test_resolve_dynamic_hazard_point_cap_uses_budget():
    cap = _resolve_dynamic_hazard_point_cap(
        total_points=110_315,
        event_count=1_500,
        memory_budget_gb=6.0,
        max_points_per_shard=0,
        min_points_per_shard=1,
    )

    assert 1 <= cap < 110_315


def test_plan_hazard_shards_prefers_territory_groups_only():
    point_records = [
        {"territory_id": "gua", "infra_class": "elec_aerien"},
        {"territory_id": "gua", "infra_class": "eau_reseau"},
        {"territory_id": "gua", "infra_class": "eau_reseau"},
        {"territory_id": "mar", "infra_class": "elec_aerien"},
        {"territory_id": "mar", "infra_class": "eau_reseau"},
    ]

    shards = _plan_hazard_shards(point_records, max_points_per_shard=2)

    assert [tuple(shard.point_indices) for shard in shards] == [
        (0, 1),
        (2,),
        (3, 4),
    ]
    assert [shard.territory_id for shard in shards] == ["gua", "gua", "mar"]
    assert all(shard.infra_class == "mixed" for shard in shards)


def test_dynamic_hazard_sharded_rain_uses_configured_inland_distance(monkeypatch: pytest.MonkeyPatch):
    point_records = [
        {
            "point_id": "pt-1",
            "territory_id": "gua",
            "infra_class": "mixed",
            "asset_type": "habitation",
            "lat": 16.2,
            "lon": -61.6,
            "value_eur": 100.0,
        }
    ]
    exposure_bundle = SimpleNamespace(
        exposures=SimpleNamespace(),
        point_records=point_records,
    )
    hazard_shards = [
        _ExposureShard(
            shard_id="hazard-0001",
            point_indices=(0,),
            territory_id="gua",
            infra_class="mixed",
        )
    ]

    def _dummy_metrics() -> HazardImpactResult:
        return HazardImpactResult(
            eai_direct_by_point=np.array([10.0], dtype=float),
            max_loss_by_point=np.array([10.0], dtype=float),
            at_event_loss=np.array([5.0], dtype=float),
            event_frequency=np.array([0.1], dtype=float),
            event_id=np.array([101]),
            event_name=np.array(["evt-101"]),
            aai_agg_eur=10.0,
            max_event_loss_eur=5.0,
            pml_eur={10: 5.0, 20: 0.0, 50: 0.0, 100: 0.0, 200: 0.0},
            tvar_95_eur=5.0,
            top_events=[{"event_id": 101, "event_name": "evt-101", "loss_eur": 5.0}],
        )

    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.subset_climada_exposure_bundle",
        lambda bundle, point_indices: SimpleNamespace(
            exposures=SimpleNamespace(),
            point_records=[point_records[idx] for idx in point_indices],
        ),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._build_centroids_from_points",
        lambda coords: "dummy-centroids",
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._build_hazard_from_tracks",
        lambda tracks, centroids: SimpleNamespace(
            centroids=centroids,
            frequency=np.array([1.0], dtype=float),
            event_id=np.array([101]),
            event_name=np.array(["evt-101"]),
        ),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._compute_component_impact_sharded",
        lambda *args, **kwargs: (
            _dummy_metrics(),
            {
                "completed_shards": 1,
                "resumed_shards": 0,
                "retry_splits": 0,
                "sharded": False,
            },
        ),
    )

    rain_calls: list[dict[str, float | str]] = []

    class DummyRain:
        @staticmethod
        def from_tracks(tracks, centroids, model, ignore_distance_to_coast, max_dist_inland_km):
            rain_calls.append(
                {
                    "model": str(model),
                    "max_dist_inland_km": float(max_dist_inland_km),
                }
            )
            return SimpleNamespace(
                centroids=centroids,
                frequency=np.array([1.0], dtype=float),
                event_id=np.array([101]),
                event_name=np.array(["evt-101"]),
            )

    total_metrics, components, component_status, component_sharding, component_notes = _compute_dynamic_hazard_sharded_results(
        np,
        object(),
        exposure_bundle=exposure_bundle,
        tracks=SimpleNamespace(data=[{"track_id": 1}]),
        hazard_key="storm",
        storm_years=100,
        top_n_events=1,
        hazard_shards=hazard_shards,
        hazard_point_cap=1,
        impfset_wind=object(),
        requested_rain_model="R-CLIPER",
        rain_max_dist_inland_km=321.0,
        multi_hazard_ready=True,
        multi_hazard_model=SimpleNamespace(rain_haz_type="TR"),
        impfset_rain=object(),
        impfset_surge=None,
        TCRain=DummyRain,
        TCSurgeBathtub=None,
        surge_topo_path=None,
        memory_budget_gb=1.0,
        max_points_per_shard=1,
        min_points_per_shard=1,
        max_shard_retry_depth=1,
        strict_required_components=True,
    )

    assert rain_calls == [{"model": "R-CLIPER", "max_dist_inland_km": 321.0}]
    assert total_metrics.aai_agg_eur == 20.0
    assert components["rain"].aai_agg_eur == 10.0
    assert component_status["rain"] == "complete"
    assert component_sharding["rain"]["status"] == "complete"
    assert any("surge component skipped" in note for note in component_notes)


def test_rebuild_component_result_recomputes_metrics_from_arrays():
    result = _rebuild_component_result(
        np,
        eai_by_point=np.array([10.0, 5.0], dtype=float),
        at_event_loss=np.array([3.0, 12.0, 0.0], dtype=float),
        event_frequency=np.array([0.1, 0.02, 0.0], dtype=float),
        event_id=np.array([101, 202, 303]),
        event_name=np.array(["evt-1", "evt-2", "evt-3"]),
        top_n_events=2,
    )

    assert result.aai_agg_eur == 15.0
    assert result.max_event_loss_eur == 12.0
    assert result.max_loss_by_point.tolist() == [8.0, 4.0]
    assert result.pml_eur[10] == 3.0
    assert result.top_events[0]["event_id"] == 202
    assert result.top_events[0]["event_name"] == "evt-2"


def test_dynamic_hazard_accumulator_reassembles_full_point_order_and_event_totals():
    acc = _init_component_result_accumulator(np, total_points=5)

    shard_a = _ExposureShard(
        shard_id="hazard-0001",
        point_indices=(0, 2, 4),
        territory_id="gua",
        infra_class="mixed",
    )
    shard_b = _ExposureShard(
        shard_id="hazard-0002",
        point_indices=(1, 3),
        territory_id="gua",
        infra_class="mixed",
    )

    metrics_a = HazardImpactResult(
        eai_direct_by_point=np.array([10.0, 20.0, 30.0], dtype=float),
        max_loss_by_point=np.array([10.0, 20.0, 30.0], dtype=float),
        at_event_loss=np.array([1.0, 2.0], dtype=float),
        event_frequency=np.array([0.1, 0.05], dtype=float),
        event_id=np.array([101, 202]),
        event_name=np.array(["evt-1", "evt-2"]),
        aai_agg_eur=60.0,
        max_event_loss_eur=2.0,
        pml_eur={10: 0.0, 20: 0.0, 50: 0.0, 100: 0.0, 200: 0.0},
        tvar_95_eur=0.0,
        top_events=[],
    )
    metrics_b = HazardImpactResult(
        eai_direct_by_point=np.array([11.0, 22.0], dtype=float),
        max_loss_by_point=np.array([11.0, 22.0], dtype=float),
        at_event_loss=np.array([3.0, 4.0], dtype=float),
        event_frequency=np.array([0.1, 0.05], dtype=float),
        event_id=np.array([101, 202]),
        event_name=np.array(["evt-1", "evt-2"]),
        aai_agg_eur=33.0,
        max_event_loss_eur=4.0,
        pml_eur={10: 0.0, 20: 0.0, 50: 0.0, 100: 0.0, 200: 0.0},
        tvar_95_eur=0.0,
        top_events=[],
    )

    _merge_component_result_accumulator(np, accumulator=acc, shard=shard_a, metrics=metrics_a)
    _merge_component_result_accumulator(np, accumulator=acc, shard=shard_b, metrics=metrics_b)
    rebuilt = _finalize_component_result_accumulator(
        np,
        accumulator=acc,
        event_count=2,
        top_n_events=2,
    )

    assert rebuilt.eai_direct_by_point.tolist() == [10.0, 11.0, 20.0, 22.0, 30.0]
    assert rebuilt.at_event_loss.tolist() == [4.0, 6.0]
    assert rebuilt.event_frequency.tolist() == [0.1, 0.05]
    assert list(rebuilt.event_id) == [101, 202]


def test_scoped_dynamic_progress_callback_filters_component_events_and_prefixes_shards():
    seen = []
    callback = _scoped_dynamic_progress_callback(
        lambda payload: seen.append(payload),
        hazard_shard_id="hazard-0003",
    )

    assert callback is not None
    callback({"event": "component_plan", "component": "wind"})
    callback({"event": "shard_start", "component": "wind", "shard_id": "shard-0001"})
    callback({"event": "component_complete", "component": "wind"})

    assert seen == [
        {
            "event": "shard_start",
            "component": "wind",
            "shard_id": "hazard-0003__shard-0001",
            "hazard_shard_id": "hazard-0003",
        }
    ]


def test_shard_checkpoint_round_trip_rebuilds_metrics(tmp_path):
    shard = _ExposureShard(
        shard_id="shard-0001",
        point_indices=(0, 1),
        territory_id="gua",
        infra_class="surge",
    )
    point_records = [
        {"point_id": "pt-1", "territory_id": "gua", "infra_class": "surge"},
        {"point_id": "pt-2", "territory_id": "gua", "infra_class": "surge"},
    ]
    metrics = HazardImpactResult(
        eai_direct_by_point=np.array([10.0, 5.0], dtype=float),
        max_loss_by_point=np.array([8.0, 4.0], dtype=float),
        at_event_loss=np.array([3.0, 12.0], dtype=float),
        event_frequency=np.array([0.1, 0.02], dtype=float),
        event_id=np.array([101, 202]),
        event_name=np.array(["evt-1", "evt-2"]),
        aai_agg_eur=15.0,
        max_event_loss_eur=12.0,
        pml_eur={10: 3.0, 20: 0.0, 50: 0.0, 100: 0.0, 200: 0.0},
        tvar_95_eur=12.0,
        top_events=[{"event_id": 202, "event_name": "evt-2", "loss_eur": 12.0}],
    )

    checkpoint_path = _save_shard_checkpoint(
        np,
        checkpoint_dir=tmp_path,
        hazard_key="storm",
        component_name="surge",
        shard=shard,
        point_records=point_records,
        metrics=metrics,
    )

    assert checkpoint_path is not None
    assert checkpoint_path.exists()

    loaded = _load_shard_checkpoint(
        np,
        checkpoint_dir=tmp_path,
        hazard_key="storm",
        component_name="surge",
        shard=shard,
        point_records=point_records,
        top_n_events=2,
    )

    assert loaded is not None
    assert loaded.eai_direct_by_point.tolist() == [10.0, 5.0]
    assert loaded.at_event_loss.tolist() == [3.0, 12.0]
    assert loaded.event_frequency.tolist() == [0.1, 0.02]
    assert list(loaded.event_id) == ["101", "202"]
    assert list(loaded.event_name) == ["evt-1", "evt-2"]
    assert loaded.aai_agg_eur == 15.0
    assert loaded.top_events[0]["event_id"] == 202


def test_shard_checkpoint_is_ignored_when_point_ids_do_not_match(tmp_path):
    shard = _ExposureShard(
        shard_id="shard-0002",
        point_indices=(0, 1),
        territory_id="gua",
        infra_class="wind",
    )
    saved_records = [
        {"point_id": "pt-1", "territory_id": "gua", "infra_class": "wind"},
        {"point_id": "pt-2", "territory_id": "gua", "infra_class": "wind"},
    ]
    _save_shard_checkpoint(
        np,
        checkpoint_dir=tmp_path,
        hazard_key="storm",
        component_name="wind",
        shard=shard,
        point_records=saved_records,
        metrics=HazardImpactResult(
            eai_direct_by_point=np.array([1.0, 2.0], dtype=float),
            max_loss_by_point=np.array([1.0, 2.0], dtype=float),
            at_event_loss=np.array([3.0], dtype=float),
            event_frequency=np.array([0.1], dtype=float),
            event_id=np.array([101]),
            event_name=np.array(["evt"]),
            aai_agg_eur=3.0,
            max_event_loss_eur=3.0,
            pml_eur={10: 3.0, 20: 0.0, 50: 0.0, 100: 0.0, 200: 0.0},
            tvar_95_eur=3.0,
            top_events=[{"event_id": 101, "event_name": "evt", "loss_eur": 3.0}],
        ),
    )

    loaded = _load_shard_checkpoint(
        np,
        checkpoint_dir=tmp_path,
        hazard_key="storm",
        component_name="wind",
        shard=shard,
        point_records=[
            {"point_id": "pt-1", "territory_id": "gua", "infra_class": "wind"},
            {"point_id": "pt-9", "territory_id": "gua", "infra_class": "wind"},
        ],
        top_n_events=1,
    )

    assert loaded is None


def test_shard_split_plan_round_trip(tmp_path):
    parent = _ExposureShard(
        shard_id="shard-0003",
        point_indices=tuple(range(8)),
        territory_id="gua",
        infra_class="rain",
    )
    children = _split_exposure_shard(parent, min_points_per_shard=4)

    assert children is not None

    plan_path = _save_shard_split_plan(
        checkpoint_dir=tmp_path,
        hazard_key="storm_cmcc",
        component_name="rain",
        parent_shard=parent,
        child_shards=children,
    )

    assert plan_path is not None
    assert plan_path.exists()

    loaded = _load_shard_split_plan(
        checkpoint_dir=tmp_path,
        hazard_key="storm_cmcc",
        component_name="rain",
        shard=parent,
    )

    assert loaded is not None
    assert [item.shard_id for item in loaded] == [item.shard_id for item in children]
    assert [tuple(item.point_indices) for item in loaded] == [tuple(item.point_indices) for item in children]
    assert [item.retry_depth for item in loaded] == [item.retry_depth for item in children]


def test_point_records_bounds_wgs84_applies_padding_and_clamps():
    bounds = _point_records_bounds_wgs84(
        [
            {"lon": -61.8, "lat": 15.9},
            {"lon": -61.1, "lat": 16.5},
        ],
        padding_degrees=0.25,
    )

    assert bounds == (-62.05, 15.65, -60.85, 16.75)


def test_estimate_fraction_raster_shape_reports_large_virtual_grid():
    centroids = SimpleNamespace(
        lat=np.array([15.0, 15.00001, 16.0], dtype=float),
        lon=np.array([-61.0, -60.99999, -60.0], dtype=float),
        total_bounds=np.array([-61.0, 15.0, -60.0, 16.0], dtype=float),
        size=3,
    )

    info = _estimate_fraction_raster_shape(
        centroids,
        get_resolution_fn=lambda lat, lon: (1e-5, 1e-5),
        pts_to_raster_meta_fn=lambda points_bounds, res: (100_000, 120_000, None),
    )

    assert info == {
        "rows": 100_000,
        "cols": 120_000,
        "cells": 12_000_000_000,
        "centroid_count": 3,
    }
    assert _should_use_pointwise_surge_fraction(centroids, fraction_grid_info=info)


def test_build_pointwise_surge_hazard_uses_unit_land_fraction_for_point_centroids():
    class DummyCentroids:
        def __init__(self):
            self.lat = np.array([16.0, 16.1, 16.2], dtype=float)
            self.lon = np.array([-61.7, -61.6, -61.5], dtype=float)
            self.crs = "EPSG:4326"

        def get_dist_coast(self, signed: bool = True):
            return np.array([-1000.0, -2000.0, 500.0], dtype=float)

    wind_hazard = SimpleNamespace(
        centroids=DummyCentroids(),
        intensity=sparse.csr_matrix(np.array([[30.0, 40.0, 50.0]], dtype=float)),
        event_id=np.array([101]),
        event_name=np.array(["evt-101"]),
        date=np.array([123456]),
        orig=np.array([False]),
        frequency=np.array([0.1], dtype=float),
    )

    class DummySurgeHazard:
        pass

    surge = _build_pointwise_surge_hazard(
        np,
        surge_hazard_cls=DummySurgeHazard,
        wind_hazard=wind_hazard,
        topo_path="dummy-topo.tif",
        read_raster_sample_fn=lambda path, lat, lon: np.array([1.0, 20.0], dtype=float),
    )

    assert surge.intensity.indices.tolist() == [0]
    assert surge.fraction.indices.tolist() == [0]
    assert surge.fraction.data.tolist() == [1.0]
    assert surge.event_id.tolist() == [101]
    assert surge.event_name.tolist() == ["evt-101"]
    assert surge.frequency.tolist() == [0.1]
    assert float(surge.intensity.data[0]) > 0.0


def test_build_surge_hazard_prefers_pointwise_mode_for_dynamic_source(monkeypatch: pytest.MonkeyPatch):
    wind_hazard = SimpleNamespace(centroids=SimpleNamespace())

    class DummySurgeHazard:
        @staticmethod
        def from_tc_winds(wind_hazard, topo_path):
            raise AssertionError("raster surge path should not be used for dynamic exposure centroids")

    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._estimate_fraction_raster_shape",
        lambda centroids: {"rows": 10, "cols": 20, "cells": 200, "centroid_count": 5},
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._build_pointwise_surge_hazard",
        lambda np_mod, **kwargs: "pointwise-surge",
    )

    surge_hazard, meta = _build_surge_hazard(
        np,
        surge_hazard_cls=DummySurgeHazard,
        wind_hazard=wind_hazard,
        topo_path="dummy-topo.tif",
        hazard_source="dynamic_parquet",
    )

    assert surge_hazard == "pointwise-surge"
    assert meta["fraction_mode"] == "pointwise"
    assert meta["reason"] == "dynamic_exposure_centroids"