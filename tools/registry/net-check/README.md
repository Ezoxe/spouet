# net-check

Diagnostic réseau **réel** et restreint, exposé à l'IA comme un tool sandbox.
Son but : permettre à l'assistant de *vraiment* vérifier une connexion (au lieu de
le supposer et halluciner « ✅ réseau stable »).

## Actions (whitelist)

| action | cible (`target`)      | ce que ça fait                                   |
|--------|-----------------------|--------------------------------------------------|
| `ping` | hôte / domaine        | latence + joignabilité (mesure **TCP** 443/80)   |
| `dns`  | hôte / domaine        | résolution → liste d'adresses IP                 |
| `http` | URL (ou domaine)      | code HTTP + temps de réponse                      |
| `port` | hôte + `port`         | un port TCP donné est-il ouvert ?                |

Exemple d'appel (stdin) :

```json
{ "action": "ping", "target": "google.com", "count": 4 }
```

## Pourquoi « TCP » et pas un vrai ping ICMP / traceroute ?

Le runner Spouet lance chaque tool avec `--cap-drop=ALL --read-only` en
utilisateur non-root. L'ICMP brut (le `ping` du système) et `traceroute`
exigent la capability `CAP_NET_RAW`, **volontairement retirée** pour la sécurité.

`net-check` est donc écrit en **pur Python (stdlib)** et n'utilise que des sockets
non privilégiés : « ping » mesure le temps d'établissement d'une connexion TCP
(ports 443 puis 80). C'est une mesure de joignabilité fiable et honnête ; la
méthode employée est indiquée dans la sortie (`méthode TCP`). Aucune commande
shell n'est exécutée : il n'y a pas de surface d'injection, et les cibles sont
validées par expression régulière.

## Réseau

Mode `bridge` (sortie Internet) avec `requires_approval: false` : la surface est
restreinte (4 actions, pas de shell, hôtes validés), donc l'appel ne demande pas
d'approbation HITL. Le conteneur est sur le bridge Docker par défaut — il peut
joindre Internet et le LAN, mais **ne** résout **pas** les services compose
(`backend`, `postgres`…).

## Installation (sur le serveur Debian)

```bash
sudo bash tools/install-all.sh net-check          # build image + insert en DB
# ou, pour (re)builder tous les tools :
sudo bash tools/install-all.sh
```

Une fois installé et activé, l'outil apparaît automatiquement dans les
function-calls proposés à l'IA (slug `net-check`).
