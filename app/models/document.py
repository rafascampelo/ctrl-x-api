from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PrivateDocument(Base):
    __tablename__ = "private_documents"
    __table_args__ = (Index("ix_private_documents_patient_id", "patient_id", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(150))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int]
    ocr_status: Mapped[str] = mapped_column(String(12))
    ocr_error: Mapped[str | None] = mapped_column(String(160))
    raw_text: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"))
    reviewed_text: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @property
    def is_verified(self):
        return self.verified_at is not None

    @property
    def extracted_text(self):
        return self.reviewed_text if self.is_verified else self.raw_text


class DocumentGrant(Base):
    __tablename__ = "document_grants"
    __table_args__ = (Index("ix_document_grants_link_id", "link_id", "document_id"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("private_documents.id"), primary_key=True)
    link_id: Mapped[str] = mapped_column(ForeignKey("professional_links.id"), primary_key=True)
