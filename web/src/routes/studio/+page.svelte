<script lang="ts">
    import { onMount } from 'svelte';
    import { fly, fade, scale } from 'svelte/transition';
    import {
        images,
        authedImage,
        ApiError,
        type ImageOut,
        type ImageHealth,
        type GenerateImageIn
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import AuthedImage from '$lib/components/AuthedImage.svelte';
    import { ImagePlus, Sparkles, Trash2, Download, X, Settings2, Wand2 } from 'lucide-svelte';

    type SizePreset = { label: string; w: number; h: number };
    const SIZES: SizePreset[] = [
        { label: 'Carré', w: 1024, h: 1024 },
        { label: 'Portrait', w: 768, h: 1024 },
        { label: 'Paysage', w: 1024, h: 768 }
    ];

    let prompt = $state('');
    let negative = $state('');
    let size = $state(SIZES[0]);
    let advanced = $state(false);
    let steps = $state<number | null>(null);
    let guidance = $state<number | null>(null);
    let seed = $state<number | null>(null);

    let busy = $state(false);
    let health: ImageHealth | null = $state(null);
    let gallery: ImageOut[] = $state([]);
    let selected: ImageOut | null = $state(null);

    async function refresh() {
        [health, gallery] = await Promise.all([
            images.health().catch(() => null),
            images.list().catch(() => [])
        ]);
    }
    onMount(refresh);

    async function generate() {
        const p = prompt.trim();
        if (!p) {
            toast.error('Décris l’image à générer');
            return;
        }
        busy = true;
        try {
            const payload: GenerateImageIn = {
                prompt: p,
                negative_prompt: negative.trim() || null,
                width: size.w,
                height: size.h
            };
            if (advanced) {
                if (steps != null) payload.steps = steps;
                if (guidance != null) payload.guidance_scale = guidance;
                if (seed != null) payload.seed = seed;
            }
            const img = await images.generate(payload);
            gallery = [img, ...gallery];
            toast.success('Image générée');
        } catch (e) {
            const msg =
                e instanceof ApiError && typeof e.body === 'object' && e.body && 'detail' in e.body
                    ? String((e.body as { detail: unknown }).detail)
                    : 'Échec de la génération';
            toast.error(msg);
        } finally {
            busy = false;
        }
    }

    async function remove(img: ImageOut) {
        if (!confirm('Supprimer cette image ?')) return;
        try {
            await images.delete(img.id);
            gallery = gallery.filter((g) => g.id !== img.id);
            if (selected?.id === img.id) selected = null;
        } catch {
            toast.error('Suppression impossible');
        }
    }

    async function download(img: ImageOut) {
        try {
            const url = await authedImage(img.url);
            const a = document.createElement('a');
            a.href = url;
            a.download = `spouet-${img.id}.png`;
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 4000);
        } catch {
            toast.error('Téléchargement impossible');
        }
    }

    function onKey(e: KeyboardEvent) {
        if (e.key === 'Escape') selected = null;
    }
</script>

