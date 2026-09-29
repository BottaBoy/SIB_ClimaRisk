#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "web" / "data" / "user-impact-surfaces.json"
TERRITORIES = {
    "guadeloupe": {"label": "Guadeloupe", "basin": "NA", "iso3": "GUA"},
    "martinique": {"label": "Martinique", "basin": "NA", "iso3": "MTQ"},
    "saint-barthelemy": {"label": "Saint-Barthelemy", "basin": "NA", "iso3": "BLM"},
}
SI_SCREENING_TERRITORIES = {
    "la-reunion": {"label": "La Reunion", "basin": "SI", "iso3": "REU", "registry_key": "la_reunion"},
    "mayotte": {"label": "Mayotte", "basin": "SI", "iso3": "MYT", "registry_key": "mayotte"},
}
HAZARDS = ("storm", "storm_cmcc")
SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
COMPONENTS = ("wind", "rain", "surge", "landslide")
STATE_KEYS = ("S0", "S1", "S2", "S3")
ASSET_CLASS_ALIASES = {
    "habitation": "habitation",
    "eau_aep": "eau_aep",
    "eau_aep_cana": "eau_aep",
    "eau_aep_ouvrage_trait": "eau_aep",
    "eau_aep_ouvrage_stpmp": "eau_aep",
    "eau_aep_ouvrage_cap": "eau_aep",
    "eau_aep_ouvrage_cuv": "eau_aep",
    "eau_aep_ouvrage_ouveb": "eau_aep",
    "eau_aep_ouvrage_na": "eau_aep",
    "eau_eu": "eau_eu",
    "eau_eu_cana": "eau_eu",
    "eau_eu_pr": "eau_eu",
    "eau_eu_step": "eau_eu",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: float, digits: int = 10) -> float:
    return round(float(value), digits)


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return _round(max(0.0, numerator) / denominator)


