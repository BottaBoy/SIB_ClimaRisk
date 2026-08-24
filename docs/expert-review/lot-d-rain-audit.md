# Lot D - Rain Coefficients and Data Audit

Last updated: 2026-04-29

## Decision

Lot D changes the rain path in two places that were materially inconsistent with the expert review:

1. rain vulnerability is now built with a real per-class runoff profile instead of a single hidden `0.25` coefficient
2. native rain map outputs are now treated as event-total `mm`, with normalized frequencies before extracting `rp50` / `rp100`

This closes the implementation side of point 2 and the root-cause audit side of point 8.

## Implemented Changes

### Backend rain vulnerability wiring

- `backend/app/risk_engine/impact_functions_multi_hazard.py`
  - keeps `RUNOFF_COEFF_BY_INFRA_CLASS` as the baseline profile
  - builds distinct rain proxy impact functions per `(curve_code, infra_class)` instead of one function per curve code
  - preserves the existing sensitivity lever `multi_hazard_rain_base_runoff_coeff` as a global scaling factor around the `0.25` reference baseline
  - exposes the effective per-class runoff coefficients and rain-curve specs in `mapping_info`
  - extends rain vulnerability payload metadata so the active `infra_class` and `runoff_coeff` are visible per asset mapping

Resulting baseline profile:

```text
elec_aerien      -> 0.10
elec_souterrain  -> 0.30
eau_reseau       -> 0.25
eau_ouvrage      -> 0.35
habitation       -> 0.20
```

### Rain unit / return-period audit

- `scripts/build_guadeloupe_wind_maps.py`
  - audits the CLIMADA `TCRain` semantics: `TCRain.intensity` is an event-total rain amount in `mm`
  - normalizes `TCRain` frequencies before return-level extraction
  - writes corrected rain map fields with `*_rain_mm` names
  - keeps legacy `*_rain_mmph` aliases temporarily for backward compatibility with older artefacts
  - changes emitted metadata from `rain: mm/h` to `rain: mm`
  - adds a guard that raises if positive rain `rp50`, `rp100`, and `event_max` collapse to the same value on sampled cells

### Frontend unit fix

- `web/assets/app.js`
  - reads the corrected `*_rain_mm` keys first
  - falls back to legacy `*_rain_mmph` keys so existing archived artefacts still load
  - updates displayed rain units from `mm/h` to `mm`

### Sensitivity / method documentation

- `config/sensitivity/workbook-variable-sheet.json`
  - updates the runoff-coefficient description from `0.25 unique` to a class-profile plus global scaling factor
- `docs/note-backend-calculatoire.md`
- `docs/note-analyse-sensibilite.md`
  - now describe rain as event-total `mm` and explain the per-class runoff profile

## Root Cause Summary for Point 8

The observed equality of rain `50 ans`, `100 ans`, and `evenement le plus fort` was consistent with a frequency-handling bug in the map-generation path:

- `TCRain.from_tracks(...)` returns event intensities and event frequencies must be normalized before return-level extraction
- the native rain map builder previously summarized `TCRain` directly without that normalization
- under raw event weights, the exceedance search collapses early and can return the strongest event for multiple return periods

The unit labeling issue was also real:

- `TCRain.rainrates` are documented in `mm/h`
- but `TCRain.intensity` is documented and used here as total event rainfall in `mm`
- the map payloads and UI were labeling that quantity as `mm/h`, which was incorrect

## Validation

### Focused tests completed

- `tests/risk_engine/test_expert_review_lot_d.py`
  - verifies that two asset types sharing the same D2 depth curve still resolve to different rain impact functions when their infrastructure classes differ
  - verifies that the global runoff sensitivity still scales the per-class profile coherently
- `tests/scripts/test_lot_d_rain_maps.py`
  - verifies the anti-degeneracy guard for rain return levels
  - verifies that the native rain-map path normalizes `TCRain` frequency before summarization

### Static / syntax checks completed

- `node --check web/assets/app.js`
- language-service diagnostics on all modified source files

### Broader validation completed

- `pytest tests/risk_engine -q`
- `pytest tests/scripts -q`
- frozen reference run `20260427_113740` contains complete `rain` component status for both territories and both hazards
- targeted post-integration runtime validation `20260429_075050` completed successfully on the current Guadeloupe no-deploy path

## Remaining Risk

The main residual risk is now regression risk rather than unresolved design risk:

1. a future publication rebuild could reintroduce legacy rain-unit wording in derived prose or UI copy
2. a future change in rain summarization could reintroduce collapsed positive `rp50 / rp100 / event_max` rows

## Recommendation

Lot D is closed.

Re-open Lot D only if a later rerun shows one of the following:

1. rain map metadata no longer reports `mm`
2. positive rain `rp50`, `rp100`, and `event_max` collapse spuriously again
3. a new strict-component failure appears in the multi-hazard rain path