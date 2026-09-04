from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TutorialDemoRunRead(BaseModel):
    id: str
    state: str
    stage: str
    course_id: str | None
    recipe_id: str | None
    job_id: str | None
    task_id: str | None
    error_code: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
