# Expert Follow-up Plan - 2026-05-05

This plan converts the latest expert comments from `/home/ubuntu/uploads/Expert Review/review_OFB 2.docx` into a phased implementation sequence that can be executed one part at a time without reopening the full backend surface on every pass.

## 1) Scope Decision

### In scope now
- fix tropical-cyclone return-period calculations using CLIMADA-native logic where possible
- fix the wind-speed convention mismatch for the Eberenz tropical-cyclone curve
- verify the climate-change signal against the papers provided in `/home/ubuntu/uploads/STORM/papers`
- add a limitation note for future-climate rain modelling in the backend note
- explain the surge-resolution comment and decide what is backlog vs immediate action
- prepare a focused final review package for the expert

### Explicitly not implemented now
- replacing all wind vulnerability curves with Eberenz only
- changing TC hazard resolution now; that stays in sensitivity analysis
- implementing a full new rain-only future-climate model in this cycle
- implementing an adaptive coastal surge mesh in this cycle unless later validation proves it is necessary for correctness rather than refinement

## 2) Why This Needs To Be Split

The current issues live in different layers:
- native hazard/impact math in `backend/app/risk_engine/climada_engine.py`
- presentation curves in `backend/app/risk_engine/impact_runner.py`
- track wind convention in `backend/app/risk_engine/hazard_loader.py`
- vulnerability-curve semantics in `backend/app/risk_engine/impact_functions.py`
- scientific narrative in `docs/note-backend-calculatoire.md`
- expert-review refresh material in `docs/expert-review/`

To avoid memory overload and accidental regressions, each part below should be executed, validated, and closed before starting the next one.

## 3) Part A - Return-Period Engine Correction

### Goal
Replace custom return-period interpolation with CLIMADA-native exceedance-frequency logic and make the published curves consistent with that engine.

### Why first
This is the highest-risk scientific issue and the expert called it out twice:
- wind at return periods appears inconsistent with the hazard values
- impacts return periods currently rely on custom logic and may explain `PML50 = 0` while `PML100 > 0`

### Current implementation surface
- custom PML interpolation: `backend/app/risk_engine/climada_engine.py` (`_compute_pml`)
- raw component impact creation: `backend/app/risk_engine/climada_engine.py` (`_compute_component_impact`)
- published annual/lifetime FEC charts: `backend/app/risk_engine/impact_runner.py` (`_build_climada_graphs`)

### Work package
1. Audit the current event-frequency arrays passed into `_compute_pml` on one reference hazard.
2. Build a small adapter that reconstructs a CLIMADA `Impact`-compatible object, or directly uses the existing `Impact` object before it is reduced to arrays.
3. Replace `_compute_pml(...)` with CLIMADA-native `calc_freq_curve(return_per=...)` wherever the engine still has access to event losses and frequencies.
4. Extend the published return periods from `[10, 20, 50, 100, 200]` to include `1000`, as requested by the expert.
5. Remove or rewrite any presentation-only FEC generation that still uses synthetic damping factors instead of actual event-loss exceedance curves.
6. Decide and document whether the platform displays a mean, a median, or another aggregation for return-period wind intensity, and keep that wording explicit.

### Validation gate
- unit tests comparing old custom PML vs `Impact.calc_freq_curve(...)` on deterministic synthetic arrays
- regression check that PML values are monotonic with return period
- rerun one narrow hazard sample and the reference complete-analysis slice to confirm `PML50` is no longer pathologically zero when `PML100` is positive
- verify the web payloads and charts use the same corrected source values

### Files likely touched
- `backend/app/risk_engine/climada_engine.py`
- `backend/app/risk_engine/impact_runner.py`
- `tests/risk_engine/test_climada_sharding.py`
- possibly new targeted tests under `tests/risk_engine/`

## 4) Part B - Wind Convention And Eberenz Conversion

### Goal
Ensure that the Eberenz curve receives 1-minute sustained wind speeds, while preserving the existing non-Eberenz vulnerability catalogue.

### Why second
The expert comment is specific and the code path is narrow: our STORM parquet loader currently converts units to m/s but does not yet appear to apply the `10-minute -> 1-minute` conversion used by CLIMADA's own STORM loader.

### Current implementation surface
- STORM parquet ingestion: `backend/app/risk_engine/hazard_loader.py`
- Eberenz curve definition and asset mapping: `backend/app/risk_engine/impact_functions.py`
- CLIMADA reference behavior: installed CLIMADA `TCTracks.from_simulations_storm(...)` converts by dividing by `0.88`

### Work package
1. Confirm the wind convention of the STORM parquet inputs used in SIB.
2. Decide the cleanest application point for the conversion:
   - either when STORM tracks are ingested into the hazard loader,
   - or only when the Eberenz curve is applied.
3. Preserve the current mixed vulnerability-curve catalogue; do not collapse everything to Eberenz.
4. Add explicit metadata/comments in the risk engine and docs stating which wind convention is stored internally and which convention each curve expects.
5. Check whether any already-exported hazard intensity diagnostics or platform labels need unit wording updates.

### Preferred implementation direction
Apply the conversion once in the STORM-to-TC track ingestion layer if the downstream CLIMADA wind hazard is meant to represent the 1-minute sustained convention consistently. If that would distort non-Eberenz curves that implicitly assumed the old convention, then isolate the adjustment to the Eberenz mapping path and document that asymmetry clearly.

