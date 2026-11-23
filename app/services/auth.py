from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    DUMMY_HASH,
    SESSION_DURATION_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    SESSION_RENEWAL_WINDOW_SECONDS,
    create_access_token,
    password_hash,
)
from app.models.auth import AuthSession
from app.models.user import Patient, Professional, Role, User
from app.repositories.auth import audit, reserve_login_attempt, utc
from app.repositories.users import by_email
from app.schemas.auth import Credentials, Registration


def register(db: Session, data: Registration) -> User:
    user = User(email=data.email, password_hash=password_hash.hash(data.password), role=data.role)
    profile = Patient(full_name=data.full_name) if data.role == Role.PATIENT else Professional(
        full_name=data.full_name, crefito_region=data.crefito_region, crefito_number=data.crefito_number,
    )
    profile.user = user
    try:
        db.add(profile)
        db.flush()
        audit(db, "register_succeeded", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        audit(db, "register_rejected")
        db.commit()
        detail = ("Unable to register with these details" if data.role == Role.PROFESSIONAL
                  else "Unable to register with this email")
        raise HTTPException(status_code=409, detail=detail) from None
    return user


def authenticate(db: Session, data: Credentials) -> User:
    retry_after = reserve_login_attempt(db, data.email)
    if retry_after:
        raise HTTPException(status_code=429, detail="Too many login attempts",
                            headers={"Retry-After": str(retry_after)})
    user = by_email(db, data.email)
    valid = password_hash.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid:
        audit(db, "login_failed")
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def start_session(db: Session, user: User) -> str:
    issued_at = datetime.now(UTC).replace(microsecond=0)
    session = AuthSession(
        id=str(uuid4()), user_id=user.id,
        expires_at=issued_at + timedelta(seconds=SESSION_DURATION_SECONDS),
    )
    db.add(session)
    token = create_access_token(user, session, issued_at, issued_at)
    audit(db, "login_succeeded", user.id)
    db.commit()
    return token


def renew_session(db: Session, user: User, session_id: str, token_expires_at: datetime,
                  started_at: datetime) -> tuple[str | None, datetime]:
    # Lock and reload after authentication so concurrent renewals or logout share the same state.
    session = db.get(AuthSession, session_id, with_for_update=True, populate_existing=True)
    now = datetime.now(UTC)
    if (session is None or session.user_id != user.id or session.revoked_at is not None
            or min(utc(session.expires_at), token_expires_at) <= now):
        raise HTTPException(401, "Not authenticated")

    expires_at = utc(session.expires_at)
    issued_at = now.replace(microsecond=0)
    if expires_at - now <= timedelta(seconds=SESSION_RENEWAL_WINDOW_SECONDS):
        renewal = min(
            issued_at + timedelta(seconds=SESSION_DURATION_SECONDS),
            started_at + timedelta(seconds=SESSION_MAX_AGE_SECONDS),
        )
        if renewal > expires_at:
            expires_at = session.expires_at = renewal
            audit(db, "session_renewed", user.id)

    # A second tab with the previous JWT can receive the expiry already set by the first.
    token = None
    if expires_at > token_expires_at:
        token = create_access_token(user, session, issued_at, started_at)
    db.commit()
    return token, expires_at
