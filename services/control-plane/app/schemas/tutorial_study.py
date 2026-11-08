"""Structured notes a vision model returns for one chunk of a tutorial video."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

STUDY_RULE_CATEGORIES = {"hook", "pacing", "structure", "captions", "audio", "cta", "negative", "closeup", "comparison"}
STUDY_SEGMENT_TYPES = ("lecture", "software_operation", "finished_example", "intro_outro", "other")


class StudyRule(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    category: str = "structure"
    instruction: str = Field(min_length=1, max_length=600)
    evidence_quote: str = Field(default="", max_length=1000)
    start: float = Field(ge=-5)
    end: float = Field(ge=-5)

    @field_validator("category", mode="before")
    @classmethod
    def known_category(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in STUDY_RULE_CATEGORIES else "structure"


class StudySegment(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    start: float = Field(ge=-5)
    end: float = Field(ge=-5)
    type: Literal["lecture", "software_operation", "finished_example", "intro_outro", "other"] = "other"
    summary: str = Field(min_length=1, max_length=1000)
    teacher_actions: list[str] = Field(default_factory=list, max_length=40)
    rules: list[StudyRule] = Field(default_factory=list, max_length=40)

    @field_validator("type", mode="before")
    @classmethod
    def known_type(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in STUDY_SEGMENT_TYPES else "other"

    @field_validator("teacher_actions", mode="before")
    @classmethod
    def bounded_actions(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:300] for item in value if str(item).strip()][:40]


class StudyChunkReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    segments: list[StudySegment] = Field(default_factory=list, max_length=200)
    uncertain: list[str] = Field(default_factory=list, max_length=60)

    @field_validator("uncertain", mode="before")
    @classmethod
    def bounded_uncertain(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:500] for item in value if str(item).strip()][:60]


class LessonStudyRule(BaseModel):
    category: str
    instruction: str
    evidence_quote: str = ""
    start_ms: int
    end_ms: int
    chunk_index: int


class LessonStudySegment(BaseModel):
    start_ms: int
    end_ms: int
    type: str
    summary: str
    teacher_actions: list[str] = Field(default_factory=list)
    chunk_index: int


class LessonStudy(BaseModel):
    version: int = 1
    source_name: str
    source_sha256: str = ""
    duration_seconds: float
    model: str
    fps: float
    chunk_seconds: int
    chunk_count: int
    completed_chunks: int
    failed_chunks: list[dict] = Field(default_factory=list)
    segments: list[LessonStudySegment] = Field(default_factory=list)
    rules: list[LessonStudyRule] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    coverage: str = "sampled_frames_per_chunk_not_every_frame"

    @property
    def complete(self) -> bool:
        return self.chunk_count > 0 and self.completed_chunks == self.chunk_count
