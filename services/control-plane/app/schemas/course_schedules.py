from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class CourseScheduleCreate(BaseModel):
    course_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    material_ids: list[str] = Field(min_length=1, max_length=200)
    device_id: str | None = Field(default=None, max_length=100)
    requirements_text: str = Field(default="", max_length=5000)
    content_type: str = Field(default="教程讲解", min_length=1, max_length=100)
    commercial: bool = False
    cloud_processing_allowed: bool = False
    daily_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Shanghai", max_length=100)
    enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("invalid_timezone") from error
        return value


class CourseScheduleToggle(BaseModel):
    enabled: bool
