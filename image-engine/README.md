# Spouet Image Engine

Microservice self-hosted de génération d'images pour Spouet, basé sur
[🤗 diffusers](https://github.com/huggingface/diffusers) (Stable Diffusion / SDXL).

Miroir de `voice-engine` : conteneur dédié, **jamais exposé au LAN** (pas de
`ports`), seul le backend Spouet l'appelle en interne (`spouet.images.client`).

## Endpoints

| Méthode | Route        | Entrée                              | Sortie      |
|---------|--------------|-------------------------------------|-------------|
| `GET`   | `/health`    | —                                   | JSON (état) |
| `POST`  | `/generate`  | JSON `GenerateRequest`              | `image/png` |

`GenerateRequest` : `prompt` (requis), `negative_prompt`, `width`, `height`,
`steps`, `guidance_scale`, `seed`.

## Modèle & device

Le **device** est auto-détecté au démarrage : `cuda` si un GPU NVIDIA est
exploitable, sinon `cpu` (forçable via `IMAGE_DEVICE`).

Le **modèle** par défaut s'adapte au device :

- GPU : `stabilityai/sdxl-turbo` (1024px, ~1-4 steps, guidance 0 → quelques secondes).
- CPU : `stabilityai/sd-turbo` (512px, viable mais lent).

Le premier appel télécharge les poids dans le volume `/data/hf` (persistant).

## Variables d'environnement

| Var                    | Défaut             | Rôle |
|------------------------|--------------------|------|
| `IMAGE_DEVICE`         | auto (`cuda`/`cpu`)| Force le device. |
| `IMAGE_MODEL`          | selon device       | Repo HF text2image. |
| `IMAGE_DTYPE`          | selon device       | `float16` (GPU) / `float32` (CPU) / `bfloat16`. |
| `IMAGE_MAX_DIMENSION`  | `1024`             | Plafond largeur/hauteur. |
| `IMAGE_MAX_STEPS`      | `50`               | Plafond du nombre de steps. |
| `IMAGE_DEFAULT_STEPS`  | `4`                | Steps par défaut (modèles turbo). |
| `IMAGE_DEFAULT_GUIDANCE`| `0.0`             | Guidance par défaut (turbo = 0). |
| `IMAGE_DEFAULT_SIZE`   | 1024 (GPU)/512 (CPU)| Taille carrée par défaut. |
| `MODELS_PRELOAD`       | `1`                | Précharge le modèle au démarrage. |
| `HF_HOME`              | `/data/hf`         | Cache des poids HF. |

## GPU NVIDIA

Décommenter la section `deploy.resources.reservations.devices` (ou `gpus: all`)
du service `image-engine` dans `deploy/docker-compose.yml`, et installer le
NVIDIA Container Toolkit sur l'hôte Debian.

Pour une image CPU plus légère :
`docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu .`

## Dev local

```bash
cd image-engine
uv sync
uv run uvicorn image_engine.app:app --port 8002
```
