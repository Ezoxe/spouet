"""Loader des manifests de connectors (YAML).

Format ::

    slug: discord-bot
    name: Discord Bot
    version: 0.1.0
    image: spouet/connector-discord:0.1.0
    description: Bridge Discord ↔ Spouet
    network: bridge        # toujours bridge (sortie internet pour le service externe)
    mem_limit: 384m
    cpu_limit: 0.5
    secrets:
      DISCORD_TOKEN: connector:discord-bot/token
    config_schema:
      type: object
      required: [bot_persona]
      properties:
        bot_persona: { type: string }
        default_model: { type: string }
        allowed_channels: { type: array, items: { type: string } }
    inbound_kinds: [message]
    outbound_kinds: [send_message, react, typing]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from spouet.tools.manifest import ManifestError

REQUIRED_FIELDS = {"slug", "name", "version", "image"}


@dataclass
class ConnectorManifest:
    slug: str
    name: str
    version: str
    image: str
    description: str = ""
    network: str = "bridge"
    mem_limit: str = "384m"
    cpu_limit: float = 0.5
    secrets: dict[str, str] = field(default_factory=dict)
    config_schema: dict[str, Any] = field(default_factory=dict)
    inbound_kinds: list[str] = field(default_factory=lambda: ["message"])
    outbound_kinds: list[str] = field(default_factory=lambda: ["send_message"])
    raw: dict[str, Any] = field(default_factory=dict)


def load_connector_manifest(path: Path) -> ConnectorManifest:
    if path.is_dir():
        path = path / "manifest.yaml"
    if not path.exists():
        raise ManifestError(f"manifest not found at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be a YAML mapping")

    missing = REQUIRED_FIELDS - raw.keys()
    if missing:
        raise ManifestError(f"missing required fields: {sorted(missing)}")

    config_schema = raw.get("config_schema") or {"type": "object"}
    try:
        Draft202012Validator.check_schema(config_schema)
    except Exception as e:  # noqa: BLE001
        raise ManifestError(f"invalid config_schema: {e}") from e

    secrets_raw = raw.get("secrets") or {}
    if not isinstance(secrets_raw, dict):
        raise ManifestError("'secrets' doit être un mapping {ENV_VAR: 'scope/key'}")
    secrets = {str(k): str(v) for k, v in secrets_raw.items()}

    return ConnectorManifest(
        slug=str(raw["slug"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        image=str(raw["image"]),
        description=str(raw.get("description", "")),
        network=str(raw.get("network", "bridge")),
        mem_limit=str(raw.get("mem_limit", "384m")),
        cpu_limit=float(raw.get("cpu_limit", 0.5)),
        secrets=secrets,
        config_schema=config_schema,
        inbound_kinds=list(raw.get("inbound_kinds") or ["message"]),
        outbound_kinds=list(raw.get("outbound_kinds") or ["send_message"]),
        raw=raw,
    )


def validate_config(manifest: ConnectorManifest, config: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(manifest.config_schema)
    return [
        f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}"
        for e in validator.iter_errors(config)
    ]
