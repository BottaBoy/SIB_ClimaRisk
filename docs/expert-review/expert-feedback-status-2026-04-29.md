# Expert Feedback Status - 2026-04-29

This note closes each recommendation from the expert review against the current repository state after integration of Lots A to G.

## Delivery Summary

- Lots A to G are integrated in the repository, test suite, and expert-review package.
- Frozen comparison baseline: `20260427_113740` (`docs/expert-review/reference-run/20260427_113740`).
- Targeted post-integration validation run: `20260429_075050` (Guadeloupe, `--no-deploy`, success).
- Focused validations completed during the Lots A to G close-out:
	- `pytest tests/risk_engine/test_expert_review_lot_a.py -q`
	- `pytest tests/risk_engine -q`
	- `pytest tests/scripts -q`

## Recommendation Status Summary

- Integrated: points 1, 2, 4, 6, 8
- Integrated in production path, with an explicit maintain note: points 3, 7
- Integrated with a documented implementation difference: point 5

## Lot Map

- Lot A: frozen reference baseline, regression matrix, fallback/publication detection helpers.
- Lot B: valuation transparency and annualization guardrails.
- Lot C: `risk_index_*` usage audit and maintain decision.
- Lot D: rain coefficients, rain units, and rain return-period guardrails.
- Lot E: `save_mat=True`, exact `max_loss_by_point`, shard/checkpoint persistence, public percentile-99 headline.
- Lot F: web grid overlay, `publication_trace`, and archived frontend validation metadata.
- Lot G: expert-review package refresh, reviewer handoff checklist, and documentation closure.

## 1) Per-asset max loss now comes from the CLIMADA impact matrix

Status: integrated.

Implemented:
- the CLIMADA component path now calls `ImpactCalc(...).impact(save_mat=True)`
- per-asset direct worst-case losses are read from `imp_mat.max(axis=0)` instead of using the old portfolio-wide scaling approximation
- shard checkpoints now persist `max_loss_by_point`, and old checkpoints without that field are invalidated so resumed runs recompute under the new semantics
- the public headline event-loss metric has moved from a single maximum toward a 99th-percentile tail metric in the aggregated payloads
- raw single-event maxima are still retained separately for diagnostics
- expert-review baselines now expose both `percentile_99_loss_eur` and the legacy `max_event_loss_eur` alias for backward compatibility

Implementation note:
- the combined multi-component hazard still composes component-level maxima additively after exact per-component matrix extraction; the live code no longer uses the old portfolio-wide ratio approximation, but an exact joint event-wise `wind+rain+surge` per-asset maximum would require retaining cross-component event-point matrices longer

Conclusion:
- the expert concern about portfolio-wide worst-case scaling is removed from the live direct-loss path
- the `save_mat=True` recommendation is integrated in the live code path

## 2) Rain vulnerability curves: per-class coefficients defined but never used

Status: integrated.

Implemented:
- `RUNOFF_COEFF_BY_INFRA_CLASS` is wired into rain vulnerability construction
- rain proxy functions are now distinct per `(curve_code, infra_class)` instead of sharing one hidden `0.25` coefficient
- the sensitivity lever remains available as a global scaling factor around the class profile

## 3) Silent fallbacks: failed components that continue as if nothing happened

Status: integrated in the production path.

Implemented:
- production `compute_impacts(...)` now rejects `allow_climada_fallback`, rejects `impact_engine_mode=fallback`, rejects hazard fallback to precomputed HDF5, and requires strict multi-hazard components
- failed scientific components now stop the run instead of silently degrading the result

Residual maintain note:
- legacy fallback helper code is still present in the repository for audit/history purposes, even though the production compute entry point no longer allows it

Conclusion:
- the expert concern about silent scientific degradation is removed from the live production path
- the remaining residue is historical/helper code, not an allowed production execution mode

## 4) Asset valuation: infrastructure datasets contain no monetary values

Status: integrated.

Implemented:
- ingestion records whether each asset uses a default value
- result payloads now expose `valuation_audit`, default-value counts, and default-value notes
- asset-level previews carry valuation provenance fields so the assumption is visible instead of silent

## 5) Frequency normalisation

Status: integrated with an implementation note.

Implemented:
- hazard frequency is normalized on copied hazard objects before impact extraction
- the rain-map generation path now normalizes frequencies before `rp50` and `rp100` extraction

Remaining difference versus the exact recommendation:
- the current implementation divides the existing CLIMADA frequency array by `storm_years`
- it does not overwrite the array with a guaranteed uniform `np.ones(len(freq)) / storm_years` vector

Conclusion:
- the normalization intent is implemented in the live path
- the exact expert formulation is not applied verbatim because the current code preserves the existing relative event weights before annualization

## 6) Territory assignment uses arbitrary grid cells, not administrative boundaries

Status: integrated as requested for the current phase.

Implemented:
- the territory grid remains unchanged for now
- the website now exposes a grid-overlay toggle so reviewers can see the operational mesh directly on Guadeloupe and Martinique impact maps
- publication trace metadata is surfaced in the generated web artefacts and the UI badge

## 7) Risk index: undocumented, probably unused, and duplicated four times

Status: reviewed and intentionally kept.

Conclusion:
- the expert suggestion was to verify usage first, then delete only if unused
- the verification shows `risk_index_*` is still used in backend payloads, exports, and the shipped frontend table sorting/display contract
- point 7 is therefore closed as a maintain decision, not as a deletion

## 8) Platform and results: rain units and return-period rows

Status: integrated.

Implemented:
- rain map outputs are treated as event-total `mm`, not `mm/h`
- frontend display prefers corrected `*_rain_mm` fields and keeps legacy aliases only for archived artefacts
- a guard now raises when positive rain `rp50`, `rp100`, and `event_max` collapse spuriously to the same value

## Overall Conclusion

Lots A to G are integrated.

Remaining residual notes for the next expert pass:
- point 3 is closed for the production compute path, but legacy helper code is intentionally retained for audit/history context
- point 5 is implemented in spirit and in production behavior, but the exact uniform-array rewrite proposed by the expert was not adopted verbatim