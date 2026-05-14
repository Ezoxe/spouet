#!/usr/bin/env bash
# Installe (build + insert en DB) tous les tools présents sous tools/registry/.
#
# À lancer sur le serveur Debian où Spouet est déployé. Idempotent — relancer
# = rebuild des images et update des lignes Tool en DB.
#
# Usage :
#   sudo bash tools/install-all.sh                     # tous les tools (sauf _shared/)
#   sudo bash tools/install-all.sh web-fetch fs-read   # un sous-ensemble
#   sudo bash tools/install-all.sh --no-build          # skip docker build (DB only)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_DIR="${SCRIPT_DIR}/registry"
COMPOSE_DIR="${SCRIPT_DIR}/../deploy"

BUILD_FLAG="--build"
SLUGS=()

for arg in "$@"; do
    case "$arg" in
        --no-build) BUILD_FLAG="" ;;
        *)          SLUGS+=("$arg") ;;
    esac
done

if [[ ${#SLUGS[@]} -eq 0 ]]; then
    while IFS= read -r -d '' dir; do
        slug="$(basename "$dir")"
        # _shared n'est pas un tool, juste des helpers communs
        [[ "$slug" == _* ]] && continue
        [[ -f "$dir/manifest.yaml" ]] || continue
        SLUGS+=("$slug")
    done < <(find "$REGISTRY_DIR" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
fi

if [[ ${#SLUGS[@]} -eq 0 ]]; then
    echo "Aucun tool trouvé dans $REGISTRY_DIR" >&2
    exit 1
fi

echo "→ Installation des tools : ${SLUGS[*]}"

# On exécute spouet-admin dans le conteneur backend (qui a déjà uv + la DB).
# Si docker compose n'est pas disponible (dev), on tente uv directement.
run_admin() {
    local args=("$@")
    if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_DIR/docker-compose.yml" ]]; then
        (cd "$COMPOSE_DIR" && docker compose exec -T backend spouet-admin "${args[@]}")
    elif command -v uv >/dev/null 2>&1 && [[ -d "${SCRIPT_DIR}/../backend" ]]; then
        (cd "${SCRIPT_DIR}/../backend" && uv run spouet-admin "${args[@]}")
    else
        echo "Ni docker compose ni uv disponibles — impossible d'exécuter spouet-admin." >&2
        exit 1
    fi
}

# Le --build de spouet-admin tools install fait un docker build local côté
# host (pas dans le conteneur). On le déclenche donc via docker direct quand
# on est en mode compose, sinon directement.
build_image() {
    local slug="$1"
    local manifest="$REGISTRY_DIR/$slug/manifest.yaml"
    local image
    image="$(grep -E '^image:' "$manifest" | head -n1 | awk '{print $2}' | tr -d '"'"'"')"
    if [[ -z "$image" ]]; then
        echo "  ⚠ image manquante dans $manifest, skip build" >&2
        return
    fi
    echo "  → docker build -t $image $REGISTRY_DIR/$slug"
    docker build -t "$image" "$REGISTRY_DIR/$slug" >/dev/null
}

for slug in "${SLUGS[@]}"; do
    echo
    echo "=== $slug ==="
    if [[ -n "$BUILD_FLAG" ]]; then
        build_image "$slug"
    fi
    # Le chemin doit être absolu côté host puisque spouet-admin tools install
    # le lit pour parser le manifest.
    # Quand on passe par docker compose exec, on monte tools/registry dans le
    # conteneur (cf. docker-compose.yml). Sinon, chemin local.
    if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_DIR/docker-compose.yml" ]]; then
        run_admin tools install "/app/tools/registry/$slug"
    else
        run_admin tools install "$REGISTRY_DIR/$slug"
    fi
done

echo
echo "✓ Terminé."
