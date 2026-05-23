"""Synchronisation d'un compte : fetch IMAP → analyse IA → actions → brouillons.

Garde-fous : on ne supprime jamais (déplacement réversible vers le dossier spam),
on ne fait qu'écrire des brouillons `pending` (jamais d'envoi ici).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import MailAccount, MailDraft, MailMessage, User
from spouet.mail import imap_client, llm
from spouet.mail.imap_client import ImapParams
from spouet.nodes.router import NoSuitableNodeError, list_available_models
from spouet.realtime.hub import publish, user_channel
from spouet.secrets import store as secrets_store

logger = get_logger(__name__)

# Pas de réponse auto sur ces catégories, même si needs_reply.
_NO_REPLY_CLASSES = {"spam", "newsletter", "notification"}


def _imap_params(account: MailAccount, password: str) -> ImapParams:
    return ImapParams(
        host=account.imap_host,
        port=account.imap_port,
        ssl=account.imap_ssl,
        username=account.username,
        password=password,
    )


async def _resolve_model(db: AsyncSession, account: MailAccount) -> str | None:
    user = await db.get(User, account.user_id)
    if user and user.default_model:
        return user.default_model
    models = await list_available_models(db)
    return str(models[0]["name"]) if models else None


async def sync_account(db: AsyncSession, account: MailAccount) -> dict[str, Any]:
    try:
        password = await secrets_store.get_value(
            db, scope=f"mail:{account.id}", key="password"
        )
    except secrets_store.SecretMissingError:
        account.last_error = "Mot de passe absent du coffre."
        await db.commit()
        return {"error": account.last_error}

    params = _imap_params(account, password)
    try:
        fetched, max_uid = await asyncio.to_thread(
            imap_client.fetch_new, params, folder="INBOX", last_uid=account.last_uid, limit=30
        )
    except Exception as e:  # noqa: BLE001
        account.last_error = f"IMAP: {e}"
        await db.commit()
        logger.warning("mail.fetch_failed", account=str(account.id), error=str(e))
        return {"error": account.last_error}

    model = await _resolve_model(db, account) if account.auto_classify else None
    new_count = 0
    spam_moves: list[tuple[int, str]] = []

    for fm in fetched:
        already = await db.scalar(
            select(MailMessage.id).where(
                MailMessage.account_id == account.id,
                MailMessage.folder == "INBOX",
                MailMessage.uid == fm.uid,
            )
        )
        if already:
            continue

        row = MailMessage(
            account_id=account.id,
            uid=fm.uid,
            folder="INBOX",
            message_id=fm.message_id,
            from_addr=fm.from_addr[:320],
            from_name=fm.from_name[:255],
            to_addrs=fm.to_addrs,
            subject=fm.subject,
            snippet=(fm.body_text or "")[:280],
            body_text=fm.body_text,
            received_at=fm.received_at,
        )

        if model:
            try:
                res = await llm.classify(
                    db,
                    model=model,
                    sender=f"{fm.from_name} <{fm.from_addr}>",
                    subject=fm.subject,
                    body=fm.body_text,
                )
                row.classification = res["classification"]
                row.importance = res["importance"]
                row.needs_reply = res["needs_reply"]
                row.summary = res["summary"]
            except NoSuitableNodeError:
                model = None  # plus aucun node LLM dispo : on cesse de classifier
            except Exception as e:  # noqa: BLE001
                logger.warning("mail.classify_failed", error=str(e))

        db.add(row)
        await db.flush()
        new_count += 1

        if account.auto_trash_spam and row.classification == "spam":
            spam_moves.append((fm.uid, account.spam_folder))
            row.action_taken = "trashed"

        if (
            account.auto_draft_replies
            and model
            and row.needs_reply
            and row.classification not in _NO_REPLY_CLASSES
        ):
            try:
                body = await llm.draft_reply(db, model=model, account=account, message=row)
                if body.strip():
                    subj = fm.subject or "(sans objet)"
                    if not subj.lower().startswith("re"):
                        subj = f"Re: {subj}"
                    db.add(
                        MailDraft(
                            account_id=account.id,
                            in_reply_to_id=row.id,
                            to_addrs=fm.from_addr,
                            subject=subj[:998],
                            body=body,
                            status="pending",
                        )
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("mail.draft_failed", error=str(e))

    if spam_moves:
        try:
            await asyncio.to_thread(
                imap_client.move_messages, params, spam_moves, folder="INBOX"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("mail.move_failed", error=str(e))

    if max_uid is not None:
        account.last_uid = max_uid
    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = None
    await db.commit()

    if new_count:
        await publish(
            user_channel(account.user_id),
            "mail_sync",
            {"account_id": str(account.id), "new": new_count},
        )
    return {"new": new_count, "spam_moved": len(spam_moves)}
