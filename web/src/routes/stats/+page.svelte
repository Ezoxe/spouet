<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { Activity, Zap, Clock, MessageSquare, Timer, Gauge, Layers, FolderOpen, ArrowUpDown } from 'lucide-svelte';

    interface ModelStat {
        model: string;
        messages: number;
        tokens_in: number;
        tokens_out: number;
        latency_ms: number;
        avg_tps: number | null;
        avg_ttft_ms: number | null;
        last_used: string | null;
    }
    interface DayStat {
        day: string;
        messages: number;
        tokens_out: number;
    }
    interface StatsOut {
        tokens_in_total: number;
        tokens_out_total: number;
        latency_ms_total: number;
        messages_count: number;
        tokens_per_second: number | null;
        conversations_count: number;
        avg_latency_ms: number | null;
        avg_ttft_ms: number | null;
        avg_tokens_out: number | null;
        models_used: number;
        by_model: ModelStat[];
        by_day: DayStat[];
    }

    let stats: StatsOut | null = $state(null);
    let loading = $state(true);

    type SortKey = 'model' | 'messages' | 'tokens_out' | 'tokens_in' | 'avg_tps' | 'avg_ttft_ms' | 'last_used';
    let sortKey: SortKey = $state('tokens_out');
    let sortDir: 1 | -1 = $state(-1);

    const sortedModels = $derived.by(() => {
        if (!stats) return [] as ModelStat[];
        const arr = [...stats.by_model];
        arr.sort((a, b) => {
            const av = a[sortKey];
            const bv = b[sortKey];
            if (av == null && bv == null) return 0;
            if (av == null) return 1;
            if (bv == null) return -1;
            if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * sortDir;
            return ((av as number) - (bv as number)) * sortDir;
        });
        return arr;
    });

    function setSort(k: SortKey) {
        if (sortKey === k) sortDir = sortDir === 1 ? -1 : 1;
        else {
            sortKey = k;
            sortDir = k === 'model' ? 1 : -1;
        }
    }

    const maxDayMsg = $derived.by(() => {
        if (!stats || stats.by_day.length === 0) return 1;
        return Math.max(1, ...stats.by_day.map((d) => d.messages));
    });

    onMount(async () => {
        try {
            stats = await api<StatsOut>('/stats');
        } catch (e) {
            console.error(e);
        } finally {
            loading = false;
        }
    });

    function fmt(num: number | null | undefined): string {
        if (num == null) return '—';
        return new Intl.NumberFormat('fr-FR').format(Math.round(num));
    }
    function fmtTime(ms: number | null | undefined): string {
        if (ms == null) return '—';
        if (ms < 1000) return `${Math.round(ms)} ms`;
        const s = ms / 1000;
        if (s < 60) return `${s.toFixed(1)} s`;
        const m = Math.floor(s / 60);
        return `${m}m ${Math.floor(s % 60)}s`;
    }
    function fmtTps(v: number | null | undefined): string {
        return v == null ? '—' : `${v.toFixed(1)} t/s`;
    }
    function fmtDate(iso: string | null): string {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
    }
</script>

<header class="px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Statistiques</h1>
    <p class="mt-1 text-xs text-neutral-500">
        Utilisation de l'IA : volumes, vitesse, détail par modèle et tendance sur 30 jours.
    </p>
</header>

