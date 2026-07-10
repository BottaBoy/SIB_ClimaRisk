#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.config import resolve_surge_topo_path_for_territory
from app.risk_engine.analysis_export import build_result_payload
from app.risk_engine.exposure_disaggregation import summarize_disaggregation
from app.risk_engine.impact_runner import compute_impacts, prepare_climada_exposure_bundle
from app.risk_engine.targeted_cyclone_loader import (
    TargetedCycloneRequest,
    build_targeted_cyclone_hazard_bundle,
    build_transposed_targeted_cyclones,
)
from case_study_sources import CASE_STUDY_BBOX, parse_territory, territory_label
from run_complete_analysis import (
    JOURNAL_JSONL,
    JOURNAL_MD,
    RunLogger,
    RunManifest,
    _build_complete_analysis_settings,
    build_complete_exposure,
)


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

UTC = timezone.utc
TARGETED_RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "targeted-cyclone-runs"
PRESETS_PATH = REPO_ROOT / "config" / "targeted-cyclones" / "presets.json"
DEFAULT_GRAPH_OUTPUT_DIR = REPO_ROOT / "outputs" / "Graphs"
SAFFIR_SIMPSON_THRESHOLDS_KN = [34.0, 64.0, 83.0, 96.0, 113.0, 137.0, 1000.0]
SAFFIR_SIMPSON_LABELS = {
    -1: "Tropical Depression",
    0: "Tropical Storm",
    1: "Cat 1",
    2: "Cat 2",
    3: "Cat 3",
    4: "Cat 4",
    5: "Cat 5",
}
SAFFIR_SIMPSON_COLORS = {
    -1: "#94a3b8",
    0: "#38bdf8",
    1: "#22c55e",
    2: "#facc15",
    3: "#fb923c",
    4: "#ef4444",
    5: "#7f1d1d",
}


def _load_presets(path: Path = PRESETS_PATH) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    out: dict[str, dict[str, Any]] = {}
    for preset_id, entry in payload.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid preset payload for {preset_id!r} in {path}")
        out[str(preset_id)] = dict(entry)
    return out


def _print_presets(presets: dict[str, dict[str, Any]]) -> None:
    for preset_id in sorted(presets.keys()):
        entry = presets[preset_id]
        print(
            f"{preset_id}: source={entry.get('source')} "
            f"name={entry.get('name')} season={entry.get('season')} basin={entry.get('basin')} "
            f"storm_id={entry.get('storm_id')}"
        )


def _territory_center(territory: str) -> tuple[float, float]:
    bbox = CASE_STUDY_BBOX[str(territory)]
    lat = (float(bbox["lat_min"]) + float(bbox["lat_max"])) / 2.0
    lon = (float(bbox["lon_min"]) + float(bbox["lon_max"])) / 2.0
    return lat, lon


def _build_request_list(
    cyclone_ids: list[str],
    presets: dict[str, dict[str, Any]],
) -> list[TargetedCycloneRequest]:
    requests: list[TargetedCycloneRequest] = []
    for preset_id in cyclone_ids:
        if preset_id not in presets:
            raise ValueError(
                f"Unknown cyclone preset {preset_id!r}. Available presets: {', '.join(sorted(presets.keys()))}"
            )
        entry = presets[preset_id]
        requests.append(
            TargetedCycloneRequest(
                preset_id=str(preset_id),
                source=str(entry.get("source") or "ibtracs"),
                name=str(entry.get("name") or ""),
                season=int(entry.get("season") or 0),
                basin=str(entry.get("basin") or ""),
                storm_id=str(entry.get("storm_id") or "").strip() or None,
            )
        )
    return requests


def _normalize_wind_to_kn(value: Any, wind_unit: str) -> float:
    numeric = float(value)
    unit = str(wind_unit or "kn").strip().lower()
    if unit in {"kn", "kt", "kts", "knot", "knots"}:
        return numeric
    if unit in {"m/s", "mps", "ms-1"}:
        return numeric * 1.9438444924406
    if unit in {"km/h", "kmh", "kph"}:
        return numeric / 1.852
    if unit in {"mph"}:
        return numeric / 1.1507794480235
    return numeric


def _saffir_simpson_category(wind_value: Any, wind_unit: str) -> int:
    wind_kn = _normalize_wind_to_kn(wind_value, wind_unit)
    for index, threshold in enumerate(SAFFIR_SIMPSON_THRESHOLDS_KN):
        if wind_kn < threshold:
            return index - 1
    return 5


