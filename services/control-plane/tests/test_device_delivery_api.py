from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import CourseEditJob


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


def test_device_claim_scopes_queue_artifacts_and_monotonic_ack(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    app = create_app(settings)
    database = Database(settings.database_url)
    task_id = "device-scoped-task"
    task_dir = settings.artifact_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "quality-report.json").write_text('{"status":"pass","blocking_failures":[]}', encoding="utf-8")
    (task_dir / "draft.zip").write_bytes(b"draft")
    with Session(database.engine) as session:
        job = CourseEditJob(
            course_id="course-1",
            recipe_id="recipe-1",
            task_id=task_id,
            state="awaiting_device",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with TestClient(app) as client:
        first_code = client.post("/api/devices/pairing-codes").json()["code"]
        first_token = client.post("/api/devices/pair", json={"code": first_code, "name": "First"}).json()["token"]
        second_code = client.post("/api/devices/pairing-codes").json()["code"]
        second_token = client.post("/api/devices/pair", json={"code": second_code, "name": "Second"}).json()["token"]
        first_headers = {"Authorization": f"Bearer {first_token}"}
        second_headers = {"Authorization": f"Bearer {second_token}"}

        first_queue = client.get("/api/devices/me/course-edit-jobs", headers=first_headers)
        second_queue = client.get("/api/devices/me/course-edit-jobs", headers=second_headers)
        second_download = client.get(
            f"/api/devices/me/course-edit-jobs/{job_id}/artifacts/draft.zip",
            headers=second_headers,
        )
        second_ack = client.post(
            f"/api/devices/me/course-edit-jobs/{job_id}/handoff",
            headers=second_headers,
            json={"status": "imported"},
        )
        first_download = client.get(
            f"/api/devices/me/course-edit-jobs/{job_id}/artifacts/draft.zip",
            headers=first_headers,
        )
        first_ack = client.post(
            f"/api/devices/me/course-edit-jobs/{job_id}/handoff",
            headers=first_headers,
            json={"status": "imported"},
        )
        stale_failure = client.post(
            f"/api/devices/me/course-edit-jobs/{job_id}/handoff",
            headers=first_headers,
            json={"status": "failed", "error_code": "stale"},
        )

    assert [item["id"] for item in first_queue.json()] == [job_id]
    assert second_queue.json() == []
    assert second_download.status_code == 404
    assert second_ack.status_code == 404
    assert first_download.status_code == 200
    assert first_ack.status_code == 200
    assert first_ack.json()["state"] == "delivered_to_jianying"
    assert stale_failure.status_code == 409
