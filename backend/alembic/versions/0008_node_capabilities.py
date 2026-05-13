"""Add capabilities JSONB column to nodes

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "capabilities")
