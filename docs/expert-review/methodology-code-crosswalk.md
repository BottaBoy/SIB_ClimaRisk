# Methodology -> Code Crosswalk (Backend + Critical Scripts)

Last updated: **2026-04-22**

## Mapping Rules
- Methodology reference: `docs/expert-review/note-backend-calculatoire.en.md`
- Code scope: `backend/app`, `backend/scripts`, and critical root scripts in `scripts/`
- This document is an audit navigation map (implementation truth remains the original source files).

## Section-by-Section Traceability

| Methodology topic | Main implementation anchors | What to verify |
|---|---|---|
| 1) Objective and engine policy | `backend/app/risk_engine/impact_runner.py` (`compute_impacts`, `compute_impacts_fallback`) | Default CLIMADA path, explicit fallback gating, deterministic fallback behavior. |
| 2) API and orchestration flow | `backend/app/main.py`, `backend/app/job_runner.py`, `backend/app/risk_engine/pipeline.py` | Request -> queue -> pipeline ordering and job-state transitions. |
| 3) Exposure ingestion/normalization | `backend/app/risk_engine/exposure_ingest.py` | Category aliases, strict validation, parsing behavior by format (CSV/XLSX/GeoJSON/GPKG/drawn). |
| 4) Exposure sampling and conversion | `backend/app/risk_engine/exposure_to_climada.py` | CRS transforms, line/polygon sampling, point caps, value conservation. |
| 5) Hazard loading and source policy | `backend/app/risk_engine/hazard_loader.py`, `backend/app/config.py` | Dynamic parquet preference, HDF5 fallback behavior, source metadata traceability. |
| 6) Vulnerability curves (wind/rain/surge/landslide) | `backend/app/risk_engine/impact_functions.py`, `backend/app/risk_engine/impact_functions_multi_hazard.py`, `backend/app/risk_engine/impact_functions_landslide.py` | Curve provenance, asset-type mappings, D2 workbook dependencies, profile consistency. |
| 7) CLIMADA direct impacts and component composition | `backend/app/risk_engine/climada_engine.py` (`run_climada_direct_impacts`) | Frequency normalization, component-level execution (`wind`,`rain`,`surge`), strict vs degraded component policy. |
| 8) Electricity -> water interdependency | `backend/app/risk_engine/interdependency.py` | Health computation, local/nearest/global electrical-health resolution, uplift and caps. |
| 9) Social impact enrichment | `backend/app/risk_engine/population_loader.py`, `backend/app/risk_engine/social_impact.py`, `backend/app/risk_engine/impact_runner.py` | Population loading robustness, territory-level metrics, payload integration safeguards. |
| 10) Territory/portfolio aggregation and graphs | `backend/app/risk_engine/impact_runner.py` | `risk_index`, direct/indirect split, component health blocks, graph semantic continuity. |
| 11) Output contract and artifacts | `backend/app/risk_engine/analysis_export.py` | Payload schema continuity, additive extensions, CSV/JSON artifact generation. |
| 12) Sensitivity scenario handling | `backend/app/risk_engine/sensitivity_scenarios.py`, `scripts/run_sensitivity_analysis.py`, `scripts/export_sensitivity_matrix.py` | Scenario-pack validation, allowed overrides, manifest fields for reproducibility. |
| 13) Landslide computation path (specialized) | `backend/app/risk_engine/landslide_engine.py`, `scripts/landslide_poc_guadeloupe.py`, `scripts/build_case_study_landslide_maps.py` | Raster-to-hazard conversion assumptions, event sampling controls, explicit scope limits vs production path. |
| 14) End-to-end complete run scripts | `scripts/run_complete_analysis.py`, `scripts/build_guadeloupe_complete_analysis.py`, `scripts/rerun_case_studies_light.py` | GUA+MQ execution reproducibility, non-deploy mode, frontend artifact rebuild behavior. |
| 15) Runtime quality checks and debt | `scripts/audit_quick_checks.sh` | Current known non-passing state (`ruff` failures as of 2026-04-22). |

## Critical Function Anchors (Quick Jump)
- `backend/app/main.py`: `health`, `hazard_coverage`, `vulnerability_curves`, `create_run`
- `backend/app/job_runner.py`: `JobProcessor._process_one`
- `backend/app/risk_engine/pipeline.py`: `run_job_pipeline`
- `backend/app/risk_engine/impact_runner.py`: `compute_impacts`, `_compute_impacts_climada`, `compute_impacts_fallback`
- `backend/app/risk_engine/climada_engine.py`: `run_climada_direct_impacts`
- `backend/app/risk_engine/interdependency.py`: `aggregate_impacts_with_interdependency`
- `backend/app/risk_engine/social_impact.py`: `calculate_social_impact_metrics`, `aggregate_social_summary`
- `backend/app/risk_engine/sensitivity_scenarios.py`: `resolve_scenario_from_pack`, `apply_settings_overrides`
- `backend/app/risk_engine/analysis_export.py`: `build_result_payload`

## Root Script -> Backend/Artifacts Mapping

| Root script | Backend dependencies | Primary outputs |
|---|---|---|
| `scripts/run_complete_analysis.py` | `impact_runner.py`, `analysis_export.py`, `sensitivity_scenarios.py` | `outputs/complete-analysis-runs/*`, `web/data/*-complete-analysis.json`, rebuilt frontend artifacts |
| `scripts/build_guadeloupe_complete_analysis.py` | backend API-compatible compute path | single territory complete-analysis JSON |
| `scripts/rerun_case_studies_light.py` | multi script orchestration + backend config | `web/data/*-wind-maps.json`, `web/data/*-multi-hazard-proxy.json`, `web/data/*-page1-analysis.json`, `web/data/*-page2-analysis.json` |
| `scripts/build_case_study_multi_hazard_proxy.py` | `climada_engine.py`, `hazard_loader.py`, `impact_functions_multi_hazard.py` | multi-hazard proxy web dataset |
| `scripts/build_guadeloupe_page1_data.py` | `impact_runner.py`, exposure conversion/hazard helpers | page1 analysis + network states |
| `scripts/run_sensitivity_analysis.py` | `sensitivity_scenarios.py` + complete-analysis runner | scenario batch outputs + workbook/matrix exports |

## Fast Path Existence Check
From repository root, to ensure every referenced backend module path exists:

```bash
python3 - <<'PY'
from pathlib import Path
paths = [
    "backend/app/risk_engine/impact_functions_multi_hazard.py",
    "backend/app/risk_engine/impact_functions_landslide.py",
    "backend/app/risk_engine/landslide_engine.py",
    "backend/app/risk_engine/population_loader.py",
    "backend/app/risk_engine/social_impact.py",
    "backend/app/risk_engine/sensitivity_scenarios.py",
]
missing = [p for p in paths if not Path(p).exists()]
print("OK" if not missing else "MISSING:\n" + "\n".join(missing))
PY
```
