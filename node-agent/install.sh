#!/usr/bin/env bash
# Spouet — installer node-agent Linux (one-liner).
#
# Usage typique :
#   curl -fsSL https://raw.githubusercontent.com/<owner>/spouet/master/node-agent/install.sh \
#     | sudo BACKEND=https://spouet.local TOKEN=<token> bash
#
# Variables d'env (BACKEND/TOKEN obligatoires en non-interactif) :
#   SPOUET_REPO_URL      (def: https://github.com/<owner>/spouet.git)
#   SPOUET_BRANCH        (def: master)
#   SPOUET_INSTALL_DIR   (def: /opt/spouet)
#   BACKEND              URL du backend Spouet (ex: https://spouet.local)
#   TOKEN                Token admin créé par le backend
#   OLLAMA_URL           (def: http://localhost:11434)
#   HEARTBEAT_INTERVAL   (def: 10)
#   SPOUET_NON_INTERACTIVE (def: 0)

set -euo pipefail

: "${SPOUET_REPO_URL:=https://github.com/ezoxe/spouet.git}"
: "${SPOUET_BRANCH:=master}"
: "${SPOUET_INSTALL_DIR:=/opt/spouet}"
: "${BACKEND:=}"
: "${TOKEN:=}"
: "${OLLAMA_URL:=http://localhost:11434}"
: "${HEARTBEAT_INTERVAL:=10}"
: "${SPOUET_NON_INTERACTIVE:=0}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend=*) BACKEND="${1#*=}" ;;
        --token=*)   TOKEN="${1#*=}" ;;
        --ollama=*)  OLLAMA_URL="${1#*=}" ;;
        --interval=*) HEARTBEAT_INTERVAL="${1#*=}" ;;
        --dir=*)     SPOUET_INSTALL_DIR="${1#*=}" ;;
        --branch=*)  SPOUET_BRANCH="${1#*=}" ;;
        --repo=*)    SPOUET_REPO_URL="${1#*=}" ;;
        --non-interactive) SPOUET_NON_INTERACTIVE=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Argument inconnu: $1" >&2; exit 2 ;;
    esac
    shift
done

log()  { printf '\033[1;36m[spouet-agent]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[spouet-agent]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[spouet-agent]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Lance en root (sudo bash install.sh)."

prompt() {
    local var="$1" question="$2"
    if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then return; fi
    [[ -n "${!var}" ]] && return
    local answer
    read -rp "$question : " answer </dev/tty || true
    [[ -n "$answer" ]] && printf -v "$var" '%s' "$answer"
}

prompt BACKEND "URL du backend Spouet (ex: https://spouet.local)"
prompt TOKEN   "Token agent (créé par spouet-admin create-token)"

[[ -n "$BACKEND" ]] || die "BACKEND requis."
[[ -n "$TOKEN"   ]] || die "TOKEN requis."

# ---------------------------------------------------------------------------
# Dépendances
# ---------------------------------------------------------------------------
log "Installation des dépendances système…"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates
elif command -v dnf &>/dev/null; then
    dnf install -y -q git curl ca-certificates
fi

# ---------------------------------------------------------------------------
# uv
# ---------------------------------------------------------------------------
UV_BIN=""
for cand in /root/.local/bin/uv /usr/local/bin/uv "$(command -v uv 2>/dev/null || true)"; do
    [[ -x "$cand" ]] && { UV_BIN="$cand"; break; }
done
if [[ -z "$UV_BIN" ]]; then
    log "Installation de uv (astral.sh)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_BIN=/root/.local/bin/uv
    [[ -x "$UV_BIN" ]] || die "Échec installation uv."
fi
log "uv : $UV_BIN ($($UV_BIN --version))"

# Symlink stable pour systemd
install -d /usr/local/bin
ln -sf "$UV_BIN" /usr/local/bin/uv

# ---------------------------------------------------------------------------
# Utilisateur dédié
# ---------------------------------------------------------------------------
if ! id -u spouet &>/dev/null; then
    log "Création de l'utilisateur système 'spouet'…"
    useradd --system --home-dir "$SPOUET_INSTALL_DIR" --shell /usr/sbin/nologin spouet
fi

# ---------------------------------------------------------------------------
# Clone / pull
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
chown -R spouet:spouet "$SPOUET_INSTALL_DIR"

log "uv sync (node-agent)…"
sudo -u spouet "$UV_BIN" sync --directory "$SPOUET_INSTALL_DIR/node-agent"

# ---------------------------------------------------------------------------
# Config /etc/spouet/agent.env
# ---------------------------------------------------------------------------
install -d -m 0750 /etc/spouet
cat > /etc/spouet/agent.env <<EOF
SPOUET_BACKEND=$BACKEND
SPOUET_AGENT_TOKEN=$TOKEN
OLLAMA_URL=$OLLAMA_URL
HEARTBEAT_INTERVAL=$HEARTBEAT_INTERVAL
EOF
chmod 0640 /etc/spouet/agent.env
chown root:spouet /etc/spouet/agent.env

# ---------------------------------------------------------------------------
# systemd unit (généré pour pointer sur uv run)
# ---------------------------------------------------------------------------
log "Installation du service systemd spouet-agent…"
cat > /etc/systemd/system/spouet-agent.service <<EOF
[Unit]
Description=Spouet Ollama node agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=spouet
EnvironmentFile=/etc/spouet/agent.env
WorkingDirectory=$SPOUET_INSTALL_DIR/node-agent
ExecStart=/usr/local/bin/uv run --directory $SPOUET_INSTALL_DIR/node-agent spouet-agent run \\
    --backend \${SPOUET_BACKEND} \\
    --ollama  \${OLLAMA_URL} \\
    --interval \${HEARTBEAT_INTERVAL}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now spouet-agent

log "✓ spouet-agent actif."
log "  → status : systemctl status spouet-agent"
log "  → logs   : journalctl -u spouet-agent -f"
