# SIB Thesis Cyclone Risk Demo

Website + backend scaffold for presenting cyclone risk results over water infrastructure (SIB example exposure) and enabling future user exposure testing.

## What is implemented

### Frontend (`web/`)
- Thesis-mode interface focused on `STORM` vs `STORM_CMCC`
- Unified result schema (`web/data/guadeloupe-complete-analysis.json`)
- Interactive map + drawing tools (Leaflet + Leaflet.draw)
- Dual interactive mean-wind maps for Guadeloupe (`web/data/guadeloupe-wind-maps.json`)
- Interactive chart panels (ECharts) for the notebook graph families (web replicas)
- Upload and drawn-exposure async job workflow UI (`/api/v1/runs`)
- Demo reset and job result reload by job ID

### Backend scaffold (`backend/`)
- FastAPI API with async file-backed job queue (single worker)
- Endpoints:
  - `GET /api/v1/health`
  - `POST /api/v1/runs`
  - `GET /api/v1/runs/{job_id}`
  - `GET /api/v1/runs/{job_id}/result`
  - `GET /api/v1/runs/{job_id}/artifacts/{name}`
- Ephemeral job storage (24h TTL) + cleanup script
- Modular risk-engine package with explicit modules for:
  - hazard loading / frequency normalization design
  - exposure ingestion
  - disaggregation summary (metric CRS aware)
  - impact function (Eberenz 2021 curve)
  - CLIMADA impact computation (direct impacts) + electricity->water propagation post-processing
  - deterministic fallback engine (explicit mode only)
  - result/artifact export

## Runtime note

The backend now runs the CLIMADA production path by default (`SIB_RISK_IMPACT_ENGINE_MODE=climada`).
Fallback remains available only when explicitly enabled.

## Guadeloupe reference build scripts

- Build complete Guadeloupe reference result (water + electricity):
  ```bash
  /home/ubuntu/sib-work/backend/.venv/bin/python scripts/build_guadeloupe_complete_analysis.py
  ```
- Build Guadeloupe mean-wind maps from full STORM/STORM_CMCC NA catalogs (10,000 years):
  ```bash
  /home/ubuntu/sib-work/backend/.venv/bin/python scripts/build_guadeloupe_wind_maps.py
  ```
- Build Guadeloupe water infrastructure map layer (AEP + EU):
  ```bash
  /home/ubuntu/sib-work/backend/.venv/bin/python scripts/build_guadeloupe_water_infra_map.py
  ```
- Rebuild NA hazards (STORM / STORM_CMCC) for Guadeloupe centroids:
  ```bash
  /home/ubuntu/sib-work/backend/.venv/bin/python scripts/rebuild_tc_hazard_na.py --build both
  ```

## Full STORM dataset links (for GitHub restitution)

- STORM present climate (all basins): https://data.4tu.nl/articles/dataset/STORM_IBTrACS_present_climate_synthetic_tropical_cyclone_tracks/12706085
- STORM CMCC: https://data.4tu.nl/datasets/98900e17-8e01-4d70-b3b6-ca1a1da2f194/2

## Thesis result schema (new)

- Demo file: `web/data/sib-thesis-demo.json`
- Validator: `scripts/validate-thesis-result.mjs`

Validation:

```bash
node scripts/validate-thesis-result.mjs web/data/sib-thesis-demo.json
```

Legacy validator is still available for the old demo schema:

```bash
node scripts/validate-data.mjs web/data/sib-demo.json
```

## Backend local run (after installing dependencies)

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Backend scripts

From `backend/`:

```bash
python scripts/cleanup_expired_jobs.py
python scripts/run_backoffice_sample.py --file /path/to/exposure.csv --value-field value_eur
```

## Nginx / systemd artifacts (templates)

- Nginx vhost with `/api/` proxy: `config/nginx/sib.dev.elio.bottagisio.com`
- systemd service/timer examples:
  - `config/systemd/sib-risk-api.service`
  - `config/systemd/sib-risk-cleanup.service`
  - `config/systemd/sib-risk-cleanup.timer`
  - `config/systemd/sib-risk-api.env.example`

## Web deploy (static assets only)

See `DEPLOIEMENT.md`.

## Backend explanation note

- Simplified note with formulas, diagrams and code excerpts:
  - `docs/note-backend-calculatoire.md`
