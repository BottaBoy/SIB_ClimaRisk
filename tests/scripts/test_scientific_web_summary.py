from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts.build_scientific_web_summary import build_scientific_web_summary
import scripts.build_scientific_web_summary as build_scientific_web_summary_module
from scripts.scientific_graph_postprocess import needs_strict_scientific_rebuild
from scripts.scientific_publication_contract import (
    EVENT_SELECTION_BASIS,
    SCIENTIFIC_SCENARIOS,
    SCIENTIFIC_WEB_CONTRACT_VERSION,
    SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
)


@pytest.fixture(autouse=True)
def _isolate_web_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    web_data_dir = tmp_path / "isolated-web-data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(build_scientific_web_summary_module, "WEB_DATA_DIR", web_data_dir)


def _damage_row(value: float) -> dict:
    return {
        "class_key": "eau_aep",
        "class_label": "Eau AEP",
        "storm": {
            "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
            "exposure_eur": 1000.0,
            "damage_eur": value,
            "direct_damage_eur": value,
            "indirect_damage_eur": 0.0,
            "damage_components_eur": {"wind": value, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
        },
        "storm_cmcc": {
            "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0},
            "exposure_eur": 1000.0,
            "damage_eur": value + 1.0,
            "direct_damage_eur": value + 1.0,
            "indirect_damage_eur": 0.0,
            "damage_components_eur": {"wind": value + 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
        },
    }


def _strict_graph_inputs() -> dict:
    values = {"rp10": 10.0, "rp50": 50.0, "rp100": 100.0, "rp1000": 1000.0}
    return {
        "source_of_truth": "complete_analysis",
        "event_selection_basis": EVENT_SELECTION_BASIS,
        "event_selection": {
            "basis": EVENT_SELECTION_BASIS,
            "return_period_by_scenario": {"rp10": 10, "rp50": 50, "rp100": 100, "rp1000": 1000},
            "event_indices_by_hazard": {
                "storm": {"rp10": 1, "rp50": 5, "rp100": 10, "rp1000": 100},
                "storm_cmcc": {"rp10": 2, "rp50": 6, "rp100": 11, "rp1000": 101},
            },
            "event_loss_eur_by_hazard": {
                "storm": {"rp10": 10.0, "rp50": 50.0, "rp100": 100.0, "rp1000": 1000.0},
                "storm_cmcc": {"rp10": 11.0, "rp50": 51.0, "rp100": 101.0, "rp1000": 1001.0},
            },
        },
        "scenarios": list(SCIENTIFIC_SCENARIOS),
        "state_damage_tables": {scenario: [_damage_row(value)] for scenario, value in values.items()},
        "damage_breakdown_by_scenario": {
            scenario: {
                "storm": [{"class_key": "eau_aep", "damage_eur": value, "exposure_eur": 1000.0}],
                "storm_cmcc": [{"class_key": "eau_aep", "damage_eur": value + 1.0, "exposure_eur": 1000.0}],
            }
            for scenario, value in values.items()
        },
        "social_impact_by_scenario": {
            scenario: {
                "storm": {"total_population_affected_any_network": value},
                "storm_cmcc": {"total_population_affected_any_network": value + 1.0},
            }
            for scenario, value in values.items()
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
        "meta": {"run_id": "20260701_071828", "requested_dynamic_max_tracks": 1500},
        "portfolio_results": {
            "storm": {"pml_10_eur": 10.0, "pml_50_eur": 50.0, "pml_100_eur": 100.0, "pml_1000_eur": 1000.0},
            "storm_cmcc": {"pml_10_eur": 11.0, "pml_50_eur": 51.0, "pml_100_eur": 101.0, "pml_1000_eur": 1001.0},
        },
        "scientific_graph_inputs": _strict_graph_inputs(),
    }


def _network_states_payload() -> dict:
    props = {
        "feature_id": "AEP_001",
        "layer_key": "eau_aep",
        "service_feature_id": "AEP_001",
        "zone_component_key": "AEP_001",
    }
    for scenario in SCIENTIFIC_SCENARIOS:
        props[f"state_{scenario}_storm"] = "S2"
        props[f"state_{scenario}_storm_cmcc"] = "S3"
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [-61.5, 16.2]}}],
    }