def _segment_category(start_wind: Any, end_wind: Any, wind_unit: str) -> int:
    start_kn = _normalize_wind_to_kn(start_wind, wind_unit)
    end_kn = _normalize_wind_to_kn(end_wind, wind_unit)
    return _saffir_simpson_category(max(start_kn, end_kn), "kn")


def _track_feature(cyclone: Any) -> dict[str, Any]:
    track = cyclone.translated_track
    lon_values = [float(value) for value in list(track["lon"].values)]
    lat_values = [float(value) for value in list(track["lat"].values)]
    wind_values = [float(value) for value in list(track["max_sustained_wind"].values)]
    wind_unit = str(getattr(track, "attrs", {}).get("max_sustained_wind_unit") or "kn")
    time_values = [str(value) for value in list(track["time"].values)] if "time" in track else []
    point_categories = [_saffir_simpson_category(value, wind_unit) for value in wind_values]
    coordinates = [[lon, lat] for lon, lat in zip(lon_values, lat_values)]
    properties = cyclone.to_metadata()
    properties["trajectory"] = {
        "wind_unit": wind_unit,
        "time": time_values,
        "max_sustained_wind": wind_values,
        "saffir_simpson_categories": point_categories,
        "saffir_simpson_labels": [SAFFIR_SIMPSON_LABELS.get(category, "Unknown") for category in point_categories],
    }
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
    }


def _track_segment_features(cyclone: Any) -> list[dict[str, Any]]:
    track = cyclone.translated_track
    lon_values = [float(value) for value in list(track["lon"].values)]
    lat_values = [float(value) for value in list(track["lat"].values)]
    wind_values = [float(value) for value in list(track["max_sustained_wind"].values)]
    wind_unit = str(getattr(track, "attrs", {}).get("max_sustained_wind_unit") or "kn")
    time_values = [str(value) for value in list(track["time"].values)] if "time" in track else []
    base_metadata = cyclone.to_metadata()
    features: list[dict[str, Any]] = []
    for index in range(len(lon_values) - 1):
        category = _segment_category(wind_values[index], wind_values[index + 1], wind_unit)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    **base_metadata,
                    "segment_index": index,
                    "wind_unit": wind_unit,
                    "start_time": time_values[index] if index < len(time_values) else "",
                    "end_time": time_values[index + 1] if index + 1 < len(time_values) else "",
                    "start_wind": float(wind_values[index]),
                    "end_wind": float(wind_values[index + 1]),
                    "start_wind_kn": round(_normalize_wind_to_kn(wind_values[index], wind_unit), 3),
                    "end_wind_kn": round(_normalize_wind_to_kn(wind_values[index + 1], wind_unit), 3),
                    "saffir_simpson_category": category,
                    "saffir_simpson_label": SAFFIR_SIMPSON_LABELS.get(category, "Unknown"),
                    "segment_color": SAFFIR_SIMPSON_COLORS.get(category, "#475569"),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [lon_values[index], lat_values[index]],
                        [lon_values[index + 1], lat_values[index + 1]],
                    ],
                },
            }
        )
    return features


