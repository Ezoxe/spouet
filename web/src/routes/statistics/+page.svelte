<script lang="ts">
    import { onMount } from 'svelte';
    import { fetchApi } from '$lib/api';
    import { Activity } from 'lucide-svelte';

    let stats: {
        total_tokens_in: number;
        total_tokens_out: number;
        total_messages: number;
        avg_tokens_per_second: number | null;
    } | null = $state(null);
    let loading = $state(true);
    let error = $state('');

    onMount(async () => {
        try {
            const res = await fetchApi('/api/statistics/tokens', { method: 'GET' });
            if (!res.ok) throw new Error('Erreur lors du chargement des statistiques');
            stats = await res.json();
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    });
</script>

<svelte:head>
    <title>Spouet — Statistiques</title>
</svelte:head>

<div class="mx-auto max-w-4xl p-4 sm:p-6">
    <header class="mb-6 flex items-center justify-between">
        <div>
            <h1 class="text-2xl font-bold text-neutral-100 flex items-center gap-2">
                <Activity size={24} class="text-cyan-500" /> Statistiques IA
            </h1>
            <p class="mt-1 text-sm text-neutral-400">Suivi des requêtes et tokens utilisés.</p>
        </div>
    </header>

    {#if loading}
        <div class="flex h-32 items-center justify-center text-neutral-500">
            Chargement...
        </div>
    {:else if error}
        <div class="rounded-lg border border-red-900 bg-red-950/50 p-4 text-red-200">
            {error}
        </div>
    {:else if stats}
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <h3 class="text-sm font-medium text-neutral-400">Total messages assistant</h3>
                <p class="mt-2 text-2xl font-bold text-neutral-100">{stats.total_messages}</p>
            </div>
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <h3 class="text-sm font-medium text-neutral-400">Tokens entrée (Prompt)</h3>
                <p class="mt-2 text-2xl font-bold text-neutral-100">{stats.total_tokens_in.toLocaleString()}</p>
            </div>
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <h3 class="text-sm font-medium text-neutral-400">Tokens sortie (Générés)</h3>
                <p class="mt-2 text-2xl font-bold text-neutral-100">{stats.total_tokens_out.toLocaleString()}</p>
            </div>
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <h3 class="text-sm font-medium text-neutral-400">Vitesse de génération moyenne</h3>
                <p class="mt-2 text-2xl font-bold text-cyan-400">
                    {#if stats.avg_tokens_per_second !== null}
                        {stats.avg_tokens_per_second.toFixed(1)} t/s
                    {:else}
                        —
                    {/if}
                </p>
            </div>
        </div>
    {/if}
</div>
