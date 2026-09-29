from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


SURFACES_PATH = Path(__file__).resolve().parents[2] / "web" / "data" / "user-impact-surfaces.json"


def _drawn_payload(lon: float = -61.53, lat: float = 16.23) -> str:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "asset_id": "A001",
                        "label": "Actif test",
                        "value_eur": 1_000_000,
                        "asset_type": "habitation",
                        "exposure_category": "habitation",
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            ],
        }
    )


def _load_main(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SIB_RISK_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("SIB_RISK_DB_PATH", str(tmp_path / "sib.sqlite3"))
    monkeypatch.setenv("SIB_RISK_USER_IMPACT_SURFACES_PATH", str(SURFACES_PATH))
    monkeypatch.setenv("SIB_RISK_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("SIB_RISK_QUICK_RATE_LIMIT_PER_HOUR", "99")
    monkeypatch.setenv("SIB_BOOTSTRAP_SUPER_ADMIN_USERNAME", "eliosib")
    monkeypatch.setenv("SIB_BOOTSTRAP_SUPER_ADMIN_EMAIL", "super@example.com")
    monkeypatch.setenv("SIB_BOOTSTRAP_SUPER_ADMIN_PASSWORD", "initial-pass-123")
    sys.modules.pop("backend.app.main", None)
    return importlib.import_module("backend.app.main")


def _login(client: TestClient, username: str, password: str) -> dict:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["authenticated"] is True
    assert payload["csrf_token"]
    return payload


def _create_user(client: TestClient, csrf: str, username: str, email: str) -> dict:
    res = client.post(
        "/api/v1/admin/users",
        headers={"x-csrf-token": csrf},
        json={
            "username": username,
            "email": email,
            "password": "initial-pass-123",
            "role": "authorized_user",
            "is_active": True,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["user"]


def test_quick_run_public_generates_maps_pdf_and_xlsx(monkeypatch, tmp_path: Path) -> None:
    main = _load_main(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        res = client.post(
            "/api/v1/runs/quick",
            data={
                "input_mode": "drawn_geojson",
                "drawn_geojson": _drawn_payload(),
                "target_zone": "guadeloupe",
                "default_exposure_category": "habitation",
                "run_label": "quick public",
            },
        )
        assert res.status_code == 201, res.text
        payload = res.json()
        job_id = payload["job_id"]
        token = payload["access_token"]

        assert client.get(f"/api/v1/runs/{job_id}/result").status_code == 403
        authed_result = client.get(f"/api/v1/runs/{job_id}/result", params={"access_token": token})
        assert authed_result.status_code == 200, authed_result.text
        result = authed_result.json()
        assert result["meta"]["engine"] == "precomputed_user_impact_v1"
        assert {item["name"] for item in result["artifacts"]["downloads"]} == {
            "user-results-report.pdf",
            "user-results-matrix.xlsx",
        }
        assert {
            "hazard_map_rp100",
            "network_state_map_rp100",
            "network_state_map_rp1000",
        } <= {item["graph_type"] for item in result["artifacts"]["visuals"]}

        for name in ("user-results-report.pdf", "user-results-matrix.xlsx"):
            artifact = client.get(f"/api/v1/runs/{job_id}/artifacts/{name}", params={"access_token": token})
            assert artifact.status_code == 200, artifact.text
            assert artifact.content

        status = client.get(f"/api/v1/runs/{job_id}", params={"access_token": token})
        assert status.status_code == 200, status.text
        status_payload = status.json()
        assert status_payload["status"] == "completed"
        assert status_payload["calculation_status"] == "completed"
        assert status_payload["output_status"] == "completed"
        assert status_payload["email_status"] == "not_applicable"
        assert client.post(f"/api/v1/runs/{job_id}/delivery", json={"email": "visitor@example.com"}).status_code == 404


def test_admin_accounts_and_complete_run_routes_are_disabled(monkeypatch, tmp_path: Path) -> None:
    main = _load_main(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        admin_login = _login(client, "eliosib", "initial-pass-123")
        assert admin_login["user"]["role"] == "super_admin"
        user = _create_user(client, admin_login["csrf_token"], "analyst", "analyst@example.com")
        future_admin = _create_user(client, admin_login["csrf_token"], "manager", "manager@example.com")

        demote = client.patch(
            f"/api/v1/admin/users/{admin_login['user']['id']}",
            headers={"x-csrf-token": admin_login["csrf_token"]},
            json={"role": "authorized_user"},
        )
        assert demote.status_code == 400

        promote = client.patch(
            f"/api/v1/admin/users/{future_admin['id']}",
            headers={"x-csrf-token": admin_login["csrf_token"]},
            json={"role": "admin"},
        )
        assert promote.status_code == 200, promote.text
        assert promote.json()["user"]["role"] == "admin"

        users = client.get("/api/v1/admin/users")
        assert users.status_code == 200
        assert any(row["username"] == "analyst" for row in users.json()["items"])

        client.post("/api/v1/auth/logout", headers={"x-csrf-token": admin_login["csrf_token"]}, json={})
        assert client.post("/api/v1/runs/complete", data={"input_mode": "drawn_geojson"}).status_code == 405
        assert client.post("/api/v1/runs", data={"input_mode": "drawn_geojson"}).status_code == 404

        analyst_login = _login(client, "analyst", "initial-pass-123")
        assert client.get("/api/v1/admin/users").status_code == 403

        client.post("/api/v1/auth/logout", headers={"x-csrf-token": analyst_login["csrf_token"]}, json={})
        second_admin_login = _login(client, "eliosib", "initial-pass-123")
        _create_user(client, second_admin_login["csrf_token"], "other", "other@example.com")
        client.post("/api/v1/auth/logout", headers={"x-csrf-token": second_admin_login["csrf_token"]}, json={})
        other_login = _login(client, "other", "initial-pass-123")
        assert other_login["user"]["id"] != user["id"]
