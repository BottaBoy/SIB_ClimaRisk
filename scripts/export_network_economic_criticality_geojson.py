#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts import generate_run_graphs as graphs  # noqa: E402


DEFAULT_SOURCES = {
    "guadeloupe": {
        "complete": Path("/home/ubuntu/uploads/from_popa/20260711_071243/scientific_archive/guadeloupe-complete-analysis.json"),
        "summary": Path("/home/ubuntu/uploads/from_popa/20260711_071243/scientific_archive/guadeloupe-scientific-web-summary.json"),
        "web_data": REPO_ROOT / "web" / "data",
    },
    "martinique": {
        "complete": REPO_ROOT / "web" / "data" / "martinique-complete-analysis.json",
        "summary": REPO_ROOT / "web" / "data" / "martinique-scientific-web-summary.json",
        "web_data": REPO_ROOT / "web" / "data",
    },
    "saint-barthelemy": {
        "complete": REPO_ROOT / "outputs" / "complete-analysis-runs" / "20260730_114218" / "territories" / "saint-barthelemy" / "web" / "data" / "saint-barthelemy-complete-analysis.json",
        "summary": REPO_ROOT / "outputs" / "complete-analysis-runs" / "20260730_114218" / "territories" / "saint-barthelemy" / "web" / "data" / "saint-barthelemy-scientific-web-summary.json",
        "web_data": REPO_ROOT / "outputs" / "complete-analysis-runs" / "20260730_114218" / "territories" / "saint-barthelemy" / "web" / "data",
    },
}

KEEP_COLUMNS = (
    "feature_id",
    "layer_key",
    "layer_label",
    "infra_type",
    "source_group",
    "economic_unit_id",
    "economic_state",
    "economic_exposure_eur",
    "economic_damage_eur",
    "economic_damage_ratio_pct",
    "economic_asset_count",
    "criticality_territory",
    "criticality_family",
    "criticality_scenario",
    "criticality_period_years",
    "criticality_hazard",
)

