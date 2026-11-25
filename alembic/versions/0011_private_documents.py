"""Persist private document metadata, OCR review, and per-link access grants."""

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from alembic import op

revision = "0011_private_documents"
down_revision = "0010_prescriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    long_text = sa.Text().with_variant(MEDIUMTEXT(), "mysql")
    op.create_table(
        "private_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("storage_key", sa.String(32), unique=True, nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("ocr_status", sa.String(12), nullable=False),
        sa.Column("ocr_error", sa.String(160)),
        sa.Column("raw_text", long_text),
        sa.Column("reviewed_text", long_text),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_private_documents_patient_id", "private_documents", ["patient_id", "id"])
    op.create_table(
        "document_grants",
        sa.Column("document_id", sa.String(36), sa.ForeignKey("private_documents.id"), primary_key=True),
        sa.Column("link_id", sa.String(36), sa.ForeignKey("professional_links.id"), primary_key=True),
    )
    op.create_index("ix_document_grants_link_id", "document_grants", ["link_id", "document_id"])


def downgrade() -> None:
    op.drop_table("document_grants")
    op.drop_table("private_documents")
