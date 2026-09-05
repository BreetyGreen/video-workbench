from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Settings
from app.main import create_app
from app.models import CourseAsset, CourseEditJob, DeliveryDevice, RightsStatus
from test_course_edit_job_service import FakeHandoff, FakePipeline, _seed_course


@pytest.fixture
def environment(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'db.sqlite'}")
    pipeline = FakePipeline(settings.artifact_dir)
    app = create_app(settings, pipeline_service_override=pipeline, jianying_handoff_override=FakeHandoff())
    with TestClient(app) as client, Session(app.state.database.engine) as session:
        course = _seed_course(session, settings.data_dir, rights=RightsStatus.COMMERCIAL_AUTHORIZED)
        device = DeliveryDevice(name="接收 Mac", token_hash="test-only")
        session.add(device)
        session.commit()
        asset = session.exec(select(CourseAsset).where(CourseAsset.course_id == course.id)).one()
        yield app, client, session, pipeline, {
            "course_id": course.id, "title": "每天按教程剪帽子", "material_ids": [asset.id],
            "device_id": device.id, "daily_time": "09:00", "timezone": "Asia/Shanghai",
            "requirements_text": "不要配乐，保留原声", "enabled": True,
        }


def create_plan(client, payload):
    response = client.post("/api/course-schedules", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_course_page_and_safe_inventory(environment):
    app, client, session, pipeline, payload = environment
    page = client.get("/courses")
    assert page.status_code == 200
    assert "课程自动剪辑" in page.text
    inventory = client.get("/api/course-schedules/catalog").json()
    assert inventory["courses"][0]["id"] == payload["course_id"]
    assert inventory["devices"][0]["id"] == payload["device_id"]
    assert "token_hash" not in str(inventory)
    assert "stored_path" not in str(inventory)


@pytest.mark.parametrize("change", [
    {"course_id": "missing"}, {"material_ids": ["missing"]}, {"material_ids": []},
    {"device_id": "missing"}, {"daily_time": "25:00"}, {"timezone": "Not/AZone"},
])
def test_invalid_plan_rejected(environment, change):
    app, client, session, pipeline, payload = environment
    response = client.post("/api/course-schedules", json=payload | change)
    assert response.status_code in {400, 422}, response.text


def test_due_date_dedup_and_pause(environment):
    app, client, session, pipeline, payload = environment
    plan = create_plan(client, payload)
    service = app.state.course_schedules
    before = datetime(2026, 9, 6, 0, 59, tzinfo=UTC)
    due = datetime(2026, 9, 6, 1, 0, tzinfo=UTC)
    assert service.enqueue_due(session, now=before) == []
    runs = service.enqueue_due(session, now=due)
    assert len(runs) == 1
    assert service.enqueue_due(session, now=due) == []
    assert client.patch(f"/api/course-schedules/{plan['id']}", json={"enabled": False}).status_code == 200
    assert service.enqueue_due(session, now=datetime(2026, 9, 7, 1, 0, tzinfo=UTC)) == []


def test_run_uses_course_brief_and_routes_only_to_selected_device(environment):
    app, client, session, pipeline, payload = environment
    plan = create_plan(client, payload)
    endpoint = f"/api/course-schedules/{plan['id']}/run"
    run = client.post(endpoint).json()
    assert run["state"] == "queued"
    assert client.post(endpoint).json()["id"] == run["id"]
    app.state.course_schedules.execute_next(session)
    result = client.get(f"/api/course-schedules/{plan['id']}/runs").json()[0]
    assert result["state"] == "awaiting_device"
    job = session.get(CourseEditJob, result["job_id"])
    assert job.device_id == payload["device_id"]
    from app.services.task_service import get_task
    task = get_task(session, job.task_id)
    assert payload["requirements_text"] in task.requirements_text
    assert "前 3 秒展示佩戴效果" in task.tutorial_text
    assert task.production_settings.cloud_processing_allowed is False
    assert len(task.materials) == 1
    import json
    evidence = json.loads((app.state.settings.artifact_dir / task.id / "learned-course-recipe.json").read_text(encoding="utf-8"))
    assert evidence["rules"][0]["instruction"] == "前 3 秒展示佩戴效果"
    assert (app.state.settings.artifact_dir / task.id / "tutorial-segments.json").is_file()
    assert app.state.course_schedules.execute_next(session) is None


def test_quality_failure_does_not_deliver(environment):
    app, client, session, pipeline, payload = environment
    pipeline.blocked = True
    plan = create_plan(client, payload)
    client.post(f"/api/course-schedules/{plan['id']}/run")
    app.state.course_schedules.execute_next(session)
    result = client.get(f"/api/course-schedules/{plan['id']}/runs").json()[0]
    assert result["state"] == "quality_blocked"
    assert session.get(CourseEditJob, result["job_id"]).handoff_status == "pending"


def test_revoked_device_blocks_before_render(environment):
    app, client, session, pipeline, payload = environment
    plan = create_plan(client, payload)
    client.post(f"/api/course-schedules/{plan['id']}/run")
    device = session.get(DeliveryDevice, payload["device_id"])
    device.active = False
    session.add(device)
    session.commit()
    app.state.course_schedules.execute_next(session)
    result = client.get(f"/api/course-schedules/{plan['id']}/runs").json()[0]
    assert result["state"] == "failed"
    assert result["error_code"] == "device_unavailable"
    assert session.exec(select(CourseEditJob)).all() == []


def test_interrupted_run_is_not_automatically_repeated(environment):
    app, client, session, pipeline, payload = environment
    from app.models import CourseScheduleRun
    plan = create_plan(client, payload)
    result = client.post(f"/api/course-schedules/{plan['id']}/run").json()
    run = session.get(CourseScheduleRun, result["id"])
    run.state = "running"
    session.add(run)
    session.commit()
    app.state.course_schedules.recover_interrupted(session)
    session.refresh(run)
    assert run.state == "interrupted"
    assert app.state.course_schedules.execute_next(session) is None


def test_missing_recipe_processed_with_explicit_local_consent(environment):
    app, client, session, pipeline, payload = environment
    from app.models import EditingRecipe, EditingRule
    from sqlalchemy import delete
    session.exec(delete(EditingRule))
    session.exec(delete(EditingRecipe))
    session.commit()
    calls = []
    class Understanding:
        def process(self, session, course_id, *, cloud_processing_allowed):
            calls.append(cloud_processing_allowed)
            recipe = EditingRecipe(course_id=course_id, title="已学习教程")
            session.add(recipe)
            session.commit()
            session.add(EditingRule(recipe_id=recipe.id, category="hook", instruction="前三秒展示结果",
                                    source_asset_id=payload["material_ids"][0]))
            session.commit()
            return recipe
    app.state.course_schedules.understanding = Understanding()
    plan = create_plan(client, payload)
    client.post(f"/api/course-schedules/{plan['id']}/run")
    app.state.course_schedules.execute_next(session)
    assert calls == [False]


def test_empty_recipe_cannot_silently_produce_generic_video(environment):
    app, client, session, pipeline, payload = environment
    from app.models import EditingRule
    from sqlalchemy import delete
    session.exec(delete(EditingRule))
    session.commit()
    plan = create_plan(client, payload)
    client.post(f"/api/course-schedules/{plan['id']}/run")
    app.state.course_schedules.execute_next(session)
    run = client.get(f"/api/course-schedules/{plan['id']}/runs").json()[0]
    assert run["state"] == "failed"
    assert run["error_code"] == "course_recipe_has_no_rules"
