from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from types import SimpleNamespace

from climada.engine import Impact

from backend.app.risk_engine.climada_engine import (
    _ExposureShard,
    _build_exposure_with_impf_column,
    _build_pointwise_surge_hazard,
    _build_surge_hazard,
    _compute_pml,
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
    _resolve_effective_memory_budget_gb,
    _scoped_dynamic_progress_callback,
    _save_shard_checkpoint,
    _save_shard_split_plan,
    _split_exposure_shard,
    _should_use_pointwise_surge_fraction,
    HazardImpactResult,
    run_climada_direct_impacts,
)


def test_build_exposure_with_impf_column_does_not_mutate_original_gdf():
    base = SimpleNamespace(
        gdf=pd.DataFrame({"value": [1.0, 2.0]}),
        extra="keep-me",
    )

    result = _build_exposure_with_impf_column(
        base,
        haz_type="TC",
        impf_ids=[3, 7],
    )

    assert result is not base
    assert result.extra == "keep-me"
    assert "impf_TC" not in base.gdf.columns
    assert result.gdf["impf_TC"].tolist() == [3, 7]


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


def test_resolve_effective_memory_budget_gb_clamps_to_host_available_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._detect_available_memory_gb",
        lambda: 2.0,
    )

    assert _resolve_effective_memory_budget_gb(6.0) == pytest.approx(1.5, abs=1e-9)
    assert _resolve_effective_memory_budget_gb(1.0) == pytest.approx(1.0, abs=1e-9)


def test_resolve_component_point_cap_uses_memory_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._resolve_effective_memory_budget_gb",
        lambda value: 1.0,
    )

    cap = _resolve_component_point_cap(
        total_points=60_000,
        event_count=79_321,
        component_name="surge",
        memory_budget_gb=6.0,
        max_points_per_shard=0,
        min_points_per_shard=512,
    )

    assert 512 <= cap < 60_000


def test_resolve_dynamic_hazard_point_cap_uses_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._resolve_effective_memory_budget_gb",
        lambda value: 1.0,
    )

    cap = _resolve_dynamic_hazard_point_cap(
        total_points=110_315,
        event_count=1_500,
        memory_budget_gb=6.0,
        max_points_per_shard=0,
        min_points_per_shard=1,
    )

    assert 1 <= cap < 110_315


def test_resolve_dynamic_hazard_point_cap_reserves_headroom_for_800_track_builds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._resolve_effective_memory_budget_gb",
        lambda value: 1.0,
    )

    cap = _resolve_dynamic_hazard_point_cap(
        total_points=110_315,
        event_count=800,
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
        "backend.app.risk_engine.climada_engine._build_surge_hazard",
        lambda *args, **kwargs: (
            SimpleNamespace(
                centroids="dummy-centroids",
                frequency=np.array([1.0], dtype=float),
                event_id=np.array([101]),
                event_name=np.array(["evt-101"]),
            ),
            {},
        ),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._prepare_topo_raster_for_exposure",
        lambda path, point_records: path,
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
        multi_hazard_model=SimpleNamespace(rain_haz_type="TR", surge_haz_type="TCSurgeBathtub"),
        impfset_rain=object(),
        impfset_surge=object(),
        TCRain=DummyRain,
        TCSurgeBathtub=object(),
        surge_topo_path=Path(__file__),
        memory_budget_gb=1.0,
        max_points_per_shard=1,
        min_points_per_shard=1,
        max_shard_retry_depth=1,
        strict_required_components=True,
    )

    assert rain_calls == [{"model": "R-CLIPER", "max_dist_inland_km": 321.0}]
    assert total_metrics.aai_agg_eur == 30.0
    assert components["rain"].aai_agg_eur == 10.0
    assert components["surge"].aai_agg_eur == 10.0
    assert component_status["rain"] == "complete"
    assert component_status["surge"] == "complete"
    assert component_sharding["rain"]["status"] == "complete"
    assert component_sharding["surge"]["status"] == "complete"
    assert not any("component skipped" in note for note in component_notes)


