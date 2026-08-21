from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'intake.db').as_posix()}",
        automation_scheduler_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_authorized_video_requires_rights_basis(client: TestClient):
    response = client.post(
        "/api/materials/authorized-video",
        data={"allowed_platforms": "douyin"},
        files={"file": ("pet.mp4", b"video", "video/mp4")},
    )

    assert response.status_code == 422


def test_authorized_video_is_deduplicated_and_auditable(client: TestClient):
    data = {
        "source_type": "merchant_authorized",
        "rights_basis": "品牌方书面授权 2026-08-21",
        "product_id": "product-1001",
        "allowed_platforms": "douyin,xiaohongshu",
        "search_text": "宠物 梳毛 商品介绍",
    }
    first = client.post(
        "/api/materials/authorized-video",
        data=data,
        files={"file": ("pet.mp4", b"authorized-video", "video/mp4")},
    )
    second = client.post(
        "/api/materials/authorized-video",
        data=data,
        files={"file": ("renamed.mp4", b"authorized-video", "video/mp4")},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["rights_status"] == "authorized"
    assert first.json()["rights_basis"] == data["rights_basis"]
    assert first.json()["product_id"] == "product-1001"
    assert first.json()["allowed_platforms"] == ["douyin", "xiaohongshu"]
