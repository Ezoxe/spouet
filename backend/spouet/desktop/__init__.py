"""Pilotage du PC client (app Tauri) : pont d'actions + registre de capacités.

Contrairement aux tools (conteneurs Docker côté serveur), les actions desktop
(lancer une application, ouvrir une URL, cibler un écran) s'exécutent sur la
machine de l'utilisateur. Le backend ne fait que router une demande vers le
client connecté et attendre son résultat.
"""
