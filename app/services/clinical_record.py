from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.clinical_record import ClinicalRecord, ClinicalRecordAmendment
from app.models.user import Role, User
from app.repositories import care, clinical_record
from app.schemas.clinical_record import (
    AmendmentCreate,
    AmendmentResponse,
    RecordCreate,
    RecordResponse,
    RecordUpdate,
)
from app.services.care import authorize_patient, own_profile


def now():
    return datetime.now(UTC).replace(microsecond=0)


def create(db: Session, user: User, data: RecordCreate):
    patient_id = str(data.patient_id)
    authorize_patient(db, user, patient_id)
    timestamp = now()
    record = ClinicalRecord(
        patient_id=patient_id, professional_id=own_profile(db, user).id,
        status="draft", created_at=timestamp, updated_at=timestamp,
        **data.model_dump(exclude={"patient_id"}),
    )
    db.add(record)
    db.flush()
    return save_record(db, user, record, "created")


def list_records(db: Session, user: User, patient_id: str | None, cursor: str | None, limit: int):
    identity = own_profile(db, user)
    if patient_id is None:
        if user.role == Role.PROFESSIONAL:
            raise HTTPException(422, "Patient ID is required")
        patient_id = identity.id
    authorize_patient(db, user, patient_id)
    author = identity.id if user.role == Role.PROFESSIONAL else None
    rows = clinical_record.records(db, patient_id, author, cursor, limit)
    items = [RecordResponse.model_validate(row) for row in rows[:limit]]
    care.audit(db, user, "clinical_records_viewed", patient_id, patient_id)
    db.commit()
    return {"items": items, "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def authorized_record(db: Session, user: User, record_id: str, *, author_only: bool = False):
    patient_id = clinical_record.patient_id_for(db, record_id)
    if patient_id is None:
        raise HTTPException(404, "Clinical record not found")
    authorize_patient(db, user, patient_id)
    record = clinical_record.record(db, record_id)
    if (author_only or record.status == "draft") and (
        user.role != Role.PROFESSIONAL or own_profile(db, user).id != record.professional_id
    ):
        raise HTTPException(404, "Clinical record not found")
    return record


def save_record(db: Session, user: User, record: ClinicalRecord, action: str):
    result = RecordResponse.model_validate(record)
    care.audit(db, user, f"clinical_record_{action}", record.id, record.patient_id)
    db.commit()
    return result


def read(db: Session, user: User, record_id: str):
    return save_record(db, user, authorized_record(db, user, record_id), "viewed")


def edit(db: Session, user: User, record_id: str, data: RecordUpdate | None):
    record = authorized_record(db, user, record_id, author_only=True)
    if record.status != "draft":
        raise HTTPException(409, "Clinical record is finalized")
    timestamp = now()
    if data is None:
        record.status = "finalized"
        record.finalized_at = timestamp
        action = "finalized"
    else:
        for name, value in data.model_dump().items():
            setattr(record, name, value)
        action = "updated"
    record.updated_at = timestamp
    return save_record(db, user, record, action)


def append_amendment(db: Session, user: User, record_id: str, data: AmendmentCreate):
    record = authorized_record(db, user, record_id)
    if record.status != "finalized":
        raise HTTPException(409, "Clinical record must be finalized")
    amendment = ClinicalRecordAmendment(
        record_id=record.id, author_id=own_profile(db, user).id, created_at=now(),
        **data.model_dump(),
    )
    db.add(amendment)
    db.flush()
    result = AmendmentResponse.model_validate(amendment)
    care.audit(db, user, "clinical_record_amended", record.id, record.patient_id)
    db.commit()
    return result
