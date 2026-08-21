from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TranscriptWord(BaseModel):
    text: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    probability: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("word end must be after start")
        return self


class TranscriptSegment(BaseModel):
    text: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    confidence: float = Field(default=0, ge=0, le=1)
    words: list[TranscriptWord] = Field(default_factory=list)


class TranscriptResult(BaseModel):
    language: str = ""
    language_probability: float = Field(default=0, ge=0, le=1)
    duration_seconds: float = Field(default=0, ge=0)
    provider: str = ""
    model: str = ""
    quality_profile: str = ""
    fallback_reason: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(item.text.strip() for item in self.segments if item.text.strip())


class SilenceInterval(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class SceneInterval(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    score: float = Field(default=0, ge=0)


class FrameEvidence(BaseModel):
    timestamp_seconds: float = Field(ge=0)
    image_path: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    brightness: float = Field(ge=0, le=255)
    contrast: float = Field(ge=0)
    sharpness: float = Field(ge=0)
    ocr_texts: list[str] = Field(default_factory=list)


class MediaAnalysis(BaseModel):
    material_id: str
    source_path: str
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    has_audio: bool
    transcript: TranscriptResult = Field(default_factory=TranscriptResult)
    scenes: list[SceneInterval] = Field(default_factory=list)
    silences: list[SilenceInterval] = Field(default_factory=list)
    frames: list[FrameEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferencePacingProfile(BaseModel):
    average_scene_seconds: float = Field(gt=0)
    cuts_per_minute: float = Field(ge=0)
    preferred_clip_seconds: float = Field(ge=0.6, le=8)
    hook_window_seconds: float = Field(ge=0.5, le=8)
    pace: Literal["rapid", "balanced", "steady"]


class ReferenceShotGroup(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    subject: str = Field(min_length=1)
    subject_motion: str = Field(min_length=1)
    scene: str = Field(min_length=1)
    spatial_framing: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("reference shot end must be after start")
        return self


class ReferenceVideoBrief(BaseModel):
    source_name: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    provider: str = "local_structural"
    content_summary: str = Field(min_length=1)
    style_summary: str = Field(min_length=1)
    structure_summary: str = Field(min_length=1)
    pacing: ReferencePacingProfile
    shot_groups: list[ReferenceShotGroup] = Field(default_factory=list)
    keep_patterns: list[str] = Field(min_length=1)
    change_requirements: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class TimelineClip(BaseModel):
    material_id: str
    source_path: str
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    timeline_start_seconds: float = Field(ge=0)
    timeline_end_seconds: float = Field(gt=0)
    score: float = Field(ge=0)
    reason: str
    has_audio: bool

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("source duration must be positive")
        if self.timeline_end_seconds <= self.timeline_start_seconds:
            raise ValueError("timeline duration must be positive")
        source_duration = self.source_end_seconds - self.source_start_seconds
        timeline_duration = self.timeline_end_seconds - self.timeline_start_seconds
        if abs(source_duration - timeline_duration) > 0.02:
            raise ValueError("source and timeline durations must match")
        return self

    @property
    def duration_seconds(self) -> float:
        return self.timeline_end_seconds - self.timeline_start_seconds


class CaptionCue(BaseModel):
    material_id: str
    text: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    emphasis_terms: list[str] = Field(default_factory=list)
    placement: Literal["bottom", "top", "middle"] = "bottom"


class AudioMixPlan(BaseModel):
    mode: Literal["original", "mixed", "narration"] = "original"
    original_gain_db: float = 0
    voiceover_path: str | None = None
    voiceover_gain_db: float = 0
    voice_type: str | None = None
    voiceover_duration_seconds: float = Field(default=0, ge=0)
    decision_reason: str = ""
    bgm_path: str | None = None
    bgm_gain_db: float = -18
    target_lufs: float = -14
    true_peak_db: float = -1.5


class CoverPlan(BaseModel):
    material_id: str
    source_path: str
    source_timestamp_seconds: float = Field(ge=0)
    title: str


class EditingTimeline(BaseModel):
    title: str
    width: int = 1080
    height: int = 1920
    fps: int = 30
    target_duration_seconds: float = Field(gt=0)
    actual_duration_seconds: float = Field(gt=0)
    engine: str = "local_intelligent"
    clips: list[TimelineClip] = Field(min_length=1)
    captions: list[CaptionCue] = Field(default_factory=list)
    audio: AudioMixPlan = Field(default_factory=AudioMixPlan)
    cover: CoverPlan | None = None
    removed_silence_seconds: float = Field(default=0, ge=0)
    source_count: int = Field(default=1, ge=1)
    warnings: list[str] = Field(default_factory=list)
