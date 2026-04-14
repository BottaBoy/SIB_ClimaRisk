#!/usr/bin/env python3
"""
Complete SIB pipeline runner with logging and auto-deployment.

Executes full impact analysis for Guadeloupe and/or Martinique with configurable parameters.
Automatically logs results and deploys to web server.

Usage:
    python3 run_complete_analysis.py
    python3 run_complete_analysis.py --dynamic-max-tracks 1500
    python3 run_complete_analysis.py --territories gua
    python3 run_complete_analysis.py --no-deploy
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

# Setup paths
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from collections import Counter

# External imports with graceful fallbacks
try:
    import geopandas as gpd
except ImportError:
    gpd = None

try:
    from shapely.geometry import box
except ImportError:
    box = None

# Backend imports
from app.risk_engine.analysis_export import build_result_payload
from app.config import load_settings, Settings
from app.risk_engine.exposure_disaggregation import summarize_disaggregation
from app.risk_engine.impact_runner import compute_impacts
from app.risk_engine.types import NormalizedExposure, NormalizedFeature

# Case study specific
sys.path.insert(0, str(SCRIPTS_ROOT))
from case_study_sources import get_case_study, normalize_territory, territory_label
from valuation_ofb import (
    SOURCE_LABEL,
    VALUATION_VERSION,
    build_valuation_metadata,
    get_aep_ouvrage_value,
    get_elec_values,
    get_water_values,
)

# Logging setup
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)

# Constants
METRIC_CRS = "EPSG:5490"
WGS84 = "EPSG:4326"
CASE_HAZARD_PATHS = {
    "guadeloupe": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
    "martinique": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_martinique_CMCC.h5",
    ),
}

WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DOCS_DIR = REPO_ROOT / "docs"
JOURNAL_MD = DOCS_DIR / "Journalisation_Run_GuaMar.md"
JOURNAL_JSONL = DOCS_DIR / "Journalisation_Run_GuaMar.jsonl"


class RunLogger:
    """Manages dual-format logging (markdown + JSONL)."""

    def __init__(self, markdown_path: Path, jsonl_path: Path):
        self.markdown_path = Path(markdown_path)
        self.jsonl_path = Path(jsonl_path)
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()
        self.events: list[dict[str, Any]] = []
        
        # Ensure directories exist
        self.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, phase: str, territory: str | None = None, **kwargs) -> None:
        """Log an event in JSONL format."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "phase": phase,
        }
        if territory:
            event["territory"] = territory
        event.update(kwargs)
        self.events.append(event)
        
        # Append to JSONL
        self.jsonl_path.write_text(
            self.jsonl_path.read_text(errors="ignore") + json.dumps(event) + "\n",
            encoding="utf-8"
        )

    def finalize(self, status: str = "success", **summary) -> None:
        """Finalize run and write markdown summary."""
        duration = time.time() - self.start_time
        self.log_event("complete", status=status, duration_seconds=int(duration), **summary)
        
        # Build markdown
        md_lines = [
            "# Journalisation Runs Guadeloupe & Martinique",
            "",
        ]
        
        # Group events by run_id and write summary
        if self.markdown_path.exists():
            md_lines = self.markdown_path.read_text(encoding="utf-8").split("\n")
        
        # Add new run section
        run_section = [
            "",
            f"## Run [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}]",
            f"**Run ID**: `{self.run_id}`",
        ]
        
        # Extract territory summaries
        territory_events = {}
        for event in self.events:
            terr = event.get("territory")
            if terr and terr not in territory_events:
                territory_events[terr] = {}
            if terr:
                territory_events[terr][event.get("phase", "")] = event
        
        for territory in ["guadeloupe", "martinique"]:
            if territory in territory_events:
                events = territory_events[territory]
                run_section.append(f"### {territory.capitalize()}")
                
                if "load_exposure" in events:
                    assets = events["load_exposure"].get("asset_count", "?")
                    run_section.append(f"- Assets loaded: {assets}")
                
                if "impacts" in events:
                    eai = events["impacts"].get("eai_eur", 0)
                    run_section.append(f"- EAI: {eai:,.0f} EUR")
                
                if "export" in events:
                    run_section.append("- Status: ✓ Complete")
        
        run_section.append(f"**Total Duration**: {int(duration)}s ({int(duration)/60:.1f}m)")
        run_section.append("")
        
        # Append to markdown
        if not self.markdown_path.exists():
            md_lines = [
                "# Journalisation Runs Guadeloupe & Martinique",
                "",
            ]
        else:
            md_lines = self.markdown_path.read_text(encoding="utf-8").split("\n")
        
        # Find insertion point (after header)
        insert_idx = 2
        for line in md_lines[2:]:
            if line.startswith("## Run"):
                break
            insert_idx += 1
        
        md_lines = md_lines[:insert_idx] + run_section + md_lines[insert_idx:]
        self.markdown_path.write_text("\n".join(md_lines), encoding="utf-8")


