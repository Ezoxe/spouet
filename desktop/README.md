# Spouet Desktop (Tauri 2.0)

Coquille Rust qui réutilise le bundle SvelteKit (`web/build/`) et ajoute :

- **fenêtre principale** : SPA classique
- **fenêtre "compagnon"** : popup `alwaysOnTop`, déclenchée par `Ctrl+Espace`
- **tray icon** avec menu (Ouvrir / Compagnon / Parler / Quitter)
- **notifications natives** (plugin)
- **voix** : micro + synthèse vocale activés dans WebView2

## Raccourcis & voix

| Raccourci | Action |
|---|---|
| `Ctrl+Espace` | Affiche/masque le compagnon |
| `Ctrl+Maj+Espace` | Ouvre le compagnon **et démarre l'écoute** (parler tout de suite) |
| `Espace` (mode vocal) | Démarrer/arrêter de parler |
| `Échap` (mode vocal) | Fermer |

Le bouton **⟳ (conversation continue)** du mode vocal réenclenche l'écoute après
chaque réponse — pour discuter mains-libres en continu.

> La permission micro est auto-accordée dans l'app (flag WebView2). Si le micro
> reste muet, vérifier Windows → *Confidentialité & sécurité* → *Microphone* →
> autoriser les applications de bureau. La voix nécessite que le service
> `voice-engine` tourne côté serveur (cf. `voice-engine/README.md`).

## Icônes

Avant le premier build, déposer les icônes dans `src-tauri/icons/` :

- `icon.png` 1024×1024
- `icon.ico` (Windows)
- `32x32.png`, `128x128.png`, `128x128@2x.png`

Génération facile : `pnpm tauri icon ./logo.png` (depuis ce dossier).

## Dev

```powershell
cd web && pnpm install && cd ..
cd desktop
pnpm install
pnpm tauri dev
```

## Build MSI / NSIS

```powershell
pnpm tauri build
```
