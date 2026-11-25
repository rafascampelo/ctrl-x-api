from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel


class HistoryCategory(StrEnum):
    PAIN = "pain"
    EXERCISE = "exercise"
    CLINICAL_RECORD = "clinical_record"


class HistoryEvent(BaseModel):
    id: UUID
    category: HistoryCategory
    title: str
    summary: str | None = None
    occurred_at: AwareDatetime
    intensity: int | None = None
    region: str | None = None


class HistoryPage(BaseModel):
    items: list[HistoryEvent]
    next_cursor: str | None


class CalendarDay(BaseModel):
    date: date
    pain_count: int
    clinical_record_count: int = 0


class PainMetrics(BaseModel):
    count: int
    average_intensity: float | None
    latest_intensity: int | None


class CalendarMonth(BaseModel):
    month: str
    timezone: str
    days: list[CalendarDay]
    pain: PainMetrics
