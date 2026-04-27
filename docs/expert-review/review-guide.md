# SIB Backend Expert Review Guide

Last updated: **2026-04-22**

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
- `docs/expert-review/methodology-code-crosswalk.md`
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
- `docs/expert-review/reference-run/20260422_094557/manifest.json`
- `docs/expert-review/reference-run/20260422_094557/guadeloupe-complete-analysis.json`
- `docs/expert-review/reference-run/20260422_094557/martinique-complete-analysis.json`
- `docs/expert-review/reference-run/20260422_094557/SHA256SUMS`

## 4) Current Backend Snapshot (2026-04-22)
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
- hazards include `storm` and `storm_cmcc`,
- multi-hazard components are `wind`, `rain`, `surge` (with controlled component fallback behavior),
- social-impact metrics are produced when population rasters are available,
- deterministic fallback engine remains available through configuration.

## 5) Suggested Review Workflow
1. Read `note-backend-calculatoire.en.md` first (architecture + formulas + limits).
2. Use `methodology-code-crosswalk.md` to jump from methodology statements to exact modules.
3. Inspect `backend_stitched_review.py` for linear, end-to-end flow review.
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
As of **2026-04-22**, `scripts/audit_quick_checks.sh` is **not a passing smoke check**.

Observed status:
- command: `bash scripts/audit_quick_checks.sh`
- result: non-zero exit
- root cause: `ruff check` fails (33 findings in current tree).

Implication for external audit:
- use `audit_quick_checks.sh` as a diagnostic signal,
- do not treat it as a blocker for computational rerun validation,
- rely on the expert package preflight/smoke scripts for reproducibility checks.

## 8) Deterministic Stitched Regeneration
```bash
cd /home/ubuntu/sib-work
python3 docs/expert-review/generate_backend_stitched_review.py
sha256sum docs/expert-review/backend_stitched_review.py
```

Expected SHA256 (2026-04-22 baseline):
- `edc2a2cb8a2fe2ae5dbdf1610be00ed2232199672f67a75bcdaf40b46a8482cc`

If source files do not change, rerunning should produce the same hash.

## 9) Data Package Reference
Use `docs/expert-review/expert-data-manifest.md` as the authoritative transfer checklist (required vs recommended optional datasets).

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
- run id: `20260422_094557`
- index: `docs/expert-review/reference-run/README.md`
- manifest: `docs/expert-review/reference-run/20260422_094557/manifest.json`
- outputs:
  - `docs/expert-review/reference-run/20260422_094557/guadeloupe-complete-analysis.json`
  - `docs/expert-review/reference-run/20260422_094557/martinique-complete-analysis.json`
- checksums: `docs/expert-review/reference-run/20260422_094557/SHA256SUMS`

Quick integrity check:
```bash
cd /home/ubuntu/sib-work
cd docs/expert-review/reference-run/20260422_094557
sha256sum -c SHA256SUMS
```
