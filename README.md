# Spouet

Plateforme self-hosted d'orchestration multi-nodes Ollama. Inspirée d'OpenClaw / Claude Desktop, mais 100 % locale.

## Vue d'ensemble

Spouet centralise plusieurs serveurs Ollama (LAN) derrière une API unique pour :

- chat distribué avec sélection automatique du node le moins chargé
- détection automatique des modèles disponibles + monitoring VRAM
- tools custom (function calling natif Ollama) exécutés en sandbox Docker
- coffre de **secrets chiffrés** (Fernet) injectés dans les tools / connectors
- **connectors persistants** : bridges Docker long-running (Discord, Telegram, IMAP…)
  qui rendent l'IA joignable depuis l'extérieur
- scheduler type cron pour automatiser des tâches IA récurrentes
- RAG + memory persistante (PGVector)
- 3 surfaces clientes : web PWA, app desktop Windows compagnon (Tauri), mobile (PWA)

## Architecture

```
[ Web PWA / Tauri / Mobile ]
            |
       Caddy (TLS)
            |
       FastAPI :8000
       /     |      \
 Postgres  Redis   Celery (worker + beat)
            |        |
        pub/sub   Docker SDK (tools)
                     |
                Ollama nodes (heartbeat agents)
```

Backend hébergé sur **Debian** (docker-compose). Node-agents déployés sur chaque machine Ollama (Linux/Windows).

## Structure du dépôt

| Dossier | Rôle |
|---|---|
| `backend/` | FastAPI + Celery + scheduler + tools runner (Python 3.12) |
| `web/` | SvelteKit PWA mobile-first (Tailwind + shadcn-svelte) |
| `desktop/` | Tauri 2.0, réutilise le bundle SvelteKit |
| `node-agent/` | Daemon léger sur chaque machine Ollama (heartbeat) |
| `tools/registry/` | Tools de référence (web-fetch, python-exec, fs-read, vaultwarden-*, ...) |
| `connectors/registry/` | Connectors de référence (Discord, …) |
| `deploy/` | docker-compose, Caddyfile, units systemd |
| `docs/` | Documentation architecture, API, authoring tools, connectors |

---

## 🚀 Installation automatique

Quatre installeurs one-liner couvrent toutes les surfaces. Aucun prérequis manuel — Docker, `uv`, NSSM, etc. sont installés automatiquement.

### Serveur Debian / Ubuntu (stack complète)

```bash
curl -fsSL https://raw.githubusercontent.com/ezoxe/spouet/master/install.sh | sudo bash
```

Le script :
- installe Docker + Compose v2 si absent (via `get.docker.com`)
- clone le dépôt dans `/opt/spouet`
- génère `deploy/.env` avec des secrets aléatoires (`openssl rand -hex`)
- build et démarre la stack (`postgres`, `redis`, `backend`, `worker`, `beat`, `web`)
- applique les migrations Alembic
- crée le **premier token admin** (affiché UNE seule fois — copie-le)
- installe et active le service systemd `spouet-stack` (auto-start au boot)

Variables/options utiles :

```bash
# Non-interactif (pour Ansible/CI)
curl -fsSL .../install.sh | sudo SPOUET_NON_INTERACTIVE=1 \
    SPOUET_ADMIN_EMAIL=ops@example.com \
    bash

# Avec drapeaux
sudo bash install.sh --email=me@local --branch=master
```

Drapeaux reconnus : `--email`, `--branch`, `--dir`, `--repo`, `--non-interactive`,
`--skip-docker`, `--skip-systemd`. Les ports hôte (postgres/redis/backend/web)
sont alloués automatiquement à partir de 10000.

### Node-agent Linux

```bash
curl -fsSL https://raw.githubusercontent.com/ezoxe/spouet/master/node-agent/install.sh \
    | sudo BACKEND=https://spouet.local TOKEN=<token> bash
```

Bootstrap `uv`, clone le dépôt, crée l'utilisateur système `spouet`, écrit `/etc/spouet/agent.env`, installe et active le service systemd `spouet-agent`. Idempotent (relancer = mise à jour).

### Node-agent Windows (machine Ollama)

PowerShell **Administrateur** :

```powershell
irm https://raw.githubusercontent.com/ezoxe/spouet/master/node-agent/install.ps1 | iex
```

Bootstrap complet : installe `git` (via winget), `uv`, télécharge NSSM, clone dans `C:\spouet`, prompts backend/token, crée et démarre le service Windows `SpouetAgent` (auto-start).

