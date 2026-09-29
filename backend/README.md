# SIB Risk Backend (MVP scaffold)

FastAPI backend for thesis cyclone-risk demo and user exposure runs.

## Status

This repository now includes:
- file-backed async jobs (`queued`/`running`/`completed`/`failed`)
- upload and drawn-geometry API endpoints
- unified result JSON schema for demo and user runs
- CLIMADA production pipeline (STORM + STORM_CMCC) with electricity->water post-processing
- explicit quick user-impact screening endpoint backed by precomputed complete-analysis ratios

`POST /api/v1/runs` remains the CLIMADA reference path. `POST /api/v1/runs/quick` is a separate screening path and returns `engine=precomputed_user_impact_v1`; it is not a silent fallback.

## Ubuntu 24.04 note (CLIMADA + GDAL)

On Ubuntu 24.04 / Python 3.12:
- use `climada 6.x` (this repo pins `climada>=6.1,<7`)
- pin Python GDAL to the system GDAL version (`gdal==3.8.4` in `requirements.txt`) to avoid wheel/build mismatches

Typical system prerequisites include `python3.12-venv`, `python3-pip`, `gdal-bin`, `libgdal-dev`, `libgeos-dev`, `libproj-dev`, and build tools.

## Run locally (after installing deps)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Important paths

Environment variables:
- `SIB_RISK_JOB_ROOT` (default: `/tmp/sib-risk-jobs`)
- `SIB_RISK_DEMO_RESULT_PATH` (default: `../web/data/sib-thesis-demo.json` relative to backend app)
- `SIB_RISK_JOB_TTL_HOURS` (default: `168`)
- `SIB_RISK_MAX_RUNS_KEPT` (default: `500`)
- `SIB_RISK_MAX_UPLOAD_MB` (default: `50`)
- `SIB_RISK_QUICK_MAX_UPLOAD_MB` (default: `10`)
- `SIB_RISK_QUICK_MAX_FEATURES` (default: `2000`)
- `SIB_RISK_USER_IMPACT_SURFACES_PATH` (default: `../web/data/user-impact-surfaces.json` relative to repo root)
- `SIB_RISK_IMPACT_ENGINE_MODE` (default: `climada`; fallback legacy rejected by the scientific engine)
- `SIB_RISK_ALLOW_CLIMADA_FALLBACK` (legacy flag kept false; fallback remains rejected)
- `SIB_RISK_CLIMADA_METRIC_CRS` (default: `EPSG:3857`)
- `SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE` (default: `300`)
- `SIB_RISK_CLIMADA_TOP_EVENTS_COUNT` (default: `20`)
- `SIB_RISK_CORS_ALLOWED_ORIGINS` (comma-separated list, includes public and protected SIB domains by default)

## API

- `GET /api/v1/health`
- `GET /api/v1/hazard/coverage`
- `POST /api/v1/runs/quick`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{job_id}`
- `GET /api/v1/runs/{job_id}/result`
- `GET /api/v1/runs/{job_id}/artifacts/{name}`

`GET /api/v1/health` intentionally returns a minimal payload (`status`, `app`, `version`, `now_utc`) to avoid leaking internal paths/runtime details.