def _require_geo_deps() -> None:
    if gpd is None or box is None:
        raise RuntimeError(
            "Missing geospatial dependencies. "
            "Install geopandas/shapely and retry."
        )


def _bbox_polygon_from_cfg(cfg: dict[str, Any]):
    _require_geo_deps()
    bbox = dict(cfg.get("wind_bbox") or {})
    return box(
        float(bbox["lon_min"]),
        float(bbox["lat_min"]),
        float(bbox["lon_max"]),
        float(bbox["lat_max"]),
    )


def _clip_to_bbox(gdf: gpd.GeoDataFrame, bbox_polygon) -> gpd.GeoDataFrame:
    gdf_wgs = gdf.copy()
    if gdf_wgs.crs is None:
        gdf_wgs = gdf_wgs.set_crs(WGS84)
    gdf_wgs = gdf_wgs.to_crs(WGS84)
    gdf_wgs["geometry"] = gdf_wgs.geometry.intersection(bbox_polygon)
    return gdf_wgs[~gdf_wgs.geometry.is_empty & gdf_wgs.geometry.notna()].copy()


def _as_wgs84_and_metric(gdf: gpd.GeoDataFrame) -> tuple:
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    gdf_wgs = gdf.to_crs(WGS84)
    gdf_metric = gdf.to_crs(METRIC_CRS)
    return gdf_wgs, gdf_metric


def _line_features(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    asset_type: str,
    exposure_category: str,
    eur_per_km: float,
) -> list[NormalizedFeature]:
    gdf_wgs, gdf_metric = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, (geom_wgs, geom_metric) in enumerate(zip(gdf_wgs.geometry, gdf_metric.geometry)):
        if geom_wgs is None or geom_metric is None or geom_wgs.is_empty or geom_metric.is_empty:
            continue
        centroid = geom_wgs.centroid
        if centroid is None or centroid.is_empty:
            continue
        length_km = max(0.0, float(geom_metric.length) / 1000.0)
        value_eur = max(5_000.0, length_km * eur_per_km)
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"{asset_type} {idx + 1}",
                value_eur=float(value_eur),
                geometry_type=str(geom_wgs.geom_type),
                exposure_category=exposure_category,
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_fixed_value(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    asset_type: str,
    exposure_category: str,
    fixed_value_eur: float,
) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, geom in enumerate(gdf_wgs.geometry):
        if geom is None or geom.is_empty:
            continue
        centroid = geom.centroid
        if centroid is None or centroid.is_empty:
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"{asset_type} {idx + 1}",
                value_eur=float(fixed_value_eur),
                geometry_type=str(geom.geom_type),
                exposure_category=exposure_category,
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_aep_ouvrages_from_field(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    field_name: str = "ovrg_type",
) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, row in enumerate(gdf_wgs.itertuples(index=False)):
        geom = getattr(row, "geometry", None)
        if geom is None or geom.is_empty:
            continue
        ovrg_type = str(getattr(row, field_name, "") or "").strip().upper()
        asset_type = f"eau_aep_ouvrage_{ovrg_type or 'NA'}"
        centroid = geom.centroid
        if centroid is None or centroid.is_empty:
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"AEP ouvrage {ovrg_type or 'NA'} {idx + 1}",
                value_eur=get_aep_ouvrage_value(ovrg_type),
                geometry_type=str(geom.geom_type),
                exposure_category="ouvrage_eau",
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=None,
                properties={"asset_type": asset_type},
            )
        )
    return out


