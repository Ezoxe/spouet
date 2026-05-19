"""Configuration pytest partagée.

Définit des variables d'environnement de test *avant* le premier import de
`spouet.core.config`, pour que les tests unitaires purs (router, crypto,
scheduler…) puissent tourner sans `.env` réel ni base de données.

`setdefault` : si l'environnement fournit déjà ces variables (exécution dans
le conteneur Docker, CI), on ne les écrase pas.
"""

from __future__ import annotations

import os

# Clé aléatoire à forte entropie, sans pattern interdit (changeme/secret/…),
# uniquement pour satisfaire la validation de Settings en test.
os.environ.setdefault(
    "SPOUET_SECRET_KEY", "k7Jq2mNp9XvWdR4tYbZc8FhUgL5sQ3aE6nD1oP0iCxB7uVw"
)
os.environ.setdefault(
    "SPOUET_DATABASE_URL",
    "postgresql+asyncpg://spouet:spouet@localhost:5432/spouet_test",
)
os.environ.setdefault("SPOUET_REDIS_URL", "redis://localhost:6379/1")
