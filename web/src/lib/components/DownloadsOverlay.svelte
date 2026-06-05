<script lang="ts">
    import { fly } from 'svelte/transition';
    import { Download, X, Check, AlertTriangle, Loader2 } from 'lucide-svelte';
    import { downloads } from '$lib/downloads.svelte';

    const items = $derived(downloads.visible);
</script>

{#if items.length > 0}
    <div class="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[90vw] flex-col gap-2">
        {#each items as d (d.id)}
            <div
                in:fly={{ y: 12, duration: 180 }}
                out:fly={{ x: 24, duration: 160 }}
                class="pointer-events-auto rounded-xl border border-neutral-700 bg-neutral-900/95 p-3 shadow-xl backdrop-blur"
            >
                <div class="flex items-start gap-2">
                    <span class="mt-0.5 shrink-0">
                        {#if d.status === 'done'}
                            <Check size={14} class="text-emerald-400" />
                        {:else if d.status === 'error'}
                            <AlertTriangle size={14} class="text-red-400" />
                        {:else}
                            <Download size={14} class="text-cyan-400" />
                        {/if}
                    </span>
                    <div class="min-w-0 flex-1">
                        <p class="truncate font-mono text-xs text-neutral-200" title={d.label}>{d.label}</p>
                        {#if d.sublabel}
                            <p class="truncate text-[10px] text-neutral-500">{d.sublabel}</p>
                        {/if}
                    </div>
                    <button
                        type="button"
                        onclick={() => downloads.dismiss(d.id)}
                        class="shrink-0 rounded p-0.5 text-neutral-500 hover:bg-white/10 hover:text-neutral-200"
                        aria-label="Masquer"
                        title="Masquer (le téléchargement continue)"
                    >
                        <X size={13} />
                    </button>
                </div>

                <!-- Barre de progression -->
                <div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                    {#if d.status === 'error'}
                        <div class="h-full w-full bg-red-500/70"></div>
                    {:else if d.percent != null}
                        <div
                            class="h-full rounded-full bg-cyan-500 transition-all duration-300"
                            style:width={`${Math.max(2, Math.min(100, d.percent))}%`}
                        ></div>
                    {:else}
                        <!-- indéterminé -->
                        <div class="dl-indeterminate h-full w-1/3 rounded-full bg-cyan-500"></div>
                    {/if}
                </div>

                <div class="mt-1 flex items-center justify-between text-[10px] text-neutral-500">
                    <span class="truncate">
                        {#if d.status === 'done'}
                            Terminé
                        {:else if d.status === 'error'}
                            {d.detail ?? 'Échec'}
                        {:else}
                            <Loader2 size={9} class="mr-1 inline animate-spin" />{d.detail ?? 'Téléchargement…'}
                        {/if}
                    </span>
                    {#if d.status === 'downloading' && d.percent != null}
                        <span class="font-mono tabular-nums text-neutral-300">{d.percent.toFixed(0)} %</span>
                    {/if}
                </div>
            </div>
        {/each}
    </div>
{/if}

<style>
    .dl-indeterminate {
        animation: dl-slide 1.3s ease-in-out infinite;
    }
    @keyframes dl-slide {
        0% { margin-left: 0; }
        50% { margin-left: 66%; }
        100% { margin-left: 0; }
    }
</style>