def test_build_scientific_web_summary_publishes_v4_contract_without_legacy_sources(tmp_path: Path) -> None:
    complete_path = tmp_path / "complete.json"
    network_states_path = tmp_path / "network-states.geojson"
    out_path = tmp_path / "summary.json"
    complete_path.write_text(json.dumps(_complete_payload()), encoding="utf-8")
    network_states_path.write_text(json.dumps(_network_states_payload()), encoding="utf-8")

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=complete_path,
        out_path=out_path,
        network_states_geojson_path=network_states_path,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["meta"]["schema_version"] == SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION
    assert payload["meta"]["contract_version"] == SCIENTIFIC_WEB_CONTRACT_VERSION
    assert payload["portfolio_summary"]["storm"] == {
        "rp10_eur": 10.0,
        "rp50_eur": 50.0,
        "rp100_eur": 100.0,
        "rp1000_eur": 1000.0,
    }
    assert payload["scientific_graph_inputs"] == json.loads(complete_path.read_text(encoding="utf-8"))["scientific_graph_inputs"]
    assert payload["scientific_graph_inputs"]["scenarios"] == list(SCIENTIFIC_SCENARIOS)
    assert "annual" not in payload["scientific_graph_inputs"]["state_damage_tables"]
    assert "p99" not in payload["scientific_graph_inputs"]["state_damage_tables"]
    assert payload["network_states"]["scenario_service_state_distribution"]["rp1000"]["storm"]["eau_aep"]["S2"] == 1
    assert "water_aep" not in json.dumps(payload)


def test_needs_strict_scientific_rebuild_detects_legacy_scenarios() -> None:
    payload = {
        "scientific_graph_inputs": {
            "source_of_truth": "complete_analysis",
            "scenarios": ["annual", "rp50", "rp100", "p99"],
            "state_damage_tables": {"annual": [], "rp50": [], "rp100": [], "p99": []},
            "damage_breakdown_by_scenario": {"annual": {"storm": [], "storm_cmcc": []}},
        }
    }

    assert needs_strict_scientific_rebuild(payload) is True


def test_build_scientific_web_summary_requires_explicit_repair_for_missing_v4_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete_path = tmp_path / "complete.json"
    network_states_path = tmp_path / "network-states.geojson"
    out_path = tmp_path / "summary.json"
    legacy_payload = _complete_payload()
    legacy_payload["scientific_graph_inputs"] = {
        "source_of_truth": "complete_analysis",
        "scenarios": ["rp50", "rp100"],
        "state_damage_tables": {},
        "damage_breakdown_by_scenario": {},
    }
    complete_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    network_states_path.write_text(json.dumps(_network_states_payload()), encoding="utf-8")
    called = {"value": False}

    def _fake_rebuild(*, territory: str, complete_analysis_path: Path, manifest_path=None):
        called["value"] = True
        payload = json.loads(complete_analysis_path.read_text(encoding="utf-8"))
        payload["scientific_graph_inputs"] = _strict_graph_inputs()
        complete_analysis_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload["scientific_graph_inputs"]

    monkeypatch.setattr(build_scientific_web_summary_module, "rebuild_scientific_graph_inputs", _fake_rebuild)

    with pytest.raises(RuntimeError, match="missing strict V4 scientific_graph_inputs"):
        build_scientific_web_summary(
            territory="guadeloupe",
            complete_analysis_path=complete_path,
            out_path=out_path,
            network_states_geojson_path=network_states_path,
        )
    assert called["value"] is False

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=complete_path,
        out_path=out_path,
        network_states_geojson_path=network_states_path,
        repair_legacy_scientific_inputs=True,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert called["value"] is True
    assert payload["scientific_graph_inputs"]["event_selection_basis"] == EVENT_SELECTION_BASIS


