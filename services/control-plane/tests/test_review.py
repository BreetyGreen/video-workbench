from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'review.db').as_posix()}",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_task(client: TestClient, *, rights_confirmed: bool = True) -> dict:
    response = client.post(
        "/api/tasks",
        data={
            "title": "审核示例",
            "content_type": "pet",
            "rights_confirmed": str(rights_confirmed).lower(),
        },
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )
    assert response.status_code == 201
    return response.json()


def create_review_artifacts(client: TestClient, task_id: str) -> Path:
    task_dir = client.app.state.settings.artifact_dir / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "preview.mp4").write_bytes(b"preview")
    (task_dir / "draft.zip").write_bytes(b"draft")
    (task_dir / "cover.jpg").write_bytes(b"cover")
    (task_dir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕", encoding="utf-8")
    (task_dir / "edit-timeline.json").write_text("{}", encoding="utf-8")
    (task_dir / "render-report.json").write_text("{}", encoding="utf-8")
    (task_dir / "quality-report.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "gates": [
                    {
                        "name": "canvas",
                        "status": "pass",
                        "blocking": True,
                        "message": "画布符合竖屏交付规格",
                        "evidence": {"actual": "1080x1920"},
                    },
                    {
                        "name": "narration_coverage",
                        "status": "pass",
                        "blocking": True,
                        "message": "旁白字幕覆盖完整",
                        "evidence": {"coverage_percent": 100, "covered_seconds": 25, "timeline_seconds": 25},
                    },
                ],
                "blocking_failures": [],
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "review.json").write_text(
        json.dumps(
            {
                "aigc_declaration": "AI 辅助完成教程分析、字幕和剪辑草稿，发布前由人工审核。",
                "evidence": ["公开样本：点赞数 120000，来源 https://example.test/video/1"],
                "warnings": ["尚未在本机剪映打开兼容性验证"],
                "audio_route": {
                    "mode": "narration",
                    "voiceover_used": True,
                    "voice_type": "zh_female_vv_uranus_bigtts",
                    "voiceover_duration_seconds": 25,
                    "reason": "商品介绍使用完整旁白。",
                },
                "analysis_summary": {
                    "material_count": 2,
                    "transcribed_materials": 2,
                    "transcript_segments": 8,
                    "scene_count": 12,
                    "silence_count": 3,
                    "keyframe_count": 10,
                    "ocr_text_count": 4,
                },
                "timeline": [
                    {
                        "material_id": "camera-a",
                        "start_seconds": 0,
                        "end_seconds": 2.4,
                        "source_start_seconds": 1.2,
                        "source_end_seconds": 3.6,
                        "score": 8.7,
                        "reason": "hook:speech:先看结果",
                    }
                ],
                "publish_copy": [
                    {"title": f"标题{i}", "body": f"正文{i}", "topics": ["宠物", "日常"]}
                    for i in range(1, 4)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return task_dir


def test_approval_requires_rights(client: TestClient):
    task = create_task(client, rights_confirmed=False)
    create_review_artifacts(client, task["id"])

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rights_not_confirmed"


def test_approval_requires_all_review_artifacts(client: TestClient):
    task = create_task(client)

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "missing_review_artifacts"
    assert set(response.json()["detail"]["missing"]) == {
        "preview.mp4",
        "draft.zip",
        "quality-report.json",
        "review.json",
    }


def test_approval_writes_immutable_audit_event(client: TestClient):
    task = create_task(client)
    create_review_artifacts(client, task["id"])

    approved = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve", "comment": "人工已逐项核对"},
    )
    events = client.get(f"/api/tasks/{task['id']}/review-events")

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["decision"] == "approve"
    assert events.json()[0]["comment"] == "人工已逐项核对"


def test_review_page_displays_video_copy_evidence_and_warnings(client: TestClient):
    task = create_task(client)
    create_review_artifacts(client, task["id"])

    response = client.get(f"/review/{task['id']}")

    assert response.status_code == 200
    assert 'aria-label="主导航"' in response.text
    assert 'class="app-sidebar"' in response.text
    assert 'class="app-main review-main shell"' in response.text
    assert '/static/design_system.css' in response.text
    assert 'href="/"' in response.text
    assert 'href="/settings/cloud-usage"' in response.text
    assert "返回工作台" in response.text
    assert "审核示例" in response.text
    assert "preview.mp4" in response.text
    assert "标题1" in response.text
    assert "点赞数 120000" in response.text
    assert "尚未在本机剪映打开" in response.text
    assert "剪辑理解证据" in response.text
    assert ">段语音转写<" in response.text
    assert ">8<" in response.text
    assert "hook:speech:先看结果" in response.text
    assert "captions.srt" in response.text
    assert "质量门禁" in response.text
    assert "画布符合竖屏交付规格" in response.text
    assert "本条视频云端消耗" in response.text
    assert "Dify Token" in response.text
    assert 'class="review-stage"' in response.text
    assert 'id="review-inspector"' in response.text
    assert 'id="review-issues"' in response.text
    assert "旁白覆盖" in response.text
    assert "字幕覆盖" in response.text
    assert ">100%<" in response.text
    assert 'data-timeline-start="' in response.text
    assert "在剪映中导入草稿" in response.text
    assert "抖音官方交付" in response.text
    assert "仅自己可见" in response.text
    assert "/static/review.js" in response.text

    review_script = client.get("/static/review.js")
    assert review_script.status_code == 200
    assert "currentTime" in review_script.text
    assert "data-timeline-start" in review_script.text


@pytest.mark.parametrize("name", ["captions.srt", "edit-timeline.json", "render-report.json"])
def test_editing_evidence_artifacts_are_downloadable(client: TestClient, name: str):
    task = create_task(client)
    create_review_artifacts(client, task["id"])

    response = client.get(f"/api/tasks/{task['id']}/artifacts/{name}")

    assert response.status_code == 200


def test_change_request_is_audited_without_artifacts(client: TestClient):
    task = create_task(client)

    changed = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "request_changes", "comment": "调整前三秒节奏"},
    )
    events = client.get(f"/api/tasks/{task['id']}/review-events").json()

    assert changed.status_code == 200
    assert changed.json()["status"] == "changes_requested"
    assert events[0]["decision"] == "request_changes"


def test_approval_rejects_invalid_review_manifest(client: TestClient):
    task = create_task(client)
    task_dir = create_review_artifacts(client, task["id"])
    (task_dir / "review.json").write_text(
        json.dumps({"aigc_declaration": "", "evidence": [], "warnings": [], "publish_copy": []}),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_review_manifest"


def test_approval_rejects_blocking_quality_gate(client: TestClient):
    task = create_task(client)
    task_dir = create_review_artifacts(client, task["id"])
    (task_dir / "quality-report.json").write_text(
        json.dumps(
            {
                "status": "fail",
                "gates": [
                    {
                        "name": "canvas",
                        "status": "fail",
                        "blocking": True,
                        "message": "expected 1080x1920",
                        "evidence": {"actual": "320x240"},
                    }
                ],
                "blocking_failures": ["canvas"],
            }
        ),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/tasks/{task['id']}/review",
        json={"decision": "approve"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "quality_gates_failed",
        "blocking_failures": ["canvas"],
    }
