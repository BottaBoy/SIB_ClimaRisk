#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SOURCE_LABEL = "Dossiers gestionnaires reseaux (profil partage Guadeloupe) + exceptions documentees"
VALUATION_VERSION = "network_dossiers_2026_05_v2_saint_barthelemy"
SAINT_BARTHELEMY_COST_MULTIPLIER = 1.5

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
    "saint-barthelemy": {
        "lat_min": 17.86,
        "lat_max": 17.98,
        "lon_min": -62.95,
        "lon_max": -62.78,
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
    "saint-barthelemy": {
        "aep_cana_eur_per_km": 280_000.0 * SAINT_BARTHELEMY_COST_MULTIPLIER,
        "eu_cana_eur_per_km": 340_000.0 * SAINT_BARTHELEMY_COST_MULTIPLIER,
        "eu_pr_eur_per_unit": 900_000.0 * SAINT_BARTHELEMY_COST_MULTIPLIER,
        "eu_step_eur_per_unit": 6_000_000.0 * SAINT_BARTHELEMY_COST_MULTIPLIER,
    },
}

AEP_PENDING_VALUES: dict[str, dict[str, float]] = {
    "guadeloupe": {
        "aep_cana_eur_per_km": 776_386.0,
    },
    "martinique": {
        "aep_cana_eur_per_km": 653_445.0,
    },
    "saint-barthelemy": {
        "aep_cana_eur_per_km": 776_386.0 * SAINT_BARTHELEMY_COST_MULTIPLIER,
    },
}

EU_DOSSIER_SHARED_VALUES = {
    # Mean of the documented EU network price points (EUR/ml) converted to EUR/km.
    "eu_cana_eur_per_km": 957_143.0,
    # Mean of the documented PR capacity brackets.
    "eu_pr_eur_per_unit": 397_636.0,
    # Mean plant total from the documented EUR/EH matrix using representative band midpoints.
    "eu_step_eur_per_unit": 8_785_714.0,
}

CURRENT_WATER_VALUES: dict[str, dict[str, float]] = {
    territory: {
        **values,
        **EU_DOSSIER_SHARED_VALUES,
    }
    for territory, values in AEP_PENDING_VALUES.items()
}
CURRENT_WATER_VALUES["saint-barthelemy"]["eu_cana_eur_per_km"] *= SAINT_BARTHELEMY_COST_MULTIPLIER
CURRENT_WATER_VALUES["saint-barthelemy"]["eu_pr_eur_per_unit"] *= SAINT_BARTHELEMY_COST_MULTIPLIER
CURRENT_WATER_VALUES["saint-barthelemy"]["eu_step_eur_per_unit"] *= SAINT_BARTHELEMY_COST_MULTIPLIER

DOSSIER_PRICE_POINT_COUNTS = {
    "eu_cana": 7,
    "eu_pr": 11,
    "eu_step": 14,
}

