from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import Settings
from backend.app.risk_engine.climada_engine import (
    ClimadaRunResult,
    HazardImpactResult,
    RETURN_PERIODS,
    run_climada_direct_impacts,
)
from backend.app.risk_engine.impact_runner import compute_impacts
from backend.app.risk_engine.types import DisaggregationSummary, NormalizedExposure


def _empty_exposure() -> NormalizedExposure:
    return NormalizedExposure(
        source_name="test",
        source_format="geojson",
        input_mode="upload",
        features=[],
    )


def _empty_disaggregation() -> DisaggregationSummary:
    return DisaggregationSummary(
        spacing_m=100.0,
        metric_crs="EPSG:3857",
        asset_count_points=0,
        by_geometry_type={},
    )


def test_compute_impacts_rejects_removed_fallback_mode() -> None:
    with pytest.raises(ValueError, match="Scientific fallback impact mode has been removed"):
        compute_impacts(
            _empty_exposure(),
            _empty_disaggregation(),
            settings=Settings(impact_engine_mode="fallback"),
        )


def test_compute_impacts_rejects_non_strict_scientific_settings() -> None:
    with pytest.raises(ValueError, match="SIB_RISK_CLIMADA_STRICT_REQUIRED_COMPONENTS must remain enabled"):
        compute_impacts(
            _empty_exposure(),
            _empty_disaggregation(),
            settings=Settings(climada_strict_required_components=False),
        )


def test_run_climada_direct_impacts_rejects_removed_precomputed_fallback() -> None:
    with pytest.raises(ValueError, match="Scientific fallback to precomputed hazards has been removed"):
        run_climada_direct_impacts(
            SimpleNamespace(point_records=[], exposures=SimpleNamespace()),
            hazard_storm_path=Path("storm.h5"),
            hazard_storm_cmcc_path=Path("storm_cmcc.h5"),
            storm_years=100,
            fallback_to_precomputed_hazards=True,
            strict_required_components=True,
            multi_hazard_enabled=False,
        )


def test_compute_impacts_forwards_targeted_hazard_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_compute(*args, **kwargs):
        captured["hazard_keys"] = kwargs.get("hazard_keys")
        captured["explicit_hazard_bundle"] = kwargs.get("explicit_hazard_bundle")
        return "ok"

    monkeypatch.setattr("backend.app.risk_engine.impact_runner._compute_impacts_climada", _fake_compute)

    explicit_bundle = object()
    result = compute_impacts(
        _empty_exposure(),
        _empty_disaggregation(),
        settings=Settings(),
        hazard_keys=("storm",),
        explicit_hazard_bundle=explicit_bundle,
    )

    assert result == "ok"
    assert captured["hazard_keys"] == ("storm",)
    assert captured["explicit_hazard_bundle"] is explicit_bundle


def test_compute_impacts_zero_fills_unselected_hazard_for_targeted_runs(monkeypatch, tmp_path) -> None:
    def _hazard_result() -> HazardImpactResult:
        return HazardImpactResult(
            eai_direct_by_point=np.array([12.0], dtype=float),
            max_loss_by_point=np.array([18.0], dtype=float),
            at_event_loss=np.array([25.0], dtype=float),
            event_frequency=np.array([1.0], dtype=float),
            event_id=np.array([101]),
            event_name=np.array(["irma-targeted"]),
            aai_agg_eur=12.0,
            max_event_loss_eur=25.0,
            pml_eur={int(rp): float(rp) for rp in RETURN_PERIODS},
            tvar_95_eur=30.0,
            top_events=[{"event_id": 101, "event_name": "irma-targeted", "loss_eur": 25.0}],
            raw_max_event_loss_eur=25.0,
        )

    monkeypatch.setattr(
        "backend.app.risk_engine.impact_runner.run_climada_direct_impacts",
        lambda *args, **kwargs: ClimadaRunResult(
            hazards={"storm": _hazard_result()},
            component_hazards={"storm": {}},
            modeling={"hazard_exposure_matching_qa": {}},
            notes=[],
        ),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.impact_runner.aggregate_impacts_with_interdependency",
        lambda **kwargs: SimpleNamespace(
            portfolio_by_hazard={
                "storm": {"eai_direct_eur": 12.0, "eai_indirect_eur": 0.0, "eai_total_eur": 12.0},
                "storm_cmcc": {"eai_direct_eur": 0.0, "eai_indirect_eur": 0.0, "eai_total_eur": 0.0},
            },
            dependency_scaler_by_hazard={"storm": 1.0, "storm_cmcc": 1.0},
            component_health={},
            interdependency={},
            native_service_states_by_hazard={},
            projected_service_states_by_territory={},
            projected_service_coverage_by_territory={},
            projected_service_units_by_territory={},
            state_aggregation_metadata={},
            territory_results=[],
            asset_results=[],
        ),
    )
    monkeypatch.setattr(
        "backend.app.risk_engine.impact_runner._build_climada_coherence_report",
        lambda **kwargs: ({"status": "passed", "checks": []}, []),
    )

    prebuilt_bundle = SimpleNamespace(
        point_records=[{"lat": 17.9, "lon": -62.8, "value_eur": 100.0, "asset_type": "elec_bt_aerien"}],
        exposures=SimpleNamespace(),
        warnings=[],
    )
    result = compute_impacts(
        _empty_exposure(),
        _empty_disaggregation(),
        settings=Settings(
            multi_hazard_enabled=False,
            population_data_dir=str(tmp_path / "missing-population"),
        ),
        prebuilt_bundle=prebuilt_bundle,
        hazard_keys=("storm",),
    )

    assert result.portfolio_results["storm"]["eai_eur"] == pytest.approx(12.0)
    assert result.portfolio_results["storm_cmcc"]["eai_eur"] == pytest.approx(0.0)
    assert result.portfolio_results["event_summary"]["storm_top_events"][0]["event_name"] == "irma-targeted"
    assert result.portfolio_results["event_summary"]["storm_cmcc_top_events"] == []
    assert result.graphs["storm_cmcc"]["annual_fec"]["damage_eur"] == [0.0 for _ in RETURN_PERIODS]
    pml_inputs = result.artifacts["pml_network_graph_inputs"]
    assert pml_inputs["schema_version"] == "pml_network_graph_inputs_v1"
    assert pml_inputs["scenarios"] == ["rp10", "rp50", "rp100", "rp1000"]
    assert pml_inputs["target_totals_by_hazard"]["storm"]["rp10"] == pytest.approx(10.0)
    assert pml_inputs["target_totals_by_hazard"]["storm_cmcc"]["rp10"] == pytest.approx(0.0)
    assert any(
        row["storm"]["direct_damage_eur"] > 0.0
        for row in pml_inputs["state_damage_tables"]["rp10"]
        if row["class_key"].startswith("elec_")
    )
    assert any("zero-filled" in note for note in result.notes)
