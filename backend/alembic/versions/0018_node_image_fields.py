"""Node image generation fields

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-05 00:00:00.000000

La génération d'images tourne sur le node (machine GPU), pas sur l'admin. Le
node-agent (extra [images]) publie sa capacité dans le heartbeat ; le backend
route les demandes vers http://{host}:{image_port}/generate.
"""
from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("image_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("nodes", sa.Column("image_port", sa.Integer(), nullable=True))
    op.add_column("nodes", sa.Column("image_model", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "image_model")
    op.drop_column("nodes", "image_port")
    op.drop_column("nodes", "image_enabled")
