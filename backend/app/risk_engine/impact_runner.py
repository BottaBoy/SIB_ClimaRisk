from __future__ import annotations

from collections import defaultdict
from typing import Any
import math

from .types import DisaggregationSummary, ImpactComputationResult, NormalizedExposure


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_label(text: str) -> str:
    return ''.join(ch if ch.isalnum() else '-' for ch in text.lower()).strip('-') or 'territory'


def _group_features_to_territories(exposure: NormalizedExposure) -> list[dict[str, Any]]:
    # MVP grouping strategy:
    # - if coordinates exist, aggregate by coarse 1-degree bins (stable and cheap)
    # - otherwise aggregate everything into one pseudo-territory
    grouped: dict[str, dict[str, Any]] = {}
    unlocated: list[Any] = []

    for feat in exposure.features:
        if feat.lat is None or feat.lon is None:
            unlocated.append(feat)
            continue
        key = f"{round(feat.lat, 0):.0f}_{round(feat.lon, 0):.0f}"
        row = grouped.setdefault(key, {
            "territory_id": f"cell-{key}",
            "territory_label": f"Zone ({round(feat.lat,1)}, {round(feat.lon,1)})",
            "lat_sum": 0.0,
            "lon_sum": 0.0,
            "count": 0,
            "exposure_eur": 0.0,
        })
        row["lat_sum"] += float(feat.lat)
        row["lon_sum"] += float(feat.lon)
        row["count"] += 1
        row["exposure_eur"] += float(feat.value_eur)

    territories: list[dict[str, Any]] = []
    for row in grouped.values():
        territories.append({
            "territory_id": row["territory_id"],
            "territory_label": row["territory_label"],
            "lat": row["lat_sum"] / max(1, row["count"]),
            "lon": row["lon_sum"] / max(1, row["count"]),
            "exposure_eur": row["exposure_eur"],
        })

    if unlocated or not territories:
        total = sum(float(f.value_eur) for f in unlocated) + (0.0 if territories else sum(float(f.value_eur) for f in exposure.features))
        if total > 0:
            territories.append({
                "territory_id": "uploaded-aggregate",
                "territory_label": "Uploaded Exposure (aggregate)",
                "lat": None,
                "lon": None,
                "exposure_eur": total,
            })

    return territories


def _build_fec_curve(total_exposure_eur: float, ratio: float, lifetime_years: int | None = None) -> dict[str, Any]:
    # Deterministic synthetic exceedance curve for MVP scaffolding.
    return_periods = [1, 2, 5, 10, 20, 30, 50, 75, 100, 150, 200]
    curve_y: list[float] = []
    for rp in return_periods:
        damp = 1.0 / math.sqrt(max(1.0, rp))
        life_factor = 1.0
        if lifetime_years:
            life_factor = 1.0 + (lifetime_years / 100.0) * 0.35
        curve_y.append(total_exposure_eur * ratio * damp * life_factor)
    return {
        "return_period_years": return_periods,
        "damage_eur": [round(v, 2) for v in curve_y],
    }


def _build_graphs(total_exposure: float, storm_ratio: float, cmcc_ratio: float) -> dict[str, Any]:
    bins = [20, 30, 40, 50, 60, 70, 80]
    base_hist = [6, 18, 24, 20, 16, 10, 6]
    cmcc_hist = [4, 12, 22, 24, 20, 12, 8]

    def hazard_graphs(name: str, hist_vals: list[int], ratio: float) -> dict[str, Any]:
        return {
            "wind_year_hist": {
                "title": f"{name} - Max wind per year",
                "bins_mps": bins,
                "percent": hist_vals,
            },
            "wind_track_hist": {
                "title": f"{name} - Max wind per track",
                "bins_mps": bins,
                "percent": [max(0, v - 2) for v in hist_vals],
            },
            "annual_fec": {
                "title": f"{name} - Annual frequency-exceedance curve",
                **_build_fec_curve(total_exposure, ratio, lifetime_years=None),
                "y_scale": "linear",
            },
            "lifetime_fec": {
                "title": f"{name} - Lifetime FEC (30y / 50y)",
                "series": [
                    {"name": "30-year FEC", **_build_fec_curve(total_exposure, ratio, lifetime_years=30)},
                    {"name": "50-year FEC", **_build_fec_curve(total_exposure, ratio, lifetime_years=50)},
                ],
                "y_scale": "log",
            },
        }

    return {
        "storm": hazard_graphs("STORM", base_hist, storm_ratio),
        "storm_cmcc": hazard_graphs("STORM_CMCC", cmcc_hist, cmcc_ratio),
        "comparison": {
            "side_by_side": {
                "hazards": ["STORM", "STORM_CMCC"],
                "metrics": ["annual_eai", "max_event_loss"],
                "values": {
                    "annual_eai": [round(total_exposure * storm_ratio, 2), round(total_exposure * cmcc_ratio, 2)],
                    "max_event_loss": [round(total_exposure * storm_ratio * 4.5, 2), round(total_exposure * cmcc_ratio * 4.9, 2)],
                },
            }
        },
    }


