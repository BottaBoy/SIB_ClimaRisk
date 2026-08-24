# Lot C - Risk Index Audit

Last updated: 2026-04-29

## Decision

`risk_index_*` remains required in production.

Lot C closes point 7 by documenting a maintain decision, not a removal. The field is still part of the active backend -> web contract, and removing it now would break shipped UI behavior and downstream analysis tooling.

## Production-Critical Inventory

### Backend generation

- `backend/app/risk_engine/impact_runner.py`
  - computes `risk_index_storm` / `risk_index_cmcc` for `territory_results` and `asset_results`
  - covers the main non-interdependency aggregation path
- `backend/app/risk_engine/interdependency.py`
  - computes the same fields for the electricity -> water dependency aggregation path
- `backend/app/risk_engine/analysis_export.py`
  - preserves `risk_index_storm` / `risk_index_cmcc` in artifact field ordering when flattening/exporting result rows

Observed formulas in both backend aggregation branches:

```text
risk_index = clamp((EAI_total / max(exposure_eur, 1.0)) * 1000, 0, 100)
```

### Web consumption

- `web/assets/app.js`
  - forwards `risk_index_storm` / `risk_index_cmcc` from active result rows
  - sorts the visible table by the active hazard-specific risk-index key
  - renders both risk-index columns directly in the main territory/asset table

### Active served payloads

- `web/data/guadeloupe-complete-analysis.json`
- `web/data/martinique-complete-analysis.json`

These currently published complete-analysis payloads still carry `risk_index_storm` / `risk_index_cmcc`, so the data contract is live, not historical.

## Documentation Inventory

- `docs/note-backend-calculatoire.md`
  - explicitly states that `risk_index_*` is kept for frontend compatibility
  - documents the formula and intended interpretation
- `docs/expert-review/methodology-code-crosswalk.md`
  - maps `risk_index` to territory/portfolio aggregation and graph continuity
- `docs/expert-review/backend_stitched_review.py`
  - mirrors the backend stitched review code and still includes the same `risk_index_*` calculations
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-complete-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-complete-analysis.json`
  - the current frozen baseline also includes the fields, which keeps them in the expert-review comparison contract

## Downstream Support Inventory

These usages are not the main production UI path, but they would also need migration if removal were ever attempted.

- `scripts/export_sensitivity_matrix.py`
  - loads `risk_index_{prefix}` into the exported `territory_risk_index` tensor
- `scripts/validate-thesis-result.mjs`
  - validates `risk_index_storm` / `risk_index_cmcc` in thesis-style complete-analysis payloads

## Legacy / Demo Inventory

These usages are separate from the production complete-analysis contract, but they still show that a broader cleanup would be multi-surface.

- `scripts/validate-data.mjs`
  - validates legacy demo records with singular `risk_index`
- `scripts/notebook-json-template.md`
  - still documents/export-maps the singular `risk_index`
- `web/data/sib-demo.json`
  - legacy demo payload using singular `risk_index`
- `web/data/sib-thesis-demo.json`
  - demo payload using `risk_index_storm` / `risk_index_cmcc`
- `tests/risk_engine/test_expert_review_lot_b.py`
  - fixture rows still include `risk_index_*` as part of the output shape

## Conclusion

The exhaustively checked maintained paths show that `risk_index_*` is still required in production for two independent reasons:

1. the backend computes and emits it in both aggregation branches
2. the shipped frontend reads it directly for sorting and display without fallback

Because of that, point 7 should be closed as: keep `risk_index_*` in the current production contract.

## If Removal Is Ever Desired Later

Treat removal as a separate migration project, not as opportunistic cleanup.

Minimum scope:

1. define the replacement UI/business metric first, including table sort semantics
2. migrate `web/assets/app.js` away from direct `risk_index_*` reads
3. version or update backend payloads from `impact_runner.py` and `interdependency.py`
4. update export/validation tooling (`export_sensitivity_matrix.py`, thesis/demo validators, templates)
5. refresh expert-review reference artifacts and documentation after the schema migration

Until that dedicated migration exists, removing `risk_index_*` would be a hazardous deletion.