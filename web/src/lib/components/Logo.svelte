<script lang="ts">
    interface Props {
        size?: number;
        glow?: boolean;
        animated?: boolean;
        class?: string;
    }

    let { size = 32, glow = false, animated = false, class: klass = '' }: Props = $props();
</script>

<span
    class="spouet-logo {klass}"
    class:glow
    class:animated
    style="width:{size}px;height:{size}px"
    aria-hidden="true"
>
    <img src="/logo.png" alt="Spouet" width={size} height={size} draggable="false" />
</span>

<style>
    .spouet-logo {
        display: inline-grid;
        place-items: center;
        position: relative;
        line-height: 0;
    }
    .spouet-logo img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        /* Le logo source est sombre sur fond transparent : on inverse pour
           qu'il rende clair sur le thème sombre, puis on teinte légèrement
           cyan via une drop-shadow. */
        filter: invert(1) brightness(1.05)
            drop-shadow(0 0 6px oklch(0.7 0.18 210 / 0.35));
        user-select: none;
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
    .spouet-logo.animated img {
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
            transform: translateY(-3%) rotate(0.5deg);
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
</style>
