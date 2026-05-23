"""Client IMAP synchrone (exécuté en threadpool depuis les tâches async).

Volontairement défensif :
- lecture en `readonly` (on ne marque pas les mails comme lus en les analysant) ;
- déplacement de messages **sans suppression définitive** (UID MOVE, ou COPY +
  \\Deleted + EXPUNGE ciblé) — un spam atterrit dans le dossier Junk, réversible.
"""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from spouet.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ImapParams:
    host: str
    port: int
    ssl: bool
    username: str
    password: str


@dataclass
class FetchedMessage:
    uid: int
    message_id: str | None
    from_addr: str
    from_name: str
    to_addrs: str
    subject: str
    body_text: str
    received_at: datetime | None


def _connect(p: ImapParams) -> imaplib.IMAP4:
    if p.ssl:
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(p.host, p.port)
    else:
        conn = imaplib.IMAP4(p.host, p.port)
        try:
            conn.starttls()
        except Exception:  # noqa: BLE001
            pass
    conn.login(p.username, p.password)
    return conn


def _decode(s: str | None) -> str:
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:  # noqa: BLE001
        return s


def _part_text(part: Message) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _extract_body(msg: Message) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or ""):
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = _part_text(part)
            elif ctype == "text/html" and not html:
                html = _part_text(part)
    elif msg.get_content_type() == "text/html":
        html = _part_text(msg)
    else:
        plain = _part_text(msg)
    if plain.strip():
        return plain.strip()
    return _strip_html(html).strip()


def fetch_new(
    p: ImapParams,
    *,
    folder: str = "INBOX",
    last_uid: int | None,
    limit: int = 30,
) -> tuple[list[FetchedMessage], int | None]:
    """Récupère les messages d'UID strictement supérieur à `last_uid`."""
    conn = _connect(p)
    out: list[FetchedMessage] = []
    max_uid = last_uid
    try:
        conn.select(folder, readonly=True)
        start = (last_uid or 0) + 1
        typ, data = conn.uid("search", None, f"UID {start}:*")
        if typ != "OK" or not data or not data[0]:
            return out, max_uid
        uids = sorted(
            u for u in (int(x) for x in data[0].split()) if last_uid is None or u > last_uid
        )[:limit]
        for uid in uids:
            typ, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(bytes(raw))
            name, addr = parseaddr(msg.get("From", ""))
            try:
                received = parsedate_to_datetime(msg.get("Date"))
                if received and received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                received = None
            out.append(
                FetchedMessage(
                    uid=uid,
                    message_id=(_decode(msg.get("Message-ID")) or None),
                    from_addr=addr,
                    from_name=_decode(name),
                    to_addrs=_decode(msg.get("To")),
                    subject=_decode(msg.get("Subject")),
                    body_text=_extract_body(msg),
                    received_at=received,
                )
            )
            max_uid = max(max_uid or 0, uid)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return out, max_uid


def move_messages(
    p: ImapParams, moves: list[tuple[int, str]], *, folder: str = "INBOX"
) -> int:
    """Déplace des (UID -> dossier cible). Jamais de suppression définitive."""
    if not moves:
        return 0
    conn = _connect(p)
    moved = 0
    try:
        conn.select(folder)
        for uid, dest in moves:
            try:
                conn.create(dest)
            except Exception:  # noqa: BLE001
                pass  # le dossier existe déjà
            if _move_one(conn, uid, dest):
                moved += 1
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return moved


def _move_one(conn: imaplib.IMAP4, uid: int, dest: str) -> bool:
    # 1. UID MOVE (RFC 6851), atomique, si supporté par le serveur.
    try:
        typ, _ = conn.uid("MOVE", str(uid), dest)
        if typ == "OK":
            return True
    except Exception:  # noqa: BLE001
        pass
    # 2. Repli : COPY puis marque \Deleted + EXPUNGE ciblé (UIDPLUS).
    try:
        typ, _ = conn.uid("COPY", str(uid), dest)
        if typ != "OK":
            return False
        conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
        try:
            conn.uid("EXPUNGE", str(uid))  # UIDPLUS : ne purge que cet UID
        except Exception:  # noqa: BLE001
            pass  # sans UIDPLUS, le mail reste \Deleted (toujours réversible)
        return True
    except Exception:  # noqa: BLE001
        return False


def check_connection(p: ImapParams) -> None:
    """Teste la connexion + login (lève en cas d'échec). Pour le bouton 'Tester'."""
    conn = _connect(p)
    try:
        conn.select("INBOX", readonly=True)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
