#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password, normalize_email, normalize_username  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import AppDatabase  # noqa: E402


def main() -> int:
    settings = load_settings()
    db = AppDatabase(settings.db_path)
    db.init_schema()

    username = normalize_username(os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_USERNAME") or input("Username: "))
    email = normalize_email(os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_EMAIL") or input("Reception email: "))
    password = os.environ.get("SIB_BOOTSTRAP_SUPER_ADMIN_PASSWORD") or getpass.getpass("Initial password: ")

    existing = db.get_user_by_username(username)
    if existing:
        db.update_user(
            str(existing["id"]),
            email=email,
            role="super_admin",
            is_active=True,
            password_hash=hash_password(password),
            must_change_password=True,
        )
        print(f"Updated existing super_admin account: {username}")
        return 0

    db.create_user(
        user_id=f"usr_{secrets.token_hex(8)}",
        username=username,
        email=email,
        password_hash=hash_password(password),
        role="super_admin",
        is_active=True,
        must_change_password=True,
    )
    print(f"Created super_admin account: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
