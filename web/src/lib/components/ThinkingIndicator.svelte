<script lang="ts">
    /**
     * Indicateur de « réflexion » de l'assistant : visage en mode thinking
     * (bulle « ? »), libellé à dégradé balayé, et points qui rebondissent.
     * Affiché avant le premier token ou pendant le chargement d'un modèle.
     */
    import AiFace from './AiFace.svelte';

    interface Props {
        label?: string;
        detail?: string | null;
    }
    let { label = 'Réflexion', detail = null }: Props = $props();
</script>

<div class="ti">
    <AiFace size={26} state="thinking" />
    <span class="ti-body">
        <span class="ti-line">
            <span class="ti-text ai-shimmer-text">{label}</span>
            <span class="ti-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        </span>
        {#if detail}
            <span class="ti-detail">{detail}</span>
        {/if}
    </span>
</div>

<style>
    .ti {
        display: inline-flex;
        align-items: center;
        gap: 0.6rem;
    }
    .ti-body {
        display: flex;
        flex-direction: column;
        gap: 0.05rem;
    }
    .ti-line {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
    }
    .ti-text {
        font-size: 0.85rem;
        font-weight: 550;
        letter-spacing: 0.01em;
    }
    .ti-detail {
        font-size: 0.7rem;
        color: var(--color-text-subtle);
    }
    .ti-dots {
        display: inline-flex;
        align-items: center;
        gap: 3px;
    }
    .ti-dots i {
        width: 4px;
        height: 4px;
        border-radius: 9999px;
        background: var(--color-accent);
        animation: typing-bounce 1.3s ease-in-out infinite;
    }
    .ti-dots i:nth-child(2) {
        animation-delay: 0.18s;
    }
    .ti-dots i:nth-child(3) {
        animation-delay: 0.36s;
    }
</style>
