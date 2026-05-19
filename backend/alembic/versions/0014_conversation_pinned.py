"""Add pinned flag on conversations

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-19 00:00:00.000000

Permet à l'utilisateur d'épingler ses conversations importantes en tête de
liste. Le champ est `nullable=False` avec default `false` — toutes les convs
existantes deviennent non-épinglées.
"""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_conversations_user_pinned",
        "conversations",
        ["user_id", "pinned"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_pinned", table_name="conversations")
    op.drop_column("conversations", "pinned")
