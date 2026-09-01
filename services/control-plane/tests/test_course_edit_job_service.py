from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    EditingRecipe,
    EditingRule,
    RightsStatus,
    TaskStatus,
)
from app.services.course_edit_job_service import CourseEditJobService


class FakePipeline:
    def __init__(self, artifact_dir: Path, *, blocked: bool = False):
        self.artifact_dir = artifact_dir
        self.blocked = blocked

    def process(self, session: Session, task):
        task_dir = self.artifact_dir / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "quality-report.json").write_text(
            json.dumps(
                {
                    "status": "fail" if self.blocked else "pass",
                    "blocking_failures": ["caption_safe_area"] if self.blocked else [],
                }
            ),
            encoding="utf-8",
        )
        (task_dir / "preview.mp4").write_bytes(b"preview")
        (task_dir / "draft.zip").write_bytes(b"draft")
        task.status = TaskStatus.REVIEWING
        session.add(task)
        session.commit()
        return task


class FakeHandoff:
    def import_task(self, task_id: str):
        return {"task_id": task_id, "status": "imported", "draft_path": "B:/Jianying/Draft"}


def _seed_course(session: Session, root: Path, *, rights: RightsStatus) -> Course:
    source = root / "courses" / "course-1" / "material.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"video")
    course = Course(title="商品剪辑课", source_message_id="course-edit-1", status="processed")
    session.add(course)
    session.commit()
    asset = CourseAsset(
        course_id=course.id,
        role=CourseAssetRole.MATERIAL,
        original_name="帽子素材.mp4",
        stored_path=str(source),
        mime_type="video/mp4",
        size_bytes=source.stat().st_size,
        sha256="a" * 64,
        rights_status=rights,
    )
    recipe = EditingRecipe(course_id=course.id, title="帽子教程", summary="先结果，后卖点")
    session.add(asset)
    session.add(recipe)
    session.commit()
    session.add(
        EditingRule(
            recipe_id=recipe.id,
            category="hook",
            instruction="前 3 秒展示佩戴效果",
            source_asset_id=asset.id,
            source_page=1,
            sort_order=0,
        )
    )
    session.commit()
    return course


def test_commercial_course_job_runs_without_review_and_hands_off(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())

        job = service.run(
            session,
            course_id=course.id,
            title="夏日防晒帽",
            content_type="商品介绍",
            commercial=True,
        )

        assert job.state == "delivered_to_jianying"
        assert job.task_id
        assert job.handoff_status == "imported"
        assert job.review_skipped is True
        assert job.quality_status == "pass"
        assert job.task.status == TaskStatus.APPROVED
        assert job.task.rights_confirmed is True
        assert "前 3 秒展示佩戴效果" in job.task.tutorial_text
        assert len(job.task.materials) == 1
        assert Path(job.task.materials[0].stored_path).is_file()


def test_commercial_course_job_rejects_unlicensed_material(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.UNKNOWN)
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())

        with pytest.raises(ValueError, match="commercial_material_not_authorized"):
            service.run(
                session,
                course_id=course.id,
                title="夏日防晒帽",
                content_type="商品介绍",
                commercial=True,
            )


def test_quality_block_keeps_job_out_of_delivery(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        service = CourseEditJobService(
            settings,
            FakePipeline(settings.artifact_dir, blocked=True),
            FakeHandoff(),
        )

        job = service.run(
            session,
            course_id=course.id,
            title="夏日防晒帽",
            content_type="商品介绍",
            commercial=True,
        )

        assert job.state == "quality_blocked"
        assert job.review_skipped is False
        assert job.task.status == TaskStatus.REVIEWING


def test_course_edit_job_api_returns_automatic_delivery_state(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        course_id = course.id

    app = create_app(
        settings,
        pipeline_service_override=FakePipeline(settings.artifact_dir),
        jianying_handoff_override=FakeHandoff(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/course-edit-jobs",
            json={
                "course_id": course_id,
                "title": "夏日防晒帽",
                "content_type": "商品介绍",
                "commercial": True,
                "quality_profile": "fast_preview",
                "cloud_processing_allowed": False,
            },
        )
        fetched = client.get(f"/api/course-edit-jobs/{response.json()['id']}")

    assert response.status_code == 201, response.text
    assert response.json()["state"] == "delivered_to_jianying"
    assert response.json()["review_skipped"] is True
    assert fetched.status_code == 200
    assert fetched.json()["task_id"] == response.json()["task_id"]


def test_device_queue_and_ack_complete_server_handoff(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        course_id = course.id

    class WaitingHandoff:
        def import_task(self, task_id: str):
            return {"task_id": task_id, "status": "waiting", "code": "jianying_not_ready"}

    app = create_app(
        settings,
        pipeline_service_override=FakePipeline(settings.artifact_dir),
        jianying_handoff_override=WaitingHandoff(),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/course-edit-jobs",
            json={"course_id": course_id, "title": "帽子", "content_type": "商品介绍"},
        ).json()
        queue = client.get("/api/course-edit-jobs", params={"state": "awaiting_device"})
        ack = client.post(
            f"/api/course-edit-jobs/{created['id']}/device-handoff",
            json={"status": "imported"},
        )

    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [created["id"]]
    assert ack.status_code == 200
    assert ack.json()["state"] == "delivered_to_jianying"
    assert ack.json()["handoff_status"] == "imported"
