# SIB Backend Expert Review Guide

Last updated: **2026-04-29**

## 1) Purpose
This guide is the entry point for an external expert review of the current SIB backend and critical run scripts.

Primary audit goals:
- methodological consistency,
- implementation traceability,
- reproducibility of an autonomous rerun (Guadeloupe + Martinique),
- explicit identification of known technical debt.

## 2) Scope
In scope:
- `backend/app`
- `backend/scripts`
- root `scripts/` used to produce complete-analysis and frontend case-study artifacts.

Out of scope:
- frontend visual design details (except data-contract compatibility).

## 3) Expert Package Contents
Core audit files:
- `docs/expert-review/review-guide.md`
- `docs/expert-review/note-backend-calculatoire.en.md`
- `docs/expert-review/expert-review-delta-2026-05-05.md`
- `docs/expert-review/expert-followup-plan-2026-05-05.md`
- `docs/expert-review/expert-last-review-focus-2026-05-05.md`
- `docs/expert-review/climate-signal-check-2026-05-05.md`
- `docs/expert-review/methodology-code-crosswalk.md`
- `docs/expert-review/expert-feedback-status-2026-04-29.md`
- `docs/expert-review/expert-return-package-2026-04-29.md`
- `docs/expert-review/lot-a-validation-workflow.md`
- `docs/expert-review/lot-c-risk-index-audit.md`
- `docs/expert-review/lot-d-rain-audit.md`
- `docs/expert-review/backend_stitched_review.py`
- `docs/expert-review/generate_backend_stitched_review.py`

Execution kit:
- `docs/expert-review/expert-data-manifest.md`
- `docs/expert-review/package/expert-env-template.sh`
- `docs/expert-review/package/check_expert_inputs.py`
- `docs/expert-review/package/run_expert_smoke.sh`

Reproducibility snapshots:
- `docs/expert-review/environment/environment-snapshot-2026-04-22.md`
- `docs/expert-review/environment/pip-freeze-2026-04-22.txt`
- `docs/expert-review/reference-run/README.md`
- `docs/expert-review/reference-run/20260427_113740/README.md`
- `docs/expert-review/reference-run/20260427_113740/manifest.json`
- `docs/expert-review/reference-run/20260427_113740/latest-manifest.json`
- `docs/expert-review/reference-run/20260427_113740/artifact-index.json`
- `docs/expert-review/reference-run/20260427_113740/regression-matrix.json`
- `docs/expert-review/reference-run/20260427_113740/regression-matrix.md`
- `docs/expert-review/reference-run/20260427_113740/SHA256SUMS`

Archived raw run payloads to share alongside the frozen metadata snapshot:
- `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-complete-analysis.json`
- `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-complete-analysis.json`

## 4) Current Backend Snapshot (2026-04-29)
Main API endpoints:
- `GET /api/v1/health`
- `GET /api/v1/hazard/coverage`
- `GET /api/v1/vulnerability/curves`
- `POST /api/v1/runs`
- `GET /api/v1/runs/search`
- `GET /api/v1/runs/recent`
- `GET /api/v1/runs/{job_id}`
- `GET /api/v1/runs/{job_id}/result`
- `GET /api/v1/runs/{job_id}/artifacts/{name}`

Compute profile:
- engine default is `climada_with_interdependency_v1`,
- Lots A to G are now integrated in the live repository state,
- hazards include `storm` and `storm_cmcc`,
- multi-hazard components are `wind`, `rain`, `surge` with strict failure behavior,
- social-impact metrics are produced when population rasters are available,
- direct per-asset worst-case losses now come from the CLIMADA impact matrix (`save_mat=True` + `imp_mat.max(axis=0)`),
- aggregated payloads now expose the public event-loss headline as `percentile_99_loss_eur`,
- scientific fallback engine mode is no longer allowed by the production compute entry point,
- the shipped web contract still consumes `risk_index_*` and `publication_trace` metadata.

## 5) Suggested Review Workflow
1. Read `note-backend-calculatoire.en.md` first (architecture + formulas + limits).
2. Use `methodology-code-crosswalk.md` to jump from methodology statements to exact modules.
3. Inspect `backend_stitched_review.py` for a historical linear flow review, but use live backend source files as the implementation truth when the stitched snapshot differs.
4. Validate exposure ingestion/disaggregation/sampling logic.
5. Validate hazard loading and frequency normalization behavior.
6. Validate interdependency logic and social-impact enrichment.
7. Run `check_expert_inputs.py` and `run_expert_smoke.sh`.
8. Run a complete non-deployment rerun command.
9. Record any methodological inconsistencies and required clarifications.

