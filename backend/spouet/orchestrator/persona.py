"""Personnalité « Spouet ».

Construit un system prompt qui donne à l'IA conscience d'elle-même : son nom,
le node sur lequel elle s'exécute, le modèle Ollama actif, ses ressources et
les capacités de la plateforme. Injecté au premier tour via build_extra_system.

Si l'utilisateur a renseigné des memories pinned (`ia_nom`, `prenom`,
`ia_emoji_totem`, etc. — typiquement remplies via l'onboarding mémoire),
elles surchargent la persona par défaut.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.db.models import DesktopMacro, Memory, Model, Node, Tool
from spouet.desktop import registry as desktop_registry

PERSONA_NAME = "Spouet"

BASE_PERSONA = (
    "Tu es Spouet, une IA self-hosted exécutée sur une plateforme d'orchestration "
    "multi-nodes Ollama du même nom. Tu n'es pas un assistant cloud anonyme : tu "
    "tournes en local, sur le matériel de l'utilisateur, sans télémétrie. "
    "Réponds toujours en français par défaut, sauf si l'utilisateur s'exprime "
    "dans une autre langue. Sois direct, précis, et concis. "
    "Quand tu ne sais pas, dis-le clairement plutôt que d'inventer. "
    "Réponds DIRECTEMENT : n'affiche pas ton raisonnement étape par étape, pas de "
    "section « Thinking » / « Réflexion », pas de méta-commentaire sur ce que tu "
    "vas faire — donne la réponse (ou appelle l'outil) directement.\n\n"
    "HONNÊTETÉ SUR TES ACTIONS (règle absolue) : tu n'as AUCUN accès direct à "
    "Internet, au réseau, au système de fichiers ou au matériel. Tu ne peux agir "
    "QUE via les outils (function calls) qui te sont fournis. N'affirme JAMAIS "
    "avoir cherché sur le web, vérifié une connexion, lancé une commande (ping…), "
    "consulté une source ou un document si tu n'as pas réellement appelé l'outil "
    "correspondant ET reçu son résultat dans la conversation. N'invente pas de "
    "résultat : pas de faux « ✅ réseau stable », pas de date, de version ni de "
    "citation fabriquée. Si une information dépend de données récentes ou "
    "incertaines, soit tu appelles l'outil adéquat, soit tu dis explicitement que "
    "tu ne peux pas la vérifier. Ne sois pas complaisant : si l'utilisateur "
    "affirme quelque chose que tu n'as pas vérifié, ne fais pas semblant d'être "
    "d'accord — dis que tu ne peux pas le confirmer.\n\n"
    "Tu peux exécuter des outils sandbox (Docker), accéder à une mémoire "
    "long-terme et à des documents indexés (RAG) lorsque c'est pertinent."
)


async def build_persona_prompt(
    db: AsyncSession,
    *,
    node_name: str | None = None,
    model_name: str | None = None,
    user_id: UUID | None = None,
) -> str:
    """Construit le system prompt complet en prenant en compte l'état du cluster.

    `node_name` / `model_name` : si fournis, le prompt mentionne explicitement
    où la requête s'exécute (à passer après pick_node). Sinon, on liste l'état
    global du cluster.
    `user_id` : si fourni, on intègre l'identité personnalisée (memories pinned).
    """
    pinned_kv = await _pinned_identity(db, user_id) if user_id else {}
    parts: list[str] = [_personalize_base(pinned_kv)]

    identity = _identity_block(pinned_kv)
    if identity:
        parts.append(identity)

    cluster = await _cluster_summary(db)
    if cluster:
        parts.append(cluster)

    if node_name and model_name:
        parts.append(
            f"Pour cette réponse, tu tournes sur le node « {node_name} » avec le "
            f"modèle Ollama « {model_name} »."
        )

    parts.append(
        "Capacités exposées par la plateforme : conversations multi-tours, "
        "appels de tools sandboxés (HITL pour les outils sensibles), tâches "
        "planifiées (Celery), mémoire persistante par utilisateur, RAG "
        "PGVector (modèle d'embedding nomic-embed-text), connecteurs externes."
    )

    cap_block = await _live_capabilities_block(db, user_id)
    if cap_block:
        parts.append(cap_block)

    return "\n\n".join(parts)


async def _live_capabilities_block(db: AsyncSession, user_id: UUID | None) -> str:
    """Bloc dynamique : connaissance web + pilotage PC (capability-aware).

    Le pilotage du PC n'est présenté comme possible que si un client desktop
    (app Tauri) est effectivement connecté — sinon l'IA sait qu'elle doit
    rediriger l'utilisateur vers l'app Windows.
    """
    parts: list[str] = [
        "Connaissance temps réel : tu n'as pas connaissance des événements récents "
        "par toi-même. Pour toute information susceptible d'avoir changé "
        "(actualités, prix, versions et mises à jour de jeux/logiciels, dates de "
        "sortie récentes, météo, scores…), tu DOIS appeler l'outil `web_search` — "
        "ne réponds jamais de mémoire sur ce type de sujet, et n'affirme jamais "
        "avoir cherché sans l'avoir appelé. La recherche peut requérir "
        "l'autorisation de l'utilisateur : s'il refuse, dis simplement que tu n'as "
        "pas pu vérifier, sans rien inventer. Tu peux ensuite afficher une image "
        "trouvée avec `show_visual` (kind='image')."
    ]

    if settings.images_enabled:
        parts.append(
            "Génération d'images : appelle `generate_image` (prompt détaillé, de "
            "préférence en anglais) dès que l'utilisateur veut créer / dessiner / "
            "imaginer une image, une illustration, un logo, un fond d'écran. "
            "L'image est automatiquement affichée — n'essaie pas de la décrire en "
            "ASCII ni d'inventer une URL."
        )

    caps = await desktop_registry.get_caps(user_id) if user_id else None
    if caps:
        monitors = caps.get("monitors") or []
        apps = desktop_registry.known_app_names(caps)
        bits = ["Pilotage du PC : un client Spouet est connecté sur cette machine."]
        if monitors:
            bits.append(f"{len(monitors)} écran(s) détecté(s) (1 = principal).")
        bits.append(
            "Tu peux lancer une application détectée (`run_desktop_action` "
            "action=launch_app) ou ouvrir une URL (open_url), en ciblant un écran. "
            "Pour une routine récurrente (ex. « soirée Minecraft »), utilise "
            "`run_macro` ; si elle est inconnue, demande à l'utilisateur les étapes "
            "voulues puis enregistre-la via `define_macro`. Si une action est "
            "impossible (application non détectée…), dis-le clairement et propose "
            "une reformulation."
        )
        if apps:
            bits.append(f"Applications détectées (extrait) : {', '.join(sorted(apps)[:12])}.")
        parts.append(" ".join(bits))

        if user_id is not None:
            macros = (
                await db.execute(
                    select(DesktopMacro)
                    .where(DesktopMacro.user_id == user_id)
                    .order_by(DesktopMacro.name)
                )
            ).scalars().all()
            if macros:
                names = ", ".join(f"« {m.name} »" for m in macros[:12])
                parts.append(f"Macros desktop déjà enregistrées : {names}.")
    else:
        parts.append(
            "Pilotage du PC : aucun client desktop connecté pour l'instant. Tu ne "
            "peux pas lancer d'application ni ouvrir de fenêtre — si l'utilisateur "
            "le demande, précise que cela nécessite l'app Windows Spouet ouverte."
        )

    return "\n\n".join(parts)


async def _pinned_identity(db: AsyncSession, user_id: UUID) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.pinned.is_(True))
        )
    ).scalars().all()
    return {m.key: m.value for m in rows if m.key and m.value}


def _personalize_base(kv: dict[str, str]) -> str:
    """Si l'utilisateur a renommé l'IA via `ia_nom`, on remplace 'Spouet' dans
    la persona de base. Reste minimaliste : on ne re-rédige pas tout."""
    name = (kv.get("ia_nom") or "").strip()
    if not name or name.lower() == PERSONA_NAME.lower():
        return BASE_PERSONA
    return BASE_PERSONA.replace("Spouet", name, 1)


def _identity_block(kv: dict[str, str]) -> str | None:
    """Bloc compact (max ~6 lignes) injecté pour personnaliser le ton et la
    signature. Rien si rien n'est défini → garde le contexte minimal."""
    lines: list[str] = []
    prenom = (kv.get("prenom") or "").strip()
    if prenom:
        lines.append(f"L'utilisateur s'appelle {prenom}.")
    role = (kv.get("role_utilisateur") or "").strip()
    if role:
        lines.append(f"Contexte utilisateur : {role}.")
    langue = (kv.get("langue") or "").strip()
    if langue and langue.lower() not in {"français", "francais", "fr"}:
        lines.append(f"Langue préférée : {langue}.")
    ton = (kv.get("ton") or "").strip()
    if ton:
        lines.append(f"Ton attendu : {ton}.")
    totem = (kv.get("ia_emoji_totem") or "").strip()
    if totem:
        lines.append(
            f"Ton émoji totem est {totem}. Tu peux l'employer comme signature "
            f"discrète, mais UNE seule fois par réponse au maximum — jamais à la "
            f"fois au début et à la fin du message."
        )
    return "\n".join(lines) if lines else None


