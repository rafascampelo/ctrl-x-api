from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ClinicalRecord(Base):
    __tablename__ = "clinical_records"
    __table_args__ = (
        CheckConstraint("pain_intensity BETWEEN 0 AND 10", name="ck_clinical_pain"),
        CheckConstraint(
            "(status = 'draft' AND finalized_at IS NULL) OR "
            "(status = 'finalized' AND finalized_at IS NOT NULL)",
            name="ck_clinical_status",
        ),
        Index("ix_clinical_patient_id", "patient_id", "id"),
        Index("ix_clinical_patient_finalized", "patient_id", "finalized_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    professional_id: Mapped[str] = mapped_column(ForeignKey("professionals.id"))
    status: Mapped[str] = mapped_column(String(10))
    chief_complaint: Mapped[str] = mapped_column(Text)
    anamnesis: Mapped[str] = mapped_column(Text)
    physical_assessment: Mapped[str] = mapped_column(Text)
    body_region: Mapped[str] = mapped_column(String(120))
    pain_intensity: Mapped[int | None]
    functional_limitations: Mapped[str] = mapped_column(Text)
    therapeutic_goals: Mapped[str] = mapped_column(Text)
    care_plan: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amendments: Mapped[list["ClinicalRecordAmendment"]] = relationship(
        order_by=lambda: (ClinicalRecordAmendment.created_at, ClinicalRecordAmendment.id),
        lazy="selectin",
    )


class ClinicalRecordAmendment(Base):
    __tablename__ = "clinical_record_amendments"
    __table_args__ = (Index("ix_clinical_amendment_record", "record_id", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    record_id: Mapped[str] = mapped_column(ForeignKey("clinical_records.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("professionals.id"))
    reason: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
