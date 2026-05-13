<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { X, Copy, Check } from 'lucide-svelte';
    import type { MessageOut } from '$lib/api';

    interface Props {
        message: MessageOut;
        open: boolean;
        onclose: () => void;
    }

    let { message, open = $bindable(), onclose }: Props = $props();

    let copied = $state(false);

    const tokensTotal = $derived(
        (message.tokens_in ?? 0) + (message.tokens_out ?? 0) || null
    );
    const tps = $derived.by(() => {
        if (!message.tokens_out || !message.latency_ms || message.latency_ms <= 0) return null;
        // Si on a le ttft, retire la latence d'attente du premier token pour
        // refléter le vrai débit de génération (pas le débit moyen perçu).
        const genMs = message.ttft_ms != null
            ? message.latency_ms - message.ttft_ms
            : message.latency_ms;
        if (genMs <= 0) return null;
        return (message.tokens_out / genMs) * 1000;
    });

    const createdAtFmt = $derived(
        message.created_at ? new Date(message.created_at).toLocaleString('fr-FR') : '—'
    );

    const toolCalls = $derived.by(() => {
        const tc = (message.content_json as { tool_calls?: unknown } | undefined)?.tool_calls;
        return Array.isArray(tc) ? (tc as Array<Record<string, unknown>>) : null;
    });

    async function copyJson(): Promise<void> {
        const payload = {
            id: message.id,
            role: message.role,
            model_used: message.model_used,
            tokens_in: message.tokens_in,
            tokens_out: message.tokens_out,
            ttft_ms: message.ttft_ms,
            latency_ms: message.latency_ms,
            finish_reason: message.finish_reason,
            content_json: message.content_json,
            created_at: message.created_at
        };
        try {
            await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
            copied = true;
            setTimeout(() => (copied = false), 1500);
        } catch {
            /* clipboard refusé */
        }
    }

    function onBackdrop(e: MouseEvent): void {
        if (e.target === e.currentTarget) onclose();
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.preventDefault();
            onclose();
        }
    }
</script>

<svelte:window on:keydown={onKey} />

{#if open}
    <div
        in:fade={{ duration: 140 }}
        out:fade={{ duration: 100 }}
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        onclick={onBackdrop}
        role="dialog"
        aria-modal="true"
        tabindex="-1"
    >
        <div
            in:scale={{ duration: 200, start: 0.96 }}
            class="relative w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-950 shadow-2xl"
        >
            <header class="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
                <h2 class="text-sm font-medium text-neutral-200">Détails du message</h2>
                <div class="flex items-center gap-1">
                    <button
                        type="button"
                        onclick={copyJson}
                        class="rounded p-1.5 text-neutral-500 transition hover:bg-neutral-800 hover:text-neutral-200"
                        title="Copier en JSON"
                        aria-label="Copier les détails"
                    >
                        {#if copied}
                            <Check size={14} class="text-emerald-400" />
                        {:else}
                            <Copy size={14} />
                        {/if}
                    </button>
                    <button
                        type="button"
                        onclick={onclose}
                        class="rounded p-1.5 text-neutral-500 transition hover:bg-neutral-800 hover:text-neutral-200"
                        aria-label="Fermer"
                    >
                        <X size={14} />
                    </button>
                </div>
            </header>

            <div class="space-y-3 px-4 py-3 text-xs">
                <section>
                    <h3 class="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-neutral-500">
                        Identité
                    </h3>
                    <dl class="grid grid-cols-[100px_1fr] gap-y-1 text-neutral-300">
                        <dt class="text-neutral-500">Rôle</dt>
                        <dd class="font-mono">{message.role}</dd>
                        <dt class="text-neutral-500">ID</dt>
                        <dd class="truncate font-mono text-[10px] text-neutral-400" title={message.id}>
                            {message.id}
                        </dd>
                        <dt class="text-neutral-500">Modèle</dt>
                        <dd class="truncate font-mono" title={message.model_used ?? ''}>
                            {message.model_used ?? '—'}
                        </dd>
                        <dt class="text-neutral-500">Créé</dt>
                        <dd>{createdAtFmt}</dd>
                    </dl>
                </section>

                <section>
                    <h3 class="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-neutral-500">
                        Tokens
                    </h3>
                    <dl class="grid grid-cols-[100px_1fr] gap-y-1 text-neutral-300">
                        <dt class="text-neutral-500">Prompt (in)</dt>
                        <dd class="font-mono tabular-nums">{message.tokens_in?.toLocaleString() ?? '—'}</dd>
                        <dt class="text-neutral-500">Réponse (out)</dt>
                        <dd class="font-mono tabular-nums">{message.tokens_out?.toLocaleString() ?? '—'}</dd>
                        <dt class="text-neutral-500">Total</dt>
                        <dd class="font-mono tabular-nums">{tokensTotal?.toLocaleString() ?? '—'}</dd>
                    </dl>
                </section>

                <section>
                    <h3 class="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-neutral-500">
                        Performance
                    </h3>
                    <dl class="grid grid-cols-[100px_1fr] gap-y-1 text-neutral-300">
                        <dt class="text-neutral-500" title="Time to first token">
                            TTFT
                        </dt>
                        <dd class="font-mono tabular-nums">
                            {message.ttft_ms != null ? `${message.ttft_ms} ms` : '—'}
                        </dd>
                        <dt class="text-neutral-500">Durée totale</dt>
                        <dd class="font-mono tabular-nums">
                            {message.latency_ms != null ? `${message.latency_ms} ms` : '—'}
                        </dd>
                        <dt class="text-neutral-500">Débit</dt>
                        <dd class="font-mono tabular-nums">
                            {tps != null ? `${tps.toFixed(1)} tok/s` : '—'}
                        </dd>
                        <dt class="text-neutral-500">Finish</dt>
                        <dd class="font-mono">{message.finish_reason ?? '—'}</dd>
                    </dl>
                </section>

                {#if toolCalls && toolCalls.length > 0}
                    <section>
                        <h3 class="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-neutral-500">
                            Tool calls ({toolCalls.length})
                        </h3>
                        <pre class="max-h-40 overflow-auto rounded border border-neutral-800 bg-neutral-900/60 p-2 font-mono text-[10px] leading-snug text-neutral-300">{JSON.stringify(
                                toolCalls,
                                null,
                                2
                            )}</pre>
                    </section>
                {/if}
            </div>
        </div>
    </div>
{/if}
