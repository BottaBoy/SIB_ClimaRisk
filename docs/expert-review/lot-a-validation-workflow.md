# Lot A Validation Workflow

Last updated: 2026-04-29

This note is the execution checklist created by Lot A of the expert-review implementation plan and refreshed after closure of Lots A to G.

## Baseline Frozen by Lot A

- Frozen run id: `20260427_113740`
- Frozen snapshot directory: `docs/expert-review/reference-run/20260427_113740`
- Machine-readable regression matrix: `docs/expert-review/reference-run/20260427_113740/regression-matrix.json`
- Reviewer-facing regression table: `docs/expert-review/reference-run/20260427_113740/regression-matrix.md`
- Archived artefact index with SHA256: `docs/expert-review/reference-run/20260427_113740/artifact-index.json`
- Historical comparison snapshot retained: `docs/expert-review/reference-run/20260422_094557`

## What the Baseline Tracks

Per territory and per hazard (`storm`, `storm_cmcc`):

- `eai_eur`
- `pml_50_eur`
- `pml_100_eur`
- public tail-loss headline via `percentile_99_loss_eur`
- annual component shares from the published multi-hazard proxy where available
- scientific fallback presence from complete-analysis manifest modeling metadata
- publication fallback presence from page/proxy metadata
- default valuation count visibility status

Backward-compatibility note recorded by Lots A and E:

- the frozen regression matrix still carries the legacy `max_event_loss_eur` column name so the archived baseline stays stable
- current regression helpers also expose `percentile_99_loss_eur` so new lots can validate the updated headline metric without rewriting the frozen snapshot

Post-Lot closure notes:

- valuation transparency is now exposed explicitly in result payloads through `valuation_audit`, default-value counts, and provenance notes
- scientific fallback is now blocked by the production compute entry point
- CSV exports are still not archived by the current complete-analysis run workflow and remain a known archive gap
- the targeted post-save-mat validation run is `20260429_075050` and is separate from the frozen two-territory baseline

## Narrow Checks First

Use the backend environment for test commands:

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/sib-work/backend/.venv/bin/python -m pytest tests/risk_engine/test_expert_review_lot_a.py -q
```

The new Lot A test module is intended as the minimum guardrail for later lots:

- frequency normalization surface
- runoff coefficient baseline values
- territory grid baseline for the future overlay toggle
- scientific fallback detection helper
- publication fallback detection helper
- regression matrix field extraction, including the legacy `max_event_loss_eur` alias and the current `percentile_99_loss_eur` headline

## Current Validation Ladder After Lots A to G

1. Run the narrowest relevant test command first.
2. Keep the baseline guard tests in the validation chain when schema or methodology changes:

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/sib-work/backend/.venv/bin/python -m pytest \
	tests/risk_engine/test_expert_review_lot_a.py \
	tests/risk_engine/test_expert_review_lot_e.py \
	tests/risk_engine/test_climada_sharding.py -q
```

3. Then run the broader close-out suites:

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/sib-work/backend/.venv/bin/python -m pytest tests/risk_engine -q
/home/ubuntu/sib-work/backend/.venv/bin/python -m pytest tests/scripts -q
```

4. Keep one real runtime validation in the loop when direct-impact semantics change materially:

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/sib-work/backend/.venv/bin/python scripts/run_complete_analysis.py \
	--no-deploy --territories gua --dynamic-max-tracks 150 --memory-budget-gb 6
```

Expected recent reference for this last step:
- run id: `20260429_075050`
- status: `success`

5. If publication artefacts or metadata semantics change, inspect:

- `docs/expert-review/reference-run/20260427_113740/regression-matrix.md`
- `docs/expert-review/reference-run/20260427_113740/artifact-index.json`
- `outputs/complete-analysis-runs/latest-manifest.json`

## Rebuild or Refresh the Baseline Snapshot

To regenerate the same style of baseline snapshot for a later run:

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/.venv_openpyxl/bin/python scripts/freeze_expert_review_baseline.py --run-id latest
```

For the frozen Lots A to G baseline, the current pinned run remains `20260427_113740`.