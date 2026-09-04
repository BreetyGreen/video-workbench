from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import TutorialDemoRun, TutorialSegment, TutorialSegmentType
from app.services.tutorial_demo_service import TutorialDemoService


class FakeTutorialDemoService:
    def create(self, session):
        run = TutorialDemoRun(
            state="completed",
            stage="complete",
            course_id="course-demo",
            recipe_id="recipe-demo",
            job_id="job-demo",
            task_id="task-demo",
            artifacts_json='{"review_url":"/review/task-demo","preview_url":"/api/tasks/task-demo/artifacts/preview.mp4"}',
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    def execute(self, run_id: str) -> None:
        return None


def test_tutorial_demo_serializes_multimodal_segment_evidence() -> None:
    segment = TutorialSegment(
        id="segment-1",
        recipe_id="recipe-1",
        source_asset_id="asset-1",
        segment_type=TutorialSegmentType.FINISHED_EXAMPLE,
        start_ms=4200,
        end_ms=8300,
        transcript_text="下面看完成示例",
        ocr_text_json='["成片预览"]',
        visual_cues_json='["example:成片预览"]',
        related_rule_ids_json='["rule-1"]',
        confidence=0.95,
        sort_order=2,
    )

    assert TutorialDemoService.segment_payload(segment) == {
        "id": "segment-1",
        "source_asset_id": "asset-1",
        "segment_type": "finished_example",
        "start_ms": 4200,
        "end_ms": 8300,
        "source_page": None,
        "transcript_text": "下面看完成示例",
        "ocr_texts": ["成片预览"],
        "visual_cues": ["example:成片预览"],
        "related_rule_ids": ["rule-1"],
        "confidence": 0.95,
        "sort_order": 2,
    }


def test_tutorial_demo_requires_real_mixed_segment_coverage() -> None:
    TutorialDemoService.validate_segment_coverage(
        [
            TutorialSegmentType.LECTURE,
            TutorialSegmentType.SOFTWARE_OPERATION,
            TutorialSegmentType.FINISHED_EXAMPLE,
        ]
    )

    with pytest.raises(ValueError, match="tutorial_demo_segment_types_missing:finished_example"):
        TutorialDemoService.validate_segment_coverage(
            [TutorialSegmentType.LECTURE, TutorialSegmentType.SOFTWARE_OPERATION]
        )


def test_tutorial_learning_demo_api_returns_replayable_acceptance_run(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'demo.db').as_posix()}",
        automation_enabled=False,
    )
    app = create_app(settings, tutorial_demo_service_override=FakeTutorialDemoService())

    with TestClient(app) as client:
        created = client.post("/api/tutorial-learning-demo")
        fetched = client.get(f"/api/tutorial-learning-demo/{created.json()['id']}")

    assert created.status_code == 202
    assert created.json()["state"] == "completed"
    assert created.json()["artifacts"]["review_url"] == "/review/task-demo"
    assert fetched.status_code == 200
    assert fetched.json()["task_id"] == "task-demo"
    assert fetched.json()["artifacts"]["preview_url"].endswith("preview.mp4")


def test_missing_tutorial_demo_run_returns_not_found(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'demo-missing.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings, tutorial_demo_service_override=FakeTutorialDemoService())) as client:
        response = client.get("/api/tutorial-learning-demo/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "tutorial_demo_not_found"
