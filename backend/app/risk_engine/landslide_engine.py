from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path
from typing import Any

from shapely.geometry import box

from .climada_engine import HazardImpactResult, _build_exposure_with_impf_column, _compute_component_impact
from .climada_petals_loader import load_climada_petals_hazard_symbols
from .errors import DependencyMissingError
from .impact_functions_landslide import (
    LANDSLIDE_HAZ_TYPE,
    LANDSLIDE_IMPF_ID_HYPOTHESIS,
    try_build_climada_landslide_impact_funcs,
)


def _require_runtime() -> dict[str, Any]:
    try:
        import numpy as np  # type: ignore
        from scipy import sparse  # type: ignore
        from climada.engine import ImpactCalc  # type: ignore
        from climada.entity.impact_funcs import ImpactFuncSet  # type: ignore
        from climada.hazard import Centroids  # type: ignore
        from climada.util import coordinates as u_coord  # type: ignore
        petals_symbols = load_climada_petals_hazard_symbols("landslide", "Landslide", "sample_events")
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA Petals landslide runtime dependencies are required") from exc
    return {
        "np": np,
        "sparse": sparse,
        "ImpactCalc": ImpactCalc,
        "ImpactFuncSet": ImpactFuncSet,
        "Centroids": Centroids,
        "u_coord": u_coord,
        "Landslide": petals_symbols["Landslide"],
        "sample_events": petals_symbols["sample_events"],
    }


@contextmanager
def _temporary_numpy_seed(np: Any, seed: int):
    state = np.random.get_state()
    np.random.seed(int(seed))
    try:
        yield
    finally:
        np.random.set_state(state)


def _stable_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def build_landslide_hazard_from_prob(
    *,
    bbox: tuple[float, float, float, float],
    path_sourcefile: Path,
    corr_fact: float = 500.0,
    n_years: int = 200,
    dist: str = "poisson",
    random_seed: int | None = None,
    target_centroids: Any | None = None,
) -> Any:
    runtime = _require_runtime()
    np = runtime["np"]
    sparse = runtime["sparse"]
    Centroids = runtime["Centroids"]
    u_coord = runtime["u_coord"]
    Landslide = runtime["Landslide"]
    sample_events = runtime["sample_events"]

    path = Path(path_sourcefile).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Landslide raster not found: {path}")
    if float(corr_fact) <= 0.0:
        raise ValueError("corr_fact must be positive")
    if int(n_years) <= 0:
        raise ValueError("n_years must be positive")

    bbox_tuple = tuple(float(v) for v in bbox)
    if target_centroids is not None:
        sample_lat = np.asarray(getattr(target_centroids, "lat", []), dtype=float).reshape(-1)
        sample_lon = np.asarray(getattr(target_centroids, "lon", []), dtype=float).reshape(-1)
        if sample_lat.size == 0 or sample_lon.size == 0 or sample_lat.size != sample_lon.size:
            raise ValueError("target_centroids must expose matching lat/lon arrays for landslide sampling")
        prob_arr = np.asarray(u_coord.read_raster_sample(str(path), sample_lat, sample_lon), dtype=float).reshape(-1)
    else:
        geometry = [box(*bbox_tuple, ccw=True)]
        meta, prob_matrix = u_coord.read_raster(str(path), geometry=geometry)
        prob_arr = np.asarray(prob_matrix, dtype=float).squeeze()

    if prob_arr.size == 0:
        raise ValueError(f"Empty landslide raster after sampling bbox={bbox_tuple}: {path}")
    prob_arr = np.nan_to_num(prob_arr, nan=0.0, posinf=0.0, neginf=0.0)

    # Raster classes 0/1 represent zero probability. Classes 2..5 are sampled
    # probabilistically and later used as severity levels in the impact function.
    class_arr = np.where(prob_arr > 1.0, prob_arr, 0.0)
    sample_prob_arr = np.clip(class_arr / float(corr_fact), 0.0, 1.0)

    seed = int(random_seed) if random_seed is not None else _stable_seed(
        path.resolve(strict=False),
        bbox_tuple,
        tuple(round(float(value), 5) for value in np.asarray(getattr(target_centroids, "lat", []), dtype=float).reshape(-1))
        if target_centroids is not None
        else (),
        tuple(round(float(value), 5) for value in np.asarray(getattr(target_centroids, "lon", []), dtype=float).reshape(-1))
        if target_centroids is not None
        else (),
        float(corr_fact),
        int(n_years),
        str(dist).strip().lower(),
    )
    with _temporary_numpy_seed(np, seed):
        sampled = sample_events(sample_prob_arr, int(n_years), str(dist).strip().lower())
    sampled = sparse.csr_matrix(sampled)

    # Multiply the binary sampled occurrence by the original class values.
    class_vector = np.asarray(class_arr, dtype=float).reshape(-1)
    class_diag = sparse.diags(class_vector, offsets=0, format="csr")
    intensity = (sampled @ class_diag).tocsr()

    haz = Landslide()
    haz.centroids = copy.deepcopy(target_centroids) if target_centroids is not None else Centroids.from_meta(meta)
    haz.intensity = intensity
    haz.fraction = sampled.copy()
    if getattr(haz.fraction, "nnz", 0) > 0:
        haz.fraction.data[:] = 1.0
    haz.frequency = np.ones(int(n_years), dtype=float) / float(n_years)
    haz.date = np.array([])
    haz.event_name = np.array(range(int(n_years)))
    haz.event_id = np.array(range(int(n_years)))
    haz.check()
    return haz


