# Tools Vaultwarden (image partagée)

Cette image fournit le runtime commun aux 3 tools Vaultwarden :

- `vaultwarden-list` — lister les entrées (sans mots de passe)
- `vaultwarden-get`  — récupérer une entrée complète (mot de passe, TOTP)
- `vaultwarden-set`  — créer / mettre à jour une entrée

L'opération est sélectionnée par la variable d'environnement `BW_OP`
(`list` / `get` / `set`), définie dans le manifest de chaque tool.

## Pré-requis

Une instance Vaultwarden (ou Bitwarden) joignable depuis le serveur Spouet,
et un compte dédié pour le bot.

## Installation

```bash
# 1. Build (une seule fois) l'image partagée
docker build -t spouet/tool-vaultwarden:0.1.0 tools/registry/_shared/vaultwarden

# 2. Stocke les credentials dans le coffre Spouet (scope global)
spouet-admin secrets set --scope global --key vaultwarden_url      # ex: https://vault.example.com
spouet-admin secrets set --scope global --key vaultwarden_email
spouet-admin secrets set --scope global --key vaultwarden_password

# 3. Installe les 3 manifests
spouet-admin tools install ./tools/registry/vaultwarden-list
spouet-admin tools install ./tools/registry/vaultwarden-get
spouet-admin tools install ./tools/registry/vaultwarden-set
```

## Vérification

Dans une conversation, demande à l'IA :

> Liste mes 5 dernières entrées Vaultwarden contenant "github".
>
> Récupère le mot de passe de l'entrée "OVH Manager".
>
> Stocke un nouveau mot de passe `J3taim3SvelteKit!` pour `accounts.spouet.dev`.

Chaque appel passe par une **approval HITL** (le tool est en `network: bridge`).
