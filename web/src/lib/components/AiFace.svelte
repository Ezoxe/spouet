<script module lang="ts">
    // Compteur module-scope → id de clipPath unique par instance (évite que
    // plusieurs loutres sur la page partagent/cassent leur clip).
    let _uid = 0;
</script>

<script lang="ts">
    /**
     * Loutre « Spouet » — avatar expressif de l'assistant, dessiné en SVG et
     * animé en CSS. Dimensionnée via --s.
     *
     * Traits de loutre : tête ronde brune, gros museau crème, nez foncé, oreilles
     * rondes, moustaches. Les pupilles sont CLIPPÉES dans les yeux (elles ne
     * débordent jamais, même en regardant de côté).
     *
     * États : idle / thinking / writing / speaking / happy / surprised.
     * L'API ({size, state, class}) est inchangée.
     */
    interface Props {
        size?: number;
        state?: 'idle' | 'thinking' | 'writing' | 'speaking' | 'happy' | 'surprised';
        class?: string;
    }
    let { size = 32, state = 'idle', class: klass = '' }: Props = $props();

    const id = `otter-${++_uid}`;
</script>

<span class="otter {state} {klass}" style="--s:{size}px" role="img" aria-label="Spouet, l'assistant loutre">
    <svg viewBox="0 0 100 100" class="ot-svg">
        <defs>
            <clipPath id={`${id}-eyeL`}><ellipse cx="37" cy="49" rx="6.6" ry="7.6" /></clipPath>
            <clipPath id={`${id}-eyeR`}><ellipse cx="63" cy="49" rx="6.6" ry="7.6" /></clipPath>
        </defs>

        <g class="ot-body">
            <!-- Oreilles -->
            <g class="ear ear-l">
                <ellipse class="ear-out" cx="24" cy="26" rx="11" ry="12" />
                <ellipse class="ear-in" cx="24.5" cy="27" rx="5.5" ry="6" />
            </g>
            <g class="ear ear-r">
                <ellipse class="ear-out" cx="76" cy="26" rx="11" ry="12" />
                <ellipse class="ear-in" cx="75.5" cy="27" rx="5.5" ry="6" />
            </g>

            <!-- Tête -->
            <ellipse class="head" cx="50" cy="55" rx="34" ry="31" />
            <!-- Front un peu plus clair -->
            <ellipse class="head-hi" cx="50" cy="40" rx="26" ry="15" />

            <!-- Museau crème (large, signature loutre) -->
            <path
                class="muzzle"
                d="M50 50
                   C70 50 80 60 80 69
                   C80 81 66 88 50 88
                   C34 88 20 81 20 69
                   C20 60 30 50 50 50 Z"
            />
            <!-- Joues -->
            <circle class="cheek cheek-l" cx="29" cy="66" r="6" />
            <circle class="cheek cheek-r" cx="71" cy="66" r="6" />

            <!-- Moustaches -->
            <g class="whiskers wk-l">
                <line x1="33" y1="64" x2="11" y2="60" />
                <line x1="33" y1="67" x2="9" y2="67" />
                <line x1="33" y1="70" x2="11" y2="75" />
            </g>
            <g class="whiskers wk-r">
                <line x1="67" y1="64" x2="89" y2="60" />
                <line x1="67" y1="67" x2="91" y2="67" />
                <line x1="67" y1="70" x2="89" y2="75" />
            </g>

            <!-- Yeux ronds (sclère claire + pupille clippée) -->
            <g class="eyes">
                <g class="eye eye-l">
                    <ellipse class="sclera" cx="37" cy="49" rx="6.6" ry="7.6" />
                    <g class="pupil-wrap" clip-path={`url(#${id}-eyeL)`}>
                        <circle class="pupil" cx="37" cy="49.5" r="4.2" />
                        <circle class="glint" cx="35.2" cy="47.4" r="1.5" />
                    </g>
                </g>
                <g class="eye eye-r">
                    <ellipse class="sclera" cx="63" cy="49" rx="6.6" ry="7.6" />
                    <g class="pupil-wrap" clip-path={`url(#${id}-eyeR)`}>
                        <circle class="pupil" cx="63" cy="49.5" r="4.2" />
                        <circle class="glint" cx="61.2" cy="47.4" r="1.5" />
                    </g>
                </g>
            </g>
            <!-- Yeux « heureux » : arcs ^^ (state happy) -->
            <path class="eye-happy" d="M30 51 Q37 44 44 51" />
            <path class="eye-happy" d="M56 51 Q63 44 70 51" />

            <!-- Nez -->
            <path class="nose" d="M43 58 Q50 53 57 58 Q57 64 50 67 Q43 64 43 58 Z" />
            <!-- Bouche normale (ω) -->
            <path class="mouth m-omega" d="M50 67 Q46 71 42 68" />
            <path class="mouth m-omega" d="M50 67 Q54 71 58 68" />
            <!-- Grand sourire (state happy) -->
            <path class="mouth m-smile" d="M40 67 Q50 77 60 67" />
            <!-- Bouche ouverte (speaking / surprised) -->
            <ellipse class="mouth-open" cx="50" cy="71" rx="4.2" ry="3" />
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
        filter: drop-shadow(0 calc(var(--s) * 0.03) calc(var(--s) * 0.06) oklch(0.3 0.08 50 / 0.35));
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

    /* Couleurs (lisibles en thème clair comme sombre) */
    .head { fill: oklch(0.57 0.08 53); }
    .head-hi { fill: oklch(0.64 0.075 58); opacity: 0.5; }
    .ear-out { fill: oklch(0.5 0.08 50); }
    .ear-in { fill: oklch(0.66 0.07 33); }
    .muzzle { fill: oklch(0.94 0.025 80); }
    .cheek { fill: oklch(0.8 0.09 32); opacity: 0.4; }
    .sclera { fill: oklch(0.99 0.005 90); }
    .pupil { fill: oklch(0.21 0.03 55); }
    .glint { fill: oklch(1 0 0); opacity: 0.95; }
    .nose { fill: oklch(0.29 0.03 45); }
    .mouth {
        fill: none;
        stroke: oklch(0.3 0.03 45);
        stroke-width: 2.2;
        stroke-linecap: round;
    }
    .m-smile { display: none; }
    .mouth-open { fill: oklch(0.33 0.05 28); opacity: 0; }
    .eye-happy {
        fill: none;
        stroke: oklch(0.21 0.03 55);
        stroke-width: 3;
        stroke-linecap: round;
        opacity: 0;
    }
    .whiskers line {
        stroke: oklch(0.7 0.02 70);
        stroke-width: 1.2;
        stroke-linecap: round;
        opacity: 0.55;
    }
    .wk-l { transform-box: fill-box; transform-origin: 100% 50%; }
    .wk-r { transform-box: fill-box; transform-origin: 0% 50%; }

    /* Oreilles : pivot à la base */
    .ear { transform-box: fill-box; transform-origin: 50% 85%; }
    .otter.idle .ear-l { animation: ot-ear-l 5.5s ease-in-out infinite; }
    .otter.idle .ear-r { animation: ot-ear-r 6.2s ease-in-out infinite; }
    .otter.idle .whiskers { animation: ot-whisker 4s ease-in-out infinite; }

    /* Clignements (toute la loutre cligne ensemble) */
    .eye { transform-box: fill-box; transform-origin: center; animation: ot-blink 4.8s infinite; }
    .eye-r { animation-delay: 0.05s; }

    /* Pupilles : translation en UNITÉS SVG, bornée, + clip → jamais de débordement */
    .pupil-wrap { transform-box: fill-box; transform-origin: center; transition: transform 0.4s ease; }

    /* idle : le regard se balade */
    .otter.idle .pupil-wrap { animation: ot-dart 7s ease-in-out infinite; }

    /* thinking : tête penchée + regard en l'air */
    .otter.thinking .ot-body { animation: ot-tilt 2.6s ease-in-out infinite; }
    .otter.thinking .pupil-wrap { transform: translate(0px, -2px); }
    .otter.thinking .eye { animation-duration: 3.6s; }

    /* writing : regard concentré qui scribble */
    .otter.writing .pupil-wrap { animation: ot-scribble 0.6s ease-in-out infinite; }

    /* speaking : museau qui parle */
    .otter.speaking .mouth-open {
        opacity: 1;
        transform-box: fill-box;
        transform-origin: center;
        animation: ot-talk 0.34s ease-in-out infinite;
    }
    .otter.speaking .m-omega { opacity: 0.4; }

    /* happy : yeux en arcs + grand sourire + rebond */
    .otter.happy .eye { opacity: 0; }
    .otter.happy .eye-happy { opacity: 1; }
    .otter.happy .m-omega { display: none; }
    .otter.happy .m-smile { display: block; }
    .otter.happy .cheek { opacity: 0.72; }
    .otter.happy .ot-body { animation: ot-hop 0.7s ease-in-out infinite; }

    /* surprised : yeux écarquillés + museau « o » + pop */
    .otter.surprised .eye { transform: scale(1.18); animation: none; }
    .otter.surprised .mouth-open { opacity: 1; }
    .otter.surprised .m-omega { opacity: 0; }
    .otter.surprised .ot-body { animation: ot-pop 0.4s ease-out; }

    /* Bulle d'état (?/!) */
    .glyph {
        position: absolute;
        top: -12%;
        right: -14%;
        min-width: calc(var(--s) * 0.46);
        height: calc(var(--s) * 0.46);
        padding: 0 calc(var(--s) * 0.06);
        display: grid;
        place-items: center;
        font-size: calc(var(--s) * 0.36);
        font-weight: 800;
        line-height: 1;
        color: oklch(0.2 0.04 262);
        border-radius: 999px;
        box-shadow: 0 calc(var(--s) * 0.04) calc(var(--s) * 0.1) calc(var(--s) * -0.02) oklch(0 0 0 / 0.45);
        transform-origin: bottom left;
        animation:
            ot-glyph-pop 0.28s ease-out backwards,
            ot-glyph-bob 2.1s ease-in-out infinite 0.28s;
    }
    .glyph.think { background: linear-gradient(160deg, oklch(0.9 0.12 205), oklch(0.78 0.14 210)); }
    .glyph.bang { background: linear-gradient(160deg, oklch(0.9 0.15 95), oklch(0.82 0.16 75)); }

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
        0% { transform: scale(0.82); }
        60% { transform: scale(1.08); }
        100% { transform: scale(1); }
    }
    @keyframes ot-blink {
        0%, 92%, 100% { transform: scaleY(1); }
        96% { transform: scaleY(0.1); }
    }
    /* Mouvement borné (max ~2.4u) → reste dans la sclère, et clippé de toute façon */
    @keyframes ot-dart {
        0%, 16% { transform: translate(0px, 0px); }
        22%, 40% { transform: translate(2.4px, -0.8px); }
        46%, 64% { transform: translate(-2.4px, 0.8px); }
        70%, 100% { transform: translate(0px, 0px); }
    }
    @keyframes ot-scribble {
        0%, 100% { transform: translate(-1.8px, 1.6px); }
        50% { transform: translate(1.8px, 1.6px); }
    }
    @keyframes ot-talk {
        0%, 100% { transform: scaleY(0.4); }
        50% { transform: scaleY(1.15); }
    }
    @keyframes ot-ear-l {
        0%, 84%, 100% { transform: rotate(0deg); }
        90% { transform: rotate(-12deg); }
    }
    @keyframes ot-ear-r {
        0%, 80%, 100% { transform: rotate(0deg); }
        88% { transform: rotate(12deg); }
    }
    @keyframes ot-whisker {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(2.5deg); }
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
        .ot-body, .eye, .pupil-wrap, .ear, .whiskers, .mouth-open, .glyph {
            animation: none !important;
        }
    }
</style>