ROUND_DECIMALS = {
    "economic_exposure_eur": 0,
    "economic_damage_eur": 0,
    "economic_damage_ratio_pct": 3,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def build_artifacts(territory: str) -> graphs.AuxiliaryArtifacts:
    defaults = DEFAULT_SOURCES.get(territory)
    if not defaults:
      raise ValueError(f"Unsupported territory: {territory}")

    web_data_dir = Path(defaults["web_data"])
    fallback_web_data_dir = REPO_ROOT / "web" / "data"
    complete_path = first_existing([
        Path(defaults["complete"]),
        web_data_dir / f"{territory}-complete-analysis.json",
        fallback_web_data_dir / f"{territory}-complete-analysis.json",
    ])
    if not complete_path:
        raise FileNotFoundError(f"Complete-analysis JSON missing for {territory}")

    summary_path = first_existing([
        Path(defaults["summary"]),
        web_data_dir / f"{territory}-scientific-web-summary.json",
        fallback_web_data_dir / f"{territory}-scientific-web-summary.json",
    ])
    network_states_path = first_existing([
        web_data_dir / f"{territory}-network-states.geojson",
        fallback_web_data_dir / f"{territory}-network-states.geojson",
    ])
    water_infra_path = first_existing([
        web_data_dir / f"{territory}-water-infra.geojson",
        fallback_web_data_dir / f"{territory}-water-infra.geojson",
    ])

    return graphs.AuxiliaryArtifacts(
        territory=territory,
        complete_analysis=graphs.ArchivedArtifact(str(complete_path), load_json(complete_path)),
        scientific_web_summary=(
            graphs.ArchivedArtifact(str(summary_path), load_json(summary_path))
            if summary_path
            else None
        ),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=str(network_states_path) if network_states_path else None,
        water_infra_path=str(water_infra_path) if water_infra_path else None,
    )


def normalize_gdf_for_geojson(gdf: Any, *, territory: str, family: str, scenario: str, period: str, hazard: str) -> Any:
    out = gdf.copy()
    if out.crs is None:
        out = out.set_crs("EPSG:4326", allow_override=True)
    elif str(out.crs).upper() not in {"EPSG:4326", "WGS 84"}:
        out = out.to_crs("EPSG:4326")

    out[out.geometry.name] = out.geometry.simplify(0.00002, preserve_topology=True)
    out = out[out.geometry.notna() & ~out.geometry.is_empty].copy()

    out["criticality_territory"] = territory
    out["criticality_family"] = family
    out["criticality_scenario"] = scenario
    out["criticality_period_years"] = period
    out["criticality_hazard"] = hazard

    for column, decimals in ROUND_DECIMALS.items():
        if column in out.columns:
            out[column] = out[column].map(lambda value: round(float(value or 0), decimals))

    columns = [column for column in KEEP_COLUMNS if column in out.columns]
    return out[columns + [out.geometry.name]]


def gdf_to_feature_collection(gdf: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(gdf.to_json(drop_id=True))
    except TypeError:
        payload = json.loads(gdf.to_json())
        for feature in payload.get("features", []):
            feature.pop("id", None)
    payload["metadata"] = metadata
    return payload


def build_criticality_payload_with_reference_fallback(
    artifacts: graphs.AuxiliaryArtifacts,
    *,
    territory: str,
    family_key: str,
    scenario_key: str,
    scenario_label: str,
    period_label: str,
    hazard: str,
    asset_state_rows: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return graphs._build_economic_criticality_map_payload(
            artifacts,
            territory=territory,
            family_key=family_key,
            scenario_key=scenario_key,
            scenario_label=scenario_label,
            period_label=period_label,
            hazard=hazard,
            asset_state_rows=asset_state_rows,
        ), None
    except RuntimeError as exc:
        if "scientific_graph_inputs" not in str(exc):
            raise

    original_reference = graphs._economic_criticality_reference_pct

    def empty_reference(*_args: Any, **_kwargs: Any) -> dict[str, float]:
        return {state: 0.0 for state in graphs.STATE_SEQUENCE}

    graphs._economic_criticality_reference_pct = empty_reference
    try:
        payload = graphs._build_economic_criticality_map_payload(
            artifacts,
            territory=territory,
            family_key=family_key,
            scenario_key=scenario_key,
            scenario_label=scenario_label,
            period_label=period_label,
            hazard=hazard,
            asset_state_rows=asset_state_rows,
        )
    finally:
        graphs._economic_criticality_reference_pct = original_reference
    return payload, "strict matrix reference unavailable in legacy scientific graph contract"


def export_territory(territory: str, output_dir: Path, hazards: tuple[str, ...]) -> list[Path]:
    artifacts = build_artifacts(territory)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for hazard in hazards:
        rows_by_scenario = graphs._compute_economic_criticality_asset_states(artifacts, hazard=hazard)
        if rows_by_scenario is None:
            continue

        for scenario_key, scenario_label, period_label in graphs.ECONOMIC_CRITICALITY_SCENARIOS:
            for family_key in ("aep", "eu", "elec"):
                payload, reference_warning = build_criticality_payload_with_reference_fallback(
                    artifacts,
                    territory=territory,
                    family_key=family_key,
                    scenario_key=scenario_key,
                    scenario_label=scenario_label,
                    period_label=period_label,
                    hazard=hazard,
                    asset_state_rows=rows_by_scenario,
                )
                if not payload:
                    continue

                gdf = normalize_gdf_for_geojson(
                    payload["gdf"],
                    territory=territory,
                    family=family_key,
                    scenario=scenario_key,
                    period=period_label,
                    hazard=hazard,
                )
                metadata = {
                    "source": "complete-analysis economic criticality reconstructed by generate_run_graphs",
                    "territory": territory,
                    "family": family_key,
                    "scenario": scenario_key,
                    "scenario_label": scenario_label,
                    "period_years": period_label,
                    "hazard": hazard,
                    "note": payload.get("note"),
                    "feature_count": int(len(gdf)),
                    "map_reference_pct": payload.get("map_reference_pct"),
                    "matrix_reference_pct": payload.get("matrix_reference_pct"),
                    "reference_warning": reference_warning,
                }
                feature_collection = gdf_to_feature_collection(gdf, metadata)
                out_path = output_dir / f"{territory}-network-criticality-{family_key}-{scenario_key}-{hazard}.geojson"
                out_path.write_text(json.dumps(feature_collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                written.append(out_path)
                print(f"wrote {out_path} ({len(gdf)} features)")

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Export interactive network economic criticality GeoJSON layers.")
    parser.add_argument("territories", nargs="*", default=["guadeloupe", "martinique", "saint-barthelemy"])
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "web" / "data")
    parser.add_argument("--hazard", action="append", choices=("storm", "storm_cmcc"), help="Hazard to export; defaults to both.")
    args = parser.parse_args()

    hazards = tuple(args.hazard) if args.hazard else ("storm", "storm_cmcc")
    total_written: list[Path] = []
    for territory in args.territories:
        total_written.extend(export_territory(territory, args.output_dir, hazards))
    print(f"exported {len(total_written)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
