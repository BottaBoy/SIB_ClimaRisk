from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from app.risk_engine.exposure_to_climada import ClimadaExposureBundle


COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
MAP_SCENARIOS = ("annual", "rp10", "rp50", "rp100", "rp1000", "event_max", "top10", "top5")

DAMAGE_BREAKDOWN_LABELS = {
    "eau_aep": "Reseau eau AEP",
    "eau_eu": "Reseau eau EU",
    "elec_bt_souterrain": "Basse tension souterrain",
    "elec_bt_aerien": "Basse tension aerien",
    "elec_hta_souterrain": "Haute tension souterrain",
    "elec_hta_aerien": "Haute tension aerien",
    "eau_aep_ouvrages": "Ouvrages AEP",
    "eau_eu_pr": "Postes de refoulement",
    "eau_eu_step": "STEP",
}

ASSET_TYPE_TO_NETWORK_CLASS = {
    "eau_aep_cana": "eau_aep",
    "eau_eu_cana": "eau_eu",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
}

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_HAZARD_PATHS = {
    "guadeloupe": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
    "martinique": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique_CMCC.h5",
    ),
    "saint-barthelemy": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
}


def _prefer_case_study_hdf5_path(configured_path: Path, case_default_path: Path) -> Path:
    builtin_case_paths = {path for pair in CASE_HAZARD_PATHS.values() for path in pair}
    if configured_path.exists():
        if configured_path == case_default_path:
            return configured_path
        if configured_path in builtin_case_paths and case_default_path.exists():
            return case_default_path
        return configured_path
    return case_default_path if case_default_path.exists() else configured_path


def _resolve_hazard_paths_for_case_study(territory: str, settings: Any) -> tuple[Path, Path]:
    default_storm_path, default_cmcc_path = CASE_HAZARD_PATHS[territory]
    settings_storm_path = Path(settings.hazard_storm_path)
    settings_cmcc_path = Path(settings.hazard_storm_cmcc_path)

    if settings.multi_hazard_enabled:
        hazard_storm_path = _prefer_case_study_hdf5_path(settings_storm_path, default_storm_path)
        hazard_storm_cmcc_path = _prefer_case_study_hdf5_path(settings_cmcc_path, default_cmcc_path)
    else:
        hazard_storm_path = default_storm_path if default_storm_path.exists() else settings_storm_path
        hazard_storm_cmcc_path = default_cmcc_path if default_cmcc_path.exists() else settings_cmcc_path

    return hazard_storm_path, hazard_storm_cmcc_path


def _breakdown_class_from_point(point_record: dict[str, Any]) -> str | None:
    asset_type = str(point_record.get("asset_type") or "")
    if asset_type.startswith("eau_aep_ouvrage_"):
        return "eau_aep_ouvrages"
    if asset_type == "eau_eu_pr":
        return "eau_eu_pr"
    if asset_type == "eau_eu_step":
        return "eau_eu_step"
    return ASSET_TYPE_TO_NETWORK_CLASS.get(asset_type)


def _normalize_component_ratio_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out = {comp: 0.0 for comp in COMPONENT_ORDER}
    source = raw or {}
    for comp in COMPONENT_ORDER:
        if comp not in source:
            continue
        try:
            out[comp] = max(0.0, float(source.get(comp) or 0.0))
        except Exception:
            out[comp] = 0.0
    total = sum(out.values())
    if total <= 0.0:
        return {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0}
    return {comp: out[comp] / total for comp in COMPONENT_ORDER}


def _normalize_breakdown_share_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out = {class_key: 0.0 for class_key in DAMAGE_BREAKDOWN_LABELS}
    source = raw or {}
    for class_key in DAMAGE_BREAKDOWN_LABELS:
        if class_key not in source:
            continue
        try:
            out[class_key] = max(0.0, float(source.get(class_key) or 0.0))
        except Exception:
            out[class_key] = 0.0
    total = float(sum(out.values()))
    if total <= 0.0:
        return {}
    return {class_key: float(value) / total for class_key, value in out.items()}


