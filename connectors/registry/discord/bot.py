"""Connector Discord pour Spouet.

Ouvre une connexion WebSocket vers le backend Spouet et bridge :

- inbound  : chaque message Discord (channel ou DM) → POST WS ``{kind: 'message'}``
- outbound : commandes reçues du backend (``send_message``, ``typing``, ``react``)
  exécutées contre Discord.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import discord
import websockets


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"[fatal] missing env {name}", file=sys.stderr, flush=True)
        sys.exit(2)
    return val


CONFIG: dict[str, Any] = json.loads(os.environ.get("SPOUET_CONFIG_JSON") or "{}")
BACKEND = _required("SPOUET_BACKEND_URL").rstrip("/")
CONN_ID = _required("SPOUET_CONNECTOR_ID")
CONN_TOKEN = _required("SPOUET_CONNECTOR_TOKEN")
DISCORD_TOKEN = _required("DISCORD_TOKEN")

ALLOWED_CHANNELS: set[str] = {str(c) for c in (CONFIG.get("allowed_channels") or [])}
PREFIX: str = (CONFIG.get("trigger_prefix") or "").strip()
RESPOND_DM: bool = bool(CONFIG.get("respond_dm", True))

DISCORD_LIMIT = 1900  # marge sous la limite 2000

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# La WS est partagée par les handlers Discord (event loop unique).
_ws: websockets.WebSocketClientProtocol | None = None


def _split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    if text:
        parts.append(text)
    return parts


async def _resolve_channel(external_id: str) -> Any:
    if external_id.startswith("channel:"):
        cid = int(external_id.split(":", 1)[1])
        ch = client.get_channel(cid)
        if ch is None:
            try:
                ch = await client.fetch_channel(cid)
            except discord.NotFound:
                return None
        return ch
    if external_id.startswith("dm:"):
        uid = int(external_id.split(":", 1)[1])
        user = client.get_user(uid)
        if user is None:
            try:
                user = await client.fetch_user(uid)
            except discord.NotFound:
                return None
        return user.dm_channel or await user.create_dm()
    return None


async def _handle_outbound(data: dict[str, Any]) -> None:
    kind = data.get("kind")
    external_id = str(data.get("external_id") or "")
    try:
        if kind == "send_message":
            channel = await _resolve_channel(external_id)
            if channel is None:
                print(f"[warn] channel not found: {external_id}", flush=True)
                return
            content = str(data.get("content") or "")
            reply_to = data.get("reply_to")
            reference = None
            if reply_to and external_id.startswith("channel:"):
                try:
                    reference = await channel.fetch_message(int(reply_to))
                except Exception:  # noqa: BLE001
                    reference = None
            chunks = _split_message(content) if content else ["(vide)"]
            for i, chunk in enumerate(chunks):
                await channel.send(chunk, reference=reference if i == 0 else None)
        elif kind == "typing":
            channel = await _resolve_channel(external_id)
            if channel is not None:
                async with channel.typing():
                    await asyncio.sleep(2)
        elif kind == "react":
            channel = await _resolve_channel(external_id)
            msg_id = data.get("message_id")
            emoji = data.get("emoji")
            if channel is None or not msg_id or not emoji:
                return
            try:
                msg = await channel.fetch_message(int(msg_id))
                await msg.add_reaction(str(emoji))
            except Exception as e:  # noqa: BLE001
                print(f"[warn] react failed: {e}", flush=True)
        else:
            print(f"[warn] unsupported outbound kind: {kind}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[error] outbound failed ({kind}): {e}", flush=True)


@client.event
async def on_ready() -> None:
    print(f"[ok] discord ready as {client.user}", flush=True)


@client.event
async def on_message(msg: discord.Message) -> None:
    if msg.author.bot or _ws is None:
        return

    is_dm = isinstance(msg.channel, discord.DMChannel)
    if is_dm:
        if not RESPOND_DM:
            return
        external_id = f"dm:{msg.author.id}"
        external_label = f"DM @{msg.author.name}"
    else:
        cid = str(msg.channel.id)
        if ALLOWED_CHANNELS and cid not in ALLOWED_CHANNELS:
            return
        if PREFIX and not msg.content.startswith(PREFIX) and (
            client.user not in msg.mentions
        ):
            return
        external_id = f"channel:{cid}"
        external_label = f"#{getattr(msg.channel, 'name', cid)}"

    text = msg.content
    if PREFIX and text.startswith(PREFIX):
        text = text[len(PREFIX):].strip()
    if client.user in msg.mentions:
        text = text.replace(f"<@{client.user.id}>", "").strip()
    if not text:
        return

    payload = {
        "kind": "message",
        "external_id": external_id,
        "external_label": external_label,
        "content": text,
        "reply_to": str(msg.id),
        "metadata": {
            "author_id": str(msg.author.id),
            "author_name": msg.author.name,
            "guild_id": str(msg.guild.id) if msg.guild else None,
            "guild_name": msg.guild.name if msg.guild else None,
        },
    }
    try:
        await _ws.send(json.dumps(payload, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] inbound push failed: {e}", flush=True)


async def _ws_outbound_reader(ws: websockets.WebSocketClientProtocol) -> None:
    async for raw in ws:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        asyncio.create_task(_handle_outbound(data))


async def _ws_loop() -> None:
    global _ws
    url = f"{BACKEND}/ws/connectors/{CONN_ID}?token={CONN_TOKEN}"
    while True:
        try:
            async with websockets.connect(url, max_size=2_000_000, ping_interval=20) as ws:
                _ws = ws
                print(f"[ok] backend ws connected: {url}", flush=True)
                await ws.send(json.dumps({"kind": "ping"}))
                await _ws_outbound_reader(ws)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] backend ws disconnected: {e}, retry in 5s", flush=True)
        finally:
            _ws = None
        await asyncio.sleep(5)


async def main() -> None:
    asyncio.create_task(_ws_loop())
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
