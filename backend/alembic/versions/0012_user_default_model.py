"""Add default_model column to users

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-14 00:00:00.000000

Préférence serveur-side du modèle par défaut, pour que le choix soit
partagé entre l'app web, le desktop Tauri et utilisé par les connectors
quand ils créent une conversation sans modèle explicite.
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("default_model", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "default_model")
