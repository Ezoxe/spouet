# Microservice voix Spouet : faster-whisper (STT) + Piper (TTS).
# Python 3.11 : compat la plus sûre pour piper-tts / piper-phonemize.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    # Cache HuggingFace (modèles Whisper) dans le volume /data persistant
    HF_HOME=/data/hf

# ffmpeg : filet de sécurité pour le décodage audio (webm/opus, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY voice_engine ./voice_engine

RUN uv pip install --system .

RUN useradd -m -u 1000 voice \
    && mkdir -p /data/piper /data/hf \
    && chown -R voice:voice /app /data
USER voice

EXPOSE 8001
CMD ["uvicorn", "voice_engine.app:app", "--host", "0.0.0.0", "--port", "8001"]
