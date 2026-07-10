#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import re
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.sensitivity_scenarios import SensitivityScenario, list_scenarios_from_pack


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

SENSITIVITY_OUTPUTS_DIR = REPO_ROOT / "outputs" / "sensitivity-runs"
COMPLETE_ANALYSIS_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
DEFAULT_SCENARIO_PACK = REPO_ROOT / "config" / "sensitivity" / "default-scenario-pack.json"
HAZARD_KEYS = ("storm", "storm_cmcc")
HAZARD_FIELD_PREFIX = {"storm": "storm", "storm_cmcc": "cmcc"}
COMPONENT_ORDER = ("wind", "rain", "surge")
COMPLETE_ANALYSIS_MANIFEST_RE = re.compile(
    r"(?P<path>/home/ubuntu/sib-work/outputs/complete-analysis-runs/[^\s\"']+/manifest\.json)"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _resolve_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("run_id must not be empty")
    if value.lower() != "latest":
        return value
    latest_manifest = SENSITIVITY_OUTPUTS_DIR / "latest-manifest.json"
    payload = _load_json(latest_manifest)
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest sensitivity manifest does not contain a run_id: {latest_manifest}")
    return run_id


def _coerce_float(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        return float("nan")
    return numeric if np.isfinite(numeric) else float("nan")


def _resolve_complete_analysis_path(scenario_entry: dict[str, Any]) -> Path | None:
    explicit_path = str(scenario_entry.get("complete_analysis_json_path") or "").strip()
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            return candidate
        return None
    return None


def _scenario_map(pack_path: Path) -> dict[str, SensitivityScenario]:
    return {scenario.scenario_id: scenario for scenario in list_scenarios_from_pack(pack_path)}


def _scenario_override_text(scenario: SensitivityScenario | None) -> str:
    if scenario is None:
        return "{}"
    return json.dumps(scenario.overrides or {}, ensure_ascii=False, sort_keys=True)


def _matching_combined(payload: dict[str, Any], hazard_key: str) -> dict[str, Any]:
    matching_root = payload.get("matching_qa") if isinstance(payload.get("matching_qa"), dict) else {}
    hazard_block = matching_root.get("hazards") if isinstance(matching_root.get("hazards"), dict) else {}
    hazard_entry = hazard_block.get(hazard_key) if isinstance(hazard_block.get(hazard_key), dict) else {}
    return hazard_entry.get("combined") if isinstance(hazard_entry.get("combined"), dict) else {}


def _matching_components(payload: dict[str, Any], hazard_key: str) -> dict[str, dict[str, Any]]:
    matching_root = payload.get("matching_qa") if isinstance(payload.get("matching_qa"), dict) else {}
    hazard_block = matching_root.get("hazards") if isinstance(matching_root.get("hazards"), dict) else {}
    hazard_entry = hazard_block.get(hazard_key) if isinstance(hazard_block.get(hazard_key), dict) else {}
    components = hazard_entry.get("components") if isinstance(hazard_entry.get("components"), dict) else {}
    return {str(key): value for key, value in components.items() if isinstance(value, dict)}


def _completed_records(parent_manifest: dict[str, Any], pack_path: Path) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    summary_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    scenarios_by_id = _scenario_map(pack_path)

    for scenario_entry in list(parent_manifest.get("scenarios") or []):
        if not isinstance(scenario_entry, dict):
            continue
        scenario_id = str(scenario_entry.get("scenario_id") or "").strip()
        scenario = scenarios_by_id.get(scenario_id)
        status = str(scenario_entry.get("status") or "")
        payload_path = _resolve_complete_analysis_path(scenario_entry) if status == "complete" else None

        summary_row = {
            "parent_run_id": str(parent_manifest.get("run_id") or ""),
            "scenario_id": scenario_id,
            "status": status,
            "label": str(scenario_entry.get("label") or (scenario.label if scenario else scenario_id)),
            "parameter_key": str(scenario_entry.get("parameter_key") or (scenario.parameter_key if scenario else "") or ""),
            "execution_tier": str(scenario_entry.get("execution_tier") or (scenario.execution_tier if scenario else "") or ""),
            "supported": bool(scenario_entry.get("supported", scenario.supported if scenario else False)),
            "started_at": scenario_entry.get("started_at"),
            "completed_at": scenario_entry.get("completed_at"),
            "duration_seconds": scenario_entry.get("duration_seconds"),
            "error": scenario_entry.get("error"),
            "child_run_id": scenario_entry.get("child_run_id"),
            "child_manifest_path": scenario_entry.get("child_manifest_path"),
            "child_status": scenario_entry.get("child_status"),
            "notes": " | ".join(str(value) for value in list(scenario_entry.get("notes") or [])),
            "override_count": len(((scenario.overrides or {}).get("settings") or {}) if scenario else {}),
            "overrides_json": _scenario_override_text(scenario),
            "payload_path": str(payload_path) if payload_path else None,
        }
        summary_rows.append(summary_row)

        if status != "complete":
            continue
        if payload_path is None:
            warnings.append(f"Scenario {scenario_id}: missing complete-analysis payload path")
            continue

        payload = _load_json(payload_path)
        records.append(
            {
                "scenario_entry": scenario_entry,
                "scenario": scenario,
                "payload": payload,
                "payload_path": payload_path,
            }
        )
    return records, warnings, summary_rows


def _build_dataset(records: list[dict[str, Any]]) -> xr.Dataset:
    scenario_ids = [str(record["scenario_entry"].get("scenario_id") or "") for record in records]
    territory_ids = sorted(
        {
            str(row.get("territory_id") or "uploaded-aggregate")
            for record in records
            for row in list(record["payload"].get("territory_results") or [])
            if isinstance(row, dict)
        }
    )
    component_names = []
    for component in COMPONENT_ORDER:
        if any(component in _matching_components(record["payload"], hazard_key) for record in records for hazard_key in HAZARD_KEYS):
            component_names.append(component)
            continue
        if any(
            component in ((record["payload"].get("portfolio_results") or {}).get(hazard_key) or {}).get("components_direct_eai_eur", {})
            for record in records
            for hazard_key in HAZARD_KEYS
        ):
            component_names.append(component)
    if not component_names:
        component_names = list(COMPONENT_ORDER)

    scenario_count = len(records)
    hazard_count = len(HAZARD_KEYS)
    territory_count = len(territory_ids)
    component_count = len(component_names)

    portfolio_shape = (scenario_count, hazard_count)
    territory_shape = (scenario_count, territory_count, hazard_count)
    component_shape = (scenario_count, hazard_count, component_count)
    territory_only_shape = (scenario_count, territory_count)

    portfolio_eai = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_direct = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_indirect = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_percentile_99 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_tvar = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_10 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_20 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_50 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_100 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_200 = np.full(portfolio_shape, np.nan, dtype=float)
    portfolio_pml_1000 = np.full(portfolio_shape, np.nan, dtype=float)
    component_direct_eai = np.full(component_shape, np.nan, dtype=float)
    component_direct_percentile_99 = np.full(component_shape, np.nan, dtype=float)

    territory_eai = np.full(territory_shape, np.nan, dtype=float)
    territory_direct = np.full(territory_shape, np.nan, dtype=float)
    territory_indirect = np.full(territory_shape, np.nan, dtype=float)
    territory_risk_index = np.full(territory_shape, np.nan, dtype=float)
    territory_population = np.full(territory_only_shape, np.nan, dtype=float)
    territory_exposure = np.full(territory_only_shape, np.nan, dtype=float)

    matching_assigned_fraction = np.full(portfolio_shape, np.nan, dtype=float)
    matching_positive_hazard_fraction = np.full(portfolio_shape, np.nan, dtype=float)
    matching_positive_direct_fraction = np.full(portfolio_shape, np.nan, dtype=float)
    matching_positive_hazard_value_fraction = np.full(portfolio_shape, np.nan, dtype=float)
    matching_positive_direct_value_fraction = np.full(portfolio_shape, np.nan, dtype=float)
    matching_distance_mean = np.full(portfolio_shape, np.nan, dtype=float)
    matching_distance_p95 = np.full(portfolio_shape, np.nan, dtype=float)
    matching_distance_max = np.full(portfolio_shape, np.nan, dtype=float)
    matching_component_positive_hazard_fraction = np.full(component_shape, np.nan, dtype=float)
    matching_component_positive_direct_fraction = np.full(component_shape, np.nan, dtype=float)

    scenario_labels = []
    scenario_parameter_keys = []
    scenario_execution_tiers = []
    scenario_child_run_ids = []
    scenario_payload_paths = []
    scenario_override_json = []

    territory_index = {territory_id: idx for idx, territory_id in enumerate(territory_ids)}
    component_index = {component_name: idx for idx, component_name in enumerate(component_names)}

    for scenario_idx, record in enumerate(records):
        scenario_entry = record["scenario_entry"]
        scenario = record.get("scenario")
        payload = record["payload"]
        portfolio_results = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}

        scenario_labels.append(str(scenario_entry.get("label") or (scenario.label if scenario else "")))
        scenario_parameter_keys.append(str(scenario_entry.get("parameter_key") or (scenario.parameter_key if scenario else "") or ""))
        scenario_execution_tiers.append(str(scenario_entry.get("execution_tier") or (scenario.execution_tier if scenario else "") or ""))
        scenario_child_run_ids.append(str(scenario_entry.get("child_run_id") or ""))
        scenario_payload_paths.append(str(record["payload_path"]))
        scenario_override_json.append(_scenario_override_text(scenario))

        for hazard_idx, hazard_key in enumerate(HAZARD_KEYS):
            hazard_portfolio = portfolio_results.get(hazard_key) if isinstance(portfolio_results.get(hazard_key), dict) else {}
            portfolio_eai[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("eai_eur"))
            portfolio_direct[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("eai_direct_eur"))
            portfolio_indirect[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("eai_indirect_eur"))
            portfolio_percentile_99[scenario_idx, hazard_idx] = _coerce_float(
                hazard_portfolio.get("percentile_99_loss_eur", hazard_portfolio.get("max_event_loss_eur"))
            )
            portfolio_tvar[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("tvar_95_eur"))
            portfolio_pml_10[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_10_eur"))
            portfolio_pml_20[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_20_eur"))
            portfolio_pml_50[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_50_eur"))
            portfolio_pml_100[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_100_eur"))
            portfolio_pml_200[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_200_eur"))
            portfolio_pml_1000[scenario_idx, hazard_idx] = _coerce_float(hazard_portfolio.get("pml_1000_eur"))

            component_direct_map = hazard_portfolio.get("components_direct_eai_eur") if isinstance(hazard_portfolio.get("components_direct_eai_eur"), dict) else {}
            component_max_map = hazard_portfolio.get("components_direct_percentile_99_loss_eur") if isinstance(hazard_portfolio.get("components_direct_percentile_99_loss_eur"), dict) else {}
            if not component_max_map:
                component_max_map = hazard_portfolio.get("components_direct_max_event_loss_eur") if isinstance(hazard_portfolio.get("components_direct_max_event_loss_eur"), dict) else {}
            for component_name, component_idx in component_index.items():
                component_direct_eai[scenario_idx, hazard_idx, component_idx] = _coerce_float(component_direct_map.get(component_name))
                component_direct_percentile_99[scenario_idx, hazard_idx, component_idx] = _coerce_float(component_max_map.get(component_name))

            combined_matching = _matching_combined(payload, hazard_key)
            matching_assigned_fraction[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("assigned_point_fraction"))
            matching_positive_hazard_fraction[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("positive_hazard_point_fraction"))
            matching_positive_direct_fraction[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("positive_direct_loss_point_fraction"))
            matching_positive_hazard_value_fraction[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("positive_hazard_value_fraction"))
            matching_positive_direct_value_fraction[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("positive_direct_loss_value_fraction"))
            matching_distance_mean[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("assignment_distance_mean_km"))
            matching_distance_p95[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("assignment_distance_p95_km"))
            matching_distance_max[scenario_idx, hazard_idx] = _coerce_float(combined_matching.get("assignment_distance_max_km"))

            component_matching = _matching_components(payload, hazard_key)
            for component_name, component_idx in component_index.items():
                component_block = component_matching.get(component_name) or {}
                matching_component_positive_hazard_fraction[scenario_idx, hazard_idx, component_idx] = _coerce_float(
                    component_block.get("positive_hazard_point_fraction")
                )
                matching_component_positive_direct_fraction[scenario_idx, hazard_idx, component_idx] = _coerce_float(
                    component_block.get("positive_direct_loss_point_fraction")
                )

        for territory_row in list(payload.get("territory_results") or []):
            if not isinstance(territory_row, dict):
                continue
            territory_id = str(territory_row.get("territory_id") or "uploaded-aggregate")
            if territory_id not in territory_index:
                continue
            territory_idx = territory_index[territory_id]
            territory_population[scenario_idx, territory_idx] = _coerce_float(territory_row.get("population_total"))
            territory_exposure[scenario_idx, territory_idx] = _coerce_float(territory_row.get("exposure_eur"))
            for hazard_idx, hazard_key in enumerate(HAZARD_KEYS):
                prefix = HAZARD_FIELD_PREFIX[hazard_key]
                territory_eai[scenario_idx, territory_idx, hazard_idx] = _coerce_float(territory_row.get(f"eai_{prefix}_eur"))
                territory_direct[scenario_idx, territory_idx, hazard_idx] = _coerce_float(territory_row.get(f"eai_{prefix}_direct_eur"))
                territory_indirect[scenario_idx, territory_idx, hazard_idx] = _coerce_float(territory_row.get(f"eai_{prefix}_indirect_eur"))
                territory_risk_index[scenario_idx, territory_idx, hazard_idx] = _coerce_float(territory_row.get(f"risk_index_{prefix}"))

    return xr.Dataset(
        coords={
            "scenario": scenario_ids,
            "hazard": list(HAZARD_KEYS),
            "territory": territory_ids,
            "component": component_names,
        },
        data_vars={
            "scenario_label": ("scenario", np.asarray(scenario_labels, dtype=str)),
            "scenario_parameter_key": ("scenario", np.asarray(scenario_parameter_keys, dtype=str)),
            "scenario_execution_tier": ("scenario", np.asarray(scenario_execution_tiers, dtype=str)),
            "scenario_child_run_id": ("scenario", np.asarray(scenario_child_run_ids, dtype=str)),
            "scenario_payload_path": ("scenario", np.asarray(scenario_payload_paths, dtype=str)),
            "scenario_overrides_json": ("scenario", np.asarray(scenario_override_json, dtype=str)),
            "portfolio_eai_eur": (("scenario", "hazard"), portfolio_eai),
            "portfolio_eai_direct_eur": (("scenario", "hazard"), portfolio_direct),
            "portfolio_eai_indirect_eur": (("scenario", "hazard"), portfolio_indirect),
            "portfolio_percentile_99_loss_eur": (("scenario", "hazard"), portfolio_percentile_99),
            "portfolio_tvar_95_eur": (("scenario", "hazard"), portfolio_tvar),
            "portfolio_pml_10_eur": (("scenario", "hazard"), portfolio_pml_10),
            "portfolio_pml_20_eur": (("scenario", "hazard"), portfolio_pml_20),
            "portfolio_pml_50_eur": (("scenario", "hazard"), portfolio_pml_50),
            "portfolio_pml_100_eur": (("scenario", "hazard"), portfolio_pml_100),
            "portfolio_pml_200_eur": (("scenario", "hazard"), portfolio_pml_200),
            "portfolio_pml_1000_eur": (("scenario", "hazard"), portfolio_pml_1000),
            "portfolio_component_direct_eai_eur": (("scenario", "hazard", "component"), component_direct_eai),
            "portfolio_component_direct_percentile_99_loss_eur": (("scenario", "hazard", "component"), component_direct_percentile_99),
            "territory_eai_eur": (("scenario", "territory", "hazard"), territory_eai),
            "territory_eai_direct_eur": (("scenario", "territory", "hazard"), territory_direct),
            "territory_eai_indirect_eur": (("scenario", "territory", "hazard"), territory_indirect),
            "territory_risk_index": (("scenario", "territory", "hazard"), territory_risk_index),
            "territory_population_total": (("scenario", "territory"), territory_population),
            "territory_exposure_eur": (("scenario", "territory"), territory_exposure),
            "matching_assigned_point_fraction": (("scenario", "hazard"), matching_assigned_fraction),
            "matching_positive_hazard_point_fraction": (("scenario", "hazard"), matching_positive_hazard_fraction),
            "matching_positive_direct_loss_point_fraction": (("scenario", "hazard"), matching_positive_direct_fraction),
            "matching_positive_hazard_value_fraction": (("scenario", "hazard"), matching_positive_hazard_value_fraction),
            "matching_positive_direct_loss_value_fraction": (("scenario", "hazard"), matching_positive_direct_value_fraction),
            "matching_assignment_distance_mean_km": (("scenario", "hazard"), matching_distance_mean),
            "matching_assignment_distance_p95_km": (("scenario", "hazard"), matching_distance_p95),
            "matching_assignment_distance_max_km": (("scenario", "hazard"), matching_distance_max),
            "matching_component_positive_hazard_point_fraction": (("scenario", "hazard", "component"), matching_component_positive_hazard_fraction),
            "matching_component_positive_direct_loss_point_fraction": (("scenario", "hazard", "component"), matching_component_positive_direct_fraction),
        },
        attrs={
            "generated_at": _utcnow(),
            "territory_scope": "guadeloupe",
            "description": "Sensitivity-analysis matrix exported from complete-analysis payloads.",
        },
    )


def export_sensitivity_run(*, run_id: str, scenario_pack: Path | None = None) -> dict[str, Any]:
    resolved_run_id = _resolve_run_id(run_id)
    parent_manifest_path = SENSITIVITY_OUTPUTS_DIR / resolved_run_id / "manifest.json"
    parent_manifest = _load_json(parent_manifest_path)
    pack_path = Path(scenario_pack or parent_manifest.get("parameters", {}).get("scenario_pack") or DEFAULT_SCENARIO_PACK)
    artifacts_dir = SENSITIVITY_OUTPUTS_DIR / resolved_run_id / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    records, warnings, summary_rows = _completed_records(parent_manifest, pack_path)
    if not records:
        raise ValueError(f"No completed scenario payloads were found for sensitivity run {resolved_run_id}")

    dataset = _build_dataset(records)

    scenario_summary_df = pd.DataFrame(summary_rows)
    completed_scenarios = {str(record["scenario_entry"].get("scenario_id") or "") for record in records}
    portfolio_rows: list[dict[str, Any]] = []
    territory_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    matching_rows: list[dict[str, Any]] = []

    for record in records:
        scenario_entry = record["scenario_entry"]
        scenario = record.get("scenario")
        payload = record["payload"]
        scenario_id = str(scenario_entry.get("scenario_id") or "")
        portfolio_results = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
        matching_root = payload.get("matching_qa") if isinstance(payload.get("matching_qa"), dict) else {}
        matching_hazards = matching_root.get("hazards") if isinstance(matching_root.get("hazards"), dict) else {}

        for hazard_key in HAZARD_KEYS:
            hazard_portfolio = portfolio_results.get(hazard_key) if isinstance(portfolio_results.get(hazard_key), dict) else {}
            portfolio_rows.append(
                {
                    "parent_run_id": resolved_run_id,
                    "scenario_id": scenario_id,
                    "scenario_label": str(scenario_entry.get("label") or (scenario.label if scenario else scenario_id)),
                    "parameter_key": str(scenario_entry.get("parameter_key") or (scenario.parameter_key if scenario else "") or ""),
                    "hazard": hazard_key,
                    "eai_eur": hazard_portfolio.get("eai_eur"),
                    "eai_direct_eur": hazard_portfolio.get("eai_direct_eur"),
                    "eai_indirect_eur": hazard_portfolio.get("eai_indirect_eur"),
                    "percentile_99_loss_eur": hazard_portfolio.get("percentile_99_loss_eur", hazard_portfolio.get("max_event_loss_eur")),
                    "pml_10_eur": hazard_portfolio.get("pml_10_eur"),
                    "pml_20_eur": hazard_portfolio.get("pml_20_eur"),
                    "pml_50_eur": hazard_portfolio.get("pml_50_eur"),
                    "pml_100_eur": hazard_portfolio.get("pml_100_eur"),
                    "pml_200_eur": hazard_portfolio.get("pml_200_eur"),
                    "pml_1000_eur": hazard_portfolio.get("pml_1000_eur"),
                    "tvar_95_eur": hazard_portfolio.get("tvar_95_eur"),
                }
            )

            hazard_matching = matching_hazards.get(hazard_key) if isinstance(matching_hazards.get(hazard_key), dict) else {}
            combined_matching = hazard_matching.get("combined") if isinstance(hazard_matching.get("combined"), dict) else {}
            if combined_matching:
                matching_rows.append(
                    {
                        "parent_run_id": resolved_run_id,
                        "scenario_id": scenario_id,
                        "hazard": hazard_key,
                        "level": "combined",
                        "component": "combined",
                        **combined_matching,
                    }
                )
            component_matching = hazard_matching.get("components") if isinstance(hazard_matching.get("components"), dict) else {}
            for component_name, component_block in component_matching.items():
                if not isinstance(component_block, dict):
                    continue
                matching_rows.append(
                    {
                        "parent_run_id": resolved_run_id,
                        "scenario_id": scenario_id,
                        "hazard": hazard_key,
                        "level": "component",
                        "component": component_name,
                        **component_block,
                    }
                )

        for territory_row in list(payload.get("territory_results") or []):
            if not isinstance(territory_row, dict):
                continue
            territory_rows.append(
                {
                    "parent_run_id": resolved_run_id,
                    "scenario_id": scenario_id,
                    **territory_row,
                }
            )

        for asset_row in list(payload.get("asset_results") or []):
            if not isinstance(asset_row, dict):
                continue
            asset_rows.append(
                {
                    "parent_run_id": resolved_run_id,
                    "scenario_id": scenario_id,
                    **asset_row,
                }
            )

    scenario_summary_csv = artifacts_dir / "scenario-summary.csv"
    scenario_summary_parquet = artifacts_dir / "scenario-summary.parquet"
    portfolio_parquet = artifacts_dir / "portfolio-metrics.parquet"
    territory_parquet = artifacts_dir / "territory-metrics.parquet"
    asset_parquet = artifacts_dir / "asset-metrics.parquet"
    matching_parquet = artifacts_dir / "matching-metrics.parquet"
    matrix_netcdf = artifacts_dir / "sensitivity-matrix.nc"
    summary_json = artifacts_dir / "sensitivity-summary.json"

    scenario_summary_df.to_csv(scenario_summary_csv, index=False)
    scenario_summary_df.to_parquet(scenario_summary_parquet, index=False)
    pd.DataFrame(portfolio_rows).to_parquet(portfolio_parquet, index=False)
    pd.DataFrame(territory_rows).to_parquet(territory_parquet, index=False)
    pd.DataFrame(asset_rows).to_parquet(asset_parquet, index=False)
    pd.DataFrame(matching_rows).to_parquet(matching_parquet, index=False)
    dataset.to_netcdf(matrix_netcdf)

    summary_payload = {
        "generated_at": _utcnow(),
        "parent_run_id": resolved_run_id,
        "parent_manifest_path": str(parent_manifest_path),
        "scenario_pack": str(pack_path),
        "completed_scenario_count": len(records),
        "completed_scenario_ids": sorted(completed_scenarios),
        "warning_count": len(warnings),
        "warnings": warnings,
        "artifacts": {
            "scenario_summary_csv": str(scenario_summary_csv),
            "scenario_summary_parquet": str(scenario_summary_parquet),
            "portfolio_metrics_parquet": str(portfolio_parquet),
            "territory_metrics_parquet": str(territory_parquet),
            "asset_metrics_parquet": str(asset_parquet),
            "matching_metrics_parquet": str(matching_parquet),
            "sensitivity_matrix_netcdf": str(matrix_netcdf),
        },
        "python_examples": {
            "xarray": f"import xarray as xr\nds = xr.load_dataset(r'{matrix_netcdf}')",
            "scenario_summary": f"import pandas as pd\ndf = pd.read_parquet(r'{scenario_summary_parquet}')",
        },
    }
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sensitivity-analysis outputs to Python-friendly matrices")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--scenario-pack", type=Path, default=None)
    args = parser.parse_args()

    summary = export_sensitivity_run(run_id=str(args.run_id), scenario_pack=args.scenario_pack)
    logger.info(
        "Exported sensitivity matrix for %s with %s completed scenarios",
        summary["parent_run_id"],
        summary["completed_scenario_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
