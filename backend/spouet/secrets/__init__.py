"""Coffre de secrets chiffrés (Fernet).

Convention de scope :
- ``global``                       → constantes partagées (URLs, etc.)
- ``tool:<slug>``                  → secrets d'un tool one-shot
- ``connector:<slug>``             → secrets d'un connector persistant
- ``user:<user_id>``               → secrets propres à un utilisateur (mode multi-user futur)
"""
