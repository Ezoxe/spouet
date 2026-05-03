"""Connectors persistants : services Docker long-running qui bridgent une
plateforme externe (Discord, Telegram, IMAP, MQTT, …) avec Spouet.

Différence avec les *tools* :
- un **tool** = conteneur jetable (one-shot) appelé pendant une réponse
- un **connector** = conteneur persistant (restart=unless-stopped) qui ouvre une
  WS vers le backend et relaie inbound (events externes) ↔ outbound (commandes
  émises par l'IA).
"""
