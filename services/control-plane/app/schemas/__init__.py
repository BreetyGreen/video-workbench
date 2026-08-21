from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models import DeliveryState, TaskStatus
from app.schemas.analysis import EditRecipe, PublishCopy, ViralAnalysis


class MaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    stored_path: str
    mime_type: str
    size_bytes: int
    sha256: str


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content_type: str
    rights_confirmed: bool
    requirements_text: str
    tutorial_text: str
    quality_profile: str
    cloud_processing_allowed: bool
    reference_name: str | None
    reference_path: str | None
    reference_sha256: str | None
    voice_preset: str
    voice_type: str
    status: TaskStatus
    source_type: str | None
    source_user: str | None
    source_conversation: str | None
    source_message_id: str | None
    deduplication_key: str | None
    archived_at: datetime | None
    archive_reason: str | None
    delivery_state: DeliveryState | None
    delivery_provider_id: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    materials: list[MaterialRead]


class TaskArchiveRequest(BaseModel):
    reason: str = Field(default="manual", min_length=1, max_length=200)


class DouyinDeliveryRequest(BaseModel):
    visibility: str = Field(default="self", pattern="^(self|public|friends)$")
    title: str = Field(min_length=1, max_length=1000)


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class ReviewRequest(BaseModel):
    decision: ReviewDecision
    comment: str = Field(default="", max_length=2000)


class HealthRead(BaseModel):
    status: str
    database: str
    artifact_storage: str


class ReviewEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    decision: str
    comment: str
    created_at: datetime


__all__ = [
    "EditRecipe",
    "HealthRead",
    "MaterialRead",
    "PublishCopy",
    "ReviewDecision",
    "ReviewEventRead",
    "ReviewRequest",
    "TaskRead",
    "TaskArchiveRequest",
    "DouyinDeliveryRequest",
    "ViralAnalysis",
]
