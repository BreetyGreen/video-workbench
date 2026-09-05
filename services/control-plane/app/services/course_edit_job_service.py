from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    CourseEditJob,
    DeliveryDevice,
    EditingRecipe,
    EditingRule,
    RightsStatus,
    TaskStatus,
    VideoTask,
)
from app.services.task_service import create_task_from_course_assets, get_task


@dataclass(frozen=True)
class CourseEditJobResult:
    job: CourseEditJob
    task: VideoTask

    @property
    def state(self) -> str:
        return self.job.state

    @property
    def task_id(self) -> str | None:
        return self.job.task_id

    @property
    def handoff_status(self) -> str:
        return self.job.handoff_status

    @property
    def review_skipped(self) -> bool:
        return self.job.review_skipped

    @property
    def quality_status(self) -> str:
        return self.job.quality_status


class CourseEditJobService:
    def __init__(self, settings: Settings, pipeline: Any, handoff: Any):
        self.settings = settings
        self.pipeline = pipeline
        self.handoff = handoff

    def run(
        self,
        session: Session,
        *,
        course_id: str,
        title: str,
        content_type: str,
        commercial: bool = True,
        quality_profile: str = "production",
        cloud_processing_allowed: bool = False,
        material_ids: list[str] | None = None,
        device_id: str | None = None,
        requirements_text: str = "",
        job_id: str | None = None,
    ) -> CourseEditJobResult:
        course = session.get(Course, course_id)
        if course is None:
            raise ValueError("course_not_found")
        if device_id is not None:
            device = session.get(DeliveryDevice, device_id)
            if device is None or not device.active:
                raise ValueError("device_unavailable")
        recipe = session.exec(
            select(EditingRecipe)
            .where(EditingRecipe.course_id == course_id)
            .order_by(EditingRecipe.version.desc(), EditingRecipe.created_at.desc())
        ).first()
        if recipe is None:
            raise ValueError("course_recipe_required")

        assets = list(
            session.exec(
                select(CourseAsset)
                .where(CourseAsset.course_id == course_id)
                .where(CourseAsset.role == CourseAssetRole.MATERIAL)
                .where(CourseAsset.mime_type.startswith("video/"))
            ).all()
        )
        allowed_rights = (
            {RightsStatus.COMMERCIAL_AUTHORIZED}
            if commercial
            else {RightsStatus.PERSONAL_LEARNING, RightsStatus.COMMERCIAL_AUTHORIZED}
        )
        assets = [item for item in assets if item.rights_status in allowed_rights]
        if material_ids is not None:
            available = {item.id: item for item in assets}
            if not material_ids or any(item not in available for item in material_ids):
                raise ValueError("selected_material_unavailable_or_unlicensed")
            assets = [available[item] for item in dict.fromkeys(material_ids)]
        if not assets:
            raise ValueError("commercial_material_not_authorized" if commercial else "personal_material_not_authorized")

        rules = list(
            session.exec(
                select(EditingRule)
                .where(EditingRule.recipe_id == recipe.id)
                .order_by(EditingRule.sort_order, EditingRule.id)
            ).all()
        )
        if not rules:
            raise ValueError("course_recipe_has_no_rules")
        tutorial_text = "\n".join(
            f"[{rule.category}] {rule.instruction}（来源素材 {rule.source_asset_id}"
            + (f"，第 {rule.source_page} 页" if rule.source_page else "")
            + (f"，{rule.source_start_ms}-{rule.source_end_ms}ms" if rule.source_start_ms is not None else "")
            + "）"
            for rule in rules
        )
        job = CourseEditJob(
            **({"id": job_id} if job_id else {}),
            course_id=course_id,
            device_id=device_id,
            recipe_id=recipe.id,
            state="creating_task",
            commercial=commercial,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        try:
            task = create_task_from_course_assets(
                session,
                self.settings,
                title=title,
                content_type=content_type,
                assets=assets,
                requirements_text=f"按课程《{course.title}》的最新剪辑配方自动成片。\n{requirements_text}",
                tutorial_text=tutorial_text,
                commercial=commercial,
                quality_profile=quality_profile,
                cloud_processing_allowed=cloud_processing_allowed,
                course_recipe_id=recipe.id,
            )
            job.task_id = task.id
            job.state = "rendering"
            job.updated_at = datetime.now(UTC)
            session.add(job)
            session.commit()

            self._write_course_evidence(session, task.id, recipe, rules)
            self.pipeline.process(session, task)
            quality = self._read_quality(task.id)
            quality_status = quality.get("status")
            blocking_failures = quality.get("blocking_failures")
            if quality_status not in {"pass", "warn", "fail"} or not isinstance(blocking_failures, list):
                raise ValueError("quality_report_missing_or_invalid")
            job.quality_status = quality_status
            if quality_status == "fail" or blocking_failures:
                job.state = "quality_blocked"
                job.review_skipped = False
                job.updated_at = datetime.now(UTC)
                session.add(job)
                session.commit()
                return CourseEditJobResult(job=job, task=get_task(session, task.id) or task)

            task = get_task(session, task.id) or task
            task.status = TaskStatus.APPROVED
            task.updated_at = datetime.now(UTC)
            session.add(task)
            session.commit()
            job.review_skipped = True

            # Server jobs for a selected computer must never import on the server
            # or enter the unassigned device queue.
            handoff = {"status": "waiting"} if device_id else self.handoff.import_task(task.id)
            job.handoff_status = str(handoff.get("status") or "unknown")
            if job.handoff_status == "imported":
                job.state = "delivered_to_jianying"
            elif job.handoff_status == "waiting":
                job.state = "awaiting_device"
            else:
                job.state = "handoff_failed"
                job.error_code = str(handoff.get("code") or "handoff_failed")
            job.updated_at = datetime.now(UTC)
            session.add(job)
            session.commit()
            session.refresh(job)
            return CourseEditJobResult(job=job, task=get_task(session, task.id) or task)
        except Exception as error:
            job.state = "failed"
            job.error_code = str(error)[:200]
            job.updated_at = datetime.now(UTC)
            session.add(job)
            session.commit()
            raise

    def _read_quality(self, task_id: str) -> dict[str, Any]:
        path = self.settings.artifact_dir / task_id / "quality-report.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("quality_report_missing_or_invalid") from error
        if not isinstance(payload, dict):
            raise ValueError("quality_report_missing_or_invalid")
        return payload

    def _write_course_evidence(self, session, task_id, recipe, rules):
        from app.services.course_evidence_service import write_course_evidence
        write_course_evidence(session, self.settings, task_id, recipe, rules)