def _normalize_asset_type(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _asset_class(asset_type: str) -> str:
    return ASSET_CLASS_ALIASES.get(_normalize_asset_type(asset_type), "habitation")


def _walk_coords(node: Any, out: list[tuple[float, float]]) -> None:
    if isinstance(node, (list, tuple)) and node:
        if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
            out.append((float(node[0]), float(node[1])))
            return
        for child in node:
            _walk_coords(child, out)


def _bbox_from_feature_collection(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    payload = _read_json(path)
    points: list[tuple[float, float]] = []
    for feat in payload.get("features") or []:
        if isinstance(feat, dict):
            geom = feat.get("geometry") or {}
            if isinstance(geom, dict):
                _walk_coords(geom.get("coordinates"), points)
    if not points:
        return None
    lon_values = [p[0] for p in points]
    lat_values = [p[1] for p in points]
    return {
        "lon_min": _round(min(lon_values) - 0.05, 6),
        "lat_min": _round(min(lat_values) - 0.05, 6),
        "lon_max": _round(max(lon_values) + 0.05, 6),
        "lat_max": _round(max(lat_values) + 0.05, 6),
    }


def _empty_annual_stats() -> dict[str, float]:
    return {
        "exposure_eur": 0.0,
        "asset_count": 0.0,
        "eai_storm_direct_eur": 0.0,
        "eai_storm_indirect_eur": 0.0,
        "eai_storm_eur": 0.0,
        "eai_cmcc_direct_eur": 0.0,
        "eai_cmcc_indirect_eur": 0.0,
        "eai_cmcc_eur": 0.0,
    }


def _empty_pml_stats() -> dict[str, Any]:
    return {
        hazard: {
            scenario: {
                "exposure_eur": 0.0,
                "damage_eur": 0.0,
                "direct_damage_eur": 0.0,
                "indirect_damage_eur": 0.0,
                "damage_components_eur": {component: 0.0 for component in COMPONENTS},
                "state_pct": {state: 0.0 for state in STATE_KEYS},
            }
            for scenario in SCENARIOS
        }
        for hazard in HAZARDS
    }


def _build_annual_factors(asset_results: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_asset_type: dict[str, dict[str, float]] = defaultdict(_empty_annual_stats)
    by_class: dict[str, dict[str, float]] = defaultdict(_empty_annual_stats)
    default_stats = _empty_annual_stats()

    for asset in asset_results:
        asset_type = _normalize_asset_type(asset.get("asset_type") or "habitation")
        asset_class = _asset_class(asset_type)
        stats_targets = (by_asset_type[asset_type], by_class[asset_class], default_stats)
        for stats in stats_targets:
            stats["asset_count"] += 1.0
            stats["exposure_eur"] += _num(asset.get("exposure_eur"))
            stats["eai_storm_direct_eur"] += _num(asset.get("eai_storm_direct_eur"))
            stats["eai_storm_indirect_eur"] += _num(asset.get("eai_storm_indirect_eur"))
            stats["eai_storm_eur"] += _num(asset.get("eai_storm_eur"))
            stats["eai_cmcc_direct_eur"] += _num(asset.get("eai_cmcc_direct_eur"))
            stats["eai_cmcc_indirect_eur"] += _num(asset.get("eai_cmcc_indirect_eur"))
            stats["eai_cmcc_eur"] += _num(asset.get("eai_cmcc_eur"))

    return (
        {key: _annual_factor_from_stats(stats) for key, stats in sorted(by_asset_type.items())},
        {
            "by_class": {key: _annual_factor_from_stats(stats) for key, stats in sorted(by_class.items())},
            "default": _annual_factor_from_stats(default_stats),
        },
    )


def _annual_factor_from_stats(stats: dict[str, float]) -> dict[str, Any]:
    exposure = _num(stats.get("exposure_eur"))
    return {
        "asset_count": int(stats.get("asset_count") or 0),
        "exposure_eur": _round(exposure, 2),
        "hazards": {
            "storm": {
                "eai_direct_ratio": _safe_ratio(_num(stats.get("eai_storm_direct_eur")), exposure),
                "eai_indirect_ratio": _safe_ratio(_num(stats.get("eai_storm_indirect_eur")), exposure),
                "eai_total_ratio": _safe_ratio(_num(stats.get("eai_storm_eur")), exposure),
            },
            "storm_cmcc": {
                "eai_direct_ratio": _safe_ratio(_num(stats.get("eai_cmcc_direct_eur")), exposure),
                "eai_indirect_ratio": _safe_ratio(_num(stats.get("eai_cmcc_indirect_eur")), exposure),
                "eai_total_ratio": _safe_ratio(_num(stats.get("eai_cmcc_eur")), exposure),
            },
        },
    }


def _build_pml_factors(pml_inputs: dict[str, Any]) -> dict[str, Any]:
    by_class = defaultdict(_empty_pml_stats)
    default_stats = _empty_pml_stats()

    for scenario in SCENARIOS:
        for row in pml_inputs.get("state_damage_tables", {}).get(scenario, []) or []:
            asset_class = str(row.get("class_key") or "").strip()
            if not asset_class:
                continue
            for hazard in HAZARDS:
                payload = row.get(hazard) if isinstance(row.get(hazard), dict) else {}
                targets = (by_class[asset_class][hazard][scenario], default_stats[hazard][scenario])
                for stats in targets:
                    stats["exposure_eur"] += _num(payload.get("exposure_eur"))
                    stats["damage_eur"] += _num(payload.get("total_damage_eur", payload.get("damage_eur")))
                    stats["direct_damage_eur"] += _num(payload.get("direct_damage_eur"))
                    stats["indirect_damage_eur"] += _num(payload.get("indirect_damage_eur"))
                    components = payload.get("damage_components_eur") if isinstance(payload.get("damage_components_eur"), dict) else {}
                    for component in COMPONENTS:
                        stats["damage_components_eur"][component] += _num(components.get(component))
                    state_pct = payload.get("state_pct") if isinstance(payload.get("state_pct"), dict) else {}
                    for state in STATE_KEYS:
                        stats["state_pct"][state] += _num(state_pct.get(state))

    return {
        "by_class": {
            key: _pml_factor_from_stats(stats)
            for key, stats in sorted(by_class.items())
        },
        "default": _pml_factor_from_stats(default_stats),
    }


def _pml_factor_from_stats(stats_by_hazard: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard, by_scenario in stats_by_hazard.items():
        out[hazard] = {}
        for scenario, stats in by_scenario.items():
            exposure = _num(stats.get("exposure_eur"))
            damage = _num(stats.get("damage_eur"))
            state_pct_total = sum(_num(stats.get("state_pct", {}).get(state)) for state in STATE_KEYS) or 1.0
            out[hazard][scenario] = {
                "damage_ratio": _safe_ratio(damage, exposure),
                "direct_ratio": _safe_ratio(_num(stats.get("direct_damage_eur")), exposure),
                "indirect_ratio": _safe_ratio(_num(stats.get("indirect_damage_eur")), exposure),
                "component_ratios": {
                    component: _safe_ratio(_num(stats.get("damage_components_eur", {}).get(component)), exposure)
                    for component in COMPONENTS
                },
                "state_pct": {
                    state: _round(_num(stats.get("state_pct", {}).get(state)) / state_pct_total * 100.0, 4)
                    for state in STATE_KEYS
                },
                "source_exposure_eur": _round(exposure, 2),
            }
    return out


def _portfolio_summary(payload: dict[str, Any]) -> dict[str, Any]:
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    out: dict[str, Any] = {}
    for hazard in HAZARDS:
        haz = portfolio.get(hazard) if isinstance(portfolio.get(hazard), dict) else {}
        out[hazard] = {
            "eai_eur": _round(_num(haz.get("eai_eur")), 2),
            "pml_10_eur": _round(_num(haz.get("pml_10_eur")), 2),
            "pml_50_eur": _round(_num(haz.get("pml_50_eur")), 2),
            "pml_100_eur": _round(_num(haz.get("pml_100_eur")), 2),
            "pml_1000_eur": _round(_num(haz.get("pml_1000_eur")), 2),
            "components_direct_eai_eur": haz.get("components_direct_eai_eur") or {},
        }
    return out


def _build_territory(territory: str, info: dict[str, Any]) -> dict[str, Any]:
    analysis_path = REPO_ROOT / "web" / "data" / f"{territory}-complete-analysis.json"
    summary_path = REPO_ROOT / "web" / "data" / f"{territory}-scientific-web-summary.json"
    network_states_path = REPO_ROOT / "web" / "data" / f"{territory}-network-states.geojson"
    payload = _read_json(analysis_path)
    summary = _read_json(summary_path) if summary_path.exists() else {}
    annual_by_asset_type, annual_defaults = _build_annual_factors(payload.get("asset_results") or [])
    pml_inputs = payload.get("pml_network_graph_inputs") if isinstance(payload.get("pml_network_graph_inputs"), dict) else {}
    bbox = _bbox_from_feature_collection(network_states_path)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return {
        "label": info["label"],
        "basin": info["basin"],
        "iso3": info["iso3"],
        "mode": "complete_analysis_calibrated",
        "bbox": bbox,
        "calibration": {
            "source_artifact": str(analysis_path.relative_to(REPO_ROOT)),
            "scientific_summary_artifact": str(summary_path.relative_to(REPO_ROOT)),
            "network_states_artifact": str(network_states_path.relative_to(REPO_ROOT)) if network_states_path.exists() else None,
            "run_id": meta.get("run_id") or (summary.get("meta") or {}).get("run_id"),
            "updated_at": meta.get("updated_at") or (summary.get("meta") or {}).get("generated_at"),
            "reference_engine": meta.get("engine") or "climada_with_interdependency_v1",
            "sampling_spacing_m": meta.get("sampling_spacing_m"),
            "hazard_track_count_storm": (meta.get("modeling") or {}).get("hazard_track_count_storm"),
            "hazard_track_count_storm_cmcc": (meta.get("modeling") or {}).get("hazard_track_count_storm_cmcc"),
        },
        "asset_class_aliases": ASSET_CLASS_ALIASES,
        "annual": {
            "by_asset_type": annual_by_asset_type,
            **annual_defaults,
        },
        "scenarios": _build_pml_factors(pml_inputs),
        "portfolio_reference": _portfolio_summary(payload),
        "pml_reference": pml_inputs,
        "network_state_methodology": meta.get("network_state_methodology") or {},
        "limits": [
            "Fast user mode applies calibrated territorial/class ratios to user geometries.",
            "Spatial network states are sampled from published network-state layers when available.",
            "Native CLIMADA remains the scientific reference for final decisions.",
        ],
    }


def _merge_annual_factors(territories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    stats_by_asset: dict[str, dict[str, float]] = defaultdict(_empty_annual_stats)
    stats_by_class: dict[str, dict[str, float]] = defaultdict(_empty_annual_stats)
    default_stats = _empty_annual_stats()
    for territory in territories.values():
        for asset_type, factor in (territory.get("annual", {}).get("by_asset_type") or {}).items():
            exposure = _num(factor.get("exposure_eur"))
            for stats in (stats_by_asset[asset_type], stats_by_class[_asset_class(asset_type)], default_stats):
                stats["asset_count"] += _num(factor.get("asset_count"))
                stats["exposure_eur"] += exposure
                stats["eai_storm_direct_eur"] += exposure * _num(factor.get("hazards", {}).get("storm", {}).get("eai_direct_ratio"))
                stats["eai_storm_indirect_eur"] += exposure * _num(factor.get("hazards", {}).get("storm", {}).get("eai_indirect_ratio"))
                stats["eai_storm_eur"] += exposure * _num(factor.get("hazards", {}).get("storm", {}).get("eai_total_ratio"))
                stats["eai_cmcc_direct_eur"] += exposure * _num(factor.get("hazards", {}).get("storm_cmcc", {}).get("eai_direct_ratio"))
                stats["eai_cmcc_indirect_eur"] += exposure * _num(factor.get("hazards", {}).get("storm_cmcc", {}).get("eai_indirect_ratio"))
                stats["eai_cmcc_eur"] += exposure * _num(factor.get("hazards", {}).get("storm_cmcc", {}).get("eai_total_ratio"))
    return {
        "by_asset_type": {key: _annual_factor_from_stats(value) for key, value in sorted(stats_by_asset.items())},
        "by_class": {key: _annual_factor_from_stats(value) for key, value in sorted(stats_by_class.items())},
        "default": _annual_factor_from_stats(default_stats),
    }


def _merge_pml_factors(territories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "by_class": {},
        "default": {hazard: {scenario: {"damage_ratio": 0.0} for scenario in SCENARIOS} for hazard in HAZARDS},
    }
    classes = sorted(
        {
            class_key
            for territory in territories.values()
            for class_key in (territory.get("scenarios", {}).get("by_class") or {}).keys()
        }
    )
    for class_key in classes:
        merged["by_class"][class_key] = {hazard: {} for hazard in HAZARDS}
        for hazard in HAZARDS:
            for scenario in SCENARIOS:
                numerators = defaultdict(float)
                exposure_total = 0.0
                state_totals = defaultdict(float)
                for territory in territories.values():
                    source = (
                        territory.get("scenarios", {})
                        .get("by_class", {})
                        .get(class_key, {})
                        .get(hazard, {})
                        .get(scenario, {})
                    )
                    exposure = _num(source.get("source_exposure_eur"))
                    exposure_total += exposure
                    numerators["damage"] += exposure * _num(source.get("damage_ratio"))
                    numerators["direct"] += exposure * _num(source.get("direct_ratio"))
                    numerators["indirect"] += exposure * _num(source.get("indirect_ratio"))
                    for component, ratio in (source.get("component_ratios") or {}).items():
                        numerators[f"component:{component}"] += exposure * _num(ratio)
                    for state, pct in (source.get("state_pct") or {}).items():
                        state_totals[state] += _num(pct)
                state_count = max(1, len(territories))
                merged["by_class"][class_key][hazard][scenario] = {
                    "damage_ratio": _safe_ratio(numerators["damage"], exposure_total),
                    "direct_ratio": _safe_ratio(numerators["direct"], exposure_total),
                    "indirect_ratio": _safe_ratio(numerators["indirect"], exposure_total),
                    "component_ratios": {
                        component: _safe_ratio(numerators[f"component:{component}"], exposure_total)
                        for component in COMPONENTS
                    },
                    "state_pct": {state: _round(state_totals[state] / state_count, 4) for state in STATE_KEYS},
                    "source_exposure_eur": _round(exposure_total, 2),
                }
    if "eau_aep" in merged["by_class"]:
        merged["default"] = merged["by_class"]["eau_aep"]
    elif classes:
        merged["default"] = merged["by_class"][classes[0]]
    return merged


def _load_si_bbox(registry_key: str) -> dict[str, float] | None:
    registry_path = REPO_ROOT / "config" / "hazard-comparison" / "territories.json"
    if not registry_path.exists():
        return None
    payload = _read_json(registry_path)
    territory = (payload.get("territories") or {}).get(registry_key)
    bbox = territory.get("comparison_bbox_hint") if isinstance(territory, dict) else None
    if not isinstance(bbox, dict):
        return None
    return {
        "lon_min": _num(bbox.get("lon_min")) - 0.05,
        "lat_min": _num(bbox.get("lat_min")) - 0.05,
        "lon_max": _num(bbox.get("lon_max")) + 0.05,
        "lat_max": _num(bbox.get("lat_max")) + 0.05,
    }


def _build_si_screening_territories(reference_territories: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    annual = _merge_annual_factors(reference_territories)
    scenarios = _merge_pml_factors(reference_territories)
    out: dict[str, dict[str, Any]] = {}
    reference_run_ids = {
        key: value.get("calibration", {}).get("run_id")
        for key, value in reference_territories.items()
    }
    for territory, info in SI_SCREENING_TERRITORIES.items():
        out[territory] = {
            "label": info["label"],
            "basin": info["basin"],
            "iso3": info["iso3"],
            "mode": "si_screening_generic",
            "bbox": _load_si_bbox(info["registry_key"]),
            "calibration": {
                "reference_engine": "climada_with_interdependency_v1",
                "source_artifact": "weighted_average_of_complete_analysis_territories",
                "reference_territories": sorted(reference_territories.keys()),
                "reference_run_ids": reference_run_ids,
            },
            "asset_class_aliases": ASSET_CLASS_ALIASES,
            "annual": annual,
            "scenarios": scenarios,
            "portfolio_reference": {},
            "pml_reference": {},
            "network_state_methodology": {},
            "limits": [
                "Bassin SI active en screening uniquement pour les donnees utilisateurs.",
                "Les facteurs sont transferes depuis les territoires complete-analysis NA; ils ne constituent pas une etude de cas complete SI.",
                "Les couches reseau/social SI ne sont pas encore publiees dans cet artefact.",
            ],
        }
    return out


def build_surface_payload() -> dict[str, Any]:
    territories = {key: _build_territory(key, info) for key, info in TERRITORIES.items()}
    territories.update(_build_si_screening_territories(territories))
    return {
        "schema_version": "user_impact_surfaces_v1",
        "engine": "precomputed_user_impact_v1",
        "reference_engine": "climada_with_interdependency_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "hazards": list(HAZARDS),
        "hazard_components": list(COMPONENTS),
        "scenarios": list(SCENARIOS),
        "return_period_by_scenario": {"rp10": 10, "rp50": 50, "rp100": 100, "rp1000": 1000},
        "validation_target": {
            "portfolio_tolerance_pct": "10-20",
            "purpose": "screening rapide valide contre les analyses completes",
        },
        "territories": territories,
        "territory_aliases": {
            "auto": "auto",
            "gua": "guadeloupe",
            "glp": "guadeloupe",
            "guadeloupe": "guadeloupe",
            "mtq": "martinique",
            "mq": "martinique",
            "martinique": "martinique",
            "blm": "saint-barthelemy",
            "stb": "saint-barthelemy",
            "saint_barthelemy": "saint-barthelemy",
            "saint-barthelemy": "saint-barthelemy",
            "reunion": "la-reunion",
            "la_reunion": "la-reunion",
            "la-reunion": "la-reunion",
            "reu": "la-reunion",
            "mayotte": "mayotte",
            "myt": "mayotte",
        },
        "limits": [
            "Le mode rapide applique des facteurs pre-calcules et documentes; il ne remplace pas un run CLIMADA complet.",
            "Les resultats SI sont limites au screening tant que les etudes de cas completes SI ne sont pas produites.",
            "Les indicateurs sociaux necessitent des donnees de population utilisateur ou des couches publiees disponibles.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build precomputed user impact surfaces from published complete analyses.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path.")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_surface_payload()
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} ({len(payload['territories'])} territories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
