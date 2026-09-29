from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from email.utils import parseaddr
from typing import Any, Callable
import base64
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request, Response

from .db import ADMIN_ROLES, USER_ROLES, AppDatabase, now_utc


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_SCHEME = "pbkdf2_sha256"
DEFAULT_PASSWORD_ITERATIONS = 390_000


@dataclass(frozen=True)
class AuthContext:
    user: dict[str, Any]
    csrf_token: str
    session_id_hash: str


def normalize_username(value: str) -> str:
    username = str(value or "").strip()
    if not username:
        raise ValueError("username is required")
    if len(username) < 3 or len(username) > 80:
        raise ValueError("username must be between 3 and 80 characters")
    if not re.match(r"^[A-Za-z0-9_.@-]+$", username):
        raise ValueError("username contains unsupported characters")
    return username


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    parsed = parseaddr(email)[1]
    if parsed != email or not EMAIL_RE.match(email):
        raise ValueError("invalid email address")
    return email


def validate_password(value: str) -> str:
    password = str(value or "")
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    return password


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def hash_password(password: str, *, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> str:
    password = validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return f"{PASSWORD_SCHEME}${int(iterations)}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = str(password_hash or "").split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = _unb64(salt_raw)
        expected = _unb64(digest_raw)
        actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def ip_hash(request: Request) -> str:
    return token_hash(client_ip(request))


def user_agent(request: Request) -> str:
    return str(request.headers.get("user-agent") or "")[:500]


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id") or user.get("user_id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role"),
        "is_active": bool(user.get("is_active")),
        "must_change_password": bool(user.get("must_change_password")),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def require_role_name(value: str) -> str:
    role = str(value or "").strip()
    if role not in USER_ROLES:
        raise ValueError("invalid role")
    return role


def is_authorized_user(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") in USER_ROLES and int(user.get("is_active") or 0) == 1)


def is_admin(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") in ADMIN_ROLES and int(user.get("is_active") or 0) == 1)


def is_super_admin(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") == "super_admin" and int(user.get("is_active") or 0) == 1)


def set_session_cookie(response: Response, *, settings: Any, raw_session_token: str, expires_seconds: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_session_token,
        max_age=max(60, int(expires_seconds)),
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite=str(settings.session_cookie_samesite),
        path="/",
    )


def clear_session_cookie(response: Response, *, settings: Any) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=bool(settings.session_cookie_secure),
        samesite=str(settings.session_cookie_samesite),
    )


async def current_auth_context(request: Request) -> AuthContext | None:
    settings = request.app.state.settings
    db: AppDatabase = request.app.state.db
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None
    session = db.get_session_with_user(token_hash(raw_token))
    if session is None:
        return None
    if int(session.get("is_active") or 0) != 1:
        return None
    user = {
        "id": session.get("user_id"),
        "username": session.get("username"),
        "email": session.get("email"),
        "role": session.get("role"),
        "is_active": session.get("is_active"),
        "must_change_password": session.get("must_change_password"),
        "created_at": session.get("created_at"),
        "last_login_at": session.get("last_login_at"),
    }
    return AuthContext(user=user, csrf_token=str(session.get("csrf_token") or ""), session_id_hash=str(session.get("session_id") or ""))


async def require_user(request: Request) -> AuthContext:
    ctx = await current_auth_context(request)
    if ctx is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return ctx


def require_roles(*roles: str) -> Callable[[Request], Any]:
    async def _dep(request: Request) -> AuthContext:
        ctx = await require_user(request)
        if ctx.user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return ctx

    return _dep


async def require_authorized_user(request: Request) -> AuthContext:
    return await require_roles(*USER_ROLES)(request)


async def require_admin_user(request: Request) -> AuthContext:
    return await require_roles(*ADMIN_ROLES)(request)


async def require_super_admin_user(request: Request) -> AuthContext:
    return await require_roles("super_admin")(request)


def require_csrf_token(request: Request, ctx: AuthContext) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    header = request.headers.get("x-csrf-token")
    if not header or not hmac.compare_digest(str(header), str(ctx.csrf_token)):
        raise HTTPException(status_code=403, detail="invalid csrf token")


def create_login_session(
    *,
    db: AppDatabase,
    response: Response,
    settings: Any,
    user: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    raw_session = new_token()
    csrf_token = new_token()
    session_hours = max(1, int(settings.session_ttl_hours))
    expires_at = now_utc() + timedelta(hours=session_hours)
    db.create_session(
        session_id_hash=token_hash(raw_session),
        user_id=str(user["id"]),
        csrf_token=csrf_token,
        expires_at=expires_at,
        ip_hash=ip_hash(request),
        user_agent=user_agent(request),
    )
    db.update_user(str(user["id"]), last_login_at=now_utc().isoformat())
    set_session_cookie(response, settings=settings, raw_session_token=raw_session, expires_seconds=session_hours * 3600)
    return {"csrf_token": csrf_token, "expires_at": expires_at.replace(microsecond=0).isoformat()}
