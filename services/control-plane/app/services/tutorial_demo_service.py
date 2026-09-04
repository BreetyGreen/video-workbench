from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from sqlmodel import Session, select

from app.config import Settings
from app.db import Database
from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    EditingRule,
    RightsStatus,
    TutorialDemoRun,
    TutorialSegment,
    TutorialSegmentType,
)
from app.services.tutorial_demo_assets import TutorialDemoAssetService


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_string_list(raw: str | None, *, maximum_items: int = 200) -> list[str]:
    try:
        payload = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list) or len(payload) > maximum_items:
        return []
    return [item for item in payload if isinstance(item, str) and len(item) <= 2_000]


class TutorialDemoService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        assets: TutorialDemoAssetService,
        tutorial_understanding: Any,
        course_jobs: Any,
    ):
        self.settings = settings
        self.database = database
        self.assets = assets
        self.tutorial_understanding = tutorial_understanding
        self.course_jobs = course_jobs

    @staticmethod
    def segment_payload(segment: TutorialSegment) -> dict[str, object]:
        return {
            "id": segment.id,
            "source_asset_id": segment.source_asset_id,
            "segment_type": segment.segment_type.value,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "source_page": segment.source_page,
            "transcript_text": segment.transcript_text,
            "ocr_texts": _bounded_string_list(segment.ocr_text_json),
            "visual_cues": _bounded_string_list(segment.visual_cues_json),
            "related_rule_ids": _bounded_string_list(segment.related_rule_ids_json),
            "confidence": segment.confidence,
            "sort_order": segment.sort_order,
        }

    @staticmethod
    def validate_segment_coverage(segment_types: list[object]) -> None:
        normalized = {
            item.value if isinstance(item, TutorialSegmentType) else str(item)
            for item in segment_types
        }
        required = {
            TutorialSegmentType.LECTURE.value,
            TutorialSegmentType.SOFTWARE_OPERATION.value,
            TutorialSegmentType.FINISHED_EXAMPLE.value,
        }
        missing = sorted(required - normalized)
        if missing:
            raise ValueError(f"tutorial_demo_segment_types_missing:{','.join(missing)}")

    def create(self, session: Session) -> TutorialDemoRun:
        run = TutorialDemoRun()
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def _stage(session: Session, run: TutorialDemoRun, stage: str) -> None:
        run.state = "running"
        run.stage = stage
        run.updated_at = datetime.now(UTC)
        session.add(run)
        session.commit()

    def execute(self, run_id: str) -> None:
        with Session(self.database.engine) as session:
            run = session.get(TutorialDemoRun, run_id)
            if run is None:
                return
            try:
                self._stage(session, run, "creating_course")
                course = Course(
                    title="宠物护理教学视频学习演示",
                    source_type="tutorial_demo",
                    source_message_id=f"tutorial-demo-{run.id}",
                )
                session.add(course)
                session.commit()
                session.refresh(course)
                run.course_id = course.id
                session.add(run)
                session.commit()

                course_root = self.settings.data_dir / "courses" / course.id / "tutorial-demo"
                self._stage(session, run, "preparing_tutorial_video")
                tutorial = self.assets.prepare_tutorial(course_root)
                self._stage(session, run, "preparing_licensed_materials")
                materials = self.assets.prepare_materials(course_root)
                tutorial_asset = CourseAsset(
                    course_id=course.id,
                    role=CourseAssetRole.TUTORIAL,
                    original_name=tutorial.video_path.name,
                    stored_path=str(tutorial.video_path),
                    mime_type="video/mp4",
                    size_bytes=tutorial.video_path.stat().st_size,
                    sha256=_hash(tutorial.video_path),
                    rights_status=RightsStatus.PERSONAL_LEARNING,
                    source_message_id=f"tutorial-demo-{run.id}-tutorial",
                )
                session.add(tutorial_asset)
                ledger = json.loads(materials.rights_ledger_path.read_text(encoding="utf-8"))
                ledger_by_path = {Path(item["local_path"]).resolve(): item for item in ledger["materials"]}
                for index, path in enumerate(materials.material_paths, start=1):
                    row = ledger_by_path[path.resolve()]
                    session.add(
                        CourseAsset(
                            course_id=course.id,
                            role=CourseAssetRole.MATERIAL,
                            original_name=path.name,
                            stored_path=str(path),
                            mime_type="video/mp4" if path.suffix.lower() == ".mp4" else "video/webm",
                            size_bytes=path.stat().st_size,
                            sha256=str(row["sha256"]),
                            rights_status=RightsStatus.COMMERCIAL_AUTHORIZED,
                            source_message_id=f"tutorial-demo-{run.id}-material-{index}",
                        )
                    )
                session.commit()

                self._stage(session, run, "transcribing_and_learning")
                cloud_asr_ready = bool(
                    self.settings.volcano_asr_api_key
                    or (
                        self.settings.volcano_asr_app_key
                        and self.settings.volcano_asr_access_key
                    )
                )
                quality_profile = "production" if cloud_asr_ready else "fast_preview"
                recipe = self.tutorial_understanding.process(
                    session,
                    course.id,
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_asr_ready,
                )
                run.recipe_id = recipe.id
                session.add(run)
                session.commit()
                learned_segment_types = list(
                    session.exec(
                        select(TutorialSegment.segment_type)
                        .where(TutorialSegment.recipe_id == recipe.id)
                    ).all()
                )
                self.validate_segment_coverage(learned_segment_types)

                self._stage(session, run, "editing_and_quality_gate")
                result = self.course_jobs.run(
                    session,
                    course_id=course.id,
                    title="宠物护理前后对比",
                    content_type="商品介绍",
                    commercial=True,
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_asr_ready,
                )
                run.job_id = result.job.id
                run.task_id = result.task.id
                session.add(run)
                session.commit()
                if result.job.state in {"quality_blocked", "failed", "handoff_failed"}:
                    raise ValueError(result.job.error_code or result.job.state)

                self._stage(session, run, "collecting_acceptance_evidence")
                task_dir = self.settings.artifact_dir / result.task.id
                transcript_source = tutorial.video_path.with_suffix(".transcript.json")
                visual_analysis_source = tutorial.video_path.with_suffix(".tutorial-analysis.json")
                copies = {
                    materials.rights_ledger_path: task_dir / "rights-ledger.json",
                    tutorial.provenance_path: task_dir / "tutorial-provenance.json",
                    tutorial.video_path: task_dir / "tutorial-learning.mp4",
                }
                if transcript_source.is_file():
                    copies[transcript_source] = task_dir / "tutorial-transcript.json"
                if visual_analysis_source.is_file():
                    copies[visual_analysis_source] = task_dir / "tutorial-visual-analysis.json"
                for source, destination in copies.items():
                    shutil.copy2(source, destination)
                rules = list(
                    session.exec(
                        select(EditingRule)
                        .where(EditingRule.recipe_id == recipe.id)
                        .order_by(EditingRule.sort_order, EditingRule.id)
                    ).all()
                )
                segments = list(
                    session.exec(
                        select(TutorialSegment)
                        .where(TutorialSegment.recipe_id == recipe.id)
                        .order_by(TutorialSegment.sort_order, TutorialSegment.id)
                    ).all()
                )
                segment_payloads = [self.segment_payload(segment) for segment in segments]
                (task_dir / "tutorial-segments.json").write_text(
                    json.dumps({"recipe_id": recipe.id, "segments": segment_payloads}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (task_dir / "learned-course-recipe.json").write_text(
                    json.dumps(
                        {
                            "recipe": recipe.model_dump(mode="json"),
                            "rules": [rule.model_dump(mode="json") for rule in rules],
                            "segments": segment_payloads,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                artifacts = {
                    "review_url": f"/review/{result.task.id}",
                    "preview_url": f"/api/tasks/{result.task.id}/artifacts/preview.mp4",
                    "tutorial_video_url": f"/api/tasks/{result.task.id}/artifacts/tutorial-learning.mp4",
                    "transcript_url": f"/api/tasks/{result.task.id}/artifacts/tutorial-transcript.json",
                    "segments_url": f"/api/tasks/{result.task.id}/artifacts/tutorial-segments.json",
                    "recipe_url": f"/api/tasks/{result.task.id}/artifacts/learned-course-recipe.json",
                    "comparison_url": f"/api/tasks/{result.task.id}/artifacts/course-comparison.json",
                    "rule_trace_url": f"/api/tasks/{result.task.id}/artifacts/course-rule-trace.json",
                    "rights_ledger_url": f"/api/tasks/{result.task.id}/artifacts/rights-ledger.json",
                    "draft_url": f"/api/tasks/{result.task.id}/artifacts/draft.zip",
                }
                run.state = "completed"
                run.stage = "complete"
                run.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
                run.error_code = ""
                run.updated_at = datetime.now(UTC)
                run.finished_at = datetime.now(UTC)
                session.add(run)
                session.commit()
            except Exception as error:
                session.rollback()
                run = session.get(TutorialDemoRun, run_id)
                if run is not None:
                    run.state = "failed"
                    run.stage = "failed"
                    run.error_code = f"{type(error).__name__}:{error}"[:300]
                    run.updated_at = datetime.now(UTC)
                    run.finished_at = datetime.now(UTC)
                    session.add(run)
                    session.commit()
