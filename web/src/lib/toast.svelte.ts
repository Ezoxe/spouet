/**
 * Mini store de toasts (Svelte 5 runes).
 * Usage : `toast.push({ kind: 'success', message: '...' })`
 */

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
    id: string;
    kind: ToastKind;
    message: string;
    duration: number;
}

const _toasts: Toast[] = $state([]);

export const toast = {
    get all(): readonly Toast[] {
        return _toasts;
    },
    push(t: { kind?: ToastKind; message: string; duration?: number }): string {
        const id = crypto.randomUUID();
        const item: Toast = {
            id,
            kind: t.kind ?? 'info',
            message: t.message,
            duration: t.duration ?? 3500
        };
        _toasts.push(item);
        if (item.duration > 0) {
            setTimeout(() => toast.dismiss(id), item.duration);
        }
        return id;
    },
    dismiss(id: string) {
        const i = _toasts.findIndex((t) => t.id === id);
        if (i >= 0) _toasts.splice(i, 1);
    },
    success(message: string) {
        return toast.push({ kind: 'success', message });
    },
    error(message: string) {
        return toast.push({ kind: 'error', message, duration: 6000 });
    },
    info(message: string) {
        return toast.push({ kind: 'info', message });
    },
    warning(message: string) {
        return toast.push({ kind: 'warning', message });
    }
};
