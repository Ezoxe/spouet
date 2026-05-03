"""CLI `spouet-admin` : bootstrap, tokens, tools, secrets, connectors."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer
from sqlalchemy import select

from spouet.connectors import manager as connector_manager
from spouet.connectors.manifest import (
    load_connector_manifest,
)
from spouet.core.security import generate_token, hash_token
from spouet.db import async_session_factory
from spouet.db.models import Connector, Tool, User
from spouet.secrets import store as secrets_store
from spouet.tools.manifest import ManifestError, load_manifest

app = typer.Typer(help="Spouet admin — bootstrap, tokens, tools.", no_args_is_help=True)
tools_app = typer.Typer(help="Gestion des tools custom", no_args_is_help=True)
secrets_app = typer.Typer(help="Coffre de secrets chiffrés", no_args_is_help=True)
connectors_app = typer.Typer(help="Connectors persistants", no_args_is_help=True)
app.add_typer(tools_app, name="tools")
app.add_typer(secrets_app, name="secrets")
app.add_typer(connectors_app, name="connectors")


# ---------------------------------------------------------------------------
# Users / tokens
# ---------------------------------------------------------------------------


@app.command("create-token")
def create_token(email: str = typer.Option(..., "--email")) -> None:
    """Crée un user (si nouveau) et génère un token API. Affiché une seule fois."""
    asyncio.run(_create_token_async(email))


async def _create_token_async(email: str) -> None:
    async with async_session_factory()() as db:
        user = await db.scalar(select(User).where(User.email == email))
        token = generate_token()
        if user is None:
            user = User(email=email, api_token_hash=hash_token(token))
            db.add(user)
            action = "created"
        else:
            user.api_token_hash = hash_token(token)
            action = "rotated"
        await db.commit()
    typer.echo(f"User {email} {action}.")
    typer.echo(f"Token (à conserver, non récupérable) : {token}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tools_app.command("install")
def install_tool(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    build_image: bool = typer.Option(False, "--build", help="Builder l'image Docker locale"),
) -> None:
    """Installe un tool depuis un dossier contenant un manifest.yaml."""
    try:
        manifest = load_manifest(path)
    except ManifestError as e:
        typer.echo(f"Erreur manifest : {e}", err=True)
        raise typer.Exit(1) from e

    if build_image:
        import subprocess

        dockerfile = path / "Dockerfile"
        if not dockerfile.exists():
            typer.echo("Dockerfile manquant", err=True)
            raise typer.Exit(1)
        cmd = ["docker", "build", "-t", manifest.image, str(path)]
        typer.echo(f"$ {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    asyncio.run(_install_tool_async(manifest))


async def _install_tool_async(manifest) -> None:  # type: ignore[no-untyped-def]
    async with async_session_factory()() as db:
        existing = await db.scalar(select(Tool).where(Tool.slug == manifest.slug))
        if existing is None:
            tool = Tool(
                slug=manifest.slug,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                image=manifest.image,
                manifest_json=manifest.raw,
                network_mode=manifest.network,
                timeout_s=manifest.timeout_s,
                requires_approval=manifest.requires_approval,
            )
            db.add(tool)
            action = "installed"
        else:
            existing.name = manifest.name
            existing.version = manifest.version
            existing.description = manifest.description
            existing.image = manifest.image
            existing.manifest_json = manifest.raw
            existing.network_mode = manifest.network
            existing.timeout_s = manifest.timeout_s
            existing.requires_approval = manifest.requires_approval
            action = "updated"
        await db.commit()
    typer.echo(f"Tool {manifest.slug} {action}.")


@tools_app.command("list")
def list_tools() -> None:
    asyncio.run(_list_tools_async())


async def _list_tools_async() -> None:
    async with async_session_factory()() as db:
        rows = (await db.execute(select(Tool).order_by(Tool.slug))).scalars().all()
    typer.echo(
        json.dumps(
            [
                {
                    "slug": t.slug,
                    "version": t.version,
                    "image": t.image,
                    "enabled": t.enabled,
                    "network": t.network_mode,
                }
                for t in rows
            ],
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@secrets_app.command("set")
def secret_set(
    scope: str = typer.Option(..., "--scope", help="Ex: connector:discord-bot, global, tool:foo"),
    key: str = typer.Option(..., "--key"),
    value: str | None = typer.Option(
        None,
        "--value",
        help="Valeur en clair (NON RECOMMANDÉ : visible dans l'historique shell). Sinon lue depuis stdin.",
    ),
    description: str = typer.Option("", "--description"),
) -> None:
    """Stocke un secret chiffré. Si ``--value`` n'est pas fourni, lit la valeur sur stdin
    (recommandé : ``echo -n "$TOKEN" | spouet-admin secrets set --scope ... --key ...``)."""
    if value is None:
        value = sys.stdin.read().rstrip("\n")
    if not value:
        typer.echo("valeur vide", err=True)
        raise typer.Exit(1)
    asyncio.run(_secret_set_async(scope, key, value, description))


async def _secret_set_async(scope: str, key: str, value: str, description: str) -> None:
    async with async_session_factory()() as db:
        await secrets_store.upsert(
            db, scope=scope, key=key, value=value, description=description
        )
    typer.echo(f"OK : {scope}/{key} ({secrets_store.preview(value)})")


@secrets_app.command("list")
def secret_list(
    scope: str | None = typer.Option(None, "--scope"),
) -> None:
    asyncio.run(_secret_list_async(scope))


async def _secret_list_async(scope: str | None) -> None:
    async with async_session_factory()() as db:
        rows = await secrets_store.list_for_scope(db, scope)
    typer.echo(
        json.dumps(
            [
                {
                    "scope": r.scope,
                    "key": r.key,
                    "description": r.description,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
            indent=2,
        )
    )


@secrets_app.command("delete")
def secret_delete(
    scope: str = typer.Option(..., "--scope"),
    key: str = typer.Option(..., "--key"),
) -> None:
    asyncio.run(_secret_delete_async(scope, key))


async def _secret_delete_async(scope: str, key: str) -> None:
    async with async_session_factory()() as db:
        ok = await secrets_store.delete(db, scope=scope, key=key)
    typer.echo("supprimé" if ok else "introuvable")


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


@connectors_app.command("install")
def connector_install(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    email: str = typer.Option(..., "--email", help="Email du user propriétaire"),
) -> None:
    try:
        manifest = load_connector_manifest(path)
    except ManifestError as e:
        typer.echo(f"Erreur manifest : {e}", err=True)
        raise typer.Exit(1) from e
    asyncio.run(_connector_install_async(manifest, email))


async def _connector_install_async(manifest, email: str) -> None:  # type: ignore[no-untyped-def]
    async with async_session_factory()() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            typer.echo(f"User {email} introuvable. Créer d'abord avec create-token.", err=True)
            raise typer.Exit(1)
        existing = await db.scalar(select(Connector).where(Connector.slug == manifest.slug))
        token = generate_token()
        hashed = hash_token(token)
        if existing is None:
            row = Connector(
                user_id=user.id,
                slug=manifest.slug,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                image=manifest.image,
                manifest_json=manifest.raw,
                config_json={},
                auth_token_hash=hashed,
            )
            db.add(row)
            action = "installed"
        else:
            existing.name = manifest.name
            existing.version = manifest.version
            existing.description = manifest.description
            existing.image = manifest.image
            existing.manifest_json = manifest.raw
            existing.auth_token_hash = hashed
            row = existing
            action = "updated"
        await db.commit()
    typer.echo(f"Connector {manifest.slug} {action}.")
    typer.echo("→ Pense à stocker les secrets requis :")
    for env, ref in (manifest.secrets or {}).items():
        typer.echo(f"   spouet-admin secrets set --scope {ref.split('/')[0]} --key {ref.split('/')[1]}   # injecté en {env}")


@connectors_app.command("start")
def connector_start(
    slug: str = typer.Argument(..., help="Slug du connector"),
) -> None:
    asyncio.run(_connector_start_async(slug))


async def _connector_start_async(slug: str) -> None:
    async with async_session_factory()() as db:
        row = await db.scalar(select(Connector).where(Connector.slug == slug))
        if row is None:
            typer.echo(f"Connector '{slug}' introuvable", err=True)
            raise typer.Exit(1)
        token = generate_token()
        row.auth_token_hash = hash_token(token)
        await db.commit()
        res = await connector_manager.start(db, row, raw_token=token)
    typer.echo(f"State: {res.state} container_id={res.container_id} error={res.error}")


@connectors_app.command("stop")
def connector_stop(slug: str = typer.Argument(...)) -> None:
    asyncio.run(_connector_stop_async(slug))


async def _connector_stop_async(slug: str) -> None:
    async with async_session_factory()() as db:
        row = await db.scalar(select(Connector).where(Connector.slug == slug))
        if row is None:
            typer.echo(f"Connector '{slug}' introuvable", err=True)
            raise typer.Exit(1)
        res = await connector_manager.stop(db, row)
    typer.echo(f"State: {res.state}")


@connectors_app.command("list")
def connector_list() -> None:
    asyncio.run(_connector_list_async())


async def _connector_list_async() -> None:
    async with async_session_factory()() as db:
        rows = (await db.execute(select(Connector).order_by(Connector.slug))).scalars().all()
    typer.echo(
        json.dumps(
            [
                {
                    "slug": r.slug,
                    "image": r.image,
                    "enabled": r.enabled,
                    "status": r.status,
                    "container_id": r.container_id,
                    "last_error": r.last_error,
                }
                for r in rows
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