def test_build_scientific_web_summary_uses_pml_light_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete_path = tmp_path / "complete.json"
    network_states_path = tmp_path / "network-states.geojson"
    out_path = tmp_path / "summary.json"
    payload = _complete_payload()
    pml_inputs = _strict_graph_inputs()
    pml_inputs["schema_version"] = "pml_network_graph_inputs_v1"
    pml_inputs["method"] = "pml_calibrated_network_states"
    pml_inputs["approximation"] = True
    payload["scientific_graph_inputs"] = {
        "source_of_truth": "complete_analysis",
        "scenarios": ["rp50", "rp100"],
        "state_damage_tables": {},
        "damage_breakdown_by_scenario": {},
    }
    payload["pml_network_graph_inputs"] = pml_inputs
    complete_path.write_text(json.dumps(payload), encoding="utf-8")
    network_states_path.write_text(json.dumps(_network_states_payload()), encoding="utf-8")

    def _unexpected_rebuild(*, territory: str, complete_analysis_path: Path, manifest_path=None):
        raise AssertionError("strict scientific postprocess should not run when PML-light inputs are complete")

    monkeypatch.setattr(build_scientific_web_summary_module, "rebuild_scientific_graph_inputs", _unexpected_rebuild)

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=complete_path,
        out_path=out_path,
        network_states_geojson_path=network_states_path,
    )

    summary = json.loads(out_path.read_text(encoding="utf-8"))
    updated_complete = json.loads(complete_path.read_text(encoding="utf-8"))
    graph_inputs = summary["scientific_graph_inputs"]
    assert graph_inputs["scenarios"] == list(SCIENTIFIC_SCENARIOS)
    assert graph_inputs["source_method"] == "pml_calibrated_network_states"
    assert graph_inputs["source_schema_version"] == "pml_network_graph_inputs_v1"
    assert graph_inputs["approximation"] is True
    assert graph_inputs["state_damage_tables"]["rp1000"][0]["storm"]["damage_eur"] == 1000.0
    assert updated_complete["scientific_graph_inputs"] == graph_inputs


def test_build_scientific_web_summary_mirrors_v4_contract_to_mutable_web_complete_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_data_dir = tmp_path / "web" / "data"
    web_data_dir.mkdir(parents=True)
    monkeypatch.setattr(build_scientific_web_summary_module, "WEB_DATA_DIR", web_data_dir)

    archived_complete_path = tmp_path / "archive" / "guadeloupe-complete-analysis.json"
    archived_complete_path.parent.mkdir(parents=True)
    mutable_complete_path = web_data_dir / "guadeloupe-complete-analysis.json"
    network_states_path = tmp_path / "network-states.geojson"
    out_path = web_data_dir / "guadeloupe-scientific-web-summary.json"

    payload = _complete_payload()
    archived_complete_path.write_text(json.dumps(payload), encoding="utf-8")
    mutable_payload = _complete_payload()
    mutable_payload.pop("scientific_graph_inputs")
    mutable_complete_path.write_text(json.dumps(mutable_payload), encoding="utf-8")
    network_states_path.write_text(json.dumps(_network_states_payload()), encoding="utf-8")

    build_scientific_web_summary(
        territory="guadeloupe",
        complete_analysis_path=archived_complete_path,
        out_path=out_path,
        network_states_geojson_path=network_states_path,
    )

    mutable_updated = json.loads(mutable_complete_path.read_text(encoding="utf-8"))
    archived_updated = json.loads(archived_complete_path.read_text(encoding="utf-8"))
    assert mutable_updated["scientific_graph_inputs"] == archived_updated["scientific_graph_inputs"]
    assert mutable_updated["scientific_graph_inputs"]["scenarios"] == list(SCIENTIFIC_SCENARIOS)
