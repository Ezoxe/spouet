<script lang="ts">
    /**
     * Multi-séries SVG chart pour les métriques nodes (24h/7j).
     * Implémentation maison (cohérente avec Sparkline.svelte) : pas de
     * dépendance chart.js qui pèserait 200 KB pour quelques courbes.
     *
     * Chaque série a son propre min/max (échelle indépendante) — utile car
     * cpu_pct (0-100) et net_rx_kbps (0-10000+) ne se comparent pas en absolu.
     */

    export interface Series {
        label: string;
        color: string;
        points: { time: number; value: number | null }[];
        unit?: string;
        precision?: number;
    }

    let {
        series,
        width = 800,
        height = 220,
        timeFormat = 'auto'
    }: {
        series: Series[];
        width?: number;
        height?: number;
        timeFormat?: 'auto' | 'hh:mm' | 'date';
    } = $props();

    const M = { top: 16, right: 8, bottom: 24, left: 8 }; // pas d'axe Y (multi-échelles)

    const xMin = $derived(
        Math.min(
            ...series.flatMap((s) => s.points.map((p) => p.time)).filter((t) => Number.isFinite(t))
        )
    );
    const xMax = $derived(
        Math.max(
            ...series.flatMap((s) => s.points.map((p) => p.time)).filter((t) => Number.isFinite(t))
        )
    );

    function pathFor(s: Series): string {
        const values = s.points.map((p) => p.value).filter((v): v is number => v !== null);
        if (values.length === 0) return '';
        const lo = Math.min(...values);
        const hi = Math.max(...values);
        const range = hi - lo || 1;
        const w = width - M.left - M.right;
        const h = height - M.top - M.bottom;
        const xs = xMax - xMin || 1;
        let started = false;
        let d = '';
        for (const p of s.points) {
            if (p.value === null) continue;
            const x = M.left + ((p.time - xMin) / xs) * w;
            const y = M.top + h - ((p.value - lo) / range) * h;
            d += `${started ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
            started = true;
        }
        return d.trim();
    }

    function lastValue(s: Series): number | null {
        for (let i = s.points.length - 1; i >= 0; i--) {
            const v = s.points[i].value;
            if (v !== null) return v;
        }
        return null;
    }

    function xTickLabel(t: number): string {
        const d = new Date(t);
        if (timeFormat === 'date') {
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
        }
        if (timeFormat === 'hh:mm') {
            return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        }
        const span = xMax - xMin;
        if (span > 1.5 * 24 * 3600 * 1000) {
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
        }
        return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    }

    const ticks = $derived.by(() => {
        if (!Number.isFinite(xMin) || !Number.isFinite(xMax) || xMin === xMax) return [];
        return [0, 0.25, 0.5, 0.75, 1].map((f) => {
            const t = xMin + (xMax - xMin) * f;
            const x = M.left + f * (width - M.left - M.right);
            return { t, x, label: xTickLabel(t) };
        });
    });
</script>

<div class="space-y-2">
    {#if series.every((s) => s.points.length === 0)}
        <div class="rounded border border-neutral-800 bg-neutral-900/40 px-3 py-6 text-center text-xs text-neutral-500">
            Aucune donnée pour cette plage.
        </div>
    {:else}
        <svg viewBox={`0 0 ${width} ${height}`} class="w-full" role="img">
            <!-- ticks X -->
            {#each ticks as t}
                <line
                    x1={t.x}
                    x2={t.x}
                    y1={M.top}
                    y2={height - M.bottom}
                    stroke="rgb(38 38 38)"
                    stroke-dasharray="2 4"
                />
                <text
                    x={t.x}
                    y={height - M.bottom + 14}
                    text-anchor="middle"
                    fill="rgb(115 115 115)"
                    font-size="10"
                >{t.label}</text>
            {/each}

            <!-- séries -->
            {#each series as s}
                <path d={pathFor(s)} fill="none" stroke={s.color} stroke-width="1.5" stroke-linejoin="round" />
            {/each}
        </svg>

        <ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {#each series as s}
                {@const lv = lastValue(s)}
                <li class="flex items-center gap-1.5 text-neutral-400">
                    <span class="inline-block h-2 w-2 rounded-full" style:background-color={s.color}></span>
                    <span>{s.label}</span>
                    <span class="font-mono text-neutral-300">
                        {lv === null ? '—' : lv.toFixed(s.precision ?? 1)}{s.unit ?? ''}
                    </span>
                </li>
            {/each}
        </ul>
    {/if}
</div>
