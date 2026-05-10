<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { page } from '$app/stores';
    import {
        workspaces as workspacesApi,
        conversations,
        nodes as nodesApi,
        uuid,
        type WorkspaceOut,
        type ConversationRef,
        type MessageOut,
        type ModelAgg
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import MessageBubble from '$lib/components/MessageBubble.svelte';
    import Composer from '$lib/components/Composer.svelte';
    import { Zap, Bot, Crown, Loader2 } from 'lucide-svelte';

    const workspaceId = $derived($page.params.id);

    let workspace: WorkspaceOut | null = $state(null);
    let models: ModelAgg[] = $state([]);
    let loading = $state(true);

    // Messages par conversation : Map<conv_id, MessageOut[]>
    let messagesByConv: Map<string, MessageOut[]> = $state(new Map());
    // Streaming content par conv (token accumulation)
    let streamingByConv: Map<string, string> = $state(new Map());
    let streamingConvId: string | null = $state(null);

    // Manager
    let managerConv: ConversationRef | null = $state(null);
    let managerStreaming = $state(false);
    let managerNodeBadge: string | null = $state(null);
    let managerScroller: HTMLElement | undefined = $state();
    let selectedModel = $state('');

    let wsStream: AsyncIterable<{ event: string; data: unknown }> | null = null;
    let wsStreamActive = false;

    // -------------------------------------------------------------------------
    async function load() {
        if (!workspaceId) return;
        loading = true;
        try {
            [workspace, models] = await Promise.all([
                workspacesApi.get(workspaceId),
                nodesApi.models().catch(() => [] as ModelAgg[])
            ]);
            managerConv = workspace.conversations.find((c) => c.workspace_role === 'manager') ?? null;
            selectedModel = managerConv?.model_pref ?? models[0]?.name ?? '';

            // Charge les messages de toutes les conversations
            await Promise.all(
                workspace.conversations.map(async (c) => {
                    const msgs = await conversations.messages(c.id).catch(() => [] as MessageOut[]);
                    messagesByConv.set(c.id, msgs);
                })
            );
            messagesByConv = new Map(messagesByConv);
        } finally {
            loading = false;
        }

        // Lance le stream workspace SSE
        startWorkspaceStream();
    }

    function startWorkspaceStream() {
        if (!workspaceId) return;
        wsStreamActive = true;
        wsStream = workspacesApi.stream(workspaceId);
        consumeStream();
    }

    async function consumeStream() {
        if (!wsStream) return;
        try {
            for await (const ev of wsStream) {
                if (!wsStreamActive) break;
                const data = ev.data as Record<string, unknown>;
                const convId = data?.conv_id as string | undefined;
                if (!convId) continue;

                if (ev.event === 'worker_start') {
                    streamingByConv.set(convId, '');
                    streamingConvId = convId;
                    streamingByConv = new Map(streamingByConv);
                } else if (ev.event === 'worker_token') {
                    const text = (data.text as string) ?? '';
                    const current = streamingByConv.get(convId) ?? '';
                    streamingByConv.set(convId, current + text);
                    streamingByConv = new Map(streamingByConv);
                } else if (ev.event === 'worker_done' || ev.event === 'worker_error') {
                    // Recharge les messages pour ce conv worker
                    const msgs = await conversations.messages(convId).catch(() => [] as MessageOut[]);
                    messagesByConv.set(convId, msgs);
                    messagesByConv = new Map(messagesByConv);
                    streamingByConv.delete(convId);
                    streamingByConv = new Map(streamingByConv);
                    if (streamingConvId === convId) streamingConvId = null;
                }
            }
        } catch {
            // Stream closed or error — fine, component may be destroyed
        }
    }

    // -------------------------------------------------------------------------
    // Manager chat

    async function sendToManager(text: string) {
        if (!managerConv || !selectedModel) return;

        // Optimistic
        const msgs = [...(messagesByConv.get(managerConv.id) ?? [])];
        const userMsg: MessageOut = {
            id: uuid(),
            role: 'user',
            content: text,
            model_used: null,
            tokens_in: null,
            tokens_out: null,
            latency_ms: null,
            created_at: new Date().toISOString()
        };
        const assistantMsg: MessageOut = {
            id: uuid(),
            role: 'assistant',
            content: '',
            model_used: selectedModel,
            tokens_in: null,
            tokens_out: null,
            latency_ms: null,
            created_at: new Date().toISOString()
        };
        msgs.push(userMsg, assistantMsg);
        messagesByConv.set(managerConv.id, [...msgs]);
        messagesByConv = new Map(messagesByConv);

        managerStreaming = true;
        managerNodeBadge = null;
        await tick();
        managerScroller?.scrollTo({ top: managerScroller.scrollHeight });

        try {
            for await (const ev of conversations.send(managerConv.id, {
                text,
                model: selectedModel
            })) {
                const convMsgs = [...(messagesByConv.get(managerConv.id) ?? [])];
                const last = convMsgs[convMsgs.length - 1];
                if (ev.event === 'node') {
                    const d = ev.data as { name: string; model: string };
                    managerNodeBadge = `${d.name} · ${d.model}`;
                } else if (ev.event === 'token') {
                    const d = ev.data as { text: string };
                    if (last?.role === 'assistant') {
                        last.content += d.text;
                        convMsgs[convMsgs.length - 1] = { ...last };
                        messagesByConv.set(managerConv.id, [...convMsgs]);
                        messagesByConv = new Map(messagesByConv);
                        managerScroller?.scrollTo({ top: managerScroller.scrollHeight });
                    }
                } else if (ev.event === 'tool_result') {
                    // Recharge tout (message tool ajouté par le manager pendant la délégation)
                    const refreshed = await conversations.messages(managerConv.id).catch(() => convMsgs);
                    messagesByConv.set(managerConv.id, refreshed);
                    messagesByConv = new Map(messagesByConv);
                } else if (ev.event === 'done') {
                    const d = ev.data as { tokens_out: number; latency_ms: number };
                    if (last?.role === 'assistant') {
                        last.tokens_out = d.tokens_out;
                        last.latency_ms = d.latency_ms;
                        convMsgs[convMsgs.length - 1] = { ...last };
                        messagesByConv.set(managerConv.id, [...convMsgs]);
                        messagesByConv = new Map(messagesByConv);
                    }
                } else if (ev.event === 'error') {
                    const d = ev.data as { message: string };
                    if (last?.role === 'assistant') {
                        last.content += `\n\n⚠️ ${d.message}`;
                        convMsgs[convMsgs.length - 1] = { ...last };
                        messagesByConv.set(managerConv.id, [...convMsgs]);
                        messagesByConv = new Map(messagesByConv);
                    }
                }
            }
        } catch {
            toast.error('Erreur de communication avec le backend');
        } finally {
            managerStreaming = false;
        }
    }

    onMount(load);

    onDestroy(() => {
        wsStreamActive = false;
    });
</script>

{#if loading}
    <div class="grid flex-1 place-items-center">
        <Loader2 size={24} class="animate-spin text-neutral-500" />
    </div>
{:else if !workspace}
    <div class="grid flex-1 place-items-center text-neutral-500">Workspace introuvable.</div>
{:else}
    <div class="flex h-full flex-col overflow-hidden">
        <!-- En-tête workspace -->
        <header class="flex shrink-0 items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-3">
            <div>
                <h1 class="font-semibold">{workspace.name}</h1>
                <p class="text-xs text-neutral-500">
                    {workspace.conversations.length} agent{workspace.conversations.length !== 1 ? 's' : ''}
                    {#if streamingConvId}
                        · <span class="text-cyan-400">worker actif…</span>
                    {/if}
                </p>
            </div>
        </header>

        <!-- Panneaux -->
        <div class="flex min-h-0 flex-1 divide-x divide-[var(--color-border-subtle)] overflow-hidden">

            <!-- Panneau manager (gauche, plus large) -->
            {#if managerConv}
                <div class="flex min-w-0 flex-[2] flex-col overflow-hidden">
                    <div class="flex shrink-0 items-center gap-2 border-b border-[var(--color-border-subtle)] bg-cyan-950/20 px-4 py-2">
                        <Crown size={13} class="text-cyan-400" />
                        <span class="text-xs font-medium text-cyan-300">Manager</span>
                        <span class="truncate text-xs text-neutral-400">{managerConv.title}</span>
                        {#if managerNodeBadge}
                            <span class="ml-auto flex items-center gap-1 text-xs text-cyan-400">
                                <Zap size={10} class="fill-cyan-400" />
                                {managerNodeBadge}
                            </span>
                        {/if}
                    </div>
                    <div bind:this={managerScroller} class="flex-1 overflow-y-auto px-4 py-4">
                        <div class="mx-auto flex max-w-2xl flex-col gap-4">
                            {#each messagesByConv.get(managerConv.id) ?? [] as m, i (m.id)}
                                <MessageBubble
                                    message={m}
                                    streaming={managerStreaming && i === (messagesByConv.get(managerConv.id)?.length ?? 0) - 1 && m.role === 'assistant'}
                                />
                            {/each}
                        </div>
                    </div>
                    <Composer
                        disabled={managerStreaming || !selectedModel}
                        placeholder={!selectedModel ? 'Aucun modèle disponible.' : 'Message au manager…'}
                        onsend={sendToManager}
                    />
                </div>
            {/if}

            <!-- Panneaux workers (droite) -->
            <div class="flex min-w-0 flex-1 flex-col divide-y divide-[var(--color-border-subtle)] overflow-y-auto">
                {#each workspace.conversations.filter((c) => c.workspace_role === 'worker') as w (w.id)}
                    {@const isStreaming = streamingConvId === w.id}
                    {@const streamText = streamingByConv.get(w.id) ?? ''}
                    <div class="flex min-h-[200px] flex-col overflow-hidden">
                        <div class="flex shrink-0 items-center gap-2 border-b border-[var(--color-border-subtle)] px-4 py-2">
                            <Bot size={13} class="text-neutral-500" />
                            <span class="text-xs font-medium text-neutral-400">Worker</span>
                            <span class="truncate text-xs text-neutral-500">{w.title}</span>
                            {#if w.model_pref}
                                <span class="ml-auto text-[10px] text-neutral-600">{w.model_pref}</span>
                            {/if}
                            {#if isStreaming}
                                <span class="ml-1 h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400"></span>
                            {/if}
                        </div>
                        <div class="flex-1 overflow-y-auto px-3 py-3">
                            <div class="flex flex-col gap-3">
                                {#each messagesByConv.get(w.id) ?? [] as m (m.id)}
                                    <MessageBubble
                                        message={m}
                                        streaming={false}
                                    />
                                {/each}
                                {#if isStreaming && streamText}
                                    <MessageBubble
                                        message={{
                                            id: 'streaming',
                                            role: 'assistant',
                                            content: streamText,
                                            model_used: w.model_pref,
                                            tokens_in: null,
                                            tokens_out: null,
                                            latency_ms: null,
                                            created_at: new Date().toISOString()
                                        }}
                                        streaming={true}
                                    />
                                {/if}
                                {#if !isStreaming && (messagesByConv.get(w.id) ?? []).length === 0}
                                    <p class="text-center text-xs text-neutral-600">En attente d'une délégation…</p>
                                {/if}
                            </div>
                        </div>
                    </div>
                {/each}
                {#if workspace.conversations.filter((c) => c.workspace_role === 'worker').length === 0}
                    <div class="grid flex-1 place-items-center text-xs text-neutral-600">
                        Aucun worker configuré dans ce workspace.
                    </div>
                {/if}
            </div>
        </div>
    </div>
{/if}
