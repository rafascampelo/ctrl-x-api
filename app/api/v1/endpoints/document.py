from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.document_config import MAX_MULTIPART_BYTES, MAX_UPLOAD_BYTES
from app.core.security import current_user, require_role
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import ErrorResponse
from app.schemas.document import DocumentPage, DocumentResponse, DocumentReview, UploadFields
from app.services import document as service

router = APIRouter(
    prefix="/documents", tags=["private documents"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 413, 415, 422, 503)},
)
Database = Annotated[Session, Depends(get_db)]
Authenticated = Annotated[User, Depends(current_user)]
PatientUser = Annotated[User, Depends(require_role(Role.PATIENT))]
NO_STORE = {"Cache-Control": "no-store"}


async def parse_upload(request: Request):
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "multipart/form-data":
        raise HTTPException(415, "Expected a multipart document")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_MULTIPART_BYTES:
            raise HTTPException(413, "Document exceeds 10 MiB")
        body.extend(chunk)

    async def bounded_body():
        for start in range(0, len(body), 64 * 1024):
            yield bytes(body[start:start + 64 * 1024])

    try:
        form = await MultiPartParser(
            request.headers, bounded_body(), max_files=1, max_fields=2, max_part_size=2048,
        ).parse()
    except (MultiPartException, MultipartParseError):
        raise HTTPException(422, "Invalid document upload") from None
    try:
        uploaded = form.get("file")
        if not isinstance(uploaded, UploadFile) or len(form.multi_items()) != len(form):
            raise HTTPException(422, "Invalid document upload")
        fields = UploadFields.model_validate({key: value for key, value in form.items() if key != "file"})
        data = await uploaded.read(MAX_UPLOAD_BYTES + 1)
        return fields, data, uploaded.filename, uploaded.content_type
    except ValidationError:
        raise HTTPException(422, "Invalid document upload") from None
    finally:
        await form.close()


@router.get("", response_model=DocumentPage)
def list_documents(
    response: Response, db: Database, user: Authenticated, patient_id: UUID | None = None,
    cursor: UUID | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    response.headers.update(NO_STORE)
    return service.list_documents(
        db, user, str(patient_id) if patient_id else None, str(cursor) if cursor else None, limit,
    )


@router.post("", response_model=DocumentResponse, status_code=201, openapi_extra={
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["file", "title"],
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "title": {"type": "string", "minLength": 1, "maxLength": 150},
                "patient_id": {"type": "string", "format": "uuid"},
            },
        }}},
    },
})
async def upload(request: Request, response: Response, db: Database, user: Authenticated):
    response.headers.update(NO_STORE)
    fields, data, filename, content_type = await parse_upload(request)
    return await run_in_threadpool(service.upload, db, user, fields, data, filename, content_type)


@router.get("/{document_id}/download", response_class=Response)
def download(document_id: UUID, db: Database, user: Authenticated):
    data, filename, mime = service.download(db, user, str(document_id))
    return Response(data, media_type=mime, headers={
        **NO_STORE,
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/{document_id}/verify", response_model=DocumentResponse)
def review(document_id: UUID, data: DocumentReview, response: Response, db: Database, user: Authenticated):
    response.headers.update(NO_STORE)
    return service.review(db, user, str(document_id), data)


@router.post("/{document_id}/access/{professional_id}", status_code=204)
def grant(document_id: UUID, professional_id: UUID, db: Database, user: PatientUser):
    service.change_access(db, user, str(document_id), str(professional_id), True)
    return Response(status_code=204, headers=NO_STORE)


@router.delete("/{document_id}/access/{professional_id}", status_code=204)
def revoke(document_id: UUID, professional_id: UUID, db: Database, user: PatientUser):
    service.change_access(db, user, str(document_id), str(professional_id), False)
    return Response(status_code=204, headers=NO_STORE)
