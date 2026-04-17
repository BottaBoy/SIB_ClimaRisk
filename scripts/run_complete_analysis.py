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

import atexit
import argparse
import dataclasses
from datetime import datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import signal
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
from run_web_artifacts import (
    copy_territory_web_relative_paths,
    territory_complete_analysis_relative_path,
    territory_frontend_rebuild_relative_paths,
    territory_optional_snapshot_relative_paths,
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
# Keep complete-analysis execution logs isolated from case-study journals.
JOURNAL_MD = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.md"
JOURNAL_JSONL = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.jsonl"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"

COMPONENT_INFO_LABELS = {
    "wind": "vent",
    "rain": "pluie",
    "surge": "inondations cotieres",
    "landslide": "mouvement de terrain",
}

HAZARD_INFO_LABELS = {
    "storm": "STORM",
    "storm_cmcc": "STORM_CMCC",
}


def _component_info_label(component: str | None) -> str:
    key = str(component or "unknown").strip().lower()
    return COMPONENT_INFO_LABELS.get(key, key or "unknown")


def _hazard_info_label(hazard: str | None) -> str:
    key = str(hazard or "unknown").strip().lower()
    return HAZARD_INFO_LABELS.get(key, key.upper() or "UNKNOWN")


def _resolve_resume_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("resume_run_id must not be empty")
    if value.lower() != "latest":
        return value
    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    if not latest_manifest.exists():
        raise FileNotFoundError(f"Latest run manifest not found: {latest_manifest}")
    payload = json.loads(latest_manifest.read_text(encoding="utf-8"))
    run_id = str((payload or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest run manifest does not contain a run_id: {latest_manifest}")
    return run_id


class RunLogger:
    """Manages dual-format logging (markdown + JSONL)."""

    def __init__(self, markdown_path: Path, jsonl_path: Path, run_id: str | None = None):
        self.markdown_path = Path(markdown_path)
        self.jsonl_path = Path(jsonl_path)
        self.run_id = str(run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
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

        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def finalize(self, status: str = "success", **summary) -> None:
        """Finalize run and write markdown summary."""
        duration = time.time() - self.start_time
        self.log_event("complete", status=status, duration_seconds=int(duration), **summary)
        
        # Build markdown
        md_lines = [
            "# Journalisation Runs Complete Analysis",
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
                "# Journalisation Runs Complete Analysis",
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


class RunManifest:
    """Persist operator-facing run state for long complete-analysis executions."""

    def __init__(
        self,
        root_dir: Path,
        run_id: str,
        parameters: dict[str, Any],
        *,
        existing_data: dict[str, Any] | None = None,
    ):
        self.root_dir = Path(root_dir)
        self.run_id = str(run_id)
        self.run_dir = self.root_dir / self.run_id
        self.manifest_path = self.run_dir / "manifest.json"
        self.latest_path = self.root_dir / "latest-manifest.json"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if existing_data is None:
            self.data: dict[str, Any] = {
                "run_id": self.run_id,
                "status": "running",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "parameters": dict(parameters),
                "manifest_path": str(self.manifest_path),
                "territories": {},
                "latest_event": None,
            }
        else:
            self.data = dict(existing_data)
            self.data["run_id"] = self.run_id
            self.data["manifest_path"] = str(self.manifest_path)
            existing_params = self.data.get("parameters") if isinstance(self.data.get("parameters"), dict) else {}
            merged_params = dict(existing_params)
            merged_params.update(parameters)
            self.data["parameters"] = merged_params
        self._write()

    @classmethod
    def open_existing(cls, root_dir: Path, run_id: str, parameters: dict[str, Any]) -> "RunManifest":
        manifest_path = Path(root_dir) / str(run_id) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found for run_id={run_id}: {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid run manifest payload at {manifest_path}")
        return cls(root_dir, run_id, parameters, existing_data=payload)

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _territory_entry(self, territory: str) -> dict[str, Any]:
        entry = self.data.setdefault("territories", {}).setdefault(
            territory,
            {
                "status": "pending",
                "updated_at": self._timestamp(),
                "phases": {},
                "impacts": {"hazards": {}},
            },
        )
        return entry

    def _write(self) -> None:
        self.data["updated_at"] = self._timestamp()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        self.manifest_path.write_text(payload, encoding="utf-8")
        self.latest_path.write_text(payload, encoding="utf-8")

    def set_status(self, status: str, **kwargs) -> None:
        self.data["status"] = str(status)
        self.data.update(kwargs)
        self._write()

    def checkpoint_dir_for_territory(self, territory: str) -> Path:
        path = self.run_dir / "territories" / str(territory) / "checkpoints"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_territory_status(self, territory: str) -> str | None:
        territories = self.data.get("territories") if isinstance(self.data.get("territories"), dict) else {}
        entry = territories.get(str(territory)) if isinstance(territories, dict) else None
        if not isinstance(entry, dict):
            return None
        raw = entry.get("status")
        return str(raw) if raw is not None else None

    def completed_territory_result(self, territory: str) -> dict[str, Any] | None:
        territories = self.data.get("territories") if isinstance(self.data.get("territories"), dict) else {}
        entry = territories.get(str(territory)) if isinstance(territories, dict) else None
        if not isinstance(entry, dict):
            return None
        if str(entry.get("status") or "") != "complete":
            return None
        phases = entry.get("phases") if isinstance(entry.get("phases"), dict) else {}
        export_phase = phases.get("export") if isinstance(phases, dict) else {}
        impacts_phase = phases.get("impacts") if isinstance(phases, dict) else {}
        load_phase = phases.get("load_exposure") if isinstance(phases, dict) else {}
        output_file = str(
            entry.get("archived_complete_analysis_path")
            or entry.get("complete_analysis_path")
            or export_phase.get("archived_output_file")
            or export_phase.get("output_file")
            or ""
        )
        if not output_file or not Path(output_file).exists():
            return None
        return {
            "territory": str(territory),
            "assets": int(load_phase.get("asset_count") or 0),
            "eai": float(impacts_phase.get("eai_eur") or 0.0),
            "complete_analysis_path": output_file,
        }

    def set_territory_status(self, territory: str, status: str, **kwargs) -> None:
        entry = self._territory_entry(territory)
        entry["status"] = str(status)
        entry["updated_at"] = self._timestamp()
        entry.update(kwargs)
        self._write()

    def set_phase(self, territory: str, phase: str, status: str, **kwargs) -> None:
        entry = self._territory_entry(territory)
        entry["updated_at"] = self._timestamp()
        phase_entry = {
            "status": str(status),
            "updated_at": self._timestamp(),
            **kwargs,
        }
        entry.setdefault("phases", {})[phase] = phase_entry
        self._write()

    def record_climada_event(self, territory: str, payload: dict[str, Any]) -> None:
        entry = self._territory_entry(territory)
        impacts = entry.setdefault("impacts", {}).setdefault("hazards", {})
        hazard_key = str(payload.get("hazard") or "unknown")
        component_name = str(payload.get("component") or "unknown")
        hazard_entry = impacts.setdefault(hazard_key, {"components": {}})
        component_entry = hazard_entry.setdefault("components", {}).setdefault(
            component_name,
            {"status": "pending", "updated_at": self._timestamp(), "shards": {}},
        )

        event_name = str(payload.get("event") or "")
        component_entry["updated_at"] = self._timestamp()
        if event_name == "component_plan":
            component_entry.update(
                {
                    "status": "running",
                    "total_points": int(payload.get("total_points") or 0),
                    "event_count": int(payload.get("event_count") or 0),
                    "memory_budget_gb": payload.get("memory_budget_gb"),
                    "estimated_full_memory_gb": payload.get("estimated_full_memory_gb"),
                    "max_points_per_shard": int(payload.get("max_points_per_shard") or 0),
                    "planned_shards": int(payload.get("planned_shards") or 0),
                    "completed_shards": int(payload.get("completed_shards") or 0),
                    "retry_splits": int(payload.get("retry_splits") or 0),
                    "resumed_shards": int(payload.get("resumed_shards") or 0),
                    "sharded": bool(payload.get("sharded")),
                }
            )
        elif event_name in {"shard_start", "shard_complete", "shard_split_retry"}:
            shard_id = str(payload.get("shard_id") or "unknown")
            shard_entry = component_entry.setdefault("shards", {}).setdefault(shard_id, {})
            shard_entry.update(
                {
                    "status": "running" if event_name == "shard_start" else ("retrying" if event_name == "shard_split_retry" else "complete"),
                    "updated_at": self._timestamp(),
                    "retry_depth": int(payload.get("retry_depth") or 0),
                    "point_count": int(payload.get("point_count") or 0),
                    "territory_id": payload.get("territory_id"),
                    "infra_class": payload.get("infra_class"),
                }
            )
            if payload.get("error"):
                shard_entry["error"] = str(payload.get("error"))
            component_entry["status"] = "retrying" if event_name == "shard_split_retry" else "running"
            component_entry["completed_shards"] = int(payload.get("completed_shards") or component_entry.get("completed_shards") or 0)
            component_entry["planned_shards"] = int(payload.get("planned_shards") or component_entry.get("planned_shards") or 0)
            if payload.get("resumed"):
                component_entry["resumed_shards"] = int(component_entry.get("resumed_shards") or 0) + 1
            if event_name == "shard_split_retry":
                component_entry["retry_splits"] = int(component_entry.get("retry_splits") or 0) + 1
                component_entry["last_error"] = str(payload.get("error") or "")
        elif event_name == "component_complete":
            component_entry.update(
                {
                    "status": "complete",
                    "completed_shards": int(payload.get("completed_shards") or 0),
                    "planned_shards": int(payload.get("planned_shards") or 0),
                    "retry_splits": int(payload.get("retry_splits") or 0),
                    "resumed_shards": int(payload.get("resumed_shards") or component_entry.get("resumed_shards") or 0),
                }
            )
        elif event_name == "component_failed":
            component_entry["status"] = "failed"
            component_entry["last_error"] = str(payload.get("error") or "")

        self.data["latest_event"] = {
            "timestamp": self._timestamp(),
            "territory": territory,
            **payload,
        }
        self._write()


class RunTerminationGuard:
    """Marks a run as aborted if the process exits before normal finalization."""

    def __init__(self, run_logger: RunLogger, run_manifest: RunManifest):
        self._run_logger = run_logger
        self._run_manifest = run_manifest
        self._active = True
        self._previous_handlers: dict[int, Any] = {}
        atexit.register(self._on_exit)
        signal_numbers = [signal.SIGINT, signal.SIGTERM]
        sighup = getattr(signal, "SIGHUP", None)
        if sighup is not None:
            signal_numbers.append(sighup)
        for signum in signal_numbers:
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._on_signal)

    def mark_complete(self) -> None:
        self._active = False

    def _mark_aborted(self, *, reason: str, signum: int | None = None) -> None:
        if not self._active:
            return
        self._active = False
        finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload: dict[str, Any] = {
            "status": "failed",
            "reason": reason,
            "finished_at": finished_at,
        }
        if signum is not None:
            payload["signal"] = int(signum)
        try:
            self._run_logger.log_event("aborted", **payload)
        except Exception:
            pass
        try:
            current_status = str(self._run_manifest.data.get("status") or "")
            if current_status == "running":
                self._run_manifest.set_status("aborted", **payload)
        except Exception:
            pass

    def _on_signal(self, signum: int, _frame: Any) -> None:
        logger.error("Run interrupted by signal %s; marking manifest as aborted", signum)
        self._mark_aborted(reason="signal_interrupt", signum=signum)
        previous = self._previous_handlers.get(signum, signal.SIG_DFL)
        signal.signal(signum, previous)
        os.kill(os.getpid(), signum)

    def _on_exit(self) -> None:
        if not self._active:
            return
        try:
            current_status = str(self._run_manifest.data.get("status") or "")
        except Exception:
            current_status = ""
        if current_status == "running":
            logger.error("Process exited before run finalization; marking manifest as aborted")
            self._mark_aborted(reason="process_exit_before_finalization")


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
    geometry = gdf_wgs.geometry
    return gdf_wgs[(~geometry.is_empty) & (~geometry.isna())].copy()


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
    run_manifest: RunManifest,
    *,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
    allow_degraded_components: bool,
    resume_enabled: bool,
) -> dict[str, Any] | None:
    """Run complete analysis for a single territory. Returns result dict or None on error."""
    territory_key = normalize_territory(territory)
    logger.info(f"Starting analysis for {territory_key.upper()}...")
    run_manifest.set_territory_status(territory_key, "running")
    current_phase = "load_exposure"
    
    try:
        # Load exposure
        logger.info(f"Loading exposure data...")
        run_manifest.set_phase(territory_key, "load_exposure", "running")
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
        run_manifest.set_phase(
            territory_key,
            "load_exposure",
            "complete",
            asset_count=asset_count,
            duration_seconds=int(load_time),
        )
        
        # Disaggregate
        logger.info(f"Computing disaggregation...")
        current_phase = "disaggregation"
        run_manifest.set_phase(territory_key, "disaggregation", "running")
        disagg = summarize_disaggregation(exposure, spacing_m=100.0)
        logger.info(f"✓ Disaggregation complete - {disagg.asset_count_points} sample points")
        run_logger.log_event(
            "disaggregation",
            territory=territory_key,
            point_count=int(disagg.asset_count_points),
            spacing_m=float(disagg.spacing_m),
            status="complete",
        )
        run_manifest.set_phase(
            territory_key,
            "disaggregation",
            "complete",
            point_count=int(disagg.asset_count_points),
            spacing_m=float(disagg.spacing_m),
        )
        
        # Compute impacts
        logger.info(f"Computing impacts (dynamic_max_tracks={dynamic_max_tracks})...")
        current_phase = "impacts"
        run_manifest.set_phase(
            territory_key,
            "impacts",
            "running",
            dynamic_max_tracks=int(dynamic_max_tracks),
            memory_budget_gb=float(memory_budget_gb),
            max_points_per_shard=int(max_points_per_shard),
            min_points_per_shard=int(min_points_per_shard),
            strict_components=not bool(allow_degraded_components),
        )
        impact_start = time.time()
        
        # Create custom settings with dynamic_max_tracks
        settings = load_settings()
        settings_dict = dataclasses.asdict(settings)
        settings_dict['hazard_dynamic_max_tracks'] = dynamic_max_tracks
        settings_dict['climada_execution_profile'] = 'complete-analysis'
        settings_dict['climada_memory_budget_gb'] = max(0.0, float(memory_budget_gb))
        settings_dict['climada_max_points_per_shard'] = max(0, int(max_points_per_shard))
        settings_dict['climada_min_points_per_shard'] = max(1, int(min_points_per_shard))
        settings_dict['climada_strict_required_components'] = not bool(allow_degraded_components)
        settings = Settings(**settings_dict)
        checkpoint_dir = run_manifest.checkpoint_dir_for_territory(territory_key)
        seen_component_transitions: set[tuple[str, str]] = set()

        def _on_climada_progress(payload: dict[str, Any]) -> None:
            event_name = str(payload.get("event") or "")
            hazard_key = str(payload.get("hazard") or "")
            component_name = str(payload.get("component") or "")
            if event_name == "component_plan":
                transition_key = (hazard_key, component_name)
                if transition_key not in seen_component_transitions:
                    seen_component_transitions.add(transition_key)
                    logger.info(
                        "Impact transition: territory=%s hazard=%s component=%s",
                        territory_key.upper(),
                        _hazard_info_label(hazard_key),
                        _component_info_label(component_name),
                    )
            run_manifest.record_climada_event(territory_key, payload)
            run_logger.log_event("impact_component", territory=territory_key, **payload)
        
        comp = compute_impacts(
            exposure,
            disagg,
            settings=settings,
            progress_callback=_on_climada_progress,
            checkpoint_dir=checkpoint_dir,
            resume_enabled=resume_enabled,
        )
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
        run_manifest.set_phase(
            territory_key,
            "impacts",
            "complete",
            eai_eur=eai_storm,
            eai_cmcc_eur=eai_cmcc,
            duration_seconds=int(impact_time),
            modeling=comp.modeling,
        )
        
        # Export results
        logger.info(f"Exporting results...")
        current_phase = "export"
        run_manifest.set_phase(territory_key, "export", "running")
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
        archived_complete_analysis, _, _ = copy_territory_web_relative_paths(
            run_manifest.run_id,
            territory_key,
            [territory_complete_analysis_relative_path(territory_key)],
        )
        archived_complete_analysis_path = archived_complete_analysis.get(
            territory_complete_analysis_relative_path(territory_key)
        )
        
        logger.info(f"✓ Results exported to {out_path.name}")
        
        run_logger.log_event(
            "export",
            territory=territory_key,
            output_file=str(out_path),
            status="complete"
        )
        run_manifest.set_phase(
            territory_key,
            "export",
            "complete",
            output_file=str(out_path),
            archived_output_file=archived_complete_analysis_path,
        )
        run_manifest.set_territory_status(
            territory_key,
            "complete",
            complete_analysis_path=str(out_path),
            archived_complete_analysis_path=archived_complete_analysis_path,
        )
        
        return {
            "territory": territory_key,
            "assets": asset_count,
            "eai": eai_storm,
            "complete_analysis_path": str(out_path),
            "archived_complete_analysis_path": archived_complete_analysis_path,
        }
        
    except Exception as e:
        logger.error(f"✗ Failed to analyze {territory_key}: {e}", exc_info=True)
        run_manifest.set_phase(
            territory_key,
            current_phase,
            "failed",
            error=str(e),
        )
        run_manifest.set_territory_status(territory_key, "failed", error=str(e))
        run_logger.log_event(
            "error",
            territory=territory_key,
            error=str(e),
            status="failed"
        )
        return None


DEPLOY_VERIFY_RELATIVE_PATHS = (
    "index.html",
    "assets/app.js",
    "data/guadeloupe-complete-analysis.json",
    "data/martinique-complete-analysis.json",
    "data/guadeloupe-wind-maps.json",
    "data/martinique-wind-maps.json",
    "data/guadeloupe-landslide-maps.json",
    "data/martinique-landslide-maps.json",
    "data/guadeloupe-multi-hazard-proxy.json",
    "data/martinique-multi-hazard-proxy.json",
    "data/guadeloupe-page1-analysis.json",
    "data/martinique-page2-analysis.json",
    "data/guadeloupe-network-states.geojson",
    "data/martinique-network-states.geojson",
)

FRONTEND_PROXY_MAX_POINTS_TOTAL = 600
FRONTEND_PROXY_MAX_POINTS_PER_FEATURE = 6
FRONTEND_PROXY_DYNAMIC_MAX_TRACKS = 100
FRONTEND_PAGE_COMPONENT_LIGHT_SPACING_M = 1000.0
FRONTEND_PAGE_COMPONENT_LIGHT_MAX_POINTS_TOTAL = 400
FRONTEND_PAGE_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE = 4
FRONTEND_PAGE_COMPONENT_LIGHT_DYNAMIC_MAX_TRACKS = 50
FRONTEND_MAP_DYNAMIC_MAX_TRACKS_CAP = 300


def _resolve_vhost_destination(vhost: str) -> str:
    normalized = str(vhost or "").strip()
    if normalized == "sib.dev.elio.bottagisio.com":
        return "/var/www/sib.shared.elio.dev/"
    return f"/var/www/{normalized}/"


def _verify_deployed_web_root(destination: str) -> tuple[bool, list[str]]:
    destination_root = Path(str(destination).rstrip("/"))
    source_root = REPO_ROOT / "web"
    issues: list[str] = []
    for relative_path in DEPLOY_VERIFY_RELATIVE_PATHS:
        source_path = source_root / relative_path
        if not source_path.exists():
            continue
        deployed_path = destination_root / relative_path
        if not deployed_path.exists():
            issues.append(f"missing {deployed_path}")
            continue
        source_stat = source_path.stat()
        deployed_stat = deployed_path.stat()
        if source_stat.st_size != deployed_stat.st_size or source_stat.st_mtime_ns != deployed_stat.st_mtime_ns:
            issues.append(f"out-of-sync {relative_path}")
    return not issues, issues


def deploy_results(vhost: str = "sib.dev.elio.bottagisio.com") -> bool:
    """Deploy results to web server."""
    logger.info(f"Deploying to {vhost}...")
    try:
        deploy_script = SCRIPTS_ROOT / "deploy_shared_web.sh"
        if not deploy_script.exists():
            logger.warning(f"Deploy script not found: {deploy_script}")
            return False

        destination = _resolve_vhost_destination(vhost)
        
        result = subprocess.run(
            [str(deploy_script), str(REPO_ROOT / "web"), destination],
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        if result.returncode == 0:
            logger.info(f"✓ Deployment successful")
            verified, issues = _verify_deployed_web_root(destination)
            if not verified:
                for issue in issues:
                    logger.error(f"✗ Deployment verification failed: {issue}")
                return False
            logger.info(f"✓ Verified deployment in {destination}")
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

    frontend_map_dynamic_max_tracks = min(
        int(dynamic_max_tracks),
        int(FRONTEND_MAP_DYNAMIC_MAX_TRACKS_CAP),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--territories",
            *territories,
            "--proxy-max-points-total",
            str(FRONTEND_PROXY_MAX_POINTS_TOTAL),
            "--proxy-max-points-per-feature",
            str(FRONTEND_PROXY_MAX_POINTS_PER_FEATURE),
            "--proxy-dynamic-max-tracks",
            str(FRONTEND_PROXY_DYNAMIC_MAX_TRACKS),
            "--prefer-complete-analysis-proxy-fallback",
            "--prefer-complete-analysis-page-fallback",
            "--page-component-light-spacing-m",
            str(FRONTEND_PAGE_COMPONENT_LIGHT_SPACING_M),
            "--page-component-light-max-points-total",
            str(FRONTEND_PAGE_COMPONENT_LIGHT_MAX_POINTS_TOTAL),
            "--page-component-light-max-points-per-feature",
            str(FRONTEND_PAGE_COMPONENT_LIGHT_MAX_POINTS_PER_FEATURE),
            "--page-component-light-dynamic-max-tracks",
            str(FRONTEND_PAGE_COMPONENT_LIGHT_DYNAMIC_MAX_TRACKS),
            "--map-dynamic-max-tracks",
            str(frontend_map_dynamic_max_tracks),
        ],
        timeout=5400,
    )
    if result.returncode != 0:
        joined = ", ".join(territories) if territories else "unknown"
        if result.returncode == 2:
            raise RuntimeError(
                f"rerun_case_studies_light.py detected reused or incoherent frontend artefacts for {joined}; deployment aborted"
            )
        raise RuntimeError(f"rerun_case_studies_light.py failed for {joined} with exit code {result.returncode}")


def snapshot_frontend_artifacts_for_run(
    run_manifest: RunManifest,
    territories: list[str],
    *,
    min_mtime_epoch: float,
) -> dict[str, dict[str, str]]:
    archived_by_territory: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for territory in territories:
        required_archived, missing, stale = copy_territory_web_relative_paths(
            run_manifest.run_id,
            territory,
            territory_frontend_rebuild_relative_paths(territory),
            min_mtime_epoch=min_mtime_epoch,
        )
        optional_archived, _, _ = copy_territory_web_relative_paths(
            run_manifest.run_id,
            territory,
            territory_optional_snapshot_relative_paths(territory),
        )
        archived_by_territory[territory] = {
            **required_archived,
            **optional_archived,
        }
        if missing:
            problems.append(f"{territory}: missing {', '.join(missing)}")
        if stale:
            problems.append(f"{territory}: not rewritten during rebuild {', '.join(stale)}")
    if problems:
        raise RuntimeError("frontend artefact snapshot validation failed: " + "; ".join(problems))
    for territory, archived_files in archived_by_territory.items():
        run_manifest.set_territory_status(
            territory,
            run_manifest.get_territory_status(territory) or "complete",
            archived_frontend_artifacts=archived_files,
        )
    return archived_by_territory


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
    parser.add_argument(
        "--memory-budget-gb",
        type=float,
        default=6.0,
        help="Approximate per-component memory budget used to auto-shard CLIMADA exposure points (default: 6.0)",
    )
    parser.add_argument(
        "--max-points-per-shard",
        type=int,
        default=0,
        help="Optional hard cap on CLIMADA points per shard (default: auto from memory budget)",
    )
    parser.add_argument(
        "--min-points-per-shard",
        type=int,
        default=512,
        help="Lower bound used when retry-splitting failed shards after MemoryError (default: 512)",
    )
    parser.add_argument(
        "--allow-degraded-components",
        action="store_true",
        help="Allow eligible rain/surge component failures without failing the territory run",
    )
    parser.add_argument(
        "--resume-run-id",
        type=str,
        default=None,
        help="Resume a previous sharded run from outputs/complete-analysis-runs/<run_id> (or use 'latest')",
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
    logger.info(
        "Parameters: dynamic_max_tracks=%s, territories=%s, memory_budget_gb=%.2f, max_points_per_shard=%s, min_points_per_shard=%s, strict_components=%s",
        args.dynamic_max_tracks,
        territories,
        float(args.memory_budget_gb),
        int(args.max_points_per_shard),
        int(args.min_points_per_shard),
        not bool(args.allow_degraded_components),
    )
    logger.info("=" * 60)
    
    parameters = {
        "dynamic_max_tracks": int(args.dynamic_max_tracks),
        "territories": list(territories),
        "no_deploy": bool(args.no_deploy),
        "memory_budget_gb": float(args.memory_budget_gb),
        "max_points_per_shard": int(args.max_points_per_shard),
        "min_points_per_shard": int(args.min_points_per_shard),
        "allow_degraded_components": bool(args.allow_degraded_components),
    }
    resume_enabled = bool(args.resume_run_id)
    if resume_enabled:
        resume_run_id = _resolve_resume_run_id(str(args.resume_run_id))
        run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL, run_id=resume_run_id)
        run_manifest = RunManifest.open_existing(RUN_OUTPUTS_DIR, resume_run_id, parameters)
        run_manifest.set_status(
            "running",
            resumed_at=datetime.now(timezone.utc).isoformat(),
            resume_invocation=parameters,
        )
    else:
        run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL)
        run_manifest = RunManifest(
            RUN_OUTPUTS_DIR,
            run_logger.run_id,
            parameters=parameters,
        )
    termination_guard = RunTerminationGuard(run_logger, run_manifest)
    run_logger.log_event(
        "resume" if resume_enabled else "start",
        status="initiated",
        dynamic_max_tracks=args.dynamic_max_tracks,
        territories=territories,
        manifest_path=str(run_manifest.manifest_path),
    )
    
    results = {}
    rerun_territories: list[str] = []
    for territory in territories:
        completed_result = run_manifest.completed_territory_result(territory)
        if resume_enabled and completed_result is not None:
            logger.info("Skipping %s: already complete in manifest %s", territory, run_manifest.run_id)
            run_logger.log_event(
                "resume_skip",
                territory=territory,
                status="complete",
                reason="territory_already_complete",
            )
            results[territory] = completed_result
            continue
        result = run_territory_analysis(
            territory,
            args.dynamic_max_tracks,
            run_logger,
            run_manifest,
            memory_budget_gb=float(args.memory_budget_gb),
            max_points_per_shard=int(args.max_points_per_shard),
            min_points_per_shard=int(args.min_points_per_shard),
            allow_degraded_components=bool(args.allow_degraded_components),
            resume_enabled=resume_enabled,
        )
        if result:
            results[territory] = result
            rerun_territories.append(territory)

    frontend_artifacts_success = False
    frontend_status = ((run_manifest.data.get("frontend_artifacts") or {}).get("status") if isinstance(run_manifest.data, dict) else None)
    territories_for_frontend = list(rerun_territories)
    if results and not territories_for_frontend and str(frontend_status or "") != "complete":
        territories_for_frontend = list(results.keys())

    if results and territories_for_frontend:
        logger.info("Rebuilding case-study frontend artefacts...")
        artefact_start = time.time()
        gc.collect()
        run_manifest.set_status("running", frontend_artifacts={"status": "running", "territories": territories_for_frontend})
        try:
            rebuild_case_study_frontend_artifacts(territories_for_frontend, args.dynamic_max_tracks)
            archived_frontend_artifacts = snapshot_frontend_artifacts_for_run(
                run_manifest,
                territories_for_frontend,
                min_mtime_epoch=artefact_start,
            )
            frontend_artifacts_success = True
            artefact_time = time.time() - artefact_start
            logger.info(f"✓ Frontend artefacts rebuilt in {artefact_time:.1f}s")
            run_logger.log_event(
                "frontend_artifacts",
                territories=territories_for_frontend,
                duration_seconds=int(artefact_time),
                status="complete"
            )
            run_manifest.set_status(
                "running",
                frontend_artifacts={
                    "status": "complete",
                    "territories": territories_for_frontend,
                    "duration_seconds": int(artefact_time),
                    "archived_files_by_territory": archived_frontend_artifacts,
                },
            )
        except Exception as exc:
            logger.error(f"✗ Frontend artefact rebuild failed: {exc}", exc_info=True)
            run_logger.log_event(
                "frontend_artifacts",
                territories=territories_for_frontend,
                error=str(exc),
                status="failed"
            )
            run_manifest.set_status(
                "running",
                frontend_artifacts={
                    "status": "failed",
                    "territories": territories_for_frontend,
                    "error": str(exc),
                },
            )
    elif results:
        frontend_artifacts_success = str(frontend_status or "") == "complete"
    
    # Deploy if requested and successful
    deploy_success = False
    if not args.no_deploy and results and frontend_artifacts_success:
        run_manifest.set_status("running", deploy={"status": "running"})
        deploy_success = deploy_results()
        run_logger.log_event("deploy", status="complete" if deploy_success else "failed")
        run_manifest.set_status(
            "running",
            deploy={"status": "complete" if deploy_success else "failed"},
        )
    
    # Finalize logging
    final_status = "success" if len(results) == len(territories) and frontend_artifacts_success else ("partial" if results else "failed")
    run_logger.finalize(
        status=final_status,
        territories_completed=len(results),
        total_assets=sum(r.get("assets", 0) for r in results.values()),
        deployed=deploy_success,
    )
    run_manifest.set_status(
        final_status,
        territories_completed=len(results),
        total_assets=sum(r.get("assets", 0) for r in results.values()),
        deployed=bool(deploy_success),
        frontend_artifacts_success=bool(frontend_artifacts_success),
    )
    termination_guard.mark_complete()

    finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    logger.info(
        "Run finished: run_id=%s status=%s finished_at=%s territories_completed=%s deployed=%s",
        run_manifest.run_id,
        final_status,
        finished_at,
        len(results),
        bool(deploy_success),
    )
    
    logger.info("=" * 60)
    logger.info(f"Run complete. Logs written to:")
    logger.info(f"  {JOURNAL_MD}")
    logger.info(f"  {JOURNAL_JSONL}")
    logger.info(f"  {run_manifest.manifest_path}")
    logger.info("=" * 60)
    
    return 0 if len(results) == len(territories) and frontend_artifacts_success else 1


if __name__ == "__main__":
    sys.exit(main())
