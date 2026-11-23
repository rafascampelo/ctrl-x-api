from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import DUMMY_HASH, create_access_token, password_hash
from app.models.auth import AuthSession
from app.models.user import Patient, Professional, Role, User
from app.repositories.auth import audit, reserve_login_attempt
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
    session = AuthSession(id=str(uuid4()), user_id=user.id,
                          expires_at=datetime.now(UTC) + timedelta(minutes=15))
    db.add(session)
    token = create_access_token(user, session)
    audit(db, "login_succeeded", user.id)
    db.commit()
    return token
