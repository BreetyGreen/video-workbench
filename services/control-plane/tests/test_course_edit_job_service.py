from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

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


class MalformedQualityPipeline(FakePipeline):
    def process(self, session: Session, task):
        super().process(session, task)
        (self.artifact_dir / task.id / "quality-report.json").write_text(
            json.dumps({"status": "pass"}),
            encoding="utf-8",
        )
        return task


class PayloadQualityPipeline(FakePipeline):
    def __init__(self, artifact_dir: Path, payload: dict):
        super().__init__(artifact_dir)
        self.payload = payload

    def process(self, session: Session, task):
        super().process(session, task)
        (self.artifact_dir / task.id / "quality-report.json").write_text(
            json.dumps(self.payload),
            encoding="utf-8",
        )
        return task


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
        assert job.task.course_recipe_id == job.job.recipe_id
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


def test_personal_course_job_rejects_unknown_rights_and_accepts_personal_learning(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        unknown = _seed_course(session, settings.data_dir, rights=RightsStatus.UNKNOWN)
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())
        with pytest.raises(ValueError, match="personal_material_not_authorized"):
            service.run(
                session,
                course_id=unknown.id,
                title="个人练习",
                content_type="教程",
                commercial=False,
            )

    second_settings = Settings(
        data_dir=tmp_path / "second-data",
        database_url=f"sqlite:///{(tmp_path / 'second.db').as_posix()}",
    )
    second_database = Database(second_settings.database_url)
    second_database.create_all()
    with Session(second_database.engine) as session:
        personal = _seed_course(session, second_settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        service = CourseEditJobService(second_settings, FakePipeline(second_settings.artifact_dir), FakeHandoff())
        result = service.run(
            session,
            course_id=personal.id,
            title="个人练习",
            content_type="教程",
            commercial=False,
        )

        assert result.state == "delivered_to_jianying"
        assert result.task.rights_confirmed is True


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


def test_malformed_quality_report_never_auto_approves(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        service = CourseEditJobService(settings, MalformedQualityPipeline(settings.artifact_dir), FakeHandoff())

        with pytest.raises(ValueError, match="quality_report_missing_or_invalid"):
            service.run(
                session,
                course_id=course.id,
                title="夏日防晒帽",
                content_type="商品介绍",
                commercial=True,
            )


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "unknown", "blocking_failures": []},
        {"status": "pass", "blocking_failures": "not-a-list"},
    ],
)
def test_invalid_quality_report_shape_never_auto_approves(tmp_path: Path, payload: dict) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        service = CourseEditJobService(settings, PayloadQualityPipeline(settings.artifact_dir, payload), FakeHandoff())

        with pytest.raises(ValueError, match="quality_report_missing_or_invalid"):
            service.run(
                session,
                course_id=course.id,
                title="夏日防晒帽",
                content_type="商品介绍",
                commercial=True,
            )


def test_fail_quality_status_blocks_even_when_blocker_list_is_empty(tmp_path: Path) -> None:
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
            PayloadQualityPipeline(settings.artifact_dir, {"status": "fail", "blocking_failures": []}),
            FakeHandoff(),
        )

        result = service.run(
            session,
            course_id=course.id,
            title="夏日防晒帽",
            content_type="商品介绍",
            commercial=True,
        )

        assert result.state == "quality_blocked"
        assert result.review_skipped is False


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


