#!/usr/bin/env bash
# Spouet — installer serveur Debian/Ubuntu (one-liner).
#
# Usage typique :
#   curl -fsSL https://raw.githubusercontent.com/<owner>/spouet/master/install.sh | sudo bash
#   # OU depuis le dépôt déjà cloné :
#   sudo bash install.sh
#
# Variables d'env reconnues (toutes optionnelles) :
#   SPOUET_REPO_URL        (def: https://github.com/ezoxe/spouet.git)
#   SPOUET_BRANCH          (def: master)
#   SPOUET_INSTALL_DIR     (def: /opt/spouet)
#   SPOUET_ADMIN_EMAIL     (def: admin@local)
#   SPOUET_NON_INTERACTIVE (def: 0 — passe à 1 pour skip les prompts)
#   SPOUET_SKIP_DOCKER     (def: 0 — passe à 1 si Docker déjà géré)
#   SPOUET_SKIP_SYSTEMD    (def: 0)
#
# Drapeaux équivalents :
#   --email=...   --branch=...   --dir=...
#   --non-interactive   --skip-docker   --skip-systemd

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
: "${SPOUET_REPO_URL:=https://github.com/ezoxe/spouet.git}"
: "${SPOUET_BRANCH:=master}"
: "${SPOUET_INSTALL_DIR:=/opt/spouet}"
: "${SPOUET_ADMIN_EMAIL:=admin@local}"
: "${SPOUET_NON_INTERACTIVE:=0}"
: "${SPOUET_SKIP_DOCKER:=0}"
: "${SPOUET_SKIP_SYSTEMD:=0}"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --email=*)           SPOUET_ADMIN_EMAIL="${1#*=}" ;;
        --branch=*)          SPOUET_BRANCH="${1#*=}" ;;
        --dir=*)             SPOUET_INSTALL_DIR="${1#*=}" ;;
        --repo=*)            SPOUET_REPO_URL="${1#*=}" ;;
        --non-interactive)   SPOUET_NON_INTERACTIVE=1 ;;
        --skip-docker)       SPOUET_SKIP_DOCKER=1 ;;
        --skip-systemd)      SPOUET_SKIP_SYSTEMD=1 ;;
        -h|--help)
            sed -n '2,28p' "$0"; exit 0 ;;
        *)
            echo "Argument inconnu: $1" >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;36m[spouet]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[spouet]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[spouet]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || die "Ce script doit être lancé en root (sudo bash install.sh)."
}

prompt() {
    local var="$1" question="$2" def="${3:-}"
    if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then return; fi
    local current="${!var}"
    [[ "$current" != "$def" && -n "$current" ]] && return
    local answer
    if [[ -n "$def" ]]; then
        read -rp "$question [$def] : " answer </dev/tty || true
    else
        read -rp "$question : " answer </dev/tty || true
    fi
    [[ -n "$answer" ]] && printf -v "$var" '%s' "$answer"
}

# Retourne la liste des ports déjà utilisés (système + conteneurs Docker actifs)
_used_ports_list() {
    ss -tlnp 2>/dev/null \
        | awk 'NR>1 { n=split($4,a,":"); p=a[n]+0; if(p>0) print p }'
    docker ps --format '{{.Ports}}' 2>/dev/null \
        | sed 's/[, ]\+/\n/g' \
        | sed -n 's/.*:\([0-9]*\)->.*/\1/p' \
        | grep -E '^[0-9]+$' || true
}

# Trouve le premier port libre >= min (recherche dans système + Docker)
find_free_port() {
    local min="${1:-10000}"
    local max=$(( min + 2000 ))
    local port=$min
    local used
    used="$(_used_ports_list | sort -un)"
    while printf '%s\n' "$used" | grep -qxF "$port" && (( port < max )); do
        (( port++ ))
    done
    (( port < max )) || die "Aucun port libre trouvé entre $min et $max."
    echo "$port"
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
require_root

[[ -f /etc/os-release ]] || die "OS non identifié — Debian/Ubuntu requis."
. /etc/os-release
case "${ID:-}" in
    debian|ubuntu|raspbian) : ;;
    *) warn "OS '$ID' non testé — l'installer cible Debian/Ubuntu, mais on tente quand même." ;;
