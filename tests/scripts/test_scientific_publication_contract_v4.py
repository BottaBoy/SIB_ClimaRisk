from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import run_web_artifacts
from scripts.scientific_publication_contract import (
    EVENT_SELECTION_BASIS,
    SCIENTIFIC_SCENARIOS,
    SCIENTIFIC_WEB_CONTRACT_VERSION,
    SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
)


def _graph_inputs() -> dict:
    return {
        "source_of_truth": "complete_analysis",
        "event_selection_basis": EVENT_SELECTION_BASIS,
        "scenarios": list(SCIENTIFIC_SCENARIOS),
        "state_damage_tables": {scenario: [{"class_key": "eau_aep"}] for scenario in SCIENTIFIC_SCENARIOS},
        "damage_breakdown_by_scenario": {
            scenario: {"storm": [{"class_key": "eau_aep"}], "storm_cmcc": [{"class_key": "eau_aep"}]}
            for scenario in SCIENTIFIC_SCENARIOS
        },
        "social_impact_by_scenario": {
            scenario: {"storm": {"total_population_affected_any_network": 1.0}, "storm_cmcc": {"total_population_affected_any_network": 1.0}}
            for scenario in SCIENTIFIC_SCENARIOS
        },
        "scenario_availability": {
            scenario: {
                "state_damage_tables": True,
                "damage_breakdown_by_scenario": True,
                "social_impact_by_scenario": True,
                "network_states": True,
            }
            for scenario in SCIENTIFIC_SCENARIOS
        },
    }


def _complete_payload() -> dict:
    return {
        "portfolio_results": {
            "storm": {"pml_10_eur": 10.0, "pml_50_eur": 50.0, "pml_100_eur": 100.0, "pml_1000_eur": 1000.0},
            "storm_cmcc": {"pml_10_eur": 11.0, "pml_50_eur": 51.0, "pml_100_eur": 101.0, "pml_1000_eur": 1001.0},
        },
        "scientific_graph_inputs": _graph_inputs(),
    }


def _summary_payload() -> dict:
    graph_inputs = _graph_inputs()
    return {
        "meta": {
            "territory": "guadeloupe",
            "run_id": "20260701_071828",
            "scientific_source": True,
            "schema_version": SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
            "contract_version": SCIENTIFIC_WEB_CONTRACT_VERSION,
            "source_of_truth": "scientific_web_summary",
            "aggregation_unit": "scientific_service_unit",
        },
        "portfolio_summary": {
            "storm": {"rp10_eur": 10.0, "rp50_eur": 50.0, "rp100_eur": 100.0, "rp1000_eur": 1000.0},
            "storm_cmcc": {"rp10_eur": 11.0, "rp50_eur": 51.0, "rp100_eur": 101.0, "rp1000_eur": 1001.0},
        },
        "scientific_graph_inputs": graph_inputs,
        "network_states": {
            "scenario_availability": {scenario: True for scenario in SCIENTIFIC_SCENARIOS},
            "scenario_service_state_distribution": {},
        },
        "frontend": {
            "impact": {
                "state_damage_tables": graph_inputs["state_damage_tables"],
                "damage_breakdown_by_scenario": graph_inputs["damage_breakdown_by_scenario"],
            },
            "scenario_availability": {
                scenario: {"damage_tables": True, "social_impact": True, "network_states": True}
                for scenario in SCIENTIFIC_SCENARIOS
            },
        },
    }


def test_scientific_web_summary_alignment_accepts_v4_contract() -> None:
    validation = run_web_artifacts._validate_scientific_web_summary_alignment(
        run_id="20260701_071828",
        territory="guadeloupe",
        complete_payload=_complete_payload(),
        summary_payload=_summary_payload(),
    )

    assert validation["hazards"]["storm"]["rp1000_eur"] == pytest.approx(1000.0)
    assert validation["scientific_graph_inputs"]["rp1000"]["table_rows"] == 1


def test_scientific_web_summary_alignment_rejects_legacy_service_keys() -> None:
    summary = _summary_payload()
    summary["network_states"]["scenario_service_state_distribution"] = {
        "rp100": {"storm": {"water_aep": {"S0": 1, "S1": 0, "S2": 0, "S3": 0, "total_units": 1}}}
    }

    with pytest.raises(RuntimeError, match="non-canonical service keys"):
        run_web_artifacts._validate_scientific_web_summary_alignment(
            run_id="20260701_071828",
            territory="guadeloupe",
            complete_payload=_complete_payload(),
            summary_payload=summary,
        )


def test_scientific_web_summary_alignment_rejects_legacy_scenarios() -> None:
    complete = _complete_payload()
    summary = _summary_payload()
    complete["scientific_graph_inputs"] = copy.deepcopy(complete["scientific_graph_inputs"])
    complete["scientific_graph_inputs"]["state_damage_tables"]["p99"] = []

    with pytest.raises(RuntimeError, match="forbidden scenarios"):
        run_web_artifacts._validate_scientific_web_summary_alignment(
            run_id="20260701_071828",
            territory="guadeloupe",
            complete_payload=complete,
            summary_payload=summary,
        )
