<script lang="ts">
    import { onMount, tick, untrack } from 'svelte';
    import { page } from '$app/stores';
    import { fade } from 'svelte/transition';
    import {
        conversations,
        nodes as nodesApi,
        tools as toolsApi,
        type ConversationOut,
        type MessageOut,
        type ModelAgg
    } from '$lib/api';
    import MessageBubble from '$lib/components/MessageBubble.svelte';
    import Composer from '$lib/components/Composer.svelte';
    import EmptyState from '$lib/components/EmptyState.svelte';
    import VoiceMode from '$lib/components/VoiceMode.svelte';
    import { createVoiceBus } from '$lib/voice';
    import { toast } from '$lib/toast.svelte';
    import { Sparkles, MessageSquare, Zap, AudioLines } from 'lucide-svelte';

    const convId = $derived($page.params.id);

    let conv: ConversationOut | null = $state(null);
    let messages: MessageOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let selectedModel = $state('');
    let streaming = $state(false);
    let nodeBadge: string | null = $state(null);
    let approval: { request_id: string; tool: string } | null = $state(null);
    let scroller: HTMLElement | undefined = $state();

    // Mode vocal
    let voiceOpen = $state(false);
    const voiceBus = createVoiceBus();

    async function load() {
        conv = await conversations.get(convId);
        messages = await conversations.messages(convId);
        models = await nodesApi.models().catch(() => []);
        selectedModel = conv.model_pref ?? models[0]?.name ?? '';
        await tick();
        scrollBottom();
    }

    function scrollBottom() {
        scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    }

    async function send(text: string) {
        if (!selectedModel) return;
        // Optimistic user message
        messages = [
            ...messages,
            {
                id: crypto.randomUUID(),
                role: 'user',
                content: text,
                model_used: null,
                tokens_in: null,
                tokens_out: null,
                latency_ms: null,
                created_at: new Date().toISOString()
            }
        ];
        await tick();
        scrollBottom();

        streaming = true;
        nodeBadge = null;
        let assistant: MessageOut = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: '',
            model_used: selectedModel,
            tokens_in: null,
            tokens_out: null,
            latency_ms: null,
            created_at: new Date().toISOString()
        };
        messages = [...messages, assistant];

        try {
            for await (const ev of conversations.send(convId, { text, model: selectedModel })) {
                if (ev.event === 'node') {
                    const d = ev.data as { name: string; model: string };
                    nodeBadge = `${d.name} · ${d.model}`;
                } else if (ev.event === 'token') {
                    const d = ev.data as { text: string };
                    assistant.content += d.text;
                    voiceBus.token(d.text);
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    scrollBottom();
                } else if (ev.event === 'approval_required') {
                    const d = ev.data as { request_id: string; tool: string };
                    approval = { request_id: d.request_id, tool: d.tool };
                } else if (ev.event === 'tool_result') {
                    // Recharge l'historique : un message role=tool a été ajouté
                    messages = await conversations.messages(convId);
                } else if (ev.event === 'done') {
                    const d = ev.data as { tokens_out: number; latency_ms: number };
                    assistant.tokens_out = d.tokens_out;
                    assistant.latency_ms = d.latency_ms;
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    voiceBus.done();
                } else if (ev.event === 'error') {
                    const d = ev.data as { message: string };
                    assistant.content += `\n\n⚠️ ${d.message}`;
                    messages = [...messages.slice(0, -1), { ...assistant }];
                }
            }
        } catch (e) {
            console.error(e);
            toast.error('Erreur de communication avec le backend');
        } finally {
            streaming = false;
            approval = null;
        }
    }

    async function decide(approved: boolean) {
        if (!approval) return;
        await toolsApi.decideApproval(approval.request_id, approved);
        approval = null;
    }

    onMount(() => {
        load();
    });

    $effect(() => {
        // Si l'ID change (navigation interne), recharge
        convId;
        untrack(() => load());
    });
</script>

<header
    class="flex items-center justify-between border-b border-[var(--color-border-subtle)]
           bg-[color-mix(in_oklch,var(--color-bg-0)_70%,transparent)] px-6 py-3 backdrop-blur sm:px-8"
>
    <div class="min-w-0">
        <h1 class="truncate text-lg font-medium">{conv?.title ?? '…'}</h1>
        {#if nodeBadge}
            <p
                in:fade={{ duration: 200 }}
                class="flex items-center gap-1 text-xs text-cyan-400"
            >
                <Zap size={10} class="fill-cyan-400" />
                {nodeBadge}
            </p>
        {/if}
    </div>

    <div class="flex items-center gap-3">
        <button
            type="button"
            onclick={() => (voiceOpen = true)}
            title="Mode vocal"
            aria-label="Mode vocal"
            class="grid h-8 w-8 place-items-center rounded-full
                   border border-cyan-500/30 bg-cyan-500/10 text-cyan-300
                   transition hover:bg-cyan-500/20"
        >
            <AudioLines size={14} />
        </button>
        <label class="flex items-center gap-2 text-sm">
            <Sparkles size={14} class="text-cyan-400" />
            <select
                bind:value={selectedModel}
                class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)] px-2 py-1
                       text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
            >
                {#each models as m}
                    <option value={m.name}>{m.name}</option>
                {/each}
            </select>
        </label>
    </div>
</header>

<div bind:this={scroller} class="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
    <div class="mx-auto flex max-w-3xl flex-col gap-5">
        {#each messages as m, i (m.id)}
            <MessageBubble
                message={m}
                streaming={streaming && i === messages.length - 1 && m.role === 'assistant'}
            />
        {:else}
            <EmptyState
                icon={MessageSquare}
                title="Conversation vide"
                description="Posez votre première question pour démarrer."
            />
        {/each}
    </div>
</div>

{#if approval}
    <div
        in:fade
        class="border-t border-amber-900/50 bg-amber-950/40 px-4 py-3 sm:px-8"
    >
        <div class="mx-auto flex max-w-3xl items-center justify-between gap-4">
            <p class="text-sm text-amber-100">
                L'assistant veut utiliser <strong>{approval.tool}</strong>. Approuver ?
            </p>
            <div class="flex gap-2">
                <button
                    type="button"
                    onclick={() => decide(false)}
                    class="rounded-md border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800"
                    >Refuser</button
                >
                <button
                    type="button"
                    onclick={() => decide(true)}
                    class="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-amber-950
                           hover:bg-amber-400"
                    >Approuver</button
                >
            </div>
        </div>
    </div>
{/if}

<Composer disabled={streaming} onsend={send} />

<VoiceMode
    bind:open={voiceOpen}
    {streaming}
    bus={voiceBus}
    onclose={() => (voiceOpen = false)}
    onsubmit={(t) => send(t)}
/>
