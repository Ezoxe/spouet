#!/usr/bin/env bash
# Spouet — installer serveur Debian/Ubuntu (one-liner).
#
# Usage typique :
#   curl -fsSL https://raw.githubusercontent.com/<owner>/spouet/main/install.sh | sudo bash
#
# Variables d'env reconnues (toutes optionnelles) :
#   SPOUET_REPO_URL       (def: https://github.com/<owner>/spouet.git)
#   SPOUET_BRANCH         (def: main)
#   SPOUET_INSTALL_DIR    (def: /opt/spouet)
#   SPOUET_HOSTNAME       (def: spouet.local)
#   SPOUET_ADMIN_EMAIL    (def: admin@local)
#   SPOUET_NON_INTERACTIVE (def: 0 — passe à 1 pour skip les prompts)
#   SPOUET_SKIP_DOCKER    (def: 0 — passe à 1 si Docker déjà géré)
#   SPOUET_SKIP_SYSTEMD   (def: 0)
#
# Drapeaux équivalents :
#   --hostname=...   --email=...   --branch=...   --dir=...
#   --non-interactive   --skip-docker   --skip-systemd

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
: "${SPOUET_REPO_URL:=https://github.com/maximehollie41/spouet.git}"
: "${SPOUET_BRANCH:=main}"
: "${SPOUET_INSTALL_DIR:=/opt/spouet}"
: "${SPOUET_HOSTNAME:=spouet.local}"
: "${SPOUET_ADMIN_EMAIL:=admin@local}"
: "${SPOUET_NON_INTERACTIVE:=0}"
: "${SPOUET_SKIP_DOCKER:=0}"
: "${SPOUET_SKIP_SYSTEMD:=0}"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hostname=*)        SPOUET_HOSTNAME="${1#*=}" ;;
        --email=*)           SPOUET_ADMIN_EMAIL="${1#*=}" ;;
        --branch=*)          SPOUET_BRANCH="${1#*=}" ;;
        --dir=*)             SPOUET_INSTALL_DIR="${1#*=}" ;;
        --repo=*)            SPOUET_REPO_URL="${1#*=}" ;;
        --non-interactive)   SPOUET_NON_INTERACTIVE=1 ;;
        --skip-docker)       SPOUET_SKIP_DOCKER=1 ;;
        --skip-systemd)      SPOUET_SKIP_SYSTEMD=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
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
    if [[ $EUID -ne 0 ]]; then
        die "Ce script doit être lancé en root (sudo bash install.sh)."
    fi
}

prompt() {
    # prompt VAR_NAME "Question" "default"
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

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
require_root

if ! command -v lsb_release &>/dev/null && [[ ! -f /etc/os-release ]]; then
    die "OS non identifié — Debian/Ubuntu requis."
fi
. /etc/os-release
case "${ID:-}" in
    debian|ubuntu|raspbian) : ;;
    *) warn "OS '$ID' non testé — l'installer cible Debian/Ubuntu, mais on tente quand même." ;;
esac

log "Hôte cible       : $SPOUET_HOSTNAME"
log "Répertoire       : $SPOUET_INSTALL_DIR"
log "Branche          : $SPOUET_BRANCH"
log "Email admin      : $SPOUET_ADMIN_EMAIL"

prompt SPOUET_HOSTNAME    "Hostname public Spouet (Caddy/TLS)" "$SPOUET_HOSTNAME"
prompt SPOUET_ADMIN_EMAIL "Email du premier compte admin"      "$SPOUET_ADMIN_EMAIL"

# ---------------------------------------------------------------------------
# 1. Dépendances système
# ---------------------------------------------------------------------------
log "Installation des dépendances système (git, openssl, curl, ca-certificates)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git openssl curl ca-certificates gnupg

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
# 3. Cloner / mettre à jour le dépôt
# ---------------------------------------------------------------------------
if [[ -d "$SPOUET_INSTALL_DIR/.git" ]]; then
    log "Dépôt existant — git pull…"
    git -C "$SPOUET_INSTALL_DIR" fetch --quiet origin "$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" checkout --quiet "$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" pull --quiet --ff-only
else
    log "Clone $SPOUET_REPO_URL → $SPOUET_INSTALL_DIR…"
    git clone --quiet --branch "$SPOUET_BRANCH" "$SPOUET_REPO_URL" "$SPOUET_INSTALL_DIR"
fi

cd "$SPOUET_INSTALL_DIR/deploy"

# ---------------------------------------------------------------------------
# 4. Génération du .env (idempotent)
# ---------------------------------------------------------------------------
gen_secret() { openssl rand -hex "$1"; }

if [[ ! -f .env ]]; then
    log "Génération de deploy/.env (secrets aléatoires)…"
    POSTGRES_PASSWORD=$(gen_secret 24)
    REDIS_PASSWORD=$(gen_secret 24)
    SPOUET_SECRET_KEY=$(gen_secret 32)
    cat > .env <<EOF
# --- Généré par install.sh le $(date -u +%FT%TZ) ---
SPOUET_PUBLIC_HOSTNAME=$SPOUET_HOSTNAME

POSTGRES_USER=spouet
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=spouet

REDIS_PASSWORD=$REDIS_PASSWORD

SPOUET_DATABASE_URL=postgresql+asyncpg://spouet:$POSTGRES_PASSWORD@postgres:5432/spouet
SPOUET_REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0
SPOUET_SECRET_KEY=$SPOUET_SECRET_KEY
SPOUET_LOG_LEVEL=INFO
SPOUET_CORS_ORIGINS=https://$SPOUET_HOSTNAME,tauri://localhost,http://localhost:5173

SPOUET_EMBEDDING_MODEL=nomic-embed-text
SPOUET_EMBEDDING_DIM=768

SPOUET_TOOL_DEFAULT_MEM_LIMIT=256m
SPOUET_TOOL_DEFAULT_CPU_LIMIT=1.0
SPOUET_TOOL_DEFAULT_TIMEOUT_S=30

SPOUET_NODE_OFFLINE_AFTER_S=30
EOF
    chmod 600 .env
else
    log "deploy/.env existant — conservé tel quel."
fi

# ---------------------------------------------------------------------------
# 5. Build + up
# ---------------------------------------------------------------------------
log "docker compose build…"
docker compose build

log "docker compose up -d…"
docker compose up -d

log "Attente backend healthy…"
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
# 7. systemd
# ---------------------------------------------------------------------------
if [[ "$SPOUET_SKIP_SYSTEMD" != "1" ]]; then
    log "Installation du service systemd spouet-stack…"
    UNIT_SRC="$SPOUET_INSTALL_DIR/deploy/systemd/spouet-stack.service"
    UNIT_DST="/etc/systemd/system/spouet-stack.service"
    if [[ -f "$UNIT_SRC" ]]; then
        # Adapter le WorkingDirectory si l'install dir n'est pas /opt/spouet
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
log "  → UI Caddy   : https://$SPOUET_HOSTNAME"
log "  → Logs       : (cd $SPOUET_INSTALL_DIR/deploy && docker compose logs -f backend)"
log "  → Status     : systemctl status spouet-stack"
