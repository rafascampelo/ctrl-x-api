from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.core.security import current_user, require_role
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ErrorResponse
from app.schemas.pain import PainCreate, PainPage, PainResponse, PainUpdate
from app.services import pain as service

router = APIRouter(tags=["pain diary"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422)
})
Database = Annotated[Session, Depends(get_db)]
Authenticated = Annotated[User, Depends(current_user)]
PatientUser = Annotated[User, Depends(require_role(Role.PATIENT))]


@router.post("/me/pain-entries", response_model=PainResponse, status_code=201)
def create(data: PainCreate, response: Response, user: PatientUser, db: Database):
    response.headers["Cache-Control"] = "no-store"
    return service.create_entry(db, user, data)


@router.patch("/pain-entries/{entry_id}", response_model=PainResponse)
def update(entry_id: UUID, data: PainUpdate, response: Response, user: PatientUser, db: Database):
    response.headers["Cache-Control"] = "no-store"
    return service.change_entry(db, user, str(entry_id), data)


@router.delete("/pain-entries/{entry_id}", status_code=204)
def delete(entry_id: UUID, user: PatientUser, db: Database):
    service.change_entry(db, user, str(entry_id), None)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/patients/{patient_id}/pain-entries", response_model=PainPage)
def entries(patient_id: UUID, response: Response, user: Authenticated, db: Database,
            start: AwareDatetime | None = None, end: AwareDatetime | None = None,
            cursor: Annotated[str | None, Query(max_length=100)] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 20):
    response.headers["Cache-Control"] = "no-store"
    return service.list_entries(db, user, str(patient_id), start, end, cursor, limit)
