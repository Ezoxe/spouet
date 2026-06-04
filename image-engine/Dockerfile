# Microservice de génération d'images Spouet : diffusers + PyTorch.
#
# L'image par défaut embarque le PyTorch CUDA (wheel par défaut sur Linux x86_64)
# : elle exploite un GPU NVIDIA si l'hôte expose la stack CUDA (cf. docker-compose
# `deploy.resources` / `gpus`), et retombe automatiquement sur CPU sinon.
# Pour un hôte strictement CPU et une image plus légère, builder avec
# `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu`.
FROM python:3.11-slim

ARG TORCH_INDEX=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    # Cache HuggingFace (poids des modèles) dans le volume /data persistant.
    HF_HOME=/data/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY image_engine ./image_engine

# Si TORCH_INDEX est fourni (ex. wheel CPU), on installe torch depuis cet index
# avant le reste pour figer la variante voulue.
RUN if [ -n "$TORCH_INDEX" ]; then \
        uv pip install --system --index-url "$TORCH_INDEX" torch ; \
    fi \
    && uv pip install --system .

RUN groupadd -g 1000 spouet \
    && useradd -m -u 1000 -g spouet spouet \
    && mkdir -p /data/hf \
    && chown -R spouet:spouet /app /data
USER spouet

EXPOSE 8002
CMD ["uvicorn", "image_engine.app:app", "--host", "0.0.0.0", "--port", "8002"]
