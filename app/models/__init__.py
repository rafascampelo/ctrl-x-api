"""Register ORM models for Alembic."""

from app.models.auth import AuthEvent, AuthSession, LoginLimit
from app.models.clinical_record import ClinicalRecord, ClinicalRecordAmendment
from app.models.crefito_review import CrefitoReview
from app.models.pain_entry import PainEntry
from app.models.professional_link import CareAuditEvent, LinkStatus, ProfessionalLink
from app.models.user import Patient, Professional, Role, User

__all__ = [
    "AuthEvent",
    "AuthSession",
    "CareAuditEvent",
    "ClinicalRecord",
    "ClinicalRecordAmendment",
    "CrefitoReview",
    "LinkStatus",
    "LoginLimit",
    "PainEntry",
    "Patient",
    "Professional",
    "ProfessionalLink",
    "Role",
    "User",
]
