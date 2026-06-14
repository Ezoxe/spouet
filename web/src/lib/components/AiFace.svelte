<script module lang="ts">
    // Compteur module-scope → id de clipPath unique par instance (évite que
    // plusieurs loutres sur la page partagent/cassent leur clip).
    let _uid = 0;
</script>

<script lang="ts">
    import { onMount } from 'svelte';

    /**
     * Loutre « Spouet » — avatar expressif de l'assistant, dessiné en SVG et
     * animé en CSS. Dimensionnée via --s.
     *
     * Nouveautés : visage plus rond façon loutre (museau crème large, gros nez,
     * petites oreilles, joues roses), sourcils expressifs par état, et surtout un
     * SUIVI DU REGARD : les pupilles (clippées dans les yeux) suivent la souris,
     * avec un repli en balade douce après inactivité.
     *
     * États : idle / thinking / writing / speaking / happy / surprised.
     * L'API ({size, state, class}) est inchangée.
     */
    interface Props {
        size?: number;
        state?: 'idle' | 'thinking' | 'writing' | 'speaking' | 'happy' | 'surprised';
        class?: string;
    }
    // Renommé `state` → `faceState` en interne : le prop s'appelle bien `state`
    // côté API, mais ce nom entre en collision avec la rune `$state(...)`.
    let { size = 32, state: faceState = 'idle', class: klass = '' }: Props = $props();

    const id = `otter-${++_uid}`;

    let faceEl: HTMLElement | undefined = $state();
    // Direction du regard, normalisée -1..1. Pilotée par la souris.
    let gazeX = $state(0);
    let gazeY = $state(0);
    let tracking = $state(false);
    let idleTimer: ReturnType<typeof setTimeout> | null = null;

    const reduced =
        typeof window !== 'undefined' &&
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    function onMove(e: MouseEvent) {
        if (!faceEl) return;
        const r = faceEl.getBoundingClientRect();
        if (r.width === 0) return;
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height * 0.46; // les yeux sont un peu au-dessus du centre
        // Portée ≈ 1.6× la largeur du visage : suivi naturel de près, plafonné au loin.
        const reach = r.width * 1.6;
        gazeX = Math.max(-1, Math.min(1, (e.clientX - cx) / reach));
        gazeY = Math.max(-1, Math.min(1, (e.clientY - cy) / reach));
        tracking = true;
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
            tracking = false;
            gazeX = 0;
            gazeY = 0;
        }, 2600);
    }

    onMount(() => {
        if (reduced) return;
        window.addEventListener('mousemove', onMove, { passive: true });
        return () => {
            window.removeEventListener('mousemove', onMove);
            if (idleTimer) clearTimeout(idleTimer);
        };
    });

    // Translations en unités SVG (viewBox 100). Pupilles bornées + clippées →
    // jamais de débordement hors de la sclère.
    const pupilTx = $derived((gazeX * 2.7).toFixed(2));
    const pupilTy = $derived((gazeY * 2.3).toFixed(2));
    // Parallaxe légère du bloc facial (donne de la profondeur / « l'intelligence »).
    const faceTx = $derived((gazeX * 1.1).toFixed(2));
    const faceTy = $derived((gazeY * 0.9).toFixed(2));
</script>

<span
    bind:this={faceEl}
    class="otter {faceState} {klass}"
    class:tracking
    style="--s:{size}px"
    role="img"
    aria-label="Spouet, l'assistant loutre"
