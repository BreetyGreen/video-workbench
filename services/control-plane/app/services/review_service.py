from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from app.models import ReviewEvent, TaskStatus, VideoTask
from app.schemas import ReviewDecision
from app.services.task_service import get_task
from app.services.quality_gate_service import QualityReport


REQUIRED_REVIEW_ARTIFACTS = ("preview.mp4", "draft.zip", "quality-report.json", "review.json")
DOWNLOADABLE_ARTIFACTS = {
    "preview.mp4",
    "draft.zip",
    "cover.jpg",
    "review.json",
    "captions.srt",
    "captions.ass",
    "edit-timeline.json",
    "render-report.json",
    "quality-report.json",
    "baseline-timeline.json",
    "course-rule-trace.json",
    "course-comparison.json",
    "rights-ledger.json",
    "tutorial-provenance.json",
    "tutorial-learning.mp4",
    "tutorial-transcript.json",
    "learned-course-recipe.json",
}


class ReviewCopy(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)


class ReviewManifest(BaseModel):
    aigc_declaration: str = Field(min_length=1)
    evidence: list[str]
    warnings: list[str]
    publish_copy: list[ReviewCopy] = Field(min_length=3, max_length=3)
    analysis_summary: dict[str, int] = Field(default_factory=dict)
    production_profile: dict[str, object] = Field(default_factory=dict)
    model_routes: list[dict[str, object]] = Field(default_factory=list)
    audio_route: dict[str, object] = Field(default_factory=dict)
    reference_brief: dict[str, object] | None = None
    quality_report: dict[str, object] = Field(default_factory=dict)
    timeline: list[dict[str, str | float]] = Field(default_factory=list)


@dataclass(frozen=True)
class ReviewBundle:
    task_dir: Path
    manifest: dict[str, object]
    missing: list[str]
    invalid_reason: str = ""
    quality_report: dict[str, object] | None = None
    quality_invalid_reason: str = ""
    blocking_failures: list[str] = field(default_factory=list)


class ReviewService:
    def __init__(self, artifact_root: Path):
        self.artifact_root = artifact_root.resolve()

    def task_dir(self, task_id: str) -> Path:
        resolved = (self.artifact_root / task_id).resolve()
        if self.artifact_root not in resolved.parents:
            raise ValueError("Review artifact path escapes configured root")
        return resolved

    def load_bundle(self, task_id: str) -> ReviewBundle:
        task_dir = self.task_dir(task_id)
        missing = [name for name in REQUIRED_REVIEW_ARTIFACTS if not (task_dir / name).is_file()]
        manifest_path = task_dir / "review.json"
        manifest: dict[str, object] = {}
        invalid_reason = ""
        quality_report: dict[str, object] | None = None
        quality_invalid_reason = ""
        blocking_failures: list[str] = []
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = ReviewManifest.model_validate(loaded).model_dump()
            except (json.JSONDecodeError, ValidationError) as error:
                invalid_reason = str(error)
        quality_path = task_dir / "quality-report.json"
        if quality_path.is_file():
            try:
                validated_quality = QualityReport.model_validate_json(
                    quality_path.read_text(encoding="utf-8")
                )
                quality_report = validated_quality.model_dump()
                blocking_failures = validated_quality.blocking_failures
            except (json.JSONDecodeError, ValidationError) as error:
                quality_invalid_reason = str(error)
        return ReviewBundle(
            task_dir=task_dir,
            manifest=manifest,
            missing=missing,
            invalid_reason=invalid_reason,
            quality_report=quality_report,
            quality_invalid_reason=quality_invalid_reason,
            blocking_failures=blocking_failures,
        )

    def artifact_path(self, task_id: str, name: str) -> Path:
        if name not in DOWNLOADABLE_ARTIFACTS:
            raise FileNotFoundError(name)
        candidate = self.task_dir(task_id) / name
        if not candidate.is_file():
            raise FileNotFoundError(name)
        return candidate


def apply_review(
    session: Session,
    task: VideoTask,
    *,
    decision: ReviewDecision,
    comment: str,
) -> VideoTask:
    task.status = TaskStatus.APPROVED if decision == ReviewDecision.APPROVE else TaskStatus.CHANGES_REQUESTED
    event = ReviewEvent(
        task_id=task.id,
        decision=decision.value,
        comment=comment,
    )
    session.add(task)
    session.add(event)
    session.commit()
    return get_task(session, task.id)  # type: ignore[return-value]


def list_review_events(session: Session, task_id: str) -> list[ReviewEvent]:
    statement = (
        select(ReviewEvent)
        .where(ReviewEvent.task_id == task_id)
        .order_by(ReviewEvent.created_at, ReviewEvent.id)
    )
    return list(session.exec(statement).all())
