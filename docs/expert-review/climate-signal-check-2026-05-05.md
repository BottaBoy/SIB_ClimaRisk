# Climate Signal Check - 2026-05-05

This note records the current wind return-period signal extracted from the published `*-wind-maps.json` artefacts after the May 2026 backend fixes.

Supporting artefacts:
- `outputs/expert-review/tc-return-period-summary-2026-05-05.md`
- `outputs/expert-review/tc-return-period-summary-2026-05-05.json`
- generator: `scripts/summarize_tc_return_period_curves.py`

## 1) Current SIB Summary

### Guadeloupe
- mean wind mean: `+0.54%` (`storm_cmcc - storm`)
- RP50 mean wind: `-0.37%`
- RP100 mean wind: `+1.05%`
- event-max mean wind: `+1.00%`

### Martinique
- mean wind mean: `+0.06%`
- RP50 mean wind: `+8.32%`
- RP100 mean wind: `-3.51%`
- event-max mean wind: `-2.55%`

## 2) Preliminary Interpretation

At this stage, the wind climate-change signal remains **small to mixed**, not a large monotonic increase across all return-period indicators.

That is directionally consistent with the expert's reading of the literature package:
- little change in mean wind signal,
- possible increases for some return periods or territories,
- possible decreases for others.

The Martinique RP50 increase is noticeable and should be reviewed carefully, but the overall pattern is still closer to a weak/mixed signal than to a strong systematic amplification.

## 3) Important Limitation

This is currently a **qualitative consistency check**, not a pixel-exact reproduction of the literature figures.

Reason:
- the paper figures in `/home/ubuntu/uploads/STORM/papers` were not numerically digitized in this pass,
- so the automated artefacts generated here provide the SIB side of the comparison, but not a machine-readable benchmark extracted from the paper plots.

## 4) Recommended Expert Check

For the final review day, the expert should use the generated summary tables above together with the cited paper figures to answer one narrow question:

- are the revised SIB wind return-period curves and their weak/mixed climate-change signal still scientifically plausible relative to the literature reference curves?