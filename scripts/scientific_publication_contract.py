from __future__ import annotations

SCIENTIFIC_SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
RETURN_PERIOD_BY_SCENARIO = {
    "rp10": 10,
    "rp50": 50,
    "rp100": 100,
    "rp1000": 1000,
}
EVENT_SELECTION_BASIS = "global_portfolio_loss"

PUBLIC_SERVICE_KEYS = ("eau_aep", "eau_eu", "elec")
SERVICE_LAYER_TO_PUBLIC_KEY = {
    "eau_aep": "eau_aep",
    "eau_eu": "eau_eu",
    "elec_grid_0p1deg": "elec",
}

SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION = "scientific_web_summary_v4"
SCIENTIFIC_WEB_CONTRACT_VERSION = "scientific_web_contract_v4"

FORBIDDEN_SCIENTIFIC_SCENARIOS = frozenset({"annual", "p99", "event_max"})
FORBIDDEN_PUBLIC_SERVICE_KEYS = frozenset({"water_aep", "water_eu"})
