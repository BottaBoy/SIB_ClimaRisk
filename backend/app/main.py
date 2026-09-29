from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
import hmac
import json
import os
import secrets
import sqlite3

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .auth import (
    AuthContext,
    clear_session_cookie,
    client_ip,
    create_login_session,
    current_auth_context,
    hash_password,
    ip_hash,
    is_admin,
    is_super_admin,
    normalize_email,
    normalize_username,
    new_token,
    public_user,
    require_admin_user,
    require_authorized_user,
    require_csrf_token,
    require_role_name,
    require_user,
    token_hash,
    user_agent,
    validate_password,
    verify_password,
)
from .config import Settings, load_settings
from .db import AppDatabase, iso_now
from .job_store import JobStore
from .models import HealthResponse, JobError, JobStatus, RunInputMode
from .output_generation import artifact_kind_for_name, ensure_output_artifacts, mime_type_for_name
from .risk_engine.errors import InputValidationError, RiskEngineError
from .risk_engine.hazard_loader import list_default_basin_coverages
from .risk_engine.impact_functions import get_tc_vulnerability_payload
from .risk_engine.impact_functions_landslide import get_landslide_vulnerability_payload
from .risk_engine.impact_functions_multi_hazard import get_multi_hazard_vulnerability_payload
from .risk_engine.quick_impact import list_quick_zones, run_quick_pipeline


UTC = timezone.utc
BOOT_SETTINGS = load_settings()


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str | None = None
    new_password: str = Field(min_length=10)


class UpdateMePayload(BaseModel):
    email: str | None = None


class AdminCreateUserPayload(BaseModel):
    username: str
    email: str
    password: str = Field(min_length=10)
    role: str = "authorized_user"
    is_active: bool = True


class AdminUpdateUserPayload(BaseModel):
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


class AdminResetPasswordPayload(BaseModel):
    password: str = Field(min_length=10)
    must_change_password: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = BOOT_SETTINGS
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    db = AppDatabase(settings.db_path)
    db.init_schema()
    _bootstrap_super_admin_from_env(db)
    app.state.settings = settings
    app.state.store = store
    app.state.db = db
    yield


