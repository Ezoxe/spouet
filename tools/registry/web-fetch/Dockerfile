FROM python:3.12-alpine

RUN pip install --no-cache-dir httpx==0.27.2

WORKDIR /app
COPY run.py /app/run.py

# Utilisateur non-root
RUN adduser -D -u 1000 tool
USER tool

ENTRYPOINT ["python", "/app/run.py"]
