#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DATA_DIR = REPO_ROOT / "web" / "data"

NETWORK_CLASS_LABELS = {
    "eau_aep": "Eau AEP",
    "eau_eu": "Eau EU",
    "elec_bt_souterrain": "Elec BT souterrain",
    "elec_bt_aerien": "Elec BT aerien",
    "elec_hta_souterrain": "Elec HTA souterrain",
    "elec_hta_aerien": "Elec HTA aerien",
}

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

HAZARD_KEYS = ("storm", "storm_cmcc")
SCENARIOS = ("annual", "rp50", "rp100", "p99")
COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _round2(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except Exception:
        return 0.0


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _portfolio_summary(portfolio: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard in HAZARD_KEYS:
        payload = _safe_dict(portfolio.get(hazard))
        out[hazard] = {
            "annual_eur": _round2(payload.get("eai_eur")),
            "rp50_eur": _round2(payload.get("pml_50_eur")),
            "rp100_eur": _round2(payload.get("pml_100_eur")),
            "p99_eur": _round2(payload.get("percentile_99_loss_eur")),
            "pml_1000_eur": _round2(payload.get("pml_1000_eur")),
            "direct_annual_eur": _round2(payload.get("eai_direct_eur")),
            "indirect_annual_eur": _round2(payload.get("eai_indirect_eur")),
        }
    out["delta"] = _safe_dict(portfolio.get("delta"))
    return out


def _normalized_asset_type(asset_type_raw: Any) -> str:
    return str(asset_type_raw or "").strip().lower()


def _blank_component_map() -> dict[str, float]:
    return {component: 0.0 for component in COMPONENT_ORDER}


def _new_damage_bucket() -> dict[str, float]:
    return {
        "exposure_eur": 0.0,
        "damage_eur": 0.0,
        "direct_damage_eur": 0.0,
        "indirect_damage_eur": 0.0,
    }


def _group_asset_results(asset_results: list[dict[str, Any]], class_mapping: dict[str, str]) -> dict[str, dict[str, dict[str, float]]]:
    grouped: dict[str, dict[str, dict[str, float]]] = {}
    for asset in asset_results:
        if not isinstance(asset, dict):
            continue
        class_key = class_mapping.get(_normalized_asset_type(asset.get("asset_type")))
        if not class_key:
            continue
        class_bucket = grouped.setdefault(
            class_key,
            {
                "storm": _new_damage_bucket(),
                "storm_cmcc": _new_damage_bucket(),
            },
        )
        exposure = _round2(asset.get("exposure_eur"))
        for hazard in HAZARD_KEYS:
            bucket = class_bucket[hazard]
            bucket["exposure_eur"] += exposure
            if hazard == "storm":
                bucket["damage_eur"] += _round2(asset.get("eai_storm_eur"))
                bucket["direct_damage_eur"] += _round2(asset.get("eai_storm_direct_eur"))
                bucket["indirect_damage_eur"] += _round2(asset.get("eai_storm_indirect_eur"))
            else:
                bucket["damage_eur"] += _round2(asset.get("eai_cmcc_eur"))
                bucket["direct_damage_eur"] += _round2(asset.get("eai_cmcc_direct_eur"))
                bucket["indirect_damage_eur"] += _round2(asset.get("eai_cmcc_indirect_eur"))
    return grouped


def _build_annual_rows(grouped: dict[str, dict[str, dict[str, float]]], labels: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for class_key in labels.keys():
        by_hazard = grouped.get(class_key) or {"storm": _new_damage_bucket(), "storm_cmcc": _new_damage_bucket()}
        rows.append(
            {
                "class_key": class_key,
                "class_label": labels[class_key],
                "storm": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
                    "exposure_eur": _round2(by_hazard["storm"].get("exposure_eur")),
                    "damage_eur": _round2(by_hazard["storm"].get("damage_eur")),
                    "direct_damage_eur": _round2(by_hazard["storm"].get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(by_hazard["storm"].get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                },
                "storm_cmcc": {
                    "state_pct": {"S0": 0.0, "S1": 0.0, "S2": 0.0, "S3": 0.0},
                    "exposure_eur": _round2(by_hazard["storm_cmcc"].get("exposure_eur")),
                    "damage_eur": _round2(by_hazard["storm_cmcc"].get("damage_eur")),
                    "direct_damage_eur": _round2(by_hazard["storm_cmcc"].get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(by_hazard["storm_cmcc"].get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                },
            }
        )
    return rows


def _build_annual_breakdown_rows(grouped: dict[str, dict[str, dict[str, float]]], labels: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    by_hazard: dict[str, list[dict[str, Any]]] = {"storm": [], "storm_cmcc": []}
    for class_key in labels.keys():
        grouped_row = grouped.get(class_key) or {"storm": _new_damage_bucket(), "storm_cmcc": _new_damage_bucket()}
        for hazard in HAZARD_KEYS:
            bucket = grouped_row[hazard]
            by_hazard[hazard].append(
                {
                    "class_key": class_key,
                    "class_label": labels[class_key],
                    "exposure_eur": _round2(bucket.get("exposure_eur")),
                    "damage_eur": _round2(bucket.get("damage_eur")),
                    "direct_damage_eur": _round2(bucket.get("direct_damage_eur")),
                    "indirect_damage_eur": _round2(bucket.get("indirect_damage_eur")),
                    "damage_components_eur": _blank_component_map(),
                }
            )
    return by_hazard


def _service_state_distribution(network_states_native: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for hazard in HAZARD_KEYS:
        by_service = _safe_dict(network_states_native.get(hazard))
        out[hazard] = {}
        for service_key, service_map_raw in by_service.items():
            service_map = _safe_dict(service_map_raw)
            counts = {"S0": 0, "S1": 0, "S2": 0, "S3": 0}
            for state_row in service_map.values():
                if not isinstance(state_row, dict):
                    continue
                state = str(state_row.get("state") or "S0").strip().upper()
                if state not in counts:
                    state = "S0"
                counts[state] += 1
            counts["total_units"] = int(sum(counts.values()))
            out[hazard][service_key] = counts
    return out


def _build_scientific_web_summary(complete_analysis: dict[str, Any], territory: str) -> dict[str, Any]:
    meta = _safe_dict(complete_analysis.get("meta"))
    portfolio = _safe_dict(complete_analysis.get("portfolio_results"))
    asset_results = [row for row in _safe_list(complete_analysis.get("asset_results")) if isinstance(row, dict)]
    grouped_network = _group_asset_results(asset_results, ASSET_TYPE_TO_NETWORK_CLASS)
    grouped_breakdown = _group_asset_results(asset_results, ASSET_TYPE_TO_BREAKDOWN_CLASS)

    portfolio_summary = _portfolio_summary(portfolio)
    network_tables_annual = _build_annual_rows(grouped_network, NETWORK_CLASS_LABELS)
    breakdown_annual = _build_annual_breakdown_rows(grouped_breakdown, DAMAGE_BREAKDOWN_LABELS)

    summary_metrics = {
        "storm": {
            "eai_total_eur": _round2(portfolio_summary["storm"].get("annual_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm"].get("rp100_eur")),
            "p99_total_loss_eur": _round2(portfolio_summary["storm"].get("p99_eur")),
        },
        "storm_cmcc": {
            "eai_total_eur": _round2(portfolio_summary["storm_cmcc"].get("annual_eur")),
            "rp50_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp50_eur")),
            "rp100_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("rp100_eur")),
            "p99_total_loss_eur": _round2(portfolio_summary["storm_cmcc"].get("p99_eur")),
        },
    }

    scientific_summary = {
        "meta": {
            "territory": territory,
            "run_id": str(meta.get("run_id") or complete_analysis.get("run_id") or ""),
            "generated_at": datetime.now(UTC).isoformat(),
            "dynamic_max_tracks": meta.get("requested_dynamic_max_tracks"),
            "scientific_source": True,
            "schema_version": "scientific_web_summary_v1",
            "source_artifact": f"{territory}-complete-analysis.json",
        },
        "portfolio_summary": portfolio_summary,
        "network_damage_tables": {
            "annual": network_tables_annual,
            "rp50": [],
            "rp100": [],
            "p99": [],
            "scenario_availability": {
                "annual": "scientific_complete",
                "rp50": "portfolio_totals_only",
                "rp100": "portfolio_totals_only",
                "p99": "portfolio_totals_only",
            },
        },
        "component_breakdowns": {
            "annual": {
                "storm": breakdown_annual["storm"],
                "storm_cmcc": breakdown_annual["storm_cmcc"],
            },
            "rp50": {"storm": [], "storm_cmcc": []},
            "rp100": {"storm": [], "storm_cmcc": []},
            "p99": {"storm": [], "storm_cmcc": []},
            "portfolio_component_totals": {
                "annual": {
                    "storm": _safe_dict(_safe_dict(portfolio.get("storm")).get("components_direct_eai_eur")),
                    "storm_cmcc": _safe_dict(_safe_dict(portfolio.get("storm_cmcc")).get("components_direct_eai_eur")),
                },
                "p99": {
                    "storm": _safe_dict(_safe_dict(portfolio.get("storm")).get("components_direct_percentile_99_loss_eur")),
                    "storm_cmcc": _safe_dict(_safe_dict(portfolio.get("storm_cmcc")).get("components_direct_percentile_99_loss_eur")),
                },
            },
        },
        "network_states": {
            "scenario_service_state_distribution": {
                "annual": {},
                "rp50": {},
                "rp100": {},
                "p99": _service_state_distribution(_safe_dict(portfolio.get("network_states_native"))),
            },
            "worst_case_native_service_states": _safe_dict(portfolio.get("network_states_native")),
            "worst_case_projected_service_states": _safe_dict(portfolio.get("network_states_projected")),
            "worst_case_projected_service_coverage": _safe_dict(portfolio.get("network_states_projected_coverage")),
            "scenario_availability": {
                "annual": False,
                "rp50": False,
                "rp100": False,
                "p99": True,
            },
        },
        "social_impact": {
            "scenario_summary": {
                "annual": {},
                "rp50": {},
                "rp100": {},
                "p99": _safe_dict(portfolio.get("social_impact_summary")),
            },
            "scenario_population_state_distribution": {
                "annual": {},
                "rp50": {},
                "rp100": {},
                "p99": _safe_dict(portfolio.get("social_impact_population_state_distribution")),
            },
            "worst_case_summary": _safe_dict(portfolio.get("social_impact_summary")),
            "worst_case_population_state_distribution": _safe_dict(portfolio.get("social_impact_population_state_distribution")),
            "scenario_availability": {
                "annual": False,
                "rp50": False,
                "rp100": False,
                "p99": True,
            },
        },
        "frontend": {
            "impact": {
                "component_order": list(COMPONENT_ORDER),
                "summary_metrics": summary_metrics,
                "state_damage_tables": {
                    "annual": network_tables_annual,
                    "rp50": [],
                    "rp100": [],
                    "p99": [],
                },
                "damage_breakdown_by_scenario": {
                    "annual": {
                        "storm": breakdown_annual["storm"],
                        "storm_cmcc": breakdown_annual["storm_cmcc"],
                    },
                    "rp50": {"storm": [], "storm_cmcc": []},
                    "rp100": {"storm": [], "storm_cmcc": []},
                    "p99": {"storm": [], "storm_cmcc": []},
                },
                "map_defaults": {
                    "hazard": "storm",
                    "scenario": "p99",
                },
            },
            "scenario_availability": {
                "annual": {"damage_tables": True, "social_impact": False, "network_states": False},
                "rp50": {"damage_tables": False, "social_impact": False, "network_states": False},
                "rp100": {"damage_tables": False, "social_impact": False, "network_states": False},
                "p99": {"damage_tables": False, "social_impact": True, "network_states": True},
            },
        },
        "notes": [
            "Ce payload est derive uniquement du complete-analysis publie.",
            "Les totaux portefeuille sont canoniques pour annual/rp50/rp100/p99.",
            "Les tableaux monetaires par classe ne sont scientifiquement complets qu en annuel dans le contrat actuel du complete-analysis.",
            "Les etats reseau et impacts sociaux exposes ici sont disponibles scientifiquement en mode worst-case/p99 uniquement dans le contrat actuel.",
        ],
    }
    return scientific_summary


def build_scientific_web_summary(
    *,
    territory: str,
    complete_analysis_path: Path,
    out_path: Path,
) -> Path:
    complete_analysis = _load_json(complete_analysis_path)
    payload = _build_scientific_web_summary(complete_analysis, territory)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build scientific web summary from a published complete-analysis payload.")
    parser.add_argument("--territory", required=True)
    parser.add_argument("--complete-analysis-json", default=None)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args(argv)

    territory = str(args.territory).strip().lower()
    complete_analysis_path = (
        Path(args.complete_analysis_json)
        if args.complete_analysis_json
        else (WEB_DATA_DIR / f"{territory}-complete-analysis.json")
    )
    out_path = (
        Path(args.out_json)
        if args.out_json
        else (WEB_DATA_DIR / f"{territory}-scientific-web-summary.json")
    )
    build_scientific_web_summary(
        territory=territory,
        complete_analysis_path=complete_analysis_path,
        out_path=out_path,
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
