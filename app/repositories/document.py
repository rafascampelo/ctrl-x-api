from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import DocumentGrant, PrivateDocument


def patient_id_for(db: Session, document_id: str):
    return db.scalar(select(PrivateDocument.patient_id).where(PrivateDocument.id == document_id))


def document(db: Session, document_id: str):
    return db.scalar(select(PrivateDocument).where(PrivateDocument.id == document_id).with_for_update())


def grant(db: Session, document_id: str, link_id: str):
    return db.get(DocumentGrant, (document_id, link_id), with_for_update=True)


def documents(db: Session, patient_id: str, link_id: str | None, cursor: str | None, limit: int):
    query = select(PrivateDocument).where(PrivateDocument.patient_id == patient_id)
    if link_id is not None:
        query = query.join(DocumentGrant).where(DocumentGrant.link_id == link_id).with_for_update()
    if cursor:
        query = query.where(PrivateDocument.id < cursor)
    return list(db.scalars(query.order_by(PrivateDocument.id.desc()).limit(limit + 1)))
