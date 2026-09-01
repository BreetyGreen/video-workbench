from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic import Field


class EditingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    instruction: str
    source_asset_id: str
    source_start_ms: int | None
    source_end_ms: int | None
    source_page: int | None
    sort_order: int


class EditingRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    version: int
    title: str
    summary: str
    created_at: datetime
    rules: list[EditingRuleRead]
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
