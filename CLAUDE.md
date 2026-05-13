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
- **DB** : PostgreSQL 16 + extension PGVector (1024-dim, modèle `nomic-embed-text`)
- **Frontend web** : SvelteKit 2 + Tailwind 4 + shadcn-svelte (PWA mobile-first)
- **Desktop** : Tauri 2.0 (Rust shell + frontend Svelte réutilisé)
- **Sandbox tools** : Docker SDK Python (`docker-py`), conteneur jetable par appel
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
- **Sandboxing tools** : chaque appel = un conteneur Docker jetable avec `--network none` (par défaut), `--read-only`, `--cap-drop=ALL`, mem_limit, cpu_limit, timeout. Les tools `network: bridge` requièrent une approval HITL.
- **Coffre de secrets** : Fernet (clé dérivée de `SPOUET_SECRET_KEY`), stockage chiffré en DB, jamais réaffiché en clair. Injecté dans les tools/connectors via `manifest.secrets: { ENV_VAR: scope/key }` (scopes : `global`, `tool:<slug>`, `connector:<slug>`).
- **Connectors persistants** : à la différence des tools (jetables), un connector est un conteneur Docker long-running (Discord, Telegram, IMAP…) qui rend l'IA joignable depuis l'extérieur. Cycle de vie géré par `connectors/manager.py` ; tâche Celery `monitor_connectors` (30s) auto-restart les conteneurs crashés. Format documenté dans `docs/connectors-authoring.md`.
- **RAG** : embeddings via Ollama (`nomic-embed-text`), stockés dans PGVector (index `ivfflat`). Abstraction `VectorStore` permet de swap vers Qdrant plus tard.

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

## Capabilities : source unique de vérité hardware

Depuis la v0.3.0 du node-agent, la classification CPU vs CUDA vs ROCm + dGPU vs iGPU est centralisée dans `node-agent/spouet_agent/capabilities.py::probe_capabilities()`. Le résultat est sérialisé dans le heartbeat, persisté en JSONB sur `nodes.capabilities`, et consommé par `compute_optimal_config()` + `LlamaServer._build_cmd` (garde-fou anti-GPU-sur-CPU). Pour debug : `sudo -u spouet uv run --directory /opt/spouet/node-agent spouet-agent detect --json`.
