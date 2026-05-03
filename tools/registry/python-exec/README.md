# Tool : python-exec

Exécute un snippet Python isolé. **Sans réseau, sans fs persistant** (read-only + tmpfs).

## Exemple

```json
{ "code": "result = sum(range(100))" }
→ { "result": 4950, "stdout": "", "stderr": "" }
```

## Sécurité

- `network: none`, `--read-only`, `tmpfs /tmp`, user non-root
- Pas d'approval requise (pas d'IO externe)
- Timeout 15s, mem 256m

⚠️ Le snippet est exécuté avec `exec()` Python, donc il a accès à toutes les builtins.
Le sandboxing est assuré par le conteneur Docker, pas par un AST checker.
