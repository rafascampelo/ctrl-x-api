"""Track public CREFITO registry reviews."""

import sqlalchemy as sa

from alembic import op

revision = "0008_crefito_reviews"
down_revision = "0007_pain_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crefito_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("professional_id", sa.String(36), sa.ForeignKey("professionals.id"), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(16)),
        sa.Column("reason", sa.String(32)),
        sa.Column("source", sa.String(20)),
        sa.Column("reviewer_id", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("authorization_withdrawn", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_crefito_reviews_professional_current", "crefito_reviews", ["professional_id", "current"])


def downgrade() -> None:
    op.drop_table("crefito_reviews")
