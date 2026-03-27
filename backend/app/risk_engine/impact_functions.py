from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional during scaffolding
    np = None  # type: ignore


@dataclass(frozen=True)
class EberenzTCParams:
    v_thresh: float = 25.7
    v_half: float = 59.6
    intensity_max: int = 300
    intensity_step: int = 1


DEFAULT_EBERENZ_IMPF_ID = 2
D2_CURVE_FILE = Path(__file__).resolve().parent / "data" / "tc_vulnerability_curves_sib_v1.json"
D2_IMPF_ID_BY_CODE = {
    "W3.10": 310,
    "W3.14": 314,
    "W16.1": 316,
    "W19.1": 319,
    "W21.2": 212,
    "W21.4": 214,
    "W21.5": 215,
    "W21.10": 2110,
}

D2_MODELED_INFRA_BY_CODE = {
    "W3.10": {
        "type": "Power tower",
        "characteristics": "Design speed 160 km/h, urban terrain",
    },
    "W3.14": {
        "type": "Power tower",
        "characteristics": "Design speed 200 km/h, urban terrain",
    },
    "W16.1": {
        "type": "Transmission and distribution pipelines",
        "characteristics": "Buried pipelines",
    },
    "W19.1": {
        "type": "Sewers & interceptors",
        "characteristics": "Buried pipelines",
    },
    "W21.2": {
        "type": "School",
        "characteristics": "Building design: BLSB1",
    },
    "W21.4": {
        "type": "School",
        "characteristics": "Building design: DECS std.",
    },
    "W21.5": {
        "type": "School",
        "characteristics": "Building design: DepEd STD",
    },
    "W21.10": {
        "type": "School",
        "characteristics": "Wooden roof structure",
    },
}

EBERENZ_MODELED_INFRA = {
    "type": "Caribbean buildings (generic)",
    "characteristics": "TC vulnerability model (Eberenz et al., 2021)",
}

# Normalized (lower-case) asset_type mapping used in SIB work.
ASSET_TYPE_TO_CURVE_CODE = {
    "elec_bt_aerien": "W3.10",
    "elec_hta_aerien": "W3.14",
    "elec_bt_souterrain": "W16.1",
    "elec_hta_souterrain": "W16.1",
    "eau_aep_cana": "W16.1",
    "eau_eu_cana": "W19.1",
    # User request: keep Eberenz for this infrastructure.
    "eau_eu_pr": "EBERENZ_2021_TC",
    "eau_eu_step": "W21.2",
    "eau_aep_ouvrage_trait": "W21.2",
    "eau_aep_ouvrage_stpmp": "W21.4",
    "eau_aep_ouvrage_cap": "W21.10",
    "eau_aep_ouvrage_cuv": "W21.5",
    "eau_aep_ouvrage_ouveb": "W21.5",
    "eau_aep_ouvrage_na": "W21.5",
}

_CURVE_CATALOG_CACHE: dict[int, dict[str, Any]] | None = None


def vulnerability_function(v: float, v_thresh: float, v_half: float) -> float:
    """Eberenz-style tropical cyclone damage ratio curve (0..1)."""
    if v <= v_thresh:
        return 0.0
    if v_half <= v_thresh:
        raise ValueError("v_half must be greater than v_thresh")
    v_n = (v - v_thresh) / (v_half - v_thresh)
    ratio = (v_n ** 3) / (1.0 + v_n ** 3)
    return max(0.0, min(1.0, ratio))


def build_eberenz_curve(params: EberenzTCParams | None = None) -> dict[str, list[float]]:
    p = params or EberenzTCParams()
    intensities = list(range(0, p.intensity_max + 1, p.intensity_step))
    mdd = [vulnerability_function(float(v), p.v_thresh, p.v_half) for v in intensities]
    paa = [1.0 for _ in intensities]
    return {
        "name": "Eberenz_2021_TC",
        "haz_type": "TC",
        "intensity_unit": "m/s",
        "intensity": [float(v) for v in intensities],
        "mdd": mdd,
        "paa": paa,
        "params": {
            "v_thresh": p.v_thresh,
            "v_half": p.v_half,
        },
    }


def _normalize_asset_type(value: str | None) -> str:
    return str(value or "").strip().lower()


