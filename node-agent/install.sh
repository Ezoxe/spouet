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
#   CUDA_BUILD           NVIDIA : compile llama.cpp avec CUDA pour des perfs
#                        natives (def: 1). Mets CUDA_BUILD=0 pour rester sur le
#                        binaire pré-compilé Vulkan (pas de toolkit, plus lent).
#   IMAGES               Génération d'images (torch/diffusers) (def: 1).
#                        Mets IMAGES=0 ou --no-images pour désactiver.
#   IMAGE_MODEL          Modèle d'images par défaut (repo HF). Optionnel :
#                        normalement on choisit/télécharge le modèle depuis l'UI.
#   IMAGE_PORT           Port de l'API image     (def: 8083)
#   NAMING               Serveur de nommage titre/tags (def: 1).
#                        Mets NAMING=0 ou --no-naming pour désactiver.
#   NAMING_MODEL         GGUF du nommage (def: LFM2-350M-Q4_K_M.gguf)
#   NAMING_HF_REPO       Repo HF du modèle (def: LiquidAI/LFM2-350M-GGUF)
#   NAMING_PORT          Port du 2e llama-server (def: 8081)
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
: "${IMAGES:=1}"
: "${IMAGE_MODEL:=}"
: "${IMAGE_PORT:=8083}"
# Serveur de nommage dédié (titre/tags) : petit modèle GGUF toujours chargé (CPU).
: "${NAMING:=1}"
: "${NAMING_MODEL:=LFM2-350M-Q4_K_M.gguf}"
: "${NAMING_HF_REPO:=LiquidAI/LFM2-350M-GGUF}"
: "${NAMING_PORT:=8081}"
: "${SPOUET_NON_INTERACTIVE:=0}"
UNINSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend=*)   BACKEND="${1#*=}" ;;
        --token=*)     TOKEN="${1#*=}" ;;
        --interval=*)  HEARTBEAT_INTERVAL="${1#*=}" ;;
        --llama-port=*) LLAMA_PORT="${1#*=}" ;;
        --agent-port=*) AGENT_PORT="${1#*=}" ;;
        --image-port=*) IMAGE_PORT="${1#*=}" ;;
        --image-model=*) IMAGE_MODEL="${1#*=}" ;;
        --images)       IMAGES=1 ;;
        --no-images)    IMAGES=0 ;;
        --naming-model=*) NAMING_MODEL="${1#*=}" ;;
        --naming-repo=*)  NAMING_HF_REPO="${1#*=}" ;;
        --naming-port=*)  NAMING_PORT="${1#*=}" ;;
        --naming)         NAMING=1 ;;
        --no-naming)      NAMING=0 ;;
        --dir=*)        SPOUET_INSTALL_DIR="${1#*=}" ;;
        --branch=*)     SPOUET_BRANCH="${1#*=}" ;;
        --repo=*)       SPOUET_REPO_URL="${1#*=}" ;;
        --skip-llama)   SKIP_LLAMA=1 ;;
        --non-interactive) SPOUET_NON_INTERACTIVE=1 ;;
        --uninstall)    UNINSTALL=1 ;;
        -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
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

# Réinstall : on relit le backend + token déjà configurés et on les CONSERVE par
# défaut (l'utilisateur peut choisir de les changer). Les valeurs passées en
# env/flag (BACKEND=, TOKEN=) restent prioritaires et court-circuitent la question.
ENV_FILE=/etc/spouet/agent.env
EXISTING_BACKEND=""
EXISTING_TOKEN=""
if [[ -f "$ENV_FILE" ]]; then
    EXISTING_BACKEND=$(sed -n 's/^SPOUET_BACKEND=//p' "$ENV_FILE" | head -1)
    EXISTING_TOKEN=$(sed -n 's/^SPOUET_AGENT_TOKEN=//p' "$ENV_FILE" | head -1)
fi

if [[ -z "$BACKEND" && -n "$EXISTING_BACKEND" ]]; then
    if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then
        BACKEND="$EXISTING_BACKEND"
    else
        ans=""
        read -rp "[spouet-agent] Backend actuel : $EXISTING_BACKEND — conserver ? [Y/n] " ans </dev/tty || true
        if [[ "${ans,,}" == "n" ]]; then
            read -rp "[spouet-agent] Nouvelle URL backend : " BACKEND </dev/tty || true
        else
            BACKEND="$EXISTING_BACKEND"
        fi
    fi
fi

