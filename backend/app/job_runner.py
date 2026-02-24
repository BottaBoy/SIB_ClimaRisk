from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
import traceback

from .config import Settings
from .job_store import JobStore
from .models import JobError, JobStatus
from .risk_engine.errors import DependencyMissingError, InputValidationError
from .risk_engine.pipeline import run_job_pipeline


class JobProcessor:
    def __init__(self, *, settings: Settings, store: JobStore) -> None:
        self.settings = settings
        self.store = store
        self._queue: Queue[str] = Queue()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._worker_loop, name="sib-risk-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def enqueue(self, job_id: str) -> None:
        self._queue.put(job_id)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._process_one(job_id)
            finally:
                self._queue.task_done()

    def _process_one(self, job_id: str) -> None:
        self.store.update_job(job_id, status=JobStatus.running, stage="ingest", progress=0.05, message="Validating input")
        params = self.store.get_params(job_id)
        try:
            self.store.update_job(job_id, stage="disaggregation", progress=0.25, message="Preparing exposure geometry")
            self.store.update_job(job_id, stage="impact_calc", progress=0.55, message="Computing STORM and STORM_CMCC impacts")
            result = run_job_pipeline(job_id, params, self.settings, self.store)
            self.store.save_result(job_id, result)
            self.store.update_job(job_id, status=JobStatus.completed, stage="completed", progress=1.0, message="Run completed")
        except InputValidationError as exc:
            self.store.update_job(
                job_id,
                status=JobStatus.failed,
                stage="failed",
                progress=1.0,
                message="Input validation failed",
                error=JobError(code="INPUT_VALIDATION", message=str(exc)),
            )
        except DependencyMissingError as exc:
            self.store.update_job(
                job_id,
                status=JobStatus.failed,
                stage="failed",
                progress=1.0,
                message="Server dependency missing",
                error=JobError(code="DEPENDENCY_MISSING", message=str(exc)),
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.store.update_job(
                job_id,
                status=JobStatus.failed,
                stage="failed",
                progress=1.0,
                message="Unexpected server error",
                error=JobError(
                    code="UNEXPECTED_ERROR",
                    message=str(exc),
                    details={"traceback": traceback.format_exc(limit=20)},
                ),
            )
