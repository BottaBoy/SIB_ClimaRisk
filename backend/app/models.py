from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class RunInputMode(str, Enum):
    file = "file"
    drawn_geojson = "drawn_geojson"


class JobError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class JobEnvelope(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    progress: float = Field(ge=0.0, le=1.0)
    stage: str
    message: str | None = None
    error: JobError | None = None


class RunResultMeta(BaseModel):
    title: str
    source: str
    job_id: str | None = None
    updated_at: datetime
    unit_currency: str
    currency_display_unit: str
    sampling_spacing_m: float
    impact_function: str
    hazards: list[str]


class HealthResponse(BaseModel):
    status: str
    app: str
    now_utc: datetime
    job_root: str
    optional_dependencies: dict[str, bool]
    demo_result_available: bool
    data_files: dict[str, bool] | None = None
    climada_runtime_ready: bool | None = None
    impact_engine_mode: str | None = None
    fallback_allowed: bool | None = None
