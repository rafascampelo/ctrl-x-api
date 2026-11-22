from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PainEntry(Base):
    __tablename__ = "pain_entries"
    __table_args__ = (
        CheckConstraint("intensity BETWEEN 0 AND 10", name="ck_pain_intensity"),
        Index("ix_pain_entries_patient_time_id", "patient_id", "occurred_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    region: Mapped[str] = mapped_column(String(100))
    intensity: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(2000))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC).replace(microsecond=0),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC).replace(microsecond=0),
        onupdate=lambda: datetime.now(UTC).replace(microsecond=0),
    )
