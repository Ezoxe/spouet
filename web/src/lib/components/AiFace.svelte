<script lang="ts">
    /**
     * Loutre « Spouet » — personnage/avatar expressif de l'assistant.
     * Dessinée en SVG (pas un emoji), animée en pur CSS, dimensionnée via --s.
     *
     * États :
     *   - idle      : vivante au repos (bob, clignements, regard qui se balade,
     *                 oreilles + moustaches qui frémissent)
     *   - thinking  : tête penchée, regard en l'air, bulle « ? »
     *   - writing   : regard concentré qui « scribble », bulle « ! »
     *   - speaking  : museau qui s'anime (parle)
     *   - happy     : yeux en arcs ^^ + petit rebond joyeux
     *   - surprised : yeux écarquillés + museau en « o » + pop
     *
     * L'API ({size, state, class}) est identique à l'ancien visage abstrait.
     */
    interface Props {
        size?: number;
        state?: 'idle' | 'thinking' | 'writing' | 'speaking' | 'happy' | 'surprised';
        class?: string;
    }
    let { size = 28, state = 'idle', class: klass = '' }: Props = $props();
</script>

<span class="otter {state} {klass}" style="--s:{size}px" role="img" aria-label="Spouet, l'assistant loutre">
    <svg viewBox="0 0 100 100" class="ot-svg">
        <g class="ot-body">
            <!-- Oreilles -->
            <g class="ear ear-l">
                <ellipse class="ear-out" cx="26" cy="25" rx="11" ry="12" />
                <ellipse class="ear-in" cx="26" cy="26" rx="5.5" ry="6" />
            </g>
            <g class="ear ear-r">
                <ellipse class="ear-out" cx="74" cy="25" rx="11" ry="12" />
                <ellipse class="ear-in" cx="74" cy="26" rx="5.5" ry="6" />
            </g>

            <!-- Tête -->
            <ellipse class="head" cx="50" cy="55" rx="34" ry="31" />
            <!-- Reflet diffus haut -->
            <ellipse class="head-hi" cx="42" cy="38" rx="20" ry="13" />

            <!-- Museau (zone claire) -->
            <ellipse class="muzzle" cx="50" cy="68" rx="21" ry="16" />
            <!-- Joues -->
            <circle class="cheek cheek-l" cx="28" cy="64" r="5.5" />
            <circle class="cheek cheek-r" cx="72" cy="64" r="5.5" />

            <!-- Moustaches -->
            <g class="whiskers wk-l">
                <line x1="34" y1="64" x2="13" y2="60" />
                <line x1="34" y1="67" x2="12" y2="67" />
                <line x1="34" y1="70" x2="14" y2="74" />
            </g>
            <g class="whiskers wk-r">
                <line x1="66" y1="64" x2="87" y2="60" />
                <line x1="66" y1="67" x2="88" y2="67" />
                <line x1="66" y1="70" x2="86" y2="74" />
            </g>

            <!-- Yeux ronds -->
            <g class="eyes">
                <g class="eye eye-l">
                    <ellipse class="sclera" cx="37" cy="49" rx="7.5" ry="8.5" />
                    <circle class="pupil" cx="37" cy="50" r="4.3" />
                    <circle class="glint" cx="35" cy="47.5" r="1.5" />
                </g>
                <g class="eye eye-r">
                    <ellipse class="sclera" cx="63" cy="49" rx="7.5" ry="8.5" />
                    <circle class="pupil" cx="63" cy="50" r="4.3" />
                    <circle class="glint" cx="61" cy="47.5" r="1.5" />
                </g>
            </g>
            <!-- Yeux « heureux » (arcs ^^), montrés en state happy -->
            <path class="eye-happy" d="M30 50 Q37 43 44 50" />
            <path class="eye-happy" d="M56 50 Q63 43 70 50" />

            <!-- Nez -->
            <path class="nose" d="M44 59 Q50 54 56 59 Q56 64 50 66 Q44 64 44 59 Z" />
            <!-- Bouche / snout (deux courbes ω) -->
            <path class="mouth" d="M50 66 Q50 72 43 71" />
            <path class="mouth" d="M50 66 Q50 72 57 71" />
            <!-- Bouche ouverte (speaking / surprised) -->
            <ellipse class="mouth-open" cx="50" cy="71.5" rx="4.2" ry="2.6" />
        </g>
    </svg>

    {#if state === 'thinking'}
        <span class="glyph think">?</span>
    {:else if state === 'writing'}
        <span class="glyph bang">!</span>
    {/if}
</span>

<style>
    .otter {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: var(--s);
        height: var(--s);
        flex: none;
        filter: drop-shadow(0 calc(var(--s) * 0.03) calc(var(--s) * 0.06) oklch(0.3 0.08 50 / 0.4));
    }
    .ot-svg {
        width: 100%;
        height: 100%;
        overflow: visible;
    }
    .ot-body {
        transform-box: fill-box;
        transform-origin: 50% 80%;
        animation: ot-bob 4.6s ease-in-out infinite;
    }

    /* — Couleurs loutre (lisibles en clair comme en sombre) — */
    .head {
        fill: oklch(0.55 0.07 55);
    }
    .head-hi {
        fill: oklch(0.66 0.07 60);
        opacity: 0.55;
    }
    .ear-out {
        fill: oklch(0.5 0.07 52);
    }
    .ear-in {
        fill: oklch(0.62 0.08 35);
    }
    .muzzle {
        fill: oklch(0.93 0.03 75);
    }
    .cheek {
        fill: oklch(0.78 0.1 35);
        opacity: 0.45;
    }
    .sclera {
        fill: oklch(0.99 0.005 90);
    }
    .pupil {
        fill: oklch(0.22 0.03 60);
    }
    .glint {
        fill: oklch(1 0 0);
        opacity: 0.95;
    }
    .nose {
        fill: oklch(0.28 0.03 50);
    }
    .mouth {
        fill: none;
        stroke: oklch(0.3 0.03 50);
        stroke-width: 2;
        stroke-linecap: round;
    }
    .mouth-open {
        fill: oklch(0.32 0.05 30);
        opacity: 0;
    }
    .eye-happy {
        fill: none;
        stroke: oklch(0.22 0.03 60);
        stroke-width: 3;
        stroke-linecap: round;
        opacity: 0;
    }
    .whiskers line {
        stroke: oklch(0.75 0.02 70);
        stroke-width: 1.2;
        stroke-linecap: round;
        opacity: 0.6;
    }
    .wk-l {
        transform-box: fill-box;
        transform-origin: 100% 50%;
    }
    .wk-r {
        transform-box: fill-box;
        transform-origin: 0% 50%;
    }

    /* — Oreilles : pivot à la base — */
    .ear {
        transform-box: fill-box;
        transform-origin: 50% 85%;
    }
    .otter.idle .ear-l {
        animation: ot-ear-l 5.5s ease-in-out infinite;
    }
    .otter.idle .ear-r {
        animation: ot-ear-r 5.5s ease-in-out infinite;
    }
    .otter.idle .whiskers {
        animation: ot-whisker 4s ease-in-out infinite;
    }

    /* — Clignements — */
    .eye {
        transform-box: fill-box;
        transform-origin: center;
        animation: ot-blink 4.8s infinite;
    }
    .eye-r {
        animation-delay: 0.04s;
    }
    .pupil {
        transition: transform 0.4s ease;
    }

    /* — idle : regard qui se balade — */
    .otter.idle .pupil {
        animation: ot-dart 7s ease-in-out infinite;
    }

    /* — thinking : tête penchée, regard en l'air — */
    .otter.thinking .ot-body {
        animation: ot-tilt 2.6s ease-in-out infinite;
    }
    .otter.thinking .pupil {
        transform: translateY(-18%);
    }
    .otter.thinking .eye {
        animation-duration: 3.6s;
    }

    /* — writing : regard concentré qui scribble — */
    .otter.writing .pupil {
        animation: ot-scribble 0.6s ease-in-out infinite;
    }

    /* — speaking : museau qui parle — */
    .otter.speaking .mouth-open {
        opacity: 1;
        transform-box: fill-box;
        transform-origin: center;
        animation: ot-talk 0.34s ease-in-out infinite;
    }
    .otter.speaking .mouth {
        opacity: 0.35;
    }

    /* — happy : yeux en arcs + rebond — */
    .otter.happy .eye {
        opacity: 0;
    }
    .otter.happy .eye-happy {
        opacity: 1;
    }
    .otter.happy .cheek {
        opacity: 0.7;
    }
    .otter.happy .ot-body {
        animation: ot-hop 0.7s ease-in-out infinite;
    }

    /* — surprised : yeux écarquillés + museau « o » + pop — */
    .otter.surprised .eye {
        transform: scale(1.18);
        animation: none;
    }
    .otter.surprised .mouth-open {
        opacity: 1;
    }
    .otter.surprised .mouth {
        opacity: 0;
    }
    .otter.surprised .ot-body {
        animation: ot-pop 0.4s ease-out;
    }

    /* Bulle d'état flottante (?/!) — reprise de l'ancien visage */
    .glyph {
        position: absolute;
        top: -14%;
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
            ot-glyph-pop 0.28s ease-out backwards,
            ot-glyph-bob 2.1s ease-in-out infinite 0.28s;
    }
    .glyph.think {
        background: linear-gradient(160deg, oklch(0.9 0.12 205), oklch(0.78 0.14 210));
    }
    .glyph.bang {
        background: linear-gradient(160deg, oklch(0.9 0.15 95), oklch(0.82 0.16 75));
    }

    @keyframes ot-bob {
        0%, 100% { transform: translateY(0) rotate(-1deg); }
        50% { transform: translateY(-4%) rotate(1deg); }
    }
    @keyframes ot-tilt {
        0%, 100% { transform: translateY(0) rotate(-7deg); }
        50% { transform: translateY(-2%) rotate(6deg); }
    }
    @keyframes ot-hop {
        0%, 100% { transform: translateY(0) scale(1); }
        40% { transform: translateY(-9%) scale(1.03, 0.97); }
        70% { transform: translateY(0) scale(0.98, 1.02); }
    }
    @keyframes ot-pop {
        0% { transform: scale(0.8); }
        60% { transform: scale(1.08); }
        100% { transform: scale(1); }
    }
    @keyframes ot-blink {
        0%, 92%, 100% { transform: scaleY(1); }
        96% { transform: scaleY(0.1); }
    }
    @keyframes ot-dart {
        0%, 16% { transform: translate(0, 0); }
        22%, 40% { transform: translate(22%, -6%); }
        46%, 64% { transform: translate(-22%, 4%); }
        70%, 100% { transform: translate(0, 0); }
    }
    @keyframes ot-scribble {
        0%, 100% { transform: translate(-16%, 18%); }
        50% { transform: translate(16%, 18%); }
    }
    @keyframes ot-talk {
        0%, 100% { transform: scaleY(0.35); }
        50% { transform: scaleY(1.15); }
    }
    @keyframes ot-ear-l {
        0%, 84%, 100% { transform: rotate(0deg); }
        90% { transform: rotate(-11deg); }
    }
    @keyframes ot-ear-r {
        0%, 80%, 100% { transform: rotate(0deg); }
        88% { transform: rotate(11deg); }
    }
    @keyframes ot-whisker {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(2deg); }
    }
    @keyframes ot-glyph-pop {
        0% { transform: scale(0.2); opacity: 0; }
        70% { transform: scale(1.15); }
        100% { transform: scale(1); opacity: 1; }
    }
    @keyframes ot-glyph-bob {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-12%); }
    }

    @media (prefers-reduced-motion: reduce) {
        .ot-body,
        .eye,
        .pupil,
        .ear,
        .whiskers,
        .mouth-open,
        .glyph {
            animation: none !important;
        }
    }
</style>
