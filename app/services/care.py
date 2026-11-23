from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.professional_link import LinkStatus, ProfessionalLink
from app.models.user import Role, User
from app.repositories import care
from app.schemas.care import ProfessionalProfileResponse, ProfileResponse, ProfileUpdate


def own_profile(db: Session, user: User):
    result = care.profile(db, user)
    if result is None:
        raise HTTPException(404, "Profile not found")
    return result


def profile_response(profile, role: Role):
    values = {"id": profile.id, "user_id": profile.user_id,
              "full_name": profile.full_name, "role": role}
    if role == Role.PROFESSIONAL:
        return ProfessionalProfileResponse(
            **values, crefito_region=profile.crefito_region, crefito_number=profile.crefito_number,
            verification_status=profile.verification_status,
        )
    return ProfileResponse(**values)


def read_profile(db: Session, user: User):
    profile = own_profile(db, user)
    care.audit(db, user, "profile_viewed", profile.id,
               profile.id if user.role == Role.PATIENT else None)
    db.commit()
    return profile_response(profile, user.role)


def update_profile(db: Session, user: User, data: ProfileUpdate):
    profile = own_profile(db, user)
    fields = data.model_fields_set & {"crefito_region", "crefito_number"}
    if fields and user.role != Role.PROFESSIONAL:
        raise HTTPException(422, "Invalid request payload")
    if fields:
        if data.crefito_region is None or data.crefito_number is None:
            raise HTTPException(422, "Invalid request payload")
        profile.crefito_region = data.crefito_region
        profile.crefito_number = data.crefito_number
    if user.role == Role.PROFESSIONAL and (
        bool(fields) or profile.full_name != data.full_name
    ):
        profile.verification_status = "unverified"
        profile.verified_at = None
        profile.verification_reference = None
    profile.full_name = data.full_name
    care.audit(db, user, "profile_updated", profile.id,
               profile.id if user.role == Role.PATIENT else None)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Unable to update profile with these details") from None
    return profile_response(profile, user.role)


def list_links(db: Session, user: User, cursor: str | None, limit: int):
    identity = own_profile(db, user)
    items = care.list_links(db, identity.id, user.role, cursor, limit)
    next_cursor = items[limit - 1].id if len(items) > limit else None
    care.audit(db, user, "links_viewed", identity.id,
               identity.id if user.role == Role.PATIENT else None)
    db.commit()
    return {"items": items[:limit], "next_cursor": next_cursor}


def read_patient(db: Session, user: User, patient_id: str):
    profile = authorize_patient(db, user, patient_id)
    care.audit(db, user, "patient_viewed", profile.id, profile.id)
    db.commit()
    return profile_response(profile, Role.PATIENT)


def list_patients(db: Session, user: User, cursor: str | None, limit: int):
    professional = own_profile(db, user)
    patients = care.linked_patients(db, professional.id, cursor, limit)
    next_cursor = patients[limit - 1].id if len(patients) > limit else None
    for patient in patients[:limit]:
        care.audit(db, user, "patient_viewed", patient.id, patient.id)
    result = [profile_response(patient, Role.PATIENT) for patient in patients[:limit]]
    db.commit()
    return {"items": result, "next_cursor": next_cursor}


def authorize_patient(db: Session, user: User, patient_id: str):
    identity = own_profile(db, user)
    if user.role == Role.PATIENT:
        allowed = identity.id == patient_id
    else:
        allowed = care.active_link(db, patient_id, identity.id) is not None
    if not allowed:
        raise HTTPException(404, "Patient not found")
    patient = care.patient(db, patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient


def request_link(db: Session, user: User, professional_id: str):
    if user.role != Role.PATIENT:
        raise HTTPException(403, "Forbidden")
    patient = own_profile(db, user)
    # Serialize requests and transitions for the same patient.
    care.lock_patient(db, patient.id)
    if care.patient_active_link(db, patient.id):
        raise HTTPException(409, "End the active link before requesting another professional")
    professional = care.professional(db, professional_id)
    if professional is None:
        raise HTTPException(404, "Professional not found")
    existing = care.open_link(db, patient.id, professional_id)
    if existing:
        raise HTTPException(409, "Link already pending or active")
    link = ProfessionalLink(patient_id=patient.id, professional_id=professional_id)
    db.add(link)
    db.flush()
    care.audit(db, user, "link_requested", link.id, patient.id)
    db.commit()
    return link


def transition_link(db: Session, user: User, link_id: str, accept: bool, reject: bool = False):
    if (accept or reject) and user.role != Role.PROFESSIONAL:
        raise HTTPException(403, "Forbidden")
    identity = own_profile(db, user)
    link = care.participant_link(db, link_id, identity.id, user.role)
    if link is None:
        raise HTTPException(404, "Link not found")
    care.lock_patient(db, link.patient_id)
    care.lock_link(db, link)
    now = datetime.now(UTC)
    if accept:
        if link.status != LinkStatus.PENDING:
            raise HTTPException(409, "Link is not pending")
        active = care.patient_active_link(db, link.patient_id)
        if active:
            raise HTTPException(409, "Patient already has an active professional")
        link.status = LinkStatus.ACTIVE
        link.accepted_at = now
        for pending in care.pending_links(db, link.patient_id, link.id):
            pending.status = LinkStatus.CANCELLED
            pending.closed_at = now
            care.audit(db, user, "link_superseded", pending.id, pending.patient_id)
        action = "link_accepted"
    else:
        if reject and link.status != LinkStatus.PENDING:
            raise HTTPException(409, "Link is not pending")
        if link.status in {LinkStatus.REVOKED, LinkStatus.REJECTED, LinkStatus.CANCELLED}:
            return
        if link.status == LinkStatus.PENDING:
            refused = user.role == Role.PROFESSIONAL
            link.status = LinkStatus.REJECTED if refused else LinkStatus.CANCELLED
            action = "link_rejected" if refused else "link_cancelled"
        else:
            link.status = LinkStatus.REVOKED
            link.revoked_at = now
            action = "link_revoked"
        link.closed_at = now
    care.audit(db, user, action, link.id, link.patient_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Patient already has an active professional") from None
    return link
