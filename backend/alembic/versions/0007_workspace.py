"""Add workspace_sessions table and workspace fields to conversations

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="New workspace"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "conversations",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("workspace_role", sa.String(16), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "allowed_tool_slugs",
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_foreign_key(
        "fk_conversations_workspace_id",
        "conversations",
        "workspace_sessions",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conversations_workspace_id",
        "conversations",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_constraint("fk_conversations_workspace_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "allowed_tool_slugs")
    op.drop_column("conversations", "workspace_role")
    op.drop_column("conversations", "workspace_id")
    op.drop_table("workspace_sessions")