app = FastAPI(title="SIB Cyclone Risk API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(BOOT_SETTINGS.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store() -> JobStore:
    return app.state.store  # type: ignore[attr-defined]


def get_settings() -> Settings:
    return app.state.settings  # type: ignore[attr-defined]


def get_db() -> AppDatabase:
    return app.state.db  # type: ignore[attr-defined]


def _bootstrap_super_admin_from_env(db: AppDatabase) -> None:
    username_raw = os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_USERNAME")
    email_raw = os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_EMAIL")
    password_raw = os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_PASSWORD")
    if not username_raw:
        return
    try:
        username = normalize_username(username_raw)
    except ValueError:
        return
    existing = db.get_user_by_username(username)
    if existing is not None:
        fields: dict[str, Any] = {"role": "super_admin", "is_active": True}
        if email_raw:
            try:
                fields["email"] = normalize_email(email_raw)
            except ValueError:
                pass
        if password_raw:
            fields["password_hash"] = hash_password(password_raw)
            fields["must_change_password"] = True
        db.update_user(str(existing["id"]), **fields)
        return
    if not email_raw or not password_raw:
        return
    try:
        db.create_user(
            user_id=f"usr_{secrets.token_hex(8)}",
            username=username,
            email=normalize_email(email_raw),
            password_hash=hash_password(password_raw),
            role="super_admin",
            is_active=True,
            must_change_password=True,
        )
    except Exception:
        return


def _rate_limit_or_429(*, db: AppDatabase, route: str, key: str, limit: int, window_seconds: int) -> None:
    result = db.check_rate_limit(route=route, key=key, limit=limit, window_seconds=window_seconds)
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded for {route}",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def _json_job_payload(job_id: str, *, run: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    store = get_store()
    envelope = None
    try:
        envelope = store.get_job(job_id)
    except FileNotFoundError:
        pass
    if run is None:
        run = get_db().get_run(job_id)
    if params is None:
        try:
            params = store.get_params(job_id)
        except FileNotFoundError:
            params = {}
    if envelope is not None:
        payload = envelope.model_dump(mode="json")
    elif run is not None:
        payload = {
            "job_id": job_id,
            "status": run.get("status"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "expires_at": run.get("expires_at"),
            "progress": run.get("progress") or 0.0,
            "stage": run.get("stage") or "queued",
            "message": run.get("message"),
            "error": None,
        }
    else:
        raise HTTPException(status_code=404, detail="job not found")

    if run is not None:
        payload.update(
            {
                "status": run.get("status") or payload.get("status"),
                "stage": run.get("stage") or payload.get("stage"),
                "progress": run.get("progress") if run.get("progress") is not None else payload.get("progress"),
                "message": run.get("message") or payload.get("message"),
                "run_type": run.get("run_type"),
                "run_label": run.get("run_label"),
                "calculation_mode": "quick" if run.get("run_type") == "quick" else "complete",
                "calculation_status": run.get("calculation_status"),
                "output_status": run.get("output_status"),
                "email_status": run.get("email_status"),
                "eta_seconds": run.get("eta_seconds"),
                "eta_source": run.get("eta_source"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "track_count_requested": run.get("track_count_requested"),
                "track_count_storm": run.get("track_count_storm"),
                "track_count_storm_cmcc": run.get("track_count_storm_cmcc"),
            }
        )
        if run.get("error_code") or run.get("error_message"):
            payload["error"] = {
                "code": run.get("error_code") or "RUN_ERROR",
                "message": run.get("error_message") or "",
            }
    raw_input_mode = params.get("input_mode") if isinstance(params, dict) else None
    if raw_input_mode is None and run is not None:
        raw_input_mode = run.get("input_mode")
    input_mode = str(raw_input_mode or "").strip().lower()
    payload["dataset_mode"] = "drawn" if input_mode == "drawn_geojson" else "uploaded"
    return payload


def _public_token_is_valid(run: dict[str, Any], access_token: str | None) -> bool:
    expected = str(run.get("public_token_hash") or "")
    if not expected or not access_token:
        return False
    return hmac.compare_digest(expected, token_hash(access_token))


async def _authorize_run_access(
    request: Request,
    job_id: str,
    *,
    access_token: str | None = None,
) -> tuple[dict[str, Any] | None, AuthContext | None]:
    db = get_db()
    run = db.get_run(job_id)
    ctx = await current_auth_context(request)
    if run is None:
        return None, ctx
    if ctx is not None:
        user_id = str(ctx.user.get("id") or "")
        if is_admin(ctx.user) or str(run.get("owner_user_id") or "") == user_id:
            return run, ctx
    if _public_token_is_valid(run, access_token):
        return run, ctx
    raise HTTPException(status_code=403, detail="run access denied")


def _decorate_result_downloads(payload: dict[str, Any], *, access_token: str | None) -> dict[str, Any]:
    if not access_token:
        return payload
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    collections = [artifacts.get("downloads"), artifacts.get("visuals")]
    if not any(isinstance(items, list) for items in collections):
        return payload
    token_q = quote(access_token, safe="")
    for items in collections:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url or "access_token=" in url:
                continue
            sep = "&" if "?" in url else "?"
            item["url"] = f"{url}{sep}access_token={token_q}"
    return payload


def _register_artifacts_from_paths(job_id: str, paths: list[Path]) -> None:
    db = get_db()
    run = db.get_run(job_id)
    if run is None:
        return
    for path in paths:
        if not Path(path).exists():
            continue
        db.register_artifact(
            artifact_id=f"art_{secrets.token_hex(8)}",
            job_id=job_id,
            kind=artifact_kind_for_name(path.name),
            filename=path.name,
            path=Path(path),
            mime_type=mime_type_for_name(path.name),
            expires_at=str(run.get("expires_at")),
        )


def _register_download_artifacts(job_id: str, result: dict[str, Any]) -> None:
    downloads = result.get("artifacts", {}).get("downloads") if isinstance(result.get("artifacts"), dict) else []
    if not isinstance(downloads, list):
        return
    paths: list[Path] = []
    store = get_store()
    for item in downloads:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            path = store.artifact_path(job_id, name)
        except ValueError:
            continue
        if path.exists():
            paths.append(path)
    _register_artifacts_from_paths(job_id, paths)


async def _save_upload_to_job(
    *,
    store: JobStore,
    job_id: str,
    exposure_file: UploadFile,
    max_upload_mb: int,
) -> dict[str, Any]:
    original_name = Path(exposure_file.filename or "upload.bin").name
    save_path = store.upload_path(job_id, original_name)
    max_bytes = max_upload_mb * 1024 * 1024
    total = 0
    with save_path.open("wb") as out:
        while True:
            chunk = await exposure_file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                save_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Upload too large (>{max_upload_mb} MB)")
            out.write(chunk)
    params = store.get_params(job_id)
    params.update(
        {
            "upload_original_name": original_name,
            "upload_saved_name": save_path.name,
            "upload_size_bytes": total,
        }
    )
    store.set_params(job_id, params)
    return params


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        now_utc=datetime.now(UTC),
        version=app.version,
    )


@app.get("/api/v1/hazard/coverage")
def hazard_coverage():
    settings = get_settings()
    return {
        "hazards": ["storm", "storm_cmcc"],
        "hazard_components": ["wind", "rain", "surge", "landslide"],
        "coverages": list_default_basin_coverages(),
        "quick_zones": list_quick_zones(settings),
    }


@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    ctx = await current_auth_context(request)
    if ctx is None:
        return {"authenticated": False, "user": None, "csrf_token": None}
    return {"authenticated": True, "user": public_user(ctx.user), "csrf_token": ctx.csrf_token}


@app.post("/api/v1/auth/login")
async def auth_login(payload: LoginPayload, request: Request, response: Response):
    db = get_db()
    settings = get_settings()
    username = str(payload.username or "").strip()
    _rate_limit_or_429(
        db=db,
        route="login",
        key=f"{client_ip(request)}:{username.lower()}",
        limit=int(settings.login_rate_limit_per_15m),
        window_seconds=15 * 60,
    )
    user = db.get_user_by_username(username)
    if user is None or not verify_password(payload.password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if int(user.get("is_active") or 0) != 1:
        raise HTTPException(status_code=403, detail="account disabled")
    session = create_login_session(db=db, response=response, settings=settings, user=user, request=request)
    fresh_user = db.get_user_by_id(str(user["id"])) or user
    return {"authenticated": True, "user": public_user(fresh_user), **session}


@app.post("/api/v1/auth/logout")
async def auth_logout(request: Request, response: Response, ctx: AuthContext = Depends(require_user)):
    require_csrf_token(request, ctx)
    get_db().delete_session(ctx.session_id_hash)
    clear_session_cookie(response, settings=get_settings())
    return {"authenticated": False}


@app.patch("/api/v1/auth/me")
async def auth_update_me(payload: UpdateMePayload, request: Request, ctx: AuthContext = Depends(require_authorized_user)):
    require_csrf_token(request, ctx)
    if payload.email is None:
        return {"user": public_user(ctx.user)}
    try:
        email = normalize_email(payload.email)
        user = get_db().update_user(str(ctx.user["id"]), email=email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="email already exists")
    return {"user": public_user(user)}


@app.post("/api/v1/auth/change-password")
async def auth_change_password(payload: ChangePasswordPayload, request: Request, ctx: AuthContext = Depends(require_authorized_user)):
    require_csrf_token(request, ctx)
    db = get_db()
    user = db.get_user_by_id(str(ctx.user["id"]))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not payload.current_password or not verify_password(payload.current_password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="invalid current password")
    try:
        password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = db.update_user(str(user["id"]), password_hash=password_hash, must_change_password=False)
    return {"user": public_user(updated)}


@app.get("/api/v1/vulnerability/curves")
def vulnerability_curves(hazard_component: str = Query("wind")):
    component = str(hazard_component or "wind").strip().lower()
    if component in {"wind", "storm", "tc"}:
        return get_tc_vulnerability_payload()
    if component in {"rain", "surge"}:
        settings = get_settings()
        return get_multi_hazard_vulnerability_payload(
            hazard_component=component,
            flood_curve_file=settings.d2_flood_curve_file,
        )
    if component in {"landslide", "ls"}:
        settings = get_settings()
        return get_landslide_vulnerability_payload(d2_curve_file=settings.d2_flood_curve_file)
    raise HTTPException(
        status_code=400,
        detail="hazard_component must be one of: wind, rain, surge, landslide",
    )


@app.post("/api/v1/runs/quick")
async def create_quick_run(
    request: Request,
    input_mode: RunInputMode = Form(...),
    exposure_file: UploadFile | None = File(default=None),
    drawn_geojson: str | None = Form(default=None),
    target_zone: str | None = Form(default="auto"),
    value_field: str | None = Form(default=None),
    id_field: str | None = Form(default=None),
    asset_type_field: str | None = Form(default=None),
    exposure_category_field: str | None = Form(default=None),
    default_exposure_category: str | None = Form(default=None),
    crs: str | None = Form(default=None),
    run_label: str | None = Form(default=None),
):
    settings = get_settings()
    store = get_store()
    db = get_db()
    _rate_limit_or_429(
        db=db,
        route="quick_run",
        key=client_ip(request),
        limit=int(settings.quick_rate_limit_per_hour),
        window_seconds=3600,
    )

    if input_mode == RunInputMode.file and exposure_file is None:
        raise HTTPException(status_code=400, detail="exposure_file is required when input_mode=file")
    if input_mode == RunInputMode.drawn_geojson and not drawn_geojson:
        raise HTTPException(status_code=400, detail="drawn_geojson is required when input_mode=drawn_geojson")

    params: dict[str, Any] = {
        "input_mode": input_mode.value,
        "target_zone": target_zone or "auto",
        "value_field": value_field or "value_eur",
        "id_field": id_field or "asset_id",
        "asset_type_field": asset_type_field or "asset_type",
        "exposure_category_field": exposure_category_field or "exposure_category",
        "default_exposure_category": default_exposure_category or "habitation",
        "crs": crs,
        "run_label": run_label,
        "calculation_mode": "quick",
    }
    if drawn_geojson:
        try:
            parsed = json.loads(drawn_geojson)
            if not isinstance(parsed, dict) or parsed.get("type") != "FeatureCollection":
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="drawn_geojson must be a valid GeoJSON FeatureCollection")
        params["drawn_geojson"] = drawn_geojson

    access_token = new_token()
    envelope = store.create_job(params=params)
    db.create_run(
        job_id=envelope.job_id,
        run_type="quick",
        input_mode=input_mode.value,
        public_token_hash=token_hash(access_token),
        run_label=run_label,
        target_zone=target_zone or "auto",
        expires_at=envelope.expires_at.isoformat(),
        artifact_dir=str(store.artifacts_dir(envelope.job_id)),
        status="queued",
        calculation_status="queued",
        output_status="pending",
        email_status="not_applicable",
        stage="queued",
        progress=0.0,
        message="Quick Run accepte",
    )
    try:
        if exposure_file is not None:
            params = await _save_upload_to_job(
                store=store,
                job_id=envelope.job_id,
                exposure_file=exposure_file,
                max_upload_mb=settings.quick_max_upload_mb,
            )
        store.update_job(
            envelope.job_id,
            status=JobStatus.running,
            stage="quick_compute",
            progress=0.5,
            message="Quick impact calculation in progress",
        )
        db.update_run(
            envelope.job_id,
            status="running",
            calculation_status="running",
            stage="quick_compute",
            progress=0.5,
            message="Calcul rapide en cours",
            started_at=iso_now(),
            heartbeat_at=iso_now(),
        )
        result = run_quick_pipeline(envelope.job_id, params, settings, store)
        store.save_result(envelope.job_id, result)
        db.update_run(
            envelope.job_id,
            status="generating_outputs",
            calculation_status="completed",
            output_status="running",
            stage="generating_outputs",
            progress=0.9,
            message="Generation des cartes, du PDF et du XLSX",
            result_path=str(store.result_path(envelope.job_id)),
        )
        artifact_paths = ensure_output_artifacts(envelope.job_id, result, store)
        _register_artifacts_from_paths(envelope.job_id, artifact_paths)
        completed = store.update_job(
            envelope.job_id,
            status=JobStatus.completed,
            stage="completed",
            progress=1.0,
            message="Quick impact calculation completed",
        )
        db.update_run(
            envelope.job_id,
            status="completed",
            calculation_status="completed",
            output_status="completed",
            email_status="not_applicable",
            stage="completed",
            progress=1.0,
            message="Quick Run termine",
            finished_at=iso_now(),
            result_path=str(store.result_path(envelope.job_id)),
        )
    except HTTPException as exc:
        db.update_run(envelope.job_id, status="failed", calculation_status="failed", stage="failed", progress=1.0, error_code="HTTP_ERROR", error_message=str(exc.detail))
        store.update_job(envelope.job_id, status=JobStatus.failed, stage="failed", progress=1.0, message=str(exc.detail))
        raise
    except InputValidationError as exc:
        db.update_run(envelope.job_id, status="failed", calculation_status="failed", stage="failed", progress=1.0, error_code="INPUT_VALIDATION_ERROR", error_message=str(exc), message=str(exc))
        store.update_job(
            envelope.job_id,
            status=JobStatus.failed,
            stage="failed",
            progress=1.0,
            message=str(exc),
            error=JobError(code="INPUT_VALIDATION_ERROR", message=str(exc)),
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except RiskEngineError as exc:
        db.update_run(envelope.job_id, status="failed", calculation_status="failed", stage="failed", progress=1.0, error_code=exc.__class__.__name__.upper(), error_message=str(exc), message=str(exc))
        store.update_job(
            envelope.job_id,
            status=JobStatus.failed,
            stage="failed",
            progress=1.0,
            message=str(exc),
            error=JobError(code=exc.__class__.__name__.upper(), message=str(exc)),
        )
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        db.update_run(envelope.job_id, status="failed", calculation_status="failed", stage="failed", progress=1.0, error_code="UNEXPECTED_QUICK_FAILURE", error_message=str(exc), message="Unexpected quick impact failure")
        store.update_job(
            envelope.job_id,
            status=JobStatus.failed,
            stage="failed",
            progress=1.0,
            message="Unexpected quick impact failure",
            error=JobError(code="UNEXPECTED_QUICK_FAILURE", message=str(exc)),
        )
        raise HTTPException(status_code=500, detail="Unexpected quick impact failure")

    payload = completed.model_dump(mode="json")
    payload.update(
        {
            "dataset_mode": "drawn" if input_mode == RunInputMode.drawn_geojson else "uploaded",
            "calculation_mode": "quick",
            "run_type": "quick",
            "access_token": access_token,
            "result_url": f"/api/v1/runs/{completed.job_id}/result?access_token={quote(access_token, safe='')}",
        }
    )
    return JSONResponse(status_code=201, content=payload)


@app.get("/api/v1/runs/search")
async def search_run_by_label(
    run_label: str = Query(..., min_length=1),
    ctx: AuthContext = Depends(require_authorized_user),
):
    owner = None if is_admin(ctx.user) else str(ctx.user["id"])
    found = get_db().find_run_by_label(run_label, owner_user_id=owner)
    if not found:
        raise HTTPException(status_code=404, detail="run not found")
    return _json_job_payload(str(found["job_id"]), run=found)


@app.get("/api/v1/runs/recent")
async def list_recent_runs(
    limit: int = Query(10, ge=1, le=50),
    ctx: AuthContext = Depends(require_authorized_user),
):
    owner = None if is_admin(ctx.user) else str(ctx.user["id"])
    runs = get_db().list_runs(limit=limit, owner_user_id=owner)["items"]
    return {"runs": [_json_job_payload(str(run["job_id"]), run=run) for run in runs]}


@app.get("/api/v1/runs/{job_id}")
async def get_run(job_id: str, request: Request, access_token: str | None = Query(default=None)):
    run, _ctx = await _authorize_run_access(request, job_id, access_token=access_token)
    return _json_job_payload(job_id, run=run)


@app.get("/api/v1/runs/{job_id}/result")
async def get_run_result(job_id: str, request: Request, access_token: str | None = Query(default=None)):
    run, _ctx = await _authorize_run_access(request, job_id, access_token=access_token)
    store = get_store()
    try:
        envelope = store.get_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="job not found")

    if envelope.status == JobStatus.expired or (run and str(run.get("status")) == "expired"):
        raise HTTPException(status_code=410, detail="job expired")
    if run is not None and str(run.get("calculation_status")) != "completed":
        raise HTTPException(status_code=409, detail=f"job not completed (status={run.get('status')})")
    if run is None and envelope.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail=f"job not completed (status={envelope.status.value})")

    try:
        payload = store.get_result(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="result not found")
    return _decorate_result_downloads(payload, access_token=access_token)


@app.get("/api/v1/runs/{job_id}/artifacts/{name}")
async def get_run_artifact(job_id: str, name: str, request: Request, access_token: str | None = Query(default=None)):
    db = get_db()
    run, _ctx = await _authorize_run_access(request, job_id, access_token=access_token)
    if str(run.get("status") or "") == "expired" or str(run.get("expires_at") or "") <= iso_now():
        raise HTTPException(status_code=410, detail="job expired")

    try:
        fallback_path = get_store().artifact_path(job_id, name)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    artifact = db.get_artifact(job_id, name)
    if artifact is not None and str(artifact.get("expires_at") or "") <= iso_now():
        raise HTTPException(status_code=410, detail="artifact expired")

    artifact_path = Path(str((artifact or {}).get("path") or fallback_path))
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path=str(artifact_path), filename=artifact_path.name)


