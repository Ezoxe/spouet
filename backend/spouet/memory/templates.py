"""Modèles de fichiers mémoire `.md` prêts à l'emploi.

L'utilisateur peut les **activer** (crée le fichier avec ce contenu par défaut) /
**désactiver** (supprime le fichier) depuis la page `/memory`, puis les éditer comme
n'importe quel fichier mémoire. `name` est déjà un slug (clé stable).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryTemplate:
    name: str
    title: str
    description: str
    content: str


MEMORY_TEMPLATES: list[MemoryTemplate] = [
    MemoryTemplate(
        name="profil",
        title="Profil",
        description="Qui tu es : contexte personnel et professionnel durable.",
        content=(
            "# Profil\n\n"
            "- **Prénom** : \n"
            "- **Rôle / métier** : \n"
            "- **Localisation / fuseau horaire** : \n"
            "- **Langues** : \n"
            "- **Centres d'intérêt** : \n\n"
            "_Ce que l'assistant devrait savoir de durable sur moi._\n"
        ),
    ),
    MemoryTemplate(
        name="preferences",
        title="Préférences",
        description="Comment je veux que l'assistant réponde (format, longueur…).",
        content=(
            "# Préférences\n\n"
            "- **Langue des réponses** : français\n"
            "- **Ton** : \n"
            "- **Longueur par défaut** : concis, va à l'essentiel\n"
            "- **Format** : \n"
            "- **Niveau technique** : \n\n"
            "_Règles générales que l'assistant doit suivre dans nos échanges._\n"
        ),
    ),
    MemoryTemplate(
        name="style-communication",
        title="Style de communication",
        description="Le style/voix attendu de l'assistant.",
        content=(
            "# Style de communication\n\n"
            "- Tutoiement / vouvoiement : \n"
            "- Émojis : \n"
            "- Humour : \n"
            "- Ce que j'apprécie : \n"
            "- Ce qui m'agace : \n"
        ),
    ),
    MemoryTemplate(
        name="projets",
        title="Projets en cours",
        description="Les projets sur lesquels je travaille.",
        content=(
            "# Projets en cours\n\n"
            "## Projet A\n"
            "- Objectif : \n"
            "- Stack / contexte : \n"
            "- État actuel : \n\n"
            "_Ajoute une section par projet ; l'assistant s'y réfère pour garder le contexte._\n"
        ),
    ),
    MemoryTemplate(
        name="a-eviter",
        title="À éviter / contraintes",
        description="Ce que l'assistant ne doit pas faire.",
        content=(
            "# À éviter / contraintes\n\n"
            "- \n"
            "- \n\n"
            "_Contraintes fermes : choses à ne jamais faire, sujets sensibles, formats interdits…_\n"
        ),
    ),
    MemoryTemplate(
        name="faits-importants",
        title="Faits importants",
        description="Infos durables à toujours garder en tête.",
        content=(
            "# Faits importants\n\n"
            "- \n"
            "- \n\n"
            "_Décisions, échéances récurrentes, personnes clés, identifiants non secrets…_\n"
        ),
    ),
]
