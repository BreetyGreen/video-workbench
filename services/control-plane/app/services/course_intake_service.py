from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import Session, select

from app.models import Course, CourseAsset, CourseAssetRole, RightsStatus


ALLOWED_COURSE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
}
ALLOWED_COURSE_MIME_PREFIXES = ("video/", "audio/", "image/")


class CourseIntakeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def course_mime_allowed(value: str) -> bool:
    mime_type = value.split(";", 1)[0].strip().lower()
    return mime_type in ALLOWED_COURSE_MIME_TYPES or mime_type.startswith(
        ALLOWED_COURSE_MIME_PREFIXES
    )


def _safe_filename(value: str | None) -> str:
    normalized = (value or "unnamed").replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] or "unnamed"


def _safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


class CourseIntakeService:
    def __init__(self, data_dir: Path, max_file_bytes: int):
        self.course_root = data_dir / "courses"
        self.max_file_bytes = max_file_bytes

    def create_course(
        self,
        session: Session,
        *,
        title: str,
        source_type: str,
        source_user: str,
        source_conversation: str,
        source_message_id: str,
        files: list[UploadFile],
        roles: list[CourseAssetRole],
        rights_statuses: list[RightsStatus],
    ) -> tuple[Course, list[CourseAsset], bool]:
        existing = session.exec(
            select(Course).where(Course.source_message_id == source_message_id)
        ).first()
        if existing is not None:
            return existing, self._assets(session, existing.id), False

        if not files:
            raise CourseIntakeError("course_assets_required")
        if len(files) != len(roles) or len(files) != len(rights_statuses):
            raise CourseIntakeError("course_asset_metadata_count_mismatch")

        course = Course(
            title=title.strip(),
            source_type=source_type.strip() or "dingtalk",
            source_user=source_user.strip(),
            source_conversation=source_conversation.strip(),
            source_message_id=source_message_id.strip(),
        )
        asset_dir = (self.course_root / course.id / "assets").resolve()
        root = self.course_root.resolve()
        if root not in asset_dir.parents:
            raise CourseIntakeError("course_storage_path_invalid")
        asset_dir.mkdir(parents=True, exist_ok=False)
        assets: list[CourseAsset] = []
        seen: set[tuple[str, str]] = set()

        try:
            for upload, role, rights_status in zip(files, roles, rights_statuses, strict=True):
                mime_type = (upload.content_type or "application/octet-stream").split(";", 1)[0].lower()
                if not course_mime_allowed(mime_type):
                    raise CourseIntakeError("unsupported_course_asset_type")

                original_name = _safe_filename(upload.filename)
                asset_id = str(uuid4())
                destination = (asset_dir / f"{asset_id}{_safe_extension(original_name)}").resolve()
                if asset_dir not in destination.parents:
                    raise CourseIntakeError("course_storage_path_invalid")

                digest = hashlib.sha256()
                size_bytes = 0
                with destination.open("xb") as output:
                    while chunk := upload.file.read(1024 * 1024):
                        size_bytes += len(chunk)
                        if size_bytes > self.max_file_bytes:
                            raise CourseIntakeError("course_asset_too_large")
                        digest.update(chunk)
                        output.write(chunk)
                if size_bytes == 0:
                    raise CourseIntakeError("empty_course_asset")

                sha256 = digest.hexdigest()
                duplicate_key = (role.value, sha256)
                if duplicate_key in seen:
                    destination.unlink(missing_ok=True)
                    continue
                seen.add(duplicate_key)
                assets.append(
                    CourseAsset(
                        id=asset_id,
                        course_id=course.id,
                        role=role,
                        original_name=original_name,
                        stored_path=str(destination),
                        mime_type=mime_type,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        rights_status=rights_status,
                        source_message_id=source_message_id,
                    )
                )

            session.add(course)
            session.add_all(assets)
            session.commit()
            session.refresh(course)
            return course, self._assets(session, course.id), True
        except Exception:
            session.rollback()
            course_dir = asset_dir.parent
            if course_dir.parent == root and course_dir.is_dir():
                shutil.rmtree(course_dir)
            raise

    @staticmethod
    def _assets(session: Session, course_id: str) -> list[CourseAsset]:
        return list(
            session.exec(
                select(CourseAsset)
                .where(CourseAsset.course_id == course_id)
                .order_by(CourseAsset.created_at, CourseAsset.id)
            ).all()
        )

    def get_course(self, session: Session, course_id: str) -> tuple[Course, list[CourseAsset]] | None:
        course = session.get(Course, course_id)
        if course is None:
            return None
        return course, self._assets(session, course.id)
