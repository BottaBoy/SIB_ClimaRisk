from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.config import Settings
from backend.app.risk_engine.climada_engine import run_climada_direct_impacts
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