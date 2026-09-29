from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from threading import Lock
from typing import Any
import hashlib
import json
import sqlite3
import time


UTC = timezone.utc
ACTIVE_COMPLETE_STATUSES = ("queued", "running", "generating_outputs", "sending_email")
USER_ROLES = ("authorized_user", "admin", "super_admin")
ADMIN_ROLES = ("admin", "super_admin")


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso_now() -> str:
    return now_utc().isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int


class AppDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init_schema(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('authorized_user', 'admin', 'super_admin')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ip_hash TEXT,
                    user_agent TEXT
                );

                CREATE TABLE IF NOT EXISTS runs (
                    job_id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL CHECK (run_type IN ('quick', 'complete')),
                    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    public_token_hash TEXT,
                    input_mode TEXT,
                    run_label TEXT,
                    target_zone TEXT,
                    basin_ids TEXT,
                    track_count_requested INTEGER,
                    track_count_storm INTEGER,
                    track_count_storm_cmcc INTEGER,
                    status TEXT NOT NULL,
                    calculation_status TEXT NOT NULL DEFAULT 'queued',
                    output_status TEXT NOT NULL DEFAULT 'pending',
                    email_status TEXT NOT NULL DEFAULT 'not_requested',
                    stage TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0.0,
                    eta_seconds INTEGER,
                    eta_source TEXT,
                    message TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    heartbeat_at TEXT,
                    expires_at TEXT NOT NULL,
                    result_path TEXT,
                    artifact_dir TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_runs_owner_created ON runs(owner_user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_runs_expires ON runs(expires_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_one_active_complete_per_user
                    ON runs(owner_user_id)
                    WHERE run_type = 'complete'
                      AND owner_user_id IS NOT NULL
                      AND status IN ('queued', 'running', 'generating_outputs', 'sending_email');

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES runs(job_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    sha256 TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(job_id, filename)
                );

                CREATE TABLE IF NOT EXISTS email_deliveries (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES runs(job_id) ON DELETE CASCADE,
                    recipient_email TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_email_deliveries_job ON email_deliveries(job_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    ip_hash TEXT,
                    user_agent TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);

                CREATE TABLE IF NOT EXISTS rate_limits (
                    route TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    window_start INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(route, key_hash, window_start)
                );
                """
            )

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        email: str,
        password_hash: str,
        role: str = "authorized_user",
        is_active: bool = True,
        must_change_password: bool = True,
    ) -> dict[str, Any]:
        if role not in USER_ROLES:
            raise ValueError(f"unsupported role: {role}")
        now = iso_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, email, password_hash, role, is_active,
                    must_change_password, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    email,
                    password_hash,
                    role,
                    1 if is_active else 0,
                    1 if must_change_password else 0,
                    now,
                    now,
                ),
            )
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("created user not found")
        return user

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        must_change_password: bool | None = None,
        last_login_at: str | None = None,
    ) -> dict[str, Any]:
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [iso_now()]
        if email is not None:
            assignments.append("email = ?")
            values.append(email)
        if role is not None:
            if role not in USER_ROLES:
                raise ValueError(f"unsupported role: {role}")
            assignments.append("role = ?")
            values.append(role)
        if is_active is not None:
            assignments.append("is_active = ?")
            values.append(1 if is_active else 0)
        if password_hash is not None:
            assignments.append("password_hash = ?")
            values.append(password_hash)
        if must_change_password is not None:
            assignments.append("must_change_password = ?")
            values.append(1 if must_change_password else 0)
        if last_login_at is not None:
            assignments.append("last_login_at = ?")
            values.append(last_login_at)
        values.append(user_id)
        with self._lock, self.connect() as conn:
            conn.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id = ?", values)
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def list_users(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        active_sql = ",".join("?" for _ in ACTIVE_COMPLETE_STATUSES)
        with self.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
            rows = conn.execute(
                f"""
                SELECT
                    u.id, u.username, u.email, u.role, u.is_active,
                    u.must_change_password, u.created_at, u.updated_at, u.last_login_at,
                    COUNT(r.job_id) AS total_runs,
                    MAX(r.created_at) AS last_run_at,
                    MAX(CASE WHEN r.status IN ({active_sql}) THEN 1 ELSE 0 END) AS has_active_run
                FROM users u
                LEFT JOIN runs r ON r.owner_user_id = u.id
                GROUP BY u.id
                ORDER BY u.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (*ACTIVE_COMPLETE_STATUSES, limit, offset),
            ).fetchall()
        return {"items": [_row_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def create_session(
        self,
        *,
        session_id_hash: str,
        user_id: str,
        csrf_token: str,
        expires_at: datetime,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> None:
        now = iso_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, csrf_token, created_at, expires_at, last_seen_at, ip_hash, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id_hash, user_id, csrf_token, now, expires_at.replace(microsecond=0).isoformat(), now, ip_hash, user_agent),
            )

    def get_session_with_user(self, session_id_hash: str) -> dict[str, Any] | None:
        now = iso_now()
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    s.id AS session_id, s.csrf_token, s.expires_at, s.last_seen_at,
                    u.id AS user_id, u.username, u.email, u.role, u.is_active,
                    u.must_change_password, u.created_at, u.last_login_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.id = ?
                """,
                (session_id_hash,),
            ).fetchone()
            if row is None:
                return None
            payload = _row_to_dict(row)
            if str(payload.get("expires_at") or "") <= now:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id_hash,))
                return None
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, session_id_hash))
            return payload

    def delete_session(self, session_id_hash: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id_hash,))

    def prune_sessions(self) -> int:
        with self._lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_now(),))
            return int(cur.rowcount or 0)

    def create_run(
        self,
        *,
        job_id: str,
        run_type: str,
        input_mode: str,
        expires_at: str,
        owner_user_id: str | None = None,
        public_token_hash: str | None = None,
        run_label: str | None = None,
        target_zone: str | None = None,
        track_count_requested: int | None = None,
        artifact_dir: str | None = None,
        status: str = "queued",
        calculation_status: str = "queued",
        output_status: str = "pending",
        email_status: str = "not_requested",
        stage: str = "queued",
        progress: float = 0.0,
        message: str | None = None,
    ) -> dict[str, Any]:
        if run_type not in {"quick", "complete"}:
            raise ValueError(f"unsupported run_type: {run_type}")
        now = iso_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    job_id, run_type, owner_user_id, public_token_hash, input_mode,
                    run_label, target_zone, track_count_requested, status,
                    calculation_status, output_status, email_status, stage, progress,
                    message, created_at, updated_at, expires_at, artifact_dir
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_type,
                    owner_user_id,
                    public_token_hash,
                    input_mode,
                    run_label,
                    target_zone,
                    track_count_requested,
                    status,
                    calculation_status,
                    output_status,
                    email_status,
                    stage,
                    max(0.0, min(1.0, float(progress))),
                    message,
                    now,
                    now,
                    expires_at,
                    artifact_dir,
                ),
            )
        run = self.get_run(job_id)
        if run is None:
            raise RuntimeError("created run not found")
        return run

    def get_run(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(conn.execute("SELECT * FROM runs WHERE job_id = ?", (job_id,)).fetchone())

    def update_run(self, job_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "calculation_status",
            "output_status",
            "email_status",
            "stage",
            "progress",
            "eta_seconds",
            "eta_source",
            "message",
            "error_code",
            "error_message",
            "started_at",
            "finished_at",
            "heartbeat_at",
            "result_path",
            "artifact_dir",
            "basin_ids",
            "track_count_storm",
            "track_count_storm_cmcc",
        }
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [iso_now()]
        for key, value in fields.items():
            if key not in allowed:
                raise KeyError(key)
            assignments.append(f"{key} = ?")
            if key == "progress" and value is not None:
                value = max(0.0, min(1.0, float(value)))
            values.append(value)
        values.append(job_id)
        with self._lock, self.connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE job_id = ?", values)
        run = self.get_run(job_id)
        if run is None:
            raise KeyError(job_id)
        return run

    def claim_next_complete_run(self, *, worker_id: str) -> dict[str, Any] | None:
        del worker_id
        with self._lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE run_type = 'complete' AND status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            job_id = str(row["job_id"])
            now = iso_now()
            conn.execute(
                """
                UPDATE runs
                SET status = 'running',
                    calculation_status = 'running',
                    stage = 'ingest',
                    progress = 0.03,
                    started_at = COALESCE(started_at, ?),
                    heartbeat_at = ?,
                    updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, now, job_id),
            )
            conn.commit()
        return self.get_run(job_id)

    def active_complete_run_for_user(self, user_id: str) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in ACTIVE_COMPLETE_STATUSES)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM runs
                WHERE owner_user_id = ?
                  AND run_type = 'complete'
                  AND status IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, *ACTIVE_COMPLETE_STATUSES),
            ).fetchone()
            return _row_to_dict(row)

    def list_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        where = ""
        values: list[Any] = []
        if owner_user_id:
            where = "WHERE r.owner_user_id = ?"
            values.append(owner_user_id)
        with self.connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) AS c FROM runs r {where}", values).fetchone()["c"])
            rows = conn.execute(
                f"""
                SELECT r.*, u.username AS owner_username, u.email AS owner_email,
                    (
                        SELECT GROUP_CONCAT(a.filename, ',')
                        FROM run_artifacts a
                        WHERE a.job_id = r.job_id
                    ) AS artifact_filenames
                FROM runs r
                LEFT JOIN users u ON u.id = r.owner_user_id
                {where}
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (*values, limit, offset),
            ).fetchall()
        return {"items": [_row_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def find_run_by_label(self, query: str, *, owner_user_id: str | None = None) -> dict[str, Any] | None:
        text = str(query or "").strip()
        if not text:
            return None
        where = "WHERE lower(COALESCE(r.run_label, '')) LIKE ?"
        values: list[Any] = [f"%{text.lower()}%"]
        if owner_user_id:
            where += " AND r.owner_user_id = ?"
            values.append(owner_user_id)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT r.*, u.username AS owner_username, u.email AS owner_email,
                    (
                        SELECT GROUP_CONCAT(a.filename, ',')
                        FROM run_artifacts a
                        WHERE a.job_id = r.job_id
                    ) AS artifact_filenames
                FROM runs r
                LEFT JOIN users u ON u.id = r.owner_user_id
                {where}
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                values,
            ).fetchone()
            return _row_to_dict(row)

    def historical_duration_seconds(self, *, run_type: str = "complete", limit: int = 25) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT started_at, finished_at
                FROM runs
                WHERE run_type = ?
                  AND calculation_status = 'completed'
                  AND started_at IS NOT NULL
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (run_type, max(1, int(limit))),
            ).fetchall()
        values: list[int] = []
        for row in rows:
            try:
                start = datetime.fromisoformat(str(row["started_at"]))
                end = datetime.fromisoformat(str(row["finished_at"]))
            except Exception:
                continue
            seconds = int((end - start).total_seconds())
            if seconds > 0:
                values.append(seconds)
        return values

    def median_duration_seconds(self, *, run_type: str = "complete") -> int | None:
        values = self.historical_duration_seconds(run_type=run_type)
        if not values:
            return None
        return int(median(values))

    def register_artifact(
        self,
        *,
        artifact_id: str,
        job_id: str,
        kind: str,
        filename: str,
        path: Path,
        mime_type: str,
        expires_at: str,
    ) -> dict[str, Any]:
        raw = Path(path).read_bytes() if Path(path).exists() else b""
        digest = hashlib.sha256(raw).hexdigest() if raw else None
        size = len(raw)
        now = iso_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_artifacts (id, job_id, kind, filename, path, mime_type, size_bytes, sha256, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, filename) DO UPDATE SET
                    kind = excluded.kind,
                    path = excluded.path,
                    mime_type = excluded.mime_type,
                    size_bytes = excluded.size_bytes,
                    sha256 = excluded.sha256,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (artifact_id, job_id, kind, filename, str(path), mime_type, size, digest, now, expires_at),
            )
        artifact = self.get_artifact(job_id, filename)
        if artifact is None:
            raise RuntimeError("registered artifact not found")
        return artifact

    def get_artifact(self, job_id: str, filename: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM run_artifacts WHERE job_id = ? AND filename = ?",
                    (job_id, filename),
                ).fetchone()
            )

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_artifacts WHERE job_id = ? ORDER BY created_at ASC",
                (job_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def create_email_delivery(self, *, delivery_id: str, job_id: str, recipient_email: str) -> dict[str, Any]:
        now = iso_now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO email_deliveries (id, job_id, recipient_email, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', 0, ?, ?)
                """,
                (delivery_id, job_id, recipient_email, now, now),
            )
        delivery = self.get_email_delivery(delivery_id)
        if delivery is None:
            raise RuntimeError("created delivery not found")
        return delivery

    def get_email_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(conn.execute("SELECT * FROM email_deliveries WHERE id = ?", (delivery_id,)).fetchone())

    def latest_email_delivery(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM email_deliveries WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
            )

    def update_email_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        last_error: str | None = None,
        sent_at: str | None = None,
        increment_attempts: bool = False,
    ) -> dict[str, Any]:
        now = iso_now()
        attempts_sql = "attempts = attempts + 1," if increment_attempts else ""
        with self._lock, self.connect() as conn:
            conn.execute(
                f"""
                UPDATE email_deliveries
                SET status = ?,
                    {attempts_sql}
                    last_error = ?,
                    sent_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, last_error, sent_at, now, delivery_id),
            )
        delivery = self.get_email_delivery(delivery_id)
        if delivery is None:
            raise KeyError(delivery_id)
        return delivery

    def audit(
        self,
        *,
        actor_user_id: str | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        ip_hash: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (actor_user_id, action, target_type, target_id, ip_hash, user_agent, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (actor_user_id, action, target_type, target_id, ip_hash, user_agent, _json_dumps(metadata), iso_now()),
            )

    def list_audit_logs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM audit_logs").fetchone()["c"])
            rows = conn.execute(
                """
                SELECT a.*, u.username AS actor_username
                FROM audit_logs a
                LEFT JOIN users u ON u.id = a.actor_user_id
                ORDER BY a.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [_row_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def check_rate_limit(
        self,
        *,
        route: str,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitResult(True, 0, int(limit), 0)
        now_ts = int(time.time())
        window_start = now_ts - (now_ts % int(window_seconds))
        retry_after = max(1, int(window_seconds) - (now_ts - window_start))
        key_hash = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
        with self._lock, self.connect() as conn:
            cutoff = now_ts - max(int(window_seconds) * 4, 3600)
            conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (cutoff,))
            row = conn.execute(
                "SELECT count FROM rate_limits WHERE route = ? AND key_hash = ? AND window_start = ?",
                (route, key_hash, window_start),
            ).fetchone()
            count = int(row["count"]) if row else 0
            if count >= int(limit):
                return RateLimitResult(False, count, int(limit), retry_after)
            count += 1
            conn.execute(
                """
                INSERT INTO rate_limits (route, key_hash, window_start, count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(route, key_hash, window_start) DO UPDATE SET
                    count = excluded.count,
                    updated_at = excluded.updated_at
                """,
                (route, key_hash, window_start, count, iso_now()),
            )
        return RateLimitResult(True, count, int(limit), retry_after)

    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        now_iso = (now or now_utc()).replace(microsecond=0).isoformat()
        with self._lock, self.connect() as conn:
            artifact_rows = conn.execute("SELECT path FROM run_artifacts WHERE expires_at <= ?", (now_iso,)).fetchall()
            artifacts_deleted = 0
            for row in artifact_rows:
                path = Path(str(row["path"]))
                try:
                    if path.exists() and path.is_file():
                        path.unlink()
                        artifacts_deleted += 1
                except Exception:
                    continue
            conn.execute("DELETE FROM run_artifacts WHERE expires_at <= ?", (now_iso,))
            conn.execute(
                """
                UPDATE runs
                SET status = 'expired', stage = 'expired', updated_at = ?
                WHERE expires_at <= ?
                  AND status NOT IN ('expired', 'running', 'generating_outputs', 'sending_email')
                """,
                (now_iso, now_iso),
            )
            conn.execute(
                """
                UPDATE email_deliveries
                SET recipient_email = '[expired]', updated_at = ?
                WHERE job_id IN (SELECT job_id FROM runs WHERE expires_at <= ? AND owner_user_id IS NULL)
                """,
                (now_iso, now_iso),
            )
        return {"artifacts_deleted": artifacts_deleted}

    def reconcile_stale_active_runs(self, *, stale_after_minutes: int = 30) -> dict[str, int]:
        cutoff = (now_utc() - timedelta(minutes=max(1, int(stale_after_minutes)))).isoformat()
        now = iso_now()
        with self._lock, self.connect() as conn:
            running = conn.execute(
                """
                UPDATE runs
                SET status = 'failed',
                    calculation_status = 'failed',
                    stage = 'failed',
                    finished_at = ?,
                    updated_at = ?,
                    error_code = 'STALE_RUN',
                    error_message = 'Run marked failed after missing worker heartbeat',
                    message = 'Run bloque apres redemarrage ou perte de heartbeat'
                WHERE run_type = 'complete'
                  AND status = 'running'
                  AND COALESCE(heartbeat_at, started_at, updated_at) < ?
                """,
                (now, now, cutoff),
            ).rowcount
            outputs = conn.execute(
                """
                UPDATE runs
                SET status = 'completed',
                    output_status = 'failed',
                    stage = 'completed',
                    finished_at = ?,
                    updated_at = ?,
                    error_code = 'STALE_OUTPUT_GENERATION',
                    error_message = 'Output generation interrupted after calculation completed',
                    message = 'Calcul termine, generation des fichiers interrompue'
                WHERE run_type = 'complete'
                  AND status = 'generating_outputs'
                  AND COALESCE(heartbeat_at, updated_at) < ?
                """,
                (now, now, cutoff),
            ).rowcount
            emails = conn.execute(
                """
                UPDATE runs
                SET status = 'completed',
                    email_status = 'failed',
                    stage = 'completed',
                    finished_at = ?,
                    updated_at = ?,
                    error_code = 'STALE_EMAIL_SEND',
                    error_message = 'Email sending interrupted after calculation completed',
                    message = 'Calcul termine, envoi e-mail interrompu'
                WHERE run_type = 'complete'
                  AND status = 'sending_email'
                  AND COALESCE(heartbeat_at, updated_at) < ?
                """,
                (now, now, cutoff),
            ).rowcount
        return {"running_failed": int(running or 0), "outputs_failed": int(outputs or 0), "emails_failed": int(emails or 0)}
