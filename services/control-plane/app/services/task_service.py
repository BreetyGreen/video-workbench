from __future__ import annotations

import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    CourseAsset,
    LicensedAsset,
    Material,
    TaskBrief,
    TaskProductionSettings,
    TaskStatus,
    TaskVoiceSelection,
    VideoTask,
)


class DuplicateTaskError(ValueError):
    """Raised when an intake source retries an already-created task."""


def _safe_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


def create_task(
    session: Session,
    settings: Settings,
    *,
    title: str,
    content_type: str,
    rights_confirmed: bool,
    files: list[UploadFile],
    requirements_text: str = "",
    tutorial_text: str = "",
    quality_profile: str = "production",
    cloud_processing_allowed: bool = False,
    voice_preset: str = "vivi-2",
    voice_type: str = "zh_female_vv_uranus_bigtts",
    reference_file: UploadFile | None = None,
    source_type: str | None = None,
    source_user: str | None = None,
    source_conversation: str | None = None,
    source_message_id: str | None = None,
    deduplication_key: str | None = None,
) -> VideoTask:
    if deduplication_key:
        existing = session.exec(
            select(VideoTask).where(VideoTask.deduplication_key == deduplication_key)
        ).first()
        if existing is not None:
            raise DuplicateTaskError(deduplication_key)
    task = VideoTask(
        title=title.strip(),
        content_type=content_type.strip(),
        rights_confirmed=rights_confirmed,
        source_type=source_type,
        source_user=source_user,
        source_conversation=source_conversation,
        source_message_id=source_message_id,
        deduplication_key=deduplication_key,
    )
    task.brief = TaskBrief(
        task_id=task.id,
        requirements_text=requirements_text.strip(),
        tutorial_text=tutorial_text.strip(),
    )
    task.production_settings = TaskProductionSettings(
        task_id=task.id,
        quality_profile=quality_profile,
        cloud_processing_allowed=cloud_processing_allowed,
    )
    task.voice_selection = TaskVoiceSelection(
        task_id=task.id,
        preset_id=voice_preset,
        voice_type=voice_type,
    )
    task_dir = settings.material_dir / task.id
    task_dir.mkdir(parents=True, exist_ok=True)

    if reference_file is not None and reference_file.filename:
        mime_type = (reference_file.content_type or "").split(";", 1)[0].lower()
        if not mime_type.startswith("video/"):
            raise ValueError("Reference file must be a video")
        reference_payload = reference_file.file.read()
        reference_name = Path(reference_file.filename).name
        reference_path = (task_dir / f"reference-{uuid4()}{_safe_extension(reference_name)}").resolve()
        reference_path.write_bytes(reference_payload)
        task.production_settings.reference_name = reference_name
        task.production_settings.reference_path = str(reference_path)
        task.production_settings.reference_sha256 = hashlib.sha256(reference_payload).hexdigest()

    for upload in files:
        payload = upload.file.read()
        storage_name = f"{uuid4()}{_safe_extension(upload.filename)}"
        stored_path = (task_dir / storage_name).resolve()
        stored_path.write_bytes(payload)
        task.materials.append(
            Material(
                task_id=task.id,
                original_name=Path(upload.filename or "unnamed").name,
                stored_path=str(stored_path),
                mime_type=upload.content_type or "application/octet-stream",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    session.add(task)
    session.commit()
    session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]


def create_task_from_library_assets(
    session: Session,
    settings: Settings,
    *,
    title: str,
    content_type: str,
    assets: list[LicensedAsset],
    requirements_text: str,
    tutorial_text: str = "",
    quality_profile: str = "production",
    cloud_processing_allowed: bool = True,
    voice_preset: str = "vivi-2",
    voice_type: str = "zh_female_vv_uranus_bigtts",
    source_type: str = "daily_automation",
    deduplication_key: str,
) -> VideoTask:
    """Create a task from the centrally tracked, licensed material catalog."""
    if not assets:
        raise ValueError("At least one licensed asset is required")
    existing = session.exec(
        select(VideoTask).where(VideoTask.deduplication_key == deduplication_key)
    ).first()
    if existing is not None:
        raise DuplicateTaskError(deduplication_key)

    task = VideoTask(
        title=title.strip(),
        content_type=content_type.strip(),
        rights_confirmed=True,
        source_type=source_type,
        deduplication_key=deduplication_key,
    )
    task.brief = TaskBrief(
        task_id=task.id,
        requirements_text=requirements_text.strip(),
        tutorial_text=tutorial_text.strip(),
    )
    task.production_settings = TaskProductionSettings(
        task_id=task.id,
        quality_profile=quality_profile,
        cloud_processing_allowed=cloud_processing_allowed,
    )
    task.voice_selection = TaskVoiceSelection(
        task_id=task.id,
        preset_id=voice_preset,
        voice_type=voice_type,
    )

    task_dir = settings.material_dir / task.id
    task_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        source = Path(asset.stored_path).resolve()
        library_root = settings.library_dir.resolve()
        if library_root not in source.parents or not source.is_file():
            raise ValueError("licensed_asset_path_outside_library")
        suffix = _safe_extension(asset.original_name) or source.suffix.lower() or ".mp4"
        destination = (task_dir / f"{uuid4()}{suffix}").resolve()
        if task_dir.resolve() not in destination.parents:
            raise ValueError("task_material_destination_outside_root")
        shutil.copy2(source, destination)
        task.materials.append(
            Material(
                task_id=task.id,
                original_name=Path(asset.original_name).name,
                stored_path=str(destination),
                mime_type=asset.mime_type,
                size_bytes=destination.stat().st_size,
                sha256=asset.sha256,
            )
        )

    session.add(task)
    session.commit()
    session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]