def _build_landslide_impact_func_set() -> Any:
    runtime = _require_runtime()
    ImpactFuncSet = runtime["ImpactFuncSet"]
    funcs = try_build_climada_landslide_impact_funcs()
    if funcs is None:
        raise DependencyMissingError("Unable to instantiate CLIMADA landslide impact functions")
    return ImpactFuncSet(funcs)


def run_landslide_direct_impacts(
    exposure_bundle: Any,
    *,
    bbox: tuple[float, float, float, float],
    path_sourcefile: Path,
    corr_fact: float = 500.0,
    n_years: int = 200,
    dist: str = "poisson",
    random_seed: int | None = None,
    top_n_events: int = 20,
) -> HazardImpactResult:
    runtime = _require_runtime()
    np = runtime["np"]
    ImpactCalc = runtime["ImpactCalc"]

    point_records = list(getattr(exposure_bundle, "point_records", []) or [])
    exposure_count = len(point_records)
    exposure = _build_exposure_with_impf_column(
        exposure_bundle.exposures,
        haz_type=LANDSLIDE_HAZ_TYPE,
        impf_ids=[LANDSLIDE_IMPF_ID_HYPOTHESIS for _ in range(exposure_count)],
    )
    impfset = _build_landslide_impact_func_set()
    hazard = build_landslide_hazard_from_prob(
        bbox=bbox,
        path_sourcefile=path_sourcefile,
        corr_fact=corr_fact,
        n_years=n_years,
        dist=dist,
        random_seed=random_seed,
    )
    return _compute_component_impact(
        np,
        ImpactCalc,
        exposures=exposure,
        impfset=impfset,
        hazard_obj=hazard,
        top_n_events=top_n_events,
    )


def scenario_loss_factors(result: HazardImpactResult) -> dict[str, float]:
    eai = float(max(0.0, result.aai_agg_eur))
    pml = dict(getattr(result, "pml_eur", {}) or {})
    max_loss = float(max(0.0, result.max_event_loss_eur))
    if eai <= 0.0:
        return {
            "annual": 0.0,
            "rp10": 0.0,
            "rp50": 0.0,
            "rp100": 0.0,
            "rp1000": 0.0,
            "event_max": 0.0,
            "top10": 0.0,
            "top5": 0.0,
        }
    rp10 = float(pml.get(10, 0.0) or 0.0) / eai
    rp50 = float(pml.get(50, 0.0) or 0.0) / eai
    rp100 = float(pml.get(100, 0.0) or 0.0) / eai
    rp1000 = float(pml.get(1000, 0.0) or 0.0) / eai
    event_max = max_loss / eai
    return {
        "annual": 1.0,
        "rp10": max(0.0, rp10),
        "rp50": max(0.0, rp50),
        "rp100": max(0.0, rp100),
        "rp1000": max(0.0, rp1000),
        "event_max": max(0.0, event_max),
        "top10": max(0.0, rp50),
        "top5": max(0.0, rp100),
    }