## 6) Validated Commands
Repository root: `/home/ubuntu/sib-work`

Backend environment setup:
```bash
cd /home/ubuntu/sib-work/backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Quick backend sample run:
```bash
cd /home/ubuntu/sib-work/backend
. .venv/bin/activate
python scripts/run_backoffice_sample.py \
  --file scripts/samples/backoffice_sample_assets.csv \
  --output /tmp/sib_sample_result.json
```

Expert package preflight + smoke:
```bash
cd /home/ubuntu/sib-work
./docs/expert-review/package/check_expert_inputs.py --mode full
./docs/expert-review/package/run_expert_smoke.sh --mode minimal
```

Complete non-deployment rerun (GUA+MQ):
```bash
cd /home/ubuntu/sib-work
python3 scripts/run_complete_analysis.py --territories both --no-deploy
```

## 7) Known Debt and Audit Caveats
Historical note:
- `docs/expert-review/session-audit-2026-03-26.md` records the earlier audit state and the pre-Lots A to G cleanup work.

Current close-out validation basis:
- `pytest tests/risk_engine -q` passed during the 2026-04-29 close-out.
- `pytest tests/scripts -q` passed during the 2026-04-29 close-out.
- targeted no-deploy runtime validation passed on run `20260429_075050`.

Implication for external audit:
- treat the focused pytest suites and frozen reference run as the primary close-out evidence,
- treat `audit_quick_checks.sh` as a separate engineering-quality probe, not as the authoritative scientific validation gate for this package refresh.

## 8) Deterministic Stitched Regeneration
```bash
cd /home/ubuntu/sib-work
python3 docs/expert-review/generate_backend_stitched_review.py
sha256sum docs/expert-review/backend_stitched_review.py
```

Expected SHA256 (current stitched snapshot):
- `edc2a2cb8a2fe2ae5dbdf1610be00ed2232199672f67a75bcdaf40b46a8482cc`

If source files do not change, rerunning should produce the same hash.

## 9) Data Package Reference
Use `docs/expert-review/expert-data-manifest.md` as the authoritative transfer checklist for data prerequisites and `docs/expert-review/expert-return-package-2026-04-29.md` as the authoritative document/file handoff checklist.

Important practical rule:
- the docs package is not enough by itself for an autonomous rerun
- if a required runtime input changed since the previous transfer, that updated input must be re-transferred alongside the docs
- for the current package state, the active surge DEM inputs are `/home/ubuntu/uploads/DEM_Topo/Topo/Guadeloupe.tif` and `/home/ubuntu/uploads/DEM_Topo/Topo/Martinique.tif`

## 10) Environment Snapshot (Pinned)
The expert package now includes a pinned environment snapshot:
- `docs/expert-review/environment/environment-snapshot-2026-04-22.md`
- `docs/expert-review/environment/pip-freeze-2026-04-22.txt`

This snapshot records:
- Python runtime version,
- pip toolchain version,
- OS GDAL/PROJ versions,
- Python GDAL/PROJ bindings,
- complete Python dependency freeze from backend venv.

## 11) Frozen Reference Run (Pinned)
The latest run at capture time has been frozen for side-by-side expert comparison:
- run id: `20260427_113740`
- index: `docs/expert-review/reference-run/README.md`
- snapshot README: `docs/expert-review/reference-run/20260427_113740/README.md`
- manifest snapshots:
  - `docs/expert-review/reference-run/20260427_113740/manifest.json`
  - `docs/expert-review/reference-run/20260427_113740/latest-manifest.json`
- frozen audit matrices:
  - `docs/expert-review/reference-run/20260427_113740/regression-matrix.json`
  - `docs/expert-review/reference-run/20260427_113740/regression-matrix.md`
- checksums: `docs/expert-review/reference-run/20260427_113740/SHA256SUMS`
- archived raw outputs:
  - `outputs/complete-analysis-runs/20260427_113740/territories/guadeloupe/web/data/guadeloupe-complete-analysis.json`
  - `outputs/complete-analysis-runs/20260427_113740/territories/martinique/web/data/martinique-complete-analysis.json`

Quick integrity check:
```bash
cd /home/ubuntu/sib-work
cd docs/expert-review/reference-run/20260427_113740
sha256sum -c SHA256SUMS
```

## 12) Post-Integration Targeted Validation
The save-mat / exact max-loss integration was also validated on a fresh targeted runtime check:
- run id: `20260429_075050`
- mode: `--territories gua --dynamic-max-tracks 150 --no-deploy`
- status: `success`
- primary evidence: `outputs/complete-analysis-runs/20260429_075050/manifest.json`
