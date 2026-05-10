<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { Activity, Zap, Clock, MessageSquare, HardDrive } from 'lucide-svelte';

    interface StatsOut {
        tokens_in_total: number;
        tokens_out_total: number;
        latency_ms_total: number;
        messages_count: number;
        tokens_per_second: number | null;
    }

    let stats: StatsOut | null = $state(null);
    let loading = $state(true);

    onMount(async () => {
        try {
            stats = await api<StatsOut>('/stats');
        } catch (e) {
            console.error(e);
        } finally {
            loading = false;
        }
    });

    function formatNumber(num: number): string {
        return new Intl.NumberFormat('fr-FR').format(num);
    }

    function formatTime(ms: number): string {
        if (ms < 1000) return `${ms} ms`;
        const s = ms / 1000;
        if (s < 60) return `${s.toFixed(1)} s`;
        const m = Math.floor(s / 60);
        return `${m}m ${Math.floor(s % 60)}s`;
    }
</script>

<header class="px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Statistiques</h1>
    <p class="mt-1 text-xs text-neutral-500">
        Vue globale de votre utilisation de l'IA.
    </p>
</header>

<div class="px-6 pb-6 sm:px-8">
    {#if loading}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {#each Array(4) as _}
                <div class="skeleton h-24 rounded-xl"></div>
            {/each}
        </div>
    {:else if stats}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                <div class="flex items-center gap-2 text-neutral-400">
                    <Activity size={16} />
                    <h3 class="text-xs font-medium uppercase tracking-wider">Tokens entrants</h3>
                </div>
                <p class="mt-3 text-3xl font-semibold text-neutral-100">{formatNumber(stats.tokens_in_total)}</p>
            </div>

            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                <div class="flex items-center gap-2 text-neutral-400">
                    <Zap size={16} />
                    <h3 class="text-xs font-medium uppercase tracking-wider">Tokens générés</h3>
                </div>
                <p class="mt-3 text-3xl font-semibold text-neutral-100">{formatNumber(stats.tokens_out_total)}</p>
            </div>

            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                <div class="flex items-center gap-2 text-neutral-400">
                    <Clock size={16} />
                    <h3 class="text-xs font-medium uppercase tracking-wider">Temps total</h3>
                </div>
                <p class="mt-3 text-3xl font-semibold text-neutral-100">{formatTime(stats.latency_ms_total)}</p>
            </div>

            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                <div class="flex items-center gap-2 text-neutral-400">
                    <Activity size={16} />
                    <h3 class="text-xs font-medium uppercase tracking-wider">Vitesse moyenne</h3>
                </div>
                <p class="mt-3 text-3xl font-semibold text-neutral-100">
                    {#if stats.tokens_per_second}
                        {stats.tokens_per_second.toFixed(1)} <span class="text-lg text-neutral-500">t/s</span>
                    {:else}
                        —
                    {/if}
                </p>
            </div>

            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                <div class="flex items-center gap-2 text-neutral-400">
                    <MessageSquare size={16} />
                    <h3 class="text-xs font-medium uppercase tracking-wider">Messages IA</h3>
                </div>
                <p class="mt-3 text-3xl font-semibold text-neutral-100">{formatNumber(stats.messages_count)}</p>
            </div>
        </div>
    {:else}
        <p class="text-sm text-neutral-500">Impossible de charger les statistiques.</p>
    {/if}
</div>
