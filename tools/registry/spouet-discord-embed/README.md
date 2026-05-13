# spouet-discord-embed

Envoie un embed Discord riche (titre, description, champs, couleur, images)
dans le channel ou DM cible. Le bridge backend route l'event vers le container
du connector Discord qui l'exécute via `discord.Embed`.

Utile quand l'IA veut afficher des stats lisibles : tableau de bord cluster,
liste de modèles, résumé d'un node, etc.
