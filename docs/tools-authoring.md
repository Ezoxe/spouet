# Écrire un tool Spouet

Un **tool** est une capacité exécutable que les modèles peuvent appeler pendant
une conversation (function calling natif Ollama). Chaque appel = **un conteneur
Docker jetable**, isolé et détruit après exécution.

Différence avec les *connectors* : voir `connectors-authoring.md` (un connector
est un service long-running bidirectionnel ; un tool est one-shot sortant).

## Anatomie

```
tools/registry/<slug>/
  manifest.yaml      # métadonnées + schémas + sécurité
  Dockerfile         # idéalement non-root, image légère
  run.py             # lit JSON sur stdin, écrit JSON sur stdout
  README.md
```

## `manifest.yaml`

```yaml
slug: web-fetch                       # unique, [a-z0-9-]
name: Web Fetch
version: 0.1.0
image: spouet/tool-web-fetch:0.1.0    # tag de l'image buildée
description: |
  Description longue, lisible dans l'UI et fournie au modèle.

network: none                         # none | bridge | internal
timeout_s: 30
mem_limit: 256m
cpu_limit: 1.0

# (optionnel) secrets injectés en variables d'env, résolus depuis le coffre
secrets:
  OPENAI_KEY: tool:my-tool/openai_key   # {ENV_VAR: 'scope/key'}

# (optionnel) variables d'env statiques (non-secrètes)
env:
  SPOUET_API_URL: http://backend:8000

input_schema:                         # JSON Schema (Draft 2020-12), validé avant exécution
  type: object
  required: [url]
  additionalProperties: false
  properties:
    url: { type: string, format: uri }

output_schema:                        # informatif
  type: object
  properties:
    status: { type: integer }
    text: { type: string }
```

### Champs obligatoires

`slug`, `name`, `version`, `image`, `input_schema`.

### Modes réseau (`network`)

| Mode | Accès | Usage |
|---|---|---|
| `none` (défaut) | aucun (`--network none`) | calcul pur, parsing, transformation |
| `bridge` | sortie Internet | appels d'API externes (web-fetch, Vaultwarden distant…) |
| `internal` | réseau docker-compose Spouet | tools qui interrogent l'API backend (`http://backend:8000`) |

Tout mode ≠ `none` déclenche par défaut une **approval HITL** dans l'UI avant
chaque exécution (`requires_approval`). L'admin peut la lever par tool de
confiance depuis la page Tools.

### Garde-fous d'exécution

Chaque conteneur tourne avec : `--read-only`, `--cap-drop=ALL`, `pids_limit`,
`mem_limit`, `nano_cpus` (cpu_limit), `tmpfs` sur `/tmp`, timeout. stdin reçoit
les arguments JSON, stdout doit contenir le résultat JSON.

## `run.py` (convention stdin→stdout)

```python
import json, sys

def main() -> int:
    raw = sys.stdin.read()
    args = json.loads(raw) if raw.strip() else {}
    # … logique métier …
    print(json.dumps({"resultat": "..."}, ensure_ascii=False))
    return 0   # exit 0 + stdout JSON valide ⇒ status "ok"

if __name__ == "__main__":
    sys.exit(main())
```

- **exit 0 + JSON parsable sur stdout** ⇒ `status="ok"`, payload réinjecté au modèle.
- exit ≠ 0 ou stdout non-JSON ⇒ `status="error"` (stdout/stderr remontés).

## Champ `secrets`

Injecte des secrets du coffre en variables d'env. Format `{ENV_VAR: 'scope/key'}` :

```yaml
secrets:
  VAULTWARDEN_PASSWORD: global/vaultwarden_password
  SPOUET_API_TOKEN: tool:spouet-api/token
```

Scopes : `global`, `tool:<slug>`, `connector:<slug>`. Stocker la valeur :

```bash
echo -n "$VALEUR" | docker compose exec -T backend \
    spouet-admin secrets set --scope global --key vaultwarden_password
```

## Installation / mise à jour / suppression

```bash
# Build l'image + insère/maj la row en DB
docker compose exec backend spouet-admin tools install /app/tools/registry/<slug>
# (ou en dev local : uv run spouet-admin tools install ./tools/registry/<slug> --build)

# Tous les tools du registry (build images + DB), idempotent
bash tools/install-all.sh

# Lister / désinstaller
docker compose exec backend spouet-admin tools list
docker compose exec backend spouet-admin tools uninstall <slug>
```

## Test direct (debug)

```bash
echo '{"url":"https://example.com"}' | \
    docker run -i --rm --network none spouet/tool-web-fetch:0.1.0
```

Voir `tools/registry/web-fetch/` comme exemple de référence minimal, et
`tools/registry/spouet-nodes-status/` pour un tool `network: internal` qui
appelle l'API backend.
