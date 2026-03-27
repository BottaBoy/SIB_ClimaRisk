# SIB Backend Expert Review Guide

## 1) Purpose
This guide helps an external expert review:
- backend code architecture and implementation quality,
- computational methodology consistency,
- traceability from methodology claims to executable code.

Scope for this audit campaign covers:
- `backend/app`
- `backend/scripts`
- root-level `scripts/` that generate or refresh case-study artifacts consumed by the web app.

Out of scope:
- frontend visual implementation details (except backend/script data contract compatibility checks).

---

## 2) Delivered Artifacts
This review kit provides:
- `backend_stitched_review.py`: review-only, flow-ordered stitched backend source.
- `note-backend-calculatoire.en.md`: English technical rewrite of the backend methodology note.
- `methodology-code-crosswalk.md`: explicit section-to-code mapping.
- `generate_backend_stitched_review.py`: deterministic generator for the stitched artifact.

Important:
- Original files remain the source of truth.
- The stitched file is for linear audit readability and provenance only.
- For this campaign, stitched regeneration is on-demand (not required after every implementation lot).

---

## 3) Suggested Review Workflow
1. Read `note-backend-calculatoire.en.md` sections 1-8 to understand algorithmic intent.
2. Use `methodology-code-crosswalk.md` to jump to implementation modules/functions.
3. Inspect `backend_stitched_review.py` for end-to-end flow continuity and consistency.
4. Validate edge-case behavior in key modules:
   - ingestion/normalization,
   - geometry sampling,
   - hazard loading and frequency normalization,
   - electricity->water dependency aggregation,
   - payload/export compatibility.
5. Run quick static/script smoke checks (`scripts/audit_quick_checks.sh`).
6. Optionally run a local pipeline smoke scenario via `backend/scripts/run_backoffice_sample.py`.

---

## 4) Local Reproduction Quickstart
From repository root (`/home/ubuntu/sib-work`):

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Optional sample run (separate shell):

```bash
cd /home/ubuntu/sib-work/backend
. .venv/bin/activate
python scripts/run_backoffice_sample.py \
  --file scripts/samples/backoffice_sample_assets.csv \
  --output /tmp/sib_sample_result.json
```

Optional quick audit checks (root scope: scripts + backend):

```bash
cd /home/ubuntu/sib-work
bash scripts/audit_quick_checks.sh
```

Optional cleanup utility:

```bash
cd /home/ubuntu/sib-work/backend
. .venv/bin/activate
python scripts/cleanup_expired_jobs.py
```

---

## 5) Runtime Prerequisites and Notes
- Python 3.12 recommended.
- CLIMADA stack expected (`climada>=6.1,<7`).
- GDAL compatibility matters (`gdal==3.8.4` pinned in requirements).
- Typical system packages: `gdal-bin`, `libgdal-dev`, `libgeos-dev`, `libproj-dev`, build tools.

Main environment toggles to inspect during review:
- `SIB_RISK_IMPACT_ENGINE_MODE` (`climada` or `fallback`)
- `SIB_RISK_ALLOW_CLIMADA_FALLBACK`
- `SIB_RISK_CLIMADA_METRIC_CRS`
- `SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE`
- `SIB_RISK_CLIMADA_TOP_EVENTS_COUNT`
- hazard source controls (`SIB_RISK_HAZARD_PREFER_DYNAMIC_FROM_PARQUET`, `SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED`)
- dynamic track cache bound (`SIB_RISK_TRACK_CACHE_MAX_ENTRIES`, default `8`; set `0` to disable cache)

---

## 6) What To Verify First (High-Impact Checks)
- Input validation and category normalization paths are strict and explicit.
- Hazard frequency normalization occurs exactly once per hazard object.
- Per-point and per-asset caps enforce `EAI_total <= exposure_eur`.
- Dependency propagation for water assets uses documented resolution order:
  local territory -> nearest electric territory -> global fallback.
- Output contract preserves frontend compatibility while extensions are additive.

---

## 7) Known Methodological Limits (Expected)
- Electricity->water coupling is conservative and spatial (not explicit electrical topology).
- Indirect loss is currently modeled via uplift multiplier over direct EAI.
- Sampling cap (`max_points_per_feature`) is a deliberate computational tradeoff.

These are documented constraints, not hidden behavior.

---

## 8) Deterministic Stitched Artifact Regeneration
To regenerate and compare artifact stability:

```bash
cd /home/ubuntu/sib-work
python3 docs/expert-review/generate_backend_stitched_review.py
sha256sum docs/expert-review/backend_stitched_review.py
```

Running the same command repeatedly without source edits should yield the same SHA256.
