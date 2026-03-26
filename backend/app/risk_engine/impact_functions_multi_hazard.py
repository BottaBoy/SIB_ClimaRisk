from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

from .errors import DependencyMissingError


SURGE_IMPF_ID_BASE = 4100
RAIN_IMPF_ID_BASE = 5100
DEFAULT_FLOOD_CURVE_CODE = "F17.5"

# Detailed V1 mapping (chosen defaults, documented in methodology note).
FLOOD_ASSET_TYPE_TO_CURVE_CODE = {
    "elec_bt_aerien": "F6.2",
    "elec_hta_aerien": "F6.2",
    "elec_bt_souterrain": "F6.1",
    "elec_hta_souterrain": "F6.1",
    "eau_aep_cana": "F16.3",
    "eau_eu_cana": "F19.3",
    "eau_eu_pr": "F20.3",
    "eau_eu_step": "F18.4",
    "eau_aep_ouvrage_trait": "F14.4",
    "eau_aep_ouvrage_stpmp": "F17.4",
    "eau_aep_ouvrage_cap": "F15.1",
    "eau_aep_ouvrage_cuv": "F13.1",
    "eau_aep_ouvrage_ouveb": "F13.1",
    "eau_aep_ouvrage_na": "F14.4",
}

# Rainfall-to-depth proxy coefficients (dimensionless).
RUNOFF_COEFF_BY_INFRA_CLASS = {
    "elec_aerien": 0.10,
    "elec_souterrain": 0.30,
    "eau_reseau": 0.25,
    "eau_ouvrage": 0.35,
    "habitation": 0.20,
}

_FLOOD_CURVE_CACHE: dict[str, dict[str, Any]] = {}
_MODEL_CACHE: dict[tuple[str, str, str], "MultiHazardImpactModel"] = {}


@dataclass(frozen=True)
class MultiHazardImpactModel:
    surge_funcs: list[Any]
    rain_funcs: list[Any]
    surge_impf_by_asset_type: dict[str, int]
    rain_impf_by_asset_type: dict[str, int]
    flood_curve_file: Path
    surge_haz_type: str
    rain_haz_type: str
    mapping_info: dict[str, Any]


def _normalize_asset_type(asset_type: str | None) -> str:
    return str(asset_type or "").strip().lower()


def _infer_infra_class_from_asset_type(asset_type: str | None) -> str:
    asset = _normalize_asset_type(asset_type)
    if asset.startswith("elec_"):
        if "souterrain" in asset or "underground" in asset:
            return "elec_souterrain"
        return "elec_aerien"
    if asset.startswith("eau_"):
        if asset.endswith("_cana"):
            return "eau_reseau"
        return "eau_ouvrage"
    return "habitation"


def _safe_text(value: Any, default: str = "") -> str:
    txt = str(value or "").strip()
    if not txt or txt.lower() == "nan":
        return default
    return txt


