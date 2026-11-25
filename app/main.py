from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.care import router as care_router
from app.api.v1.endpoints.history import router as history_router
from app.api.v1.endpoints.pain import router as pain_router
from app.core.config import CorsSettings
from app.core.security import SESSION_REMAINING_HEADER
from app.db.session import database_ready

app = FastAPI(title="Ctrl X API", version="0.1.0")

origins = CorsSettings().origins
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
                   expose_headers=["Retry-After", SESSION_REMAINING_HEADER])
app.include_router(auth_router, prefix="/api/v1")
app.include_router(care_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(pain_router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request payload"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db", responses={503: {"description": "Database unavailable"}})
def health_db(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    if database_ready():
        return {"status": "ok"}
    response.status_code = 503
    return {"status": "unavailable"}
