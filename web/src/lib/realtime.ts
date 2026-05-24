/**
 * Agent realtime du client desktop.
 *
 * Tient une connexion SSE persistante sur `/sse/user` (canal user) pour :
 *  - exécuter les demandes `desktop_action` poussées par le backend (lancer une
 *    app, ouvrir une URL…) puis renvoyer le résultat via REST ;
 *  - relayer les events `visual` vers la fenêtre overlay (animation).
 *
 * Et POST périodiquement `/api/desktop/hello` avec les capacités du poste
 * (écrans, apps détectées) → l'IA devient *capability-aware*.
 *
 * Démarré une seule fois, dans la fenêtre `main` de l'app Tauri uniquement.
 */

import { PUBLIC_API_BASE } from '$env/static/public';
import { getToken } from './api';
import {
    appVersion,
    currentWindowLabel,
    emitToOverlay,
    isDesktopApp,
    listInstalledApps,
    listMonitors,
    runDesktopAction
} from './desktop';

const BASE = (PUBLIC_API_BASE ?? '').replace(/\/$/, '');

let started = false;
let appsCache: string[] | null = null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function authHeaders(): Record<string, string> {
    const token = getToken();
    return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

/** Démarre l'agent (idempotent). No-op hors app desktop / hors fenêtre main. */
export function startDesktopAgent(): void {
    if (started || !isDesktopApp()) return;
    if (currentWindowLabel() !== 'main') return; // une seule instance
    if (!getToken()) return;
    started = true;
    void heartbeatLoop();
    void sseLoop();
}

async function collectCaps(): Promise<Record<string, unknown>> {
    const monitors = await listMonitors();
    if (appsCache === null) {
        appsCache = (await listInstalledApps()).map((a) => a.name);
    }
    return { os: 'windows', version: await appVersion(), monitors, apps: appsCache };
}

async function postHello(): Promise<void> {
    try {
        const caps = await collectCaps();
        await fetch(`${BASE}/api/desktop/hello`, {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(caps)
        });
    } catch {
        /* ignore : le backend marquera le client offline après TTL */
    }
}

async function heartbeatLoop(): Promise<void> {
    while (started) {
        if (getToken()) await postHello();
        await sleep(60_000);
    }
}

async function sseLoop(): Promise<void> {
    while (started) {
        try {
            const token = getToken();
            if (!token) {
                await sleep(5_000);
                continue;
            }
            const res = await fetch(`${BASE}/sse/user`, {
                headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` }
            });
            if (!res.ok || !res.body) {
                await sleep(3_000);
                continue;
            }
            const reader = res.body.getReader();
            const dec = new TextDecoder();
            let buf = '';
            while (started) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                let idx: number;
                while ((idx = buf.indexOf('\n\n')) !== -1) {
                    const block = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    const ev = parseSse(block);
                    if (ev) await handleEvent(ev);
                }
            }
        } catch {
            /* reconnexion après backoff */
        }
        await sleep(2_000);
    }
}

function parseSse(block: string): { event: string; data: unknown } | null {
    let event = 'message';
    const dataLines: string[] = [];
    for (const raw of block.split('\n')) {
        if (raw.startsWith(':')) continue;
        if (raw.startsWith('event: ')) event = raw.slice(7).trim();
        else if (raw.startsWith('data: ')) dataLines.push(raw.slice(6));
    }
    if (!dataLines.length) return null;
    const data = dataLines.join('\n');
    try {
        return { event, data: JSON.parse(data) };
    } catch {
        return { event, data };
    }
}

async function handleEvent(ev: { event: string; data: unknown }): Promise<void> {
    if (ev.event === 'desktop_action') {
        const payload = (ev.data ?? {}) as { request_id?: string; action?: Record<string, unknown> };
        if (!payload.request_id || !payload.action) return;
        const result = await runDesktopAction(payload.action as never);
        try {
            await fetch(`${BASE}/api/desktop/actions/${payload.request_id}/result`, {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify(result)
            });
        } catch {
            /* ignore : le backend timeoutera la requête */
        }
    } else if (ev.event === 'visual') {
        emitToOverlay('spouet://visual', ev.data);
    }
}
