#!/usr/bin/env bash
# Spouet — installer node-agent + llama.cpp-server Linux (one-liner).
#
# Usage typique :
#   curl -fsSL https://raw.githubusercontent.com/<owner>/spouet/master/node-agent/install.sh \
#     | sudo BACKEND=https://spouet.local TOKEN=<token> bash
#
# Désinstallation :
#   sudo bash install.sh --uninstall
#
# Variables d'env :
#   SPOUET_REPO_URL      (def: https://github.com/ezoxe/spouet.git)
#   SPOUET_BRANCH        (def: master)
#   SPOUET_INSTALL_DIR   (def: /opt/spouet)
#   BACKEND              URL du backend Spouet  [obligatoire sauf --uninstall]
#   TOKEN                Token API Spouet        [obligatoire sauf --uninstall]
#   HEARTBEAT_INTERVAL   (def: 10)
#   LLAMA_PORT           Port llama-server       (def: 8080)
#   AGENT_PORT           Port agent API          (def: 8765)
#   SKIP_LLAMA           Si "1", ne (ré)installe pas llama.cpp (def: 0)
#   SPOUET_NON_INTERACTIVE (def: 0)

set -euo pipefail

: "${SPOUET_REPO_URL:=https://github.com/ezoxe/spouet.git}"
: "${SPOUET_BRANCH:=master}"
: "${SPOUET_INSTALL_DIR:=/opt/spouet}"
: "${BACKEND:=}"
: "${TOKEN:=}"
: "${HEARTBEAT_INTERVAL:=10}"
: "${LLAMA_PORT:=8080}"
: "${AGENT_PORT:=8765}"
: "${SKIP_LLAMA:=0}"
: "${SPOUET_NON_INTERACTIVE:=0}"
UNINSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend=*)   BACKEND="${1#*=}" ;;
        --token=*)     TOKEN="${1#*=}" ;;
        --interval=*)  HEARTBEAT_INTERVAL="${1#*=}" ;;
        --llama-port=*) LLAMA_PORT="${1#*=}" ;;
        --agent-port=*) AGENT_PORT="${1#*=}" ;;
        --dir=*)        SPOUET_INSTALL_DIR="${1#*=}" ;;
        --branch=*)     SPOUET_BRANCH="${1#*=}" ;;
        --repo=*)       SPOUET_REPO_URL="${1#*=}" ;;
        --skip-llama)   SKIP_LLAMA=1 ;;
        --non-interactive) SPOUET_NON_INTERACTIVE=1 ;;
        --uninstall)    UNINSTALL=1 ;;
        -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
        *) echo "Argument inconnu: $1" >&2; exit 2 ;;
    esac
    shift
done

