# Tool : fs-read

Lit un fichier texte depuis `/workspace` (à monter par l'orchestrateur).

## Sécurité

- `network: none`, validation anti-traversal (pas de `..`, pas de chemin absolu)
- Lecture seule, pas d'écriture
- `max_bytes` plafonné à 1 MB
