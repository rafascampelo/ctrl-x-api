"""Persist prescribed routines, their exercises, and completion logs."""

import sqlalchemy as sa

from alembic import op

revision = "0010_prescriptions"
down_revision = "0009_clinical_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prescriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("professional_id", sa.String(36), sa.ForeignKey("professionals.id"), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("frequency", sa.String(120), nullable=False),
        sa.Column("clinical_notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id", "id"])
    op.create_table(
        "prescribed_exercises",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prescription_id", sa.String(36), sa.ForeignKey("prescriptions.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sets", sa.Integer, nullable=False),
        sa.Column("reps", sa.String(60), nullable=False),
        sa.Column("notes", sa.Text),
        sa.CheckConstraint("sets BETWEEN 1 AND 20", name="ck_exercise_sets"),
        sa.UniqueConstraint("prescription_id", "position", name="uq_prescribed_exercise_position"),
    )
    op.create_table(
        "prescription_completions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prescription_id", sa.String(36), sa.ForeignKey("prescriptions.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text),
    )
    op.create_index(
        "ix_completion_prescription_time", "prescription_completions",
        ["prescription_id", "completed_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("prescription_completions")
    op.drop_table("prescribed_exercises")
    op.drop_table("prescriptions")