def _point_features_aep_ouvrages_fixed_type(
    gdf: gpd.GeoDataFrame,
    *,
    feature_prefix: str,
    ovrg_type: str,
) -> list[NormalizedFeature]:
    code = str(ovrg_type or "").strip().upper() or "NA"
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    for idx, geom in enumerate(gdf_wgs.geometry):
        if geom is None or geom.is_empty:
            continue
        centroid = geom.centroid
        if centroid is None or centroid.is_empty:
            continue
        out.append(
            NormalizedFeature(
                feature_id=f"{feature_prefix}-{idx + 1}",
                label=f"AEP ouvrage {code} {idx + 1}",
                value_eur=get_aep_ouvrage_value(code),
                geometry_type=str(geom.geom_type),
                exposure_category="ouvrage_eau",
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=None,
                properties={"asset_type": f"eau_aep_ouvrage_{code}"},
            )
        )
    return out


def build_complete_exposure(
    *,
    infra_elec_dir: Path | None = None,
    infra_eau_dir: Path | None = None,
    territory: str = "guadeloupe",
) -> tuple[NormalizedExposure, int]:
    """Build exposure from all infrastructure files. Returns (exposure, asset_count)."""
    _require_geo_deps()
    territory_key = normalize_territory(territory)
    cfg = get_case_study(
        territory_key,
        infra_elec_dir=infra_elec_dir,
        infra_eau_dir=infra_eau_dir,
    )
    valuation_meta = build_valuation_metadata(territory_key)
    water_values = get_water_values(territory_key)
    elec_values = get_elec_values()
    features: list[NormalizedFeature] = []
    bbox_polygon = _bbox_polygon_from_cfg(cfg)

    # Load electricity lines
    for src in cfg["elec_line_sources"]:
        eur_per_km = float(elec_values[str(src["asset_type"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            try:
                gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
                if gdf.empty:
                    continue
                features.extend(
                    _line_features(
                        gdf,
                        feature_prefix=f"{src['prefix']}-{p_idx}",
                        asset_type=str(src["asset_type"]),
                        exposure_category="ouvrage_electrique",
                        eur_per_km=eur_per_km,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

    # Load water lines
    for src in cfg["water_line_sources"]:
        eur_per_km = float(water_values[str(src["value_key"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            try:
                gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
                if gdf.empty:
                    continue
                features.extend(
                    _line_features(
                        gdf,
                        feature_prefix=f"{src['prefix']}-{p_idx}",
                        asset_type=str(src["asset_type"]),
                        exposure_category="ouvrage_eau",
                        eur_per_km=eur_per_km,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

    # Load water AEP ouvrages
    for src in cfg["aep_ouvrage_sources"]:
        mode = str(src.get("mode", "")).strip().lower()
        for p_idx, path in enumerate(src["paths"], start=1):
            try:
                gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
                if gdf.empty:
                    continue
                if mode == "fixed_type":
                    features.extend(
                        _point_features_aep_ouvrages_fixed_type(
                            gdf,
                            feature_prefix=f"{src['prefix']}-{p_idx}",
                            ovrg_type=str(src.get("ovrg_type", "NA")),
                        )
                    )
                else:
                    features.extend(
                        _point_features_aep_ouvrages_from_field(
                            gdf,
                            feature_prefix=f"{src['prefix']}-{p_idx}",
                            field_name=str(src.get("field_name", "ovrg_type")),
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

    # Load water point sources (fixed value)
    for src in cfg["water_point_fixed_sources"]:
        fixed_value_eur = float(water_values[str(src["value_key"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            try:
                gdf = _clip_to_bbox(gpd.read_file(path), bbox_polygon)
                if gdf.empty:
                    continue
                features.extend(
                    _point_features_fixed_value(
                        gdf,
                        feature_prefix=f"{src['prefix']}-{p_idx}",
                        asset_type=str(src["asset_type"]),
                        exposure_category="ouvrage_eau",
                        fixed_value_eur=fixed_value_eur,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

    warnings = [
        "Water valuation based on OFB cost comparator (territory mean).",
        f"Valuation source: {SOURCE_LABEL}.",
        f"Territory: {territory_key}.",
        "All water assets conservatively assumed dependent on electricity.",
    ]

    exposure = NormalizedExposure(
        source_name=f"{territory_key}_complete_infra_reference",
        source_format="mixed_geojson_gpkg_shp",
        input_mode="reference_dataset",
        features=features,
        warnings=warnings,
    )
    
    return exposure, len(features)


def run_territory_analysis(
    territory: str,
    dynamic_max_tracks: int,
    run_logger: RunLogger,
) -> dict[str, Any] | None:
    """Run complete analysis for a single territory. Returns result dict or None on error."""
    territory_key = normalize_territory(territory)
    logger.info(f"Starting analysis for {territory_key.upper()}...")
    
    try:
        # Load exposure
        logger.info(f"Loading exposure data...")
        start_time = time.time()
        exposure, asset_count = build_complete_exposure(territory=territory_key)
        load_time = time.time() - start_time
        logger.info(f"✓ Loaded {asset_count} assets in {load_time:.1f}s")
        
        run_logger.log_event(
            "load_exposure",
            territory=territory_key,
            asset_count=asset_count,
            duration_seconds=int(load_time),
            status="complete"
        )
        
        # Disaggregate
        logger.info(f"Computing disaggregation...")
        disagg = summarize_disaggregation(exposure, spacing_m=100.0)
        logger.info(f"✓ Disaggregation complete - {disagg.asset_count_points} sample points")
        
        # Compute impacts
        logger.info(f"Computing impacts (dynamic_max_tracks={dynamic_max_tracks})...")
        impact_start = time.time()
        
        # Create custom settings with dynamic_max_tracks
        settings = load_settings()
        # Create a modified settings object - need to handle the frozen dataclass
        import dataclasses
        settings_dict = dataclasses.asdict(settings)
        settings_dict['hazard_dynamic_max_tracks'] = dynamic_max_tracks
        settings = Settings(**settings_dict)
        
        comp = compute_impacts(exposure, disagg, settings=settings)
        impact_time = time.time() - impact_start
        
        eai_storm = comp.portfolio_results["storm"]["eai_eur"]
        eai_cmcc = comp.portfolio_results["storm_cmcc"]["eai_eur"]
        
        logger.info(f"✓ Impact computation complete in {impact_time:.1f}s")
        logger.info(f"  EAI STORM: {eai_storm:,.0f} EUR")
        logger.info(f"  EAI STORM_CMCC: {eai_cmcc:,.0f} EUR")
        
        run_logger.log_event(
            "impacts",
            territory=territory_key,
            eai_eur=eai_storm,
            eai_cmcc_eur=eai_cmcc,
            duration_seconds=int(impact_time),
            status="complete"
        )
        
        # Export results
        logger.info(f"Exporting results...")
        source_key = f"{territory_key}_complete_reference"
        payload = build_result_payload(
            job_id=source_key,
            source=source_key,
            run_label=None,
            exposure=exposure,
            disagg=disagg,
            comp=comp,
        )
        payload["meta"]["title"] = f"{territory_label(territory_key)} Complete Water+Electric Cyclone Risk"
        payload["meta"]["valuation_source"] = SOURCE_LABEL
        payload["meta"]["valuation_version"] = VALUATION_VERSION
        payload["meta"]["case_study_territory"] = territory_key
        payload["exposure_summary"]["asset_type_counts"] = dict(
            Counter(str((feat.properties or {}).get("asset_type") or "unknown") for feat in exposure.features)
        )
        
        out_path = WEB_DATA_DIR / f"{territory_key}-complete-analysis.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        
        logger.info(f"✓ Results exported to {out_path.name}")
        
        run_logger.log_event(
            "export",
            territory=territory_key,
            output_file=str(out_path),
            status="complete"
        )
        
        return {
            "territory": territory_key,
            "assets": asset_count,
            "eai": eai_storm,
            "complete_analysis_path": str(out_path),
        }
        
    except Exception as e:
        logger.error(f"✗ Failed to analyze {territory_key}: {e}", exc_info=True)
        run_logger.log_event(
            "error",
            territory=territory_key,
            error=str(e),
            status="failed"
        )
        return None


def deploy_results(vhost: str = "sib.dev.elio.bottagisio.com") -> bool:
    """Deploy results to web server."""
    logger.info(f"Deploying to {vhost}...")
    try:
        deploy_script = SCRIPTS_ROOT / "deploy_shared_web.sh"
        if not deploy_script.exists():
            logger.warning(f"Deploy script not found: {deploy_script}")
            return False

        destination = "/var/www/sib.shared.elio.dev/" if vhost == "sib.dev.elio.bottagisio.com" else f"/var/www/{vhost}/"
        
        result = subprocess.run(
            [str(deploy_script), str(REPO_ROOT / "web"), destination],
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        if result.returncode == 0:
            logger.info(f"✓ Deployment successful")
            # Verify
            import urllib.request
            url = f"https://{vhost}/data/guadeloupe-complete-analysis.json"
            try:
                with urllib.request.urlopen(url, context=__import__('ssl').create_default_context(__import__('ssl').CERT_NONE)) as response:
                    if response.status == 200:
                        logger.info(f"✓ Verified deployment at {vhost}")
            except Exception as e:
                logger.warning(f"Could not verify deployment: {e}")
            return True
        else:
            logger.error(f"✗ Deployment failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"✗ Deployment error: {e}", exc_info=True)
        return False


def rebuild_case_study_frontend_artifacts(territories: list[str], dynamic_max_tracks: int) -> None:
    script_path = SCRIPTS_ROOT / "rerun_case_studies_light.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing frontend build script: {script_path}")

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--territories",
            *territories,
            "--map-dynamic-max-tracks",
            str(dynamic_max_tracks),
        ],
        timeout=5400,
    )
    if result.returncode != 0:
        joined = ", ".join(territories) if territories else "unknown"
        raise RuntimeError(f"rerun_case_studies_light.py failed for {joined} with exit code {result.returncode}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run complete SIB analysis pipeline for Guadeloupe & Martinique"
    )
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=1200,
        help="Number of dynamic hazard tracks (default: 1200)"
    )
    parser.add_argument(
        "--territories",
        choices=["gua", "mar", "both"],
        default="both",
        help="Which territories to analyze (default: both)"
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Skip deployment step"
    )
    
    args = parser.parse_args()
    
    # Determine territories
    if args.territories == "gua":
        territories = ["guadeloupe"]
    elif args.territories == "mar":
        territories = ["martinique"]
    else:
        territories = ["guadeloupe", "martinique"]
    
    logger.info("=" * 60)
    logger.info(f"SIB Complete Analysis Runner")
    logger.info(f"Parameters: dynamic_max_tracks={args.dynamic_max_tracks}, territories={territories}")
    logger.info("=" * 60)
    
    run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL)
    run_logger.log_event(
        "start",
        status="initiated",
        dynamic_max_tracks=args.dynamic_max_tracks,
        territories=territories
    )
    
    results = {}
    for territory in territories:
        result = run_territory_analysis(territory, args.dynamic_max_tracks, run_logger)
        if result:
            results[territory] = result

    frontend_artifacts_success = False
    if results:
        completed_territories = list(results.keys())
        logger.info("Rebuilding case-study frontend artefacts...")
        artefact_start = time.time()
        gc.collect()
        try:
            rebuild_case_study_frontend_artifacts(completed_territories, args.dynamic_max_tracks)
            frontend_artifacts_success = True
            artefact_time = time.time() - artefact_start
            logger.info(f"✓ Frontend artefacts rebuilt in {artefact_time:.1f}s")
            run_logger.log_event(
                "frontend_artifacts",
                territories=completed_territories,
                duration_seconds=int(artefact_time),
                status="complete"
            )
        except Exception as exc:
            logger.error(f"✗ Frontend artefact rebuild failed: {exc}", exc_info=True)
            run_logger.log_event(
                "frontend_artifacts",
                territories=completed_territories,
                error=str(exc),
                status="failed"
            )
    
    # Deploy if requested and successful
    deploy_success = False
    if not args.no_deploy and results and frontend_artifacts_success:
        deploy_success = deploy_results()
        run_logger.log_event("deploy", status="complete" if deploy_success else "failed")
    
    # Finalize logging
    run_logger.finalize(
        status="success" if results else "failed",
        territories_completed=len(results),
        total_assets=sum(r.get("assets", 0) for r in results.values()),
        deployed=deploy_success,
    )
    
    logger.info("=" * 60)
    logger.info(f"Run complete. Logs written to:")
    logger.info(f"  {JOURNAL_MD}")
    logger.info(f"  {JOURNAL_JSONL}")
    logger.info("=" * 60)
    
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
