from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel

from app.models import CourseAssetRole, RightsStatus


class CourseAssetRead(SQLModel):
    id: str
    course_id: str
    role: CourseAssetRole
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    rights_status: RightsStatus
    source_message_id: str
    created_at: datetime


class CourseRead(SQLModel):
    id: str
    title: str
    source_type: str
    source_user: str
    source_conversation: str
    source_message_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    assets: list[CourseAssetRead] = []
