"""Generated images

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-04 00:00:00.000000

Images générées par le microservice image-engine (diffusers). Les octets PNG
vivent sur disque (volume images_dir) ; cette table ne garde que les métadonnées
+ le chemin relatif du fichier.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(255), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column(
            "params_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_generated_images_user", "generated_images", ["user_id"])
    op.create_index("ix_generated_images_conversation", "generated_images", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_images_conversation", table_name="generated_images")
    op.drop_index("ix_generated_images_user", table_name="generated_images")
    op.drop_table("generated_images")
