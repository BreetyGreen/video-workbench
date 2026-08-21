from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'setup.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_fresh_home_redirects_to_setup(client: TestClient):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/setup"


def test_confirmed_local_mode_opens_workbench(client: TestClient):
    saved = client.put("/api/setup/preferences", json={"local_mode_confirmed": True})

    assert saved.status_code == 200
    assert saved.json() == {"local_mode_confirmed": True}
    page = client.get("/")
    assert page.status_code == 200
    assert "今天想让观众记住什么？" in page.text


def test_setup_status_never_returns_credentials(client: TestClient):
    response = client.get("/api/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["first_run"] is True
    assert payload["local_mode"]["ready"] is True
    assert len(payload["providers"]) == 4
    lowered = response.text.lower()
    assert "client_secret" not in lowered
    assert "access_token" not in lowered
    assert "api_key" not in lowered


def test_provider_validation_returns_stable_diagnostic(client: TestClient):
    response = client.post("/api/setup/validate/materials")

    assert response.status_code == 200
    assert response.json()["id"] == "materials"
    assert response.json()["status"] in {
        "configured",
        "partially_configured",
        "not_configured",
    }


def test_provider_validation_rejects_unknown_provider(client: TestClient):
    response = client.post("/api/setup/validate/unknown")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_setup_provider"
