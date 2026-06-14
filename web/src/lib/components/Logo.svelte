<script lang="ts">
    interface Props {
        size?: number;
        glow?: boolean;
        animated?: boolean;
        class?: string;
    }

    let { size = 32, glow = false, animated = false, class: klass = '' }: Props = $props();
</script>

<!--
    Logo « Spouet » = l'image fournie par l'utilisateur (static/logo.png).
    Le fichier est un mark sombre sur fond blanc opaque : on le rend dans une TUILE
    arrondie (le fond blanc devient une pastille volontaire), nette sur thème sombre
    comme clair — pas de filtre `invert` (qui le transformait en carré noir).
-->
<span
    class="spouet-logo {klass}"
    class:glow
    class:animated
    style="--sz:{size}px"
    aria-hidden="true"
>
    <span class="tile">
        <img src="/logo.png" alt="Spouet" width={size} height={size} draggable="false" />
    </span>
</span>

<style>
    .spouet-logo {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: var(--sz);
        height: var(--sz);
        line-height: 0;
        flex: none;
    }
    .tile {
        position: relative;
        z-index: 1;
        display: block;
        width: 100%;
        height: 100%;
        border-radius: 24%;
        overflow: hidden;
        background: #fff;
        box-shadow:
            inset 0 0 0 1px oklch(0 0 0 / 0.1),
            0 1px 4px oklch(0 0 0 / 0.25);
    }
    .tile img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        user-select: none;
    }
    /* Halo (placé hors de la tuile clippée) */
    .spouet-logo.glow::before {
        content: '';
        position: absolute;
        inset: -22%;
        border-radius: 9999px;
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.18 210 / 0.35),
            oklch(0.55 0.18 210 / 0.1) 60%,
            transparent 75%
        );
        filter: blur(8px);
        z-index: 0;
        pointer-events: none;
    }
    .spouet-logo.animated .tile {
        animation: spouet-float 4.5s ease-in-out infinite;
    }
    .spouet-logo.animated.glow::before {
        animation: spouet-pulse 3s ease-in-out infinite;
    }
    @keyframes spouet-float {
        0%,
        100% {
            transform: translateY(0) rotate(-0.5deg);
        }
        50% {
            transform: translateY(-4%) rotate(0.5deg);
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
        .spouet-logo.animated .tile,
        .spouet-logo.animated.glow::before {
            animation: none;
        }
    }
</style>
