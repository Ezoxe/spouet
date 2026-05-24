<script lang="ts">
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { User, Bot, Wrench, Cog, Info, Copy, Pencil, RefreshCw, Check, X } from 'lucide-svelte';
    import type { MessageOut } from '$lib/api';
    import MessageDetails from './MessageDetails.svelte';
    import AiOrb from './AiOrb.svelte';
    import ThinkingIndicator from './ThinkingIndicator.svelte';
    import Markdown from './Markdown.svelte';
    import { toast } from '$lib/toast.svelte';

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
        canEdit?: boolean;
        canRegenerate?: boolean;
        thinkingLabel?: string;
        thinkingDetail?: string | null;
        onedit?: (msgId: string, newText: string) => void;
        onregenerate?: () => void;
    }
    let {
        message,
        streaming = false,
        canEdit = false,
        canRegenerate = false,
        thinkingLabel,
        thinkingDetail,
        onedit,
        onregenerate
    }: Props = $props();

    let detailsOpen = $state(false);
    let editing = $state(false);
    let editText = $state('');

    function startEdit() {
        editText = message.content;
        editing = true;
    }
    function cancelEdit() {
        editing = false;
        editText = '';
    }
    function commitEdit() {
        const t = editText.trim();
        if (!t || !('id' in message) || !message.id || !onedit) return;
        onedit(message.id, t);
        editing = false;
    }
    async function copyContent() {
        try {
            await navigator.clipboard.writeText(message.content);
            toast.success('Copié');
        } catch {
            toast.error('Copie impossible');
        }
    }

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

<div class="group flex flex-col gap-1 {meta.align}" in:fly={{ y: 8, duration: 220, easing: quintOut }}>
    <div class="flex items-center gap-1.5 text-xs text-neutral-500">
        {#if message.role === 'assistant'}
            <AiOrb size={15} state={streaming ? 'thinking' : 'idle'} />
        {:else}
            <meta.Icon size={12} />
        {/if}
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
    {#if editing}
        <div class="w-full max-w-[85%]">
            <textarea
                bind:value={editText}
                rows="3"
                class="w-full rounded-xl border border-cyan-500/40 bg-[var(--color-bg-1)] px-3 py-2 text-sm
                       focus:border-cyan-500 focus:outline-none"
            ></textarea>
            <div class="mt-1 flex gap-2">
                <button
                    type="button"
                    onclick={commitEdit}
                    class="flex items-center gap-1 rounded-md bg-cyan-600 px-2.5 py-1 text-xs text-white hover:bg-cyan-500"
                >
                    <Check size={12} /> Resoumettre
                </button>
                <button
                    type="button"
                    onclick={cancelEdit}
                    class="flex items-center gap-1 rounded-md border border-neutral-700 px-2.5 py-1 text-xs hover:bg-neutral-800"
                >
                    <X size={12} /> Annuler
                </button>
            </div>
        </div>
    {:else}
        <div
            class="max-w-[85%] break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed {meta.bubble}"
            class:whitespace-pre-wrap={message.role !== 'assistant'}
        >
            {#if message.role === 'assistant'}
                {#if streaming && !message.content}
                    <ThinkingIndicator label={thinkingLabel} detail={thinkingDetail} />
                {:else}
                    <Markdown content={message.content} />{#if streaming}<span
                            class="stream-caret"
                        ></span>{/if}
                {/if}
            {:else}
                {message.content || (streaming ? '' : '…')}
            {/if}
        </div>

        {#if !streaming && message.content}
            <div class="mt-0.5 flex gap-0.5 text-xs text-neutral-600 opacity-0 transition-opacity duration-200 hover:opacity-100 focus-within:opacity-100 group-hover:opacity-100">
                <button
                    type="button"
                    onclick={copyContent}
                    class="rounded p-1 hover:bg-neutral-800 hover:text-neutral-300"
                    title="Copier"
                    aria-label="Copier le contenu"
                >
                    <Copy size={11} />
                </button>
                {#if canEdit && onedit}
                    <button
                        type="button"
                        onclick={startEdit}
                        class="rounded p-1 hover:bg-neutral-800 hover:text-neutral-300"
                        title="Éditer & resoumettre"
                        aria-label="Éditer ce message"
                    >
                        <Pencil size={11} />
                    </button>
                {/if}
                {#if canRegenerate && onregenerate}
                    <button
                        type="button"
                        onclick={() => onregenerate?.()}
                        class="rounded p-1 hover:bg-neutral-800 hover:text-neutral-300"
                        title="Régénérer la réponse"
                        aria-label="Régénérer"
                    >
                        <RefreshCw size={11} />
                    </button>
                {/if}
            </div>
        {/if}
    {/if}
</div>

{#if canShowDetails}
    <MessageDetails
        message={message as MessageOut}
        bind:open={detailsOpen}
        onclose={() => (detailsOpen = false)}
    />
{/if}

<style>
    /* Curseur de frappe pendant le streaming */
    .stream-caret {
        display: inline-block;
        width: 0.5em;
        height: 1.05em;
        margin-left: 2px;
        transform: translateY(0.18em);
        border-radius: 2px;
        background: var(--color-accent);
        box-shadow: 0 0 8px -1px color-mix(in oklch, var(--color-accent) 70%, transparent);
        animation: blink 1.05s step-end infinite;
    }
</style>