<div class="space-y-6 px-6 pb-10 sm:px-8">
    {#if loading}
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {#each Array(8) as _}
                <div class="skeleton h-24 rounded-xl"></div>
            {/each}
        </div>
    {:else if stats}
        <!-- Cartes globales -->
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {#each [
                { icon: MessageSquare, label: 'Messages IA', value: fmt(stats.messages_count) },
                { icon: FolderOpen, label: 'Conversations', value: fmt(stats.conversations_count) },
                { icon: Activity, label: 'Tokens entrants', value: fmt(stats.tokens_in_total) },
                { icon: Zap, label: 'Tokens générés', value: fmt(stats.tokens_out_total) },
                { icon: Clock, label: 'Temps de génération', value: fmtTime(stats.latency_ms_total) },
                { icon: Gauge, label: 'Vitesse moyenne', value: fmtTps(stats.tokens_per_second) },
                { icon: Timer, label: 'Latence moy. / msg', value: fmtTime(stats.avg_latency_ms) },
                { icon: Layers, label: 'Modèles utilisés', value: fmt(stats.models_used) }
            ] as c}
                <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
                    <div class="flex items-center gap-2 text-neutral-400">
                        <c.icon size={16} />
                        <h3 class="text-xs font-medium uppercase tracking-wider">{c.label}</h3>
                    </div>
                    <p class="mt-3 text-3xl font-semibold text-neutral-100">{c.value}</p>
                </div>
            {/each}
        </div>

        <!-- Tendance 30 jours -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
            <h2 class="mb-4 flex items-center gap-2 text-sm font-medium text-neutral-200">
                <Activity size={15} class="text-cyan-400" /> Activité (30 derniers jours)
            </h2>
            {#if stats.by_day.length === 0}
                <p class="text-sm text-neutral-500">Aucune activité sur la période.</p>
            {:else}
                <div class="flex h-32 items-end gap-1">
                    {#each stats.by_day as d}
                        <div
                            class="group relative flex-1 rounded-t bg-gradient-to-t from-cyan-600/40 to-cyan-400/70
                                   transition hover:from-cyan-500/60 hover:to-cyan-300"
                            style="height: {Math.max(3, (d.messages / maxDayMsg) * 100)}%"
                            title="{fmtDate(d.day)} · {d.messages} msg · {fmt(d.tokens_out)} tok"
                        >
                            <span
                                class="pointer-events-none absolute -top-7 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap
                                       rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-200 shadow group-hover:block"
                            >
                                {d.messages} msg
                            </span>
                        </div>
                    {/each}
                </div>
                <div class="mt-2 flex justify-between text-[10px] text-neutral-600">
                    <span>{fmtDate(stats.by_day[0].day)}</span>
                    <span>{fmtDate(stats.by_day[stats.by_day.length - 1].day)}</span>
                </div>
            {/if}
        </section>

        <!-- Détail par modèle -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60">
            <h2 class="flex items-center gap-2 border-b border-neutral-800 px-5 py-4 text-sm font-medium text-neutral-200">
                <Layers size={15} class="text-cyan-400" /> Par modèle
            </h2>
            {#if stats.by_model.length === 0}
                <p class="px-5 py-6 text-sm text-neutral-500">Aucune donnée par modèle pour l'instant.</p>
            {:else}
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-left text-xs uppercase tracking-wider text-neutral-500">
                                {#each [
                                    { k: 'model', label: 'Modèle', num: false },
                                    { k: 'messages', label: 'Messages', num: true },
                                    { k: 'tokens_out', label: 'Tokens out', num: true },
                                    { k: 'tokens_in', label: 'Tokens in', num: true },
                                    { k: 'avg_tps', label: 'Vitesse', num: true },
                                    { k: 'avg_ttft_ms', label: 'TTFT moy.', num: true },
                                    { k: 'last_used', label: 'Dernier usage', num: true }
                                ] as col}
                                    <th class="px-4 py-2 font-medium {col.num ? 'text-right' : ''}">
                                        <button
                                            type="button"
                                            onclick={() => setSort(col.k as SortKey)}
                                            class="inline-flex items-center gap-1 hover:text-neutral-200
                                                   {sortKey === col.k ? 'text-cyan-400' : ''}"
                                        >
                                            {col.label}
                                            <ArrowUpDown size={11} class={sortKey === col.k ? 'opacity-100' : 'opacity-30'} />
                                        </button>
                                    </th>
                                {/each}
                            </tr>
                        </thead>
                        <tbody>
                            {#each sortedModels as m (m.model)}
                                <tr class="border-t border-neutral-800/70 hover:bg-neutral-800/30">
                                    <td class="px-4 py-2.5 font-medium text-neutral-200">{m.model}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-neutral-300">{fmt(m.messages)}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-cyan-300">{fmt(m.tokens_out)}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-neutral-400">{fmt(m.tokens_in)}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-neutral-300">{fmtTps(m.avg_tps)}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-neutral-400">{fmtTime(m.avg_ttft_ms)}</td>
                                    <td class="px-4 py-2.5 text-right tabular-nums text-neutral-500">{fmtDate(m.last_used)}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            {/if}
        </section>
    {:else}
        <p class="text-sm text-neutral-500">Impossible de charger les statistiques.</p>
    {/if}
</div>
