from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.main import create_app
from app.models import TaskStatus, VideoTask


def test_douyin_delivery_requires_oauth_configuration(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'delivery.db').as_posix()}",
        automation_scheduler_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/tasks/missing/deliver/douyin",
            json={"visibility": "self", "title": "宠物梳毛"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "douyin_oauth_required"


def test_douyin_self_visible_delivery_updates_explicit_state(tmp_path: Path):
    class FakePublish:
        def upload_video(self, path, *, open_id, access_token):
            assert path.name == "preview.mp4"
            return "encrypted-video"

        def create_video(self, **kwargs):
            from app.adapters.douyin_publish import DouyinCreateResult

            assert kwargs["visibility"] == "self"
            return DouyinCreateResult(item_id="item-1", video_id="video-1", visibility="self")

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'delivery-ready.db').as_posix()}",
        douyin_open_id="open-1",
        douyin_access_token="token-1",
        automation_scheduler_enabled=False,
    )
    app = create_app(settings, douyin_publish_client=FakePublish())
    with TestClient(app) as client:
        database = client.app.state.database
        with Session(database.engine) as session:
            task = VideoTask(title="宠物梳毛", content_type="商品介绍", rights_confirmed=True, status=TaskStatus.APPROVED)
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id
        artifact_dir = settings.artifact_dir / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "preview.mp4").write_bytes(b"preview")

        response = client.post(
            f"/api/tasks/{task_id}/deliver/douyin",
            json={"visibility": "self", "title": "宠物梳毛 #萌宠"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["delivery_state"] == "douyin_self_visible"
    assert response.json()["delivery_provider_id"] == "item-1"
