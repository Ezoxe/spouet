<script lang="ts">
    /**
     * Rendu lisible d'un message `role: tool` (résultat d'un appel d'outil).
     * - Forme « commande » (net-check, tout tool exposant command/output) →
     *   box type terminal : commande, sortie, résumé.
     * - Forme « recherche » (web_search) → requête + liste de résultats cliquables.
     * - Sinon → JSON formaté repliable.
     * Remplace l'ancien dump JSON brut ambre.
     */
    import {
        Terminal,
        ChevronDown,
        CircleCheck,
        CircleAlert,
        Ban,
        Clock,
        Search,
        Copy,
        Check
    } from 'lucide-svelte';
    import { copyText } from '$lib/clipboard';

    interface Props {
        toolName: string;
        content: string;
    }
    let { toolName, content }: Props = $props();

    let copied = $state(false);
    async function copy() {
        if (await copyText(content)) {
            copied = true;
            setTimeout(() => (copied = false), 1500);
        }
    }

    type Json = Record<string, unknown>;

    const parsed = $derived.by<Json | null>(() => {
        try {
            const v = JSON.parse(content);
            return v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;
        } catch {
            return null;
        }
    });

    const status = $derived(String((parsed?.status as string) ?? 'ok'));
    const isCommand = $derived(
        !!parsed && (typeof parsed.command === 'string' || typeof parsed.output === 'string')
    );
    const isSearch = $derived(
        !!parsed && Array.isArray(parsed.results) && typeof parsed.query === 'string'
    );

    type Result = { title?: string; url?: string; snippet?: string };
    const results = $derived.by<Result[]>(() =>
        isSearch ? ((parsed!.results as Result[]) ?? []) : []
    );

    let open = $state(true);

    const sm = $derived.by(() => {
        switch (status) {
            case 'ok':
            case 'shown':
            case 'saved':
                return { Icon: CircleCheck, cls: 'st-ok', label: 'ok' };
            case 'denied':
            case 'rejected':
                return { Icon: Ban, cls: 'st-warn', label: 'refusé' };
            case 'timeout':
                return { Icon: Clock, cls: 'st-warn', label: 'délai dépassé' };
            case 'empty':
                return { Icon: CircleAlert, cls: 'st-warn', label: 'vide' };
            case 'error':
            case 'invalid':
            case 'app_not_found':
            case 'unknown_macro':
                return { Icon: CircleAlert, cls: 'st-err', label: 'erreur' };
            default:
                return { Icon: CircleCheck, cls: 'st-ok', label: status };
        }
    });

    const prettyJson = $derived(parsed ? JSON.stringify(parsed, null, 2) : content);
    const HeadIcon = $derived(isSearch ? Search : Terminal);
</script>

