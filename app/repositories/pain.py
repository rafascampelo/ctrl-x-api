from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.pain_entry import PainEntry


def owned_entry(db: Session, entry_id: str, patient_id: str):
    return db.scalar(select(PainEntry).where(
        PainEntry.id == entry_id, PainEntry.patient_id == patient_id,
    ).with_for_update())


def intensities(db: Session, patient_id: str, start: datetime, end: datetime):
    return db.execute(select(PainEntry.occurred_at, PainEntry.intensity).where(
        PainEntry.patient_id == patient_id,
        PainEntry.occurred_at >= start,
        PainEntry.occurred_at < end,
    ).order_by(PainEntry.occurred_at.desc(), PainEntry.id.desc()).execution_options(yield_per=512))


def entries(db: Session, patient_id: str, start: datetime | None, end: datetime | None,
            cursor: tuple[datetime, str] | None, limit: int):
    query = select(PainEntry).where(PainEntry.patient_id == patient_id)
    if start is not None:
        query = query.where(PainEntry.occurred_at >= start)
    if end is not None:
        query = query.where(PainEntry.occurred_at < end)
    if cursor is not None:
        timestamp, entry_id = cursor
        query = query.where(or_(
            PainEntry.occurred_at < timestamp,
            and_(PainEntry.occurred_at == timestamp, PainEntry.id < entry_id),
        ))
    return list(db.scalars(query.order_by(
        PainEntry.occurred_at.desc(), PainEntry.id.desc(),
    ).limit(limit + 1)))