if [[ -z "$TOKEN" && -n "$EXISTING_TOKEN" ]]; then
    if [[ "$SPOUET_NON_INTERACTIVE" == "1" ]]; then
        TOKEN="$EXISTING_TOKEN"
    else
        masked="****${EXISTING_TOKEN: -4}"
        ans=""
        read -rp "[spouet-agent] Token actuel : $masked — conserver ? [Y/n] " ans </dev/tty || true
        if [[ "${ans,,}" == "n" ]]; then
            read -rp "[spouet-agent] Nouveau token : " TOKEN </dev/tty || true
        else
            TOKEN="$EXISTING_TOKEN"
        fi
    fi
fi

# Première install (rien d'existant) : on demande.
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
# libgomp1 + libopenblas0 + libcurl4 sont nécessaires au runtime de
# llama.cpp ≥ b4000 : les plugins backend CPU (libggml-cpu-*.so) sont
# linkés contre libgomp (OpenMP). Sans ces .so, dlopen échoue silencieusement
# et llama.cpp lève « make_cpu_buft_list: no CPU backend found ».
#
# libvulkan1 = loader Vulkan (libvulkan.so.1). llama.cpp ne publie AUCUN binaire
# CUDA pour Linux : sur un GPU NVIDIA, c'est le build Vulkan qui est installé et
# il offload via l'ICD fourni par le driver NVIDIA. Sans le loader, le backend
# Vulkan ne se charge pas → « ggml_vulkan: No devices found » → repli CPU.
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates wget jq \
        libgomp1 libopenblas0 libcurl4 libvulkan1
elif command -v dnf &>/dev/null; then
    dnf install -y -q git curl ca-certificates wget jq \
        libgomp libopenblas libcurl vulkan-loader
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
    # `-c safe.directory` : le dépôt appartient à `spouet` mais ce script tourne
    # en root → sans ça git lève « detected dubious ownership » et `set -e`
    # avorte l'install. On l'applique à chaque commande git du bloc.
    GIT="git -c safe.directory=$SPOUET_INSTALL_DIR -C $SPOUET_INSTALL_DIR"
    $GIT fetch --quiet origin "$SPOUET_BRANCH"
    $GIT checkout --quiet "$SPOUET_BRANCH"
    # Force la copie locale à correspondre exactement à origin.
    # reset --hard corrige les fichiers suivis modifiés ;
    # clean -fdq supprime les fichiers non suivis qui bloqueraient le merge
    # (ex : uv.lock généré par une ancienne install). Les fichiers ignorés
    # par .gitignore (modèles GGUF, cache uv…) sont préservés.
    $GIT reset --hard "origin/$SPOUET_BRANCH"
    $GIT clean -fdq
    log "✓ Dépôt mis à jour."
else
    log "Clone $SPOUET_REPO_URL → $SPOUET_INSTALL_DIR…"
    git clone --quiet --branch "$SPOUET_BRANCH" "$SPOUET_REPO_URL" "$SPOUET_INSTALL_DIR"
fi

install -d -o spouet -g spouet -m 0755 "$MODELS_DIR"
install -d -o spouet -g spouet -m 0755 "$BIN_DIR"
install -d -o spouet -g spouet -m 0755 "$SPOUET_INSTALL_DIR/.cache/huggingface"
chown -R spouet:spouet "$SPOUET_INSTALL_DIR"

# Modèle de nommage (titre/tags) : téléchargé une fois dans MODELS_DIR.
if [[ "$NAMING" == "1" && -n "$NAMING_MODEL" ]]; then
    NAMING_PATH="$MODELS_DIR/$NAMING_MODEL"
    if [[ -f "$NAMING_PATH" ]]; then
        log "Modèle de nommage déjà présent : $NAMING_MODEL"
    else
        log "Téléchargement du modèle de nommage ($NAMING_HF_REPO / $NAMING_MODEL)…"
        if wget -qO "$NAMING_PATH" \
            "https://huggingface.co/$NAMING_HF_REPO/resolve/main/$NAMING_MODEL"; then
            chown spouet:spouet "$NAMING_PATH"
            log "✓ Modèle de nommage téléchargé."
        else
            warn "Échec du téléchargement du modèle de nommage — nommage dédié désactivé."
            rm -f "$NAMING_PATH"
            NAMING=0
        fi
    fi
fi

