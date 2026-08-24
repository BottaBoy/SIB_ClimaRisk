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
import ctypes
import ctypes.util
import dataclasses
from datetime import datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import shutil
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
    from shapely.geometry import box, mapping
except ImportError:
    box = None
    mapping = None

# Backend imports
from app.risk_engine.analysis_export import build_result_payload
from app.config import load_settings, Settings, resolve_surge_topo_path_for_territory
from app.risk_engine.exposure_disaggregation import summarize_disaggregation
from app.risk_engine.impact_runner import compute_impacts, prepare_climada_exposure_bundle
from app.risk_engine.sensitivity_scenarios import (
    SensitivityScenario,
    apply_settings_overrides,
    resolve_scenario_from_pack,
    scenario_manifest_fields,
)
from app.risk_engine.types import DisaggregationSummary, NormalizedExposure, NormalizedFeature

# Case study specific
sys.path.insert(0, str(SCRIPTS_ROOT))
from case_study_sources import (
    EXPLICIT_TERRITORIES,
    get_case_study,
    normalize_territory,
    parse_territory_selection,
    territory_label,
    territory_page_suffix,
)
from frontend_supervision import (
    ENV_FRONTEND_SUPERVISION_JOURNAL,
    ENV_FRONTEND_SUPERVISION_RUN_ID,
    frontend_supervision_journal_path,
    launch_frontend_supervision_monitor,
    read_process_start_ticks,
    write_frontend_supervision_event,
)
from run_web_artifacts import (
    MIN_PUBLICATION_DYNAMIC_MAX_TRACKS,
    publication_policy_for_requested_tracks,
)
from valuation_ofb import (
    SOURCE_LABEL,
    VALUATION_VERSION,
    build_valuation_metadata,
    get_aep_ouvrage_value_for_territory,
    get_elec_values_for_territory,
    get_water_values,
)
from run_web_artifacts import (
    collect_archived_run_files,
    copy_territory_web_relative_paths,
    territory_complete_analysis_relative_path,
    territory_scientific_web_summary_relative_path,
    territory_frontend_rebuild_relative_paths,
    territory_optional_snapshot_relative_paths,
    validate_territory_web_snapshot,
)
from scientific_publication_contract import (
    PUBLIC_SERVICE_KEYS,
    SCIENTIFIC_SCENARIOS,
    SCIENTIFIC_WEB_CONTRACT_VERSION,
    SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
)


ENV_FRESH_FRONTEND_RESUME = "SIB_COMPLETE_ANALYSIS_FRESH_FRONTEND_RESUME"

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
    "saint-barthelemy": (
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe.h5",
        REPO_ROOT / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5",
    ),
}

HYDRAULIC_NETWORK_KIND_TO_ASSET_TYPE = {
    "AEP": "eau_aep_cana",
    "EU": "eau_eu_cana",
}

HYDRAULIC_ASSET_ROLE_TO_ASSET_TYPE = {
    "captage_aep": "eau_aep_ouvrage_CAP",
    "upep_aep": "eau_aep_ouvrage_TRAIT",
    "pompage_aep": "eau_aep_ouvrage_STPMP",
    "reservoir_aep": "eau_aep_ouvrage_CUV",
    "ouvrage_eau_brute_aep": "eau_aep_ouvrage_OUVEB",
    "poste_refoulement": "eau_eu_pr",
    "step": "eau_eu_step",
}

HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX = "hydraulic-native"

WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DOCS_DIR = REPO_ROOT / "docs"
# Keep complete-analysis execution logs isolated from case-study journals.
JOURNAL_MD = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.md"
JOURNAL_JSONL = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.jsonl"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
TRACK_SAMPLE_OUTPUT_ROOT = REPO_ROOT / "outputs" / "Échantillons Tracks_NA_Guadeloupe"

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

_SELF_STATUS_PATH = Path("/proc/self/status")
_MEMINFO_PATH = Path("/proc/meminfo")


def _read_proc_value_kb(path: Path, prefix: str) -> int | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if not raw_line.startswith(prefix):
                    continue
                parts = raw_line.split()
                if len(parts) < 2:
                    return None
                return int(parts[1])
    except (FileNotFoundError, OSError, ValueError):
        return None
    return None


def _resolve_malloc_trim() -> Any | None:
    if not sys.platform.startswith("linux"):
        return None
    libc_name = ctypes.util.find_library("c")
    if not libc_name:
        return None
    try:
        libc = ctypes.CDLL(libc_name)
    except OSError:
        return None
    malloc_trim = getattr(libc, "malloc_trim", None)
    if malloc_trim is None:
        return None
    malloc_trim.argtypes = [ctypes.c_size_t]
    malloc_trim.restype = ctypes.c_int
    return malloc_trim


_MALLOC_TRIM = _resolve_malloc_trim()


