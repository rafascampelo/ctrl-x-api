from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.repositories.auth import utc

Region = Annotated[str, Field(min_length=1, max_length=100)]
Intensity = Annotated[int, Field(strict=True, ge=0, le=10)]
Description = Annotated[str, Field(max_length=2000)]


class PainCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    region: Region
    intensity: Intensity
    description: Description | None = None
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("occurred_at")
    @classmethod
    def normalize_time(cls, value: datetime):
        if value is None:
            raise ValueError("Timestamp may not be null")
        # Match MySQL DATETIME second precision before both persistence and pagination.
        return value.astimezone(UTC).replace(microsecond=0)


class PainUpdate(PainCreate):
    region: Region | None = None
    intensity: Intensity | None = None
    occurred_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for name in self.model_fields_set - {"description"}:
            if getattr(self, name) is None:
                raise ValueError("Only description may be null")
        return self


class PainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    patient_id: UUID
    region: str
    intensity: int
    description: str | None
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime

    @field_serializer("occurred_at", "created_at", "updated_at")
    def serialize_time(self, value: datetime):
        return utc(value)


class PainPage(BaseModel):
    items: list[PainResponse]
    next_cursor: str | None
