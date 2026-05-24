<script lang="ts">
    import { onDestroy } from 'svelte';
    import { scale, fade } from 'svelte/transition';
    import { X } from 'lucide-svelte';
    import { proxiedImage } from '$lib/api';

    type Visual = {
        kind: 'image' | 'card' | 'fact';
        url?: string | null;
        title?: string | null;
        text?: string | null;
        duration_ms?: number;
    };

    let { visual, ondone }: { visual: Visual | null; ondone?: () => void } = $props();

    let imgSrc: string | null = $state(null);
    let objectUrl: string | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function revoke() {
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }

    // Réagit au changement de visuel : (re)charge l'image et arme l'auto-dismiss.
    $effect(() => {
        const v = visual;
        revoke();
        imgSrc = null;
        if (timer) clearTimeout(timer);
        if (!v) return;
        if ((v.kind === 'image' || v.kind === 'card') && v.url) {
            proxiedImage(v.url)
                .then((u) => {
                    objectUrl = u;
                    imgSrc = u;
                })
                .catch(() => {
                    imgSrc = v.url ?? null;
                });
        }
        const dur = Math.max(1500, Math.min(v.duration_ms ?? 7000, 30000));
        timer = setTimeout(() => ondone?.(), dur);
    });

    onDestroy(() => {
        if (timer) clearTimeout(timer);
        revoke();
    });
</script>

{#if visual}
    <div class="vc" in:scale={{ start: 0.85, duration: 280 }} out:fade={{ duration: 200 }}>
        <button class="vc-close" type="button" onclick={() => ondone?.()} aria-label="Fermer">
            <X size={14} />
        </button>
        {#if imgSrc}
            <img class="vc-img" src={imgSrc} alt={visual.title ?? 'visuel'} />
        {/if}
        {#if visual.title}
            <p class="vc-title">{visual.title}</p>
        {/if}
        {#if visual.text}
            <p class="vc-text" class:vc-big={visual.kind === 'fact'}>{visual.text}</p>
        {/if}
    </div>
{/if}

<style>
    .vc {
        position: relative;
        display: flex;
        flex-direction: column;
        gap: 8px;
        width: 320px;
        max-width: 80vw;
        padding: 12px;
        border-radius: 16px;
        background: linear-gradient(165deg, oklch(0.2 0.03 240 / 0.95), oklch(0.12 0.02 240 / 0.95));
        border: 1px solid oklch(0.7 0.15 210 / 0.3);
        box-shadow: 0 18px 50px -16px oklch(0 0 0 / 0.7), 0 0 36px -14px oklch(0.6 0.18 210 / 0.5);
        backdrop-filter: blur(12px);
        color: #eef2f6;
    }
    .vc-close {
        position: absolute;
        top: 6px;
        right: 6px;
        display: grid;
        place-items: center;
        height: 22px;
        width: 22px;
        border-radius: 8px;
        color: oklch(0.7 0.02 240);
    }
    .vc-close:hover {
        background: oklch(1 0 0 / 0.08);
        color: #fff;
    }
    .vc-img {
        width: 100%;
        max-height: 240px;
        object-fit: contain;
        border-radius: 10px;
        animation: vcMediaIn 400ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }
    .vc-title {
        margin: 0;
        font-size: 14px;
        font-weight: 600;
        text-align: center;
    }
    .vc-text {
        margin: 0;
        font-size: 12.5px;
        line-height: 1.45;
        color: oklch(0.84 0.02 240);
        white-space: pre-wrap;
    }
    .vc-big {
        font-size: 18px;
        font-weight: 600;
        color: #fff;
        text-align: center;
    }
    @keyframes vcMediaIn {
        from {
            opacity: 0;
            filter: blur(8px);
            transform: scale(1.03);
        }
        to {
            opacity: 1;
            filter: blur(0);
            transform: scale(1);
        }
    }
</style>
