from datetime import UTC, datetime
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    COOKIE_NAME,
    SESSION_DURATION_SECONDS,
    SESSION_REMAINING_HEADER,
    cookie_auth,
    current_user,
    require_trusted_origin,
)
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.user import User
from app.repositories.auth import audit
from app.schemas.auth import Credentials, ErrorResponse, Registration, UserResponse
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"], responses={
    422: {"model": ErrorResponse, "description": "Invalid request payload"},
})


def _cookie_samesite() -> str:
    return "lax" if get_settings().app_env == "development" else "none"


@router.post("/register", response_model=UserResponse, status_code=201,
             dependencies=[Depends(require_trusted_origin)], responses={
                 403: {"model": ErrorResponse, "description": "Missing or untrusted Origin"},
                 409: {"model": ErrorResponse, "description": "Email already registered"},
             })
def register(data: Registration, db: Annotated[Session, Depends(get_db)]):
    return auth.register(db, data)


@router.post("/login", response_model=UserResponse, dependencies=[Depends(require_trusted_origin)],
             responses={
                 200: {"description": "User and host-only ctrlx_access JWT cookie. "
                       f"HttpOnly; Path=/; Max-Age={SESSION_DURATION_SECONDS}; SameSite=None. "
                       "Secure outside development. No refresh token.",
                       "headers": {"Set-Cookie": {"schema": {"type": "string"}},
                                   "Cache-Control": {"schema": {"type": "string"}},
                                   SESSION_REMAINING_HEADER: {"schema": {"type": "integer"}}}},
                 401: {"model": ErrorResponse, "description": "Invalid credentials"},
                 403: {"model": ErrorResponse, "description": "Missing or untrusted Origin"},
                 429: {"model": ErrorResponse, "description": "Login limit reached", "headers": {
                     "Retry-After": {"schema": {"type": "integer"}}}},
             })
def login(data: Credentials, response: Response, db: Annotated[Session, Depends(get_db)]):
    user = auth.authenticate(db, data)
    response.set_cookie(
        COOKIE_NAME, auth.start_session(db, user), max_age=SESSION_DURATION_SECONDS, httponly=True,
        secure=get_settings().app_env != "development", samesite=_cookie_samesite(), path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers[SESSION_REMAINING_HEADER] = str(SESSION_DURATION_SECONDS)
    return user


@router.get("/me", response_model=UserResponse,
            responses={
                200: {"headers": {SESSION_REMAINING_HEADER: {"schema": {"type": "integer"}}}},
                401: {"model": ErrorResponse, "description": "Missing, expired, invalid or revoked session"},
            })
def me(request: Request, response: Response, user: Annotated[User, Depends(current_user)],
       db: Annotated[Session, Depends(get_db)]):
    audit(db, "session_viewed", user.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    remaining = request.state.auth_session_expires_at - datetime.now(UTC)
    response.headers[SESSION_REMAINING_HEADER] = str(max(0, ceil(remaining.total_seconds())))
    return user


@router.post("/logout", status_code=204,
             dependencies=[Depends(require_trusted_origin), Depends(cookie_auth)],
             openapi_extra={"security": [{"APIKeyCookie": []}, {}]},
             responses={
                 204: {"description": "Session revoked and ctrlx_access cookie removed",
                       "headers": {"Set-Cookie": {"schema": {"type": "string"}}}},
                 403: {"model": ErrorResponse, "description": "Missing or untrusted Origin"},
             })
def logout(request: Request, db: Annotated[Session, Depends(get_db)]):
    try:
        user = current_user(request, db)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        audit(db, "logout_anonymous")
    else:
        db.execute(update(AuthSession).where(
            AuthSession.id == request.state.auth_session_id,
            AuthSession.revoked_at.is_(None),
        ).values(revoked_at=datetime.now(UTC)))
        audit(db, "logout_succeeded", user.id)
    db.commit()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=get_settings().app_env != "development",
                           samesite=_cookie_samesite())
    return response
