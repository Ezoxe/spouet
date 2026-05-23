# Tool `spotify`

Permet à l'IA de **contrôler la lecture Spotify** de l'utilisateur (Spotify
Connect) pendant une conversation : « mets *Bohemian Rhapsody* », « pause »,
« morceau suivant », « monte le volume à 70 »…

Appelle `POST /api/spotify/control` sur le backend (réseau `internal`).

## Prérequis

1. **Compte Spotify Premium** connecté dans Spouet (onglet *Spotify* → *Connecter*).
2. Un **appareil Spotify actif** (app ouverte quelque part) — l'API Web ne crée
   pas de lecteur, elle pilote un appareil existant.
3. Le secret `tool:spouet-api/token` doit contenir un token API Spouet valide
   (déjà requis par les tools `spouet-*`).

## Actions

| action     | paramètres        | effet |
|------------|-------------------|-------|
| `play`     | `query` (option.) | lance un titre (recherche) ou reprend la lecture |
| `pause`    | —                 | met en pause |
| `next`     | —                 | piste suivante |
| `previous` | —                 | piste précédente |
| `volume`   | `volume` (0-100)  | règle le volume |
| `search`   | `query`           | recherche des titres (sans jouer) |
| `status`   | —                 | ce qui joue actuellement |

## Installation

```bash
spouet-admin tools install ./tools/registry/spotify
```