esac

# Détecter si le script est lancé depuis le dépôt lui-même
SCRIPT_SRC="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SRC" && "$SCRIPT_SRC" != "/dev/stdin" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SRC")" && pwd)"
else
    SCRIPT_DIR="$(pwd)"
fi

_GIT_DETECTED=0
if [[ -d "$SCRIPT_DIR/.git" ]]; then
    log "Dépôt git détecté dans $SCRIPT_DIR — utilisation directe, pas de clone."
    SPOUET_INSTALL_DIR="$SCRIPT_DIR"
    _GIT_DETECTED=1
fi

log "Répertoire       : $SPOUET_INSTALL_DIR"
log "Branche          : $SPOUET_BRANCH"
log "Email admin      : $SPOUET_ADMIN_EMAIL"

prompt SPOUET_ADMIN_EMAIL "Email du premier compte admin" "$SPOUET_ADMIN_EMAIL"

# ---------------------------------------------------------------------------
# 1. Dépendances système
# ---------------------------------------------------------------------------
log "Installation des dépendances système (git, openssl, curl, ca-certificates)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git openssl curl ca-certificates gnupg iproute2

# ---------------------------------------------------------------------------
# 2. Docker + Compose v2
# ---------------------------------------------------------------------------
if [[ "$SPOUET_SKIP_DOCKER" != "1" ]]; then
    if ! command -v docker &>/dev/null; then
        log "Installation de Docker (script officiel get.docker.com)…"
        curl -fsSL https://get.docker.com | sh
    else
        log "Docker déjà présent : $(docker --version)"
    fi
    if ! docker compose version &>/dev/null; then
        log "Installation du plugin docker-compose-plugin…"
        apt-get install -y -qq docker-compose-plugin
    fi
    systemctl enable --now docker
fi

# ---------------------------------------------------------------------------
# 2b. Inventaire des conteneurs Docker existants
# ---------------------------------------------------------------------------
log "Conteneurs Docker actuellement en cours d'exécution :"
RUNNING_CONTAINERS=$(docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || true)
RUNNING_COUNT=$(docker ps -q 2>/dev/null | wc -l || echo 0)
if [[ "$RUNNING_COUNT" -gt 0 ]]; then
    echo "$RUNNING_CONTAINERS"
    warn "$RUNNING_COUNT conteneur(s) en cours — les ports seront pris en compte lors de l'allocation."
else
    log "  (aucun conteneur actif)"
fi

# ---------------------------------------------------------------------------
# 3. Cloner / mettre à jour / ignorer le dépôt
# ---------------------------------------------------------------------------
if [[ "$_GIT_DETECTED" == "1" ]]; then
    log "Script lancé depuis le dépôt local — étape git ignorée."
elif [[ -d "$SPOUET_INSTALL_DIR/.git" ]]; then
    log "Dépôt existant dans $SPOUET_INSTALL_DIR — git pull…"
    git -C "$SPOUET_INSTALL_DIR" fetch --quiet origin "$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" checkout --quiet "$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" pull --quiet --ff-only
else
    log "Clone $SPOUET_REPO_URL → $SPOUET_INSTALL_DIR…"
    git clone --quiet --branch "$SPOUET_BRANCH" "$SPOUET_REPO_URL" "$SPOUET_INSTALL_DIR"
fi

cd "$SPOUET_INSTALL_DIR/deploy"

# ---------------------------------------------------------------------------
# 3b. Purge optionnelle des données Spouet existantes
# ---------------------------------------------------------------------------
_SPOUET_CONTAINERS=$(docker ps -a --filter "label=com.docker.compose.project=spouet" -q 2>/dev/null || true)
_SPOUET_HAS_DATA=0
[[ -d "data" || -f ".env" ]] && _SPOUET_HAS_DATA=1

