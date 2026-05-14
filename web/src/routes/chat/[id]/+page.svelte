<script lang="ts">
    import { onMount, tick, untrack } from 'svelte';
    import { page } from '$app/stores';
    import { fade } from 'svelte/transition';
    import {
        conversations,
        nodes as nodesApi,
        tools as toolsApi,
        auth,
        uuid,
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
    import { Sparkles, MessageSquare, Zap, AudioLines, ChevronDown, Loader2 } from 'lucide-svelte';

    const convId = $derived($page.params.id);

    let conv: ConversationOut | null = $state(null);
    let messages: MessageOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let selectedModel = $state('');
    let streaming = $state(false);
    let nodeBadge: string | null = $state(null);
    let loadingModel: { node: string; model: string; phase: string; elapsed_s?: number } | null = $state(null);
    let approval: { request_id: string; tool: string } | null = $state(null);
    let scroller: HTMLElement | undefined = $state();

    // Dropdown models
    let isModelDropdownOpen = $state(false);

    // Mode vocal
    let voiceOpen = $state(false);
    const voiceBus = createVoiceBus();

    async function load() {
        if (!convId) return;
        conv = await conversations.get(convId);
        messages = await conversations.messages(convId);
        models = await nodesApi.models().catch(() => []);
        let defaultModel = '';
        try {
            const me = await auth.me();
            defaultModel = me.default_model ?? '';
        } catch {
            if (typeof localStorage !== 'undefined') {
                defaultModel = localStorage.getItem('spouet:default_model') || '';
            }
        }
        selectedModel = conv.model_pref ?? defaultModel ?? models[0]?.name ?? '';
        // If default model wasn't available in the nodes list, fallback to first available
        if (selectedModel && models.length > 0 && !models.some(m => m.name === selectedModel)) {
             selectedModel = models[0].name;
        }
        await tick();
        scrollBottom();
    }

    function scrollBottom() {
        scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    }

    async function send(text: string) {
        if (!selectedModel) {
            if (models.length === 0) {
                toast.error(
                    'Aucun modèle disponible. Vérifie que ton node est en ligne et qu\'au moins un modèle Ollama y est installé (ollama pull …).'
                );
            } else {
                toast.error('Sélectionne un modèle dans la liste en haut à droite.');
            }
            return;
        }
        // Optimistic user message
        messages = [
            ...messages,
            {
                id: uuid(),
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
        loadingModel = null;
        let assistant: MessageOut = {
            id: uuid(),
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
            if (!convId) return;
            for await (const ev of conversations.send(convId, { text, model: selectedModel })) {
                if (ev.event === 'node') {
                    const d = ev.data as { name: string; model: string };
                    nodeBadge = `${d.name} · ${d.model}`;
                    loadingModel = null;
                } else if (ev.event === 'loading_model') {
                    const d = ev.data as { node: string; model: string; phase: string; elapsed_s?: number };
                    loadingModel = d;
                } else if (ev.event === 'token') {
                    const d = ev.data as { text: string };
                    assistant.content += d.text;
                    // TTS uniquement quand le mode vocal est ouvert — sinon
                    // l'assistant ne doit JAMAIS parler de lui-même.
                    if (voiceOpen) voiceBus.token(d.text);
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    scrollBottom();
                } else if (ev.event === 'approval_required') {
                    const d = ev.data as { request_id: string; tool: string };
                    approval = { request_id: d.request_id, tool: d.tool };
                } else if (ev.event === 'tool_result') {
                    // Recharge l'historique : un message role=tool a été ajouté
                    if (convId) messages = await conversations.messages(convId);
                } else if (ev.event === 'done') {
                    const d = ev.data as { tokens_out: number; latency_ms: number };
                    assistant.tokens_out = d.tokens_out;
                    assistant.latency_ms = d.latency_ms;
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    if (voiceOpen) voiceBus.done();
                    // Recharge depuis le serveur pour récupérer ttft/finish_reason
                    if (convId) {
                        const fresh = await conversations.messages(convId);
                        if (fresh.length > 0) {
                            messages = fresh;
                        }
                    }
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
            loadingModel = null;
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
        {#if loadingModel}
            <p
                in:fade={{ duration: 200 }}
                class="flex items-center gap-1.5 text-xs text-amber-300"
            >
                <Loader2 size={10} class="animate-spin" />
                {#if loadingModel.phase === 'start'}
                    Chargement de {loadingModel.model} sur {loadingModel.node}…
                {:else if loadingModel.phase === 'warming'}
                    Chauffe llama-server… ({loadingModel.elapsed_s ?? 0}s)
                {:else}
                    Prêt ({loadingModel.elapsed_s ?? 0}s)
                {/if}
            </p>
        {:else if nodeBadge}
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
            title="Mode vocal — dicter et écouter la réponse"
            aria-label="Mode vocal"
            class="grid h-8 w-8 place-items-center rounded-full
                   border border-cyan-500/30 bg-cyan-500/10 text-cyan-300
                   transition hover:bg-cyan-500/20"
        >
            <AudioLines size={14} />
        </button>
        <div class="relative">
            <button
                type="button"
                onclick={() => (isModelDropdownOpen = !isModelDropdownOpen)}
                class="flex items-center gap-2 rounded-md border border-[var(--color-border)]
                       bg-[var(--color-bg-1)] px-3 py-1.5 text-sm transition hover:border-cyan-500/50"
                title="Modèle Ollama utilisé pour répondre"
            >
                <Sparkles size={14} class="text-cyan-400" />
                <span class="hidden text-xs text-neutral-500 sm:inline">Modèle :</span>
                <span class="max-w-[120px] truncate text-neutral-200 sm:max-w-[160px]">
                    {selectedModel || 'Aucun modèle'}
                </span>
                <ChevronDown size={14} class="text-neutral-500 transition-transform {isModelDropdownOpen ? 'rotate-180' : ''}" />
            </button>
            {#if isModelDropdownOpen}
                <div
                    class="absolute right-0 top-full mt-2 z-50 w-56 rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-1)] p-1 shadow-xl"
                >
                    {#if models.length === 0}
                        <div class="px-3 py-2 text-xs text-neutral-500">Aucun modèle disponible</div>
                    {/if}
                    <ul class="max-h-60 overflow-y-auto">
                        {#each models as m}
                            <li>
                                <button
                                    type="button"
                                    class="w-full rounded px-3 py-2 text-left text-sm transition
                                           {selectedModel === m.name ? 'bg-cyan-500/10 text-cyan-400' : 'text-neutral-300 hover:bg-neutral-800'}"
                                    onclick={() => {
                                        selectedModel = m.name;
                                        isModelDropdownOpen = false;
                                    }}
                                >
                                    {m.name}
                                </button>
                            </li>
                        {/each}
                    </ul>
                </div>
                <!-- Svelte 5 - overlay to catch clicks outside -->
                <button
                    type="button"
                    class="fixed inset-0 z-40 cursor-default"
                    aria-label="Fermer le menu"
                    onclick={() => (isModelDropdownOpen = false)}
                ></button>
            {/if}
        </div>
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

{#if models.length === 0}
    <div class="border-t border-amber-900/50 bg-amber-950/40 px-4 py-3 sm:px-8">
        <div class="mx-auto max-w-3xl text-sm text-amber-100">
            Aucun modèle Ollama disponible.
            <a href="/nodes" class="underline">Vérifie tes nodes</a>
            (le node doit être <em>online</em> et avoir au moins un modèle installé via
            <code class="rounded bg-amber-950/60 px-1">ollama pull …</code>).
        </div>
    </div>
{/if}

<Composer
    disabled={streaming || !selectedModel}
    placeholder={!selectedModel
        ? 'Aucun modèle disponible — voir bandeau ci-dessus.'
        : 'Écrivez votre message…'}
    onsend={send}
/>

<VoiceMode
    bind:open={voiceOpen}
    {streaming}
    bus={voiceBus}
    onclose={() => (voiceOpen = false)}
    onsubmit={(t) => send(t)}
/>
