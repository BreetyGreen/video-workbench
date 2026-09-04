from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field


class EditingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    instruction: str
    evidence_text: str
    confidence: float
    source_asset_id: str
    source_start_ms: int | None
    source_end_ms: int | None
    source_page: int | None
    sort_order: int


class TutorialSegmentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    source_asset_id: str = Field(min_length=1, max_length=100)
    segment_type: Literal["lecture", "software_operation", "finished_example", "intro_outro", "unknown"]
    start_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    end_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    source_page: int | None = Field(default=None, ge=0, le=10_000_000)
    transcript_text: str = Field(default="", max_length=20_000)
    ocr_texts: list[str] = Field(default_factory=list, max_length=200)
    visual_cues: list[str] = Field(default_factory=list, max_length=200)
    related_rule_ids: list[str] = Field(default_factory=list, max_length=200)
    confidence: float = Field(ge=0, le=1)
    sort_order: int = Field(ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TutorialSegmentRead":
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("tutorial segment end_ms must be greater than start_ms")
        for values in (self.ocr_texts, self.visual_cues, self.related_rule_ids):
            if any(not isinstance(item, str) or len(item) > 2_000 for item in values):
                raise ValueError("tutorial segment list values must be bounded strings")
        return self


class TutorialSegmentArtifactRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=100)
    segments: list[TutorialSegmentRead] = Field(min_length=1, max_length=1_000)


class EditingRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    version: int
    title: str
    summary: str
    tutorial_asset_id: str | None
    transcript_sha256: str
    created_at: datetime
    rules: list[EditingRuleRead]
    segments: list[TutorialSegmentRead] = Field(default_factory=list)
    shot_count: int = 0


class ShotSearchResultRead(BaseModel):
    shot_id: str
    asset_id: str
    original_name: str
    start_ms: int
    end_ms: int
    thumbnail_path: str
    rights_status: str
    text_score: float
    semantic_score: float
    duplicate_score: float
    combined_score: float


class CourseEditJobCreate(BaseModel):
    course_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content_type: str = Field(default="商品介绍", min_length=1, max_length=100)
    commercial: bool = True
    quality_profile: str = Field(default="production", pattern="^(fast_preview|production|local_privacy)$")
    cloud_processing_allowed: bool = False


class CourseEditJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    recipe_id: str
    task_id: str | None
    device_id: str | None
    state: str
    commercial: bool
    quality_status: str
    review_skipped: bool
    handoff_status: str
    error_code: str
    created_at: datetime
    updated_at: datetime


class CourseEditJobHandoffUpdate(BaseModel):
    status: str = Field(pattern="^(imported|failed)$")
    error_code: str = Field(default="", max_length=200)
