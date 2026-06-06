FROM python:3.12-alpine

# Aucune dépendance externe : run.py n'utilise que la stdlib (socket, ssl,
# urllib). Image minimale, démarrage rapide.
WORKDIR /app
COPY run.py /app/run.py

# Utilisateur non-root (le runner ajoute déjà --cap-drop=ALL --read-only).
RUN adduser -D -u 1000 tool
USER tool

ENTRYPOINT ["python", "/app/run.py"]
