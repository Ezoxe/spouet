# spouet-voice-engine

Microservice HTTP qui fournit la **reconnaissance vocale** (STT) et la
**synthèse vocale** (TTS) à Spouet, 100 % self-hosted.

- **STT** : [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, pas de torch → léger en CPU).
- **TTS** : [Piper](https://github.com/rhasspy/piper) (voix néorales ONNX, modèles `rhasspy/piper-voices`).

Le service n'est **jamais exposé au LAN** : seul le backend Spouet l'appelle
(réseau docker-compose interne). Il ne porte aucune authentification propre.

## Endpoints

| Méthode | Chemin    | Entrée                                   | Sortie            |
|---------|-----------|------------------------------------------|-------------------|
| GET     | `/health` | —                                        | JSON état/modèles |
| POST    | `/stt`    | `multipart` : `audio` (+ `language`)     | `{"text": "..."}` |
| POST    | `/tts`    | JSON `{"text", "voice"?}`                | `audio/wav`       |

## Variables d'environnement

| Variable                | Défaut               | Rôle |
|-------------------------|----------------------|------|
| `WHISPER_MODEL`         | `small`              | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `WHISPER_DEVICE`        | `cpu`                | `cpu` ou `cuda` (GPU NVIDIA) |
| `WHISPER_COMPUTE_TYPE`  | `int8`               | `int8` (CPU) / `float16` (GPU) |
| `WHISPER_LANGUAGE`      | `fr`                 | `""` = détection auto |
| `WHISPER_BEAM_SIZE`     | `5`                  | `1` = rapide, `5` = précis |
| `PIPER_VOICE`           | `fr_FR-siwis-medium` | `<locale>-<nom>-<qualité>` |
| `PIPER_DATA_DIR`        | `/data/piper`        | cache des modèles de voix |
| `MODELS_PRELOAD`        | `1`                  | précharger au démarrage |

Voix FR disponibles : `fr_FR-siwis-medium`, `fr_FR-upmc-medium`,
`fr_FR-tom-medium`, `fr_FR-gilles-low`. Voir
<https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR>.

## Déploiement

Lancé automatiquement par le `docker-compose` de `deploy/` (service
`voice-engine`). Les modèles sont téléchargés au premier démarrage et persistés
dans le volume `deploy/data/voice`. Premier démarrage = quelques minutes
(téléchargement Whisper + voix Piper).

## Dev local

> ⚠️ `piper-tts` / `piper-phonemize` n'ont des wheels que pour Linux x86_64.
> Le service est donc destiné à tourner dans son conteneur (cible Debian).

```bash
uv sync
uv run uvicorn voice_engine.app:app --reload --port 8001
```