def _write_track_geojsons(track_output_path: Path, segment_output_path: Path, cyclones: list[Any]) -> tuple[str, str]:
    payload = {
        "type": "FeatureCollection",
        "features": [_track_feature(cyclone) for cyclone in cyclones],
    }
    segments_payload = {
        "type": "FeatureCollection",
        "features": [
            feature
            for cyclone in cyclones
            for feature in _track_segment_features(cyclone)
        ],
    }
    track_output_path.parent.mkdir(parents=True, exist_ok=True)
    track_output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    segment_output_path.write_text(json.dumps(segments_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(track_output_path), str(segment_output_path)


def _export_targeted_run_outputs(
    *,
    run_id: str,
    graph_formats: str,
    graph_output_dir: str,
) -> None:
    from generate_run_graphs import main as generate_run_graphs_main

    exit_code = generate_run_graphs_main(
        [
            "--run-family",
            "targeted-cyclone",
            "--run-id",
            str(run_id),
            "--formats",
            str(graph_formats),
            "--output-dir",
            str(graph_output_dir),
        ]
    )
    if exit_code != 0:
        raise RuntimeError(f"Targeted graph export failed for run {run_id} with exit code {exit_code}")


def _build_run_id() -> str:
    return f"targeted_cyclone_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


def _default_parameters(args: argparse.Namespace, territory: str, cyclone_ids: list[str]) -> dict[str, Any]:
    return {
        "run_family": "targeted-cyclone",
        "report_semantics": "event",
        "territories": [territory],
        "territory": territory,
        "cyclones": list(cyclone_ids),
        "dynamic_max_tracks": int(args.dynamic_max_tracks),
        "requested_dynamic_max_tracks": int(args.dynamic_max_tracks),
        "memory_budget_gb": float(args.memory_budget_gb),
        "max_points_per_shard": int(args.max_points_per_shard),
        "min_points_per_shard": int(args.min_points_per_shard),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a targeted historical cyclone impact analysis using IBTrACS tracks, "
            "transposed onto a selected SIB territory, and archive the result like a complete-analysis run."
        )
    )
    parser.add_argument("--cyclones", nargs="+", default=["irma-2017"], help="Preset IDs from config/targeted-cyclones/presets.json")
    parser.add_argument("--territory", default="saint-barthelemy", help="Target territory alias, e.g. saint-barthelemy or stb")
    parser.add_argument("--dynamic-max-tracks", type=int, default=1200)
    parser.add_argument("--memory-budget-gb", type=float, default=6.0)
    parser.add_argument("--max-points-per-shard", type=int, default=0)
    parser.add_argument("--min-points-per-shard", type=int, default=512)
    parser.add_argument("--list-cyclones", action="store_true", help="List available cyclone presets and exit")
    parser.add_argument("--graph-formats", default="html,png", help="Comma-separated graph pack outputs generated after a successful targeted run")
    parser.add_argument("--graph-output-dir", default=str(DEFAULT_GRAPH_OUTPUT_DIR), help="Output root directory for generated graph packs")
    parser.add_argument("--skip-output-export", action="store_true", help="Skip automatic graph/table/map generation after the targeted run")
    args = parser.parse_args(argv)

    presets = _load_presets()
    if args.list_cyclones:
        _print_presets(presets)
        return 0

    territory = parse_territory(args.territory)
    cyclone_ids = [str(value).strip() for value in list(args.cyclones or []) if str(value).strip()]
    if not cyclone_ids:
        raise ValueError("At least one cyclone preset must be selected")

    run_id = _build_run_id()
    parameters = _default_parameters(args, territory, cyclone_ids)
    run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL, run_id=run_id)
    run_manifest = RunManifest(TARGETED_RUN_OUTPUTS_DIR, run_id, parameters)
    run_manifest.data["run_family"] = "targeted-cyclone"
    run_manifest.data["report_semantics"] = "event"
    run_manifest._write()

    logger.info("Starting targeted cyclone analysis run_id=%s territory=%s cyclones=%s", run_id, territory, cyclone_ids)
    run_manifest.set_territory_status(territory, "running")

    try:
        run_manifest.set_phase(territory, "load_exposure", "running")
        exposure_start = time.time()
        exposure, asset_count = build_complete_exposure(territory=territory)
        exposure_duration = time.time() - exposure_start
        run_manifest.set_phase(
            territory,
            "load_exposure",
            "complete",
            asset_count=int(asset_count),
            duration_seconds=int(exposure_duration),
        )
        run_logger.log_event(
            "load_exposure",
            territory=territory,
            asset_count=int(asset_count),
            duration_seconds=int(exposure_duration),
            status="complete",
        )

        settings = _build_complete_analysis_settings(
            dynamic_max_tracks=int(args.dynamic_max_tracks),
            track_sample_manifest_path=None,
            memory_budget_gb=float(args.memory_budget_gb),
            max_points_per_shard=int(args.max_points_per_shard),
            min_points_per_shard=int(args.min_points_per_shard),
            allow_degraded_components=False,
            scenario=None,
        )
        settings = dataclasses.replace(
            settings,
            storm_years=1,
            hazard_prefer_dynamic_from_parquet=False,
            hazard_surge_topo_path=resolve_surge_topo_path_for_territory(territory, settings=settings),
        )

        run_manifest.set_phase(territory, "disaggregation", "running")
        disagg_start = time.time()
        disagg = summarize_disaggregation(
            exposure,
            spacing_m=float(settings.default_sampling_spacing_m),
            metric_crs=settings.climada_metric_crs,
            max_points_per_feature=int(settings.climada_max_points_per_feature),
        )
        climada_bundle = prepare_climada_exposure_bundle(exposure, disagg, settings)
        disagg = dataclasses.replace(disagg, asset_count_points=len(climada_bundle.point_records))
        disagg_duration = time.time() - disagg_start
        run_manifest.set_phase(
            territory,
            "disaggregation",
            "complete",
            point_count=int(disagg.asset_count_points),
            spacing_m=float(disagg.spacing_m),
            duration_seconds=int(disagg_duration),
        )
        run_logger.log_event(
            "disaggregation",
            territory=territory,
            point_count=int(disagg.asset_count_points),
            spacing_m=float(disagg.spacing_m),
            duration_seconds=int(disagg_duration),
            status="complete",
        )

        run_manifest.set_phase(
            territory,
            "load_targeted_track",
            "running",
            selected_cyclones=cyclone_ids,
        )
        logger.info("Loading and transposing targeted IBTrACS cyclone(s): %s", ", ".join(cyclone_ids))
        targeted_track_start = time.time()
        requests = _build_request_list(cyclone_ids, presets)
        target_lat, target_lon = _territory_center(territory)
        transposed_cyclones = build_transposed_targeted_cyclones(
            requests,
            target_lat=float(target_lat),
            target_lon=float(target_lon),
            territory_key=territory,
        )
        run_manifest.set_phase(
            territory,
            "load_targeted_track",
            "complete",
            duration_seconds=int(time.time() - targeted_track_start),
            cyclone_count=len(transposed_cyclones),
            storm_ids=[cyclone.resolved.storm_id for cyclone in transposed_cyclones],
        )
        run_logger.log_event(
            "load_targeted_track",
            territory=territory,
            duration_seconds=int(time.time() - targeted_track_start),
            cyclone_count=len(transposed_cyclones),
            storm_ids=[cyclone.resolved.storm_id for cyclone in transposed_cyclones],
            status="complete",
        )
        point_coords = [
            (float(record.get("lat")), float(record.get("lon")))
            for record in list(climada_bundle.point_records or [])
            if record.get("lat") is not None and record.get("lon") is not None
        ]
        run_manifest.set_phase(
            territory,
            "build_targeted_hazard",
            "running",
            point_count=len(point_coords),
            cyclone_count=len(transposed_cyclones),
        )
        logger.info(
            "Building targeted hazard bundle for %s cyclone(s) on %s exposure points",
            len(transposed_cyclones),
            len(point_coords),
        )
        targeted_hazard_start = time.time()
        explicit_hazard_bundle = build_targeted_cyclone_hazard_bundle(
            cyclones=transposed_cyclones,
            point_coords=point_coords,
            source_label="explicit_ibtracs_targeted",
            storm_years=1,
        )
        run_manifest.set_phase(
            territory,
            "build_targeted_hazard",
            "complete",
            point_count=len(point_coords),
            cyclone_count=len(transposed_cyclones),
            duration_seconds=int(time.time() - targeted_hazard_start),
        )
        run_logger.log_event(
            "build_targeted_hazard",
            territory=territory,
            point_count=len(point_coords),
            cyclone_count=len(transposed_cyclones),
            duration_seconds=int(time.time() - targeted_hazard_start),
            status="complete",
        )

        run_manifest.set_phase(
            territory,
            "impacts",
            "running",
            hazard_mode="explicit_ibtracs_targeted",
            selected_cyclones=cyclone_ids,
        )
        impact_start = time.time()

        def _on_climada_progress(payload: dict[str, Any]) -> None:
            run_manifest.record_climada_event(territory, payload)
            run_logger.log_event("impact_component", territory=territory, **payload)

        comp = compute_impacts(
            exposure,
            disagg,
            settings=settings,
            progress_callback=_on_climada_progress,
            prebuilt_bundle=climada_bundle,
            hazard_keys=("storm",),
            explicit_hazard_bundle=explicit_hazard_bundle,
        )
        impact_duration = time.time() - impact_start
        storm_results = (comp.portfolio_results or {}).get("storm") if isinstance(comp.portfolio_results, dict) else {}
        run_manifest.set_phase(
            territory,
            "impacts",
            "complete",
            eai_eur=float((storm_results or {}).get("eai_eur") or 0.0),
            duration_seconds=int(impact_duration),
            modeling=comp.modeling,
        )
        run_logger.log_event(
            "impacts",
            territory=territory,
            eai_eur=float((storm_results or {}).get("eai_eur") or 0.0),
            duration_seconds=int(impact_duration),
            status="complete",
        )

        run_manifest.set_phase(territory, "export", "running")
        payload = build_result_payload(
            job_id=f"{territory}_targeted_cyclone",
            source=f"{territory}_targeted_cyclone",
            run_label=f"Targeted cyclone {', '.join(cyclone_ids)} on {territory}",
            exposure=exposure,
            disagg=disagg,
            comp=comp,
        )
        payload.setdefault("meta", {})
        payload["meta"]["title"] = f"{territory_label(territory)} Targeted Cyclone Impact"
        payload["meta"]["run_family"] = "targeted-cyclone"
        payload["meta"]["report_semantics"] = "event"
        payload["meta"]["hazards"] = ["STORM"]
        payload["meta"]["case_study_territory"] = territory
        payload["meta"]["selected_cyclones"] = [cyclone.to_metadata() for cyclone in transposed_cyclones]
        payload["meta"]["selected_cyclone_ids"] = list(cyclone_ids)
        payload["meta"]["transposition_mode"] = "max_wind_anchor_translation"
        payload["meta"]["target_center"] = {
            "lat": float(target_lat),
            "lon": float(target_lon),
        }
        payload["meta"]["event_report_warning"] = (
            "This targeted-cyclone run uses transposed historical IBTrACS events. "
            "Event-derived metrics must not be interpreted as probabilistic climate return-period metrics."
        )
        payload["notes"] = list(payload.get("notes") or [])
        payload["notes"].append(
            "Targeted-cyclone report semantics are event-based. Annualized or tail-risk metrics are retained for traceability only and are not climatological."
        )
        payload["notes"].append(
            "Historical IBTrACS tracks were transposed by rigid translation so that the maximum-wind timestep is anchored on the selected territory centroid."
        )

        output_dir = run_manifest.run_dir / "territories" / territory / "web" / "data"
        output_dir.mkdir(parents=True, exist_ok=True)
        complete_analysis_path = output_dir / f"{territory}-complete-analysis.json"
        track_geojson_path = output_dir / f"{territory}-targeted-cyclones.geojson"
        track_segments_geojson_path = output_dir / f"{territory}-targeted-cyclone-segments.geojson"
        payload["meta"]["targeted_cyclone_track_geojson"] = str(track_geojson_path)
        payload["meta"]["targeted_cyclone_track_segments_geojson"] = str(track_segments_geojson_path)
        complete_analysis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_track_geojsons(track_geojson_path, track_segments_geojson_path, transposed_cyclones)

        run_manifest.set_phase(
            territory,
            "export",
            "complete",
            output_file=str(complete_analysis_path),
            archived_output_file=str(complete_analysis_path),
            targeted_cyclone_track_geojson=str(track_geojson_path),
            targeted_cyclone_track_segments_geojson=str(track_segments_geojson_path),
        )
        run_manifest.set_territory_status(
            territory,
            "complete",
            complete_analysis_path=str(complete_analysis_path),
            archived_complete_analysis_path=str(complete_analysis_path),
        )
        run_logger.log_event(
            "export",
            territory=territory,
            output_file=str(complete_analysis_path),
            status="complete",
        )

        if not args.skip_output_export:
            run_manifest.set_phase(territory, "graph_export", "running", formats=str(args.graph_formats))
            graph_export_start = time.time()
            _export_targeted_run_outputs(
                run_id=run_id,
                graph_formats=str(args.graph_formats),
                graph_output_dir=str(args.graph_output_dir),
            )
            run_manifest.set_phase(
                territory,
                "graph_export",
                "complete",
                output_dir=str(Path(args.graph_output_dir) / run_id),
                duration_seconds=int(time.time() - graph_export_start),
                formats=str(args.graph_formats),
            )
            run_logger.log_event(
                "graph_export",
                territory=territory,
                output_dir=str(Path(args.graph_output_dir) / run_id),
                duration_seconds=int(time.time() - graph_export_start),
                status="complete",
            )

        run_manifest.set_status(
            "success",
            finished_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            frontend_required=False,
            frontend_artifacts={"status": "skipped", "reason": "targeted_cyclone_v1"},
            territories_completed=1,
        )
        run_logger.finalize(
            status="success",
            territories_completed=1,
            territory=territory,
            run_family="targeted-cyclone",
        )
        logger.info("Targeted cyclone run complete: run_id=%s archived=%s", run_id, complete_analysis_path)
        return 0
    except Exception:
        logger.exception("Targeted cyclone run failed: run_id=%s", run_id)
        run_manifest.set_status(
            "failed",
            finished_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            frontend_required=False,
            frontend_artifacts={"status": "skipped", "reason": "targeted_cyclone_v1"},
        )
        run_logger.finalize(status="failed", territories_completed=0, run_family="targeted-cyclone")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
