#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SOURCE_LABEL = "Comparateur de couts OFB (moyenne territoriale observee)"
VALUATION_VERSION = "ofb_2026_03_v1"

TERRITORY_BBOX = {
    "guadeloupe": {
        "lat_min": 15.5,
        "lat_max": 16.96,
        "lon_min": -62.48,
        "lon_max": -60.66,
    },
    "martinique": {
        "lat_min": 14.3,
        "lat_max": 15.1,
        "lon_min": -61.4,
        "lon_max": -60.7,
    },
}

INITIAL_VALUES: dict[str, dict[str, float]] = {
    "guadeloupe": {
        "aep_cana_eur_per_km": 280_000.0,
        "eu_cana_eur_per_km": 340_000.0,
        "eu_pr_eur_per_unit": 900_000.0,
        "eu_step_eur_per_unit": 6_000_000.0,
    },
    "martinique": {
        "aep_cana_eur_per_km": 280_000.0,
        "eu_cana_eur_per_km": 340_000.0,
        "eu_pr_eur_per_unit": 900_000.0,
        "eu_step_eur_per_unit": 6_000_000.0,
    },
}

NEW_VALUES_OFB: dict[str, dict[str, float]] = {
    "guadeloupe": {
        "aep_cana_eur_per_km": 776_386.0,
        "eu_cana_eur_per_km": 791_691.0,
        "eu_pr_eur_per_unit": 523_211.0,
        "eu_step_eur_per_unit": 7_777_800.0,
    },
    "martinique": {
        "aep_cana_eur_per_km": 653_445.0,
        "eu_cana_eur_per_km": 831_815.0,
        "eu_pr_eur_per_unit": 44_257.0,
        "eu_step_eur_per_unit": 7_923_344.0,
    },
}

NB_PRIX_COMPARES: dict[str, dict[str, int]] = {
    "guadeloupe": {
        "aep_cana": 24,
        "eu_cana": 10,
        "eu_pr": 6,
        "eu_step": 1,
    },
    "martinique": {
        "aep_cana": 16,
        "eu_cana": 6,
        "eu_pr": 1,
        "eu_step": 2,
    },
}

ELECTRIC_VALUES = {
    "elec_bt_aerien": 167_060.0,
    "elec_bt_souterrain": 1_336_480.0,
    "elec_hta_aerien": 249_299.0,
    "elec_hta_souterrain": 1_994_390.0,
}

AEP_OUVRAGE_VALUES = {
    "TRAIT": 3_500_000.0,
    "STPMP": 1_200_000.0,
    "CAP": 1_000_000.0,
    "CUV": 500_000.0,
    "__DEFAULT__": 800_000.0,
}


def _normalize_territory(territory: str | None) -> str:
    value = str(territory or "").strip().lower()
    aliases = {
        "guadeloupe": "guadeloupe",
        "gua": "guadeloupe",
        "gp": "guadeloupe",
        "martinique": "martinique",
        "mq": "martinique",
        "fallback_guadeloupe": "fallback_guadeloupe",
    }
    return aliases.get(value, "fallback_guadeloupe")


def detect_territory_bbox(lon: float, lat: float) -> str:
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError):
        return "fallback_guadeloupe"

    gua = TERRITORY_BBOX["guadeloupe"]
    if gua["lat_min"] <= lat_f <= gua["lat_max"] and gua["lon_min"] <= lon_f <= gua["lon_max"]:
        return "guadeloupe"

    mq = TERRITORY_BBOX["martinique"]
    if mq["lat_min"] <= lat_f <= mq["lat_max"] and mq["lon_min"] <= lon_f <= mq["lon_max"]:
        return "martinique"

    return "fallback_guadeloupe"


def detect_territory_from_centroids(centroids: Iterable[tuple[float, float]]) -> str:
    for lon, lat in centroids:
        candidate = detect_territory_bbox(lon, lat)
        if candidate in {"guadeloupe", "martinique"}:
            return candidate
    return "fallback_guadeloupe"


def _effective_territory(territory: str | None) -> str:
    normalized = _normalize_territory(territory)
    if normalized in {"guadeloupe", "martinique"}:
        return normalized
    return "guadeloupe"


def _outside_bbox_policy_label(territory_input: str, territory_effective: str) -> str:
    if territory_input == territory_effective and territory_effective in {"guadeloupe", "martinique"}:
        return "explicit_territory_input"
    return f"default_to_{territory_effective}"


def get_water_values(territory: str | None) -> dict[str, float]:
    key = _effective_territory(territory)
    values = NEW_VALUES_OFB[key]
    return {
        "eau_aep": float(values["aep_cana_eur_per_km"]),
        "eau_eu": float(values["eu_cana_eur_per_km"]),
        "eau_eu_pr": float(values["eu_pr_eur_per_unit"]),
        "eau_eu_step": float(values["eu_step_eur_per_unit"]),
    }


def get_elec_values() -> dict[str, float]:
    return dict(ELECTRIC_VALUES)


def get_network_values_per_km(territory: str | None) -> dict[str, float]:
    water = get_water_values(territory)
    elec = get_elec_values()
    return {
        "eau_aep": float(water["eau_aep"]),
        "eau_eu": float(water["eau_eu"]),
        "elec_bt_souterrain": float(elec["elec_bt_souterrain"]),
        "elec_bt_aerien": float(elec["elec_bt_aerien"]),
        "elec_hta_souterrain": float(elec["elec_hta_souterrain"]),
        "elec_hta_aerien": float(elec["elec_hta_aerien"]),
    }


def get_aep_ouvrage_values() -> dict[str, float]:
    return dict(AEP_OUVRAGE_VALUES)


def get_aep_ouvrage_value(ovrg_type: str | None) -> float:
    key = str(ovrg_type or "").strip().upper()
    values = get_aep_ouvrage_values()
    return float(values.get(key, values["__DEFAULT__"]))


def build_valuation_metadata(territory: str | None) -> dict[str, Any]:
    territory_input = _normalize_territory(territory)
    territory_effective = _effective_territory(territory_input)
    return {
        "source": SOURCE_LABEL,
        "valuation_version": VALUATION_VERSION,
        "territory_input": territory_input,
        "territory_effective": territory_effective,
        "initial_values": dict(INITIAL_VALUES[territory_effective]),
        "new_values": dict(NEW_VALUES_OFB[territory_effective]),
        "nb_prix_compares": dict(NB_PRIX_COMPARES[territory_effective]),
        "policy_outside_bbox": _outside_bbox_policy_label(territory_input, territory_effective),
    }
