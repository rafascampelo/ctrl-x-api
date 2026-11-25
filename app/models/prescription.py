from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import Professional


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = (Index("ix_prescriptions_patient_id", "patient_id", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    professional_id: Mapped[str] = mapped_column(ForeignKey("professionals.id"))
    title: Mapped[str] = mapped_column(String(150))
    frequency: Mapped[str] = mapped_column(String(120))
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    professional: Mapped[Professional] = relationship(lazy="selectin")
    exercises: Mapped[list["PrescribedExercise"]] = relationship(
        order_by=lambda: PrescribedExercise.position, lazy="selectin",
    )
    completions: Mapped[list["PrescriptionCompletion"]] = relationship(
        order_by=lambda: (PrescriptionCompletion.completed_at.desc(), PrescriptionCompletion.id.desc()),
        lazy="selectin",
    )

    @property
    def professional_name(self):
        return self.professional.full_name


class PrescribedExercise(Base):
    __tablename__ = "prescribed_exercises"
    __table_args__ = (
        CheckConstraint("sets BETWEEN 1 AND 20", name="ck_exercise_sets"),
        UniqueConstraint("prescription_id", "position", name="uq_prescribed_exercise_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prescription_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"))
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(150))
    sets: Mapped[int]
    reps: Mapped[str] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)


class PrescriptionCompletion(Base):
    __tablename__ = "prescription_completions"
    __table_args__ = (Index("ix_completion_prescription_time", "prescription_id", "completed_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prescription_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
