#!/usr/bin/env python3
from __future__ import annotations

"""
Targeted scientific rebuild for complete-analysis graph inputs.

Why this exists:
- archived runs produced robust `complete-analysis.json` portfolio outputs, but older
  publication payloads did not persist strict scientific graph tables for
  `rp10` / `rp50` / `rp100` / `rp1000`;
- the legacy page-analysis chain tried to reconstruct those widgets with a lighter
  path, which is now forbidden;
- this module rebuilds the missing graph inputs directly from the original
  complete-analysis run settings, checkpoints, exposure, and hazards, then writes
  them back into `complete_analysis.scientific_graph_inputs`.

Operational note for future audits:
- `build_scientific_web_summary.py` now invokes this module automatically when an
  archived run is missing strict scenario tables, so future complete-analysis runs
  should not require a separate manual "post-process" step from operators;
- the manual CLI remains available only to repair archived runs that predate the
  strict v4 publication contract.
"""

import argparse
import ctypes
import dataclasses
import gc
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.config import resolve_surge_topo_path_for_territory
from app.risk_engine.climada_engine import (  # noqa: E402
    _build_exposure_with_impf_column,
    _build_surge_hazard,
    _normalize_frequency_on_copy,
    _prepare_topo_raster_for_exposure,
    _require_runtime,
)
from app.risk_engine.climada_petals_loader import load_climada_petals_hazard_symbols  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.exposure_to_climada import ClimadaExposureBundle  # noqa: E402
from app.risk_engine.hazard_loader import (  # noqa: E402
    _build_centroids_from_points,
    _build_hazard_from_tracks,
    load_storm_hazards,
    load_storm_hazards_from_parquet_for_points,
    release_hazard_bundle_tracks,
    resolve_hazard_bundle_tracks,
)
from app.risk_engine.impact_functions import try_build_climada_impact_funcs  # noqa: E402
from app.risk_engine.impact_functions_multi_hazard import (  # noqa: E402
    build_multi_hazard_impact_model,
    resolve_rain_impf_id,
    resolve_surge_impf_id,
)
from app.risk_engine.impact_runner import prepare_climada_exposure_bundle  # noqa: E402
from build_guadeloupe_page1_data import (  # noqa: E402
    ASSET_TYPE_TO_NETWORK_CLASS,
    COMPONENT_ORDER,
    DAMAGE_BREAKDOWN_LABELS,
    NETWORK_CLASS_LABELS,
    STATE_ORDER,
    _allocate_damage_components,
    _breakdown_class_from_point,
    _electric_native_unit_id_from_point,
    _evaluate_network_dependency_scenario,
    _is_blocking_water_asset_point,
    _is_water_service_network_point,
    _network_class_from_point,
    _water_service_class_from_point,
    _water_service_feature_id_from_point,
)
from run_complete_analysis import (  # noqa: E402
    _build_complete_analysis_settings,
    _reconcile_disaggregation_with_climada_bundle,
    build_complete_exposure,
)
try:  # pragma: no cover - import path depends on module vs CLI execution
    from scripts.scientific_publication_contract import (  # type: ignore  # noqa: E402
        EVENT_SELECTION_BASIS,
        PUBLIC_SERVICE_KEYS,
        RETURN_PERIOD_BY_SCENARIO,
        SCIENTIFIC_SCENARIOS,
    )
except ModuleNotFoundError:  # pragma: no cover
    from scientific_publication_contract import (  # type: ignore  # noqa: E402
        EVENT_SELECTION_BASIS,
        PUBLIC_SERVICE_KEYS,
        RETURN_PERIOD_BY_SCENARIO,
        SCIENTIFIC_SCENARIOS,
    )


LOGGER = logging.getLogger(__name__)
HAZARD_KEYS = ("storm", "storm_cmcc")
COMPONENT_NAMES = ("wind", "rain", "surge")
SCENARIOS = SCIENTIFIC_SCENARIOS
EVENT_SCENARIOS = SCIENTIFIC_SCENARIOS
GRAPH_INPUT_AUTOFILL_NOTE = (
    "Scientific graph inputs for RP10/RP50/RP100/RP1000 were rebuilt from the original "
    "complete-analysis hazards/exposure/checkpoints. This repair path is automatic "
    "for archived pre-v4 runs and does not rely on page-analysis or any fallback."
)
WORKER_MAX_POINTS_PER_SHARD = 5_000
ASSET_TYPE_TO_BREAKDOWN_CLASS = {
    **ASSET_TYPE_TO_NETWORK_CLASS,
    "eau_aep_ouvrage_cap": "eau_aep_ouvrages",
    "eau_aep_ouvrage_stpmp": "eau_aep_ouvrages",
    "eau_aep_ouvrage_ouveb": "eau_aep_ouvrages",
    "eau_aep_ouvrage_trait": "eau_aep_ouvrages",
    "eau_aep_ouvrage_cuv": "eau_aep_ouvrages",
    "eau_aep_ouvrage_captage": "eau_aep_ouvrages",
    "eau_aep_ouvrage_production_traitement": "eau_aep_ouvrages",
    "eau_aep_ouvrage_stockage": "eau_aep_ouvrages",
    "eau_eu_pr": "eau_eu_pr",
    "eau_eu_step": "eau_eu_step",
}
DAMAGE_ZONE_FAMILY_CLASS_KEYS = {
    "aep": ("eau_aep", "eau_aep_ouvrages"),
    "eu": ("eau_eu", "eau_eu_pr", "eau_eu_step"),
    "elec": (
        "elec_bt_souterrain",
        "elec_bt_aerien",
        "elec_hta_souterrain",
        "elec_hta_aerien",
    ),
}
DAMAGE_ZONE_FAMILY_LABELS = {
    "aep": "AEP",
    "eu": "EU",
    "elec": "Elec",
}
DAMAGE_ZONE_FAMILY_NETWORK_KIND = {
    "aep": "AEP",
    "eu": "EU",
    "elec": "ELEC",
}


@dataclass(frozen=True)
class ComponentContext:
    hazard_obj: Any
    impfset: Any
    exposure_builder: Callable[[ClimadaExposureBundle], Any]


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _round2(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except Exception:
        return 0.0


def _trim_process_memory() -> None:
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _state_code(value: Any) -> str:
    state = str(value or "S0").strip().upper()
    return state if state in STATE_ORDER else "S0"


def _state_severity(value: Any) -> int:
    return int(STATE_ORDER.get(_state_code(value), 0))


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def needs_strict_scientific_rebuild(complete_analysis: dict[str, Any]) -> bool:
    graph_inputs = _safe_dict(complete_analysis.get("scientific_graph_inputs"))
    if list(graph_inputs.get("scenarios") or []) != list(SCIENTIFIC_SCENARIOS):
        return True
    if str(graph_inputs.get("event_selection_basis") or "").strip() != EVENT_SELECTION_BASIS:
        return True
    state_tables = _safe_dict(graph_inputs.get("state_damage_tables"))
    breakdowns = _safe_dict(graph_inputs.get("damage_breakdown_by_scenario"))
    damage_zones = _safe_dict(graph_inputs.get("damage_zones_by_scenario"))
    for scenario in EVENT_SCENARIOS:
        if not _safe_list(state_tables.get(scenario)):
            return True
        block = _safe_dict(breakdowns.get(scenario))
        if not _safe_list(block.get("storm")) or not _safe_list(block.get("storm_cmcc")):
            return True
        zone_block = _safe_dict(damage_zones.get(scenario))
        for hazard_key in HAZARD_KEYS:
            hazard_block = _safe_dict(zone_block.get(hazard_key))
            for family_key in DAMAGE_ZONE_FAMILY_CLASS_KEYS:
                if not _safe_list(hazard_block.get(family_key)):
                    return True
    event_selection = _safe_dict(graph_inputs.get("event_selection"))
    event_indices = _safe_dict(event_selection.get("event_indices_by_hazard"))
    event_losses = _safe_dict(event_selection.get("event_loss_eur_by_hazard"))
    for hazard_key in HAZARD_KEYS:
        indices_row = _safe_dict(event_indices.get(hazard_key))
        losses_row = _safe_dict(event_losses.get(hazard_key))
        for scenario in EVENT_SCENARIOS:
            if scenario not in indices_row or scenario not in losses_row:
                return True
    return False


def _resolve_manifest_path(
    *,
    complete_analysis_path: Path,
    complete_analysis: dict[str, Any],
    manifest_path: Path | None,
) -> Path:
    if manifest_path is not None:
        return manifest_path
    run_id = str(
        _safe_dict(complete_analysis.get("meta")).get("run_id")
        or complete_analysis.get("run_id")
        or ""
    ).strip()
    if not run_id:
        parts = list(complete_analysis_path.resolve().parts)
        try:
            outputs_idx = parts.index("complete-analysis-runs")
        except ValueError:
            outputs_idx = -1
        if outputs_idx >= 0 and outputs_idx + 1 < len(parts):
            candidate = str(parts[outputs_idx + 1]).strip()
            if candidate:
                run_id = candidate
    if not run_id:
        raise ValueError("Unable to resolve run_id from complete-analysis payload for scientific graph rebuild")
    resolved = REPO_ROOT / "outputs" / "complete-analysis-runs" / run_id / "manifest.json"
    if not resolved.exists():
        raise FileNotFoundError(f"Run manifest not found for run_id={run_id}: {resolved}")
    return resolved


def _resolve_territory_checkpoint_dir(manifest_path: Path, territory: str) -> Path:
    return manifest_path.parent / "territories" / territory / "checkpoints"


def _point_record_id(point_record: dict[str, Any], index: int) -> str:
    return str(point_record.get("point_id") or point_record.get("feature_id") or f"idx-{index}")


def _aggregate_exposure_by_class(
    asset_results: list[dict[str, Any]],
    mapping: dict[str, str],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in asset_results:
        if not isinstance(row, dict):
            continue
        class_key = mapping.get(str(row.get("asset_type") or "").strip().lower())
        if not class_key:
            continue
        out[class_key] = float(out.get(class_key, 0.0)) + _round2(row.get("exposure_eur"))
    return {key: _round2(value) for key, value in out.items()}


def _chunk_indices(indices: list[int], *, chunk_size: int) -> list[list[int]]:
    if chunk_size <= 0:
        return [list(indices)]
    return [indices[start:start + chunk_size] for start in range(0, len(indices), chunk_size)]


def _public_service_key_from_point(point_record: dict[str, Any]) -> str | None:
    network_class_key = str(_network_class_from_point(point_record) or "").strip()
    if network_class_key == "eau_aep":
        return "eau_aep"
    if network_class_key == "eau_eu":
        return "eau_eu"
    if network_class_key.startswith("elec_"):
        return "elec"
    return None


def _service_unit_id_from_point(point_record: dict[str, Any], service_key: str) -> str:
    if service_key == "elec":
        value = str(_electric_native_unit_id_from_point(point_record) or point_record.get("territory_id") or "").strip()
        return value
    value = str(_water_service_feature_id_from_point(point_record) or "").strip()
    return value


def _empty_state_count_row() -> dict[str, int]:
    return {
        "S0": 0,
        "S1": 0,
        "S2": 0,
        "S3": 0,
        "total_units": 0,
    }


def _empty_state_population_row() -> dict[str, float]:
    return {
        "S0": 0.0,
        "S1": 0.0,
        "S2": 0.0,
        "S3": 0.0,
    }


def _service_aliases(service_key: str) -> tuple[str, ...]:
    if service_key == "eau_aep":
        return ("eau_aep", "water_aep")
    if service_key == "eau_eu":
        return ("eau_eu", "water_eu")
    return ("elec",)


def _service_unit_id_from_territory_row(
    row: dict[str, Any],
    *,
    hazard_key: str,
    service_key: str,
) -> str:
    native_states = _safe_dict(row.get("network_states_native"))
    hazard_native = _safe_dict(native_states.get(hazard_key))
    for alias in _service_aliases(service_key):
        unit_payload = _safe_dict(hazard_native.get(alias))
        unit_id = str(unit_payload.get("service_unit_id") or "").strip()
        if unit_id:
            return unit_id
    if service_key == "elec":
        return str(row.get("territory_id") or "").strip()
    return ""


def _aggregate_service_unit_states(
    *,
    point_records: list[dict[str, Any]],
    final_states: np.ndarray,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, int]]]:
    unit_states: dict[str, dict[str, str]] = {service_key: {} for service_key in PUBLIC_SERVICE_KEYS}
    for point_record, state_raw in zip(point_records, final_states, strict=False):
        service_key = _public_service_key_from_point(point_record)
        if service_key is None:
            continue
        unit_id = _service_unit_id_from_point(point_record, service_key)
        if not unit_id:
            continue
        state_code = _state_code(state_raw)
        current = unit_states[service_key].get(unit_id, "S0")
        if _state_severity(state_code) > _state_severity(current):
            unit_states[service_key][unit_id] = state_code
        elif unit_id not in unit_states[service_key]:
            unit_states[service_key][unit_id] = current

    distribution: dict[str, dict[str, int]] = {}
    for service_key in PUBLIC_SERVICE_KEYS:
        counts = _empty_state_count_row()
        for state_code in unit_states[service_key].values():
            normalized = _state_code(state_code)
            counts[normalized] += 1
            counts["total_units"] += 1
        distribution[service_key] = counts
    return unit_states, distribution


