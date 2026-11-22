from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.pain_entry import PainEntry
from app.models.user import Role, User
from app.repositories import care, pain
from app.repositories.auth import utc
from app.schemas.pain import PainCreate, PainResponse, PainUpdate
from app.services.care import authorize_patient, own_profile


def patient_owner(db: Session, user: User):
    if user.role != Role.PATIENT:
        raise HTTPException(403, "Forbidden")
    return own_profile(db, user)


def create_entry(db: Session, user: User, data: PainCreate):
    patient = patient_owner(db, user)
    entry = PainEntry(patient_id=patient.id, **data.model_dump())
    db.add(entry)
    db.flush()
    care.audit(db, user, "pain_entry_created", entry.id, patient.id)
    result = PainResponse.model_validate(entry)
    db.commit()
    return result


def change_entry(db: Session, user: User, entry_id: str, data: PainUpdate | None):
    patient = patient_owner(db, user)
    entry = pain.owned_entry(db, entry_id, patient.id)
    if entry is None:
        raise HTTPException(404, "Pain entry not found")
    if data is None:
        db.delete(entry)
        action = "pain_entry_deleted"
        result = None
    else:
        for name, value in data.model_dump(exclude_unset=True).items():
            setattr(entry, name, value)
        db.flush()
        action = "pain_entry_updated"
        result = PainResponse.model_validate(entry)
    care.audit(db, user, action, entry.id, patient.id)
    db.commit()
    return result


def list_entries(db: Session, user: User, patient_id: str, start: datetime | None,
                 end: datetime | None, cursor: str | None, limit: int):
    authorize_patient(db, user, patient_id)
    start = utc(start) if start is not None else None
    end = utc(end) if end is not None else None
    if start is not None and end is not None and start >= end:
        raise HTTPException(422, "Invalid date range")
    position = None
    if cursor:
        try:
            timestamp, entry_id = cursor.split("|", 1)
            timestamp = datetime.fromisoformat(timestamp)
            if timestamp.tzinfo is None:
                raise ValueError
            position = (utc(timestamp), str(UUID(entry_id)))
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid cursor") from None
    rows = pain.entries(db, patient_id, start, end, position, limit)
    items = [PainResponse.model_validate(entry) for entry in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = f"{utc(last.occurred_at).isoformat()}|{last.id}"
    care.audit(db, user, "pain_entries_viewed", patient_id, patient_id)
    db.commit()
    return {"items": items, "next_cursor": next_cursor}
