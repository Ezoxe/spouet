#!/usr/bin/env bash
# Spouet — setup/mise à jour de la stack depuis un dépôt déjà cloné.
#
# Idempotent. À lancer depuis deploy/. Fait tout d'un coup : génère .env (1re
# fois, avec détection de ports libres), build + up des conteneurs, attend que
# le backend soit healthy, applique les migrations Alembic ET les vérifie,
# (ré)installe les tools du registry, puis affiche le token admin (1re fois,
# ou à la demande avec --new-token).
#
# Usage :
#   bash install.sh                 # setup / mise à jour complète
#   bash install.sh --new-token     # régénère + affiche un token (token perdu)
#   bash install.sh --email=me@x    # email du compte admin (1re fois / rotation ciblée)
#   bash install.sh --no-build      # skip le build (juste up + migrate + token)
#   bash install.sh --skip-tools    # ne pas (ré)installer les tools du registry
set -euo pipefail

EMAIL=""
DO_BUILD=1
DO_TOOLS=1
NEW_TOKEN=0
for arg in "$@"; do
    case "$arg" in
        --email=*)              EMAIL="${arg#*=}" ;;
        --new-token|--rotate-token) NEW_TOKEN=1 ;;
        --no-build)             DO_BUILD=0 ;;
        --skip-tools)           DO_TOOLS=0 ;;
        -h|--help)              sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "Argument inconnu: $arg" >&2; exit 2 ;;
    esac
done

log()  { printf '\033[1;36m[spouet]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[spouet]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[spouet]\033[0m %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"                       # deploy/
ROOT_DIR="$(cd .. && pwd)"

command -v docker >/dev/null 2>&1 || die "docker introuvable."
docker compose version >/dev/null 2>&1 || die "plugin 'docker compose' introuvable."
[[ -f docker-compose.yml ]] || die "docker-compose.yml absent — lance ce script depuis deploy/."

# ---------------------------------------------------------------------------
# Ports libres (système + conteneurs Docker), utilisé seulement à la 1re config
# ---------------------------------------------------------------------------
_used_ports() {
    ss -tlnp 2>/dev/null | awk 'NR>1 { n=split($4,a,":"); p=a[n]+0; if(p>0) print p }'
    docker ps --format '{{.Ports}}' 2>/dev/null \
        | sed 's/[, ]\+/\n/g' | sed -n 's/.*:\([0-9]*\)->.*/\1/p' | grep -E '^[0-9]+$' || true
}
find_free_port() {
    local min="${1:-10000}" max port used
    max=$(( min + 2000 )); port=$min
    used="$(_used_ports | sort -un)"
    while printf '%s\n' "$used" | grep -qxF "$port" && (( port < max )); do (( port++ )); done
    (( port < max )) || die "Aucun port libre entre $min et $max."
    echo "$port"
}
gen() { openssl rand -hex "$1"; }

# ---------------------------------------------------------------------------
# .env (généré une seule fois ; conservé ensuite)
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    log "Première config : détection des ports libres (>= 10000)…"
    PORT_PG=$(find_free_port 10000)
    PORT_REDIS=$(find_free_port $(( PORT_PG + 1 )))
    PORT_BACKEND=$(find_free_port $(( PORT_REDIS + 1 )))
    PORT_WEB=$(find_free_port $(( PORT_BACKEND + 1 )))
    log "  postgres :$PORT_PG  redis :$PORT_REDIS  backend :$PORT_BACKEND  web :$PORT_WEB"
    PGP=$(gen 24); RDP=$(gen 24); SK=$(gen 32); SXNG=$(gen 24)
    cat > .env <<EOF
# --- genere par deploy/install.sh le $(date -u +%FT%TZ) ---
POSTGRES_USER=spouet
POSTGRES_PASSWORD=$PGP
POSTGRES_DB=spouet
REDIS_PASSWORD=$RDP
SPOUET_DATABASE_URL=postgresql+asyncpg://spouet:$PGP@postgres:5432/spouet
SPOUET_REDIS_URL=redis://:$RDP@redis:6379/0
SPOUET_SECRET_KEY=$SK
SPOUET_LOG_LEVEL=INFO
SPOUET_CORS_ORIGINS=["http://localhost:$PORT_BACKEND","tauri://localhost","http://localhost:5173"]
SPOUET_EMBEDDING_MODEL=nomic-embed-text
SPOUET_EMBEDDING_DIM=768
SPOUET_TOOL_DEFAULT_MEM_LIMIT=256m
SPOUET_TOOL_DEFAULT_CPU_LIMIT=1.0
SPOUET_TOOL_DEFAULT_TIMEOUT_S=30
SPOUET_NODE_OFFLINE_AFTER_S=30
SEARXNG_SECRET=$SXNG
SPOUET_SEARXNG_URL=http://searxng:8080
SPOUET_POSTGRES_PORT=$PORT_PG
SPOUET_REDIS_PORT=$PORT_REDIS
SPOUET_BACKEND_PORT=$PORT_BACKEND
SPOUET_WEB_PORT=$PORT_WEB
EOF
    chmod 600 .env
else
    log "deploy/.env présent — conservé tel quel."
fi

get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- ; }
PORT_WEB="$(get_env SPOUET_WEB_PORT)";     PORT_WEB="${PORT_WEB:-?}"
PORT_BACKEND="$(get_env SPOUET_BACKEND_PORT)"; PORT_BACKEND="${PORT_BACKEND:-?}"

