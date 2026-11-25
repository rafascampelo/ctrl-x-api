import re
from datetime import UTC, datetime
from pathlib import PurePath
from threading import BoundedSemaphore

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import document_storage
from app.core.document_config import MAX_UPLOAD_BYTES, DocumentSettings
from app.models.document import DocumentGrant, PrivateDocument
from app.models.user import Role, User
from app.repositories import care, document
from app.schemas.document import DocumentResponse, DocumentReview, UploadFields
from app.services import document_ocr
from app.services.care import own_profile

EXTENSIONS = {
    ".pdf": "application/pdf", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}
OCR_SLOTS = BoundedSemaphore(2)


def validate_file(data: bytes, filename: str | None, content_type: str | None):
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Document exceeds 10 MiB")
    if not filename or len(filename) > 255 or re.search(r"[/\\\x00-\x1f\x7f]", filename):
        raise HTTPException(422, "Invalid file name")
    mime = EXTENSIONS.get(PurePath(filename).suffix.lower())
    if mime is None or mime != content_type:
        raise HTTPException(415, "Unsupported document type")
    valid_signature = {
        "application/pdf": bool(re.match(rb"%PDF-[12]\.[0-9][\r\n]", data))
        and data.rstrip().endswith(b"%%EOF"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not valid_signature[mime]:
        raise HTTPException(415, "Document content does not match its type")
    return mime


def scope(db: Session, user: User, patient_id: str | None):
    identity = own_profile(db, user)
    if user.role == Role.PATIENT:
        if patient_id is not None and patient_id != identity.id:
            raise HTTPException(404, "Patient not found")
        return identity.id, None
    if patient_id is None:
        raise HTTPException(422, "Patient ID is required")
    link = care.active_link(db, patient_id, identity.id)
    if link is None:
        raise HTTPException(404, "Patient not found")
    return patient_id, link.id


def authorized_document(db: Session, user: User, document_id: str):
    patient_id = document.patient_id_for(db, document_id)
    if patient_id is None:
        raise HTTPException(404, "Document not found")
    _, link_id = scope(db, user, patient_id)
    row = document.document(db, document_id)
    if link_id is not None and document.grant(db, document_id, link_id) is None:
        raise HTTPException(404, "Document not found")
    return row


def upload(db: Session, user: User, fields: UploadFields, data: bytes,
           filename: str | None, content_type: str | None):
    patient_id, original_link_id = scope(db, user, str(fields.patient_id) if fields.patient_id else None)
    mime = validate_file(data, filename, content_type)
    settings = DocumentSettings()
    # Release the link lock during extraction, then verify consent again before persisting.
    db.rollback()
    if not OCR_SLOTS.acquire(blocking=False):
        raise HTTPException(503, "Document processing is busy")
    try:
        status, text, error = document_ocr.extract(data, mime, settings.tesseract_cmd, settings.ocr_lang)
    finally:
        OCR_SLOTS.release()
    if status == "invalid":
        raise HTTPException(415, "Malformed or unsupported document")
    patient_id, link_id = scope(db, user, patient_id)
    if link_id != original_link_id:
        raise HTTPException(404, "Patient not found")
    try:
        storage_key, path = document_storage.store(settings.upload_dir, data)
    except (OSError, ValueError):
        raise HTTPException(503, "Private document storage is unavailable") from None
    try:
        row = PrivateDocument(
            patient_id=patient_id, uploaded_by=user.id, storage_key=storage_key,
            title=fields.title, file_name=filename, content_type=mime, size_bytes=len(data),
            ocr_status=status, raw_text=text, ocr_error=error,
            created_at=datetime.now(UTC).replace(microsecond=0),
        )
        db.add(row)
        db.flush()
        if link_id is not None:
            db.add(DocumentGrant(document_id=row.id, link_id=link_id))
        return save(db, user, row, "uploaded")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def save(db: Session, user: User, row: PrivateDocument, action: str):
    result = DocumentResponse.model_validate(row)
    care.audit(db, user, f"document_{action}", row.id, row.patient_id)
    db.commit()
    return result


def list_documents(db: Session, user: User, patient_id: str | None, cursor: str | None, limit: int):
    patient_id, link_id = scope(db, user, patient_id)
    rows = document.documents(db, patient_id, link_id, cursor, limit)
    items = [DocumentResponse.model_validate(row) for row in rows[:limit]]
    care.audit(db, user, "documents_viewed", patient_id, patient_id)
    db.commit()
    return {"items": items, "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def download(db: Session, user: User, document_id: str):
    row = authorized_document(db, user, document_id)
    try:
        data = document_storage.read(DocumentSettings().upload_dir, row.storage_key, row.size_bytes)
    except (OSError, ValueError):
        raise HTTPException(503, "Private document storage is unavailable") from None
    result = data, row.file_name, row.content_type
    care.audit(db, user, "document_downloaded", row.id, row.patient_id)
    db.commit()
    return result


def review(db: Session, user: User, document_id: str, data: DocumentReview):
    row = authorized_document(db, user, document_id)
    row.reviewed_text = data.extracted_text
    row.reviewed_by = user.id
    row.verified_at = datetime.now(UTC).replace(microsecond=0)
    return save(db, user, row, "ocr_reviewed")


def change_access(db: Session, user: User, document_id: str, professional_id: str, grant: bool):
    patient_id = document.patient_id_for(db, document_id)
    if patient_id is None:
        raise HTTPException(404, "Document not found")
    scope(db, user, patient_id)
    link = care.active_link(db, patient_id, professional_id)
    if link is None:
        raise HTTPException(404, "Active professional link not found")
    existing = document.grant(db, document_id, link.id)
    if grant and existing is None:
        db.add(DocumentGrant(document_id=document_id, link_id=link.id))
    if not grant and existing is not None:
        db.delete(existing)
    action = "document_access_granted" if grant else "document_access_revoked"
    care.audit(db, user, action, document_id, patient_id)
    db.commit()
