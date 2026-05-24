<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { scale, fade } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { proxiedImage } from '$lib/api';

    type Visual = {
        kind: 'image' | 'card' | 'fact';
        url?: string | null;
        title?: string | null;
        text?: string | null;
        duration_ms?: number;
    };

    let current: Visual | null = $state(null);
    let imgSrc: string | null = $state(null);
    let hideTimer: ReturnType<typeof setTimeout> | null = null;
    let unlisten: (() => void) | null = null;
    let objectUrl: string | null = null;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    function tauriWin(): any | null {
        const t = (window as unknown as { __TAURI__?: any }).__TAURI__;
        if (!t?.window) return null;
        const get = t.window.getCurrentWindow ?? t.window.getCurrent;
        try {
            return get?.call(t.window) ?? null;
        } catch {
            return null;
        }
    }

    function revoke() {
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }

    async function present(v: Visual) {
        if (hideTimer) clearTimeout(hideTimer);
        revoke();
        imgSrc = null;
        current = v;

        if ((v.kind === 'image' || v.kind === 'card') && v.url) {
            try {
                objectUrl = await proxiedImage(v.url);
                imgSrc = objectUrl;
            } catch {
                imgSrc = v.url; // repli : chargement direct
            }
        }

        try {
            await tauriWin()?.show?.();
        } catch {
            /* ignore */
        }
        const dur = Math.max(1500, Math.min(v.duration_ms ?? 7000, 30000));
        hideTimer = setTimeout(dismiss, dur);
    }

    async function dismiss() {
        current = null;
        try {
            await tauriWin()?.hide?.();
        } catch {
            /* ignore */
        }
        revoke();
        imgSrc = null;
    }

    onMount(() => {
        // Fenêtre transparente : on neutralise le fond global du thème.
        document.documentElement.style.background = 'transparent';
        document.body.style.background = 'transparent';
        // Overlay non-interactif : les clics passent à travers (jeu en dessous).
        try {
            tauriWin()?.setIgnoreCursorEvents?.(true);
        } catch {
            /* ignore */
        }
        const t = (window as unknown as { __TAURI__?: any }).__TAURI__;
        if (t?.event?.listen) {
            t.event
                .listen('spouet://visual', (e: { payload: Visual }) => present(e.payload))
                .then((un: () => void) => (unlisten = un))
                .catch(() => {});
        }
    });

    onDestroy(() => {
        unlisten?.();
        if (hideTimer) clearTimeout(hideTimer);
        revoke();
    });
</script>

<div class="overlay-root">
    {#if current}
        <div
            class="card"
            in:scale={{ start: 0.82, duration: 340, easing: cubicOut }}
            out:fade={{ duration: 220 }}
        >
            {#if imgSrc}
                <div class="media">
                    <img src={imgSrc} alt={current.title ?? 'visuel'} />
                </div>
            {/if}
            {#if current.title}
                <h2 class="title">{current.title}</h2>
            {/if}
            {#if current.text}
                <p class="text" class:big={current.kind === 'fact'}>{current.text}</p>
            {/if}
        </div>
    {/if}
</div>

<style>
    .overlay-root {
        position: fixed;
        inset: 0;
        display: grid;
        place-items: center;
        background: transparent;
        overflow: hidden;
        padding: 24px;
    }

    .card {
        max-width: 100%;
        max-height: 100%;
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 18px;
        border-radius: 20px;
        background: linear-gradient(
            165deg,
            oklch(0.18 0.03 240 / 0.92),
            oklch(0.1 0.02 240 / 0.92)
        );
        border: 1px solid oklch(0.7 0.15 210 / 0.35);
        box-shadow:
            0 24px 70px -20px oklch(0 0 0 / 0.8),
            0 0 50px -12px oklch(0.6 0.18 210 / 0.55);
        backdrop-filter: blur(14px);
        color: #f2f5f8;
        animation: glow 2.6s ease-in-out infinite alternate;
    }

    .media {
        display: flex;
        justify-content: center;
        border-radius: 12px;
        overflow: hidden;
    }

    .media img {
        max-width: 480px;
        max-height: 320px;
        width: auto;
        height: auto;
        object-fit: contain;
        border-radius: 12px;
        animation: mediaIn 420ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }

    .title {
        font-size: 16px;
        font-weight: 650;
        letter-spacing: -0.01em;
        text-align: center;
        margin: 0;
    }

    .text {
        font-size: 13.5px;
        line-height: 1.5;
        text-align: center;
        color: oklch(0.85 0.02 240);
        margin: 0;
        white-space: pre-wrap;
    }

    .text.big {
        font-size: 22px;
        font-weight: 600;
        color: #fff;
    }

    @keyframes mediaIn {
        from {
            opacity: 0;
            filter: blur(10px);
            transform: scale(1.04);
        }
        to {
            opacity: 1;
            filter: blur(0);
            transform: scale(1);
        }
    }

    @keyframes glow {
        from {
            box-shadow:
                0 24px 70px -20px oklch(0 0 0 / 0.8),
                0 0 40px -16px oklch(0.6 0.18 210 / 0.45);
        }
        to {
            box-shadow:
                0 24px 70px -20px oklch(0 0 0 / 0.8),
                0 0 64px -10px oklch(0.62 0.2 210 / 0.7);
        }
    }
</style>
