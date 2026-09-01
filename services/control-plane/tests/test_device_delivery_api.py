from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_device_pairing_and_authenticated_queue(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    with TestClient(create_app(settings)) as client:
        issued = client.post("/api/devices/pairing-codes")
        denied = client.get("/api/devices/me/course-edit-jobs")
        paired = client.post(
            "/api/devices/pair",
            json={"code": issued.json()["code"], "name": "MacBook Pro"},
        )
        token = paired.json()["token"]
        queue = client.get(
            "/api/devices/me/course-edit-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        reused = client.post(
            "/api/devices/pair",
            json={"code": issued.json()["code"], "name": "Other"},
        )

    assert issued.status_code == 201
    assert issued.json()["expires_at"]
    assert denied.status_code == 401
    assert paired.status_code == 201
    assert paired.json()["device_id"]
    assert "token_hash" not in paired.text
    assert queue.status_code == 200
    assert queue.json() == []
    assert reused.status_code == 409