def _load_d2_curves() -> dict[str, Any]:
    if not D2_CURVE_FILE.exists():
        return {}
    try:
        raw = json.loads(D2_CURVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    curves = raw.get("curves")
    if not isinstance(curves, dict):
        return {}
    return curves


def _build_curve_catalog() -> dict[int, dict[str, Any]]:
    eberenz = build_eberenz_curve()
    catalog: dict[int, dict[str, Any]] = {
        DEFAULT_EBERENZ_IMPF_ID: {
            "impf_id": DEFAULT_EBERENZ_IMPF_ID,
            "code": "EBERENZ_2021_TC",
            "name": "Eberenz Caraibes Impact Function",
            "source": "Eberenz et al. (2021)",
            "geography": "Caribbean (generalized)",
            "haz_type": "TC",
            "intensity_unit": str(eberenz["intensity_unit"]),
            "intensity": [float(v) for v in eberenz["intensity"]],
            "mdd": [float(v) for v in eberenz["mdd"]],
            "paa": [1.0 for _ in eberenz["intensity"]],
            "modeled_infrastructure_type": str(EBERENZ_MODELED_INFRA["type"]),
            "modeled_infrastructure_characteristics": str(EBERENZ_MODELED_INFRA["characteristics"]),
            "uncertainty_lower": None,
            "uncertainty_upper": None,
        }
    }

    d2_curves = _load_d2_curves()
    for code, impf_id in D2_IMPF_ID_BY_CODE.items():
        curve = d2_curves.get(code)
        if not isinstance(curve, dict):
            continue
        intensity = [float(v) for v in list(curve.get("intensity") or [])]
        mdd = [float(v) for v in list(curve.get("mdd") or [])]
        if not intensity or not mdd or len(intensity) != len(mdd):
            continue
        modeled = D2_MODELED_INFRA_BY_CODE.get(str(code), {})
        catalog[int(impf_id)] = {
            "impf_id": int(impf_id),
            "code": str(code),
            "name": str(curve.get("name") or f"D2_{code}"),
            "source": str(curve.get("source") or "Unknown"),
            "geography": str(curve.get("geography") or "Unknown"),
            "haz_type": "TC",
            "intensity_unit": str(curve.get("intensity_unit") or "m/s"),
            "intensity": intensity,
            "mdd": mdd,
            "paa": [1.0 for _ in intensity],
            "modeled_infrastructure_type": str(modeled.get("type") or "Unknown"),
            "modeled_infrastructure_characteristics": str(modeled.get("characteristics") or "N/A"),
            "uncertainty_lower": curve.get("uncertainty_lower"),
            "uncertainty_upper": curve.get("uncertainty_upper"),
        }
    return catalog


def get_tc_curve_catalog() -> dict[int, dict[str, Any]]:
    global _CURVE_CATALOG_CACHE
    if _CURVE_CATALOG_CACHE is None:
        _CURVE_CATALOG_CACHE = _build_curve_catalog()
    return _CURVE_CATALOG_CACHE


def resolve_tc_impact_func_id(asset_type: str | None) -> int:
    asset = _normalize_asset_type(asset_type)
    code = ASSET_TYPE_TO_CURVE_CODE.get(asset, "EBERENZ_2021_TC")
    if code == "EBERENZ_2021_TC":
        return DEFAULT_EBERENZ_IMPF_ID
    return int(D2_IMPF_ID_BY_CODE.get(code, DEFAULT_EBERENZ_IMPF_ID))


def get_tc_vulnerability_payload() -> dict[str, Any]:
    catalog = get_tc_curve_catalog()
    asset_types_by_code: dict[str, list[str]] = {}
    for asset_type, code in ASSET_TYPE_TO_CURVE_CODE.items():
        asset_types_by_code.setdefault(str(code), []).append(str(asset_type))
    for code in asset_types_by_code:
        asset_types_by_code[code] = sorted(asset_types_by_code[code])

    curves = []
    for curve in sorted(catalog.values(), key=lambda item: int(item.get("impf_id", 0))):
        curve_item = dict(curve)
        curve_code = str(curve_item.get("code") or "")
        curve_item["sib_asset_types"] = list(asset_types_by_code.get(curve_code, []))
        curves.append(curve_item)
    explicit_mapping = {}
    for asset_type, code in ASSET_TYPE_TO_CURVE_CODE.items():
        if code == "EBERENZ_2021_TC":
            impf_id = DEFAULT_EBERENZ_IMPF_ID
        else:
            impf_id = int(D2_IMPF_ID_BY_CODE.get(code, DEFAULT_EBERENZ_IMPF_ID))
        explicit_mapping[asset_type] = {"code": code, "impf_id": impf_id}
    return {
        "profile": "sib_tc_multicurve_v1",
        "haz_type": "TC",
        "intensity_unit": "m/s",
        "explicit_asset_type_mapping": explicit_mapping,
        "default_curve": {"code": "EBERENZ_2021_TC", "impf_id": DEFAULT_EBERENZ_IMPF_ID},
        "curves": curves,
    }


def _build_climada_impact_func(curve: dict[str, Any]) -> object | None:
    if np is None:
        return None
    try:
        from climada.entity.impact_funcs.base import ImpactFunc  # type: ignore
    except Exception:
        return None

    impf = ImpactFunc()
    impf.id = int(curve["impf_id"])
    impf.haz_type = str(curve.get("haz_type") or "TC")
    impf.name = str(curve.get("name") or f"TC Impact Function {impf.id}")
    impf.intensity = np.array(list(curve.get("intensity") or []), dtype=float)
    impf.mdd = np.array(list(curve.get("mdd") or []), dtype=float)
    impf.paa = np.array(list(curve.get("paa") or []), dtype=float)
    impf.intensity_unit = str(curve.get("intensity_unit") or "m/s")
    try:
        impf.check()
    except Exception:
        return None
    return impf


def try_build_climada_impact_func() -> object | None:
    """Create a CLIMADA ImpactFunc object when CLIMADA is available.

    The production backend should use this instead of notebook-only dummy/example curves.
    """
    curve = get_tc_curve_catalog().get(DEFAULT_EBERENZ_IMPF_ID)
    if not curve:
        return None
    return _build_climada_impact_func(curve)


def try_build_climada_impact_funcs() -> list[object] | None:
    catalog = get_tc_curve_catalog()
    if not catalog:
        return None
    funcs: list[object] = []
    for impf_id in sorted(catalog.keys()):
        impf = _build_climada_impact_func(catalog[impf_id])
        if impf is not None:
            funcs.append(impf)
    if not funcs:
        return None
    return funcs