# ---------------------------------------------------------------------------
# uv sync (node-agent) — nécessaire AVANT la détection GPU car on utilise
# `spouet-agent detect` comme source de vérité unique pour le choix de la
# variante de binaire llama-server. Plus de double détection bash/python.
# ---------------------------------------------------------------------------
UV_CACHE="$SPOUET_INSTALL_DIR/.cache/uv"
install -d -o spouet -g spouet -m 0755 "$UV_CACHE"

log "uv sync (node-agent)…"
if [[ "$IMAGES" == "1" ]]; then
    log "  → extra [images] (torch/diffusers) : installation (peut être longue)…"
    sudo -Hu spouet env UV_CACHE_DIR="$UV_CACHE" "$UV_BIN" sync --extra images \
        --directory "$SPOUET_INSTALL_DIR/node-agent"
else
    sudo -Hu spouet env UV_CACHE_DIR="$UV_CACHE" "$UV_BIN" sync \
        --directory "$SPOUET_INSTALL_DIR/node-agent"
fi

# ---------------------------------------------------------------------------
# Build llama.cpp avec CUDA (perfs natives NVIDIA).
#
# llama.cpp ne publie AUCUN binaire CUDA pour Linux (uniquement CPU/Vulkan/ROCm) :
# pour retrouver les perfs d'Ollama sur NVIDIA, on compile localement. Renvoie 0
# si un llama-server CUDA a été installé dans BIN_DIR, non-zero sinon (l'appelant
# retombe alors proprement sur le binaire pré-compilé Vulkan). Désactivable via
# CUDA_BUILD=0 (reste en Vulkan).
# ---------------------------------------------------------------------------
build_llama_cuda() {
    local bin_dir="$1"
    local src_dir="$SPOUET_INSTALL_DIR/.cache/llama-src"

    log "Build CUDA de llama.cpp (perfs natives — peut prendre 10-20 min)…"

    # nvcc déjà présent ? (évite de retélécharger le toolkit ~1.5 Go).
    local have_nvcc=0
    if command -v nvcc &>/dev/null || [[ -x /usr/local/cuda/bin/nvcc ]]; then
        have_nvcc=1
    fi

    # Garde-fou espace disque : le toolkit CUDA + le build ont besoin de marge.
    # Sans ça, un disque presque plein casse l'install (dpkg à moitié configuré,
    # initramfs non régénéré). On préfère rester en Vulkan dans ce cas. Seuil
    # plus bas si nvcc est déjà là (pas de téléchargement du toolkit).
    local need_kb=6291456            # ~6 Go (toolkit + build)
    (( have_nvcc == 1 )) && need_kb=3145728   # ~3 Go (build seul)
    local avail_root avail_src
    avail_root=$(df -Pk / | awk 'NR==2{print $4}')
    avail_src=$(df -Pk "$SPOUET_INSTALL_DIR" | awk 'NR==2{print $4}')
    if (( avail_root < need_kb || avail_src < need_kb )); then
        warn "Espace disque insuffisant pour le build CUDA ("
        warn "  / = $((avail_root/1024)) Mo, $SPOUET_INSTALL_DIR = $((avail_src/1024)) Mo libres ;"
        warn "  ~$((need_kb/1024/1024)) Go requis). Libère de l'espace puis relance,"
        warn "  ou reste en Vulkan (CUDA_BUILD=0)."
        return 1
    fi

    # Dépendances de compilation + toolkit CUDA (nvcc).
    if command -v apt-get &>/dev/null; then
        apt-get install -y -qq build-essential cmake git libcurl4-openssl-dev \
            || { warn "deps de build manquantes (apt)"; return 1; }
        if ! command -v nvcc &>/dev/null && [[ ! -x /usr/local/cuda/bin/nvcc ]]; then
            log "  → installation du toolkit CUDA (nvcc + libs, ~1.5 Go)…"
            # --no-install-recommends : ESSENTIEL. Sans ça, nvidia-cuda-toolkit
            # tire nsight, les profilers, OpenJDK, GTK et la doc (plusieurs Go
            # inutiles pour compiler) → disque plein. On ne garde que nvcc + dev.
            apt-get install -y -qq --no-install-recommends nvidia-cuda-toolkit \
                || { warn "nvidia-cuda-toolkit introuvable / install échouée"; return 1; }
        fi
    elif command -v dnf &>/dev/null; then
        dnf install -y -q --setopt=install_weak_deps=False \
            gcc-c++ cmake git libcurl-devel cuda-toolkit \
            || { warn "deps de build/CUDA manquantes (dnf)"; return 1; }
    else
        warn "gestionnaire de paquets non supporté pour le build CUDA"; return 1
    fi

    export PATH="/usr/local/cuda/bin:$PATH"
    command -v nvcc &>/dev/null || { warn "nvcc introuvable après installation"; return 1; }

    # Compute capability du GPU (ex. 6.1 → 61). Repli : éventail Pascal→Ada.
    local cc archs
    cc=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '. ')
    if [[ "$cc" =~ ^[0-9]+$ ]]; then
        archs="$cc"
    else
        archs="61;70;75;80;86;89"
        warn "  → compute capability non détectée, build multi-arch ($archs)"
    fi
    log "  → CMAKE_CUDA_ARCHITECTURES=$archs"

    # Source : tag de la dernière release (cohérent avec le canal prebuilt).
    local tag
    tag=$(curl -fsSL "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=1" 2>/dev/null \
          | jq -r '.[0].tag_name // empty')
    rm -rf "$src_dir"
    if [[ -n "$tag" ]]; then
        log "  → clone llama.cpp $tag"
        git clone --quiet --depth 1 --branch "$tag" \
            https://github.com/ggml-org/llama.cpp "$src_dir" 2>/dev/null \
            || git clone --quiet --depth 1 https://github.com/ggml-org/llama.cpp "$src_dir" \
            || { warn "clone llama.cpp échoué"; return 1; }
    else
        git clone --quiet --depth 1 https://github.com/ggml-org/llama.cpp "$src_dir" \
            || { warn "clone llama.cpp échoué"; return 1; }
    fi

    if ! cmake -S "$src_dir" -B "$src_dir/build" \
            -DGGML_CUDA=ON \
            -DCMAKE_CUDA_ARCHITECTURES="$archs" \
            -DLLAMA_CURL=ON \
            -DCMAKE_BUILD_TYPE=Release >/tmp/llama-cuda-cmake.log 2>&1; then
        warn "configuration cmake CUDA échouée (voir /tmp/llama-cuda-cmake.log)"; return 1
    fi
    if ! cmake --build "$src_dir/build" --config Release -j"$(nproc)" \
            --target llama-server >/tmp/llama-cuda-build.log 2>&1; then
        warn "compilation CUDA échouée (voir /tmp/llama-cuda-build.log)"; return 1
    fi

    local built
    built=$(find "$src_dir/build" -name llama-server -type f | head -1)
    [[ -n "$built" ]] || { warn "binaire llama-server compilé introuvable"; return 1; }

    install -m 755 "$built" "$bin_dir/llama-server"
    # Copie les .so produits (libggml-base, libggml-cuda, libllama…) à côté.
    find "$src_dir/build" \( -name "*.so" -o -name "*.so.*" \) -type f \
        -exec cp -P {} "$bin_dir/" \; 2>/dev/null || true
    chown -R spouet:spouet "$bin_dir"

    # Vérifie que le binaire se lance avec ses libs (sans charger de modèle).
    if ! LD_LIBRARY_PATH="$bin_dir:/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "$bin_dir/llama-server" --version 2>&1 | grep -qiE 'version|build'; then
        warn "le llama-server CUDA ne démarre pas (libs CUDA manquantes ?)"; return 1
    fi
    # Récupère l'espace : les sources + objets de build (~2 Go) ne servent plus.
    rm -rf "$src_dir"
    log "✓ llama-server CUDA compilé et installé (arch $archs)."
    return 0
}

