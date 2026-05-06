# Expert Review Delta - 2026-05-05

This note is the short handoff summary of what changed since the previous expert review round.

## 1) Scientific / backend changes

- tropical-cyclone impact return periods now use the CLIMADA exceedance-frequency interpolation basis instead of the previous custom `searchsorted` step logic
- the published return-period basis now extends to `10/20/50/100/200/1000` years
- the comparison payload now prioritizes `annual_eai` and `pml_1000` instead of using percentile-99 as the main comparison bar
- dynamic STORM and STORM_CMCC winds are now converted from 10-minute sustained winds to their 1-minute equivalent before CLIMADA hazard generation

## 2) Frontend / publication changes

- the comparison chart label now follows `PML 1000y`
- wind-map captions and labels now state explicitly that wind summaries are per-cell means / return levels, not a territorial median
- exported wind-map JSON now includes explicit metadata describing the wind aggregation semantics

## 3) Documentation changes

- the backend technical note now documents `pml_1000`, the `annual_eai + pml_1000` comparison convention, and the STORM `10min -> 1min` wind conversion
- the backend technical note now states explicitly that future-climate rainfall remains a first-approach screening approximation in V1
- the latest expert package now includes a focused final-review note and a climate-signal check note

## 4) New review artefacts

- `docs/expert-review/climate-signal-check-2026-05-05.md`
- `outputs/expert-review/tc-return-period-summary-2026-05-05.md`
- `outputs/expert-review/tc-return-period-summary-2026-05-05.json`
- refreshed `docs/expert-review/backend_stitched_review.py`

## 5) Still not changed in this cycle

- the vulnerability catalogue was not reduced to Eberenz only
- TC hazard resolution was not changed yet; that stays a sensitivity-analysis topic
- surge coastal-resolution refinement was not implemented yet; it remains a sensitivity / backlog decision point
- future-climate rainfall was not replaced by a dedicated climate-rain model in this cycle