if [[ -n "$_SPOUET_CONTAINERS" || "$_SPOUET_HAS_DATA" == "1" ]]; then
    warn "Données Spouet existantes détectées :"
    if [[ -n "$_SPOUET_CONTAINERS" ]]; then
        _NAMES=$(docker ps -a --filter "label=com.docker.compose.project=spouet" \
                     --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')
        warn "  Conteneurs : $_NAMES"
    fi
    [[ -f ".env" ]]          && warn "  Fichier    : deploy/.env (secrets)"
    [[ -d "data/postgres" ]] && warn "  Données    : deploy/data/postgres/"
    [[ -d "data/redis" ]]    && warn "  Données    : deploy/data/redis/"
    echo

    _PURGE="n"
    if [[ "$SPOUET_NON_INTERACTIVE" != "1" ]]; then
        printf '\033[1;33m[spouet]\033[0m Purger complètement les conteneurs et données Spouet ? [y/N] : '
        read -r _PURGE </dev/tty || true
    fi

    if [[ "${_PURGE,,}" == "y" ]]; then
        log "Arrêt et suppression des conteneurs Spouet…"
        docker compose down -v --remove-orphans 2>/dev/null || true
        log "Suppression des données Spouet (bind mounts + .env)…"
        rm -rf data/ .env .first-token-issued
        log "Purge terminée — installation repart de zéro."
    else
        log "Purge ignorée — données existantes conservées."
    fi
fi

# ---------------------------------------------------------------------------
# 4. Génération du .env (idempotent)
# ---------------------------------------------------------------------------
gen_secret() { openssl rand -hex "$1"; }

if [[ ! -f .env ]]; then
    log "Détection des ports libres (>= 10000, hors système et Docker existant)…"
    PORT_PG=$(find_free_port 10000)
    PORT_REDIS=$(find_free_port $(( PORT_PG + 1 )))
    PORT_BACKEND=$(find_free_port $(( PORT_REDIS + 1 )))
    PORT_WEB=$(find_free_port $(( PORT_BACKEND + 1 )))
    log "  postgres → :$PORT_PG   redis → :$PORT_REDIS   backend → :$PORT_BACKEND   web → :$PORT_WEB"

    POSTGRES_PASSWORD=$(gen_secret 24)
    REDIS_PASSWORD=$(gen_secret 24)
    SPOUET_SECRET_KEY=$(gen_secret 32)

    cat > .env <<EOF
# --- Généré par install.sh le $(date -u +%FT%TZ) ---

POSTGRES_USER=spouet
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=spouet

REDIS_PASSWORD=$REDIS_PASSWORD

SPOUET_DATABASE_URL=postgresql+asyncpg://spouet:$POSTGRES_PASSWORD@postgres:5432/spouet
SPOUET_REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0
SPOUET_SECRET_KEY=$SPOUET_SECRET_KEY
SPOUET_LOG_LEVEL=INFO
SPOUET_CORS_ORIGINS=["http://localhost:$PORT_BACKEND","tauri://localhost","http://localhost:5173"]

SPOUET_EMBEDDING_MODEL=nomic-embed-text
SPOUET_EMBEDDING_DIM=768

SPOUET_TOOL_DEFAULT_MEM_LIMIT=256m
SPOUET_TOOL_DEFAULT_CPU_LIMIT=1.0
SPOUET_TOOL_DEFAULT_TIMEOUT_S=30

SPOUET_NODE_OFFLINE_AFTER_S=30

# Ports hôte alloués dynamiquement
SPOUET_POSTGRES_PORT=$PORT_PG
SPOUET_REDIS_PORT=$PORT_REDIS
SPOUET_BACKEND_PORT=$PORT_BACKEND
SPOUET_WEB_PORT=$PORT_WEB
EOF
    chmod 600 .env
else
    log "deploy/.env existant — conservé tel quel."
    PORT_BACKEND=$(grep -E '^SPOUET_BACKEND_PORT=' .env | cut -d= -f2 || true)
    PORT_BACKEND="${PORT_BACKEND:-10002}"
    PORT_WEB=$(grep -E '^SPOUET_WEB_PORT=' .env | cut -d= -f2 || true)
    PORT_WEB="${PORT_WEB:-10003}"
fi

# ---------------------------------------------------------------------------
# 5. Build + up
# ---------------------------------------------------------------------------
log "docker compose build…"
docker compose build

log "docker compose up -d…"
docker compose up -d

log "Attente backend healthy (max 180s)…"
deadline=$(( $(date +%s) + 180 ))
until docker compose exec -T backend curl -fsS --max-time 2 http://127.0.0.1:8000/api/health &>/dev/null; do
    if (( $(date +%s) > deadline )); then
        docker compose logs --tail=80 backend
        die "Backend n'a pas démarré dans les 180s."
    fi
    sleep 3
done

# ---------------------------------------------------------------------------
# 6. Migrations + premier token
# ---------------------------------------------------------------------------
log "Migrations Alembic…"
docker compose exec -T backend alembic upgrade head

TOKEN_FLAG_FILE="$SPOUET_INSTALL_DIR/deploy/.first-token-issued"
if [[ ! -f "$TOKEN_FLAG_FILE" ]]; then
    log "Création du premier token admin (email=$SPOUET_ADMIN_EMAIL)…"
    set +e
    TOKEN_OUTPUT=$(docker compose exec -T backend spouet-admin create-token --email "$SPOUET_ADMIN_EMAIL" 2>&1)
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
        touch "$TOKEN_FLAG_FILE"
        echo
        echo "==========================================================="
        echo " TOKEN ADMIN — copie-le MAINTENANT, il ne sera plus affiché"
        echo "==========================================================="
        echo "$TOKEN_OUTPUT"
        echo "==========================================================="
        echo
    else
        warn "create-token a échoué :"
        echo "$TOKEN_OUTPUT" >&2
        warn "Tu peux le créer plus tard : docker compose exec backend spouet-admin create-token --email <addr>"
    fi
else
    log "Premier token déjà émis (flag $TOKEN_FLAG_FILE) — skip."
fi

# ---------------------------------------------------------------------------
# 6b. Installation des tools custom (build images + insert en DB)
# ---------------------------------------------------------------------------
TOOLS_FLAG_FILE="$SPOUET_INSTALL_DIR/deploy/.tools-installed"
if [[ ! -f "$TOOLS_FLAG_FILE" ]] && [[ -x "$SPOUET_INSTALL_DIR/tools/install-all.sh" ]]; then
    log "Installation des tools custom (registry)…"
    set +e
    (cd "$SPOUET_INSTALL_DIR" && bash tools/install-all.sh) 2>&1 | tee /tmp/spouet-tools-install.log
    rc=${PIPESTATUS[0]}
    set -e
    if [[ $rc -eq 0 ]]; then
        touch "$TOOLS_FLAG_FILE"
        log "Tools installés. (Re-run : bash $SPOUET_INSTALL_DIR/tools/install-all.sh)"
    else
        warn "Installation des tools incomplète — voir /tmp/spouet-tools-install.log"
    fi
fi

# ---------------------------------------------------------------------------
# 7. systemd
# ---------------------------------------------------------------------------
if [[ "$SPOUET_SKIP_SYSTEMD" != "1" ]]; then
    UNIT_SRC="$SPOUET_INSTALL_DIR/deploy/systemd/spouet-stack.service"
    UNIT_DST="/etc/systemd/system/spouet-stack.service"
    if [[ -f "$UNIT_SRC" ]]; then
        log "Installation du service systemd spouet-stack…"
        sed "s|/opt/spouet|$SPOUET_INSTALL_DIR|g" "$UNIT_SRC" > "$UNIT_DST"
        systemctl daemon-reload
        systemctl enable --now spouet-stack
        log "spouet-stack actif (auto-start au boot)."
    else
        warn "Unit file introuvable: $UNIT_SRC"
    fi
fi

# ---------------------------------------------------------------------------
log "✓ Installation terminée."
log "  → Web UI      : http://localhost:$PORT_WEB  (navigateur / PWA mobile)"
log "  → Backend API : http://localhost:$PORT_BACKEND/api/docs"
log "  → Logs        : (cd $SPOUET_INSTALL_DIR/deploy && docker compose logs -f)"
log "  → Status      : systemctl status spouet-stack"
log ""
log "  Pour l'app desktop Windows (Tauri), construire avec :"
log "    cd desktop"
log "    PUBLIC_API_BASE=http://<IP_SERVEUR>:$PORT_BACKEND pnpm tauri build"
