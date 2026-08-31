from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderSettingsUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list)
