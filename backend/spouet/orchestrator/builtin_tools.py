"""Tools « built-in » exécutés en-process (pas dans un conteneur Docker).

Sur le modèle de ``delegate_to_node`` (cf. chat_loop), ces tools sont déclarés
au LLM comme n'importe quel function-call, mais leur exécution est gérée
directement par l'orchestrator :

- ``web_search``   : recherche web rapide (SearXNG) — connaissance temps réel.
- ``show_visual``  : affiche une image / carte / fait à l'écran (overlay animé + inline).
- ``run_desktop_action`` : action bureau primitive (lancer une app, ouvrir une URL).
- ``run_macro``    : exécute une macro desktop enregistrée (« soirée Minecraft »).
- ``define_macro`` : enregistre une nouvelle macro (validation HITL).
- ``list_macros``  : liste les macros connues de l'utilisateur.

Les tools desktop (run_desktop_action / run_macro / define_macro) passent par le
pont :mod:`spouet.desktop.bridge` et ne sont exposés que si un client desktop
(app Tauri) est connecté — c'est la persona qui rend l'IA *capability-aware*.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import Conversation, DesktopMacro
from spouet.desktop import bridge, registry
from spouet.images import client as image_client
from spouet.images import storage as image_storage
from spouet.images.client import GenerateParams
from spouet.memory import files as memory_files
from spouet.nodes.router import NoSuitableNodeError, pick_image_node
from spouet.realtime.hub import publish, user_channel
from spouet.tools.approval import request_approval, wait_for_decision
from spouet.websearch import search as websearch_search

logger = get_logger(__name__)

# Tools toujours disponibles (n'exigent pas de client desktop).
WEB_SEARCH_SLUG = "web_search"
SHOW_VISUAL_SLUG = "show_visual"
LIST_MACROS_SLUG = "list_macros"
# Mémoire long-terme « fichiers .md » (toujours disponible).
MEMORY_LIST_SLUG = "memory_list"
MEMORY_READ_SLUG = "memory_read"
MEMORY_WRITE_SLUG = "memory_write"
MEMORY_DELETE_SLUG = "memory_delete"
# Tool conditionné à l'activation du moteur d'images (image-engine).
GENERATE_IMAGE_SLUG = "generate_image"
# Tools exigeant un client desktop connecté.
RUN_DESKTOP_ACTION_SLUG = "run_desktop_action"
RUN_MACRO_SLUG = "run_macro"
DEFINE_MACRO_SLUG = "define_macro"

_ALWAYS = {
    WEB_SEARCH_SLUG,
    SHOW_VISUAL_SLUG,
    LIST_MACROS_SLUG,
    MEMORY_LIST_SLUG,
    MEMORY_READ_SLUG,
    MEMORY_WRITE_SLUG,
    MEMORY_DELETE_SLUG,
}
_IMAGE_GATED = {GENERATE_IMAGE_SLUG}
_DESKTOP_GATED = {RUN_DESKTOP_ACTION_SLUG, RUN_MACRO_SLUG, DEFINE_MACRO_SLUG}
BUILTIN_SLUGS = _ALWAYS | _IMAGE_GATED | _DESKTOP_GATED

# Actions primitives autorisées dans une étape de macro / action directe.
ALLOWED_STEP_ACTIONS = ("launch_app", "open_url")
ALLOWED_WINDOW_MODES = ("normal", "maximized", "fullscreen")
MACRO_APPROVAL_TIMEOUT_S = 180
# Temps max d'attente d'une décision utilisateur pour autoriser une recherche web.
WEB_SEARCH_APPROVAL_TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# Définitions exposées au LLM
# ---------------------------------------------------------------------------

_DEF_WEB_SEARCH: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": WEB_SEARCH_SLUG,
        "description": (
            "Recherche des informations à jour sur Internet (counters de jeux, "
            "actualités, prix, définitions, documentation…). Utilise-le DÈS QUE "
            "la réponse dépend d'infos récentes ou que tu n'es pas certain. "
            "Mets kind='images' pour trouver une image (que tu pourras ensuite "
            "afficher avec show_visual)."
        ),
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Requête de recherche"},
                "kind": {
                    "type": "string",
                    "enum": ["web", "images"],
                    "description": "web (défaut) ou images",
                },
            },
        },
    },
}

_DEF_SHOW_VISUAL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SHOW_VISUAL_SLUG,
        "description": (
            "Affiche un visuel à l'écran de l'utilisateur (overlay animé) : une "
            "image (ex. la photo d'un counterpick trouvée via web_search), une "
            "carte d'info, ou un fait court. Idéal en complément d'une réponse "
            "vocale."
        ),
        "parameters": {
            "type": "object",
            "required": ["kind"],
            "properties": {
                "kind": {"type": "string", "enum": ["image", "card", "fact"]},
                "url": {"type": "string", "description": "URL de l'image (kind=image/card)"},
                "title": {"type": "string"},
                "text": {"type": "string", "description": "Texte de la carte / du fait"},
                "duration_ms": {
                    "type": "integer",
                    "description": "Durée d'affichage en ms (défaut 7000)",
                },
            },
        },
    },
}

_DEF_GENERATE_IMAGE: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GENERATE_IMAGE_SLUG,
        "description": (
            "Génère une image à partir d'une description textuelle (modèle de "
            "diffusion self-hosted). Utilise-le quand l'utilisateur demande de "
            "créer / dessiner / imaginer une image, une illustration, un logo, un "
            "fond d'écran, etc. L'image générée est automatiquement affichée à "
            "l'utilisateur. Décris la scène en détail dans `prompt` (de préférence "
            "en anglais pour la qualité), ce que tu veux éviter dans "
            "`negative_prompt`."
        ),
        "parameters": {
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Description détaillée de l'image à générer.",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Éléments à éviter (ex. 'blurry, low quality, text').",
                },
                "width": {"type": "integer", "description": "Largeur en px (multiple de 8)."},
                "height": {"type": "integer", "description": "Hauteur en px (multiple de 8)."},
                "seed": {
                    "type": "integer",
                    "description": "Graine pour reproduire un résultat (optionnel).",
                },
            },
        },
    },
}

_DEF_LIST_MACROS: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LIST_MACROS_SLUG,
        "description": "Liste les macros desktop enregistrées par l'utilisateur.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_MEMORY_LIST: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_LIST_SLUG,
        "description": (
            "Liste les fichiers de mémoire long-terme (.md) de l'utilisateur : "
            "nom + courte description. La liste t'est aussi rappelée dans le system "
            "prompt ; appelle ce tool pour la rafraîchir si besoin."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_MEMORY_READ: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_READ_SLUG,
        "description": (
            "Lit le contenu complet d'un fichier de mémoire long-terme par son nom "
            "(slug donné dans l'index/`memory_list`). Utilise-le DÈS QUE la réponse "
            "peut dépendre d'un souvenir de l'utilisateur (préférences, contexte, "
            "faits durables). N'invente jamais le contenu."
        ),
        "parameters": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Nom (slug) du fichier mémoire"}},
        },
    },
}

_DEF_MEMORY_WRITE: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_WRITE_SLUG,
        "description": (
            "Crée ou met à jour un fichier de mémoire long-terme (.md). Utilise-le "
            "pour retenir durablement une information utile pour les prochaines "
            "conversations (préférence, fait personnel, décision, contexte projet). "
            "Donne un `name` court et stable (ex. 'preferences', 'projet-x') et un "
            "`content` Markdown commençant idéalement par un titre `# ...`. Réécrit "
            "intégralement le fichier (relis-le avant si tu veux compléter)."
        ),
        "parameters": {
            "type": "object",
            "required": ["name", "content"],
            "properties": {
                "name": {"type": "string", "description": "Nom (slug) du fichier mémoire"},
                "content": {"type": "string", "description": "Contenu Markdown complet du fichier"},
            },
        },
    },
}

_DEF_MEMORY_DELETE: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEMORY_DELETE_SLUG,
        "description": (
            "Supprime un fichier de mémoire long-terme devenu obsolète ou erroné, "
            "par son nom (slug)."
        ),
        "parameters": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Nom (slug) du fichier mémoire"}},
        },
    },
}

_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"type": "string", "enum": list(ALLOWED_STEP_ACTIONS)},
        "app": {"type": "string", "description": "Nom de l'application (action launch_app)"},
        "url": {"type": "string", "description": "URL à ouvrir (action open_url)"},
        "monitor": {
            "type": "integer",
            "description": "Numéro d'écran (1 = principal, 2 = secondaire…)",
        },
        "mode": {"type": "string", "enum": list(ALLOWED_WINDOW_MODES)},
    },
}

_DEF_RUN_DESKTOP_ACTION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RUN_DESKTOP_ACTION_SLUG,
        "description": (
            "Exécute UNE action bureau sur le PC de l'utilisateur : lancer une "
            "application (launch_app + app) ou ouvrir une URL (open_url + url), "
            "éventuellement sur un écran donné. Pour une séquence récurrente, "
            "préfère define_macro puis run_macro."
        ),
        "parameters": _STEP_SCHEMA,
    },
}

_DEF_RUN_MACRO: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RUN_MACRO_SLUG,
        "description": (
            "Exécute une macro desktop enregistrée par son nom (ex. « soirée "
            "Minecraft »). Si la macro est inconnue, le résultat l'indique : "
            "demande alors à l'utilisateur ce qu'il veut, puis enregistre-la "
            "avec define_macro."
        ),
        "parameters": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Nom de la macro"}},
        },
    },
}

_DEF_DEFINE_MACRO: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DEFINE_MACRO_SLUG,
        "description": (
            "Enregistre une nouvelle macro desktop (séquence d'actions bureau) "
            "après que l'utilisateur a décrit ce qu'il veut. La macro est "
            "soumise à validation de l'utilisateur avant d'être sauvegardée. "
            "Chaque étape est une action launch_app (app) ou open_url (url), "
            "avec un monitor optionnel (1 = principal)."
        ),
        "parameters": {
            "type": "object",
            "required": ["name", "steps"],
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "steps": {"type": "array", "items": _STEP_SCHEMA, "minItems": 1},
            },
        },
    },
}


def tool_defs(*, desktop_connected: bool, images_enabled: bool = False) -> list[dict[str, Any]]:
    """Définitions des built-in tools à exposer au LLM pour ce tour.

    Les tools de pilotage PC ne sont exposés que si un client desktop est
    connecté (capability-aware). ``generate_image`` n'est exposé que si le moteur
    d'images est activé. web_search / show_visual / list_macros sont toujours
    disponibles.
    """
    defs = [
        _DEF_WEB_SEARCH,
        _DEF_SHOW_VISUAL,
        _DEF_LIST_MACROS,
        _DEF_MEMORY_LIST,
        _DEF_MEMORY_READ,
        _DEF_MEMORY_WRITE,
        _DEF_MEMORY_DELETE,
    ]
    if images_enabled:
        defs.append(_DEF_GENERATE_IMAGE)
    if desktop_connected:
        defs += [_DEF_RUN_DESKTOP_ACTION, _DEF_RUN_MACRO, _DEF_DEFINE_MACRO]
    return defs


def is_builtin(slug: str | None) -> bool:
    return slug in BUILTIN_SLUGS


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------


@dataclass
class BuiltinOutcome:
    """Résultat d'un built-in tool.

    ``content`` est le dict réinjecté en message role=tool. ``events`` sont des
    events SSE supplémentaires que la boucle de chat doit yield (ex. ``visual``
    pour l'affichage inline, ``desktop_step`` pour la progression d'une macro).
    """

    tool_name: str
    content: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


async def execute(
    db: AsyncSession,
    *,
    conversation: Conversation,
    tool_call: dict[str, Any],
    channel: str,
) -> BuiltinOutcome:
    fn = tool_call.get("function") or {}
    slug = fn.get("name") or ""
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    try:
        if slug == WEB_SEARCH_SLUG:
            return await _h_web_search(conversation, args, channel)
        if slug == SHOW_VISUAL_SLUG:
            return await _h_show_visual(conversation, args, channel)
        if slug == GENERATE_IMAGE_SLUG:
            return await _h_generate_image(db, conversation, args, channel)
        if slug == LIST_MACROS_SLUG:
            return await _h_list_macros(db, conversation)
        if slug == MEMORY_LIST_SLUG:
            return _h_memory_list(conversation)
        if slug == MEMORY_READ_SLUG:
            return _h_memory_read(conversation, args)
        if slug == MEMORY_WRITE_SLUG:
            return _h_memory_write(conversation, args)
        if slug == MEMORY_DELETE_SLUG:
            return _h_memory_delete(conversation, args)
        if slug == RUN_DESKTOP_ACTION_SLUG:
            return await _h_run_desktop_action(conversation, args, channel)
        if slug == RUN_MACRO_SLUG:
            return await _h_run_macro(db, conversation, args, channel)
        if slug == DEFINE_MACRO_SLUG:
            return await _h_define_macro(db, conversation, args, channel)
    except Exception as e:  # noqa: BLE001 — un built-in ne doit jamais tuer le tour
        logger.warning("builtin.failed", slug=slug, error=str(e))
        return BuiltinOutcome(slug, {"status": "error", "error": str(e)})

    return BuiltinOutcome(slug, {"status": "error", "error": f"unknown builtin '{slug}'"})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _h_web_search(
    conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    query = str(args.get("query") or "").strip()
    kind = args.get("kind") if args.get("kind") in ("web", "images") else "web"
    if not query:
        return BuiltinOutcome(WEB_SEARCH_SLUG, {"status": "error", "error": "query manquante"})

    # Permission HITL : l'utilisateur autorise (ou non) la recherche. Rend chaque
    # recherche réelle visible — et un refus force l'IA à l'admettre honnêtement
    # plutôt que d'inventer une réponse.
    if settings.websearch_require_approval:
        rid = await request_approval(
            {
                "kind": "web_search",
                "query": query,
                "search_kind": kind,
                "conversation_id": str(conversation.id),
            }
        )
        await publish(
            channel,
            "approval_required",
            {"request_id": rid, "kind": "web_search", "query": query},
        )
        decision = await wait_for_decision(rid, timeout_s=WEB_SEARCH_APPROVAL_TIMEOUT_S)
        if decision != "approved":
            return BuiltinOutcome(
                WEB_SEARCH_SLUG,
                {
                    "status": "denied" if decision == "rejected" else "timeout",
                    "query": query,
                    "note": (
                        "L'utilisateur a refusé la recherche web."
                        if decision == "rejected"
                        else "Aucune réponse de l'utilisateur (délai dépassé)."
                    ),
                    "instruction": (
                        "Tu n'as donc PAS pu effectuer la recherche. Indique-le "
                        "honnêtement à l'utilisateur et ne fournis aucune "
                        "information inventée sur ce sujet."
                    ),
                },
            )

    resp = await websearch_search(query, kind=kind, count=6)
    results = [
        {
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
            **({"image": r.image} if r.image else {}),
        }
        for r in resp.results
    ]
    content: dict[str, Any] = {
        "status": "ok",
        "query": resp.query,
        "kind": resp.kind,
        "answer": resp.answer,
        "results": results,
    }
    if not results and not resp.answer:
        content["status"] = "empty"
        content["note"] = "aucun résultat (SearXNG indisponible ou requête sans résultat)"
    return BuiltinOutcome(WEB_SEARCH_SLUG, content)


async def _h_show_visual(
    conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    kind = args.get("kind") if args.get("kind") in ("image", "card", "fact") else "card"
    visual: dict[str, Any] = {
        "kind": kind,
        "url": _safe_url(args.get("url")),
        "title": (str(args.get("title") or "")).strip() or None,
        "text": (str(args.get("text") or "")).strip() or None,
        "duration_ms": _clamp_duration(args.get("duration_ms")),
    }
    if kind in ("image", "card") and not visual["url"] and not visual["text"]:
        return BuiltinOutcome(
            SHOW_VISUAL_SLUG, {"status": "error", "error": "url ou text requis"}
        )
    # Overlay (toute l'app, via canal user) + companion inline (canal conv).
    await publish(user_channel(conversation.user_id), "visual", visual)
    await publish(channel, "visual", visual)
    return BuiltinOutcome(
        SHOW_VISUAL_SLUG,
        {"status": "shown", "visual": visual},
        events=[{"event": "visual", "data": visual}],
    )


async def _h_generate_image(
    db: AsyncSession, conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    if not settings.images_enabled:
        return BuiltinOutcome(
            GENERATE_IMAGE_SLUG,
            {"status": "error", "error": "La génération d'images est désactivée."},
        )
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return BuiltinOutcome(GENERATE_IMAGE_SLUG, {"status": "error", "error": "prompt manquant"})

    try:
        choice = await pick_image_node(db)
    except NoSuitableNodeError as e:
        return BuiltinOutcome(
            GENERATE_IMAGE_SLUG,
            {"status": "error", "error": str(e)},
        )

    params = GenerateParams(
        prompt=prompt,
        model=choice.image_model,
        negative_prompt=(str(args.get("negative_prompt") or "").strip() or None),
        width=_opt_int(args.get("width")),
        height=_opt_int(args.get("height")),
        seed=_opt_int(args.get("seed")),
    )
    try:
        png = await image_client.generate(choice.base_url, params)
    except image_client.ImageEngineError as e:
        return BuiltinOutcome(
            GENERATE_IMAGE_SLUG,
            {"status": "error", "error": f"node image indisponible: {e}"},
        )

    img = await image_storage.store(
        db,
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        png=png,
        prompt=prompt,
        negative_prompt=params.negative_prompt,
        params={"node": choice.name, "model": choice.image_model},
        seed=params.seed,
    )
    url = f"/api/images/{img.id}/file"
    visual: dict[str, Any] = {
        "kind": "image",
        "url": url,
        "title": prompt[:120],
        "text": None,
        "duration_ms": 12000,
    }
    # Affichage : overlay (canal user) + companion inline (canal conv).
    await publish(user_channel(conversation.user_id), "visual", visual)
    await publish(channel, "visual", visual)
    return BuiltinOutcome(
        GENERATE_IMAGE_SLUG,
        {
            "status": "ok",
            "image_id": str(img.id),
            "url": url,
            "width": img.width,
            "height": img.height,
            "note": "Image générée et affichée à l'utilisateur.",
        },
        events=[{"event": "visual", "data": visual}],
    )


async def _h_list_macros(db: AsyncSession, conversation: Conversation) -> BuiltinOutcome:
    macros = await _user_macros(db, conversation.user_id)
    return BuiltinOutcome(
        LIST_MACROS_SLUG,
        {
            "status": "ok",
            "macros": [
                {"name": m.name, "description": m.description, "steps": len(m.steps_json)}
                for m in macros
            ],
        },
    )


def _h_memory_list(conversation: Conversation) -> BuiltinOutcome:
    files = memory_files.list_files(conversation.user_id)
    return BuiltinOutcome(
        MEMORY_LIST_SLUG,
        {
            "status": "ok",
            "files": [
                {"name": f.name, "title": f.title, "description": f.description}
                for f in files
            ],
        },
    )


def _h_memory_read(conversation: Conversation, args: dict[str, Any]) -> BuiltinOutcome:
    name = str(args.get("name") or "").strip()
    if not name:
        return BuiltinOutcome(MEMORY_READ_SLUG, {"status": "error", "error": "name manquant"})
    content = memory_files.read_file(conversation.user_id, name)
    if content is None:
        return BuiltinOutcome(
            MEMORY_READ_SLUG,
            {
                "status": "not_found",
                "name": memory_files.slugify(name),
                "note": "Aucun fichier mémoire de ce nom. Utilise memory_list pour voir l'existant.",
            },
        )
    return BuiltinOutcome(
        MEMORY_READ_SLUG,
        {"status": "ok", "name": memory_files.slugify(name), "content": content},
    )


def _h_memory_write(conversation: Conversation, args: dict[str, Any]) -> BuiltinOutcome:
    name = str(args.get("name") or "").strip()
    content = str(args.get("content") or "")
    if not name:
        return BuiltinOutcome(MEMORY_WRITE_SLUG, {"status": "error", "error": "name manquant"})
    try:
        f = memory_files.write_file(conversation.user_id, name, content)
    except memory_files.MemoryFileError as e:
        return BuiltinOutcome(MEMORY_WRITE_SLUG, {"status": "error", "error": str(e)})
    return BuiltinOutcome(
        MEMORY_WRITE_SLUG,
        {"status": "saved", "name": f.name, "title": f.title, "size_bytes": f.size_bytes},
    )


def _h_memory_delete(conversation: Conversation, args: dict[str, Any]) -> BuiltinOutcome:
    name = str(args.get("name") or "").strip()
    if not name:
        return BuiltinOutcome(MEMORY_DELETE_SLUG, {"status": "error", "error": "name manquant"})
    try:
        deleted = memory_files.delete_file(conversation.user_id, name)
    except memory_files.MemoryFileError as e:
        return BuiltinOutcome(MEMORY_DELETE_SLUG, {"status": "error", "error": str(e)})
    return BuiltinOutcome(
        MEMORY_DELETE_SLUG,
        {"status": "deleted" if deleted else "not_found", "name": memory_files.slugify(name)},
    )


async def _h_run_desktop_action(
    conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    step, errs = _validate_step(args)
    if errs:
        return BuiltinOutcome(
            RUN_DESKTOP_ACTION_SLUG, {"status": "invalid", "errors": errs}
        )
    gate = await _gate_step(conversation.user_id, step)
    if gate is not None:
        return BuiltinOutcome(RUN_DESKTOP_ACTION_SLUG, gate)
    result = await _exec_step(conversation.user_id, step)
    return BuiltinOutcome(RUN_DESKTOP_ACTION_SLUG, {"status": "ok", "result": result})


async def _h_run_macro(
    db: AsyncSession, conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    name = str(args.get("name") or "").strip()
    if not name:
        return BuiltinOutcome(RUN_MACRO_SLUG, {"status": "error", "error": "name manquant"})
    macro = await _resolve_macro(db, conversation.user_id, name)
    if macro is None:
        return BuiltinOutcome(
            RUN_MACRO_SLUG,
            {
                "status": "unknown_macro",
                "message": (
                    f"La macro « {name} » n'existe pas encore. Demande à "
                    f"l'utilisateur ce qu'il veut, puis enregistre-la via define_macro."
                ),
            },
        )

    step_results = await run_macro_steps(conversation.user_id, macro.steps_json)
    events: list[dict[str, Any]] = []
    ok = True
    for entry in step_results:
        if entry["result"].get("status") not in ("ok", "shown"):
            ok = False
        events.append({"event": "desktop_step", "data": entry})
        await publish(channel, "desktop_step", entry)

    return BuiltinOutcome(
        RUN_MACRO_SLUG,
        {
            "status": "ok" if ok else "partial",
            "macro": macro.name,
            "steps": step_results,
        },
        events=events,
    )


async def _h_define_macro(
    db: AsyncSession, conversation: Conversation, args: dict[str, Any], channel: str
) -> BuiltinOutcome:
    name = str(args.get("name") or "").strip()
    description = str(args.get("description") or "").strip()
    raw_steps = args.get("steps")
    if not name or not isinstance(raw_steps, list) or not raw_steps:
        return BuiltinOutcome(
            DEFINE_MACRO_SLUG, {"status": "error", "error": "name et steps (non vide) requis"}
        )

    cleaned: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_steps):
        step, errs = _validate_step(raw if isinstance(raw, dict) else {})
        if errs:
            return BuiltinOutcome(
                DEFINE_MACRO_SLUG,
                {
                    "status": "invalid_step",
                    "step": i + 1,
                    "errors": errs,
                    "message": "Reformule cette étape (action non réalisable).",
                },
            )
        cleaned.append(step)

    # Validation HITL : on montre les étapes à l'utilisateur avant de sauvegarder.
    rid = await request_approval(
        {
            "kind": "define_macro",
            "name": name,
            "description": description,
            "steps": cleaned,
            "conversation_id": str(conversation.id),
        }
    )
    await publish(
        channel,
        "approval_required",
        {"request_id": rid, "kind": "define_macro", "name": name, "steps": cleaned},
    )
    decision = await wait_for_decision(rid, timeout_s=MACRO_APPROVAL_TIMEOUT_S)
    if decision != "approved":
        return BuiltinOutcome(
            DEFINE_MACRO_SLUG,
            {"status": "rejected" if decision == "rejected" else "timeout"},
        )

    slug = _slugify(name)
    existing = await db.scalar(
        select(DesktopMacro).where(
            DesktopMacro.user_id == conversation.user_id, DesktopMacro.slug == slug
        )
    )
    if existing is not None:
        existing.name = name
        existing.description = description
        existing.steps_json = cleaned
    else:
        db.add(
            DesktopMacro(
                user_id=conversation.user_id,
                slug=slug,
                name=name,
                description=description,
                steps_json=cleaned,
            )
        )
    await db.commit()
    return BuiltinOutcome(
        DEFINE_MACRO_SLUG,
        {"status": "saved", "name": name, "slug": slug, "steps": cleaned},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user_macros(db: AsyncSession, user_id: UUID) -> list[DesktopMacro]:
    return list(
        (
            await db.execute(
                select(DesktopMacro)
                .where(DesktopMacro.user_id == user_id)
                .order_by(DesktopMacro.name)
            )
        )
        .scalars()
        .all()
    )


async def _resolve_macro(
    db: AsyncSession, user_id: UUID, name: str
) -> DesktopMacro | None:
    slug = _slugify(name)
    macro = await db.scalar(
        select(DesktopMacro).where(
            DesktopMacro.user_id == user_id, DesktopMacro.slug == slug
        )
    )
    if macro is not None:
        return macro
    # Repli : correspondance floue sur le nom (insensible à la casse / aux accents).
    needle = _norm(name)
    for m in await _user_macros(db, user_id):
        if needle and (needle in _norm(m.name) or _norm(m.name) in needle):
            return m
    return None


def _validate_step(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Nettoie + valide une étape. Retourne (step_nettoyée, erreurs)."""
    errs: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["étape invalide (objet attendu)"]
    action = str(raw.get("action") or "").strip()
    if action not in ALLOWED_STEP_ACTIONS:
        return {}, [f"action inconnue '{action}' (autorisé: {', '.join(ALLOWED_STEP_ACTIONS)})"]

    step: dict[str, Any] = {"action": action}

    if action == "launch_app":
        app = str(raw.get("app") or "").strip()
        if not app:
            errs.append("launch_app requiert 'app'")
        else:
            step["app"] = app
    elif action == "open_url":
        url = _safe_url(raw.get("url"))
        if not url:
            errs.append("open_url requiert une 'url' http(s) valide")
        else:
            step["url"] = url

    if raw.get("monitor") is not None:
        try:
            mon = int(raw["monitor"])
            if mon >= 1:
                step["monitor"] = mon
        except (TypeError, ValueError):
            errs.append("monitor doit être un entier ≥ 1")

    mode = raw.get("mode")
    if mode is not None:
        if mode in ALLOWED_WINDOW_MODES:
            step["mode"] = mode
        else:
            errs.append(f"mode invalide (autorisé: {', '.join(ALLOWED_WINDOW_MODES)})")

    return step, errs