def test_run_climada_direct_impacts_keeps_single_shard_dynamic_input_on_sharded_path(
    monkeypatch: pytest.MonkeyPatch,
):
    point_records = [
        {
            "point_id": "pt-1",
            "territory_id": "gua",
            "infra_class": "mixed",
            "asset_type": "habitation",
            "lat": 16.2,
            "lon": -61.6,
            "value_eur": 100.0,
        },
        {
            "point_id": "pt-2",
            "territory_id": "gua",
            "infra_class": "mixed",
            "asset_type": "habitation",
            "lat": 16.25,
            "lon": -61.55,
            "value_eur": 200.0,
        },
    ]
    exposure_bundle = SimpleNamespace(
        exposures=SimpleNamespace(),
        point_records=point_records,
    )
    bundle = SimpleNamespace(
        storm=None,
        storm_cmcc=None,
        storm_years=100,
        normalized_on_copy=True,
        source="dynamic_parquet",
        basin_ids=(1,),
        point_count=len(point_records),
        tracks_storm=None,
        tracks_storm_cmcc=None,
        track_count_storm=800,
        track_count_storm_cmcc=800,
        centroids=None,
        global_hazards_built=False,
        storm_track_load_spec=object(),
        storm_cmcc_track_load_spec=object(),
    )

    def _dummy_metrics(scale: float) -> HazardImpactResult:
        return HazardImpactResult(
            eai_direct_by_point=np.array([1.0, 2.0], dtype=float) * scale,
            max_loss_by_point=np.array([3.0, 4.0], dtype=float) * scale,
            at_event_loss=np.array([5.0], dtype=float) * scale,
            event_frequency=np.array([0.01], dtype=float),
            event_id=np.array([101]),
            event_name=np.array([f"evt-{int(scale)}"]),
            aai_agg_eur=3.0 * scale,
            max_event_loss_eur=5.0 * scale,
            pml_eur={10: 5.0 * scale, 20: 5.0 * scale, 50: 5.0 * scale, 100: 5.0 * scale, 200: 5.0 * scale, 1000: 5.0 * scale},
            tvar_95_eur=5.0 * scale,
            top_events=[{"event_id": 101, "event_name": f"evt-{int(scale)}", "loss_eur": 5.0 * scale}],
        )

    sharded_calls: list[dict[str, object]] = []
    resolved_track_calls: list[str] = []
    released_track_calls: list[str] = []

    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.get_tc_vulnerability_payload",
        lambda **kwargs: {
            "profile": "test-profile",
            "default_curve": "curve-a",
            "explicit_asset_type_mapping": {},
        },
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.try_build_climada_impact_funcs",
        lambda: [object()],
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._require_runtime",
        lambda: {
            "np": np,
            "ImpactCalc": object(),
            "ImpactFuncSet": lambda impact_funcs: impact_funcs,
        },
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: bundle,
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.resolve_hazard_bundle_tracks",
        lambda bundle_obj, hazard_key: resolved_track_calls.append(str(hazard_key)) or SimpleNamespace(data=[{"track_id": hazard_key}]),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.release_hazard_bundle_tracks",
        lambda bundle_obj, hazard_key: released_track_calls.append(str(hazard_key)),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine.load_storm_hazards",
        lambda *args, **kwargs: pytest.fail("dynamic parquet path should not fall back to precomputed hazards"),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._estimate_dynamic_hazard_memory_bytes",
        lambda **kwargs: 1024,
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._dynamic_hazard_budget_exceeded_at_min_shard",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._resolve_dynamic_hazard_point_cap",
        lambda **kwargs: len(point_records),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._build_hazard_from_tracks",
        lambda *args, **kwargs: pytest.fail("single-shard dynamic setup should not prebuild global hazards"),
    )

    def _fake_compute_dynamic_hazard_sharded_results(*args, **kwargs):
        hazard_key = str(kwargs["hazard_key"])
        scale = 1.0 if hazard_key == "storm" else 2.0
        metrics = _dummy_metrics(scale)
        assert kwargs["tracks"] is not None
        sharded_calls.append(
            {
                "hazard_key": hazard_key,
                "planned_shards": len(kwargs["hazard_shards"]),
                "hazard_point_cap": int(kwargs["hazard_point_cap"]),
            }
        )
        return (
            metrics,
            {"wind": metrics},
            {"wind": "complete"},
            {
                "wind": {
                    "status": "complete",
                    "completed_shards": 1,
                    "resumed_shards": 0,
                    "retry_splits": 0,
                    "sharded": False,
                }
            },
            [f"{hazard_key}: test note"],
        )

    monkeypatch.setattr(
        "backend.app.risk_engine.climada_engine._compute_dynamic_hazard_sharded_results",
        _fake_compute_dynamic_hazard_sharded_results,
    )

    result = run_climada_direct_impacts(
        exposure_bundle,
        hazard_storm_path=Path("storm.h5"),
        hazard_storm_cmcc_path=Path("storm_cmcc.h5"),
        storm_years=100,
        fallback_to_precomputed_hazards=False,
        strict_required_components=True,
        multi_hazard_enabled=False,
        storm_parquet_path=Path("storm.parquet"),
        storm_cmcc_parquet_path=Path("storm_cmcc.parquet"),
        dynamic_max_tracks=800,
        memory_budget_gb=6.0,
    )

    assert [call["hazard_key"] for call in sharded_calls] == ["storm", "storm_cmcc"]
    assert resolved_track_calls == ["storm", "storm_cmcc"]
    assert released_track_calls == ["storm", "storm_cmcc"]
    assert all(call["planned_shards"] == 1 for call in sharded_calls)
    assert all(call["hazard_point_cap"] == len(point_records) for call in sharded_calls)
    assert result.modeling["hazard_build_planned_shards"] == 1
    assert result.modeling["hazard_global_hazards_built"] is False
    assert result.modeling["hazard_build_sharded"] is True
    assert result.modeling["hazard_dynamic_max_tracks_requested"] == 800
    assert result.modeling["storm_convert_10min_to_1min"] is True
    assert result.modeling["hazard_event_stats_by_hazard"] == {
        "storm": {
            "event_count": 1,
            "nonzero_event_count": 1,
            "event_frequency_sum": 0.01,
        },
        "storm_cmcc": {
            "event_count": 1,
            "nonzero_event_count": 1,
            "event_frequency_sum": 0.01,
        },
    }


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
    assert result.pml_eur[10] == pytest.approx(3.36, abs=1e-9)
    assert result.pml_eur[50] == pytest.approx(12.0, abs=1e-9)
    assert result.pml_eur[1000] == pytest.approx(12.0, abs=1e-9)
    assert result.top_events[0]["event_id"] == 202
    assert result.top_events[0]["event_name"] == "evt-2"


