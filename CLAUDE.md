# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Vue d'ensemble

Spouet est une plateforme self-hosted d'orchestration multi-nodes Ollama. Architecture monorepo avec backend Python, frontend SvelteKit, app desktop Tauri, agent Python pour les machines Ollama, et registre de tools Docker.

Le backend tourne sur Debian (docker-compose). Les autres surfaces sont distribuées séparément.

## ⚠️ Environnement de développement

**Le poste de dev courant est sous Windows**. La cible de production est Debian. En conséquence :

- **NE JAMAIS** lancer `docker compose up`, `docker run`, `docker build` ni aucune commande Docker depuis ce poste. Le runtime Docker n'est pas l'environnement de prod, et toute manipulation est inutile et peut interférer avec d'autres projets.
- **NE JAMAIS** lancer `uvicorn`, `celery`, `alembic upgrade`, ou tout service backend en arrière-plan ici. Le code est destiné à tourner dans les conteneurs Debian.
- Pour les frontends (`pnpm dev` web, `pnpm tauri dev` desktop) : OK uniquement si l'utilisateur le demande explicitement.
- Lints / type-check / tests unitaires hors I/O (`ruff`, `mypy`, `pytest` avec mocks) : OK localement.
- Pour valider une modif end-to-end, l'utilisateur déploiera sur son Debian et fera tourner les commandes là-bas.

## Stack

- **Backend** : FastAPI 0.11x + Pydantic v2 + SQLAlchemy 2 (async) + Celery + Celery Beat + Redis
- **DB** : PostgreSQL 16 + extension PGVector (768-dim, modèle `nomic-embed-text`)
- **Frontend web** : SvelteKit 2 + Tailwind 4 + shadcn-svelte (PWA mobile-first)
- **Desktop** : Tauri 2.0 (Rust shell + frontend Svelte réutilisé)
- **Sandbox tools** : Docker SDK Python (`docker-py`), conteneur jetable par appel
- **Voix** : microservice `voice-engine` (faster-whisper STT + Piper TTS), self-hosted, conteneur dédié
- **Reverse proxy** : Caddy
- **Package manager Python** : `uv`
- **Package manager JS** : `pnpm`

## Commandes courantes

### Backend
```bash
cd backend
uv sync                              # install deps
uv run uvicorn spouet.main:app --reload --port 8000
uv run alembic upgrade head          # migrations
uv run alembic revision --autogenerate -m "msg"
uv run pytest                        # tous les tests
uv run pytest tests/test_router.py::test_pick_least_loaded -xvs   # un test
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run mypy spouet                   # types
uv run celery -A spouet.workers worker --loglevel=info
uv run celery -A spouet.workers beat --loglevel=info
uv run spouet-admin create-token --email me@local
```

### Web
```bash
cd web
pnpm install
pnpm dev                             # dev server :5173
pnpm build                           # production build (consommé par Tauri)
pnpm check                           # svelte-check + tsc
pnpm lint
```

### Desktop
```bash
cd desktop
pnpm tauri dev                       # build web puis lance Tauri
pnpm tauri build                     # MSI Windows
```

### Stack complète (dev local)
```bash
cd deploy
docker compose up -d                 # postgres + redis + caddy
docker compose logs -f backend
docker compose down -v               # reset complet (DROP DATA)
```

### Node-agent (sur chaque machine Ollama)
```bash
cd node-agent
uv sync
SPOUET_AGENT_TOKEN=$TOKEN uv run spouet-agent run \
    --backend http://debian:8000 \
    --ollama  http://localhost:11434 \
    --interval 10
```

### Installeurs (prod, one-liner)

Les scripts à la racine et dans chaque surface sont la voie d'install canonique en prod, idempotents (relancer = update) :
- `install.sh` (root) → stack serveur Debian (clone vers `/opt/spouet`, génère `deploy/.env`, build/up, migrations, premier token admin, service `spouet-stack`).
- `node-agent/install.sh` / `install.ps1` → daemon heartbeat Linux (systemd) ou Windows (NSSM, service `SpouetAgent`).
- `desktop/install.ps1` → installe le dernier MSI publié par CI (`.github/workflows/release.yml` sur tag `v*`).

