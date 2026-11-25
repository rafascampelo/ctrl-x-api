from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.security import current_user, require_role
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ErrorResponse
from app.schemas.clinical_record import (
    AmendmentCreate,
    AmendmentResponse,
    RecordCreate,
    RecordPage,
    RecordResponse,
    RecordUpdate,
)
from app.services import clinical_record as service

router = APIRouter(
    prefix="/clinical-records", tags=["clinical records"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)},
)
Database = Annotated[Session, Depends(get_db)]
Authenticated = Annotated[User, Depends(current_user)]
ProfessionalUser = Annotated[User, Depends(require_role(Role.PROFESSIONAL))]


@router.post("", response_model=RecordResponse, status_code=201)
def create(data: RecordCreate, response: Response, db: Database, user: ProfessionalUser):
    response.headers["Cache-Control"] = "no-store"
    return service.create(db, user, data)


@router.get("", response_model=RecordPage)
def list_records(
    response: Response, db: Database, user: Authenticated, patient_id: UUID | None = None,
    cursor: UUID | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_records(
        db, user, str(patient_id) if patient_id else None, str(cursor) if cursor else None, limit,
    )


@router.get("/{record_id}", response_model=RecordResponse)
def read(record_id: UUID, response: Response, db: Database, user: Authenticated):
    response.headers["Cache-Control"] = "no-store"
    return service.read(db, user, str(record_id))


@router.patch("/{record_id}", response_model=RecordResponse)
def update(record_id: UUID, data: RecordUpdate, response: Response, db: Database, user: ProfessionalUser):
    response.headers["Cache-Control"] = "no-store"
    return service.edit(db, user, str(record_id), data)


@router.post("/{record_id}/finalize", response_model=RecordResponse)
def finalize(record_id: UUID, response: Response, db: Database, user: ProfessionalUser):
    response.headers["Cache-Control"] = "no-store"
    return service.edit(db, user, str(record_id), None)


@router.post("/{record_id}/amendments", response_model=AmendmentResponse, status_code=201)
def amend(record_id: UUID, data: AmendmentCreate, response: Response, db: Database, user: ProfessionalUser):
    response.headers["Cache-Control"] = "no-store"
    return service.append_amendment(db, user, str(record_id), data)
