from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import UploadFile
from sqlmodel import Session, select

from app.adapters.pexels import PexelsClient
from app.config import Settings
from app.db import Database
from app.models import AutomationSchedule, LicensedAsset, TaskStatus, VideoTask
from app.services.automation_service import DailyAutomation
from app.services.material_library_service import MaterialLibraryService
from app.services.task_service import create_task


def test_pexels_search_uses_official_video_endpoint_and_selects_portrait_mp4():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/videos/search"
        assert request.headers["authorization"] == "pexels-key"
        assert request.url.params["query"] == "宠物"
        assert request.url.params["orientation"] == "portrait"
        assert request.url.params["locale"] == "zh-CN"
        return httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "id": 101,
                        "width": 1080,
                        "height": 1920,
                        "duration": 8,
                        "url": "https://www.pexels.com/video/101/",
                        "image": "https://images.pexels.com/videos/101/poster.jpg",
                        "user": {
                            "name": "Creator",
                            "url": "https://www.pexels.com/@creator",
                        },
                        "video_files": [
                            {
                                "id": 1,
                                "quality": "hd",
                                "file_type": "video/mp4",
                                "width": 1920,
                                "height": 1080,
                                "link": "https://player.vimeo.com/landscape.mp4",
                            },
                            {
                                "id": 2,
                                "quality": "hd",
                                "file_type": "video/mp4",
                                "width": 1080,
                                "height": 1920,
                                "link": "https://videos.pexels.com/portrait.mp4",
                            },
                        ],
                    }
                ]
            },
        )

    client = PexelsClient(
        api_key="pexels-key",
        transport=httpx.MockTransport(handler),
    )

    assets = client.search_videos("宠物", count=3)

    assert len(requests) == 1
    assert assets[0].provider_asset_id == "101"
    assert assets[0].download_url == "https://videos.pexels.com/portrait.mp4"
    assert assets[0].width == 1080
    assert assets[0].height == 1920


def test_confirmed_task_materials_become_deduplicated_local_library_assets(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'library.db').as_posix()}",
        automation_enabled=False,
    )
    database = Database(settings.database_url)
    database.create_all()
    with Session(database.engine) as session:
        for suffix in ("a", "b"):
            create_task(
                session,
                settings,
                title=f"宠物梳毛素材 {suffix}",
                content_type="宠物",
                rights_confirmed=True,
                files=[
                    UploadFile(
                        filename=f"pet-{suffix}.mp4",
                        file=BytesIO(b"same-confirmed-video"),
                        headers={"content-type": "video/mp4"},
                    )
                ],
            )

        library = MaterialLibraryService(settings, PexelsClient(api_key=""))
        result = library.sync_confirmed_assets(session)
        assets = list(session.exec(select(LicensedAsset)).all())

    assert result.imported == 1
    assert result.skipped_duplicates == 1
    assert len(assets) == 1
    assert assets[0].provider == "user_confirmed"
    assert assets[0].rights_basis == "task_rights_confirmed"
    assert Path(assets[0].stored_path).is_file()
    assert "宠物梳毛素材" in assets[0].search_text

    with Session(database.engine) as session:
        assert library.search_local(session, "萌宠", limit=3)[0].id == assets[0].id


def test_daily_automation_creates_and_processes_task_from_confirmed_library(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'automation-library.db').as_posix()}",
        automation_enabled=False,
        automation_auto_create_tasks=True,
        automation_task_limit=1,
        automation_material_count=2,
    )
    database = Database(settings.database_url)
    database.create_all()

    class FakePipeline:
        def process(self, session: Session, task: VideoTask) -> VideoTask:
            task.status = TaskStatus.REVIEWING
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    class MissingDouyin:
        def status(self):
            return {"status": "not_configured", "reason": "missing_credentials"}

    library = MaterialLibraryService(settings, PexelsClient(api_key=""))
    automation = DailyAutomation(
        settings,
        FakePipeline(),  # type: ignore[arg-type]
        MissingDouyin(),  # type: ignore[arg-type]
        material_library=library,
    )

    with Session(database.engine) as session:
        for index, payload in enumerate((b"pet-video-one", b"pet-video-two")):
            create_task(
                session,
                settings,
                title=f"宠物日常素材 {index}",
                content_type="宠物",
                rights_confirmed=True,
                files=[
                    UploadFile(
                        filename=f"pet-{index}.mp4",
                        file=BytesIO(payload),
                        headers={"content-type": "video/mp4"},
                    )
                ],
            )
        seed_tasks = list(session.exec(select(VideoTask)).all())
        for seed in seed_tasks:
            seed.status = TaskStatus.REVIEWING
            session.add(seed)
        session.commit()
        schedule = AutomationSchedule(
            enabled=True,
            hour=8,
            minute=30,
            timezone="Asia/Shanghai",
            keywords_json='["宠物"]',
        )
        session.add(schedule)
        session.commit()

        run = automation.run(session, schedule, trigger="manual")
        created = session.exec(
            select(VideoTask).where(VideoTask.source_type == "daily_automation")
        ).one()

    assert run.material_status == "local_catalog"
    assert run.sourced_assets == 2
    assert run.created_task_ids == [created.id]
    assert run.processed_tasks == 1
    assert created.status == TaskStatus.REVIEWING
    assert created.rights_confirmed is True
    assert len(created.materials) == 2
    assert created.deduplication_key.startswith("daily-automation:")