def _compact_process_memory() -> dict[str, Any]:
    rss_kb_before = _read_proc_value_kb(_SELF_STATUS_PATH, "VmRSS:")
    mem_available_kb_before = _read_proc_value_kb(_MEMINFO_PATH, "MemAvailable:")
    gc_collected = int(gc.collect())
    malloc_trim_result: int | None = None
    if _MALLOC_TRIM is not None:
        try:
            malloc_trim_result = int(_MALLOC_TRIM(0))
        except Exception:
            malloc_trim_result = None
    rss_kb_after = _read_proc_value_kb(_SELF_STATUS_PATH, "VmRSS:")
    mem_available_kb_after = _read_proc_value_kb(_MEMINFO_PATH, "MemAvailable:")
    return {
        "gc_collected": gc_collected,
        "malloc_trim_supported": bool(_MALLOC_TRIM is not None),
        "malloc_trim_result": malloc_trim_result,
        "rss_kb_before": rss_kb_before,
        "rss_kb_after": rss_kb_after,
        "mem_available_kb_before": mem_available_kb_before,
        "mem_available_kb_after": mem_available_kb_after,
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


def _load_existing_run_manifest_payload(run_id: str) -> dict[str, Any]:
    manifest_path = RUN_OUTPUTS_DIR / str(run_id) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found for run_id={run_id}: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid run manifest payload at {manifest_path}")
    return payload


def _parse_iso_datetime(raw_value: Any) -> datetime | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _infer_resume_max_points_per_shard(existing_manifest: dict[str, Any]) -> int | None:
    resumed_at = _parse_iso_datetime(existing_manifest.get("resumed_at"))
    candidate_counts: list[int] = []
    fallback_counts: list[int] = []
    territories = existing_manifest.get("territories") if isinstance(existing_manifest.get("territories"), dict) else {}
    for territory_entry in territories.values() if isinstance(territories, dict) else []:
        if not isinstance(territory_entry, dict):
            continue
        impacts = territory_entry.get("impacts") if isinstance(territory_entry.get("impacts"), dict) else {}
        hazards = impacts.get("hazards") if isinstance(impacts, dict) else {}
        if not isinstance(hazards, dict):
            continue
        for hazard_entry in hazards.values():
            if not isinstance(hazard_entry, dict):
                continue
            components = hazard_entry.get("components") if isinstance(hazard_entry.get("components"), dict) else {}
            if not isinstance(components, dict):
                continue
            for component_entry in components.values():
                if not isinstance(component_entry, dict):
                    continue
                shards = component_entry.get("shards") if isinstance(component_entry.get("shards"), dict) else {}
                if not isinstance(shards, dict):
                    continue
                for shard_entry in shards.values():
                    if not isinstance(shard_entry, dict):
                        continue
                    if str(shard_entry.get("status") or "") != "complete":
                        continue
                    point_count = int(shard_entry.get("point_count") or 0)
                    if point_count <= 0:
                        continue
                    fallback_counts.append(point_count)
                    updated_at = _parse_iso_datetime(shard_entry.get("updated_at"))
                    if resumed_at is not None and updated_at is not None and updated_at >= resumed_at:
                        continue
                    candidate_counts.append(point_count)
    if candidate_counts:
        return max(candidate_counts)
    if fallback_counts:
        return max(fallback_counts)
    return None


def _resolve_resume_runtime_parameters(
    *,
    args: argparse.Namespace,
    existing_manifest: dict[str, Any] | None,
    scenario: SensitivityScenario | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    existing_parameters = (
        dict(existing_manifest.get("parameters") or {})
        if isinstance(existing_manifest, dict)
        else {}
    )

    resolved_dynamic_max_tracks = int(
        existing_parameters.get("dynamic_max_tracks")
        if existing_parameters.get("dynamic_max_tracks") is not None
        else int(args.dynamic_max_tracks)
    )
    resolved_requested_dynamic_max_tracks = int(
        existing_parameters.get("requested_dynamic_max_tracks")
        if existing_parameters.get("requested_dynamic_max_tracks") is not None
        else int(args.dynamic_max_tracks)
    )
    resolved_memory_budget_gb = float(
        existing_parameters.get("memory_budget_gb")
        if existing_parameters.get("memory_budget_gb") is not None
        else float(args.memory_budget_gb)
    )
    inferred_max_points_per_shard = None
    if isinstance(existing_manifest, dict):
        inferred_max_points_per_shard = _infer_resume_max_points_per_shard(existing_manifest)
    resolved_max_points_per_shard = int(
        inferred_max_points_per_shard
        if inferred_max_points_per_shard is not None
        else (
            existing_parameters.get("max_points_per_shard")
            if existing_parameters.get("max_points_per_shard") is not None
            else int(args.max_points_per_shard)
        )
    )
    resolved_min_points_per_shard = int(
        existing_parameters.get("min_points_per_shard")
        if existing_parameters.get("min_points_per_shard") is not None
        else int(args.min_points_per_shard)
    )
    territories_raw = existing_parameters.get("territories")
    resolved_territories = (
        list(territories_raw)
        if isinstance(territories_raw, list) and territories_raw
        else parse_territory_selection(str(args.territories), default="both")
    )
    resolved_track_sample_manifest = (
        existing_parameters.get("track_sample_manifest")
        if existing_parameters.get("track_sample_manifest") is not None
        else (
            str(getattr(args, "track_sample_manifest", None))
            if getattr(args, "track_sample_manifest", None)
            else None
        )
    )

    if existing_parameters:
        requested_track_sample_manifest = getattr(args, "track_sample_manifest", None)
        current_requested = {
            "dynamic_max_tracks": int(args.dynamic_max_tracks),
            "requested_dynamic_max_tracks": int(args.dynamic_max_tracks),
            "memory_budget_gb": float(args.memory_budget_gb),
            "max_points_per_shard": int(args.max_points_per_shard),
            "min_points_per_shard": int(args.min_points_per_shard),
            "territories": parse_territory_selection(str(args.territories), default="both"),
            "track_sample_manifest": str(requested_track_sample_manifest) if requested_track_sample_manifest else None,
        }
        resolved_current = {
            "dynamic_max_tracks": resolved_dynamic_max_tracks,
            "requested_dynamic_max_tracks": resolved_requested_dynamic_max_tracks,
            "memory_budget_gb": resolved_memory_budget_gb,
            "max_points_per_shard": resolved_max_points_per_shard,
            "min_points_per_shard": resolved_min_points_per_shard,
            "territories": resolved_territories,
            "track_sample_manifest": resolved_track_sample_manifest,
        }
        for key in ("dynamic_max_tracks", "requested_dynamic_max_tracks", "memory_budget_gb", "max_points_per_shard", "min_points_per_shard", "territories", "track_sample_manifest"):
            if current_requested[key] != resolved_current[key]:
                warnings.append(
                    f"resume parameter '{key}' changed from {current_requested[key]!r} to {resolved_current[key]!r}; using the manifest value to preserve shard checkpoints"
                )

    effective_args = {
        "dynamic_max_tracks": resolved_dynamic_max_tracks,
        "requested_dynamic_max_tracks": resolved_requested_dynamic_max_tracks,
        "memory_budget_gb": resolved_memory_budget_gb,
        "max_points_per_shard": resolved_max_points_per_shard,
        "min_points_per_shard": resolved_min_points_per_shard,
        "territories": resolved_territories,
        "track_sample_manifest": resolved_track_sample_manifest,
    }
    return effective_args, warnings


def _build_fresh_frontend_resume_command(
    *,
    args: argparse.Namespace,
    resolved_args: dict[str, Any],
    effective_settings: Any,
    run_id: str,
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--resume-run-id",
        str(run_id),
        "--dynamic-max-tracks",
        str(int(resolved_args["requested_dynamic_max_tracks"])),
        "--territories",
        str(args.territories),
        "--max-points-per-shard",
        str(int(effective_settings.climada_max_points_per_shard)),
        "--memory-budget-gb",
        str(float(resolved_args["memory_budget_gb"])),
        "--min-points-per-shard",
        str(int(resolved_args["min_points_per_shard"])),
    ]
    track_sample_manifest = resolved_args.get("track_sample_manifest")
    if track_sample_manifest:
        command.extend(["--track-sample-manifest", str(track_sample_manifest)])
    if bool(args.no_deploy):
        command.append("--no-deploy")
    if bool(args.require_legacy_web):
        command.append("--require-legacy-web")
    if bool(args.abort_on_sighup):
        command.append("--abort-on-sighup")
    return command


def _infer_resume_dynamic_hazard_point_cap(
    run_manifest: "RunManifest",
    territory: str,
) -> int | None:
    territories = run_manifest.data.get("territories") if isinstance(run_manifest.data.get("territories"), dict) else {}
    territory_entry = territories.get(str(territory)) if isinstance(territories, dict) else None
    if not isinstance(territory_entry, dict):
        return None
    impacts = territory_entry.get("impacts") if isinstance(territory_entry.get("impacts"), dict) else {}
    hazards = impacts.get("hazards") if isinstance(impacts, dict) else {}
    if not isinstance(hazards, dict):
        return None

    candidate_counts: list[int] = []
    for hazard_entry in hazards.values():
        if not isinstance(hazard_entry, dict):
            continue
        components = hazard_entry.get("components") if isinstance(hazard_entry.get("components"), dict) else {}
        if not isinstance(components, dict):
            continue
        for component_entry in components.values():
            if not isinstance(component_entry, dict):
                continue
            shards = component_entry.get("shards") if isinstance(component_entry.get("shards"), dict) else {}
            if not isinstance(shards, dict):
                continue
            for shard_entry in shards.values():
                if not isinstance(shard_entry, dict):
                    continue
                if str(shard_entry.get("status") or "") != "complete":
                    continue
                point_count = int(shard_entry.get("point_count") or 0)
                if point_count > 0:
                    candidate_counts.append(point_count)
    if candidate_counts:
        return max(candidate_counts)
    return None


def _resolve_track_sample_manifest_path(track_sample_manifest_path: str | None, dynamic_max_tracks: int) -> Path | None:
    if not track_sample_manifest_path:
        return None

    raw_path = Path(str(track_sample_manifest_path)).expanduser()
    path = raw_path if raw_path.is_absolute() else (REPO_ROOT / raw_path)
    track_sample_root = TRACK_SAMPLE_OUTPUT_ROOT.resolve(strict=False)
    path_resolved = path.resolve(strict=False)

    candidate_roots: list[Path] = [path]
    if path_resolved == track_sample_root or (
        path.parent.resolve(strict=False) == TRACK_SAMPLE_OUTPUT_ROOT.parent.resolve(strict=False)
        and TRACK_SAMPLE_OUTPUT_ROOT.name.startswith(path.name)
    ):
        candidate_roots.append(TRACK_SAMPLE_OUTPUT_ROOT)

    candidates: list[Path] = []
    if int(dynamic_max_tracks) > 0:
        sample_manifest_rel = Path(f"sample_{int(dynamic_max_tracks):04d}") / "manifest.json"
        for candidate_root in candidate_roots:
            candidates.append(candidate_root / sample_manifest_rel)
    candidates.extend(candidate_root / "manifest.json" for candidate_root in candidate_roots)
    candidates.append(path)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            if candidate != path:
                logger.info("Resolved track sample manifest %s -> %s", path, candidate)
            return candidate
    return path


def _default_track_sample_max_points_per_shard(dynamic_max_tracks: int) -> int:
    track_count = int(dynamic_max_tracks)
    if track_count <= 0:
        return 0
    if track_count <= 50:
        return 20_000
    if track_count <= 100:
        return 15_000
    if track_count <= 800:
        return 5_000
    return 3_000


def _build_complete_analysis_settings(
    *,
    dynamic_max_tracks: int,
    track_sample_manifest_path: str | None,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
    allow_degraded_components: bool,
    scenario: SensitivityScenario | None,
) -> Settings:
    if bool(allow_degraded_components):
        raise ValueError(
            "--allow-degraded-components has been removed: scientific runs now fail explicitly on incomplete multi-hazard execution."
        )
    settings = load_settings()
    settings_dict = dataclasses.asdict(settings)
    settings_dict["hazard_dynamic_max_tracks"] = int(dynamic_max_tracks)
    resolved_track_sample_manifest_path = _resolve_track_sample_manifest_path(
        track_sample_manifest_path,
        int(dynamic_max_tracks),
    )
    settings_dict["hazard_track_sample_manifest_path"] = resolved_track_sample_manifest_path
    resolved_max_points_per_shard = max(0, int(max_points_per_shard))
    if resolved_track_sample_manifest_path is not None and resolved_max_points_per_shard <= 0:
        resolved_max_points_per_shard = _default_track_sample_max_points_per_shard(int(dynamic_max_tracks))
        if resolved_max_points_per_shard > 0:
            logger.info(
                "Using conservative track-sample shard cap: max_points_per_shard=%d for dynamic_max_tracks=%d",
                int(resolved_max_points_per_shard),
                int(dynamic_max_tracks),
            )
    settings_dict["climada_execution_profile"] = "complete-analysis"
    settings_dict["climada_memory_budget_gb"] = max(0.0, float(memory_budget_gb))
    settings_dict["climada_max_points_per_shard"] = int(resolved_max_points_per_shard)
    settings_dict["climada_min_points_per_shard"] = max(1, int(min_points_per_shard))
    settings_dict["impact_engine_mode"] = "climada"
    settings_dict["allow_climada_fallback"] = False
    settings_dict["hazard_fallback_to_precomputed"] = False
    settings_dict["climada_strict_required_components"] = True
    settings = Settings(**settings_dict)
    return apply_settings_overrides(settings, scenario)


def _reconcile_disaggregation_with_climada_bundle(
    *,
    territory_key: str,
    disagg: DisaggregationSummary,
    point_count_exact: int,
) -> DisaggregationSummary:
    exact_point_count = int(point_count_exact)
    if exact_point_count == int(disagg.asset_count_points):
        return disagg

    logger.warning(
        "Disaggregation count drift detected for %s: summary=%s exact_bundle=%s. Using exact bundle count.",
        territory_key.upper(),
        int(disagg.asset_count_points),
        exact_point_count,
    )
    disagg_warnings = list(disagg.warnings or [])
    disagg_warnings.append(
        "Disaggregation summary count was reconciled to the exact CLIMADA exposure bundle point count."
    )
    return dataclasses.replace(
        disagg,
        asset_count_points=exact_point_count,
        warnings=disagg_warnings,
    )


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
        
        for territory in EXPLICIT_TERRITORIES:
            if territory in territory_events:
                events = territory_events[territory]
                run_section.append(f"### {territory_label(territory)}")
                
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

    def set_post_run_phase(self, phase: str, status: str, **kwargs) -> None:
        phases = self.data.setdefault("post_run_phases", {})
        previous = phases.get(phase) if isinstance(phases, dict) else None
        previous_attempt = int(previous.get("attempt") or 0) if isinstance(previous, dict) else 0
        now = self._timestamp()
        entry = dict(previous) if isinstance(previous, dict) else {}
        entry.update(
            {
                "status": str(status),
                "updated_at": now,
                "resume_key": f"{self.run_id}:{phase}",
                **kwargs,
            }
        )
        if str(status) == "running":
            entry["attempt"] = previous_attempt + 1
            entry["started_at"] = now
            entry.pop("finished_at", None)
            entry.pop("last_error", None)
        elif str(status) in {"complete", "failed", "skipped"}:
            entry.setdefault("attempt", previous_attempt)
            entry["finished_at"] = now
            if str(status) != "failed":
                entry.pop("last_error", None)
        phases[phase] = entry
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

    def __init__(self, run_logger: RunLogger, run_manifest: RunManifest, *, abort_on_sighup: bool = False):
        self._run_logger = run_logger
        self._run_manifest = run_manifest
        self._abort_on_sighup = bool(abort_on_sighup)
        self._active = True
        self._previous_handlers: dict[int, Any] = {}
        atexit.register(self._on_exit)
        signal_numbers = [signal.SIGINT, signal.SIGTERM]
        sighup = getattr(signal, "SIGHUP", None)
        if sighup is not None and self._abort_on_sighup:
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
                manifest_payload = dict(payload)
                manifest_payload.pop("status", None)
                self._run_manifest.set_status("aborted", **manifest_payload)
        except Exception:
            pass

    def _on_signal(self, signum: int, _frame: Any) -> None:
        sighup = getattr(signal, "SIGHUP", None)
        if sighup is not None and signum == sighup and not self._abort_on_sighup:
            logger.warning(
                "Run received SIGHUP; keeping the complete-analysis job alive so the computation can finish."
            )
            return
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


def _read_vector(path: Path, *, layer: str | None = None, source_crs: str | None = None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if gdf.crs is None:
        return gdf.set_crs(source_crs or WGS84)
    return gdf


def _geometry_to_geojson(geom: Any) -> dict[str, Any] | None:
    if geom is None or getattr(geom, "is_empty", False) or mapping is None:
        return None
    try:
        return dict(mapping(geom))
    except Exception:
        return None


def _valuation_properties(asset_type: str, *, valuation_method: str, **extra_properties: Any) -> dict[str, Any]:
    props = {
        "asset_type": str(asset_type),
        "uses_default_value": False,
        "valuation_source": SOURCE_LABEL,
        "valuation_version": VALUATION_VERSION,
        "valuation_method": str(valuation_method),
    }
    for key, value in extra_properties.items():
        if value is None:
            continue
        props[str(key)] = value
    return props


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_hydraulic_service_key(
    row: Any,
    *,
    feature_id: str,
    context: str,
    allow_zone_uid_fallback: bool = False,
) -> tuple[str, str, str]:
    service_key = _clean_text(getattr(row, "zone_component_key", ""))
    if service_key:
        return service_key, "hydraulic_zone_component", "zone_component_key"

    zone_uid = _clean_text(getattr(row, "zone_uid", ""))
    if zone_uid and allow_zone_uid_fallback:
        return zone_uid, "hydraulic_zone_uid_legacy", "zone_uid_fallback"

    fallback_key = f"{HYDRAULIC_NATIVE_SERVICE_KEY_PREFIX}:{feature_id}"
    return fallback_key, "native_feature", "feature_id_fallback"


def _hydraulic_line_asset_type(network_kind: str) -> str:
    asset_type = HYDRAULIC_NETWORK_KIND_TO_ASSET_TYPE.get(_clean_text(network_kind).upper())
    if not asset_type:
        raise ValueError(f"Unsupported hydraulic line network_kind: {network_kind!r}")
    return asset_type


def _hydraulic_asset_type(feature_role: str, asset_type_code: str) -> str:
    asset_type = HYDRAULIC_ASSET_ROLE_TO_ASSET_TYPE.get(_clean_text(feature_role))
    if asset_type:
        return asset_type
    code = _clean_text(asset_type_code).upper()
    if code:
        return f"eau_aep_ouvrage_{code}"
    raise ValueError(f"Unsupported hydraulic asset role: feature_role={feature_role!r} asset_type_code={asset_type_code!r}")


def _hydraulic_line_features(
    gdf: gpd.GeoDataFrame,
    *,
    water_values: dict[str, float],
    context: str,
) -> list[NormalizedFeature]:
    gdf_wgs, gdf_metric = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    fallback_counts: Counter[str] = Counter()
    for idx, (row_wgs, geom_metric) in enumerate(zip(gdf_wgs.itertuples(index=False), gdf_metric.geometry, strict=False), start=1):
        geom_wgs = getattr(row_wgs, "geometry", None)
        if geom_wgs is None or geom_metric is None or getattr(geom_wgs, "is_empty", False) or getattr(geom_metric, "is_empty", False):
            continue
        feature_id = _clean_text(getattr(row_wgs, "feature_id", "")) or f"hydraulic-line-{idx}"
        service_key, service_unit_kind, service_key_source = _resolve_hydraulic_service_key(
            row_wgs,
            feature_id=feature_id,
            context=context,
        )
        if service_key_source != "zone_component_key":
            fallback_counts[service_key_source] += 1
        centroid = geom_wgs.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        asset_type = _hydraulic_line_asset_type(getattr(row_wgs, "network_kind", ""))
        value_key = "eau_aep" if asset_type == "eau_aep_cana" else "eau_eu"
        zone_uid = _clean_text(getattr(row_wgs, "zone_uid", "")) or None
        feature_role = _clean_text(getattr(row_wgs, "feature_role", "")) or "canalisation"
        network_kind = _clean_text(getattr(row_wgs, "network_kind", "")) or None
        source_feature_id = _clean_text(getattr(row_wgs, "source_feature_id", "")) or None
        zone_label = _clean_text(getattr(row_wgs, "zone_component_label", "")) or service_key
        length_km = max(0.0, float(getattr(geom_metric, "length", 0.0)) / 1000.0)
        value_eur = max(5_000.0, length_km * float(water_values[value_key]))
        out.append(
            NormalizedFeature(
                feature_id=feature_id,
                label=f"{asset_type} {zone_label}",
                value_eur=float(value_eur),
                geometry_type=str(getattr(geom_wgs, "geom_type", "LineString")),
                exposure_category="ouvrage_eau",
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=_geometry_to_geojson(geom_wgs),
                properties=_valuation_properties(
                    asset_type,
                    valuation_method="length_times_eur_per_km",
                    zone_component_key=service_key,
                    service_feature_id=service_key,
                    zone_uid=zone_uid,
                    network_kind=network_kind,
                    feature_role=feature_role,
                    source_feature_id=source_feature_id,
                    service_unit_kind=service_unit_kind,
                    hydraulic_service_key_source=service_key_source,
                ),
            )
        )
    if fallback_counts:
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(fallback_counts.items()))
        logger.warning(
            "%s: %d hydraulic line features used fallback service keys (%s)",
            context,
            int(sum(fallback_counts.values())),
            summary,
        )
    return out


def _hydraulic_asset_features(
    gdf: gpd.GeoDataFrame,
    *,
    territory: str,
    water_values: dict[str, float],
    context: str,
) -> list[NormalizedFeature]:
    gdf_wgs, _ = _as_wgs84_and_metric(gdf)
    out: list[NormalizedFeature] = []
    fallback_counts: Counter[str] = Counter()
    for idx, row in enumerate(gdf_wgs.itertuples(index=False), start=1):
        geom = getattr(row, "geometry", None)
        if geom is None or getattr(geom, "is_empty", False):
            continue
        feature_id = _clean_text(getattr(row, "feature_id", "")) or f"hydraulic-asset-{idx}"
        service_key, service_unit_kind, service_key_source = _resolve_hydraulic_service_key(
            row,
            feature_id=feature_id,
            context=context,
            allow_zone_uid_fallback=True,
        )
        if service_key_source != "zone_component_key":
            fallback_counts[service_key_source] += 1
        centroid = geom.centroid
        if centroid is None or getattr(centroid, "is_empty", False):
            continue
        feature_role = _clean_text(getattr(row, "feature_role", ""))
        asset_type_code = _clean_text(getattr(row, "asset_type_code", ""))
        asset_type = _hydraulic_asset_type(feature_role, asset_type_code)
        if asset_type == "eau_eu_pr":
            value_eur = float(water_values["eau_eu_pr"])
        elif asset_type == "eau_eu_step":
            value_eur = float(water_values["eau_eu_step"])
        else:
            value_eur = float(
                get_aep_ouvrage_value_for_territory(
                    territory,
                    asset_type_code or asset_type.rsplit("_", 1)[-1],
                )
            )
        zone_uid = _clean_text(getattr(row, "zone_uid", "")) or None
        network_kind = _clean_text(getattr(row, "network_kind", "")) or None
        criticality = _clean_text(getattr(row, "criticality", "")) or None
        source_feature_id = _clean_text(getattr(row, "source_feature_id", "")) or None
        asset_name = _clean_text(getattr(row, "asset_name", "")) or feature_id
        out.append(
            NormalizedFeature(
                feature_id=feature_id,
                label=asset_name,
                value_eur=float(value_eur),
                geometry_type=str(getattr(geom, "geom_type", "Point")),
                exposure_category="ouvrage_eau",
                lon=float(getattr(centroid, "x", 0.0)),
                lat=float(getattr(centroid, "y", 0.0)),
                geometry_geojson=_geometry_to_geojson(geom),
                properties=_valuation_properties(
                    asset_type,
                    valuation_method="hydraulic_asset_role_lookup",
                    zone_component_key=service_key,
                    service_feature_id=service_key,
                    zone_uid=zone_uid,
                    network_kind=network_kind,
                    feature_role=feature_role,
                    criticality=criticality,
                    asset_type_code=asset_type_code or None,
                    source_feature_id=source_feature_id,
                    service_unit_kind=service_unit_kind,
                    hydraulic_service_key_source=service_key_source,
                ),
            )
        )
    if fallback_counts:
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(fallback_counts.items()))
        logger.warning(
            "%s: %d hydraulic asset features used fallback service keys (%s)",
            context,
            int(sum(fallback_counts.values())),
            summary,
        )
    return out


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
                geometry_geojson=_geometry_to_geojson(geom_wgs),
                properties=_valuation_properties(asset_type, valuation_method="length_times_eur_per_km"),
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
                geometry_geojson=_geometry_to_geojson(geom),
                properties=_valuation_properties(asset_type, valuation_method="fixed_unit_value"),
            )
        )
    return out


