# Tool : web-fetch

Télécharge le contenu d'une URL HTTP(S) et le renvoie en texte brut.

## Installation

```bash
spouet-admin tools install ./tools/registry/web-fetch --build
```

## Sécurité

- `network: bridge` (accès Internet requis) → **requires_approval=true** par défaut
- `--read-only`, user non-root, mem 256m, cpu 1.0, timeout 30s

## Test manuel

```bash
echo '{"url":"https://example.com"}' | docker run -i --rm --network bridge spouet/tool-web-fetch:0.1.0
```