def _point_geometry(point_records: list[dict[str, Any]], indices: list[int]) -> dict[str, Any]:
    lons: list[float] = []
    lats: list[float] = []
    for idx in indices:
        rec = point_records[idx]
        try:
            lon = float(rec.get("lon"))
            lat = float(rec.get("lat"))
        except (TypeError, ValueError):
            continue
        lons.append(lon)
        lats.append(lat)
    if not lons or not lats:
        return {"type": "Point", "coordinates": [0.0, 0.0]}
    return {
        "type": "Point",
        "coordinates": [round(float(sum(lons) / len(lons)), 6), round(float(sum(lats) / len(lats)), 6)],
    }


def _electric_cell_geometry(cell_id: str) -> dict[str, Any] | None:
    text = str(cell_id or "").strip()
    if not text.startswith("cell-") or "_" not in text:
        return None
    try:
        lat_text, lon_text = text[5:].split("_", 1)
        lat = float(lat_text)
        lon = float(lon_text)
    except ValueError:
        return None
    half = 0.1 / 2.0
    west = round(lon - half, 6)
    east = round(lon + half, 6)
    south = round(lat - half, 6)
    north = round(lat + half, 6)
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _build_network_states_geojson(
    *,
    territory: str,
    point_records: list[dict[str, Any]],
    scenario_unit_states_by_hazard: dict[str, dict[str, dict[str, dict[str, str]]]],
) -> dict[str, Any]:
    unit_indices: dict[str, dict[str, list[int]]] = {service_key: {} for service_key in PUBLIC_SERVICE_KEYS}
    for idx, point_record in enumerate(point_records):
        service_key = _public_service_key_from_point(point_record)
        if service_key is None:
            continue
        unit_id = _service_unit_id_from_point(point_record, service_key)
        if not unit_id:
            continue
        unit_indices[service_key].setdefault(unit_id, []).append(idx)

    features: list[dict[str, Any]] = []
    layer_key_by_service = {
        "eau_aep": "eau_aep",
        "eau_eu": "eau_eu",
        "elec": "elec_grid_0p1deg",
    }
    for service_key in PUBLIC_SERVICE_KEYS:
        for unit_id, indices in sorted(unit_indices[service_key].items()):
            geometry = (
                _electric_cell_geometry(unit_id)
                if service_key == "elec"
                else None
            ) or _point_geometry(point_records, indices)
            properties: dict[str, Any] = {
                "feature_id": unit_id,
                "service_feature_id": unit_id,
                "zone_component_key": unit_id if service_key in {"eau_aep", "eau_eu"} else None,
                "service_key": service_key,
                "layer_key": layer_key_by_service[service_key],
                "asset_count": len(indices),
            }
            for hazard_key in HAZARD_KEYS:
                for scenario in EVENT_SCENARIOS:
                    state = _state_code(
                        _safe_dict(
                            _safe_dict(
                                _safe_dict(scenario_unit_states_by_hazard.get(hazard_key)).get(scenario)
                            ).get(service_key)
                        ).get(unit_id)
                    )
                    properties[f"state_{scenario}_{hazard_key}"] = state
            features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            })

    return {
        "type": "FeatureCollection",
        "metadata": {
            "territory": territory,
            "state_geometry_mode": "hydraulic_zoning_v2",
            "water_state_geometry_mode": "hydraulic_zoning_v2",
            "water_service_unit": "zone_component_key",
            "electric_state_geometry_mode": "fixed_grid_0p1deg",
            "schema_version": "aggregated_service_state_v1",
            "aggregation_method": "aggregated_service_state",
            "electric_state_unit": "fixed_grid_0p1deg",
            "water_state_unit": "zone_component_key",
            "geometry_semantics": "native_service_geometry",
            "methodology_breaks_comparability": True,
            "source_of_truth": "complete_analysis.scientific_graph_inputs",
            "event_selection_basis": EVENT_SELECTION_BASIS,
            "scenarios": list(EVENT_SCENARIOS),
        },
        "features": features,
    }


