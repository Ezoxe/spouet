<script lang="ts">
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { User, Bot, Wrench, Cog, Info } from 'lucide-svelte';
    import type { MessageOut } from '$lib/api';
    import MessageDetails from './MessageDetails.svelte';

    interface Props {
        message:
            | MessageOut
            | {
                  id?: string;
                  role: string;
                  content: string;
                  model_used?: string | null;
                  latency_ms?: number | null;
                  tokens_out?: number | null;
              };
        streaming?: boolean;
    }
    let { message, streaming = false }: Props = $props();

    let detailsOpen = $state(false);

    // L'icône Info n'a de sens que si on a au moins quelques métriques
    // serveur (id + au moins un compteur de tokens ou un timing).
    const canShowDetails = $derived.by(() => {
        if (!('id' in message) || !message.id) return false;
        const m = message as MessageOut;
        return (
            m.tokens_in != null ||
            m.tokens_out != null ||
            m.latency_ms != null ||
            m.ttft_ms != null ||
            m.finish_reason != null
        );
    });

    const meta = $derived.by(() => {
        switch (message.role) {
            case 'user':
                return {
                    Icon: User,
                    label: 'Vous',
                    align: 'items-end',
                    bubble:
                        'bg-gradient-to-br from-cyan-600 to-cyan-700 text-white shadow-[0_8px_28px_-12px_oklch(0.55_0.18_210/0.6)]'
                };
            case 'assistant':
                return {
                    Icon: Bot,
                    label: ('model_used' in message && message.model_used) || 'Assistant',
                    align: 'items-start',
                    bubble: 'glass text-neutral-100'
                };
            case 'tool':
                return {
                    Icon: Wrench,
                    label: 'Tool',
                    align: 'items-start',
                    bubble:
                        'border border-amber-900/40 bg-amber-950/30 text-amber-100 font-mono text-xs'
                };
            case 'system':
                return {
                    Icon: Cog,
                    label: 'Système',
                    align: 'items-start',
                    bubble: 'border border-neutral-800 bg-neutral-900/40 text-neutral-400 italic'
                };
            default:
                return {
                    Icon: Bot,
                    label: message.role,
                    align: 'items-start',
                    bubble: 'bg-neutral-800'
                };
        }
    });
</script>

<div class="flex flex-col gap-1 {meta.align}" in:fly={{ y: 8, duration: 220, easing: quintOut }}>
    <div class="flex items-center gap-1.5 text-xs text-neutral-500">
        <meta.Icon size={12} />
        <span>{meta.label}</span>
        {#if 'latency_ms' in message && message.latency_ms != null}
            <span class="text-neutral-600">· {message.latency_ms}ms</span>
        {/if}
        {#if 'tokens_out' in message && message.tokens_out != null}
            <span class="text-neutral-600">· {message.tokens_out} tok</span>
        {/if}
        {#if canShowDetails}
            <button
                type="button"
                onclick={() => (detailsOpen = true)}
                class="ml-0.5 rounded p-0.5 text-neutral-600 transition hover:bg-neutral-800 hover:text-neutral-300"
                title="Détails complets"
                aria-label="Afficher les détails du message"
            >
                <Info size={11} />
            </button>
        {/if}
    </div>
    <div
        class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
               whitespace-pre-wrap break-words {meta.bubble}"
        class:cursor-blink={streaming}
    >
        {message.content || (streaming ? '' : '…')}
    </div>
</div>

{#if canShowDetails}
    <MessageDetails
        message={message as MessageOut}
        bind:open={detailsOpen}
        onclose={() => (detailsOpen = false)}
    />
{/if}
