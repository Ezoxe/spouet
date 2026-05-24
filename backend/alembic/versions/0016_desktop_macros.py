"""Desktop macros

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-24 00:00:00.000000

Macros desktop : séquences d'actions bureau nommées (« soirée Minecraft » =
lancer CurseForge sur l'écran 1 + ouvrir YouTube sur l'écran 2), apprises par
la conversation et exécutées côté client (app Tauri), jamais dans un conteneur.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_macros",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "steps_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("user_id", "slug", name="uq_macro_user_slug"),
    )
    op.create_index("ix_desktop_macros_user", "desktop_macros", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_desktop_macros_user", table_name="desktop_macros")
    op.drop_table("desktop_macros")
