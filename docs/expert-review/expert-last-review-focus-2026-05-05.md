# Expert Last Review Focus - 2026-05-05

This note narrows the expected focus for the expert's last review day after the May 2026 follow-up fixes.

## 1) What Changed Since The Previous Review Round

- return-period impacts in the CLIMADA backend now use the native exceedance-frequency interpolation basis instead of the previous custom `searchsorted` logic
- annual return-period curves now extend to `1000y`
- the comparison view now prioritizes `annual_eai` and `pml_1000`
- dynamic STORM/STORM_CMCC winds are now converted from 10-minute sustained winds to their 1-minute equivalent before hazard generation
- the backend note now states explicitly that future-climate rainfall remains a first-approach screening approximation in this V1

## 2) Primary Questions For The Expert

Please focus on these four checks first:

1. Can you independently reproduce the revised return-period wind and impact curves, especially around `50y`, `100y`, `200y`, and `1000y`?
2. Does the 10-minute to 1-minute sustained wind conversion look scientifically appropriate for the Eberenz-aligned tropical-cyclone path?
3. Does the revised climate-change wind signal remain qualitatively consistent with the literature package cited in the review comments?
4. Is the current coastal surge resolution acceptable for a V1 screening product, or does it already require promotion from "sensitivity item" to "implementation priority"?

## 3) Interpretation Of The Surge-Resolution Comment

My current reading of the expert comment is:

- the first request is about the **centroid layout** used for surge hazard construction, not about replacing the DEM itself
- the intended refinement is to keep very fine centroid spacing close to the coastline (roughly the first `1-2 km`, around `100 m` spacing)
- the motivation is to avoid averaging away low-lying coastal strips when using coarser `1-2 km` cells
- the sea-level-rise suggestion is a separate possible extension for the future-climate surge scenario

Current implementation decision:
- keep this as a sensitivity / benchmark item for now rather than changing the production surge path immediately

## 4) Recommended Reproducibility Package For The Last Review Day

Please prioritize a compact package that contains:

- refreshed `docs/expert-review/backend_stitched_review.py`
- the hazard payloads or a minimal reproducible extract used for the revised return-period checks
- the exposure sample used for the targeted sanity checks
- the effective vulnerability-function catalogue used by the revised run
- a simple before/after table for `PML50`, `PML100`, `PML200`, and `PML1000`
- the territory wind-return-period summary exported by `scripts/summarize_tc_return_period_curves.py`

## 5) Suggested Decision Outputs From The Expert

The most useful final outputs would be:

- `validated` / `needs clarification` / `not validated` on the return-period fix
- `acceptable` / `questionable` on the wind-convention conversion
- `consistent` / `needs explanation` on the climate-change wind signal relative to the cited literature
- `keep as sensitivity item` / `promote to implementation` for the surge-resolution comment