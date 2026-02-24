from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
import json
import secrets
import shutil
from typing import Any

from .models import JobEnvelope, JobError, JobStatus


UTC = timezone.utc


class JobStore:
    def __init__(self, root: Path, ttl_hours: int = 24) -> None:
        self.root = root
        self.ttl_hours = ttl_hours
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _job_meta_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _job_result_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "result.json"

    def _job_params_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "params.json"

    def _job_artifacts_dir(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "artifacts"

    def _job_uploads_dir(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "uploads"

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def create_job(self, *, params: dict[str, Any]) -> JobEnvelope:
        with self._lock:
            now = self._now()
            job_id = f"jr_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
            job_dir = self._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=False)
            self._job_artifacts_dir(job_id).mkdir(parents=True, exist_ok=True)
            self._job_uploads_dir(job_id).mkdir(parents=True, exist_ok=True)
            expires_at = now + timedelta(hours=self.ttl_hours)
            envelope = JobEnvelope(
                job_id=job_id,
                status=JobStatus.queued,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                progress=0.0,
                stage="queued",
                message="Job accepted",
                error=None,
            )
            self._write_json(self._job_meta_path(job_id), envelope.model_dump(mode="json"))
            self._write_json(self._job_params_path(job_id), params)
            return envelope

    def get_job(self, job_id: str) -> JobEnvelope:
        path = self._job_meta_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        payload = self._read_json(path)
        envelope = JobEnvelope.model_validate(payload)
        if envelope.status != JobStatus.expired and envelope.expires_at <= self._now():
            payload["status"] = JobStatus.expired.value
            payload["stage"] = "expired"
            payload["message"] = "Job artifacts expired"
            payload["updated_at"] = self._now().isoformat()
            self._write_json(path, payload)
            envelope = JobEnvelope.model_validate(payload)
        return envelope

    def get_params(self, job_id: str) -> dict[str, Any]:
        path = self._job_params_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        return self._read_json(path)

    def set_params(self, job_id: str, params: dict[str, Any]) -> None:
        self._write_json(self._job_params_path(job_id), params)

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        stage: str | None = None,
        message: str | None = None,
        progress: float | None = None,
        error: JobError | None = None,
    ) -> JobEnvelope:
        with self._lock:
            current = self.get_job(job_id)
            payload = current.model_dump(mode="json")
            payload["updated_at"] = self._now().isoformat()
            if status is not None:
                payload["status"] = status.value
            if stage is not None:
                payload["stage"] = stage
            if message is not None:
                payload["message"] = message
            if progress is not None:
                payload["progress"] = max(0.0, min(1.0, float(progress)))
            payload["error"] = error.model_dump(mode="json") if error else None
            self._write_json(self._job_meta_path(job_id), payload)
            return JobEnvelope.model_validate(payload)

    def save_result(self, job_id: str, result: dict[str, Any]) -> Path:
        path = self._job_result_path(job_id)
        self._write_json(path, result)
        return path

    def get_result(self, job_id: str) -> dict[str, Any]:
        path = self._job_result_path(job_id)
        if not path.exists():
            raise FileNotFoundError(job_id)
        return self._read_json(path)

    def save_artifact_bytes(self, job_id: str, name: str, content: bytes) -> Path:
        safe_name = Path(name).name
        target = self._job_artifacts_dir(job_id) / safe_name
        target.write_bytes(content)
        return target

    def artifact_path(self, job_id: str, name: str) -> Path:
        safe_name = Path(name).name
        path = (self._job_artifacts_dir(job_id) / safe_name).resolve()
        if self._job_artifacts_dir(job_id).resolve() not in path.parents:
            raise ValueError("invalid artifact path")
        return path

    def upload_path(self, job_id: str, name: str) -> Path:
        safe_name = Path(name).name
        path = (self._job_uploads_dir(job_id) / safe_name).resolve()
        if self._job_uploads_dir(job_id).resolve() not in path.parents:
            raise ValueError("invalid upload path")
        return path

    def cleanup_expired(self) -> list[str]:
        removed: list[str] = []
        now = self._now()
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            meta = child / "job.json"
            if not meta.exists():
                continue
            try:
                envelope = JobEnvelope.model_validate(self._read_json(meta))
            except Exception:
                continue
            if envelope.expires_at <= now:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)
        return removed

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
