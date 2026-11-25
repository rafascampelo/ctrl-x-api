"""Persist structured clinical records and append-only amendments."""

import sqlalchemy as sa

from alembic import op

revision = "0009_clinical_records"
down_revision = "0008_crefito_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("professional_id", sa.String(36), sa.ForeignKey("professionals.id"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("chief_complaint", sa.Text, nullable=False),
        sa.Column("anamnesis", sa.Text, nullable=False),
        sa.Column("physical_assessment", sa.Text, nullable=False),
        sa.Column("body_region", sa.String(120), nullable=False),
        sa.Column("pain_intensity", sa.Integer),
        sa.Column("functional_limitations", sa.Text, nullable=False),
        sa.Column("therapeutic_goals", sa.Text, nullable=False),
        sa.Column("care_plan", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("pain_intensity BETWEEN 0 AND 10", name="ck_clinical_pain"),
        sa.CheckConstraint(
            "(status = 'draft' AND finalized_at IS NULL) OR "
            "(status = 'finalized' AND finalized_at IS NOT NULL)",
            name="ck_clinical_status",
        ),
    )
    op.create_index("ix_clinical_patient_id", "clinical_records", ["patient_id", "id"])
    op.create_index(
        "ix_clinical_patient_finalized", "clinical_records", ["patient_id", "finalized_at", "id"],
    )
    op.create_table(
        "clinical_record_amendments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("clinical_records.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("professionals.id"), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_clinical_amendment_record", "clinical_record_amendments", ["record_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("clinical_record_amendments")
    op.drop_table("clinical_records")
