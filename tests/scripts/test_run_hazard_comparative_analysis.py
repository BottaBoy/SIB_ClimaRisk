from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import run_hazard_comparative_analysis


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _catalog_payload(root: Path) -> dict:
    catalogs: dict[str, dict[str, dict[str, object]]] = {}
    for basin_code, basin_id in (("NA", 1), ("SI", 3), ("SP", 4)):
        basin_dir = root / basin_code.lower()
        catalogs[basin_code] = {}
        for provider in ("storm", "storm_cmcc"):
            parquet_path = basin_dir / f"{provider}.parquet"
            manifest_path = basin_dir / f"{provider}.manifest.json"
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            parquet_path.write_text("parquet-placeholder", encoding="utf-8")
            _write_json(
                manifest_path,
                {
                    "basin_code": basin_code,
                    "basin_id": basin_id,
                    "provider": provider,
                    "row_count": 8,
                    "track_count": 3,
                    "track_identity_version": 2,
                    "years_covered": 1000,
                    "year_min": 0,
                    "year_max": 999,
                    "source_files": [],
                },
            )
            catalogs[basin_code][provider] = {
                "provider": provider,
                "provider_label": provider.upper(),
                "basin_id": basin_id,
                "parquet_path": str(parquet_path),
                "manifest_path": str(manifest_path),
                "wind_unit_in": "m/s",
                "radius_unit_in": "km",
                "timestep_hours": 3,
            }
    return {"meta": {"catalog_version": 1}, "catalogs": catalogs}


def _scenario_payload() -> dict:
    return {
        "meta": {"scenario_version": 1},
        "scenarios": {
            "storm": {
                "label": "STORM",
                "track_catalog_provider": "storm",
                "components": {
                    "wind": {"enabled": True, "source": "track_catalog", "hazard_class": "TC"},
                    "rain": {"enabled": True, "source": "track_catalog", "hazard_class": "TCRain"},
                    "surge": {
                        "enabled": True,
                        "source": "track_catalog",
                        "hazard_class": "TCSurgeBathtub",
                        "topography_source": "canonical_copernicus",
                    },
                    "landslide": {
                        "enabled": True,
                        "source": "native_raster_pair",
                        "hazard_class": "LS",
                        "combination_mode": "concatenate_native_hazards",
                        "raster_fields": ["earthquake_path", "precip_current_path"],
                    },
                },
            },
            "storm_cmcc": {
                "label": "STORM_CMCC",
                "track_catalog_provider": "storm_cmcc",
                "components": {
                    "wind": {"enabled": True, "source": "track_catalog", "hazard_class": "TC"},
                    "rain": {"enabled": True, "source": "track_catalog", "hazard_class": "TCRain"},
                    "surge": {
                        "enabled": True,
                        "source": "track_catalog",
                        "hazard_class": "TCSurgeBathtub",
                        "topography_source": "canonical_copernicus",
                    },
                    "landslide": {
                        "enabled": True,
                        "source": "native_raster_pair",
                        "hazard_class": "LS",
                        "combination_mode": "concatenate_native_hazards",
                        "raster_fields": ["earthquake_path", "precip_ssp585_path"],
                    },
                },
            },
        },
    }


