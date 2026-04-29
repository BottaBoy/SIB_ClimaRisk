# Expert Return Package - 2026-04-29

This checklist enumerates the files to send back to the expert for the next review cycle after Lots A to G.

## 1) Mandatory Narrative Docs

- `docs/expert-review/review-guide.md`
- `docs/expert-review/note-backend-calculatoire.en.md`
- `docs/expert-review/methodology-code-crosswalk.md`
- `docs/expert-review/expert-feedback-status-2026-04-29.md`
- `docs/expert-review/lot-a-validation-workflow.md`
- `docs/expert-review/lot-c-risk-index-audit.md`
- `docs/expert-review/lot-d-rain-audit.md`
- `docs/expert-review/expert-data-manifest.md`

Optional companion note:
- `docs/note-backend-calculatoire.md`

## 2) Execution Kit

- `docs/expert-review/package/expert-env-template.sh`
- `docs/expert-review/package/check_expert_inputs.py`
- `docs/expert-review/package/run_expert_smoke.sh`

## 3) Frozen Reference Baseline To Compare Against

Baseline run id:
- `20260427_113740`

Send these frozen-review files:
- `docs/expert-review/reference-run/README.md`
- `docs/expert-review/reference-run/20260427_113740/README.md`
- `docs/expert-review/reference-run/20260427_113740/manifest.json`
- `docs/expert-review/reference-run/20260427_113740/latest-manifest.json`
- `docs/expert-review/reference-run/20260427_113740/artifact-index.json`
- `docs/expert-review/reference-run/20260427_113740/regression-matrix.json`
- `docs/expert-review/reference-run/20260427_113740/regression-matrix.md`
- `docs/expert-review/reference-run/20260427_113740/Journalisation_Run_CompleteAnalysis.md`
- `docs/expert-review/reference-run/20260427_113740/Journalisation_Run_CompleteAnalysis.jsonl`
- `docs/expert-review/reference-run/20260427_113740/SHA256SUMS`

## 4) Archived Raw Run Payloads To Share With The Baseline

These files are not duplicated in the frozen docs snapshot and should be shared from the archived run itself:

- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-complete-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-complete-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-page1-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-page2-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-multi-hazard-proxy.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-multi-hazard-proxy.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-wind-maps.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-wind-maps.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-network-states.geojson`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-network-states.geojson`

## 5) Additional Validation Evidence (Optional But Useful)

Targeted post-integration runtime validation:
- `outputs/complete-analysis-runs/20260429_075050/manifest.json`

Historical pre-Lots A to G snapshot kept only for differential comparison:
- `docs/expert-review/reference-run/20260422_094557/README.md`

## 6) Packaging Rule

When sending the package externally:
- keep paths and filenames unchanged
- keep the frozen baseline (`20260427_113740`) and the raw archived payloads together
- do not replace the frozen baseline with the targeted Guadeloupe-only validation run (`20260429_075050`); that second run is supporting evidence, not the main comparison baseline