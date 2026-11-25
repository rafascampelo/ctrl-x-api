from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ErrorResponse
from app.schemas.prescription import (
    CompletionCreate,
    CompletionResponse,
    PrescriptionCreate,
    PrescriptionPage,
    PrescriptionResponse,
)
from app.services import prescription as service

router = APIRouter(
    tags=["exercise prescriptions"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 422)},
)
Database = Annotated[Session, Depends(get_db)]
PatientUser = Annotated[User, Depends(require_role(Role.PATIENT))]
ProfessionalUser = Annotated[User, Depends(require_role(Role.PROFESSIONAL))]
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.post("/patients/{patient_id}/prescriptions", response_model=PrescriptionResponse, status_code=201)
def create(patient_id: UUID, data: PrescriptionCreate, response: Response, db: Database, user: ProfessionalUser):
    response.headers["Cache-Control"] = "no-store"
    return service.create(db, user, str(patient_id), data)


@router.get("/patients/{patient_id}/prescriptions", response_model=PrescriptionPage)
def professional_list(
    patient_id: UUID, response: Response, db: Database, user: ProfessionalUser,
    cursor: UUID | None = None, limit: PageLimit = 20,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_prescriptions(db, user, str(patient_id), str(cursor) if cursor else None, limit)


@router.get("/me/prescriptions", response_model=PrescriptionPage)
def patient_list(
    response: Response, db: Database, user: PatientUser, cursor: UUID | None = None, limit: PageLimit = 20,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_prescriptions(db, user, None, str(cursor) if cursor else None, limit)


@router.post("/me/prescriptions/{prescription_id}/completions", response_model=CompletionResponse, status_code=201)
def complete(
    prescription_id: UUID, data: CompletionCreate, response: Response, db: Database, user: PatientUser,
):
    response.headers["Cache-Control"] = "no-store"
    return service.log_completion(db, user, str(prescription_id), data)