def test_compute_pml_matches_climada_frequency_curve_interpolation():
    losses = np.array([3.0, 12.0, 0.0], dtype=float)
    frequency = np.array([0.1, 0.02, 0.0], dtype=float)
    return_periods = (10, 20, 50, 100, 200, 1000)

    impact_view = SimpleNamespace(
        at_event=losses,
        frequency=frequency,
        unit="EUR",
        frequency_unit="1/year",
    )
    expected_curve = Impact.calc_freq_curve(impact_view, np.asarray(return_periods, dtype=float))

    result = _compute_pml(np, losses, frequency, return_periods)

    for idx, rp in enumerate(return_periods):
        assert result[rp] == pytest.approx(float(expected_curve.impact[idx]), abs=1e-9)


def test_rebuild_component_result_preserves_explicit_asset_maxima():
    result = _rebuild_component_result(
        np,
        eai_by_point=np.array([10.0, 5.0], dtype=float),
        max_loss_by_point=np.array([12.0, 4.0], dtype=float),
        at_event_loss=np.array([3.0, 12.0, 0.0], dtype=float),
        event_frequency=np.array([0.1, 0.02, 0.0], dtype=float),
        event_id=np.array([101, 202, 303]),
        event_name=np.array(["evt-1", "evt-2", "evt-3"]),
        top_n_events=2,
    )

    assert result.max_loss_by_point.tolist() == [12.0, 4.0]


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
    assert rebuilt.max_loss_by_point.tolist() == [10.0, 11.0, 20.0, 22.0, 30.0]
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
            return np.array([0.0, -2000.0, 500.0], dtype=float)

    wind_hazard = SimpleNamespace(
        centroids=DummyCentroids(),
        intensity=sparse.csr_matrix(np.array([[30.0, 300.0, 50.0]], dtype=float)),
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
        inland_decay_rate=0.0,
        read_raster_sample_fn=lambda path, lat, lon: np.array([1.0, 20.0], dtype=float),
    )

    assert surge.intensity.indices.tolist() == [0, 1]
    assert surge.fraction.indices.tolist() == [0, 1]
    assert surge.fraction.data.tolist() == [1.0, 1.0]
    assert surge.event_id.tolist() == [101]
    assert surge.event_name.tolist() == ["evt-101"]
    assert surge.frequency.tolist() == [0.1]
    assert all(float(value) > 0.0 for value in surge.intensity.data.tolist())


def test_build_pointwise_surge_hazard_samples_raster_without_window_expansion(tmp_path: Path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster_path = tmp_path / "pointwise-topo.tif"
    data = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 20.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-1.5, 1.5, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)

    class DummyCentroids:
        def __init__(self):
            self.lat = np.array([0.0, 0.0, -1.0], dtype=float)
            self.lon = np.array([-1.0, 0.0, 1.0], dtype=float)
            self.crs = "EPSG:4326"

        def get_dist_coast(self, signed: bool = True):
            return np.array([0.0, -2000.0, 500.0], dtype=float)

    wind_hazard = SimpleNamespace(
        centroids=DummyCentroids(),
        intensity=sparse.csr_matrix(np.array([[30.0, 300.0, 50.0]], dtype=float)),
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
        topo_path=raster_path,
        inland_decay_rate=0.0,
    )

    assert surge.intensity.indices.tolist() == [0, 1]
    assert surge.fraction.indices.tolist() == [0, 1]
    assert surge.fraction.data.tolist() == [1.0, 1.0]
    assert surge.event_id.tolist() == [101]
    assert surge.event_name.tolist() == ["evt-101"]
    assert surge.frequency.tolist() == [0.1]
    assert all(float(value) > 0.0 for value in surge.intensity.data.tolist())


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