<svelte:window onkeydown={onKey} />

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Studio images</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Génération d’images self-hosted (Stable Diffusion). L’IA peut aussi générer des images
            en conversation via le tool <code class="text-neutral-400">generate_image</code>.
        </p>
    </div>
    {#if health}
        <div
            class="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[11px]
                   {health.ok
                ? 'border-emerald-900/50 bg-emerald-950/30 text-emerald-200'
                : 'border-amber-900/50 bg-amber-950/30 text-amber-200'}"
            title={health.error ?? ''}
        >
            <span class="h-1.5 w-1.5 rounded-full {health.ok ? 'bg-emerald-400' : 'bg-amber-400'}"></span>
            {#if !health.enabled}
                Moteur désactivé
            {:else if health.ok}
                {health.model} · {health.device}
            {:else}
                Moteur injoignable
            {/if}
        </div>
    {/if}
</header>

<div class="flex-1 overflow-y-auto px-6 pb-8 sm:px-8">
    <!-- Composer -->
    <div class="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-1)] p-4">
        <textarea
            bind:value={prompt}
            placeholder="Un renard roux endormi dans une forêt enneigée, lumière dorée, style aquarelle…"
            rows="3"
            class="w-full resize-y rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]
                   px-3 py-2 text-sm placeholder:text-neutral-600 focus:border-cyan-500/40 focus:outline-none"
        ></textarea>

        <div class="mt-3 flex flex-wrap items-center gap-3">
            <div class="flex gap-1 rounded-lg border border-[var(--color-border-subtle)] p-0.5">
                {#each SIZES as s}
                    <button
                        type="button"
                        onclick={() => (size = s)}
                        class="rounded-md px-2.5 py-1 text-xs transition
                               {size.label === s.label
                            ? 'bg-cyan-600 text-white'
                            : 'text-neutral-400 hover:text-neutral-200'}"
                    >
                        {s.label}
                    </button>
                {/each}
            </div>

            <button
                type="button"
                onclick={() => (advanced = !advanced)}
                class="flex items-center gap-1.5 rounded-lg border border-[var(--color-border-subtle)]
                       px-2.5 py-1.5 text-xs text-neutral-400 hover:text-neutral-200"
            >
                <Settings2 size={13} /> Avancé
            </button>

            <button
                type="button"
                onclick={generate}
                disabled={busy}
                class="ml-auto flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm
                       font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
            >
                {#if busy}
                    <Sparkles size={16} class="animate-pulse" /> Génération…
                {:else}
                    <Wand2 size={16} /> Générer
                {/if}
            </button>
        </div>

        {#if advanced}
            <div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" in:fly={{ y: -4, duration: 140 }}>
                <label class="text-xs text-neutral-400">
                    Prompt négatif
                    <input
                        bind:value={negative}
                        placeholder="blurry, low quality, text"
                        class="mt-1 w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]
                               px-2 py-1.5 text-xs focus:border-cyan-500/40 focus:outline-none"
                    />
                </label>
                <label class="text-xs text-neutral-400">
                    Steps
                    <input
                        type="number"
                        min="1"
                        max="150"
                        bind:value={steps}
                        placeholder="défaut"
                        class="mt-1 w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]
                               px-2 py-1.5 text-xs focus:border-cyan-500/40 focus:outline-none"
                    />
                </label>
                <label class="text-xs text-neutral-400">
                    Guidance
                    <input
                        type="number"
                        min="0"
                        max="30"
                        step="0.5"
                        bind:value={guidance}
                        placeholder="défaut"
                        class="mt-1 w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]
                               px-2 py-1.5 text-xs focus:border-cyan-500/40 focus:outline-none"
                    />
                </label>
                <label class="text-xs text-neutral-400">
                    Seed
                    <input
                        type="number"
                        bind:value={seed}
                        placeholder="aléatoire"
                        class="mt-1 w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]
                               px-2 py-1.5 text-xs focus:border-cyan-500/40 focus:outline-none"
                    />
                </label>
            </div>
        {/if}
    </div>

    <!-- Galerie -->
    {#if gallery.length === 0}
        <div class="grid place-items-center py-16 text-center text-neutral-600" in:fade>
            <ImagePlus size={40} class="mb-3 opacity-40" />
            <p class="text-sm">Aucune image générée pour l’instant.</p>
            <p class="mt-1 text-xs">Décris une scène ci-dessus, ou demande à Spouet de l’imaginer.</p>
        </div>
    {:else}
        <div class="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {#each gallery as img (img.id)}
                <div
                    in:fly={{ y: 8, duration: 160 }}
                    class="group relative aspect-square overflow-hidden rounded-xl border
                           border-[var(--color-border-subtle)] bg-[var(--color-bg-0)]"
                >
                    <button
                        type="button"
                        onclick={() => (selected = img)}
                        class="block h-full w-full"
                        title={img.prompt}
                    >
                        <AuthedImage
                            path={img.url}
                            alt={img.prompt}
                            class="h-full w-full object-cover transition group-hover:scale-105"
                        />
                    </button>
                    <div
                        class="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-end gap-1
                               bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0
                               transition group-hover:opacity-100"
                    >
                        <button
                            type="button"
                            onclick={() => download(img)}
                            class="pointer-events-auto rounded-md bg-black/50 p-1.5 text-neutral-200 hover:text-white"
                            aria-label="Télécharger"
                        >
                            <Download size={14} />
                        </button>
                        <button
                            type="button"
                            onclick={() => remove(img)}
                            class="pointer-events-auto rounded-md bg-black/50 p-1.5 text-neutral-200 hover:text-red-300"
                            aria-label="Supprimer"
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                </div>
            {/each}
        </div>
    {/if}
</div>

<!-- Lightbox (fermeture : clic sur le fond ou touche Échap, gérée par svelte:window) -->
{#if selected}
    <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
        onclick={() => (selected = null)}
        role="presentation"
        in:fade={{ duration: 150 }}
    >
        <div
            class="relative max-h-[90vh] max-w-3xl"
            in:scale={{ start: 0.9, duration: 200 }}
            role="presentation"
            onclick={(e) => e.stopPropagation()}
        >
            <AuthedImage
                path={selected.url}
                alt={selected.prompt}
                class="max-h-[78vh] w-auto rounded-xl"
            />
            <p class="mt-3 max-w-2xl text-sm text-neutral-300">{selected.prompt}</p>
            <p class="mt-1 text-xs text-neutral-500">
                {selected.width}×{selected.height}{selected.seed != null
                    ? ` · seed ${selected.seed}`
                    : ''}
            </p>
            <div class="mt-3 flex gap-2">
                <button
                    type="button"
                    onclick={() => selected && download(selected)}
                    class="flex items-center gap-1.5 rounded-lg bg-neutral-800 px-3 py-1.5 text-xs
                           text-neutral-200 hover:bg-neutral-700"
                >
                    <Download size={14} /> Télécharger
                </button>
                <button
                    type="button"
                    onclick={() => selected && remove(selected)}
                    class="flex items-center gap-1.5 rounded-lg bg-red-950/60 px-3 py-1.5 text-xs
                           text-red-200 hover:bg-red-900/60"
                >
                    <Trash2 size={14} /> Supprimer
                </button>
            </div>
        </div>
        <button
            type="button"
            class="absolute right-4 top-4 rounded-lg bg-black/50 p-2 text-neutral-300 hover:text-white"
            onclick={() => (selected = null)}
            aria-label="Fermer"
        >
            <X size={18} />
        </button>
    </div>
{/if}
