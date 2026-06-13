<script lang="ts">
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { User, Bot, Wrench, Cog, Info, Copy, Pencil, RefreshCw, Check, X, Brain, ChevronDown } from 'lucide-svelte';
    import type { MessageOut } from '$lib/api';
    import MessageDetails from './MessageDetails.svelte';
    import AiFace from './AiFace.svelte';
    import ThinkingIndicator from './ThinkingIndicator.svelte';
    import Markdown from './Markdown.svelte';
    import CommandCard from './CommandCard.svelte';
    import { toast } from '$lib/toast.svelte';
    import { copyText } from '$lib/clipboard';

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
        // copyText : robuste hors contexte sécurisé (app servie en HTTP sur le LAN).
        if (await copyText(message.content)) toast.success('Copié');
        else toast.error('Copie impossible');
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

    // État du visage de l'assistant : réflexion (avant le 1er token), écriture
    // (tokens en cours), repos (réponse figée).
    const faceState = $derived(
        !streaming ? 'idle' : message.content ? 'writing' : 'thinking'
    );

    // Métadonnées d'outil (messages role=tool et tool_calls de l'assistant).
    const cjson = $derived(
        ('content_json' in message ? message.content_json : null) as Record<string, any> | null | undefined
    );
    const toolName = $derived(String(cjson?.tool_name ?? 'outil'));
    const toolCalls = $derived.by(() => {
        const raw = cjson?.tool_calls;
        if (!Array.isArray(raw)) return [] as { name: string; summary: string }[];
        return raw.map((tc: any) => {
            const fn = tc?.function ?? {};
            const args = fn.arguments;
            let summary = '';
            if (args && typeof args === 'object') {
                summary = Object.entries(args)
                    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
                    .join(' ');
            } else if (typeof args === 'string') {
                summary = args;
            }
            return { name: String(fn.name ?? 'outil'), summary: summary.slice(0, 90) };
        });
    });

    // Raisonnement « thinking » du modèle : en direct via message.reasoning
    // (streaming), sinon réhydraté depuis content_json.reasoning (persisté).
    const reasoning = $derived.by(() => {
        const live = ('reasoning' in message ? (message as any).reasoning : null) as string | null | undefined;
        const persisted = typeof cjson?.reasoning === 'string' ? (cjson.reasoning as string) : null;
        return (live || persisted || '').trim();
    });
    let reasoningOpen = $state(false);
    // Auto-déplié pendant que le modèle réfléchit (réponse pas encore arrivée),
    // puis replié une fois la réponse en cours — sauf si l'utilisateur l'ouvre.
    const showReasoning = $derived(reasoningOpen || (streaming && !!reasoning && !message.content));

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
    {#if message.role !== 'tool'}
        <div class="flex items-center gap-1.5 text-xs text-neutral-500">
            {#if message.role === 'assistant'}
                <AiFace size={32} state={faceState} />
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
    {/if}
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
    {:else if message.role === 'tool'}
        <div class="w-full max-w-[85%]">
            <CommandCard {toolName} content={message.content} />
        </div>
    {:else}
        <div
            class="max-w-[85%] break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed {meta.bubble}"
            class:whitespace-pre-wrap={message.role !== 'assistant'}
        >
            {#if message.role === 'assistant'}
                {#if reasoning}
                    <div class="mb-2">
                        <button
                            type="button"
                            onclick={() => (reasoningOpen = !reasoningOpen)}
                            class="flex items-center gap-1.5 text-xs text-neutral-500 transition-colors hover:text-neutral-300"
                        >
                            <Brain size={12} />
                            <span>Réflexion</span>
                            <ChevronDown size={12} class="transition-transform {showReasoning ? 'rotate-180' : ''}" />
                        </button>
                        {#if showReasoning}
                            <div class="reasoning-body mt-1 rounded-lg border border-[var(--color-border-subtle)] bg-black/20 px-3 py-2 text-xs leading-relaxed text-neutral-400">
                                <Markdown content={reasoning} streaming={streaming && !message.content} />{#if streaming && !message.content}<span class="stream-caret"></span>{/if}
                            </div>
                        {/if}
                    </div>
                {/if}
                {#if streaming && !message.content && !reasoning}
                    <ThinkingIndicator label={thinkingLabel} detail={thinkingDetail} />
                {:else}
                    {#if message.content}
                        <Markdown content={message.content} {streaming} />{#if streaming}<span
                                class="stream-caret"
                            ></span>{/if}
                    {/if}
                    {#if toolCalls.length}
                        <div class="toolcalls" class:mt-2={!!message.content}>
                            {#each toolCalls as tc}
                                <span class="toolcall-chip">
                                    <Wrench size={11} />
                                    <span class="tc-name">{tc.name}</span>
                                    {#if tc.summary}<span class="tc-args">{tc.summary}</span>{/if}
                                </span>
                            {/each}
                        </div>
                    {/if}
                {/if}
            {:else}
                {message.content || (streaming ? '' : '…')}
            {/if}
        </div>

        {#if !streaming && message.content && message.role !== 'tool'}
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
    /* Chips « appel d'outil » sous une réponse assistant */
    .toolcalls {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
    }
    .toolcall-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        max-width: 100%;
        padding: 0.12rem 0.5rem;
        border-radius: 999px;
        border: 1px solid color-mix(in oklch, var(--color-accent) 30%, transparent);
        background: color-mix(in oklch, var(--color-accent) 12%, transparent);
        color: var(--color-text);
        font-size: 0.72rem;
        animation: chip-in 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }
    .toolcall-chip:nth-child(2) {
        animation-delay: 0.07s;
    }
    .toolcall-chip:nth-child(3) {
        animation-delay: 0.14s;
    }
    .toolcall-chip:nth-child(4) {
        animation-delay: 0.21s;
    }
    @keyframes chip-in {
        from {
            opacity: 0;
            transform: translateY(4px) scale(0.96);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }
    .tc-name {
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        font-weight: 600;
    }
    .tc-args {
        color: var(--color-text-muted);
        font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', monospace;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

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
