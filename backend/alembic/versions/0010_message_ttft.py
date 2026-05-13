"""Add ttft_ms column to messages (time-to-first-token)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("ttft_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "ttft_ms")
