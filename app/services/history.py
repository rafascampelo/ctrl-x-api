from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories import care, pain
from app.repositories.auth import utc
from app.schemas.history import HistoryCategory, HistoryEvent
from app.services.pain import list_own_entries, patient_owner


def local_period(timezone: str, month: str | None, day: str | None):
    if month is not None and day is not None:
        raise HTTPException(422, "Choose a month or a date")
    try:
        zone = ZoneInfo(timezone)
        if day is not None:
            start = date.fromisoformat(day)
            end = start + timedelta(days=1)
        elif month is not None:
            start = date.fromisoformat(f"{month}-01")
            end = (start + timedelta(days=31)).replace(day=1)
        else:
            return zone, None, None
        return (
            zone,
            datetime.combine(start, time.min, zone).astimezone(UTC),
            datetime.combine(end, time.min, zone).astimezone(UTC),
        )
    except (ValueError, OverflowError, ZoneInfoNotFoundError) as error:
        raise HTTPException(422, "Invalid date or timezone") from error


def timeline(db: Session, user: User, timezone: str, month: str | None, day: str | None,
             category: HistoryCategory | None, cursor: str | None, limit: int):
    _, start, end = local_period(timezone, month, day)
    # Additional categories can supply their own projected events when their sources exist.
    if category not in (None, HistoryCategory.PAIN) or (start is not None and start == end):
        patient = patient_owner(db, user)
        care.audit(db, user, "history_viewed", patient.id, patient.id)
        db.commit()
        return {"items": [], "next_cursor": None}
    page = list_own_entries(db, user, start, end, cursor, limit)
    return {
        "items": [
            HistoryEvent(id=entry.id, category=HistoryCategory.PAIN, title="Registro de dor",
                         summary=entry.description, occurred_at=utc(entry.occurred_at),
                         intensity=entry.intensity, region=entry.region)
            for entry in page["items"]
        ],
        "next_cursor": page["next_cursor"],
    }


def calendar(db: Session, user: User, timezone: str, month: str):
    patient = patient_owner(db, user)
    zone, start, end = local_period(timezone, month, None)
    days = Counter[date]()
    total_intensity = 0
    latest_intensity = None
    for occurred_at, intensity in pain.intensities(db, patient.id, start, end):
        days[utc(occurred_at).astimezone(zone).date()] += 1
        total_intensity += intensity
        if latest_intensity is None:
            latest_intensity = intensity
    count = sum(days.values())
    care.audit(db, user, "calendar_viewed", patient.id, patient.id)
    db.commit()
    return {
        "month": month,
        "timezone": timezone,
        "days": [{"date": day, "pain_count": days[day]} for day in sorted(days)],
        "pain": {
            "count": count,
            "average_intensity": round(total_intensity / count, 1) if count else None,
            "latest_intensity": latest_intensity,
        },
    }