def _load_flood_depth_curves(curve_file: Path) -> dict[str, dict[str, Any]]:
    cache_key = str(curve_file.resolve(strict=False))
    cached = _FLOOD_CURVE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("pandas/numpy are required to load D2 flood curves") from exc

    if not curve_file.exists():
        raise FileNotFoundError(f"Missing D2 flood curve file: {curve_file}")

    df = pd.read_excel(curve_file, sheet_name="F_Vuln_Depth", header=None)
    if df.shape[0] < 8 or df.shape[1] < 3:
        raise ValueError(f"Invalid F_Vuln_Depth sheet shape in {curve_file}: {df.shape}")

    id_row = df.iloc[0, :].tolist()
    depth_vals = pd.to_numeric(df.iloc[5:, 0], errors="coerce").to_numpy(dtype=float)

    curves: dict[str, dict[str, Any]] = {}
    for col_idx in range(1, len(id_row)):
        raw_id = str(id_row[col_idx] or "").strip()
        if not re.match(r"^F\d+(\.\d+)?[a-zA-Z]?$", raw_id):
            continue
        mdd_vals = pd.to_numeric(df.iloc[5:, col_idx], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(depth_vals) & np.isfinite(mdd_vals)
        if not mask.any():
            continue
        depth = np.asarray(depth_vals[mask], dtype=float)
        mdd = np.asarray(mdd_vals[mask], dtype=float)
        if depth.size == 0:
            continue
        order = np.argsort(depth)
        depth = depth[order]
        mdd = mdd[order]
        # Keep monotonic depth axis and clamp MDD to [0,1].
        uniq_depth, uniq_idx = np.unique(depth, return_index=True)
        uniq_mdd = np.clip(mdd[uniq_idx], 0.0, 1.0)
        if uniq_depth.size < 2:
            continue
        curves[raw_id] = {
            "code": raw_id,
            "depth_m": uniq_depth.astype(float),
            "mdd": uniq_mdd.astype(float),
            "intensity_unit": "m",
            "modeled_infrastructure_type": _safe_text(df.iat[1, col_idx], "Unknown"),
            "modeled_infrastructure_characteristics": _safe_text(df.iat[2, col_idx], "N/A"),
        }

    if DEFAULT_FLOOD_CURVE_CODE not in curves:
        raise ValueError(
            f"Default flood curve {DEFAULT_FLOOD_CURVE_CODE} was not found in {curve_file}#F_Vuln_Depth"
        )

    _FLOOD_CURVE_CACHE[cache_key] = curves
    return curves


def _build_climada_impact_func(
    *,
    impf_id: int,
    haz_type: str,
    name: str,
    intensity: Any,
    mdd: Any,
    intensity_unit: str,
) -> Any:
    try:
        import numpy as np  # type: ignore
        from climada.entity.impact_funcs.base import ImpactFunc  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("CLIMADA ImpactFunc runtime is required") from exc

    impf = ImpactFunc()
    impf.id = int(impf_id)
    impf.haz_type = str(haz_type)
    impf.name = str(name)
    impf.intensity = np.asarray(intensity, dtype=float)
    impf.mdd = np.clip(np.asarray(mdd, dtype=float), 0.0, 1.0)
    impf.paa = np.ones_like(impf.intensity, dtype=float)
    impf.intensity_unit = str(intensity_unit)
    impf.check()
    return impf


def build_multi_hazard_impact_model(
    *,
    surge_haz_type: str,
    rain_haz_type: str,
    flood_curve_file: Path,
) -> MultiHazardImpactModel:
    key = (
        str(surge_haz_type or "").strip(),
        str(rain_haz_type or "").strip(),
        str(flood_curve_file.resolve(strict=False)),
    )
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    curves = _load_flood_depth_curves(flood_curve_file)
    used_codes = sorted(
        {DEFAULT_FLOOD_CURVE_CODE, *[str(v) for v in FLOOD_ASSET_TYPE_TO_CURVE_CODE.values() if str(v) in curves]}
    )

    surge_funcs: list[Any] = []
    rain_funcs: list[Any] = []
    surge_impf_id_by_code: dict[str, int] = {}
    rain_impf_id_by_code: dict[str, int] = {}

    for idx, code in enumerate(used_codes, start=1):
        curve = curves[code]
        surge_impf_id = SURGE_IMPF_ID_BASE + idx
        rain_impf_id = RAIN_IMPF_ID_BASE + idx
        surge_impf_id_by_code[code] = surge_impf_id
        rain_impf_id_by_code[code] = rain_impf_id

        surge_funcs.append(
            _build_climada_impact_func(
                impf_id=surge_impf_id,
                haz_type=surge_haz_type,
                name=f"SIB Flood Depth Curve {code}",
                intensity=curve["depth_m"],
                mdd=curve["mdd"],
                intensity_unit="m",
            )
        )

        # Rain proxy curves are derived from depth curves:
        # equivalent_depth_m = runoff_coeff * rain_mm / 1000
        # rain_mm = depth_m * 1000 / runoff_coeff
        # We encode one baseline curve (coeff=0.25) and per-asset scaling via ID resolver below.
        base_coeff = 0.25
        rain_intensity_mm = (curve["depth_m"] * 1000.0) / base_coeff
        rain_funcs.append(
            _build_climada_impact_func(
                impf_id=rain_impf_id,
                haz_type=rain_haz_type,
                name=f"SIB Rain Proxy Curve {code}",
                intensity=rain_intensity_mm,
                mdd=curve["mdd"],
                intensity_unit="mm_proxy",
            )
        )

    def code_for_asset(asset_type: str | None) -> str:
        asset = _normalize_asset_type(asset_type)
        code = FLOOD_ASSET_TYPE_TO_CURVE_CODE.get(asset, DEFAULT_FLOOD_CURVE_CODE)
        return code if code in surge_impf_id_by_code else DEFAULT_FLOOD_CURVE_CODE

    surge_impf_by_asset_type: dict[str, int] = {}
    rain_impf_by_asset_type: dict[str, int] = {}
    for asset in {DEFAULT_FLOOD_CURVE_CODE, *FLOOD_ASSET_TYPE_TO_CURVE_CODE.keys()}:
        if asset == DEFAULT_FLOOD_CURVE_CODE:
            continue
        c = code_for_asset(asset)
        surge_impf_by_asset_type[str(asset)] = int(surge_impf_id_by_code[c])
        rain_impf_by_asset_type[str(asset)] = int(rain_impf_id_by_code[c])

    model = MultiHazardImpactModel(
        surge_funcs=surge_funcs,
        rain_funcs=rain_funcs,
        surge_impf_by_asset_type=surge_impf_by_asset_type,
        rain_impf_by_asset_type=rain_impf_by_asset_type,
        flood_curve_file=flood_curve_file,
        surge_haz_type=str(surge_haz_type),
        rain_haz_type=str(rain_haz_type),
        mapping_info={
            "default_curve_code": DEFAULT_FLOOD_CURVE_CODE,
            "curve_codes_used": used_codes,
            "asset_type_to_curve_code": dict(FLOOD_ASSET_TYPE_TO_CURVE_CODE),
            "runoff_coeff_by_infra_class": dict(RUNOFF_COEFF_BY_INFRA_CLASS),
            "base_rain_coeff_for_curve_construction": 0.25,
        },
    )
    _MODEL_CACHE[key] = model
    return model


def _default_impf_id(funcs: list[Any]) -> int:
    for func in list(funcs):
        if DEFAULT_FLOOD_CURVE_CODE in str(getattr(func, "name", "")):
            return int(getattr(func, "id", 0) or 0)
    return int(min(int(getattr(func, "id", 0) or 0) for func in list(funcs)))


def resolve_surge_impf_id(asset_type: str | None, model: MultiHazardImpactModel) -> int:
    asset = _normalize_asset_type(asset_type)
    if asset in model.surge_impf_by_asset_type:
        return int(model.surge_impf_by_asset_type[asset])
    return int(_default_impf_id(model.surge_funcs))


def resolve_rain_impf_id(asset_type: str | None, model: MultiHazardImpactModel) -> int:
    asset = _normalize_asset_type(asset_type)
    if asset in model.rain_impf_by_asset_type:
        return int(model.rain_impf_by_asset_type[asset])
    return int(_default_impf_id(model.rain_funcs))


def get_multi_hazard_vulnerability_payload(
    *,
    hazard_component: str,
    flood_curve_file: Path,
) -> dict[str, Any]:
    component = str(hazard_component or "").strip().lower()
    if component not in {"rain", "surge"}:
        raise ValueError("hazard_component must be 'rain' or 'surge'")

    model = build_multi_hazard_impact_model(
        surge_haz_type="TCSurgeBathtub",
        rain_haz_type="TR",
        flood_curve_file=Path(flood_curve_file),
    )
    curves_raw = _load_flood_depth_curves(Path(flood_curve_file))
    used_codes = [str(code) for code in list(model.mapping_info.get("curve_codes_used") or [])]
    if not used_codes:
        used_codes = [DEFAULT_FLOOD_CURVE_CODE]

    base_coeff = float(model.mapping_info.get("base_rain_coeff_for_curve_construction", 0.25) or 0.25)
    if base_coeff <= 0.0:
        base_coeff = 0.25

    if component == "surge":
        profile = "sib_tc_surge_depth_multicurve_v1"
        haz_type = str(model.surge_haz_type)
        intensity_unit = "m"
        impf_base = SURGE_IMPF_ID_BASE
    else:
        profile = "sib_tc_rain_proxy_multicurve_v1"
        haz_type = str(model.rain_haz_type)
        intensity_unit = "mm_proxy"
        impf_base = RAIN_IMPF_ID_BASE

    impf_id_by_code: dict[str, int] = {}
    curves: list[dict[str, Any]] = []
    for idx, code in enumerate(used_codes, start=1):
        curve = dict(curves_raw.get(code) or {})
        depth_raw = curve.get("depth_m")
        mdd_raw = curve.get("mdd")
        depth = [float(v) for v in list(depth_raw) if v is not None]
        mdd = [float(v) for v in list(mdd_raw) if v is not None]
        if not depth or not mdd:
            continue
        if component == "surge":
            intensity = [float(v) for v in depth]
        else:
            intensity = [float(v) * 1000.0 / base_coeff for v in depth]
        impf_id = int(impf_base + idx)
        impf_id_by_code[code] = impf_id
        curves.append(
            {
                "impf_id": impf_id,
                "code": code,
                "name": f"SIB {'Surge depth' if component == 'surge' else 'Rain proxy'} curve {code}",
                "source": "D2 flood vulnerability table (F_Vuln_Depth)",
                "geography": "Global / transferability assumptions",
                "haz_type": haz_type,
                "intensity_unit": intensity_unit,
                "intensity": intensity,
                "mdd": [float(v) for v in mdd],
                "paa": [1.0 for _ in intensity],
                "modeled_infrastructure_type": str(curve.get("modeled_infrastructure_type") or "Unknown"),
                "modeled_infrastructure_characteristics": str(
                    curve.get("modeled_infrastructure_characteristics") or "N/A"
                ),
                "uncertainty_lower": None,
                "uncertainty_upper": None,
            }
        )

    if not curves:
        raise ValueError("No usable curves were found for multi-hazard vulnerability payload")

    default_code = str(model.mapping_info.get("default_curve_code") or DEFAULT_FLOOD_CURVE_CODE)
    default_impf_id = int(impf_id_by_code.get(default_code, curves[0]["impf_id"]))

    asset_type_to_code = dict(model.mapping_info.get("asset_type_to_curve_code") or FLOOD_ASSET_TYPE_TO_CURVE_CODE)
    explicit_mapping: dict[str, dict[str, Any]] = {}
    by_code_assets: dict[str, list[str]] = {}
    for asset_type, code in asset_type_to_code.items():
        resolved_code = str(code if code in impf_id_by_code else default_code)
        explicit_mapping[str(asset_type)] = {
            "code": resolved_code,
            "impf_id": int(impf_id_by_code.get(resolved_code, default_impf_id)),
        }
        by_code_assets.setdefault(resolved_code, []).append(str(asset_type))

    for curve in curves:
        code = str(curve.get("code") or "")
        curve["sib_asset_types"] = sorted(by_code_assets.get(code, []))

    return {
        "profile": profile,
        "haz_type": haz_type,
        "hazard_component": component,
        "intensity_unit": intensity_unit,
        "explicit_asset_type_mapping": explicit_mapping,
        "default_curve": {"code": default_code, "impf_id": default_impf_id},
        "curves": curves,
    }
