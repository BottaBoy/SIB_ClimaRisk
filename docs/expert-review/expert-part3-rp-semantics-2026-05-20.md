# Expert Part 3 RP Semantics And Reference-Run Audit - 2026-05-20

This note closes the remaining in-scope audit work for `Review of Methodology and Implementation - part 3: Reproducing some Results`.

## 1) Dashboard Wind Return-Period Semantics

The published wind maps and the published loss return periods use the same annual exceedance-frequency logic, but they do not describe the same observable.

Wind-map side:
- `scripts/build_guadeloupe_wind_maps.py::_return_level(...)` sorts cell intensities in descending order and finds the first cumulative annual frequency that reaches `1 / RP`.
- The result is a **hazard return level per display cell**, not a territorial median and not a portfolio loss.

Published wind-map artefacts confirm the intended semantics for the frozen reference run `20260427_113740`:
- `years_covered = 10000`
- `native_dynamic_max_tracks = 150`
- `track_journal.storm.n_events = 150`
- `track_journal.storm.event_frequency_sum = 0.015`
- same values for `storm_cmcc`

The wind-map metadata also states that only cells intersecting the territory mask are retained and that each display point is the representative point of the land portion of the cell.

## 2) Impact Return-Period Semantics

Loss return periods on the Guadeloupe page use `scripts/build_guadeloupe_page1_data.py::_loss_at_return_period(...)`.

That function:
- sorts event losses in descending order,
- accumulates annual frequencies,
- finds the first point reaching `1 / RP`.

This is therefore the same exceedance-frequency basis as the wind-map return-level calculation, but applied to **portfolio event losses** instead of cell hazard intensities.

## 3) Why The Expert Notebook May See A Mismatch

The mathematical basis is aligned, but the published products are not directly like-for-like:
- wind RP = cell hazard return level
- impact RP = portfolio loss exceedance point

For the frozen run `20260427_113740`, the reproducibility context also matters:
- `outputs/complete-analysis-runs/20260427_113740/manifest.json` records `dynamic_max_tracks = 150`
- the same manifest records `hazard_track_count_storm = 150` and `hazard_track_count_storm_cmcc = 150`
- component plans in the archived manifest report `event_count = 150`

So the reference run is a **track-limited 150-event slice**, not a full-catalog run.

The archived page-1 artefact also records that it was generated from `complete_analysis_asset_fallback` with `fallback = true`, meaning the published page-analysis view is a lightweight derivative of complete-analysis results, not a separate heavy CLIMADA page rerun.

Conclusion from this audit:
- no evidence was found here for a fresh backend inconsistency in the RP interpolation logic
- the more likely explanation for notebook/platform divergence is a comparison-basis mismatch, a track-catalog mismatch, or both

## 4) Martinique Surge Closure Check

The historical `zero surge impacts for Martinique` concern does not reproduce in the current archived evidence.

Archived run `20260512_080434` shows:
- `multi_hazard_surge_topo_path = /home/ubuntu/uploads/DEM_Topo/Topo/Martinique.tif`
- surge component status `complete`
- non-zero surge values in the Martinique web payload, including `5721184.15` and `5376860.79`

This supports treating the old Martinique surge comment as a historical issue already fixed by the current per-territory DEM path.

## 5) Validation Executed In This Close-Out

Targeted no-deploy validation completed:
- `tests/risk_engine/test_climada_sharding.py::test_compute_pml_matches_climada_frequency_curve_interpolation`
- `tests/risk_engine/test_climada_sharding.py::test_build_pointwise_surge_hazard_uses_unit_land_fraction_for_point_centroids`
- `tests/risk_engine/test_hazard_loader_wind_conversion.py::test_convert_storm_wind_to_climada_mps_applies_10min_to_1min_once`
- `tests/risk_engine/test_climada_sharding.py::test_run_climada_direct_impacts_keeps_single_shard_dynamic_input_on_sharded_path`

## 6) Current Decision

For the current no-deploy cycle:
- keep the newly added reproducibility diagnostics
- do not change the frequency formula yet
- do not claim that wind-map RP and loss RP are the same statistic
- keep full-track rerun as the next scientific discriminator if the expert still sees a material mismatch