def test_daily_automation_does_not_create_duplicate_task_for_same_day(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'automation-dedup.db').as_posix()}",
        automation_enabled=False,
        automation_auto_create_tasks=True,
    )
    database = Database(settings.database_url)
    database.create_all()

    class FakePipeline:
        def process(self, session: Session, task: VideoTask) -> VideoTask:
            task.status = TaskStatus.REVIEWING
            session.add(task)
            session.commit()
            return task

    class MissingDouyin:
        def status(self):
            return {"status": "not_configured"}

    library = MaterialLibraryService(settings, PexelsClient(api_key=""))
    automation = DailyAutomation(
        settings,
        FakePipeline(),  # type: ignore[arg-type]
        MissingDouyin(),  # type: ignore[arg-type]
        material_library=library,
    )
    with Session(database.engine) as session:
        create_task(
            session,
            settings,
            title="宠物素材",
            content_type="宠物",
            rights_confirmed=True,
            files=[UploadFile(filename="pet.mp4", file=BytesIO(b"pet"), headers={"content-type": "video/mp4"})],
        ).status = TaskStatus.REVIEWING
        session.commit()
        schedule = AutomationSchedule(keywords_json='["宠物"]')
        session.add(schedule)
        session.commit()
        first = automation.run(session, schedule, trigger="manual")
        second = automation.run(session, schedule, trigger="manual")
        auto_tasks = list(session.exec(select(VideoTask).where(VideoTask.source_type == "daily_automation")).all())

    assert len(first.created_task_ids) == 1
    assert second.created_task_ids == []
    assert len(auto_tasks) == 1


def test_daily_automation_advances_to_next_keyword_when_first_is_already_done(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'automation-next-keyword.db').as_posix()}",
        automation_enabled=False,
        automation_auto_create_tasks=True,
        automation_task_limit=1,
        automation_material_count=1,
    )
    database = Database(settings.database_url)
    database.create_all()

    class FakePipeline:
        def process(self, session: Session, task: VideoTask) -> VideoTask:
            task.status = TaskStatus.REVIEWING
            session.add(task)
            session.commit()
            return task

    class MissingDouyin:
        def status(self):
            return {"status": "not_configured"}

    library = MaterialLibraryService(settings, PexelsClient(api_key=""))
    automation = DailyAutomation(
        settings,
        FakePipeline(),  # type: ignore[arg-type]
        MissingDouyin(),  # type: ignore[arg-type]
        material_library=library,
    )
    with Session(database.engine) as session:
        seed = create_task(
            session,
            settings,
            title="宠物素材",
            content_type="宠物",
            rights_confirmed=True,
            files=[UploadFile(filename="pet.mp4", file=BytesIO(b"pet"), headers={"content-type": "video/mp4"})],
        )
        seed.status = TaskStatus.REVIEWING
        session.add(seed)
        schedule = AutomationSchedule(keywords_json='["宠物", "萌宠"]')
        session.add(schedule)
        session.commit()

        first = automation.run(session, schedule, trigger="manual")
        second = automation.run(session, schedule, trigger="manual")
        second_task = session.get(VideoTask, second.created_task_ids[0])

    assert len(first.created_task_ids) == 1
    assert len(second.created_task_ids) == 1
    assert second_task is not None
    assert second_task.deduplication_key.endswith(":萌宠")
