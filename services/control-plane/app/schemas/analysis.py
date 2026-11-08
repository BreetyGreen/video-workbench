from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator
from app.schemas.director import DirectorPlan


class PacingRule(BaseModel):
    from_second: float = Field(ge=0)
    to_second: float = Field(gt=0)
    instruction: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.to_second <= self.from_second:
            raise ValueError("to_second must be greater than from_second")
        return self


class QaThresholds(BaseModel):
    max_silence_seconds: float = Field(ge=0)
    max_black_seconds: float = Field(ge=0)


class EditRecipe(BaseModel):
    director_plan: DirectorPlan | None = None
    hook_rules: list[str] = Field(min_length=1)
    target_duration_seconds: int = Field(gt=0, le=600)
    pacing: list[PacingRule] = Field(min_length=1)
    track_layout: list[str] = Field(min_length=1)
    caption_style: str = Field(min_length=1)
    audio_rules: list[str]
    prohibited_elements: list[str]
    qa_thresholds: QaThresholds
    # Adapter-side notes about shape normalization (e.g. plan-only replies); never model claims.
    notes: list[str] = Field(default_factory=list)


class TrendEvidence(BaseModel):
    metric: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_type: Literal["public", "owner_authorized"]
    source: HttpUrl | str
    explanation: str = Field(min_length=1)


class PublishCopy(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=2000)
    topics: list[str] = Field(min_length=1, max_length=10)
    rationale: str = Field(min_length=1)


class ViralAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    patterns: list[str] = Field(min_length=1)
    evidence: list[TrendEvidence]
    recommendations: list[str] = Field(min_length=1)
    publish_copy: list[PublishCopy] = Field(min_length=3, max_length=3)
