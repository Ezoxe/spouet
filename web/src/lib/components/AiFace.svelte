<script lang="ts">
    /**
     * Visage « IA » — petit personnage expressif, identité de l'assistant dans
     * les conversations. Les yeux clignent et se baladent ; un glyphe flotte
     * selon l'état :
     *   - idle     : regard qui se balade, clignements lents
     *   - thinking : regard vers le haut + bulle « ? »
     *   - writing  : yeux qui « scribblent » + bulle « ! »
     *   - speaking : bouche qui s'anime
     * Pur CSS, sans dépendance. Tout est dimensionné via --s (taille en px).
     */
    interface Props {
        size?: number;
        state?: 'idle' | 'thinking' | 'writing' | 'speaking';
        class?: string;
    }
    let { size = 28, state = 'idle', class: klass = '' }: Props = $props();
</script>

<span class="face {state} {klass}" style="--s:{size}px" aria-hidden="true">
    <span class="cheeks"></span>
    <span class="eyes">
        <span class="eye"><span class="pupil"></span></span>
        <span class="eye"><span class="pupil"></span></span>
    </span>
    <span class="mouth"></span>
    {#if state === 'thinking'}
        <span class="glyph think">?</span>
    {:else if state === 'writing'}
        <span class="glyph bang">!</span>
    {/if}
</span>

<style>
    .face {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: var(--s);
        height: var(--s);
        flex: none;
        border-radius: 44% 44% 48% 48% / 48% 48% 44% 44%;
        background:
            radial-gradient(circle at 32% 24%, oklch(0.82 0.11 205 / 0.95), transparent 52%),
            linear-gradient(155deg, oklch(0.64 0.16 232), oklch(0.47 0.16 272));
        box-shadow:
            inset 0 0 calc(var(--s) * 0.12) oklch(0 0 0 / 0.35),
            0 calc(var(--s) * 0.04) calc(var(--s) * 0.2) calc(var(--s) * -0.04)
                oklch(0.5 0.18 250 / 0.5);
        animation: face-bob 4.5s ease-in-out infinite;
    }

    /* Joues / reflet diffus */
    .cheeks {
        position: absolute;
        inset: 12%;
        border-radius: inherit;
        background: radial-gradient(
            circle at 50% 78%,
            oklch(0.78 0.13 200 / 0.25),
            transparent 60%
        );
        pointer-events: none;
    }

    .eyes {
        position: absolute;
        top: 33%;
        display: flex;
        gap: calc(var(--s) * 0.16);
    }
    .eye {
        position: relative;
        width: calc(var(--s) * 0.21);
        height: calc(var(--s) * 0.27);
        background: oklch(0.99 0.01 230);
        border-radius: 50%;
        overflow: hidden;
        box-shadow: inset 0 calc(var(--s) * -0.02) calc(var(--s) * 0.03) oklch(0.6 0.12 250 / 0.4);
        animation: blink 4.6s infinite;
        transform-origin: center;
    }
    .pupil {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 58%;
        height: 58%;
        border-radius: 50%;
        background: radial-gradient(circle at 38% 32%, oklch(0.45 0.06 260), oklch(0.16 0.05 262));
        transform: translate(-50%, -50%);
        transition: transform 0.45s ease;
    }

    .mouth {
        position: absolute;
        bottom: 23%;
        width: calc(var(--s) * 0.24);
        height: calc(var(--s) * 0.07);
        background: oklch(0.18 0.05 262 / 0.85);
        border-radius: 0 0 999px 999px;
    }

    /* Bulle d'état flottante (?/!) */
    .glyph {
        position: absolute;
        top: -16%;
        right: -16%;
        min-width: calc(var(--s) * 0.5);
        height: calc(var(--s) * 0.5);
        padding: 0 calc(var(--s) * 0.07);
        display: grid;
        place-items: center;
        font-size: calc(var(--s) * 0.4);
        font-weight: 800;
        line-height: 1;
        color: oklch(0.2 0.04 262);
        border-radius: 999px;
        box-shadow: 0 calc(var(--s) * 0.04) calc(var(--s) * 0.1) calc(var(--s) * -0.02)
            oklch(0 0 0 / 0.45);
        transform-origin: bottom left;
        animation:
            glyph-pop 0.28s ease-out backwards,
            glyph-bob 2.1s ease-in-out infinite 0.28s;
    }
    .glyph.think {
        background: linear-gradient(160deg, oklch(0.9 0.12 205), oklch(0.78 0.14 210));
    }
    .glyph.bang {
        background: linear-gradient(160deg, oklch(0.9 0.15 95), oklch(0.82 0.16 75));
    }

    /* — idle : le regard se balade — */
    .face.idle .pupil {
        animation: dart 6.5s ease-in-out infinite;
    }

    /* — thinking : regard en l'air, léger balancement — */
    .face.thinking {
        animation: face-tilt 2.4s ease-in-out infinite;
    }
    .face.thinking .pupil {
        transform: translate(-50%, -50%) translate(20%, -30%);
    }
    .face.thinking .eye {
        animation-duration: 3.4s;
    }

    /* — writing : yeux qui scribblent, bouche concentrée — */
    .face.writing .pupil {
        animation: scribble 0.55s ease-in-out infinite;
    }
    .face.writing .mouth {
        width: calc(var(--s) * 0.16);
    }

    /* — speaking : bouche qui parle — */
    .face.speaking .mouth {
        animation: talk 0.34s ease-in-out infinite;
    }

    @keyframes blink {
        0%, 92%, 100% { transform: scaleY(1); }
        96% { transform: scaleY(0.1); }
    }
    @keyframes dart {
        0%, 18% { transform: translate(-50%, -50%); }
        24%, 42% { transform: translate(-50%, -50%) translate(24%, -8%); }
        48%, 66% { transform: translate(-50%, -50%) translate(-24%, 6%); }
        72%, 100% { transform: translate(-50%, -50%); }
    }
    @keyframes scribble {
        0%, 100% { transform: translate(-50%, -50%) translate(-14%, 20%); }
        50% { transform: translate(-50%, -50%) translate(14%, 20%); }
    }
    @keyframes talk {
        0%, 100% { height: calc(var(--s) * 0.05); }
        50% { height: calc(var(--s) * 0.16); }
    }
    @keyframes face-bob {
        0%, 100% { transform: translateY(0) rotate(-1deg); }
        50% { transform: translateY(-4%) rotate(1deg); }
    }
    @keyframes face-tilt {
        0%, 100% { transform: translateY(0) rotate(-4deg); }
        50% { transform: translateY(-3%) rotate(4deg); }
    }
    @keyframes glyph-pop {
        0% { transform: scale(0.2); opacity: 0; }
        70% { transform: scale(1.15); }
        100% { transform: scale(1); opacity: 1; }
    }
    @keyframes glyph-bob {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-12%); }
    }

    @media (prefers-reduced-motion: reduce) {
        .face,
        .face.idle .pupil,
        .face.writing .pupil,
        .eye,
        .mouth,
        .glyph {
            animation: none !important;
        }
    }
</style>
