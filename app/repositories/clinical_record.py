from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.clinical_record import ClinicalRecord


def patient_id_for(db: Session, record_id: str):
    return db.scalar(select(ClinicalRecord.patient_id).where(ClinicalRecord.id == record_id))


def record(db: Session, record_id: str):
    return db.scalar(select(ClinicalRecord).where(ClinicalRecord.id == record_id).with_for_update())


def records(db: Session, patient_id: str, author_id: str | None, cursor: str | None, limit: int):
    visible = ClinicalRecord.status == "finalized"
    if author_id is not None:
        visible = or_(visible, ClinicalRecord.professional_id == author_id)
    query = select(ClinicalRecord).where(ClinicalRecord.patient_id == patient_id, visible)
    if cursor:
        query = query.where(ClinicalRecord.id < cursor)
    return list(db.scalars(query.order_by(ClinicalRecord.id.desc()).limit(limit + 1)))
