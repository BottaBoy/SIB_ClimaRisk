from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import Settings, load_settings
from .job_runner import JobProcessor
from .job_store import JobStore
from .models import HealthResponse, JobStatus, RunInputMode


UTC = timezone.utc
BOOT_SETTINGS = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = BOOT_SETTINGS
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    processor = JobProcessor(settings=settings, store=store)
    processor.start()
    app.state.settings = settings
    app.state.store = store
    app.state.processor = processor
    try:
        yield
    finally:
        processor.stop()


app = FastAPI(title="SIB Cyclone Risk API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(BOOT_SETTINGS.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store() -> JobStore:
    return app.state.store  # type: ignore[attr-defined]


def get_settings() -> Settings:
    return app.state.settings  # type: ignore[attr-defined]


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        now_utc=datetime.now(UTC),
        version=app.version,
    )


@app.post("/api/v1/runs")
async def create_run(
    input_mode: RunInputMode = Form(...),
    exposure_file: UploadFile | None = File(default=None),
    drawn_geojson: str | None = Form(default=None),
    value_field: str | None = Form(default=None),
    id_field: str | None = Form(default=None),
    asset_type_field: str | None = Form(default=None),
    exposure_category_field: str | None = Form(default=None),
    default_exposure_category: str | None = Form(default=None),
    crs: str | None = Form(default=None),
    sampling_spacing_m: float | None = Form(default=None),
    run_label: str | None = Form(default=None),
):
    settings = get_settings()
    store = get_store()

    if input_mode == RunInputMode.file and exposure_file is None:
        raise HTTPException(status_code=400, detail="exposure_file is required when input_mode=file")
    if input_mode == RunInputMode.drawn_geojson and not drawn_geojson:
        raise HTTPException(status_code=400, detail="drawn_geojson is required when input_mode=drawn_geojson")

    params: dict[str, Any] = {
        "input_mode": input_mode.value,
        "value_field": value_field,
        "id_field": id_field,
        "asset_type_field": asset_type_field,
        "exposure_category_field": exposure_category_field,
        "default_exposure_category": default_exposure_category or "habitation",
        "crs": crs,
        "sampling_spacing_m": sampling_spacing_m or settings.default_sampling_spacing_m,
        "run_label": run_label,
    }
    if drawn_geojson:
        # Validate basic JSON shape early to fail fast before queueing.
        try:
            parsed = json.loads(drawn_geojson)
            if not isinstance(parsed, dict) or parsed.get("type") != "FeatureCollection":
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="drawn_geojson must be a valid GeoJSON FeatureCollection")
        params["drawn_geojson"] = drawn_geojson

    envelope = store.create_job(params=params)

    if exposure_file is not None:
        original_name = Path(exposure_file.filename or "upload.bin").name
        save_path = store.upload_path(envelope.job_id, original_name)
        max_bytes = settings.max_upload_mb * 1024 * 1024
        total = 0
        with save_path.open("wb") as out:
            while True:
                chunk = await exposure_file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"Upload too large (>{settings.max_upload_mb} MB)")
                out.write(chunk)
        params = store.get_params(envelope.job_id)
        params.update({
            "upload_original_name": original_name,
            "upload_saved_name": save_path.name,
            "upload_size_bytes": total,
        })
        # overwrite params with file metadata
        store.set_params(envelope.job_id, params)

    app.state.processor.enqueue(envelope.job_id)  # type: ignore[attr-defined]
    return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))


@app.get("/api/v1/runs/search")
def search_run_by_label(run_label: str = Query(..., min_length=1)):
    store = get_store()
    found = store.find_latest_by_run_label(run_label)
    if not found:
        raise HTTPException(status_code=404, detail="run not found")
    return found


@app.get("/api/v1/runs/{job_id}")
def get_run(job_id: str):
    store = get_store()
    try:
        envelope = store.get_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")
    return envelope.model_dump(mode="json")


@app.get("/api/v1/runs/{job_id}/result")
def get_run_result(job_id: str):
    store = get_store()
    try:
        envelope = store.get_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")

    if envelope.status == JobStatus.expired:
        raise HTTPException(status_code=410, detail="job expired")
    if envelope.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail=f"job not completed (status={envelope.status.value})")

    try:
        payload = store.get_result(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="result not found")
    return payload


@app.get("/api/v1/runs/{job_id}/artifacts/{name}")
def get_run_artifact(job_id: str, name: str):
    store = get_store()
    try:
        envelope = store.get_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")

    if envelope.status == JobStatus.expired:
        raise HTTPException(status_code=410, detail="job expired")

    try:
        artifact_path = store.artifact_path(job_id, name)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid artifact name")

    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path=str(artifact_path), filename=artifact_path.name)
