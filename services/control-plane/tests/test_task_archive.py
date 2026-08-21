from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'archive.db').as_posix()}",
        automation_scheduler_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _create_task(client: TestClient) -> dict:
    response = client.post(
        "/api/tasks",
        data={
            "title": "素材上传验证",
            "content_type": "pet",
            "rights_confirmed": "true",
        },
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )
    assert response.status_code == 201
    return response.json()


def test_archived_task_is_hidden_and_can_be_restored(client: TestClient):
    task = _create_task(client)

    archived = client.post(
        f"/api/tasks/{task['id']}/archive",
        json={"reason": "historical_validation"},
    )

    assert archived.status_code == 200
    assert archived.json()["archive_reason"] == "historical_validation"
    assert archived.json()["archived_at"] is not None
    assert task["id"] not in {row["id"] for row in client.get("/api/tasks").json()}
    assert task["id"] in {
        row["id"] for row in client.get("/api/tasks?include_archived=true").json()
    }

    restored = client.post(f"/api/tasks/{task['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert task["id"] in {row["id"] for row in client.get("/api/tasks").json()}


def test_archive_is_idempotent_and_missing_task_returns_404(client: TestClient):
    task = _create_task(client)
    first = client.post(f"/api/tasks/{task['id']}/archive", json={"reason": "validation"})
    second = client.post(f"/api/tasks/{task['id']}/archive", json={"reason": "validation"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["archived_at"] == first.json()["archived_at"]
    assert client.post("/api/tasks/missing/restore").status_code == 404