### Application desktop Windows

PowerShell **Administrateur** :

```powershell
irm https://raw.githubusercontent.com/ezoxe/spouet/master/desktop/install.ps1 | iex
```

Télécharge le dernier MSI depuis GitHub Releases (publié automatiquement par CI sur tag `v*`) et l'installe en silencieux. Pas de compilation locale.

---

## ⚙️ Prérequis (uniquement pour le dev local — les installeurs se débrouillent en prod)

| Outil | Où | Version |
|---|---|---|
| Docker + Compose v2 | Debian (prod) | ≥ 24 |
| `uv` | Debian + chaque node Ollama | ≥ 0.5 |
| Ollama | Chaque node | ≥ 0.4 |
| Node.js + pnpm | Poste de dev (web/desktop) | Node ≥ 20, pnpm ≥ 9 |
| Rust toolchain | Poste de dev desktop | stable |

---

## 🖥️ Node-agent (sur chaque machine Ollama)

Voir la section [Installation automatique](#-installation-automatique) plus haut — un one-liner par OS. La sous-section ci-dessous reste utile pour le test manuel ou un setup non-standard.

### Test manuel (foreground)

```bash
cd node-agent
SPOUET_AGENT_TOKEN=<token> uv run spouet-agent run \
    --backend http://debian:8000 \
    --ollama  http://localhost:11434 \
    --interval 10 \
    --tag gpu --tag gaming
```

---

## 🐍 Backend (dev local, PAS sur Windows — utiliser Debian)

```bash
cd backend
uv sync                                              # installer
uv run uvicorn spouet.main:app --reload --port 8000  # dev server

uv run alembic upgrade head                          # migrations
uv run alembic revision --autogenerate -m "msg"      # nouvelle migration

uv run celery -A spouet.workers worker --loglevel=info
uv run celery -A spouet.workers beat   --loglevel=info

uv run spouet-admin create-token --email me@local
uv run spouet-admin tools install ./tools/registry/web-fetch --build
uv run spouet-admin tools list

uv run pytest                                        # tous les tests
uv run pytest tests/test_security.py -xvs            # un fichier
uv run pytest -k "test_router" -xvs                  # un pattern
uv run ruff check .                                  # lint
uv run ruff format .                                 # format
uv run mypy spouet                                   # types
```

---

## 🌐 Web (SvelteKit PWA)

```bash
cd web
pnpm install
pnpm dev                              # http://localhost:5173 (proxy /api → :8000)
pnpm build                            # build statique → web/build (consommé par Tauri)
pnpm preview                          # preview du build
pnpm check                            # svelte-check + tsc
pnpm lint                             # eslint + prettier --check
pnpm format                           # prettier --write
```

Connexion : `/login` → coller le token API → redirige sur `/`.

---

## 🪟 Desktop (Tauri 2.0, Windows)

```powershell
cd web && pnpm install && cd ..
cd desktop
pnpm install

# Générer les icônes une fois (depuis un PNG 1024×1024)
pnpm tauri icon ../docs/logo.png

pnpm tauri dev                        # build web + lance Tauri en dev
pnpm tauri build                      # MSI + NSIS dans src-tauri/target/release/bundle
```

Hotkey global : **Ctrl + Espace** ouvre/ferme la fenêtre compagnon.

---

## 🔧 Tools custom (créer le vôtre)

Arborescence : `tools/registry/<slug>/`

```
manifest.yaml      # slug, image, network, timeout, mem_limit, input_schema, output_schema
Dockerfile         # idéalement non-root, image légère
run.py             # lit JSON sur stdin, écrit JSON sur stdout
README.md
```

Installation :

```bash
docker compose exec backend spouet-admin tools install ./tools/registry/<slug> --build
```

Test direct du conteneur (debug) :

```bash
echo '{"url":"https://example.com"}' | docker run -i --rm --network none spouet/tool-web-fetch:0.1.0
```

### Champ `secrets` (optionnel)

Un tool peut déclarer des secrets à injecter en variable d'env, résolus depuis le coffre :

```yaml
secrets:
  VAULTWARDEN_PASSWORD: global/vaultwarden_password
  OPENAI_KEY: tool:my-tool/openai_key
```

Voir aussi `docs/tools-authoring.md`.

---

## 🔐 Coffre de secrets

Stockés chiffrés (Fernet, clé dérivée de `SPOUET_SECRET_KEY`) en base, jamais réaffichés en clair.

```bash
# Stocker (recommandé : via stdin pour ne pas polluer l'historique shell)
echo -n "$DISCORD_TOKEN" | docker compose exec -T backend \
    spouet-admin secrets set --scope connector:discord-bot --key token

# Lister
docker compose exec backend spouet-admin secrets list
docker compose exec backend spouet-admin secrets list --scope global

# Supprimer
docker compose exec backend spouet-admin secrets delete --scope global --key vaultwarden_password
```

UI : `/secrets` dans le frontend.

---

## 🔌 Connectors persistants (Discord, …)

Voir `docs/connectors-authoring.md` pour le format complet.

```bash
# 1. Build l'image (ex: discord)
docker build -t spouet/connector-discord:0.1.0 connectors/registry/discord

# 2. Stocke le token Discord dans le coffre
echo -n "$DISCORD_BOT_TOKEN" | docker compose exec -T backend \
    spouet-admin secrets set --scope connector:discord-bot --key token

# 3. Installe le manifest dans la DB (rattaché à un user)
docker compose exec backend \
    spouet-admin connectors install ./connectors/registry/discord --email me@local

# 4. Configure (UI /connectors/<id> ou via API PATCH)
#    bot_persona, default_model, allowed_channels, respond_dm, trigger_prefix

# 5. Démarre
docker compose exec backend spouet-admin connectors start discord-bot

# Vérifier
docker compose exec backend spouet-admin connectors list
docker logs -f spouet-conn-discord-bot-<8chars>
```

Auto-restart en cas de crash : tâche Celery `monitor_connectors` toutes les 30 s.

---

## 🔑 Vaultwarden (instance déjà existante)

Trois tools partagent une image. Pré-requis : un compte dédié sur ton Vaultwarden.

```bash
# 1. Build l'image partagée
docker build -t spouet/tool-vaultwarden:0.1.0 tools/registry/_shared/vaultwarden

# 2. Secrets globaux
echo -n "https://vault.example.com" | docker compose exec -T backend \
    spouet-admin secrets set --scope global --key vaultwarden_url
echo -n "ai-bot@example.com"        | docker compose exec -T backend \
    spouet-admin secrets set --scope global --key vaultwarden_email
echo -n "$MASTER_PASSWORD"          | docker compose exec -T backend \
    spouet-admin secrets set --scope global --key vaultwarden_password

# 3. Installe les 3 manifests
for slug in vaultwarden-list vaultwarden-get vaultwarden-set; do
  docker compose exec backend spouet-admin tools install ./tools/registry/$slug
done
```

Comme `network: bridge`, chaque appel déclenche une **approval HITL** dans l'UI.

---

## 🛠️ Commandes utiles (production Debian)

```bash
# Suivre la stack
docker compose ps
docker compose logs -f backend worker beat caddy

# Reset complet (⚠️ supprime DB et Redis)
docker compose down -v
rm -rf deploy/data

# Sauvegarde Postgres
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup-$(date +%F).sql

# Restauration
docker compose exec -T postgres psql -U $POSTGRES_USER $POSTGRES_DB < backup-2026-05-01.sql

# Vérifier l'état des nodes
curl -H "Authorization: Bearer $TOKEN" https://spouet.local/api/nodes | jq
curl -H "Authorization: Bearer $TOKEN" https://spouet.local/api/health | jq

# Vérifier les tool executions récentes
docker compose exec postgres psql -U $POSTGRES_USER $POSTGRES_DB \
    -c "SELECT created_at, status, exit_code, duration_ms FROM tool_executions ORDER BY created_at DESC LIMIT 20;"

# Mise à jour
git pull
docker compose build backend worker beat
docker compose up -d backend worker beat
docker compose exec backend alembic upgrade head
```

---

## 🧪 Vérification end-to-end

```bash
# 1. Health
curl https://spouet.local/api/health

# 2. Auth
curl -H "Authorization: Bearer $TOKEN" https://spouet.local/api/auth/me

# 3. Heartbeat depuis un node
SPOUET_AGENT_TOKEN=$TOKEN uv run spouet-agent run --backend https://spouet.local
# → vérifier dans l'UI qu'il apparaît "online"

# 4. Lancer un chat (M2+)
curl -N -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"hello","model":"llama3.1:8b"}' \
     https://spouet.local/api/chat/<conv_id>
```

---

## Licence

À définir.