NB_PRIX_COMPARES: dict[str, dict[str, int]] = {
    "guadeloupe": {
        "aep_cana": 24,
        **DOSSIER_PRICE_POINT_COUNTS,
    },
    "martinique": {
        "aep_cana": 16,
        **DOSSIER_PRICE_POINT_COUNTS,
    },
    "saint-barthelemy": {
        "aep_cana": 24,
        **DOSSIER_PRICE_POINT_COUNTS,
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

CLASS_COVERAGE: dict[str, dict[str, str]] = {
    "eau_aep": {
        "source": "ofb_territorial_average",
        "status": "temporary_exception_pending_aep_transcription",
        "aggregation": "territory_specific_existing_value",
    },
    "eau_eu": {
        "source": "guadeloupe_network_manager_dossier",
        "status": "shared_default_profile",
        "aggregation": "mean_of_documented_network_price_points",
    },
    "eau_eu_pr": {
        "source": "guadeloupe_network_manager_dossier",
        "status": "shared_default_profile",
        "aggregation": "mean_of_documented_capacity_brackets",
    },
    "eau_eu_step": {
        "source": "guadeloupe_network_manager_dossier",
        "status": "shared_default_profile",
        "aggregation": "mean_of_documented_eur_per_eh_matrix_with_band_midpoints",
    },
    "elec_all": {
        "source": "d3_icf_2002",
        "status": "unchanged_outside_water_dossier_scope",
        "aggregation": "unchanged_existing_value",
    },
    "aep_ouvrages": {
        "source": "sib_internal_assumption",
        "status": "temporary_exception_pending_aep_transcription",
        "aggregation": "fixed_value_by_ouvrage_type",
    },
}


def _normalize_territory(territory: str | None) -> str:
    value = str(territory or "").strip().lower()
    aliases = {
        "guadeloupe": "guadeloupe",
        "gua": "guadeloupe",
        "gp": "guadeloupe",
        "martinique": "martinique",
        "mq": "martinique",
        "mtq": "martinique",
        "mar": "martinique",
        "saint-barthelemy": "saint-barthelemy",
        "saint_barthelemy": "saint-barthelemy",
        "saintbarth": "saint-barthelemy",
        "saint_barth": "saint-barthelemy",
        "blm": "saint-barthelemy",
        "stb": "saint-barthelemy",
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

    stb = TERRITORY_BBOX["saint-barthelemy"]
    if stb["lat_min"] <= lat_f <= stb["lat_max"] and stb["lon_min"] <= lon_f <= stb["lon_max"]:
        return "saint-barthelemy"

    return "fallback_guadeloupe"


def detect_territory_from_centroids(centroids: Iterable[tuple[float, float]]) -> str:
    for lon, lat in centroids:
        candidate = detect_territory_bbox(lon, lat)
        if candidate in {"guadeloupe", "martinique", "saint-barthelemy"}:
            return candidate
    return "fallback_guadeloupe"


def _effective_territory(territory: str | None) -> str:
    normalized = _normalize_territory(territory)
    if normalized in {"guadeloupe", "martinique", "saint-barthelemy"}:
        return normalized
    return "guadeloupe"


def _outside_bbox_policy_label(territory_input: str, territory_effective: str) -> str:
    if territory_input == territory_effective and territory_effective in {"guadeloupe", "martinique", "saint-barthelemy"}:
        return "explicit_territory_input"
    return f"default_to_{territory_effective}"


def _water_values_for_territory(territory_key: str) -> dict[str, float]:
    return dict(CURRENT_WATER_VALUES[territory_key])


def _class_coverage_for_territory(territory_key: str) -> dict[str, dict[str, str]]:
    coverage = {key: dict(value) for key, value in CLASS_COVERAGE.items()}
    coverage["eau_aep"]["reference_territory"] = territory_key
    coverage["eau_eu"]["reference_territory"] = "guadeloupe"
    coverage["eau_eu_pr"]["reference_territory"] = "guadeloupe"
    coverage["eau_eu_step"]["reference_territory"] = "guadeloupe"
    coverage["elec_all"]["reference_territory"] = "shared_existing_profile"
    coverage["aep_ouvrages"]["reference_territory"] = territory_key
    return coverage


def get_water_values(territory: str | None) -> dict[str, float]:
    key = _effective_territory(territory)
    values = _water_values_for_territory(key)
    return {
        "eau_aep": float(values["aep_cana_eur_per_km"]),
        "eau_eu": float(values["eu_cana_eur_per_km"]),
        "eau_eu_pr": float(values["eu_pr_eur_per_unit"]),
        "eau_eu_step": float(values["eu_step_eur_per_unit"]),
    }


def get_elec_values() -> dict[str, float]:
    return dict(ELECTRIC_VALUES)


def get_elec_values_for_territory(territory: str | None) -> dict[str, float]:
    territory_key = _effective_territory(territory)
    multiplier = SAINT_BARTHELEMY_COST_MULTIPLIER if territory_key == "saint-barthelemy" else 1.0
    return {key: float(value) * multiplier for key, value in ELECTRIC_VALUES.items()}


def get_network_values_per_km(territory: str | None) -> dict[str, float]:
    water = get_water_values(territory)
    elec = get_elec_values_for_territory(territory)
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
    return get_aep_ouvrage_value_for_territory(None, ovrg_type)


def get_aep_ouvrage_value_for_territory(territory: str | None, ovrg_type: str | None) -> float:
    key = str(ovrg_type or "").strip().upper()
    values = get_aep_ouvrage_values()
    base_value = float(values.get(key, values["__DEFAULT__"]))
    territory_key = _effective_territory(territory)
    if territory_key == "saint-barthelemy":
        return float(base_value * SAINT_BARTHELEMY_COST_MULTIPLIER)
    return base_value


def build_valuation_metadata(territory: str | None) -> dict[str, Any]:
    territory_input = _normalize_territory(territory)
    territory_effective = _effective_territory(territory_input)
    water_values = _water_values_for_territory(territory_effective)
    return {
        "source": SOURCE_LABEL,
        "valuation_version": VALUATION_VERSION,
        "territory_input": territory_input,
        "territory_effective": territory_effective,
        "reference_profile_territory": "guadeloupe",
        "territory_cost_multiplier": SAINT_BARTHELEMY_COST_MULTIPLIER if territory_effective == "saint-barthelemy" else 1.0,
        "initial_values": dict(INITIAL_VALUES[territory_effective]),
        "new_values": dict(water_values),
        "nb_prix_compares": dict(NB_PRIX_COMPARES[territory_effective]),
        "class_coverage": _class_coverage_for_territory(territory_effective),
        "policy_outside_bbox": _outside_bbox_policy_label(territory_input, territory_effective),
        "notes": (
            ["Saint-Barthelemy uses the Guadeloupe reference valuation profile with a +50% cost uplift."]
            if territory_effective == "saint-barthelemy"
            else []
        ),
    }
