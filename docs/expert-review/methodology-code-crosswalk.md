# Methodology -> Code Crosswalk (Backend + Case-Study Scripts)

## Mapping Rules
- Methodology reference: `note-backend-calculatoire.en.md`.
- Code scope: `backend/app` + `backend/scripts` + case-study root scripts under `scripts/`.
- Function line numbers below are from current repository state and serve as direct review anchors.

---

## Section-by-Section Traceability

| Methodology section | Main implementation anchors | What to verify |
|---|---|---|
| 1) Objective | `backend/app/risk_engine/impact_runner.py` (`compute_impacts`, `compute_impacts_fallback`) | Engine selection (`climada` vs `fallback`) and fallback gating behavior. |
| 2) Architecture and flow | `backend/app/main.py`, `backend/app/job_runner.py`, `backend/app/risk_engine/pipeline.py` | API -> queue -> pipeline chain and stage transitions. |
| 3) Exposure input normalization | `backend/app/risk_engine/exposure_ingest.py` (`ingest_uploaded_exposure`, `_ingest_csv`, `_ingest_geojson`, `_ingest_xlsx`, `_ingest_gpkg`, `ingest_drawn_geojson`) | File-format handling, category aliases, strictness of validation errors. |
| 4) Exposure -> CLIMADA conversion | `backend/app/risk_engine/exposure_to_climada.py` (`build_climada_exposure`, `_sample_line_points`, `_sample_polygon_points`, `_territory_for_coords`) | CRS transformation chain, point sampling strategy, value splitting, territory assignment. |
| 5) CLIMADA direct impacts | `backend/app/risk_engine/climada_engine.py` (`run_climada_direct_impacts`, `_compute_pml`, `_compute_tvar_95`, `_extract_top_events`) | Hazard loading integration, annual frequency normalization effects, metric extraction consistency. |
| 6) States + health formula | `backend/app/risk_engine/interdependency.py` (`_state_from_damage_ratio`, `_health_from_bucket`, `_summarize_component_health`) and fallback logic in `impact_runner.py` | Thresholds (`0.05/0.15/0.35`) and `health` formula implementation details. |
| 7) Electricity -> water propagation | `backend/app/risk_engine/interdependency.py` (`aggregate_impacts_with_interdependency`, `_resolve_electric_health`, `_dependency_state_from_elec_health`) | Local/nearest/global health resolution, uplift factors, final EAI cap. |
| 8) Territory + portfolio aggregation | `backend/app/risk_engine/interdependency.py`, `backend/app/risk_engine/impact_runner.py` | `risk_index` computation, direct/indirect split, portfolio metric assembly. |
| 9) JSON contract and compatibility | `backend/app/risk_engine/analysis_export.py` (`build_result_payload`) | Top-level schema continuity and additive extension policy. |
| 10) Graph payload (`graphs`) | `backend/app/risk_engine/impact_runner.py` (`_build_climada_graphs`, `_build_fallback_graphs`) | Graph key continuity and metric semantics used by frontend. |
| 11) Runtime configuration | `backend/app/config.py` (`Settings`, `load_settings`) and `backend/app/main.py` (`/api/v1/health`) | Environment-variable defaults, runtime toggles, exposed health metadata. |
| 12) OFB conservative valuation | Ingestion/build logic reflected in normalized `value_eur` handling (`exposure_ingest.py`) and downstream impact usage | Verify valuation assumptions are treated as input data policy, not hidden recalculation in impact core. |
| 13) Guadeloupe preparation scripts | `backend/scripts/run_backoffice_sample.py`, `backend/scripts/cleanup_expired_jobs.py`, root `scripts/build_guadeloupe_*.py`, `scripts/rerun_case_studies_light.py` | Verify reproducibility and consistency between generated web artifacts and latest backend run IDs. |
| 14) NA visual update note | `scripts/build_na_wind_leaflet_overlays.py`, `scripts/render_na_wind_static_maps.py`, `scripts/build_wind_speed_comparison_doc.py` | Confirm output-only transformations preserve backend hazard metrics and units. |
| 15) Known limits | `interdependency.py`, `exposure_to_climada.py`, `impact_runner.py` | Limits are explicit and aligned with documented assumptions. |
| 16) STORM sources | `backend/app/risk_engine/hazard_loader.py`, `backend/app/config.py` | Hazard source selection path (dynamic parquet vs precomputed HDF5) is explicit and traceable. |

---

## Critical Function Anchors (Quick Jump)

- API entrypoints: `backend/app/main.py` -> `health`, `create_run`, `get_run_result`, `get_run_artifact`.
- Queue orchestration: `backend/app/job_runner.py` -> `JobProcessor._process_one`.
- Pipeline orchestration: `backend/app/risk_engine/pipeline.py` -> `run_job_pipeline`.
- CLIMADA path: `backend/app/risk_engine/impact_runner.py` -> `_compute_impacts_climada`.
- Fallback path: `backend/app/risk_engine/impact_runner.py` -> `compute_impacts_fallback`.
- Dependency aggregation: `backend/app/risk_engine/interdependency.py` -> `aggregate_impacts_with_interdependency`.
- Hazard source path: `backend/app/risk_engine/climada_engine.py` + `backend/app/risk_engine/hazard_loader.py`.
- Output contract: `backend/app/risk_engine/analysis_export.py` -> `build_result_payload`.

---

## Root Scripts -> Backend/Artifacts Mapping

| Root script | Backend dependencies | Main produced artifacts |
|---|---|---|
| `scripts/rerun_case_studies_light.py` | `backend/app/config.py`, `scripts/build_guadeloupe_wind_maps.py`, `scripts/build_case_study_multi_hazard_proxy.py`, `scripts/build_guadeloupe_page1_data.py` | `web/data/*-wind-maps.json`, `web/data/*-multi-hazard-proxy.json`, `web/data/*-page1-analysis.json`, `web/data/*-page2-analysis.json` |
| `scripts/build_guadeloupe_wind_maps.py` | `backend/app/risk_engine/hazard_loader.py`, `backend/app/risk_engine/climada_engine.py` helpers | `web/data/{territory}-wind-maps.json` |
| `scripts/build_case_study_multi_hazard_proxy.py` | `backend/app/risk_engine/climada_engine.py`, `backend/app/risk_engine/hazard_loader.py`, `backend/app/risk_engine/impact_functions_multi_hazard.py` | `web/data/{territory}-multi-hazard-proxy.json` |
| `scripts/build_guadeloupe_page1_data.py` | `backend/app/risk_engine/exposure_to_climada.py`, `backend/app/risk_engine/hazard_loader.py`, `backend/app/risk_engine/impact_runner.py` outputs | `web/data/{territory}-page1-analysis.json`, `web/data/{territory}-network-states.geojson` |
| `scripts/build_guadeloupe_complete_analysis.py` | `backend/app/risk_engine/impact_runner.py`, `backend/app/risk_engine/analysis_export.py` | `web/data/{territory}-complete-analysis.json` |
| `scripts/build_guadeloupe_water_infra_map.py` | case-study sources only (no backend compute) | `web/data/{territory}-water-infra.geojson` |

---

## Review Notes
- The stitched artifact (`backend_stitched_review.py`) contains all scoped backend files exactly once, in execution-flow order, with SHA256 provenance markers.
- For implementation truth, always refer back to original source files under `backend/`.
