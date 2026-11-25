from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories import care, history, pain
from app.repositories.auth import utc
from app.schemas.history import HistoryCategory, HistoryEvent
from app.services.pain import cursor_position, patient_owner


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
    patient = patient_owner(db, user)
    rows = history.events(db, patient.id, category, start, end, cursor_position(cursor), limit)
    items = [HistoryEvent(**{**row, "occurred_at": utc(row["occurred_at"])}) for row in rows[:limit]]
    next_cursor = f"{items[-1].occurred_at.isoformat()}|{items[-1].id}" if len(rows) > limit else None
    care.audit(db, user, "history_viewed", patient.id, patient.id)
    db.commit()
    return {"items": items, "next_cursor": next_cursor}


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
    clinical_days = Counter(
        utc(timestamp).astimezone(zone).date()
        for timestamp in history.finalized_times(db, patient.id, start, end)
    )
    care.audit(db, user, "calendar_viewed", patient.id, patient.id)
    db.commit()
    return {
        "month": month,
        "timezone": timezone,
        "days": [
            {"date": day, "pain_count": days[day], "clinical_record_count": clinical_days[day]}
            for day in sorted(days.keys() | clinical_days.keys())
        ],
        "pain": {
            "count": count,
            "average_intensity": round(total_intensity / count, 1) if count else None,
            "latest_intensity": latest_intensity,
        },
    }
