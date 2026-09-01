from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_process_course_returns_cited_recipe(tmp_path: Path) -> None:
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
                ("files", ("material.mp4", b"video", "video/mp4")),
            ],
        ).json()

        response = client.post(f"/api/courses/{created['id']}/process")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["course_id"] == created["id"]
    assert result["version"] == 1
    assert {rule["category"] for rule in result["rules"]} == {"hook", "pacing"}
    assert all(rule["source_asset_id"] for rule in result["rules"])
    assert all(rule["source_page"] for rule in result["rules"])
