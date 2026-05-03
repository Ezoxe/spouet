<script lang="ts">
    import { onDestroy } from 'svelte';
    import { fade, scale } from 'svelte/transition';
    import { Mic, MicOff, X, Volume2, VolumeX } from 'lucide-svelte';
    import {
        startStt,
        createTts,
        isSttSupported,
        isTtsSupported,
        type TtsHandle,
        type VoiceBus
    } from '$lib/voice';
    import Logo from './Logo.svelte';

    interface Props {
        open: boolean;
        streaming: boolean;
        onclose: () => void;
        onsubmit: (text: string) => void;
        /** Le parent doit passer une instance et appeler `bus.token(delta)` /
         *  `bus.done()`. Cela évite les pertes de re-render quand un même
         *  delta est ré-émis. */
        bus?: VoiceBus;
    }

    let {
        open = $bindable(),
        streaming,
        onclose,
        onsubmit,
        bus
    }: Props = $props();

    const sttOk = isSttSupported();
    const ttsOk = isTtsSupported();

    let listening = $state(false);
    let muted = $state(false);
    let partial = $state('');
    let lastFinal = $state('');
    let error = $state<string | null>(null);

    let rec: ReturnType<typeof startStt> = null;
    let tts: TtsHandle | null = null;

    function ensureTts(): TtsHandle {
        if (!tts) tts = createTts('fr-FR');
        return tts;
    }

    function startListening() {
        if (!sttOk || streaming) return;
        partial = '';
        lastFinal = '';
        error = null;
        rec = startStt({
            lang: 'fr-FR',
            onPartial: (t) => (partial = t),
            onFinal: (t) => (lastFinal = t),
            onError: (e) => {
                error = e;
                listening = false;
            },
            onEnd: () => {
                listening = false;
                const text = (lastFinal || partial).trim();
                if (text) {
                    onsubmit(text);
                    partial = '';
                    lastFinal = '';
                }
            }
        });
        listening = !!rec;
    }

    function stopListening() {
        rec?.stop();
    }

    function toggleListen() {
        if (listening) stopListening();
        else startListening();
    }

    function toggleMute() {
        muted = !muted;
        if (muted) tts?.cancel();
    }

    function close() {
        rec?.abort();
        tts?.cancel();
        listening = false;
        onclose();
    }

    // Branchement du bus parent → TTS
    $effect(() => {
        if (!bus) return;
        const off = bus.subscribe({
            token: (delta) => {
                if (!ttsOk || muted) return;
                ensureTts().speak(delta);
            },
            done: () => {
                if (!ttsOk || muted) return;
                ensureTts().flush();
            }
        });
        return () => off();
    });

    onDestroy(() => {
        rec?.abort();
        tts?.cancel();
    });

    function onKey(e: KeyboardEvent) {
        if (!open) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
            return;
        }
        const t = e.target as HTMLElement | null;
        const tag = t?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || t?.isContentEditable) return;
        if (e.code === 'Space' && !e.repeat) {
            e.preventDefault();
            toggleListen();
        }
    }
</script>

<svelte:window on:keydown={onKey} />

{#if open}
    <div
        in:fade={{ duration: 180 }}
        out:fade={{ duration: 140 }}
        class="fixed inset-0 z-50 flex flex-col items-center justify-center
               bg-[oklch(0.05_0.02_240/0.92)] backdrop-blur-2xl"
        role="dialog"
        aria-modal="true"
    >
        <button
            type="button"
            onclick={close}
            class="absolute right-5 top-5 grid h-9 w-9 place-items-center rounded-full
                   bg-white/5 text-neutral-300 hover:bg-white/10 hover:text-white"
            aria-label="Fermer le mode vocal"
        >
            <X size={16} />
        </button>

        <div in:scale={{ duration: 320, start: 0.8 }} class="relative">
            <span
                class="orb"
                class:listening
                class:speaking={streaming && !muted}
            ></span>
            <span class="relative z-10 grid place-items-center">
                <Logo size={140} glow animated />
            </span>
        </div>

        <p class="mt-10 max-w-xl px-6 text-center text-base text-neutral-200 min-h-[3rem]">
            {#if error}
                <span class="text-red-400">⚠ {error}</span>
            {:else if listening}
                {partial || lastFinal || 'À l’écoute…'}
            {:else if streaming}
                <span class="text-cyan-300">Spouet répond…</span>
            {:else if !sttOk}
                <span class="text-amber-300">
                    La reconnaissance vocale n’est pas supportée par ce navigateur.
                </span>
            {:else}
                Appuyez sur Espace ou sur le micro pour parler.
            {/if}
        </p>

        <div class="mt-8 flex items-center gap-4">
            <button
                type="button"
                onclick={toggleMute}
                disabled={!ttsOk}
                title={muted ? 'Réactiver la voix' : 'Couper la voix'}
                aria-label={muted ? 'Réactiver la voix' : 'Couper la voix'}
                class="grid h-12 w-12 place-items-center rounded-full
                       border border-white/10 bg-white/5 text-neutral-200
                       transition hover:bg-white/10 disabled:opacity-30"
            >
                {#if muted}
                    <VolumeX size={18} />
                {:else}
                    <Volume2 size={18} />
                {/if}
            </button>

            <button
                type="button"
                onclick={toggleListen}
                disabled={!sttOk || streaming}
                aria-pressed={listening}
                aria-label={listening ? 'Arrêter l’écoute' : 'Commencer à parler'}
                class="grid h-16 w-16 place-items-center rounded-full text-white shadow-xl
                       transition-transform active:scale-95 disabled:opacity-40
                       {listening
                    ? 'bg-gradient-to-br from-rose-500 to-rose-700'
                    : 'bg-gradient-to-br from-cyan-500 to-cyan-700'}"
            >
                {#if listening}
                    <MicOff size={22} />
                {:else}
                    <Mic size={22} />
                {/if}
            </button>

            <span class="grid h-12 w-12 place-items-center rounded-full text-[10px] text-neutral-500">
                Esc
            </span>
        </div>

        <p class="mt-6 text-[10px] uppercase tracking-widest text-neutral-600">
            Espace : parler · Esc : fermer
        </p>
    </div>
{/if}

<style>
    .orb {
        position: absolute;
        inset: -40px;
        border-radius: 9999px;
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.18 210 / 0.45),
            oklch(0.55 0.18 210 / 0.15) 55%,
            transparent 75%
        );
        filter: blur(18px);
        animation: idle-pulse 4s ease-in-out infinite;
        pointer-events: none;
    }
    .orb.listening {
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.22 20 / 0.55),
            oklch(0.55 0.2 20 / 0.2) 55%,
            transparent 75%
        );
        animation: listen-pulse 1.1s ease-in-out infinite;
    }
    .orb.speaking {
        background: radial-gradient(
            closest-side,
            oklch(0.78 0.2 200 / 0.6),
            oklch(0.6 0.18 210 / 0.2) 55%,
            transparent 75%
        );
        animation: speak-pulse 0.65s ease-in-out infinite;
    }
    @keyframes idle-pulse {
        0%,
        100% {
            transform: scale(1);
            opacity: 0.7;
        }
        50% {
            transform: scale(1.06);
            opacity: 1;
        }
    }
    @keyframes listen-pulse {
        0%,
        100% {
            transform: scale(0.95);
            opacity: 0.85;
        }
        50% {
            transform: scale(1.18);
            opacity: 1;
        }
    }
    @keyframes speak-pulse {
        0%,
        100% {
            transform: scale(1);
            opacity: 0.85;
        }
        50% {
            transform: scale(1.12);
            opacity: 1;
        }
    }
</style>