def _registry_payload(tmp_path: Path) -> dict:
    adm0_path = tmp_path / "adm0.geojson"
    adm0_path.write_text("{}", encoding="utf-8")
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")
    landslide_root = tmp_path / "landslide"
    landslide_root.mkdir(parents=True, exist_ok=True)
    for name in ("eq.tif", "cur.tif", "ssp585.tif"):
        (landslide_root / name).write_text(name, encoding="utf-8")
    population_path = tmp_path / "population.tif"
    population_path.write_text("population", encoding="utf-8")
    return {
        "meta": {
            "included_territories": ["demo"],
            "excluded_territories": [],
        },
        "shared_sources": {
            "admin_boundaries_adm0_path": str(adm0_path),
            "copernicus_topography_dir": str(topo_path.parent),
            "raw_track_catalogs": {
                "storm_dir": str(tmp_path / "storm"),
                "storm_cmcc_dir": str(tmp_path / "storm_cmcc"),
                "patterns_by_basin": {
                    "NA": {"storm": "na*.txt", "storm_cmcc": "na_cmcc*.txt"},
                    "SI": {"storm": "si*.txt", "storm_cmcc": "si_cmcc*.txt"},
                    "SP": {"storm": "sp*.txt", "storm_cmcc": "sp_cmcc*.txt"},
                },
            },
        },
        "territories": {
            "demo": {
                "label": "Demo",
                "include_in_comparison": True,
                "aliases": ["demo"],
                "storm_basin_code": "NA",
                "comparison_bbox_hint": {
                    "lon_min": -61.2,
                    "lat_min": 15.9,
                    "lon_max": -61.0,
                    "lat_max": 16.1,
                },
                "admin_mask": {
                    "adm0_path": str(adm0_path),
                    "mode": "shared_adm0_plus_bbox_hint",
                },
                "topography": {
                    "canonical_copernicus_path": str(topo_path),
                    "copernicus_archive_path": str(tmp_path / "Demo_rasters_COP30.tar.gz"),
                    "lot0_status": "ready",
                    "exists_now": True,
                },
                "landslide": {
                    "earthquake_path": str(landslide_root / "eq.tif"),
                    "precip_current_path": str(landslide_root / "cur.tif"),
                    "precip_ssp585_path": str(landslide_root / "ssp585.tif"),
                    "exists_now": True,
                },
                "population": {
                    "path": str(population_path),
                    "required_for_hazard_only": False,
                    "exists_now": True,
                },
            }
        },
    }


def test_run_hazard_comparative_analysis_writes_manifest_and_events(tmp_path: Path) -> None:
    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())

    manifest = run_hazard_comparative_analysis.run_hazard_comparative_analysis(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
        plan_only=True,
    )

    manifest_path = tmp_path / "runs" / "20260522_000000" / "manifest.json"
    latest_path = tmp_path / "runs" / "latest-manifest.json"
    events_path = tmp_path / "runs" / "20260522_000000" / "events.jsonl"

    lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert manifest["status"] == "planned"
    assert manifest_path.exists()
    assert latest_path.exists()
    assert manifest_path.read_text(encoding="utf-8") == latest_path.read_text(encoding="utf-8")
    assert {line["event"] for line in lines} >= {"run_initialized", "territory_planned", "scenario_planned", "run_completed"}
    assert manifest["territories"]["demo"]["status"] == "ready"


