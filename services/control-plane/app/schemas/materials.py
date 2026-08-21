from pydantic import BaseModel, Field, field_validator


class MaterialAcquisitionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    count: int = Field(default=3, ge=1, le=12)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return value.strip()
