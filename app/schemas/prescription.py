from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.repositories.auth import utc

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ClinicalNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Title
    sets: Annotated[int, Field(strict=True, ge=1, le=20)]
    reps: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    notes: ShortNote | None = None


class PrescriptionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    frequency: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    clinical_notes: ClinicalNotes | None = None


class PrescriptionCreate(PrescriptionFields):
    exercises: Annotated[list[ExerciseInput], Field(min_length=1, max_length=50)]


class ExerciseResponse(ExerciseInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class CompletionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: ClinicalNotes | None = None


class CompletionResponse(CompletionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    completed_at: datetime

    _utc = field_validator("completed_at")(utc)


class PrescriptionResponse(PrescriptionFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    professional_id: UUID
    professional_name: str
    status: Literal["active"] = "active"
    created_at: datetime
    exercises: list[ExerciseResponse]
    completions: list[CompletionResponse]

    _utc = field_validator("created_at")(utc)


class PrescriptionPage(BaseModel):
    items: list[PrescriptionResponse]
    next_cursor: UUID | None
