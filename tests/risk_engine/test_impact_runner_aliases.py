from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.impact_runner import _attach_service_state_aliases


def test_attach_service_state_aliases_adds_explicit_population_projection_keys() -> None:
    payload = {
        "network_states_native": {"storm": {"elec": {"cell-1": {"state": "S1"}}}},
        "network_states_projected": {"storm": {"cell-1": {"elec": "S1"}}},
        "network_states_projected_coverage": {"storm": {"cell-1": {"elec": True}}},
    }

    enriched = _attach_service_state_aliases(payload)

    assert enriched["native_service_states"] is payload["network_states_native"]
    assert enriched["population_projected_service_states"] is payload["network_states_projected"]
    assert (
        enriched["population_projected_service_states_coverage"]
        is payload["network_states_projected_coverage"]
    )


def test_attach_service_state_aliases_skips_missing_network_state_sections() -> None:
    payload = {"foo": "bar"}

    enriched = _attach_service_state_aliases(payload)

    assert enriched == {"foo": "bar"}
