from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CrefitoResult(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"
    NEEDS_REVIEW = "needs_review"


class CrefitoReview(Base):
    __tablename__ = "crefito_reviews"
    __table_args__ = (Index("ix_crefito_reviews_professional_current", "professional_id", "current"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    professional_id: Mapped[str] = mapped_column(ForeignKey("professionals.id"))
    current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    result: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(20))
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