@app.get("/api/v1/admin/users")
async def admin_list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_admin_user),
):
    del ctx
    return get_db().list_users(limit=limit, offset=offset)


@app.post("/api/v1/admin/users")
async def admin_create_user(payload: AdminCreateUserPayload, request: Request, ctx: AuthContext = Depends(require_admin_user)):
    require_csrf_token(request, ctx)
    try:
        username = normalize_username(payload.username)
        email = normalize_email(payload.email)
        role = require_role_name(payload.role)
        if role == "super_admin":
            raise HTTPException(status_code=403, detail="super_admin accounts must be bootstrapped outside the standard UI")
        if role == "admin" and not is_super_admin(ctx.user):
            raise HTTPException(status_code=403, detail="only super_admin can create admin accounts")
        password_hash = hash_password(validate_password(payload.password))
        user = get_db().create_user(
            user_id=f"usr_{secrets.token_hex(8)}",
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=payload.is_active,
            must_change_password=True,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="username or email already exists")
    get_db().audit(
        actor_user_id=str(ctx.user["id"]),
        action="user_created",
        target_type="user",
        target_id=str(user["id"]),
        ip_hash=ip_hash(request),
        user_agent=user_agent(request),
        metadata={"role": user["role"], "is_active": bool(user["is_active"])},
    )
    return {"user": public_user(user)}


