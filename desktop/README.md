# Spouet Desktop (Tauri 2.0)

Coquille Rust qui réutilise le bundle SvelteKit (`web/build/`) et ajoute :

- **fenêtre principale** : SPA classique
- **fenêtre "compagnon"** : popup `alwaysOnTop`, déclenchée par `Ctrl+Espace`
- **tray icon** avec menu (Ouvrir / Compagnon / Quitter)
- **notifications natives** (plugin)

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
