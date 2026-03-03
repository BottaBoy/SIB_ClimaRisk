# SIB Risk Backend (MVP scaffold)

FastAPI backend for thesis cyclone-risk demo and user exposure runs.

## Status

This repository now includes:
- file-backed async jobs (`queued`/`running`/`completed`/`failed`)
- upload and drawn-geometry API endpoints
- unified result JSON schema for demo and user runs
- CLIMADA production pipeline (STORM + STORM_CMCC) with electricity->water post-processing
- deterministic fallback engine (disabled by default, configurable)

By default, the backend tries CLIMADA first (`SIB_RISK_IMPACT_ENGINE_MODE=climada`).
Fallback is only used if explicitly configured (`SIB_RISK_IMPACT_ENGINE_MODE=fallback`) or allowed (`SIB_RISK_ALLOW_CLIMADA_FALLBACK=true`).

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
- `SIB_RISK_JOB_TTL_HOURS` (default: `24`)
- `SIB_RISK_MAX_UPLOAD_MB` (default: `50`)
- `SIB_RISK_IMPACT_ENGINE_MODE` (`climada` or `fallback`, default: `climada`)
- `SIB_RISK_ALLOW_CLIMADA_FALLBACK` (`false`/`true`, default: `false`)
- `SIB_RISK_CLIMADA_METRIC_CRS` (default: `EPSG:3857`)
- `SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE` (default: `300`)
- `SIB_RISK_CLIMADA_TOP_EVENTS_COUNT` (default: `20`)

## API

- `GET /api/v1/health`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{job_id}`
- `GET /api/v1/runs/{job_id}/result`
- `GET /api/v1/runs/{job_id}/artifacts/{name}`
