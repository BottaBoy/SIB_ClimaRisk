#!/usr/bin/env python3
"""Build a decision-oriented population impact table for STORM."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_COMPLETE_ANALYSIS = Path(
    "/home/ubuntu/uploads/from_popa/20260711_071243/scientific_archive/guadeloupe-complete-analysis.json"
)
DEFAULT_SCIENTIFIC_SUMMARY = Path(
    "/home/ubuntu/uploads/from_popa/20260711_071243/scientific_archive/guadeloupe-scientific-web-summary.json"
)
DEFAULT_NETWORK_STATES = Path("/home/ubuntu/sib-work/web/data/guadeloupe-network-states.geojson")
DEFAULT_HYDRAULIC_ZONES = Path(
    "/home/ubuntu/sib-work/outputs/hydraulic_zoning/Zonage_V2/guadeloupe_hydraulic_zones_estimate.gpkg"
)
DEFAULT_OUTPUT_CSV = Path(
    "/home/ubuntu/sib-work/outputs/Graphs/20260711_071243/tables/"
    "guadeloupe_tableau_synthese_zones_population_storm.csv"
)
DEFAULT_OUTPUT_MD = Path(
    "/home/ubuntu/sib-work/outputs/Graphs/20260711_071243/tables/"
    "guadeloupe_tableau_synthese_zones_population_storm.md"
)

PERIODS = ("rp50", "rp100", "rp1000")
CSV_COLUMNS = (
    "periode",
    "zone_principale",
    "population_potentiellement_affectee",
    "type_defaillance_modelisee",
    "ouvrage_ou_reseau_determinant",
    "commune_ou_secteur",
    "enjeu_continuite_service",
    "prudence_interpretation",
    "service",
    "etat",
    "state_basis",
    "service_unit_id",
)
MARKDOWN_COLUMNS = (
    "Zone principale",
    "Commune ou secteur",
    "Population affectée",
    "Type de défaillance modélisée",
    "Ouvrage ou réseau déterminant (ouvrages candidats)",
    "Enjeu de continuité de service",
)

STATE_SEVERITY = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
STATE_LABELS = {
    "S0": "dommage faible ou nul",
    "S1": "dommage modéré",
    "S2": "dommage élevé",
    "S3": "dommage très élevé / indisponibilité potentielle",
}
SERVICE_LABELS = {
    "water_aep": "Eau potable AEP",
    "water_eu": "Eaux usées EU",
    "elec": "Électricité",
}
SERVICE_CSV_VALUES = {
    "water_aep": "eau_aep",
    "water_eu": "eau_eu",
    "elec": "elec",
}
SERVICE_SHORT_LABELS = {
    "water_aep": "AEP",
    "water_eu": "EU",
    "elec": "Électricité",
}
MARKDOWN_SERVICE_SECTIONS = (
    ("eau_aep", "AEP"),
    ("eau_eu", "EU"),
    ("elec", "Électricité"),
)
WATER_BLOCKING_ROLES_BY_SERVICE = {
    "water_aep": frozenset({"captage_aep", "upep_aep", "pompage_aep"}),
    "water_eu": frozenset({"step", "poste_refoulement"}),
}
ASSET_ROLE_LABELS = {
    "captage_aep": "captage",
    "upep_aep": "UPEP",
    "pompage_aep": "pompage",
    "step": "STEP",
    "poste_refoulement": "poste de refoulement",
}
ASSET_ROLE_ORDER = {
    "captage_aep": 0,
    "upep_aep": 1,
    "pompage_aep": 2,
    "step": 0,
    "poste_refoulement": 1,
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_state(value: Any) -> str:
    state = str(value or "S0").strip().upper()
    return state if state in STATE_SEVERITY else "S0"


def _clean_label(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


def _format_population_csv(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.2f}"


def _format_population_markdown(value: float) -> str:
    rounded = int(round(value / 100.0) * 100)
    return f"{rounded:,}".replace(",", " ")


def _period_label(period: str) -> str:
    return period.upper().replace("RP", "RP")


def _service_from_layer(layer_key: Any) -> str | None:
    layer = str(layer_key or "").strip()
    if layer == "elec_grid_0p1deg":
        return "elec"
    if layer == "eau_aep":
        return "water_aep"
    if layer == "eau_eu":
        return "water_eu"
    return None


def _basis_from_cause(service: str, cause: str) -> str:
    if service == "elec":
        return "aggregated_damage_ratio_on_fixed_grid_0p1deg"
    if cause == "blocking_ouvrage":
        return "aggregated_damage_ratio_on_zone_component_key_plus_blocking_asset"
    return "aggregated_damage_ratio_on_zone_component_key"


def _build_network_state_index(network_states_path: Path) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    payload = _read_json(network_states_path)
    index: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        "water_aep": defaultdict(dict),
        "water_eu": defaultdict(dict),
        "elec": defaultdict(dict),
    }
    for feature in payload.get("features") or []:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            continue
        service = _service_from_layer(props.get("layer_key"))
        if service is None:
            continue
        ids = {
            str(props.get("feature_id") or "").strip(),
            str(props.get("service_feature_id") or "").strip(),
            str(props.get("zone_uid") or "").strip(),
            str(props.get("zone_component_key") or "").strip(),
        }
        ids.discard("")
        for identifier in ids:
            bucket = index[service][identifier]
            for period in PERIODS:
                state = _normalize_state(props.get(f"state_{period}_storm"))
                current = _normalize_state(bucket.get(period, {}).get("state"))
                if STATE_SEVERITY[state] >= STATE_SEVERITY[current]:
                    cause = str(props.get(f"cause_{period}_storm") or "").strip()
                    bucket[period] = {
                        "state": state,
                        "cause": cause,
                        "state_basis": _basis_from_cause(service, cause),
                    }
    return index


def _load_hydraulic_metadata(gpkg_path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(str(gpkg_path))
    conn.row_factory = sqlite3.Row
    metadata: dict[str, dict[str, Any]] = {}

    def _columns(table_name: str) -> set[str]:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}

    zone_columns = _columns("hydraulic_zones")
    line_km_expr = "line_km" if "line_km" in zone_columns else "NULL AS line_km"
    for row in conn.execute(
        f"""
        SELECT zone_uid, zone_component_key, zone_label, network_kind, line_km,
               asset_count, critical_asset_count
        FROM hydraulic_zones
        """.replace("line_km,", f"{line_km_expr},")
    ):
        record = dict(row)
        label = _clean_label(record.get("zone_label")) or _clean_label(record.get("zone_uid"))
        item = {
            "label": label,
            "network_kind": str(record.get("network_kind") or "").strip(),
            "line_km": record.get("line_km"),
            "asset_count": record.get("asset_count"),
            "critical_asset_count": record.get("critical_asset_count"),
        }
        for key in (record.get("zone_component_key"), record.get("zone_uid")):
            key = str(key or "").strip()
            if key and key not in metadata:
                metadata[key] = dict(item)

    line_columns = _columns("hydraulic_lines")
    if "commune" in line_columns:
        commune_rows = conn.execute(
            """
            SELECT zone_uid, zone_component_key, commune, SUM(line_length_m) / 1000.0 AS km
            FROM hydraulic_lines
            WHERE commune IS NOT NULL AND TRIM(commune) != ''
            GROUP BY zone_uid, zone_component_key, commune
            ORDER BY km DESC
            """
        ).fetchall()
    else:
        commune_rows = []

    asset_columns = _columns("hydraulic_assets")
    commune_expr = "commune" if "commune" in asset_columns else "'' AS commune"
    asset_rows = conn.execute(
        f"""
        SELECT zone_uid, zone_component_key, feature_role, {commune_expr}, asset_name
        FROM hydraulic_assets
        WHERE asset_name IS NOT NULL AND TRIM(asset_name) != ''
        """
    ).fetchall()
    conn.close()

    communes_by_key: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in commune_rows:
        commune = _clean_label(row["commune"])
        if not commune:
            continue
        for key in (row["zone_component_key"], row["zone_uid"]):
            key = str(key or "").strip()
            if key:
                communes_by_key[key].append((commune, float(row["km"] or 0.0)))

    for key, values in communes_by_key.items():
        # Merge duplicate commune values introduced by indexing both zone_uid and component keys.
        totals: dict[str, float] = defaultdict(float)
        for commune, km in values:
            totals[commune] += km
        top = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:3]
        if key not in metadata:
            metadata[key] = {"label": _clean_label(key)}
        metadata[key]["communes"] = "; ".join(commune for commune, _km in top)

    assets_by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_by_key: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for row in asset_rows:
        role = str(row["feature_role"] or "").strip()
        name = _clean_label(row["asset_name"])
        if not role or not name:
            continue
        commune = _clean_label(row["commune"])
        asset = {"role": role, "name": name, "commune": commune}
        identity = (role.lower(), name.lower(), commune.lower())
        for key in (row["zone_component_key"], row["zone_uid"]):
            key = str(key or "").strip()
            if not key or identity in seen_by_key[key]:
                continue
            seen_by_key[key].add(identity)
            assets_by_key[key].append(dict(asset))

    for key, assets in assets_by_key.items():
        if key not in metadata:
            metadata[key] = {"label": _clean_label(key)}
        metadata[key]["assets"] = sorted(
            assets,
            key=lambda item: (
                ASSET_ROLE_ORDER.get(item["role"], 99),
                item["name"].lower(),
                item["commune"].lower(),
            ),
        )

    return metadata


def _sector_from_cell_id(cell_id: str) -> str:
    match = re.search(r"cell-([+-]\d+\.\d+)_([+-]\d+\.\d+)", cell_id)
    if not match:
        return f"maille electrique {cell_id}"
    lat = float(match.group(1))
    lon = float(match.group(2))
    if 16.1 <= lat <= 16.3 and -61.7 <= lon <= -61.5:
        return "Pointe-à-Pitre / Les Abymes / Baie-Mahault"
    if 16.1 <= lat <= 16.3 and -61.5 < lon <= -61.3:
        return "Le Gosier / Sainte-Anne / sud Grande-Terre"
    if 16.3 <= lat <= 16.5 and -61.5 <= lon <= -61.3:
        return "Le Moule / Morne-à-l'Eau / nord Grande-Terre"
    if 15.9 <= lat <= 16.1 and lon <= -61.7:
        return "Basse-Terre / Baillif / sud Basse-Terre"
    if 15.9 <= lat <= 16.1 and -61.7 < lon <= -61.5:
        return "Capesterre-Belle-Eau / Trois-Rivières"
    if 16.1 <= lat <= 16.3 and lon <= -61.7:
        return "Bouillante / côte-sous-le-vent"
    if lat >= 16.3 and lon <= -61.5:
        return "Port-Louis / Anse-Bertrand / Petit-Canal"
    return f"secteur {lat:.2f}, {lon:.2f}"


def _zone_display(service: str, service_unit_id: str, metadata: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if service == "elec":
        sector = _sector_from_cell_id(service_unit_id)
        return f"Électricité - {sector}", f"{sector} ({service_unit_id})"
    meta = metadata.get(service_unit_id, {})
    label = _clean_label(meta.get("label")) or _clean_label(service_unit_id)
    zone = f"{SERVICE_SHORT_LABELS[service]} - {label}"
    communes = str(meta.get("communes") or "").strip()
    if not communes:
        communes = "secteur hydraulique " + _clean_label(service_unit_id)
    else:
        communes = communes + " (dominantes par longueur de réseau)"
    return zone, communes


def _failure_type(service: str, state: str, state_basis: str) -> str:
    service_label = SERVICE_LABELS[service]
    state_label = STATE_LABELS.get(state, state)
    if state_basis == "aggregated_damage_ratio_on_zone_component_key_plus_blocking_asset":
        return f"{service_label}: {state_label} ({state}), avec effet d'ouvrage bloquant modélisé"
    if service == "elec":
        return f"{service_label}: {state_label} ({state}), sur réseau électrique agrégé"
    return f"{service_label}: {state_label} ({state}), par dommage direct agrégé du réseau"


def _candidate_asset_summary(service: str, service_unit_id: str, metadata: dict[str, dict[str, Any]]) -> str:
    meta = metadata.get(service_unit_id, {})
    roles = WATER_BLOCKING_ROLES_BY_SERVICE.get(service, frozenset())
    candidates = [
        asset
        for asset in meta.get("assets", [])
        if str(asset.get("role") or "").strip() in roles and str(asset.get("name") or "").strip()
    ]
    if not candidates:
        return "ouvrages candidats non nommés dans la synthèse"

    dominant_communes = {
        _clean_label(commune).upper()
        for commune in str(meta.get("communes") or "").split(";")
        if _clean_label(commune)
    }
    candidates = sorted(
        candidates,
        key=lambda item: (
            0 if str(item.get("commune") or "").upper() in dominant_communes else 1,
            ASSET_ROLE_ORDER.get(str(item.get("role") or ""), 99),
            str(item.get("name") or "").lower(),
            str(item.get("commune") or "").lower(),
        ),
    )
    max_items = 5
    shown = candidates[:max_items]
    parts: list[str] = []
    for asset in shown:
        role = ASSET_ROLE_LABELS.get(asset["role"], _clean_label(asset["role"]))
        commune = str(asset.get("commune") or "").strip()
        suffix = f" ({commune})" if commune else ""
        parts.append(f"{role} {asset['name']}{suffix}")
    if len(candidates) > max_items:
        parts.append(f"+{len(candidates) - max_items} autres ouvrages candidats")
    return "; ".join(parts)


def _determinant(
    service: str,
    state_basis: str,
    service_unit_id: str,
    metadata: dict[str, dict[str, Any]],
) -> str:
    if state_basis == "aggregated_damage_ratio_on_zone_component_key_plus_blocking_asset":
        candidates = _candidate_asset_summary(service, service_unit_id, metadata)
        return f"Zone hydraulique + ouvrages bloquants candidats: {candidates}"
    if service == "elec":
        return "Réseau électrique agrégé (maille de service 0,1°); ouvrage non nominatif dans cette sortie"
    return "Réseau hydraulique agrégé de la zone; dommages directs sur canalisations"


def _continuity_issue(service: str, state: str) -> str:
    service_issue = {
        "water_aep": "continuité d'alimentation en eau potable",
        "water_eu": "continuité d'assainissement et vigilance sanitaire",
        "elec": "continuité d'alimentation électrique et appui aux autres réseaux",
    }[service]
    if state == "S3":
        return f"{service_issue}; priorité de rétablissement et solutions de secours"
    if state == "S2":
        return f"{service_issue}; surveillance prioritaire avant rupture de service"
    return f"{service_issue}; maintien du service sous contrainte"


def _interpretation_note(service: str, state_basis: str) -> str:
    if service == "elec":
        return (
            "Estimation prudente: le modèle peut sous-estimer les défaillances électriques "
            "aériennes ou indirectes; lignes non additives."
        )
    if state_basis == "aggregated_damage_ratio_on_zone_component_key_plus_blocking_asset":
        return (
            "Population potentiellement affectée; les ouvrages listés sont des candidats "
            "associés à la zone, sans attribution causale unique; lignes non additives."
        )
    return (
        "Population potentiellement affectée par zonage; lecture indicative pour priorisation; "
        "lignes non additives."
    )


def _validate_periods(scientific_summary: dict[str, Any]) -> None:
    availability = scientific_summary.get("network_states", {}).get("scenario_availability", {})
    social = scientific_summary.get("social_impact", {}).get("scenario_summary", {})
    missing = [period for period in PERIODS if not availability.get(period) or period not in social]
    if missing:
        raise RuntimeError(f"Missing STORM periods in scientific archive: {', '.join(missing)}")


def build_population_decision_rows(
    complete_analysis: dict[str, Any],
    scientific_summary: dict[str, Any],
    network_states_path: Path,
    hydraulic_zones_path: Path,
) -> list[dict[str, str]]:
    """Build the source rows used by the STORM population decision table."""
    _validate_periods(scientific_summary)
    network_index = _build_network_state_index(network_states_path)
    hydraulic_metadata = _load_hydraulic_metadata(hydraulic_zones_path)
    return _build_rows(complete_analysis, network_index, hydraulic_metadata)


def build_population_decision_markdown(rows: list[dict[str, str]]) -> str:
    return _markdown_table(rows)


def write_population_decision_csv(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(path, rows)


def _build_rows(
    complete_analysis: dict[str, Any],
    network_index: dict[str, dict[str, dict[str, dict[str, str]]]],
    hydraulic_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str, str], float] = defaultdict(float)

    for territory in complete_analysis.get("territory_results") or []:
        population = float(territory.get("population_total") or 0.0)
        if population <= 0.0:
            continue
        native_states = (territory.get("native_service_states") or {}).get("storm") or {}

        for service in ("water_aep", "water_eu"):
            service_state = native_states.get(service) if isinstance(native_states, dict) else {}
            service_unit_id = str((service_state or {}).get("service_unit_id") or "").strip()
            if not service_unit_id:
                continue
            state_lookup = network_index.get(service, {}).get(service_unit_id, {})
            for period in PERIODS:
                state_info = state_lookup.get(period) or {}
                state = _normalize_state(state_info.get("state"))
                if state == "S0":
                    continue
                basis = str(state_info.get("state_basis") or _basis_from_cause(service, "")).strip()
                grouped[(period, service, service_unit_id, state, basis)] += population

        # The scientific archive carries the calibrated RP1000 electricity projection per population cell.
        elec_state = _normalize_state(
            ((territory.get("population_projected_service_states") or {}).get("storm") or {}).get("elec")
        )
        if elec_state != "S0":
            service_unit_id = str(
                ((native_states.get("elec") if isinstance(native_states, dict) else {}) or {}).get("service_unit_id")
                or territory.get("territory_id")
                or ""
            ).strip()
            if service_unit_id:
                grouped[
                    (
                        "rp1000",
                        "elec",
                        service_unit_id,
                        elec_state,
                        "aggregated_damage_ratio_on_fixed_grid_0p1deg",
                    )
                ] += population

    rows: list[dict[str, str]] = []
    for (period, service, service_unit_id, state, basis), population in grouped.items():
        if population <= 0.0:
            continue
        zone, commune_or_sector = _zone_display(service, service_unit_id, hydraulic_metadata)
        rows.append(
            {
                "periode": period.upper(),
                "zone_principale": zone,
                "population_potentiellement_affectee": _format_population_csv(population),
                "type_defaillance_modelisee": _failure_type(service, state, basis),
                "ouvrage_ou_reseau_determinant": _determinant(
                    service,
                    basis,
                    service_unit_id,
                    hydraulic_metadata,
                ),
                "commune_ou_secteur": commune_or_sector,
                "enjeu_continuite_service": _continuity_issue(service, state),
                "prudence_interpretation": _interpretation_note(service, basis),
                "service": SERVICE_CSV_VALUES[service],
                "etat": state,
                "state_basis": basis,
                "service_unit_id": service_unit_id,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            PERIODS.index(row["periode"].lower()),
            -float(row["population_potentiellement_affectee"]),
            row["service"],
            row["service_unit_id"],
        ),
    )


def _markdown_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "La lecture matricielle ci-dessus peut être complétée par une lecture décisionnelle par secteur. "
        "Les tableaux suivants distinguent l'AEP, l'EU et l'électricité pour chaque temps de retour STORM, "
        "afin de faire ressortir les zones où la population potentiellement affectée est la plus élevée. "
        "Les lignes ne sont pas additives: une même population peut dépendre de plusieurs services ou "
        "apparaître dans plusieurs zones fonctionnelles.",
        "",
        "Qualification des états: S0 = dommage faible ou nul; S1 = dommage modéré; "
        "S2 = dommage élevé; S3 = dommage très élevé / indisponibilité potentielle.",
        "",
        "Les ouvrages listés sont des candidats associés à la zone hydraulique affectée; ils ne doivent pas "
        "être lus comme une attribution certaine à un ouvrage causal unique sans analyse des états directs "
        "avant propagation.",
        "",
    ]
    for period in PERIODS:
        label = period.upper()
        period_rows = [row for row in rows if row["periode"] == label]
        lines.append(f"**{label} - STORM**")
        lines.append("")
        for service_value, service_label in MARKDOWN_SERVICE_SECTIONS:
            service_rows = [row for row in period_rows if row["service"] == service_value]
            top_rows = sorted(
                service_rows,
                key=lambda row: -float(row["population_potentiellement_affectee"]),
            )[:5]
            lines.append(f"*{service_label}*")
            lines.append("")
            if not top_rows:
                lines.append(
                    "Aucune zone classée au-delà de S0 (dommage faible ou nul) dans les résultats population STORM "
                    "pour ce temps de retour."
                )
                lines.append("")
                continue
            lines.append("| " + " | ".join(MARKDOWN_COLUMNS) + " |")
            lines.append("| " + " | ".join("---" for _ in MARKDOWN_COLUMNS) + " |")
            for row in top_rows:
                values = [
                    row["zone_principale"],
                    row["commune_ou_secteur"],
                    _format_population_markdown(float(row["population_potentiellement_affectee"])),
                    row["type_defaillance_modelisee"],
                    row["ouvrage_ou_reseau_determinant"],
                    row["enjeu_continuite_service"],
                ]
                escaped = [value.replace("|", "/") for value in values]
                lines.append("| " + " | ".join(escaped) + " |")
            lines.append("")
    lines.append(
        "Pour l'électricité, cette synthèse doit être lue avec prudence: comme indiqué plus haut, "
        "le modèle tend probablement à sous-représenter certaines défaillances aériennes et indirectes."
    )
    lines.append("")
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complete-analysis", type=Path, default=DEFAULT_COMPLETE_ANALYSIS)
    parser.add_argument("--scientific-summary", type=Path, default=DEFAULT_SCIENTIFIC_SUMMARY)
    parser.add_argument("--network-states", type=Path, default=DEFAULT_NETWORK_STATES)
    parser.add_argument("--hydraulic-zones", type=Path, default=DEFAULT_HYDRAULIC_ZONES)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    complete_analysis = _read_json(args.complete_analysis)
    scientific_summary = _read_json(args.scientific_summary)
    rows = build_population_decision_rows(
        complete_analysis,
        scientific_summary,
        args.network_states,
        args.hydraulic_zones,
    )
    write_population_decision_csv(args.output_csv, rows)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(build_population_decision_markdown(rows), encoding="utf-8")
    print(f"[ok] CSV written to {args.output_csv}")
    print(f"[ok] Markdown snippet written to {args.output_md}")
    print(f"[ok] Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
