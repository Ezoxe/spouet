FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv for fast installs
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY spouet ./spouet
COPY alembic.ini ./
COPY alembic ./alembic

RUN uv pip install --system .

# non-root user
RUN useradd -m -u 1000 spouet && chown -R spouet:spouet /app
USER spouet

EXPOSE 8000
CMD ["uvicorn", "spouet.main:app", "--host", "0.0.0.0", "--port", "8000"]
