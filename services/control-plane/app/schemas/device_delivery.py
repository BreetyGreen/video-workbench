from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DevicePairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=100)
    name: str = Field(default="VideoWorkbench Device", min_length=1, max_length=100)


class DevicePairRead(BaseModel):
    device_id: str
    name: str
    token: str


class PairingCodeRead(BaseModel):
    id: str
    code: str
    expires_at: datetime
