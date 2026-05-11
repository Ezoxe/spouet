<script lang="ts">
    interface Props {
        points: number[];
        width?: number;
        height?: number;
        stroke?: string;
        fill?: string;
        max?: number;
        min?: number;
        label?: string;
        unit?: string;
        precision?: number;
    }

    let {
        points = [],
        width = 200,
        height = 56,
        stroke = 'currentColor',
        fill,
        max,
        min,
        label,
        unit,
        precision = 0
    }: Props = $props();

    const PAD = 2;

    const bounds = $derived.by(() => {
        if (points.length === 0) return { lo: 0, hi: 1 };
        const vMin = points.reduce((a, b) => Math.min(a, b), Infinity);
        const vMax = points.reduce((a, b) => Math.max(a, b), -Infinity);
        const lo = min ?? vMin;
        let hi = max ?? vMax;
        if (hi - lo < 1e-9) hi = lo + 1;
        return { lo, hi };
    });

    function toXY(i: number, v: number, n: number) {
        const x = n <= 1 ? width / 2 : (i / (n - 1)) * (width - 2 * PAD) + PAD;
        const norm = (v - bounds.lo) / (bounds.hi - bounds.lo);
        const y = height - PAD - norm * (height - 2 * PAD);
        return { x, y };
    }

    const path = $derived.by(() => {
        if (points.length === 0) return '';
        return points
            .map((v, i) => {
                const { x, y } = toXY(i, v, points.length);
                return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
            })
            .join(' ');
    });

    const area = $derived.by(() => {
        if (points.length === 0 || !fill) return '';
        const last = toXY(points.length - 1, points[points.length - 1], points.length);
        const first = toXY(0, points[0], points.length);
        return `${path} L ${last.x.toFixed(1)} ${height - PAD} L ${first.x.toFixed(1)} ${height - PAD} Z`;
    });

    const lastValue = $derived(points.length > 0 ? points[points.length - 1] : null);
    const lastXY = $derived(
        points.length > 0
            ? toXY(points.length - 1, points[points.length - 1], points.length)
            : null
    );

    const gradientId = $derived(
        `spark-grad-${Math.random().toString(36).slice(2, 9)}`
    );
</script>

<div class="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3">
    <div class="mb-1 flex items-baseline justify-between gap-2">
        {#if label}
            <span class="truncate text-[10px] uppercase tracking-wider text-neutral-500">{label}</span>
        {/if}
        {#if lastValue !== null}
            <span class="font-mono text-sm tabular-nums text-neutral-200">
                {lastValue.toFixed(precision)}{#if unit}<span class="ml-0.5 text-[10px] text-neutral-500">{unit}</span>{/if}
            </span>
        {:else}
            <span class="font-mono text-sm tabular-nums text-neutral-600">—</span>
        {/if}
    </div>
    <svg
        viewBox="0 0 {width} {height}"
        class="block h-12 w-full"
        preserveAspectRatio="none"
        style:color={stroke}
    >
        {#if fill}
            <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color={fill} stop-opacity="0.35" />
                    <stop offset="100%" stop-color={fill} stop-opacity="0" />
                </linearGradient>
            </defs>
            <path d={area} fill="url(#{gradientId})" stroke="none" />
        {/if}
        {#if path}
            <path d={path} fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        {/if}
        {#if lastXY}
            <circle cx={lastXY.x} cy={lastXY.y} r="2" fill="currentColor" />
        {/if}
    </svg>
</div>
