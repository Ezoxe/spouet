"""Loader / validator des manifests YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


REQUIRED_FIELDS = {"slug", "name", "version", "image", "input_schema"}


class ManifestError(ValueError):
    pass


# Modes réseau autorisés pour un tool :
#   none     → isolation totale (--network none), aucun accès réseau
#   bridge   → bridge Docker par défaut (sortie Internet, pas de DNS compose)
#   internal → réseau docker-compose Spouet (résout `backend`, `postgres`…) pour
#              les tools officiels qui interrogent l'API backend
ALLOWED_NETWORKS = ("none", "bridge", "internal")


@dataclass
class ToolManifest:
    slug: str
    name: str
    version: str
    image: str
    description: str = ""
    network: str = "none"  # 'none' | 'bridge' | 'internal'
    timeout_s: int = 30
    mem_limit: str = "256m"
    cpu_limit: float = 1.0
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)  # {ENV_VAR: 'scope/key'}
    env: dict[str, str] = field(default_factory=dict)  # env vars statiques (non-secrètes)
    # Override explicite du manifest (`requires_approval: true|false`). None =
    # comportement par défaut (dérivé du mode réseau).
    requires_approval_override: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_approval(self) -> bool:
        # Par défaut, tout accès réseau (Internet ou réseau interne) requiert une
        # validation HITL. Un manifest peut lever cette exigence explicitement via
        # `requires_approval: false` pour un outil de confiance dont la surface est
        # restreinte côté run.py (ex. net-check : commandes whitelistées, pas de
        # shell arbitraire). L'admin peut aussi ajuster par PATCH.
        if self.requires_approval_override is not None:
            return self.requires_approval_override
        return self.network != "none"


def load_manifest(path: Path) -> ToolManifest:
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

    network = raw.get("network", "none")
    if network not in ALLOWED_NETWORKS:
        raise ManifestError(
            f"network must be one of {ALLOWED_NETWORKS}, got {network!r}"
        )

    # Valide que l'input_schema est un schéma JSON valide
    try:
        Draft202012Validator.check_schema(raw["input_schema"])
    except Exception as e:  # noqa: BLE001
        raise ManifestError(f"invalid input_schema: {e}") from e

    if "output_schema" in raw:
        try:
            Draft202012Validator.check_schema(raw["output_schema"])
        except Exception as e:  # noqa: BLE001
            raise ManifestError(f"invalid output_schema: {e}") from e

    secrets_raw = raw.get("secrets") or {}
    if not isinstance(secrets_raw, dict):
        raise ManifestError("'secrets' doit être un mapping {ENV_VAR: 'scope/key'}")
    secrets: dict[str, str] = {}
    for env, ref in secrets_raw.items():
        if not isinstance(env, str) or not env.replace("_", "").isalnum() or not env[0].isalpha():
            raise ManifestError(
                f"nom d'env var invalide '{env}' (alphanumérique + _, doit commencer par une lettre)"
            )
        if not isinstance(ref, str) or "/" not in ref:
            raise ManifestError(f"référence secret invalide pour '{env}' (format 'scope/key')")
        secrets[env] = ref

    env_raw = raw.get("env") or {}
    if not isinstance(env_raw, dict):
        raise ManifestError("'env' doit être un mapping {ENV_VAR: 'valeur'}")
    env_static: dict[str, str] = {str(k): str(v) for k, v in env_raw.items()}

    ra_override = raw.get("requires_approval")
    if ra_override is not None and not isinstance(ra_override, bool):
        raise ManifestError("'requires_approval' doit être un booléen (true/false)")

    return ToolManifest(
        slug=str(raw["slug"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        image=str(raw["image"]),
        description=str(raw.get("description", "")),
        network=network,
        timeout_s=int(raw.get("timeout_s", 30)),
        mem_limit=str(raw.get("mem_limit", "256m")),
        cpu_limit=float(raw.get("cpu_limit", 1.0)),
        input_schema=raw["input_schema"],
        output_schema=raw.get("output_schema", {}),
        secrets=secrets,
        env=env_static,
        requires_approval_override=ra_override,
        raw=raw,
    )


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Retourne la liste des erreurs (vide si valide)."""
    validator = Draft202012Validator(schema)
    return [f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in validator.iter_errors(args)]
