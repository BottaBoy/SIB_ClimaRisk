#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "outputs"
    / "run-comparisons"
    / "guadeloupe-track-sampling"
    / "20260711_071243_vs_20260711_074032"
)
DEFAULT_FULL_ARCHIVE_DIR = Path("/home/ubuntu/uploads/from_popa/20260711_071243/scientific_archive")
DEFAULT_V1_WEB_DATA_DIR = (
    REPO_ROOT
    / "outputs"
    / "complete-analysis-runs"
    / "20260711_074032"
    / "territories"
    / "guadeloupe"
    / "web"
    / "data"
)
DEFAULT_V1_MANIFEST = (
    REPO_ROOT
    / "outputs"
    / "\u00c9chantillons Tracks_NA_Guadeloupe"
    / "sample_5000"
    / "manifest.json"
)
DEFAULT_V2_WEB_DATA_DIR = (
    REPO_ROOT
    / "outputs"
    / "complete-analysis-runs"
    / "20260720_134606"
    / "territories"
    / "guadeloupe"
    / "web"
    / "data"
)
DEFAULT_V2_MANIFEST = (
    REPO_ROOT
    / "outputs"
    / "\u00c9chantillons Tracks_NA_Guadeloupe"
    / "V2"
    / "sample_5000"
    / "manifest.json"
)

HAZARDS = ("storm", "storm_cmcc")
SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
STATE_KEYS = ("S0", "S1", "S2", "S3")
PORTFOLIO_METRICS = (
    "eai_eur",
    "aai_agg_eur",
    "eai_direct_eur",
    "eai_indirect_eur",
    "percentile_99_loss_eur",
    "pml_10_eur",
    "pml_20_eur",
    "pml_50_eur",
    "pml_100_eur",
    "pml_200_eur",
    "pml_1000_eur",
    "tvar_95_eur",
)
NETWORK_DAMAGE_METRICS = (
    "exposure_eur",
    "damage_eur",
    "direct_damage_eur",
    "dysfunction_eur",
    "blocking_ouvrage_eur",
    "indirect_damage_eur",
    "total_damage_eur",
)
SOCIAL_METRICS = (
    "total_population_affected_any_network",
    "total_without_elec",
    "total_without_eau_aep",
    "total_without_eau_eu",
    "total_without_eau",
    "total_with_degraded_elec",
    "total_with_degraded_eau_aep",
    "total_with_degraded_eau_eu",
)


class ComparisonError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunSpec:
    key: str
    label: str
    run_id: str
    complete_path: Path
    summary_path: Path
    track_mode: str
    manifest_path: Path | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ComparisonError(f"Missing required file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError(f"Expected a JSON object in {path}")
    return payload


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _fmt_num(value: float | None, unit: str = "") -> str:
    if value is None:
        return "-"
    if unit == "eur":
        return f"{value / 1_000_000:,.2f} M EUR".replace(",", " ")
    if unit == "pct":
        return f"{value:.2f}%"
    if unit in {"people", "count"}:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def _fmt_delta_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def _delta_pct(reference: float | None, compared: float | None) -> float | None:
    if reference is None or compared is None or abs(reference) < 1e-12:
        return None
    return ((compared - reference) / reference) * 100.0


def _metric_id(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("category", "")),
        str(row.get("scope", "")),
        str(row.get("hazard", "")),
        str(row.get("scenario", "")),
        str(row.get("service", "")),
        str(row.get("class_key", "")),
        str(row.get("component", "")),
        str(row.get("metric", "")),
        str(row.get("unit", "")),
    )


def _add_metric(
    rows: dict[tuple[str, ...], dict[str, Any]],
    *,
    category: str,
    scope: str,
    metric: str,
    value: Any,
    unit: str = "",
    hazard: str = "all",
    scenario: str = "all",
    service: str = "",
    class_key: str = "",
    component: str = "",
    label: str = "",
) -> None:
    numeric = _safe_float(value)
    if numeric is None:
        return
    row = {
        "category": category,
        "scope": scope,
        "hazard": hazard,
        "scenario": scenario,
        "service": service,
        "class_key": class_key,
        "component": component,
        "metric": metric,
        "unit": unit,
        "label": label,
        "value": numeric,
    }
    rows[_metric_id(row)] = row


def _flatten_numeric(
    rows: dict[tuple[str, ...], dict[str, Any]],
    payload: dict[str, Any],
    *,
    category: str,
    scope: str,
    prefix: str = "",
    unit: str = "",
    hazard: str = "all",
    scenario: str = "all",
    service: str = "",
    class_key: str = "",
    component: str = "",
) -> None:
    for key, value in payload.items():
        metric_name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            _flatten_numeric(
                rows,
                value,
                category=category,
                scope=scope,
                prefix=metric_name,
                unit=unit,
                hazard=hazard,
                scenario=scenario,
                service=service,
                class_key=class_key,
                component=component,
            )
        else:
            _add_metric(
                rows,
                category=category,
                scope=scope,
                metric=metric_name,
                value=value,
                unit=unit,
                hazard=hazard,
                scenario=scenario,
                service=service,
                class_key=class_key,
                component=component,
            )