# ---------------------------------------------------------------------------
# Volumes en uid 1000 (conteneurs non-root) — évite les PermissionError
# ---------------------------------------------------------------------------
mkdir -p data/voice data/images
chown -R 1000:1000 data/voice data/images 2>/dev/null || true

# ---------------------------------------------------------------------------
# Build + up
# ---------------------------------------------------------------------------
if [[ "$DO_BUILD" == 1 ]]; then
    log "docker compose build…"
    docker compose build
fi
log "docker compose up -d…"
docker compose up -d

# ---------------------------------------------------------------------------
# Attente backend healthy
# ---------------------------------------------------------------------------
log "Attente backend healthy (max 180s)…"
deadline=$(( $(date +%s) + 180 ))
until docker compose exec -T backend curl -fsS --max-time 2 http://127.0.0.1:8000/api/health &>/dev/null; do
    if (( $(date +%s) > deadline )); then
        docker compose logs --tail=60 backend
        die "Backend n'a pas démarré dans les 180s."
    fi
    sleep 3
done
log "Backend OK."

# ---------------------------------------------------------------------------
# Migrations Alembic + vérification (current == head)
# ---------------------------------------------------------------------------
log "Migrations Alembic…"
docker compose exec -T backend alembic upgrade head
CUR="$(docker compose exec -T backend alembic current 2>/dev/null | tr -d '\r' | grep -oE '^[0-9a-f]+' | head -n1 || true)"
HEAD="$(docker compose exec -T backend alembic heads 2>/dev/null | tr -d '\r' | grep -oE '^[0-9a-f]+' | head -n1 || true)"
if [[ -n "$CUR" && "$CUR" == "$HEAD" ]]; then
    log "Schéma DB à jour (révision $CUR)."
else
    warn "Vérif migration : current='$CUR' head='$HEAD' — à inspecter si différent."
fi

# ---------------------------------------------------------------------------
# Tools du registry (build images + insert en DB) — idempotent
# ---------------------------------------------------------------------------
if [[ "$DO_TOOLS" == 1 && -f "$ROOT_DIR/tools/install-all.sh" ]]; then
    log "Installation / mise à jour des tools du registry…"
    if ! (cd "$ROOT_DIR" && bash tools/install-all.sh); then
        warn "install-all.sh a renvoyé une erreur — voir au-dessus (les tools déjà OK restent en place)."
    fi
fi

# ---------------------------------------------------------------------------
# Token admin
# ---------------------------------------------------------------------------
list_emails() {
    docker compose exec -T postgres sh -c \
        'psql -tAq -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select email from users order by token_created_at"' \
        2>/dev/null | tr -d '\r' | sed '/^$/d'
}

FLAG=".first-token-issued"
EMAILS="$(list_emails || true)"
N_USERS="$(printf '%s\n' "$EMAILS" | sed '/^$/d' | wc -l | tr -d ' ')"

if [[ "$NEW_TOKEN" == 1 || ! -f "$FLAG" ]]; then
    TARGET="$EMAIL"
    if [[ -z "$TARGET" ]]; then
        if [[ "$N_USERS" == "1" ]]; then
            TARGET="$(printf '%s\n' "$EMAILS" | head -n1)"
            log "Compte unique détecté : $TARGET"
        elif [[ "$N_USERS" == "0" ]]; then
            TARGET="admin@local"
            log "Aucun compte — création de $TARGET"
        else
            warn "Plusieurs comptes existent :"
            printf '   - %s\n' $EMAILS >&2
            die "Précise lequel : bash install.sh --new-token --email=<email>"
        fi
    fi
    log "Émission d'un token pour $TARGET …"
    if OUT="$(docker compose exec -T backend spouet-admin create-token --email "$TARGET" 2>&1)"; then
        touch "$FLAG"
        echo
        echo "============================================================"
        echo " TOKEN — copie-le MAINTENANT (non récupérable ensuite)"
        echo "============================================================"
        echo "$OUT"
        echo "============================================================"
        echo
    else
        warn "create-token a échoué :"
        echo "$OUT" >&2
    fi
else
    log "Token déjà émis. Pour en régénérer un : bash install.sh --new-token [--email=<email>]"
fi

# ---------------------------------------------------------------------------
log "✓ Terminé."
log "  Web UI      : http://localhost:$PORT_WEB"
log "  Backend API : http://localhost:$PORT_BACKEND/api/docs"
log "  Logs        : (cd $SCRIPT_DIR && docker compose logs -f)"