def compute_impacts_fallback(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
) -> ImpactComputationResult:
    total_exposure = max(0.0, exposure.total_exposure_eur)
    complexity = _clamp(disagg.asset_count_points / max(1, exposure.asset_count_original), 1.0, 50.0)
    base_ratio = 0.0125 + (0.0015 * math.log10(complexity + 1.0))
    storm_ratio = _clamp(base_ratio, 0.005, 0.08)
    cmcc_ratio = _clamp(storm_ratio * 1.28, storm_ratio + 0.002, 0.12)

    territories = _group_features_to_territories(exposure)
    territory_results: list[dict[str, Any]] = []
    for row in territories:
        exp_eur = float(row["exposure_eur"])
        eai_storm = exp_eur * storm_ratio
        eai_cmcc = exp_eur * cmcc_ratio
        risk_index_storm = _clamp((eai_storm / max(exp_eur, 1.0)) * 1000.0, 0, 100)
        risk_index_cmcc = _clamp((eai_cmcc / max(exp_eur, 1.0)) * 1000.0, 0, 100)
        territory_results.append({
            "territory_id": row["territory_id"],
            "territory_label": row["territory_label"],
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "exposure_eur": round(exp_eur, 2),
            "eai_storm_eur": round(eai_storm, 2),
            "eai_cmcc_eur": round(eai_cmcc, 2),
            "risk_index_storm": round(risk_index_storm, 2),
            "risk_index_cmcc": round(risk_index_cmcc, 2),
        })

    portfolio_eai_storm = round(total_exposure * storm_ratio, 2)
    portfolio_eai_cmcc = round(total_exposure * cmcc_ratio, 2)
    max_event_storm = round(portfolio_eai_storm * 4.5, 2)
    max_event_cmcc = round(portfolio_eai_cmcc * 4.9, 2)

    portfolio_results = {
        "storm": {
            "eai_eur": portfolio_eai_storm,
            "aai_agg_eur": portfolio_eai_storm,
            "max_event_loss_eur": max_event_storm,
        },
        "storm_cmcc": {
            "eai_eur": portfolio_eai_cmcc,
            "aai_agg_eur": portfolio_eai_cmcc,
            "max_event_loss_eur": max_event_cmcc,
        },
        "delta": {
            "eai_eur": round(portfolio_eai_cmcc - portfolio_eai_storm, 2),
            "eai_pct": round(((portfolio_eai_cmcc / max(portfolio_eai_storm, 1.0)) - 1.0) * 100.0, 2),
        },
    }

    graphs = _build_graphs(total_exposure, storm_ratio, cmcc_ratio)

    notes = [
        "Fallback deterministic engine is currently active. The CLIMADA/geospatial runtime is installed, but the production CLIMADA computation path is not yet wired into compute_impacts().",
        "Production engine should replace these impacts with CLIMADA STORM/STORM_CMCC results using the Eberenz 2021 TC impact function.",
        "Disaggregation settings and geometry complexity are used to keep fallback outputs stable and explainable across runs.",
    ]

    return ImpactComputationResult(
        engine="fallback",
        territory_results=territory_results,
        portfolio_results=portfolio_results,
        graphs=graphs,
        notes=notes,
    )


def compute_impacts(
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
) -> ImpactComputationResult:
    """Entry point for impact computation.

    Replace this with the CLIMADA production path once the geospatial runtime is installed.
    """
    return compute_impacts_fallback(exposure, disagg)
