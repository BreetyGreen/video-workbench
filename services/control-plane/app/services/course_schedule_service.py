from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
import threading
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    Course, CourseAsset, CourseAssetRole, CourseEditJob, CourseSchedule, CourseScheduleRun,
    DeliveryDevice, EditingRecipe, RightsStatus,
)
from app.schemas.course_schedules import CourseScheduleCreate

logger = logging.getLogger(__name__)


class CourseScheduleService:
    def __init__(self, database, understanding, jobs):
        self.database = database
        self.understanding = understanding
        self.jobs = jobs
        self._stop = threading.Event()
        self._thread = None

    def validate(self, session: Session, config: CourseScheduleCreate):
        if session.get(Course, config.course_id) is None:
            raise ValueError("course_not_found")
        if config.device_id:
            device = session.get(DeliveryDevice, config.device_id)
            if device is None or not device.active:
                raise ValueError("device_unavailable")
        allowed = {RightsStatus.COMMERCIAL_AUTHORIZED}
        if not config.commercial:
            allowed.add(RightsStatus.PERSONAL_LEARNING)
        for asset_id in config.material_ids:
            asset = session.get(CourseAsset, asset_id)
            if (asset is None or asset.course_id != config.course_id
                    or asset.role != CourseAssetRole.MATERIAL or not asset.mime_type.startswith("video/")
                    or asset.rights_status not in allowed):
                raise ValueError("selected_material_unavailable_or_unlicensed")

    def create(self, session: Session, config: CourseScheduleCreate):
        self.validate(session, config)
        plan = CourseSchedule(course_id=config.course_id, title=config.title,
                              configuration_json=config.model_dump_json(), enabled=config.enabled)
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return plan

    def enqueue(self, session: Session, plan: CourseSchedule, *, now: datetime | None = None):
        config = CourseScheduleCreate.model_validate_json(plan.configuration_json)
        local_date = (now or datetime.now(UTC)).astimezone(ZoneInfo(config.timezone)).date().isoformat()
        query = select(CourseScheduleRun).where(CourseScheduleRun.schedule_id == plan.id,
                                               CourseScheduleRun.local_date == local_date)
        existing = session.exec(query).first()
        if existing:
            return existing, False
        run = CourseScheduleRun(schedule_id=plan.id, local_date=local_date,
                                configuration_json=plan.configuration_json)
        session.add(run)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.exec(query).first()
            if existing is None:
                raise
            return existing, False
        session.refresh(run)
        return run, True

    def enqueue_due(self, session: Session, *, now: datetime | None = None):
        now = now or datetime.now(UTC)
        result = []
        for plan in session.exec(select(CourseSchedule).where(CourseSchedule.enabled == True)).all():
            config = CourseScheduleCreate.model_validate_json(plan.configuration_json)
            if now.astimezone(ZoneInfo(config.timezone)).strftime("%H:%M") >= config.daily_time:
                run, created = self.enqueue(session, plan, now=now)
                if created:
                    result.append(run)
        return result

    def recover_interrupted(self, session: Session):
        for run in session.exec(select(CourseScheduleRun).where(CourseScheduleRun.state == "running")).all():
            job = session.get(CourseEditJob, run.job_id)
            terminal = {"awaiting_device", "delivered_to_jianying", "handoff_failed", "quality_blocked", "failed"}
            run.state = job.state if job and job.state in terminal else "interrupted"
            run.error_code = job.error_code if job and run.state != "interrupted" else "server_restarted_check_existing_task"
            run.finished_at = datetime.now(UTC)
            session.add(run)
        session.commit()

    def execute_next(self, session: Session):
        run = session.exec(select(CourseScheduleRun).where(CourseScheduleRun.state == "queued")
                           .order_by(CourseScheduleRun.created_at)).first()
        if run is None:
            return None
        claimed = session.exec(update(CourseScheduleRun).where(CourseScheduleRun.id == run.id,
                               CourseScheduleRun.state == "queued").values(state="running"))
        session.commit()
        if claimed.rowcount != 1:
            return None
        session.refresh(run)
        try:
            config = CourseScheduleCreate.model_validate_json(run.configuration_json)
            self.validate(session, config)  # Rights and device can change after scheduling.
            recipe = session.exec(select(EditingRecipe).where(EditingRecipe.course_id == config.course_id)).first()
            if recipe is None:
                self.understanding.process(session, config.course_id,
                                           cloud_processing_allowed=config.cloud_processing_allowed)
            result = self.jobs.run(session, course_id=config.course_id, title=config.title,
                                   content_type=config.content_type, commercial=config.commercial,
                                   cloud_processing_allowed=config.cloud_processing_allowed,
                                   material_ids=config.material_ids, device_id=config.device_id,
                                   requirements_text=config.requirements_text, job_id=run.job_id)
            run.state = result.state
            run.error_code = result.job.error_code
        except Exception as error:
            session.rollback()
            run = session.get(CourseScheduleRun, run.id)
            run.state = "failed"
            # Never expose exception strings that can include provider URLs or credentials.
            code = str(error)
            run.error_code = code if code.isascii() and code.replace("_", "").isalnum() and len(code) < 100 else "course_run_failed"
            logger.warning("Course schedule run %s failed (%s)", run.id, type(error).__name__)
        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    def start(self):
        # Supported deployment is one API process / one durable local queue worker.
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        with Session(self.database.engine) as session:
            self.recover_interrupted(session)
        self._thread = threading.Thread(target=self._loop, name="course-schedules", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                with Session(self.database.engine) as session:
                    self.enqueue_due(session)
                    run = self.execute_next(session)
                if run is not None:
                    continue
            except Exception as error:
                logger.warning("Course worker tick failed (%s)", type(error).__name__)
            self._stop.wait(5)

    async def stop(self):
        self._stop.set()
        if self._thread:
            await asyncio.to_thread(self._thread.join)

    @staticmethod
    def plan_read(plan):
        return {**json.loads(plan.configuration_json), "id": plan.id, "enabled": plan.enabled}

    @staticmethod
    def run_read(session, run):
        job = session.get(CourseEditJob, run.job_id)
        state = job.state if job and run.state in {"awaiting_device", "handoff_failed"} else run.state
        return {"id": run.id, "schedule_id": run.schedule_id, "local_date": run.local_date,
                "state": state, "error_code": run.error_code or (job.error_code if job else ""),
                "job_id": job.id if job else None, "task_id": job.task_id if job else None,
                "created_at": run.created_at, "finished_at": run.finished_at}
