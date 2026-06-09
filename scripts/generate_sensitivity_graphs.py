#!/usr/bin/env python3
"""
Generate sensitivity-analysis graphs from SIB sensitivity runs.

This script is intentionally independent from CLIMADA execution.
It only reads existing sensitivity manifests, logs, complete-analysis manifests,
and complete-analysis JSON payloads.

Main outputs:
- normalized CSV table
- sensitivity curves
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

import numpy as np
from matplotlib.patches import Patch



REPO_ROOT = Path(__file__).resolve().parents[1]

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

        payload_candidates: list[Path] = []
        child_manifest_candidates: list[Path] = []

        child_manifest_raw = scenario.get("child_manifest_path")
        if child_manifest_raw:
            child_manifest_path = Path(str(child_manifest_raw))
            child_manifest_candidates.append(child_manifest_path)
            payload_candidates.extend(payload_paths_from_child_manifest(child_manifest_path))

        log_text = read_log_text(Path(str(scenario.get("log_path"))) if scenario.get("log_path") else None)
        log_payloads, log_manifests = find_paths_in_log(log_text)
        payload_candidates.extend(log_payloads)
        child_manifest_candidates.extend(log_manifests)

        for child_manifest_path in log_manifests:
            payload_candidates.extend(payload_paths_from_child_manifest(child_manifest_path))

        payload_candidates = [path for path in dict.fromkeys(payload_candidates) if path.exists()]
        child_manifest_candidates = [path for path in dict.fromkeys(child_manifest_candidates) if path.exists()]

        for payload_path in payload_candidates:
            results.append(
                ScenarioPayload(
                    scenario_id=scenario_id,
                    scenario_label=label,
                    parameter_key=parameter_key,
                    status=status,
                    payload_path=payload_path,
                    child_manifest_path=child_manifest_candidates[-1] if child_manifest_candidates else None,
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


def extract_rows_from_payload(scenario_payload: ScenarioPayload) -> list[dict[str, Any]]:
    payload = load_json(scenario_payload.payload_path)
    territory = infer_territory_from_payload_path(scenario_payload.payload_path)

    parameter_raw_value, parameter_numeric_value = scenario_parameter_value(
        scenario_payload.scenario_id,
        scenario_payload.parameter_key,
    )

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, float]] = set()

    for path, block in iter_metric_blocks(payload):
        hazard = guess_hazard_from_path(path, block)

        # Avoid extracting component-level blocks as main portfolio rows when possible.
        path_text = "/".join(path).lower()
        if "component" in path_text or "matching" in path_text:
            continue

        for return_period, source_key in METRIC_MAP.items():
            value = safe_float(block.get(source_key))
            if math.isnan(value):
                continue

            dedup_key = (scenario_payload.scenario_id, territory, hazard, return_period, value)
            if dedup_key in seen:
                continue
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
                    "metric": "impact_eur",
                    "return_period": return_period,
                    "value": value,
                    "payload_path": str(scenario_payload.payload_path),
                    "child_manifest_path": str(scenario_payload.child_manifest_path or ""),
                }
            )

    return rows


def build_normalized_dataframe(parent_manifest: dict[str, Any]) -> pd.DataFrame:
    scenario_payloads = resolve_scenario_payloads(parent_manifest)

    rows: list[dict[str, Any]] = []
    for scenario_payload in scenario_payloads:
        rows.extend(extract_rows_from_payload(scenario_payload))

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Keep obvious useful hazard rows first. This does not delete unknown rows automatically,
    # because schemas may evolve.
    df = df.sort_values(
        by=["territory", "hazard", "return_period", "parameter_key", "scenario_id"],
        kind="stable",
    ).reset_index(drop=True)

    return df


def add_baseline_deltas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    baseline = df[df["scenario_id"] == "all-default"].copy()
    if baseline.empty:
        df["baseline_value"] = math.nan
        df["delta_abs"] = math.nan
        df["delta_pct"] = math.nan
        return df

    baseline = baseline[
        ["territory", "hazard", "metric", "return_period", "value"]
    ].rename(columns={"value": "baseline_value"})

    merged = df.merge(
        baseline,
        on=["territory", "hazard", "metric", "return_period"],
        how="left",
    )

    merged["delta_abs"] = merged["value"] - merged["baseline_value"]
    merged["delta_pct"] = merged.apply(
        lambda row: (row["delta_abs"] / row["baseline_value"] * 100.0)
        if row["baseline_value"] not in (0, None) and not pd.isna(row["baseline_value"])
        else math.nan,
        axis=1,
    )

    return merged


def safe_filename(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value).strip())
    value = value.strip("_")
    return value or "graph"


def short_scenario_label(row: pd.Series) -> str:
    """Build a compact, non-duplicated label for graph axes."""
    scenario_id = str(row.get("scenario_id") or "").strip()
    scenario_label = str(row.get("scenario_label") or "").strip()
    parameter_key = str(row.get("parameter_key") or "").strip()
    parameter_value = str(row.get("parameter_value") or "").strip()

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


def plot_curves(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    curves_dir = output_dir / "curves"
    curves_dir.mkdir(parents=True, exist_ok=True)

    if df.empty:
        return output_paths

    non_default_df = df[
        (df["scenario_id"] != "all-default")
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
    ].copy()

    if non_default_df.empty:
        return output_paths

    for (parameter_key, hazard, return_period), group in non_default_df.groupby(
        ["parameter_key", "hazard", "return_period"],
        dropna=False,
    ):
        parameter_key = str(parameter_key or "unknown_parameter")
        hazard = str(hazard or "unknown_hazard")
        return_period = str(return_period or "unknown_return_period")

        baseline_group = df[
            (df["scenario_id"] == "all-default")
            & (df["hazard"] == hazard)
            & (df["return_period"] == return_period)
        ].copy()

        if not baseline_group.empty:
            baseline_group["parameter_key"] = parameter_key
            baseline_group["parameter_value"] = "default"
            baseline_group["parameter_value_num"] = pd.NA

        plot_group = pd.concat([baseline_group, group], ignore_index=True)

        if plot_group.empty:
            continue

        # Avoid duplicated bars.
        plot_group = plot_group.drop_duplicates(
            subset=[
                "scenario_id",
                "territory",
                "hazard",
                "return_period",
                "value",
            ]
        ).copy()

        plot_group["is_default"] = plot_group["scenario_id"].eq("all-default")
        plot_group["sort_num"] = pd.to_numeric(
            plot_group["parameter_value_num"],
            errors="coerce",
        )

        plot_group = plot_group.sort_values(
            by=["is_default", "sort_num", "scenario_id", "territory"],
            ascending=[False, True, True, True],
            kind="stable",
        ).reset_index(drop=True)

        scenario_order = plot_group["scenario_id"].drop_duplicates().tolist()
        territories = plot_group["territory"].drop_duplicates().tolist()

        if not scenario_order or not territories:
            continue

        x_positions = np.arange(len(scenario_order))
        bar_width = 0.8 / max(1, len(territories))

        fig, ax = plt.subplots(figsize=(12, 6))

        legend_handles: list[Patch] = []

        for territory_idx, territory in enumerate(territories):
            territory_data = plot_group[plot_group["territory"] == territory].copy()

            offset = (territory_idx - (len(territories) - 1) / 2) * bar_width

            for scenario_idx, scenario_id in enumerate(scenario_order):
                row = territory_data[territory_data["scenario_id"] == scenario_id]

                if row.empty:
                    continue

                row = row.iloc[0]
                value = row["value"]
                is_default = bool(row["scenario_id"] == "all-default")

                if is_default:
                    color = "tab:gray"
                    legend_label = f"{territory} - défaut"
                else:
                    color = "tab:blue"
                    legend_label = f"{territory} - scénario"

                ax.bar(
                    x_positions[scenario_idx] + offset,
                    value,
                    width=bar_width,
                    color=color,
                )

                if not any(handle.get_label() == legend_label for handle in legend_handles):
                    legend_handles.append(Patch(color=color, label=legend_label))

        # Labels only on x axis.
        x_labels = []
        for scenario_id in scenario_order:
            row = plot_group[plot_group["scenario_id"] == scenario_id].iloc[0]
            x_labels.append(short_scenario_label(row))

        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_labels, rotation=30, ha="right")

        ax.set_ylabel("Impact estimé (€)")
        ax.grid(True, axis="y", alpha=0.3)

        # Legend outside graph.
        ax.legend(
            handles=legend_handles,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
        )

        fig.tight_layout(rect=[0, 0, 0.82, 1])

        filename = safe_filename(f"curve_{parameter_key}_{hazard}_{return_period}.png")
        out_path = curves_dir / filename
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        output_paths.append(out_path)

    return output_paths


def plot_tornado(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_paths: list[Path] = []
    tornado_dir = output_dir / "tornado"
    tornado_dir.mkdir(parents=True, exist_ok=True)

    scenario_df = df[
        (df["scenario_id"] != "all-default")
        & df["delta_pct"].notna()
        & df["parameter_key"].notna()
        & (df["parameter_key"].astype(str) != "")
    ].copy()

    if scenario_df.empty:
        return output_paths

    scenario_df["scenario_display_label"] = scenario_df.apply(short_scenario_label, axis=1)

    for (territory, hazard, return_period), group in scenario_df.groupby(
        ["territory", "hazard", "return_period"],
        dropna=False,
    ):
        territory = str(territory or "unknown_territory")
        hazard = str(hazard or "unknown_hazard")
        return_period = str(return_period or "unknown_return_period")

        # One row per scenario to avoid repeated labels/bars.
        summary = (
            group.groupby("scenario_id", as_index=False)
            .agg(
                scenario_display_label=("scenario_display_label", "first"),
                parameter_key=("parameter_key", "first"),
                parameter_value=("parameter_value", "first"),
                delta_pct=("delta_pct", "mean"),
            )
        )

        if summary.empty:
            continue

        summary["amplitude"] = summary["delta_pct"].abs()
        summary = summary.sort_values("amplitude", ascending=True).tail(25)

        y_positions = list(range(len(summary)))

        fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(summary) + 1)))

        colors = [
            "tab:blue" if value < 0 else "tab:orange"
            for value in summary["delta_pct"]
        ]

        ax.barh(
            y_positions,
            summary["delta_pct"],
            color=colors,
        )

        ax.set_yticks(y_positions)
        ax.set_yticklabels(summary["scenario_display_label"])

        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("Variation vs baseline (%)")
        ax.grid(True, axis="x", alpha=0.3)

        # Label each bar once, with only the % value.
        for y_pos, (_, row) in zip(y_positions, summary.iterrows()):
            delta_pct = float(row["delta_pct"])
            label = f"{delta_pct:+.1f}%"

            if delta_pct >= 0:
                ha = "left"
                x_offset = 5
            else:
                ha = "right"
                x_offset = -5

            ax.annotate(
                label,
                xy=(delta_pct, y_pos),
                xytext=(x_offset, 0),
                textcoords="offset points",
                va="center",
                ha=ha,
                fontsize=8,
            )

        legend_handles = [
            Patch(color="tab:blue", label="Diminution"),
            Patch(color="tab:orange", label="Augmentation"),
        ]

        ax.legend(
            handles=legend_handles,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            borderaxespad=0,
        )

        fig.tight_layout(rect=[0, 0, 0.82, 1])

        filename = safe_filename(f"tornado_{territory}_{hazard}_{return_period}.png")
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
        "graphs": [str(path) for path in graph_paths],
    }

    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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

    print(f"[info] Reading sensitivity manifest: {manifest_path}")
    print(f"[info] Writing outputs to: {output_dir}")

    df = build_normalized_dataframe(parent_manifest)
    df = add_baseline_deltas(df)

    normalized_csv = output_dir / "sensitivity-results-normalized.csv"
    df.to_csv(normalized_csv, index=False)
    print(f"[info] Wrote normalized table: {normalized_csv}")
    print(f"[info] Rows: {len(df)}")

    if df.empty:
        print("[warning] No scientific payload could be resolved from the sensitivity manifest/logs.")
        print("[warning] Check log_path, child_manifest_path, and complete-analysis JSON paths.")
        summary_path = write_run_summary(output_dir, manifest_path, parent_manifest, df, [])
        print(f"[info] Wrote summary: {summary_path}")
        return 2

    scenario_count = df["scenario_id"].nunique()
    if scenario_count <= 1:
        print("[warning] Only one scenario found in the normalized table.")
        print("[warning] Curves and tornado charts need at least one non-baseline scenario.")
        print("[warning] The extraction works, but your current run probably only contains all-default.")

    graph_paths: list[Path] = []
    graph_paths.extend(plot_curves(df, output_dir))
    graph_paths.extend(plot_tornado(df, output_dir))

    summary_path = write_run_summary(output_dir, manifest_path, parent_manifest, df, graph_paths)

    print(f"[info] Graphs generated: {len(graph_paths)}")
    for path in graph_paths:
        print(f"[info]   {path}")

    print(f"[info] Wrote summary: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