async def _gate_step(user_id: UUID, step: dict[str, Any]) -> dict[str, Any] | None:
    """Garde-fou sécurité avant exécution. Retourne un dict d'erreur ou None.

    Posture choisie : l'IA ne lance que des applications **détectées** sur le PC
    de l'utilisateur. Le client Tauri reste l'autorité finale, mais on filtre ici
    pour un message clair que l'IA peut relayer (→ reformulation).
    """
    if step.get("action") != "launch_app":
        return None
    caps = await registry.get_caps(user_id)
    known = registry.known_app_names(caps)
    if not known:
        # Pas de liste d'apps (client pas encore prêt) : on laisse passer, le
        # client validera de son côté.
        return None
    app = step.get("app", "")
    if not _app_matches(app, known):
        return {
            "status": "app_not_found",
            "message": (
                f"L'application « {app} » n'est pas détectée sur ton PC. "
                "Dis-moi le nom exact ou une autre application."
            ),
            "known_examples": sorted(known)[:15],
        }
    return None


async def _exec_step(user_id: UUID, step: dict[str, Any]) -> dict[str, Any]:
    """Envoie une étape au client desktop et attend son résultat."""
    rid = await bridge.request_action(user_id, step)
    return await bridge.wait_for_result(rid)


# --- Helpers publics réutilisés par l'API REST (api/desktop.py) -------------


