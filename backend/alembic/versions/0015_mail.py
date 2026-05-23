"""Mail accounts, messages, drafts

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-23 00:00:00.000000

Traitement automatique des mails : boîtes IMAP/SMTP multiples, messages
analysés/classés par l'IA, et brouillons de réponse en attente de validation
HITL. Aucune suppression définitive ni envoi automatique côté code métier.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("imap_host", sa.String(255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("imap_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("smtp_host", sa.String(255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="465"),
        sa.Column("smtp_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("username", sa.String(320), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_classify", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_trash_spam", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spam_folder", sa.String(120), nullable=False, server_default="Junk"),
        sa.Column("auto_draft_replies", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("signature", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_uid", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_mail_accounts_user", "mail_accounts", ["user_id"])

    op.create_table(
        "mail_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mail_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("folder", sa.String(120), nullable=False, server_default="INBOX"),
        sa.Column("message_id", sa.String(512), nullable=True),
        sa.Column("from_addr", sa.String(320), nullable=False, server_default=""),
        sa.Column("from_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("to_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification", sa.String(32), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("action_taken", sa.String(32), nullable=False, server_default="none"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("account_id", "folder", "uid", name="uq_mail_account_folder_uid"),
    )
    op.create_index(
        "ix_mail_messages_account_created", "mail_messages", ["account_id", "created_at"]
    )
    op.create_index("ix_mail_messages_classification", "mail_messages", ["classification"])

    op.create_table(
        "mail_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mail_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "in_reply_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mail_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("to_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_mail_drafts_account_status", "mail_drafts", ["account_id", "status"])


def downgrade() -> None:
    op.drop_table("mail_drafts")
    op.drop_table("mail_messages")
    op.drop_table("mail_accounts")