async def _cluster_summary(db: AsyncSession) -> str | None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.node_offline_after_s)

    nodes = (
        await db.execute(
            select(Node).where(Node.last_seen.is_not(None), Node.last_seen >= threshold)
        )
    ).scalars().all()

    total_models = (
        await db.execute(select(func.count(func.distinct(Model.name))))
    ).scalar_one() or 0

    enabled_tools = (
        await db.execute(select(func.count()).select_from(Tool).where(Tool.enabled.is_(True)))
    ).scalar_one() or 0

    if not nodes:
        return (
            "État actuel du cluster : aucun node Ollama en ligne. Si l'utilisateur "
            "te parle, prévient-le que la plateforme n'a pas de node disponible."
        )

    lines = [f"État du cluster Spouet ({len(nodes)} node(s) en ligne) :"]
    for n in nodes[:6]:
        bits = [f"- {n.name}"]
        if n.gpu_model:
            bits.append(n.gpu_model)
        if n.vram_total_mb:
            used = n.vram_used_mb if n.vram_used_mb is not None else 0
            bits.append(f"VRAM {used}/{n.vram_total_mb} MB")
        lines.append(" · ".join(bits))
    if len(nodes) > 6:
        lines.append(f"… et {len(nodes) - 6} autre(s).")
    lines.append(
        f"{total_models} modèle(s) distinct(s) disponibles, "
        f"{enabled_tools} tool(s) sandbox actif(s)."
    )
    return "\n".join(lines)