async def run_macro_steps(
    user_id: UUID, steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Exécute séquentiellement les étapes d'une macro via le pont desktop."""
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(steps):
        step, _ = _validate_step(raw)
        result = await _exec_step(user_id, step)
        out.append({"step": idx + 1, "action": step, "result": result})
    return out


def validate_steps(raw_steps: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Valide une liste d'étapes (création manuelle via l'UI). Retourne
    (étapes_nettoyées, erreurs)."""
    cleaned: list[dict[str, Any]] = []
    errors: list[str] = []
    if not isinstance(raw_steps, list) or not raw_steps:
        return [], ["au moins une étape est requise"]
    for i, raw in enumerate(raw_steps):
        step, errs = _validate_step(raw if isinstance(raw, dict) else {})
        if errs:
            errors.append(f"étape {i + 1}: {'; '.join(errs)}")
        else:
            cleaned.append(step)
    return cleaned, errors


def slugify(name: str) -> str:
    return _slugify(name)


def _app_matches(app: str, known: list[str]) -> bool:
    a = _norm(app)
    if not a:
        return False
    return any(a in _norm(k) or _norm(k) in a for k in known)


def _safe_url(value: Any) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s
    # Tolère « youtube.com » → https://youtube.com
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", s, re.IGNORECASE):
        return "https://" + s
    return None


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_duration(value: Any) -> int:
    try:
        d = int(value)
    except (TypeError, ValueError):
        return 7000
    return max(1000, min(d, 30000))


def _slugify(name: str) -> str:
    s = _norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "macro")[:64]


def _norm(s: str) -> str:
    """Minuscule + sans accents, pour comparaisons souples."""
    import unicodedata

    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()
