from __future__ import annotations

from pydantic import BaseModel, Field


class CloudUsageSettingsUpdate(BaseModel):
    access_key_id: str = Field(min_length=6, max_length=256)
    secret_access_key: str = Field(min_length=6, max_length=512)
    asr_total_seconds: float = Field(default=0, ge=0)
    tts_total_characters: float = Field(default=0, ge=0)
    ark_monthly_tokens: float = Field(default=0, ge=0)
    warning_threshold_percent: float = Field(default=20, ge=0, le=100)
    critical_threshold_percent: float = Field(default=10, ge=0, le=100)
