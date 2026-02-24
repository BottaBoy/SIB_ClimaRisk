from __future__ import annotations

from dataclasses import dataclass
import math

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


def try_build_climada_impact_func() -> object | None:
    """Create a CLIMADA ImpactFunc object when CLIMADA is available.

    The production backend should use this instead of notebook-only dummy/example curves.
    """
    try:
        from climada.entity.impact_funcs.base import ImpactFunc  # type: ignore
    except Exception:
        return None

    curve = build_eberenz_curve()
    if np is None:
        return None

    impf = ImpactFunc()
    impf.id = 2
    impf.haz_type = "TC"
    impf.name = "Eberenz Caraibes Impact Function"
    impf.intensity = np.array(curve["intensity"])
    impf.mdd = np.array(curve["mdd"])
    impf.paa = np.array(curve["paa"])
    impf.intensity_unit = curve["intensity_unit"]
    try:
        impf.check()
    except Exception:
        return None
    return impf
