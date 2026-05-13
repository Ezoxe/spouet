"""Add metadata_json column to connectors

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13 00:00:00.000000

Stocke des metadata calculées dynamiquement (ex: bot_user_id Discord récupéré
au `on_ready`), pas la config utilisateur (qui reste dans config_json).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connectors",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("connectors", "metadata_json")