def _extract_exposure_metrics(
    rows: dict[tuple[str, ...], dict[str, Any]],
    complete: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    exposure = complete.get("exposure_summary") if isinstance(complete.get("exposure_summary"), dict) else {}
    _add_metric(
        rows,
        category="comparability",
        scope="complete_analysis",
        metric="asset_results_count",
        value=len(complete.get("asset_results") or []),
        unit="count",
    )
    _add_metric(
        rows,
        category="comparability",
        scope="complete_analysis",
        metric="territory_results_count",
        value=len(complete.get("territory_results") or []),
        unit="count",
    )
    for metric in ("asset_count_original", "asset_count_points", "total_exposure_eur"):
        _add_metric(
            rows,
            category="comparability",
            scope="exposure_summary",
            metric=metric,
            value=exposure.get(metric),
            unit="eur" if metric.endswith("_eur") else "count",
        )
    for group in ("geometry_type_counts", "exposure_category_counts", "asset_type_counts"):
        values = exposure.get(group) if isinstance(exposure.get(group), dict) else {}
        for key, value in values.items():
            _add_metric(
                rows,
                category="comparability",
                scope=f"exposure_summary.{group}",
                metric=str(key),
                value=value,
                unit="count",
            )

    counts = (
        summary.get("network_states", {}).get("canonical_service_unit_counts")
        if isinstance(summary.get("network_states"), dict)
        else {}
    )
    if isinstance(counts, dict):
        for hazard, services in counts.items():
            if not isinstance(services, dict):
                continue
            for service, value in services.items():
                _add_metric(
                    rows,
                    category="comparability",
                    scope="network_states.canonical_service_unit_counts",
                    hazard=str(hazard),
                    service=str(service),
                    metric="total_units",
                    value=value,
                    unit="count",
                )


def _extract_portfolio_metrics(rows: dict[tuple[str, ...], dict[str, Any]], complete: dict[str, Any]) -> None:
    portfolio = complete.get("portfolio_results") if isinstance(complete.get("portfolio_results"), dict) else {}
    for hazard in HAZARDS:
        hazard_payload = portfolio.get(hazard) if isinstance(portfolio.get(hazard), dict) else {}
        for metric in PORTFOLIO_METRICS:
            _add_metric(
                rows,
                category="portfolio",
                scope="portfolio_results",
                hazard=hazard,
                metric=metric,
                value=hazard_payload.get(metric),
                unit="eur",
            )
        for field, metric_name in (
            ("components_direct_eai_eur", "direct_eai_component_eur"),
            ("components_direct_percentile_99_loss_eur", "p99_component_loss_eur"),
        ):
            components = hazard_payload.get(field) if isinstance(hazard_payload.get(field), dict) else {}
            for component, value in components.items():
                _add_metric(
                    rows,
                    category="portfolio_component",
                    scope=f"portfolio_results.{field}",
                    hazard=hazard,
                    component=str(component),
                    metric=metric_name,
                    value=value,
                    unit="eur",
                )

    social = portfolio.get("social_impact_worst_case_summary", portfolio.get("social_impact_summary"))
    if isinstance(social, dict):
        for hazard in HAZARDS:
            hazard_social = social.get(hazard) if isinstance(social.get(hazard), dict) else {}
            for metric in SOCIAL_METRICS:
                _add_metric(
                    rows,
                    category="population",
                    scope="portfolio_results.social_impact_worst_case_summary",
                    hazard=hazard,
                    scenario="worst_case",
                    metric=metric,
                    value=hazard_social.get(metric),
                    unit="people",
                )


def _extract_scenario_metrics(rows: dict[tuple[str, ...], dict[str, Any]], summary: dict[str, Any]) -> None:
    graph_inputs = summary.get("scientific_graph_inputs") if isinstance(summary.get("scientific_graph_inputs"), dict) else {}
    state_tables = graph_inputs.get("state_damage_tables") if isinstance(graph_inputs.get("state_damage_tables"), dict) else {}
    social_by_scenario = (
        graph_inputs.get("social_impact_by_scenario")
        if isinstance(graph_inputs.get("social_impact_by_scenario"), dict)
        else {}
    )
    network_by_scenario = (
        graph_inputs.get("network_state_service_distribution_by_scenario")
        if isinstance(graph_inputs.get("network_state_service_distribution_by_scenario"), dict)
        else {}
    )

    for scenario in SCENARIOS:
        rows_for_scenario = state_tables.get(scenario)
        if isinstance(rows_for_scenario, list):
            for state_row in rows_for_scenario:
                if not isinstance(state_row, dict):
                    continue
                class_key = str(state_row.get("class_key") or "")
                class_label = str(state_row.get("class_label") or "")
                for hazard in HAZARDS:
                    hazard_row = state_row.get(hazard) if isinstance(state_row.get(hazard), dict) else {}
                    state_pct = hazard_row.get("state_pct") if isinstance(hazard_row.get("state_pct"), dict) else {}
                    for state in STATE_KEYS:
                        _add_metric(
                            rows,
                            category="network_state_pct",
                            scope="scientific_graph_inputs.state_damage_tables",
                            hazard=hazard,
                            scenario=scenario,
                            class_key=class_key,
                            metric=f"state_pct_{state}",
                            value=state_pct.get(state),
                            unit="pct",
                            label=class_label,
                        )
                    for metric in NETWORK_DAMAGE_METRICS:
                        _add_metric(
                            rows,
                            category="network_damage",
                            scope="scientific_graph_inputs.state_damage_tables",
                            hazard=hazard,
                            scenario=scenario,
                            class_key=class_key,
                            metric=metric,
                            value=hazard_row.get(metric),
                            unit="eur" if metric.endswith("_eur") else "",
                            label=class_label,
                        )
                    components = (
                        hazard_row.get("damage_components_eur")
                        if isinstance(hazard_row.get("damage_components_eur"), dict)
                        else {}
                    )
                    for component, value in components.items():
                        _add_metric(
                            rows,
                            category="scenario_component_damage",
                            scope="scientific_graph_inputs.state_damage_tables.damage_components_eur",
                            hazard=hazard,
                            scenario=scenario,
                            class_key=class_key,
                            component=str(component),
                            metric="damage_component_eur",
                            value=value,
                            unit="eur",
                            label=class_label,
                        )

        social_payload = social_by_scenario.get(scenario) if isinstance(social_by_scenario, dict) else {}
        if isinstance(social_payload, dict):
            for hazard in HAZARDS:
                hazard_social = social_payload.get(hazard) if isinstance(social_payload.get(hazard), dict) else {}
                for metric in SOCIAL_METRICS:
                    _add_metric(
                        rows,
                        category="population",
                        scope="scientific_graph_inputs.social_impact_by_scenario",
                        hazard=hazard,
                        scenario=scenario,
                        metric=metric,
                        value=hazard_social.get(metric),
                        unit="people",
                    )
                state_breakdown = (
                    hazard_social.get("state_breakdown")
                    if isinstance(hazard_social.get("state_breakdown"), dict)
                    else {}
                )
                for service, service_states in state_breakdown.items():
                    if not isinstance(service_states, dict):
                        continue
                    for state, value in service_states.items():
                        _add_metric(
                            rows,
                            category="population_state_count",
                            scope="scientific_graph_inputs.social_impact_by_scenario.state_breakdown",
                            hazard=hazard,
                            scenario=scenario,
                            service=str(service),
                            metric=f"population_{state}",
                            value=value,
                            unit="people",
                        )

        network_payload = network_by_scenario.get(scenario) if isinstance(network_by_scenario, dict) else {}
        if isinstance(network_payload, dict):
            for hazard in HAZARDS:
                hazard_network = network_payload.get(hazard) if isinstance(network_payload.get(hazard), dict) else {}
                for service, service_states in hazard_network.items():
                    if not isinstance(service_states, dict):
                        continue
                    for state, value in service_states.items():
                        _add_metric(
                            rows,
                            category="network_state_units",
                            scope="scientific_graph_inputs.network_state_service_distribution_by_scenario",
                            hazard=hazard,
                            scenario=scenario,
                            service=str(service),
                            metric=str(state),
                            value=value,
                            unit="count",
                        )


def _extract_summary_flat_metrics(rows: dict[tuple[str, ...], dict[str, Any]], summary: dict[str, Any]) -> None:
    portfolio_summary = summary.get("portfolio_summary") if isinstance(summary.get("portfolio_summary"), dict) else {}
    for hazard in HAZARDS:
        payload = portfolio_summary.get(hazard) if isinstance(portfolio_summary.get(hazard), dict) else {}
        for metric, value in payload.items():
            _add_metric(
                rows,
                category="scenario_summary",
                scope="scientific_web_summary.portfolio_summary",
                hazard=hazard,
                scenario="all",
                metric=str(metric),
                value=value,
                unit="eur" if str(metric).endswith("_eur") else "",
            )


def _extract_metrics(complete: dict[str, Any], summary: dict[str, Any]) -> dict[tuple[str, ...], dict[str, Any]]:
    rows: dict[tuple[str, ...], dict[str, Any]] = {}
    _extract_exposure_metrics(rows, complete, summary)
    _extract_portfolio_metrics(rows, complete)
    _extract_summary_flat_metrics(rows, summary)
    _extract_scenario_metrics(rows, summary)
    return rows


def _merge_metrics(
    full_rows: dict[tuple[str, ...], dict[str, Any]],
    v1_rows: dict[tuple[str, ...], dict[str, Any]],
    v2_rows: dict[tuple[str, ...], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    row_sets = [full_rows, v1_rows]
    if v2_rows is not None:
        row_sets.append(v2_rows)
    all_keys = set().union(*(set(row_map) for row_map in row_sets))
    for key in sorted(all_keys):
        base = full_rows.get(key) or v1_rows.get(key) or (v2_rows or {}).get(key) or {}
        full_value = full_rows.get(key, {}).get("value")
        v1_value = v1_rows.get(key, {}).get("value")
        v2_value = (v2_rows or {}).get(key, {}).get("value") if v2_rows is not None else None
        delta_abs = v1_value - full_value if full_value is not None and v1_value is not None else None
        delta_pct = _delta_pct(full_value, v1_value)
        v2_delta_abs = v2_value - full_value if full_value is not None and v2_value is not None else None
        v2_delta_pct = _delta_pct(full_value, v2_value)
        v2_vs_v1_delta_abs = v2_value - v1_value if v1_value is not None and v2_value is not None else None
        v2_vs_v1_delta_pct = _delta_pct(v1_value, v2_value)
        missing_in = []
        if key not in full_rows:
            missing_in.append("full")
        if key not in v1_rows:
            missing_in.append("sample_v1")
        if v2_rows is not None and key not in v2_rows:
            missing_in.append("sample_v2")
        merged.append(
            {
                "category": base.get("category", ""),
                "scope": base.get("scope", ""),
                "hazard": base.get("hazard", ""),
                "scenario": base.get("scenario", ""),
                "service": base.get("service", ""),
                "class_key": base.get("class_key", ""),
                "component": base.get("component", ""),
                "metric": base.get("metric", ""),
                "unit": base.get("unit", ""),
                "label": base.get("label", ""),
                "full_value": full_value,
                "sample_v1_value": v1_value,
                "sample_v2_value": v2_value,
                "delta_abs": delta_abs,
                "delta_pct": delta_pct,
                "v2_delta_abs": v2_delta_abs,
                "v2_delta_pct": v2_delta_pct,
                "v2_vs_v1_delta_abs": v2_vs_v1_delta_abs,
                "v2_vs_v1_delta_pct": v2_vs_v1_delta_pct,
                "missing_in": ",".join(missing_in),
            }
        )
    return merged


def _build_comparability_checks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in rows:
        if row["category"] != "comparability":
            continue
        full_value = row.get("full_value")
        v1_value = row.get("sample_v1_value")
        v2_value = row.get("sample_v2_value")
        delta_abs = row.get("delta_abs")
        v2_delta_abs = row.get("v2_delta_abs")
        sample_v1_match = (
            full_value is not None
            and v1_value is not None
            and delta_abs is not None
            and abs(float(delta_abs)) <= max(1e-6, abs(float(full_value)) * 1e-10)
        )
        sample_v2_match = None
        if v2_value is not None:
            sample_v2_match = (
                full_value is not None
                and v2_delta_abs is not None
                and abs(float(v2_delta_abs)) <= max(1e-6, abs(float(full_value)) * 1e-10)
            )
        match_values = [sample_v1_match]
        if sample_v2_match is not None:
            match_values.append(sample_v2_match)
        checks.append(
            {
                "scope": row["scope"],
                "hazard": row["hazard"],
                "service": row["service"],
                "metric": row["metric"],
                "unit": row["unit"],
                "full_value": full_value,
                "sample_v1_value": v1_value,
                "sample_v2_value": v2_value,
                "delta_abs": delta_abs,
                "v2_delta_abs": v2_delta_abs,
                "sample_v1_match": sample_v1_match,
                "sample_v2_match": sample_v2_match,
                "match": all(match_values),
            }
        )
    return checks


def _sample_manifest_rows(manifest: dict[str, Any], sample_key: str, sample_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    providers = manifest.get("providers") if isinstance(manifest.get("providers"), dict) else {}
    for provider, provider_payload in providers.items():
        if not isinstance(provider_payload, dict):
            continue
        tracks = provider_payload.get("tracks") if isinstance(provider_payload.get("tracks"), list) else []
        weights = [_safe_float(track.get("sample_weight")) for track in tracks if isinstance(track, dict)]
        weights = [weight for weight in weights if weight is not None]
        frequencies = [_safe_float(track.get("frequency_annual")) for track in tracks if isinstance(track, dict)]
        frequencies = [frequency for frequency in frequencies if frequency is not None]
        category_counts: Counter[str] = Counter()
        stratum_counts: Counter[str] = Counter()
        category_weight_sum: defaultdict[str, float] = defaultdict(float)
        stratum_weight_sum: defaultdict[str, float] = defaultdict(float)
        category_frequency_sum: defaultdict[str, float] = defaultdict(float)
        stratum_frequency_sum: defaultdict[str, float] = defaultdict(float)
        for track in tracks:
            if not isinstance(track, dict):
                continue
            weight = _safe_float(track.get("sample_weight")) or 0.0
            frequency = _safe_float(track.get("frequency_annual")) or 0.0
            category = str(track.get("category"))
            stratum = str(track.get("stratum"))
            category_counts[category] += 1
            stratum_counts[stratum] += 1
            category_weight_sum[category] += weight
            stratum_weight_sum[stratum] += weight
            category_frequency_sum[category] += frequency
            stratum_frequency_sum[stratum] += frequency

        rows.append(
            {
                "sample_key": sample_key,
                "sample_label": sample_label,
                "provider": provider,
                "row_type": "overview",
                "bucket": "all",
                "selection_method": manifest.get("selection_method"),
                "selection_score_kind": manifest.get("selection_score_kind"),
                "sample_size": provider_payload.get("sample_size"),
                "population_track_count": provider_payload.get("population_track_count"),
                "selected_track_count": len(tracks),
                "seed": provider_payload.get("seed"),
                "score": provider_payload.get("score"),
                "sample_weight_min": min(weights) if weights else None,
                "sample_weight_max": max(weights) if weights else None,
                "sample_weight_mean": sum(weights) / len(weights) if weights else None,
                "sample_weight_sum": sum(weights) if weights else None,
                "frequency_annual_sum": sum(frequencies) if frequencies else None,
                "selected_count": len(tracks),
                "selected_share_pct": 100.0,
            }
        )

        for bucket, count in sorted(category_counts.items(), key=lambda item: item[0]):
            rows.append(
                {
                    "sample_key": sample_key,
                    "sample_label": sample_label,
                    "provider": provider,
                    "row_type": "category",
                    "bucket": bucket,
                    "selection_method": manifest.get("selection_method"),
                    "selection_score_kind": manifest.get("selection_score_kind"),
                    "sample_size": provider_payload.get("sample_size"),
                    "population_track_count": provider_payload.get("population_track_count"),
                    "selected_track_count": len(tracks),
                    "seed": provider_payload.get("seed"),
                    "score": provider_payload.get("score"),
                    "sample_weight_min": "",
                    "sample_weight_max": "",
                    "sample_weight_mean": "",
                    "sample_weight_sum": category_weight_sum[bucket],
                    "frequency_annual_sum": category_frequency_sum[bucket],
                    "selected_count": count,
                    "selected_share_pct": (count / len(tracks) * 100.0) if tracks else None,
                }
            )
        for bucket, count in sorted(stratum_counts.items(), key=lambda item: item[0]):
            rows.append(
                {
                    "sample_key": sample_key,
                    "sample_label": sample_label,
                    "provider": provider,
                    "row_type": "stratum",
                    "bucket": bucket,
                    "selection_method": manifest.get("selection_method"),
                    "selection_score_kind": manifest.get("selection_score_kind"),
                    "sample_size": provider_payload.get("sample_size"),
                    "population_track_count": provider_payload.get("population_track_count"),
                    "selected_track_count": len(tracks),
                    "seed": provider_payload.get("seed"),
                    "score": provider_payload.get("score"),
                    "sample_weight_min": "",
                    "sample_weight_max": "",
                    "sample_weight_mean": "",
                    "sample_weight_sum": stratum_weight_sum[bucket],
                    "frequency_annual_sum": stratum_frequency_sum[bucket],
                    "selected_count": count,
                    "selected_share_pct": (count / len(tracks) * 100.0) if tracks else None,
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})


def _top_delta_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    def has_significant_reference(row: dict[str, Any], reference_column: str) -> bool:
        full_value = abs(float(row.get(reference_column) or 0.0))
        unit = str(row.get("unit") or "")
        if unit == "eur":
            return full_value >= 1_000_000.0
        if unit in {"people", "count"}:
            return full_value >= 1.0
        return full_value >= 1.0

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    comparisons = (
        ("v1_vs_full", "sample_v1_value", "full_value", "delta_abs", "delta_pct"),
        ("v2_vs_full", "sample_v2_value", "full_value", "v2_delta_abs", "v2_delta_pct"),
        ("v2_vs_v1", "sample_v2_value", "sample_v1_value", "v2_vs_v1_delta_abs", "v2_vs_v1_delta_pct"),
    )
    for comparison, compared_column, reference_column, delta_column, pct_column in comparisons:
        comparable = [
            row
            for row in rows
            if row.get(compared_column) is not None
            and row.get(reference_column) is not None
            and row.get(delta_column) is not None
            and row.get(pct_column) is not None
            and row.get("category") != "comparability"
            and abs(float(row.get(delta_column) or 0.0)) > 0.0
        ]
        by_abs = sorted(comparable, key=lambda row: abs(float(row[delta_column])), reverse=True)[:limit]
        by_pct = sorted(
            [row for row in comparable if has_significant_reference(row, reference_column)],
            key=lambda row: abs(float(row[pct_column])),
            reverse=True,
        )[:limit]
        for basis, ranked in (("abs", by_abs), ("pct", by_pct)):
            for rank, row in enumerate(ranked, start=1):
                key = _metric_id(row)
                seen_key = (comparison, basis, *key)
                if seen_key in seen:
                    continue
                seen.add(seen_key)
                payload = dict(row)
                payload["comparison"] = comparison
                payload["ranking_basis"] = basis
                payload["rank"] = rank
                payload["reference_value"] = row.get(reference_column)
                payload["compared_value"] = row.get(compared_column)
                payload["comparison_delta_abs"] = row.get(delta_column)
                payload["comparison_delta_pct"] = row.get(pct_column)
                out.append(payload)
    return out


def _find_metric(
    rows: list[dict[str, Any]],
    *,
    category: str,
    hazard: str,
    metric: str,
    scenario: str = "all",
    component: str = "",
    class_key: str = "",
) -> dict[str, Any] | None:
    for row in rows:
        if (
            row.get("category") == category
            and row.get("hazard") == hazard
            and row.get("scenario") == scenario
            and row.get("metric") == metric
            and row.get("component", "") == component
            and row.get("class_key", "") == class_key
        ):
            return row
    return None


def _markdown_table(headers: list[str], records: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    lines.extend("| " + " | ".join(record) + " |" for record in records)
    return lines


def _write_analysis_markdown(
    path: Path,
    *,
    specs: list[RunSpec],
    rows: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    sample_manifest_rows: list[dict[str, Any]],
    missing_metrics: list[dict[str, Any]],
) -> None:
    full_spec = next(spec for spec in specs if spec.key == "full")
    v1_spec = next(spec for spec in specs if spec.key == "sample_v1")
    v2_spec = next((spec for spec in specs if spec.key == "sample_v2"), None)
    has_v2 = v2_spec is not None
    lines: list[str] = []
    title = "full tracks vs samples V1/V2 5000" if has_v2 else "full tracks vs sample V1 5000"
    lines.append(f"# Analyse comparative Guadeloupe: {title}")
    lines.append("")
    lines.append(f"Generation: `{_utc_now()}`")
    lines.append("")
    lines.append("## Synthese")
    lines.append("")
    if has_v2:
        lines.append(
            f"Cette analyse compare le run de reference full tracks `{full_spec.run_id}` aux runs "
            f"sample V1 `{v1_spec.run_id}` et sample V2 `{v2_spec.run_id}`. Les deltas `V1 - full` "
            "et `V2 - full` quantifient l'ecart de chaque echantillon 5000 tracks a la population "
            "complete; `V2 - V1` isole l'effet de methode entre deux echantillons de meme taille."
        )
    else:
        lines.append(
            f"Cette analyse compare le run de reference full tracks `{full_spec.run_id}` au run "
            f"sample V1 5000 tracks `{v1_spec.run_id}`. Les deltas sont calcules comme `V1 - full`, "
            "donc un delta positif signifie que le sample V1 surestime la reference full tracks."
        )
        lines.append("")
        lines.append(
            "Avec seulement full vs V1, l'analyse quantifie l'effet combine du passage a 5000 tracks "
            "et de la methode V1. La separation stricte entre effet de taille et effet de methode "
            "sera possible quand le run V2 sera ajoute."
        )
    lines.append("")

    lines.append("## Controle de comparabilite")
    lines.append("")
    critical = [
        check
        for check in checks
        if check["metric"] in {"asset_results_count", "territory_results_count", "total_exposure_eur", "asset_count_original", "asset_count_points"}
        or check["scope"] == "network_states.canonical_service_unit_counts"
    ]
    critical_records = []
    for check in critical[:30]:
        unit = str(check.get("unit") or "")
        status_parts = ["V1 OK" if check.get("sample_v1_match") else "V1 DIFF"]
        if check.get("sample_v2_match") is not None:
            status_parts.append("V2 OK" if check.get("sample_v2_match") else "V2 DIFF")
        critical_records.append(
            [
                str(check["scope"]),
                str(check["hazard"]),
                str(check["service"]),
                str(check["metric"]),
                _fmt_num(check.get("full_value"), unit),
                _fmt_num(check.get("sample_v1_value"), unit),
                _fmt_num(check.get("sample_v2_value"), unit) if has_v2 else "-",
                ", ".join(status_parts),
            ]
        )
    lines.extend(_markdown_table(["Scope", "Alea", "Service", "Metrique", "Full", "V1", "V2", "Statut"], critical_records))
    lines.append("")

    all_match = all(check.get("match") for check in critical)
    if all_match:
        lines.append("Les controles d'exposition et d'unites reseau critiques sont identiques entre les runs compares.")
    else:
        lines.append("Attention: au moins un controle critique differe; interpreter les deltas avec prudence.")
    lines.append("")

    def comparison_cells(row: dict[str, Any], unit: str) -> list[str]:
        cells = [
            _fmt_num(row.get("full_value"), unit),
            _fmt_num(row.get("sample_v1_value"), unit),
            _fmt_num(row.get("delta_abs"), unit),
            _fmt_delta_pct(row.get("delta_pct")),
        ]
        if has_v2:
            cells.extend(
                [
                    _fmt_num(row.get("sample_v2_value"), unit),
                    _fmt_num(row.get("v2_delta_abs"), unit),
                    _fmt_delta_pct(row.get("v2_delta_pct")),
                    _fmt_num(row.get("v2_vs_v1_delta_abs"), unit),
                    _fmt_delta_pct(row.get("v2_vs_v1_delta_pct")),
                ]
            )
        return cells

    comparison_headers = ["Full", "V1", "V1-Full", "V1-Full %"]
    if has_v2:
        comparison_headers.extend(["V2", "V2-Full", "V2-Full %", "V2-V1", "V2-V1 %"])

    lines.append("## Impacts portefeuille")
    lines.append("")
    portfolio_records: list[list[str]] = []
    for hazard in HAZARDS:
        for metric in ("eai_eur", "eai_direct_eur", "eai_indirect_eur", "percentile_99_loss_eur", "pml_100_eur", "pml_1000_eur"):
            row = _find_metric(rows, category="portfolio", hazard=hazard, metric=metric)
            if not row:
                continue
            portfolio_records.append(
                [
                    hazard,
                    metric,
                    *comparison_cells(row, "eur"),
                ]
            )
    lines.extend(_markdown_table(["Alea", "Metrique", *comparison_headers], portfolio_records))
    lines.append("")

    lines.append("## Composants EAI direct")
    lines.append("")
    component_records: list[list[str]] = []
    for hazard in HAZARDS:
        for component in ("wind", "rain", "surge", "combined_capped"):
            row = _find_metric(
                rows,
                category="portfolio_component",
                hazard=hazard,
                metric="direct_eai_component_eur",
                component=component,
            )
            if not row:
                continue
            component_records.append(
                [
                    hazard,
                    component,
                    *comparison_cells(row, "eur"),
                ]
            )
    lines.extend(_markdown_table(["Alea", "Composant", *comparison_headers], component_records))
    lines.append("")

    lines.append("## Population et reseaux")
    lines.append("")
    population_records: list[list[str]] = []
    for hazard in HAZARDS:
        for scenario in ("rp50", "rp100", "rp1000"):
            for metric in ("total_population_affected_any_network", "total_without_eau_aep", "total_with_degraded_eau_eu"):
                row = _find_metric(
                    rows,
                    category="population",
                    hazard=hazard,
                    scenario=scenario,
                    metric=metric,
                )
                if not row:
                    continue
                population_records.append(
                    [
                        hazard,
                        scenario,
                        metric,
                        *comparison_cells(row, "people"),
                    ]
                )
    lines.extend(_markdown_table(["Alea", "Scenario", "Metrique", *comparison_headers], population_records))
    lines.append("")

    lines.append("## Plus grands ecarts")
    lines.append("")
    top_rows = _top_delta_rows(rows, 10)
    top_records = []
    for row in top_rows:
        unit = str(row.get("unit") or "")
        top_records.append(
            [
                str(row.get("comparison")),
                str(row.get("ranking_basis")),
                str(row.get("rank")),
                str(row.get("category")),
                str(row.get("hazard")),
                str(row.get("scenario")),
                str(row.get("service") or row.get("class_key") or row.get("component")),
                str(row.get("metric")),
                _fmt_num(row.get("reference_value"), unit),
                _fmt_num(row.get("compared_value"), unit),
                _fmt_num(row.get("comparison_delta_abs"), unit),
                _fmt_delta_pct(row.get("comparison_delta_pct")),
            ]
        )
    lines.extend(
        _markdown_table(
            ["Comparaison", "Base", "Rang", "Categorie", "Alea", "Scenario", "Objet", "Metrique", "Reference", "Compare", "Delta", "Delta %"],
            top_records,
        )
    )
    lines.append("")

    lines.append("## Echantillons 5000")
    lines.append("")
    overview = [row for row in sample_manifest_rows if row.get("row_type") == "overview"]
    sample_records = []
    for row in overview:
        sample_records.append(
            [
                str(row.get("sample_key")),
                str(row.get("provider")),
                str(row.get("selection_method")),
                str(row.get("selection_score_kind") or ""),
                str(row.get("sample_size")),
                str(row.get("population_track_count")),
                str(row.get("seed")),
                _fmt_num(_safe_float(row.get("score"))),
                _fmt_num(_safe_float(row.get("sample_weight_min"))),
                _fmt_num(_safe_float(row.get("sample_weight_max"))),
                _fmt_num(_safe_float(row.get("sample_weight_mean"))),
            ]
        )
    lines.extend(
        _markdown_table(
            ["Sample", "Provider", "Methode", "Score kind", "Tracks", "Population tracks", "Seed", "Score", "Poids min", "Poids max", "Poids moyen"],
            sample_records,
        )
    )
    lines.append("")

    if missing_metrics:
        lines.append("## Metriques manquantes")
        lines.append("")
        lines.append(f"{len(missing_metrics)} metriques sont absentes d'au moins un run; elles sont listees dans `comparison-data.json`.")
        lines.append("")
    else:
        lines.append("## Metriques manquantes")
        lines.append("")
        lines.append("Aucune metrique comparable attendue n'est absente d'un des runs compares.")
        lines.append("")

    lines.append("## Fichiers produits")
    lines.append("")
    lines.append("- `metrics_comparison.csv`: toutes les metriques comparees.")
    lines.append("- `top_deltas.csv`: plus grands ecarts absolus et relatifs.")
    lines.append("- `sample_manifest_summary.csv`: structure des echantillons V1/V2.")
    lines.append("- `comparison-data.json`: payload structure incluant les colonnes V2.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_outputs(
    output_dir: Path,
    *,
    specs: list[RunSpec],
    merged_rows: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "metrics_comparison.csv"
    top_path = output_dir / "top_deltas.csv"
    sample_path = output_dir / "sample_manifest_summary.csv"
    data_path = output_dir / "comparison-data.json"
    analysis_path = output_dir / "analysis.md"

    metric_fields = [
        "category",
        "scope",
        "hazard",
        "scenario",
        "service",
        "class_key",
        "component",
        "metric",
        "unit",
        "label",
        "full_value",
        "sample_v1_value",
        "sample_v2_value",
        "delta_abs",
        "delta_pct",
        "v2_delta_abs",
        "v2_delta_pct",
        "v2_vs_v1_delta_abs",
        "v2_vs_v1_delta_pct",
        "missing_in",
    ]
    _write_csv(metrics_path, merged_rows, metric_fields)
    _write_csv(
        top_path,
        _top_delta_rows(merged_rows, 50),
        [
            "comparison",
            "ranking_basis",
            "rank",
            "reference_value",
            "compared_value",
            "comparison_delta_abs",
            "comparison_delta_pct",
            *metric_fields,
        ],
    )
    _write_csv(
        sample_path,
        sample_rows,
        [
            "sample_key",
            "sample_label",
            "provider",
            "row_type",
            "bucket",
            "selection_method",
            "selection_score_kind",
            "sample_size",
            "population_track_count",
            "selected_track_count",
            "seed",
            "score",
            "sample_weight_min",
            "sample_weight_max",
            "sample_weight_mean",
            "sample_weight_sum",
            "frequency_annual_sum",
            "selected_count",
            "selected_share_pct",
        ],
    )
    missing_metrics = [row for row in merged_rows if row.get("missing_in")]
    _write_analysis_markdown(
        analysis_path,
        specs=specs,
        rows=merged_rows,
        checks=checks,
        sample_manifest_rows=sample_rows,
        missing_metrics=missing_metrics,
    )
    payload = {
        "schema_version": "guadeloupe_track_sampling_comparison.v2",
        "generated_at": _utc_now(),
        "territory": "guadeloupe",
        "baseline_key": "full",
        "runs": [
            {
                "key": spec.key,
                "label": spec.label,
                "run_id": spec.run_id,
                "track_mode": spec.track_mode,
                "complete_path": str(spec.complete_path),
                "summary_path": str(spec.summary_path),
                "manifest_path": str(spec.manifest_path) if spec.manifest_path else None,
            }
            for spec in specs
        ],
        "delta_convention": {
            "delta_abs": "sample_v1 - full",
            "delta_pct": "(sample_v1 - full) / full * 100",
            "v2_delta_abs": "sample_v2 - full",
            "v2_delta_pct": "(sample_v2 - full) / full * 100",
            "v2_vs_v1_delta_abs": "sample_v2 - sample_v1",
            "v2_vs_v1_delta_pct": "(sample_v2 - sample_v1) / sample_v1 * 100",
        },
        "comparability_checks": checks,
        "missing_metrics": missing_metrics,
        "metrics": merged_rows,
        "sample_manifest_summary": sample_rows,
        "v2_extension_notes": {
            "status": "complete" if any(spec.key == "sample_v2" for spec in specs) else "pending",
            "expected_columns": ["sample_v2_value", "v2_delta_abs", "v2_delta_pct"],
        },
    }
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "analysis": str(analysis_path),
        "metrics": str(metrics_path),
        "top_deltas": str(top_path),
        "sample_manifest_summary": str(sample_path),
        "comparison_data": str(data_path),
    }


def _make_specs(args: argparse.Namespace) -> list[RunSpec]:
    full_archive_dir = Path(args.full_archive_dir)
    v1_web_data_dir = Path(args.v1_web_data_dir)
    specs = [
        RunSpec(
            key="full",
            label="Full tracks reference",
            run_id=args.full_run_id,
            complete_path=full_archive_dir / "guadeloupe-complete-analysis.json",
            summary_path=full_archive_dir / "guadeloupe-scientific-web-summary.json",
            track_mode="full_tracks",
        ),
        RunSpec(
            key="sample_v1",
            label="Sample V1 5000 tracks",
            run_id=args.v1_run_id,
            complete_path=v1_web_data_dir / "guadeloupe-complete-analysis.json",
            summary_path=v1_web_data_dir / "guadeloupe-scientific-web-summary.json",
            track_mode="sample_v1_5000",
            manifest_path=Path(args.v1_manifest),
        ),
    ]
    if not args.no_v2:
        v2_web_data_dir = Path(args.v2_web_data_dir)
        specs.append(
            RunSpec(
                key="sample_v2",
                label="Sample V2 5000 tracks",
                run_id=args.v2_run_id,
                complete_path=v2_web_data_dir / "guadeloupe-complete-analysis.json",
                summary_path=v2_web_data_dir / "guadeloupe-scientific-web-summary.json",
                track_mode="sample_v2_5000",
                manifest_path=Path(args.v2_manifest),
            )
        )
    return specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Guadeloupe full-track complete-analysis outputs with 5000-track V1/V2 sample runs."
    )
    parser.add_argument("--full-run-id", default="20260711_071243")
    parser.add_argument("--v1-run-id", default="20260711_074032")
    parser.add_argument("--v2-run-id", default="20260720_134606")
    parser.add_argument("--full-archive-dir", default=str(DEFAULT_FULL_ARCHIVE_DIR))
    parser.add_argument("--v1-web-data-dir", default=str(DEFAULT_V1_WEB_DATA_DIR))
    parser.add_argument("--v2-web-data-dir", default=str(DEFAULT_V2_WEB_DATA_DIR))
    parser.add_argument("--v1-manifest", default=str(DEFAULT_V1_MANIFEST))
    parser.add_argument("--v2-manifest", default=str(DEFAULT_V2_MANIFEST))
    parser.add_argument("--no-v2", action="store_true", help="Generate the older two-run full-vs-V1 comparison only.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    specs = _make_specs(args)
    loaded: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for spec in specs:
        loaded[spec.key] = (_load_json(spec.complete_path), _load_json(spec.summary_path))

    extracted = {key: _extract_metrics(*payloads) for key, payloads in loaded.items()}
    merged_rows = _merge_metrics(
        extracted["full"],
        extracted["sample_v1"],
        extracted.get("sample_v2"),
    )
    checks = _build_comparability_checks(merged_rows)

    sample_rows: list[dict[str, Any]] = []
    for spec in specs:
        if spec.key == "full":
            continue
        if spec.manifest_path is None:
            raise ComparisonError(f"Manifest path is required for {spec.key}")
        sample_rows.extend(_sample_manifest_rows(_load_json(spec.manifest_path), spec.key, spec.label))

    paths = _write_outputs(
        Path(args.output_dir),
        specs=specs,
        merged_rows=merged_rows,
        checks=checks,
        sample_rows=sample_rows,
    )
    print("[ok] Guadeloupe track sampling comparison generated")
    for label, path in paths.items():
        print(f"  - {label}: {path}")
    print(f"  - metrics compared: {len(merged_rows)}")
    print(f"  - missing metrics: {sum(1 for row in merged_rows if row.get('missing_in'))}")
    print(f"  - comparability checks: {sum(1 for check in checks if check.get('match'))}/{len(checks)} ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ComparisonError as exc:
        print(f"[error] {exc}")
        raise SystemExit(2)
