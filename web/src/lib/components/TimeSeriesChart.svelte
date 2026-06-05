<script lang="ts">
    /**
     * Multi-séries SVG chart pour les métriques nodes (24h/7j).
     * Implémentation maison (cohérente avec Sparkline.svelte) : pas de
     * dépendance chart.js qui pèserait 200 KB pour quelques courbes.
     *
     * Chaque série a son propre min/max (échelle indépendante) — utile car
     * cpu_pct (0-100) et net_rx_kbps (0-10000+) ne se comparent pas en absolu.
     *
     * Interactif : survol = curseur vertical + valeurs interpolées à la
     * position du pointeur. Clic sur un item de légende = toggle visibilité.
     */

    export interface Series {
        label: string;
        color: string;
        points: { time: number; value: number | null }[];
        unit?: string;
        precision?: number;
        // Bornes d'échelle Y explicites (sinon auto min/max de la série).
        min?: number;
        max?: number;
    }

    let {
        series,
        width = 800,
        height = 200,
        timeFormat = 'auto',
        showLegend = true
    }: {
        series: Series[];
        width?: number;
        height?: number;
        timeFormat?: 'auto' | 'hh:mm' | 'date';
        showLegend?: boolean;
    } = $props();

    // Tous les libellés temporels sont rendus en heure de Paris, quelle que soit
    // la timezone du navigateur (les timestamps backend sont en UTC).
    const TZ = 'Europe/Paris';

    const M = { top: 12, right: 12, bottom: 22, left: 12 };

    let hidden = $state<Set<string>>(new Set());
    let hoverX = $state<number | null>(null);
    let svgEl: SVGSVGElement | undefined = $state();

    const visible = $derived(series.filter((s) => !hidden.has(s.label)));

    const xMin = $derived(
        Math.min(
            ...visible
                .flatMap((s) => s.points.map((p) => p.time))
                .filter((t) => Number.isFinite(t))
        )
    );
    const xMax = $derived(
        Math.max(
            ...visible
                .flatMap((s) => s.points.map((p) => p.time))
                .filter((t) => Number.isFinite(t))
        )
    );

    function boundsFor(s: Series): { lo: number; hi: number } {
        const vals = s.points.map((p) => p.value).filter((v): v is number => v !== null);
        let lo = s.min ?? (vals.length ? Math.min(...vals) : 0);
        let hi = s.max ?? (vals.length ? Math.max(...vals) : 1);
        // Petite marge en haut quand l'échelle est auto, pour ne pas coller au bord.
        if (s.max === undefined && vals.length) hi = hi + (hi - lo) * 0.1;
        if (hi - lo < 1e-9) hi = lo + 1;
        return { lo, hi };
    }

    function yFor(s: Series, v: number): number {
        const { lo, hi } = boundsFor(s);
        const h = height - M.top - M.bottom;
        return M.top + h - ((v - lo) / (hi - lo)) * h;
    }

    function xFor(t: number): number {
        const w = width - M.left - M.right;
        const xs = xMax - xMin || 1;
        return M.left + ((t - xMin) / xs) * w;
    }

    function pathFor(s: Series): string {
        let started = false;
        let d = '';
        for (const p of s.points) {
            if (p.value === null) continue;
            const x = xFor(p.time);
            const y = yFor(s, p.value);
            d += `${started ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
            started = true;
        }
        return d.trim();
    }

    function areaFor(s: Series): string {
        const pts = s.points.filter((p): p is { time: number; value: number } => p.value !== null);
        if (pts.length === 0) return '';
        let d = '';
        for (let i = 0; i < pts.length; i++) {
            const p = pts[i];
            d += `${i === 0 ? 'M' : 'L'}${xFor(p.time).toFixed(1)} ${yFor(s, p.value).toFixed(1)} `;
        }
        const baseY = (height - M.bottom).toFixed(1);
        d += `L${xFor(pts[pts.length - 1].time).toFixed(1)} ${baseY} `;
        d += `L${xFor(pts[0].time).toFixed(1)} ${baseY} Z`;
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
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: TZ });
        }
        if (timeFormat === 'hh:mm') {
            return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
        }
        const span = xMax - xMin;
        if (span > 1.5 * 24 * 3600 * 1000) {
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: TZ });
        }
        return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
    }

    const ticks = $derived.by(() => {
        if (!Number.isFinite(xMin) || !Number.isFinite(xMax) || xMin === xMax) return [];
        return [0, 0.25, 0.5, 0.75, 1].map((f) => {
            const t = xMin + (xMax - xMin) * f;
            const x = M.left + f * (width - M.left - M.right);
            return { t, x, label: xTickLabel(t) };
        });
    });

    // Génère un id unique par instance pour le gradient
    const gid = `tsc-${Math.random().toString(36).slice(2, 9)}`;

    // Survol : trouve le point le plus proche dans le temps pour chaque série
    function nearestValue(s: Series, t: number): { time: number; value: number } | null {
        let best: { time: number; value: number } | null = null;
        let bestDist = Infinity;
        for (const p of s.points) {
            if (p.value === null) continue;
            const d = Math.abs(p.time - t);
            if (d < bestDist) {
                bestDist = d;
                best = { time: p.time, value: p.value };
            }
        }
        return best;
    }

    const hoverData = $derived.by(() => {
        if (hoverX === null || !Number.isFinite(xMin) || !Number.isFinite(xMax)) return null;
        const w = width - M.left - M.right;
        const ratio = Math.max(0, Math.min(1, (hoverX - M.left) / w));
        const t = xMin + ratio * (xMax - xMin);
        const items = visible
            .map((s) => ({ s, p: nearestValue(s, t) }))
            .filter((x): x is { s: Series; p: { time: number; value: number } } => x.p !== null);
        return { t, items };
    });

    function onPointer(e: PointerEvent): void {
        if (!svgEl) return;
        const rect = svgEl.getBoundingClientRect();
        const scaleX = width / rect.width;
        hoverX = (e.clientX - rect.left) * scaleX;
    }

    function onLeave(): void {
        hoverX = null;
    }

    function toggle(label: string): void {
        const next = new Set(hidden);
        if (next.has(label)) next.delete(label);
        else next.add(label);
        hidden = next;
    }

    function fmtHover(t: number): string {
        const d = new Date(t);
        if (timeFormat === 'date') {
            return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
        }
        return d.toLocaleString('fr-FR', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZone: TZ
        });
    }
</script>

<div class="space-y-2">
    {#if series.every((s) => s.points.length === 0)}
        <div
            class="rounded border border-neutral-800 bg-neutral-900/40 px-3 py-6 text-center text-xs text-neutral-500"
        >
            Aucune donnée pour cette plage.
        </div>
    {:else}
        <div class="relative">
            <svg
                bind:this={svgEl}
                viewBox={`0 0 ${width} ${height}`}
                class="w-full select-none"
                role="img"
                onpointermove={onPointer}
                onpointerleave={onLeave}
            >
                <defs>
                    {#each visible as s, i}
                        <linearGradient id={`${gid}-${i}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stop-color={s.color} stop-opacity="0.18" />
                            <stop offset="100%" stop-color={s.color} stop-opacity="0" />
                        </linearGradient>
                    {/each}
                </defs>

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
                        font-size="10">{t.label}</text
                    >
                {/each}

                <!-- séries (zone + ligne) -->
                {#each visible as s, i}
                    <path d={areaFor(s)} fill={`url(#${gid}-${i})`} stroke="none" />
                {/each}
                {#each visible as s}
                    <path
                        d={pathFor(s)}
                        fill="none"
                        stroke={s.color}
                        stroke-width="1.5"
                        stroke-linejoin="round"
                        stroke-linecap="round"
                    />
                {/each}

                <!-- curseur survol -->
                {#if hoverX !== null && hoverData}
                    <line
                        x1={hoverX}
                        x2={hoverX}
                        y1={M.top}
                        y2={height - M.bottom}
                        stroke="rgb(115 115 115)"
                        stroke-width="1"
                        stroke-dasharray="3 3"
                        pointer-events="none"
                    />
                    {#each hoverData.items as it}
                        <circle
                            cx={xFor(it.p.time)}
                            cy={yFor(it.s, it.p.value)}
                            r="3"
                            fill={it.s.color}
                            stroke="rgb(10 10 10)"
                            stroke-width="1.5"
                            pointer-events="none"
                        />
                    {/each}
                {/if}
            </svg>

            {#if hoverX !== null && hoverData && hoverData.items.length > 0}
                <div
                    class="pointer-events-none absolute top-2 z-10 rounded-md border border-neutral-700 bg-neutral-950/95 px-2.5 py-1.5 text-[11px] shadow-lg backdrop-blur"
                    style:left={`${Math.min(Math.max((hoverX / width) * 100, 4), 78)}%`}
                >
                    <div class="mb-1 font-mono text-[10px] text-neutral-500">
                        {fmtHover(hoverData.t)}
                    </div>
                    <ul class="space-y-0.5">
                        {#each hoverData.items as it}
                            <li class="flex items-center gap-2">
                                <span
                                    class="inline-block h-2 w-2 rounded-full"
                                    style:background-color={it.s.color}
                                ></span>
                                <span class="text-neutral-400">{it.s.label}</span>
                                <span class="ml-auto font-mono tabular-nums text-neutral-100">
                                    {it.p.value.toFixed(it.s.precision ?? 1)}{it.s.unit ?? ''}
                                </span>
                            </li>
                        {/each}
                    </ul>
                </div>
            {/if}
        </div>

        {#if showLegend}
        <ul class="flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {#each series as s}
                {@const lv = lastValue(s)}
                {@const off = hidden.has(s.label)}
                <li>
                    <button
                        type="button"
                        onclick={() => toggle(s.label)}
                        class="flex items-center gap-1.5 rounded px-1.5 py-0.5 transition hover:bg-neutral-800/50 {off
                            ? 'opacity-40'
                            : ''}"
                        title={off ? 'Afficher' : 'Masquer'}
                    >
                        <span
                            class="inline-block h-2 w-2 rounded-full"
                            style:background-color={s.color}
                        ></span>
                        <span class="text-neutral-400">{s.label}</span>
                        <span class="font-mono tabular-nums text-neutral-200">
                            {lv === null ? '—' : lv.toFixed(s.precision ?? 1)}{s.unit ?? ''}
                        </span>
                    </button>
                </li>
            {/each}
        </ul>
        {/if}
    {/if}
</div>
