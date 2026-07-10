#!/usr/bin/env python3
"""
Generate sensitivity-analysis graphs from SIB sensitivity runs.

This script is intentionally independent from CLIMADA execution.
It only reads existing sensitivity manifests, logs, complete-analysis manifests,
and complete-analysis JSON payloads.

Main outputs:
- normalized CSV table
- tornado charts

Typical usage:
    python scripts/generate_sensitivity_graphs.py \
        --manifest outputs/sensitivity-runs/latest-manifest.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

import numpy as np
from matplotlib.legend_handler import HandlerTuple
from matplotlib.patches import Patch



REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.sensitivity_scenarios import parameter_traceability
from app.risk_engine.png_label_layout import horizontal_bar_figure_size, place_horizontal_bar_labels

DEFAULT_MANIFEST = REPO_ROOT / "outputs" / "sensitivity-runs" / "latest-manifest.json"

EXCLUDED_SCENARIO_IDS = {
    "vulnerability_curves_profile-manual-profile-required",
    "direct_state_thresholds-10-20-40",
    "health_weights-0-3-1-1-0",
}

METRIC_MAP = {
    "annual": "eai_eur",
    "rp50": "pml_50_eur",
    "rp100": "pml_100_eur",
}

METRIC_LABELS = {
    "annual": "Impact annuel moyen",
    "rp50": "Impact RP50",
    "rp100": "Impact RP100",
}

NETWORK_SERVICES = ("elec", "water_aep", "water_eu")
SERVICE_LABELS = {
    "elec": "Elec",
    "water_aep": "AEP",
    "water_eu": "EU",
}
TERRITORY_LABELS = {
    "guadeloupe": "Guadeloupe",
    "martinique": "Martinique",
    "unknown": "Territoire inconnu",
}
HAZARD_LABELS = {
    "storm": "STORM",
    "storm_cmcc": "STORM_CMCC",
    "wind": "Vent",
    "rain": "Pluie",
    "surge": "Submersion cotiere",
    "landslide": "Mouvement de terrain",
    "unknown": "Alea inconnu",
}
NETWORK_METRICS = {
    "non_nominal_pct": "% réseaux hors Opérationnel (S0)",
    "outage_pct": "% réseaux Hors service (S3)",
}
NETWORK_METRIC_FILENAME_SUFFIXES = {
    "non_nominal_pct": "combined_pct_reseaux_hors_s0",
    "outage_pct": "combined_pct_reseaux_s3",
}
IMPACT_PERIOD_ORDER = ("annual", "rp50", "rp100")
IMPACT_NEGATIVE_COLORS = {
    "annual": "#1d4ed8",
    "rp50": "#3b82f6",
    "rp100": "#93c5fd",
}
IMPACT_POSITIVE_COLORS = {
    "annual": "#ea580c",
    "rp50": "#f97316",
    "rp100": "#fdba74",
}
NETWORK_SERIES_ORDER = (
    ("storm", "elec"),
    ("storm", "water_aep"),
    ("storm", "water_eu"),
    ("storm_cmcc", "elec"),
    ("storm_cmcc", "water_aep"),
    ("storm_cmcc", "water_eu"),
)
NETWORK_SERIES_COLORS = {
    ("storm", "elec"): "#eab308",
    ("storm_cmcc", "elec"): "#fde047",
    ("storm", "water_aep"): "#38bdf8",
    ("storm_cmcc", "water_aep"): "#7dd3fc",
    ("storm", "water_eu"): "#1d4ed8",
    ("storm_cmcc", "water_eu"): "#60a5fa",
}
HAZARD_SERIES_ORDER = ("delta", "storm", "storm_cmcc")
HAZARD_SERIES_COLORS = {
    "delta": "#7c3aed",
    "storm": "#ea580c",
    "storm_cmcc": "#2563eb",
}
PORTFOLIO_HAZARD_SERIES_ORDER = ("storm", "storm_cmcc")
PORTFOLIO_HAZARD_SERIES_COLORS = {
    "storm": "#f97316",
    "storm_cmcc": "#3b82f6",
}
PORTFOLIO_RISK_METRICS = {
    "percentile_99_loss_eur": {"slug": "percentile_99_loss", "label": "Perte percentile 99"},
    "pml_10_eur": {"slug": "pml_10", "label": "PML 10 ans"},
    "pml_20_eur": {"slug": "pml_20", "label": "PML 20 ans"},
    "pml_200_eur": {"slug": "pml_200", "label": "PML 200 ans"},
    "pml_1000_eur": {"slug": "pml_1000", "label": "PML 1000 ans"},
    "tvar_95_eur": {"slug": "tvar_95", "label": "TVaR 95"},
}
SOCIAL_METRIC_SPECS = {
    "population_without_water_aep": {"slug": "without_water_aep", "label": "Population sans eau AEP"},
    "population_without_water_eu": {"slug": "without_water_eu", "label": "Population sans eau EU"},
    "population_with_degraded_elec": {"slug": "degraded_elec", "label": "Population avec électricité dégradée"},
}
SOCIAL_STATE_SPECS = {
    ("elec", "S0"): {"slug": "elec_s0", "label": "Population électricité en Opérationnel (S0)"},
    ("elec", "S1"): {"slug": "elec_s1", "label": "Population électricité en Dégradé (S1)"},
    ("water_aep", "S2"): {"slug": "water_aep_s2", "label": "Population eau AEP en Critique (S2)"},
    ("water_aep", "S3"): {"slug": "water_aep_s3", "label": "Population eau AEP en Hors service (S3)"},
    ("water_eu", "S3"): {"slug": "water_eu_s3", "label": "Population eau EU en Hors service (S3)"},
}
RISK_INDEX_GRAPH_SPECS = {
    "mean": {"slug": "risk_index_mean", "label": "Indice de risque moyen"},
    "max": {"slug": "risk_index_max", "label": "Indice de risque maximal"},
}
SUPER_GRAPH_SIGNIFICANCE_THRESHOLD_PCT = 2.0
SOCIAL_SUPER_GRAPH_SERVICE_ORDER = ("water_aep", "water_eu", "elec")
SOCIAL_SUPER_GRAPH_SERVICE_LABELS = {
    "water_aep": "AEP",
    "water_eu": "EU",
    "elec": "Elec",
}
SOCIAL_SUPER_GRAPH_STATE_ORDER = ("S1", "S2", "S3")
SOCIAL_SUPER_GRAPH_STATE_LABELS = {
    "S1": "Dégradé (S1)",
    "S2": "Critique (S2)",
    "S3": "Hors service (S3)",
}
SUPER_TORNADO_LABEL_SCALE = 2.0

COMPLETE_ANALYSIS_JSON_RE = re.compile(
    r"(?P<path>/[^\s]+outputs/complete-analysis-runs/[^\s]+/territories/[^\s]+/web/data/[^\s]+-complete-analysis\.json)"
)

COMPLETE_ANALYSIS_MANIFEST_RE = re.compile(
    r"(?P<path>/[^\s]+outputs/complete-analysis-runs/[^\s]+/manifest\.json)"
)


@dataclass
class ScenarioPayload:
    scenario_id: str
    scenario_label: str
    parameter_key: str
    status: str
    payload_path: Path
    child_manifest_path: Path | None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_float(value: Any) -> float:
    if value is None:
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def slug_value_to_number(raw_value: str) -> float | None:
    """
    Convert scenario slug values such as:
    - "0-1" -> 0.1
    - "0-05" -> 0.05
    - "1000" -> 1000.0

    Multi-part values like "0-20-50-100" are treated as categorical.
    """
    value = str(raw_value).strip()
    if not value:
        return None

    if re.fullmatch(r"\d+", value):
        return float(value)

    if re.fullmatch(r"\d+-\d+", value):
        left, right = value.split("-", 1)
        return float(f"{left}.{right}")

    return None


def scenario_parameter_value(scenario_id: str, parameter_key: str) -> tuple[str, float | None]:
    if scenario_id == "all-default":
        return "default", None

    prefix = f"{parameter_key}-" if parameter_key else ""
    raw_value = scenario_id[len(prefix):] if prefix and scenario_id.startswith(prefix) else scenario_id

    numeric_value = slug_value_to_number(raw_value)
    return raw_value, numeric_value


def read_log_text(log_path: Path | None) -> str:
    if not log_path:
        return ""
    path = Path(log_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def find_paths_in_log(log_text: str) -> tuple[list[Path], list[Path]]:
    payload_paths = [Path(match.group("path")) for match in COMPLETE_ANALYSIS_JSON_RE.finditer(log_text)]
    manifest_paths = [Path(match.group("path")) for match in COMPLETE_ANALYSIS_MANIFEST_RE.finditer(log_text)]

    # Keep order but remove duplicates.
    payload_paths = list(dict.fromkeys(payload_paths))
    manifest_paths = list(dict.fromkeys(manifest_paths))
    return payload_paths, manifest_paths


def payload_paths_from_child_manifest(child_manifest_path: Path) -> list[Path]:
    if not child_manifest_path.exists():
        return []

    manifest = load_json(child_manifest_path)
    territories = manifest.get("territories")
    if not isinstance(territories, dict):
        return []

    candidates: list[Path] = []

    for territory_name, territory_data in territories.items():
        if not isinstance(territory_data, dict):
            continue

        # Common explicit fields.
        for key in (
            "archived_output_file",
            "output_file",
            "complete_analysis_json",
            "web_payload_path",
            "payload_path",
        ):
            value = territory_data.get(key)
            if value:
                candidates.append(Path(str(value)))

        # Standard archived location.
        run_dir = child_manifest_path.parent
        slug = str(territory_name).lower()
        standard = run_dir / "territories" / slug / "web" / "data" / f"{slug}-complete-analysis.json"
        candidates.append(standard)

    return [path for path in dict.fromkeys(candidates) if path.exists()]


def resolve_scenario_payloads(parent_manifest: dict[str, Any]) -> list[ScenarioPayload]:
    results: list[ScenarioPayload] = []

    for scenario in parent_manifest.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue

        scenario_id = str(scenario.get("scenario_id") or "").strip()
        if not scenario_id or scenario_id in EXCLUDED_SCENARIO_IDS:
            continue

        supported = bool(scenario.get("supported", True))
        if not supported:
            continue

        label = str(scenario.get("label") or scenario_id)
        parameter_key = str(scenario.get("parameter_key") or "")
        status = str(scenario.get("status") or "")
        payload_raw = str(scenario.get("complete_analysis_json_path") or "").strip()
        if not payload_raw:
            raise RuntimeError(
                f"Scenario {scenario_id} is missing complete_analysis_json_path in the sensitivity manifest"
            )
        payload_path = Path(payload_raw)
        if not payload_path.exists():
            raise RuntimeError(
                f"Scenario {scenario_id} references a missing complete-analysis payload: {payload_path}"
            )
        child_manifest_raw = str(scenario.get("child_manifest_path") or "").strip()
        child_manifest_path = Path(child_manifest_raw) if child_manifest_raw and Path(child_manifest_raw).exists() else None
        results.append(
            ScenarioPayload(
                scenario_id=scenario_id,
                scenario_label=label,
                parameter_key=parameter_key,
                status=status,
                payload_path=payload_path,
                child_manifest_path=child_manifest_path,
            )
        )

    return results


def infer_territory_from_payload_path(path: Path) -> str:
    name = path.name.lower()
    if "guadeloupe" in name:
        return "guadeloupe"
    if "martinique" in name:
        return "martinique"

    parts = [part.lower() for part in path.parts]
    for territory in ("guadeloupe", "martinique"):
        if territory in parts:
            return territory

    return "unknown"


def has_any_metric(data: dict[str, Any]) -> bool:
    return any(key in data for key in METRIC_MAP.values())


def iter_metric_blocks(obj: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """
    Recursively find dictionaries containing eai_eur / pml_50_eur / pml_100_eur.

    This avoids depending too strongly on the exact JSON schema.
    """
    blocks: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    if isinstance(obj, dict):
        if has_any_metric(obj):
            blocks.append((path, obj))

        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                blocks.extend(iter_metric_blocks(value, path + (str(key),)))

    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            if isinstance(value, (dict, list)):
                blocks.extend(iter_metric_blocks(value, path + (str(idx),)))

    return blocks


def guess_hazard_from_path(path: tuple[str, ...], block: dict[str, Any]) -> str:
    for explicit_key in ("hazard", "hazard_key", "hazard_id", "name"):
        value = block.get(explicit_key)
        if value:
            return str(value)

    known = {"storm", "storm_cmcc", "cyclone", "wind", "rain", "surge", "landslide"}
    for part in reversed(path):
        if part in known:
            return part
        if part.startswith("storm"):
            return part

    # Fallback: use the nearest meaningful key.
    for part in reversed(path):
        if not part.isdigit() and part not in {"hazards", "portfolio", "summary", "results"}:
            return part

    return "unknown"


def extract_network_states_native(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        safe_dict(payload.get("network_states_native")),
        safe_dict(safe_dict(payload.get("portfolio_results")).get("network_states_native")),
    ]

    territory_results = payload.get("territory_results")
    if isinstance(territory_results, list):
        for territory_row in territory_results:
            if not isinstance(territory_row, dict):
                continue
            candidates.append(safe_dict(territory_row.get("network_states_native")))

    for candidate in candidates:
        if candidate:
            return candidate
    return {}


def summarize_network_state_distribution(distribution: dict[str, Any]) -> tuple[float, float] | None:
    degraded_share = safe_float(distribution.get("degraded_share"))
    state = str(distribution.get("state") or "").strip().upper()
    if not math.isnan(degraded_share):
        degraded_share = max(0.0, degraded_share)
        non_nominal_pct = degraded_share * 100.0 if state != "S0" else 0.0
        outage_pct = degraded_share * 100.0 if state == "S3" else 0.0
        return non_nominal_pct, outage_pct

    weighted_non_nominal = 0.0
    weighted_outage = 0.0
    total_weight = 0.0
    for service_unit in distribution.values():
        service_unit_dict = safe_dict(service_unit)
        unit_share = safe_float(service_unit_dict.get("degraded_share"))
        unit_state = str(service_unit_dict.get("state") or "").strip().upper()
        if math.isnan(unit_share):
            continue
        weight = safe_float(service_unit_dict.get("asset_count"))
        if math.isnan(weight) or weight <= 0.0:
            weight = safe_float(service_unit_dict.get("exposed_asset_count"))
        if math.isnan(weight) or weight <= 0.0:
            weight = 1.0
        unit_share = max(0.0, unit_share)
        total_weight += weight
        if unit_state != "S0":
            weighted_non_nominal += weight * unit_share
        if unit_state == "S3":
            weighted_outage += weight * unit_share

    if total_weight <= 0.0:
        return None

    return (
        weighted_non_nominal / total_weight * 100.0,
        weighted_outage / total_weight * 100.0,
    )


def extract_rows_from_payload(
    scenario_payload: ScenarioPayload,
) -> tuple[list[dict[str, Any]], list[str]]:
    payload = load_json(scenario_payload.payload_path)
    territory = infer_territory_from_payload_path(scenario_payload.payload_path)

    parameter_raw_value, parameter_numeric_value = scenario_parameter_value(
        scenario_payload.scenario_id,
        scenario_payload.parameter_key,
    )

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str, float]] = set()

    def _append_row(
        *,
        hazard: str,
        metric: str,
        return_period: str,
        value: float,
        service: str = "",
        network_metric: str = "",
    ) -> None:
        if math.isnan(value):
            return
        dedup_key = (
            scenario_payload.scenario_id,
            territory,
            hazard,
            metric,
            return_period,
            service,
            network_metric,
            value,
        )
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        rows.append(
            {
                "scenario_id": scenario_payload.scenario_id,
                "scenario_label": scenario_payload.scenario_label,
                "scenario_status": scenario_payload.status,
                "parameter_key": scenario_payload.parameter_key,
                "parameter_value": parameter_raw_value,
                "parameter_value_num": parameter_numeric_value,
                "territory": territory,
                "hazard": hazard,
                "metric": metric,
                "return_period": return_period,
                "value": value,
                "service": service,
                "network_metric": network_metric,
                "payload_path": str(scenario_payload.payload_path),
                "child_manifest_path": str(scenario_payload.child_manifest_path or ""),
            }
        )

    for path, block in iter_metric_blocks(payload):
        hazard = guess_hazard_from_path(path, block)

        # Avoid extracting component-level blocks as main portfolio rows when possible.
        path_text = "/".join(path).lower()
        if "component" in path_text or "matching" in path_text:
            continue

        for return_period, source_key in METRIC_MAP.items():
            value = safe_float(block.get(source_key))
            _append_row(
                hazard=hazard,
                metric="impact_eur",
                return_period=return_period,
                value=value,
            )

    network_states_native = extract_network_states_native(payload)
    if not network_states_native:
        warnings.append(
            "Missing network_states_native; skipping network-state rows for "
            f"{scenario_payload.scenario_id} ({scenario_payload.payload_path})."
        )

    for hazard, service_map in network_states_native.items():
        if not isinstance(service_map, dict):
            continue
        for service in NETWORK_SERVICES:
            distribution = safe_dict(service_map.get(service))
            summarized = summarize_network_state_distribution(distribution)
            if summarized is None:
                continue
            non_nominal_pct, outage_pct = summarized
            _append_row(
                hazard=str(hazard),
                metric="network_state_pct",
                return_period="network_state",
                value=non_nominal_pct,
                service=service,
                network_metric="non_nominal_pct",
            )
            _append_row(
                hazard=str(hazard),
                metric="network_state_pct",
                return_period="network_state",
                value=outage_pct,
                service=service,
                network_metric="outage_pct",
            )

    return rows, warnings


def build_normalized_dataframe(parent_manifest: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    scenario_payloads = resolve_scenario_payloads(parent_manifest)

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for scenario_payload in scenario_payloads:
        scenario_rows, scenario_warnings = extract_rows_from_payload(scenario_payload)
        rows.extend(scenario_rows)
        warnings.extend(scenario_warnings)

    df = pd.DataFrame(rows)

    if df.empty:
        return df, warnings

    # Keep obvious useful hazard rows first. This does not delete unknown rows automatically,
    # because schemas may evolve.
    df = df.sort_values(
        by=["territory", "hazard", "return_period", "parameter_key", "scenario_id"],
        kind="stable",
    ).reset_index(drop=True)

    return df, warnings


def baseline_join_columns(metric: str) -> list[str]:
    if str(metric) == "network_state_pct":
        return ["territory", "hazard", "metric", "return_period", "service", "network_metric"]
    return ["territory", "hazard", "metric", "return_period"]


def add_baseline_deltas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    baseline = df[df["scenario_id"] == "all-default"].copy()
    if baseline.empty:
        df["baseline_value"] = math.nan
        df["delta_abs"] = math.nan
        df["delta_pct"] = math.nan
        return df

    merged_parts: list[pd.DataFrame] = []
    for metric, metric_df in df.groupby("metric", dropna=False):
        join_cols = baseline_join_columns(str(metric))
        baseline_metric = baseline[baseline["metric"] == metric].copy()
        baseline_metric = baseline_metric[join_cols + ["value"]].rename(columns={"value": "baseline_value"})
        merged_parts.append(metric_df.merge(baseline_metric, on=join_cols, how="left"))
    merged = pd.concat(merged_parts, ignore_index=True) if merged_parts else df.copy()

    merged["delta_abs"] = merged["value"] - merged["baseline_value"]
    merged["delta_pct"] = merged.apply(
        lambda row: (row["delta_abs"] / row["baseline_value"] * 100.0)
        if row["baseline_value"] not in (0, None) and not pd.isna(row["baseline_value"])
        else math.nan,
        axis=1,
    )

    return merged


def _stringify_key(row: pd.Series, cols: list[str]) -> str:
    parts = []
    for col in cols:
        parts.append(f"{col}={row.get(col)}")
    return ", ".join(parts)


def build_quality_report(df: pd.DataFrame) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "passed",
        "checks": [],
        "flat_parameters": [],
        "top_sensitive_scenarios": [],
        "alerts": [],
    }
    if df.empty:
        report["status"] = "warning"
        report["alerts"].append("Normalized sensitivity table is empty.")
        return report

    check_statuses: list[str] = []
    for metric in sorted(df["metric"].dropna().astype(str).unique().tolist()):
        join_cols = baseline_join_columns(metric)
        baseline = df[df["scenario_id"] == "all-default"].copy()
        baseline = baseline[baseline["metric"] == metric]
        duplicate_counts = (
            baseline.groupby(join_cols, dropna=False).size().reset_index(name="count")
        )
        duplicates = duplicate_counts[duplicate_counts["count"] > 1].copy()
        status = "passed" if duplicates.empty else "failed"
        check_statuses.append(status)
        report["checks"].append(
            {
                "check": f"baseline_uniqueness::{metric}",
                "status": status,
                "join_columns": join_cols,
                "duplicate_key_count": int(len(duplicates)),
                "examples": duplicates.head(10).to_dict(orient="records"),
            }
        )

    rows_missing_baseline = df[df["baseline_value"].isna()].copy()
    missing_status = "passed" if rows_missing_baseline.empty else "warning"
    check_statuses.append(missing_status)
    report["checks"].append(
        {
            "check": "baseline_value_presence",
            "status": missing_status,
            "row_count": int(len(rows_missing_baseline)),
            "examples": rows_missing_baseline.head(10).to_dict(orient="records"),
        }
    )

    recomputed_delta_abs = df["value"] - df["baseline_value"]
    mismatch_delta_abs = df[
        df["baseline_value"].notna()
        & ((df["delta_abs"] - recomputed_delta_abs).abs() > 1e-9)
    ].copy()
    delta_abs_status = "passed" if mismatch_delta_abs.empty else "failed"
    check_statuses.append(delta_abs_status)
    report["checks"].append(
        {
            "check": "delta_abs_recomputable",
            "status": delta_abs_status,
            "row_count": int(len(mismatch_delta_abs)),
            "examples": mismatch_delta_abs.head(10).to_dict(orient="records"),
        }
    )

    non_default = df[df["scenario_id"] != "all-default"].copy()
    if not non_default.empty:
        flat_summary = (
            non_default.groupby(["metric", "parameter_key"], dropna=False)["delta_abs"]
            .apply(lambda values: float(pd.Series(values).abs().max(skipna=True)))
            .reset_index(name="max_abs_delta")
        )
        flat_rows = flat_summary[flat_summary["max_abs_delta"].fillna(0.0) <= 1e-9]
        report["flat_parameters"] = flat_rows.to_dict(orient="records")

        sensitivity_summary = (
            non_default.groupby(["metric", "scenario_id", "parameter_key"], dropna=False)["delta_abs"]
            .apply(lambda values: float(pd.Series(values).abs().mean(skipna=True)))
            .reset_index(name="mean_abs_delta")
            .sort_values("mean_abs_delta", ascending=False)
        )
        report["top_sensitive_scenarios"] = sensitivity_summary.head(20).to_dict(orient="records")

        network_rows = non_default[non_default["metric"] == "network_state_pct"].copy()
        if not network_rows.empty:
            scenario_flatness = (
                network_rows.groupby("scenario_id")["delta_abs"]
                .apply(lambda values: float(pd.Series(values).abs().max(skipna=True)))
                .reset_index(name="max_abs_delta")
            )
            nearly_flat = scenario_flatness[scenario_flatness["max_abs_delta"].fillna(0.0) <= 1e-9]
            if len(nearly_flat) >= max(3, int(len(scenario_flatness) * 0.8)):
                report["alerts"].append(
                    "Most network-state scenarios are flat after baseline merge; review whether the chosen scenarios truly affect service states."
                )

            binary_rows = network_rows[
                network_rows["value"].fillna(-1).isin([0.0, 100.0])
                & network_rows["baseline_value"].fillna(-1).isin([0.0, 100.0])
            ]
            if len(binary_rows) >= max(10, int(len(network_rows) * 0.8)):
                report["alerts"].append(
                    "Most network-state rows are binary (0 or 100%); validate whether the hazard/service state contract is expected to be all-or-nothing."
                )

    if any(status == "failed" for status in check_statuses):
        report["status"] = "failed"
    elif any(status == "warning" for status in check_statuses) or report["alerts"]:
        report["status"] = "warning"

    return report


def summarize_parameter_traceability(parent_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [parameter_traceability(None)]
    seen: set[str] = set()
    for scenario in parent_manifest.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        parameter_key = str(scenario.get("parameter_key") or "").strip()
        if not parameter_key or parameter_key in seen:
            continue
        seen.add(parameter_key)
        row = parameter_traceability(parameter_key)
        row["scenario_ids"] = sorted(
            str(item.get("scenario_id") or "")
            for item in parent_manifest.get("scenarios", [])
            if isinstance(item, dict) and str(item.get("parameter_key") or "").strip() == parameter_key
        )
        rows.append(row)
    return rows


def safe_filename(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value).strip())
    value = value.strip("_")
    return value or "graph"


def display_territory(territory: str) -> str:
    normalized = str(territory or "").strip().lower()
    return TERRITORY_LABELS.get(normalized, normalized.replace("-", " ").title() or TERRITORY_LABELS["unknown"])


def display_hazard(hazard: str) -> str:
    normalized = str(hazard or "").strip().lower()
    return HAZARD_LABELS.get(normalized, normalized.replace("_", " ").title() or HAZARD_LABELS["unknown"])


def short_scenario_label(row: pd.Series) -> str:
    """Build a compact, non-duplicated label for graph axes."""
    return short_scenario_label_from_values(
        scenario_id=row.get("scenario_id"),
        scenario_label=row.get("scenario_label"),
        parameter_key=row.get("parameter_key"),
        parameter_value=row.get("parameter_value"),
    )


def short_scenario_label_from_values(
    *,
    scenario_id: Any,
    scenario_label: Any,
    parameter_key: Any,
    parameter_value: Any,
) -> str:
    """Build a compact, non-duplicated label for graph axes."""
    scenario_id = str(scenario_id or "").strip()
    scenario_label = str(scenario_label or "").strip()
    parameter_key = str(parameter_key or "").strip()
    parameter_value = str(parameter_value or "").strip()

    if scenario_id == "all-default":
        return "défaut"

    parameter_label = ""
    if parameter_key and parameter_value:
        parameter_label = f"{parameter_key} = {parameter_value}"

    # Candidate labels, ordered from most readable to fallback.
    candidates = [
        parameter_label,
        scenario_label,
        scenario_id,
    ]

    # Remove empty labels and exact duplicates while preserving order.
    unique_labels = []
    seen = set()

    for label in candidates:
        label = str(label).strip()
        if not label:
            continue

        # Normalize for duplicate detection only.
        normalized = (
            label.lower()
            .replace(" ", "")
            .replace("_", "")
            .replace("-", "")
            .replace("=", "")
            .replace(",", ".")
        )

        if normalized in seen:
            continue

        seen.add(normalized)
        unique_labels.append(label)

    if not unique_labels:
        return scenario_id or "scénario"

    # In most graphs, one clear label is enough.
    return unique_labels[0]


def display_scope_label(df: pd.DataFrame) -> str:
    if df.empty or "territory" not in df.columns:
        return "Sensibilité"

    territories = sorted(
        {
            str(value).strip()
            for value in df["territory"].dropna().tolist()
            if str(value).strip()
        }
    )
    if not territories:
        return "Sensibilité"
    if len(territories) == 1:
        return display_territory(territories[0])
    return "Multi-territoires"


def build_scenario_metadata(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["scenario_id", "scenario_label", "parameter_key", "parameter_value"]
    if df.empty or any(column not in df.columns for column in columns):
        return pd.DataFrame(columns=columns + ["scenario_display_label"])

    metadata = (
        df[columns]
        .drop_duplicates(subset=["scenario_id"], keep="first")
        .reset_index(drop=True)
        .copy()
    )
    metadata["scenario_display_label"] = metadata.apply(
        lambda row: short_scenario_label_from_values(
            scenario_id=row.get("scenario_id"),
            scenario_label=row.get("scenario_label"),
            parameter_key=row.get("parameter_key"),
            parameter_value=row.get("parameter_value"),
        ),
        axis=1,
    )
    return metadata


def clean_legacy_outputs(output_dir: Path) -> None:
    curves_dir = output_dir / "curves"
    if curves_dir.exists():
        shutil.rmtree(curves_dir)

    tornado_dir = output_dir / "tornado"
    if tornado_dir.exists():
        legacy_patterns = (
            "tornado_*_storm_annual.png",
            "tornado_*_storm_rp50.png",
            "tornado_*_storm_rp100.png",
            "tornado_*_storm_cmcc_annual.png",
            "tornado_*_storm_cmcc_rp50.png",
            "tornado_*_storm_cmcc_rp100.png",
            "tornado_*_delta_annual.png",
            "tornado_*_delta_annual_rp50_rp100.png",
        )
        for pattern in legacy_patterns:
            for path in tornado_dir.glob(pattern):
                path.unlink(missing_ok=True)

    tornado_network_dir = output_dir / "tornado-network-states"
    if tornado_network_dir.exists():
        for path in tornado_network_dir.glob("tornado_network_states_*.png"):
            path.unlink(missing_ok=True)

    for directory_name, pattern in (
        ("tornado-annual-hazards", "tornado_*.png"),
        ("tornado-portfolio-risk", "tornado_*.png"),
        ("tornado-social-impacts", "tornado_*.png"),
        ("tornado-social-states", "tornado_*.png"),
        ("tornado-super", "tornado_*.png"),
        ("tornado-super", "sensitivity_super_graph_*.png"),
        ("tornado-territory-risk", "tornado_*.png"),
    ):
        directory = output_dir / directory_name
        if not directory.exists():
            continue
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)


def _annotate_horizontal_bars(
    ax: plt.Axes,
    values: np.ndarray,
    y_positions: np.ndarray,
    *,
    suffix: str,
    fontsize: int = 8,
    min_abs_value: float = 0.0,
    decimals: int = 1,
) -> None:
    for value, y_pos in zip(values, y_positions):
        if pd.isna(value):
            continue
        numeric_value = float(value)
        if abs(numeric_value) < min_abs_value:
            continue
        ha = "left" if numeric_value >= 0 else "right"
        if decimals <= 0:
            label_value = f"{numeric_value:+.0f}"
        else:
            label_value = f"{numeric_value:+.{decimals}f}"
        offset_pts = max(5, int(round(fontsize * 0.55)))
        ax.annotate(
            f"{label_value}{suffix}",
            xy=(numeric_value, y_pos),
            xytext=(offset_pts if numeric_value >= 0 else -offset_pts, 0),
            textcoords="offset points",
            va="center",
            ha=ha,
            fontsize=fontsize,
            clip_on=True,
            bbox={"boxstyle": "round,pad=0.16", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
        )


def _horizontal_label_text(value: float, *, suffix: str, decimals: int) -> str:
    if decimals <= 0:
        label_value = f"{float(value):+.0f}"
    else:
        label_value = f"{float(value):+.{decimals}f}"
    return f"{label_value}{suffix}"


def _build_horizontal_label_items(
    values: np.ndarray,
    y_positions: np.ndarray,
    *,
    suffix: str,
    min_abs_value: float = 0.0,
    decimals: int = 1,
) -> list[dict[str, float | str]]:
    items: list[dict[str, float | str]] = []
    for value, y_pos in zip(values, y_positions):
        if pd.isna(value):
            continue
        numeric_value = float(value)
        if abs(numeric_value) < min_abs_value:
            continue
        items.append(
            {
                "value": numeric_value,
                "x": numeric_value,
                "y": float(y_pos),
                "text": _horizontal_label_text(numeric_value, suffix=suffix, decimals=decimals),
            }
        )
    return items


def _set_symmetric_xlim(
    ax: plt.Axes,
    values: list[float],
    *,
    padding_factor: float = 1.18,
    annotation_fontsize: int | None = None,
) -> None:
    finite_values = [abs(float(value)) for value in values if not pd.isna(value)]
    max_abs = max(finite_values, default=0.0)
    if max_abs <= 0.0:
        max_abs = 1.0
    effective_padding = float(padding_factor)
    if annotation_fontsize is not None:
        effective_padding = max(effective_padding, 1.0 + 0.16 + (float(annotation_fontsize) * 0.02))
    ax.set_xlim(-max_abs * effective_padding, max_abs * effective_padding)


def _scenario_tick_fontsize(count: int) -> int:
    if count >= 40:
        return 7
    if count >= 25:
        return 8
    if count >= 14:
        return 9
    return 10


def _scaled_super_annotation_fontsize(base_fontsize: int, count: int) -> int:
    scaled = max(float(base_fontsize) * SUPER_TORNADO_LABEL_SCALE, float(base_fontsize) + 2.0)
    if count >= 38:
        scaled = min(scaled, 10.0)
    elif count >= 28:
        scaled = min(scaled, 11.0)
    elif count >= 18:
        scaled = min(scaled, 12.0)
    else:
        scaled = min(scaled, 14.0)
    return max(9, int(round(scaled)))


def _annotation_fontsize(count: int) -> int:
    if count >= 40:
        return _scaled_super_annotation_fontsize(5, count)
    if count >= 25:
        return _scaled_super_annotation_fontsize(6, count)
    return _scaled_super_annotation_fontsize(7, count)


def _super_graph_height(
    count: int,
    *,
    minimum: float,
    per_scenario: float,
    extra: float,
    annotation_fontsize: int | None = None,
    tick_fontsize: int | None = None,
) -> float:
    scale = 1.0
    if annotation_fontsize is not None:
        scale = max(scale, float(annotation_fontsize) / 7.0)
    if tick_fontsize is not None:
        scale = max(scale, float(tick_fontsize) / 9.0)
    scale = min(scale, 1.35)
    return max(minimum * min(scale, 1.15), (per_scenario * scale) * max(count, 1) + (extra * min(scale, 1.15)))


def _filter_significant_scenarios(
    summary: pd.DataFrame,
    *,
    significance_columns: list[str],
    threshold_pct: float = SUPER_GRAPH_SIGNIFICANCE_THRESHOLD_PCT,
) -> pd.DataFrame:
    if summary.empty or not significance_columns:
        return pd.DataFrame()
    filtered = summary.copy()
    filtered["amplitude"] = filtered[significance_columns].abs().max(axis=1, skipna=True)
    filtered = filtered[
        filtered["amplitude"].notna()
        & (filtered["amplitude"].abs() >= threshold_pct)
    ].copy()
    if filtered.empty:
        return filtered
    return filtered.sort_values("amplitude", ascending=True).reset_index(drop=True)


def _write_super_graph_placeholder(
    output_path: Path,
    *,
    title: str,
    message: str,
    figsize: tuple[float, float],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")
    ax.text(0.5, 0.56, title, ha="center", va="center", fontsize=15, fontweight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.42, message, ha="center", va="center", fontsize=11, transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _draw_super_grouped_bars(
    ax: plt.Axes,
    summary: pd.DataFrame,
    *,
    y_positions: np.ndarray,
    series_columns: list[str],
    series_colors: dict[str, str],
    value_suffix: str,
    annotation_fontsize: int,
    min_annotation_abs: float = 0.0,
    annotation_decimals: int = 1,
) -> tuple[list[float], list[dict[str, float | str]]]:
    all_values: list[float] = []
    label_items: list[dict[str, float | str]] = []
    if not series_columns:
        return all_values, label_items
    bar_height = 0.22 if len(series_columns) <= 3 else 0.14 if len(series_columns) <= 4 else 0.11
    center_offset = (len(series_columns) - 1) / 2.0
    for series_idx, series_column in enumerate(series_columns):
        if series_column not in summary.columns:
            continue
        values = summary[series_column].to_numpy(dtype=float)
        valid_mask = ~pd.isna(values)
        if not valid_mask.any():
            continue
        bar_positions = y_positions[valid_mask] + (series_idx - center_offset) * bar_height
        valid_values = values[valid_mask]
        ax.barh(
            bar_positions,
            valid_values,
            height=bar_height * 0.9,
            color=series_colors[series_column],
        )
        label_items.extend(
            _build_horizontal_label_items(
                valid_values,
                bar_positions,
                suffix=value_suffix,
                min_abs_value=min_annotation_abs,
                decimals=annotation_decimals,
            )
        )
        all_values.extend(valid_values.tolist())
    return all_values, label_items


def _territory_groups(df: pd.DataFrame, fallback_scope_label: str) -> list[tuple[str, str, pd.DataFrame]]:
    if "territory" not in df.columns:
        return [(safe_filename(fallback_scope_label.lower()), fallback_scope_label, df.copy())]

    groups: list[tuple[str, str, pd.DataFrame]] = []
    normalized_fallback = str(fallback_scope_label or "").strip()
    for territory, group in df.groupby("territory", dropna=False):
        territory_key = str(territory or "unknown").strip().lower() or "unknown"
        groups.append((territory_key, display_territory(territory_key), group.copy()))
    if len(groups) == 1 and groups[0][0] == "unknown" and normalized_fallback and normalized_fallback != "Sensibilité":
        return [(safe_filename(normalized_fallback.lower()), normalized_fallback, groups[0][2])]
    return groups or [(safe_filename(fallback_scope_label.lower()), fallback_scope_label, df.copy())]


def build_impact_legend_spec() -> tuple[list[tuple[Patch, Patch]], list[str], str]:
    handles = [
        (
            Patch(color=IMPACT_NEGATIVE_COLORS[return_period]),
            Patch(color=IMPACT_POSITIVE_COLORS[return_period]),
        )
        for return_period in IMPACT_PERIOD_ORDER
    ]
    labels = [METRIC_LABELS[return_period] for return_period in IMPACT_PERIOD_ORDER]
    title = "Temps de retour\n(diminution | augmentation)"
    return handles, labels, title


def load_artifact_table(run_dir: Path, filename: str) -> pd.DataFrame:
    path = run_dir / "artifacts" / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def plot_series_tornado_table(
    table: pd.DataFrame,
    output_dir: Path,
    *,
    series_order: tuple[str, ...],
    series_colors: dict[str, str],
    series_labels: dict[str, str],
    xlabel: str,
    value_suffix: str,
) -> list[Path]:
    output_paths: list[Path] = []
    if table.empty:
        return output_paths

    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = table[
        (table["scenario_id"] != "all-default")
        & table["delta_value"].notna()
        & table["scenario_display_label"].notna()
    ].copy()
    if scenario_df.empty:
        return output_paths

    for (graph_slug, graph_title), group in scenario_df.groupby(
        ["graph_slug", "graph_title"],
        dropna=False,
    ):
        summary = (
            group.pivot_table(
                index="scenario_id",
                columns="series_key",
                values="delta_value",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary.empty:
            continue

        label_map = group.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary = summary.merge(label_map, on="scenario_id", how="left")
        available_series = [series_key for series_key in series_order if series_key in summary.columns]
        if not available_series:
            continue

        summary["amplitude"] = summary[available_series].abs().max(axis=1, skipna=True)
        summary = (
            summary[summary["amplitude"].notna()]
            .sort_values("amplitude", ascending=True)
            .tail(25)
            .reset_index(drop=True)
        )
        if summary.empty:
            continue

        y_positions = np.arange(len(summary), dtype=float)
        bar_height = 0.22 if len(available_series) <= 3 else 0.12
        center_offset = (len(available_series) - 1) / 2
        fig, ax = plt.subplots(figsize=(14, max(4.5, 0.54 * len(summary) + 1)))
        all_values: list[float] = []

        for series_idx, series_key in enumerate(available_series):
            values = summary[series_key].to_numpy(dtype=float)
            valid_mask = ~pd.isna(values)
            if not valid_mask.any():
                continue
            bar_positions = y_positions[valid_mask] + (series_idx - center_offset) * bar_height
            valid_values = values[valid_mask]
            ax.barh(
                bar_positions,
                valid_values,
                height=bar_height * 0.9,
                color=series_colors[series_key],
            )
            _annotate_horizontal_bars(ax, valid_values, bar_positions, suffix=value_suffix, fontsize=7)
            all_values.extend(valid_values.tolist())

        ax.set_yticks(y_positions)
        ax.set_yticklabels(summary["scenario_display_label"])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel(xlabel)
        ax.set_title(str(graph_title))
        ax.grid(True, axis="x", alpha=0.3)
        _set_symmetric_xlim(ax, all_values)

        ax.legend(
            handles=[
                Patch(color=series_colors[series_key], label=series_labels.get(series_key, series_key))
                for series_key in available_series
            ],
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            title="Séries",
        )

        fig.tight_layout(rect=[0, 0, 0.8, 1])
        out_path = output_dir / safe_filename(f"{graph_slug}.png")
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        output_paths.append(out_path)

    return output_paths


def build_delta_annual_tornado_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    scenario_df = df[
        (df["metric"] == "impact_eur")
        & (df["return_period"] == "annual")
        & (df["scenario_id"] != "all-default")
        & df["delta_pct"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
        & df["hazard"].isin(HAZARD_SERIES_ORDER)
    ].copy()
    if scenario_df.empty:
        return pd.DataFrame()

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)
    scenario_df["graph_slug"] = scenario_df["territory"].apply(
        lambda territory: f"tornado_{territory}_annual_all_hazards"
    )
    scenario_df["graph_title"] = scenario_df["territory"].apply(
        lambda territory: f"{display_territory(str(territory))} - Impact annuel moyen par aléa"
    )
    scenario_df["series_key"] = scenario_df["hazard"].astype(str)
    scenario_df["delta_value"] = scenario_df["delta_pct"]
    return scenario_df[
        ["graph_slug", "graph_title", "scenario_id", "scenario_display_label", "series_key", "delta_value"]
    ].copy()


def build_portfolio_risk_tornado_table(
    portfolio_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
) -> pd.DataFrame:
    if portfolio_df.empty:
        return pd.DataFrame()

    baseline = portfolio_df[portfolio_df["scenario_id"] == "all-default"].copy()
    if baseline.empty:
        return pd.DataFrame()
    baseline = baseline.set_index("hazard")

    rows: list[dict[str, Any]] = []
    for _, row in portfolio_df[portfolio_df["scenario_id"] != "all-default"].iterrows():
        hazard = str(row.get("hazard") or "").strip()
        if hazard not in baseline.index:
            continue
        baseline_row = baseline.loc[hazard]
        for metric_name, spec in PORTFOLIO_RISK_METRICS.items():
            baseline_value = safe_float(baseline_row.get(metric_name))
            value = safe_float(row.get(metric_name))
            if math.isnan(value) or math.isnan(baseline_value) or baseline_value == 0.0:
                continue
            rows.append(
                {
                    "scenario_id": row.get("scenario_id"),
                    "graph_slug": f"tornado_portfolio_{spec['slug']}",
                    "graph_title": f"{scope_label} - Portefeuille - {spec['label']}",
                    "series_key": hazard,
                    "delta_value": (value - baseline_value) / baseline_value * 100.0,
                }
            )

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows).merge(
        scenario_metadata[["scenario_id", "scenario_display_label"]],
        on="scenario_id",
        how="left",
    )
    table["scenario_display_label"] = table["scenario_display_label"].fillna(table["scenario_id"])
    return table


def build_social_metric_tornado_table(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
) -> pd.DataFrame:
    if territory_df.empty or "social_metrics" not in territory_df.columns:
        return pd.DataFrame()

    raw_rows: list[dict[str, Any]] = []
    for _, row in territory_df.iterrows():
        social_metrics = row.get("social_metrics")
        if not isinstance(social_metrics, dict):
            continue
        for hazard, hazard_metrics in social_metrics.items():
            if not isinstance(hazard_metrics, dict):
                continue
            for metric_name in SOCIAL_METRIC_SPECS:
                value = safe_float(hazard_metrics.get(metric_name))
                if math.isnan(value):
                    continue
                raw_rows.append(
                    {
                        "scenario_id": row.get("scenario_id"),
                        "hazard": str(hazard),
                        "metric_name": metric_name,
                        "value": value,
                    }
                )

    if not raw_rows:
        return pd.DataFrame()

    aggregated = (
        pd.DataFrame(raw_rows)
        .groupby(["scenario_id", "hazard", "metric_name"], dropna=False)["value"]
        .sum()
        .reset_index()
    )
    baseline = aggregated[aggregated["scenario_id"] == "all-default"].set_index(["hazard", "metric_name"])
    rows: list[dict[str, Any]] = []
    for _, row in aggregated[aggregated["scenario_id"] != "all-default"].iterrows():
        key = (row["hazard"], row["metric_name"])
        if key not in baseline.index:
            continue
        baseline_value = safe_float(baseline.loc[key]["value"])
        value = safe_float(row["value"])
        spec = SOCIAL_METRIC_SPECS[str(row["metric_name"])]
        rows.append(
            {
                "scenario_id": row["scenario_id"],
                "graph_slug": f"tornado_social_{spec['slug']}",
                "graph_title": f"{scope_label} - {spec['label']}",
                "series_key": str(row["hazard"]),
                "delta_value": value - baseline_value,
            }
        )

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows).merge(
        scenario_metadata[["scenario_id", "scenario_display_label"]],
        on="scenario_id",
        how="left",
    )
    table["scenario_display_label"] = table["scenario_display_label"].fillna(table["scenario_id"])
    return table


def build_social_state_tornado_table(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
) -> pd.DataFrame:
    if territory_df.empty or "social_impact_population_state_distribution" not in territory_df.columns:
        return pd.DataFrame()

    raw_rows: list[dict[str, Any]] = []
    for _, row in territory_df.iterrows():
        distribution = row.get("social_impact_population_state_distribution")
        if not isinstance(distribution, dict):
            continue
        for hazard, service_map in distribution.items():
            if not isinstance(service_map, dict):
                continue
            for (service, state), spec in SOCIAL_STATE_SPECS.items():
                service_distribution = safe_dict(service_map.get(service))
                value = safe_float(service_distribution.get(state))
                if math.isnan(value):
                    continue
                raw_rows.append(
                    {
                        "scenario_id": row.get("scenario_id"),
                        "hazard": str(hazard),
                        "service": service,
                        "state": state,
                        "metric_slug": spec["slug"],
                        "metric_label": spec["label"],
                        "value": value,
                    }
                )

    if not raw_rows:
        return pd.DataFrame()

    aggregated = (
        pd.DataFrame(raw_rows)
        .groupby(["scenario_id", "hazard", "service", "state", "metric_slug", "metric_label"], dropna=False)["value"]
        .sum()
        .reset_index()
    )
    baseline = aggregated[aggregated["scenario_id"] == "all-default"].set_index(["hazard", "service", "state"])
    rows: list[dict[str, Any]] = []
    for _, row in aggregated[aggregated["scenario_id"] != "all-default"].iterrows():
        key = (row["hazard"], row["service"], row["state"])
        if key not in baseline.index:
            continue
        baseline_value = safe_float(baseline.loc[key]["value"])
        value = safe_float(row["value"])
        rows.append(
            {
                "scenario_id": row["scenario_id"],
                "graph_slug": f"tornado_social_state_{row['metric_slug']}",
                "graph_title": f"{scope_label} - {row['metric_label']}",
                "series_key": str(row["hazard"]),
                "delta_value": value - baseline_value,
            }
        )

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows).merge(
        scenario_metadata[["scenario_id", "scenario_display_label"]],
        on="scenario_id",
        how="left",
    )
    table["scenario_display_label"] = table["scenario_display_label"].fillna(table["scenario_id"])
    return table


def build_social_state_super_graph_table(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
) -> pd.DataFrame:
    if territory_df.empty or "social_impact_population_state_distribution" not in territory_df.columns:
        return pd.DataFrame()

    raw_rows: list[dict[str, Any]] = []
    for _, row in territory_df.iterrows():
        distribution = row.get("social_impact_population_state_distribution")
        if not isinstance(distribution, dict):
            continue
        territory = str(row.get("territory") or "").strip().lower() or "unknown"
        for hazard, service_map in distribution.items():
            if not isinstance(service_map, dict):
                continue
            for service in SOCIAL_SUPER_GRAPH_SERVICE_ORDER:
                service_distribution = safe_dict(service_map.get(service))
                for state in SOCIAL_SUPER_GRAPH_STATE_ORDER:
                    value = safe_float(service_distribution.get(state))
                    if math.isnan(value):
                        continue
                    raw_rows.append(
                        {
                            "scenario_id": row.get("scenario_id"),
                            "territory": territory,
                            "hazard": str(hazard),
                            "service": service,
                            "state": state,
                            "value": value,
                        }
                    )

    if not raw_rows:
        return pd.DataFrame()

    aggregated = (
        pd.DataFrame(raw_rows)
        .groupby(["scenario_id", "territory", "hazard", "service", "state"], dropna=False)["value"]
        .sum()
        .reset_index()
    )
    baseline = aggregated[aggregated["scenario_id"] == "all-default"].set_index(["territory", "hazard", "service", "state"])
    rows: list[dict[str, Any]] = []
    for _, row in aggregated[aggregated["scenario_id"] != "all-default"].iterrows():
        key = (row["territory"], row["hazard"], row["service"], row["state"])
        if key not in baseline.index:
            continue
        baseline_value = safe_float(baseline.loc[key]["value"])
        value = safe_float(row["value"])
        delta_abs = value - baseline_value
        delta_pct = (
            (delta_abs / baseline_value) * 100.0
            if not math.isnan(baseline_value) and baseline_value != 0.0
            else math.nan
        )
        rows.append(
            {
                "scenario_id": row["scenario_id"],
                "territory": row["territory"],
                "hazard": row["hazard"],
                "service": row["service"],
                "state": row["state"],
                "delta_value": delta_abs,
                "delta_pct_filter": delta_pct,
            }
        )

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows).merge(
        scenario_metadata[["scenario_id", "scenario_display_label"]],
        on="scenario_id",
        how="left",
    )
    table["scenario_display_label"] = table["scenario_display_label"].fillna(table["scenario_id"])
    return table


def build_risk_index_tornado_table(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
) -> pd.DataFrame:
    if territory_df.empty:
        return pd.DataFrame()

    aggregated = (
        territory_df.groupby("scenario_id", dropna=False)
        .agg(
            risk_index_storm_mean=("risk_index_storm", "mean"),
            risk_index_storm_max=("risk_index_storm", "max"),
            risk_index_cmcc_mean=("risk_index_cmcc", "mean"),
            risk_index_cmcc_max=("risk_index_cmcc", "max"),
        )
        .reset_index()
    )
    baseline_df = aggregated[aggregated["scenario_id"] == "all-default"]
    if baseline_df.empty:
        return pd.DataFrame()
    baseline_row = baseline_df.iloc[0]

    rows: list[dict[str, Any]] = []
    column_specs = {
        "storm": {"mean": "risk_index_storm_mean", "max": "risk_index_storm_max"},
        "storm_cmcc": {"mean": "risk_index_cmcc_mean", "max": "risk_index_cmcc_max"},
    }
    for _, row in aggregated[aggregated["scenario_id"] != "all-default"].iterrows():
        for hazard, hazard_columns in column_specs.items():
            for graph_kind, graph_spec in RISK_INDEX_GRAPH_SPECS.items():
                column_name = hazard_columns[graph_kind]
                baseline_value = safe_float(baseline_row.get(column_name))
                value = safe_float(row.get(column_name))
                if math.isnan(value) or math.isnan(baseline_value) or baseline_value == 0.0:
                    continue
                rows.append(
                    {
                        "scenario_id": row["scenario_id"],
                        "graph_slug": f"tornado_{graph_spec['slug']}",
                        "graph_title": f"{scope_label} - {graph_spec['label']}",
                        "series_key": hazard,
                        "delta_value": (value - baseline_value) / baseline_value * 100.0,
                    }
                )

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows).merge(
        scenario_metadata[["scenario_id", "scenario_display_label"]],
        on="scenario_id",
        how="left",
    )
    table["scenario_display_label"] = table["scenario_display_label"].fillna(table["scenario_id"])
    return table


def plot_delta_annual_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    table = build_delta_annual_tornado_table(df)
    return plot_series_tornado_table(
        table,
        output_dir / "tornado-annual-hazards",
        series_order=HAZARD_SERIES_ORDER,
        series_colors=HAZARD_SERIES_COLORS,
        series_labels={hazard: display_hazard(hazard) for hazard in HAZARD_SERIES_ORDER},
        xlabel="Variation par rapport au cas de reference (%)",
        value_suffix="%",
    )


def plot_portfolio_risk_tornado(
    portfolio_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
    output_dir: Path,
) -> list[Path]:
    table = build_portfolio_risk_tornado_table(portfolio_df, scenario_metadata, scope_label)
    return plot_series_tornado_table(
        table,
        output_dir / "tornado-portfolio-risk",
        series_order=PORTFOLIO_HAZARD_SERIES_ORDER,
        series_colors=PORTFOLIO_HAZARD_SERIES_COLORS,
        series_labels={hazard: display_hazard(hazard) for hazard in PORTFOLIO_HAZARD_SERIES_ORDER},
        xlabel="Variation par rapport au cas de reference (%)",
        value_suffix="%",
    )


def plot_social_metric_tornado(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
    output_dir: Path,
) -> list[Path]:
    table = build_social_metric_tornado_table(territory_df, scenario_metadata, scope_label)
    return plot_series_tornado_table(
        table,
        output_dir / "tornado-social-impacts",
        series_order=PORTFOLIO_HAZARD_SERIES_ORDER,
        series_colors=PORTFOLIO_HAZARD_SERIES_COLORS,
        series_labels={hazard: display_hazard(hazard) for hazard in PORTFOLIO_HAZARD_SERIES_ORDER},
        xlabel="Variation par rapport au cas de reference (habitants)",
        value_suffix=" hab",
    )


def plot_social_state_tornado(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
    output_dir: Path,
) -> list[Path]:
    table = build_social_state_tornado_table(territory_df, scenario_metadata, scope_label)
    return plot_series_tornado_table(
        table,
        output_dir / "tornado-social-states",
        series_order=PORTFOLIO_HAZARD_SERIES_ORDER,
        series_colors=PORTFOLIO_HAZARD_SERIES_COLORS,
        series_labels={hazard: display_hazard(hazard) for hazard in PORTFOLIO_HAZARD_SERIES_ORDER},
        xlabel="Variation par rapport au cas de reference (habitants)",
        value_suffix=" hab",
    )


def plot_risk_index_tornado(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
    output_dir: Path,
) -> list[Path]:
    table = build_risk_index_tornado_table(territory_df, scenario_metadata, scope_label)
    return plot_series_tornado_table(
        table,
        output_dir / "tornado-territory-risk",
        series_order=PORTFOLIO_HAZARD_SERIES_ORDER,
        series_colors=PORTFOLIO_HAZARD_SERIES_COLORS,
        series_labels={hazard: display_hazard(hazard) for hazard in PORTFOLIO_HAZARD_SERIES_ORDER},
        xlabel="Variation par rapport au cas de reference (%)",
        value_suffix="%",
    )


def plot_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = df[
        (df["metric"] == "impact_eur")
        & df["hazard"].isin(["storm", "storm_cmcc"])
        & (df["scenario_id"] != "all-default")
        & df["delta_pct"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
    ].copy()

    if scenario_df.empty:
        return output_paths

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)

    for (territory, hazard), group in scenario_df.groupby(
        ["territory", "hazard"],
        dropna=False,
    ):
        territory = str(territory or "unknown_territory")
        hazard = str(hazard or "unknown_hazard")
        territory_label = display_territory(territory)
        hazard_label = display_hazard(hazard)
        summary = (
            group.pivot_table(
                index="scenario_id",
                columns="return_period",
                values="delta_pct",
                aggfunc="mean",
            )
            .reindex(columns=list(IMPACT_PERIOD_ORDER))
            .reset_index()
        )
        if summary.empty:
            continue

        label_map = group.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary = summary.merge(label_map, on="scenario_id", how="left")
        summary["amplitude"] = summary[list(IMPACT_PERIOD_ORDER)].abs().max(axis=1, skipna=True)
        summary = (
            summary[summary["amplitude"].notna()]
            .sort_values("amplitude", ascending=True)
            .tail(25)
            .reset_index(drop=True)
        )
        if summary.empty:
            continue

        y_positions = np.arange(len(summary), dtype=float)
        bar_height = 0.22
        offsets = {"annual": -bar_height, "rp50": 0.0, "rp100": bar_height}

        fig, ax = plt.subplots(figsize=(13, max(4.5, 0.52 * len(summary) + 1)))
        all_values: list[float] = []

        for return_period in IMPACT_PERIOD_ORDER:
            values = summary[return_period].to_numpy(dtype=float)
            valid_mask = ~pd.isna(values)
            if not valid_mask.any():
                continue
            bar_positions = y_positions[valid_mask] + offsets[return_period]
            valid_values = values[valid_mask]
            colors = [
                IMPACT_NEGATIVE_COLORS[return_period] if value < 0 else IMPACT_POSITIVE_COLORS[return_period]
                for value in valid_values
            ]
            ax.barh(
                bar_positions,
                valid_values,
                height=bar_height * 0.9,
                color=colors,
            )
            _annotate_horizontal_bars(ax, valid_values, bar_positions, suffix="%")
            all_values.extend(valid_values.tolist())

        ax.set_yticks(y_positions)
        ax.set_yticklabels(summary["scenario_display_label"])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("Variation par rapport au cas de reference (%)")
        ax.set_title(f"{territory_label} - {hazard_label} - Sensibilite des impacts")
        ax.grid(True, axis="x", alpha=0.3)
        _set_symmetric_xlim(ax, all_values)

        legend_handles, legend_labels, legend_title = build_impact_legend_spec()
        ax.legend(
            handles=legend_handles,
            labels=legend_labels,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            title=legend_title,
            handler_map={tuple: HandlerTuple(ndivide=None, pad=0.6)},
        )

        fig.tight_layout(rect=[0, 0, 0.8, 1])

        filename = safe_filename(f"tornado_{territory}_{hazard}_annual_rp50_rp100.png")
        out_path = tornado_dir / filename
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        output_paths.append(out_path)

    return output_paths


def plot_super_impact_monetary_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado-super"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = df[
        (df["metric"] == "impact_eur")
        & df["hazard"].isin(["storm", "storm_cmcc"])
        & (df["scenario_id"] != "all-default")
        & df["delta_pct"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
        & df["return_period"].isin(IMPACT_PERIOD_ORDER)
    ].copy()
    if scenario_df.empty:
        return output_paths

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)

    for territory, group in scenario_df.groupby("territory", dropna=False):
        territory_key = str(territory or "unknown").strip().lower() or "unknown"
        territory_label = display_territory(territory_key)
        summary = (
            group.pivot_table(
                index="scenario_id",
                columns=["hazard", "return_period"],
                values="delta_pct",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary.empty:
            continue

        flattened_columns: list[str] = []
        significance_columns: list[str] = []
        for column in summary.columns:
            if column == ("scenario_id", ""):
                flattened_columns.append("scenario_id")
                continue
            if not isinstance(column, tuple) or len(column) != 2:
                flattened_columns.append(str(column))
                continue
            hazard, return_period = column
            flat_name = f"{hazard}__{return_period}"
            flattened_columns.append(flat_name)
            significance_columns.append(flat_name)
        summary.columns = flattened_columns

        label_map = group.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary = summary.merge(label_map, on="scenario_id", how="left")
        summary = _filter_significant_scenarios(summary, significance_columns=significance_columns)

        output_path = tornado_dir / safe_filename(f"sensitivity_super_graph_1_impact_monetaire_{territory_key}.png")
        if summary.empty:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 1 - Impact monétaire",
                    message="Aucun scénario ne dépasse le seuil de variation de 2%.",
                    figsize=(14, 4.5),
                )
            )
            continue

        y_positions = np.arange(len(summary), dtype=float)
        tick_fontsize = _scenario_tick_fontsize(len(summary))
        annotation_fontsize = _annotation_fontsize(len(summary))
        base_width, base_height = horizontal_bar_figure_size(
            item_count=len(summary),
            series_count=3,
            label_fontsize=annotation_fontsize,
            base_width=17.5,
            base_height=_super_graph_height(
                len(summary),
                minimum=5.8,
                per_scenario=0.48,
                extra=2.4,
                annotation_fontsize=annotation_fontsize,
                tick_fontsize=tick_fontsize,
            ),
        )
        width = base_width
        height = base_height
        padding_factor = 1.28
        saved = False
        for _attempt in range(8):
            fig, axes = plt.subplots(1, 2, figsize=(width, height), sharex=True, sharey=True)
            all_values: list[float] = []
            axis_label_items: list[list[dict[str, float | str]]] = []

            for axis, hazard in zip(axes, ("storm", "storm_cmcc")):
                axis_items: list[dict[str, float | str]] = []
                hazard_columns = [
                    f"{hazard}__{return_period}"
                    for return_period in IMPACT_PERIOD_ORDER
                    if f"{hazard}__{return_period}" in summary.columns
                ]
                series_colors = {
                    f"{hazard}__{return_period}": IMPACT_NEGATIVE_COLORS[return_period]
                    for return_period in IMPACT_PERIOD_ORDER
                    if f"{hazard}__{return_period}" in summary.columns
                }
                bar_height = 0.22
                offsets = {
                    f"{hazard}__annual": -bar_height,
                    f"{hazard}__rp50": 0.0,
                    f"{hazard}__rp100": bar_height,
                }
                for return_period in IMPACT_PERIOD_ORDER:
                    column_name = f"{hazard}__{return_period}"
                    if column_name not in summary.columns:
                        continue
                    values = summary[column_name].to_numpy(dtype=float)
                    valid_mask = ~pd.isna(values)
                    if not valid_mask.any():
                        continue
                    bar_positions = y_positions[valid_mask] + offsets[column_name]
                    valid_values = values[valid_mask]
                    colors = [
                        IMPACT_NEGATIVE_COLORS[return_period] if value < 0 else IMPACT_POSITIVE_COLORS[return_period]
                        for value in valid_values
                    ]
                    axis.barh(bar_positions, valid_values, height=bar_height * 0.9, color=colors)
                    axis_items.extend(
                        _build_horizontal_label_items(
                            valid_values,
                            bar_positions,
                            suffix="%",
                            min_abs_value=0.15,
                            decimals=1,
                        )
                    )
                    all_values.extend(valid_values.tolist())

                axis.axvline(0, color="black", linewidth=0.8)
                axis.grid(True, axis="x", alpha=0.3)
                axis.set_title(display_hazard(hazard), fontsize=11, fontweight="bold")
                axis.tick_params(axis="x", labelsize=8)
                axis_label_items.append(axis_items)

            axes[0].set_yticks(y_positions)
            axes[0].set_yticklabels(summary["scenario_display_label"], fontsize=tick_fontsize)
            axes[1].tick_params(axis="y", labelleft=False)
            for axis in axes:
                _set_symmetric_xlim(axis, all_values, padding_factor=padding_factor, annotation_fontsize=annotation_fontsize)

            layout_ok = True
            for axis, items in zip(axes, axis_label_items):
                result = place_horizontal_bar_labels(
                    axis,
                    items,
                    label_fontsize=annotation_fontsize,
                    lane_gap_pts=8.0,
                )
                layout_ok = layout_ok and result.success

            legend_handles, legend_labels, legend_title = build_impact_legend_spec()
            fig.legend(
                handles=legend_handles,
                labels=legend_labels,
                loc="upper center",
                ncol=3,
                bbox_to_anchor=(0.5, 0.955),
                title=legend_title,
                handler_map={tuple: HandlerTuple(ndivide=None, pad=0.6)},
                frameon=False,
            )
            fig.suptitle(
                f"{territory_label} - Impact monétaire",
                fontsize=15,
                y=0.985,
                x=0.5,
            )
            fig.subplots_adjust(left=0.26, right=0.98, top=0.80, bottom=0.08, wspace=0.08)
            if layout_ok:
                fig.savefig(output_path, dpi=160)
                plt.close(fig)
                output_paths.append(output_path)
                saved = True
                break
            plt.close(fig)
            width *= 1.14
            height *= 1.09
            padding_factor *= 1.10
        if not saved:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 1 - Impact monétaire",
                    message="Le layout automatique n'a pas pu placer toutes les étiquettes sans chevauchement.",
                    figsize=(max(width, 16), max(height, 5.5)),
                )
            )

    return output_paths


def plot_super_network_state_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado-super"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = df[
        (df["metric"] == "network_state_pct")
        & (df["scenario_id"] != "all-default")
        & df["delta_abs"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
        & df["network_metric"].isin(NETWORK_METRICS)
    ].copy()
    if scenario_df.empty:
        return output_paths

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)

    for territory, group in scenario_df.groupby("territory", dropna=False):
        territory_key = str(territory or "unknown").strip().lower() or "unknown"
        territory_label = display_territory(territory_key)
        summary = (
            group.pivot_table(
                index="scenario_id",
                columns=["network_metric", "hazard", "service"],
                values="delta_abs",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary.empty:
            continue

        flattened_columns: list[str] = []
        significance_columns: list[str] = []
        for column in summary.columns:
            if column == ("scenario_id", "", ""):
                flattened_columns.append("scenario_id")
                continue
            if not isinstance(column, tuple) or len(column) != 3:
                flattened_columns.append(str(column))
                continue
            network_metric, hazard, service = column
            flat_name = f"{network_metric}__{hazard}__{service}"
            flattened_columns.append(flat_name)
            significance_columns.append(flat_name)
        summary.columns = flattened_columns

        label_map = group.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary = summary.merge(label_map, on="scenario_id", how="left")
        summary = _filter_significant_scenarios(summary, significance_columns=significance_columns)

        output_path = tornado_dir / safe_filename(f"sensitivity_super_graph_2_pct_reseaux_{territory_key}.png")
        if summary.empty:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 2 - % réseaux",
                    message="Aucun scénario ne dépasse le seuil de variation de 2 points.",
                    figsize=(14, 4.5),
                )
            )
            continue

        y_positions = np.arange(len(summary), dtype=float)
        tick_fontsize = _scenario_tick_fontsize(len(summary))
        annotation_fontsize = _annotation_fontsize(len(summary))
        base_width, base_height = horizontal_bar_figure_size(
            item_count=len(summary),
            series_count=len(NETWORK_SERIES_ORDER),
            label_fontsize=annotation_fontsize,
            base_width=18.0,
            base_height=_super_graph_height(
                len(summary),
                minimum=6.0,
                per_scenario=0.50,
                extra=2.5,
                annotation_fontsize=annotation_fontsize,
                tick_fontsize=tick_fontsize,
            ),
        )
        width = base_width
        height = base_height
        padding_factor = 1.28
        saved = False
        for _attempt in range(8):
            fig, axes = plt.subplots(1, 2, figsize=(width, height), sharex=True, sharey=True)
            all_values: list[float] = []
            axis_label_items: list[list[dict[str, float | str]]] = []

            for axis, network_metric in zip(axes, ("non_nominal_pct", "outage_pct")):
                series_columns = [
                    f"{network_metric}__{hazard}__{service}"
                    for hazard, service in NETWORK_SERIES_ORDER
                    if f"{network_metric}__{hazard}__{service}" in summary.columns
                ]
                series_colors = {
                    series_column: NETWORK_SERIES_COLORS[(series_column.split("__")[1], series_column.split("__")[2])]
                    for series_column in series_columns
                }
                drawn_values, label_items = _draw_super_grouped_bars(
                    axis,
                    summary,
                    y_positions=y_positions,
                    series_columns=series_columns,
                    series_colors=series_colors,
                    value_suffix=" pts",
                    annotation_fontsize=annotation_fontsize,
                    min_annotation_abs=0.15,
                )
                all_values.extend(drawn_values)
                axis_label_items.append(label_items)
                axis.axvline(0, color="black", linewidth=0.8)
                axis.grid(True, axis="x", alpha=0.3)
                axis.set_title(NETWORK_METRICS.get(network_metric, network_metric), fontsize=11, fontweight="bold")
                axis.tick_params(axis="x", labelsize=8)

            axes[0].set_yticks(y_positions)
            axes[0].set_yticklabels(summary["scenario_display_label"], fontsize=tick_fontsize)
            axes[1].tick_params(axis="y", labelleft=False)
            for axis in axes:
                _set_symmetric_xlim(axis, all_values, padding_factor=padding_factor, annotation_fontsize=annotation_fontsize)

            layout_ok = True
            for axis, items in zip(axes, axis_label_items):
                result = place_horizontal_bar_labels(
                    axis,
                    items,
                    label_fontsize=annotation_fontsize,
                    lane_gap_pts=8.0,
                )
                layout_ok = layout_ok and result.success

            fig.legend(
                handles=[
                    Patch(
                        color=NETWORK_SERIES_COLORS[series_key],
                        label=f"{display_hazard(series_key[0])} {SERVICE_LABELS[series_key[1]]}",
                    )
                    for series_key in NETWORK_SERIES_ORDER
                    if any(
                        f"{network_metric}__{series_key[0]}__{series_key[1]}" in summary.columns
                        for network_metric in ("non_nominal_pct", "outage_pct")
                    )
                ],
                loc="upper center",
                bbox_to_anchor=(0.5, 0.962),
                ncol=3,
                frameon=False,
                title="Séries",
            )
            fig.suptitle(f"{territory_label} - % réseaux", fontsize=15, y=0.985, x=0.5)
            fig.subplots_adjust(left=0.26, right=0.98, top=0.785, bottom=0.08, wspace=0.08)
            if layout_ok:
                fig.savefig(output_path, dpi=160)
                plt.close(fig)
                output_paths.append(output_path)
                saved = True
                break
            plt.close(fig)
            width *= 1.14
            height *= 1.09
            padding_factor *= 1.10
        if not saved:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 2 - % réseaux",
                    message="Le layout automatique n'a pas pu placer toutes les étiquettes sans chevauchement.",
                    figsize=(max(width, 16), max(height, 5.7)),
                )
            )

    return output_paths


def plot_super_social_state_tornado(
    territory_df: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    scope_label: str,
    output_dir: Path,
) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado-super"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    table = build_social_state_super_graph_table(territory_df, scenario_metadata)
    if table.empty:
        return output_paths

    for territory_key, territory_label, territory_table in _territory_groups(table, scope_label):
        summary_values = (
            territory_table.pivot_table(
                index="scenario_id",
                columns=["service", "state", "hazard"],
                values="delta_value",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary_values.empty:
            continue
        summary_significance = (
            territory_table.pivot_table(
                index="scenario_id",
                columns=["service", "state", "hazard"],
                values="delta_pct_filter",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary_significance.empty:
            continue

        value_columns: list[str] = []
        significance_columns: list[str] = []
        for frame in (summary_values, summary_significance):
            flattened_columns: list[str] = []
            current_value_columns: list[str] = []
            for column in frame.columns:
                if column == ("scenario_id", "", ""):
                    flattened_columns.append("scenario_id")
                    continue
                if not isinstance(column, tuple) or len(column) != 3:
                    flattened_columns.append(str(column))
                    continue
                service, state, hazard = column
                flat_name = f"{service}__{state}__{hazard}"
                flattened_columns.append(flat_name)
                current_value_columns.append(flat_name)
            frame.columns = flattened_columns
            if frame is summary_values:
                value_columns = current_value_columns
            else:
                significance_columns = current_value_columns

        label_map = territory_table.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary_values = summary_values.merge(label_map, on="scenario_id", how="left")
        summary_significance = summary_significance.merge(label_map, on="scenario_id", how="left")
        filtered = _filter_significant_scenarios(summary_significance, significance_columns=significance_columns)

        output_path = tornado_dir / safe_filename(f"sensitivity_super_graph_3_social_states_{territory_key}.png")
        if filtered.empty:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 3 - États sociaux",
                    message="Aucun scénario ne dépasse le seuil de variation de 2%.",
                    figsize=(16, 5),
                )
            )
            continue

        summary = summary_values[
            summary_values["scenario_id"].isin(filtered["scenario_id"].tolist())
        ].copy()
        summary["scenario_rank"] = summary["scenario_id"].map(
            {scenario_id: idx for idx, scenario_id in enumerate(filtered["scenario_id"].tolist())}
        )
        summary = summary.sort_values("scenario_rank", ascending=True).reset_index(drop=True)

        y_positions = np.arange(len(summary), dtype=float)
        tick_fontsize = _scenario_tick_fontsize(len(summary))
        annotation_fontsize = _annotation_fontsize(len(summary))
        base_width, base_height = horizontal_bar_figure_size(
            item_count=len(summary),
            series_count=len(PORTFOLIO_HAZARD_SERIES_ORDER),
            label_fontsize=annotation_fontsize,
            base_width=24.0,
            base_height=_super_graph_height(
                len(summary),
                minimum=10.2,
                per_scenario=0.46,
                extra=5.2,
                annotation_fontsize=annotation_fontsize,
                tick_fontsize=tick_fontsize,
            ),
        )
        width = base_width
        height = base_height
        padding_factor = 1.52
        saved = False
        for _attempt in range(8):
            fig, axes = plt.subplots(
                len(SOCIAL_SUPER_GRAPH_STATE_ORDER),
                len(SOCIAL_SUPER_GRAPH_SERVICE_ORDER),
                figsize=(width, height),
                sharex=True,
                sharey=True,
            )
            all_values: list[float] = []
            axis_label_items: list[list[list[dict[str, float | str]]]] = []

            for row_idx, state in enumerate(SOCIAL_SUPER_GRAPH_STATE_ORDER):
                row_label_items: list[list[dict[str, float | str]]] = []
                for col_idx, service in enumerate(SOCIAL_SUPER_GRAPH_SERVICE_ORDER):
                    axis = axes[row_idx, col_idx]
                    series_columns = [
                        f"{service}__{state}__{hazard}"
                        for hazard in PORTFOLIO_HAZARD_SERIES_ORDER
                        if f"{service}__{state}__{hazard}" in summary.columns
                    ]
                    series_colors = {
                        series_column: PORTFOLIO_HAZARD_SERIES_COLORS[series_column.split("__")[2]]
                        for series_column in series_columns
                    }
                    drawn_values, label_items = _draw_super_grouped_bars(
                        axis,
                        summary,
                        y_positions=y_positions,
                        series_columns=series_columns,
                        series_colors=series_colors,
                        value_suffix=" hab",
                        annotation_fontsize=annotation_fontsize,
                        min_annotation_abs=0.5,
                        annotation_decimals=0,
                    )
                    row_label_items.append(label_items)
                    all_values.extend(drawn_values)
                    axis.axvline(0, color="black", linewidth=0.8)
                    axis.grid(True, axis="x", alpha=0.25)
                    axis.tick_params(axis="x", labelsize=8)
                    if row_idx == 0:
                        axis.set_title(SOCIAL_SUPER_GRAPH_SERVICE_LABELS[service], fontsize=11, fontweight="bold", pad=10)
                    if col_idx == 0:
                        axis.set_yticks(y_positions)
                        axis.set_yticklabels(summary["scenario_display_label"], fontsize=tick_fontsize)
                        axis.text(
                            -0.52,
                            0.5,
                            SOCIAL_SUPER_GRAPH_STATE_LABELS[state],
                            rotation=90,
                            va="center",
                            ha="center",
                            fontsize=10,
                            fontweight="bold",
                            transform=axis.transAxes,
                        )
                    else:
                        axis.tick_params(axis="y", labelleft=False)
                    if not drawn_values:
                        axis.text(
                            0.5,
                            0.5,
                            "Aucune donnée",
                            ha="center",
                            va="center",
                            fontsize=9,
                            color="#475569",
                            transform=axis.transAxes,
                        )
                axis_label_items.append(row_label_items)

            for row in axes:
                for axis in row:
                    _set_symmetric_xlim(axis, all_values, padding_factor=padding_factor, annotation_fontsize=annotation_fontsize)

            layout_ok = True
            for row_axes, row_items in zip(axes, axis_label_items):
                for axis, items in zip(row_axes, row_items):
                    result = place_horizontal_bar_labels(
                        axis,
                        items,
                        label_fontsize=annotation_fontsize,
                        lane_gap_pts=8.0,
                    )
                    layout_ok = layout_ok and result.success

            fig.legend(
                handles=[
                    Patch(color=PORTFOLIO_HAZARD_SERIES_COLORS[hazard], label=display_hazard(hazard))
                    for hazard in PORTFOLIO_HAZARD_SERIES_ORDER
                ],
                loc="upper center",
                bbox_to_anchor=(0.5, 0.972),
                ncol=2,
                frameon=False,
                title="Aléas",
            )
            fig.suptitle(f"{territory_label} - États sociaux", fontsize=15, y=0.988, x=0.5)
            fig.subplots_adjust(left=0.30, right=0.985, top=0.865, bottom=0.07, wspace=0.10, hspace=0.24)
            if layout_ok:
                fig.savefig(output_path, dpi=160)
                plt.close(fig)
                output_paths.append(output_path)
                saved = True
                break
            plt.close(fig)
            width *= 1.18
            height *= 1.10
            padding_factor *= 1.12
        if not saved:
            output_paths.append(
                _write_super_graph_placeholder(
                    output_path,
                    title=f"{territory_label} - Super graph 3 - États sociaux",
                    message="Le layout automatique n'a pas pu placer toutes les étiquettes sans chevauchement.",
                    figsize=(max(width, 22), max(height, 10.2)),
                )
            )

    return output_paths


def plot_network_state_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado-network-states"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = df[
        (df["metric"] == "network_state_pct")
        & (df["scenario_id"] != "all-default")
        & df["delta_abs"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
    ].copy()

    if scenario_df.empty:
        return output_paths

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)
    series_column_names = {
        series_key: f"{series_key[0]}::{series_key[1]}"
        for series_key in NETWORK_SERIES_ORDER
    }

    for (territory, network_metric), group in scenario_df.groupby(
        ["territory", "network_metric"],
        dropna=False,
    ):
        territory = str(territory or "unknown_territory")
        network_metric = str(network_metric or "unknown_metric")
        territory_label = display_territory(territory)

        summary = (
            group.pivot_table(
                index="scenario_id",
                columns=["hazard", "service"],
                values="delta_abs",
                aggfunc="mean",
            )
            .reset_index()
        )
        if summary.empty:
            continue

        summary.columns = [
            "scenario_id"
            if column == ("scenario_id", "")
            else series_column_names.get(column, str(column))
            for column in summary.columns
        ]

        label_map = group.groupby("scenario_id", as_index=False).agg(
            scenario_display_label=("scenario_display_label", "first")
        )
        summary = summary.merge(label_map, on="scenario_id", how="left")
        series_columns = [
            series_key
            for series_key in NETWORK_SERIES_ORDER
            if series_column_names[series_key] in summary.columns
        ]
        if not series_columns:
            continue

        summary["amplitude"] = summary[
            [series_column_names[series_key] for series_key in series_columns]
        ].abs().max(axis=1, skipna=True)
        summary = (
            summary[summary["amplitude"].notna()]
            .sort_values("amplitude", ascending=True)
            .tail(25)
            .reset_index(drop=True)
        )
        if summary.empty:
            continue

        y_positions = np.arange(len(summary), dtype=float)
        bar_height = 0.11
        center_offset = (len(NETWORK_SERIES_ORDER) - 1) / 2

        fig, ax = plt.subplots(figsize=(14, max(4.5, 0.54 * len(summary) + 1)))
        all_values: list[float] = []

        for series_idx, series_key in enumerate(NETWORK_SERIES_ORDER):
            series_column = series_column_names[series_key]
            if series_column not in summary.columns:
                continue
            values = summary[series_column].to_numpy(dtype=float)
            valid_mask = ~pd.isna(values)
            if not valid_mask.any():
                continue
            bar_positions = y_positions[valid_mask] + (series_idx - center_offset) * bar_height
            valid_values = values[valid_mask]
            ax.barh(
                bar_positions,
                valid_values,
                height=bar_height * 0.9,
                color=NETWORK_SERIES_COLORS[series_key],
            )
            _annotate_horizontal_bars(ax, valid_values, bar_positions, suffix=" pts", fontsize=7)
            all_values.extend(valid_values.tolist())

        ax.set_yticks(y_positions)
        ax.set_yticklabels(summary["scenario_display_label"])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("Variation par rapport au cas de reference (points de pourcentage de reseau)")
        ax.set_title(f"{territory_label} - {NETWORK_METRICS.get(network_metric, network_metric)}")
        ax.grid(True, axis="x", alpha=0.3)
        _set_symmetric_xlim(ax, all_values)

        series_legend_handles = [
            Patch(
                color=NETWORK_SERIES_COLORS[series_key],
                label=f"{display_hazard(series_key[0])} {SERVICE_LABELS[series_key[1]]}",
            )
            for series_key in NETWORK_SERIES_ORDER
            if series_column_names[series_key] in summary.columns
        ]
        ax.legend(
            handles=series_legend_handles,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
            title="Séries\n(couleur fixe)",
        )

        fig.tight_layout(rect=[0, 0, 0.8, 1])
        filename_suffix = NETWORK_METRIC_FILENAME_SUFFIXES.get(network_metric, network_metric)
        filename = safe_filename(f"tornado_network_states_{territory}_{filename_suffix}.png")
        out_path = tornado_dir / filename
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        output_paths.append(out_path)

    return output_paths


def write_run_summary(
    output_dir: Path,
    manifest_path: Path,
    parent_manifest: dict[str, Any],
    df: pd.DataFrame,
    graph_paths: list[Path],
    quality_report: dict[str, Any],
) -> Path:
    summary_path = output_dir / "sensitivity-graphs-summary.json"

    payload = {
        "source_manifest": str(manifest_path),
        "sensitivity_run_id": parent_manifest.get("run_id"),
        "source_status": parent_manifest.get("status"),
        "rows": int(len(df)),
        "scenario_count_in_table": int(df["scenario_id"].nunique()) if not df.empty else 0,
        "territories": sorted(df["territory"].dropna().unique().tolist()) if not df.empty else [],
        "hazards": sorted(df["hazard"].dropna().unique().tolist()) if not df.empty else [],
        "return_periods": sorted(df["return_period"].dropna().unique().tolist()) if not df.empty else [],
        "excluded_scenario_ids": sorted(EXCLUDED_SCENARIO_IDS),
        "quality_report": quality_report,
        "parameter_traceability": summarize_parameter_traceability(parent_manifest),
        "graphs": [str(path) for path in graph_paths],
    }

    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate sensitivity-analysis graphs from existing SIB outputs.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to sensitivity manifest. Default: outputs/sensitivity-runs/latest-manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: <sensitivity-run-dir>/graphs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = REPO_ROOT / manifest_path

    if not manifest_path.exists():
        raise FileNotFoundError(f"Sensitivity manifest not found: {manifest_path}")

    parent_manifest = load_json(manifest_path)

    if args.output_dir is None:
        output_dir = manifest_path.parent / "graphs"
    else:
        output_dir = args.output_dir
        if not output_dir.is_absolute():
            output_dir = REPO_ROOT / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)
    clean_legacy_outputs(output_dir)

    print(f"[info] Reading sensitivity manifest: {manifest_path}")
    print(f"[info] Writing outputs to: {output_dir}")

    df, extraction_warnings = build_normalized_dataframe(parent_manifest)
    df = add_baseline_deltas(df)
    scenario_metadata = build_scenario_metadata(df)
    scope_label = display_scope_label(df)
    run_dir = manifest_path.parent
    portfolio_metrics_df = load_artifact_table(run_dir, "portfolio-metrics.parquet")
    territory_metrics_df = load_artifact_table(run_dir, "territory-metrics.parquet")

    normalized_csv = output_dir / "sensitivity-results-normalized.csv"
    df.to_csv(normalized_csv, index=False)
    print(f"[info] Wrote normalized table: {normalized_csv}")
    print(f"[info] Rows: {len(df)}")

    if df.empty:
        print("[warning] No scientific payload could be resolved from explicit complete_analysis_json_path entries.")
        print("[warning] The sensitivity manifest is missing strict scientific payload paths or points to non-existent files.")
        quality_report = build_quality_report(df)
        quality_report.setdefault("alerts", []).extend(extraction_warnings)
        summary_path = write_run_summary(output_dir, manifest_path, parent_manifest, df, [], quality_report)
        print(f"[info] Wrote summary: {summary_path}")
        return 2

    scenario_count = df["scenario_id"].nunique()
    if scenario_count <= 1:
        print("[warning] Only one scenario found in the normalized table.")
        print("[warning] Combined tornado charts need at least one non-baseline scenario.")
        print("[warning] The extraction works, but your current run probably only contains all-default.")

    graph_paths: list[Path] = []
    graph_paths.extend(plot_tornado(df, output_dir))
    graph_paths.extend(plot_network_state_tornado(df, output_dir))
    graph_paths.extend(plot_super_impact_monetary_tornado(df, output_dir))
    graph_paths.extend(plot_super_network_state_tornado(df, output_dir))
    graph_paths.extend(plot_delta_annual_tornado(df, output_dir))
    graph_paths.extend(plot_portfolio_risk_tornado(portfolio_metrics_df, scenario_metadata, scope_label, output_dir))
    graph_paths.extend(plot_social_metric_tornado(territory_metrics_df, scenario_metadata, scope_label, output_dir))
    graph_paths.extend(plot_social_state_tornado(territory_metrics_df, scenario_metadata, scope_label, output_dir))
    graph_paths.extend(plot_super_social_state_tornado(territory_metrics_df, scenario_metadata, scope_label, output_dir))
    graph_paths.extend(plot_risk_index_tornado(territory_metrics_df, scenario_metadata, scope_label, output_dir))

    quality_report = build_quality_report(df)
    quality_report.setdefault("alerts", []).extend(extraction_warnings)
    summary_path = write_run_summary(output_dir, manifest_path, parent_manifest, df, graph_paths, quality_report)

    print(f"[info] Graphs generated: {len(graph_paths)}")
    for path in graph_paths:
        print(f"[info]   {path}")
    if quality_report.get("alerts"):
        for alert in quality_report["alerts"]:
            print(f"[warning] {alert}")
    if quality_report.get("status") == "failed":
        print("[error] Sensitivity graph quality checks failed. Review sensitivity-graphs-summary.json.")
        print(f"[info] Wrote summary: {summary_path}")
        return 3

    print(f"[info] Wrote summary: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