# ---------------------------------------------------------------------------
# llama.cpp-server (build CUDA natif si NVIDIA, sinon binaire précompilé)
# ---------------------------------------------------------------------------
if [[ "$SKIP_LLAMA" == "0" ]]; then
    log "Détection hardware (via spouet-agent detect)…"
    CAPS_JSON=$(sudo -Hu spouet env UV_CACHE_DIR="$UV_CACHE" \
        "$UV_BIN" run --directory "$SPOUET_INSTALL_DIR/node-agent" \
        spouet-agent detect --json 2>/dev/null) || die "spouet-agent detect a échoué"
    COMPUTE_CLASS=$(echo "$CAPS_JSON" | jq -r .compute_class)
    LLAMA_VARIANT=$(echo "$CAPS_JSON" | jq -r .llama_variant)
    GPU_KIND=$(echo "$CAPS_JSON" | jq -r .gpu_kind)
    GPU_MODEL=$(echo "$CAPS_JSON" | jq -r '.gpu_model // "—"')

    # Mapping vers GPU_TYPE pour la suite (cuda/rocm/cpu)
    case "$COMPUTE_CLASS" in
        cuda) GPU_TYPE="cuda" ;;
        rocm) GPU_TYPE="rocm" ;;
        *)    GPU_TYPE="cpu" ;;
    esac
    log "  → compute_class=$COMPUTE_CLASS gpu_kind=$GPU_KIND gpu=$GPU_MODEL variant=$LLAMA_VARIANT"

    # Affiche les warnings éventuels (ex: iGPU AMD détecté → forcé en CPU)
    echo "$CAPS_JSON" | jq -r '.warnings[]?' | while read -r w; do
        [[ -n "$w" ]] && warn "  → $w"
    done

    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) ARCH_TAG="x64" ;;
        aarch64) ARCH_TAG="arm64" ;;
        *) warn "Architecture $ARCH non supportée pour les binaires précompilés, skip llama.cpp."; SKIP_LLAMA=1 ;;
    esac

    if [[ "$SKIP_LLAMA" == "0" ]]; then
        # NVIDIA : on tente un build CUDA natif (perfs ~Ollama). Si le build
        # échoue (ou CUDA_BUILD=0), on retombe sur le binaire pré-compilé Vulkan.
        CUDA_BUILT=0
        if [[ "$GPU_TYPE" == "cuda" && "${CUDA_BUILD:-1}" == "1" ]]; then
            if build_llama_cuda "$BIN_DIR"; then
                CUDA_BUILT=1
            else
                warn "Build CUDA indisponible — repli sur le binaire pré-compilé (Vulkan)."
            fi
        fi

      if [[ "$CUDA_BUILT" == "0" ]]; then
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
            # Suffixe préféré dérivé du llama_variant retourné par detect :
            #   cpu-avx512 → tente "${ARCH_TAG}-avx512" en premier
            #   cpu-avx2   → tente "${ARCH_TAG}-avx2" en premier
            #   cpu-avx    → tente "${ARCH_TAG}-avx" en premier
            #   cpu        → fallback générique
            case "$LLAMA_VARIANT" in
                cpu-avx512) _preferred="${ARCH_TAG}-avx512" ;;
                cpu-avx2)   _preferred="${ARCH_TAG}-avx2"   ;;
                cpu-avx)    _preferred="${ARCH_TAG}-avx"    ;;
                *)          _preferred="$ARCH_TAG"          ;;
            esac
            for _distro in debian ubuntu; do
                for _v in "$_preferred" "${ARCH_TAG}-avx2" "${ARCH_TAG}-avx" "${ARCH_TAG}" "${ARCH_TAG}-cpu"; do
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

        # Binaire Vulkan (seul build GPU pré-compilé pour Linux) : le loader
        # libvulkan1 ne suffit pas, il faut un ICD exposant le GPU. Sur NVIDIA
        # l'ICD vient du paquet GL du driver (souvent absent des installs
        # headless/cuda-only). Sans ICD → « ggml_vulkan: No devices found » → CPU.
        if [[ "$ASSET" == *vulkan* ]]; then
            if ! ls /usr/share/vulkan/icd.d/*.json &>/dev/null \
               && ! ls /etc/vulkan/icd.d/*.json &>/dev/null; then
                warn "Aucun ICD Vulkan (/usr/share/vulkan/icd.d/*.json) — le GPU ne sera PAS vu par llama-server."
                if [[ "$GPU_TYPE" == "cuda" ]]; then
                    _drvver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)
                    warn "  GPU NVIDIA détecté : installe le paquet GL du driver, ex. :"
                    warn "    apt-get install -y libnvidia-gl-${_drvver:-<version>}   (Debian/Ubuntu)"
                    warn "  puis : systemctl restart spouet-agent"
                fi
            else
                log "✓ ICD Vulkan présent — le GPU devrait être visible par le backend Vulkan."
            fi
        fi

        # Vérifie le binaire avec LD_LIBRARY_PATH pour trouver les .so bundlés
        if ! LD_LIBRARY_PATH="$BIN_DIR${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" "$BIN_DIR/llama-server" --version 2>&1; then
            warn "llama-server --version a échoué. Vérifiez les libs : ldd $BIN_DIR/llama-server"
        fi

        # Vérifie qu'au moins un plugin backend CPU est présent et chargeable.
        # llama.cpp ≥ b4000 utilise des `.so` plugins ; sans un libggml-cpu*.so
        # qui dlopen avec succès, le serveur lève « no CPU backend found ».
        CPU_PLUGINS=$(find "$BIN_DIR" -maxdepth 1 -name "libggml-cpu*.so*" 2>/dev/null)
        if [[ -z "$CPU_PLUGINS" ]]; then
            warn "Aucun plugin CPU (libggml-cpu*.so) trouvé dans $BIN_DIR."
            warn "llama-server lèvera « no CPU backend found » au chargement de modèle."
            warn "L'archive téléchargée ne contient pas de backend CPU séparé — variant inadaptée."
        else
            log "Plugins CPU bundlés : $(echo "$CPU_PLUGINS" | wc -l) variantes"
            # Pour chaque variant, on vérifie que toutes ses deps dynamiques sont résolues.
            MISSING_DEPS=0
            for so in $CPU_PLUGINS; do
                # `ldd` liste les libs partagées ; on cherche « not found »
                MISSING=$(LD_LIBRARY_PATH="$BIN_DIR:/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
                          ldd "$so" 2>/dev/null | grep -F "not found" || true)
                if [[ -n "$MISSING" ]]; then
                    warn "Dépendances manquantes pour $(basename "$so") :"
                    echo "$MISSING" | sed 's/^/    /' >&2
                    MISSING_DEPS=1
                fi
            done
            if [[ "$MISSING_DEPS" == "1" ]]; then
                warn "Au moins un plugin CPU a des deps manquantes — llama-server échouera."
                warn "Installez les paquets correspondants (souvent : libgomp1, libopenblas0)."
            else
                log "✓ Tous les plugins CPU ont leurs dépendances résolues."
            fi
        fi
      fi  # fin du repli prebuilt (CUDA_BUILT == 0)
    fi
else
    log "SKIP_LLAMA=1 — llama.cpp non (ré)installé."
fi

# ---------------------------------------------------------------------------
# Config /etc/spouet/agent.env
# ---------------------------------------------------------------------------
install -d -m 0750 /etc/spouet
cat > /etc/spouet/agent.env <<EOF
SPOUET_BACKEND=$BACKEND
SPOUET_AGENT_TOKEN=$TOKEN
SPOUET_BRANCH=$SPOUET_BRANCH
HEARTBEAT_INTERVAL=$HEARTBEAT_INTERVAL
LLAMA_MODELS_DIR=$MODELS_DIR
SPOUET_IMAGE_PORT=$IMAGE_PORT
SPOUET_IMAGE_MODEL=$IMAGE_MODEL
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

# Arguments de génération d'images : actifs uniquement si l'extra a été installé.
# IMPORTANT : `uv run` resynchronise l'environnement sur les deps par défaut et
# RETIRE les extras. Il faut donc relancer le service avec `--extra images`,
# sinon torch/diffusers disparaissent au démarrage et le node ne déclare pas la
# capacité image (image_enabled=false dans le heartbeat).
if [[ "$IMAGES" == "1" ]]; then
    UV_RUN_EXTRA="--extra images"
    IMAGE_ARGS="--image-port $IMAGE_PORT"
    [[ -n "$IMAGE_MODEL" ]] && IMAGE_ARGS="$IMAGE_ARGS --image-model $IMAGE_MODEL"
    log "  → génération d'images activée (port $IMAGE_PORT${IMAGE_MODEL:+, modèle $IMAGE_MODEL})"
else
    UV_RUN_EXTRA=""
    IMAGE_ARGS="--no-images"
fi

# Serveur de nommage dédié (titre/tags) : actif si NAMING=1 et modèle présent.
if [[ "$NAMING" == "1" && -n "$NAMING_MODEL" && -f "$MODELS_DIR/$NAMING_MODEL" ]]; then
    NAMING_ARGS="--naming-model $NAMING_MODEL --naming-port $NAMING_PORT"
    log "  → serveur de nommage activé (modèle $NAMING_MODEL, port $NAMING_PORT, CPU)"
else
    NAMING_ARGS=""
fi
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
ExecStart=/usr/local/bin/uv run $UV_RUN_EXTRA --directory $SPOUET_INSTALL_DIR/node-agent spouet-agent run \\
    --backend    \${SPOUET_BACKEND} \\
    --token      \${SPOUET_AGENT_TOKEN} \\
    --host       $LAN_IP \\
    --interval   \${HEARTBEAT_INTERVAL} \\
    --llama-port $LLAMA_PORT \\
    --agent-port $AGENT_PORT \\
    --install-dir $SPOUET_INSTALL_DIR \\
    --models-dir $MODELS_DIR \\
    $IMAGE_ARGS $NAMING_ARGS
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
