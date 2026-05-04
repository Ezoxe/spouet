/**
 * Gestion du thème de l'app (clair / sombre / système).
 * - "light" (crème) : défaut.
 * - "dark"          : ancien thème nuit.
 * - "system"        : suit prefers-color-scheme du navigateur.
 *
 * Persisté dans localStorage. Appliqué via l'attribut `data-theme` sur <html>.
 */

import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'spouet:theme';
const DEFAULT_THEME: Theme = 'light';

export const theme = writable<Theme>(DEFAULT_THEME);

export function loadTheme(): Theme {
    if (typeof localStorage === 'undefined') return DEFAULT_THEME;
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : DEFAULT_THEME;
}

export function resolveTheme(t: Theme): ResolvedTheme {
    if (t !== 'system') return t;
    if (typeof matchMedia === 'undefined') return 'light';
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(t: Theme): void {
    if (typeof document === 'undefined') return;
    const resolved = resolveTheme(t);
    document.documentElement.setAttribute('data-theme', resolved);
}

export function setTheme(t: Theme): void {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, t);
    theme.set(t);
    applyTheme(t);
}

/** À appeler une seule fois au boot (depuis +layout.svelte). */
export function initTheme(): void {
    const t = loadTheme();
    theme.set(t);
    applyTheme(t);
    if (typeof matchMedia !== 'undefined') {
        matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (loadTheme() === 'system') applyTheme('system');
        });
    }
}
