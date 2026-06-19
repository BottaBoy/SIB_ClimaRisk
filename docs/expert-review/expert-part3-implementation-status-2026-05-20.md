# Expert Part 3 Implementation Status - 2026-05-20

This note converts the comments from `review_OFB 3.docx`, limited to `Review of Methodology and Implementation - part 3: Reproducing some Results`, into the current implementation status.

Scope rule for this cycle:
- no deployment
- no full-track production rerun in this pass
- no adaptive coastal centroid implementation in this pass

## 1) What Was Implemented In This Pass

The first implementation slice focused on reproducibility diagnostics instead of changing the scientific engine again.

Added to `meta.modeling` in `backend/app/risk_engine/climada_engine.py`:
- `hazard_dynamic_max_tracks_requested`
- `hazard_event_stats_by_hazard`
- `storm_convert_10min_to_1min`

The new `hazard_event_stats_by_hazard` payload exposes, per hazard key:
- `event_count`
- `nonzero_event_count`
- `event_frequency_sum`

Why this was the safest first change:
- the remaining uncertainty in part 3 is mostly about reproducibility and interpretation
- the new metadata helps falsify a frequency / partial-catalog explanation for wind discrepancies without changing losses
- the change is valid on the lazy dynamic-sharded path, which is the path used by current large runs

Validation completed:
- `tests/risk_engine/test_climada_sharding.py -k keeps_single_shard_dynamic_input_on_sharded_path`

## 2) Status By Expert Comment

### A. Hazard recreation / return periods / dashboard values

Current status: mostly already fixed, with remaining validation work.

Already implemented before this pass:
- CLIMADA-native return-period interpolation in `backend/app/risk_engine/climada_engine.py`
- `10/20/50/100/200/1000` year basis
- STORM `10 min -> 1 min` conversion in `backend/app/risk_engine/hazard_loader.py`

Still to validate:
- whether the dashboard wording and the expert notebook use the same spatial statistic
- whether the hazard-side wind return levels and impact-side exceedance curves are being compared on a like-for-like basis

New support added in this pass:
- payload now records the requested track cap and the effective event-frequency summary by hazard

### B. Wind direct impacts appear too large in notebook reproduction

Current status: still open, but not yet pointing to a confirmed engine bug.

Working hypothesis after code audit:
- the discrepancy is more likely tied to reproducibility context than to a fresh defect in wind vulnerability code
- the main suspects remain track-limited catalog size, annual frequency interpretation, or notebook-side comparison basis

Not changed in this pass:
- no change to the frequency-normalization formula
- no change to wind vulnerability mapping
- no change to exposure sampling

Why not changed yet:
- the expert text explicitly says track selection will be fixed later by a full-track run
- there is not yet a local proof that the current frequency normalization is scientifically wrong for the active run path

### C. Surge zero impacts for Martinique

Current status: treated as a likely historical issue already fixed in the current code and archived runs.

Evidence in current code:
- per-territory DEM resolution in `backend/app/config.py`
- per-territory DEM injection in `scripts/run_complete_analysis.py`
- strict DEM existence checks in `backend/app/risk_engine/climada_engine.py`

Evidence in archived run artefacts:
- `outputs/complete-analysis-runs/20260512_080434/manifest.json` points Martinique to `/home/ubuntu/uploads/DEM_Topo/Topo/Martinique.tif`
- the same manifest reports surge component completion for Martinique
- the archived Martinique web payload contains non-zero surge values

Implementation decision for this cycle:
- no code change on surge logic now
- keep only a spot-check validation trail in the expert package

## 3) Explicitly Deferred Items

These items remain deferred by design and should not be reopened accidentally in this cycle:

- full-track run replacing the current dynamic track cap
- adaptive coastal centroid refinement for surge
- climate-rain model replacement

## 4) Close-Out For This Cycle

The remaining in-scope plan items are now closed for this cycle:

1. A compact semantics and reference-run audit note was added in `docs/expert-review/expert-part3-rp-semantics-2026-05-20.md`.
2. The archived reference run was checked against the notebook assumptions and confirmed to be a 150-track / 150-event slice, not a full-track run.
3. The targeted no-deploy validation set was completed.

Resulting decision:
- no further backend correction is justified from the current evidence alone
- any future correction should be conditioned on a mismatch that still appears after comparing a rerun with the exported event diagnostics

## 5) Validation Completed

Completed in this cycle:
- `tests/risk_engine/test_climada_sharding.py::test_run_climada_direct_impacts_keeps_single_shard_dynamic_input_on_sharded_path`
- `tests/risk_engine/test_climada_sharding.py::test_compute_pml_matches_climada_frequency_curve_interpolation`
- `tests/risk_engine/test_climada_sharding.py::test_build_pointwise_surge_hazard_uses_unit_land_fraction_for_point_centroids`
- `tests/risk_engine/test_hazard_loader_wind_conversion.py::test_convert_storm_wind_to_climada_mps_applies_10min_to_1min_once`

## 6) No-Deploy Boundary

This pass is implementation-only inside the repository state:
- code changed
- tests changed
- documentation changed
- no deploy command was run