def _seed_reference(session: Session, root: Path, course: Course, *, role: CourseAssetRole = CourseAssetRole.REFERENCE) -> CourseAsset:
    source = root / "courses" / course.id / "assets" / "reference.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"reference-cut")
    asset = CourseAsset(
        course_id=course.id,
        role=role,
        original_name="参考成片.mp4",
        stored_path=str(source),
        mime_type="video/mp4",
        size_bytes=source.stat().st_size,
        sha256="b" * 64,
        rights_status=RightsStatus.PERSONAL_LEARNING,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def test_course_job_attaches_named_reference_without_making_it_editable(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        reference = _seed_reference(session, settings.data_dir, course)
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())

        result = service.run(
            session,
            course_id=course.id,
            title="绿豆沙",
            content_type="商品介绍",
            commercial=False,
            requirements_text="只用真实包装信息。",
            reference_asset_id=reference.id,
        )

        task = result.task
        assert task.reference_name == "参考成片.mp4"
        assert task.reference_sha256 == "b" * 64
        reference_path = Path(task.reference_path)
        assert reference_path.is_file()
        assert reference_path.name.startswith("reference-")
        assert (settings.material_dir / task.id).resolve() in reference_path.resolve().parents
        assert reference_path.read_bytes() == b"reference-cut"
        # The reference is observed, never cut into the film.
        assert len(task.materials) == 1
        assert all(Path(item.stored_path) != reference_path for item in task.materials)
        assert "只用真实包装信息。" in task.requirements_text


def test_course_job_rejects_reference_that_is_not_a_course_reference_asset(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        material = next(iter(session.exec(select(CourseAsset)).all()))
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())

        with pytest.raises(ValueError, match="selected_reference_unavailable"):
            service.run(
                session,
                course_id=course.id,
                title="绿豆沙",
                content_type="商品介绍",
                commercial=False,
                reference_asset_id=material.id,
            )
        with pytest.raises(ValueError, match="selected_reference_unavailable"):
            service.run(
                session,
                course_id=course.id,
                title="绿豆沙",
                content_type="商品介绍",
                commercial=False,
                reference_asset_id="missing-reference",
            )
        # Nothing was silently attached when no reference was named.
        result = service.run(
            session,
            course_id=course.id,
            title="绿豆沙",
            content_type="商品介绍",
            commercial=False,
        )
        assert result.task.reference_path is None


def test_course_edit_job_api_accepts_selection_requirements_and_reference(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        material = next(iter(session.exec(select(CourseAsset)).all()))
        reference = _seed_reference(session, settings.data_dir, course)
        course_id, material_id, reference_id = course.id, material.id, reference.id

    app = create_app(
        settings,
        pipeline_service_override=FakePipeline(settings.artifact_dir),
        jianying_handoff_override=FakeHandoff(),
    )
    with TestClient(app) as client:
        rejected = client.post(
            "/api/course-edit-jobs",
            json={
                "course_id": course_id,
                "title": "绿豆沙",
                "commercial": False,
                "material_ids": [material_id],
                "reference_asset_id": material_id,
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "selected_reference_unavailable"

        response = client.post(
            "/api/course-edit-jobs",
            json={
                "course_id": course_id,
                "title": "绿豆沙",
                "commercial": False,
                "quality_profile": "production",
                "cloud_processing_allowed": True,
                "material_ids": [material_id],
                "requirements_text": "只用真实包装信息。",
                "reference_asset_id": reference_id,
            },
        )
        assert response.status_code == 201, response.text
        job = response.json()
        task = client.get(f"/api/tasks/{job['task_id']}").json()

    assert task["reference_name"] == "参考成片.mp4"
    assert Path(task["reference_path"]).is_file()
    assert task["cloud_processing_allowed"] is True
    assert "只用真实包装信息。" in task["requirements_text"]
    assert len(task["materials"]) == 1


def test_course_job_carries_audio_material_as_music_bed_but_requires_video(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        music = settings.data_dir / "courses" / course.id / "assets" / "bed.m4a"
        music.parent.mkdir(parents=True, exist_ok=True)
        music.write_bytes(b"music")
        audio = CourseAsset(
            course_id=course.id,
            role=CourseAssetRole.MATERIAL,
            original_name="轻器乐.m4a",
            stored_path=str(music),
            mime_type="audio/mp4",
            size_bytes=5,
            sha256="c" * 64,
            rights_status=RightsStatus.PERSONAL_LEARNING,
        )
        session.add(audio)
        session.commit()
        session.refresh(audio)
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())

        with pytest.raises(ValueError, match="personal_material_not_authorized"):
            service.run(session, course_id=course.id, title="绿豆沙", content_type="商品介绍",
                        commercial=False, material_ids=[audio.id])

        result = service.run(session, course_id=course.id, title="绿豆沙", content_type="商品介绍", commercial=False)
        kinds = sorted(item.mime_type for item in result.task.materials)
        assert kinds == ["audio/mp4", "video/mp4"]
        assert all(Path(item.stored_path).is_file() for item in result.task.materials)


def test_large_learned_courses_hand_the_director_a_digest(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.PERSONAL_LEARNING)
        recipe = session.exec(select(EditingRecipe).where(EditingRecipe.course_id == course.id)).first()
        asset = session.exec(select(CourseAsset)).first()
        for index in range(60):
            session.add(EditingRule(recipe_id=recipe.id, category="structure", instruction=f"规则{index}：配料句配配料画面",
                                    evidence_text="e", source_asset_id=asset.id, source_start_ms=index * 1000,
                                    source_end_ms=index * 1000 + 800, sort_order=index + 10))
        session.commit()
        service = CourseEditJobService(settings, FakePipeline(settings.artifact_dir), FakeHandoff())
        result = service.run(session, course_id=course.id, title="绿豆沙", content_type="商品介绍", commercial=False)
        text = result.task.tutorial_text

    assert text.startswith("课程规则精选：从 61 条学习规则中去重后精选")
    assert "## 结构与镜头匹配" in text and "（课时 " in text
    assert text.count("规则") <= 30  # bounded, not the raw list
