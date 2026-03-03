from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings
from ..job_store import JobStore
from .analysis_export import build_event_summary_csv, build_graph_json_artifact, build_result_payload, build_territory_csv
from .exposure_disaggregation import summarize_disaggregation
from .exposure_ingest import ingest_drawn_geojson, ingest_uploaded_exposure
from .impact_runner import compute_impacts


def run_job_pipeline(job_id: str, params: dict[str, Any], settings: Settings, store: JobStore) -> dict[str, Any]:
    input_mode = params.get("input_mode")
    sampling_spacing_m = float(params.get("sampling_spacing_m") or settings.default_sampling_spacing_m)
    value_field = params.get("value_field")
    id_field = params.get("id_field")
    asset_type_field = params.get("asset_type_field")
    exposure_category_field = params.get("exposure_category_field")
    default_exposure_category = params.get("default_exposure_category") or "habitation"
    crs = params.get("crs")

    if input_mode == "drawn_geojson":
        exposure = ingest_drawn_geojson(
            params.get("drawn_geojson") or "",
            default_exposure_category=default_exposure_category,
        )
    else:
        upload_name = str(params.get("upload_saved_name") or "")
        upload_path = store.upload_path(job_id, upload_name)
        exposure = ingest_uploaded_exposure(
            upload_path,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
            crs=crs,
        )

    disagg = summarize_disaggregation(exposure, spacing_m=sampling_spacing_m)
    comp = compute_impacts(exposure, disagg, settings=settings)

    result = build_result_payload(
        job_id=job_id,
        source="user_run",
        exposure=exposure,
        disagg=disagg,
        comp=comp,
    )

    csv_path = store.save_artifact_bytes(job_id, "territory_results.csv", build_territory_csv(result["territory_results"]))
    graphs_path = store.save_artifact_bytes(job_id, "graphs.json", build_graph_json_artifact(result["graphs"]))
    event_summary_csv = build_event_summary_csv((result.get("portfolio_results") or {}).get("event_summary"))

    downloads = [
        {"name": csv_path.name, "url": f"/api/v1/runs/{job_id}/artifacts/{csv_path.name}"},
        {"name": graphs_path.name, "url": f"/api/v1/runs/{job_id}/artifacts/{graphs_path.name}"},
    ]
    if event_summary_csv:
        event_path = store.save_artifact_bytes(job_id, "top_events.csv", event_summary_csv)
        downloads.append({"name": event_path.name, "url": f"/api/v1/runs/{job_id}/artifacts/{event_path.name}"})
    result["artifacts"]["downloads"] = downloads

    return result