log()  { printf '\033[1;36m[spouet-agent]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[spouet-agent]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[spouet-agent]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Lance en root (sudo bash install.sh)."

# ---------------------------------------------------------------------------
# Désinstallation
# ---------------------------------------------------------------------------
if [[ "$UNINSTALL" == "1" ]]; then
    log "Désinstallation de spouet-agent…"

    if systemctl is-active --quiet spouet-agent 2>/dev/null; then
        log "Arrêt du service spouet-agent…"
        systemctl stop spouet-agent
    fi
    if systemctl is-enabled --quiet spouet-agent 2>/dev/null; then
        systemctl disable spouet-agent 2>/dev/null || true
    fi
    rm -f /etc/systemd/system/spouet-agent.service
    systemctl daemon-reload
    log "✓ Service systemd supprimé."

    rm -f /etc/spouet/agent.env
    rmdir /etc/spouet 2>/dev/null || true
    log "✓ Configuration supprimée."

    if [[ -d "$SPOUET_INSTALL_DIR" ]]; then
        if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then
            warn "Répertoire $SPOUET_INSTALL_DIR conservé (mode non-interactif)."
            warn "Supprimez-le manuellement si souhaité : rm -rf $SPOUET_INSTALL_DIR"
        else
            local_ans=""
            read -rp "[spouet-agent] Supprimer $SPOUET_INSTALL_DIR (contient les modèles GGUF) ? [y/N] " local_ans </dev/tty || true
            if [[ "${local_ans,,}" == "y" ]]; then
                rm -rf "$SPOUET_INSTALL_DIR"
                log "✓ $SPOUET_INSTALL_DIR supprimé."
            else
                log "Conservé : $SPOUET_INSTALL_DIR"
            fi
        fi
    fi

    if id -u spouet &>/dev/null; then
        if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then
            warn "Utilisateur 'spouet' conservé. Supprimez manuellement : userdel spouet"
        else
            local_ans=""
            read -rp "[spouet-agent] Supprimer l'utilisateur système 'spouet' ? [y/N] " local_ans </dev/tty || true
            if [[ "${local_ans,,}" == "y" ]]; then
                userdel spouet 2>/dev/null || true
                log "✓ Utilisateur 'spouet' supprimé."
            fi
        fi
    fi

    log "✓ Désinstallation terminée."
    exit 0
fi

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

MODELS_DIR="$SPOUET_INSTALL_DIR/models"
BIN_DIR="$SPOUET_INSTALL_DIR/bin"

# ---------------------------------------------------------------------------
# Dépendances système
# ---------------------------------------------------------------------------
log "Installation des dépendances système…"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates wget jq
elif command -v dnf &>/dev/null; then
    dnf install -y -q git curl ca-certificates wget jq
fi

# ---------------------------------------------------------------------------
# uv
# ---------------------------------------------------------------------------
install -d /usr/local/bin
if [[ ! -x /usr/local/bin/uv ]]; then
    log "Installation de uv (astral.sh) → /usr/local/bin…"
    curl -LsSf https://astral.sh/uv/install.sh \
        | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
    [[ -x /usr/local/bin/uv ]] || die "Échec installation uv."
fi
UV_BIN=/usr/local/bin/uv
log "uv : $UV_BIN ($($UV_BIN --version))"

# ---------------------------------------------------------------------------
# Utilisateur dédié
# ---------------------------------------------------------------------------
if ! id -u spouet &>/dev/null; then
    log "Création de l'utilisateur système 'spouet'…"
    useradd --system --home-dir "$SPOUET_INSTALL_DIR" --shell /usr/sbin/nologin spouet
fi

# ---------------------------------------------------------------------------
# Clone / mise à jour du dépôt
# ---------------------------------------------------------------------------
if [[ -d "$SPOUET_INSTALL_DIR/.git" ]]; then
    log "Dépôt existant — mise à jour vers origin/$SPOUET_BRANCH…"
    git -C "$SPOUET_INSTALL_DIR" fetch --quiet origin "$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" checkout --quiet "$SPOUET_BRANCH"
    # Force la copie locale à correspondre exactement à origin.
    # reset --hard corrige les fichiers suivis modifiés ;
    # clean -fdq supprime les fichiers non suivis qui bloqueraient le merge
    # (ex : uv.lock généré par une ancienne install). Les fichiers ignorés
    # par .gitignore (modèles GGUF, cache uv…) sont préservés.
    git -C "$SPOUET_INSTALL_DIR" reset --hard "origin/$SPOUET_BRANCH"
    git -C "$SPOUET_INSTALL_DIR" clean -fdq
    log "✓ Dépôt mis à jour."
else
    log "Clone $SPOUET_REPO_URL → $SPOUET_INSTALL_DIR…"
    git clone --quiet --branch "$SPOUET_BRANCH" "$SPOUET_REPO_URL" "$SPOUET_INSTALL_DIR"
fi

install -d -o spouet -g spouet -m 0755 "$MODELS_DIR"
install -d -o spouet -g spouet -m 0755 "$BIN_DIR"
install -d -o spouet -g spouet -m 0755 "$SPOUET_INSTALL_DIR/.cache/huggingface"
chown -R spouet:spouet "$SPOUET_INSTALL_DIR"

# ---------------------------------------------------------------------------
# llama.cpp-server (binaire précompilé depuis les releases GitHub)
# ---------------------------------------------------------------------------
if [[ "$SKIP_LLAMA" == "0" ]]; then
    log "Détection GPU…"
    GPU_TYPE="cpu"
    if command -v nvidia-smi &>/dev/null && nvidia-smi -L 2>/dev/null | grep -q "GPU"; then
        # Vérifie que libcuda.so est accessible (drivers + runtime fonctionnels)
        if ldconfig -p 2>/dev/null | grep -q "libcuda.so" \
           || find /usr/local/cuda/lib64 /usr/lib/x86_64-linux-gnu /usr/lib64 \
                   -name "libcuda.so*" 2>/dev/null | grep -q .; then
            GPU_TYPE="cuda"
            log "  → GPU NVIDIA + libs CUDA détectés — build CUDA"
        else
            warn "  → GPU NVIDIA détecté mais libcuda.so introuvable — build CPU (installez cuda-toolkit si CUDA est souhaité)"
        fi
    elif command -v rocm-smi &>/dev/null && rocm-smi &>/dev/null 2>&1; then
        GPU_TYPE="rocm"
        log "  → GPU AMD détecté — build ROCm"
    else
        log "  → Pas de GPU — build CPU AVX2"
    fi

    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) ARCH_TAG="x64" ;;
        aarch64) ARCH_TAG="arm64" ;;
        *) warn "Architecture $ARCH non supportée pour les binaires précompilés, skip llama.cpp."; SKIP_LLAMA=1 ;;
    esac

    if [[ "$SKIP_LLAMA" == "0" ]]; then
        # La release "latest" peut avoir une CI incomplète (assets manquants).
        # On charge les 10 dernières releases et on cherche dans leurs assets API le
        # premier binaire Linux effectivement uploadé (browser_download_url garanti valide).
        log "Récupération des releases llama.cpp récentes…"
        RELEASES_JSON=$(curl -sSf \
            "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10")
        [[ -n "$RELEASES_JSON" ]] || die "Impossible de récupérer les releases llama.cpp."

        LLAMA_RELEASE=""
        ASSET=""
        LLAMA_URL=""

        # Cherche dans les assets API (browser_download_url) le premier asset dont
        # le nom se termine par $1. Remplit LLAMA_RELEASE, ASSET, LLAMA_URL.
        _find_asset() {
            local _sfx="$1" _row
            _row=$(echo "$RELEASES_JSON" | jq -r --arg s "$_sfx" \
                '[ .[] | . as $r | .assets[]
                   | select(.name | endswith($s))
                   | [$r.tag_name, .name, .browser_download_url] | @tsv
                ] | .[0] // ""')
            [[ -n "$_row" ]] || return 1
            IFS=$'\t' read -r LLAMA_RELEASE ASSET LLAMA_URL <<< "$_row"
        }

        # Variante regex pour ROCm (numéro de version variable).
        _find_asset_re() {
            local _pat="$1" _row
            _row=$(echo "$RELEASES_JSON" | jq -r --arg p "$_pat" \
                '[ .[] | . as $r | .assets[]
                   | select(.name | test($p; "i"))
                   | [$r.tag_name, .name, .browser_download_url] | @tsv
                ] | .[0] // ""')
            [[ -n "$_row" ]] || return 1
            IFS=$'\t' read -r LLAMA_RELEASE ASSET LLAMA_URL <<< "$_row"
        }

        case "$GPU_TYPE" in
            cuda)
                CUDA_VER=$(nvcc --version 2>/dev/null | grep -oP 'release \K[0-9]+' | head -1 || echo "12")
                for _distro in debian ubuntu; do
                    for _v in "cuda-cu${CUDA_VER}-${ARCH_TAG}" "cuda-cu12-${ARCH_TAG}" \
                              "cuda-${ARCH_TAG}" "vulkan-${ARCH_TAG}"; do
                        _find_asset "bin-${_distro}-${_v}.tar.gz" && {
                            log "  → Release : $LLAMA_RELEASE | Variant : ${_distro}/${_v}"
                            break 2
                        }
                    done
                done
                if [[ -z "$ASSET" ]]; then
                    warn "  → Aucun build CUDA/Vulkan — fallback CPU"
                    GPU_TYPE="cpu"
                fi
                ;;
            rocm)
                for _distro in debian ubuntu; do
                    _find_asset_re "bin-${_distro}-rocm[^-]+-${ARCH_TAG}\\.tar\\.gz$" && {
                        log "  → Release : $LLAMA_RELEASE | ROCm (${_distro})"
                        break
                    }
                done
                if [[ -z "$ASSET" ]]; then
                    warn "  → Aucun build ROCm — fallback CPU"
                    GPU_TYPE="cpu"
                fi
                ;;
            cpu) : ;;
        esac

        if [[ "$GPU_TYPE" == "cpu" && -z "$ASSET" ]]; then
            for _distro in debian ubuntu; do
                for _v in "$ARCH_TAG" "${ARCH_TAG}-avx2" "${ARCH_TAG}-avx" "${ARCH_TAG}-cpu"; do
                    _find_asset "bin-${_distro}-${_v}.tar.gz" && {
                        log "  → Release : $LLAMA_RELEASE | Variant CPU : ${_distro}/${_v}"
                        break 2
                    }
                done
            done
        fi

        [[ -n "$ASSET" ]] || die "Aucun binaire llama.cpp trouvé pour $GPU_TYPE/$ARCH_TAG dans les 10 dernières releases. Utilisez --skip-llama."
        log "  → Asset : $ASSET"

        TMPDIR_LLAMA=$(mktemp -d)
        trap "rm -rf $TMPDIR_LLAMA" EXIT

        log "Téléchargement : $LLAMA_URL"
        wget -qO "$TMPDIR_LLAMA/llama.tar.gz" "$LLAMA_URL" \
            || die "Échec téléchargement llama.cpp. Utilisez --skip-llama pour passer."

        log "Extraction de llama-server…"
        tar xzf "$TMPDIR_LLAMA/llama.tar.gz" -C "$TMPDIR_LLAMA"
        # Copie le binaire principal
        LLAMA_BIN=$(find "$TMPDIR_LLAMA" -name "llama-server" -type f | head -1)
        [[ -n "$LLAMA_BIN" ]] || die "Binaire llama-server introuvable dans l'archive."
        install -m 755 "$LLAMA_BIN" "$BIN_DIR/llama-server"
        # Copie les bibliothèques partagées bundlées dans BIN_DIR
        find "$TMPDIR_LLAMA" \( -name "*.so*" \) \( -type f -o -type l \) | while read -r sofile; do
            cp -P "$sofile" "$BIN_DIR/"
        done
        # Crée les symlinks SONAME manquants : libfoo.so.0.1.2 → libfoo.so.0
        for sofile in "$BIN_DIR"/lib*.so.*.*; do
            [[ -f "$sofile" ]] || continue
            base=$(basename "$sofile")
            soname=$(echo "$base" | sed -E 's/(.*\.so\.[0-9]+)\..*/\1/')
            [[ "$soname" != "$base" ]] && ln -sf "$base" "$BIN_DIR/$soname"
        done
        chown -R spouet:spouet "$BIN_DIR"
        log "✓ llama-server installé : $BIN_DIR/llama-server"

        # Vérifie le binaire avec LD_LIBRARY_PATH pour trouver les .so bundlés
        if ! LD_LIBRARY_PATH="$BIN_DIR${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" "$BIN_DIR/llama-server" --version 2>&1; then
            warn "llama-server --version a échoué. Vérifiez les libs : ldd $BIN_DIR/llama-server"
        fi
    fi
