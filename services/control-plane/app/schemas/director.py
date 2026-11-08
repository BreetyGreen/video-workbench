from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DirectorBeat(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    purpose: Literal['hook', 'identity', 'feature', 'evidence', 'usage', 'closing']
    narration: str = Field(min_length=1, max_length=160)
    material_id: str = Field(min_length=1, max_length=100)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def valid_range(self):
        if self.source_end_seconds - self.source_start_seconds < .3:
            raise ValueError('director_interval_too_short')
        return self


class DirectorPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    beats: list[DirectorBeat] = Field(min_length=2, max_length=40)

    @model_validator(mode='after')
    def bookends(self):
        if self.beats[0].purpose != 'hook' or self.beats[-1].purpose != 'closing':
            raise ValueError('director_bookends_required')
        return self

    @property
    def narration(self) -> str:
        return ''.join(beat.narration if beat.narration[-1] in '。！？.!?' else beat.narration + '。'
                       for beat in self.beats)
