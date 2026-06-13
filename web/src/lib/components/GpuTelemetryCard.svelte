<script lang="ts">
    import type { GpuTelemetry } from '$lib/api';
    import { Cpu, Thermometer, Zap, Fan, Gauge } from 'lucide-svelte';

    let { telemetry }: { telemetry: GpuTelemetry[] | null } = $props();

    // Couleur de la température : vert < 60, ambre < 80, rouge ≥ 80 °C.
    function tempColor(t: number | null): string {
        if (t == null) return 'text-neutral-300';
        if (t >= 80) return 'text-red-400';
        if (t >= 60) return 'text-amber-400';
        return 'text-emerald-400';
    }
    function tempBar(t: number | null): string {
        if (t == null) return 'bg-neutral-600';
        if (t >= 80) return 'bg-red-500';
        if (t >= 60) return 'bg-amber-500';
        return 'bg-emerald-500';
    }

    function pct(used: number | null, total: number | null): number {
        if (!used || !total) return 0;
        return Math.max(0, Math.min(100, (100 * used) / total));
    }

    function fmtVram(mb: number | null): string {
        if (mb == null) return '—';
        return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB';
    }

    const fmt = (v: number | null, unit = '', digits = 0): string =>
        v == null ? '—' : v.toFixed(digits) + unit;
</script>

{#if telemetry && telemetry.length > 0}
    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <div class="mb-3 flex items-center justify-between">
            <h2 class="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-neutral-400">
                <Cpu size={12} />
                GPU{telemetry.length > 1 ? ` (${telemetry.length})` : ''}
            </h2>
        </div>

        <div class="space-y-3">
            {#each telemetry as g (g.index)}
                <div class="rounded-lg border border-neutral-800 bg-neutral-950/50 p-3">
                    <div class="mb-2 flex items-center gap-2">
                        <span class="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-400">#{g.index}</span>
                        <span class="truncate text-sm font-medium text-neutral-200" title={g.name ?? ''}>
                            {g.name ?? 'GPU'}
                        </span>
                        {#if g.temp_c != null}
                            <span class="ml-auto flex items-center gap-1 font-mono text-sm tabular-nums {tempColor(g.temp_c)}">
                                <Thermometer size={13} />
                                {fmt(g.temp_c, '°', 0)}
                            </span>
                        {/if}
                    </div>

                    <!-- Barre usage GPU -->
                    <div class="mb-2">
                        <div class="mb-0.5 flex items-center justify-between text-[11px]">
                            <span class="flex items-center gap-1 text-neutral-500"><Gauge size={11} /> Usage</span>
                            <span class="font-mono tabular-nums text-neutral-300">{fmt(g.util_pct, ' %', 0)}</span>
                        </div>
                        <div class="h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                            <div class="h-full rounded-full bg-cyan-500 transition-all duration-500" style:width={`${g.util_pct ?? 0}%`}></div>
                        </div>
                    </div>

                    <!-- Barre VRAM -->
                    <div class="mb-2">
                        <div class="mb-0.5 flex items-center justify-between text-[11px]">
                            <span class="text-neutral-500">VRAM</span>
                            <span class="font-mono tabular-nums text-neutral-300">
                                {fmtVram(g.vram_used_mb)} / {fmtVram(g.vram_total_mb)}
                            </span>
                        </div>
                        <div class="h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                            <div class="h-full rounded-full bg-violet-500 transition-all duration-500" style:width={`${pct(g.vram_used_mb, g.vram_total_mb)}%`}></div>
                        </div>
                    </div>

                    <!-- Barre température -->
                    {#if g.temp_c != null}
                        <div class="mb-2">
                            <div class="mb-0.5 flex items-center justify-between text-[11px]">
                                <span class="text-neutral-500">Température</span>
                            </div>
                            <div class="h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                                <!-- échelle 30→100 °C -->
                                <div
                                    class="h-full rounded-full transition-all duration-500 {tempBar(g.temp_c)}"
                                    style:width={`${Math.max(2, Math.min(100, ((g.temp_c - 30) / 70) * 100))}%`}
                                ></div>
                            </div>
                        </div>
                    {/if}

                    <!-- Stats secondaires -->
                    <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
                        <div class="flex items-center justify-between gap-1">
                            <span class="flex items-center gap-1 text-neutral-500"><Zap size={11} /> Puissance</span>
                            <span class="font-mono tabular-nums text-neutral-300">
                                {fmt(g.power_w, '', 0)}{#if g.power_limit_w}<span class="text-neutral-600">/{fmt(g.power_limit_w, '', 0)}</span>{/if} W
                            </span>
                        </div>
                        <div class="flex items-center justify-between gap-1">
                            <span class="flex items-center gap-1 text-neutral-500"><Fan size={11} /> Ventilo</span>
                            <span class="font-mono tabular-nums text-neutral-300">{fmt(g.fan_pct, ' %', 0)}</span>
                        </div>
                        <div class="flex items-center justify-between gap-1">
                            <span class="text-neutral-500">Mém. ctrl</span>
                            <span class="font-mono tabular-nums text-neutral-300">{fmt(g.mem_util_pct, ' %', 0)}</span>
                        </div>
                        <div class="flex items-center justify-between gap-1">
                            <span class="text-neutral-500">Horloge</span>
                            <span class="font-mono tabular-nums text-neutral-300">{fmt(g.clock_sm_mhz, '', 0)} MHz</span>
                        </div>
                    </div>
                </div>
            {/each}
        </div>
    </section>
{/if}