else
    log "SKIP_LLAMA=1 — llama.cpp non (ré)installé."
fi

# ---------------------------------------------------------------------------
# uv sync node-agent
# ---------------------------------------------------------------------------
UV_CACHE="$SPOUET_INSTALL_DIR/.cache/uv"
install -d -o spouet -g spouet -m 0755 "$UV_CACHE"

log "uv sync (node-agent)…"
sudo -Hu spouet env UV_CACHE_DIR="$UV_CACHE" "$UV_BIN" sync --directory "$SPOUET_INSTALL_DIR/node-agent"

# ---------------------------------------------------------------------------
# Config /etc/spouet/agent.env
# ---------------------------------------------------------------------------
install -d -m 0750 /etc/spouet
cat > /etc/spouet/agent.env <<EOF
SPOUET_BACKEND=$BACKEND
SPOUET_AGENT_TOKEN=$TOKEN
HEARTBEAT_INTERVAL=$HEARTBEAT_INTERVAL
LLAMA_MODELS_DIR=$MODELS_DIR
EOF
chmod 0640 /etc/spouet/agent.env
chown root:spouet /etc/spouet/agent.env

# ---------------------------------------------------------------------------
# Service systemd spouet-agent
# ---------------------------------------------------------------------------
log "Installation du service systemd spouet-agent…"
# Détecte l'IP LAN routable (celle de l'interface par défaut)
LAN_IP=$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || hostname -I | awk '{print $1}')
log "  → IP routable : $LAN_IP"
cat > /etc/systemd/system/spouet-agent.service <<EOF
[Unit]
Description=Spouet node agent (llama.cpp lifecycle + heartbeat)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=spouet
Environment=UV_CACHE_DIR=$UV_CACHE
Environment=LD_LIBRARY_PATH=$BIN_DIR:/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu
Environment=GGML_BACKEND_DL_PATH=$BIN_DIR
Environment=HF_HOME=$SPOUET_INSTALL_DIR/.cache/huggingface
Environment=HOME=$SPOUET_INSTALL_DIR
EnvironmentFile=/etc/spouet/agent.env
WorkingDirectory=$SPOUET_INSTALL_DIR/node-agent
ExecStart=/usr/local/bin/uv run --directory $SPOUET_INSTALL_DIR/node-agent spouet-agent \\
    --backend    \${SPOUET_BACKEND} \\
    --token      \${SPOUET_AGENT_TOKEN} \\
    --host       $LAN_IP \\
    --interval   \${HEARTBEAT_INTERVAL} \\
    --llama-port $LLAMA_PORT \\
    --agent-port $AGENT_PORT \\
    --install-dir $SPOUET_INSTALL_DIR \\
    --models-dir $MODELS_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now spouet-agent
systemctl restart spouet-agent

log "✓ spouet-agent actif (llama-server port $LLAMA_PORT, agent API port $AGENT_PORT)."
log "  → status  : systemctl status spouet-agent"
log "  → logs    : journalctl -u spouet-agent -f"
log "  → modèles : ls $MODELS_DIR"
log ""
log "Pour charger un modèle depuis HuggingFace :"
log "  curl -X POST http://localhost:$AGENT_PORT/models/download \\"
log "    -H 'Content-Type: application/json' \\"
log "    -d '{\"hf_repo\":\"bartowski/Meta-Llama-3.1-8B-Instruct-GGUF\",\"filename\":\"Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf\"}'"
