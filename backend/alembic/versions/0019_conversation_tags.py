"""Add tags array on conversations

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-06 00:00:00.000000

Permet de classer/filtrer les conversations par mots-clés. Le champ est
`nullable=False` avec default `{}` (tableau vide) — les conversations existantes
démarrent sans tag. Index GIN pour les recherches `tag = ANY(tags)`.
"""
from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "tags",
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_conversations_tags",
        "conversations",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_tags", table_name="conversations")
    op.drop_column("conversations", "tags")
