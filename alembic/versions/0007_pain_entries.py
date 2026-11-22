"""Persist patient-owned pain diary entries."""

import sqlalchemy as sa

from alembic import op

revision = "0007_pain_entries"
down_revision = "0006_link_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pain_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("intensity", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(2000)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("intensity BETWEEN 0 AND 10", name="ck_pain_intensity"),
    )
    op.create_index("ix_pain_entries_patient_time_id", "pain_entries",
                    ["patient_id", "occurred_at", "id"])


def downgrade() -> None:
    # InnoDB uses the composite index for the patient FK; drop both with the table.
    op.drop_table("pain_entries")