### Validation gate
- unit test on `hazard_loader.py` proving the `0.88` conversion is applied exactly once
- comparison of event maximum winds before/after conversion on a small sample
- sanity check of asset losses for an Eberenz-mapped class and a D2-mapped class so we know which assets move and why

### Files likely touched
- `backend/app/risk_engine/hazard_loader.py`
- `backend/app/risk_engine/impact_functions.py`
- `docs/note-backend-calculatoire.md`
- tests around hazard loading and impact functions

## 5) Part C - Climate-Change Signal Sanity Check Against Literature

### Goal
Check that the SIB return-period wind curves and climate-change signal are directionally consistent with the literature cited by the expert.

### Papers to use
- `/home/ubuntu/uploads/STORM/papers/978-3-031-08568-0_6.pdf`
- `/home/ubuntu/uploads/STORM/papers/nhess-24-1951-2024.pdf`

### What to verify
1. Present-climate and climate-change wind return-period curves for Guadeloupe and Martinique.
2. Whether the island-average signal and curve shape are close to the literature values, even if not identical at city scale.
3. Whether the low or slightly negative wind climate-change signal in SIB is still scientifically defensible.

### Work package
1. Build a small reproducible analysis script or notebook outside the main backend path.
2. Extract the return-period intensities we currently produce for at least one stable spatial aggregation per territory.
3. Compare those against the paper figures cited by the expert.
4. Save plots/tables into `outputs/` or `docs/expert-review/` so the expert can review the comparison directly.
5. Record whether the platform wording should avoid implying that "nothing changes" under climate change.

### Validation gate
- one reproducible artefact with the computed curves for GUA and MQ
- a short note concluding `consistent`, `needs explanation`, or `inconsistent`

### Files likely touched
- new validation script under `scripts/` or `docs/expert-review/package/`
- possible new note under `docs/expert-review/`
- optional exported figure/table files under `outputs/`

## 6) Part D - Rain/Future-Climate Documentation Only

### Goal
Accept the current V1 limitation for future-climate rainfall, but make that limitation explicit in the backend note.

### Work package
1. Update `docs/note-backend-calculatoire.md` in the multi-hazard rain section.
2. State clearly that the current approach propagates the TC track signal into rain through `R-CLIPER`, but does not represent the thermodynamic moisture-driven climate-change signal adequately.
3. Keep the method for this first approach, but recommend a better dedicated future-climate rain model for later work.

### Validation gate
- doc-only review ensuring the note does not overstate future-rain certainty

### Files likely touched
- `docs/note-backend-calculatoire.md`
- optionally `docs/expert-review/note-backend-calculatoire.en.md`

## 7) Part E - Surge Resolution Comment: Interpretation And Backlog Decision

### My reading of the expert comment
The first part is not about changing the DEM itself. It is about changing the centroid layout used for the surge hazard:
- keep very fine centroids near the coastline, roughly over the first `1-2 km`
- use around `100 m` spacing there
- do not waste centroids far inland or far offshore

The rationale is that if the surge hazard is evaluated only on coarse `1-2 km` cells, each cell effectively averages DEM elevation too much and can smooth away flood-prone low coastal strips.

The second part of the comment is separate:
- optionally add sea-level rise for the climate scenario, with the cited paper as a reference point

### Current decision for this cycle
- do not implement adaptive coastal centroids yet
- do not change the production surge method yet
- capture this as a structured sensitivity-analysis item and a documented modelling limitation

### Work package
1. Add this interpretation to the plan and later to the expert note.
2. Decide whether a lightweight benchmark is needed now:
   - one coastal strip with finer centroids versus current resolution,
   - compare flooded-point counts and losses.
3. If benchmark results are negligible, keep as backlog.
4. If benchmark results materially change losses, promote to a later implementation part.

### Validation gate
- one written decision note: `backlog`, `sensitivity only`, or `promote to implementation`

## 8) Part F - Expert Final Review Package And Focus

### Goal
Make the last expert day efficient by giving a narrow set of materials and questions.

### Suggested focus for the expert
1. Independent replication of return-period wind intensities and impact exceedance curves after the CLIMADA-native fix.
2. Verification of the 10-minute vs 1-minute wind conversion and its effect on Eberenz-mapped assets.
3. Check that the climate-change signal in the revised return-period curves is consistent with the literature package.
4. Spot review of surge assumptions, specifically whether current coastal resolution is acceptable for a V1 screening product.

### Deliverables to prepare for that review day
- refreshed `docs/expert-review/backend_stitched_review.py` via `generate_backend_stitched_review.py`
- hazard inputs or a minimal reproducible extract
- exposure sample used for sanity checks
- vulnerability-function catalogue actually used in the run
- simple table of key results before/after the return-period fix
- one short note listing exactly what changed since the previous expert round

### Validation gate
- package checklist passes before sending to the expert

## 9) Recommended Execution Order

Run the parts in this order:
1. Part A - return periods and published FECs
2. Part B - wind convention and Eberenz conversion
3. Part C - literature comparison and climate-signal sanity check
4. Part D - rain/future-climate documentation note
5. Part E - surge comment interpretation and backlog decision
6. Part F - final expert review package

## 10) Memory-Safe Working Rule

For the next implementation sessions:
- open only one part at a time
- make the smallest edit set for that part
- run the narrowest available validation immediately after the first substantive edit
- do not start the next part until the current part has code, tests, and note updates aligned

That sequencing should keep the work tractable while still addressing the expert's most important scientific comments first.