@app.patch("/api/v1/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    payload: AdminUpdateUserPayload,
    request: Request,
    ctx: AuthContext = Depends(require_admin_user),
):
    require_csrf_token(request, ctx)
    db = get_db()
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    target_role = str(target.get("role") or "")
    if target_role in {"admin", "super_admin"} and not is_super_admin(ctx.user):
        raise HTTPException(status_code=403, detail="only super_admin can administer admins")
    role = None
    if payload.role is not None:
        role = require_role_name(payload.role)
        if role == "super_admin":
            raise HTTPException(status_code=403, detail="super_admin role cannot be assigned from the standard UI")
        if role == "admin" and not is_super_admin(ctx.user):
            raise HTTPException(status_code=403, detail="only super_admin can assign admin role")
    is_active = payload.is_active
    if str(target.get("id")) == str(ctx.user["id"]) and target_role == "super_admin":
        if is_active is False or (role is not None and role != "super_admin"):
            raise HTTPException(status_code=400, detail="super_admin cannot disable or demote itself")
    try:
        email = normalize_email(payload.email) if payload.email is not None else None
        updated = db.update_user(user_id, email=email, role=role, is_active=is_active)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="email already exists")
    db.audit(
        actor_user_id=str(ctx.user["id"]),
        action="user_updated",
        target_type="user",
        target_id=user_id,
        ip_hash=ip_hash(request),
        user_agent=user_agent(request),
        metadata={"role": role, "is_active": is_active, "email_changed": payload.email is not None},
    )
    return {"user": public_user(updated)}


