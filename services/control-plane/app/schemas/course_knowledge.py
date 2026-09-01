from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
