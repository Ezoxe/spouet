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
    import ToolPicker from '$lib/components/ToolPicker.svelte';
    import VisualCard from '$lib/components/VisualCard.svelte';
    import { createVoiceBus } from '$lib/voice';
    import { toast } from '$lib/toast.svelte';
    import { Sparkles, MessageSquare, Zap, AudioLines, ChevronDown, Loader2, Download, RefreshCw, Square, Copy } from 'lucide-svelte';
    import { goto } from '$app/navigation';
    import type { SseEvent } from '$lib/api';

    const convId = $derived($page.params.id);

    let conv: ConversationOut | null = $state(null);
    let messages: MessageOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let selectedModel = $state('');
    let selectedTools: string[] = $state([]);
    let streaming = $state(false);
    let abortController: AbortController | null = $state(null);
    let focusComposer: (() => void) | null = $state(null);
    let nodeBadge: string | null = $state(null);
    let loadingModel: { node: string; model: string; phase: string; elapsed_s?: number } | null = $state(null);
    let approval: {
        request_id: string;
        tool?: string;
        kind?: string;
        name?: string;
        query?: string;
        steps?: { action: string; app?: string; url?: string; monitor?: number; mode?: string }[];
    } | null = $state(null);
    let currentVisual: {
        kind: 'image' | 'card' | 'fact';
        url?: string | null;
        title?: string | null;
        text?: string | null;
        duration_ms?: number;
    } | null = $state(null);
    let scroller: HTMLElement | undefined = $state();
    // Espaceur bas : réserve une hauteur d'écran sous le dernier échange pour que
    // le couple question/réponse puisse remonter en haut du viewport (façon
    // ChatGPT) pendant la génération, au lieu de rester collé en bas.
    let spacerH = $state(0);

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
        selectedTools = [...(conv.allowed_tool_slugs ?? [])];
        await tick();
        scrollBottom();
    }

    async function updateAllowedTools(slugs: string[]) {
        if (!convId) return;
        selectedTools = slugs;
        try {
            conv = await conversations.patch(convId, { allowed_tool_slugs: slugs });
        } catch {
            toast.error('Impossible de mettre à jour les tools');
        }
    }

    async function cloneConversation() {
        if (!convId) return;
        try {
            const dup = await conversations.clone(convId);
            toast.success('Conversation dupliquée');
            goto(`/chat/${dup.id}`);
        } catch {
            toast.error('Duplication impossible');
        }
    }

    async function downloadExport() {
        if (!convId) return;
        try {
            const { blob, filename } = await conversations.export(convId);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (e) {
            console.error(e);
            toast.error('Export impossible');
        }
    }

    function scrollBottom() {
        scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    }

    // Épingle un message (par son id) en haut du viewport, en réservant une
    // hauteur d'écran en dessous pour laisser la place à la réponse à venir.
    async function pinMessageToTop(msgId: string) {
        if (scroller) spacerH = scroller.clientHeight;
        await tick();
        const el = scroller?.querySelector(`[data-mid="${msgId}"]`) as HTMLElement | null;
        if (!el || !scroller) return;
        const delta = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
        scroller.scrollTo({ top: scroller.scrollTop + delta - 12, behavior: 'smooth' });
    }

    // Génère le titre (1er échange) puis enrichit les tags au fil de l'eau.
    // Best-effort : silencieux en cas d'échec. Notifie la sidebar du changement.
    async function maybeAutoname() {
        if (!convId) return;
        const assistantCount = messages.filter((m) => m.role === 'assistant' && m.content).length;
        if (assistantCount === 0) return;
        if (assistantCount !== 1 && assistantCount % 3 !== 0) return;
        try {
            conv = await conversations.autoname(convId);
            window.dispatchEvent(new CustomEvent('spouet:conversations-changed'));
        } catch {
            /* best-effort : ni titre ni tags si le backend ne peut pas */
        }
    }

    function makePlaceholderAssistant(): MessageOut {
        return {
            id: uuid(),
            role: 'assistant',
            content: '',
            model_used: selectedModel,
            tokens_in: null,
            tokens_out: null,
            latency_ms: null,
            created_at: new Date().toISOString()
        };
    }

    function stopGeneration() {
        abortController?.abort();
    }

    async function consumeStream(source: AsyncIterable<SseEvent>) {
        streaming = true;
        nodeBadge = null;
        loadingModel = null;
        let assistant = makePlaceholderAssistant();
        messages = [...messages, assistant];

        try {
            for await (const ev of source) {
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
                    if (voiceOpen) voiceBus.token(d.text);
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    // Pas d'auto-scroll-bas par token : la question reste épinglée
                    // en haut et la réponse se déroule dessous, dans le champ de vision.
                } else if (ev.event === 'approval_required') {
                    const d = ev.data as {
                        request_id: string;
                        tool?: string;
                        kind?: string;
                        name?: string;
                        query?: string;
                        steps?: {
                            action: string;
                            app?: string;
                            url?: string;
                            monitor?: number;
                            mode?: string;
                        }[];
                    };
                    approval = {
                        request_id: d.request_id,
                        tool: d.tool,
                        kind: d.kind,
                        name: d.name,
                        query: d.query,
                        steps: d.steps
                    };
                } else if (ev.event === 'visual') {
                    currentVisual = ev.data as typeof currentVisual;
                } else if (ev.event === 'tool_result') {
                    if (convId) messages = await conversations.messages(convId);
                    // après reload, on perd la ref locale assistant → on recrée un placeholder
                    assistant = makePlaceholderAssistant();
                    messages = [...messages, assistant];
                } else if (ev.event === 'done') {
                    const d = ev.data as { tokens_out: number; latency_ms: number };
                    assistant.tokens_out = d.tokens_out;
                    assistant.latency_ms = d.latency_ms;
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    if (voiceOpen) voiceBus.done();
                    if (convId) {
                        const fresh = await conversations.messages(convId);
                        if (fresh.length > 0) messages = fresh;
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
            abortController = null;
            approval = null;
            loadingModel = null;
            // Recharge l'état persisté : si la génération a été stoppée, le
            // backend a tout de même sauvegardé les tokens reçus jusque-là.
            if (convId) {
                try {
                    const fresh = await conversations.messages(convId);
                    if (fresh.length > 0) messages = fresh;
                } catch {
                    /* garde l'état local */
                }
            }
            await maybeAutoname();
            // Génération terminée : on libère l'espaceur (la position de lecture
            // courante est conservée, pas de saut visible).
            spacerH = 0;
        }
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
        if (!convId) return;
        const userMsgId = uuid();
        messages = [
            ...messages,
            {
                id: userMsgId,
                role: 'user',
                content: text,
                model_used: null,
                tokens_in: null,
                tokens_out: null,
                latency_ms: null,
                created_at: new Date().toISOString()
            }
        ];
        await pinMessageToTop(userMsgId);
        abortController = new AbortController();
        await consumeStream(
            conversations.send(convId, { text, model: selectedModel }, abortController.signal)
        );
    }

    async function regenerate() {
        if (!convId || streaming) return;
        // Retire le dernier assistant en local pour montrer l'effet
        const lastAssistantIdx = [...messages].reverse().findIndex((m) => m.role === 'assistant');
        if (lastAssistantIdx === -1) return;
        const idx = messages.length - 1 - lastAssistantIdx;
        messages = messages.slice(0, idx);
        const lastUser = [...messages].reverse().find((m) => m.role === 'user');
        if (lastUser) await pinMessageToTop(lastUser.id);
        abortController = new AbortController();
        await consumeStream(
            conversations.regenerate(convId, { model: selectedModel }, abortController.signal)
        );
    }

    async function editUserMessage(msgId: string, newText: string) {
        if (!convId || streaming) return;
        const idx = messages.findIndex((m) => m.id === msgId);
        if (idx === -1) return;
        // Met à jour localement + tronque
        messages = messages
            .slice(0, idx + 1)
            .map((m, i) => (i === idx ? { ...m, content: newText } : m));
        await pinMessageToTop(msgId);
        abortController = new AbortController();
        await consumeStream(
            conversations.editMessage(
                convId,
                msgId,
                { text: newText, model: selectedModel },
                abortController.signal
            )
        );
    }

    async function decide(approved: boolean) {
        if (!approval) return;
        await toolsApi.decideApproval(approval.request_id, approved);
        approval = null;
    }

    function stepLabel(s: {
        action: string;
        app?: string;
        url?: string;
        monitor?: number;
        mode?: string;
    }): string {
        const extra = s.monitor
            ? ` (écran ${s.monitor}${s.mode ? `, ${s.mode}` : ''})`
            : s.mode
              ? ` (${s.mode})`
              : '';
        if (s.action === 'launch_app') return `Lancer ${s.app ?? '?'}${extra}`;
        if (s.action === 'open_url') return `Ouvrir ${s.url ?? '?'}${extra}`;
        return `${s.action}${extra}`;
    }

    onMount(() => {
        // Le chargement initial est géré par le $effect ci-dessous (qui s'exécute
        // aussi au montage en lisant convId) — ne pas le dupliquer ici.
        const handler = (e: KeyboardEvent) => {
            // Ctrl+/ : focus composer
            if (e.ctrlKey && e.key === '/') {
                e.preventDefault();
                focusComposer?.();
                return;
            }
            // Ctrl+E : export markdown
            if (e.ctrlKey && (e.key === 'e' || e.key === 'E')) {
                e.preventDefault();
                downloadExport();
                return;
            }
            // Ctrl+Shift+R : régénérer la dernière réponse
            if (e.ctrlKey && e.shiftKey && (e.key === 'R' || e.key === 'r')) {
                e.preventDefault();
                regenerate();
                return;
            }
            // Échap : arrêter la génération en cours
            if (e.key === 'Escape' && streaming) {
                e.preventDefault();
                stopGeneration();
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    });

    $effect(() => {
        // Chargement initial + rechargement quand l'ID change (navigation interne).
        // On coupe d'abord un éventuel stream encore en cours sur la conversation
        // précédente, sinon ses tokens viendraient polluer la nouvelle conv.
        convId;
        untrack(() => {
            abortController?.abort();
            load();
        });
    });

    // Stats agrégées pour le footer
    const stats = $derived.by(() => {
        let tokensOut = 0;
        let tokensIn = 0;
        let totalMs = 0;
        let count = 0;
        for (const m of messages) {
            if (m.role === 'assistant') {
                if (m.tokens_out) tokensOut += m.tokens_out;
                if (m.tokens_in) tokensIn += m.tokens_in;
                if (m.latency_ms) totalMs += m.latency_ms;
            }
            if (m.role === 'user' || m.role === 'assistant') count++;
        }
        return { count, tokensOut, tokensIn, totalMs };
    });
    // Libellé/détail de l'état de réflexion, transmis à la dernière bulle assistant.
    const thinkingLabel = $derived(loadingModel ? 'Chargement du modèle' : 'Réflexion');
    const thinkingDetail = $derived.by(() => {
        if (loadingModel) {
            if (loadingModel.phase === 'start') return `${loadingModel.model} · ${loadingModel.node}`;
            if (loadingModel.phase === 'warming') return `chauffe… ${loadingModel.elapsed_s ?? 0}s`;
            return `prêt · ${loadingModel.elapsed_s ?? 0}s`;
        }
        return nodeBadge;
    });

    function fmtSec(ms: number): string {
        if (ms < 1000) return `${ms} ms`;
        if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
        const m = Math.floor(ms / 60_000);
        const s = Math.floor((ms % 60_000) / 1000);
        return `${m}m${s.toString().padStart(2, '0')}`;
    }
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

    <div class="flex items-center gap-2 sm:gap-3">
        <button
            type="button"
            onclick={cloneConversation}
            title="Dupliquer la conversation (config sans les messages)"
            aria-label="Dupliquer la conversation"
            class="hidden h-8 w-8 place-items-center rounded-full border border-neutral-700
                   text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-100 sm:grid"
        >
            <Copy size={14} />
        </button>
        <button
            type="button"
            onclick={downloadExport}
            title="Exporter la conversation au format Markdown"
            aria-label="Exporter la conversation"
            class="hidden h-8 w-8 place-items-center rounded-full border border-neutral-700
                   text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-100 sm:grid"
        >
            <Download size={14} />
        </button>
        <ToolPicker selected={selectedTools} onchange={updateAllowedTools} disabled={streaming} />
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
            {@const isLastAssistant =
                m.role === 'assistant' &&
                i === messages.length - 1 &&
                !streaming &&
                !!m.content}
            <div data-mid={m.id}>
                <MessageBubble
                    message={m}
                    streaming={streaming && i === messages.length - 1 && m.role === 'assistant'}
                    canEdit={m.role === 'user' && !streaming}
                    canRegenerate={isLastAssistant}
                    {thinkingLabel}
                    {thinkingDetail}
                    onedit={editUserMessage}
                    onregenerate={regenerate}
                />
            </div>
        {:else}
            <EmptyState
                icon={MessageSquare}
                title="Conversation vide"
                description="Posez votre première question pour démarrer."
            />
        {/each}
        {#if spacerH > 0}
            <div style="height:{spacerH}px" aria-hidden="true"></div>
        {/if}
    </div>
</div>

{#if currentVisual}
    <div class="pointer-events-none fixed bottom-28 right-6 z-40 flex justify-end">
        <div class="pointer-events-auto">
            <VisualCard visual={currentVisual} ondone={() => (currentVisual = null)} />
        </div>
    </div>
{/if}

{#if approval}
    <div
        in:fade
        class="border-t border-amber-900/50 bg-amber-950/40 px-4 py-3 sm:px-8"
    >
        <div class="mx-auto flex max-w-3xl items-center justify-between gap-4">
            {#if approval.kind === 'define_macro'}
                <div class="min-w-0 text-sm text-amber-100">
                    <p>Enregistrer la macro <strong>« {approval.name} »</strong> ?</p>
                    <ul class="mt-1 space-y-0.5 text-xs text-amber-200/80">
                        {#each approval.steps ?? [] as s, i}
                            <li>{i + 1}. {stepLabel(s)}</li>
                        {/each}
                    </ul>
                </div>
            {:else if approval.kind === 'web_search'}
                <p class="min-w-0 text-sm text-amber-100">
                    🔎 L'assistant veut chercher sur le web :
                    <strong class="break-words">« {approval.query} »</strong>. Autoriser ?
                </p>
            {:else}
                <p class="text-sm text-amber-100">
                    L'assistant veut utiliser <strong>{approval.tool}</strong>. Approuver ?
                </p>
            {/if}
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

{#if streaming}
    <div class="flex justify-center px-4 pb-1 sm:px-8" in:fade={{ duration: 150 }}>
        <button
            type="button"
            onclick={stopGeneration}
            class="flex items-center gap-2 rounded-full border border-neutral-700 bg-[var(--color-bg-1)]
                   px-4 py-1.5 text-xs text-neutral-300 shadow-lg transition hover:border-red-500/50 hover:text-red-300"
        >
            <Square size={11} class="fill-current" />
            Arrêter la génération
        </button>
    </div>
{/if}

{#if stats.count > 0}
    <div class="border-t border-[var(--color-border-subtle)] bg-[color-mix(in_oklch,var(--color-bg-0)_85%,transparent)] px-4 py-1.5 text-[10px] text-neutral-500 sm:px-8">
        <div class="mx-auto flex max-w-3xl items-center justify-between">
            <span>{stats.count} message{stats.count > 1 ? 's' : ''}</span>
            <span>
                {#if stats.tokensIn}{stats.tokensIn} tok in · {/if}{stats.tokensOut} tok out
                {#if stats.totalMs}· {fmtSec(stats.totalMs)} de génération{/if}
            </span>
        </div>
    </div>
{/if}

<Composer
    onready={(api) => (focusComposer = api.focus)}
    disabled={streaming || !selectedModel}
    busy={streaming}
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