def create_task_from_course_assets(
    session: Session,
    settings: Settings,
    *,
    title: str,
    content_type: str,
    assets: list[CourseAsset],
    requirements_text: str,
    tutorial_text: str,
    commercial: bool,
    quality_profile: str = "production",
    cloud_processing_allowed: bool = False,
    voice_preset: str = "vivi-2",
    voice_type: str = "zh_female_vv_uranus_bigtts",
    course_recipe_id: str | None = None,
) -> VideoTask:
    """Create an isolated render task from course-owned, rights-checked assets."""
    if not assets:
        raise ValueError("course_materials_required")

    task = VideoTask(
        title=title.strip(),
        content_type=content_type.strip(),
        rights_confirmed=True,
        source_type="course_automation",
        course_recipe_id=course_recipe_id,
    )
    task.brief = TaskBrief(
        task_id=task.id,
        requirements_text=requirements_text.strip(),
        tutorial_text=tutorial_text.strip(),
    )
    task.production_settings = TaskProductionSettings(
        task_id=task.id,
        quality_profile=quality_profile,
        cloud_processing_allowed=cloud_processing_allowed,
    )
    task.voice_selection = TaskVoiceSelection(
        task_id=task.id,
        preset_id=voice_preset,
        voice_type=voice_type,
    )

    course_root = (settings.data_dir / "courses").resolve()
    task_dir = (settings.material_dir / task.id).resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        source = Path(asset.stored_path).resolve()
        if course_root not in source.parents or not source.is_file():
            raise ValueError("course_asset_path_outside_storage")
        suffix = _safe_extension(asset.original_name) or source.suffix.lower() or ".mp4"
        destination = (task_dir / f"{uuid4()}{suffix}").resolve()
        if task_dir not in destination.parents:
            raise ValueError("task_material_destination_outside_root")
        shutil.copy2(source, destination)
        task.materials.append(
            Material(
                task_id=task.id,
                original_name=Path(asset.original_name).name,
                stored_path=str(destination),
                mime_type=asset.mime_type,
                size_bytes=destination.stat().st_size,
                sha256=asset.sha256,
            )
        )

    session.add(task)
    session.commit()
    session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]


def get_task(session: Session, task_id: str) -> VideoTask | None:
    statement = select(VideoTask).where(VideoTask.id == task_id)
    return session.exec(statement).first()


def list_tasks(
    session: Session,
    limit: int = 100,
    *,
    include_archived: bool = False,
) -> list[VideoTask]:
    statement = select(VideoTask)
    if not include_archived:
        statement = statement.where(VideoTask.archived_at.is_(None))
    statement = statement.order_by(VideoTask.created_at.desc()).limit(limit)
    return list(session.exec(statement).all())


def archive_task(session: Session, task: VideoTask, reason: str) -> VideoTask:
    if task.archived_at is None:
        task.archived_at = datetime.now(UTC)
        task.archive_reason = reason.strip() or "manual"
        task.updated_at = datetime.now(UTC)
        session.add(task)
        session.commit()
        session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]


def restore_task(session: Session, task: VideoTask) -> VideoTask:
    if task.archived_at is not None:
        task.archived_at = None
        task.archive_reason = None
        task.updated_at = datetime.now(UTC)
        session.add(task)
        session.commit()
        session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]


def set_review_decision(
    session: Session,
    task: VideoTask,
    *,
    approved: bool,
) -> VideoTask:
    task.status = TaskStatus.APPROVED if approved else TaskStatus.CHANGES_REQUESTED
    task.updated_at = datetime.now(UTC)
    session.add(task)
    session.commit()
    session.refresh(task)
    return get_task(session, task.id)  # type: ignore[return-value]
