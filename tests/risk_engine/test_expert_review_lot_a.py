from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.risk_engine.expert_review_baseline import (
    build_regression_rows,
    default_valuation_count_source,
    infer_default_valuation_asset_count,
    publication_fallback_present,
    scientific_fallback_present,
)
from backend.app.risk_engine.climada_engine import _normalize_frequency_on_copy
from backend.app.risk_engine.hazard_loader import _normalize_frequency_safe
from backend.app.risk_engine.impact_functions_multi_hazard import RUNOFF_COEFF_BY_INFRA_CLASS
from backend.app.risk_engine.population_loader import TERRITORY_GRID_DEG


class _FreqVector:
    def __init__(self, values):
        self._values = [float(value) for value in values]

    def __truediv__(self, other):
        return _FreqVector([value / float(other) for value in self._values])

    def __len__(self):
        return len(self._values)

    def tolist(self):
        return list(self._values)


def test_normalize_frequency_safe_marks_copy_without_mutating_source():
    hazard = SimpleNamespace(frequency=_FreqVector([1.0, 2.0]))

    normalized = _normalize_frequency_safe(hazard, storm_years=10)

    assert normalized is not hazard
    assert hazard.frequency.tolist() == [1.0, 2.0]
    assert normalized.frequency.tolist() == [0.1, 0.2]
    assert sum(normalized.frequency.tolist()) == pytest.approx(0.3)
    assert getattr(normalized, "_sib_frequency_normalized", False) is True


def test_normalize_frequency_on_copy_preserves_relative_event_weights():
    hazard = SimpleNamespace(frequency=_FreqVector([0.5, 1.5, 3.0]))

    normalized = _normalize_frequency_on_copy(hazard, storm_years=10)

    assert normalized is not hazard
    assert hazard.frequency.tolist() == [0.5, 1.5, 3.0]
    assert normalized.frequency.tolist() == [0.05, 0.15, 0.3]
    assert getattr(normalized, "_sib_frequency_normalized", False) is True


def test_runoff_coeff_baseline_keys_and_values_are_stable():
    assert RUNOFF_COEFF_BY_INFRA_CLASS == {
        "elec_aerien": 0.10,
        "elec_souterrain": 0.30,
        "eau_reseau": 0.25,
        "eau_ouvrage": 0.35,
        "habitation": 0.20,
    }


def test_territory_grid_deg_baseline_for_overlay_readiness():
    assert TERRITORY_GRID_DEG == 0.2


def test_scientific_fallback_detection_flags_degraded_component_statuses():
    manifest_entry = {
        "phases": {
            "impacts": {
                "modeling": {
                    "strict_required_components": False,
                    "multi_hazard_component_status_by_hazard": {
                        "storm": {"wind": "complete", "rain": "fallback", "surge": "complete"}
                    },
                }
            }
        }
    }

    assert scientific_fallback_present(manifest_entry) is True


def test_publication_fallback_detection_reads_meta_modeling_flag():
    proxy_payload = {"meta": {"modeling": {"fallback": True}}}
    page_payload = {"meta": {"modeling": {"fallback": False}}}

    assert publication_fallback_present(proxy_payload, page_payload) is True
    assert publication_fallback_present(page_payload) is False


def test_default_valuation_count_reports_schema_gap_without_explicit_flag():
    payload = {"asset_results": [{"asset_id": "a"}, {"asset_id": "b"}]}

    assert infer_default_valuation_asset_count(payload) is None
    assert default_valuation_count_source(payload) == "not_exposed_in_current_payload"


def test_build_regression_rows_collects_matrix_fields():
    manifest_entry = {
        "phases": {
            "impacts": {
                "modeling": {
                    "strict_required_components": True,
                    "multi_hazard_component_status_by_hazard": {
                        "storm": {"wind": "complete", "rain": "complete", "surge": "complete"}
                    },
                }
            }
        }
    }
    complete_payload = {
        "portfolio_results": {
            "storm": {
                "eai_eur": 12.5,
                "pml_50_eur": 25.0,
                "pml_100_eur": 40.0,
                "max_event_loss_eur": 60.0,
            }
        },
        "asset_results": [{"asset_id": "asset-1"}],
    }
    proxy_payload = {
        "meta": {"modeling": {"fallback": True}},
        "hazards": {
            "storm": {
                "scenarios": {
                    "annual": {
                        "component_ratios": {
                            "wind": 0.8,
                            "rain": 0.19,
                            "surge": 0.01,
                            "landslide": 0.0,
                        }
                    }
                }
            }
        },
    }
    page_payload = {"meta": {"modeling": {"fallback": False}}}

    rows = build_regression_rows(
        territory="guadeloupe",
        manifest_entry=manifest_entry,
        complete_payload=complete_payload,
        proxy_payload=proxy_payload,
        page_payload=page_payload,
    )

    assert rows == [
        {
            "territory": "guadeloupe",
            "hazard": "storm",
            "eai_eur": 12.5,
            "pml_50_eur": 25.0,
            "pml_100_eur": 40.0,
            "max_event_loss_eur": 60.0,
            "percentile_99_loss_eur": 60.0,
            "default_valuation_asset_count": None,
            "default_valuation_count_source": "not_exposed_in_current_payload",
            "scientific_fallback_present": False,
            "publication_fallback_present": True,
            "page_analysis_fallback": False,
            "proxy_fallback": True,
            "component_share_wind": 0.8,
            "component_share_rain": 0.19,
            "component_share_surge": 0.01,
            "component_share_landslide": 0.0,
        }
    ]