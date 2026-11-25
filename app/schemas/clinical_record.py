from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import MISSING, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.repositories.auth import utc

Complaint = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Assessment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Region = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Intensity = Annotated[int, Field(strict=True, ge=0, le=10)]
Details = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Plan = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chief_complaint: Complaint
    anamnesis: Assessment
    physical_assessment: Assessment
    body_region: Region
    pain_intensity: Intensity | None = None
    functional_limitations: Details
    therapeutic_goals: Details
    care_plan: Plan
    notes: Notes | None = None


class RecordCreate(RecordInput):
    patient_id: UUID


class RecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chief_complaint: Complaint | MISSING = MISSING
    anamnesis: Assessment | MISSING = MISSING
    physical_assessment: Assessment | MISSING = MISSING
    body_region: Region | MISSING = MISSING
    pain_intensity: Intensity | None | MISSING = MISSING
    functional_limitations: Details | MISSING = MISSING
    therapeutic_goals: Details | MISSING = MISSING
    care_plan: Plan | MISSING = MISSING
    notes: Notes | None | MISSING = MISSING


class AmendmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    content: Plan


class AmendmentResponse(AmendmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    author_id: UUID
    created_at: datetime

    _utc = field_validator("created_at", mode="after")(utc)


class RecordResponse(RecordInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    professional_id: UUID
    status: Literal["draft", "finalized"]
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None
    amendments: list[AmendmentResponse]

    @field_validator("created_at", "updated_at", "finalized_at")
    @classmethod
    def to_utc(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None


class RecordPage(BaseModel):
    items: list[RecordResponse]
    next_cursor: UUID | None