@app.post("/api/v1/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    payload: AdminResetPasswordPayload,
    request: Request,
    ctx: AuthContext = Depends(require_admin_user),
):
    require_csrf_token(request, ctx)
    db = get_db()
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if str(target.get("role")) in {"admin", "super_admin"} and not is_super_admin(ctx.user):
        raise HTTPException(status_code=403, detail="only super_admin can reset admin passwords")
    try:
        password_hash = hash_password(validate_password(payload.password))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = db.update_user(user_id, password_hash=password_hash, must_change_password=payload.must_change_password)
    db.audit(
        actor_user_id=str(ctx.user["id"]),
        action="password_reset",
        target_type="user",
        target_id=user_id,
        ip_hash=ip_hash(request),
        user_agent=user_agent(request),
        metadata={"must_change_password": payload.must_change_password},
    )
    return {"user": public_user(updated)}


@app.get("/api/v1/admin/users/{user_id}/runs")
async def admin_user_runs(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_admin_user),
):
    del ctx
    if get_db().get_user_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    return get_db().list_runs(limit=limit, offset=offset, owner_user_id=user_id)


@app.get("/api/v1/admin/runs")
async def admin_list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_admin_user),
):
    del ctx
    return get_db().list_runs(limit=limit, offset=offset)


@app.get("/api/v1/admin/activity")
async def admin_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_admin_user),
):
    del ctx
    return get_db().list_audit_logs(limit=limit, offset=offset)
