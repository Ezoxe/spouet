<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { fade, fly, scale } from 'svelte/transition';
    import {
        nodes as nodesApi,
        conversations,
        tools as toolsApi,
        uuid,
        type ModelAgg,
        type MessageOut
    } from '$lib/api';
    import { Send, X, AudioLines, Sparkles } from 'lucide-svelte';
    import AiFace from '$lib/components/AiFace.svelte';
    import Markdown from '$lib/components/Markdown.svelte';
    import ThinkingIndicator from '$lib/components/ThinkingIndicator.svelte';
    import VoiceMode from '$lib/components/VoiceMode.svelte';
    import VisualCard from '$lib/components/VisualCard.svelte';
    import { createVoiceBus } from '$lib/voice';

    type Step = { action: string; app?: string; url?: string; monitor?: number; mode?: string };

    let convId: string | null = $state(null);
    let messages: MessageOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let selectedModel = $state('');
    let text = $state('');
    let streaming = $state(false);
    let scroller: HTMLElement | undefined = $state();
    let expanded = $state(false);
    let voiceOpen = $state(false);
    let voiceStart = $state(0);
    let approval: {
        request_id: string;
        kind?: string;
        name?: string;
        tool?: string;
        query?: string;
        steps?: Step[];
    } | null = $state(null);
    let currentVisual: {
        kind: 'image' | 'card' | 'fact';
        url?: string | null;
        title?: string | null;
        text?: string | null;
        duration_ms?: number;
    } | null = $state(null);
    const voiceBus = createVoiceBus();

    function stepLabel(s: Step): string {
        const extra = s.monitor ? ` (écran ${s.monitor})` : '';
        if (s.action === 'launch_app') return `Lancer ${s.app ?? '?'}${extra}`;
        if (s.action === 'open_url') return `Ouvrir ${s.url ?? '?'}${extra}`;
        return `${s.action}${extra}`;
    }

    async function decide(approved: boolean) {
        if (!approval) return;
        await toolsApi.decideApproval(approval.request_id, approved);
        approval = null;
    }

    // Dans l'app desktop, le raccourci Ctrl+Maj+Espace / le tray émettent
    // `spouet://start-voice` : on ouvre le mode vocal et on démarre l'écoute.
    let unlistenVoice: (() => void) | null = null;
    onMount(() => {
        const tauri = (window as unknown as { __TAURI__?: { event?: { listen?: Function } } })
            .__TAURI__;
        if (tauri?.event?.listen) {
            tauri.event
                .listen('spouet://start-voice', () => {
                    voiceOpen = true;
                    voiceStart++;
                })
                .then((un: () => void) => (unlistenVoice = un))
                .catch(() => {});
        }
    });
    onDestroy(() => unlistenVoice?.());

    async function ensureConv() {
        if (convId) return convId;
        const c = await conversations.create({ title: '[compagnon]' });
        convId = c.id;
        return convId;
    }

    async function send(input?: string) {
        const userText = (input ?? text).trim();
        if (!userText || !selectedModel || streaming) return;
        const id = await ensureConv();
        text = '';
        expanded = true;
        messages = [
            ...messages,
            {
                id: uuid(),
                role: 'user',
                content: userText,
                model_used: null,
                tokens_in: null,
                tokens_out: null,
                latency_ms: null,
                created_at: new Date().toISOString()
            }
        ];
        const assistant: MessageOut = {
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
        streaming = true;
        try {
            for await (const ev of conversations.send(id, { text: userText, model: selectedModel })) {
                if (ev.event === 'token') {
                    const delta = (ev.data as { text: string }).text;
                    assistant.content += delta;
                    voiceBus.token(delta);
                    messages = [...messages.slice(0, -1), { ...assistant }];
                    await tick();
                    scroller?.scrollTo({ top: scroller.scrollHeight });
                } else if (ev.event === 'approval_required') {
                    const d = ev.data as {
                        request_id: string;
                        kind?: string;
                        name?: string;
                        tool?: string;
                        query?: string;
                        steps?: Step[];
                    };
                    approval = {
                        request_id: d.request_id,
                        kind: d.kind,
                        name: d.name,
                        tool: d.tool,
                        query: d.query,
                        steps: d.steps
                    };
                } else if (ev.event === 'visual') {
                    currentVisual = ev.data as typeof currentVisual;
                } else if (ev.event === 'done') {
                    voiceBus.done();
                }
            }
        } finally {
            streaming = false;
        }
    }

    function close() {
        if (typeof window !== 'undefined' && (window as any).__TAURI__) {
            (window as any).__TAURI__.window.getCurrent().hide();
        }
    }

    function onKey(e: KeyboardEvent) {
        if (e.key === 'Escape' && !voiceOpen) {
            if (expanded) {
                expanded = false;
                messages = [];
            } else {
                close();
            }
        }
    }

    onMount(async () => {
        models = await nodesApi.models().catch(() => []);
        selectedModel = models[0]?.name ?? '';
    });
</script>

<svelte:window on:keydown={onKey} />

<div class="companion-root">
    <header
        class="flex items-center justify-between px-3 py-2 text-xs text-neutral-400"
        data-tauri-drag-region
    >
        <div class="flex items-center gap-2">
            <Sparkles size={12} class="text-cyan-400" />
            <select
                bind:value={selectedModel}
                class="rounded bg-transparent text-[11px] focus:outline-none"
            >
                {#each models as m}
                    <option value={m.name} class="bg-neutral-900">{m.name}</option>
                {/each}
            </select>
        </div>
        <div class="flex items-center gap-1">
            <button
                type="button"
                onclick={() => (voiceOpen = true)}
                class="rounded p-1 text-neutral-400 hover:bg-white/5 hover:text-cyan-300"
                title="Mode vocal"
                aria-label="Mode vocal"
            >
                <AudioLines size={14} />
            </button>
            <button
                type="button"
                onclick={close}
                class="rounded p-1 text-neutral-500 hover:bg-white/5 hover:text-neutral-200"
                aria-label="Fermer"
            >
                <X size={14} />
            </button>
        </div>
    </header>

    {#if currentVisual}
        <div class="pointer-events-none absolute inset-x-0 top-12 z-30 flex justify-center px-3">
            <div class="pointer-events-auto">
                <VisualCard visual={currentVisual} ondone={() => (currentVisual = null)} />
            </div>
        </div>
    {/if}

    {#if !expanded}
        <div
            class="flex flex-1 flex-col items-center justify-center gap-6 px-6"
            in:fade={{ duration: 180 }}
        >
            <div in:scale={{ duration: 320, start: 0.85 }}>
                <AiFace size={132} state={streaming ? 'thinking' : 'idle'} />
            </div>
            <p class="text-center text-xs text-neutral-500">
                Posez une question rapide à Spouet.
            </p>
        </div>
    {:else}
        <div bind:this={scroller} class="flex-1 overflow-y-auto px-3 py-2">
            {#each messages as m, i (m.id)}
                <div class="mb-2" in:fly={{ y: 4, duration: 150 }}>
                    <p class="flex items-center gap-1.5 text-[10px] uppercase text-neutral-600">
                        {#if m.role === 'assistant'}
                            <AiFace
                                size={22}
                                state={streaming && i === messages.length - 1
                                    ? m.content
                                        ? 'writing'
                                        : 'thinking'
                                    : 'idle'}
                            />
                        {/if}
                        {m.role}
                    </p>
                    <div
                        class="rounded-lg px-3 py-2 text-sm {m.role === 'user'
                            ? 'whitespace-pre-wrap bg-cyan-900/30 text-cyan-100'
                            : 'bg-neutral-900/70 text-neutral-200'}"
                    >
                        {#if m.role === 'assistant'}
                            {#if streaming && i === messages.length - 1 && !m.content}
                                <ThinkingIndicator />
                            {:else}
                                <Markdown content={m.content} />
                            {/if}
                        {:else}
                            {m.content || '…'}
                        {/if}
                    </div>
                </div>
            {/each}
        </div>
    {/if}

    {#if approval}
        <div
            class="mx-2 mb-1 rounded-lg border border-amber-900/50 bg-amber-950/50 px-3 py-2 text-xs text-amber-100"
        >
            {#if approval.kind === 'define_macro'}
                <p>Enregistrer « {approval.name} » ?</p>
                <ul class="mt-1 space-y-0.5 text-[11px] text-amber-200/80">
                    {#each approval.steps ?? [] as s, i}
                        <li>{i + 1}. {stepLabel(s)}</li>
                    {/each}
                </ul>
            {:else if approval.kind === 'web_search'}
                <p>🔎 Chercher sur le web : <strong>« {approval.query} »</strong> ?</p>
            {:else}
                <p>Autoriser <strong>{approval.tool}</strong> ?</p>
            {/if}
            <div class="mt-1.5 flex gap-2">
                <button
                    type="button"
                    onclick={() => decide(false)}
                    class="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800">Refuser</button
                >
                <button
                    type="button"
                    onclick={() => decide(true)}
                    class="rounded bg-amber-500 px-2 py-1 font-medium text-amber-950 hover:bg-amber-400"
                    >Approuver</button
                >
            </div>
        </div>
    {/if}

    <form
        onsubmit={(e) => {
            e.preventDefault();
            send();
        }}
        class="px-2 pb-2 pt-1"
    >
        <div
            class="flex items-end gap-2 rounded-xl border border-white/5
                   bg-neutral-900/80 p-1.5 shadow-inner backdrop-blur"
        >
            <textarea
                bind:value={text}
                rows="1"
                placeholder={expanded ? 'Continuer…' : 'Demande rapide…'}
                disabled={streaming}
                class="flex-1 resize-none bg-transparent px-2 py-1 text-sm text-neutral-100
                       placeholder:text-neutral-600 focus:outline-none"
                onkeydown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        send();
                    }
                }}
            ></textarea>
            <button
                type="submit"
                disabled={streaming || !text.trim()}
                class="grid h-7 w-7 place-items-center rounded-lg
                       bg-gradient-to-br from-cyan-500 to-cyan-700 text-white
                       shadow-[0_4px_14px_-6px_oklch(0.55_0.18_210/0.9)]
                       transition active:scale-95 disabled:opacity-30"
            >
                <Send size={12} />
            </button>
        </div>
        <p class="mt-1 text-center text-[9px] uppercase tracking-widest text-neutral-700">
            Esc pour {expanded ? 'effacer' : 'fermer'}
        </p>
    </form>
</div>

<VoiceMode
    bind:open={voiceOpen}
    {streaming}
    bus={voiceBus}
    requestListen={voiceStart}
    onclose={() => (voiceOpen = false)}
    onsubmit={(t) => send(t)}
/>

<style>
    .companion-root {
        position: relative;
        display: flex;
        flex-direction: column;
        height: 100vh;
        background:
            radial-gradient(
                ellipse at 50% 0%,
                oklch(0.35 0.12 210 / 0.25),
                transparent 60%
            ),
            linear-gradient(
                180deg,
                oklch(0.13 0.02 240) 0%,
                oklch(0.08 0.01 240) 100%
            );
        color: var(--color-fg);
        overflow: hidden;
        animation: companion-in 220ms ease-out;
    }
    @keyframes companion-in {
        from {
            opacity: 0;
            transform: translateY(6px) scale(0.98);
        }
        to {
            opacity: 1;
            transform: translateY(0) scale(1);
        }
    }
</style>
