from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.prescription import PrescribedExercise, Prescription, PrescriptionCompletion
from app.models.user import User
from app.repositories import care, prescription
from app.schemas.prescription import (
    CompletionCreate,
    CompletionResponse,
    PrescriptionCreate,
    PrescriptionResponse,
)
from app.services.care import authorize_patient, own_profile
from app.services.pain import patient_owner


def create(db: Session, user: User, patient_id: str, data: PrescriptionCreate):
    authorize_patient(db, user, patient_id)
    professional = own_profile(db, user)
    routine = Prescription(
        patient_id=patient_id,
        professional=professional,
        created_at=datetime.now(UTC).replace(microsecond=0),
        **data.model_dump(exclude={"exercises"}),
        exercises=[
            PrescribedExercise(position=position, **exercise.model_dump())
            for position, exercise in enumerate(data.exercises)
        ],
    )
    db.add(routine)
    db.flush()
    result = PrescriptionResponse.model_validate(routine)
    care.audit(db, user, "prescription_created", routine.id, patient_id)
    db.commit()
    return result


def list_prescriptions(db: Session, user: User, patient_id: str | None, cursor: str | None, limit: int):
    patient = (patient_owner(db, user) if patient_id is None
               else authorize_patient(db, user, patient_id))
    rows = prescription.prescriptions(db, patient.id, cursor, limit)
    items = [PrescriptionResponse.model_validate(row) for row in rows[:limit]]
    care.audit(db, user, "prescriptions_viewed", patient.id, patient.id)
    db.commit()
    return {"items": items, "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def log_completion(db: Session, user: User, prescription_id: str, data: CompletionCreate):
    patient = patient_owner(db, user)
    if prescription.scoped_prescription_id(db, patient.id, prescription_id) is None:
        raise HTTPException(404, "Prescription not found")
    completion = PrescriptionCompletion(
        prescription_id=prescription_id, notes=data.notes,
        completed_at=datetime.now(UTC).replace(microsecond=0),
    )
    db.add(completion)
    db.flush()
    result = CompletionResponse.model_validate(completion)
    care.audit(db, user, "prescription_completion_created", completion.id, patient.id)
    db.commit()
    return result
