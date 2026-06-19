#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "outputs" / "complete-analysis-runs"
DEFAULT_TERRITORIES = ("guadeloupe", "martinique")
HAZARDS = ("storm", "storm_cmcc")
SCENARIOS = ("annual", "rp50", "rp100", "p99")
STATE_KEYS = ("S0", "S1", "S2", "S3")


class ComparisonError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunContext:
    run_id: str
    manifest: dict[str, Any]



def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ComparisonError(f"Missing required file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError(f"Expected JSON object in {path}")
    return payload



def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _delta_pct(a: float, b: float) -> float | None:
    if abs(a) < 1e-12:
        return None
    return ((b - a) / a) * 100.0



def _find_run_context(run_id: str) -> RunContext:
    manifest_path = RUNS_ROOT / run_id / "manifest.json"
    manifest = _load_json(manifest_path)

    status = str(manifest.get("status") or "").strip().lower()
    if status != "success":
        raise ComparisonError(
            f"Run {run_id} is not success (status={status!r}); explicit failure by design"
        )

    params = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    dyn = params.get("dynamic_max_tracks", params.get("requested_dynamic_max_tracks"))
    if int(_safe_float(dyn)) != 1500:
        raise ComparisonError(
            f"Run {run_id} is not a 1500-track run (dynamic_max_tracks={dyn!r})"
        )

    return RunContext(run_id=run_id, manifest=manifest)



def _territory_page_path(run_id: str, territory: str) -> Path:
    suffix = "page2" if territory == "martinique" else "page1"
    return RUNS_ROOT / run_id / "territories" / territory / "web" / "data" / f"{territory}-{suffix}-analysis.json"



def _territory_complete_path(run_id: str, territory: str) -> Path:
    return RUNS_ROOT / run_id / "territories" / territory / "web" / "data" / f"{territory}-complete-analysis.json"



def _require_territory_payloads(run_id: str, territory: str) -> tuple[dict[str, Any], dict[str, Any]]:
    page_payload = _load_json(_territory_page_path(run_id, territory))
    complete_payload = _load_json(_territory_complete_path(run_id, territory))

    impact = page_payload.get("impact")
    if not isinstance(impact, dict):
        raise ComparisonError(f"Missing impact object in {_territory_page_path(run_id, territory)}")

    summary_metrics = impact.get("summary_metrics")
    state_damage_tables = impact.get("state_damage_tables")
    if not isinstance(summary_metrics, dict):
        raise ComparisonError(f"Missing impact.summary_metrics in {_territory_page_path(run_id, territory)}")
    if not isinstance(state_damage_tables, dict):
        raise ComparisonError(f"Missing impact.state_damage_tables in {_territory_page_path(run_id, territory)}")

    portfolio = complete_payload.get("portfolio_results")
    territory_results = complete_payload.get("territory_results")
    if not isinstance(portfolio, dict):
        raise ComparisonError(f"Missing portfolio_results in {_territory_complete_path(run_id, territory)}")
    if not isinstance(territory_results, list) or not territory_results:
        raise ComparisonError(f"Missing territory_results[] in {_territory_complete_path(run_id, territory)}")

    social = portfolio.get("social_impact_worst_case_summary", portfolio.get("social_impact_summary"))
    if not isinstance(social, dict):
        raise ComparisonError(
            f"Missing social impact summary in {_territory_complete_path(run_id, territory)}"
        )

    return page_payload, complete_payload



def _extract_monetary_rows(run_id: str, territory: str, page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary_metrics = page_payload["impact"]["summary_metrics"]

    metric_map = {
        "eai_total_eur": "eai_total_eur",
        "rp50_total_loss_eur": "rp50_total_loss_eur",
        "rp100_total_loss_eur": "rp100_total_loss_eur",
        "p99_total_loss_eur": "p99_total_loss_eur",
    }

    for hazard in HAZARDS:
        hz_payload = summary_metrics.get(hazard)
        if not isinstance(hz_payload, dict):
            raise ComparisonError(
                f"Missing impact.summary_metrics.{hazard} in {_territory_page_path(run_id, territory)}"
            )
        for metric_name, key in metric_map.items():
            rows.append(
                {
                    "category": "monetary",
                    "scope": "summary_metrics",
                    "territory": territory,
                    "hazard": hazard,
                    "scenario": "all",
                    "metric": metric_name,
                    "run_id": run_id,
                    "value": _safe_float(hz_payload.get(key)),
                }
            )
    return rows



def _extract_percent_rows(run_id: str, territory: str, page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary_metrics = page_payload["impact"]["summary_metrics"]
    state_damage_tables = page_payload["impact"]["state_damage_tables"]

    pct_metric_keys = (
        "direct_hs_pct_annual",
        "indirect_hs_pct_annual",
        "direct_hs_pct_p99",
        "indirect_hs_pct_p99",
    )

    for hazard in HAZARDS:
        hz_payload = summary_metrics.get(hazard)
        if not isinstance(hz_payload, dict):
            raise ComparisonError(
                f"Missing impact.summary_metrics.{hazard} in {_territory_page_path(run_id, territory)}"
            )
        for metric_name in pct_metric_keys:
            rows.append(
                {
                    "category": "percent",
                    "scope": "summary_metrics",
                    "territory": territory,
                    "hazard": hazard,
                    "scenario": "all",
                    "metric": metric_name,
                    "run_id": run_id,
                    "value": _safe_float(hz_payload.get(metric_name)),
                }
            )

    for scenario in SCENARIOS:
        scenario_rows = state_damage_tables.get(scenario)
        if not isinstance(scenario_rows, list):
            raise ComparisonError(
                f"Missing impact.state_damage_tables.{scenario} in {_territory_page_path(run_id, territory)}"
            )
        for row in scenario_rows:
            if not isinstance(row, dict):
                continue
            class_key = str(row.get("class_key") or "unknown")
            for hazard in HAZARDS:
                hz = row.get(hazard)
                if not isinstance(hz, dict):
                    continue
                state_pct = hz.get("state_pct") if isinstance(hz.get("state_pct"), dict) else {}
                for state in STATE_KEYS:
                    rows.append(
                        {
                            "category": "network_state_pct",
                            "scope": f"state_damage_tables:{class_key}",
                            "territory": territory,
                            "hazard": hazard,
                            "scenario": scenario,
                            "metric": f"state_pct_{state}",
                            "run_id": run_id,
                            "value": _safe_float(state_pct.get(state)),
                        }
                    )
                rows.append(
                    {
                        "category": "percent",
                        "scope": f"state_damage_tables:{class_key}",
                        "territory": territory,
                        "hazard": hazard,
                        "scenario": scenario,
                        "metric": "damage_eur",
                        "run_id": run_id,
                        "value": _safe_float(hz.get("damage_eur")),
                    }
                )
                rows.append(
                    {
                        "category": "percent",
                        "scope": f"state_damage_tables:{class_key}",
                        "territory": territory,
                        "hazard": hazard,
                        "scenario": scenario,
                        "metric": "direct_damage_eur",
                        "run_id": run_id,
                        "value": _safe_float(hz.get("direct_damage_eur")),
                    }
                )
                rows.append(
                    {
                        "category": "percent",
                        "scope": f"state_damage_tables:{class_key}",
                        "territory": territory,
                        "hazard": hazard,
                        "scenario": scenario,
                        "metric": "indirect_damage_eur",
                        "run_id": run_id,
                        "value": _safe_float(hz.get("indirect_damage_eur")),
                    }
                )
    return rows



def _extract_population_rows(run_id: str, territory: str, complete_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    social_summary = complete_payload["portfolio_results"].get(
        "social_impact_worst_case_summary",
        complete_payload["portfolio_results"].get("social_impact_summary"),
    )
    if not isinstance(social_summary, dict):
        raise ComparisonError(
            f"Missing portfolio social summary in {_territory_complete_path(run_id, territory)}"
        )

    population_metrics = (
        "total_population_affected_any_network",
        "total_with_degraded_elec",
        "total_without_elec",
        "total_with_degraded_water_aep",
        "total_without_water_aep",
        "total_with_degraded_water_eu",
        "total_without_water_eu",
    )

    for hazard in HAZARDS:
        hz = social_summary.get(hazard)
        if not isinstance(hz, dict):
            raise ComparisonError(
                f"Missing social summary hazard {hazard} in {_territory_complete_path(run_id, territory)}"
            )
        for metric in population_metrics:
            rows.append(
                {
                    "category": "population",
                    "scope": "portfolio_social_summary",
                    "territory": territory,
                    "hazard": hazard,
                    "scenario": "annual",
                    "metric": metric,
                    "run_id": run_id,
                    "value": _safe_float(hz.get(metric)),
                }
            )

    # Territory-level aggregation from all grid/territory rows.
    territory_rows = complete_payload.get("territory_results")
    if not isinstance(territory_rows, list):
        raise ComparisonError(f"Missing territory_results in {_territory_complete_path(run_id, territory)}")

    total_population = sum(_safe_float(row.get("population_total")) for row in territory_rows if isinstance(row, dict))
    rows.append(
        {
            "category": "population",
            "scope": "territory_results",
            "territory": territory,
            "hazard": "all",
            "scenario": "annual",
            "metric": "population_total",
            "run_id": run_id,
            "value": total_population,
        }
    )

    return rows



def _extract_network_aggregate_rows(run_id: str, territory: str, page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exposition = page_payload.get("exposition") if isinstance(page_payload.get("exposition"), dict) else {}

    value_by_type = exposition.get("total_value_by_type_eur") if isinstance(exposition.get("total_value_by_type_eur"), dict) else {}
    lengths = exposition.get("lengths_km") if isinstance(exposition.get("lengths_km"), dict) else {}
    counts = exposition.get("counts") if isinstance(exposition.get("counts"), dict) else {}

    metric_sources = {
        "value_eau_aep_eur": value_by_type.get("eau_aep"),
        "value_eau_eu_eur": value_by_type.get("eau_eu"),
        "value_elec_bt_aerien_eur": value_by_type.get("elec_bt_aerien"),
        "value_elec_bt_souterrain_eur": value_by_type.get("elec_bt_souterrain"),
        "value_elec_hta_aerien_eur": value_by_type.get("elec_hta_aerien"),
        "value_elec_hta_souterrain_eur": value_by_type.get("elec_hta_souterrain"),
        "length_eau_aep_km": lengths.get("eau_aep"),
        "length_eau_eu_km": lengths.get("eau_eu"),
        "length_elec_bt_aerien_km": lengths.get("elec_bt_aerien"),
        "length_elec_bt_souterrain_km": lengths.get("elec_bt_souterrain"),
        "length_elec_hta_aerien_km": lengths.get("elec_hta_aerien"),
        "length_elec_hta_souterrain_km": lengths.get("elec_hta_souterrain"),
        "count_elec_lines_total": counts.get("elec_lines_total"),
        "count_water_lines_total": counts.get("water_lines_total"),
    }

    for metric, value in metric_sources.items():
        rows.append(
            {
                "category": "network_aggregate",
                "scope": "exposition",
                "territory": territory,
                "hazard": "all",
                "scenario": "all",
                "metric": metric,
                "run_id": run_id,
                "value": _safe_float(value),
            }
        )

    return rows



def _build_rows_for_run(run_id: str, territories: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for territory in territories:
        page_payload, complete_payload = _require_territory_payloads(run_id, territory)
        rows.extend(_extract_monetary_rows(run_id, territory, page_payload))
        rows.extend(_extract_percent_rows(run_id, territory, page_payload))
        rows.extend(_extract_population_rows(run_id, territory, complete_payload))
        rows.extend(_extract_network_aggregate_rows(run_id, territory, page_payload))
    return rows



def _index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], float]:
    index: dict[tuple[str, str, str, str, str], float] = {}
    for row in rows:
        key = (
            str(row["category"]),
            str(row["scope"]),
            str(row["territory"]),
            str(row["hazard"]),
            str(row["scenario"]),
            str(row["metric"]),
        )
        index[key] = _safe_float(row["value"])
    return index



def _merge_comparison_rows(run_a: str, run_b: str, rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    idx_a = _index_rows(rows_a)
    idx_b = _index_rows(rows_b)
    all_keys = sorted(set(idx_a.keys()) | set(idx_b.keys()))

    merged: list[dict[str, Any]] = []
    for key in all_keys:
        category, scope, territory, hazard, scenario, metric = key
        a = idx_a.get(key)
        b = idx_b.get(key)
        if a is None or b is None:
            raise ComparisonError(
                f"Schema mismatch for key={key}: value missing in one run (run_a={run_a}, run_b={run_b})"
            )
        merged.append(
            {
                "category": category,
                "scope": scope,
                "territory": territory,
                "hazard": hazard,
                "scenario": scenario,
                "metric": metric,
                "run_a": a,
                "run_b": b,
                "delta_abs": b - a,
                "delta_pct": _delta_pct(a, b),
            }
        )
    return merged



def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            if "delta_pct" in payload and payload["delta_pct"] is None:
                payload["delta_pct"] = ""
            writer.writerow(payload)



def _fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".replace(",", " ")



def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"



def _write_markdown(path: Path, run_a: str, run_b: str, rows: list[dict[str, Any]]) -> None:
    sections = [
        ("monetary", "Impacts monetaires"),
        ("percent", "Impacts en pourcentage"),
        ("population", "Impacts population"),
        ("network_aggregate", "Etat des reseaux (agregats)"),
        ("network_state_pct", "Etat des reseaux S0/S1/S2/S3"),
    ]

    lines: list[str] = []
    lines.append("# Comparaison complete-analysis")
    lines.append("")
    lines.append(f"- Run A: `{run_a}`")
    lines.append(f"- Run B: `{run_b}`")
    lines.append("")
    lines.append("Convention: delta = run_B - run_A")
    lines.append("")

    for category_key, title in sections:
        section_rows = [row for row in rows if row["category"] == category_key]
        if not section_rows:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Territoire | Alea | Scenario | Scope | Metrique | Run A | Run B | Delta abs | Delta % |")
        lines.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
        for row in section_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["territory"]),
                        str(row["hazard"]),
                        str(row["scenario"]),
                        str(row["scope"]),
                        str(row["metric"]),
                        _fmt_num(_safe_float(row["run_a"])),
                        _fmt_num(_safe_float(row["run_b"])),
                        _fmt_num(_safe_float(row["delta_abs"])),
                        _fmt_pct(row["delta_pct"]),
                    ]
                )
                + " |"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two complete-analysis runs (1500 tracks) on monetary, percent, population, "
            "and network-state impacts, with explicit failures when required artefacts are missing."
        )
    )
    parser.add_argument("--run-a", required=True, help="Baseline run id (e.g. 20260511_141135)")
    parser.add_argument("--run-b", required=True, help="Compared run id (e.g. 20260527_160919)")
    parser.add_argument(
        "--territories",
        nargs="+",
        choices=list(DEFAULT_TERRITORIES),
        default=list(DEFAULT_TERRITORIES),
        help="Territories to compare (default: guadeloupe martinique)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "outputs" / "run-comparisons"),
        help="Directory where Markdown/CSV outputs are written",
    )
    return parser.parse_args()



