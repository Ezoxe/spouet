# Écrire un connector Spouet

Un **connector** est un service Docker long-running que Spouet lance et supervise,
chargé de bridger une plateforme externe (Discord, Telegram, IMAP, MQTT, Matrix, …)
avec une (ou plusieurs) conversation Spouet.

Différence avec les *tools* :

| | Tool | Connector |
|---|---|---|
| Cycle de vie | one-shot, conteneur jetable | persistant, restart=unless-stopped |
| Direction | sortie → réponse | bidirectionnel (inbound + outbound) |
| Auth | injection de secrets en env | secrets + token scopé via WS |
| Lancement | par appel LLM | manuel (UI/CLI) |

## Anatomie d'un connector

```
connectors/registry/<slug>/
  manifest.yaml
  Dockerfile
  bot.py            # ou app.js, main.go… langage libre
  README.md
```

### `manifest.yaml`

```yaml
slug: my-bridge                 # unique, [a-z0-9-]
name: Mon Bridge
version: 0.1.0
image: spouet/connector-mybridge:0.1.0
description: |
  Une description longue, lisible dans l'UI.

network: bridge                 # informatif (le manager force le réseau partagé)
mem_limit: 384m
cpu_limit: 0.5

secrets:                        # injectés en variables d'env au lancement
  MY_API_KEY: connector:my-bridge/api_key

config_schema:                  # JSON Schema, validé à chaque PATCH config
  type: object
  required: [target_id]
  properties:
    target_id: { type: string }
    bot_persona: { type: string }
    default_model: { type: string }

inbound_kinds: [message]        # purement informatif (UI)
outbound_kinds: [send_message, typing, react]
```

## Variables d'environnement injectées par Spouet

Au démarrage, le manager met à disposition du conteneur :

| Variable | Contenu |
|---|---|
| `SPOUET_BACKEND_URL` | URL WS du backend (`ws://backend:8000` par défaut) |
| `SPOUET_CONNECTOR_ID` | UUID du connector |
| `SPOUET_CONNECTOR_TOKEN` | Token d'auth pour la WS (rotaté à chaque start) |
| `SPOUET_CONFIG_JSON` | JSON de la config user (validée contre `config_schema`) |
| Tout `secrets:` | déchiffré et passé en env |

## Protocole WebSocket

Le connector ouvre une WS vers
`{SPOUET_BACKEND_URL}/ws/connectors/{SPOUET_CONNECTOR_ID}?token={SPOUET_CONNECTOR_TOKEN}`.

### Inbound (connector → backend)

Le connector envoie un JSON par event reçu de la plateforme externe :

```json
{
  "kind": "message",
  "external_id": "channel:123456",
  "external_label": "#general",
  "content": "Bonjour Spouet, quelle heure est-il ?",
  "reply_to": "987654321",
  "metadata": { "author_id": "42", "guild_id": "1" }
}
```

Spouet :

1. crée (ou récupère) une **conversation** dédiée à ce `(connector_id, external_id)`,
   héritant de `bot_persona` et `default_model` de la config ;
2. déclenche l'orchestrateur (chat loop + tools + RAG + memory) ;
3. publie une commande outbound `send_message` quand la réponse est prête.

`kind: "ping"` peut être envoyé en keepalive (ignoré côté backend, utile pour le LB).

### Outbound (backend → connector)

Le connector reçoit un JSON par commande :

```json
{ "kind": "typing", "external_id": "channel:123456" }
{ "kind": "send_message", "external_id": "channel:123456",
  "content": "Il est 14h32.", "reply_to": "987654321" }
{ "kind": "react", "external_id": "channel:123456",
  "message_id": "987654321", "emoji": "👍" }
```

C'est au connector d'implémenter ces verbes pour son protocole cible.

## Cycle de vie

```
spouet-admin connectors install ./path     → INSERT en DB (status=stopped)
spouet-admin connectors start <slug>       → docker run, status=starting → running
                                              tâche Celery monitor toutes les 30s,
                                              auto-restart si crash
spouet-admin connectors stop <slug>        → docker stop+rm, status=stopped
```

L'UI `/connectors` permet de tout faire visuellement, plus la PATCH de la config et
la consultation des logs (200 dernières lignes).

## Sécurité

- Le conteneur tourne en `read_only=True` avec `cap_drop=ALL`, `pids_limit=256`,
  `tmpfs:/tmp` (64 MB).
- Le token WS est haché en DB (SHA-256), invalidé à chaque restart.
- Le réseau Docker est partagé avec `backend` mais reste isolé d'internet sauf si
  l'image elle-même initie des connexions sortantes.
- Aucun secret n'apparaît dans les logs Spouet (les valeurs déchiffrées ne
  transitent qu'en env du conteneur).

## Exemple minimal en Python

```python
import asyncio, json, os, websockets

URL = f"{os.environ['SPOUET_BACKEND_URL']}/ws/connectors/{os.environ['SPOUET_CONNECTOR_ID']}"
URL += f"?token={os.environ['SPOUET_CONNECTOR_TOKEN']}"

async def main():
    async with websockets.connect(URL) as ws:
        # Test : envoie un message inbound puis attend la réponse
        await ws.send(json.dumps({
            "kind": "message",
            "external_id": "test:user",
            "content": "Salut !",
        }))
        async for raw in ws:
            data = json.loads(raw)
            if data.get("kind") == "send_message":
                print("AI:", data["content"])
                break

asyncio.run(main())
```

Voir `connectors/registry/discord/bot.py` pour un exemple complet.
