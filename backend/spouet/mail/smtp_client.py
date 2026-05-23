"""Envoi SMTP synchrone (exécuté en threadpool depuis les tâches async)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from spouet.core.logging import get_logger

logger = get_logger(__name__)


def send_email(
    *,
    host: str,
    port: int,
    ssl: bool,
    username: str,
    password: str,
    from_addr: str,
    to_addrs: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
) -> None:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addrs
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    if ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPException:
                pass
            server.login(username, password)
            server.send_message(msg)


def check_connection(
    *, host: str, port: int, ssl: bool, username: str, password: str
) -> None:
    """Teste la connexion + login SMTP (lève en cas d'échec)."""
    if ssl:
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            server.login(username, password)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPException:
                pass
            server.login(username, password)
