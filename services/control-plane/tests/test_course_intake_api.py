from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
        course_max_file_bytes=1024,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def post_course(client: TestClient, *, message_id: str = "message-1"):
    return client.post(
        "/api/courses/intake",
        data={
            "title": "宠物短视频剪辑课",
            "source_type": "dingtalk",
            "source_user": "staff-1",
            "source_conversation": "group-1",
            "source_message_id": message_id,
            "asset_roles": json.dumps(["tutorial", "reference", "material"]),
            "rights_statuses": json.dumps(
                ["personal_learning", "personal_learning", "commercial_authorized"]
            ),
        },
        files=[
            ("files", ("../tutorial.mp4", b"tutorial", "video/mp4")),
            ("files", ("reference.mp4", b"reference", "video/mp4")),
            ("files", ("material.mp4", b"material", "video/mp4")),
        ],
    )


def test_intake_persists_roles_rights_and_safe_files(client: TestClient, settings: Settings) -> None:
    response = post_course(client)

    assert response.status_code == 201, response.text
    course = response.json()
    assert course["source_message_id"] == "message-1"
    assert [(asset["role"], asset["rights_status"]) for asset in course["assets"]] == [
        ("tutorial", "personal_learning"),
        ("reference", "personal_learning"),
        ("material", "commercial_authorized"),
    ]
    assert course["assets"][0]["original_name"] == "tutorial.mp4"
    assert "stored_path" not in course["assets"][0]
    assert course["assets"][0]["sha256"] == hashlib.sha256(b"tutorial").hexdigest()

    stored = list((settings.data_dir / "courses" / course["id"] / "assets").iterdir())
    assert len(stored) == 3
    assert sorted(item.read_bytes() for item in stored) == [b"material", b"reference", b"tutorial"]


def test_retrieves_persisted_course(client: TestClient) -> None:
    created = post_course(client).json()

    response = client.get(f"/api/courses/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_duplicate_source_message_returns_existing_course(client: TestClient) -> None:
    first = post_course(client)
    second = post_course(client)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_rejects_executable_mime_type(client: TestClient) -> None:
    response = client.post(
        "/api/courses/intake",
        data={
            "title": "bad",
            "source_message_id": "bad-1",
            "asset_roles": '["material"]',
            "rights_statuses": '["unknown"]',
        },
        files=[("files", ("payload.exe", b"MZ", "application/x-msdownload"))],
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_course_asset_type"


def test_rejects_downloaded_file_over_limit(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
        course_max_file_bytes=4,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/courses/intake",
            data={
                "title": "large",
                "source_message_id": "large-1",
                "asset_roles": '["material"]',
                "rights_statuses": '["unknown"]',
            },
            files=[("files", ("clip.mp4", b"12345", "video/mp4"))],
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "course_asset_too_large"


def test_rejects_role_count_mismatch(client: TestClient) -> None:
    response = client.post(
        "/api/courses/intake",
        data={
            "title": "mismatch",
            "source_message_id": "mismatch-1",
            "asset_roles": '["tutorial"]',
            "rights_statuses": '["unknown"]',
        },
        files=[
            ("files", ("one.mp4", b"one", "video/mp4")),
            ("files", ("two.mp4", b"two", "video/mp4")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "course_asset_metadata_count_mismatch"
