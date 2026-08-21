from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_material_center_reindexes_rights_confirmed_video_and_serves_it(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'materials-api.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        task = client.post(
            "/api/tasks",
            data={
                "title": "宠物梳毛授权素材",
                "content_type": "宠物",
                "rights_confirmed": "true",
            },
            files=[("files", ("pet.mp4", b"licensed-pet-video", "video/mp4"))],
        )
        assert task.status_code == 201

        reindex = client.post("/api/materials/reindex")
        listing = client.get("/api/materials", params={"query": "宠物"})
        page = client.get("/materials")
        integration = client.get("/api/integrations/status")

        assert reindex.status_code == 200
        assert reindex.json()["imported"] == 1
        assert listing.status_code == 200
        asset = listing.json()["assets"][0]
        media = client.get(asset["file_url"])

    assert asset["provider"] == "user_confirmed"
    assert asset["rights_basis"] == "task_rights_confirmed"
    assert media.status_code == 200
    assert media.content == b"licensed-pet-video"
    assert page.status_code == 200
    assert "授权素材中心" in page.text
    assert 'id="authorized-video-form"' in page.text
    assert "上传授权视频" in page.text
    assert 'id="material-grid"' in page.text
    assert 'href="/materials" aria-current="page"' in page.text
    assert integration.json()["materials"]["fallback"] == "rights_confirmed_local_catalog"


def test_material_acquisition_falls_back_to_local_catalog_without_pexels_key(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'materials-acquire.db').as_posix()}",
        automation_enabled=False,
        pexels_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/tasks",
            data={"title": "萌宠素材", "content_type": "宠物", "rights_confirmed": "true"},
            files=[("files", ("cat.mp4", b"cat-video", "video/mp4"))],
        )
        response = client.post("/api/materials/acquire", json={"query": "萌宠", "count": 1})
        status = client.get("/api/materials/status")
        run = client.post("/api/automations/daily/run")
        history = client.get("/api/automations/runs").json()[0]

    assert response.status_code == 200
    assert response.json()["status"] == "local_catalog"
    assert len(response.json()["assets"]) == 1
    assert status.json()["pexels"]["status"] == "not_configured"
    assert status.json()["total"] == 1
    assert run.json()["material_status"] == "local_catalog"
    assert len(run.json()["created_task_ids"]) == 1
    assert history["created_task_ids"] == run.json()["created_task_ids"]


def test_unknown_or_unsafe_material_file_is_not_served(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'materials-missing.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/materials/not-real/file")

    assert response.status_code == 404
