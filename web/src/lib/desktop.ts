/**
 * Pont vers les commandes natives Tauri (pilotage du PC).
 *
 * Utilise le global `window.__TAURI__` (withGlobalTauri) plutôt qu'un import de
 * `@tauri-apps/api` — le web app n'a pas cette dépendance, et le companion fait
 * déjà ainsi. Toutes les fonctions sont no-op / vides hors de l'app desktop.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
type TauriGlobal = any;

export function tauri(): TauriGlobal | null {
    if (typeof window === 'undefined') return null;
    return (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__ ?? null;
}

export function isDesktopApp(): boolean {
    return tauri() != null;
}

/** Label de la fenêtre courante ('main', 'companion', 'overlay'). */
export function currentWindowLabel(): string {
    const t = tauri();
    if (!t?.window) return '';
    try {
        const get = t.window.getCurrentWindow ?? t.window.getCurrent;
        const w = get?.call(t.window);
        return w?.label ?? '';
    } catch {
        return '';
    }
}

export async function invoke<T = unknown>(
    cmd: string,
    args: Record<string, unknown> = {}
): Promise<T> {
    const t = tauri();
    if (!t?.core?.invoke) throw new Error('Tauri indisponible');
    return t.core.invoke(cmd, args) as Promise<T>;
}

export interface MonitorInfo {
    index: number;
    name: string;
    x: number;
    y: number;
    width: number;
    height: number;
    primary: boolean;
    scale: number;
}

export interface InstalledApp {
    name: string;
    kind: string;
    target: string;
}

export async function listMonitors(): Promise<MonitorInfo[]> {
    return invoke<MonitorInfo[]>('list_monitors').catch(() => []);
}

export async function listInstalledApps(): Promise<InstalledApp[]> {
    return invoke<InstalledApp[]>('list_installed_apps').catch(() => []);
}

export interface DesktopActionRequest {
    action: string;
    app?: string;
    url?: string;
    monitor?: number;
    mode?: string;
}

/** Exécute une action bureau primitive. Renvoie toujours un objet résultat. */
export async function runDesktopAction(
    a: DesktopActionRequest
): Promise<Record<string, unknown>> {
    try {
        switch (a.action) {
            case 'launch_app':
                return (await invoke('launch_app', {
                    appRef: a.app ?? '',
                    monitor: a.monitor ?? null,
                    mode: a.mode ?? null
                })) as Record<string, unknown>;
            case 'open_url':
                return (await invoke('open_url', {
                    url: a.url ?? '',
                    monitor: a.monitor ?? null
                })) as Record<string, unknown>;
            case 'list_monitors':
                return { status: 'ok', monitors: await listMonitors() };
            case 'list_apps':
                return { status: 'ok', apps: await listInstalledApps() };
            default:
                return { status: 'error', error: `action inconnue: ${a.action}` };
        }
    } catch (e) {
        return { status: 'error', error: String(e) };
    }
}

export async function appVersion(): Promise<string | null> {
    const t = tauri();
    try {
        return (await t?.app?.getVersion?.()) ?? null;
    } catch {
        return null;
    }
}

/** Émet un event Tauri vers la fenêtre overlay (fallback : broadcast). */
export function emitToOverlay(event: string, payload: unknown): void {
    const t = tauri();
    try {
        if (t?.event?.emitTo) t.event.emitTo('overlay', event, payload);
        else t?.event?.emit?.(event, payload);
    } catch {
        /* ignore */
    }
}
