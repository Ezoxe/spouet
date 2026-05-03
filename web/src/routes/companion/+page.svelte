<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { fade, fly, scale } from 'svelte/transition';
    import {
        nodes as nodesApi,
        conversations,
        type ModelAgg,
        type MessageOut
    } from '$lib/api';
    import { Send, X, AudioLines, Sparkles } from 'lucide-svelte';
    import Logo from '$lib/components/Logo.svelte';
    import VoiceMode from '$lib/components/VoiceMode.svelte';
    import { createVoiceBus } from '$lib/voice';

    let convId: string | null = $state(null);
    let messages: MessageOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let selectedModel = $state('');
    let text = $state('');
    let streaming = $state(false);
    let scroller: HTMLElement | undefined = $state();
    let expanded = $state(false);
    let voiceOpen = $state(false);
    const voiceBus = createVoiceBus();

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
                id: crypto.randomUUID(),
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

    {#if !expanded}
        <div
            class="flex flex-1 flex-col items-center justify-center gap-6 px-6"
            in:fade={{ duration: 180 }}
        >
            <div in:scale={{ duration: 320, start: 0.85 }}>
                <Logo size={130} glow animated />
            </div>
            <p class="text-center text-xs text-neutral-500">
                Posez une question rapide à Spouet.
            </p>
        </div>
    {:else}
        <div bind:this={scroller} class="flex-1 overflow-y-auto px-3 py-2">
            {#each messages as m (m.id)}
                <div class="mb-2" in:fly={{ y: 4, duration: 150 }}>
                    <p class="text-[10px] uppercase text-neutral-600">{m.role}</p>
                    <div
                        class="rounded-lg px-3 py-2 text-sm whitespace-pre-wrap
                               {m.role === 'user'
                            ? 'bg-cyan-900/30 text-cyan-100'
                            : 'bg-neutral-900/70 text-neutral-200'}"
                    >
                        {m.content || '…'}
                    </div>
                </div>
            {/each}
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
