from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prescription import Prescription, PrescriptionCompletion


def prescriptions(db: Session, patient_id: str, cursor: str | None, limit: int):
    query = select(Prescription).where(Prescription.patient_id == patient_id)
    if cursor:
        query = query.where(Prescription.id < cursor)
    return list(db.scalars(query.order_by(Prescription.id.desc()).limit(limit + 1)))


def scoped_prescription_id(db: Session, patient_id: str, prescription_id: str):
    return db.scalar(select(Prescription.id).where(
        Prescription.patient_id == patient_id, Prescription.id == prescription_id,
    ))


def completion_times(db: Session, patient_id: str, start: datetime, end: datetime):
    query = select(PrescriptionCompletion.completed_at).join(Prescription).where(
        Prescription.patient_id == patient_id,
        PrescriptionCompletion.completed_at >= start,
        PrescriptionCompletion.completed_at < end,
    )
    return db.scalars(query.execution_options(yield_per=512))
