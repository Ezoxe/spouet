FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin botuser
WORKDIR /app

RUN pip install --no-cache-dir \
        "discord.py==2.4.0" \
        "websockets==13.1"

COPY bot.py /app/bot.py

USER botuser
ENTRYPOINT ["python", "/app/bot.py"]
