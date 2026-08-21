from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_task(client: TestClient, *, rights_confirmed: bool = True):
    return client.post(
        "/api/tasks",
        data={
            "title": "demo",
            "content_type": "pet",
            "rights_confirmed": str(rights_confirmed).lower(),
        },
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )


def test_health_reports_storage_and_database(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "artifact_storage": "ok",
    }


def test_create_task_persists_safe_material(client: TestClient):
    response = create_task(client)

    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "received"
    assert task["materials"][0]["original_name"] == "raw.mp4"
    assert "raw.mp4" not in task["materials"][0]["stored_path"]
    assert task["materials"][0]["sha256"] == hashlib.sha256(b"video").hexdigest()

    stored_path = Path(task["materials"][0]["stored_path"])
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"video"


def test_get_task_returns_persisted_materials(client: TestClient):
    created = create_task(client).json()

    response = client.get(f"/api/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_missing_task_returns_404(client: TestClient):
    response = client.get("/api/tasks/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_approval_rejects_unconfirmed_rights(client: TestClient):
    task = create_task(client, rights_confirmed=False).json()

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve", "comment": "ready"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rights_not_confirmed"


def test_change_request_moves_task_to_changes_requested(client: TestClient):
    task = create_task(client).json()

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "request_changes", "comment": "shorten the hook"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "changes_requested"


def test_source_metadata_is_persisted_and_deduplication_key_is_unique(client: TestClient):
    data = {
        "title": "from DingTalk",
        "content_type": "pet",
        "rights_confirmed": "false",
        "source_type": "dingtalk",
        "source_user": "user-1",
        "source_conversation": "conversation-1",
        "source_message_id": "message-1",
        "deduplication_key": "dingtalk:message-1",
    }
    first = client.post(
        "/api/tasks",
        data=data,
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )
    second = client.post(
        "/api/tasks",
        data=data,
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )

    assert first.status_code == 201
    assert first.json()["source_type"] == "dingtalk"
    assert first.json()["source_message_id"] == "message-1"
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_task"


def test_task_persists_quality_profile_cloud_consent_and_separate_reference(client: TestClient):
    response = client.post(
        "/api/tasks",
        data={
            "title": "reference guided",
            "content_type": "pet",
            "rights_confirmed": "true",
            "quality_profile": "local_privacy",
            "cloud_processing_allowed": "true",
        },
        files=[
            ("files", ("source.mp4", b"source-video", "video/mp4")),
            ("reference_file", ("viral-reference.mp4", b"reference-video", "video/mp4")),
        ],
    )

    assert response.status_code == 201, response.text
    task = response.json()
    assert task["quality_profile"] == "local_privacy"
    assert task["cloud_processing_allowed"] is True
    assert task["reference_name"] == "viral-reference.mp4"
    assert task["reference_sha256"] == hashlib.sha256(b"reference-video").hexdigest()
    assert len(task["materials"]) == 1
    reference_path = Path(task["reference_path"])
    assert reference_path.is_file()
    assert reference_path.read_bytes() == b"reference-video"
    assert reference_path != Path(task["materials"][0]["stored_path"])


def test_task_rejects_unknown_quality_profile(client: TestClient):
    response = client.post(
        "/api/tasks",
        data={
            "title": "bad profile",
            "content_type": "pet",
            "rights_confirmed": "true",
            "quality_profile": "magic",
        },
        files=[("files", ("source.mp4", b"source-video", "video/mp4"))],
    )

    assert response.status_code == 422
