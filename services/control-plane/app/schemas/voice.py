from pydantic import BaseModel, Field


class VoicePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)
