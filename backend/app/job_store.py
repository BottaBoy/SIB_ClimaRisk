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
    def __init__(self, root: Path, ttl_hours: int = 24, max_runs_kept: int = 10) -> None:
        self.root = root
        self.ttl_hours = ttl_hours
        self.max_runs_kept = max(1, int(max_runs_kept))
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
            self._prune_jobs_locked(exclude_job_ids={job_id})
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
        with self._lock:
            removed, _ = self._prune_jobs_locked()
            return removed

    def find_latest_by_run_label(self, run_label_query: str) -> dict[str, Any] | None:
        query = str(run_label_query or "").strip().lower()
        if not query:
            return None
        with self._lock:
            self._prune_jobs_locked()
            records = self._collect_records_locked()
            if not records:
                return None
            exact_matches = [rec for rec in records if rec["run_label"].lower() == query]
            partial_matches = [rec for rec in records if query in rec["run_label"].lower()]
            candidates = exact_matches or partial_matches
            if not candidates:
                return None
            candidates.sort(
                key=lambda rec: (
                    rec["envelope"].created_at.timestamp(),
                    rec["envelope"].updated_at.timestamp(),
                ),
                reverse=True,
            )
            selected = candidates[0]
            return self._record_to_run_summary(selected)

    def list_recent_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_jobs_locked()
            records = self._collect_records_locked()
            records.sort(
                key=lambda rec: (
                    rec["envelope"].created_at.timestamp(),
                    rec["envelope"].updated_at.timestamp(),
                ),
                reverse=True,
            )
            out: list[dict[str, Any]] = []
            for rec in records[: max(1, int(limit))]:
                out.append(self._record_to_run_summary(rec))
            return out

    def _record_to_run_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        envelope: JobEnvelope = record["envelope"]
        input_mode = str(record["input_mode"]).strip().lower() or "file"
        dataset_mode = "drawn" if input_mode == "drawn_geojson" else "uploaded"
        run_label = str(record["run_label"] or "").strip() or envelope.job_id
        return {
            "job_id": envelope.job_id,
            "run_label": run_label,
            "input_mode": input_mode,
            "dataset_mode": dataset_mode,
            "status": envelope.status.value,
            "stage": envelope.stage,
            "progress": envelope.progress,
            "message": envelope.message,
            "created_at": envelope.created_at,
            "updated_at": envelope.updated_at,
        }

    def _collect_records_locked(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
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
            params: dict[str, Any] = {}
            params_path = child / "params.json"
            if params_path.exists():
                try:
                    params = self._read_json(params_path)
                except Exception:
                    params = {}
            records.append(
                {
                    "dir": child,
                    "envelope": envelope,
                    "run_label": str(params.get("run_label") or "").strip(),
                    "input_mode": str(params.get("input_mode") or "").strip(),
                }
            )
        return records

    def _remove_job_dir_locked(self, job_dir: Path) -> bool:
        if not job_dir.exists():
            return False
        if not job_dir.is_dir():
            return False
        shutil.rmtree(job_dir, ignore_errors=True)
        return True

    def _prune_jobs_locked(self, exclude_job_ids: set[str] | None = None) -> tuple[list[str], list[str]]:
        removed: list[str] = []
        kept: list[str] = []
        excluded = exclude_job_ids or set()
        now = self._now()
        records = self._collect_records_locked()

        # Step 1: always delete expired runs first.
        for record in records:
            envelope: JobEnvelope = record["envelope"]
            job_dir: Path = record["dir"]
            if envelope.expires_at <= now and envelope.job_id not in excluded:
                if self._remove_job_dir_locked(job_dir):
                    removed.append(envelope.job_id)
                continue
            kept.append(envelope.job_id)

        # Step 2: enforce max retained runs (prefer dropping oldest terminal runs).
        if len(kept) <= self.max_runs_kept:
            return removed, kept

        fresh_records = self._collect_records_locked()
        terminal = {JobStatus.completed, JobStatus.failed, JobStatus.expired}
        candidates = [
            rec
            for rec in fresh_records
            if rec["envelope"].job_id not in excluded and rec["envelope"].status in terminal
        ]
        candidates.sort(key=lambda rec: rec["envelope"].created_at.timestamp())

        idx = 0
        while len(fresh_records) > self.max_runs_kept and idx < len(candidates):
            rec = candidates[idx]
            idx += 1
            envelope: JobEnvelope = rec["envelope"]
            job_dir: Path = rec["dir"]
            if self._remove_job_dir_locked(job_dir):
                removed.append(envelope.job_id)
                fresh_records = [r for r in fresh_records if r["envelope"].job_id != envelope.job_id]

        kept = [rec["envelope"].job_id for rec in fresh_records]
        return removed, kept

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
