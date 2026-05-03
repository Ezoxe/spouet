FROM node:20-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BITWARDENCLI_APPDATA_DIR=/tmp/bwconfig

RUN apk add --no-cache python3 \
 && npm install -g @bitwarden/cli@2024.10.0 \
 && adduser -D -u 10001 vw

COPY run.py /app/run.py

USER vw
WORKDIR /app
ENTRYPOINT ["python3", "/app/run.py"]
