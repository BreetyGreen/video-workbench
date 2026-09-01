from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import TutorialDemoRun


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
