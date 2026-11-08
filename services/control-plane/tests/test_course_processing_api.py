from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_process_course_returns_cited_recipe(tmp_path: Path, ffmpeg_fixture: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/courses/intake",
            data={
                "title": "宠物课",
                "source_type": "fixture",
                "source_message_id": "process-1",
                "asset_roles": json.dumps(["tutorial", "material"]),
                "rights_statuses": json.dumps(["personal_learning", "commercial_authorized"]),
            },
            files=[
                (
                    "files",
                    (
                        "tutorial.txt",
                        "0-3 秒先展示结果制造钩子。\n3-10 秒单镜头不超过 2 秒。".encode(),
                        "text/plain",
                    ),
                ),
                ("files", ("material.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
            ],
        ).json()

        response = client.post(f"/api/courses/{created['id']}/process")
        search = client.get(
            f"/api/courses/{created['id']}/shots/search",
            params={"q": "material", "commercial": "true"},
        )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["course_id"] == created["id"]
    assert result["version"] == 1
    assert {rule["category"] for rule in result["rules"]} == {"hook", "pacing"}
    assert all(rule["source_asset_id"] for rule in result["rules"])
    assert all(rule["source_page"] for rule in result["rules"])
    assert all(rule["evidence_text"] for rule in result["rules"])
    assert all(0 <= rule["confidence"] <= 1 for rule in result["rules"])
    assert [segment["segment_type"] for segment in result["segments"]] == ["lecture", "lecture"]
    assert all(segment["transcript_text"] for segment in result["segments"])
    assert all(segment["related_rule_ids"] for segment in result["segments"])
    assert all(isinstance(segment["ocr_texts"], list) for segment in result["segments"])
    assert result["tutorial_asset_id"]
    assert len(result["transcript_sha256"]) == 64
    assert result["shot_count"] >= 1
    assert search.status_code == 200
    assert len(search.json()) >= 1
    assert all(item["rights_status"] == "commercial_authorized" for item in search.json())


def test_process_course_forwards_profile_and_cloud_consent(tmp_path: Path, ffmpeg_fixture: Path, monkeypatch) -> None:
    from app.services.tutorial_understanding_service import TutorialUnderstandingService

    calls: list[dict] = []
    original = TutorialUnderstandingService.process

    def spy(self, session, course_id, **kwargs):
        calls.append(dict(kwargs))
        return original(self, session, course_id, **kwargs)

    monkeypatch.setattr(TutorialUnderstandingService, "process", spy)
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/courses/intake",
            data={
                "title": "绿豆沙课",
                "source_type": "fixture",
                "source_message_id": "process-options-1",
                "asset_roles": json.dumps(["tutorial", "material"]),
                "rights_statuses": json.dumps(["personal_learning", "personal_learning"]),
            },
            files=[
                ("files", ("tutorial.txt", "0-3 秒先展示结果制造钩子。".encode(), "text/plain")),
                ("files", ("material.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
            ],
        ).json()
        default = client.post(f"/api/courses/{created['id']}/process")
        explicit = client.post(
            f"/api/courses/{created['id']}/process",
            json={"quality_profile": "fast_preview", "cloud_processing_allowed": True},
        )
        invalid = client.post(f"/api/courses/{created['id']}/process", json={"quality_profile": "ultra"})

    assert default.status_code == 200, default.text
    assert explicit.status_code == 200, explicit.text
    assert invalid.status_code == 422
    assert calls[0] == {"quality_profile": "production", "cloud_processing_allowed": False}
    assert calls[1] == {"quality_profile": "fast_preview", "cloud_processing_allowed": True}
    assert explicit.json()["version"] == 2


def test_background_processing_returns_202_and_finishes_after_response(tmp_path: Path, ffmpeg_fixture: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/courses/intake",
            data={
                "title": "后台课",
                "source_type": "fixture",
                "source_message_id": "process-background-1",
                "asset_roles": json.dumps(["tutorial", "material"]),
                "rights_statuses": json.dumps(["personal_learning", "personal_learning"]),
            },
            files=[
                ("files", ("tutorial.txt", "0-3 秒先展示结果制造钩子。".encode(), "text/plain")),
                ("files", ("material.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
            ],
        ).json()
        accepted = client.post(f"/api/courses/{created['id']}/process", json={"background": True})
        # TestClient runs background tasks before returning, so the course is already processed here.
        course = client.get(f"/api/courses/{created['id']}").json()
        missing = client.post("/api/courses/does-not-exist/process", json={"background": True})

    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {"course_id": created["id"], "status": "processing", "background": True}
    assert course["status"] == "processed"
    assert missing.status_code == 404


def test_startup_marks_interrupted_course_processing_as_failed(tmp_path: Path) -> None:
    from sqlmodel import Session, select
    from app.db import Database
    from app.models import Course, CourseProcessingRun

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'control-plane.db').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        stuck = Course(title="中断课", source_message_id="interrupted-1", status="processing")
        done = Course(title="完成课", source_message_id="interrupted-2", status="processed")
        session.add_all([stuck, done])
        session.commit()
        session.add(CourseProcessingRun(course_id=stuck.id, state="processing"))
        session.commit()
        stuck_id, done_id = stuck.id, done.id

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/courses/{stuck_id}").json()["status"] == "failed"
        assert client.get(f"/api/courses/{done_id}").json()["status"] == "processed"
        # A retrigger is possible again (202) instead of 409.
        assert client.post(f"/api/courses/{stuck_id}/process", json={"background": True}).status_code == 202

    with Session(database.engine) as session:
        run = session.exec(select(CourseProcessingRun).where(CourseProcessingRun.course_id == stuck_id)
                           .order_by(CourseProcessingRun.started_at)).first()
        assert run.state == "failed" and run.error_code == "interrupted_by_restart"