def main() -> int:
    args = parse_args()
    territories = tuple(args.territories)

    ctx_a = _find_run_context(args.run_a)
    ctx_b = _find_run_context(args.run_b)

    if territories:
        for run_ctx in (ctx_a, ctx_b):
            manifest_territories = run_ctx.manifest.get("territories")
            if not isinstance(manifest_territories, dict):
                raise ComparisonError(f"Run {run_ctx.run_id} has no territories object in manifest")
            for territory in territories:
                if territory not in manifest_territories:
                    raise ComparisonError(f"Run {run_ctx.run_id} missing territory {territory} in manifest")
                terr_entry = manifest_territories.get(territory)
                terr_status = str((terr_entry or {}).get("status") or "").strip().lower()
                if terr_status != "complete":
                    raise ComparisonError(
                        f"Run {run_ctx.run_id} territory {territory} not complete (status={terr_status!r})"
                    )

    rows_a = _build_rows_for_run(args.run_a, territories)
    rows_b = _build_rows_for_run(args.run_b, territories)
    merged = _merge_comparison_rows(args.run_a, args.run_b, rows_a, rows_b)

    output_dir = Path(args.output_dir) / f"{args.run_a}_vs_{args.run_b}"
    md_path = output_dir / "run-comparison.md"
    summary_csv = output_dir / "run-comparison-summary.csv"
    network_csv = output_dir / "run-comparison-network-states.csv"

    _write_markdown(md_path, args.run_a, args.run_b, merged)
    _write_csv(
        summary_csv,
        merged,
        fieldnames=[
            "category",
            "scope",
            "territory",
            "hazard",
            "scenario",
            "metric",
            "run_a",
            "run_b",
            "delta_abs",
            "delta_pct",
        ],
    )

    network_rows = [
        row for row in merged if row["category"] in {"network_aggregate", "network_state_pct"}
    ]
    _write_csv(
        network_csv,
        network_rows,
        fieldnames=[
            "category",
            "scope",
            "territory",
            "hazard",
            "scenario",
            "metric",
            "run_a",
            "run_b",
            "delta_abs",
            "delta_pct",
        ],
    )

    print(f"[ok] comparison generated")
    print(f"  - markdown: {md_path}")
    print(f"  - summary csv: {summary_csv}")
    print(f"  - network csv: {network_csv}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ComparisonError as exc:
        print(f"[error] {exc}")
        raise SystemExit(2)
