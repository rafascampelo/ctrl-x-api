from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ErrorResponse
from app.schemas.history import CalendarMonth, HistoryCategory, HistoryPage
from app.services import history as service

router = APIRouter(tags=["patient history"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422)
})
Database = Annotated[Session, Depends(get_db)]
PatientUser = Annotated[User, Depends(require_role(Role.PATIENT))]
Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]
Day = Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Timezone = Annotated[str, Query(min_length=1, max_length=100)]


@router.get("/me/timeline", response_model=HistoryPage)
def timeline(response: Response, user: PatientUser, db: Database,
             timezone: Timezone = "UTC", month: Month | None = None, date: Day | None = None,
             category: HistoryCategory | None = None,
             cursor: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
             limit: Annotated[int, Query(ge=1, le=100)] = 25):
    response.headers["Cache-Control"] = "no-store"
    return service.timeline(db, user, timezone, month, date, category, cursor, limit)


@router.get("/me/calendar", response_model=CalendarMonth, response_model_exclude_defaults=True)
def calendar(response: Response, user: PatientUser, db: Database,
             month: Month, timezone: Timezone = "UTC"):
    response.headers["Cache-Control"] = "no-store"
    return service.calendar(db, user, timezone, month)
