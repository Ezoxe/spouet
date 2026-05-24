<script lang="ts">
    /**
     * Orbe « IA » — sphère iridescente animée, identité visuelle de l'assistant.
     * Trois états : repos (respiration lente), réflexion (rotation + halo rapides),
     * parole (pulsation rythmée). Pur CSS, sans dépendance.
     */
    interface Props {
        size?: number;
        state?: 'idle' | 'thinking' | 'speaking';
        class?: string;
    }
    let { size = 28, state = 'idle', class: klass = '' }: Props = $props();
</script>

<span class="orb {state} {klass}" style="--orb-size:{size}px" aria-hidden="true">
    <span class="orb-glow"></span>
    <span class="orb-ring"></span>
    <span class="orb-core"></span>
    <span class="orb-spec"></span>
</span>

<style>
    .orb {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: var(--orb-size);
        height: var(--orb-size);
        flex: none;
    }
    .orb-glow,
    .orb-ring,
    .orb-core,
    .orb-spec {
        position: absolute;
        border-radius: 9999px;
        pointer-events: none;
    }
    /* Halo diffus derrière la sphère */
    .orb-glow {
        inset: -32%;
        background: radial-gradient(
            closest-side,
            color-mix(in oklch, var(--color-accent) 55%, transparent),
            transparent 72%
        );
        filter: blur(6px);
        z-index: 0;
        animation: breathe 4.5s ease-in-out infinite;
    }
    /* Anneau conique iridescent qui tourne */
    .orb-ring {
        inset: 0;
        background: conic-gradient(
            from 0deg,
            oklch(0.72 0.18 210),
            oklch(0.76 0.16 285),
            oklch(0.74 0.15 165),
            oklch(0.78 0.17 320),
            oklch(0.72 0.18 210)
        );
        z-index: 1;
        animation: orb-spin 6.5s linear infinite;
    }
    /* Cœur sphérique (éclairage haut-gauche) */
    .orb-core {
        inset: 13%;
        background:
            radial-gradient(circle at 32% 26%, oklch(0.97 0.04 220 / 0.92), transparent 46%),
            radial-gradient(circle at 68% 78%, oklch(0.5 0.16 255), oklch(0.26 0.1 262));
        box-shadow: inset 0 0 9px oklch(0 0 0 / 0.45);
        z-index: 2;
    }
    /* Reflet spéculaire */
    .orb-spec {
        inset: 13%;
        background: radial-gradient(circle at 34% 25%, oklch(1 0 0 / 0.65), transparent 32%);
        z-index: 3;
    }

    /* — Réflexion : tout s'accélère et s'intensifie — */
    .orb.thinking .orb-ring {
        animation-duration: 1.5s;
    }
    .orb.thinking .orb-glow {
        animation: glow-pulse 1.3s ease-in-out infinite;
        filter: blur(8px);
    }
    .orb.thinking .orb-core {
        animation: breathe 1.6s ease-in-out infinite;
    }

    /* — Parole : pulsation plus vive — */
    .orb.speaking .orb-ring {
        animation-duration: 2.6s;
    }
    .orb.speaking .orb-glow {
        animation: glow-pulse 0.75s ease-in-out infinite;
    }
</style>