<div class="cmd">
    <div class="cmd-head">
        <button type="button" class="cmd-toggle" onclick={() => (open = !open)} aria-expanded={open}>
            <HeadIcon size={13} />
            <span class="cmd-name">{toolName}</span>
            <span class="cmd-status {sm.cls}"><sm.Icon size={11} class="cmd-st-ico" /> {sm.label}</span>
            <ChevronDown size={13} class="cmd-chev {open ? 'open' : ''}" />
        </button>
        <button
            type="button"
            class="cmd-copy {copied ? 'copied' : ''}"
            onclick={copy}
            aria-label="Copier le résultat de l'outil"
            title="Copier le résultat"
        >
            {#if copied}<Check size={12} />{:else}<Copy size={12} />{/if}
        </button>
    </div>

    {#if open}
        {#if isCommand}
            <div class="cmd-body">
                {#if parsed?.command}
                    <div class="cmd-line"><span class="cmd-prompt">$</span><span>{parsed.command}</span></div>
                {/if}
                {#if parsed?.output}
                    <pre class="cmd-out">{parsed.output}</pre>
                {/if}
                {#if parsed?.error}
                    <pre class="cmd-out cmd-err">{parsed.error}</pre>
                {/if}
                {#if parsed?.summary}
                    <div class="cmd-summary">{parsed.summary}</div>
                {/if}
                {#if parsed?.note}
                    <div class="cmd-note">{parsed.note}</div>
                {/if}
            </div>
        {:else if isSearch}
            <div class="cmd-body">
                <div class="cmd-query">« {parsed?.query} »</div>
                {#if parsed?.answer}
                    <div class="cmd-summary">{parsed.answer}</div>
                {/if}
                <ul class="cmd-results">
                    {#each results.slice(0, 6) as r}
                        <li>
                            {#if r.url}
                                <a href={r.url} target="_blank" rel="noopener noreferrer" class="cmd-rtitle"
                                    >{r.title || r.url}</a
                                >
                            {:else}
                                <span class="cmd-rtitle">{r.title}</span>
                            {/if}
                            {#if r.snippet}<span class="cmd-rsnip">{r.snippet}</span>{/if}
                        </li>
                    {:else}
                        <li class="cmd-rsnip">Aucun résultat.</li>
                    {/each}
                </ul>
                {#if parsed?.note}<div class="cmd-note">{parsed.note}</div>{/if}
            </div>
        {:else}
            <pre class="cmd-json">{prettyJson}</pre>
        {/if}
    {/if}
</div>

<style>
    .cmd {
        width: 100%;
        border-radius: var(--radius-md);
        border: 1px solid var(--color-border);
        background: color-mix(in oklch, var(--color-bg-0) 82%, oklch(0 0 0 / 0.18));
        overflow: hidden;
        font-size: 0.8rem;
        animation: cmd-in 0.4s cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }
    :global(:root:not([data-theme='dark'])) .cmd {
        background: var(--light-surface-1, oklch(0.965 0.004 240));
    }
    @keyframes cmd-in {
        from {
            opacity: 0;
            transform: translateY(8px) scale(0.99);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }
    .cmd-head {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        width: 100%;
        background: color-mix(in oklch, var(--color-bg-2) 55%, transparent);
        border-bottom: 1px solid var(--color-border-subtle);
    }
    .cmd-toggle {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex: 1;
        min-width: 0;
        padding: 0.4rem 0.6rem;
        color: var(--color-text-muted);
        cursor: pointer;
        text-align: left;
    }
    .cmd-copy {
        display: grid;
        place-items: center;
        flex: none;
        width: 1.75rem;
        height: 1.75rem;
        margin-right: 0.3rem;
        border-radius: 6px;
        color: var(--color-text-subtle);
        cursor: pointer;
        opacity: 0;
        transition:
            opacity 0.15s ease,
            background 0.15s ease,
            color 0.15s ease;
    }
    .cmd:hover .cmd-copy,
    .cmd-copy:focus-visible {
        opacity: 1;
    }
    .cmd-copy:hover {
        background: var(--color-bg-3);
        color: var(--color-text);
    }
    .cmd-copy.copied {
        color: var(--color-success);
        opacity: 1;
    }
    :global(.cmd-st-ico) {
        animation: cmd-st-pop 0.45s 0.12s backwards cubic-bezier(0.2, 0.9, 0.3, 1.3);
    }
    @keyframes cmd-st-pop {
        0% {
            transform: scale(0.2);
            opacity: 0;
        }
        65% {
            transform: scale(1.25);
            opacity: 1;
        }
        100% {
            transform: scale(1);
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .cmd,
        :global(.cmd-st-ico) {
            animation: none !important;
        }
    }
    .cmd-name {
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-weight: 600;
        color: var(--color-text);
    }
    .cmd-status {
        display: inline-flex;
        align-items: center;
        gap: 0.2rem;
        font-size: 0.68rem;
        padding: 0.05rem 0.4rem;
        border-radius: 999px;
    }
    .st-ok {
        color: var(--color-success);
        background: color-mix(in oklch, var(--color-success) 14%, transparent);
    }
    .st-warn {
        color: var(--color-warning);
        background: color-mix(in oklch, var(--color-warning) 14%, transparent);
    }
    .st-err {
        color: var(--color-danger);
        background: color-mix(in oklch, var(--color-danger) 14%, transparent);
    }
    .cmd-chev {
        margin-left: auto;
        transition: transform 0.15s ease;
    }
    .cmd-chev.open {
        transform: rotate(180deg);
    }
    .cmd-body {
        padding: 0.55rem 0.7rem;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }
    .cmd-line {
        display: flex;
        gap: 0.45rem;
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        color: var(--color-text);
        overflow-wrap: anywhere;
    }
    .cmd-prompt {
        color: var(--color-accent);
        font-weight: 700;
        user-select: none;
    }
    .cmd-out {
        margin: 0;
        padding: 0.5rem 0.6rem;
        border-radius: var(--radius-sm);
        background: color-mix(in oklch, var(--color-bg-0) 70%, oklch(0 0 0 / 0.25));
        color: var(--color-text-muted);
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-size: 0.76rem;
        line-height: 1.5;
        white-space: pre-wrap;
        overflow-x: auto;
        max-height: 18rem;
    }
    :global(:root:not([data-theme='dark'])) .cmd-out {
        background: color-mix(in oklch, oklch(0.2 0.01 260) 6%, transparent);
    }
    .cmd-err {
        color: var(--color-danger);
    }
    .cmd-summary {
        font-weight: 600;
        color: var(--color-text);
    }
    .cmd-note,
    .cmd-query {
        font-size: 0.74rem;
        color: var(--color-text-subtle);
    }
    .cmd-results {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .cmd-results li {
        display: flex;
        flex-direction: column;
        gap: 0.1rem;
    }
    .cmd-rtitle {
        color: var(--color-accent);
        font-weight: 600;
        text-decoration: none;
        overflow-wrap: anywhere;
    }
    .cmd-rtitle:hover {
        text-decoration: underline;
    }
    .cmd-rsnip {
        color: var(--color-text-muted);
        font-size: 0.74rem;
        line-height: 1.45;
    }
    .cmd-json {
        margin: 0;
        padding: 0.6rem 0.7rem;
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-size: 0.74rem;
        color: var(--color-text-muted);
        white-space: pre-wrap;
        overflow-x: auto;
        max-height: 18rem;
    }
</style>
