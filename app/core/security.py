from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.user import Role, User
from app.repositories.auth import utc

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("not-a-real-password-for-timing")
COOKIE_NAME = "ctrlx_access"
SESSION_DURATION_SECONDS = 900
SESSION_REMAINING_HEADER = "X-Session-Remaining"
cookie_auth = APIKeyCookie(name=COOKIE_NAME, auto_error=False)


def create_access_token(user: User, session: AuthSession) -> str:
    settings = get_settings()
    now = session.expires_at - timedelta(seconds=SESSION_DURATION_SECONDS)
    return jwt.encode(
        {"sub": user.id, "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
         "iat": now, "exp": session.expires_at, "jti": session.id},
        settings.secret_key.get_secret_value(), algorithm="HS256",
    )


def current_user(request: Request, db: Annotated[Session, Depends(get_db)],
                 cookie: Annotated[str | None, Depends(cookie_auth)] = None) -> User:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_trusted_origin(request)
    token = cookie or request.cookies.get(COOKIE_NAME)
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not token:
        raise error
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.secret_key.get_secret_value(), algorithms=["HS256"],
            issuer=settings.jwt_issuer, audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
        user_id = str(UUID(claims["sub"]))
        session_id = str(UUID(claims["jti"]))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise error from None
    session = db.get(AuthSession, session_id)
    if (session is None or session.user_id != user_id or session.revoked_at is not None
            or utc(session.expires_at) <= datetime.now(UTC)):
        raise error
    request.state.auth_session_id = session.id
    request.state.auth_session_expires_at = utc(session.expires_at)
    user = db.get(User, user_id)
    if user is None:
        raise error
    return user


def require_role(role: Role):
    def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return dependency


def require_trusted_origin(
    request: Request,
    origin: Annotated[str | None, Header(description="Exact allowed frontend origin")] = None,
) -> None:
    if (origin or request.headers.get("origin")) not in get_settings().origins:
        raise HTTPException(status_code=403, detail="Untrusted origin")
