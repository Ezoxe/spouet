"""Add naming (auto-title) server fields on nodes

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-07 00:00:00.000000

Un node peut exposer un 2e llama-server dédié au nommage (titre + tags),
petit modèle toujours chargé. Le backend y route l'autoname. Champs miroir des
champs image_*.
"""
from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("naming_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("nodes", sa.Column("naming_port", sa.Integer(), nullable=True))
    op.add_column("nodes", sa.Column("naming_model", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "naming_model")
    op.drop_column("nodes", "naming_port")
    op.drop_column("nodes", "naming_enabled")