def _coerce_loss_array(raw: Any, *, size: int) -> np.ndarray:
    arr = np.asarray(raw if raw is not None else [], dtype=float).reshape(-1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.maximum(arr, 0.0)
    out = np.zeros(max(0, int(size)), dtype=float)
    if out.size == 0 or arr.size == 0:
        return out
    n = min(out.size, arr.size)
    out[:n] = arr[:n]
    return out


def _breakdown_shares_from_point_losses(point_losses: np.ndarray, point_records: list[dict[str, Any]]) -> dict[str, float]:
    raw = {class_key: 0.0 for class_key in DAMAGE_BREAKDOWN_LABELS}
    losses = np.asarray(point_losses, dtype=float).reshape(-1)
    for idx, rec in enumerate(point_records):
        if idx >= losses.size:
            break
        class_key = _breakdown_class_from_point(rec)
        if class_key in raw:
            raw[class_key] += max(0.0, float(losses[idx]))
    return _normalize_breakdown_share_map(raw)


def _scenario_breakdown_shares_from_component_arrays(
    point_records: list[dict[str, Any]],
    component_point_losses: dict[str, Any],
    component_ratios: dict[str, Any] | None,
    *,
    fallback_share_map: dict[str, Any] | None = None,
) -> dict[str, float]:
    fallback = _normalize_breakdown_share_map(fallback_share_map)
    point_count = len(point_records)
    if point_count <= 0:
        return dict(fallback)

    ratio_map = _normalize_component_ratio_map(component_ratios if isinstance(component_ratios, dict) else None)
    blended = np.zeros(point_count, dtype=float)
    used_weight = 0.0
    for component in COMPONENT_ORDER:
        weight = max(0.0, float(ratio_map.get(component, 0.0) or 0.0))
        if weight <= 0.0:
            continue
        arr = _coerce_loss_array(component_point_losses.get(component), size=point_count)
        total = float(arr.sum())
        if total <= 0.0:
            continue
        blended += (arr / total) * weight
        used_weight += weight

    if used_weight <= 0.0 or float(blended.sum()) <= 0.0:
        return dict(fallback)

    shares = _breakdown_shares_from_point_losses(blended, point_records)
    return shares if shares else dict(fallback)


def _isotonic_increasing(values: list[float]) -> list[float]:
    blocks: list[dict[str, float]] = []
    for raw_value in values:
        value = max(0.0, float(raw_value or 0.0))
        blocks.append({"sum": value, "count": 1.0})
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if (left["sum"] / left["count"]) <= (right["sum"] / right["count"]) + 1e-12:
                break
            left["sum"] += right["sum"]
            left["count"] += right["count"]
            blocks.pop()

    out: list[float] = []
    for block in blocks:
        mean = float(block["sum"] / max(block["count"], 1.0))
        out.extend([mean] * int(block["count"]))
    return out


def _normalize_proxy_scenario_loss_totals(raw_losses: dict[str, Any] | None) -> dict[str, float]:
    source = raw_losses if isinstance(raw_losses, dict) else {}
    out = {scenario: max(0.0, float(source.get(scenario, 0.0) or 0.0)) for scenario in MAP_SCENARIOS}

    annual, rp10, rp50, rp100, rp1000, event_max = _isotonic_increasing(
        [out["annual"], out["rp10"], out["rp50"], out["rp100"], out["rp1000"], out["event_max"]]
    )
    out["annual"] = annual
    out["rp10"] = rp10
    out["rp50"] = rp50
    out["rp100"] = rp100
    out["rp1000"] = rp1000
    out["event_max"] = event_max

    _, top10, top5, ranked_event_max = _isotonic_increasing(
        [out["annual"], out["top10"], out["top5"], out["event_max"]]
    )
    out["top10"] = top10
    out["top5"] = top5
    out["event_max"] = max(out["event_max"], ranked_event_max)
    return out


def _default_component_ratios() -> dict[str, dict[str, dict[str, float]]]:
    base = {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0}
    return {
        hazard: {scenario: dict(base) for scenario in MAP_SCENARIOS}
        for hazard in ("storm", "storm_cmcc")
    }


def _load_component_ratio_reference(path: Path | None) -> dict[str, dict[str, dict[str, float]]]:
    out = _default_component_ratios()
    if path is None or not path.exists():
        return out

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out

    portfolio = payload.get("portfolio_results") if isinstance(payload, dict) else None
    if not isinstance(portfolio, dict):
        return out

    for hazard in ("storm", "storm_cmcc"):
        hazard_payload = portfolio.get(hazard)
        if not isinstance(hazard_payload, dict):
            continue

        annual_raw = hazard_payload.get("components_direct_eai_eur")
        if isinstance(annual_raw, dict):
            annual_clean = {k: v for k, v in annual_raw.items() if str(k) != "combined_capped"}
            annual_ratio = _normalize_component_ratio_map(annual_clean)
            for scenario in ("annual", "rp10", "rp50", "rp100", "rp1000", "top10", "top5"):
                out[hazard][scenario] = dict(annual_ratio)

        event_raw = hazard_payload.get("components_direct_percentile_99_loss_eur")
        if not isinstance(event_raw, dict):
            event_raw = hazard_payload.get("components_direct_max_event_loss_eur")
        if isinstance(event_raw, dict):
            out[hazard]["event_max"] = _normalize_component_ratio_map(event_raw)
        elif isinstance(annual_raw, dict):
            annual_clean = {k: v for k, v in annual_raw.items() if str(k) != "combined_capped"}
            out[hazard]["event_max"] = _normalize_component_ratio_map(annual_clean)

        out[hazard]["rp10"] = dict(out[hazard].get("rp10") or out[hazard].get("annual") or {"wind": 1.0, "rain": 0.0, "surge": 0.0})
        out[hazard]["rp50"] = dict(out[hazard].get("rp50") or out[hazard].get("rp100") or out[hazard].get("annual") or {"wind": 1.0, "rain": 0.0, "surge": 0.0})
        out[hazard]["rp1000"] = dict(out[hazard].get("rp1000") or out[hazard].get("rp100") or out[hazard].get("annual") or {"wind": 1.0, "rain": 0.0, "surge": 0.0})

    return out


def _default_multi_hazard_proxy(
    component_ratios_by_hazard: dict[str, dict[str, dict[str, float]]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    ratios = component_ratios_by_hazard or _default_component_ratios()
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for hazard in ("storm", "storm_cmcc"):
        out[hazard] = {
            "component_ratios": {
                scenario: _normalize_component_ratio_map((ratios.get(hazard) or {}).get(scenario))
                for scenario in MAP_SCENARIOS
            },
            "global_multipliers": {scenario: 1.0 for scenario in MAP_SCENARIOS},
            "breakdown_shares": {scenario: {} for scenario in MAP_SCENARIOS},
        }
    return out


def _component_ratios_from_climada_run(climada_run: Any) -> dict[str, dict[str, dict[str, float]]]:
    out = _default_component_ratios()
    component_hazards = getattr(climada_run, "component_hazards", {}) or {}

    for hazard in ("storm", "storm_cmcc"):
        hazard_components = component_hazards.get(hazard)
        if not isinstance(hazard_components, dict) or not hazard_components:
            continue

        annual_raw: dict[str, float] = {}
        event_raw: dict[str, float] = {}
        rp10_raw: dict[str, float] = {}
        rp50_raw: dict[str, float] = {}
        rp100_raw: dict[str, float] = {}
        rp1000_raw: dict[str, float] = {}

        for component in COMPONENT_ORDER:
            comp_result = hazard_components.get(component)
            if comp_result is None:
                continue
            annual_raw[component] = float(np.asarray(getattr(comp_result, "eai_direct_by_point", []), dtype=float).sum())
            event_raw[component] = float(getattr(comp_result, "max_event_loss_eur", 0.0) or 0.0)
            pml = getattr(comp_result, "pml_eur", {}) or {}
            rp10_raw[component] = float(pml.get(10, 0.0) or 0.0)
            rp50_raw[component] = float(pml.get(50, 0.0) or 0.0)
            rp100_raw[component] = float(pml.get(100, 0.0) or 0.0)
            rp1000_raw[component] = float(pml.get(1000, 0.0) or 0.0)

        annual_ratio = _normalize_component_ratio_map(annual_raw)
        out[hazard]["annual"] = dict(annual_ratio)
        out[hazard]["top10"] = dict(annual_ratio)
        out[hazard]["top5"] = dict(annual_ratio)
        rp10_ratio = _normalize_component_ratio_map(rp10_raw)
        out[hazard]["rp10"] = dict(rp10_ratio if sum(max(0.0, float(v)) for v in rp10_raw.values()) > 0.0 else annual_ratio)
        out[hazard]["rp100"] = _normalize_component_ratio_map(rp100_raw)
        rp50_ratio = _normalize_component_ratio_map(rp50_raw)
        out[hazard]["rp50"] = dict(
            rp50_ratio if sum(max(0.0, float(v)) for v in rp50_raw.values()) > 0.0 else (out[hazard].get("rp100") or annual_ratio)
        )
        rp1000_ratio = _normalize_component_ratio_map(rp1000_raw)
        out[hazard]["rp1000"] = dict(
            rp1000_ratio if sum(max(0.0, float(v)) for v in rp1000_raw.values()) > 0.0 else (out[hazard].get("rp100") or annual_ratio)
        )
        out[hazard]["event_max"] = _normalize_component_ratio_map(event_raw)

    return out


def _pick_evenly_spaced_indices(indices: list[int], keep: int) -> list[int]:
    if keep <= 0 or not indices:
        return []
    if keep >= len(indices):
        return list(indices)
    if keep == 1:
        return [indices[0]]
    positions = np.linspace(0, len(indices) - 1, keep)
    selected: list[int] = []
    used: set[int] = set()
    for pos in positions:
        idx = indices[int(round(float(pos)))]
        if idx in used:
            continue
        selected.append(idx)
        used.add(idx)
    if len(selected) < keep:
        for idx in indices:
            if idx in used:
                continue
            selected.append(idx)
            used.add(idx)
            if len(selected) >= keep:
                break
    return selected[:keep]


def _subset_bundle_for_component_ratios(
    bundle: "ClimadaExposureBundle",
    *,
    max_points_total: int,
    priority_scores: dict[int, float] | None = None,
) -> "ClimadaExposureBundle":
    point_records = list(bundle.point_records or [])
    total = len(point_records)
    max_points_total = max(1, int(max_points_total))
    if total <= max_points_total:
        return bundle

    normalized_priority_scores: dict[int, float] = {}
    for idx, raw in (priority_scores or {}).items():
        try:
            score = float(raw)
        except Exception:
            continue
        if idx < 0 or idx >= total or not np.isfinite(score) or score <= 0.0:
            continue
        normalized_priority_scores[int(idx)] = score

    groups: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(point_records):
        asset_type = str(rec.get("asset_type") or "unknown").strip().lower()
        territory_id = str(rec.get("territory_id") or "unknown").strip().lower()
        groups[f"{asset_type}|{territory_id}"].append(idx)

    group_keys = sorted(groups.keys())
    base_alloc = {key: 1 for key in group_keys}
    remaining = max(0, max_points_total - sum(base_alloc.values()))
    total_points = sum(len(groups[key]) for key in group_keys)

    allocations: dict[str, int] = {}
    for key in group_keys:
        group_size = len(groups[key])
        extra = int(round((group_size / max(1, total_points)) * remaining)) if remaining > 0 else 0
        allocations[key] = min(group_size, base_alloc[key] + max(0, extra))

    allocated = sum(allocations.values())
    if allocated > max_points_total:
        overflow = allocated - max_points_total
        for key in sorted(group_keys, key=lambda item: allocations[item], reverse=True):
            if overflow <= 0:
                break
            reducible = max(0, allocations[key] - 1)
            if reducible <= 0:
                continue
            delta = min(reducible, overflow)
            allocations[key] -= delta
            overflow -= delta
    elif allocated < max_points_total:
        deficit = max_points_total - allocated
        for key in sorted(group_keys, key=lambda item: len(groups[item]), reverse=True):
            if deficit <= 0:
                break
            capacity = len(groups[key]) - allocations[key]
            if capacity <= 0:
                continue
            delta = min(capacity, deficit)
            allocations[key] += delta
            deficit -= delta

    selected_indices: list[int] = []
    for key in group_keys:
        indices = list(groups[key])
        keep = allocations[key]
        if keep <= 0:
            continue

        priority_indices = [idx for idx in indices if idx in normalized_priority_scores]
        priority_indices.sort(key=lambda idx: (-normalized_priority_scores.get(idx, 0.0), idx))
        if priority_indices:
            max_priority_keep = keep if keep <= 2 else max(1, int(np.ceil(keep * 0.4)))
            priority_keep = min(len(priority_indices), max_priority_keep)
        else:
            priority_keep = 0

        if priority_keep > 0:
            selected_indices.extend(priority_indices[:priority_keep])
        remaining = keep - priority_keep
        remaining_indices = [idx for idx in indices if idx not in normalized_priority_scores]
        selected_non_priority = _pick_evenly_spaced_indices(remaining_indices, remaining)
        selected_indices.extend(selected_non_priority)
        if len(selected_non_priority) < remaining:
            deficit = remaining - len(selected_non_priority)
            leftover_priority = [idx for idx in priority_indices[priority_keep:] if idx not in selected_indices]
            selected_indices.extend(leftover_priority[:deficit])

    selected_indices = sorted(set(selected_indices))[:max_points_total]

    selected_records = [point_records[idx] for idx in selected_indices if 0 <= idx < total]
    if not selected_records:
        return bundle

    exposure = bundle.exposures.copy(deep=False)
    exposure.set_gdf(
        bundle.exposures.gdf.iloc[selected_indices].reset_index(drop=True),
        crs=bundle.exposures.crs,
    )

    from app.risk_engine.exposure_to_climada import ClimadaExposureBundle

    return ClimadaExposureBundle(
        exposures=exposure,
        point_records=selected_records,
        metric_crs=bundle.metric_crs,
        warnings=list(bundle.warnings or []),
    )


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shared utilities for case-study proxy generation (library module, no standalone action)."
    )
    return parser


def main() -> None:
    _build_cli().parse_args()


if __name__ == "__main__":
    main()
