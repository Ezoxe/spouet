/**
 * Store global de téléchargements (Svelte 5 runes).
 *
 * Le polling vit DANS le store (pas dans la page) : un téléchargement continue
 * et la popup reste affichée même si on navigue ailleurs. `dismiss` masque la
 * popup sans interrompre le téléchargement.
 */

import { uuid } from './api';

export type DownloadStatus = 'downloading' | 'done' | 'error';

export interface DownloadItem {
    id: string;
    label: string;
    sublabel?: string;
    status: DownloadStatus;
    percent: number | null; // null = indéterminé
    detail?: string;
    dismissed: boolean;
}

export interface PollResult {
    status: DownloadStatus;
    percent?: number | null;
    detail?: string;
}

type Poll = () => Promise<PollResult>;

const _items = $state<DownloadItem[]>([]);
const _timers = new Map<string, ReturnType<typeof setInterval>>();

function _stop(id: string): void {
    const t = _timers.get(id);
    if (t) {
        clearInterval(t);
        _timers.delete(id);
    }
}

function _get(id: string): DownloadItem | undefined {
    return _items.find((i) => i.id === id);
}

export const downloads = {
    get visible(): readonly DownloadItem[] {
        return _items.filter((i) => !i.dismissed);
    },

    /**
     * Démarre le suivi d'un téléchargement. `poll` est appelé périodiquement et
     * doit renvoyer l'état courant. Le suivi s'arrête sur `done`/`error`.
     * `key` permet d'éviter les doublons (un même modèle/node).
     */
    track(opts: {
        key?: string;
        label: string;
        sublabel?: string;
        poll: Poll;
        intervalMs?: number;
    }): string {
        const id = opts.key ?? uuid();
        if (_timers.has(id)) return id; // déjà suivi

        const existing = _get(id);
        const item: DownloadItem = existing ?? {
            id,
            label: opts.label,
            sublabel: opts.sublabel,
            status: 'downloading',
            percent: null,
            dismissed: false
        };
        item.label = opts.label;
        item.sublabel = opts.sublabel;
        item.status = 'downloading';
        item.dismissed = false;
        item.detail = undefined;
        if (!existing) _items.push(item);

        const tick = async () => {
            try {
                const r = await opts.poll();
                const it = _get(id);
                if (!it) return;
                it.status = r.status;
                it.percent = r.percent ?? it.percent ?? null;
                if (r.detail !== undefined) it.detail = r.detail;
                if (r.status === 'done' || r.status === 'error') {
                    _stop(id);
                    if (r.status === 'done') {
                        it.percent = 100;
                        // auto-retrait après quelques secondes
                        setTimeout(() => downloads.remove(id), 5000);
                    }
                }
            } catch {
                /* transitoire — on retentera au prochain tick */
            }
        };
        const t = setInterval(tick, opts.intervalMs ?? 2000);
        _timers.set(id, t);
        void tick();
        return id;
    },

    dismiss(id: string): void {
        const it = _get(id);
        if (it) it.dismissed = true; // masque ; le timer continue
    },

    remove(id: string): void {
        _stop(id);
        const i = _items.findIndex((x) => x.id === id);
        if (i >= 0) _items.splice(i, 1);
    }
};