def test_run_hazard_comparative_analysis_executes_phase3_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())

    def _fake_materialize(plan: dict, *, dynamic_max_tracks: int | None = None, progress_callback=None):
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "component_completed",
                    "phase": "phase3_hazard_build",
                    "territory": "demo",
                    "scenario": "storm",
                    "component": "wind",
                    "output_path": str(tmp_path / "runs" / "20260522_000001" / "territories" / "demo" / "hazards" / "storm" / "wind.h5"),
                    "event_count": 3,
                }
            )
        payload = json.loads(json.dumps(plan))
        payload["mode"] = "phase3_hazard_generation"
        payload["status"] = "complete"
        payload.setdefault("contracts", {})["effective_dynamic_max_tracks"] = int(dynamic_max_tracks or 0)
        payload["territories"]["demo"]["status"] = "complete"
        payload["territories"]["demo"].setdefault("phases", {})["phase3_hazard_build"] = {
            "status": "complete"
        }
        payload["territories"]["demo"]["scenarios"]["storm"]["status"] = "complete"
        payload["territories"]["demo"]["scenarios"]["storm"]["components"]["wind"]["status"] = "complete"
        return payload

    def _fake_materialize_metrics(payload: dict, *, progress_callback=None):
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "component_metrics_completed",
                    "phase": "phase4_metric_extraction",
                    "territory": "demo",
                    "scenario": "storm",
                    "component": "wind",
                    "output_path": str(tmp_path / "runs" / "20260522_000001" / "territories" / "demo" / "hazards" / "storm" / "wind.h5"),
                    "metric_event_count": 3,
                }
            )
        executed = json.loads(json.dumps(payload))
        metrics_path = tmp_path / "runs" / "20260522_000001" / "comparison-metrics.json"
        metrics_path.write_text(json.dumps({"status": "complete"}, ensure_ascii=False, indent=2), encoding="utf-8")
        executed["mode"] = "phase4_metric_extraction"
        executed["status"] = "complete"
        executed["comparison_metrics"] = {
            "status": "complete",
            "path": str(metrics_path),
            "territory_count": 1,
            "pairwise_comparison": "storm_vs_storm_cmcc",
        }
        executed["territories"]["demo"].setdefault("phases", {})["phase4_metric_extraction"] = {
            "status": "complete"
        }
        executed["territories"]["demo"]["comparison_metrics"] = {
            "status": "complete",
            "scenarios": {},
            "storm_vs_storm_cmcc": {"status": "complete", "components": {}},
        }
        return executed

    def _fake_materialize_exports(payload: dict, *, progress_callback=None):
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "comparison_tables_completed",
                    "phase": "phase5_export_artifacts",
                    "component_metrics_csv": str(tmp_path / "runs" / "20260522_000001" / "comparison-exports" / "tables" / "component-metrics-long.csv"),
                    "comparison_delta_csv": str(tmp_path / "runs" / "20260522_000001" / "comparison-exports" / "tables" / "storm-vs-storm_cmcc-deltas.csv"),
                    "row_count_component_metrics": 2,
                    "row_count_comparison_deltas": 4,
                }
            )
        executed = json.loads(json.dumps(payload))
        summary_path = tmp_path / "runs" / "20260522_000001" / "comparison-exports" / "summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps({"status": "complete"}, ensure_ascii=False, indent=2), encoding="utf-8")
        executed["mode"] = "phase5_export_artifacts"
        executed["status"] = "complete"
        executed["comparison_exports"] = {
            "status": "complete",
            "summary_path": str(summary_path),
            "table_count": 3,
            "chart_count": 2,
            "plot_metric_keys": ["intensity_max"],
        }
        executed["territories"]["demo"].setdefault("phases", {})["phase5_export_artifacts"] = {
            "status": "complete"
        }
        executed["territories"]["demo"]["comparison_exports"] = {
            "status": "complete",
            "included_in_run_level_exports": True,
            "summary_path": str(summary_path),
        }
        return executed

    def _fake_materialize_report(payload: dict, *, progress_callback=None):
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "comparison_report_completed",
                    "phase": "phase6_html_report",
                    "index_path": str(tmp_path / "runs" / "20260522_000001" / "comparison-exports" / "index.html"),
                    "chart_count": 2,
                }
            )
        executed = json.loads(json.dumps(payload))
        index_path = tmp_path / "runs" / "20260522_000001" / "comparison-exports" / "index.html"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("<html></html>", encoding="utf-8")
        executed["mode"] = "phase6_html_report"
        executed["status"] = "complete"
        executed["comparison_report"] = {
            "status": "complete",
            "index_path": str(index_path),
            "summary_path": str(index_path.parent / "summary.json"),
        }
        executed["territories"]["demo"].setdefault("phases", {})["phase6_html_report"] = {
            "status": "complete"
        }
        executed["territories"]["demo"]["comparison_report"] = {
            "status": "complete",
            "index_path": str(index_path),
        }
        return executed

    monkeypatch.setattr(run_hazard_comparative_analysis, "materialize_hazard_comparison_hazards", _fake_materialize)
    monkeypatch.setattr(run_hazard_comparative_analysis, "materialize_hazard_comparison_metrics", _fake_materialize_metrics)
    monkeypatch.setattr(run_hazard_comparative_analysis, "materialize_hazard_comparison_exports", _fake_materialize_exports)
    monkeypatch.setattr(run_hazard_comparative_analysis, "materialize_hazard_comparison_report", _fake_materialize_report)

    manifest = run_hazard_comparative_analysis.run_hazard_comparative_analysis(
        run_id="20260522_000001",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
        plan_only=False,
        dynamic_max_tracks=9,
    )

    events_path = tmp_path / "runs" / "20260522_000001" / "events.jsonl"
    lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert manifest["status"] == "complete"
    assert manifest["mode"] == "phase6_html_report"
    assert manifest["contracts"]["effective_dynamic_max_tracks"] == 9
    assert {line["event"] for line in lines} >= {"phase3_started", "phase4_started", "phase5_started", "phase6_started", "component_completed", "component_metrics_completed", "comparison_tables_completed", "comparison_report_completed", "run_completed"}
    assert manifest["territories"]["demo"]["status"] == "complete"
    assert manifest["comparison_metrics"]["status"] == "complete"
    assert manifest["comparison_exports"]["status"] == "complete"
    assert manifest["comparison_report"]["status"] == "complete"