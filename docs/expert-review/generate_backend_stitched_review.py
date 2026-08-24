#!/usr/bin/env python3
"""Build a review-only stitched backend script for expert code audit.

The output is intentionally non-authoritative: original files remain the
single source of truth. This artifact improves linear readability by placing
modules in execution-flow order and adding provenance metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List
import hashlib
import textwrap


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "expert-review" / "backend_stitched_review.py"


MODULES: List[Dict[str, str]] = [
    {
        "path": "backend/app/main.py",
        "purpose": "FastAPI entrypoint exposing run/job/artefact endpoints and API lifecycle.",
        "inputs": "HTTP requests, uploaded files, run parameters, application settings.",
        "outputs": "Queued jobs, status/result payloads, downloadable artefacts.",
        "deps": "fastapi, app.config, app.job_store, app.job_runner, app.models.",
    },
    {
        "path": "backend/app/job_runner.py",
        "purpose": "Single-worker async queue processor for risk jobs.",
        "inputs": "Queued job IDs and per-job parameters from file-backed store.",
        "outputs": "Job state transitions and persisted run results.",
        "deps": "threading, queue, app.job_store, risk_engine.pipeline.",
    },
    {
        "path": "backend/app/risk_engine/pipeline.py",
        "purpose": "End-to-end orchestration: ingest -> disaggregation -> impacts -> export.",
        "inputs": "Run params, uploaded/drawn exposures, runtime settings.",
        "outputs": "Unified API payload and downloadable CSV/JSON artefacts.",
        "deps": "exposure_ingest, exposure_disaggregation, impact_runner, analysis_export.",
    },
    {
        "path": "backend/app/risk_engine/exposure_ingest.py",
        "purpose": "Input normalization for CSV/XLSX/GeoJSON/GPKG and drawn GeoJSON.",
        "inputs": "Raw exposure files or drawn FeatureCollection + field mapping options.",
        "outputs": "Normalized exposure model consumed by the risk engine.",
        "deps": "pandas/geopandas/shapely (runtime), normalization helpers, validation.",
    },
    {
        "path": "backend/app/risk_engine/exposure_disaggregation.py",
        "purpose": "Geometry complexity summary used for sampling and reporting.",
        "inputs": "Normalized exposure dataset and spacing parameters.",
        "outputs": "Disaggregation summary (counts, geometry stats, spacing metadata).",
        "deps": "Normalized exposure types, lightweight geometry heuristics.",
    },
    {
        "path": "backend/app/risk_engine/impact_runner.py",
        "purpose": "Main impact orchestration (CLIMADA path + deterministic fallback path).",
        "inputs": "Normalized exposure, disaggregation summary, runtime settings.",
        "outputs": "Territory/asset/portfolio results, graphs, notes, modeling metadata.",
        "deps": "climada_engine, exposure_to_climada, interdependency, settings.",
    },
    {
        "path": "backend/app/risk_engine/exposure_to_climada.py",
        "purpose": "Converts exposure geometries to CLIMADA-compatible sampled points.",
        "inputs": "Normalized features, spacing, metric CRS, max points per feature.",
        "outputs": "CLIMADA Exposures object + point-level records with business mapping.",
        "deps": "geopandas, shapely, pyproj, climada.entity.Exposures.",
    },
    {
        "path": "backend/app/risk_engine/climada_engine.py",
        "purpose": "Computes direct impacts with CLIMADA and extracts risk metrics.",
        "inputs": "Point exposures + STORM/STORM_CMCC hazards + runtime options.",
        "outputs": "Per-hazard direct metrics (EAI, event losses, PML, TVaR, top events).",
        "deps": "climada.engine.ImpactCalc, hazard_loader, impact_functions.",
    },
    {
        "path": "backend/app/risk_engine/hazard_loader.py",
        "purpose": "Loads precomputed hazards and optionally builds dynamic hazards from parquet.",
        "inputs": "Hazard files/datasets, basin coverage, point coordinates, unit settings.",
        "outputs": "HazardBundle with normalized frequencies and source metadata.",
        "deps": "climada.hazard, pandas/xarray, basin filtering and caching logic.",
    },
    {
        "path": "backend/app/risk_engine/impact_functions.py",
        "purpose": "Builds tropical-cyclone impact function set used by CLIMADA.",
        "inputs": "Configured/default vulnerability curve assumptions.",
        "outputs": "CLIMADA-compatible impact function instance(s).",
        "deps": "climada.entity.impact_funcs and numeric helpers.",
    },
    {
        "path": "backend/app/risk_engine/impact_functions_multi_hazard.py",
        "purpose": "Builds rain/surge impact-function sets and asset-type mapping from D2 flood curves.",
        "inputs": "Flood curve workbook, hazard type identifiers, per-asset mapping overrides.",
        "outputs": "Multi-hazard impact-function model with rain+surge CLIMADA functions.",
        "deps": "openpyxl/pandas/numpy parsing and CLIMADA ImpactFunc constructors.",
    },
    {
        "path": "backend/app/risk_engine/impact_functions_landslide.py",
        "purpose": "Defines landslide vulnerability curves and CLIMADA bridge helpers.",
        "inputs": "SIB landslide assumptions and optional D2 proxy worksheet values.",
        "outputs": "Landslide vulnerability payload and optional CLIMADA impact functions.",
        "deps": "openpyxl (optional), numpy (optional), CLIMADA impact function primitives.",
    },
    {
        "path": "backend/app/risk_engine/landslide_engine.py",
        "purpose": "Runs landslide hazard assembly and direct-impact computation with CLIMADA Petals.",
        "inputs": "Exposure bundle, raster probability source, bbox, simulation parameters.",
        "outputs": "Landslide direct metrics and scenario loss factors.",
        "deps": "climada_petals landslide runtime, scipy sparse, shapely bbox clipping.",
    },
    {
        "path": "backend/app/risk_engine/interdependency.py",
        "purpose": "Applies conservative electricity->water dependency post-processing.",
        "inputs": "Point-level direct EAI/max-loss arrays per hazard.",
        "outputs": "Adjusted direct/indirect totals, health metrics, dependency diagnostics.",
        "deps": "state thresholds, uplift table, territory lookup and nearest fallback.",
    },
    {
        "path": "backend/app/risk_engine/population_loader.py",
        "purpose": "Loads WorldPop rasters and aggregates population by SIB territory grid cells.",
        "inputs": "Population raster directory and territory bounds.",
        "outputs": "Population counts keyed by grid-cell territory IDs.",
        "deps": "rasterio and numpy (optional runtime dependencies).",
    },
    {
        "path": "backend/app/risk_engine/social_impact.py",
        "purpose": "Computes social impact metrics from network states and population totals.",
        "inputs": "Per-hazard detailed territory states and population-by-territory values.",
        "outputs": "Per-territory social metrics and portfolio-level social summaries.",
        "deps": "risk_engine.types.SocialImpactMetrics and aggregation helpers.",
    },
    {
        "path": "backend/app/risk_engine/sensitivity_scenarios.py",
        "purpose": "Loads sensitivity scenario packs and applies settings overrides safely.",
        "inputs": "Scenario pack JSON and selected scenario identifiers.",
        "outputs": "Validated scenario metadata and effective runtime settings.",
        "deps": "dataclasses, JSON validation, app.config.Settings.",
    },
    {
        "path": "backend/app/risk_engine/analysis_export.py",
        "purpose": "Final payload and artefact serialization helpers.",
        "inputs": "Computation result + exposure/disaggregation context.",
        "outputs": "API JSON payload, territory CSV, event CSV, graph JSON.",
        "deps": "types, csv/json formatting helpers.",
    },
    {
        "path": "backend/app/config.py",
        "purpose": "Runtime settings model and environment-variable loader.",
        "inputs": "Environment variables and default project paths.",
        "outputs": "Immutable settings object used across API and engine modules.",
        "deps": "pathlib, dataclasses, env parsing utilities.",
    },
    {
        "path": "backend/app/models.py",
        "purpose": "API response and job-status models.",
        "inputs": "API contract fields and job lifecycle values.",
        "outputs": "Typed models/enums for request/response payloads.",
        "deps": "pydantic/dataclass typing models used by FastAPI endpoints.",
    },
    {
        "path": "backend/app/job_store.py",
        "purpose": "File-backed job persistence, metadata updates, and artefact storage.",
        "inputs": "Job parameters, uploaded files, computed results.",
        "outputs": "Job envelopes, persisted payloads, local artefact files.",
        "deps": "filesystem operations, JSON serialization, TTL cleanup logic.",
    },
    {
        "path": "backend/app/risk_engine/types.py",
        "purpose": "Typed structures shared by ingest, compute, and export modules.",
        "inputs": "Normalized feature/exposure/computation field definitions.",
        "outputs": "Consistent strongly-typed payload containers.",
        "deps": "dataclasses and typing primitives.",
    },
    {
        "path": "backend/app/risk_engine/errors.py",
        "purpose": "Domain-level exceptions used by the pipeline and API layer.",
        "inputs": "Validation/dependency/runtime error conditions.",
        "outputs": "Explicit exception classes for predictable error handling.",
        "deps": "built-in exception base classes only.",
    },
    {
        "path": "backend/app/__init__.py",
        "purpose": "Package marker for API app namespace.",
        "inputs": "N/A.",
        "outputs": "Python package importability.",
        "deps": "N/A.",
    },
    {
        "path": "backend/app/risk_engine/__init__.py",
        "purpose": "Package marker for risk engine namespace.",
        "inputs": "N/A.",
        "outputs": "Python package importability.",
        "deps": "N/A.",
    },
    {
        "path": "backend/scripts/run_backoffice_sample.py",
        "purpose": "CLI sample runner to execute one backoffice-like scenario.",
        "inputs": "Input file path + field mapping arguments.",
        "outputs": "A full run result payload and optional artefacts for manual checks.",
        "deps": "risk_engine pipeline modules and local backend config/runtime.",
    },
    {
        "path": "backend/scripts/cleanup_expired_jobs.py",
        "purpose": "Maintenance utility removing expired job folders/files.",
        "inputs": "Job root path and TTL settings.",
        "outputs": "Deleted expired run data and cleanup log info.",
        "deps": "job_store cleanup methods.",
    },
]


def _read_source(path: Path) -> tuple[str, int]:
    content = path.read_text(encoding="utf-8")
    # Keep trailing newline deterministic for stable hashing.
    if not content.endswith("\n"):
        content = f"{content}\n"
    return content, len(content.splitlines())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_output() -> str:
    lines: List[str] = []

    lines.append("#!/usr/bin/env python3")
    lines.append('"""')
    lines.append("SIB Backend - Stitched Review Artifact (Non-Authoritative)")
    lines.append("")
    lines.append("WARNING:")
    lines.append("- This file is generated for expert review only.")
    lines.append("- Original modular files remain the source of truth.")
    lines.append("- Do not edit this file for production changes.")
    lines.append("")
    lines.append("Generated mode: deterministic (content depends only on source files + module metadata).")
    lines.append(f"Generator: {Path(__file__).name}")
    lines.append(f"Repository root: {ROOT}")
    lines.append('"""')
    lines.append("")

    lines.append("# Execution-flow ordered module index")
    for idx, module in enumerate(MODULES, start=1):
        lines.append(f"# {idx:02d}. {module['path']}")
    lines.append("")

    for idx, module in enumerate(MODULES, start=1):
        rel_path = module["path"]
        src_path = ROOT / rel_path
        if not src_path.exists():
            raise FileNotFoundError(f"Missing source file listed in MODULES: {src_path}")
        source, line_count = _read_source(src_path)
        file_hash = _sha256_text(source)

        header = textwrap.dedent(
            f"""
            # ============================================================================
            # MODULE {idx:02d}/{len(MODULES):02d}
            # Source file: {rel_path}
            # Provenance path: {src_path}
            # Original line span: 1-{line_count}
            # Source SHA256: {file_hash}
            # Purpose: {module['purpose']}
            # Key Inputs: {module['inputs']}
            # Key Outputs: {module['outputs']}
            # Dependency Notes: {module['deps']}
            # ----------------------------------------------------------------------------
            # BEGIN SOURCE: {rel_path}
            # ============================================================================
            """
        ).strip("\n")
        lines.append(header)
        lines.append(source.rstrip("\n"))
        lines.append(f"# END SOURCE: {rel_path}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    seen = [item["path"] for item in MODULES]
    if len(seen) != len(set(seen)):
        raise ValueError("MODULES contains duplicate file paths; stitching must be one-file-once.")

    for item in MODULES:
        if not (ROOT / item["path"]).exists():
            raise FileNotFoundError(f"Listed module not found: {item['path']}")

    payload = build_output()
    OUTPUT.write_text(payload, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(payload.splitlines())} lines)")


if __name__ == "__main__":
    main()