def _point_features_aep_ouvrages_from_field(
    gdf: gpd.GeoDataFrame,
    *,
    territory: str,
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
                value_eur=get_aep_ouvrage_value_for_territory(territory, ovrg_type),
                geometry_type=str(geom.geom_type),
                exposure_category="ouvrage_eau",
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=_geometry_to_geojson(geom),
                properties=_valuation_properties(asset_type, valuation_method="ouvrage_type_lookup"),
            )
        )
    return out


def _point_features_aep_ouvrages_fixed_type(
    gdf: gpd.GeoDataFrame,
    *,
    territory: str,
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
                value_eur=get_aep_ouvrage_value_for_territory(territory, code),
                geometry_type=str(geom.geom_type),
                exposure_category="ouvrage_eau",
                lon=float(centroid.x),
                lat=float(centroid.y),
                geometry_geojson=_geometry_to_geojson(geom),
                properties=_valuation_properties(f"eau_aep_ouvrage_{code}", valuation_method="ouvrage_type_lookup"),
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
    elec_values = get_elec_values_for_territory(territory_key)
    features: list[NormalizedFeature] = []
    bbox_polygon = _bbox_polygon_from_cfg(cfg)

    # Load electricity lines
    for src in cfg["elec_line_sources"]:
        eur_per_km = float(elec_values[str(src["asset_type"])])
        for p_idx, path in enumerate(src["paths"], start=1):
            try:
                gdf = _clip_to_bbox(
                    _read_vector(path, source_crs=str(src.get("source_crs", "") or "") or None),
                    bbox_polygon,
                )
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

    # Load water networks and ouvrages from canonical hydraulic zoning V2 bundles
    for src in cfg["hydraulic_zone_sources"]:
        bundle_path = Path(src["path"])
        try:
            lines_gdf = _clip_to_bbox(_read_vector(bundle_path, layer=str(src["line_layer"])), bbox_polygon)
            if not lines_gdf.empty:
                features.extend(
                    _hydraulic_line_features(
                        lines_gdf,
                        water_values=water_values,
                        context=f"hydraulic bundle {bundle_path.name}:{src['line_layer']}",
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to load hydraulic lines from {bundle_path}: {e}")

        try:
            assets_gdf = _clip_to_bbox(_read_vector(bundle_path, layer=str(src["asset_layer"])), bbox_polygon)
            if not assets_gdf.empty:
                features.extend(
                    _hydraulic_asset_features(
                        assets_gdf,
                        territory=territory_key,
                        water_values=water_values,
                        context=f"hydraulic bundle {bundle_path.name}:{src['asset_layer']}",
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to load hydraulic assets from {bundle_path}: {e}")

    warnings = [
        "Water valuation uses the documented network dossier profile plus territory-specific AEP exceptions.",
        f"Valuation source: {SOURCE_LABEL}.",
        f"Territory: {territory_key}.",
        "All water assets conservatively assumed dependent on electricity.",
        "Water service metadata comes from hydraulic_zoning_v2 zone_component_key.",
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
    track_sample_manifest_path: str | None,
    memory_budget_gb: float,
    max_points_per_shard: int,
    min_points_per_shard: int,
    allow_degraded_components: bool,
    resume_enabled: bool,
    resume_dynamic_hazard_point_cap: int | None,
    materialize_scientific_graph_inputs: bool,
    scenario: SensitivityScenario | None,
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

        settings = _build_complete_analysis_settings(
            dynamic_max_tracks=dynamic_max_tracks,
            track_sample_manifest_path=track_sample_manifest_path,
            memory_budget_gb=memory_budget_gb,
            max_points_per_shard=max_points_per_shard,
            min_points_per_shard=min_points_per_shard,
            allow_degraded_components=allow_degraded_components,
            scenario=scenario,
        )
        settings = dataclasses.replace(
            settings,
            hazard_surge_topo_path=resolve_surge_topo_path_for_territory(
                territory_key,
                settings=settings,
            ),
        )
        logger.info("Using surge topo for %s: %s", territory_key.upper(), settings.hazard_surge_topo_path)
        
        # Disaggregate
        logger.info(f"Computing disaggregation...")
        current_phase = "disaggregation"
        run_manifest.set_phase(territory_key, "disaggregation", "running")
        disagg = summarize_disaggregation(
            exposure,
            spacing_m=float(settings.default_sampling_spacing_m),
            metric_crs=settings.climada_metric_crs,
            max_points_per_feature=int(settings.climada_max_points_per_feature),
        )
        climada_bundle = prepare_climada_exposure_bundle(exposure, disagg, settings)
        disagg = _reconcile_disaggregation_with_climada_bundle(
            territory_key=territory_key,
            disagg=disagg,
            point_count_exact=len(climada_bundle.point_records),
        )
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
        logger.info(
            "Computing impacts (dynamic_max_tracks=%s, track_sample_manifest=%s)...",
            int(settings.hazard_dynamic_max_tracks),
            str(settings.hazard_track_sample_manifest_path) if settings.hazard_track_sample_manifest_path else "none",
        )
        current_phase = "impacts"
        run_manifest.set_phase(
            territory_key,
            "impacts",
            "running",
            dynamic_max_tracks=int(settings.hazard_dynamic_max_tracks),
            memory_budget_gb=float(memory_budget_gb),
            max_points_per_shard=int(settings.climada_max_points_per_shard),
            min_points_per_shard=int(min_points_per_shard),
            strict_components=not bool(allow_degraded_components),
            scenario_id=(scenario.scenario_id if scenario is not None else None),
            track_sample_manifest=(
                str(settings.hazard_track_sample_manifest_path)
                if settings.hazard_track_sample_manifest_path
                else None
            ),
        )
        impact_start = time.time()
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
            resume_dynamic_hazard_point_cap=resume_dynamic_hazard_point_cap,
            prebuilt_bundle=climada_bundle,
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
            coherence_report=(comp.artifacts.get("coherence_report") if isinstance(comp.artifacts, dict) else None),
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
        payload["meta"]["run_id"] = run_manifest.run_id
        payload["exposure_summary"]["asset_type_counts"] = dict(
            Counter(str((feat.properties or {}).get("asset_type") or "unknown") for feat in exposure.features)
        )
        pml_graph_inputs = payload.get("pml_network_graph_inputs")
        pml_state_tables = (
            pml_graph_inputs.get("state_damage_tables")
            if isinstance(pml_graph_inputs, dict)
            else None
        )
        pml_breakdowns = (
            pml_graph_inputs.get("damage_breakdown_by_scenario")
            if isinstance(pml_graph_inputs, dict)
            else None
        )
        pml_graph_inputs_complete = (
            isinstance(pml_graph_inputs, dict)
            and list(pml_graph_inputs.get("scenarios") or []) == list(SCIENTIFIC_SCENARIOS)
            and isinstance(pml_state_tables, dict)
            and isinstance(pml_breakdowns, dict)
            and all(
                isinstance(pml_state_tables.get(scenario), list)
                and bool(pml_state_tables.get(scenario))
                and isinstance(pml_breakdowns.get(scenario), dict)
                and isinstance(pml_breakdowns.get(scenario, {}).get("storm"), list)
                and isinstance(pml_breakdowns.get(scenario, {}).get("storm_cmcc"), list)
                for scenario in SCIENTIFIC_SCENARIOS
            )
        )
        if not pml_graph_inputs_complete:
            raise RuntimeError(
                f"PML-light network graph inputs were not produced for {territory_key}; "
                "complete-analysis cannot generate RP10/RP50/RP100/RP1000 graph outputs safely."
            )
        run_manifest.set_phase(
            territory_key,
            "pml_network_graph_inputs",
            "complete",
            schema_version=str(pml_graph_inputs.get("schema_version") or ""),
            method=str(pml_graph_inputs.get("method") or ""),
            scenarios=list(pml_graph_inputs.get("scenarios") or []),
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
        if not archived_complete_analysis_path:
            raise RuntimeError(f"Failed to archive complete-analysis for {territory_key}")
        archived_complete_analysis_file = Path(archived_complete_analysis_path)

        if materialize_scientific_graph_inputs:
            current_phase = "scientific_graph_inputs"
            del payload
            del comp
            del climada_bundle
            del disagg
            del exposure
            compaction = _compact_process_memory()
            logger.info(
                "Scientific graph parent memory compaction: rss_kb_before=%s rss_kb_after=%s mem_available_kb_before=%s mem_available_kb_after=%s malloc_trim_supported=%s malloc_trim_result=%s gc_collected=%s",
                compaction.get("rss_kb_before"),
                compaction.get("rss_kb_after"),
                compaction.get("mem_available_kb_before"),
                compaction.get("mem_available_kb_after"),
                compaction.get("malloc_trim_supported"),
                compaction.get("malloc_trim_result"),
                compaction.get("gc_collected"),
            )
            run_manifest.set_phase(
                territory_key,
                "scientific_graph_inputs",
                "running",
                complete_analysis_path=str(archived_complete_analysis_file),
                event_selection_basis="global_portfolio_loss",
                scenarios=list(SCIENTIFIC_SCENARIOS),
            )
            logger.info(
                "Materializing V4 scientific graph inputs before marking %s complete...",
                territory_key,
            )
            scientific_env = os.environ.copy()
            scientific_env.update(
                {
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                    "VECLIB_MAXIMUM_THREADS": "1",
                    "BLIS_NUM_THREADS": "1",
                    "OMP_THREAD_LIMIT": "1",
                    "MALLOC_ARENA_MAX": "2",
                    "SIB_SCIENTIFIC_WORKER_MAX_POINTS_PER_CHUNK": "5000",
                }
            )
            scientific_command = [
                sys.executable,
                str(SCRIPTS_ROOT / "scientific_graph_postprocess.py"),
                "--territory",
                territory_key,
                "--complete-analysis-json",
                str(archived_complete_analysis_file),
                "--manifest-json",
                str(run_manifest.manifest_path),
                "--inline-workers",
            ]
            scientific_result = subprocess.run(
                scientific_command,
                env=scientific_env,
                text=True,
            )
            if scientific_result.returncode != 0:
                normalized_returncode = (
                    128 + abs(scientific_result.returncode)
                    if scientific_result.returncode < 0
                    else int(scientific_result.returncode)
                )
                raise RuntimeError(
                    f"scientific_graph_postprocess failed for {territory_key} with exit code {normalized_returncode}"
                )
            rebuilt_payload = json.loads(archived_complete_analysis_file.read_text(encoding="utf-8"))
            graph_inputs = rebuilt_payload.get("scientific_graph_inputs")
            scientific_graph_inputs_complete = (
                isinstance(graph_inputs, dict)
                and str(graph_inputs.get("source_of_truth") or "") == "complete_analysis"
                and bool(graph_inputs.get("state_damage_tables"))
                and bool(graph_inputs.get("damage_breakdown_by_scenario"))
                and bool(graph_inputs.get("damage_zones_by_scenario"))
            )
            if not scientific_graph_inputs_complete:
                raise RuntimeError(
                    f"V4 scientific_graph_inputs remain incomplete for {territory_key} after materialization"
                )
            _mirror_file(archived_complete_analysis_file, out_path)
            if scientific_graph_inputs_complete:
                run_manifest.set_phase(
                    territory_key,
                    "scientific_graph_inputs",
                    "complete",
                    complete_analysis_path=str(archived_complete_analysis_file),
                    event_selection_basis="global_portfolio_loss",
                    scenarios=list(SCIENTIFIC_SCENARIOS),
                )
        else:
            run_manifest.set_phase(
                territory_key,
                "scientific_graph_inputs",
                "skipped",
                complete_analysis_path=str(archived_complete_analysis_file),
                reason="strict scientific_graph_postprocess is optional; pml_network_graph_inputs are produced natively",
                replacement_phase="pml_network_graph_inputs",
                scenarios=list(SCIENTIFIC_SCENARIOS),
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
    *tuple(
        relative_path
        for territory in EXPLICIT_TERRITORIES
        for relative_path in (
            f"data/{territory}-complete-analysis.json",
            f"data/{territory}-scientific-web-summary.json",
            f"data/{territory}-wind-maps.json",
            f"data/{territory}-landslide-maps.json",
            f"data/{territory}-multi-hazard-proxy.json",
            f"data/{territory}-{territory_page_suffix(territory)}-analysis.json",
            f"data/{territory}-water-infra.geojson",
            f"data/{territory}-network-states.geojson",
        )
    ),
)

FRONTEND_PROXY_MAX_POINTS_TOTAL = 600
FRONTEND_PROXY_MAX_POINTS_PER_FEATURE = 6
FRONTEND_PROXY_DYNAMIC_MAX_TRACKS = 100
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


def rebuild_case_study_frontend_artifacts(
    territories: list[str],
    dynamic_max_tracks: int,
    *,
    run_id: str | None,
    supervision_journal: Path,
) -> None:
    script_path = SCRIPTS_ROOT / "rerun_case_studies_light.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing frontend build script: {script_path}")

    compaction = _compact_process_memory()
    logger.info(
        "Frontend rebuild parent memory compaction: rss_kb_before=%s rss_kb_after=%s mem_available_kb_before=%s mem_available_kb_after=%s malloc_trim_supported=%s malloc_trim_result=%s gc_collected=%s",
        compaction.get("rss_kb_before"),
        compaction.get("rss_kb_after"),
        compaction.get("mem_available_kb_before"),
        compaction.get("mem_available_kb_after"),
        compaction.get("malloc_trim_supported"),
        compaction.get("malloc_trim_result"),
        compaction.get("gc_collected"),
    )
    write_frontend_supervision_event(
        supervision_journal,
        actor="parent",
        event="frontend_parent_memory_compacted",
        run_id=run_id,
        parent_pid=os.getpid(),
        **compaction,
    )

    # Normal runs keep the stable public cap, but fast validation runs must not
    # request a heavier map rebuild than the parent analysis itself.
    requested_dynamic_max_tracks = int(dynamic_max_tracks)
    configured_dynamic_max_tracks = int(getattr(load_settings(), "hazard_dynamic_max_tracks"))
    if requested_dynamic_max_tracks > 0:
        frontend_map_dynamic_max_tracks = min(
            int(FRONTEND_MAP_DYNAMIC_MAX_TRACKS_CAP),
            requested_dynamic_max_tracks,
        )
    else:
        frontend_map_dynamic_max_tracks = int(FRONTEND_MAP_DYNAMIC_MAX_TRACKS_CAP)

    def _normalized_subprocess_returncode(returncode: int) -> int:
        code = int(returncode)
        if code >= 0:
            return code
        return 128 + abs(code)

    def _frontend_command() -> list[str]:
        # rerun_case_studies_light now derives a territory-safe full-coverage
        # page-component configuration when these overrides are omitted.
        return [
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
            "--map-dynamic-max-tracks",
            str(frontend_map_dynamic_max_tracks),
        ]

    command = _frontend_command()
    env = os.environ.copy()
    env[ENV_FRONTEND_SUPERVISION_JOURNAL] = str(supervision_journal)
    if run_id:
        env[ENV_FRONTEND_SUPERVISION_RUN_ID] = str(run_id)
    frontend_page_component_dynamic_max_tracks: int | None = None
    if 0 < requested_dynamic_max_tracks < configured_dynamic_max_tracks:
        frontend_page_component_dynamic_max_tracks = requested_dynamic_max_tracks
        env["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] = str(requested_dynamic_max_tracks)

    write_frontend_supervision_event(
        supervision_journal,
        actor="parent",
        event="frontend_rebuild_requested",
        run_id=run_id,
        parent_pid=os.getpid(),
        territories=list(territories),
        requested_dynamic_max_tracks=requested_dynamic_max_tracks,
        configured_dynamic_max_tracks=configured_dynamic_max_tracks,
        frontend_map_dynamic_max_tracks=frontend_map_dynamic_max_tracks,
        frontend_page_component_dynamic_max_tracks=frontend_page_component_dynamic_max_tracks,
        command=" ".join(str(part) for part in command),
    )

    process = subprocess.Popen(command, env=env)
    child_start_ticks = read_process_start_ticks(process.pid)
    parent_start_ticks = read_process_start_ticks(os.getpid())
    write_frontend_supervision_event(
        supervision_journal,
        actor="parent",
        event="frontend_child_spawned",
        run_id=run_id,
        parent_pid=os.getpid(),
        parent_start_ticks=parent_start_ticks,
        child_pid=process.pid,
        child_start_ticks=child_start_ticks,
    )
    monitor_process = launch_frontend_supervision_monitor(
        journal_path=supervision_journal,
        run_id=run_id,
        territories=list(territories),
        parent_pid=os.getpid(),
        parent_start_ticks=parent_start_ticks,
        child_pid=process.pid,
        child_start_ticks=child_start_ticks,
    )
    write_frontend_supervision_event(
        supervision_journal,
        actor="parent",
        event="frontend_monitor_spawned",
        run_id=run_id,
        monitor_pid=monitor_process.pid,
    )

    try:
        returncode = process.wait(timeout=5400)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        returncode = process.wait(timeout=30)
        normalized_returncode = _normalized_subprocess_returncode(int(returncode))
        write_frontend_supervision_event(
            supervision_journal,
            actor="parent",
            event="frontend_child_wait_timeout",
            run_id=run_id,
            child_pid=process.pid,
            timeout_seconds=5400,
            returncode_raw=int(returncode),
            returncode_normalized=normalized_returncode,
        )
        raise RuntimeError(
            f"rerun_case_studies_light.py timed out after 5400s while rebuilding frontend artefacts for {', '.join(territories)}"
        ) from exc

    normalized_returncode = _normalized_subprocess_returncode(int(returncode))
    write_frontend_supervision_event(
        supervision_journal,
        actor="parent",
        event="frontend_child_returned",
        run_id=run_id,
        child_pid=process.pid,
        returncode_raw=int(returncode),
        returncode_normalized=normalized_returncode,
    )
    if returncode != 0:
        joined = ", ".join(territories) if territories else "unknown"
        if normalized_returncode == 2:
            raise RuntimeError(
                f"rerun_case_studies_light.py detected reused or incoherent frontend artefacts for {joined}; deployment aborted"
            )
        if normalized_returncode == 137:
            raise RuntimeError(
                f"rerun_case_studies_light.py was killed by SIGKILL while rebuilding frontend artefacts for {joined}; "
                "the heavy case-study rerun likely exhausted memory"
            )
        raise RuntimeError(
            f"rerun_case_studies_light.py failed for {joined} with exit code {normalized_returncode} (raw={returncode})"
        )


def _frontend_artifacts_required(scenario: SensitivityScenario | None) -> bool:
    return scenario is None


def snapshot_frontend_artifacts_for_run(
    run_manifest: RunManifest,
    territories: list[str],
    *,
    min_mtime_epoch: float,
) -> dict[str, dict[str, str]]:
    archived_by_territory: dict[str, dict[str, str]] = {}
    validation_by_territory: dict[str, dict[str, Any]] = {}
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
        try:
            validation_by_territory[territory] = validate_territory_web_snapshot(run_manifest.run_id, territory)
        except Exception as exc:
            problems.append(f"{territory}: validation {exc}")
    if problems:
        raise RuntimeError("frontend artefact snapshot validation failed: " + "; ".join(problems))
    for territory, archived_files in archived_by_territory.items():
        run_manifest.set_territory_status(
            territory,
            run_manifest.get_territory_status(territory) or "complete",
            archived_frontend_artifacts=archived_files,
            archived_frontend_validation=validation_by_territory.get(territory),
        )
    return archived_by_territory


def _fresh_frontend_resume_active() -> bool:
    return str(os.environ.get(ENV_FRESH_FRONTEND_RESUME) or "").strip() == "1"


def _should_exec_fresh_frontend_resume(
    *,
    calculation_complete: bool,
    frontend_required: bool,
    territories_for_frontend: list[str],
) -> bool:
    return (
        bool(calculation_complete)
        and bool(frontend_required)
        and bool(territories_for_frontend)
        and not _fresh_frontend_resume_active()
    )


def _read_frontend_supervision_events(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _completed_frontend_journal_min_mtime_epoch(
    journal_path: Path,
    *,
    run_id: str,
    territories: list[str],
) -> float | None:
    requested_territories = {str(territory) for territory in territories}
    frontend_started_at: datetime | None = None
    latest_child_terminal: dict[str, Any] | None = None
    for event in _read_frontend_supervision_events(journal_path):
        event_run_id = str(event.get("run_id") or event.get("complete_analysis_run_id") or "").strip()
        if event_run_id and event_run_id != str(run_id):
            continue
        event_name = str(event.get("event") or "")
        if event_name == "frontend_phase_started":
            parsed = _parse_iso_datetime(event.get("timestamp"))
            if parsed is not None:
                frontend_started_at = parsed
            latest_child_terminal = None
            continue
        if event_name not in {"child_completed", "child_failed"}:
            continue
        event_territories = {str(item) for item in event.get("territories") or []}
        if requested_territories and event_territories and not requested_territories.issubset(event_territories):
            continue
        latest_child_terminal = event

    if not latest_child_terminal or str(latest_child_terminal.get("event") or "") != "child_completed":
        return None
    completed_at = _parse_iso_datetime(latest_child_terminal.get("timestamp"))
    started_at = frontend_started_at or completed_at
    if started_at is None:
        return None
    # Give the filesystem clock a small grace window around the journal write.
    return max(0.0, started_at.timestamp() - 2.0)


def recover_completed_frontend_artifacts_from_journal(
    run_manifest: RunManifest,
    territories: list[str],
    *,
    supervision_journal: Path,
) -> dict[str, dict[str, str]] | None:
    min_mtime_epoch = _completed_frontend_journal_min_mtime_epoch(
        supervision_journal,
        run_id=run_manifest.run_id,
        territories=list(territories),
    )
    if min_mtime_epoch is None:
        return None
    archived_frontend_artifacts = snapshot_frontend_artifacts_for_run(
        run_manifest,
        territories,
        min_mtime_epoch=min_mtime_epoch,
    )
    run_manifest.set_status(
        "running",
        frontend_artifacts={
            "status": "complete",
            "territories": list(territories),
            "archived_files_by_territory": archived_frontend_artifacts,
            "supervision_journal": str(supervision_journal),
            "recovered_from_supervision_journal": True,
            "recovered_at": datetime.now(timezone.utc).isoformat(),
        },
        frontend_artifacts_success=True,
    )
    return archived_frontend_artifacts


def _tail_text(value: str, *, max_chars: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _run_bounded_postrun_command(
    command: list[str],
    *,
    phase_name: str,
    attempts: int = 2,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max(1, int(attempts)) + 1):
        logger.info("Post-run phase %s attempt %s/%s: %s", phase_name, attempt, attempts, " ".join(command))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(
                command,
                returncode=124,
                stdout=str(exc.stdout or ""),
                stderr=f"Timed out after {timeout_seconds}s\n{exc.stderr or ''}",
            )
        last_result = result
        if result.returncode == 0:
            return result
        normalized_returncode = 128 + abs(result.returncode) if result.returncode < 0 else int(result.returncode)
        retryable = normalized_returncode in {124, 137, 143}
        logger.error(
            "Post-run phase %s failed attempt %s/%s with exit=%s: %s",
            phase_name,
            attempt,
            attempts,
            normalized_returncode,
            _tail_text(result.stderr or result.stdout, max_chars=1200),
        )
        if not retryable or attempt >= attempts:
            return result
        time.sleep(min(30, 5 * attempt))
    assert last_result is not None
    return last_result


def _archived_web_data_dir(run_manifest: RunManifest, territory: str) -> Path:
    return run_manifest.run_dir / "territories" / str(territory) / "web" / "data"


def _completed_complete_analysis_path(run_manifest: RunManifest, territory: str) -> Path:
    result = run_manifest.completed_territory_result(territory)
    if not result:
        raise FileNotFoundError(f"No completed complete-analysis artifact registered for territory={territory}")
    path = Path(str(result.get("complete_analysis_path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"complete-analysis artifact is missing for territory={territory}: {path}")
    return path


def _web_data_path(relative_path: str) -> Path:
    return REPO_ROOT / "web" / str(relative_path)


def _mirror_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Cannot mirror missing artifact: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() == source.read_bytes():
        return
    shutil.copyfile(source, destination)


def _mirror_allowed_web_artifacts_to_archive(run_manifest: RunManifest, territory: str) -> dict[str, str]:
    data_dir = _archived_web_data_dir(run_manifest, territory)
    allowed_names = (
        f"{territory}-wind-maps.json",
        f"{territory}-landslide-maps.json",
        f"{territory}-multi-hazard-proxy.json",
        f"{territory}-network-states.geojson",
        f"{territory}-water-infra.geojson",
        "vulnerability-curves-wind.json",
        "vulnerability-curves-rain.json",
        "vulnerability-curves-surge.json",
        "vulnerability-curves-landslide.json",
    )
    mirrored: dict[str, str] = {}
    for name in allowed_names:
        source = WEB_DATA_DIR / name
        if not source.exists():
            continue
        destination = data_dir / name
        _mirror_file(source, destination)
        mirrored[name] = str(destination)
    return mirrored


def _validate_scientific_summary_v4(summary_path: Path, complete_analysis_path: Path) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    complete_analysis = json.loads(complete_analysis_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or not isinstance(complete_analysis, dict):
        raise ValueError(f"Invalid scientific publication JSON payloads for {summary_path}")
    summary_meta = summary.get("meta") if isinstance(summary.get("meta"), dict) else {}
    if summary_meta.get("schema_version") != SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION:
        raise ValueError(
            f"{summary_path} has schema_version={summary_meta.get('schema_version')!r}, "
            f"expected {SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION!r}"
        )
    if summary_meta.get("contract_version") != SCIENTIFIC_WEB_CONTRACT_VERSION:
        raise ValueError(
            f"{summary_path} has contract_version={summary_meta.get('contract_version')!r}, "
            f"expected {SCIENTIFIC_WEB_CONTRACT_VERSION!r}"
        )
    graph_inputs = complete_analysis.get("scientific_graph_inputs")
    if not isinstance(graph_inputs, dict):
        raise ValueError(f"{complete_analysis_path} is missing scientific_graph_inputs")
    scenarios = list(graph_inputs.get("scenarios") or [])
    if scenarios != list(SCIENTIFIC_SCENARIOS):
        raise ValueError(
            f"{complete_analysis_path} has scientific scenarios {scenarios!r}, "
            f"expected {list(SCIENTIFIC_SCENARIOS)!r}"
        )
    if summary.get("scientific_graph_inputs") != graph_inputs:
        raise ValueError(
            f"{summary_path} does not republish complete_analysis.scientific_graph_inputs 1:1"
        )
    payload_text = json.dumps(summary, ensure_ascii=False)
    forbidden_exact_tokens = ("\"annual\"", "\"p99\"", "\"event_max\"")
    forbidden_substrings = ("water_aep", "water_eu")
    found = [token.strip('"') for token in forbidden_exact_tokens if token in payload_text]
    found.extend(token for token in forbidden_substrings if token in payload_text)
    if found:
        raise ValueError(f"{summary_path} contains forbidden legacy public keys/scenarios: {found}")
    network_keys = set()
    for scenario_payload in (graph_inputs.get("network_state_distribution_by_scenario") or {}).values():
        if isinstance(scenario_payload, dict):
            network_keys.update(str(key) for key in scenario_payload.keys())
    unexpected_network_keys = sorted(network_keys.difference(PUBLIC_SERVICE_KEYS))
    if unexpected_network_keys:
        raise ValueError(
            f"{complete_analysis_path} contains non-canonical public service keys: {unexpected_network_keys}"
        )
    return summary


def build_scientific_publication_artifacts(
    run_manifest: RunManifest,
    territories: list[str],
    *,
    repair_legacy_scientific_inputs: bool,
) -> bool:
    if not territories:
        return False
    run_manifest.set_post_run_phase(
        "scientific_publication",
        "running",
        territories=list(territories),
        repair_legacy_scientific_inputs=bool(repair_legacy_scientific_inputs),
    )
    archived_by_territory: dict[str, dict[str, str]] = {}
    try:
        for territory in territories:
            complete_analysis_path = _completed_complete_analysis_path(run_manifest, territory)
            web_data_dir = _archived_web_data_dir(run_manifest, territory)
            mirrored_allowed_artifacts = _mirror_allowed_web_artifacts_to_archive(run_manifest, territory)
            summary_path = web_data_dir / f"{territory}-scientific-web-summary.json"
            network_states_path = web_data_dir / f"{territory}-network-states.geojson"
            if not network_states_path.exists():
                mutable_network_states_path = WEB_DATA_DIR / f"{territory}-network-states.geojson"
                network_states_path = mutable_network_states_path if mutable_network_states_path.exists() else network_states_path

            command = [
                sys.executable,
                str(SCRIPTS_ROOT / "build_scientific_web_summary.py"),
                "--territory",
                territory,
                "--complete-analysis-json",
                str(complete_analysis_path),
                "--out-json",
                str(summary_path),
            ]
            if network_states_path.exists():
                command.extend(["--network-states-geojson", str(network_states_path)])
            if repair_legacy_scientific_inputs:
                command.append("--repair-legacy-scientific-inputs")

            run_manifest.set_phase(
                territory,
                "scientific_publication",
                "running",
                output_file=str(summary_path),
                repair_legacy_scientific_inputs=bool(repair_legacy_scientific_inputs),
            )
            result = _run_bounded_postrun_command(
                command,
                phase_name=f"scientific_publication:{territory}",
                attempts=2,
                timeout_seconds=None,
            )
            if result.returncode != 0:
                error = _tail_text(result.stderr or result.stdout)
                run_manifest.set_phase(
                    territory,
                    "scientific_publication",
                    "failed",
                    output_file=str(summary_path),
                    last_error=error,
                )
                raise RuntimeError(f"scientific_publication failed for {territory}: {error}")
            _validate_scientific_summary_v4(summary_path, complete_analysis_path)
            _mirror_file(summary_path, _web_data_path(territory_scientific_web_summary_relative_path(territory)))
            archived_by_territory[territory] = {
                "complete_analysis": str(complete_analysis_path),
                "scientific_web_summary": str(summary_path),
                **mirrored_allowed_artifacts,
            }
            run_manifest.set_phase(
                territory,
                "scientific_publication",
                "complete",
                output_file=str(summary_path),
                contract_version=SCIENTIFIC_WEB_CONTRACT_VERSION,
                schema_version=SCIENTIFIC_WEB_SUMMARY_SCHEMA_VERSION,
            )
        run_manifest.set_post_run_phase(
            "scientific_publication",
            "complete",
            territories=list(territories),
            archived_files_by_territory=archived_by_territory,
        )
        return True
    except Exception as exc:
        run_manifest.set_post_run_phase(
            "scientific_publication",
            "failed",
            territories=list(territories),
            last_error=str(exc),
            recoverable=True,
        )
        logger.error("✗ Scientific publication failed: %s", exc, exc_info=True)
        return False


def generate_graph_artifacts_for_run(run_manifest: RunManifest, *, formats: str = "html,png") -> bool:
    output_dir = REPO_ROOT / "outputs" / "Graphs" / run_manifest.run_id
    run_manifest.set_post_run_phase(
        "graphs",
        "running",
        output_dir=str(output_dir),
        formats=formats,
    )
    command = [
        sys.executable,
        str(SCRIPTS_ROOT / "generate_run_graphs.py"),
        "--run-id",
        run_manifest.run_id,
        "--formats",
        formats,
    ]
    result = _run_bounded_postrun_command(
        command,
        phase_name="graphs",
        attempts=2,
        timeout_seconds=None,
    )
    if result.returncode != 0:
        error = _tail_text(result.stderr or result.stdout)
        run_manifest.set_post_run_phase(
            "graphs",
            "failed",
            output_dir=str(output_dir),
            last_error=error,
            recoverable=True,
        )
        logger.error("✗ Graph generation failed: %s", error)
        return False
    manifest_path = output_dir / "graphs-manifest.json"
    if not manifest_path.exists():
        run_manifest.set_post_run_phase(
            "graphs",
            "failed",
            output_dir=str(output_dir),
            last_error=f"missing graphs manifest: {manifest_path}",
            recoverable=True,
        )
        return False
    graph_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated_count = len(graph_manifest.get("generated_outputs") or [])
    warnings = graph_manifest.get("warnings") if isinstance(graph_manifest.get("warnings"), list) else []
    run_manifest.set_status(
        "running",
        graphs={
            "status": "complete",
            "output_dir": str(output_dir),
            "manifest_path": str(manifest_path),
            "generated_count": int(generated_count),
            "warnings": warnings,
            "validation_status": "complete",
        },
    )
    run_manifest.set_post_run_phase(
        "graphs",
        "complete",
        output_dir=str(output_dir),
        manifest_path=str(manifest_path),
        generated_count=int(generated_count),
        warnings=warnings,
        validation_status="complete",
    )
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run complete SIB analysis pipeline for Guadeloupe, Martinique, and Saint-Barthélemy"
    )
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=1200,
        help="Number of dynamic hazard tracks (default: 1200)"
    )
    parser.add_argument(
        "--track-sample-manifest",
        default=None,
        help=(
            "Optional prefabricated weighted track sample manifest. "
            "When provided, the manifest track selection takes precedence over nearest-track capping."
        ),
    )
    parser.add_argument(
        "--territories",
        default="both",
        help="Which territories to analyze: gua, mar, stb, both, all (default: both)"
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Skip deployment step"
    )
    parser.add_argument(
        "--repair-legacy-scientific-inputs",
        action="store_true",
        help=(
            "Repair archived/pre-V4 runs by allowing the heavy scientific graph-input "
            "reconstruction during publication. Do not use for new V4 runs."
        ),
    )
    parser.add_argument(
        "--require-legacy-web",
        action="store_true",
        help=(
            "Make the legacy page-analysis/frontend adapter mandatory for run success. "
            "By default, scientific publication and graphs define success."
        ),
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
        help="Removed in Lot F; scientific runs now fail explicitly on incomplete multi-hazard execution",
    )
    parser.add_argument(
        "--resume-run-id",
        type=str,
        default=None,
        help="Resume a previous sharded run from outputs/complete-analysis-runs/<run_id> (or use 'latest')",
    )
    parser.add_argument(
        "--abort-on-sighup",
        action="store_true",
        help="Treat SIGHUP as a fatal interrupt instead of keeping the run alive after terminal disconnects",
    )
    parser.add_argument(
        "--scenario-pack",
        type=str,
        default=None,
        help="Path to a JSON sensitivity scenario pack generated from the workbook extractor",
    )
    parser.add_argument(
        "--scenario-id",
        type=str,
        default=None,
        help="Scenario identifier inside the sensitivity scenario pack",
    )
    
    args = parser.parse_args()
    try:
        requested_territories = parse_territory_selection(str(args.territories), default="both")
    except ValueError as exc:
        parser.error(str(exc))
    if args.allow_degraded_components:
        parser.error("--allow-degraded-components has been removed; scientific runs must remain strict multi-hazard")
    if bool(args.scenario_pack) != bool(args.scenario_id):
        parser.error("--scenario-pack and --scenario-id must be provided together")

    scenario: SensitivityScenario | None = None
    if args.scenario_pack and args.scenario_id:
        scenario = resolve_scenario_from_pack(args.scenario_pack, args.scenario_id)

    resume_enabled = bool(args.resume_run_id)
    existing_manifest_payload: dict[str, Any] | None = None
    if resume_enabled:
        resume_run_id = _resolve_resume_run_id(str(args.resume_run_id))
        existing_manifest_payload = _load_existing_run_manifest_payload(resume_run_id)
    else:
        resume_run_id = ""

    resolved_args, resume_warnings = _resolve_resume_runtime_parameters(
        args=args,
        existing_manifest=existing_manifest_payload,
        scenario=scenario,
    )

    effective_settings = _build_complete_analysis_settings(
        dynamic_max_tracks=int(resolved_args["dynamic_max_tracks"]),
        track_sample_manifest_path=resolved_args.get("track_sample_manifest"),
        memory_budget_gb=float(resolved_args["memory_budget_gb"]),
        max_points_per_shard=int(resolved_args["max_points_per_shard"]),
        min_points_per_shard=int(resolved_args["min_points_per_shard"]),
        allow_degraded_components=bool(args.allow_degraded_components),
        scenario=scenario,
    )

    territories = list(resolved_args["territories"])
    
    logger.info("=" * 60)
    logger.info(f"SIB Complete Analysis Runner")
    for warning in resume_warnings:
        logger.warning("%s", warning)
    logger.info(
        "Parameters: dynamic_max_tracks=%s (requested=%s), track_sample_manifest=%s, territories=%s, memory_budget_gb=%.2f, max_points_per_shard=%s, min_points_per_shard=%s, strict_components=%s, scenario_id=%s",
        int(effective_settings.hazard_dynamic_max_tracks),
        int(resolved_args["requested_dynamic_max_tracks"]),
        str(effective_settings.hazard_track_sample_manifest_path) if effective_settings.hazard_track_sample_manifest_path else "none",
        territories,
        float(resolved_args["memory_budget_gb"]),
        int(effective_settings.climada_max_points_per_shard),
        int(resolved_args["min_points_per_shard"]),
        not bool(args.allow_degraded_components),
        scenario.scenario_id if scenario is not None else None,
    )
    logger.info("=" * 60)
    
    parameters = {
        "dynamic_max_tracks": int(effective_settings.hazard_dynamic_max_tracks),
        "requested_dynamic_max_tracks": int(resolved_args["requested_dynamic_max_tracks"]),
        "territories": list(territories),
        "no_deploy": bool(args.no_deploy),
        "repair_legacy_scientific_inputs": bool(args.repair_legacy_scientific_inputs),
        "require_legacy_web": bool(args.require_legacy_web),
        "memory_budget_gb": float(resolved_args["memory_budget_gb"]),
        "max_points_per_shard": int(effective_settings.climada_max_points_per_shard),
        "min_points_per_shard": int(resolved_args["min_points_per_shard"]),
        "allow_degraded_components": bool(args.allow_degraded_components),
        "sampling_spacing_m": float(effective_settings.default_sampling_spacing_m),
        "territory_grid_deg": float(effective_settings.territory_grid_deg),
        "climada_max_points_per_feature": int(effective_settings.climada_max_points_per_feature),
        "track_sample_manifest": (
            str(effective_settings.hazard_track_sample_manifest_path)
            if effective_settings.hazard_track_sample_manifest_path
            else None
        ),
        **scenario_manifest_fields(scenario),
    }
    publication_policy = publication_policy_for_requested_tracks(
        parameters.get("requested_dynamic_max_tracks")
    )
    if resume_enabled:
        run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL, run_id=resume_run_id)
        run_manifest = RunManifest.open_existing(RUN_OUTPUTS_DIR, resume_run_id, parameters)
        run_manifest.set_status(
            "running",
            finished_at=None,
            resumed_at=datetime.now(timezone.utc).isoformat(),
            resume_invocation={
                "dynamic_max_tracks": int(resolved_args["dynamic_max_tracks"]),
                "requested_dynamic_max_tracks": int(resolved_args["requested_dynamic_max_tracks"]),
                "territories": territories,
                "no_deploy": bool(args.no_deploy),
                "repair_legacy_scientific_inputs": bool(args.repair_legacy_scientific_inputs),
                "require_legacy_web": bool(args.require_legacy_web),
                "memory_budget_gb": float(resolved_args["memory_budget_gb"]),
                "max_points_per_shard": int(effective_settings.climada_max_points_per_shard),
                "min_points_per_shard": int(resolved_args["min_points_per_shard"]),
                "allow_degraded_components": bool(args.allow_degraded_components),
                "sampling_spacing_m": float(effective_settings.default_sampling_spacing_m),
                "territory_grid_deg": float(effective_settings.territory_grid_deg),
                "climada_max_points_per_feature": int(effective_settings.climada_max_points_per_feature),
                "track_sample_manifest": (
                    str(effective_settings.hazard_track_sample_manifest_path)
                    if effective_settings.hazard_track_sample_manifest_path
                    else None
                ),
                **scenario_manifest_fields(scenario),
            },
            publication=publication_policy,
        )
    else:
        run_logger = RunLogger(JOURNAL_MD, JOURNAL_JSONL)
        run_manifest = RunManifest(
            RUN_OUTPUTS_DIR,
            run_logger.run_id,
            parameters=parameters,
        )
        run_manifest.set_status("running", publication=publication_policy)
    if not bool(publication_policy.get("eligible")):
        logger.info(
            "Publication policy: auto-deploy disabled for this run (%s; minimum publication-safe tracks=%s)",
            publication_policy.get("reason"),
            int(MIN_PUBLICATION_DYNAMIC_MAX_TRACKS),
        )
    termination_guard = RunTerminationGuard(
        run_logger,
        run_manifest,
        abort_on_sighup=bool(args.abort_on_sighup),
    )
    run_logger.log_event(
        "resume" if resume_enabled else "start",
        status="initiated",
        dynamic_max_tracks=int(effective_settings.hazard_dynamic_max_tracks),
        requested_dynamic_max_tracks=int(resolved_args["requested_dynamic_max_tracks"]),
        territories=territories,
        manifest_path=str(run_manifest.manifest_path),
        sampling_spacing_m=float(effective_settings.default_sampling_spacing_m),
        territory_grid_deg=float(effective_settings.territory_grid_deg),
        climada_max_points_per_feature=int(effective_settings.climada_max_points_per_feature),
        track_sample_manifest=(
            str(effective_settings.hazard_track_sample_manifest_path)
            if effective_settings.hazard_track_sample_manifest_path
            else None
        ),
        publication_eligible=bool(publication_policy.get("eligible")),
        min_publication_dynamic_max_tracks=int(publication_policy.get("min_dynamic_max_tracks") or 0),
        **scenario_manifest_fields(scenario),
    )
    
    results = {}
    rerun_territories: list[str] = []
    for territory in territories:
        resume_dynamic_hazard_point_cap = (
            _infer_resume_dynamic_hazard_point_cap(run_manifest, territory)
            if resume_enabled
            else None
        )
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
            int(resolved_args["requested_dynamic_max_tracks"]),
            run_logger,
            run_manifest,
            track_sample_manifest_path=resolved_args.get("track_sample_manifest"),
            memory_budget_gb=float(resolved_args["memory_budget_gb"]),
            max_points_per_shard=int(effective_settings.climada_max_points_per_shard),
            min_points_per_shard=int(resolved_args["min_points_per_shard"]),
            allow_degraded_components=bool(args.allow_degraded_components),
            resume_enabled=resume_enabled,
            resume_dynamic_hazard_point_cap=resume_dynamic_hazard_point_cap,
            materialize_scientific_graph_inputs=bool(args.repair_legacy_scientific_inputs),
            scenario=scenario,
        )
        if result:
            results[territory] = result
            rerun_territories.append(territory)

    frontend_artifacts_success = False
    frontend_status = ((run_manifest.data.get("frontend_artifacts") or {}).get("status") if isinstance(run_manifest.data, dict) else None)
    territories_for_frontend = list(rerun_territories)
    if results and not territories_for_frontend and str(frontend_status or "") != "complete":
        territories_for_frontend = list(results.keys())

    frontend_required = (
        _frontend_artifacts_required(scenario)
        and not bool(args.repair_legacy_scientific_inputs)
    )
    if results and territories_for_frontend and frontend_required:
        frontend_supervision_journal = frontend_supervision_journal_path(run_manifest.run_dir)
        try:
            archived_frontend_artifacts = recover_completed_frontend_artifacts_from_journal(
                run_manifest,
                territories_for_frontend,
                supervision_journal=frontend_supervision_journal,
            )
        except Exception as exc:
            archived_frontend_artifacts = None
            logger.info(
                "Completed frontend journal could not be reused for %s; rebuilding frontend artefacts: %s",
                ", ".join(territories_for_frontend),
                exc,
            )
        if archived_frontend_artifacts is not None:
            frontend_artifacts_success = True
            logger.info(
                "Recovered completed frontend artefacts for %s from supervision journal %s",
                ", ".join(territories_for_frontend),
                frontend_supervision_journal,
            )
            run_logger.log_event(
                "frontend_artifacts",
                territories=territories_for_frontend,
                status="complete",
                recovered_from_supervision_journal=True,
                supervision_journal=str(frontend_supervision_journal),
            )

        if (
            not frontend_artifacts_success
            and _should_exec_fresh_frontend_resume(
                calculation_complete=len(results) == len(territories),
                frontend_required=frontend_required,
                territories_for_frontend=territories_for_frontend,
            )
        ):
            resume_command = _build_fresh_frontend_resume_command(
                args=args,
                resolved_args=resolved_args,
                effective_settings=effective_settings,
                run_id=run_manifest.run_id,
            )
            compaction = _compact_process_memory()
            logger.info(
                "Restarting in fresh resume mode before frontend artefacts to release impact-calculation memory: %s",
                " ".join(resume_command),
            )
            logger.info(
                "Pre-frontend exec memory compaction: rss_kb_before=%s rss_kb_after=%s mem_available_kb_before=%s mem_available_kb_after=%s malloc_trim_supported=%s malloc_trim_result=%s gc_collected=%s",
                compaction.get("rss_kb_before"),
                compaction.get("rss_kb_after"),
                compaction.get("mem_available_kb_before"),
                compaction.get("mem_available_kb_after"),
                compaction.get("malloc_trim_supported"),
                compaction.get("malloc_trim_result"),
                compaction.get("gc_collected"),
            )
            run_logger.log_event(
                "frontend_resume_exec",
                territories=territories_for_frontend,
                status="starting",
                command=resume_command,
                memory_compaction=compaction,
            )
            run_manifest.set_status(
                "running",
                frontend_artifacts={
                    "status": "pending_fresh_resume",
                    "territories": territories_for_frontend,
                    "reason": "release impact-calculation memory before frontend rebuild",
                    "command": resume_command,
                    "memory_compaction": compaction,
                },
            )
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                ENV_FRESH_FRONTEND_RESUME: "1",
            }
            try:
                os.execvpe(resume_command[0], resume_command, env)
            except OSError as exc:
                logger.error("Fresh frontend resume exec failed; continuing in current process: %s", exc)
        if not frontend_artifacts_success:
            logger.info("Rebuilding case-study frontend artefacts...")
            artefact_start = time.time()
            gc.collect()
            run_manifest.set_status(
                "running",
                frontend_artifacts={
                    "status": "running",
                    "territories": territories_for_frontend,
                    "supervision_journal": str(frontend_supervision_journal),
                },
            )
            write_frontend_supervision_event(
                frontend_supervision_journal,
                actor="parent",
                event="frontend_phase_started",
                run_id=run_manifest.run_id,
                parent_pid=os.getpid(),
                territories=list(territories_for_frontend),
            )
            try:
                frontend_dynamic_max_tracks = int(resolved_args["requested_dynamic_max_tracks"])
                rebuild_case_study_frontend_artifacts(
                    territories_for_frontend,
                    frontend_dynamic_max_tracks,
                    run_id=run_manifest.run_id,
                    supervision_journal=frontend_supervision_journal,
                )
                write_frontend_supervision_event(
                    frontend_supervision_journal,
                    actor="parent",
                    event="frontend_snapshot_started",
                    run_id=run_manifest.run_id,
                    territories=list(territories_for_frontend),
                )
                archived_frontend_artifacts = snapshot_frontend_artifacts_for_run(
                    run_manifest,
                    territories_for_frontend,
                    min_mtime_epoch=artefact_start,
                )
                frontend_artifacts_success = True
                artefact_time = time.time() - artefact_start
                logger.info(f"✓ Frontend artefacts rebuilt in {artefact_time:.1f}s")
                write_frontend_supervision_event(
                    frontend_supervision_journal,
                    actor="parent",
                    event="frontend_rebuild_completed",
                    run_id=run_manifest.run_id,
                    parent_pid=os.getpid(),
                    territories=list(territories_for_frontend),
                    duration_seconds=int(artefact_time),
                    archived_territories=sorted(archived_frontend_artifacts.keys()),
                )
                run_logger.log_event(
                    "frontend_artifacts",
                    territories=territories_for_frontend,
                    duration_seconds=int(artefact_time),
                    status="complete",
                    supervision_journal=str(frontend_supervision_journal),
                )
                run_manifest.set_status(
                    "running",
                    frontend_artifacts={
                        "status": "complete",
                        "territories": territories_for_frontend,
                        "duration_seconds": int(artefact_time),
                        "archived_files_by_territory": archived_frontend_artifacts,
                        "supervision_journal": str(frontend_supervision_journal),
                    },
                )
            except Exception as exc:
                logger.error(f"✗ Frontend artefact rebuild failed: {exc}", exc_info=True)
                write_frontend_supervision_event(
                    frontend_supervision_journal,
                    actor="parent",
                    event="frontend_rebuild_failed",
                    run_id=run_manifest.run_id,
                    parent_pid=os.getpid(),
                    territories=list(territories_for_frontend),
                    error=str(exc),
                )
                run_logger.log_event(
                    "frontend_artifacts",
                    territories=territories_for_frontend,
                    error=str(exc),
                    status="failed",
                    supervision_journal=str(frontend_supervision_journal),
                )
                run_manifest.set_status(
                    "running",
                    frontend_artifacts={
                        "status": "failed",
                        "territories": territories_for_frontend,
                        "error": str(exc),
                        "supervision_journal": str(frontend_supervision_journal),
                    },
                )
    elif results and not frontend_required:
        frontend_artifacts_success = True
        if bool(args.repair_legacy_scientific_inputs):
            frontend_skip_reason = "legacy frontend artefact rebuild is skipped during explicit legacy scientific repair"
        else:
            frontend_skip_reason = "frontend artefact rebuild is skipped for sensitivity scenario runs"
        run_manifest.set_status(
            "running",
            frontend_artifacts={
                "status": "skipped",
                "territories": list(results.keys()),
                "reason": frontend_skip_reason,
            },
        )
        run_logger.log_event(
            "frontend_artifacts",
            territories=list(results.keys()),
            status="skipped",
            reason=frontend_skip_reason,
        )
    elif results:
        frontend_artifacts_success = str(frontend_status or "") == "complete"
        if frontend_artifacts_success and frontend_required:
            try:
                collect_archived_run_files(run_manifest.run_id, list(results.keys()))
            except Exception as exc:
                reason = f"archived frontend artefacts are incomplete: {exc}"
                frontend_artifacts_success = False
                logger.error("✗ Frontend artefact snapshot is incomplete: %s", exc)
                run_logger.log_event(
                    "frontend_artifacts",
                    territories=list(results.keys()),
                    status="failed",
                    reason=reason,
                )
                run_manifest.set_status(
                    "running",
                    frontend_artifacts={
                        "status": "failed",
                        "territories": list(results.keys()),
                        "error": reason,
                    },
                )
    
    scientific_publication_success = False
    graphs_success = False
    post_run_territories = list(results.keys())
    calculation_complete = len(results) == len(territories)
    frontend_ready_for_post_run = (not frontend_required) or bool(frontend_artifacts_success)
    if results and calculation_complete and frontend_ready_for_post_run:
        post_run_phases = run_manifest.data.get("post_run_phases") if isinstance(run_manifest.data, dict) else {}
        scientific_phase = (
            post_run_phases.get("scientific_publication")
            if isinstance(post_run_phases, dict)
            else None
        )
        if isinstance(scientific_phase, dict) and str(scientific_phase.get("status") or "") == "complete":
            scientific_publication_success = True
            logger.info("Skipping scientific_publication: already complete in manifest %s", run_manifest.run_id)
        else:
            scientific_publication_success = build_scientific_publication_artifacts(
                run_manifest,
                post_run_territories,
                repair_legacy_scientific_inputs=bool(args.repair_legacy_scientific_inputs),
            )

        post_run_phases = run_manifest.data.get("post_run_phases") if isinstance(run_manifest.data, dict) else {}
        graphs_phase = post_run_phases.get("graphs") if isinstance(post_run_phases, dict) else None
        if scientific_publication_success:
            if isinstance(graphs_phase, dict) and str(graphs_phase.get("status") or "") == "complete":
                graphs_success = True
                logger.info("Skipping graphs: already complete in manifest %s", run_manifest.run_id)
            else:
                graphs_success = generate_graph_artifacts_for_run(run_manifest)
        else:
            run_manifest.set_post_run_phase(
                "graphs",
                "skipped",
                reason="scientific_publication failed or did not complete",
            )
    elif results and calculation_complete:
        reason = "frontend artefact rebuild failed or archived graph inputs are incomplete"
        run_manifest.set_post_run_phase(
            "scientific_publication",
            "skipped",
            territories=post_run_territories,
            reason=reason,
        )
        run_manifest.set_post_run_phase(
            "graphs",
            "skipped",
            reason=reason,
        )
    elif results:
        run_manifest.set_post_run_phase(
            "scientific_publication",
            "skipped",
            territories=post_run_territories,
            reason="not all requested territories completed",
        )
        run_manifest.set_post_run_phase(
            "graphs",
            "skipped",
            reason="not all requested territories completed",
        )

    legacy_frontend_ok = (not bool(args.require_legacy_web)) or bool(frontend_artifacts_success)

    # Deploy if requested and successful
    deploy_success = False
    deploy_required = (not bool(args.no_deploy)) and bool(publication_policy.get("eligible"))
    if not args.no_deploy and results and calculation_complete and scientific_publication_success and graphs_success and legacy_frontend_ok:
        if bool(publication_policy.get("eligible")):
            run_manifest.set_status("running", deploy={"status": "running"})
            deploy_success = deploy_results()
            run_logger.log_event("deploy", status="complete" if deploy_success else "failed")
            run_manifest.set_status(
                "running",
                deploy={"status": "complete" if deploy_success else "failed"},
            )
        else:
            deploy_reason = str(publication_policy.get("reason") or "run is not publication-eligible")
            logger.info("Skipping deploy: %s", deploy_reason)
            run_logger.log_event(
                "deploy",
                status="skipped",
                reason=deploy_reason,
                requested_dynamic_max_tracks=int(
                    publication_policy.get("requested_dynamic_max_tracks") or 0
                ),
                min_publication_dynamic_max_tracks=int(
                    publication_policy.get("min_dynamic_max_tracks") or 0
                ),
            )
            run_manifest.set_status(
                "running",
                publication=publication_policy,
                deploy={
                    "status": "skipped",
                    "reason": deploy_reason,
                    "requested_dynamic_max_tracks": int(
                        publication_policy.get("requested_dynamic_max_tracks") or 0
                    ),
                    "min_dynamic_max_tracks": int(
                        publication_policy.get("min_dynamic_max_tracks") or 0
                    ),
                },
            )
    elif args.no_deploy:
        run_manifest.set_status("running", deploy={"status": "skipped", "reason": "--no-deploy"})
    elif not bool(publication_policy.get("eligible")):
        deploy_reason = str(publication_policy.get("reason") or "run is not publication-eligible")
        run_manifest.set_status(
            "running",
            deploy={"status": "skipped", "reason": deploy_reason},
        )
    elif results:
        run_manifest.set_status(
            "running",
            deploy={
                "status": "skipped",
                "reason": "scientific publication or graph generation did not complete",
            },
        )
    
    # Finalize logging
    deploy_ok = bool(args.no_deploy) or (not deploy_required) or bool(deploy_success)
    post_run_ok = bool(scientific_publication_success) and bool(graphs_success)
    publication_ok = (
        bool(post_run_ok)
        and bool(legacy_frontend_ok)
        and bool(deploy_ok)
    )
    if calculation_complete and publication_ok:
        final_status = "success"
    elif results and len(results) < len(territories) and len(territories) > 1:
        final_status = "partial"
    else:
        final_status = "failed"
    run_logger.finalize(
        status=final_status,
        territories_completed=len(results),
        total_assets=sum(r.get("assets", 0) for r in results.values()),
        deployed=deploy_success,
    )
    finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_manifest.set_status(
        final_status,
        territories_completed=len(results),
        total_assets=sum(r.get("assets", 0) for r in results.values()),
        deployed=bool(deploy_success),
        frontend_artifacts_success=bool(frontend_artifacts_success),
        scientific_publication_success=bool(scientific_publication_success),
        graphs_success=bool(graphs_success),
        legacy_frontend_required=bool(args.require_legacy_web),
        legacy_frontend_ok=bool(legacy_frontend_ok),
        deploy_required=bool(deploy_required),
        deploy_ok=bool(deploy_ok),
        finished_at=finished_at,
    )
    termination_guard.mark_complete()

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
    
    return 0 if final_status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
