# Connector Discord

Bridge un bot Discord avec une (ou plusieurs) conversation Spouet.

## Installation côté Discord

1. Crée une application sur https://discord.com/developers/applications
2. Onglet *Bot* → ajoute un bot, copie le **token**
3. Active **MESSAGE CONTENT INTENT** (sinon le bot ne lit pas les messages)
4. *OAuth2 → URL Generator* :
   - scopes : `bot`
   - permissions : `Send Messages`, `Read Message History`, `Add Reactions`, `Use External Emojis`
5. Invite le bot sur ton serveur via l'URL générée

## Installation côté Spouet

```bash
# 1. Build l'image (sur le serveur Debian)
cd /opt/spouet/connectors/registry/discord
docker build -t spouet/connector-discord:0.1.0 .

# 2. Stocke le token Discord dans le coffre
spouet-admin secrets set --scope connector:discord-bot --key token

# 3. Installe le manifest dans la DB
spouet-admin connectors install ./

# 4. Configure le persona, modèle, channels (optionnel via UI ou API)
curl -X PATCH http://localhost:8000/api/connectors/<id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"config": {
        "bot_persona": "Tu es Spouet, l'IA maison. Réponds en français, court.",
        "default_model": "qwen2.5:14b",
        "allowed_channels": ["123456789012345678"],
        "respond_dm": true,
        "trigger_prefix": ""
      }}'

# 5. Démarre le bot
spouet-admin connectors start discord-bot
```

## Comportement

- DMs : toujours répondu si `respond_dm: true`
- Channels : seulement ceux dans `allowed_channels` (vide = tous)
- `trigger_prefix` non vide : le bot ne répond qu'aux messages commençant par
  ce préfixe ou aux mentions du bot
- Une **conversation Spouet est créée par channel** Discord (et par DM user) :
  l'historique est isolé par contexte
- Les longs messages (> 1900 chars) sont splittés automatiquement
- Le bot affiche un indicateur "écrit…" pendant que l'IA réfléchit
