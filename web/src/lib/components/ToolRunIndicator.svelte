<script lang="ts">
    /**
     * Indicateur « live » d'exécution d'un outil — affiché entre l'instant où le
     * modèle déclenche un tool_call et l'arrivée du résultat (event `tool_result`).
     * Comble le trou visuel pendant que le conteneur Docker / le built-in tourne :
     * engrenage qui tourne, balayage lumineux, chrono, points animés.
     *
     * Le rendu du résultat (CommandCard) prend le relais une fois l'outil terminé.
     */
    import { onMount } from 'svelte';
    import { scale } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { Cog, Wrench } from 'lucide-svelte';

    interface Props {
        name: string;
        summary?: string;
    }
    let { name, summary = '' }: Props = $props();

    // Chrono local (dixièmes de seconde) — donne une sensation de progression.
    let elapsed = $state(0);
    onMount(() => {
        const t0 = Date.now();
        const iv = setInterval(() => (elapsed = (Date.now() - t0) / 1000), 100);
        return () => clearInterval(iv);
    });
</script>

<div class="trun" in:scale={{ start: 0.95, duration: 220, easing: quintOut }}>
    <span class="trun-ico">
        <Cog size={15} class="trun-cog" />
    </span>
    <span class="trun-body">
        <span class="trun-line">
            <span class="trun-label">
                <Wrench size={11} />
                <span class="trun-name">{name}</span>
            </span>
            <span class="trun-state">
                en cours<span class="trun-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            </span>
            <span class="trun-time">{elapsed.toFixed(1)}s</span>
        </span>
        {#if summary}<span class="trun-args">{summary}</span>{/if}
    </span>
    <span class="trun-scan" aria-hidden="true"></span>
</div>

<style>
    .trun {
        position: relative;
        display: flex;
        align-items: center;
        gap: 0.6rem;
        width: 100%;
        padding: 0.55rem 0.75rem;
        border-radius: var(--radius-md);
        border: 1px solid color-mix(in oklch, var(--color-accent) 32%, transparent);
        background:
            linear-gradient(
                90deg,
                color-mix(in oklch, var(--color-accent) 9%, transparent),
                transparent 60%
            ),
            color-mix(in oklch, var(--color-bg-0) 80%, oklch(0 0 0 / 0.12));
        overflow: hidden;
        box-shadow: 0 0 0 1px color-mix(in oklch, var(--color-accent) 14%, transparent),
            0 10px 28px -16px color-mix(in oklch, var(--color-accent) 50%, transparent);
    }
    :global(:root:not([data-theme='dark'])) .trun {
        background:
            linear-gradient(90deg, var(--light-cyan-bg, oklch(0.95 0.035 230)), transparent 60%),
            var(--light-surface-1, oklch(0.975 0.004 240));
    }

    /* Engrenage qui tourne dans une pastille lumineuse */
    .trun-ico {
        position: relative;
        display: grid;
        place-items: center;
        flex: none;
        width: 1.85rem;
        height: 1.85rem;
        border-radius: 999px;
        color: var(--color-accent);
        background: color-mix(in oklch, var(--color-accent) 16%, transparent);
        box-shadow: 0 0 0 1px color-mix(in oklch, var(--color-accent) 30%, transparent);
    }
    .trun-ico::after {
        content: '';
        position: absolute;
        inset: -3px;
        border-radius: 999px;
        border: 1.5px solid transparent;
        border-top-color: color-mix(in oklch, var(--color-accent) 70%, transparent);
        animation: trun-orbit 1.1s linear infinite;
    }
    :global(.trun-cog) {
        animation: trun-spin 2.6s linear infinite;
    }

    .trun-body {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        min-width: 0;
        flex: 1;
    }
    .trun-line {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .trun-label {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        color: var(--color-text-muted);
    }
    .trun-name {
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-weight: 600;
        color: var(--color-text);
    }
    .trun-state {
        display: inline-flex;
        align-items: center;
        gap: 0.1rem;
        font-size: 0.72rem;
        color: var(--color-accent);
    }
    .trun-time {
        margin-left: auto;
        font-size: 0.7rem;
        font-variant-numeric: tabular-nums;
        color: var(--color-text-subtle);
    }
    .trun-args {
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        color: var(--color-text-subtle);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .trun-dots {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        margin-left: 2px;
    }
    .trun-dots i {
        width: 3px;
        height: 3px;
        border-radius: 999px;
        background: var(--color-accent);
        animation: typing-bounce 1.3s ease-in-out infinite;
    }
    .trun-dots i:nth-child(2) {
        animation-delay: 0.18s;
    }
    .trun-dots i:nth-child(3) {
        animation-delay: 0.36s;
    }

    /* Balayage lumineux qui traverse la carte → impression d'activité continue */
    .trun-scan {
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(
            105deg,
            transparent 35%,
            color-mix(in oklch, var(--color-accent) 14%, transparent) 50%,
            transparent 65%
        );
        background-size: 220% 100%;
        animation: trun-sweep 1.8s ease-in-out infinite;
    }

    @keyframes trun-spin {
        to {
            transform: rotate(360deg);
        }
    }
    @keyframes trun-orbit {
        to {
            transform: rotate(360deg);
        }
    }
    @keyframes trun-sweep {
        0% {
            background-position: 130% 0;
        }
        100% {
            background-position: -130% 0;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        :global(.trun-cog),
        .trun-ico::after,
        .trun-scan,
        .trun-dots i {
            animation: none !important;
        }
    }
</style>
