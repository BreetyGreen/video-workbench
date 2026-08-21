from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DailyScheduleUpdate(BaseModel):
    enabled: bool
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str
    keywords: list[str] = Field(min_length=1, max_length=20)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA timezone") from error
        return value

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in values if item.strip()))
        if not normalized:
            raise ValueError("At least one non-empty keyword is required")
        return normalized


class DailyScheduleRead(DailyScheduleUpdate):
    last_run_at: datetime | None = None


class TrendImportRecord(BaseModel):
    source: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    digg_count: int = Field(default=0, ge=0)
    author: str = ""
    cover_url: str = ""
    high_quality_text: str = ""
    captured_at: datetime
    published_at: datetime | None = None
    evidence: str = Field(min_length=1)


class TrendImportRequest(BaseModel):
    records: list[TrendImportRecord] = Field(min_length=1, max_length=500)


class TrendDiscoveryRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    count: int = Field(default=10, ge=1, le=20)
    publish_days: int = Field(default=7, ge=1, le=30)

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return value.strip()


class XiaohongshuEvidenceImport(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    author: str = Field(default="", max_length=200)
    engagement_count: int = Field(default=0, ge=0)
    evidence_note: str = Field(min_length=1, max_length=1000)

    @field_validator("keyword", "title", "author", "evidence_note")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("url")
    @classmethod
    def validate_public_xiaohongshu_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        hostname = (parsed.hostname or "").lower()
        valid = hostname == "xiaohongshu.com" or hostname.endswith(".xiaohongshu.com") or hostname == "xhslink.com" or hostname.endswith(".xhslink.com")
        if parsed.scheme != "https" or not valid:
            raise ValueError("A public Xiaohongshu or xhslink HTTPS URL is required")
        return normalized


class TrendRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    source_type: str
    keyword: str
    item_id: str
    title: str
    url: str
    digg_count: int
    author: str
    cover_url: str
    high_quality_text: str
    evidence: str
    published_at: datetime | None
    captured_at: datetime


class AutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    trigger: str
    trend_status: str
    trend_records: int
    processed_tasks: int
    failed_tasks: int
    material_status: str = "not_recorded"
    sourced_assets: int = 0
    created_task_ids: list[str] = Field(default_factory=list)
    warning: str
    started_at: datetime
    finished_at: datetime | None