def _build_social_outputs_from_service_unit_states(
    *,
    complete_analysis: dict[str, Any],
    scenario_unit_states_by_hazard: dict[str, dict[str, dict[str, dict[str, str]]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    territory_rows = [row for row in _safe_list(complete_analysis.get("territory_results")) if isinstance(row, dict)]
    social_summary: dict[str, Any] = {}
    population_distribution: dict[str, Any] = {}
    social_availability: dict[str, bool] = {}

    for scenario in EVENT_SCENARIOS:
        social_summary[scenario] = {}
        population_distribution[scenario] = {}
        scenario_available = True
        for hazard_key in HAZARD_KEYS:
            state_breakdown = {service_key: _empty_state_population_row() for service_key in PUBLIC_SERVICE_KEYS}
            totals = {
                "total_population_affected_any_network": 0.0,
                "total_without_elec": 0.0,
                "total_without_eau_aep": 0.0,
                "total_without_eau_eu": 0.0,
                "total_without_eau": 0.0,
                "total_with_degraded_elec": 0.0,
                "total_with_degraded_eau_aep": 0.0,
                "total_with_degraded_eau_eu": 0.0,
                "state_breakdown": state_breakdown,
            }
            hazard_unit_states = {
                service_key: dict(
                    _safe_dict(
                        _safe_dict(
                            _safe_dict(scenario_unit_states_by_hazard.get(hazard_key)).get(scenario)
                        ).get(service_key)
                    )
                )
                for service_key in PUBLIC_SERVICE_KEYS
            }
            hazard_available = True
            for row in territory_rows:
                population = float(row.get("population_total") or 0.0)
                if population <= 0.0:
                    continue
                projected_states: dict[str, str] = {}
                for service_key in PUBLIC_SERVICE_KEYS:
                    unit_id = _service_unit_id_from_territory_row(row, hazard_key=hazard_key, service_key=service_key)
                    if not unit_id:
                        hazard_available = False
                        projected_states[service_key] = "S0"
                        continue
                    state_code = _state_code(hazard_unit_states[service_key].get(unit_id))
                    if unit_id not in hazard_unit_states[service_key]:
                        hazard_available = False
                    projected_states[service_key] = state_code
                    state_breakdown[service_key][state_code] += population

                elec_state = projected_states["elec"]
                water_aep_state = projected_states["eau_aep"]
                water_eu_state = projected_states["eau_eu"]
                if elec_state != "S0" or water_aep_state != "S0" or water_eu_state != "S0":
                    totals["total_population_affected_any_network"] += population
                if elec_state == "S3":
                    totals["total_without_elec"] += population
                if water_aep_state == "S3":
                    totals["total_without_eau_aep"] += population
                if water_eu_state == "S3":
                    totals["total_without_eau_eu"] += population
                if elec_state in {"S1", "S2"}:
                    totals["total_with_degraded_elec"] += population
                if water_aep_state in {"S1", "S2"}:
                    totals["total_with_degraded_eau_aep"] += population
                if water_eu_state in {"S1", "S2"}:
                    totals["total_with_degraded_eau_eu"] += population
            totals["total_without_eau"] = _round2(
                float(totals["total_without_eau_aep"]) + float(totals["total_without_eau_eu"])
            )
            social_summary[scenario][hazard_key] = totals
            population_distribution[scenario][hazard_key] = state_breakdown
            scenario_available = scenario_available and hazard_available
        social_availability[scenario] = scenario_available

    return social_summary, population_distribution, social_availability


def _scenario_event_index_at_return_period(losses: np.ndarray, frequencies: np.ndarray, return_period_years: float) -> int:
    vals = np.maximum(np.nan_to_num(np.asarray(losses, dtype=float).reshape(-1), nan=0.0), 0.0)
    freq = np.maximum(np.nan_to_num(np.asarray(frequencies, dtype=float).reshape(-1), nan=0.0), 0.0)
    if vals.size == 0:
        raise ValueError("Cannot resolve return-period event index from an empty event-loss array")
    if freq.size != vals.size or float(freq.sum()) <= 0.0:
        freq = np.full(vals.size, 1.0 / max(1, vals.size), dtype=float)
    order = np.argsort(vals)[::-1]
    exceed = np.cumsum(freq[order])
    target = 1.0 / max(1.0, float(return_period_years))
    sorted_idx = int(np.searchsorted(exceed, target, side="left"))
    sorted_idx = max(0, min(sorted_idx, vals.size - 1))
    return int(order[sorted_idx])


def _load_component_checkpoint_payload(
    *,
    component_root: Path,
    point_id_to_index: dict[str, int],
    point_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    annual_by_point = np.zeros(point_count, dtype=float)
    at_event_loss: np.ndarray | None = None
    event_frequency: np.ndarray | None = None

    result_paths = sorted(component_root.glob("**/results/*.npz"))
    if not result_paths:
        raise FileNotFoundError(f"Missing component checkpoint results under {component_root}")

    seen_points: set[int] = set()
    for result_path in result_paths:
        with np.load(result_path, allow_pickle=False) as payload:
            required = {"eai_direct_by_point", "at_event_loss", "event_frequency", "point_id"}
            missing = sorted(required - set(payload.files))
            if missing:
                raise RuntimeError(f"Incomplete checkpoint {result_path}: missing keys {missing}")

            point_ids = [str(value) for value in list(payload["point_id"])]
            shard_eai = np.asarray(payload["eai_direct_by_point"], dtype=float).reshape(-1)
            if len(point_ids) != shard_eai.size:
                raise RuntimeError(f"Checkpoint point-id mismatch in {result_path}")
            for offset, point_id in enumerate(point_ids):
                point_idx = point_id_to_index.get(point_id)
                if point_idx is None:
                    raise RuntimeError(f"Checkpoint point_id={point_id} is not present in the rebuilt CLIMADA bundle")
                annual_by_point[point_idx] = float(shard_eai[offset])
                seen_points.add(int(point_idx))

            shard_at_event = np.asarray(payload["at_event_loss"], dtype=float).reshape(-1)
            shard_frequency = np.asarray(payload["event_frequency"], dtype=float).reshape(-1)
            if at_event_loss is None:
                at_event_loss = np.zeros_like(shard_at_event, dtype=float)
                event_frequency = shard_frequency
            if shard_at_event.size != at_event_loss.size or shard_frequency.size != at_event_loss.size:
                raise RuntimeError(f"Incompatible event arrays across checkpoints for {component_root}")
            at_event_loss += shard_at_event

    if len(seen_points) != point_count:
        raise RuntimeError(
            f"Checkpoint coverage mismatch for {component_root}: expected {point_count} points, found {len(seen_points)}"
        )
    if at_event_loss is None or event_frequency is None:
        raise RuntimeError(f"No event arrays were loaded from {component_root}")
    return annual_by_point, at_event_loss, event_frequency


def _load_component_shard_point_indices(
    *,
    component_root: Path,
    point_id_to_index: dict[str, int],
) -> list[tuple[str, list[int]]]:
    shard_dirs = sorted(path.parent for path in component_root.glob("**/summary.npz"))
    if not shard_dirs:
        raise FileNotFoundError(f"Missing component shard summaries under {component_root}")

    out: list[tuple[str, list[int]]] = []
    for shard_dir in shard_dirs:
        summary_path = shard_dir / "summary.npz"
        with np.load(summary_path, allow_pickle=False) as payload:
            if "point_id" not in payload.files:
                raise RuntimeError(f"Incomplete shard summary {summary_path}: missing point_id")
            point_ids = [str(value) for value in list(payload["point_id"])]
        indices: list[int] = []
        for point_id in point_ids:
            point_idx = point_id_to_index.get(point_id)
            if point_idx is None:
                raise RuntimeError(
                    f"Shard summary point_id={point_id} is not present in the rebuilt CLIMADA bundle"
                )
            indices.append(int(point_idx))
        out.append((str(shard_dir.name), indices))
    return out


def _chunk_worker_point_indices(point_indices: list[int]) -> list[list[int]]:
    max_points = max(
        1,
        int(os.environ.get("SIB_SCIENTIFIC_WORKER_MAX_POINTS_PER_CHUNK") or WORKER_MAX_POINTS_PER_SHARD),
    )
    if len(point_indices) <= max_points:
        return [point_indices]
    return [point_indices[start : start + max_points] for start in range(0, len(point_indices), max_points)]


def _extract_event_row(imp_mat: Any, event_idx: int, expected_size: int) -> np.ndarray:
    row = imp_mat.getrow(int(event_idx))
    if hasattr(row, "toarray"):
        arr = np.asarray(row.toarray(), dtype=float).reshape(-1)
    else:
        arr = np.asarray(row, dtype=float).reshape(-1)
    if arr.size != expected_size:
        raise RuntimeError(
            f"Unexpected event-row size: got {arr.size}, expected {expected_size} for event_idx={event_idx}"
        )
    return np.maximum(np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0), 0.0)


def _prepare_runtime_context() -> dict[str, Any]:
    runtime = _require_runtime()
    impact_funcs = try_build_climada_impact_funcs()
    if impact_funcs is None:
        raise RuntimeError("Unable to instantiate CLIMADA impact functions for scientific graph rebuild")
    runtime["impfset_wind"] = runtime["ImpactFuncSet"](impact_funcs)
    return runtime


def _build_complete_analysis_context(
    *,
    territory: str,
    manifest: dict[str, Any],
) -> tuple[Any, Any, ClimadaExposureBundle, dict[str, Any]]:
    parameters = _safe_dict(manifest.get("parameters"))
    requested_dynamic_max_tracks = int(
        parameters.get("requested_dynamic_max_tracks")
        if parameters.get("requested_dynamic_max_tracks") is not None
        else parameters.get("dynamic_max_tracks", 0)
    )
    settings = _build_complete_analysis_settings(
        dynamic_max_tracks=requested_dynamic_max_tracks,
        track_sample_manifest_path=(
            str(parameters.get("track_sample_manifest"))
            if parameters.get("track_sample_manifest")
            else None
        ),
        memory_budget_gb=float(parameters.get("memory_budget_gb") or 0.0),
        max_points_per_shard=int(parameters.get("max_points_per_shard") or 0),
        min_points_per_shard=int(parameters.get("min_points_per_shard") or 512),
        allow_degraded_components=bool(parameters.get("allow_degraded_components")),
        scenario=None,
    )
    settings = dataclasses.replace(
        settings,
        hazard_surge_topo_path=resolve_surge_topo_path_for_territory(territory, settings=settings),
    )

    exposure, _ = build_complete_exposure(territory=territory)
    disagg = summarize_disaggregation(
        exposure,
        spacing_m=float(settings.default_sampling_spacing_m),
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=int(settings.climada_max_points_per_feature),
    )
    climada_bundle = prepare_climada_exposure_bundle(exposure, disagg, settings)
    disagg = _reconcile_disaggregation_with_climada_bundle(
        territory_key=territory,
        disagg=disagg,
        point_count_exact=len(climada_bundle.point_records or []),
    )
    return exposure, disagg, climada_bundle, settings


def _build_hazard_bundle(
    *,
    settings: Any,
    point_records: list[dict[str, Any]],
) -> Any:
    point_coords = [
        (float(rec.get("lat")), float(rec.get("lon")))
        for rec in point_records
        if rec.get("lat") is not None and rec.get("lon") is not None
    ]
    if settings.storm_parquet_path and settings.storm_cmcc_parquet_path:
        return load_storm_hazards_from_parquet_for_points(
            storm_parquet_path=Path(settings.storm_parquet_path),
            cmcc_parquet_path=Path(settings.storm_cmcc_parquet_path),
            point_coords=point_coords,
            storm_years=max(1, int(settings.storm_years)),
            max_tracks=int(settings.hazard_dynamic_max_tracks),
            track_cache_max_entries=int(settings.hazard_track_cache_max_entries),
            wind_unit_in=str(settings.storm_wind_unit_in),
            convert_10min_to_1min=bool(settings.storm_convert_10min_to_1min),
            radius_unit_in=str(settings.storm_radius_unit_in),
            env_pressure_hpa=float(settings.storm_env_pressure_hpa),
            build_hazards=False,
        )
    return load_storm_hazards(
        Path(settings.hazard_storm_path),
        Path(settings.hazard_storm_cmcc_path),
        max(1, int(settings.storm_years)),
    )


def _build_component_contexts_for_hazard(
    *,
    runtime: dict[str, Any],
    settings: Any,
    hazard_key: str,
    climada_bundle: ClimadaExposureBundle,
    hazard_bundle: Any,
    requested_components: tuple[str, ...] | None = None,
) -> dict[str, ComponentContext]:
    requested = tuple(requested_components or COMPONENT_NAMES)
    need_rain = "rain" in requested
    need_surge = "surge" in requested

    wind_hazard = getattr(hazard_bundle, hazard_key, None)
    if wind_hazard is None:
        tracks = resolve_hazard_bundle_tracks(hazard_bundle, hazard_key)
        if tracks is None:
            raise RuntimeError(f"Missing dynamic track bundle for {hazard_key}")
        centroids = getattr(hazard_bundle, "centroids", None)
        if centroids is None:
            centroids = _build_centroids_from_points(
                [
                    (float(rec.get("lat")), float(rec.get("lon")))
                    for rec in list(climada_bundle.point_records or [])
                    if rec.get("lat") is not None and rec.get("lon") is not None
                ]
            )
            setattr(hazard_bundle, "centroids", centroids)
        wind_hazard = _build_hazard_from_tracks(tracks, centroids)
        wind_hazard = _normalize_frequency_on_copy(wind_hazard, max(1, int(settings.storm_years)))

    contexts: dict[str, ComponentContext] = {}
    if "wind" in requested:
        contexts["wind"] = ComponentContext(
            hazard_obj=wind_hazard,
            impfset=runtime["impfset_wind"],
            exposure_builder=lambda subset_bundle: subset_bundle.exposures,
        )

    if need_rain or need_surge:
        multi_hazard_model = build_multi_hazard_impact_model(
            surge_haz_type="TCSurgeBathtub",
            rain_haz_type="TR",
            flood_curve_file=Path(settings.d2_flood_curve_file),
            asset_type_to_curve_code=dict(getattr(settings, "flood_asset_type_to_curve_code", None) or {}) or None,
            rain_proxy_base_runoff_coeff=float(settings.multi_hazard_rain_base_runoff_coeff),
        )
        petals_symbols = {
            **load_climada_petals_hazard_symbols("tc_rainfield", "TCRain"),
            **load_climada_petals_hazard_symbols("tc_surge_bathtub", "TCSurgeBathtub"),
        }
        ImpactFuncSet = runtime["ImpactFuncSet"]
        tracks = resolve_hazard_bundle_tracks(hazard_bundle, hazard_key)
        if tracks is None:
            raise RuntimeError(f"Missing dynamic track bundle for {hazard_key}")

        if need_rain:
            TCRain = petals_symbols["TCRain"]
            impfset_rain = ImpactFuncSet(multi_hazard_model.rain_funcs)
            requested_rain_model = str(settings.hazard_rain_model or "R-CLIPER")
            rain_hazard = TCRain.from_tracks(
                tracks,
                centroids=wind_hazard.centroids,
                model=requested_rain_model,
                ignore_distance_to_coast=True,
                max_dist_inland_km=float(settings.hazard_rain_max_dist_inland_km),
            )
            rain_hazard = _normalize_frequency_on_copy(rain_hazard, max(1, int(settings.storm_years)))
            contexts["rain"] = ComponentContext(
                hazard_obj=rain_hazard,
                impfset=impfset_rain,
                exposure_builder=lambda subset_bundle, model=multi_hazard_model: _build_exposure_with_impf_column(
                    subset_bundle.exposures,
                    haz_type=model.rain_haz_type,
                    impf_ids=[
                        resolve_rain_impf_id(rec.get("asset_type"), model)
                        for rec in list(subset_bundle.point_records or [])
                    ],
                ),
            )

        if need_surge:
            TCSurgeBathtub = petals_symbols["TCSurgeBathtub"]
            impfset_surge = ImpactFuncSet(multi_hazard_model.surge_funcs)
            prepared_topo = _prepare_topo_raster_for_exposure(
                Path(settings.hazard_surge_topo_path),
                point_records=list(climada_bundle.point_records or []),
            )
            surge_hazard, _ = _build_surge_hazard(
                runtime["np"],
                surge_hazard_cls=TCSurgeBathtub,
                wind_hazard=wind_hazard,
                topo_path=prepared_topo,
                hazard_source=getattr(hazard_bundle, "source", None),
            )
            surge_hazard = _normalize_frequency_on_copy(surge_hazard, max(1, int(settings.storm_years)))
            contexts["surge"] = ComponentContext(
                hazard_obj=surge_hazard,
                impfset=impfset_surge,
                exposure_builder=lambda subset_bundle, model=multi_hazard_model: _build_exposure_with_impf_column(
                    subset_bundle.exposures,
                    haz_type=model.surge_haz_type,
                    impf_ids=[
                        resolve_surge_impf_id(rec.get("asset_type"), model)
                        for rec in list(subset_bundle.point_records or [])
                    ],
                ),
            )

    return contexts


POINT_LOSS_PAYLOAD_KEY = "__scenario_loss_by_point__"


def _component_worker_output_to_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for class_key, scenario_map in payload.items():
        if class_key == POINT_LOSS_PAYLOAD_KEY:
            out[class_key] = {
                str(scenario): [_round2(value) for value in values]
                for scenario, values in (scenario_map.items() if isinstance(scenario_map, dict) else [])
            }
            continue
        out[str(class_key)] = {
            str(scenario): _round2(value)
            for scenario, value in (scenario_map.items() if isinstance(scenario_map, dict) else [])
        }
    return out


def _compute_component_scenario_totals_worker(
    *,
    territory: str,
    manifest_path: Path,
    hazard_key: str,
    component_name: str,
    event_indices: dict[str, int],
    class_key: str | None = None,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    runtime = _prepare_runtime_context()
    _, _, climada_bundle, settings = _build_complete_analysis_context(
        territory=territory,
        manifest=manifest,
    )
    point_records = list(climada_bundle.point_records or [])
    use_shard_scoped_hazard_bundle = getattr(settings, "hazard_track_sample_manifest_path", None) is not None
    shared_hazard_bundle = None
    if use_shard_scoped_hazard_bundle:
        LOGGER.info(
            "Worker using shard-scoped hazard bundles for prefabricated track sample: hazard=%s component=%s",
            hazard_key,
            component_name,
        )
    else:
        shared_hazard_bundle = _build_hazard_bundle(
            settings=settings,
            point_records=point_records,
        )
    breakdown_class_keys = [_breakdown_class_from_point(rec) for rec in point_records]
    target_classes = (str(class_key),) if class_key else tuple(DAMAGE_BREAKDOWN_LABELS.keys())
    shard_points = _load_component_shard_point_indices(
        component_root=_resolve_territory_checkpoint_dir(manifest_path, territory) / "dynamic-hazard-shards" / hazard_key / component_name,
        point_id_to_index={_point_record_id(rec, idx): idx for idx, rec in enumerate(point_records)},
    )
    out: dict[str, dict[str, float]] = {
        target_class_key: {scenario: 0.0 for scenario in EVENT_SCENARIOS}
        for target_class_key in target_classes
    }
    scenario_loss_by_point_full: dict[str, np.ndarray] = {
        scenario: np.zeros(len(point_records), dtype=float)
        for scenario in EVENT_SCENARIOS
    }
    total_shards = len(shard_points)
    for shard_position, (shard_id, shard_indices) in enumerate(shard_points, start=1):
        LOGGER.info(
            "Worker shard start hazard=%s component=%s shard=%s progress=%s/%s points=%s",
            hazard_key,
            component_name,
            shard_id,
            shard_position,
            total_shards,
            len(shard_indices),
        )
        point_index_chunks = (
            _chunk_worker_point_indices(shard_indices)
            if use_shard_scoped_hazard_bundle
            else [shard_indices]
        )
        for point_indices in point_index_chunks:
            subset_bundle = _subset_bundle_for_indices(base_bundle=climada_bundle, point_indices=point_indices)
            subset_records = list(subset_bundle.point_records or [])
            subset_breakdown_classes = [_breakdown_class_from_point(rec) for rec in subset_records]
            hazard_bundle = (
                _build_hazard_bundle(settings=settings, point_records=subset_records)
                if use_shard_scoped_hazard_bundle
                else shared_hazard_bundle
            )
            if hazard_bundle is None:
                raise RuntimeError(f"Unable to build hazard bundle for {hazard_key}/{component_name}")
            component_contexts = _build_component_contexts_for_hazard(
                runtime=runtime,
                settings=settings,
                hazard_key=hazard_key,
                climada_bundle=subset_bundle,
                hazard_bundle=hazard_bundle,
                requested_components=(component_name,),
            )
            component_rows = _component_event_totals_for_shard(
                runtime=runtime,
                subset_bundle=subset_bundle,
                component_contexts=component_contexts,
                event_indices=event_indices,
            )
            component_payload = component_rows[component_name]
            for target_class_key in target_classes:
                class_mask = np.array([value == target_class_key for value in subset_breakdown_classes], dtype=bool)
                if not class_mask.any():
                    continue
                for scenario in EVENT_SCENARIOS:
                    scenario_loss_by_point = np.asarray(
                        _safe_dict(component_payload.get("scenario_loss_by_point")).get(scenario),
                        dtype=float,
                    ).reshape(-1)
                    if scenario_loss_by_point.size != class_mask.size:
                        raise RuntimeError(
                            f"Scenario loss size mismatch in shard={shard_id} hazard={hazard_key} component={component_name} "
                            f"scenario={scenario}: got {scenario_loss_by_point.size}, expected {class_mask.size}"
                        )
                    scenario_loss_by_point_full[scenario][point_indices] = scenario_loss_by_point
                    out[target_class_key][scenario] += float(scenario_loss_by_point[class_mask].sum())
            del component_rows
            del component_contexts
            if use_shard_scoped_hazard_bundle:
                del hazard_bundle
            elif shared_hazard_bundle is not None and getattr(shared_hazard_bundle, hazard_key, None) is not None:
                setattr(shared_hazard_bundle, hazard_key, None)
            del component_payload
            del subset_records
            del subset_breakdown_classes
            del subset_bundle
            _trim_process_memory()
        LOGGER.info(
            "Worker shard done hazard=%s component=%s shard=%s progress=%s/%s",
            hazard_key,
            component_name,
            shard_id,
            shard_position,
            total_shards,
        )
    for target_class_key in target_classes:
        out[target_class_key] = {
            scenario: _round2(out[target_class_key][scenario])
            for scenario in EVENT_SCENARIOS
        }
        LOGGER.info(
            "Worker class done hazard=%s component=%s class=%s rp10=%.2f rp50=%.2f rp100=%.2f rp1000=%.2f",
            hazard_key,
            component_name,
            target_class_key,
            float(out[target_class_key]["rp10"]),
            float(out[target_class_key]["rp50"]),
            float(out[target_class_key]["rp100"]),
            float(out[target_class_key]["rp1000"]),
        )
    if shared_hazard_bundle is not None:
        release_hazard_bundle_tracks(shared_hazard_bundle, hazard_key)
        del shared_hazard_bundle
    _trim_process_memory()
    out[POINT_LOSS_PAYLOAD_KEY] = {
        scenario: scenario_loss_by_point_full[scenario].tolist()
        for scenario in EVENT_SCENARIOS
    }
    return out


def _run_component_scenario_totals_worker(
    *,
    territory: str,
    manifest_path: Path,
    hazard_key: str,
    component_name: str,
    event_indices: dict[str, int],
    class_key: str | None = None,
    inline: bool = False,
) -> dict[str, Any]:
    if inline:
        LOGGER.info(
            "Worker inline start hazard=%s component=%s class=%s",
            hazard_key,
            component_name,
            class_key or "*",
        )
        return _compute_component_scenario_totals_worker(
            territory=territory,
            manifest_path=manifest_path,
            hazard_key=hazard_key,
            component_name=component_name,
            event_indices=event_indices,
            class_key=class_key,
        )

    with tempfile.NamedTemporaryFile(prefix="sib-component-worker-", suffix=".json", delete=False) as tmp_file:
        out_path = Path(tmp_file.name)
    try:
        started_at = time.monotonic()
        LOGGER.info(
            "Worker start hazard=%s component=%s class=%s scenarios=%s",
            hazard_key,
            component_name,
            class_key or "*",
            ",".join(f"{scenario}:{int(event_indices[scenario])}" for scenario in EVENT_SCENARIOS),
        )
        env = os.environ.copy()
        env.update(
            {
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "VECLIB_MAXIMUM_THREADS": "1",
                "BLIS_NUM_THREADS": "1",
                "OMP_THREAD_LIMIT": "1",
                "MALLOC_ARENA_MAX": "2",
            }
        )
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-component-totals",
                "--territory",
                territory,
                "--manifest-json",
                str(manifest_path),
                "--hazard-key",
                hazard_key,
                "--component-name",
                component_name,
                "--class-key",
                str(class_key or ""),
                "--event-indices-json",
                json.dumps({scenario: int(event_indices[scenario]) for scenario in EVENT_SCENARIOS}),
                "--out-json",
                str(out_path),
            ],
            check=True,
            env=env,
        )
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("Component worker returned a non-object payload")
        result: dict[str, Any] = {}
        for payload_key, scenario_map in payload.items():
            if payload_key == POINT_LOSS_PAYLOAD_KEY:
                result[payload_key] = {
                    str(scenario): [float(value) for value in values]
                    for scenario, values in (scenario_map.items() if isinstance(scenario_map, dict) else [])
                    if isinstance(values, list)
                }
                continue
            result[str(payload_key)] = {
                str(scenario): float(value)
                for scenario, value in (scenario_map.items() if isinstance(scenario_map, dict) else [])
            }
        LOGGER.info(
            "Worker done hazard=%s component=%s class=%s elapsed=%.1fs",
            hazard_key,
            component_name,
            class_key or "*",
            time.monotonic() - started_at,
        )
        return result
    finally:
        if out_path.exists():
            out_path.unlink()


def _subset_bundle_for_indices(
    *,
    base_bundle: ClimadaExposureBundle,
    point_indices: list[int],
) -> ClimadaExposureBundle:
    subset_exposures = base_bundle.exposures.copy(deep=False)
    subset_exposures.set_gdf(
        base_bundle.exposures.gdf.iloc[point_indices].reset_index(drop=True),
        crs=base_bundle.exposures.crs,
    )
    subset_point_records = [base_bundle.point_records[idx] for idx in point_indices]
    return ClimadaExposureBundle(
        exposures=subset_exposures,
        point_records=subset_point_records,
        metric_crs=base_bundle.metric_crs,
        warnings=list(base_bundle.warnings or []),
    )


def _component_event_totals_for_class(
    *,
    runtime: dict[str, Any],
    subset_bundle: ClimadaExposureBundle,
    component_contexts: dict[str, ComponentContext],
    event_indices: dict[str, int],
) -> dict[str, dict[str, Any]]:
    ImpactCalc = runtime["ImpactCalc"]
    out: dict[str, dict[str, Any]] = {}
    for component_name, context in component_contexts.items():
        exposures = context.exposure_builder(subset_bundle)
        impact = ImpactCalc(exposures, context.impfset, context.hazard_obj).impact(
            save_mat=False,
            assign_centroids=True,
        )
        annual_direct = float(np.asarray(getattr(impact, "eai_exp", []), dtype=float).reshape(-1).sum())
        at_event = np.maximum(
            np.nan_to_num(np.asarray(getattr(impact, "at_event", []), dtype=float).reshape(-1), nan=0.0),
            0.0,
        )
        if at_event.size == 0:
            raise RuntimeError(f"Missing at_event totals for component={component_name}")
        scenario_totals = {}
        for scenario, event_idx in event_indices.items():
            if int(event_idx) < 0 or int(event_idx) >= at_event.size:
                raise RuntimeError(
                    f"Scenario event index out of bounds for component={component_name}, "
                    f"scenario={scenario}, event_idx={event_idx}, event_count={at_event.size}"
                )
            scenario_totals[scenario] = float(at_event[int(event_idx)])
        out[component_name] = {
            "annual_direct_total": max(0.0, annual_direct),
            "scenario_totals": scenario_totals,
        }
        del impact
        del exposures
        del at_event
        gc.collect()
    return out


def _hazard_selection_has_zero_fraction(
    hazard_obj: Any,
    selected_event_positions: list[int],
) -> bool:
    fraction = getattr(hazard_obj, "fraction", None)
    if fraction is None or not selected_event_positions:
        return False
    try:
        source_fraction = hazard_obj._get_fraction() if hasattr(hazard_obj, "_get_fraction") else fraction
    except Exception:
        source_fraction = fraction
    if source_fraction is None:
        return False
    try:
        selected_fraction = fraction[selected_event_positions, :]
    except Exception:
        selected_fraction = np.asarray(fraction)[selected_event_positions, :]
    if hasattr(selected_fraction, "eliminate_zeros"):
        selected_fraction.eliminate_zeros()
    nnz = getattr(selected_fraction, "nnz", None)
    if nnz is not None:
        return int(nnz) == 0
    return int(np.count_nonzero(np.asarray(selected_fraction))) == 0


def _record_zero_scenario_losses(
    out: dict[str, dict[str, Any]],
    component_name: str,
    selected_scenarios: list[str],
    point_count: int,
) -> None:
    for scenario in selected_scenarios:
        out[component_name]["scenario_loss_by_point"][scenario] = np.zeros(point_count, dtype=float)


def _component_event_totals_for_shard(
    *,
    runtime: dict[str, Any],
    subset_bundle: ClimadaExposureBundle,
    component_contexts: dict[str, ComponentContext],
    event_indices: dict[str, int],
) -> dict[str, dict[str, Any]]:
    ImpactCalc = runtime["ImpactCalc"]
    out: dict[str, dict[str, Any]] = {}
    point_count = len(list(subset_bundle.point_records or []))
    if point_count <= 0:
        raise RuntimeError("Cannot evaluate a scientific graph rebuild shard without points")

    for component_name, context in component_contexts.items():
        exposures = context.exposure_builder(subset_bundle)
        out[component_name] = {
            "scenario_loss_by_point": {},
        }
        del exposures
        gc.collect()
        full_hazard = context.hazard_obj
        raw_event_ids = getattr(full_hazard, "event_id", None)
        event_ids = [] if raw_event_ids is None else list(raw_event_ids)
        if not event_ids:
            raise RuntimeError(f"Missing event identifiers for component={component_name}")
        selected_event_ids: list[Any] = []
        selected_event_positions: list[int] = []
        selected_scenarios: list[str] = []
        for scenario, event_idx in event_indices.items():
            if int(event_idx) < 0 or int(event_idx) >= len(event_ids):
                raise RuntimeError(
                    f"Scenario event index out of bounds for component={component_name}, "
                    f"scenario={scenario}, event_idx={event_idx}, event_count={len(event_ids)}"
                )
            selected_event_ids.append(event_ids[int(event_idx)])
            selected_event_positions.append(int(event_idx))
            selected_scenarios.append(str(scenario))
        if _hazard_selection_has_zero_fraction(full_hazard, selected_event_positions):
            LOGGER.info(
                "Selected hazard events have zero fraction for component=%s; recording zero scenario losses",
                component_name,
            )
            _record_zero_scenario_losses(out, component_name, selected_scenarios, point_count)
            continue
        try:
            event_hazard = full_hazard.select(event_id=selected_event_ids, reset_frequency=False)
        except RuntimeError as exc:
            if "fraction matrix is zero everywhere" not in str(exc):
                raise
            LOGGER.info(
                "CLIMADA rejected zero-fraction hazard selection for component=%s; recording zero scenario losses",
                component_name,
            )
            _record_zero_scenario_losses(out, component_name, selected_scenarios, point_count)
            continue
        if event_hazard is None:
            raise RuntimeError(
                f"Unable to select event_ids={selected_event_ids!r} for component={component_name}"
            )
        scenario_exposures = context.exposure_builder(subset_bundle)
        impact = ImpactCalc(scenario_exposures, context.impfset, event_hazard).impact(
            save_mat=True,
            assign_centroids=True,
        )
        imp_mat = getattr(impact, "imp_mat", None)
        if imp_mat is None:
            raise RuntimeError(
                f"Missing impact matrix for component={component_name}; strict rebuild requires save_mat=True"
            )
        for row_idx, scenario in enumerate(selected_scenarios):
            out[component_name]["scenario_loss_by_point"][scenario] = _extract_event_row(
                imp_mat,
                row_idx,
                point_count,
            )
        del impact
        del scenario_exposures
        del event_hazard
        gc.collect()
    return out


def _row_from_state_distribution(
    *,
    class_key: str,
    class_label: str,
    state_result: dict[str, Any],
    class_mask: np.ndarray,
    weights_km: np.ndarray,
) -> dict[str, float]:
    total_w = float(weights_km[class_mask].sum())
    if total_w <= 0.0:
        return {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}
    final_state = np.asarray(state_result.get("final_state"), dtype=object).reshape(-1)
    return {
        state: round(
            float(weights_km[class_mask & (final_state == state)].sum()) / total_w * 100.0,
            3,
        )
        for state in ("S0", "S1", "S2", "S3")
    }


def _damage_zone_family_from_breakdown_class(class_key: str | None) -> str | None:
    if not class_key:
        return None
    for family_key, class_keys in DAMAGE_ZONE_FAMILY_CLASS_KEYS.items():
        if class_key in class_keys:
            return family_key
    return None


def _damage_zone_unit_id_from_point(point_record: dict[str, Any], family_key: str) -> str:
    if family_key in {"aep", "eu"}:
        return str(
            point_record.get("service_feature_id")
            or point_record.get("zone_component_key")
            or point_record.get("zone_uid")
            or ""
        ).strip()
    if family_key == "elec":
        return str(_electric_native_unit_id_from_point(point_record) or "").strip()
    return ""


def _damage_zone_label_from_point(point_record: dict[str, Any], family_key: str, unit_id: str) -> str:
    label = str(point_record.get("zone_uid") or point_record.get("label") or "").strip()
    if label:
        return label
    prefix = DAMAGE_ZONE_FAMILY_LABELS.get(family_key, family_key.upper())
    return f"{prefix} - {unit_id}" if unit_id else prefix


def _aggregate_damage_zones_by_scenario(
    *,
    point_records: list[dict[str, Any]],
    values: np.ndarray,
    breakdown_class_keys: list[str | None],
    scenario_direct_loss_by_hazard: dict[str, dict[str, np.ndarray]],
) -> dict[str, dict[str, dict[str, list[dict[str, Any]]]]]:
    point_units: list[tuple[int, str, str] | None] = []
    base_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for idx, point_record in enumerate(point_records):
        class_key = breakdown_class_keys[idx] if idx < len(breakdown_class_keys) else None
        family_key = _damage_zone_family_from_breakdown_class(class_key)
        if family_key is None:
            point_units.append(None)
            continue
        unit_id = _damage_zone_unit_id_from_point(point_record, family_key)
        if not unit_id:
            point_units.append(None)
            continue
        bucket_key = (family_key, unit_id)
        bucket = base_buckets.setdefault(
            bucket_key,
            {
                "family_key": family_key,
                "family_label": DAMAGE_ZONE_FAMILY_LABELS.get(family_key, family_key.upper()),
                "network_kind": DAMAGE_ZONE_FAMILY_NETWORK_KIND.get(family_key, ""),
                "spatial_unit_kind": "fixed_grid_0p1deg" if family_key == "elec" else "hydraulic_zone_component",
                "unit_id": unit_id,
                "zone_component_key": unit_id if family_key in {"aep", "eu"} else "",
                "zone_uid": str(point_record.get("zone_uid") or unit_id).strip(),
                "zone_label": _damage_zone_label_from_point(point_record, family_key, unit_id),
                "exposure_eur": 0.0,
                "point_count": 0,
                "_asset_ids": set(),
            },
        )
        bucket["exposure_eur"] += max(float(values[idx]) if idx < values.size else 0.0, 0.0)
        bucket["point_count"] += 1
        asset_id = str(point_record.get("feature_id") or point_record.get("asset_id") or "").strip()
        if asset_id:
            bucket["_asset_ids"].add(asset_id)
        point_units.append((idx, family_key, unit_id))

    out: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        scenario: {hazard_key: {family_key: [] for family_key in DAMAGE_ZONE_FAMILY_CLASS_KEYS} for hazard_key in HAZARD_KEYS}
        for scenario in SCENARIOS
    }
    if not base_buckets:
        return out

    for scenario in SCENARIOS:
        for hazard_key in HAZARD_KEYS:
            direct_loss = np.minimum(
                np.maximum(np.asarray(scenario_direct_loss_by_hazard[hazard_key][scenario], dtype=float), 0.0),
                values,
            )
            direct_by_bucket = {bucket_key: 0.0 for bucket_key in base_buckets}
            for point_unit in point_units:
                if point_unit is None:
                    continue
                point_idx, family_key, unit_id = point_unit
                if point_idx >= direct_loss.size:
                    continue
                direct_by_bucket[(family_key, unit_id)] += max(float(direct_loss[point_idx]), 0.0)

            for bucket_key, base_bucket in base_buckets.items():
                family_key, _unit_id = bucket_key
                row = {
                    key: value
                    for key, value in base_bucket.items()
                    if key != "_asset_ids"
                }
                row["exposure_eur"] = _round2(row.get("exposure_eur"))
                row["direct_damage_eur"] = _round2(direct_by_bucket.get(bucket_key))
                row["asset_count"] = len(base_bucket.get("_asset_ids") or set())
                out[scenario][hazard_key][family_key].append(row)

    for scenario in SCENARIOS:
        for hazard_key in HAZARD_KEYS:
            for family_key in DAMAGE_ZONE_FAMILY_CLASS_KEYS:
                out[scenario][hazard_key][family_key] = sorted(
                    out[scenario][hazard_key][family_key],
                    key=lambda row: (
                        -float(row.get("direct_damage_eur") or 0.0),
                        str(row.get("unit_id") or ""),
                    ),
                )
    return out


def rebuild_scientific_graph_inputs(
    *,
    territory: str,
    complete_analysis_path: Path,
    manifest_path: Path | None = None,
    inline_workers: bool = False,
) -> dict[str, Any]:
    started_at = time.monotonic()
    LOGGER.info("Scientific rebuild requested territory=%s complete_analysis=%s", territory, complete_analysis_path)
    complete_analysis = _load_json(complete_analysis_path)
    manifest_path = _resolve_manifest_path(
        complete_analysis_path=complete_analysis_path,
        complete_analysis=complete_analysis,
        manifest_path=manifest_path,
    )
    manifest = _load_json(manifest_path)
    territory_key = str(territory or "").strip().lower()
    checkpoint_dir = _resolve_territory_checkpoint_dir(manifest_path, territory_key)
    LOGGER.info(
        "Resolved scientific rebuild inputs territory=%s manifest=%s checkpoints=%s",
        territory_key,
        manifest_path,
        checkpoint_dir,
    )

    LOGGER.info("Building complete-analysis context territory=%s", territory_key)
    _, _, climada_bundle, settings = _build_complete_analysis_context(
        territory=territory_key,
        manifest=manifest,
    )
    LOGGER.info(
        "Complete-analysis context ready territory=%s point_count=%s",
        territory_key,
        len(list(climada_bundle.point_records or [])),
    )

    point_records = list(climada_bundle.point_records or [])
    point_count = len(point_records)
    point_id_to_index = {_point_record_id(rec, idx): idx for idx, rec in enumerate(point_records)}
    values = np.array([float(rec.get("value_eur") or 0.0) for rec in point_records], dtype=float)
    territories = [str(rec.get("territory_id") or "") for rec in point_records]
    network_class_keys = [_network_class_from_point(rec) for rec in point_records]
    breakdown_class_keys = [_breakdown_class_from_point(rec) for rec in point_records]
    water_service_classes = [_water_service_class_from_point(rec) for rec in point_records]
    service_feature_ids = [_water_service_feature_id_from_point(rec) for rec in point_records]
    is_service_network = [_is_water_service_network_point(rec) for rec in point_records]
    is_blocking_asset = [_is_blocking_water_asset_point(rec) for rec in point_records]
    weights_km = np.array(
        [
            float(rec.get("value_eur") or 0.0)
            for rec in point_records
        ],
        dtype=float,
    )
    del climada_bundle
    del settings
    gc.collect()

    existing_graph_inputs = _safe_dict(complete_analysis.get("scientific_graph_inputs"))
    existing_state_tables = _safe_dict(existing_graph_inputs.get("state_damage_tables"))
    existing_breakdowns = _safe_dict(existing_graph_inputs.get("damage_breakdown_by_scenario"))
    portfolio_results = _safe_dict(complete_analysis.get("portfolio_results"))
    asset_results = [row for row in _safe_list(complete_analysis.get("asset_results")) if isinstance(row, dict)]
    network_exposure_by_class = _aggregate_exposure_by_class(asset_results, ASSET_TYPE_TO_NETWORK_CLASS)
    breakdown_exposure_by_class = _aggregate_exposure_by_class(asset_results, ASSET_TYPE_TO_BREAKDOWN_CLASS)
    del asset_results
    del complete_analysis
    gc.collect()

    state_damage_tables: dict[str, list[dict[str, Any]]] = {
        scenario: _safe_list(existing_state_tables.get(scenario))
        for scenario in EVENT_SCENARIOS
    }
    damage_breakdowns: dict[str, dict[str, list[dict[str, Any]]]] = {
        scenario: _safe_dict(existing_breakdowns.get(scenario)) or {"storm": [], "storm_cmcc": []}
        for scenario in EVENT_SCENARIOS
    }

    for hazard_key in HAZARD_KEYS:
        pass

    annual_full_direct_by_hazard: dict[str, np.ndarray] = {}
    scenario_event_indices_by_hazard: dict[str, dict[str, int]] = {}
    scenario_event_loss_by_hazard: dict[str, dict[str, float]] = {}
    annual_direct_by_breakdown_class: dict[str, dict[str, float]] = {}
    annual_scaler_by_hazard: dict[str, float] = {}
    annual_component_totals_by_class: dict[str, dict[str, dict[str, float]]] = {
        hazard_key: {
            class_key: {component: 0.0 for component in COMPONENT_NAMES}
            for class_key in DAMAGE_BREAKDOWN_LABELS.keys()
        }
        for hazard_key in HAZARD_KEYS
    }

    for hazard_key in HAZARD_KEYS:
        combined_at_event: np.ndarray | None = None
        combined_frequency: np.ndarray | None = None
        combined_annual_components = np.zeros(point_count, dtype=float)
        for component_name in COMPONENT_NAMES:
            component_root = checkpoint_dir / "dynamic-hazard-shards" / hazard_key / component_name
            annual_by_point, at_event_loss, event_frequency = _load_component_checkpoint_payload(
                component_root=component_root,
                point_id_to_index=point_id_to_index,
                point_count=point_count,
            )
            combined_annual_components += annual_by_point
            for class_key in DAMAGE_BREAKDOWN_LABELS.keys():
                class_mask = np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)
                annual_component_totals_by_class[hazard_key][class_key][component_name] = float(
                    annual_by_point[class_mask].sum()
                )
            if combined_at_event is None:
                combined_at_event = np.zeros_like(at_event_loss, dtype=float)
                combined_frequency = event_frequency
            if at_event_loss.size != combined_at_event.size or event_frequency.size != combined_at_event.size:
                raise RuntimeError(f"Incompatible event arrays across components for {hazard_key}")
            combined_at_event += at_event_loss

        if combined_at_event is None or combined_frequency is None:
            raise RuntimeError(f"Unable to rebuild event arrays for {hazard_key}")
        annual_full_direct = np.minimum(np.maximum(combined_annual_components, 0.0), values)
        annual_full_direct_by_hazard[hazard_key] = annual_full_direct
        scenario_event_indices_by_hazard[hazard_key] = {
            scenario: _scenario_event_index_at_return_period(
                combined_at_event,
                combined_frequency,
                float(RETURN_PERIOD_BY_SCENARIO[scenario]),
            )
            for scenario in EVENT_SCENARIOS
        }
        scenario_event_loss_by_hazard[hazard_key] = {
            scenario: _round2(combined_at_event[int(scenario_event_indices_by_hazard[hazard_key][scenario])])
            for scenario in EVENT_SCENARIOS
        }
        annual_direct_by_breakdown_class[hazard_key] = {
            class_key: float(annual_full_direct[np.array([ck == class_key for ck in breakdown_class_keys], dtype=bool)].sum())
            for class_key in DAMAGE_BREAKDOWN_LABELS.keys()
        }

        portfolio_row = _safe_dict(portfolio_results.get(hazard_key))
        annual_direct_total = float(portfolio_row.get("eai_direct_eur") or 0.0)
        annual_total = float(portfolio_row.get("eai_eur") or 0.0)
        annual_scaler_by_hazard[hazard_key] = (annual_total / annual_direct_total) if annual_direct_total > 0.0 else 1.0

    class_union = tuple(DAMAGE_BREAKDOWN_LABELS.keys())
    exact_component_totals: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        hazard_key: {
            class_key: {
                scenario: {component: 0.0 for component in COMPONENT_NAMES}
                for scenario in EVENT_SCENARIOS
            }
            for class_key in class_union
        }
        for hazard_key in HAZARD_KEYS
    }
    scenario_direct_loss_by_hazard: dict[str, dict[str, np.ndarray]] = {
        hazard_key: {
            scenario: np.zeros(point_count, dtype=float)
            for scenario in EVENT_SCENARIOS
        }
        for hazard_key in HAZARD_KEYS
    }
    total_worker_tasks = len(HAZARD_KEYS) * len(COMPONENT_NAMES) * len(class_union)
    completed_worker_tasks = 0
    LOGGER.info(
        "Scientific rebuild start territory=%s run_manifest=%s worker_tasks=%s point_count=%s",
        territory_key,
        manifest_path,
        total_worker_tasks,
        point_count,
    )

    del point_id_to_index
    del point_records
    del values
    del territories
    del network_class_keys
    del breakdown_class_keys
    del water_service_classes
    del service_feature_ids
    del is_service_network
    del is_blocking_asset
    del weights_km
    del annual_full_direct_by_hazard
    del annual_direct_by_breakdown_class
    del annual_component_totals_by_class
    gc.collect()

    for hazard_key in HAZARD_KEYS:
        event_indices = scenario_event_indices_by_hazard[hazard_key]
        LOGGER.info(
            "Resolved scenario event indices hazard=%s rp10=%s rp50=%s rp100=%s rp1000=%s",
            hazard_key,
            int(event_indices["rp10"]),
            int(event_indices["rp50"]),
            int(event_indices["rp100"]),
            int(event_indices["rp1000"]),
        )
        for component_name in COMPONENT_NAMES:
            LOGGER.info("Starting hazard=%s component=%s", hazard_key, component_name)
            worker_totals = _run_component_scenario_totals_worker(
                territory=territory_key,
                manifest_path=manifest_path,
                hazard_key=hazard_key,
                component_name=component_name,
                event_indices=event_indices,
                class_key=None,
                inline=bool(inline_workers),
            )
            for class_key in class_union:
                scenario_totals = worker_totals.get(class_key) if isinstance(worker_totals, dict) else None
                for scenario in EVENT_SCENARIOS:
                    exact_component_totals[hazard_key][class_key][scenario][component_name] = _round2(
                        _safe_dict(scenario_totals).get(scenario)
                    )
                completed_worker_tasks += 1
                LOGGER.info(
                    "Progress %s/%s hazard=%s component=%s class=%s rp10=%.2f rp50=%.2f rp100=%.2f rp1000=%.2f",
                    completed_worker_tasks,
                    total_worker_tasks,
                    hazard_key,
                    component_name,
                    class_key,
                    float(exact_component_totals[hazard_key][class_key]["rp10"][component_name]),
                    float(exact_component_totals[hazard_key][class_key]["rp50"][component_name]),
                    float(exact_component_totals[hazard_key][class_key]["rp100"][component_name]),
                    float(exact_component_totals[hazard_key][class_key]["rp1000"][component_name]),
                )
            point_loss_payload = _safe_dict(worker_totals.get(POINT_LOSS_PAYLOAD_KEY))
            for scenario in EVENT_SCENARIOS:
                component_loss_by_point = np.asarray(point_loss_payload.get(scenario), dtype=float).reshape(-1)
                if component_loss_by_point.size != point_count:
                    raise RuntimeError(
                        f"Component point loss size mismatch hazard={hazard_key} component={component_name} "
                        f"scenario={scenario}: got {component_loss_by_point.size}, expected {point_count}"
                    )
                scenario_direct_loss_by_hazard[hazard_key][scenario] += component_loss_by_point
            del worker_totals
            gc.collect()

    LOGGER.info("Rebuilding point metadata after worker phase territory=%s", territory_key)
    _, _, metadata_bundle, metadata_settings = _build_complete_analysis_context(
        territory=territory_key,
        manifest=manifest,
    )
    point_records = list(metadata_bundle.point_records or [])
    if len(point_records) != point_count:
        raise RuntimeError(
            f"Point metadata count changed after worker phase: got {len(point_records)}, expected {point_count}"
        )
    values = np.array([float(rec.get("value_eur") or 0.0) for rec in point_records], dtype=float)
    territories = [str(rec.get("territory_id") or "") for rec in point_records]
    network_class_keys = [_network_class_from_point(rec) for rec in point_records]
    breakdown_class_keys = [_breakdown_class_from_point(rec) for rec in point_records]
    water_service_classes = [_water_service_class_from_point(rec) for rec in point_records]
    service_feature_ids = [_water_service_feature_id_from_point(rec) for rec in point_records]
    is_service_network = [_is_water_service_network_point(rec) for rec in point_records]
    is_blocking_asset = [_is_blocking_water_asset_point(rec) for rec in point_records]
    weights_km = np.array(
        [
            float(rec.get("value_eur") or 0.0)
            for rec in point_records
        ],
        dtype=float,
    )
    del metadata_bundle
    del metadata_settings
    gc.collect()

    scenario_state_results_by_hazard: dict[str, dict[str, dict[str, Any]]] = {hazard: {} for hazard in HAZARD_KEYS}
    network_state_distribution_by_scenario: dict[str, dict[str, dict[str, dict[str, int]]]] = {
        scenario: {hazard_key: {service_key: _empty_state_count_row() for service_key in PUBLIC_SERVICE_KEYS} for hazard_key in HAZARD_KEYS}
        for scenario in EVENT_SCENARIOS
    }
    network_service_unit_counts: dict[str, dict[str, int]] = {
        hazard_key: {service_key: 0 for service_key in PUBLIC_SERVICE_KEYS}
        for hazard_key in HAZARD_KEYS
    }
    scenario_unit_states_by_hazard: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        hazard_key: {scenario: {service_key: {} for service_key in PUBLIC_SERVICE_KEYS} for scenario in EVENT_SCENARIOS}
        for hazard_key in HAZARD_KEYS
    }
    for hazard_key in HAZARD_KEYS:
        for scenario in EVENT_SCENARIOS:
            scenario_direct = np.minimum(
                np.maximum(scenario_direct_loss_by_hazard[hazard_key][scenario], 0.0),
                values,
            )
            scenario_state_results_by_hazard[hazard_key][scenario] = _evaluate_network_dependency_scenario(
                direct_loss=scenario_direct,
                values=values,
                class_keys=network_class_keys,
                territories=territories,
                weights_km=weights_km,
                water_service_classes=water_service_classes,
                service_feature_ids=service_feature_ids,
                is_service_network=is_service_network,
                is_blocking_asset=is_blocking_asset,
            )
            final_states = np.asarray(
                _safe_dict(scenario_state_results_by_hazard[hazard_key][scenario]).get("final_state"),
                dtype=object,
            ).reshape(-1)
            unit_states, unit_distribution = _aggregate_service_unit_states(
                point_records=point_records,
                final_states=final_states,
            )
            scenario_unit_states_by_hazard[hazard_key][scenario] = unit_states
            network_state_distribution_by_scenario[scenario][hazard_key] = unit_distribution
            for service_key in PUBLIC_SERVICE_KEYS:
                network_service_unit_counts[hazard_key][service_key] = max(
                    int(network_service_unit_counts[hazard_key][service_key]),
                    len(unit_states[service_key]),
                )

    complete_analysis = _load_json(complete_analysis_path)
    social_summary_by_scenario, social_population_distribution_by_scenario, social_availability = (
        _build_social_outputs_from_service_unit_states(
            complete_analysis=complete_analysis,
            scenario_unit_states_by_hazard=scenario_unit_states_by_hazard,
        )
    )
    damage_zones_by_scenario = _aggregate_damage_zones_by_scenario(
        point_records=point_records,
        values=values,
        breakdown_class_keys=breakdown_class_keys,
        scenario_direct_loss_by_hazard=scenario_direct_loss_by_hazard,
    )

    for scenario in EVENT_SCENARIOS:
        scenario_rows: list[dict[str, Any]] = []
        breakdown_rows_by_hazard: dict[str, list[dict[str, Any]]] = {"storm": [], "storm_cmcc": []}

        for network_class_key, label in NETWORK_CLASS_LABELS.items():
            row_payload = {"class_key": network_class_key, "class_label": label}
            class_mask = np.array([key == network_class_key for key in network_class_keys], dtype=bool)
            for hazard_key in HAZARD_KEYS:
                direct_total = float(sum(exact_component_totals[hazard_key][network_class_key][scenario].values()))
                scaler = max(0.0, float(annual_scaler_by_hazard[hazard_key]))
                total_damage = _round2(direct_total * scaler)
                component_damage = {
                    component: _round2(float(exact_component_totals[hazard_key][network_class_key][scenario][component]) * scaler)
                    for component in COMPONENT_NAMES[:-1]
                }
                component_damage["landslide"] = 0.0
                direct_damage = _round2(direct_total)
                row_payload[hazard_key] = {
                    "state_pct": _row_from_state_distribution(
                        class_key=network_class_key,
                        class_label=label,
                        state_result=scenario_state_results_by_hazard[hazard_key][scenario],
                        class_mask=class_mask,
                        weights_km=weights_km,
                    ),
                    "exposure_eur": _round2(network_exposure_by_class.get(network_class_key)),
                    "damage_eur": total_damage,
                    "direct_damage_eur": direct_damage,
                    "indirect_damage_eur": _round2(max(total_damage - direct_damage, 0.0)),
                    "damage_components_eur": component_damage,
                }
            scenario_rows.append(row_payload)

        for hazard_key in HAZARD_KEYS:
            scaler = max(0.0, float(annual_scaler_by_hazard[hazard_key]))
            for breakdown_class_key, label in DAMAGE_BREAKDOWN_LABELS.items():
                direct_total = float(sum(exact_component_totals[hazard_key][breakdown_class_key][scenario].values()))
                total_damage = _round2(direct_total * scaler)
                component_damage = {
                    component: _round2(float(exact_component_totals[hazard_key][breakdown_class_key][scenario][component]) * scaler)
                    for component in COMPONENT_NAMES[:-1]
                }
                component_damage["landslide"] = 0.0
                breakdown_rows_by_hazard[hazard_key].append(
                    {
                        "class_key": breakdown_class_key,
                        "class_label": label,
                        "exposure_eur": _round2(breakdown_exposure_by_class.get(breakdown_class_key)),
                        "damage_eur": total_damage,
                        "direct_damage_eur": _round2(direct_total),
                        "indirect_damage_eur": _round2(max(total_damage - direct_total, 0.0)),
                        "damage_components_eur": component_damage,
                    }
                )

        state_damage_tables[scenario] = scenario_rows
        damage_breakdowns[scenario] = breakdown_rows_by_hazard

    availability = _safe_dict(existing_graph_inputs.get("scenario_availability"))
    rebuilt = {
        "source_of_truth": "complete_analysis",
        "event_selection_basis": EVENT_SELECTION_BASIS,
        "event_selection": {
            "basis": EVENT_SELECTION_BASIS,
            "return_period_by_scenario": dict(RETURN_PERIOD_BY_SCENARIO),
            "event_indices_by_hazard": {
                hazard_key: {
                    scenario: int(scenario_event_indices_by_hazard[hazard_key][scenario])
                    for scenario in EVENT_SCENARIOS
                }
                for hazard_key in HAZARD_KEYS
            },
            "event_loss_eur_by_hazard": {
                hazard_key: {
                    scenario: _round2(scenario_event_loss_by_hazard[hazard_key][scenario])
                    for scenario in EVENT_SCENARIOS
                }
                for hazard_key in HAZARD_KEYS
            },
        },
        "scenarios": list(SCENARIOS),
        "state_damage_tables": {
            scenario: _safe_list(state_damage_tables.get(scenario))
            for scenario in SCENARIOS
        },
        "damage_breakdown_by_scenario": {
            scenario: _safe_dict(damage_breakdowns.get(scenario)) or {"storm": [], "storm_cmcc": []}
            for scenario in SCENARIOS
        },
        "damage_zones_by_scenario": {
            scenario: _safe_dict(damage_zones_by_scenario.get(scenario))
            for scenario in SCENARIOS
        },
        "social_impact_by_scenario": {
            scenario: _safe_dict(social_summary_by_scenario.get(scenario))
            for scenario in SCENARIOS
        },
        "social_population_state_distribution_by_scenario": {
            scenario: _safe_dict(social_population_distribution_by_scenario.get(scenario))
            for scenario in SCENARIOS
        },
        "network_state_service_distribution_by_scenario": {
            scenario: _safe_dict(network_state_distribution_by_scenario.get(scenario))
            for scenario in SCENARIOS
        },
        "network_state_service_unit_counts": network_service_unit_counts,
        "scenario_availability": {
            scenario: {
                "state_damage_tables": bool(_safe_list(state_damage_tables.get(scenario))),
                "damage_breakdown_by_scenario": bool(
                    _safe_list(_safe_dict(damage_breakdowns.get(scenario)).get("storm"))
                    or _safe_list(_safe_dict(damage_breakdowns.get(scenario)).get("storm_cmcc"))
                ),
                "social_impact_by_scenario": bool(_safe_dict(social_summary_by_scenario.get(scenario))) and bool(social_availability.get(scenario)),
                "network_states": bool(_safe_dict(network_state_distribution_by_scenario.get(scenario)).get("storm"))
                and bool(_safe_dict(network_state_distribution_by_scenario.get(scenario)).get("storm_cmcc")),
                "damage_zones_by_scenario": all(
                    bool(
                        _safe_list(
                            _safe_dict(
                                _safe_dict(damage_zones_by_scenario.get(scenario)).get(hazard_key)
                            ).get(family_key)
                        )
                    )
                    for hazard_key in HAZARD_KEYS
                    for family_key in DAMAGE_ZONE_FAMILY_CLASS_KEYS
                ),
            }
            for scenario in SCENARIOS
        },
    }

    complete_analysis["scientific_graph_inputs"] = rebuilt
    network_states_geojson = _build_network_states_geojson(
        territory=territory_key,
        point_records=point_records,
        scenario_unit_states_by_hazard=scenario_unit_states_by_hazard,
    )
    network_states_path = complete_analysis_path.parent / f"{territory_key}-network-states.geojson"
    network_states_path.write_text(
        json.dumps(network_states_geojson, ensure_ascii=False),
        encoding="utf-8",
    )
    notes = [str(item).strip() for item in _safe_list(complete_analysis.get("notes")) if str(item).strip()]
    if GRAPH_INPUT_AUTOFILL_NOTE not in notes:
        notes.append(GRAPH_INPUT_AUTOFILL_NOTE)
    complete_analysis["notes"] = notes
    complete_analysis_path.write_text(json.dumps(complete_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info(
        "Scientific rebuild finished territory=%s output=%s elapsed=%.1fs",
        territory_key,
        complete_analysis_path,
        time.monotonic() - started_at,
    )
    return rebuilt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild strict scientific graph inputs for an archived complete-analysis run.")
    parser.add_argument("--territory", required=True)
    parser.add_argument("--complete-analysis-json", default=None)
    parser.add_argument("--manifest-json", default=None)
    parser.add_argument("--worker-component-totals", action="store_true")
    parser.add_argument("--hazard-key", default=None)
    parser.add_argument("--component-name", default=None)
    parser.add_argument("--class-key", default=None)
    parser.add_argument("--event-indices-json", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--inline-workers", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )

    territory = str(args.territory).strip().lower()
    if args.worker_component_totals:
        if not args.manifest_json:
            parser.error("--manifest-json is required with --worker-component-totals")
        if not args.hazard_key:
            parser.error("--hazard-key is required with --worker-component-totals")
        if not args.component_name:
            parser.error("--component-name is required with --worker-component-totals")
        if not args.event_indices_json:
            parser.error("--event-indices-json is required with --worker-component-totals")
        if not args.out_json:
            parser.error("--out-json is required with --worker-component-totals")
        event_indices_payload = json.loads(str(args.event_indices_json))
        if not isinstance(event_indices_payload, dict):
            raise ValueError("--event-indices-json must decode to an object")
        payload = _compute_component_scenario_totals_worker(
            territory=territory,
            manifest_path=Path(args.manifest_json),
            hazard_key=str(args.hazard_key).strip().lower(),
            component_name=str(args.component_name).strip().lower(),
            event_indices={scenario: int(event_indices_payload[scenario]) for scenario in EVENT_SCENARIOS},
            class_key=(str(args.class_key).strip().lower() or None),
        )
        Path(args.out_json).write_text(
            json.dumps(_component_worker_output_to_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0

    if not args.complete_analysis_json:
        parser.error("--complete-analysis-json is required")

    rebuild_scientific_graph_inputs(
        territory=territory,
        complete_analysis_path=Path(args.complete_analysis_json),
        manifest_path=Path(args.manifest_json) if args.manifest_json else None,
        inline_workers=bool(args.inline_workers),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