## Architecture

- **Découverte des nodes Ollama** : pas de mDNS natif Ollama. Chaque machine Ollama exécute un `node-agent` qui poste un heartbeat HTTP toutes les 10s avec son état (modèles installés, modèles en RAM, VRAM utilisée). Le backend marque un node `offline` si pas de heartbeat depuis 30s (tâche Celery périodique).
- **Routage des prompts** : `nodes/router.py` choisit un node selon le modèle demandé + VRAM dispo + charge actuelle. Failover automatique si un node crash en streaming.
- **Streaming** : SSE par défaut pour les tokens LLM. WebSocket pour les besoins HITL et la synchronisation multi-device. Redis pub/sub diffuse les events à tous les clients abonnés à `conv:{id}`.
- **Tool calling** : utilise le format natif Ollama (`/api/chat` avec `tools=[...]`). L'orchestrator détecte les `tool_calls` dans le stream, suspend, exécute en Docker, réinjecte `role: tool`.
- **Sandboxing tools** : chaque appel = un conteneur Docker jetable avec `--network none` (par défaut), `--read-only`, `--cap-drop=ALL`, mem_limit, cpu_limit, timeout. Modes réseau : `none` (isolation), `bridge` (sortie Internet), `internal` (attaché au réseau docker-compose Spouet pour résoudre `backend` — utilisé par les tools `spouet-*` qui appellent l'API). Tout mode ≠ `none` requiert une approval HITL par défaut.
- **Coffre de secrets** : Fernet (clé dérivée de `SPOUET_SECRET_KEY`), stockage chiffré en DB, jamais réaffiché en clair. Injecté dans les tools/connectors via `manifest.secrets: { ENV_VAR: scope/key }` (scopes : `global`, `tool:<slug>`, `connector:<slug>`).
- **Connectors persistants** : à la différence des tools (jetables), un connector est un conteneur Docker long-running (Discord, Telegram, IMAP…) qui rend l'IA joignable depuis l'extérieur. Cycle de vie géré par `connectors/manager.py` ; tâche Celery `monitor_connectors` (30s) auto-restart les conteneurs crashés. Format documenté dans `docs/connectors-authoring.md`.
- **RAG** : embeddings via Ollama (`nomic-embed-text`), stockés dans PGVector (index `ivfflat`). Abstraction `VectorStore` permet de swap vers Qdrant plus tard.
- **Voix (STT/TTS)** : microservice `voice-engine` (conteneur dédié, hors backend) embarque faster-whisper (reconnaissance) + Piper (synthèse FR). Le frontend capture le micro via `MediaRecorder` (fonctionne dans WebView2/Tauri, contrairement à la Web Speech API), POST `/api/voice/transcribe`, puis lit l'audio renvoyé par `/api/voice/speak`. Le backend (`voice/client.py`) ne fait que proxifier avec auth. Repli navigateur (`SpeechSynthesis`) si le service est indisponible. Le service n'est jamais exposé au LAN (pas de `ports`).
- **Mail** : module `mail/` (IMAP en lecture `readonly` + SMTP) piloté par la tâche Celery `sync_mail_accounts` (toutes les 3 min, verrou Redis anti-chevauchement). Chaque nouveau mail est classé par le LLM (spam / important / normal / newsletter / notification + score + `needs_reply` + résumé). Garde-fous **par conception** : les spams sont *déplacés* vers un dossier (jamais supprimés), et toute réponse est un brouillon `pending` qui n'est **envoyé que sur validation explicite** (`POST /api/mail/drafts/{id}/send`). Identifiants stockés au coffre (scope `mail:<account_id>`).
- **Spotify** : module `spotify/` (OAuth Authorization Code + refresh). Le contrôle de lecture passe par `POST /api/spotify/control`, consommé à la fois par l'UI (`/spotify`) et par le tool `spotify` (réseau `internal`) que l'IA invoque pour lancer/piloter la musique. `refresh_token` au coffre (scope `spotify:<user_id>`), `access_token` caché en Redis. Premium + appareil actif requis (l'API Web pilote un appareil Connect existant, elle ne crée pas de lecteur).
- **Pilotage du PC (desktop)** : contrairement aux tools (Docker côté serveur, qui ne peuvent pas toucher le bureau), les **actions desktop** (lancer une app, ouvrir une URL, cibler un écran) s'exécutent **côté client (app Tauri)**. L'orchestrator publie une demande `desktop_action` sur le canal `user:{id}` et **attend** le résultat (même pattern que l'approval HITL — `desktop/bridge.py`, miroir de `tools/approval.py`). Le client Tauri tient une connexion SSE persistante (`/sse/user`, agent `web/src/lib/realtime.ts`), exécute via des commandes Rust natives (`desktop/src-tauri/src/desktop_actions.rs` : `ShellExecuteExW` + placement de fenêtre best-effort par PID→HWND), puis POST le résultat sur `/api/desktop/actions/{id}/result`. Les capacités du poste (écrans, apps détectées) sont publiées via `/api/desktop/hello` et stockées en Redis (TTL court, `desktop/registry.py`) → la **persona devient capability-aware** (n'expose les tools de pilotage que si un client est connecté). Garde-fou : `launch_app` n'accepte que des **apps détectées**.
- **Macros desktop** : séquences d'actions bureau nommées (« soirée Minecraft »), table `desktop_macros` (user-scopée). Le LLM les apprend en conversation : `run_macro` sur une macro inconnue → demande à l'utilisateur → `define_macro` (validation HITL affichant les étapes) → sauvegarde → exécution. Gérables aussi via l'UI `/macros`.
- **Recherche web** : module `websearch/` (SearXNG self-hosted, conteneur interne jamais exposé au LAN). Appel **in-process httpx async** (PAS un tool Docker → latence minimale) + cache Redis court. Exposé au LLM via le built-in `web_search` (texte/images).
- **Visuels / overlay** : built-in `show_visual` (image/carte/fait) → event `visual` sur `user:{id}` (+ `conv:{id}`). Fenêtre Tauri `overlay` (transparente, click-through, always-on-top, route `/overlay`) qui flashe le visuel avec animations ; rendu inline aussi dans le chat/companion (`VisualCard.svelte`). Images servies via le proxy authentifié `/api/visual/proxy` (anti mixed-content/CORS).
- **Tools built-in** : `orchestrator/builtin_tools.py` déclare et exécute en-process (hors Docker) `web_search`, `show_visual`, `list_macros`, `run_desktop_action`, `run_macro`, `define_macro` — sur le modèle de `delegate_to_node`. Dispatch dans `chat_loop._execute_tool_call` avant le lookup des tools Docker.

## Modules backend

| Package | Rôle |
|---|---|
| `api/` | Routes FastAPI (REST + SSE + WS) |
| `core/` | Config (pydantic-settings), logging, security, DI |
| `db/` | Models SQLAlchemy 2 + Alembic |
| `nodes/` | Registry, health checker, router, client httpx vers Ollama |
| `orchestrator/` | Boucle chat ↔ tools, streaming, troncature contexte, persona |
| `tools/` | Loader manifest, registry, runner Docker jetable, JSON-Schema validator |
| `connectors/` | Manifest + manager (cycle de vie des bridges Docker long-running) + bridge HTTP backend ↔ conteneur |
| `secrets/` | Coffre Fernet (chiffrement, scopes, injection en env var) |
| `scheduler/` | Définitions Celery Beat dynamiques (DB-backed) |
| `rag/` | Ingest, retriever PGVector, abstraction VectorStore |
| `voice/` | Pont httpx vers le microservice voice-engine (STT/TTS) |
| `mail/` | Boîtes IMAP/SMTP, tri IA, réponses validées en HITL |
| `spotify/` | OAuth Spotify + contrôle de lecture (Connect) |
| `desktop/` | Pont d'actions client (app Tauri) + registre de capacités (Redis) |
| `websearch/` | Recherche web rapide in-process (SearXNG self-hosted) |
| `memory/` | Key/value persistant + résumé conversationnel |
| `realtime/` | Hub SSE/WS backed par Redis pub/sub |
| `workers/` | Tâches Celery (heartbeat sweeper, monitor_connectors, scheduler runs) |
| `cli/` | `spouet-admin` (Typer) — tokens, tools, secrets, connectors |

## Format des tools custom

Chaque tool dans `tools/registry/<slug>/` :
- `manifest.yaml` (slug, image, network, timeout, mem_limit, input_schema, output_schema)
- `Dockerfile`
- `run.py` (lit JSON sur stdin, écrit JSON sur stdout)
- `README.md`

Installation : `spouet-admin tools install ./tools/registry/<slug>` → build image + insert row dans `tools`.

## Conventions

- Toutes les valeurs de config via `pydantic-settings` (préfixe `SPOUET_`)
- IDs UUID v4 partout (jamais d'auto-increment exposé)
- Timestamps en UTC (`datetime.now(timezone.utc)`)
- Async-first : SQLAlchemy async, httpx async, FastAPI dependencies async
- Pas de `print` : utiliser `core.logging.get_logger(__name__)`
- Token API : header `Authorization: Bearer ...`, hash SHA-256 en DB (jamais en clair)

## Variables d'environnement utiles

- `SPOUET_FORCE_CPU=1` (node-agent) : court-circuite la détection GPU, force `compute_class=cpu`. Filet de sécurité si la détection se trompe sur un dGPU non utilisable.
- `SPOUET_METRICS_RETENTION_DAYS` (backend, défaut 7) : durée de conservation de `node_metrics_1min`. La table `node_metrics_raw` est toujours purgée à 24h.
- `SPOUET_CONNECTORS_REGISTRY_DIR` (backend, défaut `/opt/spouet/connectors/registry`) : chemin où le wizard Discord cherche le manifest canonique.
- `SPOUET_WHISPER_MODEL` / `SPOUET_WHISPER_DEVICE` / `SPOUET_WHISPER_COMPUTE_TYPE` / `SPOUET_PIPER_VOICE` (service `voice-engine`) : modèle Whisper (`small` par défaut), device (`cpu`/`cuda`), type de calcul, et voix Piper FR. Cf. `voice-engine/README.md`. Premier démarrage = téléchargement des modèles (volume `deploy/data/voice`).
- `SPOUET_SEARXNG_URL` (backend, défaut `http://searxng:8080`) / `SPOUET_WEBSEARCH_ENABLED` (défaut `true`) : recherche web. Le service `searxng` (docker-compose) embarque `deploy/searxng/settings.yml` qui **active la sortie JSON** (consommée par `websearch/client.py`) et désactive le limiteur. `SEARXNG_SECRET` (compose) = secret interne SearXNG. Jamais exposé au LAN.
- `SPOUET_SPOTIFY_*` : cf. section Spotify ci-dessus.
- `SPOUET_VOICE_ENABLED` (backend, défaut `true`) : coupe proprement les endpoints `/api/voice/*` et le check santé voix si la voix n'est pas déployée.
- `SPOUET_SPOTIFY_CLIENT_ID` / `SPOUET_SPOTIFY_CLIENT_SECRET` / `SPOUET_SPOTIFY_REDIRECT_URI` (backend) : OAuth Spotify. App créée sur developer.spotify.com ; le `redirect_uri` doit correspondre exactement (ex. `https://spouet.local/api/spotify/callback`). Vide = intégration Spotify désactivée.

## Capabilities : source unique de vérité hardware

Depuis la v0.3.0 du node-agent, la classification CPU vs CUDA vs ROCm + dGPU vs iGPU est centralisée dans `node-agent/spouet_agent/capabilities.py::probe_capabilities()`. Le résultat est sérialisé dans le heartbeat, persisté en JSONB sur `nodes.capabilities`, et consommé par `compute_optimal_config()` + `LlamaServer._build_cmd` (garde-fou anti-GPU-sur-CPU). Pour debug : `sudo -u spouet uv run --directory /opt/spouet/node-agent spouet-agent detect --json`.
