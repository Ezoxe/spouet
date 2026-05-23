"""Routes Mail : comptes IMAP/SMTP, messages classés, brouillons à valider.

L'envoi SMTP n'a lieu QUE via POST /drafts/{id}/send (action explicite = la
validation HITL). La synchro/le tri tournent en tâche Celery périodique.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.logging import get_logger
from spouet.db.models import MailAccount, MailDraft, MailMessage
from spouet.mail import imap_client, smtp_client
from spouet.mail.imap_client import ImapParams
from spouet.secrets import store as secrets_store
from spouet.workers.app import celery_app

router = APIRouter()
logger = get_logger(__name__)


def _secret_scope(account_id: UUID) -> str:
    return f"mail:{account_id}"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MailAccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    imap_host: str = Field(min_length=1)
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_host: str = Field(min_length=1)
    smtp_port: int = 465
    smtp_ssl: bool = True
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    auto_classify: bool = True
    auto_trash_spam: bool = False
    spam_folder: str = "Junk"
    auto_draft_replies: bool = True
    signature: str = ""


class MailAccountPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_ssl: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_ssl: bool | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool | None = None
    auto_classify: bool | None = None
    auto_trash_spam: bool | None = None
    spam_folder: str | None = None
    auto_draft_replies: bool | None = None
    signature: str | None = None


class MailAccountOut(BaseModel):
    id: str
    name: str
    email: str
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    username: str
    enabled: bool
    auto_classify: bool
    auto_trash_spam: bool
    spam_folder: str
    auto_draft_replies: bool
    signature: str
    last_sync_at: datetime | None
    last_error: str | None


class MailMessageOut(BaseModel):
    id: str
    account_id: str
    from_addr: str
    from_name: str
    subject: str
    snippet: str
    classification: str | None
    importance: int
    needs_reply: bool
    summary: str
    is_read: bool
    action_taken: str
    received_at: datetime | None
    created_at: datetime


class MailDraftOut(BaseModel):
    id: str
    account_id: str
    in_reply_to_id: str | None
    to_addrs: str
    subject: str
    body: str
    status: str
    error: str | None
    created_at: datetime


class MailDraftPatch(BaseModel):
    subject: str | None = None
    body: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _account_out(a: MailAccount) -> MailAccountOut:
    return MailAccountOut(
        id=str(a.id),
        name=a.name,
        email=a.email,
        imap_host=a.imap_host,
        imap_port=a.imap_port,
        imap_ssl=a.imap_ssl,
        smtp_host=a.smtp_host,
        smtp_port=a.smtp_port,
        smtp_ssl=a.smtp_ssl,
        username=a.username,
        enabled=a.enabled,
        auto_classify=a.auto_classify,
        auto_trash_spam=a.auto_trash_spam,
        spam_folder=a.spam_folder,
        auto_draft_replies=a.auto_draft_replies,
        signature=a.signature,
        last_sync_at=a.last_sync_at,
        last_error=a.last_error,
    )


async def _owned_account(db: DbSession, user: CurrentUser, account_id: UUID) -> MailAccount:
    acc = await db.get(MailAccount, account_id)
    if acc is None or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable")
    return acc


# ---------------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------------


@router.get("/accounts", response_model=list[MailAccountOut])
async def list_accounts(user: CurrentUser, db: DbSession) -> list[MailAccountOut]:
    rows = (
        await db.execute(
            select(MailAccount)
            .where(MailAccount.user_id == user.id)
            .order_by(MailAccount.created_at)
        )
    ).scalars().all()
    return [_account_out(a) for a in rows]


@router.post("/accounts", response_model=MailAccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(payload: MailAccountIn, user: CurrentUser, db: DbSession) -> MailAccountOut:
    acc = MailAccount(
        user_id=user.id,
        name=payload.name,
        email=payload.email,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        imap_ssl=payload.imap_ssl,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_ssl=payload.smtp_ssl,
        username=payload.username,
        auto_classify=payload.auto_classify,
        auto_trash_spam=payload.auto_trash_spam,
        spam_folder=payload.spam_folder or "Junk",
        auto_draft_replies=payload.auto_draft_replies,
        signature=payload.signature,
    )
    db.add(acc)
    await db.flush()
    await secrets_store.upsert(
        db,
        scope=_secret_scope(acc.id),
        key="password",
        value=payload.password,
        description=f"Mot de passe mail {acc.email}",
    )
    await db.refresh(acc)
    return _account_out(acc)


@router.patch("/accounts/{account_id}", response_model=MailAccountOut)
async def patch_account(
    account_id: UUID, payload: MailAccountPatch, user: CurrentUser, db: DbSession
) -> MailAccountOut:
    acc = await _owned_account(db, user, account_id)
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(acc, field, value)
    if password:
        await secrets_store.upsert(
            db, scope=_secret_scope(acc.id), key="password", value=password
        )
    await db.commit()
    await db.refresh(acc)
    return _account_out(acc)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: UUID, user: CurrentUser, db: DbSession) -> None:
    acc = await _owned_account(db, user, account_id)
    await secrets_store.delete(db, scope=_secret_scope(acc.id), key="password")
    await db.delete(acc)
    await db.commit()


@router.post("/accounts/{account_id}/test")
async def test_account(account_id: UUID, user: CurrentUser, db: DbSession) -> dict:
    acc = await _owned_account(db, user, account_id)
    try:
        password = await secrets_store.get_value(db, scope=_secret_scope(acc.id), key="password")
    except secrets_store.SecretMissingError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe absent du coffre")

    result: dict[str, object] = {"imap_ok": False, "smtp_ok": False, "error": None}
    try:
        await asyncio.to_thread(
            imap_client.check_connection,
            ImapParams(acc.imap_host, acc.imap_port, acc.imap_ssl, acc.username, password),
        )
        result["imap_ok"] = True
    except Exception as e:  # noqa: BLE001
        result["error"] = f"IMAP: {e}"
    try:
        await asyncio.to_thread(
            smtp_client.check_connection,
            host=acc.smtp_host,
            port=acc.smtp_port,
            ssl=acc.smtp_ssl,
            username=acc.username,
            password=password,
        )
        result["smtp_ok"] = True
    except Exception as e:  # noqa: BLE001
        prev = result["error"]
        result["error"] = f"{prev + ' · ' if prev else ''}SMTP: {e}"
    return result


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(user: CurrentUser) -> dict:
    """Lance un cycle de synchro de toutes les boîtes (tâche Celery)."""
    celery_app.send_task("spouet.workers.tasks.sync_mail_accounts")
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.get("/messages", response_model=list[MailMessageOut])
async def list_messages(
    user: CurrentUser,
    db: DbSession,
    account_id: UUID | None = None,
    classification: str | None = None,
    limit: int = 100,
) -> list[MailMessageOut]:
    stmt = (
        select(MailMessage)
        .join(MailAccount, MailAccount.id == MailMessage.account_id)
        .where(MailAccount.user_id == user.id)
        .order_by(MailMessage.created_at.desc())
        .limit(max(1, min(limit, 300)))
    )
    if account_id is not None:
        stmt = stmt.where(MailMessage.account_id == account_id)
    if classification:
        stmt = stmt.where(MailMessage.classification == classification)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        MailMessageOut(
            id=str(m.id),
            account_id=str(m.account_id),
            from_addr=m.from_addr,
            from_name=m.from_name,
            subject=m.subject,
            snippet=m.snippet,
            classification=m.classification,
            importance=m.importance,
            needs_reply=m.needs_reply,
            summary=m.summary,
            is_read=m.is_read,
            action_taken=m.action_taken,
            received_at=m.received_at,
            created_at=m.created_at,
        )
        for m in rows
    ]


# ---------------------------------------------------------------------------
# Brouillons (validation HITL)
# ---------------------------------------------------------------------------


def _draft_out(d: MailDraft) -> MailDraftOut:
    return MailDraftOut(
        id=str(d.id),
        account_id=str(d.account_id),
        in_reply_to_id=str(d.in_reply_to_id) if d.in_reply_to_id else None,
        to_addrs=d.to_addrs,
        subject=d.subject,
        body=d.body,
        status=d.status,
        error=d.error,
        created_at=d.created_at,
    )


async def _owned_draft(db: DbSession, user: CurrentUser, draft_id: UUID) -> MailDraft:
    draft = await db.get(MailDraft, draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brouillon introuvable")
    acc = await db.get(MailAccount, draft.account_id)
    if acc is None or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brouillon introuvable")
    return draft


@router.get("/drafts", response_model=list[MailDraftOut])
async def list_drafts(
    user: CurrentUser, db: DbSession, status_filter: str | None = None
) -> list[MailDraftOut]:
    stmt = (
        select(MailDraft)
        .join(MailAccount, MailAccount.id == MailDraft.account_id)
        .where(MailAccount.user_id == user.id)
        .order_by(MailDraft.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(MailDraft.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return [_draft_out(d) for d in rows]


@router.patch("/drafts/{draft_id}", response_model=MailDraftOut)
async def patch_draft(
    draft_id: UUID, payload: MailDraftPatch, user: CurrentUser, db: DbSession
) -> MailDraftOut:
    draft = await _owned_draft(db, user, draft_id)
    if draft.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Brouillon non modifiable")
    if payload.subject is not None:
        draft.subject = payload.subject
    if payload.body is not None:
        draft.body = payload.body
    await db.commit()
    await db.refresh(draft)
    return _draft_out(draft)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_draft(draft_id: UUID, user: CurrentUser, db: DbSession) -> None:
    draft = await _owned_draft(db, user, draft_id)
    await db.delete(draft)
    await db.commit()


@router.post("/drafts/{draft_id}/send", response_model=MailDraftOut)
async def send_draft(draft_id: UUID, user: CurrentUser, db: DbSession) -> MailDraftOut:
    """Validation HITL : approuve et envoie le brouillon via SMTP."""
    draft = await _owned_draft(db, user, draft_id)
    if draft.status == "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà envoyé")
    acc = await db.get(MailAccount, draft.account_id)
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable")
    try:
        password = await secrets_store.get_value(db, scope=_secret_scope(acc.id), key="password")
    except secrets_store.SecretMissingError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe absent du coffre")

    in_reply_to = None
    if draft.in_reply_to_id:
        msg = await db.get(MailMessage, draft.in_reply_to_id)
        in_reply_to = msg.message_id if msg else None

    body = draft.body + (f"\n\n{acc.signature}" if acc.signature and acc.signature not in draft.body else "")
    try:
        await asyncio.to_thread(
            smtp_client.send_email,
            host=acc.smtp_host,
            port=acc.smtp_port,
            ssl=acc.smtp_ssl,
            username=acc.username,
            password=password,
            from_addr=acc.email,
            to_addrs=draft.to_addrs,
            subject=draft.subject,
            body=body,
            in_reply_to=in_reply_to,
        )
    except Exception as e:  # noqa: BLE001
        draft.status = "failed"
        draft.error = str(e)
        await db.commit()
        logger.warning("mail.send_failed", draft=str(draft.id), error=str(e))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Envoi échoué : {e}")

    draft.status = "sent"
    draft.sent_at = datetime.now(timezone.utc)
    draft.error = None
    await db.commit()
    await db.refresh(draft)
    logger.info("mail.sent", draft=str(draft.id), to=draft.to_addrs)
    return _draft_out(draft)
