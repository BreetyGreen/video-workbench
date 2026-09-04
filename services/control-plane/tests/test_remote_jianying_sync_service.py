from __future__ import annotations

import json
from pathlib import Path

from app.services.remote_jianying_sync_service import RemoteJianyingSyncService


class FakeHttp:
    def __init__(self):
        self.posts: list[tuple[str, dict]] = []

    def get_json(self, path: str):
        assert path == "/api/course-edit-jobs?state=awaiting_device&limit=20"
        return [{"id": "job-1", "task_id": "task-1"}]

    def download(self, path: str, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.endswith("quality-report.json"):
            destination.write_text(json.dumps({"status": "pass", "blocking_failures": []}), encoding="utf-8")
        else:
            destination.write_bytes(b"zip")

    def post_json(self, path: str, payload: dict):
        self.posts.append((path, payload))
        return {"state": "delivered_to_jianying"}


class FakeHandoff:
    def import_task(self, task_id: str):
        assert task_id == "task-1"
        return {"status": "imported", "draft_path": "/Movies/Jianying/draft"}


def test_sync_pending_downloads_and_acknowledges_device_delivery(tmp_path: Path) -> None:
    http = FakeHttp()
    service = RemoteJianyingSyncService(
        data_dir=tmp_path / "data",
        http=http,
        handoff=FakeHandoff(),
    )

    results = service.sync_pending()

    assert results == [{"job_id": "job-1", "task_id": "task-1", "status": "imported"}]
    assert (tmp_path / "data" / "artifacts" / "task-1" / "draft.zip").read_bytes() == b"zip"
    assert http.posts == [
        ("/api/course-edit-jobs/job-1/device-handoff", {"status": "imported", "error_code": ""})
    ]


class FakeDeviceHttp(FakeHttp):
    def get_json(self, path: str):
        assert path == "/api/devices/me/course-edit-jobs?limit=20"
        return [{"id": "job-1", "task_id": "task-1"}]

    def download(self, path: str, destination: Path):
        assert path.startswith("/api/devices/me/course-edit-jobs/job-1/artifacts/")
        super().download(path, destination)


def test_paired_device_mode_uses_scoped_routes(tmp_path: Path) -> None:
    http = FakeDeviceHttp()
    service = RemoteJianyingSyncService(
        data_dir=tmp_path / "data",
        http=http,
        handoff=FakeHandoff(),
        device_api=True,
    )

    result = service.sync_pending()

    assert result[0]["status"] == "imported"
    assert http.posts == [
        ("/api/devices/me/course-edit-jobs/job-1/handoff", {"status": "imported", "error_code": ""})
    ]
