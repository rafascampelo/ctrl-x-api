from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.repositories.auth import utc

MAX_TEXT_CHARS = 20000
OcrStatus = Literal["completed", "failed", "unsupported"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class UploadFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    patient_id: UUID | None = None


class DocumentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extracted_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_CHARS),
    ]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    uploaded_by: UUID
    title: str
    file_name: str
    content_type: str
    size_bytes: int
    ocr_status: OcrStatus
    ocr_error: str | None
    extracted_text: str | None
    is_verified: bool
    verified_at: datetime | None
    created_at: datetime

    @field_validator("created_at", "verified_at")
    @classmethod
    def to_utc(cls, value: datetime | None):
        return utc(value) if value is not None else None


class DocumentPage(BaseModel):
    items: list[DocumentResponse]
    next_cursor: UUID | None