>
    <svg viewBox="0 0 100 100" class="ot-svg">
        <defs>
            <clipPath id={`${id}-eyeL`}><ellipse cx="39" cy="51" rx="7.2" ry="8" /></clipPath>
            <clipPath id={`${id}-eyeR`}><ellipse cx="61" cy="51" rx="7.2" ry="8" /></clipPath>
            <radialGradient id={`${id}-head`} cx="50%" cy="32%" r="75%">
                <stop offset="0%" stop-color="oklch(0.62 0.075 56)" />
                <stop offset="100%" stop-color="oklch(0.54 0.08 50)" />
            </radialGradient>
        </defs>

        <g class="ot-body">
            <!-- Oreilles rondes (petites, écartées) -->
            <g class="ear ear-l">
                <ellipse class="ear-out" cx="25" cy="29" rx="10" ry="10.5" />
                <ellipse class="ear-in" cx="25.5" cy="30" rx="5" ry="5.5" />
            </g>
            <g class="ear ear-r">
                <ellipse class="ear-out" cx="75" cy="29" rx="10" ry="10.5" />
                <ellipse class="ear-in" cx="74.5" cy="30" rx="5" ry="5.5" />
            </g>

            <!-- Tête large et ronde -->
            <ellipse class="head" cx="50" cy="55" rx="36" ry="33" fill={`url(#${id}-head)`} />

            <!-- Museau crème (large, signature loutre) + chin -->
            <path
                class="muzzle"
                d="M50 48
                   C72 48 82 60 82 70
                   C82 83 67 90 50 90
                   C33 90 18 83 18 70
                   C18 60 28 48 50 48 Z"
            />
            <!-- Joues roses -->
            <circle class="cheek cheek-l" cx="28" cy="66" r="6.5" />
            <circle class="cheek cheek-r" cx="72" cy="66" r="6.5" />

            <!-- Moustaches -->
            <g class="whiskers wk-l">
                <line x1="34" y1="64" x2="10" y2="59" />
                <line x1="34" y1="67" x2="8" y2="67" />
                <line x1="34" y1="70" x2="10" y2="75" />
            </g>
            <g class="whiskers wk-r">
                <line x1="66" y1="64" x2="90" y2="59" />
                <line x1="66" y1="67" x2="92" y2="67" />
                <line x1="66" y1="70" x2="90" y2="75" />
            </g>

            <!-- Bloc facial (yeux + sourcils + nez), légère parallaxe vers la souris -->
            <g class="ot-face" style="transform: translate({faceTx}px, {faceTy}px)">
                <!-- Sourcils (expression par état) -->
                <path class="brow brow-l" d="M31 38 Q39 34 46 37" />
                <path class="brow brow-r" d="M54 37 Q61 34 69 38" />

                <!-- Yeux ronds (sclère claire + pupille clippée qui suit la souris) -->
                <g class="eyes">
                    <g class="eye eye-l">
                        <ellipse class="sclera" cx="39" cy="51" rx="7.2" ry="8" />
                        <g class="pupil-wrap" clip-path={`url(#${id}-eyeL)`}>
                            <g class="gaze" style="transform: translate({pupilTx}px, {pupilTy}px)">
                                <circle class="pupil" cx="39" cy="51.5" r="4.6" />
                                <circle class="glint" cx="37" cy="49.2" r="1.7" />
                                <circle class="glint glint-sm" cx="41" cy="53" r="0.9" />
                            </g>
                        </g>
                    </g>
                    <g class="eye eye-r">
                        <ellipse class="sclera" cx="61" cy="51" rx="7.2" ry="8" />
                        <g class="pupil-wrap" clip-path={`url(#${id}-eyeR)`}>
                            <g class="gaze" style="transform: translate({pupilTx}px, {pupilTy}px)">
                                <circle class="pupil" cx="61" cy="51.5" r="4.6" />
                                <circle class="glint" cx="59" cy="49.2" r="1.7" />
                                <circle class="glint glint-sm" cx="63" cy="53" r="0.9" />
                            </g>
                        </g>
                    </g>
                </g>
                <!-- Yeux « heureux » : arcs ^^ (state happy) -->
                <path class="eye-happy" d="M31 53 Q39 45 47 53" />
                <path class="eye-happy" d="M53 53 Q61 45 69 53" />

                <!-- Nez (gros, rond, signature loutre) -->
                <path class="nose" d="M43 60 Q50 56 57 60 Q58 66 50 70 Q42 66 43 60 Z" />
                <ellipse class="nose-shine" cx="47.5" cy="61.5" rx="1.6" ry="1.1" />
            </g>

            <!-- Bouche normale (ω) -->
            <path class="mouth m-omega" d="M50 70 Q46 74 42 71" />
            <path class="mouth m-omega" d="M50 70 Q54 74 58 71" />
            <!-- Grand sourire (state happy) -->
            <path class="mouth m-smile" d="M40 70 Q50 80 60 70" />
            <!-- Bouche ouverte (speaking / surprised) -->
            <ellipse class="mouth-open" cx="50" cy="74" rx="4.2" ry="3" />
        </g>
    </svg>

    {#if faceState === 'thinking'}
        <span class="glyph think">?</span>
    {:else if faceState === 'writing'}
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
    .ear-out { fill: oklch(0.5 0.08 50); }
    .ear-in { fill: oklch(0.68 0.08 33); }
    .muzzle { fill: oklch(0.95 0.022 80); }
    .cheek { fill: oklch(0.8 0.1 28); opacity: 0.38; transition: opacity 0.3s ease; }
    .sclera { fill: oklch(0.99 0.005 90); }
    .pupil { fill: oklch(0.21 0.03 55); }
    .glint { fill: oklch(1 0 0); opacity: 0.95; }
    .glint-sm { opacity: 0.6; }
    .nose { fill: oklch(0.3 0.035 40); }
    .nose-shine { fill: oklch(1 0 0 / 0.5); }
    .mouth {
        fill: none;
        stroke: oklch(0.3 0.03 45);
        stroke-width: 2.2;
        stroke-linecap: round;
    }
    .m-smile { display: none; }
    .mouth-open { fill: oklch(0.33 0.05 26); opacity: 0; }
    .eye-happy {
        fill: none;
        stroke: oklch(0.21 0.03 55);
        stroke-width: 3;
        stroke-linecap: round;
        opacity: 0;
    }
    .brow {
        fill: none;
        stroke: oklch(0.4 0.06 48);
        stroke-width: 2.4;
        stroke-linecap: round;
        transform-box: fill-box;
        transform-origin: center;
        transition: transform 0.28s ease;
    }
    .whiskers line {
        stroke: oklch(0.7 0.02 70);
        stroke-width: 1.2;
        stroke-linecap: round;
        opacity: 0.5;
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

    /* Pupilles : le groupe .gaze suit la souris (translation inline, transition
       douce, bornée + clippée). Quand on NE suit PAS, .pupil-wrap fait une petite
       balade idle ; le suivi désactive cette balade pour éviter le conflit. */
    .gaze { transform-box: fill-box; transform-origin: center; transition: transform 0.16s ease-out; }
    .pupil-wrap { transform-box: fill-box; transform-origin: center; }
    .otter.idle:not(.tracking) .pupil-wrap { animation: ot-dart 7s ease-in-out infinite; }

    /* thinking : tête penchée + regard en l'air + un sourcil relevé */
    .otter.thinking .ot-body { animation: ot-tilt 2.6s ease-in-out infinite; }
    .otter.thinking:not(.tracking) .pupil-wrap { transform: translate(0px, -2px); }
    .otter.thinking .eye { animation-duration: 3.6s; }
    .otter.thinking .brow-l { transform: translateY(-2px) rotate(-8deg); }
    .otter.thinking .brow-r { transform: translateY(1px) rotate(4deg); }

    /* writing : regard concentré + sourcils froncés */
    .otter.writing:not(.tracking) .pupil-wrap { animation: ot-scribble 0.6s ease-in-out infinite; }
    .otter.writing .brow-l { transform: translateY(1.5px) rotate(7deg); }
    .otter.writing .brow-r { transform: translateY(1.5px) rotate(-7deg); }

    /* speaking : museau qui parle */
    .otter.speaking .mouth-open {
        opacity: 1;
        transform-box: fill-box;
        transform-origin: center;
        animation: ot-talk 0.34s ease-in-out infinite;
    }
    .otter.speaking .m-omega { opacity: 0.35; }

    /* happy : yeux en arcs + grand sourire + rebond + joues roses */
    .otter.happy .eye { opacity: 0; }
    .otter.happy .eye-happy { opacity: 1; }
    .otter.happy .brow { opacity: 0; }
    .otter.happy .m-omega { display: none; }
    .otter.happy .m-smile { display: block; }
    .otter.happy .cheek { opacity: 0.72; }
    .otter.happy .ot-body { animation: ot-hop 0.7s ease-in-out infinite; }

    /* surprised : yeux écarquillés + sourcils hauts + museau « o » + pop */
    .otter.surprised .eye { transform: scale(1.16); animation: none; }
    .otter.surprised .brow { transform: translateY(-3px); }
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
    /* Balade idle bornée (max ~2.4u) → reste dans la sclère, et clippée de toute façon */
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
        .ot-body, .eye, .pupil-wrap, .gaze, .ear, .whiskers, .mouth-open, .glyph, .brow {
            animation: none !important;
            transition: none !important;
        }
    }
</style>
