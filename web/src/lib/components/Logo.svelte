<script module lang="ts">
    // id de gradient unique par instance (plusieurs logos sur la page ne se
    // marchent pas dessus).
    let _uid = 0;
</script>

<script lang="ts">
    interface Props {
        size?: number;
        glow?: boolean;
        animated?: boolean;
        class?: string;
    }

    let { size = 32, glow = false, animated = false, class: klass = '' }: Props = $props();

    const id = `logo-${++_uid}`;
</script>

<!--
    Logo « Spouet » dessiné en SVG inline (vectoriel, net à toute taille, sans
    dépendance à un asset raster ni hack `invert`). Motif nœud + orbite + satellite,
    cohérent avec le favicon : évoque l'orchestration multi-nodes. Couleurs propres
    → rend identique en thème sombre comme clair.
-->
<span
    class="spouet-logo {klass}"
    class:glow
    class:animated
    style="width:{size}px;height:{size}px"
    aria-hidden="true"
>
    <svg viewBox="0 0 64 64" width={size} height={size}>
        <defs>
            <radialGradient id={`${id}-core`} cx="36%" cy="30%" r="75%">
                <stop offset="0%" stop-color="oklch(0.9 0.1 200)" />
                <stop offset="55%" stop-color="oklch(0.72 0.16 215)" />
                <stop offset="100%" stop-color="oklch(0.58 0.17 245)" />
            </radialGradient>
            <linearGradient id={`${id}-ring`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="oklch(0.82 0.15 200)" />
                <stop offset="100%" stop-color="oklch(0.62 0.17 250)" />
            </linearGradient>
        </defs>

        <!-- Orbite -->
        <circle
            cx="32"
            cy="32"
            r="21"
            fill="none"
            stroke={`url(#${id}-ring)`}
            stroke-width="3"
            opacity="0.5"
        />
        <!-- Satellite (le bloc tourne autour du cœur en mode `animated`) -->
        <g class="sat-orbit">
            <circle class="sat" cx="32" cy="11" r="3.6" fill="oklch(0.86 0.13 205)" />
        </g>
        <!-- Cœur -->
        <circle cx="32" cy="32" r="10.5" fill={`url(#${id}-core)`} />
        <!-- Reflet -->
        <circle cx="28.5" cy="28" r="3" fill="oklch(1 0 0 / 0.55)" />
    </svg>
</span>

<style>
    .spouet-logo {
        display: inline-grid;
        place-items: center;
        position: relative;
        line-height: 0;
    }
    .spouet-logo svg {
        width: 100%;
        height: 100%;
        overflow: visible;
        filter: drop-shadow(0 0 5px oklch(0.7 0.18 210 / 0.35));
        user-select: none;
    }
    .sat-orbit {
        transform-box: fill-box;
        transform-origin: 32px 32px;
    }
    .spouet-logo.animated .sat-orbit {
        animation: spouet-orbit 7s linear infinite;
    }
    .spouet-logo.animated svg {
        animation: spouet-float 4.5s ease-in-out infinite;
    }
    .spouet-logo.glow::before {
        content: '';
        position: absolute;
        inset: -25%;
        border-radius: 9999px;
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.18 210 / 0.35),
            oklch(0.55 0.18 210 / 0.1) 60%,
            transparent 75%
        );
        filter: blur(8px);
        z-index: -1;
        pointer-events: none;
    }
    .spouet-logo.animated.glow::before {
        animation: spouet-pulse 3s ease-in-out infinite;
    }
    @keyframes spouet-orbit {
        to {
            transform: rotate(360deg);
        }
    }
    @keyframes spouet-float {
        0%,
        100% {
            transform: translateY(0);
        }
        50% {
            transform: translateY(-4%);
        }
    }
    @keyframes spouet-pulse {
        0%,
        100% {
            opacity: 0.7;
            transform: scale(1);
        }
        50% {
            opacity: 1;
            transform: scale(1.08);
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .spouet-logo.animated .sat-orbit,
        .spouet-logo.animated svg {
            animation: none;
        }
    }
</style>
